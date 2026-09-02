"""DecisionPoint detector: deterministic rule-based (no LLM, no ML).

V1 taxonomy: PEEK / HOLD / RE_PEEK / DISENGAGE / FALLBACK (COUNTERFACTUAL_DESIGN
§1-§2). One DP per contact episode; the episode's most significant choice wins.
Action predicates are parameterized via Config; no geometric occlusion in V1
(exposure is approximated by movement relative to the known enemy anchor).
"""
from __future__ import annotations

import math
from dataclasses import asdict

from .config import Config
from .features import build_features
from .ingest import IngestedDemo
from .state import (PublicInfoBuilder, KnownStateBuilder, build_ground_truth,
                    build_tick_index, pos_at)
from .zones import zone_for
from .weapons import name_from_def
from .geometry import get_geometry
from .contact_semantics import build_contact_window, exposure_relations, classify_contact

TAXONOMY = ["PEEK", "HOLD", "RE_PEEK", "DISENGAGE", "FALLBACK"]
_LOOKBACK = 96  # ticks before first contact to look for approach
_EPISODE_TAIL = 32


def contact_meta(prediction) -> dict:
    """Serialize V1.3.4 contact output without discarding its distribution."""
    return {"initiation": prediction.initiation,
            "prediction": {"top_label": prediction.top_label,
                           "probabilities": prediction.probabilities,
                           "confidence": prediction.confidence,
                           "ambiguous": prediction.ambiguous,
                           "subtype": prediction.subtype,
                           "evidence": prediction.evidence}}


def apply_contact_prediction(dp: dict, prediction) -> dict:
    """Make contact semantics the action source while preserving legacy fields."""
    dp = dict(dp)
    dp["observed_action"] = prediction.top_label
    meta = dict(dp.get("meta") or {})
    meta["contact"] = contact_meta(prediction)
    dp["meta"] = meta
    return dp


def _dot_dir(px, py, vx, vy, ax, ay) -> float:
    """Dot product of velocity with direction to anchor (normalized-ish)."""
    dx, dy = ax - px, ay - py
    n = math.hypot(dx, dy)
    if n < 1.0:
        return 1.0
    return (vx * dx + vy * dy) / n


def detect_for_player(demo: IngestedDemo, steamid: int, cfg: Config,
                      idx: dict) -> list[dict]:
    """Detect DecisionPoints for one player across the whole match."""
    name = next((p["name"] for p in demo.players if p["steamid"] == steamid), "?")
    recs = {t: r for (s, t), r in idx.items() if s == steamid}
    if not recs:
        return []
    ticks_sorted = sorted(recs)
    geometry = get_geometry(cfg.geometry_provider, nav_dir=cfg.geometry_nav_dir or None,
                            tri_dir=cfg.geometry_tri_dir or None)

    # damage contacts involving this player
    contacts = []
    for d in demo.events["damages"]:
        if d["user_steamid"] == steamid:
            contacts.append((d["tick"], "taken", d["attacker_steamid"], d))
        elif d["attacker_steamid"] == steamid:
            contacts.append((d["tick"], "dealt", d["user_steamid"], d))
    contacts.sort(key=lambda c: c[0])
    # merge into episodes
    episodes = []
    for t, kind, other, d in contacts:
        if episodes and t - episodes[-1][-1]["t"] <= cfg.episode_merge_ticks:
            episodes[-1].append({"t": t, "kind": kind, "other": other, "d": d})
        else:
            episodes.append([{"t": t, "kind": kind, "other": other, "d": d}])

    death_ticks = {}
    for k in demo.events["kills"]:
        if k.get("user_steamid") is not None:
            death_ticks[int(k["user_steamid"])] = int(k["tick"])
    dps = []
    for ep in episodes:
        tc0 = ep[0]["t"]
        tc1 = ep[-1]["t"]
        if tc0 not in recs:
            continue
        # round 0 = warmup/knife (before the first real round); the game has
        # not started — no decision points there (cs-demo-manager: only count
        # rounds after match start)
        if demo.round_of_tick(tc0) < 1:
            continue
        # opponent = other party with most events
        counts = {}
        for e in ep:
            counts[e["other"]] = counts.get(e["other"], 0) + 1
        opponent = max(counts, key=counts.get)
        anchor = pos_at(idx, opponent, tc0) or pos_at(idx, opponent, tc1)
        if not anchor:
            continue
        ax, ay = anchor

        taken_tick = next((e["t"] for e in ep if e["kind"] == "taken"), None)

        def speed_at(t):
            r = recs.get(t)
            if not r or r.get("speed") is None or not r.get("is_alive"):
                return 0.0
            return float(r["speed"])

        def approach_tick(lo, hi, min_speed):
            """Last tick in [lo, hi] with movement toward anchor above min_speed."""
            found = None
            for t in ticks_sorted:
                if t < lo:
                    continue
                if t > hi:
                    break
                r = recs[t]
                if not r.get("is_alive") or r.get("vx") is None:
                    continue
                px, py = r.get("x"), r.get("y")
                if px is None or py is None:
                    continue
                if speed_at(t) >= min_speed and _dot_dir(px, py, r["vx"], r["vy"], ax, ay) > 0:
                    found = t
            return found

        def retreat_start(lo, hi):
            for t in ticks_sorted:
                if t < lo:
                    continue
                if t > hi:
                    break
                r = recs[t]
                if not r.get("is_alive") or r.get("vx") is None:
                    continue
                px, py = r.get("x"), r.get("y")
                if px is None or py is None:
                    continue
                if speed_at(t) >= cfg.v_disengage and _dot_dir(px, py, r["vx"], r["vy"], ax, ay) < 0:
                    return t
            return None

        lo = max(tc0 - _LOOKBACK, min(ticks_sorted))
        t_app = approach_tick(lo, tc0 - 8, cfg.v_peek)

        # hold: max consecutive low-speed run around contact (alive ticks only)
        hold_run = 0
        cur = 0
        for t in ticks_sorted:
            if t < tc0 - 8:
                continue
            if t > tc1 + 8:
                break
            if not recs[t].get("is_alive"):
                cur = 0
                continue
            if speed_at(t) <= cfg.v_hold:
                cur += 1
                hold_run = max(hold_run, cur)
            else:
                cur = 0
        holding = hold_run >= cfg.hold_min_ticks

        td = taken_tick if taken_tick is not None else tc0
        t_retreat = retreat_start(td, td + 2 * cfg.disengage_quiet_ticks)

        action = "HOLD"
        decision_tick = tc0
        start_tick = lo
        end_tick = tc1 + _EPISODE_TAIL

        if t_retreat is not None:
            # measure sustained retreat distance
            dist_away = 0.0
            prev = None
            for t in ticks_sorted:
                if t < t_retreat:
                    continue
                if t > t_retreat + 2 * cfg.disengage_quiet_ticks:
                    break
                r = recs[t]
                if not r.get("is_alive") or r.get("x") is None:
                    continue
                if prev is not None and r.get("vx") is not None:
                    if _dot_dir(r["x"], r["y"], r["vx"], r["vy"], ax, ay) < 0:
                        dist_away += math.hypot(r["x"] - prev[0], r["y"] - prev[1])
                prev = (r["x"], r["y"])
            if dist_away >= cfg.fallback_min_dist:
                action = "FALLBACK"
            else:
                action = "DISENGAGE"
            decision_tick = t_retreat
            end_tick = t_retreat + 2 * cfg.disengage_quiet_ticks + _EPISODE_TAIL

            # re-peek: same-angle re-approach after retreat
            yaw_at_contact = recs.get(tc0, {}).get("yaw")
            for t in ticks_sorted:
                if t < t_retreat + cfg.disengage_quiet_ticks:
                    continue
                if t > t_retreat + cfg.disengage_quiet_ticks + cfg.re_peek_window_ticks:
                    break
                r = recs[t]
                if not r.get("is_alive") or r.get("vx") is None:
                    continue
                px, py = r.get("x"), r.get("y")
                if px is None or py is None:
                    continue
                if speed_at(t) >= cfg.v_peek and _dot_dir(px, py, r["vx"], r["vy"], ax, ay) > 0:
                    yaw = r.get("yaw")
                    if yaw_at_contact is not None and yaw is not None:
                        from .state import angle_diff
                        if angle_diff(yaw, yaw_at_contact) <= cfg.re_peek_angle_deg:
                            action = "RE_PEEK"
                            decision_tick = t
                            end_tick = t + _EPISODE_TAIL + 32
                            break
        elif t_app is not None:
            action = "PEEK"
            decision_tick = t_app
            end_tick = tc1 + _EPISODE_TAIL
        elif holding:
            action = "HOLD"
            decision_tick = tc0

        # ---- evidence & confidence ----
        ev_ticks = 0
        ev_ok = 0
        for t in ticks_sorted:
            if t < start_tick:
                continue
            if t > end_tick:
                break
            r = recs[t]
            ev_ticks += 1
            if (r.get("x") is not None and r.get("speed") is not None
                    and r.get("buttons") is not None):
                ev_ok += 1
        ratio = ev_ok / ev_ticks if ev_ticks else 0.0
        confidence = min(1.0, 0.25 + 0.75 * ratio)
        if taken_tick is None:
            confidence = min(confidence, 0.5)

        # ---- significance ----
        rnum = demo.round_of_tick(decision_tick)
        side = demo.side_at_round(steamid, rnum)
        alive_counts = {2: 0, 3: 0}
        for s, t in {p["steamid"]: p["team_number"] for p in demo.players}.items():
            rec = idx.get((s, decision_tick))
            if rec and rec.get("is_alive"):
                alive_counts[t] += 1
        total_alive = alive_counts[2] + alive_counts[3]
        died = death_ticks.get(steamid)
        died_in_ep = died is not None and start_tick <= died <= end_tick + 96
        bomb = any(b["tick"] <= decision_tick for b in demo.events["bombs"]["planted"])
        myrec = recs.get(decision_tick, {})
        hp = myrec.get("health")
        bounds = demo.round_bounds(rnum)
        time_left_s = (bounds[1] - decision_tick) / 64.0 if bounds else 0.0
        sig = (min(1.0, len(ep) / 6.0)
               + (1.5 if died_in_ep else 0.0)
               + (10 - total_alive) * 0.1
               + (0.5 if bomb else 0.0)
               + (0.5 if 0 < time_left_s < 30 else 0.0)
               + (0.5 if hp is not None and hp < 30 else 0.0))

        place = myrec.get("place") or "unknown"
        zone = zone_for(demo.header.get("map_name"), place)

        alternatives = [a for a in TAXONOMY if a != action]
        evidence_events = []
        for e in ep[-8:]:
            evidence_events.append({"type": "damage", "tick": e["t"],
                                    "kind": e["kind"], "weapon": e["d"].get("weapon"),
                                    "dmg_health": e["d"].get("dmg_health")})
        for k in demo.events["kills"]:
            if start_tick <= k["tick"] <= end_tick and k["user_steamid"] in (steamid, opponent):
                evidence_events.append({"type": "kill", "tick": k["tick"],
                                        "victim": k["user_name"], "attacker": k["attacker_name"],
                                        "weapon": k.get("weapon"), "distance": k.get("distance")})

        dp = {
            "dp_id": f"{demo.demo_id}-r{rnum}-{steamid}-{decision_tick}",
            "match_id": demo.demo_id, "round": rnum, "steamid": steamid,
            "player_name": name, "start_tick": start_tick,
            "decision_tick": decision_tick, "end_tick": end_tick,
            "observed_action": action, "alternatives": alternatives,
            "zone": zone, "place": place, "confidence": round(confidence, 3),
            "significance": round(sig, 3),
            "evidence": {"ticks": [start_tick, decision_tick, end_tick],
                         "events": evidence_events,
                         "sources": ["damage_events", "tick_states"]},
            "meta": {"episode": {"tc0": tc0, "tc1": tc1, "n_events": len(ep)},
                     "opponent": opponent, "side": side,
                     "anchor": list(anchor), "t_app": t_app, "t_retreat": t_retreat,
                     "hold_run": hold_run, "died_in_episode": died_in_ep},
        }
        # V1.3.4: the old approach heuristic only creates a candidate.  The
        # exposure pipeline owns the action label and remains honestly UNKNOWN
        # when geometry cannot establish LOS.
        windows = build_contact_window(demo, steamid, opponent, idx, cfg)
        if windows:
            window = min(windows, key=lambda w: abs((w.first_damage_tick or w.first_shot_tick or w.pre_contact_start) - tc0))
            relations = exposure_relations(window, demo.header.get("map_name", ""), idx, geometry, cfg)
            if relations:
                prediction = classify_contact(window, relations, idx, cfg)
                dp = apply_contact_prediction(dp, prediction)
                dp["meta"]["contact"]["window"] = {
                    "pre_contact_start": window.pre_contact_start,
                    "visibility_tick": window.visibility_tick,
                    "first_shot_tick": window.first_shot_tick,
                    "first_damage_tick": window.first_damage_tick,
                    "resolution_tick": window.resolution_tick,
                }
                dp["meta"]["contact"]["geometry"] = geometry.get_metadata()
        dps.append(dp)
    return dps


def build_state(demo: IngestedDemo, dp: dict, cfg: Config, idx: dict) -> dict:
    """Build GameState (ground truth + player-known) + feature vector for a DP."""
    steamid = dp["steamid"]
    rnum = dp["round"]
    tick = dp["decision_tick"]
    map_name = demo.header.get("map_name")
    side = demo.side_at_round(steamid, rnum)

    teams = {p["steamid"]: p["team_number"] for p in demo.players}
    my_team = teams.get(steamid, -1)
    alive_counts = {2: 0, 3: 0}
    for s, t in teams.items():
        rec = idx.get((s, tick))
        if rec and rec.get("is_alive"):
            alive_counts[t] += 1
    team_alive = alive_counts.get(my_team, 0)
    enemy_alive = alive_counts.get(3 if my_team == 2 else 2, 0)

    pub = PublicInfoBuilder(demo, cfg).build(steamid, rnum, tick, idx, teams)
    known = KnownStateBuilder(demo, cfg, idx).build(steamid, rnum, tick)
    gt = build_ground_truth(demo, idx, steamid, tick)
    recent_contact = any(d["tick"] >= tick - 128 for d in demo.events["damages"]
                         if d["user_steamid"] == steamid and d["tick"] <= tick)

    features, labels = build_features(
        known, pub, cfg, map_name, side, dp["zone"], dp["observed_action"],
        recent_contact, known.get("teammate_near", 0), known.get("teammate_mid", 0),
        team_alive, enemy_alive)

    return {
        "dp_id": dp["dp_id"], "match_id": demo.demo_id, "round": rnum,
        "decision_tick": tick, "map": map_name, "side": side,
        "zone": dp["zone"], "observed_action": dp["observed_action"],
        "features": features, "labels": labels,
        "known_state": known, "public_info": pub, "ground_truth": gt,
    }


def build_outcome(demo: IngestedDemo, dp: dict, cfg: Config) -> dict:
    """survival@W / duel result / round win for a DP (fixed windows)."""
    steamid = dp["steamid"]
    death_ticks = {}
    for k in demo.events["kills"]:
        if k.get("user_steamid") is not None:
            death_ticks[int(k["user_steamid"])] = int(k["tick"])
    death_tick = death_ticks.get(steamid)
    W = cfg.outcome_window_ticks
    survival = 1
    if death_tick is not None and death_tick - dp["decision_tick"] <= W:
        survival = 0
    opponent = dp["meta"].get("opponent")
    o_death = death_ticks.get(opponent)
    duel_result = "undefined"
    if death_tick is not None and death_tick - dp["decision_tick"] <= W:
        duel_result = "lost"
    elif o_death is not None and o_death - dp["decision_tick"] <= W:
        duel_result = "won"
    rnum = dp["round"]
    side = demo.side_at_round(steamid, rnum)
    winner = next((r["winner"] for r in demo.rounds if r["round"] == rnum), None)
    round_win = 1 if (winner and side != "unknown" and winner == side) else 0
    return {
        "dp_id": dp["dp_id"], "survival": survival,
        "survival_window_ticks": W, "death_tick": death_tick,
        "duel_result": duel_result, "duel_opponent": str(opponent),
        "round_win": round_win,
    }


def analyze_match(demo: IngestedDemo, cfg: Config, db) -> list[dict]:
    """Detect DPs for all players, dedupe by episode, keep top-N, persist."""
    idx = build_tick_index(demo)
    all_dps = []
    for p in demo.players:
        if p["team_number"] not in (2, 3):
            continue
        all_dps += detect_for_player(demo, p["steamid"], cfg, idx)
    # dedupe: same player + overlapping windows -> keep highest significance
    all_dps.sort(key=lambda d: (d["steamid"], d["start_tick"]))
    kept = []
    for d in all_dps:
        if kept and kept[-1]["steamid"] == d["steamid"] and \
                d["start_tick"] - kept[-1]["end_tick"] < cfg.episode_merge_ticks:
            if d["significance"] > kept[-1]["significance"]:
                kept[-1] = d
        else:
            kept.append(d)
    kept.sort(key=lambda d: d["significance"], reverse=True)
    kept = kept[:cfg.max_dp_per_match]
    kept.sort(key=lambda d: d["decision_tick"])

    for dp in kept:
        state = build_state(demo, dp, cfg, idx)
        outcome = build_outcome(demo, dp, cfg)
        db.insert_dp(dp, state, outcome)
    db.rebuild_coverage()
    return kept
