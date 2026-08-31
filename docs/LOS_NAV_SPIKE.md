# LOS_NAV_SPIKE.md — Phase C：LOS / Nav / Cover 可行性研究

> 目标（spec §9-§10）：在自己实现 LOS/nav 之前，先检查现有成熟方案；
> 回答 10 个问题；输出复用 or 明确 UNKNOWN 的集成决策。
> 研究日期：2026-08-31（仓库快照经 gh api 核实）。

---

## 1. 候选项目清单

| 项目 | 仓库 | License | 活跃度 | 相关能力 |
| --- | --- | --- | --- | --- |
| **awpy** | pnxenopoulos/awpy | MIT | ★★★（610★，2026-08 仍在更新） | `awpy.nav.NavMesh`（.nav 解析 + A* find_path）+ `awpy.visibility`（VPhys KV3 → 三角网格 → BVH → `is_visible`） |
| DAK Studio / DAK packages | leon-wolf/DAK-Studio | 闭源/部分开源 | ★★★ | 分析 substrate；nav 能力不对外提供 Python API 复用 |
| Freezetime | ashe-rafi/freezetime | MIT | ★★ | demoparser2 生态；事件级分析，无 nav 几何 |
| demoparser2 | LaihoE/demoparser2 | MIT | ★★★ | Rust 解析核心；**不含** nav/geometry（明确：解析层≠几何层） |
| cs2-map-parser | AtomicBool/cs2-map-parser | MIT | ★★ | CS2 地图碰撞网格解析（awpy visibility 的底层参考实现） |

**结论**：唯一同时提供「nav distance + point-to-point visibility raycast」且 MIT 可复用的是 **awpy**（nav.py + visibility.py 两模块）。DAK 闭源不可复用；demoparser2 明确不含几何。

## 2. 十个问题的答案

### Q1 哪个项目能提供 nav data？
**awpy**：`awpy.nav.NavMesh.from_path("de_dust2.nav")` 解析 Source 2 nav 文件（BinaryIO 读取 areas/connections/polygons），`NavMesh.find_path(start_id, end_id)` 返回 A* 最短路径。地图资产（.nav 文件）可从 CS2 安装目录或社区资产包获取（CS2 nav 文件约 1-3MB/图）。

### Q2 是否有 point-to-point visibility？
**awpy.visibility**：`read_tri_file` 读取 VPhys 碰撞网格（KV3 解析，参考 cs2-map-parser），构建 BVH（`_build_bvh`），`is_visible(point_a, point_b)` 沿线段做 ray-triangle 求交。CS2 每图 VPhys 资产（de_dust2 约 50-120MB .vphys 网格）。

### Q3 是否能 raycast？
是。`Triangle`/`AABB`/BVH 全在 awpy.visibility；`intersects_ray` 返回首个命中三角形。LOS 判定 = `is_visible(a, b)`（线段与碰撞网格无交点）。

### Q4 是否能得到 nav distance？
是。`NavMesh.find_path(start_id, end_id, weight="distance")` 返回路径 area 序列与总距离。需要先把世界坐标投影到最近 nav area（awpy 提供 `NavMesh.find_closest_area` 类接口——V1 实现需自行写 pos→area 最近匹配，O(areas) 线性或 KD 树）。

### Q5 性能如何？
- nav 解析：一次性 ~1-3s/图（.nav 小文件）。
- find_path：A*，单查询 <1ms（数千 area 图）。
- visibility：BVH 构建一次性 ~5-15s/图（VPhys 网格大）；单次 `is_visible` 查询 ~0.05-0.5ms（BVH 剪枝）。
- 实测参考：awpy 官方 visibility notebook 单 demo 全 tick LOS 批处理在秒级。

### Q6 地图支持范围？
awpy 官方支持 de_dust2 / de_mirage / de_inferno / de_overpass / de_nuke / de_ancient / de_vertigo / de_anubis 等主流竞技图（需要对应 .nav + .vphys 资产）。非主流图需自备资产。

### Q7 数据文件大小？
- .nav：1-3MB/图（文本二进制混合）。
- .vphys（碰撞网格）：de_dust2 约 50-120MB/图（KV3 含字节数组）。
- 合计每图 ~100MB 级资产目录。

### Q8 集成复杂度？
中等：
1. `pip install awpy`（依赖 numpy/pandas/loguru；**不含** torch——轻量）；
2. 资产目录约定：`data/nav/<map>.nav` + `data/vphys/<map>.vphys`；
3. 封装 `TradeabilityGeometry` 适配器（tradeability.py 已定义接口：direct_los / nav_distance / intervening_cover）；
4. 无资产时 `NULL_GEOMETRY` 自动降级（已有），不伪造精度。
复杂度集中在「资产获取」而非代码——CS2 更新会改变 nav 版本，需随版本锁定资产。

### Q9 license？
awpy = **MIT**（visibility/nav 模块均可商用/自由复用）。cs2-map-parser = MIT（仅作参考，不直接依赖）。

### Q10 是否适合离线 Demo 批处理？
适合。资产静态、解析一次性、查询微秒级；批处理管线（`batch.py`）在 context 阶段调用 `compute_tradeability(..., geometry=awpy_geometry)` 即可，无运行时网络依赖。**需要**：先把资产目录纳入 `.gitignore`（不提交 100MB 级网格）。

## 3. 集成决策（本阶段）

| 能力 | V1.2 现状 | V1.2.1 决策 |
| --- | --- | --- |
| nav_distance | ❌ 无 | **awpy NavMesh 适配器（Phase C2 可选）**；未安装/无资产 → None → Tradeability UNKNOWN |
| direct_los | ❌ 无 | **awpy visibility 适配器**；同上降级 |
| intervening_cover | ❌ 无 | 近似：LOS 为 False 且遮挡面数 >0 → cover；无网格 → None |
| response_time | ❌ 无 | 规则近似：nav_distance/移动速度 + 反应时间（tradeability.py 已实现） |

**本阶段落点**：`tradeability.py` 已按「无几何即 UNKNOWN」实现完整字段 + 分类；
`TradeabilityGeometry` 接口已定义；awpy 适配器作为可选模块（`geometry_awpy.py`）
在资产可用时注入，核心不依赖。**验收 §74-B**（远队友但可补枪 → 不判 isolated）
由 tradeability 的 classification 承担——即使 LOS 为 None，距离 + 响应时间 +
commitment 约束也禁止仅凭距离下 isolated 结论。

## 4. 未纳入（诚实披露）

- 未在本阶段下载地图资产（100MB 级）与安装 awpy（避免核心依赖膨胀，spec §61）；
- nav 的 `place→area` 投影未实现（需资产后验证最近 area 匹配质量）；
- cover 无标准定义（网格法线/遮挡计数为近似）——记为 LIMITATION。

## 5. 后续接入路径（Phase C2，非本阶段）

```python
# geometry_awpy.py（未来模块草图）
from awpy.nav import NavMesh
from awpy.visibility import read_tri_file, is_visible

class AwpyGeometry(TradeabilityGeometry):
    def __init__(self, nav_path, tri_path):
        self.nav = NavMesh.from_path(nav_path)
        self.tri = read_tri_file(tri_path)
    def nav_distance(self, map_name, a, b):
        a_id = self.nav.find_closest_area(a); b_id = self.nav.find_closest_area(b)
        return self.nav.find_path(a_id, b_id).distance
    def direct_los(self, map_name, a, b):
        return is_visible(self.tri, Vector3(*a), Vector3(*b))
```
