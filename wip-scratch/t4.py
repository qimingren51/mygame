import sys
sys.path.insert(0, "/home/user/mygame/lantern-next/art")
from style import style as S
from style import bstyle as B
import bpy, numpy as np
from PIL import Image
OUT = "/tmp/claude-0/-home-user-mygame/01f265ce-5196-560e-be75-2f924c080bfe/scratchpad/t"
tiles = []
for variant in [2.0, 20.0, 200.0, 2000.0]:
    B.reset_scene(); B.setup_render(128); B.setup_camera(128); B.setup_freestyle()
    st = bpy.data.linestyles["InkOuter"]
    keep = ["Wobble","Pressure","Overshoot"]; st.thickness_modifiers["Pressure"].period = variant
    for mods in (st.thickness_modifiers, st.geometry_modifiers):
        for mo in mods:
            if mo.name in ("Wobble","Pressure","Overshoot"): mo.use = mo.name in keep
    root = B.empty("root")
    m = B.toon_material("robe", S.ACCENT["huaqing"])
    B.mesh_object("ball", B.uv_sphere(0.4, 32, 16), m, "outer", root, loc=(0, 0, 0.4))
    L = B.render_layers(OUT + "/t4")
    a = L["lines"][..., 3]
    tiles.append((255 - a * 255).astype(np.uint8)[200:470, 120:390])
Image.fromarray(np.concatenate(tiles, 1)).save(OUT + "/t4.png")
