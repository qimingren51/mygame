import sys
sys.path.insert(0, "/home/user/mygame/lantern-next/art"); sys.path.insert(0, "/home/user/mygame/lantern-next/art/models"); sys.path.insert(0, "/home/user/mygame/lantern-next/art/post")
from style import style as S, bstyle as B
import postprocess as P, event_props as EP, bpy, numpy as np
from PIL import Image
OUT = "/tmp/claude-0/-home-user-mygame/01f265ce-5196-560e-be75-2f924c080bfe/scratchpad/t"
F = S.FRAME["prop"]; tiles = []
for fn in ["build_ancient_lamp", "build_blood_altar"]:
    B.reset_scene(); B.setup_render(F); B.setup_camera(F, anchor=S.PROP_ANCHOR); B.setup_freestyle()
    root, parts, socks = getattr(EP, fn)()
    B.set_direction(root, "S")
    L = B.render_layers(OUT + "/tp2"); r = P.process_layers(L, fn)
    a = r["rgba"][..., 3]; ys, xs = np.where(a > 128)
    print(fn, B.face_count(root), "%.2fs" % L["time_s"], r["stats"], "bbox", xs.min(), xs.max(), ys.min(), ys.max())
    tiles.append(r["rgba"])
sheet = Image.new("RGBA", (F * 2, F), tuple(S.hex_to_rgb(S.PAPER)) + (255,))
for i, t in enumerate(tiles): sheet.alpha_composite(Image.fromarray(t), (F * i, 0))
sheet.convert("RGB").resize((F * 6, F * 3), Image.NEAREST).save(OUT + "/ep_zoom.png")
