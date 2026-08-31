"""Reference / Pro corpus interfaces (spec §36-§42).

V1.2 ships only Null/Local-stub providers: the main PlayerLab pipeline never
depends on any specific pro-data source (no HLTV/FACEIT/scraper coupling).
These interfaces are the contract future Pro modules must implement.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class DecisionSample:
    state_sequence: list
    player_known_state: dict
    commitment_state: str
    situational_role: str
    intent: str
    feasible_actions: dict
    observed_action: str | None
    outcome: dict
    source: str
    evidence_refs: list = field(default_factory=list)


class ReferenceCorpusProvider:
    """Corpus of reference states (personal or pro) for retrieval."""

    def query_samples(self, state: dict, filters: dict | None = None) -> list:
        raise NotImplementedError

    def get_metadata(self) -> dict:
        raise NotImplementedError

    def get_version(self) -> str:
        raise NotImplementedError


class DecisionSampleProvider:
    """Unified provider of DecisionSamples (personal + reference)."""

    def samples_for(self, match_id: str, filters: dict | None = None) -> list[DecisionSample]:
        raise NotImplementedError

    def get_version(self) -> str:
        raise NotImplementedError


class ReferencePolicyProvider:
    """Reference action policy for a decision state (Pro Reference Behavior,
    never 'Correct Answer')."""

    def policy_for(self, state: dict, filters: dict | None = None) -> dict:
        return {"action_distribution": {}, "sample_count": 0, "similarity": None,
                "confidence": None, "source": "null", "reference_version": "null"}

    def get_version(self) -> str:
        return "null"


class NullReferenceProvider(ReferenceCorpusProvider, DecisionSampleProvider,
                            ReferencePolicyProvider):
    """Default provider when no reference corpus is configured."""

    def query_samples(self, state, filters=None):
        return []

    def get_metadata(self):
        return {"type": "null", "note": "no reference corpus configured"}

    def get_version(self):
        return "null"

    def samples_for(self, match_id, filters=None):
        return []


class LocalStubReferenceProvider(NullReferenceProvider):
    """Demonstration provider: derives a policy from the local decision_states
    (personal history only) to prove the interface works end-to-end."""

    def __init__(self, db):
        self.db = db

    def get_metadata(self):
        return {"type": "local-stub", "note": "local personal-history stub (not a pro corpus)"}

    def get_version(self):
        return "local-stub-1"

    def policy_for(self, state, filters=None):
        import collections
        action_counter = collections.Counter()
        n = 0
        for s in self.db.all_states():
            if s["labels"].get("action"):
                action_counter[s["labels"]["action"]] += 1
                n += 1
        total = max(1, n)
        return {"action_distribution": {k: round(v / total, 4)
                                        for k, v in sorted(action_counter.items())},
                "sample_count": n, "similarity": None, "confidence": None,
                "source": "local-history", "reference_version": self.get_version()}
