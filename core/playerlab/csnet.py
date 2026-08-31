"""CSNetProvider (V1.2.1 spec §31/§70): optional adapter over CS-NET.

PlayerLab canonical state -> adapter -> CS-NET state -> CS-NET output
-> ModelEvidence. Never copies CS-NET internals; imports them from the pinned
clone (external/cs-net, see VERSION.lock). Fully optional: import errors or
missing weights degrade to NullGameModelProvider behaviour (spec §30/§62).

Hindsight boundary (spec §34): all predictions are outcome/value evidence
marked state_scope=GROUND_TRUTH_STATE (CS-NET consumes the full match state,
not what a player knew). They must never enter PlayerKnownState and never
drive responsibility directly (spec §35).
"""
from __future__ import annotations

import os
import time

from .model_provider import (GameModelProvider, ModelEvidence,
                             STATE_SCOPE_GROUND_TRUTH)

# task ids supported by this adapter (subset of CS-NET heads)
_HEAD_DIRS = {
    "win_rate": "win_rate",
    "survival": "alive",
    "next_kill": "nxt_kill",
    "next_death": "nxt_death",
    "duel": "duel",
}


class CSNetProvider(GameModelProvider):
    """Lazy-loading adapter. Models are loaded per head on first use
    (spec §28: load requested heads lazily; win_rate is the primary head)."""

    provider_name = "csnet"

    def __init__(self, repo_dir: str | None = None,
                 models_dir: str | None = None,
                 device: str = "cpu"):
        # default repo_dir = <PlayerLab root>/external/cs-net
        _root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        self.repo_dir = repo_dir or os.environ.get(
            "CSNET_REPO_DIR", os.path.join(_root, "external", "cs-net"))
        self.models_dir = models_dir or os.environ.get(
            "CSNET_MODELS_DIR", os.path.join(self.repo_dir, "cs-net-models"))
        self.device = device
        self._loaded = {}   # head -> (model, cfg)
        self._tokenizer = None
        self._error = None
        self._try_import()

    # ------------------------------------------------------------ bootstrap
    def _try_import(self):
        """Import CS-NET modules; failure must never raise to callers."""
        try:
            import sys
            repo = os.path.abspath(self.repo_dir)
            if repo not in sys.path:
                sys.path.insert(0, repo)
            pylibs = os.path.join(repo, ".pylibs")
            if os.path.isdir(pylibs) and pylibs not in sys.path:
                sys.path.insert(0, pylibs)
            # CS-NET's load_tokenizer_cfg / find_head_yaml use repo-relative
            # paths, so the import must run with the repo as cwd. Save and
            # restore the caller's cwd (adapter runs in the same process).
            self._cwd = os.getcwd()
            os.chdir(repo)
            import torch  # noqa: F401
            from demo_analysis.get_round_win_rate import (  # noqa: F401
                load_model_and_cfg, load_tokenizer_cfg, build_weapon_index,
                build_projectile_index, apply_temperature_scaling)
            self._torch = torch
            self._load_model_and_cfg = load_model_and_cfg
            self._tokenizer_cfg = load_tokenizer_cfg()
            self._weapon2idx = build_weapon_index(self._tokenizer_cfg)
            self._projectile2idx = build_projectile_index(self._tokenizer_cfg)
            self._apply_temperature_scaling = apply_temperature_scaling
            self._ready = True
        except Exception as e:  # noqa: BLE001
            self._ready = False
            self._error = f"{type(e).__name__}: {e}"
            try:
                if getattr(self, "_cwd", None):
                    os.chdir(self._cwd)
            except Exception:  # noqa: BLE001
                pass

    @property
    def ready(self) -> bool:
        return bool(getattr(self, "_ready", False))

    # ------------------------------------------------------------ heads
    def _head_model(self, task: str):
        """Load the CS-NET head for a task, lazily, on CPU by default."""
        head = _HEAD_DIRS.get(task)
        if head is None:
            raise ValueError(f"unsupported task: {task}")
        if not self.ready:
            raise RuntimeError(f"CS-NET not importable: {self._error}")
        if head in self._loaded:
            return self._loaded[head]
        head_dir = os.path.join(self.models_dir, head)
        if not os.path.isdir(head_dir):
            raise FileNotFoundError(f"CS-NET head dir missing: {head_dir}")
        model, cfg, ckpt = self._load_model_and_cfg(head_dir, self._torch.device(self.device))
        self._loaded[head] = (model, cfg)
        return model, cfg

    def _evidence(self, task: str, prediction, state: dict, **kw) -> ModelEvidence:
        return ModelEvidence(
            provider="csnet", provider_version="v1.2.1-1",
            model_version="cs-net-v3", task=task, prediction=prediction,
            calibrated=True,
            calibration_metadata=self._calibration(task),
            input_match_id=kw.get("match_id"), input_round=kw.get("round"),
            input_tick=kw.get("tick"),
            state_scope=STATE_SCOPE_GROUND_TRUTH,
            evidence_type="state_value")

    def _calibration(self, task: str) -> dict | None:
        try:
            _, cfg = self._head_model(task)
            cal = (cfg or {}).get("calibration", {}).get("temperature_scaling")
            if cal:
                return {"temperature": cal.get("temperature")}
        except Exception:  # noqa: BLE001
            pass
        return None

    # ------------------------------------------------------------ predict
    def _predict_win(self, state: dict, **kw) -> ModelEvidence:
        """Win probability from a canonical PlayerLab state frame.
        Expects state to contain CS-NET-compatible players_info or a raw
        CS-NET state dict (see CSNET_FIELD_MAPPING.md)."""
        model, cfg = self._head_model("win_rate")
        batch = self._build_batch(state)
        try:
            with self._torch.no_grad():
                logits, _ = model({**batch, "label": self._torch.zeros(1, device=self.device)})
            logits = self._apply_temperature_scaling(logits, cfg)
            prob = float(self._torch.sigmoid(logits).item())
        finally:
            if getattr(self, "_cwd", None):
                os.chdir(self._cwd)
        return self._evidence("win_rate", prob, state, **kw)

    def predict_win_probability(self, state: dict, **kw) -> ModelEvidence:
        if not self.ready:
            return self._unavailable("win_rate", state, **kw)
        try:
            return self._predict_win(state, **kw)
        except Exception as e:  # noqa: BLE001
            return self._unavailable("win_rate", state, **kw, error=str(e))

    def predict_survival(self, state: dict, **kw) -> ModelEvidence:
        return self._unsupported("survival", state, **kw)

    def predict_next_kill(self, state: dict, **kw) -> ModelEvidence:
        return self._unsupported("next_kill", state, **kw)

    def predict_next_death(self, state: dict, **kw) -> ModelEvidence:
        return self._unsupported("next_death", state, **kw)

    def predict_duels(self, state: dict, **kw) -> ModelEvidence:
        return self._unsupported("duel", state, **kw)

    def _unsupported(self, task, state, **kw) -> ModelEvidence:
        """Not implemented in this spike (spec §70: at least win_rate real)."""
        return self._evidence(task, None, state, **kw) if self.ready else self._unavailable(task, state, **kw)

    def _unavailable(self, task, state, **kw) -> ModelEvidence:
        error = kw.pop("error", "")
        ev = ModelEvidence(provider="csnet", provider_version="v1.2.1-1",
                           model_version="cs-net-v3", task=task, prediction=None,
                           state_scope=STATE_SCOPE_GROUND_TRUTH,
                           evidence_type="unavailable",
                           input_match_id=kw.get("match_id"), input_round=kw.get("round"),
                           input_tick=kw.get("tick"))
        if error:
            ev.calibration_metadata = {"error": error}
        return ev

    # ------------------------------------------------------------ batch build
    def _build_batch(self, state: dict) -> dict:
        """Single-state batch (SPACE_SIZE=31). Accepts a raw CS-NET state
        dict (players_info, map_name, bomb_position, ...) or a PlayerLab
        frame pre-converted by the adapter (see CSNET_FIELD_MAPPING.md)."""
        from demo_analysis.get_round_win_rate import build_batch
        return build_batch([state], self._weapon2idx, self._projectile2idx,
                           self._torch.device(self.device))

    # ------------------------------------------------------------ metadata
    def get_metadata(self) -> dict:
        if not self.ready:
            return {"provider": "csnet", "version": "v1.2.1-1",
                    "model_version": "cs-net-v3", "status": "error",
                    "note": f"CS-NET not importable: {self._error}"}
        return {"provider": "csnet", "version": "v1.2.1-1",
                "model_version": "cs-net-v3", "status": "ready",
                "device": self.device,
                "note": f"heads: {sorted(self._loaded.keys())}",
                "repo": os.path.abspath(self.repo_dir),
                "models_dir": os.path.abspath(self.models_dir)}

    def get_supported_tasks(self) -> list[str]:
        if not self.ready:
            return []
        return ["win_rate"]
