"""Demo: run what-if on a PEEK at zone A (same-match mode for single demo)."""
import sys

sys.path.insert(0, "core")
from playerlab.config import Config
from playerlab.db import DB
from playerlab.counterfactual import what_if

cfg = Config().resolve()
db = DB(cfg.db_path)
dps = db.get_dps("28959955a5ce1cb8")
import collections
zones = collections.Counter((d["observed_action"], d["zone"]) for d in dps)
print("DP distribution (action, zone):")
for k, v in sorted(zones.items()):
    print(f"  {k}: {v}")

peek = next(d for d in dps if d["observed_action"] == "PEEK" and d["zone"] == "A")
print(f"\nquery: {peek['dp_id']} zone={peek['zone']}")
r = what_if(db, cfg, peek["dp_id"], include_same=True)
print("verdict:", r["verdict"], "| confidence:", r["evidence_strength"]["confidence"])
for a, s in r["actions"].items():
    print(f"  {a}: n={s['n']} surv={s['survival']:.2f} "
          f"[{s['survival_ci'][0]:.2f},{s['survival_ci'][1]:.2f}] "
          f"rw={s['round_win']:.2f} duel={s['duel']}")
for c in r["comparisons"]:
    print(f"  cmp: {c['observed']} vs {c['alternative']} -> {c['note'] or 'difference'}")
