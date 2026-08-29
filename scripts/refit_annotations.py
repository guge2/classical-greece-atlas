"""把落到成图范围外的地区名与海域名就近移回框内，并写回 data/maps.yaml。

收紧画幅后，原先放在远处空白里的注记会越界。本脚本为每个越界注记搜索一个
距离最近、且满足以下条件的新位置：

  * 文字盒完整落在页面安全区内；
  * 落位符合注记声明的 over（land / sea / any）；
  * 不压住地点符号，也不与其他注记重叠。

结果写回 maps.yaml 后仍是人工可读、可再编辑的显式坐标。

用法：uv run python scripts/refit_annotations.py [--dry-run]
"""
from __future__ import annotations

import re
import sys

import numpy as np
from shapely.geometry import Point, Polygon
from shapely.ops import unary_union

sys.path.insert(0, ".")

from atlas import config as C                                    # noqa: E402
from atlas import fonts as F                                     # noqa: E402
from atlas.geometry import load_land                             # noqa: E402
from atlas.labels import Box                                     # noqa: E402
from atlas.mapspec import load_map_places, load_maps, load_places  # noqa: E402
from atlas.scene import Scene, _faction_legend, _title_block, marker_radius  # noqa: E402


def annotation_box(book, name, kind, px, py):
    font_key, size_pt, tracking = (
        ("sans", C.PT_SEA, 0.28) if kind == "sea" else ("sans-medium", C.PT_REGION, 0.16))
    w = book.text_width_mm(font_key, name, size_pt, tracking)
    _, h, _ = F.text_box_mm(w, size_pt)
    return Box(px - w / 2.0, py - h / 2.0, px + w / 2.0, py + h / 2.0, tag=name)


def inside_safe(box: Box) -> bool:
    return (C.SAFE_MM <= box.x0 and box.x1 <= C.PAGE_W_MM - C.SAFE_MM
            and C.SAFE_MM <= box.y0 and box.y1 <= C.PAGE_H_MM - C.SAFE_MM)


def surface_ok(land, box: Box, over: str) -> bool:
    if over == "any":
        return True
    centre = Point((box.x0 + box.x1) / 2.0, (box.y0 + box.y1) / 2.0)
    on_land = land.contains(centre)
    return on_land if over == "land" else not on_land


def refit_map(spec, places, map_places, book):
    frame = spec.frame
    land_polys = []
    for poly in load_land(spec, frame, [(places[r["place_id"]]["lon"],
                                         places[r["place_id"]]["lat"])
                                        for r in map_places[spec.id]]):
        try:
            land_polys.append(Polygon(poly.exterior, poly.holes))
        except (ValueError, TypeError):
            continue
    land = unary_union([p.buffer(0) for p in land_polys])

    markers = []
    for r in map_places[spec.id]:
        p = places[r["place_id"]]
        x, y = frame.to_page(p["lon"], p["lat"])
        rad = marker_radius(r["rank"]) + 0.25
        markers.append(Box(float(x) - rad, float(y) - rad,
                           float(x) + rad, float(y) + rad, tag=p["zh_name"]))

    # 标题块与图例同样是固定文字，注记必须避开
    placed: list = []
    _, title_box = _title_block(spec, book, Scene(spec=spec))
    placed.append(title_box)
    if spec.faction_areas:
        _, legend_box = _faction_legend(spec, book)
        placed.append(legend_box)
    moves = []
    for kind, items in (("sea", spec.seas), ("region", spec.regions)):
        for ann in items:
            px, py = frame.to_page(ann.lon, ann.lat)
            px, py = float(px), float(py)
            box = annotation_box(book, ann.name, kind, px, py)
            ok = (inside_safe(box) and surface_ok(land, box, ann.over)
                  and not any(box.overlaps(m, 0.4) for m in markers)
                  and not any(box.overlaps(b, 0.8) for b in placed))
            if ok:
                placed.append(box)
                continue
            best = None
            for radius in np.arange(2.0, 130.0, 2.0):            # 由近及远搜索
                for angle in np.arange(0.0, 360.0, 12.0):
                    nx = px + radius * np.cos(np.radians(angle))
                    ny = py + radius * np.sin(np.radians(angle))
                    trial = annotation_box(book, ann.name, kind, nx, ny)
                    if (inside_safe(trial) and surface_ok(land, trial, ann.over)
                            and not any(trial.overlaps(m, 0.4) for m in markers)
                            and not any(trial.overlaps(b, 0.8) for b in placed)):
                        best = (nx, ny, radius)
                        break
                if best:
                    break
            if not best:
                moves.append((ann.name, None, None, None))
                continue
            nx, ny, radius = best
            lon, lat = frame._inv.transform(
                *[float(v) for v in _page_to_proj(frame, nx, ny)])
            placed.append(annotation_box(book, ann.name, kind, nx, ny))
            moves.append((ann.name, round(float(lon), 2), round(float(lat), 2), radius))
    return moves


def _page_to_proj(frame, px, py):
    x = frame.px0 + (px - frame.fx) / frame.fw * (frame.px1 - frame.px0)
    y = frame.py1 - (py - frame.fy) / frame.fh * (frame.py1 - frame.py0)
    return x, y


def rewrite_yaml(map_id: str, moves) -> int:
    text = C.MAPS_YAML.read_text(encoding="utf-8")
    start = text.index(f'id: "{map_id}"')
    end = len(text)
    for other in re.finditer(r'  - id: "', text):
        if other.start() > start:
            end = other.start()
            break
    block = text[start:end]
    changed = 0
    for name, lon, lat, _ in moves:
        if lon is None:
            continue
        pattern = re.compile(r'(\{name: "%s", lon: )[-0-9.]+(, lat: )[-0-9.]+' % re.escape(name))
        block, n = pattern.subn(lambda m: f"{m.group(1)}{lon}{m.group(2)}{lat}", block)
        changed += n
    C.MAPS_YAML.write_text(text[:start] + block + text[end:], encoding="utf-8")
    return changed


def main(argv=None) -> int:
    dry = "--dry-run" in (argv or sys.argv[1:])
    places = load_places()
    map_places = load_map_places()
    book = F.FontBook()
    total = 0
    for spec in load_maps():
        moves = refit_map(spec, places, map_places, book)
        if not moves:
            print(f"{spec.id}：全部注记就位")
            continue
        print(f"{spec.id}：{len(moves)} 处注记需要移动")
        for name, lon, lat, radius in moves:
            if lon is None:
                print(f"  ! 「{name}」找不到合适位置，请人工处理")
            else:
                print(f"  · 「{name}」 -> {lon}, {lat}（页面移动 {radius:.0f} mm）")
        if not dry:
            total += rewrite_yaml(spec.id, moves)
    if not dry:
        print(f"\n已写回 data/maps.yaml：{total} 处")
    return 0


if __name__ == "__main__":
    sys.exit(main())
