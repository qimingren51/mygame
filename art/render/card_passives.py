"""升级卡插画：心法（17 门；疾行在 card_art.py）。题材见 docs/LORE-TEXT.md 第 7.2 节。

每张：@scene 注册 3D 场景（相机、灯、物体），@background 注册水墨底。由 card_art.py 统一渲染和后期：
  art/.venv/bin/python art/render/card_art.py huichun --draft
"""

from __future__ import annotations

import math

import numpy as np

import card_art as K
import card_props as P
from card_art import background, lin, make_obj, scene
from card_weapons import COLD_GRADE, EARTH_GRADE, WARM_GRADE, WOOD_GRADE, ScreenCam, bg_clouds, sky_gradient


def bez(ctrl, n=60):
    """控制点 → 折线（Catmull-Rom）。"""
    return [tuple(p) for p in K.catmull(ctrl, n=n)]


def mat_bark(name, color=(0.075, 0.062, 0.052), crack=1.0):
    """老树皮（tube_uv 的 UV：u = 沿枝弧长米，v = 绕一圈）：纵向的裂纹（沿枝拉长的噪声），灰褐，裂缝里压黑，凸处偏灰白。"""
    M = K.Mat(name)
    m = M.math
    uv = M.coord("UV")
    mp = M.n("ShaderNodeMapping")
    M.l(uv, mp.inputs["Vector"])
    mp.inputs["Scale"].default_value = (14.0, 9.0, 1.0)
    fis = M.noise(mp.outputs["Vector"], scale=1.0, detail=6.0, rough=0.62, dist=0.5)
    mp2 = M.n("ShaderNodeMapping")
    M.l(uv, mp2.inputs["Vector"])
    mp2.inputs["Scale"].default_value = (60.0, 40.0, 1.0)
    fine = M.noise(mp2.outputs["Vector"], scale=1.0, detail=4.0, rough=0.6)
    oc = M.coord("Object")
    lich = M.noise(oc, scale=30.0, detail=4.0)
    ck = M.maprange(fis.outputs["Fac"], 0.40, 0.30)
    col = M.mix(M.maprange(fine.outputs["Fac"], 0.3, 0.7), (color[0] * 0.7, color[1] * 0.7, color[2] * 0.7, 1.0),
                (color[0] * 1.6, color[1] * 1.6, color[2] * 1.55, 1.0))
    col = M.mix(m("MULTIPLY", M.maprange(lich.outputs["Fac"], 0.58, 0.70), 0.6), col, (0.20, 0.21, 0.18, 1.0))
    col = M.mix(m("MULTIPLY", ck, crack), col, (0.006, 0.005, 0.004, 1.0))
    h = m("SUBTRACT", m("ADD", fis.outputs["Fac"], m("MULTIPLY", fine.outputs["Fac"], 0.3)), m("MULTIPLY", ck, crack))
    nrm = M.bump(h, strength=0.8, distance=0.004)
    bsdf = M.principled(Base_Color=col, Roughness=0.86, Normal=nrm)
    return M.surface(bsdf.outputs[0])


def mat_petal(name, color=(0.95, 0.86, 0.86), heart=(0.85, 0.30, 0.38), glow=0.0):
    """花瓣：白里透粉，瓣根一点胭脂；薄，透光（Translucent），一点细纹。UV.x = 0（瓣根）→ 1（瓣尖）。"""
    M = K.Mat(name)
    m = M.math
    uv = M.coord("UV")
    sep = M.n("ShaderNodeSeparateXYZ")
    M.l(uv, sep.inputs[0])
    col = M.mix(M.maprange(sep.outputs["X"], 0.0, 0.45), (*heart, 1.0), (*color, 1.0))
    veins = m("ABSOLUTE", m("SINE", m("MULTIPLY", sep.outputs["Y"], math.pi * 7.0)))
    nrm = M.bump(veins, strength=0.08, distance=0.0003)
    bsdf = M.principled(Base_Color=col, Roughness=0.55, Subsurface_Weight=0.4, Subsurface_Radius=(0.004, 0.003, 0.003),
                        Subsurface_Scale=0.5, Normal=nrm, Sheen_Weight=0.3)
    if glow:
        bsdf.inputs["Emission Color"].default_value = (*color, 1.0)
        bsdf.inputs["Emission Strength"].default_value = glow
    trn = M.n("ShaderNodeBsdfTranslucent")
    M.l(col, trn.inputs["Color"])
    mx = M.n("ShaderNodeMixShader")
    mx.inputs[0].default_value = 0.35
    M.l(bsdf.outputs[0], mx.inputs[1])
    M.l(trn.outputs[0], mx.inputs[2])
    return M.surface(mx.outputs[0])


def petal_build(L, W, cup=0.35, curl=0.15, n=10, side=4):
    """一片花瓣（沿 +X，瓣根在原点）：倒卵形，瓣尖略凹，横向往上兜（cup），沿长往后卷一点（curl）。UV.x 沿长、UV.y 横跨。"""
    def build(bm):
        uvl = bm.loops.layers.uv.new("UVMap")
        grid = []
        for i in range(n + 1):
            t = i / n
            w = W * (math.sin(math.pi * min(1.0, t * 0.62 + 0.10)) ** 0.8) * (1 - 0.18 * math.exp(-((t - 1.0) / 0.08) ** 2))
            w = max(w, W * 0.12)
            row = []
            for j in range(2 * side + 1):
                s = -1 + j / side
                x = L * t - 0.10 * L * (s * s) * t ** 4
                y = s * w / 2
                z = cup * W * s * s * (0.3 + 0.7 * t) - curl * L * t ** 3
                row.append(bm.verts.new((x, y, z)))
            grid.append(row)
        for i in range(n):
            for j in range(2 * side):
                f = bm.faces.new((grid[i][j], grid[i + 1][j], grid[i + 1][j + 1], grid[i][j + 1]))
                for lp, uv in zip(f.loops, ((i / n, j / (2 * side)), ((i + 1) / n, j / (2 * side)), ((i + 1) / n, (j + 1) / (2 * side)),
                                           (i / n, (j + 1) / (2 * side)))):
                    lp[uvl].uv = uv
    return build


def blossom(name, loc, normal, size, petal_m, center_m, stamen_m, *, n=5, open_=1.0, rng=None, index=2, spin=0.0):
    """一朵小花：n 片花瓣绕花心（open_ = 1 全开，越小越收拢成杯），花心一颗小球，十几根花蕊。normal：花朝向。"""
    from mathutils import Matrix, Vector  # noqa: PLC0415

    rng = rng or np.random.default_rng(1)
    bpy = K._bpy()
    root = bpy.data.objects.new(name, None)
    K.link(root)
    root.location = loc
    root.rotation_mode = "QUATERNION"
    root.rotation_quaternion = Vector(normal).normalized().to_track_quat("Z", "Y")
    pb = petal_build(size, size * 0.85, cup=0.30, curl=0.10)
    tilt = math.radians(90 - 70 * open_)
    for k in range(n):
        a = 2 * math.pi * k / n + spin + rng.normal(0, 0.06)
        R = Matrix.Rotation(a, 3, "Z") @ Matrix.Rotation(-tilt + rng.normal(0, 0.08), 3, "Y")
        ob = make_obj(f"{name}_P{k}", pb, petal_m, parent=root, index=index)
        ob.rotation_euler = R.to_euler()
        ob.location = R @ Vector((size * 0.06, 0, 0))
    make_obj(f"{name}_C", K.ico_cloud([(0, 0, 0)], [size * 0.14], 2), center_m, parent=root, loc=(0, 0, size * 0.04), index=index)
    for k in range(14):
        a = rng.uniform(0, 2 * math.pi)
        r = size * rng.uniform(0.12, 0.30)
        h = size * rng.uniform(0.28, 0.42)
        tip = (r * math.cos(a), r * math.sin(a), h)
        make_obj(f"{name}_S{k}", K.tube_uv([(r * 0.3 * math.cos(a), r * 0.3 * math.sin(a), size * 0.05), tip], size * 0.012, sides=5),
                 stamen_m, parent=root, index=index)
        make_obj(f"{name}_A{k}", K.ico_cloud([(0, 0, 0)], [size * 0.03], 1), center_m, parent=root, loc=tip, index=index)
    return root


def mat_young_leaf(name, color=(0.16, 0.42, 0.10), tip=(0.42, 0.62, 0.16), vein=(0.55, 0.70, 0.30)):
    """嫩叶：亮的嫩绿，叶尖偏黄绿，透光多；中脉一道浅色。UV.x 叶柄 → 叶尖。"""
    M = K.Mat(name)
    m = M.math
    uv = M.coord("UV")
    sep = M.n("ShaderNodeSeparateXYZ")
    M.l(uv, sep.inputs[0])
    col = M.mix(M.maprange(sep.outputs["X"], 0.2, 1.0), (*color, 1.0), (*tip, 1.0))
    mid = M.maprange(m("ABSOLUTE", m("SUBTRACT", sep.outputs["Y"], 0.5)), 0.0, 0.04, 1.0, 0.0)
    col = M.mix(m("MULTIPLY", mid, 0.6), col, (*vein, 1.0))
    veins = m("ABSOLUTE", m("SINE", m("MULTIPLY", m("ADD", sep.outputs["Y"], m("MULTIPLY", sep.outputs["X"], 0.6)), math.pi * 8.0)))
    nrm = M.bump(m("ADD", m("MULTIPLY", veins, 0.3), mid), strength=0.2, distance=0.0004)
    bsdf = M.principled(Base_Color=col, Roughness=0.45, Specular_IOR_Level=0.35, Normal=nrm, Coat_Weight=0.2, Coat_Roughness=0.2)
    trn = M.n("ShaderNodeBsdfTranslucent")
    M.l(M.mix(0.4, col, (0.35, 0.65, 0.12, 1.0)), trn.inputs["Color"])
    mx = M.n("ShaderNodeMixShader")
    mx.inputs[0].default_value = 0.30
    M.l(bsdf.outputs[0], mx.inputs[1])
    M.l(trn.outputs[0], mx.inputs[2])
    return M.surface(mx.outputs[0])


def mat_glass(name, color=(0.95, 0.98, 1.0), rough=0.0, ior=1.33):
    M = K.Mat(name)
    bsdf = M.principled(Base_Color=(*color, 1.0), Roughness=rough, IOR=ior, Transmission_Weight=1.0)
    return M.surface(bsdf.outputs[0])


def upd():
    """刷新物体的 matrix_world（刚设的位置、旋转、缩放要等场景更新后才进 matrix_world）。"""
    K._bpy().context.view_layer.update()


def frame_quat(xd, zh):
    """物体 +X 对准 xd、+Z 尽量朝 zh 的旋转（四元数）。"""
    from mathutils import Matrix, Vector  # noqa: PLC0415

    x = Vector(xd).normalized()
    z = Vector(zh)
    z = (z - x * z.dot(x)).normalized()
    y = z.cross(x)
    return Matrix((x, y, z)).transposed().to_quaternion()


def orient(ob, loc, xd, zh):
    ob.location = loc
    ob.rotation_mode = "QUATERNION"
    ob.rotation_quaternion = frame_quat(xd, zh)
    return ob


def place_on(ob, loc, d, up=(0, 0, 1)):
    """把物体的 +X 对准方向 d、放到 loc。"""
    from mathutils import Vector  # noqa: PLC0415

    ob.location = loc
    ob.rotation_mode = "QUATERNION"
    ob.rotation_quaternion = Vector(d).normalized().to_track_quat("X", "Z")
    _ = up
    return ob


# ====================================================================== 回春


@scene("huichun", name="回春", samples=128, grade=WOOD_GRADE)
def build_huichun(draft):
    """回春：一截枯枝从左下斜伸到右上（树皮开裂、灰褐），枝上冒出几簇嫩叶和几朵小白花（梅花样，瓣根一点胭脂）；
    右边一片垂下的嫩叶叶尖挂着一滴露水，映着光。逆光打轮廓，叶子透亮。按画面位置摆（ScreenCam）。"""
    from mathutils import Vector  # noqa: PLC0415

    sky_gradient(lin("#06090A"), lin("#2E4A3E"), 0.7, ground=lin("#040605"))
    rng = np.random.default_rng(61)
    S = ScreenCam(lens=50.0)
    bark = mat_bark("Bark")
    main = bez([tuple(S(x, y, d)) for x, y, d in ((-0.08, 0.95, 1.05), (0.12, 0.80, 1.02), (0.34, 0.66, 0.98), (0.60, 0.52, 0.95),
                                                  (0.82, 0.40, 0.98), (1.06, 0.27, 1.02))], n=90)
    make_obj("Branch", K.tube_uv(main, 0.026, sides=28, radius_fn=lambda t: (1 - 0.62 * t) * (1 + 0.10 * math.sin(t * 23) ** 2)), bark,
             index=1)
    twig1 = bez([tuple(S(x, y, d)) for x, y, d in ((0.38, 0.64, 0.98), (0.42, 0.50, 0.96), (0.47, 0.36, 0.95), (0.50, 0.22, 0.96))], n=40)
    make_obj("Twig1", K.tube_uv(twig1, 0.010, sides=16, radius_fn=lambda t: 1 - 0.7 * t), bark, index=1)
    twig2 = bez([tuple(S(x, y, d)) for x, y, d in ((0.70, 0.47, 0.96), (0.77, 0.54, 0.94), (0.84, 0.62, 0.93))], n=30)
    make_obj("Twig2", K.tube_uv(twig2, 0.007, sides=12, radius_fn=lambda t: 1 - 0.6 * t), bark, index=1)
    stub = bez([tuple(S(x, y, d)) for x, y, d in ((0.18, 0.77, 1.02), (0.15, 0.66, 1.0), (0.14, 0.60, 0.99))], n=12)
    make_obj("Stub", K.tube_uv(stub, 0.008, sides=12, radius_fn=lambda t: 1 - 0.4 * t), bark, index=1)
    leaf_m = mat_young_leaf("Leaf")
    petal = mat_petal("Petal")
    center = K.mat_gold("Pollen", color=(0.95, 0.72, 0.25), rough=0.5)
    stamen = mat_petal("Stamen", color=(0.95, 0.90, 0.80), heart=(0.95, 0.85, 0.75))
    cam = Vector((0, 0, 0))

    def leaf_at(name, p, d, L, droop=0.0):
        ob = make_obj(name, K.leaf_build(L, L * 0.40, fold=0.20, curl=0.20 + droop, twist=rng.normal(0, 0.3)), leaf_m, index=2)
        zh = (cam - Vector(p)).normalized() + Vector(rng.normal(0, 0.25, 3))
        return orient(ob, p, d, zh)

    # 嫩叶：枝梢一簇、右边小枝一簇（其中一片往下垂，挂露水）、主枝节上一片
    leaf_at("LeafA0", twig1[-1], (0.25, 0.0, 1.0), 0.075)
    leaf_at("LeafA1", twig1[-1], (-0.7, 0.0, 0.8), 0.060)
    leaf_at("LeafA2", twig1[-1], (0.8, 0.1, 0.35), 0.050)
    leaf_at("LeafB0", twig2[-1], (0.9, 0.0, 0.25), 0.068)
    hang_d = Vector((0.35, -0.15, -1.0)).normalized()
    leaf_at("LeafB1", twig2[-1], tuple(hang_d), 0.080, droop=0.05)
    leaf_at("LeafC0", main[30], (-0.6, -0.2, 1.0), 0.055)
    # 小花：贴着枝条，朝镜头
    spots = [(main[44], 0.0, 1.0), (main[62], 0.4, 1.0), (twig1[16], -0.3, 1.0), (twig1[28], 0.2, 0.75), (main[74], -0.2, 0.55),
             (main[22], 0.3, 0.9)]
    for k, (p, tilt, op) in enumerate(spots):
        nrm = (cam - Vector(p)).normalized() + Vector((tilt, 0, 0.35))
        blossom(f"Blossom{k}", tuple(Vector(p) + nrm.normalized() * 0.010), nrm, 0.030, petal, center, stamen, open_=op, rng=rng,
                spin=rng.uniform(0, 1))
    for k, p in enumerate((main[52], twig1[36], main[82])):  # 花苞
        make_obj(f"Bud{k}", K.ico_cloud([(0, 0, 0)], [0.008], 2), petal, loc=tuple(Vector(p) + Vector((0, -0.010, 0.008))), index=2)
    # 露水：垂叶的叶尖下挂一滴（叶尖 = 叶柄 + 叶长 × 方向，叶子往下弯一点）
    tip = Vector(twig2[-1]) + hang_d * 0.078 + Vector((0, 0, -0.004))
    drop = make_obj("Dew", K.lathe_uv([(0.0, -0.013), (0.005, -0.0118), (0.0078, -0.008), (0.0086, -0.004), (0.0070, 0.0),
                                        (0.0035, 0.0028), (0.0, 0.0036)], segments=48), mat_glass("Water"), index=3)
    drop.location = tuple(tip)
    K.point_light("DewGlint", tuple(tip + Vector((-0.06, -0.10, 0.08))), 0.08, radius=0.003, color=(1.0, 0.95, 0.85))
    # 光：逆光（左上后方，暖白）打亮叶子和花瓣的边，前面一点冷的补光
    K.area_light("Back", tuple(S(0.2, -0.2, 2.2) + Vector((0, 0.8, 0.6))), tuple(S(0.55, 0.5, 0.97)), 70.0, 0.8, color=(1.0, 0.92, 0.78))
    K.area_light("Rim", tuple(S(1.2, 0.4, 1.6)), tuple(S(0.55, 0.5, 0.97)), 20.0, 0.6, color=(0.78, 0.92, 1.0))
    K.area_light("Fill", (-0.3, -0.4, 0.3), tuple(S(0.55, 0.5, 0.97)), 5.0, 1.0, color=(0.75, 0.88, 0.80))
    S.place(lens=50.0, fstop=4.0, focus=0.96)
    return {"light": "wood"}


@background("huichun")
def bg_huichun(P_, h, w, rng, k):
    P_.fill_grad("#0C1412", "#0F1A16", cloud=0.12)
    K.bg_glow(P_, 0.36, 0.34, 0.46, 0.40, "#3E6656", 0.30)
    K.bg_glow(P_, 0.30, 0.28, 0.16, 0.16, "#B9D3A8", 0.16)
    bg_clouds(P_, rng, k, [(0.62, 0.03, 0.30, 0.95), (0.70, 0.02, 0.05, 0.60)], "#4C6A5E", 0.16)
    K.bg_mountains(P_, [(0.92, [(0.18, 0.10, 0.14, 0.12), (0.55, 0.06, 0.16, 0.14), (0.88, 0.12, 0.12, 0.14)], "#132019", 0.85, 0.08, 5.0,
                         "#5E7E6E")], rng, k)
    K.bg_ink(P_, [(0.98, 0.06, 0.26, 0.18, -0.4), (0.02, 0.96, 0.30, 0.20, 0.2)], 0.45)


# ====================================================================== 寒意


def leaf_outline_build(L, W, serr=0.10, n=48, side=8, fold=0.10, curl=0.12, lobes=0):
    """宽叶（沿 +X，叶柄在原点）：卵形，叶缘细锯齿，叶尖渐尖；沿中脉折一点、沿长弯一点。UV.x 沿长、UV.y 横跨。"""
    def half(t):
        base = math.sin(math.pi * min(1.0, t ** 0.85)) ** 0.75 * (1 - 0.35 * t)
        tooth = 1 - serr * (0.5 + 0.5 * math.cos(t * 2 * math.pi * 14)) * min(1.0, t * 4)
        return max(W / 2 * base * tooth, 0.0003)

    def build(bm):
        uvl = bm.loops.layers.uv.new("UVMap")
        grid = []
        for i in range(n + 1):
            t = i / n
            hw = half(t)
            row = []
            for j in range(2 * side + 1):
                s = -1 + j / side
                y = s * hw
                z = abs(s) * hw * fold + curl * L * t * t - 0.02 * L * math.sin(s * 3.0 + t * 9.0) * abs(s)
                row.append(bm.verts.new((L * t, y, z)))
            grid.append(row)
        for i in range(n):
            for j in range(2 * side):
                f = bm.faces.new((grid[i][j], grid[i + 1][j], grid[i + 1][j + 1], grid[i][j + 1]))
                for lp, uv in zip(f.loops, ((i / n, j / (2 * side)), ((i + 1) / n, j / (2 * side)), ((i + 1) / n, (j + 1) / (2 * side)),
                                           (i / n, (j + 1) / (2 * side)))):
                    lp[uvl].uv = uv
    return build


def leaf_frost_texture(rng, w=1024, h=512, front=0.38):
    """叶缘的霜（UV 空间：x 沿叶长，y 横跨，上下两边是叶缘）：从叶缘往叶心长的冰花枝，叶缘一圈白霜，前沿参差。
    返回 (h, w) 0..1。"""
    acc = np.zeros((h, w), np.float32)
    pts = []

    def grow(x, y, ang, length, width, depth):
        n = max(int(length / 0.8), 2)
        xs, ys = [x], [y]
        a = ang
        for _ in range(n):
            a += rng.normal(0, 0.03)
            x += math.cos(a) * 0.8
            y += math.sin(a) * 0.8
            xs.append(x)
            ys.append(y)
        xs, ys = np.array(xs), np.array(ys)
        t = np.linspace(0, 1, len(xs))
        pts.append((xs, ys, width * (1 - 0.7 * t)))
        if depth <= 0:
            return
        k = int(rng.uniform(5, 8) / 0.8)
        for i in range(k, len(xs) - k // 2, k):
            Ls = length * 0.45 * (1 - i / len(xs)) * rng.uniform(0.7, 1.1)
            if Ls < 3:
                continue
            for sgn in (-1, 1):
                grow(xs[i], ys[i], a + sgn * math.radians(rng.normal(60, 8)), Ls, width * 0.6, depth - 1)

    for _ in range(140):
        x = rng.uniform(0.04, 0.99) * w
        top = rng.random() < 0.5
        y = 1.0 if top else h - 2.0
        ang = (math.pi / 2 if top else -math.pi / 2) + rng.normal(0, 0.35)
        reach = h * 0.5 * front * rng.uniform(0.5, 1.3) * (0.6 + 0.4 * math.sin(x / w * 9 + 1.0) ** 2)
        grow(x, y, ang, reach, rng.uniform(1.6, 2.4), 2)
    for xs, ys, ws in pts:
        ok = (ys >= 0) & (ys < h - 1) & (xs >= 0) & (xs < w - 1)
        X, Y, Wt = xs[ok], ys[ok], ws[ok]
        x0, y0 = np.floor(X).astype(int), np.floor(Y).astype(int)
        fx, fy = X - x0, Y - y0
        for dx, dy, wt in ((0, 0, (1 - fx) * (1 - fy)), (1, 0, fx * (1 - fy)), (0, 1, (1 - fx) * fy), (1, 1, fx * fy)):
            np.add.at(acc, (y0 + dy, x0 + dx), wt * Wt)
    V = K.vfx()
    acc = np.clip(V.fft_blur(acc.astype(np.float64), 0.8) * 1.1, 0, 1)
    # 叶缘一圈实的白霜（往里参差地淡出）
    yy = np.abs(np.arange(h)[:, None] / (h - 1) - 0.5) * 2  # 0 中脉 → 1 叶缘
    n = V.fft_blur(rng.standard_normal((h, w)), (14.0, 3.0))
    n = n / (n.std() + 1e-9)
    rim = V.smoothstep(1 - front * 0.45 + 0.06 * n, 1 - front * 0.25 + 0.06 * n, yy)
    return np.clip(np.maximum(acc, rim * 0.92), 0, 1).astype(np.float32)


def mat_frost_leaf(name, frost_img, color=(0.040, 0.095, 0.022)):
    """结霜的叶：叶面青绿，叶脉（中脉 + 侧脉）浅黄绿凸起；靠霜的叶缘冻成赭红；冰花贴图（UV）盖住叶缘，
    霜处发白、粗糙、带细闪（冰晶）。"""
    M = K.Mat(name)
    m = M.math
    uv = M.coord("UV")
    sep = M.n("ShaderNodeSeparateXYZ")
    M.l(uv, sep.inputs[0])
    t = M.n("ShaderNodeTexImage", _interpolation="Cubic", _extension="EXTEND")
    t.image = frost_img
    M.l(uv, t.inputs["Vector"])
    sc = M.n("ShaderNodeSeparateColor")
    M.l(t.outputs["Color"], sc.inputs[0])
    fr = sc.outputs[0]
    u, v = sep.outputs["X"], sep.outputs["Y"]
    d = m("MULTIPLY", m("ABSOLUTE", m("SUBTRACT", v, 0.5)), 2.0)  # 0 中脉 → 1 叶缘
    mid = M.maprange(d, 0.0, 0.035, 1.0, 0.0)
    side = m("ABSOLUTE", m("SINE", m("MULTIPLY", m("SUBTRACT", u, m("MULTIPLY", d, 0.30)), math.pi * 9.0)))  # 侧脉斜向叶尖
    side = m("MULTIPLY", M.maprange(side, 0.93, 1.0), M.maprange(d, 0.02, 0.10))
    vein = m("MAXIMUM", mid, m("MULTIPLY", side, 0.8))
    oc = M.coord("Object")
    blot = M.noise(oc, scale=30.0, detail=4.0)
    col = M.mix(M.maprange(blot.outputs["Fac"], 0.35, 0.7), (*color, 1.0), (color[0] * 1.8, color[1] * 1.45, color[2] * 1.1, 1.0))
    burn = m("MULTIPLY", M.maprange(d, 0.35, 0.80), M.maprange(blot.outputs["Fac"], 0.3, 0.6, 0.6, 1.0))
    col = M.mix(burn, col, (0.30, 0.075, 0.025, 1.0))
    col = M.mix(m("MULTIPLY", vein, 0.55), col, (0.36, 0.42, 0.14, 1.0))
    col = M.mix(fr, col, (0.88, 0.93, 1.0, 1.0))
    sparkle = M.noise(oc, scale=1200.0, detail=1.0)
    rough = M.mixf(fr, 0.42, M.maprange(sparkle.outputs["Fac"], 0.55, 0.75, 0.60, 0.10))
    nrm = M.bump(m("ADD", m("MULTIPLY", vein, 0.5), m("MULTIPLY", fr, 0.9)), strength=0.45, distance=0.0010)
    bsdf = M.n("ShaderNodeBsdfPrincipled")
    M.l(col, bsdf.inputs["Base Color"])
    M.l(rough, bsdf.inputs["Roughness"])
    M.l(nrm, bsdf.inputs["Normal"])
    M.l(m("MULTIPLY", fr, 0.4), bsdf.inputs["Subsurface Weight"])
    bsdf.inputs["Subsurface Radius"].default_value = (0.002, 0.003, 0.004)
    trn = M.n("ShaderNodeBsdfTranslucent")
    M.l(M.mix(fr, M.mix(burn, (0.16, 0.36, 0.06, 1.0), (0.45, 0.12, 0.03, 1.0)), (0.6, 0.7, 0.8, 1.0)), trn.inputs["Color"])
    mx = M.n("ShaderNodeMixShader")
    M.l(m("MULTIPLY", m("SUBTRACT", 1.0, fr), 0.28), mx.inputs[0])
    M.l(bsdf.outputs[0], mx.inputs[1])
    M.l(trn.outputs[0], mx.inputs[2])
    return M.surface(mx.outputs[0])


@scene("hanyi", name="寒意", samples=128, grade=dict(COLD_GRADE, bloom=0.30))
def build_hanyi(draft):
    """寒意：一片宽叶斜着占满画面（叶柄在左下、叶尖朝右上），叶缘一圈白霜，冰花一枝枝从叶缘往叶心爬，前沿参差，
    霜到的地方叶子冻成赭红；叶缘立着细小的冰晶，空中几粒冰屑。冷光从左上打来，后面一道轮廓光。"""
    from mathutils import Vector  # noqa: PLC0415

    sky_gradient(lin("#05080F"), lin("#2E4466"), 0.7, ground=lin("#04060A"))
    rng = np.random.default_rng(83)
    S = ScreenCam(lens=50.0)
    frost = K.np_image("leaf_frost", leaf_frost_texture(rng, front=0.46))
    L, Wd = 0.46, 0.30
    base, tip = S(0.08, 0.90, 0.80), S(0.86, 0.27, 0.74)
    d = (tip - base).normalized()
    zh = (Vector((0, 0, 0)) - base).normalized() + Vector((0.0, 0.0, 0.55))
    leaf = make_obj("Leaf", leaf_outline_build(L, Wd, serr=0.07, fold=0.16, curl=0.08), mat_frost_leaf("LeafM", frost), index=1)
    orient(leaf, tuple(base), d, zh)
    leaf.scale = ((tip - base).length / L,) * 3
    stem_m = mat_bark("Stem", color=(0.10, 0.10, 0.04), crack=0.0)
    make_obj("Stem", K.tube_uv([(-0.07, 0, -0.01), (-0.03, 0, 0.0), (0.0, 0, 0.0)], 0.0045, sides=10), stem_m, parent=leaf, index=1)
    # 叶缘的冰晶：沿叶缘一圈小六棱针
    ice = K.mat_ice("Ice")
    for k in range(140):
        t = rng.uniform(0.04, 0.97)
        sg = 1 if rng.random() < 0.5 else -1
        hw = Wd / 2 * math.sin(math.pi * min(1.0, t ** 0.85)) ** 0.75 * (1 - 0.35 * t)
        pp = Vector((L * t, sg * hw * rng.uniform(0.80, 0.99), 0.16 * hw + 0.08 * L * t * t + 0.004))
        dd = Vector((rng.normal(0, 0.5), sg * rng.uniform(0.0, 0.6), 1.0)).normalized()
        Lc = rng.uniform(0.004, 0.012)
        ob = make_obj(f"Rime{k}", P.crystal_build(Lc, Lc * 0.22), ice, parent=leaf, loc=tuple(pp), index=3, smooth=False)
        ob.rotation_mode = "QUATERNION"
        ob.rotation_quaternion = dd.to_track_quat("Z", "Y")
    for k in range(36):
        pp = S(rng.uniform(0.05, 0.95), rng.uniform(0.05, 0.95), rng.uniform(0.5, 1.2))
        Lc = rng.uniform(0.003, 0.008)
        ob = make_obj(f"Dust{k}", P.crystal_build(Lc, Lc * 0.25), ice, loc=tuple(pp), index=3, smooth=False)
        ob.rotation_euler = tuple(rng.uniform(0, 6.28, 3))
    c = S(0.5, 0.5, 0.78)
    K.area_light("Key", tuple(c + Vector((-0.6, -0.5, 0.8))), tuple(c), 13.0, 0.8, color=(0.80, 0.88, 1.0))
    K.area_light("Back", tuple(c + Vector((0.3, 1.0, 0.6))), tuple(c), 22.0, 1.0, color=(0.70, 0.82, 1.0))
    K.area_light("Rim", tuple(c + Vector((1.0, 0.4, -0.2))), tuple(c), 20.0, 0.8, color=(0.62, 0.76, 1.0))
    S.place(lens=50.0, fstop=4.0, focus=0.77)
    return {"light": "cold"}


@background("hanyi")
def bg_hanyi(P_, h, w, rng, k):
    P_.fill_grad("#0B1222", "#111C30", cloud=0.12)
    K.bg_glow(P_, 0.50, 0.42, 0.50, 0.40, "#40597E", 0.30)
    K.bg_moon(P_, 0.80, 0.26, 0.05, rng, k, color="#E6ECF4", halo="#7890B6", a=0.45, halo_a=0.24)
    bg_clouds(P_, rng, k, [(0.30, 0.03, 0.40, 0.98), (0.72, 0.03, 0.05, 0.70)], "#5B7194", 0.16)
    K.bg_ink(P_, [(0.02, 0.06, 0.26, 0.18, 0.2), (0.98, 0.96, 0.30, 0.20, -0.2)], 0.45)


# ====================================================================== 长明


def mat_paving(name, light_r=1.6):
    """青石板地：一块块方石（Brick 纹），缝里压黑，石面有凹凸、苔点；离中心越远越暗（夜色压过来）。"""
    M = K.Mat(name)
    m = M.math
    oc = M.coord("Object")
    br = M.n("ShaderNodeTexBrick", Scale=1.0, Mortar_Size=0.012, Mortar_Smooth=0.2, Bias=0.0, Brick_Width=0.62, Row_Height=0.42,
             _offset=0.5, _squash=1.0)
    br.inputs["Color1"].default_value = (1.0, 1.0, 1.0, 1.0)
    br.inputs["Color2"].default_value = (0.75, 0.75, 0.75, 1.0)
    br.inputs["Mortar"].default_value = (0.0, 0.0, 0.0, 1.0)
    M.l(oc, br.inputs["Vector"])
    n1 = M.noise(oc, scale=6.0, detail=6.0, rough=0.6)
    n2 = M.noise(oc, scale=40.0, detail=5.0, rough=0.7)
    mortar = m("SUBTRACT", 1.0, br.outputs["Fac"])
    sep = M.n("ShaderNodeSeparateColor")
    M.l(br.outputs["Color"], sep.inputs[0])
    tone = sep.outputs[0]
    base = M.mix(M.maprange(n1.outputs["Fac"], 0.3, 0.7), (0.040, 0.042, 0.044, 1.0), (0.11, 0.11, 0.105, 1.0))
    base = M.mix(m("MULTIPLY", m("SUBTRACT", 1.0, tone), 0.8), base, (0.05, 0.05, 0.05, 1.0))
    base = M.mix(m("MULTIPLY", M.maprange(n2.outputs["Fac"], 0.62, 0.72), 0.5), base, (0.035, 0.055, 0.03, 1.0))
    base = M.mix(mortar, base, (0.004, 0.004, 0.004, 1.0))
    h = m("SUBTRACT", m("ADD", m("MULTIPLY", n1.outputs["Fac"], 0.2), m("MULTIPLY", n2.outputs["Fac"], 0.15)), m("MULTIPLY", mortar, 0.6))
    nrm = M.bump(h, strength=0.6, distance=0.01)
    bsdf = M.principled(Base_Color=base, Roughness=M.maprange(n2.outputs["Fac"], 0.3, 0.7, 0.55, 0.85), Normal=nrm,
                        Specular_IOR_Level=0.4)
    return M.surface(bsdf.outputs[0])


def mat_light_ring(name, color=(1.0, 0.70, 0.32), strength=6.0, seed=0.0, inner=0.06):
    """地上扩开的光圈（UV.y = 0 内 → 1 外）：外沿一道亮边，往里拖一片淡光，噪声打散成一缕缕。"""
    M = K.Mat(name)
    m = M.math
    uv = M.coord("UV")
    sep = M.n("ShaderNodeSeparateXYZ")
    M.l(uv, sep.inputs[0])
    vv = sep.outputs["Y"]
    mp = M.n("ShaderNodeMapping")
    M.l(uv, mp.inputs["Vector"])
    mp.inputs["Scale"].default_value = (40.0, 2.0, 1.0)
    nz = M.noise(mp.outputs["Vector"], scale=1.0, detail=6.0, rough=0.62, w=seed)
    wisp = M.maprange(nz.outputs["Fac"], 0.30, 0.66, interp="SMOOTHSTEP")
    edge = m("EXPONENT", m("MULTIPLY", m("POWER", m("DIVIDE", m("SUBTRACT", vv, 0.93), 0.030), 2.0), -1.0))
    trail = m("MULTIPLY", m("POWER", M.maprange(vv, 0.0, 0.93), 2.0), m("LESS_THAN", vv, 0.93))
    a = m("MULTIPLY", m("ADD", m("MULTIPLY", edge, 1.0), m("MULTIPLY", trail, inner)), m("ADD", m("MULTIPLY", wisp, 0.8), 0.3), clamp=True)
    emi = M.n("ShaderNodeEmission", Color=(*color, 1.0))
    M.l(m("MULTIPLY", a, strength), emi.inputs["Strength"])
    tr = M.n("ShaderNodeBsdfTransparent")
    add = M.n("ShaderNodeAddShader")
    M.l(tr.outputs[0], add.inputs[0])
    M.l(emi.outputs[0], add.inputs[1])
    return M.surface(add.outputs[0])


def flat_ring_build(r0, r1, z, n=320, m=40, wob=0.012, seed=0):
    """贴地的环带（UV.x 绕一圈 0..1，UV.y = 0 内 → 1 外），边缘只有很轻的起伏。"""
    rng = np.random.default_rng(seed)
    ph = rng.uniform(0, 6.28, 3)

    def build(bm):
        uvl = bm.loops.layers.uv.new("UVMap")
        grid = []
        for j in range(m + 1):
            t = j / m
            rr = r0 + (r1 - r0) * t
            row = []
            for i in range(n + 1):
                a = 2 * math.pi * i / n
                w = 1 + wob * (math.sin(3 * a + ph[0]) + 0.6 * math.sin(7 * a + ph[1]) + 0.3 * math.sin(13 * a + ph[2])) * t
                row.append(bm.verts.new((rr * w * math.cos(a), rr * w * math.sin(a), z)))
            grid.append(row)
        for j in range(m):
            for i in range(n):
                f = bm.faces.new((grid[j][i], grid[j][i + 1], grid[j + 1][i + 1], grid[j + 1][i]))
                for lp, uv in zip(f.loops, ((i / n, j / m), ((i + 1) / n, j / m), ((i + 1) / n, (j + 1) / m), (i / n, (j + 1) / m))):
                    lp[uvl].uv = uv
    return build


def bronze_oil_lamp(name, *, loc=(0, 0, 0), scale=1.0, flame=1.0, index=1, bronze=None, flame_h=0.07, lean=0.0):
    """青铜灯台：圆座、细柱（中间一道箍）、上托一只浅灯盏，盏里一根灯芯、一朵火（核心火 + 点光）。灯盏口在 z≈0.36·scale。
    返回 (父物体, 火苗位置)。"""
    from mathutils import Vector  # noqa: PLC0415

    bpy = K._bpy()
    root = bpy.data.objects.new(name, None)
    K.link(root)
    root.location = loc
    root.scale = (scale, scale, scale)
    bronze = bronze or P.mat_bronze(f"{name}_Bronze", base=(0.32, 0.20, 0.08), patina_amt=0.55, gilt=0.0)
    prof = [(0.0, 0.0), (0.085, 0.0), (0.088, 0.008), (0.075, 0.016), (0.050, 0.030), (0.030, 0.050), (0.016, 0.075), (0.012, 0.10),
            (0.012, 0.18), (0.020, 0.186), (0.020, 0.196), (0.012, 0.202), (0.011, 0.30), (0.016, 0.31), (0.030, 0.318),
            (0.0, 0.318)]
    make_obj(f"{name}_Stand", K.lathe_uv(prof, segments=64), bronze, parent=root, index=index)
    dish = [(0.0, 0.316), (0.030, 0.316), (0.055, 0.322), (0.072, 0.336), (0.078, 0.352), (0.074, 0.356), (0.066, 0.344),
            (0.050, 0.334), (0.0, 0.330)]
    make_obj(f"{name}_Dish", K.lathe_uv(dish, segments=64), bronze, parent=root, index=index)
    oil = P.mat_emit(f"{name}_OilGlow", (0.9, 0.55, 0.20), 0.0)
    oil = K.Mat(f"{name}_Oil")
    ob = oil.principled(Base_Color=(0.035, 0.020, 0.006, 1.0), Roughness=0.22, Coat_Weight=0.25, Specular_IOR_Level=0.35)
    oil = oil.surface(ob.outputs[0])
    make_obj(f"{name}_OilSurf", K.lathe_uv([(0.0, 0.342), (0.064, 0.342)], segments=48), oil, parent=root, index=index)
    wick_top = Vector((0.0, 0.0, 0.346 + 0.012))
    make_obj(f"{name}_Wick", K.tube_uv([(0.0, 0.0, 0.338), (0.0, 0.0, 0.346), tuple(wick_top)], 0.0022, sides=8),
             P.mat_stone(f"{name}_WickM", color=(0.05, 0.03, 0.02), scale=200.0), parent=root, index=index)
    fz = wick_top + Vector((lean * 0.3, 0.0, 0.004))
    if flame > 0:
        fh = flame_h
        prof_f = [(0.0, 0.0), (0.006, 0.006 * fh / 0.07), (0.0105, 0.017 * fh / 0.07), (0.0095, 0.030 * fh / 0.07), (0.0058, 0.048 * fh / 0.07),
                  (0.0, fh)]
        f = make_obj(f"{name}_Flame", K.lathe_uv(prof_f, segments=40), K.mat_core_flame(f"{name}_FlameM"), parent=root, loc=tuple(fz),
                     index=index + 2)
        f.rotation_euler = (0.0, lean, 0.0)
        upd()
        K.point_light(f"{name}_Light", tuple(root.matrix_world @ (fz + Vector((0, 0, fh * 0.35)))), 3.0 * flame * scale * scale,
                      radius=0.01 * scale, color=(1.0, 0.62, 0.30))
    return root, fz


def mat_ink_smoke(name, alpha=0.85, seed=0.0):
    """贴地的墨烟（夜色）：近黑、半透明的带子，UV.x 沿长、UV.y 横跨；两头淡出，横向边柔，沿长拉出一缕缕。"""
    M = K.Mat(name)
    m = M.math
    uv = M.coord("UV")
    sep = M.n("ShaderNodeSeparateXYZ")
    M.l(uv, sep.inputs[0])
    u, v = sep.outputs["X"], sep.outputs["Y"]
    across = m("POWER", m("SINE", m("MULTIPLY", v, math.pi)), 1.2)
    ends = m("MULTIPLY", M.maprange(u, 0.0, 0.3), M.maprange(u, 1.0, 0.6))
    mp = M.n("ShaderNodeMapping")
    M.l(uv, mp.inputs["Vector"])
    mp.inputs["Scale"].default_value = (2.0, 14.0, 1.0)
    nz = M.noise(mp.outputs["Vector"], scale=1.0, detail=6.0, rough=0.65, w=seed)
    streak = M.maprange(nz.outputs["Fac"], 0.38, 0.62, interp="SMOOTHSTEP")
    a_ = m("MULTIPLY", m("MULTIPLY", across, ends), m("ADD", m("MULTIPLY", streak, 0.8), 0.2))
    a_ = m("MULTIPLY", a_, alpha, clamp=True)
    bsdf = M.principled(Base_Color=(0.006, 0.006, 0.008, 1.0), Roughness=1.0, Specular_IOR_Level=0.0)
    tr = M.n("ShaderNodeBsdfTransparent")
    mx = M.n("ShaderNodeMixShader")
    M.l(a_, mx.inputs[0])
    M.l(tr.outputs[0], mx.inputs[1])
    M.l(bsdf.outputs[0], mx.inputs[2])
    return M.surface(mx.outputs[0])


@scene("changming", name="长明", samples=128, grade=dict(WARM_GRADE, exposure=1.0, bloom=0.36))
def build_changming(draft):
    """长明：俯看青石板地上一盏青铜灯台，灯光照出一圈暖光；光圈的外沿是一道亮边，正往外扩，
    外面一道更淡的余波；圈外的夜色是贴地的墨烟，被光推着往外退、卷起来。"""
    from mathutils import Vector  # noqa: PLC0415

    sky_gradient(lin("#05060A"), lin("#1E1A18"), 0.4, ground=lin("#030303"))
    rng = np.random.default_rng(47)
    make_obj("Ground", K.box_build(14.0, 14.0, 0.02), mat_paving("Paving"), loc=(0, 1.0, -0.01), index=0, smooth=False)
    bronze_oil_lamp("Lamp", loc=(0, 0, 0), scale=2.1, flame=1.8)
    K.point_light("Pool", (0, 0, 1.15), 130.0, radius=0.10, color=(1.0, 0.62, 0.30))
    # 光圈：亮边在 1.25 米，外面一道余波
    make_obj("Ring0", flat_ring_build(0.20, 1.25, 0.006, seed=1), mat_light_ring("RingM0", strength=8.0, seed=1.0, inner=0.025), index=4)
    make_obj("Ring1", flat_ring_build(1.42, 1.60, 0.005, m=20, seed=2), mat_light_ring("RingM1", strength=2.2, seed=4.0, inner=0.0),
             index=4)
    # 往外漂的光点
    ember = K.mat_ember("Mote")
    for k in range(40):
        a = rng.uniform(0, 2 * math.pi)
        r = rng.uniform(0.9, 1.7)
        make_obj(f"Mote{k}", K.ico_cloud([(0, 0, 0)], [rng.uniform(0.004, 0.009)], 1), ember,
                 loc=(r * math.cos(a), r * math.sin(a), rng.uniform(0.02, 0.35)), index=4)
    # 墨烟：圈外一缕缕，往外退、卷起
    for k in range(22):
        a = 2 * math.pi * k / 22 + rng.normal(0, 0.10)
        r0 = rng.uniform(1.40, 1.60)
        pts = []
        for t in np.linspace(0, 1, 40):
            r = r0 + 1.4 * t
            aa = a + 0.35 * t * (1 if k % 2 else -1)
            pts.append((r * math.cos(aa), r * math.sin(aa), 0.02 + 0.25 * t * t))
        make_obj(f"Smoke{k}", K.ribbon_uv(pts, rng.uniform(0.35, 0.6), ups=[(-math.sin(a), math.cos(a), 0.0)] * len(pts)),
                 mat_ink_smoke(f"SmokeM{k}", alpha=0.9, seed=k * 1.3), index=0)
    K.area_light("Moon", (-3.0, 5.0, 5.0), (0, 0.5, 0), 420.0, 3.0, color=(0.50, 0.62, 0.95))
    K.camera((0.0, -2.9, 2.2), (0.0, 0.25, 0.18), lens=34.0, fstop=8.0, focus=3.5)
    return {"light": "warm"}


@background("changming")
def bg_changming(P_, h, w, rng, k):
    P_.fill_grad("#0A0B10", "#0C0D12", cloud=0.12)
    K.bg_glow(P_, 0.50, 0.55, 0.40, 0.40, "#5A3A1C", 0.25)
    K.bg_ink(P_, [(0.02, 0.06, 0.30, 0.22, 0.2), (0.98, 0.08, 0.30, 0.22, -0.4), (0.02, 0.96, 0.30, 0.22, -0.2), (0.98, 0.96, 0.30, 0.22, 0.3)],
             0.55)


# ====================================================================== 炉心


@scene("luxin", name="炉心", samples=128, grade=dict(WARM_GRADE, exposure=0.98, bloom=0.42, sat=1.04))
def build_luxin(draft):
    """炉心：从下往上看一盏正升空的孔明灯的底口：方圆的竹圈、两根十字铁丝托着一只小铁炉，炉里一团白热的火，
    火光把纸袋从里面照得通红；几粒火星往下落，远处夜空里还有两盏小灯。"""
    from mathutils import Vector  # noqa: PLC0415

    sky_gradient(lin("#06070C"), lin("#2A2230"), 0.6, ground=lin("#030305"))
    rng = np.random.default_rng(29)
    root = P.sky_lantern("Lantern", H=0.90, top=0.30, bottom=0.22, fire=False, loc=(0, 0, 0), rot=(math.radians(4), math.radians(-6), 0.3))
    # 小铁炉：一只浅碗挂在十字铁丝中间，碗里一块烧得通红的燃料、上面一团白热的火
    iron = K.mat_iron("Furnace")
    make_obj("Bowl", K.lathe_uv([(0.0, -0.035), (0.030, -0.034), (0.046, -0.022), (0.052, 0.0), (0.049, 0.004), (0.040, -0.016),
                                  (0.0, -0.022)], segments=48), iron, parent=root, index=1)
    coal = K.Mat("Coal")
    oc = coal.coord("Object")
    nz = coal.noise(oc, scale=90.0, detail=5.0, rough=0.6)
    hot = coal.maprange(nz.outputs["Fac"], 0.35, 0.65)
    cc, _ = coal.ramp(hot, [(0.0, (0.08, 0.02, 0.005)), (0.5, (1.0, 0.30, 0.04)), (1.0, (1.0, 0.85, 0.50))])
    em = coal.n("ShaderNodeEmission")
    coal.l(cc, em.inputs["Color"])
    coal.l(coal.math("MULTIPLY", hot, 30.0), em.inputs["Strength"])
    coal.surface(em.outputs[0])
    make_obj("Fuel", K.ico_cloud([(0, 0, 0)], [0.034], 3), coal.m, parent=root, loc=(0, 0, -0.012), scale=(1.0, 1.0, 0.45), index=1)
    flame = make_obj("Flame", K.lathe_uv([(0.0, 0.0), (0.030, 0.012), (0.040, 0.040), (0.032, 0.085), (0.016, 0.135), (0.0, 0.19)],
                                          segments=32), K.mat_core_flame("FlameM"), parent=root, loc=(0, 0, -0.004), index=3)
    flame.scale = (1.15, 1.15, 1.25)
    L = K._bpy().data.lights.new("FireLight", "POINT")
    L.energy, L.color, L.shadow_soft_size = 90.0, (1.0, 0.58, 0.24), 0.03
    lo = K.link(K._bpy().data.objects.new("FireLight", L), root)
    lo.location = (0, 0, 0.09)
    # 往下落的火星
    ember = K.mat_ember("Ember")
    for k in range(26):
        p = Vector((rng.normal(0, 0.10), rng.normal(0, 0.10), -rng.uniform(0.05, 0.6)))
        r0 = rng.uniform(0.002, 0.004)
        ob = make_obj(f"Spark{k}", K.lathe_uv([(0.0, -1.0), (0.6, -0.6), (1.0, 0.0), (0.6, 0.6), (0.0, 1.0)], segments=8), ember,
                      loc=tuple(p), scale=(r0, r0, r0 * rng.uniform(2.5, 5.0)), index=3)
        ob.rotation_euler = (rng.normal(0, 0.2), rng.normal(0, 0.2), 0)
    # 远处两盏小孔明灯
    for k, (p, s) in enumerate((((1.6, 4.2, 2.6), 0.55), ((-2.2, 6.0, 3.4), 0.45))):
        P.sky_lantern(f"Far{k}", loc=p, rot=(0.1 * k, -0.1, 0.5 * k), light_w=20.0, fire_strength=0.8)
        K._bpy().data.objects[f"Far{k}"].scale = (s, s, s)
    K.area_light("Moon", (-2.0, 2.0, 3.0), (0, 0, 0.4), 30.0, 1.5, color=(0.55, 0.62, 0.95))
    K.camera((0.24, -0.62, -0.78), (0.0, 0.02, 0.25), lens=26.0, fstop=4.0, focus=1.0)
    return {"light": "warm"}


@background("luxin")
def bg_luxin(P_, h, w, rng, k):
    P_.fill_grad("#0A0B12", "#120F16", cloud=0.12)
    K.bg_glow(P_, 0.50, 0.45, 0.50, 0.45, "#5A2E16", 0.30)
    bg_clouds(P_, rng, k, [(0.20, 0.03, 0.40, 0.98), (0.82, 0.03, 0.02, 0.60)], "#4C4058", 0.16)
    K.bg_ink(P_, [(0.02, 0.06, 0.26, 0.18, 0.2), (0.98, 0.96, 0.30, 0.20, -0.2)], 0.45)


# ====================================================================== 磐石


def mat_river(name, foam_img=None, color=(0.006, 0.020, 0.026)):
    """激流的水面：深青黑、很亮的反光，沿流向拉长的波纹（物体坐标 Y 是流向），白沫贴图（UV）盖在上面。"""
    M = K.Mat(name)
    m = M.math
    oc = M.coord("Object")
    mp = M.n("ShaderNodeMapping")
    M.l(oc, mp.inputs["Vector"])
    mp.inputs["Scale"].default_value = (2.5, 0.6, 1.0)
    nz = M.noise(mp.outputs["Vector"], scale=6.0, detail=8.0, rough=0.62, dist=0.6)
    nrm = M.bump(nz.outputs["Fac"], strength=0.55, distance=0.05)
    bsdf = M.principled(Base_Color=(*color, 1.0), Roughness=0.06, IOR=1.33, Normal=nrm, Specular_IOR_Level=0.7)
    shader = bsdf.outputs[0]
    if foam_img is not None:
        uv = M.coord("UV")
        t = M.n("ShaderNodeTexImage", _interpolation="Cubic", _extension="CLIP")
        t.image = foam_img
        M.l(uv, t.inputs["Vector"])
        sc = M.n("ShaderNodeSeparateColor")
        M.l(t.outputs["Color"], sc.inputs[0])
        fb = M.principled(Base_Color=(0.78, 0.86, 0.92, 1.0), Roughness=0.6, Subsurface_Weight=0.3, Subsurface_Radius=(0.02, 0.03, 0.04),
                          Subsurface_Scale=0.02, Normal=nrm)
        mx = M.n("ShaderNodeMixShader")
        M.l(sc.outputs[0], mx.inputs[0])
        M.l(shader, mx.inputs[1])
        M.l(fb.outputs[0], mx.inputs[2])
        shader = mx.outputs[0]
    _ = m
    return M.surface(shader)


def river_foam(rng, w=2048, h=1024, rock=(0.47, 0.42), rx=0.075, ry=0.11):
    """激流的白沫（UV：x 沿流向 0 = 左边上游 → 1 = 右边下游，y 横跨河面 0 = 近 → 1 = 远）：石头上游一道翻起的白浪，
    石头两侧往下游拖出两条白练，河面散着一缕缕顺流的泡沫纹（近处疏、远处密）。返回 (h, w)。"""
    V = K.vfx()
    Y, X = np.mgrid[0:h, 0:w].astype(np.float64)
    u, v = X / w, 1 - Y / h
    n1 = V.fft_blur(rng.standard_normal((h, w)), (60.0, 3.0))
    n1 = n1 / (n1.std() + 1e-9)
    n2 = V.fft_blur(rng.standard_normal((h, w)), (16.0, 1.2))
    n2 = n2 / (n2.std() + 1e-9)
    cx, cy = rock
    dv = (v - cy) / ry
    du = u - cx
    up = np.exp(-((du + rx * 1.05) / 0.025) ** 2) * np.exp(-dv ** 2 / 1.3)  # 石头上游的翻浪
    up += 0.6 * np.exp(-((du + rx * 1.35) / 0.05) ** 2) * np.exp(-dv ** 2 / 2.5)
    down = np.clip(du / 0.6, 0, 1)
    tails = np.zeros_like(u)
    for sgn in (-1, 1):
        v0 = cy + sgn * ry * (0.9 + 1.2 * down)
        tails += np.exp(-((v - v0) / (0.015 + 0.06 * down)) ** 2) * (du > -rx * 0.3) * np.clip(1 - down, 0, 1)
    wake = np.exp(-(dv / (0.6 + 2.0 * down)) ** 2) * (du > rx) * np.clip(1 - down * 1.2, 0, 1) * 0.5
    streaks = np.clip(np.tanh(1.3 * (n1 - 0.8)), 0, 1) * 0.45 + np.clip(np.tanh(2.0 * (n2 - 1.2)), 0, 1) * 0.30
    f = np.clip(up * (0.8 + 0.3 * n2) + tails * (0.55 + 0.35 * n1) + wake * (0.6 + 0.4 * n2) + streaks * (0.15 + 0.35 * v), 0, 1)
    return f.astype(np.float32)


@scene("panshi", name="磐石", samples=128, grade=dict(EARTH_GRADE, exposure=1.02, shadow="#121C26", high="#EEF2FA", sat=0.96), fog=(9.0, 18.0))
def build_panshi(draft):
    """磐石：一块巨大的磐石立在激流中间，纹丝不动；水从左边冲过来，在石前翻成一道白浪、水花碎开往上溅，
    石头两侧往右拖出两条白练。石顶几片青苔。月光从后上方打过来，水面一片碎光。"""
    from mathutils import Vector  # noqa: PLC0415

    sky_gradient(lin("#05080D"), lin("#2C3A4C"), 0.8, ground=lin("#03050A"))
    rng = np.random.default_rng(97)
    stone = P.mat_stone("Boulder", color=(0.20, 0.195, 0.185), scale=1.6, cavity=1.0, bump=1.0, bump_dist=0.04, moss=0.9)
    P.rock_mesh("Boulder", stone, scale=(1.15, 0.95, 1.30), loc=(0.0, 0.0, 0.50), rot=(0.05, 0.10, 0.5), crag=0.32, crag_size=1.0, fine=0.08,
                index=1, flat_bottom=-0.55, subdiv=6, seed=12, ridges=5, ridge_amp=0.20)
    for k, (p, s_) in enumerate((((2.3, 1.2, -0.02), 0.32), ((-2.6, 2.6, -0.02), 0.40), ((3.4, 4.5, 0.0), 0.55))):
        P.rock_mesh(f"Rock{k}", stone, scale=(s_ * 1.3, s_, s_ * 0.8), loc=p, rot=tuple(rng.uniform(0, 1, 3)), crag=0.25, index=1,
                    flat_bottom=-0.2, subdiv=4, seed=20 + k)
    foam = K.np_image("river_foam", river_foam(rng))

    def plane(bm):  # 河面：x ∈ [-5, 5]（流向），y ∈ [-2, 8]（近 → 远）；UV.x 沿流向、UV.y 横跨
        uvl = bm.loops.layers.uv.new("UVMap")
        vs = [bm.verts.new((x, y, 0.0)) for x, y in ((-6, -6), (6, -6), (6, 8), (-6, 8))]
        f = bm.faces.new(vs)
        for lp in f.loops:  # 贴图只铺在 x ∈ [-5, 5]、y ∈ [-2, 8]，外面 CLIP 掉（只剩水）
            lp[uvl].uv = ((lp.vert.co.x + 5) / 10, (lp.vert.co.y + 2) / 10)
    make_obj("River", plane, mat_river("RiverM", foam), index=0)
    # 石前碎开的水花：从石头左侧往上、往左上溅
    spray = P.mat_foam("Spray", emit=0.10)
    pts_, rad_ = [], []
    for i in range(3200):
        a = rng.uniform(-1.3, 1.3)  # 绕石头左侧（-X）的角度
        r = 1.0 + abs(rng.normal(0, 0.12))
        x, y = -r * math.cos(a) * 0.95, r * math.sin(a) * 0.8
        hgt = abs(rng.normal(0, 0.55)) * math.cos(a) ** 1.5
        x -= 0.35 * hgt * rng.uniform(0.2, 1.0)
        pts_.append((x + rng.normal(0, 0.06), y + rng.normal(0, 0.06), hgt))
        rad_.append(rng.uniform(0.003, 0.011) * (1.2 - min(hgt, 1.0) * 0.5))
    make_obj("Spray", K.ico_cloud(pts_, rad_, 1), spray, index=3)
    K.area_light("Moon", (-2.0, 6.0, 4.0), (0, 0.0, 0.5), 900.0, 2.0, color=(0.62, 0.74, 1.0))
    K.area_light("Rim", (3.0, 3.0, 1.5), (0, 0.0, 0.6), 160.0, 1.5, color=(0.60, 0.72, 1.0))
    K.area_light("Front", (-1.5, -4.0, 2.5), (0, 0.0, 0.6), 220.0, 3.0, color=(0.66, 0.74, 0.95))
    K.camera((0.4, -4.3, 1.05), (0.0, 0.3, 0.50), lens=34.0, fstop=8.0, focus=4.3)
    _ = Vector
    return {"light": "cold"}


@background("panshi")
def bg_panshi(P_, h, w, rng, k):
    P_.fill_grad("#0A1018", "#121A24", cloud=0.12)
    K.bg_glow(P_, 0.45, 0.30, 0.45, 0.35, "#3C5068", 0.30)
    K.bg_moon(P_, 0.24, 0.20, 0.045, rng, k, color="#E6ECF4", halo="#7890B6", a=0.5, halo_a=0.28)
    K.bg_mountains(P_, [(0.42, [(0.15, 0.14, 0.12, 0.12), (0.45, 0.10, 0.14, 0.12), (0.80, 0.16, 0.14, 0.14)], "#1A2433", 0.8, 0.10, 6.0,
                         "#6E8098")], rng, k)
    K.bg_mist(P_, 0.44, 0.04, "#8CA0B8", 0.18, rng, k)
    K.bg_ink(P_, [(0.98, 0.06, 0.26, 0.18, -0.4), (0.02, 0.96, 0.30, 0.20, 0.2)], 0.45)


# ====================================================================== 厚德


def slab_build(x0, x1, y0, y1, zb, zt, nx=60, ny=30):
    """一层土石（实心）：底面 zb(x, y)、顶面 zt(x, y) 两张起伏的网格，四周竖墙连起来。"""
    def build(bm):
        import bmesh  # noqa: PLC0415

        def grid(fz):
            g = []
            for j in range(ny + 1):
                y = y0 + (y1 - y0) * j / ny
                g.append([bm.verts.new((x0 + (x1 - x0) * i / nx, y, fz(x0 + (x1 - x0) * i / nx, y))) for i in range(nx + 1)])
            return g

        top, bot = grid(zt), grid(zb)
        for j in range(ny):
            for i in range(nx):
                bm.faces.new((top[j][i], top[j][i + 1], top[j + 1][i + 1], top[j + 1][i]))
                bm.faces.new((bot[j][i], bot[j + 1][i], bot[j + 1][i + 1], bot[j][i + 1]))
        for i in range(nx):  # 前后两面
            bm.faces.new((bot[0][i], bot[0][i + 1], top[0][i + 1], top[0][i]))
            bm.faces.new((bot[ny][i + 1], bot[ny][i], top[ny][i], top[ny][i + 1]))
        for j in range(ny):  # 左右两面
            bm.faces.new((bot[j + 1][0], bot[j][0], top[j][0], top[j + 1][0]))
            bm.faces.new((bot[j][nx], bot[j + 1][nx], top[j + 1][nx], top[j][nx]))
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    return build


def mat_gravel(name, color=(0.16, 0.15, 0.14)):
    """卵石层：Voronoi 一颗颗石子（各自明暗），石缝压黑。"""
    M = K.Mat(name)
    m = M.math
    oc = M.coord("Object")
    vor = M.n("ShaderNodeTexVoronoi", Scale=26.0, _feature="F1")
    M.l(oc, vor.inputs["Vector"])
    vor2 = M.n("ShaderNodeTexVoronoi", Scale=26.0, _feature="DISTANCE_TO_EDGE")
    M.l(oc, vor2.inputs["Vector"])
    sep = M.n("ShaderNodeSeparateColor")
    M.l(vor.outputs["Color"], sep.inputs[0])
    tone = sep.outputs[0]
    col = M.mix(tone, (color[0] * 0.5, color[1] * 0.5, color[2] * 0.5, 1.0), (color[0] * 1.6, color[1] * 1.5, color[2] * 1.4, 1.0))
    edge = M.maprange(vor2.outputs["Distance"], 0.0, 0.08, 1.0, 0.0)
    col = M.mix(edge, col, (0.01, 0.009, 0.008, 1.0))
    nrm = M.bump(m("SUBTRACT", 1.0, edge), strength=0.9, distance=0.01)
    bsdf = M.principled(Base_Color=col, Roughness=0.7, Normal=nrm)
    return M.surface(bsdf.outputs[0])


def mat_plaster(name, color=(0.62, 0.60, 0.55)):
    """粉墙：灰白，下沿脏一点，细的斑驳。"""
    M = K.Mat(name)
    oc = M.coord("Object")
    nz = M.noise(oc, scale=40.0, detail=6.0)
    sep = M.n("ShaderNodeSeparateXYZ")
    M.l(oc, sep.inputs[0])
    col = M.mix(M.maprange(nz.outputs["Fac"], 0.3, 0.7), (color[0] * 0.8, color[1] * 0.78, color[2] * 0.74, 1.0), (*color, 1.0))
    nrm = M.bump(nz.outputs["Fac"], strength=0.2, distance=0.003)
    bsdf = M.principled(Base_Color=col, Roughness=0.85, Normal=nrm)
    return M.surface(bsdf.outputs[0])


def cottage(name, *, loc=(0, 0, 0), rot_z=0.0, w=0.40, d=0.28, wall=0.17, roof_h=0.13, lit=True, index=2, scale=1.0):
    """一座小屋：粉墙、黑瓦两坡顶（檐角微翘），正面一门两窗透出暖光。返回父物体。"""
    bpy = K._bpy()
    root = bpy.data.objects.new(name, None)
    K.link(root)
    root.location, root.rotation_euler, root.scale = loc, (0, 0, rot_z), (scale, scale, scale)
    make_obj(f"{name}_Wall", K.box_build(w, d, wall), mat_plaster(f"{name}_Plaster"), parent=root, loc=(0, 0, wall / 2), index=index,
             bevel=(0.004, 2), smooth=False)
    make_obj(f"{name}_Roof", P.roof_build(w=w * 1.18, d=d * 1.25, h=roof_h, curl=0.05, wall_h=0.0), P.mat_roof_tiles(f"{name}_Tiles", rows=30.0),
             parent=root, loc=(0, 0, wall - 0.005), index=index)
    if lit:
        glow = P.mat_emit(f"{name}_Win", (1.0, 0.62, 0.28), 6.0)
        for x, ww, hh, z in ((-w * 0.28, w * 0.16, wall * 0.30, wall * 0.55), (w * 0.28, w * 0.16, wall * 0.30, wall * 0.55),
                             (0.0, w * 0.17, wall * 0.62, wall * 0.31)):
            make_obj(f"{name}_W{x:.2f}", K.box_build(ww, 0.004, hh), glow, parent=root, loc=(x, -d / 2 - 0.002, z), index=index)
        upd()
        K.point_light(f"{name}_L", tuple(root.matrix_world @ __import__("mathutils").Vector((0, -d / 2 - 0.05, wall * 0.5))), 0.6 * scale,
                      radius=0.02, color=(1.0, 0.62, 0.30))
    return root


def mat_foliage(name, color=(0.05, 0.12, 0.05)):
    M = K.Mat(name)
    oc = M.coord("Object")
    nz = M.noise(oc, scale=60.0, detail=6.0, rough=0.7)
    col = M.mix(M.maprange(nz.outputs["Fac"], 0.3, 0.7), (color[0] * 0.5, color[1] * 0.5, color[2] * 0.5, 1.0),
                (color[0] * 1.6, color[1] * 1.5, color[2] * 1.3, 1.0))
    nrm = M.bump(nz.outputs["Fac"], strength=0.8, distance=0.01)
    bsdf = M.principled(Base_Color=col, Roughness=0.8, Normal=nrm)
    return M.surface(bsdf.outputs[0])


def tree(name, *, loc=(0, 0, 0), h=0.45, r=0.16, kind="round", rng=None, index=2, trunk_m=None, leaf_m=None):
    """一棵小树：kind="round" 一团团圆冠，"pine" 几层塔形松针。"""
    rng = rng or np.random.default_rng(3)
    from mathutils import Vector  # noqa: PLC0415

    trunk_m = trunk_m or mat_bark(f"{name}_Bark", color=(0.06, 0.045, 0.035), crack=0.6)
    leaf_m = leaf_m or mat_foliage(f"{name}_Leaf")
    base = Vector(loc)
    make_obj(f"{name}_T", K.tube_uv([tuple(base), tuple(base + Vector((0.01, 0.0, h * 0.55))), tuple(base + Vector((0.0, 0.01, h * 0.8)))],
                                    r * 0.12, sides=10, radius_fn=lambda t: 1 - 0.5 * t), trunk_m, index=index)
    if kind == "pine":
        for k in range(4):
            z = h * (0.35 + 0.18 * k)
            rr = r * (1.0 - 0.22 * k)
            make_obj(f"{name}_C{k}", K.lathe_uv([(0.0, 0.0), (rr, 0.02), (rr * 0.9, 0.05), (0.0, h * 0.30)], segments=18,
                                               radial=lambda th, zz, i: 1 + 0.12 * math.sin(th * 9 + k)), leaf_m,
                     loc=tuple(base + Vector((0, 0, z))), index=index)
    else:
        pts, rad = [], []
        for k in range(9):
            pts.append(tuple(base + Vector((rng.normal(0, r * 0.45), rng.normal(0, r * 0.35), h * 0.75 + rng.normal(0, r * 0.35)))))
            rad.append(r * rng.uniform(0.45, 0.70))
        make_obj(f"{name}_Crown", K.ico_cloud(pts, rad, 2), leaf_m, index=index)


@scene("houde", name="厚德", samples=128, grade=dict(EARTH_GRADE, exposure=1.04))
def build_houde(draft):
    """厚德：一整块大地被切开（地势坤）：剖面上土石一层层厚实地叠着——草皮、黄土、红土、卵石、青石、黑色的基岩，
    层与层交界起伏；顶上稳稳托着一座小屋（窗里透着暖光）和一棵树。整块浮在夜里，斜前方看，暖光从左打来。"""
    from mathutils import Vector  # noqa: PLC0415

    sky_gradient(lin("#06070B"), lin("#2C2822"), 0.6, ground=lin("#040404"))
    rng = np.random.default_rng(71)
    X0, X1, Y0, Y1 = -0.85, 0.85, -0.50, 0.50

    def wav(seed, amp, f=3.0):
        ph = np.random.default_rng(seed).uniform(0, 6.28, 4)
        return lambda x, y: amp * (math.sin(f * x + ph[0]) + 0.5 * math.sin(2.3 * f * x + ph[1]) + 0.4 * math.sin(1.7 * f * y + ph[2]))

    bounds = [0.0, -0.10, -0.36, -0.56, -0.74, -1.10, -1.55]  # 各层的交界（自上而下）
    waves = [wav(1, 0.012), wav(2, 0.030), wav(3, 0.028), wav(4, 0.020), wav(5, 0.040), wav(6, 0.050), wav(7, 0.0)]
    mats = [P.mat_stone("Soil", color=(0.075, 0.050, 0.030), scale=12.0, bump=0.6),
            P.mat_stone("Loess", color=(0.30, 0.205, 0.105), scale=6.0, cavity=0.8, bump=0.8),
            P.mat_stone("RedClay", color=(0.21, 0.085, 0.045), scale=8.0, bump=0.7),
            mat_gravel("Gravel", color=(0.17, 0.155, 0.14)),
            P.mat_stone("BlueStone", color=(0.10, 0.12, 0.13), scale=3.0, cavity=1.0, bump=1.2, bump_dist=0.02),
            P.mat_stone("Bedrock", color=(0.035, 0.035, 0.04), scale=2.0, cavity=1.0, bump=1.4, bump_dist=0.03)]
    for k in range(6):
        zt = (lambda kk: (lambda x, y: bounds[kk] + waves[kk](x, y)))(k)
        zb = (lambda kk: (lambda x, y: bounds[kk + 1] + waves[kk + 1](x, y) + (0.0 if kk < 5 else -0.25 * (1 - (x / X1) ** 2))))(k)
        make_obj(f"Layer{k}", slab_build(X0, X1, Y0, Y1, zb, zt), mats[k], index=1, smooth=False)
    # 草皮：顶面一层青草（细短的草叶），边上垂下几缕根
    grass = mat_young_leaf("Grass", color=(0.05, 0.14, 0.03), tip=(0.20, 0.30, 0.06))
    blades = []

    def blade_mesh(bm):
        import bmesh  # noqa: PLC0415

        for _ in range(1400):
            x, y = rng.uniform(X0 + 0.01, X1 - 0.01), rng.uniform(Y0 + 0.01, Y1 - 0.01)
            z = bounds[0] + waves[0](x, y)
            hgt = rng.uniform(0.015, 0.045)
            a = rng.uniform(0, 6.28)
            tip = (x + 0.01 * math.cos(a), y + 0.01 * math.sin(a), z + hgt)
            tmp = bmesh.new()
            K.ribbon_uv([(x, y, z - 0.003), ((x + tip[0]) / 2, (y + tip[1]) / 2, z + hgt * 0.6), tip], 0.004,
                        ups=[(math.cos(a + 1.57), math.sin(a + 1.57), 0)] * 3, width_fn=lambda t: 1 - 0.9 * t, segs_w=1)(tmp)
            me = K._bpy().data.meshes.new("tmp")
            tmp.to_mesh(me)
            tmp.free()
            bm.from_mesh(me)
            K._bpy().data.meshes.remove(me)
        blades.append(1)
    make_obj("Grass", blade_mesh, grass, index=1)
    roots = mat_bark("Roots", color=(0.10, 0.07, 0.045), crack=0.0)
    for k in range(8):
        x = rng.uniform(X0 + 0.08, X1 - 0.08)
        z0 = bounds[0] + waves[0](x, Y0) - 0.02
        pts = [(x, Y0 - 0.003, z0)]
        for t in np.linspace(0.1, 1, 8):
            pts.append((x + 0.02 * math.sin(t * 6 + k), Y0 - 0.004, z0 - 0.11 * t * rng.uniform(0.6, 1.2)))
        make_obj(f"Root{k}", K.tube_uv(pts, 0.0025, sides=6, radius_fn=lambda t: 1 - 0.8 * t), roots, index=1)
    # 小屋和树
    top = lambda x, y: bounds[0] + waves[0](x, y)  # noqa: E731
    cottage("House", loc=(-0.10, 0.02, top(-0.10, 0.02) - 0.005), rot_z=math.radians(8), scale=1.25)
    tree("Tree", loc=(0.45, 0.12, top(0.45, 0.12) - 0.01), h=0.50, r=0.17, rng=rng)
    tree("Pine", loc=(-0.58, 0.25, top(-0.58, 0.25) - 0.01), h=0.42, r=0.11, kind="pine", rng=rng)
    K.area_light("Key", (-2.5, -2.0, 2.2), (0, 0, -0.3), 260.0, 2.0, color=(1.0, 0.86, 0.66))
    K.area_light("Rim", (2.0, 2.5, 1.5), (0, 0, -0.3), 160.0, 1.5, color=(0.62, 0.72, 1.0))
    K.area_light("Fill", (1.5, -3.0, -0.5), (0, 0, -0.5), 40.0, 2.0, color=(0.62, 0.70, 0.95))
    K.camera((1.02, -2.85, 0.98), (0.0, 0.0, -0.36), lens=40.0, fstop=8.0, focus=3.0)
    _ = Vector
    return {"light": "earth"}


@background("houde")
def bg_houde(P_, h, w, rng, k):
    P_.fill_grad("#0D0F16", "#16130F", cloud=0.12)
    K.bg_glow(P_, 0.45, 0.35, 0.50, 0.40, "#5E4026", 0.28)
    K.bg_mountains(P_, [(0.80, [(0.12, 0.12, 0.12, 0.12), (0.34, 0.07, 0.12, 0.10), (0.80, 0.14, 0.12, 0.14), (0.97, 0.08, 0.10, 0.10)],
                         "#221E1A", 0.7, 0.10, 6.0, "#7C6A56")], rng, k)
    bg_clouds(P_, rng, k, [(0.18, 0.03, 0.25, 0.80), (0.86, 0.02, 0.05, 0.95)], "#5A5248", 0.16)
    K.bg_ink(P_, [(0.02, 0.06, 0.26, 0.18, 0.2), (0.98, 0.08, 0.24, 0.18, -0.4)], 0.45)


# ====================================================================== 载物


def mat_shield_bronze(name):
    """盾面：老青铜，大片青绿锈，凸起处磨出铜色；盾心一圈圈同心的浅纹（车削痕）。"""
    M = K.Mat(name)
    m = M.math
    oc = M.coord("Object")
    sep = M.n("ShaderNodeSeparateXYZ")
    M.l(oc, sep.inputs[0])
    r = m("SQRT", m("ADD", m("MULTIPLY", sep.outputs["X"], sep.outputs["X"]), m("MULTIPLY", sep.outputs["Y"], sep.outputs["Y"])))
    rings = m("ABSOLUTE", m("SINE", m("MULTIPLY", r, 180.0)))
    n1 = M.noise(oc, scale=4.0, detail=6.0, rough=0.6)
    n2 = M.noise(oc, scale=30.0, detail=6.0, rough=0.7)
    geo = M.n("ShaderNodeNewGeometry")
    wear = m("ADD", M.maprange(geo.outputs["Pointiness"], 0.53, 0.60), m("MULTIPLY", M.maprange(n1.outputs["Fac"], 0.62, 0.76), 0.6),
             clamp=True)
    patina = M.mix(M.maprange(n2.outputs["Fac"], 0.3, 0.7), (0.020, 0.055, 0.045, 1.0), (0.060, 0.140, 0.110, 1.0))
    bronze = M.mix(M.maprange(n2.outputs["Fac"], 0.3, 0.7), (0.22, 0.13, 0.05, 1.0), (0.42, 0.27, 0.11, 1.0))
    col = M.mix(wear, patina, bronze)
    nrm = M.bump(m("ADD", m("MULTIPLY", rings, 0.15), m("MULTIPLY", n2.outputs["Fac"], 0.4)), strength=0.35, distance=0.004)
    bsdf = M.n("ShaderNodeBsdfPrincipled")
    M.l(col, bsdf.inputs["Base Color"])
    M.l(wear, bsdf.inputs["Metallic"])
    M.l(M.mixf(wear, 0.62, 0.30), bsdf.inputs["Roughness"])
    M.l(nrm, bsdf.inputs["Normal"])
    return M.surface(bsdf.outputs[0])


@scene("zaiwu", name="载物", samples=128, grade=dict(EARTH_GRADE, exposure=1.04, bloom=0.32))
def build_zaiwu(draft):
    """载物：大地像一面宽厚的圆盾，斜斜地托在夜里；盾面是一片土地，上面立着三座山、几棵树、一个小村子（窗里有灯），
    盾沿是厚重的青铜边、一圈鎏金乳钉。暖光从左上打来，盾沿反出一道金。"""
    from mathutils import Vector  # noqa: PLC0415

    sky_gradient(lin("#06070B"), lin("#2C2822"), 0.6, ground=lin("#040404"))
    rng = np.random.default_rng(53)
    bpy = K._bpy()
    root = bpy.data.objects.new("Shield", None)
    K.link(root)
    root.rotation_euler = (math.radians(-12), math.radians(6), 0.0)
    upd()
    R = 1.0
    bronze = mat_shield_bronze("Bronze")
    gold = K.mat_gold("Gold", worn=0.5)
    # 盾身：微凸的厚圆盘（背面是锥形，看不太到）
    prof = [(0.0, -0.16), (R * 0.6, -0.13), (R * 0.97, -0.05), (R, 0.0), (R * 1.02, 0.04), (R * 0.99, 0.07), (R * 0.93, 0.065),
            (R * 0.90, 0.055), (0.0, 0.10)]
    make_obj("Disc", K.lathe_uv(prof, segments=180), bronze, parent=root, index=1)
    make_obj("Rim", K.torus_build(R * 0.985, 0.045, 180, 16), bronze, parent=root, loc=(0, 0, 0.055), index=1)
    for k in range(28):  # 鎏金乳钉
        a = 2 * math.pi * k / 28
        make_obj(f"Stud{k}", K.ico_cloud([(0, 0, 0)], [0.026], 2), gold, parent=root,
                 loc=(R * 0.985 * math.cos(a), R * 0.985 * math.sin(a), 0.095), index=1)
    make_obj("GoldBand", K.torus_build(R * 0.90, 0.010, 180, 8), gold, parent=root, loc=(0, 0, 0.06), index=1)
    # 盾面上的土地：一块微微起伏的地（圆形），三座山、几棵树、一个小村
    soil = P.mat_stone("Land", color=(0.10, 0.085, 0.05), scale=6.0, moss=0.8, bump=0.6)

    def land(bm):
        rings, nr, ns = [], 30, 120
        for j in range(nr + 1):
            rr = R * 0.88 * j / nr
            row = []
            for i in range(ns):
                a = 2 * math.pi * i / ns
                x, y = rr * math.cos(a), rr * math.sin(a)
                z = 0.075 + 0.02 * math.sin(3 * x + 1) * math.sin(4 * y) * (1 - (rr / (R * 0.88)) ** 2)
                row.append(bm.verts.new((x, y, z)))
            rings.append(row)
        c = bm.verts.new((0, 0, 0.075))
        for i in range(ns):
            bm.faces.new((c, rings[1][i], rings[1][(i + 1) % ns]))
        for j in range(1, nr):
            for i in range(ns):
                bm.faces.new((rings[j][i], rings[j + 1][i], rings[j + 1][(i + 1) % ns], rings[j][(i + 1) % ns]))
    make_obj("Land", land, soil, parent=root, index=1)
    peak = P.mat_stone("Peak", color=(0.11, 0.115, 0.11), scale=3.0, moss=0.9, cavity=1.0, bump=1.2, bump_dist=0.02)
    for k, (x, y, s_, h_) in enumerate(((-0.25, 0.42, 0.34, 0.85), (0.20, 0.50, 0.28, 0.65), (0.50, 0.25, 0.22, 0.50))):
        ob = P.rock_mesh(f"Mount{k}", peak, scale=(s_, s_ * 0.85, h_ * 0.5), loc=(x, y, 0.07 + h_ * 0.18), rot=(0, 0, rng.uniform(0, 6)),
                         peak=0.62, crag=0.22, crag_size=0.35, fine=0.04, index=1, flat_bottom=-0.35, subdiv=5, ridges=9, ridge_amp=0.6,
                         seed=40 + k, parent=root)
        _ = ob
    for k, (x, y, kind) in enumerate(((-0.55, 0.05, "pine"), (-0.45, -0.20, "round"), (0.62, -0.10, "pine"), (0.40, -0.35, "round"),
                                       (-0.15, 0.10, "pine"), (0.05, -0.55, "round"))):
        tree(f"Tree{k}", loc=tuple(root.matrix_world @ Vector((x, y, 0.07))), h=0.22, r=0.08, kind=kind, rng=rng)
    for k, (x, y, rz) in enumerate(((-0.12, -0.20, 0.3), (0.12, -0.12, -0.2), (0.0, -0.38, 0.1), (0.26, -0.32, 0.5))):
        p = root.matrix_world @ Vector((x, y, 0.07))
        cottage(f"House{k}", loc=tuple(p), rot_z=rz, scale=0.45)
    K.area_light("Key", (-2.2, -1.2, 2.6), (0, 0, 0.1), 300.0, 2.0, color=(1.0, 0.84, 0.62))
    K.area_light("Rim", (2.0, 2.2, 1.0), (0, 0, 0.1), 160.0, 1.5, color=(0.62, 0.72, 1.0))
    K.area_light("Fill", (1.0, -3.0, 0.4), (0, 0, 0.0), 40.0, 2.0, color=(0.62, 0.70, 0.95))
    K.camera((0.0, -2.75, 1.85), (0.0, 0.0, 0.10), lens=40.0, fstop=8.0, focus=3.3)
    return {"light": "earth"}


@background("zaiwu")
def bg_zaiwu(P_, h, w, rng, k):
    P_.fill_grad("#0D0F16", "#16130F", cloud=0.12)
    K.bg_glow(P_, 0.50, 0.50, 0.55, 0.45, "#5E4026", 0.30)
    bg_clouds(P_, rng, k, [(0.15, 0.03, 0.25, 0.80), (0.88, 0.02, 0.05, 0.95)], "#5A5248", 0.16)
    K.bg_ink(P_, [(0.02, 0.06, 0.26, 0.18, 0.2), (0.98, 0.08, 0.24, 0.18, -0.4), (0.02, 0.96, 0.26, 0.18, -0.2)], 0.45)


# ====================================================================== 引魂


def mat_lotus_paper(name, color=(0.95, 0.55, 0.62), base=(0.98, 0.90, 0.86)):
    """河灯的纸瓣：粉纸（瓣尖粉、瓣根近白），透光为主，里面的烛光透出来。UV.x 瓣根 → 瓣尖。"""
    M = K.Mat(name)
    uv = M.coord("UV")
    sep = M.n("ShaderNodeSeparateXYZ")
    M.l(uv, sep.inputs[0])
    col = M.mix(M.maprange(sep.outputs["X"], 0.2, 1.0), (*base, 1.0), (*color, 1.0))
    oc = M.coord("Object")
    fib = M.noise(oc, scale=300.0, detail=6.0, rough=0.7)
    nrm = M.bump(fib.outputs["Fac"], strength=0.1, distance=0.0005)
    trn = M.n("ShaderNodeBsdfTranslucent")
    M.l(col, trn.inputs["Color"])
    M.l(nrm, trn.inputs["Normal"])
    dif = M.n("ShaderNodeBsdfDiffuse")
    M.l(col, dif.inputs["Color"])
    mx = M.n("ShaderNodeMixShader")
    mx.inputs[0].default_value = 0.6
    M.l(dif.outputs[0], mx.inputs[1])
    M.l(trn.outputs[0], mx.inputs[2])
    return M.surface(mx.outputs[0])


def lotus_lamp(name, loc, *, scale=1.0, rot_z=0.0, petal_m=None, leaf_m=None, light_w=1.2, index=2):
    """一盏河灯：一圈绿纸荷叶托底，三层粉纸莲瓣（外层摊开、里层竖起），中间一根小红烛和一朵火。返回父物体。"""
    from mathutils import Matrix  # noqa: PLC0415

    bpy = K._bpy()
    root = bpy.data.objects.new(name, None)
    K.link(root)
    root.location, root.rotation_euler, root.scale = loc, (0, 0, rot_z), (scale, scale, scale)
    petal_m = petal_m or mat_lotus_paper(f"{name}_Petal")
    leaf_m = leaf_m or mat_young_leaf(f"{name}_Leaf", color=(0.04, 0.16, 0.06), tip=(0.08, 0.24, 0.08))
    for k in range(10):  # 荷叶托
        a = 2 * math.pi * k / 10
        ob = make_obj(f"{name}_L{k}", K.leaf_build(0.11, 0.07, fold=0.05, curl=-0.08), leaf_m, parent=root, index=index)
        ob.rotation_euler = (Matrix.Rotation(a, 3, "Z") @ Matrix.Rotation(math.radians(-6), 3, "Y")).to_euler()
        ob.location = (0.01 * math.cos(a), 0.01 * math.sin(a), 0.004)
    for layer, (n, L, tilt, z, ph) in enumerate(((10, 0.075, 18, 0.010, 0.0), (8, 0.065, 48, 0.016, 0.3), (6, 0.052, 70, 0.022, 0.1))):
        pb = petal_build(L, L * 0.55, cup=0.45, curl=-0.05)
        for k in range(n):
            a = 2 * math.pi * k / n + ph
            ob = make_obj(f"{name}_P{layer}_{k}", pb, petal_m, parent=root, index=index)
            ob.rotation_euler = (Matrix.Rotation(a, 3, "Z") @ Matrix.Rotation(-math.radians(tilt), 3, "Y")).to_euler()
            ob.location = (0.012 * math.cos(a), 0.012 * math.sin(a), z)
    make_obj(f"{name}_Candle", K.lathe_uv([(0.0, 0.02), (0.008, 0.02), (0.008, 0.06), (0.0, 0.062)], segments=16), K.mat_wax(f"{name}_Wax"),
             parent=root, index=index)
    make_obj(f"{name}_Flame", K.lathe_uv([(0.0, 0.0), (0.005, 0.005), (0.0075, 0.013), (0.006, 0.022), (0.0, 0.036)], segments=16),
             K.mat_core_flame(f"{name}_FlameM"), parent=root, loc=(0, 0, 0.064), index=index + 2)
    L_ = bpy.data.lights.new(f"{name}_Light", "POINT")
    L_.energy, L_.color, L_.shadow_soft_size = light_w, (1.0, 0.60, 0.30), 0.01
    lo = K.link(bpy.data.objects.new(f"{name}_Light", L_), root)
    lo.location = (0, 0, 0.08)
    return root


def mat_soul_fire(name, color=(0.45, 0.95, 0.85), strength=8.0):
    """魂火：青白的冷火（体积自发光的小团 + 拖尾用 mat_wind）。"""
    M = K.Mat(name)
    lw = M.n("ShaderNodeLayerWeight", Blend=0.4)
    a = M.math("POWER", M.math("SUBTRACT", 1.0, lw.outputs["Facing"], clamp=True), 1.5)
    emi = M.n("ShaderNodeEmission", Color=(*color, 1.0))
    M.l(M.math("MULTIPLY", a, strength), emi.inputs["Strength"])
    tr = M.n("ShaderNodeBsdfTransparent")
    mx = M.n("ShaderNodeMixShader")
    M.l(a, mx.inputs[0])
    M.l(tr.outputs[0], mx.inputs[1])
    M.l(emi.outputs[0], mx.inputs[2])
    return M.surface(mx.outputs[0])


@scene("yinhun", name="引魂", samples=128, grade=dict(COLD_GRADE, exposure=1.02, bloom=0.40, sat=1.0), fog=(7.0, 16.0))
def build_yinhun(draft):
    """引魂：中元夜的河面，一盏盏莲花河灯从近处排到远处、往右边岸上漂；几点青白的魂火拖着细尾跟着灯往岸边漂。
    水面倒映着灯光，远处岸边一丛芦苇。"""
    from mathutils import Vector  # noqa: PLC0415

    sky_gradient(lin("#05070D"), lin("#24324A"), 0.7, ground=lin("#03050A"))
    rng = np.random.default_rng(37)
    water = K.Mat("Water")
    oc = water.coord("Object")
    nz = water.noise(oc, scale=3.0, detail=8.0, rough=0.6, dist=0.4)
    nz2 = water.noise(oc, scale=24.0, detail=4.0)
    nrm = water.bump(water.math("ADD", nz.outputs["Fac"], water.math("MULTIPLY", nz2.outputs["Fac"], 0.3)), strength=0.07, distance=0.02)
    bsdf = water.principled(Base_Color=(0.004, 0.010, 0.016, 1.0), Roughness=0.04, Normal=nrm, Specular_IOR_Level=0.8)
    water.surface(bsdf.outputs[0])
    make_obj("River", K.box_build(30.0, 30.0, 0.01), water.m, loc=(0, 10.0, -0.005), index=0, smooth=False)  # 平滑着色的盒子顶面法线是斜的
    petal_m = mat_lotus_paper("Petal")
    leaf_m = mat_young_leaf("LotusLeaf", color=(0.04, 0.16, 0.06), tip=(0.08, 0.24, 0.08))
    path = [(-0.55, 0.15), (-0.10, 0.75), (0.30, 1.55), (0.75, 2.55), (1.25, 3.8), (1.85, 5.3), (2.5, 7.0)]
    lamps = []
    for k, (x, y) in enumerate(path):
        s_ = 1.6 if k == 0 else 1.4
        lotus_lamp(f"Lotus{k}", (x + rng.normal(0, 0.05), y, 0.0), scale=s_, rot_z=rng.uniform(0, 6.28), petal_m=petal_m, leaf_m=leaf_m,
                   light_w=1.6 * s_ * s_)
        lamps.append(Vector((x, y, 0.0)))
    # 魂火：跟在灯后，拖着往回的细尾
    soul = mat_soul_fire("Soul")
    for k in range(7):
        i = rng.integers(0, len(lamps) - 1)
        t = rng.uniform(0.2, 0.8)
        p = lamps[i].lerp(lamps[i + 1], t) + Vector((rng.normal(0, 0.25), rng.normal(0, 0.1), rng.uniform(0.18, 0.45)))
        r = rng.uniform(0.022, 0.035)
        make_obj(f"Soul{k}", K.ico_cloud([(0, 0, 0)], [r], 2), soul, loc=tuple(p), scale=(1.0, 1.0, 1.25), index=4)
        K.point_light(f"SoulL{k}", tuple(p), 0.4, radius=0.02, color=(0.45, 0.95, 0.85))
        back = (lamps[i] - lamps[i + 1]).normalized()
        pts = [tuple(p + back * (0.5 * s) + Vector((0.06 * math.sin(s * 9 + k), 0, -0.05 * s + 0.03 * math.sin(s * 7)))) for s in
               np.linspace(0, 1, 30)]
        make_obj(f"SoulTail{k}", K.ribbon_uv(pts, r * 1.6, width_fn=lambda t: 1 - 0.85 * t),
                 K.mat_wind(f"SoulTailM{k}", strength=1.6, seed=k * 1.7, color=(0.45, 0.95, 0.85)), index=4)
    # 远岸的芦苇
    reed = mat_bark("Reed", color=(0.04, 0.045, 0.03), crack=0.0)
    for k in range(60):
        x = rng.uniform(2.0, 5.5)
        y = rng.uniform(6.5, 8.5)
        h = rng.uniform(0.6, 1.3)
        lean = rng.normal(0.08, 0.06)
        make_obj(f"Reed{k}", K.tube_uv([(x, y, -0.05), (x + lean * 0.5, y, h * 0.6), (x + lean, y, h)], 0.008, sides=5,
                                       radius_fn=lambda t: 1 - 0.7 * t), reed, index=1)
    # 月光从很高的后上方来：水面里看不到它的倒影（只倒映河灯）
    K.area_light("Moon", (3.0, 9.0, 11.0), (0.5, 3.0, 0.0), 900.0, 3.0, color=(0.60, 0.72, 1.0))
    K.camera((-0.48, -1.18, 0.50), (0.55, 2.4, 0.05), lens=34.0, fstop=4.0, focus=1.45)
    return {"light": "cold"}


@background("yinhun")
def bg_yinhun(P_, h, w, rng, k):
    P_.fill_grad("#0A0F1A", "#121C2C", cloud=0.12)
    K.bg_glow(P_, 0.62, 0.32, 0.40, 0.30, "#3E5680", 0.28)
    K.bg_moon(P_, 0.80, 0.18, 0.040, rng, k, color="#E6ECF4", halo="#7890B6", a=0.55, halo_a=0.30)
    K.bg_mountains(P_, [(0.38, [(0.15, 0.10, 0.14, 0.12), (0.55, 0.06, 0.16, 0.14), (0.88, 0.12, 0.12, 0.14)], "#162030", 0.8, 0.08, 5.0,
                         "#6E8CAA")], rng, k)
    K.bg_mist(P_, 0.40, 0.04, "#8FB0D0", 0.18, rng, k)
    K.bg_ink(P_, [(0.02, 0.06, 0.26, 0.18, 0.2)], 0.45)


# ====================================================================== 静心


def mat_smoke(name, color=(0.70, 0.72, 0.78), alpha=0.5, seed=0.0):
    """一缕细烟（ribbon，UV.x 沿长）：灰白半透明，下段实、往上散开淡出，沿长有细的明暗。"""
    M = K.Mat(name)
    m = M.math
    uv = M.coord("UV")
    sep = M.n("ShaderNodeSeparateXYZ")
    M.l(uv, sep.inputs[0])
    u, v = sep.outputs["X"], sep.outputs["Y"]
    across = m("POWER", m("SINE", m("MULTIPLY", v, math.pi)), 1.5)
    fade = m("MULTIPLY", M.maprange(u, 0.0, 0.06), M.maprange(u, 1.0, 0.35))
    mp = M.n("ShaderNodeMapping")
    M.l(uv, mp.inputs["Vector"])
    mp.inputs["Scale"].default_value = (6.0, 2.0, 1.0)
    nz = M.noise(mp.outputs["Vector"], scale=1.0, detail=5.0, rough=0.6, w=seed)
    a_ = m("MULTIPLY", m("MULTIPLY", across, fade), m("ADD", m("MULTIPLY", M.maprange(nz.outputs["Fac"], 0.35, 0.65), 0.7), 0.3))
    a_ = m("MULTIPLY", a_, alpha, clamp=True)
    bsdf = M.principled(Base_Color=(*color, 1.0), Roughness=1.0, Specular_IOR_Level=0.0)
    tr = M.n("ShaderNodeBsdfTransparent")
    mx = M.n("ShaderNodeMixShader")
    M.l(a_, mx.inputs[0])
    M.l(tr.outputs[0], mx.inputs[1])
    M.l(bsdf.outputs[0], mx.inputs[2])
    return M.surface(mx.outputs[0])


@scene("jingxin", name="静心", samples=128, grade=dict(COLD_GRADE, exposure=1.04, bloom=0.34))
def build_jingxin(draft):
    """静心：山寺的大钟静静挂在梁下（不结霜，青铜老锈、铭文鎏金），钟旁一盏青铜灯台，灯焰又细又长、笔直不动，
    一缕青烟直直往上；地上薄雾。冷的夜色里只有这一点暖。"""
    from mathutils import Vector  # noqa: PLC0415

    K.set_world(lin("#0A1222"), 1.0)
    rng = np.random.default_rng(19)
    K.temple_bell(frost=False)
    iron = K.mat_iron("Iron")
    beam_z = 2.13
    make_obj("Shackle", K.torus_build(0.125, 0.026, 64, 14), iron, loc=(0, 0, 1.765),
             rot=(math.radians(90), 0, math.radians(18) + math.radians(90)), index=2)
    make_obj("Strap", K.box_build(0.10, 0.07, 0.12), iron, loc=(0, 0.0, beam_z - 0.235), index=2, bevel=(0.006, 2), smooth=False)
    make_obj("Beam", K.box_build(7.0, 0.36, 0.40), K.mat_wood("Wood"), loc=(0, 0.0, beam_z), index=2, bevel=(0.02, 3), smooth=False)
    floor_z = -0.55
    make_obj("Floor", K.box_build(14.0, 14.0, 0.02), mat_paving("Floor"), loc=(0, 4.0, floor_z - 0.01), index=0, smooth=False)
    # 灯台：钟的右前方，灯焰细长
    lamp, fz = bronze_oil_lamp("Lamp", loc=(1.05, -1.05, floor_z), scale=2.6, flame=1.2, flame_h=0.11)
    upd()
    tip = Vector(lamp.matrix_world @ (fz + Vector((0, 0, 0.11))))
    smoke = [tuple(tip + Vector((0.0015 * math.sin(t * 9), 0.0, 1.45 * t + 0.02))) for t in np.linspace(0, 1, 60)]
    make_obj("Smoke", K.ribbon_uv(smoke, 0.012, width_fn=lambda t: 0.5 + 2.5 * t ** 2), mat_smoke("SmokeM", alpha=0.55), index=3)
    # 薄雾：地上一层（淡的体积）
    mist = K.Mat("Mist")
    vol = mist.n("ShaderNodeVolumePrincipled", Color=(0.55, 0.65, 0.85, 1.0), Density=0.22)
    mist.l(vol.outputs[0], mist.out.inputs["Volume"])
    make_obj("MistVol", K.box_build(9.0, 9.0, 0.32), mist.m, loc=(0, 2.0, floor_z + 0.12), index=0, smooth=False)
    K.area_light("Moon", (-3.0, 3.2, 3.2), (0, 0, 0.9), 520.0, 1.6, color=(0.70, 0.80, 1.0))
    K.area_light("MoonFill", (3.2, 2.6, 1.6), (0, 0, 0.7), 120.0, 1.4, color=(0.55, 0.70, 1.0))
    K.area_light("Front", (-1.8, -4.0, 2.4), (0, 0, 0.8), 70.0, 3.0, color=(0.62, 0.72, 1.0))
    K.point_light("LampGlow", tuple(tip + Vector((0, -0.05, -0.04))), 45.0, radius=0.03, color=(1.0, 0.62, 0.30))
    K.camera((0.95, -5.1, 0.55), (0.30, 0.0, 0.62), lens=42.0, fstop=4.0, focus=4.2)
    _ = rng
    return {"light": "cold"}


@background("jingxin")
def bg_jingxin(P_, h, w, rng, k):
    P_.fill_grad("#0B1222", "#142034", cloud=0.12)
    K.bg_glow(P_, 0.40, 0.45, 0.46, 0.40, "#4C6890", 0.28)
    K.bg_glow(P_, 0.72, 0.55, 0.14, 0.18, "#8A5A2C", 0.18)
    K.bg_mountains(P_, [(0.74, [(0.10, 0.12, 0.12, 0.10), (0.40, 0.08, 0.14, 0.12), (0.78, 0.14, 0.14, 0.14)], "#1B2840", 0.8, 0.08, 5.0)],
                   rng, k)
    K.bg_mist(P_, 0.78, 0.05, "#8FB0D0", 0.16, rng, k)
    K.bg_ink(P_, [(0.98, 0.08, 0.22, 0.16, -0.4), (0.02, 0.96, 0.26, 0.18, 0.2)], 0.45)


# ====================================================================== 灯芯


def scissors_half(name, mat, *, mirror=False, open_deg=18.0, parent=None, index=1):
    """剪刀的一半（沿 +X：刃在 +X，轴钉在原点，柄和圈在 -X）：扁的刀身（一边开刃）、细柄、一个椭圆指圈。
    mirror=True 给另一半（刃朝另一边）。open_deg：张开的半角。"""
    s = -1.0 if mirror else 1.0
    T = 0.0018

    def blade(bm):
        import bmesh  # noqa: PLC0415

        prof = []
        for t in np.linspace(0, 1, 28):  # 刀身：从轴钉往刀尖，宽度收尖；一边直（刃）、一边弧
            x = 0.002 + 0.060 * t
            w = 0.0075 * (1 - t ** 1.6) + 0.0006
            prof.append((x, w))
        top = [bm.verts.new((x, s * 0.0, T / 2)) for x, w in prof] + [bm.verts.new((x, s * w, T / 2)) for x, w in reversed(prof)]
        bot = [bm.verts.new((v.co.x, v.co.y, -T / 2)) for v in top]
        bm.faces.new(top)
        bm.faces.new(list(reversed(bot)))
        n = len(top)
        for i in range(n):
            j = (i + 1) % n
            bm.faces.new((top[i], top[j], bot[j], bot[i]))
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)

    bpy = K._bpy()
    root = bpy.data.objects.new(name, None)
    K.link(root, parent)
    root.rotation_euler = (0, 0, math.radians(open_deg) * s)
    make_obj(f"{name}_Blade", blade, mat, parent=root, index=index, smooth=False, bevel=(0.0004, 1))
    stem = [(0.0, 0.0, 0.0), (-0.020, -s * 0.004, 0.0), (-0.038, -s * 0.010, 0.0)]
    make_obj(f"{name}_Stem", K.tube_uv(stem, 0.0022, sides=8, flat=0.6), mat, parent=root, index=index)
    ring = make_obj(f"{name}_Ring", K.torus_build(0.012, 0.0022, 40, 8), mat, parent=root, loc=(-0.050, -s * 0.013, 0.0), index=index)
    ring.scale = (1.0, 0.75, 1.0)
    return root


def mat_flame_volume(name, h, r, strength=40.0):
    """一朵烛火（体积自发光，物体坐标：火根在原点、往 +Z 高 h、最宽半径 r）：泪滴形，根部一圈蓝，芯子白黄，
    外焰橙红、边缘柔，越往上越窄、越淡。"""
    M = K.Mat(name)
    m = M.math
    oc = M.coord("Object")
    sep = M.n("ShaderNodeSeparateXYZ")
    M.l(oc, sep.inputs[0])
    x, y, z = sep.outputs["X"], sep.outputs["Y"], sep.outputs["Z"]
    t = m("DIVIDE", z, h)
    tc = m("MINIMUM", m("MAXIMUM", t, 0.0), 1.0)
    prof = m("MULTIPLY", m("POWER", m("SINE", m("MULTIPLY", m("POWER", tc, 0.55), math.pi)), 0.85), r)  # 泪滴形的半径
    rr = m("SQRT", m("ADD", m("MULTIPLY", x, x), m("MULTIPLY", y, y)))
    inside = m("SUBTRACT", 1.0, m("DIVIDE", rr, m("MAXIMUM", prof, 1e-5)), clamp=True)
    inside = m("MULTIPLY", inside, m("MULTIPLY", m("GREATER_THAN", t, 0.0), m("LESS_THAN", t, 1.0)))
    core = m("POWER", inside, 2.2)
    f = m("ADD", m("MULTIPLY", m("POWER", inside, 1.1), 0.55), m("MULTIPLY", core, 0.9))
    f = m("MULTIPLY", f, m("SUBTRACT", 1.0, m("POWER", tc, 2.5)), clamp=True)
    col, _ = M.ramp(f, [(0.0, (0.55, 0.08, 0.01)), (0.25, (1.0, 0.36, 0.06)), (0.55, (1.0, 0.70, 0.25)), (0.85, (1.0, 0.93, 0.70)),
                        (1.0, (1.0, 0.98, 0.92))])
    blue = m("MULTIPLY", M.maprange(t, 0.18, 0.02), m("MULTIPLY", M.maprange(inside, 0.0, 0.5), M.maprange(inside, 1.0, 0.6)))
    col = M.mix(blue, col, (0.25, 0.45, 1.0, 1.0))
    emi = M.n("ShaderNodeEmission")
    M.l(col, emi.inputs["Color"])
    M.l(m("MULTIPLY", m("POWER", f, 1.3), strength), emi.inputs["Strength"])
    M.l(emi.outputs[0], M.out.inputs["Volume"])
    return M.m


@scene("dengxin", name="灯芯", samples=128, grade=dict(WARM_GRADE, exposure=0.98, bloom=0.42))
def build_dengxin(draft):
    """灯芯：一盏青铜油灯盏的特写，一把小铁剪刀从右边伸过来，张开的刃口正剪在灯芯上；灯焰随之一跳，
    又高又亮，迸出几粒火星。暗处只有这一团火光。"""
    from mathutils import Vector  # noqa: PLC0415

    K.set_world(lin("#0A0806"), 1.0)
    rng = np.random.default_rng(23)
    lamp, fz = bronze_oil_lamp("Lamp", loc=(0, 0, -0.30), scale=1.0, flame=0.0)
    upd()
    tip = Vector(lamp.matrix_world @ fz)
    # 灯焰：体积火（又高又亮，剪过以后“一跳”），装在一个比它大一点的包围盒里
    fh, fr = 0.060, 0.0115
    from mathutils import Matrix  # noqa: PLC0415

    fl = make_obj("Flame", K.box_build(fr * 3, fr * 3, fh * 1.05), mat_flame_volume("FlameV", fh, fr, strength=1600.0), loc=tuple(tip),
                  index=3, smooth=False)
    fl.data.transform(Matrix.Translation((0, 0, fh * 0.52)))  # 物体原点在火根
    K.point_light("FlameLight", tuple(tip + Vector((0, 0, 0.02))), 6.0, radius=0.006, color=(1.0, 0.62, 0.30))
    # 剪刀：刃口夹着灯芯上端，柄伸向右下
    steel = P.mat_steel("Scissor", tint=(0.42, 0.40, 0.38), rough=0.22, pattern=0.2, dark=0.35)
    sc = K._bpy().data.objects.new("Scissors", None)
    K.link(sc)
    sc.location = tuple(tip + Vector((0.040, -0.004, -0.002)))
    sc.rotation_euler = (math.radians(90), math.radians(14), math.radians(172))  # 刃面朝镜头，刃尖朝左夹住灯芯
    sc.scale = (1.3, 1.3, 1.3)
    scissors_half("ScA", steel, parent=sc, open_deg=16.0)
    scissors_half("ScB", steel, mirror=True, parent=sc, open_deg=16.0)
    make_obj("Pivot", K.lathe_uv([(0.0, -0.002), (0.0028, -0.002), (0.0028, 0.002), (0.0, 0.0024)], segments=16), K.mat_gold("Rivet"),
             parent=sc, index=1)
    # 火星
    ember = K.mat_ember("Ember")
    for k in range(12):
        d = Vector((rng.normal(0, 0.6), rng.normal(0, 0.08), rng.uniform(0.6, 1.2))).normalized()
        p = tip + Vector((0, 0, 0.03)) + d * rng.uniform(0.02, 0.07)
        r0 = rng.uniform(0.00025, 0.00045)
        ob = make_obj(f"Spark{k}", K.lathe_uv([(0.0, -1.0), (0.6, -0.6), (1.0, 0.0), (0.6, 0.6), (0.0, 1.0)], segments=8), ember,
                      loc=tuple(p), scale=(r0, r0, r0 * rng.uniform(3, 6)), index=3)
        ob.rotation_mode = "QUATERNION"
        ob.rotation_quaternion = d.to_track_quat("Z", "Y")
    K.point_light("Burst", tuple(tip + Vector((0, -0.01, 0.04))), 6.0, radius=0.015, color=(1.0, 0.66, 0.32))
    K.area_light("Rim", (-0.6, 0.6, 0.4), tuple(tip), 8.0, 0.4, color=(0.55, 0.65, 1.0))
    K.area_light("Fill", tuple(tip + Vector((0.25, -0.45, 0.05))), tuple(tip + Vector((0, 0, -0.03))), 2.5, 0.5, color=(1.0, 0.78, 0.55))
    K.area_light("Under", tuple(tip + Vector((-0.2, -0.3, -0.10))), tuple(tip + Vector((0, 0, -0.04))), 0.8, 0.4, color=(0.60, 0.68, 1.0))
    K.camera(tuple(tip + Vector((-0.05, -0.40, 0.17))), tuple(tip + Vector((0.020, 0.0, -0.012))), lens=50.0, fstop=7.0, focus=0.43)
    return {"light": "warm"}


@background("dengxin")
def bg_dengxin(P_, h, w, rng, k):
    P_.fill_grad("#0E0B0A", "#0A0808", cloud=0.12)
    K.bg_glow(P_, 0.48, 0.45, 0.42, 0.42, "#6A3A16", 0.32)
    K.bg_glow(P_, 0.48, 0.40, 0.18, 0.20, "#C27630", 0.22)
    K.bg_ink(P_, [(0.02, 0.06, 0.30, 0.22, 0.2), (0.98, 0.94, 0.30, 0.22, -0.3), (0.02, 0.96, 0.26, 0.18, -0.2)], 0.5)


# ====================================================================== 迅锋


def mat_slit(name, color=(0.85, 0.94, 1.0), strength=14.0):
    """空气被划开的口子（ribbon，UV.x 沿长、UV.y 横跨）：中线一道极细的白光，两边很快暗下去，两头收尖。"""
    M = K.Mat(name)
    m = M.math
    uv = M.coord("UV")
    sep = M.n("ShaderNodeSeparateXYZ")
    M.l(uv, sep.inputs[0])
    u, v = sep.outputs["X"], sep.outputs["Y"]
    lens_ = m("POWER", m("SINE", m("MULTIPLY", u, math.pi)), 0.6)  # 两头收尖
    d = m("DIVIDE", m("ABSOLUTE", m("SUBTRACT", v, 0.5)), m("MAXIMUM", m("MULTIPLY", lens_, 0.5), 0.001))
    core = m("EXPONENT", m("MULTIPLY", m("POWER", m("DIVIDE", d, 0.18), 2.0), -1.0))
    halo = m("MULTIPLY", m("EXPONENT", m("MULTIPLY", d, -3.0)), 0.25)
    a_ = m("MULTIPLY", m("ADD", core, halo), m("SUBTRACT", 1.0, m("GREATER_THAN", d, 1.0)))
    emi = M.n("ShaderNodeEmission", Color=(*color, 1.0))
    M.l(m("MULTIPLY", a_, strength), emi.inputs["Strength"])
    tr = M.n("ShaderNodeBsdfTransparent")
    add = M.n("ShaderNodeAddShader")
    M.l(tr.outputs[0], add.inputs[0])
    M.l(emi.outputs[0], add.inputs[1])
    return M.surface(add.outputs[0])


@scene("xunfeng", name="迅锋", samples=128, grade=dict(COLD_GRADE, bloom=0.38))
def build_xunfeng(draft):
    """迅锋：一道剑锋从左往右飞过画面（只露前半截剑身和剑尖），身后拖着一串越来越淡的残影；剑过之处，空气被划开
    一道又细又长的白口子，口子两边卷起几缕气浪。冷月光，剑刃一线亮。"""
    from mathutils import Matrix, Vector  # noqa: PLC0415

    import card_weapons as CW

    sky_gradient(lin("#05080F"), lin("#33496C"), 0.9, ground=lin("#04060A"))
    rng = np.random.default_rng(31)
    S = ScreenCam(lens=40.0)
    a0, a1 = S(-0.05, 0.62, 1.6), S(1.0, 0.44, 1.5)  # 剑飞的方向：左下 → 右上一点
    d = (a1 - a0).normalized()
    q = d.to_track_quat("X", "Z")
    tip = S(0.86, 0.465, 1.52)
    steel = P.mat_steel("Steel", tint=(0.84, 0.87, 0.92), rough=0.10, edge_glow=((0.80, 0.92, 1.0), 1.8))
    P.sword("Sword", steel=steel, loc=tuple(tip - d * 0.74), rot=q.to_euler(), index=1, tassel=False)
    ghost = CW.mat_ghost_blade("Ghost")
    gb = CW.ghost_sword_build(L=0.74, W=0.034, T=0.0075)
    for k in range(7):
        back = 0.16 * (k + 1) ** 1.15
        ob = make_obj(f"After{k}", gb, ghost, smooth=False, loc=tuple(tip - d * (0.74 + back) + Vector((0, 0.02 * k, 0))), index=2)
        ob.rotation_mode = "QUATERNION"
        ob.rotation_quaternion = q @ Matrix.Rotation(0.0, 3, "X").to_quaternion()
        ob["fade"] = float(0.75 * (1 - k / 7) ** 1.4)
    # 划开的口子：沿剑路一道长长的亮缝（剑尖后面最亮），两边几缕气浪
    path = [tuple(a0.lerp(tip, t) + Vector((0, 0.03, 0))) for t in np.linspace(0, 1, 80)]
    make_obj("Slit", K.ribbon_uv(path, 0.09, ups=[(0, 0, 1)] * len(path)), mat_slit("SlitM"), index=3)
    for j in range(6):
        sg = 1 if j % 2 else -1
        off = Vector((0, 0.05, sg * rng.uniform(0.03, 0.08)))
        pts = [tuple(a0.lerp(tip, t) + off * (0.4 + 1.6 * (1 - t)) + Vector((0, 0, sg * 0.05 * (1 - t) ** 2))) for t in
               np.linspace(rng.uniform(0.0, 0.3), rng.uniform(0.75, 0.95), 60)]
        make_obj(f"Wake{j}", K.ribbon_uv(pts, rng.uniform(0.02, 0.05), ups=[(0, 0, 1)] * len(pts)),
                 K.mat_wind(f"WakeM{j}", strength=rng.uniform(0.8, 1.4), seed=j * 1.9, color=(0.72, 0.86, 1.0)), index=3)
    area_oriented = CW.area_oriented
    area_oriented("Strip", tuple(tip + Vector((0.0, -1.0, 0.9))), tuple(tip), tuple(d), 26.0, 2.4, 0.05, color=(0.82, 0.90, 1.0))
    K.area_light("Moon", (-1.4, 2.0, 1.6), tuple(tip), 140.0, 1.2, color=(0.66, 0.78, 1.0))
    S.place(lens=40.0, fstop=5.6, focus=1.52)
    return {"light": "cold"}


@background("xunfeng")
def bg_xunfeng(P_, h, w, rng, k):
    P_.fill_grad("#0C1322", "#111B2E", cloud=0.12)
    K.bg_glow(P_, 0.55, 0.50, 0.50, 0.30, "#405A80", 0.28)
    bg_clouds(P_, rng, k, [(0.30, 0.035, 0.05, 0.62), (0.70, 0.03, 0.35, 0.98)], "#5B7194", 0.20)
    K.bg_mountains(P_, [(0.92, [(0.12, 0.10, 0.12, 0.10), (0.40, 0.06, 0.12, 0.14), (0.75, 0.12, 0.14, 0.12)], "#17233A", 0.85, 0.08, 5.0)],
                   rng, k)
    K.bg_ink(P_, [(0.02, 0.06, 0.26, 0.18, 0.2), (0.98, 0.08, 0.24, 0.18, -0.4)], 0.45)


# ====================================================================== 剑意


def sleeve(name, wrist, d, *, r=0.040, L=0.20, mat=None, index=1, flare=1.5):
    """袖口：沿 d（从腕往肘）的一段布筒，腕口略收、往后放宽，口沿一道深色镶边。"""
    from mathutils import Vector  # noqa: PLC0415

    mat = mat or K.mat_cloth(f"{name}_Cloth", (0.045, 0.055, 0.085), weave=900.0)
    d = Vector(d).normalized()
    pts = [tuple(Vector(wrist) + d * (L * t)) for t in np.linspace(0, 1, 20)]
    make_obj(name, K.tube_uv(pts, r, sides=40, radius_fn=lambda t: 1.0 + (flare - 1.0) * t ** 1.5, caps=False), mat, index=index)
    make_obj(f"{name}_Hem", K.tube_uv([tuple(Vector(wrist) + d * (L * t)) for t in np.linspace(0, 0.08, 4)], r * 1.03, sides=40,
                                      caps=False), K.mat_cloth(f"{name}_HemM", (0.012, 0.012, 0.016), weave=900.0), index=index)


def scabbard(name, L=0.70, W=0.050, T=0.026, *, lac=None, gold=None, parent=None, index=1):
    """剑鞘（沿 +X，鞘口在 x=0）：扁椭圆截面的黑漆木鞘，鞘口、鞘中、鞘尾三道鎏金铜箍，尾端收圆。"""
    lac = lac or K.mat_lacquer(f"{name}_Lac", color=(0.020, 0.012, 0.010))
    gold = gold or K.mat_gold(f"{name}_Gold", worn=0.5)
    pts = [(L * t, 0.0, 0.0) for t in np.linspace(0, 1, 60)]
    make_obj(name, K.tube_uv(pts, W / 2, sides=32, flat=T / W, radius_fn=lambda t: (1 - 0.12 * t) * (1 - 0.6 * max(0.0, (t - 0.96) / 0.04) ** 2)),
             lac, parent=parent, index=index, rot=(math.pi / 2, 0, 0))
    for x0, x1 in ((0.0, 0.045), (0.30, 0.32), (L - 0.07, L)):
        k0 = 1 - 0.12 * x0 / L
        make_obj(f"{name}_Band{x0:.2f}", K.tube_uv([(x0, 0, 0), (x1, 0, 0)], W / 2 * k0 * 1.08, sides=32, flat=T / W), gold,
                 parent=parent, index=index, rot=(math.pi / 2, 0, 0))


@scene("jianyi", name="剑意", samples=128, grade=dict(COLD_GRADE, bloom=0.40))
def build_jianyi(draft):
    """剑意：一只手握着剑柄（手背朝镜头、袖口压在腕上），剑还在黑漆鞘里，只拔出一指宽；鞘口那道缝里已经凝出一道白光，
    几缕光丝从缝里迸出来。剑斜着从左下指向右上，冷月光打轮廓。"""
    from mathutils import Matrix, Vector  # noqa: PLC0415

    sky_gradient(lin("#05080F"), lin("#33496C"), 0.9, ground=lin("#04060A"))
    rng = np.random.default_rng(13)
    S = ScreenCam(lens=45.0)
    g0, g1 = S(0.36, 0.62, 0.95), S(0.98, 0.20, 1.10)  # 剑格在左中，鞘尾出画右上
    d = (g1 - g0).normalized()
    zh = Vector((0.0, -0.4, 1.0))
    q = frame_quat(d, zh)
    steel = P.mat_steel("Steel", tint=(0.86, 0.89, 0.94), rough=0.10, edge_glow=((0.85, 0.95, 1.0), 4.0))
    root = P.sword("Sword", steel=steel, loc=tuple(g0), rot=q.to_euler(), index=1, tassel=True)
    gap = 0.030  # 拔出的一指宽
    sc_root = K._bpy().data.objects.new("ScabbardRoot", None)
    K.link(sc_root, root)
    sc_root.location = (gap, 0, 0)
    scabbard("Scabbard", L=0.72, parent=sc_root)
    # 鞘口的光：一圈很亮的光环 + 几缕往外迸的光丝 + 点光
    R_ = Matrix(((1, 0, 0), (0, 1, 0), (0, 0, 1)))
    glow = P.mat_emit("GapGlow", (0.85, 0.94, 1.0), 9.0)
    make_obj("GapRing", K.tube_uv([(gap - 0.002, 0, 0), (gap + 0.001, 0, 0)], 0.027, sides=32, flat=0.52, caps=False), glow, parent=root,
             index=3, rot=(math.pi / 2, 0, 0))
    for j in range(9):
        a = 2 * math.pi * j / 9 + rng.normal(0, 0.2)
        dirv = Vector((rng.uniform(-0.2, 0.25), math.cos(a), math.sin(a) * 0.6)).normalized()
        L = rng.uniform(0.06, 0.16)
        pts = [tuple(Vector((gap, 0, 0)) + dirv * (0.02 + L * t) + Vector((0.01 * t, 0, 0))) for t in np.linspace(0, 1, 20)]
        make_obj(f"Ray{j}", K.ribbon_uv(pts, rng.uniform(0.004, 0.010), ups=[(1, 0, 0)] * len(pts)),
                 K.mat_wind(f"RayM{j}", strength=rng.uniform(1.2, 2.2), seed=j * 1.3, color=(0.80, 0.92, 1.0)), parent=root, index=3)
    K.point_light("GapLight", tuple(root.matrix_world @ Vector((gap, -0.03, 0.0))) if False else tuple(g0 + d * gap + Vector((0, -0.04, 0))),
                  1.2, radius=0.01, color=(0.80, 0.92, 1.0))
    # 握剑的手：拳握在柄中段，拇指朝剑格；手背朝镜头
    skin = P.mat_skin("Skin", color=(0.56, 0.40, 0.31))
    grip_c = g0 - d * 0.085
    hx = d  # 手的 +X（拇指一侧）顺着剑
    hz = (Vector((0, 0, 1)) - d * d.z).normalized()  # 手指朝上绕过剑柄
    hz = (hz + Vector((0, -0.6, 0))).normalized()
    hq = frame_quat(hx, hz)
    Rm = hq.to_matrix()
    wrist = grip_c - Rm @ Vector((0.0, -0.024, 0.080))
    P.hand("Hand", skin, P.HAND_FIST, loc=tuple(wrist), rot=hq.to_euler())
    sleeve("Sleeve", tuple(wrist + Rm @ Vector((0, 0.0, 0.01))), tuple(-(Rm @ Vector((0, 0, 1)))), r=0.042, L=0.25)
    K.area_light("Moon", (-1.2, 1.6, 1.6), tuple(g0), 90.0, 1.2, color=(0.66, 0.78, 1.0))
    K.area_light("Key", (-0.8, -1.2, 0.9), tuple(g0), 25.0, 1.0, color=(0.78, 0.84, 1.0))
    K.area_light("Warm", (1.0, -0.8, -0.4), tuple(g0), 4.0, 0.8, color=(1.0, 0.74, 0.50))
    S.place(lens=45.0, fstop=4.0, focus=0.95)
    _ = R_
    return {"light": "cold"}


@background("jianyi")
def bg_jianyi(P_, h, w, rng, k):
    P_.fill_grad("#0C1322", "#111B2E", cloud=0.12)
    K.bg_glow(P_, 0.48, 0.45, 0.45, 0.40, "#405A80", 0.30)
    K.bg_glow(P_, 0.46, 0.48, 0.12, 0.14, "#B8CCE6", 0.18)
    bg_clouds(P_, rng, k, [(0.25, 0.03, 0.40, 0.98), (0.80, 0.03, 0.02, 0.60)], "#5B7194", 0.18)
    K.bg_ink(P_, [(0.02, 0.06, 0.26, 0.18, 0.2), (0.98, 0.96, 0.30, 0.20, -0.2)], 0.45)


# ====================================================================== 聚魂


def mat_glow_volume(name, R, color=(1.0, 0.72, 0.40), strength=60.0):
    """一团柔光（体积自发光，物体坐标原点为心）：越近心越亮，到半径 R 淡到没有。"""
    M = K.Mat(name)
    m = M.math
    oc = M.coord("Object")
    ln = M.n("ShaderNodeVectorMath", _operation="LENGTH")
    M.l(oc, ln.inputs[0])
    f = m("POWER", m("SUBTRACT", 1.0, m("DIVIDE", ln.outputs["Value"], R), clamp=True), 2.4)
    emi = M.n("ShaderNodeEmission", Color=(*color, 1.0))
    M.l(m("MULTIPLY", f, strength), emi.inputs["Strength"])
    M.l(emi.outputs[0], M.out.inputs["Volume"])
    return M.m


@scene("juhun", name="聚魂", samples=128, grade=dict(WARM_GRADE, exposure=1.0, bloom=0.44))
def build_juhun(draft):
    """聚魂：一只摊开的手（掌心朝上，袖口在右下），掌心上方一团暖光；点点魂火从四面八方沿着弧线旋进来，
    越近越暖、越亮，拖着细尾。手被那团光从上面照亮。"""
    from mathutils import Vector  # noqa: PLC0415

    K.set_world(lin("#07080E"), 1.0)
    rng = np.random.default_rng(41)
    skin = P.mat_skin("Skin", color=(0.54, 0.38, 0.29))
    pose = {"index": (-8, 14, 12, 6), "middle": (-1, 14, 12, 6), "ring": (6, 16, 13, 7), "pinky": (14, 18, 14, 8), "thumb": (50, 25, 12, 10)}
    hx = Vector((0.25, 0.97, 0.0)).normalized()  # 拇指一侧朝里（远离镜头）
    hz = Vector((-0.92, 0.20, 0.18)).normalized()  # 手指朝左
    q = frame_quat(hx, hz)
    wrist = Vector((0.10, -0.02, -0.02))
    P.hand("Hand", skin, pose, loc=tuple(wrist), rot=q.to_euler())
    Rm = q.to_matrix()
    sleeve("Sleeve", tuple(wrist + Rm @ Vector((0, 0, 0.012))), tuple(-(Rm @ Vector((0, 0, 1)))), r=0.044, L=0.30, flare=1.7)
    palm = wrist + Rm @ Vector((0.0, -0.05, 0.06))
    orb_c = palm + Vector((0, 0, 0.080))
    make_obj("Orb", K.ico_cloud([(0, 0, 0)], [0.010], 3), P.mat_emit("OrbCore", (1.0, 0.86, 0.60), 40.0), loc=tuple(orb_c), index=4)
    make_obj("Glow", K.ico_cloud([(0, 0, 0)], [0.050], 3), mat_glow_volume("GlowV", 0.050, strength=90.0), loc=tuple(orb_c), index=4)
    K.point_light("OrbLight", tuple(orb_c), 4.0, radius=0.02, color=(1.0, 0.72, 0.40))
    # 魂火：起点散在一个大球面上（上、左右、前后都有），绕竖轴旋着收进光团；远处青白、近处暖金
    n = 22
    for k in range(n):
        u = (k + 0.5) / n
        el = math.asin(2 * u - 1) * 0.8 + 0.15
        az = k * 2.399963  # 黄金角，散得匀
        r0 = rng.uniform(0.22, 0.36)
        start = orb_c + Vector((r0 * math.cos(az) * math.cos(el), r0 * math.sin(az) * math.cos(el) * 0.8, r0 * math.sin(el)))
        swirl = rng.uniform(0.9, 1.6) * (1 if k % 3 else -1)
        pts = []
        for t in np.linspace(0, 1, 60):
            v = start - orb_c
            rr = v.length * (1 - t) ** 1.2 + 0.012
            a_ = math.atan2(v.y, v.x) + swirl * t
            h_ = v.z * (1 - t) ** 1.1
            rho = math.hypot(v.x, v.y) / max(v.length, 1e-6) * rr
            pts.append(tuple(orb_c + Vector((rho * math.cos(a_), rho * math.sin(a_), h_ * rr / max(v.length * (1 - t) + 0.012, 1e-6)))))
        head_t = rng.uniform(0.30, 0.85)
        n_ = int(len(pts) * head_t)
        trail = pts[max(0, n_ - 22):n_]
        if len(trail) < 4:
            continue
        col = (0.45 + 0.55 * head_t, 0.92 - 0.18 * head_t, 0.88 - 0.50 * head_t)
        make_obj(f"Wisp{k}", K.ribbon_uv(list(reversed(trail)), rng.uniform(0.005, 0.009), width_fn=lambda t: 1 - 0.9 * t),
                 K.mat_wind(f"WispM{k}", strength=2.4, seed=k * 1.1, color=col), index=4)
        make_obj(f"Spirit{k}", K.ico_cloud([(0, 0, 0)], [rng.uniform(0.0035, 0.006)], 2), P.mat_emit(f"SpiritM{k}", col, 20.0),
                 loc=trail[-1], index=4)
    K.area_light("Rim", (-0.6, 0.8, 0.5), tuple(palm), 8.0, 0.6, color=(0.55, 0.68, 1.0))
    K.area_light("Fill", (0.4, -0.8, 0.3), tuple(palm), 1.5, 0.8, color=(0.62, 0.70, 0.95))
    K.camera(tuple(palm + Vector((0.05, -0.55, 0.30))), tuple(palm + Vector((0.0, 0.0, 0.07))), lens=50.0, fstop=4.0, focus=0.62)
    return {"light": "warm"}


def mat_soul_fire_warm(name):
    return mat_soul_fire(name, color=(1.0, 0.70, 0.36), strength=3.0)


@background("juhun")
def bg_juhun(P_, h, w, rng, k):
    P_.fill_grad("#0A0B12", "#0C0C12", cloud=0.12)
    K.bg_glow(P_, 0.50, 0.40, 0.45, 0.40, "#5A3A1C", 0.26)
    K.bg_glow(P_, 0.50, 0.40, 0.45, 0.40, "#2E5A60", 0.10)
    K.bg_ink(P_, [(0.02, 0.06, 0.26, 0.18, 0.2), (0.98, 0.08, 0.24, 0.18, -0.4), (0.02, 0.96, 0.26, 0.18, -0.2)], 0.45)


# ====================================================================== 折纸


def finger_tip(pose, finger="index", mirror=False):
    """手的骨架里某根手指指尖的位置（手的局部坐标）。"""
    order = ["index", "middle", "ring", "pinky"]
    segs = P.hand_points(pose, mirror=mirror)
    if finger == "thumb":
        return segs[4 * 4 + 2][1]  # 拇指三节在四根手指（各 3 节 + 掌骨）之后
    i = order.index(finger)
    return segs[i * 4 + 2][1]


def screen_ray(cam, target, lens, sx, sy, z, sensor=36.0, aspect=0.75):
    """相机（位置 cam、看向 target、焦距 lens）画面上 (sx, sy)（0..1，左上为原点）那条视线和平面 Z = z 的交点。"""
    from mathutils import Vector  # noqa: PLC0415

    cam, target = Vector(cam), Vector(target)
    fwd = (target - cam).normalized()
    right = fwd.cross(Vector((0, 0, 1))).normalized()
    up = right.cross(fwd).normalized()
    k = sensor / lens
    d = (fwd + right * ((sx - 0.5) * k) + up * ((0.5 - sy) * k * aspect)).normalized()
    t = (z - cam.z) / d.z
    return cam + d * t


@scene("zhezhi", name="折纸", samples=128, grade=dict(WARM_GRADE, exposure=1.02, bloom=0.30))
def build_zhezhi(draft):
    """折纸：一张旧木桌，一双手从画面两个下角伸进来，正捏着一只快折好的纸鹤的两边翅尖（拇指、食指捏住，往两边轻轻拉开），
    桌上散着几张方纸，一张红的、一张蓝的；后面一盏小油灯给出暖光。按画面位置摆。"""
    from mathutils import Matrix, Vector  # noqa: PLC0415

    K.set_world(lin("#0A0806"), 1.0)
    rng = np.random.default_rng(57)
    cam, tgt, lens = Vector((0.0, -0.50, 0.50)), Vector((0.0, 0.10, 0.04)), 42.0
    make_obj("Table", K.box_build(2.4, 1.6, 0.04), P.mat_wood_plain("Wood", color=(0.12, 0.075, 0.045), rough=0.55,
                                                                    grain_scale=(0.4, 14.0, 14.0)), loc=(0, 0.3, -0.02), index=0,
             smooth=False)
    paper = P.mat_paper_plain("Paper", color=(0.86, 0.83, 0.74))
    tinted = [P.mat_paper_plain("PaperR", color=(0.70, 0.20, 0.14)), P.mat_paper_plain("PaperB", color=(0.32, 0.42, 0.58)), paper]
    for k, (sx, sy, rz, m_) in enumerate(((0.24, 0.30, 0.3, 0), (0.70, 0.22, -0.4, 2), (0.48, 0.16, 0.9, 1), (0.84, 0.48, 0.15, 2),
                                           (0.16, 0.62, -0.6, 2))):
        pp = screen_ray(cam, tgt, lens, sx, sy, 0.0)
        make_obj(f"Sheet{k}", K.box_build(0.15, 0.15, 0.0008), tinted[m_], loc=(pp.x, pp.y, 0.0005 + 0.0009 * k), rot=(0, 0, rz), index=1,
                 smooth=False)
    # 两个捏点（画面左右各一），纸鹤按两翅尖的距离缩放、转向
    PL = screen_ray(cam, tgt, lens, 0.30, 0.50, 0.12)
    PR = screen_ray(cam, tgt, lens, 0.72, 0.46, 0.12)
    span = (PR - PL).length
    S_ = span / 0.66
    yaxis = (PL - PR).normalized()  # 鹤的 +Y（左翅）朝画面左
    xaxis = yaxis.cross(Vector((0, 0, 1))).normalized()
    if xaxis.y > 0:  # 鹤头朝镜头一侧
        xaxis = -xaxis
    xaxis = (Matrix.Rotation(math.radians(-25), 3, "Z") @ xaxis).normalized()
    q = frame_quat(xaxis, (0, 0, 1))
    mid = (PL + PR) / 2
    crane = make_obj("Crane", P.crane_build(wing_up=0.05, wing_sweep=0.0, neck_up=0.18, tail_up=0.17, scale=S_), P.mat_crane_paper("CraneP"),
                     smooth=False, index=2)
    crane.rotation_mode = "QUATERNION"
    crane.rotation_quaternion = q
    crane.location = tuple(mid - q.to_matrix() @ Vector((-0.03 * S_, 0.0, 0.095 * S_)))
    upd()
    tips = [crane.matrix_world @ Vector((-0.03 * S_, sg * 0.33 * S_, 0.095 * S_)) for sg in (1, -1)]
    tips.sort(key=lambda v: v.x)
    skin = P.mat_skin("Skin", color=(0.56, 0.40, 0.31))
    pinch = {"index": (-6, 28, 22, 12), "middle": (2, 60, 70, 40), "ring": (8, 72, 75, 42), "pinky": (14, 82, 78, 42),
             "thumb": (12, 62, 14, 10)}
    for side, tgt_p, corner in (("R", tips[1], (1.02, 1.08)), ("L", tips[0], (-0.02, 1.08))):
        mir = side == "L"
        elbow = screen_ray(cam, tgt, lens, corner[0], corner[1], 0.05)
        hz = (tgt_p - elbow).normalized()
        hz = (hz + Vector((0, 0, -0.10))).normalized()
        hx = Vector((0, 0, 1)).cross(hz).normalized()  # 手背朝上
        qq = frame_quat(hx, hz)
        tip_l = (finger_tip(pinch, "index", mir) + finger_tip(pinch, "thumb", mir)) / 2
        wrist = tgt_p - qq.to_matrix() @ tip_l
        P.hand(f"Hand{side}", skin, pinch, mirror=mir, loc=tuple(wrist), rot=qq.to_euler())
        back = -(qq.to_matrix() @ Vector((0, 0, 1)))
        sleeve(f"Sleeve{side}", tuple(wrist + back * 0.01), tuple(back), r=0.042, L=0.34, flare=1.6)
    lp = screen_ray(cam, tgt, lens, 0.12, 0.10, 0.0)
    bronze_oil_lamp("Lamp", loc=(lp.x, lp.y, 0.0), scale=0.8, flame=1.4)
    K.point_light("Warm", (lp.x + 0.15, lp.y - 0.10, 0.45), 22.0, radius=0.25, color=(1.0, 0.64, 0.32))
    K.area_light("Rim", (0.6, 0.9, 0.5), tuple(mid), 10.0, 0.6, color=(0.55, 0.65, 1.0))
    K.area_light("Fill", (0.2, -1.0, 0.8), tuple(mid), 12.0, 1.2, color=(0.80, 0.78, 0.90))
    K.area_light("Top", (mid.x - 0.1, mid.y + 0.1, 0.9), tuple(mid), 6.0, 0.5, color=(1.0, 0.92, 0.80))
    K.camera(tuple(cam), tuple(tgt), lens=lens, fstop=4.5, focus=(mid - cam).length)
    _ = rng
    return {"light": "warm"}


@background("zhezhi")
def bg_zhezhi(P_, h, w, rng, k):
    P_.fill_grad("#0E0B0A", "#0A0808", cloud=0.12)
    K.bg_glow(P_, 0.30, 0.30, 0.40, 0.35, "#6A3A16", 0.28)
    K.bg_ink(P_, [(0.98, 0.06, 0.26, 0.18, -0.4), (0.02, 0.96, 0.30, 0.20, 0.2)], 0.45)


# ====================================================================== 轻功


def hero_figure(pose_frame=0):
    """主角模型（art/models/hero.py，和游戏里的立绘同一个模型）摆成腾跃：轻功冲刺的上身，前腿高抬、后腿蹬直、脚尖点地。
    返回 (root, parts)。模型朝 -Y，root 坐标里 +Y 是身后。"""
    import sys  # noqa: PLC0415

    from mathutils import Vector  # noqa: PLC0415

    bpy = K._bpy()
    models = str(K.ART / "models")
    if models not in sys.path:
        sys.path.insert(0, models)
    from style import bstyle as B  # noqa: PLC0415

    for name in [*B.LINE_COLLECTIONS.values(), B.CONTOUR_COLLECTION, B.CUN_COLLECTION]:  # hero 要这几个集合
        if name not in bpy.data.collections:
            bpy.context.scene.collection.children.link(bpy.data.collections.new(name))
    import hero as H  # noqa: PLC0415

    root, parts, _ = H.build_hero(lamps=("red",))
    H.pose_hero(parts, "dash", pose_frame, 8)
    parts["pelvis"].location = (0, 0.02, H.PELVIS_Z - 0.02)
    H._leg_ik(parts, "L", Vector((H.HIP_X * 0.9, -0.30, 0.52)), math.radians(10))  # 前腿高抬
    H._leg_ik(parts, "R", Vector((-H.HIP_X * 0.9, 0.46, 0.10)), math.radians(48))  # 后腿蹬直，脚尖点地
    return root, parts


@scene("qinggong", name="轻功", samples=128, grade=dict(COLD_GRADE, exposure=1.06, bloom=0.40))
def build_qinggong(draft):
    """轻功：月下，一个身影（主角：白衣墨氅、手提灯杖）在飞檐的檐角上脚尖一点、腾身而起，衣摆、发带、马尾都往后飞扬；
    脚下的瓦片纹丝不动。人物是逆着大月亮的剪影，月光给他镶一道冷边，灯笼一点暖光。"""
    from mathutils import Vector  # noqa: PLC0415

    bpy = K._bpy()
    sky_gradient(lin("#05080F"), lin("#2E4466"), 0.8, ground=lin("#04060A"))
    root, parts = hero_figure(0)
    root.rotation_euler = (0, 0, math.radians(90))  # 面朝 +X（画面右）
    root.location = (0.0, 0.0, 0.0)
    upd()
    # 剪影材质：近黑的墨蓝，布面带一点绒光（月光从后面打出轮廓）
    sil = K.Mat("Silhouette")
    b = sil.principled(Base_Color=(0.016, 0.018, 0.026, 1.0), Roughness=0.55, Sheen_Weight=0.8, Sheen_Roughness=0.3,
                       Sheen_Tint=(0.75, 0.85, 1.0, 1.0))
    sil_m = sil.surface(b.outputs[0])
    paper = K.mat_lantern_paper("LanternPaperQ")
    core = P.mat_emit("LanternCoreQ", (1.0, 0.70, 0.35), 18.0)
    for ob in bpy.data.objects:
        if ob.type != "MESH":
            continue
        ob.data.materials.clear()
        ob.data.materials.append(paper if ob.name == "LanternShell" else core if ob.name == "LanternCore" else sil_m)
        ob.pass_index = 1
    lc = bpy.data.objects["LanternCore"].matrix_world.translation
    K.point_light("LanternLight", tuple(lc), 6.0, radius=0.05, color=(1.0, 0.62, 0.30))
    # 檐角：后脚尖下面
    toe = bpy.data.objects["FootR"].matrix_world @ Vector((0.0, -0.10, -0.03))
    w, d_, h_, curl = 4.2, 2.2, 0.80, 0.45
    roof = make_obj("Roof", P.roof_build(w=w, d=d_, h=h_, curl=curl, wall_h=0.0), P.mat_roof_tiles("Tiles", rows=60.0),
                    index=2)
    roof.rotation_euler = (0, 0, math.radians(-18))  # 檐角斜着朝镜头，看得到翘起的角和瓦垄
    upd()
    tip_local = roof.matrix_world.to_3x3() @ Vector((w * 1.08 / 2, -d_ / 2 * 1.12, curl))
    roof.location = tuple(toe - tip_local + Vector((0.0, 0.0, -0.01)))
    K.area_light("Moon", (-2.0, 9.0, 4.0), (0, 0, 1.2), 2600.0, 3.0, color=(0.70, 0.82, 1.0))
    K.area_light("Rim", (3.0, 6.0, 1.0), (0, 0, 1.2), 900.0, 2.0, color=(0.62, 0.76, 1.0))
    K.area_light("Front", (-2.0, -7.0, 2.5), (-1.0, 0, 0.0), 160.0, 4.0, color=(0.55, 0.62, 0.90))
    K.camera((0.7, -9.0, 0.55), (0.30, 0.0, 1.50), lens=54.0, fstop=8.0, focus=9.0)
    return {"light": "cold"}


@background("qinggong")
def bg_qinggong(P_, h, w, rng, k):
    P_.fill_grad("#0B1222", "#111C30", cloud=0.12)
    K.bg_glow(P_, 0.58, 0.40, 0.55, 0.50, "#40597E", 0.32)
    K.bg_moon(P_, 0.58, 0.38, 0.17, rng, k, color="#EEF2F8", halo="#8098BE", a=0.85, halo_a=0.40)
    bg_clouds(P_, rng, k, [(0.20, 0.03, 0.05, 0.50), (0.70, 0.025, 0.55, 1.0), (0.78, 0.02, 0.0, 0.45)], "#5B7194", 0.20)
    K.bg_ink(P_, [(0.02, 0.06, 0.26, 0.18, 0.2), (0.98, 0.08, 0.24, 0.18, -0.4)], 0.45)


# ====================================================================== 锐目

EYE_R = 0.012  # 眼球半径（米）


def mat_iris(name, R=EYE_R, ri=0.0059, rp=0.0032):
    """眼球（物体坐标：光轴 +Z）：虹膜是铜金色的放射纹（深铜 → 亮金，近瞳孔一圈略亮的卷缩轮，外缘一道深色的缘），
    瞳孔放大、纯黑；眼白埋在暗处（灰蓝）；角膜一层清漆，接住月光的高光。不画血丝。"""
    M = K.Mat(name)
    m = M.math
    oc = M.coord("Object")
    sep = M.n("ShaderNodeSeparateXYZ")
    M.l(oc, sep.inputs[0])
    x, y, z = sep.outputs["X"], sep.outputs["Y"], sep.outputs["Z"]
    rxy = m("SQRT", m("ADD", m("MULTIPLY", x, x), m("MULTIPLY", y, y)))
    phi = m("ARCTAN2", y, x)
    front = m("GREATER_THAN", z, 0.0)
    t_ir = m("DIVIDE", m("SUBTRACT", rxy, rp), ri - rp)  # 0 瞳孔边 → 1 虹膜外缘
    # 放射纹：沿角度很密、沿半径拉长；再叠一层更细的
    cp = M.n("ShaderNodeCombineXYZ")
    M.l(m("MULTIPLY", phi, 14.0), cp.inputs["X"])
    M.l(m("MULTIPLY", t_ir, 1.2), cp.inputs["Y"])
    fib = M.noise(cp.outputs[0], scale=3.0, detail=7.0, rough=0.62)
    cp2 = M.n("ShaderNodeCombineXYZ")
    M.l(m("MULTIPLY", phi, 40.0), cp2.inputs["X"])
    M.l(m("MULTIPLY", t_ir, 0.8), cp2.inputs["Y"])
    fib2 = M.noise(cp2.outputs[0], scale=3.0, detail=4.0, rough=0.6)
    f = m("ADD", m("MULTIPLY", fib.outputs["Fac"], 0.6), m("MULTIPLY", fib2.outputs["Fac"], 0.4))
    icol, _ = M.ramp(M.maprange(f, 0.32, 0.68), [(0.0, (0.05, 0.020, 0.007)), (0.45, (0.30, 0.13, 0.035)), (0.8, (0.72, 0.42, 0.11)),
                                                 (1.0, (0.95, 0.70, 0.30))])
    collar = m("MULTIPLY", M.maprange(t_ir, 0.10, 0.28), M.maprange(t_ir, 0.45, 0.28))
    icol = M.mix(m("MULTIPLY", collar, 0.55), icol, (0.85, 0.58, 0.20, 1.0))
    icol = M.mix(M.maprange(t_ir, 0.80, 1.0), icol, (0.012, 0.006, 0.003, 1.0))
    icol = M.mix(M.maprange(t_ir, 0.06, 0.0), icol, (0.02, 0.01, 0.004, 1.0))  # 瞳孔边一圈暗
    in_iris = m("MULTIPLY", front, M.maprange(rxy, ri + 0.0002, ri - 0.0002))
    col = M.mix(in_iris, (0.07, 0.075, 0.085, 1.0), icol)
    in_pupil = m("MULTIPLY", front, M.maprange(rxy, rp + 0.0001, rp - 0.0001))
    col = M.mix(in_pupil, col, (0.0015, 0.0015, 0.0018, 1.0))
    nrm = M.bump(m("MULTIPLY", f, in_iris), strength=0.25, distance=0.0002)
    bsdf = M.principled(Base_Color=col, Roughness=0.42, Coat_Weight=1.0, Coat_Roughness=0.012, Coat_IOR=1.376, Normal=nrm)
    return M.surface(bsdf.outputs[0])


def lid_curves(a=0.0132, up=0.0036, lo=0.0032):
    """眼裂（物体坐标 XY）：上眼睑弧最高点偏向内眼角，下眼睑平缓；返回 s∈[0,1) → (x, y) 的函数（上缘内→外，下缘外→内）。"""
    def at(s):
        if s < 0.5:
            u = s / 0.5
            x = -a + 2 * a * u
            k = max(0.0, 1 - (x / a) ** 2)
            return x, up * k ** 0.70 * (1 - 0.18 * x / a)
        u = (s - 0.5) / 0.5
        x = a - 2 * a * u
        k = max(0.0, 1 - (x / a) ** 2)
        return x, -lo * k ** 0.85 * (1 + 0.10 * x / a)
    return at


def eyelid_build(R=EYE_R, n=160, m=46, T=0.050):
    """眼周的皮肤（物体坐标，光轴 +Z）：从眼裂的边（贴着眼球）往外长一圈，先往前鼓出眼睑的厚度、再顺着脸往后弯；
    上眼睑一道褶、眉骨往前鼓。"""
    lid = lid_curves()

    def build(bm):
        uvl = bm.loops.layers.uv.new("UVMap")
        grid = []
        for j in range(m + 1):
            t = T * (j / m) ** 1.6
            row = []
            for i in range(n):
                s = i / n
                x, y = lid(s)
                rr = math.hypot(x, y)
                nx, ny = (x / rr, y / rr) if rr > 1e-6 else (1.0, 0.0)
                upper = s < 0.5
                px, py = x + nx * t * (1.0 if upper else 0.9), y + ny * t * (1.25 if upper else 0.9)
                zb = math.sqrt(max(R * R - x * x - y * y, 0.0)) + 0.0004
                zt = zb + 0.0016 * math.sin(min(t / 0.0035, 1.0) * math.pi / 2) - 0.0028 * min(t / 0.004, 1.0) ** 2 - 2.2 * t * t
                if upper:
                    k = max(0.0, 1 - (x / 0.015) ** 2)
                    zt += -0.0005 * math.exp(-((t - 0.0062) / 0.0013) ** 2) * k  # 双眼皮那道褶
                    zt += 0.0040 * math.exp(-((t - 0.020) / 0.007) ** 2) * (0.6 + 0.4 * k)  # 眉骨
                else:
                    zt += 0.0010 * math.exp(-((t - 0.012) / 0.006) ** 2)  # 下眼睑下面的卧蚕
                row.append(bm.verts.new((px, py, zt)))
            grid.append(row)
        for j in range(m):
            for i in range(n):
                i1 = (i + 1) % n
                f = bm.faces.new((grid[j][i], grid[j][i1], grid[j + 1][i1], grid[j + 1][i]))
                for lp, uv in zip(f.loops, ((i / n, j / m), ((i + 1) / n, j / m), ((i + 1) / n, (j + 1) / m), (i / n, (j + 1) / m))):
                    lp[uvl].uv = uv
        import bmesh  # noqa: PLC0415

        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    return build


@scene("ruimu", name="锐目", samples=160, grade=dict(COLD_GRADE, exposure=1.05, bloom=0.40, sat=1.02))
def build_ruimu(draft):
    """锐目：一只眼睛的特写，脸和眼周都埋在暗处（眼睑只是两片暗影，不画皮肤和睫毛），只有一道横的月光照亮眼睛这一条；
    虹膜铜金色的放射纹，瞳孔放大，瞳孔里七枚方孔小铜钱排成北斗，钱面带一点高光。"""
    from mathutils import Vector  # noqa: PLC0415

    K.set_world(lin("#04060B"), 1.0)
    eye = make_obj("Eyeball", K.lathe_uv([(EYE_R * math.sin(a), -EYE_R * math.cos(a)) for a in np.linspace(0, math.pi, 96)], segments=128),
                   mat_iris("IrisM"), index=1)
    lid_m = P.mat_stone("LidDark", color=(0.012, 0.010, 0.010), rough=0.9, scale=40.0, bump=0.0)
    lid = make_obj("Lids", eyelid_build(), lid_m, index=1)
    # 瞳孔里的北斗七钱：真的小方孔钱，贴着瞳孔、钱面朝镜头；斗口朝上、斗柄往右
    rp, rc = 0.0034, 0.00056
    pts = np.array(P.DIPPER, float)
    pts = pts - (pts.min(0) + pts.max(0)) / 2
    k = (rp - rc * 1.15) / np.hypot(pts[:, 0], pts[:, 1]).max()
    ang = math.radians(-8)
    rot = np.array([[math.cos(ang), -math.sin(ang)], [math.sin(ang), math.cos(ang)]])
    pts = (pts * k) @ rot.T
    coin_m = P.mat_coin("PupilCoin", gilt=1.0, rough=0.28, emit=((1.0, 0.58, 0.16), 0.55))
    sc = rc / 0.022
    for j, (x, y) in enumerate(pts):
        zc = math.sqrt(max(EYE_R ** 2 - x * x - y * y, 0.0))
        nrm = Vector((x, y, zc)).normalized()
        ob = make_obj(f"Coin{j}", P.coin_build(), coin_m, parent=eye, loc=tuple(nrm * (EYE_R + 0.00007)), scale=(sc, sc, sc * 0.6), index=2)
        ob.rotation_mode = "QUATERNION"
        ob.rotation_quaternion = nrm.to_track_quat("Z", "Y")
    for ob in (eye, lid):  # 光轴 +Z → 世界 -Y（朝镜头），物体 +Y → 世界 +Z（朝上）
        ob.rotation_euler = (math.radians(90), 0, 0)
    # 月光：一道横的长条光，只照亮眼睛这一条；另一盏小的给铜钱点高光
    K.area_light("Key", (-0.05, -0.22, 0.085), (0, 0, 0.001), 0.40, 0.12, size_y=0.010, color=(0.78, 0.88, 1.0))
    K.area_light("Glint", (0.05, -0.18, 0.07), (0, 0, 0.0), 0.02, 0.02, color=(1.0, 0.85, 0.60))
    K.area_light("Rim", (0.10, 0.15, 0.06), (0, 0, 0), 0.03, 0.10, color=(0.55, 0.68, 1.0))
    K.camera((0.0015, -0.062, 0.0024), (0.0003, 0.0, 0.0005), lens=85.0)
    return {"light": "cold"}


@background("ruimu")
def bg_ruimu(P_, h, w, rng, k):
    P_.fill_grad("#0A0D14", "#0B0E15", cloud=0.12)
    K.bg_ink(P_, [(0.02, 0.06, 0.26, 0.18, 0.2), (0.98, 0.08, 0.24, 0.18, -0.4)], 0.5)


# ====================================================================== 补给：莲子、灯油


def mat_lotus_pod(name):
    """莲蓬：青绿偏黄的海绵质，顶面一个个孔，侧面细的竖纹，边上一点干枯的褐。"""
    M = K.Mat(name)
    m = M.math
    oc = M.coord("Object")
    nz = M.noise(oc, scale=60.0, detail=6.0, rough=0.7)
    big = M.noise(oc, scale=8.0, detail=3.0)
    col = M.mix(M.maprange(big.outputs["Fac"], 0.35, 0.65), (0.10, 0.20, 0.06, 1.0), (0.22, 0.30, 0.10, 1.0))
    col = M.mix(m("MULTIPLY", M.maprange(big.outputs["Fac"], 0.62, 0.75), 0.6), col, (0.20, 0.14, 0.06, 1.0))
    nrm = M.bump(nz.outputs["Fac"], strength=0.35, distance=0.002)
    bsdf = M.principled(Base_Color=col, Roughness=0.62, Subsurface_Weight=0.15, Normal=nrm, Sheen_Weight=0.4)
    return M.surface(bsdf.outputs[0])


def mat_lotus_seed(name, glow=0.0, peeled=False):
    """莲子：外皮青绿发亮（剥开的是乳白），淡青的光从里面透出来。"""
    M = K.Mat(name)
    oc = M.coord("Object")
    nz = M.noise(oc, scale=300.0, detail=4.0)
    base = (0.66, 0.84, 0.70) if peeled else (0.16, 0.30, 0.10)
    nrm = M.bump(nz.outputs["Fac"], strength=0.08, distance=0.0005)
    bsdf = M.principled(Base_Color=(*base, 1.0), Roughness=0.30 if not peeled else 0.5, Coat_Weight=0.6 if not peeled else 0.0,
                        Subsurface_Weight=0.5, Subsurface_Radius=(0.004, 0.006, 0.005), Subsurface_Scale=0.5, Normal=nrm)
    if glow:
        bsdf.inputs["Emission Color"].default_value = (0.30, 1.0, 0.72, 1.0)
        bsdf.inputs["Emission Strength"].default_value = glow
    return M.surface(bsdf.outputs[0])


@scene("lotus", name="莲子", samples=128, grade=dict(WOOD_GRADE, exposure=1.04, bloom=0.40))
def build_lotus(draft):
    """莲子：一只莲蓬斜躺在一片荷叶上，顶面朝镜头（一个个孔，有的孔空了），剥出来的莲子散在旁边，
    其中剥了皮的三颗乳白、发着淡青的光；荷叶上滚着两滴水。俯看。"""
    from mathutils import Vector  # noqa: PLC0415

    K.set_world(lin("#060A0A"), 1.0)
    rng = np.random.default_rng(14)
    pod_m = mat_lotus_pod("Pod")
    # 莲蓬：倒圆锥（顶面平、微鼓），顶上 13 个孔里嵌着莲子的顶
    prof = [(0.0, -0.075), (0.012, -0.072), (0.030, -0.05), (0.050, -0.02), (0.066, 0.005), (0.072, 0.018), (0.070, 0.024), (0.0, 0.028)]
    pod = make_obj("Pod", K.lathe_uv(prof, segments=80), pod_m, index=1)
    seed_m = mat_lotus_seed("Seed")
    holes = [(0.0, 0.0)] + [(0.026 * math.cos(a), 0.026 * math.sin(a)) for a in np.linspace(0, 2 * math.pi, 5, endpoint=False)] + \
            [(0.050 * math.cos(a + 0.3), 0.050 * math.sin(a + 0.3)) for a in np.linspace(0, 2 * math.pi, 7, endpoint=False)]
    hole_m = P.mat_stone("Hole", color=(0.03, 0.05, 0.02), scale=60.0)
    for k, (x, y) in enumerate(holes):
        make_obj(f"Hole{k}", K.lathe_uv([(0.0, 0.0), (0.0085, 0.0), (0.0085, 0.001), (0.0, 0.001)], segments=20), hole_m, parent=pod,
                 loc=(x, y, 0.0275), index=1)
        if k % 3 != 2:  # 有的孔里还嵌着莲子（只露个顶）
            make_obj(f"SeedIn{k}", K.ico_cloud([(0, 0, 0)], [0.0078], 2), seed_m, parent=pod, loc=(x, y, 0.024), scale=(1.0, 1.0, 0.8),
                     index=1)
    pod.location = (-0.035, 0.035, 0.065)
    pod.rotation_euler = (math.radians(42), math.radians(-8), math.radians(14))
    # 荷叶：一大片圆叶托底（边缘起伏、叶脉放射）；压低镜面，免得反出一大片光
    from card_weapons import low_spec  # noqa: PLC0415

    leaf_m = low_spec(mat_young_leaf("LotusLeaf", color=(0.006, 0.022, 0.010), tip=(0.014, 0.040, 0.016), vein=(0.030, 0.070, 0.030)),
                      0.10)

    def lotus_leaf(bm):
        uvl = bm.loops.layers.uv.new("UVMap")
        nr, ns = 24, 96
        rows = []
        for j in range(nr + 1):
            r = 0.30 * j / nr
            row = []
            for i in range(ns):
                a = 2 * math.pi * i / ns
                z = -0.02 + 0.10 * (r / 0.30) ** 2 + 0.012 * math.sin(a * 7) * (r / 0.30) ** 2
                row.append(bm.verts.new((r * math.cos(a), r * math.sin(a), z)))
            rows.append(row)
        for j in range(nr):
            for i in range(ns):
                i1 = (i + 1) % ns
                f = bm.faces.new((rows[j][i], rows[j][i1], rows[j + 1][i1], rows[j + 1][i]))
                v0 = (i * 12 / ns) % 1.0  # 一圈 12 道叶脉（ns 是 12 的倍数，每格不跨接缝）
                v1 = v0 + 12 / ns
                for lp, uv in zip(f.loops, ((j / nr, v0), (j / nr, v1), ((j + 1) / nr, v1), ((j + 1) / nr, v0))):
                    lp[uvl].uv = uv
    make_obj("Leaf", lotus_leaf, leaf_m, index=0)
    # 散在叶上的莲子：两颗剥了皮发光
    glow_m = mat_lotus_seed("SeedGlow", glow=0.55, peeled=True)
    for k, (x, y, g) in enumerate(((0.085, -0.045, True), (0.125, 0.015, False), (0.050, -0.090, True), (-0.105, -0.060, False),
                                   (0.140, -0.075, True), (-0.060, -0.105, False))):
        ob = make_obj(f"Seed{k}", K.ico_cloud([(0, 0, 0)], [0.011], 3), glow_m if g else seed_m, loc=(x, y, 0.0 + 0.10 * ((x * x + y * y) / 0.09) - 0.02 + 0.011),
                      scale=(1.0, 1.0, 1.25), rot=(rng.uniform(0, 1.5), 0, rng.uniform(0, 6)), index=2)
        if g:
            K.point_light(f"SeedL{k}", tuple(Vector(ob.location) + Vector((0, 0, 0.012))), 0.12, radius=0.01, color=(0.45, 0.95, 0.85))
    glass = mat_glass("Drop")
    for k, (x, y, r) in enumerate(((-0.14, 0.06, 0.012), (0.20, 0.10, 0.008))):
        make_obj(f"Drop{k}", K.ico_cloud([(0, 0, 0)], [r], 3), glass, loc=(x, y, 0.10 * ((x * x + y * y) / 0.09) - 0.02 + r * 0.6),
                 scale=(1.0, 1.0, 0.6), index=3)
    K.area_light("Key", (0.30, 0.25, 0.80), (0, 0, 0.03), 5.0, 0.35, color=(0.90, 0.95, 1.0))
    K.area_light("Rim", (0.5, 0.6, 0.4), (0, 0, 0.03), 8.0, 0.4, color=(0.70, 0.95, 0.85))
    K.area_light("Fill", (0.3, -0.6, 0.3), (0, 0, 0.03), 1.5, 0.6, color=(0.80, 0.90, 1.0))
    K.camera((0.03, -0.40, 0.42), (0.015, 0.0, 0.035), lens=50.0, fstop=4.0, focus=0.57)
    return {"light": "wood"}


@background("lotus")
def bg_lotus(P_, h, w, rng, k):
    P_.fill_grad("#08100F", "#0A1212", cloud=0.12)
    K.bg_glow(P_, 0.50, 0.50, 0.45, 0.40, "#2E5A50", 0.28)
    K.bg_ink(P_, [(0.02, 0.06, 0.26, 0.18, 0.2), (0.98, 0.08, 0.24, 0.18, -0.4)], 0.45)


def mat_glaze(name, color=(0.30, 0.12, 0.05)):
    """陶釉：深褐的釉面，釉厚处积色、边上淡出露胎（偏灰黄），清亮带一点细开片。"""
    M = K.Mat(name)
    m = M.math
    oc = M.coord("Object")
    nz = M.noise(oc, scale=12.0, detail=4.0)
    craze = M.n("ShaderNodeTexVoronoi", Scale=90.0, _feature="DISTANCE_TO_EDGE")
    M.l(oc, craze.inputs["Vector"])
    cr = M.maprange(craze.outputs["Distance"], 0.0, 0.03, 1.0, 0.0)
    col = M.mix(M.maprange(nz.outputs["Fac"], 0.35, 0.65), (color[0] * 0.6, color[1] * 0.6, color[2] * 0.6, 1.0), (*color, 1.0))
    col = M.mix(m("MULTIPLY", cr, 0.25), col, (0.05, 0.03, 0.02, 1.0))
    bsdf = M.principled(Base_Color=col, Roughness=0.30, Coat_Weight=0.45, Coat_Roughness=0.12)
    return M.surface(bsdf.outputs[0])


def mat_oil_stream(name):
    """油线：金黄透亮（半透 + 一点自发光，像被灯光照透）。"""
    M = K.Mat(name)
    bsdf = M.principled(Base_Color=(1.0, 0.70, 0.20, 1.0), Roughness=0.05, IOR=1.47, Transmission_Weight=0.85)
    bsdf.inputs["Emission Color"].default_value = (1.0, 0.62, 0.18, 1.0)
    bsdf.inputs["Emission Strength"].default_value = 2.0
    return M.surface(bsdf.outputs[0])


@scene("oil", name="灯油", samples=128, grade=dict(WARM_GRADE, exposure=1.0, bloom=0.38))
def build_oil(draft):
    """灯油：一只深褐釉的陶油壶从右上斜下来，壶嘴往下面的青铜灯盏里倒油，一线金黄的油细细地落进灯盏，
    溅起一圈涟漪；灯芯那头的火映着油线发亮。"""
    from mathutils import Vector  # noqa: PLC0415

    K.set_world(lin("#0A0806"), 1.0)
    lamp, fz = bronze_oil_lamp("Lamp", loc=(0, 0, -0.30), scale=1.0, flame=1.2, flame_h=0.035)
    upd()
    oil_z = -0.30 + 0.342
    # 壶：倒过来斜着（壶身 + 壶颈 + 壶嘴 + 把手）
    jar_m = mat_glaze("Glaze", color=(0.13, 0.055, 0.025))
    jar = K._bpy().data.objects.new("Jar", None)
    K.link(jar)
    prof = [(0.0, 0.0), (0.040, 0.0), (0.060, 0.02), (0.072, 0.06), (0.068, 0.10), (0.050, 0.13), (0.030, 0.145), (0.028, 0.165),
            (0.034, 0.172), (0.024, 0.176), (0.0, 0.176)]
    make_obj("JarBody", K.lathe_uv(prof, segments=64), jar_m, parent=jar, index=1)
    spout = [(0.045, 0.0, 0.10), (0.085, 0.0, 0.13), (0.115, 0.0, 0.165), (0.130, 0.0, 0.180)]
    make_obj("Spout", K.tube_uv(spout, 0.010, sides=16, radius_fn=lambda t: 1 - 0.35 * t), jar_m, parent=jar, index=1)
    handle = [(-0.05, 0.0, 0.14), (-0.10, 0.0, 0.13), (-0.11, 0.0, 0.07), (-0.065, 0.0, 0.04)]
    make_obj("Handle", K.tube_uv(K.catmull(handle, n=30), 0.008, sides=12), jar_m, parent=jar, index=1)
    jar.rotation_euler = (0.0, math.radians(-58), math.radians(-12))
    jar.location = (0.13, 0.02, oil_z + 0.17)
    upd()
    mouth = jar.matrix_world @ Vector((0.132, 0.0, 0.181))
    # 油线：从壶嘴落到灯盏（抛物线，越往下越细）
    land = Vector((0.020, 0.0, oil_z))
    pts = [mouth.lerp(land, t) + Vector((0.012 * math.sin(math.pi * t) * (1 - t), 0, -0.02 * math.sin(math.pi * t))) for t in np.linspace(0, 1, 40)]
    make_obj("Stream", K.tube_uv([tuple(p) for p in pts], 0.0032, sides=12, radius_fn=lambda t: 1.0 - 0.45 * t), mat_oil_stream("OilM"), index=3)
    ring = mat_oil_stream("RingM")
    for k, r in enumerate((0.010, 0.018, 0.026)):
        make_obj(f"Ripple{k}", K.torus_build(r, 0.0012 * (1 - 0.25 * k), 64, 8), ring, loc=(land.x, land.y, oil_z + 0.0008), index=3)
    for k in range(10):  # 溅起的小油珠
        a = 2 * math.pi * k / 10
        make_obj(f"Drop{k}", K.ico_cloud([(0, 0, 0)], [0.0018], 2), ring, loc=(land.x + 0.014 * math.cos(a), land.y + 0.014 * math.sin(a),
                                                                            oil_z + 0.006 + 0.004 * (k % 3)), index=3)
    K.point_light("Warm", (-0.10, -0.15, oil_z + 0.12), 6.0, radius=0.03, color=(1.0, 0.66, 0.34))
    K.area_light("Rim", (0.3, 0.4, oil_z + 0.3), (0.05, 0, oil_z + 0.1), 2.0, 0.4, color=(0.55, 0.65, 1.0))
    K.area_light("Fill", (0.2, -0.5, oil_z + 0.1), (0.05, 0, oil_z + 0.08), 3.0, 0.5, color=(1.0, 0.82, 0.60))
    K.camera((-0.03, -0.72, oil_z + 0.17), (0.06, 0.0, oil_z + 0.14), lens=45.0, fstop=5.6, focus=0.72)
    return {"light": "warm"}


@background("oil")
def bg_oil(P_, h, w, rng, k):
    P_.fill_grad("#0E0B0A", "#0A0808", cloud=0.12)
    K.bg_glow(P_, 0.45, 0.55, 0.45, 0.42, "#6A3A16", 0.30)
    K.bg_ink(P_, [(0.02, 0.06, 0.30, 0.22, 0.2), (0.98, 0.94, 0.30, 0.22, -0.3)], 0.5)
