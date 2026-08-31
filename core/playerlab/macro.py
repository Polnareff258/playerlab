"""MacroContext (V1.3 spec §22-§24): WHY this local decision matters.

Macro explains Micro: 5v4 advantage -> preserve advantage, so a dry re-peek
is high-risk/low-value. Never a standalone score — it feeds DecisionEvaluation
as context (spec §2/§3). Deterministic; no LLM; only player-known + public
information (hindsight guard: no future data).
"""
from __future__ import annotations

import math

from .config import Config
from .context import TemporalContext

ADVANTAGE_STATES = ("NUMERIC_ADVANTAGE", "EVEN", "NUMERIC_DISADVANTAGE",
                    "UNKNOWN")
RISK_TOLERANCE = ("LOW", "MEDIUM", "HIGH")
NEED_FOR_INFORMATION = ("NONE", "LOW", "MEDIUM", "HIGH", "CRITICAL")


def compute_macro_context(tc: TemporalContext, cfg: Config) -> dict:
    """Build the MacroContext for an anchor tick from TemporalContext."""
    my_team_alive = tc.team_alive
    enemy_alive = tc.enemy_alive
    diff = (my_team_alive or 0) - (enemy_alive or 0)

    if my_team_alive is None or enemy_alive is None:
        advantage_state = "UNKNOWN"
    elif diff >= 2:
        advantage_state = "NUMERIC_ADVANTAGE"
    elif diff == 1:
        advantage_state = "NUMERIC_ADVANTAGE"
    elif diff == 0:
        advantage_state = "EVEN"
    else:
        advantage_state = "NUMERIC_DISADVANTAGE"

    # objective urgency
    objective_urgency = tc.objective_urgency  # HIGH/MED/LOW (bomb + time)
    round_time = tc.round_time_s

    # need for information: when enemies are unknown and the round demands
    # knowledge (bomb not seen / not planted + time pressure or disadvantage)
    n_known = tc.n_known_enemies
    enemy_unknown = (enemy_alive or 0) - n_known
    need_info = "NONE"
    if tc.bomb_planted:
        need_info = "LOW"          # defenders must come to you; info less critical
    elif enemy_unknown <= 0:
        need_info = "NONE"
    elif round_time is not None and round_time < 15.0:
        need_info = "CRITICAL"     # must create action now
    elif advantage_state == "NUMERIC_ADVANTAGE":
        need_info = "LOW"          # ahead: the enemy must act; hold info lines
    elif advantage_state == "NUMERIC_DISADVANTAGE":
        need_info = "HIGH"
    elif advantage_state == "EVEN" and n_known <= 1:
        need_info = "HIGH"
    else:
        need_info = "MEDIUM"

    # risk tolerance: high when we must create opportunity, low when we must
    # protect a lead / objective
    risk = "MEDIUM"
    if advantage_state == "NUMERIC_ADVANTAGE" and tc.bomb_planted:
        risk = "LOW"               # enemies forced to act; preserve the lead
    elif need_info in ("HIGH", "CRITICAL"):
        risk = "HIGH"              # must gamble for information
    elif advantage_state == "NUMERIC_ADVANTAGE":
        risk = "LOW"
    elif round_time is not None and round_time < 12.0:
        risk = "HIGH"

    # team structure: roles around the player (from tc.zone_set / teammates)
    team_structure = {
        "team_alive": my_team_alive, "enemy_alive": enemy_alive,
        "alive_difference": diff,
        "nearest_teammate_dist": tc.nearest_teammate_dist,
        "teammate_contact_count": getattr(tc, "teammate_contact_count", 0),
    }

    return {
        "alive_difference": diff,
        "round_time": round_time,
        "bomb_state": {"planted": tc.bomb_planted, "site": tc.bomb_site,
                       "known": getattr(tc, "bomb_known", False)},
        "objective_urgency": objective_urgency,
        "team_structure": team_structure,
        "map_control_summary": _map_control(tc),
        "information_strength": getattr(tc, "information_strength", "NONE"),
        "information_direction": getattr(tc, "information_direction", "UNKNOWN"),
        "economic_context": None,   # not parsed in V1.3 (documented limitation)
        "advantage_state": advantage_state,
        "need_for_information": need_info,
        "risk_tolerance": risk,
    }


def _map_control(tc: TemporalContext) -> dict:
    """Coarse map control from known enemy zones (no nav in V1.3)."""
    zones = tc.known.get("known_enemy_zones", []) or []
    from collections import Counter
    enemy_zone_dist = Counter(zones)
    return {
        "enemy_zone_distribution": dict(enemy_zone_dist),
        "n_enemy_zones_known": len(enemy_zone_dist),
    }
