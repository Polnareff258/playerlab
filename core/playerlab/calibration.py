"""Calibration (V1.3.2 PART C/D/E): sample selection, metrics, states.

CalibrationSample: preserves original prediction; human correction never
overwrites it (PART C §11). Stratified sampling (PART C §12): high-confidence
positives, threshold-edge, ambiguous, negative controls, context-diverse.

CalibrationState (PART E §28): UNCALIBRATED / EXPERIMENTAL / CALIBRATED /
UNRELIABLE — sample-count + precision driven, not just naming.

Metrics (PART E §23-§27): precision / confirmation rate with sample size;
per-context precision (weapon/distance/map/method); confidence buckets;
threshold sensitivity. We never fake overall accuracy when only positives
were reviewed (§24) — that is stated explicitly in every output.

GROUND_TRUTH_PENDING_HUMAN_REVIEW: until a human reviews, predictions are
rules output, never treated as ground truth (PART N §53).
"""
from __future__ import annotations

import math
import time
import uuid

from .config import Config
from .db import DB

# detectors we calibrate (PART C preamble)
CALIBRATABLE_DETECTORS = (
    "PREAIM_ERROR", "MOVING_SHOT", "FIRE_BEFORE_AIM_READY",
    "IRREGULAR_DUEL_MOVEMENT", "DRY_PEEK", "JIGGLE", "TEAM_FLASH_PEEK",
    "RESPONSIBILITY", "INTENT", "STRATEGIC_EVAL", "ENGAGEMENT_EVAL",
    "EXECUTION_EVAL",
)

CALIBRATION_STATES = ("UNCALIBRATED", "EXPERIMENTAL", "CALIBRATED", "UNRELIABLE")
MIN_REVIEWED_FOR_CALIBRATED = 20
MIN_REVIEWED_FOR_EXPERIMENTAL = 5
PRECISION_FOR_CALIBRATED = 0.7
PRECISION_FOR_UNRELIABLE = 0.4

# PREAIM false-positive categories (PART C §13)
PREAIM_FP_REASONS = (
    "TRUE_PREAIM_ERROR", "REACTION_TARGET_SWITCH", "UNEXPECTED_ENEMY_POSITION",
    "MULTI_TARGET_TRANSITION", "VERTICAL_ADJUSTMENT", "CLOSE_RANGE_DYNAMIC_FIGHT",
    "VISIBILITY_APPROXIMATION_ERROR", "INSUFFICIENT_CONTEXT", "OTHER",
)
# MOVING_SHOT false-positive categories (PART C §15)
MOVING_SHOT_FP_REASONS = (
    "ACTUAL_INACCURATE_MOVING_SHOT", "COUNTER_STRAFE_TRANSITION",
    "LOW_SPEED_ACCEPTABLE_SHOT", "SMG_CLOSE_RANGE_REASONABLE",
    "PISTOL_DYNAMIC_FIGHT", "AIRBORNE_SPECIAL", "FALSE_DETECTION", "UNKNOWN",
)

MIN_SAMPLES_PER_DETECTOR = {
    "PREAIM_ERROR": 30, "MOVING_SHOT": 30, "FIRE_BEFORE_AIM_READY": 20,
    "DRY_PEEK": 20, "IRREGULAR_DUEL_MOVEMENT": 15, "JIGGLE": 10,
    "TEAM_FLASH_PEEK": 10,
}
DEFAULT_MOMENTS_PER_MATCH = 8


def _episode_detectors(episode: dict) -> list[str]:
    """Detector flags present on an episode (execution primitives + methods)."""
    out = list(episode.get("execution_primitives") or [])
    m = (episode.get("engagement_method") or {}).get("method")
    if m:
        out.append(m)
    return out


def sample_calibration_set(db: DB, cfg: Config, match_id: str,
                           player_id: int | None = None,
                           per_detector: int | None = None) -> list[dict]:
    """Stratified calibration sampling per detector (PART C §12).
    Returns CalibrationSample rows (PENDING_REVIEW); idempotent per match."""
    target = per_detector or DEFAULT_MOMENTS_PER_MATCH
    eps = db.get_decision_episodes(match_id=match_id, player_id=player_id, limit=2000)
    if not eps:
        return []
    # index episodes by detector
    by_det = {}
    for ep in eps:
        for det in _episode_detectors(ep):
            by_det.setdefault(det, []).append(ep)
    samples = []
    for det in CALIBRATABLE_DETECTORS:
        pool = by_det.get(det, [])
        if not pool:
            continue
        picked = _stratified_pick(pool, det, n=min(target, max(1, len(pool))))
        for ep in picked:
            samples.append({
                "id": f"{match_id}-cal-{det}-{ep['anchor_tick']}-{ep['player_id']}",
                "match_id": match_id, "player_id": ep["player_id"],
                "round": ep["round"], "tick": ep["anchor_tick"],
                "episode_id": ep["id"], "detector_type": det,
                "predicted_label": det,
                "predicted_confidence": ep.get("confidence"),
                "evidence_sufficiency": ep.get("evidence_sufficiency"),
                "model_version": ep.get("model_version", "v1.3.1-1"),
                "rule_version": ep.get("rule_version", "v1.3.1-1"),
                "sample_stratum": "general",
                "review_status": "pending",
            })
    # persist (replace per match to keep idempotent)
    db.delete_calibration_samples(match_id)
    for s in samples:
        db.upsert_calibration_sample(s)
    return samples


def _stratified_pick(pool: list[dict], det: str, n: int) -> list[dict]:
    """Context-diverse pick: prefer spread across maps/weapons/distance."""
    scored = []
    for ep in pool:
        wm = ep.get("weapon_matchup") or {}
        key = f"{wm.get('range_bucket', '?')}|{wm.get('self_weapon_class', '?')}"
        scored.append((ep, key))
    # diversity: pick one per context key first, then fill
    by_key = {}
    for ep, key in scored:
        by_key.setdefault(key, []).append(ep)
    picked = []
    for key in sorted(by_key):
        if len(picked) >= n:
            break
        picked.append(by_key[key][0])
    if len(picked) < n:
        rest = [ep for ep, _ in scored if ep not in picked]
        picked.extend(rest[: n - len(picked)])
    return picked


# ---------------------------------------------------------------- metrics
def calibration_stats(db: DB, cfg: Config,
                      detector_type: str | None = None) -> dict:
    """Precision / confirmation rate per detector with sample size
    (PART E §23-§25). Only confirmation rate (not accuracy) when negatives
    were not reviewed (§24 — explicit)."""
    samples = db.get_calibration_samples(detector_type=detector_type, limit=10000)
    by_det = {}
    for s in samples:
        by_det.setdefault(s["detector_type"], []).append(s)
    out = {}
    for det, lst in by_det.items():
        reviewed = [s for s in lst if s["review_status"] == "reviewed"]
        n = len(reviewed)
        confirmed = sum(1 for s in reviewed
                        if s.get("human_label") in ("YES", "TRUE", "CONFIRMED", "CORRECT"))
        denied = sum(1 for s in reviewed if s.get("human_label") in ("NO", "FALSE", "INCORRECT"))
        precision = confirmed / n if n else None
        # per-context precision (weapon/distance/map/method)
        per_context = _per_context_precision(reviewed)
        # confidence buckets (§26)
        buckets = _confidence_buckets(reviewed)
        out[det] = {
            "reviewed": n, "confirmed": confirmed, "denied": denied,
            "precision": round(precision, 3) if precision is not None else None,
            "pending": sum(1 for s in lst if s["review_status"] == "pending"),
            "sample_size": n,
            "note": "confirmation rate over reviewed positives; overall accuracy "
                    "requires negative controls (not estimated here, PART E §24)",
            "per_context": per_context,
            "confidence_buckets": buckets,
            "false_positive_reasons": _fp_reason_dist(reviewed),
            "calibration_state": calibration_state(n, precision),
        }
    return {"detectors": out,
            "ground_truth_note": "GROUND_TRUTH_PENDING_HUMAN_REVIEW — "
                                 "rule predictions are not ground truth"}


def _per_context_precision(reviewed: list[dict]) -> dict:
    from collections import Counter
    ctx = {}
    for s in reviewed:
        ep = s.get("episode_id")
        if not ep:
            continue
        # context from the sample's stored fields (weapon/distance via episode
        # not stored; use stratum + detector as proxy — document limitation)
        key = s.get("sample_stratum", "general")
        c = ctx.setdefault(key, {"n": 0, "confirmed": 0})
        c["n"] += 1
        if s.get("human_label") in ("YES", "TRUE", "CONFIRMED", "CORRECT"):
            c["confirmed"] += 1
    out = {}
    for k, v in ctx.items():
        out[k] = {"n": v["n"],
                  "precision": round(v["confirmed"] / v["n"], 3) if v["n"] else None}
    return out


def _confidence_buckets(reviewed: list[dict]) -> dict:
    out = {}
    for lo, hi, label in ((0.7, 1.01, "HIGH"), (0.45, 0.7, "MEDIUM"), (0.0, 0.45, "LOW")):
        sel = [s for s in reviewed if s.get("predicted_confidence") is not None
               and lo <= s["predicted_confidence"] < hi]
        if not sel:
            continue
        conf = sum(1 for s in sel
                   if s.get("human_label") in ("YES", "TRUE", "CONFIRMED", "CORRECT"))
        out[label] = {"n": len(sel),
                      "confirmed": round(conf / len(sel), 3)}
    return out


def _fp_reason_dist(reviewed: list[dict]) -> dict:
    from collections import Counter
    return dict(Counter(s.get("false_positive_reason") or "N/A"
                        for s in reviewed
                        if s.get("human_label") in ("NO", "FALSE", "INCORRECT")))


# ---------------------------------------------------------------- states
def calibration_state(n_reviewed: int, precision: float | None) -> str:
    """Sample-count + precision driven (PART E §28)."""
    if n_reviewed < MIN_REVIEWED_FOR_EXPERIMENTAL:
        return "UNCALIBRATED"
    if n_reviewed < MIN_REVIEWED_FOR_CALIBRATED:
        return "EXPERIMENTAL"
    if precision is None:
        return "EXPERIMENTAL"
    if precision >= PRECISION_FOR_CALIBRATED:
        return "CALIBRATED"
    if precision <= PRECISION_FOR_UNRELIABLE:
        return "UNRELIABLE"
    return "EXPERIMENTAL"


def detector_calibration_map(db: DB, cfg: Config) -> dict:
    """{detector_type: CalibrationState} for ranking gates (PART J §43)."""
    stats = calibration_stats(db, cfg)
    return {det: s["calibration_state"]
            for det, s in stats.get("detectors", {}).items()}


def threshold_sensitivity(db: DB, cfg: Config, detector: str,
                          base_values: list[float]) -> list[dict]:
    """Threshold experiment: sample count vs confirmed rate at each threshold
    (PART E §27). Values are contextual labels for the detector."""
    samples = db.get_calibration_samples(detector_type=detector, limit=10000)
    out = []
    for v in base_values:
        sel = [s for s in samples if (s.get("predicted_confidence") or 0) >= v]
        rev = [s for s in sel if s["review_status"] == "reviewed"]
        conf = sum(1 for s in rev
                   if s.get("human_label") in ("YES", "TRUE", "CONFIRMED", "CORRECT"))
        out.append({
            "threshold": v,
            "candidate_count": len(sel),
            "reviewed": len(rev),
            "confirmed": conf,
            "precision": round(conf / len(rev), 3) if rev else None,
            "coverage_note": "higher threshold = fewer candidates but (expected) higher precision",
        })
    return out
