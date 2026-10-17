import sys, time
sys.path.insert(0, "/home/user/mygame/lantern-next/art")
sys.path.insert(0, "/home/user/mygame/lantern-next/art/models")
sys.path.insert(0, "/home/user/mygame/lantern-next/art/post")
from style import style as S
from style import bstyle as B
import postprocess as P
import hero
import bpy, numpy as np
from PIL import Image
OUT = "/tmp/claude-0/-home-user-mygame/01f265ce-5196-560e-be75-2f924c080bfe/scratchpad/t"
dirs = sys.argv[1].split(",") if len(sys.argv) > 1 else ["S", "SE", "E", "NE", "N"]
anim = sys.argv[2] if len(sys.argv) > 2 else "idle"
fr = int(sys.argv[3]) if len(sys.argv) > 3 else 0
B.reset_scene(); B.setup_render(128); B.setup_camera(128); B.setup_freestyle()
root, parts, sockets = hero.build_hero()
print("faces", B.face_count(root))
hero.pose_hero(parts, anim, fr, 8 if anim == "walk" else 6)
tiles = []
for d in dirs:
    B.set_direction(root, d)
    L = B.render_layers(OUT + "/th")
    r = P.process_layers(L, "hero")
    print(d, "render %.2fs" % L["time_s"], r["stats"])
    tiles.append(r["rgba"])
paper = np.array(S.hex_to_rgb(S.PAPER), np.uint8)
sheet = Image.new("RGBA", (128 * len(tiles), 128), tuple(paper) + (255,))
for i, t in enumerate(tiles):
    sheet.alpha_composite(Image.fromarray(t), (128 * i, 0))
sheet = sheet.convert("RGB")
sheet.save(OUT + "/hero_sheet.png")
sheet.resize((sheet.width * 3, sheet.height * 3), Image.NEAREST).save(OUT + "/hero_zoom.png")
