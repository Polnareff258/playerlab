"""Quick check: review queue content + context eval after V1.2 pipeline."""
import sys
import os
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "core"))
from playerlab.config import Config
from playerlab.db import DB

db = DB(Config().resolve().db_path)
items = db.get_review_queue(limit=30)
print("review items:", len(items))
print(Counter(i["item_type"] for i in items))
for i in items[:8]:
    print(f"  {i['priority']:.2f} {i['item_type']:<10} pred={i['model_prediction']:<14} "
          f"conf={i['model_confidence']} cands={i.get('candidates')}")
ces = db.get_context_events(limit=5000)
print("context events:", len(ces), "| intent:", Counter(c["intent"] for c in ces))
