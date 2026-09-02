"""Engagement layer (V1.3.1 spec §9-§21, §97-§98).

If the fight must be taken, HOW should it be fought? This layer sits between
the strategic local decision and duel execution:

    Strategic (should I fight?) -> Engagement (how?) -> Execution (quality?)

Core objects:
- EngagementContext: self/opponent state, weapon matchup, information
  advantage, geometry, utility, teammate support, duel phase
- InformationAdvantage: SELF / ENEMY / MUTUAL / NEITHER / UNKNOWN
- WeaponMatchup: self/enemy class + range bucket
- EngagementMethod: base_action x method (NORMAL_PEEK / WIDE_SWING /
  DRY_PEEK / FLASH_PEEK / TEAM_FLASH_PEEK / JIGGLE / LET_CROSS / ...)
- FightPreparation: ANGLE_SELECTION / STANDARD_HOLD / OFF_ANGLE / ...

Deterministic; only player-known + public information (hindsight guard).
"""
from __future__ import annotations

import math
from collections import Counter

from .config import Config
from .ingest import IngestedDemo
from .state import pos_at
from .context import TemporalContext
from .weapons import name_from_def, engagement_class, range_bucket, weapon_class

ENGAGEMENT_METHODS = ("HOLD", "NORMAL_PEEK", "WIDE_SWING", "DRY_PEEK",
                      "FLASH_PEEK", "TEAM_FLASH_PEEK", "JIGGLE", "LET_CROSS",
                      "DISENGAGE")
INFORMATION_ADVANTAGE = ("SELF", "ENEMY", "MUTUAL", "NEITHER", "UNKNOWN")
FIGHT_PREPARATIONS = ("ANGLE_SELECTION", "STANDARD_HOLD", "OFF_ANGLE",
                      "CLOSE_HOLD", "LONG_HOLD", "REPOSITION", "UTILITY_PREP",
                      "UNKNOWN")


def compute_information_advantage(tc: TemporalContext, known: dict) -> str:
    """Who knows whom? (spec §12). Player-known only."""
    n_known = tc.n_known_enemies
    # enemy likely knows us: we recently dealt/took damage or they saw us
    enemy_knows_us = bool(
        tc.events.get("damage_taken", 0) >= 1 or tc.events.get("damage_dealt", 0) >= 1
        or getattr(tc, "time_since_visual_contact", None) is not None
        and tc.time_since_visual_contact <= 64)
    we_know_them = n_known >= 1 and getattr(tc, "information_strength", "NONE") in (
        "MEDIUM", "STRONG", "CONFIRMED")
    if we_know_them and enemy_knows_us:
        return "MUTUAL"
    if we_know_them:
        return "SELF"
    if enemy_knows_us:
        return "ENEMY"
    return "NEITHER"


def weapon_matchup(tc: TemporalContext, known: dict,
                   opponent_state: dict | None = None) -> dict:
    """WeaponMatchup (spec §13): self/enemy class + range bucket."""
    self_def = known.get("own", {}).get("weapon_def")
    self_name = name_from_def(self_def) if self_def is not None else "unknown"
    self_cls = engagement_class(self_name)

    enemy_name = "unknown"
    enemy_cls = "UNKNOWN"
    if opponent_state:
        enemy_name = opponent_state.get("known_weapon") or "unknown"
        enemy_cls = engagement_class(enemy_name)

    mypos = pos_at(tc.idx, tc.steamid, tc.tick)
    enemy_pos = (opponent_state or {}).get("last_known_position")
    dist = None
    if mypos and enemy_pos:
        dist = math.hypot(enemy_pos[0] - mypos[0], enemy_pos[1] - mypos[1])

    return {
        "self_weapon": self_name, "self_weapon_class": self_cls,
        "enemy_weapon": enemy_name, "enemy_weapon_class": enemy_cls,
        "distance": dist,
        "range_bucket": range_bucket(dist),
        "note": "enemy weapon from PlayerKnownState only (UNKNOWN if never seen)",
    }


def fight_preparation(tc: TemporalContext, known: dict, anchor_tick: int) -> str:
    """FightPreparation (spec §22): what the player set up before contact."""
    # recently exposed / shot at this angle -> repeated angle
    recent_fire = tc.events.get("shots", 0)
    if recent_fire > 0:
        return "ANGLE_SELECTION"
    if known.get("own", {}).get("is_ducking"):
        return "CLOSE_HOLD"
    util = known.get("utility_inventory") or {}
    if util.get("flash_count", 0) > 0:
        return "UTILITY_PREP"
    return "STANDARD_HOLD"


def detect_engagement_method(demo: IngestedDemo, cfg: Config, tc: TemporalContext,
                             known: dict, observed_action: str,
                             duel: dict | None = None) -> dict:
    """EngagementMethod detection (spec §14-§21, §98).

    MVP methods: HOLD / NORMAL_PEEK / WIDE_SWING / DRY_PEEK / FLASH_PEEK /
    TEAM_FLASH_PEEK / JIGGLE / LET_CROSS / DISENGAGE.
    """
    util = known.get("utility_inventory") or {}
    flash_count = util.get("flash_count", 0)
    # self flash used in the pre-engagement window (flashbang detonate by us)
    self_flash_tick = _self_flash_tick(demo, tc.steamid, tc.tick, 128)
    team_flash_tick = _team_flash_tick(demo, tc, 128)

    method = "HOLD"
    base = observed_action
    # movement profile from the duel window (lateral velocity, reversals)
    lat = (duel or {}).get("movement", {}) or {}
    max_lat = lat.get("max_lateral_speed", 0.0)
    reversals = lat.get("direction_reversals", 0)
    exposure_ticks = (duel or {}).get("exposure_ticks", 0)

    if observed_action in ("DISENGAGE", "REPOSITION"):
        method = "DISENGAGE" if observed_action == "DISENGAGE" else "HOLD"
        base = "DISENGAGE"
    elif observed_action in ("HOLD", "HIDE"):
        method = "HOLD"
        base = "HOLD"
    elif observed_action in ("PEEK", "RE_PEEK"):
        if flash_count > 0 and self_flash_tick:
            method = "FLASH_PEEK"
            base = "PEEK"
        elif team_flash_tick:
            method = "TEAM_FLASH_PEEK"
            base = "PEEK"
        elif max_lat >= 320.0 and exposure_ticks >= 24:
            method = "WIDE_SWING"
            base = "PEEK"
        elif exposure_ticks <= 10 and reversals >= 2:
            method = "JIGGLE"
            base = "PEEK"
        elif _enemy_visible_without_util(demo, cfg, tc, known, self_flash_tick,
                                         team_flash_tick):
            method = "DRY_PEEK"
            base = "PEEK"
        else:
            method = "NORMAL_PEEK"
            base = "PEEK"
    elif observed_action == "TRADE":
        method = "NORMAL_PEEK"
        base = "TRADE"

    return {
        "base_action": base,
        "method": method,
        "self_utility_used": bool(self_flash_tick),
        "teammate_utility_used": bool(team_flash_tick),
        "self_flash_tick": self_flash_tick,
        "team_flash_tick": team_flash_tick,
        "movement_pattern": lat.get("pattern", "UNKNOWN"),
        "exposure_style": ("wide" if method == "WIDE_SWING"
                           else "jiggle" if method == "JIGGLE" else "standard"),
        "exposure_ticks": exposure_ticks,
        "max_lateral_speed": round(max_lat, 1) if max_lat else None,
        "direction_reversals": reversals,
        "confidence": round(0.5 + 0.1 * min(1.0, exposure_ticks / 32.0), 3),
    }


def _self_flash_tick(demo, steamid, tick, window) -> int | None:
    """Flash detonate by this player shortly before the anchor tick."""
    for g in demo.events.get("grenades", {}).get("flashbang_detonate", []):
        if g.get("user_steamid") == steamid and 0 <= tick - g["tick"] <= window:
            return g["tick"]
    return None


def _team_flash_tick(demo, tc, window) -> int | None:
    """Teammate flash detonate near this player shortly before the anchor."""
    teams = {p["steamid"]: p["team_number"] for p in demo.players}
    my_team = teams.get(tc.steamid, -1)
    for g in demo.events.get("grenades", {}).get("flashbang_detonate", []):
        gs = g.get("user_steamid")
        if gs in teams and teams[gs] == my_team and gs != tc.steamid \
                and 0 <= tc.tick - g["tick"] <= window:
            return g["tick"]
    return None


def _enemy_visible_without_util(demo, cfg, tc, known, self_flash, team_flash) -> bool:
    """Dry-peek criterion (spec §17): enemy known present and no utility
    advantage in the engagement window."""
    if self_flash or team_flash:
        return False
    return tc.n_known_enemies >= 1


def opponent_state(tc: TemporalContext, known: dict) -> dict:
    """OpponentState from PlayerKnownState only (spec §11). Unknown -> UNKNOWN."""
    enemies = known.get("last_seen_enemies") or {}
    if not enemies:
        return {"known_weapon": None, "known_hp": None,
                "last_known_position": None, "last_known_velocity": None,
                "last_seen_time": None, "known_cover": None,
                "known_direction": None, "known_scope_state": None,
                "known_flash_state": None, "confidence": 0.0}
    # nearest known enemy
    mypos = pos_at(tc.idx, tc.steamid, tc.tick)
    best = None
    best_d = None
    for e, v in enemies.items():
        p = v.get("pos")
        if not p or not mypos:
            continue
        d = math.hypot(p[0] - mypos[0], p[1] - mypos[1])
        if best_d is None or d < best_d:
            best, best_d = (e, v), d
    if not best:
        return {"known_weapon": None, "known_hp": None,
                "last_known_position": None, "last_known_velocity": None,
                "last_seen_time": None, "known_cover": None,
                "known_direction": None, "known_scope_state": None,
                "known_flash_state": None, "confidence": 0.0}
    e, v = best
    return {
        "enemy_steamid": e,
        "known_weapon": None,          # weapon not tracked in V1.3.1 known-state
        "known_hp": None,
        "last_known_position": v.get("pos"),
        "last_known_velocity": None,
        "last_seen_time": v.get("tick"),
        "known_cover": None,
        "known_direction": v.get("zone"),
        "known_scope_state": None,
        "known_flash_state": None,
        "confidence": round(max(0.0, 1.0 - (tc.tick - v["tick"]) / 512.0), 3),
    }


def build_engagement_context(demo, cfg, tc, known, duel=None,
                             observed_action="HOLD") -> dict:
    """EngagementContext (spec §9): everything about HOW the fight happens.

    V1.3.4.1: engagement_method carries ORTHOGONAL dimensions
    (base_action / movement_style / support_style / utility_type) instead of
    a single collapsed enum (PART G §20); SupportContext and StealthContext
    are computed from observable evidence only.
    """
    op = opponent_state(tc, known)
    matchup = weapon_matchup(tc, known, op)
    info_adv = compute_information_advantage(tc, known)
    prep = fight_preparation(tc, known, tc.tick)
    method = detect_engagement_method(demo, cfg, tc, known, observed_action,
                                      duel=duel)
    util = known.get("utility_inventory") or {}
    # V1.3.4.1 orthogonal support + stealth (PART G/H)
    try:
        from .context_semantics import detect_support, detect_stealth
        support = detect_support(
            demo, cfg, tc, known, idx=tc.idx,
            observed_action=observed_action,
            self_utility_used=bool(method.get("self_utility_used")),
            self_flash_tick=method.get("self_flash_tick"),
            team_flash_tick=method.get("team_flash_tick"),
            flank_state="UNKNOWN")
        stealth = detect_stealth(demo, cfg, tc, known, idx=tc.idx)
    except Exception:  # noqa: BLE001  support/stealth are additive
        support = {"support_style": "UNKNOWN", "utility_type": "NONE",
                   "confidence": 0.0, "note": ""}
        stealth = {"flank_state": "UNKNOWN", "reveal_score": None,
                   "confidence": 0.0, "note": ""}
    # orthogonal method dims (base_action / movement_style / support_style /
    # utility_type) — never collapse into one enum
    mv = (duel or {}).get("movement", {}) or {}
    max_lat = mv.get("max_lateral_speed", 0.0)
    method_dims = {
        "base_action": observed_action,
        "movement_style": _movement_style(observed_action, max_lat,
                                          (duel or {}).get("exposure_ticks", 0)),
        "support_style": support.get("support_style", "UNKNOWN")
        if isinstance(support, dict) else support.support_style,
        "utility_type": support.get("utility_type", "NONE")
        if isinstance(support, dict) else support.utility_type,
        "exposure_style": method.get("exposure_style", "standard"),
    }
    return {
        "self_state": {
            "weapon": name_from_def((known.get("own") or {}).get("weapon_def")),
            "hp": (known.get("own") or {}).get("hp"),
            "ammo_clip": (known.get("own") or {}).get("ammo_clip"),
            "scope_state": bool((known.get("own") or {}).get("zoom_level")),
            "movement_speed": (known.get("own") or {}).get("speed"),
            "duck_state": (known.get("own") or {}).get("is_ducking"),
            "utility_inventory": util,
            "position": pos_at(tc.idx, tc.steamid, tc.tick),
            "view_direction": (known.get("own") or {}).get("yaw"),
            "recent_shot": tc.events.get("shots", 0),
            "recent_damage": tc.events.get("damage_taken", 0),
        },
        "opponent_state": op,
        "distance": matchup.get("distance"),
        "weapon_matchup": matchup,
        "information_advantage": info_adv,
        "geometry": {"provider": "null",
                     "note": "AwpyGeometry optional; NULL_GEOMETRY in core"},
        "utility_context": util,
        "teammate_support": {
            "near": tc.mates[0]["dist"] if tc.mates else None,
            "tradeability": (getattr(tc, "_tradeability", {}) or {}).get("classification"),
        },
        "duel_phase": (duel or {}).get("phase", "UNKNOWN"),
        "exposure": {"ticks": (duel or {}).get("exposure_ticks", 0),
                     "style": method.get("exposure_style", "standard")},
        "fight_preparation": prep,
        "engagement_method": method,
        "method_dimensions": method_dims,     # orthogonal (PART G §20)
        "support_context": support if isinstance(support, dict) else support.summary(),
        "stealth_context": stealth if isinstance(stealth, dict) else stealth.summary(),
        "confidence": round(0.6, 3),
    }


def _movement_style(observed_action: str, max_lat: float, exposure_ticks: int) -> str:
    """Orthogonal movement dimension for EngagementMethod (PART G §20)."""
    if observed_action in ("HOLD", "HIDE"):
        return "STATIC"
    if observed_action in ("DISENGAGE", "REPOSITION"):
        return "RUN"
    if max_lat >= 320.0:
        return "WIDE_SWING"
    if exposure_ticks <= 10:
        return "JIGGLE"
    if observed_action in ("PEEK", "RE_PEEK"):
        return "PEEL"
    return "UNKNOWN"
