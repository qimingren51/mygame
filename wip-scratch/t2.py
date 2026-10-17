import sys
sys.path.insert(0, "/home/user/mygame/lantern-next/art")
from style import style as S
from style import bstyle as B
import bpy, numpy as np
OUT = "/tmp/claude-0/-home-user-mygame/01f265ce-5196-560e-be75-2f924c080bfe/scratchpad/t"
for variant in ["base", "bounces1", "nofreestyle", "sample1"]:
    B.reset_scene(); B.setup_render(64, samples=4); B.setup_camera(64)
    if variant != "nofreestyle": B.setup_freestyle()
    if variant == "bounces1": bpy.context.scene.cycles.max_bounces = 1
    root = B.empty("root")
    e = B.emissive_material("eye", S.EYE["shade"])
    ob = B.mesh_object("eye", B.uv_sphere(0.3), e, "none", root, loc=(0, 0, 0.3))
    ob.pass_index = 1
    L = B.render_layers(OUT + "/t2")
    print(variant, ob.pass_index, np.unique(L["index"])[:5], L["fill"][...,3].max())
