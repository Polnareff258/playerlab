# PlayerLab V1.2.1 — Context Grounding + Optional Model Intelligence

本地优先的 CS2 Demo 分析项目。核心目标：

> 从 CS2 Demo 中自动识别关键决策点，区分「决策问题」和「执行问题」，并通过历史相似状态检索回答：
> **「如果我当时做了另一个选择，历史上类似局面通常会怎样？」**

V1 优先证明一条链真实、可靠、可追溯地工作：

```
DecisionPoint → GameState → Similar State Retrieval → Counterfactual Comparison
```

V1.2.1 升级：**Context Grounding**（KnownState 序列 + InformationStrength/Direction
+ Tradeability + 保守责任归因 + Review Quota）+ **Optional Model Intelligence**
（GameModelProvider / Null / CSNetProvider，CS-NET 作为可选后端）。

## 与 DAK Studio 的关系

- DAK Studio / DAK packages 是 **analysis substrate**（发生了什么、表现如何）；
- PlayerLab 是 **decision intelligence layer**（我选了哪个选择、还有哪些备选、历史上相似选择的实际结果如何、问题出在决策还是执行）。

PlayerLab 不通过重复实现 mechanics dashboard 制造差异，只消费现有解析与分析能力。

## 文档

| 文档 | 内容 | 状态 |
| --- | --- | --- |
| [docs/EXISTING_PROJECTS.md](docs/EXISTING_PROJECTS.md) | 阶段 1：现有项目研究（DAK Studio / cs-demo-analyzer / demoparser2 / AWPy / CS Demo Manager 等） | ✅ |
| [docs/TECHNICAL_SPIKE.md](docs/TECHNICAL_SPIKE.md) | 阶段 2：真实 Demo 数据可用性验证（252MB 真实 CS2 demo 实测） | ✅ |
| [docs/CAPABILITY_MATRIX.md](docs/CAPABILITY_MATRIX.md) | 阶段 2：能力矩阵（数据 × 来源 × 频率 × 精度） | ✅ |
| [docs/COUNTERFACTUAL_DESIGN.md](docs/COUNTERFACTUAL_DESIGN.md) | 阶段 3：反事实可行性设计（14 问） | ✅ |
| [docs/BACKTEST_DESIGN.md](docs/BACKTEST_DESIGN.md) | 阶段 4：反事实回测与验证设计 | ✅ |
| [docs/DESIGN.md](docs/DESIGN.md) | 阶段 5：架构设计（模块边界 / 存储 / 管线 / LLM 边界 / token 预算） | ✅ |
| [docs/MVP_PLAN.md](docs/MVP_PLAN.md) | 阶段 5：MVP 实现计划（M0–M8） | ✅ |
| [docs/ROADMAP.md](docs/ROADMAP.md) | V1.5 / V2 / V2+ / V3 路线（不实现） | ✅ |

### V1.1 — Evidence-Driven Improvement Loop（设计阶段）

| 文档 | 内容 | 状态 |
| --- | --- | --- |
| [docs/V1_1_AUDIT.md](docs/V1_1_AUDIT.md) | Phase 1：仓库审计（V1 现状 / 复用组件 / 缺口） | ✅ |
| [docs/REUSE_MATRIX.md](docs/REUSE_MATRIX.md) | Phase 2：外部能力审计（Freezetime / structural-analytics / CounterStrafe / AWPy / CS Demo Manager / demoparser2） | ✅ |
| [docs/IMPROVEMENT_MODEL.md](docs/IMPROVEMENT_MODEL.md) | Phase 3：改进模型（Decision Hierarchy / Root Cause / Pattern / Bottleneck / TrainingTarget / Validation） | ✅ |
| [docs/MACRO_DECISION_DESIGN.md](docs/MACRO_DECISION_DESIGN.md) | Phase 4：宏观决策设计（信息纪律 / 旋转 / 优势 / 间距 / 区域控制 / 时机） | ✅ |
| [docs/V1_1_MVP.md](docs/V1_1_MVP.md) | Phase 5：MVP 选型（8 模式 + 支撑层 + 验证路径） | ✅ |
| [docs/IMPLEMENTATION_PLAN.md](docs/IMPLEMENTATION_PLAN.md) | Phase 6：实现计划（模块/文件/Schema/迁移/测试/UI/Token 边界） | ✅ |

**V1.1 定位**：不是加更多复盘指标，而是闭环 PLAY → OBSERVE → DIAGNOSE → TRAINING TARGET → VALIDATE —— 一次只改 1–2 个行为，后续 Demo 自动验证行为是否真正改善。Phase 6 完成后**暂停等待确认**。

### V1.1-alpha — 已实现（Improvement Loop + Human Annotation Loop）

3 个 pattern 检测器（Immediate Same-Angle Re-peek / Move-and-Shoot+Couter-Strafe / Advantage Overaggression）+ TrainingTarget（Active Focus ≤2、三通道验证）+ 人工标注闭环（HumanAnnotation / PreferenceAnnotation / ReviewQueue / JSONL 导出 / 统计）+ 黄金样本。详见 [docs/ALPHA_RESULTS.md](docs/ALPHA_RESULTS.md)。

```powershell
python3 -m playerlab.cli alpha "path\demo.dem"        # 全管线（ingest + 3 pattern + 目标 + review）
python3 -m playerlab.cli patterns | focus | targets | review
python3 -m playerlab.cli target-validate
python3 -m playerlab.cli annotations stats | annotations export --out ..\backtest\ann.jsonl
python3 -m playerlab.cli api --port 8125               # UI：首页 = CURRENT FOCUS；Review 卡可标注
```

### V1.2 — Context & Intent Spike（已实现）

在 alpha 之上增加**上下文理解层**：TemporalContext（4s 窗口）、CommitmentState（11 态，事件≠承诺）、ActionFeasibility（6 态规则引擎）、SituationalRole（15 态动态职责）、Intent Rule Baseline（ROTATE/SOFT_ROTATE/REPOSITION/HOLD…+概率+AMBIGUOUS）、ResponsibilityAttribution（8 类，commitment≠免责、outcome 独立）。详见 [docs/V1_2_RESULTS.md](docs/V1_2_RESULTS.md)。

### V1.2.1 — Context Grounding + CS-NET Integration Spike（已实现）

在 V1.2 之上增加：

1. **KnownState Grounding**：PlayerKnownState 真正接入 TemporalContext 与 IntentSample（540 样本全覆盖）——known_enemy_count/zones/directions、time_since_*、bomb_known/zone/confidence、teammate_contact、objective_information；IntentSample v2 含 `known_state_sequence / information_sequence / motion_features / structural_features / known_state_features / information_features / round_id / episode_id`（split metadata，防泄漏）。
2. **InformationStrength / InformationDirection**（`information.py`，LLM-free）：视觉/伤害/bomb/公共 feed/声音 + 时间衰减 → NONE..CONFIRMED；方向 A/B/Mid/Unknown。**Intent 学「为什么」**：同轨迹不同信息 → ROTATE vs REPOSITION 不同判定（spec §74-A 测试覆盖）。
3. **Tradeability**（`tradeability.py`）：direct_distance / nav_distance / direct_los / response_time / lane / cover / commitment 约束 → HIGH..UNKNOWN 分类（内部保留 score）；无 LOS/nav 几何时保守封顶 MEDIUM，不伪造精度（spec §8）。
4. **Responsibility 保守校准**：四门 gate（Evidence/Feasible/Alternative/Causal）+ tradeability 参与；SELF_DECISION 76.9% → 17.7%（真实 demo，抽样人工审查 96% 可辩护）。详见 [docs/RESPONSIBILITY_CALIBRATION.md](docs/RESPONSIBILITY_CALIBRATION.md)。
5. **Review Quota**：intent 3 / responsibility 2 / pattern 2 / other 1（可配置）+ `review_focus`（balanced/intent/responsibility/pattern/other）+ 新优先级（top-close、responsibility conflict、low-confidence tradeability）。
6. **Optional Model Intelligence**（`model_provider.py`）：`GameModelProvider` 接口 + `NullGameModelProvider`（默认，无 CS-NET 时完整运行）+ `CSNetProvider`（CS-NET 适配器，win_rate 真实推理已通过）。

    - **CS-NET 是 optional**（spec §60）：不安装不影响任何 PlayerLab 功能；安装见下。
    - 依赖隔离：`requirements-csnet.txt`（torch 等不进 PlayerLab core）。
    - 权重不入 git（`external/cs-net/` 已 gitignore）；版本锁定 `external/cs-net/VERSION.lock`。
    - 详见 [docs/CSNET_INTEGRATION_REPORT.md](docs/CSNET_INTEGRATION_REPORT.md) 与 [docs/CSNET_FIELD_MAPPING.md](docs/CSNET_FIELD_MAPPING.md)。

```powershell
python3 -m playerlab.cli context-eval                 # intent/role/commitment/responsibility agreement
python3 -m playerlab.cli intent-dataset --out ..\backtest\intent.jsonl    # tiny-model 数据集（含 KnownState/信息特征）
python3 -m playerlab.cli responsibility-dataset --out ..\backtest\resp.jsonl
python3 -m playerlab.cli model-intelligence           # Model Intelligence 状态（默认 Null）
python3 -m playerlab.cli model-intelligence --provider csnet   # 已装 CS-NET 时显示 CONNECTED + tasks
# Review 页新增 intent 标注（ROTATE/SOFT_ROTATE/…）与 Preference A/B 候选；Focus 页新增 Model Intelligence 卡片
```

**CS-NET 可选安装**（spec §61/§62，失败不影响核心）：

```powershell
cd playerlab
git clone https://github.com/Gary2005/cs-net.git external/cs-net   # 或解压 zipball；commit 见 VERSION.lock
python3 -m pip install torch --index-url https://download.pytorch.org/whl/cpu   # CPU；或 cu126 换 GPU
python3 -m pip install -r requirements-csnet.txt     # 可选依赖（torch 已装可跳过）
# 权重随仓库分发（cs-net-models/*.pt，各 ~36MB）；或 python -m scripts.download_model（HF 镜像）
# 验证：
python3 -m playerlab.cli model-intelligence --provider csnet
# 期望：status=ready, tasks=["win_rate"]
```

## 阶段状态

- [x] 阶段 1：现有项目研究 → EXISTING_PROJECTS.md
- [x] 阶段 2：Technical Spike（真实 CS2 Demo）→ TECHNICAL_SPIKE.md + CAPABILITY_MATRIX.md
- [x] 阶段 3：Counterfactual Feasibility → COUNTERFACTUAL_DESIGN.md
- [x] 阶段 4：Backtest Design → BACKTEST_DESIGN.md
- [x] 阶段 5：Architecture → DESIGN.md + MVP_PLAN.md
- [x] 阶段 6（已确认）：MVP 实现 M0–M8 → `core/playerlab/`（ingest/state/decision/features/counterfactual/backtest/api/cli）+ `ui/` + `tests/`
- [x] 实现期验证：真实 demo 全链路走查通过（见下）
- [ ] 人工验收：多场 demo 回测（LOMO 需 ≥2 场才有信号）与 Retrieval QA 标注

## 实现期验证结果（252MB 真实 CS2 demo，de_dust2，18 局）

- 全流程 38–50s/场：ingest → 60 个 DecisionPoint（PEEK 28 / HOLD 22 / DISENGAGE 6 / RE_PEEK 4）→ SQLite 入库
- 反事实全链路跑通：RE_PEEK 查询 → HOLD n=8 / PEEK n=8 / DISENGAGE n=2 → Wilson CI + 证据强度 → COMPARISON_AVAILABLE；CI 重叠时诚实返回 NO_RELIABLE_DIFFERENCE
- 证据可追溯：DP 链到精确 tick/事件（如 t39512 吃刀 40 → t39516 glock 反杀 2.9m）
- 纪律生效：单场跨场检索 0 样本 → INSUFFICIENT_EVIDENCE（不编造）；backtest/ablation 在 ≥2 场时出校准/Brier/消融信号（单场诚实报告 0 预测）
- 单元测试 10/10；复现性：重跑 DP 数量/分布/哈希完全一致
- 字段勘误：`CCSPlayerPawn.origin`（陈旧出生点）→ `CBodyComponentBaseAnimGraph.m_vecX/Y/Z`；`m_vecBaseVelocity`（恒 0）→ 位置差分推导；`m_iTeamNum` 逐 tick 真实阵营

## 实测数据（spike 摘要）

- 解析器：demoparser2 0.42.0（MIT，Rust 核心）· 252MB 真实 CS2 Valve 官方 demo（de_dust2，18 局）
- 全字段实测可用：XYZ / velocity / yaw / pitch / buttons / shots / damage / weapon / grenades / 点位名 / 脚步声 / 经济 / bomb / kill feed
- 全量解析 <60s/场；visibility/nav 需复用 awpy LOS 原语与地图资产（生态已有）

## 运行（MVP 实现）

```powershell
cd playerlab\core
python3 -m playerlab.cli ingest "C:\path\to\demo.dem"   # 解析 + 检测 DP + 入库
python3 -m playerlab.cli batch "D:\demos"               # 批量分析目录（递归，幂等跳过已入库）
python3 -m playerlab.cli batch "D:\demos" --dry-run     # 只列出将分析的 demo
python3 -m playerlab.cli batch "D:\demos" --force --report ..\backtest\batch.json  # 强制重分析+报告
python3 -m playerlab.cli list                            # 匹配列表
python3 -m playerlab.cli dps <demo_id>                   # DP 列表
python3 -m playerlab.cli dp <dp_id>                      # DP 详情（JSON）
python3 -m playerlab.cli whatif <dp_id>                  # 反事实对比（JSON）
python3 -m playerlab.cli coverage                        # 相似状态覆盖报告
python3 -m playerlab.cli backtest                        # 留一比赛校准/Brier
python3 -m playerlab.cli qa --out ..\backtest\qa.json   # 检索 QA 批次导出
python3 -m playerlab.cli ablation                        # 特征消融
python3 -m playerlab.cli api --port 8123                 # 本地 UI + API
# 浏览器打开 http://127.0.0.1:8123
```

### 批量分析模块（`core/playerlab/batch.py`）

独立子命令 `batch`，用于一次性消化整个 demo 目录：
- **发现**：目录递归收集 `*.dem`（`--no-recursive` 关递归；也可直接传文件）
- **幂等**：按路径哈希跳过已入库 demo（`--force` 强制重分析）
- **失败隔离**：单场解析失败（含底层解析器 panic）只记入失败清单，不中断批次
- **报告**：`--report <path>` 输出 JSON 汇总（ingested/skipped/failed、DP 数、动作分布、失败明细）；控制台实时进度
- **安全操作**：`--dry-run` 只列出将分析的 demo 与跳过原因

依赖：Python 3.11+、`demoparser2==0.42.0`（+ pandas）。其余全部 stdlib（sqlite3/http.server）。
数据默认落在 `playerlab/data/`（SQLite + analyses/ 缓存）。测试：`python3 tests\test_core.py`（10 项全部通过）。

## 隐私与 GitHub

- **demo 数据绝不入库**：`data/`（SQLite + canonical + tick 缓存）、`backtest/`（QA 批次/截图）、探针输出均含真实玩家 steamid/昵称与本地路径，已在 `.gitignore` 中排除；提交前对文档样例做了匿名化（PlayerA/B）并移除了本机路径。
- 仓库：https://github.com/Polnareff258/playerlab （Private）
- 本机推送约定（沙箱环境）：TLS 后端用 openssl（repo 级已配置）。在普通终端先运行一次 `gh auth setup-git`，之后 `git push` 即可；若仍报认证错误，用一次性 token URL 推送（token 不写入 `.git/config`）：
  ```powershell
  $url = "https://x-access-token:$((gh auth token))@github.com/Polnareff258/playerlab.git"
  git push $url master:master
  ```
