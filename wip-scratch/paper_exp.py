"""宣纸云絮的几种做法对比（草稿，不进仓库）。"""
import sys, math
sys.path.insert(0, '/home/user/mygame/art/post')
import numpy as np
from PIL import Image
import moon_textures as M
V = M.V
SP = '/tmp/claude-0/-home-user-mygame/01f265ce-5196-560e-be75-2f924c080bfe/scratchpad'
n = 1024

def warped_fbm(rng, sigmas, weights, warp_sigma, warp_amp, cut):
    wx = warp_amp * V.noise(rng, (n, n), warp_sigma)
    wy = warp_amp * V.noise(rng, (n, n), warp_sigma)
    f = sum(w * V.noise(rng, (n, n), s) for s, w in zip(sigmas, weights))
    f = V.wrap_sample(f, wx, wy)
    if cut:
        f = f - V.fft_blur(f, cut, wrap=True)
    return f / f.std()

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
    if variant == 'blob':     # 现在的做法
        c = M.band_noise(rng, n, (6.0, 14.0, 30.0), (0.3, 0.6, 0.5), 40.0)
        L['cloud'] = (0.017 * c, M.DIR_SHADE)
    elif variant == 'broad':  # 宽频（1/f 一样）
        c = warped_fbm(rng, (4, 10, 24, 56, 130), (0.12, 0.25, 0.4, 0.5, 0.45), 30, 0, 260)
        L['cloud'] = (0.017 * c, M.DIR_SHADE)
    elif variant == 'warp':   # 宽频 + 坐标扭曲（絮状、一缕缕）
        c = warped_fbm(rng, (4, 10, 24, 56, 130), (0.12, 0.25, 0.4, 0.5, 0.45), 24, 22, 260)
        L['cloud'] = (0.017 * c, M.DIR_SHADE)
    elif variant == 'floc':   # 扭曲宽频 + 细的絮（3–8 px，tanh 压成一团团）
        c = warped_fbm(rng, (10, 24, 56, 130), (0.25, 0.4, 0.5, 0.45), 24, 22, 260)
        fl = warped_fbm(rng, (2.5, 5.0, 9.0), (0.5, 0.4, 0.25), 8, 4, 0)
        L['cloud'] = (0.015 * c, M.DIR_SHADE)
        L['floc'] = (0.010 * np.tanh(1.3 * fl), M.DIR_SHADE)
    dev = sum(f[..., None] * d for f, d in L.values())
    dev = dev - dev.reshape(-1, 3).mean(0)
    lum = dev @ M.LUMA
    parts = {k: round(float(((f[..., None] * d) @ M.LUMA).std()), 4) for k, (f, d) in L.items()}
    gain = 0.039 / lum.std()
    rgb = M.current_paper().reshape(-1, 3).mean(0) + 255 * gain * dev
    rgb8 = np.clip(np.round(rgb), 0, 255).astype(np.uint8)
    return rgb8, gain, parts

rows = []
for v in ('blob', 'broad', 'warp', 'floc'):
    rgb8, gain, parts = build(v)
    st = M.paper_stats(rgb8)
    print(v, 'gain', round(gain, 3), parts, 'lowfreq', st['lowfreq_share_lambda_ge_256px'], 'blob', st['max_blob_over_std_sigma24'])
    Image.fromarray(rgb8).save(f'{SP}/exp_{v}.png')
    rows.append(rgb8[100:500, 200:900])
Image.fromarray(np.concatenate([np.concatenate([r, np.full((400, 8, 3), 40, np.uint8)], 1) for r in rows], 0)).save(f'{SP}/exp_crops.png')
# 游戏里的比例（1080p 0.643 倍）3×3
for v in ('warp', 'floc'):
    a = np.asarray(Image.open(f'{SP}/exp_{v}.png'))
    Image.fromarray(np.tile(a, (2, 3, 1))).resize((int(3072 * 0.6428), int(2048 * 0.6428)), Image.BILINEAR).save(f'{SP}/exp_{v}_tiled.png')
