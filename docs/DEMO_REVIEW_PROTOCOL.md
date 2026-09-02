# DEMO_REVIEW_PROTOCOL.md — Demo-Centric Human Review（V1.3.4.2 PART I-U）

核心原则：

> One Demo = One Review Session
> Active Learning chooses WHAT to review.
> Chronological order chooses HOW to review.
> Blind first. Model comparison second. Conflict review third.

## 1. Demo 选择（PART J）

Contact Review 首页显示 Demo 卡片：

```
Mirage · 2026-08-30 21:43
FOCUS PLAYER: Dhv (队伍 2)
Recommended: 28 · All candidates: 173 · Reviewed: 17
[Review Recommended] [Review All] [Continue Review]
```

排序：latest match first。每张卡绑定一个 focus player（FocusPlayerContext
或用户选择 "Which player is you?"）。

## 2. Review Budget（PART M）

默认生成 **Recommended Review Set**（20-40 samples/demo，config 可调）。
Active Learning 选样优先：PEEK vs HOLD ambiguous、initiation UNKNOWN、
geometry/rule disagreement、support uncertainty、flank/stealth、high
impact、rare context、sample deficit。**选样永不重排** —— 样本仍按
round ASC、tick ASC 展示。

## 3. Blind Review（PART O）

第一遍审核**隐藏系统答案**。用户只看到：

```
Round 8 · 00:42 · tick 13682
Opponent: xxx
[必要上下文: 原始位置/运动/事件timeline]

Q1 谁主动建立了接敌？
Q2 你当时在做什么？
Q3 什么支援存在？
```

- **Blind flag**：提交的 annotation 保存 `blind_review=true` —— 未来论文可
  明确 "Human labels collected before model output exposure"。
- 提交后 Reveal：显示 YOUR LABEL vs PLAYERLAB，不同则标 DISAGREEMENT。
- Raw Demo Evidence 展开只显示 positions/movement/event timing/weapon/
  utility —— 不显示 system prediction/support classification/CS-NET。

## 4. 时间顺序（PART L）

固定 round ASC、tick ASC。Prev/Next 只在当前 Demo 内移动，不跨 Demo。
Round selector 方便在 CS Demo Manager / 游戏内同步回放。

## 5. Review Outcome（PART H）

```
LABELED                  人工明确判断（3 维度各一条 annotation）
UNSURE                   信息大致够，但无法明确判断
INSUFFICIENT_INFORMATION demo 缺判断所需信息（无音频/隐藏意图/无 geometry）
SKIPPED                  暂时跳过，可回看；不是 label
```

INSUFFICIENT_INFORMATION 不进入：classifier error、training ground truth、
calibration accuracy（Observability Ceiling）。

## 6. Conflict Review（PART P/AD）

一个 Demo 的 blind review 完成后，列出 Human != PlayerLab 的样本。此阶段
允许看 model prediction / rule evidence / geometry / motion / support /
CS-NET auxiliary。用户若改判，系统追加写入一条新标注记录，其
`revision_of` 字段指向原盲审标注的 annotation_id —— **第一次 blind label
原样保留，历史不被覆盖**（PART AD §AnnotationRevision 语义）。

## 7. Session Resume（PART Q/AG）

每次 answer/skip/position/outcome 即时保存。关闭后 Continue Review 直接
定位到下一个未解析样本。sample_ids 在 session 创建时**冻结** —— classifier
rerun 不得改变当前审核集合和顺序（防 queue 漂移）。

## 8. Demo Completion Summary（PART R）

完成后显示：reviewed / 各 label 分布 / model agreement（仅 HUMAN 可用标签）/
insufficient 数。按钮：Review Conflicts / Back to Demo List /
Start Next Demo（不自动切 Demo）。

## 9. 快捷键（PART AF）

S=skip，I=insufficient，1/2/3=轮换 Q1-Q3 选项，Enter=提交。按钮完整保留。
