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
from .intent import ROLES

MODEL_VERSION = "alpha-1"
RULE_VERSION = "alpha-1"
CONFIG_VERSION = "alpha-1"

REASON_CODES = ["TEAM_CALL", "COORDINATED_PEEK", "MISSING_AUDIO", "MISSING_VISUAL_CONTEXT",
                "WRONG_ACTION_CLASSIFICATION", "WRONG_TIMING", "WRONG_INFORMATION_ASSUMPTION",
                "WRONG_RISK_ESTIMATE", "EXECUTION_NOT_DECISION", "OTHER"]

ANNOTATION_TYPES = ("behavior_detection", "decision_quality", "root_cause",
                    "target_feedback", "intent", "situational_role",
                    "commitment_state", "action_feasibility", "responsibility",
                    # V1.3.1 (spec §83)
                    "engagement_method", "execution_issue", "movement_effect")

INTENT_LABELS = ("ROTATE", "SOFT_ROTATE", "REPOSITION", "GATHER_INFO", "HOLD",
                 "CONTEST", "SUPPORT", "TRADE", "PLANT", "DEFUSE", "OTHER", "UNSURE")
ROLE_LABELS = tuple([*ROLES] + ["OTHER", "UNSURE"])
COMMITMENT_LABELS = ("FREE", "PLANT_INTENT", "PLANT_COMMITTED", "DEFUSE_INTENT",
                     "DEFUSE_COMMITTED", "RELOAD_COMMITTED", "UTILITY_COMMITTED",
                     "ENGAGEMENT_COMMITTED", "DISENGAGE_COMMITTED", "SAVE_COMMITTED",
                     "UNKNOWN", "UNSURE")
RESPONSIBILITY_LABELS = ("SELF_DECISION", "SELF_EXECUTION", "TEAMMATE_DECISION",
                         "TEAMMATE_EXECUTION", "SHARED", "REASONABLE_BUT_LOST",
                         "NOT_ACTIONABLE", "INSUFFICIENT_EVIDENCE", "UNSURE")


def build_review_queue(db: DB, cfg: Config, match_id: str,
                       review_focus: str = "balanced") -> list[dict]:
    """Create review items for a match with per-category quotas (spec §16-§18).

    Default quota: Intent 3 / Responsibility 2 / Pattern 2 / Other 1 = 8
    (configurable via cfg.review_quota / cfg.review_focus). Dynamic focus
    (spec §17): 'intent' / 'responsibility' / 'pattern' raise that quota at
    the expense of others. Priority (spec §18): intent top-1/top-2 closeness,
    responsibility conflicts, LOW-confidence tradeability, rule-vs-model
    disagreement, TrainingTarget key samples.
    """
    quota = dict(getattr(cfg, "review_quota", None) or
                 {"intent": 3, "responsibility": 2, "pattern": 2, "other": 1})
    budget = int(getattr(cfg, "review_budget_per_match", 8)) or sum(quota.values())
    focus = review_focus or getattr(cfg, "review_focus", "balanced")
    if focus == "intent":
        quota = {"intent": quota.get("intent", 3) + 2, "responsibility": 1,
                 "pattern": 1, "other": 0}
    elif focus == "responsibility":
        quota = {"intent": 1, "responsibility": quota.get("responsibility", 2) + 2,
                 "pattern": 1, "other": 0}
    elif focus == "pattern":
        quota = {"intent": 1, "responsibility": 1,
                 "pattern": quota.get("pattern", 2) + 2, "other": 0}
    elif focus == "other":
        quota = {"intent": 0, "responsibility": 0, "pattern": 0, "other": quota.get("other", 1) + 2}

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
    # V1.2.1: intent / responsibility ambiguity with new priorities (§18)
    for ce in db.get_context_events(match_id, limit=4000):
        dist = ce.get("intent_dist") or {}
        cands = [k for k, _ in sorted(dist.items(), key=lambda kv: -kv[1])][:2]
        top_close = (len(cands) >= 2
                     and ce["intent"] in ("ROTATE", "SOFT_ROTATE", "REPOSITION")
                     and (dist.get(cands[0], 0) - dist.get(cands[1], 0)) <= 0.12)
        if ce["intent"] == "AMBIGUOUS" or top_close:
            items.append({
                "id": f"{ce['id']}-intent", "match_id": match_id, "round": ce["round"],
                "tick": ce["tick"], "event_id": ce["event_ref"], "dp_id": None,
                "item_type": "intent", "priority": round(0.62 + (0.15 if top_close else 0.0), 3),
                "model_prediction": ce["intent"] if ce["intent"] != "AMBIGUOUS" else "AMBIGUOUS",
                "model_confidence": ce["intent_conf"],
                "rationale": f"intent ambiguity/top-close: {ce['intent_dist']}",
                "candidates": cands,
                "status": "pending", "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            })
        elif ce["intent"] in ("ROTATE", "SOFT_ROTATE", "REPOSITION"):
            items.append({
                "id": f"{ce['id']}-intent", "match_id": match_id, "round": ce["round"],
                "tick": ce["tick"], "event_id": ce["event_ref"], "dp_id": None,
                "item_type": "intent", "priority": round(0.3 + ce["intent_conf"] * 0.3, 3),
                "model_prediction": ce["intent"], "model_confidence": ce["intent_conf"],
                "rationale": f"intent candidate: {ce['intent_dist']}",
                "candidates": cands,
                "status": "pending", "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            })
        # responsibility conflict / low-confidence tradeability
        resp = ce.get("responsibility")
        trade = (ce.get("temporal_summary") or {}).get("tradeability")
        resp_conflict = resp in ("SHARED", "INSUFFICIENT_EVIDENCE")
        low_trade = trade and trade.get("classification") == "LOW" \
            and trade.get("confidence", 1.0) < 0.5
        if (resp_conflict or low_trade) and ce["anchor"] == "death":
            items.append({
                "id": f"{ce['id']}-resp", "match_id": match_id, "round": ce["round"],
                "tick": ce["tick"], "event_id": ce["event_ref"], "dp_id": None,
                "item_type": "responsibility", "priority": round(0.7, 3),
                "model_prediction": resp or "UNKNOWN", "model_confidence": ce.get("intent_conf", 0.5),
                "rationale": f"responsibility {'conflict' if resp_conflict else 'low-confidence tradeability'}: "
                             f"attribution={resp}",
                "status": "pending", "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            })

    # V1.3: DecisionEpisode review (spec §49-§51): 3-5 high-value episodes
    for ep in db.get_decision_episodes(match_id=match_id, limit=500):
        prio = 0.0
        reasons = []
        if ep["actionability"] in ("HIGHLY_ACTIONABLE", "ACTIONABLE"):
            prio += 0.35
            reasons.append("actionable")
        if ep["decision_evaluation"] in ("QUESTIONABLE", "POOR"):
            prio += 0.3
            reasons.append(f"evaluation={ep['decision_evaluation']}")
        if ep["decision_evaluation"] == "INSUFFICIENT_EVIDENCE":
            prio += 0.15
            reasons.append("low-confidence evaluation")
        if ep["intent"] == "AMBIGUOUS":
            prio += 0.1
            reasons.append("ambiguous intent")
        # V1.3.1: engagement/execution issues boost review priority (spec §83)
        em = (ep.get("engagement_method") or {})
        if em.get("method") in ("DRY_PEEK", "WIDE_SWING"):
            prio += 0.2
            reasons.append(f"engagement method={em.get('method')}")
        if ep.get("execution_primitives"):
            prio += 0.15
            reasons.append(f"execution issues={','.join(ep['execution_primitives'][:2])}")
        if prio < 0.35:
            continue
        items.append({
            "id": f"{ep['id']}-decision", "match_id": match_id,
            "round": ep["round"], "tick": ep["anchor_tick"],
            "event_id": ep["id"], "dp_id": None,
            "item_type": "decision_episode",
            "priority": round(min(0.95, prio), 3),
            "model_prediction": ep["observed_action"],
            "model_confidence": ep["confidence"],
            "rationale": f"decision episode {ep['family']}: " + "; ".join(reasons),
            "candidates": [c["action"] for c in
                           db.get_decision_candidates(ep["id"])
                           if c["feasibility"] not in ("UNAVAILABLE", "TEMPORARILY_UNAVAILABLE")][:5],
            "status": "pending", "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        })

    # quota allocation: stable ordering (priority desc), cap per category
    items.sort(key=lambda i: i["priority"], reverse=True)
    buckets = {"intent": [], "responsibility": [], "pattern": [], "other": []}
    for it in items:
        t = it["item_type"]
        if t in ("intent", "responsibility"):
            buckets[t].append(it)
        elif t == "decision_episode":
            buckets["pattern"].append(it)   # shares the pattern/other quota
        elif t.endswith("_sample") or t == "root_cause":
            buckets["pattern"].append(it)
        else:
            buckets["other"].append(it)
    picked = []
    counts = {"intent": 0, "responsibility": 0, "pattern": 0, "other": 0}
    for cat, cap in quota.items():
        for it in buckets.get(cat, []):
            if counts[cat] >= cap:
                break
            picked.append(it)
            counts[cat] += 1
    # fill the remaining budget from any category, still respecting quotas
    if len(picked) < budget:
        rest = [it for it in items if it not in picked]
        for it in rest:
            if len(picked) >= budget:
                break
            cat = it["item_type"] if it["item_type"] in counts else "other"
            if counts.get(cat, 0) >= quota.get(cat, 99):
                continue
            picked.append(it)
            counts[cat] = counts.get(cat, 0) + 1
    return picked[:budget]


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
                      round: int = 0, tick: int = 0,
                      mark_done: bool = False) -> dict:
    """Record a human annotation, preserving the model prediction separately.

    mark_done=False (default): the review item stays in the queue so the
    user can answer the other questions on the same item (判断对吗 /
    Decision 是 / 候选比较 are submitted one by one, then the frontend
    calls complete_review to remove the item once all are answered).
    """
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
            if mark_done:
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


def complete_review(db: DB, review_id: str) -> bool:
    """Mark a review item done once all its questions are answered."""
    item = next((r for r in db.get_review_queue(status="pending", limit=1000)
                 if r["id"] == review_id), None)
    if not item:
        return False
    db.mark_review_done(review_id)
    return True


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
    if t in ("intent", "situational_role", "commitment_state", "action_feasibility",
             "responsibility"):
        if hl in ("UNSURE", "OTHER"):
            return None
        return mp == hl
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


def export_intent_dataset(db: DB, out_path: str, fmt: str = "jsonl") -> str:
    """Export IntentSample rows (§49): JSONL always; Parquet when pyarrow exists."""
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    rows = db.get_intent_samples()
    if fmt == "jsonl" or out_path.endswith(".jsonl"):
        with open(out_path, "w", encoding="utf-8") as fh:
            for s in rows:
                fh.write(json.dumps(s, ensure_ascii=False) + "\n")
        return out_path
    try:
        import pandas as pd  # noqa: F401
        pd.DataFrame(rows).to_parquet(out_path, index=False)
        return out_path
    except Exception:  # noqa: BLE001
        with open(out_path, "w", encoding="utf-8") as fh:
            for s in rows:
                fh.write(json.dumps(s, ensure_ascii=False) + "\n")
        return out_path


def export_responsibility_dataset(db: DB, out_path: str) -> str:
    """Responsibility attribution rows (death-anchored context events)."""
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        for ce in db.get_context_events(limit=5000):
            if ce["anchor"] != "death":
                continue
            ts = ce.get("temporal_summary") or {}
            fh.write(json.dumps({
                "match_id": ce["match_id"], "round": ce["round"], "tick": ce["tick"],
                "steamid": ce["steamid"], "commitment": ce["commitment"],
                "role": ce["role"], "intent": ce["intent"],
                "feasibility": ce["feasibility"],
                "attribution": ce["responsibility"],
                "gate": ts.get("responsibility_gate"),
                "tradeability": ts.get("tradeability"),
                "information_strength": ts.get("information_strength"),
                "information_direction": ts.get("information_direction"),
                "temporal": ts,
                "model_version": "alpha-1", "rule_version": "v1.2.1-1",
            }, ensure_ascii=False) + "\n")
    return out_path
