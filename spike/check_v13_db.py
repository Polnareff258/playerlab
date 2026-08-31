import sys
sys.path.insert(0, "core")
from playerlab.db import DB

db = DB(":memory:")
print("schema version:", db.schema_version())
tables = [r[0] for r in db.conn.execute(
    "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'decision_%'").fetchall()]
print("v5 tables:", tables)

# round-trip test
e = {"id": "e1", "match_id": "m1", "round": 3, "player_id": 1, "family": "CONTACT_RESPONSE",
     "start_tick": 100, "anchor_tick": 200, "end_tick": 300, "temporal_context": {"t": 1},
     "player_known_state": {"n": 2}, "macro_context": {"adv": "5v4"}, "local_context": {"p": 1},
     "commitment_state": "FREE", "situational_role": "FREE_ROLE", "intent": "HOLD",
     "observed_action": "RE_PEEK", "feasibility": {"HOLD": "FEASIBLE"},
     "immediate_result": {"survived": True}, "state_value_before": 0.7, "state_value_after": 0.5,
     "decision_evaluation": "QUESTIONABLE", "actionability": "ACTIONABLE",
     "confidence": 0.7, "extractor_version": "v1.3-1", "context_version": "v1.2.1",
     "rule_version": "v1.3-1", "model_provider_version": "null", "geometry_version": "null",
     "computed_at": "2026-01-01"}
db.upsert_decision_episode(e)
got = db.get_decision_episode("e1")
assert got["family"] == "CONTACT_RESPONSE" and got["macro_context"]["adv"] == "5v4"
db.upsert_decision_candidate({"id": "c1", "episode_id": "e1", "action": "HOLD",
                              "feasibility": "FEASIBLE", "feasibility_reason": "ok",
                              "rank": 1, "confidence": 0.6})
assert len(db.get_decision_candidates("e1")) == 1
db.upsert_decision_evidence({"id": "ev1", "episode_id": "e1", "candidate_action": "HOLD",
                             "source": "rule", "type": "risk", "supports_action": "HOLD",
                             "confidence": 0.5, "related_sources": ["hist"]})
assert db.get_decision_evidence("e1")[0]["related_sources"] == ["hist"]
db.insert_decision_preference({"id": "p1", "episode_id": "e1", "match_id": "m1",
                               "round": 3, "tick": 200, "candidate_a": "HOLD",
                               "candidate_b": "RE_PEEK", "human_choice": "A"})
assert len(db.get_decision_preferences("e1")) == 1
print("v5 round-trip OK")
