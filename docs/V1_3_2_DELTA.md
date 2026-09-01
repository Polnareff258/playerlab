# V1_3_2_DELTA.md — Phase A：V1.3.1 → V1.3.2 增量审计

> 审计对象：`db.py / api.py / episode.py / evaluate.py / evidence.py / duel.py /
> engagement.py / training.py / annotation.py / cli.py / ui/index.html`
> （HEAD `7b20b7c`，V1.3.1 + 多场修复）。
> 目的：确认 V1.3.2「Calibration, Ground Truth & Player-Centric UX」的复用面与缺口（spec PART A-P）。

---

## 1. 现状基线（可复用面）

| 模块 | 现状（V1.3.1） | V1.3.2 复用 |
| --- | --- | --- |
| db.py | schema v6：decision_episodes 带 player_id + 索引；players 表；human_annotations（无 player_id/detector_type） | ★★ v7：players 表加 is_user/remembered；新表 player_profiles / calibration_samples / review_moments（或派生视图） |
| get_decision_episodes | 已支持 match_id/player_id/family 过滤 + limit | ★★★ 直接作为 player-scoped 查询底座 |
| api.py | /api/matches/{id} 返回 players；/api/decisions 列表 + detail + alternatives + preference；/api/decision-stats | ★★ 新增 player-scoped 端点：players/{sid}/overview·decisions·engagements·patterns·review-moments；/api/focus-player 设置 |
| episode.py | DecisionEpisode 全字段（family/macro/engagement/execution/actionability/evidence_sufficiency） | ★★★ ReviewMoment 的 episode 数据源（selection/presentation 层，不新增 detector） |
| evaluate.py | 三层评价 + actionability | ★★★ 直接喂 ReviewMoment 评分 |
| evidence.py | EvidenceSufficiency（MEDIUM/LOW 诚实） | ★★ calibration metrics 的 sufficiency 输入 |
| duel.py / engagement.py | PREAIM_ERROR/MOVING_SHOT/FIRE_BEFORE_AIM_READY/IRREGULAR + DRY_PEEK/JIGGLE/TEAM_FLASH_PEEK | ★★★ 校准对象（detector_type） |
| training.py | TrainingTarget（bottleneck + episode pattern 双源） | ★★ 加 calibration gate：UNCALIBRATED detector 不得自动成 HIGH-confidence target（PART E §29） |
| annotation.py | ReviewQueue + annotation 类型（含 engagement_method/execution_issue） | ★★ CalibrationSample 的 review 状态复用；reason code 扩展（PREAIM 分类） |
| cli.py | decisions/decision-show/decision-stats/decision-preference | ★★ 加 focus-player / calibrate / calibration-stats |
| ui/index.html | Decisions 标签（WHY FIGHT/HOW YOU FOUGHT/HOW YOU EXECUTED） | ★★★ 重构：Match Entry Flow（选 Focus Player → Overview → Top Review Moments → Decision Card） |
| reference.py | ReferencePolicyProvider 等 | ★ 保留不动（PART K） |

## 2. V1.3.2 新增（spec PART A-P 落点）

| 能力 | 模块 | 对应 spec |
| --- | --- | --- |
| FocusPlayerContext（session/application 级一等概念） | `focus.py`（新）+ API | PART A §1-§2 |
| PlayerProfile（steam_id/name/is_user/created_at）+ remembered user（"This is me" 持久化） | db v7 + `focus.py` | PART A §4-§5、PART H §37-§39 |
| player-scoped API（overview/decisions/engagements/patterns/review-moments） | api.py | PART A §3 |
| ReviewMoment（selection/ranking/presentation 层，非新 detector） | `moments.py`（新） | PART B §8-§10 |
| Top Review Moments（默认 5，weighted factors + 解释，positive moments 含入） | `moments.py` | PART B §9、PART J §43-§44、PART I §42 |
| CalibrationSample（保留 original prediction + 分层采样） | `calibration.py`（新）+ db v7 | PART C §11-§12 |
| Calibration Review UI（单场景 Yes/No/Why + PREAIM 分类） | ui + api | PART D §20-§22 |
| Calibration metrics（precision/confirmation/per-context/confidence buckets/threshold sensitivity） | `calibration.py` | PART E §23-§27 |
| CalibrationState（UNCALIBRATED/EXPERIMENTAL/CALIBRATED/UNRELIABLE，样本量驱动） | `calibration.py` | PART E §28 |
| TrainingTarget calibration gate | training.py | PART E §29 |
| GeometryProvider 接口 + NullGeometryProvider + 成熟工具 spike | `geometry.py`（新）+ GEOMETRY_SPIKE.md | PART F §30-§33 |
| Player Match Overview（Good/Mixed/Needs Review，非 0-100 总分） | api + ui | PART G §34-§36 |
| 跨场 PlayerProfile 趋势（≥多场才显示） | api + ui | PART H |

## 3. 关键设计决策（审计结论）

1. **FocusPlayerContext 是 session 概念**：不硬编码进分析模块（分析层按 player_id 查询即可），由 API/UI 层维护当前 focus，并提供 `/api/focus-player` 设置/获取 + 持久化 remembered user（preferences 表或新 key-value 表）。
2. **ReviewMoment ≠ 新 detector**：只对已有 DecisionEpisode 做加权排名（actionability × sufficiency × impact × recurrence × training relevance），输出每个因素值 + `why_selected` 解释；默认 Top 5；含 positive moments（Good Decision 类）。
3. **CalibrationSample 保留 original prediction**：沿用 human_annotations 原则（预测与修正分离），新表存 detector_type/predicted_label/confidence/sufficiency + review_status/human_label/false_positive_reason。
4. **分层采样**：high-confidence positives / threshold-edge / ambiguous / negative-control / context-diverse（map/weapon/distance/method 多样）；每场 5-10 个。
5. **CalibrationState 样本量驱动**：reviewed <20 → UNCALIBRATED；≥20 且 precision ≥阈值 → CALIBRATED；precision 低 → EXPERIMENTAL/UNRELIABLE。
6. **PREAIM_ERROR 优先校准**（spec §13）：Review UI 提供 PREAIM 专用 false-positive 分类（UNEXPECTED_ENEMY_POSITION / TARGET_SWITCH / CLOSE_RANGE_DYNAMIC / VISIBILITY_APPROX / OTHER）；operational definition 写进文档（§14）。
7. **Geometry 不制造假精度**：GeometryProvider 接口 + Null 实现；metadata 含 geometry_source/quality/version；无几何时 EvidenceSufficiency 维持 MEDIUM/LOW（已有行为，保持一致）。
8. **UI 重构 Moment first**：Match → 选 Focus Player → Overview → Top Review Moments → Decision Card；debug 信息移到 Advanced；不做 0-100 总分（用 Good/Mixed/Needs Review + 分布）。

## 4. 明确不做（PART O）

- 不新增 Decision Family / 不训练模型 / 不建 Pro Corpus / 不做 0-100 总分 / 不做 LLM judge / 不重写 parser / 不做复杂 3D viewer。

## 5. 验收判定（PART P 对照）

| Scenario | 计划 |
| --- | --- |
| A 打开 Demo 先选 Focus Player | Match API 返回 players + 前端 selector（无假设 owner） |
| B 先看 3-8 个 Moment 而非数千条 | ReviewMoment API + UI 默认 Top 5 |
| C 切换玩家整个视图变化 | 所有 player-scoped 端点按 player_id 过滤 |
| D 未校准高频 detector 不当"最大问题" | TrainingTarget gate + ReviewMoment 校准权重 |
| E 人工确认 FP 保存 original+correction+reason | CalibrationSample schema |
| F 统计 detector reviewed 可靠性 | calibration metrics（precision/confirmation） |
| G 无几何时 Evidence 诚实 MEDIUM/LOW | GeometryProvider Null（已有 sufficiency 行为） |
| H 未来接 geometry 不重写核心 | GeometryProvider 接口隔离 |
