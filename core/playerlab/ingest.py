"""Ingestion: .dem -> canonical in-memory model + canonical JSON + DB rows.

Reuses demoparser2 0.42 (pinned) behind the CS2DataAdapter seam (DESIGN.md
§2/§5). Side determination uses bomb-plant events (planter's team = T that
round); rounds without plants inherit the nearest planted round's T side.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass, field

import pandas as pd

from . import __version__
from .config import Config
from .db import DB
from .fieldmap import CANONICAL_FIELDS, parser_props, rename_columns, team_name

EVENT_NAMES = {
    "kills": "player_death",
    "damages": "player_hurt",
    "shots": "weapon_fire",
    "footsteps": "player_footstep",
    "purchases": "item_purchase",
}

SITE_CODE = {97: "A", 98: "B"}


def clean(v):
    """Convert pandas/NaN values to JSON-safe primitives."""
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(v, (list, tuple)):
        return [clean(x) for x in v]
    if isinstance(v, dict):
        return {k: clean(x) for k, x in v.items()}
    if isinstance(v, float) and v.is_integer():
        return int(v)
    return v


def df_to_records(df) -> list[dict]:
    return [{k: clean(v) for k, v in rec.items()} for rec in df.to_dict("records")]


@dataclass
class IngestedDemo:
    demo_id: str
    demo_path: str
    header: dict
    players: list[dict]
    rounds: list[dict]
    sides: dict  # round -> T-side team number (bomb-plant fallback)
    player_sides: dict  # (steamid, round) -> "T"|"CT" (per-tick m_iTeamNum)
    events: dict
    ticks: pd.DataFrame
    tick_range: tuple
    parsed_at: str = ""
    parser_version: str = "demoparser2 0.42.0"

    def player_steamids(self) -> set[int]:
        return {p["steamid"] for p in self.players}

    def team_of(self, steamid: int) -> int:
        for p in self.players:
            if p["steamid"] == steamid:
                return p["team_number"]
        return -1

    def round_of_tick(self, tick: int) -> int:
        for r in self.rounds:
            if r["start_tick"] <= tick <= r["end_tick"]:
                return r["round"]
        return 0

    def round_bounds(self, rnum: int):
        for r in self.rounds:
            if r["round"] == rnum:
                return r["start_tick"], r["end_tick"]
        return None

    def side_at_round(self, steamid: int, rnum: int) -> str:
        """Side (T/CT) of a player's team in a given round. Uses the per-tick
        team number when available (halftime exact), else bomb-plant fallback."""
        direct = self.player_sides.get((steamid, rnum))
        if direct:
            return direct
        team = self.team_of(steamid)
        t_team = self.sides.get(rnum)
        if t_team is None:
            return "unknown"
        return "T" if team == t_team else "CT"


def _tick_state_index(demo: "IngestedDemo"):
    """Index ticks by (steamid, tick) for O(1) lookups."""
    idx = {}
    df = demo.ticks
    for rec in df.to_dict("records"):
        idx[(rec["steamid"], rec["tick"])] = rec
    return idx


STEAMID_KEYS = ("user_steamid", "attacker_steamid", "steamid", "assister_steamid")

CACHE_VERSION = "v3"  # bump when tick-property parsing changes


def vec(series, i):
    """Expand the i-th component of a vector-typed column to a scalar list."""
    out = []
    for v in series:
        if isinstance(v, (list, tuple)) and len(v) > i:
            out.append(clean(v[i]))
        else:
            out.append(None)
    return out


def derive_velocity(df) -> "pd.DataFrame":
    """Derive velocity from position deltas (64 tick): u/tick * 64 = u/s.
    Teleport/respawn deltas (>5000 u/tick) are zeroed; dead players get 0.
    (m_vecBaseVelocity is never updated in CS2 demos — verified in spike.)"""
    g = df.groupby("steamid", sort=False)
    dvx = g["x"].diff().fillna(0.0) * 64.0
    dvy = g["y"].diff().fillna(0.0) * 64.0
    dvz = g["z"].diff().fillna(0.0) * 64.0
    dist = (dvx ** 2 + dvy ** 2 + dvz ** 2) ** 0.5
    teleport = dist > 5000.0
    df["vx"] = dvx.mask(teleport, 0.0)
    df["vy"] = dvy.mask(teleport, 0.0)
    df["vz"] = dvz.mask(teleport, 0.0)
    df["speed"] = ((df["vx"] ** 2 + df["vy"] ** 2 + df["vz"] ** 2) ** 0.5)
    df.loc[df["is_alive"] != True, ["vx", "vy", "vz", "speed"]] = 0.0  # noqa: E712
    return df


def normalize_steamids(records: list[dict]) -> list[dict]:
    """Coerce steamid fields to int (demoparser2 returns them as strings in
    some events, ints in others — normalize once at the adapter boundary)."""
    for rec in records:
        for key in STEAMID_KEYS:
            val = rec.get(key)
            if val is not None:
                try:
                    rec[key] = int(val)
                except (TypeError, ValueError):
                    pass
    return records


def _ticks_cache_path(demo_id: str, cfg: Config | None = None) -> str:
    base = os.path.join(cfg.data_dir, "analyses") if cfg else os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "analyses")
    return os.path.join(base, f"{demo_id}.ticks.{CACHE_VERSION}.pickle")


def parse_demo(demo_path: str, cfg: Config | None = None) -> IngestedDemo:
    from demoparser2 import DemoParser  # lazy import keeps module importable w/o parser

    t0 = time.time()
    parser = DemoParser(demo_path)

    header = parser.parse_header()
    if not isinstance(header, dict):
        header = dict(header)

    # players
    pif = parser.parse_player_info()
    players = [{"steamid": int(r["steamid"]), "name": str(r["name"]),
                "team_number": int(r["team_number"])} for r in pif.to_dict("records")]

    # rounds
    rs = parser.parse_event("round_start")
    re_ = parser.parse_event("round_end")
    rounds = []
    for i in range(min(len(rs), len(re_))):
        rounds.append({"round": int(rs["round"].iloc[i]),
                       "start_tick": int(rs["tick"].iloc[i]),
                       "end_tick": int(re_["tick"].iloc[i]),
                       "winner": str(re_["winner"].iloc[i]),
                       "reason": str(re_["reason"].iloc[i])})
    rounds.sort(key=lambda r: r["round"])

    # sides via bomb plants (planter team = T)
    plants = parser.parse_event("bomb_planted")
    planter_team_by_round = {}
    for r in plants.to_dict("records"):
        rnum = None
        for rr in rounds:
            if rr["start_tick"] <= int(r["tick"]) <= rr["end_tick"]:
                rnum = rr["round"]
                break
        if rnum is None:
            continue
        steamid = int(r["user_steamid"])
        team = next((p["team_number"] for p in players if p["steamid"] == steamid), None)
        if team is not None:
            planter_team_by_round[rnum] = team
    sides = {}
    current = None
    for rr in rounds:
        if rr["round"] in planter_team_by_round:
            current = planter_team_by_round[rr["round"]]
        sides[rr["round"]] = current
    # backfill rounds before the first plant
    current = None
    for rr in reversed(rounds):
        if rr["round"] in planter_team_by_round:
            current = planter_team_by_round[rr["round"]]
        if sides.get(rr["round"]) is None:
            sides[rr["round"]] = current

    # events
    events = {}
    for key, ev in EVENT_NAMES.items():
        try:
            events[key] = normalize_steamids(df_to_records(parser.parse_event(ev)))
        except Exception:  # noqa: BLE001
            events[key] = []
    bombs = {"planted": normalize_steamids(df_to_records(parser.parse_event("bomb_planted"))),
             "defused": normalize_steamids(df_to_records(parser.parse_event("bomb_defused")))}
    for rec in bombs["planted"] + bombs["defused"]:
        if isinstance(rec.get("site"), (int, float)) and rec["site"] in SITE_CODE:
            rec["site"] = SITE_CODE[int(rec["site"])]
    events["bombs"] = bombs
    grenade_events = {}
    for gname in ("hegrenade_detonate", "smokegrenade_detonate",
                  "flashbang_detonate", "inferno_startburn"):
        try:
            grenade_events[gname] = normalize_steamids(df_to_records(parser.parse_event(gname)))
        except Exception:  # noqa: BLE001
            grenade_events[gname] = []
    events["grenades"] = grenade_events

    # ticks over the played range only
    start = min(r["start_tick"] for r in rounds) - 1
    end = max(r["end_tick"] for r in rounds) + 1
    demo_id = hashlib.sha256(os.path.abspath(demo_path).encode("utf-8")).hexdigest()[:16]

    cache_path = _ticks_cache_path(demo_id, cfg) if cfg else ""
    if cache_path and os.path.isfile(cache_path):
        ticks_df = pd.read_pickle(cache_path)
    else:
        ticks_df = rename_columns(parser.parse_ticks(
            parser_props(), ticks=list(range(start, end + 1))))
        # position columns are already scalar (m_vecX/Y/Z); expand view vector
        ticks_df["pitch"], ticks_df["yaw"] = vec(ticks_df["view"], 0), vec(ticks_df["view"], 1)
        ticks_df = ticks_df.drop(columns=["view"], errors="ignore")
        ticks_df = derive_velocity(ticks_df)

    # cache ticks for fast re-analysis (idempotent re-ingest)
    try:
        if cfg is not None and not os.path.exists(cache_path):
            os.makedirs(os.path.dirname(cache_path), exist_ok=True)
            ticks_df.to_pickle(cache_path)
    except Exception:  # noqa: BLE001  caching is best-effort
        pass

    # per-(player, round) side from per-tick team numbers (halftime exact)
    player_sides = {}
    starts = {r["start_tick"] + 1 for r in rounds}
    sub = ticks_df[ticks_df["tick"].isin(starts)] if len(ticks_df) else ticks_df
    for rec in sub.to_dict("records"):
        tn = rec.get("team_num")
        if tn is None:
            continue
        rnum = next((r["round"] for r in rounds
                     if r["start_tick"] <= int(rec["tick"]) <= r["end_tick"]), None)
        if rnum is not None:
            player_sides[(int(rec["steamid"]), rnum)] = team_name(int(tn))

    return IngestedDemo(
        demo_id=demo_id, demo_path=demo_path, header=header, players=players,
        rounds=rounds, sides=sides, player_sides=player_sides, events=events,
        ticks=ticks_df, tick_range=(start, end),
        parsed_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
    )


def canonical_json(demo: IngestedDemo) -> dict:
    """Serializable canonical summary (cs2-demo-format style, PlayerLab subset)."""
    return {
        "meta": {
            "demo_id": demo.demo_id, "demo_path": demo.demo_path,
            "map": demo.header.get("map_name"), "tickrate": demo.header.get("tickrate"),
            "players": len(demo.players), "rounds": len(demo.rounds),
            "parsed_at": demo.parsed_at, "parser": demo.parser_version,
            "tool": f"playerlab-core {__version__}",
        },
        "players": demo.players,
        "rounds": demo.rounds,
        "sides": {str(k): v for k, v in demo.sides.items()},
        "events": demo.events,
        "tick_range": list(demo.tick_range),
        "tick_rows": int(len(demo.ticks)),
    }


def persist(demo: IngestedDemo, cfg: Config, db: DB, analyses_dir: str | None = None) -> str:
    """Write canonical JSON + DB rows. Returns canonical JSON path."""
    if analyses_dir is None:
        analyses_dir = os.path.join(cfg.data_dir, "analyses")
    os.makedirs(analyses_dir, exist_ok=True)
    out_path = os.path.join(analyses_dir, f"{demo.demo_id}.canonical.json")
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(canonical_json(demo), fh, ensure_ascii=False, indent=1)
    match = {
        "demo_id": demo.demo_id, "demo_path": demo.demo_path,
        "map_name": demo.header.get("map_name"), "tickrate": demo.header.get("tickrate"),
        "player_count": len(demo.players), "rounds_total": len(demo.rounds),
        "side_swap_round": None, "parsed_at": demo.parsed_at,
        "parser_version": demo.parser_version,
    }
    db.upsert_match(match)
    db.replace_rounds(demo.demo_id, demo.rounds)
    db.replace_players(demo.demo_id, demo.players)
    return out_path
