"""Sanitize spike/golden_alpha.json: strip steamids from dp_id/event_id."""
import json
import os
import re

path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "spike", "golden_alpha.json")
with open(path, "r", encoding="utf-8") as fh:
    data = json.load(fh)

STEAMID_RE = re.compile(r"-76\d{9,}-")


def scrub(s):
    if isinstance(s, str):
        return STEAMID_RE.sub("-P-", s)
    return s


for rec in data:
    for key in ("dp_id", "event_id"):
        if key in rec:
            rec[key] = scrub(rec[key])

with open(path, "w", encoding="utf-8") as fh:
    json.dump(data, fh, ensure_ascii=False, indent=1, default=str)
print("sanitized", len(data), "golden samples; steamid scan:",
      any(re.search(r"76\d{9}", json.dumps(rec)) for rec in data))
