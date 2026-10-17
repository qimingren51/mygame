import bpy, sys
print(bpy.app.version_string)
sc = bpy.context.scene
vl = sc.view_layers[0]
fs = vl.freestyle_settings
ls = fs.linesets.new("X")
print([p for p in dir(ls) if not p.startswith('_')])
st = bpy.data.linestyles.new("S")
m = st.thickness_modifiers.new(name="n", type="NOISE")
print("noise", [p for p in dir(m) if not p.startswith('_')])
g = st.geometry_modifiers.new(name="p", type="PERLIN_NOISE_1D")
print("perlin", [p for p in dir(g) if not p.startswith('_')])
print("style", [p for p in dir(st) if not p.startswith('_') and ('split' in p or 'angle' in p or 'chain' in p or 'length' in p or 'thick' in p)])
print([p for p in dir(vl) if 'pass' in p])
print([p for p in dir(fs) if not p.startswith('_')])
