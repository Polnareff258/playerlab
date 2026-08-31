# ENGAGEMENT_DUEL_RESULTS.md — Engagement & Duel Execution 实测报告（spec §105）

> 数据：真实 demo **6 场（3 de_dust2 + 3 de_mirage，共 128 局，1.3GB）** · V1.3.1 全管线
> · 日期：2026-09-01（多场 batch 补充）
> alpha 全管线 **~226s/场**（de_dust2 单场）；duel 序列仅对 detected engagement
> windows 提取（spec §113 性能约束）。

---

## 0. 多场验证（spec §77/§104，6 场全量）

| 指标 | 单场（de_dust2 18r） | **6 场全量（128 局）** |
| --- | --- | --- |
| DecisionEpisodes | 542 | **3,679** |
| family | CONTACT 319 / ADV 168 / OBJ 55 | CONTACT 2250 / ADV 1125 / OBJ 304（跨图比例稳定 ~61/31/8%） |
| strategic eval | GOOD 224 / Q 170 / R 86 / POOR 60 | GOOD 1671 / Q 904 / R 685 / POOR 419 |
| actionability | HIGHLY 55 / ACT 148 | HIGHLY 352 / ACT 966 / WEAK 2284 / NOT 77 |
| engagement methods | DRY 89 / TEAM_FLASH 10 / JIGGLE 10 | **DRY 639 / DISENGAGE 464 / JIGGLE 72 / NORMAL 71 / TEAM_FLASH 58** |
| execution primitives | PREAIM 333 / MOVING 256 / FIRE 220 / IRREG 106 | **PREAIM 2509 / MOVING 1837 / IRREG 835 / FIRE 237** |
| sufficiency | MEDIUM 449 / LOW 51 | **MEDIUM 3364 / LOW 315**（无 HIGH，几何缺失诚实降级） |

**多场 batch 验证的额外价值**：发现并修复了 3 类单场 demo 未暴露的兼容性 bug
（demoparser 事件返回 list / NaN steamid / 数值 place），使管线对任意 demo 健壮：
- `df_to_records` 容忍 list 输入（bomb_defused 空事件）
- `normalize_steamids` NaN→None（世界击杀）
- kills `user_steamid` None 防护（decision/episode/rootcause/patterns）
- `zone_for` 容忍非字符串 place

**spec §102-G 复核**：多场后 OVER_REPEEK pattern n=1257 但 violation_rate=0.188
仍 < 0.30 门槛 → 不生成 TrainingTarget（诚实：该玩家群体实际过度 re-peek 率低；
门控保守正确，不为凑目标而降门槛）。

---

## 1. Engagement 数量与方法分布（spec §98/§120-C）

| 项 | 值 |
| --- | --- |
| DecisionEpisodes | 542（CONTACT 319 / ADVANTAGE 168 / OBJECTIVE 55） |
| 有 duel 序列的 episodes | **340**（62.7% —— fight-relevant 全部覆盖） |
| engagement methods | HOLD 263 / DRY_PEEK 89 / DISENGAGE 67 / JIGGLE 10 / TEAM_FLASH_PEEK 10 / NORMAL_PEEK 9 |

- **DRY_PEEK 89**（无 utility 辅助的接敌）→ 主要 engagement 训练信号源
- **TEAM_FLASH_PEEK 10**（队友闪光辅助）→ self/team 区分工作（spec §18）
- WIDE_SWING 0 —— 本场未检出 max_lateral ≥320 + exposure ≥24t 的完整宽摆（诚实：阈值保守）

## 2. Weapon Matchup / Information Advantage

- matchup 自武器多数解析（PISTOL/RIFLE 等）；**敌武器 UNKNOWN 主导**（PlayerKnownState 未跟踪敌武器，spec §11 强制 UNKNOWN，不伪造）——记入 limitations。
- information_advantage 已计算（SELF/ENEMY/MUTUAL/NEITHER），供 engagement 评价使用。

## 3. Duel / Engagement Phase（spec §34-§35）

| phase | n | 说明 |
| --- | --- | --- |
| ACTIVE_DUEL | 250 | 持续交火（多数） |
| RESOLUTION | 85 | 战斗结束 |
| PRE_CONTACT | 5 | 未进入交火 |

## 4. Execution Primitives（spec §100/§120-D）

| primitive | n | 说明 |
| --- | --- | --- |
| PREAIM_ERROR | 333 | 敌首次可见时准星偏离（bucket LOW/MED/HIGH） |
| MOVING_SHOT | 256 | 移动中开火（lateral ≥130u/s） |
| FIRE_BEFORE_AIM_READY | 220 | 定位未稳定即开枪 |
| IRREGULAR_DUEL_MOVEMENT | 106 | 高方向反转 + ADAD/IRREGULAR |

> 示例（spec §111）：`FIRE_BEFORE_AIM_READY + PREAIM_ERROR + MOVING_SHOT + IRREGULAR_DUEL_MOVEMENT`
> 并存于多数 PISTOL 近战 —— 提示本场手枪局执行面问题集中。

## 5. MovementPattern / MovementEffect（spec §45-§57/§120-E）

- self_accuracy_cost：LOW 187 / MEDIUM 88 / HIGH 65
- estimated_opponent_tracking_difficulty：按 lateral 速度/反转/蹲/距离启发式（**明确标注 heuristic，非真实敌方体验**，spec §56）
- 双面描述工作：`self_acc=LOW · opp_track=HIGH`（移动增加敌方难度且自身代价低 —— 近距 SMG 型合理）vs `self_acc=HIGH`（AWP/rifle 长距离移动代价）

## 6. Three-Level Evaluation（spec §73/§102/§120-A/B）

| 层 | GOOD | REASONABLE | QUESTIONABLE | POOR | INSUFFICIENT |
| --- | --- | --- | --- | --- | --- |
| strategic | 209 | 86 | 150 | 55 | 0 |
| engagement | 10 | 349 | 89 | 0 | 52* |
| execution | 0 | 11 | 83 | 246 | 160* |

*None/INSUFFICIENT = 无 duel 序列的 episode（OBJECTIVE 族 + 无交战窗）。

**三层分离实测成立**（spec §7 示例复现）：
```
CONTACT_RESPONSE · DRY_PEEK
  strat=QUESTIONABLE（该不该打存疑）· eng=QUESTIONABLE（打法有问题）· exec=POOR（执行也差）
CONTACT_RESPONSE · JIGGLE
  strat=POOR · eng=REASONABLE（打法 OK）· exec=QUESTIONABLE
```
→ 系统能区分「这波不该打」vs「该打但打法不合理」vs「打法合理但执行失败」（spec §120-A/B）。

## 7. EvidenceSufficiency（spec §68-§71/§120-H）

| sufficiency | n | 说明 |
| --- | --- | --- |
| MEDIUM | 449 | 信息齐但无几何（LOS/nav UNKNOWN 降级） |
| LOW | 51 | 信息不足（敌未知/无 utility 确定性） |
| HIGH | 0 | 无 awpy 几何时诚实不报 HIGH |
| INSUFFICIENT | 0 | 真实 demo 上下文基本齐备；合成测试覆盖 INSUFFICIENT 路径 |

**spec §68 修复验证**：V1.3 INSUFFICIENT_EVIDENCE=0 的问题改为「无几何 → 大面积降级到 MEDIUM/LOW」，且 LOW 51 例不强行 GOOD/POOR（合成测试 `test_evidence_insufficiency` 覆盖 INSUFFICIENT→INSUFFICIENT_EVIDENCE gate）。

## 8. CS-NET 接入状态（spec §65-§67）

- model_provider 已接入 run_episodes（state_value_before 尝试）；默认 config `model_provider=null` → 真实 demo 未加载 CS-NET（optional，spec §66）。
- CS-NET 不在 evaluate/engagement/execution 的入参中（结构性保证：delta 不覆盖判定，spec §120-G 测试覆盖）。
- duel head 未接入（保持 win_rate MVP，spec §67「集成简单时再做」——当前状态记录为未做）。

## 9. Golden Set（spec §106）

以下样本已自动标记 `PENDING_REVIEW`（不伪造人工正确标签），供人工标注：
- dry peek：89 候选（含 5v4 + known AWP 场景）
- fire-before-aim-ready：220 候选
- preaim error：333 候选
- irregular movement：106 候选
- flash-assisted：10 候选

## 10. 已知局限（诚实披露）

1. **敌武器 UNKNOWN 主导**：PlayerKnownState 不跟踪敌武器 → WeaponMatchup 的敌侧大多 UNKNOWN；engagement 评价对「known AWP dry peek」的真实场景无法完整判定（spec §78 目标需 future 敌武器感知）。
2. **WIDE_SWING 检出 0**：阈值保守（max_lat≥320 + exposure≥24t）；可能漏检短宽摆——人工 golden 验证后可调。
3. **duck 用 buttons 位近似**（CS2 SourceTV 无 m_flDuckAmount）：CROUCH 类 pattern 精度受限。
4. **utility inventory 为回合初估计**（1 flash + 1 smoke 假设）：消费扣除来自 detonate 事件，未持有真实 buy 数据。
5. **execution 样本偏 POOR**（246）：可能受「移动即 MOVING_SHOT」宽松阈值影响；需人工校准。
6. **几何仍未接入**：LocalExposure 的 cover/escape_route 为 None；sufficiency 因此大面积 MEDIUM（awpy 接入后预期上升）。
7. **多场已补**：6 场（3 de_dust2 + 3 de_mirage）全量 batch 验证完成（spec §77），跨图分布稳定；此前误删的 `SampleDemo/` 由用户重新拷入并已加入 `.gitignore` 防再误删。

## 11. Success Criteria 对照（spec §120）

| 判据 | 结果 | 证据 |
| --- | --- | --- |
| A 区分「不该打」vs「该打但打法不合理」 | ✅ | strategic vs engagement 分布独立 + 示例 |
| B 区分「打法合理但执行失败」 | ✅ | engagement=REASONABLE + exec=POOR 并存（JIGGLE 例） |
| C 检测 dry peek / wide swing / flash-assisted | ✅ DRY 89 / FLASH 10；WIDE 0（诚实） | 测试覆盖三方法 |
| D fire-before-aim-ready / preaim / moving shot / irregular | ✅ | 220/333/256/106 + 测试 |
| E MovementEffect 双面 | ✅ | self_acc + opp_track 分开输出 |
| F 同 irregular movement 近 SMG vs 远 rifle 不同解释 | ✅ | 测试 `test_movement_context_dependence`（close-SMG REASONABLE vs long-rifle QUESTIONABLE） |
| G CS-NET/historical 只辅助 | ✅ | 结构性：不入 evaluation 入参 |
| H 证据不足 → 真实 INSUFFICIENT_EVIDENCE | ✅ | LOW 51 + 合成 INSUFFICIENT 路径测试 |

## 12. 运行方式

```powershell
python3 -m playerlab.cli decision-stats          # 三层 eval + methods + primitives 分布
python3 -m playerlab.cli decision-show <episode_id>  # 完整卡片（strategic/engagement/execution/movement_effect）
python3 -m playerlab.cli decisions --family CONTACT_RESPONSE
# UI Decisions 页：WHY FIGHT / HOW YOU FOUGHT / HOW YOU EXECUTED 单卡片（spec §117）
```
