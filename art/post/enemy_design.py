"""妖物重做的设计稿（纯数据 + numpy，不依赖 bpy）：三维模型（models/*_v2.py）按这里的二维稿定比例、
把眼、裂缝、脸上的朱砂这些“画上去的”部件投到表面上；骨架姿态也写在这里（一套姿态，模型照着摆）。

坐标：世界单位，x 右、y 上，原点是锚点（下摆墨烟的落地点 / 脚底），朝东。
影妖：轮廓、兜帽口、眼、裂缝。赤面狐：见 FOX_*。
"""

from __future__ import annotations

import math

import numpy as np

# 设计稿整体略前倾（追着光）：x 加 LEAN·(y-5)，下摆尖不动、头往前
LEAN = 0.06


def lean(pts):
    return [(x + LEAN * (y - 5.0), y) for x, y in pts]


# 轮廓（单位，y 上；朝东）：上宽下窄的倒泪滴；兜帽在顶上，帽尖往后挑；最宽在 y≈32，下半身收细、略往后，
# 尖在 y≈5 化进烟里
SH_OUTLINE = lean([(0.0, 45.0), (5.0, 44.1), (9.0, 41.6), (11.4, 38.2), (12.4, 34.8), (11.6, 31.8), (10.8, 28.0),
                   (9.6, 23.0), (7.8, 18.0), (5.2, 13.2), (2.6, 9.2), (0.4, 6.4), (-1.8, 4.6), (-3.8, 5.4),
                   (-5.6, 8.4), (-8.0, 13.0), (-11.0, 18.8), (-13.2, 24.8), (-14.4, 30.6), (-14.6, 35.4),
                   (-14.2, 39.6), (-15.6, 41.8), (-18.4, 43.3), (-14.6, 44.8), (-9.6, 45.7), (-4.0, 45.7)])
SH_HOLLOW = (lean([(7.2, 33.8)])[0], 4.9, 4.4, -10.0)  # 兜帽里的黑：中心、半径、转角
SH_EYES = [(lean([(5.2, 33.4)])[0], 2.0, 1.15, 17.0), (lean([(9.7, 33.7)])[0], 1.55, 0.95, -21.0)]  # 近眼、远眼
SH_PIVOT = (0.0, 6.0)  # 弯腰、压扁的底
def curve_pts(ctrl, n=80, closed=False):
    """过控制点的平滑曲线（Catmull-Rom），按弧长重采样成 n 个点。"""
    c = np.asarray(ctrl, np.float64)
    if closed:
        m = len(c)
        seg = [(c[(i - 1) % m], c[i], c[(i + 1) % m], c[(i + 2) % m]) for i in range(m)]
    else:
        c = np.vstack([2 * c[0] - c[1], c, 2 * c[-1] - c[-2]])
        seg = [(c[i - 1], c[i], c[i + 1], c[i + 2]) for i in range(1, len(c) - 2)]
    t = np.linspace(0, 1, 24, endpoint=False)[:, None]
    out = [0.5 * ((2 * p1) + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t ** 2
                  + (-p0 + 3 * p1 - 3 * p2 + p3) * t ** 3) for p0, p1, p2, p3 in seg]
    out = np.vstack(out + ([c[0][None]] if closed else [c[-2][None]]))
    seg_l = np.hypot(*np.diff(out, axis=0).T)
    s = np.concatenate([[0.0], np.cumsum(seg_l)])
    u = np.linspace(0.0, s[-1], n)
    return np.stack([np.interp(u, s, out[:, 0]), np.interp(u, s, out[:, 1])], -1)


def _crack(rng, p0, p1, n=7, amp=0.55):
    """一道裂缝的折线：p0 → p1，节点间距不匀，横向随机错开（瓷器开片那样，不是闪电那样整齐的锯齿）。"""
    p0, p1 = np.asarray(p0, float), np.asarray(p1, float)
    d = p1 - p0
    nrm = np.array([-d[1], d[0]]) / (np.linalg.norm(d) + 1e-9)
    ts = np.sort(np.concatenate([[0, 1], rng.uniform(0.08, 0.92, n - 2)]))
    off = rng.normal(0, amp, n) * np.sin(np.pi * ts) ** 0.5
    return [tuple(p0 + d * t + nrm * o) for t, o in zip(ts, off)]



def shade_cracks(seed=11):
    """影妖的三道裂缝（折线, 半宽）：一道像泪痕，从近眼下往下流；肚子上一道带分叉。"""
    rng = np.random.default_rng(seed + 5)
    ex0, ey0 = SH_EYES[0][0]
    cracks = [(_crack(rng, (ex0 + 0.2, ey0 - 1.6), (ex0 - 0.7, ey0 - 11.5), 6, 0.30), 0.26),
              (_crack(rng, lean([(7.6, 21.4)])[0], lean([(4.8, 13.6)])[0], 5, 0.38), 0.30)]
    mid = cracks[1][0][2]
    cracks.append((_crack(rng, mid, (mid[0] - 3.0, mid[1] + 1.1), 3, 0.25), 0.18))
    return cracks


def shade_eye_poly(i, scale=1.0):
    """第 i 只眼（0 近、1 远）的轮廓：上沿平、往外斜下（垂眼，哀伤），下沿是弧。scale 缩放（眼心用 0.45）。"""
    (ex, ey), hl, hh, tilt = SH_EYES[i]
    a = math.radians(tilt)
    poly = [(-hl, hh * 0.35), (-hl * 0.3, hh * 0.55), (hl * 0.5, hh * 0.45), (hl, hh * 0.2), (hl * 0.75, -hh * 0.35),
            (hl * 0.1, -hh * 0.62), (-hl * 0.6, -hh * 0.45), (-hl * 0.95, -hh * 0.05)]
    return [(ex + scale * (x * math.cos(a) - y * math.sin(a)), ey + scale * (x * math.sin(a) + y * math.cos(a)))
            for x, y in poly]


# ================================================================ 赤面狐（精英，四足）
# 比普通狐狸大一圈，精瘦收腰，大尾巴翘起、尾尖墨色；淡赭到米白；脸上一抹朱砂（额头 → 鼻梁 → 两颊，像戏台上的红脸），
# 颈上一根红绳。凶但有正气，像守门的武将：头抬着、胸挺着。帧 320²、锚点 (0.5, 0.8)：走路时前沿（鼻尖）约 22 单位。
FOX_PIVOT = (-1.0, 18.0)  # 身体（躯干）的转轴
FOX_SHOULDER = (8.0, 17.4)  # 前腿根
FOX_HIP = (-9.2, 17.8)  # 后腿根
FOX_NECK = (12.4, 25.4)  # 头的转轴（颈根）
FOX_TAIL_ROOT = (-13.4, 21.4)
# 腿：(段长, 静止时的角度)，角度从正下方量起，正值往前（+x）摆
FOX_FRONT_LEG = [(6.0, -10.0), (7.8, 5.0), (3.0, 28.0)]  # 上臂、前臂、前掌
FOX_HIND_LEG = [(7.0, 24.0), (7.6, -38.0), (4.6, 6.0)]  # 大腿、小腿、后掌（跗骨）
FOX_FAR = (1.3, 1.4)  # 远侧的腿相对近侧往后上方挪一点（离镜头远）
# 躯干轮廓（含颈；颈上半截被头盖住）
FOX_TORSO = [(7.4, 24.4), (3.0, 23.2), (-2.4, 22.4), (-7.0, 22.8), (-10.6, 22.6), (-13.4, 21.2), (-15.0, 18.6),
             (-14.8, 15.6), (-13.2, 13.2), (-10.4, 12.2), (-7.8, 12.8), (-5.4, 14.2), (-1.8, 15.0), (2.4, 14.4),
             (6.0, 12.6), (9.0, 11.8), (11.6, 12.8), (13.2, 15.4), (13.8, 18.6), (13.6, 21.4), (14.6, 24.0),
             (15.0, 27.2), (12.6, 29.0), (10.0, 27.4)]
# 头部放大（风格化：游戏尺寸下先读出红脸狐狸）：绕吻中部放大 FOX_HEAD_S 倍，鼻尖仍在约 23 单位
FOX_HEAD_S = 1.3
FOX_HEAD_C = (21.0, 28.4)


def _hx(pts):
    cx, cy = FOX_HEAD_C
    return [(cx + (x - cx) * FOX_HEAD_S, cy + (y - cy) * FOX_HEAD_S) for x, y in pts]


# 头（不含耳）：额、后脑、颈背、颊毛、下颌、下巴、吻、鼻尖、吻背、两眼之间
FOX_HEAD = _hx([(14.4, 34.6), (12.2, 34.0), (10.8, 31.8), (10.6, 28.6), (11.2, 26.4), (12.6, 24.8), (14.8, 24.6),
                (17.4, 25.4), (19.8, 26.4), (21.8, 27.2), (22.8, 28.2), (22.4, 29.0), (20.4, 29.8), (18.0, 31.6),
                (16.2, 33.8)])
FOX_EAR_NEAR = _hx([(12.2, 33.6), (11.8, 40.6), (15.2, 34.6)])  # 耳根后、耳尖、耳根前
FOX_EAR_FAR = _hx([(15.4, 34.2), (17.4, 39.8), (17.6, 33.4)])
FOX_EYE = (_hx([(17.4, 30.6)])[0], 1.75 * FOX_HEAD_S, 0.62 * FOX_HEAD_S, 24.0)  # 近眼：丹凤眼，外眼角往上挑
FOX_EYE_FAR = (_hx([(20.1, 30.6)])[0], 0.55 * FOX_HEAD_S, 0.40 * FOX_HEAD_S, 18.0)
FOX_NOSE = _hx([(22.5, 28.2)])[0]
# 朱砂红脸：额头抹过鼻梁一笔（额上宽），两颊一笔（从鼻梁下往后扫到颊毛）
FOX_MASK_BRIDGE = _hx([(14.2, 35.0), (16.0, 33.6), (18.4, 31.4), (20.8, 29.8)])
FOX_MASK_CHEEK = _hx([(20.6, 29.0), (18.8, 29.3), (16.8, 29.1), (14.6, 28.2), (12.8, 27.0)])
FOX_BROW = _hx([(19.0, 31.6), (17.6, 32.4), (16.2, 33.1), (14.8, 34.1)])  # 戏台上的浓眉，往后上挑
FOX_HEAD_PTS = {"cheek_low": _hx([(23.0, 27.9), (20.4, 28.4), (17.4, 28.6), (14.6, 28.0), (12.0, 27.2), (10.8, 25.4),
                                  (12.8, 24.0), (15.0, 24.0), (17.6, 24.8), (20.0, 25.9), (22.2, 26.8)]),
                "crown": _hx([(10.8, 29.6), (11.6, 32.6), (13.6, 34.4), (16.0, 33.8), (18.6, 31.4), (21.2, 29.6)]),
                "ruff": _hx([(14.6, 24.4), (12.4, 24.8), (11.0, 26.4), (10.6, 28.4)]),
                "ruff_close": _hx([(13.0, 27.4), (15.2, 26.0)]),
                "far_cheek": _hx([(20.9, 29.3), (21.8, 28.7)]),
                "mouth": _hx([(22.0, 27.5), (20.6, 26.8), (19.0, 26.5), (17.8, 26.9)]),
                "fang": _hx([(20.3, 26.75), (20.65, 25.85), (20.95, 26.7)]),
                "line_top": _hx([(18.2, 31.6), (16.2, 33.9), (13.8, 34.7), (11.6, 33.6), (10.6, 31.0), (10.6, 28.4)]),
                "line_snout": _hx([(18.0, 31.5), (20.4, 29.9), (22.4, 29.0), (22.9, 28.2)]),
                "line_jaw": _hx([(22.6, 27.6), (21.4, 26.9), (19.6, 26.1), (17.2, 25.1), (15.0, 24.5)]),
                "whisker_root": _hx([(21.0, 27.6)])[0]}
FOX_CORD = [(11.0, 25.2), (12.0, 23.8), (13.4, 22.8), (14.6, 22.6)]  # 颈上的红绳（近侧一段），绳结在喉下
FOX_CORD_KNOT = (14.4, 22.4)
# 尾：摆直时长 FOX_TAIL_LEN，半宽按 FOX_TAIL_W（t: 0 根 → 1 尖）；尾尖墨色从 FOX_TAIL_INK 起
FOX_TAIL_LEN = 31.0
FOX_TAIL_W = [(0.0, 2.6), (0.12, 3.8), (0.42, 6.3), (0.70, 5.6), (0.88, 3.6), (1.0, 0.4)]
FOX_TAIL_INK = 0.80
FOX_TAIL_ANGLE = 166.0  # 尾根的方向（度，从 +x 逆时针量）：先往后平扫
FOX_TAIL_CURL = -6.4  # 每一节往上弯的角度（度）：往后扫出去再往上扬，尾尖朝上


def fox_leg(root, segs, angles=None):
    """腿的关节点：root 起，每段按角度（从正下方量，正值往前）往下接。返回 [根, 膝/肘, 腕/跗, 掌尖]。"""
    pts = [np.asarray(root, np.float64)]
    for (ln, a0), a in zip(segs, angles if angles is not None else [s[1] for s in segs]):
        r = math.radians(a)
        pts.append(pts[-1] + ln * np.array([math.sin(r), -math.cos(r)]))
    return pts


def fox_tail_curve(root, angle=FOX_TAIL_ANGLE, curl=FOX_TAIL_CURL, n=14, wave=0.0, ph=0.0, length=FOX_TAIL_LEN):
    """尾巴中线（n+1 个点）：从 root 按 angle 出发，每节转 curl 度，再加一道往尾传的波（wave 度，相位 ph）。"""
    pts = [np.asarray(root, np.float64)]
    a = angle
    step = length / n
    for i in range(n):
        t = i / (n - 1)
        a_i = a + wave * math.sin(ph - 2.2 * t) * (0.3 + 0.7 * t)
        r = math.radians(a_i)
        pts.append(pts[-1] + step * np.array([math.cos(r), math.sin(r)]))
        a += curl
    return np.array(pts)


# ---------------------------------------------------------------- 赤面狐的骨架姿态（每帧一套关节角度）
def fox_move_pose(i, n):
    """小跑（对角步）：近前 + 远后同相，远前 + 近后反相；身子一步一起伏，头稳、略反着点，尾巴带着波。"""
    ph = 2 * math.pi * i / n
    legs = {}
    for (name, far), off in ((("front", False), 0.0), (("hind", True), 0.0), (("front", True), math.pi),
                             (("hind", False), math.pi)):
        p = ph + off
        sw = math.sin(p)  # >0 往前摆
        lift = max(0.0, math.cos(p)) ** 1.4  # 往前摆的那半程抬脚
        rest = [sg[1] for sg in (FOX_FRONT_LEG if name == "front" else FOX_HIND_LEG)]
        if name == "front":
            a0 = rest[0] + 16 * sw
            a1 = rest[1] + 14 * sw - 12 * lift
            a2 = rest[2] + 10 * sw - 70 * lift
        else:
            a0 = rest[0] - 13 * sw + 10 * lift
            a1 = rest[1] - 10 * sw - 12 * lift
            a2 = rest[2] + 8 * sw - 48 * lift
        legs[(name, far)] = [a0, a1, a2]
    bob = 0.55 * math.cos(2 * ph)
    return {"body": (0.0, bob, 0.8 * math.sin(2 * ph), 1.0, 1.0),
            "head": (-1.2 * math.sin(2 * ph + 0.6), 0.0, -0.25 * math.cos(2 * ph)),
            "ears": 0.0,
            "legs": legs,
            "tail": (FOX_TAIL_ANGLE, FOX_TAIL_CURL, 5.0, ph, False)}


def fox_pounce_pose(i):
    """扑击 6 帧：0–1 伏低蓄力（1 最低，预警期间停在这一帧），2 蹬地，3 腾空最高、身子拉长，4 下落，5 落地前爪按地。
    2 起尾毛炸开。"""
    F = [  # body(dx, dy, rot, sx, sy), head(rot, dx, dy), ears, front[3], hind[3], tail(angle, curl, wave)
        ((-0.8, -3.4, -7, 1.04, 0.95), (-9, 1.0, -1.4), 28, [-34, 52, -16], [58, -88, 36], (158, -4.5, 2.0)),
        ((-1.8, -6.0, -11, 1.07, 0.90), (-14, 1.8, -2.4), 44, [-48, 72, -28], [74, -110, 52], (164, -4.0, 1.5)),
        ((2.2, 3.4, 16, 1.09, 0.95), (-12, 0.4, 0.2), 30, [56, 62, 56], [-20, -28, -48], (160, -6.2, 3.0)),
        ((3.4, 7.2, 4, 1.12, 0.93), (-6, 0.6, 0.0), 24, [68, 72, 66], [-46, -22, -60], (162, -6.2, 3.0)),
        ((3.8, 4.2, -10, 1.06, 0.96), (2, 0.4, -0.2), 16, [42, 30, 30], [-18, -40, -30], (160, -6.0, 3.0)),
        ((2.4, 0.4, -7, 0.95, 1.04), (4, 0.4, -0.4), 8, [22, 6, 40], [36, -56, 4], (150, -6.4, 4.0)),
    ]
    (body, head, ears, fl, hl, (ta, tc, tw)) = F[i]
    legs = {("front", False): fl, ("front", True): [fl[0] - 8, fl[1] + 4, fl[2] - 6],
            ("hind", False): hl, ("hind", True): [hl[0] + 6, hl[1] - 4, hl[2] + 4]}
    return {"body": body, "head": head, "ears": ears, "legs": legs,
            "tail": (ta, tc, tw, 2 * math.pi * i / 6, i >= 2)}
