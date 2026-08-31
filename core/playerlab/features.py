"""StateFeatureVector, Hard Filters and weighted soft similarity.

Per COUNTERFACTUAL_DESIGN §4/§9: numeric features are normalized 0..1,
weights are configurable (config/features.json) and ablations run them in
subsets. Decision-layer features derive from PlayerKnownState + public info
only — never from ground-truth enemy positions (hindsight guard).
"""
from __future__ import annotations

import math

from .config import Config

NUMERIC_FEATURES = [
    "time_left", "alive_diff", "hp", "n_known_enemies", "known_spread",
    "nearest_known_enemy", "recent_contact", "teammate_near", "teammate_mid",
    "bomb_planted", "economy", "time_pressure",
]
CATEGORICAL_LABELS = ["map", "side", "zone", "weapon_class", "action"]


def _clamp01(x) -> float:
    if x is None:
        return 0.5  # missing data = neutral (documented)
    try:
        if math.isnan(float(x)):
            return 0.5
    except (TypeError, ValueError):
        return 0.5
    return max(0.0, min(1.0, float(x)))


def build_features(known: dict, public: dict, cfg: Config,
                   map_name: str, side: str, zone: str,
                   action: str, recent_contact: bool,
                   teammate_near: int, teammate_mid: int,
                   team_alive: int, enemy_alive: int) -> tuple[dict, dict]:
    """Returns (numeric_features, categorical_labels)."""
    remaining = public.get("time_remaining_s") or 0.0
    features = {
        "time_left": _clamp01(remaining / 115.0),
        "alive_diff": _clamp01((team_alive - enemy_alive + 5.0) / 10.0),
        "hp": _clamp01((known.get("own") or {}).get("hp", 100) / 100.0),
        "n_known_enemies": _clamp01((known.get("n_known_enemies") or 0) / 5.0),
        "known_spread": _clamp01((known.get("known_spread") or 0) / 5000.0),
        "nearest_known_enemy": _clamp01((known.get("nearest_known_enemy") or 4000) / 4000.0),
        "recent_contact": 1.0 if recent_contact else 0.0,
        "teammate_near": _clamp01(teammate_near / 4.0),
        "teammate_mid": _clamp01(teammate_mid / 4.0),
        "bomb_planted": 1.0 if (public.get("bomb") or {}).get("planted_site") else 0.0,
        "economy": _clamp01(((known.get("own") or {}).get("money") or 0) / 16000.0),
        "time_pressure": 1.0 if remaining < 15.0 else 0.0,
    }
    labels = {"map": map_name, "side": side, "zone": zone,
              "weapon_class": (known.get("own") or {}).get("weapon_class", "unknown"),
              "action": action}
    return features, labels


def hard_match(q_labels: dict, c_labels: dict, cfg: Config) -> bool:
    """Map/side/zone must match (when known on both sides)."""
    if cfg.hard_filter_map and q_labels.get("map") and c_labels.get("map"):
        if q_labels["map"] != c_labels["map"]:
            return False
    if cfg.hard_filter_side and q_labels.get("side") and c_labels.get("side"):
        if q_labels["side"] != c_labels["side"]:
            return False
    if cfg.hard_filter_zone and q_labels.get("zone") and c_labels.get("zone"):
        if q_labels["zone"] != c_labels["zone"]:
            return False
    return True


def soft_score(q_features: dict, c_features: dict,
               q_labels: dict, c_labels: dict, cfg: Config) -> float:
    """Weighted similarity in [0, 1]. Categorical weapon_class scores equality."""
    weights = cfg.soft_weights
    num_w = sum(v for k, v in weights.items() if k in NUMERIC_FEATURES and k in q_features and k in c_features)
    total = num_w + weights.get("weapon_class", 0.0)
    if total <= 0:
        return 0.0
    score = 0.0
    for k in NUMERIC_FEATURES:
        w = weights.get(k)
        if w and k in q_features and k in c_features:
            score += w * (1.0 - min(1.0, abs(q_features[k] - c_features[k])))
    if "weapon_class" in q_labels and "weapon_class" in c_labels:
        score += weights.get("weapon_class", 0.0) * (1.0 if q_labels["weapon_class"] == c_labels["weapon_class"] else 0.0)
    return score / total
