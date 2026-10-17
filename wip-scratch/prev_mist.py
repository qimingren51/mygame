import sys
import time

sys.path.insert(0, "/home/user/mygame/art/post")
import numpy as np
from PIL import Image

import vfx_textures as V

SP = "/tmp/claude-0/-home-user-mygame/01f265ce-5196-560e-be75-2f924c080bfe/scratchpad/"
rows = []
for i in range(2):
    t0 = time.time()
    im = V.make_mist(i)
    a = np.asarray(im)[..., 3].astype(float)
    print(i, im.size, f"{time.time() - t0:.1f}s mean {a.mean() / 255:.3f} <10: {(a < 10).mean():.3f} >200: {(a > 200).mean():.3f}")
    for ax in (0, 1):
        wrap = np.abs(np.take(a, 0, ax) - np.take(a, -1, ax)).mean()
        inner = np.abs(np.diff(a, axis=ax)).mean()
        print("  seam ratio", ax, round(wrap / inner, 3))
    tile = np.tile(a, (2, 2)) / 255.0
    night = np.array([22, 27, 44]) / 255.0
    tint = np.array([200, 211, 230]) / 255.0
    full = night * (1 - tile[..., None]) + tint * tile[..., None]
    game = night * (1 - 0.3 * tile[..., None]) + tint * 0.3 * tile[..., None]
    rows.append(np.concatenate([full, np.ones((full.shape[0], 8, 3)), game], 1))
out = np.concatenate([rows[0], np.ones((8, rows[0].shape[1], 3)), rows[1]], 0)
Image.fromarray((out * 255).astype(np.uint8)).save(SP + "prev_mist.png")
