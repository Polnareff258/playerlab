# V1_1_AUDIT.md — Phase 1：PlayerLab 仓库审计

> 审计日期：2026-08-31 · 审计对象：https://github.com/Polnareff258/playerlab（HEAD `093feda`）
> 目的：确认 V1 现状，识别 V1.1（Evidence-Driven Improvement Loop）可直接复用的组件与缺口。

---

## 1. 仓库状态

| 项 | 值 |
| --- | --- |
| 分支 | master（3 个提交：MVP → 推送说明 → 批量分析模块） |
| 工作树 | clean；.gitignore 隔离 data/、backtest/、探针输出、测试临时目录 |
| 本地数据 | `data/playerlab.sqlite`：1 个真实 demo（de_dust2，18 局）→ 60 DPs；`data/analyses/` canonical JSON + tick pickle 缓存 |

## 2. 代码结构（core/playerlab/，17 模块）

| 模块 | 职责 | V1.1 复用度 |
| --- | --- | --- |
| ingest.py | demoparser2 0.42 适配（FieldMap）+ canonical JSON + tick 缓存 + 侧别（m_iTeamNum） | ★★★ 直接复用 |
| fieldmap.py | canonical 字段 ↔ parser 字段映射（位置/速度差分/按钮/武器/点位名） | ★★★ 直接复用 |
| state.py | PublicInfo、PlayerKnownState（证据模型：视野/声音/伤害/道具/bomb/经济）、GroundTruth、yaw 校准 | ★★★ **V1.1 宏观分析的信息基础** |
| decision.py | 交战状态机 + 五动作族（PEEK/HOLD/RE_PEEK/DISENGAGE/FALLBACK）+ duel/outcome | ★★★ Micro 层直接复用 |
| features.py | StateFeatureVector（PlayerKnownState 白名单）+ Hard Filter + 加权软相似度 | ★★★ 检索/模式聚类基础 |
| counterfactual.py | 检索 → 按动作分组 → Wilson CI → 证据强度 → verdict | ★★★ **V1.1 诊断证据核心** |
| stats.py | Wilson CI / Brier / 校准桶 | ★★★ |
| db.py | SQLite（7 表）+ JSON 净化 | ★★★（需扩展新表） |
| backtest.py | LOMO holdout / QA 导出 / ablation | ★★★ 验证基建 |
| batch.py | 批量 demo 发现/幂等/失败隔离/报告 | ★★★ 多场数据前提 |
| api.py / cli.py | stdlib HTTP API + 17 个子命令 | ★★★（新增命令） |
| ui/index.html | Match View / Decision Review / What If / Evidence / Ground Truth | ★★★（首页改造） |
| buttons.py / weapons.py / zones.py | 按键解码 / 武器表 / 区域语义 | ★★★ |

## 3. 已实现能力（V1）

### 3.1 DecisionPoint
- 检测：逐玩家交战 episode → 五动作族谓词（速度/方向/角度/窗口，全部 config 参数化）→ 去重 → 显著性 Top-N（30–80/场）
- 每 DP 携带：start/decision/end tick、observed_action、alternatives、zone/place、confidence、significance、evidence（ticks+events+sources）、meta（episode/opponent/anchor）
- 实测：60 DPs/场（PEEK 28 / HOLD 22 / DISENGAGE 6 / RE_PEEK 4），确定性复现（dp-id 哈希稳定）

### 3.2 双状态（hindsight 守卫）
- `decision_states.ground_truth`：上帝视角（敌人位置/hp/武器）——只用于 outcome/replay/debug
- `decision_states.known_state`：PlayerKnownState（own/team vision、footstep/shots/grenade 声音、伤害来源、bomb、经济、teammate_near）——决策层唯一可用
- 审计断言：Decision 层特征白名单强制（测试覆盖）

### 3.3 Counterfactual
- 流程：StateFeatureVector（12 数值特征 + map/side/zone/weapon_class）→ Hard Filter → 加权软相似度 → top-k → 按动作分组 → Wilson CI（survival@W / round_win / duel）→ 证据强度（n/高相似/分布/confounders/missing）→ verdict
- verdicts：COMPARISON_AVAILABLE / INSUFFICIENT_EVIDENCE / NO_COMPARABLE_ALTERNATIVE / NO_RELIABLE_DIFFERENCE
- 实测：RE_PEEK 查询 → HOLD n=8 / PEEK n=8 / DISENGAGE n=2，CI 重叠诚实返回 NO_RELIABLE_DIFFERENCE

### 3.4 证据追溯
- 每个 DP 链到 demo_id + round + 精确 tick；evidence.events 含 damage/kill 明细（tick、weapon、dmg、distance）
- UI Evidence 面板可展开；Show Similar Rounds 返回可点击的 match/round/tick

### 3.5 验证基建
- backtest：LOMO holdout（校准 ±10pp 门槛 + Brier）、Retrieval QA 导出、特征 ablation
- 单元测试 13/13（含反事实 verdict 纪律、batch 失败隔离）；复现性哈希断言

## 4. V1.1 缺口清单（本次要建设的）

| 能力（spec 章节） | 现状 | 缺口 |
| --- | --- | --- |
| Decision Hierarchy（§4） | DP 只有动作族标签 | 无 Micro/Local/Macro 分级 |
| Root Cause Chain（§5） | 无 | 无 Result→Immediate→Execution→Micro→Local→Macro 因果链 |
| Decision vs Execution（§6） | 有 duel/outcome，无执行指标 | 无 move-and-shoot / counter-strafe / first-shot 分析 |
| 宏观分析（§7） | 无 | 无 Information Discipline / Rotation / Advantage / Spacing / Map Control / Timing |
| Repeated Pattern Mining（§8-9） | 无 | 无跨场模式挖掘（结合相似度/反事实/执行质量） |
| Bottleneck Ranking（§11） | 无 | 无 Frequency×Impact×Confidence×Trainability 排序 |
| TrainingTarget（§12-16） | 无 | 无目标对象/基线/测量定义/Active Focus 限制 |
| Improvement Validation（§17-19） | backtest 有校准 | 无行为采纳/结果变化分离验证（BEHAVIOR_CHANGED/OUTCOME_UNCERTAIN） |
| Longitudinal Progress（§23） | 无 | 无跨场 timeline / status 流转 |
| 首页改造（§21） | Match View 首屏 | 需 CURRENT FOCUS 首屏 |

## 5. 关键复用结论

1. **PlayerKnownState/PublicInfoBuilder 是 V1.1 宏观分析的唯一合法信息源**——信息纪律（§7.1）、旋转质量（§7.2）、优势管理（§7.3）全部建立在它之上；hindsight 守卫断言必须扩展覆盖新模块。
2. **Counterfactual 引擎直接作为诊断证据**（§10）：Pattern 的负结果率必须与同状态备选动作比较，而非只看死亡次数。
3. **batch + ticks 缓存**已为多场数据铺路：Pattern Mining 需要 ≥3–5 场才出信号（§8）。
4. **stats.py**（Wilson CI）支撑 Bottleneck Confidence 与 Validation 判定。
5. UI 为单文件静态页，首页改造（CURRENT FOCUS）可在现有框架内完成。

## 6. 风险备注

- 本地库曾被测试脚本污染（已修复测试的 Config(data_dir=...) 隔离，并清理了真实库）——**V1.1 起所有测试必须隔离 DB**（回归项）。
- 单 demo 数据量下 Pattern/Validation 必然大量 INSUFFICIENT_EVIDENCE——这是设计内行为，不是缺陷（§30）。
