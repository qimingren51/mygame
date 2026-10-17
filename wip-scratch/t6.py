import sys, math
sys.path.insert(0, "/home/user/mygame/lantern-next/art")
from style import style as S
from style import bstyle as B
import bpy, bmesh, numpy as np
from mathutils import Vector, noise
from PIL import Image
OUT = "/tmp/claude-0/-home-user-mygame/01f265ce-5196-560e-be75-2f924c080bfe/scratchpad/t"
tiles = []
for variant in ["ridge", "sugg", "both"]:
    B.reset_scene(); B.setup_render(96); B.setup_camera(96); B.setup_freestyle()
    fs = bpy.context.scene.view_layers[0].freestyle_settings
    fs.use_ridges_and_valleys = variant in ("ridge", "both")
    fs.use_suggestive_contours = variant in ("sugg", "both")
    cun = bpy.data.collections.new("InkCun"); bpy.context.scene.collection.children.link(cun)
    ls = fs.linesets.new("Cun"); ls.select_by_visibility=True; ls.select_by_edge_types=True
    for a in ("silhouette","border","crease","external_contour","contour","suggestive_contour","ridge_valley","material_boundary","edge_mark"):
        setattr(ls, "select_"+a, (a=="ridge_valley" and variant in ("ridge","both")) or (a=="suggestive_contour" and variant in ("sugg","both")))
    ls.select_by_collection=True; ls.collection=cun; ls.linestyle=bpy.data.linestyles["InkInner"]
    m = B.toon_material("rock", ramp=[S.INK["qing"], S.INK["dan"], S.INK["zhong"]])
    def build(bm):
        bmesh.ops.create_icosphere(bm, subdivisions=4, radius=1.0)
        for v in bm.verts:
            p = v.co.copy()
            d = 1 + 0.18*noise.noise(p*1.3 + Vector((3,1,2))) + 0.07*noise.noise(p*3.1)
            v.co = p*d
            v.co.x *= 0.55; v.co.y *= 0.35; v.co.z = max(v.co.z*0.45, -0.02) + 0.05
    ob = B.mesh_object("rock", build, m, "outer", None, smooth=True, sharp_deg=0)
    cun.objects.link(ob)
    L = B.render_layers(OUT + "/t6")
    a = L["lines"][..., 3]; f = L["fill"]
    tiles.append((255 - a*255).astype(np.uint8)); print(variant, L["time_s"], len(ob.data.polygons))
Image.fromarray(np.concatenate(tiles, 1)).save(OUT + "/t6.png")
