"""Human Annotation Loop (spec §17-§31): HumanAnnotation, PreferenceAnnotation,
ReviewQueue (priority + budget), JSONL export and agreement statistics.

Invariants: the model prediction and the human correction are ALWAYS stored
separately; versions (model/rule/config) are recorded so future evaluation
can compare detector versions on the same human labels. Feedback NEVER
modifies rules/models in alpha (spec §27).
"""
from __future__ import annotations

import json
import os
import time
import uuid

from .config import Config
from .db import DB
from .stats import wilson_ci

MODEL_VERSION = "alpha-1"
RULE_VERSION = "alpha-1"
CONFIG_VERSION = "alpha-1"

REASON_CODES = ["TEAM_CALL", "COORDINATED_PEEK", "MISSING_AUDIO", "MISSING_VISUAL_CONTEXT",
                "WRONG_ACTION_CLASSIFICATION", "WRONG_TIMING", "WRONG_INFORMATION_ASSUMPTION",
                "WRONG_RISK_ESTIMATE", "EXECUTION_NOT_DECISION", "OTHER"]

ANNOTATION_TYPES = ("behavior_detection", "decision_quality", "root_cause", "target_feedback")


def build_review_queue(db: DB, cfg: Config, match_id: str) -> list[dict]:
    """Create review items for a match: low-confidence high-impact samples,
    near-threshold detections, and samples that shape target ranking.
    Respects the per-match budget (spec §23-§24)."""
    items = []
    # pattern samples
    for ptype in ("repeek", "move_shoot", "advantage"):
        pid = f"alpha-{ptype}"
        for ev in db.get_pattern_evidence(pid):
            if ev["match_id"] != match_id:
                continue
            det = ev.get("detail") or {}
            conf = det.get("confidence", 0.5)
            is_viol = det.get("evaluation", "?") in ("POOR", "QUESTIONABLE") \
                if ptype in ("repeek",) else (det.get("classification") == "POSSIBLE_ADVANTAGE_OVERAGGRESSION"
                                              if ptype == "advantage" else det.get("evaluation") == "POOR")
            impact = 0.4 if is_viol else 0.1
            near_thresh = 0.3 if (det.get("evaluation") == "QUESTIONABLE"
                                  or (conf is not None and 0.4 <= conf <= 0.6)) else 0.0
            priority = 0.35 * (1 - (conf or 0.5)) + 0.3 * impact + 0.2 * near_thresh + 0.15 * is_viol
            if priority < 0.25:
                continue
            items.append({
                "id": f"{match_id}-r{ev['round']}-t{ev['tick']}-{ptype}",
                "match_id": match_id, "round": ev["round"], "tick": ev["tick"],
                "event_id": ev["dp_id"], "dp_id": ev["dp_id"],
                "item_type": f"{ptype}_sample",
                "priority": round(priority, 3),
                "model_prediction": det.get("evaluation") or det.get("classification") or "DETECTED",
                "model_confidence": conf,
                "rationale": f"{ptype} sample at round {ev['round']} tick {ev['tick']}",
                "status": "pending", "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            })
    # root-cause layer conflicts (macro vs micro disagreement is review-worthy)
    for rc in db.get_root_causes(match_id):
        if rc["macro"] and rc["micro"] and rc["primary_cause"] != rc["macro"] and rc["confidence"] < 0.7:
            items.append({
                "id": f"{rc['event_id']}-rc", "match_id": match_id, "round": rc["round"],
                "tick": rc["tick"], "event_id": rc["event_id"], "dp_id": None,
                "item_type": "root_cause", "priority": round(0.6, 3),
                "model_prediction": rc["primary_cause"], "model_confidence": rc["confidence"],
                "rationale": f"root-cause layers conflict (macro={rc['macro']}, micro={rc['micro']})",
                "status": "pending", "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            })
    items.sort(key=lambda i: i["priority"], reverse=True)
    return items[: cfg.review_budget_per_match]


def persist_review_queue(db: DB, items: list[dict]):
    for it in items:
        db.insert_review_item(it)


def submit_annotation(db: DB, review_id: str | None = None,
                      annotation_type: str = "decision_quality",
                      model_prediction: str | None = None,
                      model_confidence: float | None = None,
                      human_label: str = "", human_confidence: float = 0.7,
                      reason_code: str = "OTHER", optional_comment: str = "",
                      event_id: str = "", dp_id: str = "", match_id: str = "",
                      round: int = 0, tick: int = 0) -> dict:
    """Record a human annotation, preserving the model prediction separately."""
    if reason_code not in REASON_CODES:
        raise ValueError(f"invalid reason code: {reason_code}")
    if annotation_type not in ANNOTATION_TYPES:
        raise ValueError(f"invalid annotation type: {annotation_type}")
    if review_id:
        item = next((r for r in db.get_review_queue(status="pending", limit=1000)
                     if r["id"] == review_id), None)
        if item:
            match_id, round, tick = item["match_id"], item["round"], item["tick"]
            event_id, dp_id = item.get("event_id") or "", item.get("dp_id") or ""
            model_prediction = model_prediction or item["model_prediction"]
            model_confidence = model_confidence if model_confidence is not None else item["model_confidence"]
            db.mark_review_done(review_id)
    ann = {
        "id": uuid.uuid4().hex[:16],
        "match_id": match_id, "round": round, "tick": tick,
        "event_id": event_id, "dp_id": dp_id, "annotation_type": annotation_type,
        "model_version": MODEL_VERSION, "rule_version": RULE_VERSION,
        "config_version": CONFIG_VERSION,
        "model_prediction": model_prediction, "model_confidence": model_confidence,
        "human_label": human_label, "human_confidence": human_confidence,
        "correction_type": "none" if human_label == "CORRECT" else "correction",
        "reason_code": reason_code, "optional_comment": optional_comment,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    db.insert_annotation(ann)
    return ann


def submit_preference(db: DB, match_id: str, round: int, tick: int, event_id: str,
                      candidates: list[str], human_choice: str,
                      human_confidence: float = 0.6, reason_code: str = "OTHER") -> dict:
    rec = {
        "id": uuid.uuid4().hex[:16], "match_id": match_id, "round": round, "tick": tick,
        "event_id": event_id, "candidates": candidates, "human_choice": human_choice,
        "human_confidence": human_confidence, "reason_code": reason_code,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    db.insert_preference(rec)
    return rec


def _agreement(ann) -> bool | None:
    """Does the human label confirm the model prediction (per type)?"""
    t, mp, hl = ann["annotation_type"], ann["model_prediction"], ann["human_label"]
    if t == "behavior_detection":
        return hl == "CORRECT"
    if t == "decision_quality":
        return ((mp == "POOR" and hl == "BAD") or (mp == "REASONABLE" and hl == "GOOD")
                or (mp == "QUESTIONABLE" and hl == "UNCERTAIN") or hl == "CORRECT")
    if t == "root_cause":
        return hl in ("None of these",) and False or hl == "Mixed" or mp in hl.split(",")
    return None


def annotation_stats(db: DB) -> dict:
    anns = db.get_annotations()
    by_type = {}
    for a in anns:
        by_type.setdefault(a["annotation_type"], []).append(a)
    out = {"total": len(anns), "by_type": {}}
    for t, lst in by_type.items():
        ag = [a for a in lst if _agreement(a) is not None]
        agree = sum(1 for a in ag if _agreement(a))
        out["by_type"][t] = {
            "n": len(lst),
            "agreement": round(agree / len(ag), 3) if ag else None,
        }
    # confidence calibration buckets (spec §30)
    buckets = {}
    for lo, hi, label in ((0.8, 1.01, "0.8-1.0"), (0.5, 0.8, "0.5-0.8"), (0.0, 0.5, "<0.5")):
        sel = [a for a in anns if a["model_confidence"] is not None
               and lo <= a["model_confidence"] < hi]
        if not sel:
            continue
        ag = [a for a in sel if _agreement(a) is not None]
        buckets[label] = {"n": len(sel),
                          "agreement": round(sum(1 for a in ag if _agreement(a)) / len(ag), 3) if ag else None}
    out["confidence_calibration"] = buckets
    return out


def export_annotations(db: DB, out_path: str) -> str:
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        for a in db.get_annotations():
            fh.write(json.dumps(a, ensure_ascii=False) + "\n")
    return out_path
