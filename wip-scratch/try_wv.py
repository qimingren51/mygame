"""沧浪 / 青藤第二版试画：叠加层染色 × 1.5 加在（水体 / 藤身 普通混合画过的）底上；纸色底、夜色底各一条。用法：try_wv.py wave|vine|bind"""
import os, sys, time
os.environ["LANTERN_ART_DENSITY"] = "2"
sys.path.insert(0, "wt-moon/art/post")
import numpy as np
from PIL import Image
import weapon_textures_ea as E

which = sys.argv[1]
t0 = time.perf_counter()
if which == "wave":
    adds, bodies = E._wave(); tint = "#7CC8FF"; idx = [1, 3, 5]
elif which == "vine":
    adds, bodies = E._vine(); tint = "#8FE07A"; idx = [0]
else:
    adds, bodies = E._vine_bind(); tint = "#8FE07A"; idx = [1, 3]
print(which, f"{time.perf_counter() - t0:.1f}s")
tc = E.V.col(tint)
PAPER = np.array([0.93, 0.86, 0.72])  # 灯下的暖纸
NIGHT = np.array([70, 85, 127], float) / 255 * 0.8
rows = []
for bg_c, light in ((PAPER, 1.0), (NIGHT * 0 + 1.0, None)):
    tiles = []
    for i in idx:
        a = np.asarray(adds[i]).astype(float) / 255
        b = np.asarray(bodies[i]).astype(float) / 255
        h, w = a.shape[:2]
        if light is not None:
            base = np.broadcast_to(PAPER, (h, w, 3)).copy()
            base = base * (1 - b[..., 3:]) + b[..., :3] * b[..., 3:]
        else:  # 夜里：纸 × 月夜，水体也受光
            base = np.broadcast_to(np.array([0.9, 0.86, 0.78]), (h, w, 3)).copy()
            base = (base * (1 - b[..., 3:]) + b[..., :3] * b[..., 3:]) * NIGHT
        c = np.clip(base + a[..., :3] * a[..., 3:] * tc * 1.35, 0, 1)
        tiles.append(Image.fromarray((c * 255).astype(np.uint8)))
    W_ = sum(t.width for t in tiles) + 4 * len(tiles)
    row = Image.new("RGB", (W_, tiles[0].height), (40, 40, 40)); x = 0
    for t in tiles:
        row.paste(t, (x, 0)); x += t.width + 4
    rows.append(row)
sheet = Image.new("RGB", (rows[0].width, sum(r.height + 4 for r in rows)), (40, 40, 40)); y = 0
for r in rows:
    sheet.paste(r, (0, y)); y += r.height + 4
sc = float(sys.argv[2]) if len(sys.argv) > 2 else 1.0
if sc != 1.0:
    sheet = sheet.resize((int(sheet.width * sc), int(sheet.height * sc)), Image.LANCZOS)
os.makedirs("b3_try", exist_ok=True)
sheet.save(f"b3_try/wv_{which}.png"); print(sheet.size)
