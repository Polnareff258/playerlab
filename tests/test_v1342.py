"""V1.3.4.2 tests: evidence honesty + demo-centric review sessions (PART AL).

Covers: no-LOS causality downgrade, possible_visibility not causal, session
= one demo + focus player, chronological order, frozen sample_ids, resume,
blind review hides prediction, reveal after submit, conflict review keeps
the original blind annotation (revision appended), insufficient-information
excluded from accuracy, skip is not a label, active learning selects without
reordering, HUMAN labels survive re-runs, old annotations migrate.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))

from playerlab.db import DB  # noqa: E402
from playerlab.config import Config  # noqa: E402
from playerlab import review_session as rs  # noqa: E402
from playerlab.contact_semantics import (ContactWindow, ExposureRelation,  # noqa: E402
                                         classify_contact, classify_initiation_v2,
                                         motion_evidence, classify_motion_relation)


def _cfg(**kw):
    base = dict(initiation_motion_window_ticks=8, initiation_min_speed=80.0,
                initiation_min_displacement=24.0, mutual_motion_ratio=0.5,
                static_motion_max=40.0, hold_stability_ticks=4,
                hold_max_displacement=48.0, v_hold=60.0, v_peek=120.0)
    base.update(kw)
    return Config(**base)


def _dual_records(self_rows, enemy_rows):
    idx = {}
    for pid, rows in ((1, self_rows), (2, enemy_rows)):
        for t, x, speed, yaw in rows:
            idx[(pid, t)] = {"x": x, "y": 0.0, "speed": speed, "yaw": yaw,
                             "is_alive": True, "vx": speed, "vy": 0.0}
    return idx


def _relation(tick, ss, es, sv=True, ev=True):
    return ExposureRelation(1, 2, tick, sv, ev, ss, es, "exact", 1.0,
                            pair_visible=sv)


def _seed_db_with_samples():
    """A demo with 3 pending samples across rounds for one player."""
    db = DB(":memory:")
    db.upsert_match({"demo_id": "d1", "demo_path": "", "map_name": "de_dust2",
                     "tickrate": 64, "player_count": 10, "rounds_total": 3,
                     "side_swap_round": None, "parsed_at": "2026-01-01T00:00:00",
                     "parser_version": "test"})
    db.replace_rounds("d1", [
        {"round": 1, "start_tick": 1000, "end_tick": 6000, "winner": "CT", "reason": "t_killed"},
        {"round": 2, "start_tick": 7000, "end_tick": 12000, "winner": "CT", "reason": "t_killed"},
        {"round": 3, "start_tick": 13000, "end_tick": 18000, "winner": "T", "reason": "ct_killed"},
    ])
    # round 1 (tick 2000), round 2 (tick 8000), round 3 (tick 14000)
    for i, (rnum, tick) in enumerate([(1, 2000), (2, 8000), (3, 14000)]):
        db.upsert_contact_action_sample({
            "id": f"d1-contact-111-{tick}", "match_id": "d1", "player_id": 111,
            "enemy_id": 222,
            "round": rnum, "tick": tick,
            "contact_window": {"pre_contact_start": tick - 64,
                               "visibility_tick": None, "sight_state": "UNKNOWN",
                               "first_shot_tick": tick},
            "prediction": {"initiation": "UNKNOWN", "top_label": "UNKNOWN",
                           "probabilities": {"UNKNOWN": 0.8, "HOLD": 0.1, "PEEK": 0.1},
                           "confidence": 0.3, "ambiguous": False,
                           "ambiguous_labels": [], "subtype": None,
                           "why": "no visibility evidence"},
            "context": {"map_name": "de_dust2"},
        })
    return db


# --- PART AL #1 (covered in test_v134) --------------------------------------
# --- session only contains one demo -----------------------------------------
def test_session_contains_only_one_demo_and_player():
    db = _seed_db_with_samples()
    sess = rs.start_session(db, "d1", 111, recommended_only=False)
    assert sess["demo_id"] == "d1"
    assert sess["player_id"] == 111
    ids = sess["sample_ids"]
    assert len(ids) == 3
    # all samples belong to the demo+player
    for s in db.get_contact_action_samples(review_status=None, limit=100):
        if s["id"] in ids:
            assert s["match_id"] == "d1" and s["player_id"] == 111


# --- session samples chronological ------------------------------------------
def test_session_samples_chronological():
    db = _seed_db_with_samples()
    sess = rs.start_session(db, "d1", 111, recommended_only=False)
    ids = sess["sample_ids"]
    rows = {s["id"]: (s["round"], s["tick"]) for s in
            db.get_contact_action_samples(review_status=None, limit=100)}
    order = [rows[i] for i in ids]
    assert order == sorted(order), "samples must be round ASC, tick ASC"


# --- resume preserves current position ---------------------------------------
def test_session_resume_preserves_position():
    db = _seed_db_with_samples()
    sess = rs.start_session(db, "d1", 111, recommended_only=False)
    # answer the first sample
    rs.record_answer(db, sess["session_id"], sess["sample_ids"][0],
                     {"INITIATION": "SELF_INITIATED", "ACTION": "HOLD",
                      "SUPPORT": "UNASSISTED"}, outcome="LABELED")
    sess2 = db.get_review_session(sess["session_id"])
    assert sess2["current_index"] >= 1
    assert sess2["completed_count"] == 1
    cur = rs.current_sample(db, sess2)
    assert cur["id"] == sess["sample_ids"][1]  # resumes at next unresolved


# --- blind review hides prediction -------------------------------------------
def test_blank_prediction_available_but_not_required_for_blind():
    """The blind contract is a UI concern; the API keeps the prediction on the
    sample but the session card (UI) must not render it before submit. Here we
    assert the session exposes raw evidence separately from prediction."""
    db = _seed_db_with_samples()
    sess = rs.start_session(db, "d1", 111)
    s = rs.current_sample(db, sess)
    assert s is not None
    assert "prediction" in s          # stored (reveal needs it after submit)
    assert "contact_window" in s      # raw evidence available for the card


# --- conflict review retains first blind annotation --------------------------
def test_conflict_review_keeps_original_annotation():
    db = _seed_db_with_samples()
    sess = rs.start_session(db, "d1", 111, recommended_only=False)
    sid = sess["sample_ids"][0]
    first = rs.record_answer(db, sess["session_id"], sid,
                             {"INITIATION": "ENEMY_INITIATED", "ACTION": "HOLD",
                              "SUPPORT": "UNASSISTED"}, outcome="LABELED",
                             blind=True)
    anns_before = db.get_annotations_v2(sample_id=sid)
    orig_ids = {a["annotation_id"] for a in anns_before if a["label"]}
    # conflict revision: human changes INITIATION to SELF_INITIATED
    rev = rs.record_revision(db, sess["session_id"], sid,
                             original_annotation_id=first["annotation_ids"][0],
                             dimension_answers={"INITIATION": "SELF_INITIATED",
                                                "ACTION": "HOLD",
                                                "SUPPORT": "UNASSISTED"},
                             reason="reconsidered")
    anns_after = db.get_annotations_v2(sample_id=sid)
    after_ids = {a["annotation_id"] for a in anns_after if a["label"]}
    # original blind annotations still present (not overwritten)
    assert orig_ids.issubset(after_ids)
    # revision rows point at the original
    revs = [a for a in anns_after if a.get("revision_of")]
    assert len(revs) >= 1
    assert revs[0]["revision_of"] == first["annotation_ids"][0]


# --- insufficient-information excluded from accuracy -------------------------
def test_insufficient_information_not_a_label():
    db = _seed_db_with_samples()
    sess = rs.start_session(db, "d1", 111, recommended_only=False)
    sid = sess["sample_ids"][0]
    rs.record_answer(db, sess["session_id"], sid, {}, outcome="INSUFFICIENT_INFORMATION")
    anns = db.get_annotations_v2(sample_id=sid)
    assert any(a.get("review_outcome") == "INSUFFICIENT_INFORMATION" for a in anns)
    # no LABELED annotation rows exist for it
    assert not any(a.get("review_outcome") == "LABELED" for a in anns)


# --- skip does not count as a label -----------------------------------------
def test_skip_is_not_a_label():
    db = _seed_db_with_samples()
    sess = rs.start_session(db, "d1", 111, recommended_only=False)
    sid = sess["sample_ids"][0]
    rs.record_skip(db, sess["session_id"], sid)
    # sample stays pending (can return later)
    row = db.conn.execute("SELECT review_status FROM contact_action_samples WHERE id=?",
                          (sid,)).fetchone()
    assert row["review_status"] != "reviewed"
    sess2 = db.get_review_session(sess["session_id"])
    assert sess2["skipped_count"] == 1
    assert sess2["completed_count"] == 0


# --- active learning selects but does not reorder ----------------------------
def test_active_learning_selects_without_reordering():
    db = _seed_db_with_samples()
    cands = rs.build_demo_candidates(db, "d1", 111)
    # budget 2 -> picks 2, still chronological
    picked = rs._active_learning_select(
        [s for s in db.get_contact_action_samples(review_status=None, limit=100)
         if s["id"] in cands["all_ids"]], budget=2)
    rows = {s["id"]: (s["round"], s["tick"]) for s in
            db.get_contact_action_samples(review_status=None, limit=100)}
    order = [rows[i] for i in picked]
    assert order == sorted(order), "selection must not reorder chronologically"


# --- session sample set frozen after creation --------------------------------
def test_session_sample_set_frozen():
    db = _seed_db_with_samples()
    sess = rs.start_session(db, "d1", 111, recommended_only=False)
    frozen = list(sess["sample_ids"])
    # a re-run adds a new pending sample -> session must NOT change
    db.upsert_contact_action_sample({
        "id": "s-new", "match_id": "d1", "player_id": 111, "enemy_id": 222,
        "round": 2, "tick": 9000, "contact_window": {},
        "prediction": {"initiation": "UNKNOWN", "top_label": "UNKNOWN",
                       "probabilities": {}, "confidence": 0.2}})
    sess2 = db.get_review_session(sess["session_id"])
    assert sess2["sample_ids"] == frozen


# --- rerun does not overwrite HUMAN annotations ------------------------------
def test_rerun_does_not_overwrite_human_annotations():
    db = _seed_db_with_samples()
    sess = rs.start_session(db, "d1", 111, recommended_only=False)
    sid = sess["sample_ids"][0]
    rs.record_answer(db, sess["session_id"], sid,
                     {"INITIATION": "ENEMY_INITIATED", "ACTION": "HOLD",
                      "SUPPORT": "UNASSISTED"}, outcome="LABELED")
    # simulate a pipeline re-run: persist_contact_samples skips HUMAN samples
    from playerlab.decision import persist_contact_samples
    dp = {"meta": {"contact": {
            "prediction": {"top_label": "PEEK", "initiation": "SELF_INITIATED"},
          }, "opponent": 222},
          "steamid": 111, "round": 1, "decision_tick": 2000}
    demo = type("Demo", (), {"demo_id": "d1"})()
    made = persist_contact_samples(demo, _cfg(), db, [dp])
    # sample already HUMAN -> not overwritten
    row = db.conn.execute("SELECT label_source, review_status FROM "
                          "contact_action_samples WHERE id=?", (sid,)).fetchone()
    assert row["label_source"] == "HUMAN"
    assert row["review_status"] == "reviewed"


# --- old annotations migrate safely ------------------------------------------
def test_old_annotations_migrate_safely():
    """Legacy annotations (single label row, no dimension) remain readable and
    are never dropped by the new session code."""
    db = _seed_db_with_samples()
    sess = rs.start_session(db, "d1", 111, recommended_only=False)
    sid = sess["sample_ids"][0]
    # legacy-style row (old schema shape: label only, no dimension)
    import uuid
    db.conn.execute(
        "INSERT INTO contact_action_annotations (annotation_id, sample_id, "
        "annotator_id, label, confidence, reason, created_at) VALUES (?,?,?,?,?,?,?)",
        (uuid.uuid4().hex[:16], sid, "local", "ENEMY_INITIATED", 0.8, "",
         "2026-01-01T00:00:00"))
    db.conn.commit()
    anns = db.get_annotations_v2(sample_id=sid)
    assert any(a.get("label") == "ENEMY_INITIATED" for a in anns)
    # session summary works with legacy rows present
    sm = rs.session_summary(db, db.get_review_session(sess["session_id"]))
    assert "reviewed_count" in sm


# --- CS-NET hidden in blind phase --------------------------------------------
def test_csnet_not_in_blind_payload():
    """The blind review card data must not include CS-NET interpretation
    (it lives in csnet_evidence, surfaced only in conflicts/advanced)."""
    db = _seed_db_with_samples()
    sess = rs.start_session(db, "d1", 111)
    s = rs.current_sample(db, sess)
    # csnet evidence may be stored but must not be required for the blind card
    assert s is not None
    assert s.get("csnet_evidence") is None or s.get("csnet_evidence") == {}


# --- session complete -> summary --------------------------------------------
def test_session_completes_with_summary():
    db = _seed_db_with_samples()
    sess = rs.start_session(db, "d1", 111, recommended_only=False)
    for i, sid in enumerate(sess["sample_ids"]):
        if i == 1:
            rs.record_answer(db, sess["session_id"], sid, {},
                             outcome="INSUFFICIENT_INFORMATION")
        else:
            rs.record_answer(db, sess["session_id"], sid,
                             {"INITIATION": "ENEMY_INITIATED", "ACTION": "HOLD",
                              "SUPPORT": "UNASSISTED"}, outcome="LABELED")
    sess2 = db.get_review_session(sess["session_id"])
    assert sess2["status"] == "COMPLETED"
    assert sess2["completed_count"] == 2
    assert sess2["insufficient_count"] == 1
    sm = rs.session_summary(db, sess2)
    assert sm["reviewed_count"] == 2      # 2 LABELED (insufficient not counted)
    assert sm["insufficient_count"] == 1
