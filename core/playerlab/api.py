"""Local read-only JSON API + static UI server (stdlib, no install needed).

Routes:
  GET  /                          -> ui/index.html
  GET  /api/health
  GET  /api/matches
  GET  /api/matches/{demo_id}     -> match + rounds + players + decision points
  GET  /api/dps/{dp_id}           -> dp + state + outcome
  GET  /api/dps/{dp_id}/what-if   -> counterfactual result (?k=)
  GET  /api/dps/{dp_id}/similar-rounds?action=X&k=10
  GET  /api/coverage
"""
from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .config import Config
from .db import DB
from .counterfactual import retrieve, what_if


def _intent_dist(db: DB) -> dict:
    from collections import Counter
    return dict(Counter(s.get("rule_prediction") for s in db.get_intent_samples()))


def _model_intelligence(cfg: Config) -> dict:
    """Minimal Model Intelligence status (spec §42)."""
    from .model_provider import get_provider
    provider_cfg = getattr(cfg, "model_provider", "null")
    try:
        prov = get_provider(provider_cfg)
        meta = prov.get_metadata()
        status = ("CONNECTED" if meta.get("status") == "ready"
                  else "ERROR" if meta.get("status") == "error"
                  else "NOT INSTALLED")
        return {"provider": meta.get("provider", "null"),
                "status": status,
                "model_version": meta.get("model_version"),
                "loaded_tasks": prov.get_supported_tasks(),
                "note": meta.get("note", "")}
    except Exception as e:  # noqa: BLE001
        return {"provider": "null", "status": "ERROR", "loaded_tasks": [],
                "note": f"{type(e).__name__}: {e}"}


def _json(handler, obj, code=200):
    body = json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8")
    handler.send_response(code)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def make_handler(db_path: str, cfg: Config, ui_dir: str):
    class Handler(BaseHTTPRequestHandler):
        server_version = "PlayerLab/0.1"

        def log_message(self, fmt, *args):  # keep console quiet
            pass

        def do_GET(self):
            from urllib.parse import parse_qs, urlparse
            db = DB(db_path)  # per-request connection (thread-safe)
            try:
                parsed = urlparse(self.path)
                path = parsed.path
                q = parse_qs(parsed.query)
                if path == "/" or path == "/index.html":
                    self._serve_index()
                elif path == "/api/health":
                    _json(self, {"ok": True, "db": db_path})
                elif path == "/api/matches":
                    _json(self, {"matches": db.list_matches()})
                elif path.startswith("/api/matches/"):
                    demo_id = path[len("/api/matches/"):]
                    match = db.get_match(demo_id)
                    if not match:
                        return _json(self, {"error": "match not found"}, 404)
                    _json(self, {"match": match,
                                 "rounds": db.get_rounds(demo_id),
                                 "players": db.get_players(demo_id),
                                 "decision_points": db.get_dps(demo_id)})
                elif path.startswith("/api/dps/"):
                    rest = path[len("/api/dps/"):]
                    if rest.endswith("/what-if"):
                        dp_id = rest[:-len("/what-if")]
                        k = int(q.get("k", [""])[0] or 0) or None
                        same = q.get("same", ["0"])[0] in ("1", "true", "yes")
                        _json(self, what_if(db, cfg, dp_id, k=k, include_same=same))
                    elif rest.endswith("/similar-rounds"):
                        dp_id = rest[:-len("/similar-rounds")]
                        action = q.get("action", [None])[0]
                        k = int(q.get("k", ["10"])[0])
                        state = db.get_state(dp_id)
                        if not state:
                            return _json(self, {"error": "state not found"}, 404)
                        cands = retrieve(db, cfg, state, mode="counterfactual", k=k,
                                         exclude_match=False)
                        if action and action != "any":
                            cands = [c for c in cands if c["action"] == action]
                        _json(self, {"dp_id": dp_id, "similar": cands})
                    else:
                        dp_id = rest
                        dp = db.get_dp(dp_id)
                        if not dp:
                            return _json(self, {"error": "dp not found"}, 404)
                        _json(self, {"decision_point": dp,
                                     "state": db.get_state(dp_id),
                                     "outcome": db.get_outcome(dp_id)})
                elif path == "/api/coverage":
                    _json(self, {"coverage": db.get_coverage()})
                elif path == "/api/focus":
                    from .training import active_focus
                    _json(self, {"focus": active_focus(db)})
                elif path == "/api/patterns":
                    _json(self, {"patterns": db.get_patterns()})
                elif path == "/api/bottlenecks":
                    from .bottleneck import rank_bottlenecks
                    _json(self, {"bottlenecks": rank_bottlenecks(db, cfg, len(db.list_matches()))})
                elif path == "/api/targets":
                    _json(self, {"targets": db.get_targets()})
                elif path.startswith("/api/targets/"):
                    tid = path[len("/api/targets/"):]
                    t = db.get_target(tid)
                    if not t:
                        return _json(self, {"error": "target not found"}, 404)
                    _json(self, {"target": t,
                                 "measurements": db.get_measurements(tid),
                                 "history": db.get_target_history(tid)})
                elif path == "/api/review":
                    _json(self, {"review": db.get_review_queue(limit=30)})
                elif path == "/api/annotations/stats":
                    from .annotation import annotation_stats
                    _json(self, annotation_stats(db))
                elif path == "/api/context":
                    _json(self, {"context": db.get_context_events(limit=200)})
                elif path == "/api/intent-samples":
                    _json(self, {"samples": len(db.get_intent_samples()),
                                 "intent_distribution": _intent_dist(db)})
                elif path == "/api/model-intelligence":
                    _json(self, {"model_intelligence": _model_intelligence(cfg)})
                elif path == "/api/decisions":
                    q_match = q.get("match", [None])[0]
                    q_family = q.get("family", [None])[0]
                    eps = db.get_decision_episodes(match_id=q_match,
                                                   family=q_family, limit=200)
                    for e in eps:
                        e["candidates"] = db.get_decision_candidates(e["id"])
                    _json(self, {"decisions": eps})
                elif path.startswith("/api/decisions/"):
                    ep_id = path[len("/api/decisions/"):]
                    if ep_id.endswith("/alternatives"):
                        ep_id = ep_id[:-len("/alternatives")]
                        ep = db.get_decision_episode(ep_id)
                        if not ep:
                            return _json(self, {"error": "episode not found"}, 404)
                        _json(self, {"episode_id": ep_id,
                                     "observed_action": ep["observed_action"],
                                     "candidates": ep.get("candidates", [])})
                    elif ep_id.endswith("/preference"):
                        ep_id = ep_id[:-len("/preference")]
                        if self.command == "POST":
                            return _json(self, {"error": "use POST"}, 405)
                        ep = db.get_decision_episode(ep_id)
                        if not ep:
                            return _json(self, {"error": "episode not found"}, 404)
                        _json(self, {"preferences": db.get_decision_preferences(ep_id)})
                    else:
                        ep = db.get_decision_episode(ep_id)
                        if not ep:
                            return _json(self, {"error": "episode not found"}, 404)
                        _json(self, {"decision": ep})
                elif path == "/api/decision-stats":
                    from collections import Counter
                    eps = db.get_decision_episodes(limit=2000)
                    _json(self, {"stats": {
                        "total": len(eps),
                        "family": dict(Counter(e["family"] for e in eps)),
                        "evaluation": dict(Counter(e["decision_evaluation"] for e in eps)),
                        "actionability": dict(Counter(e["actionability"] for e in eps)),
                    }})
                else:
                    _json(self, {"error": "not found"}, 404)
            except Exception as e:  # noqa: BLE001
                _json(self, {"error": f"{type(e).__name__}: {e}"}, 500)
            finally:
                db.close()

        def do_POST(self):
            import json as _json_mod
            db = DB(db_path)
            try:
                length = int(self.headers.get("Content-Length", 0))
                raw = self.rfile.read(length).decode("utf-8") if length else "{}"
                body = _json_mod.loads(raw or "{}")
                path = self.path
                if path.startswith("/api/review/") and path.endswith("/annotation"):
                    rid = path[len("/api/review/"):-len("/annotation")]
                    from .annotation import submit_annotation
                    ann = submit_annotation(
                        db, rid, body.get("annotation_type", "decision_quality"),
                        body.get("model_prediction"), body.get("model_confidence"),
                        body.get("human_label", ""),
                        float(body.get("human_confidence", 0.7)),
                        body.get("reason_code", "OTHER"),
                        body.get("optional_comment", ""))
                    _json(self, {"annotation": ann})
                elif path.startswith("/api/review/") and path.endswith("/preference"):
                    rid = path[len("/api/review/"):-len("/preference")]
                    item = next((r for r in db.get_review_queue(status="pending", limit=1000)
                                 if r["id"] == rid), None)
                    from .annotation import submit_preference
                    rec = submit_preference(
                        db, item["match_id"] if item else body.get("match_id", ""),
                        item["round"] if item else int(body.get("round", 0)),
                        item["tick"] if item else int(body.get("tick", 0)),
                        item.get("event_id", "") if item else body.get("event_id", ""),
                        body.get("candidates", []), body.get("human_choice", ""),
                        float(body.get("human_confidence", 0.6)),
                        body.get("reason_code", "OTHER"))
                    if item:
                        db.mark_review_done(rid)
                    _json(self, {"preference": rec})
                elif path.startswith("/api/decisions/") and path.endswith("/preference"):
                    ep_id = path[len("/api/decisions/"):-len("/preference")]
                    ep = db.get_decision_episode(ep_id)
                    if not ep:
                        return _json(self, {"error": "episode not found"}, 404)
                    cands = [c for c in (ep.get("candidates") or [])
                             if c["feasibility"] not in ("UNAVAILABLE", "TEMPORARILY_UNAVAILABLE")]
                    a = body.get("candidate_a") or (cands[0]["action"] if cands else "")
                    b = body.get("candidate_b") or (
                        next((c["action"] for c in cands if c["action"] != a), a)
                        if cands else a)
                    import uuid as _uuid
                    db.insert_decision_preference({
                        "id": _uuid.uuid4().hex[:16], "episode_id": ep_id,
                        "match_id": ep["match_id"], "round": ep["round"],
                        "tick": ep["anchor_tick"], "candidate_a": a, "candidate_b": b,
                        "human_choice": body.get("human_choice", "UNSURE"),
                        "human_confidence": float(body.get("human_confidence", 0.6)),
                        "reason_code": body.get("reason_code", "OTHER")})
                    _json(self, {"saved": True, "episode_id": ep_id, "a": a, "b": b})
                else:
                    _json(self, {"error": "not found"}, 404)
            except Exception as e:  # noqa: BLE001
                _json(self, {"error": f"{type(e).__name__}: {e}"}, 500)
            finally:
                db.close()

        def _serve_index(self):
            index = os.path.join(ui_dir, "index.html")
            if not os.path.isfile(index):
                return _json(self, {"error": "ui/index.html missing"}, 404)
            with open(index, "rb") as fh:
                body = fh.read()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return Handler


def serve(db_path: str, ui_dir: str, port: int = 8123, host: str = "127.0.0.1"):
    cfg = Config().resolve()
    cfg.db_path = db_path
    handler = make_handler(db_path, cfg, ui_dir)
    srv = ThreadingHTTPServer((host, port), handler)
    print(f"PlayerLab UI+API: http://{host}:{port}  (Ctrl+C to stop)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
