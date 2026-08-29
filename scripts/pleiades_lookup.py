"""开发期辅助脚本：在 Pleiades 转储中按名称检索候选地点。

用法: python scripts/pleiades_lookup.py <正则> [<正则> ...]
仅用于人工挑选 Pleiades ID，结果需人工确认后写入 data/places.csv。
"""
import csv
import gzip
import re
import sys

DUMP = "cache/pleiades/pleiades-places-latest.csv.gz"
BBOX = (10.0, 32.0, 32.0, 43.5)  # 地中海东部工作范围 lon_min, lon_max? -> (lonmin, lonmax, latmin, latmax)


def rows():
    with gzip.open(DUMP, "rt", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            try:
                lat = float(row["reprLat"])
                lon = float(row["reprLong"])
            except (TypeError, ValueError):
                continue
            if not (BBOX[0] <= lon <= BBOX[1] and BBOX[2] <= lat <= BBOX[3]):
                continue
            row["_lat"], row["_lon"] = lat, lon
            yield row


def main(patterns):
    pats = [(p, re.compile(p, re.I)) for p in patterns]
    hits = {p: [] for p in patterns}
    for row in rows():
        title = row["title"]
        for raw, rx in pats:
            if rx.search(title):
                hits[raw].append(row)
    for raw, _ in pats:
        print(f"=== {raw}")
        for row in sorted(hits[raw], key=lambda r: r["title"]):
            print(
                f"  {row['id']:>10}  {row['title'][:44]:<44} "
                f"{row['_lat']:8.4f},{row['_lon']:8.4f}  {row['locationPrecision']:<8} "
                f"{row['featureTypes'][:38]:<38} {row['timePeriods'][:14]}"
            )
        if not hits[raw]:
            print("  (无匹配)")


if __name__ == "__main__":
    main(sys.argv[1:])
