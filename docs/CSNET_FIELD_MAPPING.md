# CSNET_FIELD_MAPPING.md — PlayerLab ↔ CS-NET 字段映射研究（spec §38）

> 目的：研究 PlayerLab canonical state 与 CS-NET token/state 的字段重合度，
> 判断 direct mapping / conversion / missing，以及是否可以避免双解析（spec §39）。
> 依据：CS-NET `demoparser_utils/state_extract.py`（`build_tick_features` 的输入）
> + `data/process_demo.py` + PlayerLab `state.py / ingest.py`（HEAD 对照）。

---

## 1. CS-NET state 输入结构（每 tick）

```json
{
  "map_name": "de_dust2",
  "tick": 1234,
  "round": 3,
  "round_seconds": 42.5,
  "players_info": [   // 10 人，固定顺序（CT 在前 T 在后）
    {"steamid": ..., "X": .., "Y": .., "Z": .., "pitch": .., "yaw": ..,
     "health": .., "armor": .., "has_helmet": .., "has_defuser": ..,
     "flash_duration": .., "team_num": "CT", "velocity": .., "velocity_X": ..,
     "velocity_Y": .., "velocity_Z": .., "inventory": ["AK-47", ...],
     "is_alive": true}
  ],
  "bomb_position": [x, y, z],
  "is_bomb_planted": bool, "is_bomb_dropped": bool, "bomb_planted_duration": s,
  "projectiles": [...], "entity_grenades": [...],
  "future_damage": ..., "future_kills": ...   // 训练用，推理不需要
}
```

## 2. 字段级映射

| PlayerLab 字段 | CS-NET 字段 | 映射 | 说明 |
| --- | --- | --- | --- |
| tick record `x/y/z`（m_vecX/Y/Z） | `players_info[i].X/Y/Z` | **direct** | 同源 demoparser2 属性（PlayerLab ingest 已验证 m_vecX/Y/Z 正确） |
| `yaw`（m_angEyeAngles） | `players_info[i].yaw` | **direct** | CS-NET 用 cos/sin(yaw)；PlayerLab 已存原始 yaw |
| `pitch` | `players_info[i].pitch` | **direct** | CS-NET 需 pitch；PlayerLab tick 目前不存 pitch → **missing（易补）** |
| `health` | `players_info[i].health` | direct | 相同 |
| `armor` / `has_helmet` / `has_defuser` | 同名 | direct | PlayerLab tick 未采集 armor/helmet/defuser → **missing（易补）** |
| `is_alive` | `players_info[i].is_alive` | direct | 相同 |
| `weapon_def`（数字） | `inventory`（武器名字符串） | **conversion** | PlayerLab 有 `weapons.name_from_def` 反向表；需生成完整 inventory（主武器+副武器+刀+投掷物），CS-NET 有 51 类 tokenizer |
| 速度（speed 标量） | `velocity_X/Y/Z` | **conversion** | PlayerLab 从位置差分推 velocity；CS-NET 单独要三轴 + 标量 |
| `place`（区域名） | 无 | **n/a** | CS-NET 用绝对坐标 + map center 归一化，不用区域名 |
| `team_number`（2/3） | `team_num`（"CT"/"T"） | **conversion** | 字符串化 |
| bomb planted（事件） | `bomb_position` / `is_bomb_planted` / `bomb_planted_duration` | **conversion** | PlayerLab `bombs.planted` 事件 + bomb 实体位置需额外解析；PlayerLab 目前不存 bomb 实体坐标 → **missing** |
| 弹道/投掷物 | `projectiles` / `entity_grenades` | **missing** | CS-NET 有完整投掷物 tokenizer（smoke/inferno + 飞行中）；PlayerLab 只有 detonate 事件，无实体轨迹 |
| 回合时间 | `round_seconds` | **conversion** | PlayerLab `round_time_s` 反向（剩余→已过） |
| steamid | `players_info[i].steamid` | direct | 排序键（CT 前 T 后，PlayerLab 需按 team 重排） |

## 3. 结论：Direct vs Conversion vs Missing

- **direct mapping**：位置、yaw、health、is_alive、steamid —— 约 40% 字段可直接复用 PlayerLab tick 缓存。
- **conversion**：武器 inventory、velocity 三轴、team 字符串、回合时间 —— 约 30%，有明确转换规则（武器表已在 `weapons.py`）。
- **missing（需要新增采集）**：pitch、armor/helmet/defuser、bomb 实体坐标、投掷物实体轨迹、flash_duration —— 约 30%。这些 PlayerLab V1 tick 字段未采集，需要扩展 ingest 的 wanted_props（demoparser2 支持）。

## 4. 双解析问题（spec §39）

**现状**：CS-NET 自带 `extract_states_by_group(demo_path, ticks)` 用独立 `DemoParser` 全量重解析（parse_events + parse_ticks + parse_grenades）。

- PlayerLab parse 一次（自己的 wanted_props）+ CS-NET 再 parse 一次 = **双解析**。
- 实测成本（本 spike，de_dust2 252MB 18 局）：PlayerLab parse ~40s；CS-NET parse 8s + state extract 12s/2局 → 全量 ~90s。
- **短期**：接受双解析（spec §39 允许），成本记录在 CSNET_INTEGRATION_REPORT.md。
- **未来路径（消除双解析）**：
  1. PlayerLab ingest 扩展 wanted_props 补齐 missing 字段（pitch/armor/bomb 坐标/投掷物）→ PlayerLab ticks 缓存成为 CS-NET state 的唯一来源；
  2. 在 PlayerLab 内实现 `adapter: canonical_frame -> csnet_state`（direct+conversion 全表），CS-NET 只保留模型加载与推理；
  3. 依赖方向：`csnet.py` import CS-NET 的 `build_tick_features`（无状态纯函数），不 import 其 DemoParser 路径。
- **代价预估**：一次解析（~40s）替代两次（~130s），且 PlayerLab 缓存 tick pickle 已存在，改造成本集中在 ingest wanted_props 扩展（~30 行）。

## 5. Hindsight / scope 标注

CS-NET 输入为**全量 10 人场上状态 + bomb 实体坐标**（GROUND_TRUTH_STATE，spec §33）：
- PlayerLab 只在 Decision Review 中作为 **Supporting Evidence** 展示（spec §37）；
- 不写入 PlayerKnownState（spec §34 Hindsight Boundary）；
- win probability 变化绝不单独触发责任归因（spec §35/§36）。

## 6. 推荐集成路径（短期 → 中期）

| 阶段 | 动作 | 成本 |
| --- | --- | --- |
| 短期（本阶段） | 双解析 + CSNetProvider 只读 win_rate；结果 JSON 缓存到 `data/csnet_states/`（spec §40） | 已实现 |
| 中期 | PlayerLab ingest 扩字段 → 单解析 adapter | ~0.5 天 |
| 长期 | 若字段全齐，PlayerLab 成为唯一解析层，CS-NET 纯模型库化 | 无重复解析 |
