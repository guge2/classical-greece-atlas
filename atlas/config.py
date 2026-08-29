"""全局路径、页面几何、配色与字体规格。"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
DERIVED = DATA / "derived"
CACHE = ROOT / "cache"
BUILD = ROOT / "build"
QA = BUILD / "qa"
PDF_OUTPUT = ROOT / "output" / "pdf"

PLACES_SEED = DATA / "places_seed.csv"
PLACES = DATA / "places.csv"
MAP_PLACES = DATA / "map_places.csv"
MAPS_YAML = DATA / "maps.yaml"
SOURCES_JSON = DATA / "sources.json"

# ---------------------------------------------------------------- 页面几何（毫米）
PAGE_W_MM = 420.0          # A3 横向
PAGE_H_MM = 297.0
MARGIN_MM = 16.0

# 地图满版铺开：图廓即页面，标题与比例尺压在图上的空白处
FRAME_X_MM = 0.0
FRAME_Y_MM = 0.0
FRAME_W_MM = PAGE_W_MM
FRAME_H_MM = PAGE_H_MM

SAFE_MM = 10.0             # 页面四边的文字安全边距
LABEL_EDGE_MM = 5.0        # 地点标签允许贴近页边的最小距离
FOOTER_Y_MM = 290.0        # 来源说明基线

# ---------------------------------------------------------------- 配色
PAPER = "#F4EFE3"
SEA = "#CAD7D8"
LAND = "#E9E1CF"
STRUCTURE = "#4D5551"      # 海岸与结构线
PLACE_ACCENT = "#844B3D"   # 地点强调色
TEXT = "#2F3532"           # 正文
REGION_TEXT = "#6E6A60"    # 地区名
SEA_TEXT = "#61777B"       # 海域名
ATHENIAN_HATCH = "#567984" # 雅典同盟：横纹
SPARTAN_HATCH = "#875547"  # 斯巴达同盟：竖纹

# ---------------------------------------------------------------- 线宽（毫米）
LW_COASTLINE = 0.20
LW_COASTLINE_MINOR = 0.14
LW_FRAME = 0.35
LW_SCALEBAR = 0.30
LW_MARKER = 0.22
LW_HATCH = 0.22

# ---------------------------------------------------------------- 字号（磅）
PT_TITLE = 22.0
PT_SUBTITLE = 10.0
PT_REGION = 11.0
PT_SEA = 10.0
PT_PLACE_MAJOR = 9.0
PT_PLACE_MINOR = 7.5
PT_SCALE = 7.0
PT_SOURCE = 5.5
PT_LEGEND = 7.5

PT_TO_MM = 25.4 / 72.0

# ---------------------------------------------------------------- 字体
FONT_DIR_SYSTEM = Path("C:/Windows/Fonts")
FONT_CACHE = CACHE / "fonts"
FONT_SPECS = {
    # 逻辑名 -> (源文件, 可变字体轴实例)
    "serif": ("NotoSerifSC-VF.ttf", {"wght": 400}),
    "serif-medium": ("NotoSerifSC-VF.ttf", {"wght": 500}),
    "serif-semibold": ("NotoSerifSC-VF.ttf", {"wght": 600}),
    "sans": ("NotoSansSC-VF.ttf", {"wght": 400}),
    "sans-medium": ("NotoSansSC-VF.ttf", {"wght": 500}),
}

# ---------------------------------------------------------------- PDF 栅格与输出体积
# 地形是整份 PDF 中唯一的大面积栅格层；72 dpi 足以承载低透明度阴影，
# 海岸线、纹理、标记与文字仍保持矢量，因此打印时不会一并变糊。
PDF_IMAGE_DPI = 72

MAX_SVG_BYTES = 2_500_000
MAX_PDF_BYTES = 4_000_000   # 五页轻量版；超过即由严格校验阻止交付
TERRAIN_MAX_PX = 1800
TERRAIN_OPACITY = 0.12

FOOTER_NOTE = "海岸轮廓经概化，未重建古代岸线，不表示政区边界。"
