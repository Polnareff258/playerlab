"""Geometry A/B experiment (V1.3.3 PART I/J/S): OFF vs ON comparison on the
SAME demos, SAME detector version, SAME thresholds — the ONLY variable is the
GeometryProvider.

Episode-level diff (PART I §27): geometry_off_label vs geometry_on_label,
confidence, and reason_changed. We never claim HIGH-more = more-correct
(§28): the human-agreement check (PART J §30) is the arbiter.

Reproducibility (PART S): every run records experiment_id / config_hash /
git_commit / demo_hash / geometry_version / detector_version.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time
import uuid

from .config import Config
from .db import DB
from .ingest import parse_demo
from .episode import run_episodes
from .evidence import evidence_sufficiency
from .geometry import get_geometry


def config_hash(cfg: Config) -> str:
    """Deterministic hash of the config that affects decisions."""
    import dataclasses
    d = dataclasses.asdict(cfg)
    # drop paths / runtime noise; keep decision-relevant thresholds
    for k in ("data_dir", "db_path", "csnet_models_dir", "csnet_repo_dir"):
        d.pop(k, None)
    return hashlib.sha256(json.dumps(d, sort_keys=True, default=str)
                          .encode()).hexdigest()[:16]


def git_commit() -> str:
    try:
        r = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True,
                           text=True, cwd=os.path.dirname(os.path.dirname(
                               os.path.abspath(__file__))))
        if r.returncode == 0:
            return r.stdout.strip()[:16]
    except Exception:  # noqa: BLE001
        pass
    return "unknown"


def demo_hash(demo_path: str) -> str:
    try:
        h = hashlib.sha256()
        with open(demo_path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()[:16]
    except Exception:  # noqa: BLE001
        return "unknown"


def run_geometry_mode(demo_path: str, cfg: Config, db: DB,
                      mode: str = "off",
                      geometry_kwargs: dict | None = None) -> dict:
    """Run the episode pipeline in ONE geometry mode. mode: 'off' (Null) or
    'on' (awpy). Episodes are persisted with geometry_mode tagged so the
    OFF/ON results can be diffed per episode_id (PART I §25-§27)."""
    if mode == "on":
        cfg.geometry_provider = "awpy"
        if geometry_kwargs:
            cfg.geometry_nav_dir = geometry_kwargs.get("nav_dir", cfg.geometry_nav_dir)
            cfg.geometry_tri_dir = geometry_kwargs.get("tri_dir", cfg.geometry_tri_dir)
    else:
        cfg.geometry_provider = "null"
    geometry = get_geometry(cfg.geometry_provider,
                            nav_dir=cfg.geometry_nav_dir or None,
                            tri_dir=cfg.geometry_tri_dir or None)

    demo = parse_demo(demo_path, cfg)
    run_episodes(demo, cfg, db, model_provider=None)

    eps = db.get_decision_episodes(match_id=demo.demo_id, limit=2000)
    # tag geometry mode + provider metadata on each episode (provenance)
    meta = geometry.get_metadata()
    for e in eps:
        db.conn.execute(
            "UPDATE decision_episodes SET geometry_version=? WHERE id=?",
            (meta.get("geometry_source"), e["id"]))
    db.conn.commit()

    run_id = f"{mode}-{uuid.uuid4().hex[:8]}"
    db.upsert_experiment_run({
        "experiment_id": run_id, "mode": mode,
        "config_hash": config_hash(cfg), "git_commit": git_commit(),
        "demo_hash": demo_hash(demo_path),
        "geometry_version": meta.get("geometry_source"),
        "detector_version": "v1.3.1-1",
        "episodes_processed": len(eps),
        "notes": f"geometry_{mode} mode on {demo_path}",
    })
    return {"run_id": run_id, "mode": mode, "episodes": len(eps),
            "geometry": meta}


def diff_geometry_ab(db: DB, cfg: Config, demo_path: str,
                     geometry_kwargs: dict | None = None,
                     human_labels: dict | None = None) -> dict:
    """Full OFF/ON A/B on one demo (PART I §26-§29, PART J §30):
    - run both modes
    - episode-level diff (label/confidence/reason_changed)
    - sufficiency upgrade rate (MEDIUM->HIGH etc.)
    - decision flips (GOOD->QUESTIONABLE etc.)
    - human-agreement check when human labels exist for the episodes
    """
    demo = parse_demo(demo_path, cfg)
    demo_id = demo.demo_id
    db.delete_decision_episodes(demo_id)

    off = run_geometry_mode(demo_path, cfg, db, mode="off")
    eps_off = {e["id"]: e for e in db.get_decision_episodes(match_id=demo_id, limit=2000)}

    db.delete_decision_episodes(demo_id)
    on = run_geometry_mode(demo_path, cfg, db, mode="on", geometry_kwargs=geometry_kwargs)
    eps_on = {e["id"]: e for e in db.get_decision_episodes(match_id=demo_id, limit=2000)}

    diffs = []
    suff_upgrades = {"MEDIUM_TO_HIGH": 0, "LOW_TO_MEDIUM": 0, "unchanged": 0}
    flips = {}
    for eid in sorted(set(eps_off) & set(eps_on)):
        a, b = eps_off[eid], eps_on[eid]
        sa, sb = a.get("evidence_sufficiency"), b.get("evidence_sufficiency")
        if sa != sb:
            key = f"{sa}_TO_{sb}"
            suff_upgrades[key] = suff_upgrades.get(key, 0) + 1
        else:
            suff_upgrades["unchanged"] += 1
        eval_a, eval_b = a.get("decision_evaluation"), b.get("decision_evaluation")
        if eval_a != eval_b:
            fk = f"{eval_a}_TO_{eval_b}"
            flips[fk] = flips.get(fk, 0) + 1
        # sufficiency-driven eligibility change
        eligible_a = sa in ("HIGH", "MEDIUM")
        eligible_b = sb in ("HIGH", "MEDIUM")
        reason = None
        if eligible_a != eligible_b:
            reason = f"sufficiency {sa} -> {sb}"
        elif eval_a != eval_b:
            reason = f"evaluation {eval_a} -> {eval_b}"
        diffs.append({
            "episode_id": eid,
            "geometry_off_label": eval_a, "geometry_on_label": eval_b,
            "geometry_off_sufficiency": sa, "geometry_on_sufficiency": sb,
            "reason_changed": reason,
            "geometry_off_confidence": a.get("confidence"),
            "geometry_on_confidence": b.get("confidence"),
        })

    # PART J §30: human agreement vs OFF/ON (only for episodes with labels)
    human_agreement = {}
    if human_labels:
        for eid, human in human_labels.items():
            if eid in eps_off and eid in eps_on:
                agree_off = _agrees(human, eps_off[eid])
                agree_on = _agrees(human, eps_on[eid])
                human_agreement[eid] = {"human": human,
                                        "off_agree": agree_off,
                                        "on_agree": agree_on,
                                        "off_label": eps_off[eid].get("decision_evaluation"),
                                        "on_label": eps_on[eid].get("decision_evaluation")}

    total = len(diffs)
    changed = sum(1 for d in diffs if d["reason_changed"])
    return {
        "experiment": {
            "demo": demo_id, "demo_hash": demo_hash(demo_path),
            "config_hash": config_hash(cfg), "git_commit": git_commit(),
            "geometry_version": on.get("geometry", {}).get("geometry_source"),
            "detector_version": "v1.3.1-1",
            "partial_geometry": on.get("geometry", {}).get("geometry_quality") == "none",
        },
        "runs": {"off": off["run_id"], "on": on["run_id"]},
        "episodes_total": total,
        "episodes_changed": changed,
        "change_rate": round(changed / total, 3) if total else None,
        "sufficiency_upgrades": suff_upgrades,
        "decision_flips": flips,
        "episode_diffs": diffs,
        "human_agreement": human_agreement,
        "honest_note": ("GEOMETRY_AB_PENDING_ASSETS" if total == 0 else
                        "NO_VALIDATED_ACCURACY_GAIN" if human_agreement and
                        not any(v["on_agree"] and not v["off_agree"] for v in
                                human_agreement.values()) else None),
    }


def _agrees(human_label: str, episode: dict) -> bool:
    """Does the human label agree with the episode evaluation? (coarse)"""
    ev = episode.get("decision_evaluation")
    if human_label in ("GOOD", "REASONABLE"):
        return ev in ("GOOD", "REASONABLE")
    if human_label in ("QUESTIONABLE", "POOR"):
        return ev in ("QUESTIONABLE", "POOR")
    return False
