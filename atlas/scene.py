"""页面场景：把地理数据与配置组装成与输出格式无关的绘图指令。

场景中所有坐标均为 A3 页面毫米坐标，y 轴向下。SVG 与 PDF 两个后端共用同一场景，
因此两种输出的版面完全一致。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from . import config as C
from . import fonts as F
from .geometry import load_land
from .labels import Box, LabelPlanner


# --------------------------------------------------------------------- 绘图元素
@dataclass
class Rect:
    x: float
    y: float
    w: float
    h: float
    fill: str = "none"
    stroke: str = "none"
    stroke_w: float = 0.0


@dataclass
class Polys:
    """一组多边形（含内环），统一填色与描边。"""
    rings: list                      # [(exterior ndarray, [hole ndarray, ...]), ...]
    fill: str = "none"
    stroke: str = "none"
    stroke_w: float = 0.0
    clip: str = "frame"


@dataclass
class Image:
    path: Path
    x: float
    y: float
    w: float
    h: float
    opacity: float = 1.0
    clip: str = "land"


@dataclass
class Circle:
    cx: float
    cy: float
    r: float
    fill: str = "none"
    stroke: str = "none"
    stroke_w: float = 0.0


@dataclass
class Polyline:
    points: list
    stroke: str = C.STRUCTURE
    stroke_w: float = 0.2
    fill: str = "none"
    close: bool = False


@dataclass
class Text:
    text: str
    x: float
    baseline: float
    font_key: str
    size_pt: float
    color: str
    align: str = "start"             # start | middle | end
    tracking_em: float = 0.0
    halo_mm: float = 0.0
    clip: str = ""


@dataclass
class Scene:
    spec: object
    layers: list = field(default_factory=list)
    land_rings: list = field(default_factory=list)
    label_boxes: list = field(default_factory=list)
    fixed_boxes: list = field(default_factory=list)
    marker_boxes: list = field(default_factory=list)
    notes: list = field(default_factory=list)

    def add(self, item):
        self.layers.append(item)
        return item


# --------------------------------------------------------------------- 标记符号
def marker_radius(rank: int) -> float:
    return 1.05 if rank == 1 else 0.78


def marker_items(kind: str, rank: int, x: float, y: float) -> list:
    r = marker_radius(rank)
    accent, paper = C.PLACE_ACCENT, C.PAPER
    if kind == "sanctuary":
        d = r * 1.15
        pts = [(x, y - d), (x + d, y), (x, y + d), (x - d, y)]
        return [Polyline(pts, stroke=accent, stroke_w=C.LW_MARKER,
                         fill=accent if rank == 1 else paper, close=True)]
    if kind == "pass":
        d = r * 1.25
        pts = [(x - d, y + d * 0.8), (x, y - d), (x + d, y + d * 0.8)]
        return [Polyline(pts, stroke=accent, stroke_w=C.LW_MARKER, fill=paper, close=True)]
    if kind == "island":
        return [Circle(x, y, r * 0.72, fill="none", stroke=C.STRUCTURE, stroke_w=C.LW_MARKER)]
    if rank == 1:
        return [Circle(x, y, r, fill=accent, stroke=accent, stroke_w=C.LW_MARKER)]
    return [Circle(x, y, r, fill=paper, stroke=accent, stroke_w=C.LW_MARKER)]


# --------------------------------------------------------------------- 场景组装
def compose(spec, places: dict, map_places: list, book: F.FontBook) -> Scene:
    frame = spec.frame
    scene = Scene(spec=spec)

    rows = sorted(map_places, key=lambda r: (r["rank"], r["place_id"]))
    keep_points = [(places[r["place_id"]]["lon"], places[r["place_id"]]["lat"]) for r in rows]
    land = load_land(spec, frame, keep_points)
    scene.land_rings = [(p.exterior, p.holes) for p in land]

    # 纸面与海面
    scene.add(Rect(0, 0, C.PAGE_W_MM, C.PAGE_H_MM, fill=C.PAPER))
    scene.add(Rect(frame.fx, frame.fy, frame.fw, frame.fh, fill=C.SEA))

    # 陆地、地形淡阴影、海岸线
    scene.add(Polys(scene.land_rings, fill=C.LAND))
    terrain = spec.derived_dir / "terrain.png"
    if spec.terrain and terrain.exists():
        scene.add(Image(terrain, frame.fx, frame.fy, frame.fw, frame.fh,
                        opacity=spec.terrain_opacity, clip="land"))
    scene.add(Polys(scene.land_rings, stroke=C.STRUCTURE, stroke_w=C.LW_COASTLINE))

    planner = LabelPlanner(frame, edge_pad_mm=C.LABEL_EDGE_MM)

    # 标题块与页脚压在图上的空白处，先占位，后绘制（保证压在地图之上）
    title_items, title_box = _title_block(spec, book, scene)
    planner.add_fixed_text(title_box)
    scene.fixed_boxes.append(title_box)
    footer_items, footer_boxes = _footer(spec, book)
    for box in footer_boxes:
        planner.add_fixed_text(box)
        scene.fixed_boxes.append(box)

    # 海域名与地区名：位置固定，先于地点标签占位
    for kind, items, font_key, size_pt, color, tracking in (
        ("sea", spec.seas, "sans", C.PT_SEA, C.SEA_TEXT, 0.28),
        ("region", spec.regions, "sans-medium", C.PT_REGION, C.REGION_TEXT, 0.16),
    ):
        for ann in items:
            px, py = frame.to_page(ann.lon, ann.lat)
            px, py = float(px), float(py)
            w = book.text_width_mm(font_key, ann.name, size_pt, tracking)
            _, h, top = F.text_box_mm(w, size_pt)
            box = Box(px - w / 2.0, py - h / 2.0, px + w / 2.0, py + h / 2.0, tag=ann.name)
            pad = C.SAFE_MM * 0.5
            if not frame.contains_page(box.x0, box.y0, pad) or not frame.contains_page(box.x1, box.y1, pad):
                scene.notes.append(f"{kind} 注记「{ann.name}」超出图廓，已跳过")
                continue
            planner.add_fixed_text(box)
            scene.fixed_boxes.append(box)
            scene.add(Text(ann.name, box.x0, box.y0 + top, font_key, size_pt, color,
                           tracking_em=tracking, halo_mm=0.45))

    # 地点标记（先全部登记为障碍，再排标签）
    positions = {}
    for r in rows:
        place = places[r["place_id"]]
        px, py = frame.to_page(place["lon"], place["lat"])
        px, py = float(px), float(py)
        positions[r["place_id"]] = (px, py)
        rad = marker_radius(r["rank"]) + 0.25
        mbox = Box(px - rad, py - rad, px + rad, py + rad, tag=r["place_id"])
        planner.add_obstacle(mbox)
        scene.marker_boxes.append(mbox)

    for r in rows:
        px, py = positions[r["place_id"]]
        if not frame.contains_page(px, py):
            raise SystemExit(f"{spec.id}：地点 {r['place_id']} 落在图廓之外，请调整 extent 或地点清单")
        for item in marker_items(r["marker"], r["rank"], px, py):
            scene.add(item)

    # 地点标签
    for r in rows:
        place = places[r["place_id"]]
        px, py = positions[r["place_id"]]
        major = r["rank"] == 1
        font_key = "serif-medium" if major else "serif"
        size_pt = C.PT_PLACE_MAJOR if major else C.PT_PLACE_MINOR
        w = book.text_width_mm(font_key, place["zh_name"], size_pt)
        _, h, top = F.text_box_mm(w, size_pt)
        gap = marker_radius(r["rank"]) + 0.75
        p = planner.place(place_id=r["place_id"], text=place["zh_name"], mx=px, my=py,
                          w=w, h=h, baseline_offset=top, gap=gap,
                          font_key=font_key, size_pt=size_pt, color=C.TEXT,
                          anchor=r["anchor"], dx=r["dx_mm"], dy=r["dy_mm"])
        scene.add(Text(p.text, p.x, p.baseline, font_key, size_pt, C.TEXT, halo_mm=0.45))
        scene.label_boxes.append(p.box)

    # 固定注记与地点符号的冲突必须在配置中解决，构建期直接失败
    for fb in scene.fixed_boxes:
        for mb in scene.marker_boxes:
            if fb.overlaps(mb):
                raise SystemExit(
                    f"{spec.id}：注记「{fb.tag}」压住地点符号「{mb.tag}」；"
                    f"请在 data/maps.yaml 中调整该注记的经纬度。")

    scene.placements = planner.placements

    scene.layers.extend(title_items)
    scene.layers.extend(footer_items)
    return scene


def scale_denominator(frame) -> int:
    """图上 1 单位对应的实地单位数，取三位有效数字。"""
    raw = 1000.0 / frame.mm_per_m
    magnitude = 10 ** (len(f"{int(raw)}") - 3)
    return int(round(raw / magnitude) * magnitude)


def _title_block(spec, book, scene):
    """标题、副标题与比例尺合成一块，压在地图上的空白角落。

    返回 (绘图元素列表, 整块的包围盒)。位置由 maps.yaml 的 title_block 决定。
    """
    frame = spec.frame
    cfg = spec.title_block
    corner = str(cfg.get("corner", "SW")).upper()
    km = spec.scalebar_km
    bar_len = frame.scalebar_mm(km)

    title_w = book.text_width_mm("serif-semibold", spec.title, C.PT_TITLE)
    sub_w = book.text_width_mm("serif", spec.subtitle, C.PT_SUBTITLE)
    ratio_text = f"约 1:{scale_denominator(frame):,}".replace(",", " ") + "  ·  兰勃特等角圆锥投影"
    ratio_w = book.text_width_mm("sans", ratio_text, C.PT_SOURCE)
    tail_w = book.text_width_mm("sans", f"{km:g} 千米", C.PT_SCALE)
    width = max(title_w, sub_w, ratio_w, bar_len + tail_w * 0.5)
    height = 34.0

    x = C.SAFE_MM if corner in ("NW", "SW") else C.PAGE_W_MM - C.SAFE_MM - width
    y = C.SAFE_MM if corner in ("NW", "NE") else C.PAGE_H_MM - C.SAFE_MM - height - 8.0
    x += float(cfg.get("dx_mm", 0.0))
    y += float(cfg.get("dy_mm", 0.0))

    items = []
    items.append(Text(spec.title, x, y + 7.4, "serif-semibold", C.PT_TITLE, C.TEXT,
                      halo_mm=1.3))
    items.append(Text(spec.subtitle, x, y + 14.0, "serif", C.PT_SUBTITLE, C.REGION_TEXT,
                      halo_mm=1.1))
    rule_w = max(title_w, bar_len)
    items.append(Polyline([(x, y + 17.6), (x + rule_w, y + 17.6)],
                          stroke=C.STRUCTURE, stroke_w=0.3))

    bar_y = y + 22.0
    half = bar_len / 2.0
    items.append(Rect(x, bar_y, half, 1.4, fill=C.STRUCTURE))
    items.append(Rect(x + half, bar_y, half, 1.4, fill=C.PAPER,
                      stroke=C.STRUCTURE, stroke_w=C.LW_SCALEBAR))
    for frac, text, align in ((0.0, "0", "start"), (0.5, f"{km / 2:g}", "middle"),
                              (1.0, f"{km:g} 千米", "end")):
        tx = x + bar_len * frac
        items.append(Polyline([(tx, bar_y), (tx, bar_y - 1.1)],
                              stroke=C.STRUCTURE, stroke_w=C.LW_SCALEBAR))
        items.append(Text(text, tx, bar_y + 4.6, "sans", C.PT_SCALE, C.TEXT,
                          align=align, halo_mm=1.0))
    items.append(Text(ratio_text, x, bar_y + 9.6, "sans", C.PT_SOURCE, C.REGION_TEXT,
                      halo_mm=1.0))

    box = Box(x - 2.0, y - 2.0, x + width + 2.0, y + height + 2.0, tag=f"标题块·{spec.title}")
    if not (0 <= box.x0 and box.x1 <= C.PAGE_W_MM and 0 <= box.y0 and box.y1 <= C.PAGE_H_MM):
        scene.notes.append(f"标题块超出页面：{box.as_list()}")
    return items, box


def _footer(spec, book):
    """页脚一行：左为来源说明，右为概化说明。"""
    items, boxes = [], []
    for text, align, x in ((spec.source_note, "start", C.SAFE_MM),
                           (C.FOOTER_NOTE, "end", C.PAGE_W_MM - C.SAFE_MM)):
        items.append(Text(text, x, C.FOOTER_Y_MM, "sans", C.PT_SOURCE,
                          C.REGION_TEXT, align=align, halo_mm=1.0))
        w = book.text_width_mm("sans", text, C.PT_SOURCE)
        _, h, top = F.text_box_mm(w, C.PT_SOURCE)
        x0 = x if align == "start" else x - w
        boxes.append(Box(x0 - 1.0, C.FOOTER_Y_MM - top - 1.0,
                         x0 + w + 1.0, C.FOOTER_Y_MM - top + h + 1.0, tag="页脚"))
    return items, boxes
