"""V1.3.4 contact semantics regression tests."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))

from playerlab.contact_semantics import (
    ActionPrediction, ContactWindow, ExposureRelation, build_contact_window,
    exposure_relations, classify_contact,
    sight_state,
)
from playerlab.config import Config


def _relation(tick, self_state, enemy_state, self_see=True, enemy_see=True):
    return ExposureRelation(1, 2, tick, self_see, enemy_see, self_state,
                            enemy_state, "exact", 1.0)


def _records(rows):
    return {(1, t): {"x": x, "y": 0.0, "speed": speed, "yaw": yaw,
                     "is_alive": True}
            for t, x, speed, yaw in rows}


def test_sight_state_requires_geometry_for_visible():
    assert sight_state({"in_fov": True}, {}, None) == "POSSIBLY_VISIBLE"
    assert sight_state({"in_fov": True}, {}, False) == "IN_FOV_OCCLUDED"
    assert sight_state({"in_fov": True}, {}, True) == "VISIBLE"


def test_action_prediction_is_a_distribution():
    p = ActionPrediction("HOLD", {"HOLD": .74, "PEEK": .19, "REPOSITION": .07},
                         .74, False, "ENEMY_INITIATED", {}, "STATIC_HOLD")
    assert abs(sum(p.probabilities.values()) - 1.0) < 1e-9


def test_enemy_swing_after_stability_is_hold():
    cfg = Config(hold_stability_ticks=4)
    window = ContactWindow(10, 14, None, None, 16, 1, 2)
    relations = [_relation(t, "EXPOSED", "COVERED", True, False) for t in range(10, 14)]
    relations += [_relation(t, "EXPOSED", "EXPOSED") for t in range(14, 17)]
    idx = _records([(10, 0, 0, 0), (11, 0, 0, 0), (12, 0, 0, 1),
                    (13, 0, 0, 1), (14, 0, 0, 1), (15, 0, 0, 1)])
    p = classify_contact(window, relations, idx, cfg)
    assert (p.initiation, p.top_label, p.subtype) == ("ENEMY_INITIATED", "HOLD", "STATIC_HOLD")


def test_small_ad_without_exposure_growth_is_microadjust_hold():
    cfg = Config(hold_stability_ticks=4, hold_max_displacement=20.0)
    window = ContactWindow(10, 14, None, None, 16, 1, 2)
    relations = [_relation(t, "EXPOSED", "COVERED", True, False) for t in range(10, 14)]
    relations += [_relation(t, "EXPOSED", "EXPOSED") for t in range(14, 17)]
    idx = _records([(10, 0, 20, 0), (11, 2, 20, 1), (12, 0, 20, -1),
                    (13, 2, 20, 1), (14, 0, 20, 0), (15, 2, 20, 1)])
    p = classify_contact(window, relations, idx, cfg)
    assert p.top_label == "HOLD" and p.subtype == "MICROADJUST_HOLD"


def test_self_covered_to_visible_lateral_move_is_peek():
    cfg = Config(hold_stability_ticks=4)
    window = ContactWindow(10, 14, None, None, 16, 1, 2)
    relations = [_relation(t, "COVERED", "EXPOSED", False, True) for t in range(10, 14)]
    relations += [_relation(t, "EXPOSED", "EXPOSED") for t in range(14, 17)]
    idx = _records([(10, 0, 0, 0), (11, 10, 200, 0), (12, 20, 200, 0),
                    (13, 30, 200, 0), (14, 40, 200, 0), (15, 42, 0, 0)])
    p = classify_contact(window, relations, idx, cfg)
    assert p.initiation == "SELF_INITIATED" and p.top_label == "PEEK"


def test_mutual_encounter_is_not_active_peek():
    cfg = Config()
    window = ContactWindow(10, 14, None, None, 16, 1, 2)
    relations = [_relation(t, "COVERED", "COVERED", False, False) for t in range(10, 14)]
    relations += [_relation(t, "EXPOSED", "EXPOSED") for t in range(14, 17)]
    idx = _records([(10, 0, 200, 0), (11, 10, 200, 0), (12, 20, 200, 0),
                    (13, 30, 200, 0), (14, 40, 200, 0), (15, 50, 200, 0)])
    p = classify_contact(window, relations, idx, cfg)
    assert p.initiation == "MUTUAL" and p.top_label != "PEEK"


def test_geometry_relations_use_los_not_fov_only():
    class Geometry:
        quality = "exact"
        def can_see(self, map_name, a, b): return False
    window = ContactWindow(10, None, None, None, 11, 1, 2)
    idx = {(1, 10): {"x": 0, "y": 0, "is_alive": True},
           (2, 10): {"x": 10, "y": 0, "is_alive": True}}
    rel = exposure_relations(window, "de_test", idx, Geometry(), Config())[0]
    assert rel.self_exposure_state == "COVERED" and rel.geometry_quality == "exact"
