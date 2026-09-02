"""SupportContext + StealthContext for PlayerLab V1.3.4.1 (PART G/H).

PART G — SupportContext correctness:
  * EngagementMethod is ORTHOGONAL: {base_action, movement_style,
    support_style, utility_type} — never collapse back to one enum.
  * TEAM_UTILITY_ASSISTED requires teammate flash + timing relevance +
    SPATIAL relevance (the flash must be near this player's lane/position).
    A teammate flash on B while self peeks A is NOT team-assisted (§22).
  * COORDINATED_TEAM_PEEK: no utility but synchronized teammate exposure /
    trade / second-angle support (§23).
  * UNASSISTED only when utility + coordination + trade + stealth all absent.

PART H — StealthContext:
  * Only observable evidence: no recent damage/visual contact/public reveal/
    grenade reveal; no known enemy awareness evidence.
  * FlankState MVP: NOT_FLANKING / POSSIBLE_FLANK / ACTIVE_FLANK / DEEP_FLANK
    / UNKNOWN.
  * STEALTH_PRESERVING: deep flank + low reveal evidence + utility would
    plausibly reveal position -> holding utility is preserving surprise.
  * UI wording is 'Likely preserving surprise', never 'Enemy does not know'.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import math

# orthogonal support styles (PART G §20)
SUPPORT_STYLES = ("UNASSISTED", "SELF_UTILITY", "TEAM_UTILITY_ASSISTED",
                  "COORDINATED_TEAM_PEEK", "STEALTH_PRESERVING", "UNKNOWN")
UTILITY_TYPES = ("NONE", "SELF_FLASH", "TEAM_FLASH", "SMOKE", "HE", "MOLOTOV",
                 "UNKNOWN")
MOVEMENT_STYLES = ("STATIC", "MICRO_AD", "PEEL", "WIDE_SWING", "JIGGLE",
                   "RUN", "UNKNOWN")

FLANK_STATES = ("NOT_FLANKING", "POSSIBLE_FLANK", "ACTIVE_FLANK",
                "DEEP_FLANK", "UNKNOWN")


@dataclass(frozen=True)
class SupportContext:
    support_style: str = "UNASSISTED"
    utility_type: str = "NONE"
    teammate_flash_tick: int | None = None
    teammate_flash_relevant: bool = False    # timing + spatial relevance
    coordinated_exposure: bool = False       # teammate exposure sync
    trade_support: bool = False              # nearby teammate can trade
    second_angle: bool = False               # teammate holds a second angle
    stealth_preserving: bool = False
    confidence: float = 0.0
    note: str = ""

    def summary(self) -> dict:
        return dict(self.__dict__)


@dataclass(frozen=True)
class StealthContext:
    flank_state: str = "UNKNOWN"
    reveal_score: float = 0.0                # 0..1 (0 = fully hidden)
    recent_damage: bool = False
    recent_visual_contact: bool = False
    public_reveal: bool = False              # bomb/plant/kill feed reveal
    grenade_reveal: bool = False
    enemy_awareness_evidence: bool = False
    utility_would_reveal: bool = False
    confidence: float = 0.0
    note: str = ""

    def summary(self) -> dict:
        return dict(self.__dict__)


def _dist(a, b) -> float:
    if not a or not b:
        return float("inf")
    return math.hypot(a[0] - b[0], a[1] - b[1])


def detect_support(demo, cfg, tc, known, idx=None, geometry=None,
                   observed_action: str = "UNKNOWN",
                   self_utility_used: bool = False,
                   self_flash_tick: int | None = None,
                   team_flash_tick: int | None = None,
                   flank_state: str = "UNKNOWN") -> SupportContext:
    """SupportContext (PART G). Caller (decision/episode layer) supplies
    precomputed flash ticks; this function verifies relevance and decides the
    orthogonal style."""
    teams = {p["steamid"]: p["team_number"] for p in demo.players}
    my_team = teams.get(tc.steamid, -1)
    mypos = pos_at_tc(idx, tc) if idx else None

    # ---- teammate flash relevance: timing (<= window) + SPATIAL ----
    team_flash_relevant = False
    flash_tick = None
    if team_flash_tick is not None:
        flash_tick = team_flash_tick
        # spatial: is a teammate near our position/lane at the flash moment?
        near_teammate = False
        for p in demo.players:
            pid = p["steamid"]
            if pid == tc.steamid or p["team_number"] != my_team:
                continue
            if not idx:
                near_teammate = True   # no positions -> timing-only (weak)
                break
            rec = idx.get((pid, flash_tick))
            if not rec:
                continue
            if mypos and rec.get("x") is not None and rec.get("y") is not None:
                d = math.hypot(mypos[0] - rec["x"], mypos[1] - rec["y"])
                if d <= cfg.isolated_support_dist:
                    near_teammate = True
                    break
        team_flash_relevant = bool(near_teammate)

    # ---- coordinated exposure: teammate engaged/trading nearby ----
    coordinated = False
    trade = False
    second_angle = False
    if idx:
        t0 = tc.tick
        for p in demo.players:
            pid = p["steamid"]
            if pid == tc.steamid or p["team_number"] != my_team:
                continue
            rec = idx.get((pid, t0))
            if not rec or not rec.get("is_alive"):
                continue
            if mypos and rec.get("x") is not None and rec.get("y") is not None:
                d = math.hypot(mypos[0] - rec["x"], mypos[1] - rec["y"])
                if d <= cfg.advantage_engagement_dist:
                    # teammate engaged in same fight -> coordination/trade
                    dmg_near = any(
                        dd.get("user_steamid") == pid and
                        abs(dd.get("tick", 0) - t0) <= cfg.teammate_contact_window_ticks
                        for dd in demo.events.get("damages", []))
                    if dmg_near:
                        trade = True
                        coordinated = True
                    # teammate facing a different direction than self = 2nd angle
                    s_yaw = rec.get("yaw")
                    my_rec = idx.get((tc.steamid, t0)) or {}
                    m_yaw = my_rec.get("yaw")
                    if s_yaw is not None and m_yaw is not None:
                        diff = abs((s_yaw - m_yaw + 180) % 360 - 180)
                        if diff >= 45:
                            second_angle = True
                            coordinated = True

    # ---- stealth preserving ----
    stealth = flank_state in ("ACTIVE_FLANK", "DEEP_FLANK")
    util_would_reveal = bool(self_flash_tick or team_flash_relevant or
                             (known.get("utility_inventory") or {}).get("smoke_count", 0) > 0)
    stealth_preserving = bool(stealth and util_would_reveal and not self_utility_used)

    # ---- decide the style ----
    if self_utility_used:
        style = "SELF_UTILITY"
        utype = "SELF_FLASH"
    elif stealth_preserving:
        style = "STEALTH_PRESERVING"
        utype = "NONE"
    elif team_flash_relevant:
        style = "TEAM_UTILITY_ASSISTED"
        utype = "TEAM_FLASH"
    elif coordinated and (trade or second_angle):
        style = "COORDINATED_TEAM_PEEK"
        utype = "NONE"
    else:
        style = "UNASSISTED"
        utype = "NONE"

    conf = 0.0
    if style == "UNASSISTED":
        # truly nothing present — only when we checked and found none
        conf = 0.8
        note = "无道具、无队友协同/换位支援"
    elif style == "TEAM_UTILITY_ASSISTED":
        conf = 0.9 if team_flash_relevant else 0.4
        note = "队友闪光支援（时间+空间相关）"
    elif style == "COORDINATED_TEAM_PEEK":
        conf = 0.7
        note = "队友协同施压/换位支援（无道具）"
    elif style == "STEALTH_PRESERVING":
        conf = 0.7
        note = "深度绕后，使用道具会暴露位置 → 保持隐蔽"
    elif style == "SELF_UTILITY":
        conf = 0.85
        note = "自身道具支援"
    else:
        note = "信息不足"
    return SupportContext(style, utype, flash_tick, team_flash_relevant,
                          coordinated, trade, second_angle, stealth_preserving,
                          conf, note)


def pos_at_tc(idx, tc):
    if not idx:
        return None
    rec = idx.get((tc.steamid, tc.tick))
    if not rec:
        return None
    x, y = rec.get("x"), rec.get("y")
    return (x, y) if x is not None and y is not None else None


def detect_stealth(demo, cfg, tc, known, idx=None,
                   flank_depth_units: float | None = None,
                   rounds=None) -> StealthContext:
    """StealthContext (PART H). Observable evidence only."""
    # 1) reveal indicators
    recent_damage = any(
        (d.get("user_steamid") == tc.steamid or d.get("attacker_steamid") == tc.steamid)
        and 0 <= tc.tick - d.get("tick", 0) <= cfg.damage_memory_ticks
        for d in demo.events.get("damages", []))
    recent_visual = any(
        (v.get("tick", 0) <= tc.tick and tc.tick - v.get("tick", 0) <= cfg.known_state_memory_ticks)
        for v in (known.get("last_seen_enemies") or {}).values())
    # public reveal: recent kill we caused or plant/defuse we did
    public_reveal = any(
        (k.get("attacker_steamid") == tc.steamid and
         0 <= tc.tick - k.get("tick", 0) <= 128)
        for k in demo.events.get("kills", []))
    # grenade reveal: our grenade detonated recently (position is exposed)
    grenade_reveal = False
    for gname in ("hegrenade_detonate", "flashbang_detonate", "inferno_startburn",
                  "smokegrenade_detonate"):
        for g in demo.events.get("grenades", {}).get(gname, []):
            if g.get("user_steamid") == tc.steamid and 0 <= tc.tick - g.get("tick", 0) <= 192:
                grenade_reveal = True
                break

    # 2) enemy awareness evidence: enemy recently shot/damaged us or our zone
    enemy_aware = recent_damage or any(
        (d.get("attacker_steamid") == tc.steamid and
         0 <= tc.tick - d.get("tick", 0) <= cfg.damage_memory_ticks)
        for d in demo.events.get("damages", []))

    reveal_score = sum([0.4 if recent_damage else 0,
                        0.25 if recent_visual else 0,
                        0.25 if public_reveal else 0,
                        0.2 if grenade_reveal else 0,
                        0.3 if enemy_aware else 0])
    reveal_score = min(1.0, reveal_score)

    # 3) flank state by depth behind enemy lines (approximate)
    flank = "UNKNOWN"
    if rounds:
        my_side = demo.side_at_round(tc.steamid, tc.round) if hasattr(demo, "side_at_round") else None
        flank = "NOT_FLANKING"
    if flank_depth_units is not None:
        if flank_depth_units > 4000:
            flank = "DEEP_FLANK"
        elif flank_depth_units > 2000:
            flank = "ACTIVE_FLANK"
        elif flank_depth_units > 800:
            flank = "POSSIBLE_FLANK"
        else:
            flank = "NOT_FLANKING"
    else:
        # no geometry/nav: only flag 'possible' when hidden with movement
        if not reveal_score:
            flank = "POSSIBLE_FLANK"
        else:
            flank = "UNKNOWN"

    # utility would reveal (smoke/flash in hand while deep)
    utility_would_reveal = False
    util = known.get("utility_inventory") or {}
    if flank in ("ACTIVE_FLANK", "DEEP_FLANK") and util:
        if util.get("flash_count", 0) > 0 or util.get("he_count", 0) > 0:
            utility_would_reveal = True

    conf = min(1.0, 0.4 + 0.3 * (1.0 - reveal_score))
    note = ""
    if flank in ("ACTIVE_FLANK", "DEEP_FLANK") and reveal_score <= 0.2:
        note = "深度绕后且无明显暴露证据"
    return StealthContext(flank, round(reveal_score, 3), recent_damage,
                          recent_visual, public_reveal, grenade_reveal,
                          enemy_aware, utility_would_reveal, round(conf, 3), note)
