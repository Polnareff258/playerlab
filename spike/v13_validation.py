"""V1.3 real-demo validation: run episode pipeline on the real de_dust2 demo,
record family/evaluation/actionability/candidate distributions."""
import os
import sys
import json
import time
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "core"))

from playerlab.config import Config
from playerlab.db import DB
from playerlab.ingest import parse_demo
from playerlab.episode import run_episodes
from playerlab.episode_patterns import cluster_episodes
from playerlab.training import generate_targets_from_episodes
from playerlab.alpha import run_alpha

DEMO = r"C:\Users\20646\Downloads\003777377368365072904_0970464162.dem"
cfg = Config().resolve()
db = DB(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "playerlab.sqlite"))

# full alpha (includes episodes now) but we time episodes separately
demo = parse_demo(DEMO, cfg)
t0 = time.time()
alpha_result = run_alpha(demo, cfg, db)
print(f"alpha total: {time.time()-t0:.1f}s")
print("episodes result:", alpha_result.get("episodes"))

# distributions
eps = db.get_decision_episodes(demo.demo_id)
print(f"\nepisodes: {len(eps)}")
print("family dist:", dict(Counter(e["family"] for e in eps)))
print("evaluation dist:", dict(Counter(e["decision_evaluation"] for e in eps)))
print("actionability dist:", dict(Counter(e["actionability"] for e in eps)))
print("observed dist:", dict(Counter(e["observed_action"] for e in eps)))

# candidates
from playerlab.db import DB as _DB
cands = []
for e in eps:
    cands += db.get_decision_candidates(e["id"])
feas = Counter(c["feasibility"] for c in cands)
print("\ncandidates:", len(cands), "feasibility:", dict(feas))

# example episodes
print("\n=== example episodes ===")
for e in eps[:5]:
    m = e["macro_context"] or {}
    print(f"{e['id'][-30:]} fam={e['family']} obs={e['observed_action']} "
          f"eval={e['decision_evaluation']} act={e['actionability']} "
          f"adv={m.get('advantage_state')} risk={m.get('risk_tolerance')} "
          f"need_info={m.get('need_for_information')}")

# patterns + targets
patterns = cluster_episodes(db, cfg)
print("\npatterns:")
for p in patterns:
    print(f"  {p['pattern_id']}: n={p['sample_count']} rate={p['violation_rate']} "
          f"eligible={p['eligible']} actionable_share={p['actionability_share']}")
targets = generate_targets_from_episodes(db, cfg, patterns)
print("targets from episodes:", [t["target_id"] for t in targets])

out = {
    "episodes": len(eps),
    "family": dict(Counter(e["family"] for e in eps)),
    "evaluation": dict(Counter(e["decision_evaluation"] for e in eps)),
    "actionability": dict(Counter(e["actionability"] for e in eps)),
    "observed": dict(Counter(e["observed_action"] for e in eps)),
    "candidate_feasibility": dict(feas),
    "patterns": [{"id": p["pattern_id"], "n": p["sample_count"],
                  "rate": p["violation_rate"], "eligible": p["eligible"]}
                 for p in patterns],
}
with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backtest",
                       "v13_validation.json"), "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=2)
print("\nsaved v13_validation.json")
print(json.dumps(out, ensure_ascii=False))
