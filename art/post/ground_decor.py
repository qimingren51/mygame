#!/usr/bin/env python3
"""提灯夜行 · 第二批地面贴图：灵泉、妖潮裂隙（含叠加用的光）、芦苇、落叶、卵石、水洼、竹子；
M2.5 追加五行反应留下的区域：zone_lava（+ zone_lava_glow）熔岩、zone_mud 淤泥、zone_herb（+ zone_herb_glow）灵草。

不单独写盘：vfx_textures.py 的 main() 调用这里的 build()，和宣纸、晕染、草一起写进
art/out/<ASSETS_DIR_NAME>/ground/ 与同一份 meta.json（一个文件夹只有一个写 meta 的脚本）。
画法复用 weapon_textures.Painter（淡彩填色、手抖轮廓、干笔）与 vfx_textures 的笔触；
坐标都按 1 倍像素写，密度由 style.DENSITY 决定（见 vfx_textures.grid1 / noise1）。

单独预览（不写 assets，只出一张拼图到 art/out/review[@2x]/ground_decor_preview.png）：
  art/.venv/bin/python art/post/ground_decor.py
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
from PIL import Image

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


# ============================================================== 汇总


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
    for i, seed in enumerate((4400, 4401)):
        out[f"leaves_{i}"] = (make_leaves(seed), (0.5, 0.5), {**normal, "kind": "decor", "note": "散落的叶子，可随机旋转"})
    for i, seed in enumerate((4600, 4601)):
        out[f"pebbles_{i}"] = (make_pebbles(seed), (0.5, 0.5), {**normal, "kind": "decor", "note": "一撮卵石"})
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
    return out


if __name__ == "__main__":
    items = build()
    entries = [(k, img, "add" if e.get("blend") == "add" else "over", col(RIFT_TINT) if k == "rift_glow" else None) for k, (img, _, e) in items.items()]
    V.REVIEW_DIR.mkdir(parents=True, exist_ok=True)
    V.review_sheet(entries, V.REVIEW_DIR / "ground_decor_preview.png")
    print("写出", V.REVIEW_DIR / "ground_decor_preview.png")
