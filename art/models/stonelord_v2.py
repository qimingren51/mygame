"""石将（精修三维）：陵墓神道两旁的石翁仲。

设定（LORE 附录）：替死去的主人站了几百年岗，长夜里还在站，见了活人就当成盗墓的。
外形（世界观会话）：方正高大，戴盔披甲，双手持一柄长刀，面目被风化得模糊，青苔从脚往上爬，走动时掉石屑。
主色青灰石色；庄严、冷。
造型：比主角高一头的方石人。头盔圆顶、顶上一颗宝珠一根尖，盔沿一道箍、脑后垂着护颈；脸被风雨磨平了，
只剩眉骨、鼻梁一点起伏，眼缝里两点暗暗的暖光。胸前两面护心镜，肩上压着披膊，腰上一道宽带、带扣是块兽面牌；
下身一圈甲裙（一排排甲片刻出来的横槽）。双手叠在胸前拄着一柄长刀，刀尖朝下、离地一点。
石头：青灰，暗部偏暖、亮部偏冷；表面风化出起伏，刻槽是一道道焦墨；青苔从靴子往上爬到甲裙下摆。
身子朝镜头转 YAW（3/4 侧面），看得见正面的护心镜、刀、脸。
动画（只画 E）move 8 帧（6 fps）：石头人一步一步地挪：抬脚很低、落脚很重，身子一步一沉、往支撑脚那边歪，
刀跟着手晃；落脚那两帧甲裙底下崩出几粒石屑。
帧 320²（2 倍），锚点 (0.5, 0.8)（大妖物）。挂点 eyes。

    root, parts, sockets = build_stonelord()
    pose_stonelord(parts, "move", i, 8)
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import bpy
import numpy as np
from mathutils import Vector

ART = Path(__file__).resolve().parents[1]
for p in (ART, ART / "models", ART / "post"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
from style import bstyle as B  # noqa: E402
from style import style as S  # noqa: E402
import kit as K  # noqa: E402
import v2kit as V2  # noqa: E402

I = S.INK
EYE = "#FFB46B"
EYE_HOT = "#FFE4C0"
GLOW = "#FFB46B"
# 青灰石（d 从暗到亮）：暗部偏暖的灰褐 → 青灰 → 亮部偏冷发白
STONE_STOPS = [(0.00, "#1E1F22"), (0.16, "#2A2D30"), (0.32, "#3B4246"), (0.48, "#4F5A5E"), (0.62, "#647174"),
               (0.76, "#7E8B8C"), (0.88, "#9AA5A2"), (1.00, "#B9C0B8")]
RIM = S.mix("#C8D8DC", I["qing"], 0.3)
HK = 1.22  # 头盔、脸放大（翁仲头大，游戏尺寸下读得出盔和脸）
YAW = 50.0  # 身子朝镜头转（3/4 侧面：正面的护心镜、刀、脸都看得见）
STEP = 0.42


# ---------------------------------------------------------------- 骨架 / 姿态
def pose_params(i, n):
    """move：步态相位 ph；两脚的前后、抬起；身子的下沉、往支撑脚那边歪（roll，绕前后轴）、前后点头（pitch）。"""
    ph = 2 * math.pi * i / n
    feet = {}
    for far, off in ((False, 0.0), (True, math.pi)):
        s = math.sin(ph + off)
        lift = max(0.0, math.cos(ph + off)) ** 2 * 1.6
        feet[far] = (2.6 * s, lift)
    sink = 0.9 * (1 - abs(math.cos(ph)))  # 两脚都着地的时候最低
    return {"ph": ph, "feet": feet, "sink": sink, "roll": 3.0 * math.sin(ph), "pitch": 1.2 * math.sin(2 * ph),
            "chips": i in (2, 6), "blade": 1.2 * math.sin(ph + 0.6)}


def _rot_x(deg):
    a = math.radians(deg)
    c, s = math.cos(a), math.sin(a)
    return np.array([[1.0, 0.0, 0.0], [0.0, c, -s], [0.0, s, c]])


def _rot_z(deg):
    a = math.radians(deg)
    c, s = math.cos(a), math.sin(a)
    return np.array([[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]])


class Frame:
    """身体局部（x 前、y 上、z 左右）→ 设计稿三维：先按 roll / pitch 绕胯转、下沉，再整体绕竖轴转 YAW。"""

    def __init__(self, p):
        self.R_body = _rot_z(-p["pitch"]) @ _rot_x(p["roll"])
        self.hip = np.array([0.0, 20.0, 0.0])
        self.sink = p["sink"]
        self.R_yaw = V2.rot_y(YAW)

    def body(self, P):  # 上半身（随身子摆）
        P = np.asarray(P, np.float64)
        q = (P - self.hip) @ self.R_body.T + self.hip - np.array([0.0, self.sink, 0.0])
        return q @ self.R_yaw.T

    def ground(self, P):  # 脚（不随身子摆）
        return np.asarray(P, np.float64) @ self.R_yaw.T

    def body_inv(self, Q):  # 设计稿三维 → 上半身局部（SDF 在局部里算）
        q = np.asarray(Q, np.float64) @ self.R_yaw
        q = q + np.array([0.0, self.sink, 0.0]) - self.hip
        return q @ self.R_body + self.hip

    def ground_inv(self, Q):
        return np.asarray(Q, np.float64) @ self.R_yaw


# ---------------------------------------------------------------- 上半身（局部）
def tapered_box(p, y0, y1, h0, h1, cx=0.0, r=1.2):
    """上下两头大小不同的方块（y0 → y1，半宽 (x, z) 从 h0 变到 h1），近似的有符号距离。"""
    t = np.clip((p[..., 1] - y0) / (y1 - y0), 0, 1)
    hx = h0[0] + (h1[0] - h0[0]) * t
    hz = h0[1] + (h1[1] - h0[1]) * t
    q = np.stack([np.abs(p[..., 0] - cx) - hx + r, np.abs(p[..., 1] - (y0 + y1) / 2) - (y1 - y0) / 2 + r,
                  np.abs(p[..., 2]) - hz + r], -1)
    return np.linalg.norm(np.maximum(q, 0.0), axis=-1) + np.minimum(q.max(-1), 0.0) - r


def upper_sdf(p):
    """甲裙、躯干、腰带、披膊、两臂、两手、颈、盔、脸（都在上半身局部里）。"""
    d = tapered_box(p, 7.2, 25.0, (9.8, 11.0), (7.0, 8.8), cx=0.6, r=2.8)  # 甲裙（往下张）
    d = np.minimum(d, V2.sd_box(p, (9.0, 15.6, 0.0), (1.0, 7.4, 2.8), rot=_rot_z(-8.0), r=0.6))  # 前裆（一块护腹的长甲）
    d = V2.smin(d, tapered_box(p, 24.0, 42.0, (6.6, 8.6), (7.2, 9.8), cx=0.4, r=2.2), 1.2)  # 躯干
    d = np.minimum(d, V2.sd_box(p, (0.6, 25.4, 0.0), (8.2, 1.6, 10.2), r=0.8))  # 腰带
    for z in (-1, 1):
        sh = V2.sd_box(p, (0.4, 40.2, 10.4 * z), (4.6, 2.8, 3.2), rot=_rot_x(-24.0 * z), r=2.0)  # 披膊
        d = np.minimum(d, sh)
        a, b, c = np.array([0.6, 39.0, 10.4 * z]), np.array([2.2, 31.0, 10.6 * z]), np.array([8.0, 34.6, 2.2 * z])
        d = V2.smin(d, V2.sd_round_cone(p, a, b, 3.0, 2.7), 0.6)  # 上臂
        d = V2.smin(d, V2.sd_round_cone(p, b, c, 2.7, 2.2), 0.6)  # 小臂往胸前合
    d = np.minimum(d, V2.sd_box(p, (9.2, 36.6, -0.9), (1.9, 1.9, 1.7), r=0.8))  # 近手（压在上面）
    d = np.minimum(d, V2.sd_box(p, (9.0, 34.6, 0.9), (1.9, 1.8, 1.7), r=0.8))  # 远手
    d = V2.smin(d, V2.sd_round_cone(p, (0.6, 41.5, 0.0), (1.2, 45.5, 0.0), 3.4, 3.0), 0.8)  # 颈
    # 盔（放大 HK 倍，绕颈）：圆顶 + 盔沿一道箍 + 前沿一道檐 + 两边护耳 + 脑后护颈 + 顶上一颗宝珠；
    # 脸：被风雨磨平了，只剩眉骨、鼻梁、颧骨一点起伏
    q = (p - np.array([1.0, 45.0, 0.0])) / HK + np.array([1.0, 45.0, 0.0])
    hd = V2.sd_ellipsoid(q, (1.0, 50.4, 0.0), (5.2, 5.6, 5.0))
    hd = np.minimum(hd, V2.sd_ellipsoid(q, (1.2, 47.9, 0.0), (5.8, 1.2, 5.6)))
    hd = np.minimum(hd, V2.sd_box(q, (5.4, 48.6, 0.0), (1.4, 0.45, 3.6), rot=_rot_z(-12.0), r=0.3))  # 前檐
    for z in (-1, 1):
        hd = np.minimum(hd, V2.sd_box(q, (0.6, 45.6, 4.9 * z), (2.6, 2.6, 0.7), r=0.5))  # 护耳
    hd = V2.smin(hd, V2.sd_box(q, (-2.4, 45.2, 0.0), (2.4, 3.2, 5.2), rot=_rot_z(-14.0), r=1.3), 0.8)
    hd = np.minimum(hd, V2.sd_ellipsoid(q, (0.9, 56.0, 0.0), (1.5, 1.4, 1.5)))
    hd = np.minimum(hd, V2.sd_round_cone(q, (0.9, 56.8, 0.0), (0.9, 58.0, 0.0), 0.8, 0.45))
    face = V2.sd_box(q, (4.2, 45.4, 0.0), (1.9, 2.6, 3.3), r=1.4)
    face = V2.smin(face, V2.sd_ellipsoid(q, (5.7, 47.2, 0.0), (1.0, 0.75, 3.0)), 0.5)  # 眉骨
    face = V2.smin(face, V2.sd_ellipsoid(q, (6.1, 45.6, 0.0), (1.1, 1.7, 0.95)), 0.5)  # 鼻梁
    for z in (-1, 1):
        face = V2.smin(face, V2.sd_ellipsoid(q, (5.4, 44.6, 2.0 * z), (0.9, 1.0, 1.2)), 0.5)  # 颧
    hd = V2.smin(hd, face, 0.8) * HK
    d = np.minimum(d, hd)
    d = d + 0.32 * V2.wave_noise(p, 0.55, seed=3) + 0.12 * V2.wave_noise(p, 1.6, seed=5)  # 风化
    return d


def sd_disc_x(p, c, R, h, rr=0.3):
    """朝 x 的圆饼（半径 R、半厚 h、边上倒角 rr）。"""
    q = p - np.asarray(c, np.float64)
    dr = np.sqrt(q[..., 1] ** 2 + q[..., 2] ** 2) - (R - rr)
    dh = np.abs(q[..., 0]) - (h - rr)
    return np.minimum(np.maximum(dr, dh), 0.0) + np.sqrt(np.maximum(dr, 0) ** 2 + np.maximum(dh, 0) ** 2) - rr


def mirrors_sdf(p):
    """胸前两面护心镜（圆饼，中间一颗乳钉）。"""
    d = None
    for z in (-1, 1):
        v = sd_disc_x(p, (7.4, 35.6, 3.7 * z), 2.9, 0.55, 0.3)
        v = np.minimum(v, V2.sd_ellipsoid(p, (7.95, 35.6, 3.7 * z), (0.5, 0.8, 0.8)))
        d = v if d is None else np.minimum(d, v)
    return d + 0.05 * V2.wave_noise(p, 1.2, seed=9)


def legs_sdf(p, feet_local):
    """两腿（甲裙底下露出一截）+ 靴子（不随身子摆，脚在地上）。feet_local：{far: (x, 抬起)}。"""
    d = None
    for far, (fx, lift) in feet_local.items():
        z = 4.6 if far else -4.6
        ank = np.array([fx + 0.4, 3.6 + lift, z])
        v = V2.sd_round_cone(p, np.array([0.4, 12.0, z * 0.9]), ank, 2.7, 2.3)
        v = V2.smin(v, V2.sd_box(p, ank + np.array([1.4, -1.6 + 0.0, 0.0]), (3.6, 1.9, 2.5), r=0.9), 0.8)
        d = v if d is None else np.minimum(d, v)
    return d + 0.25 * V2.wave_noise(p, 0.6, seed=4)


def carve_attrs(P_local):
    """刻槽（zone 往暗里压成一道道焦墨）和青苔（moss）：按上半身局部的位置算。"""
    x, y, z = P_local[:, 0], P_local[:, 1], P_local[:, 2]
    zone = np.zeros(len(P_local))
    # 甲裙：一排排鱼鳞似的甲片（下沿是一道道弧，错开半片）
    sk = (y > 7.4) & (y < 23.6)
    ang = np.arctan2(z, x - 0.6)
    row0 = (y - 7.4) / 2.4
    col = ang / (2 * math.pi) * 14 + 0.5 * (np.floor(row0) % 2)
    fc = col - np.floor(col)
    row = row0 - 0.22 * np.sin(math.pi * fc) ** 2  # 甲片下沿往下兜成弧
    fr = row - np.floor(row)
    hgroove = np.exp(-((np.minimum(fr, 1 - fr)) / 0.075) ** 2)
    vgroove = np.exp(-((np.minimum(fc, 1 - fc)) / 0.05) ** 2) * (fr > 0.2) * (fr < 0.75) * 0.55
    zone -= sk * np.maximum(hgroove, vgroove) * 0.9
    # 躯干下半截（腹甲）：几道横槽
    ab = (y > 27.0) & (y < 32.5)
    r2 = (y - 27.0) / 1.8
    f2 = r2 - np.floor(r2)
    zone -= ab * np.exp(-((np.minimum(f2, 1 - f2)) / 0.09) ** 2) * 0.85
    # 腰带上下沿、盔沿
    zone -= np.exp(-((y - 23.9) / 0.25) ** 2) * 0.7 + np.exp(-((y - 26.9) / 0.25) ** 2) * 0.7
    # 雨水冲出来的一道道竖着的暗痕（风化）
    st = V2.wave_noise(np.stack([x * 1.6, y * 0.12, z * 1.6], -1), 1.0, seed=21)
    zone -= np.clip(st - 0.25, 0, 1) * 0.5
    # 青苔：从脚往上爬（下摆最浓），斑驳
    noise = V2.wave_noise(P_local, 0.9, seed=11)
    moss = np.clip((11.0 - y) / 8.0 + 0.55 * noise, 0, 1) ** 1.6
    moss += np.clip(0.6 * noise - 0.42, 0, 1) * (y < 30)  # 身上零星几块
    return {"zone": list(zone), "moss": list(np.clip(moss, 0, 1))}


def blade_outline():
    """长刀（刀面朝前：轮廓在局部的 z-y 平面里，z 是刀宽，刃在近镜头的那边）：往刀尖略宽，刀尖斜削。"""
    return [(2.0, 33.4), (-2.0, 33.4), (-3.0, 20.0), (-3.6, 8.0), (-3.1, 3.4), (0.6, 1.2), (2.0, 4.4)]


def tint_by_attr(m, attr, rgb_mul, amount=1.0):
    nt = m.node_tree
    N, Lk = nt.nodes, nt.links
    emi = next(n for n in N if n.type == "EMISSION")
    src = emi.inputs["Color"].links[0].from_socket
    at = N.new("ShaderNodeAttribute"); at.attribute_type = "GEOMETRY"; at.attribute_name = attr
    fk = N.new("ShaderNodeMath"); fk.operation = "MULTIPLY"; fk.inputs[1].default_value = amount; fk.use_clamp = True
    Lk.new(at.outputs["Fac"], fk.inputs[0])
    mx = N.new("ShaderNodeMix"); mx.data_type = "RGBA"; mx.blend_type = "MULTIPLY"
    Lk.new(fk.outputs["Value"], B.sock(mx.inputs, "Factor_Float"))
    Lk.new(src, B.sock(mx.inputs, "A_Color"))
    B.sock(mx.inputs, "B_Color").default_value = (*rgb_mul, 1.0)
    Lk.new(B.sock(mx.outputs, "Result_Color"), emi.inputs["Color"])
    return m


# ---------------------------------------------------------------- 组装
def build_stonelord():
    root = B.empty("SLRoot")
    body = B.empty("SLBody", root)
    common = dict(wash=0.34, wash_scale=2.8, shade_attr="zone", shade_gain=1.0, streak=0.1, streak_scale=(3.0, 3.0),
                  value_var=0.09, edge=0.3)
    m_stone = V2.paint_material("SLStone", STONE_STOPS, seed=71.0, rim_hex=RIM, rim=0.55, rim_power=2.3, bias=-0.12,
                                **common)
    tint_by_attr(m_stone, "moss", (0.7, 0.96, 0.6), 1.0)
    m_legs = V2.paint_material("SLStoneLegs", STONE_STOPS, seed=72.0, rim_hex=RIM, rim=0.4, bias=-0.14, **common)
    tint_by_attr(m_legs, "moss", (0.7, 0.96, 0.6), 0.9)
    m_blade = V2.paint_material("SLBlade", STONE_STOPS, seed=73.0, rim_hex=RIM, rim=0.6, rim_power=2.0, bias=0.06,
                                wash=0.25, wash_scale=3.0, value_var=0.06, edge=0.2, shade_attr="zone")
    m_mirror = V2.paint_material("SLMirror", STONE_STOPS, seed=74.0, rim_hex=RIM, rim=0.6, bias=0.1, wash=0.25,
                                 value_var=0.06, edge=0.35)
    m_eye = B.emissive_material("SLEye", EYE, 1.0)
    m_hot = B.emissive_material("SLEyeHot", EYE_HOT, 1.0)
    parts = {"root": root, "body": body, "dyn": {}}

    def dyn(name, mat, line="outer"):
        ob = V2.mesh_from_arrays(name, [(0, 0, 0), (0.001, 0, 0), (0, 0.001, 0)], [(0, 1, 2)], mat, line, body)
        parts["dyn"][name] = ob
        return ob

    for nm, mat, line in (("Upper", m_stone, "outer"), ("Legs", m_legs, "outer"), ("Mirrors", m_mirror, "inner"),
                          ("Blade", m_blade, "outer"), ("Chips", m_stone, "inner")):
        dyn(nm, mat, line)
    bpy.data.collections[B.CUN_COLLECTION].objects.link(parts["dyn"]["Upper"])  # 风化的起伏：皴笔
    eyes = []
    for k, (mat, sc) in enumerate(((m_eye, 1.0), (m_hot, 0.5))):
        for z in (-1, 1):
            ob = B.mesh_object(f"SLEye{k}{z:+d}", K.ellipsoid((0.01, 0.034 * sc, 0.011 * sc), 10, 6), mat, "none", body)
            eyes.append((ob, z, sc))
    sock = B.empty("SLSocketEyes", body)
    parts.update(eyes=eyes, sock=sock)
    parts["sockets"] = {"eyes": sock}
    pose_stonelord(parts, "move", 0, 8)
    return root, parts, parts["sockets"]


def pose_stonelord(parts, anim, frame, n):
    p = pose_params(frame, n)
    fr = Frame(p)
    D = parts["dyn"]
    groups = {k: [] for k in D}
    # 上半身：在局部里算 SDF，网格在设计稿三维的包围盒里取
    lo, hi = np.array([-16.0, 4.0, -18.0]), np.array([18.0, 63.0, 18.0])
    # 包围盒按 YAW 转过以后放大一点（局部的盒子转了以后不再对齐坐标轴）
    corners = np.array([[x, y, z] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])])
    wc = fr.body(corners)
    glo, ghi = wc.min(0) - 1.0, wc.max(0) + 1.0

    def up_fn(Q):
        return upper_sdf(fr.body_inv(Q))

    def up_attrs(V):
        return carve_attrs(fr.body_inv(V))
    groups["Upper"].append(V2.sdf_arrays(up_fn, glo, ghi, STEP, up_attrs))

    def mi_fn(Q):
        return mirrors_sdf(fr.body_inv(Q))
    mlo, mhi = fr.body(np.array([[5.0, 31.0, -8.0]])).min(0) - 6, fr.body(np.array([[9.0, 40.0, 8.0]])).max(0) + 6
    groups["Mirrors"].append(V2.sdf_arrays(mi_fn, np.minimum(mlo, mhi), np.maximum(mlo, mhi), 0.3,
                                           lambda V: {"zone": [0.0] * len(V)}))
    # 腿、靴子：在地上（局部 = 只转 YAW）
    feet = p["feet"]

    def leg_fn(Q):
        q = fr.ground_inv(Q)
        q = q + np.array([0.0, 0.0, 0.0])
        return legs_sdf(q, feet)

    def leg_attrs(V):
        q = fr.ground_inv(V)
        return carve_attrs(q)
    llo, lhi = fr.ground(np.array([[-8.0, -1.0, -9.0], [10.0, 15.0, 9.0]]))
    groups["Legs"].append(V2.sdf_arrays(leg_fn, np.minimum(llo, lhi) - 4, np.maximum(llo, lhi) + 4, STEP, leg_attrs))
    # 长刀：跟着手（上半身局部），刀尖离地一点、随步子晃
    sw = p["blade"]

    def blade_xf(P):
        P = np.asarray(P, np.float64)
        piv = np.array([9.2, 35.6, 0.0])
        q = (P - piv) @ _rot_z(sw).T + piv
        return fr.body(q)

    def blade_face(P):  # 轮廓（z, y）+ 厚度（挤出方向当 x）→ 局部点：刀面朝前，刀身在手前面 x≈10.6
        P = np.asarray(P, np.float64)
        return blade_xf(np.stack([10.6 - P[:, 2], P[:, 1], P[:, 0]], -1))  # （x 取负：保持右手系，面朝外）
    V_, F_, A_ = V2.prism_arrays(blade_outline(), -0.34, 0.34, blade_face, edge_thin=0.55)
    A_["zone"] = [0.0] * len(V_)
    groups["Blade"].append((V_, F_, A_))
    # 刀柄、护手、刀首（和刀一起晃）
    for a, b, r0, r1 in (((10.6, 33.0, 0.0), (10.6, 34.2, 0.0), 2.4, 2.4), ((10.4, 34.2, 0.0), (9.6, 39.4, 0.0), 0.8, 0.8),
                         ((9.4, 39.2, 0.0), (9.4, 40.6, 0.0), 1.15, 0.5)):
        a3, b3 = blade_xf(np.array([a]))[0], blade_xf(np.array([b]))[0]
        P = V2.d3m(np.asarray([a3 + (b3 - a3) * t for t in np.linspace(0, 1, 4)]))

        def prof(t, r0=r0, r1=r1):
            r = (r0 + (r1 - r0) * t) / 25.0
            return r, r * 25.0 / V2.VZ, r * 25.0 / V2.VZ
        Vh, Fh, Ah = V2.tube_arrays([Vector(q) for q in P], prof, nu=12, nv=4)
        Ah["zone"] = [-0.2] * len(Vh)
        groups["Blade"].append((Vh, Fh, Ah))
    # 落脚那两帧：甲裙底下崩出几粒石屑
    if p["chips"]:
        rng = np.random.default_rng(frame)
        for k in range(4):
            c = fr.body(np.array([[rng.uniform(-6, 9), rng.uniform(3.0, 8.0), rng.uniform(-9, 0)]]))[0]
            r = rng.uniform(0.55, 0.95)

            def chip(Q, c=c, r=r, k=k):
                return V2.sd_box(Q, c, (r, r * 0.8, r * 0.9), rot=V2.rot_y(30.0 * k) @ _rot_x(25.0 * k), r=0.15)
            groups["Chips"].append(V2.sdf_arrays(chip, c - 2.0, c + 2.0, 0.22, lambda V: {"zone": [0.0] * len(V)}))
    # 眼：磨平了的脸上两道暗暗的暖光
    for ob, z, sc in parts["eyes"]:
        loc = np.array([[1.0 + (6.0 - 1.0) * HK, 45.0 + (46.5 - 45.0) * HK, 1.35 * z * HK]])
        q = fr.body(loc)[0]
        q = q + fr.R_yaw @ np.array([0.5, 0.0, 0.0])  # 往脸外挪一点，别埋进石头里
        ob.location = V2.d3m(q)
        ob.rotation_euler = (math.radians(8.0 * z), 0.0, 0.0)
    e = fr.body(np.array([[1.0 + 5.6 * HK, 45.0 + 1.5 * HK, 0.0]]))[0]
    parts["sock"].location = V2.d3m(e)
    for k, arrs in groups.items():
        ob = D[k]
        if arrs:
            V_, F_, A_ = V2.merge_arrays(arrs)
            K.replace_mesh(ob, V2.arrays_build(V_, F_), smooth=True, attrs=A_)
            ob.hide_render = False
        else:
            ob.hide_render = True
    bpy.context.view_layer.update()
