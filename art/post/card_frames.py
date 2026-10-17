#!/usr/bin/env python3
"""提灯夜行 · 升级卡样张：两种卡框（黑漆描金 / 绢本织锦）、卡面排版、升级界面全景模拟（只用 Pillow + numpy）。

版式按架构会话定稿（973feef，1280×720 设计画布的逻辑像素；1080p 下 ×1.5）：
  卡片 300×460，内边距 16（下 20）；卡框的花边在节点内约 8 像素处；
  插画区 268×201（4:3，圆角 6 裁切），左上 8 像素压 34 像素的五行印，右上 8 像素压品阶签；
  下半张：卡名 30 号、收益 22 号、等级点、一行共鸣 / 进化提示（15 号）；页脚：类别、进化配对心法的 30 像素小图标、按键。
卡框贴图画 2 倍（600×920），九宫格：四角放角花（切片以内），四边沿长度方向不变，中间是漆面 / 绢面。
稀有度靠卡框的材质和光区分（品阶签只是辅助）：
  黑漆描金：深色漆底（漆面的微光、细断纹），金箔描边；内缘一圈光按稀有度换色（凡 铁灰墨、灵 青蓝、玄 紫、天 金红），
            角上的金结与边上的纹样一级比一级繁（凡 单线；灵、玄 双线 + 方胜结；天 双线 + 连珠 + 如意结 + 洒金）。
  绢本织锦：暖白绢底（细经纬、微光泽），织锦包边按稀有度换锦色与纹样，四角铜包角（灵、玄、异嵌珐琅泡钉，天、合鎏金）。

输出：
  art/out/review@2x/card_sample_lacquer.png、card_sample_silk.png   1920×1080 升级界面全景（1080p，卡片 450×690）
  art/out/review@2x/card_sample_zoom.png                           天品寒山钟两种画法：贴图原尺寸（2 倍逻辑像素）对比
  art/out/skin_card/<lacquer|silk>/card_{fan,ling,xuan,tian,focus}.png（另有参考用的 card_yi、card_he）
      + card_tag_<品阶>.png（品阶签）+ skin.json（格式同 out/skin/skin.json）；stat_*.png、seal_el_*.png 两种画法共用
插画来自 render/card_art.py（art/out/review@2x/card_art_<id>.png）。

用法（仓库根目录）：
  art/.venv/bin/python art/post/card_frames.py            # 九宫格件 + 三张样张
  art/.venv/bin/python art/post/card_frames.py --pieces   # 只出九宫格件
  art/.venv/bin/python art/post/card_frames.py --reuse    # 不重画九宫格件，只重排样张
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = Path(__file__).resolve().parent
ART = HERE.parent
sys.path.insert(0, str(HERE))
import vfx_textures as V  # noqa: E402
import weapon_textures as WT  # noqa: E402
import ui_skin as U  # noqa: E402

S = V.S
REPO = ART.parent
REVIEW = ART / "out" / "review@2x"
SKIN_OUT = ART / "out" / "skin_card"
FONT_BRUSH = REPO / "assets" / "fonts" / "MaShanZheng-subset.ttf"
FONT_SERIF = REPO / "assets" / "fonts" / "NotoSerifSC-subset.ttf"
SUBSET = set((REPO / "assets" / "fonts" / "subset-chars.txt").read_text(encoding="utf-8"))
BRUSH_MISSING = set("→·●○")  # 马善政子集里没有的符号（实测），这些字改用正文字体

CW, CH = 600, 920  # 卡片贴图（2 倍逻辑像素）
SL = 48  # 九宫格切片（贴图像素）：角花都在 48 以内
PAD, PAD_B = 32, 40  # 内边距 16 / 下 20（2 倍）
ART_BOX = (32, 32, 568, 434)  # 插画区 268×201（2 倍），圆角 12
FOCUS_PAD = 12  # 焦点框比卡大一圈（逻辑 6）

smoothstep, fft_blur, noise = V.smoothstep, V.fft_blur, V.noise


def hexc(h: str) -> np.ndarray:
    h = h.lstrip("#")
    return np.array([int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4)])


def mixc(a, b, t):
    t = np.asarray(t, dtype=np.float64)
    if t.ndim:
        t = t[..., None]
    return np.asarray(a) * (1 - t) + np.asarray(b) * t


def check_text(s: str, brush: bool = False) -> str:
    """样张里出现的字必须在子集字体里（游戏里也只有这些字）。"""
    miss = [c for c in s if c not in SUBSET and not c.isspace()]
    assert not miss, f"子集字体缺字：{miss}"
    if brush:
        bad = [c for c in s if c in BRUSH_MISSING]
        assert not bad, f"马善政子集没有：{bad}"
    return s


def font(kind: str, size: float) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONT_BRUSH if kind == "brush" else FONT_SERIF), int(round(size)))


# ============================================================== 画布与基础形状


class Cv:
    """超采样画布（坐标以最终像素计）：预乘 alpha 叠加，最后缩小输出直通 alpha 的 RGBA。"""

    def __init__(self, w: int, h: int, seed: int, ss: int = 2):
        self.w, self.h, self.ss = w, h, ss
        self.X, self.Y = V.grid(h, w, ss)
        self.lay = V.Layer(h * ss, w * ss)
        self.rng = np.random.default_rng(seed)
        self.aa = 0.7 / ss

    def over(self, rgb, a):
        self.lay.over(rgb, np.clip(a, 0, 1))

    def image(self, dither: int | None = None) -> Image.Image:
        lay = self.lay.down(self.ss)
        rgb, a = lay.straight()
        if dither is not None:
            a8 = V.dither_alpha(a, np.random.default_rng(dither))
            a8[a <= 0] = 0
        else:
            a8 = np.clip(np.round(a * 255.0), 0, 255).astype(np.uint8)
        return Image.fromarray(np.dstack([np.clip(np.round(U.bleed_rgb(rgb, a8) * 255), 0, 255).astype(np.uint8), a8]), "RGBA")

    def noise(self, sigma, angle=0.0):
        return noise(self.rng, self.X.shape, sigma * self.ss, angle)


def rrect_sd(X, Y, x0, y0, x1, y1, r):
    """圆角矩形的有向距离（内负外正）。"""
    qx = np.abs(X - 0.5 * (x0 + x1)) - (0.5 * (x1 - x0) - r)
    qy = np.abs(Y - 0.5 * (y0 + y1)) - (0.5 * (y1 - y0) - r)
    return np.hypot(np.maximum(qx, 0), np.maximum(qy, 0)) + np.minimum(np.maximum(qx, qy), 0) - r


def blur_ss(c: Cv, a, sigma):
    return fft_blur(a, sigma * c.ss)


def emboss(c: Cv, height, *, light=(-0.55, -0.70, 0.45), depth=1.0, sigma=1.0):
    """高度场 → 受光 0..1（平面约 0.5，迎光的斜面亮、背光的暗）。height 在超采样网格上。"""
    hgt = blur_ss(c, height, sigma)
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


GOLD = [(0.0, "#2E1C06"), (0.30, "#6E4A14"), (0.52, "#B5852E"), (0.68, "#D9AE52"), (0.84, "#F2D58C"), (0.95, "#FFF3CE"),
        (1.0, "#FFFFFF")]
GOLD_OLD = [(0.0, "#1E140A"), (0.30, "#4A3618"), (0.55, "#7E6234"), (0.75, "#A88A52"), (0.92, "#CDB27C"), (1.0, "#E8D6A8")]
COPPER = [(0.0, "#1C0D06"), (0.3, "#5A2E16"), (0.55, "#94532C"), (0.72, "#C27A46"), (0.88, "#E8AE78"), (1.0, "#FFE2BE")]
BRONZE_DK = [(0.0, "#100C08"), (0.3, "#2C241A"), (0.55, "#4E4232"), (0.75, "#73644C"), (0.9, "#9C8B6C"), (1.0, "#C4B494")]
GILT = [(0.0, "#2A1A06"), (0.3, "#7A5418"), (0.55, "#C2902F"), (0.72, "#E2B656"), (0.88, "#FBE3A0"), (1.0, "#FFFAE6")]


def metal(c: Cv, mask, stops, *, sigma=1.1, depth=1.0, grain=0.05, base=0.0, seams=False):
    """一块浮起的金属（描金、铜件）：mask 是覆盖度，按 emboss 打光后查色带。"""
    sh = emboss(c, mask, sigma=sigma, depth=depth)
    g = c.noise(2.2) * grain + c.noise(0.6) * grain * 0.5
    if seams:  # 金箔的方块接缝：很淡的几道直线
        sx = np.abs(((c.X + 7) % 46) - 23) < 0.35
        sy = np.abs(((c.Y + 19) % 46) - 23) < 0.35
        g = g - 0.05 * (sx | sy)
    return ramp(sh + g + base, stops)


def stroke_mask(c: Cv, pts, hw, box=None):
    """一条折线笔画的覆盖度（等宽圆头），只在包围盒里算。pts 以最终像素计。"""
    P = np.asarray(pts, np.float64)
    hwv = np.broadcast_to(np.asarray(hw, np.float64), (len(P),))
    pad = float(hwv.max()) + 2
    x0, x1 = P[:, 0].min() - pad, P[:, 0].max() + pad
    y0, y1 = P[:, 1].min() - pad, P[:, 1].max() + pad
    xs, ys = c.X[0], c.Y[:, 0]
    ix = np.nonzero((xs >= x0) & (xs <= x1))[0]
    iy = np.nonzero((ys >= y0) & (ys <= y1))[0]
    out = np.zeros(c.X.shape)
    if len(ix) == 0 or len(iy) == 0:
        return out
    sl = (slice(iy[0], iy[-1] + 1), slice(ix[0], ix[-1] + 1))
    X, Y = c.X[sl], c.Y[sl]
    d = np.full(X.shape, 1e9)
    hh = np.zeros(X.shape)
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


def bez(ctrl, n=60):
    return V.bezier(ctrl, n)


def spiral(cx, cy, r0, r1, a0, turns, n=80, sx=1.0):
    t = np.linspace(0, 1, n)
    a = a0 + sx * 2 * math.pi * turns * t
    r = r0 + (r1 - r0) * t
    return np.stack([cx + r * np.cos(a), cy + r * np.sin(a)], -1)


def mirror4(pts_list, w, h):
    """左上角的笔画复制到四角（左右、上下镜像）。"""
    out = []
    for sx in (1, -1):
        for sy in (1, -1):
            for pts in pts_list:
                P = np.asarray(pts, np.float64).copy()
                if sx < 0:
                    P[:, 0] = w - P[:, 0]
                if sy < 0:
                    P[:, 1] = h - P[:, 1]
                out.append(P)
    return out


# ============================================================== 稀有度

RARITY = {
    # 漆：内缘光、宝石主色、宝石高光；绢：锦地、锦纹、包角材质、珐琅
    "fan": dict(glow="#7C848E", glow_a=0.10, gem="#3C4046", gem_hi="#9AA3AE", gold=GOLD_OLD,
                brocade="#3A4150", motif="#5A6272", thread=None, corner=BRONZE_DK, enamel=None),
    "ling": dict(glow="#41B6E6", glow_a=0.58, gem="#1E8FC4", gem_hi="#BDF0FF", gold=GOLD,
                 brocade="#1F5C66", motif="#5FA6A0", thread=None, corner=COPPER, enamel="#2E86C8"),
    "xuan": dict(glow="#A274E8", glow_a=0.58, gem="#6E3FBE", gem_hi="#E3CCFF", gold=GOLD,
                 brocade="#4A2A62", motif="#8E6AAE", thread=None, corner=COPPER, enamel="#7A4CC6"),
    "tian": dict(glow="#F2A443", glow_a=0.50, gem="#D23A22", gem_hi="#FFD39A", gold=GOLD,
                 brocade="#7C1A16", motif="#D6A548", thread="#E8C46A", corner=GILT, enamel="#C8321E"),
    "yi": dict(glow="#E8503A", glow_a=0.50, gem="#A8201C", gem_hi="#FFB0A0", gold=GOLD,
               brocade="#5A1414", motif="#B0503C", thread=None, corner=COPPER, enamel="#B02A1E"),
    "he": dict(glow="#4FD0B8", glow_a=0.50, gem="#1D9C8C", gem_hi="#C8FFF2", gold=GOLD,
               brocade="#1A4A44", motif="#D6B45A", thread="#D6B45A", corner=GILT, enamel="#1E9C88"),
}


# ============================================================== 黑漆描金

def lacquer_surface(c: Cv, x0, y0, x1, y1, r, rarity: str):
    """漆面：近黑带一点暖（推光漆透出一点朱褐），大块的浓淡；一道斜着的柔光（漆面映着窗光）；
    很淡的细断纹（牛毛断）。返回 (颜色, 覆盖度, 有向距离)。"""
    d = rrect_sd(c.X, c.Y, x0, y0, x1, y1, r)
    body = smoothstep(c.aa, -c.aa, d)
    base = hexc("#0D0A09")
    cloud = V.fbm(c.rng, c.X.shape, (90.0 * c.ss, 40.0 * c.ss, 14.0 * c.ss), (0.5, 0.35, 0.15))
    rgb = base * (1 + 0.10 * cloud)[..., None]
    warm = smoothstep(0.4, 1.4, V.fbm(c.rng, c.X.shape, (160.0 * c.ss, 60.0 * c.ss), (0.7, 0.3)))
    rgb = mixc(rgb, hexc("#24120E"), 0.16 * warm)
    # 斜光：一条宽的柔光带 + 一道窄一点的反光（漆面像镜子，映着一扇窗）
    u = (c.X / c.w) * 0.62 + (c.Y / c.h) * 0.38
    sheen = np.exp(-((u - 0.62) / 0.16) ** 2) * 0.055 + np.exp(-((u - 0.585) / 0.022) ** 2) * 0.030
    rgb = rgb + hexc("#93A0B4") * sheen[..., None] * (0.75 + 0.25 * cloud[..., None])
    # 细断纹：顺着横向的短发丝纹
    hair = V.rank01(fft_blur(c.rng.standard_normal(c.X.shape), (26.0 * c.ss, 0.5 * c.ss), angle=0.05))
    crack = smoothstep(0.985, 0.996, hair) * smoothstep(0.3, 0.9, V.rank01(c.noise(30.0)))
    rgb = rgb * (1 - 0.30 * crack[..., None]) + hexc("#3A3430") * 0.06 * crack[..., None]
    # 漆积在边上：靠边一圈更深更亮（边棱反光）
    edge = np.exp(-np.maximum(-d, 0) / 3.0)
    rgb = rgb * (1 - 0.35 * edge[..., None]) + hexc("#5A5650") * 0.10 * np.exp(-np.maximum(-d - 1.0, 0) / 1.2)[..., None]
    return np.clip(rgb, 0, 1), body, d


def rrect_points(x0, y0, x1, y1, r, step):
    """圆角矩形上等距的点（顺时针，从顶边左端起）。"""
    pts = []
    segs = [((x0 + r, y0), (x1 - r, y0)), None, ((x1, y0 + r), (x1, y1 - r)), None, ((x1 - r, y1), (x0 + r, y1)), None,
            ((x0, y1 - r), (x0, y0 + r)), None]
    arcs = [(x1 - r, y0 + r, -90), (x1 - r, y1 - r, 0), (x0 + r, y1 - r, 90), (x0 + r, y0 + r, 180)]
    path = []
    for k in range(4):
        (ax, ay), (bx, by) = segs[2 * k]
        n = max(2, int(math.hypot(bx - ax, by - ay) / 0.5))
        path += [(ax + (bx - ax) * t, ay + (by - ay) * t) for t in np.linspace(0, 1, n, endpoint=False)]
        cx, cy, a0 = arcs[k]
        n = max(2, int(r * math.pi / 2 / 0.5))
        path += [(cx + r * math.cos(math.radians(a0 + 90 * t)), cy + r * math.sin(math.radians(a0 + 90 * t)))
                 for t in np.linspace(0, 1, n, endpoint=False)]
    P = np.array(path)
    seg = np.hypot(*np.diff(np.vstack([P, P[:1]]), axis=0).T)
    sl = np.concatenate([[0.0], np.cumsum(seg)])
    total = sl[-1]
    n = int(total // step)
    u = np.arange(n) * (total / n)
    Pc = np.vstack([P, P[:1]])
    return np.stack([np.interp(u, sl, Pc[:, 0]), np.interp(u, sl, Pc[:, 1])], -1)


def lacquer_gold(c: Cv, rarity: str):
    """描金：外沿一道细金边（离边 6），花边主线在节点内 8（贴图 16），里面一道细线（贴图 24）；
    天、合在外沿和主线之间串一圈连珠。四角的结：灵、玄是方胜（空心菱形，两线出头），天、合是如意结。返回金的覆盖度。"""
    w, h = c.w, c.h
    m = np.zeros(c.X.shape)
    d0 = rrect_sd(c.X, c.Y, 4, 3, w - 4, h - 5, 14)
    m = np.maximum(m, smoothstep(1.3 + c.aa, 1.3 - c.aa, np.abs(d0 + 3.2)))
    if rarity == "fan":
        d1 = rrect_sd(c.X, c.Y, 16, 16, w - 16, h - 16, 6)
        m = np.maximum(m, smoothstep(1.5 + c.aa, 1.5 - c.aa, np.abs(d1)))
        return m
    d1 = rrect_sd(c.X, c.Y, 16, 16, w - 16, h - 16, 5)
    m = np.maximum(m, smoothstep(2.1 + c.aa, 2.1 - c.aa, np.abs(d1)))
    d2 = rrect_sd(c.X, c.Y, 24, 24, w - 24, h - 24, 3)
    m = np.maximum(m, smoothstep(0.85 + c.aa, 0.85 - c.aa, np.abs(d2)))
    knots = []
    if rarity in ("tian", "he"):
        for (x, y) in rrect_points(10.5, 10.0, w - 10.5, h - 11.0, 9, 8.0):
            if min(x, w - x) < 26 and min(y, h - y) < 26:
                continue  # 角上让给如意结
            knots.append((np.array([[x, y], [x + 0.01, y]]), 2.4))
        for (sx, sy) in ((1, 1), (-1, 1), (1, -1), (-1, -1)):
            cx = 16 if sx > 0 else w - 16
            cy = 16 if sy > 0 else h - 16
            # 如意结：一个小圆环 + 两侧两朵小卷
            ring = spiral(cx, cy, 6.2, 6.2, 0, 1.0, 40)
            knots.append((ring, 1.6))
            for ang in (0, 90):
                a0 = math.radians(ang + (0 if sx > 0 else 180 - 2 * ang) + (0 if sy > 0 else 0))
                ux, uy = (sx * (1 if ang == 0 else 0), sy * (1 if ang == 90 else 0))
                px, py = cx + ux * 11.5, cy + uy * 11.5
                curl = spiral(px, py, 3.6, 1.2, math.atan2(-uy, -ux) if (ux or uy) else 0, 0.85, 24)
                knots.append((curl, 1.3))
            knots.append((np.array([[cx, cy], [cx + 0.01, cy]]), 2.6))
    else:
        for (sx, sy) in ((1, 1), (-1, 1), (1, -1), (-1, -1)):
            cx = 16 if sx > 0 else w - 16
            cy = 16 if sy > 0 else h - 16
            dia = np.array([[cx - 7, cy], [cx, cy - 7], [cx + 7, cy], [cx, cy + 7], [cx - 7, cy]], float)
            knots.append((dia, 1.5))
            knots.append((np.array([[cx, cy], [cx + 0.01, cy]]), 2.0))
            knots.append((np.array([[cx, cy - 7], [cx, cy - 12]]), 1.4))
            knots.append((np.array([[cx - 7 * sx, cy], [cx - 12 * sx, cy]]) if False else np.array([[cx - 7, cy], [cx - 12, cy]]), 1.4))
    for P, wd in knots:
        m = np.maximum(m, stroke_mask(c, P, wd))
    return m


def make_lacquer(rarity: str) -> Image.Image:
    R = RARITY[rarity]
    c = Cv(CW, CH, seed=700 + list(RARITY).index(rarity), ss=2)
    ds = rrect_sd(c.X, c.Y, 5, 6, CW - 5, CH - 3, 15)
    c.over(hexc("#000000"), 0.6 * np.exp(-np.maximum(ds, 0) ** 2 / (2 * 2.2 ** 2)) * (ds > -1))
    rgb, body, d = lacquer_surface(c, 4, 3, CW - 4, CH - 5, 14, rarity)
    # 内缘的光：细线以内一圈柔光（插画盖住上半，露出来的是两侧和下半张的边）
    d2 = rrect_sd(c.X, c.Y, 24, 24, CW - 24, CH - 24, 3)
    width = 18.0 if rarity in ("tian", "he") else 12.0
    inner = np.exp(-np.maximum(-d2 - 1.5, 0) / width) * (d2 < -0.8)
    wob = 0.8 + 0.2 * c.noise(40.0)
    gl = hexc(R["glow"])
    rgb = 1 - (1 - rgb) * (1 - gl * (R["glow_a"] * inner * wob)[..., None])
    if rarity in ("tian", "he"):  # 天：下半张再铺一层很淡的暖光，像金光从卡里透出来
        rgb = rgb + gl * 0.030 * np.exp(-np.maximum(-d2, 0) / 120.0)[..., None]
    c.over(np.clip(rgb, 0, 1), body)
    gm = lacquer_gold(c, rarity)
    if rarity == "fan":  # 凡：金磨得旧，露出一点漆
        worn = smoothstep(0.6, 0.9, V.rank01(c.noise(2.5)))
        gm = gm * (1 - 0.5 * worn)
    gold = metal(c, gm, R["gold"], sigma=0.7, depth=1.2, grain=0.05, seams=True)
    c.over(gold, gm * body)
    if rarity in ("tian", "he"):  # 洒金：细碎金箔，靠边多
        flake = np.zeros(c.X.shape)
        rng = c.rng
        for _ in range(260):
            x, y = rng.uniform(26, CW - 26), rng.uniform(26, CH - 26)
            dd = min(x, CW - x, y, CH - y)
            if rng.random() > math.exp(-dd / 60.0) * 0.85 + 0.06:
                continue
            rr = rng.uniform(0.5, 1.6)
            poly = [(x + rr * math.cos(a) * rng.uniform(0.5, 1.3), y + rr * math.sin(a) * rng.uniform(0.5, 1.3))
                    for a in np.sort(rng.uniform(0, 2 * math.pi, 5))]
            dist, _ = WT.poly_sdf(c.X, c.Y, poly, pad=2.0)
            flake = np.maximum(flake, smoothstep(c.aa, -c.aa, dist) * rng.uniform(0.5, 1.0))
        c.over(metal(c, flake, GOLD, sigma=0.35, grain=0.12, base=0.10), flake * body)
    return c.image()


def make_lacquer_focus() -> Image.Image:
    """焦点：比卡大一圈（每边逻辑 6），卡边上一道泥金亮线、往外一圈暖光，四角更亮。"""
    W_, H_ = CW + 2 * FOCUS_PAD, CH + 2 * FOCUS_PAD
    c = Cv(W_, H_, seed=760, ss=2)
    d = rrect_sd(c.X, c.Y, FOCUS_PAD + 4, FOCUS_PAD + 3, W_ - FOCUS_PAD - 4, H_ - FOCUS_PAD - 5, 14)
    glow = np.exp(-np.maximum(d, 0) ** 2 / (2 * 5.0 ** 2)) * (d > -2)
    cx = np.minimum(c.X, W_ - c.X)
    cy = np.minimum(c.Y, H_ - c.Y)
    corner = np.exp(-(cx ** 2 + cy ** 2) / (2 * 70.0 ** 2))
    c.over(hexc("#FFC062"), np.clip(0.75 * glow * (0.7 + 0.6 * corner), 0, 1))
    line = smoothstep(1.8 + c.aa, 1.8 - c.aa, np.abs(d + 1.0))
    c.over(hexc("#FFF0C0"), line)
    inner = np.exp(-np.maximum(-d, 0) / 9.0) * (d < 0)
    c.over(hexc("#FFD48A"), inner * 0.22)
    return c.image()


def make_tag(style: str, rarity: str) -> Image.Image:
    """品阶签（插画右上角）：漆是黑漆小牌 + 细金边，字用品阶色；绢是一张象牙色小纸签，品阶色的边。高 44（逻辑 22）。"""
    name = {"fan": "凡品", "ling": "灵品", "xuan": "玄品", "tian": "天品", "yi": "异化", "he": "合璧"}[rarity]
    col = {"fan": "#A9AEC2", "ling": "#6FB8FF", "xuan": "#B07CF0", "tian": "#FFD98A", "yi": "#CF8CDB", "he": "#F6BD62"}[rarity]
    tx_m, _ = text_mask(name, "serif", 24, pad=2)
    W_, H_ = tx_m.shape[1] + 30, 44
    c = Cv(W_, H_, seed=980, ss=3)
    d = rrect_sd(c.X, c.Y, 1.5, 1.5, W_ - 1.5, H_ - 1.5, 7)
    body = smoothstep(c.aa, -c.aa, d)
    if style == "lacquer":
        c.over(hexc("#0E0B09"), body * 0.92)
        rim = smoothstep(1.1 + c.aa, 1.1 - c.aa, np.abs(d + 1.6))
        c.over(metal(c, rim, GOLD if rarity != "fan" else GOLD_OLD, sigma=0.4), rim)
        tcol = col
    else:
        c.over(hexc("#F1E9D6"), body)
        rim = smoothstep(1.2 + c.aa, 1.2 - c.aa, np.abs(d + 1.8))
        dark = {"fan": "#5E6170", "ling": "#2F6FA8", "xuan": "#6A3FA8", "tian": "#B0731A", "yi": "#8E3E9A", "he": "#A8741E"}[rarity]
        c.over(hexc(dark), rim)
        tcol = dark
    im = c.image()
    t = plain_text(name, 24, tcol)
    paste(im, t, W_ / 2, H_ / 2, center=True)
    return im


# ============================================================== 绢本织锦

def meander(u, v):
    """回纹（一个周期）：u∈[0,1) 沿边、v∈[0,1] 跨带。返回 0/1 的线条。"""
    lw = 0.13
    lines = np.zeros_like(u)
    lines = np.maximum(lines, (np.abs(v - 0.08) < lw / 2) & (u < 0.86))
    lines = np.maximum(lines, (np.abs(u - 0.80) < lw / 2) & (v < 0.92))
    lines = np.maximum(lines, (np.abs(v - 0.86) < lw / 2) & (u > 0.24) & (u < 0.86))
    lines = np.maximum(lines, (np.abs(u - 0.30) < lw / 2) & (v > 0.36) & (v < 0.92))
    lines = np.maximum(lines, (np.abs(v - 0.40) < lw / 2) & (u > 0.24) & (u < 0.60))
    lines = np.maximum(lines, (np.abs(u - 0.06) < lw / 2) & (v > 0.02) & (v < 0.66))
    return lines.astype(np.float64)


def silk_field(c: Cv, x0, y0, x1, y1):
    """绢面：暖白，比宣纸细、亮；细经纬（3 像素一线，2 倍贴图）、偶有粗节，一道很淡的光泽，靠锦边略泛黄。"""
    base = hexc("#F4EEE2")
    warp = np.cos(c.X * (2 * math.pi / 3.0) + 0.6 * c.noise(24.0))
    weft = np.cos(c.Y * (2 * math.pi / 3.0) + 0.6 * c.noise(24.0))
    weave = 0.5 * warp * weft + 0.18 * (warp + weft)  # 平纹：经纬一上一下，交织点亮
    slub = smoothstep(0.80, 0.985, V.rank01(fft_blur(c.rng.standard_normal(c.X.shape), (46.0 * c.ss, 0.5 * c.ss))))
    cloud = V.fbm(c.rng, c.X.shape, (130.0 * c.ss, 50.0 * c.ss), (0.6, 0.4))
    rgb = base * (1 + 0.034 * weave + 0.010 * cloud)[..., None] - hexc("#2A2014") * 0.045 * slub[..., None]
    u = (c.X / c.w) * 0.55 + (c.Y / c.h) * 0.45
    rgb = rgb + hexc("#FFFFFF") * (0.040 * np.exp(-((u - 0.36) / 0.22) ** 2))[..., None]
    dd = rrect_sd(c.X, c.Y, x0, y0, x1, y1, 2)
    age = np.exp(-np.maximum(-dd, 0) / 20.0)
    rgb = mixc(rgb, hexc("#E0D0AE"), 0.40 * age)
    return np.clip(rgb, 0, 1)


def brocade_motif(u, v, rarity):
    """锦纹（一个周期的格子里，u、v ∈ [0,1)）：凡 菱纹绫，灵 龟背锦，玄 回纹，天 宝相小团花，异 火焰纹，合 方胜。"""
    if rarity == "fan":
        return smoothstep(0.07, 0.02, np.abs(np.abs(u - 0.5) + np.abs(v - 0.5) - 0.34))
    if rarity == "ling":  # 龟背：六边形网格 + 中心一点
        q = np.abs(np.stack([u - 0.5, (v - 0.5) * 1.155], 0))
        hexd = np.maximum(q[0] * 0.866 + q[1] * 0.5, q[1]) - 0.36
        return np.clip(smoothstep(0.05, 0.015, np.abs(hexd)) + smoothstep(0.08, 0.05, np.hypot(u - 0.5, v - 0.5)), 0, 1)
    if rarity == "xuan":
        return meander(u, v)
    if rarity == "yi":
        r = np.hypot(u - 0.5, v - 0.5)
        return smoothstep(0.05, 0.01, np.abs(r - 0.22 - 0.06 * np.sin(np.arctan2(v - 0.5, u - 0.5) * 5)))
    if rarity == "he":  # 方胜：两个交叠的菱形
        d1 = np.abs(u - 0.38) + np.abs(v - 0.5) - 0.24
        d2 = np.abs(u - 0.62) + np.abs(v - 0.5) - 0.24
        return np.clip(smoothstep(0.05, 0.015, np.abs(d1)) + smoothstep(0.05, 0.015, np.abs(d2)), 0, 1)
    # 天：宝相团花（八瓣）+ 花心 + 四角小花
    r = np.hypot(u - 0.5, v - 0.5)
    a = np.arctan2(v - 0.5, u - 0.5)
    petal = smoothstep(0.035, 0.0, r - (0.20 + 0.11 * np.abs(np.cos(a * 4))))
    hole = smoothstep(0.0, 0.03, r - (0.11 + 0.06 * np.abs(np.cos(a * 4))))
    dot = smoothstep(0.07, 0.04, r)
    corner = smoothstep(0.10, 0.05, np.minimum(np.minimum(np.hypot(u, v), np.hypot(1 - u, v)),
                                               np.minimum(np.hypot(u, 1 - v), np.hypot(1 - u, 1 - v))))
    return np.clip(petal * hole + dot + corner * 0.8, 0, 1)


def brocade_band(c: Cv, rarity, outer, inner, period=22.0, x_off=0.0):
    """织锦包边：outer / inner 是外、内两条边界的有向距离场（outer<0 在卡内，inner>0 在绢外）。
    锦地 + 锦纹（沿边平铺，周期 period）+ 斜纹组织 + 缎面光泽；外缘卷过板边（发暗），内缘压在绢上（投影）。"""
    R = RARITY[rarity]
    w, h = c.w, c.h
    band = smoothstep(c.aa, -c.aa, outer) * smoothstep(-c.aa, c.aa, inner)
    depth = (-outer) / np.maximum(-outer + inner, 1e-6)  # 0 外缘 → 1 内缘
    horiz = np.minimum(c.Y, h - c.Y) < np.minimum(c.X, w - c.X)
    along = np.where(horiz, c.X, c.Y) - x_off
    across = np.where(horiz, np.minimum(c.Y, h - c.Y), np.minimum(c.X, w - c.X))
    u = np.mod(along / period, 1.0)
    v = np.clip((across - 2.0) / period, 0, 0.999)
    motif = brocade_motif(u, v, rarity)
    base = hexc(R["brocade"])
    mcol = hexc(R["thread"] or R["motif"])
    twill = np.sin((c.X + c.Y) * (2 * math.pi / 2.6))
    twill2 = np.sin((c.X - c.Y) * (2 * math.pi / 2.6))
    rgb = base * (1.0 + 0.10 * twill)[..., None]
    rgb = mixc(rgb, mcol * (1.0 + 0.12 * twill2)[..., None], motif)
    if R["thread"]:  # 金线：亮一些，带一点闪
        sp = smoothstep(0.82, 1.0, V.rank01(c.noise(0.7)))
        rgb = rgb + hexc("#FFF2C8") * (0.28 * motif * sp)[..., None]
    sheen = np.exp(-((depth - 0.42) / 0.26) ** 2) * 0.14
    rgb = rgb * (1 + sheen)[..., None]
    roll = np.exp(-np.maximum(-outer, 0) / 2.0)
    rgb = rgb * (1 - 0.50 * roll)[..., None]
    rgb = rgb * (1 - 0.30 * np.exp(-np.maximum(inner, 0) / 1.4))[..., None]
    return np.clip(rgb, 0, 1), band


def silk_corners(c: Cv, rarity):
    """四角铜包角：贴着卡角的一块铜片（34×34），内角剪成一道如意弧；外沿起棱、里面錾一道线，角上一颗泡钉
    （灵、玄、异是珐琅泡钉）。天、合鎏金。返回 (颜色, 覆盖度)。"""
    R = RARITY[rarity]
    w, h = c.w, c.h
    L = 36.0
    t = np.linspace(0, 1, 60)
    # 内缘：从 (L, 0) 往里弯到 (0, L)，中间鼓出一个如意头
    ang = t * math.pi / 2
    rad = (L - 12.0) + 5.0 * np.sin(t * math.pi) ** 2 - 4.0 * np.sin(t * math.pi * 3) ** 2 * np.sin(t * math.pi)
    ix = L - rad * np.sin(ang) * 0 + (rad * np.cos(ang)) * 0
    ix = (L) * np.cos(ang) ** 1.0 * (rad / (L - 12.0)) * 0.70 + 8.0 * np.cos(ang)
    iy = (L) * np.sin(ang) ** 1.0 * (rad / (L - 12.0)) * 0.70 + 8.0 * np.sin(ang)
    poly0 = [(L + 2, -6)] + list(zip(ix * 0 + np.maximum(ix, 0), np.maximum(iy, 0))) + [(-6, L + 2), (-6, -6)]
    plate = np.zeros(c.X.shape)
    edge_d = np.full(c.X.shape, 1e3)
    for sx in (1, -1):
        for sy in (1, -1):
            P = np.array(poly0, float)
            if sx < 0:
                P[:, 0] = w - P[:, 0]
            if sy < 0:
                P[:, 1] = h - P[:, 1]
            dist, _ = WT.poly_sdf(c.X, c.Y, P, pad=4.0)
            plate = np.maximum(plate, smoothstep(c.aa, -c.aa, dist))
            edge_d = np.minimum(edge_d, dist)
    card = rrect_sd(c.X, c.Y, 3, 3, w - 3, h - 4, 10)
    plate = plate * smoothstep(c.aa, -c.aa, card)
    edge_all = np.maximum(edge_d, card)
    rim = smoothstep(0.0, 2.2, -edge_all) * (1 - 0.6 * smoothstep(3.0, 5.0, -edge_all))
    groove = np.exp(-((-edge_d - 7.0) / 0.8) ** 2) * (edge_d < -5)
    height = plate * (0.55 + 0.45 * rim) - 0.35 * groove * plate
    nail = np.zeros(c.X.shape)
    centers = []
    for sx in (1, -1):
        for sy in (1, -1):
            px, py = (12.5 if sx > 0 else w - 12.5), (12.5 if sy > 0 else h - 12.5)
            centers.append((px, py))
            r2 = ((c.X - px) ** 2 + (c.Y - py) ** 2) / 5.2 ** 2
            nail = np.maximum(nail, np.clip(1 - r2, 0, 1) ** 0.5)
    height = height + 0.85 * nail
    col = metal(c, height, R["corner"], sigma=0.7, depth=1.6, grain=0.06)
    if R["corner"] is not GILT:  # 錾线里的铜锈
        pat = groove * plate * smoothstep(0.3, 0.8, V.rank01(c.noise(5.0)))
        col = mixc(col, hexc("#3E7A68"), 0.55 * pat)
    if R["enamel"]:  # 珐琅泡钉：一颗彩色的小圆顶
        en = np.zeros(c.X.shape)
        for (px, py) in centers:
            en = np.maximum(en, smoothstep(4.0 + c.aa, 4.0 - c.aa, np.hypot(c.X - px, c.Y - py)))
        sh = emboss(c, en, sigma=1.2, depth=0.9)
        ecol = hexc(R["enamel"])
        col = mixc(col, mixc(ecol * 0.55, mixc(ecol, hexc("#FFFFFF"), 0.45), sh), en)
    return col, plate


def make_silk(rarity: str) -> Image.Image:
    c = Cv(CW, CH, seed=800 + list(RARITY).index(rarity), ss=2)
    ds = rrect_sd(c.X, c.Y, 4, 6, CW - 4, CH - 2, 11)
    c.over(hexc("#000000"), 0.6 * np.exp(-np.maximum(ds, 0) ** 2 / (2 * 2.2 ** 2)) * (ds > -1))
    outer = rrect_sd(c.X, c.Y, 3, 3, CW - 3, CH - 4, 10)
    inner = rrect_sd(c.X, c.Y, 22, 22, CW - 22, CH - 22, 3)
    body = smoothstep(c.aa, -c.aa, outer)
    silk = silk_field(c, 25, 25, CW - 25, CH - 25)
    shade = np.exp(-np.maximum(-inner, 0) / 3.5) * (inner < 0)
    silk = silk * (1 - 0.20 * shade)[..., None]
    c.over(silk, body)
    brc, band = brocade_band(c, rarity, outer, inner, x_off=22.0)
    c.over(brc, band)
    # 内缘一道细绦（象牙色；天、合泥金）
    pip = smoothstep(1.5 + c.aa, 1.5 - c.aa, np.abs(inner + 2.0))
    if rarity in ("tian", "he"):
        pip_col = metal(c, pip, GILT, sigma=0.4)
    else:
        pip_col = mixc(hexc("#EDE4CC"), hexc("#B8AC92"), 0.5 + 0.2 * np.sin(c.X * 1.3 + c.Y * 1.3))
    c.over(pip_col, pip * body)
    col, plate = silk_corners(c, rarity)
    sh = fft_blur(plate, 1.6 * c.ss)
    c.over(hexc("#000000"), 0.45 * np.clip(sh - plate, 0, 1))
    c.over(col, plate)
    return c.image()


def make_silk_focus() -> Image.Image:
    W_, H_ = CW + 2 * FOCUS_PAD, CH + 2 * FOCUS_PAD
    c = Cv(W_, H_, seed=860, ss=2)
    d = rrect_sd(c.X, c.Y, FOCUS_PAD + 3, FOCUS_PAD + 3, W_ - FOCUS_PAD - 3, H_ - FOCUS_PAD - 4, 10)
    glow = np.exp(-np.maximum(d, 0) ** 2 / (2 * 5.5 ** 2)) * (d > -2)
    c.over(hexc("#FFD07A"), 0.80 * glow)
    line = smoothstep(1.7 + c.aa, 1.7 - c.aa, np.abs(d + 0.8))
    c.over(hexc("#FFF4D2"), line)
    return c.image()


# ============================================================== 卡面元素

def stat_icon(key: str, size: int = 64) -> Image.Image:
    """数值小图标（白色，界面里染色）：speed 三道风、orbit 一团火与绕它的环、freeze 六出冰花。"""
    c = Cv(size, size, seed=950, ss=4)
    m = np.zeros(c.X.shape)
    s = size / 64.0
    if key == "speed":
        for i, (y, x0, x1, hw) in enumerate(((20, 8, 52, 3.4), (32, 4, 58, 3.6), (44, 12, 50, 3.0))):
            pts = bez([(x0 * s, (y + 4) * s), ((x0 + x1) / 2 * s, (y - 2) * s), (x1 * s, y * s), ((x1 + 2) * s, (y - 7) * s)], 40)
            hwv = hw * s * np.interp(np.linspace(0, 1, 40), [0, 0.2, 0.8, 1], [0.4, 1.0, 1.0, 0.5])
            m = np.maximum(m, stroke_mask(c, pts, hwv))
        m = np.maximum(m, stroke_mask(c, spiral(52 * s, 22 * s, 6 * s, 1.5 * s, math.radians(90), 0.8, 30, sx=-1), 2.6 * s))
    elif key == "orbit":
        fl = [(32, 14), (40, 26), (41, 36), (36, 44), (32, 46), (26, 44), (22, 37), (24, 28), (28, 32), (30, 22)]
        dist, _ = WT.poly_sdf(c.X, c.Y, [(x * s, y * s) for x, y in fl], pad=3)
        m = np.maximum(m, smoothstep(c.aa, -c.aa, dist))
        e = np.hypot((c.X - 32 * s) / (27 * s), (c.Y - 38 * s) / (10 * s))
        ring = smoothstep(0.075 + 0.03, 0.075 - 0.03, np.abs(e - 1.0)) * ((c.Y > 38 * s) | (np.abs(c.X - 32 * s) > 17 * s))
        m = np.maximum(m, ring)
        for ang in (200, 340):
            px = 32 + 27 * math.cos(math.radians(ang))
            py = 38 + 10 * math.sin(math.radians(ang))
            m = np.maximum(m, smoothstep(4.4 * s, 3.6 * s, np.hypot(c.X - px * s, c.Y - py * s)))
    elif key == "freeze":
        cx, cy = 32 * s, 32 * s
        for k in range(6):
            a = math.radians(90 + 60 * k)
            tip = (cx + 26 * s * math.cos(a), cy + 26 * s * math.sin(a))
            m = np.maximum(m, stroke_mask(c, [(cx, cy), tip], 2.6 * s))
            for f in (0.55, 0.78):
                bx, by = cx + 26 * s * f * math.cos(a), cy + 26 * s * f * math.sin(a)
                for sg in (-1, 1):
                    b2 = a + sg * math.radians(55)
                    L = (8 if f < 0.6 else 5.5) * s
                    m = np.maximum(m, stroke_mask(c, [(bx, by), (bx + L * math.cos(b2), by + L * math.sin(b2))], 2.0 * s))
        m = np.maximum(m, smoothstep(5.5 * s, 4.5 * s, np.hypot(c.X - cx, c.Y - cy)))
    c.over(np.ones(3), m)
    return c.image()


ELEMENT = {"wood": ("木", "#3F7556"), "fire": ("火", "#BC3424"), "water": ("水", "#2F5584"), "metal": ("金", "#A9862C"),
           "earth": ("土", "#9A6A36")}


def element_seal(el: str, size: int = 60, seed: int = 0) -> Image.Image:
    """五行小印：方印、白文（字留白），印边略不齐，印泥有轻重和没印上的白点。颜色按五行。"""
    ch, hx = ELEMENT[el]
    check_text(ch, brush=True)
    ss = 4
    n = size * ss
    rng = np.random.default_rng(31 + seed)
    Y, X = np.mgrid[0:n, 0:n].astype(np.float64) + 0.5
    cc = n / 2
    wob = 0.010 * n * noise(rng, (n, n), n * 0.07)
    d = np.maximum(np.abs(X - cc), np.abs(Y - cc)) + wob - n * 0.44
    plate = smoothstep(1.5 * ss, -1.5 * ss, d)
    gl = Image.new("L", (n, n), 0)
    dr = ImageDraw.Draw(gl)
    f = font("brush", n * 0.78)
    bb = dr.textbbox((0, 0), ch, font=f)
    dr.text((cc - (bb[2] - bb[0]) / 2 - bb[0], cc - (bb[3] - bb[1]) / 2 - bb[1]), ch, font=f, fill=255)
    g = np.asarray(gl.filter(ImageFilter.GaussianBlur(0.6 * ss)), np.float64) / 255.0
    carve = smoothstep(0.35, 0.6, g + 0.15 * noise(rng, (n, n), 1.6 * ss) * g * (1 - g) * 4)
    ink = 0.88 + 0.08 * noise(rng, (n, n), 8.0 * ss) + 0.05 * noise(rng, (n, n), 1.4 * ss)
    specks = smoothstep(2.1, 2.6, noise(rng, (n, n), 1.3 * ss))
    a = plate * (1 - carve) * np.clip(ink, 0, 1) * (1 - specks)
    rim = smoothstep(-5 * ss, -0.5 * ss, d) * plate
    col = mixc(hexc(hx), hexc(hx) * 0.65, 0.5 * rim)
    lay = V.Layer(n, n)
    lay.over(col, a)
    lay = lay.down(ss)
    rgb, al = lay.straight()
    return V.to_rgba8(rgb, al)


def text_mask(s: str, kind: str, size: float, pad: int = 8):
    """文字的覆盖度（numpy，0..1）与字框。"""
    check_text(s, brush=(kind == "brush"))
    f = font(kind, size)
    bb = f.getbbox(s)
    w, h = bb[2] - bb[0] + 2 * pad, bb[3] - bb[1] + 2 * pad
    im = Image.new("L", (w, h), 0)
    ImageDraw.Draw(im).text((pad - bb[0], pad - bb[1]), s, font=f, fill=255)
    return np.asarray(im, np.float64) / 255.0, (bb, pad)


def gold_text(s: str, size: float, stops=GOLD, kind="brush") -> Image.Image:
    """描金字：文字遮罩按浮雕打光，查金色带；下面垫一层很淡的暗影，压在漆面上更清楚。"""
    m, _ = text_mask(s, kind, size * 2)  # 先放大一倍画，再缩回（边缘更顺）
    h, w = m.shape
    c = Cv(w // 2, h // 2, seed=990, ss=2)
    mm = np.asarray(Image.fromarray((m * 255).astype(np.uint8)).resize((c.w * 2, c.h * 2), Image.LANCZOS), np.float64) / 255.0
    sh = fft_blur(mm, 2.5 * c.ss)
    c.over(hexc("#000000"), 0.65 * np.clip(np.roll(np.roll(sh, 2 * c.ss, 0), 1 * c.ss, 1), 0, 1))
    col = metal(c, mm, stops, sigma=0.8, depth=1.4, grain=0.04, base=0.04)
    c.over(col, mm)
    return c.image()


def plain_text(s: str, size: float, color: str, kind="serif", shadow: str | None = None) -> Image.Image:
    m, _ = text_mask(s, kind, size)
    h, w = m.shape
    lay = V.Layer(h, w)
    if shadow:
        lay.over(hexc(shadow), 0.5 * np.clip(fft_blur(m, 1.5), 0, 1))
    lay.over(hexc(color), m)
    rgb, a = lay.straight()
    return V.to_rgba8(rgb, a)


def level_dots(style: str, cur: int, mx: int) -> Image.Image:
    """等级点（选完以后的等级）：逻辑 10×10、间距 6（贴图 20、12）。这次升上的那一点带一圈光。"""
    step, r = 32, 10.0
    W_, H_ = int(step * mx + 16), 40
    c = Cv(W_, H_, seed=970, ss=4)
    for i in range(mx):
        cx, cy = 8 + step * i + step / 2, H_ / 2
        d = np.hypot(c.X - cx, c.Y - cy)
        on, new = i < cur, i == cur - 1
        m = smoothstep(r + 0.5, r - 0.5, d)
        if new:
            c.over(hexc("#FFC86A" if style == "lacquer" else "#E2862C"), 0.55 * np.exp(-(d / (r * 1.7)) ** 2))
        if style == "lacquer":
            if on:
                c.over(metal(c, m, GOLD, sigma=1.4, depth=1.3, base=0.06 if new else 0.0), m)
            else:
                ringm = smoothstep(1.5, 0.6, np.abs(d - r + 0.9))
                c.over(hexc("#070504"), m * 0.85)
                c.over(metal(c, ringm, GOLD_OLD, sigma=0.5), ringm * 0.9)
        else:
            if on:
                c.over(hexc("#B8402A") if new else hexc("#2A241E"), m)
            else:
                c.over(hexc("#6A5F50"), smoothstep(1.4, 0.5, np.abs(d - r + 0.9)))
    return c.image()


def keycap(style: str, label: str, size: int = 40) -> Image.Image:
    """按键提示（简画）：圆角小方块里一个字。"""
    c = Cv(size, size, seed=975, ss=3)
    d = rrect_sd(c.X, c.Y, 2, 2, size - 2, size - 2, 7)
    rim = smoothstep(1.3 + c.aa, 1.3 - c.aa, np.abs(d + 1.5))
    if style == "lacquer":
        c.over(hexc("#0C0907"), smoothstep(c.aa, -c.aa, d) * 0.9)
        c.over(metal(c, rim, GOLD_OLD, sigma=0.4), rim)
        col = "#CDB27C"
    else:
        c.over(hexc("#E9E0CC"), smoothstep(c.aa, -c.aa, d))
        c.over(hexc("#6A5F50"), rim)
        col = "#3A322A"
    im = c.image()
    paste(im, plain_text(label, size * 0.62, col), size / 2, size / 2, center=True)
    return im


def paste(base: Image.Image, im: Image.Image, x: float, y: float, center=False):
    x, y = int(round(x)), int(round(y))
    if center:
        x, y = x - im.width // 2, y - im.height // 2
    x0, y0 = max(x, 0), max(y, 0)
    x1, y1 = min(x + im.width, base.width), min(y + im.height, base.height)
    if x1 <= x0 or y1 <= y0:
        return
    base.alpha_composite(im.crop((x0 - x, y0 - y, x1 - x, y1 - y)), (x0, y0))


def tint(im: Image.Image, hx: str, alpha: float = 1.0) -> Image.Image:
    a = np.asarray(im, np.float64)
    a[..., :3] = a[..., :3] * hexc(hx)
    a[..., 3] = a[..., 3] * alpha
    return Image.fromarray(np.round(a).astype(np.uint8), "RGBA")


def fade(im: Image.Image, alpha: float) -> Image.Image:
    a = np.asarray(im, np.float64).copy()
    a[..., 3] *= alpha
    return Image.fromarray(np.round(a).astype(np.uint8), "RGBA")


def rounded(im: Image.Image, r: int) -> Image.Image:
    """插画按圆角裁切（模拟界面的 border_radius + overflow clip）。"""
    w, h = im.size
    ss = 4
    m = Image.new("L", (w * ss, h * ss), 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, w * ss - 1, h * ss - 1), radius=r * ss, fill=255)
    m = m.resize((w, h), Image.LANCZOS)
    out = im.copy()
    a = np.asarray(out, np.float64)
    a[..., 3] = a[..., 3] * (np.asarray(m, np.float64) / 255.0)
    return Image.fromarray(np.round(a).astype(np.uint8), "RGBA")


# ============================================================== 一张卡

ITEM_COLOR = {"wood": "#82A489", "fire": "#EA7841", "water": "#6B8EAB"}
CARDS = [
    dict(id="jixing", name="疾行", gain="移动速度 +8%", el="wood", rarity="fan", lv=(3, 5), kind="心法",
         note=("木 2 → 3", None), pair=None,
         caption="移动速度 +8%。风属木：脚下生风，妖就追不上。"),
    dict(id="lamp", name="灯火", gain="火环绕身，烧近身妖", el="fire", rarity="ling", lv=(1, 8), kind="新法器",
         note=("火 1 → 2", None), pair=("icon_changming", False),
         caption="火焰环绕周身，烧灼靠近的妖物。　进化需心法「长明」"),
    dict(id="bell_evo", name="寒山钟", gain="每 6 秒全屏冻结", el="water", rarity="tian", lv=None, kind="进化",
         note=("选择后立即进化", "#FFD98A"), pair=("icon_jingxin", True),
         caption="每 6 秒钟鸣全屏，冻结所有妖物。　霜铃 Lv8 + 静心"),
]
UI_ICONS = ART / "out" / "assets@2x" / "ui"


def card_face(style: str, card: dict, pieces: dict, focus: bool = False, index: int = 0) -> Image.Image:
    """一张卡（贴图 2 倍，600×920；焦点时外面多一圈，整张 624×944，卡在 (12, 12)）。
    按 973feef 的骨架排：插画区 → 卡名 / 收益 / 等级点 / 提示（在插画和页脚之间居中）→ 页脚。"""
    r = card["rarity"]
    P = FOCUS_PAD
    im = Image.new("RGBA", (CW + 2 * P, CH + 2 * P), (0, 0, 0, 0))
    im.alpha_composite(pieces[f"card_{r}"], (P, P))
    ax0, ay0, ax1, ay1 = ART_BOX
    art = Image.open(REVIEW / f"card_art_{card['id']}.png").convert("RGBA").resize((ax1 - ax0, ay1 - ay0), Image.LANCZOS)
    im.alpha_composite(rounded(art, 12), (P + ax0, P + ay0))
    seal = element_seal(card["el"], 68, seed=len(card["id"]))
    paste(im, seal, P + ax0 + 16, P + ay0 + 16)
    tag = pieces[f"card_tag_{r}"]
    paste(im, tag, P + ax1 - 16 - tag.width, P + ay0 + 16)
    lac = style == "lacquer"
    icol = hexc(ITEM_COLOR[card["el"]])
    gain_col = "#%02X%02X%02X" % tuple(int(v * 255) for v in (mixc(icol, hexc("#F2E8D2"), 0.55) if lac else mixc(icol, hexc("#17140F"), 0.45)))
    if lac:
        nm = gold_text(card["name"], 60, GOLD if r != "fan" else GOLD_OLD)
    else:
        nm = plain_text(card["name"], 60, "#1C1814", kind="brush")
    gn = plain_text(card["gain"], 44, gain_col, kind="brush", shadow="#000000" if lac else None)
    rows = [(nm, 0), (gn, 6)]
    if card["lv"]:
        rows.append((level_dots(style, *card["lv"]), 18))
    if card["note"]:
        t, colr = card["note"]
        if colr and not lac:  # 绢底上亮金看不清，换深一点的金
            colr = "#A0681A"
        rows.append((plain_text(t, 30, colr or ("#9C8F78" if lac else "#6A5F50"), shadow="#000000" if lac else None), 14))
    total = sum(x.height + gap for x, gap in rows)
    foot_top = CH - PAD_B - 60
    y = ay1 + (foot_top - ay1 - total) / 2
    for x, gap in rows:
        y += gap
        paste(im, x, P + CW / 2 - x.width / 2, P + y)
        y += x.height
    # 页脚：类别（左）；进化配对的小图标 + 按键（右）
    fy = P + foot_top + 30
    lab = plain_text(card["kind"], 24, "#8E8066" if lac else "#6A5F50")
    paste(im, lab, P + PAD + 20, fy - lab.height / 2)
    kc = keycap(style, str(index + 1))
    xr = P + CW - PAD - 20
    paste(im, kc, xr - kc.width, fy - kc.height / 2)
    if card["pair"]:
        icon_name, owned = card["pair"]
        ic = Image.open(UI_ICONS / f"{icon_name}.png").convert("RGBA").resize((60, 60), Image.LANCZOS)
        paste(im, fade(ic, 1.0 if owned else 0.5), xr - kc.width - 16 - 60, fy - 30)
    if focus:
        im.alpha_composite(pieces["card_focus"])
    return im


# ============================================================== 九宫格件

RARITIES = ("fan", "ling", "xuan", "tian", "yi", "he")


def build_pieces() -> dict:
    t0 = time.perf_counter()
    P = {}
    for style in ("lacquer", "silk"):
        for r in RARITIES:
            P[(style, f"card_{r}")] = make_lacquer(r) if style == "lacquer" else make_silk(r)
            P[(style, f"card_tag_{r}")] = make_tag(style, r)
        P[(style, "card_focus")] = make_lacquer_focus() if style == "lacquer" else make_silk_focus()
    for k in ("speed", "orbit", "freeze"):
        P[("common", f"stat_{k}")] = stat_icon(k)
    for el in ELEMENT:
        P[("common", f"seal_el_{el}")] = element_seal(el, 68)
    print(f"[pieces] {time.perf_counter() - t0:.1f}s")
    return P


def save_pieces(P: dict):
    notes = {"fan": "凡品", "ling": "灵品", "xuan": "玄品", "tian": "天品", "yi": "异化（参考，界面暂用 card_xuan）",
             "he": "合璧（参考，界面暂用 card_tian）"}
    for style in ("lacquer", "silk", "common"):
        d = SKIN_OUT / style
        d.mkdir(parents=True, exist_ok=True)
        items = {}
        for (st, name), img in P.items():
            if st != style:
                continue
            img.save(d / f"{name}.png", optimize=True)
            if name.startswith("card_tag_"):
                slc, note = [16, 0, 16, 0], "品阶签：" + notes[name[9:]][:2]
            elif name == "card_focus":
                slc, note = [SL + FOCUS_PAD] * 4, "卡片焦点：比卡大一圈（每边逻辑 6），叠在卡上"
            elif name.startswith("card_"):
                slc, note = [SL] * 4, "升级卡框：" + notes[name[5:]]
            elif name.startswith("stat_"):
                slc, note = [0] * 4, "数值小图标：白色，界面染色，原图 64²、显示 32"
            else:
                slc, note = [0] * 4, "五行印：插画左上角，原图 68²、显示 34"
            items[name] = {"file": f"{name}.png", "size": [img.width, img.height], "slice": slc, "center": "stretch",
                           "sides": "stretch", "note": note}
        lines = ["{", '  "scale": 2,', '  "items": {']
        names = list(items)
        for i, n in enumerate(names):
            lines.append(f"    {json.dumps(n, ensure_ascii=False)}: {json.dumps(items[n], ensure_ascii=False)}" +
                         ("," if i < len(names) - 1 else ""))
        lines += ["  }", "}"]
        (d / "skin.json").write_text("\n".join(lines) + "\n", encoding="utf-8")


def load_pieces() -> dict:
    """读已经出好的九宫格件（只改排版时用）。"""
    P = {}
    for style in ("lacquer", "silk", "common"):
        for f in sorted((SKIN_OUT / style).glob("*.png")):
            P[(style, f.stem)] = Image.open(f).convert("RGBA")
    return P


def pieces_for(P: dict, style: str) -> dict:
    return {name: img for (st, name), img in P.items() if st in (style, "common")}


# ============================================================== 全景样张

def game_backdrop(size=(1920, 1080)) -> Image.Image:
    """暗下来的游戏画面：夜景截图转成更亮的月夜蓝调，略糊，再压暗（同游戏的压暗层），四周压一点墨。"""
    W_, H_ = size
    src = Image.open(REVIEW / "night_scene.png").convert("RGB")
    sw, sh = src.size
    k = max(W_ / sw, H_ / sh)
    src = src.resize((int(sw * k + 0.5), int(sh * k + 0.5)), Image.LANCZOS)
    x0, y0 = (src.width - W_) // 2, (src.height - H_) // 2
    src = src.crop((x0, y0, x0 + W_, y0 + H_))
    a = np.asarray(src, np.float64) / 255.0
    lin = np.where(a <= 0.04045, a / 12.92, ((a + 0.055) / 1.055) ** 2.4)
    lin = lin * np.array([1.25, 1.35, 1.6]) + np.array([0.020, 0.030, 0.060])
    a = np.where(lin <= 0.0031308, 12.92 * lin, 1.055 * np.power(np.clip(lin, 0, None), 1 / 2.4) - 0.055)
    img = Image.fromarray((np.clip(a, 0, 1) * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(3.0 * W_ / 1920))
    a = np.asarray(img, np.float64) / 255.0
    a = a * (1 - 0.62) + np.array([0.03, 0.04, 0.07]) * 0.62
    yy, xx = np.mgrid[0:H_, 0:W_]
    vig = ((xx - W_ / 2) / (W_ / 2)) ** 2 + ((yy - H_ / 2) / (H_ / 2)) ** 2
    a = a * (1 - 0.35 * np.clip(vig - 0.25, 0, 1))[..., None]
    return Image.fromarray((np.clip(a, 0, 1) * 255).astype(np.uint8)).convert("RGBA")


def button(style: str, label: str, w: int, h: int) -> Image.Image:
    """底部按钮（简画）：漆是黑漆圆角牌 + 细金边；绢是一块绢面 + 一圈素锦边。"""
    c = Cv(w, h, seed=990 + len(label), ss=2)
    d = rrect_sd(c.X, c.Y, 2, 2, w - 2, h - 2, h * 0.24)
    body = smoothstep(c.aa, -c.aa, d)
    if style == "lacquer":
        rgb, _, _ = lacquer_surface(c, 2, 2, w - 2, h - 2, h * 0.24, "fan")
        c.over(rgb, body)
        gm = smoothstep(1.6 + c.aa, 1.6 - c.aa, np.abs(d + 6.0))
        c.over(metal(c, gm, GOLD_OLD, sigma=0.5), gm)
        tx = plain_text(label, h * 0.36, "#E6DCC6", shadow="#000000")
    else:
        inner = rrect_sd(c.X, c.Y, 10, 10, w - 10, h - 10, h * 0.16)
        c.over(silk_field(c, 10, 10, w - 10, h - 10), body)
        brc, band = brocade_band(c, "fan", d, inner, period=18.0)
        c.over(brc, band)
        tx = plain_text(label, h * 0.36, "#2A241E")
    im = c.image()
    paste(im, tx, w / 2, h / 2, center=True)
    return im


def mock_screen(style: str, P: dict) -> Image.Image:
    """1920×1080 升级页：按 973feef 的竖排（页头、三张卡、聚焦卡说明、操作提示、按钮），逻辑尺寸 ×1.5。"""
    pc = pieces_for(P, style)
    scr = game_backdrop()
    k = 1.5
    # 页头
    wash = Image.open(ART / "out" / "assets@2x" / "ui_wash" / "ink_wash.png").convert("RGBA")
    wash = tint(wash.resize((520, 160), Image.LANCZOS), "#05070C", 0.75)
    paste(scr, wash, 960, 62, center=True)
    title = gold_text("升级", 48 * k, GOLD) if style == "lacquer" else plain_text("升级", 48 * k, "#F2EBDC", kind="brush",
                                                                                  shadow="#000000")
    paste(scr, title, 960, 58, center=True)
    paste(scr, plain_text("Lv 12 → 13", 18 * k, "#A9A08E", shadow="#000000"), 960, 122, center=True)
    # 三张卡
    cw, chh, gap = int(300 * k), int(460 * k), int(20 * k)
    x0 = 960 - (3 * cw + 2 * gap) / 2
    y0 = 156
    for i, card in enumerate(CARDS):
        face = card_face(style, card, pc, focus=(i == 1), index=i)
        fw = int(round(face.width * k / 2))
        face = face.resize((fw, int(round(face.height * k / 2))), Image.LANCZOS)
        off = FOCUS_PAD * k / 2
        paste(scr, face, x0 + i * (cw + gap) - off, y0 - off)
    # 聚焦卡的说明、操作提示、按钮
    y = y0 + chh + 18
    paste(scr, plain_text(CARDS[1]["caption"], 16 * k, "#E9E2D2", shadow="#000000"), 960, y + 34, center=True)
    y += 67 + 18
    paste(scr, plain_text("← → 选择　↑ ↓ 切换卡片与操作　空格 确定", 17 * k, "#8E8576", shadow="#000000"), 960, y + 18, center=True)
    y += 36 + 18
    labels = ["重抽（剩 2 次）", "封印第 1 项（剩 1 次）", "跳过（灯油 +10）"]
    bw, bh, bg = int(240 * k), 66, int(16 * k)
    bx0 = 960 - (3 * bw + 2 * bg) / 2
    for j, lab in enumerate(labels):
        b = button(style, check_text(lab), bw * 2, bh * 2).resize((bw, bh), Image.LANCZOS)
        paste(scr, b, bx0 + j * (bw + bg), y)
    return scr.convert("RGB")


def zoom_sheet(P: dict) -> Image.Image:
    """天品寒山钟两种画法，按贴图原尺寸（600×920，即 1440p 下的实际像素，1080p 的 1.33 倍）并排。"""
    card = CARDS[2]
    a = card_face("lacquer", card, pieces_for(P, "lacquer"), index=2)
    b = card_face("silk", card, pieces_for(P, "silk"), index=2)
    W_, H_ = a.width * 2 + 100, a.height + 110
    bg = game_backdrop((W_, H_))
    paste(bg, a, 30, 80)
    paste(bg, b, a.width + 70, 80)
    for i, lab in enumerate(("黑漆描金", "绢本织锦")):
        paste(bg, plain_text(lab, 32, "#E6DCC6", shadow="#000000"), 30 + i * (a.width + 40) + a.width / 2, 44, center=True)
    return bg.convert("RGB")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pieces", action="store_true", help="只出九宫格件")
    ap.add_argument("--reuse", action="store_true", help="不重画九宫格件，读 out/skin_card/ 里已有的")
    a = ap.parse_args(argv)
    if a.reuse:
        P = load_pieces()
    else:
        P = build_pieces()
        save_pieces(P)
    if a.pieces:
        return 0
    REVIEW.mkdir(parents=True, exist_ok=True)
    for style in ("lacquer", "silk"):
        t0 = time.perf_counter()
        mock_screen(style, P).save(REVIEW / f"card_sample_{style}.png", optimize=True)
        print(f"[{style}] {time.perf_counter() - t0:.1f}s")
    zoom_sheet(P).save(REVIEW / "card_sample_zoom.png", optimize=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
