"""升级卡插画：法器（本体、进化、异化）与合璧。题材见 docs/LORE-TEXT.md 第 7.1、7.3 节。

每张：@scene 注册 3D 场景（相机、灯、物体），@background 注册水墨底。由 card_art.py 统一渲染和后期：
  art/.venv/bin/python art/render/card_art.py sword --draft
"""

from __future__ import annotations

import math

import numpy as np

import card_art as K
import card_props as P
from card_art import background, lin, make_obj, scene

COLD_GRADE = dict(exposure=1.05, shadow="#141E30", high="#EAF2FF", sat=0.95, bloom=0.34, contrast=1.06)
WARM_GRADE = dict(exposure=0.98, shadow="#1A2236", high="#FFE2B0", sat=1.02, bloom=0.32, contrast=1.04)


def area_oriented(name, loc, target, xdir, energy, size, size_y, color=(1, 1, 1)):
    """长条面光：-Z 朝向 target，长边（X）尽量顺着 xdir（给剑身打一道长高光）。"""
    bpy = K._bpy()
    from mathutils import Matrix, Vector  # noqa: PLC0415

    L = bpy.data.lights.new(name, "AREA")
    L.energy, L.color, L.shape, L.size, L.size_y = energy, color, "RECTANGLE", size, size_y
    ob = K.link(bpy.data.objects.new(name, L))
    ob.location = loc
    z = (Vector(loc) - Vector(target)).normalized()
    x = Vector(xdir)
    x = (x - z * x.dot(z)).normalized()
    y = z.cross(x)
    ob.rotation_euler = Matrix((x, y, z)).transposed().to_euler()
    return ob


def sky_gradient(top, horizon, strength=1.0, ground=None, width=0.35):
    """天光：朝上暗、地平线一带亮、朝下（地面）又暗下去——金属面映出一道渐变，不至于一片黑，也不至于整面发白。"""
    bpy = K._bpy()
    ground = ground if ground is not None else tuple(c * 0.25 for c in top)
    w = bpy.context.scene.world
    nt = w.node_tree
    nt.nodes.clear()
    tc = nt.nodes.new("ShaderNodeTexCoord")
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    nt.links.new(tc.outputs["Generated"], sep.inputs[0])
    mr = nt.nodes.new("ShaderNodeMapRange")
    mr.inputs["From Min"].default_value = -1.0
    mr.inputs["From Max"].default_value = 1.0
    nt.links.new(sep.outputs["Z"], mr.inputs["Value"])
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    cr = ramp.color_ramp
    cr.elements[0].position, cr.elements[0].color = 0.5 - width * 0.5, (*ground, 1.0)
    cr.elements[1].position, cr.elements[1].color = 0.5 + width, (*top, 1.0)
    e = cr.elements.new(0.5 + 0.02)
    e.color = (*horizon, 1.0)
    nt.links.new(mr.outputs["Result"], ramp.inputs["Fac"])
    bg = nt.nodes.new("ShaderNodeBackground")
    bg.inputs["Strength"].default_value = strength
    nt.links.new(ramp.outputs["Color"], bg.inputs["Color"])
    out = nt.nodes.new("ShaderNodeOutputWorld")
    nt.links.new(bg.outputs["Background"], out.inputs["Surface"])


def bg_clouds(P_, rng, k, bands, color, a):
    """几道横云：bands = [(y, 半高, x0, x1)]（按 0..1），云边按噪声打散，像淡墨一笔横扫。"""
    h, w = P_.h, P_.w
    for y, hh, x0, x1 in bands:
        cx, rx = (x0 + x1) / 2 * w, (x1 - x0) / 2 * w
        ux = np.clip(1 - ((P_.X - cx) / rx) ** 2, 0, 1)
        n = K._noise(rng, (h, w), (60 * k, 7 * k))
        m = np.exp(-((P_.Y - y * h) / (hh * h)) ** 2) * ux ** 0.7 * K._ss(-0.3, 0.6, n)
        P_.light(m * a, color)


# ====================================================================== 符剑


def sword_frame(rz, ry):
    """剑的朝向：绕 Z 转 rz（剑尖转向镜头），再绕 Y 转 ry（剑尖抬起）。返回 (旋转矩阵, 欧拉角)。"""
    from mathutils import Matrix  # noqa: PLC0415

    R = Matrix.Rotation(rz, 3, "Z") @ Matrix.Rotation(ry, 3, "Y")
    return R, R.to_euler()


@scene("sword", name="符剑", samples=128, grade=COLD_GRADE)
def build_sword(draft):
    """符剑：一柄细长的剑悬在半空，左下剑柄、右上剑尖（斜着朝前）；剑身中段贴一道黄符，符纸后半截被剑气吹起、往后飘；
    几缕冷白的剑气从剑尖沿剑身往后拖。月光从左后打轮廓，一道长条面光给剑面一道长高光；天光上暗下亮，钢面映出渐变。"""
    from mathutils import Vector  # noqa: PLC0415

    sky_gradient(lin("#05080F"), lin("#33496C"), 0.9, ground=lin("#04060A"))
    rng = np.random.default_rng(11)
    R, eul = sword_frame(math.radians(-18), math.radians(-15))
    mid = R @ Vector((0.27, 0, 0))
    loc = tuple(-mid + Vector((0.0, 0.0, -0.01)))
    steel = P.mat_steel("Steel", tint=(0.80, 0.83, 0.88), rough=0.12, edge_glow=((0.78, 0.90, 1.0), 0.7))
    root = P.sword("Sword", L=0.74, W=0.040, T=0.0085, steel=steel, loc=loc, rot=eul, index=1)
    # 黄符：前段贴在剑面上（剑面在 -Y），往后离开剑身、被风吹起成波浪
    img = K.np_image("talisman", P.talisman_texture("雷令"), colorspace="sRGB")
    pts, ups = [], []
    T = 0.0085
    for s in np.linspace(0, 1, 56):
        x = 0.30 - 0.42 * s
        lift = K.smoothstep(0.20, 0.55, s)
        y = -(T / 2 + 0.0012) - 0.06 * lift - 0.014 * math.sin(6.0 * s + 0.6) * lift
        z = 0.002 + (0.030 * math.sin(8.0 * s - 1.4) - 0.045 * s) * lift
        pts.append((x, y, z))
        phi = 0.8 * lift * math.sin(4.5 * s + 0.3)
        ups.append((0.0, math.sin(phi), math.cos(phi)))
    P.talisman_strip("Talisman", pts, 0.044, img, ups=ups, parent=root, index=2, curl_amp=0.05)
    # 剑气：几缕冷白的光带，从剑尖前方沿剑身往后拖，绕剑身转小半圈（离剑身远一点，不糊住剑面）
    for j in range(5):
        r0 = rng.uniform(0.045, 0.10)
        a0 = rng.uniform(0, 2 * math.pi)
        turn = rng.uniform(0.4, 1.0) * (1 if j % 2 else -1)
        x0, x1 = rng.uniform(0.72, 0.84), rng.uniform(-0.40, -0.05)
        pts = []
        for s in np.linspace(0, 1, 60):
            x = x0 + (x1 - x0) * s
            a = a0 + turn * s
            rr = r0 * (0.30 + 0.70 * K.smoothstep(0.0, 0.40, s)) * (1 + 0.5 * s)
            pts.append((x, rr * math.sin(a) * 0.6 + 0.02, rr * math.cos(a)))
        wd = rng.uniform(0.010, 0.026)
        make_obj(f"Qi{j}", K.ribbon_uv(pts, wd), K.mat_wind(f"QiM{j}", strength=rng.uniform(0.9, 1.5), seed=float(j) * 1.7,
                                                         color=(0.74, 0.86, 1.0)), parent=root, index=3)
    tip = R @ Vector((0.74, 0, 0)) + Vector(loc)
    K.point_light("TipLight", tuple(tip + Vector((0, -0.02, 0.0))), 0.4, radius=0.01, color=(0.75, 0.88, 1.0))
    blade_dir = R @ Vector((1, 0, 0))
    area_oriented("Strip", (0.15, -1.2, 0.95), (0.0, 0.0, 0.0), tuple(blade_dir), 22.0, 2.4, 0.04, color=(0.80, 0.88, 1.0))
    K.area_light("Moon", (-1.4, 1.3, 1.5), (0, 0, 0), 120.0, 1.2, color=(0.66, 0.78, 1.0))
    K.area_light("Rim", (1.6, 1.2, 0.2), (0, 0, 0), 50.0, 0.8, color=(0.6, 0.72, 1.0))
    K.area_light("Warm", (-1.3, -0.5, 0.1), (-0.2, 0, 0), 4.0, 0.6, color=(1.0, 0.74, 0.46))
    area_oriented("Under", (0.1, -1.0, -0.9), (0.0, 0.0, 0.0), tuple(blade_dir), 7.0, 2.4, 0.10, color=(0.72, 0.82, 1.0))
    K.camera((0.0, -1.62, 0.16), (0.0, 0.0, 0.0), lens=50.0, fstop=5.6, focus=1.60)
    return {"light": "cold"}


@background("sword")
def bg_sword(P_, h, w, rng, k):
    P_.fill_grad("#0C1322", "#111B2E", cloud=0.12)
    K.bg_glow(P_, 0.52, 0.50, 0.46, 0.36, "#405A80", 0.30)
    K.bg_moon(P_, 0.33, 0.29, 0.075, rng, k, color="#EEF2F8", halo="#7890B6", a=0.92, halo_a=0.42)
    bg_clouds(P_, rng, k, [(0.30, 0.035, 0.05, 0.62), (0.36, 0.022, 0.40, 0.98), (0.66, 0.03, 0.10, 0.70)], "#5B7194", 0.20)
    K.bg_mountains(P_, [(0.90, [(0.12, 0.10, 0.12, 0.10), (0.36, 0.06, 0.12, 0.14), (0.70, 0.12, 0.14, 0.12), (0.94, 0.07, 0.10, 0.10)],
                         "#17233A", 0.85, 0.08, 5.0)], rng, k)
    K.bg_mist(P_, 0.86, 0.05, "#7F9CC0", 0.14, rng, k)
    K.bg_ink(P_, [(0.02, 0.06, 0.26, 0.18, 0.2), (0.98, 0.08, 0.24, 0.18, -0.4)], 0.45)


# ====================================================================== 万剑归宗


def mat_ghost_blade(name, color=(0.70, 0.84, 1.0)):
    """剑影：半透明的冷光剑——中间透、轮廓和刃口亮（像残影）。每把剑的物体属性 fade（0..1）：越靠后越淡。"""
    M = K.Mat(name)
    m = M.math
    at = M.n("ShaderNodeAttribute", _attribute_type="OBJECT", _attribute_name="fade")
    fade = at.outputs["Fac"]
    lw = M.n("ShaderNodeLayerWeight", Blend=0.25)
    rim = m("POWER", lw.outputs["Facing"], 2.0)
    bsdf = M.principled(Base_Color=(0.50, 0.56, 0.66, 1.0), Metallic=1.0, Roughness=0.16)
    emi = M.n("ShaderNodeEmission", Color=(*color, 1.0))
    M.l(m("MULTIPLY", m("ADD", m("MULTIPLY", rim, 2.2), 0.10), m("MULTIPLY", fade, 1.6)), emi.inputs["Strength"])
    add = M.n("ShaderNodeAddShader")
    M.l(bsdf.outputs[0], add.inputs[0])
    M.l(emi.outputs[0], add.inputs[1])
    tr = M.n("ShaderNodeBsdfTransparent")
    mx = M.n("ShaderNodeMixShader")
    op = m("MULTIPLY", m("ADD", m("MULTIPLY", rim, 0.65), 0.32), m("ADD", m("MULTIPLY", fade, 0.80), 0.20), clamp=True)
    M.l(op, mx.inputs[0])
    M.l(tr.outputs[0], mx.inputs[1])
    M.l(add.outputs[0], mx.inputs[2])
    return M.surface(mx.outputs[0])


def ghost_sword_build(L=0.66, W=0.028, T=0.007):
    """简化的剑（剑身 + 一字格 + 柄），合成一个网格：剑影用。沿 +X，剑格在原点。"""
    def build(bm):
        import bmesh  # noqa: PLC0415

        P.blade_build(L, W, T)(bm)
        res = bmesh.ops.create_cube(bm, size=1.0)
        bmesh.ops.scale(bm, vec=(0.012, T * 2.6, W * 1.7), verts=res["verts"])
        res = bmesh.ops.create_cone(bm, cap_ends=True, segments=10, radius1=0.010, radius2=0.010, depth=0.15)
        bmesh.ops.rotate(bm, cent=(0, 0, 0), matrix=__import__("mathutils").Matrix.Rotation(math.pi / 2, 3, "Y"), verts=res["verts"])
        bmesh.ops.translate(bm, vec=(-0.085, 0, 0), verts=res["verts"])
    return build


class ScreenCam:
    """按画面位置摆东西：相机在原点朝 +Y、Z 朝上。screen(x, y, 深度) → 世界坐标（x、y 按 0..1，左上为原点）。"""

    def __init__(self, lens=35.0, sensor=36.0, aspect=0.75):
        self.k = sensor / lens
        self.aspect = aspect

    def __call__(self, x, y, depth):
        from mathutils import Vector  # noqa: PLC0415

        W = depth * self.k
        return Vector(((x - 0.5) * W, depth, (0.5 - y) * W * self.aspect))

    def place(self, lens=35.0, fstop=None, focus=None):
        return K.camera((0.0, 0.0, 0.0), (0.0, 1.0, 0.0), lens=lens, fstop=fstop, focus=focus)


@scene("sword_evo", name="万剑归宗", samples=128, grade=dict(COLD_GRADE, bloom=0.36))
def build_sword_evo(draft):
    """万剑归宗：几十把剑排成一股宽带，从左下斜着涌向右上；最前面一把是贴着黄符的实剑、最亮、离镜头最近，
    后面的剑影都顺着带子指向同一处，前后错开几层、越往后越淡；带子里拖着几道剑气。按画面位置摆（ScreenCam）。"""
    from mathutils import Quaternion, Vector  # noqa: PLC0415

    sky_gradient(lin("#05080F"), lin("#33496C"), 0.9, ground=lin("#04060A"))
    rng = np.random.default_rng(23)
    S = ScreenCam(lens=35.0)
    # 领头的实剑：剑格在画面 (0.55, 0.50)、深 1.6，剑尖指向右上、略朝镜头
    g0, g1 = S(0.55, 0.50, 1.60), S(0.97, 0.27, 1.45)
    d = (g1 - g0).normalized()
    q = d.to_track_quat("X", "Z")
    steel = P.mat_steel("LeadSteel", tint=(0.84, 0.87, 0.92), rough=0.12, edge_glow=((0.80, 0.92, 1.0), 1.6))
    root = P.sword("Lead", steel=steel, loc=tuple(g0), rot=q.to_euler(), index=1, tassel=True)
    # 领头剑也贴一道黄符（符剑进化来的），后半截被剑气吹起
    img = K.np_image("talisman", P.talisman_texture("雷令"), colorspace="sRGB")
    pts, ups = [], []
    T = 0.0075
    for s in np.linspace(0, 1, 56):
        lift = K.smoothstep(0.20, 0.55, s)
        pts.append((0.26 - 0.40 * s, -(T / 2 + 0.0012) - 0.05 * lift - 0.012 * math.sin(6.0 * s + 0.6) * lift,
                    0.002 + (0.026 * math.sin(8.0 * s - 1.4) - 0.040 * s) * lift))
        phi = 0.8 * lift * math.sin(4.5 * s + 0.3)
        ups.append((0.0, math.sin(phi), math.cos(phi)))
    P.talisman_strip("Talisman", pts, 0.040, img, ups=ups, parent=root, index=2, curl_amp=0.05)
    # 剑影：一股宽带从左下斜着涌向领头剑，剑都顺着带子指向右上；前后错开几层（层层叠叠），越往后越淡
    ghost = mat_ghost_blade("Ghost")
    gb = ghost_sword_build()
    a0, a1 = Vector((0.48, 0.55)), Vector((-0.10, 1.02))  # 带子中线：画面位置，从紧跟领头剑到左下出画
    across = Vector((-(a1 - a0).y, (a1 - a0).x)).normalized()
    n = 54
    for i in range(n):
        t = (i + rng.uniform(0, 1)) / n
        c = a0 + (a1 - a0) * t + across * rng.normal(0, 0.035 + 0.075 * t)
        depth = 1.85 + 1.4 * t + rng.normal(0, 0.18 + 0.30 * t)
        p0 = S(c.x, c.y, depth)
        dd = (d + Vector(rng.normal(0, 0.035, 3))).normalized()
        qq = dd.to_track_quat("X", "Z") @ Quaternion((1, 0, 0), rng.uniform(-0.7, 0.7))
        sc = rng.uniform(0.85, 1.10)
        ob = make_obj(f"Ghost{i}", gb, ghost, smooth=False, loc=tuple(p0), scale=(sc, sc, sc), index=2)
        ob.rotation_mode = "QUATERNION"
        ob.rotation_quaternion = qq
        ob["fade"] = float(max(0.08, (1 - t) ** 1.25 * rng.uniform(0.7, 1.0)))
    # 剑气：顺着带子的几道细光带，一直拖到领头剑的剑尖前
    for j in range(6):
        c0 = a1 + across * rng.normal(0, 0.06)
        c1 = Vector((0.95, 0.30)) + across * rng.normal(0, 0.03)
        pts = []
        for t in np.linspace(0, 1, 90):
            cc = c0 + (c1 - c0) * t + across * 0.03 * math.sin(3.0 * t + j)
            pts.append(tuple(S(cc.x, cc.y, 3.4 - 1.9 * t + rng.normal(0, 0.002))))
        make_obj(f"Stream{j}", K.ribbon_uv(pts, rng.uniform(0.02, 0.05)),
                 K.mat_wind(f"StreamM{j}", strength=rng.uniform(0.6, 1.0), seed=j * 2.3, color=(0.70, 0.84, 1.0)), index=3)
    p = Vector(g0)
    K.point_light("LeadGlow", tuple(p + d * 0.45 + Vector((0, -0.12, 0.12))), 0.6, radius=0.05, color=(0.75, 0.88, 1.0))
    area_oriented("Strip", tuple(p + Vector((0.1, -1.0, 0.9))), tuple(p), tuple(d), 22.0, 2.4, 0.05, color=(0.80, 0.88, 1.0))
    area_oriented("Under", tuple(p + Vector((0.1, -0.9, -0.8))), tuple(p), tuple(d), 6.0, 2.4, 0.10, color=(0.72, 0.82, 1.0))
    K.area_light("Moon", tuple(S(0.3, -0.3, 6.0) + Vector((0, 2.0, 2.0))), tuple(S(0.5, 0.5, 3.0)), 500.0, 2.0, color=(0.66, 0.78, 1.0))
    K.area_light("Warm", tuple(S(0.1, 0.9, 0.5)), tuple(S(0.5, 0.5, 2.0)), 6.0, 0.8, color=(1.0, 0.74, 0.46))
    S.place(lens=35.0, fstop=4.0, focus=1.6)
    return {"light": "cold"}


@background("sword_evo")
def bg_sword_evo(P_, h, w, rng, k):
    P_.fill_grad("#0B1220", "#121C30", cloud=0.12)
    K.bg_glow(P_, 0.45, 0.45, 0.50, 0.40, "#3E5680", 0.30)
    K.bg_glow(P_, 0.92, 0.28, 0.20, 0.24, "#9FB6D6", 0.24)
    K.bg_moon(P_, 0.34, 0.24, 0.045, rng, k, color="#E6ECF4", halo="#7890B6", a=0.55, halo_a=0.26)
    bg_clouds(P_, rng, k, [(0.20, 0.03, 0.30, 0.85), (0.30, 0.02, 0.45, 0.95), (0.76, 0.03, 0.25, 0.95)], "#5B7194", 0.22)
    K.bg_mountains(P_, [(0.93, [(0.10, 0.12, 0.12, 0.10), (0.40, 0.08, 0.14, 0.12), (0.78, 0.14, 0.14, 0.14)], "#16223A", 0.85, 0.08, 5.0)],
                   rng, k)
    K.bg_mist(P_, 0.88, 0.05, "#7F9CC0", 0.14, rng, k)
    K.bg_ink(P_, [(0.02, 0.06, 0.26, 0.18, 0.2), (0.98, 0.08, 0.24, 0.18, -0.4)], 0.45)


# ====================================================================== 纸鹤


@scene("crane", name="纸鹤", samples=128, grade=dict(WARM_GRADE, exposure=1.02, bloom=0.34))
def build_crane(draft):
    """纸鹤：一只白纸折的鹤正展翅扑下（机头朝右下），翅尖带着折痕；身后远处一点暖黄灯光，把翅膀透亮、给轮廓镶一道暖边。"""
    from mathutils import Euler, Vector  # noqa: PLC0415

    sky_gradient(lin("#07090F"), lin("#2B3550"), 0.6, ground=lin("#05060A"))
    paper = P.mat_crane_paper("Paper")
    ob = make_obj("Crane", P.crane_build(wing_up=0.34, wing_sweep=-0.05, neck_up=0.20, tail_up=0.20, wing_bend=0.05), paper,
                  smooth=False, index=1)
    # 侧面略偏前看：翅膀高高举成 V，颈、尾两根尖往上翘，鹤头朝右下一扑
    ob.rotation_euler = Euler((math.radians(8), math.radians(14), math.radians(-20)), "XYZ")
    # 身后的灯：右上远处一点暖光（虚焦），近处一盏把翅膀透亮的暖光
    P.glow_orb("Lamp", (0.62, 2.6, 0.30), 0.045, (1.0, 0.62, 0.26), 40.0, light_w=60.0)
    K.point_light("Back", (0.10, 0.55, 0.28), 14.0, radius=0.10, color=(1.0, 0.66, 0.32))
    K.area_light("Moon", (-1.2, -0.4, 1.6), (0, 0, 0), 30.0, 1.0, color=(0.62, 0.74, 1.0))
    K.area_light("Fill", (0.4, -1.6, -0.3), (0, 0, 0), 4.0, 1.2, color=(0.62, 0.70, 0.95))
    # 几张飘落的碎纸屑
    rng = np.random.default_rng(5)
    for i in range(10):
        p = Vector((rng.uniform(-0.6, 0.6), rng.uniform(-0.2, 0.6), rng.uniform(-0.35, 0.35)))
        if p.length < 0.35:
            continue
        sq = make_obj(f"Bit{i}", K.box_build(0.018, 0.0004, 0.018), paper, loc=tuple(p), index=2, smooth=False)
        sq.rotation_euler = tuple(rng.uniform(0, 6.28, 3))
    K.camera((0.05, -1.50, 0.24), (0.02, 0.0, 0.09), lens=50.0, fstop=4.0, focus=1.48)
    return {"light": "warm"}


@background("crane")
def bg_crane(P_, h, w, rng, k):
    P_.fill_grad("#0D111B", "#0F1520", cloud=0.12)
    K.bg_glow(P_, 0.70, 0.30, 0.42, 0.40, "#5A3A1C", 0.30)
    K.bg_glow(P_, 0.70, 0.30, 0.16, 0.16, "#B2702C", 0.26)
    bg_clouds(P_, rng, k, [(0.62, 0.03, 0.05, 0.60), (0.70, 0.02, 0.30, 0.95)], "#4C5A74", 0.18)
    K.bg_mountains(P_, [(0.90, [(0.15, 0.10, 0.14, 0.12), (0.52, 0.06, 0.16, 0.14), (0.86, 0.11, 0.12, 0.14)], "#151C2C", 0.85, 0.08, 5.0)],
                   rng, k)
    K.bg_mist(P_, 0.86, 0.05, "#6E7C98", 0.12, rng, k)
    K.bg_ink(P_, [(0.02, 0.06, 0.26, 0.18, 0.2), (0.02, 0.96, 0.30, 0.20, -0.2)], 0.45)


@scene("crane_evo", name="千鹤引", samples=128, grade=dict(WARM_GRADE, exposure=1.02, bloom=0.36))
def build_crane_evo(draft):
    """千鹤引：一串纸鹤连成一道弧线飞过夜空，从左下近处一直排到右上远处，像一条引路的白线；尽头一点暖灯。按画面位置摆。"""
    from mathutils import Quaternion, Vector  # noqa: PLC0415

    sky_gradient(lin("#07090F"), lin("#2B3550"), 0.6, ground=lin("#05060A"))
    rng = np.random.default_rng(41)
    S = ScreenCam(lens=40.0)
    key = [(0.08, 0.86, 2.2), (0.22, 0.70, 2.7), (0.38, 0.60, 3.5), (0.53, 0.52, 4.6), (0.66, 0.45, 6.2), (0.76, 0.40, 8.2),
           (0.83, 0.37, 11.0)]
    path = K.catmull([tuple(S(x, y, z)) for x, y, z in key], n=600)
    seg = np.linalg.norm(np.diff(path, axis=0), axis=1)
    sl = np.concatenate([[0.0], np.cumsum(seg)])
    total = sl[-1]

    def at(s):
        p = np.array([np.interp(s, sl, path[:, c]) for c in range(3)])
        q = np.array([np.interp(min(s + 0.05, total), sl, path[:, c]) for c in range(3)])
        return Vector(p), (Vector(q) - Vector(p)).normalized()

    paper = P.mat_crane_paper("Paper", emit=((1.0, 0.86, 0.66), 0.15))
    variants = [P.crane_build(wing_up=wu, wing_sweep=ws, neck_up=0.15, tail_up=0.17, wing_bend=0.04)
                for wu, ws in ((0.26, -0.04), (0.10, 0.02), (0.32, -0.06), (0.18, 0.0))]
    n = 22
    for i in range(n):
        u = i / (n - 1)
        s = 0.35 + (total - 1.0) * u ** 1.15
        p, d = at(s)
        side = d.cross(Vector((0, 0, 1))).normalized()
        p = p + side * rng.normal(0, 0.03 + 0.10 * u) + Vector((0, 0, rng.normal(0, 0.02 + 0.06 * u)))
        q = d.to_track_quat("X", "Z") @ Quaternion((1, 0, 0), rng.uniform(-0.35, 0.35))
        ob = make_obj(f"Crane{i}", variants[i % len(variants)], paper, smooth=False, loc=tuple(p), index=1)
        ob.rotation_mode = "QUATERNION"
        ob.rotation_quaternion = q
    # 尽头的灯
    end = S(0.84, 0.36, 12.0)
    P.glow_orb("Lamp", tuple(end), 0.10, (1.0, 0.62, 0.26), 40.0, light_w=900.0)
    K.area_light("Moon", (-2.0, -0.5, 3.0), tuple(S(0.4, 0.5, 3.0)), 220.0, 1.5, color=(0.62, 0.74, 1.0))
    K.area_light("Fill", (0.6, -0.6, -0.4), tuple(S(0.3, 0.6, 2.0)), 10.0, 1.2, color=(0.62, 0.70, 0.95))
    # 一道淡淡的光带，把鹤串起来（引路的白线）
    pts = [tuple(at(s)[0] + Vector((0, 0, -0.02))) for s in np.linspace(0.1, total - 0.5, 200)]
    make_obj("Trail", K.ribbon_uv(pts, 0.05, ups=[(0, 0, 1)] * len(pts)),
             K.mat_wind("TrailM", strength=0.7, seed=3.0, color=(1.0, 0.88, 0.70)), index=3)
    S.place(lens=40.0, fstop=11.0, focus=2.5)
    return {"light": "warm"}


@background("crane_evo")
def bg_crane_evo(P_, h, w, rng, k):
    P_.fill_grad("#0C111C", "#101624", cloud=0.12)
    K.bg_glow(P_, 0.80, 0.36, 0.40, 0.36, "#5A3A1C", 0.30)
    K.bg_glow(P_, 0.84, 0.36, 0.12, 0.12, "#C07A30", 0.30)
    bg_clouds(P_, rng, k, [(0.22, 0.03, 0.20, 0.75), (0.30, 0.02, 0.05, 0.45), (0.60, 0.025, 0.45, 0.98)], "#4C5A74", 0.18)
    K.bg_mountains(P_, [(0.74, [(0.62, 0.08, 0.14, 0.12), (0.86, 0.12, 0.10, 0.12), (0.98, 0.07, 0.08, 0.10)], "#1E2638", 0.6, 0.10, 6.0),
                        (0.88, [(0.10, 0.12, 0.14, 0.12), (0.45, 0.07, 0.16, 0.14), (0.80, 0.10, 0.12, 0.14)], "#131A28", 0.88, 0.08, 5.0)],
                   rng, k)
    K.bg_mist(P_, 0.78, 0.04, "#7A7E92", 0.14, rng, k)
    K.bg_ink(P_, [(0.02, 0.06, 0.26, 0.18, 0.2), (0.98, 0.04, 0.20, 0.14, -0.4)], 0.45)


# ====================================================================== 山印


EARTH_GRADE = dict(exposure=1.0, shadow="#1C1A24", high="#FFE6C0", sat=0.98, bloom=0.30, contrast=1.06)


def ground_plane(name, mat, size=14.0, loc=(0, 0, 0), index=0, subdiv=1):
    def build(bm):
        import bmesh  # noqa: PLC0415

        bmesh.ops.create_grid(bm, x_segments=8 * subdiv, y_segments=8 * subdiv, size=size / 2)

    return make_obj(name, build, mat, loc=loc, index=index, smooth=False)


@scene("seal", name="山印", samples=128, grade=EARTH_GRADE, fog=(9.0, 16.0))
def build_seal(draft):
    """山印：一方巨大的青石印从天上压下（印身微微前倾，露出印面：阳文“山”字沾着朱砂），印钮是三座山峰；
    底下的地面已经裂开，裂缝从印下往外放射，碎石往上迸。镜头贴着地面往上看。"""
    from mathutils import Vector  # noqa: PLC0415

    sky_gradient(lin("#07080C"), lin("#3A3226"), 0.7, ground=lin("#060505"))
    rng = np.random.default_rng(17)
    face_img = K.np_image("seal_face", P.seal_shan(1024))
    stone = P.mat_stone("SealStone", color=(0.13, 0.15, 0.13), scale=3.5, cavity=1.0, bump=1.0, bump_dist=0.04)
    P.seal_block("Seal", size=2.0, height=2.1, stone_m=stone,
                 face_m=P.mat_seal_face("SealFace", face_img, stone=(0.05, 0.055, 0.05), paste=(0.40, 0.03, 0.02)),
                 loc=(0.0, 0.3, 1.85), rot=(math.radians(-30), math.radians(5), math.radians(-17)), index=1)
    crack = K.np_image("crack_seal", P.crack_texture(2048, rng, n_main=11, reach=0.40, width=3.5))
    ground_plane("Ground", P.mat_ground_crack("GroundM", crack, base=(0.011, 0.010, 0.009), glow=((1.0, 0.45, 0.15), 3.2),
                                              uv_from_object=(14.0, 14.0), fade=4.5, spec=0.08), size=14.0, loc=(0, 0.3, 0), index=0)
    # 迸起的碎石
    rock = P.mat_stone("Debris", color=(0.09, 0.08, 0.07), scale=8.0)
    for i in range(46):
        a = rng.uniform(0, 2 * math.pi)
        r = rng.uniform(0.6, 3.2)
        p = Vector((r * math.cos(a), 0.3 + r * math.sin(a) * 0.8, abs(rng.normal(0, 0.35)) * (1.2 - r / 4)))
        sz = rng.uniform(0.03, 0.12) * (1.4 - r / 4)
        ob = make_obj(f"Debris{i}", K.ico_cloud([(0, 0, 0)], [sz], 1), rock, loc=tuple(p), index=2, smooth=False)
        ob.scale = tuple(rng.uniform(0.6, 1.4, 3))
        ob.rotation_euler = tuple(rng.uniform(0, 6.28, 3))
    K.area_light("Moon", (-4.0, 6.0, 7.0), (0, 0, 1.5), 900.0, 3.0, color=(0.66, 0.76, 1.0))
    K.area_light("Rim", (5.0, 5.0, 3.0), (0, 0, 2.0), 300.0, 2.0, color=(0.62, 0.72, 1.0))
    K.area_light("Top", (-1.0, -2.0, 6.0), (0, 0.3, 2.5), 110.0, 2.0, color=(0.62, 0.70, 0.95))
    K.area_light("Under", (0.0, -1.5, 0.15), (0, 0.3, 1.0), 60.0, 3.0, size_y=0.4, color=(1.0, 0.55, 0.25))
    K.area_light("Front", (-2.0, -7.0, 2.6), (0, 0, 1.9), 40.0, 4.0, color=(0.62, 0.70, 0.95))
    K.camera((0.35, -5.9, 0.42), (0.0, 0.3, 1.62), lens=34.0, fstop=8.0, focus=5.9)
    return {"light": "earth"}


@background("seal")
def bg_seal(P_, h, w, rng, k):
    P_.fill_grad("#0D0F16", "#1A1714", cloud=0.12)
    K.bg_glow(P_, 0.50, 0.70, 0.55, 0.30, "#5E4026", 0.30)
    K.bg_mountains(P_, [(0.70, [(0.12, 0.12, 0.12, 0.12), (0.34, 0.07, 0.12, 0.10), (0.80, 0.14, 0.12, 0.14), (0.97, 0.08, 0.10, 0.10)],
                         "#2A2622", 0.7, 0.10, 6.0, "#7C6A56")], rng, k)
    bg_clouds(P_, rng, k, [(0.18, 0.03, 0.25, 0.80), (0.26, 0.02, 0.50, 0.95)], "#5A5248", 0.18)
    K.bg_mist(P_, 0.70, 0.04, "#8C7A64", 0.18, rng, k)
    K.bg_ink(P_, [(0.02, 0.06, 0.26, 0.18, 0.2), (0.98, 0.08, 0.24, 0.18, -0.4)], 0.45)


@scene("seal_evo", name="镇岳", samples=128, grade=EARTH_GRADE, fog=(14.0, 26.0))
def build_seal_evo(draft):
    """镇岳：一整座山岳形的巨岩砸进地里（山尖朝上、底下埋进土里），四周地裂成网，裂缝里透出金红的光；碎石迸起。
    镜头斜着往下看，看得到整张裂网。"""
    sky_gradient(lin("#07080C"), lin("#3A3226"), 0.6, ground=lin("#060505"))
    rng = np.random.default_rng(29)
    stone = P.mat_stone("PeakStone", color=(0.12, 0.115, 0.11), scale=1.2, cavity=0.9, bump=1.5, moss=0.5)
    P.rock_mesh("Peak", stone, scale=(1.55, 1.3, 2.4), loc=(0, 0, 1.0), rot=(math.radians(8), math.radians(-10), 0.3), peak=0.70,
                crag=0.55, crag_size=0.9, fine=0.12, index=1, flat_bottom=-0.9, subdiv=6, ridges=9, ridge_amp=0.55, seed=4)
    P.rock_mesh("PeakB", stone, scale=(0.75, 0.7, 1.2), loc=(1.25, 0.4, 0.4), rot=(0.2, -0.3, 0.5), peak=0.6, crag=0.35, index=1,
                subdiv=4)
    P.rock_mesh("PeakC", stone, scale=(0.6, 0.6, 0.9), loc=(-1.2, 0.2, 0.25), rot=(-0.2, 0.25, 0.2), peak=0.55, crag=0.3, index=1,
                subdiv=4)
    crack = K.np_image("crack_evo", P.crack_texture(2048, rng, n_main=16, reach=0.47, branch=0.06, width=2.2))
    ground_plane("Ground", P.mat_ground_crack("GroundM", crack, base=(0.032, 0.028, 0.024), glow=((1.0, 0.55, 0.18), 6.0),
                                              uv_from_object=(18.0, 18.0), fade=4.2), size=18.0, index=0)
    rock = P.mat_stone("Debris", color=(0.09, 0.08, 0.07), scale=8.0)
    from mathutils import Vector  # noqa: PLC0415

    for i in range(60):
        a = rng.uniform(0, 2 * math.pi)
        r = rng.uniform(1.6, 4.5)
        p = Vector((r * math.cos(a), r * math.sin(a), abs(rng.normal(0, 0.5)) * (1.3 - r / 5)))
        sz = rng.uniform(0.04, 0.16) * (1.5 - r / 5)
        ob = make_obj(f"Debris{i}", K.ico_cloud([(0, 0, 0)], [sz], 1), rock, loc=tuple(p), index=2, smooth=False)
        ob.scale = tuple(rng.uniform(0.6, 1.4, 3))
        ob.rotation_euler = tuple(rng.uniform(0, 6.28, 3))
    K.point_light("CoreGlow", (0.0, -1.2, 0.25), 300.0, radius=0.6, color=(1.0, 0.52, 0.18))
    K.point_light("CoreGlow2", (0.8, 1.5, 0.25), 180.0, radius=0.6, color=(1.0, 0.52, 0.18))
    K.area_light("Moon", (-6.0, 6.0, 9.0), (0, 0, 1.5), 1600.0, 4.0, color=(0.66, 0.76, 1.0))
    K.area_light("Front", (-3.0, -8.0, 5.0), (0, 0, 1.2), 160.0, 5.0, color=(0.62, 0.70, 0.95))
    K.camera((1.2, -9.0, 4.4), (0.0, 0.2, 1.05), lens=34.0, fstop=11.0, focus=9.5)
    return {"light": "earth"}


@background("seal_evo")
def bg_seal_evo(P_, h, w, rng, k):
    P_.fill_grad("#0C0E14", "#1C1814", cloud=0.12)
    K.bg_glow(P_, 0.50, 0.55, 0.55, 0.40, "#6A4424", 0.32)
    K.bg_mountains(P_, [(0.36, [(0.10, 0.10, 0.12, 0.10), (0.30, 0.06, 0.10, 0.10), (0.78, 0.12, 0.12, 0.14), (0.95, 0.07, 0.10, 0.10)],
                         "#2A2622", 0.7, 0.10, 6.0, "#7C6A56")], rng, k)
    bg_clouds(P_, rng, k, [(0.14, 0.025, 0.25, 0.78), (0.22, 0.02, 0.45, 0.95)], "#5A5248", 0.16)
    K.bg_mist(P_, 0.38, 0.04, "#8C7A64", 0.18, rng, k)
    K.bg_ink(P_, [(0.02, 0.06, 0.26, 0.18, 0.2), (0.98, 0.08, 0.24, 0.18, -0.4)], 0.45)


# ====================================================================== 霜铃


def eave_corner(name, beam_pts, *, wood=None, tile=None, snow=None, ice=None, rng=None, roof_dir=(-0.3, 1.0, 0.45), roof_len=0.9,
                index=2):
    """飞檐一角（从下面看）：一根角梁沿 beam_pts（末端上翘）；梁后是一片厚的屋面板（暗木），板下一排椽子伸出来；
    檐口一排瓦当，檐口上沿一道积雪（只在轮廓上看得到），垂着冰凌。"""
    from mathutils import Vector  # noqa: PLC0415

    rng = rng or np.random.default_rng(1)
    wood = wood or P.mat_wood_plain(f"{name}_Wood", color=(0.05, 0.032, 0.022))
    tile = tile or P.mat_stone(f"{name}_Tile", color=(0.032, 0.035, 0.040), rough=0.72, scale=12.0, cavity=0.8, bump=0.4)
    snow = snow or K.mat_snow(f"{name}_Snow")
    ice = ice or K.mat_ice(f"{name}_Ice")
    pts = K.catmull(beam_pts, n=80)
    make_obj(f"{name}_Beam", K.tube_uv([tuple(p) for p in pts], 0.035, sides=4, flat=0.8, roll=math.pi / 4), wood, smooth=False,
             index=index, bevel=(0.004, 1))
    rd = Vector(roof_dir).normalized()
    edge = [Vector(p) for p in pts]

    def slab(bm):
        rows = []
        for p in edge:
            rows.append([bm.verts.new(tuple(p + Vector((0, 0, 0.03)) + rd * (roof_len * t))) for t in (0.0, 0.5, 1.0)])
            rows.append([bm.verts.new(tuple(p + Vector((0, 0, 0.075)) + rd * (roof_len * t))) for t in (0.0, 0.5, 1.0)])
        n = len(edge)
        for i in range(n - 1):
            lo0, hi0, lo1, hi1 = rows[2 * i], rows[2 * i + 1], rows[2 * i + 2], rows[2 * i + 3]
            for j in range(2):
                bm.faces.new((lo0[j], lo1[j], lo1[j + 1], lo0[j + 1]))
                bm.faces.new((hi0[j], hi0[j + 1], hi1[j + 1], hi1[j]))
            bm.faces.new((lo0[0], hi0[0], hi1[0], lo1[0]))

    make_obj(f"{name}_Slab", slab, wood, smooth=False, index=index)
    for i in range(1, len(edge) - 1, 3):  # 椽子：板下一排圆木，伸出檐口一点
        p = edge[i]
        a, b = p + Vector((0, 0, 0.012)) - rd * 0.03, p + Vector((0, 0, 0.012)) + rd * roof_len * 0.8
        make_obj(f"{name}_Rafter{i}", K.tube_uv([tuple(a), tuple(b)], 0.012, sides=10), wood, index=index)
        disc = K.lathe_uv([(0.0, 0.0), (0.020, 0.0), (0.020, 0.010), (0.0, 0.010)], segments=16, cap_top=True)
        ob = make_obj(f"{name}_End{i}", disc, tile, loc=tuple(p + Vector((0, 0, 0.09)) - rd * 0.02), index=index)
        ob.rotation_mode = "QUATERNION"
        ob.rotation_quaternion = (-rd).to_track_quat("Z", "Y")
        if rng.random() < 0.7:
            L = rng.uniform(0.03, 0.12)
            make_obj(f"{name}_Icicle{i}", K.lathe_uv([(0.0, -L), (0.003, -L * 0.8), (0.008, -L * 0.4), (0.012, -0.004), (0.0, 0.0)],
                                                     segments=8), ice, loc=tuple(p - rd * 0.01 + Vector((0, 0, 0.02))), index=3)
    snow_line = [tuple(p + Vector((0, 0, 0.105)) + rd * 0.02) for p in edge]
    make_obj(f"{name}_SnowEdge", K.tube_uv(snow_line, 0.024, sides=10, flat=0.6), snow, index=index)
    return pts


def wind_bell(name, *, loc, rot, scale=1.0, frost=1.0, index=1):
    """霜铃那只青铜风铃（铃口朝下，原点在铃口中心）：六瓣的铃口、两道箍、顶上铜环；铃舌荡向 +X，杆尾垂一束红穗。
    铃身结冰花（frost=0 不结）。返回 (父物体, 铃高)。"""
    from mathutils import Vector  # noqa: PLC0415

    H = 0.26
    outer = [(0.095, 0.0), (0.098, 0.012), (0.090, 0.03)]
    for z in np.linspace(0.05, H - 0.04, 30):
        t = z / H
        r = 0.088 - 0.030 * t ** 1.4 + 0.005 * math.exp(-((z - 0.06) / 0.006) ** 2) + 0.004 * math.exp(-((z - 0.19) / 0.006) ** 2)
        outer.append((r, z))
    for a in np.linspace(0, 1, 10)[1:]:
        th = a * math.pi / 2
        outer.append((0.056 * math.cos(th) ** 0.9, H - 0.04 + 0.05 * math.sin(th)))
    outer[-1] = (0.0, H + 0.01)
    inner = [(0.0, H - 0.01), (0.045, H - 0.03), (0.070, 0.10), (0.084, 0.004)]

    def lobes(th, z, i):
        return 1.0 + (0.035 * (0.5 + 0.5 * math.cos(6 * th)) * (1 - min(z / 0.03, 1.0)) if z < 0.03 else 0.0)

    fern = K.frost_ferns(1024, 512, np.random.default_rng(8), n_seeds=60, v_bias=0.45, max_len=150)
    bronze = P.mat_frosted_bronze(f"{name}Bronze", K.np_image(f"{name}_fern", fern), H, base=(0.36, 0.24, 0.11), patina=(0.09, 0.24, 0.20),
                                  patina_amt=1.0, frost=frost)
    bell_root = K._bpy().data.objects.new(f"{name}Root", None)
    K.link(bell_root)
    bell_root.location = loc
    bell_root.rotation_euler = rot
    bell_root.scale = (scale, scale, scale)
    make_obj(name, K.lathe_uv(outer + inner, segments=180, radial=lobes), bronze, parent=bell_root, index=index)
    make_obj(f"{name}Loop", K.torus_build(0.020, 0.005, 40, 10), bronze, parent=bell_root, loc=(0, 0, H + 0.03),
             rot=(math.radians(90), 0, 0), index=index)
    # 铃舌（荡向 +X）：一根铜杆，杆头一颗铜锤正好敲到铃口；杆尾垂一束红穗
    sw = math.radians(20)
    top = Vector((0, 0, H - 0.02))
    d = Vector((math.sin(sw), 0, -math.cos(sw)))
    rod = [tuple(top + d * t) for t in np.linspace(0, 0.30, 20)]
    make_obj(f"{name}Tongue", K.tube_uv(rod, 0.0032, sides=8), bronze, parent=bell_root, index=index)
    make_obj(f"{name}Striker", K.ico_cloud([(0, 0, 0)], [0.016], 2), bronze, parent=bell_root, loc=tuple(top + d * 0.235), index=index)
    silk = P.mat_silk(f"{name}TasselSilk", (0.50, 0.035, 0.025))
    end = top + d * 0.30
    make_obj(f"{name}TasselKnot", K.ico_cloud([(0, 0, 0)], [0.011], 2), silk, parent=bell_root, loc=tuple(end), index=index)
    trng = np.random.default_rng(5)

    def strands(bm):
        import bmesh  # noqa: PLC0415

        bpy = K._bpy()
        for _ in range(70):
            a = trng.uniform(0, 2 * math.pi)
            rr = 0.006 * math.sqrt(trng.uniform(0.1, 1))
            Ls = trng.uniform(0.075, 0.10)
            pts = [(end.x + rr * math.cos(a) * (1 + 1.2 * t) - 0.012 * t * t, end.y + rr * math.sin(a) * (1 + 1.2 * t),
                    end.z - 0.006 - Ls * t) for t in np.linspace(0, 1, 8)]
            tmp = bmesh.new()
            K.tube_uv(pts, 0.0009, sides=4, caps=False)(tmp)
            me = bpy.data.meshes.new("tmp")
            tmp.to_mesh(me)
            tmp.free()
            bm.from_mesh(me)
            bpy.data.meshes.remove(me)

    make_obj(f"{name}TasselStrands", strands, silk, parent=bell_root, index=index)
    return bell_root, H


@scene("bell", name="霜铃", samples=128, grade=COLD_GRADE)
def build_bell(draft):
    """霜铃：夜里檐角下挂着一只青铜风铃（铃身结着冰花、泛铜青），铃舌正一荡、垂一束红穗，铃口漫出一圈白霜寒波；檐上积雪、垂冰凌。"""
    from mathutils import Vector  # noqa: PLC0415

    sky_gradient(lin("#05080F"), lin("#2E4466"), 0.8, ground=lin("#04060A"))
    rng = np.random.default_rng(37)
    # 飞檐一角：从左后伸到画面上方，末端上翘；铃挂在梁头下
    beam = [(-1.3, 0.9, 0.62), (-0.7, 0.45, 0.56), (-0.2, 0.12, 0.53), (0.08, -0.02, 0.55), (0.20, -0.08, 0.64)]
    eave_corner("Eave", beam, rng=rng, roof_dir=(-0.45, 1.0, 0.42), roof_len=0.8)
    tip = Vector((0.12, -0.04, 0.575))
    iron = K.mat_iron("Iron")
    make_obj("Hook", K.tube_uv([tuple(tip), tuple(tip + Vector((0.0, 0.0, -0.06))), tuple(tip + Vector((0.0, 0.0, -0.09)))], 0.005,
                               sides=8), iron, index=1)
    bell_root, _ = wind_bell("Bell", loc=tuple(tip + Vector((0.0, 0.0, -0.10 - 0.26 - 0.012))),
                             rot=(math.radians(6), math.radians(-9), 0.0))
    # 寒波：从铃口漫出，跟着铃身一起斜
    mouth = bell_root.matrix_world.translation if False else Vector(bell_root.location)
    P.frost_wave("Wave", tuple(mouth + Vector((0.0, 0.0, 0.004))), 0.34, strength=0.65, seed=2.0, skirt_r0=0.10)
    ice = K.mat_ice("Ice2")
    for k_ in range(70):
        a = rng.uniform(0, 2 * math.pi)
        rr = 0.34 * rng.uniform(0.6, 1.25)
        p = mouth + Vector((rr * math.cos(a), rr * math.sin(a), rng.uniform(-0.05, 0.12) * rng.random()))
        L = rng.uniform(0.006, 0.016)
        ob = make_obj(f"Flake{k_}", P.crystal_build(L, L * 0.2), ice, loc=tuple(p), index=3, smooth=False)
        ob.rotation_mode = "QUATERNION"
        ob.rotation_quaternion = Vector(rng.normal(0, 1, 3)).normalized().to_track_quat("Z", "Y")
    K.area_light("Moon", (-1.4, 1.3, 1.6), (0.1, 0, 0.3), 70.0, 1.0, color=(0.66, 0.78, 1.0))
    K.area_light("Rim", (1.2, 1.0, 0.6), (0.1, 0, 0.3), 35.0, 0.8, color=(0.6, 0.72, 1.0))
    K.area_light("Front", (-0.4, -1.5, 0.6), (0.1, 0, 0.3), 7.0, 1.2, color=(0.62, 0.72, 1.0))
    K.area_light("Warm", (0.9, -1.0, 0.1), (0.1, 0, 0.3), 1.5, 0.6, color=(1.0, 0.70, 0.45))
    K.camera((0.32, -1.18, 0.22), (0.07, 0.0, 0.31), lens=46.0, fstop=4.5, focus=1.20)
    return {"light": "cold"}


@background("bell")
def bg_bell(P_, h, w, rng, k):
    P_.fill_grad("#0B1222", "#142034", cloud=0.12)
    K.bg_glow(P_, 0.55, 0.55, 0.45, 0.40, "#4C6890", 0.30)
    K.bg_moon(P_, 0.80, 0.30, 0.05, rng, k, color="#E6ECF4", halo="#7890B6", a=0.6, halo_a=0.30)
    bg_clouds(P_, rng, k, [(0.36, 0.025, 0.45, 0.98), (0.44, 0.02, 0.60, 0.98)], "#5B7194", 0.18)
    K.bg_mountains(P_, [(0.86, [(0.10, 0.12, 0.12, 0.10), (0.40, 0.08, 0.14, 0.12), (0.78, 0.14, 0.14, 0.14)], "#1B2840", 0.8, 0.08, 5.0)],
                   rng, k)
    K.bg_mist(P_, 0.84, 0.05, "#8FB0D0", 0.16, rng, k)
    K.bg_ink(P_, [(0.98, 0.08, 0.22, 0.16, -0.4), (0.02, 0.96, 0.26, 0.18, 0.2)], 0.45)


# ====================================================================== 不夜城


def mat_house(name):
    """小城的房子：墙是暗的灰泥，窗（Brick 纹的砖块当窗格）透出暖光，亮暗按每座房子的随机数（面属性 rnd）变；屋顶另给材质。"""
    M = K.Mat(name)
    m = M.math
    at = M.n("ShaderNodeAttribute", _attribute_type="GEOMETRY", _attribute_name="rnd")
    rnd = at.outputs["Fac"]
    oc = M.coord("Object")
    br = M.n("ShaderNodeTexBrick", Scale=1.0, Mortar_Size=0.011, Bias=0.0, Brick_Width=0.030, Row_Height=0.026, _offset=0.5, _squash=1.0)
    M.l(oc, br.inputs["Vector"])
    win = m("SUBTRACT", 1.0, br.outputs["Fac"], clamp=True)
    noise = M.noise(oc, scale=60.0, detail=2.0)
    lit = m("MULTIPLY", win, m("GREATER_THAN", m("ADD", noise.outputs["Fac"], m("MULTIPLY", rnd, 0.4)), 0.58))
    col = (0.05, 0.042, 0.036, 1.0)
    bsdf = M.principled(Base_Color=col, Roughness=0.9)
    bsdf.inputs["Emission Color"].default_value = (1.0, 0.55, 0.20, 1.0)
    M.l(m("MULTIPLY", lit, m("ADD", m("MULTIPLY", rnd, 9.0), 3.0)), bsdf.inputs["Emission Strength"])
    return M.surface(bsdf.outputs[0])


def city_build(houses, roof=False):
    """所有房子合成一个网格：houses = [(x, y, 宽, 深, 高, 角度, rnd)]；roof=True 时出两坡屋顶（略出檐、脊微翘）。"""
    def build(bm):
        import bmesh  # noqa: PLC0415

        lay = bm.faces.layers.float.new("rnd")
        for x, y, w_, d_, h_, ang, rnd in houses:
            ca, sa = math.cos(ang), math.sin(ang)

            def P_(px, py, pz):
                return bm.verts.new((x + px * ca - py * sa, y + px * sa + py * ca, pz))

            if not roof:
                b = [P_(sx * w_ / 2, sy * d_ / 2, 0.0) for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
                t = [P_(sx * w_ / 2, sy * d_ / 2, h_) for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
                fs = [bm.faces.new((b[i], b[(i + 1) % 4], t[(i + 1) % 4], t[i])) for i in range(4)] + [bm.faces.new(t)]
            else:
                ow, od, rh = w_ / 2 * 1.18, d_ / 2 * 1.25, h_ * 0.55
                e = [P_(sx * ow, sy * od, h_ - 0.004) for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
                r0, r1 = P_(-ow * 1.04, 0.0, h_ + rh), P_(ow * 1.04, 0.0, h_ + rh)
                fs = [bm.faces.new((e[0], e[1], r1, r0)), bm.faces.new((e[2], e[3], r0, r1)), bm.faces.new((e[1], e[2], r1)),
                      bm.faces.new((e[3], e[0], r0))]
            for f in fs:
                f[lay] = rnd
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)

    return build


@scene("lamp_evo", name="不夜城", samples=128, grade=dict(WARM_GRADE, exposure=1.0, bloom=0.40, sat=1.04), fog=(7.5, 15.0))
def build_lamp_evo(draft):
    """不夜城：俯看夜里一座圆城，城头一圈十盏大灯笼连成火环；城里家家窗亮，十字街上灯火，正中一座鼓楼；火光把城上的夜空映亮。"""
    from mathutils import Vector  # noqa: PLC0415

    K.set_world(lin("#0A0C14"), 0.6)
    rng = np.random.default_rng(53)
    Rw = 2.0
    ground_m = P.mat_stone("Ground", color=(0.035, 0.032, 0.030), scale=1.5, cavity=0.3, bump=0.3)
    ground_plane("Ground", ground_m, size=30.0, index=0)
    wall_m = P.mat_stone("Wall", color=(0.12, 0.10, 0.085), scale=6.0, cavity=0.7, bump=0.5)
    make_obj("Wall", K.lathe_uv([(Rw - 0.14, 0.0), (Rw + 0.02, 0.0), (Rw, 0.26), (Rw - 0.12, 0.26), (Rw - 0.14, 0.0)], segments=240), wall_m,
             index=1, smooth=False)
    # 垛口
    merl = []
    for i in range(120):
        a = 2 * math.pi * i / 120
        merl.append((Rw - 0.005, a))

    def merlons(bm):
        import bmesh  # noqa: PLC0415

        for r, a in merl:
            res = bmesh.ops.create_cube(bm, size=1.0)
            bmesh.ops.scale(bm, vec=(0.05, 0.03, 0.05), verts=res["verts"])
            bmesh.ops.rotate(bm, cent=(0, 0, 0), matrix=__import__("mathutils").Matrix.Rotation(a, 3, "Z"), verts=res["verts"])
            bmesh.ops.translate(bm, vec=(r * math.cos(a), r * math.sin(a), 0.285), verts=res["verts"])

    make_obj("Merlons", merlons, wall_m, index=1, smooth=False)
    # 房子
    houses = []
    for gx in np.arange(-Rw + 0.2, Rw - 0.15, 0.20):
        for gy in np.arange(-Rw + 0.2, Rw - 0.15, 0.20):
            x, y = gx + rng.uniform(-0.03, 0.03), gy + rng.uniform(-0.03, 0.03)
            r = math.hypot(x, y)
            if r > Rw - 0.32 or r < 0.42 or abs(x) < 0.13 or abs(y) < 0.13:
                continue
            houses.append((x, y, rng.uniform(0.11, 0.17), rng.uniform(0.09, 0.14), rng.uniform(0.06, 0.12),
                           (math.pi / 2) * rng.integers(0, 2) + rng.normal(0, 0.03), rng.random()))
    make_obj("Houses", city_build(houses), mat_house("HouseM"), index=1, smooth=False)
    roof_m = P.mat_stone("Roof", color=(0.045, 0.040, 0.040), rough=0.6, scale=20.0, cavity=0.5, bump=0.3)
    make_obj("Roofs", city_build(houses, roof=True), roof_m, index=1, smooth=False)
    # 鼓楼：两层台 + 两重屋顶
    tower = [(0, 0, 0.42, 0.42, 0.20, 0.0, 0.9), (0, 0, 0.30, 0.30, 0.42, 0.0, 1.0)]
    make_obj("Tower", city_build([tower[0]]), mat_house("TowerM"), index=1, smooth=False)
    make_obj("TowerTop", city_build([tower[1]]), mat_house("TowerM2"), index=1, smooth=False)
    make_obj("TowerRoof", city_build([(0, 0, 0.36, 0.36, 0.42, 0.0, 1.0)], roof=True), roof_m, index=1, smooth=False)
    make_obj("TowerRoof0", city_build([(0, 0, 0.50, 0.50, 0.20, 0.0, 1.0)], roof=True), roof_m, index=1, smooth=False)
    # 十字街上的灯火（地上一道暖光）
    street = P.mat_emit("Street", (1.0, 0.55, 0.20), 2.2)
    for ang in (0.0, math.pi / 2):
        ob = make_obj(f"Street{ang:.1f}", K.box_build(2 * Rw - 0.3, 0.06, 0.004), street, rot=(0, 0, ang), loc=(0, 0, 0.003), index=1)
        _ = ob
    # 城头十盏灯笼 + 连成环的火光
    lant = K.mat_lantern_paper("LanternPaper")
    for i in range(10):
        a = 2 * math.pi * i / 10 + 0.15
        p = Vector(((Rw - 0.06) * math.cos(a), (Rw - 0.06) * math.sin(a), 0.42))
        make_obj(f"Lantern{i}", K.lathe_uv([(0.0, -0.07), (0.045, -0.055), (0.062, 0.0), (0.045, 0.055), (0.0, 0.07)], segments=24),
                 lant, loc=tuple(p), index=4)
        K.point_light(f"LanternL{i}", tuple(p), 9.0, radius=0.04, color=(1.0, 0.52, 0.20))
        make_obj(f"Post{i}", K.tube_uv([tuple(p - Vector((0, 0, 0.14))), tuple(p - Vector((0, 0, 0.06)))], 0.008, sides=6), wall_m, index=1)
    ring = [((Rw - 0.06) * math.cos(a), (Rw - 0.06) * math.sin(a), 0.42 + 0.02 * math.sin(10 * a)) for a in np.linspace(0, 2 * math.pi, 400)]
    make_obj("FireRing", K.tube_uv(ring, 0.018, sides=10), P.mat_glow_shell("FireRingM", (1.0, 0.55, 0.18), strength=6.0, power=1.4),
             index=4)
    K.point_light("CityGlow", (0, 0, 1.0), 220.0, radius=1.5, color=(1.0, 0.55, 0.22))
    K.area_light("Moon", (-6.0, 8.0, 10.0), (0, 0, 0), 500.0, 4.0, color=(0.60, 0.70, 1.0))
    K.camera((0.40, -4.25, 1.95), (0.0, 0.42, 0.08), lens=30.0, fstop=11.0, focus=4.6)
    return {"light": "warm"}


@background("lamp_evo")
def bg_lamp_evo(P_, h, w, rng, k):
    P_.fill_grad("#1A1214", "#0E0B0E", cloud=0.12)
    K.bg_glow(P_, 0.50, 0.30, 0.70, 0.40, "#7A4218", 0.45)
    K.bg_glow(P_, 0.50, 0.32, 0.36, 0.18, "#C46E22", 0.30)
    bg_clouds(P_, rng, k, [(0.10, 0.03, 0.15, 0.85), (0.18, 0.025, 0.30, 0.95), (0.25, 0.02, 0.05, 0.55)], "#A0663A", 0.22)
    K.bg_mountains(P_, [(0.33, [(0.10, 0.08, 0.12, 0.10), (0.30, 0.05, 0.10, 0.10), (0.75, 0.09, 0.12, 0.14), (0.95, 0.06, 0.10, 0.10)],
                         "#1C1416", 0.8, 0.10, 5.0, "#8A5A3A")], rng, k)
    K.bg_ink(P_, [(0.02, 0.06, 0.26, 0.18, 0.2), (0.98, 0.08, 0.24, 0.18, -0.4)], 0.45)


# ====================================================================== 寒山钟（样张的水墨底加江、客船）


def bg_boat(P_, cx, cy, size, rng, k, color="#0A0E16", lamp="#E09A48"):
    """江上一只客船的剪影：弯弯的船身、中间一顶篷、船尾一支橹，篷前挂一点暖灯；水面上一道淡倒影。"""
    h, w = P_.h, P_.w
    X, Y = P_.X, P_.Y
    s = size * w
    u = (X - cx * w) / s
    v = (Y - cy * h) / s
    hull = (np.abs(u) < 1.1) & (v > -0.03 - 0.13 * u ** 2) & (v < 0.06 - 0.08 * u ** 2)
    cabin = (np.abs(u + 0.05) < 0.40) & (v < -0.02) & (v > -0.24 + 0.55 * (u + 0.05) ** 2)
    oar = (np.abs((u - 0.80) - (v + 0.05) * 1.3) < 0.022) & (v > -0.30) & (v < 0.22)
    m = (hull | cabin | oar).astype(float)
    m = K._blur(m, 0.7 * k)
    P_.over(m * 0.92, color)
    lx, ly = cx * w + 0.44 * s, cy * h - 0.10 * s
    P_.light(np.exp(-(((X - lx) / (0.05 * s + 1.5 * k)) ** 2 + ((Y - ly) / (0.05 * s + 1.5 * k)) ** 2)) * 0.9, lamp)
    P_.light(np.exp(-(((X - lx) / (0.35 * s)) ** 2 + ((Y - ly) / (0.30 * s)) ** 2)) * 0.25, lamp)
    refl = np.exp(-((X - lx) / (0.06 * s)) ** 2) * K._ss(0.0, 0.15 * s, Y - (cy * h + 0.12 * s)) * np.exp(-np.maximum(Y - cy * h, 0) / (0.9 * s))
    P_.light(refl * (0.5 + 0.5 * K._ss(0.3, 0.8, K._noise(rng, (h, w), (6 * k, 1.0 * k)))) * 0.30, lamp)


@background("bell_evo")
def bg_bell_evo(P_, h, w, rng, k):
    """寒山钟：月下寒山三层，山脚一道江，江上一只客船（夜半钟声到客船）。"""
    P_.fill_grad("#0E1626", "#152035", cloud=0.12)
    P_.light(P_.blob(0.50 * w, 0.48 * h, 0.46 * w, 0.40 * h, rough=0.45, rim=0.2, soft=0.9) * 0.34, "#5C7898")
    P_.light(P_.blob(0.52 * w, 0.42 * h, 0.24 * w, 0.24 * h, rough=0.4, rim=0.1, soft=0.95) * 0.22, "#9DB6D2")
    K.bg_mountains(P_, [
        (0.58, [(0.10, 0.15, 0.12, 0.10), (0.24, 0.21, 0.10, 0.14), (0.47, 0.11, 0.14, 0.12), (0.80, 0.23, 0.14, 0.12),
                (0.95, 0.16, 0.10, 0.12)], "#2F425A", 0.62, 0.11, 7.0),
        (0.645, [(0.02, 0.13, 0.10, 0.14), (0.30, 0.10, 0.16, 0.12), (0.62, 0.15, 0.12, 0.16), (0.88, 0.10, 0.12, 0.10)],
         "#1F2D44", 0.78, 0.09, 6.0),
    ], rng, k)
    K.bg_river(P_, 0.655, 1.0, rng, k, color="#1A2840", glint="#A8C0DE", a=0.85, glint_x=0.30, glint_a=0.30)
    bg_boat(P_, 0.85, 0.705, 0.050, rng, k)
    K.bg_mist(P_, 0.66, 0.025, "#8FB0D0", 0.22, rng, k)
    for cx, cy, rx, ry, ang in ((0.02, 0.08, 0.24, 0.18, 0.2), (0.98, 0.10, 0.22, 0.18, -0.4)):
        P_.darken(P_.blob(cx * w, cy * h, rx * w, ry * h, ang=ang, rough=0.6, rim=0.5, soft=0.5), 0.45)


# ====================================================================== 铜钱剑


def coin_sword(name, *, L=0.62, r=0.026, coin_m=None, big_m=None, cord_m=None, loc=(0, 0, 0), rot=(0, 0, 0), index=1, rng=None):
    """铜钱剑（沿 +X，剑格在原点；钱面朝 -Y 对着镜头）：剑身两列铜钱交错叠压，往剑尖收成一列、越来越小；
    剑脊上七枚大钱排成北斗；红绳沿两边穿钱、隔几枚绕一道；剑格是横着的几枚钱；柄缠红绳，剑首一枚钱，下垂红穗。"""
    from mathutils import Euler  # noqa: PLC0415

    bpy = K._bpy()
    rng = rng or np.random.default_rng(2)
    root = bpy.data.objects.new(name, None)
    K.link(root)
    root.location, root.rotation_euler = loc, rot
    small = P.coin_build(r=r)
    tip_coin = P.coin_build(r=r * 0.8)

    def put(build, mat, x, z, y, tilt=0.0, nm="c", spin=None):
        ob = make_obj(f"{name}_{nm}", build, mat, parent=root, loc=(x, y, z), index=index, smooth=False)
        ob.rotation_mode = "ZXY"  # 先绕钱面法线转（方孔的朝向），再立起来朝镜头，最后微微侧一点
        ob.rotation_euler = Euler((math.radians(90) + tilt, rng.uniform(-0.12, 0.12),
                                   rng.uniform(0, 1.57) if spin is None else spin), "ZXY")
        return ob

    step = r * 1.15
    xs = np.arange(0.03, L * 0.82, step)
    for i, x in enumerate(xs):
        t = x / L
        half = r * 0.78 * (1 - 0.35 * t)
        for sgn in (-1, 1):
            put(small, coin_m, x + (step / 2 if sgn > 0 else 0), sgn * half, -0.0015 * sgn + 0.002 * (i % 2), tilt=0.06 * sgn, nm=f"c{i}_{sgn}")
    for i, x in enumerate(np.arange(L * 0.82, L * 0.97, r * 1.1)):
        put(tip_coin, coin_m, x, 0.0, -0.003, nm=f"t{i}")
    # 剑尖：一截铜尖
    make_obj(f"{name}_Tip", K.lathe_uv([(0.0, 0.0), (0.010, 0.0), (0.0, 0.07)], segments=4), coin_m, parent=root,
             loc=(L * 0.97, 0, 0), rot=(0, math.pi / 2, 0), index=index, smooth=False)
    # 剑脊上的北斗七枚大钱
    big = P.coin_build(r=r * 1.45, t=0.0023, hole=0.0115, rim_w=0.0030)
    for i, (dx, dz) in enumerate(P.DIPPER):
        x = 0.07 + dx * 0.165
        z = (dz - 0.35) * 0.040
        put(big, big_m, x, z, -0.0085, nm=f"Big{i}", spin=0.0)
    # 红绳：两边各一根，沿钱边穿过；隔一段绕一圈
    for sgn in (-1, 1):
        pts = []
        for x in np.linspace(0.0, L * 0.93, 160):
            t = x / L
            half = r * 1.55 * (1 - 0.45 * t)
            pts.append((x, -0.006 + 0.004 * math.sin(x * 140), sgn * half))
        make_obj(f"{name}_Cord{sgn}", K.tube_uv(pts, 0.0018, sides=8), cord_m, parent=root, index=index)
    for i, x in enumerate(np.arange(0.06, L * 0.85, 0.09)):
        t = x / L
        half = r * 1.6 * (1 - 0.45 * t)
        ring = [(x + 0.004 * math.sin(a), 0.012 * math.sin(a), half * math.cos(a)) for a in np.linspace(0, 2 * math.pi, 40)]
        make_obj(f"{name}_Wrap{i}", K.tube_uv(ring, 0.0016, sides=6), cord_m, parent=root, index=index)
    # 剑格：横着的几枚钱
    for j, z in enumerate((-0.064, -0.034, 0.034, 0.064)):
        put(small, coin_m, -0.005, z, -0.004, nm=f"g{j}")
    put(big, big_m, -0.005, 0.0, -0.007, nm="g_c")
    # 柄：缠红绳；剑首一枚钱；红穗
    gl = 0.15
    make_obj(f"{name}_Grip", K.lathe_uv([(0.0, 0.0), (0.011, 0.0), (0.012, gl), (0.0, gl)], segments=24), cord_m, parent=root,
             rot=(0, -math.pi / 2, 0), loc=(-0.02, 0, 0), index=index)
    wrap = [(-0.022 - gl * i / 300, 0.0125 * math.cos(i * 0.5), 0.0125 * math.sin(i * 0.5)) for i in range(300)]
    make_obj(f"{name}_GripWrap", K.tube_uv(wrap, 0.0022, sides=6), cord_m, parent=root, index=index)
    put(big, big_m, -0.02 - gl - 0.012, 0.0, 0.0, nm="pommel")
    hx = -0.02 - gl - 0.04
    pts = [(hx + 0.01 - 0.006 * i, 0.0, -0.01 - 0.010 * i) for i in range(8)]
    make_obj(f"{name}_TCord", K.tube_uv(pts, 0.0022, sides=8), cord_m, parent=root, index=index)
    for k_ in range(40):
        a = rng.uniform(0, 2 * math.pi)
        rr = 0.005 * math.sqrt(rng.uniform(0.1, 1))
        Ls = rng.uniform(0.08, 0.11)
        sp = [(pts[-1][0] - Ls * 0.3 * t_ + rr * math.cos(a) * t_, rr * math.sin(a) * (1 + t_), pts[-1][2] - Ls * t_)
              for t_ in np.linspace(0, 1, 6)]
        make_obj(f"{name}_TS{k_}", K.tube_uv(sp, 0.0007, sides=4, caps=False), cord_m, parent=root, index=index)
    return root


@scene("coin_sword", name="铜钱剑", samples=128, grade=dict(WARM_GRADE, exposure=1.0, bloom=0.34, contrast=1.06))
def build_coin_sword(draft):
    """铜钱剑：一把红绳编起来的铜钱剑悬在半空（左下柄、右上剑尖），剑脊上七枚大钱排成北斗；剑尖一点冷光；
    夜空里隐约一组北斗，和剑上的七枚钱对上。"""
    from mathutils import Vector  # noqa: PLC0415

    sky_gradient(lin("#07080D"), lin("#3A3020"), 0.7, ground=lin("#050505"))
    rng = np.random.default_rng(61)
    face = K.np_image("coin_face", P.coin_face_texture("开元通宝"))
    coin_m = P.mat_coin("Coin", face, patina_amt=0.45)
    big_m = P.mat_coin("BigCoin", K.np_image("coin_face_big", P.coin_face_texture("天下太平")), base=(0.62, 0.42, 0.16), patina_amt=0.15,
                       rough=0.22, gilt=0.65)
    cord_m = P.mat_silk("RedCord", (0.48, 0.035, 0.025), sheen=0.7, rough=0.5)
    R, eul = sword_frame(math.radians(-14), math.radians(-17))
    mid = R @ Vector((0.24, 0, 0))
    coin_sword("CoinSword", coin_m=coin_m, big_m=big_m, cord_m=cord_m, loc=tuple(-mid), rot=eul, rng=rng)
    tip = R @ Vector((0.66, 0, 0)) - mid
    P.glow_orb("TipGlow", tuple(tip), 0.006, (0.80, 0.92, 1.0), 60.0, light_w=1.2)
    K.area_light("Key", (-0.9, -1.2, 1.2), (0, 0, 0), 55.0, 1.0, color=(1.0, 0.86, 0.66))
    K.area_light("Rim", (1.0, 1.2, 0.8), (0, 0, 0), 40.0, 0.8, color=(0.62, 0.74, 1.0))
    K.area_light("Fill", (0.5, -1.4, -0.6), (0, 0, 0), 4.0, 1.0, color=(0.70, 0.75, 1.0))
    K.camera((0.0, -1.38, 0.10), (0.0, 0.0, 0.0), lens=50.0, fstop=5.6, focus=1.36)
    return {"light": "warm"}


@background("coin_sword")
def bg_coin_sword(P_, h, w, rng, k):
    P_.fill_grad("#0E0E14", "#15120F", cloud=0.12)
    K.bg_glow(P_, 0.50, 0.52, 0.48, 0.40, "#5A3E1E", 0.30)
    # 夜空里一组北斗（淡淡的星点，斗柄朝右下）
    for i, (dx, dz) in enumerate(P.DIPPER):
        x, y = (0.34 + dx * 0.085) * w, (0.17 + (0.62 - dz) * 0.10 + 0.012 * dx) * h
        P_.light(np.exp(-(((P_.X - x) / (2.2 * k)) ** 2 + ((P_.Y - y) / (2.2 * k)) ** 2)) * 0.9, "#E8EEF8")
        P_.light(np.exp(-(((P_.X - x) / (9 * k)) ** 2 + ((P_.Y - y) / (9 * k)) ** 2)) * 0.25, "#9FB0D0")
    bg_clouds(P_, rng, k, [(0.70, 0.03, 0.10, 0.70), (0.78, 0.02, 0.35, 0.98)], "#5A4A36", 0.18)
    K.bg_mountains(P_, [(0.92, [(0.12, 0.10, 0.12, 0.10), (0.40, 0.06, 0.12, 0.14), (0.75, 0.12, 0.14, 0.12)], "#17140F", 0.85, 0.08, 5.0,
                         "#7A6A52")], rng, k)
    K.bg_ink(P_, [(0.02, 0.06, 0.26, 0.18, 0.2), (0.98, 0.08, 0.24, 0.18, -0.4)], 0.45)


@scene("coin_sword_evo", name="天罡", samples=128, grade=dict(WARM_GRADE, exposure=1.0, bloom=0.40, contrast=1.06))
def build_coin_sword_evo(draft):
    """天罡：一圈铜金色的剑气旋风（几道螺旋光带 + 裹在里面的细碎剑光），头顶七枚大钱排成北斗、斗柄指向右上，
    七枚钱之间连着淡淡的金线；地上一圈金光。"""
    from mathutils import Vector  # noqa: PLC0415

    sky_gradient(lin("#07080D"), lin("#3A3020"), 0.6, ground=lin("#050505"))
    rng = np.random.default_rng(67)
    gold = (1.0, 0.72, 0.30)
    for j in range(9):
        r0 = rng.uniform(0.45, 0.70)
        z0, z1 = rng.uniform(0.0, 0.15), rng.uniform(0.30, 0.62)
        a0 = rng.uniform(0, 2 * math.pi)
        turns = rng.uniform(0.7, 1.2)
        pts = []
        for t in np.linspace(0, 1, 160):
            a = a0 + 2 * math.pi * turns * t
            r = r0 * (1 + 0.10 * math.sin(3 * t + j))
            pts.append((r * math.cos(a), r * math.sin(a) * 0.95, z0 + (z1 - z0) * t))
        make_obj(f"Whirl{j}", K.ribbon_uv(pts, rng.uniform(0.04, 0.10), ups=[(0, 0, 1)] * len(pts)),
                 K.mat_wind(f"WhirlM{j}", strength=rng.uniform(1.5, 2.6), seed=j * 1.3, color=gold), index=3)
    shard = P.mat_steel("Shard", tint=(0.95, 0.80, 0.55), rough=0.15, edge_glow=((1.0, 0.75, 0.35), 3.0))
    for i in range(26):  # 旋风里的剑光：细长的刃片顺着旋转方向
        a = rng.uniform(0, 2 * math.pi)
        r = rng.uniform(0.48, 0.72)
        z = rng.uniform(0.05, 0.55)
        tang = Vector((-math.sin(a), math.cos(a), 0.15)).normalized()
        ob = make_obj(f"Shard{i}", P.blade_build(rng.uniform(0.10, 0.20), 0.012, 0.003, tip=0.3), shard, smooth=False,
                      loc=(r * math.cos(a), r * math.sin(a) * 0.95, z), index=2)
        ob.rotation_mode = "QUATERNION"
        ob.rotation_quaternion = tang.to_track_quat("X", "Z")
    # 地上一圈金光
    make_obj("GroundRing", P.wave_ring_build(0.62, 0.022, 0.0, wob=0.15),
             K.mat_wavefront("GroundRingM", strength=1.3, seed=2.0, gaps=0.45, color=(1.0, 0.70, 0.32)), index=4)
    # 头顶七枚大钱：北斗，斗柄指向右上
    coin_m = P.mat_coin("BigCoin", K.np_image("coin_face_big2", P.coin_face_texture("天下太平")), base=(0.62, 0.42, 0.16), patina_amt=0.12,
                        rough=0.22, gilt=0.7, emit=((1.0, 0.70, 0.30), 0.12))
    cb = P.coin_build(r=0.065, t=0.006, hole=0.026, rim_w=0.008, rim_h=0.0012)
    pos = []
    for i, (dx, dz) in enumerate(P.DIPPER):
        p = Vector((-0.52 + dx * 0.38, 0.05 - 0.04 * dx, 0.90 + (dz - 0.3) * 0.28 + 0.06 * dx))
        pos.append(p)
        ob = make_obj(f"Star{i}", cb, coin_m, loc=tuple(p), index=1, smooth=False)
        ob.rotation_mode = "ZXY"
        ob.rotation_euler = (math.radians(78), rng.uniform(-0.2, 0.2), rng.uniform(0, 1.5))
        K.point_light(f"StarL{i}", tuple(p + Vector((0, 0.08, 0.02))), 0.5, radius=0.04, color=(1.0, 0.75, 0.40))
    line = []
    for a, b in zip(pos, pos[1:]):
        for t in np.linspace(0, 1, 12, endpoint=False):
            line.append(tuple(a + (b - a) * t))
    line.append(tuple(pos[-1]))
    make_obj("StarLine", K.tube_uv(line, 0.004, sides=6), P.mat_glow_shell("StarLineM", (1.0, 0.78, 0.40), strength=2.0, power=1.2),
             index=4)
    K.point_light("Core", (0, 0, 0.35), 40.0, radius=0.3, color=(1.0, 0.65, 0.28))
    K.area_light("Moon", (-2.0, 2.0, 3.0), (0, 0, 0.5), 200.0, 1.5, color=(0.62, 0.72, 1.0))
    K.area_light("Front", (0.5, -2.5, 1.5), (0, 0, 0.8), 25.0, 1.5, color=(1.0, 0.85, 0.66))
    K.camera((0.05, -2.75, 1.05), (0.0, 0.0, 0.52), lens=38.0, fstop=8.0, focus=2.8)
    return {"light": "warm"}


@background("coin_sword_evo")
def bg_coin_sword_evo(P_, h, w, rng, k):
    P_.fill_grad("#0E0E14", "#15120F", cloud=0.12)
    K.bg_glow(P_, 0.50, 0.80, 0.40, 0.14, "#8A5A20", 0.30)
    K.bg_glow(P_, 0.50, 0.55, 0.52, 0.45, "#6A4A20", 0.34)
    K.bg_glow(P_, 0.50, 0.30, 0.40, 0.20, "#8A6A30", 0.18)
    bg_clouds(P_, rng, k, [(0.12, 0.025, 0.25, 0.80), (0.20, 0.02, 0.45, 0.95)], "#5A4A36", 0.16)
    K.bg_mountains(P_, [(0.62, [(0.10, 0.10, 0.12, 0.10), (0.35, 0.05, 0.12, 0.12), (0.80, 0.11, 0.14, 0.12)], "#1C1812", 0.8, 0.10, 5.0,
                         "#7A6A52")], rng, k)
    K.bg_ink(P_, [(0.02, 0.06, 0.26, 0.18, 0.2), (0.98, 0.08, 0.24, 0.18, -0.4)], 0.45)


# ====================================================================== 孔明灯


@scene("sky_lantern", name="孔明灯", samples=128, grade=dict(WARM_GRADE, exposure=1.0, bloom=0.36))
def build_sky_lantern(draft):
    """孔明灯：一盏纸糊的孔明灯正离地升起（纸上一个红“安”字），灯底一团火把纸从里面照亮；下面是狐村的屋檐，
    檐角挂着两盏小红灯笼。镜头在屋顶上方一点，往上看灯。"""
    K.set_world(lin("#0A0C14"), 0.5)
    rng = np.random.default_rng(71)
    P.sky_lantern("SkyLantern", glyph_img=K.glyph_image("安"), loc=(0.05, 0.25, 0.30), rot=(math.radians(4), math.radians(-6), 0.4),
                  light_w=45.0)
    roof_m = P.mat_roof_tiles("Tiles", color=(0.05, 0.048, 0.052), moss=0.4)
    wall_m = P.mat_wood_plain("Walls", color=(0.09, 0.05, 0.035))
    for nm, loc, rz, sc in (("RoofA", (-0.85, 0.2, -1.12), 0.12, 1.0), ("RoofB", (1.05, 1.35, -1.35), -0.25, 1.1),
                            ("RoofC", (-0.3, 2.8, -1.45), 0.05, 1.3)):
        ob = make_obj(nm, P.roof_build(w=1.6 * sc, d=1.0 * sc, h=0.42 * sc, curl=0.12 * sc, wall_h=0.5), [roof_m, wall_m],
                      loc=loc, rot=(0, 0, rz), index=0)
        # 墙用第二个材质：最后 6 个面是墙盒子
        me = ob.data
        for f in me.polygons[-6:]:
            f.material_index = 1
    # 檐角两盏小红灯笼
    lant = K.mat_lantern_paper("RedLantern")
    for i, p in enumerate(((-1.55, -0.30, -0.62), (-0.12, -0.32, -0.60))):
        make_obj(f"RedLantern{i}", K.lathe_uv([(0.0, -0.06), (0.04, -0.05), (0.055, 0.0), (0.04, 0.05), (0.0, 0.06)], segments=20), lant,
                 loc=p, index=4)
        K.point_light(f"RedLanternL{i}", p, 2.5, radius=0.03, color=(1.0, 0.40, 0.15))
    # 几点飞起的火星
    ember = K.mat_ember("Ember")
    for i in range(16):
        p = (rng.normal(0.05, 0.12), 0.25 + rng.normal(0, 0.08), rng.uniform(0.0, 0.40))
        make_obj(f"Spark{i}", K.ico_cloud([(0, 0, 0)], [rng.uniform(0.002, 0.004)], 1), ember, loc=p, index=4)
    K.area_light("Moon", (-2.0, 3.0, 3.5), (0, 0.5, 0.5), 180.0, 1.5, color=(0.60, 0.70, 1.0))
    K.area_light("Fill", (1.2, -2.0, 0.2), (0, 0, 0.5), 6.0, 1.5, color=(0.65, 0.72, 1.0))
    K.camera((0.25, -3.35, 0.05), (0.02, 0.3, 0.22), lens=36.0, fstop=5.6, focus=3.45)
    return {"light": "warm"}


@background("sky_lantern")
def bg_sky_lantern(P_, h, w, rng, k):
    P_.fill_grad("#0C1020", "#141826", cloud=0.12)
    K.bg_glow(P_, 0.50, 0.32, 0.40, 0.36, "#6A3E1A", 0.32)
    K.bg_moon(P_, 0.80, 0.24, 0.040, rng, k, color="#E8ECF2", halo="#7890B6", a=0.55, halo_a=0.22)
    bg_clouds(P_, rng, k, [(0.40, 0.025, 0.55, 0.98), (0.48, 0.02, 0.02, 0.40)], "#4C5A74", 0.18)
    K.bg_mountains(P_, [(0.72, [(0.10, 0.10, 0.12, 0.10), (0.38, 0.06, 0.14, 0.12), (0.78, 0.12, 0.14, 0.14)], "#151B2A", 0.85, 0.08, 5.0)],
                   rng, k)
    K.bg_ink(P_, [(0.02, 0.06, 0.26, 0.18, 0.2), (0.98, 0.04, 0.20, 0.14, -0.4)], 0.45)


@scene("sky_lantern_evo", name="万灯升", samples=128, grade=dict(WARM_GRADE, exposure=0.98, bloom=0.42, sat=1.05))
def build_sky_lantern_evo(draft):
    """万灯升：满天孔明灯一齐往下坠（灯身歪斜，火往上拖成一道道火尾），像一场火雨；地上一片火光、几座屋顶的剪影。按画面位置摆。"""
    from mathutils import Euler, Vector  # noqa: PLC0415

    K.set_world(lin("#0B0A10"), 0.4)
    rng = np.random.default_rng(79)
    S = ScreenCam(lens=32.0)
    paper = P.mat_sky_paper("Paper")
    bamboo = K.mat_bamboo_dark("Bamboo")
    fire_m = K.mat_fire("FireTail", strength=3.5, seed=2.0)
    spots = []
    for i in range(34):
        x, y = rng.uniform(0.06, 0.94), rng.uniform(0.12, 0.70)
        if (x > 0.78 and y < 0.22) or (x < 0.22 and y < 0.25):
            continue
        depth = rng.uniform(8.0, 30.0) if i > 4 else rng.uniform(5.0, 7.5)
        spots.append((x, y, depth))
    spots.sort(key=lambda s_: -s_[2])
    for i, (x, y, depth) in enumerate(spots):
        p = S(x, y, depth)
        tilt = Euler((rng.uniform(-0.5, 0.5), rng.uniform(-0.6, 0.6), rng.uniform(0, 6.28)), "XYZ")
        sc = rng.uniform(0.85, 1.15)
        root = P.sky_lantern(f"L{i}", paper_m=paper, bamboo_m=bamboo, loc=tuple(p), rot=tilt, light_w=18.0 * sc, index=1)
        root.scale = (sc, sc, sc)
        # 火尾：从灯底往上（下坠时火被拖向上方）
        up = Vector((rng.normal(0, 0.08), 0, 1.0)).normalized()
        base = p + Vector((0, 0, 1.0 * sc))
        L = rng.uniform(1.0, 2.2) * sc
        pts = [tuple(base + up * L * t + Vector((0.03 * math.sin(t * 7 + i), 0, 0)) * t) for t in np.linspace(0, 1, 30)]
        make_obj(f"Tail{i}", K.ribbon_uv(pts, 0.10 * sc, ups=[(1, 0, 0)] * len(pts)), fire_m, index=4)
    K.area_light("GroundFire", tuple(S(0.5, 1.3, 14.0)), tuple(S(0.5, 0.5, 14.0)), 9000.0, 14.0, color=(1.0, 0.45, 0.15))
    S.place(lens=32.0, fstop=11.0, focus=6.0)
    return {"light": "warm"}


@background("sky_lantern_evo")
def bg_sky_lantern_evo(P_, h, w, rng, k):
    """夜空被火光映成暗红；地平线上一排屋顶剪影，屋后、屋顶上一片火光。"""
    P_.fill_grad("#120C10", "#3A1A0C", cloud=0.14)
    K.bg_glow(P_, 0.50, 0.92, 0.90, 0.30, "#B0501A", 0.50)
    K.bg_glow(P_, 0.50, 0.45, 0.60, 0.40, "#5A2E14", 0.30)
    bg_clouds(P_, rng, k, [(0.12, 0.03, 0.15, 0.85), (0.22, 0.025, 0.40, 0.98), (0.30, 0.02, 0.02, 0.50), (0.62, 0.03, 0.10, 0.90)],
              "#9A5A30", 0.22)
    # 火：地平线上一片跳动的火舌（竖向拉长的噪声）
    fire = K._ss(0.30, 0.85, K._noise(rng, (h, w), (10 * k, 40 * k))) * K._ss(0.70 * h, 0.86 * h, P_.Y)
    P_.light(fire * 0.70, "#E07A2A")
    K.bg_roofs(P_, 0.89, rng, k, color="#0A0606", a=0.95, n=13, height=0.065, lit="#FFB060", lit_a=0.6)
    P_.over(K._ss(0.88 * h, 0.92 * h, P_.Y) * 0.9, "#0A0606")
    K.bg_ink(P_, [(0.02, 0.06, 0.26, 0.18, 0.2), (0.98, 0.06, 0.22, 0.16, -0.4)], 0.45)


# ====================================================================== 沧浪


def curl_wave_build(L=3.0, H=0.9, nu=140, nv=56, curl_fn=None, height_fn=None, bend=0.35):
    """卷起的浪（沿 X，浪往 -Y 打）：截面是一条有厚度的“C”：中线从前面的浪谷沿浪面爬上浪峰，再往前卷成浪舌；
    厚度在浪底最厚（往后铺成浪背）、浪峰变薄、舌尖最薄。截面闭合，所以浪是实心的水，背面、底部都有面。
    curl_fn(u) 0..1 卷的程度，height_fn(u) 高度倍数（两头压到 0 就没入海面）；bend 让浪从上面看是弯月形。
    UV：u 沿浪长，v 沿截面一圈（0 → 0.5 舌尖 → 1）。"""
    curl_fn = curl_fn or (lambda u: 1.0)
    height_fn = height_fn or (lambda u: 1.0)

    def section(c, h):
        h = max(h, 0.02)
        cl = []
        for t in np.linspace(0, 1, 22):  # 浪面
            y = -0.45 * h + 0.45 * h * (1 - (1 - t) ** 1.7)
            z = -0.04 + (h * 0.92 + 0.04) * t ** 1.7
            cl.append((y + 0.06 * h * math.sin(t * math.pi), z))
        rc = 0.30 * h * (0.45 + 0.55 * c)
        cy, cz = cl[-1][0] - 0.02 * h, cl[-1][1] + 0.08 * h - rc
        for ph in np.linspace(0.0, math.radians(30 + 190 * c), 30)[1:]:
            cl.append((cy - rc * math.sin(ph) * (1 + 0.15 * ph), cz + rc * math.cos(ph) + 0.08 * h))
        cl = np.array(cl)
        d = np.gradient(cl, axis=0)
        n = np.stack([d[:, 1], -d[:, 0]], -1)
        n = n / (np.linalg.norm(n, axis=1, keepdims=True) + 1e-9)
        s_ = np.linspace(0, 1, len(cl))
        thick = np.interp(s_, [0, 0.35, 0.62, 0.85, 1.0], [1.1 * h, 0.45 * h, 0.16 * h, 0.06 * h, 0.012 * h])
        outer = cl + n * thick[:, None]
        inner = cl - n * 0.010 * h
        outer[:, 1] = np.maximum(outer[:, 1], -0.04)
        ring = list(map(tuple, inner)) + list(map(tuple, outer[::-1]))
        return ring

    def build(bm):
        import bmesh  # noqa: PLC0415

        uvl = bm.loops.layers.uv.new("UVMap")
        rings = []
        for i in range(nu + 1):
            u = i / nu
            ring = section(curl_fn(u), H * height_fn(u))
            x = (u - 0.5) * L
            yb = bend * (2 * u - 1) ** 2
            rings.append([bm.verts.new((x, y + yb, z)) for y, z in ring])
        m = len(rings[0])
        for i in range(nu):
            for j in range(m):
                j1 = (j + 1) % m
                f = bm.faces.new((rings[i][j], rings[i + 1][j], rings[i + 1][j1], rings[i][j1]))
                for lp, uv in zip(f.loops, ((i / nu, j / m), ((i + 1) / nu, j / m), ((i + 1) / nu, (j + 1) / m), (i / nu, (j + 1) / m))):
                    lp[uvl].uv = uv
        bm.faces.new(list(reversed(rings[0])))
        bm.faces.new(rings[-1])
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)

    return build


def foam_texture(w=1024, h=512, seed=4):
    """浪面上的泡沫：越靠浪峰、舌尖（v 大）越多，沿浪长拉出一道道白纹。返回 (h, w) 0..1（v 方向从下往上 = 图里从下到上）。"""
    rng = np.random.default_rng(seed)
    V = K.vfx()
    v = np.linspace(0, 1, h)[::-1][:, None] * np.ones((1, w))
    n1 = V.fft_blur(rng.standard_normal((h, w)), (40.0, 3.0))
    n1 = n1 / (n1.std() + 1e-9)
    n2 = V.fft_blur(rng.standard_normal((h, w)), (14.0, 1.2))
    n2 = n2 / (n2.std() + 1e-9)
    vv = 1 - np.abs(v - 0.5) * 2  # 1 = 舌尖
    band = np.clip((vv - 0.42) / 0.35, 0, 1) ** 1.2
    tipz = np.clip((vv - 0.76) / 0.20, 0, 1)
    f = np.clip(band * (0.55 + 0.35 * n1 + 0.25 * n2) + tipz * 0.9, 0, 1)
    lace = np.clip(np.tanh(1.5 * (n2 - 0.8)), 0, 1) * np.clip((vv - 0.30) / 0.4, 0, 1) * 0.45
    return np.clip(np.maximum(f, lace), 0, 1)


@scene("wave", name="沧浪", samples=128, grade=dict(COLD_GRADE, bloom=0.30, sat=1.02))
def build_wave(draft):
    """沧浪：一道卷起的月牙浪头（左边卷得最狠、往右渐成涌浪），浪尖碎成白沫往前飞溅；浪里卷着几只小妖（暗身、亮眼）。
    月光从浪后面打过来，浪舌最薄处透出青光。"""
    from mathutils import Vector  # noqa: PLC0415

    sky_gradient(lin("#05080F"), lin("#2B4A60"), 0.9, ground=lin("#03060A"))
    rng = np.random.default_rng(83)
    foam = K.np_image("wave_foam", foam_texture())
    water = P.mat_water("Water", color=(0.010, 0.075, 0.090), foam_img=foam, emit=0.05, transmission=0.40, rough=0.10)
    ob = make_obj("Wave", curl_wave_build(L=3.6, H=1.0, curl_fn=lambda u: K.smoothstep(0.05, 0.75, u),
                                         height_fn=lambda u: K.smoothstep(0.0, 0.55, u) * (1.0 - 0.25 * K.smoothstep(0.85, 1.0, u)),
                                         bend=0.45), water, index=1)
    _ = ob
    sea = P.mat_water("Sea", color=(0.008, 0.035, 0.045), rough=0.38, transmission=0.0)
    ground_plane("Sea", sea, size=30.0, loc=(0, 8.0, 0.0), index=0)
    # 浪尖飞沫：沿舌尖往前上方溅
    fm = P.mat_foam("Spray", emit=0.15)
    pts_, rad_ = [], []
    for i in range(1100):
        u = rng.uniform(0.40, 1.0)
        x = (u - 0.5) * 3.6
        h = K.smoothstep(0.0, 0.55, u)
        c = K.smoothstep(0.05, 0.75, u)
        y = -0.32 * h * c - abs(rng.normal(0.0, 0.25)) * c + 0.45 * (2 * u - 1) ** 2
        z = h * (0.82 + abs(rng.normal(0.0, 0.18)))
        pts_.append((x + rng.normal(0, 0.04), y, z))
        rad_.append(rng.uniform(0.004, 0.016))
    make_obj("Spray", K.ico_cloud(pts_, rad_, 1), fm, index=3)
    # 浪里卷着的小妖（在浪舌底下）
    for i, (u, z, sz) in enumerate(((0.62, 0.36, 0.07), (0.78, 0.50, 0.06), (0.92, 0.30, 0.055))):
        x = (u - 0.5) * 3.6
        P.imp(f"Imp{i}", size=sz, loc=(x, -0.16 + 0.45 * (2 * u - 1) ** 2, z), rot=tuple(rng.uniform(-1.0, 1.0, 3)), rng=rng)
    K.area_light("Moon", (1.0, 4.0, 2.4), (0.6, 0, 0.6), 700.0, 1.5, color=(0.62, 0.78, 1.0))
    K.area_light("Front", (-1.0, -4.0, 2.0), (0.4, 0, 0.5), 40.0, 3.0, color=(0.60, 0.72, 1.0))
    K.point_light("Inner", (0.9, 0.25, 0.45), 18.0, radius=0.2, color=(0.40, 0.85, 0.80))
    K.camera((-3.4, -1.75, 0.55), (0.55, 0.05, 0.50), lens=34.0, fstop=8.0, focus=4.2)
    return {"light": "cold"}


@background("wave")
def bg_wave(P_, h, w, rng, k):
    P_.fill_grad("#0A1320", "#10202C", cloud=0.12)
    K.bg_glow(P_, 0.40, 0.42, 0.50, 0.40, "#3A5E78", 0.30)
    K.bg_moon(P_, 0.68, 0.22, 0.05, rng, k, color="#E6EEF4", halo="#7896B0", a=0.6, halo_a=0.30)
    bg_clouds(P_, rng, k, [(0.30, 0.03, 0.40, 0.98), (0.38, 0.02, 0.05, 0.50)], "#4E6A80", 0.20)
    K.bg_ink(P_, [(0.02, 0.06, 0.26, 0.18, 0.2), (0.98, 0.06, 0.22, 0.16, -0.4)], 0.45)


# ====================================================================== 北冥潮


def fish_shadow_texture(size=1024, seed=3):
    """海面下鲲的影子：一条大鱼的剪影（纺锤形身子、叉尾、两片胸鳍），边缘糊开。返回 (size, size) 0..1，鱼头朝 +x。"""
    from PIL import Image, ImageDraw, ImageFilter  # noqa: PLC0415

    im = Image.new("L", (size, size), 0)
    dr = ImageDraw.Draw(im)
    s = size
    body = []
    for t in np.linspace(0, 1, 60):
        x = 0.18 + 0.62 * t
        hw = 0.13 * math.sin(math.pi * min(1.0, t * 1.08)) ** 0.7
        body.append((x * s, (0.5 - hw) * s))
    for t in np.linspace(1, 0, 60):
        x = 0.18 + 0.62 * t
        hw = 0.13 * math.sin(math.pi * min(1.0, t * 1.08)) ** 0.7
        body.append((x * s, (0.5 + hw) * s))
    dr.polygon(body, fill=255)
    dr.polygon([(0.20 * s, 0.5 * s), (0.02 * s, 0.30 * s), (0.09 * s, 0.5 * s), (0.02 * s, 0.70 * s)], fill=255)  # 尾
    for sy in (-1, 1):
        dr.polygon([(0.58 * s, (0.5 + sy * 0.10) * s), (0.42 * s, (0.5 + sy * 0.28) * s), (0.50 * s, (0.5 + sy * 0.11) * s)], fill=255)
    im = im.filter(ImageFilter.GaussianBlur(s * 0.012))
    return np.asarray(im, np.float64) / 255.0


@scene("wave_evo", name="北冥潮", samples=128, grade=dict(COLD_GRADE, bloom=0.32, sat=0.98), fog=(15.0, 32.0))
def build_wave_evo(draft):
    """北冥潮：俯看一圈巨浪从中心往外扩，浪头往外卷、结着冰（浪峰一圈冰晶）；圈里水面压低、正中一点青光；
    远处是冰海，浮冰点点，海面下一条巨鱼（鲲）的影子。"""
    from mathutils import Vector  # noqa: PLC0415

    sky_gradient(lin("#05080F"), lin("#2B4A60"), 0.8, ground=lin("#03060A"))
    rng = np.random.default_rng(89)
    R = 1.55
    prof = [(0.0, -0.16), (0.5, -0.15), (0.9, -0.10), (1.15, 0.02), (1.30, 0.20), (1.40, 0.42), (1.47, 0.60), (1.56, 0.72),
            (1.68, 0.74), (1.80, 0.68), (1.90, 0.56), (1.94, 0.46), (1.90, 0.40), (1.84, 0.38), (1.88, 0.30), (2.05, 0.14),
            (2.35, 0.04), (2.8, 0.0)]
    water = P.mat_water("RingWater", color=(0.012, 0.08, 0.10), transmission=0.35, rough=0.10, emit=0.04)
    make_obj("RingWave", K.lathe_uv(prof, segments=240, radial=lambda th, z, i: 1 + 0.03 * math.sin(5 * th + 1) * (z > 0.1) +
                                    0.015 * math.sin(13 * th) * (z > 0.2)), water, index=1)
    # 浪头的冰：一圈冰壳 + 冰晶
    ice = K.mat_ice("Ice", rough=0.12, tint=(0.80, 0.92, 1.0))
    make_obj("IceCrest", P.wave_ring_build(1.70, 0.05, 0.73, wob=0.4), ice, index=2)
    fm = P.mat_foam("Foam", emit=0.1)
    pts_, rad_ = [], []
    for i in range(1400):  # 浪头往外甩的飞沫
        a = rng.uniform(0, 2 * math.pi)
        rr = 1.75 + abs(rng.normal(0, 0.22))
        z = 0.45 + rng.normal(0.2, 0.15)
        pts_.append((rr * math.cos(a), rr * math.sin(a), z))
        rad_.append(rng.uniform(0.006, 0.02))
    make_obj("Spray", K.ico_cloud(pts_, rad_, 1), fm, index=3)
    for i in range(420):
        a = rng.uniform(0, 2 * math.pi)
        rr = rng.uniform(1.55, 1.95)
        z = 0.50 + 0.26 * math.exp(-((rr - 1.70) / 0.12) ** 2)
        p = Vector((rr * math.cos(a), rr * math.sin(a), z))
        d = Vector((math.cos(a) * rng.uniform(0.3, 1.0), math.sin(a) * rng.uniform(0.3, 1.0), rng.uniform(0.4, 1.0))).normalized()
        L = rng.uniform(0.05, 0.16)
        ob = make_obj(f"Xtal{i}", P.crystal_build(L, L * 0.18), ice, loc=tuple(p), index=2, smooth=False)
        ob.rotation_mode = "QUATERNION"
        ob.rotation_quaternion = d.to_track_quat("Z", "Y")
    # 寒雾一圈（霜环）
    make_obj("FrostHaze", P.wave_ring_build(1.70, 0.20, 0.42, wob=0.6), K.mat_wavefront("FrostHazeM", strength=0.5, seed=3.0, soft=3.0,
                                                                                   gaps=0.4), index=5)
    P.glow_orb("Core", (0.0, 0.0, -0.05), 0.05, (0.55, 0.95, 1.0), 30.0, light_w=12.0)
    # 冰海：海面（鲲的影子画在材质里）+ 浮冰
    fish = K.np_image("kun", fish_shadow_texture())
    sm = K.Mat("Sea")
    oc = sm.coord("Object")
    sep = sm.n("ShaderNodeSeparateXYZ")
    sm.l(oc, sep.inputs[0])
    cu = sm.n("ShaderNodeCombineXYZ")
    sm.l(sm.math("ADD", sm.math("DIVIDE", sm.math("SUBTRACT", sep.outputs["X"], 3.0), 7.0), 0.5), cu.inputs["X"])
    sm.l(sm.math("ADD", sm.math("DIVIDE", sm.math("SUBTRACT", sep.outputs["Y"], 4.6 - 10.0), 7.0), 0.5), cu.inputs["Y"])  # 海面中心在 y=10
    ft = sm.n("ShaderNodeTexImage", _interpolation="Cubic", _extension="CLIP")
    ft.image = fish
    sm.l(cu.outputs[0], ft.inputs["Vector"])
    fsc = sm.n("ShaderNodeSeparateColor")
    sm.l(ft.outputs["Color"], fsc.inputs[0])
    nz = sm.noise(oc, scale=3.0, detail=6.0)
    col = sm.mix(sm.maprange(nz.outputs["Fac"], 0.3, 0.7), (0.010, 0.040, 0.055, 1.0), (0.020, 0.075, 0.095, 1.0))
    col = sm.mix(sm.math("MULTIPLY", fsc.outputs[0], 0.95), col, (0.0005, 0.0015, 0.003, 1.0))
    wn = sm.noise(oc, scale=2.2, detail=5.0, rough=0.6)
    nrm = sm.bump(wn.outputs["Fac"], strength=0.35, distance=0.05)
    rough = sm.mixf(fsc.outputs[0], 0.16, 0.6)
    bsdf = sm.principled(Base_Color=col, Roughness=rough, Normal=nrm)
    bsdf.inputs["Emission Color"].default_value = (0.10, 0.30, 0.40, 1.0)  # 冰海底下透上来的一点青光，鲲的影子挡住它
    sm.l(sm.math("MULTIPLY", sm.math("SUBTRACT", 1.0, fsc.outputs[0]), sm.maprange(nz.outputs["Fac"], 0.3, 0.7, 0.08, 0.20)),
         bsdf.inputs["Emission Strength"])
    sm.surface(bsdf.outputs[0])
    ground_plane("Sea", sm.m, size=40.0, loc=(0, 10.0, -0.0), index=0)
    floe = P.mat_stone("Floe", color=(0.30, 0.36, 0.42), rough=0.4, scale=8.0, cavity=0.3, bump=0.3)
    for i in range(26):
        p = (rng.uniform(-6, 7), rng.uniform(3.0, 14.0), 0.01)
        if math.hypot(p[0], p[1]) < 3.0 or (abs(p[0] - 3.0) < 2.6 and abs(p[1] - 4.6) < 1.3):
            continue
        def slab(bm, r0=rng.uniform(0.15, 0.6)):
            import bmesh  # noqa: PLC0415

            pts = [(r0 * (1 + 0.25 * rng.normal()) * math.cos(a), r0 * (1 + 0.25 * rng.normal()) * math.sin(a))
                   for a in np.linspace(0, 2 * math.pi, 7, endpoint=False)]
            top = [bm.verts.new((x, y, 0.03)) for x, y in pts]
            bot = [bm.verts.new((x * 0.9, y * 0.9, -0.03)) for x, y in pts]
            bm.faces.new(top)
            bm.faces.new(list(reversed(bot)))
            for j in range(len(pts)):
                bm.faces.new((top[j], bot[j], bot[(j + 1) % len(pts)], top[(j + 1) % len(pts)]))
            bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
        make_obj(f"Floe{i}", slab, floe, loc=p, rot=(0, 0, rng.uniform(0, 6.28)), index=2, smooth=False)
    K.area_light("Moon", (-4.0, 9.0, 6.0), (0, 2.0, 0), 1800.0, 3.0, color=(0.62, 0.76, 1.0))
    K.area_light("Front", (1.0, -5.0, 4.0), (0, 0, 0), 120.0, 3.0, color=(0.60, 0.72, 1.0))
    K.camera((0.3, -3.4, 4.6), (0.15, 1.55, 0.0), lens=30.0, fstop=11.0, focus=6.6)
    return {"light": "cold"}


@background("wave_evo")
def bg_wave_evo(P_, h, w, rng, k):
    P_.fill_grad("#0A1220", "#122030", cloud=0.12)
    K.bg_glow(P_, 0.40, 0.18, 0.50, 0.25, "#4A6A8A", 0.28)
    bg_clouds(P_, rng, k, [(0.08, 0.025, 0.25, 0.85), (0.14, 0.02, 0.05, 0.55)], "#5B7194", 0.18)
    K.bg_ink(P_, [(0.02, 0.06, 0.26, 0.18, 0.2), (0.98, 0.06, 0.22, 0.16, -0.4)], 0.45)


# ====================================================================== 异化：冰火两重天（灯火）


ICE_FIRE_RAMP = [(0.0, (0.02, 0.07, 0.40)), (0.18, (0.08, 0.32, 1.0)), (0.42, (0.32, 0.68, 1.0)), (0.70, (0.72, 0.92, 1.0)),
                 (1.0, (0.95, 0.99, 1.0))]


def frost_paper_into(mat, frost_img, soft=0.010):
    """把灯罩材质（mat_lantern_paper）改成左半结霜：x<0 一侧换成透冷光的霜纸（冰花贴图按圆柱投影），交界柔一点、带锯齿。"""
    nt = mat.node_tree
    out = next(n for n in nt.nodes if n.bl_idname == "ShaderNodeOutputMaterial")
    warm = out.inputs["Surface"].links[0].from_socket
    M = K.Mat.__new__(K.Mat)  # 借 Mat 的小工具往这个现成的节点树里加节点
    M.m, M.nt, M.out = mat, nt, out
    m = M.math
    oc = M.coord("Object")
    sep = M.n("ShaderNodeSeparateXYZ")
    M.l(oc, sep.inputs[0])
    u = m("WRAP", m("DIVIDE", m("ARCTAN2", sep.outputs["Y"], sep.outputs["X"]), 2 * math.pi), 1.0, 0.0)
    v = m("ADD", m("DIVIDE", sep.outputs["Z"], 0.32), 0.5)
    uvv = M.n("ShaderNodeCombineXYZ")
    M.l(u, uvv.inputs["X"])
    M.l(v, uvv.inputs["Y"])
    t = M.n("ShaderNodeTexImage", _interpolation="Cubic", _extension="REPEAT")
    t.image = frost_img
    M.l(uvv.outputs[0], t.inputs["Vector"])
    sc = M.n("ShaderNodeSeparateColor")
    M.l(t.outputs["Color"], sc.inputs[0])
    fern = sc.outputs[0]
    col = M.mix(fern, (0.26, 0.46, 0.80, 1.0), (0.84, 0.92, 1.0, 1.0))
    tcol = M.mix(fern, (0.06, 0.30, 1.0, 1.0), (0.55, 0.78, 1.0, 1.0))
    # 墨字：沿用原材质里那张字图（同一个投影），霜纸上也写着
    gtex = next((n for n in nt.nodes if n.bl_idname == "ShaderNodeTexImage" and n.image is not None and n is not t), None)
    if gtex is not None:
        ink = m("MULTIPLY", m("MULTIPLY", gtex.outputs["Alpha"], m("LESS_THAN", sep.outputs["Y"], -0.02)), 1.25, clamp=True)
        col = M.mix(ink, col, (0.010, 0.012, 0.020, 1.0))
        tcol = M.mix(ink, tcol, (0.003, 0.005, 0.012, 1.0))
    bsdf = M.principled(Base_Color=col, Roughness=0.55, Sheen_Weight=0.4)
    trn = M.n("ShaderNodeBsdfTranslucent")
    M.l(tcol, trn.inputs["Color"])
    mx = M.n("ShaderNodeMixShader")
    mx.inputs[0].default_value = 0.6
    M.l(bsdf.outputs[0], mx.inputs[1])
    M.l(trn.outputs[0], mx.inputs[2])
    nz = M.noise(oc, scale=60.0, detail=4.0)
    edge = m("ADD", sep.outputs["X"], m("MULTIPLY", m("SUBTRACT", nz.outputs["Fac"], 0.5), 0.03))
    k = M.maprange(edge, soft, -soft)
    fin = M.n("ShaderNodeMixShader")
    M.l(k, fin.inputs[0])
    M.l(warm, fin.inputs[1])
    M.l(mx.outputs[0], fin.inputs[2])
    M.l(fin.outputs[0], out.inputs["Surface"])


@scene("lamp_mut", name="冰火两重天", samples=160, seed=101, grade=dict(WARM_GRADE, exposure=0.97, bloom=0.34, sat=1.02))
def build_lamp_mut(draft):
    """冰火两重天：灯火的那盏朱砂纸灯笼，左半结霜（霜纸透着冰蓝的冷光、竹篾挂霜晶），右半照旧是暖红的纸；
    绕灯的火左边一朵冰蓝冷焰、右边两朵橙火，冷热交界的灯顶腾起一团团白汽。"""
    from mathutils import Matrix, Vector  # noqa: PLC0415

    bpy = K._bpy()
    K.build_lamp(draft)
    rng = np.random.default_rng(73)
    shell = bpy.data.objects["Shell"]
    fern = K.frost_ferns(1024, 512, np.random.default_rng(12), n_seeds=70, v_bias=0.5, max_len=150)
    frost_paper_into(shell.data.materials[0], K.np_image("lantern_fern", fern))
    # 火：拆成冷暖两份材质。冷的是左前一朵和从灯肩飘出的那缕，暖的是右前、右后两朵（火的位置同灯火卡）。
    # 冷的那份另做一个略大一圈的包围体（两个体积的边界不能重合）。
    Rr = 0.272
    hd = [math.radians(a) for a in (212.0, 322.0, 82.0)]
    warm = K.mat_fire_volume("FireWarm", Rr, [(hd[1], 1.2, 0.38, None, 0.0), (hd[2], 1.1, 0.34, None, 0.0)], strength=320.0,
                             seed=2.0, ring_glow=0.05)
    cold = K.mat_fire_volume("FireCold", Rr, [(hd[0], 1.35, 0.42, None, 0.0), (hd[1] - 1.05, 0.8, 0.22, 0.118, 0.085)],
                             strength=320.0, seed=5.0, ring_glow=0.05)
    ramp = next(n for n in cold.node_tree.nodes if n.bl_idname == "ShaderNodeValToRGB")
    for e, (pos, c) in zip(ramp.color_ramp.elements, ICE_FIRE_RAMP):
        e.position, e.color = pos, (*c, 1.0)
    ring = bpy.data.objects["FireRing"]
    ring.data.materials[0] = warm
    ring2 = ring.copy()
    ring2.data = ring.data.copy()
    ring2.data.transform(Matrix.Scale(1.004, 4))
    ring2.data.materials[0] = cold
    ring2.name = "FireRingIce"
    bpy.context.scene.collection.objects.link(ring2)
    bpy.data.objects["FireWedge"].data.materials[0] = cold
    ice_ember = P.mat_emit("EmberIce", (0.55, 0.82, 1.0), 18.0)
    for ob in bpy.data.objects:
        if ob.name.startswith(("Ember", "Ash")) and ob.location.x < 0:
            ob.data = ob.data.copy()
            ob.data.materials[0] = ice_ember
        if ob.name.startswith("FlameLight") and ob.location.x < 0:
            ob.data.color = (0.45, 0.72, 1.0)
    # 灯里两盏光分开放：冷光贴左半、暖光贴右半，各照各的那半边纸
    core = bpy.data.objects["CoreLight"]
    core.location.x = 0.075
    core.data.energy = 7.0
    K.point_light("ColdCore", (-0.075, 0.0, core.location.z - 0.01), 5.5, radius=0.02, color=(0.30, 0.58, 1.0))
    # 左半竹篾、灯盖上挂的霜晶
    ice = K.mat_ice("IceQ")
    for k in range(60):
        th = rng.uniform(math.radians(100), math.radians(260))
        z = rng.uniform(-0.15, 0.15)
        rr = 0.136 * math.sqrt(max(0.0, 1 - (z / 0.15) ** 2)) ** 0.58 + 0.054 * (1 - math.sqrt(max(0.0, 1 - (z / 0.15) ** 2)) ** 0.58)
        p = Vector((rr * math.cos(th), rr * math.sin(th), z))
        d = (Vector((math.cos(th), math.sin(th), 0)) + Vector(rng.normal(0, 0.5, 3))).normalized()
        L = rng.uniform(0.004, 0.010)
        ob = make_obj(f"Rime{k}", P.crystal_build(L, L * 0.22), ice, loc=tuple(p), index=3, smooth=False)
        ob.rotation_mode = "QUATERNION"
        ob.rotation_quaternion = d.to_track_quat("Z", "Y")
    # 冷热交界的白汽：从灯顶一团团往上翻，越高越大越淡；左边映冷光、右边映暖光
    steam = mat_puff("Steam", alpha=0.62, emit=0.35)
    for k in range(7):
        t = k / 6
        c = Vector((rng.normal(0.0, 0.025) * (1 + t), rng.normal(-0.02, 0.02), 0.175 + 0.15 * t ** 0.9))
        n = 5 + k
        r0 = 0.020 + 0.022 * t
        pts = [tuple(rng.normal(0, r0 * 0.9, 3) * (1.6, 0.8, 0.7)) for _ in range(n)]
        rads = [r0 * rng.uniform(0.6, 1.1) for _ in range(n)]
        make_obj(f"Steam{k}", K.ico_cloud(pts, rads, 2), steam, loc=tuple(c), index=4)
    K.point_light("SteamCold", (-0.20, -0.12, 0.26), 0.9, radius=0.05, color=(0.40, 0.66, 1.0))
    K.point_light("SteamWarm", (0.20, -0.12, 0.26), 0.9, radius=0.05, color=(1.0, 0.58, 0.26))
    # 镜头退一点、往上抬，给灯顶的白汽留出地方
    K.camera((0.05, -1.80, 0.0), (0.0, 0.0, 0.022), lens=72.0, fstop=3.5, focus=1.68)
    return {"light": "warm"}


def mat_puff(name, color=(0.92, 0.95, 1.0), alpha=0.6, emit=0.3):
    """一团白汽（球团）：正对镜头处实、边上淡（按朝向），带一点噪声的厚薄；略自发光，暗处也看得见。"""
    M = K.Mat(name)
    m = M.math
    lw = M.n("ShaderNodeLayerWeight", Blend=0.5)
    face = m("SUBTRACT", 1.0, lw.outputs["Facing"], clamp=True)
    oc = M.coord("Object")
    nz = M.noise(oc, scale=30.0, detail=5.0, rough=0.62)
    a_ = m("MULTIPLY", m("POWER", face, 1.8), m("ADD", m("MULTIPLY", M.maprange(nz.outputs["Fac"], 0.35, 0.65), 0.7), 0.3))
    a_ = m("MULTIPLY", a_, alpha, clamp=True)
    bsdf = M.principled(Base_Color=(*color, 1.0), Roughness=1.0, Specular_IOR_Level=0.0)
    bsdf.inputs["Emission Color"].default_value = (*color, 1.0)
    bsdf.inputs["Emission Strength"].default_value = emit
    tr = M.n("ShaderNodeBsdfTransparent")
    mx = M.n("ShaderNodeMixShader")
    M.l(a_, mx.inputs[0])
    M.l(tr.outputs[0], mx.inputs[1])
    M.l(bsdf.outputs[0], mx.inputs[2])
    return M.surface(mx.outputs[0])


@background("lamp_mut")
def bg_lamp_mut(P_, h, w, rng, k):
    P_.fill_grad("#0E1220", "#0B0E15", cloud=0.10)
    P_.light(P_.blob(0.30 * w, 0.46 * h, 0.30 * w, 0.42 * h, rough=0.5, rim=0.25, soft=0.85) * 0.30, "#1E4A7A")
    P_.light(P_.blob(0.70 * w, 0.46 * h, 0.30 * w, 0.42 * h, rough=0.5, rim=0.25, soft=0.85) * 0.30, "#7A3E14")
    for cx, cy, rx, ry, ang in ((0.06, 0.10, 0.30, 0.20, 0.2), (0.96, 0.92, 0.34, 0.22, -0.3), (0.95, 0.06, 0.22, 0.16, 0.5),
                                (0.04, 0.95, 0.25, 0.18, -0.2)):
        P_.darken(P_.blob(cx * w, cy * h, rx * w, ry * h, ang=ang, rough=0.6, rim=0.5, soft=0.5), 0.55)


# ====================================================================== 异化：赤霄（符剑）


def mat_hot_steel(name, L=0.74, glow=1.0):
    """烧红的剑身（blade_build：物体 X 沿剑长 0..L）：靠剑格一段是发黑的铁，往剑尖越烧越红；
    剑面爬着熔金的裂纹（Voronoi 的边），刃口一线更亮。"""
    M = K.Mat(name)
    m = M.math
    oc = M.coord("Object")
    sx = M.n("ShaderNodeSeparateXYZ")
    M.l(oc, sx.inputs[0])
    mp = M.n("ShaderNodeMapping")
    M.l(oc, mp.inputs["Vector"])
    mp.inputs["Scale"].default_value = (16.0, 60.0, 55.0)
    vor = M.n("ShaderNodeTexVoronoi", Scale=1.0, _feature="DISTANCE_TO_EDGE")
    M.l(mp.outputs["Vector"], vor.inputs["Vector"])
    nz = M.noise(oc, scale=40.0, detail=6.0, rough=0.6)
    hot = M.maprange(sx.outputs["X"], 0.04 * L, 0.45 * L, interp="SMOOTHSTEP")  # 0 剑格 → 1 剑身中段往前
    vein = m("MULTIPLY", M.maprange(vor.outputs["Distance"], 0.07, 0.0), M.maprange(nz.outputs["Fac"], 0.32, 0.58))
    uv = M.coord("UV")
    sep = M.n("ShaderNodeSeparateXYZ")
    M.l(uv, sep.inputs[0])
    edge = m("ADD", M.maprange(m("ABSOLUTE", m("SUBTRACT", sep.outputs["Y"], 0.25)), 0.05, 0.0),
             M.maprange(m("ABSOLUTE", m("SUBTRACT", sep.outputs["Y"], 0.75)), 0.05, 0.0))
    heat = m("ADD", m("MULTIPLY", hot, m("ADD", 0.30, m("ADD", vein, m("MULTIPLY", edge, 0.55)))), m("MULTIPLY", vein, 0.15), clamp=True)
    col, _ = M.ramp(heat, [(0.0, (0.20, 0.015, 0.004)), (0.3, (0.80, 0.10, 0.015)), (0.6, (1.0, 0.42, 0.05)), (1.0, (1.0, 0.86, 0.48))])
    base = M.mix(hot, (0.05, 0.045, 0.045, 1.0), (0.06, 0.025, 0.02, 1.0))
    bsdf = M.principled(Base_Color=base, Metallic=0.9, Roughness=M.mixf(hot, 0.30, 0.45))
    M.l(col, bsdf.inputs["Emission Color"])
    M.l(m("MULTIPLY", m("POWER", heat, 1.4), 10.0 * glow), bsdf.inputs["Emission Strength"])
    return M.surface(bsdf.outputs[0])


def mat_snake_smoke(name, glow=0.35):
    """白蛇的烟影（tube_uv：UV.x 沿长＝米，UV.y 绕一圈）：乳白、半透，正对镜头处实、边上散；
    一片片鳞（Voronoi 的边）若隐若现，沿长有烟的浓淡。略自发光，暗处也认得出。"""
    M = K.Mat(name)
    m = M.math
    lw = M.n("ShaderNodeLayerWeight", Blend=0.5)
    face = m("SUBTRACT", 1.0, lw.outputs["Facing"], clamp=True)
    uv = M.coord("UV")
    mp = M.n("ShaderNodeMapping")
    M.l(uv, mp.inputs["Vector"])
    mp.inputs["Scale"].default_value = (55.0, 12.0, 1.0)
    vor = M.n("ShaderNodeTexVoronoi", Scale=1.0, _feature="DISTANCE_TO_EDGE")
    M.l(mp.outputs["Vector"], vor.inputs["Vector"])
    scl = M.maprange(vor.outputs["Distance"], 0.10, 0.0)
    mp2 = M.n("ShaderNodeMapping")
    M.l(uv, mp2.inputs["Vector"])
    mp2.inputs["Scale"].default_value = (7.0, 1.5, 1.0)
    nz = M.noise(mp2.outputs["Vector"], scale=1.0, detail=5.0, rough=0.6)
    dens = m("MULTIPLY", m("ADD", 0.22, m("MULTIPLY", m("POWER", face, 1.2), 0.78)), m("ADD", 0.5, m("MULTIPLY", M.maprange(nz.outputs["Fac"], 0.35, 0.65), 0.5)))
    a_ = m("MULTIPLY", dens, 0.95, clamp=True)
    col = M.mix(m("MULTIPLY", scl, 0.55), (0.92, 0.92, 0.88, 1.0), (0.46, 0.47, 0.50, 1.0))
    bsdf = M.principled(Base_Color=col, Roughness=0.9, Specular_IOR_Level=0.2)
    M.l(col, bsdf.inputs["Emission Color"])
    bsdf.inputs["Emission Strength"].default_value = glow
    tr = M.n("ShaderNodeBsdfTransparent")
    mx = M.n("ShaderNodeMixShader")
    M.l(a_, mx.inputs[0])
    M.l(tr.outputs[0], mx.inputs[1])
    M.l(bsdf.outputs[0], mx.inputs[2])
    return M.surface(mx.outputs[0])


@scene("sword_mut", name="赤霄", samples=128, grade=dict(WARM_GRADE, exposure=0.98, bloom=0.40, contrast=1.06))
def build_sword_mut(draft):
    """赤霄：一柄烧红的剑横过画面（左下剑柄、右上剑尖，同符剑卡的走向），剑身往前越烧越红，爬满熔金裂纹；
    一条白烟凝成的蛇正被剑斩断：蛇头那截往上翻、张着嘴，两点红眼；蛇尾那截往下坠；断口焦红，迸着火星。"""
    from mathutils import Quaternion, Vector  # noqa: PLC0415

    import card_passives as CP

    sky_gradient(lin("#0A0606"), lin("#3A2018"), 0.7, ground=lin("#050303"))
    rng = np.random.default_rng(19)
    S = ScreenCam(lens=40.0)
    g0, tip = S(0.25, 0.66, 1.20), S(0.86, 0.31, 1.32)
    d = (tip - g0).normalized()
    L = (tip - g0).length
    q = CP.frame_quat(d, (0.0, -0.3, 1.0))
    P.sword("Sword", L=L, W=0.046, T=0.009, steel=mat_hot_steel("HotSteel", L=L), loc=tuple(g0), rot=q.to_euler(), index=1,
            tassel=True, tassel_m=P.mat_silk("Tassel", (0.55, 0.05, 0.02)))
    K.point_light("BladeGlow", tuple(g0.lerp(tip, 0.6) + Vector((0, -0.10, 0.0))), 5.0, radius=0.2, color=(1.0, 0.42, 0.10))
    # 白蛇：剑身中段把它斩成两截。上截从断口往上翻卷到蛇头，下截从断口往下坠到蛇尾（按画面位置摆）
    snake = mat_snake_smoke("Snake")
    up_pts = CP.bez([S(0.555, 0.43, 1.27), S(0.50, 0.33, 1.29), S(0.58, 0.24, 1.31), S(0.52, 0.15, 1.30), S(0.43, 0.15, 1.27)], n=90)
    lo_pts = CP.bez([S(0.585, 0.53, 1.27), S(0.65, 0.63, 1.29), S(0.57, 0.75, 1.31), S(0.64, 0.88, 1.33), S(0.80, 0.95, 1.36),
                     S(0.95, 0.93, 1.40)], n=120)
    R0 = 0.024
    make_obj("SnakeUp", K.tube_uv(up_pts, R0, sides=24, radius_fn=lambda t: 0.92 + 0.10 * math.sin(math.pi * t) - 0.18 * t ** 3,
                                  flat=0.8), snake, index=3)
    make_obj("SnakeLo", K.tube_uv(lo_pts, R0, sides=24, radius_fn=lambda t: 1.0 - 0.93 * t ** 1.3, flat=0.8), snake, index=3)
    # 蛇头：上颌一个扁长的椭球，下颌张开；两点红眼
    hp = Vector(up_pts[-1])
    hd = (Vector(up_pts[-1]) - Vector(up_pts[-6])).normalized()
    hq = CP.frame_quat(hd, (0.0, -0.2, 1.0))
    jaw_q = hq @ Quaternion((0.0, 1.0, 0.0), math.radians(32))
    head = make_obj("SnakeHead", K.ico_cloud([(0, 0, 0)], [1.0], 3), snake, loc=tuple(hp + hd * 0.020 + (hq @ Vector((0, 0, 0.006)))),
                    scale=(0.040, 0.024, 0.014), index=3)
    head.rotation_mode = "QUATERNION"
    head.rotation_quaternion = hq
    jaw = make_obj("SnakeJaw", K.ico_cloud([(0, 0, 0)], [1.0], 3), snake, loc=tuple(hp + hd * 0.016 + (hq @ Vector((0, 0, -0.008)))),
                   scale=(0.034, 0.019, 0.007), index=3)
    jaw.rotation_mode = "QUATERNION"
    jaw.rotation_quaternion = jaw_q
    eye = P.mat_emit("SnakeEye", (1.0, 0.20, 0.06), 16.0)
    for sg in (-1, 1):
        make_obj(f"SnakeEye{sg}", K.ico_cloud([(0, 0, 0)], [0.0042], 2), eye,
                 loc=tuple(hp + hd * 0.030 + (hq @ Vector((0.0, 0.016 * sg, 0.011)))), index=3)
    # 断口：焦红的一圈 + 往外迸的火星（顺着剑走的方向多一些）
    burn = P.mat_emit("Burn", (1.0, 0.36, 0.06), 9.0)
    for nm, pt, nb in (("CutUp", up_pts[0], up_pts[2]), ("CutLo", lo_pts[0], lo_pts[2])):
        c = Vector(pt)
        n_ = (c - Vector(nb)).normalized()
        ob = make_obj(nm, K.torus_build(R0 * 0.85, R0 * 0.22, 32, 8), burn, loc=tuple(c), index=3)
        ob.rotation_mode = "QUATERNION"
        ob.rotation_quaternion = n_.to_track_quat("Z", "Y")
        ob.scale = (1.0, 0.8, 1.0)
    cut = g0.lerp(tip, 0.52)
    ember = K.mat_ember("Ember")
    for k in range(46):
        dd = (d * rng.normal(0.6, 0.5) + Vector(rng.normal(0, 0.6, 3))).normalized()
        p = cut + dd * rng.uniform(0.01, 0.16) * (1.0 if k % 3 else 1.8)
        r0 = rng.uniform(0.0012, 0.0028)
        ob = make_obj(f"Spark{k}", K.lathe_uv([(0.0, -1.0), (0.6, -0.6), (1.0, 0.0), (0.6, 0.6), (0.0, 1.0)], segments=8), ember,
                      loc=tuple(p), scale=(r0, r0, r0 * rng.uniform(2.0, 5.0)), index=3)
        ob.rotation_mode = "QUATERNION"
        ob.rotation_quaternion = dd.to_track_quat("Z", "Y")
    # 几缕从蛇身上散开的烟
    wisp = CP.mat_smoke("Wisp", color=(0.90, 0.90, 0.88), alpha=0.45)
    for k in range(7):
        src = Vector((up_pts if k < 3 else lo_pts)[rng.integers(10, 60)])
        pts = [tuple(src + Vector((0.10 * t + 0.02 * math.sin(7 * t + k), 0.02 * t, 0.06 * t + 0.015 * math.sin(5 * t + k))))
               for t in np.linspace(0, 1, 30)]
        make_obj(f"Wisp{k}", K.ribbon_uv(pts, rng.uniform(0.012, 0.024), width_fn=lambda t: 0.5 + 1.2 * t, ups=[(0, -1, 0)] * 30),
                 wisp, index=4)
    area_oriented("Strip", tuple(g0 + Vector((0.2, -1.0, 0.9))), tuple(g0.lerp(tip, 0.5)), tuple(d), 6.0, 2.4, 0.05, color=(1.0, 0.80, 0.60))
    K.area_light("Moon", (-1.2, 2.6, 2.0), tuple(S(0.55, 0.5, 1.3)), 70.0, 1.2, color=(0.62, 0.72, 1.0))
    K.area_light("Fill", (0.4, -0.6, 0.4), tuple(S(0.55, 0.5, 1.3)), 2.0, 1.0, color=(0.80, 0.82, 0.90))
    S.place(lens=40.0, fstop=5.6, focus=1.3)
    return {"light": "warm"}


@background("sword_mut")
def bg_sword_mut(P_, h, w, rng, k):
    P_.fill_grad("#140B0A", "#0C0808", cloud=0.12)
    K.bg_glow(P_, 0.56, 0.50, 0.50, 0.42, "#6A2410", 0.30)
    bg_clouds(P_, rng, k, [(0.18, 0.03, 0.30, 0.95), (0.86, 0.03, 0.02, 0.60)], "#5A3A30", 0.16)
    K.bg_mist(P_, 0.90, 0.05, "#5A3A30", 0.14, rng, k)
    K.bg_ink(P_, [(0.02, 0.06, 0.26, 0.18, 0.2), (0.98, 0.94, 0.30, 0.20, -0.3)], 0.5)


# ====================================================================== 异化：冻土（霜铃）


@scene("bell_mut", name="冻土", samples=128, grade=dict(COLD_GRADE, exposure=1.04, bloom=0.36))
def build_bell_mut(draft):
    """冻土：霜铃低低悬在地面上方，铃舌一荡，脚下一圈土地冻裂了：裂缝从铃下往外放射，缝里透着冰蓝的冷光，
    一簇簇冰晶从裂缝里长出来（越近铃下越高）；圈里结着白霜，往外越来越稀，圈边散着几块碎冰；圈外是黑土。斜俯看。"""
    from mathutils import Vector  # noqa: PLC0415

    sky_gradient(lin("#05080F"), lin("#1E2C44"), 0.6, ground=lin("#04060A"))
    rng = np.random.default_rng(33)
    SPAN, RF = 4.0, 1.45  # 贴图覆盖 4 米见方；霜圈半径
    crack = P.crack_texture(2048, rng, n_main=11, reach=0.40, branch=0.06, width=3.0)
    Y, X = (np.mgrid[0:2048, 0:2048] / 2048.0 - 0.5) * SPAN
    rr = np.hypot(X, Y)
    fern = K.frost_ferns(2048, 2048, np.random.default_rng(4), n_seeds=260, v_bias=1.0, max_len=150, wrap_x=False)
    edge_n = K.vfx().fft_blur(rng.standard_normal((2048, 2048)), (40.0, 40.0))
    edge_n = edge_n / (np.abs(edge_n).max() + 1e-9)
    inside = 1 - np.clip((rr * (1 + 0.22 * edge_n) - (RF - 0.45)) / 0.55, 0, 1)
    near = np.clip(1 - rr / (RF * 0.55), 0, 1)
    frost = np.clip(inside * (0.30 + 0.70 * fern) + near * 0.55, 0, 1)
    M = K.Mat("FrozenGround")
    m = M.math
    oc = M.coord("Object")
    sep = M.n("ShaderNodeSeparateXYZ")
    M.l(oc, sep.inputs[0])
    cu = M.n("ShaderNodeCombineXYZ")
    M.l(m("ADD", m("DIVIDE", sep.outputs["X"], SPAN), 0.5), cu.inputs["X"])
    M.l(m("ADD", m("DIVIDE", sep.outputs["Y"], SPAN), 0.5), cu.inputs["Y"])

    def tex(arr, name):
        t = M.n("ShaderNodeTexImage", _interpolation="Cubic", _extension="CLIP")
        t.image = K.np_image(name, arr)
        M.l(cu.outputs[0], t.inputs["Vector"])
        s_ = M.n("ShaderNodeSeparateColor")
        M.l(t.outputs["Color"], s_.inputs[0])
        return s_.outputs[0]

    ck, fr = tex(crack, "frozen_crack"), tex(frost, "frozen_frost")
    rad = m("SQRT", m("ADD", m("MULTIPLY", sep.outputs["X"], sep.outputs["X"]), m("MULTIPLY", sep.outputs["Y"], sep.outputs["Y"])))
    n1 = M.noise(oc, scale=3.0, detail=8.0, rough=0.62)
    n2 = M.noise(oc, scale=40.0, detail=6.0, rough=0.7)
    soil = M.mix(M.maprange(n1.outputs["Fac"], 0.3, 0.7), (0.018, 0.016, 0.014, 1.0), (0.055, 0.047, 0.040, 1.0))
    col = M.mix(fr, soil, (0.66, 0.76, 0.90, 1.0))
    # 裂缝：边上压黑（露出底下的土），缝心是冰蓝的光（离铃下越近越亮）
    col = M.mix(M.maprange(ck, 0.05, 0.5), col, (0.006, 0.008, 0.014, 1.0))
    h_ = m("SUBTRACT", m("ADD", m("MULTIPLY", n1.outputs["Fac"], 0.3), m("MULTIPLY", n2.outputs["Fac"], 0.25)), m("MULTIPLY", ck, 1.0))
    nrm = M.bump(m("ADD", h_, m("MULTIPLY", fr, 0.25)), strength=0.6, distance=0.02)
    bsdf = M.principled(Base_Color=col, Roughness=M.mixf(fr, 0.92, 0.50), Normal=nrm, Specular_IOR_Level=0.35)
    bsdf.inputs["Emission Color"].default_value = (0.26, 0.62, 1.0, 1.0)
    glow = m("MULTIPLY", M.maprange(ck, 0.45, 0.95), M.maprange(rad, 0.2, RF + 0.2, 1.0, 0.25))
    M.l(m("MULTIPLY", m("POWER", glow, 1.6), 9.0), bsdf.inputs["Emission Strength"])
    ground_plane("Ground", M.surface(bsdf.outputs[0]), size=14.0, index=0)
    # 冰晶：沿裂缝一簇簇往上长（在贴图上挑裂缝像素），越近中心越高；每簇三五根，往外斜
    ice = K.mat_ice("Ice", tint=(0.78, 0.90, 1.0))
    ys, xs = np.nonzero(crack[::8, ::8] > 0.55)
    order = rng.permutation(len(xs))
    n_cl = 0
    for i in order:
        x, y = (xs[i] * 8 / 2048 - 0.5) * SPAN, (0.5 - ys[i] * 8 / 2048) * SPAN
        r = math.hypot(x, y)
        if r > RF or r < 0.16 or rng.random() > 1.25 - r / RF:
            continue
        out = Vector((x, y, 0.0)).normalized()
        base_L = 0.30 * (1.0 - r / RF) ** 1.2 + 0.04
        for j in range(int(rng.integers(3, 6))):
            L = base_L * rng.uniform(0.45, 1.0)
            dd = (Vector((0, 0, 1.0)) + out * rng.uniform(0.2, 0.8) + Vector((*rng.normal(0, 0.35, 2), 0))).normalized()
            ob = make_obj(f"Xtal{n_cl}_{j}", P.crystal_build(L, L * rng.uniform(0.12, 0.18)), ice,
                          loc=(x + rng.normal(0, 0.015), y + rng.normal(0, 0.015), -0.01), index=3, smooth=False)
            ob.rotation_mode = "QUATERNION"
            ob.rotation_quaternion = dd.to_track_quat("Z", "Y")
        n_cl += 1
        if n_cl >= 70:
            break
    # 圈边的碎冰（冻死的妖物碎成的冰块）
    for k in range(26):
        a = rng.uniform(0, 2 * math.pi)
        r = rng.uniform(RF - 0.15, RF + 0.35)
        L = rng.uniform(0.05, 0.13)
        make_obj(f"Shard{k}", P.crystal_build(L, L * rng.uniform(0.35, 0.6)), ice, loc=(r * math.cos(a), r * math.sin(a), 0.0),
                 rot=(rng.uniform(1.0, 1.8), rng.uniform(-0.4, 0.4), rng.uniform(0, 6.28)), index=3, smooth=False)
    # 霜铃：低低悬在圈心上方，铃舌一荡；挂绳往上出画
    root, H = wind_bell("Bell", loc=(0.0, 0.0, 0.42), rot=(math.radians(-8), math.radians(-12), math.radians(20)), scale=2.0)
    cord_m = P.mat_silk("Cord", (0.42, 0.03, 0.02))
    K._bpy().context.view_layer.update()
    top = root.matrix_world @ Vector((0.0, 0.0, H + 0.05))
    make_obj("Cord", K.tube_uv([tuple(top + Vector((0.0, 0.0, 0.8 * t))) for t in np.linspace(0, 1, 12)], 0.006, sides=8), cord_m,
             index=1)
    K.point_light("CrackGlow", (0.0, 0.0, 0.05), 6.0, radius=0.3, color=(0.35, 0.66, 1.0))
    K.area_light("Moon", (-3.0, 4.0, 5.0), (0, 0, 0), 420.0, 3.0, color=(0.62, 0.74, 1.0))
    K.area_light("Front", (1.5, -4.0, 2.5), (0, 0, 0.3), 45.0, 3.0, color=(0.60, 0.72, 1.0))
    K.area_light("BellKey", (-1.2, -1.4, 1.6), (0, 0, 0.55), 18.0, 1.0, color=(0.75, 0.84, 1.0))
    K.camera((0.0, -3.05, 1.95), (0.0, 0.10, 0.34), lens=33.0, fstop=8.0, focus=3.4)
    return {"light": "cold"}


@background("bell_mut")
def bg_bell_mut(P_, h, w, rng, k):
    P_.fill_grad("#0B1222", "#0E1626", cloud=0.12)
    K.bg_ink(P_, [(0.02, 0.06, 0.26, 0.18, 0.2), (0.98, 0.08, 0.24, 0.18, -0.4)], 0.45)


# ====================================================================== 异化：铁鹤（纸鹤）


def mat_cast_iron(name, tint=(0.40, 0.42, 0.45)):
    """熟铁片：冷灰的金属，锤打的浅坑（Voronoi 凹凸），折缝和背光处泛一点铁锈（AO），面上细的磨痕。"""
    M = K.Mat(name)
    m = M.math
    oc = M.coord("Object")
    n1 = M.noise(oc, scale=90.0, detail=6.0, rough=0.7)
    n2 = M.noise(oc, scale=14.0, detail=4.0)
    vor = M.n("ShaderNodeTexVoronoi", Scale=55.0)
    M.l(oc, vor.inputs["Vector"])
    ao = M.n("ShaderNodeAmbientOcclusion", Distance=0.025, _samples=8)
    cav = M.maprange(ao.outputs["AO"], 0.85, 0.35)
    rust = m("MULTIPLY", cav, M.maprange(n2.outputs["Fac"], 0.42, 0.62))
    col = M.mix(rust, (*tint, 1.0), (0.16, 0.075, 0.04, 1.0))
    rough = M.maprange(n1.outputs["Fac"], 0.3, 0.7, 0.24, 0.42)
    rough = m("ADD", rough, m("MULTIPLY", rust, 0.4))
    nrm = M.bump(m("ADD", m("MULTIPLY", vor.outputs["Distance"], 0.6), m("MULTIPLY", n1.outputs["Fac"], 0.2)), strength=0.18, distance=0.002)
    bsdf = M.principled(Base_Color=col, Metallic=m("SUBTRACT", 1.0, m("MULTIPLY", rust, 0.7)), Roughness=rough, Normal=nrm)
    return M.surface(bsdf.outputs[0])


@scene("crane_mut", name="铁鹤", samples=128, grade=dict(COLD_GRADE, exposure=1.04, bloom=0.34, sat=0.92))
def build_crane_mut(draft):
    """铁鹤：纸鹤的样子折成了铁（同纸鹤卡的姿势：翅膀举成 V、鹤头朝右下一扑），身子是冷灰的铁片折的，
    两翼换成一扇扇锋利的铁羽，从肩往外一片压一片排开；右翼前三片铁羽已经射了出去，拖着冷白的气痕。月光从后上方打轮廓。"""
    from mathutils import Euler, Matrix, Vector  # noqa: PLC0415

    import card_passives as CP

    sky_gradient(lin("#05070C"), lin("#2C3648"), 0.7, ground=lin("#04050A"))
    rng = np.random.default_rng(29)
    iron = mat_cast_iron("Iron")
    body = make_obj("Crane", P.crane_build(neck_up=0.20, tail_up=0.20, wings=False), iron, smooth=False, index=1,
                    bevel=(0.0012, 1))
    body.rotation_euler = Euler((math.radians(8), math.radians(14), math.radians(-20)), "XYZ")
    K._bpy().context.view_layer.update()
    Mw = body.matrix_world.copy()
    feather = lambda L, W: P.blade_build(L, W, 0.0035, tip=0.34, taper=0.45)  # noqa: E731
    shots = []
    for sy in (1, -1):
        root = Vector((0.0, 0.012 * sy, 0.032))
        v = (Vector((-0.08, 0.33 * sy, 0.385)) - root).normalized()  # 肩 → 翅尖（同纸鹤翅的方向）
        u = Vector((-1.0, 0.0, 0.0))
        nw = u.cross(v).normalized() * sy
        u = (u - v * u.dot(v)).normalized()
        n = 8
        # 翅骨：一根扁铁条从肩伸到最外一片铁羽的根
        arm = [tuple(root + v * (0.25 * t)) for t in np.linspace(0, 1, 10)]
        make_obj(f"Arm{sy}", K.tube_uv(arm, 0.007, sides=6, radius_fn=lambda t: 1.0 - 0.4 * t, flat=0.5), iron, index=1, smooth=False)
        ob = K._bpy().data.objects[f"Arm{sy}"]
        ob.matrix_world = Mw @ ob.matrix_world
        for k in range(n):
            s_ = k / (n - 1)
            att = root + v * (0.03 + 0.22 * s_)
            phi = math.radians(12 + 80 * s_ ** 0.85)
            d = (u * math.cos(phi) + v * math.sin(phi)).normalized()
            L = 0.15 + 0.13 * s_ ** 1.2
            wd = nw.cross(d).normalized()
            Mf = Matrix.Translation(att + nw * (0.0025 * k)) @ CP.frame_quat(d, wd).to_matrix().to_4x4()
            if sy < 0 and k >= n - 3:
                shots.append((Mw @ Mf, L))  # 右翼最外三片射出去了
                continue
            fo = make_obj(f"Feather{sy}_{k}", feather(L, 0.044), iron, index=1, smooth=False)
            fo.matrix_world = Mw @ Mf
    # 射出去的铁羽：顺着各自的方向往右前方飞出一段，拖着冷白的气痕
    for k, (Mf, L) in enumerate(shots):
        d0 = (Mf.to_3x3() @ Vector((1, 0, 0))).normalized()
        fly = (d0 + Vector((0.9, -0.5, -0.35))).normalized()
        p0 = Mf.translation
        p1 = p0 + fly * (0.30 + 0.16 * k)
        q = CP.frame_quat(fly, Mf.to_3x3() @ Vector((0, 0, 1)))
        fo = make_obj(f"Shot{k}", feather(L, 0.044), iron, index=1, smooth=False)
        fo.rotation_mode = "QUATERNION"
        fo.location, fo.rotation_quaternion = tuple(p1), q
        pts = [tuple(p1 - fly * (0.42 * t) + Vector((0, 0, 0.02 * math.sin(3 * t + k)))) for t in np.linspace(0, 1, 30)]
        make_obj(f"Trail{k}", K.ribbon_uv(pts, 0.022, width_fn=lambda t: 1 - 0.85 * t),
                 K.mat_wind(f"TrailM{k}", strength=1.5, seed=k * 1.7, color=(0.82, 0.90, 1.0)), index=3)
    # 几星打铁迸出的火花（冷光里一点暖）
    ember = K.mat_ember("Ember")
    for k in range(10):
        p = Vector((rng.normal(0.30, 0.15), rng.normal(-0.05, 0.1), rng.normal(0.05, 0.12)))
        make_obj(f"Spark{k}", K.ico_cloud([(0, 0, 0)], [rng.uniform(0.0012, 0.0022)], 1), ember, loc=tuple(p), index=3)
    K.area_light("Moon", (-0.9, 1.0, 1.4), (0, 0, 0.1), 90.0, 1.4, color=(0.80, 0.88, 1.0))
    K.area_light("Rim", (1.1, 0.9, 0.4), (0, 0, 0.1), 40.0, 0.8, color=(0.66, 0.78, 1.0))
    K.area_light("Sky", (0.0, -0.6, 1.6), (0, 0, 0.1), 30.0, 2.0, color=(0.70, 0.78, 0.95))
    K.area_light("Front", (-0.5, -1.5, 0.2), (0, 0, 0.1), 8.0, 1.2, color=(0.70, 0.76, 0.95))
    K.camera((0.05, -1.50, 0.24), (0.02, 0.0, 0.09), lens=50.0, fstop=4.0, focus=1.48)
    return {"light": "cold"}


@background("crane_mut")
def bg_crane_mut(P_, h, w, rng, k):
    P_.fill_grad("#0B0F18", "#0E131D", cloud=0.12)
    K.bg_glow(P_, 0.62, 0.36, 0.45, 0.40, "#3E4E68", 0.30)
    K.bg_moon(P_, 0.70, 0.30, 0.07, rng, k, color="#E4EAF2", halo="#7890B6", a=0.75, halo_a=0.35)
    bg_clouds(P_, rng, k, [(0.62, 0.03, 0.05, 0.60), (0.72, 0.02, 0.30, 0.95)], "#4C5A74", 0.16)
    K.bg_mountains(P_, [(0.90, [(0.15, 0.10, 0.14, 0.12), (0.52, 0.06, 0.16, 0.14), (0.86, 0.11, 0.12, 0.14)], "#151C2C", 0.85, 0.08, 5.0)],
                   rng, k)
    K.bg_ink(P_, [(0.02, 0.06, 0.26, 0.18, 0.2), (0.02, 0.96, 0.30, 0.20, -0.2)], 0.45)


# ====================================================================== 异化：竹印（山印）


def mat_bamboo_green(name, node_gap=0.55):
    """青竹（物体坐标 Z 沿竹竿，节距 node_gap）：竹身青绿透一点黄，节下一圈白粉、节上一道深环，纵向细纹，半光带清漆似的高光。"""
    M = K.Mat(name)
    m = M.math
    oc = M.coord("Object")
    sep = M.n("ShaderNodeSeparateXYZ")
    M.l(oc, sep.inputs[0])
    seg = m("FRACT", m("DIVIDE", sep.outputs["Z"], node_gap))
    ring = m("ADD", M.maprange(seg, 0.0, 0.025), M.maprange(seg, 1.0, 0.985), clamp=True)
    ring = m("SUBTRACT", 1.0, ring)  # 1 = 节上那一道
    powder = m("MULTIPLY", M.maprange(seg, 0.03, 0.16), M.maprange(seg, 0.24, 0.10))  # 节下的白粉
    mp = M.n("ShaderNodeMapping")
    M.l(oc, mp.inputs["Vector"])
    mp.inputs["Scale"].default_value = (70.0, 70.0, 1.2)
    fib = M.noise(mp.outputs["Vector"], scale=3.0, detail=6.0, rough=0.6)
    blot = M.noise(oc, scale=2.5, detail=3.0)
    col = M.mix(M.maprange(fib.outputs["Fac"], 0.3, 0.7), (0.10, 0.30, 0.07, 1.0), (0.24, 0.48, 0.12, 1.0))
    col = M.mix(M.maprange(blot.outputs["Fac"], 0.5, 0.75), col, (0.42, 0.50, 0.14, 1.0))
    col = M.mix(m("MULTIPLY", powder, 0.7), col, (0.70, 0.74, 0.66, 1.0))
    col = M.mix(m("MULTIPLY", ring, 0.9), col, (0.05, 0.10, 0.03, 1.0))
    nrm = M.bump(m("ADD", m("MULTIPLY", fib.outputs["Fac"], 0.15), m("MULTIPLY", ring, 1.0)), strength=0.4, distance=0.01)
    bsdf = M.principled(Base_Color=col, Roughness=M.mixf(powder, 0.32, 0.7), Coat_Weight=0.5, Coat_Roughness=0.15, Normal=nrm)
    return M.surface(bsdf.outputs[0])


def mat_sheath(name):
    """笋箨：干的褐色箨叶，带深色斑点和纵纹，边缘发白，略透光。"""
    M = K.Mat(name)
    m = M.math
    oc = M.coord("Object")
    vor = M.n("ShaderNodeTexVoronoi", Scale=9.0)
    M.l(oc, vor.inputs["Vector"])
    spot = M.maprange(vor.outputs["Distance"], 0.18, 0.08)
    mp = M.n("ShaderNodeMapping")
    M.l(oc, mp.inputs["Vector"])
    mp.inputs["Scale"].default_value = (40.0, 40.0, 2.0)
    fib = M.noise(mp.outputs["Vector"], scale=3.0, detail=5.0)
    col = M.mix(M.maprange(fib.outputs["Fac"], 0.35, 0.65), (0.30, 0.18, 0.08, 1.0), (0.46, 0.32, 0.16, 1.0))
    col = M.mix(m("MULTIPLY", spot, 0.85), col, (0.08, 0.04, 0.02, 1.0))
    bsdf = M.principled(Base_Color=col, Roughness=0.62, Subsurface_Weight=0.15, Sheen_Weight=0.3)
    return M.surface(bsdf.outputs[0])


@scene("seal_mut", name="竹印", samples=128, grade=EARTH_GRADE, fog=(10.0, 18.0))
def build_seal_mut(draft):
    """竹印：地面破开，一根碗口粗的巨竹带着泥块碎土冲天而起，把那方青石大印顶飞在半空（印面朝下斜翻着，露出朱砂“山”字）；
    竹节白粉、竹身青绿，下面两节还裹着褐色的笋箨，往外翻开；地皮被顶起一圈碎块。镜头贴地往上看。"""
    from mathutils import Vector  # noqa: PLC0415

    sky_gradient(lin("#07080C"), lin("#3A3226"), 0.7, ground=lin("#060505"))
    rng = np.random.default_rng(23)
    face_img = K.np_image("seal_face", P.seal_shan(1024))
    stone = P.mat_stone("SealStone", color=(0.13, 0.15, 0.13), scale=3.5, cavity=1.0, bump=1.0, bump_dist=0.04)
    bamboo = mat_bamboo_green("Bamboo")
    # 竹：从地下斜着冲上来（微弯），越往上略细
    R = 0.40
    base, top = Vector((-0.20, 0.50, -0.8)), Vector((0.30, 0.30, 3.05))
    axis = (top - base).normalized()

    def cpt(t):
        return base.lerp(top, t) + Vector((0.10 * math.sin(t * 2.6), 0.0, 0.0))

    pts = [tuple(cpt(t)) for t in np.linspace(0, 1, 80)]
    make_obj("Culm", K.tube_uv(pts, R, sides=48, radius_fn=lambda t: 1.0 - 0.10 * t), bamboo, index=1)
    # 竹节：节上一道凸起的环（和材质的节距对齐：世界 Z 每 0.55 米一节）
    for k in range(0, 6):
        z = 0.55 * k + 0.02
        t = (z - base.z) / (top.z - base.z)
        if not 0.0 < t < 0.97:
            continue
        p = cpt(t)
        ob = make_obj(f"Node{k}", K.torus_build(R * (1 - 0.10 * t) + 0.004, 0.022, 72, 10), bamboo, loc=tuple(p), index=1)
        ob.rotation_mode = "QUATERNION"
        ob.rotation_quaternion = axis.to_track_quat("Z", "Y")
    # 下面两节裹着的笋箨：从节上包住大半圈，往上收尖，梢往外翻
    sheath_m = mat_sheath("Sheath")
    for j, (z0, a0, span) in enumerate(((0.02, 2.4, 3.6), (0.57, -0.8, 3.2), (1.12, 1.6, 2.4))):
        t0 = (z0 - base.z) / (top.z - base.z)
        c0 = cpt(t0)
        Ls = 0.85 - 0.12 * j

        def sheath(bm, c0=c0, a0=a0, span=span, Ls=Ls, j=j):
            uvl = bm.loops.layers.uv.new("UVMap")
            nu, nv = 24, 14
            rows = []
            for iv in range(nv + 1):
                v = iv / nv
                half = 0.5 * span * (1 - v ** 1.4)  # 往上收尖
                peel = 0.18 * v ** 2.2  # 梢往外翻
                row = []
                for iu in range(nu + 1):
                    u = iu / nu
                    a = a0 + (u - 0.5) * 2 * half
                    rr = R * 1.03 + 0.006 + peel + 0.01 * j
                    row.append(bm.verts.new(c0 + Vector((rr * math.cos(a), rr * math.sin(a), Ls * v))))
                rows.append(row)
            for iv in range(nv):
                for iu in range(nu):
                    f = bm.faces.new((rows[iv][iu], rows[iv][iu + 1], rows[iv + 1][iu + 1], rows[iv + 1][iu]))
                    for lp, uv in zip(f.loops, ((iu / nu, iv / nv), ((iu + 1) / nu, iv / nv), ((iu + 1) / nu, (iv + 1) / nv),
                                               (iu / nu, (iv + 1) / nv))):
                        lp[uvl].uv = uv

        ob = make_obj(f"Sheath{j}", sheath, sheath_m, index=1)
        sol = ob.modifiers.new("Sol", "SOLIDIFY")
        sol.thickness = 0.008
    # 石印：被竹梢顶住一角，往后翻，印面朝下、朝镜头斜着露出来
    P.seal_block("Seal", size=1.7, height=1.8, stone_m=stone,
                 face_m=P.mat_seal_face("SealFace", face_img, stone=(0.05, 0.055, 0.05), paste=(0.40, 0.03, 0.02)),
                 loc=tuple(top + Vector((-0.30, 0.10, 0.30))), rot=(math.radians(-36), math.radians(22), math.radians(-14)), index=1)
    crack = K.np_image("crack_mut", P.crack_texture(2048, rng, n_main=12, reach=0.30, width=4.0))
    ground_plane("Ground", P.mat_ground_crack("GroundM", crack, base=(0.014, 0.012, 0.010), glow=((0.55, 0.85, 0.35), 0.35),
                                              uv_from_object=(14.0, 14.0), fade=2.5, spec=0.08), size=14.0, loc=(-0.2, 0.5, 0), index=0)
    # 掀起的地皮：一圈翘起来的土块（扁），翘口朝竹
    soil = P.mat_stone("Clod", color=(0.075, 0.055, 0.040), scale=10.0)
    for i in range(16):
        a = 2 * math.pi * i / 16 + rng.normal(0, 0.12)
        r = R + rng.uniform(0.15, 0.55)
        c = Vector((base.x + r * math.cos(a), 0.5 + r * math.sin(a), 0.03))
        sz = rng.uniform(0.18, 0.34)
        ob = make_obj(f"Slab{i}", K.box_build(sz, sz * rng.uniform(0.6, 1.0), 0.06), soil, loc=tuple(c), index=2, smooth=False,
                      bevel=(0.01, 1))
        ob.rotation_euler = (math.radians(rng.uniform(25, 60)) * math.sin(a), -math.radians(rng.uniform(25, 60)) * math.cos(a), a)
    # 迸起的泥块和碎土：围着竹根往上迸，挂在竹身上往下掉
    for i in range(80):
        a = rng.uniform(0, 2 * math.pi)
        r = rng.uniform(0.45, 1.6)
        z = abs(rng.normal(0, 0.55)) * (1.7 - r) + 0.05
        p = Vector((base.x + r * math.cos(a), 0.5 + r * math.sin(a) * 0.8, z))
        sz = rng.uniform(0.025, 0.10)
        ob = make_obj(f"Clod{i}", K.ico_cloud([(0, 0, 0)], [sz], 1), soil, loc=tuple(p), index=2, smooth=False)
        ob.scale = tuple(rng.uniform(0.6, 1.4, 3))
        ob.rotation_euler = tuple(rng.uniform(0, 6.28, 3))
    for i in range(30):
        t = rng.uniform(0.22, 0.42)
        a = rng.uniform(0, 2 * math.pi)
        p = cpt(t) + Vector((R * 1.05 * math.cos(a), R * 1.05 * math.sin(a), rng.normal(0, 0.15)))
        make_obj(f"Mud{i}", K.ico_cloud([(0, 0, 0)], [rng.uniform(0.03, 0.08)], 1), soil, loc=tuple(p), index=2, smooth=False)
    K.area_light("Moon", (-4.0, 6.0, 7.0), (0, 0, 1.5), 900.0, 3.0, color=(0.66, 0.76, 1.0))
    K.area_light("Rim", (5.0, 5.0, 3.0), (0, 0, 2.0), 320.0, 2.0, color=(0.62, 0.72, 1.0))
    K.area_light("Front", (-2.5, -6.5, 2.0), (0, 0, 1.6), 140.0, 4.0, color=(0.70, 0.76, 0.95))
    K.area_light("Under", (0.3, -2.2, 0.3), tuple(top + Vector((-0.3, 0.1, 0.3))), 90.0, 2.0, color=(1.0, 0.78, 0.55))
    K.camera((0.5, -6.9, 0.50), (0.02, 0.3, 2.05), lens=28.0, fstop=8.0, focus=6.9)
    return {"light": "earth"}


@background("seal_mut")
def bg_seal_mut(P_, h, w, rng, k):
    P_.fill_grad("#0D0F16", "#1A1714", cloud=0.12)
    K.bg_glow(P_, 0.50, 0.55, 0.55, 0.35, "#4E5A3A", 0.26)
    K.bg_mountains(P_, [(0.80, [(0.12, 0.12, 0.12, 0.12), (0.34, 0.07, 0.12, 0.10), (0.80, 0.14, 0.12, 0.14), (0.97, 0.08, 0.10, 0.10)],
                         "#2A2622", 0.7, 0.10, 6.0, "#7C6A56")], rng, k)
    bg_clouds(P_, rng, k, [(0.18, 0.03, 0.25, 0.80), (0.26, 0.02, 0.50, 0.95)], "#5A5248", 0.18)
    K.bg_mist(P_, 0.80, 0.04, "#8C7A64", 0.18, rng, k)
    K.bg_ink(P_, [(0.02, 0.06, 0.26, 0.18, 0.2), (0.98, 0.08, 0.24, 0.18, -0.4)], 0.45)


# ====================================================================== 合璧：百鸟朝凤（纸鹤 + 灯火）


def mat_fire_ribbon(name, strength=6.0, seed=0.0, alpha=1.0):
    """一根火羽（ribbon，UV.x 0 = 羽根 → 1 = 羽梢，UV.y 横跨）：根部白金、中段橙、梢上暗红；两边柔、梢上散成一缕缕。"""
    M = K.Mat(name)
    m = M.math
    uv = M.coord("UV")
    sep = M.n("ShaderNodeSeparateXYZ")
    M.l(uv, sep.inputs[0])
    u, v = sep.outputs["X"], sep.outputs["Y"]
    col, _ = M.ramp(u, [(0.0, (1.0, 0.92, 0.70)), (0.25, (1.0, 0.62, 0.18)), (0.6, (1.0, 0.32, 0.06)), (1.0, (0.60, 0.07, 0.02))])
    across = m("POWER", m("SINE", m("MULTIPLY", v, math.pi)), 0.8)
    mp = M.n("ShaderNodeMapping")
    M.l(uv, mp.inputs["Vector"])
    mp.inputs["Scale"].default_value = (2.0, 16.0, 1.0)
    nz = M.noise(mp.outputs["Vector"], scale=1.0, detail=6.0, rough=0.65, w=seed)
    streak = M.maprange(nz.outputs["Fac"], 0.35, 0.65, interp="SMOOTHSTEP")
    tail = m("POWER", m("SUBTRACT", 1.0, u, clamp=True), 0.7)
    a_ = m("MULTIPLY", across, m("ADD", m("MULTIPLY", streak, m("MULTIPLY", u, 0.9)), m("SUBTRACT", 1.0, m("MULTIPLY", u, 0.9))))
    a_ = m("MULTIPLY", m("MULTIPLY", a_, m("ADD", tail, 0.15)), alpha, clamp=True)
    emi = M.n("ShaderNodeEmission")
    M.l(col, emi.inputs["Color"])
    M.l(m("MULTIPLY", a_, m("MULTIPLY", m("ADD", m("SUBTRACT", 1.0, u), 0.3), strength)), emi.inputs["Strength"])
    tr = M.n("ShaderNodeBsdfTransparent")
    add = M.n("ShaderNodeAddShader")
    M.l(tr.outputs[0], add.inputs[0])
    M.l(emi.outputs[0], add.inputs[1])
    return M.surface(add.outputs[0])


def mat_flame_feather(name, strength=8.0, seed=0.0, hot=(1.0, 0.88, 0.58), mid=(1.0, 0.48, 0.10), cool=(0.72, 0.10, 0.02)):
    """一片火羽（ribbon：UV.x 0 羽根 → 1 羽梢，UV.y 横跨）：羽根白金、往梢渐橙到暗红；中间一道亮羽轴，
    羽片实，边上被噪声咬成一缕缕火舌，梢上散开。只发光（加在透明上）。"""
    M = K.Mat(name)
    m = M.math
    uv = M.coord("UV")
    sep = M.n("ShaderNodeSeparateXYZ")
    M.l(uv, sep.inputs[0])
    u, v = sep.outputs["X"], sep.outputs["Y"]
    vv = m("ABSOLUTE", m("SUBTRACT", m("MULTIPLY", v, 2.0), 1.0))  # 0 羽轴 → 1 羽边
    mp = M.n("ShaderNodeMapping")
    M.l(uv, mp.inputs["Vector"])
    mp.inputs["Scale"].default_value = (3.0, 9.0, 1.0)
    nz = M.noise(mp.outputs["Vector"], scale=1.0, detail=5.0, rough=0.62, w=seed)
    edge = m("ADD", vv, m("MULTIPLY", m("SUBTRACT", nz.outputs["Fac"], 0.5), m("ADD", 0.25, m("MULTIPLY", u, 0.6))))
    body = M.maprange(edge, 0.95, 0.45, interp="SMOOTHSTEP")
    shaft = m("MULTIPLY", M.maprange(vv, 0.12, 0.0), M.maprange(u, 0.9, 0.3))
    a_ = m("MULTIPLY", body, M.maprange(u, 1.0, 0.72))
    col, _ = M.ramp(u, [(0.0, (*hot, 1.0)), (0.45, (*mid, 1.0)), (1.0, (*cool, 1.0))])
    col = M.mix(m("MULTIPLY", shaft, 0.8), col, (*hot, 1.0))
    st = m("ADD", m("MULTIPLY", a_, m("SUBTRACT", 1.0, m("MULTIPLY", u, 0.55))), m("MULTIPLY", shaft, 0.6))
    emi = M.n("ShaderNodeEmission")
    M.l(col, emi.inputs["Color"])
    M.l(m("MULTIPLY", st, strength), emi.inputs["Strength"])
    tr = M.n("ShaderNodeBsdfTransparent")
    add = M.n("ShaderNodeAddShader")
    M.l(tr.outputs[0], add.inputs[0])
    M.l(emi.outputs[0], add.inputs[1])
    return M.surface(add.outputs[0])


def feather_width(t):
    """火羽的宽度：羽根窄一点，四成处最宽，往梢收成尖。"""
    if t < 0.38:
        return 0.40 + 0.60 * K.smoothstep(0.0, 0.38, t)
    return max(1.0 - ((t - 0.38) / 0.62) ** 1.5, 0.0)


@scene("phoenix", name="百鸟朝凤", samples=128, grade=dict(WARM_GRADE, exposure=0.98, bloom=0.46, sat=1.06))
def build_phoenix(draft):
    """百鸟朝凤：一只火凤居中展翅：两翼举起往外张开，每翼一排火羽从翅骨往下、往外披开（外侧的长）；
    颈往上弯，头朝左，冠羽三根往后飘；五根长尾往下弯着散开，梢上一点凤眼。四周纸鹤绕着凤飞、鹤头都朝着它，
    远处一群墨点小鸟（背景）也朝它飞来；火羽往下洒落成火星。按画面位置摆（ScreenCam）。"""
    from mathutils import Vector  # noqa: PLC0415

    import card_passives as CP

    sky_gradient(lin("#07060A"), lin("#2E2026"), 0.6, ground=lin("#040304"))
    rng = np.random.default_rng(88)
    S = ScreenCam(lens=40.0)
    D = 2.2
    W = D * S.k  # 画面宽（米）
    n_f = [0]

    def plume(pts2, width, strength=8.0, depth=D, wfn=feather_width, **kw):
        """pts2：画面坐标的折线（x、y 按 0..1）；width：画面宽的比例。"""
        n_f[0] += 1
        nm = f"Plume{n_f[0]}"
        pts = [tuple(S(x, y, depth)) for x, y in pts2]
        make_obj(nm, K.ribbon_uv(pts, width * W, ups=[(0, 1, 0)] * len(pts), width_fn=wfn),
                 mat_flame_feather(nm + "M", strength=strength, seed=n_f[0] * 1.37, **kw), index=4)

    def curve(p0, d, L, bend, n=36):
        d = np.asarray(d, float)
        d = d / np.linalg.norm(d)
        nrm = np.array([-d[1], d[0]])
        return [tuple(np.asarray(p0) + d * L * t + nrm * bend * L * t * t) for t in np.linspace(0, 1, n)]

    # 两翼：翅骨从肩往外上拱到翅尖；火羽从翅骨披下来，内侧朝下、外侧朝外下，越往外越长
    for sg in (-1, 1):
        arm = CP.bez([(0.50 + sg * 0.035, 0.45), (0.50 + sg * 0.15, 0.31), (0.50 + sg * 0.27, 0.255), (0.50 + sg * 0.36, 0.27)], n=80)
        nf = 15
        for k in range(nf):
            s_ = k / (nf - 1)
            p0 = arm[int(s_ * 72)]
            ang = math.radians(92 - 62 * s_ ** 1.1)  # 画面里：90° 朝下，越往外越朝外
            d = (sg * math.cos(ang), math.sin(ang))
            L = 0.15 + 0.17 * s_ ** 1.3
            plume(curve(p0, d, L, -sg * 0.18), 0.050 + 0.012 * s_, strength=7.0 + 3.0 * (1 - s_))
        for k in range(10):  # 覆羽：短、亮，盖在翅骨上
            s_ = (k + 0.5) / 10
            p0 = arm[int(s_ * 76)]
            ang = math.radians(100 - 50 * s_)
            d = (sg * math.cos(ang), math.sin(ang))
            plume(curve(p0, d, 0.07 + 0.04 * s_, -sg * 0.1), 0.040, strength=11.0, depth=D - 0.02)
        plume(arm[::2], 0.022, strength=14.0, depth=D - 0.03, wfn=lambda t: 1.0 - 0.7 * t)  # 翅骨一道亮边
    # 长尾：五根往下弯着散开
    for k in range(5):
        sp = (k - 2) / 2.0
        p0 = (0.50 + 0.01 * sp, 0.56)
        pts2 = [(p0[0] + 0.30 * sp * t + 0.05 * sp * math.sin(t * 4.0), p0[1] + 0.40 * t - 0.06 * t * t * (1 - abs(sp)))
                for t in np.linspace(0, 1, 48)]
        plume(pts2, 0.050, strength=7.0, wfn=lambda t: 0.5 + 0.5 * math.sin(math.pi * min(1.0, 0.2 + t)) ** 0.5)
        eye = S(*pts2[-6], D - 0.01)
        make_obj(f"TailEye{k}", K.torus_build(0.012 * W, 0.0045 * W, 24, 8), P.mat_emit(f"TailEyeM{k}", (1.0, 0.80, 0.40), 14.0),
                 loc=tuple(eye), rot=(math.radians(90), 0, 0), index=4)
    # 身子、颈：一束往上弯的火，头朝左
    neck = CP.bez([(0.50, 0.60), (0.505, 0.48), (0.49, 0.34), (0.46, 0.26), (0.445, 0.215)], n=50)
    plume(neck, 0.085, strength=12.0, depth=D - 0.04, wfn=lambda t: (1.0 - 0.62 * t) * (0.7 + 0.3 * math.sin(math.pi * min(1, t * 2))))
    core = S(0.50, 0.50, D - 0.05)
    make_obj("Core", K.ico_cloud([(0, 0, 0)], [1.0], 3), P.mat_emit("CoreM", (1.0, 0.80, 0.45), 9.0), loc=tuple(core),
             scale=(0.030 * W, 0.02, 0.055 * W), index=4)
    head = S(0.44, 0.205, D - 0.05)
    make_obj("Head", K.ico_cloud([(0, 0, 0)], [1.0], 3), P.mat_emit("HeadM", (1.0, 0.86, 0.58), 12.0), loc=tuple(head),
             scale=(0.024 * W, 0.012, 0.016 * W), rot=(0, math.radians(12), 0), index=4)
    make_obj("Beak", K.lathe_uv([(0.0, 0.0), (0.007 * W, 0.004 * W), (0.0, 0.03 * W)], segments=10), K.mat_gold("BeakM", color=(1.0, 0.72, 0.28)),
             loc=tuple(head + Vector((-0.018 * W, -0.01, -0.002 * W))), rot=(0, math.radians(-100), 0), index=4)
    make_obj("Eye", K.ico_cloud([(0, 0, 0)], [0.0035 * W], 2), P.mat_emit("EyeM", (0.25, 0.04, 0.02), 1.0),
             loc=tuple(head + Vector((-0.008 * W, -0.03, 0.003 * W))), index=4)
    for k in range(3):  # 冠羽：往后上飘
        a = math.radians(30 + 22 * k)
        hx, hy = 0.44, 0.205
        plume(curve((hx + 0.008, hy - 0.006), (math.cos(a), -math.sin(a)), 0.10 + 0.02 * k, 0.35), 0.020, strength=10.0, depth=D - 0.05)
    K.point_light("PhoenixLight", tuple(S(0.5, 0.45, D - 0.3)), 60.0, radius=0.3, color=(1.0, 0.58, 0.24))
    # 四周朝凤的纸鹤：一圈，鹤头朝着凤（略带绕飞）
    paper = P.mat_crane_paper("Paper", emit=((1.0, 0.80, 0.55), 0.10))
    ring = [(0.12, 0.52, 2.6), (0.20, 0.80, 2.0), (0.40, 0.90, 2.8), (0.78, 0.86, 2.2), (0.90, 0.56, 2.7), (0.86, 0.36, 3.2),
            (0.14, 0.34, 3.4), (0.64, 0.12, 3.6), (0.30, 0.10, 3.8)]
    tgt = S(0.5, 0.45, D)
    for k, (x, y, dep) in enumerate(ring):
        p = S(x, y, dep)
        d = (tgt - p).normalized()
        side = d.cross(Vector((0, 1, 0))).normalized()
        dd = (d * 0.8 + side * 0.45 * (1 if x < 0.5 else -1)).normalized()
        ob = make_obj(f"Crane{k}", P.crane_build(wing_up=rng.uniform(0.10, 0.30), neck_up=0.15, tail_up=0.17, scale=0.55), paper,
                      smooth=False, index=2)
        ob.location = tuple(p)
        ob.rotation_mode = "QUATERNION"
        ob.rotation_quaternion = CP.frame_quat(dd, (0, 0, 1))
    # 洒落的火星和几片小火羽
    ember = K.mat_ember("Ember")
    for k in range(70):
        x, y = rng.uniform(0.15, 0.85), rng.uniform(0.40, 0.98)
        make_obj(f"Spark{k}", K.ico_cloud([(0, 0, 0)], [rng.uniform(0.0025, 0.006)], 1), ember, loc=tuple(S(x, y, D + rng.normal(0, 0.2))),
                 index=4)
    for k in range(6):
        x, y = rng.uniform(0.22, 0.78), rng.uniform(0.62, 0.92)
        a = rng.uniform(0, 2 * math.pi)
        plume(curve((x, y), (math.cos(a), math.sin(a)), 0.035, 0.4, n=12), 0.016, strength=8.0)
    K.area_light("Rim", tuple(S(0.5, 0.45, D) + Vector((-2.0, 2.0, 1.5))), tuple(S(0.5, 0.45, D)), 40.0, 1.5, color=(0.55, 0.65, 1.0))
    S.place(lens=40.0, fstop=8.0, focus=D)
    return {"light": "warm"}


@background("phoenix")
def bg_phoenix(P_, h, w, rng, k):
    P_.fill_grad("#120B0C", "#0C0808", cloud=0.12)
    K.bg_glow(P_, 0.50, 0.46, 0.55, 0.45, "#6A2A10", 0.34)
    K.bg_glow(P_, 0.50, 0.42, 0.24, 0.24, "#C26A20", 0.24)
    bg_clouds(P_, rng, k, [(0.80, 0.03, 0.05, 0.95), (0.88, 0.02, 0.20, 0.80)], "#5A3A30", 0.18)
    # 远处一群墨点小鸟，都朝着中间飞
    for _ in range(24):
        a = rng.uniform(0, 2 * math.pi)
        r = rng.uniform(0.22, 0.42)
        cx, cy = 0.5 + r * math.cos(a), 0.46 + r * 0.72 * math.sin(a)
        if (cx < 0.18 and cy < 0.24) or (cx > 0.80 and cy < 0.22):
            continue
        sz = rng.uniform(0.010, 0.018) * w
        to_c = math.atan2(0.46 * h - cy * h, 0.5 * w - cx * w)
        tilt = 0.35 * math.sin(to_c)
        x0, y0 = cx * w, cy * h
        for sg in (-1, 1):  # 两笔翅膀：一个扁的“人”字
            pts = [(x0 + sg * sz * t * math.cos(tilt), y0 - sz * 0.45 * math.sin(math.pi * t) + sg * sz * t * math.sin(tilt) * 0.6)
                   for t in np.linspace(0, 1, 8)]
            P_.darken(P_.dry_stroke(pts, 0.0028 * w, dry=0.2), 0.75)
    K.bg_ink(P_, [(0.02, 0.06, 0.26, 0.18, 0.2), (0.98, 0.08, 0.24, 0.18, -0.4)], 0.5)


# ====================================================================== 合璧：万剑冢（山印 + 符剑）


def low_spec(mat, level=0.12):
    """把材质里 Principled 的镜面压低（贴地看时土地反出一片天光）。"""
    for n in mat.node_tree.nodes:
        if n.bl_idname == "ShaderNodeBsdfPrincipled":
            n.inputs["Specular IOR Level"].default_value = level
    return mat


@scene("sword_grove", name="万剑冢", samples=128, grade=dict(COLD_GRADE, exposure=1.05, bloom=0.32), fog=(8.0, 18.0))
def build_sword_grove(draft):
    """万剑冢：一座土冢上插满了剑，剑柄高低错落像一片竹林；冢后一轮满月，剑林逆着月光，剑刃镶一线冷光，
    长长的剑影朝镜头斜过来；近处左右几把大剑（剑格的金、剑穗的红一点亮）把画面框住。镜头贴地平看。"""
    from mathutils import Euler, Vector  # noqa: PLC0415

    sky_gradient(lin("#05080F"), lin("#33496C"), 0.9, ground=lin("#04060A"))
    rng = np.random.default_rng(41)
    MC, MR, MH = Vector((0.0, 8.0)), (3.4, 2.6), 1.15  # 土冢：中心、半径、高

    def ground_z(x, y):
        return MH * math.exp(-(((x - MC.x) / MR[0]) ** 2 + ((y - MC.y) / MR[1]) ** 2)) + 0.04 * math.sin(x * 1.7 + y * 0.9)

    def terrain(bm):
        nx, ny = 160, 160
        xs, ys = np.linspace(-12, 12, nx), np.linspace(-3, 24, ny)
        vs = [[bm.verts.new((x, y, ground_z(x, y))) for x in xs] for y in ys]
        for j in range(ny - 1):
            for i in range(nx - 1):
                bm.faces.new((vs[j][i], vs[j][i + 1], vs[j + 1][i + 1], vs[j + 1][i]))

    earth = low_spec(P.mat_stone("Earth", color=(0.050, 0.046, 0.040), rough=0.95, scale=4.0, moss=0.25, bump=0.8, bump_dist=0.02))
    make_obj("Ground", terrain, earth, index=0)
    steel = P.mat_steel("Steel", tint=(0.74, 0.77, 0.82), rough=0.18, dark=0.25)
    gold = K.mat_gold("Gold", worn=0.6)
    tassel = P.mat_silk("Tassel", (0.45, 0.04, 0.025))
    n = [0]

    def plant(x, y, bury, tilt_sd=0.10, scale=1.0, tassel_p=0.45):
        tilt = Euler((rng.normal(0, tilt_sd), rng.normal(0, tilt_sd), rng.uniform(0, 6.28)))
        d = Vector((0, 0, -1))
        d.rotate(tilt)
        loc = Vector((x, y, ground_z(x, y))) - d * ((0.74 - bury) * scale)
        P.sword(f"S{n[0]}", steel=steel, gold=gold, tassel_m=tassel, loc=tuple(loc), rot=d.to_track_quat("X", "Z").to_euler(),
                scale=scale, index=1, tassel=rng.random() < tassel_p)
        n[0] += 1

    # 冢上的剑林：在土冢的椭圆里撒点（互相隔开），越靠冢顶越密
    pts = []
    for _ in range(4000):
        u, v = rng.uniform(-1, 1, 2)
        if u * u + v * v > 1.0:
            continue
        x, y = MC.x + u * MR[0] * 1.15, MC.y + v * MR[1] * 1.15
        if any((x - a) ** 2 + (y - b) ** 2 < 0.36 ** 2 for a, b in pts):
            continue
        pts.append((x, y))
        if len(pts) >= 70:
            break
    for x, y in pts:
        plant(x, y, rng.uniform(0.05, 0.50), scale=rng.uniform(0.9, 1.25))
    # 冢前散着的剑，和近处框住画面的几把大剑（斜插得厉害些）
    for x, y in ((-2.6, 4.2), (2.4, 4.6), (-1.2, 5.0), (1.0, 4.4), (3.6, 6.0), (-3.8, 6.4)):
        plant(x, y, rng.uniform(0.1, 0.4), tilt_sd=0.18)
    for x, y, sc in ((-1.15, 1.5, 1.05), (1.25, 1.9, 1.0), (-2.0, 2.8, 1.0), (2.3, 3.0, 1.1)):
        plant(x, y, rng.uniform(0.15, 0.30), tilt_sd=0.20, scale=sc, tassel_p=0.8)
    # 月光从冢后打来（略偏右），剑影朝镜头、往左斜
    K.sun_light("Moon", (-0.35, -1.0, -0.42), 2.2, angle_deg=0.8, color=(0.66, 0.78, 1.0))
    K.area_light("Front", (1.5, -4.0, 1.8), (0, 3.0, 0.6), 50.0, 4.0, color=(0.60, 0.72, 1.0))
    K.area_light("Glint", (0.5, 16.0, 2.6), (0, 5.0, 1.0), 900.0, 3.0, color=(0.70, 0.82, 1.0))
    K.camera((0.25, -1.3, 0.50), (0.0, 6.0, 0.62), lens=30.0, fstop=8.0, focus=4.0)
    return {"light": "cold"}


@background("sword_grove")
def bg_sword_grove(P_, h, w, rng, k):
    P_.fill_grad("#0B1220", "#121C30", cloud=0.12)
    K.bg_glow(P_, 0.52, 0.34, 0.50, 0.30, "#40597E", 0.34)
    K.bg_moon(P_, 0.55, 0.21, 0.065, rng, k, color="#EEF2F8", halo="#7890B6", a=0.9, halo_a=0.40)
    bg_clouds(P_, rng, k, [(0.12, 0.03, 0.30, 0.98), (0.20, 0.02, 0.62, 1.0)], "#5B7194", 0.16)
    K.bg_mountains(P_, [(0.50, [(0.10, 0.10, 0.12, 0.10), (0.30, 0.07, 0.14, 0.12), (0.84, 0.12, 0.14, 0.14)], "#17233A", 0.8, 0.08, 5.0)],
                   rng, k)
    K.bg_mist(P_, 0.50, 0.05, "#7F9CC0", 0.18, rng, k)
    K.bg_ink(P_, [(0.02, 0.06, 0.26, 0.18, 0.2), (0.98, 0.08, 0.24, 0.18, -0.4)], 0.45)


# ====================================================================== 合璧：霜天剑雨（霜铃 + 符剑）


def mat_ice_blade(name, glow=1.2):
    """冰剑：透明的冰（折射）+ 刃口和棱一线冷光（Layer Weight 的边缘发光）。"""
    M = K.Mat(name)
    m = M.math
    oc = M.coord("Object")
    nz = M.noise(oc, scale=60.0, detail=4.0)
    nrm = M.bump(nz.outputs["Fac"], strength=0.2, distance=0.001)
    glass = M.principled(Base_Color=(0.85, 0.95, 1.0, 1.0), Roughness=0.05, IOR=1.31, Transmission_Weight=1.0, Normal=nrm)
    lw = M.n("ShaderNodeLayerWeight", Blend=0.3)
    rim = m("POWER", lw.outputs["Facing"], 2.0)
    emi = M.n("ShaderNodeEmission", Color=(0.65, 0.88, 1.0, 1.0))
    M.l(m("MULTIPLY", rim, glow), emi.inputs["Strength"])
    add = M.n("ShaderNodeAddShader")
    M.l(glass.outputs[0], add.inputs[0])
    M.l(emi.outputs[0], add.inputs[1])
    return M.surface(add.outputs[0])


@scene("frost_rain", name="霜天剑雨", samples=128, grade=dict(COLD_GRADE, exposure=1.04, bloom=0.40))
def build_frost_rain(draft):
    """霜天剑雨：夜空里冰剑如雨，从左上斜斜落下，每把拖着一道冷白的光痕，近大远小；远处山寺的钟楼下挂一口钟，
    钟声化作一圈白霜寒波，从钟口往四外荡开。"""
    from mathutils import Vector  # noqa: PLC0415

    sky_gradient(lin("#05080F"), lin("#2E4466"), 0.8, ground=lin("#04060A"))
    rng = np.random.default_rng(57)
    ice = mat_ice_blade("IceBlade")
    gb = ghost_sword_build(L=0.66, W=0.030, T=0.008)
    fall = Vector((0.45, 0.10, -1.0)).normalized()
    for k in range(46):
        depth = rng.uniform(2.0, 11.0)
        p = Vector((rng.uniform(-0.55, 0.55) * depth * 0.9, depth, rng.uniform(-0.2, 0.55) * depth * 0.75 + 0.6))
        ob = make_obj(f"Ice{k}", gb, ice, smooth=False, loc=tuple(p), index=2)
        ob.rotation_mode = "QUATERNION"
        ob.rotation_quaternion = fall.to_track_quat("X", "Z")
        sc = 1.0 + depth * 0.05
        ob.scale = (sc, sc, sc)
        tail = [tuple(p - fall * (0.05 + 0.9 * t)) for t in np.linspace(0, 1, 20)]
        make_obj(f"Trail{k}", K.ribbon_uv(tail, 0.020 * sc, width_fn=lambda t: 1 - 0.9 * t),
                 K.mat_wind(f"TrailM{k}", strength=rng.uniform(0.8, 1.4), seed=k * 0.7, color=(0.72, 0.88, 1.0)), index=3)
    # 远处的钟：钟楼（两根柱、一道梁、一片顶）下挂一口钟；钟口一圈寒波
    bell_c = Vector((2.4, 9.0, 0.9))
    bronze = P.mat_bronze("Bronze", base=(0.28, 0.18, 0.08), patina_amt=0.7)
    prof = [(0.0, 0.0), (0.42, 0.0), (0.44, 0.05), (0.36, 0.30), (0.33, 0.70), (0.25, 0.86), (0.0, 0.90)]
    make_obj("Bell", K.lathe_uv(prof, segments=64, cap_bottom=False), bronze, loc=tuple(bell_c), index=1)
    wood = K.mat_wood("Wood")
    for sx in (-0.9, 0.9):
        make_obj(f"Post{sx}", K.box_build(0.14, 0.14, 2.4), wood, loc=tuple(bell_c + Vector((sx, 0, 0.6))), index=1, smooth=False)
    make_obj("Beam", K.box_build(2.3, 0.18, 0.18), wood, loc=tuple(bell_c + Vector((0, 0, 1.15))), index=1, smooth=False)
    make_obj("Roof", P.roof_build(w=2.6, d=1.4, h=0.55, curl=0.18, wall_h=0.0), P.mat_roof_tiles("Tiles", snow=0.6), loc=tuple(bell_c +
             Vector((0, 0, 1.75))), index=1)
    P.frost_wave("Wave", tuple(bell_c + Vector((0, 0, 0.02))), 1.6, strength=0.9, seed=3.0)
    P.frost_wave("Wave2", tuple(bell_c + Vector((0, 0, 0.02))), 3.0, strength=0.5, seed=7.0, echo=False)
    ground_plane("Ground", P.mat_stone("Snow", color=(0.20, 0.24, 0.30), scale=3.0, bump=0.4), size=40.0, loc=(0, 10, -0.05), index=0)
    K.area_light("Moon", (-5.0, 12.0, 8.0), (0, 5.0, 1.0), 2400.0, 3.0, color=(0.66, 0.78, 1.0))
    K.area_light("Front", (0.0, -4.0, 3.0), (0, 4.0, 1.0), 120.0, 4.0, color=(0.62, 0.74, 1.0))
    K.camera((0.0, -1.2, 1.1), (0.4, 6.0, 1.5), lens=30.0, fstop=8.0, focus=4.0)
    return {"light": "cold"}


@background("frost_rain")
def bg_frost_rain(P_, h, w, rng, k):
    P_.fill_grad("#0A1222", "#111C30", cloud=0.12)
    K.bg_glow(P_, 0.65, 0.55, 0.45, 0.35, "#40597E", 0.30)
    bg_clouds(P_, rng, k, [(0.16, 0.03, 0.10, 0.80), (0.24, 0.02, 0.40, 0.98)], "#5B7194", 0.20)
    K.bg_mountains(P_, [(0.62, [(0.12, 0.12, 0.12, 0.10), (0.40, 0.08, 0.14, 0.12), (0.82, 0.14, 0.14, 0.14)], "#1B2840", 0.8, 0.08, 5.0)],
                   rng, k)
    K.bg_mist(P_, 0.64, 0.05, "#8FB0D0", 0.18, rng, k)
    K.bg_ink(P_, [(0.02, 0.06, 0.26, 0.18, 0.2), (0.98, 0.08, 0.24, 0.18, -0.4)], 0.45)
