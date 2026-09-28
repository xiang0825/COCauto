"""把控制台几何标志绘制为 Windows 多尺寸图标。"""
from pathlib import Path

from PIL import Image, ImageDraw


def 生成(图标路径: Path):
    倍率 = 4
    画布 = Image.new("RGBA", (256 * 倍率, 256 * 倍率), (0, 0, 0, 0))
    画笔 = ImageDraw.Draw(画布)

    def 点列(点):
        return [(int(x * 倍率), int(y * 倍率)) for x, y in 点]

    画笔.rounded_rectangle((8 * 倍率, 8 * 倍率, 248 * 倍率, 248 * 倍率),
                         radius=56 * 倍率, fill="#fff0e1")
    画笔.polygon(点列([(57, 190), (57, 92), (87, 92), (87, 69),
                     (113, 69), (113, 92), (141, 92), (141, 69),
                     (167, 69), (167, 92), (197, 92), (197, 190)]),
                fill="#c86c39")
    画笔.rectangle((111 * 倍率, 137 * 倍率, 143 * 倍率, 190 * 倍率), fill="#fff0e1")
    画笔.line((51 * 倍率, 192 * 倍率, 204 * 倍率, 192 * 倍率),
              fill="#8f4c2d", width=8 * 倍率)
    画布 = 画布.resize((256, 256), Image.Resampling.LANCZOS)
    图标路径.parent.mkdir(parents=True, exist_ok=True)
    画布.save(图标路径, format="ICO", sizes=[(16, 16), (24, 24), (32, 32),
                                             (48, 48), (64, 64), (128, 128), (256, 256)])


if __name__ == "__main__":
    生成(Path(__file__).with_name("城控.ico"))
