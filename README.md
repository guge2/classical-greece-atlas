# 古典希腊中文静态地图集

面向公元前五世纪古典希腊地理的静态制图工程：五幅 A3 横向地图（420×297 mm）与一份五页合并 PDF，全部由 Python 可重复生成。工程不含网页应用、时间轴或交互界面。

## 成品

| 文件 | 内容 | 比例尺 |
| --- | --- | --- |
| `build/01-overview.svg` | 古典希腊世界总览 | 约 1:3 627 000 |
| `build/02-mainland.svg` | 希腊本土与伯罗奔尼撒 | 约 1:1 206 000 |
| `build/03-aegean-asia-minor.svg` | 北爱琴海与小亚细亚西岸 | 约 1:1 917 000 |
| `build/04-sicily-magna-graecia.svg` | 西西里与大希腊 | 约 1:1 666 000 |
| `build/05-power-blocs.svg` | 伯罗奔尼撒战争初期势力图（横纹／竖纹） | 约 1:2 426 000 |
| `output/pdf/classical-greece-atlas.pdf` | 五页轻量合并版，便于传输与打印 | — |

SVG 自包含（字形转为路径、地形以 data URI 内嵌），无任何远程资源；PDF 嵌入字体子集。PDF 将低透明度地形控制在 72 dpi，海岸、文字、地点和势力纹理全部保留为矢量，五页成品约 3.06 MB。构建时还会尽量同步一份兼容副本到 `build/classical-greece-atlas.pdf`。

## 环境与命令

需要 Python 3.12 与 [`uv`](https://docs.astral.sh/uv/)，以及系统已安装的 **Noto Serif SC** 与 **Noto Sans SC**（工程从 `C:/Windows/Fonts` 读取可变字体并实例化为静态字重）。

```bash
uv sync
```

三个稳定命令：

```bash
uv run python -m atlas.fetch          # 下载、校验、裁剪并本地化资源（唯一需要联网的一步）
```

```bash
uv run python -m atlas.build --all    # 离线生成五幅 SVG 与合并 PDF
```

```bash
uv run python -m atlas.check --render # 校验数据、标签冲突、输出尺寸与体积，并输出 QA 图
```

`fetch` 会把下载物放进 `cache/`（已在 `.gitignore` 中），并把裁剪后的小体积成果写入 `data/derived/`。首次 `fetch` 完成后，`build` 与 `check` 完全离线运行。

辅助脚本（不属于工程依赖）：

```bash
uv run --with pypdfium2 python scripts/render_pdf_qa.py   # 把合并 PDF 逐页渲染为 300 dpi PNG
```

## 目录结构

```
atlas/            制图工程本体
  config.py       页面几何、配色、字号、体积上限
  sources.py      外部数据源登记（URL、许可证、署名）
  fetch.py        下载 → 校验 → 裁剪 → 地形重投影 → 生成地点表
  mapspec.py      maps.yaml / places.csv / map_places.csv 读取
  projection.py   每图独立的兰勃特等角圆锥投影与页面毫米坐标换算
  geometry.py     海岸投影、概化、命名岛屿保留
  labels.py       八方位无碰撞标签排版
  fonts.py        可变字体实例化、文字度量、可复用字形路径
  scene.py        与输出格式无关的页面场景
  svgout.py       SVG 后端（文字转字形路径）
  pdfout.py       PDF / PNG 后端（matplotlib，嵌入字体子集）
  build.py        构建入口
  check.py        校验入口
data/
  places_seed.csv 人工审定的地名种子表（唯一需要手工编辑的地名源）
  places.csv      由 fetch 生成：种子表 + Pleiades 坐标 + Wikidata 关联
  map_places.csv  每图的地点、重要级别、标记类型、标签锚点与毫米偏移
  maps.yaml       五图标题、范围、投影参数、比例尺、注记、地形与势力纹理配置
  sources.json    来源、许可证、校验值与获取时间
  derived/        裁剪后的海岸 GeoJSON、地形切片、Wikidata 比对报告
docs/             来源与许可证说明、构建与验收报告
scripts/          开发与核查辅助脚本（含 refit_annotations.py：把越界注记移回框内）
output/pdf/       正式发布的轻量合并 PDF
```

## 数据接口

- **`places_seed.csv`**：`id`、中文主名、中文别名、古代名（希腊文）、拉丁名、Pleiades ID、地点类型、备注。中文名经人工逐条审定，`fetch` 不会覆盖。
- **`places.csv`**（生成物）：在种子表基础上补入 Pleiades 官方坐标、地名标题、坐标置信度、来源串与 Wikidata QID。
- **`map_places.csv`**：`map_id, place_id, rank, marker, anchor, dx_mm, dy_mm`。`rank` 为 1（主要）或 2（普通）；`marker` 取 `city / sanctuary / island / pass`；`anchor` 留空表示自动排版，填入 `E/NE/SE/W/NW/SW/N/S` 则为显式覆写，可再叠加毫米偏移。现有五图共 169 个图内标记，来自 114 个可追溯地点。
- **`maps.yaml`**：每图的 `fit`（`content` 表示画幅按本图实际内容收紧，`extent` 表示按配置范围）、`content_margin_mm`（内容四周留白毫米数）、`extent`（`fit: extent` 时的经纬度范围）、`projection`（`lon_0/lat_0/lat_1/lat_2`，省略则由成图内容推导）、`title_block`（`corner` 取 `NW/NE/SW/SE`，可叠加 `dx_mm/dy_mm`）、`simplify_km`、`scalebar_km`、`min_island_km2`、`terrain`（`enabled/opacity/max_px`）、`regions`、`seas`。注记可用 `over: land|sea|any` 声明预期落位，供 `check` 审计。势力图另用 `faction_areas` 定义联盟示意面：`athenian` 输出横纹、`spartan` 输出竖纹、`neutral` 从两方纹理中扣除。

## 排版与校验规则

- 页面固定为 A3 横向，**地图满版铺开、图廓即页面**：没有页边留白与文字栏，标题、副标题、比例尺合成一块压在图上的空白角落（位置由 `maps.yaml` 的 `title_block.corner` 指定），来源说明与概化说明压在页面最下方一行。所有文字保持 10 mm 的安全边距，地点标签至少距页边 5 mm。
- **画幅按内容收紧**（`fit: content`）：成图范围由本图实际画出的地点标记与势力范围决定，四周留 `content_margin_mm` 的空隙，再按页面宽高比居中扩展。地区名与海域名**不参与定框**——它们本来就摆在空白海面上，若参与定框会反过来把画幅撑大（实测会让主体缩小 15%–28%）。注记必须落在成图范围内，越界由 `atlas.check` 报错；`scripts/refit_annotations.py` 可把越界注记就近移回框内并写回 `maps.yaml`。
- 每图范围在投影平面上按页面宽高比（1.414）居中扩展，因此不产生变形，实际成图范围不小于配置范围。
- 标签按重要级别排序，依次尝试东、东北、东南、西、西北、西南、北、南八个方位；任一标签八方位均无解时**构建直接失败**，并提示在 `map_places.csv` 中显式覆写——不存在随机排版。
- 地区名与海域名位置固定；若压住地点符号，构建同样失败，提示在 `maps.yaml` 中调整经纬度。
- `check` 复算全部文字包围盒，确认无文字—文字、文字—符号重叠且不越界；同时校验 SVG 为合法 XML、尺寸为 420×297 mm、自包含、体积不超过 2.5 MB，五页 PDF 不超过 4 MB 且含嵌入字体子集。

## 已知取舍

- 海岸概化容差按 `maps.yaml` 配置（总览 3.26 km、区域图 0.76–1.21 km、势力图 1.53 km，均相当于打印后约 0.63–0.9 mm 的最大偏移）；小面另按自身尺度收紧，避免命名岛屿被概化成三角形。若需要更精细的海岸，调小 `simplify_km` 即可。
- 德洛斯与斯法克特里亚的面积低于 Natural Earth 1:10m 的最小岛屿，底图中没有对应多边形，二者以点符号加名称表示。
- 锡巴里斯与图里伊在 Pleiades 中同属一处遗址（452457），因此合为一个标记，标签作「锡巴里斯／图里伊」。
- 灰度打印时陆地与海面明度接近，二者的区分主要依赖海岸线；配色按规格固定。
- 势力图依据修昔底德《伯罗奔尼撒战争史》2.9 的战争初期盟友名单绘制。纹理面是联盟归属的示意范围，不是精确政区边界；阿尔戈斯、阿开亚大部、米洛斯与锡拉以留白表示中立。

## 数据来源

底图与古代地点的来源、署名要求见 [`docs/来源与许可证.md`](docs/来源与许可证.md) 与 `data/sources.json`。
