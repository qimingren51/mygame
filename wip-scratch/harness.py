"""快速试画：纸、天、地、主角、石灯笼、打光、收尾（跳过远山、松、石），出裁切图。"""
import sys
import time

sys.path.insert(0, "/tmp/claude-0/-home-user-mygame/01f265ce-5196-560e-be75-2f924c080bfe/scratchpad")
import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

import proto_hero as PH  # noqa: E402

T = PH.T
SP = "/tmp/claude-0/-home-user-mygame/01f265ce-5196-560e-be75-2f924c080bfe/scratchpad/"
t0 = time.perf_counter()
rng = np.random.default_rng(2026)
P = T.Painting(rng)
paper0 = P.rgb.copy()
P.paper0 = paper0
T.paint_sky(P, rng)
T.paint_ground(P, rng)
T.paint_ground_detail(P, rng)
lights = []
for x, y, s in sorted(T.STONE_LANTERNS, key=lambda t: t[1]):
    PH.paint_stone_lantern_ink(P, np.random.default_rng(int(x)), x, y, s, lights)
day = P.rgb.copy()
lx, ly = PH.paint_hero_ink(P, np.random.default_rng(77), lights)
day = P.rgb.copy()
print("lantern", lx, ly)
lm = T.light_map(P, lights, rng)
out = P.rgb * np.clip(lm, 0, 1.08)
e = P.emit
out = out * (1 - np.clip(e.max(-1, keepdims=True), 0, 1) * 0.6) + e + 0.55 * T.bloom(e, 5.0) + 0.45 * T.bloom(e, 22.0)
dl = np.hypot(P.X - lx, P.Y - ly)
out += (np.exp(-(dl / 90.0) ** 2) * 0.12 + np.exp(-(dl / 260.0) ** 2) * 0.05)[..., None] * PH.LAMP_LIGHT
img = Image.fromarray((np.clip(out, 0, 1) * 255 + 0.5).astype(np.uint8))
dimg = Image.fromarray((np.clip(day, 0, 1) * 255 + 0.5).astype(np.uint8))
box = (1040, 590, 1400, 920)
k = 2
a = img.crop(box).resize(((box[2] - box[0]) * k, (box[3] - box[1]) * k), Image.LANCZOS)
b = dimg.crop(box).resize(((box[2] - box[0]) * k, (box[3] - box[1]) * k), Image.LANCZOS)
c = Image.new("RGB", (a.width * 2 + 10, a.height), (255, 255, 255))
c.paste(b, (0, 0))
c.paste(a, (a.width + 10, 0))
c.save(SP + "h_hero.png")
box = (670, 720, 1030, 930)
a = img.crop(box).resize(((box[2] - box[0]) * k, (box[3] - box[1]) * k), Image.LANCZOS)
b = dimg.crop(box).resize(((box[2] - box[0]) * k, (box[3] - box[1]) * k), Image.LANCZOS)
c = Image.new("RGB", (a.width * 2 + 10, a.height), (255, 255, 255))
c.paste(b, (0, 0))
c.paste(a, (a.width + 10, 0))
c.save(SP + "h_sl.png")
img.save(SP + "h_full.png")
print(f"{time.perf_counter() - t0:.1f}s")
