"""Calibration v2 (V1.3.3 PART A/B/C/D/K/L/M): label provenance, dual-state,
human ground-truth workflow.

Hard rules:
- LabelSource: HUMAN / SIMULATED / IMPORTED_EXPERT / CONSENSUS. Only
  HUMAN (and future IMPORTED_EXPERT / CONSENSUS when configured) is
  ground-truth eligible (PART A §2). SIMULATED NEVER drives production
  CalibrationState, TrainingTargets, ReviewMoment reliability, real
  precision, or training sets (PART A §3).
- Dual state (PART B): PipelineValidationState (NOT_TESTED /
  PIPELINE_VALIDATED / PIPELINE_FAILED) reflects that the pipeline runs
  (SIMULATED may validate it); CalibrationState (UNCALIBRATED /
  EXPERIMENTAL / CALIBRATED / UNRELIABLE) reflects human-verified truth
  and is driven ONLY by eligible labels.
- One-to-many annotations (PART L): each annotation is its own row in
  calibration_annotations; sample-level human_label is a derived view.
- ConsensusResolver interface (PART M): default SingleHumanResolver.
- Metrics v2 (PART K): human and simulated counts NEVER merged; positive-
  only review reports precision/confirmation, never accuracy/recall.
- Honest rules (PART V): no human labels -> NO_REAL_CALIBRATION_AVAILABLE;
  too few -> INSUFFICIENT_HUMAN_LABELS. Never substitute simulated.
"""
from __future__ import annotations

import hashlib
import math
import time
import uuid

from .config import Config
from .db import DB

LABEL_SOURCES = ("HUMAN", "SIMULATED", "IMPORTED_EXPERT", "CONSENSUS")
ELIGIBLE_SOURCES = ("HUMAN",)  # future: + IMPORTED_EXPERT, CONSENSUS when configured

PIPELINE_STATES = ("NOT_TESTED", "PIPELINE_VALIDATED", "PIPELINE_FAILED")
CALIBRATION_STATES = ("UNCALIBRATED", "EXPERIMENTAL", "CALIBRATED", "UNRELIABLE")

MIN_REVIEWED_FOR_CALIBRATED = 20      # overridden by cfg.cal_min_for_calibrated
MIN_REVIEWED_FOR_EXPERIMENTAL = 5     # overridden by cfg.cal_min_for_experimental
PRECISION_FOR_CALIBRATED = 0.7        # overridden by cfg.cal_precision_for_calibrated
PRECISION_FOR_UNRELIABLE = 0.4        # overridden by cfg.cal_precision_for_unreliable

CALIBRATABLE_DETECTORS = (
    "PREAIM_ERROR", "MOVING_SHOT", "FIRE_BEFORE_AIM_READY",
    "IRREGULAR_DUEL_MOVEMENT", "DRY_PEEK", "JIGGLE", "TEAM_FLASH_PEEK",
    "RESPONSIBILITY", "INTENT", "STRATEGIC_EVAL", "ENGAGEMENT_EVAL",
    "EXECUTION_EVAL",
)

# PREAIM false-positive / label categories (PART E §16)
PREAIM_LABELS = (
    "REAL_PREAIM_ERROR", "UNEXPECTED_ENEMY_POSITION", "TARGET_SWITCH",
    "MULTI_TARGET_TRANSITION", "CLOSE_RANGE_DYNAMIC_FIGHT",
    "VERTICAL_ADJUSTMENT", "VISIBILITY_APPROXIMATION", "REACTION_ONLY",
    "INSUFFICIENT_CONTEXT", "OTHER", "UNSURE",
)
# MOVING_SHOT label categories (PART F §19)
MOVING_SHOT_LABELS = (
    "ACTUAL_INACCURATE_MOVING_SHOT", "COUNTER_STRAFE_TRANSITION",
    "LOW_SPEED_ACCEPTABLE", "SMG_CLOSE_RANGE_REASONABLE",
    "PISTOL_DYNAMIC_REASONABLE", "SHOTGUN_REASONABLE", "AIRBORNE_SPECIAL",
    "DETECTION_ERROR", "INSUFFICIENT_CONTEXT", "OTHER", "UNSURE",
)
# DRY_PEEK evaluation labels (PART G §22)
DRY_PEEK_LABELS = (
    "REASONABLE_DRY_PEEK", "QUESTIONABLE_DRY_PEEK", "POOR_DRY_PEEK",
    "INSUFFICIENT_CONTEXT", "UNSURE",
)

MIN_SAMPLES_PER_DETECTOR = {
    "PREAIM_ERROR": 30, "MOVING_SHOT": 30, "FIRE_BEFORE_AIM_READY": 20,
    "DRY_PEEK": 20, "IRREGULAR_DUEL_MOVEMENT": 15, "JIGGLE": 10,
    "TEAM_FLASH_PEEK": 10,
}
DEFAULT_MOMENTS_PER_MATCH = 8
NEGATIVE_CONTROL_SHARE = 0.15   # 10-20% quota for negative controls (PART K §32)


def eligible(label_source: str) -> bool:
    return label_source in ELIGIBLE_SOURCES


# ---------------------------------------------------------------- pipeline state
def pipeline_validation_state(samples: list[dict], detector_type: str) -> str:
    """PipelineValidationState (PART B §6): did the pipeline run end-to-end
    (SIMULATED may validate it)? Human labels not required."""
    total = len(samples)
    if total == 0:
        return "NOT_TESTED"
    reviewed = [s for s in samples if s["review_status"] == "reviewed"]
    if reviewed:
        return "PIPELINE_VALIDATED"
    return "NOT_TESTED"


# ---------------------------------------------------------------- calibration state
def calibration_state(n_reviewed_eligible: int, precision: float | None,
                      cfg: Config | None = None) -> str:
    """CalibrationState (PART B §7-§8): driven ONLY by eligible labels.
    SIMULATED reviews never advance this (callers must pass eligible-only
    counts). Thresholds live in Config (PART N)."""
    min_exp = (cfg.cal_min_for_experimental if cfg else MIN_REVIEWED_FOR_EXPERIMENTAL)
    min_cal = (cfg.cal_min_for_calibrated if cfg else MIN_REVIEWED_FOR_CALIBRATED)
    prec_cal = (cfg.cal_precision_for_calibrated if cfg else PRECISION_FOR_CALIBRATED)
    prec_unrel = (cfg.cal_precision_for_unreliable if cfg else PRECISION_FOR_UNRELIABLE)
    if n_reviewed_eligible < min_exp:
        return "UNCALIBRATED"
    if n_reviewed_eligible < min_cal:
        return "EXPERIMENTAL"
    if precision is None:
        return "EXPERIMENTAL"
    if precision >= prec_cal:
        return "CALIBRATED"
    if precision <= prec_unrel:
        return "UNRELIABLE"
    return "EXPERIMENTAL"


# ---------------------------------------------------------------- sampling
def _episode_detectors(episode: dict) -> list[str]:
    out = list(episode.get("execution_primitives") or [])
    m = (episode.get("engagement_method") or {}).get("method")
    if m:
        out.append(m)
    return out


def sample_calibration_set(db: DB, cfg: Config, match_id: str,
                           player_id: int | None = None,
                           per_detector: int | None = None,
                           include_negative_controls: bool = True) -> list[dict]:
    """Stratified sampling with coverage balancing (PART D §13-§14):
    prefer detectors with the largest human-label deficit; reserve 10-20%
    quota for negative controls (PART K §32)."""
    target = per_detector or DEFAULT_MOMENTS_PER_MATCH
    eps = db.get_decision_episodes(match_id=match_id, player_id=player_id, limit=2000)
    if not eps:
        return []
    by_det = {}
    for ep in eps:
        for det in _episode_detectors(ep):
            by_det.setdefault(det, []).append(ep)

    # human-label deficit per detector (coverage balancing, PART D §14)
    existing = db.get_calibration_samples(label_source="HUMAN", limit=10000)
    human_count = {}
    for s in existing:
        human_count[s["detector_type"]] = human_count.get(s["detector_type"], 0) + 1

    samples = []
    # negative controls: sample episodes where the detector did NOT fire,
    # for detectors with human labels (so the user can confirm absence)
    if include_negative_controls:
        neg = _negative_controls(db, eps, human_count, n=max(1, int(target * NEGATIVE_CONTROL_SHARE)))
        samples.extend(neg)

    for det in CALIBRATABLE_DETECTORS:
        pool = by_det.get(det, [])
        if not pool:
            continue
        deficit = human_count.get(det, 0)
        # coverage balancing: detectors with more human labels get less new quota
        weight = max(1, target - deficit)
        n = min(weight, max(1, len(pool)))
        picked = _stratified_pick(pool, det, n=n)
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
                "label_source": "HUMAN",       # queued for human review
                "pipeline_validation": "NOT_TESTED",
                "is_negative_control": False,
                "geometry_mode": "off",
            })
    # persist (replace per match to keep idempotent)
    db.delete_calibration_samples(match_id)
    for s in samples:
        db.upsert_calibration_sample(s)
    return samples


def _negative_controls(db: DB, eps: list[dict], human_count: dict, n: int) -> list[dict]:
    """Negative-control samples (PART K §32): detector did NOT fire on an
    otherwise reasonable episode; user confirms absence of the problem."""
    out = []
    for det in ("PREAIM_ERROR", "MOVING_SHOT", "DRY_PEEK"):
        if human_count.get(det, 0) < 1:
            continue  # only meaningful once we have positives to compare
        negatives = [e for e in eps
                     if det not in _episode_detectors(e)
                     and e.get("evidence_sufficiency") in ("MEDIUM", "HIGH")]
        for ep in negatives[: max(1, n // 3)]:
            out.append({
                "id": f"{ep['id']}-neg-{det}",
                "match_id": ep["match_id"], "player_id": ep["player_id"],
                "round": ep["round"], "tick": ep["anchor_tick"],
                "episode_id": ep["id"], "detector_type": det,
                "predicted_label": "NOT_" + det,
                "predicted_confidence": None,
                "evidence_sufficiency": ep.get("evidence_sufficiency"),
                "model_version": ep.get("model_version", "v1.3.1-1"),
                "rule_version": ep.get("rule_version", "v1.3.1-1"),
                "sample_stratum": "negative-control",
                "review_status": "pending",
                "label_source": "HUMAN",
                "pipeline_validation": "NOT_TESTED",
                "is_negative_control": True,
                "geometry_mode": "off",
            })
    return out


def _stratified_pick(pool: list[dict], det: str, n: int) -> list[dict]:
    scored = []
    for ep in pool:
        wm = ep.get("weapon_matchup") or {}
        key = f"{wm.get('range_bucket', '?')}|{wm.get('self_weapon_class', '?')}"
        scored.append((ep, key))
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


# ---------------------------------------------------------------- human review
def submit_human_annotation(db: DB, sample_id: str, label: str,
                            confidence: float = 0.7, reason: str = "",
                            annotator_id: str = "local") -> dict:
    """Record ONE human annotation (one-to-many, PART L). The sample's
    derived human_label is aggregated from annotations, never overwritten
    destructively."""
    annotation_id = uuid.uuid4().hex[:16]
    db.insert_calibration_annotation({
        "annotation_id": annotation_id, "sample_id": sample_id,
        "annotator_id": annotator_id, "label_source": "HUMAN",
        "label": label, "confidence": confidence, "reason": reason,
    })
    # derived view on the sample (aggregate of HUMAN annotations)
    anns = db.annotations_for_sample(sample_id)
    human_anns = [a for a in anns if a["label_source"] == "HUMAN"]
    if human_anns:
        # majority / most-confident label as the derived human_label
        from collections import Counter
        counts = Counter(a["label"] for a in human_anns)
        agg_label = counts.most_common(1)[0][0]
        agg_conf = max(a["confidence"] for a in human_anns)
        db.mark_calibration_reviewed(sample_id, agg_label, agg_conf, reason,
                                     label_source="HUMAN")
    return {"annotation_id": annotation_id, "sample_id": sample_id,
            "label_source": "HUMAN", "label": label}


def submit_simulated_review(db: DB, sample_id: str, label: str,
                            confidence: float = 0.8, reason: str = "") -> dict:
    """SIMULATED review: validates the pipeline only (PART A §3 / PART B).
    Marks sample as PIPELINE_VALIDATED and labels the SAMPLE source SIMULATED
    so calibration_stats never counts it as human; the annotation row records
    the simulated label but it never becomes a derived human_label."""
    annotation_id = uuid.uuid4().hex[:16]
    db.insert_calibration_annotation({
        "annotation_id": annotation_id, "sample_id": sample_id,
        "annotator_id": "simulated", "label_source": "SIMULATED",
        "label": label, "confidence": confidence, "reason": reason,
    })
    db.conn.execute(
        "UPDATE calibration_samples SET review_status='reviewed', "
        "pipeline_validation='PIPELINE_VALIDATED', label_source='SIMULATED' "
        "WHERE id=?", (sample_id,))
    db.conn.commit()
    return {"annotation_id": annotation_id, "sample_id": sample_id,
            "label_source": "SIMULATED"}


# ---------------------------------------------------------------- metrics v2
def calibration_stats(db: DB, cfg: Config,
                      detector_type: str | None = None) -> dict:
    """Metrics v2 (PART K): human and simulated counts are NEVER merged.
    CalibrationState from eligible (HUMAN) labels only. Positive-only ->
    confirmation rate, not accuracy/recall (PART K §31)."""
    samples = db.get_calibration_samples(detector_type=detector_type, limit=10000)
    by_det = {}
    for s in samples:
        by_det.setdefault(s["detector_type"], []).append(s)
    out = {}
    for det, lst in by_det.items():
        # HUMAN is derived from ANNOTATIONS (authoritative one-to-many).
        # SIMULATED falls back to the sample-level label_source flag (v8
        # migration tagged pre-existing simulated reviews without annotation
        # rows). Simulated NEVER drives state; only pipeline validation.
        human_rev, sim_rev = [], []
        for s in lst:
            if s["review_status"] != "reviewed":
                continue
            anns = db.annotations_for_sample(s["id"])
            has_human = any(a["label_source"] == "HUMAN" for a in anns)
            if has_human:
                human_rev.append(s)
            elif s.get("label_source") == "SIMULATED" or \
                    any(a["label_source"] == "SIMULATED" for a in anns):
                sim_rev.append(s)
        h_conf = sum(1 for s in human_rev if _confirmed(s.get("human_label")))
        h_precision = h_conf / len(human_rev) if human_rev else None
        state = calibration_state(len(human_rev), h_precision, cfg)
        pipeline = pipeline_validation_state(lst, det)
        out[det] = {
            # human (eligible) — drives CalibrationState
            "human_reviewed_count": len(human_rev),
            "human_confirmed_count": h_conf,
            "human_confirmation_rate": round(h_precision, 3) if h_precision is not None else None,
            "calibration_state": state,
            # simulated — pipeline validation only, NEVER merged
            "simulated_reviewed_count": len(sim_rev),
            "pipeline_validation_state": pipeline,
            "pending": sum(1 for s in lst if s["review_status"] == "pending"),
            "negative_controls": sum(1 for s in lst if s.get("is_negative_control")),
            "per_context": _per_context(human_rev),
            "confidence_buckets": _confidence_buckets(human_rev),
            "false_positive_reasons": _fp_reason_dist(human_rev),
            "note": ("confirmation rate over HUMAN-reviewed positives; accuracy/"
                     "recall requires negative controls (PART K §31-§32)"),
        }
    return {"detectors": out,
            "ground_truth_note": _honest_ground_truth_note(out)}


def _honest_ground_truth_note(detectors: dict) -> str:
    total_human = sum(d.get("human_reviewed_count", 0) for d in detectors.values())
    if total_human == 0:
        return "NO_REAL_CALIBRATION_AVAILABLE — no HUMAN labels yet; " \
               "simulated reviews only validate the pipeline (PART V)"
    return f"GROUND_TRUTH_PARTIAL — {total_human} HUMAN labels across detectors; " \
           "CalibrationState reflects eligible labels only"


def _confirmed(label) -> bool:
    return label in ("YES", "TRUE", "CONFIRMED", "CORRECT",
                     "REAL_PREAIM_ERROR", "ACTUAL_INACCURATE_MOVING_SHOT",
                     "REASONABLE_DRY_PEEK")


def _per_context(reviewed: list[dict]) -> dict:
    out = {}
    for s in reviewed:
        key = s.get("sample_stratum", "general")
        c = out.setdefault(key, {"n": 0, "confirmed": 0})
        c["n"] += 1
        if _confirmed(s.get("human_label")):
            c["confirmed"] += 1
    return {k: {"n": v["n"], "precision": round(v["confirmed"] / v["n"], 3) if v["n"] else None}
            for k, v in out.items()}


def _confidence_buckets(reviewed: list[dict]) -> dict:
    out = {}
    for lo, hi, label in ((0.7, 1.01, "HIGH"), (0.45, 0.7, "MEDIUM"), (0.0, 0.45, "LOW")):
        sel = [s for s in reviewed if s.get("predicted_confidence") is not None
               and lo <= s["predicted_confidence"] < hi]
        if not sel:
            continue
        conf = sum(1 for s in sel if _confirmed(s.get("human_label")))
        out[label] = {"n": len(sel), "confirmed": round(conf / len(sel), 3)}
    return out


def _fp_reason_dist(reviewed: list[dict]) -> dict:
    from collections import Counter
    return dict(Counter(s.get("false_positive_reason") or "N/A"
                        for s in reviewed if not _confirmed(s.get("human_label"))))


def detector_calibration_map(db: DB, cfg: Config) -> dict:
    """{detector: CalibrationState} — eligible-labels only (PART O)."""
    stats = calibration_stats(db, cfg)
    return {det: s["calibration_state"] for det, s in stats.get("detectors", {}).items()}


def detector_pipeline_map(db: DB, cfg: Config) -> dict:
    """{detector: PipelineValidationState} (PART B §9 / PART P)."""
    stats = calibration_stats(db, cfg)
    return {det: s["pipeline_validation_state"] for det, s in stats.get("detectors", {}).items()}


# ---------------------------------------------------------------- recompute (PART C)
def recompute_calibration(db: DB, cfg: Config) -> dict:
    """Recompute production CalibrationState from eligible labels only.
    SIMULATED reviews stay as pipeline validation and never leak into state."""
    stats = calibration_stats(db, cfg)
    # also refresh review_moments calibration reliability (PART O)
    from .moments import rank_review_moments
    from .episode_patterns import cluster_episodes
    from .training import generate_targets_from_episodes
    cal = detector_calibration_map(db, cfg)
    # re-gate existing targets (PART N): SIMULATED-validated targets stay PAUSED
    pats = cluster_episodes(db, cfg)
    generate_targets_from_episodes(db, cfg, pats, calibration_map=cal)
    return {"calibration": stats, "detector_map": cal,
            "recomputed_at": time.strftime("%Y-%m-%dT%H:%M:%S")}


def threshold_sensitivity(db: DB, cfg: Config, detector: str,
                          base_values: list[float]) -> list[dict]:
    """Threshold experiment over ELIGIBLE (human) reviews only (PART F §20)."""
    samples = db.get_calibration_samples(detector_type=detector, limit=10000)
    out = []
    for v in base_values:
        sel = [s for s in samples if (s.get("predicted_confidence") or 0) >= v]
        rev = [s for s in sel if s["review_status"] == "reviewed"
               and s.get("label_source") == "HUMAN"]
        conf = sum(1 for s in rev if _confirmed(s.get("human_label")))
        out.append({
            "threshold": v,
            "candidate_count": len(sel),
            "human_reviewed": len(rev),
            "human_confirmed": conf,
            "human_precision": round(conf / len(rev), 3) if rev else None,
            "note": "eligible (HUMAN) reviews only; higher threshold = fewer "
                    "candidates but expected higher precision",
        })
    return out


# ---------------------------------------------------------------- consensus (PART M)
class ConsensusResolver:
    """Interface for combining multiple annotations into one label (PART M).
    Default: single human label is authoritative; no voting system built."""

    def resolve(self, annotations: list[dict]) -> dict:
        raise NotImplementedError


class SingleHumanResolver(ConsensusResolver):
    def resolve(self, annotations: list[dict]) -> dict:
        human = [a for a in annotations if a["label_source"] == "HUMAN"]
        if not human:
            return {"label": None, "confidence": None, "n": 0, "mode": "no_human"}
        return {"label": human[-1]["label"], "confidence": human[-1]["confidence"],
                "n": len(human), "mode": "single_human"}


# ---------------------------------------------------------------- export (PART R)
def export_annotations_v2(db: DB, out_path: str, fmt: str = "jsonl") -> str:
    """Export samples with label_source + features (PART R)."""
    import os
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    rows = db.get_calibration_samples(limit=10000)
    for s in rows:
        s["annotations"] = db.annotations_for_sample(s["id"])
    if fmt == "jsonl" or out_path.endswith(".jsonl"):
        import json
        with open(out_path, "w", encoding="utf-8") as fh:
            for s in rows:
                fh.write(json.dumps(s, ensure_ascii=False, default=str) + "\n")
        return out_path
    try:
        import pandas as pd
        pd.DataFrame(rows).to_parquet(out_path, index=False)
        return out_path
    except Exception:  # noqa: BLE001
        import json
        with open(out_path, "w", encoding="utf-8") as fh:
            for s in rows:
                fh.write(json.dumps(s, ensure_ascii=False, default=str) + "\n")
        return out_path
