"""开发期辅助脚本：按坐标邻域检索 Pleiades 候选地点。"""
import csv
import gzip
import math
import sys

DUMP = "cache/pleiades/pleiades-places-latest.csv.gz"


def main(lat, lon, km, kinds):
    out = []
    with gzip.open(DUMP, "rt", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            try:
                y, x = float(row["reprLat"]), float(row["reprLong"])
            except (TypeError, ValueError):
                continue
            d = math.hypot((y - lat) * 111.0, (x - lon) * 111.0 * math.cos(math.radians(lat)))
            if d <= km and (not kinds or any(k in row["featureTypes"] for k in kinds)):
                out.append((d, row))
    for d, row in sorted(out)[:25]:
        print(f"  {d:6.1f}km {row['id']:>10}  {row['title'][:44]:<44} "
              f"{row['reprLat'][:8]:>8},{row['reprLong'][:8]:>8}  {row['featureTypes'][:40]:<40} {row['timePeriods'][:12]}")


if __name__ == "__main__":
    main(float(sys.argv[1]), float(sys.argv[2]), float(sys.argv[3]), sys.argv[4:])
