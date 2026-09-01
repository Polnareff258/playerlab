"""FocusPlayerContext (V1.3.2 PART A): the player currently under analysis.

Focus Player is a first-class concept: the whole analysis flow (episodes,
engagements, duels, patterns, training targets, review moments, calibration)
must know WHICH player it is working on. This is NOT a front-end filter —
the context lives at the service/API layer and player-scoped queries hit the
DB directly.

Remembered user ("This is me", PART A §4): a steam_id marked is_user persists
across sessions; when a new demo contains that steam_id it becomes the
default focus — but the user can always switch (PART A §5: never assume the
demo owner; show a selector when unknown).
"""
from __future__ import annotations

import time

from .db import DB

PREF_FOCUS = "focus_player_steam_id"


class FocusPlayerContext:
    """Session-level focus: which player is being analyzed."""

    def __init__(self, match_id: str | None = None, steam_id: int | None = None,
                 display_name: str = "", team: int | None = None,
                 is_user: bool = False):
        self.match_id = match_id
        self.steam_id = steam_id
        self.display_name = display_name
        self.team = team
        self.is_user = is_user

    @property
    def active(self) -> bool:
        return self.steam_id is not None

    def to_dict(self) -> dict:
        return {"match_id": self.match_id, "steam_id": self.steam_id,
                "display_name": self.display_name, "team": self.team,
                "is_user": self.is_user}

    def __repr__(self):
        return (f"FocusPlayerContext(match={self.match_id}, "
                f"steam={self.steam_id}, name={self.display_name!r})")


def players_of_match(db: DB, match_id: str) -> list[dict]:
    """Players of a match, enriched with profile/is_user info (PART A §3)."""
    players = db.get_players(match_id)
    user = db.get_user_profile()
    user_sid = user["steam_id"] if user else None
    out = []
    for p in players:
        sid = int(p["steamid"])
        prof = db.get_player_profile(sid)
        out.append({
            "steam_id": str(sid),   # string: JS numbers lose precision >2^53
            "display_name": p["name"],
            "team": p["team_number"],
            "is_user": bool(user_sid == sid or (prof and prof["is_user"])),
            "remembered": bool(prof),
        })
    return out


def remember_user(db: DB, steam_id: int, display_name: str) -> dict:
    """Mark a player as 'This is me' (PART A §4)."""
    return db.upsert_player_profile(steam_id, display_name, is_user=True)


def default_focus(db: DB, match_id: str) -> FocusPlayerContext:
    """Default focus: the remembered user if present in this match, else None
    (show the player selector — never guess the owner, PART A §5)."""
    user = db.get_user_profile()
    if user:
        players = db.get_players(match_id)
        for p in players:
            if int(p["steamid"]) == int(user["steam_id"]):
                return FocusPlayerContext(
                    match_id=match_id, steam_id=int(user["steam_id"]),
                    display_name=user["display_name"], team=p["team_number"],
                    is_user=True)
    return FocusPlayerContext(match_id=match_id)


def set_focus(db: DB, match_id: str, steam_id: int, persist: bool = False) -> FocusPlayerContext:
    """Set the current focus player for a match. Optionally persist as the
    remembered default (PART A §4)."""
    player = next((p for p in db.get_players(match_id)
                   if int(p["steamid"]) == int(steam_id)), None)
    if not player:
        raise ValueError(f"steam_id {steam_id} not in match {match_id}")
    ctx = FocusPlayerContext(match_id=match_id, steam_id=int(steam_id),
                             display_name=player["name"],
                             team=player["team_number"])
    if persist:
        remember_user(db, int(steam_id), player["name"])
    return ctx
