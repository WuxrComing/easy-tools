"""
生成 PDF 转长图工具的图标。
运行后在 assets/ 目录生成 pdf_tool.ico (Windows) 和 pdf_tool.png (各尺寸)。
"""
import os
from PIL import Image, ImageDraw

SIZES = [16, 32, 48, 64, 128, 256]
OUT_DIR = os.path.join(os.path.dirname(__file__), "assets")
os.makedirs(OUT_DIR, exist_ok=True)


def draw_rounded_rect(draw, xy, radius, fill, outline=None, outline_width=1):
    x0, y0, x1, y1 = xy
    draw.rounded_rectangle([x0, y0, x1, y1], radius=radius, fill=fill,
                            outline=outline, width=outline_width)


def render(size: int) -> Image.Image:
    s = size
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    pad = max(2, round(s * 0.04))
    r = max(3, round(s * 0.12))

    # ── 背景圆角矩形 ──────────────────────────────────────────
    bg = (242, 101, 70, 255)        # 温暖橙红
    draw_rounded_rect(d, [pad, pad, s - pad - 1, s - pad - 1], r,
                      fill=bg, outline=(210, 75, 50, 255),
                      outline_width=max(1, round(s * 0.025)))

    # ── PDF 文档（左半区） ────────────────────────────────────
    doc_margin = round(s * 0.10)
    doc_l = doc_margin
    doc_r = round(s * 0.44)
    doc_t = round(s * 0.14)
    doc_b = round(s * 0.86)
    fold = round(s * 0.15)          # 折角大小

    # 文档主体（白色）
    doc_poly = [
        (doc_l, doc_t),
        (doc_r - fold, doc_t),
        (doc_r, doc_t + fold),
        (doc_r, doc_b),
        (doc_l, doc_b),
    ]
    d.polygon(doc_poly, fill=(255, 255, 255, 240))

    # 折角三角形（略深白）
    d.polygon([
        (doc_r - fold, doc_t),
        (doc_r, doc_t + fold),
        (doc_r - fold, doc_t + fold),
    ], fill=(220, 220, 220, 240))

    # "PDF" 文字线条（模拟三条横线）
    lw = max(1, round(s * 0.045))
    lx0 = doc_l + round(s * 0.06)
    lx1 = doc_r - round(s * 0.10)
    for i, frac in enumerate([0.52, 0.63, 0.74]):
        ly = round(s * frac)
        d.line([(lx0, ly), (lx1, ly)], fill=(210, 75, 50, 200), width=lw)

    # "P" 字标记
    mark_size = round(s * 0.18)
    mark_x = doc_l + round(s * 0.055)
    mark_y = doc_t + round(s * 0.09)
    d.rectangle([mark_x, mark_y,
                 mark_x + mark_size, mark_y + round(s * 0.13)],
                fill=(210, 75, 50, 220))

    # ── 箭头（中间） ──────────────────────────────────────────
    ay_center = round(s * 0.50)
    # 水平箭头：从文档指向预览区域
    arr_l = round(s * 0.455)
    arr_r = round(s * 0.545)
    arr_cy = ay_center
    bar_h = max(2, round(s * 0.09))
    tip_w = max(3, round(s * 0.09))
    tip_h = max(3, round(s * 0.16))

    d.rectangle([arr_l, arr_cy - bar_h // 2,
                 arr_r - tip_w // 2, arr_cy + bar_h // 2],
                fill=(255, 255, 255, 230))
    d.polygon([
        (arr_r, arr_cy),
        (arr_r - tip_w, arr_cy - tip_h // 2),
        (arr_r - tip_w, arr_cy + tip_h // 2),
    ], fill=(255, 255, 255, 230))

    # ── 图片预览（右半区） ────────────────────────────────────
    img_l = round(s * 0.56)
    img_r = s - doc_margin
    img_t = doc_t
    img_b = doc_b
    img_r2 = max(2, round(s * 0.08))
    draw_rounded_rect(d, [img_l, img_t, img_r, img_b], img_r2,
                      fill=(255, 255, 255, 230))

    # 天空渐变（蓝色矩形）
    sky_b = img_t + round((img_b - img_t) * 0.55)
    draw_rounded_rect(d, [img_l + 2, img_t + 2, img_r - 2, sky_b], img_r2 - 1,
                      fill=(110, 185, 230, 220))

    # 山形轮廓
    mtn_y_base = sky_b
    mtn_pts = [
        (img_l + 2, mtn_y_base),
        (img_l + round((img_r - img_l) * 0.25), img_t + round((img_b - img_t) * 0.28)),
        (img_l + round((img_r - img_l) * 0.50), mtn_y_base),
        (img_l + round((img_r - img_l) * 0.65), img_t + round((img_b - img_t) * 0.40)),
        (img_r - 2, mtn_y_base),
    ]
    d.polygon(mtn_pts, fill=(80, 150, 90, 230))

    # 底部草地
    draw_rounded_rect(d, [img_l + 2, mtn_y_base, img_r - 2, img_b - 2], img_r2 - 1,
                      fill=(100, 170, 100, 220))

    # 太阳
    sun_r = max(2, round(s * 0.06))
    sun_cx = img_l + round((img_r - img_l) * 0.75)
    sun_cy = img_t + round((img_b - img_t) * 0.22)
    d.ellipse([sun_cx - sun_r, sun_cy - sun_r,
               sun_cx + sun_r, sun_cy + sun_r],
              fill=(255, 230, 80, 230))

    return img


images = []
for sz in SIZES:
    icon_img = render(sz)
    images.append(icon_img)
    out_path = os.path.join(OUT_DIR, f"pdf_tool_{sz}.png")
    icon_img.save(out_path, "PNG")
    print(f"  saved {out_path}")

# 保存主图标（256px）
main_path = os.path.join(OUT_DIR, "pdf_tool.png")
images[-1].save(main_path, "PNG")
print(f"  saved {main_path}")

# 保存 .ico（包含多尺寸，Windows 用）
ico_path = os.path.join(OUT_DIR, "pdf_tool.ico")
images[-1].save(ico_path, format="ICO",
                sizes=[(sz, sz) for sz in SIZES])
print(f"  saved {ico_path}")

print("Done.")
