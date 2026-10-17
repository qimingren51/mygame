import sys, math
sys.path.insert(0, "/home/user/mygame/lantern-next/art")
from style import style as S
from style import bstyle as B
import bpy, numpy as np
OUT = "/tmp/claude-0/-home-user-mygame/01f265ce-5196-560e-be75-2f924c080bfe/scratchpad/t"
for variant in ["nonoise", "noise_add"]:
    B.reset_scene(); B.setup_render(128); B.setup_camera(128); B.setup_freestyle()
    st = bpy.data.linestyles["InkOuter"]
    nz = st.thickness_modifiers["Pressure"]
    if variant == "nonoise": nz.use = False
    if variant == "noise_mult": nz.blend = "MULTIPLY"; nz.amplitude = 0.5
    if variant == "noise_add_asym": nz.use_asymmetric = True
    root = B.empty("root")
    m = B.toon_material("robe", S.ACCENT["huaqing"])
    B.mesh_object("ball", B.uv_sphere(0.4, 32, 16), m, "outer", root, loc=(0, 0, 0.4))
    L = B.render_layers(OUT + "/t5")
    a = L["lines"][..., 3]
    per = 2 * math.pi * 0.4 * 50 * 4  # 圆周（渲染像素）
    print(variant, "mean width px(render) = %.1f  expected ~%.1f" % (a.sum() / per, 0.8 * S.LINE_OUTER_PX * 4))
