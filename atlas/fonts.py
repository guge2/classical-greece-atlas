"""字体处理：可变字体实例化、文字度量与可复用字形路径。

SVG 输出把实际用到的汉字转为字形路径（<defs> 中一次定义、<use> 复用）；
PDF 输出直接使用同一批静态实例字体，由 matplotlib 嵌入字体子集。
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from fontTools import subset
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.ttLib import TTFont
from fontTools.varLib import instancer

from . import config as C

# CJK 字面在 em 框内的近似垂直中心（相对基线，单位 em）
VCENTER_EM = 0.36
# 版面碰撞盒的上下边界（相对基线，单位 em）
BOX_TOP_EM = 0.86
BOX_BOTTOM_EM = 0.14


def _system_font(name: str) -> Path:
    path = C.FONT_DIR_SYSTEM / name
    if not path.exists():
        raise SystemExit(f"缺少系统字体：{path}（需要 Noto Serif SC 与 Noto Sans SC）")
    return path


@lru_cache(maxsize=None)
def static_instance(key: str) -> Path:
    """把可变字体实例化为静态 TTF 并缓存，返回文件路径。"""
    if key not in C.FONT_SPECS:
        raise KeyError(f"未定义的字体逻辑名：{key}")
    filename, axes = C.FONT_SPECS[key]
    C.FONT_CACHE.mkdir(parents=True, exist_ok=True)
    out = C.FONT_CACHE / f"{key}.ttf"
    src = _system_font(filename)
    if out.exists() and out.stat().st_mtime >= src.stat().st_mtime:
        return out
    font = TTFont(src)
    if "fvar" in font:
        font = instancer.instantiateVariableFont(font, axes, inplace=False, updateFontNames=True)
    font.save(out)
    font.close()
    return out


@lru_cache(maxsize=None)
def _font(key: str) -> TTFont:
    return TTFont(static_instance(key))


@lru_cache(maxsize=None)
def _glyph_set(key: str):
    return _font(key).getGlyphSet()


@lru_cache(maxsize=None)
def _cmap(key: str):
    return _font(key).getBestCmap()


@lru_cache(maxsize=None)
def _glyph_path(key: str, glyph_name: str) -> str:
    glyph_set = _glyph_set(key)
    pen = SVGPathPen(glyph_set)
    glyph_set[glyph_name].draw(pen)
    return pen.getCommands()


@dataclass(frozen=True)
class Glyph:
    key: str          # 字体逻辑名
    name: str         # 字形名
    advance: int      # 字形宽度（字体单位）


class FontBook:
    """按逻辑名提供度量与字形路径，并记录实际用到的字形。"""

    def __init__(self):
        self.used: dict[str, set] = {}

    def upem(self, key: str) -> int:
        return _font(key)["head"].unitsPerEm

    def glyphs(self, key: str, text: str) -> list:
        font = _font(key)
        cmap = _cmap(key)
        hmtx = font["hmtx"]
        out = []
        for ch in text:
            name = cmap.get(ord(ch))
            if name is None:
                raise SystemExit(f"字体 {key} 缺少字符 “{ch}”（U+{ord(ch):04X}）")
            out.append(Glyph(key, name, hmtx[name][0]))
            self.used.setdefault(key, set()).add(name)
        return out

    def advance_units(self, key: str, text: str) -> int:
        return sum(g.advance for g in self.glyphs(key, text))

    def text_width_mm(self, key: str, text: str, size_pt: float, tracking_em: float = 0.0) -> float:
        size_mm = size_pt * C.PT_TO_MM
        units = self.advance_units(key, text)
        width = units / self.upem(key) * size_mm
        if tracking_em and len(text) > 1:
            width += tracking_em * size_mm * (len(text) - 1)
        return width

    def path_data(self, key: str, glyph_name: str) -> str:
        return _glyph_path(key, glyph_name)

    # -------------------------------------------------------------- PDF 字体子集
    def subset_font(self, key: str, out_path: Path) -> Path:
        """按已用字形导出子集字体（供 PDF 嵌入与体积核算）。"""
        names = sorted(self.used.get(key, set()))
        font = TTFont(static_instance(key))
        subsetter = subset.Subsetter(options=subset.Options(
            layout_features=[], notdef_outline=True, recalc_bounds=True))
        subsetter.populate(glyphs=names)
        subsetter.subset(font)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        font.save(out_path)
        font.close()
        return out_path


def text_box_mm(width_mm: float, size_pt: float):
    """返回 (宽, 高, 基线到盒顶距离)。"""
    size_mm = size_pt * C.PT_TO_MM
    return width_mm, (BOX_TOP_EM + BOX_BOTTOM_EM) * size_mm, BOX_TOP_EM * size_mm
