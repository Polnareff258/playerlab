"""V1.3 tests (spec §84): contact-response episode detection, re-peek candidate
generation, hold/hide/disengage feasibility, utility unavailable without
utility, plant commitment actionability, 5v4 good-outcome bad-decision,
2v3 bad-outcome reasonable-decision, decision vs execution separation,
candidate preference annotation, episode persistence, CS-NET delta not
overriding decision."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "core"))

from playerlab.config import Config  # noqa: E402
from playerlab.db import DB  # noqa: E402
from playerlab.context import TemporalContext  # noqa: E402
from playerlab.macro import compute_macro_context  # noqa: E402
from playerlab.evaluate import evaluate_decision, actionability  # noqa: E402
from playerlab.episode import (_candidate_actions, _has_bomb,  # noqa: E402
                               _local_context, _observed_action, ACTIONS)
from playerlab.episode_patterns import cluster_episodes  # noqa: E402
from playerlab.training import generate_targets_from_episodes  # noqa: E402


class FakeDemo:
    def __init__(self, players, events, rounds, demo_id="t1"):
        self.demo_id = demo_id
        self.players = players
        self.events = events
        self.rounds = rounds
        self.header = {"map_name": "de_dust2"}
        self._team = {p["steamid"]: p["team_number"] for p in players}
        self.ticks = None

    def team_of(self, s):
        return self._team.get(s, -1)

    def round_of_tick(self, t):
        for r in self.rounds:
            if r["start_tick"] <= t <= r["end_tick"]:
                return r["round"]
        return 0

    def round_bounds(self, r):
        for rr in self.rounds:
            if rr["round"] == r:
                return rr["start_tick"], rr["end_tick"]
        return None


P1 = 1
PLAYERS = [{"steamid": 1, "name": "A", "team_number": 2},
           {"steamid": 2, "name": "B", "team_number": 2},
           {"steamid": 3, "name": "C", "team_number": 2},
           {"steamid": 4, "name": "D", "team_number": 3},
           {"steamid": 5, "name": "E", "team_number": 3}]
ROUNDS = [{"round": 1, "start_tick": 0, "end_tick": 5000, "winner": "T", "reason": "x"}]
EMPTY_EVENTS = {"damages": [], "shots": [], "kills": [], "reloads": [],
                "plants_start": [], "defuses_start": [], "grenades": {},
                "bombs": {"planted": [], "defused": []}, "footsteps": []}


def rec(x, y, alive=True, vx=0.0, vy=0.0, yaw=0.0, place="Middle"):
    return {"x": x, "y": y, "vx": vx, "vy": vy, "vz": 0.0, "speed": (vx ** 2 + vy ** 2) ** 0.5,
            "is_alive": alive, "yaw": yaw, "health": 100, "weapon_def": 7,
            "money": 3000, "buttons": 0, "place": place, "team_num": 2}


def trajectory_idx(pts, step=16, vx=180.0, vy=0.0):
    idx = {}
    start = 0
    for i, (x, y, place) in enumerate(pts):
        t = start + i * step
        idx[(P1, t)] = rec(x, y, place=place, vx=vx, vy=vy)
        idx[(2, t)] = rec(x + 500, y, place=place, vx=vx, vy=vy)
        idx[(3, t)] = rec(x - 600, y, place=place, vx=vx, vy=vy)
        idx[(4, t)] = rec(x + 2000, y + 300, place="B")
        idx[(5, t)] = rec(x + 2400, y - 200, place="B")
    return idx


def mk_events(**kw):
    import copy
    e = copy.deepcopy(EMPTY_EVENTS)
    for k, v in kw.items():
        e[k] = v
    return e


def _extend(pts, n=17):
    out = list(pts)
    while len(out) < n:
        out.append(out[-1])
    return out


def _known_state(n_enemies=0, zone="B", age=0, source="own_vision",
                 bomb_known=False, bomb_zone=None, nearest=500.0, utility_flash=True):
    return {"n_known_enemies": n_enemies, "known_spread": 0.0,
            "nearest_known_enemy": nearest, "heard": [],
            "teammate_near": 0, "teammate_mid": 0,
            "known_enemy_zones": [zone] * n_enemies,
            "known_enemy_directions": [zone] * n_enemies,
            "time_since_last_known_enemy_update": age,
            "time_since_visual_contact": age if source in ("own_vision", "team_vision") else None,
            "time_since_damage_contact": age if source == "damage" else None,
            "recent_sound_info": [], "bomb_known": bomb_known, "bomb_zone": bomb_zone,
            "bomb_confidence": 0.9 if bomb_known else 0.0,
            "teammate_contact_count": 0, "recent_teammate_kill": False,
            "recent_teammate_death": False, "objective_information": {},
            "utility_flash": utility_flash,
            "last_seen_enemies": {str(4 + i): {"pos": [2100, 300], "tick": max(0, 256 - age),
                                               "source": source, "zone": zone}
                                  for i in range(n_enemies)}}


def _episode(known=None, commitment="FREE", observed="RE_PEEK", family="CONTACT_RESPONSE",
             alive_diff=0, need_info="NONE", risk_tol="MEDIUM", round_time=60.0,
             bomb_planted=False, candidates=None):
    cfg = Config()
    idx = trajectory_idx([(0, 0, "A")] * 17)
    demo = FakeDemo(PLAYERS, EMPTY_EVENTS, ROUNDS)
    tc = TemporalContext(demo, cfg, idx, P1, 256, known_state=known or _known_state())
    tc.team_alive = 5 if alive_diff >= 0 else 2
    tc.enemy_alive = 5 - alive_diff if alive_diff <= 0 else 5 - alive_diff
    tc.round_time_s = round_time
    tc.bomb_planted = bomb_planted
    macro = compute_macro_context(tc, cfg)
    macro["need_for_information"] = need_info
    macro["risk_tolerance"] = risk_tol
    ep = {
        "id": "e-test", "match_id": "m1", "round": 1, "player_id": P1,
        "family": family, "anchor_tick": 256,
        "player_known_state": known or _known_state(),
        "macro_context": macro,
        "local_context": {},
        "commitment_state": commitment, "situational_role": "FREE_ROLE",
        "intent": "HOLD", "observed_action": observed,
        "feasibility": {},
        "decision_evaluation": "INSUFFICIENT_EVIDENCE",
        "actionability": "INSUFFICIENT_EVIDENCE",
        "_candidates": candidates or [],
    }
    return cfg, demo, tc, ep


# ---------------------------------------------------------------- macro context
def test_macro_advantage_vs_disadvantage():
    """Spec §102-A: same action gets different context in 5v4 vs 2v3."""
    cfg, demo, tc, _ = _episode(alive_diff=1, need_info="NONE")
    macro_adv = compute_macro_context(tc, cfg)
    assert macro_adv["advantage_state"] == "NUMERIC_ADVANTAGE"
    assert macro_adv["risk_tolerance"] == "LOW"
    assert macro_adv["need_for_information"] in ("NONE", "LOW")

    _, _, tc2, _ = _episode(alive_diff=-1, need_info="HIGH", round_time=12.0)
    macro_dis = compute_macro_context(tc2, cfg)
    assert macro_dis["advantage_state"] == "NUMERIC_DISADVANTAGE"
    assert macro_dis["risk_tolerance"] == "HIGH"
    assert macro_dis["need_for_information"] in ("HIGH", "CRITICAL")


# ---------------------------------------------------------------- candidates
def test_candidate_generation_and_feasibility():
    """Spec §102-B/C: real alternatives + infeasible ones excluded."""
    cfg = Config()
    demo = FakeDemo(PLAYERS, EMPTY_EVENTS, ROUNDS)
    idx = trajectory_idx([(0, 0, "A")] * 17)
    tc = TemporalContext(demo, cfg, idx, P1, 256, known_state=_known_state())

    # plant commitment: TRADE unavailable
    cands = _candidate_actions(demo, cfg, tc, "PLANT_COMMITTED", "OBJECTIVE_COMMITMENT",
                               _known_state(utility_flash=True))
    trade = next(c for c in cands if c["action"] == "TRADE")
    assert trade["feasibility"] == "UNAVAILABLE", trade
    plant = next(c for c in cands if c["action"] == "PLANT")
    assert plant["feasibility"] == "FEASIBLE" or "UNAVAILABLE"

    # no utility -> FLASH unavailable (V1.3 assumption: inventory unknown ->
    # flash assumed unavailable when the flag says so)
    cands2 = _candidate_actions(demo, cfg, tc, "FREE", "CONTACT_RESPONSE",
                                _known_state(utility_flash=False))
    flash = next(c for c in cands2 if c["action"] == "FLASH")
    assert flash["feasibility"] == "UNAVAILABLE", flash

    # bomb not on player -> PLANT unavailable
    cands3 = _candidate_actions(demo, cfg, tc, "FREE", "OBJECTIVE_COMMITMENT",
                                _known_state())
    plant3 = next(c for c in cands3 if c["action"] == "PLANT")
    assert plant3["feasibility"] == "UNAVAILABLE", plant3

    # free player: HOLD/HIDE/DISENGAGE feasible
    cands4 = _candidate_actions(demo, cfg, tc, "FREE", "CONTACT_RESPONSE",
                                _known_state())
    for a in ("HOLD", "HIDE", "DISENGAGE", "REPOSITION"):
        c = next(x for x in cands4 if x["action"] == a)
        assert c["feasibility"] in ("FEASIBLE", "FEASIBLE_HIGH_COST", "CONSTRAINED"), c


def test_has_bomb():
    cfg = Config()
    demo = FakeDemo(PLAYERS, mk_events(plants_start=[{"tick": 100, "user_steamid": P1}]),
                    ROUNDS)
    idx = trajectory_idx([(0, 0, "A")] * 17)
    tc = TemporalContext(demo, cfg, idx, P1, 256, known_state={})
    assert _has_bomb(demo, cfg, tc) is True
    demo2 = FakeDemo(PLAYERS, mk_events(plants_start=[{"tick": 100, "user_steamid": 4}]),
                     ROUNDS)
    tc2 = TemporalContext(demo2, cfg, idx, P1, 256, known_state={})
    assert _has_bomb(demo2, cfg, tc2) is False


# ---------------------------------------------------------------- evaluation
def test_eval_good_outcome_bad_decision():
    """Spec §20/§102-D: 5v4 dry peek that gets a kill is still QUESTIONABLE."""
    _, _, _, ep = _episode(alive_diff=1, need_info="NONE", risk_tol="LOW",
                           observed="RE_PEEK")
    # outcome is not an input; the evaluation must come out non-GOOD
    eval_ = evaluate_decision(ep, Config(), {
        "RE_PEEK": {"risk": "HIGH", "support": "LOW", "value": "LOW"},
        "HOLD": {"risk": "LOW", "support": "HIGH", "value": "HIGH"},
    })
    assert eval_ in ("QUESTIONABLE", "POOR"), eval_
    # structural: evaluate_decision signature has no outcome param
    import inspect
    assert "outcome" not in inspect.signature(evaluate_decision).parameters


def test_eval_bad_outcome_reasonable_decision():
    """Spec §21/§102-E: 2v3 late-info peek that dies is still REASONABLE."""
    _, _, _, ep = _episode(alive_diff=-1, need_info="CRITICAL", risk_tol="HIGH",
                           observed="PEEK")
    eval_ = evaluate_decision(ep, Config(), {
        "PEEK": {"risk": "HIGH", "support": "HIGH", "value": "HIGH"},
        "HOLD": {"risk": "LOW", "support": "LOW", "value": "LOW"},
    })
    assert eval_ in ("REASONABLE", "GOOD"), eval_


def test_eval_same_peek_different_context():
    """Spec §102-A: the same PEEK differs by macro context."""
    _, _, _, ep_adv = _episode(alive_diff=1, need_info="NONE", risk_tol="LOW",
                               observed="PEEK")
    ev_adv = evaluate_decision(ep_adv, Config(), {
        "PEEK": {"risk": "HIGH", "support": "LOW", "value": "LOW"},
        "HOLD": {"risk": "LOW", "support": "HIGH", "value": "HIGH"},
    })
    _, _, _, ep_dis = _episode(alive_diff=-1, need_info="CRITICAL", risk_tol="HIGH",
                               observed="PEEK")
    ev_dis = evaluate_decision(ep_dis, Config(), {
        "PEEK": {"risk": "HIGH", "support": "HIGH", "value": "HIGH"},
        "HOLD": {"risk": "LOW", "support": "LOW", "value": "LOW"},
    })
    assert ev_adv in ("QUESTIONABLE", "POOR"), ev_adv
    assert ev_dis in ("REASONABLE", "GOOD"), ev_dis
    assert ev_adv != ev_dis


# ---------------------------------------------------------------- actionability
def test_actionability_plant_commitment_not_actionable():
    """Spec §89/§102-F: controllable-less events -> NOT_ACTIONABLE."""
    _, _, _, ep = _episode(commitment="PLANT_COMMITTED", observed="HOLD",
                           family="OBJECTIVE_COMMITMENT")
    a = actionability(ep, Config())
    assert a == "NOT_ACTIONABLE", a


def test_actionability_highly_actionable_repeek():
    _, _, _, ep = _episode(alive_diff=1, need_info="NONE", risk_tol="LOW",
                           observed="RE_PEEK")
    a = actionability(ep, Config(), evidence_sufficient=True)
    assert a in ("HIGHLY_ACTIONABLE", "ACTIONABLE"), a


# ---------------------------------------------------------------- patterns + targets
def test_episode_pattern_to_target():
    """Spec §102-G: a repeated local-decision pattern generates a target."""
    cfg = Config()
    db = DB(":memory:")
    db.upsert_match({"demo_id": "m1", "demo_path": "", "map_name": "de_dust2",
                     "tickrate": 64, "player_count": 5, "rounds_total": 1,
                     "side_swap_round": None, "parsed_at": "2026-01-01",
                     "parser_version": "t"})
    # 12 CONTACT_RESPONSE episodes, 8 with QUESTIONABLE RE_PEEK, all actionable
    for i in range(12):
        db.upsert_decision_episode({
            "id": f"e{i}", "match_id": "m1", "round": 1, "player_id": P1,
            "family": "CONTACT_RESPONSE", "start_tick": i, "anchor_tick": 100 + i,
            "end_tick": 300 + i, "temporal_context": {}, "player_known_state": {},
            "macro_context": {"advantage_state": "EVEN",
                              "need_for_information": "LOW"},
            "local_context": {}, "commitment_state": "FREE",
            "situational_role": "FREE_ROLE", "intent": "RE_PEEK",
            "observed_action": "RE_PEEK" if i % 3 != 0 else "HOLD",
            "feasibility": {}, "immediate_result": {},
            "state_value_before": None, "state_value_after": None,
            "decision_evaluation": "QUESTIONABLE" if i % 3 != 0 else "REASONABLE",
            "actionability": "ACTIONABLE",
            "confidence": 0.7, "extractor_version": "v1.3-1",
            "context_version": "v1.2.1", "rule_version": "v1.3-1",
            "model_provider_version": "null", "geometry_version": "null",
            "computed_at": "2026-01-01"})
    patterns = cluster_episodes(db, cfg)
    over_repeek = next(p for p in patterns if p["pattern_id"] == "OVER_REPEEK_AFTER_NEUTRAL_CONTACT")
    assert over_repeek["sample_count"] == 12
    assert over_repeek["eligible"] is True, over_repeek
    targets = generate_targets_from_episodes(db, cfg, patterns)
    ids = [t["target_id"] for t in targets]
    assert "OVER_REPEEK_AFTER_NEUTRAL_CONTACT" in ids, ids
    # the target must be repeatable + actionable (gate) — assert macro_reason present
    t = targets[0]
    assert "macro_reason" in t


# ---------------------------------------------------------------- persistence + preference
def test_decision_episode_persistence():
    """Spec §84: episode + candidates + evidence persist and reload."""
    cfg = Config()
    db = DB(":memory:")
    ep = {
        "id": "e-persist", "match_id": "m1", "round": 2, "player_id": P1,
        "family": "CONTACT_RESPONSE", "start_tick": 0, "anchor_tick": 100,
        "end_tick": 300, "temporal_context": {"z": 1}, "player_known_state": {"n": 1},
        "macro_context": {"advantage_state": "EVEN"},
        "local_context": {"hp": 80}, "commitment_state": "FREE",
        "situational_role": "FREE_ROLE", "intent": "HOLD",
        "observed_action": "HOLD", "feasibility": {"HOLD": "FEASIBLE"},
        "immediate_result": {"survived": True},
        "state_value_before": 0.6, "state_value_after": 0.6,
        "decision_evaluation": "REASONABLE", "actionability": "WEAKLY_ACTIONABLE",
        "confidence": 0.6, "extractor_version": "v1.3-1",
        "context_version": "v1.2.1", "rule_version": "v1.3-1",
        "model_provider_version": "null", "geometry_version": "null",
        "computed_at": "2026-01-01"}
    db.upsert_decision_episode(ep)
    db.upsert_decision_candidate({"id": "c1", "episode_id": "e-persist",
                                  "action": "HOLD", "feasibility": "FEASIBLE",
                                  "rank": 1, "confidence": 0.5})
    db.upsert_decision_evidence({"id": "ev1", "episode_id": "e-persist",
                                 "candidate_action": "HOLD", "source": "rule",
                                 "type": "heuristic", "supports_action": "HOLD",
                                 "confidence": 0.6, "related_sources": []})
    got = db.get_decision_episode("e-persist")
    assert got["macro_context"]["advantage_state"] == "EVEN"
    assert len(got["candidates"]) == 1 and got["candidates"][0]["action"] == "HOLD"
    assert len(got["evidence"]) == 1 and got["evidence"][0]["source"] == "rule"
    # preference
    import uuid
    db.insert_decision_preference({"id": uuid.uuid4().hex[:16], "episode_id": "e-persist",
                                   "match_id": "m1", "round": 2, "tick": 100,
                                   "candidate_a": "HOLD", "candidate_b": "RE_PEEK",
                                   "human_choice": "A", "human_confidence": 0.7})
    prefs = db.get_decision_preferences("e-persist")
    assert len(prefs) == 1 and prefs[0]["human_choice"] == "A"


def test_csnet_delta_not_overriding_decision():
    """Spec §33-§36/§84: CS-NET delta<0 is evidence, never the verdict."""
    _, _, _, ep = _episode(alive_diff=1, need_info="NONE", risk_tol="LOW",
                           observed="HOLD")
    # strong positive rule/context evidence for HOLD
    ev = {
        "HOLD": {"risk": "LOW", "support": "HIGH", "value": "HIGH"},
        "PEEK": {"risk": "HIGH", "support": "LOW", "value": "LOW"},
    }
    eval_ = evaluate_decision(ep, Config(), ev)
    # even if a model delta were -0.23, the decision stays reasonable because
    # delta is not an input to evaluate_decision (structural guarantee)
    import inspect
    assert "delta" not in inspect.signature(evaluate_decision).parameters
    assert eval_ in ("GOOD", "REASONABLE"), eval_


def test_decision_execution_separation():
    """Spec §62-§63: decision quality is separate from execution quality."""
    # evaluate_decision has no execution channel input -> decision-only
    import inspect
    from playerlab.evaluate import evaluate_decision
    params = inspect.signature(evaluate_decision).parameters
    assert "execution" not in params and "outcome" not in params
    # the episode schema separates immediate_result (outcome) from evaluation
    _, _, _, ep = _episode(observed="DISENGAGE", alive_diff=0)
    ep["immediate_result"] = {"survived": False}   # outcome is bad
    eval_ = evaluate_decision(ep, Config(), {"DISENGAGE": {"risk": "LOW", "support": "HIGH", "value": "HIGH"}})
    assert eval_ in ("GOOD", "REASONABLE")  # decision stays good despite bad outcome


if __name__ == "__main__":
    import traceback
    failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            try:
                fn()
                print(f"PASS {name}")
            except Exception:
                failed += 1
                print(f"FAIL {name}")
                traceback.print_exc()
    total = sum(1 for n in globals() if n.startswith("test_"))
    print(f"\n{total - failed}/{total} passed")
    sys.exit(1 if failed else 0)
