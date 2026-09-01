# DETECTOR_VALIDITY_REPORT.md — Detector 有效性报告（V1.3.3 PART U）

> 状态：**NO_REAL_CALIBRATION_AVAILABLE**（无 HUMAN 标签，PART V）
> 本报告区分：measurement validity（测量是否测对）· interpretation validity
> （解释是否成立）· human confirmation（真实验证）· geometry sensitivity。
> 全部结论为 **structural audit + simulated pipeline validation**，非人工确认。

---

## 1. PREAIM_ERROR

| 维度 | 现状 |
| --- | --- |
| **measurement** | `FIRST_VISIBILITY_CROSSHAIR_OFFSET`：首次可见敌人帧的 crosshair→enemy 角度误差（head/chest 近似 hitbox） |
| **measurement validity** | ✅ 角度计算正确（CS2 yaw 0=+y 语义已修正）；但**无几何**时 enemy 位置来自 PlayerKnownState last-seen（可能有 VISIBILITY_APPROXIMATION） |
| **interpretation** | `PREAIM_ERROR` = offset 高 ⇒ 预瞄问题。**不必然成立**：目标切换 / 意外位置 / 近距离动态 / 多目标会误判（PART E §14） |
| **human confirmation** | 0（等待标注；9 类 taxonomy 已备：REAL_PREAIM_ERROR / UNEXPECTED_ENEMY_POSITION / TARGET_SWITCH / ...） |
| **geometry sensitivity** | 未测（资产缺失 → GEOMETRY_AB_PENDING_ASSETS） |
| **simulated pipeline** | PIPELINE_VALIDATED（25 条模拟 review 验证管线跑通） |

**审计结论**：detector 测量的是**角度偏移**，不是完整 pre-aim quality ——
内部 measurement 名 `FIRST_VISIBILITY_CROSSHAIR_OFFSET`，`PREAIM_ERROR` 是
更高层 interpretation。V1.3.2 的 PREAIM 高数量（2509/6场）**不能直接解读为
玩家预瞄差**：需 HUMAN 标注区分 UNEXPECTED_ENEMY_POSITION 等 FP 类别。

## 2. MOVING_SHOT

| 维度 | 现状 |
| --- | --- |
| **measurement** | `SHOT_WHILE_MOVING`：开枪 tick 的 lateral velocity ≥130u/s |
| **measurement validity** | ✅ 行为事实（速度投影到 view-perpendicular 轴）；阈值 130 为单值 |
| **interpretation** | `MOVEMENT_HURT_ACCURACY`（隐式）：velocity>thr ⇒ error。**不成立**：SMG 近距 / pistol 动态 / 急停过渡 / 低速可接受 |
| **human confirmation** | 0（10 类 taxonomy 已备） |
| **weapon-aware threshold** | ⚠️ 未分武器组（rifle/SMG/pistol/sniper/shotgun）；`threshold_sensitivity` 已实现，**等 HUMAN 数据后调**（PART F §20：不无证据改阈值） |
| **simulated pipeline** | PIPELINE_VALIDATED（25 条） |

**审计结论**：需把 `SHOT_WHILE_MOVING`（行为）与 `MOVEMENT_HURT_ACCURACY`
（评价）在 schema/输出中显式分离；武器感知阈值依赖 HUMAN 标注。

## 3. DRY_PEEK

| 维度 | 现状 |
| --- | --- |
| **measurement** | 无 self/team flash 辅助的 PEEK（flash 事件检测） |
| **measurement validity** | ✅ 行为事实（flash in inventory + flash detonate event） |
| **interpretation** | ⚠️ V1.3.1 中 DRY_PEEK 参与 engagement 评价降分（QUESTIONABLE）；**V1.3.3 强制语义**：DRY_PEEK 是行为不是错误（PART G §21），评价需结合 utility/time/tradeability/objective/info/weapon/geometry |
| **human confirmation** | 0（4 类：REASONABLE/QUESTIONABLE/POOR/INSUFFICIENT_CONTEXT） |
| **simulated pipeline** | NOT_TESTED |

**审计结论**：engagement_evaluation 对 DRY_PEEK 的降分规则需 HUMAN 校验 ——
合理 dry peek（必须 entry + 队友可 trade）不应被降分。

## 4. FIRE_BEFORE_AIM_READY

| 维度 | 现状 |
| --- | --- |
| **measurement** | 开枪帧 crosshair error ≥ 阈值（bucket HIGH/MEDIUM） |
| **measurement validity** | ✅ 角度误差合理；但无几何时 enemy pos 近似 |
| **interpretation** | "定位未稳定即开枪"；**需区分** panic fire / pre-fire / spam / close-reaction / burst-continuation / target-switch（PART C §18） |
| **human confirmation** | 0；样本 8 < 20 目标（该 demo 集检出少） |
| **simulated pipeline** | NOT_TESTED |

## 5. 汇总

| detector | measurement | interpretation 风险 | human | 建议 |
| --- | --- | --- | --- | --- |
| PREAIM_ERROR | 角度 offset（valid） | 高（FP 类别多） | 0 | 优先标注；taxonomy 9 类 |
| MOVING_SHOT | 速度事实（valid） | 中（武器/距离上下文） | 0 | 标注 + weapon-aware threshold |
| DRY_PEEK | flash 缺失（valid） | 中（行为≠错误） | 0 | 标注 4 类评价 |
| FIRE_BEFORE_AIM_READY | 角度误差（valid） | 中（fire 类别区分） | 0 | 补样本 + 标注 |

## 6. Honest Note

`NO_REAL_CALIBRATION_AVAILABLE` —— 以上为结构审计 + simulated pipeline 验证；
**不把规则输出当 ground truth**（PART V）。真实有效性由 Calibration Lab 的
HUMAN 标注驱动：每场审 5-10 个，统计页将显示 human confirmation rate 并驱动
CalibrationState（UNCALIBRATED → ... → CALIBRATED/UNRELIABLE）。
