"""Quick DB/alpha state check (dev helper)."""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "core"))
from playerlab.config import Config
from playerlab.db import DB

db = DB(Config().resolve().db_path)
print("schema_version:", db.schema_version())
tables = [r[0] for r in db.conn.execute(
    "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
print("tables:", tables)
for t in ("execution_metrics", "patterns", "root_causes", "training_targets",
          "human_annotations", "review_queue"):
    n = db.conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
    print(f"  {t}: {n}")
