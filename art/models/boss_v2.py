"""九尾（精修三维，夜主）：巨大的白狐，九条尾巴在身后摊成一个大扇面，尾尖染着青火。

设定（LORE 附录）：“青丘之山……有兽焉，其状如狐而九尾。”古书里它吃人，也是涂山的祥瑞；长夜里，它是狐村所有小狐狸的母亲。
外形（世界观会话）：巨大的白狐，身形修长，九条尾巴像扇面一样展开，尾尖染着青火。额心一点青，眼睛也是青的。
脸上不画红（和赤面狐分开）。主色月白、青；美而凛，是护崽的母亲，凶起来不留情。
造型：身子、四条腿、头都是隐式曲面（v2kit.sdf_mesh，同青面鬼）：胸口厚、腰收细（肚子往上收）；后腿大腿肌肉饱满、
飞节往后折（反关节），前腿细长、带腕关节和爪。颈长、往前弯，头低低地往前探（扑食的架势）。
脸窄、吻长；丹凤眼细长上挑、青光，墨勾眼线带一笔上挑的尾；耳朵大、耳里一簇白毛；额心一簇青火印。
胸前、颈下一圈蓬松的白毛领（笔触扁带），颊后、肘后、腿后、肚下、尾根几簇毛。
九条尾巴从尾根在身后摊成扇面（约 155°），前后两层错开（单数在后、暗一档）；每条根细、中段蓬、尖上一截青火（AOV 发光），
火舌往外飘。
动画（只画 E）：
  move   8 帧：小跑（对角步：脚按轨迹走，两节腿反解），身子一步一起伏；扇面里每条尾巴带着波轻轻摆，尾火跳动。
  sweep  6 帧（不循环，2 帧蓄力）：0 伏低、九尾往上收拢；1 九尾从背上往前拱、尾火大盛（预警期间停在这一帧）；
         2 往前下方一扫；3 扫到身前低处；4、5 收回扇面。
  summon 4 帧（不循环）：昂头，九尾张到最开、尾尖青火腾起（召狐火），3 稍落。
帧 896²（2 倍；原 640²，扇面放不下），锚点 (0.5, 0.8)（大妖物）。挂点 eyes。
坐标：设计稿三维（单位；x 前、y 上、z 左右，z 负 = 近镜头），用 v2kit.d3m 换到模型坐标。

    root, parts, sockets = build_boss()
    pose_boss(parts, "move", i, 8)
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
EYE = "#66F4E2"  # 青眼
EYE_HOT = "#F2FFFD"
FIRE = "#6FF2D8"  # 尾尖的青火
FIRE_DEEP = "#2FAE9C"
FIRE_HOT = "#E8FFF9"
WHITE = "#F6F8F8"
# 月白的毛（d 从暗到亮）：暗部偏青灰、亮部近白
FUR_STOPS = [(0.00, "#323A46"), (0.16, "#4A5564"), (0.30, "#66717F"), (0.44, "#86909C"), (0.56, "#A4AEB8"),
             (0.68, "#C2CAD0"), (0.80, "#DCE2E4"), (0.90, "#EDF1F1"), (1.00, WHITE)]
EAR_STOPS = [(0.0, "#2C3440"), (0.5, "#56626E"), (0.85, "#7E8A96"), (1.0, "#9AA6B0")]  # 耳背、耳尖：淡青灰
RUFF_STOPS = [(0.0, "#CDD4DA"), (0.45, "#ECF0F1"), (1.0, WHITE)]  # 毛领边上的笔触：近白
RUFF_FAR = [(0.0, "#46505C"), (0.4, "#727E8A"), (1.0, "#9EA8B2")]
FIRE_STOPS = [(0.0, "#3FB8A6"), (0.45, FIRE), (1.0, FIRE_HOT)]
RIM = S.mix("#DDF6F2", I["qing"], 0.15)
STEP = 0.5  # 隐式曲面网格的格距（单位）
G = 1.12  # 整体放大（绕锚点，脚还在地上）
HEAD_K = 1.2  # 头再放大一点（绕颈端）：游戏尺寸下脸、眼、耳要读得出来


# ================================================================ 小工具
def v3(x, y, z=0.0):
    return np.array([x, y, z], np.float64)


def ell(p, c, r, rot=None):
    return V2.sd_ellipsoid(p, c, r, rot)


def cone(p, a, b, r0, r1):
    return V2.sd_round_cone(p, a, b, r0, r1)


def rotz(deg):
    """设计稿 x-y 平面里逆时针转 deg 度（3×3，局部 → 世界）。"""
    a = math.radians(deg)
    c, s = math.cos(a), math.sin(a)
    return np.array([[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]])


def along(a, b):
    """局部 x 轴沿 a → b（x-y 平面里）的旋转。"""
    d = np.asarray(b, np.float64)[:2] - np.asarray(a, np.float64)[:2]
    return rotz(math.degrees(math.atan2(d[1], d[0])))


def smooth01(t):
    t = np.clip(t, 0.0, 1.0)
    return t * t * (3 - 2 * t)


def bez(p0, p1, p2, n):
    t = np.linspace(0, 1, n)[:, None]
    return (1 - t) ** 2 * p0 + 2 * (1 - t) * t * p1 + t * t * p2


def ik2(root, target, a, b, bend):
    """两节反解（x-y 平面）：root → 中间关节 → target。bend = +1 中间关节在连线前面（膝），-1 在后面（肘）。
    够不着时伸直、往 target 方向够。返回 (中间关节, 末端)。"""
    R, T = np.asarray(root, np.float64), np.asarray(target, np.float64)
    v = T[:2] - R[:2]
    d0 = float(np.linalg.norm(v)) + 1e-9
    u = v / d0
    d = min(max(d0, abs(a - b) + 1e-3), a + b - 1e-3)
    ang = math.acos(np.clip((a * a + d * d - b * b) / (2 * a * d), -1.0, 1.0))
    perp = np.array([-u[1], u[0]])
    m2 = R[:2] + a * (u * math.cos(ang) + perp * math.sin(ang) * bend)
    e2 = R[:2] + u * d
    z0, z1 = R[2], T[2]
    return np.array([m2[0], m2[1], (z0 + z1) / 2]), np.array([e2[0], e2[1], z1])


def outward(V, F):
    """闭合网格的面朝外（有向体积为负就整体翻过来）。"""
    V = np.asarray(V, np.float64)
    vol = 0.0
    for f in F:
        for k in range(1, len(f) - 1):
            vol += float(V[f[0]] @ np.cross(V[f[k]], V[f[k + 1]]))
    return F if vol > 0 else [tuple(f[::-1]) for f in F]


def stroke_arrays(c3, w0, taper=0.75, w_end=0.12):
    """一笔毛（扁带）：设计稿三维的中线 c3（z 取各点的平均，扁带正对镜头），根宽 w0，往尖收。"""
    c3 = np.asarray(c3, np.float64)
    t = np.linspace(0, 1, len(c3))
    w = w0 * (1 - t) ** taper + w_end
    P, W, Sd = V2.design_strip(c3[:, :2], w, float(c3[:, 2].mean()) / 25.0)
    return V2.strip_arrays(P, W, Sd)


def arc(p0, a0, a1, length, n=7, z=None):
    """从 p0 出发、方向从 a0 渐变到 a1（度）的一段弧（设计稿三维，z 不变或按 z 给）。"""
    pts = [np.asarray(p0, np.float64)]
    for k in range(n - 1):
        t = (k + 0.5) / (n - 1)
        a = math.radians(a0 + (a1 - a0) * t)
        pts.append(pts[-1] + length / (n - 1) * np.array([math.cos(a), math.sin(a), 0.0]))
    P = np.asarray(pts)
    if z is not None:
        P[:, 2] = z
    return P


def cone_arrays(a, b, r0, nu=8, nv=5):
    """一根尖锥（爪）：a → b（设计稿三维），半径 r0 收到尖。"""
    a, b = np.asarray(a, np.float64), np.asarray(b, np.float64)
    P = V2.d3m(np.asarray([a + (b - a) * t for t in np.linspace(0, 1, nv)]))

    def prof(t):
        r = r0 * (1 - t) ** 0.9 + 0.02
        return r / 25.0, r / V2.VZ, r / V2.VZ
    return V2.tube_arrays([Vector(q) for q in P], prof, nu=nu, nv=nv, cap0=True, cap1=True)


def mix_attr(m, attr, hex_color, amount=1.0):
    """材质的颜色按顶点属性 attr（0..1）往 hex_color 混（尾尖的火）。"""
    nt = m.node_tree
    N, Lk = nt.nodes, nt.links
    emi = next(n for n in N if n.type == "EMISSION")
    src = emi.inputs["Color"].links[0].from_socket
    at = N.new("ShaderNodeAttribute"); at.attribute_type = "GEOMETRY"; at.attribute_name = attr
    fk = N.new("ShaderNodeMath"); fk.operation = "MULTIPLY"; fk.inputs[1].default_value = amount; fk.use_clamp = True
    Lk.new(at.outputs["Fac"], fk.inputs[0])
    mx = N.new("ShaderNodeMix"); mx.data_type = "RGBA"; mx.blend_type = "MIX"
    Lk.new(fk.outputs["Value"], B.sock(mx.inputs, "Factor_Float"))
    Lk.new(src, B.sock(mx.inputs, "A_Color"))
    B.sock(mx.inputs, "B_Color").default_value = B.hex_lin(hex_color)
    Lk.new(B.sock(mx.outputs, "Result_Color"), emi.inputs["Color"])
    return m


# ================================================================ 骨架（静止时，身子局部；锚点在原点、地面 y = 0）
PIVOT = v3(0.0, 34.0)  # 身子俯仰的转轴
NECK0 = v3(25.0, 38.0)  # 颈根
NECK_CTRL = v3(31.0, 51.0)  # 颈的弯（贝塞尔控制点，在连线上方：颈往上拱、再往前探）
HEAD0 = v3(42.0, 52.0)  # 头的转轴（颈端）
HEAD_TILT = -12.0  # 头往下低（度）
TAIL_ROOT = v3(-31.0, 41.0)
SHOULDER = v3(29.0, 31.0)
HIP = v3(-23.0, 34.0)
LEG_Z = 6.5
HUMERUS, FOREARM, PASTERN = 12.0, 15.5, 5.0
FEMUR, TIBIA, META = 14.0, 15.0, 11.5
PAW_Y = 1.7  # 爪心离地
PAW_X = {"front": 25.0, "hind": -23.0}

# 身子：(中心, 半径)。胸腔又深又厚，腰往上收，胯、臀圆；尾根一团（九条尾巴从里面长出来）
BODY_PRIMS = [((15.0, 30.5), (15.5, 13.5, 9.6)), ((25.0, 25.0), (8.5, 8.5, 7.8)), ((19.0, 38.5), (9.0, 6.5, 8.2)),
              ((-5.0, 36.0), (13.0, 5.8, 6.4)), ((-23.0, 36.0), (10.5, 8.0, 8.4)), ((-30.0, 37.5), (5.5, 6.0, 7.0)),
              ((-34.0, 42.0), (6.5, 6.5, 6.5))]


def gait(anim, i, n):
    """每条腿：(爪心目标 x, y, 远端那节的角度（度，从正下方量，正 = 往前）)，以及身子起伏。"""
    ph = 2 * math.pi * i / n
    feet = {}
    for name in ("front", "hind"):
        for far in (False, True):
            off = 0.0 if (name == "front") != far else math.pi  # 近前 + 远后同相
            q = (ph + off) % (2 * math.pi)
            A, H = (7.5, 5.5) if name == "front" else (7.0, 4.5)
            if q < math.pi:  # 着地：往后蹬
                s = q / math.pi
                x, y, lift = A * (1 - 2 * s), 0.0, 0.0
            else:  # 抬脚往前
                s = (q - math.pi) / math.pi
                e = s - math.sin(2 * math.pi * s) / (2 * math.pi)
                x, y, lift = -A + 2 * A * e, H * math.sin(math.pi * s), math.sin(math.pi * s)
            if name == "front":
                feet[(name, far)] = (PAW_X[name] + x, PAW_Y + y, 22.0 - 95.0 * lift)
            else:
                feet[(name, far)] = (PAW_X[name] + x, PAW_Y + y, 6.0 - 40.0 * lift)
    bob = 0.7 * math.cos(2 * ph)
    return feet, bob, ph


def pose_params(anim, i, n):
    """一帧的姿态：身子 (dx, dy, 俯仰)、头 (dx, dy, 转)、耳、脚、尾巴布局、火的大小。"""
    feet, bob, ph = gait("move", i if anim == "move" else 0, n if anim == "move" else 8)
    p = {"dx": 0.0, "dy": bob if anim == "move" else 0.0, "pitch": 0.0, "head": (0.0, -0.3 * bob, 0.0), "ears": 0.0,
         "feet": feet, "ph": ph, "anim": anim, "frame": i, "n": n}
    if anim == "move":
        p["pitch"] = 0.8 * math.sin(2 * ph)
    elif anim == "sweep":
        # 身子 (dx, dy, 俯仰)、头 (dx, dy, 转)
        T = [((-1.5, -2.2, -3.0), (-1.0, -1.5, -6.0)), ((-2.5, -3.8, -5.0), (-1.5, -3.0, -10.0)),
             ((2.0, -1.0, 3.0), (1.5, -0.5, 4.0)), ((3.0, -1.8, 4.0), (2.0, -1.0, 6.0)),
             ((1.0, -0.6, 1.0), (0.5, -0.3, 2.0)), ((0.0, 0.0, 0.0), (0.0, 0.0, 0.0))][i]
        (p["dx"], p["dy"], p["pitch"]), p["head"] = T
        p["feet"] = _planted(p, spread=[3.0, 4.0, 1.5, 1.0, 0.5, 0.0][i])
    else:  # summon：昂头、身子略往后仰
        T = [((-0.8, 0.4, 3.0), (-1.0, 2.0, 10.0)), ((-1.5, 1.0, 6.0), (-2.0, 4.5, 22.0)),
             ((-1.6, 1.2, 7.0), (-2.2, 5.0, 26.0)), ((-1.0, 0.6, 4.0), (-1.2, 3.0, 15.0))][i]
        (p["dx"], p["dy"], p["pitch"]), p["head"] = T
        p["feet"] = _planted(p, spread=0.0)
    return p


def _planted(p, spread):
    """四脚着地（伏低时前后脚略张开）。"""
    out = {}
    for name in ("front", "hind"):
        for far in (False, True):
            sx = (spread if name == "front" else -spread) + (1.5 if far else -1.0)
            out[(name, far)] = (PAW_X[name] + sx + p["dx"] * 0.3, PAW_Y, 22.0 if name == "front" else 6.0)
    return out


def skeleton(p):
    Rb = rotz(p["pitch"])
    shift = v3(p["dx"], p["dy"])

    def tb(q):  # 身子局部 → 世界
        return PIVOT + Rb @ (np.asarray(q, np.float64) - PIVOT) + shift
    sk = {"Rb": Rb, "shift": shift, "tb": tb}
    hx, hy, hr = p["head"]
    sk["head_piv"] = tb(HEAD0) + v3(hx, hy)
    sk["head_rot"] = p["pitch"] + hr  # 相对静止（静止的低头已经做进头的网格里）
    n0 = tb(NECK0)
    ctrl = tb(NECK_CTRL) + v3(hx * 0.5, hy * 0.6)
    C = bez(n0, ctrl, sk["head_piv"], 7)
    rr = np.linspace(8.0, 4.9, len(C))
    sk["neck"] = [(C[k], C[k + 1], rr[k], rr[k + 1]) for k in range(len(C) - 1)]
    sk["tail_root"] = tb(TAIL_ROOT)
    for name in ("front", "hind"):
        for far in (False, True):
            z = LEG_Z if far else -LEG_Z
            fx, fy, dist = p["feet"][(name, far)]
            paw = v3(fx, fy, z * 0.92)
            r = math.radians(dist)
            if name == "front":
                top = tb(SHOULDER + v3(0, 0, z * 0.7))
                wrist = paw - PASTERN * np.array([math.sin(r), -math.cos(r), 0.0])
                elbow, wrist = ik2(top, wrist, HUMERUS, FOREARM, -1)
                paw = wrist + PASTERN * np.array([math.sin(r), -math.cos(r), 0.0])
                sk[(name, far)] = [tb(SHOULDER + v3(-6.0, 9.0, z * 0.55)), top, elbow, wrist, paw]
            else:
                top = tb(HIP + v3(0, 0, z))
                hock = paw - META * np.array([math.sin(r), -math.cos(r), 0.0])
                stifle, hock = ik2(top, hock, FEMUR, TIBIA, +1)
                paw = hock + META * np.array([math.sin(r), -math.cos(r), 0.0])
                sk[(name, far)] = [top, stifle, hock, paw]
    return sk


# ================================================================ 隐式曲面
def body_sdf(sk):
    Rb, shift = sk["Rb"], sk["shift"]

    def fn(p):
        q = (p - PIVOT - shift) @ Rb + PIVOT  # 世界 → 身子局部
        d = None
        for (x, y), r in BODY_PRIMS:
            v = ell(q, v3(x, y), r)
            d = v if d is None else V2.smin(d, v, 4.0)
        d = V2.smin(d, body_tufts_sdf(q), 1.0)
        for a, b, r0, r1 in sk["neck"]:
            d = V2.smin(d, cone(p, a, b, r0, r1), 3.0)
        return d
    pts = [sk["tb"](v3(x, y)) for (x, y), _ in BODY_PRIMS] + [s[1] for s in sk["neck"]]
    return fn, pts


def front_leg_sdf(pts):
    sc, sh, el, wr, paw = pts
    d_sc = along(sc, sh)
    d_hu = along(sh, el)
    d_fa = along(el, wr)
    fwd = np.array([1.0, 0.0, 0.0])

    def fn(p):
        d = ell(p, sc + (sh - sc) * 0.5, (7.5, 4.2, 3.0), d_sc)  # 肩胛
        d = V2.smin(d, cone(p, sh, el, 3.8, 2.9), 2.0)
        d = V2.smin(d, ell(p, sh + (el - sh) * 0.55 - fwd * 1.6, (6.0, 3.6, 3.4), d_hu), 1.6)  # 上臂后面的一大块
        d = V2.smin(d, cone(p, el, wr, 2.6, 1.7), 1.2)  # 前臂：细长
        d = V2.smin(d, ell(p, el + (wr - el) * 0.22 + fwd * 0.5, (4.2, 2.2, 2.1), d_fa), 1.0)
        d = V2.smin(d, ell(p, wr, (1.9, 2.1, 1.9)), 0.6)  # 腕
        d = V2.smin(d, cone(p, wr, paw, 1.7, 1.6), 0.6)
        d = V2.smin(d, ell(p, paw + v3(1.4, -0.2), (3.4, 1.7, 2.3)), 0.8)  # 爪
        for k in range(2):  # 肘后一簇毛
            d = V2.smin(d, tuft(p, el + v3(-1.0, -0.6 - 1.6 * k), -128.0 - 14 * k, 4.6 - 0.8 * k, 1.9), 0.6)
        return d
    toes = [paw + v3(3.6, -0.6, dz) for dz in (-1.1, 0.0, 1.1)]
    claws = [(t, t + v3(1.6, -0.9, 0.0)) for t in toes]
    return fn, claws


def hind_leg_sdf(pts):
    hip, st, hk, paw = pts
    d_fe = along(hip, st)
    d_ti = along(st, hk)
    back = np.array([-1.0, 0.0, 0.0])

    def fn(p):
        d = ell(p, hip + (st - hip) * 0.42 + back * 3.2, (10.5, 8.0, 5.8), d_fe)  # 大腿：后面饱满
        d = V2.smin(d, ell(p, hip + v3(-2.0, 2.0), (7.0, 6.0, 5.6)), 2.5)  # 臀肌
        d = V2.smin(d, cone(p, st, hk, 3.4, 1.8), 1.6)  # 小腿
        d = V2.smin(d, ell(p, st + (hk - st) * 0.3 + back * 1.6, (5.4, 3.0, 2.9), d_ti), 1.4)  # 腿肚
        d = V2.smin(d, ell(p, hk + back * 1.0 + v3(0, 0.6), (1.9, 1.7, 1.7)), 0.6)  # 飞节（跟骨往后凸）
        d = V2.smin(d, cone(p, hk, paw, 1.75, 1.55), 0.7)
        d = V2.smin(d, ell(p, paw + v3(1.4, -0.2), (3.6, 1.8, 2.4)), 0.8)
        for k in range(3):  # 大腿后面往下垂的“裤”
            r = hip + (st - hip) * (0.35 + 0.22 * k) + back * (7.0 - 1.5 * k)
            d = V2.smin(d, tuft(p, r, -112.0 - 10 * k, 5.6 - 0.6 * k, 2.6), 0.8)
        return d
    toes = [paw + v3(3.8, -0.6, dz) for dz in (-1.1, 0.0, 1.1)]
    claws = [(t, t + v3(1.6, -0.9, 0.0)) for t in toes]
    return fn, claws


# 头（头局部：原点在颈端，x 沿脸往前、y 上；建好再按 HEAD_TILT 低头）
NARROW = 1.25  # 吻部左右收窄（z 方向拉伸距离）


def head_sdf():
    def fn(p):
        pn = p * np.array([1.0, 1.0, NARROW])
        d = ell(p, v3(4.8, 3.0), (7.2, 6.0, 5.3))  # 颅
        d = V2.smin(d, ell(p, v3(0.5, 1.8), (4.6, 5.0, 4.6)), 2.0)  # 后脑，接颈
        d = V2.smin(d, ell(p, v3(9.0, 4.2), (4.6, 3.4, 4.3)), 1.6)  # 额、眉
        d = V2.smin(d, cone(pn, v3(10.5, 1.4), v3(22.5, -2.3), 3.5, 1.2), 1.8)  # 吻：长
        d = V2.smin(d, cone(pn, v3(8.0, -1.8), v3(20.5, -3.9), 3.0, 1.0), 1.2)  # 下颌
        for z in (-3.6, 3.6):
            d = V2.smin(d, ell(p, v3(6.5, -0.6, z), (4.8, 3.6, 2.4)), 1.4)  # 颊
            for k, (y, a, ln) in enumerate(((0.8, 168.0, 6.0), (-0.8, 190.0, 7.5), (-2.6, 210.0, 7.0),
                                            (-4.2, 232.0, 5.5))):  # 颊后炸开的毛
                d = V2.smin(d, tuft(p, v3(4.5, y, z * 1.12), a, ln, 2.2), 0.6)
        return d
    return fn


def head_local(q):
    """头局部（未低头）→ 头物体局部（已低头，设计稿三维）。"""
    return (rotz(HEAD_TILT) @ np.asarray(q, np.float64).T).T if np.ndim(q) > 1 else rotz(HEAD_TILT) @ q


# 耳：根中点、尖、根宽、朝向（头局部，未低头）
EARS = {False: (v3(2.4, 7.0, -3.6), v3(-2.2, 22.0, -5.8)), True: (v3(1.0, 7.0, 3.6), v3(-6.0, 21.0, 5.8))}
EAR_W, EAR_T = 10.5, 1.6


def ear_arrays(far):
    """耳：往里凹的三角厚片（截面是一道弯，前面凹），里面朝前偏镜头。返回头物体局部的模型坐标 + 属性 inner。"""
    base, tip = EARS[far]
    u = tip - base
    H = float(np.linalg.norm(u))
    u /= H
    a = np.array([1.0, 0.0, 0.0]) - u * u[0]  # 横（沿头的前后）
    a /= np.linalg.norm(a)
    nrm = np.cross(u, a)  # 厚度方向
    if (nrm[2] > 0) != far:
        nrm = -nrm
    # 里面（凹面）朝前偏镜头：绕耳的长轴转一点
    yaw = math.radians(-35.0)
    a, nrm = a * math.cos(yaw) + nrm * math.sin(yaw), nrm * math.cos(yaw) - a * math.sin(yaw)
    nh, ns = 12, 9
    verts, inner = [], []
    for j in range(nh):
        h = j / (nh - 1) * 0.97
        w = EAR_W / 2 * (1 - h) ** 0.8
        c = base + u * H * h
        ring = []
        for i in range(ns):  # 前面（凹）：s 从 -1 到 1
            s = -1 + 2 * i / (ns - 1)
            ring.append((c + a * w * s + nrm * (1.3 * (1 - s * s) * (1 - h) - 0.2), 1.0 if abs(s) < 0.8 else 0.0))
        for i in range(ns - 2, 0, -1):  # 后面（凸）
            s = -1 + 2 * i / (ns - 1)
            ring.append((c + a * w * s * 0.96 + nrm * (1.3 * (1 - s * s) * (1 - h) - 0.2 - EAR_T * (1 - 0.6 * h)), 0.0))
        for q, f in ring:
            verts.append(q)
            inner.append(f)
    m = 2 * ns - 2
    F = [(j * m + i, j * m + (i + 1) % m, (j + 1) * m + (i + 1) % m, (j + 1) * m + i) for j in range(nh - 1)
         for i in range(m)]
    verts.append(base + u * H * 1.02); inner.append(0.0)
    tp = len(verts) - 1
    b0 = (nh - 1) * m
    F += [(b0 + i, b0 + (i + 1) % m, tp) for i in range(m)]
    verts.append(base - u * 0.3); inner.append(0.0)
    bc = len(verts) - 1
    F += [((i + 1) % m, i, bc) for i in range(m)]
    V = V2.d3m(head_local(np.asarray(verts)))
    hgt = [(np.asarray(q) - base) @ u / H for q in verts]
    return V, outward(V, F), {"inner": inner, "zone": [-0.5 * max(0.0, (t - 0.62) / 0.38) for t in hgt]}


# ================================================================ 九尾
# 扇面（move 时）：根部方向（度，从 +x 逆时针）、长（单位）、尖上离镜头（单位，负 = 近）、中段弯（度）。
# 双数在前层（亮）、单数在后层（暗，长一点，尖从前层后面探出来）；九条长短、弯度略有不同
FAN = [(56.0, 51.0, -8.0, -24.0), (74.0, 61.0, 7.0, -30.0), (92.0, 61.0, -10.0, -25.0), (110.0, 66.0, 8.0, -33.0),
       (128.0, 58.0, -11.0, -27.0), (146.0, 61.0, 8.0, -23.0), (164.0, 50.0, -10.0, -30.0), (182.0, 50.0, 7.0, -25.0),
       (200.0, 39.0, -8.0, -21.0)]
FAN_MID = 128.0
TAIL_T = [0.0, 0.1, 0.25, 0.45, 0.62, 0.78, 0.91, 1.0]
TAIL_R = [1.2, 2.9, 5.6, 6.7, 6.2, 4.3, 1.8, 0.2]  # 根细、中段蓬、往尖收成笔尖（尖上那截是火）
FIRE_FROM = 0.74


def tail_layout(anim, frame, n):
    """每条尾巴：dict(ang 根部方向, ln 长, z 尖上离镜头, bow 中段弯, turn 整条均匀转的角度, wave 波幅, ph 相位,
    puff 炸毛, fire 火的大小)。"""
    ph = 2 * math.pi * frame / max(n, 1)
    out = []
    for k, (ang, ln, z, bow) in enumerate(FAN):
        s = (ang - FAN_MID) / 72.0  # -1（最前）.. 1（最后）
        d = dict(ang=ang, ln=ln, z=z, bow=bow, turn=0.0, wave=4.0, ph=ph + 0.7 * k, puff=1.0, fire=1.0)
        if anim == "move":
            d["ang"] = ang + 2.5 * math.sin(ph + 0.7 * k)
        elif anim == "sweep":
            # 0 往上收拢；1 从背上往前拱（尖朝前，预警停在这）；2 往前下方砸；3 扫到身前低处；4、5 收回扇面
            # 出手时尾巴猛地抻长（妖力），才够得着身前
            a0, turn, bw, lk, puff, fire = [(104 + 24 * s, -14.0, -10.0, 0.96, 1.1, 1.2),
                                            (96 + 18 * s, -125.0, 0.0, 1.22, 1.25, 1.7),
                                            (72 + 14 * s, -122.0, 0.0, 1.5, 1.2, 1.6),
                                            (42 + 12 * s, -112.0, 0.0, 1.45, 1.1, 1.3),
                                            (104 + 40 * s, -60.0, -10.0, 1.08, 1.0, 1.1),
                                            (ang - 3.0, -8.0, bow, 1.0, 1.0, 1.0)][frame]
            d.update(ang=a0, turn=turn, bow=bw, ln=ln * lk, puff=puff, fire=fire, wave=2.0, ph=ph + 0.5 * k)
        else:  # summon：张到最开、尾尖青火一盏盏腾起来
            spread = [1.0, 1.07, 1.09, 1.04][frame]  # 身子后仰会带着尾巴往后转，这里先抵掉大半
            d.update(ang=min(FAN_MID + (ang - FAN_MID) * spread, 194.0) - 0.8 * [3.0, 6.0, 7.0, 4.0][frame], bow=bow * 0.7, wave=3.0, ph=ph + 0.5 * k,
                     puff=1.0 + 0.12 * (frame in (1, 2)), fire=[1.2, 1.6, 1.9, 1.4][frame])
        out.append(d)
    return out


def tail_curve(root, d, n=26):
    """一条尾巴的中线（设计稿三维）：根部方向 ang，中段往顺时针弯 bow、尖往回勾（S 形），整条再均匀转 turn，
    尖略往外张，带一道往尖传的波。"""
    ang, ln, z_tip, bow, turn, wave, ph = (d[k] for k in ("ang", "ln", "z", "bow", "turn", "wave", "ph"))
    pts = [np.asarray(root, np.float64)]
    step = ln / n
    spread = (ang - FAN_MID) * 0.18 * (1.0 - min(1.0, abs(turn) / 90.0))
    zr = 1.5 if z_tip > 0 else -1.5
    for i in range(n):
        t = (i + 0.5) / n
        a = (ang + bow * math.sin(math.pi * t) - bow * 1.4 * t ** 3 + spread * t + turn * t
             + wave * math.sin(ph - 2.4 * t) * (0.25 + 0.75 * t))
        r = math.radians(a)
        q = pts[-1] + step * np.array([math.cos(r), math.sin(r), 0.0])
        q[2] = zr + (z_tip - zr) * smooth01((i + 1) / n * 1.2)
        pts.append(q)
    return np.asarray(pts)


def tail_radius(t, puff=1.0):
    return float(np.interp(t, TAIL_T, TAIL_R)) * (1.0 + (puff - 1.0) * np.interp(t, [0, 0.3, 0.8, 1], [0, 1, 1, 0]))


def tail_arrays(c, puff):
    """尾巴的管：模型坐标的 (顶点, 面, 属性)；属性 fire（尖上那截火）、hot（火心）、zone。"""
    P = V2.d3m(c)

    def prof(t):
        r = tail_radius(t, puff)
        return r * 0.82 / 25.0, r / V2.VZ, r / V2.VZ
    V, F, A = V2.tube_arrays([Vector(q) for q in P], prof, nu=20, nv=64, cap0=True, cap1=True)
    t = np.asarray(A["su"])
    A["fire"] = list(smooth01((t - FIRE_FROM) / 0.12))
    A["hot"] = list(0.85 * smooth01((t - 0.9) / 0.1))
    A["zone"] = list(0.12 * np.interp(t, [0, 0.4, 1], [-1, 0, 0]))
    # 轮廓上一簇簇尖毛（朝尾尖、略往外撇）：同一个物体，管子里那半截被挡住，只露出外缘的尖
    parts = [(V, F, A)]
    tan = np.gradient(c[:, :2], axis=0)
    tan /= np.linalg.norm(tan, axis=1, keepdims=True) + 1e-9
    n = len(c)
    rng = np.random.default_rng(int(abs(c[-1, 0]) * 10) % 97)
    for j in range(18):
        tt = 0.12 + 0.68 * j / 17 + rng.uniform(-0.015, 0.015)
        i = int(tt * (n - 1))
        side = 1 if j % 2 else -1
        r = tail_radius(tt, puff)
        nr = np.array([-tan[i, 1], tan[i, 0]]) * side
        a = math.radians(math.degrees(math.atan2(tan[i, 1], tan[i, 0])) + side * rng.uniform(18.0, 30.0))
        dz = rng.uniform(-0.35, 0.35) * r * 0.8
        root = c[i] + np.array([nr[0], nr[1], 0.0]) * r * 0.5 + np.array([0.0, 0.0, dz])
        tip = root + np.array([math.cos(a), math.sin(a), 0.0]) * (r * rng.uniform(1.0, 1.35) + 2.8)
        Vt, Ft, At = cone_arrays(root, tip, r * 0.45, nu=10, nv=6)
        m = len(Vt)
        parts.append((Vt, Ft, {"su": [tt] * m, "sv": At["sv"], "fade": [tt] * m, "fire": [0.0] * m,
                               "hot": [0.0] * m, "zone": [0.0] * m}))
    return V2.merge_arrays(parts)


def tail_flames(c, fire, ph, z):
    """尾尖的火舌：往外三条、略往上飘、随相位抖。"""
    out = []
    tip = c[-1, :2]
    d = c[-1, :2] - c[-4, :2]
    d /= np.linalg.norm(d) + 1e-9
    base_a = math.degrees(math.atan2(d[1], d[0]))
    for j, (da, lj) in enumerate(((-30.0, 0.7), (-8.0, 1.0), (14.0, 0.9), (34.0, 0.6))):
        a0 = base_a + da * 0.6 + 8.0 * math.sin(ph * 1.7 + j)
        pts, w = [], []
        x, y = tip - d * 2.0
        L = 13.0 * fire * lj
        for q in np.linspace(0, 1, 9):
            rise = min(0.9, 0.35 + 0.5 * max(0.0, fire - 1.0))  # 火越大越往上腾
            aa = math.radians(a0 + (90.0 - a0) * rise * (2 * q - q * q) + 12.0 * math.sin(ph + 3 * q + j))
            pts.append((x, y))
            x += math.cos(aa) * L / 8
            y += math.sin(aa) * L / 8
            w.append(3.8 * fire ** 0.5 * (1 - q) ** 0.8 + 0.15)
        P, W, Sd = V2.design_strip(np.asarray(pts), np.asarray(w), (z - 0.8) / 25.0)
        out.append(V2.strip_arrays(P, W, Sd))
    return out


# ================================================================ 毛领、毛簇（隐式曲面：一簇簇尖叶形的毛，墨线勾出外缘）
def tuft(p, root, ang, length, r0, dz=0.0):
    """一簇毛：从 root 往 ang（度，x-y 平面里）伸出 length，根粗 r0、尖收成一点。"""
    a = math.radians(ang)
    tip = np.asarray(root, np.float64) + np.array([math.cos(a) * length, math.sin(a) * length, dz])
    return cone(p, root, tip, r0, 0.3)


def ruff_lobes(sk):
    """毛领的几团毛量：(中心, 半径, 朝向角（度）, 边上收笔触的弧段（度）)。外形是柔的，几团之间糅开。"""
    tb = sk["tb"]
    hp = sk["head_piv"]
    n0 = tb(NECK0)
    u = hp - n0
    ua = math.degrees(math.atan2(u[1], u[0]))
    mid = n0 + u * 0.45
    lobes = [(tb(v3(34.0, 32.0)), (6.5, 10.5, 8.0), -14.0, (-150.0, 40.0)),  # 胸前一兜：往前鼓、往下垂
             ((hp + tb(v3(34.0, 34.0))) / 2 + v3(0.5, -1.0), (5.5, 6.5, 6.6), ua - 90.0, (-120.0, 20.0)),  # 颈下
             (mid + v3(-1.0, -3.0, -5.6), (11.5, 6.8, 3.4), ua - 28.0, (-200.0, -40.0)),  # 颈侧（近）：一大片往后下披
             (n0 + v3(-4.0, -5.5, -6.6), (9.5, 7.0, 3.2), -138.0, (-120.0, 60.0)),  # 颈根盖肩（近）
             (mid + v3(-1.0, -3.0, 5.6), (11.5, 6.8, 3.4), ua - 28.0, (-200.0, -40.0))]  # 颈侧（远）
    return lobes


def ruff_sdf(sk, ph):
    """胸前、颈下一圈蓬松的白毛领：几团柔的毛量糅在一起（颈侧往后下披的只有一层，宽而软）。"""
    lobes = ruff_lobes(sk)

    def fn(p):
        d = None
        for c, r, a, _ in lobes:
            v = ell(p, c, r, rotz(a))
            d = v if d is None else V2.smin(d, v, 3.5)
        return d
    return fn, [c for c, *_ in lobes]


def ruff_strokes(sk, ph):
    """毛领边上收的笔触尖毛：沿每团毛量的外缘（下沿、后沿）一簇簇往外、往后下撇，根藏在毛量底下。"""
    rng = np.random.default_rng(5)
    out = []
    down = np.array([math.cos(math.radians(-112.0)), math.sin(math.radians(-112.0))])
    for li, (c, r, a, (t0, t1)) in enumerate(ruff_lobes(sk)):
        if c[2] > 2.0:  # 远侧的看不见
            continue
        R = rotz(a)[:2, :2]
        nseg = int(abs(t1 - t0) / 13.0) + 2
        for th in np.linspace(t0, t1, nseg):
            th = math.radians(th + rng.uniform(-4, 4))
            e = R @ np.array([r[0] * math.cos(th), r[1] * math.sin(th)])
            nrm = R @ np.array([math.cos(th) / r[0], math.sin(th) / r[1]])
            nrm /= np.linalg.norm(nrm)
            dv = nrm + 0.9 * down
            ang = math.degrees(math.atan2(dv[1], dv[0])) + 3.0 * math.sin(ph + th * 3)
            root = c + np.array([e[0] * 0.82, e[1] * 0.82, -0.6 - (r[2] * 0.25 if c[2] < -2 else 0.0)])
            ln = rng.uniform(5.5, 8.0)
            out.append(stroke_arrays(arc(root, ang, ang - 16.0 * np.sign(nrm[0] + 1e-6), ln, n=7, z=root[2]),
                                     rng.uniform(1.9, 2.6), taper=0.6, w_end=0.1))
    return out


# 身子上的几簇毛（身子局部）：胸下一排往后下垂、尾根一圈往扇面方向炸开（盖住九条尾巴的根）
BELLY_TUFTS = [((22.0 - 3.6 * k, 18.6 + 0.35 * (3.6 * k) ** 1.15 / 2.0, 0.0), -112.0 - 4 * k, 4.6 - 0.25 * k, 2.2)
               for k in range(6)]
RUMP_TUFTS = [((-33.0 + 4.0 * math.cos(math.radians(a)), 42.0 + 4.0 * math.sin(math.radians(a)), 0.0), a + 10.0, 6.0, 3.6)
              for a in (95, 140, 185)]


def body_tufts_sdf(q):
    d = None
    for root, a, ln, r0 in BELLY_TUFTS + RUMP_TUFTS:
        v = tuft(q, np.asarray(root, np.float64), a, ln, r0)
        d = v if d is None else np.minimum(d, v)
    return d


def ear_fur(far):
    """耳里一簇白毛：从耳根里面往耳尖、略往外撇（头局部）。"""
    base, tip = EARS[far]
    out = []
    zf = -1.2 if far else -1.6
    for k, (s, ln) in enumerate(((-0.25, 7.5), (0.05, 9.0), (0.3, 6.5))):
        root = base + v3(1.2 + 2.4 * s, 0.6, 0.0)
        d = tip - base
        a = math.degrees(math.atan2(d[1], d[0])) + 14.0 * s
        c = arc(root, a, a - 6.0, ln, n=6)
        c = head_local(c)
        c[:, 2] = base[2] + zf - (0.6 if not far else 0.0)
        out.append(stroke_arrays(c, 2.2, taper=0.9))
    return out


# ================================================================ 组装
def fur_material(name, seed, bias=-0.06, rim=0.6, streak=0.14, zone=True):
    return V2.paint_material(name, FUR_STOPS, wash=0.24, wash_scale=2.6, seed=seed, shade_attr="zone" if zone else None,
                             shade_gain=1.0, streak=streak, streak_scale=(4.0, 60.0), rim_hex=RIM, rim=rim,
                             rim_power=2.3, value_var=0.04, edge=0.22, bias=bias)


def _dummy(name, mat, line, parent, cun=False):
    ob = V2.mesh_from_arrays(name, [(0, 0, 0), (0.001, 0, 0), (0, 0.001, 0)], [(0, 1, 2)], mat, line, parent)
    if cun:
        bpy.data.collections[B.CUN_COLLECTION].objects.link(ob)
    return ob


def build_boss():
    root = B.empty("JWRoot")
    body = B.empty("JWBody", root)
    M = {
        "fur": fur_material("JWFur", 3.0),
        "leg": fur_material("JWFurLeg", 5.0),
        "far": fur_material("JWFurFar", 6.0, bias=-0.34, rim=0.35),
        "head": fur_material("JWFurHead", 7.0, bias=0.0),
        "mane": fur_material("JWMane", 8.0, bias=0.06, streak=0.22),
    }
    for nm, bias, seed in (("tail", -0.04, 9.0), ("tail_far", -0.42, 10.0)):
        m = V2.paint_material("JW" + nm, FUR_STOPS, wash=0.24, wash_scale=2.6, seed=seed, shade_attr="zone", streak=0.22,
                              streak_scale=(4.0, 60.0), rim_hex=RIM, rim=0.6 if nm == "tail" else 0.35, rim_power=2.3,
                              value_var=0.04, edge=0.22, bias=bias, glow_attr="fire", glow_gain=1.0)
        mix_attr(m, "fire", FIRE_DEEP if nm == "tail_far" else FIRE, 0.92)
        mix_attr(m, "hot", FIRE_HOT, 1.0)
        M[nm] = m
    M["ear"] = V2.paint_material("JWEar", EAR_STOPS, wash=0.2, seed=11.0, rim_hex=RIM, rim=0.5, edge=0.1,
                                 shade_attr="zone")
    mix_attr(M["ear"], "inner", "#8E9AA6", 0.85)
    brush = dict(alpha=1.0, edge_soft=0.35, edge_dark=0.12, streak=0.4, streak_from=0.4, scale=(3.0, 10.0),
                 fade_from=0.7, comb=4.0)
    M["ruff"] = V2.brush_material("JWRuff", RUFF_STOPS, seed=21.0, **brush)
    M["ruff_far"] = V2.brush_material("JWRuffFar", RUFF_FAR, seed=22.0, **brush)
    M["flame"] = V2.brush_material("JWFlame", FIRE_STOPS, alpha=0.95, edge_soft=0.3, edge_dark=0.0, streak=0.35,
                                   streak_from=0.45, scale=(3.0, 8.0), fade_from=0.55, seed=31.0, glow=1.0,
                                   glow_to=0.9, glow_tip=0.5, comb=5.0)
    M["ink"] = B.flat_material("JWInk", I["jiao"])
    M["eye"] = B.emissive_material("JWEye", EYE, 1.0)
    M["hot"] = B.emissive_material("JWEyeHot", EYE_HOT, 1.0)
    M["mark"] = B.emissive_material("JWMark", "#3CCFBC", 1.0)
    M["liner"] = V2.glow_flat("JWEyeLiner", I["jiao"], 0.5)  # 眼线：白天是墨，夜里透一圈青光
    parts = {"root": root, "body": body, "M": M, "dyn": {}}
    D = parts["dyn"]
    D["Body"] = _dummy("JWBodyMesh", M["fur"], "outer", body, cun=True)
    for name in ("front", "hind"):
        for far in (False, True):
            D[(name, far)] = _dummy(f"JW{name.title()}{'Far' if far else 'Near'}", M["far"] if far else M["leg"],
                                    "outer", body, cun=not far)
    D["Claws"] = _dummy("JWClaws", M["ink"], "none", body)
    for k in range(len(FAN)):
        D[("tail", k)] = _dummy(f"JWTail{k}", M["tail_far"] if k % 2 else M["tail"], "outer", body)
    D["Ruff"] = _dummy("JWRuff", M["mane"], "inner", body)
    D["RuffFur"] = _dummy("JWRuffFur", M["ruff"], "none", body)
    D["Flames"] = _dummy("JWFlames", M["flame"], "none", body)
    # 头：静止的网格（已低头），每帧只摆位置、转角
    Vh, Fh, Ah = _head_arrays()
    head = V2.mesh_from_arrays("JWHead", Vh, Fh, M["head"], "outer", body, attrs=Ah)
    parts["head"] = head
    for far in (False, True):
        V, F, A = ear_arrays(far)
        V2.mesh_from_arrays(f"JWEar{'Far' if far else 'Near'}", V, F, M["ear"] if not far else M["ear"], "outer", head,
                            attrs=A)
    fur = ear_fur(False)
    V2.mesh_from_arrays("JWHeadFur", *V2.merge_arrays(fur)[:2], M["ruff"], "none", head,
                        attrs=V2.merge_arrays(fur)[2], smooth=False)
    nose = head_local(v3(22.7, -2.0))
    B.mesh_object("JWNose", K.ellipsoid((1.3 / 25, 1.1 / 25, 1.0 / V2.VZ)), M["ink"], "none", head,
                  loc=Vector(V2.d3m(nose)))
    mouth = head_local(np.array([v3(21.8, -3.7), v3(18.0, -3.3), v3(14.0, -2.5), v3(10.8, -1.6)]))
    mouth[:, 2] = -3.4
    V2.mesh_from_arrays("JWMouth", *stroke_arrays(mouth, 0.7, taper=0.6, w_end=0.2)[:2], M["ink"], "none", head,
                        smooth=False)
    pose_boss(parts, "move", 0, 8)
    _face(parts)
    return root, parts, parts["sockets"]


def _head_arrays():
    fn = head_sdf()
    V, F = V2.sdf_mesh(fn, v3(-6.0, -9.0, -8.0), v3(26.0, 12.0, 8.0), 0.32, project=2)
    zone = 0.18 * np.clip((-V[:, 1] - 1.0) / 4.0, 0, 1)  # 下颌、颊底下白一点
    Vl = head_local(V)
    return V2.d3m(Vl), [f[::-1] for f in F], {"zone": list(zone)}


def _screen(head, q_local):
    """头局部（未低头）的点 → 画面（单位）。"""
    w = head.matrix_world @ Vector(V2.d3m(head_local(np.asarray(q_local, np.float64))))
    right, up, _ = B.camera_basis()
    return 25.0 * w.dot(right), 25.0 * w.dot(up)


def _face(parts):
    """脸：E 向按画面上的形状投到头上——丹凤眼（细长上挑，墨勾眼线带一笔上挑的尾）、青眼、竖瞳，额心的青火印，泪沟一笔墨。"""
    M, head = parts["M"], parts["head"]
    B.set_direction(parts["root"], "E")
    bpy.context.view_layer.update()
    tree = V2.bvh_world(head)
    cx, cy = _screen(head, v3(11.4, 3.3, -3.6))
    ix, iy = _screen(head, v3(14.6, 2.4, -3.0))  # 内眼角（近吻）
    ox, oy = _screen(head, v3(8.4, 4.0, -3.9))
    ax = np.array([ox - ix, oy - iy])
    L = float(np.linalg.norm(ax))
    ax /= L
    ang = math.atan2(ax[1], ax[0])
    ax = np.array([math.cos(ang - math.radians(12)), math.sin(ang - math.radians(12))])  # 再往上挑一点
    up = np.array([-ax[1], ax[0]])
    if up[1] < 0:
        up = -up
    c = np.array([(ix + ox) / 2, (iy + oy) / 2])
    hl = 3.3

    def almond(sc, top, bot, flick=0.0):
        pts = []
        for u in np.linspace(-1, 1, 15):
            pts.append(c + ax * hl * sc * u + up * top * sc * (1 - u * u) ** 0.8 * (1 + 0.3 * u))
        if flick:
            pts.append(c + ax * hl * (sc + flick) + up * 0.9)
            pts.append(c + ax * hl * (sc + flick * 0.55) + up * 0.15)
        for u in np.linspace(1, -1, 15)[1:-1]:
            pts.append(c + ax * hl * sc * u - up * bot * sc * (1 - u * u) ** 0.9)
        return [tuple(q) for q in pts]
    V2.design_patch("JWEyeInk", tree, V2.closed_smooth(almond(1.22, 1.55, 0.95, flick=0.75), 80), M["liner"], head,
                    lift=0.006, spacing=0.3)
    V2.design_patch("JWEye", tree, V2.closed_smooth(almond(1.0, 1.05, 0.62), 50), M["eye"], head, lift=0.007,
                    spacing=0.25)
    V2.design_patch("JWEyeHot", tree, V2.closed_smooth(almond(0.55, 0.85, 0.5), 30), M["hot"], head, lift=0.008,
                    spacing=0.2)
    pc = c + ax * 0.5
    pupil = [tuple(pc + up * 0.95 * math.cos(t) * 1.0 + ax * 0.3 * math.sin(t)) for t in np.linspace(0, 2 * math.pi, 16,
                                                                                                 endpoint=False)]
    V2.design_patch("JWPupil", tree, pupil, M["ink"], head, lift=0.009, spacing=0.15)
    # 泪沟：内眼角往下顺着吻侧一笔墨
    t0 = c - ax * hl * 1.05
    tear = [t0 + np.array([0.3, -0.3]), t0 + np.array([1.3, -1.9]), t0 + np.array([2.0, -3.0])]
    poly = [tuple(q + np.array([0.35, 0.0]) * (1 - k / 2)) for k, q in enumerate(tear)] + \
           [tuple(q - np.array([0.35, 0.0]) * (1 - k / 2)) for k, q in reversed(list(enumerate(tear)))]
    V2.design_patch("JWTear", tree, poly, M["ink"], head, lift=0.006, spacing=0.15)
    # 额心的青印：一簇往上挑的小火苗（三瓣）
    mx, my = _screen(head, v3(8.4, 7.2, -0.6))
    mark = [(mx + 1.15 * x, my + 1.15 * y) for x, y in
            ((0.0, -0.8), (0.55, -0.05), (0.3, 0.6), (0.1, 1.45), (-0.18, 0.55), (-0.6, 0.95), (-0.55, -0.05))]
    V2.design_patch("JWMark", tree, V2.closed_smooth(mark, 30), M["mark"], head, lift=0.006, spacing=0.2)
    sock = B.empty("JWSocketEyes", head)
    sock.location = Vector(V2.d3m(head_local(v3(11.4, 3.3, -1.0))))
    parts["sockets"] = {"eyes": sock}
    B.set_direction(parts["root"], "S")
    bpy.context.view_layer.update()


# ================================================================ 姿态
def frame_arrays(anim, frame, n):
    """一帧所有动的部件：{名: (顶点, 面, 属性)}（模型坐标），以及头的位置、转角。"""
    p = pose_params(anim, frame, n)
    sk = skeleton(p)
    out = {}
    fn, pts = body_sdf(sk)
    lo = np.min(pts, 0) - 17.0
    hi = np.max(pts, 0) + 17.0

    def body_attrs(V):
        y = V[:, 1]
        x = V[:, 0]
        under = np.clip((30.0 - y) / 8.0, 0, 1) * np.clip((x + 10.0) / 20.0, 0, 1)
        return {"zone": list(0.14 * under - 0.08 * np.clip((y - 42.0) / 3.0, 0, 1)),
                "su": list((x + 40.0) / 80.0), "sv": list(np.arctan2(V[:, 2], y - 34.0) / (2 * math.pi))}
    out["Body"] = V2.sdf_arrays(fn, lo, hi, STEP, body_attrs)
    claws = []
    for name in ("front", "hind"):
        for far in (False, True):
            lp = sk[(name, far)]
            f, cl = (front_leg_sdf if name == "front" else hind_leg_sdf)(lp)
            lo, hi = np.min(lp, 0) - 11.0, np.max(lp, 0) + 11.0

            def leg_attrs(V, lp=lp):
                a, b = lp[0], lp[-1]
                ab = b - a
                t = np.clip(((V - a) @ ab) / (ab @ ab), 0, 1)
                return {"zone": list(-0.16 * np.clip((7.0 - V[:, 1]) / 7.0, 0, 1)), "su": list(t),
                        "sv": list(np.arctan2(V[:, 2] - lp[-1][2], V[:, 0] - (a[0] + ab[0] * t)) / (2 * math.pi))}
            out[(name, far)] = V2.sdf_arrays(f, lo, hi, STEP * 0.8, leg_attrs)
            claws += [cone_arrays(a, b, 0.55) for a, b in cl]
    out["Claws"] = V2.merge_arrays(claws)
    # 九尾
    fur_n, fur_f, flames = [], [], []
    for k, d in enumerate(tail_layout(anim, frame, n)):
        d["ang"] += p["pitch"]
        c = tail_curve(sk["tail_root"], d)
        out[("tail", k)] = tail_arrays(c, d["puff"])
        flames.extend(tail_flames(c, d["fire"], d["ph"] + 1.3 * k, c[-1, 2]))
    out["Flames"] = V2.merge_arrays(flames)
    fr, pts = ruff_sdf(sk, p["ph"])

    def mane_attrs(V):
        return {"zone": list(0.1 + 0.0 * V[:, 0]), "su": list((V[:, 1] - 10.0) / 50.0),
                "sv": list(np.arctan2(V[:, 2], V[:, 0] - 30.0) / (2 * math.pi))}
    out["Ruff"] = V2.sdf_arrays(fr, np.min(pts, 0) - 14.0, np.max(pts, 0) + 14.0, 0.45, mane_attrs)
    out["RuffFur"] = V2.merge_arrays(ruff_strokes(sk, p["ph"]))
    return out, sk


def pose_boss(parts, anim, frame, n):
    arrs, sk = frame_arrays(anim, frame, n)
    for key, ob in parts["dyn"].items():
        V, F, A = arrs[key]
        K.replace_mesh(ob, V2.arrays_build(V, F), smooth=not (isinstance(key, str) and key in (
            "Flames", "RuffFur")), attrs=A)
    head = parts["head"]
    head.location = Vector(V2.d3m(sk["head_piv"]))
    head.rotation_euler = (math.radians(-sk["head_rot"]), 0.0, 0.0)
    head.scale = (HEAD_K, HEAD_K, HEAD_K)
    parts["body"].scale = (G, G, G)
    bpy.context.view_layer.update()
