"""InformationStrength / InformationDirection (V1.2.1 spec §3-§4).

Deterministic, LLM-free combination of the player's epistemic signals:
visual confirmation, damage events, bomb confirmation, recent teammate
contact, public kill/death information, sound info — each with time decay.

InformationStrength levels: NONE < WEAK < MEDIUM < STRONG < CONFIRMED.
InformationDirection: A_SIDE / B_SIDE / MID / UNKNOWN (aggregated from the
player-known enemy positions; the map-zone mapping comes from zones.py).

Design rules:
- No ground-truth/omniscient data may enter (hindsight guard, spec §34).
- CONFIRMED is reserved for signals that cannot be wrong (own vision of a
  living enemy right now / bomb plant public info).
- Time decay: strength decays with the age of the last update; stale info
  (< strength floor) collapses to NONE rather than lingering as WEAK.
"""
from __future__ import annotations

import math
from enum import Enum

STRENGTH_LEVELS = ("NONE", "WEAK", "MEDIUM", "STRONG", "CONFIRMED")
DIRECTIONS = ("A_SIDE", "B_SIDE", "MID", "UNKNOWN")


class InformationStrength(Enum):
    NONE = 0
    WEAK = 1
    MEDIUM = 2
    STRONG = 3
    CONFIRMED = 4


class InformationDirection(Enum):
    A_SIDE = "A_SIDE"
    B_SIDE = "B_SIDE"
    MID = "MID"
    UNKNOWN = "UNKNOWN"


# source base strength (0..1) before time decay
_SOURCE_BASE = {
    "own_vision": 1.0,      # you see them now
    "team_vision": 0.85,    # teammate callout (comms assumed, cfg.team_comms)
    "damage": 0.9,          # you were shot from there
    "footstep": 0.6,
    "shot": 0.7,
    "grenade": 0.6,
}

# half-life in ticks for each source (at 64 tick/s)
_SOURCE_HALFLIFE = {
    "own_vision": 96.0,     # ~1.5 s
    "team_vision": 192.0,   # ~3 s
    "damage": 384.0,        # ~6 s (longer memory: you know where you got shot)
    "footstep": 64.0,       # ~1 s
    "shot": 96.0,
    "grenade": 128.0,
}

_NONE_FLOOR = 0.10


def _decay(base: float, age_ticks: int, half_life: float) -> float:
    return base * 0.5 ** (max(0, age_ticks) / max(1.0, half_life))


def strength_from_score(score: float) -> str:
    if score >= 0.9:
        return "CONFIRMED"
    if score >= 0.7:
        return "STRONG"
    if score >= 0.45:
        return "MEDIUM"
    if score >= _NONE_FLOOR:
        return "WEAK"
    return "NONE"


def compute_information_strength(known_state: dict, tick: int,
                                 now_visual: bool = False) -> dict:
    """Aggregate the known-state signals into one InformationStrength.

    Args:
        known_state: the PlayerKnownState dict (from KnownStateBuilder.build())
        tick: current tick
        now_visual: True when the player currently sees a living enemy
            (source == own_vision with age 0) -> CONFIRMED without decay.

    Returns:
        {"level": str, "confidence": float (raw score 0..1),
         "components": {source: score}, "note": str}
    """
    components = {}
    for enemy, seen in (known_state.get("last_seen_enemies") or {}).items():
        src = (seen or {}).get("source", "own_vision")
        age = max(0, tick - int((seen or {}).get("tick", tick)))
        if src in _SOURCE_BASE:
            score = _decay(_SOURCE_BASE[src], age, _SOURCE_HALFLIFE[src])
            components[src] = max(components.get(src, 0.0), score)
    # bomb planted is public information (confirmable, not hindsight)
    bomb = known_state.get("bomb_known")
    if bomb:
        components["bomb"] = 0.95
    # recent teammate kill/death (public kill feed) is a weak directional hint
    if known_state.get("recent_teammate_kill"):
        components["teammate_kill_public"] = max(components.get("teammate_kill_public", 0.0), 0.55)
    if known_state.get("recent_teammate_death"):
        components["teammate_death_public"] = max(components.get("teammate_death_public", 0.0), 0.5)

    score = max(components.values(), default=0.0)
    if now_visual:
        score = max(score, 1.0)
    level = strength_from_score(score)
    return {
        "level": level,
        "confidence": round(min(1.0, score), 4),
        "components": {k: round(v, 4) for k, v in sorted(components.items())},
        "note": f"max source score {score:.3f} -> {level}",
    }


def _zone_of_enemy(known_state: dict, enemy: str) -> str | None:
    """Map a known enemy's last-seen place to its map zone (A/B/MID/...)."""
    seen = (known_state.get("last_seen_enemies") or {}).get(enemy)
    if not seen:
        return None
    return seen.get("zone") or None


def compute_information_direction(known_state: dict) -> dict:
    """Aggregate known enemy zones into an InformationDirection.

    Returns:
        {"direction": str, "confidence": float (0..1),
         "zone_votes": {zone: count}, "note": str}
    """
    votes = {}
    for enemy in (known_state.get("last_seen_enemies") or {}):
        z = _zone_of_enemy(known_state, enemy)
        if not z:
            continue
        if z in ("A", "B"):
            votes[z + "_SIDE"] = votes.get(z + "_SIDE", 0) + 1
        elif z in ("MID", "CT", "T", "LONG"):
            votes["MID"] = votes.get("MID", 0) + 1
        else:
            votes["UNKNOWN"] = votes.get("UNKNOWN", 0) + 1
    total = sum(votes.values())
    if total == 0:
        return {"direction": "UNKNOWN", "confidence": 0.0,
                "zone_votes": {}, "note": "no known enemies"}
    best = max(votes, key=votes.get)
    conf = votes[best] / total
    return {"direction": best, "confidence": round(conf, 4),
            "zone_votes": votes, "note": f"majority {best} ({conf:.2f})"}


def direction_to_label(direction: str) -> str:
    """Direction -> intent-friendly label ('A_SIDE' -> 'A')."""
    if direction in ("A_SIDE", "B_SIDE"):
        return direction[0]
    if direction == "MID":
        return "Mid"
    return "Unknown"
