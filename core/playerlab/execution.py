"""Execution metrics: move-and-shoot & counter-strafe (V1.1-alpha).

Computed per weapon_fire event for firearm weapons:
- move-and-shoot: horizontal velocity at the shot tick vs configured threshold.
- counter-strafe: pre-shot speed curve (peak, deceleration time, time since
  low velocity, shot-before-stabilized).

Deterministic; evidence ticks recorded for traceability.
"""
from __future__ import annotations

import math

from .config import Config
from .ingest import IngestedDemo
from .weapons import weapon_class

FIREARM_CLASSES = {"rifle", "smg", "pistol", "sniper", "heavy"}


def _weapon_name(raw: str) -> str:
    if not raw:
        return ""
    return raw[len("weapon_"):] if raw.startswith("weapon_") else raw


def is_firearm(raw_weapon: str) -> bool:
    return weapon_class(_weapon_name(raw_weapon)) in FIREARM_CLASSES


def compute_shot_metrics(demo: IngestedDemo, cfg: Config, idx: dict) -> list[dict]:
    """Return per-shot execution metrics (move-and-shoot + counter-strafe)."""
    out = []
    for shot in demo.events["shots"]:
        if not is_firearm(shot.get("weapon", "")):
            continue
        tick = shot["tick"]
        steamid = shot["user_steamid"]
        rec = idx.get((steamid, tick))
        if not rec or rec.get("vx") is None:
            continue
        vel_at_shot = math.hypot(rec["vx"], rec["vy"])
        move_shoot = vel_at_shot > cfg.move_shoot_velocity

        # counter-strafe window: [tick - pre_shot_window, tick - 1]
        peak = 0.0
        peak_tick = None
        last_low_tick = None
        window = []
        for dt in range(1, cfg.pre_shot_window_ticks + 1):
            r2 = idx.get((steamid, tick - dt))
            if not r2 or r2.get("vx") is None:
                continue
            sp = math.hypot(r2["vx"], r2["vy"])
            window.append((tick - dt, sp))
            if sp > peak:
                peak = sp
                peak_tick = tick - dt
            if sp <= cfg.stabilize_velocity:
                last_low_tick = tick - dt
        decel_time = (tick - peak_tick) if peak_tick is not None else None
        time_since_low = (tick - last_low_tick) if last_low_tick is not None else None
        shot_before_stabilized = vel_at_shot > cfg.stabilize_velocity

        out.append({
            "id": f"{demo.demo_id}-shot-{steamid}-{tick}",
            "match_id": demo.demo_id, "round": demo.round_of_tick(tick),
            "tick": tick, "steamid": steamid,
            "metric": "move_shoot",
            "value": round(vel_at_shot, 1),
            "threshold": cfg.move_shoot_velocity,
            "violation": 1 if move_shoot else 0,
            "evidence": {"shot_tick": tick, "weapon": shot.get("weapon"),
                         "window_ticks": [tick - cfg.pre_shot_window_ticks, tick]},
            "meta": {"peak_pre_shot_velocity": round(peak, 1),
                     "deceleration_time_ticks": decel_time,
                     "time_since_low_velocity_ticks": time_since_low,
                     "shot_before_stabilized": shot_before_stabilized,
                     "stabilize_velocity": cfg.stabilize_velocity},
        })
    return out
