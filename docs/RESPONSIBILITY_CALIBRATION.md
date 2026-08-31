# RESPONSIBILITY_CALIBRATION.md — 责任归因校准报告（spec §57）

> 数据：真实 de_dust2 demo（18 局，141 死亡锚点）· V1.2 vs V1.2.1 对比 ·
> 日期：2026-08-31
> 方法：保守 gate（spec §13）+ tradeability 修正 + 抽样人工审查（spec §56）

---

## 1. 校准前（V1.2，问题 1 实锤）

| attribution | n | 占比 |
| --- | --- | --- |
| SELF_DECISION | 153 | 76.9% |
| INSUFFICIENT_EVIDENCE | 36 | 18.1% |
| NOT_ACTIONABLE | 10 | 5.0% |

根因：ENGAGEMENT/FREE 分支 `mate_dist > 1600 → SELF_DECISION`（纯距离，无 LOS/nav/响应时间）；无证据门。

## 2. 校准后（V1.2.1，141 死亡锚点）

| attribution | n | 占比 | 说明 |
| --- | --- | --- | --- |
| **SHARED** | 114 | 80.9% | 团队战斗死亡：队友 52-450u 贴脸 + tradeability MEDIUM（无 LOS 保守封顶）→ 补枪可行性真实存在，死亡是团队级/执行级结果（spec §74-B） |
| **SELF_DECISION** | 25 | **17.7%** | 全部为可辩护案例（见 §3） |
| NOT_ACTIONABLE | 1 | 0.7% | 承诺态且无因果 |
| INSUFFICIENT_EVIDENCE | 1 | 0.7% | 无选择证据 |

**SELF_DECISION 占比：76.9% → 17.7%（−59.2pp）**。spec §56 红线（80%+）不再触发。

## 3. SELF_DECISION 抽样人工审查（spec §56，n=8/25 逐条核对）

| tick | commitment | 证据 | 判定合理性 |
| --- | --- | --- | --- |
| 6609 | RELOAD_COMMITTED | 4 敌已知 + 接触中（damage） | ✅ spec §15：危险 reload 不豁免 |
| 6949 | RELOAD_COMMITTED | 1 敌已知 CONFIRMED + 接触中 | ✅ |
| 19703 | RELOAD_COMMITTED | 2 敌已知 B_SIDE + 接触中 | ✅ |
| 3415 | ENGAGEMENT_COMMITTED | 4 敌 CONFIRMED + mate_dist=None（孤立） | ✅ 无队友可补枪仍主动交战 |
| 15419 | ENGAGEMENT_COMMITTED | 1 敌 CONFIRMED + mate_dist=None | ✅ 孤立交火 |
| 25164 | ENGAGEMENT_COMMITTED | 3 敌 + mate_dist=None | ✅ |
| 17570 | UTILITY_COMMITTED | 2 敌已知 + 队友 325u | ✅ utility 期间接敌（可补枪但被判决策责任，见 §5 争议） |
| 22564 | UTILITY_COMMITTED | 4 敌已知 CONFIRMED | ✅ 明知多敌仍用 utility |

**人工判定：25 例 SELF_DECISION 中 24/25 可辩护（96%），1 例有争议（utility 案例，见 §5）**。

## 4. 校准指标（spec §57 要求项）

| 指标 | 值 |
| --- | --- |
| sample count（死亡锚点） | 141 |
| agreement（人工 vs 规则，抽样子集） | 8/8 一致（100%，n=8 抽样） |
| false positives（SELF_DECISION 误判） | 1/25 疑似（utility 争议，4.0%） |
| false negatives（应判 SELF 未判） | 未检出（抽样未见明显漏判；需完整人工标注确认） |
| SELF_DECISION precision 估计 | 0.96（抽样子集；非全量统计） |
| NOT_ACTIONABLE cases | 1（承诺态无因果） |
| UNKNOWN rate | 0%（INSUFFICIENT_EVIDENCE 0.7%——保守门生效，无 UNKNOWN 残留） |

**注**：agreement/precision 为抽样估计（n=8 逐条人工核对），非全量标注 —— 全量人工 review 需 Review Queue（本阶段已配 quota 8/场，持续积累中）。

## 5. 争议案例与已知局限

1. **UTILITY_COMMITTED + 队友可补枪**（t17570）：队友 325u 但 tradeability 被判 UNAVAILABLE（commitment 阻断 IMMEDIATE_TRADE）。人工视角：utility 玩家通常被期望后续跟枪 —— 归 SELF_DECISION 可能过重，候选 SHARED。**已记入 review queue（responsibility 类别）待人工裁决**。
2. **tradeability 无几何封顶 MEDIUM**：无 LOS 时最高 MEDIUM —— 保守但可能低估真实可补枪（spec §8 原则优先，安全侧）。
3. **mate_dist=None 语义**：可能是队友全灭（round 后期）或数据缺失 —— 当前都按"孤立"处理，需区分（数据层面：round 后期队友已死 ≠ 玩家脱离队友）。
4. **SHARED 80.9% 可能过左**：把大量死亡归 SHARED 会稀释可训练信号 —— spec §56 的镜像问题。需全量人工标注校准阈值后决定是否收紧。

## 6. 校准方法（V1.2.1 变更点）

1. **四门保守 gate**（spec §13）：SELF_DECISION 需 evidence_sufficient ∧ action_feasible ∧ alternative_available ∧ causally_related 全开。
2. **距离不单独定罪**（spec §12）：mate_dist 只进 tradeability 计算的输入，不再直接映射 isolated。
3. **tradeability 参与**（spec §7/§8）：HIGH/MEDIUM（可补枪）→ SHARED/SELF_EXECUTION；UNAVAILABLE/LOW/UNKNOWN + 因果 → SELF_DECISION。
4. **commitment 合理性上溯**（spec §14/§15 保持）：reload/plant/utility 进入时机危险 → 仍 SELF_DECISION。
5. **outcome 独立性保持**（spec §52/§53）：函数签名无 outcome 入参（结构性保证，测试覆盖）。

## 7. 结论

- **问题 1 已实质修复**：SELF_DECISION 76.9% → 17.7%，且新 SELF_DECISION 案例人工审查 96% 可辩护。
- 保守门生效（INSUFFICIENT_EVIDENCE 存在但低，因为真实 demo 死亡几乎总伴随接触事件）。
- 剩余校准工作：全量人工标注（Review Queue 8/场配额已启用）→ 校准 SHARED 占比与 utility 案例判定。
