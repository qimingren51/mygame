"""提灯剑修：主角模型（程序化刚体部件）。

造型（约 5 头身，修长挺拔，不是 Q 版）：
  - 黑发高髻，石绿玉冠，长发披在背后；冠后垂两条朱砂发带（主要的红色动势）
  - 交领广袖长袍：内袍宣纸白（白交领露在领口），外袍花青，浓墨镶边与下摆；下摆及踝，两侧开衩露出内袍
  - 浓墨腰带，左前方挂石绿玉佩和朱砂小穗；浓墨布靴
  - 背上斜背一把带鞘的剑：剑柄在左肩上方，鞘浓墨，藤黄装具，朱砂剑穗（背面朝向的标志）
  - 右手（世界 -X）持赭石细杖（约 1.1 米），向前外侧斜伸；杖头挂红纸灯笼（朱砂纸壳、墨色上下盖、
    发光芯），灯下垂藤黄符纸和朱砂小穗
  - 脸：肤色，墨点小眼和细眉

约定：脚底在原点，面朝 -Y，右手在 -X；总高 HERO_HEIGHT_M（脚底到玉冠顶，发带可以更高）。
动画：发带、袖子、下摆、发尾、灯笼都是独立部件，pose_hero() 给它们滞后的次级运动。

用法：
    parts, sockets = ...
    root, parts, sockets = build_hero()
    pose_hero(parts, "walk", 3, 8)
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import bmesh
import bpy
import numpy as np
from mathutils import Euler, Matrix, Vector

ART = Path(__file__).resolve().parents[1]
if str(ART) not in sys.path:
    sys.path.insert(0, str(ART))
from style import bstyle as B  # noqa: E402
from style import style as S  # noqa: E402

H = S.HERO_HEIGHT_M  # 1.75

# ---------------------------------------------------------------- 尺寸（米）
HEAD_C = Vector((0.0, -0.005, 1.47))  # 头心
HEAD_R = (0.112, 0.122, 0.142)  # 头的三个半径
CROWN_TOP = H  # 玉冠顶 = 总高
SHOULDER_Z = 1.215
BELT_Z = 0.99
HEM_Z = 0.075  # 外袍下摆
SLIT_TOP = 0.52  # 开衩高度
TORSO_SY = 0.72  # 躯干前后/左右比
HAND_R = Vector((-0.265, -0.205, 0.905))  # 右手（握杖处）
STAFF_DIR = Vector((-0.36, -0.30, 0.88)).normalized()
STAFF_LEN = 1.10
STAFF_GRIP = 0.16  # 握点到杖尾
STAFF_R = (0.033, 0.029)  # 杖尾、杖头半径
TALISMAN_W, TALISMAN_LEN = 0.072, 0.22  # 符纸宽约 3.6px
SWORD_POMMEL = Vector((0.205, 0.175, 1.53))
SWORD_TIP = Vector((-0.25, 0.16, 0.72))

# 躯干轮廓 (r, z)，自下而上
TORSO_PROFILE = [(0.140, 0.94), (0.146, 1.00), (0.158, 1.08), (0.176, 1.15), (0.190, 1.195),
                 (0.186, SHOULDER_Z), (0.155, 1.245), (0.092, 1.268), (0.052, 1.285)]
# 外袍下裙 (r, z)，自上而下写，用时翻转
SKIRT_PROFILE = [(0.150, 1.00), (0.172, 0.88), (0.198, 0.72), (0.226, 0.52), (0.252, 0.32),
                 (0.276, 0.16), (0.290, HEM_Z)]


def _ramp_mat(name, base=None, ramp=None, **kw):
    return B.toon_material(name, base, ramp=ramp, **kw)


def _materials():
    I, A, Wsh = S.INK, S.ACCENT, S.WASH
    m = {
        # 大面积衣物用淡彩（兑水的花青），纯 ACCENT 只留给发带、灯笼、穗子、玉这些点睛处
        "robe": _ramp_mat("RobeHuaqingWash", Wsh["huaqing"], seed=1.0),
        "border": _ramp_mat("BorderNong", I["nong"], seed=2.0),
        "inner": _ramp_mat("InnerPaper", S.PAPER, seed=3.0),
        "skin": _ramp_mat("Skin", S.SKIN, wash=0.08, edge=0.3, seed=4.0),
        "hair": _ramp_mat("Hair", I["jiao"], seed=5.0),
        "jade": _ramp_mat("Jade", A["shilv"], seed=6.0),
        "ribbon": _ramp_mat("Ribbon", A["zhusha"], edge=0.35, seed=7.0),
        "staff": _ramp_mat("Staff", A["zheshi"], edge=0.15, seed=8.0),
        "shell": _ramp_mat("LanternShell", A["zhusha"], edge=0.25, seed=9.0),
        "cap": _ramp_mat("Cap", I["jiao"], seed=10.0),
        "gold": _ramp_mat("Tenghuang", A["tenghuang"], seed=11.0),
        "scabbard": _ramp_mat("Scabbard", I["nong"], seed=12.0),
        "boot": _ramp_mat("Boot", I["nong"], seed=13.0),
        "tassel": _ramp_mat("Tassel", A["zhusha"], seed=14.0),
        "eye": B.flat_material("EyeInk", I["jiao"]),
        "seal": B.flat_material("TalismanMark", A["zhusha"]),
        "core": B.emissive_material("LanternCore", S.LANTERN_LIGHT, 1.0),
    }
    m["window"] = B.window_material("LanternWindow", m["shell"], open_facing=0.25)  # 窗口小一点，朱砂纸壳要读得出来
    return m


def _torso_r(z):
    zs = [p[1] for p in TORSO_PROFILE]
    rs = [p[0] for p in TORSO_PROFILE]
    return float(np.interp(z, zs, rs))


def _torso_point(theta_deg, z, off=0.0, r_override=None):
    """躯干表面上的点（theta 从 +X 起逆时针；-90° 是正前方）。"""
    th = math.radians(theta_deg)
    r = (r_override if r_override is not None else _torso_r(z)) + off
    return Vector((r * math.cos(th), r * math.sin(th) * TORSO_SY + (off * math.sin(th) * (1 - TORSO_SY)), z))


# ================================================================ 各部件的几何
def _skirt_build(scale=1.0, slit=True, z_top=1.0, z_bot=HEM_Z, segs=40, hem_band=0.07):
    """外袍下裙：带竖褶的喇叭形，两侧（±X）开衩，最下一圈是浓墨镶边（材质 1）。"""
    prof = [(r * scale, z) for r, z in SKIRT_PROFILE]
    prof[0] = (prof[0][0], z_top)
    prof[-1] = (prof[-1][0], z_bot)
    zs = sorted({z for _, z in prof} | {z_bot + hem_band, SLIT_TOP})
    zs = [z for z in zs if z_bot <= z <= z_top]
    rz = [(float(np.interp(z, [p[1] for p in prof[::-1]], [p[0] for p in prof[::-1]])), z) for z in zs]

    def sy(z):
        return 0.76 + 0.14 * (1 - (z - z_bot) / (z_top - z_bot))

    def fold(th, z):
        t = 1 - (z - z_bot) / (z_top - z_bot)
        return 1 + 0.045 * t * t * math.sin(6 * th + 0.4) + 0.02 * t * math.sin(11 * th)

    slit_half = math.radians(15)

    def build(bm):
        rings = []
        for r, z in rz:
            ring = []
            for i in range(segs):
                th = 2 * math.pi * i / segs
                k = fold(th, z)
                ring.append(bm.verts.new((r * k * math.cos(th), r * k * math.sin(th) * sy(z), z)))
            rings.append(ring)
        for j in range(len(rings) - 1):
            a, b = rings[j], rings[j + 1]  # a 低 b 高
            zlo = rz[j][1]
            for i in range(segs):
                thc = 2 * math.pi * (i + 0.5) / segs
                if slit and zlo < SLIT_TOP - 1e-6:
                    d0 = min(abs(math.remainder(thc, 2 * math.pi)), abs(math.remainder(thc - math.pi, 2 * math.pi)))
                    if d0 < slit_half:
                        continue
                f = bm.faces.new((a[i], a[(i + 1) % segs], b[(i + 1) % segs], b[i]))
                if zlo < z_bot + hem_band - 1e-6:
                    f.material_index = 1
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
        # 裙面是单层，法线统一朝外
        for f in bm.faces:
            c = f.calc_center_median()
            if f.normal.dot(Vector((c.x, c.y, 0))) < 0:
                f.normal_flip()

    return build


def _sleeve_build(A, Bp, radii, droop, segs=18, border=0.12):
    """广袖：从肩 A 到袖口 B 的喇叭管，下侧（世界 -Z 方向）随长度下垂成袖兜。
    最后一段是浓墨镶边（材质 1），袖口封一个凹进去的深色面（材质 2）。顶点相对 A（物体原点放在肩上）。"""
    A, Bp = Vector(A), Vector(Bp)
    d = (Bp - A).normalized()
    down = Vector((0, 0, -1))
    u = down - d * down.dot(d)
    if u.length < 1e-3:
        u = Vector((0, 1, 0))
    u.normalize()
    v = d.cross(u).normalized()
    ts = [0.0, 0.12, 0.3, 0.5, 0.7, 0.86, 1.0 - border * 0.5, 1.0]

    def build(bm):
        rings = []
        for t in ts:
            r = float(np.interp(t, [p[0] for p in radii], [p[1] for p in radii]))
            c = A.lerp(Bp, t) - A
            ring = []
            for i in range(segs):
                th = 2 * math.pi * i / segs
                dirv = u * math.cos(th) + v * math.sin(th)
                sag = droop * (t ** 1.6) * max(0.0, math.cos(th)) ** 1.3
                ring.append(bm.verts.new(c + dirv * r + u * sag))
            rings.append(ring)
        for j in range(len(rings) - 1):
            a, b = rings[j], rings[j + 1]
            for i in range(segs):
                f = bm.faces.new((a[i], a[(i + 1) % segs], b[(i + 1) % segs], b[i]))
                if ts[j] >= 0.86 - 1e-6:
                    f.material_index = 1
        # 肩部封口
        bm.faces.new(list(reversed(rings[0])))
        # 袖口：向里收一点的深色面
        cen = sum((p.co for p in rings[-1]), Vector()) / segs - d * 0.04
        cv = bm.verts.new(cen)
        for i in range(segs):
            f = bm.faces.new((rings[-1][i], rings[-1][(i + 1) % segs], cv))
            f.material_index = 2
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)

    return build


def _strip_path_build(pts, width, thick, twist=0.0, taper=(1.0, 0.6), side_hint=Vector((1, 0, 0))):
    """扁带（发带、发尾、符纸）：沿点列扫一个扁矩形，宽度方向大致沿 side_hint，可沿长度扭转。"""
    pts = [Vector(p) for p in pts]
    n = len(pts)
    ups = []
    for i in range(n):
        tan = (pts[min(i + 1, n - 1)] - pts[max(i - 1, 0)]).normalized()
        side = side_hint - tan * side_hint.dot(tan)
        if side.length < 1e-4:
            side = Vector((0, 1, 0))
        side.normalize()
        ang = twist * i / max(n - 1, 1)
        side = (Matrix.Rotation(ang, 3, tan) @ side).normalized()
        ups.append(tan.cross(side))  # sweep 的厚度方向
    return B.sweep(pts, width, thick, ups=ups, width_fn=lambda t: taper[0] + (taper[1] - taper[0]) * t)


def _ribbon_points(start, length, phase, wind, side_sign=1.0, n=16, spread=0.0):
    """发带中心线：从冠后出发，初速度方向 + 重力下垂 + 沿带行进的 S 形波。
    wind=0 静立（大致下垂、略向身侧飘），wind=1 行走（被拉向后方，末端下垂）。"""
    d_idle = Vector((0.62 * side_sign + spread, 0.55, -1.0)).normalized()
    d_walk = Vector((0.30 * side_sign + spread, 0.8, -0.6)).normalized()
    dirv = d_idle.lerp(d_walk, wind).normalized()
    side = Vector((0, 0, 1)).cross(dirv)
    side = side.normalized() if side.length > 1e-4 else Vector((1, 0, 0))
    up = dirv.cross(side).normalized()
    sag_k = 0.10 + 0.25 * wind  # 行走时初速度更平，靠重力把末端拉下来
    amp = 0.03 + 0.05 * wind
    k = 2 * math.pi * 1.4 / length  # 全长约 1.4 个波
    pts = []
    for i in range(n):
        s = length * i / (n - 1)
        w = s / length
        p = Vector(start) + dirv * s
        p += side * (math.sin(k * s - phase) * amp * w)
        p += up * (math.cos(k * 0.8 * s - phase + 0.7) * amp * 0.7 * w)
        p.z -= sag_k * s * s
        pts.append(p)
    return pts


def _hair_tail_points(phase=0.0, wind=0.0, n=9):
    """长发：从后脑垂到背中，贴着背略向后。顶点相对发尾枢轴。"""
    pts = []
    for i in range(n):
        t = i / (n - 1)
        z = -0.50 * t
        y = 0.035 * math.sin(t * 2.4) + 0.06 * t * t + 0.10 * wind * t * t
        x = 0.012 * math.sin(3.0 * t - phase) * t
        pts.append(Vector((x, y, z)))
    return pts


def _talisman_points(top, phase, wind, n=7):
    """符纸中心线：从灯笼底垂下，随相位轻轻飘（下端摆幅大），行走时向后飘。"""
    pts = []
    for i in range(n):
        t = i / (n - 1)
        sway = (0.018 + 0.03 * wind) * t * t * math.sin(phase - 2.2 * t)
        back = (0.01 + 0.05 * wind) * t * t
        pts.append(Vector(top) + Vector((sway, back - 0.004 * i, -TALISMAN_LEN * t)))
    return pts


def _talisman_frame(top, phase, wind):
    """符纸的宽度方向：在“正前”和“右侧”之间斜 35°，并沿长度扭 60°，任何朝向都不会完全侧对镜头。"""
    pts = _talisman_points(top, phase, wind)
    return pts, Vector((math.cos(math.radians(-35)), math.sin(math.radians(-35)), 0))


def _talisman_build(top, phase, wind):
    pts, side = _talisman_frame(top, phase, wind)
    return _strip_path_build(pts, TALISMAN_W, 0.006, twist=math.radians(60) + 0.25 * math.sin(phase),
                             side_hint=side, taper=(1.0, 0.92))


def _talisman_mark_build(top, phase, wind):
    """符纸中段的一小道朱砂符文（贴在纸面前方，不描线）。"""
    pts, side = _talisman_frame(top, phase, wind)
    seg = pts[2:5]
    n = (seg[-1] - seg[0]).normalized().cross(side).normalized()
    if n.y > 0:
        n = -n
    seg = [p + n * 0.006 for p in seg]
    return _strip_path_build(seg, TALISMAN_W * 0.35, 0.004, twist=math.radians(60) * 3 / 6,
                             side_hint=side, taper=(1.0, 1.0))


def _replace_mesh(ob, build):
    """换掉物体的网格（每帧重建飘带用），保留材质。"""
    old = ob.data
    me = bpy.data.meshes.new(old.name)
    bm = bmesh.new()
    build(bm)
    bm.to_mesh(me)
    bm.free()
    me.shade_smooth()
    for m in old.materials:
        me.materials.append(m)
    ob.data = me
    if old.users == 0:
        bpy.data.meshes.remove(old)


# ================================================================ 组装
def build_hero():
    """返回 (root, parts, sockets)。sockets: lantern（灯笼纸壳中心）、feet（原点）。"""
    M = _materials()
    obj = B.mesh_object
    root = B.empty("HeroRoot")
    parts: dict = {"root": root, "mats": M}

    # ---- 靴（跟着脚走，不随身体起伏）
    for side, x in (("L", 0.085), ("R", -0.085)):
        foot = B.empty(f"Foot{side}", root, loc=(x, 0, 0))
        obj(f"Boot{side}", B.uv_sphere(1.0, 16, 8, scale=(0.052, 0.098, 0.05)), M["boot"], "outer", foot,
            loc=(0, -0.022, 0.045))
        obj(f"Shin{side}", B.cylinder(0.042, 0.048, 0.36, 10), M["boot"], "outer", foot, loc=(0, 0.01, 0.24))
        parts[f"foot_{side}"] = foot

    body = B.empty("Body", root)
    parts["body"] = body

    # ---- 下身：内袍（白）在里，外袍下裙（花青 + 浓墨下摆，两侧开衩）
    skirt_pivot = B.empty("SkirtPivot", body, loc=(0, 0, BELT_Z))
    # 内袍比外袍小一圈（外袍褶皱的凹处最多内收约 6.5%），并跟外袍一起摆，避免穿模
    inner = obj("InnerSkirt", _skirt_build(scale=0.84, slit=False, z_top=1.0, z_bot=HEM_Z - 0.03, segs=28, hem_band=0.0),
                [M["inner"], M["inner"]], "outer", skirt_pivot, sharp_deg=0)
    inner.location = (0, 0, -BELT_Z)
    sk = obj("Skirt", _skirt_build(), [M["robe"], M["border"]], "outer", skirt_pivot, sharp_deg=0)
    sk.location = (0, 0, -BELT_Z)
    parts["skirt"] = skirt_pivot

    # ---- 躯干（外袍上身）、颈
    obj("Torso", B.lathe(TORSO_PROFILE, 32, scale_y=TORSO_SY), M["robe"], "outer", body, sharp_deg=0)
    obj("Neck", B.cylinder(0.038, 0.042, 0.12, 12), M["skin"], "inner", body, loc=(0, 0.005, 1.31))

    # ---- 交领：白色内领在里，浓墨镶边的外领在外（左襟压右襟，领线从左颈斜到右腋下）
    long_path = [(95, 1.288, 0.010), (40, 1.282, 0.012), (-20, 1.262, 0.010), (-62, 1.22, 0.006),
                 (-92, 1.15, 0.006), (-122, 1.075, 0.006), (-150, 1.015, 0.006)]
    short_path = [(150, 1.286, 0.010), (205, 1.262, 0.008), (245, 1.205, 0.004), (262, 1.17, 0.003)]

    def surf(path, extra=0.0, dz=0.0):
        return [_torso_point(t, z + dz, off + extra) for t, z, off in path]

    obj("CollarWhite", B.sweep(surf(long_path, 0.004), 0.034, 0.012), M["inner"], "inner", body)
    obj("CollarWhite2", B.sweep(surf(short_path, 0.0), 0.030, 0.010), M["inner"], "inner", body)
    obj("CollarBorder", B.sweep(surf(long_path, 0.010, -0.030), 0.032, 0.012), M["border"], "inner", body)

    # ---- 腰带、玉佩、小穗
    obj("Belt", B.lathe([(0.153, 0.955), (0.158, 0.99), (0.152, 1.03)], 32, scale_y=TORSO_SY + 0.04),
        M["border"], "inner", body, sharp_deg=0)
    pend = B.empty("PendantPivot", body, loc=(0.075, -0.112, 0.965))
    obj("PendantCord", B.cylinder(0.004, 0.004, 0.07, 6), M["border"], "none", pend, loc=(0, 0, -0.035))
    obj("Jade", B.cylinder(0.030, 0.030, 0.012, 16), M["jade"], "inner", pend, loc=(0, -0.004, -0.095),
        rot=(math.radians(90), 0, 0))
    obj("PendantTassel", B.cylinder(0.006, 0.020, 0.075, 8), M["tassel"], "none", pend, loc=(0, -0.004, -0.165))
    parts["pendant"] = pend

    # ---- 袖子（广袖，有意夸张一点，小尺寸下也能看出来）
    shL, shR = Vector((0.172, 0.005, 1.205)), Vector((-0.172, 0.005, 1.205))
    cuffL = Vector((0.262, -0.035, 0.80))
    cuffR = HAND_R + Vector((0.030, 0.050, 0.020))
    radii = [(0.0, 0.062), (0.35, 0.080), (0.75, 0.112), (1.0, 0.128)]
    sleeve_mats = [M["robe"], M["border"], M["inner"]]
    sL = B.empty("SleevePivotL", body, loc=shL)
    obj("SleeveL", _sleeve_build(shL, cuffL, radii, droop=0.16), sleeve_mats, "outer", sL, sharp_deg=0)
    obj("HandL", B.uv_sphere(1.0, 12, 8, scale=(0.030, 0.034, 0.042)), M["skin"], "inner", sL,
        loc=cuffL - shL + Vector((0.0, -0.01, -0.05)))
    armR = B.empty("ArmR", body, loc=shR)  # 右臂：袖子、手、杖、灯笼一起动
    sR = B.empty("SleevePivotR", armR)
    obj("SleeveR", _sleeve_build(shR, cuffR, radii, droop=0.22), sleeve_mats, "outer", sR, sharp_deg=0)
    obj("HandR", B.uv_sphere(1.0, 12, 8, scale=(0.034, 0.034, 0.038)), M["skin"], "inner", armR,
        loc=HAND_R - shR)
    parts["sleeve_L"], parts["sleeve_R"], parts["arm_R"] = sL, sR, armR

    # ---- 杖与灯笼
    a = HAND_R - STAFF_DIR * STAFF_GRIP
    tip = HAND_R + STAFF_DIR * (STAFF_LEN - STAFF_GRIP)
    # 杖要读成赭石木色：只描细线（thin，不进粗外轮廓），直径约 3.2px，扣掉细线后木色还有 2px 左右
    staff = obj("Staff", B.cylinder(STAFF_R[0], STAFF_R[1], STAFF_LEN, 10), M["staff"], "thin", armR)
    B.aim(staff, a - shR, tip - shR)
    obj("StaffKnob", B.uv_sphere(0.036, 10, 6), M["gold"], "thin", armR, loc=tip - shR)
    lp = B.empty("LanternPivot", armR, loc=tip - shR)
    parts["lantern"] = lp
    cord = 0.085
    sh_h, sh_r = 0.125, 0.098  # 纸壳半高、半径
    c_z = -cord - 0.022 - sh_h
    obj("LanternCord", B.cylinder(0.004, 0.004, cord, 6), M["cap"], "none", lp, loc=(0, 0, -cord / 2))
    obj("LanternCapTop", B.cylinder(0.058, 0.050, 0.03, 16), M["cap"], "inner", lp, loc=(0, 0, -cord - 0.012))
    obj("LanternShell", B.lathe([(0.0, -sh_h), (0.055, -0.115), (0.085, -0.08), (sh_r, -0.03), (sh_r, 0.03),
                                 (0.085, 0.08), (0.055, 0.115), (0.0, sh_h)], 24,
                                radial=lambda th, z: 1 + 0.035 * abs(math.sin(4 * th))),
        M["window"], "outer", lp, loc=(0, 0, c_z), sharp_deg=0)
    obj("LanternCore", B.uv_sphere(1.0, 16, 10, scale=(0.072, 0.072, 0.095)), M["core"], "none", lp,
        loc=(0, 0, c_z))
    obj("LanternCapBot", B.cylinder(0.050, 0.056, 0.026, 16), M["cap"], "inner", lp, loc=(0, 0, c_z - sh_h - 0.004))
    talisman_top = Vector((0.0, -0.05, c_z - sh_h - 0.012))
    tal = obj("Talisman", _talisman_build(talisman_top, 0.0, 0.0), M["gold"], "thin", lp)
    mark = obj("TalismanMark", _talisman_mark_build(talisman_top, 0.0, 0.0), M["seal"], "none", lp)
    parts["talisman"] = (tal, mark, talisman_top)
    obj("LanternTassel", B.cylinder(0.008, 0.024, 0.09, 8), M["tassel"], "none", lp,
        loc=(0.02, 0.025, c_z - sh_h - 0.06))
    sock_lantern = B.empty("SocketLantern", lp, loc=(0, 0, c_z))

    # ---- 头：脸、发、髻、玉冠、簪
    head = B.empty("HeadPivot", body, loc=(0, 0, 1.33))
    parts["head"] = head
    hc = HEAD_C - Vector((0, 0, 1.33))
    obj("Head", B.uv_sphere(1.0, 24, 14, scale=HEAD_R), M["skin"], "outer", head, loc=hc)

    def hair_cap(bm):
        bmesh.ops.create_uvsphere(bm, u_segments=28, v_segments=16, radius=1.0)
        kill = []
        for f in bm.faces:
            c = f.calc_center_median()
            # 保留：头顶、后半、两侧到耳下；去掉脸（前下方）
            front = c.y < -0.15
            if front and c.z < 0.52 - 0.25 * abs(c.x) and not (abs(c.x) > 0.82 and c.z > -0.15):
                kill.append(f)
            elif c.z < -0.35 and c.y < 0.35:
                kill.append(f)
        bmesh.ops.delete(bm, geom=kill, context="FACES")
        bmesh.ops.scale(bm, vec=(HEAD_R[0] * 1.07, HEAD_R[1] * 1.07, HEAD_R[2] * 1.06), verts=bm.verts)

    obj("HairCap", hair_cap, M["hair"], "outer", head, loc=hc + Vector((0, 0.006, 0.006)))
    obj("Bun", B.uv_sphere(1.0, 16, 10, scale=(0.048, 0.050, 0.046)), M["hair"], "outer", head,
        loc=Vector((0, 0.012, 1.672)) - Vector((0, 0, 1.33)))
    obj("Crown", B.lathe([(0.0, 0.0), (0.040, 0.0), (0.046, 0.030), (0.040, 0.050), (0.026, 0.060), (0.0, 0.064)], 16),
        M["jade"], "inner", head, loc=Vector((0, 0.012, CROWN_TOP - 0.064 - 1.33)), sharp_deg=50)
    pin = obj("Hairpin", B.cylinder(0.006, 0.006, 0.17, 6), M["gold"], "inner", head)
    B.aim(pin, Vector((-0.085, 0.015, 1.712 - 1.33)), Vector((0.085, 0.008, 1.712 - 1.33)))
    # 眼与眉：贴在脸前
    for sx in (-1, 1):
        x = 0.042 * sx
        ez = 1.468
        ey = HEAD_C.y - HEAD_R[1] * math.sqrt(max(0.0, 1 - (x / HEAD_R[0]) ** 2 - ((ez - HEAD_C.z) / HEAD_R[2]) ** 2))
        obj(f"Eye{sx:+d}", B.uv_sphere(1.0, 10, 6, scale=(0.017, 0.006, 0.010)), M["eye"], "none", head,
            loc=(x, ey + 0.004, ez - 1.33))
        brow = obj(f"Brow{sx:+d}", B.cylinder(0.004, 0.003, 0.038, 6), M["eye"], "none", head)
        bz = ez + 0.030
        by = HEAD_C.y - HEAD_R[1] * math.sqrt(max(0.0, 1 - (x / HEAD_R[0]) ** 2 - ((bz - HEAD_C.z) / HEAD_R[2]) ** 2))
        B.aim(brow, Vector((x - 0.019 * sx, by + 0.002, bz - 0.004 - 1.33)), Vector((x + 0.019 * sx, by + 0.006, bz + 0.003 - 1.33)))

    # ---- 长发（独立部件，有滞后摆动）
    tail_pivot = B.empty("HairTailPivot", head, loc=Vector((0, 0.115, 1.50 - 1.33)))
    tail = obj("HairTail", _strip_path_build(_hair_tail_points(), 0.13, 0.03, taper=(1.0, 0.35)), M["hair"],
               "outer", tail_pivot)
    parts["hair_tail"] = tail

    # ---- 发带（两条，独立部件，pose 时按相位重建）
    rib_start = Vector((0, 0.06, 1.70 - 1.33))
    rib_a = obj("RibbonA", _strip_path_build(_ribbon_points(rib_start, RIB_LEN[0], 0.0, 0.0, 1.0), RIB_W[0], 0.008,
                                             twist=2.4, taper=(0.8, 1.0)), M["ribbon"], "inner", head)
    rib_b = obj("RibbonB", _strip_path_build(_ribbon_points(rib_start, RIB_LEN[1], 1.3, 0.0, 1.0, spread=-0.25),
                                             RIB_W[1], 0.008, twist=-2.0, taper=(0.8, 1.0)), M["ribbon"], "inner", head)
    parts["ribbon"] = (rib_a, rib_b, rib_start)

    # ---- 背剑：剑柄在左肩上方
    sw = B.empty("Sword", body)
    d = (SWORD_TIP - SWORD_POMMEL).normalized()
    P = SWORD_POMMEL

    def seg(name, t0, t1, r0, r1, mat, line="inner", segs=10):
        o = obj(name, B.cylinder(r0, r1, (t1 - t0), segs), mat, line, sw)
        B.aim(o, P + d * t0, P + d * t1)
        return o

    obj("Pommel", B.uv_sphere(0.022, 10, 6), M["gold"], "inner", sw, loc=P)
    seg("Grip", 0.012, 0.165, 0.015, 0.015, M["cap"])
    guard = obj("Guard", B.uv_sphere(1.0, 12, 6, scale=(0.065, 0.022, 0.016)), M["gold"], "inner", sw)
    guard.location = P + d * 0.175
    guard.rotation_mode = "QUATERNION"
    guard.rotation_quaternion = Vector((0, 0, 1)).rotation_difference(d)
    seg("Scabbard", 0.19, (SWORD_TIP - P).length, 0.026, 0.021, M["scabbard"], "outer", 12)
    seg("Throat", 0.19, 0.235, 0.030, 0.030, M["gold"])
    seg("Chape", (SWORD_TIP - P).length - 0.05, (SWORD_TIP - P).length + 0.01, 0.025, 0.012, M["gold"])
    st = B.empty("SwordTasselPivot", sw, loc=P)
    obj("SwordTasselCord", B.cylinder(0.004, 0.004, 0.06, 6), M["tassel"], "none", st, loc=(0.0, 0.0, -0.03))
    obj("SwordTassel", B.cylinder(0.007, 0.022, 0.085, 8), M["tassel"], "none", st, loc=(0.0, 0.0, -0.10))
    parts["sword_tassel"] = st

    sock_feet = B.empty("SocketFeet", root)
    sockets = {"lantern": sock_lantern, "feet": sock_feet}
    parts["sockets"] = sockets
    bpy.context.view_layer.update()
    pose_hero(parts, "idle", 0, 6)
    return root, parts, sockets


# ================================================================ 姿态
RIB_LEN = (0.95, 0.78)  # 两条发带的长度（米）
RIB_W = (0.075, 0.068)  # 宽度：有意加宽，128px 下约 3.5px，描内线后仍能看出朱砂色
IDLE_BREEZE = 0.3  # 静立时也有一点微风，发带离开后背，正面也能看到
WALK_STRIDE_M = 0.30  # 一步（单脚前后的总行程），一个循环走两步（脚被下摆盖住，只影响靴子摆动）
WALK_STRIDE_UNITS = 80  # style.py 约定：一轮 8 帧前进 80 单位（游戏速度约 118 单位/秒）
WALK_LIFT_M = 0.06
WALK_BOB_M = 0.012


def walk_stride_units() -> float:
    """一个走路循环（8 帧）前进的距离，游戏单位（按 style.py 输出约定取 80）。"""
    return WALK_STRIDE_UNITS


def pose_hero(parts: dict, anim: str, frame: int, n_frames: int):
    """设置一帧姿态（绝对值，可重复调用）。
    idle：呼吸起伏，发带/袖/灯笼轻摆。walk：双脚交替、身体起伏、下摆摆动，
    发带/袖子/发尾向后拖并滞后于步伐，灯笼滞后摆动。"""
    ph = 2 * math.pi * (frame % n_frames) / n_frames
    body, lp = parts["body"], parts["lantern"]
    sL, sR, armR = parts["sleeve_L"], parts["sleeve_R"], parts["arm_R"]
    for ob in (parts["foot_L"], parts["foot_R"]):
        ob.location.y, ob.location.z = 0.0, 0.0
    if anim == "walk":
        for key, off in (("foot_L", 0.0), ("foot_R", math.pi)):
            p = ph + off
            ft = parts[key]
            ft.location.y = -0.5 * WALK_STRIDE_M * math.cos(p)  # p=0 在前（-Y）
            ft.location.z = WALK_LIFT_M * max(0.0, -math.sin(p))  # 向前摆的半程抬脚
            ft.rotation_euler.x = math.radians(-12.0) * max(0.0, -math.sin(p))
        body.location.z = -WALK_BOB_M * math.cos(2 * ph)  # 双脚着地时最低
        body.rotation_euler.x = math.radians(3.0)  # 略前倾
        # 下摆摆幅很小：下摆是“脚点”测量的主体，摆大了会超过 FOOT_TOLERANCE_PX（1px）
        parts["skirt"].rotation_euler = (math.radians(0.8 * math.sin(ph - 0.6)), math.radians(0.5 * math.sin(ph)), 0)
        lag = ph - 0.9
        sL.rotation_euler = (math.radians(9.0 + 9.0 * math.sin(lag)), 0, math.radians(-2.0))
        sR.rotation_euler = (math.radians(6.0 + 4.0 * math.sin(lag + math.pi)), 0, 0)
        armR.rotation_euler = (math.radians(1.5 * math.sin(2 * ph)), 0, 0)
        lp.rotation_euler = (math.radians(12.0 + 7.0 * math.sin(ph - 1.2)), math.radians(4.0 * math.sin(2 * ph - 1.0)), 0)
        wind, rib_phase = 1.0, ph * 2
        tail_rot = math.radians(4.0 + 2.0 * math.sin(2 * ph - 1.0))
        parts["pendant"].rotation_euler = (math.radians(10 + 8 * math.sin(2 * ph - 1.0)), 0, 0)
        parts["sword_tassel"].rotation_euler = (math.radians(14 + 6 * math.sin(2 * ph - 1.4)), 0, 0)
    else:  # idle：呼吸
        for ft in (parts["foot_L"], parts["foot_R"]):
            ft.rotation_euler.x = 0.0
        breath = math.sin(ph)
        body.location.z = 0.004 * breath
        body.rotation_euler.x = 0.0
        parts["skirt"].rotation_euler = (0, 0, 0)
        sL.rotation_euler = (math.radians(1.5 * math.sin(ph - 0.8)), 0, 0)
        sR.rotation_euler = (math.radians(1.0 * math.sin(ph - 0.8)), 0, 0)
        armR.rotation_euler = (math.radians(0.8 * breath), 0, 0)
        lp.rotation_euler = (math.radians(2.5 * math.sin(ph - 1.0)), math.radians(1.5 * math.cos(ph)), 0)
        wind, rib_phase = IDLE_BREEZE, ph
        tail_rot = math.radians(1.0 * math.sin(ph - 1.2))
        parts["pendant"].rotation_euler = (math.radians(2 * math.sin(ph - 1.0)), 0, 0)
        parts["sword_tassel"].rotation_euler = (math.radians(3 * math.sin(ph - 1.4)), 0, 0)
    parts["hair_tail"].parent.rotation_euler = (tail_rot, 0, 0)

    rib_a, rib_b, start = parts["ribbon"]
    _replace_mesh(rib_a, _strip_path_build(_ribbon_points(start, RIB_LEN[0], rib_phase, wind, 1.0), RIB_W[0], 0.008,
                                           twist=2.4, taper=(0.8, 1.0)))
    _replace_mesh(rib_b, _strip_path_build(_ribbon_points(start, RIB_LEN[1], rib_phase + 1.3, wind, 1.0, spread=-0.25),
                                           RIB_W[1], 0.008, twist=-2.0, taper=(0.8, 1.0)))
    _replace_mesh(parts["hair_tail"], _strip_path_build(_hair_tail_points(rib_phase, wind), 0.13, 0.03,
                                                        taper=(1.0, 0.35)))
    tal, mark, ttop = parts["talisman"]
    _replace_mesh(tal, _talisman_build(ttop, rib_phase + 0.6, wind))
    _replace_mesh(mark, _talisman_mark_build(ttop, rib_phase + 0.6, wind))
    bpy.context.view_layer.update()
