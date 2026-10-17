import sys
sys.path.insert(0, "/home/user/mygame/lantern-next/art"); sys.path.insert(0, "/home/user/mygame/lantern-next/art/models"); sys.path.insert(0, "/home/user/mygame/lantern-next/art/post")
from style import style as S, bstyle as B
import postprocess as P, rock, stone_lantern, bpy, numpy as np
from PIL import Image
OUT = "/tmp/claude-0/-home-user-mygame/01f265ce-5196-560e-be75-2f924c080bfe/scratchpad/t"
tiles = []
for kind in ["a", "b", "c", "lantern"]:
    B.reset_scene(); B.setup_render(96); B.setup_camera(96, anchor=S.PROP_ANCHOR); B.verify_camera(96, verbose=False); B.setup_freestyle()
    root, parts, socks = stone_lantern.build_stone_lantern() if kind == "lantern" else rock.build_rock(kind)
    print(kind, "faces", B.face_count(root))
    L = B.render_layers(OUT + "/tp")
    r = P.process_layers(L, kind)
    print(kind, "%.2fs" % L["time_s"], r["stats"], [B.project_point(s.matrix_world.translation, 96) for s in socks.values()])
    tiles.append(r["rgba"])
paper = tuple(S.hex_to_rgb(S.PAPER)) + (255,)
sheet = Image.new("RGBA", (96 * len(tiles), 96), paper)
for i, t in enumerate(tiles):
    sheet.alpha_composite(Image.fromarray(t), (96 * i, 0))
sheet.convert("RGB").resize((96 * len(tiles) * 3, 288), Image.NEAREST).save(OUT + "/props_zoom.png")
