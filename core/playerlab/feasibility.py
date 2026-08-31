"""ActionFeasibility rule engine (spec §6-§8, §45).

Candidate actions each carry a feasibility state. "Can press the key" is NOT
feasibility: commitment, objective cost, timing, exposure, bomb and round time
all constrain the action space.
"""
from __future__ import annotations

from .config import Config
from .context import TemporalContext

STATUSES = ("FEASIBLE", "FEASIBLE_HIGH_COST", "CONSTRAINED",
            "TEMPORARILY_UNAVAILABLE", "UNAVAILABLE", "UNKNOWN")

CANDIDATES = ("CONTINUE_PLANT", "CANCEL_PLANT", "IMMEDIATE_TRADE", "USE_UTILITY",
              "REPOSITION", "SHOOT", "RELOAD", "CANCEL_RELOAD", "CONTINUE_DEFUSE",
              "CANCEL_DEFUSE", "CONTINUE_ENGAGE", "DISENGAGE", "CANCEL_UTILITY",
              "ROTATE", "HOLD")


def action_feasibility(commitment: str, cfg: Config, tc: TemporalContext) -> dict:
    base = {c: "UNKNOWN" for c in CANDIDATES}
    for c in CANDIDATES:
        base[c] = "FEASIBLE"  # default for FREE state

    if commitment == "PLANT_COMMITTED":
        base.update({
            "CONTINUE_PLANT": "FEASIBLE", "CANCEL_PLANT": "FEASIBLE_HIGH_COST",
            "IMMEDIATE_TRADE": "TEMPORARILY_UNAVAILABLE", "USE_UTILITY": "CONSTRAINED",
            "REPOSITION": "UNAVAILABLE", "SHOOT": "CONSTRAINED", "ROTATE": "UNAVAILABLE",
            "HOLD": "UNAVAILABLE",
        })
    elif commitment == "DEFUSE_COMMITTED":
        base.update({
            "CONTINUE_DEFUSE": "FEASIBLE", "CANCEL_DEFUSE": "FEASIBLE_HIGH_COST",
            "SHOOT": "CONSTRAINED", "IMMEDIATE_TRADE": "TEMPORARILY_UNAVAILABLE",
            "REPOSITION": "UNAVAILABLE", "ROTATE": "UNAVAILABLE",
        })
    elif commitment == "RELOAD_COMMITTED":
        base.update({
            "SHOOT": "TEMPORARILY_UNAVAILABLE", "CANCEL_RELOAD": "FEASIBLE_HIGH_COST",
            "REPOSITION": "CONSTRAINED", "IMMEDIATE_TRADE": "TEMPORARILY_UNAVAILABLE",
            "USE_UTILITY": "CONSTRAINED",
        })
    elif commitment == "UTILITY_COMMITTED":
        base.update({
            "CANCEL_UTILITY": "FEASIBLE_HIGH_COST", "SHOOT": "CONSTRAINED",
            "IMMEDIATE_TRADE": "CONSTRAINED", "REPOSITION": "FEASIBLE",
            "CONTINUE_ENGAGE": "CONSTRAINED",
        })
    elif commitment == "ENGAGEMENT_COMMITTED":
        base.update({
            "CONTINUE_ENGAGE": "FEASIBLE", "DISENGAGE": "FEASIBLE_HIGH_COST",
            "USE_UTILITY": "CONSTRAINED", "REPOSITION": "CONSTRAINED",
            "IMMEDIATE_TRADE": "FEASIBLE", "HOLD": "FEASIBLE",
        })
    elif commitment == "DISENGAGE_COMMITTED":
        base.update({"CONTINUE_ENGAGE": "FEASIBLE_HIGH_COST", "DISENGAGE": "FEASIBLE",
                     "HOLD": "FEASIBLE_HIGH_COST"})
    elif commitment == "SAVE_COMMITTED":
        base.update({"SHOOT": "CONSTRAINED", "CONTINUE_ENGAGE": "TEMPORARILY_UNAVAILABLE",
                     "IMMEDIATE_TRADE": "TEMPORARILY_UNAVAILABLE"})
    elif commitment == "PLANT_INTENT" or commitment == "DEFUSE_INTENT":
        base["IMMEDIATE_TRADE"] = "CONSTRAINED"

    if tc.objective_urgency == "HIGH" and commitment not in ("PLANT_COMMITTED", "DEFUSE_COMMITTED"):
        base["ROTATE"] = "FEASIBLE"
    if tc.enemy_alive == 0:
        for c in ("SHOOT", "IMMEDIATE_TRADE", "CONTINUE_ENGAGE"):
            base[c] = "UNAVAILABLE"
    return {k: v for k, v in base.items() if v != "UNKNOWN"}
