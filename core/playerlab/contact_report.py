"""Contact regression + sanity + performance reporting (V1.3.4.1 PART P/R/S/T).

Provides:
  * run_contact_regression(db, cfg, expected_rows) — compare human-confirmed
    samples against the classifier (PART P §45).
  * sanity_checks(predictions, cfg) — MUTUAL-rate, UNKNOWN-rate and
    PEEK-inflation warnings (PART S §47-§49).
  * contact_benchmark(predictions, geometry_queries, cache_hits, elapsed) —
    performance counters (PART T §52).
  * initiation_distribution(predictions) — old/new comparison (PART R §46),
    flagging suspicious MUTUAL rates.

An honest regression set without human labels is reported as
PENDING_HUMAN_REGRESSION_REVIEW (docs/CONTACT_REGRESSION_RESULTS.md).
"""
from __future__ import annotations

import time


# labels accepted from human regression rows
HUMAN_LABEL_SOURCES = ("HUMAN", "IMPORTED_EXPERT", "CONSENSUS")


def run_contact_regression(db, cfg, expected_rows: list[dict]) -> dict:
    """expected_rows: [{"sample_id"|"match_id"|"tick", "initiation": str,
    "action": str, "label_source": str}...]. Compares classifier predictions
    persisted on those samples (contact_action_samples table)."""
    samples = {s["id"]: s for s in db.get_contact_action_samples(limit=100000)}
    rows = []
    for exp in expected_rows:
        sid = exp.get("sample_id")
        s = samples.get(sid) if sid else None
        if s is None:
            # fall back to match+tick lookup
            for cand in samples.values():
                if (cand.get("match_id") == exp.get("match_id")
                        and cand.get("tick") == exp.get("tick")):
                    s = cand
                    break
        if s is None:
            rows.append({"sample_id": sid, "status": "missing",
                         "expected_initiation": exp.get("initiation"),
                         "expected_action": exp.get("action")})
            continue
        pred = s.get("prediction") or {}
        init_ok = (pred.get("initiation") == exp.get("initiation")
                   if exp.get("initiation") else None)
        act_ok = (pred.get("top_label") == exp.get("action")
                  if exp.get("action") else None)
        rows.append({
            "sample_id": sid,
            "expected_initiation": exp.get("initiation"),
            "predicted_initiation": pred.get("initiation"),
            "initiation_pass": init_ok,
            "expected_action": exp.get("action"),
            "predicted_action": pred.get("top_label"),
            "action_pass": act_ok,
            "confidence": pred.get("confidence"),
            "label_source": s.get("label_source"),
        })
    passed = sum(1 for r in rows if r.get("initiation_pass") is True
                 and r.get("action_pass") is not False)
    return {"total": len(rows), "passed": passed,
            "rows": rows,
            "verdict": ("PENDING_HUMAN_REGRESSION_REVIEW"
                        if not any(r.get("label_source") in HUMAN_LABEL_SOURCES
                                   for r in rows)
                        else "run")}


def sanity_checks(predictions: list[dict], cfg) -> list[dict]:
    """PART S §47-§49. Returns warning rows; never mutates results."""
    warnings = []
    total = len(predictions)
    if not total:
        return warnings
    mutual = sum(1 for p in predictions if p.get("initiation") == "MUTUAL")
    unknown = sum(1 for p in predictions
                  if p.get("initiation") in ("UNKNOWN", "STATIC_CONTACT")
                  or p.get("top_label") == "UNKNOWN")
    peek = sum(1 for p in predictions if p.get("top_label") == "PEEK")
    mutual_rate = mutual / total
    # configurable threshold with a sane default (V1.3.4.1: MUTUAL should be
    # rare; if geometry is missing many contacts will be UNKNOWN instead)
    threshold = getattr(cfg, "mutual_rate_warning", 0.25)
    if mutual_rate > threshold:
        warnings.append({
            "check": "mutual_rate",
            "level": "WARNING",
            "value": round(mutual_rate, 3),
            "message": "INITIATION_CLASSIFIER_SUSPECT: MUTUAL rate unusually "
                       f"high ({mutual_rate:.0%}); motion contrast may be weak"
                       " or the window too short — do not treat as data truth.",
        })
    if unknown / total > getattr(cfg, "unknown_rate_warning", 0.6):
        warnings.append({
            "check": "unknown_rate",
            "level": "INFO",
            "value": round(unknown / total, 3),
            "message": "High unknown rate due to missing visibility evidence "
                       "(geometry unavailable) — acceptable.",
        })
    # peek inflation: warn, never auto-fix (PART S §49)
    if peek / total > getattr(cfg, "peek_inflation_warning", 0.5):
        warnings.append({
            "check": "peek_inflation",
            "level": "WARNING",
            "value": round(peek / total, 3),
            "message": f"PEEK rate {peek / total:.0%} above the historical "
                       "ratio — possible over-classification; review before "
                       "trusting (results not modified).",
        })
    return warnings


def initiation_distribution(predictions: list[dict]) -> dict:
    """PART R §46: initiator distribution + suspicious-MUTUAL flag."""
    dist = {}
    for p in predictions:
        k = p.get("initiation", "UNKNOWN")
        dist[k] = dist.get(k, 0) + 1
    total = sum(dist.values()) or 1
    out = {k: {"n": v, "rate": round(v / total, 3)} for k, v in dist.items()}
    out["_suspect"] = (dist.get("MUTUAL", 0) / total > 0.25
                       if "MUTUAL" in dist else False)
    return out


def contact_benchmark(predictions: list[dict], geometry_queries: int,
                      cache_hits: int, elapsed_s: float) -> dict:
    """PART T §52: contact windows / geometry queries / cache hit rate /
    total time."""
    total_queries = geometry_queries + cache_hits
    return {
        "contact_windows": len(predictions),
        "geometry_queries": geometry_queries,
        "cache_hit_rate": round(cache_hits / total_queries, 3) if total_queries else None,
        "contact_semantics_total_s": round(elapsed_s, 3),
        "per_window_ms": round(elapsed_s * 1000.0 / max(1, len(predictions)), 2),
    }
