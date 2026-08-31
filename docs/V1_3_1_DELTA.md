# V1_3_1_DELTA.md — Phase A：V1.3 → V1.3.1 增量审计

> 审计对象：`episode.py / macro.py / evaluate.py / evidence.py / decision.py /
> context.py / tradeability.py / feasibility.py / patterns.py / training.py /
> model_provider.py / csnet.py / annotation.py / db.py / api.py / ui/index.html`
> （HEAD `0d31221`，V1.3 提交）。
> 目的：确认 V1.3.1「Alternative Evidence + Engagement & Duel Execution」的复用面与缺口（spec §94）。

---

## 1. 现状基线（可复用面）

| 模块 | 现状（V1.3） | V1.3.1 复用 |
| --- | --- | --- |
| episode.py | DecisionEpisode 542/场（3 family）、CandidateAction、Actionability、`_state` 合成（features 空） | ★★ episode 骨架保留；`_state` 需补 retrieval features（spec §62）；加 decision_domain / engagement_id |
| macro.py | MacroContext（advantage/risk/need_info）完整 | ★★★ 原样保留（spec §2） |
| evaluate.py | DecisionEvaluation（outcome-free）+ Actionability | ★★ 拆三层：Strategic/Engagement/Execution（spec §73/§102）；EvidenceSufficiency gate（spec §70-§71） |
| evidence.py | rule/historical/personal/model channels；`_state` features 空 → historical/personal 真实返回 None | ★★ 修复：episode retrieval features（spec §62-§64）+ CS-NET episode value（spec §65） |
| decision.py | DP 检测（PEEK/HOLD/RE_PEEK/...） | ★★★ ObservedAction 复用；交战窗口事件源 |
| context.py | TemporalContext（4s 窗口 + KnownState + info strength/dir） | ★★★ 保留 |
| tradeability.py | Tradeability + NULL_GEOMETRY | ★★★ AwpyGeometry optional（spec §25-§27） |
| feasibility.py | 6 态规则引擎 | ★★ engagement method 可行性（spec §15） |
| patterns.py | 3 检测器（聚合） | ★★ 挂接 DuelExecution（spec §44），不再孤立 |
| training.py | TrainingTarget（bottleneck + episode pattern 双源） | ★★ 三层目标：Strategic/Engagement/Execution（spec §76-§80） |
| model_provider.py / csnet.py | GameModelProvider/CSNetProvider（win_rate 真实） | ★★★ CS-NET 进 episode evidence（spec §65）；duel head spike（spec §67） |
| annotation.py | ReviewQueue + DecisionEpisode cards + pairwise preference | ★★ 新增 engagement_method/execution_issue/movement_effect 类型（spec §83-§85） |
| db.py | schema v5（decision_episodes 5 表） | ★★ v6：episode 加 decision_domain/engagement_id/三层 eval/evidence_sufficiency；新表 engagements + duel_states + engagement_preferences |
| ingest.py / fieldmap.py | tick 字段无 duck/ammo/flash/zoom/inventory | ★★★ 补 5 字段（已验证 demoparser2 可用）：`Weapon.m_iClip1`（ammo）、`CCSPlayerPawn.m_flFlashDuration`（被闪）、`m_iZoomLevel`、`buttons` duck 位（IN_DUCK=4）、utility 事件计数 |

## 2. V1.3.1 新增（spec §1-§93 落点）

| 能力 | 模块 | 对应 spec |
| --- | --- | --- |
| 五层分析链（Macro→Strategic→Engagement→Execution→Effect） | 架构 | §1 |
| decision_domain（STRATEGIC_LOCAL/ENGAGEMENT/EXECUTION_RELEVANT/OBJECTIVE） | episode.py + db | §8 |
| EngagementContext（self/opponent/weapon_matchup/info_advantage/geometry/utility/duel_phase） | `engagement.py`（新） | §9-§13 |
| InformationAdvantage（SELF/ENEMY/MUTUAL/NEITHER/UNKNOWN） | `engagement.py` | §12 |
| WeaponMatchup（class + range bucket） | `engagement.py` + `weapons.py` 扩展 | §13 |
| EngagementMethod（base_action × method；self/team utility 区分） | `engagement.py` | §15-§18 |
| MVP method detection（HOLD/NORMAL_PEEK/WIDE_SWING/DRY_PEEK/FLASH_PEEK/TEAM_FLASH_PEEK/JIGGLE/LET_CROSS/DISENGAGE） | `engagement.py` | §14/§98 |
| DuelState 序列 + EngagementPhase（PRE_CONTACT..RESOLUTION） | `duel.py`（新） | §32-§35/§99 |
| crosshair error（angular_error_head/chest，APPROXIMATE_HITBOX） | `duel.py` | §36-§38 |
| 4 execution primitives（FIRE_BEFORE_AIM_READY/PREAIM_ERROR/MOVING_SHOT/IRREGULAR_DUEL_MOVEMENT） | `duel.py` | §39-§44/§100 |
| MovementPattern（STATIC..WIDE_SWING）+ MovementEffect（self cost / opponent tracking） | `duel.py` | §45-§57/§101 |
| Three-Level Evaluation（strategic/engagement/execution） | `evaluate.py` 扩展 | §73/§102 |
| EvidenceSufficiency（HIGH/MED/LOW/INSUFFICIENT → eval gate） | `evidence.py` | §68-§71 |
| CS-NET episode value（before/after/delta）+ duel head spike | `evidence.py` + `csnet.py` | §65-§67 |
| engagement_id 链接（strategic→engagement→execution 一条卡片） | db + api + ui | §115-§117 |
| Human review（engagement_method/execution_issue/movement_effect + preference） | annotation.py + ui | §83-§85 |
| Engagement/Execution learning samples 导出 | `dataset.py`（新） | §86-§88 |

## 3. 关键设计决策（审计结论）

1. **DuelState 性能**（spec §113-§114）：只对 detected engagement windows 提取高频序列（50-100ms 降采样），不逐玩家逐 tick；engagement_sequences 缓存到 analyses/。
2. **duck_state 来源**：CS2 SourceTV 不记录 `m_flDuckAmount`（实测被静默丢弃）→ 用 `buttons & IN_DUCK(4)`（已验证掩码 1036 出现 duck bit）。
3. **flash_duration 可靠**：实测真实值 0.0-4.75 → enemy_was_flashed 可直接读（spec §31）；utility inventory 从事件计数（flashbang_detonate 等）+ clip 推断。
4. **EvidenceSufficiency 修复 INSUFFICIENT=0**（spec §68）：考虑 known state 完整度 / geometry / utility 确定性 / opponent info / historical 样本数 / model evidence → 不足时 eval=INSUFFICIENT_EVIDENCE（spec §71）。
5. **dry peek 定义**（spec §17）：主交战窗口前无 self/team flash + 无 smoke/molotov 位移辅助 → DRY；不只凭「有没有扔闪」。
6. **三层评价不混**（spec §80）：strategic=GOOD + engagement=GOOD + execution=POOR → 只生成 execution target。
7. **CS-NET 不覆盖判定**（spec §66）：delta<0 不自动 POOR（测试覆盖）；duel head 只作 DuelDifficultyEvidence（spec §67）。

## 4. 明确不做（spec §118）

- 完整所有 peek/grenade 分类、完整 hitbox reconstruction engine、raw video/VLM、pro demo corpus、Tiny Transformer / Decision Ranker / Movement Model 训练、完整 recoil coach、GameSense score。

## 5. 验收判定（spec §120 对照）

| 判据 | 计划 |
| --- | --- |
| A 区分「不该打」vs「该打但打法不合理」 | Strategic eval + Engagement eval 分离 |
| B 区分「打法合理但执行失败」 | Engagement eval vs Execution eval |
| C 检测 dry peek / wide swing / flash-assisted | Engagement method detection（真实 demo 分布） |
| D 检测 fire-before-aim-ready / preaim error / moving shot / irregular movement | 4 execution primitives |
| E MovementEffect 双面（self cost + opponent tracking） | MovementEffect heuristic |
| F 同 irregular movement 近 SMG vs 中远 rifle 不同解释 | MovementEffect 上下文依赖（weapon/range） |
| G CS-NET/historical 只辅助不覆盖 | 测试 + 结构保证 |
| H 证据不足 → 真实 INSUFFICIENT_EVIDENCE | EvidenceSufficiency gate（测试覆盖） |
