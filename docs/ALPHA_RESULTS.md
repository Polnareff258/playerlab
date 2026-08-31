# ALPHA_RESULTS.md — V1.1-alpha 实施结果（Phase A–G 完成）

> 状态：**三个 Alpha Pattern + Improvement Loop + Human Annotation Loop 均已真实运行**。
> 按 spec §48：本文件完成后暂停，等待人工确认，不自动扩展。

---

## 1. 实现了什么

| 模块 | 内容 | 文件 |
| --- | --- | --- |
| Schema 迁移 v2 | 10 张新表（execution_metrics / patterns / pattern_evidence / root_causes / training_targets / target_measurements / target_status_history / human_annotations / preference_annotations / review_queue）+ 版本化迁移器 | db.py |
| 执行指标 | move-and-shoot（速度@射击）+ counter-strafe（峰值/减速时间/急停/稳定前射击），2722 次射击逐发分析 | execution.py |
| Pattern A | Immediate Same-Angle Re-peek：first_contact/angle_delta/time_delta/position_delta/相关敌人/outcome/证据；评估 REASONABLE/QUESTIONABLE/POOR/INSUFFICIENT_EVIDENCE（含反事实支持） | patterns.py |
| Pattern B | Move-and-Shoot / Counter-Strafe（execution family 合并） | patterns.py |
| Pattern C | Advantage Overaggression：5v4 等优势态 → 孤立交火/无紧迫目标/低信息收益 → POSSIBLE_ADVANTAGE_OVERAGGRESSION，trade support / objective urgency / info gain 三因子 | patterns.py |
| Root Cause（简化） | Result→Execution→Micro→Macro，上游优先回退，任意层 UNKNOWN | rootcause.py |
| Bottleneck | Frequency×Impact×Confidence×Trainability → HIGH/MEDIUM/LOW + 可解释分解 + 门槛（eligible） | bottleneck.py |
| TrainingTarget | 目标生成（baseline/goal/trigger/cue）、Active Focus ≤2（1 执行 + 1 宏观）、三通道验证、状态流转 | training.py |
| Human Annotation | HumanAnnotation/PreferenceAnnotation/ReviewQueue、review 预算、JSONL 导出、agreement/置信校准统计 | annotation.py |
| 集成 | batch 每场自动跑 alpha 管线；CLI 10 个新命令；API 10 条新路由；UI 首页改为 CURRENT FOCUS + Review 标注卡 | alpha.py / cli / api / ui |

## 2. 测试情况（全部通过）

- `tests/test_alpha.py` **7/7**：re-peek（正确检测/合理/证据不足）、move-shoot（移动射击/正确急停/阈值边界/非枪械过滤）、advantage（孤立违规/合理主动/支援场景）、training（baseline/Active Focus 2 上限/窗口不足）、annotation（预测保留/纠正分离/版本字段/非法 reason code 拒绝）、review（低置信高影响优先/预算上限）
- `tests/test_core.py` **13/13**（V1 回归，含批次测试隔离修复）
- 复现性：alpha 管线重跑结果一致（4/2722/132 样本、60 DPs）

## 3. 真实 Demo 结果（de_dust2，18 局，60 DPs）

| Pattern | n | violation rate | conf | bottleneck | Target 生成 |
| --- | --- | --- | --- | --- | --- |
| move_shoot | 2722 次射击 | **17.3% 移动首枪** | 0.68 | **HIGH** | ✅ ACTIVE（17%→9% 目标） |
| advantage | 132 次优势态交火 | 0.8%（1 例） | 0.53 | MEDIUM | ✅ ACTIVE（1%→0.4%） |
| repeek | 4 次 RE_PEEK | 100%（全 POOR/QUESTIONABLE） | 0.32 | LOW（不达标） | ❌ INSUFFICIENT_EVIDENCE（n=4<8） |

- **CURRENT FOCUS（UI 首页）**：2 个 ACTIVE 目标（1 Execution + 1 Macro，符合 §16 上限）——move-and-shoot（WHEN 交火时 / DO 急停再开枪 / AVOID 移动开第一枪）与 advantage（WHEN 人数优势 / DO 保持可换人结构 / AVOID 孤立 1v1）。
- **Review Queue**：4 条（2 条 QUESTIONABLE re-peek、1 条 overaggression、1 条高分 re-peek）——低置信高影响优先排序正确。
- **Human Annotation（经 UI 实测）**：提交 1 条 INCORRECT → 已入库（prediction 保留、纠正分离、alpha-1 版本齐全）→ stats 输出 agreement=0.0（与人工判断一致）→ JSONL 导出成功。

## 4. Loop 验证结论

**Loop A（Improvement Loop）**：Demo → 检测（17.3% 移动首枪）→ Bottleneck（HIGH）→ TrainingTarget（ACTIVE）→ 待后续场次验证（当前仅 1 场历史，窗口测量返回 PENDING_WINDOW/INSUFFICIENT_DATA——诚实）。**闭环机制已验证，样本积累需多场。**

**Loop B（Learning Loop）**：prediction + human correction + model/rule/config version + reason code 全部保存；agreement 统计与置信校准桶输出；**可支撑未来 threshold calibration / 监督学习**（spec §31 顺序）。

## 5. False Positives 与已知局限（诚实披露）

1. **advantage 检出率极低（0.8%）**：132 例优势态交火仅 1 例判违规——检测器保守（trade/urgency/info 三因子同时 LOW 才判）。可能漏报；需人工标注校准（这正是 review 循环的用途）。
2. **repeek 评估依赖反事实支持**：当前 cf=INSUFFICIENT（DISENGAGE 对照样本不足），评估分主要来自接触结果/支援/信息——单场数据下全部样本被判 POOR/QUESTIONABLE，需更多场验证。
3. **无几何 LOS**：advantage 的「孤立」用队友距离近似；re-peek 的「无新信息」用 n_known_enemies 近似——均会在 Review 中呈现给用户纠正。
4. **outcome 通道未接入**：validation 的 outcome_verdict 目前固定 OUTCOME_UNCERTAIN（窗口样本不足）；move_shoot 样本未关联死亡结果（后续用 damage/kill 关联）。
5. **黄金样本 14/15**：demo 中恰有 4 个 RE_PEEK DP（5 个目标少 1）；执行/优势各 5。`spike/golden_alpha.json` 的 human_label 为待确认种子（经 review 循环精化）。
6. **单场数据限制**：所有「跨场聚合/窗口验证」在当前只有 1 场时如实返回样本不足。

## 6. 下一步最值得扩展（建议顺序）

1. **多场入库**（batch）→ 让 repeek 达标、validation 窗口真实运行（§44 验收路径直接依赖）
2. **outcome 关联**：move_shoot 样本 → 后续 2s 死亡/伤害关联（Impact 更准）
3. **advantage 校准**：用 review 标注调 trade/urgency/info 阈值（threshold calibration 第一优先级，§31）
4. **Preference 标注 UI**（root cause 双候选 A/B）——schema/API 已备
5. 更细的 counter-strafe 武器相关阈值（spec §4 明确「第一版不追求复杂模型」）

## 7. 运行方式

```powershell
cd playerlab\core
python3 -m playerlab.cli alpha "path\demo.dem"     # 全管线
python3 -m playerlab.cli patterns | focus | targets | review
python3 -m playerlab.cli annotations stats | annotations export --out ..\backtest\ann.jsonl
python3 -m playerlab.cli api --port 8125           # UI（首页=CURRENT FOCUS）
```
