# MANUAL_ASSET_SETUP.md — Geometry 地图资产设置（V1.3.3 PART H）

> **背景**：CS2 的 `.nav`（导航网格）与 `.tri`（可见性三角形）资产体积大、
> 来源分散，且随 CS2 更新变化。PlayerLab 的 `scripts/setup_geometry_assets.py`
> 会**自动尝试获取**资产；仅当自动获取失败（无本地 CS2、镜像不可达）时才需要
> 手动放置。资产 metadata 由脚本写入 `manifest.json`（§24）保证可复现。

---

## 1. 自动获取（推荐，脚本自动完成）

`start.bat` 启动时自动运行；也可手动执行：

```powershell
# 检查哪些图缺资产
python scripts\setup_geometry_assets.py --check

# 自动获取（按优先级）：
#   1) 本地 CS2 安装目录的 .nav（游戏自带，版本正确）
#   2) awpy 镜像 https://awpycs.com/{patch}/navs.zip + tris.zip
python scripts\setup_geometry_assets.py --auto
```

自动获取失败时脚本会打印手动指引，且 PlayerLab **仍可正常打开**——
几何查询优雅降级为 `unknown`（NullGeometry，§32）。

## 2. 需要什么（手动方案）

| 资产 | 用途 | 来源建议 | 大小 |
| --- | --- | --- | --- |
| `<map>.nav` | nav distance / path（`NavMesh.from_path`） | CS2 游戏目录 `game/csgo/maps/` | 1-3MB |
| `<map>.tri` | LOS raycast / cover（`read_tri_file`） | `pip install awpy && awpy get tris` | ~20MB/图 |

需要的图：`de_dust2`、`de_mirage`（A/B 实验 PART I §25）。

## 3. 放置位置

```
data/maps/
├── de_dust2.nav
├── de_dust2.tri
├── de_mirage.nav
├── de_mirage.tri
└── manifest.json      # 资产 metadata（setup 脚本写入）
```

`data/` 已在 `.gitignore` —— **资产绝不进 git**（§23）。

## 4. 注册资产（手动方式）

```powershell
# 先把 .nav / .tri 拷贝到 data/maps/
python scripts\setup_geometry_assets.py --map de_dust2 --nav data\maps\de_dust2.nav --tri data\maps\de_dust2.tri --source manual
python scripts\setup_geometry_assets.py --map de_mirage --nav data\maps\de_mirage.nav --tri data\maps\de_mirage.tri --source manual
python scripts\setup_geometry_assets.py --list-known
```

`manifest.json` 记录：`map_name / asset_version / source / file_hash / game_build /
created_at` —— CS2 更新后地图变化导致结果无法复现时可对照哈希排查。

## 5. 启用 Geometry

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

## 6. 验证

```powershell
python scripts\setup_geometry_assets.py --check
# 期望 [OK] de_dust2: nav=Y tri=Y registered=True 等
```
