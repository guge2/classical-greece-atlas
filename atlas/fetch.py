"""下载、校验、裁剪并本地化全部外部资源。

用法：uv run python -m atlas.fetch [--refresh] [--skip-wikidata]

首次运行需要联网；完成后 data/ 目录内的派生数据足以支撑完全离线的构建。
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import sys
import urllib.parse
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from PIL import Image
from rasterio.warp import Resampling, reproject
from shapely.geometry import box

from . import config as C
from . import sources as S
from .mapspec import load_maps, read_csv

DOWNLOADS = C.CACHE / "downloads"
EXTRACT = C.CACHE / "extracted"


# --------------------------------------------------------------------- 下载与校验
def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1048576), b""):
            h.update(chunk)
    return h.hexdigest()


def download(src: S.Source, refresh: bool) -> Path:
    DOWNLOADS.mkdir(parents=True, exist_ok=True)
    dest = DOWNLOADS / src.filename
    if dest.exists() and not refresh:
        print(f"  [缓存] {src.filename} ({dest.stat().st_size:,} 字节)")
        return dest
    print(f"  [下载] {src.url}")
    req = urllib.request.Request(src.url, headers={"User-Agent": S.USER_AGENT})
    tmp = dest.with_suffix(dest.suffix + ".part")
    with urllib.request.urlopen(req, timeout=300) as resp, open(tmp, "wb") as fh:
        while True:
            chunk = resp.read(1048576)
            if not chunk:
                break
            fh.write(chunk)
    tmp.replace(dest)
    print(f"         {dest.stat().st_size:,} 字节")
    return dest


def extract(src: S.Source, archive: Path) -> Path:
    """解压并返回主文件路径。"""
    if not src.member:
        return archive
    target = EXTRACT / src.key
    member_path = target / src.member
    if not member_path.exists():
        target.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(target)
    return member_path


def record_sources(entries: dict) -> None:
    C.SOURCES_JSON.write_text(
        json.dumps(entries, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")


# --------------------------------------------------------------------- 矢量裁剪
def clip_vectors(specs, land_shp: Path, islands_shp: Path) -> None:
    for spec in specs:
        out_dir = spec.derived_dir
        out_dir.mkdir(parents=True, exist_ok=True)
        bounds = spec.frame.clip_bounds()
        bbox = box(*bounds)
        pieces = []
        for shp, kind in ((land_shp, "land"), (islands_shp, "island")):
            gdf = gpd.read_file(shp, bbox=bounds)
            if gdf.empty:
                continue
            geom = gdf.geometry.intersection(bbox)
            gdf = gpd.GeoDataFrame({"kind": [kind] * len(geom)},
                                   geometry=geom.values, crs=4326)
            gdf = gdf[~gdf.geometry.is_empty & gdf.geometry.notna()]
            if not gdf.empty:
                pieces.append(gdf)
        merged = gpd.GeoDataFrame(pd.concat(pieces, ignore_index=True), crs=4326)
        # 轻度预概化（约 100 m）；最终概化在投影平面按容差进行
        merged["geometry"] = merged.geometry.simplify(0.001, preserve_topology=True)
        merged = merged[~merged.geometry.is_empty & merged.geometry.notna()]
        path = out_dir / "land.geojson"
        if path.exists():
            path.unlink()
        merged.to_file(path, driver="GeoJSON", coordinate_precision=5)
        print(f"  [裁剪] {spec.id}: {len(merged)} 个多边形 -> {path.name} "
              f"({path.stat().st_size:,} 字节)")


# --------------------------------------------------------------------- 地形切片
def clip_terrain(specs, tif: Path) -> None:
    with rasterio.open(tif) as ds:
        for spec in specs:
            if not spec.terrain:
                continue
            frame = spec.frame
            width_m = frame.px1 - frame.px0
            height_m = frame.py1 - frame.py0
            native_px = width_m / (111_320.0 * ds.res[0])       # 源栅格约当像元数
            # 源栅格约 1 弧分（≈1.85 km），按 2 倍重采样以获得平滑的淡阴影
            width = int(min(spec.terrain_max_px, max(800.0, native_px * 2.0)))
            height = int(round(width * height_m / width_m))
            dst = np.zeros((height, width), dtype=np.uint8)
            transform = rasterio.transform.from_bounds(
                frame.px0, frame.py0, frame.px1, frame.py1, width, height)
            reproject(
                source=rasterio.band(ds, 1), destination=dst,
                src_transform=ds.transform, src_crs=ds.crs,
                dst_transform=transform, dst_crs=frame.crs,
                resampling=Resampling.bilinear, num_threads=2)
            img = Image.fromarray(dst, mode="L").quantize(
                colors=32, method=Image.Quantize.MEDIANCUT)
            out = spec.derived_dir / "terrain.png"
            out.parent.mkdir(parents=True, exist_ok=True)
            img.save(out, optimize=True)
            (spec.derived_dir / "terrain.json").write_text(json.dumps({
                "proj_bounds": [frame.px0, frame.py0, frame.px1, frame.py1],
                "size": [width, height],
                "crs": frame.crs.to_proj4().strip(),
                "source": "Natural Earth GRAY_HR_SR_OB",
            }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(f"  [地形] {spec.id}: {width}×{height} 像素 ({out.stat().st_size:,} 字节)")


# --------------------------------------------------------------------- 地点表
def build_places(pleiades_gz: Path, wikidata: dict) -> list:
    seed = read_csv(C.PLACES_SEED)
    wanted = {r["pleiades_id"] for r in seed}
    found = {}
    with gzip.open(pleiades_gz, "rt", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            if row["id"] in wanted:
                found[row["id"]] = row
    rows = []
    for r in seed:
        pid = r["pleiades_id"]
        p = found.get(pid)
        if p is None:
            raise SystemExit(f"Pleiades 转储中找不到 {pid}（{r['zh_name']}）")
        wd = wikidata.get(pid, {})
        rows.append({
            "id": r["id"],
            "zh_name": r["zh_name"],
            "zh_aliases": r["zh_aliases"],
            "ancient_name": r["ancient_name"],
            "latin_name": r["latin_name"],
            "pleiades_id": pid,
            "pleiades_title": p["title"],
            "wikidata_id": wd.get("qid", ""),
            "lon": f"{float(p['reprLong']):.5f}",
            "lat": f"{float(p['reprLat']):.5f}",
            "place_type": r["place_type"],
            "location_precision": p["locationPrecision"],
            "source": f"Pleiades {pid} (CC BY 3.0)",
            "note": r["note"],
        })
    fields = list(rows[0].keys())
    with open(C.PLACES, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    print(f"  [地点] {len(rows)} 条 -> {C.PLACES.name}")
    return rows


def query_wikidata(pleiades_ids) -> dict:
    """按 Pleiades ID 反查 Wikidata 条目与中文标签（仅作交叉核对，不覆盖人工译名）。"""
    values = " ".join('"%s"' % i for i in sorted(pleiades_ids))
    query = """
SELECT ?pid ?item ?zh ?en WHERE {
  VALUES ?pid { %s }
  ?item wdt:P1584 ?pid .
  OPTIONAL { ?item rdfs:label ?zh FILTER(LANG(?zh) = "zh") }
  OPTIONAL { ?item rdfs:label ?en FILTER(LANG(?en) = "en") }
}""" % values
    url = S.WIKIDATA_ENDPOINT + "?format=json&query=" + urllib.parse.quote(query)
    req = urllib.request.Request(url, headers={"User-Agent": S.USER_AGENT})
    with urllib.request.urlopen(req, timeout=180) as resp:
        payload = json.load(resp)
    out = {}
    for b in payload["results"]["bindings"]:
        pid = b["pid"]["value"]
        entry = out.setdefault(pid, {"qid": "", "zh": [], "en": []})
        qid = b["item"]["value"].rsplit("/", 1)[-1]
        if not entry["qid"]:
            entry["qid"] = qid
        for key in ("zh", "en"):
            if key in b and b[key]["value"] not in entry[key]:
                entry[key].append(b[key]["value"])
    return out


def write_wikidata_report(seed, wikidata) -> None:
    path = C.DERIVED / "wikidata_check.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["id", "zh_name", "pleiades_id", "wikidata_id",
                    "wikidata_zh", "wikidata_en", "matches_zh_name"])
        for r in seed:
            wd = wikidata.get(r["pleiades_id"], {})
            names = {r["zh_name"]} | {a for a in r["zh_aliases"].split(";") if a}
            names |= {n for name in list(names) for n in name.split("／")}
            hit = any(z in names for z in wd.get("zh", []))
            w.writerow([r["id"], r["zh_name"], r["pleiades_id"], wd.get("qid", ""),
                        ";".join(wd.get("zh", [])), ";".join(wd.get("en", [])),
                        "yes" if hit else "no"])
    print(f"  [核对] Wikidata 中文标签比对 -> {path.name}")


# --------------------------------------------------------------------- 主流程
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="下载、校验、裁剪并本地化地图集资源")
    ap.add_argument("--refresh", action="store_true", help="忽略缓存重新下载")
    ap.add_argument("--skip-wikidata", action="store_true", help="跳过 Wikidata 交叉核对")
    args = ap.parse_args(argv)

    C.DERIVED.mkdir(parents=True, exist_ok=True)
    specs = load_maps()
    registry = {}
    paths = {}

    print("· 获取外部数据")
    for src in S.SOURCES:
        archive = download(src, args.refresh)
        registry[src.key] = {
            "url": src.url, "filename": src.filename, "sha256": sha256(archive),
            "bytes": archive.stat().st_size, "license": src.license,
            "attribution": src.attribution,
            "fetched_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        paths[src.key] = extract(src, archive)

    print("· 裁剪海岸与岛屿")
    clip_vectors(specs, paths["ne_land"], paths["ne_minor_islands"])

    print("· 生成地形切片")
    clip_terrain(specs, paths["ne_gray_earth"])

    print("· 生成地点表")
    seed = read_csv(C.PLACES_SEED)
    wikidata = {}
    if not args.skip_wikidata:
        try:
            wikidata = query_wikidata({r["pleiades_id"] for r in seed})
            registry["wikidata"] = {
                "url": S.WIKIDATA_ENDPOINT, "license": S.WIKIDATA_LICENSE,
                "attribution": "Wikidata（经 P1584 Pleiades ID 关联，仅作中文标签交叉核对）",
                "fetched_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "matched": len(wikidata),
            }
        except Exception as exc:                                  # 离线时降级
            print(f"  [警告] Wikidata 查询失败，保留既有值：{exc}")
    build_places(paths["pleiades"], wikidata)
    if wikidata:
        write_wikidata_report(seed, wikidata)

    record_sources(registry)
    print(f"· 来源与许可证记录 -> {C.SOURCES_JSON.relative_to(C.ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
