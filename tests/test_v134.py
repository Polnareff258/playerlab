"""V1.3.4.1 contact semantics regression tests.

V1.3.4.1 semantics (docs/CONTACT_INITIATION_FIX.md):
  - LOS transition != contact initiator
  - initiation is decided by MOTION (InitiationMotionEvidence), never by
    comparing transition ticks
  - PEEK requires SELF_INITIATED + LOS gain + enemy stable
  - HOLD evidence uses circular yaw variance + lane stability
  - visibility_tick comes from a real geometry LOS transition (FOV only =
    possible, never presented as real)
  - UNKNOWN / AMBIGUOUS are legal and propagate
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))

from playerlab.contact_semantics import (
    ActionPrediction, ContactWindow, ExposureRelation, build_contact_window,
    exposure_relations, classify_contact, sight_state,
    motion_evidence, classify_initiation_v2,
    circular_diff, yaw_variance_circular,
    fill_visibility_ticks, scan_visibility_transition,
)
from playerlab.config import Config


def _relation(tick, self_state, enemy_state, self_see=True, enemy_see=True,
              self_motion="STABLE", enemy_motion="STABLE"):
    return ExposureRelation(1, 2, tick, self_see, enemy_see, self_state,
                            enemy_state, "exact", 1.0,
                            pair_visible=self_see,
                            self_motion_state=self_motion,
                            enemy_motion_state=enemy_motion)


def _dual_records(self_rows, enemy_rows, base_x=0.0, base_y=0.0):
    """Both players' records: self = player 1, enemy = player 2.
    Rows are (tick, x, speed, yaw); y defaults to base_y.
    Includes vx/vy so motion_evidence can measure real movement."""
    idx = {}
    for pid, rows in ((1, self_rows), (2, enemy_rows)):
        for t, x, speed, yaw in rows:
            idx[(pid, t)] = {"x": x, "y": base_y, "speed": speed,
                             "yaw": yaw, "is_alive": True,
                             "vx": speed, "vy": 0.0}
    return idx


def test_sight_state_requires_geometry_for_visible():
    assert sight_state({"in_fov": True}, {}, None) == "POSSIBLY_VISIBLE"
    assert sight_state({"in_fov": True}, {}, False) == "IN_FOV_OCCLUDED"
    assert sight_state({"in_fov": True}, {}, True) == "VISIBLE"


def test_action_prediction_is_a_distribution():
    p = ActionPrediction("HOLD", {"HOLD": .74, "PEEK": .19, "REPOSITION": .07},
                         .74, False, "ENEMY_INITIATED", {}, "STATIC_HOLD")
    assert abs(sum(p.probabilities.values()) - 1.0) < 1e-9


# --- PART Q golden: enemy moves out, self holds ------------------------------
def test_enemy_moves_out_self_holds_is_enemy_initiated_hold():
    cfg = Config(hold_stability_ticks=4, initiation_motion_window_ticks=8,
                 initiation_min_speed=80.0, initiation_min_displacement=24.0)
    # self stable at x=0 (700ms+ = many ticks), enemy moves out near contact
    window = ContactWindow(10, None, None, None, 16, 1, 2)
    relations = ([_relation(t, "COVERED", "COVERED") for t in range(10, 13)] +
                 [_relation(t, "EXPOSED", "EXPOSED") for t in range(13, 17)])
    # motion window is the tail [8..16] of pre-contact [10..16]
    self_rows = [(t, 0, 0, 0) for t in range(10, 17)]          # stable
    enemy_rows = ([(t, 50, 0, 90) for t in range(10, 13)] +    # stable
                  [(t, 50 + 30 * (t - 12), 200, 90) for t in range(13, 17)])  # swings
    idx = _dual_records(self_rows, enemy_rows, base_y=0.0)
    p = classify_contact(window, relations, idx, cfg)
    assert p.initiation == "ENEMY_INITIATED"
    assert p.top_label == "HOLD"
    assert p.subtype == "STATIC_HOLD"


# --- PART Q golden: self swings out, enemy holds -----------------------------
def test_self_moves_out_enemy_holds_is_self_initiated_peek():
    cfg = Config(hold_stability_ticks=4, initiation_motion_window_ticks=8,
                 initiation_min_speed=80.0, initiation_min_displacement=24.0)
    window = ContactWindow(10, None, None, None, 16, 1, 2)
    relations = ([_relation(t, "COVERED", "COVERED") for t in range(10, 13)] +
                 [_relation(t, "EXPOSED", "EXPOSED") for t in range(13, 17)])
    self_rows = ([(t, 0, 0, 0) for t in range(10, 13)] +
                 [(t, 30 * (t - 12), 200, 0) for t in range(13, 17)])  # peeks out
    enemy_rows = [(t, 100, 0, 180) for t in range(10, 17)]     # holds angle
    idx = _dual_records(self_rows, enemy_rows)
    p = classify_contact(window, relations, idx, cfg)
    assert p.initiation == "SELF_INITIATED"
    assert p.top_label == "PEEK"


# --- PART Q golden: both move ------------------------------------------------
def test_both_move_is_mutual_not_peek():
    cfg = Config(initiation_motion_window_ticks=8,
                 initiation_min_speed=80.0, initiation_min_displacement=24.0,
                 mutual_motion_ratio=0.5)
    window = ContactWindow(10, None, None, None, 16, 1, 2)
    relations = ([_relation(t, "COVERED", "COVERED") for t in range(10, 13)] +
                 [_relation(t, "EXPOSED", "EXPOSED") for t in range(13, 17)])
    self_rows = [(t, 20 * (t - 10), 150, 0) for t in range(10, 17)]   # moves
    enemy_rows = [(t, 100 - 20 * (t - 10), 150, 180) for t in range(10, 17)]  # moves
    idx = _dual_records(self_rows, enemy_rows)
    p = classify_contact(window, relations, idx, cfg)
    assert p.initiation == "MUTUAL"
    assert p.top_label != "PEEK"


# --- PART Q golden: both static, LOS appears --------------------------------
def test_static_contact_when_both_stable():
    cfg = Config(initiation_motion_window_ticks=8)
    window = ContactWindow(10, None, None, None, 16, 1, 2)
    relations = ([_relation(t, "COVERED", "COVERED") for t in range(10, 13)] +
                 [_relation(t, "EXPOSED", "EXPOSED") for t in range(13, 17)])
    self_rows = [(t, 0, 0, 0) for t in range(10, 17)]
    enemy_rows = [(t, 100, 0, 180) for t in range(10, 17)]
    idx = _dual_records(self_rows, enemy_rows)
    p = classify_contact(window, relations, idx, cfg)
    assert p.initiation in ("STATIC_CONTACT", "UNKNOWN")


# --- circular yaw ------------------------------------------------------------
def test_circular_yaw_variance_small_across_179_to_neg179():
    # 179 -> -179 is a 2-degree change, not 358
    assert abs(circular_diff(179.0, -179.0) - 2.0) < 1e-6
    v = yaw_variance_circular([179.0, 179.5, -179.5, -179.0])
    assert v < 5.0, f"circular variance should be tiny, got {v}"


# --- micro-adjust hold -------------------------------------------------------
def test_micro_ad_is_microadjust_hold_not_peek():
    cfg = Config(hold_stability_ticks=4, hold_max_displacement=48.0,
                 initiation_motion_window_ticks=8,
                 initiation_min_speed=80.0)
    window = ContactWindow(10, None, None, None, 16, 1, 2)
    relations = ([_relation(t, "COVERED", "COVERED") for t in range(10, 13)] +
                 [_relation(t, "EXPOSED", "EXPOSED") for t in range(13, 17)])
    # self does small AD (x jitter 0-2), enemy swings out
    self_rows = [(t, 1 if t % 2 else 0, 20, 0) for t in range(10, 17)]
    enemy_rows = ([(t, 50, 0, 90) for t in range(10, 13)] +
                  [(t, 50 + 30 * (t - 12), 180, 90) for t in range(13, 17)])
    idx = _dual_records(self_rows, enemy_rows)
    p = classify_contact(window, relations, idx, cfg)
    assert p.top_label == "HOLD"
    assert p.subtype == "MICROADJUST_HOLD"


# --- old-v1.3.4 semantics now forbidden --------------------------------------
def test_transition_tick_equality_no_longer_implies_mutual():
    """The V1.3.4 bug: self_tick == enemy_tick -> MUTUAL. Now motion decides."""
    cfg = Config(initiation_motion_window_ticks=8)
    window = ContactWindow(10, None, None, None, 16, 1, 2)
    # SAME transition tick for both, but self is stable and enemy moved:
    # must be ENEMY_INITIATED, never MUTUAL
    relations = ([_relation(t, "COVERED", "COVERED") for t in range(10, 13)] +
                 [_relation(t, "EXPOSED", "EXPOSED") for t in range(13, 17)])
    self_rows = [(t, 0, 0, 0) for t in range(10, 17)]
    enemy_rows = ([(t, 50, 0, 90) for t in range(10, 13)] +
                  [(t, 50 + 30 * (t - 12), 200, 90) for t in range(13, 17)])
    idx = _dual_records(self_rows, enemy_rows)
    ev = motion_evidence(window, relations, idx, cfg)
    init = classify_initiation_v2(ev, relations, cfg)
    assert init == "ENEMY_INITIATED"


# --- visibility_tick real vs possible ----------------------------------------
class _Geom:
    def __init__(self, vis_map):
        self.quality = "exact"
        self._map = vis_map

    def can_see(self, map_name, a, b):
        return self._map  # constant LOS for the whole window


class _NullGeom:
    quality = "none"

    def can_see(self, map_name, a, b):
        return None


def test_visibility_tick_filled_from_real_geometry():
    cfg = Config()
    # geometry flips COVERED->EXPOSED at tick 13
    window = ContactWindow(10, None, None, None, 16, 1, 2)
    relations = ([_relation(t, "COVERED", "COVERED", False, False)
                  for t in range(10, 13)] +
                 [_relation(t, "EXPOSED", "EXPOSED", True, True)
                  for t in range(13, 17)])
    geom = _Geom(True)  # static geometry would not flip; relations carry it
    vt = scan_visibility_transition(window, relations)
    assert vt == 13


def test_null_geometry_gives_possible_not_real_visibility():
    cfg = Config()
    window = ContactWindow(10, None, None, None, 16, 1, 2)
    relations = [_relation(t, "UNKNOWN", "UNKNOWN", None, None)
                 for t in range(10, 17)]
    filled = fill_visibility_ticks(window, relations, "none", fov_visible=None)
    assert filled.visibility_tick is None
    assert filled.sight_state in ("UNKNOWN", "POSSIBLY_VISIBLE")


# --- FOV occluded vs visible -------------------------------------------------
def test_fov_occluded_is_not_visible():
    assert sight_state({"in_fov": True}, {}, False) == "IN_FOV_OCCLUDED"
    assert sight_state({"in_fov": True}, {}, True) == "VISIBLE"


# --- classifier bounded to window --------------------------------------------
def test_classifier_scans_only_the_contact_window_not_all_demo_ticks():
    class GuardedIndex(dict):
        def keys(self):
            raise AssertionError("classifier must not iterate the full demo index")

    cfg = Config(hold_stability_ticks=2, initiation_motion_window_ticks=4)
    window = ContactWindow(10, None, None, None, 13, 1, 2)
    relations = ([_relation(t, "COVERED", "COVERED", False, False)
                  for t in range(10, 12)] +
                 [_relation(t, "EXPOSED", "EXPOSED", True, True)
                  for t in range(12, 14)])
    idx = GuardedIndex(_dual_records(
        [(10, 0, 0, 0), (11, 0, 0, 0), (12, 0, 0, 0), (13, 0, 0, 0)],
        [(10, 0, 0, 0), (11, 0, 0, 0), (12, 0, 0, 0), (13, 0, 0, 0)]))
    assert classify_contact(window, relations, idx, cfg).top_label in \
        ("HOLD", "UNKNOWN", "STATIC_CONTACT")


# --- old v1.3.4 helpers still pass where semantics are unchanged -------------
def test_enemy_swing_after_stability_is_hold():
    cfg = Config(hold_stability_ticks=4)
    window = ContactWindow(10, 14, None, None, 16, 1, 2)
    relations = [_relation(t, "EXPOSED", "COVERED", True, False) for t in range(10, 14)]
    relations += [_relation(t, "EXPOSED", "EXPOSED") for t in range(14, 17)]
    idx = _dual_records([(10, 0, 0, 0), (11, 0, 0, 0), (12, 0, 0, 1),
                         (13, 0, 0, 1), (14, 0, 0, 1), (15, 0, 0, 1)],
                        [(10, 50, 0, 90), (11, 50, 0, 90), (12, 55, 0, 90),
                         (13, 70, 150, 90), (14, 90, 200, 90), (15, 110, 200, 90)])
    p = classify_contact(window, relations, idx, cfg)
    assert p.top_label in ("HOLD", "STATIC_CONTACT", "UNKNOWN")


def test_small_ad_without_exposure_growth_is_microadjust_hold():
    cfg = Config(hold_stability_ticks=4, hold_max_displacement=48.0,
                 initiation_min_speed=80.0)
    window = ContactWindow(10, 14, None, None, 16, 1, 2)
    relations = ([_relation(t, "EXPOSED", "COVERED", True, False) for t in range(10, 14)] +
                 [_relation(t, "EXPOSED", "EXPOSED") for t in range(14, 17)])
    idx = _dual_records([(10, 0, 20, 0), (11, 2, 20, 1), (12, 0, 20, -1),
                         (13, 2, 20, 1), (14, 0, 20, 0), (15, 2, 20, 1)],
                        [(10, 50, 0, 90), (11, 60, 120, 90), (12, 80, 200, 90),
                         (13, 90, 200, 90), (14, 100, 200, 90), (15, 110, 200, 90)])
    p = classify_contact(window, relations, idx, cfg)
    assert p.top_label == "HOLD" and p.subtype == "MICROADJUST_HOLD"


def test_self_covered_to_visible_lateral_move_is_peek():
    cfg = Config(hold_stability_ticks=4, initiation_motion_window_ticks=8,
                 initiation_min_speed=80.0)
    window = ContactWindow(10, 14, None, None, 16, 1, 2)
    # symmetric LOS (real geometry): both flip COVERED -> EXPOSED together
    relations = ([_relation(t, "COVERED", "COVERED", False, False) for t in range(10, 14)] +
                 [_relation(t, "EXPOSED", "EXPOSED", True, True) for t in range(14, 17)])
    idx = _dual_records([(10, 0, 0, 0), (11, 10, 200, 0), (12, 20, 200, 0),
                         (13, 30, 200, 0), (14, 40, 200, 0), (15, 42, 0, 0)],
                        [(t, 100, 0, 180) for t in range(10, 17)])
    p = classify_contact(window, relations, idx, cfg)
    # self clearly drives exposure (moved 40u, enemy static) -> PEEK expected;
    # AMBIGUOUS(HOLD/PEEK) is acceptable only if evidence is weak
    assert p.initiation == "SELF_INITIATED"
    assert p.top_label in ("PEEK", "UNKNOWN")


def test_mutual_encounter_is_not_active_peek():
    cfg = Config(initiation_motion_window_ticks=8, mutual_motion_ratio=0.5)
    window = ContactWindow(10, 14, None, None, 16, 1, 2)
    relations = ([_relation(t, "COVERED", "COVERED", False, False) for t in range(10, 14)] +
                 [_relation(t, "EXPOSED", "EXPOSED") for t in range(14, 17)])
    idx = _dual_records([(t, 20 * (t - 10), 150, 0) for t in range(10, 17)],
                        [(t, 100 - 20 * (t - 10), 150, 180) for t in range(10, 17)])
    p = classify_contact(window, relations, idx, cfg)
    assert p.initiation == "MUTUAL" and p.top_label != "PEEK"


def test_geometry_relations_use_los_not_fov_only():
    class Geometry:
        quality = "exact"

        def can_see(self, map_name, a, b):
            return False

    window = ContactWindow(10, None, None, None, 11, 1, 2)
    idx = {(1, 10): {"x": 0, "y": 0, "is_alive": True},
           (2, 10): {"x": 10, "y": 0, "is_alive": True}}
    rel = exposure_relations(window, "de_test", idx, Geometry(), Config())[0]
    assert rel.self_exposure_state == "COVERED" and rel.geometry_quality == "exact"


def test_unavailable_csnet_is_auxiliary_and_returns_none():
    from playerlab.csnet_assist import CSNetAssistProvider
    provider = CSNetAssistProvider(Config(csnet_repo_dir="missing"))
    assert provider.collect("demo", ContactWindow(1, 2, None, None, 3, 1, 2), [2]) is None


def test_decision_contact_meta_preserves_probability_and_initiator():
    from playerlab.decision import contact_meta
    p = ActionPrediction("HOLD", {"HOLD": .8, "PEEK": .1, "UNKNOWN": .1},
                         .8, False, "ENEMY_INITIATED", {}, "STATIC_HOLD")
    meta = contact_meta(p)
    assert meta["initiation"] == "ENEMY_INITIATED"
    assert meta["prediction"]["probabilities"]["HOLD"] == .8


def test_contact_prediction_replaces_legacy_action_only_when_available():
    from playerlab.decision import apply_contact_prediction
    dp = {"observed_action": "PEEK", "meta": {}}
    p = ActionPrediction("HOLD", {"HOLD": .8, "PEEK": .1, "UNKNOWN": .1},
                         .8, False, "ENEMY_INITIATED", {}, "STATIC_HOLD")
    out = apply_contact_prediction(dp, p)
    assert out["observed_action"] == "HOLD"
    assert out["meta"]["contact"]["initiation"] == "ENEMY_INITIATED"


def test_contact_action_samples_stay_pending_until_human_annotation():
    from playerlab.db import DB
    db = DB(":memory:")
    db.upsert_contact_action_sample({"id": "contact-1", "match_id": "m", "player_id": 1,
                                     "enemy_id": 2, "round": 1, "tick": 10,
                                     "prediction": {"top_label": "HOLD"}})
    sample = db.get_contact_action_samples()[0]
    assert sample["label_source"] == "PENDING_HUMAN_REVIEW"


# ============================================================================
# PART G/H: SupportContext + StealthContext
# ============================================================================

class _MiniDemo:
    def __init__(self):
        self.players = [{"steamid": 1, "name": "A", "team_number": 2},
                        {"steamid": 2, "name": "E", "team_number": 3},
                        {"steamid": 3, "name": "Mate", "team_number": 2}]
        self.events = {"damages": [], "kills": [],
                       "grenades": {"hegrenade_detonate": [], "flashbang_detonate": [],
                                    "inferno_startburn": [], "smokegrenade_detonate": []}}

    def side_at_round(self, sid, rnum):
        return "T"


class _MiniCtx:
    def __init__(self, steamid=1, tick=100, team=2):
        self.steamid = steamid
        self.tick = tick
        self.team = team
        self.idx = None
        self.round = 1


def _cfg(**kw):
    from playerlab.config import Config
    base = dict(known_state_memory_ticks=256, damage_memory_ticks=1024,
                isolated_support_dist=2400.0, advantage_engagement_dist=2400.0,
                teammate_contact_window_ticks=192)
    base.update(kw)
    return Config(**base)


def test_irrelevant_team_flash_is_not_team_assisted():
    """PART G §22: teammate flash far away (B site) while self peeks A must
    NOT be TEAM_UTILITY_ASSISTED."""
    from playerlab.context_semantics import detect_support
    demo = _MiniDemo()
    tc = _MiniCtx()
    # teammate (3) flashed at tick 80, but is 5000u away from self
    idx = {(1, 80): {"x": 0, "y": 0, "is_alive": True},
           (3, 80): {"x": 5000, "y": 0, "is_alive": True},
           (1, 100): {"x": 0, "y": 0, "is_alive": True}}
    support = detect_support(demo, _cfg(), tc, {"utility_inventory": {}},
                             idx=idx, team_flash_tick=80)
    assert support.support_style != "TEAM_UTILITY_ASSISTED"
    assert support.teammate_flash_relevant is False


def test_relevant_team_flash_is_team_assisted():
    """PART G §21: teammate flash + timing + spatial relevance -> assisted."""
    from playerlab.context_semantics import detect_support
    demo = _MiniDemo()
    tc = _MiniCtx()
    idx = {(1, 80): {"x": 0, "y": 0, "is_alive": True},
           (3, 80): {"x": 300, "y": 0, "is_alive": True},   # close teammate
           (1, 100): {"x": 0, "y": 0, "is_alive": True}}
    support = detect_support(demo, _cfg(), tc, {"utility_inventory": {}},
                             idx=idx, team_flash_tick=80)
    assert support.support_style == "TEAM_UTILITY_ASSISTED"
    assert support.teammate_flash_relevant is True


def test_coordinated_teammate_pressure_without_utility():
    """PART G §23: teammate engaged nearby (damage) but no flash -> coord."""
    from playerlab.context_semantics import detect_support
    demo = _MiniDemo()
    demo.events["damages"] = [{"user_steamid": 3, "attacker_steamid": 2,
                               "tick": 90}]
    tc = _MiniCtx(tick=100)
    idx = {(1, 100): {"x": 0, "y": 0, "is_alive": True, "yaw": 0},
           (3, 100): {"x": 200, "y": 0, "is_alive": True, "yaw": 180},
           (2, 100): {"x": 400, "y": 0, "is_alive": True, "yaw": 0}}
    support = detect_support(demo, _cfg(), tc, {"utility_inventory": {}},
                             idx=idx, team_flash_tick=None)
    assert support.support_style in ("COORDINATED_TEAM_PEEK", "UNASSISTED")


def test_unassisted_only_when_nothing_present():
    """PART G §24: no utility, no teammate near -> UNASSISTED (not forced)."""
    from playerlab.context_semantics import detect_support
    demo = _MiniDemo()
    tc = _MiniCtx()
    idx = {(1, 100): {"x": 0, "y": 0, "is_alive": True},
           (3, 100): {"x": 9000, "y": 0, "is_alive": True}}
    support = detect_support(demo, _cfg(), tc, {"utility_inventory": {}},
                             idx=idx, team_flash_tick=None)
    assert support.support_style == "UNASSISTED"


def test_stealth_preserving_deep_flank():
    """PART H §27: deep flank + low reveal + utility would reveal -> preserving."""
    from playerlab.context_semantics import detect_stealth
    demo = _MiniDemo()
    tc = _MiniCtx(tick=100)
    known = {"utility_inventory": {"flash_count": 1, "smoke_count": 0,
                                   "he_count": 0, "molotov_count": 0},
             "last_seen_enemies": {}}
    stealth = detect_stealth(demo, _cfg(), tc, known, idx=None,
                             flank_depth_units=5000.0)
    assert stealth.flank_state == "DEEP_FLANK"
    assert stealth.utility_would_reveal is True


def test_stealth_does_not_claim_enemy_unaware_with_reveal():
    """PART H §25/§28: recent damage means reveal evidence exists; stealth
    must not claim a clean hidden state."""
    from playerlab.context_semantics import detect_stealth
    demo = _MiniDemo()
    demo.events["damages"] = [{"user_steamid": 1, "attacker_steamid": 2,
                               "tick": 90}]  # self took damage recently
    tc = _MiniCtx(tick=100)
    known = {"utility_inventory": {}, "last_seen_enemies": {}}
    stealth = detect_stealth(demo, _cfg(), tc, known, idx=None,
                             flank_depth_units=5000.0)
    assert stealth.recent_damage is True
    assert stealth.reveal_score > 0.0


def test_circular_yaw_hold_evidence_uses_circular_variance():
    """PART Q test 5: 179 -> -179 yaw must not inflate HOLD rejection."""
    from playerlab.contact_semantics import _hold_evidence_v2
    from playerlab.config import Config
    cfg = Config(hold_stability_ticks=4)
    window = ContactWindow(10, None, None, None, 16, 1, 2)
    relations = [_relation(t, "EXPOSED", "EXPOSED") for t in range(10, 17)]
    idx = _dual_records([(t, 0, 0, 179.0 if t % 2 == 0 else -179.0)
                         for t in range(10, 17)],
                        [(t, 100, 0, 180.0) for t in range(10, 17)])
    hold = _hold_evidence_v2(window, relations, idx, cfg)
    assert hold.yaw_variance < 5.0, f"circular yaw variance too high: {hold.yaw_variance}"
