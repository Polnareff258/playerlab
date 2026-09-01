# V1_3_2_RESULTS.md — Calibration, Ground Truth & Player-Centric UX 实施结果

> 状态：**FocusPlayerContext / player-scoped API / Player Overview / Top Review
> Moments / Decision Card UX / CalibrationSample / Calibration Review UI /
> detector calibration statistics / TrainingTarget calibration gate /
> GeometryProvider interface / multi-player real-demo validation / reports 全部完成**。
> 按 PART Q Pause Rule 停止：不进入 V1.4 / Pro Reference 实现 / Tiny Model 训练。

---

## 1. 交付清单（PART Q 对照）

| 交付 | 模块 | 状态 |
| --- | --- | --- |
| FocusPlayerContext | `focus.py` | ✅ |
| player-scoped API（overview/decisions/engagements/patterns/review-moments/calibration） | `api.py` | ✅ |
| Player Overview（Good/Mixed/Needs Review，无 0-100） | `moments.py` | ✅ |
| Top Review Moments（Top 5，weighted factors + why_selected + positive 槽位） | `moments.py` | ✅ |
| Decision Card UX（WHY/HOW/HOW EXECUTED + Evidence 弱化） | `ui/index.html` | ✅ |
| CalibrationSample（original prediction 保留 + 分层采样） | `calibration.py` + db v7 | ✅ |
| Calibration Review UI（单场景 Yes/No/Unsure + FP 原因） | ui + api | ✅ |
| detector calibration statistics（precision/confirmation/buckets/state） | `calibration.py` | ✅ |
| TrainingTarget calibration gate（UNCALIBRATED → PAUSED） | `training.py` | ✅ |
| GeometryProvider interface + Null + awpy adapter | `geometry.py` + GEOMETRY_SPIKE.md | ✅ |
| multi-player real-demo validation | 6 场 3 图 + 多玩家 | ✅ |
| 报告（V1_3_2_DELTA / CALIBRATION_RESULTS / PLAYER_UX_RESULTS / GEOMETRY_SPIKE） | docs/ | ✅ |

## 2. 测试（PART L §45-§52，12 项全过 → 86/86）

| 测试 | 覆盖 |
| --- | --- |
| test_focus_player_isolation | §45：A 的 overview 不含 B 的 episodes |
| test_focus_switch_changes_view | §46：切换 A→B 结果改变 |
| test_remember_player_default_focus | §47：remember → 默认 focus + steam_id string 防精度回归 |
| test_review_moment_ranking_gate | §48：calibrated 不被 uncalibrated 抑制 |
| test_calibration_gate_no_high_conf_target | §49：UNCALIBRATED → PAUSED 非 HIGH-conf |
| test_good_example_in_review_moments | §50：Good Decision 可入选 |
| test_player_scope_db_queries | §51：player-scope 无跨玩家污染 |
| test_outcome_independence_kept | §52：outcome 不入 evaluation |
| test_calibration_sample_preserves_original | PART C/E：original prediction 保留 + precision |
| test_calibration_state_thresholds | PART E §28：状态机 |
| test_geometry_provider_contract | PART F §31-§33：Null + fallback + no fake precision |
| test_episode_detector_extraction | detector → calibration sample 映射 |

## 3. 实测（6 场 3 图）

- 330 calibration samples（7 detector 分层，跨 7 场入库记录）
- 模拟 review 验证管线：PREAIM 25→0.80→CALIBRATED；MOVING 25→0.60→EXPERIMENTAL
  （**标注 GROUND_TRUTH_PENDING_HUMAN_REVIEW**，非真实人工）
- Player Overview 实测：MIXED + Strong ADVANTAGE 78% + Needs review CONTACT 13%
- Top 5 Moments 实测：4 improvement + 1 good，含 "reduced: detector uncalibrated" 门控
- **steam_id 精度 bug 发现并修复**：JS >2^53 截断 → 全链路字符串化

## 4. PART P Scenario 对照

| Scenario | 结果 |
| --- | --- |
| A 打开 Demo 先选 Focus Player | ✅ Match 页 selector（不假设 owner） |
| B 先看 3-8 Moment 而非数千条 | ✅ Top 5 Review Moments |
| C 切换玩家整个视图变化 | ✅ player-scoped API + 测试 |
| D 未校准高频 detector 不当最大问题 | ✅ cal_penalty + TrainingTarget PAUSED |
| E 人工确认 FP 保存 original+correction+reason | ✅ CalibrationSample schema + 测试 |
| F 统计 detector 可靠性 | ✅ calibration_stats（precision/state） |
| G 无几何时 Evidence 诚实 MEDIUM/LOW | ✅ NullGeometry + sufficiency 降级（V1.3.1 已有） |
| H 未来接 geometry 不重写核心 | ✅ GeometryProvider 接口隔离 |

## 5. 下一步（未做，PART Q Pause）

- 真实人工标注（用户通过 Calibration Lab UI）→ 真实 precision / 阈值调优
- awpy 地图资产接入（`geometry_provider=awpy`）→ EvidenceSufficiency 部分升 HIGH
- multi-match PlayerProfile 趋势（≥多场 + 校准证据）
