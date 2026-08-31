"""V1.2 context pipeline: per important event compute TemporalContext ->
Commitment -> SituationalRole -> Intent (rule baseline) -> ActionFeasibility
-> ResponsibilityAttribution; persist context_events + intent_samples;
upgrade root causes. Deterministic; no future data in any classification.
"""
from __future__ import annotations

import time
import uuid

from .config import Config
from .db import DB
from .ingest import IngestedDemo
from .state import build_tick_index, build_ground_truth
from .context import build_temporal_context
from .intent import detect_commitment, detect_role, classify_intent
from .feasibility import action_feasibility
from .responsibility import attribute_responsibility


def _anchor_events(demo: IngestedDemo, db: DB) -> list[tuple]:
    """Anchor ticks worth context analysis: deaths + DP decision ticks."""
    anchors = []
    players = {p["steamid"] for p in demo.players}
    for k in demo.events["kills"]:
        if k["user_steamid"] in players:
            anchors.append((k["tick"], k["user_steamid"], "death", f"death-{k['tick']}"))
    for dp in db.get_dps(demo.demo_id):
        anchors.append((dp["decision_tick"], dp["steamid"], "dp", dp["dp_id"]))
    return anchors


def run_context(demo: IngestedDemo, cfg: Config, db: DB) -> dict:
    idx = build_tick_index(demo)
    # idempotent per match: stale rows from earlier runs are removed first
    db.conn.execute("DELETE FROM context_events WHERE match_id=?", (demo.demo_id,))
    db.conn.commit()
    teams = {p["steamid"]: p["team_number"] for p in demo.players}
    responsibility_map, commitment_map, role_map = {}, {}, {}
    events_persisted = 0
    seen = set()
    for tick, steamid, anchor, ref in _anchor_events(demo, db):
        key = (steamid, tick)
        if key in seen:
            continue
        seen.add(key)
        # known-state for decision-layer legality (build_ground_truth NOT used
        # for classification — only for the temporal summary's descriptive part)
        tc = build_temporal_context(demo, cfg, idx, steamid, tick, known_state=None)
        commitment = detect_commitment(demo, cfg, steamid, tick)
        role, role_dist = detect_role(demo, cfg, idx, steamid, tick, commitment, tc)
        intent, intent_conf, intent_dist = classify_intent(demo, cfg, tc, steamid, tick)
        feas = action_feasibility(commitment, cfg, tc)
        resp = attribute_responsibility(demo, cfg, tc, steamid, tick,
                                        decision_eval="UNKNOWN" if anchor == "death" else None)
        responsibility_map[key] = resp
        commitment_map[key] = commitment
        role_map[key] = role
        db.upsert_context_event({
            "id": f"{demo.demo_id}-{anchor}-{steamid}-{tick}", "match_id": demo.demo_id,
            "round": demo.round_of_tick(tick), "tick": tick, "steamid": steamid,
            "anchor": anchor, "commitment": commitment, "role": role,
            "role_dist": role_dist, "intent": intent, "intent_conf": intent_conf,
            "intent_dist": intent_dist, "feasibility": feas,
            "responsibility": resp["attribution"],
            "temporal_summary": tc.summary(), "event_ref": ref,
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
                tc = build_temporal_context(demo, cfg, idx, p["steamid"], t)
                commitment = detect_commitment(demo, cfg, p["steamid"], t)
                role, _ = detect_role(demo, cfg, idx, p["steamid"], t, commitment, tc)
                intent, intent_conf, _ = classify_intent(demo, cfg, tc, p["steamid"], t)
                db.upsert_intent_sample({
                    "id": f"{demo.demo_id}-r{r['round']}-{p['steamid']}-{t}",
                    "match_id": demo.demo_id, "round": r["round"], "anchor_tick": t,
                    "start_tick": max(start, t - cfg.context_window_ticks),
                    "end_tick": t, "feature_sequence": tc.feature_sequence(),
                    "hard_events": tc.events, "player_known_state": {},
                    "commitment_state": commitment, "situational_role": role,
                    "rule_prediction": intent, "rule_confidence": intent_conf,
                    "source": "rule-baseline",
                })
                samples += 1
    return {"context_events": events_persisted, "intent_samples": samples,
            "intent_distribution": _count(db.get_intent_samples()),
            "responsibility_map": responsibility_map,
            "commitment_map": commitment_map, "role_map": role_map}


def _count(samples: list[dict]) -> dict:
    from collections import Counter
    return dict(Counter(s.get("rule_prediction") for s in samples))
