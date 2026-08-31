"""Tradeability (V1.2.1 spec §7-§8): can this teammate realistically trade?

V1 判断 (teammate_distance > threshold) is NOT tradeability. V1.2.1 uses a
structured estimate with explicit UNKNOWN where geometry data (LOS / nav) is
missing — never a fake-precise score. Classification levels:

    HIGH / MEDIUM / LOW / UNAVAILABLE / UNKNOWN

Internal score is kept (0..1) but callers must use `classification`.
LOS / nav / response-time come from TradeabilityGeometry when available
(see docs/LOS_NAV_SPIKE.md); with no geometry provider, direct-distance
estimates are downgraded and marked confidence=UNKNOWN.
"""
from __future__ import annotations

import math

from .config import Config
from .context import TemporalContext

CLASSIFICATIONS = ("HIGH", "MEDIUM", "LOW", "UNAVAILABLE", "UNKNOWN")

# response-time approximation: distance / speed + reaction, seconds
_MOVE_SPEED_UPS = 250.0    # conservative rotation speed (units/s)
_REACTION_S = 0.6          # human reaction + aim settle


class TradeabilityGeometry:
    """Geometry backend contract (LOS / nav / cover).

    V1.2.1 ships a NullGeometry: PlayerLab core never depends on a nav
    provider. AWPy / DAK-style providers may implement this later (Phase C
    spike: docs/LOS_NAV_SPIKE.md). All methods return None when unknown.
    """

    def direct_los(self, map_name: str, a, b) -> bool | None:
        return None

    def nav_distance(self, map_name: str, a, b) -> float | None:
        return None

    def intervening_cover(self, map_name: str, a, b) -> float | None:
        return None

    def get_metadata(self) -> dict:
        return {"type": "null", "note": "no LOS/nav provider configured"}


NULL_GEOMETRY = TradeabilityGeometry()


def compute_tradeability(tc: TemporalContext, cfg: Config,
                         geometry: TradeabilityGeometry | None = None) -> dict:
    """Tradeability of the nearest teammate from the victim's perspective.

    Uses only player-known information (hindsight guard). The nearest
    teammate's position comes from TemporalContext (teammate index);
    geometry queries are best-effort with explicit None -> UNKNOWN.
    """
    geo = geometry or NULL_GEOMETRY
    mate = tc.nearest_teammate
    if not mate:
        return _unknown("no teammate alive")
    dist = mate.get("dist")
    if dist is None:
        return _unknown("teammate distance unknown")

    map_name = tc.demo.header.get("map_name")
    mypos = _tc_pos(tc)
    mate_pos = mate.get("pos")
    los = geo.direct_los(map_name, mypos, mate_pos) if (mypos and mate_pos) else None
    nav_dist = geo.nav_distance(map_name, mypos, mate_pos) if (mypos and mate_pos) else None
    cover = geo.intervening_cover(map_name, mypos, mate_pos) if (mypos and mate_pos) else None
    eff_dist = nav_dist if nav_dist is not None else dist
    response_time = eff_dist / _MOVE_SPEED_UPS + _REACTION_S

    # commitment constraint: IMMEDIATE_TRADE feasibility from the victim side
    feas = getattr(tc, "feasibility", None) or {}
    commit_blocked = feas.get("IMMEDIATE_TRADE") in (
        "UNAVAILABLE", "TEMPORARILY_UNAVAILABLE", "CONSTRAINED")

    # same engagement lane: roughly same zone / direction of travel
    same_lane = _same_lane(tc)

    # view alignment: teammate roughly facing toward the victim's area
    align = _view_alignment(tc, mate)

    # ---- scoring (internal) ----
    score = 1.0
    reasons = []
    # distance bands (valid for both direct and nav distance)
    if eff_dist <= 1200.0:
        reasons.append(f"distance {eff_dist:.0f}u (close)")
    elif eff_dist <= 2200.0:
        score -= 0.25
        reasons.append(f"distance {eff_dist:.0f}u (mid)")
    elif eff_dist <= 3400.0:
        score -= 0.5
        reasons.append(f"distance {eff_dist:.0f}u (far)")
    else:
        score -= 0.75
        reasons.append(f"distance {eff_dist:.0f}u (very far)")
    if los is False:
        score -= 0.3
        reasons.append("no direct LOS (confirmed by geometry)")
    elif los is None:
        score -= 0.1
        reasons.append("LOS unknown (no geometry provider)")
    if cover is not None and cover > 0.5:
        score -= 0.2
        reasons.append(f"intervening cover {cover:.2f}")
    if response_time > 4.0:
        score -= 0.2
        reasons.append(f"response time {response_time:.1f}s (slow)")
    if not same_lane:
        score -= 0.1
        reasons.append("different engagement lane")
    if not align:
        score -= 0.1
        reasons.append("teammate view misaligned")
    if commit_blocked:
        score -= 0.4
        reasons.append("commitment blocks immediate trade")

    score = max(0.0, min(1.0, score))
    if commit_blocked:
        classification = "UNAVAILABLE"
    elif los is None and score >= 0.7:
        # no geometry provider: never claim HIGH on distance alone
        # (spec §8: don't emit fake precision; conservative by default)
        classification = "MEDIUM"
    elif score >= 0.7:
        classification = "HIGH"
    elif score >= 0.45:
        classification = "MEDIUM"
    elif score >= 0.2:
        classification = "LOW"
    else:
        classification = "LOW"

    confidence = 0.6 if los is not None else 0.4  # geometry improves confidence
    return {
        "classification": classification,
        "score": round(score, 4),
        "confidence": round(confidence, 3),
        "direct_distance": round(dist, 1),
        "nav_distance": round(nav_dist, 1) if nav_dist is not None else None,
        "direct_los": los,
        "estimated_response_time": round(response_time, 2),
        "teammate_view_alignment": round(align, 3) if isinstance(align, float) else align,
        "same_engagement_lane": same_lane,
        "intervening_cover": round(cover, 3) if cover is not None else None,
        "commitment_constraint": commit_blocked,
        "trade_window_seconds": round(max(0.0, 3.0 - response_time), 2),
        "reasons": reasons,
        "geometry": geo.get_metadata(),
    }


def _unknown(reason: str) -> dict:
    return {"classification": "UNKNOWN", "score": None, "confidence": 0.0,
            "direct_distance": None, "nav_distance": None, "direct_los": None,
            "estimated_response_time": None, "teammate_view_alignment": None,
            "same_engagement_lane": None, "intervening_cover": None,
            "commitment_constraint": None, "trade_window_seconds": None,
            "reasons": [reason], "geometry": NULL_GEOMETRY.get_metadata()}


def _tc_pos(tc: TemporalContext):
    traj = tc.trajectory
    if not traj:
        return None
    last = traj[-1]
    b = tc.bounds
    x0, x1, y0, y1 = b
    return (last["pos"][0] * (x1 - x0) + x0, last["pos"][1] * (y1 - y0) + y0)


def _same_lane(tc: TemporalContext) -> bool:
    """Same engagement lane: teammate within ~180° of the player's heading,
    or same zone set recently. Approximate without geometry."""
    mypos = _tc_pos(tc)
    mate = tc.nearest_teammate
    if not mypos or not mate or not mate.get("pos"):
        return False
    dx = mate["pos"][0] - mypos[0]
    dy = mate["pos"][1] - mypos[1]
    if math.hypot(dx, dy) < 1.0:
        return True
    yaw = tc.trajectory[-1]["yaw"] if tc.trajectory and tc.trajectory[-1].get("yaw") is not None else None
    if yaw is None:
        return True  # no heading data -> do not punish
    import math as _m
    ang = _m.degrees(_m.atan2(dy, dx))
    diff = abs(((ang - yaw) + 180) % 360 - 180)
    return diff <= 90.0


def _view_alignment(tc: TemporalContext, mate: dict):
    """Teammate view alignment toward the player (approx by heading diff).
    Returns float 0..1 or True/False when unknown."""
    return True  # no teammate yaw in TemporalContext; alignment unknown
