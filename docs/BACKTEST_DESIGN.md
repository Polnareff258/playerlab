# BACKTEST_DESIGN.md — 阶段 4：反事实验证设计

> 反事实是整个项目最容易「看起来聪明但其实不可靠」的部分。本文件把 spec §26（Historical Holdout / Retrieval QA / Ablation）与 §12（验证标准）落成可执行、可判定的验证协议与发布门槛。
> 原则：**任何进入 V1 主界面的反事实输出，必须通过下述验证；未验证的能力标记 unvalidated，不展示。**

---

## 1. 验证目标与总则

| 目标 | 判据 |
| --- | --- |
| 结果可校准 | 预测的生存/胜率概率与实际结果一致（分桶校准） |
| 检索语义正确 | top-k 相似状态在 CS2 语义上真的相似（人工 QA） |
| 特征有增益 | 每个特征子集对检索/预测的真实贡献可测量（ablation） |
| 确定性可复现 | 同一输入 → 逐字节相同输出（管线确定性测试） |
| 纪律可审计 | 证据不足时固定返回 INSUFFICIENT_EVIDENCE（不生成貌似合理的答案） |

---

## 2. Historical Holdout（历史留出法）

### 目标
在**不暴露决策后结果**的前提下，用其他历史样本预测某 DecisionPoint 各动作族的 outcome 分布，再与真实 outcome 对比。

### 协议
1. **数据组织**：DecisionState DB 按 (match, round, DP) 索引；每个 DP 含 pre-decision PlayerKnownState + 公开信息 + 各动作族 outcome（survival@W / duel_outcome / round_win）。
2. **划分（两层，都要跑）**：
   - **Leave-one-match-out (LOMO)**：测试一场完整比赛的所有 DP，训练用其余全部场次 —— 防同场泄漏（同场样本高度相关）。
   - **Temporal split**：按比赛时间排序，前 80% 训练、后 20% 测试 —— 模拟真实使用场景（只能看到过去）。
3. **查询遮罩**：测试 DP 只暴露 decision 前状态（PlayerKnownState 派生特征 + 公开信息）；GroundTruth outcome 仅用于对照。
4. **预测**：从训练集检索相似状态（同一检索管线），按动作族聚合 outcome 分布（Wilson 区间），输出每个动作族的预测概率。
5. **对照**：与测试 DP 的**实际观测动作的**真实 outcome 对比（注：反事实备选动作的真实结果不可观测，本协议只校准「观测动作」的预测；备选动作的验证靠 Retrieval QA + 描述性口径）。
6. **指标**：
   - **分桶校准**：按预测概率分 5 桶，各桶内实际结果率与预测概率差 ≤ ±10pp 视为校准通过（survival@W 与 round_win 分别评估）。
   - **Brier score / log-loss**：预测分布 vs 实际（0/1），基准 = 训练集基率（majority baseline）；需显著优于基准。
   - **CI**：bootstrap（1000 次）报告不确定区间；样本不足单元跳过并计入「未覆盖」。
7. **通过门槛（V1 发布用）**：LOMO 校准通过单元 ≥ 70%；Brier 优于基准；未覆盖单元占比如实报告（不隐藏）。

### 实现要点
- 检索管线与查询管线**共用同一代码路径**（防止"训练时用了一套、发布时用另一套"）。
- 结果落盘为 `backtest_report.json`（每单元：n、预测 vs 实际、校准桶、Brier、CI），进 CI 回归。

---

## 3. Retrieval QA（检索质量人工抽样）

### 目标
程序化相似度可能数值漂亮但语义荒谬，必须人工抽检 top-k 是否真的相似。

### 协议
1. **抽样**：分层抽样查询状态 —— 每张支持地图 × 每侧 × 每 zone × 每动作族 ≥ 2 个查询；目标单轮 QA 200–300 条。
2. **标注**：导出每条查询的 top-5 相似状态（含状态摘要：地图/侧/zone/时间/alive/HP/武器/队友结构/已知敌方信息/接触），由**有 CS2 经验的标注者**按 1–5 打分「在 CS2 语义上是否相似」（5=非常相似）。
3. **判据（V1 门槛）**：top-5 中 ≥3 条得分 ≥3 的查询占比 ≥ 80%；top-1 得分 ≥3 占比 ≥ 90%。
4. **配套 sanity check（自动）**：
   - 自相似：状态与自身 top-1 应是自己（特征向量唯一性）。
   - 同族倾向：top-k 的动作族分布应与查询一致或合理（同状态、不同动作样本均需出现，否则检索有偏）。
   - 地图/侧/zone hard filter 零违规。
5. **输出**：`retrieval_qa_batch.json`（每条：查询、top-k、分数、标注人、备注），进 review 流程。

---

## 4. Ablation（特征消融）

### 目标
判断哪些特征真正提升检索/预测，为权重配置与后续学习提供依据；同时防「特征堆砌」的假增益。

### 协议（特征子集阶梯，spec §26）
| 子集 | 包含 |
| --- | --- |
| A: position only | map, side, zone, 玩家坐标桶 |
| B: +time | + round_time_bucket |
| C: +team structure | + teammate_structure, alive_count |
| D: +state | + HP, weapon, utility, economy |
| E: full | + known_enemy_info, recent_contact, bomb_state, engagement_type |

1. 每个子集在**同一 holdout 划分**上跑检索 + 预测，比较：Retrieval QA 分数、校准、Brier。
2. 每加一层特征需证明**非负增益**（CI 不劣于上一级）；负增益特征降权或移除。
3. 权重敏感性：每个软特征权重 ±50% 扫描，报告检索质量波动（稳定性检查）。
4. 输出：`ablation_report.md`（每级：指标表 + 结论 + 保留/降权建议）。

---

## 5. 反事实结论有效性门槛（§12 落地）

每条 CounterfactualResult 必须满足（否则降级/不展示）：
1. n ≥ n_min_claim（默认 10），每动作族 n ≥ n_min_action（默认 5）。
2. 预测含 Wilson 区间；区间重叠 → NO_RELIABLE_DIFFERENCE。
3. Decision 层只用 PlayerKnownState 特征（审计断言通过）。
4. outcome 窗口固定（survival@W 定义一致）。
5. 证据强度块完整：n、高相似样本数、相似度分布、每动作 n、outcome 分布、confidence、confounders、missing info。
6. 可复现：同 demo 同 config → 同输出（哈希断言）。

---

## 6. 验证流水线（CI 回归）

```
ingest(demo fixture) → build DecisionState DB
→ holdout eval (LOMO + temporal) → calibration/Brier 断言
→ retrieval QA batch 导出（人工标注，非阻塞门）
→ ablation 阶梯跑批 → ablation_report.md
→ reproducibility hash 断言
```
- Golden fixtures：从 spike demo 切出的 2–3 个 round 切片（结构化 DecisionState 快照），保证离线可跑、秒级完成。
- 所有阈值（n_min、pp 容差、QA 门槛）集中在 `config/validation.yml`，可调且版本化。

---

## 7. V1 发布门槛（汇总）

| 项 | 门槛 |
| --- | --- |
| 校准 | LOMO 通过单元 ≥70%，偏差 ≤±10pp |
| 预测质量 | Brier 优于 majority baseline |
| 检索语义 | top-5 ≥3/5 查询占比 ≥80%（≥150 条有效标注） |
| 特征消融 | 无显著负增益特征（或已降权并记录） |
| 确定性 | 复现 hash 断言通过 |
| 纪律 | 样本不足单元 100% 返回 INSUFFICIENT_EVIDENCE（自动化断言） |

> 若任一门槛不满足：该能力标记 unvalidated 或降级为「实验性」，不进 V1 主界面 —— 这比上线一个自我感觉良好的反事实系统重要得多。
