"""Batch demo analysis: discover .dem files, ingest + analyze each one.

Design:
- discover(paths, recursive): collect *.dem files from files or directories.
- run_batch(): for each demo, parse -> canonical persist -> decision-point
  detection -> DB; per-demo error isolation (one bad file never stops the
  batch); idempotent skip of already-ingested demos (stable path-hash id);
  progress + summary report (JSON + console).
- dry_run / force / limit options for safe operation.

Note: single-worker sequential in V1 (parsing is CPU-heavy); a --workers
parallel mode is a later extension, not part of this module's contract yet.
"""
from __future__ import annotations

import json
import os
import time
from collections import Counter

from .config import Config
from .db import DB
from .ingest import demo_id_for, parse_demo, persist
from .decision import analyze_match

DEMO_EXT = ".dem"


def discover(paths, recursive: bool = True, limit: int | None = None) -> list[str]:
    """Collect absolute .dem file paths from files/dirs (dedup, sorted)."""
    found = set()
    for p in paths:
        p = os.path.abspath(p)
        if os.path.isfile(p):
            if p.lower().endswith(DEMO_EXT):
                found.add(p)
        elif os.path.isdir(p):
            it = os.walk(p) if recursive else [(p, [], os.listdir(p))]
            for root, _, files in it:
                for name in files:
                    if name.lower().endswith(DEMO_EXT):
                        found.add(os.path.join(root, name))
    out = sorted(found)
    if limit:
        out = out[:limit]
    return out


def analyze_one(demo_path: str, cfg: Config, db: DB, force: bool) -> dict:
    """Analyze one demo, returning a result record (never raises)."""
    t0 = time.time()
    demo_id = demo_id_for(demo_path)
    base = {"path": demo_path, "demo_id": demo_id,
            "elapsed_s": 0.0, "actions": {}, "dps_count": 0}
    try:
        if not force and db.get_match(demo_id) is not None:
            base.update(status="skipped", reason="already_ingested")
            return base
        demo = parse_demo(demo_path, cfg)
        persist(demo, cfg, db)
        dps = analyze_match(demo, cfg, db)
        acts = Counter(d["observed_action"] for d in dps)
        base.update(status="ingested", dps_count=len(dps),
                    actions={k: v for k, v in sorted(acts.items())})
    except BaseException as e:  # noqa: BLE001  per-demo isolation; pyo3 Rust
        # panics surface as PanicException (BaseException, not Exception)
        if isinstance(e, (KeyboardInterrupt, SystemExit)):
            raise
        import traceback
        base.update(status="failed", error=f"{type(e).__name__}: {e}",
                    detail=traceback.format_exc(limit=4))
    base["elapsed_s"] = round(time.time() - t0, 1)
    return base


def run_batch(cfg: Config, paths, recursive: bool = True, skip_existing: bool = True,
              force: bool = False, dry_run: bool = False, limit: int | None = None,
              verbose: bool = True) -> list[dict]:
    """Run the batch. Returns result records; rebuilds coverage at the end."""
    db = DB(cfg.db_path)
    files = discover(paths, recursive=recursive, limit=limit)
    results = []
    if not files:
        if verbose:
            print("[batch] no .dem files found")
        return results

    if dry_run:
        for i, f in enumerate(files, 1):
            demo_id = demo_id_for(f)
            exists = db.get_match(demo_id) is not None
            status = "would_skip" if (exists and not force) else "would_ingest"
            results.append({"path": f, "demo_id": demo_id, "status": status,
                            "reason": "already_ingested" if status == "would_skip" else None})
            if verbose:
                print(f"[{i}/{len(files)}] {status}: {f}")
        return results

    for i, f in enumerate(files, 1):
        rec = analyze_one(f, cfg, db, force)
        results.append(rec)
        if verbose:
            tag = rec["status"]
            extra = f" dps={rec['dps_count']} actions={rec['actions']}" if tag == "ingested" \
                else (f" ({rec['reason']})" if tag == "skipped" else f" error={rec['error']}")
            print(f"[{i}/{len(files)}] {tag:<9} {f}{extra}  ({rec['elapsed_s']}s)")
    db.rebuild_coverage()
    return results


def summarize(results: list[dict]) -> dict:
    """Aggregate a batch report (totals + action distribution + failures)."""
    n = len(results)
    counts = Counter(r["status"] for r in results)
    actions = Counter()
    dps_total = 0
    for r in results:
        if r["status"] == "ingested":
            dps_total += r["dps_count"]
            actions.update(r["actions"])
    return {
        "total": n,
        "ingested": counts.get("ingested", 0),
        "skipped": counts.get("skipped", 0),
        "failed": counts.get("failed", 0),
        "decision_points": dps_total,
        "actions": {k: v for k, v in sorted(actions.items())},
        "failures": [{"path": r["path"], "error": r.get("error"),
                      "detail": r.get("detail")} for r in results if r["status"] == "failed"],
    }


def write_report(report: dict, out_path: str) -> str:
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=1, default=str)
    return out_path
