# PlayerLab V1.3.4 Contact Semantics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace damage-first peek detection with visibility-aware, pairwise contact semantics while keeping CS-NET strictly auxiliary.

**Architecture:** Add a pure `contact_semantics` module that builds pairwise exposure relations, anchors ContactWindows, infers initiation, and emits auditable action probability distributions. `decision.py` consumes this output; storage, calibration, API/UI, A/B reporting, and CS-NET assistance consume it without being allowed to determine it.

**Tech Stack:** Python 3.13, SQLite, pytest, optional Awpy geometry, existing stdlib HTTP API and single-file JavaScript UI.

**Spec:** `docs/superpowers/specs/2026-09-02-contact-semantics-v134-design.md`

## Global Constraints

- Use `SampleDemo` as the sole V1.3.4 real-demo baseline.
- Movement alone must never establish PEEK; true PEEK requires self-created exposure transition.
- FOV alone must never establish visible LOS or high-confidence sighting.
- HOLD needs positive stability evidence and supersedes an older approach movement.
- Encounter contact is distinct from active PEEK; `MUTUAL`, `STATIC_CONTACT`, and `UNKNOWN` do not default to PEEK.
- CS-NET must never determine ObservedAction, ContactInitiation, GroundTruthLabel, HumanConsensus, or CalibrationState.
- No Tiny-model training, Pro data work, automated ground truth, online learning, full replay viewer, or score system.
- Null geometry and unavailable CS-NET must preserve a usable, honestly downgraded pipeline.

---

## File structure and interfaces

| File | Responsibility |
| --- | --- |
| `core/playerlab/contact_semantics.py` | Pure types/functions for exposure, windows, initiation, evidence, prediction, sighting, and active-learning scoring. |
| `core/playerlab/config.py` | Configurable stability, ambiguity, exposure, and CS-NET budget thresholds. |
| `core/playerlab/decision.py` | Candidate pair selection and persistence-compatible conversion of ActionPrediction into decision points. |
| `core/playerlab/engagement.py` | Derive methods only from a valid PEEK/HOLD prediction; implement LET_CROSS. |
| `core/playerlab/csnet_assist.py` | Optional assist provider and bounded SQLite-backed cache facade. |
| `core/playerlab/db.py` | Migration and repositories for samples, annotations, assist cache, and comparison runs. |
| `core/playerlab/calibration.py` | Contact-action queue, label validation, and active-learning ordering. |
| `core/playerlab/ab_experiment.py` | Old/new contact comparison and true geometry OFF/ON contact-mode run. |
| `core/playerlab/api.py`, `core/playerlab/cli.py`, `ui/index.html` | Read/write queue APIs, statistics commands, and Decision Card/Calibration UI. |
| `tests/test_v134.py` | Deterministic unit and integration coverage for all V1.3.4 regressions. |
| `docs/*.md` | Required delta, semantics, results, assist, and old/new reports. |

The core module exports exactly:

```python
def build_contact_window(demo, self_id: int, enemy_id: int, idx: dict, cfg) -> list[ContactWindow]: ...
def exposure_relations(window: ContactWindow, map_name: str, idx: dict, geometry, cfg) -> list[ExposureRelation]: ...
def classify_contact(window: ContactWindow, relations: list[ExposureRelation], idx: dict, cfg) -> ActionPrediction: ...
def sight_state(self_record: dict, enemy_record: dict, geometry_result: bool | None) -> str: ...
def active_learning_score(prediction: ActionPrediction, geometry_quality: str, assist: dict | None, context: dict, cfg) -> dict: ...
```

## Task 1: Define contact contracts and configuration

**Files:**
- Create: `core/playerlab/contact_semantics.py`
- Modify: `core/playerlab/config.py`
- Create: `tests/test_v134.py`

**Interfaces:**
- Produces frozen dataclasses `ExposureRelation`, `ContactWindow`, `HoldEvidence`, `PeekEvidence`, and `ActionPrediction` plus enum tuples used by all later tasks.
- Produces `sight_state()` used by Task 3 and `active_learning_score()` used by Task 5.

- [ ] **Step 1: Write failing contract tests**

```python
from playerlab.contact_semantics import ActionPrediction, sight_state

def test_sight_state_requires_geometry_for_visible():
    assert sight_state({"in_fov": True}, {}, None) == "POSSIBLY_VISIBLE"
    assert sight_state({"in_fov": True}, {}, False) == "IN_FOV_OCCLUDED"
    assert sight_state({"in_fov": True}, {}, True) == "VISIBLE"

def test_action_prediction_is_a_distribution():
    p = ActionPrediction("HOLD", {"HOLD": .74, "PEEK": .19, "REPOSITION": .07}, .74, False, "ENEMY_INITIATED", {}, None)
    assert abs(sum(p.probabilities.values()) - 1.0) < 1e-9
```

- [ ] **Step 2: Run the targeted test and confirm import failure**

Run: `pytest tests/test_v134.py -k 'sight_state or action_prediction' -v`

Expected: FAIL because `playerlab.contact_semantics` does not exist.

- [ ] **Step 3: Implement dataclasses, enum constants, normalizer, sighting, and scoring**

```python
@dataclass(frozen=True)
class ActionPrediction:
    top_label: str
    probabilities: dict[str, float]
    confidence: float
    ambiguous: bool
    initiation: str
    evidence: dict[str, object]
    subtype: str | None

def sight_state(self_record, enemy_record, geometry_result):
    if not self_record.get("in_fov"):
        return "OUT_OF_FOV"
    if geometry_result is True:
        return "VISIBLE"
    return "IN_FOV_OCCLUDED" if geometry_result is False else "POSSIBLY_VISIBLE"
```

Add `hold_stability_ms`, `hold_max_speed`, `hold_max_displacement`,
`exposure_transition_window_ticks`, `action_ambiguity_margin`,
`csnet_contact_sample_ticks`, and `csnet_contact_query_budget` to `Config`.
`active_learning_score()` returns every specified component and a deterministic
`priority` in `[0, 1]`; `assist is None` contributes zero.

- [ ] **Step 4: Run targeted contracts and full legacy tests**

Run: `pytest tests/test_v134.py -k 'sight_state or action_prediction' -v; pytest -q`

Expected: all tests pass.

- [ ] **Step 5: Commit contract layer**

```bash
git add core/playerlab/contact_semantics.py core/playerlab/config.py tests/test_v134.py
git commit -m "feat: add contact semantics contracts"
```

## Task 2: Build pairwise exposure, contact windows, and action classification

**Files:**
- Modify: `core/playerlab/contact_semantics.py`
- Modify: `tests/test_v134.py`

**Interfaces:**
- Consumes Task 1 dataclasses/config and `GeometryProvider.can_see()`.
- Produces `build_contact_window()`, `exposure_relations()`, `classify_contact()` for Task 3.

- [ ] **Step 1: Write the eight failing semantic regression tests**

```python
def test_enemy_swing_after_700ms_stability_is_hold():
    prediction = classify_contact(window, relations_enemy_enters_after_stability(), idx, Config())
    assert (prediction.initiation, prediction.top_label, prediction.subtype) == ("ENEMY_INITIATED", "HOLD", "STATIC_HOLD")

def test_small_ad_without_exposure_growth_is_microadjust_hold():
    p = classify_contact(window, relations_small_ad(), idx, Config())
    assert p.top_label == "HOLD" and p.subtype == "MICROADJUST_HOLD"

def test_self_covered_to_visible_lateral_move_is_peek():
    p = classify_contact(window, relations_self_transition(), idx, Config())
    assert p.initiation == "SELF_INITIATED" and p.top_label == "PEEK"

def test_simultaneous_turn_is_encounter_not_active_peek():
    p = classify_contact(window, relations_mutual_transition(), idx, Config())
    assert p.initiation == "MUTUAL" and p.top_label != "PEEK"
```

Also add tests for re-peek state sequence, wall-following without transition,
non-damaging enemy-initiated contact, and close probabilities producing
`ambiguous=True`.

- [ ] **Step 2: Run the semantic tests and confirm failure**

Run: `pytest tests/test_v134.py -k 'enemy_swing or microadjust or covered_to_visible or simultaneous_turn or repeek or wall_following or non_damaging or ambiguous' -v`

Expected: FAIL because the classifier is not implemented.

- [ ] **Step 3: Implement bounded window and evidence-led classification**

```python
def classify_contact(window, relations, idx, cfg):
    hold = _hold_evidence(window, relations, idx, cfg)
    peek = _peek_evidence(window, relations, idx, cfg)
    initiation = _initiation(relations, idx, cfg)
    if initiation == "ENEMY_INITIATED" and hold.confidence >= peek.confidence:
        return _prediction("HOLD", initiation, hold, "MICROADJUST_HOLD" if hold.microadjust else "STATIC_HOLD", cfg)
    if initiation == "SELF_INITIATED" and peek.exposure_gain > 0:
        return _prediction("PEEK", initiation, peek, None, cfg)
    return _prediction("UNKNOWN", initiation, {"hold": hold, "peek": peek}, None, cfg)
```

Use first reciprocal `can_see=True` as visibility anchor when present, otherwise
first shot then first damage.  A `None` geometry result creates `UNKNOWN`, not
`EXPOSED`.  Re-peek requires an observed covered interval followed by a new
self-initiated transition and position/lane/context similarity.  Preserve every
measurement in evidence.

- [ ] **Step 4: Run semantic and complete suite**

Run: `pytest tests/test_v134.py -v; pytest -q`

Expected: all tests pass.

- [ ] **Step 5: Commit the classifier**

```bash
git add core/playerlab/contact_semantics.py tests/test_v134.py
git commit -m "feat: classify contact initiation and actions"
```

## Task 3: Replace decision anchor usage and gate engagement methods

**Files:**
- Modify: `core/playerlab/decision.py`
- Modify: `core/playerlab/engagement.py`
- Modify: `tests/test_v134.py`

**Interfaces:**
- Consumes `ActionPrediction` from Task 2 and `get_geometry()` from existing geometry module.
- Produces decision records with `action_prediction`, `contact_window`, and `contact_initiation` metadata.

- [ ] **Step 1: Add failing integration tests**

```python
def test_dry_peek_requires_a_real_peek():
    method = detect_engagement_method(demo, Config(), tc, known, "HOLD", {"contact_prediction": {"top_label": "HOLD"}})
    assert method["method"] == "HOLD"

def test_csnet_never_changes_classified_hold():
    assert classify_contact(window, relations, idx, Config()).top_label == "HOLD"

def test_let_cross_requires_enemy_entry_and_delayed_shot():
    assert detect_engagement_method(demo, Config(), tc, known, "HOLD", let_cross_duel)["method"] == "LET_CROSS"
```

- [ ] **Step 2: Run integration tests and confirm failure**

Run: `pytest tests/test_v134.py -k 'dry_peek or csnet_never or let_cross' -v`

Expected: FAIL because decision and engagement do not consume contact predictions.

- [ ] **Step 3: Integrate without reintroducing damage-first behavior**

Use damage events only to find candidate enemy pairs and enrich the window.
For every candidate pair, build windows and choose the highest-confidence
non-overlapping prediction.  Populate legacy `observed_action` from
`prediction.top_label`, retain `probabilities`, initiation, subtype, sight state,
and full evidence under `meta["contact"]`.  Do not pass model evidence to
`classify_contact`.  In `engagement.py`, allow all peek methods, especially
`DRY_PEEK`, only when base action is `PEEK`/`RE_PEEK`; require enemy entry,
self stability and shot delay for `LET_CROSS`.

- [ ] **Step 4: Run decision, engagement, and full regression suite**

Run: `pytest tests/test_v134.py -v; pytest -q`

Expected: all tests pass, including legacy engagement tests.

- [ ] **Step 5: Commit pipeline integration**

```bash
git add core/playerlab/decision.py core/playerlab/engagement.py tests/test_v134.py
git commit -m "feat: use contact semantics in decisions"
```

## Task 4: Persist contact samples and human calibration queue

**Files:**
- Modify: `core/playerlab/db.py`
- Modify: `core/playerlab/calibration.py`
- Modify: `core/playerlab/api.py`
- Modify: `tests/test_v134.py`

**Interfaces:**
- Consumes `ActionPrediction` and `active_learning_score()`.
- Produces `upsert_contact_action_sample`, `get_contact_action_samples`,
`submit_contact_action_annotation`, and `sample_contact_action_queue`.

- [ ] **Step 1: Add failing persistence/authority tests**

```python
def test_contact_candidates_are_pending_not_ground_truth():
    sample = make_contact_sample("HOLD")
    db.upsert_contact_action_sample(sample)
    assert db.get_contact_action_samples()[0]["label_source"] == "PENDING_HUMAN_REVIEW"

def test_model_evidence_cannot_change_calibration_state():
    db.upsert_contact_action_sample(make_contact_sample("PEEK", csnet={"duel_delta": .9}))
    assert contact_calibration_stats(db, Config())["calibration_state"] == "UNCALIBRATED"
```

- [ ] **Step 2: Run persistence tests and confirm failure**

Run: `pytest tests/test_v134.py -k 'contact_candidates or model_evidence_cannot' -v`

Expected: FAIL because the tables and methods do not exist.

- [ ] **Step 3: Add migration and queue behavior**

Create idempotent tables for `contact_action_samples`,
`contact_action_annotations`, and `csnet_assist_cache`.  Store JSON evidence,
predictions, and context alongside `match_id`, player/enemy, round, and window
ticks.  Validate only the nine approved contact labels.  Queue selection uses
the `priority` field, applies sample-deficit balancing, and creates at most the
available `30/30/15/15` candidates without fabricating data.  Calibration
statistics count only human annotations and return
`GROUND_TRUTH_PENDING_HUMAN_REVIEW` before real labels exist.  Add read/write
API handlers that expose only structured contact evidence and annotations.

- [ ] **Step 4: Run calibration tests and full suite**

Run: `pytest tests/test_v134.py -k 'contact_candidates or model_evidence_cannot or contact_queue' -v; pytest -q`

Expected: all tests pass.

- [ ] **Step 5: Commit persistence and queue**

```bash
git add core/playerlab/db.py core/playerlab/calibration.py core/playerlab/api.py tests/test_v134.py
git commit -m "feat: add contact action calibration queue"
```

## Task 5: Add optional CS-NET assist and bounded cache

**Files:**
- Create: `core/playerlab/csnet_assist.py`
- Modify: `core/playerlab/csnet.py`
- Modify: `core/playerlab/cli.py`
- Modify: `tests/test_v134.py`

**Interfaces:**
- Consumes existing CS-NET loader and Task 4 cache repositories.
- Produces `CSNetAssistProvider.collect(demo, window, ticks) -> dict | None` and cache statistics.

- [ ] **Step 1: Add failing availability, cache, and budget tests**

```python
def test_unavailable_csnet_returns_none_without_classifier_failure():
    assert CSNetAssistProvider(Config()).collect(demo, window, [100]) is None
    assert prediction.top_label == "HOLD"

def test_assist_cache_key_includes_demo_tick_model_and_head():
    key = assist_cache_key("abc", 100, "v1", "duel")
    assert key == "abc:100:v1:duel"
```

- [ ] **Step 2: Run assist tests and confirm failure**

Run: `pytest tests/test_v134.py -k 'unavailable_csnet or assist_cache' -v`

Expected: FAIL because the provider is absent.

- [ ] **Step 3: Implement assist-only provider**

`CSNetAssistProvider` wraps existing loader calls, requests no more than
`cfg.csnet_contact_query_budget` ticks from a window-selected subset, and caches
each supported head by `(demo_hash, tick, model_version, head)`.  It returns
only available values plus `model_version`, `head_versions`, `evidence_scope`,
and quality.  It never imports `decision.py` or `contact_semantics.classify_contact`.
Expose a CLI stats command reporting query count, cache hits, misses, and
unavailable heads.

- [ ] **Step 4: Run assist and full tests**

Run: `pytest tests/test_v134.py -k 'csnet or assist_cache' -v; pytest -q`

Expected: all tests pass with and without installed models.

- [ ] **Step 5: Commit CS-NET assistance**

```bash
git add core/playerlab/csnet_assist.py core/playerlab/csnet.py core/playerlab/cli.py tests/test_v134.py
git commit -m "feat: add bounded CS-NET assist evidence"
```

## Task 6: Add old/new comparison, contact statistics, API/UI presentation

**Files:**
- Modify: `core/playerlab/ab_experiment.py`
- Modify: `core/playerlab/cli.py`
- Modify: `core/playerlab/api.py`
- Modify: `ui/index.html`
- Modify: `tests/test_v134.py`

**Interfaces:**
- Consumes persisted samples from Task 4 and predictions from Task 3.
- Produces `contact_action_stats()`, `diff_contact_old_new()`, CLI `contact-action-stats`, and API payloads for UI.

- [ ] **Step 1: Add failing reporting and UI-payload tests**

```python
def test_old_new_mapping_counts_peek_to_hold():
    report = diff_contact_old_new([{"old": "PEEK", "new": "HOLD"}])
    assert report["transitions"]["PEEK_TO_HOLD"] == 1

def test_contact_stats_include_initiator_distribution():
    assert contact_action_stats(samples)["initiators"]["ENEMY_INITIATED"] == 1
```

- [ ] **Step 2: Run reporting tests and confirm failure**

Run: `pytest tests/test_v134.py -k 'old_new_mapping or contact_stats' -v`

Expected: FAIL because comparison/statistics functions are absent.

- [ ] **Step 3: Implement report payloads and minimal UI changes**

Run old and v1.3.4 classifiers over the same `SampleDemo`; align by player,
enemy, and overlapping window rather than count-only matching.  Emit counts,
transition matrix, initiator distribution, geometry status, and human metrics
only with real human labels.  Add API endpoints for statistics, comparison, and
the contact queue.  In the Decision Card render exactly: “WHO STARTED THE
CONTACT?”, “YOUR ACTION”, “HOW YOU HELD/PEEKED”; expand stable duration, both
exposure gains, geometry quality, and “Auxiliary model evidence.”  Do not build
a replay viewer.

- [ ] **Step 4: Run UI-payload, reporting, and full tests**

Run: `pytest tests/test_v134.py -k 'old_new_mapping or contact_stats' -v; pytest -q`

Expected: all tests pass.

- [ ] **Step 5: Commit reports and presentation**

```bash
git add core/playerlab/ab_experiment.py core/playerlab/cli.py core/playerlab/api.py ui/index.html tests/test_v134.py
git commit -m "feat: report contact action semantics"
```

## Task 7: Re-run SampleDemo, publish evidence reports, and verify delivery

**Files:**
- Create: `docs/V1_3_4_DELTA.md`
- Create: `docs/CONTACT_SEMANTICS.md`
- Create: `docs/CONTACT_CLASSIFIER_RESULTS.md`
- Create: `docs/CSNET_ASSIST_REPORT.md`
- Create: `docs/ACTION_OLD_NEW_COMPARISON.md`
- Modify: `tests/test_v134.py`

**Interfaces:**
- Consumes Task 6 statistics and the actual `SampleDemo` run.
- Produces reproducible, evidence-bounded delivery reports.

- [ ] **Step 1: Add an end-to-end smoke test**

```python
def test_contact_stats_report_pending_human_truth_without_annotations(tmp_path):
    report = run_contact_comparison(sample_demo_path, Config(db_path=str(tmp_path / "db.sqlite")))
    assert report["human_agreement_status"] == "GROUND_TRUTH_PENDING_HUMAN_REVIEW"
```

- [ ] **Step 2: Run the smoke test and confirm its initial failure**

Run: `pytest tests/test_v134.py -k 'pending_human_truth' -v`

Expected: FAIL until the real runner and report contract are connected.

- [ ] **Step 3: Run the baseline and write evidence-only documents**

Run the classifier and comparison on `SampleDemo` with Null geometry and, when
assets are present, Awpy geometry.  Record exact demo hash, config hash, git
commit, geometry mode, sample count, classifier transitions, cache hit/miss
counts, unavailable heads, and limitations.  If assets/models/labels are absent,
write the prescribed pending/unavailable status rather than invented accuracy or
effectiveness claims.  `CONTACT_SEMANTICS.md` explicitly states the four core
principles; the CS-NET report lists permitted and prohibited uses.

- [ ] **Step 4: Run final verification**

Run: `pytest -q`

Run: `python -m playerlab.cli contact-action-stats --demo SampleDemo`

Expected: tests pass; command emits actions, initiators, comparison values, and
honest pending-status fields.

- [ ] **Step 5: Commit reports and verified result**

```bash
git add docs/V1_3_4_DELTA.md docs/CONTACT_SEMANTICS.md docs/CONTACT_CLASSIFIER_RESULTS.md docs/CSNET_ASSIST_REPORT.md docs/ACTION_OLD_NEW_COMPARISON.md tests/test_v134.py
git commit -m "docs: publish V1.3.4 contact semantics results"
```

## Plan self-review

- Spec coverage: Tasks 1–3 implement exposure, visibility, initiation, HOLD/PEEK/RE_PEEK, encounter distinction, sighting, and action distributions; Tasks 4–5 implement human review, active learning, CS-NET boundaries, cache, and availability; Tasks 6–7 implement UI, statistics, A/B comparison, SampleDemo run, and all required reports.
- No scope extensions: the plan contains no model training, Pro reference, automatic labeling, online learning, replay viewer, or scoring work.
- Type consistency: Tasks 2–7 consume only the interfaces declared above; CS-NET returns a separate dictionary consumed only by scoring and presentation.
