import sys, time
sys.path.insert(0, "/home/user/mygame/art/post")
from pathlib import Path
import numpy as np
from PIL import Image
import ground_decor as G
V, W = G.V, G.W
OUT = Path(__file__).resolve().parent
t0 = time.time()
lava, lg = G.make_zone_lava(); mud = G.make_zone_mud(); herb, hg = G.make_zone_herb()
print("t", time.time() - t0, lava.size, mud.size, herb.size)
paper = np.asarray(Image.open(V.GROUND_DIR / "paper.png").convert("RGB"), dtype=np.float64) / 255.0
H = 700; Wd = 1500
base = np.tile(paper, (2, 2, 1))[:H, :Wd].copy()
night = base * V.col(V.S.NIGHT_AMBIENT)
for cv, dark in ((base, False), (night, True)):
    W.place(cv, lava, 250, 200); W.place(cv, mud, 750, 200); W.place(cv, herb, 1250, 200)
    if dark:
        W.place(cv, lg, 250, 200, mode="add", tint=V.col("#FF7A2A")); W.place(cv, hg, 1250, 200, mode="add", tint=V.col("#9CF0B8"))
out = np.vstack([base[:420], night[:420]])
Image.fromarray(np.round(np.clip(out, 0, 1) * 255).astype(np.uint8)).save(OUT / "prev_zones.png")
