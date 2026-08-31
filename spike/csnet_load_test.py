"""CS-NET model load smoke test: load win_rate head on CPU."""
import os
import sys
import time

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "external", "cs-net"))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, ".pylibs"))

import torch  # noqa: E402

from models.model3_space_only import CSModelV3  # noqa: E402
from demo_analysis.get_round_win_rate import load_model_and_cfg  # noqa: E402

t0 = time.time()
device = torch.device("cpu")
model, cfg, ckpt = load_model_and_cfg(os.path.join(ROOT, "cs-net-models/win_rate"), device)
t1 = time.time()
print(f"loaded {ckpt} in {t1-t0:.1f}s")
n_params = sum(p.numel() for p in model.parameters())
print(f"params: {n_params/1e6:.1f}M")
print("task:", cfg["task"])
print("OK")
