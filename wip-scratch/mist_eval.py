import sys
sys.path.insert(0, "/home/user/mygame/art/post")
import numpy as np
import vfx_textures as V
from vfx_textures import noise1, wrap_sample, smoothstep, fft_blur, sig, D, dpx

def mk(seed, scales, weights, lo, hi):
    size = dpx(256); sh = (size, size)
    rng = np.random.default_rng(seed)
    wx = 3.5 * D * noise1(rng, sh, 22.0); wy = 3.5 * D * noise1(rng, sh, 22.0)
    f = sum(w * noise1(rng, sh, sg) for sg, w in zip(scales, weights))
    f = wrap_sample(f / f.std(), wx, wy)
    body = smoothstep(lo, hi, f)
    inner = noise1(rng, sh, (9.0, 8.0))
    a = body ** 1.3 * (0.72 + 0.28 * smoothstep(-1.4, 1.4, inner))
    a = fft_blur(a, sig(1.8), wrap=True)
    a = a * (1.0 + 0.02 * noise1(rng, sh, 1.5))
    return np.clip(a / np.percentile(a, 99.8), 0, 1)

def ev(a):
    h, w = a.shape
    q = [a[:h//2,:w//2].mean(), a[:h//2,w//2:].mean(), a[h//2:,:w//2].mean(), a[h//2:,w//2:].mean()]
    gy = np.abs(np.diff(a, axis=0)).mean(); gx = np.abs(np.diff(a, axis=1)).mean()
    return max(q)-min(q), gy/gx, a.mean(), (a<0.05).mean(), (a>0.8).mean()

S0 = (((26.0, 20.0), (12.0, 10.0), (6.0, 5.0)), (0.65, 0.3, 0.1), -0.65, 1.35)
S0b = (((20.0, 16.0), (11.0, 9.0), (5.5, 4.5)), (0.6, 0.33, 0.12), -0.6, 1.35)
for name, sp in (("S0", S0), ("S0b", S0b)):
    for seed in (1500, 1502, 1504, 1506, 1508, 1510):
        print(name, seed, np.round(ev(mk(seed, *sp)), 3))
S1 = (((16.0, 13.0), (8.0, 7.0), (4.0, 3.5)), (0.6, 0.32, 0.1), -0.45, 1.6)
print("S1 1501", np.round(ev(mk(1501, *S1)), 3))
