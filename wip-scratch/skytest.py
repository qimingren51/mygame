import sys, time
SP = "/tmp/claude-0/-home-user-mygame/01f265ce-5196-560e-be75-2f924c080bfe/scratchpad/"
sys.path.insert(0, SP)
import numpy as np
from PIL import Image
import proto_mtn as PM
T = PM.T
t0 = time.perf_counter()
rng = np.random.default_rng(2026)
P = T.Painting(rng)
P.rgb = PM.soft_paper_canvas(np.random.default_rng(2027))
paper0 = P.rgb.copy()
T.paint_sky(P, rng)
lm = T.light_map(P, [], rng)
out = P.rgb * np.clip(lm, 0, 1.08)
rel = paper0.mean(-1) / paper0.mean()
rel = rel - T.blur(rel, 40.0) / T.blur(np.ones_like(rel), 40.0) + 1.0
lum = out.mean(-1, keepdims=True)
gain = 1.6 + 2.0 * (1 - T.smoothstep(0.05, 0.5, lum))
out = out * (1 + gain * (rel[..., None] - 1)) + 0.02 * (rel[..., None] - 1)
n = Image.fromarray((np.clip(out, 0, 1) * 255 + 0.5).astype(np.uint8))
o = Image.open(SP + "old/title.png")
box = (980, 40, 1280, 300)
a = np.asarray(o.crop(box), np.float64); b = np.asarray(n.crop(box), np.float64)
lo, hi = np.percentile(np.concatenate([a.ravel(), b.ravel()]), [1, 99])
st = lambda x: Image.fromarray((np.clip((x - lo) / (hi - lo), 0, 1) * 255).astype(np.uint8))
A, B = st(a).resize((600, 520), Image.LANCZOS), st(b).resize((600, 520), Image.LANCZOS)
A2, B2 = o.crop(box).resize((600, 520), Image.LANCZOS), n.crop(box).resize((600, 520), Image.LANCZOS)
c = Image.new("RGB", (1208, 1048), (255, 255, 255))
c.paste(A, (0, 0)); c.paste(B, (608, 0)); c.paste(A2, (0, 528)); c.paste(B2, (608, 528))
c.save(SP + "c_sky3.png")
print(f"{time.perf_counter()-t0:.1f}s")
