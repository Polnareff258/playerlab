"""Small statistical helpers (deterministic, no LLM): Wilson CI, Brier,
calibration bins. Confidence intervals per COUNTERFACTUAL_DESIGN §8.
"""
from __future__ import annotations

import math


def wilson_ci(k: int, n: int, z: float = 1.96):
    """Wilson score interval for a proportion. Returns (p, lo, hi)."""
    if n <= 0:
        return (0.0, 0.0, 0.0)
    p = k / n
    z2 = z * z
    denom = 1 + z2 / n
    center = (p + z2 / (2 * n)) / denom
    margin = z * math.sqrt((p * (1 - p) + z2 / (4 * n)) / n) / denom
    return (p, max(0.0, center - margin), min(1.0, center + margin))


def brier(preds, ys):
    """Mean Brier score for probability predictions vs binary outcomes."""
    n = len(preds)
    if n == 0:
        return float("nan")
    return sum((p - y) ** 2 for p, y in zip(preds, ys)) / n


def calibration_bins(preds, ys, n_bins: int = 5):
    """Bucketed calibration: each bin reports (mean_pred, actual_rate, n)."""
    pairs = sorted(zip(preds, ys))
    n = len(pairs)
    if n == 0:
        return []
    bins = []
    per = max(1, math.ceil(n / n_bins))
    for i in range(0, n, per):
        chunk = pairs[i:i + per]
        mean_p = sum(p for p, _ in chunk) / len(chunk)
        rate = sum(y for _, y in chunk) / len(chunk)
        bins.append({"n": len(chunk), "mean_pred": round(mean_p, 4),
                     "actual_rate": round(rate, 4),
                     "dev_pp": round(abs(mean_p - rate) * 100, 2)})
    return bins


def max_calibration_deviation(bins) -> float:
    if not bins:
        return float("inf")
    return max(b["dev_pp"] for b in bins)
