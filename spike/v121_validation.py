"""V1.2.1 real-demo validation (spec §55/§56): re-run the context pipeline on
the real de_dust2 demo with KnownState grounding + conservative responsibility
gate; record distributions before/after."""
import os
import sys
import json
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "core"))

from playerlab.config import Config  # noqa: E402
from playerlab.db import DB  # noqa: E402
from playerlab.ingest import parse_demo  # noqa: E402
from playerlab.context_pipeline import run_context  # noqa: E402
from playerlab.alpha import run_alpha  # noqa: E402

DEMO = r"C:\Users\20646\Downloads\003777377368365072904_0970464162.dem"
cfg = Config().resolve()
db = DB(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "playerlab.sqlite"))

t0 = time.time()
demo = parse_demo(DEMO, cfg)
print(f"parse: {time.time()-t0:.1f}s")

t0 = time.time()
alpha_result = run_alpha(demo, cfg, db)
print(f"alpha: {time.time()-t0:.1f}s")

t0 = time.time()
result = run_context(demo, cfg, db)
print(f"context: {time.time()-t0:.1f}s")

# distributions
from collections import Counter
ces = db.get_context_events(demo.demo_id, limit=5000)
deaths = [c for c in ces if c["anchor"] == "death"]
resp_dist = Counter(c["responsibility"] for c in deaths)
print("responsibility (deaths):", dict(resp_dist))
n = len(deaths)
if n:
    self_share = resp_dist.get("SELF_DECISION", 0) / n
    print(f"SELF_DECISION share: {self_share:.1%} ({resp_dist.get('SELF_DECISION')}/{n})")

intent_dist = Counter(s["rule_prediction"] for s in db.get_intent_samples(demo.demo_id))
print("intent distribution:", dict(intent_dist))

# information features coverage on intent samples
samples = db.get_intent_samples(demo.demo_id)
with_info = sum(1 for s in samples if (s.get("information_features") or {}).get("strength", "NONE") != "NONE")
with_ks = sum(1 for s in samples if (s.get("player_known_state") or {}).get("n_known_enemies", 0) >= 0 and s.get("player_known_state"))
print(f"intent samples: {len(samples)}, with known_state: {with_ks}, with non-NONE info strength: {with_info}")

# tradeability classification on death anchors
trade_dist = Counter()
unknown_trade = 0
for c in deaths:
    t = (c.get("temporal_summary") or {}).get("tradeability") or {}
    if t:
        trade_dist[t.get("classification", "?")] += 1
        if t.get("classification") == "UNKNOWN":
            unknown_trade += 1
print("tradeability (deaths):", dict(trade_dist))

# review queue quota
from playerlab.annotation import build_review_queue
queue = build_review_queue(db, cfg, demo.demo_id)
qtypes = Counter(i["item_type"] for i in queue)
print("review queue:", dict(qtypes), "total", len(queue))

out = {
    "context_events": len(ces), "deaths": n,
    "responsibility": dict(resp_dist),
    "self_decision_share": round(self_share, 4) if n else None,
    "intent": dict(intent_dist),
    "samples_with_known_state": with_ks,
    "samples_with_info": with_info,
    "tradeability": dict(trade_dist),
    "review_queue": dict(qtypes),
    "review_total": len(queue),
}
with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backtest", "v121_validation.json"), "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=2)
print("saved v121_validation.json")
print(json.dumps(out, ensure_ascii=False))
