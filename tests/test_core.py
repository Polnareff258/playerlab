"""PlayerLab core unit tests (no demo required, deterministic)."""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "core"))

from playerlab import buttons, weapons, zones, stats  # noqa: E402
from playerlab.config import Config  # noqa: E402
from playerlab.features import hard_match, soft_score, build_features  # noqa: E402
from playerlab.db import DB  # noqa: E402
from playerlab.counterfactual import what_if  # noqa: E402


def test_buttons_decode():
    flags = buttons.IN_FORWARD | buttons.IN_GRENADE2 | buttons.IN_MOVELEFT
    names = buttons.decode(flags)
    assert "forward" in names and "grenade2" in names and "moveleft" in names
    assert buttons.is_moving(buttons.IN_BACK)
    assert not buttons.is_moving(0)
    assert buttons.is_firing(buttons.IN_ATTACK2)


def test_weapons():
    assert weapons.name_from_def(7) == "ak47"
    assert weapons.weapon_class("ak47") == "rifle"
    assert weapons.weapon_class("awp") == "sniper"
    assert weapons.weapon_class("glock") == "pistol"
    assert weapons.weapon_class("flashbang") == "grenade"
    assert weapons.weapon_class("nonsense_weapon") == "unknown"
    assert "unknown" in weapons.name_from_def(999999)


def test_zones():
    assert zones.zone_for("de_dust2", "Catwalk") == "MID"
    assert zones.zone_for("de_dust2", "OutsideLong") == "LONG"
    assert zones.zone_for("de_dust2", "") == "other"
    # generic map falls back to raw place name
    assert zones.zone_for("de_mirage", "Mid") == "Mid"


def test_wilson():
    p, lo, hi = stats.wilson_ci(10, 10)
    assert abs(p - 1.0) < 1e-9 and hi <= 1.0 and lo <= hi
    p2, lo2, hi2 = stats.wilson_ci(0, 10)
    assert p2 == 0.0 and lo2 == 0.0


def test_calibration():
    bins = stats.calibration_bins([0.8, 0.8, 0.8, 0.2, 0.2, 0.2],
                                  [1, 1, 0, 0, 0, 1], n_bins=2)
    assert len(bins) == 2
    assert stats.brier([0.5, 0.5], [1, 0]) == 0.25


def test_features_build():
    cfg = Config()
    known = {"own": {"hp": 80, "money": 4000, "weapon_class": "rifle"},
             "n_known_enemies": 1, "known_spread": 100.0, "nearest_known_enemy": 500.0}
    public = {"time_remaining_s": 60.0, "bomb": {"planted_site": None}}
    f1, l1 = build_features(known, public, cfg, "de_dust2", "CT", "MID", "PEEK",
                            True, 1, 1, 4, 4)
    f2, l2 = build_features(known, public, cfg, "de_dust2", "CT", "MID", "PEEK",
                            True, 1, 1, 4, 4)
    assert f1 == f2 and l1 == l2  # determinism
    assert 0.0 <= f1["hp"] <= 1.0
    assert f1["bomb_planted"] == 0.0


def test_hard_and_soft():
    cfg = Config()
    q = {"map": "de_dust2", "side": "CT", "zone": "MID"}
    same = {"map": "de_dust2", "side": "CT", "zone": "MID"}
    other_map = {"map": "de_mirage", "side": "CT", "zone": "MID"}
    other_zone = {"map": "de_dust2", "side": "CT", "zone": "A"}
    assert hard_match(q, same, cfg)
    assert not hard_match(q, other_map, cfg)
    assert not hard_match(q, other_zone, cfg)

    f = {k: 0.5 for k in ("time_left", "alive_diff", "hp", "n_known_enemies",
                          "known_spread", "nearest_known_enemy", "recent_contact",
                          "teammate_near", "teammate_mid", "bomb_planted",
                          "economy", "time_pressure")}
    lq = {"weapon_class": "rifle"}
    assert soft_score(f, dict(f), lq, dict(lq), cfg) == 1.0
    f2 = dict(f); f2["hp"] = 0.0
    assert soft_score(f, f2, lq, lq, cfg) < 1.0
    assert soft_score(f, dict(f), lq, {"weapon_class": "smg"}, cfg) < 1.0


def _seed_db(cfg, actions=("PEEK", "HOLD"), per_action=11, query_match="m1",
             sample_match="m2"):
    """Seed per_action samples of each action in sample_match; the query DP
    lives in query_match (excluded from retrieval by leakage guard)."""
    db = DB(":memory:")
    db.upsert_match({"demo_id": "m1", "demo_path": "", "map_name": "de_dust2",
                     "tickrate": 64, "player_count": 10, "rounds_total": 3,
                     "side_swap_round": None, "parsed_at": "2026-01-01",
                     "parser_version": "test"})
    db.upsert_match({"demo_id": "m2", "demo_path": "", "map_name": "de_dust2",
                     "tickrate": 64, "player_count": 10, "rounds_total": 3,
                     "side_swap_round": None, "parsed_at": "2026-01-02",
                     "parser_version": "test"})
    f = {k: 0.5 for k in ("time_left", "alive_diff", "hp", "n_known_enemies",
                          "known_spread", "nearest_known_enemy", "recent_contact",
                          "teammate_near", "teammate_mid", "bomb_planted",
                          "economy", "time_pressure")}
    i = 0
    # query DP in query_match (observed action = first in `actions`)
    query_action = actions[0]
    db.insert_dp(
        {"dp_id": "query", "match_id": query_match, "round": 1, "steamid": 1,
         "player_name": "q", "start_tick": 0, "decision_tick": 100, "end_tick": 200,
         "observed_action": query_action, "alternatives": [], "zone": "MID",
         "place": "Middle", "confidence": 0.8, "significance": 0.5,
         "evidence": {}, "meta": {}},
        {"dp_id": "query", "match_id": query_match, "round": 1, "decision_tick": 100,
         "map": "de_dust2", "side": "CT", "zone": "MID",
         "observed_action": query_action, "features": f, "labels": {
             "map": "de_dust2", "side": "CT", "zone": "MID",
             "weapon_class": "rifle", "action": query_action},
         "known_state": {}, "public_info": {}, "ground_truth": {}},
        {"dp_id": "query", "survival": 1, "survival_window_ticks": 640,
         "death_tick": None, "duel_result": "undefined",
         "duel_opponent": "2", "round_win": 1})
    for action in actions:
        for j in range(per_action):
            dp_id = f"dp_{action}_{j}"
            db.insert_dp(
                {"dp_id": dp_id, "match_id": sample_match, "round": 1, "steamid": 2,
                 "player_name": "s", "start_tick": 0, "decision_tick": 200 + i,
                 "end_tick": 300, "observed_action": action, "alternatives": [],
                 "zone": "MID", "place": "Middle", "confidence": 0.8,
                 "significance": 0.5, "evidence": {}, "meta": {}},
                {"dp_id": dp_id, "match_id": sample_match, "round": 1,
                 "decision_tick": 200 + i, "map": "de_dust2", "side": "CT",
                 "zone": "MID", "observed_action": action, "features": f,
                 "labels": {"map": "de_dust2", "side": "CT", "zone": "MID",
                            "weapon_class": "rifle", "action": action},
                 "known_state": {}, "public_info": {}, "ground_truth": {}},
                {"dp_id": dp_id, "survival": 0 if j % 3 == 0 else 1,
                 "survival_window_ticks": 640, "death_tick": None,
                 "duel_result": "undefined", "duel_opponent": "2", "round_win": 1})
            i += 1
    db.rebuild_coverage()
    return db


def test_counterfactual_insufficient():
    cfg = Config()
    db = _seed_db(cfg, actions=("PEEK",), per_action=2)  # only 2 candidates
    res = what_if(db, cfg, "query")
    assert res["verdict"] == "INSUFFICIENT_EVIDENCE"


def test_counterfactual_ok():
    cfg = Config()
    db = _seed_db(cfg, actions=("PEEK", "HOLD"), per_action=11)
    res = what_if(db, cfg, "query")
    assert res["verdict"] == "COMPARISON_AVAILABLE"
    assert "PEEK" in res["actions"] and "HOLD" in res["actions"]
    assert res["actions"]["PEEK"]["n"] >= cfg.n_min_action
    assert res["evidence_strength"]["n_similar_states"] >= 10
    assert len(res["comparisons"]) == 1  # PEEK vs HOLD


def test_counterfactual_no_alternative():
    cfg = Config()
    db = _seed_db(cfg, actions=("PEEK",), per_action=11)
    res = what_if(db, cfg, "query")
    assert res["verdict"] == "NO_COMPARABLE_ALTERNATIVE"
    assert res["actions"]["PEEK"]["n"] >= cfg.n_min_action


# ---------------- batch module tests ----------------

def _make_demo_dir():
    import time as _time
    tmp_root = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".tmp_batch")
    os.makedirs(tmp_root, exist_ok=True)
    d = os.path.join(tmp_root, "batch_%d" % _time.time_ns())
    os.makedirs(d)  # NOTE: use os.makedirs, not tempfile.mkdtemp (sandbox)
    for name in ("a.dem", "b.dem"):
        with open(os.path.join(d, name), "w", encoding="utf-8") as fh:
            fh.write("not a real demo - parse must fail fast")
    sub = os.path.join(d, "nested")
    os.makedirs(sub)
    with open(os.path.join(sub, "c.dem"), "w", encoding="utf-8") as fh:
        fh.write("not a real demo")
    with open(os.path.join(d, "notes.txt"), "w", encoding="utf-8") as fh:
        fh.write("ignore me")
    return d


def test_batch_discover():
    from playerlab.batch import discover
    d = _make_demo_dir()
    rec = discover([d], recursive=True)
    assert len(rec) == 3 and all(f.endswith(".dem") for f in rec)
    flat = discover([d], recursive=False)
    assert len(flat) == 2  # nested excluded
    single = discover([os.path.join(d, "a.dem")])
    assert single == [os.path.join(d, "a.dem")]


def test_batch_dry_run_and_failure_tolerance():
    from playerlab.batch import run_batch, summarize
    d = _make_demo_dir()
    cfg = Config()
    cfg.data_dir = os.path.join(d, "data")
    res = run_batch(cfg, [d], dry_run=True, verbose=False)
    assert {r["status"] for r in res} == {"would_ingest"}
    res2 = run_batch(cfg, [d], verbose=False)
    assert len(res2) == 3
    assert all(r["status"] == "failed" for r in res2)
    assert all("error" in r for r in res2)
    rep = summarize(res2)
    assert rep["failed"] == 3 and rep["total"] == 3


def test_batch_skip_existing():
    from playerlab.batch import run_batch
    from playerlab.ingest import demo_id_for
    from playerlab.db import DB
    d = _make_demo_dir()
    cfg = Config()
    cfg.data_dir = os.path.join(d, "data")
    db = DB(cfg.db_path)
    demo = os.path.join(d, "a.dem")
    demo_id = demo_id_for(demo)
    db.upsert_match({"demo_id": demo_id, "demo_path": demo, "map_name": "de_dust2",
                     "tickrate": 64, "player_count": 10, "rounds_total": 3,
                     "side_swap_round": None, "parsed_at": "2026-01-01",
                     "parser_version": "test"})
    res = run_batch(cfg, [demo], skip_existing=True, verbose=False)
    assert res[0]["status"] == "skipped" and res[0]["reason"] == "already_ingested"
    res2 = run_batch(cfg, [demo], force=True, verbose=False)
    assert res2[0]["status"] == "failed"  # bogus file, but force bypassed the skip


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
    print(f"\n{sum(1 for n in globals() if n.startswith('test_')) - failed}/{sum(1 for n in globals() if n.startswith('test_'))} passed")
    sys.exit(1 if failed else 0)
