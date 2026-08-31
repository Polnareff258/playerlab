"""Weapon item-definition index table (CS2/CS:GO) -> name -> class.

`Weapon.m_iItemDefinitionIndex` is verified available per player per tick via
demoparser2 0.42 on a real CS2 SourceTV demo. Unknown indices map to
"unknown(<idx>)" and class "unknown" — never guessed.
"""
from __future__ import annotations

ITEM_DEFS = {
    1: "deagle", 2: "elite", 3: "fiveseven", 4: "glock", 7: "ak47",
    8: "aug", 9: "awp", 10: "famas", 11: "g3sg1", 13: "galilar",
    14: "m249", 16: "m4a4", 17: "mac10", 19: "p90", 23: "mp5sd",
    24: "ump45", 25: "xm1014", 26: "bizon", 27: "mag7", 28: "negev",
    29: "sawedoff", 30: "tec9", 31: "taser", 32: "p2000", 33: "mp7",
    34: "mp9", 35: "nova", 36: "p250", 37: "scar20", 38: "sg556",
    39: "ssg08", 40: "mp5", 42: "knife", 43: "flashbang", 44: "hegrenade",
    45: "smokegrenade", 46: "molotov", 47: "decoy", 48: "incgrenade",
    49: "c4", 60: "m4a1_silencer", 61: "usp_silencer", 63: "cz75a",
    64: "revolver", 500: "bayonet", 503: "knife_css", 505: "knife_flip",
    506: "knife_gut", 507: "knife_karambit", 508: "knife_m9_bayonet",
    509: "knife_tactical", 512: "knife_falchion", 514: "knife_survival_bowie",
    515: "knife_butterfly", 516: "knife_push", 517: "knife_cord", 518: "knife_canis",
    519: "knife_ursus", 520: "knife_gypsy_jackknife", 521: "knife_outdoor",
    522: "knife_stiletto", 523: "knife_widowmaker", 525: "knife_skeleton",
    526: "knife_kukri", 527: "knife_legend_blade",
}

RIFLE = {"ak47", "m4a4", "m4a1_silencer", "aug", "sg556", "galilar", "famas"}
SNIPER = {"awp", "ssg08", "scar20", "g3sg1"}
SMG = {"mp9", "mp7", "mp5sd", "mp5", "mac10", "p90", "ump45", "bizon"}
HEAVY = {"nova", "xm1014", "mag7", "sawedoff", "m249", "negev"}
PISTOL = {"deagle", "elite", "fiveseven", "glock", "tec9", "p2000", "p250",
          "usp_silencer", "cz75a", "revolver", "taser"}
GRENADES = {"flashbang", "hegrenade", "smokegrenade", "molotov", "incgrenade", "decoy"}
KNIFE = {"knife", "bayonet", "knife_css", "knife_flip", "knife_gut", "knife_karambit",
         "knife_m9_bayonet", "knife_tactical", "knife_falchion", "knife_survival_bowie",
         "knife_butterfly", "knife_push", "knife_cord", "knife_canis", "knife_ursus",
         "knife_gypsy_jackknife", "knife_outdoor", "knife_stiletto", "knife_widowmaker",
         "knife_skeleton", "knife_kukri", "knife_legend_blade"}


def name_from_def(idx) -> str:
    try:
        i = int(idx)
    except (TypeError, ValueError):
        return "unknown"
    return ITEM_DEFS.get(i, f"unknown({i})")


def weapon_class(name: str) -> str:
    if name in RIFLE:
        return "rifle"
    if name in SNIPER:
        return "sniper"
    if name in SMG:
        return "smg"
    if name in HEAVY:
        return "heavy"
    if name in PISTOL:
        return "pistol"
    if name in GRENADES:
        return "grenade"
    if name in KNIFE:
        return "knife"
    if name in ("c4",):
        return "c4"
    return "unknown"
