"""Alpha bottleneck ranking (spec §9): components Frequency / Impact /
Confidence / Trainability computed deterministically, output reduced to
HIGH / MEDIUM / LOW with an explainable breakdown. Patterns that do not
meet eligibility (min samples, min confidence) can never produce a target.
"""
from __future__ import annotations

from .config import Config
from .db import DB

LEVELS = ("HIGH", "MEDIUM", "LOW")


def _level(freq, impact, conf, train) -> str:
    if freq >= 0.5 and conf >= 0.6 and train >= 0.7:
        return "HIGH"
    if freq >= 0.3 and conf >= 0.4:
        return "MEDIUM"
    return "LOW"


def rank_bottlenecks(db: DB, cfg: Config, matches_count: int) -> list[dict]:
    """Rank patterns (from the patterns table) with an explainable breakdown."""
    out = []
    for p in db.get_patterns():
        ptype = p["pattern_type"]
        n = p["sample_count"]
        matches = max(1, matches_count)
        freq = min(1.0, (p["opportunity_count"] / max(1, matches)) / 6.0)
        neg_share = p["negative_examples"] / n if n else 0.0
        impact = min(1.0, (p["violation_count"] / max(1, matches)) / 3.0) * (0.5 + 0.5 * neg_share)
        conf = p["confidence"]
        train = cfg.trainability.get(ptype, 0.5)
        eligible = (n >= cfg.min_pattern_samples and conf >= cfg.min_pattern_confidence
                    and train >= 0.5)
        out.append({
            "pattern_id": p["pattern_id"], "pattern_type": ptype, "name": p["name"],
            "category": p["category"],
            "frequency": round(freq, 3), "impact": round(impact, 3),
            "confidence": round(conf, 3), "trainability": train,
            "level": _level(freq, impact, conf, train) if eligible else "LOW",
            "eligible": eligible,
            "breakdown": {"per_match_opportunities": round(p["opportunity_count"] / matches, 2),
                          "violation_rate": p["violation_rate"],
                          "negative_share": round(neg_share, 3),
                          "counterfactual_support": p["counterfactual_support"]},
        })
    out.sort(key=lambda b: (b["eligible"], {"HIGH": 3, "MEDIUM": 2, "LOW": 1}[b["level"]]),
             reverse=True)
    return out
