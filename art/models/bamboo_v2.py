"""竹魅（精修三维）：一截截青竹节拼成的细长人形。

设定（LORE-TEXT 4.1）：竹海里的老竹吸了魂，成了魅。它躲在竹丛里放竹刺，你找它，它就不动。
外形（世界观会话）：一截截青竹节拼成的细长人形，手指是竹枝竹叶，头是一团竹叶，叶缝里两点眼；放竹刺时身上竹节裂开。
主色青竹绿、墨；静、诡异。
造型：比主角高一头。身子是一粗一细两根竹，腿、臂各两截竹（关节就是竹节），脚是削尖的竹桩；
每一截竹单独成段，段与段之间是一圈墨色的竹节（像墨竹画里一节一节断开的竿），节下一圈淡白的竹粉。
手是从腕上的竹节里长出来的三根细竹枝，枝梢挂两三片竹叶（墨竹叶，焦墨到深绿）。
头是一团竹叶：叶子往后上方、往后下方披着，额前两片叶压低成“眉”，下面两片成“颌”，中间的缝里是焦墨的空，
空里两点薄荷色的眼（近大远小）。肩上、胯上的竹节里各冒出一小枝竹叶。
动画（只画 E）：
  idle  4 帧：像一根竹子一样立着，竹叶轻摇，身子微晃；眼睛暗（游戏里没用到，留着）。
  move  6 帧：直着腿一顿一顿地走（只在竹节处弯），身子一步一沉，两臂垂着、反着轻摆。
  shoot 5 帧（不循环，2 帧蓄力）：0–1 身子往后弯成一张拉满的弓，近手把一根削尖的竹刺举到头后，远手往前指；
        身上的竹节一节节裂开、缝里透光（1 拉满，游戏在预警期间停在这一帧）；2 甩出去（竹刺离手）；3 收势、缝合上；4 复位。
帧 320²（2 倍），锚点 (0.5, 0.875)。挂点 eyes（两眼之间，偏近眼）、muzzle（近手；蓄力时在竹刺尖上）。

    root, parts, sockets = build_bamboo_wraith()
    pose_bamboo_wraith(parts, "move", i, 6)
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
EYE = "#9BF5C9"
EYE_HOT = "#F2FFF9"
EYE_DIM = "#4E8C74"  # idle：眼睛暗着
VZ = V2.VZ
d2m = V2.d2m
# 青竹的色带（d 从暗到亮）：暗部偏蓝的墨绿 → 竹青 → 亮部偏黄的嫩绿
BAMBOO_STOPS = [(0.00, "#101C18"), (0.16, "#172B22"), (0.30, "#20402D"), (0.44, "#2C5A3A"), (0.56, "#3D7446"),
                (0.68, "#578E52"), (0.82, "#80AB66"), (1.00, "#B5CC88")]
NODE_STOPS = [(0.0, I["jiao"]), (0.45, "#1C2A1E"), (0.75, "#34482F"), (1.0, "#56693F")]  # 竹节：墨色带一点绿
SPIKE_STOPS = [(0.0, "#2A4A2C"), (0.3, "#5E8A4E"), (0.55, "#93B46A"), (0.78, "#C4D296"), (1.0, "#EDEBC4")]  # 竹刺：嫩一点
LEAF_DARK = [(0.0, I["jiao"]), (0.45, "#18231A"), (0.8, "#22362A"), (1.0, "#2E4A36")]  # 墨竹叶：根浓尖淡
LEAF_MID = [(0.0, "#1A2A1F"), (0.5, "#2F4C36"), (1.0, "#4C7352")]  # 远一点的叶：深绿
LEAF_LIGHT = [(0.0, "#22382A"), (0.5, "#3F6A48"), (1.0, "#6E9A62")]  # 顶上受光的叶
RIM = S.mix("#CFEBD2", I["qing"], 0.25)
GLOW = "#9BF5C9"  # 节缝里的光

# ---------------------------------------------------------------- 骨架（设计稿单位，E 向画面，x 前、y 上，锚点为原点）
HIP = (0.0, 28.0)
SPINE = 18.5  # 胯 → 肩
NECK = 3.4
THIGH, SHIN, FOOT = 14.0, 13.2, 4.6
UPPER, FORE = 12.6, 12.0
LAT_LEG, LAT_ARM = 0.07, 0.15  # 腿、臂离中线（米；负 = 近镜头）
R_MAIN, R_BACK = 2.6, 1.8  # 身子两根竹的半径（单位）
R_THIGH, R_SHIN, R_UPPER, R_FORE = 1.55, 1.35, 1.25, 1.1
GROUND = 0.6  # 脚尖着地的高度
LAT_RISE = 25.0 * math.sin(math.radians(S.CAMERA_PITCH_DEG))  # 离镜头远 1 米，画面上高这么多单位


def _chain(root, segs, angs):
    """关节点：root 起，每段按角度（从正下方量，正 = 往前）往下接。"""
    pts = [np.asarray(root, np.float64)]
    for ln, a in zip(segs, angs):
        r = math.radians(a)
        pts.append(pts[-1] + ln * np.array([math.sin(r), -math.cos(r)]))
    return pts


def pose_params(anim, i, n):
    """每帧的骨架参数：pelvis（胯的偏移）、lean（身子前倾，度）、head（低头为正）、legs/arms（近 False / 远 True：
    大腿、小腿、脚 / 上臂、前臂、手指的角度）、spike（手里有竹刺）、crack（节缝裂开 0..1）、eye（眼的亮度 0..1）、
    ph（竹叶摇的相位）、gust（竹叶被往后吹）。"""
    ph = 2 * math.pi * i / n
    if anim == "idle":
        sw = math.sin(ph)
        return {"pelvis": (0.0, 0.0), "lean": 4.0 + 1.3 * sw, "head": 8.0 + 3.0 * math.sin(ph + 0.9),
                "legs": {False: [3.0, -1.0, 82.0], True: [-3.0, -2.0, 82.0]},
                "arms": {False: [6.0 + 1.5 * sw, 9.0 + 1.5 * sw, 14.0], True: [-2.0 + 1.0 * sw, 4.0, 10.0]},
                "spike": 0, "crack": 0.0, "eye": 0.35, "ph": ph, "gust": 0.0}
    if anim == "move":
        legs = {}
        for far, off in ((False, 0.0), (True, math.pi)):
            s = math.sin(ph + off)
            lift = max(0.0, math.cos(ph + off)) ** 1.5
            legs[far] = [3.0 + 19.0 * s + 8.0 * lift, -3.0 + 8.0 * s - 34.0 * lift, 80.0 - 20.0 * lift]
        sw = math.sin(ph)
        return {"pelvis": (0.0, -0.5 + 0.5 * math.cos(2 * ph)), "lean": 9.0 + 1.5 * math.cos(2 * ph),
                "head": 6.0 + 2.5 * math.sin(2 * ph + 0.6), "legs": legs,
                "arms": {False: [5.0 - 13.0 * sw, 10.0 - 10.0 * sw, 16.0 - 6.0 * sw],
                         True: [5.0 + 13.0 * sw, 10.0 + 10.0 * sw, 16.0 + 6.0 * sw]},
                "spike": 0, "crack": 0.0, "eye": 1.0, "ph": ph, "gust": 0.15}
    # shoot：像拉弓——远手往前直直伸出（弓），近手把竹刺搭在远手上、拉到腮边；身子往后弯成一张弓，竹节一节节裂开。
    # 0 搭刺，1 拉满（游戏在预警期间停在这一帧），2 撒手（竹刺飞出），3 收势，4 复位
    T = [  # lean, head, 近臂（上臂、前臂、手）, 远臂, 近腿, 远腿, 胯 dy, 竹刺, 裂开, 吹
        (-3.0, -2.0, [-40.0, 62.0, 84.0], [66.0, 74.0, 80.0], [12.0, -5.0, 80.0], [-11.0, -4.0, 80.0], -0.4, 1, 0.4,
         0.2),
        (-13.0, -8.0, [-90.0, 86.0, 92.0], [99.0, 95.0, 98.0], [17.0, -9.0, 80.0], [-16.0, -7.0, 80.0], -0.9, 1, 1.0,
         0.7),
        (9.0, 6.0, [-118.0, -40.0, -20.0], [96.0, 98.0, 112.0], [19.0, -13.0, 80.0], [-19.0, -9.0, 80.0], -1.2, 0, 0.75,
         -0.35),
        (7.0, 6.0, [-30.0, 10.0, 18.0], [62.0, 52.0, 48.0], [14.0, -9.0, 80.0], [-14.0, -7.0, 80.0], -0.9, 0, 0.3, 0.0),
        (6.0, 6.0, [6.0, 12.0, 16.0], [14.0, 16.0, 18.0], [8.0, -4.0, 80.0], [-8.0, -3.0, 80.0], -0.4, 0, 0.0, 0.1),
    ]
    lean, head, na, fa, nl, fl, dy, spike, crack, gust = T[i]
    return {"pelvis": (0.0, dy), "lean": lean, "head": head, "legs": {False: nl, True: fl},
            "arms": {False: na, True: fa}, "spike": spike, "crack": crack, "eye": 1.0, "ph": 2 * math.pi * i / 5,
            "gust": gust}


def _leg_ground(root, th, sn, ft):
    """站地的腿：脚尖低于 GROUND 时，大腿往前、小腿往后弯（膝往前顶），二分到脚尖正好着地。"""
    def tip_y(d):
        return _chain(root, [THIGH, SHIN, FOOT], [th + 0.9 * d, sn - 1.3 * d, ft])[-1][1]
    if tip_y(0.0) >= GROUND:
        return th, sn
    lo, hi = 0.0, 80.0
    for _ in range(40):
        mid = (lo + hi) / 2
        if tip_y(mid) < GROUND:
            lo = mid
        else:
            hi = mid
    return th + 0.9 * hi, sn - 1.3 * hi


def skeleton(p):
    """二维骨架的关节点（设计稿单位）。"""
    hx, hy = HIP[0] + p["pelvis"][0], HIP[1] + p["pelvis"][1]
    a = math.radians(p["lean"])
    # 身子微微弓着：胯 → 腰 → 肩，上半截比下半截多前倾一点
    waist = (hx + SPINE * 0.45 * math.sin(a * 0.7), hy + SPINE * 0.45 * math.cos(a * 0.7))
    sh = (waist[0] + SPINE * 0.55 * math.sin(a * 1.25), waist[1] + SPINE * 0.55 * math.cos(a * 1.25))
    ah = math.radians(p["lean"] * 1.3 + p["head"])
    neck = (sh[0] + NECK * math.sin(ah), sh[1] + NECK * math.cos(ah))
    out = {"hip": (hx, hy), "waist": waist, "shoulder": sh, "neck": neck, "head_ang": p["lean"] * 1.3 + p["head"],
           "legs": {}, "arms": {}}
    for far, (th, sn, ft) in p["legs"].items():
        th2, sn2 = _leg_ground((hx, hy), th, sn, ft)
        out["legs"][far] = [tuple(q) for q in _chain((hx, hy), [THIGH, SHIN, FOOT], [th2, sn2, ft])]
    arm_root = (sh[0] - 0.6 * math.cos(a), sh[1] - 1.4)
    for far, (u, f, h) in p["arms"].items():
        k = p["lean"] * 0.6
        out["arms"][far] = [tuple(q) for q in _chain(arm_root, [UPPER, FORE, 1.0], [u + k, f + k, h + k])]
    return out


# ---------------------------------------------------------------- 几何
def _resample(path, s0, s1, k=5):
    """设计稿折线 path 上弧长 s0 → s1 的一段，均匀取 k 个点。"""
    P = np.asarray(path, np.float64)
    seg = np.linalg.norm(np.diff(P, axis=0), axis=1)
    s = np.concatenate([[0], np.cumsum(seg)])
    u = np.linspace(s0, s1, k)
    return np.stack([np.interp(u, s, P[:, 0]), np.interp(u, s, P[:, 1])], -1), s[-1]


def _tube(pts2, lat, r_fn, nu=14, nv=None, caps=True):
    """设计稿上的点列 → 模型坐标的管，r_fn(t) 是半径（单位）。截面左右按米、上下按 VZ 换算，侧面看是圆的。"""
    pts = [d2m(x, y, lat) for x, y in pts2]

    def prof(t):
        r = r_fn(t) / 25.0
        return r, r * 25.0 / VZ, r * 25.0 / VZ
    return V2.tube_arrays(pts, prof, nu=nu, nv=nv or max(6, 3 * len(pts)), cap0=caps, cap1=caps)


def culm(path, lat, r_u, nodes, gap=0.0, taper=0.12, end_nodes=(False, True)):
    """一根竹：设计稿折线 path（根 → 梢），离镜头 lat 米，半径 r_u（单位，往梢收 taper），在 nodes（沿长比例）处分节。
    gap > 0：竹节裂开，段与段分开 gap 单位、节缝里放一片光。end_nodes：根、梢两头要不要也画一圈竹节。
    返回 (竹身, 竹节, 光) 三组 (顶点, 面, 属性)。"""
    _, L = _resample(path, 0, 1e-6, 2)
    cuts = [0.0] + list(nodes) + [1.0]
    body, rings, glow = [], [], []

    def r_at(t):
        return r_u * (1 - taper * t)
    for k, (a, b) in enumerate(zip(cuts[:-1], cuts[1:])):
        s0 = a * L + (gap / 2 if k > 0 else 0.0)
        s1 = b * L - (gap / 2 if k < len(cuts) - 2 else 0.0)
        if s1 - s0 < 0.3:
            continue
        pts, _ = _resample(path, s0, s1, 5)
        ta, tb = s0 / L, s1 / L
        V, F, A = _tube(pts, lat, lambda t, ta=ta, tb=tb: r_at(ta + (tb - ta) * t), nu=16, nv=10)
        # 节下的竹粉（淡白一圈）、两头略暗（竹身是圆的）
        ns = []
        for t in A["su"]:
            ns.append(0.32 * math.exp(-((t - 0.12) / 0.07) ** 2) - 0.25 * max(0.0, 1 - t / 0.06)
                      - 0.2 * max(0.0, (t - 0.94) / 0.06))
        A["nodeshade"] = ns
        body.append((V, F, A))
    node_list = [(t, True) for t in nodes]
    if end_nodes[0]:
        node_list.append((0.0, False))
    if end_nodes[1]:
        node_list.append((1.0, False))
    for t, inner in node_list:
        s = t * L
        r = r_at(t) * 1.14
        halves = [(-gap / 2 - 0.42, -gap / 2), (gap / 2, gap / 2 + 0.42)] if (gap > 0 and inner) else [(-0.28, 0.28)]
        for h0, h1 in halves:
            a0, a1 = max(0.0, s + h0), min(L, s + h1)
            if a1 - a0 < 0.05:
                continue
            pts, _ = _resample(path, a0, a1, 3)
            rings.append(_tube(pts, lat, lambda tt, r=r: r * (0.92 + 0.08 * math.sin(math.pi * tt)), nu=16, nv=4))
        if gap > 0 and inner:
            pts, _ = _resample(path, s - gap / 2, s + gap / 2, 3)
            glow.append(_tube(pts, lat, lambda tt, r=r: r * 0.86, nu=12, nv=3))
    return body, rings, glow


def leaf_curve(base, a0, a1, length, width, turn=0.5, ph=0.0, sway=5.0, n=16):
    """一片竹叶的中线和宽（设计稿单位）：从叶柄 base 出发，方向从 a0 转到 a1（度，从 +x 逆时针），
    转弯集中在前 turn（沿长的比例）里，后面顺着垂下去；随相位摆。叶形：柄细、前三成最宽、长长地收尖。"""
    c = []
    x, y = base
    for t in np.linspace(0, 1, n):
        k = min(1.0, t / max(turn, 1e-3))
        k = k * k * (3 - 2 * k)
        aa = math.radians(a0 + (a1 - a0) * k + sway * math.sin(ph + 2.2 * t) * t)
        c.append((x, y))
        x += math.cos(aa) * length / (n - 1)
        y += math.sin(aa) * length / (n - 1)
    t = np.linspace(0, 1, n)
    w = width * np.where(t < 0.28, (t / 0.28) ** 0.5, ((1 - t) / 0.72) ** 0.8)
    return np.asarray(c), np.maximum(w, width * 0.06)


def leaf(base, a0, a1, length, width, lat, turn=0.5, ph=0.0, sway=5.0, ref_lat=0.0):
    """一片竹叶（扁带，正对镜头）。ref_lat：叶根落在“离镜头 ref_lat 米的点”在画面上的位置
    （俯视时远近不同的点画面上高低不同，这里抵掉）。"""
    c, w = leaf_curve((base[0], base[1] - LAT_RISE * (lat - ref_lat)), a0, a1, length, width, turn, ph, sway)
    return V2.strip_arrays(*V2.design_strip(c, w, lat))


def twig(root, ang, length, lat, r0=0.42, bend=-14.0, ph=0.0):
    """一根细竹枝（手指）：从 root 按 ang（度，从 +x 逆时针）伸出，往下弯；返回 (管, 梢的位置, 梢的方向)。"""
    pts = [np.asarray(root, np.float64)]
    a = ang
    for k in range(6):
        a += bend / 6 + 3.0 * math.sin(ph + k)
        r = math.radians(a)
        pts.append(pts[-1] + length / 6 * np.array([math.cos(r), math.sin(r)]))
    arr = _tube(pts, lat, lambda t: r0 * (1 - 0.65 * t), nu=8, nv=12)
    return arr, tuple(pts[-1]), a


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


# 头：一蓬竹叶。叶根聚在头心附近，往四面伸出去再垂下来，顶上圆、两边和后面披散；前面下半截留一道缝，
# 缝里是焦墨的空和两点眼（叶缝里两点眼）。叶子分后、前两层：后层在空的后面，前层压在空的前面、绕开脸。
HEAD_C = (2.2, 5.6)  # 头心，相对颈端（设计稿单位，头不转时）
HOLLOW_C = (3.2, 4.4)  # 焦墨的空（脸）中心，相对颈端
HOLLOW_R = (3.9, 4.0)  # 空的半径（前后、上下，单位）
EYES = [((3.7, 4.0), 1.85, 0.85, -14.0, -0.19), ((6.3, 4.4), 1.2, 0.66, 10.0, -0.17)]  # (相对颈端, 半长, 半高, 斜, 离镜头)


def _head_leaf_specs():
    """头上每片叶：(叶根相对头心, 起始角, 末端角, 长, 宽, 转弯段, 离镜头, 深浅, 相位)。固定种子，帧与帧之间一样。"""
    rng = np.random.default_rng(7)
    out = []
    # 后层：从前上方一直排到后下方
    for k, ang in enumerate(np.linspace(62, 250, 10)):
        ang = float(ang + rng.uniform(-6, 6))
        r0 = 1.6
        down = -95.0 if ang < 88 else 268.0
        ln = 12.0 + 3.5 * math.sin(math.radians(min(ang, 180))) + rng.uniform(-1, 1)
        tone = "light" if k in (3, 5) else ("mid" if k % 3 == 1 else "dark")
        out.append(((r0 * math.cos(math.radians(ang)), r0 * math.sin(math.radians(ang))), ang, down, ln,
                    rng.uniform(3.0, 3.6), rng.uniform(0.5, 0.68), 0.05 + 0.07 * (k % 3) / 2, tone, rng.uniform(0, 6.28)))
    # 前层：顶上、后半边、后下方（绕开前下方的脸）
    for k, ang in enumerate((84, 104, 126, 150, 176, 204, 232)):
        ang = float(ang + rng.uniform(-5, 5))
        r0 = 2.3
        down = -92.0 if ang < 90 else 266.0
        ln = 11.0 + 3.0 * math.sin(math.radians(min(ang, 180))) + rng.uniform(-1, 1)
        out.append(((r0 * math.cos(math.radians(ang)), r0 * math.sin(math.radians(ang))), ang, down, ln,
                    rng.uniform(2.9, 3.4), rng.uniform(0.5, 0.65), -0.2 - 0.03 * (k % 3), "dark" if k % 2 == 0 else "mid",
                    rng.uniform(0, 6.28)))
    # 额前（压在眼上，往前拱、叶尖往下扣）、颌下（托在眼下，往前下）
    out += [((1.6, 2.0), 38.0, -86.0, 12.5, 2.9, 0.62, -0.25, "dark", 0.3),
            ((1.0, 2.6), 58.0, -80.0, 10.5, 2.6, 0.6, -0.24, "dark", 1.1),
            ((1.9, -3.4), -26.0, -96.0, 8.5, 2.4, 0.45, -0.24, "dark", 2.0),
            ((0.6, -3.6), -56.0, -104.0, 8.0, 2.3, 0.4, -0.23, "mid", 2.7)]
    return out


HEAD_LEAVES = _head_leaf_specs()


def head_layout(neck, head_ang, ph, gust):
    """头上一蓬竹叶（设计稿）：返回 [(中线, 宽, 离镜头, 深浅)]、rot（相对颈端的点 → 设计稿）、转角（弧度）。"""
    a = math.radians(-head_ang * 0.5)  # 低头：整蓬往前下转一点
    ca, sa = math.cos(a), math.sin(a)

    def rot(x, y):
        return (neck[0] + x * ca - y * sa, neck[1] + x * sa + y * ca)
    out = []
    for (dx, dy), a0, a1, ln, w, turn, lat, tone, p0 in HEAD_LEAVES:
        back = 1.0 if a1 > 180 else 0.0
        da = math.degrees(a) + 12.0 * gust * back
        base = rot(HEAD_C[0] + dx, HEAD_C[1] + dy)
        c, wd = leaf_curve(base, a0 + da, a1 + da * 0.3 + 14.0 * gust * back, ln, w, turn, ph + p0, sway=4.0)
        out.append((c, wd, lat, tone))
    return out, rot, a


# 身上冒出来的小枝竹叶：(挂在哪, 沿那根竹的比例, 角度, [(叶角, 长, 宽, 下垂)])
SPRIGS = [("back", 0.98, 120, [(105, 7.5, 1.7, 0.3), (140, 8.0, 1.8, 0.45), (170, 6.5, 1.5, 0.5)]),
          ("main", 0.02, 200, [(205, 6.5, 1.5, 0.45), (235, 5.5, 1.3, 0.4)])]


# ---------------------------------------------------------------- 组装
def build_bamboo_wraith():
    root = B.empty("BWRoot")
    body = B.empty("BWBody", root)
    common = dict(wash=0.28, wash_scale=2.8, shade_attr="nodeshade", shade_gain=1.0, streak=0.16,
                  streak_scale=(26.0, 1.5), value_var=0.05, edge=0.28)
    m_bam = V2.paint_material("BWBamboo", BAMBOO_STOPS, seed=21.0, rim_hex=RIM, rim=0.55, rim_power=2.3, bias=0.02,
                              **common)
    m_far = V2.paint_material("BWBambooFar", BAMBOO_STOPS, seed=22.0, rim_hex=RIM, rim=0.3, bias=-0.26, **common)
    m_node = V2.paint_material("BWNode", NODE_STOPS, wash=0.2, seed=23.0, edge=0.0, rim_hex=RIM, rim=0.25)
    m_spike = V2.paint_material("BWSpike", SPIKE_STOPS, wash=0.2, seed=24.0, edge=0.2, streak=0.2,
                                streak_scale=(20.0, 1.5), shade_attr="nodeshade")
    m_leaf = V2.brush_material("BWLeaf", LEAF_DARK, edge_soft=0.22, edge_dark=0.3, streak=0.35, streak_from=0.45,
                               scale=(5.0, 10.0), fade_from=0.92, seed=25.0)
    m_leaf2 = V2.brush_material("BWLeafMid", LEAF_MID, edge_soft=0.22, edge_dark=0.25, streak=0.3, streak_from=0.5,
                                scale=(5.0, 10.0), fade_from=0.92, seed=26.0)
    m_leaf3 = V2.brush_material("BWLeafLight", LEAF_LIGHT, edge_soft=0.22, edge_dark=0.25, streak=0.3, streak_from=0.5,
                                scale=(5.0, 10.0), fade_from=0.92, seed=28.0)
    m_glow = B.emissive_material("BWGlow", GLOW, 1.0)
    m_core = V2.paint_material("BWHollow", [(0.0, I["jiao"]), (0.7, I["jiao"]), (1.0, "#1D2A21")], wash=0.15,
                               seed=27.0, edge=0.0)
    m_eye = B.emissive_material("BWEye", EYE, 1.0)
    m_hot = B.emissive_material("BWEyeHot", EYE_HOT, 1.0)
    m_dim = B.emissive_material("BWEyeDim", EYE_DIM, 1.0)
    parts = {"root": root, "body": body, "dyn": {}}

    def dyn(name, mat, line="outer"):
        ob = V2.mesh_from_arrays(name, [(0, 0, 0), (0.001, 0, 0), (0, 0.001, 0)], [(0, 1, 2)], mat, line, body)
        parts["dyn"][name] = ob
        return ob

    for nm, mat, line in (("Near", m_bam, "outer"), ("Far", m_far, "outer"), ("Torso", m_bam, "outer"),
                          ("Nodes", m_node, "inner"), ("NodesFar", m_node, "inner"), ("Twigs", m_bam, "thin"),
                          ("TwigsFar", m_far, "thin"), ("Glow", m_glow, "none"), ("Spike", m_spike, "inner"),
                          ("Leaves", m_leaf, "none"), ("LeavesMid", m_leaf2, "none"), ("LeavesLight", m_leaf3, "none")):
        dyn(nm, mat, line)
    # 头：焦墨的空 + 两点眼（每帧挪到颈端）
    head = B.empty("BWHead", body)
    core = B.mesh_object("BWHollow", K.ellipsoid((HOLLOW_R[0] / 25.0 * 0.8, HOLLOW_R[0] / 25.0, HOLLOW_R[1] / VZ)),
                         m_core, "none", head)
    eyes = []
    for k, ((ex, ey), hl, hh, tilt, lat) in enumerate(EYES):
        for nm, mats, sc, dl in (("Eye", (m_eye, m_dim), 1.0, 0.0), ("Hot", (m_hot, m_dim), 0.45, -0.004)):
            ob = B.mesh_object(f"BW{nm}{k}", K.ellipsoid((0.01, hl * sc / 25.0, hh * sc / VZ), 12, 8), mats[0], "none",
                               body)
            ob["mats"] = [mats[0].name, mats[1].name]
            eyes.append((ob, (ex, ey), tilt, lat + dl))
    sock_e = B.empty("BWSocketEyes", body)
    muzzle = B.empty("BWSocketMuzzle", body)
    parts.update(head=head, core=core, eyes=eyes, sock_e=sock_e, muzzle=muzzle)
    parts["sockets"] = {"eyes": sock_e, "muzzle": muzzle}
    pose_bamboo_wraith(parts, "idle", 0, 4)
    return root, parts, parts["sockets"]


def pose_bamboo_wraith(parts, anim, frame, n):
    p = pose_params(anim, frame, n)
    sk = skeleton(p)
    D = parts["dyn"]
    gap = 0.9 * p["crack"]
    groups = {k: [] for k in ("Near", "Far", "Torso", "Nodes", "NodesFar", "Twigs", "TwigsFar", "Glow", "Leaves",
                              "LeavesMid", "LeavesLight")}

    def add_culm(key, nodes_key, path, lat, r, nodes, g=0.0, taper=0.12, end_nodes=(False, True)):
        b, rg, gl = culm(path, lat, r, nodes, g, taper, end_nodes)
        groups[key] += b
        groups[nodes_key] += rg
        groups["Glow"] += gl
    # 腿：大腿、小腿各一截（膝是竹节），脚是削尖的竹桩
    for far in (False, True):
        lat = LAT_LEG if far else -LAT_LEG
        key, nk = ("Far", "NodesFar") if far else ("Near", "Nodes")
        hip_, knee, ank, toe = [np.asarray(q) for q in sk["legs"][far]]
        add_culm(key, nk, [hip_, knee, ank], lat, R_THIGH, [THIGH / (THIGH + SHIN)], gap * 0.6, taper=0.2,
                 end_nodes=(False, True))
        groups[key].append(_tube([ank, ank + (toe - ank) * 0.5, toe], lat, lambda t: R_SHIN * 0.95 * (1 - t) ** 0.9 + 0.02,
                                 nu=12, nv=8))
    # 身子：一粗一细两根竹（胯 → 腰 → 肩），细的在后面、矮一截
    hip, waist, sh = (np.asarray(sk[k]) for k in ("hip", "waist", "shoulder"))
    neck = np.asarray(sk["neck"])
    d = sh - hip
    nrm = np.array([-d[1], d[0]]) / (np.linalg.norm(d) + 1e-9)
    add_culm("Torso", "Nodes", [hip - d * 0.06, waist, sh, sh + (neck - sh) * 0.35], -0.02, R_MAIN, [0.3, 0.62, 0.88],
             gap, taper=0.16, end_nodes=(True, True))
    back = [hip + nrm * 2.0 - d * 0.02, waist + nrm * 2.4, sh + nrm * 1.9 - d * 0.1]
    add_culm("Torso", "Nodes", back, 0.06, R_BACK, [0.38, 0.78], gap * 0.8, taper=0.1, end_nodes=(True, True))
    # 颈：一截细竹伸进头里
    add_culm("Torso", "Nodes", [sh + (neck - sh) * 0.2, neck + (neck - sh) * 0.6], -0.01, 1.05, [0.45], 0.0, taper=0.05,
             end_nodes=(False, False))
    # 臂：上臂、前臂（肘、腕是竹节），手是三根细竹枝，枝梢挂竹叶
    for far in (False, True):
        lat = LAT_ARM if far else -LAT_ARM
        key, nk = ("Far", "NodesFar") if far else ("Near", "Nodes")
        tk, lk = ("TwigsFar", "LeavesMid") if far else ("Twigs", "Leaves")
        shd, elb, wri, tip = [np.asarray(q) for q in sk["arms"][far]]
        add_culm(key, nk, [shd, elb, wri], lat, R_UPPER, [UPPER / (UPPER + FORE)], gap * 0.6, taper=0.22,
                 end_nodes=(True, True))
        hand_dir = math.degrees(math.atan2(tip[1] - wri[1], tip[0] - wri[0]))
        for j, (da, ln) in enumerate(((-26.0, 7.0), (0.0, 8.2), (24.0, 6.6))):
            arr, tp, ta = twig(wri, hand_dir + da, ln, lat - 0.004 * (j - 1), r0=0.46, bend=-10.0 + 8.0 * (j - 1),
                               ph=p["ph"] + j)
            groups[tk].append(arr)
            for q, (la, ll, lw) in enumerate(((ta - 22.0, 5.6, 1.4), (ta + 20.0, 4.6, 1.2))):
                groups[lk].append(leaf(tp, la, la - 35.0 * math.copysign(1, math.cos(math.radians(la)) + 1e-6), ll, lw,
                                       lat - 0.01, turn=0.9, ph=p["ph"] + j + q, sway=6.0,
                                       ref_lat=lat - 0.004 * (j - 1)))
    # 头：一蓬竹叶 + 焦墨的空 + 两点眼
    lay, rot, a = head_layout(tuple(neck), sk["head_ang"], p["ph"], p["gust"])
    for c, w, lat, tone in lay:
        c = np.asarray(c) - np.array([0.0, LAT_RISE * lat])
        groups[{"dark": "Leaves", "mid": "LeavesMid", "light": "LeavesLight"}[tone]].append(
            V2.strip_arrays(*V2.design_strip(c, w, lat)))
    parts["head"].location = d2m(*rot(*HOLLOW_C), 0.0)
    for ob, (ex, ey), tilt, lat in parts["eyes"]:
        q = rot(ex, ey)
        ob.location = d2m(q[0], q[1] - LAT_RISE * lat, lat)
        ob.rotation_euler = (math.radians(tilt) + a, 0, 0)
        ob.active_material = bpy.data.materials[ob["mats"][0 if p["eye"] > 0.5 else 1]]
    (e0x, e0y), (e1x, e1y) = EYES[0][0], EYES[1][0]
    q = rot(e0x * 0.65 + e1x * 0.35, e0y * 0.65 + e1y * 0.35)
    parts["sock_e"].location = d2m(q[0], q[1] + LAT_RISE * 0.18, -0.18)
    # 身上冒出来的小枝竹叶
    for where, t, ang, lvs in SPRIGS:
        path = back if where == "back" else [hip - d * 0.06, waist]
        P = np.asarray(path)
        seg = np.linalg.norm(np.diff(P, axis=0), axis=1)
        s = np.concatenate([[0], np.cumsum(seg)])
        u = t * s[-1]
        base = (float(np.interp(u, s, P[:, 0])), float(np.interp(u, s, P[:, 1])))
        arr, tp, ta = twig(base, ang + p["lean"] * 0.5, 3.0, 0.08, r0=0.3, bend=8.0, ph=p["ph"])
        groups["Twigs"].append(arr)
        for k, (la, ll, lw, dr) in enumerate(lvs):
            a0 = la + 10.0 * p["gust"]
            groups["Leaves" if k % 2 == 0 else "LeavesMid"].append(
                leaf(tp, a0, a0 + dr * 90.0, ll, lw, 0.09 + 0.01 * k, turn=0.8, ph=p["ph"] + k * 1.3, sway=6.0,
                     ref_lat=0.08))
    # 竹刺：搭在远手上、尾巴捏在近手里，尖朝前（对着要射的方向），和射出去的竹刺一样长（32 单位）
    nw = np.asarray(sk["arms"][False][2])
    fw = np.asarray(sk["arms"][True][2])
    if p["spike"]:
        aim = (fw - nw) / (np.linalg.norm(fw - nw) + 1e-9)
        a0 = nw - aim * 2.0
        a1 = nw + aim * 30.0
        pts = [a0 + (a1 - a0) * t for t in np.linspace(0, 1, 12)]
        V_, F_, A_ = _tube(pts, -LAT_ARM - 0.03, lambda t: 1.1 * (1.0 if t < 0.74 else max(0.03, (1 - t) / 0.26) ** 0.85),
                           nu=12, nv=24)
        A_["nodeshade"] = [-0.7 * math.exp(-((t - 0.36) / 0.02) ** 2) + 0.55 * max(0.0, (t - 0.76) / 0.24)
                           for t in A_["su"]]
        _set(D["Spike"], V_, F_, A_)
        D["Spike"].hide_render = False
        # 竹刺尾上一片竹叶（和射出去的竹刺一样）
        lb = a0 + aim * 7.0
        ang = math.degrees(math.atan2(aim[1], aim[0]))
        groups["LeavesMid"].append(leaf(tuple(lb), ang + 150.0, ang + 175.0, 6.0, 1.5, -LAT_ARM - 0.04, turn=0.8,
                                        ph=p["ph"], sway=3.0, ref_lat=-LAT_ARM - 0.03))
        parts["muzzle"].location = d2m(*a1, -LAT_ARM - 0.03)
    else:
        D["Spike"].hide_render = True
        shd, elb, wri, tip = [np.asarray(q) for q in sk["arms"][True if anim == "shoot" and frame == 2 else False]]
        reach = (tip - wri) / (np.linalg.norm(tip - wri) + 1e-9)
        lat_m = LAT_ARM if anim == "shoot" and frame == 2 else -LAT_ARM
        parts["muzzle"].location = d2m(*(wri + reach * 6.0), lat_m)
    for k, arrs in groups.items():
        if arrs:
            _set(D[k], *_merge(arrs), smooth=not k.startswith("Leaves"))
            D[k].hide_render = False
        else:
            D[k].hide_render = True
    bpy.context.view_layer.update()


def _set(ob, V, F, A, smooth=True):
    K.replace_mesh(ob, V2.arrays_build(V, F), smooth=smooth, attrs=A)
