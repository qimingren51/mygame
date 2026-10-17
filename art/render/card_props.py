"""升级卡插画的共用道具与材质（card_weapons.py、card_passives.py 用）：剑、符纸、纸鹤、石印、铜钱、屋瓦、岩石、小妖……

都是 bmesh 程序化建模，材质用 card_art.Mat 拼节点。坐标单位米，物体各自的约定写在函数说明里。
"""

from __future__ import annotations

import math

import numpy as np

import card_art as K
from card_art import Mat, lathe_uv, make_obj, ribbon_uv, tube_uv

# ====================================================================== 材质


def mat_steel(name, tint=(0.80, 0.82, 0.86), rough=0.16, pattern=0.5, dark=0.0, edge_glow=None):
    """剑身的钢：金属，沿刃长的折叠花纹（拉长的波纹）调粗糙度和一点明暗；dark>0 时整体压暗（旧铁）。
    edge_glow=(颜色, 强度)：两道刃口发一点光（剑气），后期的泛光把它晕开。刃口在 blade_build 的 UV.y = 0、0.5、1。"""
    M = Mat(name)
    m = M.math
    oc = M.coord("Object")
    mp = M.n("ShaderNodeMapping")
    M.l(oc, mp.inputs["Vector"])
    mp.inputs["Scale"].default_value = (2.0, 40.0, 40.0)
    wave = M.n("ShaderNodeTexWave", _wave_type="BANDS", _bands_direction="Z", Scale=6.0, Distortion=7.0, Detail=4.0,
               Detail_Scale=1.5)
    M.l(mp.outputs["Vector"], wave.inputs["Vector"])
    nz = M.noise(oc, scale=120.0, detail=6.0, rough=0.6)
    pat = m("MULTIPLY", M.maprange(wave.outputs["Fac"], 0.2, 0.8), pattern)
    col = M.mix(pat, (*tint, 1.0), (tint[0] * 0.72, tint[1] * 0.74, tint[2] * 0.78, 1.0))
    if dark:
        col = M.mix(dark, col, (0.05, 0.05, 0.055, 1.0))
    rr = m("ADD", rough, m("MULTIPLY", m("ADD", m("MULTIPLY", pat, 0.10), M.maprange(nz.outputs["Fac"], 0.35, 0.7, -0.03, 0.05)), 1.0))
    bsdf = M.principled(Base_Color=col, Metallic=1.0, Roughness=rr)
    if edge_glow:
        uv = M.coord("UV")
        sep = M.n("ShaderNodeSeparateXYZ")
        M.l(uv, sep.inputs[0])
        v = sep.outputs["Y"]
        dist = m("MINIMUM", m("MINIMUM", v, m("ABSOLUTE", m("SUBTRACT", v, 0.5))), m("SUBTRACT", 1.0, v))
        mask = m("EXPONENT", m("MULTIPLY", m("POWER", m("DIVIDE", dist, 0.035), 2.0), -1.0))
        bsdf.inputs["Emission Color"].default_value = (*edge_glow[0], 1.0)
        M.l(m("MULTIPLY", mask, edge_glow[1]), bsdf.inputs["Emission Strength"])
    return M.surface(bsdf.outputs[0])


def mat_glow_shell(name, color, strength=3.0, power=2.2, blend=0.3):
    """光晕壳：套在物体外面放大一点的壳，越靠轮廓越亮、正对镜头的地方透明（做剑气、灵光）。"""
    M = Mat(name)
    m = M.math
    lw = M.n("ShaderNodeLayerWeight", Blend=blend)
    a = m("POWER", m("SUBTRACT", 1.0, lw.outputs["Facing"], clamp=True), power)
    a = m("SUBTRACT", 1.0, a, clamp=True)  # 正对 → 1，边上 → 0
    a = m("MULTIPLY", m("POWER", a, 1.5), 1.0)
    emi = M.n("ShaderNodeEmission", Color=(*color, 1.0))
    M.l(m("MULTIPLY", a, strength), emi.inputs["Strength"])
    tr = M.n("ShaderNodeBsdfTransparent")
    add = M.n("ShaderNodeAddShader")
    M.l(tr.outputs[0], add.inputs[0])
    M.l(emi.outputs[0], add.inputs[1])
    return M.surface(add.outputs[0])


def mat_emit(name, color, strength=5.0):
    M = Mat(name)
    emi = M.n("ShaderNodeEmission", Color=(*color, 1.0), Strength=strength)
    return M.surface(emi.outputs[0])


def mat_image_paper(name, img, translucent=0.35, rough=0.75, back=None, bump=0.15):
    """贴图的纸（符纸、方纸）：颜色从 img（sRGB）取，背光透一点（Translucent），纸纤维凹凸。UV 取物体的 UVMap。"""
    M = Mat(name)
    m = M.math
    uv = M.coord("UV")
    t = M.n("ShaderNodeTexImage", _interpolation="Cubic", _extension="CLIP")
    t.image = img
    M.l(uv, t.inputs["Vector"])
    oc = M.coord("Object")
    fib = M.noise(oc, scale=260.0, detail=6.0, rough=0.7)
    nrm = M.bump(fib.outputs["Fac"], strength=bump, distance=0.0008)
    bsdf = M.principled(Base_Color=t.outputs["Color"], Roughness=rough, Normal=nrm, Specular_IOR_Level=0.3)
    trn = M.n("ShaderNodeBsdfTranslucent")
    M.l(M.mix(0.0, t.outputs["Color"], t.outputs["Color"]), trn.inputs["Color"])
    M.l(nrm, trn.inputs["Normal"])
    mx = M.n("ShaderNodeMixShader")
    mx.inputs[0].default_value = translucent
    M.l(bsdf.outputs[0], mx.inputs[1])
    M.l(trn.outputs[0], mx.inputs[2])
    _ = m
    return M.surface(mx.outputs[0])


def mat_paper_plain(name, color=(0.86, 0.84, 0.78), translucent=0.30, rough=0.8, fold_tex=None):
    """白纸（纸鹤、方纸）：漫反射 + 透光，纸纤维与很淡的斑点。"""
    M = Mat(name)
    m = M.math
    oc = M.coord("Object")
    fib = M.noise(oc, scale=300.0, detail=6.0, rough=0.7)
    spot = M.noise(oc, scale=25.0, detail=3.0)
    col = M.mix(m("MULTIPLY", M.maprange(spot.outputs["Fac"], 0.45, 0.75), 0.25), (*color, 1.0),
                (color[0] * 0.8, color[1] * 0.76, color[2] * 0.66, 1.0))
    nrm = M.bump(fib.outputs["Fac"], strength=0.12, distance=0.0006)
    bsdf = M.principled(Base_Color=col, Roughness=rough, Normal=nrm, Specular_IOR_Level=0.25)
    trn = M.n("ShaderNodeBsdfTranslucent")
    M.l(col, trn.inputs["Color"])
    M.l(nrm, trn.inputs["Normal"])
    mx = M.n("ShaderNodeMixShader")
    mx.inputs[0].default_value = translucent
    M.l(bsdf.outputs[0], mx.inputs[1])
    M.l(trn.outputs[0], mx.inputs[2])
    return M.surface(mx.outputs[0])


def mat_stone(name, color=(0.16, 0.15, 0.14), rough=0.85, scale=6.0, moss=0.0, cavity=0.6, bump=0.8, bump_dist=0.01):
    """石头：多层噪声的明暗与凹凸，凹处压暗（AO），可加一点青苔。大块的石头（米级）把 bump_dist 调大。"""
    M = Mat(name)
    m = M.math
    oc = M.coord("Object")
    n1 = M.noise(oc, scale=scale, detail=8.0, rough=0.62)
    n2 = M.noise(oc, scale=scale * 7.0, detail=6.0, rough=0.7)
    n3 = M.noise(oc, scale=scale * 0.6, detail=3.0)
    ao = M.n("ShaderNodeAmbientOcclusion", Distance=0.05, _samples=8)
    cav = m("SUBTRACT", 1.0, ao.outputs["AO"], clamp=True)
    v = m("ADD", m("MULTIPLY", M.maprange(n1.outputs["Fac"], 0.3, 0.7), 0.6), m("MULTIPLY", M.maprange(n2.outputs["Fac"], 0.3, 0.7), 0.4))
    col = M.mix(v, (color[0] * 0.55, color[1] * 0.55, color[2] * 0.55, 1.0), (color[0] * 1.35, color[1] * 1.35, color[2] * 1.3, 1.0))
    col = M.mix(m("MULTIPLY", cav, cavity, clamp=True), col, (0.01, 0.01, 0.01, 1.0))
    if moss:
        geo = M.n("ShaderNodeNewGeometry")
        sz = M.n("ShaderNodeSeparateXYZ")
        M.l(geo.outputs["Normal"], sz.inputs[0])
        mm = m("MULTIPLY", M.maprange(sz.outputs["Z"], 0.4, 0.9), M.maprange(n3.outputs["Fac"], 0.45, 0.6))
        col = M.mix(m("MULTIPLY", mm, moss, clamp=True), col, (0.035, 0.06, 0.03, 1.0))
    h = m("ADD", n1.outputs["Fac"], m("MULTIPLY", n2.outputs["Fac"], 0.5))
    nrm = M.bump(h, strength=bump, distance=bump_dist)
    bsdf = M.principled(Base_Color=col, Roughness=rough, Normal=nrm)
    return M.surface(bsdf.outputs[0])


def mat_bronze(name, base=(0.30, 0.19, 0.08), patina=(0.05, 0.12, 0.10), patina_amt=0.5, rough=0.35, gilt=0.0):
    """青铜（铜钱、铃、塔刹）：磨亮的铜 + 凹处与斑块的青绿锈；gilt>0 时偏金。"""
    M = Mat(name)
    m = M.math
    oc = M.coord("Object")
    n1 = M.noise(oc, scale=18.0, detail=6.0, rough=0.65)
    n2 = M.noise(oc, scale=70.0, detail=6.0, rough=0.7)
    ao = M.n("ShaderNodeAmbientOcclusion", Distance=0.008, _samples=8)
    cav = m("SUBTRACT", 1.0, ao.outputs["AO"], clamp=True)
    p = m("ADD", m("MULTIPLY", M.maprange(n1.outputs["Fac"], 0.45, 0.7), patina_amt), m("MULTIPLY", cav, 1.6 * patina_amt), clamp=True)
    metal_c = base if not gilt else tuple(b * (1 - gilt) + g * gilt for b, g in zip(base, (0.85, 0.58, 0.20)))
    bcol = M.mix(M.maprange(n2.outputs["Fac"], 0.3, 0.7), (metal_c[0] * 0.7, metal_c[1] * 0.7, metal_c[2] * 0.7, 1.0), (*metal_c, 1.0))
    col = M.mix(p, bcol, (*patina, 1.0))
    met = m("SUBTRACT", 1.0, p, clamp=True)
    rr = M.mixf(p, rough, 0.7)
    nrm = M.bump(m("ADD", n2.outputs["Fac"], m("MULTIPLY", p, 0.6)), strength=0.25, distance=0.002)
    bsdf = M.n("ShaderNodeBsdfPrincipled")
    M.l(col, bsdf.inputs["Base Color"])
    M.l(met, bsdf.inputs["Metallic"])
    M.l(rr, bsdf.inputs["Roughness"])
    M.l(nrm, bsdf.inputs["Normal"])
    return M.surface(bsdf.outputs[0])


def mat_wood_plain(name, color=(0.07, 0.045, 0.028), rough=0.7, grain_scale=(0.6, 18.0, 18.0)):
    """木头：顺纹的拉长噪声 + 几道裂。"""
    M = Mat(name)
    oc = M.coord("Object")
    mp = M.n("ShaderNodeMapping")
    M.l(oc, mp.inputs["Vector"])
    mp.inputs["Scale"].default_value = grain_scale
    g = M.noise(mp.outputs["Vector"], scale=3.0, detail=8.0, rough=0.62, dist=0.5)
    col = M.mix(M.maprange(g.outputs["Fac"], 0.3, 0.7), (color[0] * 0.5, color[1] * 0.5, color[2] * 0.5, 1.0), (*color, 1.0))
    nrm = M.bump(g.outputs["Fac"], strength=0.3, distance=0.004)
    bsdf = M.principled(Base_Color=col, Roughness=rough, Normal=nrm)
    return M.surface(bsdf.outputs[0])


def mat_silk(name, color, sheen=0.9, rough=0.45):
    M = Mat(name)
    bsdf = M.principled(Base_Color=(*color, 1.0), Roughness=rough, Sheen_Weight=sheen, Sheen_Roughness=0.35,
                        Sheen_Tint=(1.0, 0.85, 0.75, 1.0))
    return M.surface(bsdf.outputs[0])


# ====================================================================== 贴图


def talisman_texture(chars="雷令", w=256, h=1024, seed=3):
    """黄符：土黄纸（有纤维、边上旧一点），朱砂双框、顶上一个符头（圈和几笔）、中间竖写几个字、下面几道曲折的符脚。
    返回 (h, w, 3) 0..1（sRGB）。纸的长边是竖的（UV.x 沿长时，用的时候转 90°）。"""
    from PIL import Image, ImageDraw, ImageFilter, ImageFont  # noqa: PLC0415

    rng = np.random.default_rng(seed)
    V = K.vfx()
    paper = np.ones((h, w, 3)) * K.hexc("#C8A24A")
    fib = V.fft_blur(rng.standard_normal((h, w)), (1.0, 14.0))
    fib = fib / (fib.std() + 1e-9)
    blot = V.fft_blur(rng.standard_normal((h, w)), 40.0)
    blot = blot / (blot.std() + 1e-9)
    paper *= (1 + 0.05 * fib + 0.08 * blot)[..., None]
    Y, X = np.mgrid[0:h, 0:w]
    edge = np.minimum(np.minimum(X, w - X), np.minimum(Y, h - Y))
    paper *= (1 - 0.25 * np.exp(-edge / 10.0))[..., None]
    ink = Image.new("L", (w, h), 0)
    dr = ImageDraw.Draw(ink)
    dr.rectangle((14, 14, w - 15, h - 15), outline=255, width=5)
    dr.rectangle((24, 24, w - 25, h - 25), outline=255, width=2)
    # 符头：一个圈，圈里一点，圈上三笔
    cx, cy = w // 2, 120
    dr.ellipse((cx - 46, cy - 46, cx + 46, cy + 46), outline=255, width=7)
    dr.ellipse((cx - 12, cy - 12, cx + 12, cy + 12), fill=255)
    for dx in (-30, 0, 30):
        dr.line((cx + dx, cy - 52, cx + dx * 1.4, cy - 86), fill=255, width=6)
    f = ImageFont.truetype(str(K.FONT_BRUSH), int(w * 0.62))
    y = 200
    for ch in chars:
        bb = dr.textbbox((0, 0), ch, font=f)
        dr.text((cx - (bb[2] - bb[0]) / 2 - bb[0], y - bb[1]), ch, font=f, fill=255)
        y += int(w * 0.70)
    # 符脚：几道曲折线
    pts = []
    for i in range(14):
        pts.append((cx + (34 if i % 2 else -34) * (1 - i / 16), y + 18 * i))
    dr.line(pts, fill=255, width=6, joint="curve")
    ink = ink.filter(ImageFilter.GaussianBlur(1.0))
    a = np.asarray(ink, np.float64) / 255.0
    dry = V.fft_blur(rng.standard_normal((h, w)), (6.0, 1.0))
    a = np.clip(a * (0.80 + 0.2 * np.tanh(dry / (dry.std() + 1e-9))), 0, 1)
    red = K.hexc("#A3200F")
    out = paper * (1 - a[..., None]) + red * a[..., None]
    return np.clip(out, 0, 1)


# ====================================================================== 剑


def blade_build(L=0.74, W=0.034, T=0.0075, tip=0.11, taper=0.16):
    """剑身（沿 +X，剑根在 x=0）：截面是扁菱形（中间起脊、两边斜到刃），宽度往剑尖收一点，最后 tip 一段收成剑尖。
    宽度方向是 Z、厚度方向是 Y（镜头在 -Y 看到剑面）。平直着色时每个斜面是一整块平面。"""
    n = 90

    def half_w(t):
        base = 1 - taper * t
        if t > 1 - tip:
            s = min(max((t - (1 - tip)) / tip, 0.0), 1.0)
            base *= max(1 - s ** 1.7, 0.0) ** 0.75
        return max(base * W / 2, 0.0003)

    def build(bm):
        uvl = bm.loops.layers.uv.new("UVMap")
        rings = []
        for i in range(n + 1):
            t = i / n
            hw = half_w(t)
            th = T / 2 * (1 - 0.35 * t) * (hw / (W / 2)) ** 0.35
            sec = [(0.0, hw), (th * 0.80, hw * 0.38), (th, 0.0), (th * 0.80, -hw * 0.38), (0.0, -hw), (-th * 0.80, -hw * 0.38),
                   (-th, 0.0), (-th * 0.80, hw * 0.38)]
            rings.append([bm.verts.new((L * t, y, z)) for y, z in sec])
        tipv = bm.verts.new((L * 1.0015, 0.0, 0.0))
        k = len(rings[0])
        for i in range(n):
            for j in range(k):
                f = bm.faces.new((rings[i][j], rings[i][(j + 1) % k], rings[i + 1][(j + 1) % k], rings[i + 1][j]))
                for lp, uv in zip(f.loops, ((i / n, j / k), (i / n, (j + 1) / k), ((i + 1) / n, (j + 1) / k), ((i + 1) / n, j / k))):
                    lp[uvl].uv = uv
        for j in range(k):
            bm.faces.new((rings[-1][j], rings[-1][(j + 1) % k], tipv))
        bm.faces.new(list(reversed(rings[0])))
        import bmesh  # noqa: PLC0415

        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)

    return build


def sword(name, *, L=0.74, W=0.034, T=0.0075, steel=None, gold=None, grip_m=None, tassel_m=None, loc=(0, 0, 0), rot=(0, 0, 0),
          scale=1.0, index=1, tassel=True, parent=None):
    """一柄剑（沿 +X，剑格在原点）：剑身、剑格（铜鎏金，两翼微翘）、缠绳的剑柄、剑首（圆饼）、剑穗（往 -X 飘）。
    返回父物体（空物体）；子物体的 pass_index = index。剑气的光用 mat_steel(edge_glow=...)。"""
    bpy = K._bpy()
    root = bpy.data.objects.new(name, None)
    K.link(root, parent)
    root.location, root.rotation_euler, root.scale = loc, rot, (scale, scale, scale)
    steel = steel or mat_steel(f"{name}_Steel")
    gold = gold or K.mat_gold(f"{name}_Gold", worn=0.5)
    grip_m = grip_m or mat_silk(f"{name}_Grip", (0.035, 0.022, 0.018), sheen=0.5, rough=0.6)
    make_obj(f"{name}_Blade", blade_build(L, W, T), steel, smooth=False, parent=root, index=index)
    # 剑格：一块扁的“一字格”，两翼在宽度方向（Z）伸出、末端微微翘向剑身
    def guard(bm):
        prof = []
        for t in np.linspace(-1, 1, 41):
            z = t * W * 1.25
            hx = 0.012 * (1 - 0.35 * abs(t) ** 2) + 0.004 * abs(t) ** 6
            xc = -0.004 + 0.007 * abs(t) ** 3
            prof.append((xc, z, hx))
        rows = []
        for xc, z, hx in prof:
            ry = T * 1.9 * (1 - 0.25 * abs(z) / (W * 1.25))
            ring = []
            for a in np.linspace(0, 2 * math.pi, 20, endpoint=False):
                ring.append(bm.verts.new((xc + hx * math.cos(a), ry * math.sin(a), z)))
            rows.append(ring)
        for r0, r1 in zip(rows, rows[1:]):
            for j in range(20):
                bm.faces.new((r0[j], r0[(j + 1) % 20], r1[(j + 1) % 20], r1[j]))
        bm.faces.new(list(reversed(rows[0])))
        bm.faces.new(rows[-1])
        import bmesh  # noqa: PLC0415

        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)

    make_obj(f"{name}_Guard", guard, gold, parent=root, index=index, subsurf=1)
    # 剑柄：椭圆截面，缠绳（螺旋管）
    gl = 0.17
    make_obj(f"{name}_Grip", lathe_uv([(0.0, 0.0), (0.0105, 0.0), (0.0115, 0.02), (0.0112, gl - 0.02), (0.0105, gl), (0.0, gl)],
                                      segments=32), grip_m, parent=root, rot=(0, -math.pi / 2, 0), loc=(-0.010, 0, 0), index=index)
    cord = []
    turns = 13
    for i in range(turns * 24 + 1):
        a = 2 * math.pi * i / 24
        x = -0.014 - (gl - 0.012) * i / (turns * 24)
        cord.append((x, 0.0122 * math.cos(a), 0.0122 * math.sin(a)))
    make_obj(f"{name}_Cord", tube_uv(cord, 0.0022, sides=8), grip_m, parent=root, index=index)
    # 剑首：圆饼
    px = -0.010 - gl
    make_obj(f"{name}_Pommel", lathe_uv([(0.0, 0.0), (0.016, 0.0), (0.022, 0.006), (0.024, 0.014), (0.020, 0.022), (0.0, 0.024)],
                                        segments=40), gold, parent=root, rot=(0, -math.pi / 2, 0), loc=(px, 0, 0), index=index)
    if tassel:
        tassel_m = tassel_m or mat_silk(f"{name}_Tassel", (0.45, 0.04, 0.025))
        rng = np.random.default_rng(7)
        cpts = [(px - 0.024 - 0.012 * i, 0.002 * math.sin(i), -0.008 * i - 0.0006 * i * i) for i in range(10)]
        make_obj(f"{name}_TasselCord", tube_uv(cpts, 0.0026, sides=8), tassel_m, parent=root, index=index)
        hx, hz = cpts[-1][0], cpts[-1][2]
        make_obj(f"{name}_Knot", K.ico_cloud([(0, 0, 0)], [0.010], 2), tassel_m, parent=root, loc=(hx, 0, hz), index=index)

        def strands(bm):
            import bmesh  # noqa: PLC0415

            for _ in range(60):
                a = rng.uniform(0, 2 * math.pi)
                rr = 0.0055 * math.sqrt(rng.uniform(0.1, 1))
                Ls = rng.uniform(0.09, 0.13)
                pts = [(hx - 0.006 - Ls * t * 0.85, rr * math.cos(a) * (1 + t), hz - 0.004 + rr * math.sin(a) * (1 + t) - Ls * 0.45 * t * t)
                       for t in np.linspace(0, 1, 8)]
                tmp = bmesh.new()
                tube_uv(pts, 0.0008, sides=4, caps=False)(tmp)
                me = bpy.data.meshes.new("tmp")
                tmp.to_mesh(me)
                tmp.free()
                bm.from_mesh(me)
                bpy.data.meshes.remove(me)

        make_obj(f"{name}_Strands", strands, tassel_m, parent=root, index=index)
    return root


def talisman_strip(name, pts, width, img, *, ups=None, index=1, parent=None, curl_amp=0.0):
    """符纸：沿 pts 的纸条（ribbon_uv，UV.x 沿长 0..1），贴图是竖长的符（转 90° 映到条上）。"""
    bpy = K._bpy()
    mat = mat_image_paper(f"{name}_M", img, translucent=0.38)
    # ribbon_uv 的 UV：x 沿长、y 横跨；符图竖长 → 用 Mapping 转一下：交换 UV 两轴
    nt = mat.node_tree
    tex = next(n for n in nt.nodes if n.bl_idname == "ShaderNodeTexImage")
    uvn = next(n for n in nt.nodes if n.bl_idname == "ShaderNodeTexCoord")
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    comb = nt.nodes.new("ShaderNodeCombineXYZ")
    nt.links.new(uvn.outputs["UV"], sep.inputs[0])
    nt.links.new(sep.outputs["Y"], comb.inputs["X"])
    inv = nt.nodes.new("ShaderNodeMath")
    inv.operation = "SUBTRACT"
    inv.inputs[0].default_value = 1.0
    nt.links.new(sep.outputs["X"], inv.inputs[1])
    nt.links.new(inv.outputs[0], comb.inputs["Y"])
    nt.links.new(comb.outputs[0], tex.inputs["Vector"])
    curl = (lambda t, s: curl_amp * math.sin(math.pi * (s + 0.5)) * t) if curl_amp else None
    ob = make_obj(name, ribbon_uv(pts, width, ups=ups, segs_w=6, curl=curl), mat, parent=parent, index=index)
    _ = bpy
    return ob


# ====================================================================== 纸鹤


def crane_build(wing_up=0.10, wing_sweep=0.0, neck_up=0.16, tail_up=0.14, scale=1.0, wing_bend=0.03):
    """折纸鹤（朝 +X，Y 是左右，Z 朝上）：菱形身子、细长的颈和尾斜着往上、颈头折下一个小喙，两片三角大翅。
    每个面都是平的（平直着色），折痕处颜色由材质按 AO 压一点。wing_up：翅尖抬高；wing_sweep：翅尖前后（+ 往前）。"""
    s = scale

    def V(x, y, z):
        return (x * s, y * s, z * s)

    def build(bm):
        import bmesh  # noqa: PLC0415

        def tri(a, b, c):
            vs = [bm.verts.new(V(*p)) for p in (a, b, c)]
            bm.faces.new(vs)

        def quad(a, b, c, d):
            vs = [bm.verts.new(V(*p)) for p in (a, b, c, d)]
            bm.faces.new(vs)

        top, bot = (0.0, 0.0, 0.045), (0.0, 0.0, -0.075)
        fr, bk = (0.075, 0.0, -0.005), (-0.075, 0.0, -0.005)
        for sy in (1, -1):
            side = (0.0, 0.024 * sy, -0.012)
            tri(fr, side, top)
            tri(side, bk, top)
            tri(fr, bot, side)
            tri(side, bot, bk)
        # 颈：两片窄三角，颈尖往前上；头往前下折
        nb_top, nb_bot = (0.060, 0.0, 0.010), (0.078, 0.0, -0.030)
        tip = (0.30, 0.0, neck_up)
        for sy in (1, -1):
            mid = (0.075, 0.006 * sy, -0.006)
            tri(nb_top, mid, tip)
            tri(mid, nb_bot, tip)
        head = (0.335, 0.0, neck_up - 0.035)
        for sy in (1, -1):
            tri(tip, (0.292, 0.005 * sy, neck_up - 0.010), head)
        # 尾
        tb_top, tb_bot = (-0.060, 0.0, 0.010), (-0.078, 0.0, -0.030)
        ttip = (-0.31, 0.0, tail_up)
        for sy in (1, -1):
            mid = (-0.075, 0.006 * sy, -0.006)
            tri(tb_top, mid, ttip)
            tri(mid, tb_bot, ttip)
        # 翅：根在背脊（top 前后），翅尖往外；中间一道折痕往下凹一点（两片面）
        for sy in (1, -1):
            r0, r1 = (0.072, 0.004 * sy, 0.028), (-0.072, 0.004 * sy, 0.028)
            wt = (-0.03 + wing_sweep, 0.33 * sy, wing_up + 0.045)
            crease = (-0.01 + wing_sweep * 0.5, 0.17 * sy, (wing_up + 0.045) * 0.5 + 0.02 - wing_bend)
            tri(r0, crease, wt) if sy > 0 else tri(r0, wt, crease)
            tri(r0, r1, crease) if sy > 0 else tri(r0, crease, r1)
            tri(r1, wt, crease) if sy > 0 else tri(r1, crease, wt)
        bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-6)
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)

    return build


def mat_crane_paper(name, color=(0.88, 0.86, 0.80), translucent=0.42, edge_dark=0.35, emit=None):
    """纸鹤的纸：白纸透光（背后有灯时翅膀透出暖光），折痕和边上略暗（AO），纸纤维细凹凸。emit=(颜色, 强度) 时纸本身微微发光。"""
    M = Mat(name)
    m = M.math
    oc = M.coord("Object")
    fib = M.noise(oc, scale=420.0, detail=6.0, rough=0.7)
    blot = M.noise(oc, scale=18.0, detail=3.0)
    ao = M.n("ShaderNodeAmbientOcclusion", Distance=0.03, _samples=8)
    cav = m("MULTIPLY", m("SUBTRACT", 1.0, ao.outputs["AO"], clamp=True), edge_dark)
    col = M.mix(m("MULTIPLY", M.maprange(blot.outputs["Fac"], 0.45, 0.75), 0.20), (*color, 1.0),
                (color[0] * 0.86, color[1] * 0.82, color[2] * 0.72, 1.0))
    col = M.mix(cav, col, (color[0] * 0.35, color[1] * 0.34, color[2] * 0.32, 1.0))
    nrm = M.bump(fib.outputs["Fac"], strength=0.10, distance=0.0005)
    bsdf = M.principled(Base_Color=col, Roughness=0.78, Normal=nrm, Specular_IOR_Level=0.25)
    if emit:
        bsdf.inputs["Emission Color"].default_value = (*emit[0], 1.0)
        bsdf.inputs["Emission Strength"].default_value = emit[1]
    trn = M.n("ShaderNodeBsdfTranslucent")
    M.l(M.mix(0.25, col, (1.0, 0.85, 0.65, 1.0)), trn.inputs["Color"])
    M.l(nrm, trn.inputs["Normal"])
    mx = M.n("ShaderNodeMixShader")
    mx.inputs[0].default_value = translucent
    M.l(bsdf.outputs[0], mx.inputs[1])
    M.l(trn.outputs[0], mx.inputs[2])
    return M.surface(mx.outputs[0])


def glow_orb(name, loc, radius, color, strength, light_w=None, index=4):
    """一团光（灯的光点）：发光小球 + 同位置的点光。"""
    ob = make_obj(name, K.ico_cloud([(0, 0, 0)], [radius], 3), mat_emit(f"{name}_M", color, strength), loc=loc, index=index)
    if light_w:
        K.point_light(f"{name}_L", loc, light_w, radius=radius * 1.5, color=color)
    return ob


# ====================================================================== 石印、地裂


def crack_texture(size, rng, n_main=9, center=(0.5, 0.5), reach=0.48, branch=0.035, width=2.2, ring=True):
    """地裂：从中心往外的几道主裂缝（随机折线，越走越细，一路分叉），外加一两圈环形裂纹。
    返回 (size, size) 的覆盖度 0..1（裂缝 = 1），中心那一块更碎。"""
    from PIL import Image, ImageDraw, ImageFilter  # noqa: PLC0415

    S4 = size * 2
    im = Image.new("L", (S4, S4), 0)
    dr = ImageDraw.Draw(im)
    cx, cy = center[0] * S4, center[1] * S4

    def walk(x, y, ang, length, wdt, depth):
        pts = [(x, y)]
        step = S4 * 0.012
        n = int(length / step)
        for i in range(n):
            ang += rng.normal(0, 0.28)
            x += step * math.cos(ang)
            y += step * math.sin(ang)
            pts.append((x, y))
            if depth < 3 and rng.random() < branch * (1.4 if depth == 0 else 1.0):
                walk(x, y, ang + rng.choice([-1, 1]) * rng.uniform(0.5, 1.1), length * rng.uniform(0.25, 0.5) * (1 - i / n),
                     wdt * 0.6, depth + 1)
        for i in range(len(pts) - 1):
            ww = max(1, int(round(wdt * (1 - i / len(pts)) ** 0.7 * 2)))
            dr.line((pts[i], pts[i + 1]), fill=255, width=ww)

    for j in range(n_main):
        a = 2 * math.pi * j / n_main + rng.normal(0, 0.25)
        walk(cx, cy, a, S4 * reach * rng.uniform(0.7, 1.1), width * 2, 0)
    if ring:
        for rr in (0.12, 0.24):
            pts = []
            a0 = rng.uniform(0, 6.28)
            for a in np.linspace(a0, a0 + rng.uniform(3.5, 5.5), 80):
                r = rr * S4 * (1 + 0.08 * rng.normal())
                pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
            for i in range(len(pts) - 1):
                if rng.random() < 0.85:
                    dr.line((pts[i], pts[i + 1]), fill=255, width=max(1, int(width)))
    im = im.filter(ImageFilter.GaussianBlur(0.8)).resize((size, size), Image.LANCZOS)
    return np.asarray(im, np.float64) / 255.0


def mat_ground_crack(name, crack_img, *, base=(0.05, 0.045, 0.04), glow=None, scale=1.0, uv_from_object=(2.0, 2.0), fade=None,
                     spec=None):
    """开裂的地面：干土（多层噪声的明暗、细凹凸），裂缝处凹下去、颜色压黑；glow=(颜色, 强度) 时裂缝深处透光。
    裂缝贴图按物体坐标 XY 平铺一次：u = x / 宽 + 0.5（uv_from_object 给出宽、高）。
    spec：镜面强度（贴地看时地面会反出一片天光，调小就压下去）。"""
    M = Mat(name)
    m = M.math
    oc = M.coord("Object")
    sep = M.n("ShaderNodeSeparateXYZ")
    M.l(oc, sep.inputs[0])
    cu = M.n("ShaderNodeCombineXYZ")
    M.l(m("ADD", m("DIVIDE", sep.outputs["X"], uv_from_object[0]), 0.5), cu.inputs["X"])
    M.l(m("ADD", m("DIVIDE", sep.outputs["Y"], uv_from_object[1]), 0.5), cu.inputs["Y"])
    t = M.n("ShaderNodeTexImage", _interpolation="Cubic", _extension="CLIP")
    t.image = crack_img
    M.l(cu.outputs[0], t.inputs["Vector"])
    sc = M.n("ShaderNodeSeparateColor")
    M.l(t.outputs["Color"], sc.inputs[0])
    crack = sc.outputs[0]
    n1 = M.noise(oc, scale=3.0 * scale, detail=8.0, rough=0.62)
    n2 = M.noise(oc, scale=40.0 * scale, detail=6.0, rough=0.7)
    v = m("ADD", m("MULTIPLY", M.maprange(n1.outputs["Fac"], 0.3, 0.7), 0.6), m("MULTIPLY", M.maprange(n2.outputs["Fac"], 0.3, 0.7), 0.4))
    col = M.mix(v, (base[0] * 0.55, base[1] * 0.55, base[2] * 0.55, 1.0), (base[0] * 1.5, base[1] * 1.45, base[2] * 1.4, 1.0))
    col = M.mix(m("POWER", crack, 0.6), col, (0.004, 0.004, 0.004, 1.0))
    h = m("SUBTRACT", m("ADD", m("MULTIPLY", n1.outputs["Fac"], 0.3), m("MULTIPLY", n2.outputs["Fac"], 0.25)), m("MULTIPLY", crack, 1.2))
    nrm = M.bump(h, strength=0.7, distance=0.02)
    bsdf = M.principled(Base_Color=col, Roughness=0.92, Normal=nrm)
    if spec is not None:
        bsdf.inputs["Specular IOR Level"].default_value = spec
    if glow:
        bsdf.inputs["Emission Color"].default_value = (*glow[0], 1.0)
        em = m("MULTIPLY", m("POWER", crack, 2.0), glow[1])
        if fade:  # 离中心越远越暗：exp(-(r / fade)²)
            rr = m("ADD", m("MULTIPLY", sep.outputs["X"], sep.outputs["X"]), m("MULTIPLY", sep.outputs["Y"], sep.outputs["Y"]))
            em = m("MULTIPLY", em, m("EXPONENT", m("DIVIDE", rr, -fade * fade)))
        M.l(em, bsdf.inputs["Emission Strength"])
    return M.surface(bsdf.outputs[0])


def seal_shan(size=1024, frame=True):
    """篆书“山”字印面（自己画：一道底横、三竖，中竖最高，笔画两头圆），外加一圈印框。白 = 凸起。"""
    from PIL import Image, ImageDraw, ImageFilter  # noqa: PLC0415

    im = Image.new("L", (size, size), 0)
    dr = ImageDraw.Draw(im)
    s = size / 1024
    sw = int(78 * s)
    base_y = int(735 * s)
    dr.rounded_rectangle((int(215 * s), base_y - sw // 2, int(809 * s), base_y + sw // 2), radius=sw // 2, fill=255)
    for x, top in ((260, 430), (512, 250), (764, 430)):
        dr.rounded_rectangle((int(x * s) - sw // 2, int(top * s), int(x * s) + sw // 2, base_y), radius=sw // 2, fill=255)
    if frame:
        dr.rectangle((int(70 * s), int(70 * s), int(954 * s), int(954 * s)), outline=255, width=int(56 * s))
    im = im.filter(ImageFilter.GaussianBlur(2 * s))
    a = np.asarray(im, np.float64) / 255.0
    rng = np.random.default_rng(3)
    wear = K.vfx().fft_blur(rng.standard_normal(a.shape), 6 * s)
    wear = wear / (wear.std() + 1e-9)
    return np.clip(a * (1 - 0.35 * (wear > 1.4)), 0, 1)


def glyph_array(text, size=512, font="brush", pad=0.10):
    """一个字的覆盖度（numpy，0..1），白字黑底，居中，四周留 pad。"""
    from PIL import Image, ImageDraw, ImageFont  # noqa: PLC0415

    f = ImageFont.truetype(str(K.FONT_BRUSH if font == "brush" else K.FONT_SERIF), int(size * (1 - 2 * pad)))
    im = Image.new("L", (size, size), 0)
    dr = ImageDraw.Draw(im)
    bb = dr.textbbox((0, 0), text, font=f)
    dr.text(((size - (bb[2] - bb[0])) / 2 - bb[0], (size - (bb[3] - bb[1])) / 2 - bb[1]), text, font=f, fill=255)
    return np.asarray(im, np.float64) / 255.0


def mat_seal_face(name, face_img, stone=(0.10, 0.12, 0.10), paste=(0.55, 0.05, 0.03)):
    """印面：阳文（字和边框凸起、沾着朱砂印泥），其余是石头。face_img：白 = 凸起。UV 取物体 UVMap（0..1 铺满印面）。"""
    M = Mat(name)
    m = M.math
    uv = M.coord("UV")
    t = M.n("ShaderNodeTexImage", _interpolation="Cubic", _extension="CLIP")
    t.image = face_img
    M.l(uv, t.inputs["Vector"])
    sc = M.n("ShaderNodeSeparateColor")
    M.l(t.outputs["Color"], sc.inputs[0])
    g = sc.outputs[0]
    oc = M.coord("Object")
    nz = M.noise(oc, scale=80.0, detail=6.0, rough=0.7)
    blot = M.noise(oc, scale=12.0, detail=3.0)
    pa = m("MULTIPLY", g, M.maprange(blot.outputs["Fac"], 0.3, 0.6, 0.65, 1.0))
    col = M.mix(pa, (*stone, 1.0), (*paste, 1.0))
    nrm = M.bump(m("ADD", g, m("MULTIPLY", nz.outputs["Fac"], 0.15)), strength=0.8, distance=0.02)
    bsdf = M.principled(Base_Color=col, Roughness=0.7, Normal=nrm)
    return M.surface(bsdf.outputs[0])


def seal_block(name, size=1.0, height=1.15, stone_m=None, face_m=None, knob="mountain", loc=(0, 0, 0), rot=(0, 0, 0), index=1,
               parent=None):
    """方石印（印面在 z=0、朝下，印身往上）：四棱微收、倒角；顶上印钮（knob="mountain"：三峰山形钮）。返回父物体。"""
    bpy = K._bpy()
    root = bpy.data.objects.new(name, None)
    K.link(root, parent)
    root.location, root.rotation_euler = loc, rot
    stone_m = stone_m or mat_stone(f"{name}_Stone", color=(0.10, 0.12, 0.10), scale=3.0)
    hs = size / 2

    def body(bm):
        import bmesh  # noqa: PLC0415

        bot = [bm.verts.new((sx * hs, sy * hs, 0.0)) for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
        top = [bm.verts.new((sx * hs * 0.94, sy * hs * 0.94, height)) for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
        for i in range(4):
            bm.faces.new((bot[i], bot[(i + 1) % 4], top[(i + 1) % 4], top[i]))
        bm.faces.new(list(reversed(bot)))
        bm.faces.new(top)
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)

    make_obj(f"{name}_Body", body, stone_m, smooth=False, parent=root, index=index, bevel=(0.035 * size, 3))
    for zb, hb in ((0.10 * height, 0.05 * height), (0.86 * height, 0.06 * height)):  # 印身上下两道凸起的箍
        k = 1.0 - 0.06 * (zb / height)
        make_obj(f"{name}_Band{zb:.2f}", K.box_build(size * k * 1.025, size * k * 1.025, hb), stone_m, smooth=False, parent=root,
                 loc=(0, 0, zb), index=index, bevel=(0.012 * size, 2))
    # 印面（单独一片，带 UV，贴在底面下面一点）
    if face_m is not None:
        def face(bm):
            uvl = bm.loops.layers.uv.new("UVMap")
            vs = [bm.verts.new((sx * hs * 0.97, sy * hs * 0.97, -0.004)) for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
            f = bm.faces.new(list(reversed(vs)))
            for lp in f.loops:
                lp[uvl].uv = (0.5 - lp.vert.co.x / (2 * hs * 0.97), 0.5 - lp.vert.co.y / (2 * hs * 0.97))  # 从前下方看是正字

        make_obj(f"{name}_Face", face, face_m, smooth=False, parent=root, index=index)
    if knob == "mountain":
        def peaks(bm):
            import bmesh  # noqa: PLC0415

            for px_, ph, pw in ((0.0, 0.95, 0.30), (-0.27, 0.62, 0.21), (0.27, 0.68, 0.21)):
                res = bmesh.ops.create_cone(bm, cap_ends=True, segments=6, radius1=pw * size, radius2=0.02 * size, depth=ph * size)
                bmesh.ops.translate(bm, vec=(px_ * size, 0.0, height + ph * size / 2), verts=res["verts"])
            res = bmesh.ops.create_cube(bm, size=1.0)
            bmesh.ops.scale(bm, vec=(size * 0.80, size * 0.36, size * 0.10), verts=res["verts"])
            bmesh.ops.translate(bm, vec=(0, 0, height + size * 0.05), verts=res["verts"])

        make_obj(f"{name}_Knob", peaks, stone_m, smooth=False, parent=root, index=index, bevel=(0.02 * size, 2))
    return root


def rock_mesh(name, mat, *, scale=(1.0, 1.0, 1.0), loc=(0, 0, 0), rot=(0, 0, 0), subdiv=5, crag=0.35, crag_size=0.6, fine=0.06,
              peak=0.0, seed=1, index=1, parent=None, flat_bottom=None, ridges=0, ridge_amp=0.18):
    """岩石：细分的二十面球，按 scale 拉伸；peak>0 时往上收成山峰（上半部按高度收窄）；两层置换（大块的岩面 + 细碎的凹凸）。
    flat_bottom=z 时把低于 z 的点压平（埋进地里的那一面）。"""
    bpy = K._bpy()

    def build(bm):
        import bmesh  # noqa: PLC0415

        bmesh.ops.create_icosphere(bm, subdivisions=subdiv, radius=1.0)
        rr = np.random.default_rng(seed)
        waves = [(int(rr.integers(2, 13)), rr.uniform(0, 6.28), rr.uniform(-1.2, 1.2), rr.uniform(0.3, 1.0)) for _ in range(ridges)]
        for v in bm.verts:
            x, y, z = v.co
            if waves:  # 竖向的山脊与沟（皴）：绕竖轴的角度上叠几道尖脊
                th = math.atan2(y, x)
                rsum = sum(a * (1 - abs(math.sin(kk * th + ph + tw * z))) ** 2 for kk, ph, tw, a in waves) / max(len(waves), 1)
                kk_ = 1 + ridge_amp * (rsum - 0.35) * (1 - 0.5 * max(z, 0))
                x, y = x * kk_, y * kk_
            if peak:
                t = (z + 1) / 2
                k = (1 - peak * t ** 1.4)
                x, y = x * k, y * k
                z = z + peak * 0.35 * t ** 3
            v.co = (x * scale[0], y * scale[1], z * scale[2])
            if flat_bottom is not None and v.co.z < flat_bottom:
                v.co.z = flat_bottom

    ob = make_obj(name, build, mat, loc=loc, rot=rot, index=index, parent=parent, smooth=True)
    for i, (ttype, size, strength) in enumerate((("VORONOI", crag_size, crag), ("CLOUDS", crag_size * 0.25, fine))):
        tex = bpy.data.textures.new(f"{name}_T{i}", ttype)
        if ttype == "VORONOI":
            tex.distance_metric = "DISTANCE"
            tex.noise_scale = size
            tex.weight_1, tex.weight_2 = 1.0, -0.5
        else:
            tex.noise_scale = size
            tex.noise_depth = 4
        md = ob.modifiers.new(f"Disp{i}", "DISPLACE")
        md.texture = tex
        md.strength = strength
        md.mid_level = 0.5
        md.texture_coords = "OBJECT" if False else "LOCAL"
    _ = seed
    return ob


# ====================================================================== 霜、寒波（霜铃、寒山钟、冻土、霜天剑雨共用）


def wave_ring_build(R, r, zc, n=260, k=16, wob=1.0):
    """霜环：扁一点的圆管，UV.x 绕环一圈 0..1，UV.y 绕管 0..1。"""
    def build(bm):
        uvl = bm.loops.layers.uv.new("UVMap")
        grid = []
        for i in range(n + 1):
            a = 2 * math.pi * i / n
            Rr_ = R * (1 + wob * (0.03 * math.sin(a * 5 + 1.0) + 0.018 * math.sin(a * 11)))
            zz = zc + wob * 0.025 * R * math.sin(a * 7)
            row = []
            for j in range(k + 1):
                b_ = 2 * math.pi * j / k
                rr = Rr_ + r * math.cos(b_) * 1.25
                row.append(bm.verts.new((rr * math.cos(a), rr * math.sin(a), zz + r * 0.7 * math.sin(b_))))
            grid.append(row)
        for i in range(n):
            for j in range(k):
                f = bm.faces.new((grid[i][j], grid[i + 1][j], grid[i + 1][j + 1], grid[i][j + 1]))
                for lp, uv in zip(f.loops, ((i / n, j / k), ((i + 1) / n, j / k), ((i + 1) / n, (j + 1) / k), (i / n, (j + 1) / k))):
                    lp[uvl].uv = uv
    return build


def skirt_build(r0, r1, z0, z1, n=200, m=40):
    """寒波的薄雾裙：从 r0 到 r1 的环带（UV.y = 0 内 → 1 外）。"""
    def build(bm):
        uvl = bm.loops.layers.uv.new("UVMap")
        grid = []
        for j in range(m + 1):
            t = j / m
            rr = r0 + (r1 - r0) * t
            zz = z0 + (z1 - z0) * (1 - (1 - t) ** 2.2)
            row = []
            for i in range(n + 1):
                a = 2 * math.pi * i / n
                w = 1 + 0.035 * math.sin(a * 5 + 1.0) * t + 0.02 * math.sin(a * 11) * t
                row.append(bm.verts.new((rr * w * math.cos(a), rr * w * math.sin(a), zz + 0.03 * r1 * math.sin(a * 7) * t)))
            grid.append(row)
        for j in range(m):
            for i in range(n):
                f = bm.faces.new((grid[j][i], grid[j][i + 1], grid[j + 1][i + 1], grid[j + 1][i]))
                for lp, uv in zip(f.loops, ((i / n, j / m), ((i + 1) / n, j / m), ((i + 1) / n, (j + 1) / m), (i / n, (j + 1) / m))):
                    lp[uvl].uv = uv
    return build


def crystal_build(L, r):
    """六棱冰晶（尖头）。"""
    return lathe_uv([(0.0, -0.02 * L), (r, 0.0), (r, L * 0.8), (0.0, L)], segments=6)


def mat_frosted_bronze(name, frost_img, height, base=(0.30, 0.19, 0.08), patina=(0.05, 0.13, 0.11), patina_amt=0.6, frost=1.0):
    """结霜的青铜：铜 + 青绿锈（凹处、斑块），冰花贴图按圆柱投影（u = 角度，v = z / height）盖在下半截，朝上的面积霜。"""
    M = Mat(name)
    m = M.math
    oc = M.coord("Object")
    sep = M.n("ShaderNodeSeparateXYZ")
    M.l(oc, sep.inputs[0])
    u = m("WRAP", m("DIVIDE", m("ARCTAN2", sep.outputs["Y"], sep.outputs["X"]), 2 * math.pi), 1.0, 0.0)
    v = m("DIVIDE", sep.outputs["Z"], height)
    uvv = M.n("ShaderNodeCombineXYZ")
    M.l(u, uvv.inputs["X"])
    M.l(v, uvv.inputs["Y"])
    t = M.n("ShaderNodeTexImage", _interpolation="Cubic", _extension="REPEAT")
    t.image = frost_img
    M.l(uvv.outputs[0], t.inputs["Vector"])
    scn = M.n("ShaderNodeSeparateColor")
    M.l(t.outputs["Color"], scn.inputs[0])
    fern = scn.outputs[0]
    n1 = M.noise(oc, scale=14.0, detail=6.0, rough=0.65)
    n2 = M.noise(oc, scale=60.0, detail=6.0, rough=0.7)
    ao = M.n("ShaderNodeAmbientOcclusion", Distance=0.01, _samples=8)
    cav = m("SUBTRACT", 1.0, ao.outputs["AO"], clamp=True)
    p = m("ADD", m("MULTIPLY", M.maprange(n1.outputs["Fac"], 0.42, 0.68), patina_amt), m("MULTIPLY", cav, 1.5 * patina_amt), clamp=True)
    bcol = M.mix(M.maprange(n2.outputs["Fac"], 0.3, 0.7), (base[0] * 0.7, base[1] * 0.7, base[2] * 0.7, 1.0), (*base, 1.0))
    col = M.mix(p, bcol, (*patina, 1.0))
    met = m("SUBTRACT", 1.0, p, clamp=True)
    rough = M.mixf(p, 0.32, 0.72)
    geo = M.n("ShaderNodeNewGeometry")
    nz = M.n("ShaderNodeSeparateXYZ")
    M.l(geo.outputs["Normal"], nz.inputs[0])
    top = m("MULTIPLY", M.maprange(nz.outputs["Z"], 0.5, 0.95), M.maprange(n2.outputs["Fac"], 0.40, 0.62))
    low = M.maprange(v, 0.60, 0.0)
    fr = m("MULTIPLY", m("ADD", m("MULTIPLY", fern, m("ADD", m("MULTIPLY", low, 0.95), 0.06)), m("MULTIPLY", top, 0.6)), frost, clamp=True)
    col = M.mix(fr, col, (*K.ICE, 1.0))
    met = m("MULTIPLY", met, m("SUBTRACT", 1.0, fr, clamp=True))
    rough = M.mixf(fr, rough, 0.40)
    nrm = M.bump(m("ADD", m("MULTIPLY", fern, 0.4), m("MULTIPLY", n2.outputs["Fac"], 0.3)), strength=0.4, distance=0.003)
    bsdf = M.n("ShaderNodeBsdfPrincipled")
    M.l(col, bsdf.inputs["Base Color"])
    M.l(met, bsdf.inputs["Metallic"])
    M.l(rough, bsdf.inputs["Roughness"])
    M.l(nrm, bsdf.inputs["Normal"])
    M.l(m("MULTIPLY", fr, 0.3), bsdf.inputs["Subsurface Weight"])
    bsdf.inputs["Subsurface Radius"].default_value = (0.02, 0.03, 0.05)
    bsdf.inputs["Subsurface Scale"].default_value = 0.01
    return M.surface(bsdf.outputs[0])


def frost_wave(name, center, R, *, z_scale=1.0, strength=1.0, index=5, seed=0.0, echo=True, skirt_r0=None):
    """寒波一组：亮的霜环 + 环后一圈淡霜雾 + 外面一道余波 + 环内拖着的薄雾裙。center 是钟（铃）口中心。"""
    bpy = K._bpy()
    root = bpy.data.objects.new(name, None)
    K.link(root)
    root.location = center
    root.scale = (1.0, 1.0, z_scale)
    make_obj(f"{name}_Ring", wave_ring_build(R, 0.025 * R, -0.015 * R), K.mat_wavefront(f"{name}_RingM", strength=3.2 * strength, seed=seed + 1.0,
                                                                                         soft=1.6, gaps=0.52), parent=root, index=index)
    make_obj(f"{name}_Haze", wave_ring_build(R * 0.96, 0.15 * R, 0.015 * R), K.mat_wavefront(f"{name}_HazeM", strength=0.32 * strength,
                                                                                           seed=seed + 4.0, soft=3.2, gaps=0.40), parent=root, index=index)
    if echo:
        make_obj(f"{name}_Echo", wave_ring_build(R * 1.34, 0.025 * R, -0.04 * R), K.mat_wavefront(f"{name}_EchoM", strength=2.4 * strength,
                                                                                                seed=seed + 7.0, gaps=0.58), parent=root, index=index)
    make_obj(f"{name}_Skirt", skirt_build(skirt_r0 if skirt_r0 else 0.5 * R, R * 0.985, -0.008 * R, -0.023 * R),
             K.mat_coldwave(f"{name}_SkirtM", strength=2.2 * strength, front=0.999, seed=seed + 1.0), parent=root, index=index)
    return root


# ====================================================================== 铜钱


def coin_build(r=0.022, t=0.0016, hole=0.0080, rim_w=0.0022, rim_h=0.0005, n=64):
    """方孔圆钱（钱面在 XY 平面，厚度沿 Z）：外圈、方孔四周各有一道凸起的郭；UV 按钱面平铺（u, v = x/2r+0.5, y/2r+0.5）。"""
    def build(bm):
        import bmesh  # noqa: PLC0415

        uvl = bm.loops.layers.uv.new("UVMap")
        rings_r = [0.0, 0.25, 0.55, 0.85, 1.0]

        def inner_r(th):
            return hole / max(abs(math.cos(th)), abs(math.sin(th)))

        def zf(f, rr):
            """钱面高度：外郭、内郭凸起。f = 0（孔边）→ 1（外缘）。"""
            z = 0.0
            if rr > r - rim_w:
                z = rim_h
            if f < 0.18:
                z = rim_h
            return z

        tops, bots = [], []
        for j, f in enumerate(rings_r + [1.0001]):
            rowt, rowb = [], []
            for i in range(n):
                th = 2 * math.pi * i / n + math.pi / n
                ri = inner_r(th)
                rr = ri + (r - ri) * min(f, 1.0)
                z = zf(f, rr)
                x, y = rr * math.cos(th), rr * math.sin(th)
                rowt.append(bm.verts.new((x, y, t / 2 + z)))
                rowb.append(bm.verts.new((x, y, -t / 2 - z)))
            tops.append(rowt)
            bots.append(rowb)

        def uvf(v):
            return (v.co.x / (2 * r) + 0.5, v.co.y / (2 * r) + 0.5)

        for rows, flip in ((tops, False), (bots, True)):
            for j in range(len(rows) - 1):
                for i in range(n):
                    q = (rows[j][i], rows[j + 1][i], rows[j + 1][(i + 1) % n], rows[j][(i + 1) % n])
                    f_ = bm.faces.new(tuple(reversed(q)) if flip else q)
                    for lp in f_.loops:
                        lp[uvl].uv = uvf(lp.vert)
        for i in range(n):  # 外缘、孔壁
            for a, b in ((tops[-1], bots[-1]), (bots[0], tops[0])):
                f_ = bm.faces.new((a[i], a[(i + 1) % n], b[(i + 1) % n], b[i]))
                for lp in f_.loops:
                    lp[uvl].uv = uvf(lp.vert)
        bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-7)
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)

    return build


def coin_face_texture(chars="开元通宝", size=512):
    """钱文：方孔上下右左四个字（凸起 = 白）。"""
    from PIL import Image, ImageDraw, ImageFilter, ImageFont  # noqa: PLC0415

    im = Image.new("L", (size, size), 0)
    dr = ImageDraw.Draw(im)
    f = ImageFont.truetype(str(K.FONT_SERIF), int(size * 0.20))
    c = size / 2
    for ch, (dx, dy) in zip(chars, ((0, -0.29), (0, 0.29), (0.29, 0), (-0.29, 0))):
        bb = dr.textbbox((0, 0), ch, font=f)
        dr.text((c + dx * size - (bb[2] - bb[0]) / 2 - bb[0], c + dy * size - (bb[3] - bb[1]) / 2 - bb[1]), ch, font=f, fill=255)
    im = im.filter(ImageFilter.GaussianBlur(1.2))
    return np.asarray(im, np.float64) / 255.0


def mat_coin(name, face_img=None, base=(0.42, 0.26, 0.10), patina=(0.06, 0.14, 0.11), patina_amt=0.45, rough=0.32, gilt=0.0,
             emit=None):
    """铜钱：铜色 + 凹处青锈，钱文凸起（贴图做凹凸、凸处磨亮）。"""
    M = Mat(name)
    m = M.math
    oc = M.coord("Object")
    n1 = M.noise(oc, scale=180.0, detail=6.0, rough=0.65)
    n2 = M.noise(oc, scale=900.0, detail=4.0, rough=0.7)
    ao = M.n("ShaderNodeAmbientOcclusion", Distance=0.002, _samples=8)
    cav = m("SUBTRACT", 1.0, ao.outputs["AO"], clamp=True)
    p = m("ADD", m("MULTIPLY", M.maprange(n1.outputs["Fac"], 0.45, 0.72), patina_amt), m("MULTIPLY", cav, 2.0 * patina_amt), clamp=True)
    if gilt:
        base = tuple(b * (1 - gilt) + g * gilt for b, g in zip(base, (0.95, 0.66, 0.26)))
    h = n2.outputs["Fac"]
    if face_img is not None:
        uv = M.coord("UV")
        t = M.n("ShaderNodeTexImage", _interpolation="Cubic", _extension="CLIP")
        t.image = face_img
        M.l(uv, t.inputs["Vector"])
        sc = M.n("ShaderNodeSeparateColor")
        M.l(t.outputs["Color"], sc.inputs[0])
        g = sc.outputs[0]
        h = m("ADD", m("MULTIPLY", g, 1.0), m("MULTIPLY", n2.outputs["Fac"], 0.2))
        p = m("MULTIPLY", p, m("SUBTRACT", 1.0, m("MULTIPLY", g, 0.8)), clamp=True)
    col = M.mix(p, (*base, 1.0), (*patina, 1.0))
    met = m("SUBTRACT", 1.0, p, clamp=True)
    rr = M.mixf(p, rough, 0.75)
    nrm = M.bump(h, strength=0.5, distance=0.0006)
    bsdf = M.n("ShaderNodeBsdfPrincipled")
    M.l(col, bsdf.inputs["Base Color"])
    M.l(met, bsdf.inputs["Metallic"])
    M.l(rr, bsdf.inputs["Roughness"])
    M.l(nrm, bsdf.inputs["Normal"])
    if emit:
        bsdf.inputs["Emission Color"].default_value = (*emit[0], 1.0)
        bsdf.inputs["Emission Strength"].default_value = emit[1]
    return M.surface(bsdf.outputs[0])


DIPPER = [(0.00, 0.00), (0.02, 0.62), (0.70, 0.78), (1.00, 0.30), (1.62, 0.18), (2.15, 0.36), (2.62, 0.05)]
"""北斗七星的相对位置（天枢、天璇、天玑、天权、玉衡、开阳、摇光；x 沿斗柄方向，单位任意）。"""


# ====================================================================== 屋顶、孔明灯


def roof_build(w=1.6, d=1.0, h=0.42, curl=0.10, nx=48, ny=20, wall_h=0.5):
    """两坡瓦顶（屋脊沿 X）：坡面往下凹（越靠檐越平），檐口两端翘起；下面一圈矮墙（暗）。UV：u 沿 X（0..1），v 沿坡（0 脊 → 1 檐）。"""
    def build(bm):
        import bmesh  # noqa: PLC0415

        uvl = bm.loops.layers.uv.new("UVMap")
        for side in (1, -1):
            grid = []
            for j in range(ny + 1):
                v = j / ny
                y = side * v * d / 2 * 1.12
                row = []
                for i in range(nx + 1):
                    u = i / nx
                    x = (u - 0.5) * w * 1.08
                    z = h * (1 - v) ** 1.35 + curl * (abs(2 * u - 1) ** 5) * v ** 2
                    row.append(bm.verts.new((x, y, z + wall_h)))
                grid.append(row)
            for j in range(ny):
                for i in range(nx):
                    q = (grid[j][i], grid[j][i + 1], grid[j + 1][i + 1], grid[j + 1][i])
                    f = bm.faces.new(q if side > 0 else tuple(reversed(q)))
                    for lp in f.loops:
                        co = lp.vert.co
                        lp[uvl].uv = (co.x / (w * 1.08) + 0.5, abs(co.y) / (d / 2 * 1.12))
        # 墙：一个盒子（比屋顶小一圈）
        res = bmesh.ops.create_cube(bm, size=1.0)
        bmesh.ops.scale(bm, vec=(w * 0.9, d * 0.82, wall_h), verts=res["verts"])
        bmesh.ops.translate(bm, vec=(0, 0, wall_h / 2), verts=res["verts"])
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)

    return build


def mat_roof_tiles(name, color=(0.045, 0.045, 0.05), rows=46.0, snow=0.0, moss=0.0):
    """瓦顶：沿 u 方向一垄一垄（Wave 条纹做凹凸和明暗），沿坡细细的瓦缝；暗灰。"""
    M = Mat(name)
    m = M.math
    uv = M.coord("UV")
    sep = M.n("ShaderNodeSeparateXYZ")
    M.l(uv, sep.inputs[0])
    ridge = m("ABSOLUTE", m("SINE", m("MULTIPLY", sep.outputs["X"], math.pi * rows)))
    seams = m("POWER", m("ABSOLUTE", m("SINE", m("MULTIPLY", sep.outputs["Y"], math.pi * 14.0))), 30.0)
    oc = M.coord("Object")
    nz = M.noise(oc, scale=18.0, detail=5.0)
    col = M.mix(m("MULTIPLY", ridge, 0.6), (color[0] * 0.5, color[1] * 0.5, color[2] * 0.5, 1.0), (*color, 1.0))
    col = M.mix(m("MULTIPLY", seams, 0.6), col, (0.01, 0.01, 0.012, 1.0))
    if moss:
        col = M.mix(m("MULTIPLY", M.maprange(nz.outputs["Fac"], 0.5, 0.7), moss), col, (0.03, 0.05, 0.03, 1.0))
    if snow:
        col = M.mix(m("MULTIPLY", m("MULTIPLY", ridge, M.maprange(nz.outputs["Fac"], 0.4, 0.6)), snow), col, (0.70, 0.76, 0.85, 1.0))
    nrm = M.bump(m("SUBTRACT", ridge, m("MULTIPLY", seams, 0.5)), strength=0.8, distance=0.02)
    bsdf = M.principled(Base_Color=col, Roughness=0.62, Normal=nrm)
    return M.surface(bsdf.outputs[0])


def superellipse(th, n=4.0):
    c, s = abs(math.cos(th)), abs(math.sin(th))
    return 1.0 / ((c ** n + s ** n) ** (1.0 / n))


def sky_lantern(name, *, H=0.90, top=0.29, bottom=0.21, paper_m=None, bamboo_m=None, fire=True, fire_strength=1.0, loc=(0, 0, 0),
                rot=(0, 0, 0), index=1, parent=None, light_w=30.0, glyph_img=None):
    """孔明灯（底口在 z=0，往上 H）：方圆的纸袋（上宽下窄、顶上略鼓），四角四根竹篾，底口一道竹圈、两根十字铁丝托着燃料块，
    燃料块上一团火（和一盏点光，把纸从里面照亮）。返回父物体。"""
    bpy = K._bpy()
    root = bpy.data.objects.new(name, None)
    K.link(root, parent)
    root.location, root.rotation_euler = loc, rot
    paper_m = paper_m or mat_sky_paper(f"{name}_Paper", glyph_img)
    bamboo_m = bamboo_m or K.mat_bamboo_dark(f"{name}_Bamboo")

    def r_of(z):
        t = z / H
        return bottom + (top - bottom) * (1 - (1 - t) ** 1.6)

    prof = [(r_of(z), z) for z in np.linspace(0.0, H * 0.96, 40)]
    for a in np.linspace(0, 1, 8)[1:]:
        prof.append((r_of(H * 0.96) * math.cos(a * math.pi / 2) ** 0.8, H * 0.96 + 0.05 * math.sin(a * math.pi / 2)))
    prof[-1] = (0.0, H * 0.96 + 0.05)
    make_obj(f"{name}_Bag", lathe_uv(prof, segments=96, radial=lambda th, z, i: superellipse(th, 4.0) *
                                     (1 + 0.006 * math.sin(th * 21 + z * 30))), paper_m, parent=root, index=index)
    for q in range(4):  # 四角竹篾
        th = math.pi / 4 + q * math.pi / 2
        k_ = superellipse(th, 4.0)
        pts = [(r_of(z) * k_ * 0.995 * math.cos(th), r_of(z) * k_ * 0.995 * math.sin(th), z) for z in np.linspace(0.0, H * 0.95, 30)]
        make_obj(f"{name}_Rib{q}", K.tube_uv(pts, 0.004, sides=6), bamboo_m, parent=root, index=index)
    hoop = [(r_of(0.0) * superellipse(th, 4.0) * math.cos(th), r_of(0.0) * superellipse(th, 4.0) * math.sin(th), 0.0)
            for th in np.linspace(0, 2 * math.pi, 120)]
    make_obj(f"{name}_Hoop", K.tube_uv(hoop, 0.006, sides=8), bamboo_m, parent=root, index=index)
    wire = K.mat_iron(f"{name}_Wire")
    for th in (math.pi / 4, 3 * math.pi / 4):
        rr = r_of(0.0) * superellipse(th, 4.0)
        make_obj(f"{name}_Wire{th:.1f}", K.tube_uv([(-rr * math.cos(th), -rr * math.sin(th), 0.0), (0, 0, 0.0),
                                                    (rr * math.cos(th), rr * math.sin(th), 0.0)], 0.0015, sides=6), wire, parent=root,
                 index=index)
    make_obj(f"{name}_Fuel", K.box_build(0.05, 0.05, 0.02), mat_stone(f"{name}_FuelM", color=(0.08, 0.06, 0.04), scale=40.0),
             parent=root, loc=(0, 0, 0.0), index=index)
    if fire:
        fl = make_obj(f"{name}_Flame", lathe_uv([(0.0, 0.0), (0.020, 0.010), (0.028, 0.030), (0.022, 0.060), (0.010, 0.095), (0.0, 0.13)],
                                                segments=24), K.mat_core_flame(f"{name}_FlameM"), parent=root, loc=(0, 0, 0.01),
                      index=index + 3)
        fl.scale = (fire_strength, fire_strength, fire_strength)
        L = bpy.data.lights.new(f"{name}_Light", "POINT")
        L.energy, L.color, L.shadow_soft_size = light_w, (1.0, 0.55, 0.22), 0.03
        lo = K.link(bpy.data.objects.new(f"{name}_Light", L), root)
        lo.location = (0, 0, 0.08)
    return root


def mat_sky_paper(name, glyph_img=None, color=(1.0, 0.78, 0.45)):
    """孔明灯的纸：薄纸透光（Translucent 为主），里面的火光透出来，越靠下（离火近）越亮越暖；纸纤维；可写一个红字。"""
    M = Mat(name)
    m = M.math
    oc = M.coord("Object")
    sep = M.n("ShaderNodeSeparateXYZ")
    M.l(oc, sep.inputs[0])
    fib = M.noise(oc, scale=180.0, detail=8.0, rough=0.7)
    blot = M.noise(oc, scale=12.0, detail=3.0)
    tcol = M.mix(M.maprange(sep.outputs["Z"], 0.0, 0.9), (*color, 1.0), (color[0] * 0.9, color[1] * 0.62, color[2] * 0.40, 1.0))
    tcol = M.mix(m("MULTIPLY", M.maprange(blot.outputs["Fac"], 0.4, 0.7), 0.3), tcol, (color[0] * 0.75, color[1] * 0.55, color[2] * 0.3, 1.0))
    ink = None
    if glyph_img is not None:
        cu = M.n("ShaderNodeCombineXYZ")
        M.l(m("ADD", m("DIVIDE", sep.outputs["X"], 0.40), 0.5), cu.inputs["X"])
        M.l(m("DIVIDE", m("SUBTRACT", sep.outputs["Z"], 0.25), 0.40), cu.inputs["Y"])
        t = M.n("ShaderNodeTexImage", _interpolation="Cubic", _extension="CLIP")
        t.image = glyph_img
        M.l(cu.outputs[0], t.inputs["Vector"])
        ink = m("MULTIPLY", t.outputs["Alpha"], m("LESS_THAN", sep.outputs["Y"], 0.0))
        tcol = M.mix(ink, tcol, (0.35, 0.02, 0.01, 1.0))
    nrm = M.bump(fib.outputs["Fac"], strength=0.10, distance=0.002)
    trn = M.n("ShaderNodeBsdfTranslucent")
    M.l(tcol, trn.inputs["Color"])
    M.l(nrm, trn.inputs["Normal"])
    dif = M.n("ShaderNodeBsdfDiffuse")
    M.l(tcol, dif.inputs["Color"])
    mx = M.n("ShaderNodeMixShader")
    mx.inputs[0].default_value = 0.75
    M.l(dif.outputs[0], mx.inputs[1])
    M.l(trn.outputs[0], mx.inputs[2])
    return M.surface(mx.outputs[0])


# ====================================================================== 水、浪、小妖


def mat_water(name, color=(0.03, 0.20, 0.22), rough=0.05, transmission=0.92, foam_img=None, emit=0.0):
    """水：Principled 透射（IOR 1.33），底色深青；可加泡沫（白，挡住透射）、一点自发光让浪身在夜里透出青光。"""
    M = Mat(name)
    m = M.math
    oc = M.coord("Object")
    nz = M.noise(oc, scale=14.0, detail=6.0, rough=0.6)
    nrm = M.bump(nz.outputs["Fac"], strength=0.12, distance=0.01)
    bsdf = M.principled(Base_Color=(*color, 1.0), Roughness=rough, IOR=1.33, Transmission_Weight=transmission, Normal=nrm)
    if emit:
        bsdf.inputs["Emission Color"].default_value = (color[0] * 1.6, color[1] * 1.8, color[2] * 1.8, 1.0)
        bsdf.inputs["Emission Strength"].default_value = emit
    shader = bsdf.outputs[0]
    if foam_img is not None:
        uv = M.coord("UV")
        t = M.n("ShaderNodeTexImage", _interpolation="Cubic", _extension="REPEAT")
        t.image = foam_img
        M.l(uv, t.inputs["Vector"])
        sc = M.n("ShaderNodeSeparateColor")
        M.l(t.outputs["Color"], sc.inputs[0])
        foam = sc.outputs[0]
        fb = M.principled(Base_Color=(0.80, 0.88, 0.92, 1.0), Roughness=0.7, Subsurface_Weight=0.3, Subsurface_Radius=(0.02, 0.03, 0.04),
                          Subsurface_Scale=0.02)
        mx = M.n("ShaderNodeMixShader")
        M.l(foam, mx.inputs[0])
        M.l(shader, mx.inputs[1])
        M.l(fb.outputs[0], mx.inputs[2])
        shader = mx.outputs[0]
    _ = m
    return M.surface(shader)


def mat_foam(name, color=(0.82, 0.90, 0.95), emit=0.0):
    M = Mat(name)
    bsdf = M.principled(Base_Color=(*color, 1.0), Roughness=0.6, Subsurface_Weight=0.5, Subsurface_Radius=(0.02, 0.03, 0.04),
                        Subsurface_Scale=0.02)
    if emit:
        bsdf.inputs["Emission Color"].default_value = (*color, 1.0)
        bsdf.inputs["Emission Strength"].default_value = emit
    return M.surface(bsdf.outputs[0])


def imp(name, *, size=0.08, body_m=None, eye_m=None, loc=(0, 0, 0), rot=(0, 0, 0), index=2, rng=None, horns=True, parent=None):
    """小妖：一团暗色的身子（压扁的球）+ 两只尖角 + 两点发光的眼 + 几根爪。返回父物体。"""
    bpy = K._bpy()
    rng = rng or np.random.default_rng(3)
    root = bpy.data.objects.new(name, None)
    K.link(root, parent)
    root.location, root.rotation_euler = loc, rot
    body_m = body_m or mat_stone(f"{name}_Body", color=(0.03, 0.025, 0.03), rough=0.6, scale=30.0, cavity=0.3, bump=0.3)
    eye_m = eye_m or mat_emit(f"{name}_Eye", (1.0, 0.75, 0.25), 12.0)
    s = size
    body = make_obj(f"{name}_B", K.ico_cloud([(0, 0, 0)], [s], 3), body_m, parent=root, index=index)
    body.scale = (1.0, 0.85, 1.15)
    for sx in (-1, 1):
        make_obj(f"{name}_E{sx}", K.ico_cloud([(0, 0, 0)], [s * 0.13], 2), eye_m, parent=root, loc=(sx * s * 0.35, -s * 0.82, s * 0.25),
                 index=index)
        if horns:
            make_obj(f"{name}_H{sx}", K.lathe_uv([(0.0, 0.0), (s * 0.18, 0.0), (0.0, s * 0.7)], segments=10), body_m, parent=root,
                     loc=(sx * s * 0.45, 0.0, s * 0.95), rot=(0, sx * 0.5, 0), index=index)
    for j in range(4):
        a = rng.uniform(0, 2 * math.pi)
        p0 = (s * 0.8 * math.cos(a), s * 0.6 * math.sin(a), -s * 0.4)
        p1 = (s * 1.4 * math.cos(a + 0.3), s * 1.1 * math.sin(a + 0.3), -s * 0.9 + rng.uniform(-0.3, 0.3) * s)
        make_obj(f"{name}_C{j}", K.tube_uv([p0, p1], s * 0.08, sides=6, radius_fn=lambda t: 1 - 0.85 * t), body_m, parent=root,
                 index=index)
    return root


# ====================================================================== 手（剑意、折纸、聚魂）

# 四指：掌指关节的位置 (x, z)，三节长度，三节半径（右手，米）
FINGERS = {
    "index": ((0.031, 0.094), (0.043, 0.025, 0.021), (0.0094, 0.0083, 0.0074)),
    "middle": ((0.010, 0.098), (0.047, 0.029, 0.022), (0.0097, 0.0086, 0.0076)),
    "ring": ((-0.010, 0.095), (0.044, 0.027, 0.021), (0.0091, 0.0081, 0.0072)),
    "pinky": ((-0.028, 0.087), (0.035, 0.021, 0.019), (0.0079, 0.0071, 0.0064)),
}
HAND_OPEN = {"index": (-6, 8, 6, 4), "middle": (0, 8, 6, 4), "ring": (6, 9, 7, 4), "pinky": (13, 10, 8, 5), "thumb": (40, 30, 10, 8)}
HAND_FIST = {"index": (0, 88, 95, 55), "middle": (0, 90, 98, 55), "ring": (0, 92, 98, 55), "pinky": (0, 94, 95, 55),
             "thumb": (10, 55, 25, 30)}
MB_K = 1.0 / 0.574  # metaball：刚度 2、阈值 0.6 时，表面半径 ≈ 0.574 × 元素半径


def hand_points(pose, *, mirror=False):
    """手的骨架：返回 [(起点, 终点, 半径)]（右手；mirror=True 给左手，x 取反）。
    约定：腕在原点，四指朝 +Z，掌心朝 -Y，拇指在 +X 一侧。pose = {手指: (张开°, 根节°, 中节°, 末节°)}，
    张开往小指一侧为正；屈曲往掌心（-Y）弯。拇指：(外展°, 屈向掌心°, 根节°, 末节°)。"""
    from mathutils import Matrix, Vector  # noqa: PLC0415

    segs = []
    for f, ((x0, z0), lens, rads) in FINGERS.items():
        spread, *curls = pose.get(f, HAND_OPEN[f])
        d = Matrix.Rotation(math.radians(-spread), 3, "Y") @ Vector((0, 0, 1))
        axis = d.cross(Vector((0, -1, 0))).normalized()
        p = Vector((x0, -0.002, z0))
        ang = 0.0
        for L, r, c in zip(lens, rads, curls):
            ang += math.radians(c)
            dd = Matrix.Rotation(ang, 3, axis) @ d
            q = p + dd * L
            segs.append((p.copy(), q.copy(), r))
            p = q
        # 掌骨：从腕附近到指根
        segs.append((Vector((x0 * 0.55, -0.001, 0.018)), Vector((x0, -0.002, z0 - 0.004)), rads[0] * 1.05))
    # 拇指：从大鱼际往外、往前伸出，三节（掌骨 + 两节）
    abd, flex, c1, c2 = pose.get("thumb", HAND_OPEN["thumb"])
    d = Vector((math.sin(math.radians(abd)), 0.0, math.cos(math.radians(abd))))
    d = (Matrix.Rotation(math.radians(flex), 3, "Z") @ d).normalized()
    d = (d + Vector((0, -0.35, 0)) * math.sin(math.radians(flex))).normalized()
    p = Vector((0.026, -0.010, 0.020))
    axis = d.cross(Vector((-0.6, -0.8, 0.0))).normalized()
    ang = 0.0
    for L, r, c in zip((0.040, 0.033, 0.027), (0.0125, 0.0108, 0.0096), (0.0, c1, c2)):
        ang += math.radians(c)
        dd = Matrix.Rotation(ang, 3, axis) @ d
        q = p + dd * L
        segs.append((p.copy(), q.copy(), r))
        p = q
    # 掌、腕：几颗球和两根扁的腕（两根并排的胶囊）
    for c, r in (((0.004, -0.001, 0.052), 0.020), ((0.018, -0.006, 0.034), 0.015), ((-0.015, -0.004, 0.042), 0.012),
                 ((0.004, 0.002, 0.070), 0.017)):
        segs.append((Vector(c), Vector(c), r))
    for x in (-0.011, 0.011):
        segs.append((Vector((x, 0.0, -0.07)), Vector((x * 0.9, 0.0, 0.012)), 0.0155))
    if mirror:
        segs = [(Vector((-a.x, a.y, a.z)), Vector((-b.x, b.y, b.z)), r) for a, b, r in segs]
    return segs


def hand(name, mat, pose=None, *, mirror=False, loc=(0, 0, 0), rot=(0, 0, 0), scale=1.0, index=1, parent=None, res=0.0016):
    """一只手（metaball 融成一体，转成网格，平滑着色）。pose 见 hand_points。返回网格物体。"""
    bpy = K._bpy()
    from mathutils import Vector  # noqa: PLC0415

    mb = bpy.data.metaballs.new(f"{name}_MB")
    mb.resolution = mb.render_resolution = res
    mb.threshold = 0.6
    for a, b, r in hand_points(pose or HAND_OPEN, mirror=mirror):
        el = mb.elements.new(type="CAPSULE" if (b - a).length > 1e-6 else "BALL")
        el.co = (a + b) / 2
        el.radius = r * MB_K
        el.stiffness = 2.0
        if (b - a).length > 1e-6:
            el.size_x = (b - a).length / 2
            el.rotation = (b - a).normalized().to_track_quat("X", "Z")
    tmp = bpy.data.objects.new(f"{name}_tmp", mb)
    bpy.context.scene.collection.objects.link(tmp)
    dg = bpy.context.evaluated_depsgraph_get()
    me = bpy.data.meshes.new_from_object(tmp.evaluated_get(dg))
    bpy.data.objects.remove(tmp)
    bpy.data.metaballs.remove(mb)
    me.name = name
    me.shade_smooth()
    me.materials.append(mat)
    ob = K.link(bpy.data.objects.new(name, me), parent)
    ob.location, ob.rotation_euler, ob.scale = loc, rot, (scale, scale, scale)
    ob.pass_index = index
    md = ob.modifiers.new("Smooth", "CORRECTIVE_SMOOTH")
    md.iterations = 4
    _ = Vector
    return ob


def mat_skin(name, color=(0.62, 0.43, 0.33), rough=0.48, sss=0.35):
    """皮肤：次表面散射（红色走得远），细的毛孔凹凸，指节、掌纹处略暗（AO）。"""
    M = Mat(name)
    m = M.math
    oc = M.coord("Object")
    pores = M.noise(oc, scale=900.0, detail=4.0, rough=0.6)
    blot = M.noise(oc, scale=45.0, detail=3.0)
    ao = M.n("ShaderNodeAmbientOcclusion", Distance=0.006, _samples=8)
    cav = m("SUBTRACT", 1.0, ao.outputs["AO"], clamp=True)
    col = M.mix(M.maprange(blot.outputs["Fac"], 0.35, 0.65), (color[0] * 0.92, color[1] * 0.86, color[2] * 0.86, 1.0),
                (color[0] * 1.04, color[1] * 1.0, color[2] * 0.98, 1.0))
    col = M.mix(m("MULTIPLY", cav, 0.8, clamp=True), col, (color[0] * 0.55, color[1] * 0.32, color[2] * 0.28, 1.0))
    nrm = M.bump(pores.outputs["Fac"], strength=0.10, distance=0.0002)
    bsdf = M.principled(Base_Color=col, Roughness=M.maprange(pores.outputs["Fac"], 0.3, 0.7, rough - 0.06, rough + 0.06),
                        Subsurface_Weight=sss, Subsurface_Radius=(0.010, 0.0040, 0.0025), Subsurface_Scale=0.6, Normal=nrm,
                        Specular_IOR_Level=0.45)
    return M.surface(bsdf.outputs[0])
