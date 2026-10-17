import sys
sys.path.insert(0, "/home/user/mygame/lantern-next/art"); sys.path.insert(0, "/home/user/mygame/lantern-next/art/models"); sys.path.insert(0, "/home/user/mygame/lantern-next/art/post")
from style import style as S, bstyle as B
import postprocess as P, shade, rock, bpy, numpy as np
from PIL import Image
OUT = "/tmp/claude-0/-home-user-mygame/01f265ce-5196-560e-be75-2f924c080bfe/scratchpad/t"
tiles = []
for kind in ["shade", "rock1", "rock2"]:
    fp = S.FRAME["small"] if kind == "shade" else S.FRAME["prop"]
    B.reset_scene(); B.setup_render(fp); B.setup_camera(fp); B.setup_freestyle()
    if kind == "shade":
        root, parts, socks = shade.build_shade(); B.set_direction(root, "E")
    else:
        root, parts, socks = rock.build_rock(int(kind[-1]) * 7 + 2)
    print(kind, "faces", B.face_count(root))
    L = B.render_layers(OUT + "/ts")
    r = P.process_layers(L, kind)
    print(kind, "%.2fs" % L["time_s"], r["stats"])
    tiles.append(r["rgba"])
paper = tuple(S.hex_to_rgb(S.PAPER)) + (255,)
W = sum(t.shape[1] for t in tiles)
sheet = Image.new("RGBA", (W, 96), paper); x = 0
for t in tiles:
    sheet.alpha_composite(Image.fromarray(t), (x, 96 - t.shape[0])); x += t.shape[1]
sheet = sheet.convert("RGB"); sheet.resize((W * 3, 288), Image.NEAREST).save(OUT + "/sr_zoom.png")
