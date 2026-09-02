"""Optional CS-NET evidence collector; intentionally cannot classify actions."""
from __future__ import annotations

import hashlib
import os


def assist_cache_key(demo_hash: str, tick: int, model_version: str, head: str) -> str:
    return f"{demo_hash}:{tick}:{model_version}:{head}"


class CSNetAssistProvider:
    """A failure-tolerant facade for limited contact-window model evidence.

    It returns evidence only.  No method accepts or emits action labels.
    """
    def __init__(self, cfg, loader=None, cache=None):
        self.cfg, self.loader, self.cache = cfg, loader, cache if cache is not None else {}
        self.queries = self.cache_hits = 0

    def collect(self, demo_id: str, window, ticks: list[int]) -> dict | None:
        if self.loader is None or not os.path.isdir(getattr(self.cfg, "csnet_repo_dir", "")):
            return None
        chosen = list(dict.fromkeys(ticks))[:self.cfg.csnet_contact_query_budget]
        values = []
        for tick in chosen:
            key = assist_cache_key(hashlib.sha256(demo_id.encode()).hexdigest()[:16], tick,
                                   getattr(self.loader, "model_version", "unknown"), "duel")
            if key in self.cache:
                self.cache_hits += 1
                values.append(self.cache[key])
                continue
            self.queries += 1
            try:
                value = self.loader.predict_assist(demo_id, tick)
            except Exception:  # model availability must not affect classifier
                value = None
            self.cache[key] = value
            if value is not None:
                values.append(value)
        if not values:
            return None
        before, after = values[0], values[-1]
        duel_before = before.get("duel_probability")
        duel_after = after.get("duel_probability")
        return {"win_rate_before": before.get("win_rate"), "win_rate_after": after.get("win_rate"),
                "duel_probability_before": duel_before, "duel_probability_after": duel_after,
                "duel_delta": (duel_after - duel_before if None not in (duel_before, duel_after) else None),
                "survival_probability": after.get("survival_probability"),
                "next_kill_probability": after.get("next_kill_probability"),
                "next_death_probability": after.get("next_death_probability"),
                "model_version": getattr(self.loader, "model_version", "unknown"),
                "head_versions": getattr(self.loader, "head_versions", {}),
                "evidence_scope": "contact_window_sampled_ticks",
                "evidence_quality": "MODEL_EVIDENCE"}

    def cache_stats(self) -> dict:
        return {"queries": self.queries, "cache_hits": self.cache_hits,
                "cache_entries": len(self.cache)}
