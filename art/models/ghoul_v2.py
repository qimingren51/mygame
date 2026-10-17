"""青面鬼（精修三维）：魁梧佝偻的大鬼。

设定（LORE 附录）：“青面獠牙”说的就是它。鬼门里出来的恶鬼头子，三年里吞了不少魂，个头大，血厚。
外形（世界观会话）：魁梧佝偻的大鬼，青灰皮肤，獠牙外翻，乱发，赤红眼。肚子鼓胀，吞下的魂光从肚皮里透出来。
冲锋时低头。主色青灰、赤；凶、压迫。
造型：比主角高一截、宽一倍。驼背像一座小山，头低低地探在前面（头顶比背还低）；大肚子往前下坠，肚皮发白、透着暖黄的魂光
（白天是一层暖色，夜里亮起来，光里有几道旋着的魂）；两条胳膊又粗又长、拳头垂到膝下，指头上是黑爪；两条罗圈短腿。
头：大下巴往前兜（地包天），两根獠牙从下颌翻出来往上挑，眉骨又厚又低，眼窝里两点赤红的眼，尖耳朵往后；
一头乱发（焦墨的几大笔）往后上方炸开。腰上一条破破烂烂的暗红布，草绳一系。
身子、四肢、头都是隐式曲面（v2kit.sdf_mesh：椭球和圆锥台平滑地并在一起，像捏出来的肌肉），各自一块，墨线分得开。
动画（只画 E）：
  move   8 帧：沉重地一步一步挪，身子一步一沉、左右晃，两臂和腿反着甩，拳头擦着地。
  charge 6 帧（不循环，2 帧蓄力，从第 2 帧起循环）：0–1 伏低、头往下一埋（獠牙朝前），一只脚往后刨地；
         2–5 低着头往前冲（大步，两臂往后甩）。
帧 320²（2 倍），锚点 (0.5, 0.8)（大妖物）。挂点 eyes。

    root, parts, sockets = build_ghoul()
    pose_ghoul(parts, "move", i, 8)
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
EYE = "#FF4636"
EYE_HOT = "#FFD9C4"
GLOW = "#F7C978"  # 肚子里的魂光
VZ = V2.VZ
d2m = V2.d2m
# 青灰的皮（d 从暗到亮）：暗部偏蓝紫、亮部偏青白
SKIN_STOPS = [(0.00, "#0F1418"), (0.15, "#172026"), (0.29, "#212E34"), (0.43, "#2F4045"), (0.57, "#425756"),
              (0.71, "#587069"), (0.85, "#748B80"), (1.00, "#98AA9C")]
# 肚皮：绷得发白、透着暖黄（白天是一层暖色，夜里魂光亮起来）
BELLY_STOPS = [(0.00, "#24292A"), (0.2, "#3E4644"), (0.42, "#5F6A64"), (0.62, "#828C82"), (0.8, "#A8AE9E"),
               (1.00, "#CDCFBE")]
RAG_STOPS = [(0.00, "#140909"), (0.24, "#260E0D"), (0.48, "#3E1512"), (0.7, "#5A1F18"), (0.88, "#742B1F"),
             (1.00, "#8C3A2A")]  # 暗红的破布（发黑的旧血色）
IVORY_STOPS = [(0.0, "#3E3628"), (0.35, "#857A60"), (0.65, "#C8BC9C"), (0.85, "#E6DDC4"), (1.0, "#F6F0E0")]
CLAW_STOPS = [(0.0, I["jiao"]), (0.5, "#2A2620"), (0.85, "#4E463A"), (1.0, "#6E6450")]
HAIR_STOPS = [(0.0, I["jiao"]), (0.6, I["jiao"]), (0.85, "#24201C"), (1.0, "#3A342E")]
ROPE_STOPS = [(0.0, "#2A2017"), (0.5, "#6E5A3A"), (1.0, "#A88C64")]
RIM = S.mix("#BFD8DA", I["qing"], 0.25)
LAT = 1.0 / 25.0  # 左右方向：单位 → 米
STEP = 0.45  # 隐式曲面网格的格距（单位）


def to_model(P):
    """设计稿三维（x 前、y 上、z 左右（单位，负 = 近镜头））→ 模型坐标（米）。"""
    P = np.asarray(P, np.float64)
    return np.stack([P[..., 2] * LAT, -P[..., 0] / 25.0, P[..., 1] / VZ], -1)


def ell(p, c, r):
    return V2.sd_ellipsoid(p, c, r)


def cone(p, a, b, r0, r1):
    return V2.sd_round_cone(p, a, b, r0, r1)


def rot2(v, deg):
    a = math.radians(deg)
    x, y = v[0], v[1]
    return (x * math.cos(a) - y * math.sin(a), x * math.sin(a) + y * math.cos(a)) + tuple(v[2:])


def _chain(root, segs, angs):
    """关节点：root（x, y, z）起，每段按角度（从正下方量，正 = 往前）在 x-y 平面里往下接。"""
    pts = [np.asarray(root, np.float64)]
    for ln, a in zip(segs, angs):
        r = math.radians(a)
        pts.append(pts[-1] + ln * np.array([math.sin(r), -math.cos(r), 0.0]))
    return pts


# ---------------------------------------------------------------- 骨架
UPPER, FORE, HAND = 13.0, 12.0, 5.5
THIGH, SHIN = 11.0, 10.5
LAT_ARM, LAT_LEG = 11.0, 6.2
PELVIS_Y = 20.5
BACK_X = -6.5  # 整个身子往后挪：大妖物的锚点在身子中心底下（不是在后脚底下）


def pose_params(anim, i, n):
    """每帧：pelvis（胯的偏移）、lean（整个身子往前栽的角度，度）、head（低头为正）、sway（左右晃，单位）、
    arms / legs：近 False、远 True 的角度（从正下方量，正 = 往前）、paw（拳头张开 0..1）、ph。"""
    ph = 2 * math.pi * i / n
    if anim == "move":
        legs, arms = {}, {}
        for far, off in ((False, 0.0), (True, math.pi)):
            s = math.sin(ph + off)
            lift = max(0.0, math.cos(ph + off)) ** 1.4
            legs[far] = [22.0 + 20 * s + 10 * lift, -14.0 + 6 * s - 30 * lift]
            arms[far] = [10.0 - 22 * s, 6.0 - 14 * s - 6 * max(0.0, -s), 12.0 - 10 * s]
        bob = abs(math.sin(ph))  # 一步一沉
        return {"pelvis": (0.0, -1.1 * (1 - bob)), "lean": 2.0 + 2.0 * (1 - bob), "head": 4.0 - 3.0 * (1 - bob),
                "sway": 0.8 * math.sin(ph), "legs": legs, "arms": arms, "paw": 0.0, "ph": ph, "air": False}
    # charge：0–1 伏低蓄力、头一埋、一只脚往后刨；2–5 低头往前冲（循环）
    if i < 2:
        T = [((0.0, -2.0), 14.0, 16.0, {False: [34.0, -30.0], True: [6.0, -26.0]},
              {False: [-20.0, -6.0, 10.0], True: [-10.0, 0.0, 14.0]}),
             ((0.0, -3.6), 24.0, 26.0, {False: [44.0, -40.0], True: [-24.0, -44.0]},
              {False: [-38.0, -22.0, 0.0], True: [-30.0, -16.0, 6.0]})][i]
        (pv, lean, head, legs, arms) = T
        return {"pelvis": pv, "lean": lean, "head": head, "sway": 0.0, "legs": legs, "arms": arms, "paw": 1.0,
                "ph": ph, "air": False}
    k = (i - 2) / 4.0
    ph = 2 * math.pi * k
    legs, arms = {}, {}
    for far, off in ((False, 0.0), (True, math.pi)):
        s = math.sin(ph + off)
        lift = max(0.0, math.cos(ph + off)) ** 1.2
        legs[far] = [26.0 + 34 * s + 14 * lift, -22.0 + 10 * s - 46 * lift]
        arms[far] = [-34.0 - 26 * s, -20.0 - 16 * s, -4.0]
    up = abs(math.cos(ph))
    return {"pelvis": (2.0, -2.6 + 1.6 * up), "lean": 24.0, "head": 24.0, "sway": 0.0, "legs": legs, "arms": arms,
            "paw": 0.6, "ph": ph, "air": up > 0.85}


def _leg_ground(root, th, sn, g=2.9):
    """站地的腿：脚踝低于 g 时加大屈膝，二分到正好着地。"""
    def ank(d):
        return _chain(root, [THIGH, SHIN], [th + 0.8 * d, sn - 1.2 * d])[-1][1]
    if ank(0.0) >= g:
        return th, sn
    lo, hi = 0.0, 80.0
    for _ in range(40):
        mid = (lo + hi) / 2
        if ank(mid) < g:
            lo = mid
        else:
            hi = mid
    return th + 0.8 * hi, sn - 1.2 * hi


def skeleton(p):
    px, py = p["pelvis"]
    P = np.array([px + BACK_X, PELVIS_Y + py, p["sway"]])
    lean = p["lean"]

    def tl(v):  # 躯干局部（相对胯，x 前、y 上、z 左右）→ 设计稿三维，按 lean 往前栽
        x, y = rot2(v[:2], -lean)
        return P + np.array([x, y, v[2] if len(v) > 2 else 0.0])
    out = {"P": P, "tl": tl, "lean": lean}
    out["neck"] = tl((12.0, 19.0, 0.0))
    for far in (False, True):
        z = LAT_ARM if far else -LAT_ARM
        sh = tl((4.5, 20.0, z * 0.95))
        u, f, h = p["arms"][far]
        out[("arm", far)] = _chain(sh, [UPPER, FORE, HAND], [u + lean * 0.4, f + lean * 0.4, h + lean * 0.4])
        zl = LAT_LEG if far else -LAT_LEG
        hip = P + np.array([0.5, 0.0, zl])
        th, sn = p["legs"][far]
        if not p["air"]:
            th, sn = _leg_ground(hip, th, sn)
        knee, ank = _chain(hip, [THIGH, SHIN], [th, sn])[1:]
        toe = ank + np.array([6.5, -1.6, 0.0])
        out[("leg", far)] = [hip, knee, ank, toe]
    return out


# ---------------------------------------------------------------- 隐式曲面
def torso_sdf(sk):
    """躯干（不含大肚子：肚子单独一块，墨线才分得出肚子和胸、胯）。"""
    tl = sk["tl"]
    prims = [(ell, tl((-2.0, 1.5, 0.0)), (7.5, 7.0, 8.4)),  # 胯、屁股
             (ell, tl((4.0, 4.5, 0.0)), (7.4, 8.4, 8.6)),  # 肚子的芯（被大肚子包着）
             (ell, tl((7.0, 14.0, 0.0)), (8.4, 7.6, 10.2)),  # 胸
             (ell, tl((-0.8, 19.6, 0.0)), (8.8, 7.8, 9.6)),  # 驼背
             (ell, tl((3.5, 19.5, -8.4)), (5.2, 5.4, 4.6)), (ell, tl((3.5, 19.5, 8.4)), (5.2, 5.4, 4.6))]  # 肩
    traps = (tl((1.0, 23.0, 0.0)), tl((11.5, 19.0, 0.0)))
    # 驼背上一串凸起的脊骨（打破一整个圆球的背）
    knobs = []
    for k, a in enumerate(np.linspace(150.0, 58.0, 6)):
        r = math.radians(a)
        knobs.append((tl((-0.8 + 8.6 * math.cos(r), 19.6 + 7.9 * math.sin(r), 0.0)), 1.9 - 0.12 * k))

    def fn(p):
        d = None
        for f, c, r in prims:
            v = f(p, c, r)
            d = v if d is None else V2.smin(d, v, 3.0)
        d = V2.smin(d, cone(p, traps[0], traps[1], 6.2, 4.4), 2.8)  # 颈背的一大块斜方肌，头从它前面伸出来
        for c, r in knobs:
            d = V2.smin(d, ell(p, c, (r * 1.2, r, r * 0.9)), 0.9)
        return d
    return fn, prims


def belly_sdf(sk):
    """鼓胀的大肚子：往前下坠，下沿压着腰布。"""
    tl = sk["tl"]
    c = tl((7.4, 2.4, 0.0))
    c2 = tl((9.4, 0.0, 0.0))

    def fn(p):
        d = ell(p, c, (10.0, 10.2, 9.6))
        d = V2.smin(d, ell(p, c2, (8.6, 7.4, 8.4)), 2.5)  # 往前下坠的那一兜
        return d
    return fn, c


def arm_sdf(pts, far, paw):
    sh, el, wr, hd = (np.asarray(q) for q in pts)
    z = wr[2]
    d_f = (wr - el) / (np.linalg.norm(wr - el) + 1e-9)
    d_h = (hd - wr) / (np.linalg.norm(hd - wr) + 1e-9)
    side = np.array([0.0, 0.0, 1.0])
    fingers = []
    for k, dz in enumerate((-1.7, -0.55, 0.6, 1.7)):
        base = wr + d_h * 3.2 + side * dz * 1.1
        curl = 0.55 - 0.35 * paw
        tip = base + d_h * (3.0 - 0.3 * abs(dz)) + np.array([d_h[1], -d_h[0], 0.0]) * (-1.6 * curl) + side * dz * 0.4
        fingers.append((base, tip))

    def fn(p):
        d = ell(p, sh, (5.4, 5.6, 5.0))  # 三角肌
        d = V2.smin(d, cone(p, sh, el, 4.6, 3.6), 2.0)
        d = V2.smin(d, ell(p, sh + (el - sh) * 0.45 + np.array([0.8, 0.0, 0.0]), (3.2, 5.2, 3.6)), 1.8)  # 二头肌
        d = V2.smin(d, cone(p, el, wr, 4.0, 2.6), 1.6)
        d = V2.smin(d, ell(p, el + (wr - el) * 0.28, (4.0, 4.4, 3.6)), 1.6)  # 小臂的一大块
        d = V2.smin(d, ell(p, wr + d_h * 1.9, (3.4, 3.0, 3.6)), 1.2)  # 手掌
        for a, b in fingers:
            d = V2.smin(d, cone(p, a, b, 1.15, 0.85), 0.5)
        return d
    claws = [(b, b + (b - a) / (np.linalg.norm(b - a) + 1e-9) * 2.4) for a, b in fingers]
    return fn, claws


def leg_sdf(pts):
    hip, knee, ank, toe = (np.asarray(q) for q in pts)
    fwd = np.array([1.0, 0.0, 0.0])

    def fn(p):
        d = cone(p, hip, knee, 5.4, 3.8)
        d = V2.smin(d, ell(p, hip + (knee - hip) * 0.4, (5.0, 5.6, 4.8)), 2.0)  # 大腿
        d = V2.smin(d, cone(p, knee, ank, 3.8, 2.4), 1.6)
        d = V2.smin(d, ell(p, knee + (ank - knee) * 0.3 - fwd * 0.8, (3.0, 4.2, 3.2)), 1.5)  # 小腿肚
        d = V2.smin(d, ell(p, ank + np.array([2.6, -0.8, 0.0]), (4.4, 1.9, 3.2)), 1.4)  # 脚
        return d
    claws = []
    for dz in (-1.6, 0.0, 1.6):
        b = ank + np.array([6.0, -1.4, dz])
        claws.append((b, b + np.array([1.5, -0.6, dz * 0.15])))
    return fn, claws


HEAD_K = 1.4  # 头放大（游戏尺寸下獠牙、大下巴要读得出来）


def head_sdf(neck, ang):
    """头（局部：相对颈端，x 前、y 上），按 ang（低头为正）转，放大 HEAD_K。"""
    def hl(v):
        x, y = rot2((v[0] * HEAD_K, v[1] * HEAD_K), -ang)
        return neck + np.array([x, y, v[2] * HEAD_K])
    prims = [(ell, hl((3.4, 4.0, 0.0)), np.array((5.0, 4.4, 4.6)) * HEAD_K),  # 后脑、头顶（额头往后斜）
             (ell, hl((7.0, 0.4, 0.0)), np.array((5.8, 3.6, 4.8)) * HEAD_K),  # 大下巴（地包天，往前兜）
             (ell, hl((8.8, 3.0, 0.0)), np.array((2.6, 2.0, 2.8)) * HEAD_K),  # 鼻、上唇
             (ell, hl((6.2, 2.7, -3.6)), np.array((2.8, 2.3, 1.8)) * HEAD_K),
             (ell, hl((6.2, 2.7, 3.6)), np.array((2.8, 2.3, 1.8)) * HEAD_K)]  # 颧
    brows = [(hl((5.8, 6.2, z * 3.6)), hl((9.0, 4.8, z * 2.2))) for z in (-1, 1)]  # 眉骨往鼻梁压下来：凶
    ears = [(hl((2.6, 5.4, z * 4.0)), hl((-1.2, 8.6, z * 5.8))) for z in (-1, 1)]

    def fn(p):
        d = None
        for f, c, r in prims:
            v = f(p, c, r)
            d = v if d is None else V2.smin(d, v, 1.8)
        for a, b in brows:  # 眉骨：又厚又低
            d = V2.smin(d, cone(p, a, b, 1.9 * HEAD_K, 1.5 * HEAD_K), 1.0)
        for a, b in ears:
            d = V2.smin(d, cone(p, a, b, 1.4 * HEAD_K, 0.25), 0.6)
        return d
    return fn, hl


def _bbox(points, pad):
    P = np.asarray(points, np.float64)
    return P.min(0) - pad, P.max(0) + pad


def _sdf_arrays(fn, lo, hi, attr_fn=None):
    """隐式曲面（设计稿三维里）→ 模型坐标的顶点、面、属性。"""
    V, F = V2.sdf_mesh(fn, lo, hi, STEP, project=2)
    A = attr_fn(V) if attr_fn else {}
    return to_model(V), [f[::-1] for f in F], A  # 换到模型坐标时左右手互换，面翻过来


# ---------------------------------------------------------------- 材质小件
def tint_by_attr(m, attr, rgb_mul, amount=1.0):
    """材质的颜色按顶点属性往 rgb_mul 乘（肚皮发白、发暖）。"""
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


def _merge(arrs):
    V, F, A = [], [], {}
    keys = set()
    for _, _, a in arrs:
        keys |= set(a)
    for v, f, a in arrs:
        o = len(V)
        n = len(v)
        V.extend(list(v))
        F.extend([tuple(i + o for i in ff) for ff in f])
        for k in keys:
            A.setdefault(k, []).extend(list(a.get(k, [0.0] * n)))
    return V, F, A


def _set(ob, V, F, A, smooth=True):
    K.replace_mesh(ob, V2.arrays_build(V, F), smooth=smooth, attrs=A)


def horn_arrays(a, b, r0, bend=(0.0, 0.0, 0.0), nu=10, nv=10):
    """一根尖角（獠牙、爪）：a → b（设计稿三维），中段往 bend 弯，半径 r0 收到尖。"""
    a, b, bend = (np.asarray(v, np.float64) for v in (a, b, bend))
    pts = [a + (b - a) * t + bend * math.sin(math.pi * t) for t in np.linspace(0, 1, nv)]
    P = to_model(np.asarray(pts))

    def prof(t):
        r = r0 * (1 - t) ** 0.9 / 25.0 + 0.0005
        return r, r * 25.0 / VZ, r * 25.0 / VZ
    return V2.tube_arrays([Vector(q) for q in P], prof, nu=nu, nv=nv, cap0=True, cap1=True)


def strip3(c2, w, z, ref_z=0.0):
    """头发、破布条：设计稿二维的中线 c2、宽 w，放在离镜头 z（单位）的竖平面里（抵掉俯视的高低差）。"""
    lat = z * LAT
    c = np.asarray(c2, np.float64) - np.array([0.0, (lat - ref_z * LAT) * 25.0 * math.sin(math.radians(S.CAMERA_PITCH_DEG))])
    return V2.strip_arrays(*V2.design_strip(c, np.asarray(w), lat))


# ---------------------------------------------------------------- 组装
def build_ghoul():
    root = B.empty("GhRoot")
    body = B.empty("GhBody", root)
    common = dict(wash=0.4, wash_scale=3.2, shade_attr="zone", shade_gain=1.0, streak=0.06, streak_scale=(3.0, 3.0),
                  value_var=0.08, edge=0.32)
    m_skin = V2.paint_material("GhSkin", SKIN_STOPS, seed=61.0, rim_hex=RIM, rim=0.65, rim_power=2.3, bias=-0.24,
                               **common)
    m_belly = V2.paint_material("GhBelly", BELLY_STOPS, seed=69.0, rim_hex=RIM, rim=0.45, rim_power=2.3, bias=0.05,
                                glow_attr="soul", glow_gain=1.0, **common)
    tint_by_attr(m_belly, "soul", (1.32, 1.14, 0.6), 1.3)  # 魂：白天是肚皮底下几团暖黄
    m_far = V2.paint_material("GhSkinFar", SKIN_STOPS, seed=62.0, rim_hex=RIM, rim=0.35, bias=-0.42, **common)
    m_head = V2.paint_material("GhHead", SKIN_STOPS, seed=63.0, rim_hex=RIM, rim=0.6, rim_power=2.3, bias=-0.14, **common)
    m_iron = V2.paint_material("GhIron", [(0.0, I["jiao"]), (0.4, "#26282A"), (0.7, "#45484A"), (1.0, "#6E7270")],
                               wash=0.2, seed=70.0, edge=0.1, rim_hex="#9AA4A8", rim=0.5)
    m_rag = V2.paint_material("GhRag", RAG_STOPS, wash=0.3, seed=64.0, shade_attr="zone", streak=0.3,
                              streak_scale=(30.0, 4.0), rim_hex=S.mix("#E0B8A8", I["qing"], 0.3), rim=0.35, edge=0.3)
    m_ivory = V2.paint_material("GhIvory", IVORY_STOPS, wash=0.15, seed=65.0, edge=0.15, rim_hex="#FFFFFF", rim=0.3)
    m_claw = V2.paint_material("GhClaw", CLAW_STOPS, wash=0.15, seed=66.0, edge=0.1)
    m_hair = V2.brush_material("GhHair", HAIR_STOPS, edge_soft=0.2, edge_dark=0.2, streak=0.5, streak_from=0.4,
                               scale=(5.0, 9.0), fade_from=0.85, seed=67.0, comb=9.0)
    m_rope = V2.paint_material("GhRope", ROPE_STOPS, wash=0.3, seed=68.0, streak=0.3, streak_scale=(4.0, 30.0))
    m_mouth = B.flat_material("GhMouth", I["jiao"])
    m_eye = B.emissive_material("GhEye", EYE, 1.0)
    m_hot = B.emissive_material("GhEyeHot", EYE_HOT, 1.0)
    parts = {"root": root, "body": body, "dyn": {}}

    def dyn(name, mat, line="outer"):
        ob = V2.mesh_from_arrays(name, [(0, 0, 0), (0.001, 0, 0), (0, 0.001, 0)], [(0, 1, 2)], mat, line, body)
        parts["dyn"][name] = ob
        return ob

    for nm, mat, line in (("Torso", m_skin, "outer"), ("Belly", m_belly, "outer"), ("ArmNear", m_skin, "outer"), ("ArmFar", m_far, "outer"),
                          ("LegNear", m_skin, "outer"), ("LegFar", m_far, "outer"), ("Head", m_head, "outer"),
                          ("Tusks", m_ivory, "inner"), ("Claws", m_claw, "inner"), ("Rag", m_rag, "outer"),
                          ("Rope", m_rope, "inner"), ("Hair", m_hair, "none"), ("Mouth", m_mouth, "none"),
                          ("Iron", m_iron, "inner")):
        dyn(nm, mat, line)
    for nm in ("Torso", "Belly", "ArmNear", "LegNear", "Head"):  # 肌肉的起伏：暗示轮廓线当皴笔
        bpy.data.collections[B.CUN_COLLECTION].objects.link(parts["dyn"][nm])
    eyes = []
    for k, (r_, mat) in enumerate(((1.0, m_eye), (0.5, m_hot))):
        for far in (False, True):
            ob = B.mesh_object(f"GhEye{k}{'F' if far else 'N'}", K.ellipsoid((0.012, 0.045 * r_, 0.028 * r_), 12, 8), mat,
                               "none", body)
            eyes.append((ob, far, r_))
    sock = B.empty("GhSocketEyes", body)
    parts.update(eyes=eyes, sock=sock)
    parts["sockets"] = {"eyes": sock}
    pose_ghoul(parts, "move", 0, 8)
    return root, parts, parts["sockets"]


# 头发：(根（头局部）, 起始角, 末端角, 长, 宽, 离镜头（单位）, 相位)
HAIR = [((2.4, 7.4), 118, 172, 14.0, 4.0, -2.0, 0.0), ((1.0, 7.0), 138, 196, 15.5, 4.2, 1.0, 0.7),
        ((3.6, 7.8), 98, 146, 12.0, 3.6, -3.5, 1.4), ((-0.2, 6.0), 158, 214, 14.0, 3.8, 2.5, 2.1),
        ((4.6, 7.4), 80, 120, 9.0, 3.0, -4.2, 2.8), ((-1.0, 4.4), 182, 236, 12.5, 3.6, 3.0, 3.5),
        ((1.8, 8.0), 104, 132, 11.0, 3.2, 0.0, 4.2), ((5.6, 6.6), 66, 96, 7.0, 2.6, -4.6, 4.9),
        ((0.4, 7.6), 126, 160, 16.0, 3.8, -1.2, 5.5), ((-1.6, 2.6), 196, 250, 10.0, 3.2, 1.8, 6.1),
        ((3.0, 8.2), 90, 122, 10.5, 3.2, 1.6, 0.4), ((-0.8, 5.6), 170, 226, 13.0, 3.4, -2.6, 1.9)]


def pose_ghoul(parts, anim, frame, n):
    p = pose_params(anim, frame, n)
    sk = skeleton(p)
    D = parts["dyn"]
    groups = {k: [] for k in D}
    # 躯干
    fn, prims = torso_sdf(sk)
    lo, hi = _bbox([c for _, c, _ in prims], 12.0)
    groups["Torso"].append(_sdf_arrays(fn, lo, hi, lambda V: {"zone": list(-0.22 * np.clip((V[:, 1] - sk["P"][1] - 12.0)
                                                                                          / 10.0, 0, 1))}))
    # 大肚子：几团魂在肚皮底下慢慢转（soul：白天一层暖黄、夜里发光）
    fb, bc = belly_sdf(sk)
    ph = p["ph"]

    def belly_attrs(V):
        d = V - bc
        soul = np.zeros(len(V))
        for k, (ox, oy, r) in enumerate(((2.0, 3.0, 4.2), (5.4, -3.2, 3.6), (-1.0, -4.6, 3.2))):
            a = ph * 0.5 + k * 2.1
            cx, cy = ox + 1.2 * math.cos(a), oy + 1.0 * math.sin(a)
            g = np.exp(-(((d[:, 0] - cx) ** 2 + (d[:, 1] - cy) ** 2) / (r * r)))
            soul = np.maximum(soul, g)
        front = np.clip((d[:, 0] + 3.0) / 7.0, 0, 1) * np.clip((-d[:, 2] + 6.0) / 8.0, 0, 1)
        base = np.clip(1.0 - np.linalg.norm(d / np.array([10.0, 10.2, 9.6]), axis=-1), 0, 1)
        return {"soul": list(np.clip(0.1 * front + 0.8 * soul * front + 0.0 * base, 0, 1)),
                "zone": list(0.2 * front)}
    lo, hi = _bbox([bc], 13.0)
    groups["Belly"].append(_sdf_arrays(fb, lo, hi, belly_attrs))
    # 四肢
    for far in (False, True):
        apts = sk[("arm", far)]
        fa, claws = arm_sdf(apts, far, p["paw"])
        lo, hi = _bbox(apts, 6.5)
        groups["ArmFar" if far else "ArmNear"].append(_sdf_arrays(fa, lo, hi, lambda V: {"zone": [0.0] * len(V)}))
        for a, b in claws:
            groups["Claws"].append(horn_arrays(a, b, 1.0, bend=(0.0, -0.5, 0.0), nu=8, nv=6))
        # 腕上一圈铁箍（鬼门里带出来的镣铐，断了）
        el, wr = np.asarray(apts[1]), np.asarray(apts[2])
        dd = (wr - el) / (np.linalg.norm(wr - el) + 1e-9)
        c0, c1 = wr - dd * 3.4, wr - dd * 1.0
        P2 = to_model(np.asarray([c0 + (c1 - c0) * t for t in np.linspace(0, 1, 4)]))

        def cuff(t):
            r = 3.15 / 25.0
            return r, r * 25.0 / VZ, r * 25.0 / VZ
        groups["Iron"].append(V2.tube_arrays([Vector(q) for q in P2], cuff, nu=16, nv=4, cap0=True, cap1=True))
        lpts = sk[("leg", far)]
        fl, lclaws = leg_sdf(lpts)
        lo, hi = _bbox(lpts, 6.5)
        groups["LegFar" if far else "LegNear"].append(_sdf_arrays(fl, lo, hi, lambda V: {"zone": [0.0] * len(V)}))
        for a, b in lclaws:
            groups["Claws"].append(horn_arrays(a, b, 0.7, bend=(0.0, -0.3, 0.0), nu=8, nv=6))
    # 头：大下巴、厚眉骨、尖耳朵；獠牙从下颌翻出来往上挑
    neck = sk["neck"]
    ang = p["head"] + sk["lean"] * 0.6
    fh, hl = head_sdf(neck, ang)
    lo, hi = _bbox([neck], 15.0)
    groups["Head"].append(_sdf_arrays(fh, lo, hi, lambda V: {"zone": [0.0] * len(V)}))
    for z in (-1, 1):
        a = hl((9.2, 1.0, 3.3 * z))
        b = hl((10.4, 7.8, 4.9 * z))
        groups["Tusks"].append(horn_arrays(a, b, 1.35 * HEAD_K, bend=hl((1.5, -0.8, 0.0)) - neck, nu=12, nv=12))
    # 嘴：下颌和上唇之间一道焦墨（近镜头那半边）
    mouth = [hl((11.6, 2.5, -1.0)), hl((9.8, 2.0, -3.0)), hl((7.6, 1.9, -4.4)), hl((5.4, 1.0, -4.6))]
    mc = [(q[0], q[1]) for q in mouth]
    groups["Mouth"].append(strip3(mc, [1.0, 1.35, 1.0, 0.35], -7.0, ref_z=0.0))
    for x0 in (10.6, 8.6):  # 下排两颗小牙（地包天，往上龇）
        a = hl((x0, 1.6, -3.2))
        groups["Tusks"].append(horn_arrays(a, a + (hl((x0 + 0.3, 3.0, -3.2)) - a), 0.75 * HEAD_K, nu=8, nv=6))
    # 眼：眉骨底下两点赤红
    for ob, far, r_ in parts["eyes"]:
        q = hl((8.4, 4.1, 2.3 if far else -2.4))
        z = q[2] - 3.4 if not far else q[2] - 1.6
        ob.location = to_model(np.array([q[0], q[1] - (z * LAT) * 12.5, z - (0.2 if r_ < 1 else 0.0)]))
        ob.rotation_euler = (math.radians(-12.0 if not far else 14.0), 0, 0)
        ob.scale = (1.0, 0.8 if far else 1.0, 0.8 if far else 1.0)
    e = hl((8.4, 4.1, -2.4))
    parts["sock"].location = to_model(np.array([e[0], e[1] + 5.0 * LAT * 12.5, -5.0]))
    # 头发：几大笔焦墨，往后上方炸开
    for (bx, by), a0, a1, ln, w, z, p0 in HAIR:
        b2 = hl((bx, by, 0.0))
        c, wd = _hair_curve((b2[0], b2[1]), a0 + ang * 0.3, a1 + ang * 0.3, ln, w, p["ph"] + p0)
        groups["Hair"].append(strip3(c, wd, neck[2] + z))
    # 腰上的破布 + 草绳
    P = sk["P"]
    tl = sk["tl"]
    top_c = tl((1.0, 3.5, 0.0))
    groups["Rag"].append(_rag(top_c, sk["lean"], p["ph"]))
    ring = [to_model(np.array(tl((1.0 + 8.6 * math.sin(t), 5.0 + 0.6 * math.cos(t), 9.0 * math.cos(t)))))
            for t in np.linspace(0, 2 * math.pi, 29)]
    groups["Rope"].append(V2.tube_arrays([Vector(q) for q in ring], lambda t: (0.018, 0.018, 0.018), nu=6, nv=29,
                                         cap0=False, cap1=False))
    for k, arrs in groups.items():
        ob = D[k]
        if arrs:
            _set(ob, *_merge(arrs), smooth=k not in ("Hair", "Mouth"))
            ob.hide_render = False
        else:
            ob.hide_render = True
    bpy.context.view_layer.update()


def _hair_curve(base, a0, a1, length, width, ph, n=12):
    c = []
    x, y = base
    for t in np.linspace(0, 1, n):
        aa = math.radians(a0 + (a1 - a0) * t ** 1.2 + 6.0 * math.sin(ph + 3.0 * t) * t)
        c.append((x, y))
        x += math.cos(aa) * length / (n - 1)
        y += math.sin(aa) * length / (n - 1)
    t = np.linspace(0, 1, n)
    w = width * np.where(t < 0.2, 0.7 + 1.5 * t, (1 - t) / 0.8 * 1.0) + 0.1
    return np.asarray(c), w


def _rag(top_c, lean, ph, nu=40, nv=6):
    """腰上的破布：一圈往下张的裙片，下摆参差、前后各垂一片长的。"""
    rng = np.random.default_rng(11)
    jag = rng.uniform(0, 1, nu)
    V, su, sv, zn = [], [], [], []
    for j in range(nv):
        t = j / (nv - 1)
        for i in range(nu):
            th = 2 * math.pi * i / nu
            c, s_ = math.cos(th), math.sin(th)
            r_x = 8.2 + 2.0 * t
            r_z = 9.2 + 1.8 * t
            ln = 6.0 + 6.5 * max(0.0, s_) ** 6 + 2.6 * max(0.0, -s_) ** 8  # 前、后各长一片（前面那片从肚子底下垂出来）
            drop = ln * t
            if j == nv - 1:
                drop += 2.2 * jag[i] * (1 if i % 2 else 0.5)
            x = top_c[0] + r_x * s_ - 1.0 * t * math.sin(ph) - lean * 0.02 * drop
            y = top_c[1] - drop
            z = top_c[2] + r_z * c
            V.append(to_model(np.array([x, y, z])))
            su.append(t)
            sv.append(i / nu)
            zn.append(-0.3 * max(0.0, 1 - t / 0.35))
    F = [(j * nu + i, (j + 1) * nu + i, (j + 1) * nu + (i + 1) % nu, j * nu + (i + 1) % nu)
         for j in range(nv - 1) for i in range(nu)]
    return V, F, {"su": su, "sv": sv, "zone": zn}
