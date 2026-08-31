"""Decision Episode Pattern aggregation (V1.3 spec §42-§44, §53-§54).

Pattern is the aggregation of multiple DecisionEpisodes — never the reverse.
Deterministic grouping: family x advantage_state x observed action bucket,
then TrainingTarget links via the Actionability gate (spec §64).
"""
from __future__ import annotations

from .config import Config
from .db import DB

# pattern definitions: family + trigger → what counts as a violation
PATTERN_SPECS = {
    "OVER_REPEEK_AFTER_NEUTRAL_CONTACT": {
        "family": "CONTACT_RESPONSE",
        "name": "Over re-peek after neutral contact",
        "undesired": "Immediate same-angle re-peek with no advantage/info",
        "replacement": "Hold / disengage / utility reset",
        "trigger": "First contact without advantage",
        "macro_reason": "When even or ahead, re-peeking the same angle rarely "
                        "gains new information and risks the positional lead.",
    },
    "DRY_PEEK_WITH_ADVANTAGE": {
        "family": "ADVANTAGE_PRESERVATION",
        "name": "Dry peek while holding numeric advantage",
        "undesired": "Forcing an unnecessary duel at 5v4+",
        "replacement": "Preserve spacing, hold info lines",
        "trigger": "Team gains alive advantage",
        "macro_reason": "The enemy must create action when you hold the "
                        "advantage; dry peeking converts a lead into a coin flip.",
    },
    "UNSUPPORTED_OBJECTIVE_PUSH": {
        "family": "OBJECTIVE_COMMITMENT",
        "name": "Unsupported objective push",
        "undesired": "Pushing the objective without trade support",
        "replacement": "Wait for trade structure / use utility",
        "trigger": "Plant / defuse opportunity",
        "macro_reason": "Committing to the objective without support turns a "
                        "free plant into a risky one.",
    },
}


def cluster_episodes(db: DB, cfg: Config, match_id: str | None = None) -> list[dict]:
    """Deterministic grouping of DecisionEpisodes into repeated patterns."""
    eps = db.get_decision_episodes(match_id=match_id, limit=2000)
    patterns = []
    for pid, spec in PATTERN_SPECS.items():
        fam = spec["family"]
        fam_eps = [e for e in eps if e["family"] == fam]
        if len(fam_eps) < cfg.min_pattern_samples:
            patterns.append({
                "pattern_id": pid, "family": fam, "name": spec["name"],
                "sample_count": len(fam_eps), "violation_rate": None,
                "actionability_share": 0.0, "confidence": 0.0,
                "eligible": False, "breakdown": {"n_episodes": len(fam_eps)},
                "trigger": spec["trigger"], "undesired": spec["undesired"],
                "replacement": spec["replacement"], "macro_reason": spec["macro_reason"],
            })
            continue
        # violations: episodes whose evaluation is QUESTIONABLE/POOR and whose
        # observed action matches the pattern's undesired behavior, gated by
        # actionability (spec §64: only player-controlled repeatable ones count)
        undesired_actions = {
            "OVER_REPEEK_AFTER_NEUTRAL_CONTACT": ("RE_PEEK", "PEEK"),
            "DRY_PEEK_WITH_ADVANTAGE": ("PEEK", "RE_PEEK"),
            "UNSUPPORTED_OBJECTIVE_PUSH": ("PEEK", "REPOSITION"),
        }[pid]
        violations = 0
        actionable = 0
        for e in fam_eps:
            if e["actionability"] in ("HIGHLY_ACTIONABLE", "ACTIONABLE"):
                actionable += 1
            if e["observed_action"] in undesired_actions and \
                    e["decision_evaluation"] in ("QUESTIONABLE", "POOR"):
                violations += 1
        n = len(fam_eps)
        rate = violations / n
        breakdown = {
            "n_episodes": n,
            "n_violations": violations,
            "n_actionable": actionable,
            "evaluation_dist": _eval_dist(fam_eps),
            "actionability_dist": _actionability_dist(fam_eps),
            "observed_dist": _observed_dist(fam_eps),
        }
        patterns.append({
            "pattern_id": pid, "family": fam, "name": spec["name"],
            "sample_count": n, "violation_rate": round(rate, 3),
            "actionability_share": round(actionable / n, 3),
            "confidence": round(0.5 + 0.3 * min(1.0, n / 20), 3),
            "eligible": rate >= 0.3 and actionable >= 3,
            "breakdown": breakdown,
            "trigger": spec["trigger"], "undesired": spec["undesired"],
            "replacement": spec["replacement"], "macro_reason": spec["macro_reason"],
        })
    return patterns


def _eval_dist(eps: list[dict]) -> dict:
    from collections import Counter
    return dict(Counter(e.get("decision_evaluation", "?") for e in eps))


def _actionability_dist(eps: list[dict]) -> dict:
    from collections import Counter
    return dict(Counter(e.get("actionability", "?") for e in eps))


def _observed_dist(eps: list[dict]) -> dict:
    from collections import Counter
    return dict(Counter(e.get("observed_action", "?") for e in eps))
