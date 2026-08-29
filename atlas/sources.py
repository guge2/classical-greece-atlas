"""外部数据源登记：URL、许可证与本地缓存路径。"""
from __future__ import annotations

from dataclasses import dataclass

NE_BASE = "https://naciscdn.org/naturalearth/10m"


@dataclass(frozen=True)
class Source:
    key: str
    url: str
    filename: str
    license: str
    attribution: str
    member: str = ""      # zip 内主文件（相对路径）


SOURCES = (
    Source("ne_land", f"{NE_BASE}/physical/ne_10m_land.zip", "ne_10m_land.zip",
           "Public Domain", "Natural Earth, 1:10m Physical Vectors, ne_10m_land",
           "ne_10m_land.shp"),
    Source("ne_minor_islands", f"{NE_BASE}/physical/ne_10m_minor_islands.zip",
           "ne_10m_minor_islands.zip", "Public Domain",
           "Natural Earth, 1:10m Physical Vectors, ne_10m_minor_islands",
           "ne_10m_minor_islands.shp"),
    Source("ne_gray_earth", f"{NE_BASE}/raster/GRAY_HR_SR_OB.zip", "GRAY_HR_SR_OB.zip",
           "Public Domain", "Natural Earth, 1:10m Gray Earth with Shaded Relief and Ocean Bottom",
           "GRAY_HR_SR_OB.tif"),
    Source("pleiades", "https://atlantides.org/downloads/pleiades/dumps/pleiades-places-latest.csv.gz",
           "pleiades-places-latest.csv.gz", "CC BY 3.0",
           "Pleiades: A Gazetteer of Past Places, https://pleiades.stoa.org/ (CC BY 3.0)"),
)

WIKIDATA_ENDPOINT = "https://query.wikidata.org/sparql"
WIKIDATA_LICENSE = "CC0 1.0（Wikidata 结构化数据）"
USER_AGENT = "classical-greece-atlas/1.0 (static print atlas build; contact: local user)"

BY_KEY = {s.key: s for s in SOURCES}
