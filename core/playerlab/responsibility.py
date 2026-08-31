"""ResponsibilityAttribution V1.2.1 (spec §11-§15, §51-§53).

V1.2.1 principle: 宁可输出 INSUFFICIENT_EVIDENCE，也不要轻易归责。

SELF_DECISION requires ALL FOUR gates (spec §13):
    Evidence sufficient            AND
    Action feasible                AND
    Alternative realistically available  AND
    Failure causally related

Otherwise prefer SHARED / NOT_ACTIONABLE / INSUFFICIENT_EVIDENCE.
Responsibility is NOT decided from distance alone (spec §12): tradeability,
commitment reasonableness, known-state, situational role, objective urgency
and support path all participate. Outcome is never an input (spec §52-§53).
"""
from __future__ import annotations

from .config import Config
from .ingest import IngestedDemo
from .context import TemporalContext
from .intent import detect_commitment
from .feasibility import action_feasibility
from .tradeability import compute_tradeability, NULL_GEOMETRY

ATTRIBUTIONS = ("SELF_DECISION", "SELF_EXECUTION", "TEAMMATE_DECISION",
                "TEAMMATE_EXECUTION", "SHARED", "REASONABLE_BUT_LOST",
                "NOT_ACTIONABLE", "INSUFFICIENT_EVIDENCE")


def attribute_responsibility(demo: IngestedDemo, cfg: Config, tc: TemporalContext,
                             victim: int, tick: int,
                             decision_eval: str | None = None) -> dict:
    """Responsibility for a death event (victim at tick). Conservative gate."""
    commitment = detect_commitment(demo, cfg, victim, tick)
    feas = action_feasibility(commitment, cfg, tc)
    tc.feasibility = feas  # let tradeability read the feasibility state
    trade = compute_tradeability(tc, cfg, NULL_GEOMETRY)
    n_known = tc.n_known_enemies
    mate_dist = tc.nearest_teammate_dist
    info = getattr(tc, "information_strength", "NONE")
    reasons = []

    # ---- gate evidence ------------------------------------------------
    gate = {"evidence_sufficient": False, "action_feasible": False,
            "alternative_available": False, "causally_related": False}

    # Evidence: we know what the player chose AND the state around the death.
    # A free player with no known enemies and no engagement events lacks evidence.
    # FREE is a *default* state, not evidence of a meaningful choice (V1.2.1 §13).
    had_choice_evidence = bool(
        commitment not in ("FREE", "UNKNOWN")
        or tc.events.get("damage_taken", 0) >= 1
        or tc.events.get("shots", 0) >= 1
        or tc.events.get("damage_dealt", 0) >= 1
        or n_known >= 1)
    gate["evidence_sufficient"] = had_choice_evidence
    if not had_choice_evidence:
        reasons.append("no evidence the player made a meaningful choice (free, no contact)")

    # Feasibility: was an alternative action actually feasible?
    alt_feasible = any(v not in ("UNAVAILABLE", "TEMPORARILY_UNAVAILABLE")
                       for k, v in feas.items() if k in (
                           "DISENGAGE", "REPOSITION", "CANCEL_PLANT",
                           "CANCEL_DEFUSE", "CANCEL_RELOAD", "CANCEL_UTILITY"))
    gate["action_feasible"] = alt_feasible
    if not alt_feasible:
        reasons.append("no feasible alternative action at the death tick")

    # Alternative realistically available: the player had a non-doomed path.
    gate["alternative_available"] = (
        decision_eval in ("REASONABLE", "QUESTIONABLE", "POOR")
        or (n_known >= 1 and info in ("MEDIUM", "STRONG", "CONFIRMED")))

    # Causally related: the failed outcome traces to the player's own choice.
    # Reload in contact, risky plant with enemies close, dry peek with known
    # enemies and no trade support are the causally-relatable patterns.
    causally_related = _causally_related(demo, cfg, tc, commitment, decision_eval)
    gate["causally_related"] = causally_related
    if not causally_related:
        reasons.append("failure not clearly caused by this player's decision")

    # ---- attribution ------------------------------------------------------
    attribution = "INSUFFICIENT_EVIDENCE"
    if commitment in ("PLANT_COMMITTED", "DEFUSE_COMMITTED"):
        # spec §14 example 1: committed planter who cannot trade -> NOT_ACTIONABLE
        if trade["classification"] in ("UNAVAILABLE", "UNKNOWN", "LOW") and not causally_related:
            attribution = "NOT_ACTIONABLE"
            reasons.append(f"victim committed ({commitment}); trade {trade['classification']}; failure not self-caused")
        elif causally_related and _risky_commitment_entry(cfg, tc, commitment):
            attribution = "SELF_DECISION"
            reasons.append("commitment entered despite known enemies close (risky entry)")
        else:
            attribution = "NOT_ACTIONABLE"
            reasons.append(f"victim committed ({commitment}); trade unavailable")
    elif commitment == "RELOAD_COMMITTED":
        # spec §15: reload is not an excuse; reloading in a risky window is a
        # SELF_DECISION even if it caused the death.
        if causally_related:
            attribution = "SELF_DECISION"
            reasons.append("reload started in a risky window (contact / enemy known close)")
        else:
            attribution = "NOT_ACTIONABLE"
            reasons.append("reload in a safe window; death not self-attributable")
    elif commitment == "ENGAGEMENT_COMMITTED":
        if trade["classification"] in ("HIGH", "MEDIUM") and gate["action_feasible"]:
            # teammate can trade -> the death is a team-level/execution issue,
            # NOT a unilateral bad decision (spec §74-B: support is real)
            if decision_eval == "REASONABLE":
                attribution = "SELF_EXECUTION"
                reasons.append(f"traded engagement (tradeability {trade['classification']}); execution outcome")
            elif decision_eval == "POOR":
                attribution = "SELF_DECISION"
                reasons.append("poor decision evaluated even though tradeable")
            else:
                attribution = "SHARED"
                reasons.append(f"traded engagement (tradeability {trade['classification']}); shared outcome")
        elif causally_related and gate["evidence_sufficient"]:
            attribution = "SELF_DECISION"
            reasons.append("unsupported engagement entered with known enemies")
        elif not gate["evidence_sufficient"]:
            attribution = "INSUFFICIENT_EVIDENCE"
            reasons.append("engagement but insufficient evidence of a bad choice")
        else:
            attribution = "SHARED"
            reasons.append("engagement without support; shared round context")
    elif commitment in ("UTILITY_COMMITTED",):
        attribution = "NOT_ACTIONABLE" if not causally_related else "SELF_DECISION"
        reasons.append("utility commitment constrained engagement" if not causally_related
                       else "utility thrown while engaging multiple known enemies")
    else:  # FREE / UNKNOWN / DISENGAGE / SAVE
        if all(gate.values()):
            attribution = "SELF_DECISION"
            reasons.append("free player chose an unsupported fight with feasible alternatives")
        elif decision_eval in ("REASONABLE", "QUESTIONABLE") and gate["evidence_sufficient"]:
            attribution = "REASONABLE_BUT_LOST"
            reasons.append("decision reasonable; outcome negative")
        elif gate["evidence_sufficient"] and not gate["alternative_available"]:
            attribution = "NOT_ACTIONABLE"
            reasons.append("no realistic alternative; not actionable")
        elif gate["evidence_sufficient"]:
            attribution = "SHARED"
            reasons.append("partial evidence; shared responsibility")
        else:
            attribution = "INSUFFICIENT_EVIDENCE"
            reasons.append("insufficient context to attribute")

    # team-level context (spec §23)
    team_level = None
    teams = {p["steamid"]: p["team_number"] for p in demo.players}
    my_team = teams.get(victim, -1)
    mate_committed = any(
        s != victim and teams.get(s) == my_team and detect_commitment(demo, cfg, s, tick)
        in ("PLANT_COMMITTED", "DEFUSE_COMMITTED")
        for s in teams)
    if mate_committed and attribution == "SELF_DECISION":
        team_level = "TEAMMATE_DECISION_SHARED"
    elif mate_committed:
        team_level = "SHARED"

    # confidence: gated attribution is more defensible
    conf = _confidence(attribution, gate, n_known, trade)
    return {
        "attribution": attribution, "confidence": round(conf, 3),
        "commitment": commitment, "reasons": reasons,
        "team_level": team_level,
        "gate": {k: bool(v) for k, v in gate.items()},
        "tradeability": {k: trade[k] for k in
                         ("classification", "score", "confidence", "direct_distance",
                          "nav_distance", "direct_los", "estimated_response_time",
                          "same_engagement_lane")},
        "feasibility": {k: v for k, v in feas.items()
                        if v in ("TEMPORARILY_UNAVAILABLE", "UNAVAILABLE")},
    }


def _causally_related(demo, cfg, tc, commitment, decision_eval) -> bool:
    """Was the death plausibly caused by this player's own decision?"""
    if commitment == "RELOAD_COMMITTED":
        # reloading while damage incoming / enemy known close is self-caused
        if tc.events.get("damage_taken", 0) >= 1:
            return True
        nk = tc.known.get("nearest_known_enemy", 9999)
        return tc.n_known_enemies >= 1 and nk <= cfg.reload_risk_known_enemy_dist
    if commitment in ("PLANT_COMMITTED", "DEFUSE_COMMITTED"):
        # risky entry: planted with known enemies very close
        nk = tc.known.get("nearest_known_enemy", 9999)
        return tc.n_known_enemies >= 2 and nk <= cfg.risk_plant_known_enemy_dist
    if commitment == "ENGAGEMENT_COMMITTED":
        # entered an unsupported fight while free-ish (no trade support)
        return tc.n_known_enemies >= 1
    if commitment in ("UTILITY_COMMITTED",):
        return tc.n_known_enemies >= 2
    # FREE: dry peek with known enemies and no support
    if decision_eval == "POOR":
        return True
    if tc.n_known_enemies >= 1:
        nk = tc.known.get("nearest_known_enemy", 9999)
        if nk <= cfg.dry_peek_known_enemy_dist:
            return True
    return False


def _risky_commitment_entry(cfg, tc, commitment) -> bool:
    nk = tc.known.get("nearest_known_enemy", 9999)
    if commitment == "PLANT_COMMITTED":
        return tc.n_known_enemies >= 2 and nk <= cfg.risk_plant_known_enemy_dist
    if commitment == "DEFUSE_COMMITTED":
        return tc.n_known_enemies >= 1 and nk <= cfg.dry_peek_known_enemy_dist
    return False


def _confidence(attribution, gate, n_known, trade) -> float:
    if attribution == "INSUFFICIENT_EVIDENCE":
        return 0.4
    if attribution == "NOT_ACTIONABLE":
        return 0.6
    if attribution == "SHARED":
        return 0.55
    if attribution == "SELF_DECISION":
        # gated decisions are confident only when the gate is fully open
        if all(gate.values()):
            return min(0.85, 0.6 + 0.1 * min(1.0, n_known / 2)
                       + (0.05 if trade["confidence"] and trade["confidence"] >= 0.5 else 0.0))
        return 0.5
    return 0.6
