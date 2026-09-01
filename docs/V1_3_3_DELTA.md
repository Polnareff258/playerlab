# V1_3_3_DELTA.md — Phase A：V1.3.2 → V1.3.3 增量审计

> 审计对象：`calibration.py / moments.py / training.py / db.py / api.py /
> ui/index.html / data/playerlab.sqlite`（HEAD `58848b3`，V1.3.2）。
> 目的：确认 V1.3.3「Validation Hardening, Human Ground Truth & Geometry A/B」
> 的复用面与缺口（spec PART A-W）。

---

## 1. 现状基线 + 污染实锤

### 1.1 模拟 review 污染（PART A/C 核心问题）

DB 审计（`spike/audit_v133.py`）确认：V1.3.2 的 `calib_demo` 模拟 review 已
**写入 production `calibration_samples` 表**：

| detector | reviewed | YES | NO | 当前 CalibrationState |
| --- | --- | --- | --- | --- |
| PREAIM_ERROR | 25 | 20 | 5 | **CALIBRATED**（0.80 precision）← 模拟污染 |
| MOVING_SHOT | 25 | 15 | 10 | **EXPERIMENTAL**（0.60）← 模拟污染 |
| 其余 5 个 | 0 | - | - | UNCALIBRATED |

**风险**：模拟标签在状态机层面形成 CALIBRATED，虽然文档标注
`GROUND_TRUTH_PENDING_HUMAN_REVIEW`，但概念上不安全（PART A preamble）——
模拟数据可解锁 TrainingTarget / 提升 ReviewMoment 权重 / 进入 precision 统计。

### 1.2 可复用面

| 模块 | 现状（V1.3.2） | V1.3.3 复用 |
| --- | --- | --- |
| calibration.py | CalibrationSample schema、分层采样、calibration_stats（precision/buckets/state）、threshold_sensitivity | ★★★ 升级：label_source、双状态、recompute、negative control、metrics v2 |
| moments.py | ReviewMoment ranking（weighted + why_selected + cal 门控） | ★★ Gate v2：只认 eligible calibration |
| training.py | TrainingTarget calibration gate（UNCALIBRATED→PAUSED） | ★★ Gate v2：SIMULATED 永不 unpause |
| db.py | v7：calibration_samples（单 human_label 字段）、review_moments、player_profiles | ★★ v8：label_source 列 + 新表 calibration_annotations（一对多）+ experiment_runs |
| api.py | player-scoped endpoints、calibration review POST | ★★ label_source 传递、calibration session、A/B endpoints |
| ui/index.html | Calibration Lab（单场景 Yes/No/Unsure） | ★★★ Calibration Session（连续审核 + 快捷键 + 双状态显示） |
| geometry.py | GeometryProvider + Null + AwpyGeometryProvider（lazy，无资产） | ★★ A/B 实验载体；assets setup 脚本 + metadata |
| episode.py | DecisionEpisode 全字段 | ★★★ A/B 对齐载体（episode_id） |

## 2. V1.3.3 新增（spec PART A-W 落点）

| 能力 | 模块 | 对应 spec |
| --- | --- | --- |
| LabelSource（HUMAN/SIMULATED/IMPORTED_EXPERT/CONSENSUS，MODEL_ASSISTED 预留） | calibration.py + db v8 | PART A §1-§5 |
| PipelineValidationState（NOT_TESTED/PIPELINE_VALIDATED/PIPELINE_FAILED） | calibration.py | PART B §6 |
| CalibrationState 只由 eligible labels 驱动（默认 HUMAN） | calibration.py | PART B §7-§8 |
| 生产数据 migration（50 条模拟 review 标记 label_source=SIMULATED） | db v8 migration | PART C §10 |
| recompute-calibration（只读 eligible labels） | calibration.py + cli | PART C |
| Human Calibration Queue（5-10/场）+ 采样优先级（uncertainty/threshold/coverage/deficit）+ detector coverage balancing | calibration.py | PART D §11-§14 |
| PREAIM audit：measurement（FIRST_VISIBILITY_CROSSHAIR_OFFSET）vs interpretation（PREAIM_ERROR）分离 + 9 类 human label | duel.py/calibration.py/docs | PART E §15-§17 |
| MOVING_SHOT audit：SHOT_WHILE_MOVING（事实）vs MOVEMENT_HURT_ACCURACY（评价）分离 + weapon-aware threshold 分析 | duel.py/calibration.py | PART F §18-§20 |
| DRY_PEEK audit：行为 vs 评价 + 4 类 human label | engagement.py/calibration.py | PART G §21-§22 |
| Geometry assets（data/maps gitignore + MANUAL_ASSET_SETUP.md + 资产 metadata 表） | scripts + docs | PART H §23-§24 |
| Geometry A/B 实验（OFF/ON 同批 demo + episode-level diff + experiment_id/config_hash/git_commit 复现性） | `ab_experiment.py`（新） | PART I/S §25-§29 |
| Human+Geometry joint validation（OFF vs ON vs human label 一致性） | ab_experiment.py | PART J §30 |
| Calibration Metrics v2（human_reviewed/confirmed/rate 与 simulated_reviewed 分离，永不合并）+ negative control（10-20% quota） | calibration.py | PART K §31-§32 |
| CalibrationAnnotation 一对多（annotation_id/sample_id/annotator/label_source/label/confidence/reason） | db v8 + calibration.py | PART L §33-§34 |
| ConsensusResolver 接口（默认 SingleHumanResolver） | calibration.py | PART M |
| TrainingTarget Gate v2（只认 eligible；SIMULATED→PAUSED 即使 precision 0.95） | training.py | PART N |
| ReviewMoment Gate v2（calibration reliability 只来自 eligible） | moments.py | PART O |
| Debug 可见性（Pipeline validation vs Human calibration vs Simulated 分开显示） | ui | PART P |
| Calibration Session UX（连续审核 + Next/Prev/Skip/Unsure + 快捷键 1/2/3/S） | ui | PART Q |
| Annotation Export（JSONL/Parquet + label_source + sample features + geometry mode） | calibration.py + cli | PART R |
| 复现性元数据（experiment_id/config_hash/git_commit/demo_hash） | ab_experiment.py | PART S |

## 3. 关键设计决策（审计结论）

1. **不删除历史模拟数据**（PART C）：50 条标记 `label_source=SIMULATED` + recompute → PREAIM 回到 UNCALIBRATED（human reviewed=0），PipelineValidationState=PIPELINE_VALIDATED。
2. **双状态展示**（PART B §9）：UI 显示 "Pipeline: Validated" + "Ground Truth: Pending Human Review"，不显示 CALIBRATED 直到真实 HUMAN 标签足够。
3. **CalibrationAnnotation 一对多**（PART L）：新增表存每次 annotation 独立行；CalibrationSample 只存 sample 元数据 + 聚合状态，不再被单 label 覆盖。
4. **A/B 只改 GeometryProvider**（PART I）：同一 demo 同一 detector version 两次 run（OFF=Null / ON=Awpy 或预计算几何缓存），episode_id 对齐 diff；无资产 → `GEOMETRY_AB_PENDING_ASSETS` 诚实输出（PART V）。
5. **negative control 占 10-20% quota**（PART K §32）：为未来 false-negative/recall 估计铺路；当前只报 precision/confirmation（positive-only 限制 §31）。
6. **PREAIM/MOVING 测量-解释分离**（PART E/F）：internal measurement 明确命名，PREAIM_ERROR/MOVEMENT_HURT_ACCURACY 为 interpretation；human label 分类已备。

## 4. 明确不做（PART W + 阶段总原则）

- 不新增 Decision Family / detector / 综合评分 / Pro 模块 / Tiny Transformer / 大型模型。
- 不开发 crowdsourcing（CONSENSUS 只定义接口）。
- 不实现 IMPORTED_EXPERT 导入系统（schema 预留）。
- 无真人标注不伪造：输出 `GROUND_TRUTH_PENDING_HUMAN_REVIEW`。

## 5. 验收判定（Definition of Done 对照）

| Scenario | 计划 |
| --- | --- |
| A 模拟 1000 标签 → Pipeline=VALIDATED + Calibration=UNCALIBRATED | 双状态隔离 + Test 1 |
| B 真人标注 → 统计页分显 Human reviews vs Simulated reviews，真实 precision 只用 human | Metrics v2 + recompute |
| C 真人样本不足 → TrainingTarget PAUSED | Gate v2 + Test 2 |
| D 同一 Demo OFF/ON 逐 episode 可比较 | A/B 实验 + Test 7 |
| E Geometry ON 增 confidence 但 human agreement 未增 → NO_VALIDATED_ACCURACY_GAIN | Joint validation §30 |
| F PREAIM FP 来自 target-switch/unexpected → 展示原因分类 | FP taxonomy + DETECTOR_VALIDITY_REPORT |
| G 连续快速审核（Calibration Session） | Session UX + 快捷键 |
