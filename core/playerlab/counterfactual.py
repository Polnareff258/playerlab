"""Counterfactual engine: retrieval -> group by action -> outcome stats with
Wilson CI -> evidence strength -> fixed verdicts (no LLM, no fabrication).

Retrieval modes (COUNTERFACTUAL_DESIGN §4 refinement):
- counterfactual: NO action filter, group by action afterwards;
- same_action: only states with the observed action (baseline distribution).
"""
from __future__ import annotations

import math

from .config import Config
from .db import DB
from .features import hard_match, soft_score
from .stats import wilson_ci

VERDICT_OK = "COMPARISON_AVAILABLE"
VERDICT_INSUFFICIENT = "INSUFFICIENT_EVIDENCE"


def retrieve(db: DB, cfg: Config, query_state: dict, mode: str = "counterfactual",
             k: int | None = None, exclude_match: bool | None = None) -> list[dict]:
    k = k or cfg.top_k
    if exclude_match is None:
        exclude_match = cfg.exclude_same_match
    qf, ql = query_state["features"], query_state["labels"]
    cands = []
    for s in db.all_states():
        if s["dp_id"] == query_state["dp_id"]:
            continue  # never retrieve the query itself
        if exclude_match and s["match_id"] == query_state["match_id"]:
            continue
        if not hard_match(ql, s["labels"], cfg):
            continue
        if mode == "same_action" and s["labels"].get("action") != ql.get("action"):
            continue
        score = soft_score(qf, s["features"], ql, s["labels"], cfg)
        cands.append({"dp_id": s["dp_id"], "match_id": s["match_id"],
                      "round": s["round"], "tick": s["decision_tick"],
                      "action": s["labels"].get("action"),
                      "score": round(score, 4), "state": s})
    cands.sort(key=lambda c: c["score"], reverse=True)
    return cands[:k]


def _action_stats(db: DB, dp_ids: list[str]) -> dict:
    surv_k = surv_n = rw_k = rw_n = 0
    duel = {"won": 0, "lost": 0, "undefined": 0}
    for dp_id in dp_ids:
        o = db.get_outcome(dp_id)
        if not o:
            continue
        surv_n += 1
        surv_k += 1 if o["survival"] else 0
        rw_n += 1
        rw_k += 1 if o["round_win"] else 0
        duel[o.get("duel_result", "undefined")] = duel.get(o.get("duel_result", "undefined"), 0) + 1
    surv = wilson_ci(surv_k, surv_n)
    rw = wilson_ci(rw_k, rw_n)
    return {"n": surv_n, "survival": surv[0], "survival_ci": [surv[1], surv[2]],
            "round_win": rw[0], "round_win_ci": [rw[1], rw[2]], "duel": duel}


def _ci_overlap(a: list, b: list) -> bool:
    return not (a[1] < b[0] or b[1] < a[0])


def what_if(db: DB, cfg: Config, dp_id: str, k: int | None = None,
            include_same: bool = False) -> dict:
    state = db.get_state(dp_id)
    if not state:
        return {"dp_id": dp_id, "error": "decision state not found"}
    outcome = db.get_outcome(dp_id)
    observed = state["labels"].get("action")

    cands = retrieve(db, cfg, state, mode="counterfactual", k=k,
                     exclude_match=not include_same)
    by_action: dict[str, list[str]] = {}
    for c in cands:
        by_action.setdefault(c["action"], []).append(c["dp_id"])

    actions = {}
    for action, ids in by_action.items():
        actions[action] = _action_stats(db, ids)
        actions[action]["high_sim_n"] = sum(1 for c in cands if c["action"] == action and c["score"] >= 0.85)
        actions[action]["sample_dp_ids"] = ids[:10]

    # verdicts
    total = len(cands)
    verdict = VERDICT_OK
    missing = []
    if total < cfg.n_min_claim:
        verdict = VERDICT_INSUFFICIENT
        missing.append(f"total similar states {total} < n_min_claim {cfg.n_min_claim}")
    for a in actions:
        if a not in (observed,) and actions[a]["n"] < cfg.n_min_action:
            actions[a]["verdict"] = "NO_COMPARABLE_ALTERNATIVE"
    alt_with_samples = [a for a in actions if a != observed and actions[a]["n"] >= cfg.n_min_action]
    if verdict == VERDICT_OK:
        if not alt_with_samples:
            # observed-action stats are valid, but no alternative is comparable
            verdict = "NO_COMPARABLE_ALTERNATIVE"
            missing.append("no alternative action has sufficient historical samples")

    comparisons = []
    obs = actions.get(observed)
    if obs and obs["n"] >= cfg.n_min_action:
        for a in alt_with_samples:
            alt = actions[a]
            overlap = _ci_overlap(obs["survival_ci"], alt["survival_ci"])
            comparisons.append({
                "observed": observed, "alternative": a,
                "survival_obs": obs["survival"], "survival_alt": alt["survival"],
                "survival_ci_obs": obs["survival_ci"], "survival_ci_alt": alt["survival_ci"],
                "ci_overlap": overlap,
                "note": "NO_RELIABLE_DIFFERENCE" if overlap else None,
            })

    # confidence heuristic
    high_sim = sum(1 for c in cands if c["score"] >= 0.85)
    ci_widths = [a["survival_ci"][1] - a["survival_ci"][0] for a in actions.values()]
    avg_ci = sum(ci_widths) / len(ci_widths) if ci_widths else 1.0
    conf = 0.15 + 0.20 * math.log10(total + 1) + 0.25 * (high_sim / max(1, total)) - 0.5 * avg_ci
    conf = max(0.0, min(0.95, conf))

    sim_scores = [c["score"] for c in cands]
    result = {
        "dp_id": dp_id, "observed_action": observed, "verdict": verdict,
        "evidence_strength": {
            "n_similar_states": total, "high_similarity_n": high_sim,
            "similarity_distribution": {
                "min": round(min(sim_scores), 3) if sim_scores else None,
                "mean": round(sum(sim_scores) / len(sim_scores), 3) if sim_scores else None,
                "max": round(max(sim_scores), 3) if sim_scores else None,
                "p50": round(sorted(sim_scores)[len(sim_scores) // 2], 3) if sim_scores else None,
            },
            "action_sample_counts": {a: v["n"] for a, v in actions.items()},
            "confidence": round(conf, 3),
            "confounders": ["map/side/zone matched", "sample composition may skew (see backtest)",
                            "no geometric LOS in V1 vision model"],
            "missing_information": missing,
        },
        "actions": actions,
        "comparisons": comparisons,
        "outcome_actual": outcome,
        "top_similar": [{"dp_id": c["dp_id"], "match_id": c["match_id"], "round": c["round"],
                         "tick": c["tick"], "action": c["action"], "score": c["score"]}
                        for c in cands[:10]],
    }
    return result
