"""快速预览 M2.5 图标（不写 assets）。用法：LANTERN_ART_DENSITY=2 python prev_icons.py [名字过滤...]"""
import sys
from pathlib import Path

sys.path.insert(0, "/home/user/mygame/art/post")
import numpy as np
from PIL import Image, ImageDraw
import ui_icons_m25 as M
import ui_icons as U
from ui_fonts import font
from concurrent.futures import ProcessPoolExecutor

OUT = Path(__file__).resolve().parent
flt = sys.argv[1:]
specs = M.specs()
idx = [i for i, s in enumerate(specs) if not flt or any(f in s[0] for f in flt)]


def job(i):
    return i, M.make(i)


with ProcessPoolExecutor(4) as ex:
    res = dict(ex.map(job, idx))
paper = tuple(int(c * 255) for c in U.PAPER)
night = (0x16, 0x1B, 0x2C)
cw, ch = 330, 175
cols = 4
rows = (len(idx) + cols - 1) // cols
sheet = Image.new("RGB", (cols * cw * 2, rows * ch), paper)
sheet.paste(night, (cols * cw, 0, cols * cw * 2, rows * ch))
dr = ImageDraw.Draw(sheet)
f = font("serif", 14)
for j, i in enumerate(idx):
    im = res[i]
    r, c = divmod(j, cols)
    for side in (0, 1):
        x0, y0 = side * cols * cw + c * cw + 8, r * ch + 22
        big = im if im.width >= 128 else im.resize((im.width * 2, im.height * 2), Image.NEAREST)
        sheet.paste(big, (x0, y0), big)
        sx = x0 + 136
        for s in (64, 32, 24):
            sm = im.resize((s, s), Image.LANCZOS)
            sheet.paste(sm, (sx, y0), sm)
            sx += s + 6
        dr.text((x0, r * ch + 4), specs[i][0], fill=(40, 40, 40) if side == 0 else (220, 220, 220), font=f)
sheet.save(OUT / "prev_icons.png")
print("ok", OUT / "prev_icons.png")
