"""竹魅（青丘小妖，精类）：竹海里的老竹吸了魂，成了魅。

造型：一簇竹子立在一团竹根上——三根淡彩石绿的竹竿（浓墨竹节）从根团里长出，中间最高；脸是套在中竿上的一截粗竹筒，
竹筒顶上斜切一刀（露出焦墨的空心），筒上一道竹节当眉，下面两道焦墨眼缝，里面是发光的青色眼（EYE_HEX）；
两条手臂是两根细竹枝，枝梢一簇竹叶当手；竿顶、枝梢的竹叶是墨竹的画法：浓墨、淡墨的叶片，不描线。
脚是竹根：五条赭石的根从根团里伸出去抓地，走路时轮流抬起、挪步（像滑着走、一瘸一拐）。

动画（只画 E）：
  idle  4 帧循环：藏身的样子，像一丛竹子——两条手臂竖直贴着竹竿，近手的叶簇挡在脸前，眼睛只睁一条缝；竹叶轻轻摇。
  move  6 帧循环：竹根轮流挪步，身子前倾、左右晃，手臂垂着摆。
  shoot 5 帧不循环：0–1 近手的竹枝向后弯成一张弓（枝梢搭着一根削尖的竹刺，第 1 帧拉满，游戏在预警期间停在这一帧），
        2 放：竹枝向前弹直，竹刺离手（游戏在 muzzle 挂点放出 weapons/bamboo_spike），3–4 回弹、复位。
帧 FRAME["elite"]（2 倍 320²），锚点 ANCHOR（比主角高：约 2.7 米）。挂点 eyes、muzzle（竹枝梢，竹刺出手的位置；
每个动画每帧都有，shoot 里才有用）、feet。眼睛颜色 EYE_HEX 不在调色板里，出图时写进 meta.palette_extra。
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import bmesh
import bpy
from mathutils import Matrix, Vector

ART = Path(__file__).resolve().parents[1]
for p in (ART, ART / "models"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
from style import bstyle as B  # noqa: E402
from style import style as S  # noqa: E402
import kit as K  # noqa: E402

EYE_HEX = "#9BF5C9"  # 青色妖眼
PALETTE_EXTRA = [EYE_HEX]
SOCKETS = ("eyes", "muzzle")
MASK_Z = 1.86  # 脸（竹筒）中心高度
MASK_R = 0.20  # 脸的竹筒半径
X_AXIS = Vector((1, 0, 0))


# ================================================================ 几何
def _multi(*builds):
    def build(bm):
        for b in builds:
            b(bm)
    return build


def _arc_points(base, a0_deg, kappa_deg, length, n=10, side=0.0):
    """一根弯竹：从 base 出发，在 YZ 平面里起始方向 a0（0=竖直向上，正=向前 -Y），沿长度均匀转过 kappa 度。
    side：沿 X 的横向偏移（到梢头为止线性加上去）。"""
    pts = [Vector(base)]
    ds = length / (n - 1)
    for i in range(1, n):
        a = math.radians(a0_deg + kappa_deg * (i - 0.5) / (n - 1))
        pts.append(pts[-1] + Vector((side / (n - 1), -math.sin(a) * ds, math.cos(a) * ds)))
    return pts


def _culm_builds(pts, r0, r1, node_every=0.30, node_from=0.15):
    """竹竿（圆管，略收细）+ 竹节（稍粗的短环）。返回 (竿 build, 节 build)。"""
    total = sum((b - a).length for a, b in zip(pts, pts[1:]))
    rf = lambda t: r0 + (r1 - r0) * t  # noqa: E731
    culm = K.tube_build(pts, rf, 10)
    rings = []
    s = node_from
    while s < total - 0.08:
        acc = 0.0
        for a, b in zip(pts, pts[1:]):
            L = (b - a).length
            if acc + L >= s:
                p = a.lerp(b, (s - acc) / L)
                d = (b - a).normalized()
                r = rf(s / total) * 1.16
                rings.append(K.tube_build([p - d * 0.016, p, p + d * 0.016], lambda t, r=r: r, 10))
                break
            acc += L
        s += node_every
    return culm, _multi(*rings)


def _leaf(bm, base, d, length, width, droop=0.3, twist=0.0, n=6):
    """一片竹叶：细长的披针形，叶柄窄、中前段最宽、尖端收尖，沿长度下垂（droop），中脉微微隆起。"""
    d = Vector(d).normalized()
    side = d.cross(X_AXIS)  # 叶面尽量朝 ±X：E 向时正对镜头（模型 -X 朝镜头），不会侧成一条线
    if side.length < 0.3:
        side = d.cross(Vector((0, 0, 1)))
    side.normalize()
    side = Matrix.Rotation(twist, 3, d) @ side
    nrm = side.cross(d).normalized()
    rows = []
    for i in range(n + 1):
        t = i / n
        c = Vector(base) + d * (length * t) + Vector((0, 0, -droop * length * t * t))
        w = width * (0.18 + 0.82 * math.sin(math.pi * min(1.0, t * 1.05) ** 0.75)) * (1 - t) ** 0.35 if t < 1 else 0.0
        rows.append([bm.verts.new(c - side * w * 0.5), bm.verts.new(c + nrm * w * 0.12),
                     bm.verts.new(c + side * w * 0.5)])
    for a, b in zip(rows, rows[1:]):
        for k in range(2):
            bm.faces.new((a[k], a[k + 1], b[k + 1], b[k]))


def _spray(base, d, n_leaves, length, width, spread, droop, seed, phase=0.0, flutter=0.0):
    """一簇竹叶（叶片从同一点往外散开，像画墨竹的“个”字、“介”字）。"""
    d = Vector(d).normalized()
    side = d.cross(X_AXIS)  # 叶簇在 YZ 平面里散开（E 向画面里展得开）
    if side.length < 0.3:
        side = d.cross(Vector((0, 0, 1)))
    side.normalize()
    up2 = side.cross(d).normalized()

    def build(bm):
        for k in range(n_leaves):
            u = (k / max(n_leaves - 1, 1) - 0.5) * 2  # -1..1
            ang = spread * u + 0.15 * math.sin(seed * 3.1 + k * 1.7)
            dd = (d * math.cos(ang) + side * math.sin(ang) + up2 * (0.18 * math.sin(seed + k * 2.3))).normalized()
            fl = flutter * math.sin(phase + k * 1.3 + seed)
            ln = length * (0.78 + 0.22 * math.cos(k * 2.1 + seed))
            _leaf(bm, base + dd * 0.01, dd, ln, width, droop=droop + 0.25 * fl, twist=0.5 * u + 0.4 * fl)
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    return build


# ================================================================ 姿态参数
def _state(anim: str, frame: int, n: int) -> dict:
    ph = 2 * math.pi * (frame % max(n, 1)) / max(n, 1)
    st = dict(ph=ph, lean=0.0, sway=0.0, bob=0.0, eye=1.0, cover=0.0, flutter=0.25, spike=False,
              near=(150.0, -25.0), far=(160.0, -20.0), near_side=-0.10, far_side=0.10,
              top_sway=0.0, roots=[(0.0, 0.0)] * 5)
    if anim == "idle":  # 藏身：手臂竖直贴着竹竿，叶簇挡脸，眼睛一条缝
        st.update(lean=0.0, sway=0.5 * math.sin(ph), eye=0.22, cover=1.0, flutter=0.35,
                  near=(-6.0 + 2.0 * math.sin(ph + 0.5), 8.0), far=(8.0 + 2.0 * math.sin(ph + 1.2), -6.0),
                  near_side=-0.06, far_side=0.08, top_sway=0.05 * math.sin(ph))
    elif anim == "move":  # 竹根轮流挪步；身子前倾，左右晃；手臂垂着前后摆
        st.update(lean=7.0, sway=1.2 * math.sin(ph), bob=0.015 * math.cos(2 * ph), eye=1.0, cover=0.0, flutter=0.5,
                  near=(158.0 + 14.0 * math.sin(ph), -18.0), far=(170.0 - 14.0 * math.sin(ph), -15.0),
                  top_sway=0.04 * math.sin(ph - 0.6))
        st["roots"] = [(max(0.0, math.sin(ph + k * 2 * math.pi / 5)) * 0.08,
                        0.07 * math.cos(ph + k * 2 * math.pi / 5)) for k in range(5)]
    elif anim == "shoot":
        # (前倾, 近手竹枝起始方向, 弯曲, 远手起始方向, 弯曲, 搭着竹刺, 竿顶后仰)
        P = [(-2.0, -20.0, -95.0, 150.0, -20.0, True, -0.03),
             (-3.5, -38.0, -132.0, 155.0, -18.0, True, -0.05),  # 拉满（预警时停在这）
             (9.0, 78.0, 8.0, 140.0, -24.0, False, 0.10),  # 放：竹枝向前弹直
             (6.0, 96.0, 22.0, 145.0, -22.0, False, 0.06),  # 过头往下
             (2.0, 60.0, -18.0, 150.0, -20.0, False, 0.0)][frame % 5]  # 回弹复位
        st.update(lean=P[0], near=(P[1], P[2]), far=(P[3], P[4]), spike=P[5], top_sway=P[6], eye=1.0, flutter=0.35)
    return st


# ================================================================ 组装
ROOTS = [(-30, 0.42), (40, 0.40), (110, 0.36), (180, 0.38), (250, 0.40)]  # (方位 deg, 伸出去的距离 m)


def build_bamboo_wraith():
    I, A = S.INK, S.ACCENT
    M = {
        "culm": K.toon("BWCulm", S.WASH["shilv"], edge=0.45, seed=91.0),
        "arm": K.toon("BWArm", S.WASH["shilv"], edge=0.5, seed=92.0),
        "node": B.flat_material("BWNode", I["nong"]),
        "mask": K.toon("BWMask", S.WASH["tenghuang"], edge=0.45, seed=93.0),
        "hollow": B.flat_material("BWHollow", I["jiao"]),
        "root": K.toon("BWRoot", S.WASH["zheshi"], edge=0.45, seed=94.0),
        "leaf": K.toon("BWLeaf", I["nong"], edge=0.0, wash=0.35, seed=95.0, bias=-0.30),  # 墨竹：浓墨叶为主
        "leaf2": K.toon("BWLeaf2", I["zhong"], edge=0.0, wash=0.35, seed=96.0, bias=-0.15),  # 少数重墨叶，分出浓淡
        "spike": K.toon("BWSpike", ramp=[S.PAPER, S.WASH["tenghuang"], S.ACCENT["zheshi"]], seed=97.0),
        "ink": B.flat_material("BWInk", I["jiao"]),
    }
    eye = B.emissive_material("BWEye", EYE_HEX, 1.0)
    root = B.empty("BWRoot")
    yaw = K.yaw_pivot("BWYaw", root, -20)
    body = B.empty("BWBody", yaw)  # 前倾、晃动绕根团转
    parts = {"root": root, "body": body, "M": M, "obs": {}}
    obj = B.mesh_object

    def dyn(name, mat, line, parent=body):
        ob = obj(name, lambda bm: bmesh.ops.create_cube(bm, size=0.01), mat, line, parent, sharp_deg=0)
        parts["obs"][name] = ob
        return ob

    # 根团 + 五条根（每帧重建）
    obj("BWKnot", K.ellipsoid((0.22, 0.20, 0.15), 18, 10), M["root"], "outer", root, loc=(0, 0, 0.14))
    for k in range(len(ROOTS)):
        dyn(f"BWRootLeg{k}", M["root"], "inner", root)
    # 三根竹竿 + 竹节
    for k in range(3):
        dyn(f"BWCulm{k}", M["culm"], "outer")
        dyn(f"BWNodes{k}", M["node"], "none")
    # 手臂（竹枝）+ 竹节
    for nm in ("Near", "Far"):
        dyn(f"BWArm{nm}", M["arm"], "inner")
        dyn(f"BWArmNodes{nm}", M["node"], "none")
    # 竹叶：竿顶三簇 + 两只手 + 几处节上的小簇（浓墨 / 淡墨，不描线）
    for nm in ("Top0", "Top1", "Top2", "HandNear", "HandFar", "Node0", "Node1", "Cover"):
        dyn(f"BWLeaves{nm}", M["leaf2"] if nm in ("Top1", "Node1", "HandFar") else M["leaf"], "none")
    # 竹刺（拉弓时搭在近手竹枝梢上）
    dyn("BWSpike", M["spike"], "inner")
    # 脸：一截粗竹筒套在中竿上，顶上斜切（露出焦墨空心），一道竹节当眉，两道焦墨眼缝 + 发光的眼
    head = B.empty("BWHead", body)
    parts["head"] = head

    def mask_build(bm, r=MASK_R, h0=-0.26, segs=28):
        rings_lo, rings_hi = [], []
        for i in range(segs):
            th = 2 * math.pi * i / segs
            x, y = r * math.cos(th), r * math.sin(th) * 0.92
            z_top = 0.16 + 0.13 * math.sin(th)  # 斜切：前低（-Y）后高（+Y）
            rings_lo.append(bm.verts.new((x, y, h0)))
            rings_hi.append(bm.verts.new((x, y, z_top)))
        for i in range(segs):
            j = (i + 1) % segs
            bm.faces.new((rings_lo[i], rings_lo[j], rings_hi[j], rings_hi[i]))
        bm.faces.new(list(reversed(rings_lo)))
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)

    def rim_build(bm, segs=28):  # 斜切面上的竹壁截面：一圈淡色的环
        outer, inner = [], []
        for i in range(segs):
            th = 2 * math.pi * i / segs
            c, s_ = math.cos(th), math.sin(th) * 0.92
            z = 0.16 + 0.13 * math.sin(th)
            outer.append(bm.verts.new((MASK_R * c, MASK_R * s_, z)))
            inner.append(bm.verts.new((MASK_R * 0.70 * c, MASK_R * 0.70 * s_, z - 0.004)))
        for i in range(segs):
            j = (i + 1) % segs
            bm.faces.new((outer[i], outer[j], inner[j], inner[i]))
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)

    def cut_build(bm, r=MASK_R * 0.70, segs=28):  # 空心：焦墨，略缩进去
        vs = []
        for i in range(segs):
            th = 2 * math.pi * i / segs
            vs.append(bm.verts.new((r * math.cos(th), r * math.sin(th) * 0.92, 0.15 + 0.13 * math.sin(th))))
        bm.faces.new(vs)

    obj("BWMask", mask_build, M["mask"], "outer", head, sharp_deg=0)
    obj("BWMaskRim", rim_build, M["mask"], "inner", head, sharp_deg=0)
    obj("BWMaskCut", cut_build, M["hollow"], "none", head)
    obj("BWMaskNode", K.tube_build([Vector((0, 0, 0.040)), Vector((0, 0, 0.065)), Vector((0, 0, 0.090))],
                                   lambda t: MASK_R * 1.08, 28, flat=0.92), M["node"], "inner", head)
    eyes = B.empty("BWEyes", head)
    parts["eyes"] = eyes
    for sx in (-1, 1):
        th = math.radians(-90 + 30 * sx)  # 竹筒表面上，正前方左右各偏 30°
        loc = Vector((MASK_R * math.cos(th), MASK_R * math.sin(th) * 0.92, -0.02))
        rot = (0, math.radians(-16 * sx), th + math.pi / 2)
        obj(f"BWEyeSlit{sx:+d}", K.ellipsoid((0.074, 0.024, 0.030), 14, 8), M["hollow"], "none", head, loc=loc, rot=rot)
        obj(f"BWEye{sx:+d}", K.ellipsoid((0.058, 0.018, 0.020), 14, 8), eye, "none", eyes,
            loc=loc * 1.06, rot=rot)
    obj("BWMouth", K.ellipsoid((0.085, 0.02, 0.012), 12, 6), M["hollow"], "none", head,
        loc=(0, -MASK_R * 0.93, -0.16), rot=(0, 0, 0))
    sock_eyes = B.empty("BWSocketEyes", head, loc=(0, -MASK_R - 0.02, -0.02))
    muzzle = B.empty("BWSocketMuzzle", body)
    parts["muzzle"] = muzzle
    sockets = {"eyes": sock_eyes, "muzzle": muzzle, "feet": B.empty("BWFeet", root)}
    parts["sockets"] = sockets
    pose_bamboo_wraith(parts, "idle", 0, 4)
    return root, parts, sockets


def _set(parts, name, build, visible=True):
    ob = parts["obs"][name]
    ob.hide_render = not visible
    if visible:
        K.replace_mesh(ob, build)


def pose_bamboo_wraith(parts, anim, frame, n):
    st = _state(anim, frame, n)
    ph = st["ph"]
    body = parts["body"]
    body.location = (0, 0, st["bob"])
    body.rotation_euler = (math.radians(-st["lean"]), math.radians(st["sway"]), 0)
    # 根：从根团伸向地面，挪步的根抬起、往前挪
    for k, (az, dist) in enumerate(ROOTS):
        lift, fwd = st["roots"][k]
        a = math.radians(az)
        out = Vector((math.cos(a), math.sin(a), 0))
        p0 = Vector((0, 0, 0.16)) + out * 0.12
        tip = out * dist + Vector((0, -fwd, 0.015 + lift))
        mid = p0.lerp(tip, 0.5) + Vector((0, 0, 0.10 + lift * 0.6))
        pts = K.curve_points(p0, tip, bend=mid - p0.lerp(tip, 0.5), n=7)
        _set(parts, f"BWRootLeg{k}", K.tube_build(pts, lambda t: 0.065 * (1 - t) ** 0.8 + 0.008, 8))
    # 三根竹竿：中竿最高（脸套在上面），左后一根、右前一根矮些
    ts = st["top_sway"]
    # 竹竿在模型 Y 方向错开（E 向画面里左右分得开）：中竿、后竿（高）、前竿（矮，在脸下）
    culms = [((0.0, 0.0, 0.18), (ts * 0.6, -0.04 - ts, 2.62), 0.082, 0.064),
             ((0.05, 0.16, 0.18), (0.10 + ts * 0.4, 0.42 - ts * 0.8, 2.34), 0.070, 0.052),
             ((-0.05, -0.15, 0.18), (-0.08 + ts * 0.5, -0.36 - ts * 0.9, 1.50), 0.064, 0.050)]
    paths = []
    for k, (a, b, r0, r1) in enumerate(culms):
        pts = K.curve_points(a, b, bend=Vector((0.02 * (k - 1), -0.04 - ts * 0.3, 0)), n=12)
        paths.append(pts)
        c, nd = _culm_builds(pts, r0, r1, node_every=0.32, node_from=0.30 + 0.08 * k)
        _set(parts, f"BWCulm{k}", c)
        _set(parts, f"BWNodes{k}", nd)
    # 脸：跟着中竿，取 MASK_Z 处的位置和切线
    c0 = paths[0]
    i = min(range(len(c0)), key=lambda j: abs(c0[j].z - MASK_Z))
    tan = (c0[min(i + 1, len(c0) - 1)] - c0[max(i - 1, 0)]).normalized()
    head = parts["head"]
    head.location = c0[i]
    head.rotation_mode = "QUATERNION"
    head.rotation_quaternion = Vector((0, 0, 1)).rotation_difference(tan) @ Matrix.Rotation(math.radians(-28), 4, "Z").to_quaternion()
    parts["eyes"].scale = (1.0, 1.0, max(0.05, st["eye"]))
    # 手臂：肩在脸下，竹枝按（起始方向, 弯曲）弯；近手在镜头一侧（-X）
    arms = {}
    for nm, (a0, kap), sx, side in (("Near", st["near"], -1, st["near_side"]), ("Far", st["far"], 1, st["far_side"])):
        sh = Vector((0.16 * sx, -0.02, 1.50))
        pts = _arc_points(sh, a0, kap, 1.10, n=12, side=side)
        arms[nm] = pts
        c, nd = _culm_builds(pts, 0.046, 0.030, node_every=0.40, node_from=0.30)
        _set(parts, f"BWArm{nm}", c)
        _set(parts, f"BWArmNodes{nm}", nd)
        tip, pre = pts[-1], pts[-3]
        d = (tip - pre).normalized()
        _set(parts, f"BWLeavesHand{nm}", _spray(tip, d, 5, 0.44, 0.095, 0.80, 0.30, seed=3.0 + sx,
                                                 phase=ph, flutter=st["flutter"]))
    # 竿顶叶簇
    for k, pts in enumerate(paths):
        tip = pts[-1]
        d = Vector((0.0, (0.10, 0.6, -0.5)[k], 1.0))
        _set(parts, f"BWLeavesTop{k}", _spray(tip, d, 8 if k == 0 else 7, 0.54, 0.105, 1.50, 0.75, seed=7.0 + k * 2,
                                               phase=ph + k, flutter=st["flutter"]))
    # 节上的小簇（向后下垂）
    for k, (ci, t, dd) in enumerate(((1, 0.66, Vector((0.0, 0.8, 0.3))), (0, 0.42, Vector((0.0, 0.6, 0.15))))):
        p = paths[ci][int(t * 11)]
        _set(parts, f"BWLeavesNode{k}", _spray(p, dd, 4, 0.36, 0.075, 0.9, 0.6, seed=13.0 + k, phase=ph + 2,
                                               flutter=st["flutter"]))
    # 藏身时挡在脸前的一簇叶（从近手竹枝的中段垂到脸前）
    cov = st["cover"]
    if cov > 0:
        base = c0[i] + Vector((-0.30, -0.10, 0.34))
        _set(parts, "BWLeavesCover", _spray(base, Vector((-0.15, -0.35, -1.0)), 6, 0.50, 0.10, 0.85, 0.10, seed=21.0,
                                            phase=ph, flutter=0.15), True)
    else:
        _set(parts, "BWLeavesCover", None, False)
    # 竹刺：拉弓时搭在近手竹枝梢上，沿竹枝方向，尖朝前
    near = arms["Near"]
    tip, pre = near[-1], near[-2]
    d = (tip - pre).normalized()
    if st["spike"]:
        a, b = tip - d * 0.10, tip + d * 0.40  # 竹刺顺着竹枝梢搭着，削尖的一头朝外
        _set(parts, "BWSpike", K.tube_build(K.curve_points(a, b, n=5), lambda t: 0.034 * (1 - t) ** 0.55 + 0.002, 8))
        parts["muzzle"].location = b
    else:
        _set(parts, "BWSpike", None, False)
        parts["muzzle"].location = tip + d * 0.06
    bpy.context.view_layer.update()
