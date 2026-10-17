import sys
from pathlib import Path
from PIL import Image
d = Path(sys.argv[1]); out = sys.argv[2]
names = sorted(p.stem for p in d.glob("icon_*.png"))
order = ["lamp","sword","bell","crane","seal"]
seq = [f"icon_{w}" for w in order] + [f"icon_{w}_evo" for w in order] + ["icon_"+p for p in ["changming","luxin","jianyi","ruimu","jingxin","yinhun","zhezhi","jixing","houde","panshi"]] + [f"icon_el_{e}" for e in ["metal","wood","water","fire","earth"]]
ims = [Image.open(d / f"{n}.png").convert("RGBA") for n in seq]
cell = 140
W = 10 * cell; H = 3 * 2 * cell + 40
canvas = Image.new("RGB", (W, H), (60, 60, 60))
for i, im in enumerate(ims):
    r, c = divmod(i, 10)
    for k, bg in enumerate([(237,228,207),(22,27,44)]):
        big = im.resize((128,128), Image.LANCZOS if im.width != 128 else Image.NEAREST)
        small = im.resize((32,32), Image.LANCZOS)
        t = Image.new("RGB", (cell, cell), bg)
        t.paste(big, (2, 6), big); 
        x0 = c*cell; y0 = (r*2 + k)*cell
        canvas.paste(t, (x0, y0))
        canvas.paste(Image.new("RGB",(34,34),bg),(x0+cell-36, y0+cell-36))
        canvas.paste(small, (x0+cell-35, y0+cell-35), small)
canvas.save(out)
