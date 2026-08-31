"""ResponsibilityAttribution (spec §20-§25, §54-§55).

Answers: is this failure this player's problem? Commitment alone is NOT an
excuse (spec §25): entering a commitment must itself be reasonable, otherwise
responsibility can still be SELF_DECISION (e.g., a reckless reload).
"""
from __future__ import annotations

import math

from .config import Config
from .ingest import IngestedDemo
from .context import TemporalContext
from .intent import detect_commitment
from .feasibility import action_feasibility

ATTRIBUTIONS = ("SELF_DECISION", "SELF_EXECUTION", "TEAMMATE_DECISION",
                "TEAMMATE_EXECUTION", "SHARED", "REASONABLE_BUT_LOST",
                "NOT_ACTIONABLE", "INSUFFICIENT_EVIDENCE")


def attribute_responsibility(demo: IngestedDemo, cfg: Config, tc: TemporalContext,
                             victim: int, tick: int,
                             decision_eval: str | None = None) -> dict:
    """Responsibility for a death event (victim at tick)."""
    commitment = detect_commitment(demo, cfg, victim, tick)
    feas = action_feasibility(commitment, cfg, tc)
    # how many enemies were known / near at death (from player-known state only)
    n_known = tc.n_known_enemies
    mate_dist = tc.nearest_teammate_dist
    # was the engagement (or commitment entry) reasonable?
    enemy_alive = tc.enemy_alive
    team_alive = tc.team_alive
    reasons = []

    if commitment == "PLANT_COMMITTED" or commitment == "DEFUSE_COMMITTED":
        # missed trade is not actionable (spec §22) UNLESS the commitment entry
        # itself was unreasonable: planting with known enemies very close
        if n_known >= 2 and tc.known.get("nearest_known_enemy", 9999) <= 1200.0:
            attribution = "SELF_DECISION"
            reasons.append("commitment entered with known enemies close (risky plant)")
        else:
            attribution = "NOT_ACTIONABLE"
            reasons.append(f"victim committed ({commitment}); trade unavailable")
    elif commitment == "RELOAD_COMMITTED":
        # reload is not auto-excused (spec §24): check why reload started
        if n_known >= 1 and tc.known.get("nearest_known_enemy", 9999) <= 2000.0:
            attribution = "SELF_DECISION"
            reasons.append("reload started in risky timing (enemy known close)")
        elif tc.events.get("damage_taken", 0) >= 1:
            attribution = "SELF_DECISION"
            reasons.append("reload started during active contact")
        else:
            attribution = "NOT_ACTIONABLE"
            reasons.append("reload started in a safe window; death not self-attributable")
    elif commitment in ("UTILITY_COMMITTED",):
        attribution = "NOT_ACTIONABLE" if n_known < 2 else "SELF_DECISION"
        reasons.append("utility commitment constrained engagement" if n_known < 2
                       else "utility thrown while engaging multiple known enemies")
    elif commitment == "ENGAGEMENT_COMMITTED":
        if mate_dist is None or mate_dist > 1600.0:
            attribution = "SELF_DECISION" if n_known >= 1 else "INSUFFICIENT_EVIDENCE"
            reasons.append("isolated engagement (no trade support)")
        else:
            attribution = "SELF_EXECUTION" if decision_eval == "REASONABLE" else "SELF_DECISION"
            reasons.append("traded engagement; outcome depends on execution")
    else:  # FREE or UNKNOWN
        if team_alive >= 1 and mate_dist is not None and mate_dist > 1600.0:
            attribution = "SELF_DECISION"
            reasons.append("chose an unsupported fight while free")
        elif decision_eval in ("REASONABLE", "QUESTIONABLE"):
            attribution = "REASONABLE_BUT_LOST"
            reasons.append("decision reasonable; outcome negative")
        elif decision_eval == "POOR":
            attribution = "SELF_DECISION"
            reasons.append("poor decision evaluated at death")
        else:
            attribution = "INSUFFICIENT_EVIDENCE"
            reasons.append("insufficient context to attribute")

    # teammate-driven loss: victim was fine but teammate(s) collapsed elsewhere —
    # approximated: victim committed & teammate died unsupported in same round
    if commitment in ("PLANT_COMMITTED", "DEFUSE_COMMITTED", "FREE") and enemy_alive <= team_alive:
        pass  # keep primary attribution; SHARED case below

    conf = 0.55 + 0.1 * min(1.0, n_known / 2) + (0.1 if mate_dist is not None else 0)
    conf = min(0.9, conf)
    if attribution == "INSUFFICIENT_EVIDENCE":
        conf = 0.4
    # team-level context (spec §23): was a teammate committed to plant/defuse at
    # the death tick? A free player taking an unsupported fight while a teammate
    # is committed shifts round-level responsibility toward that player's error
    # (TEAMMATE_DECISION from the committed player's perspective / SHARED).
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
    return {
        "attribution": attribution, "confidence": round(conf, 3),
        "commitment": commitment, "reasons": reasons,
        "team_level": team_level,
        "feasibility": {k: v for k, v in feas.items()
                        if v in ("TEMPORARILY_UNAVAILABLE", "UNAVAILABLE")},
    }
