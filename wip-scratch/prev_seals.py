import sys
sys.path.insert(0, "/home/user/mygame/art/post")
from pathlib import Path
from PIL import Image
import ui_seals as Z, ui_icons as U
from concurrent.futures import ProcessPoolExecutor
OUT = Path(__file__).resolve().parent
specs = Z.seal_specs()
idx = [i for i, s in enumerate(specs) if s["fname"].startswith("seal_react") or s["fname"] in ("seal_fen", "seal_tian")]
def job(i): return i, Z.make_seal(i)
with ProcessPoolExecutor(4) as ex: res = dict(ex.map(job, idx))
paper = tuple(int(c * 255) for c in U.PAPER)
cw = 128 + 48 + 28 + 30
sheet = Image.new("RGB", (6 * cw, 2 * 150 + 10), paper)
for j, i in enumerate(idx):
    im = res[i]
    x, y = (j % 6) * cw + 8, (j // 6) * 150 + 8
    sheet.paste(im, (x, y), im)
    for s, dx in ((48, 136), (28, 190)):
        sm = im.resize((s, s), Image.LANCZOS); sheet.paste(sm, (x + dx, y), sm)
sheet.save(OUT / "prev_seals.png"); print("ok")
