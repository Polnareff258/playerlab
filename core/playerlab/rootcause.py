"""Alpha simplified Root Cause Chain (spec §6): Result -> Execution -> Micro
-> Macro, any layer may be UNKNOWN. Primary = most-upstream layer with
confidence & trainability above thresholds, falling back downstream.
"""
from __future__ import annotations

from .config import Config
from .db import DB
from .ingest import IngestedDemo

LAYERS = ("macro", "micro", "execution")


def build_root_causes(demo: IngestedDemo, cfg: Config, db: DB,
                      idx: dict, advantage_samples: list[dict],
                      responsibility_map: dict | None = None,
                      commitment_map: dict | None = None,
                      role_map: dict | None = None) -> list[dict]:
    players = {p["steamid"] for p in demo.players}
    metrics = db.get_execution_metrics(demo.demo_id)
    dps = db.get_dps(demo.demo_id)
    death_t = {}
    for k in demo.events["kills"]:
        sid = k.get("user_steamid")
        if sid is None or int(sid) not in players:
            continue
        # round 0 = warmup/knife — not a real round (cs-demo-manager)
        if demo.round_of_tick(k["tick"]) < 1:
            continue
        death_t[int(k["tick"])] = int(sid)
    adv_by_player_tick = {(s["steamid"], s["tick"]): s for s in advantage_samples}

    out = []
    for tick, steamid in sorted(death_t.items()):
        # Execution layer: move-and-shoot near the death
        exec_hit = [m for m in metrics
                    if m["steamid"] == steamid and m["violation"]
                    and tick - 24 <= m["tick"] <= tick + 8]
        execution = "MOVE_AND_SHOOT" if exec_hit else None
        exec_conf = max((m.get("meta", {}).get("__conf", 0.9) for m in exec_hit), default=0.0) \
            if exec_hit else 0.0

        # Micro layer: DP covering the death
        micro_dp = next((d for d in dps
                         if d["steamid"] == steamid
                         and d["start_tick"] <= tick <= d["end_tick"] + 96), None)
        if micro_dp and micro_dp["observed_action"] == "RE_PEEK":
            micro = "IMMEDIATE_REPEEK"
        elif micro_dp:
            micro = micro_dp["observed_action"]
        else:
            micro = None
        micro_conf = micro_dp["confidence"] if micro_dp else 0.0

        # Macro layer: advantage overaggression covering the death
        adv_hit = [s for (s_, t_), s in adv_by_player_tick.items()
                   if s_ == steamid and adv_by_player_tick[(s_, t_)]["tick"] <= tick
                   and tick - adv_by_player_tick[(s_, t_)]["tick"] <= 128
                   and s["classification"] == "POSSIBLE_ADVANTAGE_OVERAGGRESSION"]
        macro = "ADVANTAGE_OVERAGGRESSION" if adv_hit else None
        macro_conf = max((s["confidence"] for s in adv_hit), default=0.0)

        layers = {"macro": (macro, macro_conf), "micro": (micro, micro_conf),
                  "execution": (execution, exec_conf)}
        primary = None
        for layer in LAYERS:
            name, conf = layers[layer]
            if name and conf >= 0.55 and cfg.trainability.get(
                    _train_key(name), 0.0) >= 0.6:
                primary = name
                break
        if primary is None:
            for layer in ("micro", "execution"):
                name, conf = layers[layer]
                if name and conf >= 0.5:
                    primary = name
                    break
        if primary is None:
            primary = "UNKNOWN"
        secondary = next((layers[l][0] for l in LAYERS
                          if layers[l][0] and layers[l][0] != primary and layers[l][1] >= 0.4),
                         None)

        key = (steamid, tick)
        resp = (responsibility_map or {}).get(key) or {}
        out.append({
            "event_id": f"{demo.demo_id}-death-{steamid}-{tick}",
            "match_id": demo.demo_id, "round": demo.round_of_tick(tick),
            "tick": tick, "steamid": steamid,
            "result": "Death",
            "execution": execution, "micro": micro, "macro": macro,
            "primary_cause": primary, "secondary_cause": secondary,
            "mechanical_cause": execution,
            "confidence": round(max(exec_conf, micro_conf, macro_conf), 3),
            "context": "TemporalContext(4s)",
            "commitment": (commitment_map or {}).get(key) or resp.get("commitment"),
            "role": (role_map or {}).get(key),
            "responsibility": resp.get("attribution"),
        })
    return out


def _train_key(layer_name: str) -> str:
    if layer_name == "IMMEDIATE_REPEEK":
        return "repeek"
    if layer_name == "MOVE_AND_SHOOT":
        return "move_shoot"
    if layer_name == "ADVANTAGE_OVERAGGRESSION":
        return "advantage"
    return "repeek"
