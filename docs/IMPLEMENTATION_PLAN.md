# IMPLEMENTATION_PLAN.md — Phase 6：V1.1 实现计划

> 范围 = V1_1_MVP.md 选定能力。**本文件完成后暂停，等待人工确认，不直接进入大规模开发。**

---

## 1. 新模块（core/playerlab/）

| 模块 | 职责 | 依赖 |
| --- | --- | --- |
| `execution.py` | 执行指标：move-and-shoot、counter-strafe quality、first-shot timing、same-angle repeat 计数 | decision.py（episode）、ingest events |
| `hierarchy.py` | Decision Hierarchy 标注：DP → micro/local/macro 标签 + 关联 | decision.py、execution.py |
| `macro/`（包） | 宏观分析六模块（info.py / rotation.py / advantage.py / spacing.py / mapcontrol.py / timing.py） | state.py（KnownState/PublicInfo）、zones.py |
| `rootcause.py` | Root Cause Chain 构建（Result→Immediate→Execution→Micro→Local→Macro） | outcomes、execution、hierarchy、macro |
| `patterns.py` | Pattern Miner：8 个模式检测 + 反事实支持 + 反例收集 | counterfactual、macro、execution、stats |
| `bottleneck.py` | BottleneckScore 排序（Frequency×Impact×Confidence×Trainability，可展开） | patterns、stats |
| `training.py` | TrainingTarget 对象 + Validator（测量窗口、三通道 verdict、状态转移）+ Active Focus | bottleneck、patterns、db |
| `longitudinal.py` | target timeline / status history 读取（供 UI） | db |

## 2. 文件变更清单

```
core/playerlab/
  ├── execution.py            (新)
  ├── hierarchy.py            (新)
  ├── rootcause.py            (新)
  ├── patterns.py             (新)
  ├── bottleneck.py           (新)
  ├── training.py             (新)
  ├── longitudinal.py         (新)
  ├── macro/
  │   ├── __init__.py
  │   ├── info.py             (信息纪律)
  │   ├── rotation.py         (旋转质量)
  │   ├── advantage.py        (优势管理)
  │   ├── spacing.py          (间距/可换人)
  │   ├── mapcontrol.py       (区域控制)
  │   └── timing.py           (时机上下文)
  ├── db.py                   (改：新表 + 迁移)
  ├── cli.py                  (改：新命令)
  ├── api.py                  (改：新路由)
  ├── batch.py                (改：分析后触发 pattern/target 更新)
  └── config.py               (改：新模式阈值/权重)
ui/index.html                 (改：首页 CURRENT FOCUS + Root Cause 面板)
docs/V1_1_AUDIT.md …          (本批 6 份设计文档)
tests/test_v1_1.py            (新：模式/验证/宏观 hindsight 测试)
spike/golden_v1_1.json        (新：真实 demo 黄金标注 ≥10 条)
```

## 3. Schema 变更与迁移

**新表**（SQLite，全部带 `match_id/round/tick` 追溯链）：
| 表 | 关键列 |
| --- | --- |
| `execution_metrics` | dp_id, metric, value, threshold, violation, evidence_ticks, match_id, round, tick |
| `root_causes` | event_id, result, immediate, execution, micro, local, macro, primary, secondary, mechanical, confidence |
| `patterns` | id, name, category, trigger, behavior, sample_count, frequency, negative_outcome_rate, baseline_rate, relative_risk, counterfactual_support, confidence, affected_contexts(JSON) |
| `pattern_evidence` | pattern_id, kind(supporting|counter), match_id, round, tick, dp_id, detail |
| `bottlenecks` | id, pattern_id, score, f, i, c, t, ranked_at, active |
| `training_targets` | id, name, category, source_pattern_ids, root_cause, trigger, undesired_behavior, target_behavior, baseline, goal, measurement_definition, measurement_window, created_at, status, progress, confidence, next_match_cue(JSON) |
| `target_measurements` | target_id, window_start, window_end, n, rate, ci, vs_baseline_delta, behavior_verdict, execution_verdict, outcome_verdict |
| `target_status_history` | target_id, status, from_status, at, reason |

**迁移机制**：`db.py` 增加 `schema_version` 表 + 版本化 DDL 迁移器（V1=1 → V1.1=2）；启动/CLI 时自动执行幂等 DDL。**不破坏现有 V1 表**。

## 4. 管线集成

```
batch ingest 完成一场
 → execution 指标计算（每 DP）
 → hierarchy 标注
 → macro 分析（每回合状态机）
 → root cause（每死亡事件）
 → patterns 重算（跨场聚合 + counterfactual 支持）
 → bottlenecks 重排
 → training targets：新目标生成 / ACTIVE 目标窗口推进
 → validation：窗口达标 → 状态转移
 → coverage/timeline 更新
```
- `batch.py` 在每场分析后调用 `pipeline_update(db, cfg)`（新增函数），保证「入库即更新改进闭环」。
- counterfactual 引擎被 patterns 复用（按模式聚合，非单 DP）。

## 5. CLI / API / UI

- **CLI 新命令**：`patterns`（列模式+支持度）、`bottlenecks`（Top-N 排序+分量展开）、`targets`（列目标）、`target create|validate <id>`、`focus`（当前 ACTIVE）。
- **API 新路由**：`/api/focus`、`/api/patterns`、`/api/bottlenecks`、`/api/targets/{id}`、`/api/targets/{id}/validate`、`/api/events/{dp_id}/root-cause`。
- **UI**：
  - 首页改造：CURRENT FOCUS（≤2 目标卡：name/progress/baseline/current/goal + WHY THIS? 展开：Frequency/Impact/Evidence/Counterfactual support + Next Match Cue：WHEN/DO/AVOID）→ Recent Matches 折叠到底部。
  - Match Review：死亡事件卡片加 Root Cause Chain（Result/Immediate/Execution/Micro/Local/Macro + Primary/Secondary/Mechanical + Active Target 命中标记）。

## 6. 测试计划（spec §32）

| 测试文件 | 内容 |
| --- | --- |
| `tests/test_execution.py` | 4 项执行指标：合成 ticks+events（move-and-shoot 正反例、counter-strafe 速度曲线、first-shot timing、same-angle 计数） |
| `tests/test_patterns.py` | 8 模式各一个合成场景；反例收集；counterfactual_support 三态；「不看 outcome 只看模式」断言（正结果样本计数） |
| `tests/test_training.py` | Validator 四态：baseline / improvement / regression / insufficient_data；状态转移全路径；Active Focus 上限 2 |
| `tests/test_macro_hindsight.py` | 三类：①GroundTruth vs KnownState 不一致的隔离用例；②判定函数白名单断言（入参仅 known/public）；③真实 demo 黄金标注回归 |
| `tests/test_rootcause.py` | 链构建：完整 4 层 / 缺层→UNKNOWN / 上游优先规则 |
| `tests/test_migration.py` | V1 库 → V1.1 迁移：现有表保留、新表创建、幂等 |

**黄金样本**：`spike/golden_v1_1.json` 从现有 60-DP demo 切片人工标注 ≥10 条（每模式 ≥1），进 CI 回归。

## 7. Token / LLM 边界（§27）

- **确定性**：全部指标/模式/排序/验证/状态（上表所有模块）零 LLM。
- **LLM（Coach 层，可关）**：Pattern explanation、Root-cause 一句话合成、TrainingTarget 措辞与 Next Match Cue、同分 Bottleneck 的假设比较。
- 输入仅结构化对象（pattern/root-cause/evidence 摘要），预算沿用：max_evidence_items=20、max_tokens=2000、每次查询 ≤2 次 LLM 调用；证据不足直接返回确定性 verdict，不调 LLM。
- **不建多 agent**：Analyzer（确定性）→ Reasoner（规则）→ Coach（LLM 措辞），三个逻辑层，非独立 agent。

## 8. 里程碑（估算）

| 里程碑 | 内容 | 估时 |
| --- | --- | --- |
| M1 | schema 迁移 + execution/hierarchy + macro 六模块 + 单测 | 4–5 天 |
| M2 | rootcause + patterns + bottleneck + 单测/黄金标注 | 3–4 天 |
| M3 | training validator + longitudinal + Active Focus + 单测 | 3–4 天 |
| M4 | batch 集成 + CLI/API + UI 首页与 Root Cause 面板 | 3–4 天 |
| M5 | 多场真实数据端到端验证（pattern→target→validate）+ 回归 | 2–3 天 |

总计约 **4–5 周（单人全职）**；M5 是 §33 成功标准的验收路径。

## 9. 暂停点

本计划完成后暂停，等待人工确认后再进入 M1 实现。
