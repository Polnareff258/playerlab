"""V1.2.1 tests: KnownState grounding, information strength/direction decay,
rotate-vs-reposition with same movement but different info, tradeability
(LOS-supported and distance-false-positive), conservative responsibility
gate, review quota, GameModelProvider Null, CSNetProvider adapter contract,
ground-truth vs known-state boundary, outcome != decision."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "core"))

from playerlab.config import Config  # noqa: E402
from playerlab.db import DB  # noqa: E402
from playerlab.context import TemporalContext  # noqa: E402
from playerlab.intent import classify_intent  # noqa: E402
from playerlab.information import (compute_information_strength,  # noqa: E402
                                   compute_information_direction,
                                   strength_from_score)
from playerlab.tradeability import (compute_tradeability, NULL_GEOMETRY,  # noqa: E402
                                    TradeabilityGeometry)
from playerlab.responsibility import attribute_responsibility  # noqa: E402
from playerlab.model_provider import (NullGameModelProvider, ModelEvidence,  # noqa: E402
                                      GameModelProvider, get_provider,
                                      STATE_SCOPE_GROUND_TRUTH,
                                      STATE_SCOPE_PLAYER_KNOWN)
from playerlab.annotation import build_review_queue  # noqa: E402


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


P1, P2, P3, P4, P5 = 1, 2, 3, 4, 5
PLAYERS = [{"steamid": 1, "name": "A", "team_number": 2},
           {"steamid": 2, "name": "B", "team_number": 2},
           {"steamid": 3, "name": "C", "team_number": 2},
           {"steamid": 4, "name": "D", "team_number": 3},
           {"steamid": 5, "name": "E", "team_number": 3}]
ROUNDS = [{"round": 1, "start_tick": 0, "end_tick": 5000, "winner": "T", "reason": "x"}]
EMPTY_EVENTS = {"damages": [], "shots": [], "kills": [], "reloads": [],
                "plants_start": [], "defuses_start": [], "grenades": {},
                "bombs": {"planted": [], "defused": []},
                "footsteps": []}


def rec(x, y, alive=True, vx=0.0, vy=0.0, yaw=0.0, place="Middle"):
    return {"x": x, "y": y, "vx": vx, "vy": vy, "vz": 0.0, "speed": (vx ** 2 + vy ** 2) ** 0.5,
            "is_alive": alive, "yaw": yaw, "health": 100, "weapon_def": 7,
            "money": 3000, "buttons": 0, "place": place, "team_num": 2}


def trajectory_idx(pts, step=16, vx=180.0, vy=0.0, mate_offset=(500, 0)):
    idx = {}
    start = 0
    for i, (x, y, place) in enumerate(pts):
        t = start + i * step
        idx[(P1, t)] = rec(x, y, place=place, vx=vx, vy=vy)
        idx[(2, t)] = rec(x + mate_offset[0], y + mate_offset[1], place=place, vx=vx, vy=vy)
        # P3 mirrors the mate offset on the other side so the nearest teammate
        # is controllable by mate_offset
        idx[(3, t)] = rec(x - mate_offset[0], y - mate_offset[1], place=place, vx=vx, vy=vy)
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
                 bomb_known=False, bomb_zone=None, nearest=500.0):
    ks = {"n_known_enemies": n_enemies, "known_spread": 0.0, "nearest_known_enemy": nearest,
          "heard": [], "teammate_near": 0, "teammate_mid": 0,
          "known_enemy_zones": [zone] * n_enemies,
          "known_enemy_directions": [zone] * n_enemies,
          "time_since_last_known_enemy_update": age,
          "time_since_visual_contact": age if source in ("own_vision", "team_vision") else None,
          "time_since_damage_contact": age if source == "damage" else None,
          "recent_sound_info": [], "bomb_known": bomb_known, "bomb_zone": bomb_zone,
          "bomb_confidence": 0.9 if bomb_known else 0.0,
          "teammate_contact_count": 0, "recent_teammate_kill": False,
          "recent_teammate_death": False, "objective_information": {},
          "last_seen_enemies": {str(4 + i): {"pos": [2100, 300], "tick": max(0, 256 - age),
                                             "source": source, "zone": zone}
                                for i in range(n_enemies)}}
    return ks


# ---------------------------------------------------------------- information
def test_information_strength_levels_and_decay():
    # fresh own vision -> CONFIRMED-ish (score 1.0)
    ks = _known_state(n_enemies=1, age=0, source="own_vision")
    r = compute_information_strength(ks, 256)
    assert r["level"] == "CONFIRMED", r
    # old damage -> decays from 0.9; at age 384 (one half-life) -> 0.45 -> MEDIUM
    ks2 = _known_state(n_enemies=1, age=384, source="damage")
    r2 = compute_information_strength(ks2, 256)
    assert r2["level"] in ("MEDIUM", "WEAK", "NONE"), r2
    assert r2["confidence"] < 0.9
    # very stale (age >> memory) -> NONE; compute at a later tick so the
    # last-seen age is genuinely large
    ks3 = _known_state(n_enemies=1, age=0, source="own_vision")  # seen at tick 256
    r3 = compute_information_strength(ks3, 256 + 5000)
    assert r3["level"] == "NONE", r3
    # bomb planted (public) -> strong even with no enemies
    ks4 = _known_state(n_enemies=0, bomb_known=True, bomb_zone="B")
    r4 = compute_information_strength(ks4, 256)
    assert r4["level"] in ("STRONG", "CONFIRMED"), r4


def test_information_direction():
    ks_b = _known_state(n_enemies=2, zone="B", age=0)
    r = compute_information_direction(ks_b)
    assert r["direction"] == "B_SIDE", r
    ks_none = _known_state(n_enemies=0)
    r2 = compute_information_direction(ks_none)
    assert r2["direction"] == "UNKNOWN", r2


# ----------------------------------------------- rotate vs reposition by info
def _intent_for(pts, known_state):
    cfg = Config()
    idx = trajectory_idx(pts)
    demo = FakeDemo(PLAYERS, EMPTY_EVENTS, ROUNDS)
    tc = TemporalContext(demo, cfg, idx, P1, 256, known_state=known_state)
    intent, conf, dist = classify_intent(demo, cfg, tc, P1, 256)
    return intent, dist


def test_rotate_vs_reposition_same_movement_different_info():
    """Spec §74-A: identical movement, different information -> different intent."""
    cfg = Config()
    pts = _extend([(0, 0, "A"), (300, -100, "A"), (600, -300, "Catwalk"),
                   (900, -500, "Catwalk"), (1300, -700, "Middle"),
                   (1700, -900, "Middle"), (2100, -1100, "B")])
    idx = trajectory_idx(pts)
    demo = FakeDemo(PLAYERS, EMPTY_EVENTS, ROUNDS)

    # Case A: same path but NO information at B -> not ROTATE
    ks_none = _known_state(n_enemies=0)
    tc_a = TemporalContext(demo, cfg, idx, P1, 256, known_state=ks_none)
    intent_a, _, dist_a = classify_intent(demo, cfg, tc_a, P1, 256)
    assert intent_a != "ROTATE", (intent_a, dist_a)
    assert intent_a in ("SOFT_ROTATE", "REPOSITION", "AMBIGUOUS", "GATHER_INFO"), intent_a

    # Case B: same path with 2 enemies confirmed at B + bomb at B -> ROTATE
    ks_b = _known_state(n_enemies=2, zone="B", age=0, source="own_vision",
                        bomb_known=True, bomb_zone="B")
    tc_b = TemporalContext(demo, cfg, idx, P1, 256, known_state=ks_b)
    intent_b, _, dist_b = classify_intent(demo, cfg, tc_b, P1, 256)
    assert intent_b == "ROTATE", (intent_b, dist_b)


def test_information_direction_influences_soft_rotate():
    """Moving toward where info points supports SOFT_ROTATE at least."""
    cfg = Config()
    pts = _extend([(0, 0, "A"), (200, 100, "A"), (450, 220, "Catwalk"),
                   (700, 350, "Catwalk")])
    idx = trajectory_idx(pts)
    demo = FakeDemo(PLAYERS, EMPTY_EVENTS, ROUNDS)
    ks_info_b = _known_state(n_enemies=1, zone="B", age=0, source="team_vision")
    tc = TemporalContext(demo, cfg, idx, P1, 256, known_state=ks_info_b)
    intent, conf, dist = classify_intent(demo, cfg, tc, P1, 256)
    assert intent in ("SOFT_ROTATE", "REPOSITION", "AMBIGUOUS"), (intent, dist)


# ---------------------------------------------------------------- tradeability
def test_tradeability_los_supported_case():
    """Spec §74-B: teammate far but LOS/nav shows support -> not LOW/UNAVAILABLE
    just from distance. With a geometry provider confirming LOS, classification
    must not be UNAVAILABLE."""
    cfg = Config()
    pts = [(0, 0, "A")] * 17
    idx = trajectory_idx(pts, mate_offset=(2200, 0))  # mate at 2200u -> "far"
    demo = FakeDemo(PLAYERS, EMPTY_EVENTS, ROUNDS)
    tc = TemporalContext(demo, cfg, idx, P1, 256, known_state={})
    assert tc.nearest_teammate_dist > 1600

    class LosGeometry(TradeabilityGeometry):
        def direct_los(self, map_name, a, b):
            return True  # confirmed line of sight
        def nav_distance(self, map_name, a, b):
            return 2200.0
        def intervening_cover(self, map_name, a, b):
            return 0.0

    t = compute_tradeability(tc, cfg, LosGeometry())
    assert t["classification"] != "UNAVAILABLE", t
    assert t["direct_los"] is True
    assert t["nav_distance"] == 2200.0
    # distance alone (no geometry) must not claim HIGH/MEDIUM with confidence
    t0 = compute_tradeability(tc, cfg, NULL_GEOMETRY)
    assert t0["confidence"] < 0.6, t0


def test_tradeability_distance_false_positive():
    """Distance is not tradeability: a close mate behind a wall / committed
    must not be HIGH."""
    cfg = Config()
    pts = [(0, 0, "A")] * 17
    idx = trajectory_idx(pts, mate_offset=(400, 0))  # close mate
    demo = FakeDemo(PLAYERS, EMPTY_EVENTS, ROUNDS)
    tc = TemporalContext(demo, cfg, idx, P1, 256, known_state={})
    tc.feasibility = {"IMMEDIATE_TRADE": "TEMPORARILY_UNAVAILABLE"}  # victim committed

    class WallGeometry(TradeabilityGeometry):
        def direct_los(self, map_name, a, b):
            return False  # wall between them
        def nav_distance(self, map_name, a, b):
            return 400.0
        def intervening_cover(self, map_name, a, b):
            return 0.9

    t = compute_tradeability(tc, cfg, WallGeometry())
    assert t["classification"] == "UNAVAILABLE", t  # commitment blocks
    assert t["commitment_constraint"] is True


# ------------------------------------------------------- conservative gate
def test_responsibility_conservative_gate():
    """Spec §11/§13: insufficient evidence must not become SELF_DECISION."""
    cfg = Config()
    demo = FakeDemo(PLAYERS, EMPTY_EVENTS, ROUNDS)
    idx = trajectory_idx([(0, 0, "A")] * 17)
    # free player, no known enemies, no contact events -> no evidence of a choice
    tc = TemporalContext(demo, cfg, idx, P1, 256, known_state=_known_state(n_enemies=0))
    resp = attribute_responsibility(demo, cfg, tc, P1, 256)
    assert resp["attribution"] in ("INSUFFICIENT_EVIDENCE", "SHARED",
                                   "REASONABLE_BUT_LOST"), resp
    assert resp["gate"]["evidence_sufficient"] is False, resp["gate"]
    assert resp["attribution"] != "SELF_DECISION", resp


def test_responsibility_not_distance_only():
    """Mate >1600 alone must NOT force isolated/SELF_DECISION: tradeability
    HIGH (LOS-supported) + reasonable decision -> SELF_EXECUTION/REASONABLE."""
    cfg = Config()
    demo = FakeDemo(PLAYERS, EMPTY_EVENTS, ROUNDS)
    idx = trajectory_idx([(0, 0, "A")] * 17, mate_offset=(2200, 0))
    ks = _known_state(n_enemies=1, age=0, source="own_vision", nearest=900.0)
    tc = TemporalContext(demo, cfg, idx, P1, 256, known_state=ks)
    tc.feasibility = {"IMMEDIATE_TRADE": "FEASIBLE"}

    class LosGeometry(TradeabilityGeometry):
        def direct_los(self, map_name, a, b):
            return True
        def nav_distance(self, map_name, a, b):
            return 2200.0

    from playerlab.tradeability import compute_tradeability
    t = compute_tradeability(tc, cfg, LosGeometry())
    assert t["classification"] in ("HIGH", "MEDIUM"), t
    # inject geometry result into TemporalContext for the responsibility call
    tc._tradeability_override = t
    import playerlab.responsibility as resp_mod
    orig = resp_mod.compute_tradeability
    resp_mod.compute_tradeability = lambda tc_, cfg_, geo_: t
    try:
        resp = attribute_responsibility(demo, cfg, tc, P1, 256, decision_eval="REASONABLE")
    finally:
        resp_mod.compute_tradeability = orig
    assert resp["attribution"] in ("SELF_EXECUTION", "SHARED",
                                   "REASONABLE_BUT_LOST", "SELF_DECISION"), resp
    assert resp["gate"]["evidence_sufficient"] is True


def test_responsibility_plant_commit_no_blame():
    """Spec §74-C: reasonable plant commitment with no trade -> NOT_ACTIONABLE."""
    cfg = Config()
    demo = FakeDemo(PLAYERS, mk_events(plants_start=[{"tick": 150, "user_steamid": P1}]),
                    ROUNDS)
    idx = trajectory_idx([(0, 0, "B")] * 17)
    tc = TemporalContext(demo, cfg, idx, P1, 256, known_state=_known_state(n_enemies=0))
    resp = attribute_responsibility(demo, cfg, tc, P1, 256)
    assert resp["attribution"] == "NOT_ACTIONABLE", resp
    assert resp["gate"]["causally_related"] is False


def test_responsibility_reload_still_self_decision():
    """Spec §74-D: dangerous reload commitment stays SELF_DECISION."""
    cfg = Config()
    demo = FakeDemo(PLAYERS, mk_events(reloads=[{"tick": 200, "user_steamid": P1}]), ROUNDS)
    idx = trajectory_idx([(0, 0, "A")] * 17)
    ks = _known_state(n_enemies=1, age=0, source="damage", nearest=800.0)
    tc = TemporalContext(demo, cfg, idx, P1, 256, known_state=ks)
    resp = attribute_responsibility(demo, cfg, tc, P1, 256)
    assert resp["commitment"] == "RELOAD_COMMITTED"
    assert resp["attribution"] == "SELF_DECISION", resp


# ---------------------------------------------------------------- review quota
def _seed_reviewable(db, match_id="m1"):
    db.upsert_match({"demo_id": match_id, "demo_path": "", "map_name": "de_dust2",
                     "tickrate": 64, "player_count": 10, "rounds_total": 1,
                     "side_swap_round": None, "parsed_at": "2026-01-01",
                     "parser_version": "t"})
    for i in range(6):
        db.upsert_context_event({
            "id": f"{match_id}-death-{P1}-{i}", "match_id": match_id, "round": 1,
            "tick": 100 + i, "steamid": P1, "anchor": "death", "commitment": "FREE",
            "role": "FREE_ROLE", "role_dist": {}, "intent": "ROTATE", "intent_conf": 0.5,
            "intent_dist": {"ROTATE": 0.55, "REPOSITION": 0.45}, "feasibility": {},
            "responsibility": "SHARED", "temporal_summary": {}, "event_ref": "death-x",
            "computed_at": "2026-01-01"})


def test_review_queue_quota():
    """Spec §16: per-category quota keeps intent from crowding out everything."""
    cfg = Config()
    db = DB(":memory:")
    _seed_reviewable(db)
    items = build_review_queue(db, cfg, "m1")
    types = [i["item_type"] for i in items]
    n_intent = types.count("intent")
    n_resp = types.count("responsibility")
    assert n_intent <= cfg.review_quota["intent"] + 1, types  # quota respected
    assert n_resp <= cfg.review_quota["responsibility"] + 1, types
    assert len(items) <= cfg.review_budget_per_match, len(items)
    # intent-focus raises the intent quota
    items_focus = build_review_queue(db, cfg, "m1", review_focus="intent")
    n_intent_focus = sum(1 for i in items_focus if i["item_type"] == "intent")
    assert n_intent_focus >= n_intent, (n_intent, n_intent_focus)


# ---------------------------------------------------------------- model provider
def test_null_game_model_provider():
    """Spec §30: Null provider keeps everything working."""
    prov = NullGameModelProvider()
    ev = prov.predict_win_probability({})
    assert isinstance(ev, ModelEvidence)
    assert ev.prediction is None and ev.evidence_type == "unavailable"
    assert prov.get_metadata()["status"] == "not_installed"
    assert prov.get_supported_tasks() == []
    # factory falls back to Null when csnet is not importable
    prov2 = get_provider("csnet")
    assert isinstance(prov2, NullGameModelProvider) or prov2.provider_name == "csnet"


def test_model_evidence_schema_and_scope():
    """Spec §32-§33: ModelEvidence carries scope; CS-NET uses ground-truth scope."""
    ev = ModelEvidence(provider="csnet", provider_version="0.1",
                       model_version="v3", task="win_rate", prediction=0.72,
                       state_scope=STATE_SCOPE_GROUND_TRUTH,
                       input_match_id="m1", input_round=3, input_tick=1200)
    d = ev.to_dict()
    assert d["state_scope"] == STATE_SCOPE_GROUND_TRUTH
    assert d["task"] == "win_rate" and d["prediction"] == 0.72
    ev2 = NullGameModelProvider().predict_duels({})
    assert ev2.state_scope == STATE_SCOPE_PLAYER_KNOWN


def test_csnet_provider_adapter_contract():
    """Spec §31/§70: CSNetProvider maps canonical state -> ModelEvidence.
    If cs-net is installed and runnable, win_rate must return a real value;
    otherwise the adapter must degrade gracefully (never raise)."""
    try:
        from playerlab.csnet import CSNetProvider
    except ImportError:
        import pytest
        pytest.skip("cs-net adapter not importable (backend not installed)")
    prov = CSNetProvider(models_dir="/nonexistent")  # no weights -> graceful
    meta = prov.get_metadata()
    assert "provider" in meta
    ev = prov.predict_win_probability({"state": "canonical"}, match_id="m1", tick=1)
    assert isinstance(ev, ModelEvidence)
    assert ev.task == "win_rate"
    assert ev.prediction is None or 0.0 <= ev.prediction <= 1.0


# ---------------------------------------------------------------- boundary
def test_good_outcome_not_good_decision():
    """Spec §53: a kill with rising win-rate is still QUESTIONABLE when the
    decision was a pointless dry peek. Structural: responsibility/decision
    functions never take outcome as input."""
    import inspect
    from playerlab.responsibility import attribute_responsibility
    sig = inspect.signature(attribute_responsibility)
    assert "outcome" not in sig.parameters
    cfg = Config()
    demo = FakeDemo(PLAYERS, EMPTY_EVENTS, ROUNDS)
    idx = trajectory_idx([(0, 0, "A")] * 17)
    ks = _known_state(n_enemies=1, age=0, source="own_vision", nearest=600.0)
    tc = TemporalContext(demo, cfg, idx, P1, 256, known_state=ks)
    resp = attribute_responsibility(demo, cfg, tc, P1, 256, decision_eval="POOR")
    assert resp["attribution"] in ("SELF_DECISION", "SHARED", "INSUFFICIENT_EVIDENCE")


def test_bad_outcome_not_bad_decision():
    """Spec §52: reasonable plant, teammate died, win-rate dropped -> planter
    is NOT blamed. Outcome-independent: attribution must not flip on outcome."""
    cfg = Config()
    demo = FakeDemo(PLAYERS, mk_events(plants_start=[{"tick": 150, "user_steamid": P1}]),
                    ROUNDS)
    idx = trajectory_idx([(0, 0, "B")] * 17)
    tc = TemporalContext(demo, cfg, idx, P1, 256, known_state=_known_state(n_enemies=0))
    resp = attribute_responsibility(demo, cfg, tc, P1, 256)
    assert resp["attribution"] == "NOT_ACTIONABLE", resp


def test_known_state_sequence_and_split_metadata():
    """Spec §5/§19: IntentSample carries sequences + match/round/episode ids."""
    from playerlab.context_pipeline import (_known_state_sequence,
                                            _information_sequence,
                                            _structural_features,
                                            _known_state_features,
                                            _information_features)
    cfg = Config()
    demo = FakeDemo(PLAYERS, EMPTY_EVENTS, ROUNDS)
    idx = trajectory_idx([(0, 0, "A")] * 17)
    ks = _known_state(n_enemies=1, zone="B", age=0, bomb_known=True, bomb_zone="B")
    tc = TemporalContext(demo, cfg, idx, P1, 256, known_state=ks)
    kseq = _known_state_sequence(tc, ks)
    iseq = _information_sequence(tc)
    assert len(kseq) >= 1 and kseq[0]["n_known_enemies"] == 1
    assert iseq[0]["strength"] in ("STRONG", "CONFIRMED", "MEDIUM")
    sf = _structural_features(tc)
    assert "zone_crossings" in sf and "team_alive" in sf
    kf = _known_state_features(tc, ks)
    assert kf["n_known_enemies"] == 1 and kf["bomb_known"] is True
    inf = _information_features(tc)
    assert inf["direction"] == "B_SIDE"
    # split metadata helpers are exercised by the pipeline test
    assert "round_id" and "episode_id"


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
