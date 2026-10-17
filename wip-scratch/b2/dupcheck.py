import os, sys
os.environ.setdefault("LANTERN_ART_DENSITY", "2")
sys.path[:0] = ["art", "art/models", "art/post", "art/render"]
import enemies_v2 as EV
import importlib, bpy
name = sys.argv[1]
cfg = EV.V2[name]
EV._setup(name)
M = importlib.import_module(cfg["module"])
print("=== build")
root, parts, socks = getattr(M, cfg["build"])()
print("=== pose")
getattr(M, cfg["pose"])(parts, cfg["anims"][0][0], 1, cfg["anims"][0][1])
print("=== done")
for ob in bpy.data.objects:
    if ob.type == "MESH":
        me = ob.data
        print(f"{ob.name:24s} v={len(me.vertices):6d} f={len(me.polygons):6d}")
