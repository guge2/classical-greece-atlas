"""离线生成四幅 SVG 与合并 PDF。

用法：uv run python -m atlas.build --all [--no-pdf] [--no-minify]
"""
from __future__ import annotations

import argparse
import json
import sys
import time

from . import config as C
from . import fonts as F
from . import pdfout, svgout
from .mapspec import load_map_places, load_maps, load_places
from .scene import compose

PDF_NAME = "classical-greece-atlas.pdf"


def build(map_ids=None, make_pdf: bool = True, minify: bool = True) -> dict:
    specs = load_maps()
    if map_ids:
        wanted = set(map_ids)
        specs = [s for s in specs if s.id in wanted]
        missing = wanted - {s.id for s in specs}
        if missing:
            raise SystemExit(f"maps.yaml 中没有这些地图：{'、'.join(sorted(missing))}")
    places = load_places()
    map_places = load_map_places()
    book = F.FontBook()
    C.BUILD.mkdir(parents=True, exist_ok=True)

    scenes, report = [], {"maps": [], "generated": time.strftime("%Y-%m-%dT%H:%M:%S")}
    for spec in specs:
        t0 = time.time()
        rows = map_places.get(spec.id, [])
        if not rows:
            raise SystemExit(f"map_places.csv 中没有 {spec.id} 的地点")
        scene = compose(spec, places, rows, book)
        scenes.append(scene)
        svg_path = C.BUILD / spec.file
        svgout.write_svg(scene, book, svg_path, minify=minify)
        entry = {
            "id": spec.id,
            "file": spec.file,
            "svg_bytes": svg_path.stat().st_size,
            "markers": len(rows),
            "polygons": len(scene.land_rings),
            "label_boxes": [b.as_list() + [b.tag] for b in scene.label_boxes],
            "marker_boxes": [b.as_list() + [b.tag] for b in scene.marker_boxes],
            "fixed_text_boxes": [],
            "overrides": [p.place_id for p in scene.placements if p.overridden],
            "anchors": {p.place_id: p.anchor for p in scene.placements},
            "notes": scene.notes,
            "scale_1_to": round(1000.0 / spec.frame.mm_per_m, -3),
            "seconds": round(time.time() - t0, 2),
        }
        report["maps"].append(entry)
        print(f"  [SVG] {spec.file}  {svg_path.stat().st_size:,} 字节  "
              f"{len(rows)} 个地点  {entry['seconds']}s")
        for note in scene.notes:
            print(f"        · {note}")

    if make_pdf and len(specs) == len(load_maps()):
        pdf_path = C.BUILD / PDF_NAME
        pdfout.save_pdf(scenes, book, pdf_path)
        report["pdf_bytes"] = pdf_path.stat().st_size
        print(f"  [PDF] {PDF_NAME}  {pdf_path.stat().st_size:,} 字节  {len(scenes)} 页")
    elif make_pdf:
        print("  [PDF] 仅构建了部分地图，跳过合并 PDF")

    # 记录实际用到的字形，供体积核算与字体子集导出
    report["glyphs_used"] = {k: len(v) for k, v in sorted(book.used.items())}
    (C.BUILD / "layout_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    return report


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="生成古典希腊中文静态地图集")
    ap.add_argument("--all", action="store_true", help="构建全部四幅地图与合并 PDF")
    ap.add_argument("--map", action="append", dest="maps", metavar="ID",
                    help="只构建指定地图（可重复）")
    ap.add_argument("--no-pdf", action="store_true", help="跳过合并 PDF")
    ap.add_argument("--no-minify", action="store_true", help="不用 scour 压缩 SVG")
    args = ap.parse_args(argv)
    if not args.all and not args.maps:
        ap.error("请指定 --all 或 --map ID")
    print("· 生成地图")
    build(args.maps, make_pdf=not args.no_pdf, minify=not args.no_minify)
    return 0


if __name__ == "__main__":
    sys.exit(main())
