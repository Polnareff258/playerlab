"""V1.3.1 real-demo validation: engagement + duel + execution layers."""
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
from playerlab.alpha import run_alpha

DEMO = r"C:\Users\20646\Downloads\003777377368365072904_0970464162.dem"
cfg = Config().resolve()
db = DB(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "playerlab.sqlite"))

demo = parse_demo(DEMO, cfg)
t0 = time.time()
alpha_result = run_alpha(demo, cfg, db)
print(f"alpha total: {time.time()-t0:.1f}s")
print("episodes:", alpha_result.get("episodes"))

eps = db.get_decision_episodes(demo.demo_id)
print(f"\nepisodes: {len(eps)}")

# engagement methods
methods = Counter()
for e in eps:
    em = (e.get("engagement_method") or {})
    m = em.get("method")
    if m:
        methods[m] += 1
print("engagement methods:", dict(methods))

# duel / execution
n_duel = sum(1 for e in eps if e.get("duel_state_sequence"))
print("with duel sequence:", n_duel)
phases = Counter()
for e in eps:
    p = e.get("duel_phase")
    if p:
        phases[p] += 1
print("duel phases:", dict(phases))

prims = Counter()
for e in eps:
    for p in (e.get("execution_primitives") or []):
        prims[p] += 1
print("execution primitives:", dict(prims))

me_dist = Counter()
for e in eps:
    me = (e.get("movement_effect") or {})
    if me:
        me_dist[me.get("self_accuracy_cost")] += 1
print("self accuracy cost:", dict(me_dist))

# three-level evaluations
print("\nstrategic:", dict(Counter(e.get("strategic_evaluation") for e in eps)))
print("engagement:", dict(Counter(e.get("engagement_evaluation") for e in eps)))
print("execution:", dict(Counter(e.get("execution_evaluation") for e in eps)))
print("sufficiency:", dict(Counter(e.get("evidence_sufficiency") for e in eps)))

# examples
print("\n=== examples with duel ===")
shown = 0
for e in eps:
    if e.get("duel_state_sequence") and shown < 6:
        m = e.get("macro_context") or {}
        wm = e.get("weapon_matchup") or {}
        me = e.get("movement_effect") or {}
        em = (e.get("engagement_method") or {})
        print(f"{e['family']:<24} obs={e['observed_action']:<10} method={em.get('method','-'):<14} "
              f"strat={e.get('strategic_evaluation'):<10} eng={e.get('engagement_evaluation'):<10} "
              f"exec={e.get('execution_evaluation'):<10} suffic={e.get('evidence_sufficiency'):<6}")
        print(f"    matchup={wm.get('self_weapon_class')} vs {wm.get('enemy_weapon_class')} "
              f"@{wm.get('range_bucket')} | prim={e.get('execution_primitives')} "
              f"| mov_eff self_acc={me.get('self_accuracy_cost')} opp_track={me.get('estimated_opponent_tracking_difficulty')}")
        shown += 1

out = {
    "episodes": len(eps),
    "engagement_methods": dict(methods),
    "n_duel": n_duel,
    "duel_phases": dict(phases),
    "execution_primitives": dict(prims),
    "self_accuracy_cost": dict(me_dist),
    "strategic": dict(Counter(e.get("strategic_evaluation") for e in eps)),
    "engagement_eval": dict(Counter(e.get("engagement_evaluation") for e in eps)),
    "execution_eval": dict(Counter(e.get("execution_evaluation") for e in eps)),
    "sufficiency": dict(Counter(e.get("evidence_sufficiency") for e in eps)),
}
with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backtest",
                       "v131_validation.json"), "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=2)
print("\nsaved v131_validation.json")
