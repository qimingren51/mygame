"""快速预览：npz → 简单色调映射 PNG（暗底）。"""
import sys
import numpy as np
from PIL import Image
p = sys.argv[1]; out = sys.argv[2]
ex = float(sys.argv[3]) if len(sys.argv) > 3 else 1.0
d = np.load(p)
rgba = d["rgba"].astype(np.float32)
bg = np.array([0.012, 0.014, 0.022], np.float32)
rgb = rgba[..., :3] + bg * (1 - rgba[..., 3:])
x = rgb * ex
a, b, c, dd, e = 2.51, 0.03, 2.43, 0.59, 0.14
y = np.clip((x * (a * x + b)) / (x * (c * x + dd) + e), 0, 1)
y = np.where(y <= 0.0031308, 12.92 * y, 1.055 * np.power(y, 1 / 2.4) - 0.055)
Image.fromarray((np.clip(y, 0, 1) * 255 + 0.5).astype(np.uint8)).save(out)
print(out, rgba.shape, "alpha mean", rgba[..., 3].mean(), "max", rgb.max())
