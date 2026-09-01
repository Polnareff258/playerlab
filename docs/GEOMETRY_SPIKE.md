# GEOMETRY_SPIKE.md — V1.3.2 几何能力调查结论（PART F §30-§33）

> 目的：调查成熟 LOS / nav / cover 方案，决定 GeometryProvider 的接入路径。
> 结论前置：**本轮不引入新依赖** —— GeometryProvider 接口 + Null 已落地，
> awpy 适配器（AwpyGeometryProvider）已写好但默认不启用（无地图资产）。
> 与 docs/LOS_NAV_SPIKE.md（V1.2.1）结论一致：awpy 是唯一同时提供
> nav distance + point-to-point visibility 且 MIT 的成熟方案。

---

## 1. 调查的成熟工具

| 项目 | 能力 | License | 结论 |
| --- | --- | --- | --- |
| **awpy**（pnxenopoulos/awpy） | `NavMesh.from_path`（.nav 解析 + find_path A*）+ `visibility`（VPhys KV3 → BVH → `is_visible` raycast） | MIT | ✅ **首选**：nav_distance + LOS + cover 近似全覆盖；610★ 活跃维护（2026-08 仍更新） |
| DAK Studio / DAK packages | 分析 substrate；nav 能力 | 闭源/部分 | ❌ 无 Python API 可复用 |
| Freezetime | demoparser2 生态事件分析 | MIT | ❌ 无 nav 几何 |
| demoparser2 | Rust 解析核心 | MIT | ❌ 明确不含 geometry（解析层 ≠ 几何层） |
| cs2-map-parser | CS2 碰撞网格解析（awpy 的底层参考） | MIT | ✅ awpy 已内置等价能力，无需单独接 |

## 2. 能力对照（PART F §31 接口）

| GeometryProvider 方法 | awpy 能力 | 本阶段（Null） |
| --- | --- | --- |
| `can_see(a, b)` | `is_visible(VPhys BVH)` | None（诚实 UNKNOWN） |
| `nav_distance(a, b)` | `NavMesh.find_path` 距离 | None |
| `has_cover(a, b)` | LOS blocked → cover 近似 | None |
| `trade_geometry` | 组合 LOS + distance | 组合 None |

## 3. 接入成本

1. **资产**：每图需要 `.nav`（1-3MB）+ `.vphys` 碰撞网格（de_dust2 ~50-120MB）；6 图合计 ~500MB+。
2. **安装**：`pip install awpy`（numpy/pandas/loguru，无 torch）；已隔离到 optional（不进 core requirements）。
3. **适配**：`AwpyGeometryProvider` 已写好（lazy load + 错误降级 None）；注入路径 = `get_geometry("awpy", nav_dir=..., tri_dir=...)`。
4. **运行时**：BVH 构建一次性 5-15s/图；查询 ~0.05-0.5ms；批处理友好。

## 4. 限制（诚实）

- CS2 更新会改变 nav 版本 → 需随版本锁定资产（同 LOS_NAV_SPIKE 结论）。
- `m_flDuckAmount` 等部分 SourceTV 字段缺失 → cover 无法用玩家姿态精确判定。
- awpy `is_visible` 是纯几何（不含烟雾/闪光遮挡）→ 标注 approximate（spec §33 禁止假精确度）。

## 5. 本轮决策

- **GeometryProvider 接口 + NullGeometryProvider 已实现**（`geometry.py`）：core 零依赖，EvidenceSufficiency 维持 MEDIUM/LOW（无几何诚实降级，spec §32/G）。
- **AwpyGeometryProvider 已实现但默认关闭**：`config.geometry_provider="null"`；未来有地图资产时 `="awpy"` 一键切换，**核心算法无需重写**（spec PART P Scenario H ✅）。
- metadata 始终含 `geometry_source / geometry_quality / geometry_version`（spec §33）。

## 6. 未来路径

```
资产到位后:
  config: geometry_provider=awpy, geometry_nav_dir=data/nav, geometry_tri_dir=data/vphys
  → LocalExposure.cover/escape_route 从 None 变为近似值
  → EvidenceSufficiency 部分从 MEDIUM 升 HIGH（sufficiency 分数已有几何加分项）
  → Tradeability.direct_los/nav_distance 从 None 变近似
```
