#!/usr/bin/env python3
"""提灯夜行 · 新法器的界面图标（只用 Pillow + numpy）：铜钱剑、孔明灯、沧浪、青藤、镇妖塔，各一张本体、一张进化。

和原有五件法器同一套框（ui_icons.frame_back / frame_front：宣纸圆底、墨圈、五行色弧，进化加金圈、纸底偏暖），
物件按原有图标的画法（淡彩、手抖墨线、干笔），64×64（1 倍）/ 128×128（2 倍），缩到 32 像素仍要认得出。
帧名 ui/icon_<id>、ui/icon_<id>_evo（与 crates/ui 的 describe / choice 一致），打进 cards 页（不动 ui 页）。
坐标按 64×64 的 1 倍像素写（圆心 (32, 32)）。种子：12000 + 37 × 序号。

输出：art/out/<ASSETS_DIR_NAME>/ui_new/  icon_*.png + meta.json（name = "ui"）
用法（在仓库根目录下）：
  LANTERN_ART_DENSITY=2 art/.venv/bin/python art/post/ui_icons_new.py
"""

from __future__ import annotations

import math
import sys
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import ui_icons as U  # noqa: E402

V, W, S = U.V, U.W, U.S
Fr, shape, stroke, sparkle, flame, coin, leaf = U.Fr, U.shape, U.stroke, U.sparkle, U.flame, U.coin, U.leaf
mixc, smoothstep = U.mixc, U.smoothstep
PAPER, PAPER_SH, WHITE = U.PAPER, U.PAPER_SH, U.WHITE
JIAO, NONG, ZHONG, DAN, QING = U.JIAO, U.NONG, U.ZHONG, U.DAN, U.QING
ZHUSHA, ZHESHI, HUAQING, SHILV, TENG = U.ZHUSHA, U.ZHESHI, U.HUAQING, U.SHILV, U.TENG
W_ZHUSHA, W_ZHESHI, W_HUAQING, W_SHILV, W_TENG = U.W_ZHUSHA, U.W_ZHESHI, U.W_HUAQING, U.W_SHILV, U.W_TENG
GOLD_DK, GOLD_HI, ZHUSHA_DK, INK_LINE, OL = U.GOLD_DK, U.GOLD_HI, U.ZHUSHA_DK, U.INK_LINE, U.OL

OUT_DIR = V.ASSETS / "ui_new"
CORD = mixc(ZHUSHA, W_ZHUSHA, 0.1)


def glow_in(P, cx, cy, r, rgb, alpha):
    """同 ui_icons.glow，但只留在圆底里（灯挨着框时光晕不会漏到圆外）。"""
    rr = np.hypot(P.X - cx, P.Y - cy) / r
    disc = smoothstep(27.4, 25.4, np.hypot(P.X - U.C, P.Y - U.C))
    P.lay.over(rgb, alpha * np.exp(-(rr**2) * 2.2) * smoothstep(1.4, 0.8, rr) * disc)


def cord_tassel(P, x, y, ang, L, s=1.0):
    """红穗：从 (x, y) 往 ang 方向垂三缕。"""
    a = math.radians(ang)
    for k, da in enumerate((-12.0, 0.0, 12.0)):
        b = a + math.radians(da)
        tip = (x + L * math.cos(b), y + L * math.sin(b))
        mid = (x + 0.5 * L * math.cos(b) + 0.6 * math.sin(b), y + 0.5 * L * math.sin(b) - 0.6 * math.cos(b))
        stroke(P, V.bezier([(x, y), mid, tip], 24), (0.75 - 0.08 * k) * s * W.brush_profile(24, 1.0, 0.25, 0.0), CORD,
               dry=0.3, dry_start=0.5)
    P.dot(x, y, 1.0 * s, ZHUSHA_DK)


# ============================================================== 铜钱剑 / 天罡


def paint_coin_sword(P, fr: Fr):
    """铜钱剑：六枚铜钱一枚压一枚串成剑身（剑尖朝 +u），红绳从钱孔里穿过；剑格是两枚竖着的钱，剑柄缠红绳，柄尾垂红穗。"""
    s = fr.s
    tail = fr.pt(-17.5, 0.0)
    cord_tassel(P, *tail, math.degrees(math.atan2(fr.sa, fr.ca)) + 180 - 20, 7.5 * s, s)
    grip = fr([(-17.0, -1.7), (-9.0, -1.7), (-9.0, 1.7), (-17.0, 1.7)])
    d, m = shape(P, grip, mixc(ZHUSHA, ZHUSHA_DK, 0.3), ol=0.8 * s, ol_rgb=mixc(ZHUSHA_DK, JIAO, 0.5), pool=0.3, pool_rgb=ZHUSHA_DK)
    for k in range(5):  # 缠绳：斜的几道深红
        u0 = -16.2 + 1.6 * k
        stroke(P, fr(W.seg_pts((u0, -1.7), (u0 + 1.0, 1.7), n=8)), 0.35 * s, ZHUSHA_DK, 0.9, clip=m)
    # 剑尖：一片小小的铁刃
    tip = fr([(16.5, -2.4), (23.5, 0.0), (16.5, 2.4)])
    d, m = shape(P, tip, mixc(PAPER, WHITE, 0.6), ol=0.8 * s, pool=0.3, pool_rgb=QING)
    stroke(P, fr(W.seg_pts((17.0, 0.0), (22.5, 0.0), n=8)), 0.25 * s, DAN, 0.7, clip=m)
    # 剑身：从剑尖往回画，后一枚压前一枚
    for u in (14.0, 9.4, 4.8, 0.2, -4.4):
        cx, cy = fr.pt(u, 0.0)
        coin(P, cx, cy, 3.15 * s)
    # 红绳：沿剑脊一道，过每个钱孔露一截
    for u in (14.0, 9.4, 4.8, 0.2, -4.4):
        stroke(P, fr(W.seg_pts((u - 0.9, 0.0), (u + 0.9, 0.0), n=6)), 0.45 * s, CORD)
    # 剑格：两枚钱竖着压在剑身根上
    for v in (-3.4, 3.4):
        cx, cy = fr.pt(-8.2, v)
        coin(P, cx, cy, 2.6 * s)


def em_coin_sword(P, evo):
    if not evo:
        glow_in(P, 48.0, 16.0, 6.0, mixc(WHITE, W_HUAQING, 0.4), 0.6)
        paint_coin_sword(P, Fr(29.5, 34.5, -45.0, 1.18))
        sparkle(P, 49.5, 14.5, 2.8, mixc(WHITE, W_HUAQING, 0.3), 0.5)
        return
    # 天罡：一圈铜金色的剑气旋风，头顶七枚铜钱排成北斗
    for k in range(3):  # 旋风：三道越来越大的弧，带干笔
        r0 = 8.0 + 5.2 * k
        a = np.linspace(math.radians(200 - 30 * k), math.radians(200 - 30 * k + 260), 60)
        pts = np.stack([32.0 + r0 * np.cos(a), 41.5 + 0.45 * r0 * np.sin(a)], -1)
        stroke(P, pts, (1.25 - 0.15 * k) * W.brush_profile(60, 0.6, 0.15, 0.2), mixc(TENG, GOLD_DK, 0.25 + 0.15 * k), 0.95,
               dry=0.35, dry_start=0.55)
    for k, (dx, dy) in enumerate(((-7.0, 0.5), (6.5, -0.5), (0.5, 2.6))):  # 旋风里卷着的三道剑气
        stroke(P, W.seg_pts((32.0 + dx - 3.5, 41.0 + dy + 1.2), (32.0 + dx + 3.5, 41.0 + dy - 1.2), n=12),
               0.55 * W.brush_profile(12, 0.2, 0.2, 0.0), mixc(WHITE, TENG, 0.3), 0.9)
    glow_in(P, 32.0, 21.0, 15.0, mixc(TENG, PAPER, 0.4), 0.4)
    pts = np.array(DIPPER, float)
    pts = (pts - (pts.min(0) + pts.max(0)) / 2) * np.array([10.4, -10.4])  # 斗口朝上、斗柄往右
    stroke(P, np.stack([31.5 + pts[:, 0], 22.0 + pts[:, 1]], -1), 0.22, mixc(TENG, GOLD_DK, 0.4), 0.55)
    for k, (x, y) in enumerate(pts):
        coin(P, 31.5 + x, 22.0 + y, 3.0 if k < 4 else 2.75, ol=0.75)


DIPPER = [(0.00, 0.00), (0.02, 0.62), (0.70, 0.78), (1.00, 0.30), (1.62, 0.18), (2.15, 0.36), (2.62, 0.05)]
"""北斗七星的相对位置（与 art/render/card_props.DIPPER 相同；y 朝上）。"""


# ============================================================== 孔明灯 / 万灯升


def paint_sky_lantern(P, cx, cy, s, *, lit=1.0):
    """孔明灯：上宽下窄的纸罩（四道竹篾），罩里透出暖光，下口一圈竹圈，口里一朵火。(cx, cy) 是灯罩中心。"""
    glow_in(P, cx, cy + 2.0 * s, 13.0 * s, mixc(TENG, PAPER, 0.3), 0.55 * lit)
    top, bot = cy - 9.5 * s, cy + 8.5 * s
    body = [(cx - 7.4 * s, top + 3.0 * s), (cx - 5.6 * s, top + 0.6 * s), (cx - 2.4 * s, top - 0.3 * s), (cx + 2.4 * s, top - 0.3 * s),
            (cx + 5.6 * s, top + 0.6 * s), (cx + 7.4 * s, top + 3.0 * s), (cx + 5.4 * s, bot), (cx - 5.4 * s, bot)]
    rn = np.hypot((P.X - cx) / (7.0 * s), (P.Y - (cy + 3.0 * s)) / (9.0 * s))
    rgb = mixc(mixc(TENG, PAPER, 0.25), mixc(TENG, WHITE, 0.55), np.exp(-((rn / 0.6) ** 2)) * lit)
    rgb = mixc(rgb, mixc(ZHESHI, TENG, 0.5), smoothstep(cy, top, P.Y) * 0.35)
    d, m = shape(P, W.catmull_closed(body, 4), rgb, ol=OL * min(1.0, 0.55 + 0.45 * s), pool=0.35, pool_rgb=mixc(ZHESHI, TENG, 0.4))
    for k in (-0.5, 0.0, 0.5):  # 竹篾
        stroke(P, W.seg_pts((cx + k * 7.0 * s, top), (cx + k * 5.0 * s, bot), n=20), 0.32 * s, mixc(ZHESHI, JIAO, 0.3), 0.7, clip=m)
    ring = W.ellipse_pts(cx, bot, 5.6 * s, 1.2 * s, 40)
    stroke(P, V.arc_resample(np.vstack([ring, ring[:1]]), 60), 0.5 * s, mixc(ZHESHI, JIAO, 0.5))
    flame(P, cx, bot + 1.0 * s, 4.6 * s, 1.9 * s, ol=0.5 * s, core=s >= 0.8)  # 小灯不画火心（太小的多边形会把整张填满）


def em_sky_lantern(P, evo):
    if not evo:
        for (x, y, r) in ((20.0, 46.0, 0.55), (44.0, 48.5, 0.5), (24.0, 51.5, 0.45), (40.5, 43.5, 0.4)):  # 升起时洒下的火星
            P.dot(x, y, r, mixc(TENG, ZHUSHA, 0.3))
        paint_sky_lantern(P, 32.0, 28.0, 1.45)
        return
    # 万灯升：一盏大灯在前，两盏小灯在后，灯下一场火雨
    for (x, y, sc) in ((18.5, 22.5, 0.60), (46.0, 20.0, 0.66)):
        paint_sky_lantern(P, x, y, sc, lit=0.8)
    paint_sky_lantern(P, 31.5, 30.0, 1.05)
    rng = np.random.default_rng(7)
    for _ in range(14):  # 火雨：一道道往下落的火线
        x = rng.uniform(15.0, 49.0)
        y = rng.uniform(42.0, 52.0)
        L = rng.uniform(2.0, 4.0)
        stroke(P, W.seg_pts((x - 0.4, y - L), (x, y), n=10), 0.5 * W.brush_profile(10, 0.1, 0.0, 0.0), mixc(TENG, ZHUSHA, 0.35), 0.9)
        P.dot(x, y, 0.55, mixc(TENG, WHITE, 0.4))


# ============================================================== 沧浪 / 北冥潮


def paint_wave(P, fr: Fr, *, ice=False):
    """一道卷起的月牙浪头（往 +u 卷），浪背花青、浪腹淡，浪尖碎成几根白沫的“爪”。"""
    s = fr.s
    outer = [(-15.0, 9.0), (-12.0, 2.0), (-7.0, -5.5), (0.0, -10.5), (7.5, -11.5), (13.5, -8.5), (15.5, -4.0), (13.0, -1.0),
             (9.5, -3.5), (6.5, -2.0), (5.5, 2.5), (8.0, 6.5), (13.5, 9.0)]
    poly = W.catmull_closed(fr(outer), 8)
    U_, Vv = fr.uv(P)
    deep = mixc(HUAQING, JIAO, 0.25) if not ice else mixc(HUAQING, PAPER, 0.15)
    pale = mixc(W_HUAQING, WHITE, 0.25) if not ice else mixc(WHITE, W_HUAQING, 0.2)
    rgb = mixc(pale, deep, smoothstep(-8.0, 6.0, Vv) * 0.5 + smoothstep(8.0, -10.0, U_) * 0.5)
    d, m = shape(P, poly, rgb, ol=OL * s, pool=0.35, pool_rgb=mixc(HUAQING, JIAO, 0.4))
    for k in range(4):  # 浪身上几道顺着卷的水纹
        a0 = -0.6 + 0.35 * k
        pts = fr([(-11.0 + 2.5 * k + 14.0 * t, 6.0 - 3.0 * k - 12.0 * t * (1 - 0.4 * t) + a0) for t in np.linspace(0, 1, 30)])
        stroke(P, pts, 0.35 * s * W.brush_profile(30, 0.3, 0.3, 0.3), mixc(WHITE, W_HUAQING, 0.4), 0.7, clip=m)
    # 浪尖的白沫：几根往前探的爪
    for k, (u0, v0, du, dv) in enumerate(((13.0, -8.5, 3.6, 2.2), (14.6, -5.0, 2.8, 2.8), (10.5, -11.0, 3.2, 0.8), (7.0, -11.6, 2.4, -0.6))):
        pts = fr([(u0 + du * t, v0 + dv * t * t) for t in np.linspace(0, 1, 12)])
        stroke(P, pts, 0.8 * s * W.brush_profile(12, 0.9, 0.0, 0.0), WHITE, 0.95)
        P.dot(*fr.pt(u0 + du + 0.6, v0 + dv + 0.4), 0.45 * s, WHITE)
    for (u0, v0) in ((16.5, -10.5), (18.0, -7.0), (11.5, -13.5)):
        P.dot(*fr.pt(u0, v0), 0.5 * s, mixc(WHITE, W_HUAQING, 0.2))
    return m


def em_wave(P, evo):
    if not evo:
        paint_wave(P, Fr(31.5, 33.5, 0.0, 1.12))
        for k in range(2):  # 浪脚下两道平的水线
            stroke(P, W.seg_pts((15.0 + 4 * k, 46.0 + 2.5 * k), (48.0 - 3 * k, 46.0 + 2.5 * k), n=20),
                   0.55 * W.brush_profile(20, 0.3, 0.3, 0.3), mixc(HUAQING, PAPER, 0.3), 0.9)
        return
    # 北冥潮：俯看一圈冰浪从中心往外荡，圈心深水里一条巨鱼（鲲）的影子
    glow_in(P, 32.0, 32.0, 16.0, mixc(W_HUAQING, PAPER, 0.3), 0.5)
    fish = [(19.0, 34.0), (23.0, 30.5), (30.0, 29.0), (37.5, 30.0), (42.5, 32.0), (46.5, 28.5), (47.5, 31.5), (45.0, 34.0),
            (47.5, 37.0), (46.0, 38.5), (42.0, 35.5), (37.0, 37.0), (29.5, 37.5), (23.0, 36.5)]
    shape(P, W.catmull_closed(fish, 6), mixc(NONG, HUAQING, 0.25), ol=0.0, pool=0.3, pool_rgb=JIAO, alpha=0.75)
    P.dot(22.5, 32.6, 0.5, mixc(W_HUAQING, WHITE, 0.4))
    for k, r0 in enumerate((12.5, 17.5, 21.5)):  # 三圈浪，外圈结冰（白）
        a = np.linspace(0, 2 * math.pi, 120)
        wob = 0.6 * np.sin(a * (7 + 2 * k) + k)
        pts = np.stack([32.0 + (r0 + wob) * np.cos(a), 32.0 + (r0 + wob) * 0.92 * np.sin(a)], -1)
        rgb = mixc(HUAQING, WHITE, 0.15 + 0.35 * k)
        stroke(P, pts, (1.05 - 0.15 * k) * (0.75 + 0.25 * np.sin(a * 3 + k) ** 2), rgb, 0.95, dry=0.2, dry_start=0.0)
        for j in range(5 + 2 * k):  # 浪头上的冰碴
            aa = 2 * math.pi * j / (5 + 2 * k) + 0.3 * k
            P.dot(32.0 + (r0 + 1.0) * math.cos(aa), 32.0 + (r0 + 1.0) * 0.92 * math.sin(aa), 0.55, WHITE)


# ============================================================== 青藤 / 万木春


VINE_GREEN = mixc(SHILV, TENG, 0.15)
LEAF_GREEN = mixc(SHILV, W_SHILV, 0.2)


def vine_stroke(P, pts, hw=1.1):
    pts = np.asarray(pts, float)
    n = len(pts)
    stroke(P, pts, hw * (0.55 + 0.45 * np.linspace(1, 0, n)), mixc(VINE_GREEN, JIAO, 0.45))
    stroke(P, pts, hw * 0.55 * (0.55 + 0.45 * np.linspace(1, 0, n)), VINE_GREEN, 0.95)


def em_vine(P, evo):
    if not evo:
        # 青藤：一根藤从左下盘上来绕一圈，几片新叶，藤尖卷着一缕绿光往回流
        t = np.linspace(0, 1, 120)
        ang = math.radians(200) + t * math.radians(330)
        rad = 13.5 - 6.0 * t
        pts = np.stack([33.0 + rad * np.cos(ang) - 9.0 * (1 - t) ** 3, 31.0 + rad * np.sin(ang) + 10.0 * (1 - t) ** 3], -1)
        spiral = np.vstack([np.array([[15.0, 52.0], [17.5, 46.0]]), pts])
        glow_in(P, 33.0, 31.0, 10.0, mixc(W_SHILV, PAPER, 0.2), 0.45)
        vine_stroke(P, V.arc_resample(spiral, 140), 1.25)
        tip = pts[-1]
        tendril = [(tip[0] + 3.0 * math.cos(a) * (1 - a / 9), tip[1] + 3.0 * math.sin(a) * (1 - a / 9)) for a in np.linspace(0, 8, 40)]
        stroke(P, tendril, 0.4, VINE_GREEN, 0.9)
        for (i, ang_, L) in ((30, -60.0, 8.5), (62, 40.0, 8.0), (95, 160.0, 7.0), (18, 200.0, 6.5)):
            x, y = pts[i]
            leaf(P, x + 3.2 * math.cos(math.radians(ang_)), y + 3.2 * math.sin(math.radians(ang_)), ang_, L, 4.0, LEAF_GREEN)
        # 往回流的一缕绿光
        flow = V.bezier([(tip[0] + 1.0, tip[1] - 2.0), (44.0, 20.0), (49.0, 30.0), (44.0, 41.0)], 40)
        stroke(P, flow, 0.7 * W.brush_profile(40, 0.2, 0.6, 0.0), mixc(W_SHILV, WHITE, 0.45), 0.85)
        for x, y in ((49.0, 30.5), (46.0, 38.0)):
            P.dot(x, y, 0.55, mixc(W_SHILV, WHITE, 0.6))
        return
    # 万木春：藤从四周长进来，盘成一个圈，开着小花
    glow_in(P, 32.0, 32.0, 14.0, mixc(W_SHILV, PAPER, 0.2), 0.5)
    for k in range(4):
        a0 = math.radians(45 + 90 * k)
        t = np.linspace(0, 1, 80)
        r = 22.0 - 8.0 * t
        ang = a0 + t * math.radians(130)
        pts = np.stack([32.0 + r * np.cos(ang), 32.0 + r * np.sin(ang)], -1)
        vine_stroke(P, pts, 1.15)
        for j, tt in enumerate((0.25, 0.55, 0.85)):
            i = int(tt * 79)
            x, y = pts[i]
            out = math.degrees(ang[i]) + (60 if j % 2 else -60)
            leaf(P, x + 2.6 * math.cos(math.radians(out)), y + 2.6 * math.sin(math.radians(out)), out, 6.0, 3.2, LEAF_GREEN)
    for k in range(5):  # 小花：五瓣，白里透粉，花心藤黄
        a = math.radians(20 + 72 * k)
        cx, cy = 32.0 + 13.0 * math.cos(a), 32.0 + 13.0 * math.sin(a)
        for j in range(5):
            b = a + 2 * math.pi * j / 5
            P.dot(cx + 1.5 * math.cos(b), cy + 1.5 * math.sin(b), 1.15, mixc(WHITE, W_ZHUSHA, 0.35))
        P.dot(cx, cy, 0.75, TENG)


# ============================================================== 镇妖塔 / 玲珑塔


def paint_pagoda(P, cx, base_y, s, *, tiers=7, gold=False):
    """七层小塔（从下往上一层比一层小）：每层一道翘角的檐、一段塔身，顶上塔刹。返回 (塔顶 y, 每层的檐 y)。"""
    body_c = mixc(ZHONG, DAN, 0.35) if not gold else mixc(TENG, GOLD_HI, 0.3)
    eave_c = mixc(NONG, JIAO, 0.3) if not gold else mixc(TENG, GOLD_DK, 0.55)
    y = base_y
    eaves = []
    w0, h0 = 6.0 * s, 4.0 * s
    for k in range(tiers):
        f = 1.0 - 0.09 * k
        w, h = w0 * f, h0 * (1.0 - 0.06 * k)
        body = [(cx - w * 0.62, y), (cx + w * 0.62, y), (cx + w * 0.55, y - h), (cx - w * 0.55, y - h)]
        shape(P, body, body_c, ol=0.6 * s, pool=0.25, pool_rgb=ZHONG if not gold else GOLD_DK, wob=0.02)
        if gold:
            P.dot(cx, y - h * 0.5, 0.55 * s, mixc(WHITE, TENG, 0.3))
        else:
            P.dot(cx, y - h * 0.5, 0.5 * s, mixc(TENG, ZHESHI, 0.3))
        ey = y - h
        ew = w * 1.25
        eave = [(cx - ew - 0.8 * s, ey - 1.4 * s), (cx - ew * 0.5, ey - 0.2 * s), (cx + ew * 0.5, ey - 0.2 * s), (cx + ew + 0.8 * s, ey - 1.4 * s),
                (cx + ew * 0.6, ey - 1.6 * s), (cx - ew * 0.6, ey - 1.6 * s)]
        shape(P, eave, eave_c, ol=0.55 * s, ol_rgb=JIAO if not gold else mixc(GOLD_DK, JIAO, 0.5), pool=0.2, wob=0.02)
        eaves.append((ey, ew))
        y = ey - 1.6 * s
    stroke(P, W.seg_pts((cx, y), (cx, y - 4.5 * s), n=10), 0.45 * s, eave_c)
    for k in range(3):
        P.dot(cx, y - 1.2 * s - 1.2 * k * s, (0.9 - 0.15 * k) * s, mixc(TENG, GOLD_DK, 0.3))
    return y - 4.5 * s, eaves


def em_tower(P, evo):
    if not evo:
        # 镇妖塔：七层小塔往下压，塔底一圈墨色旋涡把几缕妖气往里吸，檐角挂着小铜铃
        for k in range(3):
            r0 = 13.0 - 3.6 * k
            a = np.linspace(0, 2 * math.pi * 0.85, 60) + k
            pts = np.stack([32.0 + r0 * np.cos(a), 49.0 + 0.32 * r0 * np.sin(a)], -1)
            stroke(P, pts, (0.9 - 0.15 * k) * W.brush_profile(60, 0.2, 0.6, 0.2), mixc(NONG, ZHESHI, 0.2), 0.9, dry=0.3, dry_start=0.6)
        for (x0, y0, x1, y1) in ((13.0, 40.0, 24.0, 47.0), (51.0, 41.0, 40.0, 47.5), (15.0, 53.5, 25.0, 50.5)):  # 被吸进去的妖气
            stroke(P, V.bezier([(x0, y0), ((x0 + x1) / 2, y0 - 2.0), (x1, y1)], 20), 0.7 * W.brush_profile(20, 0.6, 0.0, 0.0),
                   mixc(NONG, U.SOUL, 0.25), 0.8)
        top, eaves = paint_pagoda(P, 32.0, 46.0, 1.0)
        for ey, ew in eaves[::2]:  # 檐角的小铜铃
            for sg in (-1, 1):
                P.dot(32.0 + sg * (ew + 0.6), ey - 0.4, 0.55, mixc(TENG, GOLD_DK, 0.3))
        return
    # 玲珑塔：一座金塔悬在半空，塔身透出金光，四面的小妖被吸向塔
    glow_in(P, 32.0, 30.0, 18.0, mixc(TENG, PAPER, 0.25), 0.6)
    for k in range(8):  # 金光：放射的几道
        a = math.radians(22.5 + 45 * k)
        stroke(P, W.seg_pts((32.0 + 9.0 * math.cos(a), 30.0 + 9.0 * math.sin(a)), (32.0 + 17.0 * math.cos(a), 30.0 + 17.0 * math.sin(a)), n=12),
               0.5 * W.brush_profile(12, 0.0, 0.8, 0.0), mixc(TENG, WHITE, 0.4), 0.7)
    paint_pagoda(P, 32.0, 47.0, 1.05, gold=True)
    for (x, y, dx, dy) in ((14.0, 22.0, 4.0, 2.0), (50.0, 24.0, -4.0, 1.6), (15.0, 44.0, 4.2, -1.8), (49.5, 45.0, -4.0, -2.0)):
        P.dot(x, y, 1.7, mixc(NONG, JIAO, 0.3), 0.9)  # 小妖（墨团、两点白眼），身后拖一道往塔去的痕
        P.dot(x - 0.6, y - 0.4, 0.32, WHITE)
        P.dot(x + 0.6, y - 0.4, 0.32, WHITE)
        stroke(P, W.seg_pts((x - dx * 0.9, y - dy * 0.9), (x - dx * 0.25, y - dy * 0.25), n=10), 0.45 * W.brush_profile(10, 0.0, 0.8, 0.0),
               mixc(NONG, PAPER, 0.4), 0.7)


# ============================================================== 汇总


WEAPONS_NEW = {  # id: (名, 进化名, 五行, 画法)，与 assets/data/weapons.ron 一致
    "coin_sword": ("铜钱剑", "天罡", "metal", em_coin_sword),
    "sky_lantern": ("孔明灯", "万灯升", "fire", em_sky_lantern),
    "wave": ("沧浪", "北冥潮", "water", em_wave),
    "vine": ("青藤", "万木春", "wood", em_vine),
    "tower": ("镇妖塔", "玲珑塔", "earth", em_tower),
}


def specs():
    """[(文件名, id, 五行, 是否进化, meta 附加字段)]，顺序固定（种子按序号取）。"""
    out = []
    for wid, (name, evo_name, el, _fn) in WEAPONS_NEW.items():
        out.append((f"icon_{wid}", wid, el, False, {"kind": "weapon", "id": wid, "el": el, "name": name}))
        out.append((f"icon_{wid}_evo", wid, el, True, {"kind": "weapon_evo", "id": wid, "el": el, "name": evo_name}))
    return out


def make(index: int):
    _, wid, el, evo, _ = specs()[index]
    P = W.Painter(U.SIZE, U.SIZE, 12000 + 37 * index, ss=U.SS)
    U.frame_back(P, el, evo=evo)
    WEAPONS_NEW[wid][3](P, evo)
    U.frame_front(P, el, evo=evo)
    return P.image()


def main() -> dict:
    t0 = time.perf_counter()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    files, total = {}, 0
    for i, (fname, _wid, _el, _evo, extra) in enumerate(specs()):
        img = make(i)
        a = np.asarray(img)[..., 3]
        if a[0, 0] or a[0, -1] or a[-1, 0] or a[-1, -1]:  # 圆底外面必须透明
            raise SystemExit(f"{fname}: 圆底外面有颜色")
        fn = f"{fname}.png"
        V.save_png(img, OUT_DIR / fn)
        total += (OUT_DIR / fn).stat().st_size
        files[fn] = V.anchor_entry(img, (0.5, 0.5), color="full", blend="normal", tint=False, **extra, note=f"界面图标：{extra['name']}")
    meta = {
        "name": "ui",
        "generator": "art/post/ui_icons_new.py",
        "format": "PNG RGBA，直通（非预乘）alpha；全彩、正常混合、不染色（与 ui_icons.py 同一套框）",
        "px_per_unit": V.PPU,
        "display_px_1x": U.SIZE,
        "files": files,
    }
    (OUT_DIR / "meta.json").write_text(V.dump_json(meta), encoding="utf-8")
    print(f"写出 {len(files)} 个图标，共 {total / 1024:.1f} KB，用时 {time.perf_counter() - t0:.1f} s → {OUT_DIR}")
    return files


if __name__ == "__main__":
    main()
