import sys, numpy as np
from pathlib import Path
ART = Path("/home/user/mygame/lantern-next/art")
for p in (ART, ART / "models", ART / "post", ART / "render"):
    sys.path.insert(0, str(p))
from style import style as S
from pipeline import render_asset
import hero as HERO, shade as G
from PIL import Image
OUT = Path(sys.argv[1]); REF = ART / "out" / sys.argv[2]
render_asset("hero", S.FRAME["hero"], HERO.build_hero,
             [("idle", "S", 0, 6), ("idle", "E", 0, 6), ("walk", "E", 0, 8), ("walk", "E", 1, 8), ("walk", "E", 2, 8)],
             OUT, pose=HERO.pose_hero, sockets_wanted=("lantern",))
render_asset("shade", S.FRAME["small"], G.build_shade, [("float", "E", 0, 8), ("float", "E", 1, 8)], OUT,
             pose=G.pose_ghost, sockets_wanted=("eyes",), flash=True)
for n in ["hero/idle_S_00", "hero/idle_E_00", "hero/walk_E_02", "shade/float_E_00", "shade/float_E_01"]:
    a = np.asarray(Image.open(OUT / f"{n}.png")).astype(int); b = np.asarray(Image.open(REF / f"{n}.png")).astype(int)
    d = np.abs(a - b)
    print(n, a.shape, "mean|d| rgba", d.mean(axis=(0, 1)).round(3), "px with any |d|>8:", int((d.max(-1) > 8).sum()), "of", int((b[..., 3] > 0).sum()))
