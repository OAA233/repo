#!/usr/bin/env python3
"""把任意截图适配成 Sileo 介绍页的 260×563 展示框。

Sileo 的 `DepictionScreenshotsView` 用固定尺寸（`build_repo.py` 里写死 `itemSize: 260×563`）。
丢进去比例不对的图会被**裁切**，横图基本只剩中间一条。

这个脚本的做法：把原图放大到铺满整块画布 → 高斯模糊 + 压暗当背景，
再把原图按宽度等比缩放居中贴上去（圆角 + 细边框）。
结果是完整的 260×563 画布，图本身一像素没丢，四周是它的模糊放大版，看起来像一张卡片。

用法:
    python3 tools/fit_shot.py <输入图> [输出图]
    python3 tools/fit_shot.py --check            # 只检查 shots/ 下所有图的比例
原图会被备份到 tools/originals/<文件名>（tools/ 不会被部署上去）。
"""
import os
import shutil
import sys

from PIL import Image, ImageDraw, ImageFilter

W, H = 260, 563          # Sileo 展示框
K = 4                    # 超采样倍数
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKUP = os.path.join(ROOT, "tools", "originals")


def cover(im, w, h):
    """等比缩放到完全覆盖 w×h，再居中裁掉多出来的部分。"""
    scale = max(w / im.width, h / im.height)
    im = im.resize((max(1, round(im.width * scale)), max(1, round(im.height * scale))), Image.LANCZOS)
    left = (im.width - w) // 2
    top = (im.height - h) // 2
    return im.crop((left, top, left + w, top + h))


def fit(src, dst=None):
    dst = dst or src
    im = Image.open(src).convert("RGB")
    if abs(im.width / im.height - W / H) < 0.01:
        print(f"  = {os.path.relpath(src, ROOT)} 比例已对，跳过")
        return False

    cw, ch = W * K, H * K
    canvas = cover(im, cw, ch).filter(ImageFilter.GaussianBlur(K * 14))
    # 压暗 + 轻微去饱和，别让背景抢主体
    canvas = Image.blend(canvas, Image.new("RGB", canvas.size, (10, 11, 15)), 0.55)

    # 主体：按宽度缩到 90%，居中
    margin = round(cw * 0.05)
    tw = cw - margin * 2
    th = round(im.height * tw / im.width)
    if th > ch - margin * 2:                      # 太高就改成按高度缩
        th = ch - margin * 2
        tw = round(im.width * th / im.height)
    card = im.resize((tw, th), Image.LANCZOS)

    # 圆角 + 细边框
    mask = Image.new("L", (tw, th), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, tw - 1, th - 1), radius=round(cw * 0.045), fill=255)
    border = Image.new("RGB", (tw, th), (255, 255, 255))
    bmask = Image.new("L", (tw, th), 0)
    ImageDraw.Draw(bmask).rounded_rectangle((0, 0, tw - 1, th - 1), radius=round(cw * 0.045),
                                            outline=255, width=max(1, K))
    canvas.paste(border, ((cw - tw) // 2, (ch - th) // 2), bmask)
    canvas.paste(card, ((cw - tw) // 2, (ch - th) // 2), mask)

    os.makedirs(BACKUP, exist_ok=True)
    shutil.copy2(src, os.path.join(BACKUP, os.path.basename(src)))
    canvas.resize((W, H), Image.LANCZOS).save(dst)
    print(f"  + {os.path.relpath(dst, ROOT)}  {im.width}×{im.height} → {W}×{H}"
          f"（原图备份在 tools/originals/）")
    return True


def check():
    shots = os.path.join(ROOT, "shots")
    target = W / H
    bad = 0
    for pkg in sorted(os.listdir(shots)):
        d = os.path.join(shots, pkg)
        if not os.path.isdir(d):
            continue
        for n in sorted(os.listdir(d)):
            if not n.lower().endswith((".png", ".jpg", ".jpeg")):
                continue
            im = Image.open(os.path.join(d, n))
            r = im.width / im.height
            ok = abs(r - target) < 0.05
            bad += 0 if ok else 1
            print(f"  {'✅' if ok else '⚠️ '} {pkg}/{n}  {im.width}×{im.height}  比例 {r:.3f}")
    print(f"  {bad} 张比例不对（会被 Sileo 裁切），用本脚本修：python3 tools/fit_shot.py <图>")
    return bad


if __name__ == "__main__":
    args = [a for a in sys.argv[1:]]
    if args and args[0] == "--check":
        sys.exit(1 if check() else 0)
    if not args:
        sys.exit(__doc__)
    fit(args[0], args[1] if len(args) > 1 else None)
