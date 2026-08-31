"""GameModelProvider (V1.2.1 spec §22-§37).

Unified interface for optional model intelligence backends (CS-NET first).
PlayerLab core NEVER depends on a concrete provider: NullGameModelProvider is
the default, and everything keeps working without CS-NET (spec §30/§62).

ModelEvidence (spec §32): the single schema that flows into Decision Review
as *supporting evidence* — never as ground-truth judgment. The provider is
responsible for marking state_scope (GROUND_TRUTH_STATE vs PLAYER_KNOWN_STATE)
so downstream consumers can apply the hindsight boundary (spec §33-§34).

Hindsight boundary (spec §34): predictions are outcome/value evidence only.
They must never be written back into PlayerKnownState, and a win-probability
drop must never be mapped to responsibility by itself (spec §35).
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

# task ids the provider interface supports
SUPPORTED_TASKS = ("win_rate", "survival", "next_kill", "next_death", "duel")

STATE_SCOPE_GROUND_TRUTH = "GROUND_TRUTH_STATE"
STATE_SCOPE_PLAYER_KNOWN = "PLAYER_KNOWN_STATE"


@dataclass
class ModelEvidence:
    provider: str
    provider_version: str
    model_version: str
    task: str
    prediction: Any
    calibrated: bool = False
    calibration_metadata: dict | None = None
    input_match_id: str | None = None
    input_round: int | None = None
    input_tick: int | None = None
    state_scope: str = STATE_SCOPE_PLAYER_KNOWN
    evidence_type: str = "state_value"
    created_at: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%S"))

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items()}


class GameModelProvider:
    """Contract for any model intelligence backend."""

    provider_name = "abstract"

    def predict_win_probability(self, state: dict, **kw) -> ModelEvidence:
        raise NotImplementedError

    def predict_survival(self, state: dict, **kw) -> ModelEvidence:
        raise NotImplementedError

    def predict_next_kill(self, state: dict, **kw) -> ModelEvidence:
        raise NotImplementedError

    def predict_next_death(self, state: dict, **kw) -> ModelEvidence:
        raise NotImplementedError

    def predict_duels(self, state: dict, **kw) -> ModelEvidence:
        raise NotImplementedError

    def predict(self, task: str, state: dict, **kw) -> ModelEvidence:
        fn = {"win_rate": self.predict_win_probability,
              "survival": self.predict_survival,
              "next_kill": self.predict_next_kill,
              "next_death": self.predict_next_death,
              "duel": self.predict_duels}.get(task)
        if fn is None:
            raise ValueError(f"unsupported task: {task}")
        return fn(state, **kw)

    def get_metadata(self) -> dict:
        return {"provider": self.provider_name, "version": "0",
                "model_version": "none", "status": "unknown"}

    def get_supported_tasks(self) -> list[str]:
        return list(SUPPORTED_TASKS)


class NullGameModelProvider(GameModelProvider):
    """Default provider: no model installed. Every call returns an evidence
    record marked unavailable so consumers can degrade gracefully."""

    provider_name = "null"

    def _unavailable(self, task: str, state: dict, **kw) -> ModelEvidence:
        return ModelEvidence(
            provider="null", provider_version="0", model_version="none",
            task=task, prediction=None,
            state_scope=STATE_SCOPE_PLAYER_KNOWN,
            evidence_type="unavailable",
            input_match_id=kw.get("match_id"), input_round=kw.get("round"),
            input_tick=kw.get("tick"))

    def predict_win_probability(self, state, **kw):
        return self._unavailable("win_rate", state, **kw)

    def predict_survival(self, state, **kw):
        return self._unavailable("survival", state, **kw)

    def predict_next_kill(self, state, **kw):
        return self._unavailable("next_kill", state, **kw)

    def predict_next_death(self, state, **kw):
        return self._unavailable("next_death", state, **kw)

    def predict_duels(self, state, **kw):
        return self._unavailable("duel", state, **kw)

    def get_metadata(self) -> dict:
        return {"provider": "null", "version": "0", "model_version": "none",
                "status": "not_installed", "note": "no model backend configured"}

    def get_supported_tasks(self) -> list[str]:
        return []


def get_provider(configured: str = "null", **kw) -> GameModelProvider:
    """Provider factory with graceful fallback (spec §62)."""
    if configured == "csnet":
        try:
            from .csnet import CSNetProvider
            return CSNetProvider(**kw)
        except Exception as e:  # noqa: BLE001
            # never break the core pipeline: fall back to Null
            return NullGameModelProvider()
    return NullGameModelProvider()
