# CONTACT_INITIATION_FIX.md — 为什么 LOS transition 不能决定 initiator（V1.3.4.1 PART A）

> 核心规则（Final Principle）：
>
> ```
> LOS transition ≠ Contact initiator
> Movement       ≠ Peek
> No self utility ≠ Dry peek
> No utility     ≠ Bad decision
> Unknown        ≠ Need to guess
> ```

## 1. 问题

V1.3.4 的 `ExposureRelation` 用同一个 LOS 查询构造 `self_can_see_enemy` 与
`enemy_can_see_self`（几何 LOS 是**对称**关系，不携带视角方向）。两条 exposure
状态因此几乎**同一 tick 翻转**：

```
self:  COVERED → EXPOSED
enemy: COVERED → EXPOSED     （同一个几何查询的结果）
```

旧 `_initiation` 直接比较双方 transition tick：

```python
if self_t is not None and enemy_t is not None and abs(self_t - enemy_t) <= 2:
    return "MUTUAL"
```

当双方 transition tick 相同（几何对称导致的必然结果）时，结果恒为 MUTUAL ——
这无法区分：

```
我稳定架枪 + 敌人主动走出来
```

与：

```
我主动拉出去 + 敌人原地架枪
```

**LOS becoming available 是共同事件（shared event），不是 initiator 的信号。**

## 2. 修复：InitiationMotionEvidence（motion-based initiation）

visibility transition 是共同事件；真正要问的是：

> **Which player's motion caused the pairwise LOS transition?**

`contact_semantics.py` 新增 `InitiationMotionEvidence`，在接敌前的 motion
window（`cfg.initiation_motion_window_ticks`，默认 32 ticks ≈ 500ms，规格建议
300–800ms）内测量双方：

```
window_start / transition_tick
self_displacement / enemy_displacement
self_mean_speed / enemy_mean_speed
self_peak_speed / enemy_peak_speed
self_outward_motion / enemy_outward_motion   # 朝向 exposure boundary
self_stability / enemy_stability             # 位置 + yaw 稳定度
self_yaw_change / enemy_yaw_change           # circular |deg|
confidence
```

`classify_initiation_v2` 只依赖 motion，**绝不比较 transition tick**：

| 判据 | 结果 |
| --- | --- |
| 双方均低速稳定 | `STATIC_CONTACT`（烟雾消散/门/几何变化） |
| 一方明显移动、另一方稳定 | `SELF_INITIATED` / `ENEMY_INITIATED` |
| 双方都有意义移动且比值 ≥ `mutual_motion_ratio` | `MUTUAL` |
| 其他 / 证据不足 | `UNKNOWN` |

## 3. 被禁止的判据

- `self_transition_tick == enemy_transition_tick → MUTUAL`：**已删除**。回归
  测试 `test_transition_tick_equality_no_longer_implies_mutual` 用相同的
  transition tick + self 稳定 / enemy 移动，断言结果为 `ENEMY_INITIATED`。

## 4. 正确顺序

接敌分类必须按序执行，不能反过来：

```
What became visible?   -> visibility scan（geometry LOS transition）
Who caused it?         -> motion-based initiation（v2）
What action happened?  -> hold / peek / re-peek correctness（都要求正确 initiator）
What support/context?  -> SupportContext / StealthContext（PART G/H）
How confident?         -> 诚实 UNKNOWN / AMBIGUOUS（PART J）
Was it reasonable?     -> evaluation（downstream）
```

## 5. 附带修正

- **visibility_tick 真正填充**（PART C）：扫描 pre-contact 窗口的 geometry
  LOS `NOT_VISIBLE → VISIBLE` 首次转换；geometry 缺失时只记录
  `possible_visibility_tick`（FOV-only），**从不冒充真实 visibility**。
- **HoldStability v2**（PART D）：yaw_variance 用 **circular angular
  difference**（179°→-179° ≈ 2° 而非 358°）；`lane_stability` 加入稳定性；
  小幅 AD 分类为 `MICROADJUST_HOLD`，短 reposition 保 lane 为 `ACTIVE_HOLD`，
  两者都不得被读作 PEEK。
- **PEEK v2**（PART E）：只有 `SELF_INITIATED` + LOS gain + self motion
  与 transition 重叠 + enemy 相对稳定才判 PEEK；"接敌前移动过"不再足以判
  PEEK。
- **Re-Peek v2**（PART F）：要求 `EXPOSED → COVERED → SELF_INITIATED` 再次
  暴露，且 yaw/位置相似（`re_peek_same_angle_deg`），不再只用 yaw 一个维度。
- **UNKNOWN / AMBIGUOUS 传播**（PART J）：证据不足输出 UNKNOWN（合法结果），
  PEEK/HOLD 接近时输出 `Ambiguous: Peek / Hold`（`ambiguous_labels`），
  ObservedAction=UNKNOWN 不得进入 PEEK-specific 检测/训练目标。
