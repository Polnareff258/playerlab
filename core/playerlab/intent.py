"""CommitmentState / SituationalRole / IntentState rule baseline (V1.2).

- Commitment (spec §4-§5): inferred states, NOT raw events; UNKNOWN allowed.
- SituationalRole (spec §9-§11): dynamic, with a confidence distribution.
- Intent rule baseline (spec §12-§17): deterministic scoring over
  TemporalContext; ROTATE vs SOFT_ROTATE vs REPOSITION is the key question.
  Outputs a probability-like distribution + AMBIGUOUS when top-2 are close.
"""
from __future__ import annotations

from .config import Config
from .ingest import IngestedDemo
from .context import TemporalContext, norm_pos, map_bounds
from .state import pos_at, build_tick_index

COMMITMENTS = ("FREE", "PLANT_INTENT", "PLANT_COMMITTED", "DEFUSE_INTENT",
               "DEFUSE_COMMITTED", "RELOAD_COMMITTED", "UTILITY_COMMITTED",
               "ENGAGEMENT_COMMITTED", "DISENGAGE_COMMITTED", "SAVE_COMMITTED", "UNKNOWN")

ROLES = ("BOMB_CARRIER", "BOMB_PLANTER", "PLANT_COVER", "DEFUSER", "DEFUSE_COVER",
         "ENTRY", "SECOND_CONTACT", "TRADE_SUPPORT", "ANCHOR", "ROTATOR",
         "INFO_GATHERER", "FLANK_WATCH", "POST_PLANT_HOLD", "SAVE", "FREE_ROLE", "UNKNOWN")

INTENTS = ("HOLD", "CONTEST", "REPOSITION", "ROTATE", "SOFT_ROTATE", "EXECUTE",
           "PLANT", "DEFUSE", "SUPPORT", "TRADE", "GATHER_INFO", "DISENGAGE",
           "SAVE", "UNKNOWN")


# ---------------------------------------------------------------- commitment
def detect_commitment(demo: IngestedDemo, cfg: Config, steamid: int, tick: int) -> str:
    if any(abs(e["tick"] - tick) <= cfg.commit_plant_window_ticks
           and e.get("user_steamid") == steamid for e in demo.events["plants_start"]):
        return "PLANT_COMMITTED"
    if any(abs(e["tick"] - tick) <= cfg.commit_plant_window_ticks
           and e.get("user_steamid") == steamid for e in demo.events["defuses_start"]):
        return "DEFUSE_COMMITTED"
    if any(abs(e["tick"] - tick) <= cfg.commit_reload_window_ticks
           and e.get("user_steamid") == steamid for e in demo.events["reloads"]):
        return "RELOAD_COMMITTED"
    for g in demo.events["grenades"].values():
        if any(abs(gg["tick"] - tick) <= cfg.commit_utility_window_ticks
               and gg.get("user_steamid") == steamid for gg in g):
            return "UTILITY_COMMITTED"
    for d in demo.events["damages"]:
        if abs(d["tick"] - tick) <= cfg.commit_engagement_idle_ticks and \
                (d["user_steamid"] == steamid or d["attacker_steamid"] == steamid):
            return "ENGAGEMENT_COMMITTED"
    return "FREE"


def _bomb_carrier(demo: IngestedDemo, tick: int) -> int | None:
    plants = demo.events["bombs"]["planted"]
    if plants and plants[0]["tick"] <= tick:
        return None  # planted already -> no carrier
    for b in demo.events["plants_start"]:
        if b["tick"] <= tick:
            return b.get("user_steamid")
    return None


# ---------------------------------------------------------------- role
def detect_role(demo: IngestedDemo, cfg: Config, idx: dict, steamid: int, tick: int,
                commitment: str, tc: TemporalContext) -> tuple[str, dict]:
    teams = {p["steamid"]: p["team_number"] for p in demo.players}
    my_team = teams.get(steamid, -1)
    if commitment == "PLANT_COMMITTED":
        return "BOMB_PLANTER", {"BOMB_PLANTER": 0.9, "FREE_ROLE": 0.1}
    if commitment == "DEFUSE_COMMITTED":
        return "DEFUSER", {"DEFUSER": 0.9, "FREE_ROLE": 0.1}
    carrier = _bomb_carrier(demo, tick)
    if carrier == steamid:
        return "BOMB_CARRIER", {"BOMB_CARRIER": 0.8, "FREE_ROLE": 0.2}
    # plant cover: teammate committing plant nearby
    for p in demo.events["plants_start"]:
        if p.get("user_steamid") in teams and teams[p["user_steamid"]] == my_team \
                and p["user_steamid"] != steamid and abs(p["tick"] - tick) <= cfg.commit_plant_window_ticks:
            return "PLANT_COVER", {"PLANT_COVER": 0.7, "TRADE_SUPPORT": 0.2, "FREE_ROLE": 0.1}
    # trade support: teammate in engagement near
    for d in demo.events["damages"]:
        other = d["user_steamid"] if d["attacker_steamid"] == steamid else None
        if other is None:
            continue
        if teams.get(other) == my_team and abs(d["tick"] - tick) <= 96 and \
                tc.nearest_teammate_dist is not None and tc.nearest_teammate_dist <= 1600.0:
            return "TRADE_SUPPORT", {"TRADE_SUPPORT": 0.65, "FREE_ROLE": 0.35}
    if commitment == "ENGAGEMENT_COMMITTED":
        return "ENTRY", {"ENTRY": 0.55, "SECOND_CONTACT": 0.25, "FREE_ROLE": 0.2}
    if tc.bomb_planted and tc.zone_set and max(tc.zone_set, key=tc.zone_set.get) == tc.demo.header.get("map_name"):
        pass
    if tc.bomb_planted:
        return "POST_PLANT_HOLD", {"POST_PLANT_HOLD": 0.6, "ANCHOR": 0.25, "FREE_ROLE": 0.15}
    if tc.n_known_enemies == 0 and tc.nearest_teammate_dist is not None and tc.nearest_teammate_dist > 3200.0:
        return "FLANK_WATCH", {"FLANK_WATCH": 0.5, "FREE_ROLE": 0.5}
    return "FREE_ROLE", {"FREE_ROLE": 0.8, "UNKNOWN": 0.2}


# ---------------------------------------------------------------- intent
def _softmax(scores: dict) -> dict:
    import math
    mx = max(scores.values()) if scores else 0.0
    ex = {k: math.exp(v - mx) for k, v in scores.items()}
    tot = sum(ex.values()) or 1.0
    return {k: v / tot for k, v in ex.items()}


def classify_intent(demo: IngestedDemo, cfg: Config, tc: TemporalContext,
                    steamid: int, tick: int) -> tuple[str, float, dict]:
    """Rule-baseline intent classification (spec §16-§17), information-aware.

    V1.2.1 (spec §6): the same movement trajectory must classify differently
    when the *information* differs. ROTATE requires strong information in the
    direction of travel; with no information the same movement is REPOSITION /
    GATHER_INFO. Distance/zone counts alone never decide rotation.
    """
    scores = {k: 0.0 for k in INTENTS}
    moving = tc.time_moving_ticks >= 8
    stationary = tc.time_moving_ticks <= 4
    zc = tc.zone_crossings
    resp_zone = tc.zone_sequence[0] if tc.zone_sequence else None
    head_zone = tc.zone_sequence[-1] if tc.zone_sequence else None
    head = tc.trajectory[-1] if tc.trajectory else None
    org = tc.trajectory[0] if tc.trajectory else None
    moved_dist = 0.0
    if head and org:
        b = tc.bounds
        moved_dist = ((head["pos"][0] - org["pos"][0]) * (b[1] - b[0])) ** 2
        moved_dist += ((head["pos"][1] - org["pos"][1]) * (b[3] - b[2])) ** 2
        moved_dist = moved_dist ** 0.5

    # ---- V1.2.1 information grounding (spec §6) ------------------------------
    # Where does the player's own information point? (A / B / Mid / Unknown)
    info_dir = getattr(tc, "information_direction", "UNKNOWN")
    info_strength = getattr(tc, "information_strength", "NONE")
    info_score = getattr(tc, "information_strength_score", 0.0)
    info_strong = info_strength in ("STRONG", "CONFIRMED") or info_score >= 0.7
    info_medium = info_strength in ("MEDIUM", "STRONG", "CONFIRMED") or info_score >= 0.45
    # Does the direction of travel match where the information is?
    travel_zone = head_zone if head_zone in ("A", "B") else None
    info_zone = {"A_SIDE": "A", "B_SIDE": "B"}.get(info_dir)
    moving_toward_info = bool(travel_zone and info_zone and travel_zone == info_zone)
    # bomb is public info; leaving the non-bomb site toward it is a rotation
    bomb_opposite = (tc.bomb_planted and tc.bomb_site in ("A", "B")
                     and tc.bomb_site != _side_zone(resp_zone))
    opp_side_signal = bomb_opposite or (tc.n_known_enemies >= 2 and info_strong)

    if stationary:
        scores["HOLD"] += 1.6
        scores["CONTEST"] += 0.4
    if moving:
        if zc >= cfg.rotation_min_zone_crossings and moved_dist >= cfg.rotation_min_dist \
                and (opp_side_signal or moving_toward_info) and tc.heading_consistency >= 0.5:
            scores["ROTATE"] += 2.0
        elif zc >= 1 and moved_dist >= cfg.rotation_min_dist * 0.5 and \
                (moving_toward_info and info_medium or tc.heading_consistency >= 0.6):
            scores["SOFT_ROTATE"] += 1.6
        elif zc <= 1 and moved_dist <= cfg.reposition_max_dist:
            scores["REPOSITION"] += 1.4
        else:
            scores["SOFT_ROTATE"] += 0.8
            scores["REPOSITION"] += 0.6
        # gather info: recent sound/known enemy in direction of movement
        if tc.info_update_recency <= 128 and tc.n_known_enemies >= 1:
            scores["GATHER_INFO"] += 1.2
        # support: teammate recently took damage
        for d in demo.events["damages"]:
            if abs(d["tick"] - tick) <= 96 and d["user_steamid"] != steamid and \
                    d["user_steamid"] in {p["steamid"] for p in demo.players}:
                scores["SUPPORT"] += 1.0
                break
    if _bomb_carrier(demo, tick) == steamid and moving:
        scores["PLANT"] += 1.5
    if tc.bomb_planted and stationary:
        scores["HOLD"] += 0.8
        scores["CONTEST"] += 0.6
    if tc.n_known_enemies >= 2 and stationary:
        scores["CONTEST"] += 0.8

    dist = _softmax({k: v for k, v in scores.items() if v > 0} or {"UNKNOWN": 1.0})
    ranked = sorted(dist.items(), key=lambda kv: -kv[1])
    top, second = ranked[0], ranked[1] if len(ranked) > 1 else ("UNKNOWN", 0.0)
    if top[0] == "UNKNOWN" or top[1] - second[1] < cfg.intent_ambiguity_threshold:
        return "AMBIGUOUS", round(top[1], 3), dist
    return top[0], round(top[1], 3), dist


def _side_zone(zone: str | None) -> str | None:
    if zone in ("A", "B"):
        return zone
    return None
