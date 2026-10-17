import sys, json
from pathlib import Path
sys.path.insert(0, "/home/user/mygame/art"); sys.path.insert(0, "/home/user/mygame/art/post")
from PIL import Image
import contact_sheet as CS
root = Path(sys.argv[1]); keys = sys.argv[3].split(","); out = sys.argv[2]
crop = int(sys.argv[4]) if len(sys.argv) > 4 else 0
tiles = []
for k in keys:
    base = Image.open(root/"hero"/f"{k}.png").convert("RGBA")
    meta = json.loads((root/"hero"/"meta.json").read_text())
    for lid in ["old", "red", "mirror", "frost", "none"]:
        if lid not in ("old","none") and not (root/f"lantern_{lid}"/f"{k}.png").exists(): lid = "none"
        if lid == "old":
            im = Image.open(f"/home/user/mygame/art/out/assets@2x/_hero_before_split/{k}.png").convert("RGBA")
        elif lid == "none":
            im = base
        else:
            im = base.copy(); im.alpha_composite(Image.open(root/f"lantern_{lid}"/f"{k}.png").convert("RGBA"))
        bg = CS.paper(im.width, im.height, seed=2); bg.alpha_composite(im)
        if crop:
            an, d, i = k.split("_"); sx, sy = meta["sockets"]["lantern"][an][d][int(i)]
            cx, cy = 160 + sx, 280 + sy
            bg = bg.crop((int(cx-crop), int(cy-crop), int(cx+crop), int(cy+crop)))
        tiles.append(bg.convert("RGB"))
W = tiles[0].width; H = tiles[0].height
sheet = Image.new("RGB", (W*5, H*len(keys)))
for n, t in enumerate(tiles):
    sheet.paste(t, ((n % 5)*W, (n//5)*H))
z = int(sys.argv[5]) if len(sys.argv) > 5 else 1
sheet.resize((sheet.width*z, sheet.height*z), Image.NEAREST).save(out)
