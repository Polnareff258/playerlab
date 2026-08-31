"""Phase 1 audit helper: dump current DB schema + data distribution."""
import sys
import os
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "core"))
from playerlab.config import Config
from playerlab.db import DB

cfg = Config().resolve()
db = DB(cfg.db_path)
tables = [r[0] for r in db.conn.execute(
    "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
print("tables:", tables)
for t in tables:
    n = db.conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
    print(f"  {t}: {n} rows")
ms = db.list_matches()
print("matches:", len(ms))
if ms:
    mid = ms[0]["demo_id"]
    dps = db.get_dps(mid)
    acts = Counter(d["observed_action"] for d in dps)
    print("DP actions:", dict(acts))
    outs = Counter()
    for d in dps:
        o = db.get_outcome(d["dp_id"])
        if o:
            outs[("surv" if o["survival"] else "death", o["duel_result"])] += 1
    print("outcomes:", dict(outs))
    cov = db.get_coverage()
    print("coverage cells:", len(cov))
