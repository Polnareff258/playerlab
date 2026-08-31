# CSNET_INTEGRATION_REPORT.md — CS-NET Integration Spike 实测报告（spec §58）

> 日期：2026-08-31 · 环境：Windows 11，Python 3.13.14（WindowsApps），CPU-only
> 目标：回答 spec §58 的 17 个问题，给出 Phase G/H 实测结论与推荐集成路径。

---

## 1. Clone / 版本锁定（spec §24/§25）

| 项 | 值 |
| --- | --- |
| 仓库 | https://github.com/Gary2005/cs-net.git |
| **CS_NET_COMMIT** | `e15acc3fda3de21f25fe12a5ca31722381f40162`（main，2026-08-31 抓取） |
| 获取方式 | GitHub zipball（api.github.com；git clone 在本机网络被 schannel 阻断） |
| 落盘位置 | `external/cs-net/`（**已 gitignore，不入 PlayerLab git**） |
| 版本锁定 | `external/cs-net/VERSION.lock`（CS_NET_REPO / COMMIT / MODEL_VERSION / HEADS） |
| License | **MIT**（repo 根 LICENSE 核实） |
| 模型权重 | 5 个 head 预训练权重**随仓库分发**（各 ~36MB .pt），位于 `cs-net-models/{alive,duel,nxt_kill,nxt_death,win_rate}/` |
| 权重入库 | 否 —— `external/cs-net/` 整体 gitignore（spec §25）；HuggingFace 镜像 `gary2oos/CS-Net-V3` 记录于 VERSION.lock |

## 2. 安装（spec §61 依赖隔离）

- PlayerLab core **零新增依赖**（`requirements-csnet.txt` 独立，torch/CS-NET 全家桶不进入核心 requirements）。
- 本机安装（Python 3.13 + CPU torch 2.9.1）：torch、numpy、PyYAML、python-snappy（0.7.3 + cramjam 后端，wheel 手动解压到 `external/cs-net/.pylibs/` 因沙箱 Temp 限制）、webdataset、Flask、huggingface_hub、tqdm、zstandard。
- **install success: YES**（CPU 栈）；CUDA 未测（无 GPU 环境）。
- python-snappy 是 CS-NET `state_extract.py` 输出压缩用的可选库 —— 缺失时模型推理仍可跑（只影响其 JSON 压缩分支），已在适配器 `.pylibs` 兜底。

## 3. 模型下载

- **model download success: YES（零额外下载）** —— 权重随仓库分发，5/5 head 完整。
- HuggingFace `download_model.py` 脚本存在但未运行（仓库内权重已够用，避免重复 180MB 下载）。

## 4. 测试推理（spec §26）

真实 Demo：`C:\Users\20646\Downloads\003777377368365072904_0970464162.dem`（**264.8MB，de_dust2，18 局，5242 ticks @4Hz**）

- **test inference success: YES**
- win_rate 输出示例：round 1 tick0 `ct_win_rate=0.509`，同轮末段 `0.982`（曲线单调上升，语义正确）
- 5 head 全部加载成功（win/alive/duel/nxt_kill/nxt_death，各 9.5M 参数）
- 温度校准（spec §27）：win_rate T=1.061、alive T=1.193、duel T=1.147 —— 校准元数据随 ModelEvidence 返回

## 5. Tasks 支持（spec §27）

| head | task id | 本阶段实测 |
| --- | --- | --- |
| win_rate | win_rate | ✅ 真实推理 + ModelEvidence |
| alive | survival（5s 存活） | ✅ 推理跑通（benchmark 3 head）；适配器暂未暴露（spec §70 不强行全支持） |
| duel | duel（5×5 矩阵） | ✅ 推理跑通；适配器暂未暴露 |
| nxt_kill | next_kill（10+1 分布） | ✅ 加载跑通（官方多 head 管线） |
| nxt_death | next_death（10+1 分布） | ✅ 加载跑通 |

## 6. 性能 Benchmark（spec §41，CPU-only）

| 指标 | 值 |
| --- | --- |
| demo size | 264.8 MB |
| parse time（CS-NET 独立解析） | 7.5s |
| state extraction time | 108.9s（5242 states；**本阶段最大成本**） |
| model load time（3 heads） | 0.29s（~0.1s/head，CPU） |
| CPU inference | **15.1ms/tick（3 heads 并行 batch=128）**；单 head win_rate ~6ms/tick |
| GPU inference | 未测（无 CUDA）；估计 <2ms/tick（模型仅 9.5M 参数） |
| RAM | 模型加载后 993MB → 推理后 1208MB（+215MB，含 state 缓存） |
| VRAM | 0（CPU-only） |

**解读**：推理本身很快（CPU 15ms/tick，一场 18 局 ~79s）；瓶颈是 **state extraction（109s）与双解析**（spec §39）。整场 CS-NET 全流程 ~200s（parse 8 + extract 109 + infer 79），PlayerLab 侧全管线 ~64s。

## 7. 加载策略（spec §28）

- `CSNetProvider` **按 head 惰性加载**（`_head_model()` 首次调用才 load，`_loaded` 缓存），已实测：只加载 win_rate 时内存 +0.3s/36MB。
- 官方 `get_round_win_rate` 的 `resolve_head_dirs` 也支持只给 win_rate 目录（optional heads 缺失仅 warn）。
- **结论：可以只 load win model；load requested heads lazily 可行**（本适配器即如此）。

## 8. 解析复用（spec §39/§40）

- **现状：双解析**。CS-NET 用自己的 `DemoParser + extract_states_by_group` 独立重解析；PlayerLab 解析一次（~40s）+ CS-NET 再解析一次（~116s）——成本已记录。
- **CS-NET State Cache**：官方管线每场输出 round JSON（win_rate/alive/duel 逐 tick 曲线），PlayerLab 侧 `CSNetProvider` 设计为「demo → csnet JSON cache → 按 tick 查询」；缓存目录 `data/csnet_states/`（gitignore 覆盖），避免 UI 每次请求重跑。
- **消除双解析路径**（CSNET_FIELD_MAPPING.md §4）：PlayerLab ingest 扩展 wanted_props（pitch/armor/helmet/defuser/bomb 实体坐标/投掷物轨迹）后，`canonical frame → csnet state` adapter 可单解析复用；字段重合度 direct 40% / conversion 30% / missing 30%。

## 9. 适配器（spec §31-§33）

- `GameModelProvider` 接口 + `NullGameModelProvider`（默认，spec §30）+ `CSNetProvider` 已实现并测试（48/48 全绿，含 csnet adapter contract 测试）。
- **Phase H 验收**：`CSNetProvider.predict_win_probability(state)` 返回真实 `ModelEvidence`：
  ```json
  {"provider":"csnet","model_version":"cs-net-v3","task":"win_rate",
   "prediction":0.5902,"calibrated":true,
   "calibration_metadata":{"temperature":1.0613},
   "state_scope":"GROUND_TRUTH_STATE","evidence_type":"state_value"}
  ```
- **state_scope=GROUND_TRUTH_STATE**（spec §33 强制：CS-NET 消费全量 10 人场上状态）。
- **Hindsight Boundary**（spec §34）：prediction 只作为 Decision Review 的 Supporting Evidence；不写入 PlayerKnownState；delta_value<0 不自动归责（spec §36 测试覆盖）。
- 失败隔离（spec §62）：权重缺失 / 模型目录错误 → `evidence_type=unavailable` 优雅降级，不崩溃；`get_provider("csnet")` 工厂在 import 失败时回退 Null。

## 10. 已知风险

1. **Python 版本漂移**：CS-NET README 标注 Python 3.8+，本机 3.13 实测可跑（torch 2.9.1 CPU），但 webdataset/wandb 等可选依赖在 3.13 有 wheel 风险。
2. **python-snappy 安装**：Windows 需 cramjam 后端 + 手动解包（沙箱限制所致）；生产建议用官方 wheel 或 Linux。
3. **state extraction 耗时**：109s/场是集成后主要延迟源；UI 必须走 cache。
4. **字段缺失**：PlayerLab tick 未采集 pitch/armor/defuser/bomb 实体/投掷物 —— CS-NET 输入目前必须走它的解析器，双解析不可避免（短期）。
5. **网络依赖**：首次 clone/权重获取需 GitHub 可达（本机 schannel 问题已绕过）；运行时无网络依赖。
6. **commit 漂移**：CS-NET main 会更新；VERSION.lock 已 pin，升级需显式操作。

## 11. License 说明

- CS-NET = **MIT**（含权重随仓库 MIT 分发）；PlayerLab 复用其模型推理不构成复制核心代码（适配器仅 import）。
- PlayerLab 集成路径：**Reuse through Provider**（spec §75），不 fork、不重训、不复制其代码进 PlayerLab 核心。
- 2D viewer 上游 sparkoo/csgo-2d-demo-viewer（MIT）仅存在于 CS-NET 自己的 Web App，PlayerLab 不嵌入（spec §44）。

## 12. 推荐集成路径

```
短期（本阶段已交付）:
  PlayerLab core ──GameModelProvider──> Null（默认）| CSNetProvider（可选）
  CSNetProvider: canonical/raw state -> build_batch -> win_rate head
                 -> ModelEvidence (GROUND_TRUTH_STATE) -> Decision Review
  双解析接受 + data/csnet_states/ JSON 缓存（spec §40）

中期（后续阶段）:
  PlayerLab ingest 扩展 wanted_props 补齐 missing 字段
  -> 单解析 adapter（canonical frame -> csnet state 全表转换）
  -> 移除 CS-NET DemoParser 路径，仅保留模型推理
```

**结论**：CS-NET 作为 Optional Model Intelligence Backend **可行且已验证**（真实 head 推理 + ModelEvidence 全链路）；PlayerLab core 无 CS-NET 时完整运行（Null 兜底 + 48 测试全绿）。
