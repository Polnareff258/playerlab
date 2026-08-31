"""Build spike/golden_alpha.json: 15 golden samples (5 re-peek / 5 execution /
5 advantage) from the real demo, using the HumanAnnotation schema (spec §43).
Human labels here are provisional best-effort from demo evidence; they are the
seed for the human annotation loop and should be refined through review.
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "core"))
from playerlab.config import Config
from playerlab.db import DB

cfg = Config().resolve()
db = DB(cfg.db_path)
match = db.list_matches()[0]["demo_id"] if db.list_matches() else None
assert match, "ingest a demo first"
out = []

# --- re-peek: from RE_PEEK DP samples (behavior_detection) ---
ev = db.get_pattern_evidence("alpha-repeek")
for e in ev[:5]:
    d = e.get("detail") or {}
    out.append({
        "match_id": e["match_id"], "round": e["round"], "tick": e["tick"],
        "event_id": e["dp_id"], "dp_id": e["dp_id"],
        "annotation_type": "behavior_detection",
        "model_version": "alpha-1", "rule_version": "alpha-1", "config_version": "alpha-1",
        "model_prediction": "RE_PEEK", "model_confidence": d.get("confidence"),
        "human_label": None,  # to be confirmed by reviewer
        "human_confidence": None, "correction_type": None,
        "reason_code": None, "optional_comment": "golden seed: re-peek sample",
        "created_at": "",
        "_evidence": {"evaluation": d.get("evaluation"),
                      "time_delta_ticks": d.get("time_delta_ticks"),
                      "angle_delta": d.get("angle_delta"),
                      "outcome": d.get("outcome")},
    })

# --- execution: move-shoot samples (decision_quality) ---
ms = db.get_pattern_evidence("alpha-move_shoot")
for e in ms[:5]:
    d = e.get("detail") or {}
    out.append({
        "match_id": e["match_id"], "round": e["round"], "tick": e["tick"],
        "event_id": f"shot-{e['tick']}", "dp_id": None,
        "annotation_type": "decision_quality",
        "model_version": "alpha-1", "rule_version": "alpha-1", "config_version": "alpha-1",
        "model_prediction": d.get("evaluation"), "model_confidence": d.get("confidence"),
        "human_label": None, "human_confidence": None, "correction_type": None,
        "reason_code": None, "optional_comment": "golden seed: move-and-shoot sample",
        "created_at": "",
        "_evidence": {"velocity_at_shot": d.get("velocity_at_shot"),
                      "peak_pre_shot": d.get("peak_pre_shot_velocity"),
                      "shot_before_stabilized": d.get("shot_before_stabilized")},
    })

# --- advantage: overaggression candidates + valid proactive (root_cause) ---
adv = db.get_pattern_evidence("alpha-advantage")
picks = [e for e in adv if (e.get("detail") or {}).get("classification") == "POSSIBLE_ADVANTAGE_OVERAGGRESSION"]
picks += [e for e in adv if (e.get("detail") or {}).get("classification") == "VALID_PROACTIVE"][:5 - len(picks)]
for e in picks[:5]:
    d = e.get("detail") or {}
    out.append({
        "match_id": e["match_id"], "round": e["round"], "tick": e["tick"],
        "event_id": f"adv-{e['tick']}", "dp_id": e["dp_id"],
        "annotation_type": "root_cause",
        "model_version": "alpha-1", "rule_version": "alpha-1", "config_version": "alpha-1",
        "model_prediction": d.get("classification"), "model_confidence": d.get("confidence"),
        "human_label": None, "human_confidence": None, "correction_type": None,
        "reason_code": None, "optional_comment": "golden seed: advantage management sample",
        "created_at": "",
        "_evidence": {"trade_support": d.get("trade_support"),
                      "objective_urgency": d.get("objective_urgency"),
                      "information_gain": d.get("information_gain"),
                      "time_until_engagement_s": d.get("time_until_risky_engagement_s")},
    })

path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "spike", "golden_alpha.json")
with open(path, "w", encoding="utf-8") as fh:
    json.dump(out[:15], fh, ensure_ascii=False, indent=1, default=str)
print(f"written {min(15, len(out))} golden samples to {path}")
print("per type:", {t: sum(1 for o in out if o["annotation_type"] == t) for t in
                    ("behavior_detection", "decision_quality", "root_cause")})
