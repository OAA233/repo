#!/usr/bin/env python3
"""生成 Sileo 源里包列表用的 180×180 图标（透明底）。

用法: python3 tools/make_icons.py
产物: icons/<包名>.png

风格跟已有的三个图标对齐：深色圆角方底 + 白色手机主体 + 右下角圆形徽标。
4× 超采样再 LANCZOS 缩到 180，边缘才不会锯齿。
"""
import os
from PIL import Image, ImageDraw

S = 180          # 最终尺寸
K = 4            # 超采样倍数
W = S * K
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "icons")

INK = (18, 21, 28, 255)          # 底色渐变暗端
INK2 = (44, 50, 62, 255)         # 底色渐变亮端
BODY = (233, 236, 242, 255)      # 手机机身
BODY_EDGE = (176, 183, 196, 255)
BLUE = (59, 130, 246, 255)
RED = (239, 68, 68, 255)
WHITE = (250, 251, 253, 255)


def px(v):
    return v * W


def gradient(size, top, bottom):
    g = Image.new("RGBA", (1, size))
    d = ImageDraw.Draw(g)
    for y in range(size):
        t = y / max(size - 1, 1)
        d.point((0, y), tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(4)))
    return g.resize((size, size), Image.BILINEAR)


def squircle(canvas, box, radius, top, bottom):
    mask = Image.new("L", (W, W), 0)
    ImageDraw.Draw(mask).rounded_rectangle(box, radius=radius, fill=255)
    canvas.paste(gradient(W, top, bottom), (0, 0), mask)
    # 顶部一道极淡的高光，避免整块死平
    hi = Image.new("L", (W, W), 0)
    ImageDraw.Draw(hi).rounded_rectangle(box, radius=radius, outline=255, width=int(px(0.004)))
    canvas.paste(Image.new("RGBA", (W, W), (255, 255, 255, 26)), (0, 0), hi)


def phone(canvas, screen_top, screen_bottom):
    """机身 + 屏幕（屏幕用竖向渐变，dim/ka 的区别就靠这两个色）。"""
    d = ImageDraw.Draw(canvas)
    bx0, by0, bx1, by1 = px(0.27), px(0.13), px(0.73), px(0.83)
    d.rounded_rectangle((bx0, by0, bx1, by1), radius=px(0.075), fill=BODY,
                        outline=BODY_EDGE, width=int(px(0.006)))

    sx0, sy0, sx1, sy1 = px(0.292), px(0.152), px(0.708), px(0.808)
    mask = Image.new("L", (W, W), 0)
    ImageDraw.Draw(mask).rounded_rectangle((sx0, sy0, sx1, sy1), radius=px(0.058), fill=255)
    canvas.paste(gradient(W, screen_top, screen_bottom).crop((int(sx0), int(sy0), int(sx1), int(sy1))),
                 (int(sx0), int(sy0)), mask.crop((int(sx0), int(sy0), int(sx1), int(sy1))))

    # 灵动岛
    island = (px(0.435), px(0.178), px(0.565), px(0.198))
    d.rounded_rectangle(island, radius=px(0.010), fill=(255, 255, 255, 60))


def badge(canvas):
    """右下角圆形徽标，返回可继续画字的 draw。"""
    cx, cy, r = px(0.752), px(0.752), px(0.202)
    d = ImageDraw.Draw(canvas)
    d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=WHITE, outline=BLUE, width=int(px(0.022)))
    return d, cx, cy, r


def icon_dim(path):
    """com.a0.mirror17dim —— 连接时把屏幕压暗：屏幕由亮到黑 + 徽标里一个向下箭头。"""
    im = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    squircle(im, (px(0.018), px(0.018), px(0.982), px(0.982)), px(0.225), INK2, INK)
    phone(im, (108, 116, 136, 255), (8, 9, 13, 255))
    d, cx, cy, r = badge(im)
    # 向下箭头：竖杆 + 三角头
    d.rounded_rectangle((cx - px(0.026), cy - px(0.085), cx + px(0.026), cy + px(0.020)),
                        radius=px(0.026), fill=BLUE)
    d.polygon([(cx - px(0.082), cy + px(0.006)), (cx + px(0.082), cy + px(0.006)),
               (cx, cy + px(0.098))], fill=BLUE)
    im.resize((S, S), Image.LANCZOS).save(path)


def icon_ka(path):
    """com.a0.mirror17ka —— 投屏期间禁止自动锁屏：亮屏 + 徽标里被划掉的月亮（禁睡）。"""
    im = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    squircle(im, (px(0.018), px(0.018), px(0.982), px(0.982)), px(0.225), INK2, INK)
    phone(im, (255, 255, 255, 255), (214, 222, 236, 255))
    d, cx, cy, r = badge(im)
    # 月亮：蓝圆挖掉一个偏移的白圆
    mr = px(0.098)
    d.ellipse((cx - mr, cy - mr, cx + mr, cy + mr), fill=BLUE)
    d.ellipse((cx - mr + px(0.055), cy - mr - px(0.030), cx + mr + px(0.055), cy + mr - px(0.030)),
              fill=WHITE)
    # 禁止斜杠
    d.line((cx - px(0.125), cy + px(0.125), cx + px(0.125), cy - px(0.125)),
           fill=RED, width=int(px(0.030)))
    for p in ((cx - px(0.125), cy + px(0.125)), (cx + px(0.125), cy - px(0.125))):
        d.ellipse((p[0] - px(0.015), p[1] - px(0.015), p[0] + px(0.015), p[1] + px(0.015)), fill=RED)
    im.resize((S, S), Image.LANCZOS).save(path)


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    for name, fn in [("com.a0.mirror17dim", icon_dim), ("com.a0.mirror17ka", icon_ka)]:
        p = os.path.join(OUT, name + ".png")
        fn(p)
        print(f"  + {os.path.relpath(p, os.path.dirname(OUT))}  {Image.open(p).size}")
