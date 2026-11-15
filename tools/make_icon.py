"""画一个应用图标（深底 + 信号条 + 查询点），输出多尺寸 .ico。

    python tools/make_icon.py            # -> assets/neoprobe.ico

图标含义：底座是"服务器"，三根逐渐升高的信号条是"探测/在线状态"，
右上角的亮点是"正在查询"。在 16px 下也能认出是"信号"。
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "assets" / "neoprobe.ico"

BG_TOP = (32, 38, 52)        # 深墨蓝
BG_BOTTOM = (22, 26, 36)
GREEN = (86, 214, 146)       # 在线绿
DIM = (70, 84, 104)          # 未探测


def render(size: int = 512) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # 圆角底板（竖向渐变用逐行绘制）
    radius = int(size * 0.22)
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, size - 1, size - 1], radius=radius, fill=255)
    grad = Image.new("RGB", (1, size))
    gd = ImageDraw.Draw(grad)
    for y in range(size):
        t = y / max(1, size - 1)
        gd.point((0, y), tuple(int(BG_TOP[i] + (BG_BOTTOM[i] - BG_TOP[i]) * t) for i in range(3)))
    img.paste(grad.resize((size, size)), (0, 0), mask)

    # 三根信号条：前两根暗、第三根亮（"正在探测到这里"）
    bar_w = int(size * 0.135)
    gap = int(size * 0.075)
    total = bar_w * 3 + gap * 2
    x0 = (size - total) // 2
    base_y = int(size * 0.775)
    heights = [0.26, 0.44, 0.60]
    colors = [DIM, DIM, GREEN]
    r = max(2, int(bar_w * 0.34))
    for i, (h, c) in enumerate(zip(heights, colors)):
        x = x0 + i * (bar_w + gap)
        top = base_y - int(size * h)
        d.rounded_rectangle([x, top, x + bar_w, base_y], radius=r, fill=c)

    # 不再加悬浮圆点：16px 下它会退化成噪点，也容易和第 3 根条读成一个感叹号。
    # 三根条本身（灰 / 灰 / 绿）+ 底座已经足够表达"在多台服务器里，这台是通的"。

    # 底部一条细线，像"底座/机架"
    d.rounded_rectangle([x0, base_y + int(size * 0.035), x0 + total, base_y + int(size * 0.052)],
                        radius=max(2, int(size * 0.008)), fill=(96, 112, 138))
    return img


def main() -> int:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    big = render(512)
    sizes = [(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)]
    big.resize((256, 256), Image.LANCZOS).save(
        OUT, format="ICO", sizes=sizes)
    print(f"图标: {OUT} ({OUT.stat().st_size / 1024:.1f} KB)  尺寸 {[s[0] for s in sizes]}")
    # 顺手留一张 png 方便预览
    png = OUT.with_suffix(".png")
    big.resize((256, 256), Image.LANCZOS).save(png)
    print(f"预览: {png}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
