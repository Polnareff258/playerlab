"""Duel execution layer (V1.3.1 spec §32-§60, §99-§101).

DuelState: short fight-dynamic sequence (position/velocity/yaw/crosshair/
duck/shot/phase) sampled at 50-100ms over DETECTED engagement windows only
(spec §113 performance guard). Execution primitives:

    FIRE_BEFORE_AIM_READY   shot while crosshair still correcting
    PREAIM_ERROR            crosshair far from target region at first visibility
    MOVING_SHOT             shot while moving (reuse V1.1 move-and-shoot)
    IRREGULAR_DUEL_MOVEMENT movement costs more than it gains

MovementEffect (spec §51-§57): self accuracy/aim-stability cost vs estimated
opponent tracking difficulty — LOW/MEDIUM/HIGH/UNKNOWN, never fake precision.
"""
from __future__ import annotations

import math

from .config import Config
from .ingest import IngestedDemo
from .state import pos_at, angle_diff
from .fieldmap import BUTTON_DUCK, BUTTON_ATTACK
from .weapons import range_bucket

ENGAGEMENT_PHASES = ("PRE_CONTACT", "ACQUISITION", "FIRST_SHOT", "ACTIVE_DUEL",
                     "REACQUIRE", "DISENGAGE", "RESOLUTION")
MOVEMENT_PATTERNS = ("STATIC", "COUNTER_STRAFE", "SINGLE_STRAFE", "ADAD",
                     "IRREGULAR_STRAFE", "CROUCH", "CROUCH_STRAFE",
                     "CROUCH_SPAM", "WIDE_SWING", "UNKNOWN")

# hitbox approximations (APPROXIMATE_HITBOX, spec §38) — view-height offsets
HEAD_OFFSET = 55.0    # ~1.7m eye height approx above feet (units)
CHEST_OFFSET = 30.0


def _angular_error(viewer_yaw, viewer_pitch, from_pos, to_pos) -> tuple:
    """Angular error (deg) of the view direction vs a target point.
    Returns (head_error, chest_error). None when data missing.
    CS2 yaw convention: 0 deg = +y (north), 90 deg = +x (east)."""
    if None in (viewer_yaw, from_pos, to_pos):
        return (None, None)
    dx = to_pos[0] - from_pos[0]
    dy = to_pos[1] - from_pos[1]
    d = math.hypot(dx, dy)
    if d < 1.0:
        return (0.0, 0.0)
    # need_yaw: CS2 convention (atan2(dx, dy), then to degrees)
    need_yaw = math.degrees(math.atan2(dx, dy))
    yaw_err = angle_diff(viewer_yaw, need_yaw)
    # vertical error approximated by pitch vs target elevation
    if viewer_pitch is None:
        return (yaw_err, yaw_err)
    need_pitch = -math.degrees(math.atan2(HEAD_OFFSET, d))
    head_err = math.hypot(yaw_err, abs(viewer_pitch - need_pitch))
    need_pitch_c = -math.degrees(math.atan2(CHEST_OFFSET, d))
    chest_err = math.hypot(yaw_err, abs(viewer_pitch - need_pitch_c))
    return (head_err, chest_err)


def detect_engagement_windows(demo: IngestedDemo, cfg: Config, idx: dict,
                              steamid: int, contact_ticks: list[int]) -> list[dict]:
    """Windows around damage contacts (reuse DP episode grouping)."""
    windows = []
    contact_ticks = sorted(contact_ticks)
    i = 0
    while i < len(contact_ticks):
        start = contact_ticks[i]
        end = start
        while i + 1 < len(contact_ticks) and contact_ticks[i + 1] - end <= cfg.episode_merge_ticks:
            i += 1
            end = contact_ticks[i]
        windows.append({"start": max(0, start - 16), "anchor": start,
                        "end": end + 96, "n_contacts": (end - start) // 32 + 1})
        i += 1
    return windows


def extract_duel_state_sequence(demo: IngestedDemo, cfg: Config, idx: dict,
                                steamid: int, window: dict,
                                enemy_steamid: int | None = None) -> dict:
    """DuelState sequence over one engagement window (spec §32-§35).
    Sampled every 8 ticks (~125ms) — bounded, window-local only (spec §113)."""
    start, end = window["start"], window["end"]
    tick_range = list(range(start, end + 1, 8))
    seq = []
    phase = "PRE_CONTACT"
    first_shot_tick = None
    enemy_visible_tick = None
    exposure_start = None
    exposure_ticks = 0
    seen_enemy = False
    prev_lat = None
    reversals = 0
    max_lat = 0.0
    last_shot_yaw_err = None

    for t in tick_range:
        srec = idx.get((steamid, t))
        if not srec:
            continue
        mypos = pos_at(idx, steamid, t)
        if not mypos:
            continue
        s_yaw = srec.get("yaw")
        s_pitch = srec.get("pitch") or 0.0
        alive = bool(srec.get("is_alive"))
        buttons = srec.get("buttons") or 0
        duck = bool(buttons & BUTTON_DUCK)
        firing = bool(buttons & BUTTON_ATTACK)

        # enemy position (known-state or duel opponent ground truth for
        # crosshair error is NOT allowed — error uses known enemy positions)
        epos = None
        if enemy_steamid is not None:
            # player-known only: use last seen; fall back to ground-truth ONLY
            # for distance/phase (never for 'what player knew')
            erec = idx.get((enemy_steamid, t))
            if erec and erec.get("is_alive"):
                epos = pos_at(idx, enemy_steamid, t)

        head_err, chest_err = (None, None)
        if epos:
            head_err, chest_err = _angular_error(s_yaw, s_pitch, mypos, epos)
            if not seen_enemy:
                seen_enemy = True
                enemy_visible_tick = t
                exposure_start = t
            if phase == "PRE_CONTACT":
                phase = "ACQUISITION"
        if firing and first_shot_tick is None:
            first_shot_tick = t
            if phase in ("PRE_CONTACT", "ACQUISITION"):
                phase = "FIRST_SHOT"
            last_shot_yaw_err = head_err
        elif phase in ("FIRST_SHOT", "ACQUISITION") and epos:
            phase = "ACTIVE_DUEL"
        if not alive:
            phase = "RESOLUTION"
        if exposure_start is not None and epos is not None:
            exposure_ticks = t - exposure_start

        # lateral velocity (perpendicular to view)
        vx, vy = srec.get("vx", 0.0) or 0.0, srec.get("vy", 0.0) or 0.0
        lat = _lateral(vx, vy, s_yaw)
        max_lat = max(max_lat, abs(lat))
        if prev_lat is not None and lat * prev_lat < 0:
            reversals += 1
        prev_lat = lat

        seq.append({
            "tick": t, "phase": phase,
            "self_position": list(mypos) if mypos else None,
            "enemy_position": list(epos) if epos else None,
            "self_velocity": [vx, vy], "enemy_velocity": None,
            "self_yaw": s_yaw, "self_pitch": s_pitch,
            "enemy_visible": bool(epos),
            "crosshair_error_head": round(head_err, 2) if head_err is not None else None,
            "crosshair_error_chest": round(chest_err, 2) if chest_err is not None else None,
            "duck_state": duck, "shot_state": firing,
        })

    movement = _movement_profile(seq, max_lat, reversals, duck_count=0)
    return {
        "steamid": steamid, "window": window,
        "sequence": seq,
        "phase": phase,
        "first_shot_tick": first_shot_tick,
        "enemy_visible_tick": enemy_visible_tick,
        "exposure_ticks": exposure_ticks,
        "movement": movement,
        "shot_crosshair_error": last_shot_yaw_err,
        "preaim_error": _preaim_error(seq, enemy_visible_tick),
    }


def _lateral(vx, vy, yaw_deg) -> float:
    """Velocity projected onto the view-perpendicular axis (spec §47)."""
    if yaw_deg is None:
        return math.hypot(vx, vy) * 0.7  # fallback: assume some lateral
    rad = math.radians(yaw_deg)
    fx, fy = math.cos(rad), math.sin(rad)   # forward
    # perpendicular = (-fy, fx)
    return -fy * vx + fx * vy


def _movement_profile(seq, max_lat, reversals, duck_count) -> dict:
    """MovementPattern (spec §45-§50)."""
    ducks = sum(1 for s in seq if s["duck_state"])
    moving = [s for s in seq if math.hypot(s["self_velocity"][0], s["self_velocity"][1]) > 60.0]
    pattern = "STATIC"
    if ducks >= len(seq) * 0.6 and reversals >= 2:
        pattern = "CROUCH_SPAM"
    elif ducks >= len(seq) * 0.4 and max_lat > 120.0:
        pattern = "CROUCH_STRAFE"
    elif ducks >= len(seq) * 0.4:
        pattern = "CROUCH"
    elif max_lat >= 320.0 and reversals <= 1:
        pattern = "WIDE_SWING"
    elif reversals >= 4:
        pattern = "ADAD"
    elif reversals >= 2:
        pattern = "IRREGULAR_STRAFE"
    elif len(moving) > 0 and reversals == 1:
        pattern = "SINGLE_STRAFE"
    elif len(moving) > 0:
        pattern = "COUNTER_STRAFE"
    return {"pattern": pattern, "max_lateral_speed": round(max_lat, 1),
            "direction_reversals": reversals, "duck_count": ducks}


def _preaim_error(seq, enemy_visible_tick) -> dict:
    """PREAIM_ERROR (spec §41-§42): crosshair error when enemy first visible.
    Never mixed with later corrections (spec §112)."""
    for s in seq:
        if s["tick"] == enemy_visible_tick and s["crosshair_error_head"] is not None:
            err = s["crosshair_error_head"]
            return {"error_deg": round(err, 2),
                    "bucket": _err_bucket(err),
                    "note": "error at first enemy visibility"}
    return {"error_deg": None, "bucket": "UNKNOWN", "note": "no visibility frame"}


def _err_bucket(err: float) -> str:
    if err is None:
        return "UNKNOWN"
    if err <= 1.5:
        return "LOW"
    if err <= 4.0:
        return "MEDIUM"
    return "HIGH"


def execution_primitives(demo, cfg, duel: dict, tc) -> list[str]:
    """MVP execution primitives (spec §100):
    FIRE_BEFORE_AIM_READY / PREAIM_ERROR / MOVING_SHOT / IRREGULAR_DUEL_MOVEMENT."""
    flags = []
    # FIRE_BEFORE_AIM_READY (spec §39): shot with large crosshair error
    shot_err = duel.get("shot_crosshair_error")
    if shot_err is not None and _err_bucket(shot_err) in ("HIGH", "MEDIUM"):
        flags.append("FIRE_BEFORE_AIM_READY")
    # PREAIM_ERROR (spec §41)
    preaim = duel.get("preaim_error") or {}
    if preaim.get("bucket") in ("HIGH", "MEDIUM"):
        flags.append("PREAIM_ERROR")
    # MOVING_SHOT (spec §44): shot while lateral velocity high
    movement = duel.get("movement") or {}
    if movement.get("max_lateral_speed", 0) >= 130.0:
        flags.append("MOVING_SHOT")
    # IRREGULAR_DUEL_MOVEMENT (spec §50): high reversals + no crouch benefit
    if movement.get("direction_reversals", 0) >= 3 and \
            movement.get("pattern") in ("ADAD", "IRREGULAR_STRAFE"):
        flags.append("IRREGULAR_DUEL_MOVEMENT")
    return flags


def movement_effect(demo, cfg, duel: dict, tc, weapon_class: str,
                    range_b: str) -> dict:
    """MovementEffect (spec §51-§57): self cost vs opponent difficulty.
    Deterministic heuristic; LOW/MEDIUM/HIGH/UNKNOWN only (spec §52)."""
    movement = duel.get("movement") or {}
    pattern = movement.get("pattern", "UNKNOWN")
    reversals = movement.get("direction_reversals", 0)
    max_lat = movement.get("max_lateral_speed", 0.0)
    ducks = movement.get("duck_count", 0)

    # self accuracy cost (spec §53): weapon movement inaccuracy + speed
    if weapon_class in ("AWP", "SNIPER_OTHER"):
        self_acc = "HIGH" if max_lat > 80.0 else ("MEDIUM" if max_lat > 40.0 else "LOW")
    elif weapon_class in ("RIFLE",):
        self_acc = "HIGH" if max_lat > 200.0 else ("MEDIUM" if max_lat > 120.0 else "LOW")
    else:  # SMG / shotgun / pistol: movement-tolerant
        self_acc = "LOW"

    # self aim stability cost (spec §54): reversals + crouch transitions
    if reversals >= 4 or (reversals >= 2 and ducks >= 3):
        self_stab = "HIGH"
    elif reversals >= 2 or ducks >= 2:
        self_stab = "MEDIUM"
    else:
        self_stab = "LOW"

    # estimated opponent tracking difficulty (spec §55) — heuristic only
    diff_score = 0.0
    if max_lat >= 320.0:
        diff_score += 2.0
    elif max_lat >= 160.0:
        diff_score += 1.0
    if reversals >= 3:
        diff_score += 1.5
    elif reversals >= 1:
        diff_score += 0.5
    if ducks >= 2:
        diff_score += 0.5
    if range_b == "close":
        diff_score += 0.5
    opponent_diff = "HIGH" if diff_score >= 2.5 else ("MEDIUM" if diff_score >= 1.0 else "LOW")

    return {
        "self_accuracy_cost": self_acc,
        "self_aim_stability_cost": self_stab,
        "estimated_opponent_tracking_difficulty": opponent_diff,
        "estimated_target_difficulty": opponent_diff,  # alias (spec §56 naming)
        "exposure_effect": ("HIGH" if pattern == "WIDE_SWING" else "MEDIUM"
                            if pattern in ("ADAD", "IRREGULAR_STRAFE") else "LOW"),
        "escape_value": ("HIGH" if pattern in ("WIDE_SWING",) and max_lat >= 400 else "LOW"),
        "confidence": 0.6,
        "note": "heuristic EstimatedTargetDifficulty — not guaranteed enemy experience (spec §56)",
    }


def duel_evaluation(demo, cfg, duel: dict, tc, engagement_method: dict,
                    movement_effect: dict, range_b: str,
                    weapon_class: str) -> str:
    """DuelExecutionEvaluation (spec §58-§59): GOOD..POOR, context-aware.
    Movement context (spec §57): close SMG irregular strafe may be REASONABLE,
    long-range AK ADAD may be QUESTIONABLE."""
    flags = execution_primitives(demo, cfg, duel, tc)
    score = 0.0
    if "FIRE_BEFORE_AIM_READY" in flags:
        score -= 1.5
    if "PREAIM_ERROR" in flags:
        score -= 1.0
    if "MOVING_SHOT" in flags and weapon_class in ("AWP", "SNIPER_OTHER"):
        score -= 1.5
    elif "MOVING_SHOT" in flags:
        score -= 0.5
    if "IRREGULAR_DUEL_MOVEMENT" in flags:
        if range_b == "close" and weapon_class in ("SMG", "SHOTGUN", "PISTOL"):
            score += 0.5   # movement works at close range (spec §57/§109)
        elif range_b == "long" and weapon_class == "RIFLE":
            score -= 1.0   # costs aim at range (spec §57/§110)
        else:
            score -= 0.5

    if score >= 0.5:
        return "GOOD"
    if score >= -0.5:
        return "REASONABLE"
    if score >= -1.5:
        return "QUESTIONABLE"
    return "POOR"
