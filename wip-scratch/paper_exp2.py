import sys, math
sys.path.insert(0, '/home/user/mygame/art/post')
sys.path.insert(0, '/tmp/claude-0/-home-user-mygame/01f265ce-5196-560e-be75-2f924c080bfe/scratchpad')
import numpy as np
from PIL import Image
import moon_textures as M
from paper_exp import warped_fbm, SP, n
V = M.V

def build(variant, seed=7201):
    rng = np.random.default_rng(seed)
    L = {}
    L['fuzz_d'] = (M.strands(rng, n, 120000, (2, 6), (0.010, 0.024), 0.75, 0.05), M.DIR_SHADE)
    L['fuzz_l'] = (M.strands(rng, n, 100000, (2, 6), (0.010, 0.022), 0.8, 0.05), M.DIR_LIGHT)
    L['mid_d'] = (M.strands(rng, n, 14000, (8, 28), (0.010, 0.022), 0.8, 0.03), M.DIR_SHADE)
    L['mid_l'] = (M.strands(rng, n, 9000, (8, 28), (0.008, 0.018), 0.85, 0.03), M.DIR_LIGHT)
    L['silk_l'] = (M.strands(rng, n, 420, (40, 150), (0.012, 0.024), 0.85, 0.006), M.DIR_LIGHT)
    L['silk_d'] = (M.strands(rng, n, 200, (30, 120), (0.012, 0.026), 0.8, 0.007), M.DIR_SHADE)
    L['grain'] = (0.006 * V.noise(rng, (n, n), 1.0), M.DIR_SHADE)
    sig, wts, cut, k = {
        'mid90': ((4, 9, 20, 42), (0.15, 0.3, 0.45, 0.5), 90, 1.0),
        'mid60': ((4, 9, 20, 36), (0.15, 0.3, 0.5, 0.5), 60, 1.0),
        'mid90t': ((4, 9, 20, 42), (0.15, 0.3, 0.45, 0.5), 90, 0.75),
    }[variant]
    c = warped_fbm(rng, sig, wts, 20, 16, cut)
    c = np.tanh(k * c) if k != 1.0 else np.tanh(c)
    c = c / c.std()
    fl = warped_fbm(rng, (2.5, 5.0, 9.0), (0.5, 0.4, 0.25), 8, 4, 0)
    L['cloud'] = (0.015 * c, M.DIR_SHADE)
    L['floc'] = (0.010 * np.tanh(1.3 * fl), M.DIR_SHADE)
    dev = sum(f[..., None] * d for f, d in L.values())
    dev = dev - dev.reshape(-1, 3).mean(0)
    lum = dev @ M.LUMA
    gain = 0.039 / lum.std()
    rgb = M.current_paper().reshape(-1, 3).mean(0) + 255 * gain * dev
    return np.clip(np.round(rgb), 0, 255).astype(np.uint8), gain

for v in ('mid90', 'mid60', 'mid90t'):
    rgb8, gain = build(v)
    st = M.paper_stats(rgb8)
    print(v, 'gain', round(gain, 3), 'lowfreq', st['lowfreq_share_lambda_ge_256px'], 'blob', st['max_blob_over_std_sigma24'], 'range', st['luma_p0_5_p99_5'])
    Image.fromarray(rgb8).save(f'{SP}/exp2_{v}.png')
    Image.fromarray(np.tile(rgb8, (2, 3, 1))).resize((int(3072 * 0.6428), int(2048 * 0.6428)), Image.BILINEAR).save(f'{SP}/exp2_{v}_tiled.png')
