"""把 logo SVG 渲染成多尺寸 PNG 并打包为 Windows .ico（方案文档附带，未接入构建）。

用法（需要 PySide6 + Pillow，项目打包环境里都有）：
    python 生成图标.py L1-城垛.svg 城控.ico

每个尺寸单独从矢量渲染（而不是从 256 缩小），16/24/32 更清楚；
如果同目录有 <名>-16.svg 这类手调小尺寸版本，会优先使用。
"""
import sys
from pathlib import Path

from PIL import Image
from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

尺寸 = (16, 20, 24, 32, 40, 48, 64, 128, 256)


def 渲染(svg: Path, 边长: int) -> Image.Image:
    手调 = svg.with_name(f"{svg.stem}-{边长}.svg")
    渲染器 = QSvgRenderer(str(手调 if 手调.exists() else svg))
    图 = QImage(边长, 边长, QImage.Format_RGBA8888)
    图.fill(Qt.transparent)
    画笔 = QPainter(图)
    画笔.setRenderHint(QPainter.Antialiasing)
    渲染器.render(画笔)
    画笔.end()
    return Image.frombuffer("RGBA", (边长, 边长), bytes(图.constBits()), "raw", "RGBA", 0, 1).copy()


def main(源: str, 目标: str):
    QGuiApplication.instance() or QGuiApplication([])
    图组 = [渲染(Path(源), 边长) for 边长 in 尺寸]
    最大 = 图组[-1]
    # Pillow ≥ 10.1：append_images 让每个尺寸用自己的渲染结果，而不是从 256 缩小。
    最大.save(目标, format="ICO", sizes=[(s, s) for s in 尺寸], append_images=图组[:-1])
    print("已生成", 目标)


if __name__ == "__main__":
    main(*sys.argv[1:3])
