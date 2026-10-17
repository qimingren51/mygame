import sys, json
sys.path.insert(0, "/home/user/mygame/art/render")
import portrait as PT
from PIL import Image, ImageDraw
cfgs = json.loads(sys.argv[1])
out = sys.argv[2]
px = int(sys.argv[3]) if len(sys.argv) > 3 else 128
ims = []
for c in cfgs:
    for k, v in c.items():
        setattr(PT, k, tuple(v) if isinstance(v, list) else v)
    b = PT.render_bust(px)
    im = Image.fromarray(b["rgba"])
    bg = Image.new("RGBA", im.size, (237, 228, 207, 255)); bg.alpha_composite(im)
    bg = bg.resize((512, 512), Image.LANCZOS)
    d = ImageDraw.Draw(bg); f = 512 / px
    x, y = b["lantern_px"]; d.ellipse([x*f-3, y*f-3, x*f+3, y*f+3], outline=(0, 0, 255, 255))
    for k, (x, y, v) in b["face"].items():
        c = (0, 160, 255, 255) if k.endswith("_L") else (255, 0, 200, 255)
        d.point((x*f, y*f), fill=c)
    ims.append(bg)
W = Image.new("RGB", (512 * len(ims), 512))
for i, im in enumerate(ims): W.paste(im.convert("RGB"), (i * 512, 0))
W.save(out)
