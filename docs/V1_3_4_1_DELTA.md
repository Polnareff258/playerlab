# V1_3_4_1_DELTA.md — Contact Correctness, Support Semantics & UX Cleanup

## 目标

修正 V1.3.4 中接敌主动方判断的核心逻辑问题，并让新语义真正可用于真实 Demo
review。不扩展新大功能（不进 V1.4 / Pro Reference / Tiny Model / 新 Decision
Family）。

## 本版本完成（对照规格 PART A–Z）

### PART A — ContactInitiation v2（核心修复）
- 新增 `InitiationMotionEvidence`（displacement/speed/peak/outward/stability/
  yaw_change × 双方）
- `classify_initiation_v2`：motion-based 分类，**禁止**
  `self_tick == enemy_tick → MUTUAL`（该判据已删除）
- config：`initiation_motion_window_ticks`（默认 32）、
  `initiation_min_speed` / `initiation_min_displacement` /
  `mutual_motion_ratio` / `static_motion_max` 等
- 文档：`docs/CONTACT_INITIATION_FIX.md`

### PART B — ExposureRelation 重新定义
- 新增 `pair_visible`（对称 engageability）、`self_motion_state` /
  `enemy_motion_state`、velocity 字段
- 语义：exposure state 只是 pairwise engageability，不是"谁主动暴露"

### PART C — 真正生成 visibility_tick
- `fill_visibility_ticks` / `scan_visibility_transition`：geometry LOS 首
  次 NOT_VISIBLE→VISIBLE 写入 `visibility_tick`
- 无 geometry：只写 `possible_visibility_tick`（FOV-only），sight_state 诚实
- decision 层传入 `build_fov_lookup`（校准 yaw offset）

### PART D — HOLD Stability v2
- yaw_variance 用 **circular angular difference**（`yaw_variance_circular`）
- `lane_stability`、`MICROADJUST_HOLD`、`ACTIVE_HOLD`
- HOLD confidence 被 self 移动抑制（避免把 Peek 误判为 Hold）

### PART E/F — PEEK / Re-Peek v2
- PEEK 要求 SELF_INITIATED + LOS gain + motion overlap + enemy stable
- Re-Peek 要求 EXPOSED→COVERED→SELF_INITIATED + same-angle similarity

### PART G — SupportContext
- 新 `context_semantics.py`：正交 `support_style / utility_type`
- TEAM_UTILITY_ASSISTED 需 timing + **spatial** 相关（无关队友闪不算）
- COORDINATED_TEAM_PEEK / UNASSISTED / STEALTH_PRESERVING
- engagement 集成：`method_dimensions`（base_action/movement_style/
  support_style/utility_type）

### PART H — StealthContext
- `FlankState` MVP（NOT_FLANKING/POSSIBLE_FLANK/ACTIVE_FLANK/DEEP_FLANK/
  UNKNOWN）
- 只使用可观测证据（damage/visual/public/grenade reveal）
- `STEALTH_PRESERVING`（深绕后 + 低暴露 + 道具会暴露）

### PART I — SIGHTING_RESPONSE / SightState
- `sight_state_from_relation`：OUT_OF_FOV / IN_FOV_OCCLUDED / VISIBLE /
  POSSIBLY_VISIBLE / UNKNOWN
- geometry 确认 VISIBLE 才是真 sighting；无 geometry 是 POSSIBLE_SIGHTING

### PART J — UNKNOWN / AMBIGUOUS
- UNKNOWN 是合法输出；`ambiguous_labels` 传播（UI 显示
  "Ambiguous: Peek / Hold"）
- `why` 解释来自 evidence（非模板）

### PART K — CS-NET Boundary Audit
- CS-NET 保持 auxiliary（`csnet_assist.py`），不得修改 ContactInitiation /
  ObservedAction / SupportStyle / GroundTruth / CalibrationState

### PART L/M/N/O — UX
- 新增 **Contact Review 页**（新 tab）：3 问题（谁主动/你在做什么/什么支援），
  全答后确认提交，片段隔离，Advanced 折叠显示 motion/LOS
- Decision Card / Contact Card 不再显示原始 JSON；confidence 用 High/Medium/Low
  映射（contact 卡）
- `why` 一句话解释

### PART P/Q/R/S/T — 报告与指标
- `contact_report.py`：regression / sanity / benchmark / initiation 分布
- CLI：`contact-regression` / `contact-sanity` / `contact-benchmark`
- golden synthetic tests（test_v134.py 重写，见 PART Q 清单）
- sanity：MUTUAL 率阈值警告（INITIATION_CLASSIFIER_SUSPECT）、UNKNOWN 率
  INFO、PEEK inflation 仅警告

### PART U/V — API / UI cleanup
- `/api/contact-review`（GET 队列 + POST 三问题标注）、`/api/contact-review-stats`
- steam_id 保持 string

## Definition of Done 状态

| 项 | 状态 |
| --- | --- |
| A 真实架枪 → ENEMY_INITIATED + HOLD | ✅ golden test |
| B 主动拉 → SELF_INITIATED + PEEK | ✅ golden test |
| C 双方移动 → MUTUAL | ✅ golden test |
| D visibility_tick 真实填充 | ✅ `fill_visibility_ticks` + test |
| E yaw 179→-179 不破坏 HOLD | ✅ circular test |
| F 小幅 AD → MICROADJUST_HOLD | ✅ test |
| G 队友帮闪 → TEAM_UTILITY_ASSISTED | ✅ test（spatial relevant） |
| H 深绕后不丢道具 → STEALTH_PRESERVING | ✅ test |
| I 无 Geometry → 诚实 UNKNOWN | ✅ test |
| J CS-NET 只辅助 review | ✅ audit（不变） |
| K UI 不展示大量 JSON/enum | ✅ Contact/Decision 卡重做 |
| L 准备 10+ 真人 regression samples | ⏳ PENDING_HUMAN_REGRESSION_REVIEW |
| visibility_tick 填充 + 全部测试 | ✅ 见 tests/ |

## MUTUAL 率问题（PART R/S 调查）

真实 demo 初跑发现 MUTUAL ≈ 40%（sanity 触发
`INITIATION_CLASSIFIER_SUSPECT`）。调查后确认根因：

1. **motion window 落在 anchor（shot/damage）上**：窗口覆盖交火中双方都在动的
   时刻，每次交火都像 MUTUAL。
2. 修复：motion window 改为 **anchor 之前**的 span（
   `[pre_contact_start, anchor - initiation_motion_window_ticks]`）—— 测量
   **导致 LOS transition 的移动**，而非交火中的移动。
3. initiation 判定用 **sustained motion**（mean speed / displacement），
   瞬时 speed peak 不再算"推动接敌"。

> 无 geometry 时 LOS 不可用，exposure 全 UNKNOWN —— initiation 只能靠
> motion。遭遇战双方确实都动时 MUTUAL 是诚实结果；sanity 仍会标记
> SUSPECT 提醒 review。有 geometry（awpy .tri/.nav）后 exposure 可真实
> 翻转，initiation 会更准。

## 验证摘要

- `python3 -m pytest tests/ -q`：141 通过
- Contact Review UI：Contact tab + 三问题卡 + Advanced 折叠（浏览器实测）
- contact 语义：enemy-swing→HOLD、self-swing→PEEK、mutual→非 PEEK、
  static→STATIC/UNKNOWN、circular yaw、micro-AD、FOV occluded、
  NullGeometry honest UNKNOWN（golden tests）
