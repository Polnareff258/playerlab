"""V1.1-alpha pattern detectors: immediate same-angle re-peek (Micro),
move-and-shoot / counter-strafe (Execution), advantage overaggression (Macro).

Behavior Detection and Decision Evaluation are kept separate (spec §8): a
sample is recorded whenever the behavior occurs; the evaluation (REASONABLE /
QUESTIONABLE / POOR / INSUFFICIENT_EVIDENCE) is a separate judgement.
Deterministic; all thresholds configurable.
"""
from __future__ import annotations

import math
from collections import Counter

from .config import Config
from .db import DB
from .ingest import IngestedDemo
from .state import build_tick_index, pos_at, wrap180, angle_diff
from .stats import wilson_ci

PATTERN_META = {
    "repeek": {"name": "Immediate Same-Angle Re-peek", "category": "Micro Decision"},
    "move_shoot": {"name": "Move-and-Shoot / Counter-Strafe", "category": "Execution"},
    "advantage": {"name": "Advantage Overaggression", "category": "Macro Decision"},
}
REPEEK_VERDICTS = ("REASONABLE", "QUESTIONABLE", "POOR", "INSUFFICIENT_EVIDENCE")


def _alive_counts(idx: dict, teams: dict, tick: int) -> dict:
    alive = {2: 0, 3: 0}
    for s, t in teams.items():
        rec = idx.get((s, tick))
        if rec and rec.get("is_alive"):
            alive[t] += 1
    return alive


def _speed_at(idx, steamid, tick):
    rec = idx.get((steamid, tick))
    if not rec or rec.get("vx") is None:
        return None
    return math.hypot(rec["vx"], rec["vy"])


def _nearest_teammate(idx, teams, steamid, tick):
    my_team = teams.get(steamid, -1)
    mypos = pos_at(idx, steamid, tick)
    if not mypos:
        return None
    best = None
    for s, t in teams.items():
        if s == steamid or t != my_team:
            continue
        rec = idx.get((s, tick))
        if not rec or not rec.get("is_alive"):
            continue
        p = pos_at(idx, s, tick)
        if not p:
            continue
        d = math.hypot(p[0] - mypos[0], p[1] - mypos[1])
        best = d if best is None else min(best, d)
    return best


# ---------------------------------------------------------------- re-peek
def detect_repeek(demo: IngestedDemo, cfg: Config, db: DB, idx: dict,
                  counterfactual: dict) -> list[dict]:
    samples = []
    for dp in db.get_dps(demo.demo_id):
        if dp["observed_action"] != "RE_PEEK":
            continue
        steamid = dp["steamid"]
        tc0 = dp["meta"].get("episode", {}).get("tc0")
        rnum = dp["round"]
        d_tick = dp["decision_tick"]

        def yaw_at(t):
            rec = idx.get((steamid, t))
            return rec.get("yaw") if rec else None

        ang0, ang1 = yaw_at(tc0), yaw_at(d_tick)
        angle_delta = angle_diff(ang0, ang1) if (ang0 is not None and ang1 is not None) else None
        time_delta = d_tick - tc0 if tc0 is not None else None
        p0, p1 = pos_at(idx, steamid, tc0), pos_at(idx, steamid, d_tick)
        position_delta = math.hypot(p1[0] - p0[0], p1[1] - p0[1]) if (p0 and p1) else None

        state = db.get_state(dp["dp_id"])
        known = (state or {}).get("known_state", {})
        pub = (state or {}).get("public_info", {})
        outcome = db.get_outcome(dp["dp_id"]) or {}

        # first-contact result: damage exchange around first contact
        took = dealt = 0
        for dmg in demo.events["damages"]:
            if tc0 is None:
                break
            if abs(dmg["tick"] - tc0) > 8:
                continue
            if dmg["user_steamid"] == steamid:
                took += dmg.get("dmg_health", 0)
            if dmg["attacker_steamid"] == steamid:
                dealt += dmg.get("dmg_health", 0)
        teams = {p["steamid"]: p["team_number"] for p in demo.players}
        alive = _alive_counts(idx, teams, d_tick)
        my_team = demo.team_of(steamid)
        team_alive = alive.get(my_team, 0)
        enemy_alive = alive.get(3 if my_team == 2 else 2, 0)
        mate_near = known.get("teammate_near", 0)
        n_known = known.get("n_known_enemies", 0)
        moving = (_speed_at(idx, steamid, d_tick) or 0.0) > cfg.stabilize_velocity
        support = counterfactual.get("support", "INSUFFICIENT")

        score = 0.0
        if dealt > 0 and took == 0:
            score += 1.0
        elif took > 0 and dealt == 0:
            score -= 1.0
        if mate_near >= 1:
            score += 1.0
        if n_known >= 2:
            score -= 1.0
        if moving:
            score -= 1.0
        if support == "AGAINST":
            score -= 1.5
        elif support == "FOR":
            score += 1.5
        missing = ang0 is None or ang1 is None or state is None or tc0 is None
        if missing:
            verdict = "INSUFFICIENT_EVIDENCE"
        elif score >= 1.5:
            verdict = "REASONABLE"
        elif score <= -1.5:
            verdict = "POOR"
        else:
            verdict = "QUESTIONABLE"

        samples.append({
            "match_id": demo.demo_id, "round": rnum, "tick": d_tick,
            "dp_id": dp["dp_id"], "steamid": steamid,
            "player_name": dp["player_name"],
            "first_contact_tick": tc0, "first_contact_angle": ang0,
            "repeek_tick": d_tick, "angle_delta": angle_delta,
            "time_delta_ticks": time_delta, "position_delta": position_delta,
            "relevant_enemy": dp["meta"].get("opponent"),
            "outcome": {"survival": outcome.get("survival"),
                        "duel": outcome.get("duel_result"),
                        "round_win": outcome.get("round_win")},
            "evidence_ticks": [tc0, d_tick] if tc0 else [d_tick],
            "confidence": dp["confidence"],
            "evaluation": verdict,
            "context": {"team_alive": team_alive, "enemy_alive": enemy_alive,
                        "teammate_near": mate_near, "n_known_enemies": n_known,
                        "moving_at_repeek": moving, "first_contact_dmg": [dealt, took]},
        })
    return samples


# ---------------------------------------------------------------- move-shoot
def detect_move_shoot(demo: IngestedDemo, cfg: Config, db: DB) -> list[dict]:
    samples = []
    for m in db.get_execution_metrics(demo.demo_id):
        if m["metric"] != "move_shoot":
            continue
        meta = m["meta"]
        samples.append({
            "match_id": demo.demo_id, "round": m["round"], "tick": m["tick"],
            "dp_id": None, "steamid": m["steamid"], "player_name": None,
            "velocity_at_shot": m["value"], "threshold": m["threshold"],
            "peak_pre_shot_velocity": meta["peak_pre_shot_velocity"],
            "deceleration_time_ticks": meta["deceleration_time_ticks"],
            "time_since_low_velocity_ticks": meta["time_since_low_velocity_ticks"],
            "shot_before_stabilized": meta["shot_before_stabilized"],
            "evidence_ticks": m["evidence"].get("window_ticks", []),
            "confidence": 0.95,
            "evaluation": "POOR" if m["violation"] else "REASONABLE",
            "outcome": None,
        })
    return samples


# ---------------------------------------------------------------- advantage
def detect_advantage(demo: IngestedDemo, cfg: Config, db: DB, idx: dict) -> list[dict]:
    teams = {p["steamid"]: p["team_number"] for p in demo.players}
    candidates = []
    events = []  # (tick, player, kind, dp_id)
    for dp in db.get_dps(demo.demo_id):
        if dp["observed_action"] in ("PEEK", "RE_PEEK"):
            events.append((dp["decision_tick"], dp["steamid"], "dp", dp["dp_id"]))
    for dmg in demo.events["damages"]:
        if dmg.get("dmg_health", 0) > 0 and dmg["attacker_steamid"] in teams:
            events.append((dmg["tick"], dmg["attacker_steamid"], "dmg", None))
    events.sort()

    death_ticks = {int(k["user_steamid"]): int(k["tick"]) for k in demo.events["kills"]}
    for tick, steamid, kind, dp_id in events:
        alive = _alive_counts(idx, teams, tick)
        my_team = demo.team_of(steamid)
        if my_team not in (2, 3):
            continue
        team_alive, enemy_alive = alive.get(my_team, 0), alive.get(3 if my_team == 2 else 2, 0)
        diff = team_alive - enemy_alive
        if diff < cfg.advantage_min_diff:
            continue
        # advantage_start: scan backwards up to 600 ticks for when diff first
        # dropped below the minimum (advantage gained)
        adv_start = tick
        for t in range(tick - 8, tick - 600, -8):
            a2 = _alive_counts(idx, teams, t)
            t_alive, e_alive = a2.get(my_team, 0), a2.get(3 if my_team == 2 else 2, 0)
            if t_alive - e_alive < cfg.advantage_min_diff:
                adv_start = t + 8
                break
        mate_d = _nearest_teammate(idx, teams, steamid, tick)
        trade_support = "HIGH" if (mate_d is not None and mate_d <= cfg.advantage_isolated_dist) \
            else ("MED" if mate_d is not None and mate_d <= cfg.advantage_isolated_dist * 2 else "LOW")
        # objective urgency
        bounds = demo.round_bounds(demo.round_of_tick(tick))
        remaining = (bounds[1] - tick) / 64.0 if bounds else 0.0
        planted = any(b["tick"] <= tick for b in demo.events["bombs"]["planted"])
        urgency = "HIGH" if (planted and remaining < cfg.objective_urgency_bomb_s) \
            else ("MED" if planted else "LOW")
        # info gain (player-known)
        state = db.get_state(dp_id) if dp_id else None
        n_known = 0
        if state:
            n_known = state.get("known_state", {}).get("n_known_enemies", 0)
        info_gain = "HIGH" if n_known >= 2 else ("MED" if n_known == 1 else "LOW")

        overagg = (trade_support == "LOW" and urgency == "LOW" and info_gain == "LOW")
        classification = "POSSIBLE_ADVANTAGE_OVERAGGRESSION" if overagg else "VALID_PROACTIVE"
        death_t = death_ticks.get(steamid)
        result = None
        if death_t is not None and 0 <= death_t - tick <= 96:
            new_alive = alive.copy()
            new_alive[my_team] -= 1
            result = f"death -> {new_alive[my_team]}v{enemy_alive}"
        conf = 0.55 + (0.1 if mate_d is not None else 0) + (0.05 if state else 0) \
            + (0.05 if info_gain != "LOW" or overagg else 0) + (0.1 if overagg else 0)
        conf = min(0.95, conf)
        candidates.append({
            "match_id": demo.demo_id, "round": demo.round_of_tick(tick), "tick": tick,
            "dp_id": dp_id, "steamid": steamid,
            "advantage_start_tick": adv_start, "advantage_size": diff,
            "round_time_s": round(remaining, 1),
            "player_position": pos_at(idx, steamid, tick),
            "team_alive": team_alive, "enemy_alive": enemy_alive,
            "known_enemy_information": {"n_known_enemies": n_known},
            "bomb_state": "planted" if planted else "none",
            "time_until_risky_engagement_s": round((tick - adv_start) / 64.0, 1),
            "trade_support": trade_support, "objective_urgency": urgency,
            "information_gain": info_gain, "result": result,
            "classification": classification, "confidence": round(conf, 3),
            "evidence_ticks": [adv_start, tick],
        })
    # dedupe: keep highest confidence per (player, round) engagement cluster
    candidates.sort(key=lambda c: (-c["confidence"], c["tick"]))
    kept = []
    for c in candidates:
        if any(abs(k["tick"] - c["tick"]) < 96 and k["steamid"] == c["steamid"]
               for k in kept):
            continue
        kept.append(c)
    return kept


# ---------------------------------------------------------------- aggregation
def counterfactual_support(db: DB, cfg: Config, pattern_type: str) -> dict:
    """Aggregated counterfactual support (spec §10): compare the pattern
    action's survival against its main alternative with Wilson intervals.
    Reads cumulative pattern evidence + DISENGAGE outcomes from the DB."""
    if pattern_type == "repeek":
        rep_surv = []
        for ev in db.get_pattern_evidence("alpha-repeek"):
            det = ev.get("detail") or {}
            o = det.get("outcome") or {}
            if o.get("survival") is not None:
                rep_surv.append(o["survival"])
        alt_surv = []
        for match in db.list_matches():
            for dp in db.get_dps(match["demo_id"]):
                if dp["observed_action"] != "DISENGAGE":
                    continue
                o = db.get_outcome(dp["dp_id"])
                if o and o["survival"] is not None:
                    alt_surv.append(o["survival"])
        if len(rep_surv) < cfg.n_min_action or len(alt_surv) < cfg.n_min_action:
            return {"support": "INSUFFICIENT", "n_repeek": len(rep_surv),
                    "n_alternative": len(alt_surv)}
        p1, lo1, hi1 = wilson_ci(sum(rep_surv), len(rep_surv))
        p2, lo2, hi2 = wilson_ci(sum(alt_surv), len(alt_surv))
        if hi1 < lo2:
            support = "AGAINST"   # re-peek survives less than disengage
        elif hi2 < lo1:
            support = "FOR"       # re-peek survives more
        else:
            support = "WEAK"
        return {"support": support, "n_repeek": len(rep_surv),
                "n_alternative": len(alt_surv),
                "repeek_survival": round(p1, 3), "disengage_survival": round(p2, 3)}
    return {"support": "INSUFFICIENT", "n_repeek": 0, "n_alternative": 0,
            "note": "no outcome pairing for this pattern type"}


def aggregate_patterns(db: DB, cfg: Config, pattern_type: str,
                       matches_count: int) -> dict:
    """Aggregate all cumulative evidence rows into a Pattern row (spec §7)."""
    meta = PATTERN_META[pattern_type]
    samples = [ev.get("detail") or {} for ev in db.get_pattern_evidence(f"alpha-{pattern_type}")]
    n = len(samples)
    if pattern_type == "repeek":
        violations = [s for s in samples if s.get("evaluation") in ("POOR", "QUESTIONABLE")]
        positives = [s for s in samples if s.get("evaluation") == "REASONABLE"]
        negatives = [s for s in samples if s.get("evaluation") == "POOR"]
    elif pattern_type == "move_shoot":
        violations = [s for s in samples if s.get("evaluation") == "POOR"]
        positives = [s for s in samples if s.get("evaluation") == "REASONABLE"]
        negatives = violations
    else:  # advantage
        violations = [s for s in samples
                      if s.get("classification") == "POSSIBLE_ADVANTAGE_OVERAGGRESSION"]
        positives = [s for s in samples if s.get("classification") == "VALID_PROACTIVE"]
        negatives = violations

    rate = len(violations) / n if n else 0.0
    conf_n = min(1.0, n / 30.0)
    avg_conf = sum(s.get("confidence", 0.5) for s in samples) / n if n else 0.0
    cf = counterfactual_support(db, cfg, pattern_type)
    support_boost = 0.1 if cf.get("support") == "AGAINST" else (-0.1 if cf.get("support") == "INSUFFICIENT" else 0.0)
    confidence = max(0.0, min(1.0, 0.3 * conf_n + 0.5 * avg_conf + support_boost))
    affected = Counter()
    for s in samples:
        key = (s.get("evaluation") if pattern_type != "advantage" else s.get("classification")) or "?"
        affected[key] += 1
    return {
        "pattern_id": f"alpha-{pattern_type}",
        "pattern_type": pattern_type, "name": meta["name"], "category": meta["category"],
        "sample_count": n, "opportunity_count": n,
        "violation_count": len(violations), "violation_rate": round(rate, 3),
        "positive_examples": len(positives), "negative_examples": len(negatives),
        "confidence": round(confidence, 3),
        "counterfactual_support": cf.get("support", "INSUFFICIENT"),
        "affected_contexts": dict(affected),
        "evidence_refs": [s.get("dp_id") or f"tick{s.get('tick')}" for s in samples[:10]],
        "computed_at": __import__("time").strftime("%Y-%m-%dT%H:%M:%S"),
        "matches_count": matches_count,
    }
