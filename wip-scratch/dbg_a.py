import sys
sys.path[:0] = ["/home/user/mygame/art", "/home/user/mygame/art/models", "/home/user/mygame/art/post", "/home/user/mygame/art/render"]
import os; os.environ["LANTERN_ART_DENSITY"] = "2"
import enemy_sample_a as EA
import bpy
from style import bstyle as B
EA._setup("shade")
import v2kit as V2, shade_v2 as M, enemy_design as DZ
V2.setup_lines()
root, parts, socks = M.build_shade()
print([o.name for o in bpy.data.objects if "Crack" in o.name])
B.set_direction(root, "E"); bpy.context.view_layer.update()
tree = V2.bvh_world(parts["shell"])
for cr, w in DZ.shade_cracks():
    hits = V2.project_design(tree, cr)
    print(len(cr), sum(h is not None for h, _ in hits), cr[0])
hits = V2.project_design(tree, [DZ.SH_HOLLOW[0]])
print("hollow hit", hits)
# 兜帽口中心在屏幕上的位置：脸轴与表面的交点
import mathutils
fc = parts["shell"].parent.matrix_world @ M.FACE_C
fd = (parts["shell"].parent.matrix_world.to_3x3() @ M.face_dir()).normalized()
hit = tree.ray_cast(fc, fd)
print("face axis hit", hit[0], B.project_point(hit[0], 224) if hit[0] else None)
