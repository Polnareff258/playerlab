"""DecisionEvaluation + Actionability (V1.3 spec §14-§21, §64).

DecisionEvaluation answers "was this local choice reasonable given the
context, feasible alternatives and evidence?" — GOOD / REASONABLE /
QUESTIONABLE / POOR / INSUFFICIENT_EVIDENCE. Outcome is NEVER an input
(spec §19, §56): good outcome != good decision, bad outcome != bad decision.

Actionability answers "should this become this player's own training
target?" — HIGHLY_ACTIONABLE / ACTIONABLE / WEAKLY_ACTIONABLE /
NOT_ACTIONABLE / INSUFFICIENT_EVIDENCE. Gate (spec §64): evidence sufficient
AND repeatable opportunity AND player-controlled.

ResponsibilityAttribution is NOT used here (spec §16): it degrades to a
debug/evidence field elsewhere.
"""
from __future__ import annotations

from .config import Config
from .episode import ACTIONABILITY_LEVELS

EVALUATIONS = ("GOOD", "REASONABLE", "QUESTIONABLE", "POOR", "INSUFFICIENT_EVIDENCE")


def evaluate_decision(episode: dict, cfg: Config,
                      candidate_evidence: dict | None = None) -> str:
    """Deterministic evaluation over context + feasible alternatives + evidence.

    candidate_evidence: {action: {"risk": LOW/MED/HIGH, "support": LOW/MED/HIGH,
    "value": LOW/MED/HIGH}} — populated by evidence.py (Phase E).
    """
    macro = episode.get("macro_context") or {}
    local = episode.get("local_context") or {}
    fe = episode.get("feasibility") or {}
    observed = episode.get("observed_action", "HOLD")
    commitment = episode.get("commitment_state", "FREE")
    candidates = episode.get("_candidates") or []
    evidence = candidate_evidence or {}

    # feasibility of the observed action
    obs_feas = fe.get(observed, "FEASIBLE")
    if obs_feas in ("UNAVAILABLE", "TEMPORARILY_UNAVAILABLE"):
        # the player did something infeasible -> at least QUESTIONABLE
        if _has_supporting_evidence(evidence, observed):
            return "REASONABLE"  # special case: forced by commitment
        return "QUESTIONABLE"

    # INSUFFICIENT_EVIDENCE when we lack the basics
    if not macro.get("advantage_state") or macro.get("advantage_state") == "UNKNOWN":
        if not evidence:
            return "INSUFFICIENT_EVIDENCE"

    risk_tol = macro.get("risk_tolerance", "MEDIUM")
    need_info = macro.get("need_for_information", "NONE")
    adv_state = macro.get("advantage_state", "EVEN")

    # risk of the observed action vs the context's risk tolerance
    obs_risk = (evidence.get(observed) or {}).get("risk", "MEDIUM")
    obs_support = (evidence.get(observed) or {}).get("support", "UNKNOWN")
    obs_value = (evidence.get(observed) or {}).get("value", "LOW")

    score = 0.0
    reasons = []

    # -- risk vs tolerance (spec §22-§24) --
    if obs_risk == "HIGH" and risk_tol == "LOW":
        score -= 2.0
        reasons.append("high-risk action in a low-risk-tolerance context")
    elif obs_risk == "HIGH" and risk_tol == "HIGH":
        score += 0.5
        reasons.append("high risk justified by high risk tolerance (must create action)")
    elif obs_risk == "LOW" and risk_tol == "HIGH":
        score += 0.5
        reasons.append("low-risk action in an aggressive context")

    # -- information need (spec §24) --
    if need_info in ("HIGH", "CRITICAL"):
        if observed in ("PEEK", "HIDE", "REPOSITION"):
            score += 1.0
            reasons.append(f"information need {need_info} justifies info-seeking")
        elif observed in ("HOLD",) and need_info == "CRITICAL":
            score -= 1.0
            reasons.append("passive hold while information is critical")
    elif need_info in ("NONE", "LOW"):
        if observed in ("PEEK", "RE_PEEK") and risk_tol == "LOW":
            score -= 1.0
            reasons.append("unnecessary peek with low information need")
        if observed in ("HOLD", "HIDE") and adv_state == "NUMERIC_ADVANTAGE":
            score += 0.5
            reasons.append("holding preserves the numeric advantage")

    # -- advantage preservation (spec §20) --
    if adv_state == "NUMERIC_ADVANTAGE":
        if observed in ("RE_PEEK", "PEEK") and need_info in ("NONE", "LOW"):
            score -= 1.5
            reasons.append("forcing a duel while holding numeric advantage")
        if observed in ("HOLD", "HIDE", "DISENGAGE"):
            score += 1.0
            reasons.append("preserving advantage has high strategic value")
    if adv_state == "NUMERIC_DISADVANTAGE":
        if observed in ("HOLD", "HIDE") and need_info in ("HIGH", "CRITICAL"):
            score -= 0.5
            reasons.append("passivity while behind and needing information")
        if observed in ("PEEK", "REPOSITION"):
            score += 0.5
            reasons.append("creating opportunity while behind")

    # -- commitment constraints (spec §11/§13) --
    if commitment in ("PLANT_COMMITTED", "DEFUSE_COMMITTED"):
        if observed in ("PEEK", "RE_PEEK", "TRADE"):
            score -= 1.0
            reasons.append("action conflicts with objective commitment")
        elif observed in ("HOLD", "PLANT"):
            score += 1.0
            reasons.append("action consistent with the commitment")

    # -- evidence support (Phase E) --
    if obs_support == "HIGH":
        score += 1.0
        reasons.append("historical evidence supports this action")
    elif obs_support == "LOW":
        score -= 1.0
        reasons.append("historical evidence does not support this action")

    # -- decision vs execution (spec §62-§63): outcome-free, but we keep the
    #    execution channel separate — evaluation here is decision-only.

    if score >= 2.0:
        return "GOOD"
    if score >= 0.5:
        return "REASONABLE"
    if score >= -0.5:
        return "QUESTIONABLE"
    return "POOR"


def _has_supporting_evidence(evidence: dict, action: str) -> bool:
    e = evidence.get(action) or {}
    return bool(e.get("support") or e.get("value"))


def actionability(episode: dict, cfg: Config,
                  evidence_sufficient: bool | None = None) -> str:
    """Actionability gate (spec §14-§15, §64)."""
    macro = episode.get("macro_context") or {}
    local = episode.get("local_context") or {}
    observed = episode.get("observed_action", "HOLD")
    commitment = episode.get("commitment_state", "FREE")

    # NOT_ACTIONABLE: uncontrollable / commitment-forced
    if commitment in ("PLANT_COMMITTED", "DEFUSE_COMMITTED") and \
            observed in ("HOLD", "PLANT", "TRADE"):
        return "NOT_ACTIONABLE"
    if observed == "TRADE" and commitment in ("PLANT_COMMITTED", "DEFUSE_COMMITTED"):
        return "NOT_ACTIONABLE"

    # evidence sufficiency
    if evidence_sufficient is None:
        evidence_sufficient = _evidence_basics_present(episode)
    if not evidence_sufficient:
        return "INSUFFICIENT_EVIDENCE"

    # player-controlled + repeatable (context-dependent defaults)
    repeatable = macro.get("advantage_state") not in ("UNKNOWN",)
    player_controlled = observed not in ("TRADE",) or local.get("nearby_teammates")

    if not (repeatable and player_controlled):
        return "WEAKLY_ACTIONABLE"

    # strength
    need_info = macro.get("need_for_information", "NONE")
    if observed in ("RE_PEEK", "PEEK") and need_info in ("NONE", "LOW") and \
            macro.get("advantage_state") == "NUMERIC_ADVANTAGE":
        return "HIGHLY_ACTIONABLE"
    if observed in ("RE_PEEK", "PEEK", "DISENGAGE", "HIDE"):
        return "ACTIONABLE"
    return "WEAKLY_ACTIONABLE"


def _evidence_basics_present(episode: dict) -> bool:
    """Do we have enough context to judge? KnownState present + macro computed."""
    ks = episode.get("player_known_state") or {}
    macro = episode.get("macro_context") or {}
    return bool(ks and macro.get("advantage_state"))
