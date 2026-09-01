#!/usr/bin/env python3
"""Setup geometry map assets (V1.3.3 PART H §23-§24) — automatic download.

Downloads .nav + .tri map assets into data/maps/ (gitignored) for the awpy
geometry backend. Sources:

  - nav mesh files:  https://awpycs.com/{patch}/navs.zip   (~/.awpy/navs/)
  - visibility tris: https://awpycs.com/{patch}/tris.zip   (~/.awpy/tris/)

Awpy mirrors these from the current CS2 build; the .patch file records the
game build the assets were generated from so results stay reproducible.

Usage:
    python scripts/setup_geometry_assets.py --auto          # download all known maps
    python scripts/setup_geometry_assets.py --auto --map de_dust2
    python scripts/setup_geometry_assets.py --map de_dust2  # manual .nav/.tri paths
    python scripts/setup_geometry_assets.py --list-known
    python scripts/setup_geometry_assets.py --check         # report what is missing

If automatic download fails (offline / mirror down), follow
docs/MANUAL_ASSET_SETUP.md to place .nav/.tri files manually.
"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request

MAPS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "data", "maps")
MANIFEST = os.path.join(MAPS_DIR, "manifest.json")

# All known competitive maps we can pull from the awpy mirror.
KNOWN_MAPS = [
    "de_dust2", "de_mirage", "de_inferno", "de_nuke", "de_ancient",
    "de_anubis", "de_overpass", "de_train", "de_vertigo",
]

# awpy mirror base: https://awpycs.com/{patch}/{resource}.zip
AWPYCS_BASE = "https://awpycs.com"
# fallback patch if awpy's CURRENT_BUILD_ID cannot be imported
DEFAULT_PATCH = "17595823"
# historical build ids to try if the current one 404s (mirror retention)
KNOWN_PATCHES = ["17595823", "latest"]

# Common CS2 install locations (the game ships .nav files for official maps).
CS2_MAPS_CANDIDATES = [
    r"C:\Program Files (x86)\Steam\steamapps\common\Counter-Strike Global Offensive\game\csgo\maps",
    r"D:\SteamLibrary\steamapps\common\Counter-Strike Global Offensive\game\csgo\maps",
    r"E:\SteamLibrary\steamapps\common\Counter-Strike Global Offensive\game\csgo\maps",
    r"C:\SteamLibrary\steamapps\common\Counter-Strike Global Offensive\game\csgo\maps",
    r"D:\Games\Steam\steamapps\common\Counter-Strike Global Offensive\game\csgo\maps",
]


def find_local_cs2_maps() -> str | None:
    """Return the CS2 maps dir if a local install is found (has .nav files)."""
    for d in CS2_MAPS_CANDIDATES:
        if os.path.isdir(d) and any(f.endswith(".nav") for f in
                                    os.listdir(d) if os.path.isfile(os.path.join(d, f))):
            return d
    return None


def copy_from_local_cs2(maps: list[str], maps_dir: str) -> int:
    """Copy .nav files from a local CS2 install into data/maps. Returns the
    number of maps with nav copied. (.tri must come from awpy, see docs.)"""
    src = find_local_cs2_maps()
    if not src:
        return 0
    print(f"found CS2 install with maps at: {src}")
    copied = 0
    for m in maps:
        nav_src = os.path.join(src, f"{m}.nav")
        if os.path.isfile(nav_src):
            dst = os.path.join(maps_dir, f"{m}.nav")
            shutil.copy2(nav_src, dst)
            register_asset(m, "nav", dst, "cs2-local-install",
                           version="cs2-game")
            copied += 1
    return copied


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
    return {"assets": {}, "source": "awpy-mirror"}


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
        "game_build": "unknown", "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    save_manifest(m)
    print(f"registered {map_name} {asset_type} -> {path}")


def _awpy_patch() -> str:
    """Return the awpy CURRENT_BUILD_ID if awpy is installed, else 'latest'."""
    try:
        from awpy.data import CURRENT_BUILD_ID
        return str(CURRENT_BUILD_ID)
    except Exception:  # noqa: BLE001
        return DEFAULT_PATCH


def _download_zip(url: str, dest_zip: str) -> bool:
    """Download a zip to dest_zip. Returns True on success. Uses urllib
    (stdlib); honors the HTTP(S)_PROXY / ALL_PROXY environment variables so
    users behind a proxy (e.g. socks5h://127.0.0.1:10808) work out of the box.
    """
    print(f"  downloading {url} ...")
    try:
        handlers = []
        env = {k.lower(): v for k, v in os.environ.items()}
        proxy_url = (env.get("https_proxy") or env.get("http_proxy")
                     or env.get("all_proxy"))
        if proxy_url:
            handlers.append(urllib.request.ProxyHandler({
                "http": proxy_url, "https": proxy_url}))
        opener = urllib.request.build_opener(*handlers)
        req = urllib.request.Request(url, headers={"User-Agent": "PlayerLab/1.0"})
        with opener.open(req, timeout=300) as resp:
            with open(dest_zip, "wb") as fh:
                shutil.copyfileobj(resp, fh)
        return True
    except Exception as e:  # noqa: BLE001
        print(f"  download failed: {e}")
        return False


def _extract_zip(zip_path: str, dest_dir: str):
    import zipfile
    os.makedirs(dest_dir, exist_ok=True)
    with zipfile.ZipFile(zip_path) as z:
        z.extractall(dest_dir)
    print(f"  extracted to {dest_dir}")


def awpy_dir() -> str:
    """Cache dir for awpy resources. Prefer the project-local data/maps (no
    home-dir write permission needed); fall back to ~/.awpy when it exists
    (already downloaded by `awpy get tris`)."""
    local = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "data", "maps", "_awpy_cache")
    try:
        os.makedirs(local, exist_ok=True)
        return local
    except OSError:
        return os.path.join(os.path.expanduser("~"), ".awpy")


def fetch_awpy_resource(resource: str, patch: str | None = None) -> str | None:
    """Download {resource}.zip (navs | tris) from the awpy mirror into the
    awpy cache dir. Tries the requested patch, then the known patches.
    Returns the resource dir or None on failure."""
    if patch:
        patches = [patch] if patch in KNOWN_PATCHES else [patch] + KNOWN_PATCHES
    else:
        patches = [_awpy_patch()] + [p for p in KNOWN_PATCHES if p != _awpy_patch()]
    dest_dir = os.path.join(awpy_dir(), resource)
    try:
        os.makedirs(dest_dir, exist_ok=True)
    except OSError as e:
        print(f"  cannot create cache dir {dest_dir}: {e}")
        return None
    zip_path = os.path.join(dest_dir, f"{resource}.zip")
    for p in patches:
        base = f"{AWPYCS_BASE}/{p}/{resource}.zip"
        print(f"[{resource}] trying patch {p} ...")
        if _download_zip(base, zip_path):
            _extract_zip(zip_path, dest_dir)
            try:
                os.remove(zip_path)
            except OSError:
                pass
            with open(os.path.join(dest_dir, ".patch"), "w") as f:
                f.write(p)
            return dest_dir
    return None


def auto_download(maps: list[str], patch: str | None = None) -> int:
    """Best-effort asset acquisition: try a local CS2 install first (nav
    files ship with the game), then the awpy mirror (navs + tris). Registers
    whatever was obtained into data/maps/ + manifest. Returns count."""
    os.makedirs(MAPS_DIR, exist_ok=True)
    registered = 0
    # 1) local CS2 install (free, version-correct .nav files)
    try:
        registered += copy_from_local_cs2(maps, MAPS_DIR)
    except Exception as e:  # noqa: BLE001
        print(f"  local CS2 nav copy failed: {e}")
    # 2) awpy mirror (navs + tris)
    nav_dir = fetch_awpy_resource("navs", patch)
    tri_dir = fetch_awpy_resource("tris", patch)
    if nav_dir or tri_dir:
        for m in maps:
            nav = os.path.join(nav_dir or "", f"{m}.nav")
            tri = os.path.join(tri_dir or "", f"{m}.tri")
            if os.path.isfile(nav):
                dst = os.path.join(MAPS_DIR, f"{m}.nav")
                shutil.copy2(nav, dst)
                register_asset(m, "nav", dst, "awpy-mirror",
                               version=patch or "unknown")
                registered += 1
            if os.path.isfile(tri):
                dst = os.path.join(MAPS_DIR, f"{m}.tri")
                shutil.copy2(tri, dst)
                register_asset(m, "tri", dst, "awpy-mirror",
                               version=patch or "unknown")
                registered += 1
    if registered == 0:
        print()
        print("=" * 72)
        print("Could not obtain map assets (no local CS2 install found and")
        print("the awpy mirror is unreachable).")
        print()
        print("PlayerLab still works: geometry queries degrade gracefully to")
        print("'unknown' (NullGeometry). To enable LOS / nav analysis later:")
        print()
        print("  1. Install CS2 and copy from your game directory:")
        print("     steamapps/common/Counter-Strike Global Offensive/")
        print("         game/csgo/maps/de_dust2.nav   -> data/maps/")
        print("  2. Get .tri files (visibility) via the awpy CLI:")
        print("     pip install awpy && awpy get tris")
        print("     (or copy de_dust2.tri from ~/.awpy/tris/)")
        print("  3. Register what you have:")
        print("     python scripts/setup_geometry_assets.py --map de_dust2 \\")
        print("         --nav data/maps/de_dust2.nav --tri data/maps/de_dust2.tri")
        print("  Full guide: docs/MANUAL_ASSET_SETUP.md")
        print("=" * 72)
    return registered


def check_status() -> dict:
    """Report which known maps have assets registered / on disk."""
    m = load_manifest()
    status = {}
    for name in KNOWN_MAPS:
        nav_ok = os.path.isfile(os.path.join(MAPS_DIR, f"{name}.nav"))
        tri_ok = os.path.isfile(os.path.join(MAPS_DIR, f"{name}.tri"))
        registered = name in m.get("assets", {})
        status[name] = {"nav": nav_ok, "tri": tri_ok, "registered": registered}
    return status


def main():
    ap = argparse.ArgumentParser(description="geometry asset setup")
    ap.add_argument("--auto", action="store_true",
                    help="download navs+tris from the awpy mirror")
    ap.add_argument("--map", default="", help="map name (de_dust2, ...); "
                                              "default: all known maps")
    ap.add_argument("--patch", default="", help="awpy build patch id (default: latest)")
    ap.add_argument("--list-known", action="store_true", help="list known maps")
    ap.add_argument("--check", action="store_true", help="report missing assets")
    ap.add_argument("--nav", default="", help="local path to .nav file (manual)")
    ap.add_argument("--tri", default="", help="local path to .tri file (manual)")
    ap.add_argument("--source", default="manual", help="asset source label")
    args = ap.parse_args()

    if args.list_known:
        print("known maps:", ", ".join(KNOWN_MAPS))
        return

    if args.check:
        st = check_status()
        missing = [n for n, s in st.items() if not (s["nav"] and s["tri"])]
        print("asset status:")
        for n, s in st.items():
            mark = "OK " if s["nav"] and s["tri"] else "MISS"
            print(f"  [{mark}] {n}: nav={'Y' if s['nav'] else 'N'} "
                  f"tri={'Y' if s['tri'] else 'N'} registered={s['registered']}")
        print(f"\nmissing: {', '.join(missing) if missing else 'none'}")
        print("run: python scripts/setup_geometry_assets.py --auto  to download")
        return

    if args.auto:
        maps = [args.map] if args.map else KNOWN_MAPS
        n = auto_download(maps, args.patch or None)
        print(f"\ndone: {n} assets registered in {MAPS_DIR}")
        if n == 0:
            sys.exit(1)
        return

    # manual registration
    if not args.map:
        print("error: --map required (or --auto / --check / --list-known)",
              file=sys.stderr)
        sys.exit(1)
    os.makedirs(MAPS_DIR, exist_ok=True)
    if args.nav:
        register_asset(args.map, "nav", os.path.abspath(args.nav), args.source)
    if args.tri:
        register_asset(args.map, "tri", os.path.abspath(args.tri), args.source)
    if not args.nav and not args.tri:
        print(f"no assets provided for {args.map}; place .nav/.tri in {MAPS_DIR} "
              "and re-run with --nav/--tri (see MANUAL_ASSET_SETUP.md)")


if __name__ == "__main__":
    main()
