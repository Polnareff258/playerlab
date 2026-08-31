# V1_3_DELTA.md — Phase A：V1.2.1 → V1.3 增量审计

> 审计对象：`decision.py / patterns.py / context.py / intent.py / feasibility.py /
> tradeability.py / responsibility.py / counterfactual.py / training.py /
> annotation.py / model_provider.py / csnet.py / reference.py`（HEAD `c8d320e`）。
> 目的：确认 V1.3「DecisionEpisode & Local Alternatives」的复用面与新增点（spec §91）。

---

## 1. 现状基线（可复用面）

| 模块 | 现状（V1.2.1） | V1.3 复用 |
| --- | --- | --- |
| decision.py | DecisionPoint 检测（PEEK/HOLD/RE_PEEK/DISENGAGE/FALLBACK），damage 接触聚类成 episode，`build_state`（known+GT+features）/ `build_outcome`（survival@W/duel/round_win） | ★★★ ObservedAction 分类直接复用（spec §60）；`build_state/build_outcome` 是 DecisionEpisode 的 state/outcome 底座 |
| patterns.py | 3 检测器（repeek/move_shoot/advantage）+ 聚合 + 反事实支持 | ★★ Pattern 将重构为「DecisionEpisode 聚合」（spec §42-§44），现有检测器作为 episode 证据来源 |
| context.py | TemporalContext（4s 窗口，KnownState 已接入，information strength/direction） | ★★★ 直接作为 episode 的 temporal/local context |
| intent.py | Commitment 11 态 / Role 16 态 / Intent 14 态 + 信息感知 | ★★★ Commitment/SituationalRole 直接进入 DecisionEpisode schema（spec §4） |
| feasibility.py | ActionFeasibility 6 态规则引擎（15 candidates） | ★★★ CandidateAction.feasibility 直接复用（spec §13），补 FLASH/PLANT 等缺失动作 |
| tradeability.py | Tradeability + `TradeabilityGeometry` 接口（null 实现） | ★★★ LocalContext.tradeability（spec §25）；`AwpyGeometry` 作为可选实现（spec §27） |
| responsibility.py | 保守四门 gate + tradeability | ★ Responsibility 降级为辅助过滤/evidence（spec §16），不再作为产品主轴 |
| counterfactual.py | retrieve + what_if（Wilson CI 分组统计，similar-state 检索） | ★★★ 升级为 Alternative Evidence Engine（spec §35-§36）——输出「HOLD 历史表现更稳定」而非「一定会赢」 |
| training.py | TrainingTarget（3 pattern 驱动）+ validate + Active Focus | ★★ 扩展来源：DecisionEpisode clustering / repeated local error（spec §40-§41） |
| annotation.py | 标注 + Preference + ReviewQueue（quota 8） | ★★★ 新增 decision_quality / candidate_action_preference / actionability 类型（spec §46-§48） |
| model_provider.py / csnet.py | GameModelProvider / Null / CSNetProvider（win_rate 真实推理） | ★★★ CS-NET 作为 State Value Evidence（spec §33-§34），delta 不覆盖决策判定 |
| reference.py | ReferencePolicyProvider + Null/LocalStub | ★ 保持；未来 Pro Reference Distribution（spec §82-§83） |
| db.py | schema v4（context_events/intent_samples + v4 列） | ★★ 新增 v5：decision_episodes / decision_candidates / decision_evidence / decision_preferences / decision_episode_links（spec §68） |

## 2. V1.3 新增（spec §2-§90 落点）

| 新能力 | 模块 | 对应 spec |
| --- | --- | --- |
| DecisionOpportunity（7 类） | `episode.py`（新） | §6-§7 |
| DecisionEpisode（核心对象） | `episode.py` | §4-§5 |
| CandidateAction Space（9 个 MVP） | `episode.py` + `feasibility.py` 扩展 | §8-§12 |
| MacroContext（含 RiskTolerance / NeedForInformation） | `macro.py`（新） | §22-§24 |
| LocalContext（含 LocalExposure） | `episode.py` | §25-§28 |
| Actionability（5 级） | `episode.py` | §14-§15 |
| DecisionEvaluation（5 级） | `evaluate.py`（新） | §17-§21 |
| DecisionEvidence（6+ channels） | `evidence.py`（新） | §29-§32 |
| PersonalActionHistory | `evidence.py` | §38-§39 |
| Counterfactual → Alternative Evidence Engine | `counterfactual.py` 增强 | §35-§37 |
| Pattern = Episode 聚合 → TrainingTarget | `training.py` 扩展 | §40-§44、§53-§55 |
| Review：DecisionEpisode cards + pairwise preference | `annotation.py` + UI | §46-§52 |
| 数据表 v5 | `db.py` | §68-§69 |
| CLI / API / UI | `cli.py` / `api.py` / `index.html` | §70-§76 |

## 3. 关键设计决策（审计结论）

1. **ObservedAction 复用 decision.py**：DecisionEpisode 的 observed action 由现有 DP 分类器提供（spec §60），不重复写 classifier；但 candidate space 扩展为 9 个 MVP（PEEK/HOLD/HIDE/RE_PEEK/DISENGAGE/REPOSITION/FLASH/PLANT/TRADE），DP 分类器需把 FALLBACK→REPOSITION 语义对齐。
2. **Feasibility 先行**（spec §13）：CandidateAction 生成时立即应用 `action_feasibility`（复用现有 6 态），UNAVAILABLE 的动作不进 alternative ranking——plant/defuse/reload commitment 下 TRADE 自动 UNAVAILABLE；无 flash 时 FLASH UNAVAILABLE；bomb 不在身 PLANT UNAVAILABLE。
3. **Actionability 取代 Responsibility 主轴**（spec §14-§16）：DecisionEpisode 输出 Actionability（5 级）而非责任分类；ResponsibilityAttribution 保留为 evidence 字段，UI 默认不显示。
4. **Evaluation 输入组合**（spec §18）：MacroContext + PlayerKnownState + LocalContext + Commitment + Role + Candidates + Feasibility + Observed + Historical + ModelEvidence；outcome 永不入参（spec §19 结构性保证）。
5. **Evidence Independence**（spec §31）：historical outcome 与 counterfactual retrieval 同源时标记 related source（decision_evidence.related_sources），避免重复计权。
6. **CS-NET scope**（spec §33-§34）：state_value evidence，GROUND_TRUTH_STATE，不入 PlayerKnownState；delta<0 不自动 POOR（测试覆盖）。
7. **Pattern 方向反转**（spec §42-§44）：DecisionEpisode → Repeated Decision Pattern → Bottleneck → TrainingTarget；第一版 deterministic grouping（family × advantage_state × context bucket）。

## 4. 明确不做（spec §3/§45/§58/§83/§101）

- 不做 GameSenseScore / MacroScore / DecisionIQ 总分（spec §3）。
- 不训练 Tiny Transformer / Responsibility Model / Action Policy Model（spec §45）。
- 不做完整 execute/retake/map-control/economy planning（spec §58）。
- 不实现 Pro Corpus（spec §83）。
- 不复制 CS-NET dashboard（spec §101）。

## 5. 验收判定（spec §102 对照）

| 判据 | 计划 |
| --- | --- |
| A 同 PEEK 在 5v4 vs 2v3 不同解释 | MacroContext（advantage_state/need_for_information/risk_tolerance）驱动 evaluation |
| B Observed + ≥2 真实 Alternatives | CandidateAction 生成（feasibility 过滤后） |
| C 不现实替代被排除 | PLANT_COMMITTED→TRADE UNAVAILABLE；无 flash→FLASH UNAVAILABLE 等测试 |
| D Good Outcome ≠ Good Decision | outcome 不入 evaluation 入参（§19） |
| E Bad Outcome ≠ Bad Decision | 同上 |
| F 不可控事件 NOT_ACTIONABLE 不生成目标 | Actionability gate 前置于 TrainingTarget 生成 |
| G 至少一个重复 pattern → TrainingTarget | Episode clustering → bottleneck → target（真实 demo 验证） |
