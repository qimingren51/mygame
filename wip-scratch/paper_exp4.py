import sys
sys.path.insert(0, '/home/user/mygame/art/post')
sys.path.insert(0, '/tmp/claude-0/-home-user-mygame/01f265ce-5196-560e-be75-2f924c080bfe/scratchpad')
import numpy as np
from PIL import Image
import moon_textures as M
import paper_exp3 as E
V = M.V
SP = E.SP; n = 1024

def build(sig, wts, cut, sF, sC, ws=16, wa=12, seed=7201):
    rng = np.random.default_rng(seed)
    F = (M.strands(rng, n, 120000, (2, 6), (0.010, 0.024), 0.75, 0.05)[..., None] * M.DIR_SHADE
         + M.strands(rng, n, 100000, (2, 6), (0.010, 0.022), 0.8, 0.05)[..., None] * M.DIR_LIGHT
         + M.strands(rng, n, 14000, (8, 28), (0.010, 0.022), 0.8, 0.03)[..., None] * M.DIR_SHADE
         + M.strands(rng, n, 9000, (8, 28), (0.008, 0.018), 0.85, 0.03)[..., None] * M.DIR_LIGHT
         + M.strands(rng, n, 420, (40, 150), (0.012, 0.024), 0.85, 0.006)[..., None] * M.DIR_LIGHT
         + M.strands(rng, n, 200, (30, 120), (0.012, 0.026), 0.8, 0.007)[..., None] * M.DIR_SHADE
         + (0.006 * V.noise(rng, (n, n), 1.0))[..., None] * M.DIR_SHADE)
    F -= F.reshape(-1, 3).mean(0); F *= sF / (F @ M.LUMA).std()
    c = E.soft_tails(E.warped(rng, sig, wts, ws, wa, cut))
    fl = E.warped(rng, (2.5, 5.0, 9.0), (0.5, 0.4, 0.25), 8, 4, 0)
    C = c + 0.45 * np.tanh(1.2 * fl)
    C = (C / C.std())[..., None] * M.DIR_SHADE; C *= sC / (C @ M.LUMA).std()
    dev = F + C; dev -= dev.reshape(-1, 3).mean(0)
    return np.clip(np.round(M.current_paper().reshape(-1, 3).mean(0) + 255 * dev), 0, 255).astype(np.uint8)

for tag, args in {'s28c70': ((3.5, 8, 16, 28), (0.2, 0.35, 0.5, 0.5), 70, 0.030, 0.020),
                  's22c56': ((3.5, 7, 13, 22), (0.2, 0.35, 0.5, 0.5), 56, 0.030, 0.020),
                  'b_s28c70': ((3.5, 8, 16, 28), (0.2, 0.35, 0.5, 0.5), 70, 0.027, 0.028)}.items():
    rgb8 = build(*args)
    st = M.paper_stats(rgb8)
    print(tag, 'std', st['luma_std'], 'lowfreq', st['lowfreq_share_lambda_ge_256px'], 'blob', st['max_blob_over_std_sigma24'])
    Image.fromarray(np.tile(rgb8, (2, 3, 1))).resize((int(3072 * 0.6428), int(2048 * 0.6428)), Image.BILINEAR).save(f'{SP}/exp4_{tag}_tiled.png')
    Image.fromarray(rgb8[100:400, 150:950]).save(f'{SP}/exp4_{tag}_crop.png')
