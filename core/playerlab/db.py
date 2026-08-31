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

# V1.1-alpha schema (schema_version = 2). Tables are additive; existing V1
# tables are never altered.
ALPHA_SCHEMA = """
CREATE TABLE IF NOT EXISTS execution_metrics (
    id TEXT PRIMARY KEY, match_id TEXT, round INTEGER, tick INTEGER, steamid INTEGER,
    metric TEXT, value REAL, threshold REAL, violation INTEGER, evidence TEXT, meta TEXT
);
CREATE TABLE IF NOT EXISTS patterns (
    pattern_id TEXT PRIMARY KEY, pattern_type TEXT, name TEXT, category TEXT,
    sample_count INTEGER, opportunity_count INTEGER, violation_count INTEGER,
    violation_rate REAL, positive_examples INTEGER, negative_examples INTEGER,
    confidence REAL, counterfactual_support TEXT, affected_contexts TEXT,
    evidence_refs TEXT, computed_at TEXT
);
CREATE TABLE IF NOT EXISTS pattern_evidence (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pattern_id TEXT, kind TEXT, match_id TEXT, round INTEGER, tick INTEGER,
    dp_id TEXT, detail TEXT
);
CREATE TABLE IF NOT EXISTS root_causes (
    event_id TEXT PRIMARY KEY, match_id TEXT, round INTEGER, tick INTEGER, steamid INTEGER,
    result TEXT, execution TEXT, micro TEXT, macro TEXT,
    primary_cause TEXT, secondary_cause TEXT, mechanical_cause TEXT, confidence REAL
);
CREATE TABLE IF NOT EXISTS training_targets (
    target_id TEXT PRIMARY KEY, pattern_type TEXT, name TEXT, category TEXT,
    trigger TEXT, undesired_behavior TEXT, replacement_behavior TEXT,
    baseline REAL, goal REAL, measurement_definition TEXT, measurement_window INTEGER,
    status TEXT, progress REAL, confidence REAL, created_at TEXT, next_match_cue TEXT,
    source_pattern_ids TEXT, supporting_evidence TEXT
);
CREATE TABLE IF NOT EXISTS target_measurements (
    id TEXT PRIMARY KEY, target_id TEXT, window_start TEXT, window_end TEXT,
    opportunities INTEGER, violations INTEGER, rate REAL, rate_ci TEXT,
    delta_vs_baseline REAL, behavior_verdict TEXT, execution_verdict TEXT, outcome_verdict TEXT
);
CREATE TABLE IF NOT EXISTS target_status_history (
    id TEXT PRIMARY KEY, target_id TEXT, from_status TEXT, status TEXT, at TEXT, reason TEXT
);
CREATE TABLE IF NOT EXISTS human_annotations (
    id TEXT PRIMARY KEY, match_id TEXT, round INTEGER, tick INTEGER,
    event_id TEXT, dp_id TEXT, annotation_type TEXT,
    model_version TEXT, rule_version TEXT, config_version TEXT,
    model_prediction TEXT, model_confidence REAL,
    human_label TEXT, human_confidence REAL,
    correction_type TEXT, reason_code TEXT, optional_comment TEXT, created_at TEXT
);
CREATE TABLE IF NOT EXISTS preference_annotations (
    id TEXT PRIMARY KEY, match_id TEXT, round INTEGER, tick INTEGER, event_id TEXT,
    candidates TEXT, human_choice TEXT, human_confidence REAL, reason_code TEXT, created_at TEXT
);
CREATE TABLE IF NOT EXISTS review_queue (
    id TEXT PRIMARY KEY, match_id TEXT, round INTEGER, tick INTEGER,
    event_id TEXT, dp_id TEXT, item_type TEXT, priority REAL, model_prediction TEXT,
    model_confidence REAL, rationale TEXT, status TEXT, created_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_em_match ON execution_metrics (match_id);
CREATE INDEX IF NOT EXISTS idx_rc_match ON root_causes (match_id);
CREATE INDEX IF NOT EXISTS idx_ann_match ON human_annotations (match_id);
CREATE INDEX IF NOT EXISTS idx_rq_status ON review_queue (status, priority);
"""

# V1.2 context & intent schema (schema_version = 3). Additive + one ALTER on
# root_causes (guarded by column-existence check).
V12_SCHEMA = """
CREATE TABLE IF NOT EXISTS context_events (
    id TEXT PRIMARY KEY, match_id TEXT, round INTEGER, tick INTEGER, steamid INTEGER,
    anchor TEXT, commitment TEXT, role TEXT, role_dist TEXT,
    intent TEXT, intent_conf REAL, intent_dist TEXT,
    feasibility TEXT, responsibility TEXT,
    temporal_summary TEXT, event_ref TEXT, computed_at TEXT
);
CREATE TABLE IF NOT EXISTS intent_samples (
    id TEXT PRIMARY KEY, match_id TEXT, round INTEGER, anchor_tick INTEGER,
    start_tick INTEGER, end_tick INTEGER,
    feature_sequence TEXT, hard_events TEXT, player_known_state TEXT,
    commitment_state TEXT, situational_role TEXT,
    rule_prediction TEXT, rule_confidence REAL,
    human_label TEXT, human_confidence REAL, source TEXT,
    model_version TEXT, extractor_version TEXT
);
CREATE INDEX IF NOT EXISTS idx_ctx_match ON context_events (match_id);
CREATE INDEX IF NOT EXISTS idx_int_match ON intent_samples (match_id);
"""

_ADD_COLUMNS = [
    ("root_causes", "context", "TEXT"),
    ("root_causes", "commitment", "TEXT"),
    ("root_causes", "role", "TEXT"),
    ("root_causes", "responsibility", "TEXT"),
    ("review_queue", "candidates", "TEXT"),
]


class DB:
    def __init__(self, path: str):
        self.path = path
        if path != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self._migrate()
        self.conn.commit()

    def _migrate(self):
        """Versioned additive migration. V1 -> 2 adds the alpha tables."""
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)")
        row = self.conn.execute("SELECT version FROM schema_version").fetchone()
        current = row["version"] if row else 0
        if current < 1:
            self.conn.execute("INSERT INTO schema_version (version) VALUES (1)")
        if current < 2:
            self.conn.executescript(ALPHA_SCHEMA)
            self.conn.execute("UPDATE schema_version SET version=2")
        if current < 3:
            self.conn.executescript(V12_SCHEMA)
            for table, col, typ in _ADD_COLUMNS:
                cols = [r[1] for r in self.conn.execute(f"PRAGMA table_info({table})")]
                if col not in cols:
                    self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typ}")
            self.conn.execute("UPDATE schema_version SET version=3")
        if current < 4:
            # review_queue.candidates (preference UI) added after v3 shipped
            cols = [r[1] for r in self.conn.execute("PRAGMA table_info(review_queue)")]
            if "candidates" not in cols:
                self.conn.execute("ALTER TABLE review_queue ADD COLUMN candidates TEXT")
            self.conn.execute("UPDATE schema_version SET version=4")

    def schema_version(self) -> int:
        return self.conn.execute("SELECT version FROM schema_version").fetchone()["version"]

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
        rows = []
        for r in self.conn.execute(
                "SELECT * FROM decision_points WHERE match_id=? ORDER BY decision_tick",
                (match_id,)):
            d = dict(r)
            d["alternatives"] = json.loads(d["alternatives"])
            d["evidence"] = json.loads(d["evidence"])
            d["meta"] = json.loads(d["meta"])
            rows.append(d)
        return rows

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

    # ---- alpha repositories (V1.1-alpha) ----

    def replace_execution_metrics(self, match_id, metrics: list[dict]):
        self.conn.execute("DELETE FROM execution_metrics WHERE match_id=?", (match_id,))
        if metrics:
            self.conn.executemany(
                """INSERT OR REPLACE INTO execution_metrics
                   (id, match_id, round, tick, steamid, metric, value, threshold,
                    violation, evidence, meta) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                [(m["id"], match_id, m["round"], m["tick"], m["steamid"], m["metric"],
                  m.get("value"), m.get("threshold"), int(m.get("violation", 0)),
                  jd(m.get("evidence", [])), jd(m.get("meta", {}))) for m in metrics])
        self.conn.commit()

    def get_execution_metrics(self, match_id=None):
        q = "SELECT * FROM execution_metrics"
        args = ()
        if match_id:
            q += " WHERE match_id=?"
            args = (match_id,)
        rows = []
        for r in self.conn.execute(q + " ORDER BY tick", args):
            d = dict(r)
            d["evidence"] = json.loads(d["evidence"])
            d["meta"] = json.loads(d["meta"])
            rows.append(d)
        return rows

    def upsert_pattern(self, p: dict):
        self.conn.execute(
            """INSERT OR REPLACE INTO patterns
               (pattern_id, pattern_type, name, category, sample_count, opportunity_count,
                violation_count, violation_rate, positive_examples, negative_examples,
                confidence, counterfactual_support, affected_contexts, evidence_refs, computed_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (p["pattern_id"], p["pattern_type"], p["name"], p["category"],
             p["sample_count"], p["opportunity_count"], p["violation_count"],
             p["violation_rate"], p["positive_examples"], p["negative_examples"],
             p["confidence"], p["counterfactual_support"],
             jd(p.get("affected_contexts", [])), jd(p.get("evidence_refs", [])),
             p.get("computed_at", "")))
        self.conn.commit()

    def replace_pattern_evidence(self, pattern_id, match_id, items: list[dict]):
        self.conn.execute("DELETE FROM pattern_evidence WHERE pattern_id=? AND match_id=?",
                          (pattern_id, match_id))
        self.conn.executemany(
            """INSERT INTO pattern_evidence (pattern_id, kind, match_id, round, tick, dp_id, detail)
               VALUES (?,?,?,?,?,?,?)""",
            [(pattern_id, it.get("kind"), match_id, it.get("round"),
              it.get("tick"), it.get("dp_id"), jd(it.get("detail", {}))) for it in items])
        self.conn.commit()

    def get_patterns(self):
        out = []
        for r in self.conn.execute("SELECT * FROM patterns ORDER BY pattern_type"):
            d = dict(r)
            d["affected_contexts"] = json.loads(d["affected_contexts"])
            d["evidence_refs"] = json.loads(d["evidence_refs"])
            out.append(d)
        return out

    def get_pattern(self, pattern_type):
        r = self.conn.execute("SELECT * FROM patterns WHERE pattern_type=?", (pattern_type,)).fetchone()
        if not r:
            return None
        d = dict(r)
        d["affected_contexts"] = json.loads(d["affected_contexts"])
        d["evidence_refs"] = json.loads(d["evidence_refs"])
        return d

    def get_pattern_evidence(self, pattern_id):
        rows = []
        for r in self.conn.execute(
                "SELECT * FROM pattern_evidence WHERE pattern_id=? ORDER BY tick", (pattern_id,)):
            d = dict(r)
            d["detail"] = json.loads(d["detail"])
            rows.append(d)
        return rows

    def upsert_root_cause(self, rc: dict):
        self.conn.execute(
            """INSERT OR REPLACE INTO root_causes
               (event_id, match_id, round, tick, steamid, result, execution, micro, macro,
                primary_cause, secondary_cause, mechanical_cause, confidence,
                context, commitment, role, responsibility)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (rc["event_id"], rc["match_id"], rc["round"], rc["tick"], rc["steamid"],
             rc["result"], rc["execution"], rc["micro"], rc["macro"],
             rc["primary_cause"], rc["secondary_cause"], rc["mechanical_cause"],
             rc["confidence"], rc.get("context"), rc.get("commitment"),
             rc.get("role"), rc.get("responsibility")))
        self.conn.commit()

    def get_root_causes(self, match_id=None):
        q = "SELECT * FROM root_causes"
        args = ()
        if match_id:
            q += " WHERE match_id=?"
            args = (match_id,)
        return [dict(r) for r in self.conn.execute(q + " ORDER BY tick", args)]

    def upsert_target(self, t: dict):
        self.conn.execute(
            """INSERT OR REPLACE INTO training_targets
               (target_id, pattern_type, name, category, trigger, undesired_behavior,
                replacement_behavior, baseline, goal, measurement_definition,
                measurement_window, status, progress, confidence, created_at,
                next_match_cue, source_pattern_ids, supporting_evidence)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (t["target_id"], t["pattern_type"], t["name"], t["category"],
             t["trigger"], t["undesired_behavior"], t["replacement_behavior"],
             t["baseline"], t["goal"], t["measurement_definition"],
             t["measurement_window"], t["status"], t["progress"], t["confidence"],
             t["created_at"], jd(t.get("next_match_cue", {})),
             jd(t.get("source_pattern_ids", [])), jd(t.get("supporting_evidence", []))))
        self.conn.commit()

    def get_targets(self, status=None):
        q = "SELECT * FROM training_targets"
        args = ()
        if status:
            q += " WHERE status=?"
            args = (status,)
        out = []
        for r in self.conn.execute(q + " ORDER BY created_at DESC", args):
            d = dict(r)
            d["next_match_cue"] = json.loads(d["next_match_cue"])
            d["source_pattern_ids"] = json.loads(d["source_pattern_ids"])
            d["supporting_evidence"] = json.loads(d["supporting_evidence"])
            out.append(d)
        return out

    def get_target(self, target_id):
        r = self.conn.execute("SELECT * FROM training_targets WHERE target_id=?", (target_id,)).fetchone()
        if not r:
            return None
        d = dict(r)
        d["next_match_cue"] = json.loads(d["next_match_cue"])
        d["source_pattern_ids"] = json.loads(d["source_pattern_ids"])
        d["supporting_evidence"] = json.loads(d["supporting_evidence"])
        return d

    def insert_measurement(self, m: dict):
        self.conn.execute(
            """INSERT OR REPLACE INTO target_measurements
               (id, target_id, window_start, window_end, opportunities, violations,
                rate, rate_ci, delta_vs_baseline, behavior_verdict, execution_verdict,
                outcome_verdict) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (m["id"], m["target_id"], m["window_start"], m["window_end"],
             m["opportunities"], m["violations"], m["rate"], jd(m["rate_ci"]),
             m["delta_vs_baseline"], m["behavior_verdict"], m["execution_verdict"],
             m["outcome_verdict"]))
        self.conn.commit()

    def get_measurements(self, target_id):
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM target_measurements WHERE target_id=? ORDER BY window_start", (target_id,))]

    def insert_target_history(self, h: dict):
        self.conn.execute(
            """INSERT OR REPLACE INTO target_status_history
               (id, target_id, from_status, status, at, reason) VALUES (?,?,?,?,?,?)""",
            (h["id"], h["target_id"], h["from_status"], h["status"], h["at"], h["reason"]))
        self.conn.commit()

    def get_target_history(self, target_id):
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM target_status_history WHERE target_id=? ORDER BY at", (target_id,))]

    def insert_annotation(self, a: dict):
        self.conn.execute(
            """INSERT OR REPLACE INTO human_annotations
               (id, match_id, round, tick, event_id, dp_id, annotation_type,
                model_version, rule_version, config_version, model_prediction,
                model_confidence, human_label, human_confidence, correction_type,
                reason_code, optional_comment, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (a["id"], a["match_id"], a["round"], a["tick"], a["event_id"], a["dp_id"],
             a["annotation_type"], a["model_version"], a["rule_version"], a["config_version"],
             a["model_prediction"], a["model_confidence"], a["human_label"],
             a["human_confidence"], a["correction_type"], a["reason_code"],
             a["optional_comment"], a["created_at"]))
        self.conn.commit()

    def get_annotations(self, match_id=None, annotation_type=None):
        q = "SELECT * FROM human_annotations"
        cond, args = [], []
        if match_id:
            cond.append("match_id=?")
            args.append(match_id)
        if annotation_type:
            cond.append("annotation_type=?")
            args.append(annotation_type)
        if cond:
            q += " WHERE " + " AND ".join(cond)
        return [dict(r) for r in self.conn.execute(q + " ORDER BY created_at", args)]

    def insert_preference(self, p: dict):
        self.conn.execute(
            """INSERT OR REPLACE INTO preference_annotations
               (id, match_id, round, tick, event_id, candidates, human_choice,
                human_confidence, reason_code, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (p["id"], p["match_id"], p["round"], p["tick"], p["event_id"],
             jd(p["candidates"]), p["human_choice"], p["human_confidence"],
             p["reason_code"], p["created_at"]))
        self.conn.commit()

    def get_preferences(self):
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM preference_annotations ORDER BY created_at")]

    def insert_review_item(self, r_: dict):
        self.conn.execute(
            """INSERT OR REPLACE INTO review_queue
               (id, match_id, round, tick, event_id, dp_id, item_type, priority,
                model_prediction, model_confidence, rationale, status, created_at, candidates)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (r_["id"], r_["match_id"], r_["round"], r_["tick"], r_["event_id"], r_["dp_id"],
             r_["item_type"], r_["priority"], r_["model_prediction"], r_["model_confidence"],
             r_["rationale"], r_.get("status", "pending"), r_.get("created_at", ""),
             jd(r_.get("candidates", []))))
        self.conn.commit()

    def get_review_queue(self, status="pending", limit=20):
        rows = []
        for r in self.conn.execute(
                "SELECT * FROM review_queue WHERE status=? ORDER BY priority DESC, tick LIMIT ?",
                (status, limit)):
            d = dict(r)
            d["candidates"] = json.loads(d["candidates"]) if d.get("candidates") else []
            rows.append(d)
        return rows

    def mark_review_done(self, review_id):
        self.conn.execute("UPDATE review_queue SET status='reviewed' WHERE id=?", (review_id,))
        self.conn.commit()

    # ---- V1.2 context & intent repos ----
    def upsert_context_event(self, e: dict):
        self.conn.execute(
            """INSERT OR REPLACE INTO context_events
               (id, match_id, round, tick, steamid, anchor, commitment, role, role_dist,
                intent, intent_conf, intent_dist, feasibility, responsibility,
                temporal_summary, event_ref, computed_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (e["id"], e["match_id"], e["round"], e["tick"], e["steamid"], e["anchor"],
             e["commitment"], e["role"], jd(e.get("role_dist", {})),
             e["intent"], e["intent_conf"], jd(e.get("intent_dist", {})),
             jd(e.get("feasibility", {})), e["responsibility"],
             jd(e.get("temporal_summary", {})), e.get("event_ref", ""),
             e.get("computed_at", "")))
        self.conn.commit()

    def get_context_events(self, match_id=None, limit=200):
        q = "SELECT * FROM context_events"
        args = ()
        if match_id:
            q += " WHERE match_id=?"
            args = (match_id,)
        rows = []
        for r in self.conn.execute(q + f" ORDER BY tick LIMIT {limit}", args):
            d = dict(r)
            for k in ("role_dist", "intent_dist", "feasibility", "temporal_summary"):
                d[k] = json.loads(d[k])
            rows.append(d)
        return rows

    def upsert_intent_sample(self, s: dict):
        self.conn.execute(
            """INSERT OR REPLACE INTO intent_samples
               (id, match_id, round, anchor_tick, start_tick, end_tick, feature_sequence,
                hard_events, player_known_state, commitment_state, situational_role,
                rule_prediction, rule_confidence, human_label, human_confidence, source,
                model_version, extractor_version)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (s["id"], s["match_id"], s["round"], s["anchor_tick"], s["start_tick"],
             s["end_tick"], jd(s["feature_sequence"]), jd(s.get("hard_events", {})),
             jd(s.get("player_known_state", {})), s["commitment_state"], s["situational_role"],
             s["rule_prediction"], s["rule_confidence"], s.get("human_label"),
             s.get("human_confidence"), s.get("source", "rule-baseline"),
             s.get("model_version", "alpha-1"), s.get("extractor_version", "v1.2-1")))
        self.conn.commit()

    def get_intent_samples(self, match_id=None, limit=1000):
        q = "SELECT * FROM intent_samples"
        args = ()
        if match_id:
            q += " WHERE match_id=?"
            args = (match_id,)
        rows = []
        for r in self.conn.execute(q + f" ORDER BY anchor_tick LIMIT {limit}", args):
            d = dict(r)
            d["feature_sequence"] = json.loads(d["feature_sequence"])
            d["hard_events"] = json.loads(d["hard_events"])
            d["player_known_state"] = json.loads(d["player_known_state"])
            rows.append(d)
        return rows
