# CAPABILITY_MATRIX.md — 阶段 2：能力矩阵

> 数据 × 来源 × 频率 × 精度 × 验证状态 × 消费模块。所有「已实测」行来自 spike 探针（252MB 真实 CS2 Valve SourceTV demo，de_dust2，18 局）；「生态」行来自 EXISTING_PROJECTS.md 研究。

## 1. 数据能力矩阵（PlayerLab 视角）

| Data | Available | 来源 | 频率 | 精度 | 验证状态 | 消费模块 |
| --- | --- | --- | --- | --- | --- | --- |
| XYZ | ✅ | demoparser2 `CBodyComponentBaseAnimGraph.m_vecX/Y/Z`（**origin 已废弃**） | 每 tick | 精确 | **已实测** | GameState / Replay / LOS |
| Velocity | ✅ | **位置差分推导**（Δpos×64 u/s；m_vecBaseVelocity 不更新） | 每 tick | 精确（64Hz 差分） | **已实测** | DP 检测（peek/strafe）/ Execution |
| Yaw | ✅ | `m_angEyeAngles`[1] | 每 tick | 精确（tick 级） | **已实测** | DP 检测 / Aim（crosshair 误差） |
| Pitch | ✅ | `m_angEyeAngles`[0] | 每 tick | 精确 | **已实测** | Aim（垂直误差） |
| Buttons | ✅ | `buttons` 位掩码（IN_*） | 每 tick | 位掩码 | **已实测** | DP 检测 / Execution（counter-strafe） |
| Shots | ✅ | `weapon_fire` 事件 + `m_iShotsFired` | 事件 + tick | 精确 | **已实测**（3212 条） | Duel / Aim / Engagement |
| Damage | ✅ | `player_hurt` / `bullet_damage` | 事件 | 精确（dmg/hitgroup） | **已实测**（520 条） | Duel / PlayerKnownState（伤害来源） |
| Weapon | ✅ | `m_hActiveWeapon` 句柄 + Weapon.* 实体 | 每 tick | 精确（需映射） | **已实测** | GameState / 相似度特征 |
| Grenades | ✅ | `parse_grenades` 轨迹 + detonate 事件 | 每 tick/实体 + 事件 | 精确 | **已实测**（101 万行，11 类型） | PlayerKnownState / 相似度 |
| Visibility | ⚠️ 派生 | 无内置；LOS = raycast（awpy VPhys→tri BVH / @cs2dak/maps .tri） | 按需派生 | 上帝视角精确 | 生态已验证（awpy） | PlayerKnownState 视野 / DP exposure |
| Map/nav | ✅ 部分 | `m_szLastPlaceName`（点位名）✅；`.nav` 网格 + zones/callouts（awpy / @cs2dak/maps） | tick + 静态资产 | 精确 | 点位名**已实测**；nav 生态已验证 | Location 特征 / Hard Filter / 相似度 |
| Footsteps（声音） | ✅ | `player_footstep` | 事件 | 有位置（半径阈值使用） | **已实测**（733 条） | PlayerKnownState（声音线索） |
| Economy | ✅ | `m_iAccount`（本方精确）+ `item_purchase`（1120 条） | tick + 事件 | 本方精确/敌方估计 | **已实测** | GameState / 相似度 |
| Kill feed | ✅ | `player_death`（distance/hitgroup/headshot/thrusmoke/trade…） | 事件 | 精确 | **已实测**（141 条） | PlayerKnownState（公开信息）/ Duel |
| Bomb | ✅ | bomb_planted/defused/dropped/pickup/begindefuse/exploded | 事件 | 精确 | **已实测**（12/4） | GameState / DP 显著性 |
| Rounds/胜负 | ✅ | round_start / round_end（winner+reason） | 事件 | 精确 | **已实测**（18） | Round 边界 / Outcome（round_win） |

## 2. 派生能力矩阵（PlayerLab 需自建 vs 复用）

| 能力 | 生态现状 | PlayerLab 决定 | 依据 |
| --- | --- | --- | --- |
| Demo 解析 | demoparser2 / demoinfocs-golang / csda / source2-demo | **复用 demoparser2（锁版 + FieldMap）** | spike 实测 |
| 数据契约 | cs2-demo-format v3 ZIP（cs2df 导出器） | **复用（canonical 层）** | 生态标准 |
| LOS 可见性 | awpy VisibilityChecker（BVH）；DAK `.tri` | **复用原语** | MIT 生态 |
| Nav 网格 | awpy Nav / @cs2dak/maps | 复用（V1 可选） | 生态 |
| 2D replay | CSDM 2D viewer / DAK replay | 复用交互范式，不复制实现 | 范围控制 |
| Duel/clutch 抽取 | cs2-demo-format duels/clutches、@cs2dak/core | **复用数据，自建归属** | 反事实锚点 |
| 统计评分 | awpy.stats / CSDM HLTV2.0 | 复用（如需） | 生态 |
| DecisionPoint 检测 | **无** | **自建（规则状态机）** | 护城河 1 |
| PlayerKnownState 重建 | **无**（awpy LOS 是上帝视角） | **自建（证据模型）** | 护城河 2 |
| 相似状态检索 | ggViz（研究原型，CS:GO/ESTA） | **自建（Hard+Soft，可回测）** | 护城河 3 |
| 反事实比较 | **无**（win-prob-delta 是研究） | **自建（统计 + 证据强度）** | 护城河 4 |
| Decision vs Execution 分离 | DAK Duel Lab 有部分 mechanics | **自建分离框架，复用 mechanics 原语** | 核心差异 |

## 3. 分层能力视图（V1 边界）

```
┌─ PlayerLab Decision Intelligence Layer（自建：DP 检测 / KnownState / 检索 / 反事实 / UI）
├─ Canonical Data Layer（复用：cs2-demo-format v3 ZIP + 自有 DecisionState 扩展）
├─ Ingestion Layer（复用：demoparser2 + FieldMap；可选 cs2df / csda 交叉验证）
└─ Geometry / Assets（复用：awpy LOS 原语、.nav、@cs2dak/maps zones）
```

## 4. 缺口登记（V1 明示不做，供 roadmap）

| 缺口 | 现状 | V1 处理 |
| --- | --- | --- |
| 逐 tick 原始 buttons 实体广播 | SourceTV 不广播 m_nButtons | 用 `buttons` 友好名 + IN_* 解码 |
| Sub-tick 精度（usercmd 级） | demoparser2 有 usercmd 字段但 V1 不需要 | V1 用 tick 级；接口预留 |
| POV demo | 支持性未验证 | V1 明确不支持 |
| 语音内容 | demo 无 | NOT_AVAILABLE_IN_DEMO |
| 敌方经济/道具精确值 | 只能估计 | 特征用桶 + 置信度 |
| 玩家意图 | 不可观测 | 只用可观测证据 |
