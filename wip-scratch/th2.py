import sys
sys.path.insert(0, "/home/user/mygame/lantern-next/art"); sys.path.insert(0, "/home/user/mygame/lantern-next/art/models"); sys.path.insert(0, "/home/user/mygame/lantern-next/art/post")
from style import style as S, bstyle as B
import postprocess as P, hero, bpy, numpy as np
from PIL import Image
OUT = "/tmp/claude-0/-home-user-mygame/01f265ce-5196-560e-be75-2f924c080bfe/scratchpad/t"
jobs = [tuple(j.split(":")) for j in sys.argv[1].split(",")]  # anim:dir:frame
tag = sys.argv[2] if len(sys.argv) > 2 else "h"
F = S.FRAME["hero"]
B.reset_scene(); B.setup_render(F); B.setup_camera(F); B.setup_freestyle()
root, parts, socks = hero.build_hero()
print("faces", B.face_count(root))
tiles = []
for anim, d, fr in jobs:
    parts["dir"] = d
    B.set_direction(root, d)
    hero.pose_hero(parts, anim, int(fr), {"walk": 8, "idle": 6, "dash": 4, "hurt": 2, "death": 6}[anim])
    L = B.render_layers(OUT + "/th2")
    r = P.process_layers(L, "hero")
    print(anim, d, fr, "%.2fs" % L["time_s"], r["stats"])
    tiles.append(r["rgba"])
paper = tuple(S.hex_to_rgb(S.PAPER)) + (255,)
sheet = Image.new("RGBA", (F * len(tiles), F), paper)
for i, t in enumerate(tiles):
    sheet.alpha_composite(Image.fromarray(t), (F * i, 0))
sheet = sheet.convert("RGB"); sheet.save(OUT + f"/{tag}_1x.png")
sheet.resize((sheet.width * 3, sheet.height * 3), Image.NEAREST).save(OUT + f"/{tag}_zoom.png")
