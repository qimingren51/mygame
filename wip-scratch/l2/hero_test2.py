import sys, math
sys.path.insert(0, "art/render")
import card_art as K
K.load_scenes()
import bpy
import numpy as np
from PIL import Image
sys.path.insert(0, "art/models")
from style import bstyle as B
out = []
for fr in (0, 2, 4, 6):
    K.reset_scene(16, True)
    for name in [*B.LINE_COLLECTIONS.values(), B.CONTOUR_COLLECTION, B.CUN_COLLECTION]:
        coll = bpy.data.collections.new(name)
        bpy.context.scene.collection.children.link(coll)
    import hero as H
    root, parts, sockets = H.build_hero(lamps=("red",))
    H.pose_hero(parts, "dash", fr, 8)
    root.rotation_euler = (0, 0, math.radians(90))
    dark = K.Mat("Sil")
    b = dark.principled(Base_Color=(0.02, 0.02, 0.025, 1.0), Roughness=0.6)
    dark.surface(b.outputs[0])
    for ob in bpy.data.objects:
        if ob.type == "MESH":
            ob.data.materials.clear()
            ob.data.materials.append(dark.m)
    K.set_world((0.6, 0.7, 0.9), 1.0)
    K.camera((0.0, -8.0, 1.2), (0, 0, 1.1), lens=50.0)
    K.render_to_cache(f"zz_hero{fr}", True)
    d = np.load(f"art/out/_card_tmp/zz_hero{fr}_draft.npz")
    out.append(np.clip(d["rgba"][..., :3].astype(np.float32), 0, 1) ** (1 / 2.2))
img = np.concatenate(out, 1)
Image.fromarray((img * 255).astype(np.uint8)).save("/tmp/claude-0/-home-user-mygame/01f265ce-5196-560e-be75-2f924c080bfe/scratchpad/l2/hero_test2.png")
