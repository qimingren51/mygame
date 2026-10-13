"""妖物建模的公共小工具（bmesh 几何 + 常用部件），各妖物模块共用。

约定同其它模型：脚底/地面点在原点，建模面朝 -Y，单位米。妖物只渲染 "E"：
yaw_pivot() 让身体整体朝镜头偏一点（3/4 侧面），眼睛和脸在 E 向也读得出来。

帧下方的空间：30° 俯角下地面上朝镜头 d 米在画面上是锚点下方 d×PX_PER_M/2 像素。
小妖物用 ANCHOR (0.5, 0.875)，锚点下方只有 12.5% 帧高，朝镜头一侧的厚度有限（金蟾整体略往后挪）；
大体型妖物（石妖、精英、夜主）用 BIG_ENEMY_ANCHOR (0.5, 0.8)，身体中心就在锚点上，不再后挪。
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import bmesh
import bpy
import numpy as np
from mathutils import Matrix, Vector, noise

ART = Path(__file__).resolve().parents[1]
if str(ART) not in sys.path:
    sys.path.insert(0, str(ART))
from style import bstyle as B  # noqa: E402
from style import style as S  # noqa: E402


# ---------------------------------------------------------------- 几何
def boulder_build(size, seed=1.0, big=0.20, small=0.07, subdiv=3, flat_bottom=False):
    """噪声位移的细分球（石块、石妖的身体块）。size = 三个半径。"""
    sx, sy, sz = size
    off = Vector((seed * 3.1, seed * 1.7, seed * 2.3))

    def build(bm):
        bmesh.ops.create_icosphere(bm, subdivisions=subdiv, radius=1.0)
        for v in bm.verts:
            p = v.co.copy()
            d = 1 + big * noise.noise(p * 1.2 + off) + small * noise.noise(p * 3.3 + off * 2)
            q = p * d
            z = q.z * sz
            if flat_bottom and z < 0:
                z *= 0.3
            v.co = Vector((q.x * sx, q.y * sy, z))
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)

    return build


def ellipsoid(r, u=20, v=12):
    return B.uv_sphere(1.0, u, v, scale=r)


def tube_build(pts, radius_fn, segs=10, zones=None, flat=1.0, fades=None):
    """沿点列的圆管（尾巴、四肢、角）。radius_fn(t)→半径；zones(t)→材质槽号（例如尾尖换朱砂）；
    flat：截面扁度（y 方向缩放）；fades 若给一个列表，会按顶点顺序填入 t（做渐隐属性用）。尖端收成一点。"""
    pts = [Vector(p) for p in pts]
    n = len(pts)

    def build(bm):
        rings = []
        prev_u = None
        for i, p in enumerate(pts):
            t = i / (n - 1)
            tan = (pts[min(i + 1, n - 1)] - pts[max(i - 1, 0)]).normalized()
            if prev_u is None:
                u = tan.cross(Vector((0, 0, 1)))
                if u.length < 1e-4:
                    u = tan.cross(Vector((1, 0, 0)))
            else:
                u = prev_u - tan * prev_u.dot(tan)  # 平行移动，截面不扭
            u.normalize()
            prev_u = u
            v = tan.cross(u).normalized()
            r = radius_fn(t)
            if r <= 1e-5:
                rings.append([bm.verts.new(p)])
                if fades is not None:
                    fades.append(t)
                continue
            ring = []
            for j in range(segs):
                th = 2 * math.pi * j / segs
                ring.append(bm.verts.new(p + u * math.cos(th) * r + v * math.sin(th) * r * flat))
                if fades is not None:
                    fades.append(t)
            rings.append(ring)
        for k, (a, b) in enumerate(zip(rings, rings[1:])):
            t = (k + 0.5) / (n - 1)
            mi = zones(t) if zones else 0
            if len(a) == 1 and len(b) == 1:
                continue
            if len(a) == 1:
                for j in range(segs):
                    f = bm.faces.new((b[(j + 1) % segs], b[j], a[0]))
                    f.material_index = mi
            elif len(b) == 1:
                for j in range(segs):
                    f = bm.faces.new((a[j], a[(j + 1) % segs], b[0]))
                    f.material_index = mi
            else:
                for j in range(segs):
                    f = bm.faces.new((a[j], a[(j + 1) % segs], b[(j + 1) % segs], b[j]))
                    f.material_index = mi
        if len(rings[0]) > 1:
            f = bm.faces.new(list(reversed(rings[0])))
            f.material_index = zones(0.0) if zones else 0
        if len(rings[-1]) > 1:
            f = bm.faces.new(rings[-1])
            f.material_index = zones(1.0) if zones else 0
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)

    return build


def bushy(r_max, peak=0.35, tip=0.0):
    """毛尾半径曲线：根部细、中前段最粗、尖端收尖。"""
    def f(t):
        if t >= 1.0:
            return tip
        up = math.sin(math.pi / 2 * min(t / peak, 1.0)) ** 0.7
        down = (1 - max(0.0, t - peak) / (1 - peak)) ** 0.75
        return max(r_max * (0.35 + 0.65 * up) * down, tip)
    return f


def curve_points(p0, p1, bend=Vector((0, 0, 0)), n=12, wave=None):
    """p0→p1 的弯曲点列：中段按 bend 方向鼓出（二次）；wave(t)→附加偏移。"""
    p0, p1 = Vector(p0), Vector(p1)
    out = []
    for i in range(n):
        t = i / (n - 1)
        p = p0.lerp(p1, t) + bend * (4 * t * (1 - t))
        if wave:
            p += wave(t)
        out.append(p)
    return out


def strip_build(pts, width, thick, twist=0.0, taper=(1.0, 0.6), side_hint=Vector((1, 0, 0))):
    """扁带（布条、毛发束）。"""
    pts = [Vector(p) for p in pts]
    n = len(pts)
    ups = []
    for i in range(n):
        tan = (pts[min(i + 1, n - 1)] - pts[max(i - 1, 0)]).normalized()
        side = side_hint - tan * side_hint.dot(tan)
        if side.length < 1e-4:
            side = Vector((0, 1, 0))
        side.normalize()
        side = (Matrix.Rotation(twist * i / max(n - 1, 1), 3, tan) @ side).normalized()
        ups.append(tan.cross(side))
    return B.sweep(pts, width, thick, ups=ups, width_fn=lambda t: taper[0] + (taper[1] - taper[0]) * t)


def rag_panel_rows(center_deg, width_deg, r_top, z_top, length, phase=0.0, wind=0.0, flare=0.12,
                   tatter=0.25, seed=0, nu=6, nv=8, sy=0.8, center=Vector((0, 0, 0))):
    """破布片点阵（破袍下摆）：从一圈腰线垂下，下缘参差（按列随机缩短），随风/相位飘。"""
    rng = np.random.default_rng(seed)
    cut = 1 - tatter * rng.random(nu + 1)
    rows = []
    for j in range(nv + 1):
        t = j / nv
        row = []
        for i in range(nu + 1):
            u = i / nu
            th = math.radians(center_deg + (u - 0.5) * width_deg)
            out = Vector((math.cos(th), math.sin(th) * sy, 0)).normalized()
            L = length * cut[i]
            p = center + Vector((r_top * math.cos(th), r_top * math.sin(th) * sy, z_top))
            p += out * (flare * t) + Vector((0, 0, -L * t))
            s = wind * t * t * L
            p += Vector((0, 0.7 * s, 0.25 * s * t))
            p += out * (0.03 * t * math.sin(2 * math.pi * t - phase + u * 2 + seed))
            row.append(p)
        rows.append(row)
    return rows


def grid_build(rows, outward_from=Vector((0, 0, 0))):
    """点阵 → 单层曲面，法线朝外（远离 outward_from 的竖轴）。"""
    def build(bm):
        vs = [[bm.verts.new(p) for p in row] for row in rows]
        for j in range(len(vs) - 1):
            for i in range(len(vs[0]) - 1):
                bm.faces.new((vs[j][i], vs[j][i + 1], vs[j + 1][i + 1], vs[j + 1][i]))
        for f in bm.faces:
            c = f.calc_center_median() - outward_from
            if f.normal.dot(Vector((c.x, c.y, 0))) < 0:
                f.normal_flip()
    return build


def replace_mesh(ob, build, smooth=True, attrs=None):
    """换掉物体的网格（每帧重建飘动部件），保留材质；attrs={名字: 逐顶点值}。"""
    old = ob.data
    me = bpy.data.meshes.new(old.name)
    bm = bmesh.new()
    build(bm)
    bm.to_mesh(me)
    bm.free()
    if smooth:
        me.shade_smooth()
    for m in old.materials:
        me.materials.append(m)
    ob.data = me
    if old.users == 0:
        bpy.data.meshes.remove(old)
    for k, v in (attrs or {}).items():
        B.set_point_attr(ob, k, v)


def limb(name, a, b, r0, r1, mat, line, parent, segs=10):
    """从 a 到 b 的锥台（四肢、杆）。"""
    a, b = Vector(a), Vector(b)
    ob = B.mesh_object(name, B.cylinder(r0, r1, (b - a).length, segs), mat, line, parent, sharp_deg=0)
    B.aim(ob, a, b)
    return ob


def yaw_pivot(name, parent, yaw_deg=-25.0, loc=(0, 0, 0)):
    """身体朝镜头偏转的枢轴（E 向时 -25° ≈ 3/4 侧面）。"""
    return B.empty(name, parent, loc=loc, rot=(0, 0, math.radians(yaw_deg)))


def slit_eyes(prefix, parent, center, sep, size, mat, tilt_deg=18.0, line="none"):
    """两只斜挑的发光眼（emissive），center 是两眼中点（父物体坐标），返回挂点 empty。"""
    c = Vector(center)
    for sx in (-1, 1):
        B.mesh_object(f"{prefix}Eye{sx:+d}", ellipsoid(size, 12, 6), mat, line, parent,
                      loc=c + Vector((sep / 2 * sx, 0, 0)), rot=(0, math.radians(-tilt_deg * sx), 0))
    return B.empty(f"{prefix}SocketEyes", parent, loc=c)


def toon(name, base=None, ramp=None, **kw):
    return B.toon_material(name, base, ramp=ramp, **kw)


def flame_material(name, bands, emissive_hex=None, seed=0.0, edge=0.45, noise_amt=0.14, rim=0.0, rim_power=2.0,
                   **toon_kw):
    """发光的火身（狐火、九尾尾尖的狐火）：沿顶点属性 fade 分段的假卡通（banded_toon_material），
    每段直接给三档 hex（亮, 中, 暗）——火根亮、火舌尖暗；整个物体进发光遮罩（emissive）。
    rim>0 时越靠轮廓越往后面的段走（芯亮、边是深青，像一团火而不是一个亮的实体）。
    这些颜色不在 style.py 的调色板里，出图要写进 palette_extra。积墨（edge）让轮廓处落到暗档。"""
    m = banded_toon_material(name, bands, noise_amt=noise_amt, seed=seed, edge=edge, rim=rim, rim_power=rim_power,
                             **toon_kw)
    m["emissive"] = emissive_hex or bands[0][1][0]
    m["emit_strength"] = 1.0
    return m


def _ramp_of(base):
    """分段颜色：一个 hex（按 shade_ramp 展开三档）或直接给的三档 (亮, 中, 暗)。"""
    return list(base) if isinstance(base, (tuple, list)) else S.shade_ramp(base)


def banded_toon_material(name, bands, attr="fade", noise_amt=0.10, seed=0.0, rim=0.0, rim_power=2.0, **toon_kw):
    """沿顶点属性 attr（0..1）分段换颜色的假卡通材质（九尾的尾巴：根部浓墨 → 淡墨 → 藤黄 → 朱砂尖）。
    bands = [(起点 t, 基础色 hex 或三档 (亮, 中, 暗)), ...]；每段是该色的三档 shade_ramp（或直接给的三档），段与段之间用噪声打散成水墨晕开的边，
    同一个材质里完成，所以分段处不会被 Freestyle 当成材质分界描线。
    rim>0：分段位置再加 rim·Facing^rim_power（越靠轮廓越往后面的段走；缺省 0，不加这一项）。"""
    I = S.INK
    m = B.toon_material(name, ramp=_ramp_of(bands[0][1]), **toon_kw)
    nt = m.node_tree
    N, L = nt.nodes, nt.links
    ramp_node = next(n for n in N if n.type == "VALTORGB")  # 原来的三档：亮/中/暗
    fac_src = ramp_node.inputs["Fac"].links[0].from_socket
    scale_node = ramp_node.outputs["Color"].links[0].to_node
    at = N.new("ShaderNodeAttribute"); at.attribute_type = "GEOMETRY"; at.attribute_name = attr
    tc = N.new("ShaderNodeTexCoord")
    nz = N.new("ShaderNodeTexNoise"); nz.inputs["Scale"].default_value = 6.0
    L.new(tc.outputs["Object"], nz.inputs["Vector"])
    nzs = N.new("ShaderNodeMath"); nzs.operation = "MULTIPLY_ADD"
    nzs.inputs[1].default_value = noise_amt; nzs.inputs[2].default_value = -0.5 * noise_amt
    L.new(nz.outputs["Fac"], nzs.inputs[0])
    tt = N.new("ShaderNodeMath"); tt.operation = "ADD"; tt.use_clamp = True
    L.new(at.outputs["Fac"], tt.inputs[0]); L.new(nzs.outputs["Value"], tt.inputs[1])
    if rim > 0:  # 轮廓处往后面的段走
        lw = N.new("ShaderNodeLayerWeight"); lw.inputs["Blend"].default_value = 0.5
        pw = N.new("ShaderNodeMath"); pw.operation = "POWER"; pw.inputs[1].default_value = rim_power
        L.new(lw.outputs["Facing"], pw.inputs[0])
        rk = N.new("ShaderNodeMath"); rk.operation = "MULTIPLY_ADD"
        rk.inputs[1].default_value = rim
        L.new(pw.outputs["Value"], rk.inputs[0])
        L.new(nzs.outputs["Value"], rk.inputs[2])
        L.new(rk.outputs["Value"], tt.inputs[1])
    outs = []
    for step in range(3):  # 每一档（亮/中/暗）各一个沿 t 的常量色带
        cr = N.new("ShaderNodeValToRGB")
        cr.color_ramp.interpolation = "CONSTANT"
        els = cr.color_ramp.elements
        for k, (t0, base) in enumerate(bands):
            col = B.hex_lin(_ramp_of(base)[step])
            if k < 2:
                els[k].position, els[k].color = t0, col
            else:
                e = els.new(t0); e.color = col
        if len(bands) == 1:
            els[1].position, els[1].color = 1.0, B.hex_lin(_ramp_of(bands[0][1])[step])
        L.new(tt.outputs["Value"], cr.inputs["Fac"])
        outs.append(cr.outputs["Color"])
    # 用原来的明暗点积选档：>阈值1 亮，>阈值2 中，否则暗
    t_lit, t_mid = S.SHADE_THRESHOLDS
    g1 = N.new("ShaderNodeMath"); g1.operation = "GREATER_THAN"; g1.inputs[1].default_value = t_lit
    g2 = N.new("ShaderNodeMath"); g2.operation = "GREATER_THAN"; g2.inputs[1].default_value = t_mid
    L.new(fac_src, g1.inputs[0]); L.new(fac_src, g2.inputs[0])
    mx1 = N.new("ShaderNodeMix"); mx1.data_type = "RGBA"
    L.new(g2.outputs["Value"], B.sock(mx1.inputs, "Factor_Float"))
    L.new(outs[2], B.sock(mx1.inputs, "A_Color")); L.new(outs[1], B.sock(mx1.inputs, "B_Color"))
    mx2 = N.new("ShaderNodeMix"); mx2.data_type = "RGBA"
    L.new(g1.outputs["Value"], B.sock(mx2.inputs, "Factor_Float"))
    L.new(B.sock(mx1.outputs, "Result_Color"), B.sock(mx2.inputs, "A_Color")); L.new(outs[0], B.sock(mx2.inputs, "B_Color"))
    for lk in list(ramp_node.outputs["Color"].links):
        nt.links.remove(lk)
    L.new(B.sock(mx2.outputs, "Result_Color"), scale_node.inputs[0])
    m["toon_ramp"] = [c for _, b in bands for c in _ramp_of(b)]
    return m
