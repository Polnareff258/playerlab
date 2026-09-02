# V1_3_4_2_DELTA.md — Evidence Honesty & Demo-Centric Human Validation

## 目标

1. 收紧无真实 visibility evidence 时的因果判断（MotionRelation ≠ Causality）。
2. 将 Human Review 重构为 Demo-Centric Review Session（One Demo = One
   Review Session，Blind first，时间顺序，Conflict 后置）。

不扩大 Decision Family。

## 完成（对照规格 PART A–AN）

### PART A-F — Evidence Honesty
- `MotionRelationEvidence`（SELF_MOVING/ENEMY_MOVING/BOTH_MOVING/BOTH_STABLE/
  MIXED/UNKNOWN）：可观测行为类别，与 ContactInitiation 解耦。
- `classify_initiation_v2` 加诚实门：无真实 `visibility_tick`（causal=False）
  → 默认 UNKNOWN/STATIC_CONTACT；BOTH_MOVING 永不自动 → MUTUAL。
- `motion_evidence` 锚点修正：有真实 visibility → `[visibility-W, visibility]`
  （causal=True）；无 visibility → shot/damage 窗口产出 descriptive profile
  （causal=False）。`possible_visibility_tick`（FOV）仅 informational。
- `outward_motion` → `motion_consistency`（原名误导）。
- Evidence Strength：UI 显示 Strong/Medium/Weak；API 输出
  `evidence_strength` + `calibrated_confidence=None`（无伪校准）。
- 文档：`docs/EVIDENCE_HONESTY.md`。

### PART G-H — Annotation Schema 正规化
- db v12：`contact_action_annotations` 加 `dimension / review_outcome /
  blind_review / revision_of / revision_reason`（一维度一条）。
- Review outcome：LABELED / UNSURE / INSUFFICIENT_INFORMATION / SKIPPED。
- 人工标注不覆盖 rule/model prediction（HUMAN label 与 prediction 分离）。
- INSUFFICIENT_INFORMATION 不进入 accuracy/calibration（Observability
  Ceiling）。

### PART I-N — DemoReviewSession
- 新表 `demo_review_sessions` + `review_session.py`：
  session_id/demo_id/player_id/sample_ids(冻结)/recommended_sample_ids/
  current_index/计数/status(NOT_STARTED→IN_PROGRESS→COMPLETED)。
- `build_demo_candidates`：按 (player, enemy, round) 去重（同一次接敌只标
  一次）、round ASC/tick ASC 时间序。
- Active-learning 推荐子集（20-40/demo，选样不重排）。
- focus player 绑定；无则让用户先选。

### PART O-Q — Blind Review / Conflict / Resume
- Blind 首屏不显示系统答案；提交后 Reveal + DISAGREEMENT 标记；
  annotation 保存 `blind_review=true`。
- Conflict Review 只列 Human≠Model 样本，允许看完整系统 evidence；
  改判追加新 annotation（`revision_of` 指向原盲审），历史不覆盖。
- Resume：current_index 即时保存，Continue Review 定位下一未解析样本。

### PART R-U — Summary / Navigation
- Demo 完成生成 summary：reviewed / label 分布 / model agreement /
  insufficient 数。
- Prev/Next 不跨 Demo；Round selector；完成后不自动切 Demo
  （Review Conflicts / Back to Demo List / Start Next Demo）。

### PART V-Z — Review Card / Sanity
- 盲审卡默认只显示必要上下文 + Raw Demo Evidence（位置/运动/事件，无系统
  解释标签）。
- `contact-sanity` 输出 ALL / PENDING / REVIEWED_HUMAN 三群组（防 selection
  bias）。
- STEALTH_PRESERVING 是 ContextHypothesis（"Possible stealth-preserving
  context"），非 DecisionGood；support_style 与 evaluation 分离。
- CS-NET 保持 Auxiliary：不出现在 Blind 首屏，不参与 label/GroundTruth/
  initiation。

### PART AB-AK — Regression / API / Migration / Freeze
- `contact-regression` 支持 HUMAN 样本回归集（真实标注自动积累）。
- API：`/api/contact-review/demos` + session/start|current|answer|skip|
  revision|summary|conflicts。
- 旧 contact_action_samples/annotations 保留（数据迁移安全，session 能把
  已有 pending 分配到对应 demo session）。
- Session sample_ids 冻结；classifier rerun 不改变审核集合。
- sample 记录 detector_version/git_commit/geometry_version/config_hash。

### PART AL — Tests
- test_v134.py：golden 测试改用真实 visibility 窗口；新增 7 项证据诚实测试
  （无 LOS 降级、possible 非因果锚、motion window 修正、consistency 改名）。
- test_v1342.py（新）：13 项 session/blind/conflict 测试（单 demo 单 player、
  时间序、resume、freeze、HUMAN 不覆盖、旧标注迁移、insufficient 排除、
  skip 非 label、选样不重排、blind 隐藏、conflict 保留原标注）。

## Definition of Done 对照

| 项 | 状态 |
| --- | --- |
| A 无 geometry both moving → MotionRelation=BOTH_MOVING + Initiation=UNKNOWN | ✅ test |
| B possible_visibility 不作 causal anchor | ✅ test |
| C 有真实 visibility 用紧邻窗口 | ✅ test |
| D UI 显示 Evidence Strength | ✅ |
| E Contact Review 首页先选 Demo | ✅ UI |
| F Session 只含一个 Demo + focus player | ✅ test |
| G 样本 round/tick 排序 | ✅ test |
| H Blind 看不到系统答案 | ✅ UI + test |
| I 提交后 Reveal | ✅ UI |
| J Demo 完成生成 Summary | ✅ UI + API |
| K Continue Review 恢复位置 | ✅ test |
| L 区分 UNSURE/INSUFFICIENT/SKIPPED | ✅ schema |
| M Conflict 保留原 blind annotation + revision | ✅ test |
| N 默认审核推荐样本 | ✅ |
| O ContactEpisode 去重 | ✅ dedup by player/enemy/round |
| P 开始积累真人 regression | ⏳ PENDING_HUMAN_REGRESSION_REVIEW（真实标注积累中） |

## 验证摘要

- `python3 -m pytest tests/ -q`：163 通过。
- 浏览器实测：Demo 列表 → Review Recommended → Blind Review（1/6，
  系统答案隐藏）→ 三问题提交 → Reveal（YOUR LABEL vs PLAYERLAB +
  DISAGREEMENT）→ 下一片段推进（r2→r3 时间序）。
- Steam_id 全程字符串传递（修复 parseInt >2^53 截断：76561198359094561
  被截成 ...560 的 bug）。
