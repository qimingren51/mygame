"""第三批试画：只跑给定的生成函数，拼一张小的帧条（夜色底叠加 / 纸色底普通），不写 assets。
用法：try_b3.py react_liaoyuan,react_yuni [scale]"""
import os, sys, time
os.environ["LANTERN_ART_DENSITY"] = "2"
sys.path.insert(0, "wt-moon/art/post")
import numpy as np
from PIL import Image
import vfx_frames as F

names = sys.argv[1].split(",")
scale = float(sys.argv[2]) if len(sys.argv) > 2 else 0.4
out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "b3_try")
os.makedirs(out, exist_ok=True)
NIGHT = np.array([70, 85, 127], float) / 255 * 0.9
PAPER = np.array([237, 230, 214], float) / 255
rows = []
for name in names:
    t0 = time.perf_counter()
    spec = F.BATCH3[name]
    imgs = spec[0]()
    print(name, f"{time.perf_counter() - t0:.1f}s", [im.size for im in imgs][:1], len(imgs))
    for i, im in enumerate(imgs):
        im.save(f"{out}/{name}_{i}.png")
    tiles = []
    for im in imgs:
        a = np.asarray(im).astype(float) / 255
        rgb, al = a[..., :3], a[..., 3:]
        if spec[3] == "add":
            bg = np.broadcast_to(NIGHT, rgb.shape)
            c = np.clip(bg + rgb * al * 1.5, 0, 1)
        else:
            halves = []
            bg = np.broadcast_to(PAPER, rgb.shape).copy()
            bg[:, rgb.shape[1] // 2 :] = NIGHT * 1.4
            c = bg * (1 - al) + rgb * al
        t = Image.fromarray((c * 255).astype(np.uint8)).resize((max(1, int(im.width * scale)), max(1, int(im.height * scale))), Image.LANCZOS)
        tiles.append(t)
    W_ = sum(t.width for t in tiles) + 4 * len(tiles)
    row = Image.new("RGB", (W_, max(t.height for t in tiles)), (40, 40, 40))
    x = 0
    for t in tiles:
        row.paste(t, (x, 0))
        x += t.width + 4
    rows.append(row)
W_ = max(r.width for r in rows)
sheet = Image.new("RGB", (W_, sum(r.height + 4 for r in rows)), (40, 40, 40))
y = 0
for r in rows:
    sheet.paste(r, (0, y))
    y += r.height + 4
path = f"{out}/strip_{'_'.join(n.replace('react_', '') for n in names)}.png"
sheet.save(path)
print(path, sheet.size)
