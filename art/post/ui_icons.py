#!/usr/bin/env python3
"""提灯夜行 · 桌面版界面图标（只用 Pillow + numpy）。

一套统一的图标：宣纸色圆底 + 水墨画的物件 + 一笔写成的墨圈（圆相，留一个小缺口、收笔飞白）
+ 墨圈内侧一道细的五行色弧。进化法器另加一道藤黄金圈、物件更繁复并带金饰；五行图标的圆底染一层本行的淡彩。
64×64（1 倍）/ 128×128（2 倍），正常混合，锚点居中，全彩不染色。要求缩到 32 像素仍能认出来，
所以物件以墨块、粗轮廓为主，细节只作点缀。

坐标都按 1 倍像素写（64×64 画布，圆心 (32, 32)），出图密度由 style.DENSITY 决定（见 vfx_textures.grid1/noise1）。
画法复用 weapon_textures.Painter（淡彩填色、手抖轮廓、干笔）。五行颜色取自 src/data/elements.ts，
兑上相近的国画颜料，在纸色上也看得清（EL_INK）。

第二批（追加在前 25 个之后，前 25 个逐字节不变）：
  补给 icon_lotus 莲子、icon_oil 灯油；心灯 icon_meta_<dmg|hp|agi|luck>（点亮）与 _off（未点亮，同一幅画褪成淡墨）；
  奇遇 icon_enc_<toad|spring|shrine|altar|rift>；古灯增益 icon_buff_<fury|swift|soul|iron>；
  夜签 icon_omen_<bloodmoon|fog|glass|foxes|gale|chestrain|element|greed|quiet|wonders>（朱砂双圈框）；
  界面 icon_kills、icon_pause、icon_dash、icon_ult、icon_level（等级徽章底，中间留空）；
  朱砂印章 seal_*（ui_seals.py 画，尺寸各异，见 meta 的 size）。
各类的色弧见下面“第二批”一节；meta 里每项都有 kind、id、name。

第三批（M2.5，ui_icons_m25.py 画，追加在全部原有图标与印章之后，原有的逐字节不变）：
  心法 7 门、夜签 无月 / 逆克、金币、奇遇 货郎、精英词缀 icon_affix_*（小图标 32 / 64 像素）、灯驿人物 icon_hub_0..3、灯坠 icon_charm_*；
  五行反应印 seal_react_*（ui_seals.py，朱白相间的圆角方印）。

出图按图标并行（多进程，LANTERN_JOBS 控制进程数，默认 min(4, CPU 数)；每个图标自带种子，结果与串行一致）。

输出：art/out/<ASSETS_DIR_NAME>/ui/  icon_*.png、seal_*.png + meta.json
用法（在仓库根目录下）：
  art/.venv/bin/python art/post/ui_icons.py                          # 1 倍
  LANTERN_ART_DENSITY=2 art/.venv/bin/python art/post/ui_icons.py    # 2 倍
"""

from __future__ import annotations

import math
import multiprocessing
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor
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


def disc_back(P: W.Painter, base):
    """宣纸色圆底（base 是底色，纸纹、中心提亮都在它上面做）。"""
    r = np.hypot(P.X - C, P.Y - C)
    th = np.mod(np.arctan2(P.Y - C, P.X - C) / (2 * math.pi), 1.0)
    rr = 27.4 * (1 + 0.006 * W.sample1(W.pnoise1(P.rng, 256, 10.0), th))
    disc = smoothstep(rr + 2 * P.aa, rr - 2 * P.aa, r)
    n = V.noise1(P.rng, P.X.shape, 3.0 * P.ss)
    rgb = mixc(base, mixc(base, PAPER_SH, 0.8), np.clip(0.3 + 0.25 * n, 0, 1))
    # 中心略亮，边上一圈淡淡的积色，像一张小小的册页
    rgb = mixc(rgb, mixc(rgb, WHITE, 0.35), np.exp(-((r / 16.0) ** 2)) * 0.5)
    P.lay.over(rgb, disc)


def frame_back(P: W.Painter, el: str, *, evo=False, element=False):
    base = PAPER
    if element:
        base = mixc(PAPER, EL_WASH[el], 0.55)
    elif evo:
        base = mixc(PAPER, W_TENG, 0.16)
    disc_back(P, base)


def frame_front(P: W.Painter, el: str, *, evo=False, element=False):
    ring_front(P, EL_INK[el], arc_hw=1.05 if element else 0.8, evo=evo)


def ring_front(P: W.Painter, arc_rgb, *, arc_hw=0.8, evo=False, ink=(JIAO, NONG), dry=(0.06, 0.5), ring_alpha=1.0, gold_rim=None):
    """色弧 + 墨圈（圆相）+ 进化金圈。arc_rgb=None 不画色弧；ink、dry、ring_alpha 调墨圈的墨色与干湿；
    gold_rim=(半径, 半宽) 时在墨圈内侧加一道粗金圈（等级徽章底）。"""
    r = np.hypot(P.X - C, P.Y - C)
    th = np.mod(np.arctan2(P.Y - C, P.X - C), 2 * math.pi)
    # 色弧：墨圈内侧，从右下经下、左到左上，两头收细
    a0, span = math.radians(25.0), math.radians(235.0)
    if arc_rgb is not None:
        ta = np.mod(th - a0, 2 * math.pi) / span
        hwa = arc_hw * np.sin(np.pi * np.clip(ta, 0, 1)) ** 0.6 * (ta <= 1)
        arc = smoothstep(hwa + P.aa, hwa - P.aa, np.abs(r - 24.3)) * (hwa > 0.05)
        P.lay.over(arc_rgb, 0.95 * arc)
    if gold_rim is not None:
        gr, ghw = gold_rim
        rim = smoothstep(ghw + P.aa, ghw - P.aa, np.abs(r - gr))
        P.lay.over(mixc(mixc(TENG, GOLD_HI, 0.35), GOLD_DK, smoothstep(gr - ghw, gr + ghw, r) * 0.7), rim)
        for rr_, rgb_ in ((gr - ghw, GOLD_DK), (gr + ghw, GOLD_DK)):
            P.lay.over(rgb_, 0.8 * smoothstep(0.3 + P.aa, 0.3 - P.aa, np.abs(r - rr_)))
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
    dry = dry[1] * smoothstep(0.8, 1.0, tc) + dry[0]
    cov = cov * smoothstep(dry - 0.07, dry + 0.07, b)
    if ring_alpha != 1.0:
        cov = cov * ring_alpha
    P.lay.over(mixc(ink[0], ink[1], 0.35 * (1 - b) * tc), cov)
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
    # 万剑归宗：三把剑排成扇面，剑尖齐齐汇向上方一点，汇处一团金光（只三把，汇聚一眼看得出）
    T = np.array([32.0, 11.8])
    glow(P, T[0], T[1] + 1.0, 8.0, mixc(TENG, WHITE, 0.45), 0.75)
    for ang, sc, tip in ((-56.0, 0.74, T + [-1.6, 2.4]), (-124.0, 0.74, T + [1.6, 2.4])):
        a = math.radians(ang)
        o = tip - 21.5 * sc * np.array([math.cos(a), math.sin(a)])
        paint_sword(P, Fr(o[0], o[1], ang, sc), evo=True, tassel=False)
    a = math.radians(-90.0)
    o = T - 21.5 * 0.96 * np.array([math.cos(a), math.sin(a)])
    paint_sword(P, Fr(o[0], o[1], -90.0, 0.96), evo=True)
    sparkle(P, T[0], T[1] - 0.6, 4.6, mixc(TENG, WHITE, 0.25), 0.62)
    P.dot(T[0], T[1] - 0.6, 1.0, WHITE)


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


def cloud_curl(cx, cy, r0, r1, th0, turn, n=90):
    """云头的卷：从 th0（弧度）起顺时针卷进去，半径由 r0 收到 r1。"""
    th = th0 + np.linspace(0.0, turn, n)
    r = r0 + (r1 - r0) * np.linspace(0.0, 1.0, n) ** 0.9
    return np.stack([cx + r * np.cos(th), cy + r * np.sin(th)], -1)


def em_jixing(P, evo):
    """疾行：一缕被风扯开的水墨云气——右边一个浓墨卷成的云头，淡墨的云身往左拖成长尾、尾上飞白，
    下面再跟一小卷云和一道石绿的疾风，整团往右赶。"""
    # 云身：淡墨晕开的一片，右头圆、左尾尖
    body = W.catmull_closed([(11.0, 33.6), (20.0, 29.4), (30.0, 25.6), (38.5, 22.6), (45.5, 23.8), (49.2, 29.6), (47.2, 35.6),
                             (41.0, 38.0), (33.0, 37.2), (24.0, 36.6), (16.5, 35.6)], 8)
    d, _ = P.sdf(W.wobble(body, P.rng, 0.25, spacing=0.3))
    n = V.noise1(P.rng, P.X.shape, 2.2 * P.ss)
    k = np.clip(0.55 + 0.25 * n, 0, 1) * smoothstep(8.0, 30.0, P.X)  # 越往尾巴越淡
    wash = mixc(mixc(DAN, ZHONG, 0.3), QING, 0.25)
    P.lay.over(wash, smoothstep(0.9, -1.4, d) * (0.3 + 0.55 * k))
    P.lay.over(mixc(wash, ZHONG, 0.5), 0.55 * np.exp(np.minimum(d, 0.0) / 0.9) * (d < 0.6) * k)  # 水痕：边上积一道
    # 主笔：云头卷心起笔，卷出来顺势往左一扫，尾梢飞白（笔是倒着写的：越往尾越干）
    tail = V.bezier([(9.5, 34.6), (21.0, 31.0), (31.0, 22.6), (41.0, 22.8)], 70)
    curl = cloud_curl(41.6, 29.6, 6.8, 1.6, math.radians(-95.0), math.radians(320.0))
    path = V.arc_resample(np.vstack([tail, curl[1:]]), 200)[::-1]
    tt = np.linspace(0, 1, len(path))
    hw = np.interp(tt, [0.0, 0.25, 0.58, 0.82, 1.0], [0.55, 2.0, 2.5, 1.3, 0.25])
    stroke(P, path, hw, JIAO, 1.0, dry=0.5, dry_start=0.5, jitter=0.06)
    # 小卷云：左下跟着一个小的，尾巴也往左拖
    tail2 = V.bezier([(12.5, 41.6), (20.0, 41.8), (25.0, 37.2), (29.6, 37.0)], 50)
    curl2 = cloud_curl(29.8, 40.6, 3.6, 1.0, math.radians(-92.0), math.radians(300.0), n=60)
    path2 = V.arc_resample(np.vstack([tail2, curl2[1:]]), 120)[::-1]
    t2 = np.linspace(0, 1, len(path2))
    stroke(P, path2, np.interp(t2, [0.0, 0.4, 0.75, 1.0], [0.45, 1.5, 0.9, 0.2]), mixc(NONG, ZHONG, 0.3), 0.95, dry=0.5, dry_start=0.45)
    # 疾风：石绿的两道干笔，前头（右）粗、往左拖细、越拖越干
    for (x0, y0, L, al) in ((14.0, 47.6, 27.0, 0.95), (36.0, 44.4, 12.0, 0.8)):
        pts = V.bezier([(x0 + L, y0 - 1.3), (x0 + L / 2, y0 - 0.4), (x0, y0)], 40)
        stroke(P, pts, 1.25 * W.brush_profile(40, 1.0, 0.2, 0.0), EL_INK["wood"], al, dry=0.45, dry_start=0.2)


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


# ============================================================== 第二批：补给、心灯、奇遇、增益、夜签、界面
#
# 同一套框，按类别换色弧：补给与界面用淡墨兑赭的中性弧；心灯点亮时是暖灯色弧、圈里一团灯晕，
# 没点亮时整幅褪成淡墨、墨圈更干更淡；奇遇和增益的色弧取网页版的颜色兑国画颜料（ACC_INK，同 EL_INK 的兑法）；
# 夜签不用墨圈，换朱砂双圈（像一枚圆形朱文印），和法器、心法一眼分开。

ACC_HEX = {  # 网页版 web/lantern/game.js 的 EVENTS / BUFFS 颜色
    "toad": "#FFD98A", "spring": "#5FD4C4", "shrine": "#FF8A3D", "altar": "#FF6B5A", "rift": "#B07CF0",
    "fury": "#FF8A3D", "swift": "#6FD6A0", "soul": "#5FD4C4", "iron": "#E9D9A6",
}
ACC_INK = {
    "toad": col(S.mix(S.mix(ACC_HEX["toad"], S.ACCENT["tenghuang"], 0.5), S.ACCENT["zheshi"], 0.3)),
    "spring": col(S.mix(S.mix(ACC_HEX["spring"], S.ACCENT["shilv"], 0.4), S.ACCENT["huaqing"], 0.25)),
    "shrine": EL_INK["fire"],
    "altar": col(S.mix(ACC_HEX["altar"], S.ACCENT["zhusha"], 0.55)),
    "rift": col(S.mix(S.mix(ACC_HEX["rift"], S.ACCENT["huaqing"], 0.3), S.INK["zhong"], 0.15)),
    "fury": EL_INK["fire"],
    "swift": EL_INK["wood"],
    "soul": col(S.mix(S.mix(ACC_HEX["soul"], S.ACCENT["shilv"], 0.4), S.ACCENT["huaqing"], 0.25)),
    "iron": EL_INK["metal"],
}
NEUTRAL_ARC = mixc(DAN, ZHESHI, 0.3)  # 补给、界面：淡墨兑一点赭，不像任何一行
LAMP_ARC = mixc(TENG, ZHUSHA, 0.3)  # 心灯点亮：暖灯色
LAMP_GLOW = mixc(col(S.LANTERN_LIGHT), PAPER, 0.25)
OFF_INK = (mixc(NONG, DAN, 0.35), DAN)  # 心灯未点亮：墨圈淡、干
SOUL = col(S.SOUL_LIGHT)
RIFT_HOT = col("#D2386A")  # 与 ground/rift_glow 的染色一致
PURPLE_STOPS = [
    (0.00, S.mix("#B07CF0", S.INK["jiao"], 0.55)),
    (0.15, S.mix("#B07CF0", S.INK["zhong"], 0.25)),
    (0.50, S.mix("#B07CF0", "#D2386A", 0.35)),
    (0.80, S.mix("#D2386A", "#FFFFFF", 0.55)),
    (1.00, S.mix("#F4D8F0", "#FFFFFF", 0.4)),
]
FOX_STOPS = [
    (0.00, S.mix(S.EYE["fox"], S.INK["jiao"], 0.5)),
    (0.15, S.mix(S.EYE["fox"], S.ACCENT["zhusha"], 0.5)),
    (0.50, S.EYE["fox"]),
    (0.80, S.mix(S.EYE["fox"], "#FFFFFF", 0.55)),
    (1.00, S.mix(S.EYE["fox"], "#FFFFFF", 0.85)),
]


def lum3(rgb):
    return np.asarray(rgb)[..., :3] @ np.array([0.299, 0.587, 0.114])


SOUL_RIM = mixc(mixc(HUAQING, JIAO, 0.45), QING, 0.2)  # 魂火在纸上的描边：冷的淡墨蓝


def soul_wisp(P, ctrl, rb):
    """一团魂火（同游戏里的魂火：小泪滴形的冷白鬼火，圆头是亮核，尾巴细长、末梢一甩）。
    ctrl 是从圆头中心到尾梢的贝塞尔控制点（尾巴就是它飞来的路），rb 是圆头半径。"""
    pts = np.asarray(ctrl, dtype=np.float64)
    path = V.bezier(pts, 40)
    h = pts[0]
    u = pts[0] - pts[1]
    u = u / np.hypot(*u)  # 圆头朝着的方向
    tt = np.linspace(0, 1, 40)
    hw = rb * np.interp(tt, [0.0, 0.18, 0.6, 1.0], [1.0, 0.78, 0.36, 0.06])
    g = path[8]
    glow(P, g[0], g[1], 2.4 * rb + 2.5, mixc(SOUL, PAPER, 0.25), 0.55)
    stroke(P, path, hw + 0.7, SOUL_RIM, 0.95, jitter=0.04)
    stroke(P, path, hw, mixc(SOUL, WHITE, 0.2), 1.0, jitter=0.04)
    stroke(P, path[:22], hw[:22] * 0.42, mixc(SOUL, WHITE, 0.75), 0.9, jitter=0.0)
    P.dot(h[0] + u[0] * 0.2 * rb, h[1] + u[1] * 0.2 * rb, 0.62 * rb, WHITE, 0.95)


def sparkle(P: W.Painter, x, y, L, rgb=TENG, hw=0.5, alpha=1.0):
    """四角星芒：横竖两笔，中间粗两头尖。"""
    n = 16
    prof = hw * np.sin(np.pi * np.linspace(0, 1, n)) ** 0.8 + 0.04
    for dx, dy in ((1.0, 0.0), (0.0, 1.0)):
        stroke(P, W.seg_pts((x - dx * L, y - dy * L), (x + dx * L, y + dy * L), n=n), prof, rgb, alpha)


def flame(P: W.Painter, cx, by, h, w, *, lean=0.0, ol=0.8, core=True, stops=None, ol_rgb=None, pool_rgb=None):
    """一朵火苗：底在 (cx, by)，高 h、半宽 w；lean 让火尖往右偏（负数往左）。"""
    pn = [(0.0, 0.0), (-0.7, -0.1), (-1.0, -0.35), (-0.8, -0.6), (-0.35, -0.82), (0.0, -1.0), (0.3, -0.78), (0.8, -0.58), (1.0, -0.33), (0.72, -0.1)]
    pts = [(cx + x * w + lean * (-y) ** 1.6, by + y * h) for x, y in pn]
    heat = np.exp(-(((P.X - cx - 0.3 * lean) / (0.85 * w)) ** 2 + ((P.Y - (by - 0.3 * h)) / (0.5 * h)) ** 2))
    rgb = V.ramp(np.clip(heat * 1.05, 0, 1), V.FLAME_STOPS if stops is None else stops)
    _, m = shape(P, W.catmull_closed(pts, 8), rgb, ol=ol, ol_rgb=mixc(ZHUSHA, JIAO, 0.55) if ol_rgb is None else ol_rgb,
                 pool=0.3, pool_rgb=ZHUSHA if pool_rgb is None else pool_rgb, mottle=0.0, wob=0.03)
    if core:
        cp = [(cx + 0.42 * x * w + 0.55 * lean * (-y) ** 1.6, by - 0.1 * h + 0.45 * y * h) for x, y in pn]
        shape(P, W.catmull_closed(cp, 8), mixc(TENG, WHITE, 0.65), ol=0, pool=0.25, pool_rgb=TENG, mottle=0.0, wob=0.02)
    return m


def coin(P: W.Painter, cx, cy, r, *, ry=None, ol=0.85):
    """铜钱：藤黄圆片、内圈一道细线、方孔。"""
    ry = r if ry is None else ry
    rgb = mixc(mixc(TENG, GOLD_HI, 0.35), mixc(TENG, GOLD_DK, 0.55), smoothstep(cy - ry, cy + ry, P.Y))
    _, m = shape(P, W.ellipse_pts(cx, cy, r, ry, 48), rgb, ol=ol, ol_rgb=mixc(GOLD_DK, JIAO, 0.5), pool=0.4, pool_rgb=GOLD_DK, mottle=0.0, wob=0.02)
    rim = W.ellipse_pts(cx, cy, 0.72 * r, 0.72 * ry, 48)
    stroke(P, V.arc_resample(np.vstack([rim, rim[:1]]), 60), 0.22 * r / 5.0 + 0.12, GOLD_DK, 0.7, clip=m)
    hx, hy = 0.27 * r, 0.27 * ry
    hole = [(cx - hx, cy - hy), (cx + hx, cy - hy), (cx + hx, cy + hy), (cx - hx, cy + hy)]
    shape(P, hole, mixc(NONG, GOLD_DK, 0.3), ol=0.35, ol_rgb=mixc(GOLD_DK, JIAO, 0.5), pool=0.0, mottle=0.0, wob=0.0)
    return m


def leaf(P: W.Painter, cx, cy, ang, L, wd, rgb):
    """一片叶子：杏仁形，中间一道叶脉。"""
    a = math.radians(ang)
    u = np.array([math.cos(a), math.sin(a)])
    base, tip = np.array([cx, cy]) - u * L / 2, np.array([cx, cy]) + u * L / 2
    _, m = shape(P, W.almond(base, tip, wd, 30, bulge=0.45), rgb, ol=0.8, ol_rgb=mixc(rgb, JIAO, 0.6), pool=0.3, pool_rgb=mixc(rgb, JIAO, 0.3), mottle=0.0)
    stroke(P, W.seg_pts(base, tip, n=16), 0.25, mixc(rgb, JIAO, 0.5), 0.8, clip=m)


def paint_ingot(P: W.Painter, cx, cy, s):
    """元宝（与 em_el_metal 同形，按中心 (32, 35) 平移缩放）。"""
    def q(pts):
        return [(cx + s * (x - 32.0), cy + s * (y - 35.0)) for x, y in pts]

    body = W.catmull_closed(q([(13.5, 27.5), (19.5, 33.5), (26.0, 35.3), (38.0, 35.3), (44.5, 33.5), (50.5, 27.5), (48.0, 38.5), (40.0, 45.0), (32.0, 46.5), (24.0, 45.0), (16.0, 38.5)]), 8)
    rgb = mixc(mixc(TENG, GOLD_HI, 0.35), mixc(TENG, GOLD_DK, 0.6), smoothstep(cy - 5 * s, cy + 11 * s, P.Y))
    shape(P, body, rgb, ol=OL * min(1.0, s + 0.25), ol_rgb=mixc(GOLD_DK, JIAO, 0.5), pool=0.45, pool_rgb=GOLD_DK, mottle=0.04)
    stroke(P, V.bezier(q([(14.5, 28.2), (32.0, 23.0), (49.5, 28.2)]), 40), 0.55 * s + 0.1, GOLD_DK, 0.9)
    (dx, dy), = q([(32.0, 31.0)])
    dome = W.ellipse_pts(dx, dy, 8.6 * s, 7.0 * s, 48)
    shape(P, dome, mixc(GOLD_HI, mixc(TENG, GOLD_DK, 0.4), smoothstep(0.1, 1.0, np.hypot((P.X - dx + 3 * s) / (8.6 * s), (P.Y - dy + 3 * s) / (7.0 * s)))),
          ol=1.1 * min(1.0, s + 0.25), ol_rgb=mixc(GOLD_DK, JIAO, 0.5), pool=0.35, pool_rgb=GOLD_DK, mottle=0.0)
    stroke(P, V.bezier(q([(27.0, 30.5), (28.0, 27.2), (31.0, 25.6)]), 20), 0.75 * s * W.brush_profile(20, 0.4, 0.3), WHITE, 0.85)


def chest_icon(P: W.Painter, x0, y0, w, h, dx, dy, *, ol=1.2):
    """宝箱（同 weapon_textures.make_chest 的画法，简化）：朱漆三面、箱盖缝、藤黄压条与包角、圆锁片。"""
    front, top, side, sil = W.box_faces(x0, y0, w, h, dx, dy)
    lac = ZHUSHA
    masks = []
    for poly, rgb in zip((top, front, side), (mixc(lac, PAPER, 0.28), lac, mixc(lac, ZHONG, 0.45))):
        d, _ = P.sdf(W.wobble(poly, P.rng, 0.06, spacing=0.3))
        masks.append(P.cover(d))
        P.fill(d, rgb, mottle=0.08, mottle_rgb=ZHUSHA_DK, pool=0.3, pool_rgb=ZHUSHA_DK, pool_w=0.7)
    stroke(P, V.bezier([(x0 + 0.2 * w, y0 - 0.25 * dy), (x0 + 0.5 * w, y0 - 0.7 * dy), (x0 + 0.8 * w, y0 - 0.85 * dy)], 30), 0.12 * dy * W.brush_profile(30, 0.5, 0.2), mixc(lac, WHITE, 0.55), 0.7, clip=masks[0])
    ys = y0 + 0.34 * h
    bw = max(0.55, 0.06 * h)

    def gold(poly, o=0.5):
        d, t = P.sdf(W.wobble(poly, P.rng, 0.04, spacing=0.25))
        P.fill(d, TENG, pool=0.45, pool_rgb=GOLD_DK, pool_w=0.4)
        P.outline(d, t, o, GOLD_DK)

    gold([(x0, ys - bw), (x0 + w, ys - bw), (x0 + w, ys + bw), (x0, ys + bw)])
    gold([(x0 + w, ys - bw), (x0 + w + dx, ys - dy - bw), (x0 + w + dx, ys - dy + bw), (x0 + w, ys + bw)])
    cw = 0.12 * w
    for xa, xb in ((x0, x0 + cw), (x0 + w - cw, x0 + w)):
        gold([(xa, y0), (xb, y0), (xb, y0 + h), (xa, y0 + h)])
    lx, ly, lr = x0 + w / 2, ys + 0.12 * h, 0.17 * h
    d, t = P.sdf(W.ellipse_pts(lx, ly, lr, lr, 40))
    P.fill(d, mixc(TENG, GOLD_HI, smoothstep(lr, -lr, P.Y - ly)), pool=0.5, pool_rgb=GOLD_DK, pool_w=0.5)
    P.outline(d, t, 0.55, GOLD_DK)
    P.dot(lx, ly + 0.15 * lr, 0.3 * lr, JIAO, ry=0.45 * lr)
    d, t = P.sdf(W.wobble(sil, P.rng, 0.06, spacing=0.3))
    P.outline(d, t, ol, INK_LINE, jitter=0.25)
    stroke(P, W.seg_pts((x0, y0), (x0 + w, y0), (x0 + w + dx, y0 - dy), n=50), 0.35, JIAO)
    stroke(P, W.seg_pts((x0 + w, y0), (x0 + w, y0 + h), n=30), 0.35, JIAO)


def heart_pts(cx, cy, s, n=160):
    t = np.linspace(0, 2 * math.pi, n, endpoint=False)
    x = 16 * np.sin(t) ** 3
    y = -(13 * np.cos(t) - 5 * np.cos(2 * t) - 2 * np.cos(3 * t) - np.cos(4 * t))
    return np.stack([cx + s * x, cy + s * (y - 2.5)], -1)


# ---------------------------------------------------------------- 补给

def em_lotus(P):
    """莲子：三片粉白莲瓣托着一只石绿莲蓬，蓬面七粒莲子，下接一段莲茎。"""
    stroke(P, V.bezier([(32.5, 40.0), (33.0, 46.0), (37.0, 51.0)], 30), np.linspace(1.7, 1.2, 30), mixc(SHILV, JIAO, 0.45))
    white, pink, tip_c = mixc(PAPER, WHITE, 0.7), mixc(W_ZHUSHA, PAPER, 0.05), mixc(W_ZHUSHA, ZHUSHA, 0.45)
    for base, tip, wd, asym in (((32.0, 30.0), (32.0, 10.0), 12.5, 0.0), ((28.5, 38.0), (13.0, 25.5), 12.0, 0.12), ((35.5, 38.0), (51.0, 25.5), 12.0, -0.12)):
        b, t = np.asarray(base), np.asarray(tip)
        along = ((P.X - b[0]) * (t[0] - b[0]) + (P.Y - b[1]) * (t[1] - b[1])) / ((t[0] - b[0]) ** 2 + (t[1] - b[1]) ** 2)
        rgb = mixc(mixc(white, pink, smoothstep(0.2, 0.8, along)), tip_c, smoothstep(0.75, 1.0, along))
        _, m = shape(P, W.almond(base, tip, wd, 48, bulge=0.5, asym=asym), rgb, ol=OL, ol_rgb=mixc(ZHUSHA_DK, JIAO, 0.45), pool=0.2, pool_rgb=tip_c, mottle=0.0)
        stroke(P, W.seg_pts(b + (t - b) * 0.35, b + (t - b) * 0.85, n=20), 0.32, mixc(W_ZHUSHA, ZHUSHA, 0.35), 0.6, clip=m)
    body = W.catmull_closed([(19.8, 26.0), (21.8, 32.5), (26.5, 38.5), (32.0, 40.8), (37.5, 38.5), (42.2, 32.5), (44.2, 26.0), (39.0, 21.0), (32.0, 20.0), (25.0, 21.0)], 8)
    shape(P, body, shade_lr(P, 20, 44, mixc(W_SHILV, EL_INK["wood"], 0.4), mixc(SHILV, JIAO, 0.35)), ol=OL, ol_rgb=mixc(SHILV, JIAO, 0.7), pool=0.3, pool_rgb=mixc(SHILV, JIAO, 0.4), mottle=0.06)
    _, m = shape(P, W.ellipse_pts(32.0, 25.0, 12.2, 4.8, 64), mixc(mixc(W_SHILV, TENG, 0.15), PAPER, 0.25), ol=1.0, ol_rgb=mixc(SHILV, JIAO, 0.6), pool=0.35, pool_rgb=SHILV, mottle=0.04)
    seeds = [(32.0, 25.0)] + [(32.0 + 7.4 * math.cos(a), 25.0 + 2.8 * math.sin(a)) for a in np.linspace(0, 2 * math.pi, 7)[:-1] + 0.3]
    for x, y in seeds:
        P.dot(x, y + 0.2, 1.8, mixc(SHILV, JIAO, 0.55), ry=1.3, clip=m)
        P.dot(x - 0.25, y - 0.1, 1.15, mixc(mixc(W_SHILV, TENG, 0.3), WHITE, 0.35), ry=0.85, clip=m)


def em_oil(P):
    """灯油：一大滴琥珀色的灯油，滴尖上燃着一朵小火苗。挨着数字显示，所以只有两大块：油滴、火苗。"""
    glow(P, 32.0, 37.0, 17.0, mixc(TENG, PAPER, 0.4), 0.5)
    cx, cy, R, tip = 32.0, 40.0, 11.2, 19.5  # 底下一个圆，滴尖到圆的两条切线
    half = math.asin(R / (cy - tip))
    arc = np.linspace(-0.5 * math.pi + (0.5 * math.pi - half), 1.5 * math.pi - (0.5 * math.pi - half), 60)
    drop = np.vstack([[(cx, tip)], np.stack([cx + R * np.cos(arc), cy + R * np.sin(arc)], -1)])
    rr = np.hypot((P.X - 28.5) / 12.0, (P.Y - 35.0) / 13.0)
    rgb = mixc(mixc(TENG, WHITE, 0.5), mixc(TENG, ZHESHI, 0.5), smoothstep(0.1, 0.75, rr))
    rgb = mixc(rgb, mixc(ZHESHI, JIAO, 0.3), smoothstep(0.75, 1.4, rr))
    _, m = shape(P, drop, rgb, ol=OL * 1.25, ol_rgb=mixc(ZHESHI, JIAO, 0.65), pool=0.4, pool_rgb=mixc(ZHESHI, JIAO, 0.25), mottle=0.0, wob=0.03)
    stroke(P, V.bezier([(25.5, 45.0), (23.8, 39.5), (26.0, 33.0)], 30), 1.15 * W.brush_profile(30, 0.4, 0.3), WHITE, 0.9, clip=m)
    P.dot(27.8, 30.0, 0.9, WHITE, clip=m)
    flame(P, 32.2, 20.5, 11.0, 3.6, lean=0.8)


# ---------------------------------------------------------------- 心灯

def em_meta_dmg(P):
    """锋芒：一枚矛头斜指右上，刃面一亮一暗、一线刃光，锋尖一点金芒；銎下一簇朱缨。"""
    fr = Fr(29.0, 35.0, -45.0, 1.0)
    stroke(P, fr(W.seg_pts((-18.5, 0.0), (-8.0, 0.0), n=20)), 1.5, mixc(ZHESHI, NONG, 0.45))
    root = fr.pt(-8.5, 0.0)
    for k, (ang, L) in enumerate(((148, 9.5), (163, 11.5), (180, 12.0), (197, 11.5), (212, 9.5), (172, 9.5), (189, 9.5))):
        a = math.radians(ang)
        tip = fr.pt(-8.5 + L * math.cos(a), L * math.sin(a))
        mid = fr.pt(-8.5 + 0.55 * L * math.cos(a), 0.45 * L * math.sin(a))
        stroke(P, V.bezier([root, mid, tip], 24), 1.2 * W.brush_profile(24, 1.0, 0.2, 0.0), ZHUSHA if k % 2 == 0 else mixc(ZHUSHA, ZHUSHA_DK, 0.5), dry=0.25, dry_start=0.55)
    P.dot(*root, 1.7, ZHUSHA_DK)
    shape(P, fr([(-9.0, -2.1), (-2.5, -1.7), (-2.5, 1.7), (-9.0, 2.1)]), mixc(mixc(ZHESHI, NONG, 0.3), SHILV, 0.15), ol=0.9, pool=0.3)
    stroke(P, fr(W.seg_pts((-6.8, -2.3), (-6.8, 2.3), n=10)), 0.45, mixc(TENG, GOLD_DK, 0.3))
    blade = fr(W.seg_pts((-3.0, -1.8), (0.5, -5.2), (4.0, -6.4), (13.0, -3.3), (22.0, 0.0), (13.0, 3.3), (4.0, 6.4), (0.5, 5.2), (-3.0, 1.8), n=120))
    _, Vv = fr.uv(P)
    d, t = P.sdf(W.wobble(blade, P.rng, 0.03, spacing=0.3))
    steel_hi = mixc(mixc(PAPER, WHITE, 0.6), QING, 0.15)
    steel_lo = mixc(mixc(QING, HUAQING, 0.4), ZHONG, 0.45)
    P.fill(d, mixc(steel_hi, steel_lo, smoothstep(-0.2, 0.2, Vv)), pool=0.25, pool_rgb=mixc(HUAQING, JIAO, 0.4), pool_w=0.6)
    m = P.cover(d)
    stroke(P, fr(W.seg_pts((-2.5, 0.0), (20.5, 0.0), n=30)), 0.45, mixc(HUAQING, JIAO, 0.5), 0.9, clip=m)
    stroke(P, fr(W.seg_pts((1.5, -4.4), (5.0, -5.2), (16.0, -2.0), n=30)), 0.5, WHITE, 0.95, clip=m)
    P.outline(d, t, OL * 1.15, INK_LINE, jitter=0.15)
    tx, ty = fr.pt(21.0, 0.0)
    glow(P, tx, ty, 6.5, mixc(TENG, WHITE, 0.5), 0.8)
    sparkle(P, tx, ty, 5.2, mixc(TENG, WHITE, 0.2), 0.75)
    P.dot(tx, ty, 0.9, WHITE)


def em_meta_hp(P):
    """体魄：一枚心形翡翠佩，玉色上亮下深、浮雕一道内心线，顶上系朱砂绳结。"""
    loop = V.bezier([(30.2, 29.0), (25.5, 16.0), (38.5, 16.0), (33.8, 29.0)], 50)
    stroke(P, loop, 0.8, ZHUSHA)
    shape(P, W.catmull_closed([(32.0, 14.0), (34.6, 16.6), (32.0, 19.2), (29.4, 16.6)], 6), ZHUSHA, ol=0.6, ol_rgb=ZHUSHA_DK, pool=0.3, pool_rgb=ZHUSHA_DK)
    for sx in (-1.0, 1.0):
        stroke(P, V.bezier([(32.0 + 0.8 * sx, 13.8), (32.0 + 2.2 * sx, 11.8), (32.0 + 4.0 * sx, 11.0)], 16), 0.55 * W.brush_profile(16, 1.0, 0.3, 0.0), ZHUSHA)
    jade_l = mixc(mixc(SHILV, WHITE, 0.5), W_SHILV, 0.2)
    jade_m = mixc(SHILV, EL_INK["wood"], 0.4)
    jade_d = mixc(mixc(SHILV, HUAQING, 0.35), JIAO, 0.3)
    rr = np.hypot((P.X - 26.5) / 13.0, (P.Y - 28.0) / 13.0)
    rgb = mixc(mixc(jade_l, jade_m, smoothstep(0.0, 0.7, rr)), jade_d, smoothstep(0.7, 1.5, rr))
    _, m = shape(P, heart_pts(32.0, 35.0, 0.82), rgb, ol=OL * 1.1, ol_rgb=mixc(SHILV, JIAO, 0.7), pool=0.35, pool_rgb=jade_d, mottle=0.08, mottle_rgb=mixc(SHILV, WHITE, 0.4))
    inner = heart_pts(32.0, 35.8, 0.5)
    stroke(P, V.arc_resample(np.vstack([inner, inner[:1]]), 160), 0.5, mixc(SHILV, JIAO, 0.45), 0.75, clip=m)
    stroke(P, V.bezier([(21.0, 33.5), (20.5, 27.5), (25.0, 24.5)], 30), 1.1 * W.brush_profile(30, 0.4, 0.3), WHITE, 0.85, clip=m)
    P.dot(38.0, 27.5, 0.9, WHITE, 0.8, clip=m)
    P.dot(32.0, 29.6, 1.0, mixc(SHILV, JIAO, 0.6))


def em_meta_agi(P):
    """灵巧：一只燕子斜掠向右上，镰刀似的双翅、剪刀尾，喉间一点朱红，身后两道疾风。"""
    fr = Fr(31.5, 32.0, -28.0, 0.88)
    body_c = mixc(NONG, HUAQING, 0.3)
    for v0, L, al in ((-3.5, 10.0, 0.7), (4.0, 8.0, 0.6)):
        stroke(P, fr(W.seg_pts((-11.0, v0), (-11.0 - L, v0 + 0.4), n=20)), np.linspace(0.9, 0.15, 20), mixc(HUAQING, DAN, 0.4), al, dry=0.4, dry_start=0.3)
    for sgn in (-1.0, 1.0):
        tail = fr(V.bezier([(-7.0, 0.9 * sgn), (-13.0, 2.0 * sgn), (-18.0, 4.2 * sgn), (-23.0, 6.8 * sgn)], 30))
        stroke(P, tail, np.interp(np.linspace(0, 1, 30), [0, 0.5, 1], [1.7, 0.95, 0.15]), body_c)
    for sgn in (-1.0, 1.0):
        lead = V.bezier([(3.0, 1.8 * sgn), (5.8, 9.0 * sgn), (1.5, 17.0 * sgn), (-7.5, 22.5 * sgn)], 40)
        trail = V.bezier([(-7.5, 22.5 * sgn), (-3.5, 15.0 * sgn), (-2.8, 8.0 * sgn), (-5.0, 2.2 * sgn)], 40)
        _, Vv = fr.uv(P)
        rgb = mixc(mixc(body_c, HUAQING, 0.3), mixc(body_c, JIAO, 0.4), smoothstep(4.0, 20.0, np.abs(Vv)))
        _, m = shape(P, fr(np.vstack([lead, trail[1:-1]])), rgb, ol=OL, ol_rgb=JIAO, pool=0.3, pool_rgb=JIAO, mottle=0.05)
        for f in (0.35, 0.6):
            stroke(P, fr(V.bezier([(1.0, (3.0 + 3.0 * f) * sgn), (-1.0, (10.0 + 5.0 * f) * sgn), (-5.0 - 2.0 * f, (17.0 + 3.0 * f) * sgn)], 20)), 0.3, mixc(HUAQING, QING, 0.4), 0.55, clip=m)
    _, m = shape(P, fr(W.almond((-9.5, 0.0), (6.5, 0.0), 8.2, 40, bulge=0.6)), body_c, ol=OL, ol_rgb=JIAO, pool=0.3, pool_rgb=JIAO)
    P.dot(*fr.pt(1.5, 2.0), 2.2, mixc(PAPER, WHITE, 0.6), ry=1.2, clip=m)
    shape(P, fr(W.ellipse_pts(7.4, 0.0, 3.9, 3.5, 40)), mixc(NONG, JIAO, 0.4), ol=0.9, ol_rgb=JIAO, pool=0.2)
    shape(P, fr([(10.6, -1.0), (13.4, 0.1), (10.6, 1.0)]), JIAO, ol=0.4, wob=0.0)
    P.dot(*fr.pt(9.6, 1.6), 1.25, ZHUSHA)
    P.dot(*fr.pt(8.6, -1.3), 0.6, WHITE)


def em_meta_luck(P):
    """气运：一尾锦鲤斜身跃起（鲤跃），身子微弓：朱红兑藤黄的背、白腹，背鳍、胸鳍、大尾鳍白里透红，口边吐两个泡。
    鱼先按直的设计（u 沿身长，头在 +u；v 向腹部为正），再整条弯到一段圆弧上。"""
    t = np.array([math.cos(math.radians(-48.0)), math.sin(math.radians(-48.0))])
    n = np.array([-t[1], t[0]])  # 指向腹侧（右下）
    c0, R = np.array([29.0, 30.5]), 24.0
    ctr = c0 + n * R

    def bend(pts):
        p = np.asarray(pts, dtype=np.float64).reshape(-1, 2)
        a = p[:, 0] / R
        rr = R - p[:, 1]
        return ctr[None, :] + rr[:, None] * (-np.cos(a)[:, None] * n[None, :] + np.sin(a)[:, None] * t[None, :])

    q = np.stack([P.X - ctr[0], P.Y - ctr[1]], -1)
    Vv = R - np.hypot(q[..., 0], q[..., 1])
    fin_c = mixc(PAPER, WHITE, 0.6)
    fin_ol = mixc(ZHUSHA_DK, JIAO, 0.45)
    # 尾鳍：两叶张开，中间一个分叉
    tail = W.catmull_closed([(-10.5, -1.6), (-16.0, -5.0), (-21.5, -8.6), (-19.0, -2.2), (-16.6, 0.0), (-19.0, 2.4), (-21.0, 9.0), (-15.5, 5.2), (-10.5, 1.6)], 8)
    _, m = shape(P, bend(tail), mixc(fin_c, W_ZHUSHA, 0.45), ol=1.0, ol_rgb=fin_ol, pool=0.35, pool_rgb=mixc(W_ZHUSHA, ZHUSHA, 0.4), mottle=0.0)
    for vv in (-5.5, -2.5, 2.5, 5.5):
        stroke(P, bend(W.seg_pts((-11.5, 0.2 * vv), (-18.5, vv), n=12)), 0.25, ZHUSHA, 0.55, clip=m)
    # 背鳍、腹鳍
    dorsal = [(-6.0, -4.6), (-2.0, -9.6), (5.0, -9.0), (6.5, -6.0)]
    shape(P, bend(W.catmull_closed(dorsal, 8)), mixc(fin_c, W_ZHUSHA, 0.35), ol=0.85, ol_rgb=fin_ol, pool=0.3, pool_rgb=W_ZHUSHA, mottle=0.0)
    for (u0, u1, v1) in ((6.0, 1.5, 9.5), (-3.0, -7.0, 7.5)):
        shape(P, bend(W.almond((u0, 4.0), (u1, v1), 3.2, 20, bulge=0.35)), mixc(fin_c, W_ZHUSHA, 0.3), ol=0.75, ol_rgb=fin_ol, pool=0.25, pool_rgb=W_ZHUSHA)
    # 身
    us = np.linspace(-12.0, 15.0, 60)
    hw = np.interp(us, [-12.0, -9.0, -3.0, 5.0, 11.0, 13.5, 15.0], [1.7, 2.9, 5.5, 6.6, 5.2, 3.6, 0.6])
    body = bend([(u, -h) for u, h in zip(us, hw)] + [(u, h) for u, h in zip(us[::-1], hw[::-1])][1:-1])
    koi = mixc(ZHUSHA, TENG, 0.3)
    rgb = mixc(mixc(koi, ZHUSHA_DK, 0.2), mixc(PAPER, WHITE, 0.6), smoothstep(0.5, 4.5, Vv))
    _, m = shape(P, body, rgb, ol=OL, ol_rgb=mixc(ZHUSHA_DK, JIAO, 0.55), pool=0.25, pool_rgb=ZHUSHA_DK, mottle=0.06, mottle_rgb=ZHUSHA_DK)
    for (u, v) in ((-6.0, -2.2), (-1.5, -3.0), (3.0, -3.2), (-3.5, 0.6), (1.0, 0.2)):
        a = np.linspace(-1.1, 1.1, 10)
        stroke(P, bend(np.stack([u - 1.1 * np.cos(a), v + 1.4 * np.sin(a)], -1)), 0.26, mixc(TENG, GOLD_HI, 0.45), 0.75, clip=m)
    stroke(P, bend(V.bezier([(9.0, -4.6), (7.6, 0.0), (9.0, 4.4)], 20)), 0.4, mixc(ZHUSHA_DK, JIAO, 0.3), 0.8, clip=m)
    ex, ey = bend([(11.6, -1.6)])[0]
    P.dot(ex, ey, 1.45, JIAO)
    P.dot(ex - 0.45, ey - 0.45, 0.5, WHITE)
    for vv in (-0.8, 1.6):
        stroke(P, bend(V.bezier([(14.6, vv), (16.4, vv + 0.6 * np.sign(vv)), (17.6, vv + 2.4 * np.sign(vv))], 12)), 0.24, mixc(ZHUSHA_DK, JIAO, 0.3), 0.85)
    for (u, v, r) in ((18.5, -4.5, 1.5), (21.0, -8.5, 1.05)):
        bx, by = bend([(u, v)])[0]
        bub = W.ellipse_pts(bx, by, r, r, 24)
        stroke(P, V.arc_resample(np.vstack([bub, bub[:1]]), 30), 0.32, mixc(HUAQING, DAN, 0.3), 0.85)


# ---------------------------------------------------------------- 奇遇

def em_enc_toad(P):
    """金蟾：三足金蟾蹲坐，鼓眼、阔口衔一枚铜钱，背上疙瘩点点；身后伸出第三条腿。"""
    gold_l, gold_d = mixc(TENG, GOLD_HI, 0.35), mixc(TENG, GOLD_DK, 0.6)
    ol_c = mixc(GOLD_DK, JIAO, 0.55)
    shape(P, W.catmull_closed([(40.0, 41.0), (47.5, 39.5), (51.0, 45.0), (47.0, 47.6), (41.5, 46.5)], 6), gold_d, ol=1.0, ol_rgb=ol_c, pool=0.3, pool_rgb=GOLD_DK)
    for x in (47.0, 49.5):
        stroke(P, W.seg_pts((x, 46.5), (x + 1.2, 48.3), n=8), 0.4, ol_c)
    body = W.catmull_closed([(16.5, 40.0), (18.5, 31.0), (24.0, 25.5), (32.0, 24.0), (40.0, 25.5), (45.5, 31.0), (47.5, 40.0), (42.0, 46.5), (32.0, 48.0), (22.0, 46.5)], 8)
    rgb = mixc(gold_l, gold_d, smoothstep(24.0, 50.0, P.Y + 0.4 * (P.X - 32.0)))
    _, m = shape(P, body, rgb, ol=OL * 1.15, ol_rgb=ol_c, pool=0.4, pool_rgb=GOLD_DK, mottle=0.1, mottle_rgb=GOLD_DK)
    for (x, y, r) in ((23.5, 33.5, 1.2), (40.5, 33.5, 1.2), (28.0, 30.5, 1.0), (36.0, 30.5, 1.0), (20.5, 39.0, 1.0), (43.5, 39.0, 1.0), (32.0, 29.0, 0.9)):
        P.dot(x, y, r, GOLD_DK, 0.85, clip=m)
        P.dot(x - 0.3 * r, y - 0.3 * r, 0.4 * r, GOLD_HI, clip=m)
    for ex in (24.0, 40.0):
        _, m2 = shape(P, W.ellipse_pts(ex, 25.0, 4.6, 4.2, 40), gold_l, ol=1.05, ol_rgb=ol_c, pool=0.3, pool_rgb=GOLD_DK)
        P.dot(ex, 25.5, 2.8, mixc(TENG, WHITE, 0.45), clip=m2)
        P.dot(ex + 0.3, 25.7, 1.8, JIAO, ry=1.1)
        P.dot(ex - 0.6, 24.9, 0.6, WHITE)
    stroke(P, V.bezier([(20.5, 36.5), (32.0, 41.5), (43.5, 36.5)], 40), 0.7, ol_c)
    for sx in (-1.0, 1.0):
        x0 = 32.0 + sx * 12.5
        foot = W.catmull_closed([(x0 - 2.6, 41.0), (x0 + 2.6, 41.0), (x0 + 4.0, 46.8), (x0 + 1.4, 48.6), (x0 - 1.4, 48.6), (x0 - 4.0, 46.8)], 6)
        shape(P, foot, gold_d, ol=1.0, ol_rgb=ol_c, pool=0.3, pool_rgb=GOLD_DK)
        for dx_ in (-1.4, 1.4):
            stroke(P, W.seg_pts((x0 + dx_, 46.0), (x0 + 1.6 * dx_, 48.4), n=8), 0.35, ol_c)
    coin(P, 32.0, 41.5, 5.6)


def em_enc_spring(P):
    """灵泉：一圈山石围着一汪青碧的泉水，泉眼涌起一股水柱，水花四落，涟漪荡开，上方几点灵光。"""
    wat = ACC_INK["spring"]
    wat_l, wat_d = mixc(wat, WHITE, 0.55), mixc(wat, mixc(HUAQING, JIAO, 0.45), 0.55)
    stone = mixc(DAN, W_ZHESHI, 0.25)
    shape(P, W.ellipse_pts(32.0, 40.5, 20.0, 9.4, 80), shade_lr(P, 12, 52, mixc(stone, PAPER, 0.25), mixc(stone, JIAO, 0.35)), ol=OL, pool=0.3, pool_rgb=JIAO, mottle=0.12)
    for a in np.linspace(0, 2 * math.pi, 10, endpoint=False) + 0.2:
        x, y = 32.0 + 18.2 * math.cos(a), 40.5 + 8.2 * math.sin(a)
        stroke(P, V.bezier([(x - 2.2, y + 0.6), (x, y - 1.6), (x + 2.2, y + 0.6)], 12), 0.45, NONG, 0.75)
    pool = W.ellipse_pts(32.0, 40.0, 15.6, 6.2, 80)
    _, m = shape(P, pool, mixc(wat_l, wat, smoothstep(34.5, 45.0, P.Y)), ol=1.0, ol_rgb=wat_d, pool=0.4, pool_rgb=wat_d, mottle=0.0)
    for rx, ry in ((6.0, 2.3), (11.0, 4.3)):
        rp = W.ellipse_pts(32.0, 40.6, rx, ry, 60)
        stroke(P, V.arc_resample(np.vstack([rp, rp[:1]]), 80), 0.45, WHITE, 0.85, clip=m)
    jet = V.bezier([(32.0, 40.0), (31.4, 31.0), (32.4, 21.5)], 30)
    stroke(P, jet, np.linspace(3.2, 2.0, 30), wat_d)
    stroke(P, jet, np.linspace(2.4, 1.3, 30), wat_l)
    stroke(P, jet[:24], 0.5, WHITE, 0.9)
    for sx in (-1.0, 1.0):
        arc = V.bezier([(32.2, 21.5), (32.2 + 6.0 * sx, 14.5), (32.2 + 10.5 * sx, 25.0)], 30)
        stroke(P, arc, 1.25 * W.brush_profile(30, 1.0, 0.3, 0.0), wat_d)
        stroke(P, arc, 0.6 * W.brush_profile(30, 1.0, 0.3, 0.0), wat_l)
        for (dx_, dy_, r) in ((11.5, 29.0, 0.9), (8.0, 31.5, 0.7)):
            P.dot(32.2 + dx_ * sx, dy_, r, wat_d)
    for (x, y, L) in ((19.0, 18.0, 2.6), (45.5, 15.5, 2.2), (41.0, 10.8, 1.6)):
        sparkle(P, x, y, L, mixc(wat, WHITE, 0.2), 0.55)


def em_enc_shrine(P):
    """古灯：石柱上一盏青铜古灯，灯盏里火苗正旺，四周一团暖光。"""
    glow(P, 33.0, 22.0, 15.0, mixc(col(S.FLAME_LIGHT), PAPER, 0.25), 0.75)
    stone = mixc(DAN, W_ZHESHI, 0.3)
    paint_box(P, 21.0, 47.5, 20.0, 4.0, 3.5, 2.5, mixc(stone, ZHONG, 0.25), ol=1.1)
    masks = paint_box(P, 27.0, 36.0, 9.0, 11.5, 2.5, 2.0, stone, ol=1.15)
    for (x0, y0) in ((28.5, 39.0), (29.5, 43.0)):
        stroke(P, W.seg_pts((x0, y0), (x0 + 2.5, y0 + 1.5), n=10), 0.45, ZHONG, 0.7, clip=masks[1], dry=0.4, dry_start=0.2)
    paint_box(P, 23.0, 33.0, 17.0, 3.0, 3.5, 2.5, mixc(stone, PAPER, 0.15), ol=1.1)
    bx, by = 33.2, 31.4
    bronze = mixc(mixc(ZHESHI, NONG, 0.35), SHILV, 0.2)
    shape(P, [(bx - 1.3, by - 3.0), (bx + 1.3, by - 3.0), (bx + 2.2, by + 0.4), (bx - 2.2, by + 0.4)], mixc(bronze, JIAO, 0.2), ol=0.8, wob=0.02)
    bowl = W.catmull_closed([(bx - 7.2, by - 6.8), (bx + 7.2, by - 6.8), (bx + 5.0, by - 3.6), (bx, by - 2.6), (bx - 5.0, by - 3.6)], 8)
    shape(P, bowl, shade_lr(P, bx - 7, bx + 7, mixc(bronze, GOLD_HI, 0.3), mixc(bronze, JIAO, 0.35)), ol=1.0, pool=0.3)
    shape(P, W.ellipse_pts(bx, by - 6.8, 7.0, 1.5, 40), mixc(NONG, ZHESHI, 0.2), ol=0.7, pool=0.0, wob=0.02)
    stroke(P, W.seg_pts((bx - 6.5, by - 5.3), (bx + 6.5, by - 5.3), n=20), 0.35, mixc(TENG, GOLD_DK, 0.3), 0.8)
    flame(P, bx, by - 7.0, 12.5, 4.2, lean=0.6)


def em_enc_altar(P):
    """血祭坛：两层石台，台面一汪血红的池，血顺着台沿淌下；下层台角两支短烛。"""
    red = ACC_INK["altar"]
    glow(P, 32.5, 27.0, 15.0, mixc(red, PAPER, 0.35), 0.6)
    stone_d = mixc(ZHONG, DAN, 0.2)
    paint_box(P, 13.5, 42.0, 32.0, 7.0, 5.0, 3.5, mixc(stone_d, PAPER, 0.12), ol=1.2)
    masks = paint_box(P, 18.0, 33.5, 23.0, 8.5, 6.0, 9.0, stone_d, ol=1.25)
    stroke(P, V.bezier([(21.5, 38.0), (29.5, 36.0), (37.5, 38.0)], 30), 0.5, mixc(ZHUSHA, ZHONG, 0.3), 0.7, clip=masks[1])
    blood = mixc(ZHUSHA, mixc(red, ZHUSHA_DK, 0.4), 0.5)
    pool = W.catmull_closed([(21.5, 31.0), (25.0, 27.0), (33.0, 25.6), (41.5, 26.0), (43.5, 28.6), (40.0, 31.6), (31.0, 32.4)], 8)
    rr = np.hypot((P.X - 30.0) / 9.0, (P.Y - 27.5) / 3.5)
    _, m = shape(P, pool, mixc(mixc(red, WHITE, 0.2), blood, smoothstep(0.2, 1.2, rr)), ol=0.9, ol_rgb=ZHUSHA_DK, pool=0.45, pool_rgb=ZHUSHA_DK, mottle=0.0)
    stroke(P, V.bezier([(25.5, 28.6), (30.5, 27.0), (36.5, 27.4)], 20), 0.55 * W.brush_profile(20, 0.4, 0.3), WHITE, 0.85, clip=m)
    rp = W.ellipse_pts(35.5, 29.3, 3.0, 0.9, 30)
    stroke(P, V.arc_resample(np.vstack([rp, rp[:1]]), 40), 0.25, mixc(red, WHITE, 0.45), 0.8, clip=m)
    for (x, L) in ((22.5, 5.0), (27.5, 7.5), (35.0, 4.0)):
        stroke(P, W.seg_pts((x, 32.6), (x + 0.2, 33.4 + L), n=16), np.linspace(1.1, 0.75, 16), blood)
        P.dot(x + 0.2, 33.5 + L, 1.0, blood)
    for (x, y) in ((17.5, 41.5), (45.5, 39.5)):
        shape(P, [(x - 1.3, y - 5.0), (x + 1.3, y - 5.0), (x + 1.3, y), (x - 1.3, y)], mixc(PAPER, WHITE, 0.4), ol=0.7, pool=0.2, pool_rgb=QING, wob=0.02)
        flame(P, x, y - 5.0, 4.6, 1.5, ol=0.5, core=False)


def em_enc_rift(P):
    """妖潮裂隙：一片地面被撕开一道锯齿形的裂口，口里透出紫红的妖光，碎石和妖火往上飞。"""
    pur = ACC_INK["rift"]
    ground = W.catmull_closed([(11.5, 41.0), (16.0, 35.5), (26.0, 33.0), (38.0, 32.5), (48.0, 34.5), (52.5, 39.5), (48.0, 45.5), (36.0, 48.0), (24.0, 47.5), (15.0, 45.5)], 8)
    rg = np.exp(-(((P.X - 32.0) / 15.0) ** 2 + ((P.Y - 30.0) / 12.0) ** 2))
    P.lay.over(mixc(pur, PAPER, 0.3), 0.65 * rg)
    d, m = shape(P, ground, shade_lr(P, 12.0, 52.0, mixc(mixc(W_ZHESHI, DAN, 0.6), PAPER, 0.1), mixc(ZHESHI, ZHONG, 0.55)), ol=0, pool=0.35, pool_rgb=ZHONG, mottle=0.14)
    for ctrl in (((21.0, 41.0), (19.0, 44.5), (16.5, 45.0)), ((31.0, 41.0), (32.5, 44.5), (30.5, 47.0)), ((41.0, 39.0), (44.0, 42.5), (47.5, 43.0)), ((26.5, 37.6), (25.0, 35.0), (21.5, 34.6)), ((36.5, 36.6), (38.5, 34.0), (42.0, 33.6))):
        stroke(P, V.bezier(list(ctrl), 16), np.linspace(0.7, 0.15, 16), JIAO, 0.9, clip=m)
    d2, t = P.sdf(W.wobble(ground, P.rng, 0.06, spacing=0.3))
    P.outline(d2, t, 1.2, JIAO, jitter=0.3, dry=0.3)
    cl = np.array([(12.5, 41.5), (17.5, 38.2), (21.0, 41.8), (26.5, 37.4), (31.0, 41.4), (36.5, 36.4), (41.0, 39.6), (46.5, 35.8), (51.5, 38.0)])
    cl = V.arc_resample(cl, 160)
    s = np.linspace(0, 1, 160)
    hw = 0.35 + 4.3 * np.sin(np.pi * s) ** 0.8
    d, t = P.sdf(W.ribbon(cl, hw))
    P.fill(d, mixc(RIFT_HOT, WHITE, 0.8), pool=1.0, pool_rgb=mixc(pur, RIFT_HOT, 0.35), pool_w=1.5)
    P.outline(d, t, OL, mixc(pur, JIAO, 0.65), jitter=0.2)
    stroke(P, cl[20:140], 0.2 + 0.7 * np.sin(np.pi * np.linspace(0, 1, 120)), WHITE, 0.95)
    flame(P, 25.0, 38.5, 12.0, 3.0, lean=-0.8, stops=PURPLE_STOPS, ol_rgb=mixc(pur, JIAO, 0.55), pool_rgb=pur, core=False)
    flame(P, 37.0, 36.5, 17.0, 3.8, lean=0.9, stops=PURPLE_STOPS, ol_rgb=mixc(pur, JIAO, 0.55), pool_rgb=pur, core=False)
    for (x, y, r, a) in ((17.5, 28.5, 2.3, 20), (46.5, 25.5, 2.0, -30), (29.0, 17.0, 1.6, 50)):
        pts = W.ellipse_pts(x, y, r, r * 0.75, 5, a0=math.radians(a))
        shape(P, pts, mixc(ZHONG, NONG, 0.5), ol=0.7, ol_rgb=JIAO, pool=0.0, wob=0.0)


# ---------------------------------------------------------------- 古灯增益

def em_buff_fury(P):
    """灯焰：一团怒焰，五条火舌尖利、向右上翻卷，焦墨兑朱砂的外焰、橙焰、白热的芯，四周迸出火星。"""
    outer = [(32.0, 50.5), (22.5, 47.0), (17.5, 39.0), (18.5, 30.0), (14.0, 22.5), (21.5, 25.0), (23.5, 18.0), (21.5, 10.5), (29.0, 16.0),
             (34.0, 8.0), (36.0, 16.5), (39.5, 19.5), (46.0, 12.5), (45.0, 22.0), (50.0, 26.5), (47.0, 33.5), (46.5, 42.0), (41.0, 48.0)]
    cxy = np.array([32.5, 44.0])

    def scaled(k):
        return [tuple(cxy + (np.array(p) - cxy) * k) for p in outer]

    shape(P, W.catmull_closed(outer, 6), mixc(ZHUSHA, ZHUSHA_DK, 0.25), ol=OL * 1.1, ol_rgb=mixc(ZHUSHA_DK, JIAO, 0.6), pool=0.4, pool_rgb=mixc(ZHUSHA_DK, JIAO, 0.3), mottle=0.06, mottle_rgb=ZHUSHA_DK, wob=0.05)
    shape(P, W.catmull_closed(scaled(0.7), 6), mixc(ZHUSHA, col(S.FLAME_LIGHT), 0.65), ol=0, pool=0.3, pool_rgb=ZHUSHA, mottle=0.0, wob=0.04)
    shape(P, W.catmull_closed(scaled(0.4), 6), mixc(TENG, WHITE, 0.55), ol=0, pool=0.3, pool_rgb=TENG, mottle=0.0, wob=0.03)
    for (x, y, r) in ((50.0, 16.5, 0.9), (13.5, 31.0, 0.75), (40.0, 9.5, 0.7), (52.0, 34.0, 0.6), (17.0, 15.0, 0.6)):
        P.dot(x, y, r, mixc(ZHUSHA, TENG, 0.4))


def em_buff_swift(P):
    """御风：一笔从里向外卷出的旋风，甩出长长的风尾，上下两道细风相随，一片绿叶被卷着走。"""
    ink = mixc(EL_INK["wood"], JIAO, 0.55)
    cx, cy = 35.5, 28.0
    th = np.linspace(0.0, 1.75 * math.pi, 140)
    r = 1.2 + 9.6 * th / th[-1]
    a = th - 1.25 * math.pi
    spiral = np.stack([cx + r * np.cos(a), cy + r * np.sin(a)], -1)
    end = spiral[-1]
    tail = V.bezier([end, end + [-7.0, 0.4], end + [-15.0, -1.5], end + [-23.0, 2.5]], 70)
    path = np.vstack([spiral, tail[1:]])
    tt = np.linspace(0, 1, len(path))
    hw = np.interp(tt, [0.0, 0.12, 0.5, 0.72, 1.0], [0.6, 1.6, 3.1, 2.6, 0.3])
    stroke(P, path, hw, ink, 1.0, dry=0.25, dry_start=0.85, jitter=0.06)
    for (x0, y0, L, al) in ((15.0, 30.0, 12.0, 0.95), (18.0, 46.5, 15.0, 1.0)):
        stroke(P, V.bezier([(x0, y0), (x0 + L / 2, y0 - 0.8), (x0 + L, y0 - 0.4)], 30), 1.4 * W.brush_profile(30, 0.3, 1.0, 0.0)[::-1], mixc(EL_INK["wood"], JIAO, 0.2), al, dry=0.35, dry_start=0.0)
    leaf(P, 47.0, 19.5, -35.0, 8.5, 4.4, mixc(EL_INK["wood"], SHILV, 0.4))


def em_buff_soul(P):
    """摄物（网页版旧名聚魂，meta 的 name 仍沿用）：魂火和铜钱从左边远处被一股劲吸过来，都朝右边一点飞、汇成一束，
    那一点是一团冷白的光（径直飞来，不打旋，不像风车）。"""
    cx, cy = 41.5, 31.5
    glow(P, cx, cy, 12.0, mixc(SOUL, PAPER, 0.3), 0.9)
    tq_d = mixc(ACC_INK["soul"], mixc(HUAQING, JIAO, 0.4), 0.55)
    # 吸力：上下两道淡的弧线收向那一点
    for (y0, bend) in ((19.0, -2.0), (44.0, 2.0)):
        pts = V.bezier([(12.5, y0), (26.0, y0 + bend * 0.4 + (cy - y0) * 0.25), (36.0, cy + (y0 - cy) * 0.22), (cx - 3.0, cy + (y0 - cy) * 0.08)], 40)
        stroke(P, pts, 0.6 * W.brush_profile(40, 0.2, 0.6, 0.0), mixc(tq_d, PAPER, 0.35), 0.7, dry=0.35, dry_start=0.0)
    for (x, y, r) in ((20.0, 24.0, 3.4), (21.5, 40.5, 3.0)):
        coin(P, x, y, r, ol=0.8)
    for ctrl, rb in ((((33.0, 31.6), (27.0, 31.8), (22.0, 30.2), (15.5, 31.4)), 3.0),
                     (((34.6, 24.8), (30.6, 22.6), (28.4, 18.6), (24.6, 17.0)), 2.2),
                     (((34.2, 38.4), (30.4, 40.6), (28.8, 44.4), (25.0, 45.6)), 2.0)):
        soul_wisp(P, ctrl, rb)
    shape(P, W.ellipse_pts(cx, cy, 3.8, 3.8, 40), mixc(SOUL, WHITE, 0.5), ol=0.85, ol_rgb=SOUL_RIM, pool=0.35, pool_rgb=mixc(SOUL, HUAQING, 0.4), mottle=0.0)
    P.dot(cx - 0.8, cy - 0.8, 1.3, WHITE)


def em_buff_iron(P):
    """金身（金钟罩）：一口半透明的金钟罩住一个打坐的人影，钟外一圈金光。"""
    for k in range(16):
        a = 2 * math.pi * k / 16 + 0.1
        r0, r1 = 19.0, 21.8 if k % 2 == 0 else 20.6
        p0 = (32.0 + r0 * math.cos(a), 31.5 + r0 * math.sin(a))
        p1 = (32.0 + r1 * math.cos(a), 31.5 + r1 * math.sin(a))
        stroke(P, W.seg_pts(p0, p1, n=8), np.linspace(0.6, 0.15, 8), mixc(TENG, GOLD_DK, 0.15), 0.9)
    P.dot(32.0, 30.0, 3.2, NONG)
    shape(P, W.catmull_closed([(32.0, 33.2), (37.5, 35.5), (40.0, 43.5), (36.0, 45.8), (28.0, 45.8), (24.0, 43.5), (26.5, 35.5)], 6), NONG, ol=0, pool=0.2, pool_rgb=JIAO, mottle=0.0)
    poly, _ = bell_poly(32.0, 15.5, 47.5, 7.6, 16.8, 2.2)
    rgb = shade_lr(P, 15, 49, mixc(TENG, GOLD_HI, 0.55), mixc(TENG, GOLD_DK, 0.45))
    d, t = P.sdf(W.wobble(poly, P.rng, 0.05, spacing=0.3))
    P.fill(d, rgb, 0.55, pool=0.75, pool_rgb=mixc(TENG, GOLD_DK, 0.25), pool_w=1.6)
    m = P.cover(d)
    for y in (21.5, 42.0):
        stroke(P, W.seg_pts((14.0, y), (50.0, y), n=40), 0.55, GOLD_DK, 0.85, clip=m)
    stroke(P, V.bezier([(26.0, 18.5), (21.5, 30.0), (18.5, 44.0)], 30), 0.9 * W.brush_profile(30, 0.5, 0.3), mixc(GOLD_HI, WHITE, 0.5), 0.85, clip=m)
    P.outline(d, t, OL * 1.15, mixc(GOLD_DK, JIAO, 0.45), jitter=0.18)
    shape(P, W.ellipse_pts(32.0, 13.6, 2.6, 2.0, 30), TENG, ol=0.8, ol_rgb=mixc(GOLD_DK, JIAO, 0.45), pool=0.4, pool_rgb=GOLD_DK)


# ---------------------------------------------------------------- 夜签

def em_omen_bloodmoon(P):
    """血月：一轮血红的满月，两缕干笔墨云横过月面，月下一道浓墨山脊压住月的下沿。"""
    glow(P, 32.5, 25.0, 19.0, mixc(ZHUSHA, PAPER, 0.45), 0.7)
    rr = np.hypot((P.X - 29.0) / 12.5, (P.Y - 21.0) / 12.5)
    rgb = mixc(mixc(mixc(ZHUSHA, W_ZHUSHA, 0.55), ZHUSHA, smoothstep(0.0, 0.8, rr)), ZHUSHA_DK, smoothstep(0.8, 1.6, rr))
    d, m = shape(P, W.ellipse_pts(32.5, 25.5, 12.5, 12.5, 96), rgb, ol=1.0, ol_rgb=ZHUSHA_DK, pool=0.35, pool_rgb=ZHUSHA_DK, mottle=0.12, mottle_rgb=ZHUSHA_DK, wob=0.03)
    for (x, y, r, al) in ((28.0, 21.5, 3.0, 0.35), (36.5, 28.0, 3.6, 0.3), (37.0, 19.0, 2.1, 0.3)):
        P.dot(x, y, r, ZHUSHA_DK, al, clip=m)
    for ctrl, hwm in ((((13.5, 26.5), (24.0, 23.0), (36.0, 27.5), (49.0, 22.5)), 1.25), (((17.0, 32.5), (28.0, 29.5), (40.0, 33.5), (50.5, 30.0)), 1.0)):
        stroke(P, V.bezier(list(ctrl), 60), hwm * W.brush_profile(60, 0.4, 0.2, 0.3), mixc(NONG, ZHONG, 0.3), 0.95, dry=0.5, dry_start=0.15)
    inside = smoothstep(23.6, 23.0, np.hypot(P.X - C, P.Y - C))
    ridge = [(9.0, 54.0), (9.0, 44.0), (15.0, 40.0), (19.5, 41.5), (25.0, 36.5), (29.0, 39.0), (33.5, 37.5), (38.5, 34.0), (43.5, 39.0), (48.0, 37.5), (55.0, 42.0), (55.0, 54.0)]
    d, t = P.sdf(W.wobble(W.catmull_closed(ridge, 6), P.rng, 0.06, spacing=0.3))
    P.fill(d, mixc(mixc(NONG, JIAO, 0.4), mixc(ZHONG, DAN, 0.4), smoothstep(36.0, 52.0, P.Y)), pool=0.35, pool_rgb=JIAO, pool_w=0.8, mottle=0.1, mottle_rgb=JIAO, clip=inside)
    P.outline(d, t, 1.0, JIAO, jitter=0.25, dry=0.15, clip=inside)
    for ctrl in (((25.0, 37.5), (23.5, 41.0), (24.5, 45.0)), ((38.5, 35.0), (37.5, 39.0), (39.0, 43.5))):
        stroke(P, V.bezier(list(ctrl), 20), 0.5 * W.brush_profile(20, 1.0, 0.2), mixc(DAN, QING, 0.3), 0.6, clip=inside, dry=0.4, dry_start=0.3)


def em_omen_fog(P):
    """浓雾：一盏红灯笼隐在三道白雾后面，只露出几分。"""
    paint_lantern(P, 32.0, 30.0, 0.85)
    mist = mixc(PAPER, WHITE, 0.55)
    for (y, x0, x1, h) in ((22.0, 12.5, 45.0, 4.8), (33.0, 19.5, 51.5, 5.8), (43.5, 12.0, 46.5, 5.0)):
        yc = y + 0.9 * np.sin(P.X * 0.33 + y)
        hh = 0.5 * h * (1.0 + 0.15 * np.sin(P.X * 0.6 + 2.0 * y))
        a = smoothstep(hh + 1.1, hh - 0.9, np.abs(P.Y - yc)) * smoothstep(x0 - 1.0, x0 + 5.0, P.X) * smoothstep(x1 + 1.0, x1 - 5.0, P.X)
        P.lay.over(mixc(mist, QING, smoothstep(-0.5 * h, 0.5 * h, P.Y - yc) * 0.35), 0.95 * a)
        xs = np.linspace(x0 + 3.0, x1 - 6.0, 50)
        top = np.stack([xs, y + 0.9 * np.sin(xs * 0.33 + y) - 0.5 * h * (1.0 + 0.15 * np.sin(xs * 0.6 + 2.0 * y)) + 0.3], -1)
        stroke(P, top, 0.5 * W.brush_profile(50, 0.3, 0.2), DAN, 0.8, dry=0.45, dry_start=0.2)


def em_omen_glass(P):
    """琉璃灯：一盏透明的琉璃灯，金顶金座，罩里的火苗看得分明；罩上一道细裂纹（代价：生命上限降低）。"""
    glow(P, 32.0, 33.0, 15.0, mixc(TENG, PAPER, 0.35), 0.55)
    flame(P, 32.0, 40.5, 13.5, 3.9, lean=0.3)
    stroke(P, W.seg_pts((32.0, 40.0), (32.0, 43.5), n=8), 0.45, JIAO)
    body = W.catmull_closed([(24.0, 20.0), (40.0, 20.0), (43.5, 27.0), (43.0, 38.0), (40.0, 44.5), (24.0, 44.5), (21.0, 38.0), (20.5, 27.0)], 8)
    d, t = P.sdf(W.wobble(body, P.rng, 0.04, spacing=0.3))
    P.fill(d, mixc(W_HUAQING, WHITE, 0.55), 0.35, pool=0.8, pool_rgb=mixc(W_HUAQING, HUAQING, 0.35), pool_w=1.8)
    m = P.cover(d)
    for x0, bend in ((26.5, -1.2), (37.5, 1.2)):
        stroke(P, V.bezier([(x0, 20.5), (x0 + bend, 32.0), (x0, 44.0)], 30), 0.35, mixc(TENG, GOLD_DK, 0.3), 0.6, clip=m)
    stroke(P, V.bezier([(23.6, 24.5), (22.2, 32.0), (23.6, 40.5)], 30), 1.0 * W.brush_profile(30, 0.4, 0.3), WHITE, 0.95, clip=m)
    P.dot(40.0, 25.0, 0.8, WHITE, clip=m)
    crack = [(40.5, 21.0), (38.6, 25.0), (40.0, 27.2), (37.4, 31.0), (38.2, 33.5)]
    stroke(P, V.arc_resample(np.array(crack), 40), np.linspace(0.45, 0.12, 40), JIAO, 0.9, clip=m)
    P.outline(d, t, OL, mixc(HUAQING, JIAO, 0.55), jitter=0.18)
    gold = mixc(TENG, GOLD_DK, 0.15)
    shape(P, [(25.0, 15.8), (39.0, 15.8), (42.6, 21.0), (21.4, 21.0)], gold, ol=1.0, ol_rgb=mixc(GOLD_DK, JIAO, 0.45), pool=0.45, pool_rgb=GOLD_DK, wob=0.03)
    shape(P, [(21.4, 44.0), (42.6, 44.0), (40.0, 48.8), (24.0, 48.8)], gold, ol=1.0, ol_rgb=mixc(GOLD_DK, JIAO, 0.45), pool=0.45, pool_rgb=GOLD_DK, wob=0.03)
    loop = W.ellipse_pts(32.0, 12.4, 2.6, 2.4, 40)
    stroke(P, V.arc_resample(np.vstack([loop, loop[:1]]), 60), 0.6, mixc(GOLD_DK, JIAO, 0.3))
    P.dot(32.0, 15.2, 1.5, TENG)


def em_omen_foxes(P):
    """狐火夜：一张白狐面具，朱砂描眉、细长的眼缝，两边各飘一团狐火。"""
    for x, ln in ((13.8, -1.0), (50.2, 1.0)):
        glow(P, x, 39.0, 7.0, mixc(col(S.EYE["fox"]), PAPER, 0.4), 0.55)
        flame(P, x, 44.5, 11.5, 3.3, lean=ln, stops=FOX_STOPS, ol_rgb=mixc(ZHUSHA_DK, JIAO, 0.4), core=False)
    mask = W.catmull_closed([(32.0, 47.0), (25.5, 42.0), (20.0, 34.0), (19.0, 26.0), (20.5, 14.0), (26.0, 20.0), (32.0, 19.0), (38.0, 20.0), (43.5, 14.0), (45.0, 26.0), (44.0, 34.0), (38.5, 42.0)], 8)
    rgb = mixc(mixc(PAPER, WHITE, 0.8), mixc(PAPER, QING, 0.3), smoothstep(26.0, 48.0, P.Y) * 0.6)
    _, m = shape(P, mask, rgb, ol=OL * 1.1, pool=0.25, pool_rgb=QING, mottle=0.0)
    for sx in (-1.0, 1.0):
        ear = [(32.0 + sx * 11.0, 16.8), (32.0 + sx * 7.0, 21.2), (32.0 + sx * 11.5, 23.5)]
        shape(P, ear, ZHUSHA, ol=0.5, ol_rgb=ZHUSHA_DK, pool=0.3, pool_rgb=ZHUSHA_DK, wob=0.02)
        eye = W.almond((32.0 + sx * 3.2, 31.6), (32.0 + sx * 10.8, 28.2), 2.6, 24, bulge=0.45)
        shape(P, eye, JIAO, ol=0, pool=0.0, mottle=0.0, wob=0.0)
        brow = V.bezier([(32.0 + sx * 4.0, 28.8), (32.0 + sx * 7.0, 25.5), (32.0 + sx * 11.5, 24.8)], 24)
        stroke(P, brow, 1.1 * W.brush_profile(24, 1.0, 0.1, 0.0), ZHUSHA, clip=m)
        for k in range(3):
            y = 36.5 + 1.6 * k
            stroke(P, W.seg_pts((32.0 + sx * 7.5, y), (32.0 + sx * 11.0, y - 0.8 + 0.6 * k), n=10), 0.4, ZHUSHA, 0.85, clip=m)
    shape(P, W.catmull_closed([(32.0, 21.0), (33.6, 24.0), (32.0, 26.5), (30.4, 24.0)], 6), ZHUSHA, ol=0, pool=0.2, pool_rgb=ZHUSHA_DK, wob=0.0)
    P.dot(32.0, 44.6, 1.4, JIAO, ry=1.0)


def em_omen_gale(P):
    """疾风：三道长长的风笔横扫过去，末梢上卷，几片叶子被风卷着飞。"""
    for ctrl, hwm, rgb, cxy in ((((11.5, 31.0), (22.0, 21.0), (35.0, 32.0), (47.0, 21.5)), 1.7, NONG, (47.5, 25.0)),
                                (((12.0, 40.5), (25.0, 30.5), (39.0, 42.0), (51.0, 31.0)), 2.2, JIAO, (51.0, 34.6)),
                                (((18.0, 48.0), (28.0, 41.5), (37.0, 49.0), (46.5, 43.0)), 1.3, ZHONG, None)):
        pts = V.bezier(list(ctrl), 60)
        stroke(P, pts, hwm * W.brush_profile(60, 0.4, 0.5, 0.2), rgb, 1.0, dry=0.5, dry_start=0.15)
        if cxy is not None:
            th = np.linspace(0.0, 1.5 * math.pi, 40)
            r = 3.6 - 2.5 * th / th[-1]
            curl = np.stack([cxy[0] + r * np.cos(-th - 0.5 * math.pi), cxy[1] + r * np.sin(-th - 0.5 * math.pi)], -1)
            stroke(P, curl, np.linspace(hwm * 0.5, 0.35, 40), rgb)
    leaf(P, 40.0, 17.5, -30.0, 8.0, 4.0, mixc(W_SHILV, SHILV, 0.4))
    leaf(P, 23.0, 18.0, 25.0, 6.5, 3.4, mixc(W_ZHESHI, ZHESHI, 0.4))
    leaf(P, 33.0, 50.0, -10.0, 6.5, 3.4, mixc(W_SHILV, SHILV, 0.6))


def em_omen_chestrain(P):
    """天降宝箱：一只朱漆宝箱从天而降，上面拖着几道直直的落痕；左上还掉着一只小的。"""
    for (x, y0, y1, al) in ((29.0, 13.0, 27.0, 0.8), (34.5, 10.5, 26.0, 0.9), (40.0, 13.5, 25.5, 0.75), (18.0, 9.5, 18.5, 0.6), (22.5, 11.0, 17.5, 0.5)):
        stroke(P, W.seg_pts((x, y0), (x, y1), n=24), np.linspace(0.1, 0.85, 24), mixc(DAN, ZHONG, 0.4), al, dry=0.35, dry_start=0.0)
    chest_icon(P, 15.0, 22.5, 9.5, 6.5, 3.0, 2.2, ol=0.9)
    chest_icon(P, 23.5, 33.5, 18.0, 12.0, 5.5, 4.5, ol=1.25)
    for (x, y, L) in ((49.0, 25.0, 2.4), (18.5, 40.0, 2.0)):
        sparkle(P, x, y, L, TENG, 0.55)


def em_omen_element(P):
    """五行偏重：五行一圈，相生的环线连着五点；火的那一点又大又重，坠在环底。"""
    cx, cy, R = 32.0, 29.5, 13.0
    ring = W.ellipse_pts(cx, cy, R, R, 120)
    stroke(P, V.arc_resample(np.vstack([ring, ring[:1]]), 160), 0.75, ZHONG, 0.9, dry=0.3, dry_start=0.0)
    order = ["fire", "earth", "metal", "water", "wood"]  # 顺时针相生：火生土、土生金、金生水、水生木、木生火
    for k, el in enumerate(order):
        a = math.radians(90 + 72 * k)
        x, y = cx + R * math.cos(a), cy + R * math.sin(a)
        rad = 7.4 if k == 0 else 3.9
        if k == 0:
            P.dot(x + 0.8, y + 1.2, rad, JIAO, 0.22)
        rr = np.hypot((P.X - x + 0.35 * rad) / rad, (P.Y - y + 0.35 * rad) / rad)
        rgb = mixc(mixc(EL_INK[el], WHITE, 0.3), mixc(EL_INK[el], JIAO, 0.3), smoothstep(0.2, 1.4, rr))
        shape(P, W.ellipse_pts(x, y, rad, rad, 48), rgb, ol=1.2 if k == 0 else 0.9, ol_rgb=mixc(EL_INK[el], JIAO, 0.6), pool=0.35, pool_rgb=mixc(EL_INK[el], JIAO, 0.3), mottle=0.0, wob=0.03)
        P.dot(x - 0.35 * rad, y - 0.35 * rad, 0.22 * rad, WHITE, 0.85)


def em_omen_greed(P):
    """贪婪：一锭元宝压在一堆铜钱上，钱从右边往下滚落。"""
    for (x, y) in ((21.0, 45.5), (29.0, 47.0), (37.5, 46.5), (44.0, 44.0), (25.0, 41.5), (33.5, 42.0), (40.5, 40.0)):
        shape(P, W.ellipse_pts(x, y + 0.9, 4.6, 1.9, 36), mixc(TENG, GOLD_DK, 0.6), ol=0.8, ol_rgb=mixc(GOLD_DK, JIAO, 0.5), pool=0.2, mottle=0.0, wob=0.02)
        coin(P, x, y, 4.6, ry=1.9, ol=0.8)
    paint_ingot(P, 30.0, 33.0, 0.66)
    coin(P, 46.5, 31.5, 3.9)
    coin(P, 44.5, 21.5, 1.9, ry=3.6, ol=0.75)
    for ctrl in (((41.0, 17.0), (44.0, 15.5), (47.5, 17.5)), ((49.5, 26.0), (51.5, 28.5), (51.0, 31.5))):
        stroke(P, V.bezier(list(ctrl), 16), 0.45 * W.brush_profile(16, 0.3, 0.3), DAN, 0.85)


def em_omen_quiet(P):
    """静夜：一弯新月挂在右上，下面一道平静的水线，水里一道淡淡的月影；远处一抹淡山，大片留白。"""
    hill = W.catmull_closed([(12.5, 39.0), (16.5, 35.0), (21.0, 33.0), (25.0, 35.5), (29.5, 37.0), (31.0, 39.0)], 6)
    shape(P, hill, mixc(QING, PAPER, 0.3), ol=0, pool=0.3, pool_rgb=DAN, mottle=0.08, mottle_rgb=DAN)
    x1, y1, r1 = 36.5, 23.0, 10.0
    x2, y2, r2 = 40.6, 19.6, 8.6
    d1 = np.hypot(P.X - x1, P.Y - y1) - r1
    d2 = np.hypot(P.X - x2, P.Y - y2) - r2
    d = np.maximum(d1, -d2)
    t = np.mod(np.arctan2(P.Y - y1, P.X - x1) / (2 * math.pi), 1.0)
    rr = np.hypot((P.X - 31.0) / 9.0, (P.Y - 28.0) / 9.0)
    P.fill(d, mixc(mixc(TENG, WHITE, 0.35), TENG, smoothstep(0.2, 1.0, rr)), pool=0.4, pool_rgb=mixc(TENG, GOLD_DK, 0.4), pool_w=0.7)
    P.outline(d, t, 1.0, mixc(GOLD_DK, JIAO, 0.45), jitter=0.15)
    xs = np.linspace(12.0, 52.0, 80)
    stroke(P, np.stack([xs, 39.0 + 0.35 * np.sin(xs * 0.4)], -1), 1.0 * W.brush_profile(80, 0.5, 0.3, 0.2), NONG, 1.0, dry=0.35, dry_start=0.75)
    stroke(P, W.seg_pts((21.0, 45.0), (43.0, 45.2), n=40), 0.5 * W.brush_profile(40, 0.4, 0.3), DAN, 0.8)
    for (y, half, al) in ((41.6, 4.2, 0.95), (43.4, 3.0, 0.8), (47.0, 1.8, 0.6)):
        stroke(P, W.seg_pts((32.0 - half, y), (32.0 + half, y), n=16), 0.6 * W.brush_profile(16, 0.4, 0.4), mixc(TENG, GOLD_DK, 0.15), al)
    for (x, y, r) in ((19.0, 21.0, 0.75), (25.0, 15.5, 0.6), (48.5, 33.0, 0.5)):
        P.dot(x, y, r, ZHONG)


def em_omen_wonders(P):
    """奇遇夜：一只斜放的葫芦，腰系朱砂绳，葫芦口冒出一缕卷曲的仙气，气里几颗金星。"""
    fr = Fr(26.5, 39.0, -52.0, 1.0)
    us = np.linspace(-9.6, 19.2, 90)
    big = np.sqrt(np.clip(9.6**2 - us**2, 0, None))
    small = np.sqrt(np.clip(6.0**2 - (us - 13.2) ** 2, 0, None))
    k = 2.2
    hw = k * np.log(np.exp(big / k) + np.exp(small / k) - 1.0 + 1e-9)
    hw = np.maximum(hw, 0.05)
    poly = fr([(u, -h) for u, h in zip(us, hw)] + [(u, h) for u, h in zip(us[::-1], hw[::-1])][1:-1])
    _, Vv = fr.uv(P)
    rgb = mixc(mixc(W_ZHESHI, TENG, 0.35), mixc(ZHESHI, ZHONG, 0.35), smoothstep(-6.0, 9.0, Vv))
    mouth = np.array(fr.pt(19.5, 0.0))
    smoke = V.bezier([mouth, mouth + [6.0, -4.0], mouth + [2.0, -12.0], mouth + [-6.0, -10.5]], 50)
    stroke(P, smoke, np.interp(np.linspace(0, 1, 50), [0, 0.3, 1], [1.2, 1.8, 0.3]), mixc(QING, HUAQING, 0.25), 0.9, dry=0.35, dry_start=0.6)
    th = np.linspace(0.0, 1.5 * math.pi, 30)
    rc = 2.4 - 1.6 * th / th[-1]
    end = smoke[-1]
    curl = np.stack([end[0] + 2.0 + rc * np.cos(th + math.pi), end[1] + rc * np.sin(th + math.pi)], -1)
    stroke(P, curl, 0.6, mixc(QING, HUAQING, 0.25), 0.85)
    _, m = shape(P, poly, rgb, ol=OL, pool=0.3, pool_rgb=mixc(ZHESHI, JIAO, 0.3), mottle=0.08, mottle_rgb=ZHESHI)
    stroke(P, fr(V.bezier([(-5.0, -6.0), (-1.0, -8.0), (3.0, -6.8)], 20)), 0.9 * W.brush_profile(20, 0.4, 0.3), mixc(PAPER, WHITE, 0.6), 0.85, clip=m)
    stroke(P, fr(W.seg_pts((7.8, -4.5), (7.8, 4.5), n=12)), 0.95, ZHUSHA)
    knot = np.array(fr.pt(7.8, 4.3))
    for dv in ((-1.0, 5.5), (1.6, 5.0)):
        stroke(P, V.bezier([knot, knot + [0.5 * dv[0], 2.0], knot + list(dv)], 12), 0.55 * W.brush_profile(12, 1.0, 0.3, 0.0), ZHUSHA)
    P.dot(knot[0], knot[1], 1.0, ZHUSHA_DK)
    stroke(P, fr(W.seg_pts((18.6, 0.0), (21.0, 0.0), n=8)), 1.4, mixc(ZHESHI, JIAO, 0.4))
    for (x, y, L) in ((47.5, 22.0, 2.8), (36.0, 11.5, 2.2), (43.5, 13.5, 1.6), (21.0, 17.5, 1.8)):
        sparkle(P, x, y, L, TENG, 0.6)


# ---------------------------------------------------------------- 界面

def em_hud_kills(P):
    """击杀：一只墨团小鬼被一刀斜斩成两半——两半错开，刀痕一线朱砂。不见血。"""
    ghost = [(32.0, 13.5), (40.5, 17.0), (44.5, 26.0), (44.0, 37.0), (45.5, 46.0), (41.0, 43.5), (37.5, 48.0), (33.0, 44.5), (28.5, 48.5), (25.0, 43.5), (20.0, 46.0), (21.0, 37.0), (20.0, 26.0), (24.0, 17.0)]
    poly = W.catmull_closed(ghost, 8)
    c0 = np.array([32.0, 31.0])
    e = np.array([1.0, -0.95])
    e /= np.linalg.norm(e)
    nv = np.array([-e[1], e[0]])
    g = 1.3
    for sgn in (1.0, -1.0):
        off = nv * g * sgn
        side = ((P.X - c0[0] - off[0]) * nv[0] + (P.Y - c0[1] - off[1]) * nv[1]) * sgn
        clip = smoothstep(-P.aa, P.aa, side)
        rgb = shade_lr(P, 18.0, 46.0, mixc(ZHONG, NONG, 0.4), mixc(NONG, JIAO, 0.5))
        d, t = P.sdf(W.wobble(poly + off, P.rng, 0.05, spacing=0.3))
        P.fill(d, rgb, pool=0.3, pool_rgb=JIAO, pool_w=0.8, clip=clip)
        P.outline(d, t, OL, JIAO, jitter=0.2, clip=clip)
        for ex in (27.0, 37.0):
            eye = W.almond((ex - 3.0 + off[0], 26.0 + off[1] + (0.8 if ex < 32 else -0.4)), (ex + 3.0 + off[0], 26.0 + off[1] + (-0.6 if ex < 32 else 0.8)), 3.6, 20, bulge=0.5)
            shape(P, eye, mixc(PAPER, WHITE, 0.5), ol=0, pool=0.0, mottle=0.0, wob=0.0)
    cut = W.seg_pts(c0 - e * 24.0, c0 + e * 24.0, n=60)
    stroke(P, cut, 0.15 + 0.85 * np.sin(np.pi * np.linspace(0, 1, 60)) ** 1.5, ZHUSHA, 1.0)


def em_hud_pause(P):
    """暂停：两笔竖直的浓墨，起笔重按、收笔带飞白。"""
    for x in (25.5, 38.5):
        pts = W.seg_pts((x, 18.5), (x + 0.3, 45.5), n=60)
        stroke(P, pts, 3.5 * W.brush_profile(60, 1.0, 0.75, 0.1), JIAO, 1.0, dry=0.18, dry_start=0.88, jitter=0.06)


def em_hud_dash(P):
    """闪：一只大大的浓墨快靴向前一蹬（剪影要在 24 像素下认得出），靴口一道朱砂，身后两道粗的疾痕。"""
    for (y, x0, x1, hwm) in ((28.0, 7.5, 25.0, 2.3), (37.0, 9.0, 24.0, 2.0)):
        stroke(P, W.seg_pts((x1, y - 0.5), (x0, y), n=40), hwm * W.brush_profile(40, 1.0, 0.1, 0.0), mixc(NONG, JIAO, 0.3), 0.95, jitter=0.1)
    fr = Fr(25.5, 45.0, -14.0, 1.2)
    boot = [(0.0, 0.0), (-0.2, -9.0), (-1.0, -17.5), (7.0, -18.5), (8.0, -9.5), (13.5, -7.0), (18.0, -5.0), (20.5, -2.0), (19.0, 0.2)]
    sil = fr(W.catmull_closed(boot, 5))
    _, Vv = fr.uv(P)
    _, m = shape(P, sil, mixc(mixc(NONG, JIAO, 0.5), JIAO, smoothstep(-18.0, 0.0, Vv) * 0.7), ol=OL * 1.2, ol_rgb=JIAO, pool=0.3, pool_rgb=JIAO, mottle=0.04)
    stroke(P, fr(V.bezier([(1.0, -1.2), (10.0, -0.4), (18.5, -1.4)], 30)), 0.75, mixc(ZHONG, DAN, 0.4), 0.9, clip=m)
    stroke(P, fr(W.seg_pts((-0.6, -15.2), (7.4, -16.2), n=20)), 1.25, ZHUSHA, 1.0, clip=m)
    for (x, y, r, al) in ((21.0, 46.5, 1.6, 0.55), (16.5, 45.2, 1.1, 0.45)):
        P.dot(x, y, r, DAN, al)


def em_hud_ult(P):
    """燃灯（大招）：一盏灯笼在烈焰里燃起，背后一圈放射的金光环。"""
    glow(P, 32.0, 31.0, 20.0, mixc(TENG, PAPER, 0.3), 0.7)
    ring = W.ellipse_pts(32.0, 31.5, 18.6, 18.6, 120)
    stroke(P, V.arc_resample(np.vstack([ring, ring[:1]]), 200), 0.75, mixc(TENG, GOLD_DK, 0.2), 0.95)
    for k in range(16):
        a = 2 * math.pi * k / 16
        r0, r1 = 15.0, 22.0 if k % 2 == 0 else 20.0
        stroke(P, W.seg_pts((32.0 + r0 * math.cos(a), 31.5 + r0 * math.sin(a)), (32.0 + r1 * math.cos(a), 31.5 + r1 * math.sin(a)), n=10),
               np.linspace(0.75, 0.15, 10), mixc(TENG, ZHUSHA, 0.15), 0.9)
    flame(P, 32.0, 47.0, 34.0, 12.5, ol=1.0)
    paint_lantern(P, 32.0, 33.5, 0.82)


def em_hud_level(P):
    """等级徽章底：只有框（纸底、墨圈、金圈），中间留空，数字由游戏画。"""


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


# ---------------------------------------------------------------- 第二批的框

F_PLAIN = {"arc": NEUTRAL_ARC}
F_LIT = {"arc": LAMP_ARC, "glow": True}
F_OFF = {"arc": QING, "off": True}
F_OMEN = {"omen": True}
F_LEVEL = {"arc": None, "gold_rim": (22.6, 2.3)}


def F_ACC(key):
    return {"arc": ACC_INK[key]}


def paint_faded(P: W.Painter, fn) -> None:
    """心灯未点亮：物件先画在单独一层，再按明度换成淡墨（深处重墨兑淡墨、亮处近纸色），叠回纸底。
    物件的随机数与点亮版完全一样，所以是同一幅画。"""
    back = P.lay
    P.lay = V.Layer(*P.X.shape)
    fn(P)
    em = P.lay
    P.lay = back
    rgb = em.p / np.maximum(em.a, 1e-6)[..., None]
    L = np.clip(lum3(rgb), 0.0, 1.0)
    tone = mixc(mixc(ZHONG, DAN, 0.3), mixc(PAPER, WHITE, 0.2), L**0.95)
    back.over(tone, em.a * 0.92)


def omen_front(P: W.Painter) -> None:
    """夜签的框：朱砂双圈（外粗内细），像一枚圆形朱文印——印泥有轻有重、有砂眼，外圈有两处残缺。"""
    r = np.hypot(P.X - C, P.Y - C)
    th = np.mod(np.arctan2(P.Y - C, P.X - C) / (2 * math.pi), 1.0)
    R1 = 27.2 + 0.15 * W.sample1(W.pnoise1(P.rng, 256, 6.0), th)
    hw1 = 1.6 * np.clip(1.0 + 0.12 * W.sample1(W.pnoise1(P.rng, 256, 4.0), th), 0.7, 1.3)
    R2, hw2 = 24.3, 0.62 * np.clip(1.0 + 0.15 * W.sample1(W.pnoise1(P.rng, 256, 5.0), th), 0.6, 1.4)
    cov = np.maximum(smoothstep(hw1 + P.aa, hw1 - P.aa, np.abs(r - R1)), smoothstep(hw2 + P.aa, hw2 - P.aa, np.abs(r - R2)))
    for g0, gw in ((0.135, 0.012), (0.61, 0.008)):  # 残边：外圈两处缺口
        gap = smoothstep(gw, gw * 0.4, np.abs(np.mod(th - g0 + 0.5, 1.0) - 0.5)) * (r > R2 + 1.5)
        cov = cov * (1.0 - gap)
    press = V.noise1(P.rng, P.X.shape, 2.5 * P.ss)
    speck = V.rank01(V.noise1(P.rng, P.X.shape, 0.22 * P.ss))
    holes = smoothstep(0.93 + 0.03 * press, 0.965 + 0.03 * press, speck)
    rgb = mixc(mixc(ZHUSHA, W_ZHUSHA, 0.15), mixc(ZHUSHA, ZHUSHA_DK, 0.45), np.clip(0.5 + 0.35 * press, 0, 1))
    P.lay.over(rgb, cov * (1.0 - 0.85 * holes) * 0.97)


META_NODES = [("dmg", "锋芒", em_meta_dmg), ("hp", "体魄", em_meta_hp), ("agi", "灵巧", em_meta_agi), ("luck", "气运", em_meta_luck)]
ENCOUNTERS = [("toad", "金蟾", em_enc_toad), ("spring", "灵泉", em_enc_spring), ("shrine", "古灯", em_enc_shrine), ("altar", "血祭坛", em_enc_altar), ("rift", "妖潮裂隙", em_enc_rift)]
BUFFS = [("fury", "灯焰", em_buff_fury), ("swift", "御风", em_buff_swift), ("soul", "聚魂", em_buff_soul), ("iron", "金身", em_buff_iron)]
OMENS = [  # 与 web/lantern/game.js 的 OMENS 同序
    ("bloodmoon", "血月", em_omen_bloodmoon), ("fog", "浓雾", em_omen_fog), ("glass", "琉璃灯", em_omen_glass), ("foxes", "狐火夜", em_omen_foxes),
    ("gale", "疾风", em_omen_gale), ("chestrain", "天降宝箱", em_omen_chestrain), ("element", "五行偏重", em_omen_element), ("greed", "贪婪", em_omen_greed),
    ("quiet", "静夜", em_omen_quiet), ("wonders", "奇遇夜", em_omen_wonders),
]
HUD = [("kills", "击杀", em_hud_kills, F_PLAIN), ("pause", "暂停", em_hud_pause, F_PLAIN), ("dash", "闪", em_hud_dash, F_PLAIN),
       ("ult", "燃灯", em_hud_ult, {"arc": LAMP_ARC}), ("level", "等级", em_hud_level, F_LEVEL)]


def new_specs():
    """第二批图标：[(文件名, 物件函数, 框, 种子, meta 附加字段)]，追加在前 25 个之后，顺序固定。
    心灯的亮、暗两版用同一个种子（同一幅画）。"""
    out = []
    k = 0

    def add(fname, fn, fs, extra, same_seed=False):
        nonlocal k
        if not same_seed:
            k += 1
        out.append((fname, fn, fs, 7000 + 37 * k, extra))

    add("icon_lotus", em_lotus, F_PLAIN, {"kind": "supply", "id": "lotus", "name": "莲子"})
    add("icon_oil", em_oil, F_PLAIN, {"kind": "currency", "id": "oil", "name": "灯油"})
    for mid, name, fn in META_NODES:
        add(f"icon_meta_{mid}", fn, F_LIT, {"kind": "meta", "id": mid, "name": name, "lit": True})
        add(f"icon_meta_{mid}_off", fn, F_OFF, {"kind": "meta", "id": mid, "name": name, "lit": False}, same_seed=True)
    for eid, name, fn in ENCOUNTERS:
        add(f"icon_enc_{eid}", fn, F_ACC(eid), {"kind": "encounter", "id": eid, "name": name, "accent": ACC_HEX[eid]})
    for bid, name, fn in BUFFS:
        add(f"icon_buff_{bid}", fn, F_ACC(bid), {"kind": "buff", "id": bid, "name": name, "accent": ACC_HEX[bid]})
    for oid, name, fn in OMENS:
        add(f"icon_omen_{oid}", fn, F_OMEN, {"kind": "omen", "id": oid, "name": name})
    for hid, name, fn, fs in HUD:
        add(f"icon_{hid}", fn, fs, {"kind": "hud", "id": hid, "name": name})
    return out


def make_icon2(index: int) -> Image.Image:
    _, fn, fs, seed, _ = new_specs()[index]
    P = W.Painter(SIZE, SIZE, seed, ss=SS)
    disc_back(P, mixc(PAPER, W_ZHUSHA, 0.05) if fs.get("omen") else PAPER)
    if fs.get("glow"):
        glow(P, C, C + 1.0, 22.0, LAMP_GLOW, 0.65)
    if fs.get("off"):
        paint_faded(P, fn)
    else:
        fn(P)
    if fs.get("omen"):
        omen_front(P)
    elif fs.get("off"):
        ring_front(P, fs["arc"], arc_hw=0.6, ink=OFF_INK, dry=(0.22, 0.55), ring_alpha=0.9)
    else:
        ring_front(P, fs.get("arc"), gold_rim=fs.get("gold_rim"))
    return P.image()


def note_for(extra: dict) -> str:
    if extra.get("kind") == "meta":
        return f"心灯{'（点亮）' if extra['lit'] else '（未点亮）'}：{extra['name']}"
    if extra.get("kind") == "seal":
        return f"朱砂印章（{extra['style']}）：{extra['name']}"
    return f"界面图标：{extra['name']}"


# ---------------------------------------------------------------- 并行出图

def _render(task):
    kind, i = task
    if kind == "old":
        _, key, el, evo, element, _ = icon_specs()[i]
        return make_icon(i, key, el, evo, element)
    if kind == "new":
        return make_icon2(i)
    if kind == "m25":
        import ui_icons_m25  # noqa: PLC0415

        return ui_icons_m25.make(i)
    import ui_seals  # noqa: PLC0415

    return ui_seals.make_seal(i)


def render_all(tasks) -> list[Image.Image]:
    """每个图标各自取种子，彼此独立，可以多进程并行；结果与逐个串行画完全一致。LANTERN_JOBS=1 关闭并行。"""
    jobs = int(os.environ.get("LANTERN_JOBS", str(min(4, os.cpu_count() or 1))))
    if jobs <= 1 or len(tasks) < 4:
        return [_render(t) for t in tasks]
    with ProcessPoolExecutor(jobs, mp_context=multiprocessing.get_context("fork")) as ex:
        return list(ex.map(_render, tasks, chunksize=1))


def build() -> dict[str, tuple[Image.Image, tuple[float, float], dict]]:
    import ui_icons_m25  # noqa: PLC0415
    import ui_seals  # noqa: PLC0415

    base = {"color": "full", "blend": "normal", "tint": False}
    old, new, seals, m25 = icon_specs(), new_specs(), ui_seals.seal_specs(), ui_icons_m25.specs()
    tasks = [("old", i) for i in range(len(old))] + [("new", i) for i in range(len(new))] + [("seal", i) for i in range(len(seals))]
    tasks += [("m25", i) for i in range(len(m25))]
    imgs = iter(render_all(tasks))
    out = {}
    for fname, key, el, evo, element, extra in old:
        out[fname] = (next(imgs), (0.5, 0.5), {**base, **extra, "note": f"界面图标：{extra['name']}"})
    for fname, _fn, _fs, _seed, extra in new:
        out[fname] = (next(imgs), (0.5, 0.5), {**base, **extra, "note": note_for(extra)})
    for spec in seals:
        extra = spec["meta"]
        out[spec["fname"]] = (next(imgs), (0.5, 0.5), {**base, **extra, "note": note_for(extra)})
    for fname, _fn, _frame, _seed, extra in m25:
        out[fname] = (next(imgs), (0.5, 0.5), {**base, **extra, "note": ui_icons_m25.note_for(extra)})
    # 印章在 seal_specs 里按序号排（新的反应印追加在原有 13 枚之后），meta 里把 M2.5 的印章挪到最后，原有条目的顺序不变
    keys = list(out)
    first = [k for k in keys if not k.startswith("seal_react_") and k not in {f for f, *_ in m25}]
    return {k: out[k] for k in first + [f for f, *_ in m25] + [k for k in keys if k.startswith("seal_react_")]}


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
        "accent_colors": {k: S.rgb_to_hex(tuple(int(round(c * 255)) for c in v)) for k, v in ACC_INK.items()},
        "seal_generator": "art/post/ui_seals.py（由 ui_icons.py 调用，写进同一个 ui/ 与 meta.json）",
        "m25_generator": "art/post/ui_icons_m25.py（M2.5 的图标，由 ui_icons.py 调用；五行反应印仍由 ui_seals.py 画）",
        "small_icons": "kind=affix 的精英词缀图标是小图标：1 倍 32×32、2 倍 64×64，其余图标 64 / 128",
        "files": files,
    }
    (UI_DIR / "meta.json").write_text(V.dump_json(meta), encoding="utf-8")
    print(f"写出 {len(items)} 个图标/印章，共 {total / 1024:.1f} KB，用时 {time.perf_counter() - t0:.1f} s → {UI_DIR}")
    return items


if __name__ == "__main__":
    main()
