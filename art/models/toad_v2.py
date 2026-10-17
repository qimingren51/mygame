"""金蟾（精修三维）：三条腿的圆胖金蟾，嘴里衔一枚方孔铜钱。

设定（LORE 附录）：刘海戏的那只吐钱的金蟾。长夜里它改吞魂火和钱，见了守灯人就跑。
外形（世界观会话）：三条腿的圆胖蟾蜍，嘴里衔一枚方孔铜钱，背上的疙瘩是一枚枚铜钱，通体金黄。
跑起来铜钱叮当往下掉。可爱、滑稽、带点贼。
造型：一团圆滚滚的金身子（满身小疙瘩），宽扁的大嘴横着咧开、衔着一枚大铜钱（钱面朝镜头）；头顶一对鼓眼，
上眼皮耷拉下来、眼珠斜着往后瞟（贼）；背上嵌着七枚铜钱当疙瘩；前面两条短胳膊，后面只有一条后腿（三足金蟾）。
动画（只画 E）move 6 帧（10 fps）：一蹦一蹦地逃：0 蹲下蓄劲、1 后腿一蹬、2 腾空（背上掉下一枚钱）、
3 往下落、4 落地压扁、5 收腿；掉下来的钱在后面翻着落地。
帧 192²（2 倍；原 160²，一蹦一落、掉钱要地方），锚点 (0.5, 0.875)。挂点 eyes。

    root, parts, sockets = build_toad()
    pose_toad(parts, "move", i, 6)
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
EYE = "#FFF1C2"
GOLD_STOPS = [(0.00, "#261503"), (0.16, "#442607"), (0.32, "#71430E"), (0.47, "#9F6516"), (0.61, "#C78A20"),
              (0.74, "#E2AC36"), (0.87, "#F2CE62"), (1.00, "#FFEBA6")]  # 金：暗部焦褐、中间赤金、亮部淡金
COIN_STOPS = [(0.00, "#24160A"), (0.25, "#55340E"), (0.5, "#8E5C1C"), (0.72, "#C08A30"), (0.88, "#E2B456"),
              (1.00, "#F6DC90")]  # 铜钱：比身子红一点、暗一点
EYE_STOPS = [(0.0, "#5A3A08"), (0.5, "#C89A2A"), (1.0, "#F8E08A")]
LID_STOPS = [(0.0, "#3A2408"), (0.5, "#8A5E16"), (1.0, "#D6A63A")]
RIM = S.mix("#FFF2C8", I["qing"], 0.15)
STEP = 0.3


def _rot_z(deg):
    a = math.radians(deg)
    c, s = math.cos(a), math.sin(a)
    return np.array([[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]])


def pose_params(i, n=6):
    """每帧：身子的抬高 lift、仰角 tilt（抬头为正）、压扁 squash（<1 压扁）、后腿伸直 kick（0 收着 → 1 蹬直）、
    前腿往前伸 reach、掉下来的钱（在身后的位置、转角；None 没有）。"""
    T = [  # lift, tilt, squash, kick, reach, coin
        (0.0, -4.0, 0.9, 0.0, 0.0, None),
        (2.4, 14.0, 1.06, 0.85, -0.3, None),
        (7.0, 6.0, 1.08, 1.0, 0.4, ((-6.0, 15.0), 30.0)),
        (5.0, -10.0, 1.02, 0.6, 1.0, ((-10.0, 9.0), 110.0)),
        (0.4, -6.0, 0.86, 0.2, 0.6, ((-13.0, 3.2), 200.0)),
        (0.0, -2.0, 0.95, 0.05, 0.1, ((-14.5, 1.0), 270.0)),
    ]
    lift, tilt, squash, kick, reach, coin = T[i]
    return {"lift": lift, "tilt": tilt, "squash": squash, "kick": kick, "reach": reach, "coin": coin,
            "ph": 2 * math.pi * i / n}


BACK_Z = 3.5  # 整个往后（离镜头远）挪一点：锚点下方地方少，近镜头的那只手不能出画


class Pose:
    """身子局部（x 前、y 上、z 左右；静止时肚皮贴地）→ 设计稿三维：绕肚子中心仰、压扁、抬高。"""

    def __init__(self, p):
        self.c = np.array([0.0, 8.0, 0.0])
        self.R = _rot_z(p["tilt"])
        self.sq = np.array([1.0 / math.sqrt(p["squash"]), p["squash"], 1.0 / math.sqrt(p["squash"])])
        self.lift = np.array([0.0, p["lift"], BACK_Z])

    def fwd(self, P):
        P = np.asarray(P, np.float64)
        return ((P - self.c) * self.sq) @ self.R.T + self.c + self.lift

    def inv(self, Q):
        Q = np.asarray(Q, np.float64)
        return ((Q - self.lift - self.c) @ self.R) / self.sq + self.c


# ---------------------------------------------------------------- 身子（局部）
EYE_C = [np.array([6.8, 13.4, -4.5]), np.array([6.8, 13.4, 4.5])]  # 鼓眼（近、远）
BACK_COINS = [(-3.5, 14.0, -2.8), (1.2, 14.2, 1.8), (-7.8, 11.8, 1.2), (-1.4, 12.2, -7.0), (3.0, 12.4, -6.6),
              (-6.6, 10.4, -6.4), (-2.6, 13.6, 5.8)]  # 背上的钱（局部，大约在背的表面上）


def body_sdf(p):
    d = V2.sd_ellipsoid(p, (-1.0, 7.6, 0.0), (11.0, 6.8, 9.6))  # 圆滚滚、扁扁的身子
    d = V2.smin(d, V2.sd_ellipsoid(p, (7.8, 8.0, 0.0), (6.4, 4.4, 8.4)), 2.4)  # 宽扁的头
    d = V2.smin(d, V2.sd_ellipsoid(p, (0.0, 5.2, 0.0), (10.2, 4.8, 9.8)), 2.0)  # 往下坠的肚子
    for c in EYE_C:  # 眼包：头顶鼓起两个包
        d = V2.smin(d, V2.sd_ellipsoid(p, c - np.array([0.2, 1.4, 0.0]), (2.9, 2.4, 2.6)), 1.2)
    d = d + 0.14 * V2.wave_noise(p, 1.3, seed=31) + 0.07 * V2.wave_noise(p, 2.6, seed=32)  # 一身小疙瘩
    return d


def legs_sdf(p, k):
    """两条前腿 + 一条后腿（局部）。k = (kick, reach)。"""
    kick, reach = k
    d = None
    for z in (-1, 1):  # 前腿：肩 → 肘 → 手（手掌趴地、指头张开）
        sh = np.array([5.6, 6.6, 7.4 * z])
        el = np.array([8.4 + 2.0 * reach, 3.6 + 1.0 * reach, 8.6 * z])
        hd = np.array([10.4 + 3.4 * reach, 0.8 + 0.6 * reach, 8.0 * z])
        v = V2.smin(V2.sd_round_cone(p, sh, el, 2.5, 1.8), V2.sd_round_cone(p, el, hd, 1.8, 1.3), 0.7)
        for f in (-1, 0, 1):
            tip = hd + np.array([1.9, -0.5, 1.2 * f])
            v = V2.smin(v, V2.sd_round_cone(p, hd, tip, 0.85, 0.65), 0.3)
        d = v if d is None else np.minimum(d, v)
    # 后腿（只有一条，在身子后面正中）：大腿 → 膝 → 脚（蹬直时往后伸）
    hip = np.array([-8.0, 6.0, 0.0])
    knee = np.array([-3.6 - 6.4 * kick, 2.6 + 1.2 * kick, 0.0])
    foot = np.array([-6.8 - 8.0 * kick, 0.8 + 1.8 * kick, 0.0])  # 收着时脚掌塞在屁股底下
    v = V2.smin(V2.sd_round_cone(p, hip, knee, 3.4, 2.0), V2.sd_round_cone(p, knee, foot, 2.0, 1.2), 0.8)
    toe_dir = np.array([-1.0, -0.2 * (1 - kick), 0.0])
    for f in (-1, 0, 1):
        v = V2.smin(v, V2.sd_round_cone(p, foot, foot + toe_dir * 2.4 + np.array([0.0, 0.0, 1.1 * f]), 0.8, 0.5), 0.3)
    d = np.minimum(d, v)
    return d + 0.12 * V2.wave_noise(p, 1.6, seed=33)


def body_attrs(P):
    """zone：肚皮、下巴淡（往亮里推），背上一块块深的斑。"""
    x, y, z = P[:, 0], P[:, 1], P[:, 2]
    belly = np.clip((7.0 - y) / 5.0, 0, 1) * 0.45
    spots = np.clip(V2.wave_noise(P, 0.7, seed=35) - 0.3, 0, 1) * 0.9 * np.clip((y - 8.0) / 4.0, 0, 1)
    return {"zone": list(belly - spots)}


def coin_arrays(center, normal, r=2.0, h=0.42, xform=None, hole=True, rim=True):
    """一枚方孔铜钱（圆饼，中间方孔，钱沿一道凸棱）：中心、朝向（法线），局部 → 设计稿三维用 xform。
    返回 (钱身, 方孔) 两组模型坐标的数组。"""
    n = np.asarray(normal, np.float64)
    n /= np.linalg.norm(n)
    a = np.cross(n, [0.0, 1.0, 0.0])
    if np.linalg.norm(a) < 1e-3:
        a = np.cross(n, [1.0, 0.0, 0.0])
    a /= np.linalg.norm(a)
    b = np.cross(n, a)
    c = np.asarray(center, np.float64)
    nu = 28
    V, F, zone = [], [], []

    def ring(rad, off, zz):
        out = []
        for k in range(nu):
            t = 2 * math.pi * k / nu
            V.append(c + (a * math.cos(t) + b * math.sin(t)) * rad + n * off)
            zone.append(zz)
            out.append(len(V) - 1)
        return out
    # 正面：外沿凸起一圈、中间平；背面平
    r_out_f, r_in_f = ring(r, h, 0.1), ring(r * 0.78, h * 0.55, -0.15)
    r_out_b = ring(r, -h, -0.1)
    c_f = len(V); V.append(c + n * h * 0.55); zone.append(0.0)
    c_b = len(V); V.append(c - n * h); zone.append(-0.1)
    for k in range(nu):
        j = (k + 1) % nu
        F.append((r_out_f[k], r_out_f[j], r_in_f[j], r_in_f[k]))
        F.append((r_in_f[k], r_in_f[j], c_f))
        F.append((r_out_b[j], r_out_b[k], c_b))
        F.append((r_out_b[k], r_out_b[j], r_out_f[j], r_out_f[k]))
    Vw = np.asarray(V)
    if xform is not None:
        Vw = xform(Vw)
    body = (V2.d3m(Vw), [f[::-1] for f in F], {"zone": zone})
    holes = None
    if hole:
        q = r * 0.26
        corners = [c + n * (h * 0.55 + 0.05) + (a * sx + b * sy) * q for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
        Hw = np.asarray(corners)
        if xform is not None:
            Hw = xform(Hw)
        holes = (V2.d3m(Hw), [(3, 2, 1, 0)], {})
    return body, holes


# ---------------------------------------------------------------- 组装
def build_toad():
    root = B.empty("TDRoot")
    body = B.empty("TDBody", root)
    m_gold = V2.paint_material("TDGold", GOLD_STOPS, wash=0.26, wash_scale=3.0, seed=81.0, shade_attr="zone",
                               shade_gain=1.0, rim_hex=RIM, rim=0.65, rim_power=2.0, value_var=0.06, edge=0.34,
                               bias=-0.24)
    m_gold_far = V2.paint_material("TDGoldFar", GOLD_STOPS, wash=0.26, wash_scale=3.0, seed=82.0, shade_attr="zone",
                                   rim_hex=RIM, rim=0.3, value_var=0.06, edge=0.26, bias=-0.22)
    m_coin = V2.paint_material("TDCoin", COIN_STOPS, wash=0.2, wash_scale=4.0, seed=83.0, shade_attr="zone",
                               rim_hex="#FFF0C0", rim=0.45, value_var=0.05, edge=0.2, bias=0.05)
    V2.add_glow_const(m_coin, 0.3)  # 铜钱：夜里泛一层金光（追的就是它）
    m_hole = B.flat_material("TDHole", I["jiao"])
    m_eye = B.emissive_material("TDEyeBall", "#F6DE86", 1.0)  # 眼珠：夜里两点金光
    m_lid = V2.paint_material("TDLid", LID_STOPS, wash=0.15, seed=85.0, edge=0.15, rim_hex=RIM, rim=0.4, bias=0.1)
    m_pupil = B.flat_material("TDPupil", I["jiao"])
    m_glint = B.emissive_material("TDGlint", EYE, 1.0)
    m_mouth = B.flat_material("TDMouth", S.mix(I["jiao"], "#5A2E0A", 0.3))
    parts = {"root": root, "body": body, "dyn": {}}

    def dyn(name, mat, line="outer"):
        ob = V2.mesh_from_arrays(name, [(0, 0, 0), (0.001, 0, 0), (0, 0.001, 0)], [(0, 1, 2)], mat, line, body)
        parts["dyn"][name] = ob
        return ob

    for nm, mat, line in (("Body", m_gold, "outer"), ("LegsNear", m_gold, "outer"), ("LegsFar", m_gold_far, "outer"),
                          ("Coins", m_coin, "inner"), ("Holes", m_hole, "none"), ("EyeBalls", m_eye, "inner"),
                          ("Lids", m_lid, "inner"), ("Pupils", m_pupil, "none"), ("Glints", m_glint, "none"),
                          ("Mouth", m_mouth, "none"), ("Drop", m_coin, "inner"), ("DropHole", m_hole, "none")):
        dyn(nm, mat, line)
    bpy.data.collections[B.CUN_COLLECTION].objects.link(parts["dyn"]["Body"])  # 疙瘩：皴笔
    sock = B.empty("TDSocketEyes", body)
    parts["sock"] = sock
    parts["sockets"] = {"eyes": sock}
    pose_toad(parts, "move", 0, 6)
    return root, parts, parts["sockets"]


def pose_toad(parts, anim, frame, n):
    p = pose_params(frame, n)
    ps = Pose(p)
    D = parts["dyn"]
    groups = {k: [] for k in D}
    lo, hi = np.array([-16.0, -3.0, -14.0]), np.array([18.0, 30.0, 14.0])

    def b_fn(Q):
        return body_sdf(ps.inv(Q))

    def b_attrs(V):
        return body_attrs(ps.inv(V))
    groups["Body"].append(V2.sdf_arrays(b_fn, lo, hi, STEP, b_attrs))
    k = (p["kick"], p["reach"])

    def legs_fn(Q, near):
        q = ps.inv(Q)
        dd = legs_sdf(q, k)
        if near:  # 近的一半（z < 0）：前近腿 + 后腿；远的一半：前远腿
            return np.maximum(dd, q[..., 2] - 2.0)
        return np.maximum(dd, -q[..., 2] - 2.0)
    groups["LegsNear"].append(V2.sdf_arrays(lambda Q: legs_fn(Q, True), lo, hi, STEP,
                                            lambda V: {"zone": [0.1] * len(V)}))
    groups["LegsFar"].append(V2.sdf_arrays(lambda Q: legs_fn(Q, False), lo, hi, STEP,
                                           lambda V: {"zone": [0.0] * len(V)}))
    # 背上的钱：沿身子表面的法线朝外，嵌进去一半
    for c in BACK_COINS:
        c = np.asarray(c, np.float64)
        nrm = (c - np.array([-0.5, 8.4, 0.0])) / np.array([11.0, 7.6, 9.4]) ** 2
        cb, ch = coin_arrays(c - nrm / np.linalg.norm(nrm) * 0.15, nrm, r=1.9, h=0.45, xform=ps.fwd)
        groups["Coins"].append(cb)
        groups["Holes"].append(ch)
    # 嘴里衔的大钱：钱面朝镜头，下半截咬在嘴里
    mc = np.array([14.0, 6.8, -3.4])
    cb, ch = coin_arrays(mc, (0.3, 0.05, -1.0), r=3.3, h=0.5, xform=ps.fwd)
    groups["Coins"].append(cb)
    groups["Holes"].append(ch)
    # 嘴：宽扁的一道，从嘴角往前咧到钱（嘴角往上翘：得意）
    mouth = [(13.2, 7.6, -5.6), (11.4, 7.2, -7.2), (8.4, 7.3, -8.4), (5.6, 8.4, -8.6)]
    mw = ps.fwd(np.asarray(mouth))
    c2 = mw[:, :2] - np.array([0.0, 0.0])
    lat = -9.6 / 25.0  # 放在头最宽处的前面（扁带正对镜头，像在头上描的一笔）
    c2 = c2 - np.array([0.0, 12.5 * (lat - float(np.mean(mw[:, 2])) / 25.0)])  # 抵掉俯视的高低差
    groups["Mouth"].append(V2.strip_arrays(*V2.design_strip(c2, np.array([0.5, 0.75, 0.7, 0.35]), lat)))
    # 鼓眼：眼球 + 耷拉的上眼皮（贼）+ 斜着往后瞟的横瞳 + 一点亮光
    for far, c in enumerate(EYE_C):
        ball = lambda Q, c=c: V2.sd_ellipsoid(ps.inv(Q), c, (2.3, 2.2, 2.2))
        bl, bh = ps.fwd(np.asarray([c - 3.0, c + 3.0]))
        groups["EyeBalls"].append(V2.sdf_arrays(ball, np.minimum(bl, bh), np.maximum(bl, bh), 0.2,
                                                lambda V: {"zone": [0.0] * len(V)}))

        def lid(Q, c=c):
            q = ps.inv(Q)
            d = V2.sd_ellipsoid(q, c + np.array([0.0, 0.25, 0.0]), (2.55, 2.45, 2.45))
            cut = (q[..., 1] - (c[1] + 0.05)) * -1.0 + (q[..., 0] - c[0]) * 0.18  # 上半截盖住，往前略低
            return np.maximum(d, cut)
        groups["Lids"].append(V2.sdf_arrays(lid, np.minimum(bl, bh), np.maximum(bl, bh), 0.2,
                                            lambda V: {"zone": [0.0] * len(V)}))
        pc = ps.fwd(np.asarray([c + np.array([-0.5, -0.4, -2.05])]))[0]  # 瞳往后瞟（朝镜头那面）
        pts = []
        for t in np.linspace(0, 2 * math.pi, 16, endpoint=False):
            pts.append(pc + np.array([1.05 * math.cos(t), 0.45 * math.sin(t), 0.0]))
        P3 = np.asarray(pts)
        V = list(V2.d3m(P3)) + [V2.d3m(pc)]
        F = [(16, k2, (k2 + 1) % 16) for k2 in range(16)]
        groups["Pupils"].append((V, [f[::-1] for f in F], {}))
        if far == 0:
            g = ps.fwd(np.asarray([c + np.array([0.7, 0.05, -2.2])]))[0]
            gv = [V2.d3m(g + np.array([0.45 * math.cos(t), 0.4 * math.sin(t), -0.05])) for t in
                  np.linspace(0, 2 * math.pi, 10, endpoint=False)] + [V2.d3m(g + np.array([0, 0, -0.05]))]
            groups["Glints"].append((gv, [(10, (k2 + 1) % 10, k2) for k2 in range(10)], {}))
    e = ps.fwd(np.asarray([EYE_C[0] * 0.7 + EYE_C[1] * 0.3 + np.array([0.5, 0.0, 0.0])]))[0]
    parts["sock"].location = V2.d3m(e)
    # 掉下来的钱（在身后翻着落地）
    if p["coin"] is not None:
        (cx, cy), rot = p["coin"]
        r = math.radians(rot)
        cb, ch = coin_arrays(np.array([cx, cy, -2.0]), (math.sin(r) * 0.6, math.cos(r) * 0.6, -0.8), r=1.9, h=0.45)
        groups["Drop"].append(cb)
        groups["DropHole"].append(ch)
    for kname, arrs in groups.items():
        ob = D[kname]
        if arrs:
            V_, F_, A_ = V2.merge_arrays(arrs)
            K.replace_mesh(ob, V2.arrays_build(V_, F_), smooth=kname not in ("Holes", "DropHole", "Pupils", "Glints",
                                                                              "Mouth"), attrs=A_)
            ob.hide_render = False
        else:
            ob.hide_render = True
    bpy.context.view_layer.update()
