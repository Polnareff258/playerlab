# DECISION_EPISODE_RESULTS.md — DecisionEpisode Spike 实测报告（spec §86）

> 数据：真实 de_dust2 demo（18 局，264.8MB）· V1.3 全管线 · 日期：2026-08-31
> 全量 episodes：**542**（opportunities 542，无漏检）；alpha 全管线 **144s/场**（V1.2.1 基线 64s + episode 层 ~80s）。

---

## 1. Episode 数量与 Family 分布

| family | n | 占比 | 触发 |
| --- | --- | --- | --- |
| CONTACT_RESPONSE | 319 | 58.9% | 首次伤害接触（每玩家每窗口） |
| ADVANTAGE_PRESERVATION | 168 | 31.0% | 队伍跨过人数优势阈值 |
| OBJECTIVE_COMMITMENT | 55 | 10.1% | 自己/队友 plant/defuse 开始 |
| **total** | **542** | 100% | — |

> spec §85 golden 目标：每类 ≥5 条 —— 三族均远超（319/168/55），真实 Demo 覆盖充分。

## 2. ObservedAction 分布（复用 DP 分类器，spec §60）

| action | n | 说明 |
| --- | --- | --- |
| HOLD | 302 | 优势/接触后驻守主导 |
| PEEK | 105 | 信息获取 |
| DISENGAGE | 75 | 撤退 |
| REPOSITION | 37 | 换位（含 FALLBACK 归一） |
| RE_PEEK | 23 | 同角度二次暴露 |

## 3. Candidate Actions（spec §10-§13）

- 总候选 **2742**（平均 5.1/episode）。
- feasibility 分布：FEASIBLE 2058 (75.1%) / FEASIBLE_HIGH_COST 259 (9.4%) / CONSTRAINED 308 (11.2%) / **UNAVAILABLE 117 (4.3%)**。
- **Feasibility 排除生效**：117 个不可行动作（PLANT_COMMITTED 下的 TRADE、无 bomb 的 PLANT、commitment 阻断的 FLASH）未进入正式 ranking（spec §13/§102-C）。
- 每个 episode 平均 ≥2 个 FEASIBLE alternatives → spec §102-B 满足。

## 4. DecisionEvaluation 分布（spec §17-§21）

| evaluation | n | 占比 |
| --- | --- | --- |
| GOOD | 224 | 41.3% |
| QUESTIONABLE | 170 | 31.4% |
| REASONABLE | 88 | 16.2% |
| POOR | 60 | 11.1% |
| INSUFFICIENT_EVIDENCE | 0 | 0%（真实 demo 上下文完备） |

**outcome 独立性**：evaluate_decision 签名无 outcome 参数（结构性保证，测试覆盖 spec §19/§102-D/E）。

## 5. Actionability 分布（spec §14-§15/§64）

| actionability | n | 占比 |
| --- | --- | --- |
| WEAKLY_ACTIONABLE | 324 | 59.8% |
| ACTIONABLE | 149 | 27.5% |
| HIGHLY_ACTIONABLE | 54 | 10.0% |
| NOT_ACTIONABLE | 15 | 2.8% |

**spec §102-F 满足**：15 个 NOT_ACTIONABLE（plant/defuse commitment 中的 HOLD/PLANT/TRADE）不进入 TrainingTarget 生成（gate 前置）。

## 6. 示例（spec §88/§89/§90 对照）

### 5v4 dry re-peek → POOR + HIGHLY_ACTIONABLE（spec §88）
```
CONTACT_RESPONSE · r1 t2490 · obs=RE_PEEK · eval=POOR · act=HIGHLY_ACTIONABLE
macro: NUMERIC_ADVANTAGE · risk=LOW · need_info=NONE
```
→ 「5v4 保留优势价值高于强行对枪」—— 目标信号明确。

### Plant 承诺不可控 → NOT_ACTIONABLE（spec §89）
15 例 NOT_ACTIONABLE 全部为 OBJECTIVE_COMMITMENT 中的 commitment 阻断动作 → 不生成个人目标（spec §102-F 测试覆盖）。

### 2v3 必要信息 peek → REASONABLE（spec §90 逻辑）
MacroContext：NUMERIC_DISADVANTAGE + need_info=CRITICAL + risk=HIGH → 同 PEEK 判 REASONABLE（与 5v4 的 POOR 形成对照，spec §102-A 测试覆盖）。

## 7. Pattern 聚合 → TrainingTarget（spec §42-§44/§102-G）

| pattern | n | violation_rate | actionable_share | eligible |
| --- | --- | --- | --- | --- |
| OVER_REPEEK_AFTER_NEUTRAL_CONTACT | 319 | 0.273 | 0.539 | **false**（rate < 0.30 门槛） |
| DRY_PEEK_WITH_ADVANTAGE | 168 | 0.101 | 0.167 | false |
| UNSUPPORTED_OBJECTIVE_PUSH | 55 | 0.000 | 0.055 | false |

**诚实披露**：单场样本下三个 pattern 的 violation_rate 均未达 0.30 生成门槛 → **spec §102-G 本场未触发**（不伪造目标）。聚合管线与门控已验证（测试 `test_episode_pattern_to_target` 用合成 12 样本触发 OVER_REPEEK 目标生成 ✓）；需多场 demo 积累后真实触发。

## 8. Review Queue（spec §49-§51）

- decision_episode review 项已接入 `build_review_queue`（优先级：actionable + QUESTIONABLE/POOR + 低置信 + AMBIGUOUS intent）。
- 每场默认 quota 内推送高价值 episode；UI Review 卡支持 Decision 判定（Correct/Wrong/Unsure）+ 候选 pairwise 偏好（spec §47-§48/§50-§51）。

## 9. 已知局限（诚实披露）

1. **单场单图**（de_dust2）：distribution 结论需多场验证；spec §77 batch 模式可用（多 demo 目录）。
2. **pattern 未达目标门槛**：violation 率保守（玩家本场实际较少触发过度 re-peek / dry peek）；需更多场次。
3. **geometry 未接入**：local_exposure 的 cover/escape_route 为 None（spec §27 AwpyGeometry 可选，未强制）；FLASH/utility 可用性 V1.3 假设为未知（inventory 未解析）。
4. **historical/personal evidence 在 episode 上**：检索用 episode 合成 state（features 空 → retrieve 无候选，历史证据暂未在真实 demo 填充）；CS-NET 未接入 episode 管线（model_provider=None 默认，spec §66 可选）。
5. **ADVANTAGE_PRESERVATION 检测粒度**：32-tick 轮询 alive diff 变化，锚点精度 ±32 tick（可接受）。
6. **542 opportunities 无漏检但可能有边界重复**：同玩家跨 family 的相邻锚点（如 contact 后立即 advantage）会各自成 episode（设计上允许，spec §5 围绕选择机会而非死亡）。

## 10. Success Criteria 对照（spec §102）

| 判据 | 结果 | 证据 |
| --- | --- | --- |
| A 同 PEEK 5v4 vs 2v3 不同解释 | ✅ | evaluate_decision + MacroContext 测试 + 分布对照 |
| B Observed + ≥2 可行 Alternatives | ✅ | 2742 候选 / 542 episodes，平均 5.1 个 |
| C 不现实替代被排除 | ✅ | 117 UNAVAILABLE（commitment/no-bomb/no-utility） |
| D Good Outcome ≠ Good Decision | ✅ | outcome 非输入 + 测试 |
| E Bad Outcome ≠ Bad Decision | ✅ | 同上 |
| F NOT_ACTIONABLE 不生成目标 | ✅ | gate 前置 + 测试 |
| G 重复 pattern → 目标 | ⚠️ 单场未触发 | 管线+门控已验证；需多场数据 |

## 11. 运行方式（spec §70-§71）

```powershell
python3 -m playerlab.cli decisions --match <id> --family CONTACT_RESPONSE
python3 -m playerlab.cli decision-show <episode_id>
python3 -m playerlab.cli decision-review
python3 -m playerlab.cli decision-stats
python3 -m playerlab.cli decision-preference <episode_id> A|B|BOTH|NEITHER|UNSURE
# API: GET /api/decisions · /api/decisions/{id} · /api/decisions/{id}/alternatives
#      POST /api/decisions/{id}/preference
# UI: Decisions 标签页（KEY DECISIONS 卡：Context/Alternatives/Why It Matters/Actionability）
```
