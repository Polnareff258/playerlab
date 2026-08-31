#!/usr/bin/env python3
"""PlayerLab Technical Spike - demo capability probe (demoparser2).

Probes a real .dem file for data availability:
  header / ticks / XYZ / velocity / yaw / pitch / buttons / shots / damage /
  weapon / grenades / rounds / kills / visibility proxy (none in parser) / map.

Usage: python3 demo_probe.py <path-to.dem> [out.json]
Output: JSON summary to stdout and optionally out.json.
"""
import json
import sys
import time

DEMO_PATH = sys.argv[1] if len(sys.argv) > 1 else None
OUT_PATH = sys.argv[2] if len(sys.argv) > 2 else None
if not DEMO_PATH:
    print(json.dumps({"error": "no demo path"}, ensure_ascii=False))
    sys.exit(2)

t0 = time.time()
from demoparser2 import DemoParser  # noqa: E402

parser = DemoParser(DEMO_PATH)
summary = {"demo": DEMO_PATH, "engine": "demoparser2"}


def probe(name, fn):
    try:
        r = fn()
        summary[name] = {"ok": True, "result": r}
    except Exception as e:  # noqa: BLE001
        summary[name] = {"ok": False, "error": f"{type(e).__name__}: {e}"}
    summary[name]["t_ms"] = int((time.time() - t0) * 1000)
    print(f"[probe] {name}: ok={summary[name]['ok']} ({summary[name]['t_ms']}ms)", flush=True)


# ---- header / engine info ----
def hdr():
    h = parser.parse_header()
    if not isinstance(h, dict):
        h = dict(h)
    keep = {k: h[k] for k in ("map_name", "tickrate", "playercount", "protocol", "game",
                              "hostname", "client_name", "server_name", "game_type", "game_mode",
                              "match_id", "clock_time", "datetime", "game_version", "demo_version",
                              "network_protocol", "build_number") if k in h}
    return keep

probe("header", hdr)

# ---- full-tick player state fields ----
FIELDS = [
    "x", "y", "z",
    "velocity_x", "velocity_y", "velocity_z",
    "view_angle_x", "view_angle_y",  # yaw / pitch
    "buttons", "forward", "left", "right", "back",
    "shots_fired", "is_alive", "health", "armor", "money",
    "active_weapon", "weapon_class", "current_equipment_value",
    "is_ducking", "is_crouching", "is_walking", "is_scoped", "is_zoomed",
    "has_helmet", "has_defuser", "has_bomb", "ping", "recoil_index",
]

def frames():
    df = parser.parse(FIELDS)
    return {
        "rows": int(len(df)),
        "players_seen": sorted(df["player_name"].unique().tolist()) if "player_name" in df.columns else [],
        "ticks_covered": [int(df["tick"].min()), int(df["tick"].max())] if "tick" in df.columns else None,
        "columns": list(df.columns),
        "sample_columns": {c: int(df[c].iloc[0]) if df[c].dtype.kind in "iu" else (float(df[c].iloc[0]) if df[c].dtype.kind == "f" else str(df[c].iloc[0])) for c in FIELDS if c in df.columns},
    }

probe("player_state_fields", frames)


# ---- weapons ----
def weapons():
    w = parser.parse_weapons()
    return {"rows": int(len(w)), "columns": list(w.columns),
            "sample": w.head(1).to_dict("records")}

probe("weapons", weapons)


# ---- events: kills / damage / shots / rounds / grenades ----
def ev(name):
    df = parser.parse_event(name)
    return {"rows": int(len(df)), "columns": list(df.columns),
            "sample": df.head(1).to_dict("records") if len(df) else None}

for evname in ["player_death", "player_hurt", "weapon_fire", "round_start",
               "round_end", "bomb_planted", "bomb_defused", "grenade_thrown",
               "player_footstep", "item_purchase", "round_mvp"]:
    probe(f"event:{evname}", lambda n=evname: ev(n))

# ---- game state (rounds / scores) ----
def gstate():
    gs = parser.parse_game_state()
    rounds = gs.get("rounds") if isinstance(gs, dict) else None
    return {
        "has_game_state": isinstance(gs, dict),
        "round_count": len(rounds) if rounds is not None else None,
        "first_round_sample": (rounds[0] if rounds and len(rounds) else None),
        "keys": list(gs.keys()) if isinstance(gs, dict) else str(type(gs)),
    }

probe("game_state", gstate)

# ---- tick budget probe: parse only first 5 seconds of ticks ----
def tick_sample():
    df = parser.parse_ticks(FIELDS, [0, 64, 128, 256, 512])
    return {"rows": int(len(df)), "ticks": sorted(df["tick"].unique().tolist()),
            "columns": list(df.columns)}

probe("ticks_sample", tick_sample)

summary["elapsed_s"] = round(time.time() - t0, 1)
out = json.dumps(summary, ensure_ascii=False, indent=1, default=str)
print(out)
if OUT_PATH:
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        f.write(out)
    print(f"[written] {OUT_PATH}")
