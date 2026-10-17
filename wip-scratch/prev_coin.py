import sys
sys.path.insert(0, "/home/user/mygame/art/post")
from pathlib import Path
import numpy as np
from PIL import Image
import vfx_textures as V
OUT = Path(__file__).resolve().parent
coin, emit = V.make_coin(), V.make_coin_emit()
gem = Image.open(V.VFX_DIR / "gem_1.png").convert("RGBA")
paper = np.asarray(Image.open(V.GROUND_DIR / "paper.png").convert("RGB"), dtype=np.float64)[:300, :500] / 255.0
night = paper * V.col(V.S.NIGHT_AMBIENT)
for cv, dark in ((paper, False), (night, True)):
    for k, sc in enumerate((1, 4)):
        x0 = 20 + k * 140
        c = coin.resize((coin.width * sc, coin.height * sc), Image.NEAREST) if sc > 1 else coin
        e = emit.resize((emit.width * sc, emit.height * sc), Image.NEAREST) if sc > 1 else emit
        V.composite(cv, c, x0, 40, "over", scale=1)
        if dark:
            V.composite(cv, e, x0, 40, "add", scale=1)
    V.composite(cv, gem, 440, 60, "add", tint=V.col(V.S.SOUL_LIGHT), scale=1)
out = np.vstack([paper, night])
Image.fromarray(np.round(np.clip(out, 0, 1) * 255).astype(np.uint8)).resize((1000, 1200), Image.NEAREST).save(OUT / "prev_coin.png")
print(coin.size, emit.size)
