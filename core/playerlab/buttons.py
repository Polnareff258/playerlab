"""CS2 IN_* button bitmask constants and decoder (Source SDK layout).

Verified at runtime against demoparser2 0.42 `buttons` friendly prop
(SourceTV CS2 demo). Values follow the classic Source in_buttons.h layout.
"""
from __future__ import annotations

# NOTE: CS:GO/CS2 m_nButtons has NO primary-attack bit (attack lives in
# usercmd). IN_GRENADE2 occupies bit 24; IN_ATTACK2/3 are secondary/tertiary.
IN_JUMP = 1 << 1
IN_DUCK = 1 << 2
IN_FORWARD = 1 << 3
IN_BACK = 1 << 4
IN_USE = 1 << 5
IN_CANCEL = 1 << 6
IN_LEFT = 1 << 7
IN_RIGHT = 1 << 8
IN_MOVELEFT = 1 << 9
IN_MOVERIGHT = 1 << 10
IN_ATTACK2 = 1 << 11
IN_RUN = 1 << 12
IN_RELOAD = 1 << 13
IN_ALT1 = 1 << 14
IN_ALT2 = 1 << 15
IN_SCORE = 1 << 16
IN_SPEED = 1 << 17
IN_WALK = 1 << 18
IN_ZOOM = 1 << 19
IN_WEAPON1 = 1 << 20
IN_WEAPON2 = 1 << 21
IN_BULLRUSH = 1 << 22
IN_GRENADE1 = 1 << 23
IN_GRENADE2 = 1 << 24
IN_ATTACK3 = 1 << 25

_NAMES = {
    IN_JUMP: "jump", IN_DUCK: "duck", IN_FORWARD: "forward",
    IN_BACK: "back", IN_USE: "use", IN_LEFT: "left", IN_RIGHT: "right",
    IN_MOVELEFT: "moveleft", IN_MOVERIGHT: "moveright", IN_ATTACK2: "attack2",
    IN_RELOAD: "reload", IN_SPEED: "speed", IN_WALK: "walk", IN_ZOOM: "zoom",
    IN_SCORE: "score", IN_GRENADE1: "grenade1", IN_GRENADE2: "grenade2",
}


def decode(buttons: int) -> list[str]:
    """Decode a buttons bitmask into human-readable pressed key names."""
    out = []
    for flag, name in _NAMES.items():
        if buttons & flag:
            out.append(name)
    return sorted(out)


def is_moving(buttons: int) -> bool:
    return bool(buttons & (IN_FORWARD | IN_BACK | IN_MOVELEFT | IN_MOVERIGHT))


def is_firing(buttons: int) -> bool:
    """Approximate firing indicator (no primary-attack bit exists; secondary/
    tertiary + grenade keys are the only firing-adjacent bits)."""
    return bool(buttons & (IN_ATTACK2 | IN_ATTACK3 | IN_GRENADE1 | IN_GRENADE2))
