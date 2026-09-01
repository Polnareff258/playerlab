"""GeometryProvider (V1.3.2 PART F): LOS / nav / cover abstraction.

Never let core modules depend on a specific geometry library. NullGeometry
keeps everything running without geometry; EvidenceSufficiency stays honest
at MEDIUM/LOW (§32). Metadata always carries source / quality / version so
nothing pretends to be exact when it is an approximation (§33).

Reference: docs/LOS_NAV_SPIKE.md — awpy (MIT) is the leading candidate;
see docs/GEOMETRY_SPIKE.md for the V1.3.2 investigation conclusion.
"""
from __future__ import annotations

from .context import TemporalContext

GEOMETRY_SOURCES = ("null", "awpy", "custom-nav")
GEOMETRY_QUALITY = ("none", "approximate", "exact")


class GeometryProvider:
    """Contract for any geometry backend (PART F §31)."""

    source = "null"
    quality = "none"
    version = "0"

    def can_see(self, map_name: str, pos_a, pos_b) -> bool | None:
        raise NotImplementedError

    def nav_distance(self, map_name: str, pos_a, pos_b) -> float | None:
        raise NotImplementedError

    def has_cover(self, map_name: str, pos_a, pos_b) -> bool | None:
        raise NotImplementedError

    def trade_geometry(self, map_name: str, pos_a, pos_b) -> dict:
        """Best-effort trade info (LOS + distance); unknown fields -> None."""
        return {"los": self.can_see(map_name, pos_a, pos_b),
                "nav_distance": self.nav_distance(map_name, pos_a, pos_b),
                "cover": self.has_cover(map_name, pos_a, pos_b)}

    def get_metadata(self) -> dict:
        return {"geometry_source": self.source, "geometry_quality": self.quality,
                "geometry_version": self.version}


class NullGeometryProvider(GeometryProvider):
    """Default: no geometry. Everything returns None; system still runs (§32)."""

    source = "null"
    quality = "none"
    version = "0"

    def can_see(self, map_name, pos_a, pos_b):
        return None

    def nav_distance(self, map_name, pos_a, pos_b):
        return None

    def has_cover(self, map_name, pos_a, pos_b):
        return None


class AwpyGeometryProvider(GeometryProvider):
    """Optional awpy-based backend (spike result: viable, needs map assets).

    Loading is lazy and failure-tolerant: if awpy or the map assets are
    missing, every query degrades to None (graceful fallback, §32).
    """

    source = "awpy"
    quality = "approximate"
    version = "0.1"

    def __init__(self, nav_dir: str | None = None, tri_dir: str | None = None):
        self.nav_dir = nav_dir
        self.tri_dir = tri_dir
        self._nav = {}
        self._tri = {}
        self._error = None
        try:
            import awpy  # noqa: F401
            self._awpy_ok = True
        except Exception as e:  # noqa: BLE001
            self._awpy_ok = False
            self._error = f"{type(e).__name__}: {e}"

    def _load_map(self, map_name: str):
        if map_name in self._nav or not self._awpy_ok:
            return
        try:
            from awpy.nav import NavMesh
            from awpy.visibility import read_tri_file
            import os
            nav_path = os.path.join(self.nav_dir or "", f"{map_name}.nav")
            tri_path = os.path.join(self.tri_dir or "", f"{map_name}.vphys")
            if os.path.isfile(nav_path):
                self._nav[map_name] = NavMesh.from_path(nav_path)
            if os.path.isfile(tri_path):
                self._tri[map_name] = read_tri_file(tri_path)
        except Exception as e:  # noqa: BLE001
            self._error = f"{type(e).__name__}: {e}"

    def can_see(self, map_name, pos_a, pos_b):
        self._load_map(map_name)
        tri = self._tri.get(map_name)
        if tri is None:
            return None
        try:
            from awpy.visibility import is_visible
            from awpy.vector import Vector3
            return bool(is_visible(tri, Vector3(*pos_a), Vector3(*pos_b)))
        except Exception:  # noqa: BLE001
            return None

    def nav_distance(self, map_name, pos_a, pos_b):
        self._load_map(map_name)
        nav = self._nav.get(map_name)
        if nav is None:
            return None
        try:
            a = nav.find_closest_area(pos_a)
            b = nav.find_closest_area(pos_b)
            return float(nav.find_path(a, b).distance)
        except Exception:  # noqa: BLE001
            return None

    def has_cover(self, map_name, pos_a, pos_b):
        los = self.can_see(map_name, pos_a, pos_b)
        if los is None:
            return None
        return not los  # cover present when LOS blocked

    def get_metadata(self) -> dict:
        d = super().get_metadata()
        d["note"] = ("awpy geometry: approximate; needs .nav + .vphys map assets "
                     "under nav_dir/tri_dir; loads lazily; errors degrade to None")
        if self._error:
            d["error"] = self._error
        return d


def get_geometry(provider: str = "null", **kw) -> GeometryProvider:
    """Provider factory with graceful fallback (§32)."""
    if provider == "awpy":
        try:
            g = AwpyGeometryProvider(**kw)
            return g
        except Exception:  # noqa: BLE001
            pass
    return NullGeometryProvider()
