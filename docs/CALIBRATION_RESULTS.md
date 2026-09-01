# CALIBRATION_RESULTS.md — 校准与 Ground Truth 结果（V1.3.2 PART M）

> 数据：6 场真实 demo（3 de_dust2 + 3 de_mirage，128 局）· 日期：2026-09-01
> **Ground Truth 状态：GROUND_TRUTH_PENDING_HUMAN_REVIEW**
> 本报告中的 precision/confirmation 数字来自**模拟人工 review**（脚本标记的
> 合理标签分布），用于验证校准管线；**不是真实人工标注**。真实校准需用户在
> Calibration Lab UI 逐条确认（PART N §53：不把规则输出当 ground truth）。

---

## 1. 校准管线交付

| 能力 | 状态 |
| --- | --- |
| CalibrationSample schema（保留 original prediction + human correction 分离） | ✅（db v7 + `calibration.py`） |
| 分层采样（high-conf / threshold-edge / ambiguous / negative-control / context-diverse） | ✅ `_stratified_pick`（map/weapon/distance 多样） |
| PREAIM / MOVING_SHOT 专用 FP 分类（PART C §13/§15） | ✅ 9 + 8 类 |
| Calibration Review UI（单场景 Yes/No/Unsure + Why） | ✅ Calibration Lab 页 |
| 校准指标（precision / per-context / confidence buckets / threshold sensitivity） | ✅ |
| CalibrationState（UNCALIBRATED/EXPERIMENTAL/CALIBRATED/UNRELIABLE，样本量驱动） | ✅ |
| TrainingTarget calibration gate（PART E §29） | ✅（UNCALIBRATED → PAUSED + note） |

## 2. 采样数量（PART N §53 目标对照）

6 场共生成 **330 个 calibration samples**（PENDING_REVIEW）：

| detector | samples | 目标 | 达标 |
| --- | --- | --- | --- |
| PREAIM_ERROR | 56 | 30+ | ✅ |
| MOVING_SHOT | 56 | 30+ | ✅ |
| IRREGULAR_DUEL_MOVEMENT | 56 | 15+ | ✅ |
| DRY_PEEK | 56 | 20+ | ✅ |
| JIGGLE | 50 | 10+ | ✅ |
| TEAM_FLASH_PEEK | 48 | 10+ | ✅ |
| FIRE_BEFORE_AIM_READY | 8 | 20+ | ⚠️（该 demo 集 FIRE_EARLY 样本少；多场后目标场次的更多） |

## 3. 校准指标（模拟 review，验证管线）

| detector | reviewed | confirmed | precision | state |
| --- | --- | --- | --- | --- |
| PREAIM_ERROR | 25 | 20 | **0.80** | **CALIBRATED**（≥20 样本 + ≥0.7 precision） |
| MOVING_SHOT | 25 | 15 | **0.60** | **EXPERIMENTAL**（≥20 但 precision <0.7） |
| 其余 | 0 | 0 | — | UNCALIBRATED |

**说明**：这是模拟标签（PREAIM 80% 确认 / MOVING 60% 确认 + 合理 FP 原因分布），
**证明校准统计与状态机工作**；真实 precision 待人工标注。spec §24 遵守：只报
confirmation rate（positive-only review），不假装总体 accuracy（无 negative control）。

## 4. FP 分类分布（模拟）

- **PREAIM_ERROR**：UNEXPECTED_ENEMY_POSITION / TARGET_SWITCH / CLOSE_RANGE_DYNAMIC_FIGHT / VISIBILITY_APPROXIMATION_ERROR / OTHER（各 1）→ 验证分类多样性
- **MOVING_SHOT**：COUNTER_STRAFE_TRANSITION / LOW_SPEED_ACCEPTABLE_SHOT / SMG_CLOSE_RANGE_REASONABLE / PISTOL_DYNAMIC_FIGHT / FALSE_DETECTION / AIRBORNE_SPECIAL / UNKNOWN / OTHER

## 5. Confidence Buckets（PART E §26）

- PREAIM：MEDIUM 25 例 → confirmed 0.8（单调性验证待更多 bucket 数据）
- MOVING：MEDIUM 25 例 → confirmed 0.6

> 若真实标注后 HIGH/MEDIUM/LOW 无单调性 → confidence 设计需修（§26 明确）。

## 6. Threshold Sensitivity（PART E §27）

`calibration.threshold_sensitivity` 已实现（对比候选数 vs precision at
confidence 0.5/0.6/0.7/0.8）；待真实标注后运行 —— 不在模拟数据上发布数字
（避免误导）。当前 honest 输出：higher threshold = fewer candidates。

## 7. TrainingTarget Gate（PART E §29 实测）

测试验证（`test_calibration_gate_no_high_conf_target`）：
- UNCALIBRATED detector + 高频率 → target 为 **PAUSED**（"Possible Issue" + 
  `needs calibration` note，confidence 0.3）
- CALIBRATED → ACTIVE（confidence 0.9×0.7 或 0.9）

## 8. PREAIM_ERROR Operational Definition（PART C §14）

detector 测量的是 **crosshair-to-enemy angle 在首次可见帧的误差**（`_preaim_error`），
**不是** 完整 pre-aim quality。已文档化：若敌人在不可预期位置 / wide swing 出现 /
目标切换 / 第二目标进入，首次可见的 crosshair 偏离**不构成** PREAIM_ERROR ——
这些是 FP 分类的候选（UNEXPECTED_ENEMY_POSITION / TARGET_SWITCH / MULTI_TARGET /
CLOSE_RANGE_DYNAMIC / VISIBILITY_APPROX）。**Calibration Review 是验证该定义
是否符合真实意图的入口。**

## 9. 局限（诚实）

1. **全部指标基于模拟 review**（管线验证用）——真实 precision 需人工标注。
2. per-context precision 需要样本携带 context（weapon/distance）——当前 sample
   stratum 为 general；后续把 episode 的 weapon_matchup 写进 sample。
3. FIRE_BEFORE_AIM_READY 样本 8 < 20（该 demo 集检出少）——多场后补。
4. negative control（系统判断无问题的样本）未纳入当前采样——recall/accuracy
   不可估计（spec §24 已声明）。
