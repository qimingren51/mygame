import sys, math
sys.path.insert(0, "art/render")
import card_art as K
K.load_scenes()
import bpy
import numpy as np
from PIL import Image
K.reset_scene(32, True)
sys.path.insert(0, "art/models")
import hero as H
from style import bstyle as B
for name in [*B.LINE_COLLECTIONS.values(), B.CONTOUR_COLLECTION, B.CUN_COLLECTION]:
    coll = bpy.data.collections.new(name)
    bpy.context.scene.collection.children.link(coll)
root, parts, sockets = H.build_hero(lamps=("red",))
print("parts keys", list(parts)[:40])
H.pose_hero(parts, "dash", 2, 8)
print("objects", len(bpy.data.objects))
# 看包围盒
from mathutils import Vector
bpy.context.view_layer.update()
mins = Vector((9, 9, 9)); maxs = Vector((-9, -9, -9))
for ob in bpy.data.objects:
    if ob.type == "MESH":
        for c in ob.bound_box:
            w = ob.matrix_world @ Vector(c)
            mins = Vector(map(min, mins, w)); maxs = Vector(map(max, maxs, w))
print("bbox", tuple(mins), tuple(maxs))
dark = K.Mat("Sil")
b = dark.principled(Base_Color=(0.02, 0.02, 0.025, 1.0), Roughness=0.6)
dark.surface(b.outputs[0])
for ob in bpy.data.objects:
    if ob.type in ("MESH", "CURVE"):
        ob.data.materials.clear() if hasattr(ob.data, "materials") else None
        try:
            ob.data.materials.append(dark.m)
        except Exception as e:
            print("mat fail", ob.name, e)
K.set_world((0.6, 0.7, 0.9), 1.0)
K.camera((3.5, -6.0, 1.2), (0, 0, 1.1), lens=50.0)
K.render_to_cache("zz_hero", True)
d = np.load("art/out/_card_tmp/zz_hero_draft.npz")
rgb = np.clip(d["rgba"][..., :3].astype(np.float32), 0, 1) ** (1 / 2.2)
Image.fromarray((rgb * 255).astype(np.uint8)).save("/tmp/claude-0/-home-user-mygame/01f265ce-5196-560e-be75-2f924c080bfe/scratchpad/l2/hero_test.png")
