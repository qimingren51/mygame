"""妖物重做（精修三维）的公共件：绘画感的材质、粗细有变化的墨线、贴在表面上的笔画条、渲染后期。

和 bstyle.toon_material 的三档硬阶不同：
  - 明暗 d = N·L + 晕染噪声 + 逐点的形体项（顶点属性 shade，例如层与层之间的凹缝）+ 顺着形体的笔毛丝（属性 su/sv 做坐标）
    → 多档颜色（每档带色相偏移：暗部偏暖或偏青、亮部偏冷），档与档之间窄窄地过渡，像一笔一笔罩上去的；
  - 轮廓光：背光一侧的边（Facing^p × 朝向轮廓光方向）混一层冷光，夜里托住剪影；
  - 发光：眼、裂缝用 bstyle.emissive_material（进物体编号通道）；缝里透出的微光走 AOV 通道 glow（不改白天的颜色）。
墨线：Freestyle 外轮廓 + 形线 + 细线三档，加“离光源越远越粗”（DISTANCE_FROM_OBJECT 修饰器，光源方向放一个空物体），
  背光一侧的线重、受光一侧的线轻，像提按；后期再把线条按笔毛纹打散一点（飞白）。
后期不吸附调色板（多档渐变本来就要更多颜色），只做缩小、叠墨线、墨晕、纸纹（finish）。
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import bpy
import bmesh
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree

ART = Path(__file__).resolve().parents[1]
for p in (ART, ART / "post", ART / "models"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
from style import bstyle as B  # noqa: E402
from style import style as S  # noqa: E402
import postprocess as PP  # noqa: E402

GLOW_AOV = "glow"
RIM_DIR = Vector((-0.75, 0.55, 0.45)).normalized()  # 轮廓光：从左后上方来（和主光错开，照亮背光一侧的边）


def lin(h):
    return B.hex_lin(h)


# ================================================================ 材质
def paint_material(name, stops, *, wash=0.22, wash_scale=2.2, seed=0.0, shade_attr=None, shade_gain=1.0,
                   streak=0.0, streak_scale=(3.0, 40.0), rim_hex=None, rim=0.0, rim_power=2.5, value_var=0.05,
                   glow_attr=None, glow_gain=1.0, edge=0.25, edge_power=3.0, bias=0.0, fade_z=None):
    """绘画感的自发光材质。stops = [(位置, hex), ...]，按 d（约 -1..1 映射到 0..1）取色，线性插值、档与档之间靠得近。
    shade_attr：顶点属性，直接加到 d 上（形体的凹凸、毛色分区）；streak：顺着 (su, sv) 属性方向的笔毛丝幅度；
    rim_hex/rim：轮廓光颜色和强度；glow_attr：写进 AOV glow 的属性（缝里的魂光）。"""
    m, nt = B._new_node_material(name)
    N, Lk = nt.nodes, nt.links
    m["paint_stops"] = [h for _, h in stops]
    geo = N.new("ShaderNodeNewGeometry")
    dot = N.new("ShaderNodeVectorMath"); dot.operation = "DOT_PRODUCT"
    dot.inputs[1].default_value = Vector(S.KEY_LIGHT_DIR).normalized()
    Lk.new(geo.outputs["Normal"], dot.inputs[0])
    tc = N.new("ShaderNodeTexCoord")
    nz = N.new("ShaderNodeTexNoise"); nz.noise_dimensions = "4D"
    nz.inputs["Scale"].default_value = wash_scale
    nz.inputs["Detail"].default_value = 3.0
    nz.inputs["Roughness"].default_value = 0.55
    nz.inputs["W"].default_value = seed
    Lk.new(tc.outputs["Object"], nz.inputs["Vector"])
    wn = N.new("ShaderNodeMath"); wn.operation = "MULTIPLY_ADD"
    wn.inputs[1].default_value = wash; wn.inputs[2].default_value = -0.5 * wash + bias
    Lk.new(nz.outputs["Fac"], wn.inputs[0])
    acc = N.new("ShaderNodeMath"); acc.operation = "ADD"
    Lk.new(dot.outputs["Value"], acc.inputs[0]); Lk.new(wn.outputs["Value"], acc.inputs[1])
    cur = acc.outputs["Value"]

    def add(sock_b, k=1.0):
        nonlocal cur
        if k != 1.0:
            mk = N.new("ShaderNodeMath"); mk.operation = "MULTIPLY"; mk.inputs[1].default_value = k
            Lk.new(sock_b, mk.inputs[0]); sock_b = mk.outputs["Value"]
        ad = N.new("ShaderNodeMath"); ad.operation = "ADD"
        Lk.new(cur, ad.inputs[0]); Lk.new(sock_b, ad.inputs[1])
        cur = ad.outputs["Value"]

    if edge:  # 积墨：轮廓附近略压暗
        lw = N.new("ShaderNodeLayerWeight"); lw.inputs["Blend"].default_value = 0.5
        pw = N.new("ShaderNodeMath"); pw.operation = "POWER"; pw.inputs[1].default_value = edge_power
        Lk.new(lw.outputs["Facing"], pw.inputs[0])
        add(pw.outputs["Value"], -edge)
    if shade_attr:
        at = N.new("ShaderNodeAttribute"); at.attribute_type = "GEOMETRY"; at.attribute_name = shade_attr
        add(at.outputs["Fac"], shade_gain)
    if streak:  # 笔毛丝：在 (su, sv) 坐标里沿 sv 拉长的噪声
        au = N.new("ShaderNodeAttribute"); au.attribute_type = "GEOMETRY"; au.attribute_name = "su"
        av = N.new("ShaderNodeAttribute"); av.attribute_type = "GEOMETRY"; av.attribute_name = "sv"
        cmb = N.new("ShaderNodeCombineXYZ")
        mu = N.new("ShaderNodeMath"); mu.operation = "MULTIPLY"; mu.inputs[1].default_value = streak_scale[1]
        mv = N.new("ShaderNodeMath"); mv.operation = "MULTIPLY"; mv.inputs[1].default_value = streak_scale[0]
        Lk.new(au.outputs["Fac"], mu.inputs[0]); Lk.new(av.outputs["Fac"], mv.inputs[0])
        Lk.new(mu.outputs["Value"], cmb.inputs["X"]); Lk.new(mv.outputs["Value"], cmb.inputs["Y"])
        cmb.inputs["Z"].default_value = seed * 0.37
        sn = N.new("ShaderNodeTexNoise"); sn.inputs["Scale"].default_value = 1.0
        sn.inputs["Detail"].default_value = 2.0; sn.inputs["Roughness"].default_value = 0.6
        Lk.new(cmb.outputs["Vector"], sn.inputs["Vector"])
        sm = N.new("ShaderNodeMath"); sm.operation = "MULTIPLY_ADD"
        sm.inputs[1].default_value = streak * 2; sm.inputs[2].default_value = -streak
        Lk.new(sn.outputs["Fac"], sm.inputs[0])
        add(sm.outputs["Value"])
    # d（约 -1..1）→ 0..1
    mr = N.new("ShaderNodeMapRange")
    mr.inputs["From Min"].default_value = -1.0; mr.inputs["From Max"].default_value = 1.0
    Lk.new(cur, mr.inputs["Value"])
    cr = N.new("ShaderNodeValToRGB")
    cr.color_ramp.interpolation = "LINEAR"
    els = cr.color_ramp.elements
    for i, (pos, h) in enumerate(stops):
        e = els[i] if i < 2 else els.new(pos)
        e.position, e.color = pos, lin(h)
    Lk.new(mr.outputs["Result"], cr.inputs["Fac"])
    col = cr.outputs["Color"]
    if rim and rim_hex:  # 轮廓光
        lw2 = N.new("ShaderNodeLayerWeight"); lw2.inputs["Blend"].default_value = 0.5
        pw2 = N.new("ShaderNodeMath"); pw2.operation = "POWER"; pw2.inputs[1].default_value = rim_power
        Lk.new(lw2.outputs["Facing"], pw2.inputs[0])
        rd = N.new("ShaderNodeVectorMath"); rd.operation = "DOT_PRODUCT"; rd.inputs[1].default_value = RIM_DIR
        Lk.new(geo.outputs["Normal"], rd.inputs[0])
        rc = N.new("ShaderNodeMath"); rc.operation = "MAXIMUM"; rc.inputs[1].default_value = 0.0
        Lk.new(rd.outputs["Value"], rc.inputs[0])
        rm = N.new("ShaderNodeMath"); rm.operation = "MULTIPLY"
        Lk.new(pw2.outputs["Value"], rm.inputs[0]); Lk.new(rc.outputs["Value"], rm.inputs[1])
        rk = N.new("ShaderNodeMath"); rk.operation = "MULTIPLY"; rk.inputs[1].default_value = rim; rk.use_clamp = True
        Lk.new(rm.outputs["Value"], rk.inputs[0])
        mx = N.new("ShaderNodeMix"); mx.data_type = "RGBA"; mx.blend_type = "MIX"
        Lk.new(rk.outputs["Value"], B.sock(mx.inputs, "Factor_Float"))
        Lk.new(col, B.sock(mx.inputs, "A_Color"))
        B.sock(mx.inputs, "B_Color").default_value = lin(rim_hex)
        col = B.sock(mx.outputs, "Result_Color")
    if value_var:  # 明度的细微起伏（纸上罩染不匀）
        n2 = N.new("ShaderNodeTexNoise"); n2.noise_dimensions = "4D"
        n2.inputs["Scale"].default_value = wash_scale * 3.1; n2.inputs["W"].default_value = seed + 7.0
        Lk.new(tc.outputs["Object"], n2.inputs["Vector"])
        vv = N.new("ShaderNodeMath"); vv.operation = "MULTIPLY_ADD"
        vv.inputs[1].default_value = value_var; vv.inputs[2].default_value = 1.0 - 0.5 * value_var
        Lk.new(n2.outputs["Fac"], vv.inputs[0])
        sc = N.new("ShaderNodeVectorMath"); sc.operation = "SCALE"
        Lk.new(col, sc.inputs[0]); Lk.new(vv.outputs["Value"], B.sock(sc.inputs, "Scale"))
        col = sc.outputs["Vector"]
    emi = N.new("ShaderNodeEmission"); emi.inputs["Strength"].default_value = 1.0
    out = N.new("ShaderNodeOutputMaterial"); out.target = "CYCLES"
    Lk.new(col, emi.inputs["Color"])
    if fade_z:  # 物体坐标 z 低于 fade_z[1] 往下渐隐（下摆化进烟里），噪声打散边
        sep = N.new("ShaderNodeSeparateXYZ"); Lk.new(tc.outputs["Object"], sep.inputs[0])
        nf = N.new("ShaderNodeTexNoise"); nf.inputs["Scale"].default_value = 7.0; nf.inputs["Detail"].default_value = 3.0
        Lk.new(tc.outputs["Object"], nf.inputs["Vector"])
        nfs = N.new("ShaderNodeMath"); nfs.operation = "MULTIPLY_ADD"
        nfs.inputs[1].default_value = 0.16; nfs.inputs[2].default_value = -0.08
        Lk.new(nf.outputs["Fac"], nfs.inputs[0])
        zz = N.new("ShaderNodeMath"); zz.operation = "ADD"
        Lk.new(sep.outputs["Z"], zz.inputs[0]); Lk.new(nfs.outputs["Value"], zz.inputs[1])
        mz = N.new("ShaderNodeMapRange"); mz.interpolation_type = "SMOOTHSTEP"
        mz.inputs["From Min"].default_value = fade_z[0]; mz.inputs["From Max"].default_value = fade_z[1]
        Lk.new(zz.outputs["Value"], mz.inputs["Value"])
        tr = N.new("ShaderNodeBsdfTransparent")
        mxs = N.new("ShaderNodeMixShader")
        Lk.new(mz.outputs["Result"], mxs.inputs["Fac"])
        Lk.new(tr.outputs["BSDF"], mxs.inputs[1]); Lk.new(emi.outputs["Emission"], mxs.inputs[2])
        Lk.new(mxs.outputs["Shader"], out.inputs["Surface"])
    else:
        Lk.new(emi.outputs["Emission"], out.inputs["Surface"])
    if glow_attr:
        ag = N.new("ShaderNodeAttribute"); ag.attribute_type = "GEOMETRY"; ag.attribute_name = glow_attr
        gk = N.new("ShaderNodeMath"); gk.operation = "MULTIPLY"; gk.inputs[1].default_value = glow_gain
        Lk.new(ag.outputs["Fac"], gk.inputs[0])
        ao = N.new("ShaderNodeOutputAOV"); ao.aov_name = GLOW_AOV
        Lk.new(gk.outputs["Value"], ao.inputs["Value"])
    return m


def add_glow_const(m, value):
    """材质往 AOV glow 写一个常数（白天颜色不变，夜里透出一层光）。"""
    ao = m.node_tree.nodes.new("ShaderNodeOutputAOV"); ao.aov_name = GLOW_AOV
    ao.inputs["Value"].default_value = value
    return m


def glow_flat(name, hex_color, glow=0.0):
    """单色（缝线、裂缝的墨边）；glow>0 时同时往 AOV glow 写这个值（白天还是这个颜色，夜里缝里透光）。"""
    m = B.flat_material(name, hex_color)
    if glow:
        nt = m.node_tree
        ao = nt.nodes.new("ShaderNodeOutputAOV"); ao.aov_name = GLOW_AOV
        ao.inputs["Value"].default_value = glow
    return m


def smoke_material(name, ramp, *, fade_start=0.15, fade_power=1.3, noise_amt=0.5, seed=0.0, alpha_max=1.0,
                   edge_attr=None):
    """墨烟：沿顶点属性 fade（0 根 → 1 尖）换颜色（ramp = [(t, hex)...]，根浓尖淡），并按 fade 渐隐、噪声打散边。"""
    m, nt = B._new_node_material(name)
    N, Lk = nt.nodes, nt.links
    at = N.new("ShaderNodeAttribute"); at.attribute_type = "GEOMETRY"; at.attribute_name = "fade"
    tc = N.new("ShaderNodeTexCoord")
    nz = N.new("ShaderNodeTexNoise"); nz.noise_dimensions = "4D"; nz.inputs["W"].default_value = seed
    nz.inputs["Scale"].default_value = 9.0; nz.inputs["Detail"].default_value = 4.0
    Lk.new(tc.outputs["Object"], nz.inputs["Vector"])
    nzs = N.new("ShaderNodeMath"); nzs.operation = "MULTIPLY_ADD"
    nzs.inputs[1].default_value = noise_amt; nzs.inputs[2].default_value = -0.5 * noise_amt
    Lk.new(nz.outputs["Fac"], nzs.inputs[0])
    ft = N.new("ShaderNodeMath"); ft.operation = "MULTIPLY"
    Lk.new(nzs.outputs["Value"], ft.inputs[0]); Lk.new(at.outputs["Fac"], ft.inputs[1])
    f2 = N.new("ShaderNodeMath"); f2.operation = "ADD"; f2.use_clamp = True
    Lk.new(at.outputs["Fac"], f2.inputs[0]); Lk.new(ft.outputs["Value"], f2.inputs[1])
    cr = N.new("ShaderNodeValToRGB"); cr.color_ramp.interpolation = "LINEAR"
    for i, (pos, h) in enumerate(ramp):
        e = cr.color_ramp.elements[i] if i < 2 else cr.color_ramp.elements.new(pos)
        e.position, e.color = pos, lin(h)
    Lk.new(f2.outputs["Value"], cr.inputs["Fac"])
    mr = N.new("ShaderNodeMapRange")
    mr.inputs["From Min"].default_value = fade_start; mr.inputs["From Max"].default_value = 1.0
    Lk.new(f2.outputs["Value"], mr.inputs["Value"])
    pw = N.new("ShaderNodeMath"); pw.operation = "POWER"; pw.inputs[1].default_value = fade_power
    Lk.new(mr.outputs["Result"], pw.inputs[0])
    am = N.new("ShaderNodeMath"); am.operation = "MULTIPLY_ADD"; am.use_clamp = True
    am.inputs[1].default_value = alpha_max; am.inputs[2].default_value = 1.0 - alpha_max
    Lk.new(pw.outputs["Value"], am.inputs[0])
    fac = am.outputs["Value"]
    if edge_attr:  # 横向：两边透明（扁带的边是虚的），噪声打散
        ea = N.new("ShaderNodeAttribute"); ea.attribute_type = "GEOMETRY"; ea.attribute_name = edge_attr
        ab = N.new("ShaderNodeMath"); ab.operation = "ABSOLUTE"; Lk.new(ea.outputs["Fac"], ab.inputs[0])
        an = N.new("ShaderNodeMath"); an.operation = "ADD"
        Lk.new(ab.outputs["Value"], an.inputs[0]); Lk.new(nzs.outputs["Value"], an.inputs[1])
        me = N.new("ShaderNodeMapRange"); me.interpolation_type = "SMOOTHSTEP"
        me.inputs["From Min"].default_value = 0.35; me.inputs["From Max"].default_value = 0.95
        Lk.new(an.outputs["Value"], me.inputs["Value"])
        mxe = N.new("ShaderNodeMath"); mxe.operation = "MAXIMUM"
        Lk.new(fac, mxe.inputs[0]); Lk.new(me.outputs["Result"], mxe.inputs[1])
        fac = mxe.outputs["Value"]
    # 根部也淡入（烟从下摆里化出来，不留一道硬边）
    rf = N.new("ShaderNodeMapRange"); rf.interpolation_type = "SMOOTHSTEP"
    rf.inputs["From Min"].default_value = 0.0; rf.inputs["From Max"].default_value = 0.14
    rf.inputs["To Min"].default_value = 1.0; rf.inputs["To Max"].default_value = 0.0
    Lk.new(at.outputs["Fac"], rf.inputs["Value"])
    mrf = N.new("ShaderNodeMath"); mrf.operation = "MAXIMUM"
    Lk.new(fac, mrf.inputs[0]); Lk.new(rf.outputs["Result"], mrf.inputs[1])
    fac = mrf.outputs["Value"]
    emi = N.new("ShaderNodeEmission")
    Lk.new(cr.outputs["Color"], emi.inputs["Color"])
    tr = N.new("ShaderNodeBsdfTransparent")
    mx = N.new("ShaderNodeMixShader")
    Lk.new(fac, mx.inputs["Fac"])
    Lk.new(emi.outputs["Emission"], mx.inputs[1]); Lk.new(tr.outputs["BSDF"], mx.inputs[2])
    out = N.new("ShaderNodeOutputMaterial")
    Lk.new(mx.outputs["Shader"], out.inputs["Surface"])
    return m


# ================================================================ 墨线
def setup_lines(outer_px=2.2, form_px=1.3, inner_px=0.9, light_dist=(29.3, 30.7), heavy=(0.55, 1.25)):
    """Freestyle 三档线（沿用 bstyle 的集合分档），线宽改细一档，并加“离主光越远越粗”：背光一侧的线重、受光一侧轻。
    主光方向上 30 米处放一个空物体，距离 light_dist（米）映射到线宽倍数 heavy。"""
    vl = B.setup_freestyle()
    sc = bpy.context.scene
    tgt = bpy.data.objects.new("InkLightTarget", None)
    sc.collection.objects.link(tgt)
    tgt.location = Vector(S.KEY_LIGHT_DIR).normalized() * 30.0
    rs = S.RENDER_SCALE * S.DENSITY
    for st_name, w in (("InkOuter", outer_px), ("InkForm", form_px), ("InkInner", inner_px), ("InkCun", inner_px)):
        st = bpy.data.linestyles[st_name]
        st.thickness = w * rs
        cal = st.thickness_modifiers.get("Calligraphy")
        if cal:
            cal.thickness_min, cal.thickness_max = 0.55 * w * rs, 1.0 * w * rs
        dm = st.thickness_modifiers.new(name="Heavy", type="DISTANCE_FROM_OBJECT")
        dm.target = tgt
        dm.blend = "MULTIPLY"
        dm.mapping = "LINEAR"
        dm.range_min, dm.range_max = light_dist
        dm.value_min, dm.value_max = heavy
        bz = st.geometry_modifiers.new(name="Smooth", type="BEZIER_CURVE")
        bz.error = 2.0 * rs
    return vl


def add_aov():
    vl = bpy.context.scene.view_layers[0]
    if GLOW_AOV not in [a.name for a in vl.aovs]:
        a = vl.aovs.add(); a.name = GLOW_AOV; a.type = "VALUE"


# ================================================================ 几何小工具
def mesh_from_arrays(name, verts, faces, mat, line="outer", parent=None, attrs=None, smooth=True, marks=None):
    """numpy 顶点 (n,3) + 面（索引列表）→ 网格物体；attrs={名字: 逐顶点值}；marks=[(i, j), ...] 标 Freestyle 边。"""
    me = bpy.data.meshes.new(name)
    me.from_pydata([tuple(v) for v in np.asarray(verts, np.float64)], [], [tuple(f) for f in faces])
    me.validate()
    if smooth:
        me.shade_smooth()
    for mm in mat if isinstance(mat, (list, tuple)) else [mat]:
        me.materials.append(mm)
    ob = bpy.data.objects.new(name, me)
    B.add_object(ob, line, parent)
    for k, v in (attrs or {}).items():
        B.set_point_attr(ob, k, v)
    if marks:
        bm = bmesh.new(); bm.from_mesh(me)
        bm.verts.ensure_lookup_table()
        lay = bm.edges.layers.bool.get("freestyle_edge") or bm.edges.layers.bool.new("freestyle_edge")
        want = {tuple(sorted(e)) for e in marks}
        for e in bm.edges:
            if tuple(sorted((e.verts[0].index, e.verts[1].index))) in want:
                e[lay] = True
        bm.to_mesh(me); bm.free()
    return ob


def tube_arrays(spine, prof, nu=24, nv=48, cap0=True, cap1=True, noise_amp=0.0, seed=0.0):
    """沿脊线（模型坐标点列，在 Y-Z 平面里最好）的变截面管：prof(t) → (左右半宽, 上半厚, 下半厚)。
    截面的“左右”是模型 X（E 向时朝镜头），“上下”在脊线所在的竖平面里。返回 (顶点, 面, 属性)，
    属性：fade = su = t（沿长 0..1），sv = 绕一圈 0..1。cap0/cap1：两头收成一点（封口）。"""
    from mathutils import noise as mnoise

    sp = np.asarray([tuple(p) for p in spine], np.float64)
    seg = np.linalg.norm(np.diff(sp, axis=0), axis=1)
    s = np.concatenate([[0], np.cumsum(seg)])
    u = np.linspace(0, s[-1], nv)
    C = np.stack([np.interp(u, s, sp[:, k]) for k in range(3)], -1)
    T = np.gradient(C, axis=0)
    T /= np.linalg.norm(T, axis=1, keepdims=True) + 1e-9
    side = np.array([1.0, 0, 0])
    off = Vector((seed * 1.3, seed * 0.7, seed * 2.1))
    verts, su, sv = [], [], []
    for j in range(nv):
        t = j / (nv - 1)
        up = np.cross(T[j], side)
        up /= np.linalg.norm(up) + 1e-9
        if up[2] < 0:
            up = -up
        rx, r_up, r_dn = prof(t)
        for i in range(nu):
            th = 2 * math.pi * i / nu
            c, sn = math.cos(th), math.sin(th)
            p = C[j] + side * (rx * c) + up * ((r_up if sn > 0 else r_dn) * sn)
            if noise_amp:
                p = p + (side * c + up * sn) * mnoise.noise(Vector(p) * 6.0 + off) * noise_amp
            verts.append(p)
            su.append(t)
            sv.append(i / nu)
    faces = [(j * nu + i, j * nu + (i + 1) % nu, (j + 1) * nu + (i + 1) % nu, (j + 1) * nu + i)
             for j in range(nv - 1) for i in range(nu)]
    if cap0:
        verts.append(C[0] - T[0] * 1e-4); su.append(0.0); sv.append(0.0)
        c0 = len(verts) - 1
        faces += [(c0, (i + 1) % nu, i) for i in range(nu)]
    if cap1:
        verts.append(C[-1] + T[-1] * 1e-4); su.append(1.0); sv.append(0.0)
        c1 = len(verts) - 1
        b0 = (nv - 1) * nu
        faces += [(c1, b0 + i, b0 + (i + 1) % nu) for i in range(nu)]
    return np.asarray(verts), faces, {"fade": list(su), "su": list(su), "sv": sv}


def arrays_build(verts, faces):
    """numpy 顶点 + 面 → kit.replace_mesh 用的 bmesh 构造函数（每帧重建网格时用）。"""
    def build(bm):
        vs = [bm.verts.new(tuple(v)) for v in verts]
        for f in faces:
            try:
                bm.faces.new([vs[q] for q in f])
            except ValueError:  # 退化的面（两头收成一点时可能重复）
                pass
    return build


def alpha_streak(m, *, start=0.35, end=1.0, solid_until=0.25, streak=0.55, scale=(3.0, 26.0), seed=0.0,
                 edge_noise=0.12):
    """给材质加透明：属性 fade（0 头 → 1 尾）从 start 到 end 渐隐（噪声打散边）；fade 过了 solid_until 以后，
    顺着笔（su 沿长、sv 横向）拉长的噪声把笔画撕出一道道缝（飞白），越往尾缝越多（streak 是尾端的阈值）。"""
    nt = m.node_tree
    N, Lk = nt.nodes, nt.links
    out = next(n for n in N if n.type == "OUTPUT_MATERIAL")
    src = out.inputs["Surface"].links[0].from_socket
    fa = N.new("ShaderNodeAttribute"); fa.attribute_type = "GEOMETRY"; fa.attribute_name = "fade"
    tc = N.new("ShaderNodeTexCoord")
    n1 = N.new("ShaderNodeTexNoise"); n1.noise_dimensions = "4D"; n1.inputs["W"].default_value = seed
    n1.inputs["Scale"].default_value = 6.0; n1.inputs["Detail"].default_value = 3.0
    Lk.new(tc.outputs["Object"], n1.inputs["Vector"])
    n1s = N.new("ShaderNodeMath"); n1s.operation = "MULTIPLY_ADD"
    n1s.inputs[1].default_value = edge_noise; n1s.inputs[2].default_value = -0.5 * edge_noise
    Lk.new(n1.outputs["Fac"], n1s.inputs[0])
    fan = N.new("ShaderNodeMath"); fan.operation = "ADD"
    Lk.new(fa.outputs["Fac"], fan.inputs[0]); Lk.new(n1s.outputs["Value"], fan.inputs[1])
    ln = N.new("ShaderNodeMapRange"); ln.interpolation_type = "SMOOTHSTEP"
    ln.inputs["From Min"].default_value = start; ln.inputs["From Max"].default_value = end
    ln.inputs["To Min"].default_value = 1.0; ln.inputs["To Max"].default_value = 0.0
    Lk.new(fan.outputs["Value"], ln.inputs["Value"])
    au = N.new("ShaderNodeAttribute"); au.attribute_type = "GEOMETRY"; au.attribute_name = "su"
    av = N.new("ShaderNodeAttribute"); av.attribute_type = "GEOMETRY"; av.attribute_name = "sv"
    mu = N.new("ShaderNodeMath"); mu.operation = "MULTIPLY"; mu.inputs[1].default_value = scale[0]
    mv = N.new("ShaderNodeMath"); mv.operation = "MULTIPLY"; mv.inputs[1].default_value = scale[1]
    Lk.new(au.outputs["Fac"], mu.inputs[0]); Lk.new(av.outputs["Fac"], mv.inputs[0])
    cmb = N.new("ShaderNodeCombineXYZ"); cmb.inputs["Z"].default_value = seed * 0.37
    Lk.new(mu.outputs["Value"], cmb.inputs["X"]); Lk.new(mv.outputs["Value"], cmb.inputs["Y"])
    n2 = N.new("ShaderNodeTexNoise"); n2.inputs["Scale"].default_value = 1.0
    n2.inputs["Detail"].default_value = 2.0; n2.inputs["Roughness"].default_value = 0.55
    Lk.new(cmb.outputs["Vector"], n2.inputs["Vector"])
    th = N.new("ShaderNodeMapRange"); th.interpolation_type = "SMOOTHSTEP"
    th.inputs["From Min"].default_value = solid_until; th.inputs["From Max"].default_value = 1.0
    th.inputs["To Min"].default_value = 0.0; th.inputs["To Max"].default_value = streak
    Lk.new(fa.outputs["Fac"], th.inputs["Value"])
    lo = N.new("ShaderNodeMath"); lo.operation = "SUBTRACT"; lo.inputs[1].default_value = 0.06
    hi = N.new("ShaderNodeMath"); hi.operation = "ADD"; hi.inputs[1].default_value = 0.06
    Lk.new(th.outputs["Result"], lo.inputs[0]); Lk.new(th.outputs["Result"], hi.inputs[0])
    sm = N.new("ShaderNodeMapRange"); sm.interpolation_type = "SMOOTHSTEP"
    Lk.new(n2.outputs["Fac"], sm.inputs["Value"])
    Lk.new(lo.outputs["Value"], sm.inputs["From Min"]); Lk.new(hi.outputs["Value"], sm.inputs["From Max"])
    al = N.new("ShaderNodeMath"); al.operation = "MULTIPLY"; al.use_clamp = True
    Lk.new(ln.outputs["Result"], al.inputs[0]); Lk.new(sm.outputs["Result"], al.inputs[1])
    tr = N.new("ShaderNodeBsdfTransparent")
    mx = N.new("ShaderNodeMixShader")
    Lk.new(al.outputs["Value"], mx.inputs["Fac"])
    Lk.new(tr.outputs["BSDF"], mx.inputs[1]); Lk.new(src, mx.inputs[2])
    Lk.new(mx.outputs["Shader"], out.inputs["Surface"])
    return m


def brush_material(name, ramp, *, alpha=1.0, edge_soft=0.18, edge_dark=0.35, streak=0.6, streak_from=0.3,
                   scale=(4.0, 14.0), fade_from=0.6, seed=0.0, glow=0.0, comb=0.0, glow_to=0.5, glow_tip=0.0):
    """一笔墨（扁带：属性 t 沿长 0..1、edge 横向 -1..1）。颜色按 t 取色带（根浓尖淡），两边略深（水墨的边）；
    alpha：横向的边被噪声啃毛；沿长过了 fade_from 渐淡；飞白——顺笔拉长的噪声，t 过了 streak_from 以后阈值升高
    （越往后笔越干、缝越多，streak 是尾端的阈值）；comb > 0 时尾端散成几缕（散锋）。glow：往 AOV 写多少魂光
    （起笔处最亮，到 t = glow_to 落到 glow_tip）。"""
    m, nt = B._new_node_material(name)
    N, Lk = nt.nodes, nt.links
    at = N.new("ShaderNodeAttribute"); at.attribute_type = "GEOMETRY"; at.attribute_name = "t"
    ae = N.new("ShaderNodeAttribute"); ae.attribute_type = "GEOMETRY"; ae.attribute_name = "edge"
    tc = N.new("ShaderNodeTexCoord")

    def math_(op, a, b=None, clamp=False, **kw):
        n = N.new("ShaderNodeMath"); n.operation = op; n.use_clamp = clamp
        for i, v in enumerate((a, b)):
            if v is None:
                continue
            if isinstance(v, (int, float)):
                n.inputs[i].default_value = v
            else:
                Lk.new(v, n.inputs[i])
        return n.outputs["Value"]

    def smooth(v, lo, hi, to=(0.0, 1.0)):
        n = N.new("ShaderNodeMapRange"); n.interpolation_type = "SMOOTHSTEP"
        for key, val in (("From Min", lo), ("From Max", hi)):
            if isinstance(val, (int, float)):
                n.inputs[key].default_value = val
            else:
                Lk.new(val, n.inputs[key])
        n.inputs["To Min"].default_value, n.inputs["To Max"].default_value = to
        Lk.new(v, n.inputs["Value"])
        return n.outputs["Result"]

    na = N.new("ShaderNodeTexNoise"); na.noise_dimensions = "4D"; na.inputs["W"].default_value = seed
    na.inputs["Scale"].default_value = 28.0; na.inputs["Detail"].default_value = 4.0
    Lk.new(tc.outputs["Object"], na.inputs["Vector"])
    ne = math_("MULTIPLY_ADD", na.outputs["Fac"], 0.4)
    N_ = ne.node
    N_.inputs[2].default_value = -0.2
    ab = math_("ABSOLUTE", ae.outputs["Fac"])
    abn = math_("ADD", ab, ne)
    m_e = smooth(abn, 1.0 - edge_soft, 1.0, (1.0, 0.0))
    # 飞白
    cmb = N.new("ShaderNodeCombineXYZ"); cmb.inputs["Z"].default_value = seed * 0.37
    Lk.new(math_("MULTIPLY", at.outputs["Fac"], scale[0]), cmb.inputs["X"])
    Lk.new(math_("MULTIPLY", ae.outputs["Fac"], scale[1]), cmb.inputs["Y"])
    nb = N.new("ShaderNodeTexNoise"); nb.inputs["Scale"].default_value = 1.0
    nb.inputs["Detail"].default_value = 3.0; nb.inputs["Roughness"].default_value = 0.6
    Lk.new(cmb.outputs["Vector"], nb.inputs["Vector"])
    thr = smooth(at.outputs["Fac"], streak_from, 1.0, (0.0, streak))
    s = smooth(nb.outputs["Fac"], math_("SUBTRACT", thr, 0.05), math_("ADD", thr, 0.05))
    f = smooth(math_("ADD", at.outputs["Fac"], math_("MULTIPLY", ne, 0.3)), fade_from, 1.0, (1.0, 0.0))
    al = math_("MULTIPLY", math_("MULTIPLY", m_e, s), f, clamp=True)
    if comb:  # 散锋：尾端横向按正弦分成几缕
        sn = math_("SINE", math_("MULTIPLY", ae.outputs["Fac"], comb))
        cm = smooth(math_("ABSOLUTE", sn), 0.25, 0.6)
        tail = smooth(at.outputs["Fac"], 0.7, 0.9)
        keep = math_("SUBTRACT", 1.0, math_("MULTIPLY", tail, math_("SUBTRACT", 1.0, cm)))
        al = math_("MULTIPLY", al, keep, clamp=True)
    al = math_("MULTIPLY", al, alpha, clamp=True)
    cr = N.new("ShaderNodeValToRGB"); cr.color_ramp.interpolation = "LINEAR"
    for i, (pos, h) in enumerate(ramp):
        e = cr.color_ramp.elements[i] if i < 2 else cr.color_ramp.elements.new(pos)
        e.position, e.color = pos, lin(h)
    Lk.new(at.outputs["Fac"], cr.inputs["Fac"])
    dk = smooth(ab, 0.55, 1.0, (1.0, 1.0 - edge_dark))  # 两边深一点
    sc = N.new("ShaderNodeVectorMath"); sc.operation = "SCALE"
    Lk.new(cr.outputs["Color"], sc.inputs[0]); Lk.new(dk, B.sock(sc.inputs, "Scale"))
    emi = N.new("ShaderNodeEmission"); Lk.new(sc.outputs["Vector"], emi.inputs["Color"])
    tr = N.new("ShaderNodeBsdfTransparent")
    mx = N.new("ShaderNodeMixShader")
    Lk.new(al, mx.inputs["Fac"]); Lk.new(tr.outputs["BSDF"], mx.inputs[1]); Lk.new(emi.outputs["Emission"], mx.inputs[2])
    out = N.new("ShaderNodeOutputMaterial")
    Lk.new(mx.outputs["Shader"], out.inputs["Surface"])
    if glow:
        ao = N.new("ShaderNodeOutputAOV"); ao.aov_name = GLOW_AOV
        Lk.new(smooth(at.outputs["Fac"], 0.0, glow_to, (glow, glow_tip)), ao.inputs["Value"])
    return m


def membrane_alpha(m, center=0.5, power=1.3):
    """薄膜：正对镜头的地方半透明（center），越到轮廓越实（Facing^power → 1）。"""
    nt = m.node_tree
    N, Lk = nt.nodes, nt.links
    out = next(n for n in N if n.type == "OUTPUT_MATERIAL")
    src = out.inputs["Surface"].links[0].from_socket
    lw = N.new("ShaderNodeLayerWeight"); lw.inputs["Blend"].default_value = 0.5
    pw = N.new("ShaderNodeMath"); pw.operation = "POWER"; pw.inputs[1].default_value = power
    Lk.new(lw.outputs["Facing"], pw.inputs[0])
    ma = N.new("ShaderNodeMath"); ma.operation = "MULTIPLY_ADD"; ma.use_clamp = True
    ma.inputs[1].default_value = 1.0 - center; ma.inputs[2].default_value = center
    Lk.new(pw.outputs["Value"], ma.inputs[0])
    tr = N.new("ShaderNodeBsdfTransparent")
    mx = N.new("ShaderNodeMixShader")
    Lk.new(ma.outputs["Value"], mx.inputs["Fac"]); Lk.new(tr.outputs["BSDF"], mx.inputs[1]); Lk.new(src, mx.inputs[2])
    Lk.new(mx.outputs["Shader"], out.inputs["Surface"])
    return m


def flat_strip(name, pts_m, widths_m, side_m, mat, parent, line="none"):
    """模型坐标里的一条扁带：中线 pts_m，横向沿 side_m（每点一个方向，已归一）展开 widths_m（全宽）。
    属性 t（沿长 0..1）、edge（横向 -1..1）。每帧重建时用 strip_arrays + kit.replace_mesh。"""
    V, F, A = strip_arrays(pts_m, widths_m, side_m)
    return mesh_from_arrays(name, V, F, mat, line, parent, attrs=A, smooth=False)


def strip_arrays(pts_m, widths_m, side_m, k=5):
    n = len(pts_m)
    verts, ts, es = [], [], []
    for i in range(n):
        for j in range(k):
            e = -1 + 2 * j / (k - 1)
            verts.append(Vector(pts_m[i]) + Vector(side_m[i]) * (widths_m[i] / 2 * e))
            ts.append(i / (n - 1))
            es.append(e)
    faces = [(i * k + j, i * k + j + 1, (i + 1) * k + j + 1, (i + 1) * k + j) for i in range(n - 1) for j in range(k - 1)]
    return verts, faces, {"t": ts, "edge": es}


# ---------------------------------------------------------------- 设计稿平面里的笔画（疾影、狐火……）
VZ = 25.0 * math.cos(math.radians(S.CAMERA_PITCH_DEG))  # 设计稿的高（单位）→ 米：除以它


def d2m(x, y, lat=0.0):
    """设计稿（单位，E 向画面，x 前、y 上，锚点为原点）→ 模型坐标（米，前 = -Y）。lat：离镜头的远近（正 = 远）。
    lat = 0 的点正好落在画面上的 (x, y)。"""
    return Vector((lat, -x / 25.0, y / VZ))


def wave_line(c, amp, ph, lock=0, k=1.1, power=1.2):
    """二维中线加一道往尾传的波（第 lock 个点以前不动；越往尾摆得越大）。"""
    n = len(c)
    t = np.clip((np.arange(n) - lock) / max(n - 1 - lock, 1), 0, 1)
    tan = np.gradient(c, axis=0)
    tan /= np.linalg.norm(tan, axis=1, keepdims=True) + 1e-9
    nrm = np.stack([-tan[:, 1], tan[:, 0]], -1)
    return c + nrm * (amp * t ** power * np.sin(ph - 2.0 * math.pi * k * t))[:, None]


def design_strip(c, w, lat=0.0):
    """设计稿的中线、宽度（单位）→ 模型坐标的点、宽度（米）、横向（flat_strip / strip_arrays 用）。
    扁带放在离镜头 lat 米的竖直平面里，正对镜头。"""
    c = np.asarray(c, np.float64)
    tan = np.gradient(c, axis=0)
    tan /= np.linalg.norm(tan, axis=1, keepdims=True) + 1e-9
    nrm = np.stack([-tan[:, 1], tan[:, 0]], -1)
    o = d2m(0, 0)
    pts = [d2m(x, y, lat) for x, y in c]
    side = [(d2m(nx, ny) - o).normalized() for nx, ny in nrm]  # 设计稿的法向 → 模型竖平面里的方向
    wm = [float(wi) * (d2m(nx, ny) - o).length for wi, (nx, ny) in zip(w, nrm)]  # 单位 → 米（竖向按 VZ 换算）
    return pts, wm, side


def grid_faces(nu, nv, wrap_u=True):
    """(nv 行 × nu 列) 网格的四边面索引，u 方向首尾相接。"""
    f = []
    for j in range(nv - 1):
        for i in range(nu if wrap_u else nu - 1):
            a, b = j * nu + i, j * nu + (i + 1) % nu
            f.append((a, b, b + nu, a + nu))
    return f


def bvh_world(ob):
    dg = bpy.context.evaluated_depsgraph_get()
    ev = ob.evaluated_get(dg)
    me = ev.to_mesh()
    mw = ob.matrix_world
    verts = [mw @ v.co for v in me.vertices]
    polys = [tuple(p.vertices) for p in me.polygons]
    ev.to_mesh_clear()
    return BVHTree.FromPolygons(verts, polys)


def screen_ray(x_u, y_u):
    """设计稿上的点（单位，相对锚点，y 上）→ 世界里的一条视线（起点、方向）。正交相机。"""
    right, up, fwd = B.camera_basis()
    q = right * (x_u / S.WORLD_UNITS_PER_M) + up * (y_u / S.WORLD_UNITS_PER_M)
    return q - fwd * 20.0, fwd


def project_design(tree, pts_u):
    """把设计稿（二维）上的点投到三维表面上（世界坐标）：命中点和法线；没命中给 None。"""
    out = []
    for x, y in pts_u:
        o, d = screen_ray(x, y)
        hit = tree.ray_cast(o, d)
        if hit[0] is None:
            out.append((None, None))
            continue
        n = hit[1] if hit[1].dot(d) < 0 else -hit[1]  # 法线翻向镜头
        out.append((hit[0], n))
    return out


def project_patch(tree, center, ring):
    """一块贴片：中心投到表面上；圈上的点能投上就投，投不上的落到中心点的切平面上（贴片不会因为一个点出界就整块没了）。
    返回 [(点, 法线)]（第一个是中心），中心没投上返回 None。"""
    hits = project_design(tree, [center] + list(ring))
    c, cn = hits[0]
    if c is None:
        return None
    out = [(c, cn)]
    for (x, y), (h, n) in zip(ring, hits[1:]):
        if h is None or (h - c).length > 0.25:
            o, d = screen_ray(x, y)
            t = (c - o).dot(cn) / d.dot(cn)
            h, n = o + d * t, cn
        out.append((h, n))
    return out


def point_in_poly(x, y, poly):
    """点在不在闭合折线里（射线法）。"""
    inside = False
    n = len(poly)
    for i in range(n):
        (x0, y0), (x1, y1) = poly[i], poly[(i + 1) % n]
        if (y0 > y) != (y1 > y) and x < x0 + (y - y0) * (x1 - x0) / (y1 - y0):
            inside = not inside
    return inside


def edge_dist(x, y, poly):
    """点到闭合折线各边的最近距离。"""
    best = 1e9
    n = len(poly)
    for i in range(n):
        (x0, y0), (x1, y1) = poly[i], poly[(i + 1) % n]
        dx, dy = x1 - x0, y1 - y0
        t = max(0.0, min(1.0, ((x - x0) * dx + (y - y0) * dy) / max(dx * dx + dy * dy, 1e-12)))
        best = min(best, math.hypot(x - x0 - t * dx, y - y0 - t * dy))
    return best


def _hit_or_plane(tree, pts_u):
    """设计稿上的点投到表面：没命中的点落到最近一个命中点的切平面上（贴片边上一两个点出界也不会整块没了）。"""
    hits = project_design(tree, pts_u)
    good = [(i, h, n) for i, (h, n) in enumerate(hits) if h is not None]
    if not good:
        return None
    out = []
    for i, ((x, y), (h, n)) in enumerate(zip(pts_u, hits)):
        if h is None:
            j, c, cn = min(good, key=lambda g: (pts_u[g[0]][0] - x) ** 2 + (pts_u[g[0]][1] - y) ** 2)
            o, d = screen_ray(x, y)
            t = (c - o).dot(cn) / d.dot(cn)
            h, n = o + d * t, cn
        out.append((h, n))
    return out


def design_patch(name, tree, poly_u, mat, parent, lift=0.004, spacing=0.4, line="none"):
    """设计稿上的一块闭合形状（单位，E 向画面上画的样子）→ 贴在表面上的网格：边界照原样，里面按 spacing 撒点
    做约束三角剖分（凹的形状也行），每个点沿视线投到表面上、再沿法线抬起 lift（米）。parent：挂到哪个物体下（局部坐标）。
    边界上的点（前 len(poly) 个顶点）写属性 rim=1，里面 0。"""
    from mathutils.geometry import delaunay_2d_cdt

    poly = [tuple(map(float, p)) for p in poly_u]
    xs, ys = [p[0] for p in poly], [p[1] for p in poly]
    gx = np.arange(min(xs) + spacing / 2, max(xs), spacing)
    gy = np.arange(min(ys) + spacing / 2, max(ys), spacing * 0.87)
    pts = list(poly)
    for j, y in enumerate(gy):
        for x in gx + (spacing / 2 if j % 2 else 0.0):
            if point_in_poly(x, y, poly) and edge_dist(x, y, poly) > spacing * 0.35:  # 离边太近的不要（三角形不扁）
                pts.append((float(x), float(y)))
    vs, _e, fs, *_ = delaunay_2d_cdt([Vector(p) for p in pts], [], [list(range(len(poly)))], 1, 1e-6)
    pts2 = [(v.x, v.y) for v in vs]
    hits = _hit_or_plane(tree, pts2)
    if hits is None:
        print(f"  [v2kit] 贴片 {name} 没投上")
        return None
    inv = parent.matrix_world.inverted()
    r3 = inv.to_3x3()
    verts = [inv @ h + (r3 @ n).normalized() * lift for h, n in hits]
    ob = mesh_from_arrays(name, verts, [tuple(f) for f in fs], mat, line, parent, smooth=False)
    B.set_point_attr(ob, "rim", [1.0 if i < len(poly) else 0.0 for i in range(len(verts))])
    return ob


def design_outline(name, tree, poly_u, width_u, mat, parent, lift=0.005, closed=True, step=0.3):
    """设计稿上一条折线（闭合或不闭合）沿表面勾一道边（宽 width_u 单位，可以是逐点的列表）：脸谱、眼眶的墨边。"""
    poly = [tuple(map(float, p)) for p in poly_u]
    if closed:
        poly = poly + [poly[0]]
    dense = []
    for a, b in zip(poly[:-1], poly[1:]):
        k = max(1, int(math.hypot(b[0] - a[0], b[1] - a[1]) / step))
        for t in np.linspace(0, 1, k, endpoint=False):
            dense.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
    dense.append(poly[-1])
    hits = _hit_or_plane(tree, dense)
    if hits is None:
        return None
    inv = parent.matrix_world.inverted()
    r3 = inv.to_3x3()
    w = np.broadcast_to(np.asarray(width_u, np.float64), (len(dense),)) if np.ndim(width_u) == 0 else \
        np.interp(np.linspace(0, 1, len(dense)), np.linspace(0, 1, len(width_u)), width_u)
    return surface_strip(name, [inv @ h for h, _ in hits], [(r3 @ n).normalized() for _, n in hits],
                         w / S.WORLD_UNITS_PER_M, mat, parent, lift=lift, across=1)


def decal_material(name, stops, *, soft=0.55, seed=0.0, wash=0.3, glow=0.0):
    """贴片（脸上的朱砂、浓眉）：绘画感的颜色，横向两边、两头按属性 edge（-1..1）、t（0..1）渐隐，噪声打散边（像一笔刷上去的）。"""
    m = paint_material(name, stops, wash=wash, seed=seed, edge=0.0)
    nt = m.node_tree
    N, Lk = nt.nodes, nt.links
    out = next(n for n in N if n.type == "OUTPUT_MATERIAL")
    emi_l = out.inputs["Surface"].links[0]
    emi = emi_l.from_socket
    nt.links.remove(emi_l)
    ae = N.new("ShaderNodeAttribute"); ae.attribute_type = "GEOMETRY"; ae.attribute_name = "edge"
    at = N.new("ShaderNodeAttribute"); at.attribute_type = "GEOMETRY"; at.attribute_name = "t"
    tc = N.new("ShaderNodeTexCoord")
    nz = N.new("ShaderNodeTexNoise"); nz.inputs["Scale"].default_value = 30.0; nz.inputs["Detail"].default_value = 4.0
    nz.noise_dimensions = "4D"; nz.inputs["W"].default_value = seed
    Lk.new(tc.outputs["Object"], nz.inputs["Vector"])
    nzs = N.new("ShaderNodeMath"); nzs.operation = "MULTIPLY_ADD"
    nzs.inputs[1].default_value = 0.5; nzs.inputs[2].default_value = -0.25
    Lk.new(nz.outputs["Fac"], nzs.inputs[0])
    ab = N.new("ShaderNodeMath"); ab.operation = "ABSOLUTE"; Lk.new(ae.outputs["Fac"], ab.inputs[0])
    ad = N.new("ShaderNodeMath"); ad.operation = "ADD"; Lk.new(ab.outputs["Value"], ad.inputs[0]); Lk.new(nzs.outputs["Value"], ad.inputs[1])
    me = N.new("ShaderNodeMapRange"); me.interpolation_type = "SMOOTHSTEP"
    me.inputs["From Min"].default_value = soft; me.inputs["From Max"].default_value = 1.0
    me.inputs["To Min"].default_value = 0.0; me.inputs["To Max"].default_value = 1.0
    Lk.new(ad.outputs["Value"], me.inputs["Value"])
    # 两头：起笔略快，收笔慢慢淡（出锋）
    t0 = N.new("ShaderNodeMapRange"); t0.interpolation_type = "SMOOTHSTEP"
    t0.inputs["From Min"].default_value = 0.0; t0.inputs["From Max"].default_value = 0.10
    t0.inputs["To Min"].default_value = 1.0; t0.inputs["To Max"].default_value = 0.0
    Lk.new(at.outputs["Fac"], t0.inputs["Value"])
    t1 = N.new("ShaderNodeMapRange"); t1.interpolation_type = "SMOOTHSTEP"
    t1.inputs["From Min"].default_value = 0.72; t1.inputs["From Max"].default_value = 1.0
    t1.inputs["To Min"].default_value = 0.0; t1.inputs["To Max"].default_value = 1.0
    Lk.new(at.outputs["Fac"], t1.inputs["Value"])
    mx1 = N.new("ShaderNodeMath"); mx1.operation = "MAXIMUM"; Lk.new(me.outputs["Result"], mx1.inputs[0]); Lk.new(t0.outputs["Result"], mx1.inputs[1])
    mx2 = N.new("ShaderNodeMath"); mx2.operation = "MAXIMUM"; mx2.use_clamp = True
    Lk.new(mx1.outputs["Value"], mx2.inputs[0]); Lk.new(t1.outputs["Result"], mx2.inputs[1])
    tr = N.new("ShaderNodeBsdfTransparent")
    ms = N.new("ShaderNodeMixShader")
    Lk.new(mx2.outputs["Value"], ms.inputs["Fac"]); Lk.new(emi, ms.inputs[1]); Lk.new(tr.outputs["BSDF"], ms.inputs[2])
    Lk.new(ms.outputs["Shader"], out.inputs["Surface"])
    if glow:
        inv_ = N.new("ShaderNodeMath"); inv_.operation = "SUBTRACT"; inv_.inputs[0].default_value = 1.0
        Lk.new(mx2.outputs["Value"], inv_.inputs[1])
        gk = N.new("ShaderNodeMath"); gk.operation = "MULTIPLY"; gk.inputs[1].default_value = glow
        Lk.new(inv_.outputs["Value"], gk.inputs[0])
        ao = N.new("ShaderNodeOutputAOV"); ao.aov_name = GLOW_AOV
        Lk.new(gk.outputs["Value"], ao.inputs["Value"])
    return m


def surface_strip(name, pts, nrms, widths, mat, parent, lift=0.002, line="none", attrs_t=None, across=1):
    """贴在表面上的一条笔画（缝线、裂缝、反光线）：沿点列、在表面切平面里展开成带，宽度逐点给（两头收）。
    pts、nrms 是父物体局部坐标。attrs_t：把沿带的 t（0..1）写进这个名字的顶点属性。"""
    pts = [Vector(p) for p in pts]
    nrms = [Vector(n).normalized() for n in nrms]
    n = len(pts)
    k = 2 + 2 * across  # 横向的顶点数（多几列，边上的渐隐才平滑）
    verts, faces, ts, es = [], [], [], []
    for i in range(n):
        tan = (pts[min(i + 1, n - 1)] - pts[max(i - 1, 0)])
        tan = tan.normalized() if tan.length > 1e-9 else Vector((1, 0, 0))
        side = nrms[i].cross(tan).normalized()
        c = pts[i] + nrms[i] * lift
        w = widths[i] / 2
        for j in range(k):
            e = -1 + 2 * j / (k - 1)
            verts.append(c + side * w * e)
            ts.append(i / (n - 1))
            es.append(e)
    for i in range(n - 1):
        for j in range(k - 1):
            a = i * k + j
            faces.append((a, a + 1, a + k + 1, a + k))
    ob = mesh_from_arrays(name, verts, faces, mat, line, parent, smooth=False)
    B.set_point_attr(ob, "t", ts)
    B.set_point_attr(ob, "edge", es)
    if attrs_t:
        B.set_point_attr(ob, attrs_t, ts)
    return ob


# ================================================================ 渲染与后期
def render(prefix):
    """渲一帧：填色、墨线、物体编号（发光部件）、AOV glow。全是渲染分辨率。"""
    add_aov()
    L = B.render_layers(prefix, keep_exr=True)
    ch = B.read_exr_none(L["exr"])
    key = next((k for k in ch if k.endswith(f".{GLOW_AOV}.X") or k.endswith(f".{GLOW_AOV}.V")), None)
    L["glow"] = ch[key] if key else np.zeros(L["fill"].shape[:2], np.float32)
    Path(L["exr"]).unlink(missing_ok=True)
    return L


def dry_lines(la, seed, amount=0.25, sigma=1.2):
    """线条按细碎的噪声打散一点（飞白），只吃掉线条本身较淡的边缘和少量中段。"""
    rng = np.random.default_rng(seed)
    n = rng.standard_normal(la.shape)
    from numpy.fft import rfft2, irfft2
    h, w = la.shape
    fy = np.fft.fftfreq(h)[:, None]
    fx = np.fft.rfftfreq(w)[None, :]
    g = np.exp(-2 * math.pi ** 2 * (sigma ** 2) * (fx ** 2 + (fy * 0.6) ** 2))
    n = irfft2(rfft2(n) * g, s=(h, w))
    n = (n - n.mean()) / (n.std() + 1e-9)
    keep = np.clip(1.0 - amount * np.clip(n - 0.4, 0, None), 0.0, 1.0)
    return la * keep


def closed_smooth(poly, n):
    """闭合折线 → 过点的平滑闭合曲线（Catmull-Rom），约 n 个点。"""
    c = np.asarray(poly, np.float64)
    m = len(c)
    out = []
    per = max(2, n // m)
    for i in range(m):
        p0, p1, p2, p3 = c[(i - 1) % m], c[i], c[(i + 1) % m], c[(i + 2) % m]
        for t in np.linspace(0, 1, per, endpoint=False):
            out.append(tuple(0.5 * ((2 * p1) + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t ** 2
                                    + (-p0 + 3 * p1 - 3 * p2 + p3) * t ** 3)))
    return out


def finish(rgb, a, erg, ea, grain_name):
    """缩小后的直通 rgb/alpha（0..1）→ 最终 RGBA8：纸纹（同正式管线）、清掉极小 alpha、往透明区扩色；
    发光层同样处理；闪白是纯白 + 本体 alpha。返回 (rgba, emit, flash) 三个 uint8 数组。"""
    h, w = a.shape
    rgb255 = np.clip(rgb * 255.0 * PP.paper_grain(h, w, grain_name)[..., None], 0, 255)
    a = np.where(a < PP.ALPHA_FLOOR, 0.0, a)
    rgba = PP.to_rgba8(PP.alpha_bleed(rgb255, a), a)
    ea = np.where(ea < PP.ALPHA_FLOOR, 0.0, ea)
    emit = PP.to_rgba8(PP.alpha_bleed(np.where(ea[..., None] > 0, erg * 255.0, 0.0), ea), ea)
    return rgba, emit, PP.make_flash(rgba)


def post(L, grain, glow_hex, ink_hex=S.INK["jiao"], dry=0.22, seed=0, glow_max=1.0):
    """渲染层 → (rgba, emit, flash)：缩小、墨线（打散 + 墨晕）叠在填色上、发光层（发光部件取本色；AOV 缝光取 glow_hex）。"""
    k = S.RENDER_SCALE
    fill = PP.box_downscale(L["fill"], k)
    lines = PP.box_downscale(L["lines"], k)
    fa_hi = np.clip(L["fill"][..., 3], 0, 1)
    em = PP.box_downscale(L["emit"] * fa_hi, k)
    gl = PP.box_downscale(np.clip(L["glow"], 0, glow_max) * fa_hi * (1 - L["emit"]), k)
    rgb_lin, fa = PP.unpremultiply(fill)
    rgb = PP.linear_to_srgb(rgb_lin)
    la = np.clip(lines[..., 3], 0, 1)
    # 填色渐隐的地方（下摆化进烟里）墨线也跟着淡：线只留在填色够实的边上
    near = np.clip(PP.gaussian_blur(fa, 1.5 * S.DENSITY) * 2.2, 0, 1)
    la = la * near
    if dry:
        la = dry_lines(la, seed, dry)
    la = np.clip(PP.ink_bleed(la), 0, 1)
    ink = np.array(S.hex_to_rgb(ink_hex), np.float64) / 255.0
    out_a = la + fa * (1 - la)
    out_rgb = (ink * la[..., None] + rgb * (fa * (1 - la))[..., None]) / np.maximum(out_a, 1e-6)[..., None]
    ea = np.clip(np.maximum(em, gl) * (1 - la), 0, 1)
    gcol = np.array(S.hex_to_rgb(glow_hex), np.float64) / 255.0
    w_obj = np.clip(em / np.maximum(em + gl, 1e-6), 0, 1)[..., None]
    erg = rgb * w_obj + gcol * (1 - w_obj)
    return finish(np.clip(out_rgb, 0, 1), out_a, np.clip(erg, 0, 1), ea, grain)
