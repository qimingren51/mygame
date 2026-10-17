"""狐火造型二维草图。"""
import sys, math
sys.path.insert(0, '/home/user/mygame/art/post')
import numpy as np
from PIL import Image, ImageDraw
import enemy_design as DZ
S = 14
X0, Y0 = -22.0, 32.0
def P(p): return ((p[0] - X0) * S, (Y0 - p[1]) * S)
im = Image.new('RGB', (int(44 * S), int(36 * S)), (236, 228, 208))
d = ImageDraw.Draw(im)
d.line([P((-22, 0)), P((22, 0))], fill=(150, 120, 100))
d.line([P((-20, -1)), P((-20, 35))], fill=(200, 180, 160)); d.line([P((20, -1)), P((20, 35))], fill=(200, 180, 160))
exec(open(sys.argv[2]).read())
for kind, data, col in SHAPES:
    if kind == 'stroke':
        ctrl, widths = data
        c = DZ.curve_pts(ctrl, 120)
        d.polygon([P(p) for p in DZ.stroke_poly(c, widths)], fill=col)
    elif kind == 'ellipse':
        (cx, cy), rx, ry, tilt = data
        a = math.radians(tilt)
        pts = [(cx + rx*math.cos(t)*math.cos(a) - ry*math.sin(t)*math.sin(a), cy + rx*math.cos(t)*math.sin(a) + ry*math.sin(t)*math.cos(a)) for t in np.linspace(0, 2*math.pi, 60)]
        d.polygon([P(p) for p in pts], fill=col)
    elif kind == 'poly':
        d.polygon([P(p) for p in data], fill=col)
small = im.resize((int(im.width * 2.57 / S), int(im.height * 2.57 / S)), Image.LANCZOS)
small = small.resize((small.width * 4, small.height * 4), Image.NEAREST)
canvas = Image.new('RGB', (im.width + small.width + 10, max(im.height, small.height)), (236, 228, 208))
canvas.paste(im, (0, 0)); canvas.paste(small, (im.width + 10, 0))
canvas.save(sys.argv[1])
