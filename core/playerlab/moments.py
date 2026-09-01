"""ReviewMoment + Player Match Overview (V1.3.2 PART B/G/J).

ReviewMoment is NOT a new detector: it is the selection / ranking /
presentation layer over existing DecisionEpisodes (PART B §8). Weighted
deterministic ranking with every factor recorded (no fake science, §8/§44):

    review_score = w_act*actionability + w_suff*sufficiency
                   + w_imp*impact + w_rec*recurrence + w_train*training

Positive moments (Good Decision / reasonable disengage / plant commitment)
are allowed into Top Review (§42) — the tool must not be a pure fault-finder.

Actionability before frequency (PART J §43): an uncalibrated high-frequency
detector must NOT become the top issue — calibration status gates it.
"""
from __future__ import annotations

import time

from .config import Config
from .db import DB

# weights (configurable; recorded per moment so decisions are explainable)
DEFAULT_WEIGHTS = {
    "actionability": 0.30,   # player-controlled + repeatable
    "sufficiency": 0.20,     # evidence quality (HIGH/MEDIUM/LOW)
    "impact": 0.20,          # round/death relevance
    "recurrence": 0.15,      # how often this pattern repeats
    "training": 0.15,        # training-target relevance
}

TOP_N = 5
MAX_POSITIVE_SHARE = 1.0    # all-positive allowed if data justifies


def _act_score(a: str) -> float:
    return {"HIGHLY_ACTIONABLE": 1.0, "ACTIONABLE": 0.7,
            "WEAKLY_ACTIONABLE": 0.4, "NOT_ACTIONABLE": 0.1,
            "INSUFFICIENT_EVIDENCE": 0.0}.get(a, 0.3)


def _suff_score(s: str) -> float:
    return {"HIGH": 1.0, "MEDIUM": 0.6, "LOW": 0.3, "INSUFFICIENT": 0.0}.get(s, 0.3)


def _impact(episode: dict) -> float:
    """Impact: death + round urgency + objective involvement."""
    ir = episode.get("immediate_result") or {}
    s = 0.3
    if ir.get("survived_3s") is False:
        s += 0.4
    if ir.get("kill_within_3s"):
        s += 0.2
    macro = episode.get("macro_context") or {}
    if macro.get("objective_urgency") == "HIGH":
        s += 0.3
    elif macro.get("bomb_state", {}).get("planted"):
        s += 0.2
    return min(1.0, s)


def _recurrence(episode: dict, db: DB) -> float:
    """Same family + same evaluation bucket across the player's matches."""
    pid = episode["player_id"]
    own = db.get_decision_episodes(player_id=pid, limit=500)
    if len(own) < 3:
        return 0.0
    same_fam = [e for e in own if e["family"] == episode["family"]]
    if not same_fam:
        return 0.0
    same_eval = [e for e in same_fam
                 if e.get("strategic_evaluation") == episode.get("strategic_evaluation")]
    return min(1.0, len(same_eval) / len(same_fam))


def _training(episode: dict) -> float:
    """Training relevance: actionable + questionable/poor evaluation."""
    if episode.get("actionability") in ("HIGHLY_ACTIONABLE", "ACTIONABLE"):
        if episode.get("decision_evaluation") in ("QUESTIONABLE", "POOR"):
            return 1.0
        if episode.get("execution_evaluation") in ("QUESTIONABLE", "POOR"):
            return 0.8
    return 0.2


def _is_positive(episode: dict) -> bool:
    """Good / reasonable moments worth showing as examples (§42)."""
    if episode.get("decision_evaluation") == "GOOD":
        return True
    if episode.get("decision_evaluation") == "REASONABLE" and \
            episode.get("actionability") in ("WEAKLY_ACTIONABLE", "NOT_ACTIONABLE"):
        return True  # reasonable commitment (e.g. plant)
    return False


def _primary_reason(episode: dict) -> str:
    """One-line why this moment matters (the explainable summary)."""
    ev = episode.get("decision_evaluation", "?")
    eng = episode.get("engagement_evaluation")
    exe = episode.get("execution_evaluation")
    if ev in ("QUESTIONABLE", "POOR"):
        return f"{ev} strategic decision"
    if eng in ("QUESTIONABLE", "POOR"):
        return f"{eng} engagement method"
    if exe in ("QUESTIONABLE", "POOR"):
        return f"{exe} execution"
    if _is_positive(episode):
        return "Good example to reinforce"
    return "Reasonable decision worth reviewing"


def rank_review_moments(db: DB, cfg: Config, match_id: str, player_id: int,
                        top_n: int = TOP_N,
                        calibration: dict | None = None) -> list[dict]:
    """Rank episodes into ReviewMoments for a player (PART B §8-§9).
    calibration: {detector_type: CalibrationState} — uncalibrated detectors
    are suppressed from the top (PART J §43, §10 gate)."""
    eps = db.get_decision_episodes(match_id=match_id, player_id=player_id, limit=1000)
    if not eps:
        return []
    weights = DEFAULT_WEIGHTS
    moments = []
    for ep in eps:
        act = _act_score(ep.get("actionability"))
        suff = _suff_score(ep.get("evidence_sufficiency"))
        imp = _impact(ep)
        rec = _recurrence(ep, db)
        train = _training(ep)
        # calibration gate (§10): uncalibrated detector primitives suppress
        cal = calibration or {}
        prims = ep.get("execution_primitives") or []
        cal_penalty = 0.0
        for p in prims:
            if cal.get(p) in ("UNCALIBRATED", "EXPERIMENTAL"):
                cal_penalty = max(cal_penalty, 0.3)
        # positive moments get the training dimension from the good example
        positive = _is_positive(ep)
        score = (weights["actionability"] * act
                 + weights["sufficiency"] * suff
                 + weights["impact"] * imp
                 + weights["recurrence"] * rec
                 + weights["training"] * train) * (1.0 - cal_penalty)
        moments.append({
            "id": f"{ep['id']}-moment", "match_id": match_id,
            "player_id": player_id, "episode_id": ep["id"],
            "review_score": round(score, 4),
            "actionability": ep.get("actionability"),
            "evidence_sufficiency": ep.get("evidence_sufficiency"),
            "impact": round(imp, 3), "recurrence": round(rec, 3),
            "training_relevance": round(train, 3),
            "is_positive": positive,
            "primary_reason": _primary_reason(ep),
            "why_selected": _why_selected(ep, act, suff, imp, rec, train,
                                          cal_penalty),
            "factors": {"actionability": act, "sufficiency": suff,
                        "impact": imp, "recurrence": rec, "training": train,
                        "calibration_penalty": round(cal_penalty, 3)},
            "computed_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        })
    # score-first ranking (improvement moments compete fairly); ensure at
    # least one positive example makes the top when available (PART I §42:
    # the tool is not a pure fault-finder)
    moments.sort(key=lambda m: -m["review_score"])
    positives = [m for m in moments if m["is_positive"]]
    negatives = [m for m in moments if not m["is_positive"]]
    if positives and negatives and not any(m["is_positive"] for m in moments[:top_n]):
        # reserve one slot for a good example, replace the lowest-ranked pick
        kept = negatives[:top_n - 1] + positives[:1]
        kept.sort(key=lambda m: -m["review_score"])
        moments = kept
    db.replace_review_moments(match_id, player_id, moments)
    return moments[:top_n]


def _why_selected(ep, act, suff, imp, rec, train, cal_penalty) -> str:
    parts = []
    if act >= 0.7:
        parts.append("highly actionable")
    if suff >= 0.6:
        parts.append("strong evidence")
    if imp >= 0.7:
        parts.append("high impact")
    if rec >= 0.6:
        parts.append("recurring pattern")
    if train >= 0.8:
        parts.append("directly training-relevant")
    if cal_penalty > 0:
        parts.append("reduced: detector uncalibrated")
    return "; ".join(parts) if parts else "selected by weighted ranking"


def player_match_overview(db: DB, cfg: Config, match_id: str,
                          player_id: int) -> dict:
    """Player Match Overview (PART G §34-§36): distribution + explainable
    summary — NO 0-100 composite score (PART G §35)."""
    eps = db.get_decision_episodes(match_id=match_id, player_id=player_id, limit=1000)
    if not eps:
        return {"player_id": player_id, "episodes": 0}
    from collections import Counter
    strat = Counter(e.get("strategic_evaluation") for e in eps)
    eng = Counter(e.get("engagement_evaluation") for e in eps)
    exe = Counter(e.get("execution_evaluation") for e in eps)
    fam = Counter(e["family"] for e in eps)
    n = len(eps)
    good_share = strat.get("GOOD", 0) / n
    poor_share = (strat.get("POOR", 0) + strat.get("QUESTIONABLE", 0)) / n

    decision_summary = "MOSTLY REASONABLE" if good_share >= 0.5 else (
        "MIXED" if poor_share < 0.5 else "NEEDS REVIEW")
    # strength / weakness from family-level eval
    fam_scores = {}
    for f, cnt in fam.items():
        feps = [e for e in eps if e["family"] == f]
        fgood = sum(1 for e in feps if e.get("strategic_evaluation") == "GOOD")
        fam_scores[f] = round(fgood / len(feps), 3) if feps else 0.0
    strongest = max(fam_scores, key=fam_scores.get) if fam_scores else None
    weakest = min(fam_scores, key=fam_scores.get) if fam_scores else None

    return {
        "player_id": str(player_id), "episodes": n,
        "summary": decision_summary,
        "distributions": {
            "strategic": dict(strat), "engagement": dict(eng),
            "execution": dict(exe), "family": dict(fam),
        },
        "strengths": [{"family": strongest, "good_share": fam_scores.get(strongest)}]
        if strongest else [],
        "needs_review": [{"family": weakest, "good_share": fam_scores.get(weakest)}]
        if weakest and fam_scores.get(weakest) < 0.4 else [],
        "explainable": {"based_on_episodes": n,
                        "note": "no composite score; distributions + explainable summaries only"},
    }
