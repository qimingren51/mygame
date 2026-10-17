"""开发用：只画指定的新图标/印章（2 倍），拼一张预览图。用法：dev_preview.py [名字前缀...]"""
import os
import sys
import time

os.environ.setdefault("LANTERN_ART_DENSITY", "2")
sys.path.insert(0, "/home/user/mygame/art/post")
import numpy as np  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402

import ui_icons as U  # noqa: E402
import ui_seals  # noqa: E402
from ui_fonts import font  # noqa: E402

SP = os.path.dirname(os.path.abspath(__file__))
pref = sys.argv[1:]
new = U.new_specs()
seals = ui_seals.seal_specs()
tasks, names = [], []
for i, s in enumerate(new):
    if not pref or any(s[0].startswith(p) for p in pref):
        tasks.append(("new", i))
        names.append((s[0], s[4]["name"]))
for i, s in enumerate(seals):
    if not pref or any(s["fname"].startswith(p) for p in pref):
        tasks.append(("seal", i))
        names.append((s["fname"], s["text"]))
t0 = time.time()
imgs = U.render_all(tasks)
print(f"{len(imgs)} rendered in {time.time() - t0:.1f}s")
os.makedirs(os.path.join(SP, "imgs"), exist_ok=True)
for (n, c), im in zip(names, imgs):
    im.save(os.path.join(SP, "imgs", n + ".png"))
old = [Image.open(U.UI_DIR / f"icon_{n}.png").convert("RGBA") for n in ("lamp", "jianyi", "el_fire", "jingxin", "houde")]
items = [(f"old {i}", "", im) for i, im in enumerate(old)] + [(n, c, im) for (n, c), im in zip(names, imgs)]
cols = 5
cellw, cellh = 128 + 6 + 32 + 4 + 24 + 16 + 40, 230 + 24
rows = (len(items) + cols - 1) // cols
W_ = cols * cellw
sheet = Image.new("RGB", (W_ * 2, rows * cellh + 10), U.S.PAPER)
dr = ImageDraw.Draw(sheet)
dr.rectangle((W_, 0, W_ * 2, sheet.height), fill=U.S.NIGHT_AMBIENT)
f = font("serif", 14)
for k, (n, c, im) in enumerate(items):
    r, cc = divmod(k, cols)
    for side in (0, 1):
        x = side * W_ + cc * cellw + 8
        y = r * cellh + 6
        dr.text((x, y), f"{n} {c}", fill="#2E2924" if side == 0 else "#D0D0D0", font=f)
        sheet.paste(im, (x, y + 22), im)
        h = im.height
        s32 = im.resize((32, round(32 * im.height / im.width)), Image.LANCZOS)
        s24 = im.resize((24, round(24 * im.height / im.width)), Image.LANCZOS)
        sheet.paste(s32, (x + im.width + 6, y + 22), s32)
        sheet.paste(s24, (x + im.width + 42, y + 22), s24)
out = os.path.join(SP, "dev_" + ("_".join(pref) if pref else "all") + ".png")
sheet.save(out)
print(out, sheet.size)
