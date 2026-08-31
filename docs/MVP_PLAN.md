# MVP_PLAN.md — 阶段 5：PlayerLab V1 实现计划

> 范围 = spec 第 3–20 节 V1 能力；阶段划分按 DESIGN.md 架构。**本文件为待批准计划，批准后才进入实现。**
> 里程碑验收一律以「可运行 + 可验证 + 可追溯」为判据；每步产出落盘并可回滚。

---

## M0 — 工程脚手架（~1 天）

**任务**
- 建立 `core/`（pyproject，polars/demoparser2==0.42.0/FastAPI 依赖锁定）、`ui/`（Vite+React）、`config/`、`tests/`、`schema/`
- 从 spike demo 切 2–3 个 round 的**黄金夹具快照**（结构化 JSON）
- CI 骨架（lint + 单元 + 复现哈希断言）

**验收**
- `pytest` 绿；夹具加载通过；`config/validation.yml` 生效

---

## M1 — Ingestion → Canonical（~3–4 天）

**任务**
- `CS2DataAdapter` 接口 + `demoparser_adapter`（events + ticks，spike 已验证字段）
- `FieldMap`：canonical 字段 ↔ demoparser2 0.42 字段（含按钮位掩码解码、实体句柄→武器映射）
- `canonical.py`：输出 cs2-demo-format v3 风格 ZIP + 校验（对齐 cs2df 语义）
- 解析产物缓存（demo 哈希 + 解析版本）

**验收**
- spike demo 全量解析 <90s，canonical ZIP 校验通过
- 同 demo 二次解析跳过（缓存命中）；重解析幂等
- 字段映射单元测试覆盖 §4 数据表全部行

---

## M2 — State 层：GameState / PlayerKnownState（~4–5 天）

**任务**
- `public_info`：round_time / score / alive / bomb 状态（kill feed 可见性规则）
- `known_state`：证据模型（own FOV+LOS、teammate last-seen、footstep/声音半径、伤害来源、道具 detonate、bomb、经济估值、遗忘衰减）
- `vision.py`：FOV 锥 + LOS（awpy 原语封装，按需计算）
- `ground_truth`：全状态（outcome/replay/debug）

**验收**
- 黄金夹具上：已知状态单元测试通过（含「当时玩家看不到敌人」反向用例）
- **hindsight 审计断言**：Decision 层特征白名单强制（GroundTruth 特征引入即测试失败）
- 声音/伤害/道具/bomb 各信息源在 spike demo 上可视化可检查（导出 JSON）

---

## M3 — DecisionPoint 管线 + Duel/Outcome（~5–6 天）

**任务**
- `engagement.py` 交战状态机；`actions.py` 五动作族谓词（config 参数化）
- `detector.py`：候选 → 去重 → 显著性 Top-N
- `combat/duel.py` 归属（对齐 duels.json 语义）+ `combat/outcome.py`（survival@W/duel/round_win + 扩展）

**验收**
- spike demo 产出 30–80 个 DP（可调阈值），每个 DP 含 start/decision/end tick + 双状态 + 证据
- 黄金标注抽查：≥80% 动作族标签与人工判断一致（标注集含各动作族样例）
- 同交战 episode 不重复产出 DP

---

## M4 — 特征 / 相似度 / 反事实引擎（~4–5 天）

**任务**
- `features/vector.py`（PlayerKnownState 白名单特征）+ `filters.py`（Hard）+ `similarity.py`（加权软相似度）+ `weights.py`（JSON 可配置）
- `counterfactual/`：检索、按动作族聚合、Wilson CI、证据强度块、verdict 判定
- 覆盖报告（每 map/side/zone 单元样本数）

**验收**
- 检索自相似 sanity 通过；Hard Filter 零违规
- 样本不足 → INSUFFICIENT_EVIDENCE（自动化断言）；各动作族 n 统计正确
- 输出完整 CounterfactualResult（含 confounders/missing/confidence）

---

## M5 — Backtest 验证（~3–4 天）

**任务**
- `backtest/`：LOMO + temporal holdout、校准/Brier、QA 批量导出、ablation 阶梯
- 用真实个人 demo 库（或合成库）跑批

**验收**
- BACKTEST_DESIGN §7 门槛逐项可执行（校准/Brier/QA/ablation/复现）
- 未达标能力自动标记 unvalidated（不展示）

---

## M6 — UI（~4–5 天）

**任务**
- Match View（rounds / duels / DPs 时间轴）
- Decision Review（§18 布局）+ Execution 面板（crosshair/movement/shot timing + Decision vs Execution 结论）
- What If?（samples/survival/round win/confidence + Show Similar Rounds + Show Evidence）
- 证据面板（每条声明 → demo/match/round/tick 链接）

**验收**
- 用 spike demo 走通「Round N DP → What If → Show Similar Rounds → Show Evidence」全链路（演示验收脚本）
- 无聊天首页；全部数据来自本地 API

---

## M7 — LLM 边界（Replay Question Engine，~2–3 天）

**任务**
- NL 意图解析（结构化查询，失败回退）+ 最终解释（结构化上下文 + 硬预算 + 引用门控渲染）

**验收**
- 「这波为什么死？」/「如果我不 re-peek 呢？」两类查询走通
- 预算断言：max_similar_states/evidence/events/tokens 生效；证据不足不调 LLM；无 agent loop
- 审计：整场 demo JSON 从未进入 LLM 上下文（instrumentation 断言）

---

## M8 — 收口（~2 天）

**任务**
- 复现哈希回归、License 复核（MIT 生态侧清单）、README/docs 同步、发布门槛总检

**验收**
- spec §28 成功判据逐条映射通过；BACKTEST_DESIGN §7 门槛报告归档

---

## 里程碑依赖与并行

```
M0 → M1 → M2 → M3 → M4 → M5
                  └──────→ M6（UI 可在 M3 后并行起，用 mock API）
                              └─→ M7（依赖 M4 输出）
                                  └─→ M8
```
预估总工期：**约 4–5 周（单人全职）**；M1–M4 为核心链路，M5 是「防止看起来聪明但不可靠」的强制闸门。

---

## 不在 V1（spec §21 + ROADMAP）

Valorant/Apex/Delta Force、VLM、live overlay、反作弊、自研 parser、团队战术教练、训练计划、Aim Lab/Kovaak、pro demo 爬虫、最优动作断言 —— 全部不做；见 ROADMAP.md。
