"""CS-NET real inference spike (spec §26/§27): run win_rate head on the real
de_dust2 demo and validate the output format + CPU latency."""
import os
import sys
import time
import json

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "external", "cs-net"))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, ".pylibs"))

DEMO = r"C:\Users\20646\Downloads\003777377368365072904_0970464162.dem"

import torch  # noqa: E402
from demoparser2 import DemoParser  # noqa: E402
from data.process_demo import get_important_ticks_by_round  # noqa: E402
from demoparser_utils.state_extract import extract_states_by_group  # noqa: E402
from demo_analysis.get_round_win_rate import (  # noqa: E402
    load_model_and_cfg, load_tokenizer_cfg, build_weapon_index,
    build_projectile_index, resolve_head_dirs, run_round_inference,
    build_batch, apply_temperature_scaling, process_round_json,
    build_round_ticks)

device = torch.device("cpu")
model_root = os.path.join(ROOT, "cs-net-models")

# 1) parse demo ticks (interval 0.25s -> ~4Hz)
t0 = time.time()
parser = DemoParser(DEMO)
ticks_by_round = get_important_ticks_by_round(parser, interval=0.25)
t_parse = time.time() - t0
print(f"parse ticks: {t_parse:.1f}s, rounds={len(ticks_by_round)}, ticks/round={[len(v) for k,v in sorted(ticks_by_round.items())[:3]]}")

# restrict to first 2 rounds for the spike
rounds = sorted(ticks_by_round.keys())[:2]
ticks_group = [ticks_by_round[r] for r in rounds]

t0 = time.time()
results_group = extract_states_by_group(DEMO, ticks_group)
t_state = time.time() - t0
print(f"extract states: {t_state:.1f}s, states/round={[len(g) for g in results_group]}")
print("state keys:", sorted(results_group[0][0].keys())[:20])

# 2) load win head only (spec §28: lazy per-head loading)
t0 = time.time()
model, cfg, ckpt = load_model_and_cfg(os.path.join(model_root, "win_rate"), device)
t_load = time.time() - t0
print(f"model load: {t_load:.1f}s")

tokenizer_cfg = load_tokenizer_cfg()
weapon2idx = build_weapon_index(tokenizer_cfg)
projectile2idx = build_projectile_index(tokenizer_cfg)

# 3) inference on the first round only
round_states = results_group[0]
t0 = time.time()
with torch.no_grad():
    batch = build_batch([round_states[0]], weapon2idx, projectile2idx, device)
    win_logits, _ = model({**batch, "label": torch.zeros(1, device=device)})
    win_logits = apply_temperature_scaling(win_logits, cfg)
    win_probs = torch.sigmoid(win_logits)
t1 = time.time()
print(f"single-tick inference: {(t1-t0)*1000:.0f}ms, win_prob={win_probs.item():.4f}")

# 4) full round inference (batch)
t0 = time.time()
models = {"win": model, "alive": None, "kill": None, "death": None, "duel": None}
cfgs = {"win": cfg, "alive": None, "kill": None, "death": None, "duel": None}
run_round_inference([round_states[0]], models, cfgs, weapon2idx, projectile2idx, device, 32)
t1 = time.time()
print(f"single-state run_round_inference: {(t1-t0)*1000:.0f}ms")

t0 = time.time()
run_round_inference(round_states, models, cfgs, weapon2idx, projectile2idx, device, 32)
t_full = time.time() - t0
print(f"full round ({len(round_states)} ticks) inference: {t_full:.1f}s, "
      f"{t_full/len(round_states)*1000:.0f}ms/tick")
print("sample state after inference:", {
    k: round(float(round_states[0].get(k, 0)), 4) if isinstance(round_states[0].get(k), float) else round_states[0].get(k)
    for k in ("ct_win_rate", "round_seconds", "map_name") if k in round_states[0]})

# 5) output format check (process_round_json)
out = process_round_json(round_states)
if isinstance(out, dict) and "error" in out:
    print("round json error:", out["error"])
else:
    print("round json type:", type(out), "len:", len(out) if hasattr(out, "__len__") else "?")
    if hasattr(out, "__len__") and len(out) > 0:
        first = out[0] if isinstance(out, list) else out
        print("round json sample:", json.dumps(first, ensure_ascii=False)[:400] if not isinstance(out, list) else json.dumps(out[0], ensure_ascii=False)[:400])

print("RESULT_PAYLOAD=", json.dumps({
    "parse_s": round(t_parse, 1), "state_s": round(t_state, 1),
    "model_load_s": round(t_load, 2), "single_tick_ms": round((t1-t0)*1000, 0) if False else None,
    "full_round_s": round(t_full, 2), "ticks": len(round_states),
    "win_prob_first_tick": round(win_probs.item(), 4),
}, ensure_ascii=False))
print("DONE")
