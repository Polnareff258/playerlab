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
    p_alpha = sub.add_parser("alpha", help="ingest + alpha pipeline on a demo")
    p_alpha.add_argument("demo")
    sub.add_parser("patterns", help="alpha pattern aggregation")
    sub.add_parser("focus", help="current active training targets")
    sub.add_parser("targets", help="training targets + measurements")
    sub.add_parser("target-validate", help="run validation on active targets")
    sub.add_parser("review", help="pending review queue")
    p_ann = sub.add_parser("annotations", help="annotation commands")
    p_ann.add_argument("action", choices=("export", "stats"))
    p_ann.add_argument("--out", default="")
    sub.add_parser("context-eval", help="context/intent/role/commitment/responsibility agreement")
    p_id = sub.add_parser("intent-dataset", help="export tiny-model intent dataset")
    p_id.add_argument("--out", default="")
    p_id.add_argument("--format", default="jsonl", choices=("jsonl", "parquet"))
    p_rd = sub.add_parser("responsibility-dataset", help="export responsibility dataset")
    p_rd.add_argument("--out", default="")
    p_mi = sub.add_parser("model-intelligence", help="Model Intelligence status (CS-NET)")
    p_mi.add_argument("--provider", default="", help="provider: null | csnet")
    p_mi.add_argument("--models-dir", default="", help="CS-NET models root dir")
    # V1.3 decision episodes (spec §70)
    p_dec = sub.add_parser("decisions", help="list DecisionEpisodes")
    p_dec.add_argument("--match", default="", help="filter by match id")
    p_dec.add_argument("--family", default="", help="filter by family")
    p_dec.add_argument("--limit", type=int, default=20)
    p_ds = sub.add_parser("decision-show", help="show one DecisionEpisode")
    p_ds.add_argument("episode_id")
    sub.add_parser("decision-review", help="pending DecisionEpisode review items")
    sub.add_parser("decision-stats", help="DecisionEpisode distributions")
    p_dpref = sub.add_parser("decision-preference", help="submit a pairwise preference")
    p_dpref.add_argument("episode_id")
    p_dpref.add_argument("choice", help="A / B / BOTH / NEITHER / UNSURE")
    # V1.3.2 player-centric + calibration (PART A/D/E)
    p_focus = sub.add_parser("focus-player", help="set/get Focus Player")
    p_focus.add_argument("--match", default="", help="match id")
    p_focus.add_argument("--steam", type=int, default=None, help="steam id")
    p_focus.add_argument("--remember", action="store_true", help="persist as 'This is me'")
    p_ov = sub.add_parser("player-overview", help="player match overview")
    p_ov.add_argument("match")
    p_ov.add_argument("steam", type=int)
    p_mom = sub.add_parser("moments", help="Top Review Moments for a player")
    p_mom.add_argument("match")
    p_mom.add_argument("steam", type=int)
    p_cal = sub.add_parser("calibration", help="generate calibration samples")
    p_cal.add_argument("match")
    p_cal.add_argument("--player", type=int, default=None)
    sub.add_parser("calibration-stats", help="detector calibration metrics")
    p_crev = sub.add_parser("calibration-review", help="review one calibration sample")
    p_crev.add_argument("sample_id")
    p_crev.add_argument("label", help="YES / NO / UNSURE / taxonomy label")
    p_crev.add_argument("--fp-reason", default="", help="false positive reason")
    sub.add_parser("recompute-calibration", help="recompute CalibrationState from eligible labels only")
    p_cex = sub.add_parser("calibration-export", help="export annotations (JSONL/Parquet)")
    p_cex.add_argument("--out", default="")
    p_cex.add_argument("--format", default="jsonl", choices=("jsonl", "parquet"))
    p_ab = sub.add_parser("geometry-ab", help="geometry ON/OFF A/B experiment on a demo")
    p_ab.add_argument("demo")
    p_ab.add_argument("--out", default="", help="write full diff JSON")
    # V1.3.4.1 contact reports
    p_cr = sub.add_parser("contact-regression", help="compare human-confirmed "
                          "contact samples against the classifier")
    p_cr.add_argument("--samples", default="", help="JSON/CSV of expected rows "
                      "(sample_id|match_id|tick + initiation/action)")
    p_cr.add_argument("--out", default="", help="write report JSON")
    p_cs = sub.add_parser("contact-sanity", help="sanity metrics over persisted "
                          "contact predictions (MUTUAL/UNKNOWN/PEEK rates)")
    p_cs.add_argument("--out", default="", help="write report JSON")
    p_cb = sub.add_parser("contact-benchmark", help="performance metrics over "
                          "persisted contact predictions")
    p_cb.add_argument("--out", default="", help="write report JSON")
    p_batch = sub.add_parser("batch", help="batch-analyze demo files/directories")
    p_batch.add_argument("paths", nargs="+", help=".dem files or directories")
    p_batch.add_argument("--no-recursive", action="store_true", help="do not recurse into subdirs")
    p_batch.add_argument("--dry-run", action="store_true", help="list what would be analyzed")
    p_batch.add_argument("--force", action="store_true", help="re-analyze already-ingested demos")
    p_batch.add_argument("--limit", type=int, default=None, help="max demos to process")
    p_batch.add_argument("--report", default="", help="write JSON summary report to path")
    p_batch.add_argument("--quiet", action="store_true", help="suppress per-demo progress")
    p_api = sub.add_parser("api", help="start local UI+API")
    p_api.add_argument("--port", type=int, default=8123)
    p_api.add_argument("--host", default="127.0.0.1")
    p_api.add_argument("--open", action="store_true",
                       help="open the browser automatically after startup")

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
    elif args.cmd == "alpha":
        _cmd_alpha(cfg, args.demo)
    elif args.cmd == "patterns":
        from .db import DB
        db = DB(cfg.db_path)
        for p in db.get_patterns():
            print(f"{p['pattern_type']:<12} n={p['sample_count']:>3} "
                  f"viol={p['violation_rate']:.2f} conf={p['confidence']:.2f} "
                  f"cf={p['counterfactual_support']}")
    elif args.cmd == "focus":
        from .db import DB
        from .training import active_focus
        db = DB(cfg.db_path)
        for t in active_focus(db):
            print(f"[{t['status']}] {t['name']} | baseline={t['baseline']:.2f} "
                  f"goal={t['goal']:.2f} progress={t['progress']:.2f}")
    elif args.cmd == "targets":
        from .db import DB
        db = DB(cfg.db_path)
        for t in db.get_targets():
            print(f"[{t['status']:<10}] {t['name']}")
            for m in db.get_measurements(t["target_id"]):
                print(f"    window {m['window_start'][:10]}..{m['window_end'][:10]} "
                      f"n={m['opportunities']} rate={m['rate']:.3f} "
                      f"behavior={m['behavior_verdict']} outcome={m['outcome_verdict']}")
    elif args.cmd == "target-validate":
        from .db import DB
        from .training import validate_targets
        db = DB(cfg.db_path)
        for v in validate_targets(db, cfg):
            print(v)
    elif args.cmd == "review":
        from .db import DB
        db = DB(cfg.db_path)
        for r_ in db.get_review_queue(limit=20):
            print(f"{r_['priority']:.2f} {r_['item_type']:<16} r{r_['round']} t{r_['tick']} "
                  f"pred={r_['model_prediction']} conf={r_['model_confidence']}")
    elif args.cmd == "context-eval":
        from .db import DB
        from .annotation import annotation_stats
        db = DB(cfg.db_path)
        print(json.dumps(annotation_stats(db), ensure_ascii=False, indent=1, default=str))
    elif args.cmd == "intent-dataset":
        from .db import DB
        from .annotation import export_intent_dataset
        db = DB(cfg.db_path)
        out = args.out or os.path.join(os.path.dirname(cfg.db_path), "..", "backtest",
                                       f"intent_dataset.{'parquet' if args.format == 'parquet' else 'jsonl'}")
        print(f"written: {export_intent_dataset(db, os.path.abspath(out), args.format)} "
              f"({len(db.get_intent_samples())} samples)")
    elif args.cmd == "responsibility-dataset":
        from .db import DB
        from .annotation import export_responsibility_dataset
        db = DB(cfg.db_path)
        out = args.out or os.path.join(os.path.dirname(cfg.db_path), "..", "backtest",
                                       "responsibility_dataset.jsonl")
        print(f"written: {export_responsibility_dataset(db, os.path.abspath(out))}")
    elif args.cmd == "model-intelligence":
        from .model_provider import get_provider
        provider = args.provider or cfg.model_provider
        kw = {}
        if args.models_dir:
            kw["models_dir"] = os.path.abspath(args.models_dir)
        if cfg.csnet_repo_dir:
            kw.setdefault("repo_dir", os.path.abspath(cfg.csnet_repo_dir))
        prov = get_provider(provider, **kw)
        print(json.dumps(prov.get_metadata(), ensure_ascii=False, indent=1, default=str))
        print("supported tasks:", prov.get_supported_tasks())
    elif args.cmd == "decisions":
        from .db import DB
        db = DB(cfg.db_path)
        eps = db.get_decision_episodes(match_id=args.match or None,
                                       family=args.family or None, limit=args.limit)
        print(f"{'family':<24} {'obs':<12} {'eval':<20} {'actionability':<18} tick")
        for e in eps:
            print(f"{e['family']:<24} {e['observed_action']:<12} "
                  f"{e['decision_evaluation']:<20} {e['actionability']:<18} {e['anchor_tick']}")
        print(f"total: {len(eps)}")
    elif args.cmd == "decision-show":
        from .db import DB
        db = DB(cfg.db_path)
        ep = db.get_decision_episode(args.episode_id)
        if not ep:
            print(f"episode not found: {args.episode_id}")
        else:
            print(json.dumps({
                "id": ep["id"], "family": ep["family"], "round": ep["round"],
                "tick": ep["anchor_tick"], "observed": ep["observed_action"],
                "decision_domain": ep.get("decision_domain"),
                "strategic": ep.get("strategic_evaluation"),
                "engagement": ep.get("engagement_evaluation"),
                "execution": ep.get("execution_evaluation"),
                "evidence_sufficiency": ep.get("evidence_sufficiency"),
                "actionability": ep["actionability"],
                "engagement_method": ep.get("engagement_method"),
                "weapon_matchup": ep.get("weapon_matchup"),
                "information_advantage": ep.get("information_advantage"),
                "execution_primitives": ep.get("execution_primitives"),
                "movement_effect": ep.get("movement_effect"),
                "state_value_before": ep.get("state_value_before"),
                "macro": ep["macro_context"], "intent": ep["intent"],
                "commitment": ep["commitment_state"],
                "candidates": ep.get("candidates", []),
                "evidence": ep.get("evidence", []),
            }, ensure_ascii=False, indent=1, default=str))
    elif args.cmd == "decision-review":
        from .db import DB
        db = DB(cfg.db_path)
        for r_ in db.get_review_queue(limit=30):
            if r_["item_type"] != "decision_episode":
                continue
            print(f"{r_['priority']:.2f} {r_['event_id']} r{r_['round']} t{r_['tick']} "
                  f"pred={r_['model_prediction']} | {r_['rationale']}")
    elif args.cmd == "decision-stats":
        from .db import DB
        from collections import Counter
        db = DB(cfg.db_path)
        eps = db.get_decision_episodes(limit=2000)
        print("total:", len(eps))
        print("family:", dict(Counter(e["family"] for e in eps)))
        print("evaluation:", dict(Counter(e["decision_evaluation"] for e in eps)))
        print("actionability:", dict(Counter(e["actionability"] for e in eps)))
        print("observed:", dict(Counter(e["observed_action"] for e in eps)))
        print("strategic:", dict(Counter(e.get("strategic_evaluation") for e in eps)))
        print("engagement:", dict(Counter(e.get("engagement_evaluation") for e in eps)))
        print("execution:", dict(Counter(e.get("execution_evaluation") for e in eps)))
        print("sufficiency:", dict(Counter(e.get("evidence_sufficiency") for e in eps)))
        methods = Counter()
        for e in eps:
            m = (e.get("engagement_method") or {}).get("method")
            if m:
                methods[m] += 1
        print("engagement methods:", dict(methods))
        prims = Counter()
        for e in eps:
            for p in (e.get("execution_primitives") or []):
                prims[p] += 1
        print("execution primitives:", dict(prims))
    elif args.cmd == "decision-preference":
        from .db import DB
        from .episode import _candidate_actions  # noqa: F401 (schema reuse)
        db = DB(cfg.db_path)
        ep = db.get_decision_episode(args.episode_id)
        if not ep:
            print(f"episode not found: {args.episode_id}")
        else:
            cands = ep.get("candidates", [])
            if len(cands) < 2:
                print("need >=2 feasible candidates for preference")
            else:
                a, b = cands[0]["action"], cands[1]["action"]
                import uuid as _uuid
                db.insert_decision_preference({
                    "id": _uuid.uuid4().hex[:16], "episode_id": ep["id"],
                    "match_id": ep["match_id"], "round": ep["round"],
                    "tick": ep["anchor_tick"], "candidate_a": a, "candidate_b": b,
                    "human_choice": args.choice, "human_confidence": 0.6,
                    "reason_code": "OTHER"})
                print(f"preference saved: {a} vs {b} -> {args.choice}")
    elif args.cmd == "focus-player":
        from .db import DB
        from .focus import default_focus, set_focus
        db = DB(cfg.db_path)
        if args.steam is not None:
            if not args.match:
                from .focus import remember_user
                remember_user(db, args.steam, "")
                print(f"remembered steam {args.steam} as user")
            else:
                ctx = set_focus(db, args.match, args.steam, persist=args.remember)
                print(json.dumps(ctx.to_dict(), ensure_ascii=False))
        else:
            ctx = default_focus(db, args.match or "")
            print(json.dumps(ctx.to_dict(), ensure_ascii=False))
    elif args.cmd == "player-overview":
        from .db import DB
        from .moments import player_match_overview
        db = DB(cfg.db_path)
        print(json.dumps(player_match_overview(db, cfg, args.match, args.steam),
                         ensure_ascii=False, indent=1, default=str))
    elif args.cmd == "moments":
        from .db import DB
        from .moments import rank_review_moments
        from .calibration import detector_calibration_map
        db = DB(cfg.db_path)
        cal = detector_calibration_map(db, cfg)
        moments = rank_review_moments(db, cfg, args.match, args.steam, calibration=cal)
        for m in moments:
            print(f"score={m['review_score']:.2f} {'GOOD' if m['is_positive'] else '  '} "
                  f"{m['primary_reason']:<42} r{m.get('round')} t{m.get('tick')} | {m['why_selected']}")
    elif args.cmd == "calibration":
        from .db import DB
        from .calibration import sample_calibration_set
        db = DB(cfg.db_path)
        samples = sample_calibration_set(db, cfg, args.match, player_id=args.player)
        print(f"generated {len(samples)} calibration samples (PENDING_REVIEW)")
        from collections import Counter
        print("by detector:", dict(Counter(s["detector_type"] for s in samples)))
    elif args.cmd == "calibration-stats":
        from .db import DB
        from .calibration import calibration_stats
        db = DB(cfg.db_path)
        print(json.dumps(calibration_stats(db, cfg), ensure_ascii=False, indent=1,
                         default=str))
    elif args.cmd == "calibration-review":
        from .db import DB
        from .calibration import submit_human_annotation
        db = DB(cfg.db_path)
        ann = submit_human_annotation(db, args.sample_id, args.label, 0.8,
                                      args.fp_reason)
        print(f"reviewed {args.sample_id} -> {args.label} "
              f"(label_source={ann['label_source']}; original prediction kept)")
    elif args.cmd == "recompute-calibration":
        from .db import DB
        from .calibration import recompute_calibration
        db = DB(cfg.db_path)
        res = recompute_calibration(db, cfg)
        for det, s in res["calibration"]["detectors"].items():
            print(f"{det:<26} human={s['human_reviewed_count']} "
                  f"sim={s['simulated_reviewed_count']} "
                  f"state={s['calibration_state']} "
                  f"pipeline={s['pipeline_validation_state']}")
        print(res["calibration"]["ground_truth_note"])
    elif args.cmd == "calibration-export":
        from .db import DB
        from .calibration import export_annotations_v2
        db = DB(cfg.db_path)
        out = args.out or os.path.join(os.path.dirname(cfg.db_path), "..",
                                       "backtest", "calibration_export.jsonl")
        print(f"written: {export_annotations_v2(db, os.path.abspath(out), args.format)}")
    elif args.cmd == "geometry-ab":
        from .db import DB
        from .ab_experiment import diff_geometry_ab
        db = DB(cfg.db_path)
        res = diff_geometry_ab(db, cfg, args.demo)
        print(json.dumps({k: v for k, v in res.items() if k != "episode_diffs"},
                         ensure_ascii=False, indent=1, default=str))
        if args.out:
            with open(args.out, "w", encoding="utf-8") as fh:
                json.dump(res, fh, ensure_ascii=False, indent=1, default=str)
            print(f"full diff written: {args.out}")
    elif args.cmd == "contact-regression":
        from .db import DB
        from .contact_report import run_contact_regression
        db = DB(cfg.db_path)
        expected = []
        if args.samples:
            with open(args.samples, "r", encoding="utf-8") as fh:
                text = fh.read()
            if args.samples.endswith(".json"):
                data = json.loads(text)
                expected = data if isinstance(data, list) else data.get("samples", [])
            else:  # CSV: sample_id,initiation,action,label_source
                import csv as _csv
                import io as _io
                expected = list(_csv.DictReader(_io.StringIO(text)))
        res = run_contact_regression(db, cfg, expected)
        print(json.dumps({k: v for k, v in res.items() if k != "rows"},
                         ensure_ascii=False, indent=1, default=str))
        if res["rows"]:
            print("--- rows ---")
            for r in res["rows"]:
                print(f"  {r.get('sample_id','?'):24s} exp={r.get('expected_initiation')}"
                      f"/{r.get('expected_action')} pred={r.get('predicted_initiation')}"
                      f"/{r.get('predicted_action')} pass={r.get('initiation_pass')}")
        if args.out:
            with open(args.out, "w", encoding="utf-8") as fh:
                json.dump(res, fh, ensure_ascii=False, indent=1, default=str)
            print(f"written: {args.out}")
    elif args.cmd == "contact-sanity":
        from .db import DB
        from .contact_report import sanity_checks, initiation_distribution
        db = DB(cfg.db_path)
        samples = db.get_contact_action_samples(review_status="pending", limit=100000)
        preds = [(s.get("prediction") or {}) for s in samples]
        preds = [p for p in preds if p]
        dist = initiation_distribution(preds)
        warnings = sanity_checks(preds, cfg)
        report = {"n_samples": len(samples), "distribution": dist,
                  "warnings": warnings}
        print(json.dumps(report, ensure_ascii=False, indent=1, default=str))
        if args.out:
            with open(args.out, "w", encoding="utf-8") as fh:
                json.dump(report, fh, ensure_ascii=False, indent=1, default=str)
            print(f"written: {args.out}")
    elif args.cmd == "contact-benchmark":
        from .db import DB
        from .contact_report import contact_benchmark
        db = DB(cfg.db_path)
        samples = db.get_contact_action_samples(review_status="pending", limit=100000)
        # geometry/cache counters are recorded per-sample in context if present
        geo_q = sum(int((s.get("context") or {}).get("geometry_queries", 0))
                    for s in samples)
        cache_hits = sum(int((s.get("context") or {}).get("cache_hits", 0))
                         for s in samples)
        # total processing time is not persisted per sample; report what we
        # can honestly compute (counts + hit rate) and mark elapsed unknown
        res = contact_benchmark([(s.get("prediction") or {}) for s in samples
                                 if s.get("prediction")],
                                geo_q, cache_hits, 0.0)
        res["note"] = ("total-time not persisted; run timing at the caller. "
                       "Counts and cache-hit rate are reported here.")
        print(json.dumps(res, ensure_ascii=False, indent=1, default=str))
        if args.out:
            with open(args.out, "w", encoding="utf-8") as fh:
                json.dump(res, fh, ensure_ascii=False, indent=1, default=str)
            print(f"written: {args.out}")
    elif args.cmd == "annotations":
        from .db import DB
        from .annotation import annotation_stats, export_annotations
        db = DB(cfg.db_path)
        if args.action == "stats":
            print(json.dumps(annotation_stats(db), ensure_ascii=False, indent=1, default=str))
        else:
            out = args.out or os.path.join(os.path.dirname(cfg.db_path), "..", "backtest",
                                           "annotations.jsonl")
            print(f"written: {export_annotations(db, os.path.abspath(out))}")
    elif args.cmd == "batch":
        from .batch import run_batch, summarize, write_report
        results = run_batch(cfg, args.paths, recursive=not args.no_recursive,
                            force=args.force, dry_run=args.dry_run,
                            limit=args.limit, verbose=not args.quiet)
        report = summarize(results)
        print("--- batch summary ---")
        print(json.dumps({k: v for k, v in report.items() if k != "failures"},
                         ensure_ascii=False, indent=1, default=str))
        if report["failed"]:
            print("failures:")
            for f_ in report["failures"]:
                print(f"  {f_['path']}: {f_['error']}")
        if args.report:
            path = write_report(report, args.report)
            print(f"report written: {path}")
    elif args.cmd == "api":
        from .api import serve
        ui_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__)))), "ui")
        if args.open:
            import threading
            import webbrowser
            url = f"http://{args.host}:{args.port}"
            threading.Timer(1.5, lambda: webbrowser.open(url)).start()
            print(f"opening {url} in the default browser...")
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


def _cmd_alpha(cfg: Config, demo_path: str):
    from .db import DB
    from .ingest import parse_demo, persist
    from .decision import analyze_match
    from .alpha import run_alpha

    demo_path = os.path.abspath(demo_path)
    if not os.path.isfile(demo_path):
        print(f"demo not found: {demo_path}")
        sys.exit(1)
    db = DB(cfg.db_path)
    print(f"parsing {demo_path} ...")
    demo = parse_demo(demo_path, cfg)
    persist(demo, cfg, db)
    analyze_match(demo, cfg, db)
    res = run_alpha(demo, cfg, db)
    print(f"alpha samples: {res['samples']}")
    for p in res["patterns"]:
        print(f"  pattern {p['pattern_type']:<12} n={p['sample_count']:>3} "
              f"rate={p['violation_rate']:.3f} conf={p['confidence']:.2f} "
              f"cf={p['counterfactual_support']}")
    print(f"bottlenecks: {[{'type': b['pattern_type'], 'level': b['level'], 'eligible': b['eligible']} for b in res['bottlenecks']]}")
    print(f"targets: {[t['name'] for t in res['targets']]}")
    print(f"review items: {res['review_items']}")


if __name__ == "__main__":
    main()
