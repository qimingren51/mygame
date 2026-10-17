#!/usr/bin/env python3
"""提灯夜行 · 黑漆描金界面件：升级卡框、卡片焦点、状态栏（头像章、燃灯刻度、等级印、血条 / 经验条、法器 / 心法格、小签），
以及数值小图标（只用 Pillow + numpy）。

试玩第 1 轮第 3、5 项：用户选定“黑漆描金”（样张见 art/out/review@2x/card_sample_lacquer.png、hud_sample_lacquer.png）。
  漆：近黑带一点暖的推光漆，大块浓淡、很淡的细断纹、一道斜着的柔光；
  金：金箔描边，按浮雕打光（迎光亮、背光暗），磨旧的金露出底漆；
  稀有度靠内缘的光和金饰的繁简：凡 铁灰、单线；灵 青蓝；玄 紫（多一圈金点）；天 金（双线、连珠、如意结、洒金）；
  异 朱红（两线之间一道朱漆）；合 玉青（双线、连珠、如意结、洒金）。

件的名字、切片、平铺 / 拉伸方式由 ui_skin.specs() 登记（和原来的皮肤同名，代码不用改），这里只负责画：
  - 卡框 600×920（卡片节点 300×460，1280×720 设计画布），切片 64，中间与四边平铺：漆面、内缘光、连珠、洒金都按
    平铺区的周期画（四边一个周期、中间一个周期），角上的结都在切片以内；花边主线在节点内 8 像素（贴图 16）；
  - 卡片焦点 624×944（节点比卡片每边大 6），拉伸：卡边一道泥金亮线、往外一圈暖光；
  - 横条（底槽、填充、小签）中段沿 x 完全一致（finish(band_x=…)），两头的饰件都在切片以内。
数值小图标（ui/stat_*、ui/stat_group_*）：64² 黑漆小圆章 + 金线刻的符号，界面显示 32（卡片）和 20（属性格）。
出到 art/out/assets@2x/ui_stats/（meta.json 的 name 是 ui，帧名 ui/stat_<key>），和卡面插画一起打进图集页 cards。

用法（仓库根目录）：
  art/.venv/bin/python art/post/ui_skin.py          # 整套皮肤（漆件由本文件画）
  art/.venv/bin/python art/post/ui_lacquer.py       # 数值小图标 + 审图 review@2x/lacquer_ui_review.png（1080p，按 1:1 逻辑像素）
"""

from __future__ import annotations

import json
import math
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import vfx_textures as V  # noqa: E402
import weapon_textures as W  # noqa: E402

S = V.S
smoothstep, fft_blur, noise, rank01 = V.smoothstep, V.fft_blur, V.noise, V.rank01
REPO = HERE.parents[1]
OUT = HERE.parent / "out"
STATS_DIR = OUT / "assets@2x" / "ui_stats"
FONT_SERIF = REPO / "assets" / "fonts" / "NotoSerifSC-subset.ttf"
FONT_BRUSH = REPO / "assets" / "fonts" / "MaShanZheng-subset.ttf"

CARD_W, CARD_H, CARD_SL = 600, 920, 64
FOCUS_PAD = 12  # 焦点框比卡片每边大逻辑 6（贴图 12）


def hexc(h: str) -> np.ndarray:
    h = h.lstrip("#")
    return np.array([int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4)])


def mixc(a, b, t):
    t = np.asarray(t, dtype=np.float64)
    if t.ndim:
        t = t[..., None]
    return np.asarray(a) * (1 - t) + np.asarray(b) * t


# 金色带：受光 0 → 1（emboss 的输出）查色
GOLD = [(0.0, "#2E1C06"), (0.30, "#6E4A14"), (0.52, "#B5852E"), (0.68, "#D9AE52"), (0.84, "#F2D58C"), (0.95, "#FFF3CE"),
        (1.0, "#FFFFFF")]
GOLD_OLD = [(0.0, "#1E140A"), (0.30, "#4A3618"), (0.55, "#7E6234"), (0.75, "#A88A52"), (0.92, "#CDB27C"), (1.0, "#E8D6A8")]
LACQUER = hexc("#0D0A09")
LACQUER_WARM = hexc("#24120E")
SHEEN = hexc("#93A0B4")

RARITY = {
    # glow 内缘光色、ga 强度、gw 宽度；gold 金色带；knot 角上的结；beads 连珠；flecks 洒金片数；band 两线之间的漆色
    "fan": dict(glow="#8A929C", ga=0.10, gw=10.0, gold=GOLD_OLD, lines=1, knot=None, beads=False, flecks=0, band=None),
    "ling": dict(glow="#41B6E6", ga=0.58, gw=12.0, gold=GOLD, lines=2, knot="fangsheng", beads=False, flecks=0, band=None),
    "xuan": dict(glow="#A274E8", ga=0.58, gw=12.0, gold=GOLD, lines=2, knot="fangsheng", beads=False, flecks=0, band=None,
                 dots=True),
    "tian": dict(glow="#F2A443", ga=0.52, gw=16.0, gold=GOLD, lines=2, knot="ruyi", beads=True, flecks=150, band=None),
    "yi": dict(glow="#E0566A", ga=0.55, gw=14.0, gold=GOLD, lines=2, knot="fangsheng", beads=False, flecks=0, band="#6E1410"),
    "he": dict(glow="#5ED0B0", ga=0.52, gw=16.0, gold=GOLD, lines=2, knot="ruyi", beads=True, flecks=110, band=None),
}


# ============================================================== 画布小工具


class Canvas:
    """超采样画布（坐标以最终像素计，像素中心在 .5）：预乘 alpha 叠加。和 ui_skin.Canvas 同，另带周期铺放。"""

    def __init__(self, w: int, h: int, seed: int, ss: int = 2):
        self.w, self.h, self.ss = w, h, ss
        self.X, self.Y = V.grid(h, w, ss)
        self.lay = V.Layer(h * ss, w * ss)
        self.rng = np.random.default_rng(seed)
        self.aa = 0.7 / ss

    def over(self, rgb, a):
        self.lay.over(rgb, np.clip(a, 0, 1))

    def periodic(self, field: np.ndarray, ox: float, oy: float) -> np.ndarray:
        """把一张周期场（超采样分辨率）铺满画布，field[0, 0] 对齐到最终像素 (ox, oy)。"""
        H, Wd = self.lay.a.shape
        iy = (np.arange(H) - int(round(oy * self.ss))) % field.shape[0]
        ix = (np.arange(Wd) - int(round(ox * self.ss))) % field.shape[1]
        return field[np.ix_(iy, ix)]

    def pnoise(self, per, origin, sigma, seed):
        """周期噪声（标准差 1），一个周期 = per（最终像素），对齐 origin。"""
        rng = np.random.default_rng(seed)
        f = noise(rng, (int(per[1] * self.ss), int(per[0] * self.ss)), sigma * self.ss)
        return self.periodic(f, *origin)


def rrect_sd(X, Y, x0, y0, x1, y1, r):
    """圆角矩形的有向距离（内负外正）。"""
    qx = np.abs(X - 0.5 * (x0 + x1)) - (0.5 * (x1 - x0) - r)
    qy = np.abs(Y - 0.5 * (y0 + y1)) - (0.5 * (y1 - y0) - r)
    return np.hypot(np.maximum(qx, 0), np.maximum(qy, 0)) + np.minimum(np.maximum(qx, qy), 0) - r


def emboss(c: Canvas, height, *, light=(-0.55, -0.70, 0.45), depth=1.0, sigma=1.0):
    """高度场 → 受光 0..1（平面约 0.5，迎光的斜面亮、背光的暗）。"""
    hgt = fft_blur(height, sigma * c.ss)
    gy, gx = np.gradient(hgt)
    k = depth * c.ss * 1.8
    nx, ny = -gx * k, -gy * k
    L = np.array(light, np.float64)
    L = L / np.linalg.norm(L)
    dot = (nx * L[0] + ny * L[1] + L[2]) / np.sqrt(nx * nx + ny * ny + 1)
    return np.clip(0.5 + (dot - L[2]) * 0.9, 0, 1)


def ramp(t, stops):
    t = np.clip(t, 0, 1)
    xs = [p for p, _ in stops]
    cols = np.array([hexc(h) for _, h in stops])
    return np.stack([np.interp(t, xs, cols[:, k]) for k in range(3)], -1)


def metal(c: Canvas, mask, stops, *, sigma=0.8, depth=1.2, grain=None, base=0.0):
    """浮起的金：mask 是覆盖度，按 emboss 打光查色带；grain 是（周期）噪声场，给金箔一点斑驳。"""
    sh = emboss(c, mask, sigma=sigma, depth=depth)
    if grain is not None:
        sh = sh + 0.05 * grain
    return ramp(sh + base, stops)


def stroke_mask(c: Canvas, pts, hw):
    """一条折线笔画（等宽或逐点宽度，圆头）的覆盖度，只在包围盒里算。"""
    P = np.asarray(pts, np.float64)
    hwv = np.broadcast_to(np.asarray(hw, np.float64), (len(P),))
    pad = float(hwv.max()) + 2
    xs, ys = c.X[0], c.Y[:, 0]
    ix = np.nonzero((xs >= P[:, 0].min() - pad) & (xs <= P[:, 0].max() + pad))[0]
    iy = np.nonzero((ys >= P[:, 1].min() - pad) & (ys <= P[:, 1].max() + pad))[0]
    out = np.zeros(c.X.shape)
    if len(ix) == 0 or len(iy) == 0:
        return out
    sl = (slice(iy[0], iy[-1] + 1), slice(ix[0], ix[-1] + 1))
    X, Y = c.X[sl], c.Y[sl]
    d = np.full(X.shape, 1e9)
    hh = np.zeros(X.shape)
    if len(P) == 1:
        P = np.vstack([P, P + 1e-3])
        hwv = np.array([hwv[0], hwv[0]])
    for i in range(len(P) - 1):
        ax, ay = P[i]
        ex, ey = P[i + 1] - P[i]
        L2 = max(ex * ex + ey * ey, 1e-12)
        t = np.clip(((X - ax) * ex + (Y - ay) * ey) / L2, 0, 1)
        dd = np.hypot(X - ax - ex * t, Y - ay - ey * t)
        sel = dd < d
        d = np.where(sel, dd, d)
        hh = np.where(sel, hwv[i] * (1 - t) + hwv[i + 1] * t, hh)
    out[sl] = smoothstep(hh + c.aa, hh - c.aa, d)
    return out


def dot(c: Canvas, x, y, r):
    return stroke_mask(c, [(x, y)], r)


def spiral(cx, cy, r0, r1, a0, turns, n=60, sx=1.0):
    t = np.linspace(0, 1, n)
    a = a0 + sx * 2 * math.pi * turns * t
    r = r0 + (r1 - r0) * t
    return np.stack([cx + r * np.cos(a), cy + r * np.sin(a)], -1)


def finish(c: Canvas, *, clear=True, band_x=None, band_y=None) -> Image.Image:
    """直通 alpha 的 RGBA8（颜色扩进透明区）；band_x=(L, R) 时把横向拉伸带每列换成第 L 列。同 ui_skin.finish。"""
    import ui_skin as U  # noqa: PLC0415

    lay = c.lay.down(c.ss)
    rgb, a = lay.straight()
    if clear:
        a[0, :] = a[-1, :] = a[:, 0] = a[:, -1] = 0
    a8 = np.clip(np.round(a * 255.0), 0, 255).astype(np.uint8)
    rgb = U.bleed_rgb(rgb, a8)
    arr = np.dstack([np.clip(np.round(rgb * 255.0), 0, 255).astype(np.uint8), a8])
    if band_x is not None:
        L, R = band_x
        arr[:, L: c.w - R] = arr[:, L: L + 1]
    if band_y is not None:
        T, B = band_y
        arr[T: c.h - B, :] = arr[T: T + 1, :]
    return Image.fromarray(arr, "RGBA")


# ============================================================== 漆面

def lacquer_field(c: Canvas, per, origin, seed, *, sheen=0.038, warm=0.16):
    """周期漆面（per = 一个周期的最终像素宽高，对齐 origin）：近黑带暖、大块浓淡、细断纹、一道斜的柔光。返回 rgb。"""
    pw, ph = int(per[0]), int(per[1])
    ss = c.ss
    rng = np.random.default_rng(seed)
    sh = (ph * ss, pw * ss)
    cloud = V.fbm(rng, sh, (90.0 * ss, 40.0 * ss, 14.0 * ss), (0.5, 0.35, 0.15))
    wf = smoothstep(0.4, 1.4, V.fbm(rng, sh, (160.0 * ss, 60.0 * ss), (0.7, 0.3)))
    hair = rank01(fft_blur(rng.standard_normal(sh), (26.0 * ss, 0.5 * ss), wrap=True, angle=0.05))
    cm = rank01(noise(rng, sh, 30.0 * ss))
    crack = smoothstep(0.985, 0.996, hair) * smoothstep(0.3, 0.9, cm)
    yy, xx = np.mgrid[0:sh[0], 0:sh[1]].astype(np.float64)
    ang = 2 * math.pi * (xx / sh[1] + yy / sh[0])
    band = (0.5 + 0.5 * np.cos(ang - 2 * math.pi * 0.62)) ** 5
    rgb = LACQUER * (1 + 0.10 * cloud)[..., None]
    rgb = mixc(rgb, LACQUER_WARM, warm * wf)
    rgb = rgb + SHEEN * (sheen * band * (0.75 + 0.25 * cloud))[..., None]
    rgb = rgb * (1 - 0.30 * crack[..., None]) + hexc("#3A3430") * 0.06 * crack[..., None]
    return np.stack([c.periodic(rgb[..., k], *origin) for k in range(3)], -1)


def lacquer_plain(c: Canvas, seed, *, sheen=0.05):
    """不平铺的小件用的漆面（同配方，不要求周期）。"""
    return lacquer_field(c, (c.w, c.h), (0, 0), seed, sheen=sheen)


# ============================================================== 升级卡框

def card_gold(c: Canvas, rarity: str, per, origin, grain):
    """描金：外沿细金边、花边主线（节点内 8，贴图 16）、里面一道细线；天、合在外沿与主线之间串一圈连珠（周期 8，
    和平铺区对齐）；四角的结：灵、玄、异是方胜（空心菱形、两线出头），天、合是如意结（小圆环 + 两朵小卷 + 金珠）。"""
    R = RARITY[rarity]
    w, h = c.w, c.h
    L = CARD_SL
    m = np.zeros(c.X.shape)
    d0 = rrect_sd(c.X, c.Y, 4, 3, w - 4, h - 5, 14)
    m = np.maximum(m, smoothstep(1.3 + c.aa, 1.3 - c.aa, np.abs(d0 + 3.2)))
    d1 = rrect_sd(c.X, c.Y, 16, 16, w - 16, h - 16, 5)
    m = np.maximum(m, smoothstep((1.5 if R["lines"] == 1 else 2.1) + c.aa, (1.5 if R["lines"] == 1 else 2.1) - c.aa, np.abs(d1)))
    if R["lines"] >= 2:
        d2 = rrect_sd(c.X, c.Y, 24, 24, w - 24, h - 24, 3)
        m = np.maximum(m, smoothstep(0.85 + c.aa, 0.85 - c.aa, np.abs(d2)))
    marks = []
    if R["beads"]:  # 连珠：四边按平铺区对齐（周期 8），角上让给如意结
        yb, xb = 10.0, 10.5
        for x in list(np.arange(L + 4, w - L, 8.0)) + [L - 4 - 8 * k for k in range(4)] + [w - L + 4 + 8 * k for k in range(4)]:
            marks += [((x, yb), 2.3), ((x, h - 1 - yb), 2.3)]
        for y in list(np.arange(L + 4, h - L, 8.0)) + [L - 4 - 8 * k for k in range(4)] + [h - L + 4 + 8 * k for k in range(4)]:
            marks += [((xb, y), 2.3), ((w - xb, y), 2.3)]
    if R.get("dots"):  # 玄：细线里侧一圈小金点（周期 16）
        for x in list(np.arange(L + 8, w - L, 16.0)) + [L - 8, L - 24, w - L + 8, w - L + 24]:
            marks += [((x, 30.0), 1.4), ((x, h - 30.0), 1.4)]
        for y in list(np.arange(L + 8, h - L, 16.0)) + [L - 8, L - 24, h - L + 8, h - L + 24]:
            marks += [((30.0, y), 1.4), ((w - 30.0, y), 1.4)]
    paths = []
    for (sx, sy) in ((1, 1), (-1, 1), (1, -1), (-1, -1)):
        cx = 16 if sx > 0 else w - 16
        cy = 16 if sy > 0 else h - 16
        if R["knot"] == "fangsheng":
            paths.append((np.array([[cx - 7, cy], [cx, cy - 7], [cx + 7, cy], [cx, cy + 7], [cx - 7, cy]], float), 1.5))
            marks.append(((cx, cy), 2.0))
        elif R["knot"] == "ruyi":
            paths.append((spiral(cx, cy, 6.2, 6.2, 0, 1.0, 40), 1.6))
            for ux, uy in ((sx, 0), (0, sy)):
                px, py = cx + ux * 11.5, cy + uy * 11.5
                paths.append((spiral(px, py, 3.6, 1.2, math.atan2(-uy, -ux), 0.85, 24), 1.3))
            marks.append(((cx, cy), 2.6))
    for P, wd in paths:
        m = np.maximum(m, stroke_mask(c, P, wd))
    for (x, y), r in marks:
        m = np.maximum(m, dot(c, x, y, r))
    return m


def make_card(rarity: str) -> Image.Image:
    """升级卡框（600×920，切片 64，中间与四边平铺）。"""
    R = RARITY[rarity]
    W_, H_, L = CARD_W, CARD_H, CARD_SL
    seed = 1700 + list(RARITY).index(rarity) * 10
    c = Canvas(W_, H_, seed, ss=2)
    per, origin = (W_ - 2 * L, H_ - 2 * L), (L, L)
    ds = rrect_sd(c.X, c.Y, 5, 6, W_ - 5, H_ - 3, 15)
    c.over(np.zeros(3), 0.6 * np.exp(-np.maximum(ds, 0) ** 2 / (2 * 2.2 ** 2)) * (ds > -1))
    d = rrect_sd(c.X, c.Y, 4, 3, W_ - 4, H_ - 5, 14)
    body = smoothstep(c.aa, -c.aa, d)
    rgb = lacquer_field(c, per, origin, seed + 1)
    edge = np.exp(-np.maximum(-d, 0) / 3.0)
    rgb = rgb * (1 - 0.35 * edge[..., None]) + hexc("#5A5650") * (0.10 * np.exp(-np.maximum(-d - 1.0, 0) / 1.2))[..., None]
    if R["band"]:  # 异：主线和细线之间一道朱漆
        d1 = rrect_sd(c.X, c.Y, 16, 16, W_ - 16, H_ - 16, 5)
        d2 = rrect_sd(c.X, c.Y, 24, 24, W_ - 24, H_ - 24, 3)
        bandm = smoothstep(c.aa, -c.aa, d1) * smoothstep(-c.aa, c.aa, d2)
        rgb = mixc(rgb, hexc(R["band"]) * (1 + 0.15 * c.pnoise(per, origin, 6.0, seed + 2))[..., None], bandm * 0.9)
    d2 = rrect_sd(c.X, c.Y, 24, 24, W_ - 24, H_ - 24, 3)
    inner = np.exp(-np.maximum(-d2 - 1.5, 0) / R["gw"]) * (d2 < -0.8)
    edge_dist = np.minimum(np.minimum(c.X, W_ - c.X), np.minimum(c.Y, H_ - c.Y))
    inner = inner * smoothstep(L - 1.0, L - 16.0, edge_dist)  # 光收在切片以内，中间平铺区不带光（周期）
    wob = 0.8 + 0.2 * c.pnoise(per, origin, 40.0, seed + 3)
    gl = hexc(R["glow"])
    rgb = 1 - (1 - np.clip(rgb, 0, 1)) * (1 - gl * (R["ga"] * inner * wob)[..., None])
    c.over(np.clip(rgb, 0, 1), body)
    grain = c.pnoise(per, origin, 2.0, seed + 4)
    gm = card_gold(c, rarity, per, origin, grain)
    if rarity == "fan":  # 凡：金磨得旧，露出一点漆
        worn = smoothstep(0.55, 0.95, 0.5 + 0.25 * c.pnoise(per, origin, 2.5, seed + 5))
        gm = gm * (1 - 0.5 * worn)
    c.over(metal(c, gm, R["gold"], grain=grain), gm * body)
    if R["flecks"]:  # 洒金：画在一个周期的画布上再铺开（四边、中间都连续），靠边多
        fl = Canvas(per[0], per[1], seed + 6, ss=2)
        rng = fl.rng
        for _ in range(R["flecks"]):
            x, y = rng.uniform(0, per[0]), rng.uniform(0, per[1])
            rr = rng.uniform(0.5, 1.5)
            poly = [(x + rr * math.cos(a) * rng.uniform(0.5, 1.3), y + rr * math.sin(a) * rng.uniform(0.5, 1.3))
                    for a in np.sort(rng.uniform(0, 2 * math.pi, 5))]
            dist, _ = W.poly_sdf(fl.X, fl.Y, poly, pad=2.0)
            fl.over(np.ones(3), smoothstep(fl.aa, -fl.aa, dist) * rng.uniform(0.5, 1.0))
        fm = c.periodic(fl.lay.a, *origin) * (d < -2.0)
        c.over(metal(c, fm, GOLD, sigma=0.35, base=0.10), fm * body)
    return finish(c)


def make_card_focus() -> Image.Image:
    """卡片焦点（624×944，节点比卡片每边大 6；切片 64，拉伸）：卡边上一道泥金亮线、往外一圈暖光，四角略亮。"""
    W_, H_ = CARD_W + 2 * FOCUS_PAD, CARD_H + 2 * FOCUS_PAD
    P = FOCUS_PAD
    c = Canvas(W_, H_, 1790, ss=2)
    d = rrect_sd(c.X, c.Y, P + 4, P + 3, W_ - P - 4, H_ - P - 5, 14)
    glow = np.exp(-np.maximum(d, 0) ** 2 / (2 * 5.0 ** 2)) * (d > -2)
    cx = np.minimum(c.X, W_ - c.X)
    cy = np.minimum(c.Y, H_ - c.Y)
    corner = np.exp(-((cx - P) ** 2 + (cy - P) ** 2) / (2 * 14.0 ** 2)) * ((cx < 56) & (cy < 56))
    c.over(hexc("#FFC062"), np.clip(0.75 * glow * (0.75 + 0.6 * corner), 0, 1))
    line = smoothstep(1.8 + c.aa, 1.8 - c.aa, np.abs(d + 1.0))
    c.over(hexc("#FFF0C0"), line)
    inner = np.exp(-np.maximum(-d, 0) / 9.0) * (d < 0) * (-d < 40)
    c.over(hexc("#FFD48A"), inner * 0.22)
    return finish(c)


# ============================================================== 横条：底槽、填充、小签

def make_chip() -> Image.Image:
    """小签（chip_dark，80×48，左右 24 的横向九宫格）：一块黑漆小牌，细金边。卡上的品阶签、HUD 的五行计数用。"""
    Wd, H = 80, 48
    c = Canvas(Wd, H, 1800, ss=4)
    d = rrect_sd(c.X, c.Y, 2, 4, Wd - 2, H - 4, 13)
    body = smoothstep(c.aa, -c.aa, d)
    rgb = LACQUER * (1 + 0.25 * np.exp(-((c.Y - 12) / 6.0) ** 2))[..., None]
    rgb = rgb + SHEEN * (0.05 * np.exp(-((c.Y - 13) / 3.0) ** 2))[..., None]
    c.over(rgb, body * 0.95)
    rim = smoothstep(1.2 + c.aa, 1.2 - c.aa, np.abs(d + 1.0)) * body
    c.over(metal(c, rim, GOLD, sigma=0.4), rim)
    return finish(c, band_x=(24, 24))


def make_track(big: str = "") -> Image.Image:
    """底槽：黑漆槽 + 细金边，槽里深、上沿一道内阴影。
    bar_track 128×36（左右 24）：填充放在里面，四周各留 4（逻辑 2）；
    hud_hp_track 256×60（左右 48）：大血条框（逻辑 460×30），填充四周各留 14（逻辑 7），两头各一粒金珠夹两道短金线；
    hud_xp_track 128×20（左右 16）：经验条框（逻辑高 10），填充四周各留 4。"""
    Wd, H, L, inset, r = {"": (128, 36, 24, 4.0, 12.0), "hp": (256, 60, 48, 14.0, 18.0), "xp": (128, 20, 16, 4.0, 7.0)}[big]
    c = Canvas(Wd, H, 1810 + len(big), ss=4)
    d = rrect_sd(c.X, c.Y, 1.5, 1.5, Wd - 1.5, H - 1.5, r)
    body = smoothstep(c.aa, -c.aa, d)
    shade = 1 + 0.35 * np.exp(-((c.Y - H * 0.22) / (H * 0.12)) ** 2)
    rgb = LACQUER * shade[..., None] + SHEEN * (0.06 * np.exp(-((c.Y - H * 0.18) / (H * 0.06)) ** 2))[..., None]
    c.over(rgb, body)
    rim = smoothstep(1.2 + c.aa, 1.2 - c.aa, np.abs(d + (2.6 if big != "hp" else 3.2)))
    c.over(metal(c, rim, GOLD, sigma=0.45), rim)
    tr = rrect_sd(c.X, c.Y, inset, inset, Wd - inset, H - inset, max(r - inset + 2, 2.0))
    tb = smoothstep(c.aa, -c.aa, tr)
    inner_sh = np.exp(-np.maximum(c.Y - inset, 0) / max(2.0, (H - 2 * inset) * 0.25))
    c.over(hexc("#050607") * (1 + 0.6 * (1 - inner_sh))[..., None] * 1.2, tb * 0.97)
    if big == "hp":
        lip = smoothstep(1.0 + c.aa, 1.0 - c.aa, np.abs(tr + 0.6))
        c.over(metal(c, lip, GOLD_OLD, sigma=0.4), lip * 0.9)
        for sx in (1, -1):
            x0 = 8.0 if sx > 0 else Wd - 8.0
            m = dot(c, x0, H / 2, 3.4)
            for dy in (-1, 1):
                m = np.maximum(m, stroke_mask(c, [(x0 + 0.5 * sx, H / 2 + dy * 9), (x0 + 0.5 * sx, H / 2 + dy * 18)], 1.0))
            c.over(metal(c, m, GOLD, sigma=0.5, depth=1.3), m)
    return finish(c, band_x=(L, L))


FILL = {
    # 上沿亮色、下沿暗色、高光强度
    "hp": ("#E8553C", "#7E1A14", 0.28),
    "xp": ("#F6D27A", "#9C6A1E", 0.30),
    "shield": ("#EAF6FF", "#7FB6E6", 0.18),
    "trail": ("#FFF0DA", "#E3C29C", 0.0),
}


def make_fill(kind: str) -> Image.Image:
    """填充（中段沿 x 完全一致，两头圆收在切片以内）：hp 朱漆红、xp 泥金、shield 淡青白（细条，叠在血条上半）、
    trail 掉血残影（浅，画在血条后面，比血条慢半拍缩回）。漆面上一道横向高光。"""
    shield = kind == "shield"
    Wd, H, L = (96, 12, 10) if shield else (96, 28, 20)
    c = Canvas(Wd, H, 1830 + len(kind), ss=4)
    r = H * 0.45
    d = rrect_sd(c.X, c.Y, 2.0, 1.0, Wd - 2.0, H - 1.0, r)
    m = smoothstep(c.aa, -c.aa, d)
    top, bot, gl = FILL[kind]
    t = np.clip((c.Y - 1.0) / (H - 2.0), 0, 1)
    rgb = mixc(hexc(top), hexc(bot), t ** 0.9)
    if gl:
        rgb = rgb + hexc("#FFF0DC") * (gl * np.exp(-((t - 0.24) / 0.10) ** 2))[..., None]
    c.over(np.clip(rgb, 0, 1), m)
    return finish(c, band_x=(L, L))


# ============================================================== 格子

def make_slot(big: bool, kind: str) -> Image.Image:
    """法器格 128²（逻辑 64）/ 心法格 88²（逻辑 44），不切片。kind：full 黑漆方砚 + 金边；empty 只有一道淡金虚边；
    evo 进化：双金边、暖光、角上洒金。"""
    N = 128 if big else 88
    k = N / 128.0
    c = Canvas(N, N, 1850 + 10 * big + {"full": 0, "empty": 1, "evo": 2}[kind], ss=4)
    r = 14.0 * k
    d = rrect_sd(c.X, c.Y, 3, 3, N - 3, N - 3, r)
    body = smoothstep(c.aa, -c.aa, d)
    if kind == "empty":
        c.over(np.zeros(3), body * 0.30)
        per = np.arange(0, 1, 1 / (24 if big else 18))
        m = np.zeros(c.X.shape)
        # 虚边：沿圆角矩形一段一段的短金线
        pts = rrect_path(6, 6, N - 6, N - 6, r - 3, 1.0)
        seg = (np.arange(len(pts)) // (7 if big else 5)) % 2 == 0
        for p in pts[seg][::2]:
            m = np.maximum(m, dot(c, p[0], p[1], 1.25))
        c.over(metal(c, m, GOLD_OLD, sigma=0.3), m * 0.55)
        _ = per
        return finish(c)
    rgb = lacquer_plain(c, 1860 + big)
    rr = np.hypot(c.X - N / 2, c.Y - N / 2) / (N / 2)
    rgb = rgb * (1 + 0.5 * np.exp(-(rr / 0.7) ** 2))[..., None]  # 砚池：中间略亮
    inner = np.exp(-np.maximum(-d - 6, 0) / 6.0) * (d < -6)
    c.over(rgb, body)
    c.over(np.zeros(3), body * inner * 0.35)
    rim = smoothstep(1.4 + c.aa, 1.4 - c.aa, np.abs(d + 4.0))
    if kind == "evo":
        rim = np.maximum(rim, smoothstep(0.9 + c.aa, 0.9 - c.aa, np.abs(d + 8.5)))
        c.over(hexc("#FFB04A"), body * 0.10 * np.exp(-(rr / 0.6) ** 2))
    c.over(metal(c, rim, GOLD, sigma=0.5), rim)
    if kind == "evo":
        rng = np.random.default_rng(1870 + big)
        fm = np.zeros(c.X.shape)
        for _ in range(16 if big else 10):
            q = rng.integers(4)
            x = rng.uniform(5, 22 * k) if q in (0, 3) else N - rng.uniform(5, 22 * k)
            y = rng.uniform(5, 22 * k) if q in (0, 1) else N - rng.uniform(5, 22 * k)
            fm = np.maximum(fm, dot(c, x, y, rng.uniform(0.5, 1.3)))
        c.over(metal(c, fm, GOLD, sigma=0.3, base=0.1), fm * body)
    return finish(c)


def rrect_path(x0, y0, x1, y1, r, step):
    """圆角矩形上等距的点（顺时针，从顶边左端起）。"""
    path = []
    segs = [((x0 + r, y0), (x1 - r, y0)), ((x1, y0 + r), (x1, y1 - r)), ((x1 - r, y1), (x0 + r, y1)), ((x0, y1 - r), (x0, y0 + r))]
    arcs = [(x1 - r, y0 + r, -90), (x1 - r, y1 - r, 0), (x0 + r, y1 - r, 90), (x0 + r, y0 + r, 180)]
    for k in range(4):
        (ax, ay), (bx, by) = segs[k]
        n = max(2, int(math.hypot(bx - ax, by - ay) / 0.25))
        path += [(ax + (bx - ax) * t, ay + (by - ay) * t) for t in np.linspace(0, 1, n, endpoint=False)]
        cx, cy, a0 = arcs[k]
        n = max(2, int(r * math.pi / 2 / 0.25))
        path += [(cx + r * math.cos(math.radians(a0 + 90 * t)), cy + r * math.sin(math.radians(a0 + 90 * t)))
                 for t in np.linspace(0, 1, n, endpoint=False)]
    P = np.array(path)
    seg = np.hypot(*np.diff(np.vstack([P, P[:1]]), axis=0).T)
    sl = np.concatenate([[0.0], np.cumsum(seg)])
    n = int(sl[-1] // step)
    u = np.arange(n) * (sl[-1] / n)
    Pc = np.vstack([P, P[:1]])
    return np.stack([np.interp(u, sl, Pc[:, 0]), np.interp(u, sl, Pc[:, 1])], -1)


# ============================================================== 状态栏的新件

PORTRAIT, WINDOW = 208, 156  # 头像章外径 / 窗口直径（贴图像素；逻辑 104 / 78）


def make_portrait() -> Image.Image:
    """头像章（208²，逻辑 104，不切片）：黑漆圆盘，外沿一道细金圈、窗口边一道粗金圈；窗口透明，头像画在下面。
    燃灯的十二格刻度（hud_ult_tick*）绕在漆圈上，由界面按角度摆放（半径 = 外径 / 2 − 17，贴图像素）。"""
    N = PORTRAIT
    c = Canvas(N, N, 1880, ss=4)
    cc = N / 2
    rr = np.hypot(c.X - cc, c.Y - cc)
    ring = smoothstep(c.aa, -c.aa, rr - (cc - 2)) * smoothstep(-c.aa, c.aa, rr - WINDOW / 2 - 1.5)  # 窗口边由金圈收
    c.over(lacquer_plain(c, 1881), ring)
    for rad, hw in ((cc - 5.0, 1.4), (WINDOW / 2 + 2.5, 2.4)):
        m = smoothstep(hw + c.aa, hw - c.aa, np.abs(rr - rad))
        c.over(metal(c, m, GOLD, sigma=0.5, depth=1.2), m)
    return finish(c)


def make_ult_tick(state: str) -> Image.Image:
    """燃灯刻度的一格（34×20，逻辑 17×10，长边沿圆周、朝外为上）：off 暗槽（深褐底、内沿一道暗金、外圈旧金边，
    在黑漆环上 720p 也看得出一格格，但明显比亮格暗）；on 灯焰色；full 满格更亮、带光。"""
    W_, H_ = 34, 20
    c = Canvas(W_, H_, 1890, ss=4)
    d = rrect_sd(c.X, c.Y, 6, 5, W_ - 6, H_ - 5, 4.0)
    m = smoothstep(c.aa, -c.aa, d)
    if state == "off":
        c.over(hexc("#4A3924"), m * 0.95)
        inner = smoothstep(-1.0, -3.2, d) * m  # 槽心压暗一点，像凹下去的一格
        c.over(hexc("#1E160E"), inner * 0.55)
        top = smoothstep(1.2, 0.0, np.abs(c.Y - 6.4)) * smoothstep(0.0, -1.0, d)  # 槽口朝外的一边一道暗金
        c.over(hexc("#6B5434"), top * 0.6)
        rim = smoothstep(1.1 + c.aa, 1.1 - c.aa, np.abs(d + 0.7))
        c.over(hexc("#A88A52"), rim * 0.95)
    else:
        full = state == "full"
        glow = np.exp(-np.maximum(d, 0) ** 2 / (2 * (2.8 if full else 1.8) ** 2))
        c.over(hexc("#FFB04A"), glow * (0.85 if full else 0.6))
        col = mixc(hexc("#FFF2C4"), hexc("#FF8A2E"), np.clip((c.Y - 5) / (H_ - 10) * 1.2, 0, 1))
        c.over(col if not full else mixc(col, hexc("#FFFFFF"), 0.2), m)
    return finish(c)


def make_level_seal() -> Image.Image:
    """等级印（60²，逻辑 30）：朱砂方印，印框留白，等级数字由界面写（建议马善政 17 号、纸色）。"""
    N = 60
    ss = 4
    n = N * ss
    rng = np.random.default_rng(1895)
    Y, X = np.mgrid[0:n, 0:n].astype(np.float64) + 0.5
    cc = n / 2
    wob = 0.012 * n * noise(rng, (n, n), n * 0.07)
    d = np.maximum(np.abs(X - cc), np.abs(Y - cc)) + wob - n * 0.45
    plate = smoothstep(1.5 * ss, -1.5 * ss, d)
    frame = smoothstep(0.9 * ss, 0.0, np.abs(d + n * 0.06))
    ink = 0.88 + 0.08 * noise(rng, (n, n), 6.0 * ss)
    specks = smoothstep(2.2, 2.6, noise(rng, (n, n), 1.3 * ss))
    a = plate * (1 - frame) * np.clip(ink, 0, 1) * (1 - specks)
    lay = V.Layer(n, n)
    lay.over(hexc("#B8321F"), a)
    lay = lay.down(ss)
    rgb, al = lay.straight()
    return V.to_rgba8(rgb, al)


# ============================================================== 数值小图标

STAT_KEYS = ["health", "armor", "reduction", "regen", "speed", "damage", "cooldown", "area", "count", "crit", "crit_dmg", "magnet"]
GROUP_KEYS = ["base", "output", "survival", "lamp", "build", "night", "weapons"]
STAT_NAMES = {"health": "生命", "armor": "护甲", "reduction": "减伤", "regen": "回血", "speed": "移速", "damage": "伤害",
              "cooldown": "冷却", "area": "范围", "count": "数量", "crit": "暴击率", "crit_dmg": "暴击伤害", "magnet": "拾取范围",
              "group_base": "基础", "group_output": "输出", "group_survival": "生存", "group_lamp": "灯与照见",
              "group_build": "构筑与收益", "group_night": "今夜妖物", "group_weapons": "法器"}


def glyph(key: str, c: Canvas) -> np.ndarray:
    """金线符号的覆盖度（64² 画布，中心 32,32，符号大约占 36 像素见方；线宽 3.4，20 像素显示时约 1 像素）。"""
    m = np.zeros(c.X.shape)
    lw = 3.4

    def line(pts, w=lw):
        nonlocal m
        m = np.maximum(m, stroke_mask(c, pts, w / 2))

    def fill(poly):
        nonlocal m
        dist, _ = W.poly_sdf(c.X, c.Y, poly, pad=2.0)
        m = np.maximum(m, smoothstep(c.aa, -c.aa, dist))

    def arc(cx, cy, r, a0, a1, w=lw, n=48):
        t = np.radians(np.linspace(a0, a1, n))
        line(np.stack([cx + r * np.cos(t), cy + r * np.sin(t)], -1), w)

    def bez(ctrl, n=40):
        return V.bezier(ctrl, n)

    if key == "health":  # 寿桃（心形）+ 一片叶
        t = np.linspace(0, 2 * math.pi, 120)
        x = 16 * np.sin(t) ** 3
        y = -(13 * np.cos(t) - 5 * np.cos(2 * t) - 2 * np.cos(3 * t) - np.cos(4 * t))
        fill(np.stack([32 + x * 0.95, 34 + y * 0.95], -1))
        line(bez([(33, 18), (38, 11), (45, 12), (47, 15)]), 2.6)
    elif key == "armor":  # 鱼鳞甲：盾形里三排鳞
        shield = [(32, 13), (49, 19), (47, 37), (32, 51), (17, 37), (15, 19)]
        line(np.vstack([shield, shield[:1]]), lw)
        for row, y in enumerate((27, 35, 43)):
            for x in ((24, 32, 40) if row != 2 else (28, 36)):
                arc(x, y - 4, 4.2, 20, 160, 2.2, 16)
    elif key == "reduction":  # 盾 + 断箭
        shield = [(30, 15), (45, 21), (43, 37), (30, 50), (17, 37), (15, 21)]
        line(np.vstack([shield, shield[:1]]), lw)
        line([(54, 8), (44, 18)], 2.8)
        line([(39, 25), (34, 30)], 2.8)
        fill([(55, 7), (49, 9), (53, 13)])
    elif key == "regen":  # 新芽 + 十字
        line(bez([(28, 52), (28, 42), (29, 34), (31, 28)]), lw)
        fill(np.vstack([bez([(31, 30), (22, 30), (15, 22), (16, 14)]), bez([(16, 14), (26, 15), (31, 22), (31, 30)])]))
        fill(np.vstack([bez([(31, 34), (38, 30), (44, 31), (47, 26)]), bez([(47, 26), (44, 36), (36, 38), (31, 37)])]))
        line([(47, 41), (47, 53)], 3.0)
        line([(41, 47), (53, 47)], 3.0)
    elif key == "speed":  # 三道风 + 一个卷
        for y, x0, x1 in ((22, 10, 44), (32, 6, 52), (42, 14, 42)):
            line(bez([(x0, y + 3), ((x0 + x1) / 2, y - 2), (x1, y), (x1 + 2, y - 6)]), lw)
        line(spiral(47, 20, 6.5, 1.5, math.radians(90), 0.8, 30, sx=-1), 2.8)
    elif key == "damage":  # 一柄剑（剑尖朝上）
        fill([(32, 8), (35.5, 14), (35, 40), (29, 40), (28.5, 14)])
        line([(21, 41), (43, 41)], 3.6)
        line([(32, 43), (32, 53)], 3.6)
        m = np.maximum(m, dot(c, 32, 56, 3.0))
    elif key == "cooldown":  # 沙漏
        line([(19, 11), (45, 11)], 3.4)
        line([(19, 53), (45, 53)], 3.4)
        line(bez([(22, 12), (22, 26), (32, 28), (32, 32)]) , 3.0)
        line(bez([(42, 12), (42, 26), (32, 28), (32, 32)]), 3.0)
        line(bez([(32, 32), (32, 36), (22, 38), (22, 52)]), 3.0)
        line(bez([(32, 32), (32, 36), (42, 38), (42, 52)]), 3.0)
        fill([(25, 50), (39, 50), (32, 42)])
    elif key == "area":  # 一圈涟漪 + 四个向外的箭头
        arc(32, 32, 11, 0, 360, 3.2, 60)
        m = np.maximum(m, dot(c, 32, 32, 3.2))
        for a in (45, 135, 225, 315):
            ca, sa = math.cos(math.radians(a)), math.sin(math.radians(a))
            line([(32 + 16 * ca, 32 + 16 * sa), (32 + 24 * ca, 32 + 24 * sa)], 3.0)
            tip = (32 + 27 * ca, 32 + 27 * sa)
            fill([tip, (32 + 21 * ca - 4 * sa, 32 + 21 * sa + 4 * ca), (32 + 21 * ca + 4 * sa, 32 + 21 * sa - 4 * ca)])
    elif key == "count":  # 三柄小剑成扇
        for a in (-28, 0, 28):
            ca, sa = math.sin(math.radians(a)), -math.cos(math.radians(a))
            bx, by = 32 + 4 * ca * 0, 52
            tip = (bx + 38 * ca, by + 38 * sa)
            line([(bx + 8 * ca, by + 8 * sa), tip], 3.0)
            m = np.maximum(m, dot(c, *tip, 2.2))
        m = np.maximum(m, dot(c, 32, 52, 3.4))
    elif key == "crit":  # 准星：圆 + 四道刻 + 中心点
        arc(32, 32, 15, 0, 360, 3.0, 64)
        for a in (0, 90, 180, 270):
            ca, sa = math.cos(math.radians(a)), math.sin(math.radians(a))
            line([(32 + 9 * ca, 32 + 9 * sa), (32 + 22 * ca, 32 + 22 * sa)], 3.0)
        m = np.maximum(m, dot(c, 32, 32, 3.2))
    elif key == "crit_dmg":  # 八角迸星
        pts = []
        for i in range(16):
            r = 22 if i % 2 == 0 else 8
            if i % 4 == 2:
                r = 14
            a = math.radians(-90 + i * 22.5)
            pts.append((32 + r * math.cos(a), 32 + r * math.sin(a)))
        fill(pts)
    elif key == "magnet":  # 马蹄形磁石 + 两点魂火
        arc(32, 34, 12, 0, 180, 6.0, 40)
        line([(20, 34), (20, 18)], 6.0)
        line([(44, 34), (44, 18)], 6.0)
        m = np.where((c.Y < 21) & (c.Y > 13) & ((np.abs(c.X - 20) < 3.2) | (np.abs(c.X - 44) < 3.2)), m * 0.35, m)
        m = np.maximum(m, dot(c, 26, 9, 2.4))
        m = np.maximum(m, dot(c, 38, 7, 1.8))
    elif key == "group_base":  # 人：一个提灯的小人
        m = np.maximum(m, dot(c, 30, 14, 5.0))
        line(bez([(30, 20), (29, 30), (30, 38), (31, 44)]), 4.4)
        line([(30, 44), (24, 55)], 3.6)
        line([(30, 44), (37, 55)], 3.6)
        line([(30, 26), (42, 30)], 3.2)
        line([(42, 30), (44, 36)], 2.0)
        m = np.maximum(m, dot(c, 45, 40, 4.0))
        line([(29, 27), (22, 34)], 3.0)
    elif key == "group_output":  # 两剑相交
        for s_ in (1, -1):
            a = math.radians(45 * s_)
            ux, uy = math.sin(a), -math.cos(a)
            tip = (32 + 22 * ux, 32 + 22 * uy)
            hilt = (32 - 18 * ux, 32 - 18 * uy)
            line([hilt, tip], 3.4)
            gx, gy = 32 - 11 * ux, 32 - 11 * uy
            line([(gx - 6 * uy * -1, gy + 6 * ux * -1), (gx + 6 * uy * -1, gy - 6 * ux * -1)], 3.0)
    elif key == "group_survival":  # 盾里一颗心
        shield = [(32, 10), (50, 17), (48, 36), (32, 53), (16, 36), (14, 17)]
        line(np.vstack([shield, shield[:1]]), 3.4)
        t = np.linspace(0, 2 * math.pi, 80)
        x = 16 * np.sin(t) ** 3
        y = -(13 * np.cos(t) - 5 * np.cos(2 * t) - 2 * np.cos(3 * t) - np.cos(4 * t))
        fill(np.stack([32 + x * 0.5, 31 + y * 0.5], -1))
    elif key == "group_lamp":  # 灯笼
        line([(32, 6), (32, 12)], 2.6)
        line([(25, 13), (39, 13)], 3.4)
        line([(25, 50), (39, 50)], 3.4)
        t = np.linspace(-1, 1, 40)
        line(np.stack([32 + 15 * np.sqrt(1 - t ** 2), 31.5 + 17 * t], -1), 3.0)
        line(np.stack([32 - 15 * np.sqrt(1 - t ** 2), 31.5 + 17 * t], -1), 3.0)
        line(np.stack([32 + 5 * np.sqrt(1 - t ** 2), 31.5 + 17 * t], -1), 1.8)
        line(np.stack([32 - 5 * np.sqrt(1 - t ** 2), 31.5 + 17 * t], -1), 1.8)
        line([(32, 51), (32, 58)], 2.6)
    elif key == "group_build":  # 铜钱（方孔）
        arc(32, 32, 19, 0, 360, 3.6, 72)
        sq = [(25, 25), (39, 25), (39, 39), (25, 39), (25, 25)]
        line(sq, 3.4)
        for a in (45, 135, 225, 315):
            ca, sa = math.cos(math.radians(a)), math.sin(math.radians(a))
            m = np.maximum(m, dot(c, 32 + 13 * ca, 32 + 13 * sa, 1.8))
    elif key == "group_night":  # 一弯月 + 一双妖眼
        moon = np.hypot(c.X - 30, c.Y - 28) < 17
        cut = np.hypot(c.X - 38, c.Y - 22) < 15
        m = np.maximum(m, fft_blur((moon & ~cut).astype(np.float64), 0.6 * c.ss))
        for ex in (35, 47):
            e = np.hypot((c.X - ex) / 3.6, (c.Y - 47) / 2.0) < 1
            m = np.maximum(m, fft_blur(e.astype(np.float64), 0.5 * c.ss))
    elif key == "group_weapons":  # 六格法器栏
        for i in range(3):
            for j in range(2):
                x0, y0 = 11 + i * 15, 18 + j * 15
                line([(x0, y0), (x0 + 11, y0), (x0 + 11, y0 + 11), (x0, y0 + 11), (x0, y0)], 2.6)
        m = np.maximum(m, dot(c, 16.5, 23.5, 3.0))
        m = np.maximum(m, dot(c, 31.5, 23.5, 3.0))
    return np.clip(m, 0, 1)


class _Scaled:
    """把画布坐标绕中心缩放 k 倍的影子：在它上面按原坐标画，符号（连同线宽）整体放大 k 倍。"""

    def __init__(self, c: Canvas, k: float):
        cx, cy = c.w / 2, c.h / 2
        self.X = cx + (c.X - cx) / k
        self.Y = cy + (c.Y - cy) / k
        self.aa, self.ss, self.w, self.h = c.aa / k, c.ss, c.w, c.h


def make_stat_icon(key: str) -> Image.Image:
    """数值小图标（64²）：黑漆小圆章，一道细金圈，中间金线刻的符号（略浮起）。20 像素下靠剪影认，32 像素看得见细节。"""
    N = 64
    c = Canvas(N, N, 1900 + sum(map(ord, key)), ss=4)
    rr = np.hypot(c.X - 32, c.Y - 32)
    disc = smoothstep(31.0 + c.aa, 31.0 - c.aa, rr)
    rgb = LACQUER * (1 + 1.2 * np.exp(-((c.Y - 16) / 10.0) ** 2) * (rr < 30))[..., None]
    c.over(rgb, disc)
    rim = smoothstep(1.0 + c.aa, 1.0 - c.aa, np.abs(rr - 29.2))
    c.over(metal(c, rim, GOLD_OLD, sigma=0.35), rim)
    g = glyph(key, _Scaled(c, 1.12))
    # 符号：金，四周压一圈墨（压在花底上也清楚）
    halo = np.clip(fft_blur(g, 1.6 * c.ss) * 3.0, 0, 1)
    c.over(hexc("#050403"), halo * 0.85 * disc)
    c.over(metal(c, g, GOLD, sigma=0.45, depth=1.0, base=0.06), g)
    return finish(c)


def build_stat_icons() -> dict[str, Image.Image]:
    out = {f"stat_{k}": make_stat_icon(k) for k in STAT_KEYS}
    out.update({f"stat_group_{k}": make_stat_icon(f"group_{k}") for k in GROUP_KEYS})
    return out


def save_stat_icons(icons: dict[str, Image.Image]) -> None:
    STATS_DIR.mkdir(parents=True, exist_ok=True)
    files = {}
    for name, img in icons.items():
        img.save(STATS_DIR / f"{name}.png", optimize=True)
        key = name[5:]
        files[f"{name}.png"] = {"size": [img.width, img.height], "anchor": [0.5, 0.5], "blend": "normal", "tint": False,
                                "kind": "stat_icon", "id": key, "name": STAT_NAMES[key]}
    meta = {"name": "ui", "generator": "art/post/ui_lacquer.py",
            "format": "PNG RGBA，直通 alpha；黑漆小圆章 + 金线符号，原图 64²，界面显示 32（卡片）/ 20（属性格），不染色",
            "px_per_unit": 4, "display_px_1x": 32, "files": files}
    (STATS_DIR / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


# ============================================================== 审图（1080p，界面 1:1 逻辑像素）

def review(path: Path) -> None:
    """1080p 审图：升级卡三张（凡、灵、天）+ 异、合、焦点；状态栏一块；数值图标 32 / 20 两种尺寸。
    界面只缩小不放大，所以 1080p、100% 缩放下卡片就是 300×460 物理像素，这里按 1:1 画。"""
    import ui_skin as U  # noqa: PLC0415

    sp = U.specs()
    names = ["card_fan", "card_ling", "card_xuan", "card_tian", "card_yi", "card_he", "card_focus", "chip_dark", "bar_track",
             "bar_fill_hp", "bar_fill_xp", "bar_fill_shield", "bar_fill_trail", "hud_hp_track", "hud_xp_track", "slot_l",
             "slot_l_empty", "slot_l_evo", "slot_s", "slot_s_empty", "slot_s_evo", "hud_portrait", "hud_ult_tick",
             "hud_ult_tick_on", "hud_ult_tick_full", "hud_level_seal"]
    imgs = U.build(names)
    sk = U.Skin(imgs, sp, 0.5)
    bg = Image.open(OUT / "review@2x" / "night_scene.png").convert("RGB").resize((1920, 1080), Image.LANCZOS)
    a = np.asarray(bg, np.float64) / 255.0
    a = np.clip(a * np.array([1.25, 1.35, 1.6]) + np.array([0.03, 0.04, 0.07]), 0, 1) * 0.55
    B = Image.fromarray((a * 255).astype(np.uint8)).convert("RGBA")
    fs = lambda z: ImageFont.truetype(str(FONT_SERIF), int(z))  # noqa: E731
    fb = lambda z: ImageFont.truetype(str(FONT_BRUSH), int(z))  # noqa: E731
    dr = ImageDraw.Draw(B)

    def put(im, x, y):
        B.alpha_composite(im, (int(x), int(y)))

    # 卡片：六种稀有度 + 一张带焦点
    x0, y0 = 40, 300
    for i, r in enumerate(("fan", "ling", "xuan", "tian", "yi", "he")):
        x = x0 + i * 316
        put(sk(f"card_{r}", 300, 460), x, y0)
        dr.text((x + 150, y0 + 250), {"fan": "凡品", "ling": "灵品", "xuan": "玄品", "tian": "天品", "yi": "异化", "he": "合璧"}[r],
                font=fb(30), fill="#E6CF96", anchor="mm")
        if r == "ling":
            put(sk("card_focus", 312, 472), x - 6, y0 - 6)
    # 状态栏
    sx, sy = 40, 20
    put(sk("hud_portrait", 104, 104), sx, sy)
    for i in range(12):
        tk = sk("hud_ult_tick_on" if i < 8 else "hud_ult_tick", 17, 10).rotate(-(30 * i + 15), resample=Image.BICUBIC, expand=True)
        ang = math.radians(-90 + 30 * i + 15)
        cx, cy = sx + 52 + 43.5 * math.cos(ang), sy + 52 + 43.5 * math.sin(ang)
        put(tk, cx - tk.width / 2, cy - tk.height / 2)
    put(sk("hud_level_seal", 30, 30), sx + 84, sy + 82)
    dr.text((sx + 99, sy + 97), "12", font=fb(17), fill="#F6EEDC", anchor="mm")
    bx = sx + 118
    put(sk("hud_hp_track", 460, 30), bx, sy + 18)
    put(sk("bar_fill_trail", 446 * 0.80, 16), bx + 7, sy + 25)
    put(sk("bar_fill_hp", 446 * 0.72, 16), bx + 7, sy + 25)
    put(sk("bar_fill_shield", 446 * 0.22, 8), bx + 7, sy + 25)
    dr.text((bx + 446, sy + 33), "86 / 120", font=fs(17), fill="#FFF6E8", anchor="rm")
    put(sk("hud_xp_track", 460, 10), bx, sy + 54)
    put(sk("bar_fill_xp", 452 * 0.63, 6), bx + 4, sy + 56)
    for i in range(6):
        put(sk("slot_l" if i < 2 else ("slot_l_evo" if i == 2 else "slot_l_empty"), 64, 64), bx + i * 72, sy + 72)
    for i in range(6):
        put(sk("slot_s" if i < 3 else "slot_s_empty", 44, 44), bx + i * 50, sy + 144)
    # 小件：底槽 + 填充、小签
    tx = 1000
    put(sk("bar_track", 280, 18), tx, 40)
    put(sk("bar_fill_hp", 276 * 0.7, 14), tx + 2, 42)
    put(sk("bar_track", 200, 12), tx, 72)
    put(sk("bar_fill_xp", 196 * 0.45, 8), tx + 2, 74)
    for i, (t, col) in enumerate((("金 1", "#E2B23A"), ("木 3", "#82A489"), ("水 2", "#6B8EAB"), ("火 3", "#EA7841"), ("天品", "#FFD98A"))):
        put(sk("chip_dark", 64, 24), tx + i * 72, 100)
        dr.text((tx + i * 72 + 32, 112), t, font=fs(14), fill=col, anchor="mm")
    # 数值图标：32 与 20
    icons = build_stat_icons()
    ix, iy = 1000, 150
    for i, (n, im) in enumerate(icons.items()):
        put(im.resize((32, 32), Image.LANCZOS), ix + i * 46, iy)
        put(im.resize((20, 20), Image.LANCZOS), ix + i * 46 + 6, iy + 40)
    dr.text((ix, iy + 76), "数值图标：上 32 像素（卡片），下 20 像素（属性格）", font=fs(14), fill="#BFB5A2")
    path.parent.mkdir(parents=True, exist_ok=True)
    B.convert("RGB").save(path, optimize=True)


def main() -> int:
    t0 = time.perf_counter()
    icons = build_stat_icons()
    save_stat_icons(icons)
    review(OUT / "review@2x" / "lacquer_ui_review.png")
    print(f"[ui_lacquer] {len(icons)} 个数值图标 → {STATS_DIR}，审图 lacquer_ui_review.png（{time.perf_counter() - t0:.1f}s）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
