"""PlayerLab V1 configuration: inline defaults + optional JSON overrides.

Every threshold / weight / radius is configurable and versioned. Config files
live in playerlab/config/*.json; when present they override the defaults.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, asdict

CONFIG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "config")


@dataclass
class Config:
    # --- detection thresholds (ticks at 64/s) ---
    v_peek: float = 120.0            # speed u/s for peek movement
    v_hold: float = 60.0             # speed u/s considered holding
    v_disengage: float = 120.0       # speed u/s for disengage retreat
    hold_min_ticks: int = 16         # min stationary duration to call HOLD
    disengage_quiet_ticks: int = 24  # quiet window after contact to call DISENGAGE
    re_peek_window_ticks: int = 96   # max gap between disengage and re-peek
    re_peek_angle_deg: float = 35.0  # max yaw change for same-angle re-peek
    fallback_min_dist: float = 600.0  # sustained retreat distance (units)
    episode_merge_ticks: int = 150    # DP dedup window per player
    max_dp_per_match: int = 60
    outcome_window_ticks: int = 640   # survival@W (10 s at 64 tick)
    contact_radius: float = 2000.0    # damage-actor proximity radius (units)

    # --- PlayerKnownState ---
    vision_fov_deg: float = 90.0      # CS2 horizontal FOV (approx)
    vision_max_dist: float = 4000.0   # units (~100 m); approx, no occlusion in V1
    footstep_hear_radius: float = 1280.0   # units (~32 m) configurable
    shot_hear_radius: float = 1600.0  # units (~40 m)
    grenade_hear_radius: float = 1600.0
    known_state_memory_ticks: int = 256  # forget last-seen after 4 s
    damage_memory_ticks: int = 1024  # damage-derived enemy info lasts 16 s
    team_comms: bool = True           # teammates share sightings (assumption)
    teammate_contact_window_ticks: int = 192   # V1.2.1: teammate contact recency
    public_feed_window_ticks: int = 128        # V1.2.1: public kill/death feed recency
    bomb_carrier_known_ticks: int = 512        # V1.2.1: how long the carrier is public info

    # --- similarity ---
    hard_filter_map: bool = True
    hard_filter_side: bool = True
    hard_filter_zone: bool = True
    soft_weights: dict = field(default_factory=lambda: {
        "time_left": 0.10, "alive_diff": 0.15, "hp": 0.10,
        "weapon_class": 0.10, "n_known_enemies": 0.10, "known_spread": 0.05,
        "nearest_known_enemy": 0.10, "recent_contact": 0.10,
        "teammate_near": 0.10, "teammate_mid": 0.05, "bomb_planted": 0.05,
        "economy": 0.05, "time_pressure": 0.05,
    })
    top_k: int = 50
    exclude_same_match: bool = True   # retrieval leakage guard

    # --- alpha patterns (V1.1-alpha) ---
    repeek_time_delta_max_ticks: int = 192   # "within 3 seconds" at 64 tick
    repeek_angle_max_deg: float = 35.0
    move_shoot_velocity: float = 130.0       # u/s horizontal velocity at shot -> violation
    stabilize_velocity: float = 60.0         # u/s considered "stopped enough"
    pre_shot_window_ticks: int = 24          # speed curve lookback before a shot
    advantage_min_diff: int = 1              # team_alive - enemy_alive >= 1 = advantage
    advantage_isolated_dist: float = 1600.0  # nearest teammate beyond this = isolated
    advantage_engagement_dist: float = 2400.0  # engagement zone radius around player
    objective_urgency_bomb_s: float = 30.0   # bomb planted & < this remaining = urgent
    min_pattern_samples: int = 8             # eligibility for TrainingTarget
    min_pattern_confidence: float = 0.4
    validation_window_matches: int = 5
    trainability: dict = field(default_factory=lambda: {
        "repeek": 0.9, "move_shoot": 0.9, "advantage": 0.6})
    impact_weights: dict = field(default_factory=lambda: {
        "death": 1.0, "duel_loss": 0.8, "round_loss": 0.7, "positional_loss": 0.4})
    review_budget_per_match: int = 8
    review_focus: str = "balanced"   # balanced | intent | responsibility | pattern | other
    review_quota: dict = field(default_factory=lambda: {
        "intent": 3, "responsibility": 2, "pattern": 2, "other": 1})
    # --- V1.2.1 optional model intelligence (spec §22) ---
    model_provider: str = "null"     # "null" | "csnet" (optional backend)
    csnet_models_dir: str = ""       # e.g. external/cs-net/cs-net-models
    csnet_repo_dir: str = ""         # e.g. external/cs-net

    # --- V1.2 context & intent ---
    context_window_ticks: int = 256      # ~4 s lookback for TemporalContext
    context_sample_interval: int = 16    # 4 Hz feature timesteps
    intent_ambiguity_threshold: float = 0.15
    rotation_min_zone_crossings: int = 2
    rotation_min_dist: float = 1500.0    # distance from responsibility for ROTATE
    soft_rotate_max_dist: float = 2600.0
    reposition_max_dist: float = 1400.0
    gather_info_dist: float = 2000.0
    commit_plant_window_ticks: int = 205  # plant ~3.2 s
    commit_reload_window_ticks: int = 150
    commit_utility_window_ticks: int = 96
    commit_engagement_idle_ticks: int = 48
    responsibility_conf_threshold: float = 0.55

    # --- V1.2.1 responsibility conservative gate ---
    isolated_support_dist: float = 2400.0   # beyond this, support claims need LOS/tradeability
    dry_peek_known_enemy_dist: float = 1400.0  # enemy known this close -> fight entered knowingly
    risk_plant_known_enemy_dist: float = 1200.0
    reload_risk_known_enemy_dist: float = 1800.0
    min_evidence_for_self_decision: float = 0.5  # evidence gate floor for SELF_DECISION

    # --- evidence discipline (COUNTERFACTUAL_DESIGN §8) ---
    n_min_claim: int = 10
    n_min_action: int = 5
    wilson_z: float = 1.96
    ci_overlap_alpha: float = 0.05    # interval-overlap decision threshold

    # --- validation (BACKTEST_DESIGN §7) ---
    calib_max_dev_pp: float = 10.0    # max |pred-actual| in pp per bin
    qa_topk: int = 5
    qa_pass_min_score: float = 3.0
    qa_pass_min_share: float = 0.8

    # --- runtime ---
    data_dir: str = ""
    db_path: str = ""

    def __post_init__(self):
        if not self.data_dir:
            self.data_dir = os.path.join(os.path.dirname(os.path.dirname(
                os.path.dirname(os.path.abspath(__file__)))), "data")
        if not self.db_path:
            self.db_path = os.path.join(self.data_dir, "playerlab.sqlite")

    def resolve(self) -> "Config":
        merged = asdict(self)
        for name in ("features.json", "thresholds.json", "validation.json",
                     "model_intelligence.json"):
            path = os.path.join(CONFIG_DIR, name)
            if os.path.isfile(path):
                with open(path, "r", encoding="utf-8") as fh:
                    overrides = json.load(fh)
                for k, v in overrides.items():
                    if k in merged and isinstance(v, type(merged[k])):
                        merged[k] = v
        return Config(**merged)


def load() -> Config:
    return Config().resolve()
