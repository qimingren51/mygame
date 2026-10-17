import sys, importlib
sys.path.insert(0, "/home/user/mygame/lantern-next/art"); sys.path.insert(0, "/home/user/mygame/lantern-next/art/models"); sys.path.insert(0, "/home/user/mygame/lantern-next/art/post")
from style import style as S, bstyle as B
import postprocess as P, bpy, numpy as np
from PIL import Image
OUT = "/tmp/claude-0/-home-user-mygame/01f265ce-5196-560e-be75-2f924c080bfe/scratchpad/t"
mod, frame_key, n = sys.argv[1], sys.argv[2], int(sys.argv[3])
frames = [int(x) for x in sys.argv[4].split(",")]
M = importlib.import_module(mod)
nm = sys.argv[5] if len(sys.argv) > 5 else mod
build = getattr(M, f"build_{nm}"); pose = getattr(M, f"pose_{nm}"); mod = nm
F = S.FRAME[frame_key]
B.reset_scene(); B.setup_render(F); B.setup_camera(F, anchor=S.BIG_ENEMY_ANCHOR if frame_key in ("golem", "elite", "boss") else S.ANCHOR); B.setup_freestyle()
root, parts, socks = build()
print(mod, "faces", B.face_count(root))
tiles = []
for fr in frames:
    B.set_direction(root, "E")
    pose(parts, "move", fr, n)
    L = B.render_layers(OUT + "/tm")
    r = P.process_layers(L, mod)
    a = r["rgba"][..., 3]; ys, xs = np.where(a > 128)
    print(fr, "%.2fs" % L["time_s"], r["stats"], "bbox x", xs.min(), xs.max(), "y", ys.min(), ys.max(), "w", xs.max() - xs.min(), "target w", None)
    tiles.append(r["rgba"])
paper = tuple(S.hex_to_rgb(S.PAPER)) + (255,)
sheet = Image.new("RGBA", (F * len(tiles), F), paper)
for i, t in enumerate(tiles):
    sheet.alpha_composite(Image.fromarray(t), (F * i, 0))
sheet = sheet.convert("RGB"); sheet.save(OUT + f"/{mod}_1x.png")
z = 3 if F <= 160 else 2
sheet.resize((sheet.width * z, sheet.height * z), Image.NEAREST).save(OUT + f"/{mod}_zoom.png")
