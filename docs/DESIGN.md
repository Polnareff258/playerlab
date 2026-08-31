# DESIGN.md — 阶段 5：PlayerLab V1 架构设计

> 依据：EXISTING_PROJECTS.md（复用地图）、TECHNICAL_SPIKE.md（实测数据）、COUNTERFACTUAL_DESIGN.md（反事实设计）、BACKTEST_DESIGN.md（验证设计）、spec §16-20（canonical 架构 / token 策略）。
> 本文件定义模块边界、仓库结构、存储、schema、解析集成、DP 管线、相似度索引、UI、测试、LLM 边界与 token 预算。**到这里停止，等待人工确认后再进入实现。**

---

## 1. 技术选型（含理由）

| 层 | 选型 | 理由 |
| --- | --- | --- |
| 解析 | **demoparser2 0.42.0（锁版本）+ FieldMap 适配层** | spike 实测全字段可用、性能 <60s/场、MIT |
| 数据契约 | **cs2-demo-format v3 ZIP 约定（cs2df 校验）** | 生态标准、含 duels/clutches、MIT；不自造 schema |
| 核心语言 | **Python 3.11+（polars/numpy/SQLite）** | 解析绑定 + 统计生态成熟 |
| 几何/LOS | **awpy visibility 原语（VPhys→tri BVH）** | 生态已验证、MIT |
| 区域语义 | `m_szLastPlaceName` + `@cs2dak/maps` zones/callouts | 实测可用 + 生态包 |
| 存储 | **SQLite（结构化）+ 磁盘 canonical ZIP 缓存** | 本地优先、单文件、可备份 |
| API/UI | **FastAPI（只读查询）+ React/TS 本地 Web 应用** | 与解析层解耦、UI 可独立演进 |
| LLM | **可选 provider，仅 NL 意图解析 + 最终解释** | token 预算硬约束（§8） |

---

## 2. 模块边界与仓库结构

```
playerlab/
├── README.md / docs/            # 全部决策文档 + ROADMAP
├── core/                        # Python 包 playerlab
│   ├── ingest/                  # .dem → canonical
│   │   ├── adapter.py           #   CS2DataAdapter 接口（§16：与 parser 解耦）
│   │   ├── fieldmap.py          #   canonical 字段 ↔ parser 版本字段（锁版映射）
│   │   ├── demoparser_adapter.py#   demoparser2 实现（events + ticks）
│   │   └── canonical.py         #   cs2-demo-format v3 emit/validate
│   ├── state/                   # GameState / PlayerKnownState
│   │   ├── public_info.py       #   公开信息（round_time/score/alive/bomb…）
│   │   ├── known_state.py       #   PlayerKnownState 证据模型（视野/声音/伤害/道具/bomb/经济）
│   │   ├── vision.py            #   FOV 锥 + LOS（awpy 原语封装）
│   │   └── ground_truth.py      #   GroundTruthState（outcome/replay/debug 用）
│   ├── decision/                # DecisionPoint 管线（确定性规则）
│   │   ├── engagement.py        #   交战状态机（IDLE/CONTACT/ENGAGED/DISENGAGED…）
│   │   ├── actions.py           #   动作族谓词（PEEK/HOLD/RE_PEEK/DISENGAGE/FALLBACK）
│   │   ├── detector.py          #   候选→去重→显著性 Top-N
│   │   └── taxonomy.py          #   动作分类法与 NO_COMPARABLE_ALTERNATIVE
│   ├── combat/                  # duel 归属 + outcome
│   │   ├── duel.py              #   damage/kill → duel 实例（对齐 duels.json）
│   │   └── outcome.py           #   survival@W / duel_outcome / round_win + 扩展指标
│   ├── features/                # 相似度
│   │   ├── vector.py            #   StateFeatureVector（PlayerKnownState 派生，白名单）
│   │   ├── filters.py           #   Hard Filters（map/side/zone/action family）
│   │   ├── similarity.py        #   加权软相似度
│   │   └── weights.py           #   权重配置加载（JSON，可 ablation）
│   ├── counterfactual/          # 反事实引擎
│   │   ├── retrieve.py          #   top-k 检索
│   │   ├── aggregate.py         #   按动作族分组 + outcome 统计（Wilson CI）
│   │   ├── evidence.py          #   证据强度（n/分布/confounders/missing）
│   │   └── verdicts.py          #   INSUFFICIENT_EVIDENCE / NO_COMPARABLE_ALTERNATIVE …
│   ├── stats/                   # Wilson CI / 校准 / Brier / bootstrap
│   ├── db/                      # SQLite schema + repositories
│   ├── api/                     # 本地只读 JSON API（stdlib http.server）
│   ├── backtest/                # holdout / QA 导出 / ablation 跑批
│   └── batch.py                 # 批量 demo 分析（发现/幂等跳过/失败隔离/报告）
├── ui/                          # React + TS（本地 Web）
│   └── src/views/               # MatchView / DecisionReview / WhatIf / EvidencePanel
├── schema/                      # canonical JSON schema（cs2-demo-format 对齐 + plab 扩展）
├── config/                      # feature weights / thresholds / validation.yml
├── spike/                       # 探针脚本 + fixtures（probe_out.json 等）
└── tests/                       # 单元 / 黄金夹具 / 审计 / 复现哈希
```

**模块依赖方向（单向）**：`ingest → state → decision/combat → features → counterfactual → api/ui`；`stats`、`db` 为公共底层。反事实引擎不得反向依赖 UI 或 LLM。

---

## 3. 存储设计

### SQLite（主库，`~/.playerlab/db.sqlite`）
| 表 | 内容 | 说明 |
| --- | --- | --- |
| matches | demo 元数据（路径/哈希/map/side/日期/解析版本） | demo_id 唯一 |
| rounds | round 边界、winner、reason、比分 | 链 match |
| players | steamid/name/team | 链 match |
| decision_points | DP 主记录（start/decision/end tick、action、location_zone、confidence、evidence JSON） | 链 match+round |
| decision_states | DecisionPoint 的结构化 GameState + PlayerKnownState（JSON）| 反事实检索的数据源 |
| outcomes | DP 关联 outcome（survival@W/duel/round_win + 扩展） | 窗口固定 |
| similar_index | 派生相似度索引（可重建，不手工维护） | 见 §6 |
| backtest_results / qa_batches | 验证产物 | 可追溯 |

### 磁盘缓存
`analyses/<demo_id>/`：canonical ZIP（cs2-demo-format v3）+ 派生中间产物。**解析一次，之后只读缓存**；重解析由 demo 哈希 + 解析版本触发。

---

## 4. Canonical Schema（cs2-demo-format 对齐 + plab 扩展）

复用（契约已有）：`Match / Round / PlayerState / ShotEvent / DamageEvent / KillEvent / GrenadeEvent / Duel / Clutch`。
PlayerLab 扩展（`plab:` 命名空间，Zod schema 对齐风格）：
```
DecisionPoint {
  id, demo_id, round, start_tick, decision_tick, end_tick,
  observed_action, alternative_action_candidates[],
  relevant_players[], location_zone, location_nav?, confidence,
  evidence: { ticks[], events[], sources[] }   // 每条可追溯
}
GameState {           // GroundTruthState + PlayerKnownState 双态
  ground_truth: {...},   // outcome/replay/debug 用
  player_known: {...},   // decision 层唯一可用
}
CounterfactualResult {
  observed_action, alternatives: [{ action, n, survival, round_win, duel, ci, samples[] }],
  evidence_strength: { n, high_sim_n, sim_dist, action_ns, outcome_dist, confidence, confounders[], missing[] },
  verdict: OK | INSUFFICIENT_EVIDENCE | NO_COMPARABLE_ALTERNATIVE | NO_RELIABLE_DIFFERENCE | ...
}
```

---

## 5. DecisionPoint 管线（确定性，无 LLM）

```
逐 tick 事件/状态流（FieldMap）
 → engagement 状态机（per player）
 → 动作族谓词求值（config 参数化：速度/角度/窗口/阈值）
 → 候选 DP（满足 ≥2 动作族前置条件）
 → 聚类去重（同一交战 episode 取交火前最后一个分叉点）
 → 显著性打分（接触强度/bomb/人数/round 关键度/结果）取 Top-N（30–80/场）
 → 对每个 DP：构建 GroundTruthState + PlayerKnownState + outcome 窗口
 → 入 decision_states
```
关键约束（COUNTERFACTUAL_DESIGN §1-3）：
- Decision 层只吃 PlayerKnownState 派生特征（白名单），审计断言强制。
- 每个动作族 = 前置条件 ∧ 执行窗口证据；证据不足 → 低置信度/不产出。

---

## 6. 相似度索引

- **查询时计算（V1）**：`decision_states` 全量加载到内存（几百场 ≈ 数万行），polars/numpy 向量化 Hard Filter + 加权软相似度，top-k 毫秒级。
- 索引为**派生产物**（`similar_index` 表可随时重建），不引入外部 ANN 依赖；规模超 10^5 状态再评估 usearch/annoy（V1.5 事项）。
- 特征与权重全部来自 `config/features.json`（可配置、可回测、可 ablation —— spec §8）。

---

## 7. UI（V1 无聊天首页）

| 页面 | 内容 |
| --- | --- |
| Match View | Rounds 列表、Important Duels、Decision Points（时间轴） |
| Decision Review | 例：Round 17 · Mirage CT · 1:18 · Window · Observed: RE-PEEK · Result: Death；Observed action / Alternatives / Historical comparison |
| Execution | Crosshair（initial error/flick/overshoot/undershoot/correction）、Movement（velocity@shot/counter-strafe/peek speed/sync）、Shot timing；**Decision issue vs Execution issue 结论** |
| What If? | 每备选动作：samples / survival / round win / confidence（medium-high 等）；按钮 **Show Similar Rounds**、**Show Evidence** |

- 证据面板：DP 的每一条声明 → demo/match/round/tick 链接（§13 强追溯）。
- Replay Question Engine（§19，可选）：NL 输入 → 结构化查询 → 证据检索 → LLM 解释（解释的引用全部可点击回证据）。

---

## 8. LLM 边界与 Token 预算（spec §20 落地）

### 确定性优先（绝不进 LLM）
parsing / geometry / timing / event detection / similarity / statistics / aggregation / retrieval / clustering / verdicts。

### LLM 仅两处
1. **NL 意图解析**：Replay Question Engine 把「这波为什么死？」转结构化查询（字段枚举 + 过滤器）；失败即回退空查询。
2. **最终解释**：输入 = 结构化上下文（DecisionPoint 摘要 + GameState 摘要 + top 相似状态 + outcome 统计 + mechanics findings），**禁止整场 demo JSON / 原始 tick 流**。

### 硬预算（每次调用 config 化）
```
max_similar_states = 50
max_evidence_items  = 20
max_events          = 200
max_tokens          = 2000（解释）/ 500（意图解析）
max_llm_calls_per_query = 2   # 无 agent loop
```
- 证据不足 → 直接返回 INSUFFICIENT_EVIDENCE 等固定 verdict，**不调 LLM 补全**（spec §12 纪律，审计断言覆盖）。
- LLM 输出结构化为 JSON（含引用 id），UI 只渲染「有证据引用」的句子。

---

## 9. 测试与验证（与 BACKTEST_DESIGN 联动）

| 层 | 内容 |
| --- | --- |
| 单元 | 动作族谓词、PlayerKnownState 构建、Wilson CI、verdict 判定 |
| 黄金夹具 | spike demo 切 2–3 round 的结构化快照（离线秒级） |
| 审计断言 | hindsight 守卫（Decision 层禁 GroundTruth 特征）、INSUFFICIENT_EVIDENCE 纪律 |
| 复现哈希 | 同 demo 同 config → 相同输出（管线确定性） |
| 回测 CI | holdout 校准 / Brier / Retrieval QA / ablation（BACKTEST_DESIGN §6） |
| 发布门槛 | 见 BACKTEST_DESIGN §7；不达标 → unvalidated 降级 |

---

## 10. 风险与缓解

| 风险 | 缓解 |
| --- | --- |
| 样本不足导致反事实空转 | 覆盖报告 + INSUFFICIENT_EVIDENCE 制度（COUNTERFACTUAL_DESIGN §7-8） |
| PlayerKnownState 过保守/过激进 | 保守默认 + 证据置信度 + 参数化（半径/遗忘时长） |
| 字段命名版本漂移 | FieldMap + 锁 demoparser2 版本 + 解析版本字段入库 |
| LOS 计算成本 | awpy BVH 原语 + 按需计算（只对接触/决策窗口） |
| 反事实被误读为因果 | 描述性口径 + UI 措辞（"历史上类似局面…"）+ Pro Reference 行为≠optimal（V2） |
| LLM 幻觉补全 | 结构化输入 + 硬预算 + verdict 纪律 + 引用门控渲染 |

---

## 11. 成功判据（spec §28 → 可验收）

> 给定一个 CS2 关键 DecisionPoint，PlayerLab 能：重建玩家可知状态 → 检索真正相似的局面 → 对比不同动作的实际历史结果 → 展示证据强度 → 区分决策 vs 执行问题。
所有重要结论满足：traceable / evidence-backed / uncertainty-aware / reproducible / token-efficient；证据不足 → INSUFFICIENT_EVIDENCE。

验收测试（V1 收口）：用 spike demo 走通「Round N DP → What If → Show Similar Rounds → Show Evidence」全链路，并产出符合 BACKTEST_DESIGN §7 门槛的验证报告。

---

## 12. 实现偏差记录（MVP 落地时与设计的差异，均为有意的简化）

| 设计 | 实现 | 理由 | 升级路径 |
| --- | --- | --- | --- |
| FastAPI API | stdlib `http.server`（只读 JSON API） | 零额外依赖，本地单机足够 | 换 FastAPI 包装同一 handler |
| React/TS UI | 单文件静态 `ui/index.html`（vanilla JS，hash 路由） | 无构建步骤、开箱即用 | 按页面组件化迁移 |
| polars | pandas（demoparser2 依赖链已带） | 避免额外安装；规模足够 | 数据量大时切 polars |
| 相似度 action hard filter（§9 字面） | counterfactual 检索**不**按 action 过滤，检索后按 action 分组；same_action 模式才过滤 | 反事实必须比较不同动作（spec §7 流程：Group by Action 在检索之后） | — |
| 几何 LOS（awpy .tri） | V1 视野 = FOV 锥 + 距离 + **数据校准 yaw 偏移**（用 kill 事件拟合），无遮挡测试 | 零地图资产依赖、确定性；文档明示近似 | awpy VisibilityChecker 原语 |
| 侧别判定 | bomb_planted 的携带者团队 = 该局 T，无雷局继承最近有雷局；无雷整场 = unknown | demo 无直接 side 字段的可靠来源 | **已升级**：`CCSPlayerController.m_iTeamNum` 逐 tick 阵营（半场精确）为准，炸弹推断仅兜底 |
| 武器逐 tick | `Weapon.m_iItemDefinitionIndex`（实测可用）+ 事件武器名兜底 | 实测验证 | 接 Weapon 实体全量字段 |
| 位置字段 | ~~`CCSPlayerPawn.origin`（陈旧出生点，已废弃）~~ → `CBodyComponentBaseAnimGraph.m_vecX/Y/Z` | 实现期实测发现 | — |
| 速度字段 | ~~`m_vecBaseVelocity`（恒 0）~~ → 位置差分推导（Δpos×64，传送钳制） | SourceTV 不更新速度字段 | — |

> 给定一个 CS2 关键 DecisionPoint，PlayerLab 能：重建玩家可知状态 → 检索真正相似的局面 → 对比不同动作的实际历史结果 → 展示证据强度 → 区分决策 vs 执行问题。
所有重要结论满足：traceable / evidence-backed / uncertainty-aware / reproducible / token-efficient；证据不足 → INSUFFICIENT_EVIDENCE。

验收测试（V1 收口）：用 spike demo 走通「Round N DP → What If → Show Similar Rounds → Show Evidence」全链路，并产出符合 BACKTEST_DESIGN §7 门槛的验证报告。
