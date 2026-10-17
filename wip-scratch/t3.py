import sys
sys.path.insert(0, "/home/user/mygame/lantern-next/art")
from style import style as S
from style import bstyle as B
import bpy, numpy as np
OUT = "/tmp/claude-0/-home-user-mygame/01f265ce-5196-560e-be75-2f924c080bfe/scratchpad/t"
for variant in ["s16", "s16_64"]:
    B.reset_scene(); B.setup_render(128 if variant=='s16' else 64, samples=16); B.setup_camera(64)
    vl = bpy.context.scene.view_layers[0]
    root = B.empty("root")
    if variant == "diffuse":
        e = bpy.data.materials.new("d")
    else:
        e = B.emissive_material("eye", S.EYE["shade"])
    e.pass_index = 2
    vl.use_pass_z = True
    B.setup_freestyle()
    if variant=='fs_mat': vl.use_pass_material_index=True
    if variant == "nontransparent": bpy.context.scene.render.film_transparent = False
    ob = B.mesh_object("eye", B.uv_sphere(0.3), e, "none", root, loc=(0, 0, 0.3))
    ob.pass_index = 1
    L = B.render_layers(OUT + "/t3", keep_exr=True)
    ch = B.read_exr_none(L["exr"])
    print(variant, {k: np.unique(v)[:4] for k, v in ch.items() if not k.endswith(('.R','.G','.B'))})
