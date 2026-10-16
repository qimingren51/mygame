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
