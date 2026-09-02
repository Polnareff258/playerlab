"""Pairwise, visibility-aware contact semantics for PlayerLab V1.3.4.1.

The V1.3.4.1 fix (docs/CONTACT_INITIATION_FIX.md) establishes the core rule:

    LOS transition != Contact initiator
    Movement       != Peek

Visibility becoming available is a *shared* event: the LOS query is symmetric
(geometry does not know view directions).  Both players' exposure states flip
on nearly the same tick, so comparing transition ticks can never separate

    "I held an angle and the enemy walked out"
from
    "I swung out while the enemy held".

What actually identifies the initiator is *whose motion caused the pairwise
visibility transition*.  InitiationMotionEvidence measures both players'
displacement / speed / outward motion / stability / yaw change inside a
pre-contact motion window (cfg.initiation_motion_window_ticks, 300-800 ms),
and ContactInitiation v2 is decided from those measurements — never from
self_transition_tick == enemy_transition_tick.

Final order (must not be reversed):

    What became visible?   -> visibility scan (geometry LOS transition)
    Who caused it?         -> motion-based initiation
    What action happened?  -> hold/peek/re-peek correctness
    What support/context?  -> support & stealth context (audited separately)
    How confident?         -> honest UNKNOWN / AMBIGUOUS
    Was it reasonable?     -> evaluation downstream

This module deliberately has no dependency on CS-NET or evaluation.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import math

EXPOSURE_STATES = ("COVERED", "PARTIALLY_EXPOSED", "EXPOSED", "UNKNOWN")
CONTACT_INITIATIONS = ("SELF_INITIATED", "ENEMY_INITIATED", "MUTUAL",
                       "STATIC_CONTACT", "INFORMATION_CONTACT", "UNKNOWN")
OBSERVED_ACTIONS = ("PEEK", "HOLD", "RE_PEEK", "DISENGAGE", "REPOSITION",
                    "HIDE", "TRADE", "PLANT", "UNKNOWN")
SIGHT_STATES = ("OUT_OF_FOV", "IN_FOV_OCCLUDED", "VISIBLE",
                "POSSIBLY_VISIBLE", "UNKNOWN")
HOLD_SUBTYPES = ("STATIC_HOLD", "MICROADJUST_HOLD", "ACTIVE_HOLD")
MOTION_STATES = ("STABLE", "MICRO_MOVING", "MOVING", "UNKNOWN")


@dataclass(frozen=True)
class ExposureRelation:
    """Pairwise engageability, NOT an attribution of who exposed whom.

    self_can_see_enemy / enemy_can_see_self come from the same symmetric LOS
    query when geometry has no view-direction model, so they are usually
    equal. They describe *pairwise engageability*, never 'who acted first'.
    """
    self_id: int
    enemy_id: int
    tick: int
    self_can_see_enemy: bool | None
    enemy_can_see_self: bool | None
    self_exposure_state: str
    enemy_exposure_state: str
    geometry_quality: str
    confidence: float
    pair_visible: bool | None = None          # symmetric engageability
    self_motion_state: str = "UNKNOWN"        # STABLE / MICRO_MOVING / MOVING
    enemy_motion_state: str = "UNKNOWN"
    self_velocity: tuple | None = None        # (vx, vy) for outward motion
    enemy_velocity: tuple | None = None


@dataclass(frozen=True)
class ContactWindow:
    pre_contact_start: int
    visibility_tick: int | None
    first_shot_tick: int | None
    first_damage_tick: int | None
    resolution_tick: int | None
    self_id: int
    enemy_id: int
    # V1.3.4.1: a visibility scan may also record a *possible* visibility
    # tick when geometry is unavailable (FOV only). It is never presented as
    # real visibility.
    possible_visibility_tick: int | None = None
    sight_state: str = "UNKNOWN"              # from PART I scan


@dataclass(frozen=True)
class InitiationMotionEvidence:
    """Motion measurements inside the pre-contact window (PART A §2)."""
    window_start: int
    transition_tick: int | None
    self_displacement: float = 0.0
    enemy_displacement: float = 0.0
    self_mean_speed: float = 0.0
    enemy_mean_speed: float = 0.0
    self_peak_speed: float = 0.0
    enemy_peak_speed: float = 0.0
    self_outward_motion: float = 0.0          # toward exposure boundary
    enemy_outward_motion: float = 0.0
    self_stability: float = 0.0               # 0..1 (position+yaw stability)
    enemy_stability: float = 0.0
    self_yaw_change: float = 0.0              # circular |deg|
    enemy_yaw_change: float = 0.0
    confidence: float = 0.0

    def summary(self) -> dict:
        return {k: (v if not isinstance(v, float) else round(v, 3))
                for k, v in self.__dict__.items()}


@dataclass(frozen=True)
class HoldEvidence:
    stable_duration_ticks: int
    displacement: float
    mean_speed: float
    yaw_variance: float                      # circular variance (degrees)
    exposure_change: str
    lane_stability: float
    confidence: float
    microadjust: bool = False
    active_hold: bool = False                # short reposition, lane kept


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
    motion_overlaps_transition: bool = False  # self motion overlaps LOS flip
    enemy_stable: bool = False                # enemy relatively stable


@dataclass(frozen=True)
class ActionPrediction:
    top_label: str
    probabilities: dict[str, float]
    confidence: float
    ambiguous: bool
    initiation: str
    evidence: dict[str, object]
    subtype: str | None
    motion_evidence: InitiationMotionEvidence | None = None
    ambiguous_labels: tuple = ()             # e.g. ("PEEK", "HOLD")
    why: str = ""                            # evidence-derived one-liner (PART N)

    def explanation(self) -> str:
        return self.why or "证据不足，暂不判断"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def circular_diff(a: float | None, b: float | None) -> float:
    """Smallest signed angular difference (degrees), wrapping at 180."""
    if a is None or b is None:
        return 0.0
    d = (b - a) % 360.0
    if d > 180.0:
        d -= 360.0
    return abs(d)


def yaw_variance_circular(yaws: list[float]) -> float:
    """Circular yaw spread. 179 -> -179 must be ~2deg, not 358deg."""
    if len(yaws) < 2:
        return 0.0
    rad = [math.radians(y) for y in yaws]
    sx = sum(math.sin(r) for r in rad) / len(rad)
    sy = sum(math.cos(r) for r in rad) / len(rad)
    r = math.hypot(sx, sy)
    # mean resultant length R in [0,1]; circular std approx sqrt(-2 ln R)
    if r >= 1.0:
        return 0.0
    return math.degrees(math.sqrt(-2.0 * math.log(max(r, 1e-9))))


def _speed(vx, vy):
    if vx is None or vy is None:
        return 0.0
    return math.hypot(float(vx), float(vy))


def _motion_state(speed: float, micro_max: float) -> str:
    if speed <= micro_max:
        return "STABLE"
    if speed <= micro_max * 2.5:
        return "MICRO_MOVING"
    return "MOVING"


def _records_in_window(window: ContactWindow, idx: dict, steamid: int) -> list[tuple[int, dict]]:
    """Records for one player inside the pre-contact window (bounded)."""
    end = window.visibility_tick or window.possible_visibility_tick \
        or window.first_shot_tick or window.first_damage_tick \
        or window.resolution_tick or window.pre_contact_start
    start = window.pre_contact_start
    out = []
    for tick in range(start, end + 1):
        rec = idx.get((steamid, tick))
        if rec is not None:
            out.append((tick, rec))
    return out


# ---------------------------------------------------------------------------
# PART C: real visibility_tick (geometry LOS transition)
# ---------------------------------------------------------------------------

def scan_visibility_transition(window: ContactWindow, relations: list[ExposureRelation],
                               sight_state_lookup: dict[int, str] | None = None) -> int | None:
    """First NOT_VISIBLE -> VISIBLE transition of the pairwise relation.

    Only a geometry-confirmed VISIBLE counts. Returns the tick or None.
    `relations` must be chronological and already carry pair_visible.
    """
    prev = None
    for rel in relations:
        vis = rel.pair_visible if rel.pair_visible is not None else rel.self_can_see_enemy
        if vis is True and prev is False:
            return rel.tick
        if vis is not None:
            prev = vis
    return None


def scan_possible_visibility(window: ContactWindow, relations: list[ExposureRelation],
                             fov_visible: dict[int, bool] | None = None) -> int | None:
    """FOV-only 'possible visibility' tick when geometry is unavailable.

    This must never be presented as real visibility (PART C §10).
    """
    if fov_visible is None:
        return None
    prev = None
    for rel in relations:
        vis = fov_visible.get(rel.tick)
        if vis is True and prev is False:
            return rel.tick
        if vis is not None:
            prev = vis
    return None


def fill_visibility_ticks(window: ContactWindow, relations: list[ExposureRelation],
                          geometry_quality: str,
                          fov_visible: dict[int, bool] | None = None) -> ContactWindow:
    """Return a new ContactWindow with visibility_tick populated from real
    geometry transitions (or possible_visibility_tick from FOV only)."""
    if geometry_quality != "none":
        vt = scan_visibility_transition(window, relations)
        return ContactWindow(window.pre_contact_start, vt,
                             window.first_shot_tick, window.first_damage_tick,
                             window.resolution_tick, window.self_id, window.enemy_id,
                             possible_visibility_tick=None,
                             sight_state="VISIBLE" if vt is not None else "UNKNOWN")
    pvt = scan_possible_visibility(window, relations, fov_visible)
    return ContactWindow(window.pre_contact_start, None,
                         window.first_shot_tick, window.first_damage_tick,
                         window.resolution_tick, window.self_id, window.enemy_id,
                         possible_visibility_tick=pvt,
                         sight_state="POSSIBLY_VISIBLE" if pvt is not None else "UNKNOWN")


# ---------------------------------------------------------------------------
# PART A: InitiationMotionEvidence + motion-based ContactInitiation v2
# ---------------------------------------------------------------------------

def motion_evidence(window: ContactWindow, relations: list[ExposureRelation],
                    idx: dict, cfg) -> InitiationMotionEvidence:
    """Measure both players inside the pre-contact motion window.

    The window is the tail of the pre-contact span (up to
    cfg.initiation_motion_window_ticks before the anchor tick). Bounded
    per-player tick scans only — never the full demo index (PART T §50).
    """
    anchor = window.visibility_tick or window.possible_visibility_tick \
        or window.first_shot_tick or window.first_damage_tick \
        or window.resolution_tick or window.pre_contact_start
    win_start = max(window.pre_contact_start, anchor - cfg.initiation_motion_window_ticks)
    win_end = anchor

    def measure(steamid: int):
        rows = [idx[(steamid, t)] for t in range(win_start, win_end + 1)
                if (steamid, t) in idx]
        if not rows:
            return dict(disp=0.0, mean=0.0, peak=0.0, out=0.0,
                        stable=1.0, yaw=0.0)
        valid = [(r.get("x"), r.get("y")) for r in rows
                 if r.get("x") is not None and r.get("y") is not None]
        disp = math.hypot(valid[-1][0] - valid[0][0],
                          valid[-1][1] - valid[0][1]) if len(valid) > 1 else 0.0
        speeds = []
        for r in rows:
            s = _speed(r.get("vx"), r.get("vy"))
            speeds.append(s if s > 0 else float(r.get("speed") or 0.0))
        mean = sum(speeds) / len(speeds) if speeds else 0.0
        peak = max(speeds) if speeds else 0.0
        yaws = [float(r["yaw"]) for r in rows if r.get("yaw") is not None]
        yaw_ch = circular_diff(yaws[0], yaws[-1]) if len(yaws) > 1 else 0.0
        # outward motion: last velocity along the window displacement vector
        out = 0.0
        if len(valid) > 1:
            dx, dy = valid[-1][0] - valid[0][0], valid[-1][1] - valid[0][1]
            n = math.hypot(dx, dy)
            if n > 1.0:
                vx = float(rows[-1].get("vx") or 0.0)
                vy = float(rows[-1].get("vy") or 0.0)
                if vx or vy:
                    out = (vx * dx + vy * dy) / n
        # stability: position low motion + yaw low circular spread
        yaw_var = yaw_variance_circular(yaws) if yaws else 0.0
        pos_ok = disp <= cfg.hold_max_displacement
        yaw_ok = yaw_var <= cfg.hold_max_yaw_variance
        stable = (1.0 if (pos_ok and yaw_ok) else
                  0.5 if (pos_ok or yaw_ok) else 0.0)
        return dict(disp=disp, mean=mean, peak=peak, out=out,
                    stable=stable, yaw=yaw_ch)

    self_m = measure(window.self_id)
    enemy_m = measure(window.enemy_id)

    # confidence: how clean is the motion contrast? both known -> higher
    conf = min(1.0, 0.5 + abs(self_m["mean"] - enemy_m["mean"]) /
               max(1.0, self_m["mean"] + enemy_m["mean"] + 1.0))
    return InitiationMotionEvidence(win_start, anchor,
                                    self_m["disp"], enemy_m["disp"],
                                    self_m["mean"], enemy_m["mean"],
                                    self_m["peak"], enemy_m["peak"],
                                    self_m["out"], enemy_m["out"],
                                    self_m["stable"], enemy_m["stable"],
                                    self_m["yaw"], enemy_m["yaw"], conf)


def classify_initiation_v2(ev: InitiationMotionEvidence, relations: list[ExposureRelation],
                           cfg) -> str:
    """ContactInitiation v2 — motion-based, never transition-tick equality.

    Order: both stable -> STATIC_CONTACT; one clearly drives exposure ->
    SELF/ENEMY_INITIATED; both move meaningfully -> MUTUAL; else UNKNOWN.
    """
    self_meaningful = (ev.self_mean_speed >= cfg.initiation_min_speed or
                       ev.self_displacement >= cfg.initiation_min_displacement)
    enemy_meaningful = (ev.enemy_mean_speed >= cfg.initiation_min_speed or
                        ev.enemy_displacement >= cfg.initiation_min_displacement)
    self_moving = (ev.self_mean_speed >= cfg.initiation_min_speed or
                   ev.self_peak_speed >= cfg.initiation_min_speed * 1.5)
    enemy_moving = (ev.enemy_mean_speed >= cfg.initiation_min_speed or
                    ev.enemy_peak_speed >= cfg.initiation_min_speed * 1.5)

    # both (mostly) static -> STATIC_CONTACT (smoke fade / geometry change)
    if (ev.self_mean_speed <= cfg.static_motion_max and
            ev.enemy_mean_speed <= cfg.static_motion_max):
        return "STATIC_CONTACT"

    # mutual: both sides move meaningfully and neither is clearly dominant
    max_mean = max(ev.self_mean_speed, ev.enemy_mean_speed, 1.0)
    ratio = min(ev.self_mean_speed, ev.enemy_mean_speed) / max_mean
    if (self_meaningful and enemy_meaningful and
            ratio >= cfg.mutual_motion_ratio):
        return "MUTUAL"

    # one side dominates motion
    if self_meaningful and not enemy_meaningful:
        # stable self + enemy moving -> ENEMY_INITIATED; moving self + stable
        # enemy -> SELF_INITIATED
        if self_moving and not enemy_moving:
            return "SELF_INITIATED"
        return "UNKNOWN" if not enemy_moving else "ENEMY_INITIATED"
    if enemy_meaningful and not self_meaningful:
        if enemy_moving and not self_moving:
            return "ENEMY_INITIATED"
        return "UNKNOWN" if not self_moving else "SELF_INITIATED"

    # both moving but ratio below mutual threshold -> dominant side
    if ev.self_mean_speed > ev.enemy_mean_speed:
        return "SELF_INITIATED"
    return "ENEMY_INITIATED"


# ---------------------------------------------------------------------------
# window construction (anchors from damage/shots; visibility leads later)
# ---------------------------------------------------------------------------

def build_contact_window(demo, self_id: int, enemy_id: int, idx: dict,
                         cfg) -> list[ContactWindow]:
    """Build damage/shot candidates; a real visibility scan (PART C) fills
    visibility_tick afterwards. Each window covers the pre-contact span."""
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
        lead = cfg.contact_timeline_lead_ticks
        out.append(ContactWindow(max(0, tick - lead), None,
                                 tick if kind == "shot" else None,
                                 tick if kind == "damage" else None,
                                 tick + 32, self_id, enemy_id))
    return out


# ---------------------------------------------------------------------------
# exposure relations (geometry LOS, symmetric engageability)
# ---------------------------------------------------------------------------

def exposure_relations(window: ContactWindow, map_name: str, idx: dict,
                       geometry, cfg) -> list[ExposureRelation]:
    """Pairwise relations. Symmetric LOS (geometry) is engageability, and the
    per-tick motion state is measured independently so initiation v2 can use
    real motion rather than exposure flips (PART A/B)."""
    quality = getattr(geometry, "quality", "none")
    out = []
    end = window.resolution_tick or window.pre_contact_start
    for tick in range(window.pre_contact_start, end + 1):
        self_rec, enemy_rec = idx.get((window.self_id, tick)), idx.get((window.enemy_id, tick))
        if not self_rec or not enemy_rec:
            continue
        if not self_rec.get("is_alive") or not enemy_rec.get("is_alive"):
            continue
        a, b = (self_rec.get("x"), self_rec.get("y")), (enemy_rec.get("x"), enemy_rec.get("y"))
        if None in a or None in b:
            los = None
        else:
            los = geometry.can_see(map_name, a, b)
        state = ("EXPOSED" if los is True else "COVERED"
                 if los is False else "UNKNOWN")
        s_speed = _speed(self_rec.get("vx"), self_rec.get("vy")) or float(self_rec.get("speed") or 0)
        e_speed = _speed(enemy_rec.get("vx"), enemy_rec.get("vy")) or float(enemy_rec.get("speed") or 0)
        micro = cfg.v_hold
        self_mot = _motion_state(s_speed, micro)
        enemy_mot = _motion_state(e_speed, micro)
        out.append(ExposureRelation(
            window.self_id, window.enemy_id, tick,
            los, los, state, state, quality,
            1.0 if los is not None else 0.0,
            pair_visible=los,
            self_motion_state=self_mot, enemy_motion_state=enemy_mot,
            self_velocity=(self_rec.get("vx"), self_rec.get("vy")),
            enemy_velocity=(enemy_rec.get("vx"), enemy_rec.get("vy"))))
    return out


def sight_state_from_relation(self_record: dict, enemy_record: dict,
                              geometry_result: bool | None, in_fov: bool | None = None) -> str:
    """SightState (PART I §29): FOV gate first, geometry confirms VISIBLE.

    - out of FOV          -> OUT_OF_FOV
    - FOV yes + geom True -> VISIBLE
    - FOV yes + geom False-> IN_FOV_OCCLUDED
    - FOV yes + geom None -> POSSIBLY_VISIBLE
    - FOV unknown         -> UNKNOWN
    """
    fov = in_fov if in_fov is not None else self_record.get("in_fov")
    if fov is False:
        return "OUT_OF_FOV"
    if not fov:
        return "UNKNOWN"
    if geometry_result is True:
        return "VISIBLE"
    if geometry_result is False:
        return "IN_FOV_OCCLUDED"
    return "POSSIBLY_VISIBLE"


def build_fov_lookup(window: ContactWindow, idx: dict, cfg,
                     yaw_offset: float) -> dict[int, bool]:
    """FOV-only 'enemy in my cone' per tick inside the window (no geometry).

    Used ONLY for possible_visibility_tick when geometry is unavailable.
    Requires a calibrated yaw offset (decision layer passes it in).
    """
    out = {}
    end = window.resolution_tick or window.pre_contact_start
    from .state import facing_yaw, dist2d, wrap180, angle_diff
    import math as _m
    for tick in range(window.pre_contact_start, end + 1):
        srec = idx.get((window.self_id, tick))
        erec = idx.get((window.enemy_id, tick))
        if not srec or not erec:
            continue
        f = facing_yaw(srec, yaw_offset)
        fx, fy = srec.get("x"), srec.get("y")
        tx, ty = erec.get("x"), erec.get("y")
        if f is None or None in (fx, fy, tx, ty):
            out[tick] = False
            continue
        d = dist2d(fx, fy, tx, ty)
        if d > cfg.vision_max_dist:
            out[tick] = False
            continue
        ang = wrap180(_m.degrees(_m.atan2(ty - fy, tx - fx)))
        out[tick] = angle_diff(f, ang) <= cfg.vision_fov_deg / 2.0
    return out


def sight_state(self_record: dict, enemy_record: dict, geometry_result: bool | None) -> str:
    """Backward-compatible wrapper (kept for the existing test surface)."""
    return sight_state_from_relation(self_record, enemy_record, geometry_result)


# ---------------------------------------------------------------------------
# PART D: HoldStability v2
# ---------------------------------------------------------------------------

def _hold_evidence_v2(window: ContactWindow, relations: list[ExposureRelation],
                      idx: dict, cfg) -> HoldEvidence:
    """HOLD evidence v2: position + circular yaw variance + lane stability.

    MICROADJUST_HOLD: small AD / small displacement / small yaw corrections
    with no meaningful exposure expansion. ACTIVE_HOLD: short reposition
    while still maintaining the lane. Both must never be read as PEEK.
    """
    anchor = window.visibility_tick or window.first_shot_tick \
        or window.first_damage_tick or window.resolution_tick
    rows = _records_in_window(window, idx, window.self_id)
    rows = [(t, r) for t, r in rows if t <= (anchor or t)]
    if not rows:
        return HoldEvidence(0, 0, 0, 0, "UNKNOWN", 0, 0)
    rows = rows[-cfg.hold_stability_ticks:]
    pts = [(r.get("x"), r.get("y")) for _, r in rows if r.get("x") is not None and r.get("y") is not None]
    displacement = math.hypot(pts[-1][0] - pts[0][0],
                              pts[-1][1] - pts[0][1]) if len(pts) > 1 else 0.0
    speeds = [float(r.get("speed") or 0.0) for _, r in rows]
    yaws = [float(r["yaw"]) for _, r in rows if r.get("yaw") is not None]
    mean_speed = sum(speeds) / len(speeds) if speeds else 0.0
    yaw_var = yaw_variance_circular(yaws) if yaws else 0.0

    # lane stability: heading/yaw stays around one lane (low circular spread
    # after removing the mean); position jitter is already in displacement.
    lane_stability = max(0.0, 1.0 - yaw_var / 90.0)

    pre = relations[0].self_exposure_state if relations else "UNKNOWN"
    post = relations[-1].self_exposure_state if relations else "UNKNOWN"
    dur_ok = len(rows) >= cfg.hold_stability_ticks
    disp_ok = displacement <= cfg.hold_max_displacement
    yaw_ok = yaw_var <= cfg.hold_max_yaw_variance
    stable = dur_ok and disp_ok and yaw_ok
    # micro-adjust: position stable-ish + yaw stable + small AD motion
    micro = (disp_ok and yaw_ok and mean_speed <= cfg.v_hold * 1.5
             and displacement > 0.5)
    # active hold: a short reposition (< 2x hold window) with lane kept and
    # no exposure *loss* — the player re-settles on the same angle
    active = (displacement > cfg.hold_max_displacement
              and displacement <= cfg.hold_max_displacement * 2.5
              and yaw_ok and lane_stability >= 0.75)
    conf = min(1.0, (len(rows) / max(1, cfg.hold_stability_ticks))
               * (1.0 if stable else 0.3 if micro else 0.1))
    # a player who is actively moving is not holding an angle: suppress HOLD
    # confidence in proportion to how much of the window was spent moving
    if mean_speed > cfg.v_hold:
        speed_factor = max(0.0, 1.0 - mean_speed / (cfg.v_peek * 2.0))
        conf *= speed_factor
    return HoldEvidence(len(rows), displacement, mean_speed, yaw_var,
                        f"{pre}->{post}", lane_stability, conf,
                        microadjust=micro and not active, active_hold=active)


# ---------------------------------------------------------------------------
# PART E/F: Peek v2 + Re-Peek v2
# ---------------------------------------------------------------------------

def _peek_evidence_v2(window: ContactWindow, relations: list[ExposureRelation],
                      idx: dict, cfg, initiation: str,
                      motion: InitiationMotionEvidence) -> PeekEvidence:
    """PEEK evidence requires SELF_INITIATED (or high-confidence self
    initiation) + LOS transition + self motion overlapping the transition +
    enemy relatively stable (PART E §16-§18)."""
    rows = _records_in_window(window, idx, window.self_id)
    pts = [(r.get("x"), r.get("y")) for _, r in rows
           if r.get("x") is not None and r.get("y") is not None]
    displacement = math.hypot(pts[-1][0] - pts[0][0],
                              pts[-1][1] - pts[0][1]) if len(pts) > 1 else 0.0
    pre = relations[0].self_exposure_state if relations else "UNKNOWN"
    post = relations[-1].self_exposure_state if relations else "UNKNOWN"
    gain = 1.0 if pre != "EXPOSED" and post == "EXPOSED" else 0.0
    contact = window.visibility_tick or window.first_shot_tick or window.first_damage_tick
    delay = contact - rows[-1][0] if contact is not None and rows else None
    # self motion overlaps the LOS transition?
    vt = window.visibility_tick
    motion_overlap = False
    if vt is not None and rows:
        motion_overlap = any(abs(t - vt) <= cfg.initiation_motion_window_ticks // 2
                             and float(r.get("speed") or 0) >= cfg.v_peek
                             for t, r in rows)
    elif vt is None:
        # no real visibility: motion overlap is unknown, not false
        motion_overlap = None
    enemy_stable = motion.enemy_mean_speed <= cfg.initiation_min_speed
    self_init = initiation == "SELF_INITIATED"
    moving = motion.self_mean_speed >= cfg.initiation_min_speed or \
        motion.self_peak_speed >= cfg.v_peek
    ok = self_init and gain and moving and enemy_stable
    if ok is False and motion_overlap is True:
        ok = ok  # overlap cannot rescue a non-self-initiated peek
    confidence = 0.0
    if ok:
        confidence = min(1.0, 0.55 + 0.25 * gain + (0.2 if motion_overlap else 0.0))
    return PeekEvidence(pre, post, displacement, displacement,
                        motion.self_outward_motion, gain, delay,
                        initiation, confidence,
                        motion_overlaps_transition=bool(motion_overlap),
                        enemy_stable=enemy_stable)


def _re_peek_evidence(window: ContactWindow, relations: list[ExposureRelation],
                      idx: dict, cfg, motion: InitiationMotionEvidence,
                      prev_cover_tick: int | None = None) -> tuple[bool, float]:
    """Re-peek: EXPOSED -> COVERED -> SELF_INITIATED exposure again, on a
    similar angle/position (PART F §19)."""
    # exposure timeline
    states = [(r.tick, r.self_exposure_state) for r in relations]
    exposed_runs = []
    covered = True
    for t, s in states:
        if s == "EXPOSED":
            if covered:
                exposed_runs.append(t)
                covered = False
        elif s in ("COVERED", "PARTIALLY_EXPOSED"):
            covered = True
    if len(exposed_runs) < 2:
        return False, 0.0
    # second exposure run must be SELF_INITIATED
    if motion.self_mean_speed < cfg.initiation_min_speed:
        return False, 0.0
    # same-angle similarity: yaw of first vs second exposure
    anchor1 = exposed_runs[0]
    anchor2 = exposed_runs[-1]
    yaws = {}
    for t, r in _records_in_window(window, idx, window.self_id):
        if r.get("yaw") is not None:
            yaws.setdefault(t, float(r["yaw"]))
    y1 = min(yaws.items(), key=lambda kv: abs(kv[0] - anchor1))[1] if yaws else None
    y2 = min(yaws.items(), key=lambda kv: abs(kv[0] - anchor2))[1] if yaws else None
    similar = y1 is not None and y2 is not None and circular_diff(y1, y2) <= cfg.re_peek_same_angle_deg
    return similar, (0.8 if similar else 0.3)


# ---------------------------------------------------------------------------
# classifier
# ---------------------------------------------------------------------------

def _prediction(label: str, initiation: str, hold: HoldEvidence,
                peek: PeekEvidence, cfg, motion: InitiationMotionEvidence,
                why: str = "", ambiguous_labels: tuple = ()) -> ActionPrediction:
    scores = {"HOLD": hold.confidence, "PEEK": peek.confidence,
              "REPOSITION": 0.05, "UNKNOWN": 0.05}
    if initiation == "MUTUAL":
        scores["PEEK"] = 0.0
        scores["UNKNOWN"] = max(scores["UNKNOWN"], 0.55)
    total = sum(scores.values()) or 1.0
    probs = {k: round(v / total, 6) for k, v in scores.items()}
    ranked = sorted(probs.items(), key=lambda x: x[1], reverse=True)
    top, confidence = ranked[0]
    ambiguous = (len(ranked) > 1 and
                 ranked[0][1] - ranked[1][1] <= cfg.action_ambiguity_margin)
    amb_labels = ()
    if ambiguous:
        amb_labels = (ranked[0][0], ranked[1][0])
    if label == "HOLD":
        subtype = ("MICROADJUST_HOLD" if hold.microadjust else
                   "ACTIVE_HOLD" if hold.active_hold else "STATIC_HOLD")
    elif label == "RE_PEEK":
        subtype = "SAME_ANGLE_RE_PEEK"
    else:
        subtype = None
    return ActionPrediction(label if not ambiguous else top, probs, confidence,
                            ambiguous, initiation,
                            {"hold": hold.__dict__, "peek": peek.__dict__,
                             "motion": motion.summary()},
                            subtype, motion_evidence=motion,
                            ambiguous_labels=amb_labels, why=why)


def classify_contact(window: ContactWindow, relations: list[ExposureRelation],
                     idx: dict, cfg,
                     prev_cover_tick: int | None = None) -> ActionPrediction:
    """Classify evidence only; caller may attach CS-NET after this point.

    Order: what became visible -> who caused it -> what action -> confidence.
    LOS transition alone never decides initiation (PART A).
    """
    motion = motion_evidence(window, relations, idx, cfg)
    initiation = classify_initiation_v2(motion, relations, cfg)
    hold = _hold_evidence_v2(window, relations, idx, cfg)
    peek = _peek_evidence_v2(window, relations, idx, cfg, initiation, motion)

    # re-peek requires a previous covered->exposed cycle + SELF_INITIATED
    is_re_peek, re_conf = _re_peek_evidence(window, relations, idx, cfg, motion,
                                            prev_cover_tick)
    if is_re_peek and initiation == "SELF_INITIATED":
        why = (f"判为主动 Re-peek：你在同一角度再次建立接敌"
               f"（{motion.self_displacement:.0f}u 位移，对手静止）")
        return _prediction("RE_PEEK", initiation, hold, peek, cfg, motion, why)

    # ENEMY swings, self holds -> HOLD
    if initiation == "ENEMY_INITIATED":
        why = (f"判为架枪：接敌前 {motion.self_displacement:.0f}u 位移 / "
               f"均速 {motion.self_mean_speed:.0f}，"
               f"敌方发生主要位移（{motion.enemy_displacement:.0f}u / "
               f"均速 {motion.enemy_mean_speed:.0f}）")
        return _prediction("HOLD", initiation, hold, peek, cfg, motion, why)

    # SELF swings out, enemy holds -> PEEK (only with real evidence)
    if initiation == "SELF_INITIATED":
        if peek.exposure_gain and peek.confidence > 0.0:
            why = (f"判为主动 Peek：你在 LOS 建立前发生 "
                   f"{motion.self_displacement:.0f}u 位移（均速 "
                   f"{motion.self_mean_speed:.0f}），对手基本保持静止")
            return _prediction("PEEK", initiation, hold, peek, cfg, motion, why)
        # self moved but no exposure gain / weak evidence -> ambiguous
        why = "更像主动拉出，但证据不足（LOS 转换未确认或对手非静止）"
        return _prediction("UNKNOWN", initiation, hold, peek, cfg, motion, why,
                           ambiguous_labels=("PEEK", "HOLD"))

    # MUTUAL / STATIC / UNKNOWN
    if initiation == "MUTUAL":
        why = "双方同时移动接敌（MUTUAL），无法可靠归因主动方"
    elif initiation == "STATIC_CONTACT":
        why = "双方基本静止（烟雾/掩体/几何转换），非主动暴露"
    else:
        why = "证据不足，暂不判断"
    return _prediction("UNKNOWN", initiation, hold, peek, cfg, motion, why)


# ---------------------------------------------------------------------------
# active learning score (unchanged surface)
# ---------------------------------------------------------------------------

def active_learning_score(prediction: ActionPrediction, geometry_quality: str,
                          assist: dict | None, context: dict, cfg) -> dict:
    ranked = sorted(prediction.probabilities.values(), reverse=True)
    return {"rule_uncertainty": round(1.0 - prediction.confidence, 3),
            "geometry_uncertainty": 0.0 if geometry_quality == "exact" else .5 if geometry_quality == "approximate" else 1.0,
            "rule_geometry_disagreement": float(prediction.ambiguous),
            "csnet_signal_change": abs(float((assist or {}).get("duel_delta") or 0.0)),
            "model_disagreement": 0.0, "detector_importance": float(context.get("importance", 0.0)),
            "context_rarity": float(context.get("rarity", 0.0)), "sample_deficit": float(context.get("sample_deficit", 0.0))}
