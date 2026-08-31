# TECHNICAL_SPIKE.md — 阶段 2：真实 CS2 Demo 数据可用性验证

> 目的：用至少一场真实 CS2 Demo 验证 §24 的数据可用性表，确认「复用现有解析层」成立，并为架构决策提供实测依据。
> 结论：**demoparser2 (0.42.0) 对真实 CS2 SourceTV demo 提供全部 V1 所需逐 tick 状态与事件信号；无内置 visibility/nav，需复用 awpy 的 LOS 原语与地图数据；字段命名在 0.42 变更，必须加映射层。**

---

## 1. Spike 设置

| 项 | 值 |
| --- | --- |
| Demo 文件 | 本地 252.5 MB 真实 CS2 demo（本机已有；路径为本地私有信息，不随仓库提交） |
| Demo 类型 | **Valve Counter-Strike 2** 官方服务器（server_name: `Valve Counter-Strike 2 japan Server`，SourceTV 录制） |
| 地图 | `de_dust2` |
| 局数 | 18 局（round_start ×18，round_end ×18，含 winner+reason） |
| 玩家 | 10 人（parse_player_info 实测） |
| 解析器 | `demoparser2` 0.42.0（Rust 核心，Python 绑定，MIT），Python 3.13.14 |
| 辅助 | `@akiver/cs-demo-analyzer` 1.10.7（npm，Go 包装器）已安装未启用（二进制需另下载） |
| 探针脚本 | `spike/demo_probe.py`（v1）、`spike/demo_probe2.py`（v2），输出 `spike/probe_out.json`、`spike/probe2_out.json` |

---

## 2. 实测事件与计数（probe v1）

| 事件 | 数量 | 关键列（实测） |
| --- | --- | --- |
| player_death | 141 | distance, hitgroup, headshot, thrusmoke, noscope, attackerblind, penetrated, dmg_health, dmg_armor, weapon, weapon_itemid, tick |
| player_hurt | 520 | dmg_health, dmg_armor, health, armor, hitgroup, attacker_name, weapon, tick |
| weapon_fire | 3212 | weapon, silenced, user, tick |
| round_start / round_end | 18 / 18 | round, tick / reason, winner, tick |
| bomb_planted / bomb_defused | 12 / 4 | site, user, tick |
| player_footstep | 733 | user, tick（**声音线索可用**） |
| item_purchase | 1120 | item_name, cost, skin, was_sold, tick（**经济重建可用**） |

---

## 3. 实测逐 tick 字段（probe v2 + 决定性验证）

demoparser2 0.42.0 字段命名 = 友好名 + 实体路径混合，**必须按版本建映射**。以下为在本 demo 上实测存活的字段：

| 需求 | 实测可用字段 | 形态 | 备注 |
| --- | --- | --- | --- |
| XYZ | `CCSPlayerPawn.origin` | [x,y,z] 向量 | ✅ 每 tick |
| Velocity | `CCSPlayerPawn.m_vecBaseVelocity`（+ `m_flVelocityModifier`） | [vx,vy,vz] 向量 | ✅ 每 tick |
| Yaw | `CCSPlayerPawn.m_angEyeAngles`[1] | 角度分量 | ✅ 每 tick |
| Pitch | `CCSPlayerPawn.m_angEyeAngles`[0] | 角度分量 | ✅ 每 tick |
| Buttons | `buttons`（友好名，位掩码） | int | ✅ 每 tick；CS2 IN_* 位掩码需 SDK 常量解码；实体路径 `m_nButtons` 未广播（SourceTV 限制） |
| 血量/护甲 | `CCSPlayerPawn.m_iHealth` / `m_ArmorValue` | int | ✅ |
| 金钱 | `CCSPlayerController...InGameMoneyServices.m_iAccount` | int | ✅ |
| 武器 | `CCSPlayerPawn.CCSPlayer_WeaponServices.m_hActiveWeapon` | 实体句柄 | ✅ 需 Weapon.* 实体映射 |
| 点位名 | `CCSPlayerPawn.m_szLastPlaceName` | string（CTSpawn/TSpawn/Catwalk…） | ✅ **区域语义直接可得** |
| 瞄准状态 | `is_walking` / `is_scoped`（友好名） | bool | ✅ |
| 开火计数 | `CCSPlayerPawn.m_iShotsFired` | int | ✅ |
| 身份 | `steamid` / `name` / `player_name` | — | ✅ |

实测样例（tick 700，玩家名已匿名化）：
```
name     origin(xyz)         m_vecBaseVelocity  m_angEyeAngles     money  armor  health  buttons  place
PlayerA  [-8,-308,202]       [0,0,0]            [0,-67.5,0]        800    0      100     3752194  CTSpawn
PlayerB  [-8,-308,202]       [0,0,0]            [4.87,-0.28,0]     150    100    100     377100   TSpawn
```

### ⚠️ 字段勘误（实现期实测发现并修正，2026-08-31）
1. **`CCSPlayerPawn.origin` 在 CS2 demo 中返回陈旧的出生点坐标**（全员同一坐标，与真实点位名矛盾）。正确位置字段：
   `CCSPlayerPawn.CBodyComponentBaseAnimGraph.m_vecX / m_vecY / m_vecZ`（与 `m_szLastPlaceName` 完全吻合，mid-round 实测 ExtendedA/Catwalk/Middle/TopofMid 等）。
2. **`m_vecBaseVelocity` 在 CS2 demo 中恒为 [0,0,0]**（SourceTV 不更新）。实现改为**位置差分推导速度**（Δpos×64 u/s，传送/重生钳制），任何 parser 下都稳健。
3. 其余字段（m_angEyeAngles、m_iHealth、m_iShotsFired、buttons、m_szLastPlaceName、Weapon.m_iItemDefinitionIndex、m_iAccount、m_iTeamNum）实测均正确；`CCSPlayerController.m_iTeamNum` 逐 tick 提供**真实阵营**（含半场换边），替代炸弹推断。

### 事件全集（list_game_events 实测，52 个）
round_time_warning, bomb_dropped, hegrenade_detonate, smokegrenade_detonate, item_equip, chat_message, bomb_begindefuse, player_disconnect, round_freeze_end, player_connect, round_announce_last_round_half, bomb_exploded, weapon_zoom, bomb_planted, decoy_detonate, weapon_fire_on_empty, buytime_ended, item_pickup, fire_bullets, round_officially_ended, player_connect_full, cs_win_panel_match, round_poststart, rank_update, bomb_pickup, flashbang_detonate, player_death, bomb_beginplant, decoy_started, begin_new_match, bullet_damage, player_team, player_blind, cs_round_start_beep, smokegrenade_expired, bomb_defused, weapon_fire, round_announce_match_point, cs_round_final_beep, announce_phase_end, inferno_startburn, round_prestart, round_announce_match_start, hltv_versioninfo, player_spawn, player_jump, weapon_reload, player_footstep, cs_pre_restart, server_cvar, player_hurt, inferno_expire

### Grenade 轨迹（parse_grenades 实测）
- 1,015,587 行（grenade 实体逐 tick 状态），类型 11 种：CDecoyGrenade/Projectile、CFlashbang/Projectile、CHEGrenade/Projectile、CIncendiaryGrenade、CMolotovGrenade/Projectile、CSmokeGrenade/Projectile
- 字段：grenade_type, grenade_entity_id, x, y, z, tick, steamid, name
- 未出手实体位置为 NaN（持有状态）；detonate 事件另有 hegrenade_detonate / smokegrenade_detonate / flashbang_detonate / inferno_startburn

---

## 4. §24 数据可用性表（实测结论）

| Data | Available | Source | Frequency | Accuracy |
| --- | --- | --- | --- | --- |
| XYZ | ✅ | `CCSPlayerPawn.origin` | 每 tick（64 tick） | 服务器权威坐标，精确 |
| Velocity | ✅ | `m_vecBaseVelocity` + `m_flVelocityModifier` | 每 tick | 精确（含站/走/跑差异） |
| Yaw | ✅ | `m_angEyeAngles`[1] | 每 tick | 精确（Sub-tick 需 usercmd 级，V1 用 tick 级） |
| Pitch | ✅ | `m_angEyeAngles`[0] | 每 tick | 精确 |
| Buttons | ✅ | `buttons` 位掩码 | 每 tick | 位掩码（需 SDK 常量解码；m_nButtons 实体路径不广播） |
| Shots | ✅ | `weapon_fire` 事件 + `m_iShotsFired` | 事件级 + tick | 精确 |
| Damage | ✅ | `player_hurt` + `bullet_damage` | 事件级 | 精确（dmg_health/armor、hitgroup） |
| Weapon | ✅ | `m_hActiveWeapon` 句柄 + Weapon.* 实体字段 | 每 tick | 精确（需实体映射） |
| Grenades | ✅ | `parse_grenades`（轨迹）+ detonate 事件 | 每 tick/实体 + 事件 | 精确；轨迹行量大（100 万行/场）需裁剪 |
| Visibility | ⚠️ 间接 | 无内置字段；LOS 需 raycast（awpy VPhys→tri BVH 原语） | 派生计算 | 上帝视角 LOS 精确；**玩家可知视野需 PlayerKnownState 层叠加 FOV/声音** |
| Map/nav | ✅ 部分 | `m_szLastPlaceName`（点位名）；nav 网格需 `.nav` 文件 + awpy/`@cs2dak/maps` | tick + 静态资产 | 点位名精确；nav 需要按 patch 下载 |
| Footsteps（声音） | ✅ | `player_footstep`（733 条实测） | 事件级 | 有方向/位置（V1 按半径阈值使用） |
| Economy | ✅ | `m_iAccount` + `item_purchase`（1120 条） | tick + 事件 | 精确（本方）；敌方为估计 |
| Kill feed | ✅ | `player_death`（141 条，含 distance/hitgroup/headshot/thrusmoke） | 事件级 | 精确 |
| Bomb | ✅ | bomb_planted/defused/dropped/pickup/beginplant/exploded/begindefuse | 事件级 | 精确 |
| Rounds/胜负 | ✅ | round_start/round_end（winner+reason） | 事件级 | 精确 |

---

## 5. 性能实测（MVP 管线，2026-08-31 实现期复测）

| 项目 | 数值 |
| --- | --- |
| 1000 ticks × 10 玩家（16 字段） | 0.64 s，15,594 行/s |
| 全量事件解析（v1，252MB demo） | ~20 s |
| 全量 tick 状态（17 字段，110k ticks × 10 玩家 ≈ 110 万行） | 主导耗时 |
| **完整 ingest + DP 检测管线（含事件+tick+校准+检测+入库）** | **38–50 s/场（实测）** |
| 二次分析（tick pickle 缓存命中） | 秒级 |

结论：一场 252MB 完整比赛的全量结构化解析+决策点检测在**一分钟内**完成，本地优先可行；tick 缓存（`analyses/<demo_id>.ticks.v3.pickle`）使重跑/调参在秒级完成。grenade 轨迹按需裁剪（只在需要时解析）。

---

## 6. Spike 发现（影响架构）

1. **字段命名不稳定**：0.42.0 的友好名（x/y/z、view_angle_x 等）大量失效，改用实体路径（`CCSPlayerPawn.origin` 等）；友好名 `buttons`/`last_place_name` 仍可用。→ 架构必须建 **FieldMap 适配层**（canonical 字段 ↔ parser 版本字段），并锁 demoparser2 版本。
2. **SourceTV 限制**：`m_nButtons` 实体字段不广播，但 `buttons` 友好名可用（游戏内合成）；POV demo 另有差异（V1 不做 POV，明确范围）。
3. **Visibility 无内置**：LOS 需要复用 awpy 的 VPhys→tri BVH raycast（或 @cs2dak/maps + .tri）；PlayerKnownState 的「玩家可知视野」还需要 FOV 锥 + 声音 + last-seen 逻辑（PlayerLab 自建，生态空白）。
4. **Grenade 行量大**：100 万行/场；存储时只保留 detonate/轨迹关键点，或按需解析。
5. **点位名直接可用**：`m_szLastPlaceName` 提供区域语义（CTSpawn/Catwalk/OutsideLong…），可作 location 特征的地图无关表示；与 `@cs2dak/maps` zones/callouts 对齐后进 Hard Filter。
6. **cs2-demo-format v3 契约兼容性**：cs2df（参考导出器，demoparser2 后端）存在，说明 v3 ZIP 数据契约可直接消费/发射 —— canonical 层采用它，避免自造 schema。

---

## 7. 复用决定（基于实测）

| 层 | 决定 | 依据 |
| --- | --- | --- |
| 解析 | **demoparser2 0.42（锁定版本）+ FieldMap 适配层** | 实测全字段可用、性能达标、MIT |
| 数据契约 | **cs2-demo-format v3 ZIP（cs2df 导出/校验）** | 生态标准、含 duels/clutches、MIT |
| LOS/几何 | **awpy visibility 原语（VPhys→tri BVH）+ 地图资产** | 生态已有、MIT |
| 区域语义 | `m_szLastPlaceName` + `@cs2dak/maps` zones/callouts | 实测可用 + 生态包 |
| 2D replay | 不实现；复用 CSDM/DAK 交互范式与 `@cs2dak/maps` worldToRadar | 避免重复造轮子 |
| 统计 | awpy.stats / cs2-demo-format 字段 | 已有实现 |

**禁止自研 CS2 demo parser 的结论成立：现有生态（尤其 demoparser2）已验证满足 V1 全部数据需求。**
