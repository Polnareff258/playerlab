#!/usr/bin/env python3
"""PlayerLab Technical Spike - probe v2 (demoparser2 0.42 API).

Fills gaps from probe v1: per-tick player state (XYZ/velocity/yaw/pitch/buttons/
weapon/hp), grenades, available game events, player info, tick budgets.
"""
import json
import sys
import time

DEMO_PATH = sys.argv[1]
OUT_PATH = sys.argv[2] if len(sys.argv) > 2 else None
t0 = time.time()
from demoparser2 import DemoParser  # noqa: E402

parser = DemoParser(DEMO_PATH)
summary = {"demo": DEMO_PATH, "engine": "demoparser2", "version": "0.42.0"}


def probe(name, fn):
    try:
        r = fn()
        summary[name] = {"ok": True, "result": r}
    except Exception as e:  # noqa: BLE001
        summary[name] = {"ok": False, "error": f"{type(e).__name__}: {e}"}
    summary[name]["t_ms"] = int((time.time() - t0) * 1000)
    print(f"[probe] {name}: ok={summary[name]['ok']} ({summary[name]['t_ms']}ms)", flush=True)


FIELDS = [
    "tick", "player_name", "steamid", "team", "is_alive", "health", "armor",
    "x", "y", "z", "velocity_x", "velocity_y", "velocity_z",
    "view_angle_x", "view_angle_y",
    "buttons", "forward", "left", "right", "back",
    "shots_fired", "active_weapon", "weapon_class", "current_equipment_value",
    "is_ducking", "is_crouching", "is_walking", "is_scoped",
    "has_helmet", "has_defuser", "has_bomb", "money", "ping",
    "last_place_name", "is_strafing", "stamina", "recoil_index",
]


def all_ticks():
    df = parser.parse_ticks(FIELDS)
    return {
        "rows": int(len(df)),
        "tick_range": [int(df["tick"].min()), int(df["tick"].max())],
        "players": sorted(df["player_name"].unique().tolist()),
        "teams": sorted(df["team"].unique().tolist()),
        "columns": list(df.columns),
    }

probe("all_ticks", all_ticks)


def mid_round_sample():
    # pick a tick ~2/3 into round 3 (round_start[2]=tick, round_end[2]=tick)
    rs = parser.parse_event("round_start")
    re = parser.parse_event("round_end")
    if len(rs) < 3 or len(re) < 3:
        return {"error": "fewer than 3 rounds"}
    t = int(rs["tick"].iloc[2] + (re["tick"].iloc[2] - rs["tick"].iloc[2]) * 0.6)
    df = parser.parse_ticks(FIELDS, ticks=[t])
    rows = df.sort_values("player_name").to_dict("records")
    return {"round3_mid_tick": t, "n_players": len(rows), "sample_rows": rows}

probe("mid_round_sample", mid_round_sample)


def grenades():
    g = parser.parse_grenades()
    return {"rows": int(len(g)), "columns": list(g.columns),
            "types": sorted(g["grenade_type"].unique().tolist()) if "grenade_type" in g.columns else None,
            "sample": g.head(3).to_dict("records")}

probe("grenades", grenades)


def events():
    evs = parser.list_game_events()
    return {"available_events": evs}

probe("game_events", events)


def player_info():
    pi = parser.parse_player_info()
    return {"rows": int(len(pi)), "columns": list(pi.columns),
            "sample": pi.head(2).to_dict("records")}

probe("player_info", player_info)


def tick_budget():
    # parse 1000 ticks (about 15s at 64 tick) to measure cost
    t = time.time()
    df = parser.parse_ticks(FIELDS, ticks=list(range(0, 1000)))
    dt = time.time() - t
    return {"ticks": 1000, "elapsed_s": round(dt, 3),
            "rows": int(len(df)), "rows_per_s": round(len(df) / dt, 1)}

probe("tick_budget_1000", tick_budget)


summary["elapsed_s"] = round(time.time() - t0, 1)
out = json.dumps(summary, ensure_ascii=False, indent=1, default=str)
print(out)
if OUT_PATH:
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        f.write(out)
    print(f"[written] {OUT_PATH}")
