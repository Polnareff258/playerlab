"""State layer: PublicInfo, GroundTruth and PlayerKnownState (epistemic model).

PlayerKnownState is the ONLY input to the Decision layer (hindsight guard,
COUNTERFACTUAL_DESIGN §3/§10). All entries carry source + confidence.
Vision is an approximation in V1: FOV cone + distance with a data-calibrated
yaw offset; NO geometric occlusion test (awpy LOS is the upgrade path).
"""
from __future__ import annotations

import functools
import math

from .config import Config
from .ingest import IngestedDemo
from .weapons import name_from_def, weapon_class

DEG = math.pi / 180.0


def wrap180(deg: float) -> float:
    return (deg + 180.0) % 360.0 - 180.0


def angle_diff(a: float, b: float) -> float:
    return abs(wrap180(a - b))


def dist2d(ax, ay, bx, by) -> float:
    return math.hypot(ax - bx, ay - by)


def build_tick_index(demo: IngestedDemo) -> dict:
    """(steamid, tick) -> tick record dict (positions/vel/view/alive/...)."""
    idx = {}
    for rec in demo.ticks.to_dict("records"):
        idx[(rec["steamid"], rec["tick"])] = rec
    return idx


def pos_at(idx, steamid: int, tick: int):
    rec = idx.get((steamid, tick))
    if not rec:
        return None
    x, y = rec.get("x"), rec.get("y")
    if x is None or y is None:
        return None
    return (x, y)


@functools.lru_cache(maxsize=1)
def _calibrated_offset(demo_id: str, demo_path: str) -> float:
    """Median yaw offset so that facing = yaw - offset aligns with
    atan2(dy, dx) toward the target. Calibrated from kill events (attacker
    yaw vs victim direction at kill tick). Deterministic per demo."""
    # re-parse minimal: use kill events + victim/attacker positions at tick
    from demoparser2 import DemoParser
    parser = DemoParser(demo_path)
    kills = parser.parse_event("player_death")
    ticks = parser.parse_ticks([
        "CCSPlayerPawn.CBodyComponentBaseAnimGraph.m_vecX",
        "CCSPlayerPawn.CBodyComponentBaseAnimGraph.m_vecY",
        "CCSPlayerPawn.m_angEyeAngles", "is_alive", "steamid", "name", "tick"],
        ticks=[int(t) for t in kills["tick"].tolist()])
    idx = {}
    for rec in ticks.to_dict("records"):
        idx[(int(rec["steamid"]), int(rec["tick"]))] = rec
    offsets = []
    for rec in kills.to_dict("records"):
        try:
            a_steamid = int(rec["attacker_steamid"])
            v_steamid = int(rec["user_steamid"])
            t = int(rec["tick"])
        except (TypeError, ValueError):
            continue  # world/suicide kills or missing data
        a = idx.get((a_steamid, t))
        v = idx.get((v_steamid, t))
        if not a or not v:
            continue
        ax, ay = a["CCSPlayerPawn.CBodyComponentBaseAnimGraph.m_vecX"], a["CCSPlayerPawn.CBodyComponentBaseAnimGraph.m_vecY"]
        vx, vy = v["CCSPlayerPawn.CBodyComponentBaseAnimGraph.m_vecX"], v["CCSPlayerPawn.CBodyComponentBaseAnimGraph.m_vecY"]
        yaw = a["CCSPlayerPawn.m_angEyeAngles"][1]
        if None in (ax, ay, vx, vy) or yaw is None:
            continue
        d = math.degrees(math.atan2(vy - ay, vx - ax))
        offsets.append(wrap180(yaw - d))
    if not offsets:
        return 0.0
    offsets.sort()
    return offsets[len(offsets) // 2]


def yaw_offset(demo: IngestedDemo) -> float:
    return _calibrated_offset(demo.demo_id, demo.demo_path)


def facing_yaw(rec, offset: float) -> float | None:
    yaw = rec.get("yaw")
    if yaw is None:
        return None
    return wrap180(yaw - offset)


def vision_sees(rec_viewer, rec_target, cfg: Config, offset: float) -> bool:
    """Approximate FOV-cone visibility (no occlusion). False on missing data."""
    fx, fy = rec_viewer.get("x"), rec_viewer.get("y")
    tx, ty = rec_target.get("x"), rec_target.get("y")
    f = facing_yaw(rec_viewer, offset)
    if None in (fx, fy, tx, ty) or f is None:
        return False
    d = dist2d(fx, fy, tx, ty)
    if d > cfg.vision_max_dist:
        return False
    ang = wrap180(math.degrees(math.atan2(ty - fy, tx - fx)))
    return angle_diff(f, ang) <= cfg.vision_fov_deg / 2.0


class PublicInfoBuilder:
    """Public information any player can see (kill feed, scoreboard, bomb)."""

    def __init__(self, demo: IngestedDemo, cfg: Config):
        self.demo = demo
        self.cfg = cfg
        deaths_by_round = {}
        for k in demo.events["kills"]:
            r = demo.round_of_tick(k["tick"])
            deaths_by_round.setdefault(r, []).append(k)
        self.deaths_by_round = deaths_by_round
        self.bomb_events = demo.events["bombs"]

    def score_before(self, rnum: int):
        ct = sum(1 for r in self.demo.rounds if r["round"] < rnum and r["winner"] == "CT")
        t = sum(1 for r in self.demo.rounds if r["round"] < rnum and r["winner"] == "T")
        return {"CT": ct, "T": t}

    def alive_counts(self, tick: int, idx: dict, teams: dict[int, int]):
        alive = {2: 0, 3: 0}
        for steamid, team in teams.items():
            rec = idx.get((steamid, tick))
            if rec and rec.get("is_alive"):
                alive[team] += 1
        return alive

    def bomb_state(self, tick: int) -> dict:
        planted = None
        defused = False
        for b in self.bomb_events["planted"]:
            if b["tick"] <= tick:
                planted = b.get("site") or "?"
        for b in self.bomb_events["defused"]:
            if b["tick"] <= tick:
                defused = True
                planted = None
        return {"planted_site": planted, "defused": defused}

    def build(self, steamid: int, rnum: int, tick: int, idx: dict,
              teams: dict[int, int]) -> dict:
        return {
            "round": rnum,
            "tick": tick,
            "time_remaining_s": round((self.demo.round_bounds(rnum)[1] - tick) / 64.0, 1),
            "score_before": self.score_before(rnum),
            "alive_counts": self.alive_counts(tick, idx, teams),
            "bomb": self.bomb_state(tick),
            "deaths_this_round": len(self.deaths_by_round.get(rnum, [])),
        }


class KnownStateBuilder:
    """Reconstructs what the decision player plausibly knew at a tick."""

    def __init__(self, demo: IngestedDemo, cfg: Config, idx: dict):
        self.demo = demo
        self.cfg = cfg
        self.idx = idx
        self.offset = yaw_offset(demo)
        self.teams = {p["steamid"]: p["team_number"] for p in demo.players}
        self.opponents_of = {}
        for s, t in self.teams.items():
            self.opponents_of[s] = {o for o, ot in self.teams.items() if ot != t and ot in (2, 3)}
        # tick-indexed events so per-tick known-state builds scan only the
        # window instead of the full event log (V1.2.1 intent-sample volume).
        from collections import defaultdict
        self._ev = {}
        for key in ("damages", "footsteps", "shots", "kills"):
            lst = sorted(self.demo.events.get(key, []), key=lambda e: int(e["tick"]))
            self._ev[key] = ([int(e["tick"]) for e in lst], lst)
        self._grenades = []
        for gname, glist in self.demo.events.get("grenades", {}).items():
            for g in glist:
                self._grenades.append({**g, "kind": gname, "tick": int(g["tick"])})
        self._grenades.sort(key=lambda g: g["tick"])
        self._bomb_planted = sorted(
            (int(b["tick"]) for b in self.demo.events["bombs"].get("planted", [])), reverse=True)
        self._bomb_defused = sorted(
            (int(b["tick"]) for b in self.demo.events["bombs"].get("defused", [])), reverse=True)
        self._plants_start = sorted(
            self.demo.events.get("plants_start", []), key=lambda e: int(e["tick"]))

    def _events_in(self, key: str, lo: int, hi: int) -> list:
        import bisect
        ticks, lst = self._ev[key]
        i = bisect.bisect_left(ticks, lo)
        j = bisect.bisect_right(ticks, hi)
        return lst[i:j]

    def _enemy_pos_at(self, enemy: int, tick: int):
        return pos_at(self.idx, enemy, tick)

    def _zone_of(self, enemy: int, tick: int) -> str | None:
        """Map zone of an enemy's position at a tick (from its place name)."""
        rec = self.idx.get((enemy, tick))
        if not rec:
            return None
        from .zones import zone_for
        return zone_for(self.demo.header.get("map_name"), rec.get("place") or "")

    def seen_now(self, viewer: int, tick: int) -> list[dict]:
        """Enemies currently inside the viewer's FOV cone (approx, no occlusion)."""
        vrec = self.idx.get((viewer, tick))
        if not vrec or not vrec.get("is_alive"):
            return []
        out = []
        for enemy in self.opponents_of[viewer]:
            erec = self.idx.get((enemy, tick))
            if not erec or not erec.get("is_alive"):
                continue
            if vision_sees(vrec, erec, self.cfg, self.offset):
                out.append({"enemy": enemy, "pos": pos_at(self.idx, enemy, tick),
                            "tick": tick, "source": "own_vision"})
        return out

    def build(self, steamid: int, rnum: int, tick: int) -> dict:
        cfg = self.cfg
        memory = cfg.known_state_memory_ticks
        last_seen = {}   # enemy -> {pos, tick, source}
        heard = []

        # 1) own + teammate vision
        viewers = [steamid]
        if cfg.team_comms:
            viewers += [s for s in self.teams
                        if self.teams[s] == self.teams[steamid] and s != steamid]
        for viewer in viewers:
            for hit in self.seen_now(viewer, tick):
                prev = last_seen.get(hit["enemy"])
                if prev is None or prev["tick"] < hit["tick"]:
                    last_seen[hit["enemy"]] = {"pos": hit["pos"], "tick": tick,
                                               "source": "own_vision" if viewer == steamid else "team_vision"}

        # 2) damage taken -> know attacker's location (longer memory: you know
        #    where you were shot from until the info is superseded)
        damage_memory = getattr(cfg, "damage_memory_ticks", 1024)
        for d in self._events_in("damages", tick - damage_memory, tick):
            if d["user_steamid"] != steamid:
                continue
            att = d["attacker_steamid"]
            pos = self._enemy_pos_at(att, d["tick"])
            prev = last_seen.get(att)
            if pos is not None and (prev is None or prev["tick"] <= d["tick"]):
                last_seen[att] = {"pos": pos, "tick": d["tick"], "source": "damage"}

        # 3) footsteps heard (enemies within radius, position at event tick)
        mem = self.cfg.known_state_memory_ticks
        for f in self._events_in("footsteps", tick - mem, tick):
            enemy = f["user_steamid"]
            if enemy not in self.opponents_of[steamid]:
                continue
            pos = self._enemy_pos_at(enemy, f["tick"])
            mypos = pos_at(self.idx, steamid, f["tick"])
            if pos and mypos and dist2d(*mypos, *pos) <= cfg.footstep_hear_radius:
                heard.append({"type": "footstep", "tick": f["tick"], "pos": pos})
                prev = last_seen.get(enemy)
                if prev is None or prev["tick"] <= f["tick"]:
                    last_seen[enemy] = {"pos": pos, "tick": f["tick"], "source": "footstep"}

        # 4) shots heard
        for s in self._events_in("shots", tick - mem, tick):
            enemy = s["user_steamid"]
            if enemy not in self.opponents_of[steamid]:
                continue
            pos = self._enemy_pos_at(enemy, s["tick"])
            mypos = pos_at(self.idx, steamid, s["tick"])
            if pos and mypos and dist2d(*mypos, *pos) <= cfg.shot_hear_radius:
                heard.append({"type": "shot", "weapon": s["weapon"], "tick": s["tick"], "pos": pos})

        # 5) grenades heard
        import bisect as _bi
        _gts = [g["tick"] for g in self._grenades]
        for g in self._grenades[_bi.bisect_left(_gts, tick - mem): _bi.bisect_right(_gts, tick)]:
            mypos = pos_at(self.idx, steamid, g["tick"])
            gpos = (g.get("x"), g.get("y"))
            if not mypos or None in gpos:
                continue
            if dist2d(*mypos, *gpos) <= cfg.grenade_hear_radius:
                heard.append({"type": "grenade", "kind": g["kind"],
                              "tick": g["tick"], "pos": gpos})

        # decay last_seen by memory window
        last_seen = {e: v for e, v in last_seen.items() if tick - v["tick"] <= memory}
        known_positions = [v["pos"] for v in last_seen.values() if v["pos"]]

        spread = 0.0
        if len(known_positions) >= 2:
            s = 0.0
            c = 0
            for i in range(len(known_positions)):
                for j in range(i + 1, len(known_positions)):
                    s += dist2d(*(known_positions[i] + known_positions[j]))
                    c += 1
            spread = s / max(1, c)
        nearest = None
        mypos = pos_at(self.idx, steamid, tick)
        if mypos:
            ds = [dist2d(*mypos, *p) for p in known_positions]
            nearest = min(ds) if ds else None

        myrec = self.idx.get((steamid, tick))
        own_money = myrec.get("money") if myrec else None
        own_hp = myrec.get("health") if myrec else None
        own_weapon_def = myrec.get("weapon_def") if myrec else None

        # teammates visible to the player (own FOV only; public-ish via vision)
        teammate_near = 0
        teammate_mid = 0
        if myrec and myrec.get("is_alive"):
            for mate in self.teams:
                if mate == steamid or self.teams[mate] != self.teams[steamid]:
                    continue
                mrec = self.idx.get((mate, tick))
                if not mrec or not mrec.get("is_alive"):
                    continue
                if not vision_sees(myrec, mrec, self.cfg, self.offset):
                    continue
                d = dist2d(*(pos_at(self.idx, steamid, tick) or (0, 0)),
                           *(pos_at(self.idx, mate, tick) or (0, 0)))
                if d <= 1600.0:
                    teammate_near += 1
                elif d <= 3200.0:
                    teammate_mid += 1

        # ---- V1.2.1 KnownState grounding (spec §2) --------------------------
        # zone per known enemy (for InformationDirection aggregation)
        for e, v in last_seen.items():
            v["zone"] = self._zone_of(int(e), v["tick"])
        known_enemy_zones = [v.get("zone") for v in last_seen.values() if v.get("zone")]
        # directions: enemy zone semantics relative to the player's map half
        known_enemy_directions = [v["zone"] for v in last_seen.values()
                                  if v.get("zone") in ("A", "B", "MID", "CT", "T", "LONG")]

        def _min_age(*sources):
            ages = [tick - v["tick"] for v in last_seen.values()
                    if v.get("source") in sources and v["tick"] <= tick]
            return min(ages) if ages else None

        time_since_last_known_enemy_update = min(
            (tick - v["tick"] for v in last_seen.values() if v["tick"] <= tick), default=None)
        time_since_visual_contact = _min_age("own_vision", "team_vision")
        time_since_damage_contact = _min_age("damage")
        recent_sound = [h for h in heard if tick - h["tick"] <= self.cfg.teammate_contact_window_ticks]

        # bomb known: planted is public; carrier is public via bomb status.
        planted_now = bool(self._bomb_planted and self._bomb_planted[0] <= tick)
        defused_now = bool(self._bomb_defused and self._bomb_defused[0] <= tick)
        bomb_known = bool(planted_now) and not defused_now
        bomb_zone = None
        bomb_confidence = 0.0
        if bomb_known:
            bomb_zone = next((b.get("site") for b in reversed(self.demo.events["bombs"]["planted"])
                              if b["tick"] <= tick), None)
            bomb_confidence = 0.9 if bomb_zone in ("A", "B") else 0.5
        else:
            # carrier known publicly while alive (bomb icon in the HUD)
            carrier = None
            for b in self._plants_start:
                if b["tick"] <= tick and b.get("user_steamid"):
                    carrier = b["user_steamid"]
                    break
            if carrier is not None:
                pos = pos_at(self.idx, carrier, tick)
                zone = self._zone_of(carrier, tick) if pos else None
                bomb_known = True
                bomb_zone = zone
                bomb_confidence = 0.6 if pos else 0.4

        # teammate contact count in window: teammates visible or within radius
        teammate_contact_count = teammate_near + teammate_mid
        if myrec and myrec.get("is_alive"):
            for mate in self.teams:
                if mate == steamid or self.teams[mate] != self.teams[steamid]:
                    continue
                mrec = self.idx.get((mate, tick))
                if not mrec or not mrec.get("is_alive"):
                    continue
                if not vision_sees(myrec, mrec, self.cfg, self.offset):
                    continue
                d = dist2d(*(pos_at(self.idx, steamid, tick) or (0, 0)),
                           *(pos_at(self.idx, mate, tick) or (0, 0)))
                if d <= 1600.0:
                    teammate_contact_count += 1

        # recent teammate kill/death from the public feed
        feed_win = self.cfg.public_feed_window_ticks
        my_team_num = self.teams.get(steamid, -1)
        recent_teammate_kill = any(
            k["tick"] > tick - feed_win and k["tick"] <= tick
            and k.get("attacker_steamid") in self.teams
            and self.teams[k["attacker_steamid"]] == my_team_num
            for k in self._events_in("kills", tick - feed_win, tick))
        recent_teammate_death = any(
            k["tick"] > tick - feed_win and k["tick"] <= tick
            and k.get("user_steamid") in self.teams
            and self.teams[k["user_steamid"]] == my_team_num
            for k in self._events_in("kills", tick - feed_win, tick))

        # alive counts from tick index (no ground-truth shortcut)
        _alive = {2: 0, 3: 0}
        for _s, _t in self.teams.items():
            _rec = self.idx.get((_s, tick))
            if _rec and _rec.get("is_alive"):
                _alive[_t] = _alive.get(_t, 0) + 1
        objective_information = {
            "bomb_planted": bomb_known and bool(planted_now) and not defused_now,
            "bomb_site": bomb_zone,
            "round_time_s": round((self.demo.round_bounds(rnum)[1] - tick) / 64.0, 1)
            if self.demo.round_bounds(rnum) else None,
            "alive_counts": {str(k): v for k, v in _alive.items()},
        }

        info_dict = dict(last_seen)  # information.py reads zone per enemy
        return {
            "last_seen_enemies": {str(e): {"pos": v["pos"], "tick": v["tick"],
                                           "source": v["source"], "zone": v.get("zone")}
                                  for e, v in last_seen.items()},
            "n_known_enemies": len(last_seen),
            "known_enemy_count": len(last_seen),
            "known_enemy_zones": known_enemy_zones,
            "known_enemy_directions": known_enemy_directions,
            "time_since_last_known_enemy_update": time_since_last_known_enemy_update,
            "time_since_visual_contact": time_since_visual_contact,
            "time_since_damage_contact": time_since_damage_contact,
            "recent_sound_info": recent_sound,
            "bomb_known": bomb_known,
            "bomb_zone": bomb_zone,
            "bomb_confidence": round(bomb_confidence, 3),
            "teammate_contact_count": teammate_contact_count,
            "recent_teammate_kill": recent_teammate_kill,
            "recent_teammate_death": recent_teammate_death,
            "objective_information": objective_information,
            "known_spread": spread,
            "nearest_known_enemy": nearest,
            "heard": heard[-20:],
            "teammate_near": teammate_near,
            "teammate_mid": teammate_mid,
            "own": {"hp": own_hp, "money": own_money,
                    "weapon_def": own_weapon_def,
                    "weapon_class": weapon_class(name_from_def(own_weapon_def))
                    if own_weapon_def is not None else "unknown"},
            "vision_model": "approx_fov_no_occlusion_v1",
        }


def build_ground_truth(demo: IngestedDemo, idx: dict, steamid: int, tick: int) -> dict:
    """Full omniscient state at a tick (outcome/replay/debug ONLY)."""
    enemies = []
    team = demo.team_of(steamid)
    for p in demo.players:
        if p["team_number"] not in (2, 3) or p["team_number"] == team:
            continue
        rec = idx.get((p["steamid"], tick))
        if not rec:
            continue
        enemies.append({
            "steamid": p["steamid"], "name": p["name"],
            "pos": [rec.get("x"), rec.get("y"), rec.get("z")],
            "hp": rec.get("health"), "alive": bool(rec.get("is_alive")),
            "weapon_def": rec.get("weapon_def"),
            "place": rec.get("place"), "yaw": rec.get("yaw"),
        })
    myrec = idx.get((steamid, tick))
    return {
        "enemies": enemies,
        "self": {"pos": [myrec.get("x"), myrec.get("y"), myrec.get("z")] if myrec else None,
                 "hp": myrec.get("health") if myrec else None,
                 "yaw": myrec.get("yaw") if myrec else None,
                 "place": myrec.get("place") if myrec else None},
    }
