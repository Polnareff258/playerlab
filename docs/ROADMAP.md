# ROADMAP.md — V1 之后（只写规划，不在 V1 实现）

> 本文件内容来自 spec §22，仅作为路线规划存档。

## V1.5 — Match-Level Analysis（对局级分析）

**新增能力**
- **Decision Graph**：单场/多场的决策点图（DP 按 round 串联，动作族转移，与结果着色）
- **Repeated mistake detection**：跨场识别重复出现的同单元决策问题
- **Behavioral fingerprints**（行为指纹）：
  - Immediate re-peek tendency（接触后立即 re-peek 频率）
  - Overstay after contact（接触后停留过久）
  - Wide swing preference（大拉偏好）
  - Early disengage（过早脱离）
  - Utility-before-engage frequency（交火前道具使用频率）
- 形成分层：Round → Match → Long-term behavior

**工程要点**
- 复用 V1 的 DP/outcome 数据，纯聚合层；相似度索引规模 >10^5 时引入 ANN（usearch/annoy）评估

## V2 — Professional Reference Population（职业参考人群）

**新增能力**
- 公共 demo 源 → downloader → metadata → parser → DecisionPoint extraction → **Reference State DB（预存结构化 DecisionState，查询时不解析）**
- 查询同时比较：Your History / Reference Population / Pro Reference

**关键口径（spec §22 强制）**
- 职业行为 ≠ Optimal Action；界面显示 **Pro Reference Behavior**，绝不显示 "Correct Answer"
- 职业环境混杂：team system / communication / coordinated utility / opponent preparation / execution ability —— 作为 confounders 显式展示
- 公共 demo 获取的 ToS/合规边界在启动前单独评估

## V2+ — Skill Model（长期技能模型）

- 长期维度：Aim / Mechanics / Decision 三轴模型
- 数据来源：V1 DP + execution 指标 + V1.5 行为指纹的时间序列

## V3 — Aim Trainer Integration（瞄准训练器集成）

- 接入：Kovaak / Aim Lab
- 研究问题：Trainer improvement → CS2 mechanics change → Real-game transfer（训练提升是否迁移到实战）
- 依赖 V2+ 的 Aim/Mechanics 测量基线

## 永不承诺

- "Optimal Action" 断言（任何版本都以描述性统计呈现）
