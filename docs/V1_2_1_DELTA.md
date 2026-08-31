# V1_2_1_DELTA.md — Phase A：V1.2 → V1.2.1 增量审计

> 审计对象：`context.py / intent.py / feasibility.py / responsibility.py /
> context_pipeline.py / reference.py / annotation.py / rootcause.py`
> （HEAD `ca9a723`，V1.2 提交）+ 真实 Demo 实测（de_dust2，18 局）。
> 目的：确认 V1.2.1 复用面与缺口（spec §63 Phase A）。

---

## 1. 现状基线（可复用面）

| 模块 | 现状 | V1.2.1 复用 |
| --- | --- | --- |
| state.py | PlayerKnownState（own/team vision 近似 FOV、damage 记忆、footstep/shot/grenade 听觉、`last_seen_enemies`、`n_known_enemies`、`nearest_known_enemy`、teammate 可见计数） | ★★★ 直接作为 KnownState 序列底座（§2 字段大部分已在其 `build()` 内部可推导） |
| context.py | TemporalContext（4s 窗口、轨迹归一化、zone 序列、heading 一致性、事件计数、bomb/objective、`trade_support` 距离近似） | ★★ `feature_sequence()` 保留；信息特征全部新增 |
| intent.py | Commitment 11 态 / SituationalRole 16 态 / Intent 14 态规则基线 + AMBIGUOUS | ★★ ROTATE vs REPOSITION 骨架保留，规则需引入 information features（§6） |
| feasibility.py | ActionFeasibility 6 态规则引擎 | ★★★ 原样保留；Tradeability 在其上叠加（§7-§8） |
| responsibility.py | 8 类归因 + commitment≠免责 | ★ 重写判断主干：保守 gate（§11-§14） |
| context_pipeline.py | 死亡/DP 锚点 + 每玩家每回合 3 采样 IntentSample | ★★★ `player_known_state={}` → 接入 KnownState + 信息序列（§2/§5） |
| reference.py | ReferenceCorpusProvider / DecisionSampleProvider / ReferencePolicyProvider + Null + LocalStub | ★★ 保留不动（§49） |
| annotation.py | 4+5 类标注 + ReviewQueue（优先级+预算）+ JSONL | ★★ 加分类 quota + review_focus + 新优先级（§16-§18） |
| rootcause.py | Result→Context→Commitment/Role→Execution→Micro→Macro→Responsibility 7 层 | ★ 只消费 responsibility_map，无需改动 |
| db.py | schema v3（context_events / intent_samples 已含 player_known_state 列） | ★★ schema v4：intent_samples 加 `known_state_sequence / information_sequence / round_id / episode_id`（§5/§19） |

## 2. V1.2 已知问题确认（实测数据）

### 问题 1：ResponsibilityAttribution 过度偏向 SELF_DECISION —— 实锤

真实 Demo（18 局，199 context_events）responsibility 分布：

```
SELF_DECISION         153 (76.9%)
INSUFFICIENT_EVIDENCE  36 (18.1%)
NOT_ACTIONABLE         10 ( 5.0%)
```

根因（代码确认，`responsibility.py`）：

- `ENGAGEMENT_COMMITTED` 分支：`mate_dist > 1600 → SELF_DECISION` —— **纯距离**判定"孤立"，无 LOS/nav/cover/响应时间（spec §12 明令禁止）。
- `FREE` 分支：`team_alive >= 1 and mate_dist > 1600 → SELF_DECISION` —— 同样纯距离。
- 无 evidence-sufficiency 门：只要命中一条规则就直接归责，`confidence` 只是事后装饰。

### 问题 2：trade/support/isolation 依赖欧氏距离

- `context.py:106` `trade_support = HIGH if dist<=1600 / MED if <=3200 / LOW`。
- `intent.py:84` TRADE_SUPPORT role 判定同用 `nearest_teammate_dist <= 1600`。
- 无 `nav_distance / direct_los / estimated_response_time / intervening_cover` 字段（spec §7 全缺）。

### 问题 3：缺少 LOS / nav / cover / response-time

V1.2 已诚实声明 LIMITATION（V1_2_DELTA.md §3）：awpy .tri BVH 成本高，未引入。
V1.2.1 Phase C 要求先做研究（spec §9/§10）再决定复用 or UNKNOWN。

### 问题 4：IntentSample 未接入 PlayerKnownState —— 实锤

`context_pipeline.py:89` 写库时 `player_known_state: {}` 硬编码空 dict；
`build_temporal_context(..., known_state=None)` 全程传 None。
→ 信息特征零接入（spec §2/§5）。

### 问题 5：Intent 学到"怎么移动"而非"为什么移动"

`classify_intent` 输入只有：`time_moving_ticks / zone_crossings / moved_dist /
heading_consistency / n_known_enemies / info_update_recency / bomb 状态`。
信息侧信号仅有 `opp_side_signal`（bomb 对侧 或 ≥2 known enemies）——不足以区分
§6 Case A（B 无信息 → REPOSITION/GATHER_INFO）与 Case B（B 2 敌确认 + bomb B → ROTATE）。

### 问题 6：Tiny Model 不适合正式训练

- 540 条样本全为 rule-baseline 无人工标签；单场单图（spec §20：需多场多图 500-1000 条）。
- 无 split metadata：`intent_samples` 表无 `round_id / episode_id`（spec §19 泄漏预防）。
- 判定保持：人工标签 < 门槛 → `INSUFFICIENT_DATA_FOR_MODEL_SPIKE`（spec §21）。

### 问题 7：Review 挤占

真实 Demo review queue 14 条：intent 10 / repeek 2 / advantage 1 / root_cause 1。
`build_review_queue` 无分类 quota，intent 项无条件填满预算（spec §16）。

## 3. V1.2.1 设计落点（对应 spec 章节）

| V1.2.1 能力 | 模块 | 对应 spec |
| --- | --- | --- |
| KnownState 序列（14 字段） | `state.py` KnownStateBuilder 扩展 + 序列化 | §2 |
| InformationStrength（5 级 + confidence，无 LLM） | `information.py`（新） | §3 |
| InformationDirection（A/B/Mid/Unknown） | `information.py` | §4 |
| IntentSample v2（known_state_sequence / information_sequence / round_id / episode_id） | `context_pipeline.py` + `db.py` v4 | §5/§19 |
| Intent 信息感知（ROTATE vs REPOSITION 按信息区分） | `intent.py` | §6 |
| Tradeability（8 字段 + 5 级分类，内部保留 score） | `tradeability.py`（新） | §7-§8 |
| LOS/Nav Spike 研究 + 集成决策 | `docs/LOS_NAV_SPIKE.md` | §9-§10 |
| Responsibility 保守 gate（证据充分 AND 可行 AND 备选 AND 因果） | `responsibility.py` 重写 | §11-§14 |
| Review Quota（3/2/2/1=8）+ review_focus + 新优先级 | `annotation.py` | §16-§18 |
| GameModelProvider / Null / ModelEvidence / CSNetProvider | `model_provider.py`（新）+ `csnet.py`（新） | §22-§38 |
| 依赖隔离（requirements-csnet.txt）+ 失败隔离 | pyproject/pip extras + provider 层 | §61-§62 |
| 最小 UI（Model Intelligence 状态 + Decision Review Model Evidence） | `ui/index.html` | §42-§43 |

## 4. 明确不做（spec §1）

- 不新增宏观 Pattern（保留 3 个 alpha 检测器）。
- 不实现 Pro Demo crawler / Pro Reference Corpus / 完整 Skill Model / Aim Trainer。
- 不训练大规模 Tiny Transformer；人工标签不足 → INSUFFICIENT_DATA_FOR_MODEL_SPIKE。
- 不复制 CS-NET Dashboard / 不把 CS-NET 核心代码复制进 PlayerLab。
- 不把 CS-NET prediction 写进 PlayerKnownState（Hindsight Boundary，spec §34）。

## 5. 验收判定（spec §74 对照本审计）

| 判据 | 现状 | V1.2.1 计划 |
| --- | --- | --- |
| A 同轨迹不同信息 → ROTATE vs REPOSITION | ROTATE 需 bomb 对侧或 ≥2 敌，信息粒度粗 | 引入 InformationStrength/Direction 后合成测试区分 Case A/B |
| B 远队友但可补枪 → 不判 isolated | 距离>1600 直接孤立 | Tradeability 用 LOS/nav/response-time（无则 UNKNOWN，不伪造） |
| C 合理下包无法补枪 → 不归责 planter | 已有 NOT_ACTIONABLE | 保守 gate 强化 + 测试 |
| D 危险 reload → SELF_DECISION | 已有 | 保持 + 加"reload 决策本身是否合理"复核 |
| E CS-NET 至少一个真实 head 返回 ModelEvidence | 无 | Phase G/H |
| F 无 CS-NET 时全功能运行 | 无 provider 层 | NullGameModelProvider 兜底 + 测试 |
