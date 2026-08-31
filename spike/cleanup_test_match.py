import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "core"))
from playerlab.config import Config
from playerlab.db import DB

db = DB(Config().resolve().db_path)
n = db.conn.execute("DELETE FROM matches WHERE demo_id='769f0ab22e8836df'").rowcount
db.conn.commit()
print(f"deleted {n} test-artifact match row; matches now: {len(db.list_matches())}")
