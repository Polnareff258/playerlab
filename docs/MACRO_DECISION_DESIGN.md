# MACRO_DECISION_DESIGN.md — Phase 4：宏观决策设计

> 覆盖 spec §7（Information Discipline / Rotation Quality / Advantage Management / Spacing & Tradeability / Map Control Responsibility / Timing Usage）。
> 每个模块按固定结构输出：**Available telemetry / Detection rule / Existing reusable implementation / Confidence strategy / Failure modes**。
> **全局硬约束**：宏观判定只使用 PlayerKnownState + 公开信息（hindsight 守卫，§32 测试强制）；GroundTruth 仅用于描述性结构指标（spacing/territory），且不得进入「该不该做」的判定。

---

## 0. 公共基元（所有宏观模块复用）

| 基元 | 来源 | 用途 |
| --- | --- | --- |
| KnownState 快照（任意 tick） | `state.KnownStateBuilder` | 信息强度/响应判定 |
| 公开信息（alive/比分/bomb/时间） | `state.PublicInfoBuilder` | 优势状态/时间压力 |
| 区域序列（zone transitions） | `zones.zone_for` + tick 位置 | rotate/位移检测 |
| 事件时间线 | `ingest.events` | timing/utility/contact |
| 团队结构（描述性） | tick 全量位置 | spacing/territory 描述 |

**回合级状态机**：每个玩家维护 `RoundStateMachine { phase, current_zone, info_snapshot, commitment, contacts[] }`，回合开始重置。

---

## 1. Information Discipline（信息纪律，§7.1）

**问题**：弱信息 + 强行动 = overreaction；强信息 + 弱行动 = underreaction。

**Available telemetry**：KnownState（`last_seen_enemies` 数量/来源/新旧、`heard` 声音、damage 来源）、zone、velocity、bomb 状态、alive counts。

**Detection rule（确定性）**：
- `info_strength(t)` = Σ 每条已知信息的加权强度（damage=1.0 / own_vision=0.8 / team_vision=0.6 / footstep=0.4 / shot=0.4 / grenade=0.3，× 新鲜度衰减 exp(-Δt/8s)）
- `commitment(t)` = 事件内位移量（跨 zone 移动）+ 道具消耗数 + 交火参与
- **overreaction**：`info_strength < θ_low(默认 0.5)` 且发生 full rotate（§2）或 utility 全耗 + 主动 push
- **underreaction**：`info_strength ≥ θ_high(默认 2.0)`（如 2+ 确认敌人 + bomb 已确认）且无响应动作（无位移、无 utility、无 reposition）持续 > τ(默认 3s)
- 特例（spec §7.1 例）：单一 footstep（强度 0.4）→ full rotate；B 侧 2+ 确认 + bomb + A 无压力 → 仍深守 A 无响应

**Existing reusable implementation**：无直接实现（生态空白）→ 自定义；复用 KnownStateBuilder 全部输入。

**Confidence strategy**：逐条信息源置信度（来源类型表）+ 新鲜度；总置信 = 证据覆盖率（所需字段齐全度）。规则判定置信 < 0.5 → 该事件标 UNKNOWN。

**Failure modes**：①信息来源缺失（SourceTV 无脚步声方向——我们用位置近似，半径内有效）；②队友信息假设（team_comms 开关）；③未考虑语音（demo 无）→ 标注 confounder。

---

## 2. Rotation Quality（旋转质量，§7.2）

**问题**：early/late/soft/full/fake-induced/unnecessary/no-response 旋转。

**Available telemetry**：zone 序列、KnownState（对方信息）、bomb 状态、alive、teammate（可见部分）、utility。

**Detection rule**：
- **rotate 事件** = 同回合内连续跨 zone 移动（zone A→B 且位移 > 阈值），记录 `{start_tick, from_zone, to_zone, duration}`。
- 分类：
  - `full rotate`：跨全场 zone（A↔B 或经 MID）
  - `soft rotate`：移动到中间/半场 zone 即停（如 A→MID），或先移动后回撤
  - `early rotate`：bomb 未下、敌信息 ≤1 条、round_time 前 40% 内 full rotate
  - `late rotate`：bomb 已下/敌信息 ≥2 条后仍无响应，响应时距爆炸 < 20s
  - `fake-induced`：敌方假动作可证（fake 后敌主力仍原侧——用 GroundTruth 事后标注，**不进判定**，只进事后解释）
  - `unnecessary rotate`：rotate 后新区域无接触且原区域压力消失
  - `no-response`：强信息（≥2 条 + bomb）下无 rotate/无动作（与 §1 underreaction 复用）
- 判定只依赖 rotate 时刻的 KnownState（玩家当时知道什么），bomb/score/alive 为公开信息。

**Existing reusable implementation**：无成熟 rotate 分析（生态空缺，research 待合并）→ 自定义；zone 语义复用 zones.py + @cs2dak/maps 风格的 zones。

**Confidence strategy**：分类依赖的信息条目数（≥2 条才标 early/late）；fake-induced 永远标 UNKNOWN（无法从玩家视角证明）。

**Failure modes**：zone 边界定义（dust2 表自定义，其他图回退点位名）；SourceTV 无视角 → 信息强度偏低；1v1 残局无 rotate 概念（alive≤2 跳过）。

---

## 3. Advantage Management（优势管理，§7.3）

**问题**：5v4/4v3/3v2 优势下主动送孤立 1v1、追杀、unnecessary peek、放弃可换人结构、overextend。

**Available telemetry**：alive counts（公开）、KnownState（敌最后位置）、teammates（可见）、duel 归属、counterfactual 引擎。

**Detection rule**：
- **advantage 状态**：`alive_diff = team_alive − enemy_alive ≥ 1` 时进入（回合状态机记录进入 tick）。
- 违规检测（事件级）：
  - `isolated_1v1_given`：优势状态下，玩家在无队友支援距离（nearest teammate > 1600u 且无 LOS）内主动交火（PEEK/RE_PEEK 且敌人 ≥1 确认）
  - `chase`：沿最后已知敌位置连续位移 > 2000u 且超出本方已知信息边界（进入无信息区）
  - `unnecessary_peek`：优势 + 无新信息价值（对方无动作、无 bomb 压力）时 RE_PEEK/PEEK
  - `abandon_tradeable`：队友正在交火（最近 damage < 96 ticks）时玩家反方向移动远离
  - `overextend`：位移越过本方信息边界进入无信息 zone（与 chase 区分：不追人，纯位置过深）
- **不禁止主动**：spec §7.3 明确——比较 risk/reward/info gain/team value → 用 counterfactual（同状态相似样本中该行为的 survival/round_win）作为证据，而非一刀切。

**Existing reusable implementation**：duel/换人结构 = CS Demo Manager 的 trade 分析（research 合并，MIT）；其余自定义。

**Confidence strategy**：每类违规要求证据条目 ≥2（如 isolated 需要距离 + 敌确认）；counterfactual 支持度并入（§IMPROVEMENT_MODEL-6）。

**Failure modes**：alive 数从 kill feed 推导有延迟（死亡到 feed 的 tick 差）；无语音 → 无法区分「明知有人支援」。→ 相关违规标 UNKNOWN 或降置信。

---

## 4. Spacing / Tradeability（间距与可换人性，§7.4）

**定位**：描述性结构指标（用全量位置计算），**用于诊断上下文，不直接评判**。

**Available telemetry**：tick 全量位置（描述层）、damage/kill 事件、duel 归属。

**指标（复用成熟实现优先，research 合并）**：
- `teammate_distance`：决策时最近队友距离分布
- `tradeable_window`：队友死亡 tick 前后，本玩家能否在 W 内还击（对击杀者造成 damage）
- `trade_response_time`：队友死亡 → 本玩家首次伤害的 tick 差
- `isolated_duel_rate`：nearest teammate > 阈值时的 duel 占比
- `support_availability`：决策点处最近队友是否 alive + 距离桶

**Existing reusable implementation**：AWPy `calculate_trades`/trades、CS Demo Manager trade 检测（MIT）——research 确认后按 adapter 复用或本地等价实现（规则简单，若 adapter 成本高则本地实现并对照）。

**Confidence strategy**：全部为描述性数值（高置信，来自 tick 数据）；仅当它们进入判定（如 isolated_1v1）时按 §3 的置信规则。

**Failure modes**：SourceTV 位置为服务器权威（可靠）；「换人窗口」依赖对击杀者位置的即时响应判定（damage 事件时间粒度 tick 级，足够）。

---

## 5. Map Control Responsibility（区域控制责任，§7.5）

**问题**：玩家离位后谁负责该区域？是否形成信息真空？

**Available telemetry**：zone 序列、KnownState 信息覆盖（哪些 zone 有已知敌信息）、team 结构。

**Detection rule**：
- `area_control_before/after`：某 zone 内本方人数与信息覆盖度在玩家离位前后对比（离位 = 离开所在 zone 且停留 > 2s）。
- `info_vacuum`：离位后该 zone 无任何本方玩家且无 KnownState 信息（zone 内无 last_seen/heard）持续 > τ。
- **avoid 简单判断「移动了=错」**：离位只有在造成 `info_vacuum` 或队友需补位而无人补时标记为风险事件；离位换取更强位置（对方新信息 + 新 zone 有覆盖）→ 记为积极事件。
- 责任转移：离位后最近队友是否进入该 zone（描述层）。

**Existing reusable implementation**：区域/点位语义 = zones.py + 生态 maps 包（research）；control/territory 无成熟实现（cs2-structural-analytics research 待合并）→ 自定义 zone-occupancy 计算（简单计数，无复杂度风险）。

**Confidence strategy**：occupancy/coverage 为确定性计数（高置信）；「责任归属」为推断 → 只输出候选责任玩家，标注 UNKNOWN 可能。

**Failure modes**：zone 表覆盖不全（其他地图回退点位名导致区域粒度不一致）→ 覆盖报告提示；同时离位多人时的责任归属歧义 → 保守（无责判定，仅列结构变化）。

---

## 6. Timing Usage（时机运用，§7.6）

**问题**：行为发生的时机是否合理（早/晚/错误窗口）。

**Available telemetry**：事件时间线（kill/death/damage/utility/footstep）、KnownState 更新、bomb、zone 变化。

**Detection rule**：
- `TimingContext(t)` = { 队友接触(最近 damage/tick)、recent_kill、recent_death（<96 ticks）、敌方 utility（detonate 事件）、本方 utility、enemy_busy（敌方开火/伤害中）、possible_reload（敌方开火后 2.5s 内）、info_update（新 last_seen）、map_control_change（zone 转移）}
- 评估行为时机：对每个重要行为（PEEK/rotate/utility 使用），在 TimingContext 下打分：
  - 接触后 <300ms 立即 re-peek 且无新信息 → 差时机（与 p_repeek 共用证据）
  - 敌方 utility 刚爆（flash/smoke detonate <500ms）时 push → 差时机
  - recent kill 后 2s 内利用窗口推进 → 好时机（事件计数）
- 输出为 `timing_events[]`，进 Pattern 上下文，不单独出 dashboard。

**Existing reusable implementation**：无成熟实现 → 自定义（规则直接、事件齐全）。

**Confidence strategy**：TimingContext 各项全部来自事件（确定性）；「好时机」仅作正向计数，不参与负面模式。

**Failure modes**：无语音/无视野 → enemy_busy 只能从事件近似；possible_reload 为启发式 → 只用于解释不用于判定。

---

## 7. Hindsight 泄漏测试（spec §32 强制）

每个宏观模块的单元测试必须包含：
1. **隔离用例**：构造 GroundTruth 与 PlayerKnownState 不一致的合成场景（如 KnownState 无 B 侧信息但 GroundTruth 有 3 人）→ 断言宏观判定输出不变（不读取敌人真实位置）。
2. **白名单断言**：宏观模块 import 黑名单——判定函数签名不接受 ground_truth 输入；测试断言 `info_strength/rotate/advantage` 等函数入参仅含 known/public。
3. **回归样例**：真实 demo 切片标注（如「已知 B 确认 + bomb → 无响应」应为 underreaction），人工预标注 ≥10 条进入黄金夹具。

---

## 8. 与 V1.1 MVP 的映射

| 宏观模块 | MVP 启用（V1_1_MVP.md） | 备注 |
| --- | --- | --- |
| Information Discipline | ✅ overreaction/underreaction 两模式 | 数据可行、规则直接 |
| Rotation Quality | ✅ 基础 rotate 分类（full/soft/late/no-response） | early/fake 后置 |
| Advantage Management | ✅ isolated_1v1 / chase / unnecessary_peek | counterfactual 支持 |
| Spacing / Tradeability | ✅ 描述性指标 + isolated_duel_rate | 复用/本地等价 |
| Map Control Responsibility | ⚠️ info_vacuum 单指标 | 责任归属后置 |
| Timing Usage | ⚠️ 事件上下文，仅支持其他模块 | 不单独出模式 |
