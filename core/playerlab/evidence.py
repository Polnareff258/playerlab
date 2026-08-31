"""Alternative Evidence channels (V1.3 spec §29-§38).

DecisionEvidence rows per candidate action from independent sources:
- rule: deterministic context heuristics
- historical: similar-state retrieval (counterfactual engine)
- personal: PersonalActionHistory ("you re-peek 62% in similar spots")
- model: CS-NET state-value (GROUND_TRUTH_STATE, never PlayerKnownState)
- (future) pro_reference

Evidence independence (spec §31): historical retrieval and counterfactual
come from the same dataset -> mark related_sources so weights are not
double-counted. CS-NET delta is evidence, never a verdict (spec §33-§36).
"""
from __future__ import annotations

import time
import uuid

from .config import Config
from .db import DB
from .counterfactual import retrieve


def build_evidence(demo, cfg, db, episode: dict, candidates: list[dict],
                   model_provider=None) -> tuple[dict, list[dict]]:
    """Produce DecisionEvidence for every candidate + a per-action summary
    {action: {risk, support, value}} used by evaluate_decision.

    Returns (summary, evidence_rows).
    """
    summary = {}
    rows = []
    macro = episode.get("macro_context") or {}
    local = episode.get("local_context") or {}
    observed = episode.get("observed_action", "HOLD")
    adv = macro.get("advantage_state", "EVEN")
    need_info = macro.get("need_for_information", "NONE")
    risk_tol = macro.get("risk_tolerance", "MEDIUM")

    for c in candidates:
        action = c["action"]
        f = c["feasibility"]
        s = {"risk": "MEDIUM", "support": "UNKNOWN", "value": "LOW", "sources": []}

        # ---- rule evidence ----
        risk, support, value, rule_notes = _rule_signal(
            action, f, adv, need_info, risk_tol, observed, macro)
        s["risk"], s["support"], s["value"] = risk, support, value
        if rule_notes:
            rows.append(_row(episode, action, "rule", "heuristic",
                             supports=action, contradicts=None,
                             confidence=0.6, notes="; ".join(rule_notes),
                             related=["rule_v1.3-1"]))
            s["sources"].append("rule")

        # ---- historical evidence (spec §35-§37) ----
        hist = _historical(db, cfg, episode, action)
        if hist:
            rows.append(_row(episode, action, "historical", "similar_state_outcome",
                             supports=action if hist["support"] else None,
                             contradicts=action if not hist["support"] else None,
                             confidence=hist["confidence"],
                             sample_count=hist["n"],
                             source_version="counterfactual-v1.2.1",
                             related=["historical", "counterfactual"],
                             notes=hist["note"]))
            s["sources"].append("historical")
            if hist["support"] and s["support"] == "UNKNOWN":
                s["support"] = "HIGH" if hist["confidence"] >= 0.6 else "MEDIUM"

        # ---- personal history (spec §38-§39) ----
        pers = _personal(db, cfg, episode, action)
        if pers:
            rows.append(_row(episode, action, "personal", "personal_action_history",
                             supports=action if pers["support"] else None,
                             contradicts=action if not pers["support"] else None,
                             confidence=pers["confidence"],
                             sample_count=pers["n"],
                             source_version="personal-history-v1.3-1",
                             notes=pers["note"]))
            s["sources"].append("personal")

        # ---- CS-NET state value (spec §33-§34) ----
        if model_provider is not None:
            ev = _model_evidence(model_provider, episode)
            if ev:
                rows.append(ev)
                s["sources"].append("model")
                # delta < 0 is evidence, NOT a verdict (spec §36)
                if ev.get("type") == "state_value_swing" and ev.get("contradicts_action"):
                    s["support"] = "LOW"
                s["model_delta"] = ev.get("delta")

        summary[action] = s

    return summary, rows


def _rule_signal(action, f, adv, need_info, risk_tol, observed, macro):
    risk = "MEDIUM"; support = "UNKNOWN"; value = "LOW"
    notes = []
    if f in ("UNAVAILABLE", "TEMPORARILY_UNAVAILABLE"):
        return "HIGH", "LOW", "NONE", [f"{action} not feasible ({f})"]
    # risk
    if action in ("RE_PEEK", "PEEK", "WIDE_SWING"):
        risk = "HIGH"
        if adv == "NUMERIC_ADVANTAGE" and need_info in ("NONE", "LOW"):
            support = "LOW"; value = "LOW"
            notes.append("dry peek while ahead with low info need")
        elif need_info in ("HIGH", "CRITICAL"):
            support = "HIGH"; value = "HIGH"
            notes.append("info-seeking peek justified by need")
    elif action in ("HOLD", "HIDE"):
        risk = "LOW"
        if adv == "NUMERIC_ADVANTAGE":
            support = "HIGH"; value = "HIGH"
            notes.append("holding preserves advantage")
        elif need_info in ("HIGH", "CRITICAL"):
            support = "LOW"; value = "LOW"
            notes.append("passive while information critical")
        else:
            support = "MEDIUM"; value = "MEDIUM"
    elif action in ("DISENGAGE", "REPOSITION"):
        risk = "LOW"
        support = "HIGH" if adv == "NUMERIC_ADVANTAGE" else "MEDIUM"
        value = "HIGH" if adv == "NUMERIC_ADVANTAGE" else "MEDIUM"
        notes.append("disengage preserves life/position")
    elif action == "FLASH":
        risk = "MEDIUM"
        support = "HIGH" if need_info in ("HIGH", "CRITICAL") else "MEDIUM"
        value = "HIGH"
        notes.append("utility creates information advantage")
    elif action == "PLANT":
        risk = "MEDIUM"; support = "HIGH"; value = "HIGH"
        notes.append("objective commitment")
    elif action == "TRADE":
        risk = "MEDIUM"; support = "MEDIUM"; value = "HIGH"
        notes.append("trade completes the kill exchange")
    return risk, support, value, notes


def _row(episode, action, source, etype, supports, contradicts,
         confidence, sample_count=None, source_version="", related=None, notes=""):
    return {
        "id": f"{episode['id']}-{source}-{action}",
        "episode_id": episode["id"],
        "candidate_action": action,
        "source": source, "type": etype,
        "supports_action": supports, "contradicts_action": contradicts,
        "confidence": round(confidence, 3), "sample_count": sample_count,
        "source_version": source_version,
        "scope": "PLAYER_KNOWN_STATE" if source in ("rule", "personal") else
                 ("GROUND_TRUTH_STATE" if source == "model" else "RETRIEVAL"),
        "notes": notes, "related_sources": related or [],
    }


def _historical(db, cfg, episode, action):
    """Similar-state retrieval for one candidate action (spec §35-§37)."""
    state = episode.get("_state") or {}
    if not state:
        return None
    try:
        cands = retrieve(db, cfg, state, mode="same_action", k=20)
    except Exception:  # noqa: BLE001
        return None
    if not cands:
        return None
    n = len(cands)
    surv = sum(1 for c in cands
               if (db.get_outcome(c["dp_id"]) or {}).get("survival"))
    rate = surv / n
    return {"n": n, "confidence": round(abs(rate - 0.5) + 0.4, 3),
            "support": rate >= 0.5,
            "note": f"{action}: survival {rate:.2f} over {n} similar states"}


def _personal(db, cfg, episode, action):
    """PersonalActionHistory: what THIS player does in similar spots."""
    player_id = episode["player_id"]
    own = db.get_decision_episodes(player_id=player_id, limit=300)
    if not own:
        return None
    similar = [e for e in own
               if e.get("family") == episode.get("family")
               and e.get("macro_context", {}).get("advantage_state")
               == episode.get("macro_context", {}).get("advantage_state")]
    if len(similar) < 3:
        return None
    n = len(similar)
    k = sum(1 for e in similar if e.get("observed_action") == action)
    rate = k / n
    return {"n": n, "confidence": 0.5,
            "support": rate >= 0.5,
            "note": f"you chose {action} {rate:.0%} in {n} similar spots"}


def _model_evidence(model_provider, episode):
    """CS-NET state-value evidence (GROUND_TRUTH_STATE only)."""
    try:
        state = episode.get("_state") or {}
        before = model_provider.predict_win_probability(state).prediction
        # after: reuse immediate_result timing — we do not have a future state
        # in this deterministic pass; store before + note.
        if before is None:
            return None
        return {
            "id": f"{episode['id']}-model-win_rate",
            "episode_id": episode["id"],
            "candidate_action": episode.get("observed_action", ""),
            "source": "model", "type": "state_value",
            "supports_action": None, "contradicts_action": None,
            "confidence": 0.7, "sample_count": None,
            "source_version": "cs-net-v3",
            "scope": "GROUND_TRUTH_STATE",
            "notes": f"win_prob before={before:.3f}",
            "related_sources": ["csnet"],
            "delta": None,
        }
    except Exception:  # noqa: BLE001
        return None
