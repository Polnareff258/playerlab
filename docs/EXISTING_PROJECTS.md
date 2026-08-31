# EXISTING_PROJECTS.md — 阶段 1：现有项目研究

> PlayerLab V1 决策文档 · 研究日期：2026-08-31（研究子代理对活源核实：GitHub / npm / PyPI / crates.io / readthedocs / arXiv / OpenAlex；本机对关键包做了运行时验证）
>
> 结论先行：**PlayerLab 的解析层、数据契约、2D replay、LOS 可见性、统计脚手架全部有成熟实现可复用；决策点检测、玩家可知状态重建、相似状态检索、反事实比较是现有生态的空白，是 PlayerLab 的护城河。**

---

## 0. 总览表

| 项目 | 定位 | 语言/形态 | License | 与 PlayerLab 的关系 |
| --- | --- | --- | --- | --- |
| DAK Studio / cs2-demo-analysis-kit | 桌面分析工作台 + 产品中立 packages | Python(pywebview) + TS | 生态包 MIT / Studio AGPL-3.0 | **最接近的现有产品**；analysis substrate |
| cs2-demo-format | 解析后数据交换契约（ZIP） | TS + JSON Schema + Python(cs2df) | MIT | 推荐作为 canonical 数据层 |
| @cs2dak/core / maps / cohort | DemoPackage→AnalysisBundle→DemoViewModel；地图/雷达/区域 | TS | MIT | 可直接复用 |
| @akiver/cs-demo-analyzer | Go CLI + Node 包装的解析器（事件型，JSON Match 输出） | Go + Node | MIT | 事件型解析备选 |
| demoparser2（LaihoE/demoparser） | Rust 高速解析核心（Python/JS/WASM 绑定） | Rust | MIT | **推荐解析层**（本机已验证） |
| demoinfocs-golang | Go 解析器（生产级，HLTV 等在用） | Go | MIT | 解析备选（csda 的后端） |
| AWPy | Python 分析 + 可视化 + nav + LOS | Python(Polars) | MIT | 复用 visibility / nav / stats |
| CS Demo Manager | 本地 demo 管理 + 分析桌面应用 | Electron + React | MIT | 复用平台识别 / 2D viewer 思路 |
| pbdems2 / source2-demo | Rust Source2 解析原语 | Rust | MIT | 未来解析层备选 |
| csgostats.gg | 云端统计（闭源） | — | 闭源 | 仅参考数据模型 |
| ggViz / Valuing Player Actions（论文） | 相似游戏状态检索 / 动作价值 | 研究 | — | **PlayerLab 检索与反事实的研究模板** |

---

## 1. DAK Studio / CS2 Demo Analysis Kit

**仓库**：[github.com/Starfie1d1272/cs2-demo-analysis-kit](https://github.com/Starfie1d1272/cs2-demo-analysis-kit)（v0.8.0，作者 Starfie1d1272）
**License**：双轨 —— `@cs2dak/*` + Python 侧 **MIT**；`apps/dak-studio` 桌面应用 **AGPL-3.0-only**。

### 核心功能（DAK Studio 应用）
本地优先桌面工作台：2D replay、逐选手档案、Duel & Mechanics Lab（用 `.tri` 物理网格做 line-of-sight 的 TTK / first-shot / counter-strafe / pre-aim 分析）、Utility Lab、Economy & Round Flow、Tournament Hub、Coach Workbench；IndexedDB 本地存储；**每个统计都链回精确的 round 与 tick**（evidence-first）。

### 架构（官方 README 明示的管线）
```
.dem → cs2df（Python 参考导出器，demoparser2 后端）
     → cs2-demo-format v3 ZIP（唯一的 Python↔TS 接缝）
     → @cs2dak/core（DemoPackage → AnalysisBundle → DemoViewModel）
     → @cs2dak/cohort / presentation / react
     → apps/dak-studio（pywebview）
```

### 可复用 packages（全部 MIT，npm）
| 包 | 用途 |
| --- | --- |
| `cs2-demo-format` v3.1.0 | ZIP 数据契约：manifest + match/players/rounds/player-stats/player-economies + kills/damages/blinds/bombs/grenades/clutches + 可选 shots/replay(8Hz)/duels(全 tick 研究窗口)；Zod schemas + JSON Schema + delta 编码整数列 |
| `cs2df` (PyPI 3.1.0) | demoparser2 参考导出器 / 校验器 |
| `@cs2dak/contract` | 契约常量 |
| `@cs2dak/core` | DemoPackage→AnalysisBundle→DemoViewModel |
| `@cs2dak/cohort` | 多 demo 聚合 |
| `@cs2dak/maps` v0.2.0 | worldToRadar / zones / callouts / nav |
| `@cs2dak/presentation` / `react` / `cli` | 展示与命令行 |
| `@rivalhub/rival-rating` | 六账号 RR + PRISM 8 维评分 |

### DAK 引用/依赖的其他项目
demoparser2（运行时）、CS Demo Manager、AWPy（设计与 nav 图）、CS2 2D Demo Viewer、pr1maly（仅研究、非商用）、simpleheat（BSD-2）、CS2-insight-agent（事件抽取溯源，获授权移植）。
注意：`@akiver/cs-demo-analyzer` **未被 DAK 引用**（只有 CS Demo Manager 用了它）。

### PlayerLab 复用地图
- ✅ 采用 `cs2-demo-format v3 ZIP` 作为 canonical 数据契约（**而不是自造私有 schema**）。
- ✅ 复用 `@cs2dak/core` 的 AnalysisBundle 信号与 `duels.json`（全 tick 交战研究窗口）作为反事实的 duel 锚点。
- ✅ 复用 `@cs2dak/maps` 的空间/区域语义（location 用 nav area / 区域语义的基础）。
- ⚠️ 不 fork DAK Studio UI（AGPL）；不复制 mechanics dashboard。
- ❌ **DAK 生态中不存在**：DecisionPoint 检测、PlayerKnownState（可知状态）重建、相似状态检索、反事实比较 —— 全部是 PlayerLab 的绿地。

---

## 2. cs2-demo-format（canonical 数据契约候选）

**仓库**：[github.com/Starfie1d1272/cs2-demo-format](https://github.com/Starfie1d1272/cs2-demo-format) · **npm** `cs2-demo-format` v3.1.0 · **License** MIT

- 实现中立（implementation-neutral）的解析结果 ZIP 契约，**不是解析器**。
- v3 ZIP 内容：`manifest.json` + `match/players/rounds/player-stats/player-economies/kills/damages/blinds/bombs/grenades/clutches/shots/replay/duels`；replay/duels 用 delta 编码整数列流；Zod schemas + 生成 JSON Schema。
- 自带 golden fixture（de_anubis 21 局）与 Python 参考导出器 `cs2df`。
- 已定义 **`clutches.json` 与 `duels.json`**（全 tick 交战窗口，"for reaction-time and duel analysis"）——PlayerLab 反事实的 duel 锚点可从这里长出来。

---

## 3. @akiver/cs-demo-analyzer（Go CLI + Node 包装）

**仓库**：[github.com/akiver/cs-demo-analyzer](https://github.com/akiver/cs-demo-analyzer) · **npm** `@akiver/cs-demo-analyzer`（本机安装 v1.10.7） · **License** MIT · 后端 [demoinfocs-golang](https://github.com/markus-wa/demoinfocs-golang)

- 事件型解析，导出**单个 JSON `Match` 文档**（也支持 CSV / CSDM）；可选 `-positions` 输出逐 tick 位置。
- 数据结构（从源码 struct 核实）：逐 tick PlayerPositions（x/y/z、yaw、pitch、health、armor、money、weapon、flash、ducking/scoping/planting 标志 —— **无 velocity、无原始 buttons**）；kills（distance / thrusmoke / noscope / blinded / trade 标志）；shots（shooter velocity + recoil + aimPunch + viewPunch）；damages（hitgroup + health/armor delta）；rounds（sides/scores/economy type/money）；**内置 1v1–1v5 clutch 检测**、trade kills、KAST/HLTV rating/ADR 统计。
- 无 visibility、无 nav、无 2D 渲染。
- npm 包本体是 Go 二进制包装器（本机验证：二进制需另行下载到 `bin/windows-x64/csda.exe`，包内未附）。

---

## 4. demoparser2（LaihoE/demoparser）— 推荐解析层

**仓库**：[github.com/LaihoE/demoparser](https://github.com/LaihoE/demoparser) · PyPI `demoparser2`（本机安装 **0.42.0**）· npm `@laihoe/demoparser2`（native）/ `demoparser2`（WASM）· **License** MIT · Rust 核心

- 查询式 API：`parse_ticks(fields, players=, ticks=)` / `parse_event(name)` / `parse_grenades()` / `parse_header()` / `parse_player_info()` / `list_game_events()`。
- 逐 tick 字段（已由研究子代理从 README/e2e 测试核实，本机验证部分见 TECHNICAL_SPIKE）：XYZ、velocity、yaw/pitch（view_angle_x/y）、buttons 位掩码 + 12 个具名按钮、shots_fired、is_strafing、stamina、duck/jump 微状态、spotted 掩码、last_place_name、aim punch、usercmd mouse_dx/dy + subtick moves、~60 weapon 实体字段、~60 game-state 字段、16 usercmd 字段、17 round 级聚合。
- 事件：43 个事件名（player_death / player_hurt / weapon_fire / round_start / round_end / bomb_planted / bomb_defused / player_footstep / item_purchase …），事件列表 demo 动态可枚举（`list_game_events`）。
- 性能：约 749 MB/s（12 核基准）——本机单场 252MB demo 全量逐 tick 解析仅约 20 秒级（详见 TECHNICAL_SPIKE）。
- 无 visibility、无 nav（awpy 在其上加 `.nav` + `.tri` LOS）。

---

## 5. AWPy

**仓库**：[pnxenopoulos/awpy](https://github.com/pnxenopoulos/awpy) · **文档**：awpy.readthedocs.io · **License** MIT · v2.0.2 · Python ≥ 3.11（Polars）

- **解析后端**：demoparser2（LaihoE）——v2 架构 `Demo` 对象暴露 Polars 数据帧：header / rounds / bomb / kills / damages（含 dmg_health_real、attacker/victim XYZ）/ shots（weapon、silenced、位置）/ grenades（thrower/tick/XYZ）/ infernos / smokes（start/end ticks）/ footsteps / ticks。
- **navmesh**：`awpy.nav.Nav` 解析 `.nav` 文件；`awpy.plot.nav` 绘图。
- **可见性**：`awpy.visibility` —— VPhysParser（解析 `.vphys` → 三角形）、AABB/BVH、`VisibilityChecker.is_visible(start,end)` 射线 LOS；参考 [AtomicBool/cs2-map-parser](https://github.com/AtomicBool/cs2-map-parser)。注意：这是**上帝视角 LOS**，不是逐玩家可知状态。
- **绘图**：matplotlib 的 plot / heatmap / gif（2D replay 基础）。
- **统计**：adr / trades / impact / kast / rating（HLTV 类）。v2 无 clutch 模块（"CLUTCH framework paper" 在 arXiv/OpenAlex 均无法核实，官方推荐引用的是 Xenopoulos/Freeman/Silva, CHI EA 2022 win-probability 论文，DOI 10.1145/3485447.3512277）。
- **资产下载**：`awpy get maps|navs|tris` 按 patch/build id 下载地图数据。
- 仓库不内置 `.dem`；测试时从 figshare 下载 3 个 demo + 1 个 nav（URL 见研究记录）。
- 新核心 [pnxenopoulos/pbdems2](https://github.com/pnxenopoulos/pbdems2)（MIT，Rust，游戏中立 Source2 原语）是 awpy 的下一代解析层。

---

## 6. CS Demo Manager

**仓库**：[akiver/cs-demo-manager](https://github.com/akiver/cs-demo-manager) · **License** MIT · ~2k stars，非常活跃

- Electron + React（Vite + TS + pnpm）；重活（数据库/文件系统/demo 分析）在 **forked Node 进程的 WebSocket server** 里跑。
- 解析走 companion CLI `cs-demo-analyzer`（Go，demoinfocs-golang 后端），导出 CSV/JSON/CSDM。
- 能力：本地 demo 浏览/分析/组织/重命名、16 种 demo 来源识别（FACEIT/Valve MM/Perfect World/5EPlay/eBot/ESL/Esportal/MatchZy 等）、2D viewer、rank（Valve MM）、HLTV 2.0 rating（估算，HLTV 2.1 未逆向）、VAC tracker、视频导出、SQL 导出。
- PlayerLab 复用：平台/来源识别思路、2D viewer 交互范式（不复制实现）。

---

## 7. 其他相关项目（简述）

| 项目 | 说明 | License |
| --- | --- | --- |
| demoinfocs-golang | Go 生产级解析器，HLTV / noesis.gg / esportal / refrag 等在用 | MIT |
| source2-demo | Rust Source2 replay 解析（Dota 2 / Deadlock / CS2） | — |
| pbdems2 | Rust 游戏中立 Source2 原语（awpy 下一代核心） | MIT |
| saul/demofile | Node.js CS:GO 解析器 | MIT |
| a2x/cs2-analyzer | 名字像 demo 分析，实为**游戏二进制分析**（无关） | MIT |
| subtick-demoviewer / @deademx/engine / counter-strike-2-demo-parser | npm 上的 CS2 demo 解析/viewer（TS 从零实现，可参考不可依赖） | MIT |
| csgostats.gg | 云端 sharecode 解析，闭源（org 404）；仅参考数据模型 | 闭源 |
| ggViz (arXiv:2107.06495) | CHI Play 2022：草图式检索大规模 CS:GO 数据集中**相似游戏状态** | 研究 |
| Valuing Player Actions in CS:GO (arXiv:2011.01324) | 用 win-probability delta 对 70M 事件做**动作价值评估** | 研究 |
| Optimal Team Economic Decisions (arXiv:2109.12990) | 经济决策评估（OSE 指标） | 研究 |

---

## 8. 与 PlayerLab 的重叠 & 避免重复实现清单

### 已存在 → 禁止重复实现
1. **Demo 解析（.dem → events/ticks）**：demoparser2（推荐）/ cs2df+cs2-demo-format / csda / demoinfocs-golang / source2-demo。**采用 demoparser2 作为 ingestion seam**。
2. **解析数据交换契约**：cs2-demo-format v3 ZIP（含 clutches/duels/shots/replay 研究窗口 + Zod 校验）。PlayerLab 应**发射/消费它**，不发明私有 schema。
3. **2D replay + tick 联动可视化**：CSDM 2D viewer、DAK replay + `@cs2dak/maps` world→radar 变换。
4. **几何 LOS 可见性**：awpy VisibilityChecker（VPhys→tri→BVH raycast）；DAK Duel Lab 的 `.tri` TTK/first-shot/counter-strafe/pre-aim。
5. **元数据 / 平台识别 / 文件管理**：CSDM + csda（16 来源、rank、HLTV 2.0）。
6. **基础统计与评分**：awpy.stats（ADR/KAST/Rating/trades）、CSDM HLTV 2.0、cs2-demo-format player-economies。
7. **Clutch/duel 事件抽取（事件级）**：cs2-demo-format `clutches.json`、`@cs2dak/core` —— 检测交战不新奇，**解读**才是 PlayerLab 的事。

### 现有生态没有 → PlayerLab 的差异化（护城河）
1. **DecisionPoint 检测**：没有工具建模「这是一个面临真实选择的时刻」（定位/道具/交火时机/转点备选）。DAK 的 labs 是**反应式**的（发生了什么），awpy 是统计/事件导向。没有 decision-point 分类法、没有「moment」数据类型、cs2-demo-format 里也没有 DP schema。
2. **PlayerKnownState（可知状态）重建**：所有解析器输出上帝视角；awpy LOS 是 omniscient。没有工具重建「玩家 X 在 tick T 实际可能知道什么」（FOV 视野、战争迷雾、脚步声/声音线索、last-seen、道具/经济感知）。
3. **反事实动作比较**：没有工具生成「如果你 1 秒后再 peek / 架住 / 丢道具 / 转点会怎样」并评估。最近的研究是 win-probability-delta 动作价值（arXiv:2011.01324），非产品化工具。
4. **相似状态检索**：ggViz 是研究原型（ESTA 数据集上的草图式检索），无维护中的 CS2 开源工具。
5. **决策智能的本地优先产品化**：DAK Studio 最近邻，但止步于评分/mechanics，且 Studio 是 AGPL。

---

## 9. PlayerLab 差异化总结

> **DAK Studio / AWPy / CSDM 回答「What happened? How did I perform?」；PlayerLab 回答「What did I choose? What alternatives existed? How did similar historical choices perform? Was it a decision or execution problem?」**

- 上层差异：DecisionPoint 检测 + PlayerKnownState 重建 + 相似状态检索 + 反事实比较 + 证据强度 —— 生态空白。
- 下层复用：demoparser2 解析 → cs2-demo-format v3 契约 → @cs2dak/core 信号 + awpy LOS/nav 原语 → PlayerLab Core。
- 边界：PlayerLab 是 decision intelligence layer；DAK packages 是 analysis substrate。不重复实现 mechanics dashboard、2D replay、demo 管理、统计评分。
- License 风险控制：只依赖 MIT 生态侧；不 fork DAK Studio（AGPL）；pr1maly（非商用）仅参考。
