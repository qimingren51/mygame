"""九尾（精修三维，夜主）：巨大的白狐，九条尾巴像扇面一样展开，尾尖染着青火。

设定（LORE 附录）：“青丘之山……有兽焉，其状如狐而九尾。”古书里它吃人，也是涂山的祥瑞；长夜里，它是狐村所有小狐狸的母亲。
外形（世界观会话）：巨大的白狐，身形修长，九条尾巴像扇面一样展开，尾尖染着青火。额心一点青，眼睛也是青的。
脸上不画红（和赤面狐分开）。主色月白、青；美而凛，是护崽的母亲，凶起来不留情。
造型：借用赤面狐（models/fox_v2.py：同一族）的骨架、躯干、头、耳、腿和尾巴的做法，整体放大、拉高拉长（修长）；
毛是月白（暗部偏青灰），耳背、耳尖淡青灰；没有朱砂脸谱、没有红绳；额心一簇青火形的印记（发光），眼是青的丹凤眼（发光），
墨勾眼线、竖瞳；颊后一圈白毛炸开（像披风领）。九条尾巴从尾根扇形展开（前后错开几层），尾尖一截是青火（发光），
火舌往外飘。
动画（只画 E）：
  move   8 帧：赤面狐的小跑步态，九尾张着扇面、一条条带着波轻轻摆。
  sweep  6 帧（不循环，2 帧蓄力）：0 伏低、九尾往上收拢，1 九尾从背上往前拱过来、尾火大盛（预警期间停在这一帧），
         2 往前下方一扫而过，3 扫到身前低处，4、5 收回扇面。
  summon 4 帧（不循环）：昂头，九尾张到最开、尾尖的青火一盏盏腾起来（召狐火），3 稍落。
帧 640²（2 倍），锚点 (0.5, 0.8)（大妖物）。挂点 eyes。

    root, parts, sockets = build_boss()
    pose_boss(parts, "move", i, 8)
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import bpy
import numpy as np
from mathutils import Matrix, Vector

ART = Path(__file__).resolve().parents[1]
for p in (ART, ART / "models", ART / "post"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
from style import bstyle as B  # noqa: E402
from style import style as S  # noqa: E402
import kit as K  # noqa: E402
import v2kit as V2  # noqa: E402
import enemy_design as DZ  # noqa: E402
import fox_v2 as FX  # noqa: E402

I = S.INK
EYE = "#5FE8D6"  # 青眼
EYE_HOT = "#E6FFFB"
FIRE = "#6FF2D8"  # 尾尖的青火
FIRE_HOT = "#E8FFF9"
SCALE = (1.9, 2.05, 2.15)  # 模型坐标的 (左右, 前后, 高)：整体放大，拉长、拉高（修长）
WHITE = "#F6F8F8"
# 月白的毛（d 从暗到亮）：暗部偏青灰、亮部近白
FUR_STOPS = [(0.00, "#323A46"), (0.16, "#4A5564"), (0.30, "#66717F"), (0.44, "#86909C"), (0.56, "#A4AEB8"),
             (0.68, "#C2CAD0"), (0.80, "#DCE2E4"), (0.90, "#EDF1F1"), (1.00, WHITE)]
EAR_STOPS = [(0.0, "#2C3440"), (0.5, "#56626E"), (0.85, "#7E8A96"), (1.0, "#9AA6B0")]  # 耳背、耳尖：淡青灰
FIRE_STOPS = [(0.0, "#3FB8A6"), (0.45, FIRE), (1.0, FIRE_HOT)]
RIM = S.mix("#DDF6F2", I["qing"], 0.15)
N_TAILS = 9


def fur_material(name, seed, zone=True, streak=0.16, bias=-0.3, rim=0.6):
    return V2.paint_material(name, FUR_STOPS, wash=0.24, wash_scale=2.6, seed=seed, shade_attr="zone" if zone else None,
                             shade_gain=1.0, streak=streak, streak_scale=(4.0, 60.0), rim_hex=RIM, rim=rim,
                             rim_power=2.3, value_var=0.04, edge=0.22, bias=bias)


def _world_to_design(w):
    right, up, _ = B.camera_basis()
    return 25.0 * w.dot(right), 25.0 * w.dot(up)


# ================================================================ 组装
def build_boss():
    root = B.empty("JWRoot")
    scale = B.empty("JWScale", root)
    scale.scale = SCALE
    body = B.empty("JWBody", scale)
    M_fur = fur_material("JWFur", 3.0, bias=-0.06)
    M_leg = fur_material("JWFurLeg", 5.0, bias=-0.06)
    M_far = fur_material("JWFurFar", 6.0, bias=-0.36, rim=0.35)
    M_head = fur_material("JWFurHead", 7.0, bias=-0.02)
    M_tail = fur_material("JWFurTail", 9.0, streak=0.24, bias=-0.04)
    M_ear = V2.paint_material("JWEar", EAR_STOPS, wash=0.2, seed=11.0, rim_hex=RIM, rim=0.5, edge=0.1)
    M_paw = V2.paint_material("JWPaw", [(0.0, "#2A323C"), (0.5, "#5A6674"), (1.0, "#8A96A2")], wash=0.2, seed=12.0,
                              edge=0.1)
    M_cream = V2.paint_material("JWCream", [(0.0, "#9AA6B0"), (0.4, "#D6DEE2"), (0.7, "#EEF2F2"), (1.0, WHITE)],
                                wash=0.2, seed=14.0, edge=0.1)
    # 尾尖一截：青火（不用发光材质：发光层按物体分，整条尾巴都会算进去；这里走 AOV，只有尾尖亮）
    M_fire = V2.paint_material("JWTailFire", FIRE_STOPS, wash=0.2, seed=10.0, edge=0.0, bias=0.35)
    V2.add_glow_const(M_fire, 1.0)
    M_eye = B.emissive_material("JWEye", EYE, 1.0)
    M_hot = B.emissive_material("JWEyeHot", EYE_HOT, 1.0)
    M_mark = B.emissive_material("JWMark", EYE, 1.0)
    M_jiao = B.flat_material("JWJiao", I["jiao"])
    M_flame = V2.brush_material("JWFlame", FIRE_STOPS, alpha=0.95, edge_soft=0.3, edge_dark=0.0, streak=0.35,
                                streak_from=0.45, scale=(3.0, 8.0), fade_from=0.55, seed=31.0, glow=1.0, glow_to=0.9,
                                glow_tip=0.5, comb=5.0)
    parts = {"root": root, "scale": scale, "body": body}
    FX.build_torso(body, M_fur)
    # 胸前一蓬白毛、腹下一排毛簇
    roots, dirs, lens, ws = [], [], [], []
    rng = np.random.default_rng(5)
    for k in range(18):
        a = rng.uniform(-0.9, 0.9)
        zc = rng.uniform(13.0, 23.0)
        roots.append(FX.d2m(13.2 - 0.2 * abs(a) - 0.08 * (22 - zc), zc, 0.12 * a))
        dirs.append(Vector((0.3 * a, -0.55, -0.85)))
        lens.append(rng.uniform(0.11, 0.18)); ws.append(rng.uniform(0.035, 0.05))
    for k in range(14):
        x = rng.uniform(-7.0, 7.0)
        roots.append(FX.d2m(x, 14.6 + 0.10 * abs(x), rng.uniform(-0.12, 0.12)))
        dirs.append(Vector((0, 0.35, -1))); lens.append(rng.uniform(0.07, 0.11)); ws.append(0.035)
    B.mesh_object("JWChestFur", FX.clumps_build(roots, dirs, lens, ws), M_cream, "none", body, sharp_deg=0)
    # 腿
    parts["legs"] = {}
    for far in (False, True):
        lat = 0.11 if far else -0.11
        for name, rootp, segs, rad in (("front", DZ.FOX_SHOULDER, DZ.FOX_FRONT_LEG, FX.LEG_R["front"]),
                                       ("hind", DZ.FOX_HIP, DZ.FOX_HIND_LEG, FX.LEG_R["hind"])):
            nm = f"JW{name.title()}{'Far' if far else 'Near'}"
            pts = [FX.d2m(x, y, lat) for x, y in DZ.fox_leg(rootp, segs)]
            ob = FX.leg_tube(nm, pts, [r * 0.92 for r in rad], [M_far if far else M_leg, M_paw], scale,
                             zones=lambda t: 1 if t > 0.88 else 0)
            paw = B.mesh_object(nm + "Paw", K.ellipsoid(FX.PAW_R), M_paw, "outer", scale)
            parts["legs"][(name, far)] = (ob, paw, lat, [r * 0.92 for r in rad])
    # 头（转轴在颈根），朝镜头转一点
    neck = FX.d2m(*DZ.FOX_NECK)
    head_piv = B.empty("JWHeadPivot", scale, loc=neck)
    head_yaw = B.empty("JWHeadYaw", head_piv, rot=(0, 0, math.radians(-12)))
    head = FX.build_head(head_yaw, M_head)
    # 颊后一圈白毛炸开（像披风领）
    roots, dirs, lens, ws = [], [], [], []
    for k in range(20):
        a = rng.uniform(-1, 1)
        roots.append(FX.d2m(12.2 + rng.uniform(-1.0, 1.8), 25.4 + rng.uniform(-1.6, 1.6), 0.14 * a) - neck)
        dirs.append(Vector((0.45 * a, 0.75, -0.5)))
        lens.append(rng.uniform(0.11, 0.18)); ws.append(rng.uniform(0.032, 0.048))
    B.mesh_object("JWCheekFur", FX.clumps_build(roots, dirs, lens, ws), M_cream, "none", head_yaw, sharp_deg=0)
    ear_n = FX.build_ear("JWEarNear", DZ.FOX_EAR_NEAR, head_yaw, M_head, M_cream, M_ear, neck)
    ear_f = FX.build_ear("JWEarFar", DZ.FOX_EAR_FAR, head_yaw, M_head, M_cream, M_ear, neck)
    ear_n.location.x -= 0.07
    ear_f.location.x += 0.09
    B.mesh_object("JWNose", K.ellipsoid((0.028, 0.022, 0.02)), M_jiao, "none", head_yaw,
                  loc=FX.d2m(*DZ.FOX_NOSE) - neck + Vector((0, -0.005, 0.004)))
    # 九条尾巴（每帧重建）：尾身白、尾尖一截青火（材质槽 1）
    tails = []
    for k in range(N_TAILS):
        t = B.mesh_object(f"JWTail{k}", lambda bm: None, [M_tail, M_fire], "outer", scale)
        tf = B.mesh_object(f"JWTailFur{k}", lambda bm: None, [M_tail, M_fire], "none", scale)
        bpy.data.collections[B.CONTOUR_COLLECTION].objects.link(tf)
        tails.append((t, tf))
    flames = V2.mesh_from_arrays("JWFlames", [(0, 0, 0), (0.001, 0, 0), (0, 0.001, 0)], [(0, 1, 2)], M_flame, "none",
                                 scale)
    parts.update(head_piv=head_piv, head_yaw=head_yaw, head=head, ear_n=ear_n, ear_f=ear_f, tails=tails, flames=flames,
                 neck=neck)
    # 脸：E 向静止姿态下按设计稿投到头上——墨勾的丹凤眼、青眼、竖瞳，额心一簇青火形的印记
    B.set_direction(root, "E")
    bpy.context.view_layer.update()
    tree = V2.bvh_world(head)

    def scr(pts):  # 赤面狐设计稿上头部的点 → 这里画面上的点（经过放大、转头）
        return [_world_to_design(head_yaw.matrix_world @ (FX.d2m(x, y) - neck)) for x, y in pts]
    V2.design_patch("JWEyeInk", tree, V2.closed_smooth(scr(DZ.FOX_EYE_INK), 60), M_jiao, head_yaw, lift=0.006,
                    spacing=0.5)
    V2.design_patch("JWEye", tree, V2.closed_smooth(scr(DZ.fox_eye_poly(1.0)), 40), M_eye, head_yaw, lift=0.007,
                    spacing=0.4)
    V2.design_patch("JWEyeHot", tree, V2.closed_smooth(scr(DZ.fox_eye_poly(0.5)), 28), M_hot, head_yaw, lift=0.008,
                    spacing=0.3)
    (ex, ey), hl, hh, tilt = DZ.FOX_EYE2
    a = math.radians(tilt)
    pupil = [(ex + x * math.cos(a) - y * math.sin(a), ey + x * math.sin(a) + y * math.cos(a))
             for x, y in ((0.10 * hl, 0.80 * hh), (-0.07 * hl, 0.0), (0.10 * hl, -0.78 * hh), (0.24 * hl, 0.0))]
    V2.design_patch("JWPupil", tree, V2.closed_smooth(scr(pupil), 24), M_jiao, head_yaw, lift=0.009, spacing=0.25)
    # 额心的青印：一簇往上挑的小火苗（三瓣）
    cx, cy = DZ._hx([(17.3, 33.0)])[0]  # 额心：两眼之上、眉心往上一点
    mark = [(cx + 0.75 * x, cy + 0.75 * y) for x, y in
            ((0.0, -0.7), (0.5, -0.05), (0.26, 0.55), (0.08, 1.25), (-0.16, 0.5), (-0.55, 0.8), (-0.5, -0.05))]
    V2.design_patch("JWMark", tree, V2.closed_smooth(scr(mark), 30), M_mark, head_yaw, lift=0.006, spacing=0.25)
    (fx, fy), fl, fh, ft = DZ.FOX_EYE_FAR
    inv = head_yaw.matrix_world.inverted()
    rot3 = inv.to_3x3()
    hits = V2.project_design(tree, scr([(fx, fy)]))
    if hits[0][0] is not None:
        p_ = inv @ hits[0][0]
        n_ = (rot3 @ hits[0][1]).normalized()
        B.mesh_object("JWEyeFar", K.ellipsoid((0.016, 0.018, 0.011)), M_eye, "none", head_yaw, loc=p_ + n_ * 0.004)
    sock = B.empty("JWSocketEyes", head_yaw)
    sock.location = FX.d2m(ex * 0.7 + fx * 0.3, ey * 0.7 + fy * 0.3) - neck
    B.set_direction(root, "S")
    parts["sockets"] = {"eyes": sock}
    bpy.context.view_layer.update()
    return root, parts, parts["sockets"]


# ================================================================ 姿态
# 九条尾巴的扇面（move 时）：根部的方向（度，从 +x 逆时针）、每节弯多少、离镜头（米，负 = 近）、长短
FAN = [(92, -0.45, -0.22, 0.97), (101.5, -0.6, 0.16, 0.98), (111, -0.75, -0.14, 0.97), (120.5, -0.9, 0.22, 0.95),
       (130, -1.0, -0.06, 0.91), (139.5, -1.1, 0.28, 0.86), (149, -1.2, 0.08, 0.78), (158.5, -1.3, 0.32, 0.7),
       (168, -1.4, 0.18, 0.62)]  # 扇面：尾巴从尾根往上、往后一路排开，各自只略往上弯（不然九条都卷成一束）；后面的短（帧宽有限）


def tail_layout(anim, frame, n):
    """每条尾巴：(根部方向, 每节弯, 波幅, 相位, 长度倍数, 炸毛, 火的大小)。"""
    ph = 2 * math.pi * frame / max(n, 1)
    out = []
    for k, (ang, curl, lat, ln) in enumerate(FAN):
        if anim == "move":
            out.append((ang + 3.0 * math.sin(ph + 0.6 * k), curl, 5.0, ph + 0.5 * k, ln, False, 1.0))
        elif anim == "sweep":
            # 0 往上收拢；1 从背上往前拱过来（预警时停在这）；2 往前下方扫；3 扫到身前低处；4、5 收回扇面
            s = (k - 4) / 4.0
            T = [(116 + 22 * s, -3.0, 1.0, 1.15), (92 + 26 * s, -6.4, 1.05, 1.6), (52 + 26 * s, -6.0, 1.05, 1.5),
                 (18 + 26 * s, -3.6, 1.0, 1.2), (112 + 50 * s, -4.0, 0.98, 1.0), (ang - 4, curl, ln, 1.0)][frame]
            a0, cu, lk, fire = T
            out.append((a0, cu, 2.0, ph + 0.4 * k, ln * lk, frame in (1, 2), fire))
        else:  # summon：张到最开、尾尖青火一盏盏腾起来
            spread = [0.6, 1.12, 1.16, 1.06][frame]
            a0 = min(145 + (ang - 145) * spread, 176.0)  # 最后面几条别甩出画（帧左边）
            fire = [1.2, 1.6, 1.9, 1.4][frame]
            ln2 = ln * (0.92 if k < 5 else 0.72)  # 后面几条短一点（别出画）
            out.append((a0 - 6 * (frame in (1, 2)), curl * 0.8, 3.0, ph + 0.5 * k, ln2, frame in (1, 2), fire))
    return out


def pose_boss(parts, anim, frame, n):
    if anim == "move":
        pose = DZ.fox_move_pose(frame, n)
    elif anim == "sweep":
        F = [  # body(dx, dy, rot, sx, sy), head(rot, dx, dy), ears, 前腿, 后腿
            ((-1.0, -2.6, -6, 1.02, 0.97), (-8, 0.6, -1.0), 22, [-22, 40, -10], [46, -70, 28]),
            ((-1.8, -4.2, -9, 1.04, 0.94), (-14, 1.2, -1.8), 34, [-34, 56, -20], [60, -90, 42]),
            ((1.6, -1.0, 6, 1.04, 0.97), (6, 0.8, -1.0), 24, [26, 24, 20], [20, -60, 20]),
            ((2.0, -1.6, 8, 1.03, 0.97), (10, 0.8, -1.4), 18, [30, 20, 16], [24, -62, 22]),
            ((0.8, -0.8, 2, 1.0, 1.0), (2, 0.4, -0.6), 8, [8, 10, 20], [26, -52, 10]),
            ((0.0, 0.0, 0, 1.0, 1.0), (0, 0.0, 0.0), 0, None, None),
        ]
        body, head, ears, fl, hl = F[frame]
        rest_f = [sg[1] for sg in DZ.FOX_FRONT_LEG]
        rest_h = [sg[1] for sg in DZ.FOX_HIND_LEG]
        fl = fl or rest_f
        hl = hl or rest_h
        pose = {"body": body, "head": head, "ears": ears,
                "legs": {("front", False): fl, ("front", True): [fl[0] - 8, fl[1] + 4, fl[2] - 6],
                         ("hind", False): hl, ("hind", True): [hl[0] + 6, hl[1] - 4, hl[2] + 4]}}
    else:  # summon：昂头、身子略往后仰
        R = [((-0.6, 0.6, 4, 1.0, 1.0), (-10, 0.0, 0.6), -6), ((-1.0, 1.4, 8, 1.0, 1.02), (-20, -0.4, 1.2), -12),
             ((-1.0, 1.6, 9, 1.0, 1.03), (-24, -0.4, 1.4), -14), ((-0.6, 0.8, 5, 1.0, 1.01), (-14, -0.2, 0.8), -8)]
        body, head, ears = R[frame]
        rest_f = [sg[1] for sg in DZ.FOX_FRONT_LEG]
        rest_h = [sg[1] for sg in DZ.FOX_HIND_LEG]
        lift = [0, 10, 12, 6][frame]
        fl = [rest_f[0] + lift, rest_f[1] - lift * 0.5, rest_f[2]]
        pose = {"body": body, "head": head, "ears": ears,
                "legs": {("front", False): fl, ("front", True): [fl[0] - 6, fl[1] + 4, fl[2]],
                         ("hind", False): [rest_h[0] - 6, rest_h[1] - 8, rest_h[2] + 6],
                         ("hind", True): [rest_h[0] - 2, rest_h[1] - 6, rest_h[2] + 4]}}
    body = parts["body"]
    dx, dy, rot, sx, sy = pose["body"]
    piv = FX.d2m(*DZ.FOX_PIVOT)
    R = Matrix.Rotation(math.radians(-rot), 4, "X")
    Sc = Matrix.Diagonal((1.0, sx, sy, 1.0))
    T = Matrix.Translation(piv + Vector((0, -dx / 25.0, dy / FX.VZ)))
    Mb = T @ R @ Sc @ Matrix.Translation(-piv)
    body.matrix_basis = Mb
    # 腿（同赤面狐：站地的腿收短，脚不陷进地里）
    for (name, far), (ob, paw, lat, rad) in parts["legs"].items():
        segs = DZ.FOX_FRONT_LEG if name == "front" else DZ.FOX_HIND_LEG
        root2 = DZ.FOX_SHOULDER if name == "front" else DZ.FOX_HIP
        r3 = Mb @ FX.d2m(*root2, lat)
        angs = [a + rot for a in pose["legs"][(name, far)]]
        angs = DZ.fox_leg_ground(FX._to2(r3), segs, angs, name)
        pts = [FX.d2m(x, y, lat) for x, y in DZ.fox_leg(FX._to2(r3), segs, angs)]
        dense = []
        for a_, b_ in zip(pts[:-1], pts[1:]):
            for t in np.linspace(0, 1, 6, endpoint=False):
                dense.append(a_.lerp(b_, t))
        dense.append(pts[-1])
        rr = np.interp(np.linspace(0, 1, len(dense)), np.linspace(0, 1, len(rad)), rad)
        K.replace_mesh(ob, K.tube_build(dense, lambda t, rr=rr: float(np.interp(t, np.linspace(0, 1, len(rr)), rr)), 14,
                                        zones=lambda t: 1 if t > 0.88 else 0))
        zs = [0.42 * max(0.0, -v.normal.y) ** 1.5 - 0.18 * max(0.0, v.normal.y) for v in ob.data.vertices]
        B.set_point_attr(ob, "zone", zs)
        tipv = (pts[-1] - pts[-2]).normalized()
        paw.location = pts[-1] + Vector((0, -0.045, -0.012))
        paw.rotation_euler = (math.atan2(tipv.z, -tipv.y) * 0.4, 0, 0)
    # 头
    hrot, hdx, hdy = pose["head"]
    hp = parts["head_piv"]
    hp.location = Mb @ parts["neck"] + Vector((0, -hdx / 25.0, hdy / FX.VZ))
    hp.rotation_euler = (math.radians(-(hrot + rot)), 0, 0)
    e = math.radians(-pose["ears"])
    for ear in (parts["ear_n"], parts["ear_f"]):
        ear.rotation_euler = (e, 0, 0)
    # 九尾：从尾根扇形展开；尾尖青火的火舌（扁带）往外飘
    root_t = FX._to2(Mb @ FX.d2m(*DZ.FOX_TAIL_ROOT))
    flames = []
    for k, ((t_ob, tf_ob), (ang, curl, wave, ph, ln, puff, fire)) in enumerate(
            zip(parts["tails"], tail_layout(anim, frame, n))):
        lat = FAN[k][2]
        c2 = DZ.fox_tail_curve(root_t, angle=ang + rot, curl=curl, wave=wave, ph=ph, n=18,
                               length=DZ.FOX_TAIL_LEN * 0.92 * ln)
        back = c2[0] - (c2[1] - c2[0]) / np.linalg.norm(c2[1] - c2[0]) * 1.2
        c2 = np.vstack([back, c2])
        cm = [FX.d2m(x, y, lat + 0.01 * j / len(c2)) for j, (x, y) in enumerate(c2)]
        tube, fur = FX._tail_geom(cm, 0.82 if puff else 0.62, seed=21 + k)
        K.replace_mesh(t_ob, tube)
        K.replace_mesh(tf_ob, fur)
        # 火舌：尾尖往外三条，略往上飘、随相位抖
        tip = np.asarray(c2[-1])
        d = np.asarray(c2[-1]) - np.asarray(c2[-3])
        d /= np.linalg.norm(d) + 1e-9
        base_a = math.degrees(math.atan2(d[1], d[0]))
        for j, (da, lj) in enumerate(((-24.0, 0.8), (0.0, 1.0), (22.0, 0.75))):
            a0 = base_a + da * 0.6 + 8.0 * math.sin(ph * 1.7 + j)
            pts, w = [], []
            x, y = tip - d * 1.2
            L = 5.5 * fire * lj
            for q in np.linspace(0, 1, 9):
                aa = math.radians(a0 + (90.0 - a0) * 0.35 * q * q + 10.0 * math.sin(ph + 3 * q + j))
                pts.append((x, y))
                x += math.cos(aa) * L / 8
                y += math.sin(aa) * L / 8
                w.append(2.0 * fire ** 0.5 * (1 - q) ** 0.8 + 0.15)
            P, Wm, Sd = V2.design_strip(np.asarray(pts), np.asarray(w), lat - 0.03)
            flames.append(V2.strip_arrays(P, Wm, Sd))
    Vf, Ff, Af = V2.merge_arrays(flames)
    K.replace_mesh(parts["flames"], V2.arrays_build(Vf, Ff), smooth=False, attrs=Af)
    bpy.context.view_layer.update()
