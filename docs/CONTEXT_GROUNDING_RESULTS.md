# CONTEXT_GROUNDING_RESULTS.md — Context Grounding 结果报告（spec §59）

> 数据：真实 de_dust2 demo（18 局）· V1.2.1 全管线重跑 · 日期：2026-08-31

---

## 1. KnownState 接入覆盖（spec §2/§5）

| 指标 | V1.2 | V1.2.1 |
| --- | --- | --- |
| IntentSample player_known_state | `{}`（0/540 接入） | **540/540 完整接入** |
| known_state_sequence / information_sequence | 无 | ✅ 逐 timestep 生成 |
| round_id / episode_id（spec §19 split metadata） | 无 | ✅ `{match}-r{round}` / `{match}-r{round}-{player}` |
| 信息特征（strength/direction）非 NONE 比例 | 0% | **531/540 (98.3%)** |
| 新增字段（known_enemy_zones/directions、time_since_*、bomb_known/zone/confidence、teammate_contact_count、recent_teammate_kill/death、objective_information、recent_sound_info） | 无 | ✅ 全字段产出 |

## 2. InformationStrength / Direction（spec §3/§4）

- **实现**：`information.py`，LLM-free 确定性组合（own_vision 1.0 / team_vision 0.85 / damage 0.9 / footstep 0.6 / shot 0.7 / grenade 0.6，半衰期 1-6s）+ 时间衰减 → NONE/WEAK/MEDIUM/STRONG/CONFIRMED + confidence。
- **测试**：fresh vision → CONFIRMED；半衰期衰减正确；超陈旧 → NONE；bomb 公共信息 → STRONG+。Direction：A/B/MID 多数票 + confidence。
- **真实 demo**：信息强度分布（540 samples 中 531 非 NONE）——玩家在绝大多数时刻有可用的已知敌/bomb 信息。

## 3. Intent 规则变化（spec §6 核心：为什么 ≠ 怎么移动）

| intent | V1.2 | V1.2.1 | 说明 |
| --- | --- | --- | --- |
| HOLD | 225 | 225 | 不变（静态无信息） |
| REPOSITION | 255 | 26 | 大幅下降：无强信息的长移动不再默认 REPOSITION |
| SOFT_ROTATE | 14 | 10 | 基本持平 |
| ROTATE | 0 | 0 | 本场仍无满足「强对侧信息 + 跨区 + 方向一致」的真实样本（诚实） |
| AMBIGUOUS | 46 | 279 | **上升**：信息特征让更多样本 top1/top2 接近 → 诚实输出 AMBIGUOUS（不硬猜） |

**判据 §74-A 测试**（同轨迹不同信息 → 不同判定）：
- Case A（A→Connector→Mid，B 无信息）→ **REPOSITION/SOFT_ROTATE**（非 ROTATE）✅
- Case B（同轨迹 + 2 敌确认 B + bomb B）→ **ROTATE** ✅
- 单元测试 `test_rotate_vs_reposition_same_movement_different_info` 覆盖。

**观察**：AMBIGUOUS 上升是信息驱动规则的预期副作用（无强信息不猜）；规则阈值（`intent_ambiguity_threshold=0.15`）可在人工标注积累后校准。

## 4. Tradeability 结果（spec §7/§8/§10）

真实 demo 死亡锚点 tradeability 分布：

| classification | n | 说明 |
| --- | --- | --- |
| MEDIUM | 112 | 无 LOS 几何（NULL_GEOMETRY）时**保守封顶 MEDIUM**（spec §8：不伪造 HIGH） |
| UNKNOWN | 18 | 队友死亡/数据缺失 |
| UNAVAILABLE | 11 | commitment 阻断 IMMEDIATE_TRADE（plant/defuse/reload 中） |
| HIGH | 0 | 需要 LOS provider 确认才能给（awpy 集成后可用） |

- **判据 §74-B**（远队友但可补枪 → 不判 isolated）：`test_tradeability_los_supported_case` 验证 LOS/nav 支持时非 UNAVAILABLE；距离单独不产生 isolated 结论。✅
- **距离假阳性测试**：近距离队友 + 墙（LOS=False）+ commitment 阻断 → UNAVAILABLE ✅（距离≠tradeability）。
- LOS/nav 研究结论见 `LOS_NAV_SPIKE.md`：awpy（MIT）提供 NavMesh + visibility raycast，本阶段未集成（依赖隔离优先），TradeabilityGeometry 接口已就绪，未来注入。

## 5. Responsibility 分布（spec §55/§56，详见 RESPONSIBILITY_CALIBRATION.md）

| attribution | V1.2 | V1.2.1 |
| --- | --- | --- |
| SELF_DECISION | 153 (76.9%) | 25 (17.7%) |
| SHARED | 0 | 114 (80.9%) |
| INSUFFICIENT_EVIDENCE | 36 | 1 |
| NOT_ACTIONABLE | 10 | 1 |

## 6. Review 统计（spec §16-§18）

| 指标 | V1.2 | V1.2.1 |
| --- | --- | --- |
| 预算/场 | 4 | **8（可配置）** |
| quota | 无分类限制（intent 挤占 10/13） | **intent 3 / responsibility 2 / pattern 2 / other 1** |
| 本场 review queue | 14 条（intent 10） | **8 条（intent 3 / resp 2 / repeek 2 / advantage 1）** |
| review_focus | 无 | ✅ balanced / intent / responsibility / pattern / other |
| 新优先级 | intent AMBIGUOUS 优先 | ✅ + top1/top2 接近、responsibility conflict、low-confidence tradeability |

## 7. 数据集泄漏预防（spec §19/§20）

- IntentSample 现含 `match_id / round_id / episode_id`，支持 match-level split 与 Leave-One-Match-Out。
- 人工标签 = 0 < 200 门槛 → **模型 spike 判定：INSUFFICIENT_DATA_FOR_MODEL_SPIKE**（spec §21，不硬训练）。
- Tiny Model 正式比较需 500-1000 条多场多图人工标注（spec §20）—— 未达成，如实报告。

## 8. Success Criteria 对照（spec §74）

| 判据 | 结果 | 证据 |
| --- | --- | --- |
| A 同轨迹不同信息 → ROTATE vs REPOSITION | ✅ | 单元测试 + 信息特征驱动 |
| B 远队友可补枪 → 不判 isolated | ✅ | tradeability LOS 测试 + 真实分布（无 HIGH 即保守） |
| C 合理 plant 承诺不背锅 | ✅ | NOT_ACTIONABLE 路径 + 测试 |
| D 危险 reload → SELF_DECISION | ✅ | 5 例实测 + 测试 |
| E CS-NET 至少一个真实 head 返回 ModelEvidence | ✅ | win_rate 0.5902 + 全链路 |
| F 无 CS-NET 时完整运行 | ✅ | Null provider + 48 测试全绿 |

## 9. 已知局限（诚实披露）

1. 单场单图（de_dust2）；distribution 结论需多场验证。
2. AMBIGUOUS 上升（279/540）—— 阈值待人工标注校准。
3. tradeability 无 HIGH（无 LOS provider）—— awpy 集成后预期出现。
4. SHARED 80.9% 可能过左 —— 需全量人工 review 判定是否收紧。
5. 人工标签 0 条 —— 模型 spike 门未过（INSUFFICIENT_DATA_FOR_MODEL_SPIKE）。
