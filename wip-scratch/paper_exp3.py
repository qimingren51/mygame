import sys, math
sys.path.insert(0, '/home/user/mygame/art/post')
import numpy as np
from PIL import Image
import moon_textures as M
V = M.V
SP = '/tmp/claude-0/-home-user-mygame/01f265ce-5196-560e-be75-2f924c080bfe/scratchpad'
n = 1024

def warped(rng, sigmas, weights, ws, wa, cut):
    wx = wa * V.noise(rng, (n, n), ws); wy = wa * V.noise(rng, (n, n), ws)
    f = sum(w * V.noise(rng, (n, n), s) for s, w in zip(sigmas, weights))
    f = V.wrap_sample(f, wx, wy)
    if cut: f = f - V.fft_blur(f, cut, wrap=True)
    return f / f.std()

def soft_tails(c, k=2.2):
    c = c / np.sqrt(1 + (c / k) ** 2)
    return c / c.std()

def build(variant, sF, sC, seed=7201):
    rng = np.random.default_rng(seed)
    F = (M.strands(rng, n, 120000, (2, 6), (0.010, 0.024), 0.75, 0.05)[..., None] * M.DIR_SHADE
         + M.strands(rng, n, 100000, (2, 6), (0.010, 0.022), 0.8, 0.05)[..., None] * M.DIR_LIGHT
         + M.strands(rng, n, 14000, (8, 28), (0.010, 0.022), 0.8, 0.03)[..., None] * M.DIR_SHADE
         + M.strands(rng, n, 9000, (8, 28), (0.008, 0.018), 0.85, 0.03)[..., None] * M.DIR_LIGHT
         + M.strands(rng, n, 420, (40, 150), (0.012, 0.024), 0.85, 0.006)[..., None] * M.DIR_LIGHT
         + M.strands(rng, n, 200, (30, 120), (0.012, 0.026), 0.8, 0.007)[..., None] * M.DIR_SHADE
         + (0.006 * V.noise(rng, (n, n), 1.0))[..., None] * M.DIR_SHADE)
    F -= F.reshape(-1, 3).mean(0)
    F *= sF / (F @ M.LUMA).std()
    if variant == 'capped':
        c = soft_tails(warped(rng, (4, 10, 24, 50), (0.15, 0.3, 0.45, 0.5), 22, 16, 200))
        fl = None
    elif variant == 'capped_floc':
        c = soft_tails(warped(rng, (6, 14, 30, 56), (0.2, 0.35, 0.5, 0.45), 22, 16, 200))
        fl = warped(rng, (2.5, 5.0, 9.0), (0.5, 0.4, 0.25), 8, 4, 0)
    elif variant == 'small':
        c = soft_tails(warped(rng, (4, 10, 22, 40), (0.2, 0.35, 0.5, 0.45), 22, 14, 120))
        fl = warped(rng, (2.5, 5.0, 9.0), (0.5, 0.4, 0.25), 8, 4, 0)
    C = c if fl is None else c + 0.45 * np.tanh(1.2 * fl)
    C = (C / C.std())[..., None] * M.DIR_SHADE
    C *= sC / (C @ M.LUMA).std()
    dev = F + C
    dev -= dev.reshape(-1, 3).mean(0)
    rgb = M.current_paper().reshape(-1, 3).mean(0) + 255 * dev
    return np.clip(np.round(rgb), 0, 255).astype(np.uint8)

crops = []
for v, sF, sC in (('capped', 0.027, 0.024), ('capped_floc', 0.027, 0.024), ('small', 0.027, 0.024), ('capped_floc', 0.030, 0.020)):
    rgb8 = build(v, sF, sC)
    st = M.paper_stats(rgb8)
    tag = f'{v}_{sF}_{sC}'
    print(tag, 'std', st['luma_std'], 'lowfreq', st['lowfreq_share_lambda_ge_256px'], 'blob', st['max_blob_over_std_sigma24'])
    Image.fromarray(np.tile(rgb8, (2, 3, 1))).resize((int(3072 * 0.6428), int(2048 * 0.6428)), Image.BILINEAR).save(f'{SP}/exp3_{tag}_tiled.png')
    crops.append(rgb8[100:400, 150:950])
Image.fromarray(np.concatenate([np.concatenate([c, np.full((300, 6, 3), 40, np.uint8)], 1) for c in crops], 0)).save(f'{SP}/exp3_crops.png')
