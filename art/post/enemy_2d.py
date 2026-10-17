#!/usr/bin/env python3
"""妖物重做 · B 法：手绘分件动画（纯 2D，Pillow + numpy，不用 Blender）。

每个部件用笔墨画一遍（ink2d.Layer），每帧给部件做旋转、平移、弯曲、压扁拉长，拼成动画（ink2d.Frame）；
烟、飘带这种本来就每帧变形的，按固定种子每帧现画（笔毛纹顺着笔走，不会闪）。超采样 SS 倍画，最后缩小。

影妖 shade（float 8 帧 @8）：人那么高的一团焦墨，倒挂的泪滴披着斗篷——兜帽里一团黑，只有两点暖金的眼；
  斗篷盖住背后，前襟露出一圈圈缠裹的墨茧，缠带的缝里和两道裂缝透出魂的微光；下摆散成墨烟拖在地上，
  背后两条松开的缠带在飘。诡异、哀伤，不凶：眼角下垂，一道裂缝从眼下流下来，像泪痕。
赤面狐 fox（move 8 @12、pounce 6 @12）：见 build_fox。

    art/.venv/bin/python art/post/enemy_2d.py            # 两只都出
    art/.venv/bin/python art/post/enemy_2d.py shade      # 只出影妖
    art/.venv/bin/python art/post/enemy_2d.py --preview shade   # 只出第 0 帧预览到 scratch（调形用）
输出：art/out/enemy_sample@2x/<shade|fox>_B/（同正式素材格式）。
"""

from __future__ import annotations

import math
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("LANTERN_ART_DENSITY", "2")

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

import ink2d as K  # noqa: E402
from enemy_design import *  # noqa: E402,F401,F403  设计稿（A、B 共用）
import enemy_design as DZ  # noqa: E402
import enemy_sample as ES  # noqa: E402

S = K.S
col, mixc = K.col, K.mixc
JIAO, NONG, ZHONG, DAN, QING, PAPER = K.JIAO, K.NONG, K.ZHONG, K.DAN, K.QING, K.PAPER
HUAQING, ZHUSHA, ZHESHI, TENG = (col(S.ACCENT[k]) for k in ("huaqing", "zhusha", "zheshi", "tenghuang"))
SS = 3  # 超采样倍数


def new_layer(kind, seed):
    sp = ES.SPEC[kind]
    n = sp["size"] * SS
    return K.Layer(n, n, ES.PPU * SS, (sp["anchor"][0] * n, sp["anchor"][1] * n), seed)


def new_frame(kind):
    n = ES.SPEC[kind]["size"] * SS
    return K.Frame(n, n)


def out_frame(kind, fr: K.Frame, grain):
    rgb, a, erg, ea = fr.down(SS)
    return ES.finish(rgb, a, erg, ea, grain)


def socket_px(kind, layer, pt_px):
    """画层像素 → 相对锚点的最终像素。"""
    return ((pt_px[0] - layer.ox) / SS, (pt_px[1] - layer.oy) / SS)


# ================================================================ 影妖
SH_EYE = col(ES.SPEC["shade"]["eye"])  # 暖金 #FFC46B
SH_EYE_HOT = col("#FFF1C8")  # 眼心最亮处
SH_CRACK = col("#F7D58A")  # 裂缝里的魂光（比眼淡）
SH_SHEEN = mixc(ZHONG, HUAQING, 0.30)  # 缠带受光的一道冷灰（月夜里也读得出层次）
SH_RIM = mixc(DAN, HUAQING, 0.25)

def _outline_pts():
    return K.curve_pts(SH_OUTLINE, 600, closed=True)


# 背后飘的两条斗篷尾角（最外两层的末端），每帧现画、跟着飘：(控制点, 根半宽, 相位)
SH_FLAPS = []


def paint_shade_body(seed=11):
    """影妖本体（不含烟）。返回画层和两眼之间的挂点（像素）。"""
    L = new_layer("shade", seed)
    k = L.k
    whole = (slice(0, L.h), slice(0, L.w))
    sl0, m0 = L.cover(L.P(SH_OUTLINE), soft=0.0)
    body = np.zeros((L.h, L.w), np.float32)
    body[sl0] = m0
    Xu = (L.X - L.ox) / k
    Yu = (L.oy - L.Y) / k
    # 1. 底：焦墨铺满剪影，边上洇开；左上受光处薄一点（浓墨里透一丝冷）
    L.fill(SH_OUTLINE, JIAO, 1.0, wet=1.4 * k / 4)
    lit = K.smoothstep(-0.2, 1.0, (-(Xu + 3.0) * 0.55 + (Yu - 26.0) * 0.85) / 15.0)
    L.tint(body * lit * 0.7, mixc(NONG, SH_SHEEN, 0.35), whole)
    # 2. 兜帽顶：两笔侧锋顺着帽顶的弧，外沿淡、里面浓；帽尖一笔
    L.broad(lean([(-14.2, 36.6), (-12.6, 41.8), (-6.6, 45.0), (0.6, 44.7), (7.0, 42.4), (10.8, 38.6)]), 2.4,
            (mixc(SH_SHEEN, ZHONG, 0.3), JIAO), 0.85, cross=1.2, streak=0.6, taper=(0.12, 0.25), wet=2.0, clip=body)
    L.broad(lean([(-18.2, 43.3), (-14.6, 43.4), (-10.6, 42.6)]), 0.9, (mixc(SH_SHEEN, ZHONG, 0.3), NONG), 0.8,
            cross=0.9, taper=(0.05, 0.6), wet=1.0, clip=body)
    # 3. 一层层裹住的纹：以脸为心往外套，每层的边是一道弧——焦墨的缝，缝里侧一线冷光（层边受光，左上亮、右下隐），
    #    缝里透一线魂光（夜里是一圈圈从眼睛荡开的淡金纹）；外层往下摆越来越松，断开
    vis = 0.25 + 0.75 * K.smoothstep(8.0, -8.0, (Xu - 2.0) * 0.8 - (Yu - 22.0) * 0.6)
    nl = len(SH_LAYERS)
    for i in range(nl - 1, -1, -1):
        pts = DZ._layer_arc(i)
        loose = i >= nl - 3
        w = 0.40 - 0.02 * i
        L.broad(pts, 1.5 + 0.12 * i, (mixc(NONG, SH_SHEEN, 0.35), JIAO), 0.55, cross=-1.1, streak=0.5,
                taper=(0.15, 0.25), wet=1.5, clip=body * vis)  # 层边的一道侧锋：近缝处淡（翻起的边），往外浓
        L.brush(pts, w, JIAO, 1.0, nail=0.3, tail=0.35, press=0.5, clip=body, dry=0.35 if loose else 0.1,
                dry_start=0.75, gap=((0.45, 0.55) if loose else None), emit=(SH_CRACK, 0.045 + 0.025 * (i % 2)))  # 缝里只是微光
        sheen = _offset(pts, -0.42)
        L.brush(sheen, 0.26, mixc(SH_SHEEN, DAN, 0.25), 0.6, nail=0.1, tail=0.5, press=0.0, clip=body * vis,
                dry=0.5, dry_start=0.25, gap=(0.30 + 0.07 * (i % 3), 0.42 + 0.07 * (i % 3)))
    # 4. 兜帽口：焦墨的空洞，帽檐一笔略亮（左上受光）
    (cx, cy), rx, ry, rot = SH_HOLLOW
    L.dot((cx, cy), rx, ry, JIAO, 1.0, ang=math.radians(rot), soft=7.0)
    th = np.linspace(math.radians(60), math.radians(200), 9)
    lip = [(cx + (rx + 0.5) * math.cos(t), cy + (ry + 0.4) * math.sin(t)) for t in th]
    L.broad(lip, [0.4, 0.85, 0.95, 0.8, 0.4], (mixc(SH_SHEEN, DAN, 0.2), ZHONG), 0.8, cross=-0.8, taper=(0.3, 0.4),
            wet=0.8, clip=body)
    L.glow((cx - 0.4, cy - 0.4), 3.6, SH_EYE, 0.10)  # 魂在肚子里：兜帽深处一团很淡的暖光（只在发光层）
    # 5. 眼：暖金的两点，上沿平、往外斜下（垂眼，哀伤），下沿是弧；眼心近白；柔光只在发光层
    eyes_px = []
    for ei, ((ex, ey), hl, hh, tilt) in enumerate(SH_EYES):
        a = math.radians(tilt)
        poly = DZ.shade_eye_poly(ei)
        L.glow((ex, ey), hl * 1.5, SH_EYE, 0.32)
        sl, m = L.cover(L.P(poly), soft=0.9)
        L.emit(m, SH_EYE, sl, keep_base=False)
        L.dot((ex - hl * 0.05, ey + hh * 0.05), hl * 0.42, hh * 0.30, SH_EYE_HOT, 1.0, ang=-a, emit=1.0, soft=2.0)
        eyes_px.append(L.P((ex, ey)))
    eyes_mid = eyes_px[0] * 0.6 + eyes_px[1] * 0.4
    # 6. 裂缝：墨壳裂开的细口子（边上焦墨，里面淡金），透出魂光；一道像泪痕，从近眼下往下流
    cracks = DZ.shade_cracks(seed)
    for cr, w in cracks:
        widths = w * np.interp(np.linspace(0, 1, len(cr)), [0, 0.3, 0.6, 1], [0.6, 1.1, 0.9, 0.3])
        L.broad(cr, widths * 2.3, JIAO, 0.8, taper=(0.1, 0.2), smooth=False, clip=body, jitter=0.3)
        L.broad(cr, widths, (SH_EYE_HOT, SH_CRACK), 1.0, taper=(0.15, 0.35), smooth=False, clip=body, jitter=0.3)
        L.brush(cr, w * 0.8, False, 1.0, nail=0.0, tail=0.6, press=0.0, smooth=False, clip=body, emit=(SH_CRACK, 0.8))
        for x, y in cr[1:-1:2]:
            L.glow((x, y), 1.3, SH_CRACK, 0.12)
    # 7. 外轮廓：受光的左上一线冷灰（墨边化开，夜里也托住剪影）
    ring = np.clip((body - np.clip(K.blur(body, 1.0 * k / 4), 0, 1)) * 3.0, 0, 1)
    up_left = K.smoothstep(-0.2, 0.7, (-(Xu + 1) * 0.6 + (Yu - 22) * 0.8) / 16.0)
    L.tint(ring * up_left * 0.6 * K.smoothstep(8, 14, Yu), SH_RIM, whole)
    # 下摆尖：往下化开，接到烟里
    fade = K.smoothstep(3.8, 10.0, Yu + 0.18 * Xu)
    for arr in (L.p, L.ep):
        arr *= fade[..., None]
    L.a *= fade
    L.ea *= fade
    return L, eyes_mid


def _offset(pts, d):
    """折线往左手边（沿走向）平移 d 单位。"""
    p = np.asarray(pts, np.float64)
    t = np.gradient(p, axis=0)
    t /= np.linalg.norm(t, axis=1, keepdims=True) + 1e-9
    return list(p + np.stack([-t[:, 1], t[:, 0]], -1) * d)


def _wave_pts(pts, ph, amp, k_wave=1.6, grow=1.2):
    """控制点加一道沿长度往后传的波（烟、飘带用）。amp 单位；越往尾越大。"""
    p = np.asarray(pts, np.float64)
    n = len(p)
    out = []
    for i in range(n):
        t = i / (n - 1)
        a = p[min(i + 1, n - 1)] - p[max(i - 1, 0)]
        a = a / (np.linalg.norm(a) + 1e-9)
        nrm = np.array([-a[1], a[0]])
        out.append(p[i] + nrm * amp * t ** grow * math.sin(2 * math.pi * k_wave * t - ph))
    return out


SH_SMOKE = [  # (控制点, 根半宽, 根的浓淡, 相位)：从下摆尖接下来（根是焦墨），贴着地往后拖，越拖越淡越细
    ([(0.6, 10.0), (-0.6, 5.6), (-3.0, 2.4), (-6.8, 1.2), (-10.6, 1.4), (-13.4, 2.8)], 2.7, 1.0, 0.0),
    ([(-3.0, 9.4), (-5.4, 6.8), (-8.2, 6.4), (-10.4, 7.6)], 1.1, 0.6, 1.9),  # 背后一缕往上飘
    ([(1.8, 7.6), (1.2, 3.6), (-1.2, 0.8), (-5.0, -0.2), (-9.0, 0.0)], 1.5, 0.8, 3.3),  # 前面一缕贴地
]


def paint_shade_smoke(ph, bob=0.0, seed=23):
    """这一帧的墨烟和斗篷尾角（同一个画层，按固定种子现画；相位 ph 让波往后传）。
    bob：本体这一帧浮起的高度，烟根、尾角根跟着走，烟尾贴着地不动。"""
    L = new_layer("shade", seed)
    L.rng = np.random.default_rng(seed)
    # 地上淡淡一滩（烟落地洇开）
    L.wash([(3.0, 1.0), (-1.0, 2.2), (-7.0, 2.4), (-12.6, 1.8), (-14.0, 0.4), (-9.0, -1.2), (-2.0, -1.0), (2.4, -0.4)],
           ZHONG, 0.22, soft=4.0 * L.k / 4, ring=0.15, rough=0.8)
    for j, (ctrl, hw, dens, sp) in enumerate(SH_SMOKE):
        L.rng = np.random.default_rng(seed * 10 + j)
        n = len(ctrl)
        ctrl = [(x, y + bob * (1 - i / (n - 1)) ** 1.5) for i, (x, y) in enumerate(ctrl)]
        pts = _wave_pts(ctrl, ph + sp, 0.7 + 0.2 * j, k_wave=0.9, grow=1.5)
        t = np.linspace(0, 1, 40)
        widths = hw * (1 - 0.88 * t ** 0.9)
        # 根是焦墨、往尾淡成重墨淡墨，透明度也往尾降：一笔里浓淡变化（不是两种颜色的两笔）
        colr_dark = mixc(JIAO, ZHONG, np.clip(t * 1.2, 0, 1) ** 1.2)
        sl, cov = L.broad(pts, widths, (mixc(NONG, ZHONG, 0.3), JIAO), 1.0, cross=0.4, taper=(0.02, 0.35),
                          dry=0.25, dry_start=0.7, streak=0.5, wet=3.0, mode="over")
        if cov is None:
            continue
        # 按沿笔的 t 重新上色、按 t 降透明：用笔画自己的场重新算（同一笔）
        f = K.seg_fields(L.X[sl], L.Y[sl], K.curve_pts(L.P(pts), 60), widths.max() * L.k)
        tt = f["t"]
        tone = mixc(JIAO, mixc(ZHONG, DAN, 0.3), np.clip(tt * 1.15, 0, 1) ** 1.1)
        L.tint(cov, tone, sl)
        fade = (1 - 0.75 * K.smoothstep(0.35, 1.0, tt)) * dens
        L.p[sl] *= (1 - cov * (1 - fade))[..., None]
        L.a[sl] *= (1 - cov * (1 - fade))
    Xu = (L.X - L.ox) / L.k
    Yu = (L.oy - L.Y) / L.k
    f = K.smoothstep(-15.5, -10.0, Xu) * K.smoothstep(-2.2, 0.4, Yu)  # 往后、往外淡掉
    L.p *= f[..., None]
    L.a *= f
    # 斗篷尾角：两条焦墨，从背后飘出来，尖朝后下，波往尾传
    for j, (ctrl, hw, sp) in enumerate(SH_FLAPS):
        L.rng = np.random.default_rng(seed * 100 + j)
        n = len(ctrl)
        ctrl = lean([(x, y + bob * (1 - 0.4 * i / (n - 1))) for i, (x, y) in enumerate(ctrl)])
        pts = _wave_pts(ctrl, ph + sp, 0.9, k_wave=0.8, grow=1.4)
        widths = hw * np.array([1.0, 0.85, 0.5, 0.12])
        L.broad(pts, widths, (mixc(NONG, SH_SHEEN, 0.3), JIAO), 1.0, cross=1.0, taper=(0.0, 0.55), wet=1.2,
                streak=0.5, dry=0.2, dry_start=0.8)
        L.brush(_offset(pts, -widths.mean() * 0.6)[1:], 0.22, mixc(SH_SHEEN, DAN, 0.3), 0.5, nail=0.1, tail=0.6,
                dry=0.5, dry_start=0.3)
    return L


def build_shade():
    """出影妖的 8 帧。返回 frames、sockets。"""
    sp = ES.SPEC["shade"]
    n, fps, _ = sp["anims"]["float"]
    body_layer, eyes_px = paint_shade_body()
    body = body_layer.part(SH_PIVOT, name="body")
    k = body_layer.k
    frames, eyes = [], []
    for i in range(n):
        ph = 2 * math.pi * i / n
        # 浮：上下 1.4 单位；往上时略拉长、到顶略压扁（弹性）；上身前后点头（追着光）
        bob = 1.4 * math.sin(ph)
        vel = math.cos(ph)
        sy = 1.0 + 0.035 * vel
        sx = 1.0 / math.sqrt(sy)
        bend = K.Bend(body.pivot, rot=-3.0 * math.sin(ph - 0.9), sx=sx, sy=sy, height=36 * k)
        move = K.Affine(body.pivot, tx=0.0, ty=bob, k=k)
        warp = K.Chain(bend, move)
        fr = new_frame("shade")
        fr.paint(paint_shade_smoke(ph, bob))
        fr.put(body, warp, emit_gain=0.88 + 0.12 * math.sin(ph * 2 + 0.6))
        frames.append(("float", i, *out_frame("shade", fr, "shade_B")))
        e = warp.fwd(np.asarray(eyes_px))
        eyes.append(socket_px("shade", body_layer, e))
    return frames, {"eyes": {"float": eyes}}


# ================================================================ 赤面狐
FX_EYE = col(ES.SPEC["fox"]["eye"])  # #FF6B5A
FX_EYE_HOT = col("#FFE2C2")
FX_CREAM = col("#F3EAD6")  # 米白（比宣纸略亮）
FX_MID = mixc(col(S.ACCENT["zheshi"]), PAPER, 0.52)  # 淡赭
FX_DARK = mixc(col(S.ACCENT["zheshi"]), PAPER, 0.12)  # 赭（背脊、暗面）
FX_SHADOW = mixc(col(S.ACCENT["zheshi"]), ZHONG, 0.45)
FX_RED = ZHUSHA
FX_RED_DARK = mixc(ZHUSHA, JIAO, 0.35)
FX_RED_GLOW = col("#E2553C")
FX_FAR_TINT = (mixc(ZHONG, col(S.ACCENT["huaqing"]), 0.3), 0.30)
LW = 1.4  # 赤面狐的墨线整体加粗（游戏里缩到 0.64 倍还要看得清）  # 远侧的腿：罩一层冷暗（离镜头远、在身子的影里）


def _limb_poly(a, b, wa, wb, bulge=0.0, n=10):
    """a→b 的一段肢体轮廓（单位）：两边按半宽 wa→wb 收，bulge>0 时中段后侧（行进方向右手边）鼓一点（肌肉），两头圆。"""
    a, b = np.asarray(a, float), np.asarray(b, float)
    d = b - a
    ln = np.linalg.norm(d) + 1e-9
    u = d / ln
    nr = np.array([-u[1], u[0]])  # 左手边
    ts = np.linspace(0, 1, n)
    w = wa + (wb - wa) * ts
    left = [a + u * ln * t + nr * wi for t, wi in zip(ts, w)]
    right = [a + u * ln * t - nr * (wi + bulge * math.sin(math.pi * t)) for t, wi in zip(ts, w)]
    capb = [b + (nr * math.cos(th) + u * math.sin(th)) * wb for th in np.linspace(0, math.pi, 7)[1:-1]]
    capa = [a + (-nr * math.cos(th) - u * math.sin(th)) * wa for th in np.linspace(0, math.pi, 7)[1:-1]]
    return left + capb + right[::-1] + capa, left, right


def paint_fox_segment(seed, a, b, wa, wb, base, *, bulge=0.0, light=None, dark=None, line_w=0.32, paw=False,
                      fur=0.0, far=False):
    """一段腿（在画层里按静止姿态原位画）：淡赭铺底，前侧（受光）一线米白，后侧压暗，两边提按的墨线（近端不画，
    好和上一段接上），paw=True 时末端画脚掌（墨色爪尖）。"""
    L = new_layer("fox", seed)
    poly, left, right = _limb_poly(a, b, wa, wb, bulge)
    sl, m = L.fill(poly, base, 1.0, wet=1.0)
    clip = np.zeros((L.h, L.w), np.float32)
    clip[sl] = m
    d = np.asarray(b, float) - np.asarray(a, float)
    d /= np.linalg.norm(d) + 1e-9
    back = (-d[1], d[0]) if d[1] < 0 else (d[1], -d[0])  # 腿往下时，右手边（画面右，背光）
    L.shade(poly, dark if dark is not None else FX_SHADOW, 0.55, (abs(back[0]) * 1.0, -0.4), lo=-0.1, hi=1.0, clip=clip)
    if light is not None:
        L.broad(left[1:-1], max(wa, wb) * 0.35, (light, base), 0.7, taper=(0.3, 0.3), cross=0.8, wet=0.6, clip=clip)
    if fur:
        k_ = max(3, int(np.linalg.norm(np.asarray(b) - np.asarray(a)) / 1.2))
        ts = np.linspace(0.15, 0.85, k_)
        roots = [np.asarray(a) + (np.asarray(b) - np.asarray(a)) * t + np.array([-d[1], d[0]]) * L.rng.uniform(-0.4, 0.4) * wa
                 for t in ts]
        L.fur(roots, [d] * len(roots), 1.4, 0.16, FX_DARK, 0.45 * fur, clip=clip, dry=0.4)
    lw = line_w * LW * (0.8 if far else 1.0)
    L.brush(right[1:], lw * 1.25, NONG if far else JIAO, 0.9, nail=0.25, tail=0.5, press=0.6)
    L.brush(left[2:], lw * 0.8, NONG, 0.8, nail=0.2, tail=0.5, press=0.4, gap=(0.45, 0.6))
    if paw:
        tip = np.asarray(b) + np.array([d[1] if d[1] < 0 else 0, 0]) * 0
        fw = np.array([1.0, -0.15])
        fw /= np.linalg.norm(fw)
        c = np.asarray(b) + fw * 0.6
        pw = [c + fw * 1.9 + np.array([0, -0.2]), c + fw * 1.2 + np.array([0, 0.75]), c + np.array([-0.9, 0.85]),
              c + np.array([-1.3, -0.15]), c + np.array([-0.7, -0.85]), c + fw * 1.4 + np.array([0, -0.85])]
        L.fill(pw, mixc(base, FX_DARK, 0.5), 1.0, wet=0.6)
        L.broad([c + np.array([-0.3, -0.5]), c + fw * 1.3 + np.array([0, -0.55]), c + fw * 2.0 + np.array([0, -0.3])],
                0.42, (NONG, JIAO), 0.9, taper=(0.2, 0.4))  # 墨色的爪尖一笔
        L.brush([c + np.array([-1.2, 0.3]), c + np.array([-0.4, 0.95]), c + fw * 1.4 + np.array([0, 0.6]),
                 c + fw * 2.0 + np.array([0, -0.2])], lw, JIAO, 0.9, nail=0.3, tail=0.4)
        L.brush([c + fw * 0.5 + np.array([0, 0.5]), c + fw * 0.9 + np.array([0, -0.4])], lw * 0.5, JIAO, 0.7, nail=0.0,
                tail=0.5)
    return L.part(a, name="seg")


def _tufted(edge_pts, nrm_sign, amp, every, rng, sharp=0.55):
    """在一条边上起毛簇：每隔 every 单位一个尖（往外 amp），尖之间略凹。返回加密后的点。"""
    c = K.curve_pts(edge_pts, max(12, int(np.hypot(*np.diff(np.asarray(edge_pts), axis=0).T).sum() / 0.4)))
    seg = np.hypot(*np.diff(c, axis=0).T)
    sacc = np.concatenate([[0], np.cumsum(seg)])
    tan = np.gradient(c, axis=0)
    tan /= np.linalg.norm(tan, axis=1, keepdims=True) + 1e-9
    nrm = np.stack([-tan[:, 1], tan[:, 0]], -1) * nrm_sign
    ph = rng.uniform(0, 1)
    u = (sacc / every + ph) % 1.0
    jit = 1 + 0.35 * np.sin(sacc * 1.7 + rng.uniform(0, 6))
    prof = np.where(u < sharp, u / sharp, (1 - u) / (1 - sharp)) ** 1.6  # 锯齿：慢起、快落（毛尖朝后）
    return c + nrm * (amp * jit * prof - amp * 0.25)[:, None]


def paint_fox_torso(seed=31):
    L = new_layer("fox", seed)
    rng = np.random.default_rng(seed)
    k = L.k
    whole = (slice(0, L.h), slice(0, L.w))
    sl, m = L.cover(L.P(FOX_TORSO), soft=0.0)
    body = np.zeros((L.h, L.w), np.float32)
    body[sl] = m
    L.fill(FOX_TORSO, FX_MID, 1.0, wet=1.0)
    # 胸、腹、喉是米白（上沿洇开）
    under = [(15.2, 27.0), (14.0, 24.6), (12.0, 21.6), (9.4, 18.2), (5.6, 16.4), (1.0, 16.6), (-3.6, 16.6), (-6.8, 15.0),
             (-8.6, 12.0), (-4.0, 11.6), (3.0, 12.0), (10.0, 10.6), (14.6, 14.0), (15.6, 20.0)]
    L.wash(under, FX_CREAM, 0.95, soft=4.0 * k / 4, mode="over", clip=body, ring=0.0)
    # 背脊：一笔侧锋的赭（上沿浓），从颈背到臀
    L.broad([(10.6, 27.2), (8.4, 24.8), (4.0, 23.6), (-2.0, 22.8), (-7.0, 23.0), (-11.2, 22.2), (-14.0, 20.0)],
            [1.6, 2.2, 2.3, 2.1, 2.2, 1.9, 1.3], (FX_MID, FX_DARK), 0.95, cross=-1.3, streak=0.8, wet=1.6,
            taper=(0.1, 0.25), clip=body)
    # 背光：腹下、臀后压暗
    L.shade(FOX_TORSO, FX_SHADOW, 0.6, (0.25, -1.0), lo=0.05, hi=1.0, clip=body)
    # 后腿根的大腿肌、前腿根的肩胛（几笔暗赭的弧，后段飞白）
    L.broad([(-5.2, 21.4), (-7.4, 19.6), (-10.0, 17.0), (-12.6, 14.4)], 1.5, (FX_MID, FX_DARK), 0.5, cross=1.0,
            taper=(0.2, 0.4), dry=0.4, dry_start=0.5, wet=1.0, clip=body)
    L.brush([(-5.0, 20.8), (-7.8, 18.4), (-10.4, 15.6), (-12.2, 13.6)], 0.24 * LW, NONG, 0.7, nail=0.2, tail=0.6, dry=0.3)
    L.brush([(7.0, 22.6), (6.0, 20.0), (5.6, 17.4)], 0.22 * LW, NONG, 0.6, nail=0.2, tail=0.6, dry=0.35)
    # 毛：背上一片顺着往后的短笔丝（赭），腹边一排往下的米白毛尖
    roots = [(x, 22.6 - 0.06 * abs(x + 2) + rng.uniform(-1.6, 0.4)) for x in np.linspace(8.0, -12.5, 26)]
    L.fur(roots, [(-1.0, -0.25)] * len(roots), 1.8, 0.15, [FX_DARK, FX_SHADOW], 0.5, clip=body, dry=0.5)
    roots = [(x, 15.4 + 0.25 * x * (x < 3) * -0.1 + rng.uniform(-0.3, 0.3)) for x in np.linspace(5.0, -5.5, 9)]
    L.fur(roots, [(-0.35, -1.0)] * len(roots), 1.5, 0.2, FX_CREAM, 0.7, dry=0.3)
    # 胸前的一蓬白毛（守门的武将挺着胸）：几簇毛尖往下、往前
    for i, (cx, cy, ln, ang) in enumerate([(13.4, 21.2, 3.0, -62), (13.8, 19.0, 3.2, -70), (13.6, 16.8, 3.0, -78),
                                            (12.8, 14.6, 2.6, -90), (11.4, 13.0, 2.2, -100)]):
        r = math.radians(ang)
        dvec = np.array([math.cos(r), math.sin(r)])
        nrm = np.array([-dvec[1], dvec[0]])
        base0 = np.array([cx, cy]) - nrm * 1.1
        base1 = np.array([cx, cy]) + nrm * 1.1
        tipp = np.array([cx, cy]) + dvec * ln + np.array([0.9, 0.0])
        tuft = [base0, base0 + dvec * ln * 0.5 - nrm * 0.4, tipp, base1 + dvec * ln * 0.45 + nrm * 0.2, base1]
        L.fill(tuft, FX_CREAM, 1.0, wet=0.5)
        L.brush([base1 + dvec * 0.3, base1 + dvec * ln * 0.5 + nrm * 0.15, tipp], 0.2 * LW, JIAO, 0.85, nail=0.15, tail=0.7)
    # 外轮廓：背线（肩上重、往臀收）、臀、腹线（腰收进去）、胸前
    L.brush([(11.2, 27.6), (8.8, 25.0), (4.6, 23.4), (-1.0, 22.6), (-6.4, 23.0)], 0.42 * LW, JIAO, 0.95, press=0.6, nail=0.5,
            tail=0.4)
    L.brush([(-6.0, 23.0), (-10.4, 22.8), (-13.6, 21.0), (-15.0, 18.4), (-14.6, 15.4)], 0.36 * LW, JIAO, 0.95, press=0.7,
            nail=0.3, tail=0.5)
    belly = _tufted([(5.6, 12.8), (2.4, 14.2), (-1.8, 14.8), (-5.2, 14.0), (-7.4, 12.8)], 1, 0.55, 1.5, rng)
    L.brush(belly, 0.26 * LW, JIAO, 0.9, smooth=False, nail=0.2, tail=0.4, press=0.3, dry=0.2, dry_start=0.7)
    # 颈上的红绳：一圈朱砂（近侧一段看得见），喉下打个结，垂两截
    cord = FOX_CORD
    L.broad(cord, 0.42, (FX_RED, FX_RED_DARK), 1.0, cross=0.9, taper=(0.15, 0.15), wet=0.4)
    L.brush([(x, y - 0.35) for x, y in cord], 0.14, FX_RED_DARK, 0.9, nail=0.0, tail=0.3)
    kx, ky = FOX_CORD_KNOT
    L.dot((kx, ky), 0.62, 0.52, FX_RED, 1.0, soft=1.2)
    L.dot((kx + 0.15, ky + 0.15), 0.25, 0.2, mixc(FX_RED, PAPER, 0.4), 1.0, soft=1.0)
    L.broad([(kx, ky - 0.3), (kx + 0.5, ky - 1.4), (kx + 0.4, ky - 2.6)], [0.3, 0.26, 0.18], (FX_RED, FX_RED_DARK), 1.0,
            taper=(0.05, 0.5))
    L.broad([(kx - 0.2, ky - 0.3), (kx - 0.6, ky - 1.3), (kx - 0.9, ky - 2.2)], [0.26, 0.22, 0.15], (FX_RED, FX_RED_DARK), 1.0,
            taper=(0.05, 0.5))
    return L.part(FOX_PIVOT, name="torso")


def paint_fox_head(seed=41):
    L = new_layer("fox", seed)
    rng = np.random.default_rng(seed)
    k = L.k
    sl, m = L.cover(L.P(FOX_HEAD), soft=0.0)
    head = np.zeros((L.h, L.w), np.float32)
    head[sl] = m
    L.fill(FOX_HEAD, FX_MID, 1.0, wet=0.9)
    # 颊、下颌、吻下是米白
    low = FOX_HEAD_PTS["cheek_low"]
    L.wash(low, FX_CREAM, 0.95, soft=2.5 * k / 4, mode="over", clip=head, ring=0.0)
    # 额顶、后脑：一笔侧锋的赭
    L.broad(FOX_HEAD_PTS["crown"],
            [1.3, 1.7, 1.8, 1.6, 1.2, 0.8], (FX_MID, FX_DARK), 0.8, cross=-1.1, streak=0.6, wet=1.2, taper=(0.2, 0.3),
            clip=head)
    # 颊毛：往后下方炸开的米白毛簇（狐狸的腮毛）
    cheek = _tufted(FOX_HEAD_PTS["ruff"], -1, 1.5, 1.6, rng, sharp=0.35)
    poly = list(cheek) + FOX_HEAD_PTS["ruff_close"]
    L.fill(poly, FX_CREAM, 1.0, wet=0.4, units=True)
    L.brush(cheek, 0.22 * LW, JIAO, 0.85, smooth=False, nail=0.2, tail=0.5, press=0.3)
    # 朱砂红脸：额头抹过鼻梁一笔，两颊一笔（湿笔，边上积一点深红）
    for line, wds, al, cr in ((FOX_MASK_BRIDGE, [2.2, 2.0, 1.55, 1.05], 0.96, 0.5), (FOX_MASK_CHEEK, [1.25, 1.6, 1.55, 1.2, 0.6], 0.94, 0.6)):
        sl_m, cov_m = L.broad(line, wds, (FX_RED, FX_RED_DARK), al, cross=cr, streak=0.5, wet=1.2, taper=(0.15, 0.35),
                              clip=head)
        if cov_m is not None:  # 朱砂在夜里隐隐透红：发光层里很淡的一层
            L.emit(cov_m * head[sl_m] * 0.18, FX_RED_GLOW, sl_m)
    L.broad(FOX_HEAD_PTS["far_cheek"], 0.65, FX_RED, 0.85, taper=(0.2, 0.4), wet=0.8, clip=head)  # 远颊露出一点
    # 戏台浓眉：往后上挑，起笔重
    L.brush(FOX_BROW, 0.75 * LW, JIAO, 0.95, nail=0.8, tail=0.55, press=0.4)
    # 丹凤眼：发光的眼仁、竖瞳；上眼线重，过外眼角往后上挑
    (ex, ey), hl, hh, tilt = FOX_EYE
    a = math.radians(tilt)

    def rot(pts):
        return [(ex + x * math.cos(a) - y * math.sin(a), ey + x * math.sin(a) + y * math.cos(a)) for x, y in pts]
    eye = rot([(hl, 0.0), (hl * 0.3, hh), (-hl * 0.5, hh * 0.9), (-hl, 0.15 * hh), (-hl * 0.4, -hh * 0.8),
               (hl * 0.4, -hh * 0.75)])
    L.glow((ex, ey), 1.8, FX_EYE, 0.28)
    sl_e, m_e = L.cover(L.P(eye), soft=0.7)
    L.emit(m_e, FX_EYE, sl_e, keep_base=False)
    sl_p, a_p = L.dot((ex - 0.15, ey + 0.05), hh * 0.32, hh * 0.85, JIAO, 1.0, ang=a, soft=0.8)  # 竖瞳（发光层里挖掉）
    L.ep[sl_p] *= (1 - a_p * 0.9)[..., None]
    L.ea[sl_p] *= (1 - a_p * 0.9)
    L.dot((ex + 0.5, ey + 0.25), 0.22, 0.16, FX_EYE_HOT, 1.0, emit=1.0, soft=0.8)
    L.brush(rot([(hl * 1.05, 0.05), (hl * 0.2, hh * 1.15), (-hl * 0.7, hh * 0.95), (-hl * 1.5, hh * 1.4)]), 0.30 * LW,
            JIAO, 0.95, nail=0.3, tail=0.5, press=0.5)
    L.brush(rot([(-hl * 0.9, 0.0), (-hl * 0.2, -hh * 0.95), (hl * 0.6, -hh * 0.7)]), 0.16 * LW, JIAO, 0.85, nail=0.1,
            tail=0.5)
    (fx, fy), fl, fh, ft = FOX_EYE_FAR
    L.dot((fx, fy), fl, fh, FX_EYE, 1.0, ang=math.radians(ft), emit=1.0, soft=0.8)
    L.brush([(fx - 0.8, fy + 0.6), (fx + 0.6, fy + 0.5)], 0.15 * LW, JIAO, 0.85, nail=0.2, tail=0.4)
    # 鼻、嘴、獠牙、须
    L.dot(FOX_NOSE, 0.62 * FOX_HEAD_S, 0.48 * FOX_HEAD_S, JIAO, 1.0, soft=1.0)
    L.brush(FOX_HEAD_PTS["mouth"], 0.18 * LW, JIAO, 0.9, nail=0.2, tail=0.4)
    L.fill(FOX_HEAD_PTS["fang"], FX_CREAM, 1.0, soft=0.4)
    L.brush(FOX_HEAD_PTS["fang"], 0.09 * LW, JIAO, 0.8, nail=0.0, tail=0.2, smooth=False)
    wx, wy = FOX_HEAD_PTS["whisker_root"]
    for dy, ln in ((0.0, 5.2), (-0.6, 4.4), (0.6, 4.2)):
        L.brush([(wx, wy + dy), (wx - 2.4, wy + 0.1 + dy * 1.6), (wx - ln, wy - 0.2 + dy * 2.4)], 0.08 * LW, NONG, 0.55,
                nail=0.0, tail=0.7)
    # 外轮廓：额顶到后脑、吻背到鼻尖、下巴到喉（提按，留几处断）
    L.brush(FOX_HEAD_PTS["line_top"], 0.36 * LW, JIAO, 0.95, nail=0.5, tail=0.6, press=0.7)
    L.brush(FOX_HEAD_PTS["line_snout"], 0.32 * LW, JIAO, 0.95, nail=0.3, tail=0.3, press=0.5)
    L.brush(FOX_HEAD_PTS["line_jaw"], 0.28 * LW, JIAO, 0.9, nail=0.2, tail=0.5, gap=(0.5, 0.62))
    return L.part(FOX_NECK, name="head")


def paint_fox_ear(seed, tri, far=False):
    L = new_layer("fox", seed)
    b0, tip, b1 = (np.asarray(p, float) for p in tri)
    mid = (b0 + b1) / 2
    out = [b0, b0 + (tip - b0) * 0.55 + np.array([-0.35, 0.1]), tip, b1 + (tip - b1) * 0.5 + np.array([0.25, 0.1]), b1,
           mid + np.array([0, -0.5])]
    sl, m = L.fill(out, FX_MID if not far else mixc(FX_MID, FX_DARK, 0.4), 1.0, wet=0.6)
    clip = np.zeros((L.h, L.w), np.float32)
    clip[sl] = m
    inner = [b0 + (b1 - b0) * 0.2 + (tip - b0) * 0.1, tip + (mid - tip) * 0.22, b1 + (b0 - b1) * 0.2 + (tip - b1) * 0.08]
    if not far:
        L.fill(inner, FX_CREAM, 1.0, wet=0.5)
        rr = [inner[0] + (inner[2] - inner[0]) * t for t in np.linspace(0.1, 0.9, 5)]
        L.fur(rr, [tip - r for r in rr], 1.6, 0.12, mixc(FX_CREAM, FX_DARK, 0.4), 0.6, dry=0.3, clip=clip)
    # 耳背、耳尖是墨色（狐狸的黑耳背）
    L.broad([b0 + np.array([0.1, 0.0]), b0 + (tip - b0) * 0.6, tip], [0.75, 0.6, 0.3], (NONG, JIAO), 0.9, taper=(0.2, 0.2),
            wet=0.6, clip=clip)
    L.broad([tip + (mid - tip) * 0.3, tip], 0.8, (NONG, JIAO), 0.9, taper=(0.4, 0.1), clip=clip)
    L.brush([b0, b0 + (tip - b0) * 0.55 + np.array([-0.3, 0.1]), tip], 0.3 * LW, JIAO, 0.95, nail=0.4, tail=0.2)
    L.brush([tip, b1 + (tip - b1) * 0.5 + np.array([0.25, 0.1]), b1], 0.24 * LW, JIAO, 0.9, nail=0.1, tail=0.6)
    return L.part(tuple(mid), name="ear")


def tail_layer(seed, puff=1.0, spiky=1.0):
    """尾巴摆直画（沿 +x，尾根在左）：返回画层、尾根像素、尾尖像素。puff>1 是炸毛（扑击时）。"""
    k = ES.PPU * SS
    Lx = FOX_TAIL_LEN
    wmax = max(w for _, w in FOX_TAIL_W) * puff + 3.5
    W = int((Lx + 8) * k)
    H = int(2 * wmax * k)
    L = K.Layer(W, H, k, (3 * k, H / 2), seed)
    rng = np.random.default_rng(seed)
    ts = np.linspace(0, 1, 60)
    wt = np.interp(ts, [t for t, _ in FOX_TAIL_W], [w for _, w in FOX_TAIL_W]) * puff
    top = [(t * Lx, w) for t, w in zip(ts, wt)]
    bot = [(t * Lx, -w) for t, w in zip(ts, wt)]
    amp, every = 1.0 * spiky * puff, 2.0 / max(spiky, 1e-3) * (1.0 if puff <= 1 else 0.8)
    top_t = _tufted(top, -1, amp, every, rng)
    bot_t = _tufted(bot, 1, amp * 0.9, every * 1.1, rng)
    tipp = np.array([[Lx + 1.4 * puff, 0.3]])
    poly = np.vstack([top_t[1:], tipp, bot_t[::-1][:-1]])
    sl, m = L.cover(L.P(poly), soft=0.0, smooth=False)
    clip = np.zeros((L.h, L.w), np.float32)
    clip[sl] = m
    L.over(m, FX_MID, sl)
    # 外侧（+y，背向身子）赭、内侧（-y）米白
    L.wash([(0, 0.3), (Lx, 0.3), (Lx, -wmax), (0, -wmax)], FX_CREAM, 0.9, soft=3.0 * k / 4, mode="over", clip=clip,
           ring=0.0)
    L.broad([(x, w * 0.65) for x, w in top[2::6]], [w * 0.45 for _, w in top[2::6]], (FX_MID, FX_DARK), 0.7, cross=-1.0,
            streak=0.9, wet=1.4, taper=(0.1, 0.3), clip=clip)
    # 毛：顺着尾巴往尖的长笔丝
    for j in range(36):
        y0 = rng.uniform(-1, 1)
        x0 = rng.uniform(0.0, 0.7) * Lx
        ln = rng.uniform(4.0, 8.0)
        wy = np.interp(x0 / Lx, ts, wt)
        pts = [(x0, y0 * wy * 0.8), (x0 + ln * 0.5, y0 * wy * 0.9 + 0.3 * np.sign(y0)), (x0 + ln, y0 * wy * 1.0 + 0.6 * np.sign(y0))]
        L.brush(pts, 0.14, FX_DARK if y0 > -0.2 else mixc(FX_CREAM, FX_DARK, 0.35), 0.4, nail=0.0, tail=0.8, dry=0.5,
                dry_start=0.3, clip=clip)
    # 尾尖墨色：像蘸饱墨的笔尖——墨从尖往根洇（边缘参差），尖上几笔飞白往外拖、收成一点
    X0 = FOX_TAIL_INK * Lx
    ink = K.smoothstep(X0 - 1.6, X0 + 2.6, (L.X - L.ox) / k + 1.1 * L.noise((L.h, L.w), 3.0 * SS)) * clip
    whole = (slice(0, L.h), slice(0, L.w))
    L.over(ink * 0.96, JIAO, whole)
    for j in range(16):
        y0 = rng.uniform(-0.85, 0.85)
        x0 = X0 - rng.uniform(1.0, 3.5)
        wy = np.interp(x0 / Lx, ts, wt)
        L.brush([(x0, y0 * wy), (x0 + 3.0, y0 * wy * 0.7), (Lx + 1.2 * puff, 0.2 * y0)], 0.22, NONG, 0.75, nail=0.0,
                tail=0.9, dry=0.55, dry_start=0.25, clip=clip)
    # 外轮廓：两边带毛簇的墨线（断续）
    L.brush(top_t[::2], 0.3 * LW, JIAO, 0.9, smooth=False, nail=0.3, tail=0.3, press=0.3, gap=(0.35, 0.42))
    L.brush(bot_t[::2], 0.26 * LW, JIAO, 0.85, smooth=False, nail=0.3, tail=0.3, press=0.3, gap=(0.6, 0.66))
    if puff > 1:  # 炸开的毛：几根散出去的毛尖
        for j in range(14):
            t = rng.uniform(0.2, 0.85)
            side = 1 if j % 2 else -1
            w0 = np.interp(t, ts, wt)
            r0 = (t * Lx, side * w0 * 0.9)
            r1 = (t * Lx + rng.uniform(1.0, 2.5), side * (w0 + rng.uniform(1.0, 2.2)))
            L.brush([r0, ((r0[0] + r1[0]) / 2, (r0[1] + r1[1]) / 2 + side * 0.2), r1], 0.18,
                    JIAO if t > FOX_TAIL_INK - 0.05 else FX_DARK, 0.85, nail=0.1, tail=0.9)
    root_px = L.P((0.0, 0.0))
    tip_px = L.P((Lx, 0.0))
    return L.part((0.0, 0.0), name="tail", pad=8), root_px, tip_px


class FoxRig:
    """赤面狐的分件和每帧的摆法。"""

    def __init__(self):
        t0 = time.perf_counter()
        self.torso = paint_fox_torso()
        self.head = paint_fox_head()
        self.ear_near = paint_fox_ear(51, FOX_EAR_NEAR)
        self.ear_far = paint_fox_ear(52, FOX_EAR_FAR, far=True)
        self.tail, self.tail_a, self.tail_b = tail_layer(61)
        self.tail_puff, self.tp_a, self.tp_b = tail_layer(62, puff=1.32, spiky=1.4)
        self.legs = {}
        fw = [(2.5, 1.9, 0.6), (1.45, 1.05, 0.0), (1.0, 0.9, 0.0)]  # 前腿三段的半宽、鼓
        hw = [(3.4, 2.1, 0.9), (1.6, 1.05, 0.3), (0.95, 0.85, 0.0)]
        for far in (False, True):
            off = np.array(FOX_FAR) if far else np.zeros(2)
            for name, root, segs, widths in (("front", FOX_SHOULDER, FOX_FRONT_LEG, fw), ("hind", FOX_HIP, FOX_HIND_LEG, hw)):
                pts = fox_leg(np.asarray(root) + off, segs)
                parts = []
                for si in range(3):
                    wa, wb, bu = widths[si]
                    base = FX_MID if si < 2 else mixc(FX_MID, FX_DARK, 0.35)
                    parts.append(paint_fox_segment(71 + si + 10 * far + (5 if name == "hind" else 0), pts[si], pts[si + 1],
                                                   wa, wb, base, bulge=bu, light=FX_CREAM if si < 2 else None,
                                                   paw=(si == 2), fur=1.0 if si == 0 else 0.0, far=far))
                self.legs[(name, far)] = (parts, pts)
        print(f"  赤面狐分件 {time.perf_counter() - t0:.1f}s")

    def frame(self, pose):
        """pose：dict（body: (dx, dy, rot, sx, sy)、head: (rot, dx, dy)、ears: rot、legs: {(name, far): [角度×3]}、
        tail: (angle, curl, wave, ph, puff)）→ 一帧（Frame）和两眼挂点（像素）。"""
        k = ES.PPU * SS
        lay = new_layer("fox", 0)
        dx, dy, rot, sx, sy = pose["body"]
        bodyw = K.Affine(lay.P(FOX_PIVOT), rot=rot, sx=sx, sy=sy, tx=dx, ty=dy, k=k)
        fr = new_frame("fox")

        def attach(pt):  # 身体上一点（设计稿）→ 这一帧的位置（像素）
            return bodyw.fwd(lay.P(pt))

        # 尾巴（在最后面）
        ang, curl, wave, ph, puff = pose["tail"]
        root_now = lay.U(attach(FOX_TAIL_ROOT))
        tail_part, ta, tb = (self.tail_puff, self.tp_a, self.tp_b) if puff else (self.tail, self.tail_a, self.tail_b)
        curve = fox_tail_curve(root_now - np.array([0.0, 0.0]), angle=ang + rot, curl=curl, wave=wave, ph=ph, n=24)
        # 尾巴往身子里多插一截，免得根上露缝
        back = curve[0] - (curve[1] - curve[0]) / np.linalg.norm(curve[1] - curve[0]) * 1.6
        ext = np.vstack([back, curve])
        cpx = lay.P(ext)
        rest_a = ta - np.array([1.6 * k, 0.0])
        fr.put(tail_part, K.Curve(rest_a, tb, cpx))
        # 远侧两条腿 → 躯干 → 近侧两条腿
        order = [("hind", True), ("front", True), None, ("hind", False), ("front", False)]
        for item in order:
            if item is None:
                fr.put(self.torso, bodyw)
                continue
            parts, rest_pts = self.legs[item]
            ang_now = pose["legs"][item]
            root_rest = rest_pts[0]
            root_now = lay.U(attach(root_rest))
            segs = FOX_FRONT_LEG if item[0] == "front" else FOX_HIND_LEG
            now_pts = fox_leg(root_now, segs, [a + rot for a in ang_now])
            rest_ang = [sg[1] for sg in segs]
            for si in (2, 1, 0):  # 先画末端（脚掌在下面，上一段盖住接口）
                w = K.Affine(lay.P(rest_pts[si]), rot=ang_now[si] + rot - rest_ang[si],
                             tx=now_pts[si][0] - rest_pts[si][0], ty=now_pts[si][1] - rest_pts[si][1], k=k)
                fr.put(parts[si], w, tint=FX_FAR_TINT if item[1] else None)
        # 头和耳
        hrot, hdx, hdy = pose["head"]
        neck_now = lay.U(attach(FOX_NECK))
        headw = K.Affine(lay.P(FOX_NECK), rot=hrot + rot, tx=neck_now[0] - FOX_NECK[0] + hdx,
                         ty=neck_now[1] - FOX_NECK[1] + hdy, k=k)
        erot = pose["ears"]
        for ear, tri in ((self.ear_far, FOX_EAR_FAR),):
            fr.put(ear, K.Chain(K.Affine(ear.pivot, rot=erot), headw))
        fr.put(self.head, headw)
        fr.put(self.ear_near, K.Chain(K.Affine(self.ear_near.pivot, rot=erot), headw))
        eye = headw.fwd(lay.P(FOX_EYE[0]) * 0.65 + lay.P(FOX_EYE_FAR[0]) * 0.35)
        return fr, ((eye[0] - lay.ox) / SS, (eye[1] - lay.oy) / SS)


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


def build_fox():
    rig = FoxRig()
    frames, eyes = [], {}
    for anim, (n, fps, _) in ES.SPEC["fox"]["anims"].items():
        for i in range(n):
            pose = fox_move_pose(i, n) if anim == "move" else fox_pounce_pose(i)
            fr, eye = rig.frame(pose)
            frames.append((anim, i, *out_frame("fox", fr, "fox_B")))
            eyes.setdefault(anim, []).append(eye)
    return frames, {"eyes": eyes}


# ================================================================ 出图
def preview(kind, path):
    if kind == "shade":
        frames, socks = build_shade_preview()
    else:
        rig = FoxRig()
        frames = []
        for name in (os.environ.get("FOX_PREVIEW", "move:0").split(",")):
            an, idx = name.split(":")
            pose = fox_move_pose(int(idx), 8) if an == "move" else fox_pounce_pose(int(idx))
            fr, _ = rig.frame(pose)
            frames.append((an, int(idx), *out_frame("fox", fr, "fox_B")))
    fr = frames[0]
    im = Image.fromarray(fr[2], "RGBA")
    big = im.resize((im.width * 3, im.height * 3), Image.NEAREST)
    bg = Image.new("RGBA", big.size, tuple(int(c * 255) for c in PAPER) + (255,))
    bg.alpha_composite(big)
    bg.convert("RGB").save(path)


def build_shade_preview():
    body_layer, eyes_px = paint_shade_body()
    fr = new_frame("shade")
    fr.paint(paint_shade_smoke(0.0))
    fr.put(body_layer.part(SH_PIVOT))
    return [("float", 0, *out_frame("shade", fr, "shade_B"))], {}


def main(argv):
    t0 = time.perf_counter()
    kinds = [a for a in argv if not a.startswith("-")] or ["shade", "fox"]
    for kind in kinds:
        t1 = time.perf_counter()
        if kind == "shade":
            frames, socks = build_shade()
        else:
            frames, socks = build_fox()
        extra = {"shadow_radius_px": 32 if kind == "shade" else 77, "method": "B"}
        out = ES.write_asset(f"{kind}_B", frames, socks, extra)
        print(f"[{kind}_B] {len(frames)} 帧 → {out}（{time.perf_counter() - t1:.1f}s）")
    print(f"共 {time.perf_counter() - t0:.1f}s")


if __name__ == "__main__":
    main(sys.argv[1:])
