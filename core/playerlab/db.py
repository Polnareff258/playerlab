"""SQLite storage for PlayerLab (stdlib sqlite3).

Schema (DESIGN.md §3): matches / rounds / players / decision_points /
decision_states / outcomes. All JSON blobs are schema-versioned payloads;
the similarity index is a derived artifact, rebuilt on demand.
"""
from __future__ import annotations

import json
import math
import os
import sqlite3


def js(value):
    """Recursively sanitize NaN/Infinity to None (strict-JSON safe)."""
    if isinstance(value, float):
        return None if (math.isnan(value) or math.isinf(value)) else value
    if isinstance(value, list):
        return [js(v) for v in value]
    if isinstance(value, dict):
        return {k: js(v) for k, v in value.items()}
    return value


def jd(value, **kw):
    return json.dumps(js(value), ensure_ascii=False, **kw)

SCHEMA = """
CREATE TABLE IF NOT EXISTS matches (
    demo_id TEXT PRIMARY KEY,
    demo_path TEXT, map_name TEXT, tickrate INTEGER, player_count INTEGER,
    rounds_total INTEGER, side_swap_round INTEGER,
    parsed_at TEXT, parser_version TEXT
);
CREATE TABLE IF NOT EXISTS rounds (
    match_id TEXT, round INTEGER, start_tick INTEGER, end_tick INTEGER,
    winner TEXT, reason TEXT, PRIMARY KEY (match_id, round)
);
CREATE TABLE IF NOT EXISTS players (
    match_id TEXT, steamid INTEGER, name TEXT, team_number INTEGER,
    PRIMARY KEY (match_id, steamid)
);
CREATE TABLE IF NOT EXISTS decision_points (
    dp_id TEXT PRIMARY KEY, match_id TEXT, round INTEGER, steamid INTEGER,
    player_name TEXT, start_tick INTEGER, decision_tick INTEGER, end_tick INTEGER,
    observed_action TEXT, alternatives TEXT, zone TEXT, place TEXT,
    confidence REAL, significance REAL, evidence TEXT, meta TEXT
);
CREATE TABLE IF NOT EXISTS decision_states (
    dp_id TEXT PRIMARY KEY, match_id TEXT, round INTEGER, decision_tick INTEGER,
    map TEXT, side TEXT, zone TEXT, observed_action TEXT,
    features TEXT, labels TEXT, known_state TEXT, public_info TEXT,
    ground_truth TEXT
);
CREATE TABLE IF NOT EXISTS outcomes (
    dp_id TEXT PRIMARY KEY, survival INTEGER, survival_window_ticks INTEGER,
    death_tick INTEGER, duel_result TEXT, duel_opponent TEXT, round_win INTEGER
);
CREATE TABLE IF NOT EXISTS coverage (
    map TEXT, side TEXT, zone TEXT, action TEXT, n INTEGER, PRIMARY KEY (map, side, zone, action)
);
CREATE INDEX IF NOT EXISTS idx_dp_match ON decision_points (match_id);
CREATE INDEX IF NOT EXISTS idx_ds_match ON decision_states (match_id);
"""


class DB:
    def __init__(self, path: str):
        self.path = path
        if path != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self):
        self.conn.close()

    # ---- matches ----
    def upsert_match(self, m: dict):
        self.conn.execute(
            """INSERT OR REPLACE INTO matches
               (demo_id, demo_path, map_name, tickrate, player_count, rounds_total,
                side_swap_round, parsed_at, parser_version)
               VALUES (:demo_id, :demo_path, :map_name, :tickrate, :player_count,
                       :rounds_total, :side_swap_round, :parsed_at, :parser_version)""", m)
        self.conn.commit()

    def list_matches(self):
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM matches ORDER BY parsed_at DESC")]

    def get_match(self, demo_id: str):
        r = self.conn.execute("SELECT * FROM matches WHERE demo_id=?", (demo_id,)).fetchone()
        return dict(r) if r else None

    # ---- rounds / players ----
    def replace_rounds(self, match_id, rounds):
        self.conn.execute("DELETE FROM rounds WHERE match_id=?", (match_id,))
        self.conn.executemany(
            """INSERT OR REPLACE INTO rounds (match_id, round, start_tick, end_tick, winner, reason)
               VALUES (?,?,?,?,?,?)""",
            [(match_id, r["round"], r["start_tick"], r["end_tick"], r["winner"], r["reason"])
             for r in rounds])
        self.conn.commit()

    def get_rounds(self, match_id):
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM rounds WHERE match_id=? ORDER BY round", (match_id,))]

    def replace_players(self, match_id, players):
        self.conn.execute("DELETE FROM players WHERE match_id=?", (match_id,))
        self.conn.executemany(
            "INSERT OR REPLACE INTO players (match_id, steamid, name, team_number) VALUES (?,?,?,?)",
            [(match_id, p["steamid"], p["name"], p["team_number"]) for p in players])
        self.conn.commit()

    def get_players(self, match_id):
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM players WHERE match_id=? ORDER BY team_number, name", (match_id,))]

    # ---- decision points ----
    def insert_dp(self, dp: dict, state: dict, outcome: dict):
        with self.conn:
            self.conn.execute(
                """INSERT OR REPLACE INTO decision_points
                   (dp_id, match_id, round, steamid, player_name, start_tick, decision_tick,
                    end_tick, observed_action, alternatives, zone, place, confidence,
                    significance, evidence, meta)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (dp["dp_id"], dp["match_id"], dp["round"], dp["steamid"], dp["player_name"],
                 dp["start_tick"], dp["decision_tick"], dp["end_tick"], dp["observed_action"],
                 jd(dp["alternatives"]), dp["zone"], dp["place"],
                 dp["confidence"], dp["significance"],
                 jd(dp["evidence"]),
                 jd(dp.get("meta", {}))))
            self.conn.execute(
                """INSERT OR REPLACE INTO decision_states
                   (dp_id, match_id, round, decision_tick, map, side, zone, observed_action,
                    features, labels, known_state, public_info, ground_truth)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (state["dp_id"], state["match_id"], state["round"], state["decision_tick"],
                 state["map"], state["side"], state["zone"], state["observed_action"],
                 jd(state["features"]),
                 jd(state["labels"]),
                 jd(state["known_state"]),
                 jd(state["public_info"]),
                 jd(state["ground_truth"])))
            self.conn.execute(
                """INSERT OR REPLACE INTO outcomes (dp_id, survival, survival_window_ticks,
                   death_tick, duel_result, duel_opponent, round_win)
                   VALUES (?,?,?,?,?,?,?)""",
                (outcome["dp_id"], outcome["survival"], outcome["survival_window_ticks"],
                 outcome["death_tick"], outcome["duel_result"], outcome["duel_opponent"],
                 outcome["round_win"]))

    def get_dps(self, match_id):
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM decision_points WHERE match_id=? ORDER BY decision_tick", (match_id,))]

    def get_dp(self, dp_id: str):
        r = self.conn.execute("SELECT * FROM decision_points WHERE dp_id=?", (dp_id,)).fetchone()
        if not r:
            return None
        dp = dict(r)
        dp["alternatives"] = json.loads(dp["alternatives"])
        dp["evidence"] = json.loads(dp["evidence"])
        dp["meta"] = json.loads(dp["meta"])
        return dp

    def get_state(self, dp_id: str):
        r = self.conn.execute("SELECT * FROM decision_states WHERE dp_id=?", (dp_id,)).fetchone()
        if not r:
            return None
        s = dict(r)
        for k in ("features", "labels", "known_state", "public_info", "ground_truth"):
            s[k] = json.loads(s[k])
        return s

    def get_outcome(self, dp_id: str):
        r = self.conn.execute("SELECT * FROM outcomes WHERE dp_id=?", (dp_id,)).fetchone()
        return dict(r) if r else None

    def all_states(self, match_id=None):
        q = "SELECT * FROM decision_states"
        args = ()
        if match_id:
            q += " WHERE match_id=?"
            args = (match_id,)
        rows = []
        for r in self.conn.execute(q, args):
            s = dict(r)
            for k in ("features", "labels", "known_state", "public_info", "ground_truth"):
                s[k] = json.loads(s[k])
            rows.append(s)
        return rows

    # ---- coverage ----
    def rebuild_coverage(self):
        self.conn.execute("DELETE FROM coverage")
        rows = self.conn.execute(
            """SELECT map, side, zone, observed_action AS action, COUNT(*) AS n
               FROM decision_states GROUP BY map, side, zone, observed_action""").fetchall()
        self.conn.executemany(
            "INSERT OR REPLACE INTO coverage (map, side, zone, action, n) VALUES (?,?,?,?,?)",
            [(r["map"], r["side"], r["zone"], r["action"], r["n"]) for r in rows])
        self.conn.commit()

    def get_coverage(self):
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM coverage ORDER BY map, side, zone, action")]
