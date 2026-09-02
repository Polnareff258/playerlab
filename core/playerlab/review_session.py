"""DemoReviewSession logic (V1.3.4.2 PART I-N/O-Q/R-U).

Core principles:
  * One Demo = One Review Session (bound to a focus player).
  * Active learning chooses WHAT (recommended subset); chronological order
    (round ASC, tick ASC) chooses HOW to review. The session sample list is
    FROZEN at creation — a classifier re-run must never reshuffle or extend
    an in-progress session (PART AJ).
  * Blind first: the system prediction is hidden until the human submits;
    after submit we reveal it and (optionally) record a conflict revision.
  * Review outcomes: LABELED / UNSURE / INSUFFICIENT_INFORMATION / SKIPPED.
    UNSURE = enough info but annotator cannot decide; INSUFFICIENT_INFORMATION
    = the demo itself lacks the needed info (no audio, hidden intent, no LOS
    geometry) and such samples never enter accuracy/calibration (PART H §21).
  * SKIPPED is temporary, never a label.
"""
from __future__ import annotations

import json
import time
import uuid

# review outcome categories (PART H)
OUTCOMES = ("LABELED", "UNSURE", "INSUFFICIENT_INFORMATION", "SKIPPED")
SESSION_STATUS = ("NOT_STARTED", "IN_PROGRESS", "COMPLETED")
DIMENSIONS = ("INITIATION", "ACTION", "SUPPORT")


def build_demo_candidates(db, demo_id: str, player_id: int,
                          recommended_only: bool = False) -> dict:
    """Gather all pending samples of a demo+player, chronologically sorted,
    deduped by contact episode. Returns {all_ids, recommended_ids}."""
    samples = db.get_contact_action_samples(review_status="pending", limit=100000)
    # dedupe by (player, opponent, round, temporal window) — PART N §31:
    # one contact episode = one review unit
    by_key: dict[tuple, dict] = {}
    for s in samples:
        if s.get("match_id") != demo_id:
            continue
        if s.get("player_id") is not None and player_id and \
                int(s.get("player_id")) != int(player_id):
            continue
        key = (s.get("player_id"), s.get("enemy_id"), s.get("round"))
        # keep the earliest tick of the same (player,enemy,round) cluster when
        # windows overlap
        existing = by_key.get(key)
        if existing is None:
            by_key[key] = s
    # chronological order (round ASC, tick ASC) — PART L §25
    all_sorted = sorted(by_key.values(), key=lambda s: (s.get("round", 0),
                                                        s.get("tick", 0)))
    all_ids = [s["id"] for s in all_sorted]
    # recommended = active-learning selected subset (PART M §28), still in
    # chronological order (selection does NOT reorder — PART L §14)
    rec_ids = _active_learning_select(all_sorted)
    return {"all_ids": all_ids, "recommended_ids": rec_ids,
            "all_count": len(all_ids), "recommended_count": len(rec_ids)}


def _active_learning_select(samples: list[dict], budget: int | None = None,
                            max_budget: int = 40) -> list[str]:
    """Active-learning selection (PART M §28): prioritize samples the system
    is least sure about. Selection never reorders the chronological list."""
    if budget is None:
        budget = max_budget
    scored = []
    for s in samples:
        pred = s.get("prediction") or {}
        score = 0.0
        if pred.get("ambiguous"):
            score += 2.0                      # PEEK vs HOLD ambiguous
        if pred.get("initiation") == "UNKNOWN":
            score += 1.5                      # initiation unknown
        if pred.get("top_label") == "UNKNOWN":
            score += 1.0
        conf = pred.get("confidence") or 0.0
        score += (1.0 - conf) * 1.0           # low evidence
        cw = s.get("contact_window") or {}
        if cw.get("sight_state") == "POSSIBLY_VISIBLE":
            score += 0.7                      # geometry/rule disagreement
        # rare contexts / flank/stealth cues from stored context
        ctx = s.get("context") or {}
        if ctx.get("flank_state") in ("ACTIVE_FLANK", "DEEP_FLANK"):
            score += 0.6
        scored.append((score, s["id"], s.get("round", 0), s.get("tick", 0)))
    # sort by score desc but keep chronological tie-break in output order:
    # select top-N then re-sort selected chronologically
    scored.sort(key=lambda x: (-x[0], x[2], x[3]))
    picked = [sid for _, sid, _, _ in scored[:budget]]
    id_order = {sid: i for i, sid in
                enumerate(s["id"] for s in samples)}
    picked.sort(key=lambda sid: id_order.get(sid, 0))
    return picked


def start_session(db, demo_id: str, player_id: int,
                  player_display_name: str = "",
                  recommended_only: bool = True) -> dict:
    """Create a frozen demo review session (PART I §22, PART AJ §freeze)."""
    cands = build_demo_candidates(db, demo_id, player_id)
    ids = cands["recommended_ids"] if recommended_only else cands["all_ids"]
    session_id = f"drs-{demo_id[:8]}-{player_id}-{int(time.time())}"
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    session = {
        "session_id": session_id,
        "demo_id": demo_id,
        "player_id": player_id,
        "sample_ids": ids,                 # frozen at creation
        "recommended_sample_ids": cands["recommended_ids"],
        "current_index": 0,
        "completed_count": 0, "skipped_count": 0,
        "unsure_count": 0, "insufficient_count": 0,
        "status": "IN_PROGRESS",
        "focus_display_name": player_display_name,
        "started_at": now, "updated_at": now, "completed_at": "",
    }
    db.upsert_review_session(session)
    return session


def next_unresolved_index(db, session: dict) -> int:
    """Resume: first sample not yet reviewed/skipped, from current_index on
    (PART Q §39). Returns index into sample_ids, or -1 when done."""
    ids = session.get("sample_ids") or []
    start = session.get("current_index", 0)
    if start >= len(ids):
        return -1
    for i in range(start, len(ids)):
        sid = ids[i]
        row = db.conn.execute(
            "SELECT review_status FROM contact_action_samples WHERE id=?",
            (sid,)).fetchone()
        if row is None or row["review_status"] != "reviewed":
            return i
    return -1


def current_sample(db, session: dict) -> dict | None:
    idx = next_unresolved_index(db, session)
    if idx < 0:
        return None
    ids = session.get("sample_ids") or []
    if idx >= len(ids):
        return None
    sid = ids[idx]
    for s in db.get_contact_action_samples(review_status=None, limit=100000):
        if s["id"] == sid:
            return s
    return None


def record_answer(db, session_id: str, sample_id: str,
                  dimension_answers: dict, outcome: str = "LABELED",
                  reason: str = "", blind: bool = True,
                  confidence: float = 0.7) -> dict:
    """Record per-dimension human answers (PART G §16 one row per dimension).

    outcome in {LABELED, UNSURE, INSUFFICIENT_INFORMATION}. For LABELED,
    dimension_answers = {INITIATION: label, ACTION: label, SUPPORT: label}.
    blind=True records that labels were collected before model exposure.
    """
    if outcome not in OUTCOMES:
        raise ValueError(f"invalid outcome: {outcome}")
    session = db.get_review_session(session_id)
    if not session:
        raise ValueError("session not found")
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    created = []
    dims = list(DIMENSIONS) if outcome == "LABELED" else [None]
    for d in dims:
        label = ""
        if outcome == "LABELED":
            label = dimension_answers.get(d, "")
        ann_id = uuid.uuid4().hex[:16]
        db.upsert_contact_annotation_v2({
            "annotation_id": ann_id,
            "sample_id": sample_id,
            "annotator_id": "local",
            "label": label,
            "confidence": confidence,
            "reason": reason,
            "created_at": now,
            "dimension": d or outcome,
            "review_outcome": outcome,
            "blind_review": 1 if blind else 0,
            "revision_of": None,
            "revision_reason": "",
        })
        created.append(ann_id)
    # mark sample reviewed with its outcome; HUMAN labels are authoritative
    db.update_sample_review(sample_id, "reviewed", outcome,
                            label_source="HUMAN" if outcome == "LABELED"
                            else None)
    # update session counters + advance
    counts = {
        "LABELED": "completed_count", "SKIPPED": "skipped_count",
        "UNSURE": "unsure_count",
        "INSUFFICIENT_INFORMATION": "insufficient_count",
    }
    col = counts[outcome]
    session[col] = session.get(col, 0) + 1
    session["current_index"] = _advance_index(db, session, sample_id)
    session["updated_at"] = now
    if next_unresolved_index(db, session) < 0:
        session["status"] = "COMPLETED"
        session["completed_at"] = now
    db.upsert_review_session(session)
    return {"annotation_ids": created, "session": session,
            "status": session["status"]}


def record_skip(db, session_id: str, sample_id: str) -> dict:
    """SKIPPED: temporary, never a label (PART H §20). Sample stays pending
    so the user can come back to it."""
    session = db.get_review_session(session_id)
    if not session:
        raise ValueError("session not found")
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    db.upsert_contact_annotation_v2({
        "annotation_id": uuid.uuid4().hex[:16],
        "sample_id": sample_id, "annotator_id": "local",
        "label": "", "confidence": None, "reason": "skipped",
        "created_at": now, "dimension": "SKIPPED",
        "review_outcome": "SKIPPED", "blind_review": 1,
        "revision_of": None, "revision_reason": ""})
    # keep sample pending; just advance the session cursor past it
    session["skipped_count"] = session.get("skipped_count", 0) + 1
    session["current_index"] = _advance_index(db, session, sample_id,
                                              keep_pending=True)
    session["updated_at"] = now
    db.upsert_review_session(session)
    return {"session": session}


def _advance_index(db, session: dict, sample_id: str,
                   keep_pending: bool = False) -> int:
    """Move the cursor to the next unresolved sample (resume logic)."""
    ids = session.get("sample_ids") or []
    try:
        cur = ids.index(sample_id)
    except ValueError:
        cur = session.get("current_index", 0)
    return cur + 1


def record_revision(db, session_id: str, sample_id: str,
                    original_annotation_id: str,
                    dimension_answers: dict, reason: str = "") -> dict:
    """Conflict-review revision (PART AD): save a NEW annotation that points
    at the original blind annotation. The original is never overwritten."""
    session = db.get_review_session(session_id)
    if not session:
        raise ValueError("session not found")
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    created = []
    for d in DIMENSIONS:
        ann_id = uuid.uuid4().hex[:16]
        db.upsert_contact_annotation_v2({
            "annotation_id": ann_id,
            "sample_id": sample_id, "annotator_id": "local",
            "label": dimension_answers.get(d, ""),
            "confidence": 0.7, "reason": reason,
            "created_at": now, "dimension": d,
            "review_outcome": "LABELED", "blind_review": 0,
            "revision_of": original_annotation_id,
            "revision_reason": reason})
        created.append(ann_id)
    db.update_sample_review(sample_id, "reviewed", "LABELED")
    session["updated_at"] = now
    db.upsert_review_session(session)
    return {"revision_annotation_ids": created}


def session_summary(db, session: dict) -> dict:
    """Demo completion summary (PART R §40-§43)."""
    ids = session.get("sample_ids") or []
    anns = []
    for a in db.get_annotations_v2(limit=100000):
        if a.get("sample_id") in ids:
            anns.append(a)
    # dimension label distributions (only LABELED, non-revision rows)
    dim_counts = {}
    for a in anns:
        if a.get("review_outcome") == "LABELED" and not a.get("revision_of"):
            d = a.get("dimension") or ""
            dim_counts.setdefault(d, {})
            lbl = a.get("label") or "UNKNOWN"
            dim_counts[d][lbl] = dim_counts[d].get(lbl, 0) + 1
    # model agreement on HUMAN-labeled samples (blind, non-revision)
    agreement = {}
    for d in DIMENSIONS:
        agree_n = total_n = 0
        for s_id in ids:
            for s in _samples_by_id(db, ids):
                if s.get("id") != s_id:
                    continue
                pred = s.get("prediction") or {}
                human = _latest_label(anns, s_id, d)
                model = _model_label(pred, d)
                if human and model:
                    total_n += 1
                    if human == model:
                        agree_n += 1
        agreement[d.lower()] = round(agree_n / total_n, 3) if total_n else None
    insufficient = len({a["sample_id"] for a in anns
                        if a.get("review_outcome") == "INSUFFICIENT_INFORMATION"})
    # reviewed = distinct samples with LABELED/UNSURE (INSUFFICIENT and
    # SKIPPED are not reviewed annotations — PART H §21)
    reviewed = len({a["sample_id"] for a in anns
                    if a.get("review_outcome") in ("LABELED", "UNSURE")
                    and not a.get("revision_of")})
    return {
        "session_id": session["session_id"],
        "demo_id": session["demo_id"],
        "player_id": str(session.get("player_id", "")),
        "reviewed_count": reviewed,
        "insufficient_count": insufficient,
        "total_samples": len(ids),
        "label_distribution": dim_counts,
        "model_agreement": agreement,
        "status": session.get("status"),
    }


def _samples_by_id(db, ids):
    return [s for s in db.get_contact_action_samples(review_status=None,
                                                     limit=100000)
            if s["id"] in ids]


def _latest_label(anns, sample_id, dimension):
    rows = [a for a in anns
            if a.get("sample_id") == sample_id and a.get("dimension") == dimension
            and a.get("label")]
    if not rows:
        return None
    rows.sort(key=lambda a: a.get("created_at", ""))
    return rows[-1]["label"]   # revision (latest) wins for agreement


def _model_label(pred: dict, dimension: str) -> str | None:
    if dimension == "INITIATION":
        return pred.get("initiation")
    if dimension == "ACTION":
        return pred.get("top_label")
    if dimension == "SUPPORT":
        # support is stored in engagement context, not prediction — unknown
        return None
    return None


def conflict_samples(db, session: dict) -> list[dict]:
    """PART P §36: samples where the human (blind, latest) disagrees with the
    model, for the Conflict Review pass."""
    ids = set(session.get("sample_ids") or [])
    samples = [s for s in db.get_contact_action_samples(review_status=None,
                                                        limit=100000)
               if s["id"] in ids]
    anns = db.get_annotations_v2(limit=100000)
    out = []
    for s in samples:
        pred = s.get("prediction") or {}
        human_init = _latest_label(anns, s["id"], "INITIATION")
        model_init = pred.get("initiation")
        human_act = _latest_label(anns, s["id"], "ACTION")
        model_act = pred.get("top_label")
        disagree = False
        if human_init and model_init and human_init != model_init:
            disagree = True
        if human_act and model_act and human_act != model_act:
            disagree = True
        if disagree:
            out.append(s)
    return out
