# 量模型的世界包围盒（米）
import sys
from pathlib import Path
ART = Path("art").resolve()
for p in (ART, ART / "models", ART / "render", ART / "post"):
    sys.path.insert(0, str(p))
import pipeline  # noqa
import bpy
from mathutils import Vector
import qingqiu_props as Q
from style import bstyle as B
for n in sys.argv[1:]:
    B.reset_scene()
    Q.BUILDERS[n]()
    bpy.context.view_layer.update()
    lo = Vector((1e9,) * 3); hi = Vector((-1e9,) * 3)
    for ob in bpy.data.objects:
        if ob.type != "MESH":
            continue
        for c in ob.bound_box:
            w = ob.matrix_world @ Vector(c)
            lo = Vector(map(min, lo, w)); hi = Vector(map(max, hi, w))
    print(n, "x", round(lo.x, 3), round(hi.x, 3), "y", round(lo.y, 3), round(hi.y, 3), "z", round(lo.z, 3), round(hi.z, 3))
