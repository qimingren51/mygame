import sys
from pathlib import Path
ART = Path("art").resolve()
for p in (ART, ART / "models", ART / "render", ART / "post"):
    sys.path.insert(0, str(p))
import pipeline  # noqa
import bpy
from mathutils import Vector
import stone_lantern as SL
from style import bstyle as B
B.reset_scene()
SL.build_stone_lantern()
bpy.context.view_layer.update()
hi = -1e9
for ob in bpy.data.objects:
    if ob.type == "MESH":
        for c in ob.bound_box:
            hi = max(hi, (ob.matrix_world @ Vector(c)).z)
print("stone_lantern z max", round(hi, 3))
