# EVIDENCE_HONESTY.md — 证据诚实性（V1.3.4.2 PART A-F）

核心区分：

```
Motion               ≠  Exposure causality
Both moving          ≠  Mutual initiation
FOV                  ≠  Visibility
Possible visibility  ≠  Causal anchor
Rule score           ≠  Calibrated probability
```

## 1. MotionRelation 与 ContactInitiation 解耦

V1.3.4.1 曾把 motion 过度解释成 causality：双方都动就判 MUTUAL，即使没有
任何 LOS 证据。V1.3.4.2 正式拆成两层：

**MotionRelationEvidence**（观测/行为类别，`classify_motion_relation`）：

```
SELF_MOVING / ENEMY_MOVING / BOTH_MOVING / BOTH_STABLE / MIXED / UNKNOWN
```

BOTH_MOVING 只证明"双方都在动"，**不证明**"双方共同造成接敌"。

**ContactInitiation**（因果判断，`classify_initiation_v2`）保持：
SELF_INITIATED / ENEMY_INITIATED / MUTUAL / STATIC_CONTACT /
INFORMATION_CONTACT / UNKNOWN —— 但必须由真实 exposure 证据支持。

## 2. 无真实 visibility 时的诚实门

`motion_evidence` 现在只认 `visibility_tick`（geometry-confirmed LOS
transition）为因果锚点。没有真实 visibility 时：

- MotionRelation 正常计算（可观测）；
- ContactInitiation **默认 UNKNOWN**（除非双方都静止 → STATIC_CONTACT）；
- BOTH_MOVING 永不自动映射为 MUTUAL。

`possible_visibility_tick`（FOV-only）是 **informational evidence only**：
不得用于 causal 锚点、PEEK/MUTUAL 确认、visibility-confirmed evaluation。
UI 显示为 "Possible visual alignment"，从不显示成 "Visibility started here"。

## 3. Motion window

- 有真实 visibility：`[visibility_tick - W, visibility_tick]`，测紧邻 LOS
  transition 的运动（causal=True）。
- 无 visibility：窗口锚在 shot/damage，产出 **descriptive pre-contact
  motion profile**（causal=False），不得产生强因果。

## 4. Outward motion 更名

旧的 `self_outward_motion` 实际是 movement direction consistency（速度与
位移方向的一致性），不是"朝向 exposure boundary 的运动"。已更名
`self_motion_consistency / enemy_motion_consistency`，避免误导。
真正的 exposure-driving motion（LOS(current) vs LOS(projected)）是可选
enhancement，本版本不强行实现。

## 5. Evidence Strength ≠ Calibrated Confidence

规则 score 归一化不是真实概率。UI 现在显示 **Evidence: Strong/Medium/
Weak**（不再显示 "Confidence: High"）；API 输出：

```python
{"evidence_strength": "STRONG",      # rule-derived
 "calibrated_confidence": None}      # None 直到有足够 HUMAN labels
```

Advanced 区显示 raw rule score 并标注 "Not calibrated probability"。

## 6. 为什么这样改（真实数据教训）

V1.3.4.1 无 geometry 实跑 MUTUAL ≈ 40-55%：motion window 落在 shot anchor
上时双方都在交火中移动，对称 motion 被误读成 mutual causality。拆分
MotionRelation（可观测）与 ContactInitiation（需因果证据）后，无 LOS 的
BOTH_MOVING 主要落为 ContactInitiation=UNKNOWN，MUTUAL 应明显下降。
