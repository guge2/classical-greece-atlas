"""maps.yaml / places.csv / map_places.csv 的读取与结构化。"""
from __future__ import annotations

import csv
from dataclasses import dataclass, field

import yaml

from . import config as C
from .projection import Extent, MapFrame


@dataclass
class Annotation:
    name: str
    lon: float
    lat: float
    over: str = ""        # land | sea | any；留空则按注记类别取默认


@dataclass
class MapSpec:
    id: str
    file: str
    title: str
    subtitle: str
    extent: Extent
    simplify_km: float
    scalebar_km: float
    min_island_km2: float
    terrain: bool
    terrain_opacity: float = 0.12
    terrain_max_px: int = 1800
    projection: dict = field(default_factory=dict)
    title_block: dict = field(default_factory=dict)
    regions: list = field(default_factory=list)
    seas: list = field(default_factory=list)
    source_note: str = ""

    @property
    def frame(self) -> MapFrame:
        if not hasattr(self, "_frame"):
            self._frame = MapFrame(self.extent, projection=self.projection)
        return self._frame

    @property
    def derived_dir(self):
        return C.DERIVED / self.id


def load_maps(path=None) -> list[MapSpec]:
    doc = yaml.safe_load((path or C.MAPS_YAML).read_text(encoding="utf-8"))
    defaults = doc.get("defaults", {})
    out = []
    for m in doc["maps"]:
        terrain = m.get("terrain", {})
        if isinstance(terrain, bool):
            terrain = {"enabled": terrain}
        out.append(MapSpec(
            id=m["id"], file=m["file"], title=m["title"], subtitle=m["subtitle"],
            extent=Extent(*m["extent"]),
            simplify_km=float(m["simplify_km"]), scalebar_km=float(m["scalebar_km"]),
            min_island_km2=float(m.get("min_island_km2", 10.0)),
            terrain=bool(terrain.get("enabled", True)),
            terrain_opacity=float(terrain.get("opacity", C.TERRAIN_OPACITY)),
            terrain_max_px=int(terrain.get("max_px", C.TERRAIN_MAX_PX)),
            projection=dict(m.get("projection", {})),
            title_block=dict(m.get("title_block", {})),
            regions=[Annotation(a["name"], a["lon"], a["lat"], a.get("over", "land"))
                     for a in m.get("regions", [])],
            seas=[Annotation(a["name"], a["lon"], a["lat"], a.get("over", "sea"))
                  for a in m.get("seas", [])],
            source_note=m.get("source_note", defaults.get("source_note", "")),
        ))
    return out


def read_csv(path):
    with open(path, encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def load_places(path=None) -> dict:
    rows = read_csv(path or C.PLACES)
    places = {}
    for r in rows:
        r["lon"] = float(r["lon"])
        r["lat"] = float(r["lat"])
        places[r["id"]] = r
    return places


def load_map_places(path=None) -> dict:
    rows = read_csv(path or C.MAP_PLACES)
    out: dict[str, list] = {}
    for r in rows:
        r["rank"] = int(r["rank"])
        r["dx_mm"] = float(r["dx_mm"]) if r.get("dx_mm") else None
        r["dy_mm"] = float(r["dy_mm"]) if r.get("dy_mm") else None
        r["anchor"] = (r.get("anchor") or "").strip()
        out.setdefault(r["map_id"], []).append(r)
    return out
