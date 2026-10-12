"""石将：活过来的石雕将军。刻出来的甲片（平直着色的多面体）、兜鍪上一束赭石盔缨，右手（-X）持关刀斜举；
水墨石色（清墨/淡墨/重墨），赭石点缀（盔缨、腰带、刀杆），身上有裂纹（边标记 + 暗示轮廓线）。
眼睛 EYE['stonelord']，藏在盔下的焦墨面甲缝里。动画 move：8 帧缓慢的重踏（一腿高抬、落地），上身晃。
帧 FRAME["elite"]（160px）。只渲染 E。游戏碰撞半径 28 单位 → 占地直径约 2.2 米。
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import bmesh
import bpy
from mathutils import Vector

ART = Path(__file__).resolve().parents[1]
for p in (ART, ART / "models"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
from style import bstyle as B  # noqa: E402
from style import style as S  # noqa: E402
import kit as K  # noqa: E402


def _mark_cracks(ob, seed, keep=0.35, min_deg=12.0):
    """随机挑一部分棱标成 Freestyle 边标记，当作石头裂纹。"""
    import numpy as np
    me = ob.data
    rng = np.random.default_rng(seed)
    ef: dict = {}
    for poly in me.polygons:
        for ek in poly.edge_keys:
            ef.setdefault(ek, []).append(poly.normal.copy())
    attr = me.attributes.get("freestyle_edge") or me.attributes.new("freestyle_edge", "BOOLEAN", "EDGE")
    vals = []
    for e in me.edges:
        ns = ef.get(tuple(sorted(e.vertices)), [])
        ang = math.degrees(ns[0].angle(ns[1])) if len(ns) == 2 else 0.0
        vals.append(ang > min_deg and rng.random() < keep)
    attr.data.foreach_set("value", vals)


def _blade_build():
    """关刀刀头：长而弯的偃月刃，刃口朝前（局部 -Y）向上弯出刀尖，刀背直、带一个回钩。局部 z 沿刀杆向上。"""
    def build(bm):
        n = 11
        rows = []
        for i in range(n):
            t = i / (n - 1)
            z = 0.66 * t
            yb = 0.04 + 0.10 * t * t  # 刀背略向后弯
            yf = -0.06 - 0.20 * math.sin(math.pi * min(t / 0.85, 1.0)) ** 0.8 + 0.20 * max(0.0, t - 0.85) / 0.15
            if t > 0.85:
                yf = yb - (yb - yf) * (1 - (t - 0.85) / 0.15)  # 收成刀尖
            rows.append((yf, yb, z))
        vf = [[bm.verts.new((th, yf, z)) for yf, yb, z in rows] for th in (-0.018, 0.018)]
        vb = [[bm.verts.new((th * 2, yb, z)) for yf, yb, z in rows] for th in (-0.018, 0.018)]
        for i in range(n - 1):
            for s_ in (0, 1):
                bm.faces.new((vf[s_][i], vf[s_][i + 1], vb[s_][i + 1], vb[s_][i]))
            bm.faces.new((vf[0][i], vf[1][i], vf[1][i + 1], vf[0][i + 1]))
            bm.faces.new((vb[0][i + 1], vb[1][i + 1], vb[1][i], vb[0][i]))
        bm.faces.new((vf[0][0], vb[0][0], vb[1][0], vf[1][0]))
        bm.faces.new((vf[1][-1], vb[1][-1], vb[0][-1], vf[0][-1]))
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    return build


def build_stonelord():
    I, A = S.INK, S.ACCENT
    stone = K.toon("LordStone", ramp=[I["qing"], I["dan"], I["zhong"]], wash=0.35, edge=0.6, seed=71.0)
    ochre = K.toon("LordOchre", A["zheshi"], seed=72.0)
    ink = B.flat_material("LordInk", I["jiao"])
    eye = B.emissive_material("LordEye", S.EYE["stonelord"], 1.0)
    root = B.empty("LordRoot")
    yaw = K.yaw_pivot("LordYaw", root, -12, loc=(0.22, 0.05, 0))
    body = B.empty("LordBody", yaw)
    parts = {"root": root, "body": body}
    obj = B.mesh_object

    def facet(name, build, mat, parent, loc=(0, 0, 0), rot=(0, 0, 0), scale=(1, 1, 1), crack=None):
        ob = obj(name, build, mat, "outer", parent, loc=loc, rot=rot, scale=scale, smooth=False)
        if crack is not None:
            _mark_cracks(ob, crack)
        return ob

    pelvis = B.empty("LordPelvis", body, loc=(0, 0, 1.05))
    parts["pelvis"] = pelvis
    upper = B.empty("LordUpper", pelvis, rot=(math.radians(6), 0, 0))
    parts["upper"] = upper
    # 胸甲（八棱，平直着色像刻出来的）、腰带、裙甲
    facet("LordCuirass", B.lathe([(0.30, 0.0), (0.36, 0.20), (0.44, 0.48), (0.46, 0.66), (0.30, 0.80), (0.12, 0.86)], 8,
                                 scale_y=0.72), stone, upper, rot=(0, 0, math.radians(22.5)), crack=1)
    obj("LordBelt", B.lathe([(0.32, -0.04), (0.34, 0.03), (0.32, 0.10)], 16, scale_y=0.75), ochre, "inner", upper,
        sharp_deg=0)
    for i, ang in enumerate((-90, -40, 40, 90, 140, 220)):
        a = math.radians(ang)
        plate = obj(f"LordTasset{i}", K.ellipsoid((0.17, 0.035, 0.24), 6, 4), stone, "outer", pelvis,
                    loc=(0.34 * math.cos(a), 0.26 * math.sin(a), -0.20),
                    rot=(math.radians(-12) * -math.sin(a), math.radians(12) * math.cos(a), a + math.radians(90)),
                    smooth=False)
        _mark_cracks(plate, 10 + i, keep=0.5)
    # 兜鍪、面甲、盔缨
    head = B.empty("LordHead", upper, loc=(0, -0.04, 0.98), rot=(math.radians(-8), 0, math.radians(-48)))
    parts["head"] = head
    facet("LordHelm", B.lathe([(0.0, 0.34), (0.10, 0.32), (0.19, 0.22), (0.21, 0.08), (0.22, 0.02), (0.23, 0.0)], 8),
          stone, head, crack=3)
    facet("LordFace", K.ellipsoid((0.16, 0.15, 0.17), 8, 6), stone, head, loc=(0, -0.02, -0.12))
    obj("LordVisor", K.ellipsoid((0.15, 0.05, 0.045), 10, 6), ink, "inner", head, loc=(0, -0.165, -0.11))
    sock = K.slit_eyes("Lord", head, Vector((0, -0.205, -0.11)), 0.11, (0.048, 0.014, 0.018), eye, tilt_deg=-10)
    plume = K.curve_points((0, 0.02, 0.33), (0, 0.42, 0.62), bend=Vector((0, -0.05, 0.16)), n=9)
    obj("LordPlume", K.tube_build(plume, K.bushy(0.07, peak=0.3), 10), ochre, "outer", head)
    # 肩甲、手臂
    for sx, nm in ((1, "L"), (-1, "R")):
        sh = B.empty(f"LordShoulder{nm}", upper, loc=(0.44 * sx, 0, 0.70))
        facet(f"LordPauldron{nm}", B.lathe([(0.0, 0.16), (0.16, 0.12), (0.24, 0.0), (0.25, -0.10)], 7), stone, sh,
              rot=(0, math.radians(-25 * sx), 0), crack=4 + sx)
        K.limb(f"LordArmU{nm}", (0.05 * sx, 0, -0.05), (0.08 * sx, -0.18, -0.42), 0.12, 0.10, stone, "outer", sh)
        K.limb(f"LordArmF{nm}", (0.08 * sx, -0.18, -0.42), (0.02 * sx, -0.42, -0.50), 0.10, 0.09, stone, "outer", sh)
        obj(f"LordHand{nm}", K.ellipsoid((0.08, 0.09, 0.08), 8, 6), stone, "outer", sh, loc=(0.02 * sx, -0.46, -0.52),
            smooth=False)
        parts[f"arm_{nm}"] = sh
        hip = B.empty(f"LordHip{nm}", pelvis, loc=(0.20 * sx, 0, -0.05))
        K.limb(f"LordThigh{nm}", (0, 0, 0), (0.02 * sx, -0.06, -0.46), 0.17, 0.14, stone, "outer", hip)
        knee = B.empty(f"LordKnee{nm}", hip, loc=(0.02 * sx, -0.06, -0.46))
        facet(f"LordGreave{nm}", B.lathe([(0.12, -0.42), (0.15, -0.30), (0.16, -0.05), (0.13, 0.02)], 6), stone, knee,
              crack=20 + sx)
        facet(f"LordBoot{nm}", K.ellipsoid((0.14, 0.22, 0.08), 8, 4), stone, knee, loc=(0, -0.06, -0.47))
        parts[f"hip_{nm}"], parts[f"knee_{nm}"] = hip, knee
    # 关刀：右手斜举，杆赭石，刀头石色、刀背一缕赭石穗
    armR = parts["arm_R"]
    grip = Vector((0.02 * -1, -0.46, -0.52))
    pole_dir = Vector((0.02, -0.55, 0.83)).normalized()
    a, b = grip - pole_dir * 0.85, grip + pole_dir * 1.12
    K.limb("LordPole", a, b, 0.035, 0.032, ochre, "inner", armR)
    blade = obj("LordBlade", _blade_build(), stone, "outer", armR, smooth=False)
    blade.location = b - pole_dir * 0.10
    blade.rotation_mode = "QUATERNION"
    blade.rotation_quaternion = Vector((0, 0, 1)).rotation_difference(pole_dir)
    K.limb("LordPoleCap", b - pole_dir * 0.08, b + pole_dir * 0.02, 0.05, 0.05, ochre, "inner", armR)
    sockets = {"eyes": sock, "feet": B.empty("LordFeet", root)}
    parts["sockets"] = sockets
    bpy.context.view_layer.update()
    return root, parts, sockets


def pose_stonelord(parts, anim, frame, n):
    """move：缓慢重踏——一条腿抬起再重重踏下（两拍各 4 帧），上身随之左右晃、落地时微沉。"""
    ph = 2 * math.pi * (frame % n) / n
    parts["pelvis"].location.z = 1.05 - 0.02 * abs(math.cos(ph))
    parts["pelvis"].rotation_euler = (0, math.radians(3 * math.sin(ph)), 0)
    for nm, sgn in (("L", 1), ("R", -1)):
        s = sgn * math.sin(ph)
        lift = max(0.0, s)
        parts[f"hip_{nm}"].rotation_euler = (math.radians(-26 * lift + 6 * min(0.0, s)), 0, 0)
        parts[f"knee_{nm}"].rotation_euler = (math.radians(34 * lift), 0, 0)
    parts["arm_L"].rotation_euler = (math.radians(8 * math.sin(ph)), 0, 0)
    parts["arm_R"].rotation_euler = (math.radians(2 * math.sin(ph)), 0, 0)
    bpy.context.view_layer.update()
