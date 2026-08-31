"""Alpha pipeline driver: execution metrics -> pattern detection -> root
causes -> pattern aggregation -> bottleneck ranking -> training targets ->
review queue. Called per match (via batch or CLI `alpha`).
"""
from __future__ import annotations

from .config import Config
from .db import DB
from .ingest import IngestedDemo
from .state import build_tick_index
from .execution import compute_shot_metrics
from .patterns import (detect_repeek, detect_move_shoot, detect_advantage,
                       aggregate_patterns, counterfactual_support)
from .rootcause import build_root_causes
from .bottleneck import rank_bottlenecks
from .training import generate_targets, validate_targets
from .annotation import build_review_queue, persist_review_queue


def _persist_samples(db: DB, demo_id: str, pattern_type: str, samples: list[dict]):
    items = []
    for s in samples:
        if pattern_type == "repeek":
            kind = "violation" if s["evaluation"] in ("POOR", "QUESTIONABLE") else "positive"
        elif pattern_type == "move_shoot":
            kind = "violation" if s["evaluation"] == "POOR" else "positive"
        else:
            kind = "violation" if s["classification"] == "POSSIBLE_ADVANTAGE_OVERAGGRESSION" else "positive"
        items.append({"kind": kind, "round": s.get("round"), "tick": s.get("tick"),
                      "dp_id": s.get("dp_id"), "detail": s})
    db.replace_pattern_evidence(f"alpha-{pattern_type}", demo_id, items)


def run_alpha(demo: IngestedDemo, cfg: Config, db: DB) -> dict:
    """Run the whole alpha analysis for one freshly-ingested demo."""
    idx = build_tick_index(demo)
    demo_id = demo.demo_id

    # 1) execution metrics
    metrics = compute_shot_metrics(demo, cfg, idx)
    db.replace_execution_metrics(demo_id, metrics)

    # 2) patterns (counterfactual support computed before sample evaluation)
    cf = counterfactual_support(db, cfg, "repeek")
    rep_samples = detect_repeek(demo, cfg, db, idx, cf)
    ms_samples = detect_move_shoot(demo, cfg, db)
    adv_samples = detect_advantage(demo, cfg, db, idx)
    _persist_samples(db, demo_id, "repeek", rep_samples)
    _persist_samples(db, demo_id, "move_shoot", ms_samples)
    _persist_samples(db, demo_id, "advantage", adv_samples)

    # 3) root causes (with V1.2 context / commitment / role / responsibility)
    from .context_pipeline import run_context
    ctx = run_context(demo, cfg, db)
    for rc in build_root_causes(demo, cfg, db, idx, adv_samples,
                                ctx.get("responsibility_map"),
                                ctx.get("commitment_map"), ctx.get("role_map")):
        db.upsert_root_cause(rc)

    # 3b) V1.3 decision episodes (spec §4-§28) + episode patterns (spec §42-§44)
    from .episode import run_episodes
    from .episode_patterns import cluster_episodes
    from .training import generate_targets_from_episodes
    from .model_provider import get_provider
    model_provider = get_provider(cfg.model_provider,
                                  models_dir=cfg.csnet_models_dir or None,
                                  repo_dir=cfg.csnet_repo_dir or None)
    ep_result = run_episodes(demo, cfg, db, model_provider=model_provider)
    episode_patterns = cluster_episodes(db, cfg)
    ep_targets = generate_targets_from_episodes(db, cfg, episode_patterns)

    # 4) aggregation + ranking
    matches_count = len(db.list_matches())
    patterns = [aggregate_patterns(db, cfg, p, matches_count)
                for p in ("repeek", "move_shoot", "advantage")]
    for p in patterns:
        db.upsert_pattern(p)
    bottlenecks = rank_bottlenecks(db, cfg, matches_count)

    # 5) training loop
    targets = generate_targets(db, cfg, bottlenecks)
    validations = validate_targets(db, cfg)

    # 6) review queue (this match only, idempotent)
    db.conn.execute("DELETE FROM review_queue WHERE match_id=?", (demo_id,))
    db.conn.commit()
    items = build_review_queue(db, cfg, demo_id)
    persist_review_queue(db, items)

    return {
        "demo_id": demo_id,
        "execution_metrics": len(metrics),
        "samples": {"repeek": len(rep_samples), "move_shoot": len(ms_samples),
                    "advantage": len(adv_samples)},
        "patterns": patterns,
        "bottlenecks": bottlenecks,
        "targets": targets,
        "validations": validations,
        "review_items": len(items),
        "context": {k: ctx[k] for k in ("context_events", "intent_samples",
                                        "intent_distribution")},
        "episodes": ep_result,
        "episode_patterns": episode_patterns,
        "episode_targets": ep_targets,
    }
