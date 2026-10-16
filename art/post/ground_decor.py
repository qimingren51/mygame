#!/usr/bin/env python3
"""提灯夜行 · 第二批地面贴图：灵泉、妖潮裂隙（含叠加用的光）、芦苇、落叶、卵石、水洼、竹子；
M2.5 追加五行反应留下的区域：zone_lava（+ zone_lava_glow）熔岩、zone_mud 淤泥、zone_herb（+ zone_herb_glow）灵草。

不单独写盘：vfx_textures.py 的 main() 调用这里的 build()，和宣纸、晕染、草一起写进
art/out/<ASSETS_DIR_NAME>/ground/ 与同一份 meta.json（一个文件夹只有一个写 meta 的脚本）。
画法复用 weapon_textures.Painter（淡彩填色、手抖轮廓、干笔）与 vfx_textures 的笔触；
坐标都按 1 倍像素写，密度由 style.DENSITY 决定（见 vfx_textures.grid1 / noise1）。

单独预览（不写 assets，只出一张拼图到 art/out/review[@2x]/ground_decor_preview.png）：
  art/.venv/bin/python art/post/ground_decor.py

青丘追加（帧名前缀 qq_，只往后追加，前面的条目逐字节不变）：qq_bamboo_leaves_0..2 落竹叶、qq_shoots_0..1 竹笋（锚点在底边）、
qq_moss_0..1 苔点与地衣、qq_wash_0..1 兑花青石绿的淡墨晕、qq_fox_tracks 一行狐狸脚印。
月夜（只在 2 倍；1 倍逐字节不变）：leaves_0..1、pebbles_0..1、qq_bamboo_leaves_0..2、qq_moss_0..1、qq_fox_tracks
在各自生成处调浓一次（vfx_textures.moon_boost，对纸面的 L* 反差目标 +12%）。
青丘审图（读盘：地面装饰、vfx/mist_0..1、weapons/bamboo_spike，先跑 vfx_textures.py 和 weapon_textures.py）：
  LANTERN_ART_DENSITY=2 art/.venv/bin/python art/post/ground_decor.py --sample   # → art/out/review@2x/qq_2d_sample.png
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import vfx_textures as V  # noqa: E402
import weapon_textures as W  # noqa: E402

S = V.S
D = V.D
col, mixc, smoothstep = V.col, W.mixc, V.smoothstep
PAPER, PAPER_SH, WHITE = W.PAPER, W.PAPER_SH, W.WHITE
JIAO, NONG, ZHONG, DAN, QING = W.JIAO, W.NONG, W.ZHONG, W.DAN, W.QING
ZHUSHA, ZHESHI, HUAQING, SHILV, TENG = W.ZHUSHA, W.ZHESHI, W.HUAQING, W.SHILV, W.TENG
W_ZHUSHA, W_ZHESHI, W_HUAQING, W_SHILV, W_TENG = W.W_ZHUSHA, W.W_ZHESHI, W.W_HUAQING, W.W_SHILV, W.W_TENG

RIFT_TINT = "#D2386A"  # 裂隙光建议染色：偏紫的深朱砂


def stone_rgb(rng) -> np.ndarray:
    """几种石色：淡墨、清墨偏赭、重墨偏青。"""
    choices = (mixc(QING, PAPER, 0.2), mixc(DAN, W_ZHESHI, 0.45), mixc(mixc(ZHONG, DAN, 0.5), W_HUAQING, 0.2), mixc(W_ZHESHI, DAN, 0.3))
    return choices[int(rng.integers(len(choices)))]


def paint_stone(P: W.Painter, cx, cy, rx, ry, rgb, *, ol=0.8, shadow=0.2, moss=False):
    """一块卵石/垒石：不规则椭圆，上亮下暗，焦墨轮廓，底下一点接触影，可选几粒苔点。"""
    rng = P.rng
    th = np.linspace(0, 2 * math.pi, 40, endpoint=False)
    rr = 1.0 + V.angular_noise(rng, th, harmonics=(2, 3, 4), amp=0.12)
    poly = np.stack([cx + rx * rr * np.cos(th), cy + ry * rr * np.sin(th)], -1)
    poly = W.wobble(poly, rng, 0.08 * min(rx, ry) / 3.0, spacing=0.3)
    if shadow:
        sh = np.hypot((P.X - cx - 0.4) / (rx * 1.1), (P.Y - cy - ry * 0.75) / (ry * 0.55))
        P.lay.over(JIAO, shadow * smoothstep(1.0, 0.4, sh))
    d, t = P.sdf(poly)
    k = smoothstep(cy - ry * 0.9, cy + ry * 0.9, P.Y) * 0.8 + 0.25 * smoothstep(cx - rx, cx + rx, P.X)
    P.fill(d, mixc(mixc(rgb, PAPER, 0.4), mixc(rgb, ZHONG, 0.45), np.clip(k, 0, 1)), mottle=0.08, mottle_rgb=ZHONG, pool=0.2, pool_rgb=ZHONG, pool_w=0.6)
    if moss:
        for _ in range(int(rng.integers(1, 3))):
            P.dot(cx + rng.uniform(-0.5, 0.5) * rx, cy - ry * rng.uniform(0.4, 0.8), rng.uniform(0.35, 0.6), mixc(SHILV, JIAO, 0.45))
    P.outline(d, t, ol, mixc(JIAO, NONG, 0.2), jitter=0.3, dry=0.12)
    return d


# ============================================================== 灵泉


def make_spring() -> Image.Image:
    """灵泉：一汪浅泉。水面是兑了石绿的淡墨，中间深、边上浅，几圈若断若连的涟漪和几笔留白的反光；
    一圈垒石围着，石缝里几笔草。正常混合，锚点在中心。"""
    Wd, Hd = 160, 100
    P = W.Painter(Wd, Hd, 4100, ss=4)
    rng = P.rng
    cx, cy, rx, ry = 80.0, 50.0, 60.0, 31.0
    th = np.linspace(0, 2 * math.pi, 160, endpoint=False)
    rr = 1.0 + V.angular_noise(rng, th, harmonics=(2, 3, 4, 5), amp=0.05)
    pool = np.stack([cx + rx * rr * np.cos(th), cy + ry * rr * np.sin(th)], -1)
    d, t = P.sdf(pool, pad=6.0)
    # 外面一圈湿痕
    P.lay.over(ZHONG, 0.16 * np.exp(-np.maximum(d, 0) / 2.5) * (d > -0.5) * (d < 8))
    depth = smoothstep(0.0, 18.0, -d)
    n = V.noise1(rng, P.X.shape, 6.0 * P.ss)
    shallow = mixc(W_SHILV, PAPER, 0.25)
    deep = mixc(mixc(SHILV, HUAQING, 0.35), ZHONG, 0.45)
    water = mixc(shallow, deep, np.clip(depth * 0.9 + 0.08 * n, 0, 1))
    P.fill(d, water, 0.94, pool=0.35, pool_rgb=mixc(SHILV, JIAO, 0.5), pool_w=2.2)
    inside = P.cover(d + 1.0)
    # 涟漪：以偏左的一点为心，三圈断续的亮线
    rcx, rcy = cx - 10.0, cy - 1.0
    for k, (ax, alpha) in enumerate(((7.0, 0.55), (14.0, 0.45), (22.0, 0.32))):
        a0 = rng.uniform(0, 2 * math.pi)
        for seg in range(3):
            aa = np.linspace(a0 + seg * 2.1, a0 + seg * 2.1 + rng.uniform(1.1, 1.6), 50)
            pts = np.stack([rcx + ax * np.cos(aa), rcy + ax * 0.48 * np.sin(aa)], -1)
            P.line(pts, 0.42 * W.brush_profile(50, 0.3, 0.2), mixc(PAPER, WHITE, 0.5), alpha, clip=inside)
    # 反光：几笔横向的留白干笔
    for (x0, y0, L) in ((cx + 12, cy - 15, 22), (cx + 20, cy - 10, 13), (cx - 34, cy + 8, 10)):
        pts = V.bezier([(x0, y0), (x0 + L / 2, y0 - 0.6), (x0 + L, y0 + 0.2)], 40)
        P.line(pts, 0.75 * W.brush_profile(40, 0.6, 0.15), mixc(PAPER, WHITE, 0.6), 0.6, clip=inside, dry=0.45, dry_start=0.2)
    # 垒石：沿池边一圈，按 y 由后往前画；前面（下方）的石头大一些
    n_st = 17
    angs = np.sort((np.arange(n_st) + rng.uniform(-0.3, 0.3, n_st)) * 2 * math.pi / n_st)
    stones = []
    for a in angs:
        front = 0.5 + 0.5 * math.sin(a)
        sx = rng.uniform(6.0, 9.5) * (0.85 + 0.45 * front)
        sy = rng.uniform(3.8, 5.6) * (0.85 + 0.45 * front)
        rad = rng.uniform(1.0, 1.07)
        px, py = cx + rx * rad * math.cos(a), cy + ry * rad * math.sin(a) + 1.0
        stones.append((py, px, sx, sy))
    for py, px, sx, sy in sorted(stones):
        paint_stone(P, px, py, sx, sy, stone_rgb(rng), ol=0.85, shadow=0.18, moss=rng.random() < 0.35)
    # 石缝里的草
    for a in (math.radians(200), math.radians(335), math.radians(110)):
        bx, by = cx + rx * 1.02 * math.cos(a), cy + ry * 1.02 * math.sin(a) - 2.0
        for j in range(3):
            ang = (j - 1) * 0.5 + rng.normal(0, 0.15)
            L = rng.uniform(5, 8)
            tip = (bx + L * math.sin(ang), by - L * math.cos(ang))
            pts = V.bezier([(bx, by), (bx + 0.5 * L * math.sin(ang), by - 0.6 * L), tip], 30)
            P.line(pts, 0.55 * W.brush_profile(30, 1.0, 0.15, 0.0), mixc(SHILV, NONG, 0.5), dry=0.35, dry_start=0.5)
    return P.image()


# ============================================================== 妖潮裂隙


def rift_geometry(rng):
    """裂隙中线（略呈 S 形）与两侧锯齿状的半宽。"""
    c = V.bezier([(12.0, 46.0), (48.0, 33.0), (90.0, 52.0), (128.0, 33.0)], 220)
    tt = np.linspace(0, 1, len(c))
    base = 12.0 * np.sin(np.pi * tt) ** 0.85
    j1 = np.interp(tt, np.linspace(0, 1, 256), W.pnoise1(rng, 256, 9.0))
    j2 = np.interp(tt, np.linspace(0, 1, 256), W.pnoise1(rng, 256, 9.0))
    teeth_l = np.clip(np.interp(tt, np.linspace(0, 1, 512), W.pnoise1(rng, 512, 1.6)), 0, None)
    teeth_r = np.clip(np.interp(tt, np.linspace(0, 1, 512), W.pnoise1(rng, 512, 1.6)), 0, None)
    hl = base * (1 + 0.25 * j1) + 1.4 * teeth_l * np.sin(np.pi * tt) ** 0.5
    hr = base * (1 + 0.25 * j2) + 1.4 * teeth_r * np.sin(np.pi * tt) ** 0.5
    tan = np.gradient(c, axis=0)
    tan /= np.linalg.norm(tan, axis=1, keepdims=True)
    nrm = np.stack([-tan[:, 1], tan[:, 0]], -1)
    poly = np.vstack([c + nrm * hl[:, None], (c - nrm * hr[:, None])[::-1]])
    return c, poly, np.maximum(hl, hr)


def make_rift() -> tuple[Image.Image, Image.Image]:
    """妖潮裂隙：地上撕开的一道口子。焦墨的毛边（干笔、崩出的细裂纹、墨点），口子里由外到内
    焦墨 → 深紫红 → 朱砂亮芯。另出一张白色的 rift_glow（叠加，游戏里染色并做呼吸闪烁）。"""
    Wd, Hd = 140, 80
    P = W.Painter(Wd, Hd, 4200, ss=4)
    rng = P.rng
    c, poly, hw_max = rift_geometry(rng)
    d, t = P.sdf(poly, pad=10.0)
    f = V.stroke_fields(P.X, P.Y, c, hw_max)
    s = np.clip(np.abs(f["perp"]) / np.maximum(f["hw"], 0.5), 0, 1.5)
    s = V.fft_blur(s, V.sig(1.2 * P.ss))  # 中线采样点在弯的内侧会跳，平滑掉色带
    # 周围地面压暗（偏紫的淡墨晕）
    halo_rgb = mixc(ZHONG, mixc(ZHUSHA, HUAQING, 0.5), 0.25)
    n = V.noise1(rng, P.X.shape, 4.0 * P.ss)
    P.lay.over(halo_rgb, 0.22 * np.exp(-np.maximum(d, 0) / 6.0) * (d > 0) * (0.75 + 0.25 * n))
    # 崩出去的细裂纹
    for _ in range(14):
        i = int(rng.uniform(0.08, 0.92) * (len(c) - 1))
        side = rng.choice([-1.0, 1.0])
        tan = c[min(i + 1, len(c) - 1)] - c[max(i - 1, 0)]
        tan /= np.linalg.norm(tan) + 1e-9
        nrm = np.array([-tan[1], tan[0]]) * side
        start = c[i] + nrm * (hw_max[i] * 0.9)
        pts = [start]
        L = rng.uniform(4.0, 11.0)
        a = math.atan2(nrm[1], nrm[0]) + rng.normal(0, 0.4)
        walked = 0.0
        while walked < L:
            step = rng.uniform(1.5, 3.0)
            a2 = a + rng.normal(0, 0.45)
            pts.append(pts[-1] + step * np.array([math.cos(a2), math.sin(a2)]))
            walked += step
        dense = V.arc_resample(np.array(pts), 40)
        P.line(dense, 0.55 * np.linspace(1.0, 0.2, 40), JIAO, 0.9, dry=0.3, dry_start=0.4)
    # 口子里面：焦墨 → 深紫红 → 朱砂芯
    deep = mixc(mixc(ZHUSHA, HUAQING, 0.5), JIAO, 0.42)  # 紫红
    ember = mixc(ZHUSHA, W_ZHUSHA, 0.35)  # 深朱砂的亮芯
    inner = mixc(JIAO, deep, smoothstep(1.0, 0.55, s))
    inner = mixc(inner, ember, smoothstep(0.45, 0.05, s) * (0.75 + 0.25 * n))
    P.fill(d, inner)
    # 毛边：干笔墨线压在口子边上
    P.outline(d, t, 2.4, JIAO, center=0.2, jitter=0.5, dry=0.3)
    P.outline(d, t, 1.0, NONG, center=1.9, jitter=0.6, dry=0.55, alpha=0.7)
    # 溅出的墨点和几粒飘出的火星
    for _ in range(10):
        i = int(rng.uniform(0.05, 0.95) * (len(c) - 1))
        off = (hw_max[i] + rng.uniform(2.0, 7.0)) * rng.choice([-1.0, 1.0])
        tan = c[min(i + 1, len(c) - 1)] - c[max(i - 1, 0)]
        tan /= np.linalg.norm(tan) + 1e-9
        p = c[i] + np.array([-tan[1], tan[0]]) * off
        P.dot(p[0], p[1], rng.uniform(0.35, 0.8), JIAO, 0.85)
    for _ in range(5):
        i = int(rng.uniform(0.2, 0.8) * (len(c) - 1))
        p = c[i] + np.array([rng.uniform(-3, 3), -hw_max[i] - rng.uniform(2, 6)])
        P.dot(p[0], p[1], rng.uniform(0.35, 0.55), ember, 0.9)
    rift = P.image()

    # 叠加用的光：口子中线最亮，往两边淡，出口子边一点点
    G = V.grid1(Hd, Wd, 4)
    X, Y = G
    f2 = V.stroke_fields(X, Y, c, hw_max)
    s2 = np.abs(f2["perp"]) / np.maximum(f2["hw"], 0.5)
    along = np.interp(f2["t"], np.linspace(0, 1, 256), W.pnoise1(np.random.default_rng(4210), 256, 10.0))
    d2, _ = W.poly_sdf(X, Y, poly, pad=10.0)
    core = np.exp(-((s2 / 0.28) ** 2)) * (0.8 + 0.2 * along) * (d2 < 0)
    body = 0.55 * smoothstep(0.5, -2.5, d2) * smoothstep(1.1, 0.3, s2)
    halo = 0.28 * np.exp(-np.maximum(d2, 0) / 4.5) * (d2 > -1) * smoothstep(1.6, 0.6, s2)
    a = np.clip(np.maximum.reduce([core, body, halo]), 0, 1)
    a *= smoothstep(0.0, 0.08, f2["t"]) * smoothstep(1.0, 0.92, f2["t"]) * 0.7 + 0.3
    a *= (f2["over"] < 1e8)
    glow = W.white_image(a, 4)
    return rift, glow


# ============================================================== 芦苇、竹子（锚点在底边）


def make_reed(seed: int, n_stems: int, plumes: tuple[int, ...]) -> Image.Image:
    """芦苇：几根细秆，长叶子从秆上撇出、梢头下垂，钉头鼠尾、尾端飞白；个别秆顶一簇芦花（淡赭的干笔）。"""
    Wd, Hd = 40, 64
    P = W.Painter(Wd, Hd, seed, ss=6)
    rng = P.rng
    smudge = 0.15 * V.bump_window(np.hypot((P.X - 20.0) / 13.0, (P.Y - 62.8) / 2.0)) * smoothstep(-1.5, 1.5, V.noise1(rng, P.X.shape, 1.5 * P.ss) + 0.8)
    P.lay.over(DAN, smudge)
    slots = np.linspace(-1, 1, n_stems) * 0.75 + rng.uniform(-0.15, 0.15, n_stems)
    for i in rng.permutation(n_stems):
        u = slots[i]
        bx = 20.0 + 7.0 * u
        h = rng.uniform(42.0, 56.0) * (1.0 - 0.15 * abs(u))
        lean = 5.0 * u + rng.normal(0, 1.5)
        top = (bx + lean, 63.5 - h)
        stem = V.bezier([(bx, 63.6), (bx + lean * 0.2, 63.5 - h * 0.5), top], 80)
        depth = rng.uniform(0.0, 1.0)
        ink = mixc(mixc(ZHONG, ZHESHI, 0.2), JIAO, 0.35 + 0.5 * depth)
        P.line(stem, np.linspace(0.55, 0.28, 80), ink, 0.95, jitter=0.1)
        # 叶子
        for _ in range(int(rng.integers(1, 3))):
            ti = rng.uniform(0.2, 0.55)
            k = int(ti * 79)
            st = stem[k]
            side = rng.choice([-1.0, 1.0])
            L = rng.uniform(14.0, 22.0)
            up = np.array([side * 0.45, -1.0])
            up /= np.linalg.norm(up)
            ctrl = [st, st + up * L * 0.5, st + up * L * 0.8 + np.array([side * L * 0.35, 0.0]), st + np.array([side * L * 0.75, -L * 0.35])]
            pts = V.bezier(ctrl, 80)
            pts[:, 0] = np.clip(pts[:, 0], 2.0, Wd - 2.0)
            pts[:, 1] = np.maximum(pts[:, 1], 2.0)
            prof = (0.75 + 0.25 * np.sin(np.pi * np.clip(np.linspace(0, 1, 80) / 0.4, 0, 1) * 0.5)) * (1 - np.linspace(0, 1, 80)) ** 0.8
            leaf_ink = mixc(ink, mixc(SHILV, NONG, 0.4), 0.35 if rng.random() < 0.4 else 0.0)
            P.line(pts, 1.05 * prof + 0.05, leaf_ink, 0.9, dry=rng.uniform(0.4, 0.65), dry_start=0.45)
        # 芦花
        if i in plumes:
            hang = np.sign(lean + 0.01)
            for j in range(16):
                a0 = math.pi / 2 + hang * rng.uniform(0.3, 1.25)
                L = rng.uniform(4.5, 9.0)
                s0 = np.array(top) + np.array([rng.uniform(-0.8, 0.8), rng.uniform(0, 3.5)])
                tip = s0 + L * np.array([math.cos(a0) * 0.9, math.sin(a0) * 0.6])
                pts = V.bezier([s0, (s0 + tip) / 2 + np.array([hang * 0.4, -0.3]), tip], 24)
                rgbp = mixc(W_ZHESHI, PAPER, 0.15) if j % 3 else mixc(ZHESHI, ZHONG, 0.3)
                P.line(pts, 0.62 * W.brush_profile(24, 1.0, 0.2, 0.0), rgbp, 0.85, dry=0.35, dry_start=0.3)
    return P.image(keep_bottom=True)


def make_bamboo(seed: int, n_stalks: int, shoot: bool) -> Image.Image:
    """竹：短短几节竹竿（石绿兑墨，一节一笔，节处焦墨点节），节上撇出“个”字形竹叶；可带一个竹笋（赭石，焦墨勾箨）。"""
    Wd, Hd = 40, 56
    P = W.Painter(Wd, Hd, seed, ss=6)
    rng = P.rng
    P.lay.over(DAN, 0.15 * V.bump_window(np.hypot((P.X - 20.0) / 14.0, (P.Y - 55.0) / 2.0)))
    stalk_rgb = mixc(SHILV, NONG, 0.45)
    leaf_rgb = (mixc(NONG, SHILV, 0.25), mixc(SHILV, JIAO, 0.55), mixc(ZHONG, SHILV, 0.4))
    xs = np.linspace(-1, 1, n_stalks) * 6.0 if n_stalks > 1 else np.array([rng.uniform(-3, 3)])
    for si, x0 in enumerate(xs):
        bx = 20.0 + x0 + rng.uniform(-1.5, 1.5)
        h = rng.uniform(34.0, 48.0) * (1.0 if si % 2 == 0 else 0.8)
        lean = rng.normal(0, 1.2)
        n_seg = int(rng.integers(3, 5))
        ys = 55.6 - np.cumsum(np.r_[0, rng.uniform(0.85, 1.15, n_seg)]) / (1 + n_seg) * h * (n_seg + 1) / n_seg
        hw = 1.55 - 0.15 * si
        nodes = []
        for k in range(n_seg):
            y_a, y_b = ys[k] - 0.4, ys[k + 1] + 0.4
            xa, xb = bx + lean * (55.6 - y_a) / h, bx + lean * (55.6 - y_b) / h
            pts = V.bezier([(xa, y_a), ((xa + xb) / 2 + 0.2, (y_a + y_b) / 2), (xb, y_b)], 40)
            prof = 0.92 + 0.08 * np.cos(np.linspace(0, 1, 40) * np.pi * 2)
            P.line(pts, hw * prof, mixc(stalk_rgb, NONG, 0.15 * k), 0.95, dry=0.18, dry_start=0.7, jitter=0.06)
            nodes.append((xb, y_b))
        for (nx, ny) in nodes[:-1]:
            P.line(V.bezier([(nx - hw * 1.3, ny + 0.3), (nx, ny - 0.5), (nx + hw * 1.3, ny + 0.2)], 20), 0.42, JIAO, 0.95)
        # 竹叶：上面的节伸出一根小枝，枝头三四片叶子成“个”字向下散开
        for (nx, ny) in nodes[-2:][:: 1 if si % 2 else -1][: 1 + int(rng.random() < 0.6)]:
            side = rng.choice([-1.0, 1.0])
            twig_end = np.array([nx + side * rng.uniform(3.0, 5.0), ny - rng.uniform(2.0, 4.0)])
            twig_end[0] = np.clip(twig_end[0], 6.0, Wd - 6.0)
            P.line(W.seg_pts((nx, ny), twig_end, n=16), 0.32, NONG, 0.9)
            rgb_l = leaf_rgb[int(rng.integers(3))]
            for a_deg in rng.permutation([35.0, 80.0, 125.0, 160.0 if side < 0 else 15.0])[: int(rng.integers(3, 5))]:
                a = math.radians(a_deg + rng.normal(0, 8))
                L = rng.uniform(9.0, 13.0)
                dirv = np.array([math.cos(a), math.sin(a)])
                s0 = twig_end
                tip = s0 + dirv * L
                tip = np.clip(tip, 2.5, [Wd - 2.5, Hd - 3.0])
                bend = np.array([-dirv[1], dirv[0]]) * rng.uniform(-0.8, 0.8)
                pts = V.bezier([s0, s0 + dirv * L * 0.45 + bend, tip], 40)
                prof = np.interp(np.linspace(0, 1, 40), [0, 0.1, 0.32, 1.0], [0.25, 0.85, 1.0, 0.04])
                P.line(pts, 1.0 * prof, rgb_l, 0.95, dry=0.2, dry_start=0.65)
    if shoot:
        sx = 20.0 + rng.choice([-1.0, 1.0]) * 9.0
        body = W.catmull_closed([(sx - 4.0, 55.4), (sx - 3.2, 50.0), (sx - 1.2, 44.5), (sx + 0.4, 41.5), (sx + 1.6, 45.0), (sx + 3.6, 50.5), (sx + 4.0, 55.4)], 8)
        d, t = P.sdf(body)
        P.fill(d, mixc(W_ZHESHI, ZHESHI, smoothstep(44, 55, P.Y)), mottle=0.1, mottle_rgb=ZHONG, pool=0.3, pool_rgb=mixc(ZHESHI, JIAO, 0.4), pool_w=0.6)
        m = P.cover(d)
        for k in range(3):
            y0 = 52.5 - k * 3.6
            P.line(V.bezier([(sx - 3.6 + k * 0.9, y0 + 1.2), (sx, y0 - 0.6), (sx + 3.0 - k * 0.7, y0 - 2.4)], 20), 0.3, mixc(ZHESHI, JIAO, 0.55), clip=m)
        P.outline(d, t, 0.7, mixc(JIAO, NONG, 0.2))
    return P.image(keep_bottom=True)


# ============================================================== 落叶、卵石、水洼


def paint_ginkgo(P: W.Painter, x, y, ang, size, rgb):
    """银杏叶：扇形，外缘中间一道缺口，几条放射叶脉，短叶柄。"""
    rng = P.rng
    a = np.linspace(-0.95, 0.95, 40)
    rim = size * (1.0 - 0.18 * np.exp(-((a / 0.12) ** 2))) * (1 + 0.04 * np.sin(a * 9 + rng.uniform(0, 6)))
    fan = np.stack([rim * np.sin(a), -rim * np.cos(a)], -1)
    fan = np.vstack([[0.0, 0.0], fan])
    ca, sa = math.cos(ang), math.sin(ang)
    R = np.array([[ca, -sa], [sa, ca]])
    poly = fan @ R.T + [x, y]
    sh = poly + [0.6, 0.7]
    d, _ = P.sdf(sh)
    P.fill(d, JIAO, 0.12)
    d, t = P.sdf(poly)
    P.fill(d, mixc(rgb, mixc(rgb, ZHESHI, 0.5), smoothstep(0, size, np.hypot(P.X - x, P.Y - y))), mottle=0.08, mottle_rgb=ZHESHI, pool=0.3, pool_rgb=mixc(rgb, ZHESHI, 0.7), pool_w=0.5)
    m = P.cover(d)
    for av in np.linspace(-0.7, 0.7, 5):
        tip = np.array([size * 0.85 * math.sin(av), -size * 0.85 * math.cos(av)]) @ R.T + [x, y]
        P.line(W.seg_pts((x, y), tip, n=16), 0.15, mixc(ZHESHI, JIAO, 0.3), 0.6, clip=m)
    stem_end = np.array([0.0, size * 0.45]) @ R.T + [x, y]
    P.line(W.seg_pts((x, y), stem_end, n=12), 0.25, mixc(ZHESHI, JIAO, 0.4))
    P.outline(d, t, 0.5, mixc(ZHESHI, JIAO, 0.6), jitter=0.2)


def paint_leaf(P: W.Painter, x, y, ang, length, width, rgb):
    """柳叶形的落叶：杏仁形，中脉一线，叶柄，淡墨勾边，底下一点影子。"""
    base = np.array([x - 0.5 * length * math.cos(ang), y - 0.5 * length * math.sin(ang)])
    tip = np.array([x + 0.5 * length * math.cos(ang), y + 0.5 * length * math.sin(ang)])
    poly = W.almond(base, tip, width, 40, bulge=0.4, asym=P.rng.uniform(-0.15, 0.15))
    d, _ = P.sdf(poly + [0.6, 0.7])
    P.fill(d, JIAO, 0.12)
    d, t = P.sdf(poly)
    along = ((P.X - base[0]) * (tip - base)[0] + (P.Y - base[1]) * (tip - base)[1]) / (length**2)
    P.fill(d, mixc(rgb, mixc(rgb, ZHESHI, 0.45), smoothstep(0.2, 1.0, along)), mottle=0.1, mottle_rgb=ZHESHI, pool=0.3, pool_rgb=mixc(rgb, JIAO, 0.35), pool_w=0.5)
    m = P.cover(d)
    P.line(W.seg_pts(base, tip, n=20), 0.17, mixc(rgb, JIAO, 0.5), 0.8, clip=m)
    stem = base - (tip - base) / length * 2.2
    P.line(W.seg_pts(base, stem, n=8), 0.22, mixc(rgb, JIAO, 0.5))
    P.outline(d, t, 0.5, mixc(rgb, JIAO, 0.6), jitter=0.2)


def make_leaves(seed: int) -> Image.Image:
    """几片落叶散在地上：银杏（藤黄）、柳叶（赭石、朱砂淡彩、枯绿），叶脉淡墨。"""
    Wd, Hd = 64, 40
    P = W.Painter(Wd, Hd, seed, ss=6)
    rng = P.rng
    palette = (mixc(TENG, W_TENG, 0.4), W_ZHESHI, mixc(W_ZHUSHA, ZHUSHA, 0.35), mixc(W_SHILV, W_TENG, 0.5))
    spots = [(14, 14), (31, 24), (47, 13), (24, 31), (52, 29), (38, 10)]
    rng.shuffle(spots)
    for k, (sx, sy) in enumerate(spots[: int(rng.integers(4, 6))]):
        x, y = sx + rng.uniform(-3, 3), sy + rng.uniform(-2, 2)
        ang = rng.uniform(0, 2 * math.pi)
        if k % 3 == 0:
            paint_ginkgo(P, x, y, ang, rng.uniform(5.0, 6.5), palette[0])
        else:
            paint_leaf(P, x, y, ang, rng.uniform(9.0, 13.0), rng.uniform(3.6, 4.8), palette[1 + int(rng.integers(3))])
    return P.image()


def make_pebbles(seed: int) -> Image.Image:
    """一小撮卵石：大小不一，焦墨勾边，淡墨/赭石/青灰，接触影，个别带苔点。"""
    Wd, Hd = 48, 28
    P = W.Painter(Wd, Hd, seed, ss=6)
    rng = P.rng
    n = int(rng.integers(4, 7))
    items = []
    for i in range(n):
        rx = rng.uniform(3.6, 7.5) if i else 8.5
        ry = rx * rng.uniform(0.55, 0.75)
        x = np.clip(24 + rng.normal(0, 10), rx + 2, Wd - rx - 2)
        y = np.clip(14 + rng.normal(0, 4.0), ry + 2.5, Hd - ry - 3)
        items.append((y, x, rx, ry))
    for y, x, rx, ry in sorted(items):
        paint_stone(P, x, y, rx, ry, stone_rgb(rng), ol=0.75, shadow=0.22, moss=rng.random() < 0.3)
    return P.image()


def make_puddle() -> Image.Image:
    """小水洼：不规则的一汪重墨（中间略淡、边上积墨），边外一圈湿痕，水面上一两笔淡淡的留白反光。"""
    Wd, Hd = 72, 36
    P = W.Painter(Wd, Hd, 4500, ss=4)
    rng = P.rng
    th = np.linspace(0, 2 * math.pi, 120, endpoint=False)
    rr = 1.0 + V.angular_noise(rng, th, harmonics=(2, 3, 4, 5, 7), amp=0.12)
    poly = np.stack([36 + 30 * rr * np.cos(th), 18 + 12.5 * rr * np.sin(th)], -1)
    d, t = P.sdf(poly, pad=5.0)
    P.lay.over(DAN, 0.18 * np.exp(-np.maximum(d, 0) / 1.6) * (d > -0.5))
    n = V.noise1(rng, P.X.shape, 5.0 * P.ss)
    rgb = mixc(mixc(NONG, HUAQING, 0.18), JIAO, np.clip(0.25 + 0.25 * n, 0, 1))
    P.fill(d, rgb, 0.8, pool=0.55, pool_rgb=JIAO, pool_w=1.8)
    inside = P.cover(d + 1.5)
    for (x0, y0, L, al) in ((18, 12.0, 22, 0.55), (43, 20.5, 10, 0.35)):
        pts = V.bezier([(x0, y0), (x0 + L / 2, y0 - 0.8), (x0 + L, y0 - 0.3)], 40)
        P.line(pts, 0.8 * W.brush_profile(40, 0.5, 0.15), mixc(PAPER, W_HUAQING, 0.25), al, clip=inside, dry=0.45, dry_start=0.15)
    return P.image()


# ============================================================== 五行反应留下的地面区域（M2.5）
#
# 都按俯角压扁成横的扁圆（高 ≈ 宽 × 0.62，同 spring 和游戏里地上圆圈的 FLAT），游戏里等比缩放到反应的半径；
# 边缘柔和地化进纸里，没有硬边。radius_px 是扁圆横向的“有效半径”（区域的边大约在这里）。

ZONE_FLAT = 0.62


def zone_q(P: W.Painter, cx, cy, rx, ry, rng, amp=0.07):
    """到扁圆中心的归一化距离（1 = 边），边上带一点不规则的起伏。"""
    th = np.arctan2((P.Y - cy) / ry, (P.X - cx) / rx)
    wob = V.angular_noise(rng, th, harmonics=(2, 3, 4, 5, 7, 9), amp=amp)
    return np.hypot((P.X - cx) / rx, (P.Y - cy) / ry) * (1.0 + wob)


def voronoi(P: W.Painter, pts: np.ndarray, warp: tuple[np.ndarray, np.ndarray]):
    """各向同性的（按世界坐标，竖向先除以 FLAT 还原）沃罗诺伊：返回 (F1, F2, 最近点序号)，单位 1 倍像素。"""
    X = P.X + warp[0]
    Y = (P.Y + warp[1]) / ZONE_FLAT
    f1 = np.full(P.X.shape, 1e9)
    f2 = np.full(P.X.shape, 1e9)
    idx = np.zeros(P.X.shape, dtype=np.int64)
    for i, (px, py) in enumerate(pts):
        dd = np.hypot(X - px, Y - py / ZONE_FLAT)
        closer = dd < f1
        f2 = np.where(closer, f1, np.minimum(f2, dd))
        idx = np.where(closer, i, idx)
        f1 = np.where(closer, dd, f1)
    return f1, f2, idx


def make_zone_lava() -> tuple[Image.Image, Image.Image]:
    """熔岩：一摊冷了表皮的熔岩。焦墨兑赭的硬壳裂成一块块（沃罗诺伊），裂缝里是朱砂到藤黄的岩浆，
    当中两三处还没结壳的熔池；壳的外缘碎成小块，再往外一圈烤焦的淡赭，柔和地化进纸里。
    另出一张白色的 zone_lava_glow（叠加，染橙）：裂缝与熔池的光。"""
    Wd, Hd = 224, 144
    cx, cy, rx, ry = 112.0, 72.0, 100.0, 62.0
    P = W.Painter(Wd, Hd, 4800, ss=3)
    rng = P.rng
    q = zone_q(P, cx, cy, rx * 0.86, ry * 0.86, rng, amp=0.06)
    # 裂缝网
    pts = []
    while len(pts) < 46:
        x, y = rng.uniform(cx - rx, cx + rx), rng.uniform(cy - ry, cy + ry)
        if np.hypot((x - cx) / rx, (y - cy) / ry) < 0.95:
            pts.append((x, y))
    pts = np.array(pts)
    warp = (2.2 * V.noise1(rng, P.X.shape, 6.0 * P.ss), 2.2 * V.noise1(rng, P.X.shape, 6.0 * P.ss))
    f1, f2, idx = voronoi(P, pts, warp)
    gap = f2 - f1
    cw = 0.9 + 0.7 * smoothstep(-1.0, 1.0, V.noise1(rng, P.X.shape, 4.0 * P.ss))  # 裂缝宽窄不一
    crack = smoothstep(cw + 0.6, cw - 0.4, gap)
    heat_edge = np.exp(-gap / 2.6)  # 壳靠近裂缝的地方被烤红
    # 熔池：几团没结壳的
    pool = np.zeros(P.X.shape)
    for (px, py, pr) in ((cx - 18.0, cy + 4.0, 15.0), (cx + 24.0, cy - 8.0, 10.0), (cx + 6.0, cy + 20.0, 7.0)):
        dpq = np.hypot((P.X - px) / pr, (P.Y - py) / (pr * ZONE_FLAT)) + 0.18 * V.noise1(rng, P.X.shape, 2.5 * P.ss)
        pool = np.maximum(pool, smoothstep(1.0, 0.75, dpq))
    crust_in = smoothstep(1.0, 0.92, q)  # 壳的范围
    # 外缘碎块：壳的边上有的块缺掉
    tone = rng.uniform(0.0, 1.0, len(pts))[idx]
    frag = smoothstep(0.84, 0.97, q) * (tone > 0.45)
    plate = crust_in * (1.0 - frag) * (1.0 - crack) * (1.0 - pool)
    # 颜色
    n = V.noise1(rng, P.X.shape, 1.2 * P.ss)
    crust_rgb = mixc(mixc(JIAO, ZHESHI, 0.25), mixc(NONG, ZHESHI, 0.35), np.clip(0.35 + 0.25 * n + 0.3 * tone, 0, 1))
    crust_rgb = mixc(crust_rgb, mixc(ZHUSHA, JIAO, 0.45), np.clip(heat_edge * 0.8, 0, 1))
    molten = V.ramp(np.clip(0.55 + 0.45 * np.exp(-gap / 0.8), 0, 1), V.FLAME_STOPS)
    pool_rgb = V.ramp(np.clip(0.42 + 0.3 * pool + 0.1 * V.noise1(rng, P.X.shape, 1.5 * P.ss), 0, 1), V.FLAME_STOPS)
    # 烤焦的外圈：淡赭兑淡墨，往外渐淡
    scorch = 0.55 * smoothstep(1.22, 0.95, q) * (0.8 + 0.2 * V.noise1(rng, P.X.shape, 3.0 * P.ss))
    P.lay.over(mixc(mixc(ZHESHI, ZHONG, 0.45), PAPER, 0.15), np.clip(scorch, 0, 1))
    P.lay.over(mixc(ZHUSHA, JIAO, 0.4), 0.85 * crust_in * np.maximum(crack, frag * 0.4))
    P.lay.over(molten, crust_in * crack * (1.0 - frag))
    P.lay.over(pool_rgb, pool * crust_in)
    P.lay.over(crust_rgb, 0.97 * plate)
    # 壳面：几道干笔皴（只在壳上）
    for _ in range(26):
        x0, y0 = rng.uniform(cx - rx * 0.8, cx + rx * 0.8), rng.uniform(cy - ry * 0.7, cy + ry * 0.7)
        L = rng.uniform(5.0, 11.0)
        ang = rng.uniform(-0.4, 0.4)
        p1 = (x0 + L * math.cos(ang), y0 + L * math.sin(ang) * ZONE_FLAT)
        P.line(V.bezier([(x0, y0), ((x0 + p1[0]) / 2, (y0 + p1[1]) / 2 - 0.6), p1], 20), 0.45 * W.brush_profile(20, 0.6, 0.3), mixc(NONG, QING, 0.3), 0.5, clip=plate, dry=0.5, dry_start=0.2)
    # 熔池里一两道暗的流纹、零星火星
    for (px, py, pr) in ((cx - 18.0, cy + 4.0, 15.0), (cx + 24.0, cy - 8.0, 10.0)):
        a = np.linspace(0.3, 2.6, 30)
        P.line(np.stack([px + 0.55 * pr * np.cos(a), py + 0.55 * pr * ZONE_FLAT * np.sin(a)], -1), 0.5, mixc(ZHUSHA, JIAO, 0.2), 0.6, clip=pool)
    for _ in range(16):
        a = rng.uniform(0, 2 * math.pi)
        rr = rng.uniform(0.9, 1.08)
        P.dot(cx + rx * 0.86 * rr * math.cos(a), cy + ry * 0.86 * rr * math.sin(a), rng.uniform(0.4, 0.9), mixc(ZHUSHA, TENG, rng.uniform(0.2, 0.7)), 0.85)
    lava = P.image()
    # 叠加的光：裂缝、熔池，外加一圈柔光
    hot = crust_in * np.maximum(crack * (1.0 - frag) * (0.65 + 0.35 * np.exp(-gap / 0.8)), pool)
    soft = V.fft_blur(hot, V.sig(2.5 * P.ss))
    a = np.clip(np.maximum(hot, 0.55 * soft / max(soft.max(), 1e-6)), 0, 1)
    glow = W.white_image(a, P.ss, dither_seed=4801)
    return lava, glow


def make_zone_mud() -> Image.Image:
    """淤泥：一大摊湿泥。焦墨兑赭的泥面（中间稀、积着一层泛青的水光），边上积得更深、往外渗出一圈湿痕；
    面上几圈涟漪（亮的湿光压一道暗），冒几个泥泡，几笔留白的水光，边外溅几点泥。"""
    Wd, Hd = 240, 152
    cx, cy, rx, ry = 120.0, 76.0, 106.0, 66.0
    P = W.Painter(Wd, Hd, 4900, ss=3)
    rng = P.rng
    q = zone_q(P, cx, cy, rx * 0.86, ry * 0.86, rng, amp=0.08)
    n1 = V.noise1(rng, P.X.shape, 8.0 * P.ss)
    n2 = V.noise1(rng, P.X.shape, 2.5 * P.ss)
    # 湿痕：泥外一圈淡赭墨，往外淡出
    P.lay.over(mixc(mixc(ZHESHI, ZHONG, 0.55), PAPER, 0.15), 0.34 * smoothstep(1.22, 0.97, q) * (0.85 + 0.15 * n2))
    body = smoothstep(1.0, 0.9, q + 0.015 * n2)
    mud = mixc(mixc(ZHESHI, JIAO, 0.62), mixc(ZHESHI, JIAO, 0.8), np.clip(0.5 + 0.3 * n1 + 0.1 * n2, 0, 1))
    mud = mixc(mud, mixc(ZHESHI, JIAO, 0.9), smoothstep(0.78, 1.0, q) * 0.8)  # 边上积得深
    # 中间几片积水：泛青的水光，边上柔
    water = smoothstep(0.45, 1.3, n1 + 0.4 * smoothstep(0.7, 0.2, q)) * smoothstep(0.85, 0.6, q)
    mud = mixc(mud, mixc(mixc(HUAQING, ZHONG, 0.55), JIAO, 0.25), np.clip(water * 0.75, 0, 1))
    P.lay.over(mud, 0.96 * body)
    # 涟漪：两处，各三圈断续的弧，亮的湿光下面压一道暗
    for (ox, oy, rad0) in ((cx - 26.0, cy - 6.0, 8.0), (cx + 32.0, cy + 12.0, 6.5), (cx - 2.0, cy + 26.0, 5.0)):
        for k in range(3):
            rr = rad0 * (1.0 + 0.85 * k)
            a0 = rng.uniform(0, 2 * math.pi)
            for seg in range(3):
                a = np.linspace(a0 + seg * 2.1, a0 + seg * 2.1 + rng.uniform(1.1, 1.7), 40)
                pts = np.stack([ox + rr * np.cos(a), oy + rr * ZONE_FLAT * np.sin(a)], -1)
                P.line(pts + [0.0, 0.7], 0.6 * W.brush_profile(40, 0.3, 0.3), JIAO, 0.55, clip=body)
                P.line(pts, 0.5 * W.brush_profile(40, 0.3, 0.3), mixc(mixc(W_ZHESHI, PAPER, 0.4), W_HUAQING, 0.35), 0.8 - 0.15 * k, clip=body)
    # 泥泡
    for _ in range(11):
        a = rng.uniform(0, 2 * math.pi)
        rr = rng.uniform(0.1, 0.78)
        bx, by = cx + rx * 0.86 * rr * math.cos(a), cy + ry * 0.86 * rr * math.sin(a)
        br = rng.uniform(1.0, 2.6)
        P.dot(bx, by, br, mixc(ZHESHI, JIAO, 0.55), 0.95, ry=br * 0.75)
        e = W.ellipse_pts(bx, by, br, br * 0.75, 30)
        P.line(V.arc_resample(np.vstack([e, e[:1]]), 40), 0.25, JIAO, 0.85)
        P.dot(bx - 0.35 * br, by - 0.3 * br, 0.3 * br, mixc(PAPER, W_HUAQING, 0.3), 0.95)
    # 水光：几笔横向的留白干笔
    for (x0, y0, L) in ((cx - 62.0, cy - 30.0, 32.0), (cx + 6.0, cy - 38.0, 24.0), (cx + 48.0, cy - 16.0, 20.0), (cx - 44.0, cy + 18.0, 18.0), (cx + 20.0, cy + 34.0, 14.0)):
        pts = V.bezier([(x0, y0), (x0 + L / 2, y0 - 1.0), (x0 + L, y0 + 0.3)], 40)
        P.line(pts, 1.0 * W.brush_profile(40, 0.6, 0.15), mixc(mixc(PAPER, WHITE, 0.3), W_HUAQING, 0.35), 0.55, clip=body, dry=0.5, dry_start=0.15)
    # 溅出的泥点
    for _ in range(24):
        a = rng.uniform(0, 2 * math.pi)
        rr = rng.uniform(1.0, 1.2)
        P.dot(cx + rx * 0.86 * rr * math.cos(a), cy + ry * 0.86 * rr * math.sin(a), rng.uniform(0.4, 1.3), mixc(ZHESHI, JIAO, 0.7), 0.85)
    return P.image()


def make_zone_herb() -> tuple[Image.Image, Image.Image]:
    """灵草：地上冒出一片灵草。底下一层石绿的淡彩，上面一丛丛短草（石绿兑墨、钉头鼠尾），几根卷须盘着（缠住妖物），
    不少草尖亮着一点青白的灵光。另出一张白色的 zone_herb_glow（叠加，染青绿）：草尖的光和一层淡淡的地光。"""
    Wd, Hd = 208, 132
    cx, cy, rx, ry = 104.0, 70.0, 92.0, 57.0
    P = W.Painter(Wd, Hd, 5000, ss=3)
    rng = P.rng
    q = zone_q(P, cx, cy, rx * 0.86, ry * 0.86, rng, amp=0.08)
    n = V.noise1(rng, P.X.shape, 5.0 * P.ss)
    patch = smoothstep(1.2, 0.7, q) * (0.75 + 0.25 * n)
    P.lay.over(mixc(W_SHILV, PAPER, 0.15), 0.5 * np.clip(patch, 0, 1))
    P.lay.over(mixc(SHILV, ZHONG, 0.3), 0.18 * smoothstep(0.9, 0.3, q) * smoothstep(0.2, 1.2, n))
    tufts = []
    while len(tufts) < 34:
        x, y = rng.uniform(cx - rx, cx + rx), rng.uniform(cy - ry, cy + ry)
        if np.hypot((x - cx) / (rx * 0.86), (y - cy) / (ry * 0.86)) < 0.92:
            tufts.append((y, x))
    tips = []
    greens = (mixc(SHILV, JIAO, 0.35), mixc(SHILV, NONG, 0.5), mixc(mixc(SHILV, W_SHILV, 0.5), ZHONG, 0.2), mixc(NONG, SHILV, 0.3))
    for y, x in sorted(tufts):
        k = int(rng.integers(3, 6))
        P.dot(x, y + 0.3, 4.5, mixc(SHILV, JIAO, 0.5), 0.3, ry=1.3)
        for j in range(k):
            ang = (j - (k - 1) / 2) * 0.38 + rng.normal(0, 0.12)
            L = rng.uniform(10.0, 17.0) * (1.0 - 0.15 * abs(ang))
            bend = rng.uniform(-0.35, 0.35)
            root = np.array([x + rng.uniform(-1.2, 1.2), y])
            d = np.array([math.sin(ang), -math.cos(ang)])
            side = np.array([-d[1], d[0]])
            tip = root + d * L + side * bend * L * 0.4
            pts = V.bezier([root, root + d * L * 0.5, tip], 30)
            P.line(pts, 0.9 * W.brush_profile(30, 1.0, 0.1, 0.0), greens[int(rng.integers(len(greens)))], 0.95, dry=0.3, dry_start=0.6)
            if rng.random() < 0.35:
                tips.append(tip)
    # 卷须：几根盘起来的藤
    for _ in range(5):
        a = rng.uniform(0, 2 * math.pi)
        rr = rng.uniform(0.2, 0.7)
        sx, sy = cx + rx * 0.86 * rr * math.cos(a), cy + ry * 0.86 * rr * math.sin(a)
        th = np.linspace(0, 2.2 * math.pi, 60)
        r_ = 7.0 * (1 - th / th[-1]) + 0.8
        sgn = rng.choice([-1.0, 1.0])
        spiral = np.stack([sx + sgn * r_ * np.cos(th), sy - 4.0 + r_ * np.sin(th) * 0.8], -1)
        P.line(np.vstack([[(sx, sy + 3.0)], spiral]), 0.6 * np.linspace(1.0, 0.45, 61), mixc(SHILV, JIAO, 0.45), 0.95)
        tips.append(spiral[-1])
    glow_pts = np.array(tips)
    for (x, y) in glow_pts:
        P.dot(x, y, 1.25, mixc(mixc(W_SHILV, WHITE, 0.6), col(S.SOUL_LIGHT), 0.25), 0.95)
    herb = P.image()
    # 叠加的光：草尖一点、地上一层很淡的光
    a = 0.16 * smoothstep(1.05, 0.5, q)
    for (x, y) in glow_pts:
        a = np.maximum(a, np.exp(-(((P.X - x) ** 2 + (P.Y - y) ** 2) / 3.5)))
    glow = W.white_image(np.clip(a, 0, 1), P.ss, dither_seed=5001)
    return herb, glow


# ============================================================== 青丘的地面（帧名前缀 qq_，只往后追加）
#
# 青丘是竹海里的狐村：落了一地的竹叶、刚冒头的竹笋、苔点、兑了花青石绿的淡墨晕、一行狐狸脚印。
# 画法与上面的落叶、卵石、竹子一致（Painter：淡彩填色、手抖轮廓、干笔）；长夜里以墨为主，颜色压得很淡。

QQ_FLAT = 0.7  # 狐狸脚印按地面透视压扁（比反应区域的 0.62 略松，小脚印才认得出）


def paint_bamboo_leaf(P: W.Painter, x, y, ang, length, width, rgb, *, curl=0.0, shadow=0.12, vein=True):
    """一片落在地上的竹叶：披针形，叶柄端圆钝、最宽处靠后、长长地收成尖；略弯，中脉一线，淡墨勾边，底下一点影子。"""
    s = np.linspace(0.0, 1.0, 48)
    # 叶形：靠叶柄 30% 处最宽，叶尖细长
    prof = 0.5 * width * np.sin(np.pi * np.clip(s, 0, 1) ** 0.62) ** 0.9 * (1.0 - 0.25 * s)
    bend = curl * length * (s - 0.5) ** 2
    up = np.stack([s * length, bend + prof], -1)
    dn = np.stack([s * length, bend - prof], -1)
    loc = np.vstack([up, dn[::-1][1:-1]]) - [0.5 * length, 0.0]
    ca, sa = math.cos(ang), math.sin(ang)
    R = np.array([[ca, -sa], [sa, ca]])
    poly = loc @ R.T + [x, y]
    if shadow:
        d, _ = P.sdf(poly + [0.5, 0.6])
        P.fill(d, JIAO, shadow)
    d, t = P.sdf(poly)
    base = np.array([x, y]) - 0.5 * length * np.array([ca, sa])
    along = np.clip(((P.X - base[0]) * ca + (P.Y - base[1]) * sa) / length, 0, 1)
    P.fill(d, mixc(rgb, mixc(rgb, ZHESHI, 0.35), smoothstep(0.3, 1.0, along)), mottle=0.12, mottle_rgb=mixc(ZHESHI, ZHONG, 0.5),
           pool=0.3, pool_rgb=mixc(rgb, JIAO, 0.4), pool_w=0.45)
    m = P.cover(d)
    if vein:
        mid = np.stack([s * length - 0.5 * length, bend], -1) @ R.T + [x, y]
        P.line(mid[2:-6], 0.13, mixc(rgb, JIAO, 0.45), 0.75, clip=m)
    stem = base - 1.6 * np.array([ca, sa]) + np.array([-sa, ca]) * curl * 0.6
    P.line(W.seg_pts(base, stem, n=8), 0.2, mixc(rgb, JIAO, 0.5))
    P.outline(d, t, 0.5, mixc(rgb, JIAO, 0.72), jitter=0.2)


# 落叶的颜色：枯黄、赭、旧了的灰，少数还带一点石绿（墨为主，颜色很淡）
QQ_LEAF_RGB = (
    mixc(mixc(W_TENG, W_ZHESHI, 0.55), DAN, 0.15),  # 枯黄
    mixc(W_ZHESHI, ZHESHI, 0.3),  # 赭
    mixc(mixc(DAN, QING, 0.5), W_ZHESHI, 0.25),  # 旧叶，灰
    mixc(mixc(W_SHILV, DAN, 0.35), W_TENG, 0.15),  # 刚落的，灰绿
    mixc(mixc(SHILV, ZHONG, 0.35), W_ZHESHI, 0.2),  # 深一点的绿
)


def make_qq_bamboo_leaves(seed: int, Wd: int, Hd: int, n: int, *, axis: float, spread: float, elong: float) -> Image.Image:
    """一堆被风扫到一起的竹叶：大致顺着风向（axis）排，有的叠在一起，中间密边上疏；底下一抹潮湿的淡墨。"""
    P = W.Painter(Wd, Hd, seed, ss=6)
    rng = P.rng
    cx, cy = Wd / 2, Hd / 2
    ca, sa = math.cos(axis), math.sin(axis)
    # 潮湿的地：一抹很淡的墨，沿堆的方向拉长
    u = ((P.X - cx) * ca + (P.Y - cy) * sa) / (0.42 * Wd)
    v = (-(P.X - cx) * sa + (P.Y - cy) * ca) / (0.30 * Hd)
    damp = V.bump_window(np.hypot(u, v)) * smoothstep(-1.2, 1.2, V.noise1(rng, P.X.shape, 3.0 * P.ss) + 0.4)
    P.lay.over(DAN, 0.10 * damp)
    leaves = []
    for _ in range(n):
        # 堆的中心密：沿 axis 方向近似正态、横向更窄
        a_ = rng.normal(0, 0.30) * elong
        b_ = rng.normal(0, 0.22)
        x = cx + (a_ * ca - b_ * sa) * Wd * 0.5
        y = cy + (a_ * sa + b_ * ca) * Hd * 0.5
        L = rng.uniform(10.0, 14.5)
        wdt = L * rng.uniform(0.17, 0.22)
        ang = axis + rng.normal(0, spread) + (math.pi if rng.random() < 0.35 else 0.0)
        # 不出框：叶尖、叶柄都离边至少 2.5 像素
        hx, hy = 0.5 * L * abs(math.cos(ang)) + 2.5, 0.5 * L * abs(math.sin(ang)) + 2.5
        x, y = float(np.clip(x, hx, Wd - hx)), float(np.clip(y, hy, Hd - hy))
        k = int(rng.choice(len(QQ_LEAF_RGB), p=(0.3, 0.22, 0.22, 0.16, 0.10)))
        leaves.append((x, y, ang, L, wdt, k, rng.uniform(-0.12, 0.12)))
    # 先画下面的（离中心远的、旧的灰叶在下）
    order = sorted(range(n), key=lambda i: (leaves[i][5] != 2, -abs(leaves[i][0] - cx) - abs(leaves[i][1] - cy) * 2))
    for i in order:
        x, y, ang, L, wdt, k, curl = leaves[i]
        paint_bamboo_leaf(P, x, y, ang, L, wdt, QQ_LEAF_RGB[k], curl=curl)
    return P.image()


def paint_shoot(P: W.Painter, x, y0, h, b, lean, *, tone: float = 0.0):
    """一根竹笋：下宽上尖、略弯的笋身，一层层箨（笋壳）交替包着，壳上褐斑，笋尖几片墨绿的箨叶。
    tone 0..1：越大颜色越深（老一点的笋）。"""
    rng = P.rng

    def cx_at(f):  # 笋身中线：根直、上段弯向 lean 一侧（像牛角）
        return x + lean * f ** 1.8

    def half_at(f):  # 半宽：根部圆鼓，往上收尖
        return b * (1.0 - f) ** 0.62 * (0.92 + 0.3 * np.sin(np.pi * np.clip(f / 0.42, 0, 1)) * (f < 0.42))

    fs = np.linspace(0.0, 1.0, 40)
    left = np.stack([cx_at(fs) - half_at(fs), y0 - fs * h], -1)
    right = np.stack([cx_at(fs) + half_at(fs), y0 - fs * h], -1)
    body = np.vstack([left, right[::-1][1:]]) + [[0.0, 0.4]]
    d, t = P.sdf(body)
    hh = np.clip((y0 - P.Y) / h, 0, 1)  # 0 根 .. 1 尖
    base_rgb = mixc(mixc(W_ZHESHI, ZHESHI, 0.4 + 0.3 * tone), mixc(DAN, JIAO, 0.3), 0.22 + 0.12 * tone)
    top_rgb = mixc(mixc(W_ZHESHI, W_SHILV, 0.5), DAN, 0.2)
    rgb = mixc(base_rgb, top_rgb, smoothstep(0.3, 1.0, hh))
    # 左亮右暗（光从左上来），和卵石一致
    rgb = mixc(rgb, mixc(rgb, ZHONG, 0.5), smoothstep(x - 0.3 * b, x + 1.1 * b, P.X) * 0.75)
    P.fill(d, rgb, mottle=0.16, mottle_rgb=mixc(ZHESHI, JIAO, 0.5), pool=0.35, pool_rgb=mixc(ZHESHI, JIAO, 0.55), pool_w=0.6)
    m = P.cover(d)
    # 箨：一片片尖头的壳从下往上叠，左右错开。每片外壳的边是一道“人”字形的弧（尖朝上），
    # 弧外（下面那片被压住的地方）一线深，弧里（这片壳）一道亮
    n_sh = max(3, int(round(h / 5.5)))
    for k in range(n_sh):
        f_tip = min(0.97, (k + 1.2) / (n_sh + 0.5))
        f_lo = max(0.0, f_tip - 0.42)
        side = 1.0 if k % 2 == 0 else -1.0
        apex = np.array([cx_at(f_tip) + side * 0.18 * half_at(f_tip - 0.1), y0 - f_tip * h])
        f_l = f_lo + (0.1 if side > 0 else 0.0)
        f_r = f_lo + (0.0 if side > 0 else 0.1)
        pl = np.array([cx_at(f_l) - half_at(f_l) * 1.05, y0 - f_l * h])
        pr = np.array([cx_at(f_r) + half_at(f_r) * 1.05, y0 - f_r * h])
        for p_side, bulge in ((pl, -1.0), (pr, 1.0)):
            mid = (p_side + apex) / 2 + np.array([bulge * 0.12 * half_at(f_lo), 0.06 * h])
            arc = V.bezier([p_side, mid, apex], 24)
            P.line(arc + [0.0, -0.45], 0.3, mixc(top_rgb, PAPER, 0.45), 0.45, clip=m)
            P.line(arc, 0.24 * W.brush_profile(24, 0.4, 0.5), mixc(ZHESHI, JIAO, 0.7), 0.85, clip=m)
    # 笋壳上的褐斑（下半多）
    for _ in range(int(h * 0.6)):
        fy = rng.uniform(0.03, 0.7) ** 1.3
        px = cx_at(fy) + rng.uniform(-0.8, 0.8) * half_at(fy)
        P.dot(px, y0 - fy * h, rng.uniform(0.2, 0.42), mixc(ZHESHI, JIAO, 0.72), 0.8, ry=rng.uniform(0.16, 0.3), clip=m)
    P.outline(d, t, 0.5, mixc(JIAO, NONG, 0.25), jitter=0.3, dry=0.18)
    # 笋尖：两三片墨绿的箨叶
    tip = np.array([x + lean, y0 - h])
    for a_deg, L in ((-100 + rng.normal(0, 8), rng.uniform(3.0, 4.5)), (-62 + rng.normal(0, 8), rng.uniform(2.6, 4.0)), (-128 + rng.normal(0, 8), rng.uniform(2.0, 3.2))):
        a = math.radians(a_deg) + 0.04 * lean
        e = tip + L * np.array([math.cos(a), math.sin(a)])
        e[1] = max(e[1], 1.8)
        P.line(V.bezier([tip + [0.0, 0.8], (tip + e) / 2 + [0.25, 0.0], e], 20), 0.42 * W.brush_profile(20, 1.0, 0.1, 0.0),
               mixc(SHILV, JIAO, 0.55), 0.95)


def make_qq_shoots(seed: int, Wd: int, Hd: int, shoots) -> Image.Image:
    """几根刚冒头的竹笋：根下一小堆翻起的土（淡墨、几粒土块），旁边一两片落叶。锚点在底边。"""
    P = W.Painter(Wd, Hd, seed, ss=6)
    rng = P.rng
    y0 = Hd - 0.6
    # 翻起的土：一抹淡墨，中间略鼓
    mound = V.bump_window(np.hypot((P.X - Wd / 2) / (0.44 * Wd), (P.Y - y0 + 0.6) / 3.2))
    P.lay.over(mixc(DAN, W_ZHESHI, 0.3), 0.32 * mound * smoothstep(-1.4, 1.4, V.noise1(rng, P.X.shape, 1.4 * P.ss) + 0.6))
    for (sx, h, b, lean, tone) in sorted(shoots, key=lambda s: s[1]):  # 矮的在后
        paint_shoot(P, Wd / 2 + sx, y0 - 0.2, h, b, lean, tone=tone)
    # 土块与苔点
    for _ in range(int(rng.integers(4, 7))):
        px = Wd / 2 + rng.uniform(-0.42, 0.42) * Wd
        P.dot(px, y0 - rng.uniform(0.3, 1.6), rng.uniform(0.45, 0.9), mixc(ZHONG, JIAO, rng.uniform(0.2, 0.8)), 0.9, ry=rng.uniform(0.35, 0.6))
    # 一片落下的竹叶靠在根边
    paint_bamboo_leaf(P, Wd / 2 + rng.choice([-1.0, 1.0]) * 0.3 * Wd, y0 - 1.8, rng.uniform(-0.25, 0.25), 9.0, 1.8, QQ_LEAF_RGB[0], shadow=0.0)
    return P.image(keep_bottom=True)


def make_qq_moss(seed: int, Wd: int, Hd: int, n_clumps: int, n_lichen: int) -> Image.Image:
    """苔点与地衣：底下一层兑石绿的淡墨，上面一簇簇点出的苔点（浓墨为主，夹几点石绿，大小错落、横点多），
    再有几圈灰绿的地衣（不规则的环，边上碎点）。按地面透视横向略宽。"""
    P = W.Painter(Wd, Hd, seed, ss=6)
    rng = P.rng
    cx, cy = Wd / 2, Hd / 2
    # 底：一整块兑石绿的淡墨，边缘柔和起伏
    th = np.arctan2((P.Y - cy) / (0.36 * Hd), (P.X - cx) / (0.42 * Wd))
    q = np.hypot((P.X - cx) / (0.42 * Wd), (P.Y - cy) / (0.36 * Hd)) * (1.0 + V.angular_noise(rng, th, harmonics=(2, 3, 4, 6), amp=0.14))
    q = q + 0.06 * V.noise1(rng, P.X.shape, 1.5 * P.ss)
    P.lay.over(mixc(mixc(W_SHILV, DAN, 0.45), PAPER, 0.05), 0.30 * smoothstep(1.0, 0.6, q) * (0.85 + 0.15 * V.noise1(rng, P.X.shape, 4.0 * P.ss)))
    P.lay.over(mixc(SHILV, ZHONG, 0.4), 0.10 * smoothstep(0.75, 0.2, q))
    # 地衣：灰绿的小圆斑，深一圈的边、里面淡，边上碎点
    for _ in range(n_lichen):
        a0 = rng.uniform(0, 2 * math.pi)
        lx, ly = cx + 0.24 * Wd * math.cos(a0), cy + 0.2 * Hd * math.sin(a0)
        r = rng.uniform(1.8, 2.8)
        tt = np.linspace(0, 2 * math.pi, 40, endpoint=False)
        rr = 1.0 + V.angular_noise(rng, tt, harmonics=(3, 5, 7), amp=0.12)
        ring = np.stack([lx + r * rr * np.cos(tt), ly + r * QQ_FLAT * rr * np.sin(tt)], -1)
        d, t = P.sdf(ring)
        P.fill(d, mixc(mixc(W_SHILV, QING, 0.6), PAPER, 0.2), 0.45, pool=0.8, pool_rgb=mixc(SHILV, ZHONG, 0.6), pool_w=0.4)
        for _ in range(int(rng.integers(4, 7))):
            a = rng.uniform(0, 2 * math.pi)
            P.dot(lx + r * 1.25 * math.cos(a), ly + r * QQ_FLAT * 1.25 * math.sin(a), rng.uniform(0.22, 0.38), mixc(SHILV, ZHONG, 0.55), 0.7)
    # 苔点：几簇，每簇先点一两个大的“横点”，周围小点错落，簇外零星几粒
    centers = []
    tries = 0
    while len(centers) < n_clumps and tries < 400:
        tries += 1
        px, py = cx + rng.uniform(-0.33, 0.33) * Wd, cy + rng.uniform(-0.24, 0.24) * Hd
        if all(math.hypot(px - a, (py - b) / QQ_FLAT) > 8.0 for a, b in centers):
            centers.append((px, py))
    inks = (JIAO, NONG, mixc(NONG, SHILV, 0.3), mixc(SHILV, JIAO, 0.5))
    for ci, (px, py) in enumerate(centers):
        # 一簇按“品”字错落：点与点之间留出空，不粘成一团
        placed: list[tuple[float, float, float]] = []
        k = int(rng.integers(7, 12))
        for j in range(120):
            if len(placed) >= k:
                break
            big = len(placed) < 3
            size = (rng.uniform(0.95, 1.25) if big else rng.uniform(0.4, 0.75))
            rad = rng.uniform(0.0, 2.0) if big else rng.uniform(1.8, 5.0)
            a = rng.uniform(0, 2 * math.pi)
            dx, dy = px + rad * math.cos(a), py + rad * QQ_FLAT * math.sin(a)
            rx, ry = size * rng.uniform(1.25, 1.6), size * rng.uniform(0.55, 0.7)
            dx = float(np.clip(dx, rx + 2.0, Wd - rx - 2.0))
            dy = float(np.clip(dy, ry + 2.0, Hd - ry - 2.0))
            if any(math.hypot(dx - qx, (dy - qy) / 0.8) < 0.8 * (rx + qr) for qx, qy, qr in placed):
                continue
            placed.append((dx, dy, rx))
            c = inks[0 if big else int(rng.choice(len(inks), p=(0.4, 0.3, 0.15, 0.15)))]
            # 横点：左头略重、右尾略收（侧锋一点）
            P.dot(dx, dy, rx, c, rng.uniform(0.85, 0.97), ry=ry)
            P.dot(dx - 0.35 * rx, dy - 0.1 * ry, 0.6 * rx, c, 0.9, ry=ry * 1.15)
    for _ in range(int(rng.integers(5, 9))):
        a = rng.uniform(0, 2 * math.pi)
        rr_ = rng.uniform(0.6, 1.0)
        P.dot(cx + 0.4 * Wd * rr_ * math.cos(a), cy + 0.34 * Hd * rr_ * math.sin(a), rng.uniform(0.3, 0.55), NONG, 0.85)
    return P.image()


def make_qq_wash(seed: int, Wd: int, Hd: int, lobes, base_alpha: float, *, tilt=(0.0, 0.0)) -> Image.Image:
    """兑了花青、石绿的淡墨晕：大片、很淡、边全是湿接湿的柔边（不像 wash_* 那样积出硬边）。
    里面一块浓一块淡，有几处水渍的回流（一圈略深的淡痕），花青沉在纸纹里的细颗粒。"""
    ss = 1
    rng = np.random.default_rng(seed)
    X, Y = V.grid1(Hd, Wd, ss)
    sh = X.shape
    nx, ny = (X - Wd / 2) / (Wd / 2), (Y - Hd / 2) / (Hd / 2)
    wx = nx + 0.10 * V.noise1(rng, sh, 40) + 0.05 * V.noise1(rng, sh, 14) + 0.02 * V.noise1(rng, sh, 5)
    wy = ny + 0.10 * V.noise1(rng, sh, 40) + 0.05 * V.noise1(rng, sh, 14) + 0.02 * V.noise1(rng, sh, 5)
    F = np.zeros(sh)
    for cx, cy, rx, ry, wt in lobes:
        F += wt * np.exp(-(((wx - cx) / rx) ** 2 + ((wy - cy) / ry) ** 2))
    F += 0.06 * V.noise1(rng, sh, 10) + 0.03 * V.noise1(rng, sh, 3) + 0.012 * V.noise1(rng, sh, 1.2)
    # 柔边：湿接湿，过渡带宽窄沿边变化（几像素到十几像素），但看得出一块墨的边界
    soft = 0.03 + 0.10 * smoothstep(-1.0, 1.0, V.noise1(rng, sh, 22))
    body = smoothstep(0.5 - soft, 0.5 + soft, F)
    inner = base_alpha * (1.0 + 0.3 * (tilt[0] * nx + tilt[1] * ny))
    inner = inner * (0.75 + 0.25 * smoothstep(-1.5, 1.5, V.noise1(rng, sh, 18)) + 0.06 * V.noise1(rng, sh, 5))
    inner += 0.05 * smoothstep(0.75, 1.05, F + 0.1 * V.noise1(rng, sh, 8))  # 墨聚处再深一层
    # 边上略积一点颜料（柔边处几乎没有，窄边处才看得出）
    inner += 0.035 * np.exp(-np.maximum(F - 0.5, 0) / 0.05) * (F > 0.5) * smoothstep(0.08, 0.04, soft)
    # 回流：另一个场的等值线，一道略深的淡痕，只在里面
    G = V.noise1(rng, sh, 12) + 0.4 * V.noise1(rng, sh, 3.5)
    tide = 0.025 * np.exp(-(((G - 0.8) / 0.08) ** 2)) * (G < 0.85) * smoothstep(0.55, 0.85, F)
    # 颗粒：花青颜料沉在纸纹里（很轻）
    gran = 1.0 + 0.06 * V.noise1(rng, sh, 0.7) * smoothstep(0.5, 0.9, F)
    a = (body * inner + tide * body) * gran
    a *= smoothstep(1.0, 0.88, np.maximum(np.abs(nx), np.abs(ny)))
    a = np.clip(a, 0, 0.3)
    a[0, :] = a[-1, :] = a[:, 0] = a[:, -1] = 0
    # 颜色：浓处偏花青、淡处偏石绿的淡墨（青）
    k = smoothstep(-1.2, 1.2, V.noise1(rng, sh, 30) + 2.0 * (F - 0.7))
    rgb = mixc(mixc(DAN, SHILV, 0.5), mixc(ZHONG, HUAQING, 0.55), k)
    return V.to_rgba8(rgb, a)


QQ_WASHES = [
    # (种子, 宽, 高, 叶瓣 [(cx, cy, rx, ry, 权重)], 内部浓度, 关键字参数)
    (5701, 320, 200, [(-0.32, 0.06, 0.46, 0.46, 1.0), (0.30, -0.08, 0.44, 0.42, 0.9), (0.02, 0.32, 0.40, 0.26, 0.55)], 0.19, {"tilt": (-0.4, 0.2)}),
    (5702, 288, 192, [(-0.20, -0.10, 0.36, 0.50, 1.0), (0.32, 0.18, 0.34, 0.36, 0.85), (0.58, -0.30, 0.16, 0.18, 0.7), (-0.55, 0.30, 0.18, 0.20, 0.6)], 0.185, {"tilt": (0.3, -0.3)}),
]


def fox_print(GX, GY, x, y, heading, k):
    """一只狐狸脚印的覆盖度（地面坐标）：四个趾垫（中间两个靠前）、一个人字形的掌垫、中趾前两点爪痕。
    狐狸的脚印紧凑，趾垫和掌垫之间留出一个“X”形的空。"""
    ca, sa = math.cos(heading), math.sin(heading)
    u = ((GX - x) * ca + (GY - y) * sa) / k
    v = (-(GX - x) * sa + (GY - y) * ca) / k

    def blob(u0, v0, ru, rv, rot=0.0):
        cr, sr = math.cos(rot), math.sin(rot)
        du, dv = u - u0, v - v0
        return np.hypot((du * cr + dv * sr) / ru, (-du * sr + dv * cr) / rv)

    aa = 0.08
    m = np.zeros_like(u)
    for (u0, v0, ru, rv, rot) in ((1.35, 0.52, 0.72, 0.48, 0.15), (1.35, -0.52, 0.72, 0.48, -0.15),
                                  (0.25, 1.32, 0.62, 0.46, 0.5), (0.25, -1.32, 0.62, 0.46, -0.5)):
        m = np.maximum(m, smoothstep(1.0 + aa, 1.0 - aa, blob(u0, v0, ru, rv, rot)))
    heel = smoothstep(1.0 + aa, 1.0 - aa, blob(-1.15, 0.0, 0.95, 1.18))
    notch = smoothstep(1.0 + aa, 1.0 - aa, blob(-1.85, 0.0, 0.55, 0.5))  # 掌垫后沿一个缺口，成人字形
    m = np.maximum(m, heel * (1.0 - notch))
    claws = np.maximum(smoothstep(1.0 + aa, 1.0 - aa, blob(2.35, 0.5, 0.26, 0.2)), smoothstep(1.0 + aa, 1.0 - aa, blob(2.35, -0.5, 0.26, 0.2)))
    halo = np.exp(-(blob(0.0, 0.0, 2.6, 2.1) ** 2))  # 踩实的地，周围一圈淡墨
    return m, claws, halo


def make_qq_fox_tracks() -> Image.Image:
    """一行狐狸脚印：狐狸走路后脚踩进前脚的印里，所以几乎走成一条线，左右只差一点；从左下往右上走，
    最早的几步淡（地干了），越往前越清楚。浓墨点出趾垫和掌垫，墨边略洇，周围一圈踩实的淡墨。按地面透视压扁。"""
    Wd, Hd = 128, 40
    P = W.Painter(Wd, Hd, 5800, ss=6)
    rng = P.rng
    cy = Hd / 2
    GX, GY = P.X, cy + (P.Y - cy) / QQ_FLAT  # 屏幕 → 地面坐标
    path = V.bezier([(10.0, cy + 17.0), (42.0, cy + 9.0), (78.0, cy - 2.0), (118.0, cy - 15.0)], 200)
    tan = np.gradient(path, axis=0)
    tan /= np.linalg.norm(tan, axis=1, keepdims=True)
    n_steps = 7
    idx = np.linspace(8, len(path) - 9, n_steps).astype(int)
    for j, i in enumerate(idx):
        side = 1.0 if j % 2 == 0 else -1.0
        nrm = np.array([-tan[i, 1], tan[i, 0]])
        x, y = path[i] + nrm * side * 1.3 + rng.normal(0, 0.25, 2)
        heading = math.atan2(tan[i, 1], tan[i, 0]) + side * 0.12 + rng.normal(0, 0.06)
        k = rng.uniform(1.45, 1.6)
        fresh = 0.45 + 0.55 * j / (n_steps - 1)  # 越往后（越新）越清楚
        m, claws, halo = fox_print(GX, GY, x, y, heading, k)
        m = np.clip(m + 0.12 * V.noise1(rng, P.X.shape, 0.5 * P.ss) * (m > 0.05) * (m < 0.95), 0, 1)
        P.lay.over(mixc(DAN, ZHONG, 0.3), 0.16 * fresh * halo)
        P.lay.over(mixc(ZHONG, JIAO, 0.3 + 0.5 * fresh), 0.92 * fresh * m)
        P.lay.over(mixc(NONG, JIAO, 0.5), 0.8 * fresh * claws)
        # 洇边：墨在湿地上往外渗一点
        P.lay.over(mixc(ZHONG, DAN, 0.4), 0.25 * fresh * np.clip(V.fft_blur(m, V.sig(0.5 * P.ss)) - m, 0, 1) * 2.0)
    return P.image()


# ============================================================== 汇总


LEAVES_SEEDS = (4400, 4401)
PEBBLES_SEEDS = (4600, 4601)


def build() -> dict[str, tuple[Image.Image, tuple[float, float], dict]]:
    """{名字: (图, 锚点, meta 附加字段)}。不写盘。"""
    normal = {"color": "full", "blend": "normal", "tint": False}
    out: dict[str, tuple[Image.Image, tuple[float, float], dict]] = {}
    out["spring"] = (make_spring(), (0.5, 0.5), {**normal, "kind": "zone", "note": "灵泉：站进去回血；池面中心即锚点，池面半径约 60×31 像素（1 倍）"})
    rift, glow = make_rift()
    out["rift"] = (rift, (0.5, 0.5), {**normal, "kind": "zone", "note": "妖潮裂隙：地上的口子，上面叠 rift_glow"})
    out["rift_glow"] = (glow, (0.5, 0.5), {"color": "white", "blend": "add", "tint": True, "kind": "zone",
                                           "note": f"裂隙里的光：与 rift 同尺寸同锚点叠加，游戏里染色（建议 {RIFT_TINT}）并做呼吸闪烁"})
    for i, (seed, n, plumes) in enumerate(((4300, 4, (1,)), (4301, 3, (0, 2)), (4302, 5, (2, 3)))):
        out[f"reed_{i}"] = (make_reed(seed, n, plumes), (0.5, 1.0), {**normal, "kind": "decor", "note": "芦苇，锚点在根部（底边）"})
    # 落叶、卵石在 2 倍（桌面版）按月夜调浓（V.moon_boost；1 倍原样）
    for i, seed in enumerate(LEAVES_SEEDS):
        out[f"leaves_{i}"] = (V.moon_boost(make_leaves(seed)), (0.5, 0.5), {**normal, "kind": "decor", "note": "散落的叶子，可随机旋转"})
    for i, seed in enumerate(PEBBLES_SEEDS):
        out[f"pebbles_{i}"] = (V.moon_boost(make_pebbles(seed)), (0.5, 0.5), {**normal, "kind": "decor", "note": "一撮卵石"})
    out["puddle_0"] = (make_puddle(), (0.5, 0.5), {**normal, "kind": "decor", "note": "小水洼"})
    out["bamboo_0"] = (make_bamboo(4700, 2, True), (0.5, 1.0), {**normal, "kind": "decor", "note": "两竿短竹 + 竹笋，锚点在根部（底边）"})
    out["bamboo_1"] = (make_bamboo(4701, 3, False), (0.5, 1.0), {**normal, "kind": "decor", "note": "三竿短竹，锚点在根部（底边）"})
    # ---- M2.5：五行反应留下的区域（只往后追加）
    white_add = {"color": "white", "blend": "add", "tint": True}
    lava, lava_glow = make_zone_lava()
    out["zone_lava"] = (lava, (0.5, 0.5), {**normal, "kind": "zone", "radius_px": V.dpx(86), "flat": ZONE_FLAT,
                                           "note": "熔岩（熔岩反应）：已按俯角压扁，等比缩放到区域半径（radius_px 是横向半径）；上面叠 zone_lava_glow"})
    out["zone_lava_glow"] = (lava_glow, (0.5, 0.5), {**white_add, "kind": "zone", "radius_px": V.dpx(86),
                                                      "note": "熔岩裂缝与熔池的光：与 zone_lava 同尺寸同锚点叠加，建议染 #FF7A2A，可慢慢明暗起伏"})
    out["zone_mud"] = (make_zone_mud(), (0.5, 0.5), {**normal, "kind": "zone", "radius_px": V.dpx(91), "flat": ZONE_FLAT,
                                                      "note": "淤泥（淤泥反应）：已按俯角压扁，等比缩放到区域半径（radius_px 是横向半径）"})
    herb, herb_glow = make_zone_herb()
    out["zone_herb"] = (herb, (0.5, 0.5), {**normal, "kind": "zone", "radius_px": V.dpx(79), "flat": ZONE_FLAT,
                                           "note": "灵草（滋生反应）：已按俯角压扁，等比缩放到区域半径（radius_px 是横向半径）；上面叠 zone_herb_glow"})
    out["zone_herb_glow"] = (herb_glow, (0.5, 0.5), {**white_add, "kind": "zone", "radius_px": V.dpx(79),
                                                      "note": "灵草草尖的光：与 zone_herb 同尺寸同锚点叠加，建议染 #9CF0B8"})
    out.update(build_qq())
    return out


def build_qq(boost: bool | None = None) -> dict[str, tuple[Image.Image, tuple[float, float], dict]]:
    """青丘的地面装饰（帧名前缀 qq_），追加在 build() 的最后。落竹叶、苔点、狐爪印在 2 倍按月夜调浓
    （V.moon_boost）；boost=False 时给原图（moon_textures 审图用），None 时看密度。"""
    normal = {"color": "full", "blend": "normal", "tint": False, "region": "qingqiu"}
    out: dict[str, tuple[Image.Image, tuple[float, float], dict]] = {}
    specs = ((5401, 72, 44, 12, -0.25, 0.45, 1.0), (5402, 56, 36, 7, 0.4, 0.9, 0.8), (5403, 96, 40, 14, -0.12, 0.3, 1.5))
    for i, (seed, w, h, n, axis, spread, elong) in enumerate(specs):
        out[f"qq_bamboo_leaves_{i}"] = (V.moon_boost(make_qq_bamboo_leaves(seed, w, h, n, axis=axis, spread=spread, elong=elong), boost), (0.5, 0.5),
                                        {**normal, "kind": "decor", "note": "青丘：被风扫成一堆的落竹叶（枯黄、赭、灰，少数灰绿），可随机旋转、镜像"})
    shoots = (
        (5501, 44, 44, ((-8.0, 30.0, 6.2, 1.6, 0.2), (7.5, 19.0, 4.6, -1.4, 0.5), (16.5, 9.0, 3.0, 0.6, 0.0))),
        (5502, 32, 40, ((-2.0, 33.0, 6.6, 2.4, 0.35), (10.0, 7.5, 3.0, -0.6, 0.0))),
    )
    for i, (seed, w, h, sp) in enumerate(shoots):
        out[f"qq_shoots_{i}"] = (make_qq_shoots(seed, w, h, sp), (0.5, 1.0), {**normal, "kind": "decor", "note": "青丘：刚冒头的竹笋，锚点在根部（底边），可水平镜像"})
    for i, (seed, w, h, nc, nl) in enumerate(((5601, 56, 36, 6, 2), (5602, 44, 30, 4, 1))):
        out[f"qq_moss_{i}"] = (V.moon_boost(make_qq_moss(seed, w, h, nc, nl), boost), (0.5, 0.5), {**normal, "kind": "decor", "note": "青丘：苔点与地衣，可随机旋转（小角度）、镜像"})
    for i, (seed, w, h, lobes, ba, kw) in enumerate(QQ_WASHES):
        out[f"qq_wash_{i}"] = (make_qq_wash(seed, w, h, lobes, ba, **kw), (0.5, 0.5),
                               {**normal, "kind": "decor", "max_alpha": 0.3, "note": "青丘：兑花青、石绿的淡墨晕，大片柔边，铺在宣纸上最底层；可随机旋转、镜像"})
    out["qq_fox_tracks"] = (V.moon_boost(make_qq_fox_tracks(), boost), (0.5, 0.5), {**normal, "kind": "decor", "flat": QQ_FLAT,
                                                               "note": "青丘：一行狐狸脚印（从左下往右上走，越往右越新），已按地面透视压扁；可水平镜像、小角度旋转"})
    return out


# ============================================================== 青丘审图（读盘，不重新生成）


def qq_sample(path: Path) -> None:
    """青丘新素材的游戏比例审图（1 贴图像素 = 1 画面像素）：
    上排：左白天（宣纸、不打光）、右夜里（世界 × 光照图，竹刺尾光叠加，迷雾两层画在暗层之上、染月白、alpha 0.3 / 0.2）；
    中排：mist_0、mist_1 各平铺 2×2（夜色底，满不透明度，看接缝和重复）；
    下排：新素材放大 2 倍（最近邻），纸色底。
    先跑 vfx_textures.py 和 weapon_textures.py（同一密度）。"""
    import weapon_textures as WT  # noqa: PLC0415  只读它的产物与 place()

    def load(folder, name):
        return Image.open(V.ASSETS / folder / f"{name}.png").convert("RGBA")

    gmeta = json.loads((V.GROUND_DIR / "meta.json").read_text(encoding="utf-8"))["files"]
    wmeta = json.loads((WT.WEAPON_DIR / "meta.json").read_text(encoding="utf-8"))["files"]
    Wm, Hm = V.dpx(1000), V.dpx(640)
    pt = np.asarray(Image.open(V.GROUND_DIR / "paper.png").convert("RGB"), np.float64) / 255.0
    base = np.tile(pt, (Hm // pt.shape[0] + 1, Wm // pt.shape[1] + 1, 1))[:Hm, :Wm].copy()
    G = {n[:-4]: load("ground", n[:-4]) for n in gmeta if n.startswith(("qq_", "bamboo_", "grass_"))}
    spike, trail = load("weapons", "bamboo_spike"), load("weapons", "bamboo_spike_trail")
    mists = [load("vfx", f"mist_{i}") for i in range(2)]
    shadow, light = load("vfx", "shadow"), load("vfx", "light")
    hero, hero_k = None, 1.0
    for b, k in ((V.ASSETS, 1.0), (V.OUT / "assets", D)):
        if (b / "hero" / "idle_SE_00.png").exists():
            hero, hero_k = Image.open(b / "hero" / "idle_SE_00.png").convert("RGBA"), k
            break

    def put(canvas, img, x, y, **kw):
        WT.place(canvas, img, x * D, y * D, **kw)

    def A(n):
        return tuple(gmeta[f"{n}.png"]["anchor"])

    flat = [("qq_wash_0", 250, 430, 1.0), ("qq_wash_1", 770, 170, 1.0), ("qq_bamboo_leaves_0", 390, 320, 1.0),
            ("qq_bamboo_leaves_1", 690, 470, 1.0), ("qq_bamboo_leaves_2", 560, 590, 1.0), ("qq_moss_0", 150, 200, 1.0),
            ("qq_moss_1", 880, 430, 1.0), ("qq_fox_tracks", 640, 300, 1.0), ("qq_fox_tracks", 250, 560, -1.0)]
    upright = [("bamboo_0", 720, 250), ("bamboo_1", 765, 238), ("qq_shoots_0", 180, 300), ("qq_shoots_1", 830, 330),
               ("qq_shoots_0", 95, 600), ("grass_0", 430, 520), ("grass_2", 950, 600), ("qq_shoots_1", 520, 160)]
    hx, hy = 470.0, 400.0
    spikes = [(610, 140, -0.3), (300, 110, 0.25), (880, 560, math.pi + 0.4), (360, 250, 0.05)]

    def draw_world(world):
        for n, x, y, sx in flat:
            put(world, G[n], x, y, anchor=A(n), scale=(sx, 1.0))
        items = [(y, n, x) for n, x, y in upright]
        if hero is not None:
            items.append((hy, "hero", hx))
        for y, n, x in sorted(items):
            if n == "hero":
                put(world, shadow, x, y, scale=1.0)
                put(world, hero, x, y, anchor=(0.5, 0.875), scale=hero_k)
            else:
                put(world, G[n], x, y, anchor=A(n))

    def draw_spikes(canvas, mode, lm=None):
        for x, y, ang in spikes:
            put(canvas, trail, x, y, angle=ang, anchor=tuple(wmeta["bamboo_spike_trail.png"]["anchor"]), mode=mode,
                tint=col(WT.SPIKE_TRAIL_TINT), alpha=0.85 if mode == "add" else 0.5)
            tint = None if lm is None else lm[int(y * D), int(x * D)]
            put(canvas, spike, x, y, angle=ang, anchor=tuple(wmeta["bamboo_spike.png"]["anchor"]), tint=tint)

    def mist_layer(canvas, img, alpha, off):
        a = np.asarray(img, np.float64)[..., 3] / 255.0
        a = np.roll(np.roll(a, off[1], 0), off[0], 1)
        t = np.tile(a, (canvas.shape[0] // a.shape[0] + 1, canvas.shape[1] // a.shape[1] + 1))[: canvas.shape[0], : canvas.shape[1]]
        k = (alpha * t)[..., None]
        canvas[:] = canvas * (1 - k) + col(V.MIST_TINT) * k

    day = base.copy()
    draw_world(day)
    draw_spikes(day, "over")
    world = base.copy()
    draw_world(world)
    lm = np.broadcast_to(col(S.NIGHT_AMBIENT), world.shape).copy()
    put(lm, light, hx, hy - 50, scale=760 * D / light.width, mode="add", tint=col(S.LANTERN_LIGHT))
    lm = np.clip(lm, 0, 1)
    night = world * lm
    draw_spikes(night, "add", lm)
    mist_layer(night, mists[0], V.MIST_ALPHAS[0], (V.dpx(37), V.dpx(11)))
    mist_layer(night, mists[1], V.MIST_ALPHAS[1], (V.dpx(-90), V.dpx(60)))
    gap, top = 12, V.dpx(30)
    tiles = []
    for m in mists:
        a = np.asarray(m, np.float64)[..., 3:4] / 255.0
        t = np.tile(a, (2, 2, 1))
        tiles.append(col(S.NIGHT_AMBIENT) * (1 - t) + col(V.MIST_TINT) * t)
    # 放大 2 倍的新素材
    zoom_names = [n for n in G if n.startswith("qq_") and not n.startswith("qq_wash")]
    zimgs = [G[n] for n in zoom_names] + [spike]
    zw = sum(im.width * 2 + 16 for im in zimgs) + 16
    zh = max(im.height * 2 for im in zimgs) + 32
    zoom = np.broadcast_to(PAPER, (zh, max(zw, Wm * 2 + gap), 3)).copy()
    x = 16
    for im in zimgs:
        V.composite(zoom, im, x, 16, "over", scale=2)
        x += im.width * 2 + 16
    th = tiles[0].shape[0]
    Wt = max(Wm * 2 + gap, tiles[0].shape[1] * 2 + gap, zoom.shape[1])
    out = np.ones((top + Hm + top + th + top + zh, Wt, 3)) * 0.1
    out[top : top + Hm, :Wm] = np.clip(day, 0, 1)
    out[top : top + Hm, Wm + gap : Wm * 2 + gap] = np.clip(night, 0, 1)
    y2 = top + Hm + top
    out[y2 : y2 + th, : tiles[0].shape[1]] = tiles[0]
    out[y2 : y2 + th, tiles[0].shape[1] + gap : tiles[0].shape[1] * 2 + gap] = tiles[1]
    y3 = y2 + th + top
    out[y3 : y3 + zh, : zoom.shape[1]] = zoom
    im = Image.fromarray(np.round(out * 255).astype(np.uint8), "RGB")
    dr = ImageDraw.Draw(im)
    f = V.font(V.dpx(14))
    dr.text((8, 7), f"day: paper, normal over (density {D:g}x, 1 texel = {1 / S.PX_PER_UNIT:g} world unit); bamboo_spike + trail (tinted {WT.SPIKE_TRAIL_TINT})", fill="#DDDDDD", font=f)
    dr.text((Wm + gap + 8, 7), f"night: world x lightmap, trail additive, mist_0 @ {V.MIST_ALPHAS[0]} + mist_1 @ {V.MIST_ALPHAS[1]} over the dark layer (tint {V.MIST_TINT})", fill="#DDDDDD", font=f)
    dr.text((8, y2 - top + 7), "mist_0 / mist_1 tiled 2x2, full alpha on NIGHT_AMBIENT (tile edges meet at the centre lines)", fill="#DDDDDD", font=f)
    dr.text((8, y3 - top + 7), "new decor + bamboo_spike at 2x nearest, on PAPER", fill="#DDDDDD", font=f)
    V.save_png(im, path)


if __name__ == "__main__":
    if "--sample" in sys.argv:
        V.REVIEW_DIR.mkdir(parents=True, exist_ok=True)
        qq_sample(V.REVIEW_DIR / "qq_2d_sample.png")
        print("写出", V.REVIEW_DIR / "qq_2d_sample.png")
        sys.exit(0)
    items = build()
    entries = [(k, img, "add" if e.get("blend") == "add" else "over", col(RIFT_TINT) if k == "rift_glow" else None) for k, (img, _, e) in items.items()]
    V.REVIEW_DIR.mkdir(parents=True, exist_ok=True)
    V.review_sheet(entries, V.REVIEW_DIR / "ground_decor_preview.png")
    print("写出", V.REVIEW_DIR / "ground_decor_preview.png")
