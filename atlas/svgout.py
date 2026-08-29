"""SVG 后端：自包含、无远程资源，文字转为可复用字形路径。"""
from __future__ import annotations

import base64
from pathlib import Path
from xml.sax.saxutils import escape

from scour import scour

from . import config as C
from . import fonts as F
from . import scene as SC

PRECISION = 2          # 页面毫米坐标保留位数（0.01 mm）
SIGNIFICANT = 7        # 缩放因子等极小数值保留的有效位数


def _n(v: float) -> str:
    """页面坐标格式化（毫米，两位小数）。"""
    s = f"{v:.{PRECISION}f}".rstrip("0").rstrip(".")
    return s if s not in ("", "-0") else "0"


def _f(v: float) -> str:
    """按有效位数格式化：字号缩放因子约 0.003，固定小数位会被舍成 0。"""
    return f"{v:.{SIGNIFICANT}g}"


def _ring_path(exterior, holes) -> str:
    parts = []
    for ring in [exterior, *holes]:
        pts = ring
        parts.append("M" + " ".join(f"{_n(x)} {_n(y)}" for x, y in pts) + "Z")
    return "".join(parts)


class SvgWriter:
    def __init__(self, book: F.FontBook):
        self.book = book
        self.glyph_defs: dict[str, str] = {}

    # ------------------------------------------------------------ 文字
    def _glyph_id(self, font_key: str, glyph_name: str) -> str:
        gid = f"g{font_key.replace('-', '')}_{glyph_name}"
        gid = "".join(ch if (ch.isalnum() or ch == "_") else "_" for ch in gid)
        if gid not in self.glyph_defs:
            self.glyph_defs[gid] = self.book.path_data(font_key, glyph_name)
        return gid

    def _text_group(self, t: SC.Text, halo: bool) -> str:
        book = self.book
        upem = book.upem(t.font_key)
        size_mm = t.size_pt * C.PT_TO_MM
        k = size_mm / upem
        glyphs = book.glyphs(t.font_key, t.text)
        tracking_units = t.tracking_em * upem
        width_units = sum(g.advance for g in glyphs)
        if len(glyphs) > 1:
            width_units += tracking_units * (len(glyphs) - 1)
        x = t.x
        if t.align == "middle":
            x -= width_units * k / 2.0
        elif t.align == "end":
            x -= width_units * k
        uses, cursor = [], 0.0
        for g in glyphs:
            data = book.path_data(t.font_key, g.name)
            if data:                                        # 跳过空白字形
                gid = self._glyph_id(t.font_key, g.name)
                uses.append(f'<use xlink:href="#{gid}" x="{_n(cursor)}"/>')
            cursor += g.advance + tracking_units
        if not uses:
            return ""
        transform = f'transform="translate({_n(x)} {_n(t.baseline)}) scale({_f(k)} {_f(-k)})"'
        if halo:
            stroke_units = (t.halo_mm / k) if k else 0.0
            attrs = (f'fill="{C.PAPER}" stroke="{C.PAPER}" '
                     f'stroke-width="{stroke_units:.1f}" stroke-linejoin="round" '
                     f'opacity="0.82"')
        else:
            attrs = f'fill="{t.color}"'
        return f'<g {transform} {attrs}>' + "".join(uses) + "</g>"

    # ------------------------------------------------------------ 元素
    def _item(self, item) -> str:
        if isinstance(item, SC.Rect):
            style = []
            if item.fill != "none":
                style.append(f'fill="{item.fill}"')
            else:
                style.append('fill="none"')
            if item.stroke != "none":
                style.append(f'stroke="{item.stroke}" stroke-width="{_n(item.stroke_w)}"')
            return (f'<rect x="{_n(item.x)}" y="{_n(item.y)}" width="{_n(item.w)}" '
                    f'height="{_n(item.h)}" {" ".join(style)}/>')
        if isinstance(item, SC.Polys):
            d = "".join(_ring_path(ext, holes) for ext, holes in item.rings)
            style = [f'fill="{item.fill}"', 'fill-rule="evenodd"']
            if item.stroke != "none":
                style.append(f'stroke="{item.stroke}" stroke-width="{_n(item.stroke_w)}" '
                             'stroke-linejoin="round"')
            return f'<path clip-path="url(#frameClip)" d="{d}" {" ".join(style)}/>'
        if isinstance(item, SC.Image):
            payload = base64.b64encode(item.path.read_bytes()).decode("ascii")
            return (f'<image clip-path="url(#landClip)" x="{_n(item.x)}" y="{_n(item.y)}" '
                    f'width="{_n(item.w)}" height="{_n(item.h)}" opacity="{item.opacity}" '
                    f'preserveAspectRatio="none" image-rendering="optimizeQuality" '
                    f'xlink:href="data:image/png;base64,{payload}"/>')
        if isinstance(item, SC.Circle):
            return (f'<circle cx="{_n(item.cx)}" cy="{_n(item.cy)}" r="{_n(item.r)}" '
                    f'fill="{item.fill}" stroke="{item.stroke}" '
                    f'stroke-width="{_n(item.stroke_w)}"/>')
        if isinstance(item, SC.Polyline):
            pts = " ".join(f"{_n(x)},{_n(y)}" for x, y in item.points)
            tag = "polygon" if item.close else "polyline"
            return (f'<{tag} points="{pts}" fill="{item.fill}" stroke="{item.stroke}" '
                    f'stroke-width="{_n(item.stroke_w)}" stroke-linejoin="round" '
                    f'stroke-linecap="round"/>')
        if isinstance(item, SC.Text):
            out = ""
            if item.halo_mm:
                out += self._text_group(item, halo=True)
            return out + self._text_group(item, halo=False)
        raise TypeError(f"未知绘图元素：{type(item)!r}")

    # ------------------------------------------------------------ 输出
    def render(self, scene: SC.Scene) -> str:
        body = [self._item(i) for i in scene.layers]
        frame = scene.spec.frame
        land_d = "".join(_ring_path(ext, holes) for ext, holes in scene.land_rings)
        defs = [
            f'<clipPath id="frameClip"><rect x="{_n(frame.fx)}" y="{_n(frame.fy)}" '
            f'width="{_n(frame.fw)}" height="{_n(frame.fh)}"/></clipPath>',
            f'<clipPath id="landClip"><path d="{land_d}" clip-rule="evenodd"/></clipPath>',
        ]
        defs += [f'<path id="{gid}" d="{d}"/>' for gid, d in sorted(self.glyph_defs.items())]
        title = escape(f"{scene.spec.title} · {scene.spec.subtitle}")
        return (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
            f'width="{C.PAGE_W_MM}mm" height="{C.PAGE_H_MM}mm" '
            f'viewBox="0 0 {_n(C.PAGE_W_MM)} {_n(C.PAGE_H_MM)}" '
            'shape-rendering="geometricPrecision">'
            f'<title>{title}</title>'
            f'<defs>{"".join(defs)}</defs>'
            + "".join(body) +
            '</svg>\n'
        )


def write_svg(scene: SC.Scene, book: F.FontBook, path: Path, minify: bool = True) -> Path:
    writer = SvgWriter(book)
    text = writer.render(scene)
    if minify:
        options = scour.parse_args([
            "--set-precision=7", "--remove-metadata", "--enable-comment-stripping",
            "--no-line-breaks", "--disable-style-to-xml",
        ])
        text = scour.scourString(text, options)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path
