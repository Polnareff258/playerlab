"""Debug: predicate trigger rates across all episodes (uses cached ticks)."""
import math
import os
import sys

sys.path.insert(0, "core")
from playerlab.config import Config
from playerlab.ingest import parse_demo
from playerlab.state import build_tick_index, pos_at

cfg = Config().resolve()
demo_path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    cfg.data_dir, "..", "..", "spike", "sample.dem")
if not os.path.isfile(demo_path):
    print(f"demo not found: {demo_path}")
    sys.exit(1)
demo = parse_demo(demo_path, cfg)
idx = build_tick_index(demo)
agg = {"episodes": 0, "approach": 0, "retreat": 0, "hold": 0, "any_pos_dot": 0,
       "maxspeed_ge_120": 0, "fallback": 0}

for p in demo.players:
    if p["team_number"] not in (2, 3):
        continue
    steamid = p["steamid"]
    recs = {t: r for (s, t), r in idx.items() if s == steamid}
    ticks_sorted = sorted(recs)
    contacts = []
    for d in demo.events["damages"]:
        if d["user_steamid"] == steamid:
            contacts.append((d["tick"], "taken", d["attacker_steamid"]))
        elif d["attacker_steamid"] == steamid:
            contacts.append((d["tick"], "dealt", d["user_steamid"]))
    contacts.sort(key=lambda c: c[0])
    eps = []
    for t, k, o in contacts:
        if eps and t - eps[-1][-1][0] <= 150:
            eps[-1].append((t, k, o))
        else:
            eps.append([(t, k, o)])
    for ep in eps:
        agg["episodes"] += 1
        tc0, tc1 = ep[0][0], ep[-1][0]
        opp = max({c[2] for c in ep},
                  key=lambda o: sum(1 for c in ep if c[2] == o))
        anchor = pos_at(idx, opp, tc0) or pos_at(idx, opp, tc1)
        if not anchor:
            continue
        lo = max(tc0 - 96, min(ticks_sorted))
        maxsp, posdot = 0.0, False
        for t in ticks_sorted:
            if t < lo:
                continue
            if t > tc0 - 8:
                break
            r = recs[t]
            if not r.get("is_alive") or r.get("vx") is None:
                continue
            px, py = r.get("x"), r.get("y")
            if px is None or py is None:
                continue
            sp = (r["vx"] ** 2 + r["vy"] ** 2) ** 0.5
            maxsp = max(maxsp, sp)
            dx, dy = anchor[0] - px, anchor[1] - py
            n = math.hypot(dx, dy) or 1
            if (r["vx"] * dx + r["vy"] * dy) / n > 0:
                posdot = True
        if maxsp >= 120:
            agg["maxspeed_ge_120"] += 1
        if posdot:
            agg["any_pos_dot"] += 1
        if maxsp >= 120 and posdot:
            agg["approach"] += 1
        taken = [t for t, k, o in ep if k == "taken"]
        td = taken[0] if taken else tc0
        for t in ticks_sorted:
            if t < td:
                continue
            if t > td + 2 * 24:
                break
            r = recs[t]
            if not r.get("is_alive") or r.get("vx") is None:
                continue
            px, py = r.get("x"), r.get("y")
            if px is None or py is None:
                continue
            sp = (r["vx"] ** 2 + r["vy"] ** 2) ** 0.5
            dx, dy = anchor[0] - px, anchor[1] - py
            n = math.hypot(dx, dy) or 1
            if sp >= 120 and (r["vx"] * dx + r["vy"] * dy) / n < 0:
                agg["retreat"] += 1
                break
        # stationary hold run
        run = cur = 0
        for t in ticks_sorted:
            if t < tc0 - 8:
                continue
            if t > tc1 + 8:
                break
            if not recs[t].get("is_alive"):
                cur = 0
                continue
            sp = recs[t].get("speed") or 0.0
            if sp <= 60:
                cur += 1
                run = max(run, cur)
            else:
                cur = 0
        if run >= 16:
            agg["hold"] += 1

print("episodes:", agg["episodes"])
print("approach (speed>=120 & toward anchor):", agg["approach"])
print("  any positive dot:", agg["any_pos_dot"], "| max speed >= 120:", agg["maxspeed_ge_120"])
print("retreat (speed>=120 & away, after taken):", agg["retreat"])
print("stationary hold run >= 16:", agg["hold"])
