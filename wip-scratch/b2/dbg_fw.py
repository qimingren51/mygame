import os, sys
os.environ.setdefault("LANTERN_ART_DENSITY", "2")
sys.path[:0] = ["art", "art/models", "art/post", "art/render"]
import enemies_v2 as EV, importlib, bpy
from style import bstyle as B
EV._setup("fox_wisp")
M = importlib.import_module("fox_wisp_v2")
root, parts, socks = M.build_fox_wisp()
B.set_direction(root, "E"); bpy.context.view_layer.update()
right, up, _ = B.camera_basis()
for ob in bpy.data.objects:
    if ob.name.startswith("FoxWispSocket") or ob.name.startswith("FoxWispEye"):
        mw = ob.matrix_world
        pts = [(25*(mw @ v.co).dot(right), 25*(mw @ v.co).dot(up)) for v in ob.data.vertices]
        if not pts: print(ob.name, 'empty'); continue
        xs=[p[0] for p in pts]; ys=[p[1] for p in pts]
        print(f"{ob.name:22s} n={len(pts):4d} faces={len(ob.data.polygons):4d} x[{min(xs):.2f},{max(xs):.2f}] y[{min(ys):.2f},{max(ys):.2f}]")
