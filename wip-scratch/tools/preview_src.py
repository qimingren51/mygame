"""草稿：角色格式的源图（<动画>_S_NN.png + _emit）拼成预览：每帧纸色底一张、夜里一张（普通层 × 月夜 + 发光层叠加 × 1.5），放大 z 倍。
用法：preview_src.py <源图目录> <输出 png> [z]"""
import sys
from pathlib import Path

import numpy as np
from PIL import Image

src, out = Path(sys.argv[1]), Path(sys.argv[2])
z = int(sys.argv[3]) if len(sys.argv) > 3 else 2


def lin(c):
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def srgb(c):
    c = np.clip(c, 0, 1)
    return np.where(c <= 0.0031308, c * 12.92, 1.055 * c ** (1 / 2.4) - 0.055)


paper = lin(np.array([0xED, 0xE4, 0xCF]) / 255)
night = lin(np.array([0x46, 0x55, 0x7F]) / 255)
pngs = sorted(p for p in src.glob("*_S_*.png") if not p.stem.endswith("_emit"))
tiles = []
for p in pngs:
    a = np.asarray(Image.open(p).convert("RGBA")).astype(float) / 255
    e = p.with_name(p.stem + "_emit.png")
    em = np.asarray(Image.open(e).convert("RGBA")).astype(float) / 255 if e.exists() else np.zeros_like(a)
    day = lin(a[..., :3]) * a[..., 3:] + paper * (1 - a[..., 3:])
    nt = (lin(a[..., :3]) * a[..., 3:] + paper * (1 - a[..., 3:])) * night + lin(em[..., :3]) * em[..., 3:] * 1.5
    col = np.concatenate([day, nt], 0)
    im = Image.fromarray((srgb(col) * 255).astype(np.uint8)).resize((a.shape[1] * z, a.shape[0] * 2 * z), Image.NEAREST)
    tiles.append(im)
W = sum(t.width for t in tiles) + 4 * len(tiles)
H = max(t.height for t in tiles)
canvas = Image.new("RGB", (W, H), (20, 20, 20))
x = 0
for t in tiles:
    canvas.paste(t, (x, 0))
    x += t.width + 4
canvas.save(out)
print(out, canvas.size, [p.stem for p in pngs])
