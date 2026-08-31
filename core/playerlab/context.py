"""TemporalContext (spec §3): structured time-window context per player.

Past window only for player-known features (hindsight guard); future data is
never used for classification — only for offline/outcome attribution.
Feature values are normalized for future tiny-model training (§29-§30):
positions map-relative, zones indexed, relative teammate geometry.
"""
from __future__ import annotations

import math
from collections import Counter

from .config import Config
from .ingest import IngestedDemo
from .state import pos_at, angle_diff
from .zones import zone_for

MAP_BOUNDS = {"de_dust2": (-2500.0, 3000.0, -2500.0, 2500.0)}  # fallback


def map_bounds(demo: IngestedDemo) -> tuple:
    b = MAP_BOUNDS.get(demo.header.get("map_name"))
    if b:
        return b
    xs = demo.ticks["x"].dropna()
    ys = demo.ticks["y"].dropna()
    if len(xs) < 2:
        return (-4000.0, 4000.0, -4000.0, 4000.0)
    return (float(xs.min()), float(xs.max()), float(ys.min()), float(ys.max()))


def norm_pos(x, y, bounds) -> tuple:
    x0, x1, y0, y1 = bounds
    nx = (x - x0) / max(1.0, x1 - x0)
    ny = (y - y0) / max(1.0, y1 - y0)
    return (max(0.0, min(1.0, nx)), max(0.0, min(1.0, ny)))


class TemporalContext:
    """Everything the decision-quality layer may legally read about a moment."""

    def __init__(self, demo: IngestedDemo, cfg: Config, idx: dict, steamid: int,
                 tick: int, known_state: dict | None = None):
        self.demo = demo
        self.cfg = cfg
        self.idx = idx
        self.steamid = steamid
        self.tick = tick
        self.known = known_state or {}
        self.window = [tick - cfg.context_window_ticks, tick]
        self.bounds = map_bounds(demo)
        self._build()

    def _build(self):
        cfg = self.cfg
        ts = list(range(max(0, self.window[0]), self.window[1] + 1, cfg.context_sample_interval))
        traj = []
        for t in ts:
            rec = self.idx.get((self.steamid, t))
            if not rec:
                continue
            x, y = rec.get("x"), rec.get("y")
            sp = rec.get("speed") or 0.0
            if x is None or y is None:
                continue
            traj.append({
                "t": t, "pos": norm_pos(x, y, self.bounds),
                "speed": float(sp),
                "yaw": rec.get("yaw"),
                "zone": zone_for(self.demo.header.get("map_name"), rec.get("place") or ""),
                "alive": bool(rec.get("is_alive")),
                "weapon_def": rec.get("weapon_def"),
            })
        self.trajectory = traj
        zones = [s["zone"] for s in traj if s["alive"]]
        self.zone_sequence = zones
        self.zone_crossings = sum(1 for i in range(1, len(zones)) if zones[i] != zones[i - 1])
        self.zone_set = Counter(zones)
        self.time_moving_ticks = sum(1 for s in traj if s["speed"] > 60.0)
        # heading consistency: circular variance of yaw while moving
        yaws = [s["yaw"] for s in traj if s["speed"] > 60.0 and s["yaw"] is not None]
        self.heading_consistency = 1.0
        if len(yaws) >= 3:
            r = math.hypot(sum(math.cos(math.radians(y)) for y in yaws),
                           sum(math.sin(math.radians(y)) for y in yaws)) / len(yaws)
            self.heading_consistency = r

        teams = {p["steamid"]: p["team_number"] for p in self.demo.players}
        my_team = teams.get(self.steamid, -1)
        alive = {2: 0, 3: 0}
        mates = []
        for s, t in teams.items():
            rec = self.idx.get((s, self.tick))
            if rec and rec.get("is_alive"):
                alive[t] += 1
                if t == my_team and s != self.steamid:
                    p = pos_at(self.idx, s, self.tick)
                    mypos = pos_at(self.idx, self.steamid, self.tick)
                    if p and mypos:
                        mates.append({"steamid": s, "dist": math.hypot(p[0] - mypos[0], p[1] - mypos[1])})
        self.alive = alive
        self.team_alive = alive.get(my_team, 0)
        self.enemy_alive = alive.get(3 if my_team == 2 else 2, 0)
        mates.sort(key=lambda m: m["dist"])
        self.nearest_teammate_dist = mates[0]["dist"] if mates else None
        self.trade_support = ("HIGH" if (mates and mates[0]["dist"] <= 1600.0)
                              else "MED" if (mates and mates[0]["dist"] <= 3200.0) else "LOW")

        # recent events in window
        ev = {"shots": 0, "damage_taken": 0, "damage_dealt": 0, "kills_near": 0,
              "reloads": 0, "deaths_team": 0, "grenades": 0}
        for d in self.demo.events["damages"]:
            if not (self.window[0] <= d["tick"] <= self.window[1]):
                continue
            if d["user_steamid"] == self.steamid:
                ev["damage_taken"] += 1
            if d["attacker_steamid"] == self.steamid:
                ev["damage_dealt"] += 1
        for s in self.demo.events["shots"]:
            if self.window[0] <= s["tick"] <= self.window[1] and s["user_steamid"] == self.steamid:
                ev["shots"] += 1
        for r_ in self.demo.events["reloads"]:
            if self.window[0] <= r_["tick"] <= self.window[1] and r_.get("user_steamid") == self.steamid:
                ev["reloads"] += 1
        for k in self.demo.events["kills"]:
            if self.window[0] <= k["tick"] <= self.window[1]:
                if k["user_steamid"] in teams and teams[k["user_steamid"]] == my_team:
                    ev["deaths_team"] += 1
        for g in self.demo.events["grenades"].values():
            for gg in g:
                if self.window[0] <= gg["tick"] <= self.window[1] and gg.get("user_steamid") == self.steamid:
                    ev["grenades"] += 1
        self.events = ev

        # bomb / objective
        bounds = self.demo.round_bounds(self.demo.round_of_tick(self.tick))
        self.round_time_s = (bounds[1] - self.tick) / 64.0 if bounds else 0.0
        planted = any(b["tick"] <= self.tick for b in self.demo.events["bombs"]["planted"])
        self.bomb_planted = planted
        self.bomb_site = next((b.get("site") for b in reversed(self.demo.events["bombs"]["planted"])
                               if b["tick"] <= self.tick), None)
        self.objective_urgency = ("HIGH" if (planted and self.round_time_s < self.cfg.objective_urgency_bomb_s)
                                  else "MED" if planted else "LOW")

        # known enemy
        self.n_known_enemies = self.known.get("n_known_enemies", 0)
        self.last_known_positions = [v["pos"] for v in self.known.get("last_seen_enemies", {}).values()
                                     if v.get("pos")]
        self.info_update_recency = min(999, min(
            (self.tick - v["tick"] for v in self.known.get("last_seen_enemies", {}).values()),
            default=999))

    def summary(self) -> dict:
        """Compact serializable summary (for context_events / review)."""
        return {
            "trajectory_len": len(self.trajectory),
            "zone_crossings": self.zone_crossings,
            "zones": dict(self.zone_set),
            "time_moving_ticks": self.time_moving_ticks,
            "heading_consistency": round(self.heading_consistency, 3),
            "team_alive": self.team_alive, "enemy_alive": self.enemy_alive,
            "nearest_teammate_dist": round(self.nearest_teammate_dist, 1) if self.nearest_teammate_dist else None,
            "trade_support": self.trade_support,
            "events": self.events,
            "round_time_s": round(self.round_time_s, 1),
            "bomb_planted": self.bomb_planted, "bomb_site": self.bomb_site,
            "objective_urgency": self.objective_urgency,
            "n_known_enemies": self.n_known_enemies,
            "info_update_recency": self.info_update_recency,
            "norm_origin": self.trajectory[0]["pos"] if self.trajectory else None,
            "norm_head": self.trajectory[-1]["pos"] if self.trajectory else None,
        }

    def feature_sequence(self) -> list[dict]:
        """Normalized per-timestep features (§29) for the tiny-model dataset."""
        out = []
        for s in self.trajectory:
            out.append({
                "x": round(s["pos"][0], 4), "y": round(s["pos"][1], 4),
                "speed": round(min(1.0, s["speed"] / 350.0), 4),
                "yaw_sin": round(math.sin(math.radians(s["yaw"] or 0.0)), 4),
                "yaw_cos": round(math.cos(math.radians(s["yaw"] or 0.0)), 4),
                "zone": s["zone"], "alive": 1 if s["alive"] else 0,
            })
        return out


def build_temporal_context(demo, cfg, idx, steamid, tick, known_state=None) -> TemporalContext:
    return TemporalContext(demo, cfg, idx, steamid, tick, known_state)
