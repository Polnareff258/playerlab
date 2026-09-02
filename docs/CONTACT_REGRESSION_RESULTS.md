# CONTACT_REGRESSION_RESULTS.md — Contact Regression Set（V1.3.4.1 PART P）

> **诚实状态：`PENDING_HUMAN_REGRESSION_REVIEW`**
> 本版本建立了 contact regression 框架与命令，但**尚无真人确认样本**
> （V1.3.4.1 之前 contact_action_samples 未被管线填充；本版本已在
> `analyze_match` 中接入 persist_contact_samples）。用户开始真实 review 后，
> 每个 HUMAN 标注样本自动进入 regression set。

## 目标集（规格 §44：≥10 真人确认样本）

| 建议分布 | n |
| --- | --- |
| HOLD / enemy initiated（架枪接敌） | 5 |
| SELF PEEK（主动拉） | 3 |
| MUTUAL（双方接敌） | 1 |
| MICROADJUST HOLD（小幅调整架枪） | 1 |

所有样本 `label_source = HUMAN`（contact_action_samples 表），绝不写入
detector ground truth。

## 使用方式

```powershell
# 1. 跑 alpha 管线（自动持久化 pending contact samples）
python -m playerlab.cli alpha SampleDemo\g161-20260828202750949889581_de_dust2.dem

# 2. 在 UI 的 Contact Review 页回答三问题（谁主动 / 你在做什么 / 什么支援）
#    -> 每答一个样本即 label_source=HUMAN, review_status=reviewed

# 3. 运行 regression 对比
python -m playerlab.cli contact-regression --samples docs\contact_expected.csv
# 输出每行：expected / predicted / confidence / pass/fail

# 4. 导出为 CSV 对照表（手工维护 expected）
# 列：sample_id, initiation, action, label_source
```

## 当前结果

```
PENDING_HUMAN_REGRESSION_REVIEW — 尚无真人标注样本（等待 Contact Review 流程）。
```

跑 `python -m playerlab.cli contact-sanity` 可查看当前 pending 样本的
initiation 分布与 sanity 警告（MUTUAL 率 / UNKNOWN 率 / PEEK inflation）。

## 附录：如何判断"expected"

| 情形 | expected initiation | expected action |
| --- | --- | --- |
| 我稳定架枪、敌人走出来 | ENEMY_INITIATED | HOLD |
| 我主动拉出、敌人架枪 | SELF_INITIATED | PEEK |
| 双方同时暴露 | MUTUAL | （不判 PEEK） |
| 烟雾消散/门/几何 | STATIC_CONTACT | HOLD/UNKNOWN |
| 小幅 AD 修正 | ENEMY_INITIATED | HOLD（MICROADJUST_HOLD） |
