# REUSE_MATRIX.md — Phase 2：外部能力审计与复用矩阵

> 审计对象：Freezetime / cs2-structural-analytics / CounterStrafe / AWPy / CS Demo Manager / demoparser2 / 及 V1 已研究生态。
> 复用原则（spec §2）：成熟 + License 兼容 + 接口适合 → dependency/adapter/algorithm/data reuse；**不要自行重复开发**。
> License 结论先行：**Freezetime (MIT) 是本阶段最有价值的参考实现；cs2-structural-analytics 无 License（仅可借鉴指标规格，不可复制代码）。**

---

## 1. 重点项目详解

### 1.1 Freezetime（benginN/csfreezetime）— ★★★ 最重要参考
| 项 | 值 |
| --- | --- |
| URL / License / 活跃度 | github.com/benginN/csfreezetime · **MIT** · 255+ commits，2026-07 仍在更新（一手核实：license=MIT，desc="Self-hosted, coach-grade CS2 analysis"） |
| 定位 | 本地优先教练级 CS2 分析平台：**parse once, query forever**（Rust 解析 → 16Hz 位置/kills/nades/economy → 数百预计算特征入 Postgres+ClickHouse → 之后一切是查表） |
| 功能 | 2D replay、heatmap、**ghost rounds**（半透明轨迹叠加、按 round start/plant/first-kill 对齐）、**Pattern Finder**、Moments、**Scenarios**、**对手报告**（setups/rotations/map-control→outcome/trades）、ML Lab（LightGBM 本地训练）、veto sim、WASM 浏览器解析 |
| 可复用 | ①「parse-once-query-forever」架构思想（PlayerLab 已具雏形：ticks 缓存 + canonical）；② ghost rounds 概念与对齐方案；③ Scenarios 检索交互；④ 对手报告结构（rotations/map-control→outcome） |
| 不可照搬 | Rust 解析器（PlayerLab 已锁 demoparser2）；Postgres+ClickHouse 栈（PlayerLab 用 SQLite，规模不同） |

### 1.2 cs2-structural-analytics（Grant-Holloway369/cs2-structural-analytics）
| 项 | 值 |
| --- | --- |
| URL / License | github.com/Grant-Holloway369/cs2-structural-analytics · **无 License（README 声明 proprietary）** · demo 性质（1 commit, 2025-02） |
| 内容 | Trade/Spacing 分析 demo + Streamlit 展示，demoparser2 后端 |
| **可复用（指标规格，非代码）** | **Trade Efficiency** = trades / geometric opportunities（队友 ≤800u + LOS/FOV + NavMesh pathing 排除穿墙误判 + 速度向量检查排除 baiting）；WPA per trade；**spacing** = 战斗时与最近队友的平均欧氏距离 |
| 不可复用 | 代码本身（无 License）——只能把公式作为规格参照 |

### 1.3 CounterStrafe 与执行指标生态（一手核实，2026-08-31）
GitHub 检索 `counter-strafe cs2` / `counterstrafe counter-strike` 结论：**不存在成熟、MIT、面向 demo 分析的 counter-strafe 库**。命中项目均为：
- 训练 overlay/工具（非 demo 分析）：cs2kitchen/CS2-Counter-Strafing-Utility（MIT，★13，辅助练习）、gnarr/dStrafe（MIT，★2，训练 overlay）、LolitaIceMia/CounterStrafeTestTools（GPL-3.0）、asss-whom/NullMovement（无 license）
- 小型 demo 分析工具：TsunamiBlue/CounterStrafeAnalyzer（NOASSERTION，★0，评价工具）、naeyn/counterstrafe（无 license，web demo 分析 + 2D replay）
- 无 pip/npm 同名包（404）

**决策**：执行指标（move-and-shoot / counter-strafe quality / first-shot timing）**由 PlayerLab 自定义实现**——所需遥测（速度@射击、按键位掩码、角度、事件）V1 已全具备，规则简单；训练 overlay 类工具仅作 V3（训练器集成）的参考背景。

### 1.4 V1 已研究生态（回顾，详见 EXISTING_PROJECTS.md）
- **demoparser2**（MIT，Rust）：PlayerLab 解析层，已锁定 0.42 + FieldMap。
- **AWPy**（MIT）：nav 区域、visibility（BVH LOS）、heatmap、trades 函数、CLUTCH 相关统计 —— 区域/可视性/热力可直接复用原语。
- **CS Demo Manager**（MIT）：trade 检测、2D viewer 交互范式、平台识别 —— trade 分析参考。
- **@cs2dak/maps / cs2-demo-format**（MIT）：zones/callouts、duels/clutches 数据契约 —— 区域语义与交战窗口参考。

---

## 2. 能力 × 来源矩阵（spec §2 重点项）

| Feature | Existing project | Maturity | License | Reusable? | Integration approach | Need custom? |
| --- | --- | --- | --- | --- | --- | --- |
| duel 检测/窗口 | cs2-demo-format duels.json；PlayerLab duel 归属（已有） | 中 | MIT | ✅ 部分 | 复用数据契约语义；PlayerLab 归属逻辑已实现 | 少量对齐 |
| aim mechanics（first-shot/flick） | 无成熟开源（CounterStrafe 研究待补） | — | — | ❌ | — | ✅ 自定义（遥测齐全） |
| counter-strafe | CounterStrafe 项目（待补） | — | — | ? | 待确认 | 可能自定义 |
| utility 分析 | Freezetime nades；@cs2dak utility | 中 | MIT | ✅ 参考 | 借鉴事件建模 | 本地实现（简单） |
| economy | Freezetime economy 特征；cs2-demo-format player-economies | 高 | MIT | ✅ 参考 | 借鉴特征清单 | 本地已有 item_purchase 数据 |
| **map control** | 无独立库（Freezetime 有 map-control→outcome 报告） | 低 | MIT(参考) | ⚠️ 概念参考 | 借鉴 zone-occupancy 思路 | ✅ zone occupancy 自定义 |
| **rotation** | 仅 Freezetime 内部（非独立库） | 低 | MIT(参考) | ⚠️ 概念参考 | 借鉴其对手报告结构 | ✅ 自定义（MACRO_DESIGN §2） |
| **trade** | cs2-structural-analytics 规格 + CSDM + Freezetime | 中 | 规格无License | ✅ 规格参考 | 按其公式实现（≤800u+LOS 排除误判） | ✅ 本地实现 |
| **spacing** | cs2-structural-analytics 规格（战斗时最近队友距离） | 中 | 规格无License | ✅ 规格参考 | 直接按其公式 | ✅ 本地实现（简单） |
| **ghost rounds** | 生态无此术语（skkwowee/cs2-demo-viewer 的 ghost-dot 预测叠加最接近） | 空白 | MIT(参考) | ❌ | **PlayerLab 原创定义**：相似状态检索 + 胜率 delta + ghost-dot 渲染 | ✅ 原创（V1.2 排期） |
| **scenario retrieval** | ggViz（nav-mesh place-count token + 精确匹配 + modified Hamming，MIT 原型，死仓库）+ Freezetime Scenarios | 原型级 | MIT(研究) | ⚠️ 算法蓝图 | 复用 token 化算法思想；特征源用 cs2-demo-format replay.json（8Hz 状态流） | ✅ 扩展 PlayerLab 相似度引擎 |
| win probability（WPA） | 无公开 CS2 模型；Xenopoulos XGBoost 特征集（map/ticks/equipment/players/HP/bomb/site 距离）可复刻 | 论文级 | — | ⚠️ 特征规格参考 | 按特征集自训 CS2 模型（Brier 校准） | ✅ 后置（V1.2 反事实增强） |
| **territory / positional value** | 无（研究确认缺口） | — | — | ❌ | — | ✅ 自定义（后置） |
| 证据 → round/tick 追溯 | PlayerLab 已有；Freezetime 亦有 | 高 | MIT | ✅ | 保持现有 | 无 |

---

## 3. 对 PlayerLab V1.1 的复用决定

| PlayerLab V1.1 能力 | 复用/参考来源 | 决策 |
| --- | --- | --- |
| Spacing / Tradeability（MACRO §4） | cs2-structural-analytics 指标规格 + CSDM trade | **按规格本地实现**（公式明确、遥测齐全）；标注「规格来源」 |
| Rotation / Map Control（MACRO §2/§5） | Freezetime 对手报告结构（概念） | **自定义**（zone occupancy + 状态机），借鉴其「map-control→outcome」呈现 |
| Ghost rounds（后续） | 生态空白（无此术语）；ghost-dot 预测叠加可参考 | **PlayerLab 原创**：相似状态检索 + 胜率 delta + ghost-dot 渲染（对齐 round start/plant/first kill，借鉴 Freezetime 对齐方案） |
| Scenario retrieval（后续） | ggViz 算法蓝图（nav 区域计数 token + 精确匹配）+ cs2-demo-format replay.json | 扩展 PlayerLab 相似度引擎（已有特征向量基础）；ggViz 仓库为 2020 死原型，不直接依赖 |
| Win probability / WPA（后置） | Xenopoulos XGBoost 特征集（论文规格） | 自训 CS2 模型（公开无 CS2 模型）；仅用于反事实/ghost rounds 的增强证据，不进入 V1.1 MVP |
| 执行指标（move-and-shoot / counter-strafe） | CounterStrafe 研究待补 | 若成熟且 MIT → adapter；否则自定义（规则简单） |
| Pattern Finder（§8） | Freezetime Pattern Finder（概念） | PlayerLab 原创实现（结合反事实支持，比其纯统计更进一步） |

## 4. 明确不引入的外部依赖（保持 PlayerLab 独立性）

- Postgres/ClickHouse（Freezetime 栈）——SQLite 规模足够，避免运维复杂度。
- Rust 解析器（Freezetime 自研）——已锁定 demoparser2。
- cs2-structural-analytics 代码——无 License，不可复制（仅规格）。
- 任何 AGPL/非商用组件（历史审计已确认规避）。

## 5. 研究边界说明

- 所有结论以一手来源标注（GitHub/npm/arXiv/Crossref/Semantic Scholar 直查；firecrawl 限流期间未依赖其结果）。
- **ghost rounds**：经 DuckDuckGo/Bing/GitHub 检索确认为生态空白术语 → PlayerLab 原创定义（本矩阵即定义依据）。
- **CounterStrafe**：一手检索确认无成熟 MIT 的 demo 分析库（多为训练 overlay）→ 执行指标自定义（见 §1.3）。
- **ESTA 数据集**（CC BY-SA 4.0，1558 场职业 demo）仅兼容 awpy 1.x——未来训练用，V1.1 不引入。
- 商业工具（recoilanalytics / roundiq / cs2.cam）未经深度验证，不构成复用依据。
