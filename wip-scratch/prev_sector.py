import sys, math
sys.path.insert(0, "/home/user/mygame/art/post")
from pathlib import Path
import numpy as np
from PIL import Image
import weapon_textures as W
V = W.V
OUT = Path(__file__).resolve().parent
sec, fill = W.make_sector(), W.make_sector_fill()
anc = (W.SECTOR_APEX[0] / W.SECTOR_W, 0.5)
paper = np.asarray(Image.open(V.GROUND_DIR / "paper.png").convert("RGB"), dtype=np.float64)[:600, :1000] / 255.0
night = paper * V.col(V.S.NIGHT_AMBIENT)
red = V.col("#FF4A3A")
for cv in (paper, night):
    W.place(cv, sec, 60, 300, anchor=anc, mode="add", tint=red)
    W.place(cv, sec, 420, 300, anchor=anc, mode="add", tint=red, angle=math.radians(-35), scale=1.6)
    W.place(cv, fill, 420, 300, anchor=anc, mode="add", tint=red * 0.8, angle=math.radians(-35), scale=1.6 * 0.6)
out = np.vstack([paper, night])
Image.fromarray(np.round(np.clip(out, 0, 1) * 255).astype(np.uint8)).save(OUT / "prev_sector.png")
big = Image.new("RGB", (sec.width * 2 + 20, sec.height), (22, 27, 44))
big.paste(sec, (0, 0), sec); big.paste(fill, (sec.width + 20, 0), fill)
big.save(OUT / "prev_sector_raw.png")
print(sec.size)
