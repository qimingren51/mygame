"""在设计稿坐标里画赤面狐的头和脸谱草图（迭代形状用）。"""
import sys, math
sys.path.insert(0, '/home/user/mygame/art/post')
import numpy as np
from PIL import Image, ImageDraw
import enemy_design as DZ

S = 36
X0, Y0 = 8.0, 42.0
def P(p): return ((p[0] - X0) * S, (Y0 - p[1]) * S)
im = Image.new('RGB', (int(18 * S), int(20 * S)), (236, 228, 208))
d = ImageDraw.Draw(im)
head = DZ.curve_pts(DZ.FOX_HEAD, 300, closed=True)
d.polygon([P(p) for p in head], fill=(205, 170, 120), outline=(20, 20, 20))
for ear in (DZ.FOX_EAR_FAR, DZ.FOX_EAR_NEAR):
    d.polygon([P(p) for p in ear], fill=(190, 150, 100), outline=(20, 20, 20))
def poly(pts, fill, outline=None, w=1):
    d.polygon([P(p) for p in pts], fill=fill, outline=outline, width=w)
for nm in ('FOX_MASK', 'FOX_MASK_FAR'):
    if hasattr(DZ, nm):
        poly(getattr(DZ, nm), (200, 50, 40), (110, 20, 20), 3)
for nm in ('FOX_EYE_WINDOW',):
    if hasattr(DZ, nm):
        poly(getattr(DZ, nm), (245, 236, 214))
for nm in ('FOX_EYE_INK', 'FOX_BROW_POLY'):
    if hasattr(DZ, nm):
        poly(getattr(DZ, nm), (25, 22, 20))
if hasattr(DZ, 'fox_eye_poly'):
    poly(DZ.fox_eye_poly(1.0), (255, 107, 90))
    poly(DZ.fox_eye_poly(0.5), (255, 226, 194))
nx, ny = DZ.FOX_NOSE
d.ellipse([P((nx - 0.5, ny + 0.4)), P((nx + 0.5, ny - 0.4))], fill=(20, 20, 20))
d.line([P(p) for p in DZ.FOX_HEAD_PTS['mouth']], fill=(20, 20, 20), width=2)
im.save(sys.argv[1])
# 1080p 实际大小（2.57 px/单位）放大 4 倍看
small = im.resize((int(im.width * 2.57 / S), int(im.height * 2.57 / S)), Image.LANCZOS)
small = small.resize((small.width * 4, small.height * 4), Image.NEAREST)
canvas = Image.new('RGB', (im.width + small.width + 20, im.height), (236, 228, 208))
canvas.paste(im, (0, 0)); canvas.paste(small, (im.width + 20, 0))
canvas.save(sys.argv[1])
