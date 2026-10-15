"""石将：神道石像生里的翁仲武将，活了过来。

造型（中式石雕武将，不是西洋骑士）：
  - 兜鍪：圆顶盔，后面和两侧垂下外张的顿项，盔顶一簇朱砂盔缨
  - 方脸、浓眉压眼（眼睛 EYE['stonelord'] 在眉下发光），胸前垂一把长髯（重墨石色）
  - 明光铠：胸甲上刻出鳞状甲片（Freestyle 边标记），正中一面圆形护心镜（赭石镜框）；赭石腰带、圆扣
  - 披膊：肩上两层外张的弧形护甲；战裙：前、侧、后几片甲裙垂到膝，甲片一排排
  - 右手（-X）立持青龙偃月刀：右臂垂在身侧握杆，刀杆竖在身侧略偏后、杆头微向外倾，刀刃朝身后外侧
    （E 向画面上刀在身体左边、刃口朝左），不挡长髯和护心镜；赭石长杆，弯月大刃、刃背有缺口和一个圆环，
    刃下一缕朱砂刀穗
  - 石色清墨/淡墨/重墨，赭石点缀，身上有裂纹
动画 move：8 帧缓慢的重踏。帧 FRAME["elite"]，锚点 BIG_ENEMY_ANCHOR。只渲染 E。
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import bmesh
import bpy
import numpy as np
from mathutils import Matrix, Vector

ART = Path(__file__).resolve().parents[1]
for p in (ART, ART / "models"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
from style import bstyle as B  # noqa: E402
from style import style as S  # noqa: E402
import kit as K  # noqa: E402


def _mark_edges(ob, seed, keep=0.35, min_deg=12.0, horizontal_only=False):
    """把一部分棱标成 Freestyle 边标记：裂纹（随机）或甲片（只取水平方向的棱）。"""
    me = ob.data
    rng = np.random.default_rng(seed)
    ef: dict = {}
    for poly in me.polygons:
        for ek in poly.edge_keys:
            ef.setdefault(ek, []).append(poly.normal.copy())
    attr = me.attributes.get("freestyle_edge") or me.attributes.new("freestyle_edge", "BOOLEAN", "EDGE")
    vals = []
    for e in me.edges:
        v0, v1 = (me.vertices[i].co for i in e.vertices)
        if horizontal_only:
            d = (v1 - v0)
            vals.append(abs(d.z) < 0.3 * d.length and rng.random() < keep)
            continue
        ns = ef.get(tuple(sorted(e.vertices)), [])
        ang = math.degrees(ns[0].angle(ns[1])) if len(ns) == 2 else 0.0
        vals.append(ang > min_deg and rng.random() < keep)
    attr.data.foreach_set("value", vals)


def _crescent_blade_build(length=0.66):
    """偃月刀刃：刃口（局部 -Y）是一条大弧，刃尖向前上方挑；刃背较直，中段有个缺口。局部 z 沿刀杆向上。"""
    def build(bm):
        n = 14
        rows = []
        for i in range(n):
            t = i / (n - 1)
            z = length * t
            edge = -0.06 - 0.24 * math.sin(math.pi * min(t / 0.8, 1.0)) ** 0.7  # 刃口弧
            if t > 0.8:
                edge = -0.06 - (0.24 * math.sin(math.pi * 1.0) ** 0.7) - 0.20 * (t - 0.8) / 0.2  # 刀尖向前挑
            back = 0.05 + 0.03 * t
            if 0.42 < t < 0.55:
                back -= 0.05  # 刃背缺口
            if t > 0.8:
                back = back + (edge - back) * ((t - 0.8) / 0.2) ** 1.2  # 收成刀尖
            rows.append((edge, back, z))
        th = 0.02
        F = [[bm.verts.new((s * th, e, z)) for e, b, z in rows] for s in (-1, 1)]
        Bk = [[bm.verts.new((s * th * 1.6, b, z)) for e, b, z in rows] for s in (-1, 1)]
        for i in range(n - 1):
            for s in (0, 1):
                bm.faces.new((F[s][i], F[s][i + 1], Bk[s][i + 1], Bk[s][i]))
            bm.faces.new((F[0][i], F[1][i], F[1][i + 1], F[0][i + 1]))
            bm.faces.new((Bk[0][i + 1], Bk[1][i + 1], Bk[1][i], Bk[0][i]))
        bm.faces.new((F[0][0], Bk[0][0], Bk[1][0], F[1][0]))
        bm.faces.new((F[1][-1], Bk[1][-1], Bk[0][-1], F[0][-1]))
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    return build


def _plate_skirt_rows(center_deg, width_deg, r_top, z_top, length, flare=0.10, nu=4, nv=4, sy=0.78):
    rows = []
    for j in range(nv + 1):
        t = j / nv
        row = []
        for i in range(nu + 1):
            u = i / nu
            th = math.radians(center_deg + (u - 0.5) * width_deg)
            r = r_top + flare * t
            row.append(Vector((r * math.cos(th), r * math.sin(th) * sy, z_top - length * t)))
        rows.append(row)
    return rows


# 右臂（肩坐标系，肩在上身 (-0.42, 0, 0.70)）：上臂垂下略向后，前臂垂在身侧；握杆处在髋侧略偏后
ELBOW_R = Vector((-0.10, 0.05, -0.42))
GRIP_R = Vector((-0.12, 0.02, -0.72))
POLE_DIR = Vector((-0.08, 0.10, 1.0))  # 杆：竖直，杆头略向外、向后倾，刀头让开盔
BLADE_EDGE = Vector((-0.75, 0.66, 0.0))  # 刃口朝身后外侧：E 向画面上整片刀面朝左展开


def build_stonelord():
    I, A = S.INK, S.ACCENT
    stone = K.toon("LordStone", ramp=[I["qing"], I["dan"], I["zhong"]], wash=0.35, edge=0.6, seed=71.0)
    dark = K.toon("LordStoneDark", ramp=[I["dan"], I["zhong"], I["nong"]], wash=0.3, edge=0.5, seed=73.0)
    ochre = K.toon("LordOchre", A["zheshi"], seed=72.0)
    red = K.toon("LordRed", A["zhusha"], seed=74.0)
    ink = B.flat_material("LordInk", I["jiao"])
    eye = B.emissive_material("LordEye", S.EYE["stonelord"], 1.0)
    root = B.empty("LordRoot")
    yaw = K.yaw_pivot("LordYaw", root, -34)  # 多转向镜头，护心镜和长髯要露出来
    body = B.empty("LordBody", yaw)
    parts = {"root": root, "body": body}
    obj = B.mesh_object

    def flat(name, build, mat, parent, line="outer", **kw):
        return obj(name, build, mat, line, parent, smooth=False, **kw)

    pelvis = B.empty("LordPelvis", body, loc=(0, 0, 1.05))
    parts["pelvis"] = pelvis
    upper = B.empty("LordUpper", pelvis, rot=(math.radians(3), 0, 0))
    parts["upper"] = upper
    # 明光铠胸甲：多面体 + 一排排鳞甲（水平棱的边标记）
    cuir = flat("LordCuirass", B.lathe([(0.29, 0.0), (0.33, 0.12), (0.38, 0.26), (0.43, 0.42), (0.45, 0.56), (0.42, 0.68),
                                        (0.30, 0.78), (0.13, 0.84)], 12, scale_y=0.70), stone, upper,
                rot=(0, 0, math.radians(15)))
    _mark_edges(cuir, 1, keep=0.85, horizontal_only=True)
    # 护心镜（正中圆镜，赭石框）
    obj("LordMirrorRim", B.cylinder(0.145, 0.145, 0.03, 20), ochre, "inner", upper, loc=(0, -0.29, 0.48),
        rot=(math.radians(100), 0, 0))
    obj("LordMirror", B.cylinder(0.11, 0.11, 0.035, 20), stone, "inner", upper, loc=(0, -0.30, 0.48),
        rot=(math.radians(100), 0, 0))
    obj("LordBelt", B.lathe([(0.31, -0.04), (0.33, 0.04), (0.31, 0.11)], 16, scale_y=0.74), ochre, "inner", upper,
        sharp_deg=0)
    obj("LordBuckle", B.cylinder(0.07, 0.07, 0.03, 12), ochre, "inner", upper, loc=(0, -0.24, 0.035),
        rot=(math.radians(90), 0, 0))
    # 战裙：前、两侧、后四片，一排排甲片
    for i, (c, w, ln) in enumerate(((-90, 70, 0.52), (90, 90, 0.55), (0, 60, 0.48), (180, 60, 0.48))):
        sk = flat(f"LordSkirt{i}", K.grid_build(_plate_skirt_rows(c, w, 0.33, 1.08, ln)), stone, body)
        _mark_edges(sk, 30 + i, keep=0.9, horizontal_only=True)
    # 兜鍪：圆顶 + 外张的顿项（正面开口露脸），盔顶尖 + 朱砂盔缨
    head = B.empty("LordHead", upper, loc=(0, -0.03, 1.02), rot=(math.radians(-6), 0, math.radians(-22)))
    parts["head"] = head

    def helmet(bm):
        prof = [(0.0, 0.30), (0.10, 0.28), (0.18, 0.20), (0.21, 0.08), (0.215, 0.02), (0.25, -0.08), (0.29, -0.20)]
        segs = 16
        rings = []
        for r, z in prof:
            if r == 0:
                rings.append([bm.verts.new((0, 0, z))])
                continue
            rings.append([bm.verts.new((r * math.cos(2 * math.pi * i / segs), r * math.sin(2 * math.pi * i / segs), z))
                          for i in range(segs)])
        for j, (a, b) in enumerate(zip(rings, rings[1:])):
            if len(a) == 1:
                for i in range(segs):
                    bm.faces.new((b[(i + 1) % segs], b[i], a[0]))
                continue
            for i in range(segs):
                thc = 2 * math.pi * (i + 0.5) / segs
                front = math.sin(thc) < -0.55  # 正面（-Y）
                if front and prof[j][1] <= 0.02:
                    continue  # 顿项正面开口
                bm.faces.new((a[i], a[(i + 1) % segs], b[(i + 1) % segs], b[i]))
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
        for f in bm.faces:
            c = f.calc_center_median()
            if f.normal.dot(Vector((c.x, c.y, c.z - 0.05))) < 0:
                f.normal_flip()

    helm = flat("LordHelm", helmet, stone, head)
    _mark_edges(helm, 3, keep=0.6, horizontal_only=True)
    K.limb("LordSpike", (0, 0, 0.29), (0, 0, 0.40), 0.03, 0.0, ochre, "inner", head, segs=8)
    for i, (dx, dy) in enumerate(((0, 0.0), (0.05, 0.04), (-0.05, 0.04), (0.0, 0.08))):
        tassel = K.curve_points((dx * 0.3, dy * 0.3, 0.37), (dx * 2.2, 0.18 + dy * 2, 0.16), bend=Vector((0, 0.02, 0.12)), n=7)
        obj(f"LordTassel{i}", K.tube_build(tassel, K.bushy(0.045, peak=0.25), 8), red, "outer", head)
    obj("LordFace", K.ellipsoid((0.15, 0.14, 0.18), 10, 8), stone, "outer", head, loc=(0, -0.03, -0.10), smooth=False)
    obj("LordBrow", K.ellipsoid((0.15, 0.04, 0.03), 10, 6), dark, "inner", head, loc=(0, -0.155, -0.04),
        rot=(math.radians(-8), 0, 0))
    sock = K.slit_eyes("Lord", head, Vector((0, -0.165, -0.085)), 0.10, (0.042, 0.012, 0.016), eye, tilt_deg=-12)
    beard = [Vector((0, -0.15, -0.20)), Vector((0, -0.20, -0.32)), Vector((0, -0.22, -0.46)), Vector((0, -0.21, -0.62))]
    obj("LordBeard", K.strip_build(beard, 0.15, 0.04, taper=(1.0, 0.15), side_hint=Vector((1, 0, 0))), dark, "outer", head)
    # 披膊（两层）、手臂
    for sx, nm in ((1, "L"), (-1, "R")):
        sh = B.empty(f"LordShoulder{nm}", upper, loc=(0.42 * sx, 0, 0.70))
        for k_, (r, z, rot) in enumerate(((0.22, 0.02, 20), (0.26, -0.10, 32))):
            pd = flat(f"LordPauldron{nm}{k_}", B.lathe([(0.0, 0.10), (r * 0.6, 0.08), (r, -0.02), (r * 1.08, -0.12)], 9),
                      stone, sh, loc=(0.03 * sx * k_, 0, z), rot=(0, math.radians(-rot * sx), 0))
            _mark_edges(pd, 40 + k_ + sx, keep=0.5, horizontal_only=True)
        elbow = ELBOW_R if sx < 0 else Vector((0.08 * sx, -0.10, -0.44))
        K.limb(f"LordArmU{nm}", (0.05 * sx, 0, -0.08), elbow, 0.12, 0.10, stone, "outer", sh)
        if sx < 0:  # 右前臂垂在身侧握杆
            K.limb("LordArmFR", elbow, GRIP_R, 0.10, 0.09, stone, "outer", sh)
            br = flat("LordBracerR", B.lathe([(0.10, -0.20), (0.11, -0.05), (0.09, 0.0)], 8), stone, sh, loc=elbow)
            br.rotation_mode = "QUATERNION"
            br.rotation_quaternion = Vector((0, 0, -1)).rotation_difference((GRIP_R - elbow).normalized())
        else:
            flat(f"LordBracer{nm}", B.lathe([(0.10, -0.20), (0.11, -0.05), (0.09, 0.0)], 8), stone, sh,
                 loc=elbow, rot=(math.radians(-40), 0, 0))
        obj(f"LordHand{nm}", K.ellipsoid((0.08, 0.09, 0.08), 8, 6), stone, "outer", sh,
            loc=GRIP_R if sx < 0 else (0.02, -0.16, -0.66), smooth=False)
        parts[f"arm_{nm}"] = sh
        hip = B.empty(f"LordHip{nm}", pelvis, loc=(0.19 * sx, 0, -0.05))
        K.limb(f"LordThigh{nm}", (0, 0, 0), (0.02 * sx, -0.04, -0.46), 0.17, 0.14, stone, "outer", hip)
        knee = B.empty(f"LordKnee{nm}", hip, loc=(0.02 * sx, -0.04, -0.46))
        gr = flat(f"LordGreave{nm}", B.lathe([(0.12, -0.42), (0.15, -0.30), (0.16, -0.05), (0.13, 0.02)], 8), stone, knee)
        _mark_edges(gr, 20 + sx, keep=0.4)
        flat(f"LordBoot{nm}", K.ellipsoid((0.14, 0.23, 0.08), 8, 4), dark, knee, loc=(0, -0.07, -0.47))
        parts[f"hip_{nm}"], parts[f"knee_{nm}"] = hip, knee
    # 青龙偃月刀：右手垂在身侧立持，杆竖直略向外倾；刃口朝身后外侧（E 向画面上朝左），刀头在盔的左后方
    armR = parts["arm_R"]
    grip = GRIP_R
    pole_dir = POLE_DIR.normalized()
    a, b = grip - pole_dir * 0.95, grip + pole_dir * 1.02  # 杆尾离地约 8 厘米
    K.limb("LordPole", a, b, 0.032, 0.030, ochre, "inner", armR)
    K.limb("LordPoleCollar", b - pole_dir * 0.04, b + pole_dir * 0.08, 0.05, 0.045, ochre, "inner", armR)
    edge = BLADE_EDGE - pole_dir * BLADE_EDGE.dot(pole_dir)  # 刃口方向（刀的局部 -Y），和杆垂直
    edge.normalize()
    ly = -edge
    lx = ly.cross(pole_dir).normalized()
    rot = Matrix((lx, ly, pole_dir)).transposed().to_quaternion()  # 局部 X、Y、Z → 世界
    blade = flat("LordBlade", _crescent_blade_build(0.62), stone, armR)
    blade.location = b + pole_dir * 0.06
    blade.rotation_mode = "QUATERNION"
    blade.rotation_quaternion = rot
    ring = obj("LordRing", B.lathe([(0.045, -0.008), (0.052, 0.0), (0.045, 0.008)], 14), ochre, "inner", armR,
               loc=b + pole_dir * 0.36 - edge * 0.10)
    ring.rotation_mode = "QUATERNION"
    ring.rotation_quaternion = Vector((0, 0, 1)).rotation_difference(lx)  # 环面和刀面同一平面
    tas = K.curve_points(b - edge * 0.03, b - edge * 0.08 + Vector((0, 0, -0.22)), bend=-edge * 0.03, n=6)
    obj("LordBladeTassel", K.tube_build(tas, K.bushy(0.035, peak=0.3), 8), red, "inner", armR)
    sockets = {"eyes": sock, "feet": B.empty("LordFeet", root)}
    parts["sockets"] = sockets
    bpy.context.view_layer.update()
    return root, parts, sockets


def pose_stonelord(parts, anim, frame, n):
    """move：缓慢重踏——一条腿抬起再重重踏下（两拍各 4 帧），上身随之左右晃、落地时微沉。"""
    ph = 2 * math.pi * (frame % n) / n
    parts["pelvis"].location.z = 1.05 - 0.010 * abs(math.cos(ph))
    parts["pelvis"].rotation_euler = (0, math.radians(1.2 * math.sin(ph)), 0)
    for nm, sgn in (("L", 1), ("R", -1)):
        s = sgn * math.sin(ph)
        lift = max(0.0, s)
        parts[f"hip_{nm}"].rotation_euler = (math.radians(-24 * lift + 5 * min(0.0, s)), 0, 0)
        parts[f"knee_{nm}"].rotation_euler = (math.radians(30 * lift), 0, 0)
    parts["arm_L"].rotation_euler = (math.radians(6 * math.sin(ph)), 0, 0)
    parts["arm_R"].rotation_euler = (math.radians(1.5 * math.sin(ph)), 0, 0)
    bpy.context.view_layer.update()
