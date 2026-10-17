"""狐火（精修三维）：一团青绿冷火，拖成一条狐尾。

设定：青丘的小妖，“像灯，又不是灯”（LORE 第 5 节）。造型：前面是一团圆圆的冷火（火芯近白、往外青绿、边上深青），
两簇火舌往后上方窜成一对尖耳，一双细长、往后上挑的狐眼（白热，嵌在深青的眼窝里）；火往后拖成一条蓬松的狐尾——
根细、中段最蓬，往后再往上翘起来（火往上走，像狐狸竖起的尾巴），尾梢往前卷、收尖，一点白（狐狸尾尖的白，
也是最烫的火）；尾巴外沿一簇簇火舌往后上方窜，里沿收得干净。颜色：深青 → 青 → 青绿 → 近白（冷火），整团火都在发光层里（夜里是一盏青灯）。
做法：头是三维的球（绘画感材质，发光很强）；尾巴和火舌是在设计稿（E 向画面）上画的扁带，放在过锚点的竖直平面里，
材质是 v2kit.brush_material（沿长取色、两边深、飞白很少、尾梢渐淡）。只给头描一道细墨线。
动画：
  float  8 帧循环：火舌一跳一跳（长短、弯度跟着相位变）、尾巴的波往后传，头一胀一缩。
  pounce 4 帧不循环：0–1 蓄力（头往后缩、压扁，尾巴卷紧、往上收，火舌贴伏；1 最紧，预警期间停在这一帧），
         2–3 扑出（头往前拉长，尾巴拉直往后，火舌往后拖成长条）。
帧 224²（2 倍；原来 160²，第二批审图后放大），锚点 (0.5, 0.875)，悬浮（游戏会抬高 4 单位、上下起伏）。

    root, parts, sockets = build_fox_wisp()
    pose_fox_wisp(parts, "float", i, 8)
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
import enemy_design as DZ  # noqa: E402

I = S.INK
DEEP, TEAL, JADE, MINT, PALE, WHITE = "#25555E", "#3F8C88", "#58AFA6", "#8FD6C6", "#BDEEE2", "#F2FFFC"
EYE = WHITE  # meta.eye_color（旧版同色）
GLOW = "#8FE3C8"
VZ = V2.VZ
FIRE_STOPS = [(0.00, DEEP), (0.25, S.mix(DEEP, TEAL, 0.6)), (0.45, TEAL), (0.62, JADE), (0.78, MINT), (0.90, PALE),
              (1.00, WHITE)]  # 头：d 从暗到亮
TAIL_RAMP = [(0.0, PALE), (0.25, MINT), (0.55, JADE), (0.74, TEAL), (0.84, S.mix(TEAL, PALE, 0.6)), (0.9, PALE),
             (1.0, WHITE)]  # 尾梢一点白
LICK_RAMP = [(0.0, JADE), (0.5, TEAL), (1.0, S.mix(TEAL, DEEP, 0.6))]
CORE_RAMP = [(0.0, WHITE), (0.4, PALE), (0.8, MINT), (1.0, JADE)]

# ---------------------------------------------------------------- 设计稿（单位，锚点为原点，x 前、y 上）
# 第二批审图后改：头更大；尾巴从头后往后、再往上翘成一条立起来的狐尾（火往上走，尾梢往前卷），和横着拖的疾影分开
HEAD_C = (6.0, 16.0)
HEAD_R = 5.0
TAIL = [(2.6, 15.2), (-2.4, 14.0), (-7.4, 15.0), (-11.6, 18.4), (-13.4, 23.4), (-12.4, 28.6), (-9.0, 32.0), (-5.6, 33.0)]
TAIL_CURL = [(2.4, 15.4), (-1.8, 14.8), (-5.6, 16.6), (-8.4, 20.4), (-9.0, 25.0), (-7.4, 29.0), (-4.4, 31.0), (-1.8, 31.0)]
TAIL_STREAM = [(2.6, 15.2), (-3.0, 14.6), (-8.5, 14.8), (-13.5, 15.6), (-17.5, 17.0), (-20.5, 18.8), (-22.5, 20.4),
               (-23.5, 21.4)]  # 扑出时往后拖直
TAIL_W = [4.0, 7.0, 9.0, 9.6, 8.6, 6.6, 4.4, 1.4]  # 尾梢圆一点（尾尖那一点白要看得见）
LICKS = [  # 头后、头下的火舌：(根 x, 根 y, 长, 根宽, 往后倒的角度, 相位)；尾巴外沿的火舌是尾巴扁带自己的齿（_tail）
    (2.4, 19.0, 4.2, 2.4, 55, 1.0), (2.0, 12.2, 3.4, 2.0, 100, 5.0)]
LICK_T = [None, None]  # 火舌根跟着谁（尾巴中线的 0..1；None 跟着头）
# 尾巴后面再叠两条大火舌（S 形、收尖），让整团火的外形是“火”而不是一根月牙：(平时, 扑出时拖直, 宽, 相位)
TONGUES = [
    ([(2.4, 13.6), (-2.6, 11.6), (-7.6, 11.4), (-11.8, 13.0), (-14.4, 15.8)],
     [(2.4, 13.6), (-3.0, 12.6), (-8.6, 12.6), (-14.0, 13.4), (-19.0, 14.2)], [3.0, 4.4, 3.6, 2.0, 0.2], 0.7),  # 下面一条
    ([(2.0, 18.0), (-1.0, 21.2), (-2.4, 25.0), (-1.6, 28.4)],
     [(2.0, 18.0), (-3.0, 19.0), (-8.0, 19.6), (-12.6, 20.0)], [2.6, 3.0, 1.8, 0.2], 2.3),  # 头后往上窜的一条
]
EARS = [((3.6, 19.8), (1.8, 27.4), 2.8, 0.0), ((6.6, 20.6), (6.0, 26.0), 2.2, 1.3)]  # 耳：根、尖、根宽、相位
EYES = [((8.1, 17.2), 1.5, 0.16, 14.0), ((10.9, 16.8), 0.7, 0.12, 18.0)]  # 近眼、远眼：中心、半长、半高、斜度（后上挑）


def _pose_params(anim, i, n):
    """每帧的参数：头的伸缩 (前后, 上下)、头的位移、尾巴卷紧 curl / 拉直 stretch（0..1）、火舌长短、往后倒、波。"""
    if anim == "float":
        ph = 2 * math.pi * i / n
        return {"ph": ph, "head": (1.0 + 0.03 * math.sin(ph), 1.0 - 0.03 * math.sin(ph)), "hd": (0.0, 0.0),
                "curl": 0.0, "stretch": 0.0, "lick": 1.0 + 0.12 * math.sin(ph * 2), "lean": 0.0, "wave": 1.0}
    P = [  # head(sx, sy), hd(dx, dy), curl, stretch, lick, lean, wave
        ((0.92, 1.08), (-1.4, -0.4), 0.5, 0.0, 0.85, -10, 0.5),
        ((0.86, 1.12), (-2.4, -0.8), 1.0, 0.0, 0.7, -16, 0.3),
        ((1.18, 0.88), (2.6, 0.2), 0.0, 0.75, 1.25, 30, 0.6),
        ((1.24, 0.84), (3.6, 0.3), 0.0, 1.0, 1.4, 40, 0.8),
    ]
    (hs, hd, curl, stretch, lick, lean, wave) = P[i]
    return {"ph": 2 * math.pi * i / n, "head": hs, "hd": hd, "curl": curl, "stretch": stretch, "lick": lick,
            "lean": lean, "wave": wave}


def _tail_ctrl(p):
    base = np.asarray(TAIL, np.float64)
    if p["curl"]:
        base = base * (1 - p["curl"]) + np.asarray(TAIL_CURL) * p["curl"]
    if p["stretch"]:
        base = base * (1 - p["stretch"]) + np.asarray(TAIL_STREAM) * p["stretch"]
    t = np.linspace(0, 1, len(base))[:, None]
    return base + np.asarray(p["hd"]) * (1 - t) ** 1.5  # 尾根跟着头走


def _tail_line(p):
    c = DZ.curve_pts(_tail_ctrl(p), 44)
    return V2.wave_line(c, 0.9 * p["wave"], p["ph"], lock=3)


TAIL_C0 = (-5.5, 22.0)  # 尾巴弯的中心：离它远的一侧是外沿（火舌长在外沿）


def _tail(p, scale_w=1.0, off=(0.0, 0.0), lat=0.0, cut=0, flames=0.0):
    """尾巴扁带。flames > 0：外沿长出一排往后倒的火舌（齿形沿尾巴往后走，跟着相位窜），内沿不动。"""
    c = _tail_line(p) + np.array(off)
    n = len(c)
    t = np.linspace(0, 1, n)
    w = np.interp(t, np.linspace(0, 1, len(TAIL_W)), TAIL_W) * scale_w
    w = w * (1 + 0.06 * np.sin(p["ph"] * 2 + 7 * t))
    if flames:
        tan = np.gradient(c, axis=0)
        tan /= np.linalg.norm(tan, axis=1, keepdims=True) + 1e-9
        nrm = np.stack([-tan[:, 1], tan[:, 0]], -1)
        away = c - np.asarray(TAIL_C0) - np.asarray(p["hd"]) * 0.5
        sgn = np.sign((nrm * away).sum(1))[:, None]
        outer = nrm * np.where(sgn == 0, 1.0, sgn)
        u = (6.0 * t - p["ph"] / (2 * math.pi) * 2.0) % 1.0  # 齿：前缘陡、后缘缓（火舌往后倒）
        tooth = np.where(u < 0.75, (u / 0.75) ** 2.2, (1 - (u - 0.75) / 0.25) ** 0.7 * 1.0)
        amp = flames * np.sin(np.pi * np.clip(t * 1.1, 0, 1)) ** 0.8 * p["lick"]
        spike = tooth * amp
        c = c + outer * (spike / 2)[:, None]
        w = w + spike
    if cut:
        c, w = c[:-cut], w[:-cut]
    return V2.design_strip(c, w, lat)


def _tongue(k, p):
    calm, stream, ws, ph0 = TONGUES[k]
    base = np.asarray(calm, np.float64)
    if p["curl"]:  # 蓄力：往头那边收
        base = base + (np.asarray(HEAD_C) - base) * 0.22 * p["curl"]
    if p["stretch"]:
        base = base * (1 - p["stretch"]) + np.asarray(stream) * p["stretch"]
    t = np.linspace(0, 1, len(base))[:, None]
    base = base + np.asarray(p["hd"]) * (1 - t) ** 1.5
    c = V2.wave_line(DZ.curve_pts(base, 30), 0.8 * p["wave"], p["ph"] + ph0, lock=2)
    w = np.interp(np.linspace(0, 1, len(c)), np.linspace(0, 1, len(ws)), ws) * (1 + 0.1 * math.sin(p["ph"] * 2 + ph0))
    return V2.design_strip(c, w, 0.006)


def _lick_root(k, p):
    """第 k 簇火舌的根：尾巴上的跟着尾巴中线走（在中线外侧、略靠外沿），头上的跟着头。"""
    x, y = LICKS[k][:2]
    tt = LICK_T[k]
    if tt is None:
        return x + p["hd"][0], y + p["hd"][1]
    c = _tail_line(p)
    i = int(tt * (len(c) - 1))
    tan = c[min(i + 1, len(c) - 1)] - c[max(i - 1, 0)]
    tan /= np.linalg.norm(tan) + 1e-9
    nrm = np.array([-tan[1], tan[0]])  # 中线左侧（往后上方弯的时候是外沿）
    w = float(np.interp(tt, np.linspace(0, 1, len(TAIL_W)), TAIL_W))
    q = c[i] - nrm * w * 0.25
    return float(q[0]), float(q[1])


def _lick(spec, p, root=None):
    """一簇火舌：从根往上窜、越往尖越往后倒（中段带一点 S 形），长短跟着相位跳。"""
    x, y, ln, w, back, ph0 = spec
    if root is not None:
        x, y = root
    k = p["lick"] * (1.0 + 0.18 * math.sin(p["ph"] * 2 + ph0))
    ln = ln * k
    back = back + p["lean"] + 10 * math.sin(p["ph"] + ph0)
    pts = []
    cx, cy = x, y
    for t in np.linspace(0, 1, 14):
        a = math.radians(90 + back * (0.3 + 0.9 * t) + 14 * math.sin(math.pi * t * 1.6 + p["ph"] + ph0))
        pts.append((cx, cy))
        cx += math.cos(a) * ln / 13
        cy += math.sin(a) * ln / 13
    c = np.asarray(pts)
    ww = w * (1 - np.linspace(0, 1, len(c))) ** 1.1 + 0.05
    return V2.design_strip(c, ww, 0.004)


def _ear(spec, p):
    """耳：一簇往上窜的火舌（扑出时往后倒）。"""
    (bx, by), (tx, ty), w, ph0 = spec
    lean = p["lean"] * 0.06
    tx2 = tx - lean * 2.0 + 0.3 * math.sin(p["ph"] * 2 + ph0)
    ty2 = ty - abs(lean) * 0.8
    c = np.asarray([(bx + (tx2 - bx) * t + 0.6 * math.sin(math.pi * t), by + (ty2 - by) * t) for t in np.linspace(0, 1, 12)])
    ww = w * (1 - np.linspace(0, 1, len(c))) ** 0.7 + 0.05
    return V2.design_strip(c, ww, -0.002)


def build_fox_wisp():
    root = B.empty("FoxWispRoot")
    body = B.empty("FoxWispBody", root)
    head_piv = B.empty("FoxWispHeadPivot", body, loc=V2.d2m(*HEAD_C))
    m_head = V2.paint_material("FoxWispFire", FIRE_STOPS, wash=0.28, wash_scale=3.0, seed=4.0, value_var=0.05,
                               edge=0.75, edge_power=1.6, bias=0.30, rim_hex=PALE, rim=0.3)
    V2.add_glow_const(m_head, 0.75)
    _facing_shade(m_head)  # 火球：正对镜头的芯最亮、往边上暗（不按主光的方向）
    r = HEAD_R
    head = B.mesh_object("FoxWispHead", K.ellipsoid((r / 25.0, r * 1.05 / 25.0, r * 0.95 / VZ)), m_head, "none", head_piv)
    p0 = _pose_params("float", 0, 8)
    m_tail = V2.brush_material("FoxWispTail", TAIL_RAMP, alpha=0.97, streak=0.25, streak_from=0.5, scale=(2.0, 12.0),
                               fade_from=0.9, seed=5.0, glow=0.75, glow_to=1.0, glow_tip=0.5, edge_soft=0.14,
                               edge_dark=0.45)
    m_core = V2.brush_material("FoxWispCore", CORE_RAMP, alpha=0.9, streak=0.3, streak_from=0.3, scale=(2.0, 10.0),
                               fade_from=0.55, seed=6.0, glow=0.85, glow_to=1.0, glow_tip=0.4, edge_soft=0.5,
                               edge_dark=0.0)
    m_lick = V2.brush_material("FoxWispLick", LICK_RAMP, alpha=0.95, streak=0.2, streak_from=0.5, scale=(2.0, 6.0),
                               fade_from=0.7, seed=7.0, glow=0.6, glow_to=1.0, glow_tip=0.3, edge_soft=0.2,
                               edge_dark=0.3)
    tail = V2.flat_strip("FoxWispTail", *_tail(p0), m_tail, body)
    tongues = [V2.flat_strip(f"FoxWispTongue{k}", *_tongue(k, p0), m_lick, body) for k in range(len(TONGUES))]
    core = V2.flat_strip("FoxWispTailCore", *_tail(p0, 0.45, (0.4, 0.5), -0.003, cut=6), m_core, body)
    licks = [V2.flat_strip(f"FoxWispLick{k}", *_lick(sp, p0, _lick_root(k, p0)), m_lick, body)
             for k, sp in enumerate(LICKS)]
    ears = [V2.flat_strip(f"FoxWispEar{k}", *_ear(sp, p0), m_lick if k else m_core, body) for k, sp in enumerate(EARS)]
    # 眼：设计稿上的形状投到头上
    B.set_direction(root, "E")
    bpy.context.view_layer.update()
    tree = V2.bvh_world(head)
    m_socket = B.flat_material("FoxWispEyeSocket", DEEP)
    m_eye = B.emissive_material("FoxWispEye", WHITE, 1.0)
    for k, ((ex, ey), hl, hh, tilt) in enumerate(EYES):
        V2.design_patch(f"FoxWispSocket{k}", tree, _eye_poly(ex, ey, hl * 1.25, 0.62 if k == 0 else 0.4, tilt), m_socket,
                        head_piv,
                        lift=0.004, spacing=0.2)
        V2.design_patch(f"FoxWispEye{k}", tree, _eye_poly(ex, ey, hl, hh, tilt), m_eye, head_piv, lift=0.006, spacing=0.2)
    sock = B.empty("FoxWispSocketEyes", head_piv)
    hits = V2.project_design(tree, [(EYES[0][0][0] * 0.65 + EYES[1][0][0] * 0.35,
                                     EYES[0][0][1] * 0.65 + EYES[1][0][1] * 0.35)])
    if hits[0][0] is not None:
        sock.location = head_piv.matrix_world.inverted() @ hits[0][0]
    B.set_direction(root, "S")
    parts = {"root": root, "body": body, "head_piv": head_piv, "tail": tail, "core": core, "licks": licks,
             "tongues": tongues,
             "ears": ears, "sockets": {"eyes": sock}}
    bpy.context.view_layer.update()
    return root, parts, parts["sockets"]


def _facing_shade(m):
    """把 paint_material 的明暗（N·主光）换成 N·视线：球心最亮、往轮廓暗。"""
    _, _, fwd = B.camera_basis()
    for n in m.node_tree.nodes:
        if n.type == "VECT_MATH" and n.operation == "DOT_PRODUCT":
            n.inputs[1].default_value = -fwd
            break
    return m


def _eye_poly(ex, ey, hl, hh, tilt):
    """狐眼：细长，前头圆、后头尖、往后上挑（tilt 为正 = 后头高）。"""
    a = math.radians(180 - tilt)  # 后头朝 -x
    pts = [(hl, 0.0), (hl * 0.3, hh * 0.9), (-hl * 0.55, hh * 0.85), (-hl, 0.05 * hh), (-hl * 0.5, -hh * 0.7),
           (hl * 0.35, -hh * 0.75)]
    return V2.closed_smooth([(ex + x * math.cos(a) - y * math.sin(a), ey + x * math.sin(a) + y * math.cos(a))
                             for x, y in pts], 30)


def pose_fox_wisp(parts, anim, frame, n):
    p = _pose_params(anim, frame, n)
    hp = parts["head_piv"]
    hp.location = V2.d2m(HEAD_C[0] + p["hd"][0], HEAD_C[1] + p["hd"][1])
    hp.scale = (1.0, p["head"][0], p["head"][1])
    for ob, args in ([(parts["tail"], _tail(p)), (parts["core"], _tail(p, 0.45, (0.4, 0.5), -0.003, cut=6))]
                     + [(ob_, _tongue(k, p)) for k, ob_ in enumerate(parts["tongues"])]):
        V_, F_, A_s = V2.strip_arrays(*args)
        K.replace_mesh(ob, V2.arrays_build(V_, F_), smooth=False, attrs=A_s)
    for k, (ob, sp) in enumerate(zip(parts["licks"], LICKS)):
        V_, F_, A_s = V2.strip_arrays(*_lick(sp, p, _lick_root(k, p)))
        K.replace_mesh(ob, V2.arrays_build(V_, F_), smooth=False, attrs=A_s)
    for ob, sp in zip(parts["ears"], EARS):
        (bx, by), (tx, ty), w, ph0 = sp
        sp2 = ((bx + p["hd"][0], by + p["hd"][1]), (tx + p["hd"][0], ty + p["hd"][1]), w, ph0)
        V_, F_, A_s = V2.strip_arrays(*_ear(sp2, p))
        K.replace_mesh(ob, V2.arrays_build(V_, F_), smooth=False, attrs=A_s)
    bpy.context.view_layer.update()
