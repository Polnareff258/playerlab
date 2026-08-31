"""V1.1-alpha tests: pattern detectors, training loop, annotation loop,
review queue (spec §42). Synthetic fixtures, no real demos required."""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "core"))

from playerlab.config import Config  # noqa: E402
from playerlab.db import DB  # noqa: E402
from playerlab.execution import compute_shot_metrics  # noqa: E402
from playerlab.patterns import detect_repeek, detect_move_shoot, detect_advantage  # noqa: E402
from playerlab.bottleneck import rank_bottlenecks  # noqa: E402
from playerlab.training import generate_targets, validate_targets, active_focus  # noqa: E402
from playerlab.annotation import (submit_annotation, submit_preference,  # noqa: E402
                                  annotation_stats, build_review_queue, REASON_CODES)
from playerlab.stats import wilson_ci  # noqa: E402


class FakeDemo:
    def __init__(self, players, events, rounds, demo_id="t1"):
        self.demo_id = demo_id
        self.players = players
        self.events = events
        self.rounds = rounds
        self.header = {"map_name": "de_dust2"}
        self._team = {p["steamid"]: p["team_number"] for p in players}

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


P1, P2, P3, P4, P5 = 1, 2, 3, 4, 5  # P1-P3 team2(T), P4-P5 team3(CT)
PLAYERS = [{"steamid": P1, "name": "A", "team_number": 2},
           {"steamid": P2, "name": "B", "team_number": 2},
           {"steamid": P3, "name": "C", "team_number": 2},
           {"steamid": P4, "name": "D", "team_number": 3},
           {"steamid": P5, "name": "E", "team_number": 3}]
ROUNDS = [{"round": 1, "start_tick": 0, "end_tick": 5000, "winner": "CT", "reason": "x"}]


def rec(x, y, alive=True, vx=0.0, vy=0.0, yaw=0.0, health=100, weapon_def=7, money=3000):
    return {"x": x, "y": y, "vx": vx, "vy": vy, "vz": 0.0, "speed": (vx ** 2 + vy ** 2) ** 0.5,
            "is_alive": alive, "yaw": yaw, "health": health, "weapon_def": weapon_def,
            "money": money, "buttons": 0, "place": "Middle", "team_num": 2}


def seed_db(players=PLAYERS):
    db = DB(":memory:")
    db.upsert_match({"demo_id": "t1", "demo_path": "", "map_name": "de_dust2",
                     "tickrate": 64, "player_count": len(players), "rounds_total": 1,
                     "side_swap_round": None, "parsed_at": "2026-01-01", "parser_version": "t"})
    db.replace_players("t1", players)
    return db


def seed_dp(db, dp_id="d1", action="RE_PEEK", tick=150, tc0=100, conf=0.8,
            survival=0, duel="lost"):
    db.insert_dp(
        {"dp_id": dp_id, "match_id": "t1", "round": 1, "steamid": P1, "player_name": "A",
         "start_tick": 60, "decision_tick": tick, "end_tick": 250,
         "observed_action": action, "alternatives": [], "zone": "MID", "place": "Middle",
         "confidence": conf, "significance": 1.0, "evidence": {}, "meta": {
             "episode": {"tc0": tc0, "tc1": tc0 + 20, "n_events": 3}, "opponent": P4}},
        {"dp_id": dp_id, "match_id": "t1", "round": 1, "decision_tick": tick,
         "map": "de_dust2", "side": "T", "zone": "MID", "observed_action": action,
         "features": {}, "labels": {}, "known_state": {"n_known_enemies": 0, "teammate_near": 0},
         "public_info": {}, "ground_truth": {}},
        {"dp_id": dp_id, "survival": survival, "survival_window_ticks": 640,
         "death_tick": tick + 100 if survival == 0 else None,
         "duel_result": duel, "duel_opponent": str(P4), "round_win": 0})


def idx_at(entries):
    """entries: {(steamid, tick): rec_dict}; just normalize to dict."""
    return dict(entries)


# ---------------------------------------------------------------- re-peek
def test_repeek_poor():
    cfg = Config()
    db = seed_db()
    seed_dp(db, survival=0)
    demo = FakeDemo(PLAYERS, {"damages": [{"tick": 100, "user_steamid": P1,
                                           "attacker_steamid": P4, "dmg_health": 25}],
                              "kills": [], "shots": [], "bombs": {"planted": [], "defused": []},
                              "grenades": {}}, ROUNDS)
    idx = idx_at({(P1, 100): rec(0, 0), (P1, 150): rec(0, 0, vx=0),
                  (P4, 100): rec(100, 0)})
    samples = detect_repeek(demo, cfg, db, idx, {"support": "AGAINST"})
    assert len(samples) == 1
    s = samples[0]
    assert s["evaluation"] == "POOR"          # took damage, no support, no info, moving?
    assert s["first_contact_tick"] == 100
    assert s["time_delta_ticks"] == 50


def test_repeek_reasonable():
    cfg = Config()
    db = seed_db()
    seed_dp(db, survival=1, duel="won")
    demo = FakeDemo(PLAYERS, {"damages": [{"tick": 100, "user_steamid": P4,
                                           "attacker_steamid": P1, "dmg_health": 40}],
                              "kills": [], "shots": [], "bombs": {"planted": [], "defused": []},
                              "grenades": {}}, ROUNDS)
    idx = idx_at({(P1, 100): rec(0, 0), (P1, 150): rec(0, 0)})
    samples = detect_repeek(demo, cfg, db, idx, {"support": "FOR"})
    assert samples[0]["evaluation"] == "REASONABLE"


def test_repeek_insufficient():
    cfg = Config()
    db = seed_db()
    seed_dp(db, survival=0)
    demo = FakeDemo(PLAYERS, {"damages": [], "kills": [], "shots": [],
                              "bombs": {"planted": [], "defused": []}, "grenades": {}}, ROUNDS)
    idx = idx_at({(P1, 150): rec(0, 0)})  # missing first-contact tick rec -> no yaw
    samples = detect_repeek(demo, cfg, db, idx, {"support": "INSUFFICIENT"})
    assert samples[0]["evaluation"] == "INSUFFICIENT_EVIDENCE"


# ---------------------------------------------------------------- move-shoot
def test_move_shoot():
    cfg = Config()
    db = seed_db()
    demo = FakeDemo(PLAYERS, {"shots": [
        {"tick": 100, "user_steamid": P1, "weapon": "weapon_ak47"},
        {"tick": 200, "user_steamid": P1, "weapon": "weapon_ak47"},
        {"tick": 300, "user_steamid": P1, "weapon": "weapon_knife"},
    ], "damages": [], "kills": [], "bombs": {"planted": [], "defused": []},
        "grenades": {}}, ROUNDS)
    idx = idx_at({(P1, 100): rec(0, 0, vx=200),          # moving shot -> violation
                  (P1, 200): rec(0, 0, vx=20),           # proper stop -> ok
                  (P1, 300): rec(0, 0, vx=300)})         # knife -> filtered out
    metrics = compute_shot_metrics(demo, cfg, idx)
    by_tick = {m["tick"]: m for m in metrics}
    assert 100 in by_tick and by_tick[100]["violation"] == 1
    assert 200 in by_tick and by_tick[200]["violation"] == 0
    assert 300 not in by_tick  # non-firearm excluded
    # threshold edge: exactly at threshold is NOT a violation
    demo2 = FakeDemo(PLAYERS, {"shots": [{"tick": 100, "user_steamid": P1, "weapon": "weapon_ak47"}],
                               "damages": [], "kills": [], "bombs": {"planted": [], "defused": []},
                               "grenades": {}}, ROUNDS)
    idx2 = idx_at({(P1, 100): rec(0, 0, vx=cfg.move_shoot_velocity)})
    m2 = compute_shot_metrics(demo2, cfg, idx2)
    assert m2[0]["violation"] == 0


# ---------------------------------------------------------------- advantage
def test_advantage():
    cfg = Config()
    db = seed_db()
    demo = FakeDemo(PLAYERS, {"damages": [], "kills": [], "shots": [],
                              "bombs": {"planted": [], "defused": []}, "grenades": {}}, ROUNDS)
    # 3v2 advantage; P1 isolated (teammates far), no bomb -> LOW urgency, no info -> LOW
    idx = idx_at({(P1, 100): rec(0, 0), (P2, 100): rec(0, 5000), (P3, 100): rec(0, 6000),
                  (P4, 100): rec(1000, 0), (P5, 100): rec(1200, 0)})
    db.insert_dp(
        {"dp_id": "a1", "match_id": "t1", "round": 1, "steamid": P1, "player_name": "A",
         "start_tick": 60, "decision_tick": 100, "end_tick": 200, "observed_action": "PEEK",
         "alternatives": [], "zone": "MID", "place": "Middle", "confidence": 0.7,
         "significance": 1.0, "evidence": {}, "meta": {"opponent": P4}},
        {"dp_id": "a1", "match_id": "t1", "round": 1, "decision_tick": 100,
         "map": "de_dust2", "side": "T", "zone": "MID", "observed_action": "PEEK",
         "features": {}, "labels": {}, "known_state": {"n_known_enemies": 0, "teammate_near": 0},
         "public_info": {}, "ground_truth": {}},
        {"dp_id": "a1", "survival": 0, "survival_window_ticks": 640, "death_tick": 150,
         "duel_result": "lost", "duel_opponent": str(P4), "round_win": 0})
    cands = detect_advantage(demo, cfg, db, idx)
    assert any(c["classification"] == "POSSIBLE_ADVANTAGE_OVERAGGRESSION" for c in cands)
    # valid proactive: teammate near -> trade HIGH
    idx2 = idx_at({(P1, 100): rec(0, 0), (P2, 100): rec(300, 0), (P3, 100): rec(0, 5000),
                   (P4, 100): rec(1000, 0), (P5, 100): rec(1200, 0)})
    cands2 = detect_advantage(demo, cfg, db, idx2)
    assert cands2 and cands2[0]["classification"] == "VALID_PROACTIVE"


# ---------------------------------------------------------------- training
def _seed_pattern(db, ptype, n, rate, conf, category="Micro Decision"):
    db.upsert_pattern({"pattern_id": f"alpha-{ptype}", "pattern_type": ptype,
                       "name": ptype, "category": category,
                       "sample_count": n, "opportunity_count": n,
                       "violation_count": int(n * rate), "violation_rate": rate,
                       "positive_examples": int(n * (1 - rate)), "negative_examples": int(n * rate),
                       "confidence": conf, "counterfactual_support": "AGAINST",
                       "affected_contexts": {}, "evidence_refs": [],
                       "computed_at": time.strftime("%Y-%m-%dT%H:%M:%S")})


def test_training_baseline_and_insufficient():
    cfg = Config()
    db = seed_db()
    _seed_pattern(db, "repeek", n=12, rate=0.6, conf=0.8)
    _seed_pattern(db, "move_shoot", n=12, rate=0.3, conf=0.8, category="Execution")
    _seed_pattern(db, "advantage", n=12, rate=0.5, conf=0.7, category="Macro Decision")
    bottlenecks = rank_bottlenecks(db, cfg, matches_count=1)
    rep = next(b for b in bottlenecks if b["pattern_type"] == "repeek")
    assert rep["eligible"] and rep["level"] == "HIGH"
    targets = generate_targets(db, cfg, bottlenecks)
    # Active Focus: max 2 (one micro/execution + one macro) -> two distinct categories
    cats = {t["category"] for t in targets}
    assert len(targets) == 2
    assert "Macro Decision" in cats and ("Micro Decision" in cats or "Execution" in cats)
    assert db.get_target(targets[0]["target_id"])["status"] == "ACTIVE"
    # no matches since creation -> PENDING_WINDOW / insufficient data
    val = validate_targets(db, cfg)
    assert val and val[0]["verdict"] in ("PENDING_WINDOW", "INSUFFICIENT_DATA")


# ---------------------------------------------------------------- annotation
def test_annotation_loop():
    cfg = Config()
    db = seed_db()
    _seed_pattern(db, "repeek", n=12, rate=0.6, conf=0.8)
    seed_dp(db)
    db.replace_pattern_evidence("alpha-repeek", "t1", [
        {"kind": "violation", "round": 1, "tick": 150, "dp_id": "d1",
         "detail": {"evaluation": "POOR", "confidence": 0.5}},
        {"kind": "positive", "round": 1, "tick": 300, "dp_id": None,
         "detail": {"evaluation": "REASONABLE", "confidence": 0.95}},
    ])
    items = build_review_queue(db, cfg, "t1")
    assert len(items) <= cfg.review_budget_per_match
    assert items and all(i["priority"] > 0 for i in items)
    from playerlab.annotation import persist_review_queue
    persist_review_queue(db, items)
    ann = submit_annotation(db, items[0]["id"], "decision_quality",
                            human_label="BAD", reason_code="TEAM_CALL")
    assert ann["model_prediction"] == items[0]["model_prediction"]  # prediction preserved
    assert ann["human_label"] == "BAD"                               # correction separate
    assert ann["model_version"] == "alpha-1" and ann["rule_version"] == "alpha-1"
    got = db.get_annotations()
    assert len(got) == 1 and got[0]["correction_type"] == "correction"
    try:
        submit_annotation(db, None, "decision_quality", human_label="GOOD",
                          reason_code="NOT_A_CODE")
        assert False, "invalid reason code must be rejected"
    except ValueError:
        pass
    pref = submit_preference(db, "t1", 1, 150, "e1", ["A", "B"], "A")
    assert pref["candidates"] == ["A", "B"]
    stats = annotation_stats(db)
    assert "decision_quality" in stats["by_type"]


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
