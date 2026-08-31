# V1_1_MVP.md — Phase 5：MVP 选型

> 原则：**不一次实现所有 Pattern**。选「现有遥测能可靠支撑」的能力；每项标注数据可行性依据与置信风险。
> 详细检测规则见 IMPROVEMENT_MODEL.md 与 MACRO_DECISION_DESIGN.md；本文只做选型与理由。

---

## 1. 选型矩阵

| 能力 | 层级 | 选入 MVP? | 数据可行性依据 | 主要风险 |
| --- | --- | --- | --- | --- |
| immediate same-angle re-peek | Micro | ✅ | 现有 RE_PEEK 谓词直接复用；tick 位置/速度/角度齐全 | 无几何 LOS，暴露度近似 |
| same-angle repeat | Micro | ✅ | 同 episode 多 RE_PEEK 聚合（现有 episode 结构） | 同上 |
| move-and-shoot first shot | Execution | ✅ | weapon_fire 事件 + 速度@射击（实测字段） | 事件与 tick 对齐精度 |
| counter-strafe quality | Execution | ✅ | 速度@射击 + 射击前速度衰减（实测字段） | 阈值需标定 |
| overstay after contact | Local | ✅ | 接触事件 + 位置滞留 + utility 事件 | 无视野时的「被架」歧义 |
| overaggressive advantage play | Macro | ✅ | alive 公开数 + KnownState + duel 归属 | 无语音，孤立判定近似 |
| slow response to strong info | Macro | ✅ | KnownState 信息强度（damage/vision/声音） | team_comms 假设 |
| overreaction to weak info | Macro | ✅ | 同上 + rotate 检测 | 同上 |
| basic rotation（full/soft/late/no-response） | Macro | ✅ | zone 序列 + bomb + 信息强度 | zone 表覆盖 |
| early/fake-induced rotate | Macro | ❌（后置） | early 可做但易误报；fake 需要事后真相 | 假动作不可从玩家视角证明 |
| map control responsibility（info_vacuum） | Macro | ⚠️（单指标） | zone occupancy 可算；责任归属歧义 | 多人离位歧义 |
| timing usage 事件 | Macro | ⚠️（仅支持上下文） | 事件齐全 | 不单独出模式 |
| poor trade spacing / isolated duel tendency | Local | ⚠️（描述指标入 MVP，模式判定后置） | 距离/换人窗口可算 | 描述 vs 判定边界 |

## 2. MVP 最终范围

### 2.1 Pattern（启用 8 个）
- **Micro/Execution（4）**：`p_repeek`（immediate same-angle re-peek）、`p_same_angle`、`p_move_shoot`、`p_counter_strafe`
- **Local（1）**：`p_overstay`
- **Macro（3）**：`p_adv_overaggro`（优势下送孤立交火/追杀/无谓 peek）、`p_info_slow`（强信息无响应）、`p_info_overreact`（弱信息过度反应）

### 2.2 支撑层
- Root Cause Chain：覆盖死亡事件（Micro/Local/Macro/Execution 四层，允许 UNKNOWN）
- Bottleneck Ranking：8 模式 × (Frequency×Impact×Confidence×Trainability)
- TrainingTarget：MVP 产出 ≤2 个 ACTIVE（1 Micro/Execution + 1 Macro）
- Improvement Validation：每窗口自动重测（baseline/current/goal + 三通道 verdict）
- Longitudinal：target timeline + 状态流转
- UI 首页：CURRENT FOCUS（2 目标卡 + WHY THIS? + Next Match Cue）+ Recent Matches
- Execution 指标 4 项（move-and-shoot / counter-strafe / first-shot timing / same-angle repeat）

### 2.3 明确不做（V1.1）
early/fake rotate 分类、责任归属判定、territory 热力 dashboard、Skill Model、Aim Trainer、Pro Reference（§24–§26 后置）、timing 独立模式。

## 3. 选择理由（浓缩）

1. **遥测完整性**：Micro/Execution 四项全部依赖已有字段（位置差分速度/事件/角度），零新解析；Macro 三项依赖 KnownState 与公开信息，均有实现基元。
2. **可靠判定**：规则 + Wilson CI + 反事实支持三层把关；证据不足自动降级（Confidence 上限、INSUFFICIENT_EVIDENCE）。
3. **闭环可演示**：8 个模式任一都能走完 `Pattern → Bottleneck → TrainingTarget → Validation` 全链——满足 §33 成功标准（如 immediate re-peek 的 baseline 71% → target <35% → next-5 场验证）。
4. **样本现实**：多场 batch 后，re-peek/overstay 类模式样本最快达标；宏观类样本更薄 → 由 Confidence 规则自然降级，不硬凑。

## 4. 验证路径（§32 测试要求映射）

| 要求 | MVP 落实 |
| --- | --- |
| Pattern detector 单测 + 合成场景 | 每个 Pattern 一个合成场景测试（构造 ticks+events 输入） |
| 真实 demo 回归样例 | 现有 60-DP demo 切片标注 ≥10 条黄金样本（人工预标注后入库） |
| Validator 四态 | baseline / improvement / regression / insufficient data 各一测试 |
| 宏观 hindsight 泄漏 | MACRO_DESIGN §7 的三类测试（隔离/白名单/回归） |
