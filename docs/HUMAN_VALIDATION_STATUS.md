# HUMAN_VALIDATION_STATUS.md — 真人校准/审核状态（V1.3.4.2）

> **诚实状态：`INSUFFICIENT_HUMAN_VALIDATION`**
>
> V1.3.4.2 建立了完整 demo-centric 盲审流程，但**真实人工审核仍在起步
> 阶段**。以下数字如实记录，未达到阈值前不宣称模型已校准。

## 当前真实 HUMAN 数据

| 指标 | 值 |
| --- | --- |
| HUMAN 标注样本数（contact，盲审） | 1（验证流程时录入） |
| 其中 LABELED（3 维度齐全） | 1 |
| INSUFFICIENT_INFORMATION | 0 |
| UNSURE | 0 |
| SKIPPED | 0 |
| HUMAN vs 模型 disagreement | 1（真人判 ENEMY_INITIATED，系统判 MUTUAL） |
| 盲审标记（blind_review=true） | 1 |

## 结论

- **`INSUFFICIENT_HUMAN_VALIDATION`**：样本远未达到 PART AB 目标
  （20-30 个真实样本，优先 10 enemy-initiated HOLD / 8 self PEEK /
  3 mutual / 3 micro-adjust / 3 unsure-insufficient）。
- 在足够 HUMAN 样本前：
  - `calibrated_confidence` 保持 `None`（不伪装成校准概率）；
  - UI 显示 Evidence: Strong/Medium/Weak（规则分，非概率）；
  - 不产出 ground-truth 驱动的校准/accuracy 结论。

## 如何使用本版本审核流程积累数据

1. Contact Review → Choose Demo → Review Recommended（每 Demo 20-40 样本）。
2. Blind 回答三问题（Q1 谁主动 / Q2 你做什么 / Q3 什么支援）→ 提交后
   Reveal，分歧样本后续进 Conflict Review。
3. 每标完一个 Demo，运行：
   ```powershell
   python -m playerlab.cli contact-regression --samples <expected.csv>
   python -m playerlab.cli contact-sanity
   ```
4. 样本数达到阈值后更新本文件状态，并可用 HUMAN 标签评估
   `calibrated_confidence`。

## 追踪

- contact_action_samples / contact_action_annotations 表存全部 HUMAN 标注
  （每维度一条，含 blind/revision 元数据）。
- Session 进度存 demo_review_sessions（可 Continue Review 恢复）。
- 本文件随真实审核进展更新。
