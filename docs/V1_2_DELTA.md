# V1_2_DELTA.md — Phase A：V1.2 与 V1.1-alpha 的增量审计

> 审计对象：alpha.py / patterns.py / training.py / rootcause.py / annotation.py / state.py / decision.py / db.py（HEAD `d46db8e`）。
> 目的：确认 V1.2 复用面与新增点（spec §61 Phase A）。

---

## 1. 现状（V1.1-alpha 关键结构）

| 模块 | 现状 | V1.2 复用 |
| --- | --- | --- |
| state.py | PlayerKnownState（视野/声音/伤害/bomb/经济）、PublicInfo、GroundTruth | ★★★ TemporalContext 的信息底座 |
| decision.py | 交战状态机 + 5 动作族 + duel/outcome | ★★★ ENGAGEMENT_COMMITTED 依据 |
| patterns.py | 3 个 alpha 检测器 + 聚合 | ★ 不改（§1 不扩 pattern） |
| rootcause.py | Result→Execution→Micro→Macro 简化链 | ★★ 升级为 7 层（§27） |
| training.py / bottleneck.py | TrainingTarget / 排序 | ★ 不动 |
| annotation.py | 4 类标注 + ReviewQueue + JSONL | ★★★ 扩展 5 类 + ambiguity + Preference UI |
| alpha.py | 每场管线 | ★★★ 插入 context/intent/feasibility/responsibility 阶段 |
| db.py | v2（19 表） | ★★★ 迁移 v3（context_events / intent_samples / root_causes 加列） |

## 2. V1.2 新增（spec §2–§58 落点）

| 新能力 | 模块 | 对应 spec |
| --- | --- | --- |
| TemporalContext | context.py（新） | §3（窗口 3–8s，未来数据仅离线） |
| CommitmentState（11 态） | intent.py（新） | §4–§5（事件≠承诺，推断+UNKNOWN） |
| ActionFeasibility（6 态） | feasibility.py（新） | §6–§8、§45（规则引擎） |
| SituationalRole（15 态+置信分布） | intent.py | §9–§11（动态职责） |
| IntentState（14 态，规则基线） | intent.py | §12–§17（rotation vs reposition 重点） |
| ResponsibilityAttribution（8 类） | responsibility.py（新） | §20–§25、§54–§55 |
| Root Cause 7 层升级 | rootcause.py | §27 |
| IntentSample / feature sequence | context.py + db | §28–§30（归一化，不保存 raw） |
| Reference 接口 | reference.py（新） | §36–§42（Null/Stub 实现） |
| 标注升级 + ambiguity review | annotation.py | §18–§19、§46–§50 |
| context-eval / 数据集导出 | cli / api | §49–§50 |

## 3. 复用与不重复开发

- **Zone**：复用 zones.py（区域语义）；地图相对坐标由 map bounds 归一化（自研，简单）。
- **Visibility/LOS**（§44 spike）：alpha 已知局限（队友距离≠trade support）。V1.2 **研究**是否引入 LOS 原语——结论：awpy 的 .tri BVH 需下载地图资产 + patch 对齐，成本偏高；V1.2 以「无 LOS」为显式 LIMITATION（§44），在 feasibility/responsibility 中标注置信降级，不伪造精度。
- **Trade context**：复用 alpha 的 teammate distance + damage 事件；LOS 缺失记为 LIMITATION。
- **bomb state / plant/defuse 事件**：已有事件流（bomb_beginplant/begindefuse 在 list_game_events 中，需新增解析）——补入 ingest。

## 4. 明确不做（§1、§36、§62）

不扩 pattern、不做 rotation/map-control/timing score、不建 Pro corpus/downloader、不训练 Transformer（Phase H 由标签数量门控）、不自动上线宏观评分系统。

## 5. 测试与黄金集规划（§51–§55）

- intent golden：≥50 样本（当前 1 场 → 如实输出 PARTIAL_DATASET）
- commitment golden：plant/reload/utility/engagement/free 各 ≥1
- responsibility 场景 ≥10（合成，作为测试）：plant-commit 队友死亡 / reload 失误 / utility commitment / supported trade / unsupported teammate peek / good decision bad outcome / bad decision good outcome
- 回归：Good Outcome ≠ Good Decision；Bad Outcome ≠ Bad Decision（§54–§55）
