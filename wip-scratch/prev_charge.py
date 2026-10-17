import sys, math
sys.path.insert(0, "/home/user/mygame/art/post")
from pathlib import Path
import numpy as np
from PIL import Image
import weapon_textures as W
V = W.V; D = V.D
OUT = Path(__file__).resolve().parent
body, head = W.make_charge_line(), W.make_charge_line_head()
print(body.size, head.size)
paper = np.asarray(Image.open(V.GROUND_DIR / "paper.png").convert("RGB"), dtype=np.float64)[:500, :1100] / 255.0
night = paper * V.col(V.S.NIGHT_AMBIENT)
red = V.col("#FF4A3A")
L = 200 * V.S.PX_PER_UNIT  # 200 世界单位
hl = V.dpx(W.HEAD_TIP - W.HEAD_BASE)
for cv, mode in ((paper, "over"), (night, "add")):
    for (x0, y0, ang) in ((60, 120, 0.0), (80, 330, math.radians(-12))):
        k = (L - hl) / body.width
        W.place(cv, body, x0, y0, anchor=(0.0, 0.5), angle=ang, scale=(k, 1.0), mode=mode, tint=red, alpha=1.0 if mode == "add" else 0.6)
        ex, ey = x0 + (L - hl) * math.cos(ang), y0 + (L - hl) * math.sin(ang)
        W.place(cv, head, ex, ey, anchor=(W.HEAD_BASE / W.HEAD_W, 0.5), angle=ang, mode=mode, tint=red, alpha=1.0 if mode == "add" else 0.6)
out = np.vstack([paper, night])
Image.fromarray(np.round(np.clip(out, 0, 1) * 255).astype(np.uint8)).save(OUT / "prev_charge.png")
raw = Image.new("RGB", (body.width + head.width + 20, max(body.height, head.height) * 3), (22, 27, 44))
raw.paste(body, (0, 10), body); raw.paste(head, (body.width + 10, 0), head)
raw.resize((raw.width * 3, raw.height * 3), Image.NEAREST).save(OUT / "prev_charge_raw.png")
