"""海岸几何：投影、概化、岛屿取舍与页面坐标转换。"""
from __future__ import annotations

from dataclasses import dataclass

import geopandas as gpd
import numpy as np
from shapely.geometry import MultiPolygon, Point, Polygon
from shapely.geometry.polygon import orient

from .projection import MapFrame


@dataclass
class PagePolygon:
    """页面毫米坐标下的一个陆地多边形（含内环）。"""
    exterior: np.ndarray
    holes: list
    area_km2: float
    forced: bool          # 因承载命名地点而强制保留


def _polygons(geom):
    if geom is None or geom.is_empty:
        return []
    if isinstance(geom, Polygon):
        return [geom]
    if isinstance(geom, MultiPolygon):
        return list(geom.geoms)
    return [g for g in getattr(geom, "geoms", []) if isinstance(g, Polygon)]


def load_land(spec, frame: MapFrame, keep_points=()) -> list:
    """读取裁剪后的陆地面，投影、概化，并返回页面坐标多边形。

    keep_points 为需要强制保留其所在岛屿的经纬度点。
    """
    gdf = gpd.read_file(spec.derived_dir / "land.geojson")
    projected = gdf.to_crs(frame.crs)

    keep_geoms = []
    if len(keep_points):
        pts = gpd.GeoSeries([Point(lon, lat) for lon, lat in keep_points], crs=4326)
        keep_geoms = list(pts.to_crs(frame.crs).values)

    # 概化容差按 maps.yaml 配置；小面另按自身尺度收紧，避免命名岛屿塌形
    tol_m = spec.simplify_km * 1000.0
    out = []
    for geom in projected.geometry:
        for poly in _polygons(geom):
            area = poly.area
            forced = any(poly.buffer(2500.0).contains(p) for p in keep_geoms)
            # 小面按自身尺度收紧容差，避免概化后塌成三角形
            tol = min(tol_m, 0.05 * np.sqrt(max(area, 1.0)))
            simple = poly.simplify(tol, preserve_topology=True)
            if simple.is_empty:
                continue
            if not forced and area / 1e6 < spec.min_island_km2:
                continue
            for part in _polygons(simple):
                part = orient(part, sign=1.0)   # 外环逆时针、内环顺时针
                ext = np.asarray(part.exterior.coords)
                holes = [np.asarray(r.coords) for r in part.interiors
                         if Polygon(r).area / 1e6 >= spec.min_island_km2]
                out.append(PagePolygon(
                    exterior=np.column_stack(frame.proj_to_page(ext[:, 0], ext[:, 1])),
                    holes=[np.column_stack(frame.proj_to_page(h[:, 0], h[:, 1])) for h in holes],
                    area_km2=area / 1e6,
                    forced=forced,
                ))
    out.sort(key=lambda p: p.area_km2, reverse=True)
    return out


def polygon_vertex_count(polys) -> int:
    return sum(len(p.exterior) + sum(len(h) for h in p.holes) for p in polys)
