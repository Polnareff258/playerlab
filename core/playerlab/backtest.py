"""Backtest harness (BACKTEST_DESIGN.md): historical holdout, retrieval QA
export, feature ablation. Deterministic; results land in backtest/ artifacts.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass

from .config import Config
from .db import DB
from .features import NUMERIC_FEATURES
from .stats import brier, calibration_bins, max_calibration_deviation

ABLATION_SUBSETS = {
    "position_only": ["time_left"],
    "position_plus_time": ["time_left", "alive_diff", "hp"],
    "plus_team": ["time_left", "alive_diff", "hp", "teammate_near", "teammate_mid"],
    "plus_state": ["time_left", "alive_diff", "hp", "teammate_near", "teammate_mid",
                   "n_known_enemies", "known_spread", "nearest_known_enemy", "economy"],
    "full": list(NUMERIC_FEATURES),
}


def holdout(db: DB, cfg: Config, test_match_ids: list[str] | None = None) -> dict:
    """Leave-one-match-out: predict observed-action survival from other matches."""
    states = db.all_states()
    by_match: dict[str, list[dict]] = {}
    for s in states:
        by_match.setdefault(s["match_id"], []).append(s)
    test_ids = test_match_ids or [m for m, ss in by_match.items() if len(ss) >= 3]
    preds, ys = [], []
    per_match = []
    for mid in test_ids:
        train = [s for m, ss in by_match.items() if m != mid for s in ss]
        if len(train) < 2:
            continue
        m_preds, m_ys = [], []
        for s in by_match[mid]:
            o = db.get_outcome(s["dp_id"])
            if not o or o["survival"] is None:
                continue
            qf, ql = s["features"], s["labels"]
            cands = []
            for t in train:
                if not _hf(ql, t["labels"], cfg):
                    continue
                if t["labels"].get("action") != ql.get("action"):
                    continue
                score = _soft(qf, t["features"], ql, t["labels"], cfg)
                cands.append(score)
            if len(cands) < cfg.n_min_action:
                continue
            cands.sort(reverse=True)
            top = cands[:cfg.top_k]
            p = sum(top) / len(top)  # similarity-weighted proxy of survival propensity
            m_preds.append(p)
            m_ys.append(float(o["survival"]))
        if len(m_preds) >= 3:
            per_match.append({"match_id": mid, "n": len(m_preds),
                              "brier": round(brier(m_preds, m_ys), 4),
                              "max_calib_dev_pp": round(
                                  max_calibration_deviation(calibration_bins(m_preds, m_ys)), 2)})
        preds += m_preds
        ys += m_ys
    bins = calibration_bins(preds, ys)
    return {
        "n_predictions": len(preds),
        "brier": round(brier(preds, ys), 4),
        "baseline_brier": round(brier([sum(ys) / len(ys)] * len(ys), ys), 4) if ys else None,
        "calibration_bins": bins,
        "max_calibration_deviation_pp": round(max_calibration_deviation(bins), 2),
        "pass_threshold": cfg.calib_max_dev_pp,
        "per_match": per_match,
    }


def _hf(a, b, cfg):
    if cfg.hard_filter_map and a.get("map") and b.get("map") and a["map"] != b["map"]:
        return False
    if cfg.hard_filter_side and a.get("side") and b.get("side") and a["side"] != b["side"]:
        return False
    if cfg.hard_filter_zone and a.get("zone") and b.get("zone") and a["zone"] != b["zone"]:
        return False
    return True


def _soft(qf, cf, ql, cl, cfg):
    weights = cfg.soft_weights
    num_w = sum(v for k, v in weights.items() if k in NUMERIC_FEATURES and k in qf and k in cf)
    total = num_w + weights.get("weapon_class", 0.0)
    if total <= 0:
        return 0.0
    score = sum(w * (1.0 - min(1.0, abs(qf[k] - cf[k])))
                for k in NUMERIC_FEATURES
                if (w := weights.get(k)) and k in qf and k in cf)
    if ql.get("weapon_class") and cl.get("weapon_class"):
        score += weights.get("weapon_class", 0.0) * (1.0 if ql["weapon_class"] == cl["weapon_class"] else 0.0)
    return score / total


def qa_export(db: DB, cfg: Config, out_path: str, n_queries: int = 60) -> str:
    """Stratified retrieval-QA batch (BACKTEST_DESIGN §3). Score fields blank."""
    from .counterfactual import retrieve
    states = db.all_states()
    cells = {}
    for s in states:
        key = (s["map"], s["side"], s["zone"], s["labels"].get("action"))
        cells.setdefault(key, []).append(s)
    queries = []
    for key, ss in cells.items():
        queries.extend(ss[:max(1, n_queries // max(1, len(cells)))])
    queries = queries[:n_queries]
    batch = []
    for s in queries:
        top = retrieve(db, cfg, s, mode="counterfactual", k=cfg.qa_topk, exclude_match=False)
        batch.append({
            "query": {"dp_id": s["dp_id"], "match_id": s["match_id"], "round": s["round"],
                      "tick": s["decision_tick"], "action": s["labels"].get("action"),
                      "map": s["map"], "side": s["side"], "zone": s["zone"],
                      "features": s["features"], "labels": s["labels"]},
            "top_k": [{"dp_id": c["dp_id"], "match_id": c["match_id"], "round": c["round"],
                       "tick": c["tick"], "action": c["action"], "score": c["score"],
                       "features": c["state"]["features"], "labels": c["state"]["labels"],
                       "score_1_5": None} for c in top],
        })
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(batch, fh, ensure_ascii=False, indent=1)
    return out_path


def ablation(db: DB, cfg: Config) -> dict:
    """Feature-subset ablation on holdout Brier (BACKTEST_DESIGN §4)."""
    from copy import deepcopy
    out = {}
    for name, feats in ABLATION_SUBSETS.items():
        c2 = deepcopy(cfg)
        weights = {k: (1.0 if k in feats else 0.0) for k in NUMERIC_FEATURES}
        weights["weapon_class"] = 1.0 if name in ("full", "plus_state") else 0.0
        c2.soft_weights = weights
        out[name] = holdout(db, c2)
    return out
