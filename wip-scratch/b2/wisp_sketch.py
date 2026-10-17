"""疾影卷云造型的二维草图（迭代形状用）：设计稿单位，锚点原点。"""
import sys, math
sys.path.insert(0, '/home/user/mygame/art/post')
import numpy as np
from PIL import Image, ImageDraw
import enemy_design as DZ

S = 14
X0, Y0 = -22.0, 30.0
def P(p): return ((p[0] - X0) * S, (Y0 - p[1]) * S)
im = Image.new('RGB', (int(44 * S), int(36 * S)), (236, 228, 208))
d = ImageDraw.Draw(im)
# 地面、锚点
d.line([P((-22, 0)), P((22, 0))], fill=(150, 120, 100))
d.line([P((-20, -1)), P((-20, 35))], fill=(200, 180, 160)); d.line([P((20, -1)), P((20, 35))], fill=(200, 180, 160))
exec(open(sys.argv[2]).read())  # 定义 STROKES = [(ctrl, widths, color)], EYES
for ctrl, widths, col in STROKES:
    c = np.asarray(ctrl) if len(ctrl) > 30 else DZ.curve_pts(ctrl, 120)
    poly = DZ.stroke_poly(c, widths)
    d.polygon([P(p) for p in poly], fill=col)
for (ex, ey), hl, hh, tilt, col in EYES:
    a = math.radians(tilt)
    pts = [(hl, 0.0), (hl * 0.3, hh * 0.95), (-hl * 0.5, hh * 0.8), (-hl, 0.1 * hh), (-hl * 0.45, -hh * 0.7), (hl * 0.45, -hh * 0.65)]
    d.polygon([P((ex + x * math.cos(a) - y * math.sin(a), ey + x * math.sin(a) + y * math.cos(a))) for x, y in pts], fill=col)
small = im.resize((int(im.width * 2.57 / S), int(im.height * 2.57 / S)), Image.LANCZOS)
small = small.resize((small.width * 4, small.height * 4), Image.NEAREST)
canvas = Image.new('RGB', (im.width + small.width + 10, max(im.height, small.height)), (236, 228, 208))
canvas.paste(im, (0, 0)); canvas.paste(small, (im.width + 10, 0))
canvas.save(sys.argv[1])
