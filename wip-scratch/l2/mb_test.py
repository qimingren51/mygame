import bpy, bmesh
from mathutils import Vector
bpy.ops.wm.read_factory_settings(use_empty=True)
for stiff in (2.0, 4.0, 8.0):
    mb = bpy.data.metaballs.new("MB")
    mb.resolution = 0.05
    mb.render_resolution = 0.05
    mb.threshold = 0.6
    el = mb.elements.new(type="CAPSULE")
    el.co = (0, 0, 0)
    el.radius = 1.0
    el.size_x = 1.0
    el.stiffness = stiff
    ob = bpy.data.objects.new("MBo", mb)
    bpy.context.scene.collection.objects.link(ob)
    dg = bpy.context.evaluated_depsgraph_get()
    me = bpy.data.meshes.new_from_object(ob.evaluated_get(dg))
    xs = [v.co.x for v in me.vertices]; ys = [v.co.y for v in me.vertices]
    print("stiff", stiff, "x", min(xs), max(xs), "y", min(ys), max(ys), len(me.vertices))
    bpy.data.objects.remove(ob)
