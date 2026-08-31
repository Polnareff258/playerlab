"""Map place name (m_szLastPlaceName) -> coarse zone table.

Zone = hard-filter level for similar-state retrieval. de_dust2 zones are
hand-defined (case-insensitive); other maps fall back to the raw place name
so retrieval still works (just finer-grained). Place names verified from the
real spike demo.
"""
from __future__ import annotations

DUST2_ZONES = {
    "A": {"asite", "shorta", "longa", "longdoor", "longcorner", "pit", "aramp",
          "extendeda", "aupper", "sitea", "ctspawnsidea", "crosswalk", "goose", "a",
          "bombsitea", "shortstairs", "undera", "short"},
    "B": {"bsite", "siteb", "bdoors", "bwindow", "bramp", "uppertunnel", "lowertunnel",
          "outsidetunnel", "window", "bstairs", "backalley", "closet", "hole",
          "tunnelstairs", "b", "banda", "bombsiteb", "twindow", "bench"},
    "MID": {"middle", "topofmid", "middoors", "midboxes", "midbottom", "catwalk",
            "nest", "cat", "short", "connector", "palace", "xbox", "mid"},
    "CT": {"ctspawn", "ctmid", "ct", "ctspawnsideb", "ctspawnsidea"},
    "T": {"tspawn", "tunnel", "tmid", "t", "tspawnsidea"},
    "LONG": {"outsidelong", "long", "pit", "longdoors", "longcorner", "longa",
             "lond", "lone", "bighouse"},
    "OTHER": {"", "unknown"},
}


def zone_for(map_name: str, place: str) -> str:
    """Map a place name to a coarse zone. Unknown places keep their raw name.
    Non-string places (NaN / numeric garbage in some demos) -> 'other'."""
    if not isinstance(place, str):
        return "other"
    p = place.strip()
    if not p:
        return "other"
    if map_name == "de_dust2":
        pl = p.lower()
        for zone, places in DUST2_ZONES.items():
            if pl in places:
                return zone
        return p  # unhandled dust2 place -> raw name as zone
    return p  # generic map: place name IS the zone (documented limitation)
