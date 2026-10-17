"""疾影（精修三维）：一缕被风扯长的薄墨烟。

设定（LORE 附录）：裹得薄的影妖，多是新死的魂，还没被夜压沉，所以又轻又快，一碰就散。
造型和影妖分开（影妖是竖着的一团焦墨，疾影是横着的一缕薄墨）：头是一朵卷云——一笔从漩涡中心起笔，往外卷一圈，
转到前下方最粗，成了圆圆的“头”，卷心留一点白（魂裹在烟里，夜里卷心透出冷光）；到顶上顺背往后被风扯成长尾，
越拖越细、越淡、越干（飞白），尾梢散锋成几缕；肚下、中间、背上再拖三笔淡的。两只冷青的细眼斜着朝前（冲）。
颜色是薄墨（重墨到淡墨，偏冷），边上积墨，比影妖淡一大截。
做法：每一笔都是在设计稿（E 向画面）上画的扁带，放在过锚点的竖直平面里（正对镜头），材质是 v2kit.brush_material
（沿长取色、两边积墨、飞白、散锋、沿长渐淡）；眼是投到主笔上的贴片。不描墨线（薄烟没有硬边）。
动画 float 6 帧：卷云一胀一缩，每一笔的波往尾传。
帧 224²（2 倍；原来 160²，放大 1.4 倍后放不下），锚点 (0.5, 0.875)；游戏会给悬浮的妖物抬高 4 单位、上下起伏，帧里不做起伏。

    root, parts, sockets = build_wisp()
    pose_wisp(parts, "float", i, 6)
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

I, A_ = S.INK, S.ACCENT
EYE = "#9FE3FF"  # 同 enemies.ron 的 eye
EYE_HOT = "#F2FBFF"
GLOW = "#8CC8E8"  # 头里透出的魂光（夜里）
VZ = 25.0 * math.cos(math.radians(S.CAMERA_PITCH_DEG))
COOL = S.mix(I["dan"], A_["huaqing"], 0.3)
# 头的色带（d 从暗到亮）：焦墨 → 浓 → 重 → 偏冷的淡墨
HEAD_STOPS = [(0.00, I["jiao"]), (0.22, I["nong"]), (0.42, S.mix(I["nong"], I["zhong"], 0.6)), (0.60, I["zhong"]),
              (0.80, S.mix(I["zhong"], COOL, 0.7)), (1.00, S.mix(COOL, I["qing"], 0.3))]
RIM = S.mix(S.SOUL_LIGHT, I["qing"], 0.4)

# ---------------------------------------------------------------- 设计稿（单位，锚点为原点，x 前、y 上）
# 主笔：卷云头——从漩涡中心起笔，逆时针往外卷一圈（转到前下方最粗，成了“头”），到顶上顺背往后拖成尾，越拖越细
SPIRAL_C = (4.3, 13.2)
SPIRAL = (math.pi * 0.7, math.pi * 2.5, 0.45, 2.55)  # 起止角、起止半径
TAIL = [(-1.2, 2.55), (-5.0, 2.3), (-9.5, 2.9), (-14.0, 4.7), (-18.0, 7.0), (-21.0, 9.6)]  # 相对漩涡中心
MAIN_RAMP = [(0.0, S.mix(I["nong"], I["zhong"], 0.35)), (0.40, S.mix(I["nong"], I["zhong"], 0.5)), (0.62, I["zhong"]),
             (0.85, S.mix(I["zhong"], COOL, 0.6)), (1.0, COOL)]  # 主笔：薄墨（比影妖的焦墨淡），边上积墨
DARK_RAMP = [(0.0, I["jiao"]), (0.40, I["nong"]), (0.75, I["zhong"]), (1.0, S.mix(I["zhong"], COOL, 0.5))]
MID_RAMP = [(0.0, I["nong"]), (0.3, I["zhong"]), (0.7, S.mix(I["zhong"], COOL, 0.6)), (1.0, COOL)]
PALE_RAMP = [(0.0, I["zhong"]), (0.4, S.mix(I["zhong"], COOL, 0.6)), (1.0, S.mix(COOL, I["qing"], 0.5))]
# 副笔：(中线, 宽度, 色带, 前后（米，正 = 离镜头远）, 波幅, 相位, 散锋)
STROKES = [
    ([(4.6, 10.4), (0.6, 9.8), (-3.8, 10.4), (-8.2, 12.0), (-12.2, 14.0), (-15.6, 15.6)], [2.0, 1.9, 1.5, 1.0, 0.5, 0.15],
     "mid", 0.012, 0.9, 1.4, 6.0),  # 肚下一笔
    ([(2.0, 12.6), (-2.4, 12.6), (-6.8, 13.4), (-11.0, 14.8), (-15.0, 16.2), (-18.8, 16.8)], [1.4, 1.3, 1.0, 0.7, 0.35, 0.1],
     "pale", 0.020, 1.0, 2.6, 0.0),  # 夹在中间一笔淡的
    ([(0.6, 15.6), (-4.0, 17.6), (-8.6, 19.0), (-12.4, 19.6)], [0.8, 0.65, 0.4, 0.12], "dark", 0.008, 0.7, 3.6, 0.0),  # 背上细丝
]
FLECKS = []  # 墨点（起、止、半径、相位）：1080p 下只有一两个像素，像脏点，不要了
EYES = [((7.1, 13.8), 1.2, 0.5, -16.0), ((8.25, 13.3), 0.55, 0.33, -20.0)]  # 近眼、远眼：中心、半长、半高、斜度


d2m = V2.d2m


def main_path(breath=1.0):
    """主笔的中线（密）和每点的宽度（单位）：卷云头 + 尾。breath：卷云头一胀一缩。返回 (点, 宽, 尾从第几个点开始)。"""
    th0, th1, r0, r1 = SPIRAL
    cx, cy = SPIRAL_C
    pts, ws = [], []
    n = 60
    for i in range(n):
        u = i / (n - 1)
        th = th0 + (th1 - th0) * u
        r = (r0 + (r1 - r0) * u ** 0.8) * breath
        pts.append((cx + r * math.cos(th), cy + r * math.sin(th)))
        ws.append((0.35 + 3.4 * min(1.0, u / 0.72) ** 1.1 - 0.4 * max(0.0, (u - 0.72) / 0.28)) * breath)
    tc = DZ.curve_pts([pts[-1]] + [(cx + dx, cy + dy * breath if k == 0 else cy + dy) for k, (dx, dy) in enumerate(TAIL)],
                      80)[1:]
    m = len(tc)
    for k, p in enumerate(tc):
        v = (k + 1) / m
        pts.append(tuple(p))
        ws.append(3.0 * breath * (1 - v) ** 1.1 + 0.1)
    return np.asarray(pts), np.asarray(ws), n


_wave = V2.wave_line


WS = 1.4  # 整体放大（第二批审图：1080p 下太小、看不清）：以 (0, 13.2) 为中心放大，再整体抬到 14.8


def _T(c):
    c = np.asarray(c, np.float64).reshape(-1, 2)
    return np.stack([c[:, 0] * WS, (c[:, 1] - 13.2) * WS + 14.8], -1)


def _to_model(c, w, lat):
    return V2.design_strip(_T(c), np.asarray(w) * WS, lat)


def _main(ph):
    c, w, lock = main_path(1.0 + 0.035 * math.sin(ph))
    return _to_model(_wave(c, 1.1, ph, lock + 6), w, 0.0)


def _stroke(ctrl, widths, lat, amp, ph, n=36):
    c = DZ.curve_pts(ctrl, n)
    w = np.interp(np.linspace(0, 1, n), np.linspace(0, 1, len(widths)), widths)
    w = w * (1 + 0.08 * np.sin(ph * 2 + 5 * np.linspace(0, 1, n)))
    return _to_model(_wave(c, amp, ph), w, lat)


def build_wisp():
    root = B.empty("WispRoot")
    body = B.empty("WispBody", root)
    ramps = {"dark": DARK_RAMP, "mid": MID_RAMP, "pale": PALE_RAMP}
    m_main = V2.brush_material("WispMain", MAIN_RAMP, alpha=1.0, streak=0.62, streak_from=0.40, scale=(2.2, 26.0),
                               fade_from=0.80, seed=3.0, comb=10.0, glow=0.3, glow_to=0.22, edge_soft=0.12,
                               edge_dark=0.55)  # 魂光：卷云中心最亮（魂裹在烟里），到外圈落尽
    main = V2.flat_strip("WispMain", *_main(0.0), m_main, body)
    strokes = []
    for si, (ctrl, widths, rk, lat, amp, ph0, comb) in enumerate(STROKES):
        m = V2.brush_material(f"WispStroke{si}", ramps[rk], alpha=0.92 if rk != "pale" else 0.8, streak=0.6,
                              streak_from=0.2, scale=(2.0, 18.0 + 3 * si), fade_from=0.62, seed=4.0 + si, comb=comb)
        strokes.append(V2.flat_strip(f"WispStroke{si}", *_stroke(ctrl, widths, lat, amp, ph0), m, body))
    m_fleck = V2.paint_material("WispFleck", [(0.0, I["jiao"]), (0.5, I["nong"]), (1.0, I["zhong"])], wash=0.3, seed=8.0,
                                edge=0.5, bias=-0.15)
    flecks = [B.mesh_object(f"WispFleck{k}", K.ellipsoid((r / 25.0, r * 1.4 / 25.0, r / VZ)), m_fleck, "none", body)
              for k, (_, _, r, _) in enumerate(FLECKS)]
    # 眼：设计稿上的形状贴到主笔的“头”上（E 向）
    B.set_direction(root, "E")
    bpy.context.view_layer.update()
    tree = V2.bvh_world(main)
    m_eye = B.emissive_material("WispEye", EYE, 1.0)
    m_hot = B.emissive_material("WispEyeHot", EYE_HOT, 1.0)
    for k, ((ex, ey), hl, hh, tilt) in enumerate(EYES):
        for nm, mat, sc, lift in (("Eye", m_eye, 1.0, 0.004), ("Hot", m_hot, 0.5, 0.006)):
            V2.design_patch(f"WispEye{nm}{k}", tree, [tuple(q) for q in _T(_eye_poly(ex, ey, hl * sc, hh * sc, tilt))],
                            mat, body, lift=lift, spacing=0.25)
    sock = B.empty("WispSocketEyes", body)
    hits = V2.project_design(tree, [tuple(_T([(EYES[0][0][0] * 0.65 + EYES[1][0][0] * 0.35,
                                               EYES[0][0][1] * 0.65 + EYES[1][0][1] * 0.35)])[0])])
    if hits[0][0] is not None:
        sock.location = body.matrix_world.inverted() @ hits[0][0]
    B.set_direction(root, "S")
    parts = {"root": root, "body": body, "main": main, "strokes": strokes, "flecks": flecks, "sockets": {"eyes": sock}}
    bpy.context.view_layer.update()
    return root, parts, parts["sockets"]


def _eye_poly(ex, ey, hl, hh, tilt):
    """细长的眼：前头尖、往前下斜（冲），下沿平一点。"""
    a = math.radians(tilt)
    pts = [(hl, 0.0), (hl * 0.3, hh * 0.95), (-hl * 0.5, hh * 0.8), (-hl, 0.1 * hh), (-hl * 0.45, -hh * 0.7),
           (hl * 0.45, -hh * 0.65)]
    return V2.closed_smooth([(ex + x * math.cos(a) - y * math.sin(a), ey + x * math.sin(a) + y * math.cos(a))
                             for x, y in pts], 30)


def pose_wisp(parts, anim, frame, n):
    ph = 2 * math.pi * (frame % n) / n
    V_, F_, A_s = V2.strip_arrays(*_main(ph))
    K.replace_mesh(parts["main"], V2.arrays_build(V_, F_), smooth=False, attrs=A_s)
    for ob, (ctrl, widths, rk, lat, amp, ph0, comb) in zip(parts["strokes"], STROKES):
        V_, F_, A_s = V2.strip_arrays(*_stroke(ctrl, widths, lat, amp, ph + ph0))
        K.replace_mesh(ob, V2.arrays_build(V_, F_), smooth=False, attrs=A_s)
    for ob, (p0, p1, r, ph0) in zip(parts["flecks"], FLECKS):
        u = ((frame % n) / n + ph0) % 1.0  # 0..1 往后飘
        x, y = p0[0] + (p1[0] - p0[0]) * u, p0[1] + (p1[1] - p0[1]) * u
        ob.location = d2m(x, y, 0.03)
        sc = max(0.05, math.sin(math.pi * u)) ** 0.6  # 出现、长大、散掉
        ob.scale = (sc, sc, sc)
    bpy.context.view_layer.update()
