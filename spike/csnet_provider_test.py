"""Phase H acceptance: CSNetProvider returns a real win_probability via
GameModelProvider, with proper ModelEvidence schema + ground-truth scope."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "core"))

from playerlab.csnet import CSNetProvider  # noqa: E402
from playerlab.model_provider import get_provider, ModelEvidence  # noqa: E402

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "external", "cs-net"))
MODELS = os.path.join(REPO, "cs-net-models")

prov = CSNetProvider(repo_dir=REPO, models_dir=MODELS, device="cpu")
meta = prov.get_metadata()
print("metadata:", meta)
assert meta["status"] == "ready", meta
print("tasks:", prov.get_supported_tasks())

# minimal CS-NET-compatible state (single tick, 10 players, dust2)
import math
players = []
for i in range(10):
    players.append({
        "steamid": 1000 + i, "X": -199.0 + i * 50, "Y": 977.0 + i * 30, "Z": 32.0,
        "pitch": 0.0, "yaw": 0.0, "health": 100, "armor": 100,
        "has_helmet": True, "has_defuser": False, "flash_duration": 0.0,
        "team_num": "CT" if i < 5 else "T",
        "velocity": 0.0, "velocity_X": 0.0, "velocity_Y": 0.0, "velocity_Z": 0.0,
        "inventory": ["AK-47" if i < 5 else "M4A4", "knife"],
        "is_alive": True,
    })
state = {"map_name": "de_dust2", "tick": 1000, "round": 3, "round_seconds": 30.0,
         "players_info": players,
         "bomb_position": None, "is_bomb_planted": False, "is_bomb_dropped": False,
         "bomb_planted_duration": 0.0, "projectiles": [], "entity_grenades": []}

ev = prov.predict_win_probability(state, match_id="m1", round=3, tick=1000)
print("evidence:", ev.to_dict())
assert isinstance(ev, ModelEvidence)
assert ev.task == "win_rate"
assert ev.prediction is not None and 0.0 <= ev.prediction <= 1.0, ev
assert ev.state_scope == "GROUND_TRUTH_STATE", ev.state_scope
assert ev.provider == "csnet" and ev.calibrated is True
print(f"WIN_PROBABILITY={ev.prediction:.4f}")

# factory path (spec §62): get_provider('csnet') builds CSNetProvider
prov2 = get_provider("csnet", repo_dir=REPO, models_dir=MODELS)
print("factory provider:", type(prov2).__name__, prov2.get_metadata()["status"])
assert type(prov2).__name__ == "CSNetProvider"

# failure isolation: bad models dir -> unavailable evidence, no crash
prov3 = CSNetProvider(repo_dir=REPO, models_dir="/nonexistent", device="cpu")
ev3 = prov3.predict_win_probability(state)
print("missing-weights evidence:", ev3.to_dict()["prediction"], ev3.to_dict()["evidence_type"])
assert ev3.prediction is None and ev3.evidence_type == "unavailable"

print("PHASE_H_ACCEPTANCE=TRUE")
