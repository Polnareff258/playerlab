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
