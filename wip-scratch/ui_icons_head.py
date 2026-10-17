#!/usr/bin/env python3
"""提灯夜行 · 桌面版界面图标（只用 Pillow + numpy）。

一套统一的图标：宣纸色圆底 + 水墨画的物件 + 一笔写成的墨圈（圆相，留一个小缺口、收笔飞白）
+ 墨圈内侧一道细的五行色弧。进化法器另加一道藤黄金圈、物件更繁复并带金饰；五行图标的圆底染一层本行的淡彩。
64×64（1 倍）/ 128×128（2 倍），正常混合，锚点居中，全彩不染色。要求缩到 32 像素仍能认出来，
所以物件以墨块、粗轮廓为主，细节只作点缀。

坐标都按 1 倍像素写（64×64 画布，圆心 (32, 32)），出图密度由 style.DENSITY 决定（见 vfx_textures.grid1/noise1）。
画法复用 weapon_textures.Painter（淡彩填色、手抖轮廓、干笔）。五行颜色取自 src/data/elements.ts，
兑上相近的国画颜料，在纸色上也看得清（EL_INK）。

输出：art/out/<ASSETS_DIR_NAME>/ui/  icon_*.png + meta.json
用法（在仓库根目录下）：
  art/.venv/bin/python art/post/ui_icons.py                          # 1 倍
  LANTERN_ART_DENSITY=2 art/.venv/bin/python art/post/ui_icons.py    # 2 倍
"""

from __future__ import annotations

import math
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import vfx_textures as V  # noqa: E402
import weapon_textures as W  # noqa: E402

S = V.S
D = V.D
UI_DIR = V.ASSETS / "ui"
SIZE = 64
SS = 4
C = 32.0

col, mixc, smoothstep = V.col, W.mixc, V.smoothstep
PAPER, PAPER_SH, WHITE = W.PAPER, W.PAPER_SH, W.WHITE
JIAO, NONG, ZHONG, DAN, QING = W.JIAO, W.NONG, W.ZHONG, W.DAN, W.QING
ZHUSHA, ZHESHI, HUAQING, SHILV, TENG = W.ZHUSHA, W.ZHESHI, W.HUAQING, W.SHILV, W.TENG
W_ZHUSHA, W_ZHESHI, W_HUAQING, W_SHILV, W_TENG = W.W_ZHUSHA, W.W_ZHESHI, W.W_HUAQING, W.W_SHILV, W.W_TENG
GOLD_DK, GOLD_HI, ZHUSHA_DK = W.GOLD_DK, W.GOLD_HI, W.ZHUSHA_DK
INK_LINE = mixc(JIAO, NONG, 0.15)

# 五行色（src/data/elements.ts）与兑了国画颜料的“墨里能用”的版本
EL_HEX = {"metal": "#E9D9A6", "wood": "#6FD6A0", "water": "#6FB8FF", "fire": "#FF8A3D", "earth": "#C9925A"}
EL_INK = {
    "metal": col(S.mix(S.mix(EL_HEX["metal"], S.ACCENT["tenghuang"], 0.5), S.ACCENT["zheshi"], 0.3)),
    "wood": col(S.mix(S.mix(EL_HEX["wood"], S.ACCENT["shilv"], 0.55), S.INK["zhong"], 0.12)),
    "water": col(S.mix(EL_HEX["water"], S.ACCENT["huaqing"], 0.5)),
    "fire": col(S.mix(EL_HEX["fire"], S.ACCENT["zhusha"], 0.45)),
    "earth": col(S.mix(EL_HEX["earth"], S.ACCENT["zheshi"], 0.55)),
}
EL_WASH = {k: mixc(v, PAPER, 0.62) for k, v in EL_INK.items()}

WEAPONS = {  # id: (名, 进化名, 五行)
    "lamp": ("灯火", "不夜城", "fire"),
    "sword": ("符剑", "万剑归宗", "metal"),
    "bell": ("霜铃", "寒山钟", "water"),
    "crane": ("纸鹤", "千鹤引", "wood"),
    "seal": ("山印", "镇岳", "earth"),
}
PASSIVES = {  # id: (名, 五行)，与 src/data/passives.ts 一致
    "changming": ("长明", "fire"),
    "luxin": ("炉心", "fire"),
    "jianyi": ("剑意", "metal"),
    "ruimu": ("锐目", "metal"),
    "jingxin": ("静心", "water"),
    "yinhun": ("引魂", "water"),
    "zhezhi": ("折纸", "wood"),
    "jixing": ("疾行", "wood"),
    "houde": ("厚德", "earth"),
    "panshi": ("磐石", "earth"),
}
ELEMENTS = {"metal": "金", "wood": "木", "water": "水", "fire": "火", "earth": "土"}

OL = 1.35  # 物件外轮廓线宽（1 倍像素）：缩到 32 像素约 0.7 像素，仍看得见
OL_IN = 0.8  # 内部的线


# ============================================================== 工具


class Fr:
    """局部坐标系：(u, v) → 画布。u 沿物件主轴，ang 为主轴相对 +X 的角度（度，y 向下为正）。"""

    def __init__(self, cx: float, cy: float, ang: float = 0.0, s: float = 1.0):
        self.cx, self.cy, self.s = cx, cy, s
        a = math.radians(ang)
        self.ca, self.sa = math.cos(a), math.sin(a)

    def __call__(self, pts) -> np.ndarray:
        p = np.asarray(pts, dtype=np.float64).reshape(-1, 2)
        x = self.cx + self.s * (p[:, 0] * self.ca - p[:, 1] * self.sa)
        y = self.cy + self.s * (p[:, 0] * self.sa + p[:, 1] * self.ca)
        return np.stack([x, y], -1)

    def pt(self, x, y):
        return tuple(self((x, y))[0])

    def uv(self, P: W.Painter):
        dx, dy = P.X - self.cx, P.Y - self.cy
        return (dx * self.ca + dy * self.sa) / self.s, (-dx * self.sa + dy * self.ca) / self.s


def shape(P: W.Painter, poly, rgb, *, ol=OL, ol_rgb=None, pool=0.25, pool_rgb=None, mottle=0.06, mottle_rgb=None, alpha=1.0, wob=0.06, dry=0.0):
    """填色 + 墨线轮廓，返回 (d, 覆盖度)。"""
    if wob:
        poly = W.wobble(poly, P.rng, wob, spacing=0.3)
    d, t = P.sdf(poly)
    P.fill(d, rgb, alpha, pool=pool, pool_rgb=ZHONG if pool_rgb is None else pool_rgb, pool_w=0.8, mottle=mottle, mottle_rgb=ZHONG if mottle_rgb is None else mottle_rgb)
    if ol:
        P.outline(d, t, ol, INK_LINE if ol_rgb is None else ol_rgb, jitter=0.22, dry=dry)
    return d, P.cover(d)


def stroke(P: W.Painter, pts, hw, rgb=INK_LINE, alpha=1.0, **kw):
    pts = np.asarray(pts, dtype=np.float64)
    return P.line(pts, hw, rgb, alpha, **kw)


def glow(P: W.Painter, cx, cy, r, rgb, alpha):
    """柔和的淡彩晕（灯光、魂火背后的光），正常混合。"""
    rr = np.hypot(P.X - cx, P.Y - cy) / r
    P.lay.over(rgb, alpha * np.exp(-(rr**2) * 2.2) * smoothstep(1.4, 0.8, rr))


def shade_lr(P: W.Painter, x0, x1, light, dark, gamma=1.0):
    """从左（亮）到右（暗）的过渡色。"""
    return mixc(light, dark, smoothstep(x0, x1, P.X) ** gamma)


# ============================================================== 框：纸底、墨圈、五行弧、金圈


def frame_back(P: W.Painter, el: str, *, evo=False, element=False):
    r = np.hypot(P.X - C, P.Y - C)
    th = np.mod(np.arctan2(P.Y - C, P.X - C) / (2 * math.pi), 1.0)
    rr = 27.4 * (1 + 0.006 * W.sample1(W.pnoise1(P.rng, 256, 10.0), th))
    disc = smoothstep(rr + 2 * P.aa, rr - 2 * P.aa, r)
    n = V.noise1(P.rng, P.X.shape, 3.0 * P.ss)
    base = PAPER
    if element:
        base = mixc(PAPER, EL_WASH[el], 0.55)
    elif evo:
        base = mixc(PAPER, W_TENG, 0.16)
    rgb = mixc(base, mixc(base, PAPER_SH, 0.8), np.clip(0.3 + 0.25 * n, 0, 1))
    # 中心略亮，边上一圈淡淡的积色，像一张小小的册页
    rgb = mixc(rgb, mixc(rgb, WHITE, 0.35), np.exp(-((r / 16.0) ** 2)) * 0.5)
    P.lay.over(rgb, disc)


def frame_front(P: W.Painter, el: str, *, evo=False, element=False):
    r = np.hypot(P.X - C, P.Y - C)
    th = np.mod(np.arctan2(P.Y - C, P.X - C), 2 * math.pi)
    # 五行色弧：墨圈内侧，从右下经下、左到左上，两头收细
    a0, span = math.radians(25.0), math.radians(235.0)
    ta = np.mod(th - a0, 2 * math.pi) / span
    hwa = (1.05 if element else 0.8) * np.sin(np.pi * np.clip(ta, 0, 1)) ** 0.6 * (ta <= 1)
    arc = smoothstep(hwa + P.aa, hwa - P.aa, np.abs(r - 24.3)) * (hwa > 0.05)
    P.lay.over(EL_INK[el], 0.95 * arc)
    # 墨圈：一笔圆相，起笔在右上，顺时针，收笔飞白，留一个小缺口
    th0, span2 = math.radians(-38.0), math.radians(336.0)
    rel = np.mod(th - th0 + math.radians(8.0), 2 * math.pi) - math.radians(8.0)
    t = rel / span2
    tc = np.clip(t, 0, 1)
    R = 28.0 - 0.5 + 0.9 * tc
    hw = np.interp(tc, [0.0, 0.05, 0.5, 0.9, 1.0], [2.0, 2.15, 1.85, 1.45, 0.4]) * (1.12 if evo else 1.0)
    over = np.where(t < 0, -t * span2 * 28.0, 0.0)
    over = np.where(t > 1.0, 1e3, over)
    dist = np.hypot(r - R, over)
    cov = smoothstep(hw + P.aa, hw - P.aa, dist)
    tex = W.ptex(P.rng, ns=16, nt=512, along=8.0, across=0.6)
    b = W.sample_ptex(tex, np.clip((r - R) / np.maximum(hw, 0.3), -1, 1), tc * 0.999)
    dry = 0.5 * smoothstep(0.8, 1.0, tc) + 0.06
    cov = cov * smoothstep(dry - 0.07, dry + 0.07, b)
    P.lay.over(mixc(JIAO, NONG, 0.35 * (1 - b) * tc), cov)
    if evo:
        # 金圈：墨圈外一道细金线，四角各一粒金点
        gc = smoothstep(0.55 + P.aa, 0.55 - P.aa, np.abs(r - 30.05))
        P.lay.over(mixc(TENG, GOLD_DK, 0.15), gc)
        for k in range(4):
            a = math.radians(45 + 90 * k)
            P.dot(C + 30.05 * math.cos(a), C + 30.05 * math.sin(a), 0.85, TENG)


# ============================================================== 常用物件


def paint_lantern(P: W.Painter, cx, cy, s, *, gold=False):
    """红灯笼：朱砂身、中间透出暖光、竹骨三道，上下墨盖，下垂朱砂穗。"""
    glow(P, cx, cy, 14 * s, mixc(TENG, PAPER, 0.35), 0.55)
    cap_rgb, cap_ol = (TENG, GOLD_DK) if gold else (NONG, INK_LINE)
    stroke(P, W.seg_pts((cx, cy - 12.0 * s), (cx, cy - 16.5 * s), n=12), 0.45 * s + 0.1, INK_LINE)
    th = np.linspace(0, 2 * math.pi, 64, endpoint=False)
    rx, ry = 9.3 * s, 10.6 * s
    body = np.stack([cx + rx * np.sign(np.cos(th)) * np.abs(np.cos(th)) ** 0.8, cy + ry * np.sign(np.sin(th)) * np.abs(np.sin(th)) ** 0.9], -1)
    rn = np.hypot((P.X - cx) / rx, (P.Y - cy) / ry)
    rgb = mixc(ZHUSHA, mixc(TENG, WHITE, 0.25), np.exp(-((rn / 0.55) ** 2)) * 0.75)
    d, m = shape(P, body, rgb, ol=OL * min(1.0, 0.55 + 0.45 * s), pool=0.35, pool_rgb=ZHUSHA_DK)
    for k in (-0.55, 0.0, 0.55):
        yy = np.linspace(-0.92, 0.92, 30)
        pts = np.stack([cx + k * rx * np.sqrt(1 - yy**2), cy + ry * yy], -1)
        stroke(P, pts, 0.38 * s, ZHUSHA_DK, 0.75, clip=m)
    for y0, half, hh in ((-ry - 0.2 * s, 5.2 * s, 2.4 * s), (ry - 0.8 * s, 4.2 * s, 2.0 * s)):
        cap = [(cx - half, cy + y0 - (hh if y0 < 0 else 0)), (cx + half, cy + y0 - (hh if y0 < 0 else 0)),
               (cx + half, cy + y0 + (0 if y0 < 0 else hh)), (cx - half, cy + y0 + (0 if y0 < 0 else hh))]
        shape(P, cap, cap_rgb, ol=0.75 * s + 0.2, ol_rgb=cap_ol, pool=0.3, pool_rgb=GOLD_DK if gold else JIAO, wob=0.04)
    y_t = cy + ry + 1.2 * s
    P.dot(cx, y_t + 0.6 * s, 0.9 * s, TENG if gold else ZHUSHA_DK)
    for dx_ in (-1.0, 0.0, 1.0):
        pts = V.bezier([(cx + dx_ * 0.3 * s, y_t + 1.0 * s), (cx + dx_ * 0.9 * s, y_t + 3.5 * s), (cx + dx_ * 1.4 * s, y_t + 6.0 * s)], 24)
        stroke(P, pts, 0.55 * s * W.brush_profile(24, 1.0, 0.25, 0.0), ZHUSHA, dry=0.3, dry_start=0.5)


def paint_sword(P: W.Painter, fr: Fr, *, evo=False, tassel=True):
    """剑：局部坐标 u 沿剑身（剑尖在 +u），v 横跨。"""
    s = fr.s
    U, Vv = fr.uv(P)
    if tassel:
        root = fr.pt(-16.6, 0.4)
        for tip in ((-21.0, 3.6), (-20.0, 5.8), (-21.8, 1.4)):
            pts = V.bezier([root, fr.pt((-16.6 + tip[0]) / 2, (0.4 + tip[1]) / 2 + 0.6), fr.pt(*tip)], 30)
            stroke(P, pts, 0.85 * s * W.brush_profile(30, 1.0, 0.25, 0.0), ZHUSHA, dry=0.3, dry_start=0.5)
        P.dot(*root, 1.0 * s, ZHUSHA_DK)
    grip = fr([(-15.4, -1.8), (-6.4, -1.8), (-6.4, 1.8), (-15.4, 1.8)])
    stripes = 0.5 + 0.5 * np.sin(2 * math.pi * (U - Vv * 0.9) / 1.7)
    shape(P, grip, mixc(NONG, mixc(ZHONG, DAN, 0.3), 0.7 * smoothstep(0.45, 0.85, stripes)), ol=0.85 * s, wob=0.03)
    pom = fr(np.stack([-16.0 + 2.1 * np.cos(np.linspace(0, 2 * math.pi, 32, endpoint=False)), 2.1 * np.sin(np.linspace(0, 2 * math.pi, 32, endpoint=False))], -1))
    shape(P, pom, mixc(TENG, GOLD_HI, 0.3), ol=0.8 * s, ol_rgb=mixc(GOLD_DK, JIAO, 0.4), pool=0.5, pool_rgb=GOLD_DK, wob=0.02)
    xs = np.linspace(-6.4, 21.5, 50)
    hw = np.where(xs < 15.0, 2.9 - 0.5 * (xs + 6.4) / 21.4, 2.4 * np.clip(1 - (xs - 15.0) / 6.5, 0, 1) ** 0.7)
    blade = fr([(x, -h) for x, h in zip(xs, hw)] + [(x, h) for x, h in zip(xs[::-1], hw[::-1])][1:-1])
    if evo:
        hi, lo, ol_rgb = mixc(PAPER, WHITE, 0.9), mixc(W_TENG, WHITE, 0.55), mixc(GOLD_DK, JIAO, 0.35)
    else:
        hi, lo, ol_rgb = mixc(PAPER, WHITE, 0.65), mixc(QING, PAPER, 0.35), INK_LINE
    d, t = P.sdf(blade)
    P.fill(d, mixc(hi, lo, smoothstep(-0.3, 0.5, Vv)))
    m = P.cover(d)
    stroke(P, fr(W.seg_pts((-4.5, 0.0), (15.5, 0.0), n=30)), 0.28 * s, DAN if not evo else mixc(TENG, ZHESHI, 0.4), 0.8, clip=m)
    stroke(P, fr(W.seg_pts((-2.0, -1.3), (12.5, -1.0), n=30)), 0.35 * s, WHITE, 0.9, clip=m)
    if evo:
        P.outline(d, t, 0.9 * s, TENG, center=-0.85 * s, jitter=0.12)
    P.outline(d, t, OL * s, ol_rgb, jitter=0.18)
    gp = fr([(-7.5, -6.6), (-5.6, -5.9), (-3.8, -0.7), (-3.8, 0.7), (-5.6, 5.9), (-7.5, 6.6), (-6.3, 0.0)])
    guard = W.catmull_closed(gp, 8)
    d, t = P.sdf(guard)
    P.fill(d, mixc(TENG, GOLD_HI, smoothstep(2.0, -4.0, Vv)), pool=0.5, pool_rgb=GOLD_DK, pool_w=0.6)
    P.outline(d, t, 0.95 * s, mixc(GOLD_DK, JIAO, 0.45))
    band = fr([(-3.2, -3.5), (-0.4, -3.4), (-0.6, 3.5), (-3.4, 3.4)])
    d, m2 = shape(P, band, mixc(W_TENG, TENG, 0.35), ol=0.6 * s, ol_rgb=mixc(ZHESHI, JIAO, 0.5), pool=0.2, pool_rgb=ZHESHI, wob=0.03)
    stroke(P, fr(W.seg_pts((-1.8, -2.3), (-2.0, 2.3), n=12)), 0.38 * s, ZHUSHA, clip=m2)


def bell_poly(cx, top, mouth, half_top, half_mouth, lift):
    """铃身：圆肩、下摆外撇，铃口向上弯成弧。"""
    ys = np.linspace(top, mouth, 32)
    yn = (ys - top) / (mouth - top)
    hw = half_top + (half_mouth - half_top) * (0.55 * np.sqrt(yn) + 0.45 * yn**2.4)
    left = [(cx - a, y) for a, y in zip(hw, ys)]
    xs = np.linspace(-hw[-1], hw[-1], 30)[1:-1]
    mouth_pts = [(cx + x, mouth - lift * (1 - (x / hw[-1]) ** 2)) for x in xs]
    right = [(cx + a, y) for a, y in zip(hw[::-1], ys[::-1])]
    crown = [(cx + half_top * math.cos(a), top - 0.5 * half_top * math.sin(a)) for a in np.linspace(0, math.pi, 14)[1:-1]]
    return np.array(left + mouth_pts + right + crown), hw[-1]


def paint_bell(P: W.Painter, cx, cy, s, *, metal, loop=True, frost=False):
    """小铃：铃钮、铃身（左亮右暗）、一道箍、三粒乳钉、口沿，铃舌露在铃口下。"""
    top, mouth = cy - 7.5 * s, cy + 8.0 * s
    if loop:
        lp = W.ellipse_pts(cx, top - 6.0 * s, 1.9 * s, 2.1 * s, 48)
        stroke(P, V.arc_resample(np.vstack([lp, lp[:1]]), 80), 0.55 * s, ZHUSHA)
    P.dot(cx + 0.2 * s, mouth + 1.0 * s, 1.5 * s, mixc(GOLD_DK, JIAO, 0.45), ry=1.8 * s)
    d, t = P.sdf(W.ellipse_pts(cx, top - 1.6 * s, 2.0 * s, 1.8 * s, 32))
    P.fill(d, metal, pool=0.4, pool_rgb=GOLD_DK, pool_w=0.5)
    P.dot(cx, top - 1.6 * s, 0.75 * s, NONG)
    P.outline(d, t, 0.75 * s, INK_LINE)
    poly, hm = bell_poly(cx, top, mouth, 4.4 * s, 10.0 * s, 2.4 * s)
    rgb = shade_lr(P, cx - 7 * s, cx + 9 * s, mixc(metal, WHITE if frost else GOLD_HI, 0.35), mixc(metal, ZHONG, 0.5))
    d, m = shape(P, poly, rgb, ol=OL * min(1.0, 0.6 + 0.4 * s), pool=0.35, pool_rgb=GOLD_DK if not frost else mixc(HUAQING, JIAO, 0.4))
    stroke(P, V.bezier([(cx - 2.6 * s, top + 1.8 * s), (cx - 4.2 * s, cy), (cx - 7.2 * s, mouth - 1.8 * s)], 30), 0.7 * s * W.brush_profile(30, 0.5, 0.3), WHITE if frost else GOLD_HI, 0.75, clip=m)
    yb = cy - 2.5 * s
    hwb = 4.4 * s + (hm - 4.4 * s) * (0.55 * math.sqrt((yb - top) / (mouth - top)) + 0.45 * ((yb - top) / (mouth - top)) ** 2.4)
    stroke(P, np.array([(cx + hwb * math.cos(a), yb + 1.2 * s * math.sin(a)) for a in np.linspace(math.pi, 0, 30)]), 0.42 * s, GOLD_DK if not frost else mixc(HUAQING, JIAO, 0.3), clip=m)
    lip = np.array([(cx + x * 0.97, mouth - 1.6 * s - 2.4 * s * (1 - (x / hm) ** 2)) for x in np.linspace(-hm, hm, 40)])
    stroke(P, lip, 0.4 * s, GOLD_DK if not frost else mixc(HUAQING, JIAO, 0.3), 0.85, clip=m)
    for xo in (-3.6, 0.0, 3.6):
        yy = cy + 1.6 * s + 0.15 * abs(xo) * s
        P.dot(cx + xo * s, yy, 0.8 * s, GOLD_DK if not frost else mixc(HUAQING, JIAO, 0.3), clip=m)
        P.dot(cx + (xo - 0.25) * s, yy - 0.25 * s, 0.35 * s, WHITE if frost else GOLD_HI, clip=m)
    if frost:
        for (fx, fy) in ((-5.0, 4.5), (5.5, 2.0), (2.5, -4.0), (-1.5, 6.5)):
            P.dot(cx + fx * s, cy + fy * s, 0.45 * s, WHITE, 0.9, clip=m)


def ripples(P: W.Painter, cx, cy, radii, spans, rgb, hw0=0.7, squash=1.0):
    """左右两侧的声波/涟漪弧。"""
    for k, r0 in enumerate(radii):
        for side in (0.0, math.pi):
            a = np.linspace(side - spans[k], side + spans[k], 40)
            pts = np.stack([cx + r0 * np.cos(a), cy + squash * r0 * np.sin(a)], -1)
            stroke(P, pts, (hw0 - 0.12 * k) * W.brush_profile(40, 0.3, 0.3, 0.3), rgb, 0.95)


# 纸鹤的设计坐标（与 weapon_textures.make_crane 第 0 帧相同，30×26 画布）
CRANE_BODY = [(8.4, 15.0), (15.0, 12.6), (21.8, 14.4), (15.6, 18.8)]
CRANE_NECK = [(18.0, 13.5), (22.4, 15.2), (26.1, 7.5), (24.9, 6.5)]
CRANE_HEAD = [(24.5, 6.1), (26.5, 7.0), (28.5, 10.4)]
CRANE_TAIL = [(8.4, 13.4), (13.0, 16.6), (4.2, 11.8), (1.7, 8.0)]


def paint_crane(P: W.Painter, fr: Fr, *, evo=False, ink=False, ol=1.1):
    """纸鹤（翅膀上扬）。ink=True 画成淡墨剪影（远处的鹤群）。"""
    def L(pts):
        return fr(np.asarray(pts, dtype=np.float64) - [15.0, 13.0])

    hf, hb = np.array([18.6, 13.4]), np.array([10.6, 13.9])
    far_poly, far_tip, far_root = W.crane_wing(hf + [1.0, -1.5], hb + [1.0, -1.5], 60.0, -1, 0.0)
    near_poly, near_tip, near_root = W.crane_wing(hf, hb, 60.0, +1, 0.0)
    if ink:
        tone = mixc(DAN, ZHONG, 0.3)
        for poly in (far_poly, CRANE_TAIL, CRANE_NECK, CRANE_HEAD, CRANE_BODY, near_poly):
            shape(P, L(poly), tone, ol=0, pool=0.3, pool_rgb=NONG, mottle=0.0, wob=0.0)
        P.dot(*L([(25.2, 7.3)])[0], 0.6 * fr.s, ZHUSHA)
        return
    lit, mid, dark, body_c = mixc(PAPER, WHITE, 0.7), mixc(PAPER, WHITE, 0.3), mixc(PAPER_SH, QING, 0.3), mixc(PAPER, PAPER_SH, 0.3)
    crease = 0.3 * fr.s

    def facet(poly, rgb, gold=False, w=ol):
        d, t = P.sdf(W.wobble(L(poly), P.rng, 0.05, spacing=0.3))
        P.fill(d, rgb, pool=0.2, pool_rgb=QING, pool_w=0.8)
        if gold:
            P.outline(d, t, 0.9, TENG, center=-0.75, jitter=0.15)
        P.outline(d, t, w, INK_LINE, jitter=0.2)

    facet(far_poly, dark, evo)
    stroke(P, L(W.seg_pts(far_root, far_tip, n=20)), crease, DAN, 0.6)
    facet(CRANE_TAIL, mid, w=ol * 0.85)
    facet(CRANE_NECK, mid, w=ol * 0.85)
    facet(CRANE_HEAD, lit, w=ol * 0.8)
    facet(CRANE_BODY, body_c)
    stroke(P, L(W.seg_pts((9.4, 15.0), (15.2, 15.6), (21.0, 14.4), n=30)), crease, DAN, 0.6)
    facet(near_poly, mixc(lit, mid, 0.4), evo)
    stroke(P, L(W.seg_pts(near_root, near_tip, n=20)), crease, DAN, 0.7)
    P.dot(*L([(25.2, 7.3)])[0], 0.75 * fr.s, ZHUSHA)


def paint_seal_glyph(P: W.Painter, fr: Fr, half: float, rgb=ZHUSHA, worn=True):
    """朱砂方印（白文“山”），局部坐标以印面中心为原点。"""
    U, Vv = fr.uv(P)
    sq = (np.abs(U) ** 10 + np.abs(Vv) ** 10) ** 0.1 - half
    if worn:
        sq = sq + 0.35 * V.noise1(P.rng, P.X.shape, 2.0 * P.ss)
    cover = smoothstep(P.aa * 2, -P.aa * 2, sq)
    gd = np.full(P.X.shape, 1e3)
    for st in W.SHAN_GLYPH:
        pts = V.arc_resample(np.array([(half * 1.0 * x, half * 1.0 * y) for x, y in st]), 80)
        gd = np.minimum(gd, W.polyline_dist(U, Vv, pts))
    gw = half * 0.13
    glyph = smoothstep(gw - P.aa * 2, gw + P.aa * 2, gd)
    dens = 1.0
    if worn:
        sp = V.rank01(V.noise1(P.rng, P.X.shape, 0.5 * P.ss))
        dens = 1.0 - 0.6 * smoothstep(0.93, 0.985, sp)
    P.lay.over(mixc(rgb, mixc(rgb, JIAO, 0.25), np.exp(np.minimum(sq, 0) / 1.2) * 0.6), cover * glyph * dens)


def paint_box(P: W.Painter, x0, y0, w, h, dx, dy, base, *, ol=OL, top_gold=False):
    front, top, side, sil = W.box_faces(x0, y0, w, h, dx, dy)
    masks = []
    for poly, rgb in zip((top, front, side), (mixc(base, PAPER, 0.5), base, mixc(base, ZHONG, 0.5))):
        d, _ = P.sdf(W.wobble(poly, P.rng, 0.06, spacing=0.3))
        P.fill(d, rgb, mottle=0.1, mottle_rgb=ZHONG, pool=0.25, pool_rgb=ZHONG, pool_w=0.8)
        masks.append(P.cover(d))
    stroke(P, W.seg_pts((x0, y0), (x0 + w, y0), (x0 + w + dx, y0 - dy), n=50), 0.5 if not top_gold else 0.6, NONG if not top_gold else TENG)
    stroke(P, W.seg_pts((x0 + w, y0), (x0 + w, y0 + h), n=30), 0.45, NONG)
    d, t = P.sdf(W.wobble(sil, P.rng, 0.05, spacing=0.3))
    P.outline(d, t, ol, INK_LINE, jitter=0.25)
    return masks


def paint_mountain(P: W.Painter, fr: Fr, *, jinbi=False, ol=OL):
    """三峰的山。jinbi=True：石绿花青敷色、峰脊勾金（金碧山水）；否则水墨，山脚带一点赭。"""
    peaks = [(-15.0, 9.0), (-12.5, 2.5), (-8.5, -5.5), (-6.0, -3.5), (-3.0, -11.5), (0.0, -17.0), (3.0, -11.0), (5.0, -7.0),
             (8.0, -9.5), (11.5, -3.0), (14.0, 2.5), (15.5, 9.0)]
    poly = W.catmull_closed(fr(peaks + [(0.0, 9.6)]), 8)
    U, Vv = fr.uv(P)
    h = np.clip((9.0 - Vv) / 26.0, 0, 1)
    if jinbi:
        top_c = mixc(mixc(SHILV, HUAQING, 0.5), ZHONG, 0.15)
        base_c = mixc(W_SHILV, PAPER, 0.2)
    else:
        top_c = mixc(ZHONG, NONG, 0.4)
        base_c = mixc(mixc(DAN, W_ZHESHI, 0.5), PAPER, 0.25)
    rgb = mixc(base_c, top_c, smoothstep(0.1, 0.85, h))
    rgb = mixc(rgb, mixc(rgb, JIAO, 0.25), smoothstep(-2.0, 12.0, U) * 0.6)
    d, m = shape(P, poly, rgb, ol=0, pool=0.3, pool_rgb=JIAO if not jinbi else mixc(HUAQING, JIAO, 0.4), mottle=0.1)
    for (sx, sy), (ex, ey) in (((-1.0, -14.0), (-6.5, -2.0)), ((1.5, -12.0), (3.5, 0.0)), ((9.0, -6.0), (12.0, 3.0)), ((-8.0, -2.0), (-11.0, 5.0))):
        pts = V.bezier([fr.pt(sx, sy), fr.pt((sx + ex) / 2 + 0.8, (sy + ey) / 2), fr.pt(ex, ey)], 30)
        stroke(P, pts, 0.55 * fr.s * W.brush_profile(30, 1.0, 0.2), mixc(NONG, HUAQING, 0.3) if jinbi else JIAO, 0.6, clip=m, dry=0.45, dry_start=0.25)
    if jinbi:
        for ridge in (((-3.0, -11.5), (0.0, -17.0), (3.0, -11.0)), ((-8.5, -5.5), (-6.0, -3.5), (-4.0, -9.0)), ((8.0, -9.5), (11.5, -3.0), (13.0, 0.0))):
            stroke(P, V.bezier([fr.pt(x, y + 1.0) for x, y in ridge], 30), 0.6 * fr.s * W.brush_profile(30, 0.6, 0.3), TENG, clip=m)
    mist = V.bezier([fr.pt(-13.0, 4.5), fr.pt(-4.0, 2.0), fr.pt(4.0, 5.0), fr.pt(13.0, 3.0)], 40)
    stroke(P, mist, 1.1 * fr.s * W.brush_profile(40, 0.4, 0.2), mixc(PAPER, WHITE, 0.4), 0.7, clip=m, dry=0.4, dry_start=0.2)
    t = None
    d2, t = P.sdf(W.wobble(poly, P.rng, 0.05, spacing=0.3))
    P.outline(d2, t, ol, INK_LINE, jitter=0.3, dry=0.12)
    return m


# ============================================================== 法器


def em_lamp(P, evo):
    if not evo:
        paint_lantern(P, 32.0, 31.5, 1.0)
        return
    # 不夜城：一道墨色屋檐（城楼），三盏金顶灯笼悬在上面，四周几点金星
    for (x, y) in ((17.5, 19.0), (47.0, 18.5), (24.0, 13.0), (41.5, 12.5)):
        P.dot(x, y, 0.7, TENG)
    eave = [(12.5, 44.5), (17.0, 41.6), (24.0, 40.6), (32.0, 40.3), (40.0, 40.6), (47.0, 41.6), (51.5, 44.5), (47.0, 45.2), (40.0, 46.4), (32.0, 46.8), (24.0, 46.4), (17.0, 45.2)]
    shape(P, W.catmull_closed(eave, 6), mixc(NONG, JIAO, 0.4), ol=0.8, pool=0.0)
    stroke(P, V.bezier([(13.5, 44.0), (32.0, 39.2), (50.5, 44.0)], 40), 0.55, TENG)
    wall = [(17.5, 46.0), (46.5, 46.0), (45.5, 51.0), (18.5, 51.0)]
    shape(P, wall, mixc(ZHONG, DAN, 0.3), ol=0.8)
    for x in (24.0, 32.0, 40.0):
        P.dot(x, 48.6, 0.9, mixc(TENG, ZHUSHA, 0.3), ry=1.3)
    paint_lantern(P, 21.0, 31.0, 0.5, gold=True)
    paint_lantern(P, 43.0, 31.0, 0.5, gold=True)
    paint_lantern(P, 32.0, 25.5, 0.72, gold=True)


def em_sword(P, evo):
    if not evo:
        paint_sword(P, Fr(31.0, 33.0, -45.0, 1.0))
        return
    # 万剑归宗：三把剑剑尖汇向右上一点，金光放射
    T = np.array([45.5, 18.5])
    for k in range(10):
        a = 2 * math.pi * k / 10 + 0.2
        r0, r1 = 2.2, 5.2 + 1.5 * (k % 2)
        stroke(P, W.seg_pts(T + r0 * np.array([math.cos(a), math.sin(a)]), T + r1 * np.array([math.cos(a), math.sin(a)]), n=10), 0.42, TENG, 0.9)
    glow(P, T[0], T[1], 6.0, mixc(TENG, WHITE, 0.5), 0.6)
    for ang, sc, tip in ((-79.0, 0.56, T + [-2.2, -0.6]), (-11.0, 0.56, T + [0.6, 2.2])):
        a = math.radians(ang)
        o = tip - 21.5 * sc * np.array([math.cos(a), math.sin(a)])
        paint_sword(P, Fr(o[0], o[1], ang, sc), evo=True, tassel=False)
    a = math.radians(-45.0)
    o = T - 21.5 * 0.95 * np.array([math.cos(a), math.sin(a)])
    paint_sword(P, Fr(o[0], o[1], -45.0, 0.95), evo=True)


def em_bell(P, evo):
    if not evo:
        metal = mixc(mixc(TENG, ZHESHI, 0.45), HUAQING, 0.4)
        ripples(P, 32.0, 35.0, (14.0, 17.8), (0.55, 0.42), EL_INK["water"], 0.85)
        paint_bell(P, 32.0, 34.5, 1.15, metal=metal, frost=True)
        return
    # 寒山钟：远处一抹雪山，前面一口大钟，金色的箍和撞座
    hills = [(10.5, 40.0), (16.0, 33.0), (21.0, 28.0), (25.0, 31.0), (31.0, 24.5), (38.0, 31.5), (43.0, 27.0), (48.5, 33.0), (53.5, 40.0)]
    d, m = shape(P, W.catmull_closed(hills + [(32.0, 41.0)], 6), mixc(W_HUAQING, PAPER, 0.25), ol=0, pool=0.3, pool_rgb=HUAQING, mottle=0.08)
    for x0, y0 in ((21.0, 28.0), (31.0, 24.5), (43.0, 27.0)):
        stroke(P, V.bezier([(x0 - 2.5, y0 + 2.5), (x0, y0 + 0.6), (x0 + 2.5, y0 + 2.8)], 20), 0.7, WHITE, 0.9, clip=m)
    ripples(P, 32.0, 38.0, (16.5, 19.5), (0.42, 0.32), mixc(TENG, GOLD_DK, 0.2), 0.75)
    cx = 32.0
    loop = V.bezier([(cx - 3.0, 18.5), (cx - 3.4, 13.0), (cx + 3.4, 13.0), (cx + 3.0, 18.5)], 40)
    stroke(P, loop, 1.1, INK_LINE)
    body = [(cx - 7.5, 18.0), (cx + 7.5, 18.0), (cx + 9.0, 21.0), (cx + 9.6, 36.0), (cx + 11.0, 44.5), (cx - 11.0, 44.5), (cx - 9.6, 36.0), (cx - 9.0, 21.0)]
    poly = W.catmull_closed(body, 6)
    metal = mixc(NONG, HUAQING, 0.25)
    rgb = shade_lr(P, cx - 10, cx + 11, mixc(metal, W_HUAQING, 0.45), mixc(metal, JIAO, 0.3))
    d, m = shape(P, poly, rgb, ol=OL, pool=0.3, pool_rgb=JIAO)
    for y in (24.0, 37.5, 42.0):
        stroke(P, W.seg_pts((cx - 12.0, y), (cx + 12.0, y), n=30), 0.5, TENG, clip=m)
    for x in (cx - 3.6, cx + 3.6):
        stroke(P, W.seg_pts((x, 24.0), (x, 37.5), n=20), 0.4, mixc(TENG, GOLD_DK, 0.3), clip=m)
    P.dot(cx - 7.0, 30.5, 2.0, TENG, clip=m)
    P.dot(cx - 7.0, 30.5, 1.0, GOLD_DK, clip=m)
    stroke(P, V.bezier([(cx - 6.0, 20.5), (cx - 7.0, 30.0), (cx - 8.5, 42.0)], 30), 0.6 * W.brush_profile(30, 0.5, 0.3), mixc(W_HUAQING, WHITE, 0.4), 0.6, clip=m)


def em_crane(P, evo):
    if not evo:
        paint_crane(P, Fr(32.5, 33.5, 0.0, 1.45))
        return
    paint_crane(P, Fr(19.0, 19.0, -8.0, 0.55), ink=True)
    paint_crane(P, Fr(15.5, 35.0, 4.0, 0.42), ink=True)
    paint_crane(P, Fr(35.5, 34.5, -4.0, 1.25), evo=True)
    for (x, y) in ((44.0, 18.0), (49.0, 24.0), (25.0, 46.0)):
        P.dot(x, y, 0.65, TENG)


def em_seal(P, evo):
    if not evo:
        paint_seal_glyph(P, Fr(26.5, 37.5, -8.0, 1.0), 9.8)
        x0, w, h, dx, dy = 30.5, 12.0, 12.5, 5.5, 4.0
        y0 = 21.5
        stone = mixc(W_ZHESHI, DAN, 0.3)
        paint_box(P, x0, y0, w, h, dx, dy, stone, ol=1.2)
        tx, ty = x0 + w / 2 + dx / 2, y0 - dy / 2 + 0.3
        shell = W.catmull_closed([(tx - 4.6, ty + 0.8), (tx - 4.0, ty - 2.2), (tx - 1.2, ty - 4.0), (tx + 1.8, ty - 4.0), (tx + 4.4, ty - 2.2), (tx + 4.9, ty + 0.6), (tx, ty + 1.6)], 8)
        P.dot(tx - 5.2, ty - 0.6, 1.3, mixc(stone, PAPER, 0.3))
        d, m = shape(P, shell, shade_lr(P, tx - 4, tx + 5, mixc(stone, PAPER, 0.5), mixc(stone, ZHONG, 0.3)), ol=0.85, pool=0.3)
        hexa = W.ellipse_pts(tx + 0.2, ty - 1.9, 1.7, 1.0, 6)
        stroke(P, V.arc_resample(np.vstack([hexa, hexa[:1]]), 40), 0.25, NONG, 0.8, clip=m)
        stroke(P, V.bezier([(tx + 3.6, ty - 0.6), (tx + 6.6, ty + 0.6), (tx + 7.2, ty + 6.0)], 30), 0.5, ZHUSHA)
        return
    # 镇岳：金碧三峰坐在印台上，印台金边、正面金篆“山”
    x0, w, h, dx, dy = 17.5, 22.0, 11.0, 7.5, 5.0
    y0 = 35.5
    stone = mixc(W_ZHESHI, ZHONG, 0.4)
    masks = paint_box(P, x0, y0, w, h, dx, dy, stone, ol=1.3, top_gold=True)
    gx, gy, gs = x0 + w / 2, y0 + h / 2 + 0.3, 4.0
    for st in W.SHAN_GLYPH:
        pts = V.arc_resample(np.array([(gx + gs * x, gy + gs * y) for x, y in st]), 40)
        stroke(P, pts, 0.75, TENG, clip=masks[1], jitter=0.05)
    paint_mountain(P, Fr(x0 + w / 2 + dx / 2, y0 - dy / 2 - 8.5, 0.0, 0.9), jinbi=True, ol=1.15)


# ============================================================== 心法


def em_changming(P, evo):
    """长明：一支红烛，烛泪下垂，火苗藤黄芯，背后暖光。"""
    glow(P, 32.0, 17.5, 11.0, mixc(TENG, PAPER, 0.3), 0.6)
    dish = W.ellipse_pts(32.0, 46.5, 10.5, 2.9, 48)
    shape(P, dish, shade_lr(P, 22, 43, mixc(ZHESHI, NONG, 0.3), mixc(ZHESHI, JIAO, 0.6)), ol=1.0, pool=0.3)
    body = [(26.0, 46.0), (26.0, 25.6), (27.5, 24.6), (32.0, 24.0), (36.5, 24.6), (38.0, 25.6), (38.0, 46.0)]
    rgb = shade_lr(P, 25, 39, mixc(ZHUSHA, W_ZHUSHA, 0.55), mixc(ZHUSHA, ZHUSHA_DK, 0.7))
    d, m = shape(P, body, rgb, ol=OL, pool=0.3, pool_rgb=ZHUSHA_DK, wob=0.05)
    for (x, L) in ((28.5, 7.0), (35.6, 4.5)):
        drip = V.bezier([(x, 25.0), (x - 0.2, 25.0 + L * 0.6), (x + 0.1, 25.0 + L)], 20)
        stroke(P, drip, np.linspace(1.0, 0.75, 20), mixc(W_ZHUSHA, PAPER, 0.4), 0.95, clip=m)
        P.dot(x + 0.1, 25.0 + L, 0.85, mixc(W_ZHUSHA, PAPER, 0.4), clip=m)
    stroke(P, V.bezier([(26.5, 25.6), (32.0, 27.2), (37.5, 25.6)], 30), 0.5, ZHUSHA_DK, 0.8, clip=m)
    stroke(P, W.seg_pts((32.0, 24.6), (32.2, 21.0), n=10), 0.5, JIAO)
    flame = W.catmull_closed([(32.2, 21.6), (35.2, 19.5), (35.6, 15.8), (33.8, 11.5), (32.6, 7.6), (31.0, 11.8), (28.7, 15.8), (29.0, 19.5)], 8)
    rr = np.hypot((P.X - 32.2) / 3.2, (P.Y - 17.2) / 5.2)
    frgb = mixc(mixc(ZHUSHA, TENG, 0.4), mixc(TENG, WHITE, 0.7), smoothstep(1.0, 0.25, rr))
    shape(P, flame, frgb, ol=0.7, ol_rgb=ZHUSHA_DK, pool=0.3, pool_rgb=ZHUSHA, mottle=0.0, wob=0.03)


def em_luxin(P, evo):
    """炉心：三足丹炉，炉身青铜，炉盖带钮，两耳，炉下火苗，炉顶一缕烟。"""
    glow(P, 32.0, 47.0, 10.0, mixc(TENG, ZHUSHA, 0.3), 0.55)
    for x0 in (26.5, 32.0, 37.5):
        fl = W.catmull_closed([(x0 - 2.0, 50.5), (x0 - 1.6, 47.5), (x0 + 0.2, 44.0), (x0 + 1.8, 47.8), (x0 + 2.0, 50.5)], 6)
        shape(P, fl, mixc(ZHUSHA, TENG, 0.45), ol=0.5, ol_rgb=ZHUSHA_DK, pool=0.4, pool_rgb=ZHUSHA, mottle=0.0, wob=0.02)
    bronze = mixc(mixc(ZHESHI, NONG, 0.4), SHILV, 0.12)
    for x0, x1 in ((22.5, 20.5), (41.5, 43.5), (32.0, 32.0)):
        leg = [(x0 - 1.6, 41.0), (x0 + 1.6, 41.0), (x1 + 0.9, 51.0), (x1 - 0.9, 51.0)]
        shape(P, leg, mixc(bronze, JIAO, 0.25), ol=0.8, pool=0.2)
    for x in (19.0, 45.0):
        ear = [(x - 1.8, 27.5), (x - 2.2, 19.5), (x + 2.2, 19.5), (x + 1.8, 27.5)]
        d, m = shape(P, ear, mixc(bronze, JIAO, 0.15), ol=0.9, pool=0.2)
        P.dot(x, 22.5, 0.9, PAPER, clip=m)
    body = W.catmull_closed([(18.0, 27.0), (19.0, 35.0), (23.5, 41.0), (32.0, 43.6), (40.5, 41.0), (45.0, 35.0), (46.0, 27.0)], 8)
    rgb = shade_lr(P, 18, 46, mixc(bronze, GOLD_HI, 0.35), mixc(bronze, JIAO, 0.35))
    d, m = shape(P, body, rgb, ol=OL, pool=0.3, pool_rgb=JIAO)
    for y in (30.0, 33.5):
        stroke(P, W.seg_pts((17.0, y), (47.0, y), n=40), 0.42, mixc(TENG, GOLD_DK, 0.35), clip=m)
    for x in np.arange(21.0, 44.0, 3.0):
        stroke(P, W.seg_pts((x, 30.6), (x + 1.4, 32.9), n=8), 0.32, mixc(TENG, GOLD_DK, 0.35), clip=m)
    lid = W.catmull_closed([(19.5, 27.2), (23.0, 23.0), (32.0, 21.0), (41.0, 23.0), (44.5, 27.2), (32.0, 28.0)], 8)
    shape(P, lid, shade_lr(P, 19, 45, mixc(bronze, GOLD_HI, 0.25), mixc(bronze, JIAO, 0.3)), ol=1.0, pool=0.25)
    P.dot(32.0, 19.6, 2.0, mixc(TENG, GOLD_DK, 0.2))
    P.dot(31.4, 19.0, 0.7, GOLD_HI)
    smoke = V.bezier([(32.0, 17.0), (29.5, 14.0), (34.5, 11.5), (31.0, 8.0)], 40)
    stroke(P, smoke, 0.9 * W.brush_profile(40, 0.8, 0.15), DAN, 0.7, dry=0.35, dry_start=0.3)


def em_jianyi(P, evo):
    """剑意：一道月牙剑气向右上飞出——浓墨刃身、内缘一线留白的锋，背后拖几道直的干笔疾痕，锋尖一点金星。"""
    cx, cy, R = 27.0, 39.0, 17.5
    a0, a1 = math.radians(-118), math.radians(28)
    a = np.linspace(a0, a1, 120)
    tt = np.linspace(0, 1, 120)
    hw = 0.3 + 4.4 * np.sin(np.pi * tt) ** 1.2
    pts = np.stack([cx + R * np.cos(a), cy + R * np.sin(a)], -1)
    # 疾痕：从弧的内侧往左下拖，平行于飞行方向
    mdir = np.array([math.cos(math.radians(-45)), math.sin(math.radians(-45))])
    for f, L, al in ((0.22, 7.0, 0.6), (0.4, 11.0, 0.75), (0.58, 12.0, 0.75), (0.76, 8.0, 0.6)):
        i = int(f * 119)
        st = pts[i] - mdir * (hw[i] + 1.2)
        stroke(P, W.seg_pts(st, st - mdir * L, n=24), np.linspace(1.0, 0.15, 24), NONG, al, dry=0.45, dry_start=0.2)
    stroke(P, pts, hw, JIAO, 1.0, dry=0.25, dry_start=0.6, jitter=0.06)
    edge = np.stack([cx + (R + 1.4) * np.cos(a), cy + (R + 1.4) * np.sin(a)], -1)
    stroke(P, edge[14:106], 0.15 + 0.75 * np.sin(np.pi * tt[14:106]), mixc(PAPER, WHITE, 0.85), 1.0)
    stroke(P, edge[30:92], 0.3, mixc(EL_INK["metal"], TENG, 0.3), 0.9)
    tip = pts[-1]
    for ang in (math.radians(20), math.radians(110)):
        for sgn in (-1, 1):
            e = tip + sgn * 3.0 * np.array([math.cos(ang), math.sin(ang)])
            stroke(P, W.seg_pts(tip, e, n=10), np.linspace(0.6, 0.1, 10), TENG)
    P.dot(tip[0], tip[1], 0.9, mixc(TENG, WHITE, 0.4))


def em_ruimu(P, evo):
    """锐目：杏仁眼，金色虹膜、竖瞳，上眼睑一笔浓墨挑出锋，眉如剑。"""
    up = V.bezier([(13.5, 34.5), (24.0, 21.0), (40.0, 21.5), (50.5, 31.0)], 60)
    lo = V.bezier([(13.5, 34.5), (24.0, 44.0), (40.0, 43.0), (50.5, 31.0)], 60)
    eye = np.vstack([up, lo[::-1][1:-1]])
    d, m = shape(P, eye, mixc(PAPER, WHITE, 0.75), ol=0, pool=0.25, pool_rgb=QING, mottle=0.0, wob=0.0)
    P.lay.over(QING, 0.35 * m * smoothstep(29.0, 22.0, P.Y))
    rr = np.hypot(P.X - 32.0, P.Y - 32.5)
    iris = smoothstep(7.4 + P.aa, 7.4 - P.aa, rr) * m
    irgb = mixc(mixc(EL_INK["metal"], TENG, 0.3), mixc(ZHESHI, JIAO, 0.3), smoothstep(2.0, 7.4, rr))
    P.lay.over(irgb, iris)
    th = np.arctan2(P.Y - 32.5, P.X - 32.0)
    spokes = 0.5 + 0.5 * np.cos(th * 14)
    P.lay.over(mixc(ZHESHI, JIAO, 0.4), iris * 0.35 * smoothstep(0.7, 1.0, spokes) * smoothstep(3.0, 6.0, rr))
    ring = smoothstep(0.55 + P.aa, 0.55 - P.aa, np.abs(rr - 7.2)) * m
    P.lay.over(INK_LINE, ring)
    pupil = smoothstep(1.0 + P.aa / 2, 1.0 - P.aa / 2, np.hypot((P.X - 32.0) / 1.6, (P.Y - 32.5) / 5.0)) * m
    P.lay.over(JIAO, pupil)
    P.dot(29.8, 29.6, 1.3, WHITE, clip=m)
    stroke(P, V.bezier([(13.0, 35.0), (24.0, 20.8), (40.0, 21.2), (53.0, 27.5)], 80), 0.3 + 1.9 * np.sin(np.pi * np.linspace(0.05, 0.95, 80)) ** 0.8, JIAO, 1.0)
    stroke(P, lo, 0.25 + 0.75 * np.sin(np.pi * np.linspace(0, 1, 60)), NONG, 1.0)
    brow = V.bezier([(15.5, 20.0), (25.0, 14.5), (38.0, 13.5), (49.5, 16.5)], 60)
    stroke(P, brow, 0.25 + 1.9 * np.interp(np.linspace(0, 1, 60), [0, 0.25, 0.7, 1.0], [0.4, 1.0, 0.8, 0.0]), JIAO, 1.0, dry=0.35, dry_start=0.55)


def em_jingxin(P, evo):
    """静心：一滴水（花青淡彩、白色反光），下面几圈静静的涟漪。"""
    for k, (rx, ry, hw) in enumerate(((7.5, 1.9, 0.75), (12.5, 3.2, 0.65), (17.5, 4.4, 0.5))):
        for a0, a1 in ((0.15, 2.95), (3.35, 6.1)):
            a = np.linspace(a0 + 0.1 * k, a1 - 0.1 * k, 50)
            pts = np.stack([32.0 + rx * np.cos(a), 45.5 + ry * np.sin(a)], -1)
            stroke(P, pts, hw * W.brush_profile(50, 0.3, 0.3, 0.3), mixc(EL_INK["water"], HUAQING, 0.4), 0.9)
    drop = W.catmull_closed([(32.0, 10.5), (35.4, 18.0), (39.6, 25.0), (40.6, 30.5), (38.0, 36.0), (32.0, 38.2), (26.0, 36.0), (23.4, 30.5), (24.4, 25.0), (28.6, 18.0)], 8)
    rr = np.hypot((P.X - 29.5) / 9.0, (P.Y - 26.0) / 12.0)
    rgb = mixc(mixc(W_HUAQING, WHITE, 0.25), mixc(EL_INK["water"], HUAQING, 0.45), smoothstep(0.2, 1.1, rr))
    d, m = shape(P, drop, rgb, ol=OL, ol_rgb=mixc(HUAQING, JIAO, 0.55), pool=0.35, pool_rgb=mixc(HUAQING, JIAO, 0.3), mottle=0.0, wob=0.03)
    stroke(P, V.bezier([(27.2, 33.0), (25.6, 28.5), (27.5, 23.5)], 30), 1.0 * W.brush_profile(30, 0.4, 0.3), WHITE, 0.9, clip=m)
    P.dot(29.5, 20.5, 0.8, WHITE, clip=m)


def em_yinhun(P, evo):
    """引魂：一团魂火悬在小铃上方。"""
    metal = mixc(TENG, ZHESHI, 0.45)
    paint_bell(P, 32.0, 42.0, 0.85, metal=metal, loop=False)
    glow(P, 32.0, 22.0, 11.0, mixc(col(S.SOUL_LIGHT), PAPER, 0.4), 0.7)
    wisp = W.catmull_closed([(32.0, 30.5), (37.0, 28.0), (38.0, 22.5), (35.6, 17.5), (36.8, 12.5), (34.0, 8.5), (33.2, 13.5), (30.0, 16.0), (26.5, 20.5), (26.6, 26.5)], 8)
    rr = np.hypot((P.X - 32.0) / 5.5, (P.Y - 24.0) / 6.5)
    rgb = mixc(mixc(col(S.SOUL_LIGHT), WHITE, 0.5), mixc(EL_INK["water"], HUAQING, 0.3), smoothstep(0.3, 1.2, rr))
    shape(P, wisp, rgb, ol=1.1, ol_rgb=mixc(HUAQING, JIAO, 0.45), pool=0.35, pool_rgb=EL_INK["water"], mottle=0.0, wob=0.03)
    P.dot(32.0, 25.0, 2.4, WHITE, 0.85)
    for (x, y, r) in ((24.0, 14.0, 0.6), (41.0, 18.0, 0.5), (40.0, 9.5, 0.45)):
        P.dot(x, y, r, EL_INK["water"])


def em_zhezhi(P, evo):
    """折纸：一张略斜的方纸，右下角折起一角（露出石绿的纸背），纸面上虚线的折痕。"""
    fr = Fr(31.0, 32.0, -9.0, 1.0)
    h = 13.5
    A, B_, C_, D_ = (-h, -h), (h, -h), (h, h), (-h, h)
    f = 9.0  # 折角大小
    e1, e2 = (h, h - f), (h - f, h)
    fold_tip = (h - f, h - f)  # 角折回纸面上的位置
    sheet = fr([A, B_, e1, e2, D_])
    d, _ = P.sdf(sheet + [1.4, 1.6])
    P.fill(d, JIAO, 0.18)
    rgb = shade_lr(P, 16, 48, mixc(PAPER, WHITE, 0.75), mixc(PAPER, PAPER_SH, 0.55))
    d, m = shape(P, sheet, rgb, ol=OL, pool=0.15, pool_rgb=QING, mottle=0.03, wob=0.04)
    for a, b in (((-h, 0.0), (h, 0.0)), ((0.0, -h), (0.0, h - 0.5)), ((-h, -h), (h - f - 0.5, h - f - 0.5))):
        pts = fr(W.seg_pts(a, b, n=60))
        k = np.arange(len(pts))
        for i0 in range(0, len(pts) - 4, 8):
            stroke(P, pts[i0 : i0 + 5], 0.32, DAN, 0.75, clip=m)
        del k
    flap = fr([e1, e2, fold_tip])
    d, t = P.sdf(flap + [0.8, 0.9])
    P.fill(d, JIAO, 0.2)
    shape(P, flap, mixc(W_SHILV, EL_INK["wood"], 0.3), ol=1.1, pool=0.35, pool_rgb=mixc(SHILV, JIAO, 0.35), wob=0.03)
    stroke(P, fr(W.seg_pts(e1, e2, n=20)), 0.6, INK_LINE)


def em_jixing(P, evo):
    """疾行：一朵祥云（三团云头，白底墨勾，主云头里一个卷），左边拖出几道疾风。"""
    puffs = ((38.0, 27.5, 8.2), (28.5, 31.5, 6.2), (46.0, 33.5, 5.2), (36.5, 35.5, 6.0))
    for (x, y, r) in puffs:
        d, t = P.sdf(W.ellipse_pts(x + 0.8, y + 1.0, r, r * 0.9, 48))
        P.fill(d, JIAO, 0.15)
    for (x, y, r) in puffs:
        d, t = P.sdf(W.wobble(W.ellipse_pts(x, y, r, r * 0.9, 48), P.rng, 0.05, spacing=0.3))
        P.fill(d, shade_lr(P, 20, 52, mixc(PAPER, WHITE, 0.8), mixc(PAPER, QING, 0.35)), pool=0.25, pool_rgb=QING, pool_w=0.8)
        P.outline(d, t, 1.15, INK_LINE, jitter=0.2)
    cx, cy = 38.0, 27.5
    th = np.linspace(0.0, 1.6 * math.pi, 80)
    r = 1.0 + 4.6 * th / th[-1]
    spiral = np.stack([cx + r * np.cos(th + 1.2), cy + 0.9 * r * np.sin(th + 1.2)], -1)
    stroke(P, spiral, np.interp(np.linspace(0, 1, 80), [0, 0.3, 1.0], [0.4, 0.9, 1.0]), INK_LINE)
    for (x0, y0, L, rgb) in ((9.5, 38.0, 16.0, EL_INK["wood"]), (12.5, 43.0, 14.0, NONG), (15.0, 29.0, 9.0, ZHONG), (14.0, 47.5, 9.0, EL_INK["wood"])):
        stroke(P, V.bezier([(x0, y0), (x0 + L / 2, y0 - 0.5), (x0 + L, y0 - 1.2)], 30), 1.15 * W.brush_profile(30, 0.2, 1.0, 0.0)[::-1], rgb, 0.95, dry=0.45, dry_start=0.0)


def _old_jixing(P, evo):
    cx, cy = 37.0, 28.5
    th = np.linspace(0.0, 2.15 * math.pi, 160)
    r = 1.0 + 7.6 * th / th[-1]
    a = th + math.radians(-60)
    spiral = np.stack([cx + r * np.cos(a), cy + r * np.sin(a)], -1)
    end = spiral[-1]
    tail = V.bezier([end, end + [-6.0, 2.5], end + [-14.0, 0.0], end + [-22.0, 5.0]], 80)
    path = np.vstack([spiral, tail[1:]])
    tt = np.linspace(0, 1, len(path))
    hw = np.interp(tt, [0.0, 0.15, 0.55, 0.7, 1.0], [0.35, 1.0, 2.0, 1.7, 0.25])
    P.lay.over(mixc(PAPER, WHITE, 0.6), 0.9 * smoothstep(8.8, 7.5, np.hypot(P.X - cx, P.Y - cy)))
    stroke(P, path, hw, JIAO, 1.0, dry=0.35, dry_start=0.75, jitter=0.06)
    th2 = np.linspace(0.0, 1.8 * math.pi, 100)
    r2 = 0.8 + 4.2 * th2 / th2[-1]
    a2 = th2 + math.radians(-80)
    sp2 = np.stack([22.0 + r2 * np.cos(a2), 21.0 + r2 * np.sin(a2)], -1)
    tail2 = V.bezier([sp2[-1], sp2[-1] + [-3.0, 1.5], sp2[-1] + [-7.0, 0.5]], 40)
    path2 = np.vstack([sp2, tail2[1:]])
    stroke(P, path2, np.interp(np.linspace(0, 1, len(path2)), [0, 0.2, 0.7, 1], [0.3, 0.8, 1.3, 0.2]), NONG, 0.95, dry=0.3, dry_start=0.75)
    for (x0, y0, L, rgb) in ((11.0, 41.0, 17.0, EL_INK["wood"]), (14.0, 46.0, 13.0, NONG), (17.0, 36.5, 9.0, ZHONG)):
        stroke(P, V.bezier([(x0, y0), (x0 + L / 2, y0 - 0.6), (x0 + L, y0 - 1.6)], 30), 1.2 * W.brush_profile(30, 1.0, 0.1), rgb, 0.95, dry=0.45, dry_start=0.4)


def em_houde(P, evo):
    """厚德：水墨三峰，山脚一抹赭，一道留白的云气。"""
    paint_mountain(P, Fr(32.0, 35.5, 0.0, 1.15))


def em_panshi(P, evo):
    """磐石：一块敦实的大石，折带皴、苔点，下面一道地线。"""
    stroke(P, V.bezier([(12.0, 46.0), (32.0, 45.0), (52.0, 46.0)], 40), 0.9 * W.brush_profile(40, 0.8, 0.2), ZHONG, 0.8, dry=0.45, dry_start=0.3)
    rock = W.catmull_closed([(15.0, 44.5), (14.0, 36.0), (18.0, 27.5), (26.0, 21.5), (37.0, 20.5), (45.5, 25.5), (50.0, 34.5), (49.0, 44.5), (32.0, 45.5)], 8)
    stone = mixc(DAN, W_ZHESHI, 0.35)
    k = np.clip((P.X - 14.0) / 36.0 * 0.55 + (P.Y - 20.0) / 25.0 * 0.6, 0, 1)
    rgb = mixc(mixc(stone, PAPER, 0.45), mixc(stone, JIAO, 0.45), k)
    d, m = shape(P, rock, rgb, ol=0, pool=0.3, pool_rgb=JIAO, mottle=0.12)
    for pts in (((26.0, 21.5), (23.0, 31.0), (28.0, 44.0)), ((37.0, 20.5), (39.5, 31.5), (36.0, 44.5)), ((18.0, 28.0), (24.0, 30.5), (30.5, 30.0))):
        stroke(P, V.bezier(list(pts), 30), 0.75 * W.brush_profile(30, 1.0, 0.3), NONG, 0.85, clip=m, dry=0.35, dry_start=0.4)
    for (x0, y0) in ((41.5, 33.0), (44.0, 38.0), (19.5, 37.0)):
        stroke(P, W.seg_pts((x0, y0), (x0 + 3.0, y0 + 2.2), n=12), 0.55, ZHONG, 0.6, clip=m, dry=0.4, dry_start=0.2)
    d2, t = P.sdf(W.wobble(rock, P.rng, 0.06, spacing=0.3))
    P.outline(d2, t, 1.6, INK_LINE, jitter=0.3, dry=0.1)
    for (x, y, r) in ((24.0, 22.5, 0.9), (30.0, 20.6, 0.8), (40.0, 21.3, 0.9), (45.5, 25.8, 0.7)):
        P.dot(x, y, r, JIAO)
    P.dot(35.0, 20.2, 0.9, mixc(SHILV, JIAO, 0.3))
    P.dot(51.0, 45.0, 1.4, mixc(DAN, PAPER, 0.3))


# ============================================================== 五行


def em_el_metal(P, evo):
    """金：一锭元宝。"""
    body = W.catmull_closed([(13.5, 27.5), (19.5, 33.5), (26.0, 35.3), (38.0, 35.3), (44.5, 33.5), (50.5, 27.5), (48.0, 38.5), (40.0, 45.0), (32.0, 46.5), (24.0, 45.0), (16.0, 38.5)], 8)
    rgb = mixc(mixc(TENG, GOLD_HI, 0.35), mixc(TENG, GOLD_DK, 0.6), smoothstep(30.0, 46.0, P.Y))
    shape(P, body, rgb, ol=OL, ol_rgb=mixc(GOLD_DK, JIAO, 0.5), pool=0.45, pool_rgb=GOLD_DK, mottle=0.04)
    stroke(P, V.bezier([(14.5, 28.2), (32.0, 23.0), (49.5, 28.2)], 40), 0.55, GOLD_DK, 0.9)
    rr = np.hypot((P.X - 32.0) / 8.6, (P.Y - 31.0) / 7.0)
    dome = W.ellipse_pts(32.0, 31.0, 8.6, 7.0, 48)
    shape(P, dome, mixc(GOLD_HI, mixc(TENG, GOLD_DK, 0.4), smoothstep(0.1, 1.0, np.hypot((P.X - 29.0) / 8.6, (P.Y - 28.0) / 7.0))), ol=1.1, ol_rgb=mixc(GOLD_DK, JIAO, 0.5), pool=0.35, pool_rgb=GOLD_DK, mottle=0.0)
    del rr
    stroke(P, V.bezier([(27.0, 30.5), (28.0, 27.2), (31.0, 25.6)], 20), 0.75 * W.brush_profile(20, 0.4, 0.3), WHITE, 0.85)
    for (x, y, L) in ((47.5, 18.0, 3.0), (16.5, 21.0, 2.2)):
        stroke(P, W.seg_pts((x - L, y), (x + L, y), n=10), 0.35, TENG)
        stroke(P, W.seg_pts((x, y - L), (x, y + L), n=10), 0.35, TENG)


def em_el_wood(P, evo):
    """木：一株新芽，两片石绿的叶子，下面一小抔土。"""
    mound = W.ellipse_pts(32.0, 46.5, 11.5, 3.4, 48)
    shape(P, mound, mixc(W_ZHESHI, DAN, 0.3), ol=1.0, pool=0.3)
    stem = V.bezier([(32.0, 46.0), (30.6, 38.0), (32.6, 29.0)], 40)
    stroke(P, stem, np.linspace(1.3, 0.9, 40), mixc(SHILV, JIAO, 0.45))
    for base, tip, wd in (((31.6, 34.5), (15.5, 26.5), 9.0), ((32.4, 30.5), (48.5, 17.0), 10.5)):
        poly = W.almond(base, tip, wd, 40, bulge=0.45)
        along = ((P.X - base[0]) * (tip[0] - base[0]) + (P.Y - base[1]) * (tip[1] - base[1])) / ((tip[0] - base[0]) ** 2 + (tip[1] - base[1]) ** 2)
        d, m = shape(P, poly, mixc(mixc(W_SHILV, EL_INK["wood"], 0.4), mixc(SHILV, JIAO, 0.3), smoothstep(0.0, 1.0, along)), ol=1.15, ol_rgb=mixc(SHILV, JIAO, 0.65), pool=0.35, pool_rgb=mixc(SHILV, JIAO, 0.4), mottle=0.05)
        stroke(P, W.seg_pts(base, tip, n=30), 0.35 * W.brush_profile(30, 1.0, 0.2, 0.0), mixc(SHILV, JIAO, 0.6), 0.8, clip=m)
    bud = W.almond((32.6, 29.5), (34.6, 22.0), 3.6, 24, bulge=0.4)
    shape(P, bud, mixc(W_SHILV, PAPER, 0.2), ol=0.8, ol_rgb=mixc(SHILV, JIAO, 0.6), pool=0.3, pool_rgb=SHILV)


def em_el_water(P, evo):
    """水：三道水纹，最上一道浪头卷起。"""
    rgb = mixc(EL_INK["water"], HUAQING, 0.45)
    for k, y0 in enumerate((25.0, 33.5, 42.0)):
        half = math.sqrt(max(21.0**2 - (y0 - 32.0) ** 2, 0)) - 1.5
        xs = np.linspace(32 - half, 32 + half, 120)
        ys = y0 + 2.5 * np.sin(2 * math.pi * (xs - 32 + 3.0 * k) / 13.0)
        pts = np.stack([xs, ys], -1)
        stroke(P, pts, (1.7 - 0.15 * k) * W.brush_profile(120, 0.35, 0.2, 0.1), rgb if k else mixc(rgb, JIAO, 0.25), 1.0, dry=0.25, dry_start=0.8)
    # 浪头：顶上一道向右卷的浪尖
    th = np.linspace(math.pi, 2.6 * math.pi, 60)
    r = 4.2 - 2.6 * (th - th[0]) / (th[-1] - th[0])
    curl = np.stack([30.0 + r * np.cos(th), 18.5 + r * np.sin(th)], -1)
    stroke(P, curl, np.linspace(1.5, 0.4, 60), mixc(rgb, JIAO, 0.25), 1.0)
    P.dot(41.5, 19.0, 0.8, rgb)
    P.dot(44.0, 22.0, 0.6, rgb)


def em_el_fire(P, evo):
    """火：三舌火苗，朱砂边、藤黄芯、白热的心，火舌尖收一点焦墨。"""
    pts = [(32.0, 48.0), (24.5, 45.0), (20.5, 38.0), (22.0, 29.5), (25.0, 24.0), (26.4, 29.0), (28.6, 24.0), (30.2, 17.0), (32.6, 9.0),
           (35.8, 17.0), (37.8, 23.5), (39.4, 28.0), (41.0, 21.0), (44.0, 28.5), (44.2, 38.0), (40.0, 45.0)]
    flame = W.catmull_closed(pts, 8)
    heat = np.exp(-(((P.X - 32.0) / 8.0) ** 2 + ((P.Y - 39.0) / 9.5) ** 2))
    rgb = V.ramp(np.clip(heat * 1.05, 0, 1), V.FLAME_STOPS)
    shape(P, flame, rgb, ol=1.15, ol_rgb=mixc(ZHUSHA, JIAO, 0.55), pool=0.35, pool_rgb=ZHUSHA, mottle=0.0, wob=0.04)
    core = W.catmull_closed([(32.0, 44.0), (28.5, 41.0), (28.6, 36.0), (31.4, 30.0), (33.4, 35.5), (35.5, 39.5), (35.0, 42.5)], 8)
    shape(P, core, mixc(TENG, WHITE, 0.55), ol=0, pool=0.3, pool_rgb=TENG, mottle=0.0, wob=0.03)
    for (x, y, r) in ((18.0, 22.0, 0.7), (46.5, 17.0, 0.6), (42.0, 11.5, 0.5)):
        P.dot(x, y, r, ZHUSHA)


def em_el_earth(P, evo):
    """土：一座层层堆起的土丘（几道地层），顶上两茎小草，脚边一块方石。"""
    mound = W.catmull_closed([(12.5, 45.5), (16.5, 35.0), (23.5, 27.5), (32.0, 24.5), (40.5, 27.5), (47.5, 35.0), (51.5, 45.5), (32.0, 46.5)], 8)
    rgb = mixc(mixc(W_ZHESHI, EL_INK["earth"], 0.35), mixc(ZHESHI, ZHONG, 0.35), smoothstep(24.0, 46.0, P.Y))
    d, m = shape(P, mound, rgb, ol=0, pool=0.3, pool_rgb=mixc(ZHESHI, JIAO, 0.3), mottle=0.08)
    for k, y0 in enumerate((31.5, 37.0, 42.0)):
        xs = np.linspace(10.0, 54.0, 60)
        ys = y0 + 1.0 * np.sin(xs * 0.35 + k * 1.7)
        stroke(P, np.stack([xs, ys], -1), 0.55 - 0.05 * k, mixc(ZHESHI, JIAO, 0.45), 0.85, clip=m, dry=0.3, dry_start=0.0)
    d2, t = P.sdf(W.wobble(mound, P.rng, 0.06, spacing=0.3))
    P.outline(d2, t, OL, INK_LINE, jitter=0.25)
    for a in (-0.35, 0.25):
        stroke(P, V.bezier([(32.0, 25.0), (32.0 + 4 * math.sin(a), 21.0), (32.0 + 7 * math.sin(a), 18.0)], 20), 0.6 * W.brush_profile(20, 1.0, 0.1, 0.0), mixc(SHILV, JIAO, 0.45))
    for (x, y, rx) in ((46.5, 44.0, 2.4), (50.0, 45.2, 1.5)):
        shape(P, W.ellipse_pts(x, y, rx, rx * 0.7, 24), mixc(DAN, PAPER, 0.3), ol=0.8, pool=0.3)


# ============================================================== 汇总

EMBLEMS = {
    "lamp": em_lamp, "sword": em_sword, "bell": em_bell, "crane": em_crane, "seal": em_seal,
    "changming": em_changming, "luxin": em_luxin, "jianyi": em_jianyi, "ruimu": em_ruimu, "jingxin": em_jingxin,
    "yinhun": em_yinhun, "zhezhi": em_zhezhi, "jixing": em_jixing, "houde": em_houde, "panshi": em_panshi,
    "el_metal": em_el_metal, "el_wood": em_el_wood, "el_water": em_el_water, "el_fire": em_el_fire, "el_earth": em_el_earth,
}


def icon_specs():
    """[(文件名, 物件键, 五行, 是否进化, 是否五行图标, meta 附加字段)]，顺序固定（种子按序号取）。"""
    out = []
    for wid, (name, evo_name, el) in WEAPONS.items():
        out.append((f"icon_{wid}", wid, el, False, False, {"kind": "weapon", "id": wid, "el": el, "name": name}))
    for wid, (name, evo_name, el) in WEAPONS.items():
        out.append((f"icon_{wid}_evo", wid, el, True, False, {"kind": "weapon_evo", "id": wid, "el": el, "name": evo_name}))
    for pid, (name, el) in PASSIVES.items():
        out.append((f"icon_{pid}", pid, el, False, False, {"kind": "passive", "id": pid, "el": el, "name": name}))
    for el, name in ELEMENTS.items():
        out.append((f"icon_el_{el}", f"el_{el}", el, False, True, {"kind": "element", "id": el, "el": el, "name": name}))
    return out


def make_icon(index: int, key: str, el: str, evo: bool, element: bool) -> Image.Image:
    P = W.Painter(SIZE, SIZE, 6000 + 37 * index, ss=SS)
    frame_back(P, el, evo=evo, element=element)
    EMBLEMS[key](P, evo)
    frame_front(P, el, evo=evo, element=element)
    return P.image()


def build() -> dict[str, tuple[Image.Image, tuple[float, float], dict]]:
    base = {"color": "full", "blend": "normal", "tint": False}
    out = {}
    for i, (fname, key, el, evo, element, extra) in enumerate(icon_specs()):
        out[fname] = (make_icon(i, key, el, evo, element), (0.5, 0.5), {**base, **extra, "note": f"界面图标：{extra['name']}"})
    return out


def main() -> dict:
    t0 = time.perf_counter()
    UI_DIR.mkdir(parents=True, exist_ok=True)
    items = build()
    files, total = {}, 0
    for key, (img, anc, extra) in items.items():
        fn = f"{key}.png"
        V.save_png(img, UI_DIR / fn)
        total += (UI_DIR / fn).stat().st_size
        files[fn] = V.anchor_entry(img, anc, **extra)
    meta = {
        "name": "ui",
        "generator": "art/post/ui_icons.py",
        "format": "PNG RGBA，直通（非预乘）alpha；全彩、正常混合、不染色",
        "px_per_unit": V.PPU,
        "display_px_1x": SIZE,
        "el_colors": {k: S.rgb_to_hex(tuple(int(round(c * 255)) for c in v)) for k, v in EL_INK.items()},
        "files": files,
    }
    (UI_DIR / "meta.json").write_text(V.dump_json(meta), encoding="utf-8")
    print(f"写出 {len(items)} 个图标，共 {total / 1024:.1f} KB，用时 {time.perf_counter() - t0:.1f} s → {UI_DIR}")
    return items


if __name__ == "__main__":
    main()
