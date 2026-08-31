# IMPROVEMENT_MODEL.md — Phase 3：改进模型设计

> 覆盖 spec §3–§6、§8–§20、§23、§27–§30 的设计落地。核心原则：**Evidence before advice；One bottleneck at a time；Behavior must be measurable；Unknown is better than hallucinated。**
> 全部决策/模式/目标对象为确定性规则产出；LLM 只做解释性文字（§27），且不参与任何统计判定。

---

## 1. Decision Hierarchy（三级决策，spec §4）

在现有 DP（动作族）之上增加两个层级。**V1.1 每个被分析的对象都带 `hierarchy` 标签**：

| 层级 | 定义 | V1.1 内容 | 数据来源 |
| --- | --- | --- | --- |
| **Micro** | 局部操作 | 现有五动作族 + 执行指标：move-and-shoot、counter-strafe、first-shot、same-angle repeat、shot timing | 现有 DP 检测器 + 新增 execution 指标（见 §3） |
| **Local** | 局部区域内的决策 | reposition、utility-then-engage、stay/leave position、follow-up after contact、local push/retreat | 由 Micro 序列 + 区域上下文推导（确定性规则） |
| **Macro** | 整回合/大局 | rotate（full/soft/early/late/fake-induced/unnecessary/no-response）、advantage management、information response、map-control responsibility | 回合级状态机 + PlayerKnownState（见 MACRO_DECISION_DESIGN.md） |

**关联**：一次死亡可以同时有 Micro/Local/Macro 判定，但**只有其中一层是 Primary Root Cause**（§20 上游优先规则）。

---

## 2. Root Cause Chain（spec §5）

对每个「重要事件」（死亡 / 失败交火 / 低质量回合）构建因果链。链是**确定性组合**，每层带 evidence + confidence，允许 UNKNOWN：

```
Result          (death | lost_duel | lost_round | positional_loss)
↓
Immediate       (lost duel / traded / utility died / timing lost)
↓
Execution       (move-and-shoot | poor counter-strafe | first-shot miss | …)   ← 可缺失
↓
Micro Cause     (RE_PEEK | PEEK | HOLD | DISENGAGE | FALLBACK | …)
↓
Local Cause     (unsupported contest | failed reposition | no utility reset | …)
↓
Macro Cause     (poor advantage management | slow information response | unnecessary rotate | …)
```

**输出约定**（spec §5 末）：
- `primary_root_cause`：最上游、且可训练、且证据足够的一层（§20 规则）
- `secondary_cause`：同链上相邻的可训练层（如 primary=RE_PEEK 时 secondary=counter-strafe）
- `mechanical_cause`：执行层问题（若存在）
- 每层缺失或证据不足 → `UNKNOWN` / `INSUFFICIENT_EVIDENCE`（**禁止编造完整 4 层**）

**构建规则（确定性）**：
1. Result 来自 outcome（death_tick / duel_result / round_win）。
2. Immediate 来自 duel 归属（lost/won/undefined）+ 死亡方式（weapon、距离、through smoke 等）。
3. Execution 来自死亡 tick 附近的执行指标（§3）——无指标/无开枪 → 该层 UNKNOWN。
4. Micro 来自死亡关联的 DP（死亡 tick 落在某 DP 窗口内）。
5. Local 来自 DP 上下文：teammates 距离（有无支援）、utility 剩余、接触后是否 reposition（位移轨迹）。
6. Macro 来自回合级状态机：优势/信息/旋转状态（见 MACRO_DECISION_DESIGN）。
7. **层级优先级（§20）**：Macro > Local > Micro > Execution，但仅当选中的层级 `trainability 高 且 confidence ≥ 门槛`；否则下移一层。**不要永远优先机械执行问题。**

---

## 3. Execution 指标（spec §6 强化）

V1.1 新增（全部从现有 tick 数据计算，无新解析器依赖）：
- **move-and-shoot**：首次射击（weapon_fire 事件）前 ≤N tick 内水平速度 > 阈值（config，如 120 u/s）→ violation
- **counter-strafe quality**：射击前速度轨迹——最近静止时刻到射击时刻的 tick 数、速度衰减曲线；`shot_while_moving = 速度@shot > 阈值`
- **first-shot timing**：首次伤害 tick − 首次可见/接触 tick（PlayerKnownState 判定）→ 反应时间
- **same-angle repeat**：同一 episode 内 yaw 回到接触角度的次数（现有 RE_PEEK 谓词的自然扩展，跨 DP 聚合）
- **shot timing**：每次射击与其后首次命中/死亡的间隔

每条执行指标：`{dp_id, metric, value, threshold, violation: bool, evidence_ticks}`。
**Decision vs Execution 四分类**（spec §6）：`good/bad × good/poor`，判定 = Decision 层（反事实支持，§6）∧ Execution 层（执行指标违规）。**death 不自动 ⇒ decision bad**（outcome 独立于分类）。

---

## 4. Pattern（spec §8–§9）

### 4.1 Schema（§8 字段全部实现，JSON）
```
Pattern {
  id, name, category: micro|local|macro|execution,
  trigger, behavior,                 // 可读描述
  sample_count, frequency,           // 次/场（Wilson CI）
  negative_outcome_rate,             // 该模式下的死亡/失利率（含 CI）
  baseline_rate,                     // 无模式对照率（同状态非模式样本）
  relative_risk,                     // negative_outcome_rate / baseline_rate
  counterfactual_support,            // STRONG | WEAK | INSUFFICIENT（§6）
  confidence,                        // 样本×相似度×指标可靠性合成（确定性）
  supporting_evidence,               // [{match, round, tick, dp_id, detail}]
  counter_evidence,                  // 反例（模式出现但正面结果的样本）
  affected_contexts,                 // [{map, side, zone, alive_bucket, weapon_class}]
}
```

### 4.2 不允许只看 Outcome（spec §9）
- 模式计数**必须**带 `counterfactual_support`：该行为与同状态备选动作的结果差（复用 counterfactual 引擎）。
- `relative_risk` 基于**状态相似**的对照样本，而非全局基率。
- 反例（counter_evidence）必须展示：模式出现但存活/赢下的样本——防止「re-peek 死了 ⇒ re-peek 错」的循环推理。
- 若 counterfactual 样本不足：`counterfactual_support = INSUFFICIENT`，且 **Bottleneck 排序中该模式 Confidence 上限 0.4**（§10：不要凭感觉提高优先级）。

### 4.3 V1.1 Pattern 清单（spec §8 第一阶段）
| id | name | category | 检测依据 |
| --- | --- | --- | --- |
| p_repeek | immediate same-angle re-peek | micro | RE_PEEK DP + 反事实支持 |
| p_same_angle | same-angle repeat | micro | 同 episode 多 RE_PEEK |
| p_move_shoot | move-and-shoot first shot | execution | §3 指标 |
| p_counter_strafe | poor counter-strafe | execution | §3 指标 |
| p_overstay | overstay after contact | local | 接触后无 reposition/utility，停留 > 阈值 |
| p_adv_overaggro | overaggressive advantage play | macro | MACRO_DESIGN §Advantage |
| p_info_slow | slow response to strong information | macro | MACRO_DESIGN §Information |
| p_info_overreact | overreaction to weak information | macro | MACRO_DESIGN §Information |
| p_isolated_duel | isolated duel tendency | local | teammates 距离 > 阈值时的 duel |

（V1.1 MVP 只启用前 6 个，见 V1_1_MVP.md。）

---

## 5. Bottleneck Ranking（spec §11）

### 5.1 BottleneckScore（可展开，非黑盒）
```
BottleneckScore = Frequency^wf × Impact^wi × Confidence^wc × Trainability^wt
（权重 wf/wi/wc/wt ∈ config，默认 1.0；各分量 0..1，乘积天然 0..1）
```
每个分量**必须可展开**（UI 显示构成）：
- **Frequency**：`min(1, rate / rate_scale)`，rate=次/场（Wilson 中位估计）
- **Impact**：`relative_risk 关联度` = 模式样本中 (death|round_loss) 比例 vs 对照，取提升量（0..1 归一）；另计 positional/map-control loss（若有 Macro 指标）
- **Confidence**：样本数（n≥30 满）、counterfactual_support（STRONG=1 / WEAK=0.6 / INSUFFICIENT 上限 0.4）、state-similarity 均值、指标可靠性（执行指标>宏观指标，规则表）
- **Trainability**：规则表（表驱动，可改）：
  | 模式 | trainability |
  | --- | --- |
  | immediate re-peek / same-angle / move-and-shoot / counter-strafe | 0.9（短期可改） |
  | overstay / isolated duel | 0.7 |
  | advantage management（个人层面） | 0.6 |
  | 需全队沟通的 rotation | 0.3 |

### 5.2 规则
- 一次只产出 Top-2 候选（1 Micro/Execution + 1 Macro/Local）——受 Active Focus 限制（§7）。
- 任何模式 `confidence < 0.4` 或 `sample_count < n_min_pattern`（默认 8）→ 不进入 Bottleneck 列表。

---

## 6. Counterfactual 作为诊断证据（spec §10）

对候选模式自动跑其动作族的反事实（复用 counterfactual.what_if，**按模式聚合**而非单 DP）：
```
Pattern: immediate re-peek
  RE_PEEK     n=37  survival=39% [CI]  round_win=43% [CI]
  DISENGAGE   n=29  survival=72% [CI]  round_win=59% [CI]
```
- `counterfactual_support = STRONG`：备选动作 n ≥ n_min_action 且 CI 不重叠且差 ≥ 效果量门槛（如 survival 差 ≥ 15pp）
- `WEAK`：备选 n 达标但 CI 重叠或差 < 门槛
- `INSUFFICIENT`：任何一侧 n < 门槛
- **样本不足 → 不得凭感觉提高优先级**（Confidence 上限 0.4，§4.2）。

---

## 7. TrainingTarget（spec §12–§16）

### 7.1 Schema（§12 字段全实现）
```
TrainingTarget {
  id, name, category: micro|local|macro|execution,
  source_pattern_ids[], root_cause,          // 来自 Root Cause Chain
  trigger, undesired_behavior, target_behavior,   // 可读 + 结构化（谓词可测）
  baseline, goal,                            // 率值（0..1）或次数；goal 为方向性
  measurement_definition,                    // 指标计算定义（可执行，供 validator）
  measurement_window,                        // 默认 next 5 matches（可配）
  created_at, status, progress,
  confidence, supporting_evidence,
  next_match_cue: { when, do, avoid },       // §21 首页 cue，规则生成 + LLM 措辞
}
```
### 7.2 Status（§18）
`ACTIVE → IMPROVING → MASTERED | FAILED_TO_TRANSFER | INSUFFICIENT_DATA | PAUSED | REPLACED`
转移规则（确定性，见 §8 Validator）：
- MASTERED：连续 2 个窗口达标且行为/结果均改善
- FAILED_TO_TRANSFER：≥3 个窗口行为未改善
- INSUFFICIENT_DATA：窗口内样本 < n_min_measure
- PAUSED/REPLACED：人工或系统（更高 Bottleneck 取代）操作

### 7.3 Active Focus（§16）
- **上限 2 个**：1 Micro/Execution + 1 Macro（可少不可多）。
- 新目标候选须 BottleneckScore 超过当前 ACTIVE 中最低者才可替换（REPLACED 流程）。

---

## 8. Improvement Validation（spec §17–§19，V1.1 最重要闭环）

### 8.1 测量窗口
- `measurement_window`：默认接下来 5 场；每个窗口结束时自动重测（batch 后触发）。
- 每窗口输出：`{window_start_match, window_end_match, n, rate, ci, vs_baseline_delta}`。

### 8.2 三通道分离（spec §19）
| 通道 | 度量 | verdict |
| --- | --- | --- |
| **Behavior Adoption** | 目标行为率（如 bad re-peek rate）是否向 goal 移动且 CI 不重叠 | BEHAVIOR_CHANGED / BEHAVIOR_UNCHANGED |
| **Execution Change** | 执行指标改善（如 move-and-shoot 违规率） | EXECUTION_IMPROVED / EXECUTION_UNCHANGED |
| **Outcome Change** | survival / round_win 变化（Wilson 差） | OUTCOME_IMPROVED / OUTCOME_UNCHANGED / OUTCOME_UNCERTAIN（n 不足） |

组合判定（§19 例）：
```
Behavior: improved strongly; Outcome: n 不足
→ BEHAVIOR_CHANGED + OUTCOME_UNCERTAIN（不判失败，不判成功）
```

### 8.3 确定性判定
- 全部用 Wilson CI 差（不重叠 + 效果量门槛），无 LLM。
- `progress = (baseline − current) / (baseline − goal)`，clamp [0,1]（方向敏感：target 是降率则反之）。

---

## 9. Longitudinal Progress（spec §23）

- `training_targets` 表 + `target_measurements` 表（每窗口一行）+ `target_status_history`（状态流转日志）。
- UI：CURRENT FOCUS 卡片显示 baseline → current → goal 的时间线（每窗口一个点）。
- **不做 Skill Model**（Aim/GameSense 综合分后置，§24）；先保证 target history 可靠。

---

## 10. 数据不足策略（spec §30）

| 情况 | 返回 |
| --- | --- |
| 总样本 < n_min_pattern | No TrainingTarget generated（明确输出空原因） |
| 某层因果证据不足 | 该层 UNKNOWN / INSUFFICIENT_EVIDENCE |
| 反事实备选不足 | counterfactual_support = INSUFFICIENT |
| 窗口测量样本不足 | status 保持，报告 INSUFFICIENT_DATA |
**禁止为了「每天有建议」而生成低质量目标。**

---

## 11. Token / LLM 边界（spec §27–§28）

- **确定性管线**（零 LLM）：parsing、geometry、事件、指标、模式计数、相似度、反事实检索、Bottleneck 算术、Validation 判定、状态转移。
- **LLM 仅**（输入全部为结构化对象，禁 raw tick）：
  - Pattern explanation（解释为什么这个模式存在）
  - Root-cause synthesis（把链转成一句话，引用各层证据 id）
  - TrainingTarget wording（trigger/undesired/target 的措辞 + Next Match Cue）
  - competing hypothesis comparison（仅当 ≥2 个同分 Bottleneck 时，比较解释）
- **架构**：Analyzer（确定性）→ Reasoner（规则排序）→ Coach（LLM 措辞层）——**不建多 agent 对话**。
- 硬预算沿用 V1：`max_evidence_items=20, max_similar_states=50, max_tokens=2000`；证据不足 → 不调 LLM 直接返回确定性 verdict。
