"""Canonical field map: PlayerLab canonical names <-> demoparser2 0.42 names.

Verified at runtime on a real CS2 SourceTV demo (de_dust2, 18 rounds):
friendly names like x/y/z/view_angle_x were dropped by 0.42, while entity
paths (CCSPlayerPawn.origin etc.) parse correctly. `buttons`, `is_walking`,
`is_scoped`, `last_place_name` friendly names still work.
"""
from __future__ import annotations

# canonical -> demoparser2 0.42.0 prop name
# NOTE (spike v2): CCSPlayerPawn.origin returns stale spawn coordinates in CS2
# demos; the live position is CBodyComponentBaseAnimGraph.m_vecX/Y/Z.
# m_vecBaseVelocity is never updated in demos -> velocity is DERIVED from
# position deltas at ingest time (see ingest.derive_velocity).
FIELD_MAP = {
    "tick": "tick",
    "steamid": "steamid",
    "name": "name",
    "x": "CCSPlayerPawn.CBodyComponentBaseAnimGraph.m_vecX",
    "y": "CCSPlayerPawn.CBodyComponentBaseAnimGraph.m_vecY",
    "z": "CCSPlayerPawn.CBodyComponentBaseAnimGraph.m_vecZ",
    "view": "CCSPlayerPawn.m_angEyeAngles",              # [pitch, yaw, roll]
    "buttons": "buttons",                                # friendly bitmask
    "health": "CCSPlayerPawn.m_iHealth",
    "armor": "CCSPlayerPawn.m_ArmorValue",
    "money": "CCSPlayerController.CCSPlayerController_InGameMoneyServices.m_iAccount",
    "weapon_def": "Weapon.m_iItemDefinitionIndex",
    "place": "CCSPlayerPawn.m_szLastPlaceName",
    "shots_fired": "CCSPlayerPawn.m_iShotsFired",
    "is_walking": "is_walking",
    "is_scoped": "is_scoped",
    "is_alive": "is_alive",
    "ping": "ping",
    "team_num": "CCSPlayerController.m_iTeamNum",
    # V1.3.1 duel/utility grounding (verified on real CS2 SourceTV demo):
    "ammo_clip": "Weapon.m_iClip1",                     # current magazine
    "flash_duration": "CCSPlayerPawn.m_flFlashDuration",  # blind state (>0 = flashed)
    "zoom_level": "CCSPlayerPawn.m_iZoomLevel",          # 0 = unscoped, 1/2 = scoped
}

# buttons bitmask flags (CS2 IN_* constants; verified in real demo)
BUTTON_DUCK = 4       # IN_DUCK
BUTTON_ATTACK = 1     # IN_ATTACK
BUTTON_USE = 512      # IN_USE (plant/defuse hold)
BUTTON_MOVELEFT = 1024
BUTTON_MOVERIGHT = 2048

CANONICAL_FIELDS = list(FIELD_MAP.keys())

# CS2 team numbers (verified via parse_player_info + round_end winner)
TEAM_T = 2
TEAM_CT = 3


def parser_props() -> list[str]:
    return list(FIELD_MAP.values())


def rename_columns(df):
    """Rename demoparser2 output columns back to canonical names."""
    reverse = {v: k for k, v in FIELD_MAP.items()}  # parser name -> canonical
    df = df.rename(columns={k: v for k, v in reverse.items() if k in df.columns})
    return df


def team_name(team_number) -> str:
    if team_number == TEAM_T:
        return "T"
    if team_number == TEAM_CT:
        return "CT"
    return "SPECTATOR"
