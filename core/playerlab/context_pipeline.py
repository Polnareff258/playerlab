"""V1.2.1 context pipeline: per important event compute TemporalContext ->
Commitment -> SituationalRole -> Intent (rule baseline) -> ActionFeasibility
-> Tradeability -> ResponsibilityAttribution; persist context_events +
intent_samples (KnownState-grounded); upgrade root causes.

Deterministic; no future data in any classification (hindsight guard).
IntentSample v2 carries known_state_sequence / information_sequence and
split metadata (match_id / round_id / episode_id) for leakage-safe
train/test splits (spec §5/§19).
"""
from __future__ import annotations

import time
import uuid

from .config import Config
from .db import DB
from .ingest import IngestedDemo
from .state import (build_tick_index, KnownStateBuilder)
from .context import build_temporal_context
from .intent import detect_commitment, detect_role, classify_intent
from .feasibility import action_feasibility
from .responsibility import attribute_responsibility
from .tradeability import compute_tradeability, NULL_GEOMETRY


def _anchor_events(demo: IngestedDemo, db: DB) -> list[tuple]:
    """Anchor ticks worth context analysis: deaths + DP decision ticks.
    Round 0 (warmup/knife before the first real round) is excluded — the
    match has not started (cs-demo-manager counts rounds only after start)."""
    anchors = []
    players = {p["steamid"] for p in demo.players}
    for k in demo.events["kills"]:
        if k["user_steamid"] in players and demo.round_of_tick(k["tick"]) >= 1:
            anchors.append((k["tick"], k["user_steamid"], "death", f"death-{k['tick']}"))
    for dp in db.get_dps(demo.demo_id):
        if demo.round_of_tick(dp["decision_tick"]) >= 1:
            anchors.append((dp["decision_tick"], dp["steamid"], "dp", dp["dp_id"]))
    return anchors


def run_context(demo: IngestedDemo, cfg: Config, db: DB) -> dict:
    idx = build_tick_index(demo)
    # idempotent per match: stale rows from earlier runs are removed first
    db.conn.execute("DELETE FROM context_events WHERE match_id=?", (demo.demo_id,))
    db.conn.execute("DELETE FROM intent_samples WHERE match_id=?", (demo.demo_id,))
    db.conn.commit()
    known_builder = KnownStateBuilder(demo, cfg, idx)
    teams = {p["steamid"]: p["team_number"] for p in demo.players}
    responsibility_map, commitment_map, role_map = {}, {}, {}
    events_persisted = 0
    seen = set()
    for tick, steamid, anchor, ref in _anchor_events(demo, db):
        key = (steamid, tick)
        if key in seen:
            continue
        seen.add(key)
        rnum = demo.round_of_tick(tick)
        # player-known state is the ONLY classification input (hindsight guard)
        known_state = known_builder.build(steamid, rnum, tick)
        tc = build_temporal_context(demo, cfg, idx, steamid, tick, known_state=known_state)
        commitment = detect_commitment(demo, cfg, steamid, tick)
        role, role_dist = detect_role(demo, cfg, idx, steamid, tick, commitment, tc)
        intent, intent_conf, intent_dist = classify_intent(demo, cfg, tc, steamid, tick)
        feas = action_feasibility(commitment, cfg, tc)
        tc.feasibility = feas
        trade = compute_tradeability(tc, cfg, NULL_GEOMETRY)
        resp = attribute_responsibility(demo, cfg, tc, steamid, tick,
                                        decision_eval="UNKNOWN" if anchor == "death" else None)
        responsibility_map[key] = resp
        commitment_map[key] = commitment
        role_map[key] = role
        summary = tc.summary()
        summary["tradeability"] = trade
        summary["responsibility_gate"] = resp.get("gate")
        db.upsert_context_event({
            "id": f"{demo.demo_id}-{anchor}-{steamid}-{tick}", "match_id": demo.demo_id,
            "round": rnum, "tick": tick, "steamid": steamid,
            "anchor": anchor, "commitment": commitment, "role": role,
            "role_dist": role_dist, "intent": intent, "intent_conf": intent_conf,
            "intent_dist": intent_dist, "feasibility": feas,
            "responsibility": resp["attribution"],
            "temporal_summary": summary, "event_ref": ref,
            "computed_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        })
        events_persisted += 1
    # intent samples: 3 anchors per player-round (30/60/85% of round)
    samples = 0
    for r in demo.rounds:
        start, end = r["start_tick"], r["end_tick"]
        fracs = (0.3, 0.6, 0.85)
        for p in demo.players:
            if p["team_number"] not in (2, 3):
                continue
            for f in fracs:
                t = int(start + (end - start) * f)
                rnum = r["round"]
                known_state = known_builder.build(p["steamid"], rnum, t)
                tc = build_temporal_context(demo, cfg, idx, p["steamid"], t,
                                            known_state=known_state)
                commitment = detect_commitment(demo, cfg, p["steamid"], t)
                role, _ = detect_role(demo, cfg, idx, p["steamid"], t, commitment, tc)
                intent, intent_conf, _ = classify_intent(demo, cfg, tc, p["steamid"], t)
                # split metadata: match / round / episode (leakage prevention §19)
                episode_id = f"{demo.demo_id}-r{rnum}-{p['steamid']}"
                sample = {
                    "id": f"{demo.demo_id}-r{rnum}-{p['steamid']}-{t}",
                    "match_id": demo.demo_id, "round": rnum, "anchor_tick": t,
                    "start_tick": max(start, t - cfg.context_window_ticks),
                    "end_tick": t, "feature_sequence": tc.feature_sequence(),
                    "hard_events": tc.events, "player_known_state": known_state,
                    "commitment_state": commitment, "situational_role": role,
                    "rule_prediction": intent, "rule_confidence": intent_conf,
                    "source": "rule-baseline",
                    "round_id": f"{demo.demo_id}-r{rnum}",
                    "episode_id": episode_id,
                    "motion_features": tc.feature_sequence(),
                    "structural_features": _structural_features(tc),
                    "known_state_features": _known_state_features(tc, known_state),
                    "information_features": _information_features(tc),
                    "known_state_sequence": _known_state_sequence(tc, known_state),
                    "information_sequence": _information_sequence(tc),
                    "extractor_version": "v1.2.1-1",
                }
                db.upsert_intent_sample(sample)
                samples += 1
    return {"context_events": events_persisted, "intent_samples": samples,
            "intent_distribution": _count(db.get_intent_samples()),
            "responsibility_map": responsibility_map,
            "commitment_map": commitment_map, "role_map": role_map}


def _count(samples: list[dict]) -> dict:
    from collections import Counter
    return dict(Counter(s.get("rule_prediction") for s in samples))


def _structural_features(tc) -> dict:
    return {
        "zone_crossings": tc.zone_crossings,
        "zones": dict(tc.zone_set),
        "team_alive": tc.team_alive, "enemy_alive": tc.enemy_alive,
        "nearest_teammate_dist": tc.nearest_teammate_dist,
        "bomb_planted": tc.bomb_planted, "bomb_site": tc.bomb_site,
        "objective_urgency": tc.objective_urgency,
        "round_time_s": tc.round_time_s,
    }


def _known_state_features(tc, known_state: dict) -> dict:
    """Aggregated (per-sample) known-state summary for the feature vector."""
    return {
        "n_known_enemies": tc.n_known_enemies,
        "known_enemy_zones": known_state.get("known_enemy_zones", []),
        "known_enemy_directions": known_state.get("known_enemy_directions", []),
        "time_since_last_known_enemy_update": known_state.get("time_since_last_known_enemy_update"),
        "time_since_visual_contact": known_state.get("time_since_visual_contact"),
        "time_since_damage_contact": known_state.get("time_since_damage_contact"),
        "bomb_known": known_state.get("bomb_known", False),
        "bomb_zone": known_state.get("bomb_zone"),
        "bomb_confidence": known_state.get("bomb_confidence", 0.0),
        "teammate_contact_count": known_state.get("teammate_contact_count", 0),
        "recent_teammate_kill": known_state.get("recent_teammate_kill", False),
        "recent_teammate_death": known_state.get("recent_teammate_death", False),
        "nearest_known_enemy": known_state.get("nearest_known_enemy"),
        "known_spread": known_state.get("known_spread", 0.0),
    }


def _information_features(tc) -> dict:
    return {
        "strength": getattr(tc, "information_strength", "NONE"),
        "strength_score": getattr(tc, "information_strength_score", 0.0),
        "direction": getattr(tc, "information_direction", "UNKNOWN"),
        "direction_confidence": getattr(tc, "information_direction_confidence", 0.0),
        "components": getattr(tc, "information_components", {}),
    }


def _known_state_sequence(tc, known_state: dict) -> list:
    """Per-timestep known-state snapshots (compact; for sequence models)."""
    seq = []
    for s in tc.trajectory:
        seq.append({
            "t": s["t"],
            "n_known_enemies": tc.n_known_enemies,
            "nearest_known_enemy": known_state.get("nearest_known_enemy"),
            "bomb_known": known_state.get("bomb_known", False),
            "teammate_contact_count": known_state.get("teammate_contact_count", 0),
            "time_since_visual_contact": known_state.get("time_since_visual_contact"),
        })
    return seq


def _information_sequence(tc) -> list:
    """Per-timestep information strength/direction (the 'why' signal)."""
    seq = []
    for s in tc.trajectory:
        seq.append({
            "t": s["t"],
            "strength": getattr(tc, "information_strength", "NONE"),
            "strength_score": getattr(tc, "information_strength_score", 0.0),
            "direction": getattr(tc, "information_direction", "UNKNOWN"),
            "direction_confidence": getattr(tc, "information_direction_confidence", 0.0),
        })
    return seq
