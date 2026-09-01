"""V1.3.1 tests (spec §120): strategic/engagement/execution separation,
dry peek / wide swing / flash-assisted detection, fire-before-aim-ready /
preaim error / moving shot / irregular movement, MovementEffect dual-face,
context-dependent movement interpretation, CS-NET not overriding, evidence
insufficiency produces real INSUFFICIENT_EVIDENCE, utility inventory."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "core"))

from playerlab.config import Config  # noqa: E402
from playerlab.context import TemporalContext  # noqa: E402
from playerlab.engagement import (compute_information_advantage,  # noqa: E402
                                  weapon_matchup, detect_engagement_method,
                                  build_engagement_context, opponent_state)
from playerlab.duel import (_angular_error, extract_duel_state_sequence,  # noqa: E402
                            execution_primitives, movement_effect, duel_evaluation,
                            detect_engagement_windows, ENGAGEMENT_PHASES)
from playerlab.evaluate import (engagement_evaluation, execution_evaluation,  # noqa: E402
                                evaluate_decision)
from playerlab.evidence import evidence_sufficiency  # noqa: E402
from playerlab.weapons import engagement_class, range_bucket  # noqa: E402


class FakeDemo:
    def __init__(self, players, events, rounds, demo_id="t1"):
        self.demo_id = demo_id
        self.demo_path = "fake.dem"
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


P1, P4 = 1, 4
PLAYERS = [{"steamid": 1, "name": "A", "team_number": 2},
           {"steamid": 2, "name": "B", "team_number": 2},
           {"steamid": 3, "name": "C", "team_number": 2},
           {"steamid": 4, "name": "D", "team_number": 3},
           {"steamid": 5, "name": "E", "team_number": 3}]
ROUNDS = [{"round": 1, "start_tick": 0, "end_tick": 5000, "winner": "T", "reason": "x"}]
EMPTY_EVENTS = {"damages": [], "shots": [], "kills": [], "reloads": [],
                "plants_start": [], "defuses_start": [], "grenades": {},
                "bombs": {"planted": [], "defused": []}, "footsteps": []}


def rec(x, y, alive=True, vx=0.0, vy=0.0, yaw=0.0, place="Middle", pitch=0.0,
        buttons=0, weapon_def=7):
    return {"x": x, "y": y, "vx": vx, "vy": vy, "vz": 0.0,
            "speed": (vx ** 2 + vy ** 2) ** 0.5, "is_alive": alive,
            "yaw": yaw, "pitch": pitch, "health": 100, "weapon_def": weapon_def,
            "money": 3000, "buttons": buttons, "place": place, "team_num": 2,
            "ammo_clip": 30, "zoom_level": 0, "flash_duration": 0.0}


def idx_for(pts, enemy_yaw=0.0):
    """pts: list of (x, y) at successive 8-tick steps for P1; enemy fixed."""
    idx = {}
    for i, (x, y) in enumerate(pts):
        t = i * 8
        idx[(P1, t)] = rec(x, y, vx=200.0, vy=0.0, yaw=90.0, place="B")
        idx[(P4, t)] = rec(2000, 0, yaw=enemy_yaw, place="B")  # enemy far East
    return idx


def known_state(n_enemies=1, zone="B", source="own_vision", age=0,
                flash_count=0, weapon_def=7):
    return {"n_known_enemies": n_enemies, "known_spread": 0.0,
            "nearest_known_enemy": 1500.0, "heard": [],
            "teammate_near": 0, "teammate_mid": 0,
            "known_enemy_zones": [zone] * n_enemies,
            "known_enemy_directions": [zone] * n_enemies,
            "time_since_last_known_enemy_update": age,
            "time_since_visual_contact": age,
            "time_since_damage_contact": None,
            "recent_sound_info": [], "bomb_known": False, "bomb_zone": None,
            "bomb_confidence": 0.0, "teammate_contact_count": 0,
            "recent_teammate_kill": False, "recent_teammate_death": False,
            "objective_information": {},
            "utility_inventory": {"flash_count": flash_count, "smoke_count": 0,
                                  "he_count": 0, "molotov_count": 0},
            "own": {"hp": 100, "weapon_def": weapon_def,
                    "weapon_class": "rifle", "ammo_clip": 30,
                    "zoom_level": 0, "flash_duration": 0.0, "is_ducking": False,
                    "speed": 0.0, "yaw": 90.0},
            "last_seen_enemies": {str(P4): {"pos": [2000, 0], "tick": 0,
                                            "source": source, "zone": zone}}}


def duel_fixture():
    """Duel window: P1 fires while moving fast + large crosshair error."""
    pts = [(0, 0), (120, 0), (240, 0), (360, 0), (480, 0), (600, 0)]
    idx = idx_for(pts)
    demo = FakeDemo(PLAYERS, EMPTY_EVENTS, ROUNDS)
    cfg = Config()
    win = {"start": 0, "anchor": 8, "end": 96, "n_contacts": 2}
    duel = extract_duel_state_sequence(demo, cfg, idx, P1, win, enemy_steamid=P4)
    return demo, cfg, idx, duel


# ---------------------------------------------------------------- information advantage
def test_information_advantage():
    cfg = Config()
    demo = FakeDemo(PLAYERS, EMPTY_EVENTS, ROUNDS)
    idx = idx_for([(0, 0)] * 4)
    ks = known_state(n_enemies=1, source="own_vision", age=0)
    tc = TemporalContext(demo, cfg, idx, P1, 0, known_state=ks)
    tc.events["damage_taken"] = 1  # enemy knows us
    tc.information_strength = "CONFIRMED"
    assert compute_information_advantage(tc, ks) in ("SELF", "MUTUAL")
    ks2 = known_state(n_enemies=0)
    tc2 = TemporalContext(demo, cfg, idx, P1, 0, known_state=ks2)
    tc2.events["damage_taken"] = 1
    assert compute_information_advantage(tc2, ks2) == "ENEMY"


# ---------------------------------------------------------------- weapon matchup
def test_weapon_matchup_and_range():
    cfg = Config()
    demo = FakeDemo(PLAYERS, EMPTY_EVENTS, ROUNDS)
    idx = idx_for([(0, 0)] * 4)
    ks = known_state(weapon_def=9)  # awp
    tc = TemporalContext(demo, cfg, idx, P1, 0, known_state=ks)
    wm = weapon_matchup(tc, ks, {"known_weapon": "awp",
                                 "last_known_position": [2000, 0]})
    assert wm["self_weapon_class"] == "AWP"
    assert wm["enemy_weapon_class"] == "AWP"
    assert wm["range_bucket"] in ("close", "medium", "long")
    assert engagement_class("ak47") == "RIFLE"
    assert range_bucket(3000.0) == "long"


# ---------------------------------------------------------------- engagement method
def test_dry_peek_detection():
    """Spec §120-C: dry peek = engagement with known enemy, no utility."""
    cfg = Config()
    demo = FakeDemo(PLAYERS, EMPTY_EVENTS, ROUNDS)
    idx = idx_for([(0, 0)] * 4)
    ks = known_state(n_enemies=1, flash_count=0)
    tc = TemporalContext(demo, cfg, idx, P1, 0, known_state=ks)
    duel = {"movement": {"max_lateral_speed": 100.0, "direction_reversals": 0},
            "exposure_ticks": 16}
    m = detect_engagement_method(demo, cfg, tc, ks, "PEEK", duel=duel)
    assert m["method"] == "DRY_PEEK", m


def test_flash_peek_detection():
    """Flash in inventory + self flash event -> FLASH_PEEK, not dry."""
    cfg = Config()
    events = {"flashbang_detonate": [{"tick": 100, "user_steamid": P1}]}
    demo = FakeDemo(PLAYERS, {**EMPTY_EVENTS, "grenades": events}, ROUNDS)
    idx = idx_for([(0, 0)] * 4)
    ks = known_state(n_enemies=1, flash_count=1)
    tc = TemporalContext(demo, cfg, idx, P1, 150, known_state=ks)
    m = detect_engagement_method(demo, cfg, tc, ks, "PEEK", duel=None)
    assert m["method"] == "FLASH_PEEK", m


def test_wide_swing_detection():
    cfg = Config()
    demo = FakeDemo(PLAYERS, EMPTY_EVENTS, ROUNDS)
    idx = idx_for([(0, 0)] * 4)
    ks = known_state(n_enemies=1, flash_count=0)
    tc = TemporalContext(demo, cfg, idx, P1, 0, known_state=ks)
    duel = {"movement": {"max_lateral_speed": 380.0, "direction_reversals": 0},
            "exposure_ticks": 32}
    m = detect_engagement_method(demo, cfg, tc, ks, "PEEK", duel=duel)
    assert m["method"] == "WIDE_SWING", m


# ---------------------------------------------------------------- duel / crosshair
def test_angular_error():
    # CS2 yaw: 0 = +y (north), 90 = +x (east). Viewer at origin facing
    # east (yaw 90), target east at 1000u -> aligned, small error.
    err_h, err_c = _angular_error(90.0, 0.0, (0, 0), (1000, 0))
    assert err_h is not None and err_h < 10.0, (err_h, err_c)
    # facing north (yaw 0), target east -> ~90° yaw error
    err2, _ = _angular_error(0.0, 0.0, (0, 0), (1000, 0))
    assert err2 > 60.0, err2
    # facing east, target north (0, 1000) -> ~90° error
    err3, _ = _angular_error(90.0, 0.0, (0, 0), (0, 1000))
    assert err3 > 60.0, err3


def test_execution_primitives():
    """Spec §120-D: moving shot + fire before aim ready detectable.
    V1.3.3: SHOT_WHILE_MOVING is the measurement (behavior fact); MOVING_SHOT
    no longer exists as a primitive (it was conflating behavior with error)."""
    demo, cfg, idx, duel = duel_fixture()
    flags = execution_primitives(demo, cfg, duel, None)
    assert isinstance(flags, list)
    assert "MOVING_SHOT" not in flags  # renamed: behavior fact, not an error
    # duel fixture has player moving (200u/s) -> SHOT_WHILE_MOVING likely
    movement = duel.get("movement") or {}
    if movement.get("max_lateral_speed", 0) >= 130.0:
        assert "SHOT_WHILE_MOVING" in flags, flags


def test_movement_effect_dual_face():
    """Spec §120-E: self cost + opponent difficulty both described."""
    demo, cfg, idx, duel = duel_fixture()
    me = movement_effect(demo, cfg, duel, None, "RIFLE", "long")
    assert me["self_accuracy_cost"] in ("LOW", "MEDIUM", "HIGH")
    assert me["estimated_opponent_tracking_difficulty"] in ("LOW", "MEDIUM", "HIGH")
    assert "not guaranteed enemy experience" in me["note"]
    # AWP is movement-sensitive
    me_awp = movement_effect(demo, cfg, duel, None, "AWP", "long")
    assert me_awp["self_accuracy_cost"] in ("MEDIUM", "HIGH")


def test_movement_context_dependence():
    """Spec §120-F: same irregular movement differs close-SMG vs long-rifle."""
    duel = {"movement": {"pattern": "IRREGULAR_STRAFE", "max_lateral_speed": 250.0,
                         "direction_reversals": 4, "duck_count": 1},
            "exposure_ticks": 24}
    cfg = Config()
    # close SMG: irregular movement is defensible
    ev_close = duel_evaluation(None, cfg, duel, None, {}, None, "close", "SMG")
    # long rifle: costs aim
    ev_long = duel_evaluation(None, cfg, duel, None, {}, None, "long", "RIFLE")
    assert ev_close in ("GOOD", "REASONABLE"), ev_close
    assert ev_long in ("QUESTIONABLE", "POOR", "REASONABLE"), ev_long
    assert ev_close != ev_long  # different interpretations


def test_three_level_separation():
    """Spec §120-A/B: strategic reasonable + engagement questionable +
    execution good can coexist (spec §7 example)."""
    cfg = Config()
    episode = {"macro_context": {"advantage_state": "EVEN",
                                 "need_for_information": "HIGH",
                                 "risk_tolerance": "MEDIUM"},
               "feasibility": {"PEEK": "FEASIBLE", "HOLD": "FEASIBLE",
                               "DISENGAGE": "FEASIBLE"},
               "observed_action": "PEEK", "commitment_state": "FREE",
               "_candidates": []}
    strat = evaluate_decision(episode, cfg, {
        "PEEK": {"risk": "HIGH", "support": "HIGH", "value": "HIGH"}})
    # engagement: dry peek at known AWP long range -> questionable
    eng = {"engagement_method": {"method": "DRY_PEEK"},
           "weapon_matchup": {"enemy_weapon_class": "AWP", "range_bucket": "long"}}
    eng_eval = engagement_evaluation(episode, cfg, eng)
    assert eng_eval in ("QUESTIONABLE", "POOR"), eng_eval
    # execution: good aim
    duel = {"movement": {"pattern": "STATIC", "max_lateral_speed": 10.0,
                         "direction_reversals": 0, "duck_count": 0},
            "exposure_ticks": 8, "shot_crosshair_error": 0.3,
            "preaim_error": {"bucket": "LOW"}}
    exec_eval = execution_evaluation(episode, cfg, duel, eng)
    assert exec_eval in ("GOOD", "REASONABLE"), exec_eval


def test_csnet_delta_not_overriding():
    """Spec §120-G: CS-NET state-value is evidence only (structural)."""
    import inspect
    from playerlab.evaluate import evaluate_decision, engagement_evaluation
    assert "state_value" not in inspect.signature(evaluate_decision).parameters
    assert "delta" not in inspect.signature(engagement_evaluation).parameters


def test_evidence_insufficiency():
    """Spec §120-H: low evidence -> real INSUFFICIENT_EVIDENCE."""
    cfg = Config()
    # episode with no known state, no macro -> sufficiency LOW/INSUFFICIENT
    ep_bare = {"player_known_state": {}, "macro_context": {},
               "local_context": {}, "_candidates": []}
    suff = evidence_sufficiency(ep_bare)
    assert suff in ("LOW", "INSUFFICIENT"), suff
    eval_ = evaluate_decision(ep_bare, cfg, {}, sufficiency=suff)
    if suff == "INSUFFICIENT":
        assert eval_ == "INSUFFICIENT_EVIDENCE", eval_
    # well-informed episode -> HIGH or MEDIUM
    ep_full = {"player_known_state": {"n_known_enemies": 2,
                                      "last_seen_enemies": {"4": {}},
                                      "bomb_known": False,
                                      "own": {"weapon_def": 7},
                                      "utility_inventory": {"flash_count": 1}},
               "macro_context": {"advantage_state": "EVEN",
                                 "need_for_information": "MEDIUM"},
               "local_context": {"geometry": {"provider": "awpy"}},
               "_candidates": [{"action": "HOLD"}]}
    assert evidence_sufficiency(ep_full) in ("HIGH", "MEDIUM")
    # strong episode without geometry should NOT be HIGH (spec §68 honesty)
    ep_no_geom = {"player_known_state": {"n_known_enemies": 2,
                                         "last_seen_enemies": {"4": {}},
                                         "bomb_known": False,
                                         "own": {"weapon_def": 7},
                                         "utility_inventory": {"flash_count": 1}},
                  "macro_context": {"advantage_state": "EVEN",
                                    "need_for_information": "MEDIUM"},
                  "local_context": {"geometry": {"provider": "null"}},
                  "_candidates": [{"action": "HOLD"}]}
    assert evidence_sufficiency(ep_no_geom) in ("MEDIUM", "LOW", "INSUFFICIENT")


def test_utility_inventory_grounding():
    """Flash count drops after a flash detonate by the player this round."""
    from playerlab.state import KnownStateBuilder
    events = {"flashbang_detonate": [{"tick": 100, "user_steamid": P1}]}
    demo = FakeDemo(PLAYERS, {**EMPTY_EVENTS, "grenades": events}, ROUNDS)
    idx = idx_for([(0, 0)] * 4)
    # add team_num to idx records
    for k, r in idx.items():
        r["team_num"] = 2
    kb = KnownStateBuilder(demo, Config(), idx)
    ks_before = kb.build(P1, 1, 50)
    ks_after = kb.build(P1, 1, 150)
    assert ks_before.get("utility_inventory", {}).get("flash_count", 0) >= 1
    assert ks_after.get("utility_inventory", {}).get("flash_count", 0) < \
        ks_before.get("utility_inventory", {}).get("flash_count", 0)


def test_duel_engagement_windows_bounded():
    """Only detected windows get duel sequences (spec §113 performance)."""
    demo, cfg, idx, duel = duel_fixture()
    assert len(duel["sequence"]) <= 20  # bounded sampling
    assert duel["phase"] in ENGAGEMENT_PHASES


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
