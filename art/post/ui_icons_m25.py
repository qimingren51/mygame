#!/usr/bin/env python3
"""提灯夜行 · M2.5 界面图标（只用 Pillow + numpy；由 ui_icons.py 调用，写进同一个 ui/ 与 meta.json）。

和原有图标同一套框（ui_icons.disc_back / ring_front / omen_front），追加在全部原有图标与印章之后：
  心法 icon_{xunfeng,huichun,hanyi,dengxin,zaiwu,qinggong,juhun}：有五行的用本行色弧，无属性的用补给那道中性弧；
  夜签 icon_omen_{wuyue,nike}：朱砂双圈框；
  货币 icon_gold（金币）；奇遇 icon_enc_merchant（货郎，色弧取 events.ron 的 #E8C27A）；
  精英词缀 icon_affix_{ji,jian,fen,zhao,yin,kuang}：界面图集里唯一的小图标，32×32（1 倍）/ 64×64（2 倍），
    同一套框但墨圈、色弧加粗，物件只留大块，要在 24 像素下认得出；色弧统一用朱砂（精英）。

坐标按 64×64 的 1 倍像素写（圆心 (32, 32)）；小图标的画布是 32 像素，把网格坐标乘 2 后照样按 64 的设计坐标画。
种子：9000 + 37 × 序号（与前两批错开）。
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import ui_icons as U  # noqa: E402

V, W, S = U.V, U.W, U.S
Fr, shape, stroke, glow, shade_lr, sparkle, flame, coin, leaf = U.Fr, U.shape, U.stroke, U.glow, U.shade_lr, U.sparkle, U.flame, U.coin, U.leaf
mixc, smoothstep, col = U.mixc, U.smoothstep, U.col
PAPER, PAPER_SH, WHITE = U.PAPER, U.PAPER_SH, U.WHITE
JIAO, NONG, ZHONG, DAN, QING = U.JIAO, U.NONG, U.ZHONG, U.DAN, U.QING
ZHUSHA, ZHESHI, HUAQING, SHILV, TENG = U.ZHUSHA, U.ZHESHI, U.HUAQING, U.SHILV, U.TENG
W_ZHUSHA, W_ZHESHI, W_HUAQING, W_SHILV, W_TENG = U.W_ZHUSHA, U.W_ZHESHI, U.W_HUAQING, U.W_SHILV, U.W_TENG
GOLD_DK, GOLD_HI, ZHUSHA_DK, INK_LINE = U.GOLD_DK, U.GOLD_HI, U.ZHUSHA_DK, U.INK_LINE
EL_INK, OL = U.EL_INK, U.OL
C = U.C

MERCHANT_HEX = "#E8C27A"  # assets/data/events.ron 货郎的颜色
MERCHANT_INK = col(S.mix(S.mix(MERCHANT_HEX, S.ACCENT["tenghuang"], 0.4), S.ACCENT["zheshi"], 0.35))
AFFIX_ARC = mixc(ZHUSHA, ZHUSHA_DK, 0.2)  # 精英词缀：朱砂色弧
SOUL = U.SOUL


# ============================================================== 心法


def em_xunfeng(P):
    """迅锋：一支羽箭斜向右上疾飞，柳叶钢镞一线寒光，箭身两旁拖着几道金色的疾痕（飞得快、飞得远）。"""
    fr = Fr(31.5, 33.0, -30.0, 1.0)
    gold = mixc(EL_INK["metal"], GOLD_DK, 0.3)
    for v, u0, u1, hw, rgb, al in ((-6.2, 7.0, -18.0, 1.35, gold, 0.95), (6.4, 4.0, -20.0, 1.55, gold, 0.95),
                                   (-11.2, -2.0, -15.0, 0.95, mixc(gold, DAN, 0.4), 0.85), (11.4, -4.0, -16.5, 0.95, mixc(gold, DAN, 0.4), 0.85)):
        stroke(P, fr(W.seg_pts((u0, v), (u1, v + 0.2), n=30)), hw * np.linspace(1.0, 0.12, 30) ** 0.8, rgb, al, dry=0.45, dry_start=0.3)
    # 箭羽：上下两片，白羽墨边，下面一片染朱砂
    for sgn, rgb in ((-1.0, mixc(PAPER, WHITE, 0.75)), (1.0, mixc(W_ZHUSHA, ZHUSHA, 0.25))):
        feather = fr(W.catmull_closed([(-11.0, 0.3 * sgn), (-14.0, 3.9 * sgn), (-20.5, 5.4 * sgn), (-19.0, 1.8 * sgn), (-17.0, 0.3 * sgn)], 8))
        _, m = shape(P, feather, rgb, ol=1.0, pool=0.25, pool_rgb=QING if sgn < 0 else ZHUSHA_DK, mottle=0.0, wob=0.03)
        for k in range(3):
            u = -13.5 - 2.3 * k
            stroke(P, fr(W.seg_pts((u, 0.4 * sgn), (u - 2.0, 3.4 * sgn), n=8)), 0.24, DAN if sgn < 0 else ZHUSHA_DK, 0.7, clip=m)
    # 箭杆
    stroke(P, fr(W.seg_pts((-20.0, 0.0), (10.0, 0.0), n=60)), 1.3, mixc(ZHESHI, JIAO, 0.5))
    stroke(P, fr(W.seg_pts((-18.0, -0.45), (8.5, -0.45), n=60)), 0.4, mixc(W_ZHESHI, PAPER, 0.3), 0.8)
    # 箭镞：柳叶形钢镞，一亮一暗两面、中脊一线
    head = fr(W.catmull_closed([(8.0, 0.0), (10.5, -4.0), (15.5, -4.4), (22.5, 0.0), (15.5, 4.4), (10.5, 4.0)], 8))
    _, Vv = fr.uv(P)
    steel_hi = mixc(mixc(PAPER, WHITE, 0.7), QING, 0.12)
    steel_lo = mixc(mixc(QING, HUAQING, 0.4), ZHONG, 0.5)
    d, t = P.sdf(W.wobble(head, P.rng, 0.03, spacing=0.3))
    P.fill(d, mixc(steel_hi, steel_lo, smoothstep(-0.2, 0.2, Vv)), pool=0.25, pool_rgb=mixc(HUAQING, JIAO, 0.4), pool_w=0.6)
    m = P.cover(d)
    stroke(P, fr(W.seg_pts((9.5, 0.0), (21.0, 0.0), n=20)), 0.4, mixc(HUAQING, JIAO, 0.5), 0.9, clip=m)
    stroke(P, fr(W.seg_pts((11.5, -2.6), (18.5, -1.4), n=20)), 0.45, WHITE, 0.9, clip=m)
    P.outline(d, t, OL * 1.15, INK_LINE, jitter=0.15)
    stroke(P, fr(W.seg_pts((7.4, -2.2), (7.6, 2.2), n=8)), 0.85, mixc(TENG, GOLD_DK, 0.3))
    tx, ty = fr.pt(22.5, 0.0)
    glow(P, tx, ty, 5.5, mixc(TENG, WHITE, 0.5), 0.75)
    sparkle(P, tx, ty, 4.4, mixc(TENG, WHITE, 0.2), 0.6)
    P.dot(tx, ty, 0.8, WHITE)


def em_huichun(P):
    """回春：一株灵芝，两朵扇形的芝盖（赭红、一圈圈年轮、边上一道嫩黄），芝柄从侧边长出，脚下一丛新绿，四周几点青碧的生气。"""
    glow(P, 32.0, 30.0, 16.0, mixc(W_SHILV, PAPER, 0.35), 0.55)
    green = mixc(EL_INK["wood"], SHILV, 0.4)
    for (x, y, r) in ((15.5, 17.5, 0.75), (47.5, 16.0, 0.65), (50.0, 30.5, 0.55), (13.5, 33.0, 0.5)):
        sparkle(P, x, y, 2.4 + r, mixc(green, WHITE, 0.25), 0.45)
    stem_c = mixc(ZHESHI, JIAO, 0.35)
    stroke(P, V.bezier([(31.0, 48.0), (28.5, 42.0), (31.5, 36.0), (28.5, 29.5)], 40), np.linspace(1.7, 1.15, 40), stem_c)
    stroke(P, V.bezier([(33.5, 48.0), (36.5, 45.0), (38.0, 42.5), (38.5, 39.5)], 30), np.linspace(1.4, 1.0, 30), stem_c)

    def cap(ax, ay, R, a0, a1, squash, rings):
        """芝盖：以芝柄顶 (ax, ay) 为心的扇形，外缘起伏如云头，年轮是同心的弧。"""
        th = np.linspace(a0, a1, 70)
        wav = 1.0 + 0.06 * np.sin((th - a0) / (a1 - a0) * math.pi * 5.0) ** 2
        rim = np.stack([ax + R * wav * np.cos(th), ay + squash * R * wav * np.sin(th)], -1)
        poly = np.vstack([rim, [[ax + 1.2 * math.cos(a1 + 0.6), ay + 1.2], [ax + 1.2 * math.cos(a0 - 0.6), ay + 1.2]]])
        rn = np.hypot((P.X - ax) / R, (P.Y - ay) / (squash * R))
        base = mixc(mixc(ZHUSHA, ZHESHI, 0.5), ZHUSHA_DK, 0.25 + 0.35 * smoothstep(0.2, 0.9, rn))
        rgb = mixc(base, mixc(TENG, W_TENG, 0.35), smoothstep(0.8, 0.97, rn))
        _, m = shape(P, poly, rgb, ol=OL, ol_rgb=mixc(ZHUSHA_DK, JIAO, 0.55), pool=0.2, pool_rgb=ZHUSHA_DK, mottle=0.08, mottle_rgb=ZHUSHA_DK)
        for k in rings:
            tt = np.linspace(a0 + 0.12, a1 - 0.12, 40)
            arc = np.stack([ax + k * R * np.cos(tt), ay + squash * k * R * np.sin(tt)], -1)
            stroke(P, arc, 0.42 * W.brush_profile(40, 0.4, 0.4, 0.2), mixc(ZHUSHA_DK, JIAO, 0.35), 0.8, clip=m)
        a_m = 0.5 * (a0 + a1) - 0.35
        hl = [(ax + k * R * math.cos(a_m + o), ay + squash * k * R * math.sin(a_m + o)) for k, o in ((0.55, -0.35), (0.72, -0.05), (0.62, 0.3))]
        stroke(P, V.bezier(hl, 20), 0.75 * W.brush_profile(20, 0.4, 0.3), mixc(W_TENG, WHITE, 0.55), 0.8, clip=m)

    cap(28.5, 29.0, 15.0, math.radians(-178.0), math.radians(-8.0), 0.78, (0.42, 0.64, 0.82))
    cap(38.5, 39.0, 9.5, math.radians(-150.0), math.radians(12.0), 0.7, (0.5, 0.75))
    for (bx, a0, L) in ((25.0, -0.5, 7.5), (27.5, -0.15, 9.0), (36.5, 0.3, 7.5), (40.0, 0.6, 6.0)):
        tip = (bx + L * math.sin(a0), 49.0 - L * math.cos(a0))
        stroke(P, V.bezier([(bx, 49.0), (bx + 0.4 * L * math.sin(a0), 49.0 - 0.6 * L), tip], 20), 0.9 * W.brush_profile(20, 1.0, 0.15, 0.0), mixc(SHILV, JIAO, 0.35))
    leaf(P, 22.0, 45.0, -150.0, 8.0, 3.8, mixc(W_SHILV, green, 0.5))
    leaf(P, 43.0, 46.5, -25.0, 7.5, 3.6, mixc(W_SHILV, green, 0.6))
    stroke(P, V.bezier([(18.5, 50.0), (32.0, 48.5), (45.5, 50.0)], 30), 0.8 * W.brush_profile(30, 0.6, 0.3), mixc(ZHESHI, ZHONG, 0.4), 0.8, dry=0.3, dry_start=0.3)


def em_hanyi(P):
    """寒意：一朵六出冰花，花青墨边、冰白的枝杈，中间一片六角冰晶，背后一团寒气。"""
    cx, cy = 32.0, 32.0
    glow(P, cx, cy, 18.0, mixc(W_HUAQING, WHITE, 0.3), 0.7)
    edge = mixc(HUAQING, JIAO, 0.5)
    ice = mixc(mixc(W_HUAQING, WHITE, 0.55), EL_INK["water"], 0.12)
    arms = []
    for k in range(6):
        a = math.radians(-90.0 + 60.0 * k)
        u = np.array([math.cos(a), math.sin(a)])
        n = np.array([-u[1], u[0]])
        c = np.array([cx, cy])
        arms.append((c + u * 3.0, c + u * 18.0, 2.0 * np.ones(2)))
        for f, L in ((0.45, 6.2), (0.72, 4.4)):
            b = c + u * (3.0 + 15.0 * f)
            for s in (-1.0, 1.0):
                tip = b + (u * 0.75 + n * s * 0.66) * L
                arms.append((b, tip, 1.25 * np.ones(2)))
    for wide in (True, False):
        for p0, p1, hw in arms:
            pts = W.seg_pts(p0, p1, n=16)
            prof = np.interp(np.linspace(0, 1, 16), [0, 0.7, 1.0], [hw[0], hw[0] * 0.85, hw[0] * 0.45])
            stroke(P, pts, prof + (0.75 if wide else 0.0), edge if wide else ice, 1.0)
    for k in range(6):
        a = math.radians(-90.0 + 60.0 * k)
        tx, ty = cx + 19.0 * math.cos(a), cy + 19.0 * math.sin(a)
        shape(P, W.ellipse_pts(tx, ty, 1.9, 1.9, 4, a0=a), ice, ol=0.75, ol_rgb=edge, pool=0.0, mottle=0.0, wob=0.0)
    hexa = W.ellipse_pts(cx, cy, 5.2, 5.2, 6, a0=math.radians(-90.0))
    rr = np.hypot(P.X - cx + 1.5, P.Y - cy + 1.5) / 6.0
    shape(P, hexa, mixc(mixc(W_HUAQING, WHITE, 0.75), mixc(EL_INK["water"], HUAQING, 0.4), smoothstep(0.1, 1.2, rr)), ol=0.9, ol_rgb=edge, pool=0.3, pool_rgb=HUAQING, mottle=0.0, wob=0.02)
    for k in range(6):
        a = math.radians(-90.0 + 60.0 * k)
        stroke(P, W.seg_pts((cx, cy), (cx + 4.2 * math.cos(a), cy + 4.2 * math.sin(a)), n=8), 0.25, mixc(HUAQING, JIAO, 0.2), 0.7)
    P.dot(cx - 1.2, cy - 1.4, 0.9, WHITE)


def em_dengxin(P):
    """灯芯：一盏高足油灯——灯盏里一汪油、一根灯芯搭出盏沿，芯上一朵又高又静的火苗；灯脚下淡淡一圈暖光（照见圈）。"""
    fx, fb, fh, fw = 33.0, 26.4, 18.0, 3.9  # 火苗：底中点、高、最宽处的半宽
    glow(P, fx, fb - 7.5, 15.0, mixc(TENG, PAPER, 0.3), 0.6)
    # 照见圈：灯脚下一圈淡淡的暖光
    dd = np.hypot((P.X - 32.0) / 16.0, (P.Y - 48.0) / 4.2)
    P.lay.over(mixc(mixc(col(S.LANTERN_LIGHT), WHITE, 0.3), PAPER, 0.3), 0.75 * smoothstep(1.0, 0.45, dd))
    stroke(P, V.bezier([(17.5, 49.2), (32.0, 52.6), (46.5, 49.2)], 40), 0.55 * W.brush_profile(40, 0.4, 0.4), mixc(ZHUSHA, TENG, 0.35), 0.8)
    bronze = mixc(mixc(ZHESHI, NONG, 0.45), SHILV, 0.1)
    b_hi, b_lo = mixc(bronze, GOLD_HI, 0.35), mixc(bronze, JIAO, 0.45)
    ol_c = mixc(GOLD_DK, JIAO, 0.55)
    # 灯脚、灯柱（中间一个节）、托盘
    foot = W.catmull_closed([(24.0, 48.6), (26.0, 45.4), (30.6, 44.0), (33.4, 44.0), (38.0, 45.4), (40.0, 48.6), (32.0, 49.6)], 8)
    shape(P, foot, shade_lr(P, 24, 40, b_hi, b_lo), ol=1.1, ol_rgb=ol_c, pool=0.3, pool_rgb=JIAO)
    shape(P, [(30.9, 32.5), (33.1, 32.5), (33.5, 44.6), (30.5, 44.6)], shade_lr(P, 30.5, 33.5, b_hi, b_lo), ol=0.9, ol_rgb=ol_c, pool=0.2, wob=0.02)
    shape(P, W.ellipse_pts(32.0, 39.0, 3.2, 1.5, 30), shade_lr(P, 29, 35, b_hi, b_lo), ol=0.8, ol_rgb=ol_c, pool=0.25, wob=0.02)
    # 灯盏：浅碗，盏沿一道金，里面一汪油
    dish = W.catmull_closed([(20.5, 28.6), (43.5, 28.6), (41.0, 31.6), (36.0, 33.4), (28.0, 33.4), (23.0, 31.6)], 8)
    shape(P, dish, shade_lr(P, 21, 43, b_hi, b_lo), ol=1.15, ol_rgb=ol_c, pool=0.3, pool_rgb=JIAO)
    shape(P, W.ellipse_pts(32.0, 28.6, 11.4, 1.9, 48), mixc(TENG, ZHESHI, 0.4), ol=0.7, ol_rgb=ol_c, pool=0.2, wob=0.02)
    shape(P, W.ellipse_pts(31.5, 28.8, 9.4, 1.15, 40), mixc(mixc(ZHESHI, TENG, 0.35), JIAO, 0.25), ol=0.0, pool=0.3, pool_rgb=mixc(ZHESHI, JIAO, 0.5), mottle=0.0, wob=0.0)
    # 灯芯：一截棉芯泡在油里，头搭出来，烧黑的芯头伸进火苗底
    stroke(P, V.bezier([(24.5, 29.2), (29.0, 29.6), (32.0, 28.6), (fx, fb + 0.3)], 24), 0.75 * W.brush_profile(24, 0.6, 0.7, 0.0), mixc(W_ZHESHI, PAPER, 0.3), 0.95)
    stroke(P, V.bezier([(31.0, 28.9), (32.2, 28.0), (fx, fb - 1.4)], 12), 0.55, JIAO)
    # 火苗：上尖下圆的一滴，直直往上、不摇，外朱砂、里藤黄、芯近白；底下一点暗（贴着芯头）
    ctrl = [(fx, fb), (fx + 0.72 * fw, fb - 0.07 * fh), (fx + fw, fb - 0.24 * fh), (fx + 0.82 * fw, fb - 0.45 * fh),
            (fx + 0.4 * fw, fb - 0.72 * fh), (fx, fb - fh), (fx - 0.4 * fw, fb - 0.72 * fh), (fx - 0.82 * fw, fb - 0.45 * fh),
            (fx - fw, fb - 0.24 * fh), (fx - 0.72 * fw, fb - 0.07 * fh)]
    heat = np.exp(-(((P.X - fx) / (0.9 * fw)) ** 2 + ((P.Y - (fb - 0.3 * fh)) / (0.42 * fh)) ** 2))
    _, m = shape(P, W.catmull_closed(ctrl, 8), V.ramp(np.clip(0.15 + heat, 0, 1), V.FLAME_STOPS), ol=0.8, ol_rgb=mixc(ZHUSHA, JIAO, 0.5),
                 pool=0.3, pool_rgb=ZHUSHA, mottle=0.0, wob=0.02)
    core = [(fx, fb - 1.6), (fx + 0.42 * fw, fb - 0.2 * fh), (fx + 0.3 * fw, fb - 0.42 * fh), (fx, fb - 0.62 * fh), (fx - 0.3 * fw, fb - 0.42 * fh), (fx - 0.42 * fw, fb - 0.2 * fh)]
    shape(P, W.catmull_closed(core, 8), mixc(TENG, WHITE, 0.7), ol=0, pool=0.3, pool_rgb=TENG, mottle=0.0, wob=0.0)
    P.dot(fx, fb - 1.0, 1.0, mixc(ZHUSHA_DK, JIAO, 0.4), 0.8, ry=0.8, clip=m)


def em_zaiwu(P):
    """载物：一只神龟（俯看），背甲赭黄、六角甲纹墨线勾出，四足伸开、昂首，背甲正中一点金。"""
    fr = Fr(32.0, 33.0, -18.0, 1.0)
    skin = mixc(mixc(ZHONG, SHILV, 0.3), DAN, 0.25)
    skin_ol = mixc(JIAO, SHILV, 0.15)
    # 四足、尾、头（先画，背甲压在上面）
    for (u, v, a) in ((9.0, -9.5, -40.0), (9.0, 9.5, 40.0), (-9.0, -9.0, -140.0), (-9.0, 9.0, 140.0)):
        aa = math.radians(a)
        base = (u, v)
        tip = (u + 7.5 * math.cos(aa), v + 7.5 * math.sin(aa))
        shape(P, fr(W.almond(base, tip, 5.6, 24, bulge=0.4)), skin, ol=0.95, ol_rgb=skin_ol, pool=0.3, pool_rgb=JIAO, mottle=0.06)
    shape(P, fr(W.almond((-12.0, 0.0), (-19.0, 0.8), 2.8, 16, bulge=0.3)), skin, ol=0.8, ol_rgb=skin_ol, pool=0.3, pool_rgb=JIAO)
    head = fr(W.catmull_closed([(11.0, -3.0), (16.0, -3.6), (20.5, -2.2), (22.0, 0.0), (20.5, 2.2), (16.0, 3.6), (11.0, 3.0)], 8))
    shape(P, head, skin, ol=1.0, ol_rgb=skin_ol, pool=0.3, pool_rgb=JIAO, mottle=0.05)
    for sgn in (-1.0, 1.0):
        P.dot(*fr.pt(18.6, 1.7 * sgn), 0.7, JIAO)
    # 背甲
    U_, V_ = fr.uv(P)
    shell_l = mixc(mixc(EL_INK["earth"], TENG, 0.3), PAPER, 0.2)
    shell_d = mixc(ZHESHI, JIAO, 0.35)
    rr = np.hypot((U_ + 3.0) / 14.0, (V_ + 3.0) / 12.0)
    rgb = mixc(shell_l, shell_d, smoothstep(0.2, 1.3, rr))
    shell = fr(W.ellipse_pts(0.0, 0.0, 14.0, 11.6, 80))
    d, t = P.sdf(W.wobble(shell, P.rng, 0.05, spacing=0.3))
    P.fill(d, rgb, pool=0.35, pool_rgb=mixc(ZHESHI, JIAO, 0.5), pool_w=1.2, mottle=0.06, mottle_rgb=ZHESHI)
    m = P.cover(d)
    seam = mixc(ZHESHI, JIAO, 0.6)
    # 甲纹：脊上一列三块六角（相邻两块共一条边），从六角的角上往外分出肋甲，外圈一道缘甲
    sp, hr = 6.4, 3.7  # 六角的间距、外接圆半径（平边朝脊的方向）
    for k in (-1, 0, 1):
        hx = fr(W.ellipse_pts(k * sp, 0.0, hr, hr * 1.05, 6, a0=math.radians(30.0)))
        stroke(P, V.arc_resample(np.vstack([hx, hx[:1]]), 60), 0.55, seam, 0.95, clip=m)
    for k in (-1.5, -0.5, 0.5, 1.5):  # 肋甲的缝：从相邻两块六角的公共边的端点往外到缘甲
        u0 = k * sp
        for sgn in (-1.0, 1.0):
            v0 = sgn * hr * 1.05 * 0.5
            stroke(P, fr(W.seg_pts((u0, v0), (u0 * 1.22, sgn * 9.0), n=12)), 0.5, seam, 0.9, clip=m)
    rim = fr(W.ellipse_pts(0.0, 0.0, 11.4, 9.2, 80))
    stroke(P, V.arc_resample(np.vstack([rim, rim[:1]]), 120), 0.5, seam, 0.85, clip=m)
    for a in np.linspace(0, 2 * math.pi, 14, endpoint=False) + 0.1:
        p0 = (11.4 * math.cos(a), 9.2 * math.sin(a))
        p1 = (14.2 * math.cos(a), 11.8 * math.sin(a))
        stroke(P, fr(W.seg_pts(p0, p1, n=8)), 0.35, seam, 0.75, clip=m)
    stroke(P, fr(V.bezier([(-9.0, -5.5), (-4.0, -8.6), (2.0, -8.8)], 20)), 0.8 * W.brush_profile(20, 0.4, 0.3), mixc(W_TENG, WHITE, 0.5), 0.75, clip=m)
    P.outline(d, t, OL * 1.15, INK_LINE, jitter=0.2)
    gx, gy = fr.pt(0.0, 0.0)
    P.dot(gx, gy, 1.4, mixc(TENG, GOLD_HI, 0.3))
    P.dot(gx - 0.4, gy - 0.4, 0.5, WHITE)


def paint_figure(P, ox, oy, s, rgb, alpha, sash=True):
    """腾空的人影（向右飞身）：头、前倾的身子、一腿前蹬一腿后踢、两臂张开，腰间一条飘带。"""
    def q(x, y):
        return (ox + s * x, oy + s * y)

    hw = 1.7 * s
    torso = V.bezier([q(2.0, -9.0), q(0.5, -5.0), q(-1.5, -1.0)], 20)
    stroke(P, torso, np.linspace(hw * 1.25, hw * 1.05, 20), rgb, alpha)
    for ctrl, w0 in (((q(-1.5, -1.0), q(3.5, 1.0), q(7.5, 5.0)), hw), ((q(-1.5, -1.0), q(-6.0, 0.0), q(-9.5, 4.0)), hw * 0.95),
                     ((q(1.2, -7.0), q(5.5, -8.5), q(9.0, -10.5)), hw * 0.7), ((q(1.2, -7.0), q(-2.5, -6.5), q(-6.5, -8.0)), hw * 0.7)):
        stroke(P, V.bezier(list(ctrl), 20), w0 * W.brush_profile(20, 1.0, 0.55, 0.1), rgb, alpha)
    P.dot(*q(3.6, -12.4), 2.3 * s, rgb, alpha)
    if sash:
        stroke(P, V.bezier([q(-0.5, -3.0), q(-6.0, -6.0), q(-10.0, -2.5), q(-15.5, -5.5)], 30), 0.95 * s * W.brush_profile(30, 1.0, 0.2, 0.0), ZHUSHA, alpha, dry=0.3, dry_start=0.6)


def em_qinggong(P):
    """轻功：一个人影飞身向右，身后两道渐淡的残影；脚下水面两圈涟漪（踏水而过）。"""
    for (rx, ry, al) in ((8.5, 1.6, 0.8), (4.5, 0.9, 0.9)):
        e = W.ellipse_pts(27.0, 46.5, rx, ry, 60)
        stroke(P, V.arc_resample(np.vstack([e, e[:1]]), 80), 0.5, mixc(HUAQING, DAN, 0.3), al)
    stroke(P, W.seg_pts((12.0, 46.8), (17.0, 46.6), n=10), 0.45, DAN, 0.6)
    stroke(P, W.seg_pts((38.0, 46.6), (50.0, 46.8), n=20), 0.45, DAN, 0.6)
    paint_figure(P, 21.5, 34.5, 1.15, mixc(DAN, PAPER, 0.25), 0.5, sash=False)
    paint_figure(P, 27.5, 33.0, 1.18, mixc(ZHONG, DAN, 0.4), 0.68, sash=False)
    paint_figure(P, 35.0, 31.0, 1.28, JIAO, 1.0)
    for (x, y, L) in ((12.5, 22.5, 7.0), (11.5, 30.0, 8.0)):
        stroke(P, W.seg_pts((x, y), (x + L, y - 0.6), n=20), 0.7 * np.linspace(0.2, 1.0, 20), ZHONG, 0.7, dry=0.4, dry_start=0.0)


SOUL_RIM, soul_wisp = U.SOUL_RIM, U.soul_wisp  # 魂火（ui_icons 里的那一份，古灯增益“摄物”也用）


def em_juhun(P):
    """聚魂：一只青瓷魂瓶，几团魂火从左右两边横着飞来、拖着细尾聚进瓶口（不是从瓶里冒出来），瓶口透出冷光。"""
    cel = mixc(mixc(W_SHILV, PAPER, 0.35), QING, 0.15)
    cel_d = mixc(mixc(SHILV, HUAQING, 0.4), ZHONG, 0.35)
    ol_c = mixc(SHILV, JIAO, 0.7)
    dy = 4.0  # 瓶子整体下移，瓶口落在圆心附近
    body = W.catmull_closed([(27.0, 30.5 + dy), (21.5, 34.0 + dy), (19.5, 40.0 + dy), (22.0, 45.5 + dy), (26.5, 48.5 + dy), (37.5, 48.5 + dy), (42.0, 45.5 + dy), (44.5, 40.0 + dy), (42.5, 34.0 + dy), (37.0, 30.5 + dy)], 8)
    rgb = shade_lr(P, 19.0, 45.0, mixc(cel, WHITE, 0.3), cel_d)
    _, m = shape(P, body, rgb, ol=OL, ol_rgb=ol_c, pool=0.3, pool_rgb=cel_d, mottle=0.05, mottle_rgb=cel_d)
    for y in (37.0 + dy, 39.0 + dy):
        stroke(P, V.bezier([(19.5, y), (32.0, y + 2.0), (44.5, y)], 30), 0.35, mixc(SHILV, JIAO, 0.45), 0.7, clip=m)
    stroke(P, V.bezier([(22.8, 36.0 + dy), (21.8, 41.0 + dy), (24.2, 45.5 + dy)], 20), 0.8 * W.brush_profile(20, 0.4, 0.3), WHITE, 0.75, clip=m)
    neck = [(27.5, 26.5 + dy), (36.5, 26.5 + dy), (37.5, 31.0 + dy), (26.5, 31.0 + dy)]
    shape(P, neck, shade_lr(P, 26.0, 38.0, cel, cel_d), ol=1.0, ol_rgb=ol_c, pool=0.25, pool_rgb=cel_d)
    mx, my = 32.0, 26.3 + dy
    shape(P, W.ellipse_pts(mx, my, 6.6, 1.9, 40), mixc(cel, WHITE, 0.2), ol=0.9, ol_rgb=ol_c, pool=0.2, wob=0.02)
    glow(P, mx, my - 0.5, 7.5, mixc(SOUL, WHITE, 0.3), 0.75)
    shape(P, W.ellipse_pts(mx, my + 0.1, 4.4, 1.1, 30), mixc(SOUL, WHITE, 0.55), ol=0.0, pool=0.4, pool_rgb=mixc(SOUL, HUAQING, 0.4), mottle=0.0, wob=0.0)
    # 魂火：左右各一团大的、上方两侧各一团小的，圆头都朝着瓶口，尾巴往两边横着拖（左右对称，不是一个方向转的风车）
    for ctrl, rb in ((((21.5, 28.5), (16.5, 26.6), (13.5, 23.0), (10.8, 24.2)), 3.1),
                     (((42.5, 27.8), (47.5, 26.0), (50.0, 22.6), (52.8, 23.6)), 2.9),
                     (((26.0, 20.0), (21.8, 18.8), (19.2, 15.6), (16.4, 16.4)), 2.1),
                     (((38.2, 19.2), (42.4, 18.0), (44.6, 14.8), (47.4, 15.6)), 1.9)):
        soul_wisp(P, ctrl, rb)
    for (x, y, r) in ((16.0, 37.5, 0.7), (48.0, 36.0, 0.6), (33.5, 12.5, 0.6)):  # 远处几点还没聚过来的魂
        P.dot(x, y, r + 0.45, SOUL_RIM, 0.8)
        P.dot(x, y, r, mixc(SOUL, WHITE, 0.5))


# ============================================================== 夜签


def em_omen_wuyue(P):
    """无月：圈里一片墨夜，右上一轮看不见的黑月（只剩一道淡淡的月边），左下一盏灯照出一小圈暖光，圈外暗处两点妖眼。"""
    r = np.hypot(P.X - C, P.Y - C)
    inside = smoothstep(23.4, 22.6, r)
    n = V.noise1(P.rng, P.X.shape, 4.0 * P.ss)
    night = mixc(mixc(JIAO, HUAQING, 0.12), mixc(NONG, HUAQING, 0.2), np.clip(0.5 + 0.25 * n + 0.25 * smoothstep(10.0, 54.0, P.Y), 0, 1))
    P.lay.over(night, inside * 0.97)
    # 黑月：比夜还黑的一轮，边上一线淡光
    mx, my, mr = 40.5, 21.5, 6.6
    dm = np.hypot(P.X - mx, P.Y - my)
    P.lay.over(mixc(JIAO, NONG, 0.1), smoothstep(mr + P.aa, mr - P.aa, dm))
    th = np.arctan2(P.Y - my, P.X - mx)
    rim_w = 0.42 + 0.3 * smoothstep(0.0, 1.0, np.cos(th - math.radians(-140.0)))
    P.lay.over(mixc(DAN, QING, 0.4), 0.85 * smoothstep(rim_w + P.aa, rim_w - P.aa, np.abs(dm - mr)))
    # 一圈灯光：中心暖白、边上收得很快（照见圈外什么都看不见）
    lx, ly, lr = 27.0, 38.0, 10.5
    dl = np.hypot((P.X - lx) / 1.0, (P.Y - ly) / 0.82)
    lit = smoothstep(lr + 0.6, lr - 2.4, dl) * inside
    P.lay.over(mixc(col(S.LANTERN_LIGHT), PAPER, 0.25), lit * 0.95)
    P.lay.over(mixc(TENG, WHITE, 0.55), 0.6 * np.exp(-((dl / 4.5) ** 2)) * inside)
    P.lay.over(mixc(col(S.LANTERN_LIGHT), ZHESHI, 0.4), 0.8 * smoothstep(0.9, 0.0, np.abs(dl - lr + 0.3)) * inside)
    stroke(P, V.bezier([(17.5, 43.5), (27.0, 42.2), (36.5, 43.5)], 30), 0.5 * W.brush_profile(30, 0.4, 0.3), mixc(ZHESHI, ZHONG, 0.3), 0.7)
    U.paint_lantern(P, lx, ly - 1.2, 0.42)
    # 暗处的妖眼
    for (ex, ey) in ((43.5, 35.0), (47.5, 35.6)):
        eye = W.almond((ex - 1.3, ey + 0.3), (ex + 1.3, ey - 0.3), 1.2, 16, bulge=0.5)
        shape(P, eye, mixc(ZHUSHA, TENG, 0.35), ol=0, pool=0.0, mottle=0.0, wob=0.0)
        glow(P, ex, ey, 2.6, mixc(ZHUSHA, PAPER, 0.2), 0.25)
    for (x, y, rr) in ((19.0, 18.5, 0.4), (25.5, 14.0, 0.35), (30.0, 20.5, 0.3)):
        P.dot(x, y, rr, mixc(DAN, QING, 0.5), 0.8)


def em_omen_nike(P):
    """逆克：五行相克的五角星，每条边上一个朱砂箭头倒着指（克反过来）；外面相生的环断成几截（相生无效）。"""
    cx, cy, R = 32.0, 33.0, 16.0
    order = ["fire", "earth", "metal", "water", "wood"]  # 外圈相生的顺序（火在上，顺时针）
    pos = []
    for k in range(5):
        a = math.radians(-90.0 + 72.0 * k)
        pos.append(np.array([cx + R * math.cos(a), cy + R * math.sin(a)]))
    # 断开的相生环
    th = np.linspace(0, 2 * math.pi, 400)
    ring = np.stack([cx + R * np.cos(th), cy + R * np.sin(th)], -1)
    for k in range(5):
        a0 = -90.0 + 72.0 * k + 15.0
        seg = (np.degrees(th) >= (a0 % 360.0)) & (np.degrees(th) <= ((a0 + 30.0) % 360.0 or 360.0))
        pts = ring[seg]
        if len(pts) > 4:
            stroke(P, pts, 0.55 * W.brush_profile(len(pts), 0.4, 0.4, 0.2), mixc(DAN, QING, 0.3), 0.8, dry=0.3, dry_start=0.3)
    # 相克的五角星：火→金→木→土→水→火（隔一个连一个）
    for k in range(5):
        a, b = pos[k], pos[(k + 2) % 5]
        stroke(P, W.seg_pts(a, b, n=40), 1.25 * W.brush_profile(40, 1.0, 0.75, 0.1), JIAO, 1.0, jitter=0.05)
    for k in range(5):
        a, b = pos[k], pos[(k + 2) % 5]
        u = (a - b) / np.linalg.norm(a - b)  # 反着指：从被克的一方指回克它的一方
        nv = np.array([-u[1], u[0]])
        tip = a - u * 6.2
        for s in (-1.0, 1.0):
            stroke(P, W.seg_pts(tip - u * 3.4 + nv * s * 2.6, tip, n=10), np.linspace(0.5, 0.95, 10), ZHUSHA, 1.0, jitter=0.0)
    for k, el in enumerate(order):
        x, y = pos[k]
        rad = 3.6
        rr = np.hypot((P.X - x + 0.35 * rad) / rad, (P.Y - y + 0.35 * rad) / rad)
        rgb = mixc(mixc(EL_INK[el], WHITE, 0.3), mixc(EL_INK[el], JIAO, 0.3), smoothstep(0.2, 1.4, rr))
        shape(P, W.ellipse_pts(x, y, rad, rad, 40), rgb, ol=1.0, ol_rgb=mixc(EL_INK[el], JIAO, 0.65), pool=0.35, pool_rgb=mixc(EL_INK[el], JIAO, 0.3), mottle=0.0, wob=0.03)
        P.dot(x - 0.35 * rad, y - 0.35 * rad, 0.22 * rad, WHITE, 0.85)


# ============================================================== 货币、奇遇


def em_gold(P):
    """金币：一枚方孔金钱正面立着，后面斜摞着一小叠，钱面四个字的位置各一笔凸起。"""
    glow(P, 33.0, 33.0, 17.0, mixc(TENG, PAPER, 0.45), 0.45)
    for k in range(4):
        y = 46.0 - 2.4 * k
        shape(P, W.ellipse_pts(43.0, y + 0.9, 7.6, 2.9, 40), mixc(TENG, GOLD_DK, 0.6), ol=0.85, ol_rgb=mixc(GOLD_DK, JIAO, 0.5), pool=0.2, mottle=0.0, wob=0.02)
        coin(P, 43.0, y, 7.6, ry=2.9, ol=0.85)
    cx, cy, r = 28.5, 33.0, 14.0
    m = coin(P, cx, cy, r, ol=OL * 1.15)
    for (dx, dy, horiz) in ((0.0, -1.0, True), (0.0, 1.0, True), (-1.0, 0.0, False), (1.0, 0.0, False)):
        x, y = cx + dx * 0.5 * r, cy + dy * 0.5 * r
        L = 0.13 * r
        p0, p1 = ((x - L, y), (x + L, y)) if horiz else ((x, y - L), (x, y + L))
        stroke(P, W.seg_pts(p0, p1, n=8), 0.55, GOLD_DK, 0.85, clip=m)
    stroke(P, V.bezier([(cx - 0.62 * r, cy + 0.25 * r), (cx - 0.68 * r, cy - 0.3 * r), (cx - 0.25 * r, cy - 0.66 * r)], 30), 0.9 * W.brush_profile(30, 0.4, 0.3), WHITE, 0.8, clip=m)
    sparkle(P, cx + 0.62 * r, cy - 0.66 * r, 3.6, mixc(TENG, WHITE, 0.3), 0.55)


def em_enc_merchant(P):
    """货郎：一根扁担挑着两头货（左边带抽屉的货箱、右边一只竹筐，筐里插一面拨浪鼓），扁担中间挂一盏小灯笼。"""
    pole = V.bezier([(13.5, 19.5), (32.0, 22.5), (50.5, 19.5)], 60)
    for x0, x1 in ((20.0, 19.5), (44.5, 45.0)):
        for dx in (-2.4, 2.4):
            stroke(P, W.seg_pts((x0, 20.8), (x1 + dx, 31.5), n=16), 0.32, NONG, 0.9)
    U.paint_lantern(P, 32.0, 29.0, 0.36)
    stroke(P, W.seg_pts((32.0, 22.0), (32.0, 24.4), n=8), 0.3, NONG)
    # 货箱：三面，正面两层抽屉，铜拉手
    wood = mixc(W_ZHESHI, ZHESHI, 0.45)
    masks = U.paint_box(P, 13.0, 33.0, 12.0, 13.5, 3.5, 2.5, wood, ol=1.1)
    for y in (37.5, 42.0):
        stroke(P, W.seg_pts((13.5, y), (24.5, y), n=16), 0.35, mixc(ZHESHI, JIAO, 0.5), 0.9, clip=masks[1])
        P.dot(19.0, y - 2.2, 0.6, TENG, clip=masks[1])
    P.dot(19.0, 44.2, 0.6, TENG, clip=masks[1])
    shape(P, [(15.0, 31.6), (19.0, 30.4), (19.6, 32.2), (15.6, 33.4)], ZHUSHA, ol=0.4, ol_rgb=ZHUSHA_DK, pool=0.2, pool_rgb=ZHUSHA_DK, wob=0.0)
    # 竹筐：竹编的横纹，筐口露出几样货（布匹、小瓷瓶）
    shape(P, W.ellipse_pts(42.5, 33.6, 6.2, 2.0, 30), mixc(W_ZHUSHA, ZHUSHA, 0.4), ol=0.6, pool=0.2, pool_rgb=ZHUSHA_DK, wob=0.02)
    shape(P, W.catmull_closed([(46.5, 33.6), (48.4, 30.6), (50.0, 33.2)], 6), mixc(W_HUAQING, QING, 0.3), ol=0.6, pool=0.2, wob=0.02)
    basket = W.catmull_closed([(36.0, 34.0), (50.0, 34.0), (49.0, 41.0), (47.0, 46.5), (39.0, 46.5), (37.0, 41.0)], 6)
    bam = mixc(W_TENG, ZHESHI, 0.35)
    _, m = shape(P, basket, shade_lr(P, 36.0, 50.0, mixc(bam, PAPER, 0.25), mixc(bam, ZHONG, 0.35)), ol=1.1, pool=0.3, pool_rgb=ZHESHI)
    for y in (37.0, 40.0, 43.0):
        stroke(P, W.seg_pts((35.5, y), (50.5, y), n=20), 0.3, mixc(ZHESHI, JIAO, 0.45), 0.8, clip=m)
    for x in np.arange(38.0, 50.0, 2.6):
        stroke(P, W.seg_pts((x, 34.0), (x - 0.4, 46.5), n=12), 0.22, mixc(ZHESHI, JIAO, 0.3), 0.55, clip=m)
    stroke(P, W.seg_pts((36.0, 34.0), (50.0, 34.0), n=20), 0.6, mixc(ZHESHI, JIAO, 0.4))
    # 拨浪鼓：插在筐边，一根柄、扁圆的鼓、两粒弹丸
    stroke(P, W.seg_pts((48.0, 35.0), (50.5, 27.5), n=12), 0.45, mixc(ZHESHI, JIAO, 0.3))
    shape(P, W.ellipse_pts(51.0, 25.6, 2.2, 2.6, 30), ZHUSHA, ol=0.6, ol_rgb=ZHUSHA_DK, pool=0.3, pool_rgb=ZHUSHA_DK, wob=0.02)
    P.dot(51.0, 25.6, 1.2, mixc(PAPER, WHITE, 0.5))
    for sx in (-1.0, 1.0):
        stroke(P, W.seg_pts((51.0 + sx * 2.0, 25.6), (51.0 + sx * 3.4, 27.4), n=8), 0.15, NONG)
        P.dot(51.0 + sx * 3.4, 27.6, 0.55, JIAO)
    # 扁担：竹色，压在绳上
    stroke(P, pole, 1.45, mixc(ZHESHI, JIAO, 0.45))
    stroke(P, pole[3:-3] + [0.0, -0.35], 0.7, mixc(W_TENG, ZHESHI, 0.4), 0.95)
    for x in (24.0, 40.0):
        P.dot(x, 21.6 - 0.0, 0.45, mixc(ZHESHI, JIAO, 0.6))


# ============================================================== 精英词缀（小图标）


def small_painter(seed: int) -> W.Painter:
    """32 像素（1 倍）的画布，网格坐标乘 2，仍按 64×64 的设计坐标画。"""
    P = W.Painter(32, 32, seed, ss=U.SS * 2)
    P.X = P.X * 2.0
    P.Y = P.Y * 2.0
    P.aa = P.aa * 2.0
    return P


def small_ring_front(P: W.Painter, arc_rgb):
    """小图标的框：色弧更粗、墨圈更粗（缩到 24 像素仍是一整圈），一笔圆相、收笔飞白。"""
    r = np.hypot(P.X - C, P.Y - C)
    th = np.mod(np.arctan2(P.Y - C, P.X - C), 2 * math.pi)
    a0, span = math.radians(25.0), math.radians(235.0)
    ta = np.mod(th - a0, 2 * math.pi) / span
    hwa = 1.6 * np.sin(np.pi * np.clip(ta, 0, 1)) ** 0.6 * (ta <= 1)
    arc = smoothstep(hwa + P.aa, hwa - P.aa, np.abs(r - 23.6)) * (hwa > 0.05)
    P.lay.over(arc_rgb, 0.95 * arc)
    th0, span2 = math.radians(-38.0), math.radians(336.0)
    rel = np.mod(th - th0 + math.radians(8.0), 2 * math.pi) - math.radians(8.0)
    t = rel / span2
    tc = np.clip(t, 0, 1)
    R = 27.6 + 0.6 * tc
    hw = np.interp(tc, [0.0, 0.05, 0.5, 0.9, 1.0], [2.9, 3.1, 2.7, 2.1, 0.6])
    over = np.where(t < 0, -t * span2 * 28.0, 0.0)
    over = np.where(t > 1.0, 1e3, over)
    dist = np.hypot(r - R, over)
    cov = smoothstep(hw + P.aa, hw - P.aa, dist)
    tex = W.ptex(P.rng, ns=12, nt=256, along=6.0, across=0.6)
    b = W.sample_ptex(tex, np.clip((r - R) / np.maximum(hw, 0.3), -1, 1), tc * 0.999)
    dry = 0.45 * smoothstep(0.82, 1.0, tc) + 0.04
    cov = cov * smoothstep(dry - 0.07, dry + 0.07, b)
    P.lay.over(mixc(JIAO, NONG, 0.3 * (1 - b) * tc), cov)


def af_ji(P):
    """疾：两道浓墨的箭头折笔（»）向右，身后三道疾风。"""
    for (y, x0, L, hw, rgb) in ((22.5, 11.5, 12.0, 1.5, ZHONG), (32.0, 9.5, 13.0, 2.0, mixc(EL_INK["wood"], JIAO, 0.35)), (41.5, 11.5, 12.0, 1.5, ZHONG)):
        stroke(P, W.seg_pts((x0, y), (x0 + L, y), n=20), hw * np.linspace(0.15, 1.0, 20) ** 0.7, rgb, 0.95, dry=0.4, dry_start=0.0)
    for x0 in (26.0, 37.0):
        for (y0, y1) in ((19.5, 32.0), (44.5, 32.0)):
            stroke(P, W.seg_pts((x0, y0), (x0 + 10.0, y1), n=24), 3.0 * W.brush_profile(24, 1.0, 0.85, 0.1), JIAO, 1.0, jitter=0.05)


def af_jian(P):
    """坚：一面铁盾，青灰的盾面一亮一暗，中间一道凸脊、四颗铆钉，盾缘一圈重墨。"""
    poly = W.catmull_closed([(32.0, 13.5), (40.0, 16.5), (46.0, 17.0), (45.5, 30.0), (41.5, 41.0), (32.0, 50.0), (22.5, 41.0), (18.5, 30.0), (18.0, 17.0), (24.0, 16.5)], 8)
    iron_l = mixc(mixc(QING, PAPER, 0.5), W_HUAQING, 0.25)
    iron_d = mixc(mixc(ZHONG, HUAQING, 0.25), JIAO, 0.25)
    rgb = mixc(iron_l, iron_d, smoothstep(30.0, 34.0, P.X))
    _, m = shape(P, poly, rgb, ol=OL * 1.9, ol_rgb=JIAO, pool=0.35, pool_rgb=mixc(HUAQING, JIAO, 0.5), mottle=0.06)
    stroke(P, W.seg_pts((32.0, 16.0), (32.0, 47.0), n=30), 1.3, mixc(TENG, GOLD_DK, 0.3), 1.0, clip=m)
    for (x, y) in ((24.5, 22.0), (39.5, 22.0), (25.5, 36.0), (38.5, 36.0)):
        P.dot(x, y, 1.5, mixc(TENG, GOLD_DK, 0.35), clip=m)
    stroke(P, V.bezier([(22.0, 20.0), (21.5, 30.0), (25.0, 40.0)], 20), 1.1 * W.brush_profile(20, 0.4, 0.3), WHITE, 0.8, clip=m)


def af_fen(P):
    """分：上面一只墨团妖物被一道锯齿裂缝劈成两半（缝里透出朱砂），下面迸出四只小的（各有两点白眼）。"""
    cx = 32.0
    body = W.catmull_closed([(32.0, 12.5), (40.0, 15.0), (44.0, 22.0), (43.5, 30.5), (39.5, 34.0), (32.0, 35.0), (24.5, 34.0), (20.5, 30.5), (20.0, 22.0), (24.0, 15.0)], 8)
    crack = np.array([(32.5, 10.0), (30.5, 16.0), (34.0, 21.0), (30.0, 26.5), (33.0, 31.0), (31.5, 37.0)])
    d0, _ = P.sdf(body)
    inside = smoothstep(1.2, -0.4, d0)
    stroke(P, V.arc_resample(crack, 40), 2.0, mixc(ZHUSHA, W_ZHUSHA, 0.2), 0.95, jitter=0.0, clip=inside)
    cl = V.arc_resample(crack, 120)
    for sgn in (-1.0, 1.0):
        # 半边：用裂缝把身子切开，两半各往外挪一点
        off = np.array([sgn * 1.5, 0.0])
        cut = np.vstack([cl, [[cx + sgn * 30.0, 40.0], [cx + sgn * 30.0, 6.0]]])
        dc, _ = P.sdf(cut + off, pad=30.0)
        db, tb = P.sdf(W.wobble(body + off, P.rng, 0.05, spacing=0.3))
        d = np.maximum(db, dc + 0.8)
        P.fill(d, mixc(mixc(ZHONG, NONG, 0.3), JIAO, smoothstep(14.0, 36.0, P.Y) * 0.6), pool=0.35, pool_rgb=JIAO, pool_w=1.0)
        P.outline(d, tb, OL * 1.5, JIAO, jitter=0.2)
        P.dot(cx + sgn * 5.2 + off[0], 21.5, 1.5, mixc(PAPER, WHITE, 0.6), ry=1.1)
    for k, (x, y) in enumerate(((18.0, 43.5), (27.0, 47.5), (37.0, 47.5), (46.0, 43.5))):
        dx = (x - cx) / 14.0
        stroke(P, W.seg_pts((cx + dx * 4.0, 37.5), (x - dx * 2.5, y - 5.0), n=10), np.linspace(0.2, 0.6, 10), ZHONG, 0.7)
        small = W.catmull_closed([(x, y - 4.0), (x + 3.2, y - 1.6), (x + 3.0, y + 2.6), (x, y + 3.4), (x - 3.0, y + 2.6), (x - 3.2, y - 1.6)], 6)
        shape(P, small, mixc(NONG, JIAO, 0.35), ol=1.0, ol_rgb=JIAO, pool=0.2, pool_rgb=JIAO, mottle=0.0, wob=0.03)
        for sx in (-1.0, 1.0):
            P.dot(x + sx * 1.2, y - 0.6, 0.65, mixc(PAPER, WHITE, 0.6))


def af_zhao(P):
    """召：地上一圈紫色的召唤阵（两道圆、阵上一圈符点），阵外围着六个小影妖（墨团、两点白眼）。"""
    pur = U.ACC_INK["rift"]
    cx, cy = 32.0, 32.0
    for rad, hw in ((9.5, 1.1), (6.0, 0.7)):
        e = W.ellipse_pts(cx, cy, rad, rad, 80)
        stroke(P, V.arc_resample(np.vstack([e, e[:1]]), 120), hw, pur, 1.0)
    for k in range(8):
        a = math.radians(22.5 + 45.0 * k)
        P.dot(cx + 7.8 * math.cos(a), cy + 7.8 * math.sin(a), 0.7, pur)
    P.dot(cx, cy, 2.4, mixc(pur, WHITE, 0.45))
    for k in range(6):
        a = math.radians(-60.0 + 60.0 * k)
        gx, gy = cx + 16.5 * math.cos(a), cy + 16.5 * math.sin(a)
        ghost = W.catmull_closed([(gx, gy - 5.4), (gx + 4.0, gy - 2.0), (gx + 3.8, gy + 3.6), (gx + 1.4, gy + 2.6), (gx, gy + 4.4), (gx - 1.4, gy + 2.6), (gx - 3.8, gy + 3.6), (gx - 4.0, gy - 2.0)], 6)
        shape(P, ghost, mixc(NONG, JIAO, 0.4), ol=0.9, ol_rgb=JIAO, pool=0.2, pool_rgb=JIAO, mottle=0.0, wob=0.03)
        for sx in (-1.0, 1.0):
            P.dot(gx + sx * 1.5, gy - 1.2, 0.8, mixc(PAPER, WHITE, 0.6))


def af_yin(P):
    """隐：一个影妖的身形，左半边是实的墨，右半边只剩断续的虚线轮廓，往右散成几点淡墨。"""
    ghost = W.catmull_closed([(32.0, 12.5), (41.0, 16.0), (45.0, 25.0), (44.5, 36.0), (46.0, 46.5), (41.0, 43.0), (37.0, 48.0), (32.0, 44.0), (27.0, 48.0), (23.0, 43.0), (18.0, 46.5), (19.5, 36.0), (19.0, 25.0), (23.0, 16.0)], 8)
    d, t = P.sdf(W.wobble(ghost, P.rng, 0.05, spacing=0.3))
    left = smoothstep(33.5, 30.5, P.X)
    P.fill(d, mixc(mixc(ZHONG, NONG, 0.4), JIAO, smoothstep(14.0, 50.0, P.Y) * 0.5), pool=0.3, pool_rgb=JIAO, pool_w=0.8, clip=left)
    P.outline(d, t, OL * 1.6, JIAO, jitter=0.2, clip=left)
    dash = (np.mod(t * 26.0, 1.0) < 0.55).astype(np.float64)
    P.outline(d, t, OL * 1.3, mixc(ZHONG, DAN, 0.3), jitter=0.1, clip=(1.0 - left) * dash)
    P.fill(d, DAN, 0.18, clip=1.0 - left)
    for ex in (26.0, 37.5):
        eye = W.almond((ex - 3.0, 26.5), (ex + 3.0, 26.0), 3.6, 20, bulge=0.5)
        shape(P, eye, mixc(PAPER, WHITE, 0.6) if ex < 32 else mixc(DAN, PAPER, 0.3), ol=0.0 if ex < 32 else 0.7, ol_rgb=ZHONG, pool=0.0, mottle=0.0, wob=0.0)
    for (x, y, r) in ((48.5, 24.0, 1.0), (50.0, 31.0, 0.8), (48.0, 38.0, 0.7)):
        P.dot(x, y, r, DAN, 0.85)


def af_kuang(P):
    """狂：三道爪痕从右上斜撕下来（细长、两头尖），痕里深红、正中一线朱砂亮，痕边焦墨，四周迸出几点火星。"""
    for k, (ox, oy, L) in enumerate(((-7.5, 3.5, 0.88), (0.0, 0.0, 1.0), (7.5, 3.5, 0.88))):
        p0 = np.array([42.0 + ox, 13.0 + oy])
        ctrl = [p0, p0 + np.array([-2.5, 11.0]) * L, p0 + np.array([-10.0, 21.0]) * L, p0 + np.array([-19.0, 28.0]) * L]
        pts = V.bezier(ctrl, 40)
        prof = 2.1 * np.sin(np.pi * np.linspace(0.0, 1.0, 40)) ** 0.9 + 0.08
        stroke(P, pts, prof + 0.85, JIAO, 1.0, jitter=0.0)
        stroke(P, pts, prof, mixc(ZHUSHA_DK, JIAO, 0.15), 1.0, jitter=0.0)
        stroke(P, pts[6:34], prof[6:34] * 0.45, mixc(ZHUSHA, TENG, 0.25), 1.0, jitter=0.0)
    for (x, y, r) in ((49.0, 21.0, 1.3), (16.0, 41.0, 1.1), (46.0, 45.0, 1.0), (19.0, 18.5, 0.9)):
        P.dot(x, y, r, mixc(ZHUSHA, TENG, 0.4))


# ============================================================== 灯驿人物（暖的中性色弧）

HUB_ARC = mixc(mixc(ZHESHI, TENG, 0.4), DAN, 0.25)


def em_hub_lampsmith(P):
    """老灯匠：一盏正在扎的灯笼——左半边已糊上红纸，右半边还露着竹骨，前面斜架着一把小锤和一把火钳，迸出两点火星。"""
    bam = mixc(W_ZHESHI, ZHESHI, 0.6)
    cx, cy, rx, ry = 29.5, 29.0, 10.5, 12.0
    glow(P, cx, cy, 13.0, mixc(TENG, PAPER, 0.4), 0.45)
    th = np.linspace(0, 2 * math.pi, 64, endpoint=False)
    body = np.stack([cx + rx * np.sign(np.cos(th)) * np.abs(np.cos(th)) ** 0.8, cy + ry * np.sign(np.sin(th)) * np.abs(np.sin(th)) ** 0.9], -1)
    d, _ = P.sdf(body)
    half = smoothstep(cx + 0.6, cx - 0.6, P.X)  # 左半边糊了纸
    rn = np.hypot((P.X - cx) / rx, (P.Y - cy) / ry)
    P.fill(d, mixc(ZHUSHA, mixc(TENG, WHITE, 0.2), np.exp(-((rn / 0.55) ** 2)) * 0.55), pool=0.35, pool_rgb=ZHUSHA_DK, clip=half)
    for k in (-0.9, -0.45, 0.0, 0.45, 0.9):
        yy = np.linspace(-0.96, 0.96, 40)
        pts = np.stack([cx + k * rx * np.sqrt(1 - yy**2) ** 0.9, cy + ry * yy], -1)
        stroke(P, pts, 0.8 if k else 0.9, mixc(bam, JIAO, 0.45) if k > 0 else ZHUSHA_DK, 1.0)
    P.lay.over(INK_LINE, P.cover(d) * smoothstep(OL * 0.5 + P.aa, OL * 0.5 - P.aa, np.abs(d + 0.4)) * half)
    for y0, hw in ((cy - ry - 0.5, 5.4), (cy + ry - 0.2, 4.6)):
        shape(P, [(cx - hw, y0 - 1.4), (cx + hw, y0 - 1.4), (cx + hw, y0 + 1.4), (cx - hw, y0 + 1.4)], mixc(ZHESHI, NONG, 0.35), ol=0.85, pool=0.3, pool_rgb=JIAO, wob=0.03)
    stroke(P, W.seg_pts((cx, cy - ry - 2.0), (cx, cy - ry - 5.0), n=10), 0.5, INK_LINE)
    # 火钳：两根长腿，钳口夹着一小块烧红的铁
    for sgn in (-1.0, 1.0):
        stroke(P, V.bezier([(19.0, 48.0 + sgn * 0.6), (31.0, 41.0 + sgn * 1.4), (43.0, 32.0 + sgn * 1.8)], 30), 0.8, mixc(NONG, HUAQING, 0.15))
    P.dot(44.0, 31.0, 1.7, mixc(ZHUSHA, TENG, 0.5))
    P.dot(44.0, 31.0, 0.85, mixc(TENG, WHITE, 0.5))
    # 小锤：木柄、铁锤头
    fr = Fr(38.0, 42.0, -55.0, 1.0)
    shape(P, fr([(-9.5, -1.1), (7.0, -1.1), (7.0, 1.1), (-9.5, 1.1)]), mixc(W_ZHESHI, ZHESHI, 0.6), ol=0.9, pool=0.25, wob=0.02)
    shape(P, fr([(6.0, -4.8), (10.2, -4.8), (10.2, 4.8), (6.0, 4.8)]), shade_lr(P, 38, 51, mixc(QING, PAPER, 0.35), mixc(ZHONG, JIAO, 0.3)), ol=1.0, pool=0.3, pool_rgb=JIAO, wob=0.02)
    for (x, y, L) in ((48.5, 23.5, 2.8), (46.0, 18.5, 2.0)):
        sparkle(P, x, y, L, mixc(TENG, ZHUSHA, 0.2), 0.5)


def em_hub_peddler(P):
    """货郎（灯驿）：一面拨浪鼓（扁圆的朱漆鼓、金边、两粒弹丸甩开），地上它的影子却拖出一条毛茸茸的狐尾。"""
    # 影子：地上一抹淡墨，末端卷成狐尾、尾尖留白
    tail = V.bezier([(28.0, 47.5), (38.0, 51.0), (50.0, 47.5), (49.5, 35.0)], 60)
    tt = np.linspace(0, 1, 60)
    hw = np.interp(tt, [0.0, 0.3, 0.75, 1.0], [1.8, 2.8, 4.6, 1.2])
    P.dot(27.0, 47.3, 7.0, mixc(DAN, ZHONG, 0.45), 0.6, ry=2.0)
    d, t = P.sdf(W.wobble(W.ribbon(tail, hw), P.rng, 0.12, spacing=0.3))
    P.fill(d, mixc(ZHONG, DAN, 0.4), 0.85, pool=0.4, pool_rgb=NONG, pool_w=1.0)
    m = P.cover(d)
    P.lay.over(mixc(PAPER, WHITE, 0.4), 0.9 * m * smoothstep(40.5, 37.5, P.Y) * smoothstep(45.0, 47.5, P.X))
    for k in range(6):
        i = int((0.35 + 0.1 * k) * 59)
        stroke(P, W.seg_pts(tail[i] + np.array([-1.0, 0.8]), tail[i] + np.array([1.4, -1.4]), n=8), 0.3, mixc(NONG, ZHONG, 0.3), 0.65, clip=m)
    # 拨浪鼓：柄、扁圆鼓（3/4 看得见鼓身）、两粒弹丸
    stroke(P, W.seg_pts((27.5, 47.0), (26.0, 33.5), n=30), np.linspace(1.4, 1.1, 30), mixc(ZHESHI, JIAO, 0.35))
    cx, cy = 25.5, 23.0
    side = W.catmull_closed([(cx - 1.5, cy - 10.0), (cx + 4.5, cy - 9.6), (cx + 6.0, cy), (cx + 4.5, cy + 9.6), (cx - 1.5, cy + 10.0)], 8)
    shape(P, side, mixc(ZHUSHA, ZHUSHA_DK, 0.45), ol=1.1, ol_rgb=JIAO, pool=0.3, pool_rgb=JIAO)
    for y in (cy - 6.0, cy, cy + 6.0):
        P.dot(cx + 4.9, y, 0.55, TENG)
    rr = np.hypot((P.X - cx + 1.0) / 7.0, (P.Y - cy) / 9.6)
    _, mm = shape(P, W.ellipse_pts(cx - 1.5, cy, 6.6, 9.8, 64), mixc(mixc(W_ZHUSHA, PAPER, 0.3), ZHUSHA, smoothstep(0.1, 1.0, rr)), ol=OL, ol_rgb=ZHUSHA_DK, pool=0.3, pool_rgb=ZHUSHA_DK, mottle=0.05)
    rim = W.ellipse_pts(cx - 1.5, cy, 5.3, 8.3, 64)
    stroke(P, V.arc_resample(np.vstack([rim, rim[:1]]), 80), 0.55, TENG, 0.95, clip=mm)
    gx, gy = cx - 1.5, cy
    stroke(P, W.seg_pts((gx - 2.0, gy - 3.0), (gx + 2.0, gy - 3.0), (gx + 2.0, gy + 3.0), (gx - 2.0, gy + 3.0), (gx - 2.0, gy - 0.5), (gx + 0.6, gy - 0.5), n=40), 0.45, TENG, 0.9, clip=mm)
    for (sx, sy), (ex, ey) in (((cx - 7.0, cy - 2.0), (12.5, 30.0)), ((cx + 5.0, cy - 2.0), (38.0, 31.0))):
        stroke(P, V.bezier([(sx, sy), ((sx + ex) / 2, sy + 1.0), (ex, ey)], 16), 0.32, NONG)
        P.dot(ex, ey, 1.8, JIAO)
        P.dot(ex - 0.5, ey - 0.6, 0.6, mixc(PAPER, WHITE, 0.5))


def paint_rabbit_lantern(P, ox, oy, s):
    """兔子灯（白纸身、朱砂勾的眼和耳、两个小轮、拖绳）：按原 64 设计坐标画，(32, 33) 落在 (ox, oy)，缩放 s。"""
    def q(pts):
        p = np.asarray(pts, dtype=np.float64)
        return np.stack([ox + s * (p[..., 0] - 32.0), oy + s * (p[..., 1] - 33.0)], -1)

    def qp(x, y):
        return (ox + s * (x - 32.0), oy + s * (y - 33.0))

    ol = OL * min(1.0, 0.5 + 0.5 * s)
    glow(P, *qp(32.0, 31.0), 15.0 * s, mixc(col(S.LANTERN_LIGHT), PAPER, 0.35), 0.6)
    stroke(P, V.bezier(q([(9.5, 39.0), (12.0, 44.0), (18.0, 42.5)]), 24), 0.4 * s + 0.1, ZHUSHA, 0.9)
    body = W.catmull_closed(q([(18.0, 36.0), (21.0, 28.0), (29.0, 24.5), (38.0, 25.0), (44.5, 28.5), (47.5, 34.0), (45.0, 41.0), (36.0, 43.0), (25.0, 43.0), (19.0, 41.0)]), 8)
    cx, cy = qp(32.0, 33.0)
    rr = np.hypot((P.X - cx) / (14.0 * s), (P.Y - cy) / (9.0 * s))
    _, m = shape(P, body, mixc(mixc(PAPER, WHITE, 0.85), mixc(col(S.LANTERN_LIGHT), PAPER, 0.3), smoothstep(0.2, 1.0, 1.0 - rr) * 0.8), ol=ol, pool=0.3, pool_rgb=mixc(W_ZHUSHA, PAPER, 0.3), mottle=0.0)
    for k in (-0.5, 0.0, 0.5):
        xs = np.linspace(-0.95, 0.95, 30)
        stroke(P, q(np.stack([32.0 + k * 14.0 + 0 * xs, 33.5 + 8.0 * xs * 0.95], -1)), 0.3 * s, mixc(W_ZHUSHA, ZHUSHA, 0.3), 0.5, clip=m)
    # 头、耳
    head = W.catmull_closed(q([(39.0, 27.0), (43.0, 21.5), (49.0, 21.0), (52.0, 25.0), (50.0, 30.0), (44.0, 31.0)]), 8)
    shape(P, head, mixc(PAPER, WHITE, 0.85), ol=ol, pool=0.25, pool_rgb=mixc(W_ZHUSHA, PAPER, 0.3), mottle=0.0)
    for (base, tip) in (((44.0, 22.0), (40.0, 11.0)), ((47.5, 21.5), (47.0, 10.5))):
        b, t = np.array(qp(*base)), np.array(qp(*tip))
        _, me = shape(P, W.almond(b, t, 4.0 * s, 24, bulge=0.45), mixc(PAPER, WHITE, 0.85), ol=1.0 * min(1.0, 0.5 + 0.5 * s), pool=0.2, pool_rgb=W_ZHUSHA, mottle=0.0)
        stroke(P, W.seg_pts(b + (t - b) * 0.2, b + (t - b) * 0.8, n=12), 0.8 * s, mixc(W_ZHUSHA, ZHUSHA, 0.5), 0.9, clip=me)
    P.dot(*qp(48.0, 24.5), 1.1 * s + 0.1, ZHUSHA)
    P.dot(*qp(51.0, 27.0), 0.6 * s + 0.05, ZHUSHA)
    stroke(P, V.bezier(q([(19.5, 31.0), (16.0, 28.5), (17.0, 25.0)]), 16), 0.9 * s, mixc(W_ZHUSHA, ZHUSHA, 0.4))
    for x in (24.0, 40.0):
        wx, wy = qp(x, 45.0)
        shape(P, W.ellipse_pts(wx, wy, 3.4 * s, 3.4 * s, 30), mixc(ZHUSHA, ZHUSHA_DK, 0.3), ol=0.9 * min(1.0, 0.5 + 0.5 * s), ol_rgb=ZHUSHA_DK, pool=0.2)
        P.dot(wx, wy, 1.0 * s, TENG)


def tally_zheng(P, x0, y0, sz, n, hw, rgb):
    """一个“正”字的前 n 笔（计数用的正字，手写、略斜）：(x0, y0) 是左上角，sz 是字宽。"""
    k = sz / 10.0
    strokes = [((0.6, 0.4), (9.6, 0.0)), ((5.1, 0.2), (5.0, 9.6)), ((5.0, 4.9), (8.8, 4.7)), ((1.6, 5.2), (1.7, 9.6)), ((0.0, 9.8), (10.0, 9.4))]
    for (a, b) in strokes[:n]:
        pa = (x0 + k * a[0], y0 + k * a[1])
        pb = (x0 + k * b[0], y0 + k * b[1])
        stroke(P, W.seg_pts(pa, pb, n=14), hw * W.brush_profile(14, 1.0, 0.5, 0.2), rgb, 0.95, jitter=0.08)


def em_hub_lampboy(P):
    """灯童：门框边上用炭笔记的“正”字（你回来几次，他就在墙上添一道），门口放着他拖着玩的兔子灯。"""
    r = np.hypot(P.X - C, P.Y - C)
    inside = smoothstep(25.0 + P.aa, 25.0 - P.aa, r)
    # 门框：左边一根木柱（出圆的部分藏在墨圈下），柱脚一道门槛
    wood_l, wood_d = mixc(ZHESHI, NONG, 0.35), mixc(ZHESHI, JIAO, 0.6)
    post = [(9.0, 4.0), (17.6, 4.0), (17.0, 60.0), (9.0, 60.0)]
    d, t = P.sdf(W.wobble(post, P.rng, 0.04, spacing=0.3))
    P.fill(d, shade_lr(P, 10.0, 17.5, wood_l, wood_d), pool=0.3, pool_rgb=JIAO, pool_w=0.8, clip=inside)
    for x in (12.0, 14.6):
        stroke(P, W.seg_pts((x, 6.0), (x - 0.2, 58.0), n=40), 0.22, mixc(wood_d, JIAO, 0.4), 0.7, clip=inside * P.cover(d))
    P.outline(d, t, OL, INK_LINE, jitter=0.2, clip=inside)
    stroke(P, W.seg_pts((15.0, 49.6), (50.0, 49.8), n=40), 1.0 * W.brush_profile(40, 0.8, 0.3), mixc(ZHESHI, ZHONG, 0.45), 0.85, clip=inside)
    # 墙上的正字：一个写满，下一个写了两笔（炭笔，浓墨）
    tally_zheng(P, 20.5, 13.5, 8.2, 5, 0.85, JIAO)
    tally_zheng(P, 20.5, 26.5, 8.2, 2, 0.85, JIAO)
    paint_rabbit_lantern(P, 38.5, 37.5, 0.8)


def em_hub_storyteller(P):
    """说书人：一把展开的折扇（扇面上淡墨勾一只白泽的影子），扇下一块醒木。"""
    cx, cy = 32.0, 39.0
    R0, R1 = 6.0, 21.0
    a0, a1 = math.radians(-160.0), math.radians(-20.0)
    th = np.linspace(a0, a1, 60)
    outer = np.stack([cx + R1 * np.cos(th), cy + R1 * np.sin(th)], -1)
    inner = np.stack([cx + R0 * np.cos(th[::-1]), cy + R0 * np.sin(th[::-1])], -1)
    rr = np.hypot(P.X - cx, P.Y - cy)
    _, m = shape(P, np.vstack([outer, inner]), mixc(mixc(PAPER, WHITE, 0.6), PAPER_SH, smoothstep(R1 - 3.0, R1, rr) * 0.5), ol=OL, pool=0.15, pool_rgb=QING, mottle=0.03)
    for k in range(13):
        a = a0 + (a1 - a0) * k / 12
        stroke(P, W.seg_pts((cx + R0 * math.cos(a), cy + R0 * math.sin(a)), (cx + R1 * math.cos(a), cy + R1 * math.sin(a)), n=16), 0.22, DAN, 0.6, clip=m)
    # 扇面上的白泽：淡墨几笔——弓背、昂首、一只角、长尾
    beast = [((22.0, 31.0), (27.0, 27.0), (34.0, 28.0), (39.0, 30.5)), ((39.0, 30.5), (42.0, 27.0), (43.5, 25.0), (45.5, 26.0)),
             ((22.0, 31.0), (19.5, 28.0), (17.5, 27.5), (16.0, 24.5)), ((25.0, 30.5), (24.0, 33.5), (24.5, 35.0), (25.5, 36.0)),
             ((36.0, 30.0), (37.0, 33.0), (37.5, 35.0), (38.5, 36.0)), ((43.5, 25.0), (43.0, 22.0), (44.0, 20.0), (46.0, 19.5))]
    for ctrl in beast:
        stroke(P, V.bezier(list(ctrl), 20), 0.75 * W.brush_profile(20, 0.8, 0.3), mixc(ZHONG, DAN, 0.2), 0.95, clip=m)
    P.dot(44.4, 25.6, 0.5, ZHUSHA, clip=m)
    shape(P, W.ellipse_pts(cx, cy, 2.0, 2.0, 24), mixc(TENG, GOLD_DK, 0.3), ol=0.6, ol_rgb=GOLD_DK, pool=0.3, pool_rgb=GOLD_DK)
    # 醒木
    masks = U.paint_box(P, 22.5, 44.0, 19.0, 5.0, 3.0, 2.2, mixc(ZHESHI, NONG, 0.45), ol=1.1)
    stroke(P, W.seg_pts((25.0, 46.5), (39.5, 46.5), n=20), 0.35, mixc(ZHESHI, W_ZHESHI, 0.5), 0.7, clip=masks[1])
    shape(P, [(27.0, 41.8), (29.5, 41.0), (30.2, 42.6), (27.6, 43.4)], ZHUSHA, ol=0.4, ol_rgb=ZHUSHA_DK, pool=0.2, wob=0.0)


# ============================================================== 灯坠（挂在灯上的坠子：圆底外绕一圈红绳，顶上一个中国结）

CORD = mixc(ZHUSHA, W_ZHUSHA, 0.15)


def charm_cord(P: W.Painter):
    """一圈编成的红绳（墨圈内侧，代替色弧）：两股绞在一起，一明一暗的斜纹。"""
    r = np.hypot(P.X - C, P.Y - C)
    th = np.mod(np.arctan2(P.Y - C, P.X - C) / (2 * math.pi), 1.0)
    band = smoothstep(0.85 + P.aa, 0.85 - P.aa, np.abs(r - 24.2))
    twist = 0.5 + 0.5 * np.sin(2 * math.pi * (th * 64.0 + (r - 24.2) / 1.7 * 0.5))
    P.lay.over(mixc(ZHUSHA_DK, mixc(CORD, W_ZHUSHA, 0.3), twist), 0.95 * band)


def charm_knot(P: W.Painter):
    """顶上的中国结：一个菱形的盘长结（朱砂、编纹）、上面一个小提环，下面两股绳分开接到红绳圈上。"""
    kx, ky, s = C, 5.2, 3.3
    for sgn in (-1.0, 1.0):
        stroke(P, V.bezier([(kx + sgn * 0.6, ky + s * 0.7), (kx + sgn * 2.2, ky + s + 1.0), (kx + sgn * 3.6, 7.9)], 12), 0.55, ZHUSHA_DK)
    loop = W.ellipse_pts(kx, 2.4, 1.3, 1.1, 30)
    stroke(P, V.arc_resample(np.vstack([loop, loop[:1]]), 40), 0.42, ZHUSHA_DK)
    dia = [(kx, ky - s), (kx + s, ky), (kx, ky + s), (kx - s, ky)]
    _, m = shape(P, dia, CORD, ol=0.55, ol_rgb=ZHUSHA_DK, pool=0.3, pool_rgb=ZHUSHA_DK, mottle=0.0, wob=0.0)
    for k in (-0.5, 0.0, 0.5):
        stroke(P, W.seg_pts((kx - s + abs(k) * s, ky + k * s - (s - abs(k) * s) * 0), (kx + k * s * 0 + s * (1 - abs(k)), ky + k * s), n=8), 0.18, mixc(W_ZHUSHA, WHITE, 0.3), 0.7, clip=m)
    for k in (-0.5, 0.5):
        stroke(P, W.seg_pts((kx + k * s - 0.5 * s, ky - 0.5 * s), (kx + k * s + 0.5 * s, ky + 0.5 * s), n=8), 0.18, mixc(W_ZHUSHA, WHITE, 0.3), 0.7, clip=m)
        stroke(P, W.seg_pts((kx + k * s + 0.5 * s, ky - 0.5 * s), (kx + k * s - 0.5 * s, ky + 0.5 * s), n=8), 0.18, mixc(W_ZHUSHA, WHITE, 0.3), 0.7, clip=m)


def ch_wind_wheel(P):
    """风火轮：一对火轮（金圈、八根辐条），轮边裹着火，火舌往后（左）拖。"""
    for (cx, cy, R, al) in ((41.0, 25.0, 8.0, 0.9), (31.0, 37.0, 10.5, 1.0)):
        for k in range(9):
            a = math.radians(70.0 + 24.0 * k)
            b = np.array([cx + R * math.cos(a), cy + R * math.sin(a)])
            tip = b + np.array([-(8.0 + 3.5 * (k % 2)) * R / 10.0, -2.0 - 1.5 * math.sin(a)])
            ctrl = [b + np.array([1.5, 0.0]), b + (tip - b) * 0.5 + np.array([0.0, 2.0]), tip]
            center = V.bezier(ctrl, 24)
            poly = W.ribbon(center, (3.0 * R / 10.0) * (1 - np.linspace(0, 1, 24)) ** 0.8 + 0.05)
            heat = np.exp(-(((P.X - b[0]) ** 2 + (P.Y - b[1]) ** 2) / 12.0))
            shape(P, poly, V.ramp(np.clip(0.2 + 0.8 * heat, 0, 1), V.FLAME_STOPS), ol=0.5, ol_rgb=mixc(ZHUSHA, JIAO, 0.5), pool=0.3, pool_rgb=ZHUSHA, mottle=0.0, wob=0.0, alpha=al)
        ring = W.ellipse_pts(cx, cy, R, R, 80)
        stroke(P, V.arc_resample(np.vstack([ring, ring[:1]]), 120), 2.0 * R / 10.0 + 0.6, mixc(GOLD_DK, JIAO, 0.4), al)
        stroke(P, V.arc_resample(np.vstack([ring, ring[:1]]), 120), 1.5 * R / 10.0 + 0.3, mixc(TENG, GOLD_HI, 0.25), al)
        for k in range(8):
            a = math.radians(22.5 * 2 * k + 10.0)
            stroke(P, W.seg_pts((cx + 1.6 * math.cos(a), cy + 1.6 * math.sin(a)), (cx + (R - 1.0) * math.cos(a), cy + (R - 1.0) * math.sin(a)), n=10), 0.45 * R / 10.0 + 0.2, mixc(ZHUSHA, ZHUSHA_DK, 0.3), al)
        P.dot(cx, cy, 2.0 * R / 10.0 + 0.8, mixc(TENG, GOLD_DK, 0.3), al)
        for k in range(4):
            a = math.radians(45.0 + 90.0 * k)
            P.dot(cx + R * math.cos(a), cy + R * math.sin(a), 0.9 * R / 10.0 + 0.3, ZHUSHA, al)


def ch_pillar(P):
    """定海神针：一根乌铁的棍子竖着插在海浪里，两头金箍，周身一道道回旋的海水。"""
    for k, y0 in enumerate((45.5, 41.0)):
        xs = np.linspace(13.0, 51.0, 80)
        ys = y0 + 1.6 * np.sin(2 * math.pi * (xs - 13.0) / 11.0 + k * 1.8)
        stroke(P, np.stack([xs, ys], -1), (1.3 - 0.25 * k) * W.brush_profile(80, 0.4, 0.3, 0.2), mixc(EL_INK["water"], HUAQING, 0.5 + 0.2 * k), 0.95)
    iron_l, iron_d = mixc(ZHONG, QING, 0.3), mixc(JIAO, HUAQING, 0.1)
    x0, x1, y0, y1 = 28.5, 35.5, 11.0, 46.0
    shape(P, [(x0, y0), (x1, y0), (x1, y1), (x0, y1)], shade_lr(P, x0, x1, iron_l, iron_d), ol=OL, pool=0.3, pool_rgb=JIAO, mottle=0.06, wob=0.03)
    for (ya, yb) in ((11.0, 17.0), (39.0, 44.5)):
        shape(P, [(x0 - 0.8, ya), (x1 + 0.8, ya), (x1 + 0.8, yb), (x0 - 0.8, yb)], shade_lr(P, x0, x1, mixc(TENG, GOLD_HI, 0.4), mixc(TENG, GOLD_DK, 0.55)), ol=1.0, ol_rgb=mixc(GOLD_DK, JIAO, 0.45), pool=0.3, pool_rgb=GOLD_DK, wob=0.02)
        for y in (ya + 1.4, yb - 1.4):
            stroke(P, W.seg_pts((x0 - 0.4, y), (x1 + 0.4, y), n=12), 0.3, GOLD_DK, 0.9)
    stroke(P, W.seg_pts((30.2, 18.5), (30.2, 37.5), n=20), 0.5, mixc(QING, WHITE, 0.3), 0.7)
    for (y, x0_, x1_) in ((32.0, 21.0, 43.0), (25.0, 23.5, 41.0)):
        a = np.linspace(0.15 * math.pi, 0.85 * math.pi, 40)
        stroke(P, np.stack([32.0 + (x1_ - x0_) / 2 * np.cos(a + math.pi), y + 2.2 * np.sin(a)], -1), 0.55 * W.brush_profile(40, 0.4, 0.3), mixc(EL_INK["water"], HUAQING, 0.4), 0.6)
    for (x, y) in ((16.5, 38.5), (47.0, 37.5), (44.0, 33.0)):
        P.dot(x, y, 0.8, mixc(W_HUAQING, WHITE, 0.3))


def ch_night_pearl(P):
    """照夜珠：一颗月白的大珠子托在一朵花青的祥云上，珠光暖白、一圈月晕，四周几缕夜云、几点星。"""
    cx, cy, R = 32.0, 27.5, 10.0
    for (y, x0, x1) in ((46.5, 13.5, 24.0), (16.0, 44.0, 52.0), (40.5, 44.0, 53.0)):
        stroke(P, V.bezier([(x0, y), ((x0 + x1) / 2, y - 1.6), (x1, y)], 24), 1.0 * W.brush_profile(24, 0.5, 0.3), mixc(DAN, QING, 0.3), 0.75, dry=0.35, dry_start=0.3)
    for (x, y) in ((17.0, 21.0), (46.0, 30.0), (20.0, 35.0)):
        sparkle(P, x, y, 2.0, mixc(TENG, W_TENG, 0.3), 0.45)
    halo = W.ellipse_pts(cx, cy, R + 4.5, R + 4.5, 120)
    glow(P, cx, cy, 18.0, mixc(mixc(TENG, WHITE, 0.65), PAPER, 0.15), 0.9)
    stroke(P, V.arc_resample(np.vstack([halo, halo[:1]]), 160), 0.45, mixc(TENG, W_TENG, 0.4), 0.7)
    # 祥云托：两个云卷
    cloud = mixc(W_HUAQING, HUAQING, 0.35)
    base = W.catmull_closed([(18.5, 43.0), (21.0, 38.5), (26.5, 37.5), (32.0, 39.5), (37.5, 37.5), (43.0, 38.5), (45.5, 43.0), (40.0, 45.0), (32.0, 44.0), (24.0, 45.0)], 8)
    _, m = shape(P, base, shade_lr(P, 18, 46, mixc(cloud, WHITE, 0.3), mixc(cloud, ZHONG, 0.3)), ol=1.1, ol_rgb=mixc(HUAQING, JIAO, 0.5), pool=0.3, pool_rgb=HUAQING)
    for (x, sgn) in ((25.0, 1.0), (39.0, -1.0)):
        th = np.linspace(0.0, 1.6 * math.pi, 30)
        r = 0.6 + 2.4 * th / th[-1]
        stroke(P, np.stack([x + sgn * r * np.cos(th), 41.0 + r * np.sin(th) * 0.8], -1), 0.4, mixc(HUAQING, JIAO, 0.45), 0.9, clip=m)
    rr = np.hypot((P.X - cx + 3.0) / R, (P.Y - cy + 3.0) / R)
    rgb = mixc(WHITE, mixc(mixc(TENG, PAPER, 0.45), W_HUAQING, 0.2), smoothstep(0.1, 1.5, rr))
    _, mp = shape(P, W.ellipse_pts(cx, cy, R, R, 80), rgb, ol=1.0, ol_rgb=mixc(ZHESHI, JIAO, 0.4), pool=0.35, pool_rgb=mixc(TENG, ZHESHI, 0.3), mottle=0.0)
    P.dot(cx - 3.4, cy - 3.6, 1.9, WHITE)
    stroke(P, V.bezier([(cx + 2.0, cy + 7.0), (cx + 6.5, cy + 4.5), (cx + 7.5, cy)], 20), 0.65, mixc(W_HUAQING, WHITE, 0.2), 0.8, clip=mp)


def ch_elixir(P):
    """九转金丹：打开的朱漆丹盒里一粒金丹，金光一圈，三缕丹气从丹上旋着升起。"""
    cx, cy = 32.0, 30.5
    glow(P, cx, cy, 14.0, mixc(TENG, WHITE, 0.45), 0.85)
    for k in range(16):
        a = 2 * math.pi * k / 16 + 0.1
        r0, r1 = 9.0, 12.0 if k % 2 == 0 else 10.8
        stroke(P, W.seg_pts((cx + r0 * math.cos(a), cy + r0 * math.sin(a)), (cx + r1 * math.cos(a), cy + r1 * math.sin(a)), n=8), np.linspace(0.55, 0.12, 8), mixc(TENG, GOLD_DK, 0.15), 0.85)
    for (x0, sgn, h) in ((27.5, -1.0, 13.0), (32.0, 1.0, 17.0), (36.5, 1.0, 12.0)):
        ctrl = [(x0, cy - 5.0), (x0 + sgn * 4.0, cy - 5.0 - 0.4 * h), (x0 - sgn * 3.5, cy - 5.0 - 0.75 * h), (x0 + sgn * 1.5, cy - 5.0 - h)]
        stroke(P, V.bezier(ctrl, 30), 0.85 * W.brush_profile(30, 0.4, 0.2), mixc(TENG, ZHESHI, 0.35), 0.85, dry=0.3, dry_start=0.5)
    # 丹盒：盒身朱漆，盒盖斜靠在后面
    shape(P, [(19.0, 33.5), (44.0, 30.5), (45.0, 33.0), (20.5, 36.2)], mixc(ZHUSHA, ZHONG, 0.25), ol=1.0, pool=0.3, pool_rgb=ZHUSHA_DK, wob=0.02)
    box = U.paint_box(P, 20.5, 38.0, 22.0, 8.0, 3.5, 2.6, ZHUSHA, ol=1.15)
    stroke(P, W.seg_pts((21.0, 41.5), (42.0, 41.5), n=20), 0.45, TENG, 0.9, clip=box[1])
    shape(P, W.ellipse_pts(33.5, 37.0, 9.5, 1.8, 40), mixc(ZHUSHA_DK, JIAO, 0.3), ol=0.0, pool=0.0, wob=0.0)
    rr = np.hypot((P.X - cx + 2.2) / 6.8, (P.Y - cy + 2.2) / 6.8)
    rgb = mixc(mixc(TENG, WHITE, 0.55), mixc(TENG, GOLD_DK, 0.55), smoothstep(0.1, 1.4, rr))
    shape(P, W.ellipse_pts(cx, cy, 6.8, 6.8, 60), rgb, ol=1.15, ol_rgb=mixc(GOLD_DK, JIAO, 0.45), pool=0.35, pool_rgb=GOLD_DK, mottle=0.0)
    P.dot(cx - 2.3, cy - 2.5, 1.35, WHITE)


def ch_five_coins(P):
    """五帝钱：五枚方孔钱用红绳串成一道弧，绳头一个小结、两缕穗子。"""
    pts = [(14.5, 34.0), (22.5, 27.5), (32.0, 25.0), (41.5, 27.5), (49.5, 34.0)]
    stroke(P, V.bezier([(9.5, 38.5), (20.0, 25.0), (44.0, 25.0), (54.0, 38.5)], 80), 0.75, CORD)
    for k, (x, y) in enumerate(pts):
        coin(P, x, y, 6.6, ry=6.6, ol=1.05)
        stroke(P, W.seg_pts((x - 1.8, y), (x + 1.8, y), n=8), 0.6, CORD)
    stroke(P, W.seg_pts((32.0, 31.0), (32.0, 41.0), n=12), 0.6, CORD)
    shape(P, [(32.0, 39.5), (34.0, 41.5), (32.0, 43.5), (30.0, 41.5)], CORD, ol=0.5, ol_rgb=ZHUSHA_DK, pool=0.2, pool_rgb=ZHUSHA_DK, wob=0.0)
    for dx in (-1.0, 0.0, 1.0):
        stroke(P, V.bezier([(32.0 + dx * 0.4, 43.5), (32.0 + dx * 1.2, 47.0), (32.0 + dx * 2.0, 50.5)], 16), 0.5 * W.brush_profile(16, 1.0, 0.3, 0.0), CORD, dry=0.3, dry_start=0.5)


def ch_longevity(P):
    """长命锁：一把如意云头形的银锁，錾一圈边、正面阳刻“长命”二字，一条银链从两肩挂上去，下面垂三只小银铃。"""
    import ui_seals  # noqa: PLC0415

    silver_l, silver_d = mixc(mixc(PAPER, WHITE, 0.7), QING, 0.15), mixc(mixc(QING, HUAQING, 0.25), ZHONG, 0.45)
    chain = V.bezier([(18.5, 24.0), (18.0, 9.0), (46.0, 9.0), (45.5, 24.0)], 80)
    for i in range(0, 80, 4):
        P.dot(chain[i, 0], chain[i, 1], 0.95, mixc(ZHONG, JIAO, 0.2))
        P.dot(chain[i, 0], chain[i, 1], 0.55, silver_l)
    # 锁身：上沿两个如意云头、中间下凹，下沿圆
    lock = W.catmull_closed([(32.0, 22.5), (27.0, 19.0), (21.5, 18.5), (16.5, 22.0), (15.5, 27.5), (19.0, 34.5), (25.5, 39.5), (32.0, 41.0), (38.5, 39.5), (45.0, 34.5), (48.5, 27.5), (47.5, 22.0), (42.5, 18.5), (37.0, 19.0)], 8)
    rr = np.hypot((P.X - 27.0) / 17.0, (P.Y - 25.0) / 12.0)
    _, m = shape(P, lock, mixc(silver_l, silver_d, smoothstep(0.2, 1.3, rr)), ol=OL * 1.15, ol_rgb=mixc(ZHONG, JIAO, 0.45), pool=0.35, pool_rgb=silver_d, mottle=0.04)
    inner = W.catmull_closed([(32.0, 25.0), (27.5, 22.0), (22.0, 21.8), (19.0, 24.0), (18.6, 27.6), (21.5, 33.0), (26.5, 36.6), (32.0, 37.8), (37.5, 36.6), (42.5, 33.0), (45.4, 27.6), (45.0, 24.0), (42.0, 21.8), (36.5, 22.0)], 8)
    stroke(P, V.arc_resample(np.vstack([inner, inner[:1]]), 160), 0.45, silver_d, 0.85, clip=m)
    for ch, cell in (("长", (21.5, 24.5, 31.0, 35.0)), ("命", (33.0, 24.5, 42.5, 35.0))):
        g = ui_seals.glyph_field(P, ch, cell, stretch=1.0)
        P.lay.over(mixc(silver_d, JIAO, 0.25), smoothstep(0.35, 0.55, g) * m)
    stroke(P, V.bezier([(18.0, 24.0), (21.5, 20.6), (27.0, 20.5)], 20), 0.75 * W.brush_profile(20, 0.4, 0.3), WHITE, 0.85, clip=m)
    for x in (24.0, 32.0, 40.0):
        y = 40.5 if x == 32.0 else 38.0
        stroke(P, W.seg_pts((x, y - 1.5), (x, y + 2.0), n=8), 0.3, silver_d)
        shape(P, W.ellipse_pts(x, y + 4.4, 2.4, 2.6, 24), mixc(silver_l, silver_d, 0.3), ol=0.75, ol_rgb=mixc(ZHONG, JIAO, 0.4), pool=0.3, pool_rgb=silver_d)
        P.dot(x, y + 5.7, 0.6, JIAO)


def ch_ice_soul(P):
    """冰魄珠：一颗冰蓝的珠子（串在一小截红绳上），珠里冻着一朵小冰花，珠面一道冰裂，四周寒气与几点冰晶。"""
    cx, cy, R = 32.0, 31.0, 11.0
    glow(P, cx, cy, 18.0, mixc(W_HUAQING, WHITE, 0.35), 0.8)
    edge = mixc(HUAQING, JIAO, 0.5)
    for (ctrl, al) in ((((14.0, 40.0), (20.0, 44.5), (27.0, 44.0), (31.0, 47.5)), 0.8), (((50.0, 20.0), (45.0, 15.0), (39.0, 17.0), (35.0, 13.5)), 0.7)):
        stroke(P, V.bezier(list(ctrl), 30), 0.9 * W.brush_profile(30, 0.3, 0.3), mixc(W_HUAQING, QING, 0.4), al, dry=0.35, dry_start=0.4)
    stroke(P, W.seg_pts((cx, cy - R - 3.5), (cx, cy - R + 1.0), n=10), 0.6, CORD)
    stroke(P, W.seg_pts((cx, cy + R - 1.0), (cx, cy + R + 3.5), n=10), 0.6, CORD)
    rr = np.hypot((P.X - cx + 3.5) / R, (P.Y - cy + 3.5) / R)
    rgb = mixc(mixc(W_HUAQING, WHITE, 0.65), mixc(EL_INK["water"], HUAQING, 0.55), smoothstep(0.1, 1.4, rr))
    _, m = shape(P, W.ellipse_pts(cx, cy, R, R, 80), rgb, ol=OL, ol_rgb=edge, pool=0.45, pool_rgb=mixc(HUAQING, JIAO, 0.2), mottle=0.0)
    for k in range(6):
        a = math.radians(-90.0 + 60.0 * k)
        stroke(P, W.seg_pts((cx + 1.0 * math.cos(a), cy + 1.0 * math.sin(a)), (cx + 6.0 * math.cos(a), cy + 6.0 * math.sin(a)), n=10), 0.6, WHITE, 0.9, clip=m)
        bx, by = cx + 3.6 * math.cos(a), cy + 3.6 * math.sin(a)
        for sgn in (-1.0, 1.0):
            stroke(P, W.seg_pts((bx, by), (bx + 2.0 * math.cos(a + sgn * 0.9), by + 2.0 * math.sin(a + sgn * 0.9)), n=6), 0.38, WHITE, 0.85, clip=m)
    stroke(P, V.arc_resample(np.array([(cx + 4.0, cy - 9.5), (cx + 6.0, cy - 5.5), (cx + 4.8, cy - 3.0), (cx + 8.0, cy + 1.0)]), 30), np.linspace(0.45, 0.15, 30), edge, 0.8, clip=m)
    stroke(P, V.bezier([(cx - 7.5, cy + 2.5), (cx - 8.0, cy - 3.5), (cx - 3.0, cy - 8.0)], 20), 1.0 * W.brush_profile(20, 0.4, 0.3), WHITE, 0.9, clip=m)
    for (x, y, L) in ((17.5, 22.0, 2.6), (47.0, 39.5, 2.4), (45.0, 26.5, 1.6), (19.0, 30.0, 1.5)):
        sparkle(P, x, y, L, mixc(EL_INK["water"], WHITE, 0.3), 0.5)


def ch_broken_sword(P):
    """断剑：一把剑尖朝下插在地上、剑身从中间断了，断下来的剑尖斜躺在一旁，断口一线朱砂。"""
    stroke(P, V.bezier([(13.0, 47.5), (32.0, 46.0), (51.0, 47.5)], 40), 0.9 * W.brush_profile(40, 0.6, 0.3), ZHONG, 0.8, dry=0.4, dry_start=0.3)
    fr = Fr(27.0, 30.0, 90.0, 1.15)  # 剑尖朝下（+u 向下）
    hi, lo = mixc(PAPER, WHITE, 0.65), mixc(QING, PAPER, 0.3)
    _, Vv = fr.uv(P)
    blade = fr([(-4.0, -2.9), (5.5, -2.7), (7.0, -1.2), (6.0, 0.4), (8.2, 2.7), (-4.0, 2.9)])
    d, t = P.sdf(W.wobble(blade, P.rng, 0.03, spacing=0.3))
    P.fill(d, mixc(hi, lo, smoothstep(-0.3, 0.5, Vv)))
    m = P.cover(d)
    stroke(P, fr(W.seg_pts((-3.0, 0.0), (5.5, 0.0), n=12)), 0.3, DAN, 0.8, clip=m)
    P.outline(d, t, OL, INK_LINE, jitter=0.15)
    stroke(P, fr(W.seg_pts((5.6, -2.7), (7.0, -1.2), (6.0, 0.4), (8.2, 2.7), n=20)), 0.45, ZHUSHA, 0.9)
    # 剑格、剑柄、剑首
    gp = fr([(-6.8, -6.6), (-5.0, -5.8), (-3.4, -0.7), (-3.4, 0.7), (-5.0, 5.8), (-6.8, 6.6), (-5.6, 0.0)])
    d, t = P.sdf(W.catmull_closed(gp, 8))
    P.fill(d, mixc(TENG, GOLD_HI, 0.2), pool=0.5, pool_rgb=GOLD_DK, pool_w=0.6)
    P.outline(d, t, 0.95, mixc(GOLD_DK, JIAO, 0.45))
    grip = fr([(-15.5, -1.8), (-6.4, -1.8), (-6.4, 1.8), (-15.5, 1.8)])
    U_, _ = fr.uv(P)
    stripes = 0.5 + 0.5 * np.sin(2 * math.pi * (U_ - Vv * 0.9) / 1.7)
    shape(P, grip, mixc(NONG, mixc(ZHONG, DAN, 0.3), 0.7 * smoothstep(0.45, 0.85, stripes)), ol=0.85, wob=0.03)
    shape(P, fr(W.ellipse_pts(-16.4, 0.0, 2.1, 2.1, 32)), mixc(TENG, GOLD_HI, 0.3), ol=0.8, ol_rgb=mixc(GOLD_DK, JIAO, 0.4), pool=0.5, pool_rgb=GOLD_DK, wob=0.02)
    for tip in ((-19.0, 3.0), (-18.5, 5.4)):
        stroke(P, fr(V.bezier([(-17.0, 0.6), (-18.0, 2.0), tip], 16)), 0.6 * W.brush_profile(16, 1.0, 0.25, 0.0), ZHUSHA)
    # 断下来的剑尖：斜躺在右下
    fr2 = Fr(42.0, 41.0, -18.0, 1.15)
    _, V2 = fr2.uv(P)
    tipp = fr2([(-6.0, -2.5), (-4.6, -0.8), (-6.4, 0.8), (-5.0, 2.5), (4.0, 1.6), (9.0, 0.0), (4.0, -1.6)])
    d, t = P.sdf(W.wobble(tipp, P.rng, 0.03, spacing=0.3))
    P.fill(d, mixc(hi, lo, smoothstep(-0.3, 0.5, V2)))
    P.outline(d, t, OL, INK_LINE, jitter=0.15)
    stroke(P, fr2(W.seg_pts((-6.0, -2.5), (-4.6, -0.8), (-6.4, 0.8), (-5.0, 2.5), n=20)), 0.45, ZHUSHA, 0.9)
    for (x, y) in ((35.5, 44.5), (47.5, 44.0)):
        P.dot(x, y, 0.6, DAN)


# ============================================================== 汇总


PASSIVES_M25 = [  # (id, 名, 五行或 None, 画法)，五行与 assets/data/passives.ron 一致
    ("xunfeng", "迅锋", "metal", em_xunfeng),
    ("huichun", "回春", "wood", em_huichun),
    ("hanyi", "寒意", "water", em_hanyi),
    ("dengxin", "灯芯", "fire", em_dengxin),
    ("zaiwu", "载物", "earth", em_zaiwu),
    ("qinggong", "轻功", None, em_qinggong),
    ("juhun", "聚魂", None, em_juhun),
]
OMENS_M25 = [("wuyue", "无月", em_omen_wuyue), ("nike", "逆克", em_omen_nike)]
AFFIXES = [  # 与 assets/data/affixes.ron 一致
    ("ji", "疾", af_ji), ("jian", "坚", af_jian), ("fen", "分", af_fen),
    ("zhao", "召", af_zhao), ("yin", "隐", af_yin), ("kuang", "狂", af_kuang),
]
HUB = [  # 灯驿人物，按序号 icon_hub_0..3（docs/GAMEPLAY.md 11.6 节）
    ("lampsmith", "老灯匠", em_hub_lampsmith), ("peddler", "货郎", em_hub_peddler),
    ("lampboy", "灯童", em_hub_lampboy), ("storyteller", "说书人", em_hub_storyteller),
]
CHARMS = [  # 与 assets/data/charms.ron 一致
    ("wind_wheel", "风火轮", ch_wind_wheel), ("pillar", "定海神针", ch_pillar), ("night_pearl", "照夜珠", ch_night_pearl),
    ("elixir", "九转金丹", ch_elixir), ("five_coins", "五帝钱", ch_five_coins), ("longevity", "长命锁", ch_longevity),
    ("ice_soul", "冰魄珠", ch_ice_soul), ("broken_sword", "断剑", ch_broken_sword),
]


def specs():
    """[(文件名, 画法, 框, 种子, meta 附加字段)]，顺序固定（种子按序号取）。
    框：("ring", 色弧) 普通墨圈；("omen", None) 朱砂双圈；("small", 色弧) 小图标；("charm", None) 灯坠（红绳圈 + 中国结）。"""
    out = []

    def add(fname, fn, frame, extra):
        out.append((fname, fn, frame, 9000 + 37 * len(out), extra))

    for pid, name, el, fn in PASSIVES_M25:
        arc = EL_INK[el] if el else U.NEUTRAL_ARC
        extra = {"kind": "passive", "id": pid, "name": name}
        if el:
            extra["el"] = el
        add(f"icon_{pid}", fn, ("ring", arc), extra)
    for oid, name, fn in OMENS_M25:
        add(f"icon_omen_{oid}", fn, ("omen", None), {"kind": "omen", "id": oid, "name": name})
    add("icon_gold", em_gold, ("ring", U.NEUTRAL_ARC), {"kind": "currency", "id": "gold", "name": "金币"})
    add("icon_enc_merchant", em_enc_merchant, ("ring", MERCHANT_INK), {"kind": "encounter", "id": "merchant", "name": "货郎", "accent": MERCHANT_HEX})
    for aid, name, fn in AFFIXES:
        add(f"icon_affix_{aid}", fn, ("small", AFFIX_ARC), {"kind": "affix", "id": aid, "name": name})
    for k, (role, name, fn) in enumerate(HUB):
        add(f"icon_hub_{k}", fn, ("ring", HUB_ARC), {"kind": "hub", "id": str(k), "role": role, "name": name})
    for cid, name, fn in CHARMS:
        add(f"icon_charm_{cid}", fn, ("charm", None), {"kind": "charm", "id": cid, "name": name})
    return out


def make(index: int):
    _, fn, (frame, arc), seed, _ = specs()[index]
    if frame == "small":
        P = small_painter(seed)
        U.disc_back(P, PAPER)
        fn(P)
        small_ring_front(P, arc)
        return P.image()
    P = W.Painter(U.SIZE, U.SIZE, seed, ss=U.SS)
    if frame == "charm":
        U.disc_back(P, mixc(PAPER, W_ZHUSHA, 0.03))
        fn(P)
        charm_cord(P)
        U.ring_front(P, None)
        charm_knot(P)
        return P.image()
    if frame == "omen":
        U.disc_back(P, mixc(PAPER, W_ZHUSHA, 0.05))
        fn(P)
        U.omen_front(P)
    else:
        U.disc_back(P, PAPER)
        fn(P)
        U.ring_front(P, arc)
    return P.image()


def note_for(extra: dict) -> str:
    if extra["kind"] == "affix":
        return f"精英词缀（小图标，1 倍 32 像素 / 2 倍 64 像素）：{extra['name']}"
    return f"界面图标：{extra['name']}"
