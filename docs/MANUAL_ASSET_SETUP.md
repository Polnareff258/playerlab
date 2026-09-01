# MANUAL_ASSET_SETUP.md — Geometry 地图资产手动设置（V1.3.3 PART H）

> **为什么手动**：CS2 的 `.nav`（导航网格）与 `.vphys`（碰撞网格，KV3 格式）资产
> 体积大（每图 50-120MB）、来源分散（社区/游戏安装目录）、且随 CS2 更新变化。
> 自动下载存在版权/来源/稳定性问题 → 本版本**不硬做自动下载**（PART H §23），
> 提供手动设置 + 资产 metadata 记录（§24）保证可复现。

---

## 1. 需要什么

| 资产 | 用途 | 来源建议 | 大小 |
| --- | --- | --- | --- |
| `<map>.nav` | nav distance / path（`NavMesh.from_path`） | CS2 游戏安装目录 `csgo/maps/` 或社区 nav 资产包 | 1-3MB |
| `<map>.vphys` | LOS raycast / cover（`read_tri_file`） | cs2-map-parser 社区导出 / awpy 文档链接 | 50-120MB |

当前需要的图：`de_dust2`、`de_mirage`（A/B 实验 PART I §25）。

## 2. 放置位置

```
data/maps/
├── de_dust2.nav
├── de_dust2.vphys
├── de_mirage.nav
├── de_mirage.vphys
└── manifest.json      # 资产 metadata（setup 脚本写入）
```

`data/` 已在 `.gitignore` —— **资产绝不进 git**（§23）。

## 3. 注册资产（记录 metadata，§24）

```powershell
# 先把 .nav / .vphys 拷贝到 data/maps/
python scripts\setup_geometry_assets.py --map de_dust2 --nav data\maps\de_dust2.nav --vphys data\maps\de_dust2.vphys --source manual
python scripts\setup_geometry_assets.py --map de_mirage --nav data\maps\de_mirage.nav --vphys data\maps\de_mirage.vphys --source manual
python scripts\setup_geometry_assets.py --list-known
```

`manifest.json` 记录：`map_name / asset_version / source / file_hash / game_build /
created_at` —— CS2 更新后地图变化导致结果无法复现时可对照哈希排查。

## 4. 启用 Geometry

```json
// config/model_intelligence.json（或新建 config/geometry.json）
{
  "geometry_provider": "awpy",
  "geometry_nav_dir": "data/maps",
  "geometry_tri_dir": "data/maps"
}
```

启用后：
- `AwpyGeometryProvider` 懒加载资产；**缺失 → 全部返回 None，graceful fallback**（§32）。
- EvidenceSufficiency 的几何加分项生效（部分 MEDIUM → HIGH）。
- 可跑 `python -m playerlab.cli geometry-ab <demo.dem>` 做 OFF/ON 对照（PART I）。

## 5. 验证

```python
from playerlab.geometry import get_geometry
g = get_geometry("awpy", nav_dir="data/maps", tri_dir="data/maps")
print(g.get_metadata())          # source=awpy, quality=approximate
print(g.can_see("de_dust2", (0, 0, 0), (1000, 1000, 0)))   # True/False/None
print(g.nav_distance("de_dust2", (0, 0, 0), (1000, 0, 0)))  # float/None
```

## 6. 诚实规则

- **无资产 → `GEOMETRY_AB_PENDING_ASSETS`**（PART V）：A/B 实验报告如实输出
  `geometry_quality="none"`，不伪造 experiment。
- **awpy `is_visible` 是纯几何**（不含烟雾/闪光遮挡）→ metadata
  `geometry_quality="approximate"`，不标 exact（§33）。
- 资产未就绪时 PlayerLab 全部功能正常（NullGeometryProvider 兜底）。
