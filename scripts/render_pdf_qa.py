"""把合并 PDF 逐页渲染为 300 dpi PNG，供人工核查。

这是核查辅助脚本，pypdfium2 不属于工程依赖，用法：
    uv run --with pypdfium2 python scripts/render_pdf_qa.py
"""
import sys
from pathlib import Path

import pypdfium2 as pdfium

PDF = Path("output/pdf/classical-greece-atlas.pdf")
OUT = Path("build/qa")


def main() -> int:
    if not PDF.exists():
        print(f"找不到 {PDF}，请先运行 atlas.build --all")
        return 1
    OUT.mkdir(parents=True, exist_ok=True)
    doc = pdfium.PdfDocument(PDF)
    print(f"PDF 共 {len(doc)} 页")
    for i, page in enumerate(doc, start=1):
        w_pt, h_pt = page.get_size()
        image = page.render(scale=300 / 72).to_pil()
        path = OUT / f"pdf-page{i}-300dpi.png"
        image.save(path)
        print(f"  第 {i} 页 {w_pt:.1f}×{h_pt:.1f} pt "
              f"（{w_pt / 72 * 25.4:.1f}×{h_pt / 72 * 25.4:.1f} mm）"
              f" -> {path.name} {image.width}×{image.height} 像素")
    return 0


if __name__ == "__main__":
    sys.exit(main())
