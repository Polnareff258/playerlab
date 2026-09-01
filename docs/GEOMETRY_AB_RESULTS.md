# GEOMETRY_AB_RESULTS.md — Geometry ON/OFF A/B 实验（V1.3.3 PART I/J/S）

> **诚实状态：`GEOMETRY_AB_PENDING_ASSETS`（PART V）**
> 本版本完成了 A/B 实验**基础设施**（`ab_experiment.py`：OFF/ON 同批 demo 双跑、
> episode-level diff、experiment_id/config_hash/git_commit/demo_hash 复现元数据），
> 但**未跑完整实验**：de_dust2 / de_mirage 的 `.nav` + `.vphys` 资产未就绪
> （来源分散 + 大体积，遵循 PART H 不硬做自动下载）。
> 无资产时 AwpyGeometryProvider 返回 None → Geometry ON ≈ OFF → 实验无意义，
> 因此**不伪造 experiment**。资产就绪后按 §3 流程一键执行。

---

## 1. 实验基础设施（已交付）

| 能力 | 实现 | spec |
| --- | --- | --- |
| OFF/ON 双跑（唯一变量 = GeometryProvider） | `ab_experiment.diff_geometry_ab` | PART I §25 |
| episode-level diff（off/on label + sufficiency + reason_changed） | 同左 | §27 |
| sufficiency upgrade rate（MEDIUM→HIGH 等） | 同左 | §28 |
| decision flips（GOOD→QUESTIONABLE 等） | 同左 | §29 |
| human-agreement check（OFF vs ON vs HUMAN） | `_agrees` | PART J §30 |
| 复现元数据（experiment_id/config_hash/git_commit/demo_hash/geometry_version/detector_version） | `experiment_runs` 表 | PART S |
| 命令 | `python -m playerlab.cli geometry-ab <demo.dem> [--out diff.json]` | - |

## 2. 未跑实验的原因（诚实）

1. **资产缺失**：`data/maps/` 空（de_dust2/de_mirage 的 .nav/.vphys 未放置）。
2. **无资产 → 双跑等价**：AwpyGeometryProvider 无资产时全部返回 None，
   Geometry ON 与 OFF 的 episode 输出一致 → diff 全为 unchanged → 无信息。
   跑了会产出**无意义且误导**的结果，故不跑。
3. **不伪造**：`GEOMETRY_AB_PENDING_ASSETS` 是诚实输出（PART V）。

## 3. 资产就绪后执行流程

```powershell
# 1. 放置资产 + 注册 metadata（见 MANUAL_ASSET_SETUP.md）
python scripts\setup_geometry_assets.py --map de_dust2 --nav data\maps\de_dust2.nav --vphys data\maps\de_dust2.vphys
python scripts\setup_geometry_assets.py --map de_mirage --nav data\maps\de_mirage.nav --vphys data\maps\de_mirage.vphys
# 2. 配置启用 awpy
# config geometry_provider=awpy, geometry_nav_dir=data/maps, geometry_tri_dir=data/maps
# 3. 跑 A/B（6 场 3 de_dust2 + 3 de_mirage，或先单图）
python -m playerlab.cli geometry-ab "SampleDemo\g161-20260828202750949889581_de_dust2.dem" --out backtest\ab_dust2_a.json
python -m playerlab.cli geometry-ab "SampleDemo\g161-20260715213814336074130_de_mirage.dem" --out backtest\ab_mirage_a.json
# 4. 关注（PART J §30）：不是 confidence 变高，而是 human agreement 是否提高
```

## 4. 预期关注点（资产就绪后）

- `sufficiency_upgrades`：MEDIUM→HIGH 比例（几何加分生效）
- `decision_flips`：哪些判定实质改变（vs 仅 confidence 微调）
- `human_agreement`：OFF vs ON 与 HUMAN 标签的一致性 —— **若 ON 增加 confidence
  但 human agreement 未增 → 输出 `NO_VALIDATED_ACCURACY_GAIN`**（PART E Scenario E）
- `change_rate`：episodes_changed / total（判断几何影响面）

## 5. 已知限制（诚实）

1. awpy `is_visible` 纯几何（无烟雾/闪光遮挡）→ quality=approximate。
2. nav distance 是路径近似；`find_closest_area` 对非 nav 位置有误差。
3. 资产版本随 CS2 更新漂移 → manifest.json 哈希用于复现性排查。
4. 本实验只验证**几何是否改善判断**，最终正确性仍需 HUMAN label（PART J）。
