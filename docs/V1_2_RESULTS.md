# V1_2_RESULTS.md — Context & Intent Spike 实施结果（Phase A–I 完成）

> 状态：**Commitment / Feasibility / SituationalRole / Intent Rule Baseline / Responsibility Attribution / Human Annotation 升级 / Tiny Model 数据集 / Pro 接口 stub 全部实现并可运行**。
> 按 spec §62：本文件完成后暂停；不自动进入 Pro Demo Pipeline / 大规模模型训练 / 完整宏观评分。

---

## 1. 新增能力

| 能力 | 实现 | 文件 |
| --- | --- | --- |
| TemporalContext | 4s 窗口轨迹（位置归一化/速度/yaw/zone/事件/队友/已知敌/回合），未来数据绝不进入分类（§3） | context.py |
| CommitmentState | 11 态确定性检测（plant/defuse/reload/utility/engagement/free…，事件≠承诺，允许 UNKNOWN） | intent.py |
| ActionFeasibility | 6 态规则引擎（§45：PLANT_COMMITTED → trade 不可用；RELOAD_COMMITTED → shoot 暂不可用…） | feasibility.py |
| SituationalRole | 15 态动态职责 + 置信分布（§9–§11） | intent.py |
| Intent Rule Baseline | HOLD/REPOSITION/ROTATE/SOFT_ROTATE/GATHER_INFO/PLANT/SUPPORT/UNKNOWN + 概率分布 + AMBIGUOUS（§16–§17） | intent.py |
| ResponsibilityAttribution | 8 类 + commitment≠免责（§25）+ 团队级字段（§23 SHARED/TEAMMATE） | responsibility.py |
| Root Cause 升级 | 7 层（Result→Context→Commitment/Role→Execution→Micro→Macro→Responsibility），任意层 UNKNOWN | rootcause.py |
| 标注升级 | 新增 intent/situational_role/commitment_state/action_feasibility/responsibility 类型；ambiguity review（§46）；Preference UI（A/B 候选，§47） | annotation.py + ui |
| Tiny Model 数据集 | IntentSample 540 条（16 步 × 4Hz 归一化序列，§29–§30），JSONL/Parquet 导出（§49） | context_pipeline.py + cli |
| Reference 接口 | ReferenceCorpusProvider / DecisionSampleProvider / ReferencePolicyProvider + Null + LocalStub（§37–§42），主线零 Pro 依赖 | reference.py |

## 2. 测试情况（31 项全绿）

- `tests/test_v12.py` **11/11**：commitment（plant/reload/utility/free）、feasibility 规则、intent（**ROTATE vs REPOSITION vs HOLD 分类正确**）、responsibility（§23 plant-commit 队友死亡→planter NOT_ACTIONABLE + 团队级 SHARED；§24 reload 危险时机→SELF_DECISION 不豁免；§54/§55 outcome 独立——函数签名无 outcome 入参，结构性保证）、新标注类型、Reference provider
- `tests/test_alpha.py` **7/7**、`tests/test_core.py` **13/13** 回归通过
- 幂等性：context_events 199 条 / intent_samples 540 条 / review_queue 按场重建

## 3. 真实 Demo 结果（de_dust2，18 局）

| 量 | 值 | 说明 |
| --- | --- | --- |
| intent samples | 540（HOLD 225 / REPOSITION 255 / SOFT_ROTATE 14 / AMBIGUOUS 46） | **ROTATE=0**——本场无对侧强信息响应的长途旋转（诚实；需多场 + 人工验证） |
| context events | 199（死亡 + DP 锚点） | commitment：ENGAGEMENT 173 / RELOAD 9 / UTILITY 6 / FREE 9 / DEFUSE 1 / PLANT 1 |
| responsibility（死亡） | SELF_DECISION 119 / INSUFFICIENT_EVIDENCE 16 / NOT_ACTIONABLE 6 | 孤立交火主导；6 例承诺态免责 |
| review queue | 13 条（intent 10 / repeek 2 / advantage 1） | AMBIGUOUS intent 优先（§46） |
| 数据集导出 | intent_dataset.jsonl（540）+ responsibility_dataset.jsonl | JSONL 可用；parquet 依赖 pyarrow（已装） |

## 4. Success Criteria 对照（§63）

- **Scenario A（经过≠full rotate）**：✅ REPOSITION 分类正确（同区短位移，无对侧信号）；ROTATE 需 zc≥2 + 距离 + 对侧强信息 + 方向一致性——不会被「经过」误触发。
- **Scenario B（持续脱离响应强信息→ROTATE/SOFT_ROTATE）**：✅ 合成测试通过（bomb B + 跨区移动 + 方向一致 → ROTATE 1.0）；真实 demo 无样本（诚实输出 0）。
- **Scenario C（下包不背补枪锅）**：✅ planter 死亡 → NOT_ACTIONABLE；自由队友孤立交火 → SHARED（团队级字段）。
- **Scenario D（reload 承诺不豁免）**：✅ 敌已知在近 → SELF_DECISION（向上追溯 commitment 本身合理性）。

## 5. 已知局限（如实披露）

1. **ROTATE 检出率 = 0**（单场）：对侧信号条件严（bomb 对侧 或 ≥2 已知敌）+ 本场行为保守。需要更多场次 + intent 人工标注校准规则权重。
2. **责任归因 SELF_DECISION 占比高**（119/141 死亡）：ENGAGEMENT_COMMITTED + 孤立（队友>1600u）即判 SELF_DECISION——无几何 LOS 时「孤立」用距离近似（§44 LIMITATION），可能误判有墙后支援的玩家。
3. **无 LOS/nav 距离**：feasibility 的 trade/cover 判定是近似；未伪造精度（§44）。
4. **known_state 未接入 intent samples**（player_known_state={}）：特征序列为运动/结构特征；信息特征待 V1.3 接入。
5. **intent 黄金集 PARTIAL_DATASET**（§51）：单场仅能提供规则样本，人工标签 0 条——**模型 spike 门槛（≥200 标签）未达到 → INSUFFICIENT_DATA_FOR_MODEL_SPIKE**（§61 Phase H 按规则不硬训）。
6. review 预算下 intent 项挤占 pattern 项（13 条含 10 intent）——预算分配需后续调整。

## 6. 模型 Spike 判定（Phase H）

人工 intent 标签 = 0 < 200 → **INSUFFICIENT_DATA_FOR_MODEL_SPIKE**。数据集管线（特征序列/归一化/导出）已就绪，标签积累后即可跑 Rules vs XGBoost vs GRU/TCN vs Tiny Transformer 对照（§31–§33）。

## 7. 下一步建议（优先级）

1. **多场入库 + intent 人工标注**（Review UI 已支持 intent 标注与 Preference）→ 达到 200 标签后跑模型 spike
2. **责任归因阈值校准**（用标注数据调 commitment/孤立判定，threshold calibration）
3. **LOS 原语接入评估**（awpy .tri BVH 成本调研；接入后 trade/cover 判定升级）
4. intent 特征接入 known_state 信息特征（V1.3）

## 8. 运行方式

```powershell
cd playerlab\core
python3 -m playerlab.cli alpha "path\demo.dem"     # 全管线（含 context/intent/feasibility/responsibility）
python3 -m playerlab.cli context-eval              # 各类型 agreement
python3 -m playerlab.cli intent-dataset --out ..\backtest\intent_dataset.jsonl
python3 -m playerlab.cli responsibility-dataset --out ..\backtest\resp.jsonl
python3 -m playerlab.cli api --port 8125           # Review 页含 intent 标注与 Preference A/B
```
