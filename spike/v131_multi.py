"""Multi-match aggregation (spec §77/§105): after batch, summarize decision
episode distributions across all matches + episode patterns -> targets."""
import os
import sys
import json
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "core"))

from playerlab.config import Config
from playerlab.db import DB
from playerlab.episode_patterns import cluster_episodes
from playerlab.training import generate_targets_from_episodes

cfg = Config().resolve()
db = DB(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "playerlab.sqlite"))

matches = db.list_matches()
print(f"matches in DB: {len(matches)}")
for m in matches:
    print(f"  {m['demo_id'][:12]} {m['map_name']:<10} {m['rounds_total']}r {m['parsed_at']}")

# per-match episode stats
print("\n=== per-match ===")
family_tot = Counter()
eval_tot = Counter()
act_tot = Counter()
method_tot = Counter()
prim_tot = Counter()
suffic_tot = Counter()
all_eps = []
for m in matches:
    eps = db.get_decision_episodes(match_id=m["demo_id"], limit=3000)
    if not eps:
        continue
    all_eps.extend(eps)
    fam = Counter(e["family"] for e in eps)
    ev = Counter(e.get("strategic_evaluation") for e in eps)
    act = Counter(e.get("actionability") for e in eps)
    print(f"  {m['map_name']:<10} eps={len(eps):>3} fam={dict(fam)} "
          f"strat={dict(ev)} act={dict(act)}")
    for e in eps:
        fam_key = e["family"]
        family_tot[fam_key] += 1
        eval_tot[e.get("strategic_evaluation")] += 1
        act_tot[e.get("actionability")] += 1
        suffic_tot[e.get("evidence_sufficiency")] += 1
        em = (e.get("engagement_method") or {}).get("method")
        if em:
            method_tot[em] += 1
        for p in (e.get("execution_primitives") or []):
            prim_tot[p] += 1

print("\n=== totals ===")
print("family:", dict(family_tot))
print("strategic:", dict(eval_tot))
print("actionability:", dict(act_tot))
print("sufficiency:", dict(suffic_tot))
print("engagement methods:", dict(method_tot))
print("execution primitives:", dict(prim_tot))

# episode patterns across all matches -> training targets (spec 102-G)
print("\n=== episode patterns (all matches) ===")
patterns = cluster_episodes(db, cfg)
for p in patterns:
    print(f"  {p['pattern_id']}: n={p['sample_count']} rate={p['violation_rate']} "
          f"eligible={p['eligible']} actionable={p['actionability_share']}")
targets = generate_targets_from_episodes(db, cfg, patterns)
print("targets from episodes:", [t["target_id"] for t in targets])

out = {
    "matches": len(matches),
    "family": dict(family_tot), "strategic": dict(eval_tot),
    "actionability": dict(act_tot), "sufficiency": dict(suffic_tot),
    "methods": dict(method_tot), "primitives": dict(prim_tot),
    "patterns": [{"id": p["pattern_id"], "n": p["sample_count"],
                  "rate": p["violation_rate"], "eligible": p["eligible"]}
                 for p in patterns],
    "targets": [t["target_id"] for t in targets],
}
with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backtest",
                       "v131_multi_match.json"), "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=2)
print("\nsaved v131_multi_match.json")
