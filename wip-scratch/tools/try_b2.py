"""第二批逐组试画（不写正式产物）：python try_b2.py <组名…>，帧条存到 scratchpad/b2_<组名>.png。"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(sys.argv[1]).resolve()))
import numpy as np
from PIL import Image

import vfx_frames as F

SP = Path(__file__).resolve().parent.parent
bg = np.array([0x2a, 0x33, 0x4f], float) / 255
paper = np.array([0xEC, 0xE3, 0xCE], float) / 255


def lin(c):
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def srgb(c):
    c = np.clip(c, 0, None)
    return np.where(c <= 0.0031308, c * 12.92, 1.055 * c ** (1 / 2.4) - 0.055)


for name in sys.argv[2:]:
    fn = getattr(F, name)
    t0 = time.time()
    frames = fn()
    print(name, len(frames), frames[0].size, f"{time.time() - t0:.1f}s")
    zoom = int(sys.argv[0] and 1)
    w, h = frames[0].size
    z = max(1, 256 // max(w, h)) if max(w, h) < 128 else 1
    row = Image.new("RGB", (len(frames) * (w * z + 6) + 6, 2 * (h * z + 6) + 6), (30, 30, 30))
    for i, im in enumerate(frames):
        a = np.asarray(im, float) / 255
        for k, base in enumerate((bg, paper)):
            if name in ("make_fire_smoke", "make_feather"):
                tint = np.array([0xED, 0xE6, 0xD6], float) / 255 if name == "make_feather" else np.ones(3)
                rgb = srgb(lin(a[..., :3]) * lin(tint) * a[..., 3:4] + lin(base)[None, None] * (1 - a[..., 3:4]))
            else:
                rgb = srgb(lin(base)[None, None] + lin(a[..., :3]) * a[..., 3:4] * 1.5)
            img = Image.fromarray((np.clip(rgb, 0, 1) * 255).astype(np.uint8)).resize((w * z, h * z), Image.NEAREST)
            row.paste(img, (6 + i * (w * z + 6), 6 + k * (h * z + 6)))
        al = a[..., 3]
        ys, xs = np.nonzero(al)
        print(f"  {i}: max {al.max() * 255:.0f} sum {al.sum():.0f} bbox x{xs.min()}-{xs.max()} y{ys.min()}-{ys.max()}" if len(xs) else f"  {i}: 空")
    row.save(SP / f"b2_{name[5:]}.png")
