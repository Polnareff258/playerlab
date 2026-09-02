# PlayerLab V1.3.4 — Contact Semantics Design

## Status and scope

This design replaces the damage-first, movement-to-enemy-anchor heuristic for
contact actions.  It applies to the existing `SampleDemo` baseline only.  It
stops after the V1.3.4 work listed here; it does not add Pro Reference data,
online learning, a Tiny Transformer, a total-score system, or a replay viewer.

The governing principles are:

- Movement is not peek.
- Visibility is not FOV; contact is not damage.
- Exposure is pairwise and precedes action labeling.
- HOLD is an observed action requiring positive evidence.
- CS-NET is auxiliary model evidence, never action or ground-truth authority.

## Architecture

Add a dedicated contact-semantics layer between tick/event measurements and the
existing decision/evaluation pipeline:

```
motion + tick state + geometry
  -> ExposureRelation sequence
  -> ContactWindow
  -> ContactInitiation
  -> ActionPrediction
  -> EngagementMethod and evaluation
```

The layer owns these serializable contracts:

- `ExposureState`: `COVERED`, `PARTIALLY_EXPOSED`, `EXPOSED`, `UNKNOWN`.
- `ExposureRelation`: self/enemy IDs and tick, reciprocal visibility, both
  exposure states, geometry metadata, and confidence.
- `ContactWindow`: pre-contact start, visibility tick, first shot tick, first
  damage tick, and resolution tick; every anchor other than the window start
  may be absent.
- `ContactInitiation`: `SELF_INITIATED`, `ENEMY_INITIATED`, `MUTUAL`,
  `STATIC_CONTACT`, `INFORMATION_CONTACT`, or `UNKNOWN`.
- `HoldEvidence` and `PeekEvidence`: compact, auditable measurements used by
  the classifier rather than a single historical velocity dot product.
- `ActionPrediction`: top label, normalized probabilities, confidence,
  ambiguity flag, initiation, evidence, and action subtype/method.

This layer has no evaluation or model-provider dependency.  Existing decision
records retain compatible summary fields, but store the complete prediction and
contact evidence in metadata/state for auditability.

## Semantics and graceful degradation

With geometry, visibility is `in_fov AND GeometryProvider.can_see`; transitions
in reciprocal pairwise exposure determine initiation.  Geometry is queried only
within candidate contact windows and its source, version, and quality are stored
with each relation.  Awpy remains optional.

Without geometry, the system must not claim LOS.  Exposure is `UNKNOWN` or
`PARTIALLY_EXPOSED` only when supported by explicitly approximate evidence;
initiation becomes `UNKNOWN_INITIATION` and action predictions use possible or
low-confidence alternatives.  `SightState` is `OUT_OF_FOV`,
`IN_FOV_OCCLUDED`, `VISIBLE`, `POSSIBLY_VISIBLE`, or `UNKNOWN`; FOV-only
evidence produces `POSSIBLE_SIGHTING`, never high-confidence true sighting.

`HOLD` uses a configurable 500–1000 ms stability window: displacement, mean
speed, yaw/lane variance, exposure gain, weapon readiness, and lack of outward
movement.  It wins over an older approach, so a player who stopped for 700 ms
before an enemy swing is `ENEMY_INITIATED + HOLD`.  Small AD without exposure
expansion is `MICROADJUST_HOLD`; static and actively maintained lanes are
`STATIC_HOLD` and `ACTIVE_HOLD`.

`PEEK` requires temporally close self movement, a self-caused exposure gain, and
`SELF_INITIATED` (or explicitly weak, downgraded self-initiation evidence).
`RE_PEEK` requires exposed -> covered/disengaged -> self-initiated exposed plus
lane, position, and enemy-context similarity.  `DRY_PEEK` is an EngagementMethod
only after a real peek.  `LET_CROSS` uses enemy entry, self stability, and a
delayed shot.  A close top-two probability margin produces `AMBIGUOUS` and an
automatic review candidate.

## CS-NET boundary and active learning

Create `CSNetAssistProvider`, reusing loading infrastructure but not the
`GameModelProvider` action path.  It yields `CSNetAssistEvidence` with supported
heads only (unavailable heads are `None`/`UNKNOWN`), model/head versions,
evidence scope and quality, before/after win and duel signals where available,
survival/next-event probabilities where available, and deltas.

It is called on sampled ticks within candidate ContactWindows only.  Results
cache by `(demo_hash, tick, model_version, head)`.  It may feed
`ActiveLearningScore`: rule uncertainty, geometry uncertainty, rule/geometry
disagreement, CS-NET temporal signal change, future model disagreement, detector
importance, context rarity, and sample deficit.  It may not enter
`ObservedAction`, `ContactInitiation`, `GroundTruthLabel`, `HumanConsensus`, or
`CalibrationState`; unavailable CS-NET is neutral and leaves classification
fully functional.

## Persistence, calibration, and UI

Persist contact samples, relation/prediction evidence, CS-NET assist evidence,
and cache entries with explicit schema versions.  `ContactActionSample` contains
the contact window, motion/exposure/visibility sequences, rule and geometry
predictions, optional assist evidence, human annotations, label source, and
context (map, weapon, range, role, commitment).  Generated candidates are
always `PENDING_HUMAN_REVIEW`, not ground truth.

The calibration workflow adds the question “What actually happened?” with:
`SELF_PEEK`, `HOLD_ENEMY_PEEKED`, `MUTUAL_PEEK`, `RE_PEEK`,
`MICROADJUST_HOLD`, `REPOSITION`, `NO_REAL_CONTACT`, `UNSURE`, and `OTHER`.
It displays pre-contact movement, stable duration, exposure transition,
visibility/shot/damage ticks, and geometry quality.  The initial `SampleDemo`
queue targets 30 likely HOLD, 30 likely PEEK, 15 likely RE_PEEK, and 15
ambiguous candidates, while honestly reporting shortages.

Decision cards display who initiated contact, the user action, and its subtype.
Expanded evidence shows stability duration, self/enemy exposure gain, geometry
quality, and CS-NET delta under the label “Auxiliary model evidence.”

## Verification and reports

Tests cover all eleven supplied regressions: stable hold, micro-adjust hold,
self peek, mutual peek, re-peek, movement without exposure gain, FOV-versus-LOS,
non-damaging enemy-initiated sighting, CS-NET non-authority, calibration
non-contamination, and CS-NET absence.  They also enforce probability output,
ambiguity routing, and cache/query-budget behavior.

Re-run `SampleDemo` under old and new classifiers, align comparable episodes,
and report old/new action counts and mappings such as old PEEK -> new HOLD and
old DRY_PEEK -> new HOLD.  Human-agreement metrics are emitted only when real
human annotations exist; otherwise reports state
`GROUND_TRUTH_PENDING_HUMAN_REVIEW`.

Implementation produces `docs/V1_3_4_DELTA.md`, `docs/CONTACT_SEMANTICS.md`,
`docs/CONTACT_CLASSIFIER_RESULTS.md`, `docs/CSNET_ASSIST_REPORT.md`, and
`docs/ACTION_OLD_NEW_COMPARISON.md`.

## Acceptance criteria

- A stopped, stable player facing an enemy swing is HOLD, not PEEK.
- Small AD while maintaining an angle is `MICROADJUST_HOLD`.
- Self-created cover-to-LOS movement is PEEK; only then may it be dry.
- FOV without LOS never claims true sighting.
- CS-NET changes sampling priority only, never labels/calibration authority.
- With CS-NET or geometry unavailable, the contact pipeline remains usable and
  reports its uncertainty honestly.
