# HUMAN_CALIBRATION_PROTOCOL.md — 人工校准协议（V1.3.3 PART U）

> 目的：说明用户应如何审核校准样本，让 PlayerLab 的 detector 判断变得可信、
> 可验证、可复现。**Simulated labels ≠ ground truth**；只有 HUMAN 标签推动
> 真实 CalibrationState（PART A §2-§3）。

---

## 1. 流程概览

```
1. 导入 Demo → 选择 Focus Player（进入比赛）
2. Matches → 任一玩家 → "校准这个判断"（或直接 Calibration 标签页）
3. Calibration Lab → REVIEW SESSION：连续审核样本
4. 快捷键：1=Yes 2=No 3=Unsure S=Skip
5. 每场只需审 5-10 个高价值样本（PART D §12）
```

## 2. 审核目标（先确认系统说得对）

每个样本展示：
- **detector 判定**（PREAIM_ERROR / MOVING_SHOT / DRY_PEEK ...）
- confidence + evidence sufficiency
- 上下文：round / tick / stratum

你的任务是回答：
> "系统这个判定在**这个具体场景**下是对的吗？"

## 3. 各 detector 的审核要点

### PREAIM_ERROR（PART E §16）

measurement = **首次可见敌人时的 crosshair offset**；interpretation = 这是否
真的是 pre-aim 问题。**以下情况不算 PREAIM_ERROR**：

| 分类 | 含义 |
| --- | --- |
| REAL_PREAIM_ERROR | 敌人正常出现在预期位置，但准星没预瞄到 |
| UNEXPECTED_ENEMY_POSITION | 敌人在不可预期位置出现（预瞄正确但位置变了） |
| TARGET_SWITCH | 从第一个目标切换到第二个 |
| MULTI_TARGET_TRANSITION | 多个目标切换中 |
| CLOSE_RANGE_DYNAMIC_FIGHT | 近距离动态交火（预瞄概念不适用） |
| VERTICAL_ADJUSTMENT | 垂直角度调整中 |
| VISIBILITY_APPROXIMATION | 视野近似误差（无几何时） |
| REACTION_ONLY | 纯反应射击（没有预瞄时间） |
| INSUFFICIENT_CONTEXT | 信息不足 |
| OTHER / UNSURE | 其他 / 不确定 |

### MOVING_SHOT（PART F §18-§19）

measurement = SHOT_WHILE_MOVING（行为事实）；interpretation = MOVEMENT_HURT_ACCURACY。
**velocity > threshold ≠ error**。分类：
- ACTUAL_INACCURATE_MOVING_SHOT：移动确实导致打偏
- COUNTER_STRAFE_TRANSITION：急停过渡中的合理射击
- LOW_SPEED_ACCEPTABLE：低速移动射击可接受
- SMG_CLOSE_RANGE_REASONABLE / PISTOL_DYNAMIC_REASONABLE / SHOTGUN_REASONABLE：
  武器/距离上下文下合理
- AIRBORNE_SPECIAL / DETECTION_ERROR / INSUFFICIENT_CONTEXT / OTHER / UNSURE

### DRY_PEEK（PART G §21-§22）

DRY_PEEK 是**行为**（无 flash 辅助的 peek），不是错误。评价：
- REASONABLE_DRY_PEEK：结合 utility 可用性/时间压力/tradeability/objective 需要
- QUESTIONABLE_DRY_PEEK / POOR_DRY_PEEK
- INSUFFICIENT_CONTEXT / UNSURE

## 4. Negative Controls（PART K §32）

某些样本是 **negative control**（系统判断"没问题"）。目的：
> 确认确实没问题 → 未来可估算 false negatives / recall。

## 5. 校准状态含义

| 显示 | 含义 |
| --- | --- |
| Pipeline: VALIDATED | 管线能跑通（simulated 已验证流程） |
| Pipeline: NOT_TESTED | 尚无 review 样本 |
| Ground Truth: UNCALIBRATED | 无/极少 HUMAN 标签 |
| Ground Truth: EXPERIMENTAL | 有少量 HUMAN 标签（5-20） |
| Ground Truth: CALIBRATED | ≥20 HUMAN 标签 + precision ≥0.7 |
| Ground Truth: UNRELIABLE | HUMAN 标签足够但 precision ≤0.4 |

**UI 双状态显示**（PART B §9）：Pipeline 与 Ground Truth 永远分开 —— 模拟数据
只能点亮 Pipeline，不能点亮 Ground Truth。

## 6. 诚实规则（PART V）

- 你还没标任何样本时：统计页显示 `NO_REAL_CALIBRATION_AVAILABLE`。
- 模拟 review 数永远与 HUMAN 数分开显示（永不合并）。
- 系统不会用模拟数据解锁 TrainingTarget 或提升 ReviewMoment 权重。
