#!/usr/bin/env python3
"""Setup geometry map assets (V1.3.3 PART H §23-§24).

Downloads/places .nav + .vphys assets into data/maps/ (gitignored) for the
awpy geometry backend. Assets are large (100MB+ per map) and MUST NOT be
committed to git.

Usage:
    python scripts/setup_geometry_assets.py --map de_dust2
    python scripts/setup_geometry_assets.py --list-known

Asset metadata is recorded to data/maps/manifest.json so results are
reproducible after CS2 updates (map_name/asset_version/source/file_hash/
created_at). This is a MANUAL-asset workflow: if automated download sources
are unstable or unavailable, follow docs/MANUAL_ASSET_SETUP.md instead.
"""
import argparse
import hashlib
import json
import os
import sys

MAPS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "data", "maps")
MANIFEST = os.path.join(MAPS_DIR, "manifest.json")

# Known-good asset source locations to check (may be empty until community
# sources are curated — do not fabricate URLs).
KNOWN_SOURCES = {
    # map_name: {"nav": url_or_none, "vphys": url_or_none}
    "de_dust2": {"nav": None, "vphys": None},
    "de_mirage": {"nav": None, "vphys": None},
}


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_manifest() -> dict:
    if os.path.isfile(MANIFEST):
        with open(MANIFEST, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"assets": {}}


def save_manifest(m: dict):
    os.makedirs(MAPS_DIR, exist_ok=True)
    with open(MANIFEST, "w", encoding="utf-8") as f:
        json.dump(m, f, ensure_ascii=False, indent=1)


def register_asset(map_name: str, asset_type: str, path: str, source: str,
                   version: str = "unknown"):
    m = load_manifest()
    entry = m["assets"].setdefault(map_name, {})
    entry[asset_type] = {
        "path": path, "source": source, "asset_version": version,
        "file_hash": _sha256(path),
        "game_build": "unknown", "created_at": __import__("time").strftime(
            "%Y-%m-%dT%H:%M:%S"),
    }
    save_manifest(m)
    print(f"registered {map_name} {asset_type} -> {path}")


def main():
    ap = argparse.ArgumentParser(description="geometry asset setup")
    ap.add_argument("--map", default="", help="map name (de_dust2, de_mirage, ...)")
    ap.add_argument("--list-known", action="store_true", help="list known maps")
    ap.add_argument("--nav", default="", help="local path to .nav file")
    ap.add_argument("--vphys", default="", help="local path to .vphys file")
    ap.add_argument("--source", default="manual", help="asset source label")
    args = ap.parse_args()

    if args.list_known:
        for m, src in KNOWN_SOURCES.items():
            print(f"{m}: nav={src['nav'] or 'MANUAL'} vphys={src['vphys'] or 'MANUAL'}")
        return

    if not args.map:
        print("error: --map required (or --list-known)", file=sys.stderr)
        sys.exit(1)
    os.makedirs(MAPS_DIR, exist_ok=True)
    if args.nav:
        register_asset(args.map, "nav", os.path.abspath(args.nav), args.source)
    if args.vphys:
        register_asset(args.map, "vphys", os.path.abspath(args.vphys), args.source)
    if not args.nav and not args.vphys:
        print(f"no assets provided for {args.map}; place .nav/.vphys in {MAPS_DIR} "
              "and re-run with --nav/--vphys (see MANUAL_ASSET_SETUP.md)")


if __name__ == "__main__":
    main()
