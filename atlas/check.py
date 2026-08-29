"""验证数据、标签冲突、输出尺寸与文件体积。

用法：uv run python -m atlas.check [--render] [--strict]

任何一项失败都会以非零状态退出，可直接用于构建流水线。
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from shapely.geometry import MultiPolygon, Point, Polygon
from shapely.ops import unary_union

from . import config as C
from . import fonts as F
from . import pdfout
from .build import PDF_NAME
from .mapspec import load_map_places, load_maps, load_places, read_csv
from .scene import compose

MARKER_LIMIT = {"01-overview": 32, "05-power-blocs": 36}
MARKER_LIMIT_DEFAULT = 40
VALID_MARKERS = {"city", "sanctuary", "island", "pass"}
# 印刷标签只允许汉字与少量中文标点
LABEL_RE = re.compile(r"^[一-鿿㐀-䶿·・／·、]+$")
SVG_NS = "{http://www.w3.org/2000/svg}"
XLINK = "{http://www.w3.org/1999/xlink}href"


def _mm(value):
    """解析形如 "420mm" 的长度，返回毫米数。"""
    if not value or not value.endswith("mm"):
        return None
    try:
        return float(value[:-2])
    except ValueError:
        return None


class Report:
    def __init__(self):
        self.errors: list = []
        self.warnings: list = []
        self.info: list = []

    def error(self, msg):
        self.errors.append(msg)

    def warn(self, msg):
        self.warnings.append(msg)

    def note(self, msg):
        self.info.append(msg)

    def dump(self) -> int:
        for line in self.info:
            print(f"  · {line}")
        for line in self.warnings:
            print(f"  [提醒] {line}")
        for line in self.errors:
            print(f"  [错误] {line}")
        print(f"\n结论：{len(self.errors)} 项错误，{len(self.warnings)} 项提醒")
        return 1 if self.errors else 0


# --------------------------------------------------------------------- 数据校验
def check_places(rep: Report) -> dict:
    places = load_places()
    seen_ids, seen_pleiades = set(), {}
    for pid, row in places.items():
        if pid in seen_ids:
            rep.error(f"地点 ID 重复：{pid}")
        seen_ids.add(pid)
        if not row["zh_name"].strip():
            rep.error(f"{pid}：中文主名为空")
        elif not LABEL_RE.match(row["zh_name"]):
            rep.error(f"{pid}：打印标签「{row['zh_name']}」含未计划的非中文字符")
        if not (-180.0 <= row["lon"] <= 180.0 and -90.0 <= row["lat"] <= 90.0):
            rep.error(f"{pid}：经纬度超出有效范围（{row['lon']}, {row['lat']}）")
        if not (10.0 <= row["lon"] <= 32.0 and 33.0 <= row["lat"] <= 43.0):
            rep.warn(f"{pid}：经纬度落在地图集工作范围之外（{row['lon']}, {row['lat']}）")
        if not row["pleiades_id"].strip().isdigit():
            rep.error(f"{pid}：缺少可追溯的 Pleiades ID")
        else:
            seen_pleiades.setdefault(row["pleiades_id"], []).append(pid)
        if "Pleiades" not in row["source"]:
            rep.error(f"{pid}：source 字段未记录 Pleiades 来源")
        if not row["location_precision"].strip():
            rep.error(f"{pid}：缺少坐标置信度")
    for pleiades_id, ids in seen_pleiades.items():
        if len(ids) > 1:
            rep.warn(f"Pleiades {pleiades_id} 被多个地点共用：{'、'.join(ids)}")
    rep.note(f"地点表 {len(places)} 条，ID 唯一，标签均为中文")
    return places


def check_pleiades_traceable(rep: Report, places: dict) -> None:
    dump = C.CACHE / "downloads" / "pleiades-places-latest.csv.gz"
    if not dump.exists():
        rep.warn("未找到 Pleiades 转储缓存，跳过坐标逐条比对（先运行 atlas.fetch）")
        return
    wanted = {row["pleiades_id"]: pid for pid, row in places.items()}
    found = {}
    with gzip.open(dump, "rt", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            if row["id"] in wanted:
                found[row["id"]] = row
    for pleiades_id, pid in wanted.items():
        row = found.get(pleiades_id)
        if row is None:
            rep.error(f"{pid}：Pleiades {pleiades_id} 在转储中不存在")
            continue
        dlon = abs(float(row["reprLong"]) - places[pid]["lon"])
        dlat = abs(float(row["reprLat"]) - places[pid]["lat"])
        if max(dlon, dlat) > 1e-4:
            rep.error(f"{pid}：坐标与 Pleiades {pleiades_id} 不一致（差 {dlon:.5f}, {dlat:.5f}）")
    rep.note(f"{len(found)} 条地点坐标与 Pleiades 转储逐条一致")


def check_map_places(rep: Report, places: dict) -> None:
    specs = {s.id: s for s in load_maps()}
    map_places = load_map_places()
    for map_id, rows in map_places.items():
        if map_id not in specs:
            rep.error(f"map_places.csv 引用了未定义的地图：{map_id}")
            continue
        limit = MARKER_LIMIT.get(map_id, MARKER_LIMIT_DEFAULT)
        if len(rows) > limit:
            rep.error(f"{map_id}：{len(rows)} 个地点标记，超过上限 {limit}")
        seen = set()
        for r in rows:
            if r["place_id"] not in places:
                rep.error(f"{map_id}：引用了不存在的地点 {r['place_id']}")
            if r["place_id"] in seen:
                rep.error(f"{map_id}：地点 {r['place_id']} 重复出现")
            seen.add(r["place_id"])
            if r["rank"] not in (1, 2):
                rep.error(f"{map_id}/{r['place_id']}：重要级别必须为 1 或 2")
            if r["marker"] not in VALID_MARKERS:
                rep.error(f"{map_id}/{r['place_id']}：未知标记类型 {r['marker']}")
        rep.note(f"{map_id}：{len(rows)} 个地点标记（上限 {limit}）")
    for spec in specs.values():
        for ann in [*spec.regions, *spec.seas]:
            if not LABEL_RE.match(ann.name):
                rep.error(f"{spec.id}：注记「{ann.name}」含未计划的非中文字符")
        for text, kind in ((spec.title, "标题"), (spec.subtitle, "副标题")):
            if re.search(r"[A-Za-z]", text):
                rep.error(f"{spec.id}：{kind}「{text}」含未计划的英文")


# --------------------------------------------------------------------- 版面校验
def check_layout(rep: Report, places: dict, render: bool) -> list:
    specs = load_maps()
    map_places = load_map_places()
    book = F.FontBook()
    scenes = []
    for spec in specs:
        scene = compose(spec, places, map_places[spec.id], book)
        scenes.append(scene)
        frame = spec.frame

        boxes = list(scene.label_boxes)
        fixed = [b for b in getattr(scene, "fixed_boxes", [])]
        all_text = boxes + fixed
        for i, a in enumerate(all_text):
            for b in all_text[i + 1:]:
                if a.overlaps(b):
                    rep.error(f"{spec.id}：文字重叠 「{a.tag}」×「{b.tag}」")
        for t in all_text:
            for m in scene.marker_boxes:
                if t.tag != m.tag and t.overlaps(m):
                    rep.error(f"{spec.id}：文字「{t.tag}」压住地点符号「{m.tag}」")
            if not (frame.fx <= t.x0 and t.x1 <= frame.fx + frame.fw
                    and frame.fy <= t.y0 and t.y1 <= frame.fy + frame.fh):
                rep.error(f"{spec.id}：标签「{t.tag}」越出图廓")
        for note in scene.notes:
            rep.warn(f"{spec.id}：{note}")
        overrides = [p.place_id for p in scene.placements if p.overridden]
        rep.note(f"{spec.id}：{len(scene.label_boxes)} 个地点标签无碰撞，"
                 f"{len(overrides)} 个使用配置覆写")

        _check_annotation_placement(rep, scene)

        if render:
            png = pdfout.save_png(scene, book, C.QA / f"{spec.id}-300dpi.png", dpi=300)
            pdfout.save_png(scene, book, C.QA / f"{spec.id}-gray.png", dpi=150, grayscale=True)
            rep.note(f"{spec.id}：QA 渲染 {png.name}（300 dpi）与灰度版")
    return scenes


def _check_annotation_placement(rep: Report, scene) -> None:
    """海域名应落在海上，地区名应落在陆地上。"""
    polys = []
    for ext, holes in scene.land_rings:
        try:
            polys.append(Polygon(ext, holes))
        except (ValueError, TypeError):
            continue
    land = unary_union([p for p in polys if p.is_valid or p.buffer(0).is_valid])
    if isinstance(land, Polygon):
        land = MultiPolygon([land])
    spec = scene.spec
    for kind, items in (("海域名", spec.seas), ("地区名", spec.regions)):
        for ann in items:
            px, py = spec.frame.to_page(ann.lon, ann.lat)
            on_land = land.contains(Point(float(px), float(py)))
            if ann.over == "any":
                continue
            if ann.over == "sea" and on_land:
                rep.warn(f"{spec.id}：{kind}「{ann.name}」落在陆地上")
            if ann.over == "land" and not on_land:
                rep.warn(f"{spec.id}：{kind}「{ann.name}」落在海上")


# --------------------------------------------------------------------- 输出校验
def check_outputs(rep: Report) -> None:
    specs = load_maps()
    for spec in specs:
        path = C.BUILD / spec.file
        if not path.exists():
            rep.error(f"缺少输出文件 {spec.file}（请先运行 atlas.build --all）")
            continue
        size = path.stat().st_size
        if size > C.MAX_SVG_BYTES:
            rep.error(f"{spec.file}：{size:,} 字节，超过上限 {C.MAX_SVG_BYTES:,}")
        try:
            root = ET.parse(path).getroot()
        except ET.ParseError as exc:
            rep.error(f"{spec.file}：不是合法 XML（{exc}）")
            continue
        got = (_mm(root.get("width")), _mm(root.get("height")))
        if got != (C.PAGE_W_MM, C.PAGE_H_MM):
            rep.error(f"{spec.file}：页面尺寸为 {root.get('width')}×{root.get('height')}，"
                      f"应为 {C.PAGE_W_MM}mm×{C.PAGE_H_MM}mm")
        remote = 0
        for el in root.iter():
            for key, value in el.attrib.items():
                if key.startswith("xmlns"):
                    continue
                if key in ("href", XLINK):
                    if not (value.startswith("#") or value.startswith("data:")):
                        remote += 1
                elif "http://" in value or "https://" in value:
                    remote += 1
        if remote:
            rep.error(f"{spec.file}：存在 {remote} 处外部引用，SVG 不自包含")
        rep.note(f"{spec.file}：合法 XML，{C.PAGE_W_MM}×{C.PAGE_H_MM} mm，自包含，"
                 f"{size:,} 字节")

    pdf = C.PDF_OUTPUT / PDF_NAME
    if not pdf.exists():
        rep.error(f"缺少合并 PDF {PDF_NAME}")
        return
    size = pdf.stat().st_size
    if size > C.MAX_PDF_BYTES:
        rep.error(f"{PDF_NAME}：{size:,} 字节，超过上限 {C.MAX_PDF_BYTES:,}")
    head = pdf.read_bytes()
    pages = head.count(b"/Type /Page\n") or head.count(b"/Type/Page")
    if not head.startswith(b"%PDF-"):
        rep.error(f"{PDF_NAME}：不是有效的 PDF")
    if pages and pages != len(specs):
        rep.warn(f"{PDF_NAME}：检测到 {pages} 页，预期 {len(specs)} 页")
    fonts = head.count(b"/FontFile2")
    if not fonts:
        rep.error(f"{PDF_NAME}：未检测到嵌入的 TrueType 字体子集")
    rep.note(f"{PDF_NAME}：{size:,} 字节，{pages or len(specs)} 页，"
             f"{fonts} 个嵌入字体子集")


def check_sources(rep: Report) -> None:
    if not C.SOURCES_JSON.exists():
        rep.error("缺少 data/sources.json（请先运行 atlas.fetch）")
        return
    entries = json.loads(C.SOURCES_JSON.read_text(encoding="utf-8"))
    for key, meta in entries.items():
        for field in ("url", "license", "attribution"):
            if not meta.get(field):
                rep.error(f"sources.json/{key}：缺少 {field}")
        if key != "wikidata" and not meta.get("sha256"):
            rep.error(f"sources.json/{key}：缺少校验值")
    rep.note(f"来源记录 {len(entries)} 项，均含 URL、许可证与署名")


# --------------------------------------------------------------------- 主流程
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="校验地图集数据与输出")
    ap.add_argument("--render", action="store_true", help="额外输出 300 dpi 与灰度 QA 图")
    ap.add_argument("--strict", action="store_true", help="把提醒也视为失败")
    args = ap.parse_args(argv)

    rep = Report()
    print("· 数据校验")
    places = check_places(rep)
    check_pleiades_traceable(rep, places)
    check_map_places(rep, places)
    print("· 版面校验")
    check_layout(rep, places, args.render)
    print("· 输出校验")
    check_outputs(rep)
    check_sources(rep)
    print()
    code = rep.dump()
    if args.strict and rep.warnings:
        code = 1
    return code


if __name__ == "__main__":
    sys.exit(main())
