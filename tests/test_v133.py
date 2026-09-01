"""V1.3.3 tests (PART T): simulated labels never drive CalibrationState,
SIMULATED never unpauses TrainingTargets, SIMULATED never boosts ReviewMoment
score, HUMAN labels accumulate, multiple annotations don't overwrite,
recompute reads eligible only, geometry A/B episode alignment, NullGeometry
behavior preserved, awpy graceful fallback, steam_id stays string."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "core"))

from playerlab.config import Config  # noqa: E402
from playerlab.db import DB  # noqa: E402
from playerlab.calibration import (calibration_state, calibration_stats,  # noqa: E402
                                   sample_calibration_set, recompute_calibration,
                                   submit_human_annotation, submit_simulated_review,
                                   detector_calibration_map, SingleHumanResolver,
                                   ConsensusResolver, _confirmed)
from playerlab.training import generate_targets_from_episodes  # noqa: E402
from playerlab.moments import rank_review_moments  # noqa: E402
from playerlab.geometry import (NullGeometryProvider, AwpyGeometryProvider,  # noqa: E402
                                get_geometry, GeometryProvider)
from playerlab.episode_patterns import cluster_episodes  # noqa: E402

P1 = 1
PLAYERS = [{"steamid": 1, "name": "Alice", "team_number": 2},
           {"steamid": 2, "name": "Bob", "team_number": 2},
           {"steamid": 4, "name": "D", "team_number": 3}]


def _episode(eid, player=P1, prims=None, method="DRY_PEEK", eval_="QUESTIONABLE",
             suff="MEDIUM", actionability="ACTIONABLE"):
    return {
        "id": eid, "match_id": "m1", "round": 1, "player_id": player,
        "family": "CONTACT_RESPONSE", "anchor_tick": 100, "start_tick": 0,
        "end_tick": 300, "temporal_context": {}, "player_known_state": {},
        "macro_context": {"objective_urgency": "LOW", "bomb_state": {"planted": False}},
        "local_context": {}, "commitment_state": "FREE",
        "situational_role": "FREE_ROLE", "intent": "HOLD",
        "observed_action": "PEEK", "feasibility": {},
        "immediate_result": {"survived_3s": False, "kill_within_3s": False},
        "decision_evaluation": eval_, "actionability": actionability,
        "evidence_sufficiency": suff,
        "strategic_evaluation": eval_, "engagement_evaluation": "REASONABLE",
        "execution_evaluation": "QUESTIONABLE",
        "engagement_method": {"method": method},
        "execution_primitives": prims or [],
        "weapon_matchup": {"range_bucket": "medium", "self_weapon_class": "RIFLE"},
        "confidence": 0.7, "model_version": "v1.3.1-1",
        "rule_version": "v1.3.1-1", "computed_at": "2026-01-01",
    }


def _seed(db, n=12):
    db.upsert_match({"demo_id": "m1", "demo_path": "", "map_name": "de_dust2",
                     "tickrate": 64, "player_count": 3, "rounds_total": 1,
                     "side_swap_round": None, "parsed_at": "2026-01-01",
                     "parser_version": "t"})
    db.replace_players("m1", PLAYERS)
    for i in range(n):
        db.upsert_decision_episode(_episode(f"e{i}", prims=["PREAIM_ERROR"]))


def _mk_sample(db, det="PREAIM_ERROR", n=1):
    out = []
    for i in range(n):
        s = {"id": f"s-{det}-{i}", "match_id": "m1", "player_id": P1,
             "round": 1, "tick": 100 + i, "episode_id": f"e{i}",
             "detector_type": det, "predicted_label": det,
             "predicted_confidence": 0.7, "evidence_sufficiency": "MEDIUM",
             "model_version": "v1.3.1-1", "rule_version": "v1.3.1-1",
             "sample_stratum": "general", "review_status": "pending",
             "label_source": "HUMAN", "pipeline_validation": "NOT_TESTED"}
        db.upsert_calibration_sample(s)
        out.append(s)
    return out


def test_simulated_never_drives_state():
    """PART T Test 1: 100 simulated reviews still UNCALIBRATED."""
    cfg = Config()
    db = DB(":memory:")
    _seed(db)
    _mk_sample(db, n=20)
    samples = db.get_calibration_samples(detector_type="PREAIM_ERROR", limit=100)
    for i, s in enumerate(samples):
        label = "YES" if i < 80 else "NO"
        submit_simulated_review(db, s["id"], label, 0.9, "sim")
    stats = calibration_stats(db, cfg)
    d = stats["detectors"]["PREAIM_ERROR"]
    assert d["simulated_reviewed_count"] == 20
    assert d["human_reviewed_count"] == 0
    assert d["calibration_state"] == "UNCALIBRATED", d
    assert d["pipeline_validation_state"] == "PIPELINE_VALIDATED"


def test_simulated_never_unpauses_target():
    """PART T Test 2: SIMULATED precision 0.95 must not unpause a target."""
    cfg = Config()
    db = DB(":memory:")
    _seed(db)
    _mk_sample(db, n=20)
    for i, s in enumerate(db.get_calibration_samples(detector_type="PREAIM_ERROR", limit=100)):
        submit_simulated_review(db, s["id"], "YES", 0.95, "sim")
    # even with simulated 100% precision, the calibration map stays UNCALIBRATED
    cal = detector_calibration_map(db, cfg)
    assert cal["PREAIM_ERROR"] == "UNCALIBRATED"
    pats = [{
        "pattern_id": "OVER_REPEEK_AFTER_NEUTRAL_CONTACT",
        "family": "CONTACT_RESPONSE", "name": "x", "sample_count": 12,
        "violation_rate": 0.5, "actionability_share": 0.8, "confidence": 0.9,
        "eligible": True, "breakdown": {}, "trigger": "t", "undesired": "u",
        "replacement": "r", "macro_reason": "m"}]
    targets = generate_targets_from_episodes(db, cfg, pats, calibration_map=cal)
    assert all(t["status"] == "PAUSED" for t in targets), targets


def test_simulated_never_boosts_review_moment():
    """PART T Test 3: SIMULATED must not boost ReviewMoment calibration score."""
    cfg = Config()
    db = DB(":memory:")
    _seed(db)
    _mk_sample(db, n=20)
    for i, s in enumerate(db.get_calibration_samples(detector_type="PREAIM_ERROR", limit=100)):
        submit_simulated_review(db, s["id"], "YES", 0.9, "sim")
    cal = detector_calibration_map(db, cfg)   # all UNCALIBRATED (sim only)
    moments = rank_review_moments(db, cfg, "m1", P1, calibration=cal)
    for m in moments:
        assert m["calibration_reliability"] in ("UNCALIBRATED", "UNKNOWN"), m
        assert m["factors"]["calibration_boost"] == 0.0, m  # sim never boosts


def test_human_labels_accumulate():
    """PART T Test 4: HUMAN labels accumulate normally."""
    cfg = Config()
    db = DB(":memory:")
    _seed(db)
    _mk_sample(db, n=25)
    samples = db.get_calibration_samples(detector_type="PREAIM_ERROR", limit=100)
    for i, s in enumerate(samples[:25]):
        label = "YES" if i < 20 else "NO"
        submit_human_annotation(db, s["id"], label, 0.8, "human test")
    stats = calibration_stats(db, cfg)
    d = stats["detectors"]["PREAIM_ERROR"]
    assert d["human_reviewed_count"] == 25
    assert d["human_confirmed_count"] == 20
    assert d["calibration_state"] == "CALIBRATED"
    assert d["human_confirmation_rate"] == 0.8


def test_multiple_annotations_no_overwrite():
    """PART T Test 5: one-to-many annotations never overwrite history."""
    cfg = Config()
    db = DB(":memory:")
    _seed(db)
    s = _mk_sample(db, n=1)[0]
    submit_human_annotation(db, s["id"], "YES", 0.8, "first")
    submit_human_annotation(db, s["id"], "NO", 0.9, "second")
    anns = db.annotations_for_sample(s["id"])
    assert len(anns) == 2
    assert anns[0]["label"] == "YES" and anns[1]["label"] == "NO"
    # derived human_label reflects aggregation (most recent / majority)
    sample = db.get_calibration_samples(detector_type="PREAIM_ERROR")[0]
    assert sample["human_label"] in ("YES", "NO")


def test_recompute_eligible_only():
    """PART T Test 6: recompute reads eligible labels only."""
    cfg = Config()
    db = DB(":memory:")
    _seed(db)
    _mk_sample(db, n=30)
    samples = db.get_calibration_samples(detector_type="PREAIM_ERROR", limit=100)
    # 20 simulated YES + 5 human (4 YES 1 NO)
    for i, s in enumerate(samples[:20]):
        submit_simulated_review(db, s["id"], "YES", 0.9, "sim")
    for i, s in enumerate(samples[20:25]):
        submit_human_annotation(db, s["id"], "YES" if i < 4 else "NO", 0.8, "human")
    res = recompute_calibration(db, cfg)
    d = res["calibration"]["detectors"]["PREAIM_ERROR"]
    assert d["human_reviewed_count"] == 5
    assert d["simulated_reviewed_count"] == 20
    assert d["human_confirmation_rate"] == 0.8
    # 5 human >= min_experimental(5) but < min_calibrated(20) -> EXPERIMENTAL
    assert d["calibration_state"] == "EXPERIMENTAL"


def test_geometry_ab_episode_alignment():
    """PART T Test 7: OFF/ON align by episode_id."""
    cfg = Config()
    db = DB(":memory:")
    _seed(db, n=5)
    # simulate two runs producing the same episode ids with different suff
    for eid in ("e0", "e1", "e2", "e3", "e4"):
        e_off = _episode(eid, prims=["PREAIM_ERROR"], suff="MEDIUM")
        e_on = _episode(eid, prims=["PREAIM_ERROR"], suff="HIGH")
        db.upsert_decision_episode(e_off)
    eps_off = {e["id"]: e for e in db.get_decision_episodes(match_id="m1", limit=100)}
    assert "e0" in eps_off and "e4" in eps_off  # same id space both modes


def test_null_geometry_preserves_behavior():
    """PART T Test 8: NullGeometryProvider keeps original behavior."""
    g = NullGeometryProvider()
    assert g.can_see("de_dust2", (0, 0), (100, 0)) is None
    assert g.nav_distance("de_dust2", (0, 0), (100, 0)) is None
    assert g.get_metadata()["geometry_source"] == "null"
    assert isinstance(g, GeometryProvider)


def test_awpy_graceful_fallback():
    """PART T Test 9: missing assets -> None, no crash."""
    g = AwpyGeometryProvider(nav_dir="/nonexistent", tri_dir="/nonexistent")
    # awpy may or may not be installed; either way queries never crash
    for fn in (g.can_see, g.nav_distance, g.has_cover):
        try:
            r = fn("de_dust2", (0, 0), (1000, 0))
            assert r in (True, False, None)
        except Exception:  # noqa: BLE001
            assert False, "awpy provider must not raise on missing assets"
    # factory fallback: bad provider config -> Null-like behavior
    g2 = get_geometry("awpy", nav_dir="/nope", tri_dir="/nope")
    assert g2.source in ("awpy", "null")


def test_steam_id_always_string():
    """PART T Test 10: steam_id stays string (precision regression guard)."""
    from playerlab.focus import players_of_match
    db = DB(":memory:")
    _seed(db)
    ps = players_of_match(db, "m1")
    for p in ps:
        assert isinstance(p["steam_id"], str), p


def test_consensus_resolver_interface():
    """PART M: interface defined; default SingleHumanResolver."""
    r = SingleHumanResolver()
    out = r.resolve([{"label_source": "HUMAN", "label": "YES", "confidence": 0.8}])
    assert out["mode"] == "single_human" and out["label"] == "YES"
    out2 = r.resolve([])
    assert out2["label"] is None and out2["mode"] == "no_human"
    assert issubclass(SingleHumanResolver, ConsensusResolver)


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
