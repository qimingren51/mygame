import sys, math
sys.path.insert(0, "art/render")
import card_art as K
K.load_scenes()
import bpy
sys.path.insert(0, "art/models")
from style import bstyle as B
K.reset_scene(16, True)
for name in [*B.LINE_COLLECTIONS.values(), B.CONTOUR_COLLECTION, B.CUN_COLLECTION]:
    coll = bpy.data.collections.new(name)
    bpy.context.scene.collection.children.link(coll)
import hero as H
root, parts, sockets = H.build_hero(lamps=("red",))
print(sorted(o.name for o in bpy.data.objects))
print("lantern", parts["lantern"].name, [c.name for c in parts["lantern"].children_recursive][:20])
