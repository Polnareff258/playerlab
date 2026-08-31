import sqlite3
c = sqlite3.connect("data/playerlab.sqlite"); c.row_factory = sqlite3.Row
tables = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
print("tables:", tables)
for t in ("matches", "context_events", "intent_samples", "review_queue"):
    if t in tables:
        n = c.execute(f"SELECT COUNT(*) c FROM {t}").fetchone()["c"]
        print(t, n)
if "matches" in tables:
    rows = c.execute("SELECT * FROM matches LIMIT 5").fetchall()
    for r in rows:
        print(dict(r))
if "context_events" in tables:
    from collections import Counter
    rows = c.execute("SELECT responsibility FROM context_events").fetchall()
    print("responsibility dist:", dict(Counter(r["responsibility"] for r in rows)))
