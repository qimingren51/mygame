import sys
sys.path.insert(0, "/home/user/mygame/lantern-next/art"); sys.path.insert(0, "/home/user/mygame/lantern-next/art/models"); sys.path.insert(0, "/home/user/mygame/lantern-next/art/post")
from style import style as S, bstyle as B
import postprocess as P, shade, bpy, numpy as np
from PIL import Image
OUT = "/tmp/claude-0/-home-user-mygame/01f265ce-5196-560e-be75-2f924c080bfe/scratchpad/t"
tiles = []
for kind in ["shade", "wisp"]:
    B.reset_scene(); B.setup_render(80); B.setup_camera(80); B.setup_freestyle()
    root, parts, socks = shade.build_shade() if kind == "shade" else shade.build_wisp()
    B.set_direction(root, "E")
    print(kind, "faces", B.face_count(root))
    for fr in (0, 2):
        shade.pose_ghost(parts, "float", fr, 8)
        L = B.render_layers(OUT + "/tg")
        r = P.process_layers(L, kind)
        print(kind, fr, "%.2fs" % L["time_s"], r["stats"])
        tiles.append(r["rgba"])
paper = tuple(S.hex_to_rgb(S.PAPER)) + (255,)
sheet = Image.new("RGBA", (80 * len(tiles), 80), paper)
for i, t in enumerate(tiles):
    sheet.alpha_composite(Image.fromarray(t), (80 * i, 0))
sheet.convert("RGB").resize((80 * len(tiles) * 4, 320), Image.NEAREST).save(OUT + "/ghost_zoom.png")
