"""CS-NET full-demo benchmark (spec §41): parse time, state extraction time,
model load, CPU/GPU inference, memory. Runs win_rate + alive + duel heads
over the full real demo (18 rounds)."""
import os
import sys
import time
import json

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "external", "cs-net"))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, ".pylibs"))

DEMO = r"C:\Users\20646\Downloads\003777377368365072904_0970464162.dem"

import torch  # noqa: E402
import psutil  # noqa: E402
from demoparser2 import DemoParser  # noqa: E402
from data.process_demo import get_important_ticks_by_round  # noqa: E402
from demoparser_utils.state_extract import extract_states_by_group  # noqa: E402
from demo_analysis.get_round_win_rate import (  # noqa: E402
    load_model_and_cfg, load_tokenizer_cfg, build_weapon_index,
    build_projectile_index, run_round_inference, apply_temperature_scaling,
    resolve_head_dirs, compute_duel_matrix)

device = torch.device("cpu")
model_root = os.path.join(ROOT, "cs-net-models")

demo_mb = os.path.getsize(DEMO) / 1e6

t0 = time.time()
parser = DemoParser(DEMO)
ticks_by_round = get_important_ticks_by_round(parser, interval=0.25)
t_parse = time.time() - t0
total_ticks = sum(len(v) for v in ticks_by_round.values())
print(f"[bench] parse: {t_parse:.1f}s demo={demo_mb:.1f}MB rounds={len(ticks_by_round)} ticks={total_ticks}")

ticks_group = [ticks_by_round[r] for r in sorted(ticks_by_round.keys())]
t0 = time.time()
results_group = extract_states_by_group(DEMO, ticks_group)
t_state = time.time() - t0
print(f"[bench] state extraction: {t_state:.1f}s states={sum(len(g) for g in results_group)}")

# load heads: win (required), then alive + duel lazily (spec §28)
t0 = time.time()
models, cfgs = {}, {}
for key, head in (("win", "win_rate"), ("alive", "alive"), ("duel", "duel")):
    tt = time.time()
    model, cfg, ckpt = load_model_and_cfg(os.path.join(model_root, head), device)
    models[key] = model
    cfgs[key] = cfg
    print(f"[bench] load {head}: {time.time()-tt:.1f}s params={sum(p.numel() for p in model.parameters())/1e6:.1f}M")
t_load = time.time() - t0

tokenizer_cfg = load_tokenizer_cfg()
weapon2idx = build_weapon_index(tokenizer_cfg)
projectile2idx = build_projectile_index(tokenizer_cfg)

proc = psutil.Process(os.getpid())
ram0 = proc.memory_info().rss / 1e6

t0 = time.time()
n_ticks_run = 0
for idx, round_id in enumerate(sorted(ticks_by_round.keys())):
    round_states = results_group[idx]
    if not round_states:
        continue
    run_round_inference(round_states, models, cfgs, weapon2idx, projectile2idx, device, 128)
    n_ticks_run += len(round_states)
t_infer = time.time() - t0
ram1 = proc.memory_info().rss / 1e6

print(f"[bench] inference ({models.keys()} heads): {t_infer:.1f}s over {n_ticks_run} ticks = "
      f"{t_infer/n_ticks_run*1000:.1f}ms/tick")
print(f"[bench] RAM: {ram0:.0f}MB (post-load) -> {ram1:.0f}MB (post-infer), +{(ram1-ram0):.0f}MB")
print(f"[bench] VRAM: 0 (CPU-only)")

# check a sample win rate curve exists
first_round = results_group[0]
print(f"[bench] first-round ticks={len(first_round)} win_rate@0={first_round[0].get('ct_win_rate')}")
win_rates = [s.get("ct_win_rate") for s in first_round if s.get("ct_win_rate") is not None]
print(f"[bench] win_rate sample: n={len(win_rates)} first={win_rates[0]:.3f} last={win_rates[-1]:.3f}")

print(json.dumps({
    "demo_size_mb": round(demo_mb, 1),
    "parse_s": round(t_parse, 1),
    "state_extract_s": round(t_state, 1),
    "model_load_s": round(t_load, 2),
    "cpu_inference_ms_per_tick": round(t_infer / max(1, n_ticks_run) * 1000, 2),
    "total_ticks": n_ticks_run,
    "ram_mb": round(ram1 - ram0, 0),
    "vram_mb": 0,
    "heads": list(models.keys()),
    "device": "cpu",
}, ensure_ascii=False))
print("DONE")
