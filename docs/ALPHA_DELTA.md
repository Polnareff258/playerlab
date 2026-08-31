# ALPHA_DELTA.md — Phase A：V1.1-alpha 与既有 V1.1 设计的增量说明

> 依据：V1_1_MVP.md / IMPROVEMENT_MODEL.md / MACRO_DECISION_DESIGN.md / IMPLEMENTATION_PLAN.md。
> 结论：alpha 是 V1.1 的**收窄首演**——保留核心闭环与数据对象，删减全部宏观冗余，新增 Human Annotation Loop。

---

## 1. 保留（直接沿用既有设计）

| 设计 | 保留内容 |
| --- | --- |
| Decision Hierarchy | Micro/Local/Macro 三级标签概念；alpha 只落地 Micro + Macro 两级（Local 由 overstay 承载，后置） |
| Root Cause Chain | 链条结构保留，但**简化 4 层**（Result→Execution→Micro→Macro），允许 UNKNOWN（spec §6） |
| Pattern 原则 | 「不允许只看死亡结果」：Behavior Detection 与 Decision Evaluation 分离（spec §8） |
| Bottleneck 概念 | Frequency/Impact/Confidence/Trainability 四分量计算保留，**输出降为 HIGH/MEDIUM/LOW + 可解释**（spec §9） |
| TrainingTarget | Schema 全字段保留；Active Focus ≤2（1 Micro/Execution + 1 Macro）；三通道验证（Behavior/Execution/Outcome） |
| Counterfactual 作为证据 | Pattern 的 counterfactual_support 复用现有引擎（STRONG/WEAK/INSUFFICIENT） |
| Token/LLM 边界 | 全部检测/测量/排序/验证确定性；LLM 仅措辞与解释 |
| hindsight 守卫 | PlayerKnownState 白名单不变；宏观判定不读敌人真相 |

## 2. 推迟（沿用完整 V1.1 设计，alpha 不做）

- 完整 Rotation 分类（early/late/fake/unnecessary）、完整 Map Control Responsibility、完整 Spacing/Trade 模型、完整 Timing 模型、完整 Information Discipline 双模式（只做 Advantage 一项宏观）
- Pattern 清单从 8 个收窄到 **3 个**
- 完整 BottleneckScore 乘法公式的 UI 主角地位（alpha 只用三档等级）
- 完整 Root Cause 5 层（含 Local 层）与 Preference 学习
- Longitudinal 完整 timeline（alpha 只保留 target 状态流转）

## 3. 新增（alpha 特有，V1.1 设计未覆盖）

| 新增 | 说明 |
| --- | --- |
| Human Annotation Loop | HumanAnnotation / PreferenceAnnotation / ReviewQueue / Review Budget（3–5/场）/ Review UI / JSONL 导出 / 标注统计（spec §17–§30、§34–§36、§38–§39） |
| Model/Rule Versioning | 每条 annotation 保存 model_version/rule_version/config_version（spec §28） |
| 黄金样本集 | spike/golden_alpha.json（15 条：5 re-peek / 5 execution / 5 advantage，HumanAnnotation schema，spec §43） |
| Alpha Pipeline | batch 集成 `alpha` 阶段：execution → patterns → rootcause → bottleneck → targets → review queue（spec §34） |

## 4. 明确禁止（spec §46）

完整 rotation/map-control/spacing/trade 模型、Aim Lab/Kovaak、Pro Demo 爬虫、Pro Reference、Skill Model、LLM fine-tuning、online learning、multi-agent coaching、跨游戏、video/VLM。**人工反馈不自动改模型**（spec §27）。

## 5. 验收路径（spec §44–§45）

- Loop A：多场 → 检测 immediate re-peek → TrainingTarget → 后续窗口 → bad re-peek 率下降 → 三通道验证
- Loop B：保存 prediction + human correction + version + reason code → 输出 human agreement 统计（如 RE_PEEK 82%、Advantage 61%）→ 指引下一版优化目标
- 数据不足时明确 INSUFFICIENT_EVIDENCE（不硬凑结论）
