"""Alpha TrainingTarget: creation, Active Focus, validation windows and the
three-channel validation (behavior / execution / outcome) — spec §10-§19.
Deterministic; no LLM in the loop.
"""
from __future__ import annotations

import time
import uuid

from .config import Config
from .db import DB
from .stats import wilson_ci

STATUSES = ("ACTIVE", "IMPROVING", "MASTERED", "FAILED_TO_TRANSFER",
            "INSUFFICIENT_DATA", "PAUSED", "REPLACED")

TARGET_SPECS = {
    "repeek": {
        "name": "Reduce automatic same-angle re-peeks",
        "category": "Micro Decision",
        "trigger": "第一次接触没有获得明显优势",
        "undesired": "3 秒内从同一角度重新暴露（无新信息）",
        "replacement": "disengage / reposition / utility reset",
        "measure": "bad_repeek_rate = (POOR+QUESTIONABLE) / repeek opportunities",
        "cue": {"when": "第一次接触后未取得优势时", "do": "脱离角度、换位或道具重置",
                "avoid": "3 秒内同角度重复暴露"},
    },
    "move_shoot": {
        "name": "Reduce moving first shots / improve counter-strafe",
        "category": "Execution",
        "trigger": "首次有效交火",
        "undesired": "高速度状态下提交首枪",
        "replacement": "完成有效减速（急停）后再提交首枪",
        "measure": "moving_first_shot_rate = moving shots / shots",
        "cue": {"when": "与敌人交火时", "do": "急停到低速度再开枪",
                "avoid": "移动中开第一枪"},
    },
    "advantage": {
        "name": "Protect man advantage / stop overaggressive advantage play",
        "category": "Macro Decision",
        "trigger": "队伍取得人数优势",
        "undesired": "无支援、无紧迫 objective、低信息收益的主动孤立交火",
        "replacement": "保持可换人结构、保持地图控制，只在明显高价值时机继续主动",
        "measure": "advantage_overaggression_rate = overaggression / advantage engagements",
        "cue": {"when": "取得人数优势后", "do": "保持间距与可换人结构、控制信息面",
                "avoid": "孤立 1v1 / 无情报推进"},
    },
}


def generate_targets(db: DB, cfg: Config, bottlenecks: list[dict]) -> list[dict]:
    """Create/refresh TrainingTargets from eligible bottlenecks, respecting the
    Active Focus limit (max 2: one micro/execution + one macro)."""
    created = []
    active = [t for t in db.get_targets() if t["status"] in ("ACTIVE", "IMPROVING")]
    slots = {"micro": sum(1 for t in active if t["category"] in ("Micro Decision", "Execution")),
             "macro": sum(1 for t in active if t["category"] == "Macro Decision")}
    for b in bottlenecks:
        if not b["eligible"]:
            continue
        ptype = b["pattern_type"]
        spec = TARGET_SPECS[ptype]
        pattern = db.get_pattern(ptype)
        baseline = pattern["violation_rate"] if pattern else 0.0
        # goal is always below baseline (reduce-rate target), never floored above it
        goal = round(min(baseline, max(0.001, baseline * 0.5)), 3)
        existing = db.get_target(ptype)  # one target per pattern type in alpha
        if existing and existing["status"] not in ("REPLACED", "PAUSED"):
            if existing["status"] in ("ACTIVE", "IMPROVING"):
                existing["baseline"], existing["goal"] = baseline, goal
                existing["confidence"] = b["confidence"]
                db.upsert_target(existing)
            created.append(existing)
            continue
        bucket = "macro" if b["category"] == "Macro Decision" else "micro"
        if slots[bucket] >= 1:
            continue
        target = {
            "target_id": ptype,
            "pattern_type": ptype, "name": spec["name"], "category": spec["category"],
            "trigger": spec["trigger"], "undesired_behavior": spec["undesired"],
            "replacement_behavior": spec["replacement"],
            "baseline": baseline, "goal": goal,
            "measurement_definition": spec["measure"],
            "measurement_window": cfg.validation_window_matches,
            "status": "ACTIVE", "progress": 0.0,
            "confidence": b["confidence"],
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "next_match_cue": spec["cue"],
            "source_pattern_ids": [b["pattern_id"]],
            "supporting_evidence": b["breakdown"],
        }
        db.upsert_target(target)
        db.insert_target_history({"id": uuid.uuid4().hex[:12], "target_id": ptype,
                                  "from_status": None, "status": "ACTIVE",
                                  "at": target["created_at"], "reason": "generated from bottleneck"})
        slots[bucket] += 1
        created.append(target)
    return created


def active_focus(db: DB) -> list[dict]:
    return [t for t in db.get_targets() if t["status"] in ("ACTIVE", "IMPROVING")]


def _window_rate(db: DB, cfg: Config, ptype: str, match_ids: list[str]) -> dict:
    opp = viol = 0
    for pid in {f"alpha-{ptype}"}:
        for ev in db.get_pattern_evidence(pid):
            if ev["match_id"] not in match_ids:
                continue
            det = ev.get("detail") or {}
            if ptype == "repeek":
                if det.get("evaluation") == "INSUFFICIENT_EVIDENCE":
                    continue
                opp += 1
                if det.get("evaluation") in ("POOR", "QUESTIONABLE"):
                    viol += 1
            elif ptype == "move_shoot":
                opp += 1
                if det.get("evaluation") == "POOR":
                    viol += 1
            else:  # advantage
                opp += 1
                if det.get("classification") == "POSSIBLE_ADVANTAGE_OVERAGGRESSION":
                    viol += 1
    rate = viol / opp if opp else None
    ci = wilson_ci(viol, opp) if opp else (None, None, None)
    return {"opportunities": opp, "violations": viol, "rate": rate, "ci": ci}


def validate_targets(db: DB, cfg: Config) -> list[dict]:
    """Re-measure ACTIVE targets on the matches ingested since creation."""
    verdicts = []
    matches = sorted(db.list_matches(), key=lambda m: m["parsed_at"])
    for t in active_focus(db):
        created = t["created_at"]
        window_matches = [m for m in matches if m["parsed_at"] >= created][: t["measurement_window"]]
        base = t["baseline"]
        if not window_matches:
            verdicts.append({"target_id": t["target_id"], "status": t["status"],
                             "verdict": "PENDING_WINDOW", "note": "no matches since creation"})
            continue
        wr = _window_rate(db, cfg, t["pattern_type"], [m["demo_id"] for m in window_matches])
        if wr["rate"] is None or wr["opportunities"] < cfg.min_pattern_samples:
            verdicts.append({"target_id": t["target_id"], "status": t["status"],
                             "verdict": "INSUFFICIENT_DATA", "note": "window samples below minimum",
                             "window": wr})
            continue
        # behavior channel
        b_lo, b_hi = wilson_ci(int(base * 1000), 1000)[1:3] if base is not None else (0, 1)
        lo, hi = wr["ci"][1], wr["ci"][2]
        behavior = "BEHAVIOR_CHANGED" if (hi < b_lo) else ("BEHAVIOR_WORSE" if (lo > b_hi) else "BEHAVIOR_UNCHANGED")
        # outcome channel: survival among window samples vs baseline samples
        out_verdict = "OUTCOME_UNCERTAIN"
        # execution channel applies to the execution target
        exec_verdict = None
        if t["pattern_type"] == "move_shoot":
            exec_verdict = "EXECUTION_IMPROVED" if behavior == "BEHAVIOR_CHANGED" else "EXECUTION_UNCHANGED"
        progress = 0.0
        if base and base != t["goal"]:
            progress = max(0.0, min(1.0, (base - (wr["rate"] or base)) / (base - t["goal"])))
        t2 = dict(t)
        t2["progress"] = round(progress, 3)
        if behavior == "BEHAVIOR_CHANGED" and t2["status"] == "ACTIVE":
            t2["status"] = "IMPROVING"
        elif behavior in ("BEHAVIOR_UNCHANGED", "BEHAVIOR_WORSE") and t2["status"] == "IMPROVING":
            t2["status"] = "ACTIVE"
        t2["status"] = t2["status"]
        db.upsert_target(t2)
        db.insert_measurement({
            "id": uuid.uuid4().hex[:12], "target_id": t["target_id"],
            "window_start": window_matches[0]["parsed_at"],
            "window_end": window_matches[-1]["parsed_at"],
            "opportunities": wr["opportunities"], "violations": wr["violations"],
            "rate": wr["rate"], "rate_ci": [wr["ci"][1], wr["ci"][2]],
            "delta_vs_baseline": round((wr["rate"] or 0) - (base or 0), 3),
            "behavior_verdict": behavior, "execution_verdict": exec_verdict,
            "outcome_verdict": out_verdict})
        verdicts.append({"target_id": t["target_id"], "status": t2["status"],
                         "verdict": behavior, "outcome": out_verdict,
                         "execution": exec_verdict, "progress": t2["progress"],
                         "window": wr})
    return verdicts
