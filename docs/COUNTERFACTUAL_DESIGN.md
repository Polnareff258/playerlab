# COUNTERFACTUAL_DESIGN.md — 阶段 3：反事实可行性设计

> PlayerLab V1 决策文档 · 本文件回答 spec 第 25 节的 14 个研究问题，并把答案落成 V1 可实现的设计决策。
> 核心立场：**反事实系统只做「历史相似局面下不同动作的实际结果分布」的统计描述与检索，绝不做「你应该那样做」的因果断言；证据不足一律返回 INSUFFICIENT_EVIDENCE。**

---

## 0. 设计基调（先立规矩）

1. **Decision 层只用 PlayerKnownState**（§6），GroundTruthState 只用于 outcome 评估 / replay / debug。
2. **相似性检索程序化**：Hard Filters（必须匹配）+ Soft Similarity（加权评分），权重可配置、可回测、可 ablation（§8-9）。
3. **统计先行**：样本阈值、Wilson 置信区间、效果量门槛全部确定性计算；LLM 只做最终用户面解释（§20）。
4. **每一条反事实结论可追溯**：demo → match → round → tick 范围（§13）。
5. 反事实是**描述性**的（"历史相似状态的实际结果"），不是因果的（"你 hold 就会赢"）。

---

## 1. DecisionPoint 如何可靠检测？

### 核心思想
不把每个 movement change 当 DecisionPoint。DP 必须是「存在 ≥2 个可执行动作族」的时刻，并且有证据支持。

### V1 检测管线（确定性规则状态机，非 ML）
```
逐 tick 流
 ├─ 事件层：player_hurt / weapon_fire / player_death / player_footstep / grenade_*
 ├─ 状态层：位置 / velocity / yaw-pitch / buttons / hp / weapon / LOS(omniscient, 仅用于 expose 判定)
 └─ 交战检测：对每个玩家维护 engagement state machine
       states: IDLE → CONTACT → ENGAGED → DISENGAGED(→ RE-ENGAGE) …
```

**动作族形式化谓词（V1 规则，参数进 config 可调）：**

| Action family | 判定条件（全部可测量） | 关键特征 |
| --- | --- | --- |
| PEEK | 起点在掩体/低暴露，随后向敌方角度移动，exposure 上升，速度≥阈值，yaw 指向可能敌角 | velocity, yaw, LOS 暴露度, buttons |
| HOLD | 静止（速度≈0），架住某角度，接触后维持 ≥ 阈值时长，无大幅位移 | velocity≈0, yaw 稳定, 接触事件 |
| RE_PEEK | PEEK → DISENGAGE（回掩体）→ 短窗口内同角度再次 PEEK | 两次 PEEK 的角度差 < θ, 间隔 < W |
| DISENGAGE | 接触后（damage/shots）离开角度回掩体，窗口内不再交火 | velocity 反向, exposure 下降, 无后续 shots |
| FALLBACK | 持续远离压力/炸弹点位，向更可守位置后撤，越过队友防线 | 位移方向, 距离增量, bomb/队友位置 |

**DecisionPoint 候选条件**：判定时刻必须满足 ≥2 个动作族的**前置条件**（例如：有掩体可退 → DISENGAGE/FALLBACK 可行；有角度可架 → HOLD 可行；有敌方信息 → PEEK 可行）。否则是「别无选择」，不是 DecisionPoint。

**置信度**：evidence 完整性评分 —— 有 velocity+buttons+yaw 证据 + 有 LOS 判定 + 有接触事件 → 高；只有部分 → 低。置信度过低不产出 DP。

**去重与重要性排序**：聚类邻近候选（同一交战 episode 只保留一个决策时刻 = 交火前最后一个可行分叉点）；按「决策显著性」打分（接触强度、bomb 状态、人数劣势/优势、round 关键度、动作结果）取 Top-N。

**V1 数量目标**：一场完整比赛保留 **30–80 个** DP（可配置阈值）。

---

## 2. Peek / Hold / Re-peek / Fallback 怎么形式化？

- 见上表谓词。要点：每个动作族 = (前置条件) ∧ (执行特征窗口 W 内成立) ∧ (存在证据 tick)。
- **执行特征窗口**：动作从开始到结束的 tick 范围（start_tick / decision_tick / end_tick，spec §3 字段），供 Execution 层切窗口做 aim/movement 分析。
- **Re-peek 判定优先级**：RE_PEEK ⊃ PEEK（先判 re-peek，再判 peek），避免重复计数。
- 若历史数据中某动作族无法可靠识别 → 直接返回 NO_COMPARABLE_ALTERNATIVE，不强行生成（§10）。

---

## 3. PlayerKnownState 怎么构建？

### 信息源（全部来自 demo 可确定信号，无 VLM）— 实测可用性见 TECHNICAL_SPIKE

| 信息源 | demo 信号 | 状态 |
| --- | --- | --- |
| 自己视野 | FOV 锥（CS2 约 90°）+ LOS raycast（awpy visibility 原语）∩ 敌人位置 | V1 实现 |
| 队友共享（假设开黑/默认信息共享，config 可关） | 队友视野 ∩ 敌人位置 → last_seen 记忆 | V1 实现（保守默认：仅自己+队友最后确认位置） |
| 声音线索 | player_footstep 事件（实测 733 条可用）+ 开枪声（weapon_fire 位置） | V1 实现（半径阈值 config，如 20m） |
| 伤害来源 | player_hurt 事件（attacker 位置、weapon、hitgroup） | V1 实现 |
| 道具信息 | grenade 事件（烟/闪/火/雷，含 detonate 位置） | V1 实现 |
| bomb 信息 | bomb_planted / bomb_defused / 携带者 last_seen | V1 实现 |
| 经济信息 | item_purchase 事件（实测 1120 条）→ 双方经济量级 | V1 实现（粗略桶） |
| 击杀信息 | player_death 事件（谁杀谁、位置、武器、距离）→ kill feed | V1 实现 |

### 可知状态模型（每个玩家 × tick 可计算）
```
PlayerKnownState {
  seen_enemies: [{ enemy_id, last_seen_pos, last_seen_tick, source: own|teammate, confidence }],
  heard: [{ type: footstep|shot|grenade|flash, pos, tick, confidence }],
  damage_derived: [{ attacker_id, attacker_pos?, weapon, tick }],
  known_bomb: { planted_site?, carrier_last_seen?, status },
  known_economy: { own_money, team_spend_estimate, enemy_economy_bucket? },
  public_info: { round_time, score, alive_counts, freeze_end_tick, weapon_in_hand },
  utility_remaining: [own nades],
}
```
每条目带 **source / confidence / 遗忘衰减**（超过 T 秒未更新 → 降级为"可能"→"未知"）。

### 保守原则
V1 只把有明确证据的事实放进 PlayerKnownState；其余一律 unknown。**禁止**把 GroundTruth 敌人位置当可知信息。

### 公开 vs 私有信息清单（供审计）
- 公开（可用于 Decision 层）：round_time、score、alive 数（kill feed 可见）、bomb 状态、freeze time、自己位置/武器/道具、经济（估值）。
- 私有（只进 GroundTruthState）：敌人精确位置、敌人 hp、敌人经济、敌人道具。

---

## 4. GameState similarity 怎么设计？

### StateFeatureVector（§8 候选特征落地）
```
map (hard)
side (hard)
location_zone (hard, 区域语义)
action_family (hard, 比较时按动作分组)
alive_count_bucket (soft, 如 5v5/4v5/3v5/…)
round_time_bucket (soft, 秒桶)
hp_bucket (soft, 25 一档)
weapon_class (soft, 如 rifle/smg/pistol/sniper)
teammate_structure (soft, 锚定相对表示，见 §6)
known_enemy_info (soft, 已知敌方位置数 + 其空间散布)
recent_contact (soft, 过去 N 秒是否有接触)
utility_state (soft, 道具数桶)
bomb_state (soft, 未下/已下/携带者位置已知)
economy_bucket (soft)
```

### 距离度量
- 数值特征归一化后加权 L2/余弦；分类特征用相等性（或 one-hot）。
- **权重可配置**（JSON 文件）：V1 默认权重来自专家直觉 + 敏感性检查，不做黑盒调参；权重对象支持 ablation（§26）。

### 相似度输出
`similarity_score ∈ [0,1]` + top-k 列表 + 每条的 feature 对齐报告（哪些特征匹配、哪些偏离）。

---

## 5. Location 用 nav area、区域语义还是坐标？

**结论：三层并用，各司其职。**
1. **区域语义（callout/zone）→ Hard Filter 与展示**。来源：`@cs2dak/maps` zones/callouts 或 awpy nav 聚类。粒度以「Mid / A site / B site / CT spawn / …」级为准（约 8–15 区/图），太细的 nav area 不做匹配键。
2. **nav area → 分析层**（微观距离、路线、控制面），来源 `.nav`（awpy Nav 或 cs2-demo-format 兼容解析）。
3. **原始坐标 → 保留**，用于 replay、LOS raycast、渲染。

V1 只实现区域语义 + 坐标；nav area 作为可选增强（若接入 awpy 不引入额外依赖成本）。

---

## 6. Teammate structure 怎么表示？

**结论：锚定相对表示（rotation-invariant、compact、可解释）。**

```
TeammateStructure = {
  alive_count,
  nearest_teammate_dist_bucket,
  teammates: [ { dist_bucket(<10m,<25m,<50m,>50m),
                 hp_bucket, weapon_class, has_los_to_contact_angle? } × n ],
  teammates_on_site_near_angle: count,
}
```
- 以决策玩家为锚，不存全局距离矩阵（旋转不变、维度小、利于相似度）。
- `has_los_to_contact_angle` 用 LOS 原语近似"队友能否帮架/帮打"，ablation 时验证是否有增益。

---

## 7. Similar-state 数据至少需要多少场 Demo？

### 数量模型（V1 检测器实测标定，见 TECHNICAL_SPIKE 后更新）
- 每场约 30–80 DP（按 §1 阈值），约 18–24 局。
- 一个比较单元 = (map, side, zone, alive bucket, action family)。粗估只有 5–20% 的 DP 落入同一单元。
- 设目标单元样本 n≥10（每动作族）、单元内 ≥2 个动作族可比较 → **单一地图单侧至少 50–150 场**才有稳定证据；全图聚合（zone 粗化）可降一个量级。

### V1 的现实策略
- 反事实数据库 = **用户自己的历史 demo 库**（本地解析入库，结构化 DecisionState，不在查询时解析）。
- 覆盖报告：显示每个 (map, side, zone) 单元的样本数与可比较动作族数；低于阈值 → INSUFFICIENT_EVIDENCE。
- 未来 V2 pro 参考库（§22）解决"个人历史不足"问题——但那是参考行为，不是答案。

---

## 8. 如何避免样本极少导致伪结论？

确定性门槛（全部 config 化）：
1. **n_min_claim = 10**（任何结论的总样本下限；单元内每动作族 n_min_action = 5）。
2. 比例用 **Wilson 区间**，不报点估计。
3. **效果量门槛**：两动作的结果区间无分离（CI 重叠）→ 报 "no reliable difference"，不报数值高低。
4. 相似度加权结果（soft evidence）与原始结果并存展示，主结论用原始计数。
5. 低于门槛 → 固定返回 **INSUFFICIENT_EVIDENCE**，LLM 只解释缺什么证据。

---

## 9. 如何避免 selection bias？

偏置来源与缓解：
| 偏置 | 缓解 |
| --- | --- |
| 动作-状态相关（玩家只在有把握时 peek） | 按 PlayerKnownState 特征分桶比较；报告每动作族的样本构成（地图/玩家/时段占比）；明示 confounders 清单（§12） |
| 幸存者/录制偏置（demo 都是打完的局） | 在 Evidence Strength 中声明"仅覆盖已录制完整对局" |
| 玩家内自适应（爱后撤的玩家产生不同 HOLD 样本群） | 支持按玩家/技能桶分层（V2）；V1 报告"样本来自哪些玩家" |
| 单元内样本分布不均（某玩家贡献过多） | 报告 top contributor 占比；可选 per-player 权重 |

**口径声明**：CounterfactualResult 一律是描述性统计（"历史上类似状态这样发展"），不声称因果（"这样做会更好"）。

---

## 10. 如何避免 hindsight bias？

1. **架构强制分离**：Decision 层只接收 PlayerKnownState 派生特征；GroundTruth 特征若被 Decision 层引用 → 审计违规（测试用例覆盖）。
2. **特征白名单**：相似度与动作比较只用 §3 公开信息 + PlayerKnownState；隐私特征（敌人位置/hp/道具）物理上不进入 feature vector。
3. **双状态输出**：每个 DP 同时输出 GroundTruthState 与 PlayerKnownState（§6），供展示"当时玩家看到什么"。
4. **自动审计**：管线测试断言——用 GroundTruth 敌人位置算出的特征必须不改变 Decision 层输出。

---

## 11. Outcome 应该如何定义？

### 核心三元组（V1 展示）
- **survival@W**：decision_tick + W（默认 10s 或 round 结束，先到为准）玩家是否存活。
- **duel_outcome**：该 DP 关联交战的结果 won / lost / undefined（duel 归属：窗口内 damage/kill 对；复用 cs2-demo-format duels.json 或自建归属）。
- **round_win**：该 round 是否获胜。

### 数据模型（支持扩展，spec §11 全量字段）
first_damage / first_kill / tradeability / local_control（接触角控制面变化）/ teammate_survival / positional_value（可守性代理）/ utility_cost —— V1 全部算出但默认不展示，模型层预留。

### 窗口与边界
- 固定 outcome 窗口 W（config），避免"看完整局结果"引入时间维度噪声；round_win 除外（全局限定）。
- duel_outcome 需要与 DP 关联：DP → 交战 episode → 归属 duel；归属规则确定性实现（时间窗口 + 伤害对）。

---

## 12. Counterfactual 的验证标准是什么？

见 BACKTEST_DESIGN.md（阶段 4）。要点：
- **Historical Holdout**：留一场/留一 DP，只用决策前状态预测，与真实 outcome 对比（calibration + Brier）。
- **Retrieval QA**：人工抽样 top-k 相似度合理性。
- **Ablation**：position only / +time / +team structure / full state 的检索质量对比。
- **可复现性**：同一 demo 输入 → 逐字节相同输出（确定性管线）。
- 任一环节失败 → 对应能力标记为 "unvalidated"，不放 V1 主界面。

---

## 13. 是否需要未来公共 reference dataset？

**V1：不需要（个人历史库足够验证管线）。V2：需要，但注意约束。**
- V2 pro 库：public demo 源 → downloader → metadata → parser → DecisionState 预入库（查询时不解析）。
- **关键口径**（spec §22）：职业行为 ≠ optimal。展示 "Pro Reference Behavior"，绝不标注 "Correct Answer"；职业环境含团队系统/交流/协同道具/对手准备/执行能力等混杂。
- 公共 demo 获取的 ToS/合规边界在 V2 启动前单独评估（V1 不做爬虫）。

---

## 14. 哪些结论必须明确返回"不知道"？

固定返回词汇（用户可见）：
| 场景 | 返回 |
| --- | --- |
| 样本低于门槛（§8） | `INSUFFICIENT_EVIDENCE` |
| 某备选动作在历史上无样本 | `NO_COMPARABLE_ALTERNATIVE` |
| 两动作结果 CI 重叠 | `NO_RELIABLE_DIFFERENCE` |
| 决策时刻信息不足以形成有效决策（无接触/无数值依据） | `INSUFFICIENT_INFORMATION_AT_DECISION_TIME` |
| 执行指标无数据（没开枪→无 aim 指标） | `NOT_APPLICABLE` |
| 需要 demo 之外的信息（语音内容、意图） | `NOT_AVAILABLE_IN_DEMO` |
| LLM 必须在此类情况下只解释"缺什么证据"，**禁止补全事实** | — |

---

## 15. 可行性结论（阶段 3 判定）

| 问题 | 结论 |
| --- | --- |
| DP 检测可靠？ | 可行（规则状态机 + 证据门槛），V1 目标 30–80 DP/场 |
| 动作族形式化？ | 可行（5 个谓词 + 窗口 + 置信度） |
| PlayerKnownState 构建？ | 可行（demo 信号齐全：视野/LOS/footstep/damage/道具/bomb/经济均实测可用），保守默认 |
| 相似度设计？ | 可行（Hard + Soft，权重可配置可 ablation） |
| Location 表示？ | 区域语义（匹配）+ nav/坐标（分析/渲染），三层并用 |
| Teammate 结构？ | 锚定相对表示 |
| 最少数据量？ | 单图单侧 50–150 场（V1 用个人库 + 覆盖报告管理预期） |
| 伪结论防护？ | 门槛 + Wilson CI + 效果量 + INSUFFICIENT_EVIDENCE |
| selection bias？ | 分层报告 + confounders 清单 + 描述性口径 |
| hindsight bias？ | 双状态架构 + 特征白名单 + 审计断言 |
| Outcome 定义？ | survival@W / duel_outcome / round_win 三元组 + 扩展模型 |
| 验证标准？ | Holdout + Retrieval QA + Ablation（见 BACKTEST_DESIGN） |
| 公共数据集？ | V2 才做；Pro Reference 行为 ≠ optimal |
| "不知道"清单？ | 6 类固定返回词汇（§14 表） |

**阶段 3 判定：Counterfactual 链路的每个环节在数据与算法上都可行；主要风险是样本量与 PlayerKnownState 的保守性导致的低覆盖率——这正是 V1 用 INSUFFICIENT_EVIDENCE 制度化管理的东西。**
