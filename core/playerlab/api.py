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
                elif path == "/api/focus-player":
                    # current focus + remember (POST handled in do_POST)
                    from .focus import default_focus
                    mid = q.get("match", [None])[0]
                    if mid:
                        _json(self, {"focus": default_focus(db, mid).to_dict()})
                    else:
                        _json(self, {"focus": None,
                                     "user": db.get_user_profile()})
                elif path.startswith("/api/players/") and path.endswith("/matches"):
                    sid = int(path[len("/api/players/"):-len("/matches")])
                    eps = db.get_decision_episodes(player_id=sid, limit=2000)
                    matches = {}
                    for e in eps:
                        matches.setdefault(e["match_id"], {"episodes": 0})
                        matches[e["match_id"]]["episodes"] += 1
                    _json(self, {"steam_id": sid, "matches": matches,
                                 "match_count": len(matches),
                                 "profile": db.get_player_profile(sid)})
                elif path.startswith("/api/matches/"):
                    rest = path[len("/api/matches/"):]
                    if "/players/" in rest:
                        demo_id, sub = rest.split("/players/", 1)
                        match = db.get_match(demo_id)
                        if not match:
                            return _json(self, {"error": "match not found"}, 404)
                        parts = sub.split("/")
                        steam_id = int(parts[0])
                        endpoint = parts[1] if len(parts) > 1 else "overview"
                        player = next((p for p in db.get_players(demo_id)
                                       if int(p["steamid"]) == steam_id), None)
                        if not player:
                            return _json(self, {"error": "player not in match"}, 404)
                        from .focus import players_of_match, remember_user
                        from .moments import (rank_review_moments,
                                              player_match_overview)
                        from .calibration import detector_calibration_map
                        cal = detector_calibration_map(db, cfg)
                        if endpoint == "overview":
                            _json(self, {"overview": player_match_overview(
                                db, cfg, demo_id, steam_id)})
                        elif endpoint == "decisions":
                            eps = db.get_decision_episodes(
                                match_id=demo_id, player_id=steam_id, limit=500)
                            for e in eps:
                                e["player_id"] = str(e["player_id"])
                                e["candidates"] = db.get_decision_candidates(e["id"])
                                e.pop("duel_state_sequence", None)
                            _json(self, {"decisions": eps})
                        elif endpoint == "engagements":
                            eps = db.get_decision_episodes(
                                match_id=demo_id, player_id=steam_id, limit=500)
                            _json(self, {"engagements": [
                                {"episode_id": e["id"], "round": e["round"],
                                 "tick": e["anchor_tick"],
                                 "player_id": str(e["player_id"]),
                                 "method": (e.get("engagement_method") or {}).get("method"),
                                 "evaluation": e.get("engagement_evaluation"),
                                 "weapon_matchup": e.get("weapon_matchup")}
                                for e in eps if e.get("engagement_method")]})
                        elif endpoint == "patterns":
                            from .episode_patterns import cluster_episodes
                            from .calibration import calibration_stats
                            pats = cluster_episodes(db, cfg, match_id=demo_id)
                            _json(self, {"patterns": pats})
                        elif endpoint == "review-moments":
                            moments = rank_review_moments(db, cfg, demo_id, steam_id,
                                                          calibration=cal)
                            for m in moments:
                                m["player_id"] = str(m["player_id"])
                            _json(self, {"moments": moments})
                        elif endpoint == "calibration":
                            from .calibration import sample_calibration_set
                            samples = sample_calibration_set(db, cfg, demo_id,
                                                             player_id=steam_id)
                            for s in samples:
                                s["player_id"] = str(s["player_id"])
                            _json(self, {"samples": samples})
                        else:
                            _json(self, {"error": "unknown player endpoint"}, 404)
                    else:
                        demo_id = rest
                        match = db.get_match(demo_id)
                        if not match:
                            return _json(self, {"error": "match not found"}, 404)
                        from .focus import players_of_match
                        _json(self, {"match": match,
                                     "rounds": db.get_rounds(demo_id),
                                     "players": players_of_match(db, demo_id),
                                     "decision_points": db.get_dps(demo_id)})
                elif path == "/api/calibration-stats":
                    from .calibration import calibration_stats
                    det = q.get("detector", [None])[0]
                    _json(self, calibration_stats(db, cfg, detector_type=det))
                elif path == "/api/calibration-samples":
                    from .calibration import sample_calibration_set
                    det = q.get("detector", [None])[0]
                    mid = q.get("match", [None])[0]
                    sid = q.get("player", [None])[0]
                    samples = db.get_calibration_samples(
                        detector_type=det, match_id=mid,
                        player_id=int(sid) if sid else None, limit=500)
                    if not samples and mid and sid:
                        samples = sample_calibration_set(db, cfg, mid,
                                                         player_id=int(sid))
                    _json(self, {"samples": samples})
                elif path == "/api/threshold-sensitivity":
                    from .calibration import threshold_sensitivity
                    det = q.get("detector", [""])[0]
                    vals = [float(v) for v in q.get("values", [])] or [0.5, 0.6, 0.7, 0.8]
                    _json(self, {"detector": det,
                                 "experiments": threshold_sensitivity(db, cfg, det, vals)})
                elif path == "/api/review-moments":
                    mid = q.get("match", [None])[0]
                    sid = q.get("player", [None])[0]
                    from .moments import rank_review_moments
                    from .calibration import detector_calibration_map
                    cal = detector_calibration_map(db, cfg)
                    if mid and sid:
                        moments = rank_review_moments(db, cfg, mid, int(sid),
                                                      calibration=cal)
                        _json(self, {"moments": moments})
                    else:
                        _json(self, {"moments": db.get_review_moments(limit=50)})
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
                        # strip heavy duel sequence for the list view (keep
                        # summary); the detail endpoint returns it fully
                        seq = e.pop("duel_state_sequence", None)
                        e["duel_summary"] = {"n_states": len(seq)} if seq else None
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
                elif path == "/api/focus-player" or path == "/api/remember-player":
                    from .focus import set_focus, remember_user
                    match_id = body.get("match_id")
                    steam_id = int(body.get("steam_id"))
                    persist = path == "/api/remember-player" or bool(body.get("remember"))
                    if not match_id:
                        # remember by steam_id only (cross-match default)
                        name = body.get("display_name", "")
                        remember_user(db, steam_id, name)
                        _json(self, {"saved": True, "is_user": True, "steam_id": steam_id})
                    else:
                        ctx = set_focus(db, match_id, steam_id, persist=persist)
                        _json(self, {"focus": ctx.to_dict()})
                elif path.startswith("/api/calibration/") and path.endswith("/review"):
                    sample_id = path[len("/api/calibration/"):-len("/review")]
                    from .calibration import PREAIM_FP_REASONS, MOVING_SHOT_FP_REASONS
                    human_label = body.get("human_label", "UNSURE")  # YES/NO/UNSURE
                    conf = float(body.get("human_confidence", 0.7))
                    fp = body.get("false_positive_reason", "")
                    db.mark_calibration_reviewed(sample_id, human_label, conf, fp,
                                                 body.get("notes", ""))
                    _json(self, {"saved": True, "sample_id": sample_id,
                                 "human_label": human_label})
                elif path == "/api/calibration-review-fp-reasons":
                    det = body.get("detector", "")
                    if det == "PREAIM_ERROR":
                        _json(self, {"reasons": list(PREAIM_FP_REASONS)})
                    elif det == "MOVING_SHOT":
                        _json(self, {"reasons": list(MOVING_SHOT_FP_REASONS)})
                    else:
                        _json(self, {"reasons": ["OTHER", "INSUFFICIENT_CONTEXT"]})
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
