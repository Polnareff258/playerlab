"""V1.2 tests: commitment, feasibility, intent rule baseline (rotation vs
reposition), responsibility scenarios (§23/§24/§54/§55), annotation types,
reference interfaces."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "core"))

from playerlab.config import Config  # noqa: E402
from playerlab.db import DB  # noqa: E402
from playerlab.context import TemporalContext  # noqa: E402
from playerlab.intent import detect_commitment, classify_intent  # noqa: E402
from playerlab.feasibility import action_feasibility  # noqa: E402
from playerlab.responsibility import attribute_responsibility  # noqa: E402
from playerlab.annotation import submit_annotation, annotation_stats  # noqa: E402
from playerlab.reference import (NullReferenceProvider, LocalStubReferenceProvider,  # noqa: E402
                                 ReferencePolicyProvider)


class FakeDemo:
    def __init__(self, players, events, rounds, demo_id="t1"):
        self.demo_id = demo_id
        self.players = players
        self.events = events
        self.rounds = rounds
        self.header = {"map_name": "de_dust2"}
        self._team = {p["steamid"]: p["team_number"] for p in players}
        self.ticks = None  # map_bounds falls back to the dust2 constant

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


P1, P4 = 1, 4
PLAYERS = [{"steamid": 1, "name": "A", "team_number": 2},
           {"steamid": 2, "name": "B", "team_number": 2},
           {"steamid": 3, "name": "C", "team_number": 2},
           {"steamid": 4, "name": "D", "team_number": 3},
           {"steamid": 5, "name": "E", "team_number": 3}]
ROUNDS = [{"round": 1, "start_tick": 0, "end_tick": 5000, "winner": "T", "reason": "x"}]
EMPTY_EVENTS = {"damages": [], "shots": [], "kills": [], "reloads": [],
                "plants_start": [], "defuses_start": [], "grenades": {},
                "bombs": {"planted": [], "defused": []}}


def rec(x, y, alive=True, vx=0.0, vy=0.0, yaw=0.0, place="Middle"):
    return {"x": x, "y": y, "vx": vx, "vy": vy, "vz": 0.0, "speed": (vx ** 2 + vy ** 2) ** 0.5,
            "is_alive": alive, "yaw": yaw, "health": 100, "weapon_def": 7,
            "money": 3000, "buttons": 0, "place": place, "team_num": 2}


def trajectory_idx(pts, step=16, vx=180.0, vy=0.0):
    """pts: list of (x, y, place) at successive timesteps -> idx over a window."""
    idx = {}
    start = 0
    for i, (x, y, place) in enumerate(pts):
        t = start + i * step
        idx[(P1, t)] = rec(x, y, place=place, vx=vx, vy=vy)
        # teammates/enemies present at each timestep
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


# ---------------------------------------------------------------- commitment
def test_commitment_plant_and_free():
    cfg = Config()
    demo = FakeDemo(PLAYERS, mk_events(plants_start=[{"tick": 100, "user_steamid": P1}]),
                    ROUNDS)
    assert detect_commitment(demo, cfg, P1, 150) == "PLANT_COMMITTED"
    assert detect_commitment(demo, cfg, P1, 400) == "FREE"
    assert detect_commitment(demo, cfg, P4, 150) == "FREE"


def test_commitment_reload_and_utility():
    cfg = Config()
    demo = FakeDemo(PLAYERS, mk_events(reloads=[{"tick": 100, "user_steamid": P1}]), ROUNDS)
    assert detect_commitment(demo, cfg, P1, 120) == "RELOAD_COMMITTED"
    demo2 = FakeDemo(PLAYERS, mk_events(grenades={"hegrenade_detonate": [
        {"tick": 100, "user_steamid": P1}]}), ROUNDS)
    assert detect_commitment(demo2, cfg, P1, 140) == "UTILITY_COMMITTED"


# ---------------------------------------------------------------- feasibility
def test_feasibility_plant_rules():
    cfg = Config()
    demo = FakeDemo(PLAYERS, EMPTY_EVENTS, ROUNDS)
    idx = trajectory_idx([(0, 0, "B")] * 17)
    tc = TemporalContext(demo, cfg, idx, P1, 256, known_state={})
    feas = action_feasibility("PLANT_COMMITTED", cfg, tc)
    assert feas["CONTINUE_PLANT"] == "FEASIBLE"
    assert feas["IMMEDIATE_TRADE"] == "TEMPORARILY_UNAVAILABLE"
    assert feas["REPOSITION"] == "UNAVAILABLE"
    assert feas["SHOOT"] == "CONSTRAINED"
    feas_free = action_feasibility("FREE", cfg, tc)
    assert feas_free["SHOOT"] == "FEASIBLE"


# ---------------------------------------------------------------- intent
def _extend(pts, n=17):
    """Repeat the last point to cover the full context window (17 timesteps)."""
    out = list(pts)
    while len(out) < n:
        out.append(out[-1])
    return out


def test_intent_rotate():
    cfg = Config()
    # moving from A zone across zones with bomb planted at B + heading consistent
    pts = _extend([(0, 0, "A"), (300, -100, "A"), (600, -300, "Catwalk"), (900, -500, "Catwalk"),
                   (1300, -700, "Middle"), (1700, -900, "Middle"), (2100, -1100, "B")])
    idx = trajectory_idx(pts)
    demo = FakeDemo(PLAYERS, mk_events(bombs={"planted": [{"tick": 100, "site": "B"}],
                                                "defused": []}), ROUNDS)
    tc = TemporalContext(demo, cfg, idx, P1, 256, known_state={"n_known_enemies": 2})
    intent, conf, dist = classify_intent(demo, cfg, tc, P1, 256)
    assert intent == "ROTATE", dist


def test_intent_reposition():
    cfg = Config()
    # short same-zone movement, no opposite-side signal
    pts = _extend([(0, 0, "A"), (100, 50, "A"), (200, 90, "A"), (280, 120, "A")])
    idx = trajectory_idx(pts)
    demo = FakeDemo(PLAYERS, EMPTY_EVENTS, ROUNDS)
    tc = TemporalContext(demo, cfg, idx, P1, 256, known_state={})
    intent, _, dist = classify_intent(demo, cfg, tc, P1, 256)
    assert intent == "REPOSITION", dist


def test_intent_hold():
    cfg = Config()
    pts = [(0, 0, "A")] * 17
    idx = trajectory_idx(pts, vx=0.0, vy=0.0)
    demo = FakeDemo(PLAYERS, EMPTY_EVENTS, ROUNDS)
    tc = TemporalContext(demo, cfg, idx, P1, 256, known_state={})
    intent, _, dist = classify_intent(demo, cfg, tc, P1, 256)
    assert intent == "HOLD", dist


# ---------------------------------------------------------------- responsibility
def test_responsibility_plant_teammate_death():
    cfg = Config()
    demo = FakeDemo(PLAYERS, mk_events(plants_start=[{"tick": 150, "user_steamid": P1}]),
                    ROUNDS)
    idx = trajectory_idx([(0, 0, "B")] * 17)
    tc = TemporalContext(demo, cfg, idx, P1, 256, known_state={"n_known_enemies": 0})
    resp = attribute_responsibility(demo, cfg, tc, P1, 256)
    assert resp["commitment"] == "PLANT_COMMITTED"
    assert resp["attribution"] in ("NOT_ACTIONABLE", "SELF_DECISION")
    if resp["attribution"] == "SELF_DECISION":
        assert tc.known.get("nearest_known_enemy") is None  # only when enemies close
    # free teammate (P2) taking an unsupported fight while P1 plants -> SHARED
    idx2 = trajectory_idx([(0, 0, "A")] * 17)
    tc2 = TemporalContext(demo, cfg, idx2, 2, 256, known_state={"n_known_enemies": 1,
                                                               "nearest_known_enemy": 500.0})
    resp2 = attribute_responsibility(demo, cfg, tc2, 2, 256)
    assert resp2["team_level"] in ("SHARED", "TEAMMATE_DECISION_SHARED", None), resp2


def test_responsibility_reload_mistake():
    cfg = Config()
    demo = FakeDemo(PLAYERS, mk_events(reloads=[{"tick": 200, "user_steamid": P1}]), ROUNDS)
    idx = trajectory_idx([(0, 0, "A")] * 17)
    tc = TemporalContext(demo, cfg, idx, P1, 256,
                         known_state={"n_known_enemies": 1,
                                      "nearest_known_enemy": 800.0})
    resp = attribute_responsibility(demo, cfg, tc, P1, 256)
    assert resp["commitment"] == "RELOAD_COMMITTED"
    # reload with a known enemy close -> not excused
    assert resp["attribution"] == "SELF_DECISION", resp


def test_responsibility_outcome_independence():
    """Good outcome != good decision; bad outcome != bad decision (§54-§55).
    The attribution function must not receive outcome as input at all."""
    cfg = Config()
    demo = FakeDemo(PLAYERS, EMPTY_EVENTS, ROUNDS)
    idx = trajectory_idx([(0, 0, "A")] * 17)
    tc = TemporalContext(demo, cfg, idx, P1, 256, known_state={})
    import inspect
    sig = inspect.signature(attribute_responsibility)
    assert "outcome" not in sig.parameters  # structurally outcome-free
    resp_bad = attribute_responsibility(demo, cfg, tc, P1, 256, decision_eval="POOR")
    assert resp_bad["attribution"] == "SELF_DECISION"  # poor decision even if outcome were good
    resp_good = attribute_responsibility(demo, cfg, tc, P1, 256, decision_eval="REASONABLE")
    assert resp_good["attribution"] in ("REASONABLE_BUT_LOST", "SELF_DECISION")


# ---------------------------------------------------------------- annotation + reference
def test_annotation_new_types():
    cfg = Config()
    db = DB(":memory:")
    ann = submit_annotation(db, None, "intent", model_prediction="ROTATE",
                            model_confidence=0.6, human_label="ROTATE")
    assert ann["annotation_type"] == "intent" and ann["model_version"] == "alpha-1"
    ann2 = submit_annotation(db, None, "responsibility", model_prediction="NOT_ACTIONABLE",
                             model_confidence=0.7, human_label="SELF_DECISION")
    assert ann2["human_label"] == "SELF_DECISION"
    stats = annotation_stats(db)
    assert stats["by_type"]["intent"]["agreement"] == 1.0


def test_reference_providers():
    cfg = Config()
    db = DB(":memory:")
    null = NullReferenceProvider()
    assert null.query_samples({}) == [] and null.get_version() == "null"
    # seed a state for the stub policy
    db.upsert_match({"demo_id": "m1", "demo_path": "", "map_name": "de_dust2",
                     "tickrate": 64, "player_count": 5, "rounds_total": 1,
                     "side_swap_round": None, "parsed_at": "2026-01-01",
                     "parser_version": "t"})
    f = {k: 0.5 for k in ("time_left", "alive_diff", "hp", "n_known_enemies", "known_spread",
                          "nearest_known_enemy", "recent_contact", "teammate_near",
                          "teammate_mid", "bomb_planted", "economy", "time_pressure")}
    db.insert_dp(
        {"dp_id": "d1", "match_id": "m1", "round": 1, "steamid": 1, "player_name": "A",
         "start_tick": 0, "decision_tick": 100, "end_tick": 200, "observed_action": "PEEK",
         "alternatives": [], "zone": "A", "place": "A", "confidence": 0.8,
         "significance": 1.0, "evidence": {}, "meta": {}},
        {"dp_id": "d1", "match_id": "m1", "round": 1, "decision_tick": 100,
         "map": "de_dust2", "side": "T", "zone": "A", "observed_action": "PEEK",
         "features": f, "labels": {"map": "de_dust2", "side": "T", "zone": "A",
                                   "weapon_class": "rifle", "action": "PEEK"},
         "known_state": {}, "public_info": {}, "ground_truth": {}},
        {"dp_id": "d1", "survival": 1, "survival_window_ticks": 640, "death_tick": None,
         "duel_result": "won", "duel_opponent": "4", "round_win": 1})
    stub = LocalStubReferenceProvider(db)
    pol = stub.policy_for({"labels": {"action": "PEEK"}})
    assert pol["sample_count"] == 1 and pol["action_distribution"]["PEEK"] == 1.0
    assert pol["source"] == "local-history" and pol["reference_version"] == "local-stub-1"
    assert isinstance(stub, ReferencePolicyProvider)


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
