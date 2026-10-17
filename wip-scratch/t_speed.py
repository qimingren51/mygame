import sys, time, math
sys.path.insert(0, "/home/user/mygame/art")
import bpy
from style import bstyle as B
t0=time.time()
bpy.ops.wm.read_factory_settings(use_empty=True)
sc=bpy.context.scene
r=sc.render; r.engine="CYCLES"; r.resolution_x=960; r.resolution_y=720; r.film_transparent=True
r.compositor_device="CPU"; r.use_compositing=False
cy=sc.cycles; cy.device="CPU"; cy.samples=128; cy.use_adaptive_sampling=True; cy.adaptive_threshold=0.02
cy.use_denoising=True
print("denoisers:", [e.identifier for e in cy.bl_rna.properties['denoiser'].enum_items])
cy.denoiser="OPENIMAGEDENOISE"
print("view transforms:", [e.identifier for e in sc.view_settings.bl_rna.properties['view_transform'].enum_items])
# objects
bpy.ops.mesh.primitive_uv_sphere_add(radius=1, segments=64, ring_count=32)
s=bpy.context.object; bpy.ops.object.shade_smooth()
m=bpy.data.materials.new("bronze"); nt=m.node_tree
p=nt.nodes.get("Principled BSDF")
print("principled inputs:", [i.name for i in p.inputs])
p.inputs["Metallic"].default_value=1; p.inputs["Roughness"].default_value=0.35
p.inputs["Base Color"].default_value=(0.5,0.32,0.15,1)
s.data.materials.append(m)
bpy.ops.mesh.primitive_plane_add(size=10, location=(0,0,-1))
L=bpy.data.lights.new("key","AREA"); L.energy=500; L.size=2
lo=bpy.data.objects.new("key",L); sc.collection.objects.link(lo); lo.location=(3,-3,4); lo.rotation_euler=(math.radians(45),0,math.radians(45))
print("light props:", [p.identifier for p in L.bl_rna.properties][:60])
cam=bpy.data.objects.new("cam",bpy.data.cameras.new("cam")); sc.collection.objects.link(cam); sc.camera=cam
cam.location=(0,-5,0.5); cam.rotation_euler=(math.radians(85),0,0)
cam.data.dof.use_dof=True; cam.data.dof.focus_distance=5; cam.data.dof.aperture_fstop=2.8
sc.world=bpy.data.worlds.new("w"); 
print("world nodes:", [n.name for n in sc.world.node_tree.nodes] if sc.world.node_tree else None)
im=r.image_settings; im.media_type="MULTI_LAYER_IMAGE"; im.file_format="OPEN_EXR_MULTILAYER"; im.exr_codec="NONE"; im.color_depth="32"
r.filepath="/tmp/claude-0/-home-user-mygame/01f265ce-5196-560e-be75-2f924c080bfe/scratchpad/t_speed.exr"
t1=time.time()
bpy.ops.render.render(write_still=True)
print("setup %.2f render %.2f"%(t1-t0, time.time()-t1))
ch=B.read_exr_none(r.filepath)
print(sorted(ch.keys()))
