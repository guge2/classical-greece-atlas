"""每幅地图的独立 Lambert 等角圆锥投影与页面坐标换算。"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from pyproj import CRS, Transformer

from . import config as C


@dataclass(frozen=True)
class Extent:
    lon_min: float
    lon_max: float
    lat_min: float
    lat_max: float

    @property
    def lon_mid(self) -> float:
        return (self.lon_min + self.lon_max) / 2.0

    @property
    def lat_mid(self) -> float:
        return (self.lat_min + self.lat_max) / 2.0


class MapFrame:
    """把地理坐标映射到 A3 页面毫米坐标（y 轴向下）。"""

    def __init__(self, extent: Extent, frame=None, projection=None,
                 content=None, content_margin_mm: float = 0.0):
        self.extent = extent
        fx, fy, fw, fh = frame or (C.FRAME_X_MM, C.FRAME_Y_MM, C.FRAME_W_MM, C.FRAME_H_MM)
        self.fx, self.fy, self.fw, self.fh = fx, fy, fw, fh
        self.fitted_to_content = bool(content)

        # 收紧画幅时，投影中心与标准纬线跟着实际内容走，而不是配置范围
        basis = extent
        if content:
            lons = [p[0] for p in content]
            lats = [p[1] for p in content]
            basis = Extent(min(lons), max(lons), min(lats), max(lats))
        self.params = self.default_params(basis)
        self.params.update({k: float(v) for k, v in (projection or {}).items()
                            if k in self.params})
        p = self.params
        self.crs = CRS.from_proj4(
            "+proj=lcc +ellps=WGS84 +datum=WGS84 +units=m +no_defs "
            f"+lat_1={p['lat_1']:.6f} +lat_2={p['lat_2']:.6f} "
            f"+lat_0={p['lat_0']:.6f} +lon_0={p['lon_0']:.6f} "
            "+x_0=0 +y_0=0"
        )
        self._fwd = Transformer.from_crs(CRS.from_epsg(4326), self.crs, always_xy=True)
        self._inv = Transformer.from_crs(self.crs, CRS.from_epsg(4326), always_xy=True)

        if content:
            x0, x1, y0, y1 = self._content_window(content, content_margin_mm)
        else:
            x, y = self._project_extent_ring()
            x0, x1, y0, y1 = x.min(), x.max(), y.min(), y.max()
        # 按地图框宽高比在投影平面上居中扩展，保证不变形
        target = self.fw / self.fh
        w, h = x1 - x0, y1 - y0
        if w / h < target:
            grow = (target * h - w) / 2.0
            x0, x1 = x0 - grow, x1 + grow
        else:
            grow = (w / target - h) / 2.0
            y0, y1 = y0 - grow, y1 + grow
        self.px0, self.px1, self.py0, self.py1 = x0, x1, y0, y1
        self.mm_per_m = self.fw / (x1 - x0)

    def _content_window(self, content, margin_mm: float):
        """由实际绘制内容的包围盒定框，四周留出指定毫米数的空隙。

        留白的实地宽度取决于比例尺，而比例尺又取决于留白，故迭代收敛。
        """
        lon = np.asarray([p[0] for p in content], dtype=float)
        lat = np.asarray([p[1] for p in content], dtype=float)
        cx, cy = self._fwd.transform(lon, lat)
        x0, x1 = float(np.min(cx)), float(np.max(cx))
        y0, y1 = float(np.min(cy)), float(np.max(cy))
        margin_m = 0.0
        for _ in range(6):
            w = max(x1 - x0 + 2 * margin_m, 1.0)
            h = max(y1 - y0 + 2 * margin_m, 1.0)
            scale = min(self.fw / w, self.fh / h)      # 毫米每米
            margin_m = margin_mm / scale if scale else 0.0
        return x0 - margin_m, x1 + margin_m, y0 - margin_m, y1 + margin_m

    @staticmethod
    def default_params(extent: Extent) -> dict:
        """未在配置中指定时，投影参数由地图范围推导。"""
        span = extent.lat_max - extent.lat_min
        return {
            "lon_0": extent.lon_mid,
            "lat_0": extent.lat_mid,
            "lat_1": extent.lat_min + span / 6.0,
            "lat_2": extent.lat_max - span / 6.0,
        }

    def _project_extent_ring(self):
        e = self.extent
        n = 120
        lons = np.linspace(e.lon_min, e.lon_max, n)
        lats = np.linspace(e.lat_min, e.lat_max, n)
        ring_lon = np.concatenate([lons, np.full(n, e.lon_max), lons[::-1], np.full(n, e.lon_min)])
        ring_lat = np.concatenate([np.full(n, e.lat_min), lats, np.full(n, e.lat_max), lats[::-1]])
        return (lambda xy: (np.asarray(xy[0]), np.asarray(xy[1])))(self._fwd.transform(ring_lon, ring_lat))

    # ------------------------------------------------------------ 坐标换算
    def to_page(self, lon, lat):
        """经纬度 -> 页面毫米坐标。接受标量或数组。"""
        x, y = self._fwd.transform(np.asarray(lon, dtype=float), np.asarray(lat, dtype=float))
        return self.proj_to_page(x, y)

    def proj_to_page(self, x, y):
        px = self.fx + (np.asarray(x) - self.px0) / (self.px1 - self.px0) * self.fw
        py = self.fy + (self.py1 - np.asarray(y)) / (self.py1 - self.py0) * self.fh
        return px, py

    def clip_bounds(self, margin_frac: float = 0.03):
        """裁剪用的经纬度包围盒（略大于成图范围）。"""
        mx = (self.px1 - self.px0) * margin_frac
        my = (self.py1 - self.py0) * margin_frac
        n = 80
        xs = np.linspace(self.px0 - mx, self.px1 + mx, n)
        ys = np.linspace(self.py0 - my, self.py1 + my, n)
        gx = np.concatenate([xs, np.full(n, xs[-1]), xs[::-1], np.full(n, xs[0])])
        gy = np.concatenate([np.full(n, ys[0]), ys, np.full(n, ys[-1]), ys[::-1]])
        lon, lat = self._inv.transform(gx, gy)
        return float(np.min(lon)), float(np.min(lat)), float(np.max(lon)), float(np.max(lat))

    def scalebar_mm(self, km: float) -> float:
        return km * 1000.0 * self.mm_per_m

    def contains_page(self, x: float, y: float, pad: float = 0.0) -> bool:
        return (self.fx + pad <= x <= self.fx + self.fw - pad
                and self.fy + pad <= y <= self.fy + self.fh - pad)
