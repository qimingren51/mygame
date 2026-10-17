import sys, json, os
sys.path.insert(0, "/home/user/mygame/art/render")
import portrait as PT
from PIL import Image
cfgs = json.loads(sys.argv[1]); out = sys.argv[2]
px = int(round(PT.SIZE * PT.D))
tiles = []
for c in cfgs:
    for k, v in c.items():
        setattr(PT, k, tuple(v) if isinstance(v, list) else v)
    b = PT.render_bust(px)
    img = PT.compose_portrait(b)
    raw = Image.fromarray(b["rgba"])
    t = Image.new("RGBA", (512 * 2 + 64 + 128, 512), (237, 228, 207, 255))
    t.alpha_composite(raw.resize((512, 512), Image.LANCZOS), (0, 0))
    t.alpha_composite(img.resize((512, 512), Image.LANCZOS), (512, 0))
    t.alpha_composite(img.resize((64, 64), Image.LANCZOS), (1024, 10))
    nb = Image.new("RGBA", (128, 200), (22, 27, 44, 255)); nb.alpha_composite(img.resize((64, 64), Image.LANCZOS), (32, 10)); nb.alpha_composite(img.resize((128, 128), Image.LANCZOS), (0, 72))
    t.alpha_composite(nb, (1024 + 64, 0))
    tiles.append(t)
W = Image.new("RGB", (tiles[0].width, 512 * len(tiles)))
for i, t in enumerate(tiles): W.paste(t.convert("RGB"), (0, i * 512))
W.save(out)
