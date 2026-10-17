"""草稿：几组帧（普通层 + 可选发光层）在纸色底、夜色底上排一行看。用法：night_row.py <目录> <输出> <组名[+发光组名]>…"""
import sys
from pathlib import Path

import numpy as np
from PIL import Image

d, out = Path(sys.argv[1]), Path(sys.argv[2])
groups = sys.argv[3:]
lin = lambda c: np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)  # noqa: E731
srgb = lambda c: np.where(np.clip(c, 0, 1) <= 0.0031308, np.clip(c, 0, 1) * 12.92, 1.055 * np.clip(c, 0, 1) ** (1 / 2.4) - 0.055)  # noqa: E731
paper = lin(np.array([0xED, 0xE4, 0xCF]) / 255)
night = lin(np.array([0x46, 0x55, 0x7F]) / 255)
cols = []
for g in groups:
    base, _, emit = g.partition("+")
    i = 0
    while (d / f"{base}_{i}.png").exists():
        a = np.asarray(Image.open(d / f"{base}_{i}.png").convert("RGBA")).astype(float) / 255
        e = np.asarray(Image.open(d / f"{emit}_{i}.png").convert("RGBA")).astype(float) / 255 if emit else np.zeros_like(a)
        add = a[..., 3:] if a.shape[-1] else 0
        if base.endswith(("vortex", "mark", "sea")) or "emit" in base:
            day = paper + lin(a[..., :3]) * a[..., 3:] * 1.5
            nt = paper * night + lin(a[..., :3]) * a[..., 3:] * 1.5
        else:
            day = lin(a[..., :3]) * a[..., 3:] + paper * (1 - a[..., 3:]) + lin(e[..., :3]) * e[..., 3:] * 0.0
            nt = (lin(a[..., :3]) * a[..., 3:] + paper * (1 - a[..., 3:])) * night + lin(e[..., :3]) * e[..., 3:] * 1.5
        cols.append(np.concatenate([day, nt], 0))
        i += 1
H = max(c.shape[0] for c in cols)
row = np.zeros((H, sum(c.shape[1] + 4 for c in cols), 3))
x = 0
for c in cols:
    row[: c.shape[0], x : x + c.shape[1]] = c
    x += c.shape[1] + 4
img = Image.fromarray((srgb(row) * 255).astype(np.uint8))
sc = float(sys.argv[0] and 1)
img.save(out)
print(out, img.size)
