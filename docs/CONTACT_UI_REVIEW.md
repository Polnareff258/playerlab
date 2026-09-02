# CONTACT_UI_REVIEW.md — Contact Review / Decision Card UX（V1.3.4.1 PART L/M/N/O/V）

## 新增 Contact Review 页（PART L §37-§38）

顶部导航新增 **Contact** tab。每张卡只显示一个接敌片段，回答 **3 个问题**：

| Q | 问题 | 选项 |
| --- | --- | --- |
| Q1 | 谁主动建立了这次接敌？ | 你主动拉出 / 对手主动拉出 / 双方同时 / 静态·环境 / 没有真接敌 / Unsure |
| Q2 | 你当时在做什么？ | Peek / Hold / 小幅调整架枪 / Re-peek / Reposition / Other / Unsure |
| Q3 | 当时有什么支援？ | 自身道具 / 队友道具 / 队友协同施压 / 保持隐蔽·Timing / 无 / Unsure |

**交互规则**：
- 回答任意问题只重渲染当前卡片（其他卡片不受影响，答案保留）
- 三个问题**全部回答后**「确认提交」才可用 → 提交后该样本从队列移除
- 系统预测行（initiator / action / subtype）以**可读中文**展示，非原始枚举/JSON
- **Advanced** 折叠区才显示技术字段：双方 displacement / mean·peak speed /
  yawΔ / visibility_tick / sight_state / possible_visibility_tick

## Decision Card（PART M §39）

Contact/Decision 卡顶层展示语义化的三段式（不再让用户读 JSON）：

```
CONTACT
对手主动拉出                    ← initiator
你的应对：Hold                  ← action + subtype
支援：队友道具                  ← support
```

绕后场景额外显示战术上下文（STEALTH_PRESERVING → "Likely preserving surprise"，
**绝不**宣称 "Enemy does not know you are here"）。

## Confidence UI（§40）

- 默认显示 **High / Medium / Low**（0.66+ / 0.4-0.66 / <0.4），不显示 0.61342
- Advanced 区才显示 raw probability
- AMBIGUOUS 显示 "Peek / Hold 难以区分"，UNKNOWN 显示 "信息不足，暂不判断"

## Why 解释（PART N §41）

每张 Contact 卡带一句来自 evidence 的解释，例如：

- `判为架枪：接敌前 0.8u 位移 / 均速 2，敌方发生主要位移（114u / 均速 142）`
- `判为主动 Peek：你在 LOS 建立前发生 96u 位移（均速 200），对手基本保持静止`
- `判为主动 Re-peek：你在同一角度再次建立接敌（…）`
- `双方同时移动接敌（MUTUAL），无法可靠归因主动方`
- `双方基本静止（烟雾/掩体/几何转换），非主动暴露`
- `证据不足，暂不判断`

解释**来自 motion evidence 的实测数字**，不是模板套话。

## 内部 enum ↔ 中文（PART V §57）

| 内部 | UI |
| --- | --- |
| SELF_INITIATED | 你主动建立接敌 |
| ENEMY_INITIATED | 对手主动拉出 |
| MICROADJUST_HOLD | 小幅调整架枪 |
| TEAM_UTILITY_ASSISTED | 队友道具支援 |
| STEALTH_PRESERVING | 保持隐蔽 / Timing |
| UNKNOWN | 信息不足，暂不判断 |

## Debug / Timeline（PART O §42-§43）

Contact 卡 Advanced 提供 motion 摘要；visibility_tick / first_shot_tick /
first_damage_tick 已写入样本的 contact_window 供回放核对。
（完整 debug timeline 视图计划在真实 regression 数据就绪后补充。）
