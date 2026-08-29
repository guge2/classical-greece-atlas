"""标签排版：八方位无碰撞放置，失败即报错，不做随机化。"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import config as C

# 依次尝试的方位（东、东北、东南、西、西北、西南、北、南）
ANCHOR_ORDER = ("E", "NE", "SE", "W", "NW", "SW", "N", "S")
ANCHOR_NAMES = {
    "E": "东", "NE": "东北", "SE": "东南", "W": "西",
    "NW": "西北", "SW": "西南", "N": "北", "S": "南",
}


@dataclass
class Box:
    x0: float
    y0: float
    x1: float
    y1: float
    tag: str = ""

    def overlaps(self, other: "Box", pad: float = 0.0) -> bool:
        return not (self.x1 + pad <= other.x0 or other.x1 + pad <= self.x0
                    or self.y1 + pad <= other.y0 or other.y1 + pad <= self.y0)

    def as_list(self):
        return [round(self.x0, 3), round(self.y0, 3), round(self.x1, 3), round(self.y1, 3)]


@dataclass
class Placement:
    place_id: str
    text: str
    box: Box
    anchor: str
    font_key: str
    size_pt: float
    color: str
    baseline_offset: float
    overridden: bool = False

    @property
    def x(self) -> float:
        return self.box.x0

    @property
    def baseline(self) -> float:
        return self.box.y0 + self.baseline_offset


def anchored_box(mx: float, my: float, w: float, h: float, anchor: str, gap: float) -> Box:
    """按方位把 w×h 的文字盒摆到标记点周围。"""
    # 对角方位在两个轴上都要让开标记符号，故偏移量不能小于正交方位的间距
    diag = gap * 0.95
    if anchor == "E":
        x0, y0 = mx + gap, my - h / 2.0
    elif anchor == "W":
        x0, y0 = mx - gap - w, my - h / 2.0
    elif anchor == "N":
        x0, y0 = mx - w / 2.0, my - gap - h
    elif anchor == "S":
        x0, y0 = mx - w / 2.0, my + gap
    elif anchor == "NE":
        x0, y0 = mx + diag, my - diag - h
    elif anchor == "SE":
        x0, y0 = mx + diag, my + diag
    elif anchor == "NW":
        x0, y0 = mx - diag - w, my - diag - h
    elif anchor == "SW":
        x0, y0 = mx - diag - w, my + diag
    else:
        raise ValueError(f"未知方位：{anchor}")
    return Box(x0, y0, x0 + w, y0 + h)


class LabelPlanner:
    """按重要级别依次放置标签；无解时抛出可操作的错误。"""

    def __init__(self, frame, pad_mm: float = 0.6, edge_pad_mm: float = 1.2):
        self.frame = frame
        self.pad = pad_mm
        self.edge_pad = edge_pad_mm
        self.obstacles: list = []      # 标记符号等固定障碍
        self.boxes: list = []          # 已放置文字盒
        self.placements: list = []

    def add_obstacle(self, box: Box) -> None:
        self.obstacles.append(box)

    def add_fixed_text(self, box: Box) -> None:
        self.boxes.append(box)

    def _blocker(self, box: Box):
        """返回阻挡该位置的原因；无阻挡时返回 None。"""
        f = self.frame
        if not (f.fx + self.edge_pad <= box.x0 and box.x1 <= f.fx + f.fw - self.edge_pad
                and f.fy + self.edge_pad <= box.y0 and box.y1 <= f.fy + f.fh - self.edge_pad):
            return "越出页面"
        for other in self.boxes:
            if box.overlaps(other, self.pad):
                return f"文字「{other.tag}」"
        for other in self.obstacles:
            if box.overlaps(other, self.pad * 0.5):
                return f"符号「{other.tag}」"
        return None

    def _fits(self, box: Box) -> bool:
        return self._blocker(box) is None

    def place(self, *, place_id, text, mx, my, w, h, baseline_offset, gap,
              font_key, size_pt, color, anchor="", dx=None, dy=None) -> Placement:
        if anchor:
            box = anchored_box(mx, my, w, h, anchor, gap)
            if dx or dy:
                box = Box(box.x0 + (dx or 0.0), box.y0 + (dy or 0.0),
                          box.x1 + (dx or 0.0), box.y1 + (dy or 0.0))
            chosen, overridden = anchor, True
        else:
            chosen, box, overridden = None, None, False
            blocked = []
            for cand in ANCHOR_ORDER:
                trial = anchored_box(mx, my, w, h, cand, gap)
                reason = self._blocker(trial)
                if reason is None:
                    chosen, box = cand, trial
                    break
                blocked.append(f"{ANCHOR_NAMES[cand]}被{reason}挡住")
            if chosen is None:
                raise LabelConflict(place_id, text, blocked)
        box.tag = place_id
        self.boxes.append(box)
        p = Placement(place_id, text, box, chosen, font_key, size_pt, color,
                      baseline_offset, overridden)
        self.placements.append(p)
        return p


class LabelConflict(RuntimeError):
    def __init__(self, place_id: str, text: str, blocked=()):
        detail = ("\n  " + "\n  ".join(blocked)) if blocked else ""
        super().__init__(
            f"标签「{text}」（{place_id}）在八个方位均无法无碰撞放置；"
            f"请在 data/map_places.csv 中为其显式指定 anchor 与 dx_mm/dy_mm 覆写。"
            + detail)
        self.place_id = place_id
        self.text = text
        self.blocked = list(blocked)
