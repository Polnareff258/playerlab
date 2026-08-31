"""PlayerLab CLI. Usage:
  python3 -m playerlab.cli ingest <demo.dem> [--steamid N]
  python3 -m playerlab.cli list
  python3 -m playerlab.cli dps <demo_id>
  python3 -m playerlab.cli dp <dp_id>
  python3 -m playerlab.cli whatif <dp_id>
  python3 -m playerlab.cli coverage
  python3 -m playerlab.cli backtest
  python3 -m playerlab.cli qa [--out path] [--n 60]
  python3 -m playerlab.cli ablation
  python3 -m playerlab.cli api [--port 8123]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

from .config import Config


def main(argv=None):
    cfg = Config().resolve()
    parser = argparse.ArgumentParser(prog="playerlab", description="PlayerLab V1 CLI")
    parser.add_argument("--db", default=cfg.db_path, help="SQLite path")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_ingest = sub.add_parser("ingest", help="parse + detect + persist a demo")
    p_ingest.add_argument("demo")
    p_ingest.add_argument("--steamid", type=int, default=None)

    sub.add_parser("list", help="list matches")
    p_dps = sub.add_parser("dps", help="list decision points of a match")
    p_dps.add_argument("match_id")
    p_dp = sub.add_parser("dp", help="show one decision point")
    p_dp.add_argument("dp_id")
    p_wi = sub.add_parser("whatif", help="counterfactual for a DP")
    p_wi.add_argument("dp_id")
    p_wi.add_argument("--same", action="store_true",
                      help="include same-match states (single-demo demo mode)")
    sub.add_parser("coverage", help="similar-state coverage report")
    sub.add_parser("backtest", help="leave-one-match-out holdout")
    p_qa = sub.add_parser("qa", help="export retrieval-QA batch")
    p_qa.add_argument("--out", default="")
    p_qa.add_argument("--n", type=int, default=60)
    sub.add_parser("ablation", help="feature-subset ablation")
    p_api = sub.add_parser("api", help="start local UI+API")
    p_api.add_argument("--port", type=int, default=8123)
    p_api.add_argument("--host", default="127.0.0.1")

    args = parser.parse_args(argv)
    cfg.db_path = args.db
    t0 = time.time()

    if args.cmd == "ingest":
        _cmd_ingest(cfg, args.demo, args.steamid)
    elif args.cmd == "list":
        from .db import DB
        db = DB(cfg.db_path)
        for m in db.list_matches():
            print(f"{m['demo_id']}  {m['map_name']}  {m['rounds_total']}r  "
                  f"{m['player_count']}p  {m['parsed_at']}")
    elif args.cmd == "dps":
        from .db import DB
        db = DB(cfg.db_path)
        dps = db.get_dps(args.match_id)
        if not dps:
            print("no decision points (ingest first?)")
        for d in dps:
            o = db.get_outcome(d["dp_id"]) or {}
            res = {0: "DEATH", 1: "SURVIVED"}.get(o.get("survival"), "?")
            print(f"{d['dp_id'][-16:]}  r{d['round']:>2} t{d['decision_tick']:>6}  "
                  f"{d['observed_action']:<10} {d['player_name'][:12]:<12} {d['zone']:<8} "
                  f"conf={d['confidence']:.2f} sig={d['significance']:.2f} {res}")
    elif args.cmd == "dp":
        from .db import DB
        db = DB(cfg.db_path)
        dp = db.get_dp(args.dp_id)
        if not dp:
            print("dp not found"); sys.exit(1)
        print(json.dumps({"decision_point": dp, "state": db.get_state(args.dp_id),
                          "outcome": db.get_outcome(args.dp_id)},
                         ensure_ascii=False, indent=1, default=str))
    elif args.cmd == "whatif":
        from .db import DB
        from .counterfactual import what_if
        db = DB(cfg.db_path)
        print(json.dumps(what_if(db, cfg, args.dp_id, include_same=args.same),
                         ensure_ascii=False, indent=1, default=str))
    elif args.cmd == "coverage":
        from .db import DB
        db = DB(cfg.db_path)
        rows = db.get_coverage()
        if not rows:
            print("no coverage (ingest first?)")
        for r in rows:
            print(f"{r['map']:<12} {r['side']:<3} {r['zone']:<10} {r['action']:<10} n={r['n']}")
    elif args.cmd == "backtest":
        from .db import DB
        from .backtest import holdout
        db = DB(cfg.db_path)
        res = holdout(db, cfg)
        print(json.dumps(res, ensure_ascii=False, indent=1, default=str))
    elif args.cmd == "qa":
        from .db import DB
        from .backtest import qa_export
        db = DB(cfg.db_path)
        out = args.out or os.path.join(os.path.dirname(cfg.db_path), "..", "backtest",
                                       "retrieval_qa_batch.json")
        path = qa_export(db, cfg, os.path.abspath(out), args.n)
        print(f"QA batch written: {path}")
    elif args.cmd == "ablation":
        from .db import DB
        from .backtest import ablation
        db = DB(cfg.db_path)
        res = ablation(db, cfg)
        print(f"{'subset':<22} {'n':>4} {'brier':>7} {'maxdev_pp':>10}")
        for name, r in res.items():
            print(f"{name:<22} {r['n_predictions']:>4} {r['brier']:>7.4f} "
                  f"{r['max_calibration_deviation_pp']:>10.2f}")
    elif args.cmd == "api":
        from .api import serve
        ui_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__)))), "ui")
        serve(cfg.db_path, ui_dir, port=args.port, host=args.host)
    print(f"[done in {time.time() - t0:.1f}s]")


def _cmd_ingest(cfg: Config, demo_path: str, steamid: int | None):
    from .db import DB
    from .ingest import parse_demo, persist
    from .decision import analyze_match

    demo_path = os.path.abspath(demo_path)
    if not os.path.isfile(demo_path):
        print(f"demo not found: {demo_path}")
        sys.exit(1)
    db = DB(cfg.db_path)
    print(f"parsing {demo_path} ...")
    demo = parse_demo(demo_path, cfg)
    path = persist(demo, cfg, db)
    print(f"canonical: {path}")
    print(f"map={demo.header.get('map_name')} rounds={len(demo.rounds)} "
          f"players={len(demo.players)} ticks={demo.tick_range}")
    dps = analyze_match(demo, cfg, db)
    from collections import Counter
    acts = Counter(d["observed_action"] for d in dps)
    print(f"decision points: {len(dps)}  by action: {dict(acts)}")
    if steamid:
        mine = [d for d in dps if d["steamid"] == steamid]
        print(f"for steamid {steamid}: {len(mine)} DPs")
    for d in dps[:15]:
        o = db.get_outcome(d["dp_id"]) or {}
        print(f"  r{d['round']:>2} t{d['decision_tick']:>6} {d['observed_action']:<10} "
              f"{d['player_name'][:12]:<12} {d['zone']:<8} surv={o.get('survival')} "
              f"duel={o.get('duel_result')}")


if __name__ == "__main__":
    main()
