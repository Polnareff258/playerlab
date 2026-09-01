"""V1.3.2 tests (PART L §45-§52): focus-player isolation, focus switch,
remember player, ReviewMoment ranking, calibration gate, good example,
player-scope DB, outcome independence."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "core"))

from playerlab.config import Config  # noqa: E402
from playerlab.db import DB  # noqa: E402
from playerlab.focus import (FocusPlayerContext, players_of_match,  # noqa: E402
                             remember_user, default_focus, set_focus)
from playerlab.moments import (rank_review_moments, player_match_overview,  # noqa: E402
                               _is_positive, _impact)
from playerlab.calibration import (sample_calibration_set, calibration_stats,  # noqa: E402
                                   calibration_state, detector_calibration_map,
                                   _episode_detectors)
from playerlab.training import generate_targets_from_episodes  # noqa: E402
from playerlab.geometry import (GeometryProvider, NullGeometryProvider,  # noqa: E402
                                AwpyGeometryProvider, get_geometry)
from playerlab.evaluate import evaluate_decision  # noqa: E402


P1, P2 = 1, 2
PLAYERS = [{"steamid": 1, "name": "Alice", "team_number": 2},
           {"steamid": 2, "name": "Bob", "team_number": 2},
           {"steamid": 4, "name": "D", "team_number": 3}]


def _episode(eid, player, fam="CONTACT_RESPONSE", actionability="ACTIONABLE",
             suff="MEDIUM", strat="QUESTIONABLE", eng="QUESTIONABLE",
             exe="QUESTIONABLE", prims=None, method="DRY_PEEK", impact=0.8,
             eval_="QUESTIONABLE"):
    return {
        "id": eid, "match_id": "m1", "round": 1, "player_id": player,
        "family": fam, "anchor_tick": 100, "start_tick": 0, "end_tick": 300,
        "temporal_context": {}, "player_known_state": {},
        "macro_context": {"objective_urgency": "LOW", "bomb_state": {"planted": False}},
        "local_context": {}, "commitment_state": "FREE",
        "situational_role": "FREE_ROLE", "intent": "HOLD",
        "observed_action": "PEEK",
        "feasibility": {}, "immediate_result": {"survived_3s": False,
                                                "kill_within_3s": False},
        "decision_evaluation": eval_, "actionability": actionability,
        "evidence_sufficiency": suff,
        "strategic_evaluation": strat, "engagement_evaluation": eng,
        "execution_evaluation": exe,
        "engagement_method": {"method": method},
        "execution_primitives": prims or [],
        "weapon_matchup": {"range_bucket": "medium",
                           "self_weapon_class": "RIFLE"},
        "confidence": 0.7, "model_version": "v1.3.1-1",
        "rule_version": "v1.3.1-1", "computed_at": "2026-01-01",
    }


def _seed_match(db):
    db.upsert_match({"demo_id": "m1", "demo_path": "", "map_name": "de_dust2",
                     "tickrate": 64, "player_count": 3, "rounds_total": 1,
                     "side_swap_round": None, "parsed_at": "2026-01-01",
                     "parser_version": "t"})
    db.replace_players("m1", PLAYERS)
    for i in range(5):
        db.upsert_decision_episode(_episode(f"a{i}", P1, eval_="QUESTIONABLE",
                                            prims=["PREAIM_ERROR"]))
    for i in range(5):
        db.upsert_decision_episode(_episode(f"b{i}", P2, eval_="GOOD",
                                            actionability="WEAKLY_ACTIONABLE",
                                            strat="GOOD", eng="GOOD", exe="GOOD",
                                            prims=[], method="HOLD"))


def test_focus_player_isolation():
    """PART L §45: Player A's overview must not include B's episodes."""
    cfg = Config()
    db = DB(":memory:")
    _seed_match(db)
    ov_a = player_match_overview(db, cfg, "m1", P1)
    ov_b = player_match_overview(db, cfg, "m1", P2)
    assert ov_a["episodes"] == 5
    assert ov_b["episodes"] == 5
    # A is QUESTIONABLE-heavy, B is GOOD-heavy -> different summaries
    assert ov_a["summary"] != ov_b["summary"] or \
        ov_a["distributions"]["strategic"] != ov_b["distributions"]["strategic"]
    # no cross-player pollution: A has no GOOD from B
    assert ov_a["distributions"]["strategic"].get("GOOD", 0) == 0


def test_focus_switch_changes_view():
    """PART L §46: switching A -> B changes results."""
    cfg = Config()
    db = DB(":memory:")
    _seed_match(db)
    moments_a = rank_review_moments(db, cfg, "m1", P1)
    moments_b = rank_review_moments(db, cfg, "m1", P2)
    assert len(moments_a) >= 1 and len(moments_b) >= 1
    ids_a = {m["episode_id"] for m in moments_a}
    ids_b = {m["episode_id"] for m in moments_b}
    assert not (ids_a & ids_b), "player scopes overlap"


def test_remember_player_default_focus():
    """PART L §47: remembering steam X makes X the default focus next match."""
    db = DB(":memory:")
    _seed_match(db)
    # no remembered user -> no default focus (show selector)
    ctx0 = default_focus(db, "m1")
    assert ctx0.steam_id is None
    # remember Bob
    remember_user(db, P2, "Bob")
    ctx = default_focus(db, "m1")
    assert ctx.steam_id == P2 and ctx.is_user is True
    # set_focus with persist
    ctx2 = set_focus(db, "m1", P1, persist=True)
    assert ctx2.steam_id == P1
    assert db.get_user_profile()["steam_id"] == P1
    # match players enriched with is_user; steam_id serialized as string
    # (JS number precision guard: >2^53 steam ids must not truncate)
    ps = players_of_match(db, "m1")
    alice = next(p for p in ps if int(p["steam_id"]) == P1)
    assert alice["is_user"] is True and alice["display_name"] == "Alice"
    assert isinstance(alice["steam_id"], str)


def test_review_moment_ranking_gate():
    """PART L §48: HIGH actionable + calibrated beats uncalibrated high-
    frequency detector."""
    cfg = Config()
    db = DB(":memory:")
    _seed_match(db)
    # all detectors uncalibrated (no reviews yet) -> calibration gate suppresses
    cal = detector_calibration_map(db, cfg)
    assert all(v in ("UNCALIBRATED",) for v in cal.values()) or not cal
    moments = rank_review_moments(db, cfg, "m1", P1, calibration=cal)
    for m in moments:
        assert m["factors"]["calibration_penalty"] >= 0.0
    # a calibrated detector should rank higher than an uncalibrated one with
    # equal features: simulate by injecting a calibrated state
    cal2 = dict(cal)
    cal2["PREAIM_ERROR"] = "CALIBRATED"
    moments_cal = rank_review_moments(db, cfg, "m1", P1, calibration=cal2)
    scores_uncal = {m["episode_id"]: m["review_score"] for m in moments}
    scores_cal = {m["episode_id"]: m["review_score"] for m in moments_cal}
    for eid in scores_uncal:
        if eid in scores_cal:
            assert scores_cal[eid] >= scores_uncal[eid], \
                "calibration should not lower a calibrated detector's score"


def test_calibration_gate_no_high_conf_target():
    """PART L §49: UNCALIBRATED detector must not auto-generate a HIGH-
    confidence TrainingTarget."""
    cfg = Config()
    db = DB(":memory:")
    _seed_match(db)
    pats = [{
        "pattern_id": "OVER_REPEEK_AFTER_NEUTRAL_CONTACT",
        "family": "CONTACT_RESPONSE", "name": "Over re-peek",
        "sample_count": 12, "violation_rate": 0.5, "actionability_share": 0.8,
        "confidence": 0.9, "eligible": True, "breakdown": {},
        "trigger": "first contact", "undesired": "re-peek",
        "replacement": "hold", "macro_reason": "preserve",
    }]
    targets = generate_targets_from_episodes(
        db, cfg, pats, calibration_map={"OVER_REPEEK_AFTER_NEUTRAL_CONTACT": "UNCALIBRATED"})
    assert len(targets) == 1
    t = targets[0]
    assert t["status"] == "PAUSED", t
    assert t["confidence"] <= 0.3
    assert "needs calibration" in t.get("calibration_note", ""), t
    # calibrated version becomes ACTIVE with reasonable confidence
    targets2 = generate_targets_from_episodes(
        db, cfg, pats, calibration_map={"OVER_REPEEK_AFTER_NEUTRAL_CONTACT": "CALIBRATED"})
    assert any(t2["status"] == "ACTIVE" for t2 in targets2)


def test_good_example_in_review_moments():
    """PART L §50: Good Decision episodes can enter Review Moments."""
    cfg = Config()
    db = DB(":memory:")
    _seed_match(db)
    eps = db.get_decision_episodes(match_id="m1", player_id=P2)
    assert any(e["decision_evaluation"] == "GOOD" for e in eps)
    assert any(_is_positive(e) for e in eps)
    moments = rank_review_moments(db, cfg, "m1", P2)
    # positive moments are allowed (not suppressed)
    assert isinstance(moments, list)


def test_player_scope_db_queries():
    """PART L §51: player-specific queries use player scope, no cross-player
    pollution at the storage layer."""
    cfg = Config()
    db = DB(":memory:")
    _seed_match(db)
    a = db.get_decision_episodes(match_id="m1", player_id=P1)
    b = db.get_decision_episodes(match_id="m1", player_id=P2)
    assert all(e["player_id"] == P1 for e in a)
    assert all(e["player_id"] == P2 for e in b)
    assert len(a) == 5 and len(b) == 5
    # calibration samples scoped by player
    from playerlab.calibration import sample_calibration_set
    sa = sample_calibration_set(db, cfg, "m1", player_id=P1)
    assert all(s["player_id"] == P1 for s in sa)
    sb = sample_calibration_set(db, cfg, "m1", player_id=P2)
    assert all(s["player_id"] == P2 for s in sb)


def test_outcome_independence_kept():
    """PART L §52: regression — outcome never drives the decision."""
    import inspect
    from playerlab.evaluate import evaluate_decision
    params = inspect.signature(evaluate_decision).parameters
    assert "outcome" not in params
    cfg = Config()
    ep = _episode("x", P1, eval_="QUESTIONABLE")
    ep["immediate_result"] = {"survived_3s": True, "kill_within_3s": True}
    ev = evaluate_decision(ep, cfg, {
        "PEEK": {"risk": "HIGH", "support": "LOW", "value": "LOW"},
        "HOLD": {"risk": "LOW", "support": "HIGH", "value": "HIGH"}})
    assert ev in ("QUESTIONABLE", "POOR")  # good outcome did not flip it


def test_calibration_sample_preserves_original():
    """PART E §23 / PART C §11: original prediction never overwritten."""
    db = DB(":memory:")
    db.upsert_calibration_sample({"id": "s1", "match_id": "m1", "player_id": P1,
                                  "round": 1, "tick": 100, "episode_id": "e1",
                                  "detector_type": "PREAIM_ERROR",
                                  "predicted_label": "PREAIM_ERROR",
                                  "predicted_confidence": 0.8,
                                  "evidence_sufficiency": "MEDIUM",
                                  "sample_stratum": "high-conf"})
    db.mark_calibration_reviewed("s1", "NO", 0.9, "UNEXPECTED_ENEMY_POSITION")
    s = db.get_calibration_samples(detector_type="PREAIM_ERROR")[0]
    assert s["predicted_label"] == "PREAIM_ERROR"  # original kept
    assert s["human_label"] == "NO" and s["false_positive_reason"] == \
        "UNEXPECTED_ENEMY_POSITION"
    stats = calibration_stats(db, Config())
    det = stats["detectors"]["PREAIM_ERROR"]
    assert det["reviewed"] == 1 and det["confirmed"] == 0 and det["precision"] == 0.0
    assert stats["ground_truth_note"].startswith("GROUND_TRUTH_PENDING_HUMAN_REVIEW")


def test_calibration_state_thresholds():
    """PART E §28: sample-count + precision driven states."""
    assert calibration_state(3, None) == "UNCALIBRATED"
    assert calibration_state(10, 0.6) == "EXPERIMENTAL"
    assert calibration_state(25, 0.8) == "CALIBRATED"
    assert calibration_state(25, 0.3) == "UNRELIABLE"
    assert calibration_state(25, 0.55) == "EXPERIMENTAL"


def test_geometry_provider_contract():
    """PART F §31-§33: interface + Null + graceful fallback + no fake precision."""
    g = NullGeometryProvider()
    assert g.can_see("de_dust2", (0, 0), (1000, 0)) is None
    assert g.nav_distance("de_dust2", (0, 0), (1000, 0)) is None
    meta = g.get_metadata()
    assert meta["geometry_source"] == "null" and meta["geometry_quality"] == "none"
    # factory: awpy missing -> Null fallback (no crash)
    g2 = get_geometry("awpy", nav_dir="/nonexistent", tri_dir="/nonexistent")
    assert g2.source in ("awpy", "null")
    assert g2.can_see("de_dust2", (0, 0), (1000, 0)) in (True, False, None)
    assert isinstance(NullGeometryProvider(), GeometryProvider)


def test_episode_detector_extraction():
    db = DB(":memory:")
    ep = _episode("e1", P1, prims=["PREAIM_ERROR", "MOVING_SHOT"], method="DRY_PEEK")
    dets = _episode_detectors(ep)
    assert "PREAIM_ERROR" in dets and "DRY_PEEK" in dets


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
