"""Pairwise, visibility-aware contact semantics for PlayerLab V1.3.4.

This module deliberately has no dependency on CS-NET or evaluation.  It turns
measurements into an auditable action prediction; model evidence can only be
attached later for review prioritisation.
"""
from __future__ import annotations

from dataclasses import dataclass
import math

EXPOSURE_STATES = ("COVERED", "PARTIALLY_EXPOSED", "EXPOSED", "UNKNOWN")
CONTACT_INITIATIONS = ("SELF_INITIATED", "ENEMY_INITIATED", "MUTUAL",
                       "STATIC_CONTACT", "INFORMATION_CONTACT", "UNKNOWN")
OBSERVED_ACTIONS = ("PEEK", "HOLD", "RE_PEEK", "DISENGAGE", "REPOSITION",
                    "HIDE", "TRADE", "PLANT", "UNKNOWN")
SIGHT_STATES = ("OUT_OF_FOV", "IN_FOV_OCCLUDED", "VISIBLE",
                "POSSIBLY_VISIBLE", "UNKNOWN")


@dataclass(frozen=True)
class ExposureRelation:
    self_id: int
    enemy_id: int
    tick: int
    self_can_see_enemy: bool | None
    enemy_can_see_self: bool | None
    self_exposure_state: str
    enemy_exposure_state: str
    geometry_quality: str
    confidence: float


@dataclass(frozen=True)
class ContactWindow:
    pre_contact_start: int
    visibility_tick: int | None
    first_shot_tick: int | None
    first_damage_tick: int | None
    resolution_tick: int | None
    self_id: int
    enemy_id: int


@dataclass(frozen=True)
class HoldEvidence:
    stable_duration_ticks: int
    displacement: float
    mean_speed: float
    yaw_variance: float
    exposure_change: str
    lane_stability: float
    confidence: float
    microadjust: bool = False


@dataclass(frozen=True)
class PeekEvidence:
    pre_exposure_state: str
    post_exposure_state: str
    self_displacement: float
    lateral_displacement: float
    outward_component: float
    exposure_gain: float
    contact_delay_ticks: int | None
    initiator: str
    confidence: float


@dataclass(frozen=True)
class ActionPrediction:
    top_label: str
    probabilities: dict[str, float]
    confidence: float
    ambiguous: bool
    initiation: str
    evidence: dict[str, object]
    subtype: str | None


def build_contact_window(demo, self_id: int, enemy_id: int, idx: dict, cfg) -> list[ContactWindow]:
    """Build damage/shot candidates while allowing true visibility to lead later."""
    anchors = []
    for event in demo.events.get("damages", []):
        ids = {event.get("user_steamid"), event.get("attacker_steamid")}
        if {self_id, enemy_id} == ids:
            anchors.append((int(event["tick"]), "damage"))
    for event in demo.events.get("shots", []):
        if event.get("user_steamid") in (self_id, enemy_id):
            anchors.append((int(event["tick"]), "shot"))
    if not anchors:
        return []
    anchors.sort()
    out = []
    for tick, kind in anchors:
        if out and tick <= (out[-1].resolution_tick or tick) + cfg.episode_merge_ticks:
            continue
        out.append(ContactWindow(max(0, tick - cfg.exposure_transition_window_ticks), None,
                                 tick if kind == "shot" else None,
                                 tick if kind == "damage" else None,
                                 tick + 32, self_id, enemy_id))
    return out


def exposure_relations(window: ContactWindow, map_name: str, idx: dict, geometry, cfg) -> list[ExposureRelation]:
    """Create pairwise relations.  `None` LOS never masquerades as exposure."""
    quality = getattr(geometry, "quality", "none")
    out = []
    for tick in range(window.pre_contact_start, (window.resolution_tick or window.pre_contact_start) + 1):
        self_rec, enemy_rec = idx.get((window.self_id, tick)), idx.get((window.enemy_id, tick))
        if not self_rec or not enemy_rec or not self_rec.get("is_alive") or not enemy_rec.get("is_alive"):
            continue
        a, b = (self_rec.get("x"), self_rec.get("y")), (enemy_rec.get("x"), enemy_rec.get("y"))
        if None in a or None in b:
            los = None
        else:
            los = geometry.can_see(map_name, a, b)
        state = "EXPOSED" if los is True else "COVERED" if los is False else "UNKNOWN"
        out.append(ExposureRelation(window.self_id, window.enemy_id, tick, los, los,
                                    state, state, quality, 1.0 if los is not None else 0.0))
    return out


def sight_state(self_record: dict, enemy_record: dict, geometry_result: bool | None) -> str:
    """Visibility is FOV plus geometry; unknown geometry stays explicitly weak."""
    if self_record.get("in_fov") is False:
        return "OUT_OF_FOV"
    if not self_record.get("in_fov"):
        return "UNKNOWN"
    if geometry_result is True:
        return "VISIBLE"
    if geometry_result is False:
        return "IN_FOV_OCCLUDED"
    return "POSSIBLY_VISIBLE"


def _records_for(window: ContactWindow, idx: dict) -> list[tuple[int, dict]]:
    return [(t, idx[(window.self_id, t)]) for (sid, t) in sorted(idx)
            if sid == window.self_id and window.pre_contact_start <= t <= (window.resolution_tick or t)
            and (window.self_id, t) in idx]


def _transition(relations: list[ExposureRelation], field: str) -> int | None:
    previous = None
    for rel in relations:
        state = getattr(rel, field)
        if state == "EXPOSED" and previous in ("COVERED", "PARTIALLY_EXPOSED", "UNKNOWN"):
            return rel.tick
        previous = state
    return None


def _initiation(relations: list[ExposureRelation], idx: dict, cfg) -> str:
    self_t = _transition(relations, "self_exposure_state")
    enemy_t = _transition(relations, "enemy_exposure_state")
    if self_t is None and enemy_t is None:
        return "STATIC_CONTACT" if any(r.self_exposure_state == "EXPOSED" for r in relations) else "UNKNOWN"
    if self_t is not None and enemy_t is not None and abs(self_t - enemy_t) <= 2:
        return "MUTUAL"
    if self_t is not None and (enemy_t is None or self_t < enemy_t):
        return "SELF_INITIATED"
    return "ENEMY_INITIATED"


def _hold_evidence(window: ContactWindow, relations: list[ExposureRelation], idx: dict, cfg) -> HoldEvidence:
    anchor = window.visibility_tick or window.first_shot_tick or window.first_damage_tick or window.resolution_tick
    rows = [(t, r) for t, r in _records_for(window, idx) if t <= (anchor or t)]
    if not rows:
        return HoldEvidence(0, 0, 0, 0, "UNKNOWN", 0, 0)
    start = max(0, len(rows) - cfg.hold_stability_ticks)
    rows = rows[start:]
    points = [(r.get("x"), r.get("y")) for _, r in rows]
    valid = [p for p in points if None not in p]
    displacement = math.hypot(valid[-1][0] - valid[0][0], valid[-1][1] - valid[0][1]) if len(valid) > 1 else 0.0
    speeds = [float(r.get("speed") or 0.0) for _, r in rows]
    yaws = [float(r.get("yaw")) for _, r in rows if r.get("yaw") is not None]
    mean_speed = sum(speeds) / len(speeds) if speeds else 0.0
    yaw_variance = max(yaws) - min(yaws) if yaws else 0.0
    pre = relations[0].self_exposure_state if relations else "UNKNOWN"
    post = relations[-1].self_exposure_state if relations else "UNKNOWN"
    stable = len(rows) >= cfg.hold_stability_ticks and displacement <= cfg.hold_max_displacement and mean_speed <= cfg.v_hold
    micro = stable and displacement > 0.5
    confidence = min(1.0, (len(rows) / max(1, cfg.hold_stability_ticks)) * (1.0 if stable else .35))
    return HoldEvidence(len(rows), displacement, mean_speed, yaw_variance,
                        f"{pre}->{post}", max(0.0, 1.0 - yaw_variance / 180.0), confidence, micro)


def _peek_evidence(window: ContactWindow, relations: list[ExposureRelation], idx: dict, cfg, initiation: str) -> PeekEvidence:
    rows = _records_for(window, idx)
    pts = [(r.get("x"), r.get("y")) for _, r in rows if r.get("x") is not None and r.get("y") is not None]
    displacement = math.hypot(pts[-1][0] - pts[0][0], pts[-1][1] - pts[0][1]) if len(pts) > 1 else 0.0
    pre = relations[0].self_exposure_state if relations else "UNKNOWN"
    post = relations[-1].self_exposure_state if relations else "UNKNOWN"
    gain = 1.0 if pre != "EXPOSED" and post == "EXPOSED" else 0.0
    contact = window.visibility_tick or window.first_shot_tick or window.first_damage_tick
    delay = contact - rows[-1][0] if contact is not None and rows else None
    moving = any(float(r.get("speed") or 0) >= cfg.v_peek for _, r in rows)
    confidence = .85 if initiation == "SELF_INITIATED" and gain and moving else .0
    return PeekEvidence(pre, post, displacement, displacement, displacement, gain, delay,
                        initiation, confidence)


def _prediction(label: str, initiation: str, hold: HoldEvidence, peek: PeekEvidence, cfg) -> ActionPrediction:
    scores = {"HOLD": hold.confidence, "PEEK": peek.confidence, "REPOSITION": .05, "UNKNOWN": .05}
    if initiation == "MUTUAL":
        scores["PEEK"] = 0.0
        scores["UNKNOWN"] = max(scores["UNKNOWN"], .55)
    total = sum(scores.values()) or 1.0
    probs = {k: round(v / total, 6) for k, v in scores.items()}
    ranked = sorted(probs.items(), key=lambda x: x[1], reverse=True)
    top, confidence = ranked[0]
    ambiguous = len(ranked) > 1 and ranked[0][1] - ranked[1][1] <= cfg.action_ambiguity_margin
    if label == "HOLD":
        subtype = "MICROADJUST_HOLD" if hold.microadjust else "STATIC_HOLD"
    else:
        subtype = None
    return ActionPrediction(label if not ambiguous else top, probs, confidence, ambiguous, initiation,
                            {"hold": hold.__dict__, "peek": peek.__dict__}, subtype)


def classify_contact(window: ContactWindow, relations: list[ExposureRelation], idx: dict, cfg) -> ActionPrediction:
    """Classify only evidence; caller may attach CS-NET after this point."""
    initiation = _initiation(relations, idx, cfg)
    hold = _hold_evidence(window, relations, idx, cfg)
    peek = _peek_evidence(window, relations, idx, cfg, initiation)
    if initiation == "ENEMY_INITIATED" and hold.confidence >= peek.confidence:
        return _prediction("HOLD", initiation, hold, peek, cfg)
    if initiation == "SELF_INITIATED" and peek.exposure_gain and peek.confidence:
        return _prediction("PEEK", initiation, hold, peek, cfg)
    return _prediction("UNKNOWN", initiation, hold, peek, cfg)


def active_learning_score(prediction: ActionPrediction, geometry_quality: str,
                          assist: dict | None, context: dict, cfg) -> dict:
    ranked = sorted(prediction.probabilities.values(), reverse=True)
    return {"rule_uncertainty": round(1.0 - prediction.confidence, 3),
            "geometry_uncertainty": 0.0 if geometry_quality == "exact" else .5 if geometry_quality == "approximate" else 1.0,
            "rule_geometry_disagreement": float(prediction.ambiguous),
            "csnet_signal_change": abs(float((assist or {}).get("duel_delta") or 0.0)),
            "model_disagreement": 0.0, "detector_importance": float(context.get("importance", 0.0)),
            "context_rarity": float(context.get("rarity", 0.0)), "sample_deficit": float(context.get("sample_deficit", 0.0))}
