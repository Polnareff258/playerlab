"""Quick GitHub search for counter-strafe / counterstrafe projects (research)."""
import json
import os
import subprocess
import urllib.parse
import urllib.request

token = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True).stdout.strip()


def search(q, per_page=6):
    url = "https://api.github.com/search/repositories?q=" + urllib.parse.quote(q) + f"&per_page={per_page}"
    req = urllib.request.Request(url, headers={"Authorization": f"token {token}",
                                               "Accept": "application/vnd.github+json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.load(r)
    except Exception as e:  # noqa: BLE001
        return [("ERR", str(e))]
    out = []
    for it in data.get("items", []):
        lic = (it.get("license") or {}).get("spdx_id") or "none"
        out.append(f"{it['full_name']} | {lic} | ★{it['stargazers_count']} | {it.get('pushed_at','')} | {(it.get('description') or '')[:90]}")
    return out


for q in ["counter-strafe cs2", "counterstrafe counter-strike", "cs2 counter strafe analysis"]:
    print(f"=== {q} ===")
    for line in search(q):
        print(" ", line)
