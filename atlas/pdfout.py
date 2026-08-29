"""PDF / PNG 后端：与 SVG 共用同一场景，PDF 嵌入字体子集。"""
from __future__ import annotations

from pathlib import Path

import matplotlib
import numpy as np

matplotlib.use("Agg")

import matplotlib.pyplot as plt                                    # noqa: E402
from matplotlib import patheffects                                 # noqa: E402
from matplotlib.backends.backend_pdf import PdfPages               # noqa: E402
from matplotlib.font_manager import FontProperties                 # noqa: E402
from matplotlib.patches import Circle as MplCircle                 # noqa: E402
from matplotlib.patches import PathPatch, Polygon, Rectangle       # noqa: E402
from matplotlib.path import Path as MplPath                        # noqa: E402
from PIL import Image as PILImage                                  # noqa: E402

from . import config as C
from . import fonts as F
from . import scene as SC

matplotlib.rcParams["pdf.fonttype"] = 42        # TrueType，按用字嵌入子集
matplotlib.rcParams["pdf.compression"] = 9
matplotlib.rcParams["svg.fonttype"] = "path"


def _lw(mm: float) -> float:
    """毫米线宽 -> 磅。"""
    return mm / 25.4 * 72.0


def _compound_path(rings) -> MplPath:
    verts, codes = [], []
    for exterior, holes in rings:
        for ring in [exterior, *holes]:
            pts = np.asarray(ring)
            verts.append(pts)
            codes.append(np.concatenate(([MplPath.MOVETO],
                                         np.full(len(pts) - 1, MplPath.LINETO))))
    if not verts:
        return MplPath(np.zeros((0, 2)))
    return MplPath(np.concatenate(verts), np.concatenate(codes))


def _font(key: str, size_pt: float) -> FontProperties:
    return FontProperties(fname=str(F.static_instance(key)), size=size_pt)


def draw_scene(scene: SC.Scene, ax, book: F.FontBook) -> None:
    land_path = _compound_path(scene.land_rings)
    frame = scene.spec.frame
    fx, fy, fw, fh = frame.fx, frame.fy, frame.fw, frame.fh
    frame_path = MplPath([(fx, fy), (fx + fw, fy), (fx + fw, fy + fh),
                          (fx, fy + fh), (fx, fy)], closed=True)

    for z, item in enumerate(scene.layers, start=2):
        if isinstance(item, SC.Rect):
            ax.add_patch(Rectangle(
                (item.x, item.y), item.w, item.h,
                facecolor=item.fill if item.fill != "none" else "none",
                edgecolor=item.stroke if item.stroke != "none" else "none",
                linewidth=_lw(item.stroke_w), zorder=z))
        elif isinstance(item, SC.Polys):
            patch = PathPatch(
                _compound_path(item.rings),
                facecolor=item.fill if item.fill != "none" else "none",
                edgecolor=item.stroke if item.stroke != "none" else "none",
                linewidth=_lw(item.stroke_w), joinstyle="round", zorder=z)
            ax.add_patch(patch)
            patch.set_clip_path(frame_path, ax.transData)
        elif isinstance(item, SC.Image):
            arr = np.asarray(PILImage.open(item.path).convert("L"), dtype=float) / 255.0
            im = ax.imshow(arr, cmap="gray", vmin=0.0, vmax=1.0,
                           extent=(item.x, item.x + item.w, item.y + item.h, item.y),
                           origin="upper", alpha=item.opacity, interpolation="bilinear",
                           zorder=z, aspect="auto")
            im.set_clip_path(land_path, ax.transData)
        elif isinstance(item, SC.Circle):
            ax.add_patch(MplCircle(
                (item.cx, item.cy), item.r,
                facecolor=item.fill if item.fill != "none" else "none",
                edgecolor=item.stroke if item.stroke != "none" else "none",
                linewidth=_lw(item.stroke_w), zorder=z))
        elif isinstance(item, SC.Polyline):
            pts = np.asarray(item.points, dtype=float)
            if item.close:
                ax.add_patch(Polygon(
                    pts, closed=True,
                    facecolor=item.fill if item.fill != "none" else "none",
                    edgecolor=item.stroke, linewidth=_lw(item.stroke_w),
                    joinstyle="round", zorder=z))
            else:
                ax.plot(pts[:, 0], pts[:, 1], color=item.stroke,
                        linewidth=_lw(item.stroke_w), solid_capstyle="round", zorder=z)
        elif isinstance(item, SC.Text):
            _draw_text(ax, item, book, z)
        else:
            raise TypeError(f"未知绘图元素：{type(item)!r}")


def _draw_text(ax, t: SC.Text, book: F.FontBook, z: int) -> None:
    """逐字定位，字距与对齐方式与 SVG 后端完全一致。"""
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
    prop = _font(t.font_key, t.size_pt)
    # 光晕单独画一遍。matplotlib 一旦给文字加 path effect 就改用路径绘制，
    # 与正文合用会让 PDF 不再嵌入字体子集；因此正文一遍不带任何 path effect。
    passes = []
    if t.halo_mm:
        passes.append((C.PAPER, [patheffects.withStroke(
            linewidth=_lw(t.halo_mm), foreground=C.PAPER)], 0.82))
    passes.append((t.color, None, None))
    cursor = 0.0
    for ch, g in zip(t.text, glyphs):
        if not ch.isspace():
            for color, effects, alpha in passes:
                ax.text(x + cursor * k, t.baseline, ch, fontproperties=prop, color=color,
                        ha="left", va="baseline", zorder=z, path_effects=effects,
                        alpha=alpha)
        cursor += g.advance + tracking_units


def make_figure(scene: SC.Scene, book: F.FontBook):
    fig = plt.figure(figsize=(C.PAGE_W_MM / 25.4, C.PAGE_H_MM / 25.4))
    ax = fig.add_axes((0.0, 0.0, 1.0, 1.0))
    ax.set_xlim(0.0, C.PAGE_W_MM)
    ax.set_ylim(C.PAGE_H_MM, 0.0)
    ax.set_axis_off()
    ax.set_facecolor(C.PAPER)
    fig.patch.set_facecolor(C.PAPER)
    draw_scene(scene, ax, book)
    return fig


def save_pdf(scenes, book: F.FontBook, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with PdfPages(path) as pdf:
        for scene in scenes:
            fig = make_figure(scene, book)
            pdf.savefig(fig, facecolor=C.PAPER)
            plt.close(fig)
        info = pdf.infodict()
        info["Title"] = "古典希腊中文静态地图集"
        info["Subject"] = "公元前五世纪古典希腊地理（Natural Earth / Pleiades）"
        info["Creator"] = "classical-greece-atlas"
    return path


def save_png(scene: SC.Scene, book: F.FontBook, path: Path, dpi: int = 300,
             grayscale: bool = False) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig = make_figure(scene, book)
    fig.savefig(path, dpi=dpi, facecolor=C.PAPER)
    plt.close(fig)
    if grayscale:
        PILImage.open(path).convert("L").save(path)
    return path
