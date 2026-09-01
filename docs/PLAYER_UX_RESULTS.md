# PLAYER_UX_RESULTS.md — Player-Centric UX 结果（V1.3.2 PART M）

> 目标（PART A/B）：从 debug dashboard 改造成围绕指定玩家的比赛复盘工具。
> 核心原则：Player first · Moment first · Actionability before frequency ·
> Calibration before confidence。

---

## 1. FocusPlayerContext 架构（PART A）

- `focus.py`：session/application 级 FocusPlayerContext（match_id / steam_id /
  display_name / team / is_user）。
- **Remembered user**（"This is me"，PART A §4）：`remember_user(steam_id)`
  持久化到 player_profiles；后续含同一 SteamID 的 demo 默认 Focus 该玩家
  （`default_focus`），用户始终可切换（§5 不假设 demo owner → 显示 selector）。
- **steam_id 字符串化**（关键 bug 修复）：JS number 精度上限 2^53，
  CS2 steam_id（7656...）超限会截断 → 所有 player-scoped API 返回 string。
- 分析层查询（storage/service/API）按 player_id 过滤，非前端 JS filter（§2）。

## 2. Player-Scoped API（PART A §3）

| 端点 | 说明 |
| --- | --- |
| `GET /api/matches/{id}` | players 含 steam_id(string)/display_name/team/is_user/remembered |
| `GET /api/focus-player?match=` | 当前默认 focus（remembered user or null） |
| `POST /api/focus-player` / `POST /api/remember-player` | 设置 focus / 持久化 "This is me" |
| `GET /api/matches/{id}/players/{sid}/overview` | Player Match Overview（分布 + 可解释摘要） |
| `GET .../players/{sid}/decisions` | 该玩家全部 DecisionEpisodes |
| `GET .../players/{sid}/engagements` | 该玩家 engagement methods |
| `GET .../players/{sid}/patterns` | 该玩家 episode patterns |
| `GET .../players/{sid}/review-moments` | Top Review Moments |
| `GET .../players/{sid}/calibration` | 该玩家 calibration samples |
| `GET /api/players/{sid}/matches` | 跨场 PlayerProfile 聚合（PART H） |

## 3. ReviewMoment Ranking（PART B/J）

- `moments.py`：**selection/presentation 层，非新 detector**（PART B §8）。
- weighted factors（全部记录，可解释）：actionability 0.30 / sufficiency 0.20 /
  impact 0.20 / recurrence 0.15 / training 0.15。
- **校准门控**（PART J §43）：uncalibrated detector 的 primitive 施加
  cal_penalty（≤0.3），防止"PREAIM_ERROR 100 次但 uncalibrated"成为首页最大问题。
- **Positive moments 含入**（PART I §42）：Good Decision 允许入选；score-first
  排名 + 至少保留 1 个 good example 槽位（非纯找错器）。
- 每 moment 输出 `why_selected` 解释（§44）。

实测（真实玩家 73 episodes）Top 5：
```
0.73 POOR strategic decision   | highly actionable; high impact; directly training-relevant
0.55 POOR strategic decision   | ...; reduced: detector uncalibrated
0.54 Reasonable decision       | highly actionable; strong evidence
0.54 POOR strategic decision   | ...; reduced: detector uncalibrated
0.51 GOOD EXAMPLE              | strong evidence; recurring pattern
```

## 4. Player Match Overview（PART G）

```
MIXED · 73 decision episodes
Strong:      ADVANTAGE_PRESERVATION (good 78%)
Needs review: CONTACT_RESPONSE (good 13%)
no composite score; distributions + explainable summaries only
```
- 无 0-100 总分（PART G §35 禁止）→ 用 MIXED + 分布 + 可展开证据。
- Explainable summary（§36）：strengths/needs_review 基于 family 级 good_share。

## 5. UI 流程（PART B §6）

```
Import Demo → Match → Select Focus Player → Player Match Overview
→ Top Review Moments → Decision Card → Calibration Lab
```
- Match 页第一屏 = Focus Player selector（不假设 owner）+ Overview + Top 5 Moments。
- **Moment first, metrics second**（§7）：detector 计数（PREAIM 2509 等）移到
  Decisions/Advanced，不在首页。
- Decision Card（§41）：ROUND / WHY YOU FOUGHT / HOW YOU FOUGHT / HOW YOU EXECUTED /
  Main issue / Evidence（LOW 弱化显示）。
- Calibration Lab（PART D §20-§22）：单场景 Yes/No/Unsure + FP 原因分类；
  校准统计表（detector/reviewed/confirmed/precision/state）。

## 6. Cross-Match PlayerProfile（PART H）

- `player_profiles` 表 + `/api/players/{sid}/matches`（match_count + 场次 episodes）。
- **趋势仅多场 + 足够校准证据时显示**（§38-§39）；单场 → "Not enough matches"。
  本阶段为基础结构，不承诺职业系统。

## 7. Pro Reference 兼容（PART K）

- ReferenceCorpusProvider / DecisionSampleProvider / ReferencePolicyProvider
  原样保留；PlayerProfile/UI 不破坏接口（`focus.py` 与 `reference.py` 无耦合）。

## 8. 已知 UX 局限（诚实）

1. **无 2D replay viewer**：Review 定位到 round/tick/事件上下文，无视频；
   完整 viewer 明确不做（PART O）。
2. **Focus Player 持久化粒度为全局**（remembered user 是所有 match 的默认）；
   无 per-match focus 记忆（刷新后需重选）——app_preferences 表已留接口。
3. **Overview 的 needs_review 阈值**（good_share < 0.4）是启发式，未校准。
4. **positive/negative 槽位比例**（4+1）硬编码；未来按数据调。
5. steam_id 字符串化解决了精度，但 `parseInt` 已在 UI 层移除 —— 需确保未来
   前端代码不再把 steam_id 转 number（测试 `test_remember_player_default_focus`
   断言 string 类型防回归）。

## 9. Screenshot 说明

Calibration Lab 渲染验证（真实数据）：detector 统计表 + 单场景 review 卡 +
GROUND_TRUTH_PENDING_HUMAN_REVIEW 标注。Match 页验证：de_dust2 18 rounds +
10 玩家 selector + Top 5 Moments（4 improvement + 1 good）。
