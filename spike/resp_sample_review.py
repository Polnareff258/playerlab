"""Spec §56: sample-review the SELF_DECISION attributions to verify they are
defensible (not just 'that's how the player is')."""
import os
import sys
import json

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "core"))
from playerlab.db import DB  # noqa: E402

db = DB(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "playerlab.sqlite"))
ces = db.get_context_events("28959955a5ce1cb8", limit=5000)
deaths = [c for c in ces if c["anchor"] == "death"]

self_dec = [c for c in deaths if c["responsibility"] == "SELF_DECISION"]
shared = [c for c in deaths if c["responsibility"] == "SHARED"]

print(f"SELF_DECISION: {len(self_dec)} / SHARED: {len(shared)}")
print("\n=== SELF_DECISION sample (first 8) ===")
for c in self_dec[:8]:
    ts = c.get("temporal_summary") or {}
    print(f"t{c['tick']:>6} r{c['round']:>2} commit={c['commitment']:<20} "
          f"n_known={ts.get('n_known_enemies')} mate_dist={ts.get('nearest_teammate_dist')} "
          f"info={ts.get('information_strength')}/{ts.get('information_direction')} "
          f"trade={ (ts.get('tradeability') or {}).get('classification') }")
    print(f"    feasibility={c.get('feasibility')}")

print("\n=== SHARED sample (first 6) ===")
for c in shared[:6]:
    ts = c.get("temporal_summary") or {}
    print(f"t{c['tick']:>6} r{c['round']:>2} commit={c['commitment']:<20} "
          f"n_known={ts.get('n_known_enemies')} mate_dist={ts.get('nearest_teammate_dist')} "
          f"trade={ (ts.get('tradeability') or {}).get('classification') }")
