"""DecisionEpisode (V1.3 spec §4-§28, §57): the primary analysis unit.

A DecisionEpisode wraps a *meaningful choice opportunity* (not just deaths):
first contact, enemy retreat, advantage formed, bomb info updated, plant /
trade / disengage opportunities. MVP families (spec §57):

    CONTACT_RESPONSE     first meaningful enemy contact
    ADVANTAGE_PRESERVATION  team gains meaningful alive advantage
    OBJECTIVE_COMMITMENT plant / defuse / objective opportunity

Each episode carries: MacroContext (why it matters), LocalContext (what the
player sees), CandidateActions (feasibility-filtered alternatives), the
observed action, DecisionEvaluation and Actionability.

Principles: context before judgment; alternatives before criticism;
feasibility before recommendation; unknown before hallucination (spec §104).
"""
from __future__ import annotations

import math
import time
import uuid

from .config import Config
from .db import DB
from .ingest import IngestedDemo
from .state import build_tick_index, pos_at, build_ground_truth
from .context import build_temporal_context
from .intent import detect_commitment, detect_role, classify_intent
from .feasibility import action_feasibility
from .engagement import build_engagement_context
from .macro import compute_macro_context
from .tradeability import compute_tradeability, NULL_GEOMETRY
from .state import KnownStateBuilder

FAMILIES = ("CONTACT_RESPONSE", "ADVANTAGE_PRESERVATION", "OBJECTIVE_COMMITMENT")

# MVP action taxonomy (spec §9)
ACTIONS = ("PEEK", "HOLD", "HIDE", "RE_PEEK", "DISENGAGE", "REPOSITION",
           "FLASH", "PLANT", "TRADE")

ACTIONABILITY_LEVELS = ("HIGHLY_ACTIONABLE", "ACTIONABLE", "WEAKLY_ACTIONABLE",
                        "NOT_ACTIONABLE", "INSUFFICIENT_EVIDENCE")

# candidate families per episode family
_FAMILY_CANDIDATES = {
    "CONTACT_RESPONSE": ["PEEK", "HOLD", "HIDE", "DISENGAGE", "FLASH", "REPOSITION"],
    "ADVANTAGE_PRESERVATION": ["HOLD", "PEEK", "DISENGAGE", "FLASH", "REPOSITION"],
    "OBJECTIVE_COMMITMENT": ["PLANT", "TRADE", "HOLD", "REPOSITION"],
}


def detect_opportunities(demo: IngestedDemo, cfg: Config, idx: dict,
                         known_builder: KnownStateBuilder) -> list[dict]:
    """Deterministic DecisionOpportunity detection (spec §6-§7, §59)."""
    opps = []
    teams = {p["steamid"]: p["team_number"] for p in demo.players}
    death_tick = {}
    for k in demo.events["kills"]:
        if k.get("user_steamid") is not None:
            death_tick[int(k["user_steamid"])] = int(k["tick"])

    # ---- per player, per round ----
    for p in demo.players:
        sid = p["steamid"]
        if p["team_number"] not in (2, 3):
            continue
        my_team = p["team_number"]
        enemy_team = 3 if my_team == 2 else 2

        # 1) CONTACT_RESPONSE: first damage contact of a window (reuse DP logic)
        contacts = sorted(
            ((d["tick"], d) for d in demo.events["damages"]
             if d["user_steamid"] == sid or d["attacker_steamid"] == sid),
            key=lambda x: x[0])
        seen_contact_window = None
        for t, d in contacts:
            if seen_contact_window and t - seen_contact_window <= cfg.episode_merge_ticks:
                continue
            seen_contact_window = t
            rec = idx.get((sid, t))
            if not rec or not rec.get("is_alive"):
                continue
            # warmup (round 0 — platform 练枪/热身) is not a real match round
            if demo.round_of_tick(t) < 1:
                continue
            opps.append({"type": "CONTACT_RESPONSE", "anchor_tick": t, "steamid": sid,
                         "trigger": "first_damage_contact", "confidence": 0.7})

        # 2) ADVANTAGE_PRESERVATION: team crosses to numeric advantage
        prev_diff = None
        for r in demo.rounds:
            for t in range(r["start_tick"] + 16, r["end_tick"], 32):
                rec = idx.get((sid, t))
                if not rec or not rec.get("is_alive"):
                    continue
                alive = {2: 0, 3: 0}
                for s, tm in teams.items():
                    r2 = idx.get((s, t))
                    if r2 and r2.get("is_alive"):
                        alive[tm] = alive.get(tm, 0) + 1
                diff = alive.get(my_team, 0) - alive.get(enemy_team, 0)
                if prev_diff is not None and prev_diff <= 0 and diff >= 1:
                    opps.append({"type": "ADVANTAGE_PRESERVATION", "anchor_tick": t,
                                 "steamid": sid, "trigger": "advantage_gained",
                                 "confidence": 0.65})
                prev_diff = diff

        # 3) OBJECTIVE_COMMITMENT: plant/defuse started near player
        for ev in demo.events.get("plants_start", []) + demo.events.get("defuses_start", []):
            t = ev["tick"]
            if demo.round_of_tick(t) < 1:   # skip warmup
                continue
            actor = ev.get("user_steamid")
            rec = idx.get((sid, t))
            if not rec or not rec.get("is_alive"):
                continue
            if actor == sid:
                opps.append({"type": "OBJECTIVE_COMMITMENT", "anchor_tick": t,
                             "steamid": sid, "trigger": "own_plant_start",
                             "confidence": 0.9})
            elif actor in teams and teams[actor] == my_team:
                mypos = pos_at(idx, sid, t)
                apos = pos_at(idx, actor, t)
                if mypos and apos and math.hypot(apos[0] - mypos[0], apos[1] - mypos[1]) <= 3000.0:
                    opps.append({"type": "OBJECTIVE_COMMITMENT", "anchor_tick": t,
                                 "steamid": sid, "trigger": "teammate_plant_start",
                                 "confidence": 0.6})

    # dedupe: same (steamid, type) within merge window -> keep first
    out = []
    for o in sorted(opps, key=lambda x: (x["steamid"], x["anchor_tick"])):
        if out and out[-1]["steamid"] == o["steamid"] and \
                o["type"] == out[-1]["type"] and \
                o["anchor_tick"] - out[-1]["anchor_tick"] < cfg.episode_merge_ticks * 2:
            continue
        out.append(o)
    return out


def _local_context(demo, cfg, idx, known, tc, steamid, tick) -> dict:
    """LocalContext (spec §25-§28): what the player sees and can do."""
    rec = idx.get((steamid, tick)) or {}
    mypos = pos_at(idx, steamid, tick)
    trade = compute_tradeability(tc, cfg, NULL_GEOMETRY)
    nearby_enemies = []
    for e, v in (known.get("last_seen_enemies") or {}).items():
        pos = v.get("pos")
        if pos and mypos:
            d = math.hypot(pos[0] - mypos[0], pos[1] - mypos[1])
            if d <= 2500.0:
                nearby_enemies.append({"enemy": e, "dist": round(d, 1),
                                       "zone": v.get("zone"),
                                       "source": v.get("source"),
                                       "age_ticks": tick - v["tick"]})
    # local exposure primitive (spec §28): visible threat lanes approximated
    # by known enemies within FOV-ish range + recent damage
    local_exposure = {
        "enemy_los_count": len(nearby_enemies),
        "cover_available": None,       # no geometry in V1.3 -> UNKNOWN
        "escape_route": None,
        "note": "geometry provider not configured (AwpyGeometry optional)",
    }
    return {
        "player_position": mypos,
        "zone": rec.get("place"),
        "cover": None,
        "los": None,
        "nearby_teammates": [m for m in tc.mates if m["dist"] <= 2500.0],
        "nearby_known_enemies": nearby_enemies,
        "tradeability": trade,
        "weapon": rec.get("weapon_def"),
        "weapon_name": rec.get("weapon_name"),
        "utility": {"flash": None},    # inventory not parsed in V1.3
        "hp": rec.get("health"),
        "movement_speed": rec.get("speed"),
        "view_yaw": rec.get("yaw"),
        "recent_contact_ticks": tc.events.get("damage_taken", 0) + tc.events.get("damage_dealt", 0),
        "enemy_retreat_direction": _retreat_dir(demo, idx, steamid, tick),
        "local_exposure": local_exposure,
    }


def _retreat_dir(demo, idx, steamid, tick):
    """Approximate: direction of the last known enemy movement away (UNKNOWN)."""
    return None


def _candidate_actions(demo, cfg, tc, commitment, family, known) -> list[dict]:
    """Generate MVP candidates with feasibility first (spec §10-§13)."""
    feas = action_feasibility(commitment, cfg, tc)
    out = []
    for action in _FAMILY_CANDIDATES.get(family, ACTIONS):
        f = feas.get(action, "FEASIBLE")
        reason = ""
        if action in ("FLASH",) and not known.get("utility_flash", True):
            f, reason = "UNAVAILABLE", "no flash in inventory (V1.3: unknown -> assume available)"
        if action in ("PLANT",) and not _has_bomb(demo, cfg, tc):
            f, reason = "UNAVAILABLE", "bomb not on player"
        if action in ("TRADE",) and commitment in ("PLANT_COMMITTED", "DEFUSE_COMMITTED"):
            f, reason = "UNAVAILABLE", "commitment blocks immediate trade"
        out.append({
            "action": action, "feasibility": f, "feasibility_reason": reason,
            "expected_risk": None, "expected_information_gain": None,
            "expected_team_value": None, "expected_objective_value": None,
            "evidence": {}, "confidence": 0.5,
        })
    return out


def _has_bomb(demo, cfg, tc) -> bool:
    """Bomb on this player: planted already -> no; carrier = this player."""
    planted = any(b["tick"] <= tc.tick for b in demo.events["bombs"]["planted"])
    if planted:
        return False
    for b in demo.events.get("plants_start", []):
        if b["tick"] <= tc.tick:
            return b.get("user_steamid") == tc.steamid
    return False


def _observed_action(demo, cfg, tc, idx, steamid, tick, family,
                     dp_lookup=None) -> str:
    """Observed action from DP/decision classifiers (spec §60): reuse the
    contact-based classifier for CONTACT_RESPONSE; fall back to intent.
    dp_lookup: {steamid: [dps]} precomputed once per demo (perf guard)."""
    if dp_lookup is not None:
        dps = dp_lookup.get(steamid, [])
        for dp in dps:
            if dp["decision_tick"] == tick or abs(dp["decision_tick"] - tick) <= 48:
                a = dp["observed_action"]
                if a == "FALLBACK":
                    return "REPOSITION"
                return a
    else:
        from .decision import detect_for_player  # reuse existing classifier
        try:
            dps = detect_for_player(demo, steamid, cfg, idx)
            for dp in dps:
                if dp["decision_tick"] == tick or abs(dp["decision_tick"] - tick) <= 48:
                    a = dp["observed_action"]
                    if a == "FALLBACK":
                        return "REPOSITION"
                    return a
        except Exception:  # noqa: BLE001
            pass
    intent, _, _ = classify_intent(demo, cfg, tc, steamid, tick)
    mapping = {"ROTATE": "REPOSITION", "SOFT_ROTATE": "REPOSITION",
               "REPOSITION": "REPOSITION", "HOLD": "HOLD",
               "GATHER_INFO": "PEEK", "CONTEST": "PEEK",
               "PLANT": "PLANT", "TRADE": "TRADE"}
    return mapping.get(intent, "HOLD")


def _precompute_dp_lookup(demo, cfg, idx) -> dict:
    """Detect DPs once per player, grouped by steamid (spec §60 reuse)."""
    from .decision import detect_for_player
    lookup = {}
    for p in demo.players:
        if p["team_number"] not in (2, 3):
            continue
        try:
            lookup[p["steamid"]] = detect_for_player(demo, p["steamid"], cfg, idx)
        except Exception:  # noqa: BLE001
            lookup[p["steamid"]] = []
    return lookup


def build_episode(demo, cfg, db, idx, known_builder, opp: dict,
                  dp_lookup=None) -> dict:
    """Assemble a full DecisionEpisode for one opportunity."""
    sid = opp["steamid"]
    tick = opp["anchor_tick"]
    family = opp["type"]
    rnum = demo.round_of_tick(tick)

    known = known_builder.build(sid, rnum, tick)
    tc = build_temporal_context(demo, cfg, idx, sid, tick, known_state=known)
    commitment = detect_commitment(demo, cfg, sid, tick)
    role, role_dist = detect_role(demo, cfg, idx, sid, tick, commitment, tc)
    intent, intent_conf, intent_dist = classify_intent(demo, cfg, tc, sid, tick)
    macro = compute_macro_context(tc, cfg)
    local = _local_context(demo, cfg, idx, known, tc, sid, tick)
    candidates = _candidate_actions(demo, cfg, tc, commitment, family, known)
    observed = _observed_action(demo, cfg, tc, idx, sid, tick, family,
                                dp_lookup=dp_lookup)

    # V1.3.1: engagement + duel layers (spec §4-§5, §9-§60) — only when this
    # episode is fight-relevant and a duel window exists around the anchor.
    engagement_ctx = None
    duel = None
    if family in ("CONTACT_RESPONSE", "ADVANTAGE_PRESERVATION"):
        duel = _find_duel(demo, cfg, idx, known_builder, sid, tick)
        engagement_ctx = build_engagement_context(
            demo, cfg, tc, known, duel=duel, observed_action=observed)

    episode_id = f"{demo.demo_id}-{family}-{sid}-{tick}"
    return {
        "id": episode_id,
        "match_id": demo.demo_id, "round": rnum, "player_id": sid,
        "family": family,
        "start_tick": max(0, tick - cfg.context_window_ticks),
        "anchor_tick": tick,
        "end_tick": tick + 256,
        "temporal_context": tc.summary(),
        "player_known_state": known,
        "macro_context": macro,
        "local_context": local,
        "commitment_state": commitment,
        "situational_role": role,
        "intent": intent,
        "observed_action": observed,
        "feasibility": {k: v for k, v in action_feasibility(commitment, cfg, tc).items()},
        "immediate_result": _immediate_result(demo, idx, sid, tick),
        "state_value_before": None, "state_value_after": None,
        "decision_evaluation": "INSUFFICIENT_EVIDENCE",
        "actionability": "INSUFFICIENT_EVIDENCE",
        "decision_domain": ("OBJECTIVE" if family == "OBJECTIVE_COMMITMENT"
                            else "ENGAGEMENT" if engagement_ctx else "STRATEGIC_LOCAL"),
        "engagement_id": None,
        "engagement_context": engagement_ctx,
        "duel_state_sequence": (duel or {}).get("sequence"),
        "weapon_matchup": (engagement_ctx or {}).get("weapon_matchup"),
        "information_advantage": (engagement_ctx or {}).get("information_advantage"),
        "duel_phase": (duel or {}).get("phase"),
        "confidence": round(0.4 + 0.3 * opp["confidence"], 3),
        "extractor_version": "v1.3.1-1",
        "context_version": "v1.3-1",
        "rule_version": "v1.3.1-1",
        "model_provider_version": "null",
        "geometry_version": "null",
        "computed_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "_known": known, "_tc": tc, "_candidates": candidates,
        "_engagement": engagement_ctx, "_duel": duel,
    }


def _find_duel(demo, cfg, idx, known_builder, sid, tick) -> dict | None:
    """Extract the duel sequence around the anchor tick (spec §32-§35).
    Window-local only; bounded; no full-match per-tick cost (spec §113)."""
    from .duel import detect_engagement_windows, extract_duel_state_sequence
    contacts = [d["tick"] for d in demo.events["damages"]
                if d["user_steamid"] == sid or d["attacker_steamid"] == sid]
    if not contacts:
        return None
    windows = detect_engagement_windows(demo, cfg, idx, sid, contacts)
    win = next((w for w in windows if w["start"] <= tick <= w["end"]), None)
    if not win:
        return None
    # duel opponent: the other party in the contact window
    opponent = None
    for d in demo.events["damages"]:
        if win["start"] <= d["tick"] <= win["end"]:
            if d["user_steamid"] == sid:
                opponent = d["attacker_steamid"]
                break
            if d["attacker_steamid"] == sid:
                opponent = d["user_steamid"]
                break
    return extract_duel_state_sequence(demo, cfg, idx, sid, win,
                                       enemy_steamid=opponent)


def _immediate_result(demo, idx, sid, tick) -> dict:
    """Immediate outcome window (3s): survival + kills + round result.
    NEVER used for decision evaluation (spec §19)."""
    death_tick = None
    for k in demo.events["kills"]:
        if k["user_steamid"] == sid and k["tick"] >= tick:
            death_tick = k["tick"]
            break
    survived = death_tick is None or (death_tick - tick) > 192
    kill_after = any(k["tick"] >= tick and k["tick"] <= tick + 192
                     and k["attacker_steamid"] == sid for k in demo.events["kills"])
    return {
        "survived_3s": bool(survived),
        "kill_within_3s": bool(kill_after),
        "death_tick": death_tick,
        "round_result": demo.rounds[demo.round_of_tick(tick) - 1].get("winner")
        if 0 < demo.round_of_tick(tick) <= len(demo.rounds) else None,
    }


def run_episodes(demo: IngestedDemo, cfg: Config, db: DB,
                 model_provider=None) -> dict:
    """Detect + persist all DecisionEpisodes for a demo (idempotent)."""
    idx = build_tick_index(demo)
    known_builder = KnownStateBuilder(demo, cfg, idx)
    db.delete_decision_episodes(demo.demo_id)
    dp_lookup = _precompute_dp_lookup(demo, cfg, idx)
    opps = detect_opportunities(demo, cfg, idx, known_builder)
    episodes = []
    for opp in opps:
        try:
            ep = build_episode(demo, cfg, db, idx, known_builder, opp,
                               dp_lookup=dp_lookup)
        except Exception:  # noqa: BLE001
            continue
        # real retrieval features for historical/personal evidence (spec §62)
        ep["_state"] = _retrieval_state(demo, cfg, ep)
        # Phase E: evidence + Phase F/G: evaluation + actionability
        from .evidence import build_evidence, evidence_sufficiency
        from .evaluate import evaluate_decision, actionability
        cands = ep.get("_candidates", [])
        summary, evidence_rows = build_evidence(
            demo, cfg, db, ep, cands, model_provider=model_provider)
        ep["evidence_sufficiency"] = evidence_sufficiency(ep)
        ep["decision_evaluation"] = evaluate_decision(ep, cfg, summary,
                                                      sufficiency=ep["evidence_sufficiency"])
        ep["actionability"] = actionability(ep, cfg)
        # V1.3.1 three-level evaluation (spec §73/§102)
        eng = ep.get("_engagement")
        duel = ep.get("_duel")
        from .evaluate import engagement_evaluation, execution_evaluation
        from .duel import execution_primitives, movement_effect
        from .weapons import engagement_class, range_bucket, name_from_def
        ep["strategic_evaluation"] = ep["decision_evaluation"]
        # CS-NET state-value evidence (spec §65): before/after/delta. The
        # provider consumes a canonical state frame; failures degrade to None
        # and never affect the evaluation (spec §66).
        if model_provider is not None:
            try:
                ev = model_provider.predict_win_probability(
                    ep["_state"], match_id=ep["match_id"], round=ep["round"],
                    tick=ep["anchor_tick"])
                if ev.prediction is not None:
                    ep["state_value_before"] = round(float(ev.prediction), 4)
            except Exception:  # noqa: BLE001
                pass
        if eng:
            ep["engagement_evaluation"] = engagement_evaluation(ep, cfg, eng)
            ep["engagement_method"] = eng.get("engagement_method")
        if duel:
            matchup = (eng or {}).get("weapon_matchup") or {}
            self_name = matchup.get("self_weapon", "unknown")
            enemy_cls = matchup.get("enemy_weapon_class", "UNKNOWN")
            rb = matchup.get("range_bucket", "UNKNOWN")
            ep["execution_primitives"] = execution_primitives(demo, cfg, duel, ep.get("_tc"))
            ep["movement_effect"] = movement_effect(
                demo, cfg, duel, ep.get("_tc"),
                engagement_class(self_name), rb)
            # V1.3.3 supplement: movement purpose + contextual moving-shot eval
            from .duel import (detect_movement_purpose, moving_shot_evaluation)
            ep["movement_purpose"] = detect_movement_purpose(
                duel, ep.get("_tc"), engagement_class(self_name), rb,
                ep["movement_effect"])
            if "SHOT_WHILE_MOVING" in ep["execution_primitives"]:
                ep["moving_shot_evaluation"] = moving_shot_evaluation(
                    duel, ep.get("_tc"), engagement_class(self_name), rb,
                    enemy_cls, ep["movement_effect"])
            ep["execution_evaluation"] = execution_evaluation(ep, cfg, duel, eng)
            ep["duel_phase"] = duel.get("phase")
        # engagement_id: group the CONTACT_RESPONSE episode as the anchor of
        # one duel; related ADVANTAGE/OBJECTIVE episodes link to it (spec §115)
        if ep["family"] == "CONTACT_RESPONSE":
            ep["engagement_id"] = f"{demo.demo_id}-eng-{ep['player_id']}-{ep['anchor_tick']}"
        # persist episode + candidates + evidence
        for rank, c in enumerate(cands, start=1):
            db.upsert_decision_candidate({
                "id": f"{ep['id']}-{c['action']}", "episode_id": ep["id"],
                "action": c["action"], "feasibility": c["feasibility"],
                "feasibility_reason": c.get("feasibility_reason", ""),
                "expected_risk": (summary.get(c["action"]) or {}).get("risk"),
                "expected_information_gain": None,
                "expected_team_value": (summary.get(c["action"]) or {}).get("value"),
                "expected_objective_value": None,
                "evidence": summary.get(c["action"], {}), "confidence": c.get("confidence"),
                "rank": rank})
        for ev in evidence_rows:
            db.upsert_decision_evidence(ev)
        db.upsert_decision_episode(ep)
        episodes.append(ep)
    # link non-contact episodes to the nearest engagement of the same player
    # (spec §115-§116: one duel = one card, not three duplicate cards)
    contact_by_player = {}
    for ep in episodes:
        if ep.get("engagement_id"):
            contact_by_player.setdefault(ep["player_id"], []).append(ep)
    for ep in episodes:
        if ep.get("engagement_id") or ep["family"] == "OBJECTIVE_COMMITMENT":
            continue
        near = contact_by_player.get(ep["player_id"], [])
        if not near:
            continue
        best = min(near, key=lambda c: abs(c["anchor_tick"] - ep["anchor_tick"]))
        if abs(best["anchor_tick"] - ep["anchor_tick"]) <= 512:
            ep["engagement_id"] = best["engagement_id"]
            db.upsert_decision_episode(ep)
    return {"opportunities": len(opps), "episodes": len(episodes),
            "families": _family_dist(episodes)}


def _family_dist(episodes: list[dict]) -> dict:
    from collections import Counter
    return dict(Counter(e["family"] for e in episodes))


def _retrieval_state(demo, cfg, ep: dict) -> dict:
    """Real retrieval features for the evidence engine (spec §62)."""
    from .features import build_features
    known = ep.get("player_known_state") or {}
    macro = ep.get("macro_context") or {}
    local = ep.get("local_context") or {}
    myrec_place = (local.get("zone") or "unknown")
    side = demo.side_at_round(ep["player_id"], ep["round"])
    recent_contact = bool((local.get("recent_contact_ticks") or 0) > 0)
    team_alive = macro.get("team_structure", {}).get("team_alive")
    enemy_alive = macro.get("team_structure", {}).get("enemy_alive")
    features, labels = build_features(
        known, {"time_remaining_s": macro.get("round_time"),
                "bomb": {"planted_site": (macro.get("bomb_state") or {}).get("site")}},
        cfg, demo.header.get("map_name"), side, myrec_place,
        ep.get("observed_action", "HOLD"), recent_contact,
        known.get("teammate_near", 0), known.get("teammate_mid", 0),
        team_alive or 5, enemy_alive or 5)
    return {
        "dp_id": f"{ep['id']}-state", "match_id": ep["match_id"],
        "round": ep["round"], "decision_tick": ep["anchor_tick"],
        "map": demo.header.get("map_name"), "side": side,
        "zone": myrec_place, "observed_action": ep.get("observed_action"),
        "features": features, "labels": labels,
        "known_state": known, "public_info": {}, "ground_truth": {},
    }
