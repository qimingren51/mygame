"""快速看图：素材文件夹里的若干帧 → 纸面白天 + 月夜（灯下），2 倍原图和 1080p 实际大小（放大 3 倍）。
用法：quick_look.py 输出.png 文件夹 帧名... [--hero]"""
import sys
from pathlib import Path
import numpy as np
from PIL import Image
out, folder, names = sys.argv[1], Path(sys.argv[2]), [a for a in sys.argv[3:] if not a.startswith('--')]
PAPER = np.array([236, 228, 207]) / 255.0
NIGHT = np.array([0x46, 0x55, 0x7F]) / 255.0
LAMP = np.array([0xFF, 0xC2, 0x7A]) / 255.0
def srgb2lin(c): return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
def lin2srgb(c): return np.where(c <= 0.0031308, c * 12.92, 1.055 * np.clip(c, 0, None) ** (1 / 2.4) - 0.055)
tiles = []
for nm in names:
    im = np.asarray(Image.open(folder / f"{nm}.png")).astype(np.float64) / 255.0
    ep = folder / f"{nm}_emit.png"
    em = np.asarray(Image.open(ep)).astype(np.float64) / 255.0 if ep.exists() else np.zeros_like(im)
    a = im[..., 3:4]
    day = im[..., :3] * a + PAPER * (1 - a)
    lin = srgb2lin(im[..., :3])
    ground = srgb2lin(PAPER) * 0.55
    light = srgb2lin(NIGHT) * 0.9 + srgb2lin(LAMP) * 0.35
    night_lin = (lin * a + ground * (1 - a)) * light + srgb2lin(em[..., :3]) * em[..., 3:4] * 1.5
    night = lin2srgb(np.clip(night_lin, 0, 1))
    row = np.concatenate([day, night], 1)
    tiles.append(row)
big = np.concatenate(tiles, 0)
img = Image.fromarray((np.clip(big, 0, 1) * 255).astype(np.uint8))
s = img.resize((round(img.width * 2.57 / 4), round(img.height * 2.57 / 4)), Image.LANCZOS)
s = s.resize((s.width * 3, s.height * 3), Image.NEAREST)
img2 = img.resize((img.width * 2, img.height * 2), Image.LANCZOS)
W = img2.width + s.width + 10
canvas = Image.new('RGB', (W, max(img2.height, s.height)), (200, 200, 200))
canvas.paste(img2, (0, 0)); canvas.paste(s, (img2.width + 10, 0))
canvas.save(out)
print(canvas.size)
