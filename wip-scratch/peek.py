"""快速看几帧（裁到内容并放大）：python peek.py [--base=dir] out.png zoom asset:key ...（主角自动叠红纸灯）"""
import sys
from pathlib import Path
from PIL import Image
args = sys.argv[1:]
base = Path("art/out/assets@2x")
if args[0].startswith("--base="):
    base = Path(args[0].split("=", 1)[1]); args = args[1:]
out, zoom, keys = args[0], int(args[1]), args[2:]
PAPER = (237, 228, 207)
ims = []
rows_break = []
for k in keys:
    if k == "|":
        rows_break.append(len(ims)); continue
    a, key = k.split(":")
    b = base
    if "@" in a:
        a, b = a.split("@", 1); b = Path(b)
    im = Image.open(b / a / f"{key}.png").convert("RGBA")
    if a == "hero" and (b / ("lantern_" + __import__("os").environ.get("LAMP", "red")) / f"{key}.png").exists():
        im.alpha_composite(Image.open(b / ("lantern_" + __import__("os").environ.get("LAMP", "red")) / f"{key}.png").convert("RGBA"))
    ims.append(im)
x0 = y0 = 10**9; x1 = y1 = 0
for im in ims:
    bb = im.getchannel("A").getbbox()
    if bb:
        x0, y0, x1, y1 = min(x0, bb[0]), min(y0, bb[1]), max(x1, bb[2]), max(y1, bb[3])
box = (max(0, x0 - 4), max(0, y0 - 4), x1 + 4, y1 + 4)
tiles = []
for im in ims:
    bg = Image.new("RGBA", im.size, PAPER + (255,))
    bg.alpha_composite(im)
    tiles.append(bg.convert("RGB").crop(box))
cuts = [0] + rows_break + [len(tiles)]
rows = [tiles[a:b] for a, b in zip(cuts, cuts[1:]) if b > a]
W = max(sum(t.width + 6 for t in r) for r in rows); H = max(t.height for t in tiles)
o = Image.new("RGB", (W, (H + 6) * len(rows)), (200, 190, 170))
for ri, r in enumerate(rows):
    x = 0
    for t in r:
        o.paste(t, (x, ri * (H + 6))); x += t.width + 6
o = o.resize((o.width * zoom, o.height * zoom), Image.NEAREST)
o.save(out)
print(o.size)
