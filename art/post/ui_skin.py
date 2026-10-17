#!/usr/bin/env python3
"""提灯夜行 · 桌面版界面皮肤：九宫格切片的水墨贴图（只用 Pillow + numpy）。

“灯照见画”：界面是宣纸、墨笔和一点朱砂、泥金。面板是毛边宣纸，按钮是一笔横扫的浓墨或朱砂，
卡片是带墨框的纸笺，进度条是一笔颜料，焦点是泥金的笔触。和 ui_icons.py 的图标出自同一只手：
一笔写成、起笔圆钝、收笔飞白。

只给桌面版用，与 LANTERN_ART_DENSITY 无关：所有尺寸按 1080p 逻辑像素的 2 倍画（SCALE = 2，
例如逻辑 300×420 的卡片画成 600×840）。游戏里用 Bevy 的 ImageNode + TextureSlicer：
  - border = skin.json 里的 slice [左, 上, 右, 下]（贴图像素）；
  - max_corner_scale = 0.5（2 倍贴图 → 逻辑像素）；
  - center / sides 为 "tile" 时用 SliceScaleMode::Tile { stretch_value: 0.5 }，"stretch" 时用 Stretch；
  - slice 全为 0 的是固定尺寸的整图（不切片）；
  - 横向九宫格（上下 slice 为 0）的高度应不超过贴图高度的一半（逻辑像素），否则两端会被竖向拉长。
复用 vfx_textures / weapon_textures 里与密度无关的工具（噪声、模糊、笔毛纹理、预乘图层）；
与密度有关的几样（宣纸纤维、透明区扩色）在这里按固定的 2 倍重写。

约定：
  - PNG 为直通（非预乘）alpha，颜色已向全透明区域扩展；固定种子，重复运行逐字节相同。
  - 平铺区（tile）四边周期接缝；拉伸带（stretch）沿拉伸方向逐列（逐行）完全相同，拉多长都不变形。
  - 横向拉伸的条（按钮、进度条、提示条）两端的笔头都在切片以内，中段只有横向的笔毛纹。

输出：art/out/skin/<name>.png + skin.json
检查图：art/out/review@2x/ui_skin_sheet.png（每件按 nine_slice 摆 2–3 种尺寸，夜色底和纸色底各一遍）
用法（在仓库根目录下）：
  art/.venv/bin/python art/post/ui_skin.py
  art/.venv/bin/python art/post/test_ui_skin.py
"""

from __future__ import annotations

import json
import math
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import vfx_textures as V  # noqa: E402  只用与密度无关的工具
import weapon_textures as W  # noqa: E402
import ui_lacquer as LQ  # noqa: E402  黑漆描金的件（升级卡、状态栏），试玩第 1 轮选定

S = V.S
SCALE = 2
SKIN_DIR = V.OUT / "skin"
REVIEW_PATH = V.OUT / "review@2x" / "ui_skin_sheet.png"

col, mixc, smoothstep = V.col, W.mixc, V.smoothstep
fft_blur, noise, rank01 = V.fft_blur, V.noise, V.rank01

# ============================================================== 颜色（取自 style.py）

WHITE = V.WHITE
PAPER, PAPER_SH = W.PAPER, W.PAPER_SH
PAPER_LT = col("#F8F2E4")  # 宣纸迎光的亮处（与 vfx_textures.make_paper 相同）
JIAO, NONG, ZHONG, DAN, QING = W.JIAO, W.NONG, W.ZHONG, W.DAN, W.QING
ZHUSHA, ZHESHI, HUAQING, SHILV, TENG = W.ZHUSHA, W.ZHESHI, W.HUAQING, W.SHILV, W.TENG
W_ZHUSHA, W_TENG = W.W_ZHUSHA, W.W_TENG
GOLD_DK, GOLD_HI, ZHUSHA_DK = W.GOLD_DK, W.GOLD_HI, W.ZHUSHA_DK
NIGHT = col(S.NIGHT_AMBIENT)
LANTERN = col(S.LANTERN_LIGHT)
SOUL = col(S.SOUL_LIGHT)
GOLD = mixc(TENG, LANTERN, 0.3)  # 泥金：藤黄兑一点灯光，夜里更亮
NIGHT_INK = mixc(JIAO, NIGHT, 0.45)  # 夜墨：偏一点夜色的焦墨，压在夜景上不发灰
RARITY = {  # 品级色（lantern-next 的 --r-*），稍兑墨，和国画颜料一个调子
    "fan": col(S.INK["dan"]),
    "ling": mixc(col("#3E6FA8"), HUAQING, 0.25),
    "xuan": mixc(col("#7A4FB0"), ZHONG, 0.12),
    "tian": col("#C9962E"),
}
BOSS = mixc(mixc(ZHUSHA, RARITY["xuan"], 0.45), JIAO, 0.3)  # 夜主血条：深的绛紫
SHIELD = mixc(mixc(HUAQING, SOUL, 0.55), PAPER, 0.1)  # 护盾：淡花青

# ============================================================== 画布与输出


class Canvas:
    """ss 倍超采样画布，坐标以最终像素计（像素中心在 .5）。预乘 alpha 叠加，最后缩小输出。"""

    def __init__(self, w: int, h: int, seed: int, ss: int = 4):
        self.w, self.h, self.ss = w, h, ss
        self.X, self.Y = V.grid(h, w, ss)
        self.xs, self.ys = self.X[0], self.Y[:, 0]
        self.lay = V.Layer(h * ss, w * ss)
        self.rng = np.random.default_rng(seed)
        self.aa = 0.6 / ss

    def over(self, rgb, a):
        self.lay.over(rgb, a)

    def periodic(self, field: np.ndarray, ox: float, oy: float) -> np.ndarray:
        """把一张周期场（超采样分辨率）铺满画布，field[0, 0] 对齐到最终像素 (ox, oy)。平铺区就是一个整周期。"""
        H, Wd = self.lay.a.shape
        iy = (np.arange(H) - int(round(oy * self.ss))) % field.shape[0]
        ix = (np.arange(Wd) - int(round(ox * self.ss))) % field.shape[1]
        return field[np.ix_(iy, ix)]


def bleed_rgb(rgb: np.ndarray, a8: np.ndarray) -> np.ndarray:
    """把颜色扩展到全透明区域（与 vfx_textures.bleed_rgb 同法，半径固定按 2 倍密度）。"""
    w = a8.astype(np.float64) / 255.0
    out = rgb.copy()
    hole = a8 == 0
    if not hole.any() or not (~hole).any():
        return out
    filled = np.zeros_like(hole)
    for sigma in (2.0, 5.0, 12.0, 48.0):
        den = fft_blur(w, sigma)
        num = np.stack([fft_blur(rgb[..., k] * w, sigma) for k in range(3)], -1)
        ok = hole & ~filled & (den > 1e-4)
        out[ok] = num[ok] / den[ok][:, None]
        filled |= ok
    rest = hole & ~filled
    if rest.any():
        out[rest] = (rgb * w[..., None]).sum((0, 1)) / max(w.sum(), 1e-9)
    return np.clip(out, 0.0, 1.0)


def finish(c: Canvas, *, clear: bool = True, band_x=None, band_y=None, dither: int | None = None) -> Image.Image:
    """输出直通 alpha 的 RGBA8。band_x=(L, R)：把横向拉伸带 [L, w-R) 每一列都换成第 L 列（带内本来就只随 y 变，
    这一步把超采样和扩色带来的细小差别也抹平）；band_y 同理按行。clear=True 时最外一圈像素清成透明。"""
    lay = c.lay.down(c.ss)
    rgb, a = lay.straight()
    if clear:
        a[0, :] = a[-1, :] = a[:, 0] = a[:, -1] = 0
    if dither is not None:
        a8 = V.dither_alpha(a, np.random.default_rng(dither))
        a8[a <= 0] = 0
    else:
        a8 = np.clip(np.round(a * 255.0), 0, 255).astype(np.uint8)
    rgb = bleed_rgb(rgb, a8)
    rgb8 = np.clip(np.round(rgb * 255.0), 0, 255).astype(np.uint8)
    arr = np.dstack([rgb8, a8])
    if band_x is not None:
        L, R = band_x
        arr[:, L : c.w - R] = arr[:, L : L + 1]
    if band_y is not None:
        T, B = band_y
        arr[T : c.h - B, :] = arr[T : T + 1, :]
    return Image.fromarray(arr, "RGBA")


# ============================================================== 纹理


def tex1(rng, n: int = 96, sigma: float = 1.2) -> np.ndarray:
    """横跨笔触的一维笔毛纹（s∈[-1,1] 上的 n 个采样，按名次归一到 0..1）。"""
    return rank01(fft_blur(rng.standard_normal((1, n)), (sigma, 0.0), wrap=True)[0])


def samp1(arr: np.ndarray, s) -> np.ndarray:
    """在 s∈[-1,1] 上线性采样一维数组（两端夹紧）。"""
    n = len(arr)
    return np.interp(np.clip((np.asarray(s) + 1.0) * 0.5 * (n - 1), 0, n - 1), np.arange(n), arr)


def tex2(rng, ns: int, nt: int, along: float, across: float = 0.9) -> np.ndarray:
    """二维笔毛纹（第一维横跨笔触，第二维沿笔触，沿笔方向周期），按名次归一。"""
    return rank01(noise(rng, (ns, nt), (along, across)))


def samp2(tex: np.ndarray, s, t) -> np.ndarray:
    """s∈[-1,1] 横跨（夹紧），t 沿笔（以采样点为单位，周期）。最近邻足够（纹理本身是平滑的）。"""
    ns, nt = tex.shape
    si = np.clip(np.round((np.asarray(s) + 1.0) * 0.5 * (ns - 1)).astype(int), 0, ns - 1)
    ti = np.mod(np.round(t).astype(int), nt)
    return tex[si, ti]


def pnoise(rng, n: int, sigma: float) -> np.ndarray:
    """一维周期平滑噪声（长度 n 个采样），标准差 1。"""
    return W.pnoise1(rng, n, sigma)


def bump(x, c, half):
    """以 c 为中心、半宽 half 的平滑隆起 (1-t²)²，范围外为 0。"""
    return V.bump_window(np.abs(np.asarray(x) - c) / half)


def fibres(rng, h: int, w: int, ss: int, count: int, length, amp, sigma: float, wobble: float) -> np.ndarray:
    """一组纸纤维（vfx_textures.fibre_layer 的长方形版，按 2 倍密度）：周期场，尺寸 (h·ss, w·ss)。"""
    H, Wd = h * ss, w * ss
    acc = np.zeros((H, Wd))
    step = 1.0
    sig = sigma * ss * 2.0
    xs_all, ys_all, w_all = [], [], []
    for _ in range(count):
        L = rng.uniform(*length) * ss * 2.0
        n = max(int(L / step), 4)
        x0, y0 = rng.uniform(0, Wd), rng.uniform(0, H)
        th = rng.uniform(0, 2 * math.pi) + fft_blur(np.cumsum(rng.normal(0, wobble, n))[None, :], (6, 0))[0]
        xs = x0 + np.cumsum(np.cos(th)) * step
        ys = y0 + np.cumsum(np.sin(th)) * step
        tt = np.linspace(0, 1, n)
        a = rng.uniform(*amp)
        prof = np.sin(np.pi * tt) ** 0.6 * (0.7 + 0.3 * np.cos(tt * rng.uniform(4, 12) + rng.uniform(0, 6)))
        xs_all.append(xs)
        ys_all.append(ys)
        w_all.append(prof * a * math.sqrt(2 * math.pi) * sig * step)
    V.splat_lines(acc, np.concatenate(xs_all), np.concatenate(ys_all), np.concatenate(w_all))
    return fft_blur(acc, sig, wrap=True)


def paper_field(rng, h: int, w: int, ss: int, *, grain: float = 0.02, fibre: float = 1.0, long: float = 0.45,
                cloud: float = 0.035) -> np.ndarray:
    """周期的宣纸浓淡场（超采样分辨率，h×w 最终像素一个周期）：正值偏纸影，负值偏亮。
    与 vfx_textures.make_paper 同一配方，按面积缩减纤维数量；界面上要压字，长纤维减弱（long）。
    平铺块在九宫格里最后一块会被裁开、接到角上，大块的浓淡（cloud）在接口处会显出一道色阶，所以压得很低。"""
    sh = (h * ss, w * ss)
    k = h * w / 1024.0**2
    d = cloud * V.fbm(rng, sh, (110.0 * ss, 46.0 * ss, 18.0 * ss), (0.3, 0.7, 0.5))
    floc = noise(rng, sh, 6.0 * ss) + 0.6 * noise(rng, sh, 11.0 * ss)
    d += 0.045 * np.tanh(floc / floc.std())
    if fibre:
        n = lambda c: max(int(round(c * k)), 2)  # noqa: E731
        d += fibre * long * fibres(rng, h, w, ss, n(150), (40, 150), (0.12, 0.34), 0.45, 0.035)
        d -= fibre * long * fibres(rng, h, w, ss, n(110), (25, 100), (0.10, 0.26), 0.6, 0.05)
        d += fibre * fibres(rng, h, w, ss, n(900), (4, 18), (0.03, 0.08), 0.4, 0.08)
        d -= fibre * fibres(rng, h, w, ss, n(700), (4, 16), (0.03, 0.08), 0.45, 0.08)
    if grain:
        d += grain * noise(rng, sh, 1.1 * ss)
    return d


def paper_rgb(d: np.ndarray, base=PAPER) -> np.ndarray:
    pos = np.clip(d, 0, None)[..., None]
    neg = np.clip(-d, 0, None)[..., None]
    return base + pos * (PAPER_SH - PAPER) + neg * (PAPER_LT - PAPER) * 1.6


# ============================================================== 形状


def rrect(c: Canvas, x0, y0, x1, y1, r):
    """圆角矩形的有向距离（内负外正）与绕行角 θ（顶边 -90°、右 0°、底 90°、左 ±180°，只在四角的圆弧上变化）。"""
    cx = np.clip(c.X, x0 + r, x1 - r)
    cy = np.clip(c.Y, y0 + r, y1 - r)
    dx, dy = c.X - cx, c.Y - cy
    hx, hy = 0.5 * (x1 - x0) - r, 0.5 * (y1 - y0) - r
    qx = np.abs(c.X - 0.5 * (x0 + x1)) - hx
    qy = np.abs(c.Y - 0.5 * (y0 + y1)) - hy
    d = np.hypot(np.maximum(qx, 0), np.maximum(qy, 0)) + np.minimum(np.maximum(qx, qy), 0) - r
    th = np.degrees(np.arctan2(dy, dx))
    return d, th


def side_value(th, top, right, bottom, left, press=0.0):
    """按绕行角在四边的取值之间平滑过渡（只在圆角处过渡），press>0 时转角处加粗（折笔顿一下）。"""
    t = np.mod(th + 90.0, 360.0) / 90.0  # 0 顶 → 1 右 → 2 底 → 3 左 → 4 顶
    vals = np.array([top, right, bottom, left, top], dtype=np.float64)
    i = np.clip(np.floor(t).astype(int), 0, 3)
    f = t - i
    g = f * f * (3 - 2 * f)
    out = vals[i] * (1 - g) + vals[i + 1] * g
    if press:
        out = out * (1.0 + press * np.sin(np.pi * f) ** 2)
    return out


def corner_weight(th, which: str):
    """某个角的圆弧上为 1、两边直线上为 0 的平滑权重（which ∈ tl tr br bl）。"""
    c = {"tr": -45.0, "br": 45.0, "bl": 135.0, "tl": -135.0}[which]
    dd = np.abs(np.mod(th - c + 180.0, 360.0) - 180.0)
    return np.clip(1.0 - dd / 45.0, 0.0, 1.0) ** 2 * (dd < 45.0)


# ============================================================== 笔触


def hstroke(c: Canvas, x0, x1, yc, hw, *, band, seed, head_len, tail_len, slant=0.25, blunt=3.0, taper=0.55, lift=0.12,
            dry=0.0, dry_tail=0.75, head_dry=0.0, edge_soft=0.7, rough=0.06, streak=True, tail_round=False, head_taper=1.0,
            head_rx=0.55, tail_rx=0.9, pool=0.0):
    """一笔横画（按钮、提示条、进度条……）。拉伸带 band=(bx0, bx1) 内的一切只随 y 变：上下沿是直的，笔毛纹是
    横跨方向的一维纹，所以拉多长都不变形。起笔（左）和收笔（右）的变化都在带外：
      起笔：笔锋斜落（slant：下沿比上沿晚 slant·hw 起笔），方中带圆（blunt：超椭圆指数，越大越方）；
      收笔：笔肚收细（taper）、略向上提（lift），笔毛从两边先干、一根根断开（dry_tail）；head_dry>0 时起笔也毛。
    返回 dict：cov 覆盖度（含飞白）、shape 外形、s 横向坐标（-1 上沿 … 1 下沿）、T 笔毛纹、edge 到边缘的有向距离。"""
    rng = np.random.default_rng(seed)
    bx0, bx1 = band
    assert x0 + head_len <= bx0 + 1e-6 and x1 - tail_len >= bx1 - 1e-6, "笔头伸进了拉伸带"
    X, Y, x = c.X, c.Y, c.xs
    th = smoothstep(x0 + head_len, x0, x)
    tt = smoothstep(x1 - tail_len, x1, x)
    hwx = hw * (1 - (1 - taper) * tt**1.6) * (1 - (1 - head_taper) * th**1.2)
    ycx = yc - lift * hw * tt**2
    v = Y - ycx[None, :]
    sv = np.clip(v / hwx[None, :], -1, 1)
    cap = np.maximum(th, tt)[None, :]
    n2 = noise(rng, X.shape, (5.0 * c.ss, 1.6 * c.ss))
    hwb = hwx[None, :] * (1 + rough * cap * n2)
    # 两端是椭圆（超椭圆）笔头：最左点正好在 x0，最右点正好在 x1
    hw0 = hw * head_taper
    hw1 = hw * taper
    rx0, rx1 = head_rx * hw0, tail_rx * hw1 * (1.0 if tail_round else 1.6)
    xl = x0 + rx0 + slant * hw * (sv + 1) * 0.5
    over_l = np.maximum(xl - X, 0) * (hw0 / rx0)
    over_r = np.maximum(X - (x1 - rx1), 0) * (hw1 / rx1)
    pw = np.where(over_l > 0, blunt, 2.0)
    ov = over_l + over_r
    dist = (np.abs(v) ** pw + ov**pw) ** (1.0 / pw)
    soft = edge_soft + c.aa
    shape = smoothstep(hwb + soft, hwb - soft, dist)
    s = np.clip(v / hwb, -1, 1)
    T1 = samp1(tex1(rng, 96, 1.8), s)
    z1 = (T1 - 0.5) / 0.29
    nl = noise(rng, X.shape, (11.0 * c.ss, 0.45 * c.ss))
    nsh = noise(rng, X.shape, (2.5 * c.ss, 0.6 * c.ss))
    T2 = rank01(0.8 * z1 + 0.55 * nl + 0.3 * nsh)
    wt = smoothstep(0.0, 0.35, np.maximum(tt, th * (head_dry > 0))[None, :])
    T = T1 * (1 - wt) + T2 * wt
    edgek = 0.5 + 0.5 * np.abs(s) ** 2  # 两边的笔毛先干
    d = dry + ((dry_tail - dry) * tt[None, :] ** 1.3 + head_dry * th[None, :] ** 1.6) * edgek
    # 飞白：干度 d 以下的笔毛断开；d≈0 时完全不断（不会出现细白线）
    ink = 1 - (1 - smoothstep(d - 0.08, d + 0.08, T)) * smoothstep(0.0, 0.08, d) if streak else 1.0
    # 起笔处墨积得浓（返回给调用者上色用）：离左边缘越近越浓
    pooled = pool * th[None, :] * np.exp(-np.maximum(X - (xl - rx0), 0) / max(0.3 * head_len, 1e-6)) if pool else 0.0
    return {"cov": shape * ink, "shape": shape, "s": s, "T": T, "edge": dist - hwb, "pool": pooled}


def loop(c: Canvas, x0, y0, x1, y1, r, *, center, hw, seed, rgb, alpha=1.0, press=0.3, dry=0.0, seam=None, wobble=0.0,
         soft=0.5, tone=None, tone_k=0.0, slices=None):
    """沿圆角矩形一笔绕一圈的边框：顺时针，从左上角起笔，绕回左上角收笔，中间留个小缺口，收笔飞白（同图标的圆相）。
    hw = (上, 右, 下, 左) 半宽，转角处 press 加粗（折笔顿一下）。
    seam = (起笔位置, 缺口, 起笔长, 收笔长, 收笔粗细比, 收笔干度)，位置用绕行坐标 q（顶边直线段左端为 0，
    顺时针为正，左上圆弧和左边为负）。slices=(左, 上) 给出时检查起收笔都在左上角的切片以内。
    wobble>0 只给固定尺寸的贴图：整圈的粗细起伏和沿笔的飞白；拉伸用的贴图 wobble=0，直边上只随离边距离变化。"""
    rng = np.random.default_rng(seed)
    d, th = rrect(c, x0, y0, x1, y1, r)
    p, per = rrect_perim(c, x0, y0, x1, y1, r)
    q = np.where(p > per / 2, p - per, p)
    hwv = side_value(th, *hw, press=press)
    if wobble:
        hwv = hwv * (1 + wobble * W.sample1(pnoise(rng, 512, 10.0), p / per))
    v = d - center
    s = np.clip(v / hwv, -1, 1)
    T1 = samp1(tex1(rng, 64, 1.0), s)
    nt = int(per * c.ss) + 8
    tex = noise(rng, (48, nt), (10.0 * c.ss, 0.5))
    T2 = rank01(0.8 * (T1 - 0.5) / 0.29 + 0.6 * samp2(tex, s, (q + per / 2) * c.ss))
    edgek = 0.5 + 0.5 * s**2
    if seam is None:
        cov = smoothstep(hwv + soft + c.aa, hwv - soft - c.aa, np.abs(v))
        T = T2 if wobble else T1
        cov = cov * smoothstep(dry - 0.07, dry + 0.07, T)
    else:
        qs, gap, hl, tl, taper, dry_tail = seam
        qe = qs - gap
        if slices is not None:
            arc = r * math.pi / 2
            assert qs + hl <= slices[0] - x0 - r + 1e-6 and qe - tl >= -(arc + slices[1] - y0 - r) - 1e-6, "起收笔越过了切片"
        hA = hwv * (1 + 0.28 * bump(q, qs + 0.4 * hl, 0.6 * hl))
        oA = np.maximum(qs - q, 0) * 1.1
        covA = smoothstep(hA + soft + c.aa, hA - soft - c.aa, np.hypot(v, oA))
        ttl = smoothstep(qe - tl, qe, q)
        hB = hwv * (1 - (1 - taper) * ttl**1.5)
        oB = np.maximum(q - qe, 0) * 1.6
        covB = smoothstep(hB + soft + c.aa, hB - soft - c.aa, np.hypot(v, oB))
        TA = T2 if wobble else T1
        wt = smoothstep(0.0, 0.3, ttl)
        TB = TA * (1 - wt) + T2 * wt
        dB = dry + (dry_tail - dry) * ttl**1.3 * edgek
        covA = covA * smoothstep(dry - 0.07, dry + 0.07, TA) * (q > qe)  # 起笔那段只在缺口之后
        covB = covB * smoothstep(dB - 0.08, dB + 0.08, TB) * (q < qs)
        cov = np.maximum(covA, covB)
        T = np.where(q >= qs, TA, TB)
    color = rgb if tone is None else mixc(rgb, tone, np.clip(tone_k * (0.62 - T) * 1.6, 0, 1))
    c.over(color, cov * alpha)
    return d, th, cov, s


def seg_stroke(c: Canvas, pts, hw, *, seed, rgb, alpha=1.0, dry=0.0, dry_start=0.5, jitter=0.1, taper=(0.8, 0.3)):
    """任意方向的一笔（角上的起收笔、小笔画）：weapon_textures 同法，但不依赖密度。"""
    rng = np.random.default_rng(seed)
    pts = np.asarray(pts, dtype=np.float64)
    n = len(pts)
    tt = np.linspace(0, 1, n)
    prof = np.interp(tt, [0.0, 0.15, 0.75, 1.0], [taper[0], 1.0, 1.0, taper[1]])
    halfw = hw * prof
    if dry > 0:
        cov, _ = V.brush_stroke(c.X, c.Y, pts, halfw, rng, dry=dry, dry_start=dry_start, edge_jitter=jitter, ss=c.ss)
    else:
        f = V.stroke_fields(c.X, c.Y, pts, halfw)
        cov = smoothstep(f["hw"] + c.aa, f["hw"] - c.aa, np.hypot(f["perp"], f["over"]))
    c.over(rgb, cov * alpha)
    return cov


def glow_rrect(c: Canvas, x0, y0, x1, y1, r, *, rgb, alpha, width, inner=0.0):
    """圆角矩形外沿的柔光（带内只随离边距离变化）。"""
    d, _ = rrect(c, x0, y0, x1, y1, r)
    g = np.exp(-np.maximum(d, 0.0) ** 2 / (2 * width**2)) * (d > -inner)
    if inner:
        g = g * smoothstep(-inner, 0.0, d)
    c.over(rgb, g * alpha)


# ============================================================== 九宫格（模拟 Bevy TextureSlicer）


def _premul(img: Image.Image) -> np.ndarray:
    a = np.asarray(img.convert("RGBA"), dtype=np.float64) / 255.0
    return np.dstack([a[..., :3] * a[..., 3:], a[..., 3:]])


def _resize_pm(pm: np.ndarray, w: int, h: int) -> np.ndarray:
    """预乘 RGBA 的双线性缩放（逐通道）。"""
    if w <= 0 or h <= 0:
        return np.zeros((max(h, 0), max(w, 0), 4))
    if pm.shape[1] == w and pm.shape[0] == h:
        return pm
    out = [np.asarray(Image.fromarray(pm[..., k].astype(np.float32), "F").resize((w, h), Image.BILINEAR)) for k in range(4)]
    return np.stack(out, -1).astype(np.float64)


def _tile_pm(pm: np.ndarray, w: int, h: int, tile_x: bool, tile_y: bool, scale: float = 1.0) -> np.ndarray:
    """沿选定方向按原尺寸 × scale 重复（最后一块裁掉多余部分，与 Bevy 从左上开始铺一致），另一方向拉伸。"""
    if scale != 1.0:
        pm = _resize_pm(pm, max(1, int(round(pm.shape[1] * scale))), max(1, int(round(pm.shape[0] * scale))))
    th, tw = pm.shape[:2]
    if not tile_x:
        pm = _resize_pm(pm, w, th if tile_y else h)
        tw = w
    if not tile_y:
        pm = _resize_pm(pm, tw if tile_x else w, h)
        th = h
    ny, nx = -(-h // th), -(-w // tw)
    return np.tile(pm, (ny, nx, 1))[:h, :w]


def nine_slice(img: Image.Image, slc, out_w: int, out_h: int, center: str = "stretch", sides: str = "stretch",
               max_corner_scale: float = 1.0, tile_scale: float | None = None) -> Image.Image:
    """按 Bevy TextureSlicer 的规则把贴图画到 out_w×out_h：
    四角按 min(out_w/w, out_h/h, max_corner_scale) 等比缩放；上下边沿 x、左右边沿 y 拉伸或平铺；中间拉伸或双向平铺，
    平铺块的大小 = 原尺寸 × tile_scale（Bevy 的 stretch_value，默认等于 max_corner_scale）。slice 全为 0 时整图拉伸。
    默认参数以贴图像素为单位（相当于 4K 屏）；按 1080p 逻辑像素出图时用 max_corner_scale=0.5（与游戏一致）。
    返回直通 alpha 的 RGBA。"""
    ts = max_corner_scale if tile_scale is None else tile_scale
    l, t, r, b = (int(v) for v in slc)
    pm = _premul(img)
    H, Wd = pm.shape[:2]
    if (l, t, r, b) == (0, 0, 0, 0):
        out = _resize_pm(pm, out_w, out_h)
    else:
        k = min(out_w / Wd, out_h / H, max_corner_scale)
        cl, ct, cr, cb = (int(round(v * k)) for v in (l, t, r, b))
        mw, mh = out_w - cl - cr, out_h - ct - cb
        out = np.zeros((out_h, out_w, 4))
        src = {  # (y0, y1, x0, x1)
            "tl": (0, t, 0, l), "tr": (0, t, Wd - r, Wd), "bl": (H - b, H, 0, l), "br": (H - b, H, Wd - r, Wd),
            "t": (0, t, l, Wd - r), "b": (H - b, H, l, Wd - r), "l": (t, H - b, 0, l), "r": (t, H - b, Wd - r, Wd),
            "c": (t, H - b, l, Wd - r),
        }
        dst = {
            "tl": (0, ct, 0, cl), "tr": (0, ct, out_w - cr, out_w), "bl": (out_h - cb, out_h, 0, cl),
            "br": (out_h - cb, out_h, out_w - cr, out_w), "t": (0, ct, cl, out_w - cr), "b": (out_h - cb, out_h, cl, out_w - cr),
            "l": (ct, out_h - cb, 0, cl), "r": (ct, out_h - cb, out_w - cr, out_w), "c": (ct, out_h - cb, cl, out_w - cr),
        }
        for key in src:
            sy0, sy1, sx0, sx1 = src[key]
            dy0, dy1, dx0, dx1 = dst[key]
            if sy1 <= sy0 or sx1 <= sx0 or dy1 <= dy0 or dx1 <= dx0:
                continue
            piece = pm[sy0:sy1, sx0:sx1]
            w_, h_ = dx1 - dx0, dy1 - dy0
            if key in ("t", "b") and sides == "tile":
                piece = _tile_pm(piece, w_, h_, True, False, ts)
            elif key in ("l", "r") and sides == "tile":
                piece = _tile_pm(piece, w_, h_, False, True, ts)
            elif key == "c" and center == "tile":
                piece = _tile_pm(piece, w_, h_, True, True, ts)
            else:
                piece = _resize_pm(piece, w_, h_)
            out[dy0:dy1, dx0:dx1] = piece
        _ = (mw, mh)
    a = out[..., 3:]
    rgb = np.where(a > 1e-6, out[..., :3] / np.maximum(a, 1e-6), 0.0)
    arr = np.dstack([np.clip(rgb, 0, 1), np.clip(a, 0, 1)])
    return Image.fromarray(np.round(arr * 255).astype(np.uint8), "RGBA")


def line_stroke(c: Canvas, horizontal: bool, pos, a, b, hw, *, period: int, origin: float, seed: int, rgb, alpha=1.0,
                dark=None, dark_k=0.0, head_len=10.0, tail_len=14.0, bulge=0.18, taper=0.45, dry=0.06, dry_var=0.08,
                dry_tail=0.55, wob=0.5, jitter=0.1, soft=0.45):
    """沿 x（horizontal）或 y 的一笔直线，用在可平铺的边上：沿笔方向的抖动、粗细、飞白都是周期为 period 的函数，
    相位对齐到 origin（平铺区的起点），所以平铺区里正好一个周期；起笔（a 端）和收笔（b 端）的变化只在角上。"""
    rng = np.random.default_rng(seed)
    ss = c.ss
    u = c.xs if horizontal else c.ys
    P = period * ss
    idx = (np.arange(len(u)) - int(round(origin * ss))) % P
    wv = pnoise(rng, P, 34.0 * ss)[idx] * wob
    jv = pnoise(rng, P, 9.0 * ss)[idx]
    dv = pnoise(rng, P, 20.0 * ss)[idx]
    tt = smoothstep(b - tail_len, b, u)
    hwu = hw * (1 + jitter * jv) * (1 + bulge * bump(u, a + 0.4 * head_len, 0.6 * head_len)) * (1 - (1 - taper) * tt)
    over = np.maximum(a - u, 0) * 1.2 + np.maximum(u - b, 0) * 1.5
    dryu = dry + dry_var * np.clip(dv, 0, None) + (dry_tail - dry) * tt**1.5
    tex = tex2(rng, 40, P, 12.0 * ss, 0.8)
    if horizontal:
        v = c.Y - (pos + wv)[None, :]
        hwb, ob, db, ib = hwu[None, :], over[None, :], dryu[None, :], idx[None, :]
    else:
        v = c.X - (pos + wv)[:, None]
        hwb, ob, db, ib = hwu[:, None], over[:, None], dryu[:, None], idx[:, None]
    dist = np.hypot(v, ob)
    cov = smoothstep(hwb + soft + c.aa, hwb - soft - c.aa, dist)
    s = np.clip(v / hwb, -1, 1)
    T = samp2(tex, s, np.broadcast_to(ib, s.shape))
    cov = cov * smoothstep(db - 0.07, db + 0.07, T)
    color = rgb if dark is None else mixc(rgb, dark, dark_k * np.clip(0.8 * smoothstep(0.7, 1.0, np.abs(s)) + 0.9 * (0.5 - T), 0, 1))
    c.over(color, cov * alpha)
    return cov


def rrect_perim(c: Canvas, x0, y0, x1, y1, r):
    """圆角矩形上最近点的周长坐标（从顶边左端起顺时针，单位像素）与总周长。"""
    w, h = (x1 - x0) - 2 * r, (y1 - y0) - 2 * r
    cx = np.clip(c.X, x0 + r, x1 - r)
    cy = np.clip(c.Y, y0 + r, y1 - r)
    dx, dy = c.X - cx, c.Y - cy
    ang = np.arctan2(dy, dx)  # -π/2 顶
    arc = r * math.pi / 2
    p = np.zeros_like(c.X)
    top = (dy < 0) & (dx == 0)
    right = (dx > 0) & (dy == 0)
    bot = (dy > 0) & (dx == 0)
    left = (dx < 0) & (dy == 0)
    p = np.where(top, cx - (x0 + r), p)
    p = np.where(right, w + arc + (cy - (y0 + r)), p)
    p = np.where(bot, w + h + 2 * arc + (x1 - r - cx), p)
    p = np.where(left, 2 * w + h + 3 * arc + (y1 - r - cy), p)
    tr = (dx > 0) & (dy < 0)
    br = (dx > 0) & (dy > 0)
    bl = (dx < 0) & (dy > 0)
    tl = (dx < 0) & (dy < 0)
    p = np.where(tr, w + r * (ang + math.pi / 2), p)
    p = np.where(br, w + arc + h + r * ang, p)
    p = np.where(bl, 2 * w + h + 2 * arc + r * (ang - math.pi / 2), p)
    p = np.where(tl, 2 * w + 2 * h + 3 * arc + r * (ang + math.pi), p)
    return p, 2 * (w + h) + 4 * arc


def flecks(c: Canvas, rng, boxes, n, size, rgb, alpha, hi=None):
    """泥金碎屑：小块不规则的金箔，只撒在给定的方框里（不越过切片线）。"""
    for _ in range(n):
        x0, y0, x1, y1 = boxes[rng.integers(len(boxes))]
        cx, cy = rng.uniform(x0, x1), rng.uniform(y0, y1)
        rr = rng.uniform(*size)
        k = rng.integers(4, 7)
        ang = np.sort(rng.uniform(0, 2 * math.pi, k))
        rad = rr * rng.uniform(0.5, 1.2, k)
        poly = np.stack([cx + rad * np.cos(ang), cy + rad * np.sin(ang)], -1)
        d, _ = W.poly_sdf(c.X, c.Y, poly, pad=2.0)
        cov = smoothstep(c.aa, -c.aa, d)
        a = alpha * rng.uniform(0.55, 1.0)
        c.over(rgb if hi is None else mixc(rgb, hi, rng.uniform(0, 0.6)), cov * a)


# ============================================================== 面板


def make_panel() -> Image.Image:
    """毛边宣纸大面板：512²，左上角 176、其余 80 的切片，中间 256² 一个周期（中间和四边都平铺）。
    纸纹、毛边、旧纸边都是对齐平铺区的周期场；淡墨晕染只在左上角里（176² 以内淡出）。"""
    Wd = H = 512
    L, T, R, B = 176, 176, 80, 80
    Cx, Cy = Wd - L - R, H - T - B
    ss = 2
    c = Canvas(Wd, H, 101, ss)
    rng = c.rng
    m = 13
    per = lambda f: c.periodic(f, L, T)  # noqa: E731
    pd = per(paper_field(rng, Cy, Cx, ss, grain=0.015, long=0.22))
    n_fine = per(noise(rng, (Cy * ss, Cx * ss), 1.6 * ss))
    n_mid = per(noise(rng, (Cy * ss, Cx * ss), 6.0 * ss))
    n_big = per(noise(rng, (Cy * ss, Cx * ss), 22.0 * ss))
    hair = per(fibres(rng, Cy, Cx, ss, 260, (3, 9), (0.4, 0.9), 0.35, 0.12))
    d, _ = rrect(c, m, m, Wd - m, H - m, 8)
    # 撕开的纸边：平铺的边上只有细碎的毛（九宫格最后一块被裁开、接到角上时，边的位置跳得少，看不出缺口）；
    # 大的起伏只放在四个角里，到切片线前淡成 0
    X, Y = c.X, c.Y
    win = (smoothstep(L - 4, L - 60, X) + smoothstep(Wd - R + 4, Wd - R + 40, X)) * \
          (smoothstep(T - 4, T - 60, Y) + smoothstep(H - B + 4, H - B + 40, Y))
    n_tear = noise(np.random.default_rng(104), X.shape, 18.0 * ss)
    dd = d + 0.3 * n_big + 0.55 * n_mid + 0.6 * n_fine + 4.5 * np.clip(win, 0, 1) * n_tear
    body = smoothstep(0.7, -0.7, dd)
    # 纸边最外 3 px 薄而半透（撕口处纤维稀疏），外面再伸出几根纤维
    thin = smoothstep(-3.5, 0.0, dd)
    body = body * (1.0 - 0.45 * thin * np.clip(0.6 + 0.5 * n_fine, 0, 1))
    fringe = np.clip(hair * 1.2, 0, 0.85) * smoothstep(6.5, 1.0, dd) * (dd > -1.0)
    a = 1 - (1 - body) * (1 - fringe)
    rgb = paper_rgb(pd)
    # 旧纸边：靠边 20 px 内略黄略暗
    age = 0.5 * np.exp(np.minimum(dd, 0) / 8.0) * np.clip(0.75 + 0.35 * n_mid, 0, 1.2)
    rgb = mixc(rgb, mixc(PAPER_SH, ZHESHI, 0.12), np.clip(age, 0, 1))
    c.over(rgb, a)
    # 左上角的淡墨晕染：几团湿墨从角上洇进来，边上积一道干痕，墨落进纸纹里
    wn = np.clip(noise(np.random.default_rng(102), X.shape, 14.0 * ss), -1.6, 1.6)
    wn2 = noise(np.random.default_rng(103), X.shape, 4.0 * ss)
    lobes = ((m - 4, m - 4, 150.0), (m + 92, m - 2, 52.0), (m - 2, m + 96, 58.0))
    f = np.full(X.shape, 9.0)
    for lx, ly, lr in lobes:
        f = np.minimum(f, np.hypot(X - lx, Y - ly) / lr)
    f = f * (1 + 0.10 * wn + 0.035 * wn2)
    inner = smoothstep(1.0, 0.15, f)
    rim = np.exp(-(((f - 0.965) / 0.03) ** 2)) * np.clip(0.35 + 0.65 * smoothstep(-0.8, 0.6, wn2), 0, 1)
    gran = np.clip(0.8 + 1.1 * pd, 0.3, 1.4)
    wash = (0.26 * inner**1.15 + 0.12 * rim * (f < 1.1)) * gran
    wash = wash * smoothstep(L - 2, L - 30, X) * smoothstep(T - 2, T - 30, Y) * body
    c.over(mixc(ZHONG, HUAQING, 0.18), wash)
    return finish(c)


INK_RIM = mixc(DAN, QING, 0.3)  # 夜色上的边框墨：淡墨，夜里看得见、纸上也不刺眼


def make_panel_dark() -> Image.Image:
    """夜墨面板（HUD 底板、提示框）：128×96，切片 32，中间与四边拉伸。中间是约 88% 不透明的浓夜墨，压字的地方匀净。
    边框是一笔淡墨，四边轻重不一（上边轻，下边、左边重），四个角各有各的笔意：左上起笔圆钝、墨积得浓，
    右上转角笔快没墨、扫出几丝飞白，右下顿笔留一个墨团，左下转角略出一点锋，绕回左上角收笔、散成干丝。
    墨底的浓淡也收在四个角里：左上起笔处洇开一大团淡墨、边上干出一道水痕，右下一块墨被纸吸走的浅斑，
    右上、左下是墨的颗粒；四条边上只有很淡的一层往里渐淡的洇痕。
    拉伸的规矩：中间、四条边沿长度方向都一样（只随离边远近渐变），所有不规则的东西都收在四个 32² 的角里。"""
    Wd, H, m, r, L = 128, 96, 4, 12, 32
    c = Canvas(Wd, H, 201, 4)
    X, Y = c.X, c.Y
    d, _ = rrect(c, m, m, Wd - m, H - m, r)
    fill = smoothstep(0.6 + c.aa, -0.6 - c.aa, d)
    e = -d  # 离边的距离（里面为正）
    # 按离哪条边最近在四边的取值之间过渡（rrect 的 θ 在里面的矩形里恒为 0，不能用来分边）
    dist = np.stack([Y - m, Wd - m - X, H - m - Y, X - m])
    wts = np.exp(-(dist - dist.min(0)) / 3.0)
    wts = wts / wts.sum(0)

    def side_k(top, right, bottom, left):
        return np.tensordot(np.array([top, right, bottom, left]), wts, axes=1)

    def corner_win(cx_, cy_):  # 角里的东西离切片线 3 px 前淡尽
        wx = smoothstep(L - 3.0, L - 16.0, np.abs(X - cx_))
        wy = smoothstep(L - 3.0, L - 16.0, np.abs(Y - cy_))
        return wx * wy

    nb = noise(np.random.default_rng(205), X.shape, 3.5 * c.ss)
    nb2 = noise(np.random.default_rng(208), X.shape, 1.4 * c.ss)
    nf = noise(np.random.default_rng(206), X.shape, 0.8 * c.ss)
    inner = smoothstep(2.5, 6.0, e)
    light = side_k(0.1, 0.12, 0.17, 0.15) * np.exp(-np.maximum(e - 3.0, 0.0) / 3.5) * smoothstep(1.0, 4.0, e)
    # 左上：一大团淡墨洇开，边上一道干痕（不规则）
    f_tl = np.hypot(X - (m + 5.0), (Y - (m + 5.0)) * 1.12) / 20.0 * (1.0 + 0.18 * nb + 0.05 * nb2)
    w_tl = corner_win(0.0, 0.0) * inner
    light = light + 0.42 * smoothstep(1.0, 0.3, f_tl) ** 1.2 * w_tl
    dark = 0.75 * np.exp(-(((f_tl - 1.0) / 0.045) ** 2)) * w_tl
    # 右下：墨被纸吸走的浅斑，边缘一道浅痕
    f_br = np.hypot(X - (Wd - m - 10.0), Y - (H - m - 9.0)) / 12.0 * (1.0 + 0.22 * nb + 0.06 * nb2)
    w_br = corner_win(Wd, H) * inner
    light = light + 0.3 * smoothstep(1.0, 0.25, f_br) * w_br
    dark = dark + 0.5 * np.exp(-(((f_br - 1.0) / 0.055) ** 2)) * w_br
    # 右上、左下：墨的颗粒
    gw = (corner_win(Wd, 0.0) + corner_win(0.0, H)) * inner * smoothstep(20.0, 6.0, e)
    gran = 0.22 * np.clip(nf + 0.4 * nb2, -1.6, 1.6) * gw
    light = np.clip(light + np.maximum(gran, 0), 0, 1)
    dark = np.clip(dark + np.maximum(-gran, 0), 0, 1)
    rgb = mixc(mixc(NIGHT_INK, mixc(ZHONG, QING, 0.3), light), JIAO, dark)
    c.over(rgb, fill * 0.88)
    # 边框：先画在单独一层，再在右上角按笔毛纹扣出几丝飞白
    cb = Canvas(Wd, H, 209, c.ss)
    loop(cb, m, m, Wd - m, H - m, r, center=-2.3, hw=(1.25, 1.75, 2.6, 2.15), seed=202, rgb=INK_RIM, alpha=0.85,
         press=1.1, dry=0.05, seam=(-4.0, 9.0, 16.0, 21.0, 0.22, 0.9), tone=ZHONG, tone_k=0.6, slices=(L, L))
    acx, acy = Wd - m - r, m + r  # 右上圆角的圆心
    rho = np.hypot(X - acx, Y - acy)
    phi = np.degrees(np.arctan2(Y - acy, X - acx))  # 顶 -90 → 右 0
    streak = samp1(tex1(np.random.default_rng(210), 12, 0.7), np.clip((rho - (r + 2.3)) / 2.2, -1, 1))
    streak = rank01(streak + 0.25 * noise(np.random.default_rng(211), X.shape, (0.8 * c.ss, 3.0 * c.ss)))
    dry_tr = 0.62 * np.exp(-(((phi + 40.0) / 26.0) ** 2)) * corner_win(Wd, 0.0)
    keep = 1.0 - smoothstep(0.0, 0.08, dry_tr) * (1.0 - smoothstep(dry_tr - 0.06, dry_tr + 0.06, streak))  # 干度≈0 处一点不断
    c.over(cb.lay.p / np.maximum(cb.lay.a, 1e-6)[..., None], cb.lay.a * keep)
    # 左上起笔：圆钝的笔头，墨积得浓
    head = np.hypot((X - (m + 2.6)) / 3.0, (Y - (m + 11.0)) / 4.4)
    c.over(mixc(INK_RIM, PAPER, 0.12), 0.7 * smoothstep(1.0, 0.55, head + 0.12 * nb2))
    # 右下顿笔：笔在转角停了一下，留一个墨团
    knot = np.hypot((X - (Wd - m - 4.0)) / 3.6, (Y - (H - m - 4.0)) / 3.2)
    c.over(mixc(INK_RIM, ZHONG, 0.2), 0.75 * smoothstep(1.0, 0.45, knot + 0.15 * nb2))
    # 左下转角略出一点锋：一小笔往外挑
    seg_stroke(c, V.bezier([(m + 2.6, H - m - 14.0), (m + 1.2, H - m - 4.0), (m - 1.6, H - m + 1.4)], 24), 1.2, seed=212,
               rgb=INK_RIM, alpha=0.7, taper=(1.0, 0.15))
    return finish(c, band_x=(L, L), band_y=(L, L))


def make_overlay() -> Image.Image:
    """全屏压暗：960×540（整张拉伸到全屏），中间较透，四周是墨云。"""
    Wd, H = 960, 540
    c = Canvas(Wd, H, 301, 1)
    rng = c.rng
    u = (c.X - Wd / 2) / (Wd / 2)
    v = (c.Y - H / 2) / (H / 2)
    p = 2.4
    rr = (np.abs(u) ** p + np.abs(v) ** p) ** (1 / p)
    cloud = V.fbm(rng, c.X.shape, (90.0, 40.0, 16.0), (0.5, 0.35, 0.2))
    fine = noise(rng, c.X.shape, 5.0)
    e = rr + 0.10 * cloud + 0.02 * fine
    a = 0.40 + 0.52 * smoothstep(0.45, 1.25, e)
    # 墨云：边上一团团更浓的墨，带一道湿边的水痕
    blob = smoothstep(0.15, 0.9, cloud) * smoothstep(0.55, 1.15, rr)
    a = a + 0.10 * blob
    tide = np.exp(-(((cloud - 0.55) / 0.05) ** 2)) * smoothstep(0.6, 1.1, rr)
    a = np.clip(a + 0.06 * tide, 0, 0.96)
    rgb = mixc(mixc(JIAO, NIGHT, 0.4), JIAO, 0.25 * blob)
    c.over(rgb * 0.75, a)
    return finish(c, clear=False, dither=302)


# ============================================================== 卡片

CARD_W, CARD_H, CARD_SL, CARD_M = 320, 400, 64, 16


def card_base(seed: int, *, wash_rgb=None, wash_a=0.0, shadow=0.3, glow_rgb=None, glow_a=0.0):
    """卡片底：宣纸笺，下面一层柔和的投影（或泥金光）。返回 (画布, 纸面距离场, 周期对齐函数)。"""
    Wd, H, L, m = CARD_W, CARD_H, CARD_SL, CARD_M
    Cx, Cy = Wd - 2 * L, H - 2 * L
    ss = 3
    c = Canvas(Wd, H, seed, ss)
    rng = c.rng
    per = lambda f: c.periodic(f, L, L)  # noqa: E731
    pd = per(paper_field(rng, Cy, Cx, ss, grain=0.012, fibre=0.8, long=0.25))
    n_edge = per(noise(rng, (Cy * ss, Cx * ss), 5.0 * ss))
    n_wash = per(noise(rng, (Cy * ss, Cx * ss), 12.0 * ss))
    x0, y0, x1, y1 = m, m, Wd - m, H - m
    if shadow:
        ds, _ = rrect(c, x0 + 2, y0 + 7, x1 - 2, y1 + 3, 8)
        c.over(JIAO, shadow * np.exp(-np.maximum(ds + 1.5, 0) ** 2 / (2 * 5.0**2)))
    if glow_rgb is not None:
        dg, _ = rrect(c, x0, y0, x1, y1, 6)
        c.over(glow_rgb, glow_a * np.exp(-np.maximum(dg, 0) ** 2 / (2 * 6.0**2)))
    d, _ = rrect(c, x0, y0, x1, y1, 5)
    d = d + 0.45 * n_edge
    body = smoothstep(0.6 + c.aa, -0.6 - c.aa, d)
    rgb = paper_rgb(pd)
    rgb = mixc(rgb, PAPER_SH, 0.3 * np.exp(np.minimum(d, 0) / 3.0))  # 纸边一线略深（纸的厚度）
    if wash_rgb is not None:
        k = wash_a * np.exp(np.minimum(d, 0) / 16.0) * np.clip(0.8 + 0.35 * n_wash, 0.3, 1.3) * smoothstep(-44, -30, d)
        rgb = mixc(rgb, wash_rgb, np.clip(k, 0, 1))
    c.over(rgb, body)
    return c, d, per


def card_frame(c: Canvas, inset: float, hw: float, rgb, *, seed: int, alpha=1.0, dark=None, dark_k=0.5, over=6.0, dry=0.03,
               dry_tail=0.6, head_len=12.0, tail_len=20.0):
    """四笔直线围成的框：横笔从左往右、竖笔从上往下写，左上两笔起笔、右下两笔收笔飞白，四角交叉出一点头。"""
    Wd, H, L, m = CARD_W, CARD_H, CARD_SL, CARD_M
    x0, y0, x1, y1 = m + inset, m + inset, Wd - m - inset, H - m - inset
    # 线的抖动、粗细起伏取得小：九宫格最后一块被裁开、接到角上时，相位对不上的台阶不到半个像素
    kw = dict(rgb=rgb, alpha=alpha, dark=dark, dark_k=dark_k, dry=dry, dry_tail=dry_tail, head_len=head_len, tail_len=tail_len,
              wob=0.22, jitter=0.06)
    line_stroke(c, True, y0, x0 - over, x1 + over * 0.7, hw, period=Wd - 2 * L, origin=L, seed=seed, **kw)
    line_stroke(c, False, x0, y0 - over, y1 + over * 0.7, hw * 0.92, period=H - 2 * L, origin=L, seed=seed + 1, **kw)
    line_stroke(c, False, x1, y0 - over * 0.5, y1 + over, hw * 0.96, period=H - 2 * L, origin=L, seed=seed + 2, **kw)
    line_stroke(c, True, y1, x0 - over * 0.5, x1 + over, hw * 1.06, period=Wd - 2 * L, origin=L, seed=seed + 3, **kw)


def seal(c: Canvas, x0: float, y0: float, size: float, *, seed: int):
    """一方小朱印：边缘磨损的朱砂方块，中间留白两笔（像一个篆字的意思，不是真字）。"""
    rng = np.random.default_rng(seed)
    poly = W.wobble([(x0, y0), (x0 + size, y0), (x0 + size, y0 + size), (x0, y0 + size)], rng, 0.35, spacing=0.5, sigma_px=1.5)
    d, _ = W.poly_sdf(c.X, c.Y, poly, pad=2.0)
    worn = noise(rng, c.X.shape, 0.8 * c.ss)
    ink = smoothstep(c.aa, -c.aa, d) * (1 - smoothstep(1.3, 1.8, worn + 0.7 * smoothstep(-2.5, 0.0, d)))
    k = size / 20.0
    white = np.zeros_like(c.X)
    for pts, hw in ((((x0 + 5 * k, y0 + 5.5 * k), (x0 + 15 * k, y0 + 5.5 * k)), 1.2 * k),
                    (((x0 + 10 * k, y0 + 5.5 * k), (x0 + 10 * k, y0 + 15 * k), (x0 + 15 * k, y0 + 15 * k)), 1.2 * k),
                    (((x0 + 5 * k, y0 + 10 * k), (x0 + 5 * k, y0 + 15 * k)), 1.1 * k)):
        dist = W.polyline_dist(c.X, c.Y, pts)
        white = np.maximum(white, smoothstep(hw + c.aa, hw - c.aa, dist))
    c.over(mixc(ZHUSHA, ZHUSHA_DK, 0.15), ink * (1 - white) * 0.92)


def make_card(kind: str) -> Image.Image:
    """升级卡（凡 / 灵 / 玄 / 天）与夜签卡：320×400，切片 64，中间 192×272 一个周期（中间和四边都平铺）。
    品级越高框越重：凡一道淡墨；灵、玄一道品级色 + 一道细内框；玄的内框四角点墨；天是泥金框、外发金光、四角洒金。"""
    Wd, H, L, m = CARD_W, CARD_H, CARD_SL, CARD_M
    seed = {"fan": 410, "ling": 420, "xuan": 430, "tian": 440, "omen": 450}[kind]
    if kind == "omen":
        c, d, per = card_base(seed, wash_rgb=W_ZHUSHA, wash_a=0.12)
        card_frame(c, 9.0, 2.7, ZHUSHA, seed=seed + 10, dark=ZHUSHA_DK, dark_k=0.45, dry=0.03, dry_tail=0.55)
        loop(c, m, m, Wd - m, H - m, 6, center=-17.5, hw=(1.0,) * 4, seed=seed + 20, rgb=ZHUSHA, alpha=0.9, press=0.0)
        seal(c, Wd - L + 2, H - L + 2, 20.0, seed=seed + 30)  # 右下角一方小朱印（在角的切片以内）
        return finish(c)
    rc = RARITY[kind]
    tian = kind == "tian"
    wash = {"fan": 0.0, "ling": 0.11, "xuan": 0.12, "tian": 0.14}[kind]
    c, d, per = card_base(seed, wash_rgb=mixc(rc, PAPER, 0.3), wash_a=wash, shadow=0.18 if tian else 0.3,
                          glow_rgb=GOLD if tian else None, glow_a=0.6)
    hw = {"fan": 2.2, "ling": 2.5, "xuan": 2.7, "tian": 2.9}[kind]
    if kind == "fan":
        ink, dark = mixc(ZHONG, DAN, 0.35), NONG
    elif tian:
        ink, dark = mixc(rc, TENG, 0.35), GOLD_DK
    else:
        ink, dark = rc, mixc(rc, JIAO, 0.45)
    card_frame(c, 9.0, hw, ink, seed=seed + 10, dark=dark, dark_k=0.55, dry=0.05 if kind == "fan" else 0.03)
    if kind != "fan":
        loop(c, m, m, Wd - m, H - m, 6, center=-17.5, hw=(0.8,) * 4, seed=seed + 20, rgb=mixc(ink, dark, 0.3), alpha=0.8,
             press=0.0)
    if kind in ("xuan", "tian"):
        for (px, py) in ((m + 17.5, m + 17.5), (Wd - m - 17.5, m + 17.5), (m + 17.5, H - m - 17.5), (Wd - m - 17.5, H - m - 17.5)):
            dd = np.hypot(c.X - px, c.Y - py)
            c.over(mixc(ink, dark, 0.5), smoothstep(2.4 + c.aa, 2.4 - c.aa, dd))
    if tian:
        rng = np.random.default_rng(seed + 30)
        boxes = [(m + 3, m + 3, L - 5, L - 5), (Wd - L + 5, m + 3, Wd - m - 3, L - 5),
                 (m + 3, H - L + 5, L - 5, H - m - 3), (Wd - L + 5, H - L + 5, Wd - m - 3, H - m - 3)]
        flecks(c, rng, boxes[:1] * 3 + boxes[3:] * 3 + boxes[1:3], 60, (0.9, 2.8), GOLD, 0.85, hi=GOLD_HI)
        # 平铺区里稀疏几片（画在周期画布上再铺开，接缝处连续）
        fl = Canvas(Wd - 2 * L, H - 2 * L, seed + 31, c.ss)
        flecks(fl, rng, [(3, 3, Wd - 2 * L - 3, H - 2 * L - 3)], 9, (0.8, 1.9), GOLD, 0.8, hi=GOLD_HI)
        pa = per(fl.lay.a) * smoothstep(0.5, -1.5, d)
        pr = np.stack([per(fl.lay.p[..., k]) for k in range(3)], -1) / np.maximum(per(fl.lay.a), 1e-6)[..., None]
        c.over(np.clip(pr, 0, 1), pa)
    return finish(c)


def make_card_focus() -> Image.Image:
    """卡片焦点：叠在卡片上面的一笔泥金圈（左上起笔、留缺口、收笔飞白）与暖光，中间透明；尺寸、切片与卡片相同。"""
    Wd, H, L, m = CARD_W, CARD_H, CARD_SL, CARD_M
    c = Canvas(Wd, H, 460, 3)
    x0, y0, x1, y1 = m, m, Wd - m, H - m
    glow_rrect(c, x0, y0, x1, y1, 6, rgb=mixc(GOLD, LANTERN, 0.5), alpha=0.65, width=6.5)
    d, _ = rrect(c, x0, y0, x1, y1, 6)
    c.over(mixc(GOLD, LANTERN, 0.4), 0.2 * np.exp(np.minimum(d, 0) / 6.0) * smoothstep(1.0, -0.5, d))
    loop(c, x0, y0, x1, y1, 6, center=1.0, hw=(2.3, 2.0, 2.6, 2.1), seed=461, rgb=GOLD, alpha=0.97, press=0.6, dry=0.04,
         seam=(-2.0, 9.0, 16.0, 26.0, 0.25, 0.75), tone=GOLD_DK, tone_k=0.55, slices=(L, L))
    return finish(c, band_x=(L, L), band_y=(L, L))


def make_note(hi: bool) -> Image.Image:
    """卡片里的说明框：一块淡墨（hi：藤黄）晕染，边上积一道干痕。128×80，切片 24，中间与四边拉伸。"""
    Wd, H, m, r = 128, 80, 3, 9
    c = Canvas(Wd, H, 470 + hi, 4)
    d, th = rrect(c, m, m, Wd - m, H - m, r)
    # 四角各有一点洇开的不规则（只在圆角上）
    cw = sum(corner_weight(th, k) for k in ("tl", "tr", "br", "bl"))
    d = d + 0.35 * cw * np.sin(np.radians(th) * 5.0 + 1.3)
    fill_rgb = mixc(W_TENG, TENG, 0.25) if hi else mixc(DAN, ZHONG, 0.25)
    rim_rgb = mixc(TENG, ZHESHI, 0.55) if hi else mixc(ZHONG, NONG, 0.4)
    a_fill = 0.34 if hi else 0.10
    a_rim = 0.55 if hi else 0.28
    # 颜料往下流：上沿淡而软，下沿积色、边硬；左右居中
    feather = side_value(th, 2.4, 1.0, 0.55, 1.1)
    rim_k = side_value(th, 0.25, 0.7, 1.25, 0.8)
    body = smoothstep(feather + c.aa, -feather - c.aa, d)
    c.over(fill_rgb, body * (a_fill + 0.05 * smoothstep(-8, -1, d)))
    c.over(rim_rgb, a_rim * rim_k * np.exp(-(((d + 0.9) / 0.9) ** 2)) * smoothstep(feather + 0.5, 0.0, d))
    return finish(c, band_x=(24, 24), band_y=(24, 24))


# ============================================================== 按钮、胶囊


BTN_W, BTN_H, BTN_SL = 192, 112, 72


def make_button(primary: bool, state: str) -> Image.Image:
    """一笔横扫的按钮（primary：朱砂）。192×112，左右 72 的横向九宫格；状态 normal / focus / pressed / disabled。
    起笔方中带圆、收笔上提飞白，都在两端的切片里；中段只有横向的笔毛纹，拉多长都不变形。"""
    Wd, H, L = BTN_W, BTN_H, BTN_SL
    seed = 500 + 20 * primary
    c = Canvas(Wd, H, seed + {"normal": 0, "focus": 1, "pressed": 2, "disabled": 3}[state], 4)
    yc, hw = 56.0, 35.0
    dry, dry_tail, alpha = 0.0, 0.72, 0.97
    if primary:
        core, edge, light = ZHUSHA, ZHUSHA_DK, mixc(ZHUSHA, W_ZHUSHA, 0.5)
    else:
        core, edge, light = mixc(NONG, ZHONG, 0.3), JIAO, mixc(ZHONG, DAN, 0.45)
    if state == "focus":
        core = mixc(core, mixc(TENG, ZHUSHA, 0.4), 0.2) if primary else mixc(core, ZHONG, 0.45)
        light = mixc(light, GOLD, 0.3)
    elif state == "pressed":
        yc, hw = 58.0, 32.5
        dry, dry_tail, alpha = 0.0, 0.5, 1.0
        core = mixc(core, edge, 0.4)
    elif state == "disabled":
        dry, dry_tail, alpha = 0.0, 0.82, 0.48
        core = mixc(mixc(core, DAN, 0.82 if primary else 0.7), ZHONG, 0.15)
        edge, light = mixc(edge, DAN, 0.6), mixc(core, QING, 0.3)
    st = dict(band=(L, Wd - L), seed=seed + 7, head_len=46.0, tail_len=62.0, slant=0.3, blunt=3.0, taper=0.72, lift=0.1,
              dry=dry, dry_tail=dry_tail, edge_soft=0.8, rough=0.06, pool=0.55)
    S_ = hstroke(c, 12.0, 184.0, yc, hw, **st)
    e = np.maximum(S_["edge"], 0.0)
    if state == "focus":
        c.over(mixc(GOLD, LANTERN, 0.5), 0.55 * np.exp(-(e**2) / (2 * 6.0**2)) * (1 - S_["shape"]))
    if not primary and state != "disabled":
        # 洇墨：浓墨在纸上向外洇出一圈淡墨；在夜色上它就是笔画的轮廓
        c.over(mixc(DAN, QING, 0.2), 0.42 * np.exp(-(e**2) / (2 * 2.4**2)) * (1 - S_["shape"]))
    s, T = S_["s"], S_["T"]
    rgb = mixc(core, edge, np.clip(smoothstep(0.72, 1.0, np.abs(s)) * 0.7 + 0.25 * (0.45 - T), 0, 1))
    rgb = mixc(rgb, light, np.clip((T - 0.55) * 1.2, 0, 1) * smoothstep(0.4, -0.8, s) * 0.8)
    rgb = mixc(rgb, edge, np.clip(S_["pool"], 0, 1))
    c.over(rgb, S_["cov"] * alpha)
    if state == "focus":
        g = hstroke(c, 26.0, 178.0, yc + hw + 1.0, 2.6, band=(L, Wd - L), seed=seed + 9, head_len=46.0, tail_len=58.0,
                    slant=0.0, blunt=2.0, taper=0.25, lift=0.0, dry=0.05, dry_tail=0.75, edge_soft=0.4, rough=0.1, head_taper=0.4)
        c.over(mixc(GOLD, GOLD_HI, 0.25), g["cov"])
    return finish(c, band_x=(L, L))


def make_capsule(kind: str) -> Image.Image:
    """小胶囊：pill / pill_on（开关、徽记）96×64，chip / chip_dark（五行、增益小签）80×48。
    左右为圆头，中段拉伸；边是一笔绕成的圈，起收笔在左边的圆头里。"""
    if kind.startswith("pill"):
        Wd, H, L, m, my = 96, 64, 32, 4, 6
    else:
        Wd, H, L, m, my = 80, 48, 24, 3, 5
    k = 1.0 if kind.startswith("pill") else 0.78
    c = Canvas(Wd, H, 600 + len(kind), 4)
    r = (H - 2 * my) / 2
    x0, y0, x1, y1 = m, my, Wd - m, H - my
    d, _ = rrect(c, x0, y0, x1, y1, r)
    body = smoothstep(0.5 + c.aa, -0.5 - c.aa, d)
    pool = smoothstep(-6.0 * k, -1.0, d)
    sv = np.clip((c.Y - 0.5 * (y0 + y1)) / r, -1, 1)
    streak = samp1(tex1(np.random.default_rng(620 + len(kind)), 48, 1.6), sv) - 0.5  # 横向的笔毛纹（只随 y 变）
    if kind == "pill_on":
        c.over(mixc(mixc(ZHUSHA, ZHUSHA_DK, 0.35 * pool), ZHUSHA_DK, np.clip(-0.7 * streak, 0, 1)), body * 0.96)
        top = smoothstep(0.1, -0.7, (c.Y - y0) / (y1 - y0) * 2 - 1) * smoothstep(-2.5, -6.0, d)
        c.over(mixc(ZHUSHA, W_ZHUSHA, 0.55), body * 0.35 * top)
        rim, ra, tone = ZHUSHA_DK, 0.9, JIAO
    elif kind == "chip":
        c.over(mixc(mixc(PAPER, PAPER_LT, 0.3), PAPER_SH, np.clip(0.5 * pool + 0.5 * streak, 0, 1)), body * 0.96)
        rim, ra, tone = mixc(NONG, ZHONG, 0.3), 0.9, JIAO
    else:
        c.over(mixc(mixc(NIGHT_INK, JIAO, 0.3 * pool), ZHONG, np.clip(0.35 * streak, 0, 1)), body * (0.8 + 0.08 * pool))
        rim, ra, tone = INK_RIM, 0.75, ZHONG
    hwv = tuple(v * k for v in (1.3, 1.5, 1.4, 1.9))
    seam = (-16.0 * k, 6.5 * k, 12.0 * k, 26.0 * k, 0.3, 0.7)
    loop(c, x0, y0, x1, y1, r, center=-1.4 * k, hw=hwv, seed=610 + len(kind), rgb=rim, alpha=ra, press=0.0, dry=0.03,
         seam=seam, tone=tone, tone_k=0.4)
    return finish(c, band_x=(L, L))


# ============================================================== 法器 / 心法格子


def make_slot(big: bool, kind: str) -> Image.Image:
    """HUD 上的格子（不切片）：大 128²（法器）、小 80²（心法）。kind：full / empty / evo。
    夜墨的方砚，一笔淡墨圈边（左上起笔、留缺口、收笔飞白）；空格是断续的虚笔；进化格是泥金边、暖光和金屑。"""
    N = 128 if big else 80
    k = N / 128.0
    c = Canvas(N, N, 700 + 10 * big + {"full": 0, "empty": 1, "evo": 2}[kind], 4)
    rng = c.rng
    m, r = 8 * k, 22 * k
    x0, y0, x1, y1 = m, m, N - m, N - m
    d, _ = rrect(c, x0, y0, x1, y1, r)
    body = smoothstep(0.5 + c.aa, -0.5 - c.aa, d)
    rr = np.hypot(c.X - N / 2, c.Y - N / 2) / (N / 2)
    if kind == "evo":
        glow_rrect(c, x0, y0, x1, y1, r, rgb=mixc(GOLD, LANTERN, 0.5), alpha=0.65, width=4.5 * k)
    if kind in ("full", "evo"):
        base = mixc(NIGHT_INK, mixc(ZHESHI, JIAO, 0.65), 0.45) if kind == "evo" else NIGHT_INK
        mott = noise(rng, c.X.shape, 9.0 * k * c.ss) + 0.5 * noise(rng, c.X.shape, 2.5 * k * c.ss)
        # 砚池：中间一团略浅的墨晕，四周积墨（往里凹）
        rgb = mixc(base, ZHONG, np.clip(0.16 * np.exp(-((rr / 0.62) ** 2)) + 0.035 * mott, 0, 1))
        rgb = mixc(rgb, JIAO, np.clip(0.6 * smoothstep(-16 * k, -1, d), 0, 1))
        c.over(rgb, body * 0.88)
        if kind == "evo":
            c.over(mixc(GOLD, LANTERN, 0.3), body * 0.16 * np.exp(-((rr / 0.55) ** 2)))
    else:
        c.over(NIGHT_INK, body * 0.32)
    if kind == "empty":
        p, per = rrect_perim(c, x0, y0, x1, y1, r)
        n = 12 if big else 8
        ph = np.mod(p / per * n + 0.3, 1.0)
        dash = np.sin(np.pi * np.clip(ph / 0.6, 0, 1)) ** 0.6 * (ph < 0.6)
        v = d + 1.8 * k
        hw = 2.0 * k * (0.3 + 0.7 * dash)
        T = rank01(0.8 * (samp1(tex1(np.random.default_rng(705 + big), 48, 1.0), np.clip(v / np.maximum(hw, 1e-3), -1, 1)) - 0.5)
                   + 0.25 * noise(rng, c.X.shape, (2.0 * c.ss, 2.0 * c.ss)))
        cov = smoothstep(hw + 0.45, hw - 0.45, np.abs(v)) * (dash > 0.05) * smoothstep(0.22, 0.36, T)
        c.over(INK_RIM, cov * 0.8)
        return finish(c)
    evo = kind == "evo"
    rim = mixc(GOLD, TENG, 0.25) if evo else INK_RIM
    hwv = tuple(v * k * (1.15 if evo else 1.0) for v in (2.6, 2.2, 3.0, 2.3))
    loop(c, x0, y0, x1, y1, r, center=-1.6 * k, hw=hwv, seed=720 + big, rgb=rim, alpha=0.97 if evo else 0.88, press=0.5,
         dry=0.07, wobble=0.12, seam=(-9.0 * k, 10.0 * k, 18.0 * k, 34.0 * k, 0.22, 0.8), tone=GOLD_DK if evo else ZHONG,
         tone_k=0.6)
    if evo:
        rng2 = np.random.default_rng(740 + big)
        e = 6 * k
        boxes = [(x0 - 2, y0 - 2, x0 + e * 3, y0 + e * 3), (x1 - e * 3, y1 - e * 3, x1 + 2, y1 + 2),
                 (x1 - e * 2, y0 - 2, x1 + 2, y0 + e * 2), (x0 - 2, y1 - e * 2, x0 + e * 2, y1 + 2)]
        flecks(c, rng2, boxes, 18 if big else 11, (0.6 * k + 0.3, 1.8 * k + 0.3), GOLD, 0.9, hi=GOLD_HI)
    return finish(c)


# ============================================================== 进度条


def bar_dry(c: Canvas, S_: dict, x1: float, tail_len: float, seed: int, amount: float, n: int = 7) -> np.ndarray:
    """进度条收笔的飞白：横跨笔画只有 n 根粗笔毛（每根几像素宽），越往笔尾越干、下沿先干（笔往上提，下面的毛先离纸），
    上沿一直是顺的，所以条缩到 10 像素高还看得出尾巴下面劈开的几道。只在收笔段（带外）里，返回乘到覆盖度上的系数。"""
    tt = smoothstep(x1 - tail_len, x1, c.X)
    Tc = samp1(tex1(np.random.default_rng(seed), n, 0.6), S_["s"])
    dd = amount * tt**1.3 * (0.25 + 0.75 * np.clip(S_["s"], 0.0, 1.0) ** 1.5) * smoothstep(-0.85, -0.4, S_["s"])
    return 1.0 - (1.0 - smoothstep(dd - 0.08, dd + 0.08, Tc)) * smoothstep(0.0, 0.08, dd)


def make_track() -> Image.Image:
    """进度条的底槽：一笔压低的夜墨，上半更深（凹下去），边上一道淡墨。128×36，左右 24 的横向九宫格。
    笔头要在细条（10–12 逻辑像素高，两端缩到原来的 1/3 左右）里也认得出：起笔斜落、方头、墨积得浓，
    收笔收细到四成多、往上提，尾巴下沿劈开几道粗的飞白。"""
    Wd, H, L = 128, 36, 24
    c = Canvas(Wd, H, 800, 4)
    S_ = hstroke(c, 4.0, 124.0, 18.0, 13.5, band=(L, Wd - L), seed=801, head_len=19.0, tail_len=20.0, slant=0.72, blunt=2.8,
                 taper=0.45, lift=0.24, dry=0.0, dry_tail=0.3, edge_soft=0.7, rough=0.05, tail_rx=0.95, pool=0.6)
    cov = S_["cov"] * bar_dry(c, S_, 124.0, 20.0, 802, 0.42)
    s = S_["s"]
    rgb = mixc(NIGHT_INK, JIAO, np.clip(0.65 * smoothstep(0.5, -0.9, s) + 0.5 * S_["pool"], 0, 1))
    c.over(rgb, cov * 0.88)
    e = np.maximum(S_["edge"], 0.0)
    c.over(mixc(DAN, QING, 0.2), 0.4 * np.exp(-(e**2) / (2 * 1.8**2)) * (1 - S_["shape"]))  # 洇出的一圈淡墨
    edge = cov * smoothstep(0.6, 0.97, np.abs(s)) * (1 - 0.35 * (s < 0))
    c.over(INK_RIM, edge * 0.6 * smoothstep(0.15, 0.45, S_["T"]))
    return finish(c, band_x=(L, L))


def make_fill(kind: str) -> Image.Image:
    """进度条的填充：一笔颜料，上沿略亮、下沿积色。中段沿 x 完全一致，游戏按百分比改宽度，任何宽度两端都是笔头。
    笔头画得粗放，条再细也认得出：起笔斜落、方头、颜料在起笔处积得深；收笔收细到四成、往上提，
    尾巴下沿劈开几道粗的飞白（细条上也看得见），大尺寸时还有一层细的笔毛飞白。hp 朱砂 / xp 藤黄 / boss 绛紫 / unlock 石绿 / shield 淡花青（细条）。"""
    shield = kind == "shield"
    Wd, H, L = (96, 12, 10) if shield else (96, 28, 20)
    c = Canvas(Wd, H, 820 + len(kind), 4)
    base = {"hp": ZHUSHA, "xp": mixc(TENG, GOLD, 0.5), "boss": BOSS, "unlock": SHILV, "shield": SHIELD}[kind]
    hi = mixc(base, WHITE if kind in ("xp", "shield") else PAPER_LT, 0.38)
    lo = mixc(base, JIAO, 0.38)
    if shield:
        x1, tail = 94.0, 8.0
        S_ = hstroke(c, 2.0, x1, 6.0, 3.7, band=(L, Wd - L), seed=830, head_len=8.0, tail_len=tail, slant=0.7, blunt=2.6,
                     taper=0.42, lift=0.2, dry=0.0, dry_tail=0.3, edge_soft=0.45, rough=0.04, tail_rx=0.95, pool=0.5)
        cov = S_["cov"] * bar_dry(c, S_, x1, tail, 832, 0.5, n=5)
    else:
        x1, tail = 93.0, 17.0
        S_ = hstroke(c, 3.0, x1, 14.0, 10.5, band=(L, Wd - L), seed=831 + len(kind), head_len=17.0, tail_len=tail,
                     slant=0.85, blunt=3.0, taper=0.4, lift=0.3, dry=0.0, dry_tail=0.45, edge_soft=0.6, rough=0.05,
                     tail_rx=0.95, pool=0.55)
        cov = S_["cov"] * bar_dry(c, S_, x1, tail, 840 + len(kind), 0.55)
    s, T = S_["s"], S_["T"]
    rgb = mixc(base, lo, np.clip(smoothstep(0.1, 1.0, s) * 0.85 + 0.25 * (0.5 - T), 0, 1))
    rgb = mixc(rgb, hi, np.clip(smoothstep(-0.2, -0.85, s) * 0.8 + 0.3 * (T - 0.6), 0, 1))
    rgb = mixc(rgb, lo, np.clip(0.8 * S_["pool"], 0, 1))
    c.over(rgb, cov)
    return finish(c, band_x=(L, L))


def make_pip(on: bool) -> Image.Image:
    """心灯进度点（40²，不切片）：灭 = 一个小墨圈；亮 = 圈里一点灯焰，带暖光。"""
    N = 40
    c = Canvas(N, N, 850 + on, 6)
    C = N / 2
    r = np.hypot(c.X - C, c.Y - C)
    th = np.mod(np.arctan2(c.Y - C, c.X - C), 2 * math.pi)
    if on:
        c.over(mixc(LANTERN, GOLD, 0.4), 0.55 * np.exp(-((r / 9.5) ** 2)) * smoothstep(19.5, 14, r))
    c.over(NIGHT_INK, (0.25 if on else 0.55) * smoothstep(9.6, 8.6, r))
    # 一笔圆圈（同 ui_icons 的圆相）：右上起笔，顺时针，收笔飞白，留个小缺口
    th0, span = math.radians(-40.0), math.radians(330.0)
    rel = np.mod(th - th0 + math.radians(10.0), 2 * math.pi) - math.radians(10.0)
    t = rel / span
    tc = np.clip(t, 0, 1)
    R = 10.4 + 0.5 * tc
    hw = np.interp(tc, [0.0, 0.06, 0.5, 0.9, 1.0], [1.7, 1.9, 1.6, 1.3, 0.45])
    over = np.where(t < 0, -t * span * R, 0.0)
    over = np.where(t > 1.0, 1e3, over)
    cov = smoothstep(hw + c.aa, hw - c.aa, np.hypot(r - R, over))
    tex = W.ptex(np.random.default_rng(852), ns=16, nt=256, along=8.0, across=0.6)
    b = W.sample_ptex(tex, np.clip((r - R) / np.maximum(hw, 0.3), -1, 1), tc * 0.999)
    dry = 0.5 * smoothstep(0.75, 1.0, tc) + 0.05
    cov = cov * smoothstep(dry - 0.08, dry + 0.08, b)
    c.over(GOLD if on else INK_RIM, cov * (0.95 if on else 0.85))
    if on:
        # 灯焰：上尖下圆的一滴，芯白、外金、根上一点朱砂
        fx, fy = C, C + 1.5
        dy = c.Y - fy
        wdt = np.where(dy < 0, 4.3 * np.clip(1 + dy / 9.5, 0, 1) ** 0.85, np.sqrt(np.clip(1 - (dy / 4.3) ** 2, 0, 1)) * 4.3)
        dd = np.abs(c.X - fx) - wdt
        fl = smoothstep(0.5, -0.5, dd) * (dy > -9.6) * (dy < 4.4)
        h = np.clip((-dy + 4.3) / 13.8, 0, 1)
        core = np.exp(-(((c.X - fx) / 1.6) ** 2 + ((c.Y - fy + 1.0) / 2.6) ** 2))
        frgb = mixc(mixc(ZHUSHA, TENG, smoothstep(0.0, 0.35, h)), GOLD_HI, smoothstep(0.45, 1.0, h) * 0.6)
        frgb = mixc(frgb, mixc(WHITE, GOLD_HI, 0.4), np.clip(core, 0, 1))
        c.over(frgb, fl)
    return finish(c)


# ============================================================== 提示条、小签


def make_toast(big: bool) -> Image.Image:
    """提示条：一笔横拖的夜墨，两端毛而软（big：下沿再拖一道朱砂）。toast 144×72 / toast_big 176×88。"""
    Wd, H, L = (176, 88, 64) if big else (144, 72, 56)
    c = Canvas(Wd, H, 900 + big, 4)
    yc, hw = (42.0, 29.0) if big else (36.0, 25.0)
    S_ = hstroke(c, 6.0, Wd - 6.0, yc, hw, band=(L, Wd - L), seed=901 + big, head_len=L - 8.0, tail_len=L - 8.0, slant=0.2,
                 blunt=2.2, taper=0.62, lift=0.06, dry=0.0, dry_tail=0.5, head_dry=0.3, edge_soft=1.8, rough=0.05)
    rgb = mixc(NIGHT_INK, JIAO, np.clip(np.abs(S_["s"]) ** 2 * 0.5, 0, 1))
    c.over(rgb, S_["cov"] * 0.86)
    if big:
        g = hstroke(c, 18.0, Wd - 12.0, yc + hw + 4.5, 2.5, band=(L, Wd - L), seed=905, head_len=40.0, tail_len=48.0,
                    slant=0.0, blunt=2.0, taper=0.25, lift=0.0, dry=0.03, dry_tail=0.72, edge_soft=0.4, rough=0.1, head_taper=0.45)
        c.over(ZHUSHA, g["cov"])
    return finish(c, band_x=(L, L))


# ============================================================== 其他


def make_divider() -> Image.Image:
    """分隔线：一笔淡墨横线，细入、中段匀、收笔飞白。256×24，左右 96 的横向九宫格。"""
    Wd, H, L = 256, 24, 96
    c = Canvas(Wd, H, 950, 4)
    S_ = hstroke(c, 10.0, 248.0, 12.0, 2.7, band=(L, Wd - L), seed=951, head_len=84.0, tail_len=86.0, slant=0.0, blunt=2.0,
                 taper=0.15, lift=0.0, dry=0.02, dry_tail=0.7, edge_soft=0.45, rough=0.08, head_taper=0.2)
    c.over(mixc(ZHONG, DAN, 0.35), S_["cov"] * 0.95)
    return finish(c, band_x=(L, L))


SCROLL_W, SCROLL_H, SCROLL_SL, SCROLL_BAND = 256, 480, 56, 40
SILK = mixc(mixc(HUAQING, PAPER_SH, 0.35), ZHONG, 0.12)  # 裱卷轴的绫子：淡花青


def scroll_mount(c: Canvas, per_x, y_top: float, y_bot: float, seed: int, *, flip: bool):
    """卷轴上下的绫边（淡花青的绫子，织纹极细 + 暗花云纹，靠纸一侧一道金线），沿 x 周期。"""
    rng = np.random.default_rng(seed)
    Hs = c.lay.a.shape[0]
    sh = (Hs, SCROLL_W * c.ss)
    weft = per_x(noise(rng, sh, (5.0 * c.ss, 0.3 * c.ss)))
    sheen = per_x(noise(rng, sh, 18.0 * c.ss))
    # 暗花：沿 x 周期的一排卷云（同色略亮），8 朵一个周期
    X = c.X
    ph = np.mod(X / SCROLL_W * 8.0, 1.0)
    cy = 0.5 * (y_top + y_bot)
    yy = (c.Y - cy) / (0.5 * (y_bot - y_top))
    cloud = np.exp(-(((ph - 0.5) / 0.16) ** 2 + (yy / 0.35) ** 2))
    curl = np.sin(2 * math.pi * (ph * 2.0) + yy * 3.0)
    flower = smoothstep(0.3, 0.5, cloud * (0.75 + 0.25 * curl)) * (1 - smoothstep(0.55, 0.62, cloud))
    inside = smoothstep(y_top - 0.5, y_top + 0.5, c.Y) * smoothstep(y_bot + 0.5, y_bot - 0.5, c.Y)
    rgb = SILK + 0.012 * weft[..., None] + 0.018 * sheen[..., None]
    rgb = mixc(rgb, mixc(SILK, PAPER_LT, 0.35), 0.5 * flower)
    yy01 = (c.Y - y_top) / (y_bot - y_top)
    rgb = mixc(rgb, ZHONG, 0.3 * (smoothstep(0.12, 0.0, yy01) + smoothstep(0.88, 1.0, yy01)))
    c.over(np.clip(rgb, 0, 1), inside)
    gy = y_bot - 3.0 if not flip else y_top + 3.0
    gl = smoothstep(1.4, 0.7, np.abs(c.Y - gy))
    c.over(mixc(TENG, GOLD_DK, 0.3), gl * 0.95)


def make_scroll_body() -> Image.Image:
    """宝箱卷轴的卷身：256×480，上下各 56 的切片；整张沿 x 周期（平铺），纸面沿 y 也周期。"""
    Wd, H, T, Bd = SCROLL_W, SCROLL_H, SCROLL_SL, SCROLL_BAND
    c = Canvas(Wd, H, 960, 2)
    rng = c.rng
    Cy = H - 2 * T
    pd = c.periodic(paper_field(rng, Cy, Wd, c.ss, grain=0.012, fibre=0.9), 0, T)
    c.over(paper_rgb(pd), np.ones_like(c.X))
    per_x = lambda f: c.periodic(f, 0, 0)  # noqa: E731
    # 绫边下的纸略有阴影（在切片以内结束）
    dist = np.minimum(c.Y - Bd, H - Bd - c.Y)
    c.over(mixc(PAPER_SH, ZHONG, 0.3), 0.32 * np.exp(-np.maximum(dist, 0) / 4.0) * smoothstep(T - Bd, T - Bd - 8, dist))
    scroll_mount(c, per_x, 0.0, float(Bd), 961, flip=False)
    scroll_mount(c, per_x, float(H - Bd), float(H), 962, flip=True)
    return finish(c, clear=False)


SCROLL_END_W, SCROLL_KNOB, SCROLL_TASSEL = 112, 34, 116


def make_scroll_end() -> Image.Image:
    """卷轴左端（不切片，游戏水平镜像得到右端）：卷起的纸筒 + 木轴头 + 朱砂穗子。
    图的右边缘贴着卷身的左边缘；卷身在本图里占 y ∈ [34, 514)（与 scroll_body 同高），上下伸出轴头，穗子垂在下面。"""
    Wd = SCROLL_END_W
    H = SCROLL_H + 2 * SCROLL_KNOB + SCROLL_TASSEL
    y0, y1 = SCROLL_KNOB, SCROLL_KNOB + SCROLL_H
    c = Canvas(Wd, H, 970, 3)
    rng = c.rng
    X, Y = c.X, c.Y
    ax, rad = 76.0, 34.0  # 纸筒中心线与半径（右缘到 110）
    u = np.clip((X - ax) / rad, -1, 1)
    inside = smoothstep(rad + 0.5, rad - 0.5, np.abs(X - ax)) * smoothstep(y0 - 0.5, y0 + 0.5, Y) * smoothstep(y1 + 0.5, y1 - 0.5, Y)
    pd = paper_field(rng, H, Wd, c.ss, grain=0.01, fibre=0.6)
    shade = 0.62 * (u + 0.2) ** 2 - 0.1  # 左上受光：偏左处最亮，两侧转暗
    rgb = mixc(paper_rgb(pd), mixc(PAPER_SH, ZHONG, 0.5), np.clip(shade, 0, 1))
    rgb = mixc(rgb, PAPER_LT, np.clip(-shade * 3.0, 0, 1))
    c.over(rgb, inside)
    # 纸筒上下的绫边，与卷身同色，随圆柱明暗
    for (a, b, flip) in ((y0, y0 + SCROLL_BAND, False), (y1 - SCROLL_BAND, y1, True)):
        cc = Canvas(Wd, H, 971, c.ss)
        scroll_mount(cc, lambda f, cc=cc: cc.periodic(f, 0, 0), float(a), float(b), 961 if not flip else 962, flip=flip)
        rgbm, am = cc.lay.p / np.maximum(cc.lay.a, 1e-6)[..., None], cc.lay.a
        rgbm = mixc(rgbm, JIAO, np.clip(shade, 0, 1) * 0.7)
        rgbm = mixc(rgbm, WHITE, np.clip(-shade * 1.5, 0, 1))
        c.over(np.clip(rgbm, 0, 1), am * inside)
    # 纸筒上几道卷层的细线（淡墨，竖向）
    for kk, xx in enumerate((ax - 25, ax - 12, ax + 8, ax + 22)):
        wv = 0.6 * np.sin(Y / 37.0 + kk)
        c.over(mixc(ZHONG, DAN, 0.4), 0.22 * smoothstep(0.9, 0.3, np.abs(X - xx - wv)) * inside)
    line_stroke(c, False, ax - rad + 1.0, y0 - 1, y1 + 1, 1.6, period=SCROLL_H, origin=y0, seed=972, rgb=JIAO, alpha=0.9,
                head_len=8, tail_len=12, dry=0.04, dry_tail=0.35)
    line_stroke(c, False, ax + rad - 1.0, y0 - 1, y1 + 1, 0.9, period=SCROLL_H, origin=y0, seed=973, rgb=ZHONG, alpha=0.55,
                head_len=8, tail_len=12, dry=0.04, dry_tail=0.35)
    # 纸筒上下口的椭圆（看得出是卷起来的）
    for yy in (y0, y1):
        de = np.hypot((X - ax) / rad, (Y - yy) / 4.0) - 1.0
        c.over(mixc(PAPER_SH, ZHONG, 0.3), smoothstep(0.0, -0.08, de) * 0.9)
        c.over(JIAO, smoothstep(0.12, 0.03, np.abs(de)) * 0.85)
    # 轴杆与轴头：赭石木杆，象牙色的轴头（扁鼓），墨线勾边
    wood = mixc(ZHESHI, JIAO, 0.3)
    for top in (True, False):
        ya, yb = (4.0, y0 + 2.0) if top else (y1 - 2.0, y1 + SCROLL_KNOB - 4.0)
        rod = smoothstep(8.5, 7.5, np.abs(X - ax)) * smoothstep(ya - 0.5, ya + 0.5, Y) * smoothstep(yb + 0.5, yb - 0.5, Y)
        rr_ = np.clip((X - ax) / 8.0, -1, 1)
        c.over(mixc(mixc(wood, PAPER_SH, 0.2), JIAO, np.clip(0.55 * (rr_ + 0.25) ** 2, 0, 1)), rod)
        cy = (ya + 11.0) if top else (yb - 11.0)
        dk = np.hypot((X - ax) / 15.0, (Y - cy) / 10.0) - 1.0
        cap = smoothstep(0.04, -0.04, dk)
        ivory = mixc(PAPER, PAPER_SH, 0.25)
        c.over(mixc(ivory, ZHONG, np.clip(0.55 * ((X - ax) / 15.0 + 0.3) ** 2, 0, 1)), cap)
        c.over(JIAO, smoothstep(0.11, 0.03, np.abs(dk)) * 0.9)
        c.over(mixc(ivory, WHITE, 0.5), 0.6 * np.exp(-(((X - ax + 6) / 2.6) ** 2 + ((Y - cy + 3) / 3.0) ** 2)))
    # 朱砂穗子：从下轴头垂下，打一个结，散开成穗
    ky = y1 + SCROLL_KNOB - 6.0
    cord = np.array([(ax, ky), (ax - 4, ky + 14), (ax - 2, ky + 30), (ax, ky + 38)])
    seg_stroke(c, V.bezier(cord, 40), 1.7, seed=974, rgb=ZHUSHA, taper=(1.0, 1.0))
    knot_y = ky + 42
    dk = np.hypot((X - ax) / 5.8, (Y - knot_y) / 4.8) - 1.0
    c.over(mixc(ZHUSHA, ZHUSHA_DK, np.clip(0.5 + 0.5 * (X - ax) / 5.8, 0, 1)), smoothstep(0.08, -0.08, dk))
    trng = np.random.default_rng(975)
    for i in range(18):
        x_top = ax + trng.uniform(-3.5, 3.5)
        x_bot = ax + (x_top - ax) * 2.4 + trng.uniform(-3, 3)
        y_end = knot_y + trng.uniform(54, 68)
        pts = V.bezier(np.array([(x_top, knot_y + 3), (x_top, knot_y + 20), (x_bot, y_end - 18), (x_bot, y_end)]), 48)
        seg_stroke(c, pts, trng.uniform(0.55, 0.9), seed=976 + i, rgb=mixc(ZHUSHA, ZHUSHA_DK, trng.uniform(0, 0.7)),
                   alpha=0.95, taper=(1.0, 0.4))
    c.over(ZHUSHA_DK, smoothstep(1.4, 0.6, np.abs(Y - knot_y - 7.5)) * smoothstep(5.4, 4.4, np.abs(X - ax)))
    return finish(c)


def make_arrow_marker() -> Image.Image:
    """屏幕外遭遇的指示（128²，白色可染色）：半透明圆底 + 一笔圆相 + 指向 +X 的笔锋。游戏绕中心旋转，图标画在圆底上。"""
    N = 128
    c = Canvas(N, N, 990, 4)
    C = N / 2
    r = np.hypot(c.X - C, c.Y - C)
    th = np.mod(np.arctan2(c.Y - C, c.X - C), 2 * math.pi)
    # 指针：从圆边向右撇出的一笔，根部宽、笔锋尖，两边略弧
    tip = 124.0
    base_x = C + 30.0
    xx = (c.X - base_x) / (tip - base_x)
    half = 15.0 * np.clip(1 - xx, 0, 1) ** 1.35
    ptr = smoothstep(0.6, -0.6, np.abs(c.Y - C) - half) * (xx >= 0) * (xx <= 1)
    a = ptr
    disc = smoothstep(38.5, 37.5, r)
    a = 1 - (1 - a) * (1 - 0.55 * disc)
    th0, span = math.radians(-30.0), math.radians(335.0)
    rel = np.mod(th - th0 + math.radians(8.0), 2 * math.pi) - math.radians(8.0)
    t = rel / span
    tc = np.clip(t, 0, 1)
    R = 40.0 + 0.8 * tc
    hw = np.interp(tc, [0.0, 0.05, 0.5, 0.9, 1.0], [3.4, 3.8, 3.2, 2.6, 0.8])
    over = np.where(t < 0, -t * span * R, 0.0)
    over = np.where(t > 1.0, 1e3, over)
    cov = smoothstep(hw + c.aa, hw - c.aa, np.hypot(r - R, over))
    tex = W.ptex(np.random.default_rng(991), ns=16, nt=512, along=8.0, across=0.6)
    b = W.sample_ptex(tex, np.clip((r - R) / np.maximum(hw, 0.3), -1, 1), tc * 0.999)
    dry = 0.5 * smoothstep(0.78, 1.0, tc) + 0.05
    cov = cov * smoothstep(dry - 0.08, dry + 0.08, b)
    a = 1 - (1 - a) * (1 - cov)
    c.over(WHITE, a)
    return finish(c)


def make_focus_ring() -> Image.Image:
    """键盘 / 手柄焦点：四角各一笔泥金折角（竖笔起、转折、横笔收，收笔飞白），带一点暖光，中间透明。
    128²，切片 48，中间与四边拉伸（四边是空的）。"""
    N, L = 128, 48
    c = Canvas(N, N, 1000, 4)
    m, arm, rc = 7.0, 30.0, 5.0
    gl = np.zeros_like(c.X)
    paths = []
    for i, (sx, sy) in enumerate(((1, 1), (-1, 1), (-1, -1), (1, -1))):
        cx = m if sx > 0 else N - m
        cy = m if sy > 0 else N - m
        # 竖臂末端 → 转角（圆一点） → 横臂末端
        a0 = (cx, cy + sy * arm)
        a1 = (cx, cy + sy * rc)
        a2 = (cx + sx * rc, cy)
        a3 = (cx + sx * arm, cy)
        pts = np.vstack([W.seg_pts(a0, a1, n=30), V.bezier([a1, (cx, cy), a2], 12)[1:], W.seg_pts(a2, a3, n=30)[1:]])
        pts = V.arc_resample(pts, 72)
        f = V.stroke_fields(c.X, c.Y, pts, np.full(len(pts), 3.0))
        gl = np.maximum(gl, np.exp(-np.hypot(np.maximum(np.abs(f["perp"]) - 2.0, 0), f["over"]) ** 2 / (2 * 3.4**2)))
        paths.append(pts)
    inside_corner = (np.minimum(c.X, N - c.X) < L - 1) & (np.minimum(c.Y, N - c.Y) < L - 1)
    c.over(mixc(GOLD, LANTERN, 0.5), 0.5 * gl * inside_corner)
    for i, pts in enumerate(paths):
        seg_stroke(c, pts, 2.8, seed=1010 + i, rgb=GOLD, dry=0.55, dry_start=0.6, jitter=0.14, taper=(0.9, 0.3))
    return finish(c, band_x=(L, L), band_y=(L, L))


def make_menu_hl() -> Image.Image:
    """标题菜单的选中底：一笔淡夜墨横扫，两端毛而软，下沿一道泥金干笔，四周一点暖光。320×80，左右 112 的横向九宫格。"""
    Wd, H, L = 320, 80, 112
    c = Canvas(Wd, H, 1100, 4)
    yc, hw = 38.0, 22.0
    S_ = hstroke(c, 14.0, 306.0, yc, hw, band=(L, Wd - L), seed=1101, head_len=96.0, tail_len=96.0, slant=0.2, blunt=2.2,
                 taper=0.5, lift=0.06, dry=0.0, dry_tail=0.55, head_dry=0.35, edge_soft=2.2, rough=0.06)
    e = np.maximum(S_["edge"], 0.0)
    c.over(mixc(GOLD, LANTERN, 0.6), 0.22 * np.exp(-(e**2) / (2 * 7.0**2)) * (1 - S_["shape"]) * smoothstep(306, 250, c.X) * smoothstep(14, 60, c.X))
    c.over(mixc(NIGHT_INK, JIAO, 0.3), S_["cov"] * 0.64)
    g = hstroke(c, 40.0, 292.0, yc + hw + 3.0, 1.9, band=(L, Wd - L), seed=1102, head_len=70.0, tail_len=84.0, slant=0.0,
                blunt=2.0, taper=0.2, lift=0.0, dry=0.04, dry_tail=0.75, edge_soft=0.4, rough=0.1, head_taper=0.35)
    c.over(GOLD, g["cov"] * 0.95)
    return finish(c, band_x=(L, L))


# ============================================================== 清单

TXT_PAPER, TXT_INK, TXT_GOLD = "#ede4cf", "#17140f", "#ffd98a"


def specs() -> dict:
    """名字 → (生成函数, slice, center, sides, 建议文字色, 用途, 额外字段)。顺序即 skin.json 的顺序。"""
    sp: dict = {}

    def add(name, fn, slc, center, sides, text, note, **extra):
        sp[name] = (fn, list(slc), center, sides, text, note, extra)

    hx = lambda v: (v, 0, v, 0)  # noqa: E731  横向九宫格
    add("panel", make_panel, (176, 176, 80, 80), "tile", "tile", TXT_INK, "大面板：毛边宣纸，左上角洇一团淡墨（暂停、结算、心灯、设置）")
    add("panel_dark", make_panel_dark, (32,) * 4, "stretch", "stretch", TXT_PAPER, "夜墨小面板：HUD 底板、提示框、结算数据格")
    add("overlay_vignette", make_overlay, (0,) * 4, "stretch", "stretch", TXT_PAPER, "全屏压暗：整张拉伸铺满屏幕，四周墨云")
    for k, nm in (("fan", "凡品：铁灰内光、单道旧金线"), ("ling", "灵品：青蓝内光、双金线、方胜结"),
                  ("xuan", "玄品：紫色内光、双金线、方胜结、一圈金点"), ("tian", "天品：金色内光、双金线、连珠、如意结、洒金"),
                  ("yi", "异化：朱红内光、两线之间一道朱漆"), ("he", "合璧：玉青内光、双金线、连珠、如意结、洒金")):
        add(f"card_{k}", lambda k=k: LQ.make_card(k), (LQ.CARD_SL,) * 4, "tile", "tile", TXT_PAPER,
            f"升级 / 宝箱卡 600×920（节点 300×460）：黑漆描金，{nm}；字用纸色或金色")
    add("card_omen", lambda: make_card("omen"), (CARD_SL,) * 4, "tile", "tile", TXT_INK, "夜签卡：朱砂双线框")
    add("card_focus", LQ.make_card_focus, (LQ.CARD_SL,) * 4, "stretch", "stretch", TXT_PAPER,
        "卡片焦点 624×944：节点比卡片每边大 6（逻辑），卡边一道泥金亮线、往外一圈暖光")
    add("note_box", lambda: make_note(False), (24,) * 4, "stretch", "stretch", "#4f4942", "卡片里的说明框：淡墨晕染")
    add("note_box_hi", lambda: make_note(True), (24,) * 4, "stretch", "stretch", "#2e2924", "卡片里的提示框（可进化等）：藤黄晕染")
    for primary in (False, True):
        base = "btn_primary" if primary else "btn"
        for st in ("normal", "focus", "pressed", "disabled"):
            name = base if st == "normal" else f"{base}_{st}"
            txt = "#8f877a" if st == "disabled" else ("#f6efe0" if primary else TXT_PAPER)
            what = {"normal": "", "focus": "（焦点）", "pressed": "（按下）", "disabled": "（不可用）"}[st]
            add(name, lambda p=primary, s=st: make_button(p, s), hx(BTN_SL), "stretch", "stretch", txt,
                ("主按钮：朱砂横扫" if primary else "按钮：浓墨横扫") + what)
    add("pill", lambda: make_capsule("pill"), hx(32), "stretch", "stretch", TXT_PAPER, "开关 / 徽记小胶囊（关）")
    add("pill_on", lambda: make_capsule("pill_on"), hx(32), "stretch", "stretch", "#f6efe0", "开关 / 徽记小胶囊（开）：朱砂")
    for big, sz in ((True, "l"), (False, "s")):
        what = "法器格 128²（显示 64）" if big else "心法格 88²（显示 44）"
        add(f"slot_{sz}", lambda b=big: LQ.make_slot(b, "full"), (0,) * 4, "stretch", "stretch", TXT_PAPER, f"{what}：黑漆方砚，金边")
        add(f"slot_{sz}_empty", lambda b=big: LQ.make_slot(b, "empty"), (0,) * 4, "stretch", "stretch", TXT_PAPER,
            f"{what}：空格，一道淡金虚边")
        add(f"slot_{sz}_evo", lambda b=big: LQ.make_slot(b, "evo"), (0,) * 4, "stretch", "stretch", TXT_GOLD,
            f"{what}：进化，双金边、暖光、洒金")
    add("bar_track", lambda: LQ.make_track(""), hx(24), "stretch", "stretch", TXT_PAPER,
        "进度条底槽：黑漆槽、细金边（填充放在里面，四周各留 4，即逻辑 2）")
    add("hud_hp_track", lambda: LQ.make_track("hp"), hx(48), "stretch", "stretch", TXT_PAPER,
        "大血条框 256×60（建议显示 460×30）：黑漆、金边，两头一粒金珠；填充四周各留 14（逻辑 7），数字写在条里")
    add("hud_xp_track", lambda: LQ.make_track("xp"), hx(16), "stretch", "stretch", TXT_PAPER,
        "经验条框 128×20（建议显示 460×10，放在血条下）：填充四周各留 4（逻辑 2）")
    for k, nm, txt, fn in (("hp", "血条：朱漆红", TXT_PAPER, lambda: LQ.make_fill("hp")),
                           ("xp", "经验条：泥金", TXT_INK, lambda: LQ.make_fill("xp")),
                           ("boss", "夜主血条：绛紫", TXT_PAPER, lambda: make_fill("boss")),
                           ("unlock", "解锁进度：石绿", TXT_PAPER, lambda: make_fill("unlock"))):
        add(f"bar_fill_{k}", fn, hx(20), "stretch", "stretch", txt, f"{nm}，宽度按百分比设")
    add("bar_fill_shield", lambda: LQ.make_fill("shield"), hx(10), "stretch", "stretch", TXT_PAPER,
        "护盾：淡青白，叠在血条上半，宽度按护盾值")
    add("bar_fill_trail", lambda: LQ.make_fill("trail"), hx(20), "stretch", "stretch", TXT_INK,
        "掉血残影：浅色，画在血条填充后面，比血条慢半拍缩回")
    add("hud_portrait", LQ.make_portrait, (0,) * 4, "stretch", "stretch", TXT_PAPER,
        "头像章 208²（显示 104）：黑漆圆盘、两道金圈，中间直径 156（显示 78）的窗口透明，主角胸像 ui/portrait_hero 画在下面")
    for st, nm in (("off", "灭"), ("on", "亮"), ("full", "满格，更亮带光")):
        add("hud_ult_tick" + ("" if st == "off" else f"_{st}"), lambda st=st: LQ.make_ult_tick(st), (0,) * 4, "stretch", "stretch",
            TXT_PAPER, f"燃灯刻度一格（{nm}）34×20（显示 17×10）：十二格绕头像章，长边沿圆周，圆心距 = 外径/2 − 8.5（逻辑）")
    add("hud_level_seal", LQ.make_level_seal, (0,) * 4, "stretch", "stretch", "#f6eedc",
        "等级印 60²（显示 30）：朱砂方印，压在头像章右下；等级数字由界面写（马善政 17 号、纸色）")
    add("pip", lambda: make_pip(False), (0,) * 4, "stretch", "stretch", TXT_PAPER, "心灯进度点（灭）")
    add("pip_on", lambda: make_pip(True), (0,) * 4, "stretch", "stretch", TXT_PAPER, "心灯进度点（亮）：灯焰")
    add("toast", lambda: make_toast(False), hx(56), "stretch", "stretch", TXT_PAPER, "提示条：夜墨横拖")
    add("toast_big", lambda: make_toast(True), hx(64), "stretch", "stretch", TXT_PAPER, "大提示条：下沿一道朱砂")
    add("chip", lambda: make_capsule("chip"), hx(24), "stretch", "stretch", TXT_INK, "小签（纸色）：五行、增益")
    add("chip_dark", LQ.make_chip, hx(24), "stretch", "stretch", TXT_PAPER, "小签（黑漆细金边）：HUD 上的五行计数、卡上的品阶签")
    add("divider", make_divider, hx(96), "stretch", "stretch", "#4f4942", "分隔线：两头尖的淡墨横线")
    add("scroll_body", make_scroll_body, (0, SCROLL_SL, 0, SCROLL_SL), "tile", "tile", TXT_INK, "宝箱卷轴的卷身：横向平铺")
    add("scroll_end", make_scroll_end, (0,) * 4, "stretch", "stretch", TXT_INK,
        f"卷轴左端（右端水平镜像）：右缘贴卷身，卷身占 y {SCROLL_KNOB}–{SCROLL_KNOB + SCROLL_H}")
    add("arrow_marker", make_arrow_marker, (0,) * 4, "stretch", "stretch", "#ffffff", "屏幕外遭遇指示：白色染色，指向 +X，绕中心旋转",
        tint=True)
    add("focus_ring", make_focus_ring, (48,) * 4, "stretch", "stretch", TXT_GOLD, "键盘 / 手柄焦点框：四角泥金折笔")
    add("menu_hl", make_menu_hl, hx(112), "stretch", "stretch", TXT_GOLD, "标题菜单选中项的底：夜墨横扫 + 泥金")
    return sp


def build(names=None) -> dict[str, Image.Image]:
    sp = specs()
    return {n: sp[n][0]() for n in (names or sp)}


def manifest(images: dict[str, Image.Image]) -> dict:
    items = {}
    for name, (_, slc, center, sides, text, note, extra) in specs().items():
        img = images[name]
        items[name] = {"file": f"{name}.png", "size": [img.width, img.height], "slice": slc, "center": center,
                       "sides": sides, "text": text, "note": note, **extra}
    return {"scale": SCALE, "items": items}


def dump_manifest(m: dict) -> str:
    lines = ["{", f'  "scale": {m["scale"]},', '  "items": {']
    names = list(m["items"])
    for i, n in enumerate(names):
        tail = "," if i < len(names) - 1 else ""
        lines.append(f"    {json.dumps(n, ensure_ascii=False)}: {json.dumps(m['items'][n], ensure_ascii=False)}{tail}")
    lines += ["  }", "}"]
    return "\n".join(lines) + "\n"


# ============================================================== 检查图

ICON_DIR = V.OUT / "assets@2x" / "ui"  # ui_icons.py 的 2 倍图标（只读，用来摆样子；没有就画个圆代替）
NIGHT_HEX = S.NIGHT_AMBIENT


def _font(name: str, size: int):
    import ui_fonts  # noqa: PLC0415  只有出检查图时才需要（第一次会下载完整字体）

    return ui_fonts.font(name, int(round(size)))


def _icon(name: str, size: int) -> Image.Image:
    path = ICON_DIR / f"icon_{name}.png"
    if path.exists():
        return Image.open(path).convert("RGBA").resize((size, size), Image.LANCZOS)
    im = Image.new("RGBA", (size, size))
    ImageDraw.Draw(im).ellipse((2, 2, size - 3, size - 3), fill=S.PAPER, outline=S.INK["jiao"], width=max(2, size // 16))
    return im


def _tint(img: Image.Image, hex_: str) -> Image.Image:
    a = np.asarray(img, dtype=np.float64)
    t = np.array(S.hex_to_rgb(hex_), dtype=np.float64) / 255.0
    a[..., :3] = a[..., :3] * t
    return Image.fromarray(np.round(a).astype(np.uint8), "RGBA")


class Board:
    """检查图画板：RGBA 底，按直通 alpha 叠图，写字。"""

    def __init__(self, w: int, h: int, bg):
        self.im = Image.new("RGBA", (w, h), bg)
        self.dr = ImageDraw.Draw(self.im)

    def put(self, img: Image.Image, x: float, y: float, *, angle: float = 0.0, center: bool = False):
        if angle:
            img = img.rotate(angle, resample=Image.BICUBIC, expand=True)
        x, y = int(round(x)), int(round(y))
        if center:
            x, y = x - img.width // 2, y - img.height // 2
        x0, y0 = max(x, 0), max(y, 0)
        x1, y1 = min(x + img.width, self.im.width), min(y + img.height, self.im.height)
        if x1 <= x0 or y1 <= y0:
            return
        self.im.alpha_composite(img.crop((x0 - x, y0 - y, x1 - x, y1 - y)), (x0, y0))

    def fill(self, box, color):
        self.dr.rectangle(box, fill=color)

    def text(self, x, y, s, font, fill, anchor="la", **kw):
        self.dr.text((x, y), s, font=font, fill=fill, anchor=anchor, **kw)


class Skin:
    """按清单把皮肤画到指定尺寸：k=1 以贴图像素计（4K），k=0.5 以 1080p 逻辑像素计（与游戏一致）。"""

    def __init__(self, images: dict, sp: dict, k: float = 1.0):
        self.images, self.sp, self.k = images, sp, k

    def __call__(self, name: str, w: float, h: float | None = None) -> Image.Image:
        img = self.images[name]
        _, slc, center, sides, *_ = self.sp[name]
        if h is None:
            h = img.height * self.k
        w, h = int(round(w)), int(round(h))
        if list(slc) == [0, 0, 0, 0]:
            return img.resize((w, h), Image.LANCZOS) if (w, h) != img.size else img
        return nine_slice(img, slc, w, h, center, sides, max_corner_scale=self.k)

    def fixed(self, name: str, scale: float = 1.0) -> Image.Image:
        img = self.images[name]
        s = self.k * scale
        return img if s == 1 else img.resize((int(round(img.width * s)), int(round(img.height * s))), Image.LANCZOS)


def _bar(B: Board, sk: Skin, x, y, w, h, fill: str | None, pct: float, shield: float = 0.0):
    """底槽 + 填充（上下各留 h·4/36）+ 可选护盾细条。"""
    B.put(sk("bar_track", w, h), x, y)
    pad = h * 4.0 / 36.0
    fw = (w - 2 * pad) * pct
    if fill and fw >= 2:
        B.put(sk(fill, fw, h - 2 * pad), x + pad, y + pad)
    if shield > 0:
        sw = (w - 2 * pad) * shield
        B.put(sk("bar_fill_shield", sw, (h - 2 * pad) * 12 / 28), x + pad, y + pad - 1)


def _card(B: Board, sk: Skin, kind: str, x, y, w, h, *, icon: str, name: str, desc: list[str], note: str | None, hi=False,
          rarity: str = "", focus=False):
    """一张升级卡的样子：品级印、图标、名字、说明、说明框。坐标单位随 sk.k。"""
    k = sk.k
    B.put(sk(kind, w, h), x, y)
    m = 34 * k * 2
    if rarity:
        seal = 44 * k
        rc = {"card_fan": S.INK["dan"], "card_ling": "#3e6fa8", "card_xuan": "#7a4fb0", "card_tian": "#c9962e", "card_yi": "#cf8cdb",
              "card_he": "#f6bd62"}.get(kind, S.ACCENT["zhusha"])
        B.dr.rounded_rectangle((x + m, y + m, x + m + seal, y + m + seal), radius=4 * k, fill=rc)
        B.text(x + m + seal / 2, y + m + seal / 2 + 2 * k, rarity, _font("brush", 34 * k), "#f6efe0", "mm")
    isz = int(round(112 * k))
    B.put(_icon(icon, isz), x + w - m - isz + 8 * k, y + m - 10 * k)
    B.text(x + m, y + m + 70 * k, name, _font("brush", 54 * k), S.INK["jiao"])
    for i, line in enumerate(desc):
        B.text(x + m, y + m + 150 * k + i * 42 * k, line, _font("serif", 27 * k), "#3a342d")
    if note:
        nh = 92 * k
        B.put(sk("note_box_hi" if hi else "note_box", w - 2 * m + 16 * k, nh), x + m - 8 * k, y + h - m - nh + 6 * k)
        B.text(x + m + 8 * k, y + h - m - nh / 2 + 6 * k, note, _font("serif", 24 * k), "#2e2924" if hi else "#4f4942", "lm")
    if focus:
        B.put(sk("card_focus", w, h), x, y)


def review_sheet(images: dict[str, Image.Image], path: Path) -> None:
    """每件按 nine_slice 摆 2–3 种尺寸（贴图像素，1:1，相当于 4K 屏），左边夜色底、右边纸色底，配上样字。
    另出一张 ui_skin_mock.png：按 1080p 逻辑像素拼的四个界面（HUD、升级、暂停 / 心灯、宝箱 / 夜签）。"""
    sp = specs()
    sk = Skin(images, sp, 1.0)
    brush, serif = (lambda z: _font("brush", z)), (lambda z: _font("serif", z))
    P, I = S.PAPER, S.INK["jiao"]

    def demo(name: str) -> list[tuple[Image.Image, callable]]:
        """返回 [(底图, 画样字的函数(board, x, y)), ...]。"""
        out = []

        def add(img, deco=None):
            out.append((img, deco))

        def centered(txt, f, col_):
            return lambda B, x, y, im: B.text(x + im.width / 2, y + im.height / 2, txt, f, col_, "mm")

        t = sp[name][4]
        if name == "panel":
            for w, h in ((560, 380), (980, 600)):
                add(sk(name, w, h), lambda B, x, y, im: (B.text(x + 60, y + 50, "暂停", brush(84), I),
                                                       B.text(x + 64, y + 170, "已行 12 分 34 秒 · 击杀 1234", serif(30), "#3a342d"),
                                                       B.text(x + 64, y + 220, "灯油 86 · 古灯 2 盏", serif(30), "#3a342d")))
        elif name == "panel_dark":
            for w, h in ((180, 72), (360, 120), (560, 220)):
                add(sk(name, w, h), lambda B, x, y, im: (B.text(x + 26, y + 20, "炉心 · 二级", serif(28), P),
                                                       B.text(x + 26, y + 60, "灯火伤害 +20%", serif(24), S.INK["qing"]) if im.height > 100 else None))
        elif name == "overlay_vignette":
            for w, h in ((640, 360), (960, 360)):
                bg = Image.open(V.OUT / "review@2x" / "night_scene.png").convert("RGBA") if (V.OUT / "review@2x" / "night_scene.png").exists() else Image.new("RGBA", (2000, 1120), NIGHT_HEX)
                bg = bg.resize((w, int(round(bg.height * w / bg.width)))).crop((0, 0, w, h))
                bg.alpha_composite(sk(name, w, h))
                add(bg, centered("择一而行", brush(64), P))
        elif name.startswith("card_") and name not in ("card_focus", "card_omen"):
            nm = {"card_fan": "凡", "card_ling": "灵", "card_xuan": "玄", "card_tian": "天", "card_yi": "异", "card_he": "合"}[name]
            for w, h in ((320, 400), (460, 660)):
                small = w < 400
                add(None, lambda B, x, y, im, w=w, h=h, small=small: _card(
                    B, sk, name, x, y, w, h, icon="lamp" if not small else "changming", name="灯火" if not small else "长明",
                    desc=["灯光照到的妖物", "每秒受 12 点灼伤"] if not small else ["灯火 +1 级"], note=None if small else "下一级：范围 +15%",
                    hi=(name == "card_tian"), rarity=nm))
                out[-1] = (Image.new("RGBA", (w, h)), out[-1][1])
        elif name == "card_omen":
            for w, h in ((320, 400), (460, 660)):
                def deco(B, x, y, im):
                    B.text(x + im.width / 2, y + im.height * 0.36, "月晦", brush(110 if im.width > 400 else 80), S.ACCENT["zhusha"], "mm")
                    B.text(x + im.width / 2, y + im.height * 0.62, "妖物 +25%", serif(28), "#3a342d", "mm")
                    B.text(x + im.width / 2, y + im.height * 0.62 + 44, "灯油 +40%", serif(28), "#3a342d", "mm")
                add(sk(name, w, h), deco)
        elif name == "card_focus":
            for w, h in ((320, 400), (460, 660)):
                im = sk("card_ling", w, h).copy()
                im.alpha_composite(sk(name, w, h))
                add(im)
        elif name in ("note_box", "note_box_hi"):
            for w, h in ((260, 64), (440, 110)):
                pap = sk("card_fan", w + 120, h + 110).copy()
                pap.alpha_composite(sk(name, w, h), (60, 55))
                add(pap, lambda B, x, y, im, h=h: B.text(x + 80, y + 55 + h / 2, "进化：灯火 + 长明" if h > 80 else "范围 +15%", serif(26), t, "lm"))
        elif name.startswith("btn"):
            for w, h in ((200, 84), (380, 104)):
                add(sk(name, w, h), centered("再来" if w < 300 else "开始夜行", brush(46 if w < 300 else 54), t))
        elif name.startswith("pill"):
            for w, h in ((84, 52), (190, 64)):
                add(sk(name, w, h), centered("开" if w < 100 else "音效 开" if name == "pill_on" else "音效 关", serif(26), t))
        elif name.startswith("slot_"):
            big = name.startswith("slot_l")
            evo = name.endswith("evo")
            empty = name.endswith("empty")
            img = sk.fixed(name)

            def deco(B, x, y, im, big=big, evo=evo, empty=empty):
                if not empty:
                    isz = int(im.width * 0.78)
                    B.put(_icon(("lamp" if big else "changming") + ("_evo" if evo and big else ""), isz), x + (im.width - isz) / 2,
                          y + (im.height - isz) / 2)
                    B.text(x + im.width - 12, y + im.height - 8, "5" if evo else "3", serif(30 if big else 22), t, "rb",
                           stroke_width=3, stroke_fill=I)
            add(img, deco)
            add(img.resize((img.width * 3 // 2, img.height * 3 // 2), Image.LANCZOS), deco)
        elif name == "bar_track":
            for w, h in ((180, 30), (400, 36), (720, 36)):
                add(Image.new("RGBA", (w, h)), lambda B, x, y, im: _bar(B, sk, x, y, im.width, im.height, None, 0))
        elif name.startswith("bar_fill"):
            kind = name
            if name == "bar_fill_shield":
                for w in (300, 600):
                    add(Image.new("RGBA", (w, 36)), lambda B, x, y, im: _bar(B, sk, x, y, im.width, 36, "bar_fill_hp", 0.72, 0.45))
            else:
                for w, pct in ((300, 0.12), (300, 0.55), (600, 1.0)):
                    add(Image.new("RGBA", (w, 36)), lambda B, x, y, im, p=pct, kind=kind: _bar(B, sk, x, y, im.width, 36, kind, p))
        elif name in ("pip", "pip_on"):
            row = Image.new("RGBA", (5 * 44, 40))
            for i in range(5):
                row.alpha_composite(images["pip_on" if i < 3 else "pip"], (i * 44, 0))
            add(row)
            add(images[name].resize((80, 80), Image.LANCZOS))
        elif name in ("toast", "toast_big"):
            for w in (300, 560):
                add(sk(name, w), centered("获得 灯火" if name == "toast" else ("不夜城" if w < 400 else "进化  不夜城"),
                                          serif(30) if name == "toast" else brush(48), t))
        elif name in ("chip", "chip_dark"):
            for w in (90, 170):
                add(sk(name, w), centered("火" if w < 100 else "火 3 · 炉心", serif(24), t))
        elif name == "divider":
            for w in (300, 760):
                add(sk(name, w))
        elif name == "scroll_body":
            for w in (520, 1000):
                body = sk(name, w, 480)
                end = images["scroll_end"]
                im = Image.new("RGBA", (w + 2 * end.width, end.height))
                im.alpha_composite(body, (end.width, SCROLL_KNOB))
                im.alpha_composite(end, (0, 0))
                im.alpha_composite(end.transpose(Image.FLIP_LEFT_RIGHT), (w + end.width, 0))
                n = 1 if w < 600 else 3
                tiles = []
                for i in range(n):
                    tiles.append(("card_" + ("ling", "tian", "xuan")[i], ("sword", "lamp_evo", "bell")[i]))

                def deco(B, x, y, im, tiles=tiles, w=w):
                    tw, th_ = 240, 300
                    gap = (w - len(tiles) * tw) / (len(tiles) + 1)
                    for i, (kind, ic) in enumerate(tiles):
                        tx = x + SCROLL_END_W + gap + i * (tw + gap)
                        ty = y + SCROLL_KNOB + 90
                        B.put(sk(kind, tw, th_), tx, ty)
                        B.put(_icon(ic, 120), tx + (tw - 120) / 2, ty + 40)
                        B.text(tx + tw / 2, ty + 210, ("符剑", "不夜城", "霜铃")[i], brush(46), I, "mm")
                add(im, deco)
        elif name == "scroll_end":
            add(images[name])
        elif name == "arrow_marker":
            row = Image.new("RGBA", (3 * 150, 150))
            add(row, lambda B, x, y, im: [(
                B.put(_tint(images[name], tc), x + 75 + i * 150, y + 75, angle=ang, center=True),
                B.put(_icon(ic, 60), x + 75 + i * 150, y + 75, center=True))
                for i, (ang, tc, ic) in enumerate(((0, S.ACCENT["zhusha"], "seal"), (135, "#f2b544", "lamp"), (250, S.SOUL_LIGHT, "bell")))])
        elif name == "focus_ring":
            def deco1(B, x, y, im):
                B.put(sk("btn", 300, 92), x + 16, y + 16)
                B.text(x + 166, y + 62, "设置", brush(48), P, "mm")
                B.put(sk(name, 332, 124), x, y)
            add(Image.new("RGBA", (332, 124)), deco1)

            def deco2(B, x, y, im):
                B.put(images["slot_l"], x + 16, y + 16)
                B.put(_icon("sword", 100), x + 30, y + 30)
                B.put(sk(name, 160, 160), x, y)
            add(Image.new("RGBA", (160, 160)), deco2)
        elif name == "menu_hl":
            for w in (360, 600):
                add(sk(name, w, 80), centered("开始夜行", brush(52), t))
        else:
            add(sk(name, images[name].width, images[name].height))
        return out

    # 排版：每件一行（名字 + 夜色底一份 + 纸色底一份），太宽的换成上下两段
    W_ = 2800
    pad, gap = 24, 28
    rows = []
    for name in sp:
        items = demo(name)
        iw = sum(im.width for im, _ in items) + gap * (len(items) - 1)
        ih = max(im.height for im, _ in items)
        rows.append((name, items, iw, ih))
    y = 130
    layout = []
    for name, items, iw, ih in rows:
        side = iw + 2 * pad
        stacked = 2 * side > W_ - 2 * pad
        layout.append((name, items, iw, ih, y, stacked))
        y += (ih + 2 * pad) * (2 if stacked else 1) + 64
    B = Board(W_, y + 20, "#3a3a3e")
    B.text(pad, 18, "ui_skin · 每件按 nine_slice 画 2–3 种尺寸，贴图像素 1:1（相当于 4K）；左 / 上为夜色 #161B2C，右 / 下为宣纸", serif(30), "#e8e8e8")
    for name, items, iw, ih, y0, stacked in layout:
        img0 = images[name]
        _, slc, center, sides, txt, note, extra = sp[name]
        B.text(pad, y0 - 44, f"{name}  {img0.width}×{img0.height}  slice {slc}  {center}/{sides}  text {txt}" + ("  tint" if extra.get("tint") else ""),
               serif(26), "#f0f0f0")
        B.text(pad + 1180, y0 - 44, note, serif(24), "#bdbdbd")
        side = iw + 2 * pad
        for j, bg in enumerate((NIGHT_HEX, P)):
            bx = pad if stacked else pad + j * (side + pad)
            by = y0 + (j * (ih + 2 * pad) if stacked else 0)
            B.fill((bx, by, bx + side, by + ih + 2 * pad), bg)
            x = bx + pad
            for im, deco in items:
                yy = by + pad + (ih - im.height) // 2
                B.put(im, x, yy)
                if deco is not None:
                    deco(B, x, yy, im)
                x += im.width + gap
    path.parent.mkdir(parents=True, exist_ok=True)
    B.im.convert("RGB").save(path, optimize=True)
    mock_sheet(images, sp, path.with_name("ui_skin_mock.png"))


def mock_sheet(images: dict, sp: dict, path: Path) -> None:
    """按 1080p 逻辑像素拼的四个界面（max_corner_scale 0.5、平铺 0.5，与游戏里一致），2×2 排成一张。"""
    sk = Skin(images, sp, 0.5)
    brush, serif = (lambda z: _font("brush", z)), (lambda z: _font("serif", z))
    P, I, G = S.PAPER, S.INK["jiao"], "#ffd98a"
    Wm, Hm = 1920, 1080
    scene_path = V.OUT / "review@2x" / "night_scene.png"
    scene = Image.open(scene_path).convert("RGBA") if scene_path.exists() else Image.new("RGBA", (2000, 1120), NIGHT_HEX)
    scene = scene.resize((Wm, int(round(scene.height * Wm / scene.width))), Image.LANCZOS).crop((0, 0, Wm, Hm))

    def screen() -> Board:
        B = Board(Wm, Hm, NIGHT_HEX)
        B.put(scene, 0, 0)
        return B

    # ---- 1. HUD
    H1 = screen()
    _bar(H1, sk, 0, 0, Wm, 12, "bar_fill_xp", 0.62)
    H1.put(sk("panel_dark", 340, 176), 16, 22)
    H1.text(36, 36, "提灯人", serif(20), P)
    H1.text(124, 38, "Lv 12", serif(16), S.INK["qing"])
    _bar(H1, sk, 34, 62, 300, 24, "bar_fill_hp", 0.7, 0.4)
    icons = ["lamp", "sword", "bell", "crane", "seal"]
    for i in range(6):
        nm = "slot_l_evo" if i == 1 else ("slot_l_empty" if i == 5 else "slot_l")
        x = 30 + i * 52
        H1.put(sk.fixed(nm, 0.75), x, 96)
        if i < 5:
            H1.put(_icon(icons[i] + ("_evo" if i == 1 else ""), 38), x + 5, 101)
    pas = ["changming", "jianyi", "jingxin", "zhezhi"]
    for i in range(6):
        nm = "slot_s_empty" if i >= 4 else "slot_s"
        x = 30 + i * 36
        H1.put(sk.fixed(nm, 0.8), x, 150)
        if i < 4:
            H1.put(_icon(pas[i], 26), x + 3, 153)
    H1.put(sk("panel_dark", 150, 56), Wm / 2 - 75, 20)
    H1.text(Wm / 2, 48, "12:34", serif(32), P, "mm")
    for i, (el, n) in enumerate((("金", 1), ("木", 0), ("水", 2), ("火", 3), ("土", 1))):
        x = Wm / 2 - 150 + i * 62
        H1.put(sk("chip_dark", 56), x, 84)
        H1.text(x + 28, 96, f"{el} {n}", serif(15), P if n else S.INK["dan"], "mm")
    H1.put(sk("chip_dark", 150), Wm - 250, 22)
    H1.text(Wm - 175, 34, "击杀 1234", serif(16), P, "mm")
    H1.put(sk("btn", 70, 44), Wm - 90, 14)
    H1.text(Wm - 55, 36, "停", brush(26), P, "mm")
    H1.text(Wm - 40, 96, "连斩 ×42", serif(28), G, "rm")
    H1.put(sk("toast", 260), Wm / 2 - 130, 160)
    H1.text(Wm / 2, 178, "获得 霜铃", serif(20), P, "mm")
    H1.put(sk("toast_big", 360), Wm / 2 - 180, 210)
    H1.text(Wm / 2, 230, "进化  万剑归宗", brush(32), P, "mm")
    H1.put(sk("chip_dark", 170), 30, 196)
    H1.text(115, 208, "增益 · 灯油 ×2", serif(15), G, "mm")
    H1.text(Wm / 2, Hm - 70, "九 尾 · 夜 主", serif(22), "#ffb4a8", "mm")
    _bar(H1, sk, Wm / 2 - 300, Hm - 56, 600, 24, "bar_fill_boss", 0.66)
    ar = _tint(sk.fixed("arrow_marker"), S.ACCENT["zhusha"])
    H1.put(ar, Wm - 60, 560, angle=-10, center=True)
    H1.put(_icon("seal", 30), Wm - 60, 560, center=True)

    # ---- 2. 升级
    H2 = screen()
    H2.put(sk("overlay_vignette", Wm, Hm), 0, 0)
    H2.text(Wm / 2, 150, "择一而行", brush(64), P, "mm")
    H2.text(Wm / 2, 205, "第 12 级 · 选一样带走", serif(20), S.INK["qing"], "mm")
    cw, ch = 280, 420
    kinds = (("card_fan", "凡", "jixing", "疾行", ["移动速度 +8%"], "当前 2 级", False),
             ("card_ling", "灵", "bell", "霜铃", ["铃声冻住近身的", "妖物 0.6 秒"], "下一级：冻结 +0.2 秒", False),
             ("card_xuan", "玄", "crane", "纸鹤", ["纸鹤绕身飞行", "撞到妖物即爆开"], "新法器", False),
             ("card_tian", "天", "sword_evo", "万剑归宗", ["符剑化作剑阵", "环身齐发"], "进化：符剑 + 剑意", True))
    x0 = Wm / 2 - (4 * cw + 3 * 28) / 2
    for i, (kind, rar, ic, nm, desc, note, hi) in enumerate(kinds):
        _card(H2, sk, kind, x0 + i * (cw + 28), 260 - (6 if i == 1 else 0), cw, ch, icon=ic, name=nm, desc=desc, note=note, hi=hi,
              rarity=rar, focus=(i == 1))
    for i, (el, n) in enumerate((("金", 1), ("木", 0), ("水", 2), ("火", 3), ("土", 1))):
        x = Wm / 2 - 300 + i * 62
        H2.put(sk("chip_dark", 56), x, 730)
        H2.text(x + 28, 742, f"{el} {n}", serif(15), P if n else S.INK["dan"], "mm")
    H2.put(sk("btn", 170, 52), Wm / 2 + 30, 718)
    H2.text(Wm / 2 + 115, 744, "重抽 2", brush(28), P, "mm")
    H2.put(sk("btn_disabled", 150, 52), Wm / 2 + 214, 718)
    H2.text(Wm / 2 + 289, 744, "跳过", brush(28), sp["btn_disabled"][4], "mm")

    # ---- 3. 标题菜单 / 暂停 / 心灯
    H3 = screen()
    H3.put(sk("overlay_vignette", Wm, Hm), 0, 0)
    H3.text(240, 170, "提灯夜行", brush(96), P, "mm")
    for i, t in enumerate(("开始夜行", "心灯", "设置", "离开")):
        y = 300 + i * 70
        if i == 0:
            H3.put(sk("menu_hl", 300, 40), 90, y - 20)
        H3.text(240, y, t, brush(36), G if i == 0 else P, "mm")
    px, py, pw, ph = 520, 110, 620, 560
    H3.put(sk("panel", pw, ph), px, py)
    H3.text(px + 44, py + 40, "暂停", brush(56), I)
    H3.put(sk("divider", pw - 88), px + 44, py + 112)
    for j, (lab, val) in enumerate((("时间", "12:34"), ("击杀", "1234"), ("等级", "12"), ("灯油", "86"), ("连斩", "42"), ("伤害", "38k"))):
        bx, by = px + 44 + (j % 3) * 180, py + 140 + (j // 3) * 76
        H3.put(sk("panel_dark", 168, 64), bx, by)
        H3.text(bx + 16, by + 10, lab, serif(13), S.INK["qing"])
        H3.text(bx + 16, by + 28, val, serif(24), P)
    for i, ic in enumerate(("lamp", "sword_evo", "bell", "crane", "seal")):
        bx = px + 44 + i * 70
        H3.put(sk.fixed("slot_l_evo" if i == 1 else "slot_l"), bx, py + 310)
        H3.put(_icon(ic, 50), bx + 7, py + 317)
    H3.put(sk("btn_primary_focus", 220, 56), px + 44, py + ph - 110)
    H3.text(px + 154, py + ph - 82, "继续", brush(32), "#f6efe0", "mm")
    H3.put(sk("btn", 200, 56), px + 290, py + ph - 110)
    H3.text(px + 390, py + ph - 82, "放弃", brush(32), P, "mm")
    H3.put(sk("focus_ring", 236, 72), px + 36, py + ph - 118)
    # 心灯：两张夜墨卡 + 进度点
    for i, (nm, lv, desc) in enumerate((("长明", 3, "开局灯火范围 +10%"), ("厚土", 5, "最大生命 +20"))):
        cx, cy = 1220 + i * 330, 160
        H3.put(sk("panel_dark", 310, 230), cx, cy)
        H3.put(_icon("changming" if i == 0 else "houde", 56), cx + 18, cy + 18)
        H3.text(cx + 88, cy + 32, nm, serif(26), P)
        for k in range(5):
            H3.put(sk.fixed("pip_on" if k < lv else "pip"), cx + 88 + k * 24, cy + 66)
        H3.text(cx + 18, cy + 100, desc, serif(17), "#d8d2c2")
        if lv < 5:
            H3.put(sk("btn_primary", 150, 46), cx + 18, cy + 160)
            H3.text(cx + 93, cy + 183, "点灯 · 40", serif(18), "#f6efe0", "mm")
        else:
            H3.put(sk("pill_on", 90, 32), cx + 18, cy + 166)
            H3.text(cx + 63, cy + 182, "圆满", serif(16), "#f6efe0", "mm")
    H3.put(sk("pill", 100, 32), 1220, 420)
    H3.text(1270, 436, "音效 关", serif(15), P, "mm")
    H3.put(sk("pill_on", 100, 32), 1330, 420)
    H3.text(1380, 436, "震屏 开", serif(15), "#f6efe0", "mm")

    # ---- 4. 宝箱卷轴 / 夜签 / 结算解锁条
    H4 = screen()
    H4.put(sk("overlay_vignette", Wm, Hm), 0, 0)
    end = sk.fixed("scroll_end")
    sw = 900
    sx, sy = Wm / 2 - sw / 2, 90
    H4.put(sk("scroll_body", sw, SCROLL_H / 2), sx, sy + SCROLL_KNOB / 2)
    H4.put(end, sx - end.width, sy)
    H4.put(end.transpose(Image.FLIP_LEFT_RIGHT), sx + sw, sy)
    for i, (kind, ic, nm) in enumerate((("card_ling", "sword", "符剑"), ("card_tian", "lamp_evo", "不夜城"), ("card_xuan", "bell", "霜铃"),
                                        ("card_fan", "jixing", "疾行"), ("card_ling", "zhezhi", "折纸"))):
        tx, ty = sx + 30 + i * 172, sy + SCROLL_KNOB / 2 + 50
        H4.put(sk(kind, 150, 150), tx, ty)
        H4.put(_icon(ic, 64), tx + 43, ty + 22)
        H4.text(tx + 75, ty + 112, nm, brush(26), I, "mm")
    for i, (nm, good, bad) in enumerate((("月晦", "灯油 +40%", "妖物 +25%"), ("风起", "移动 +10%", "灯光 -15%"), ("无事", "平安一夜", ""))):
        ox, oy = Wm / 2 - 390 + i * 270, 470
        H4.put(sk("card_omen", 240, 320), ox, oy)
        H4.text(ox + 120, oy + 110, nm, brush(64), S.ACCENT["zhusha"], "mm")
        H4.text(ox + 120, oy + 200, good, serif(19), "#2f6b55", "mm")
        if bad:
            H4.text(ox + 120, oy + 232, bad, serif(19), "#9a3324", "mm")
        if i == 0:
            H4.put(sk("card_focus", 240, 320), ox, oy)
    H4.text(Wm / 2 - 300, 830, "下一盏解锁：寒山钟", serif(20), P)
    _bar(H4, sk, Wm / 2 - 300, 860, 600, 16, "bar_fill_unlock", 0.42)
    H4.text(Wm / 2 + 300, 830, "42 / 100", serif(20), "#8ff0e0", "ra")

    out = Image.new("RGB", (Wm * 2 + 20, Hm * 2 + 20), "#3a3a3e")
    for i, Bd in enumerate((H1, H2, H3, H4)):
        out.paste(Bd.im.convert("RGB"), ((i % 2) * (Wm + 20), (i // 2) * (Hm + 20)))
    out.save(path, optimize=True)


def main() -> dict:
    t0 = time.perf_counter()
    images = {}
    times = {}
    for name, spec in specs().items():
        t = time.perf_counter()
        images[name] = spec[0]()
        times[name] = time.perf_counter() - t
    SKIN_DIR.mkdir(parents=True, exist_ok=True)
    for p in SKIN_DIR.glob("*.png"):
        if p.stem not in images:
            p.unlink()
    sizes = {}
    for name, img in images.items():
        path = SKIN_DIR / f"{name}.png"
        V.save_png(img, path)
        sizes[name] = path.stat().st_size
    (SKIN_DIR / "skin.json").write_text(dump_manifest(manifest(images)), encoding="utf-8")
    t1 = time.perf_counter()
    review_sheet(images, REVIEW_PATH)
    total = sum(sizes.values())
    print(f"写出 {len(images)} 张，共 {total / 1024:.0f} KB；生成 {t1 - t0:.1f} s，合计 {time.perf_counter() - t0:.1f} s")
    for k in images:
        print(f"  {k:22s} {images[k].width:4d}×{images[k].height:<4d} {sizes[k] / 1024:7.1f} KB  {times[k]:5.2f} s")
    return sizes


if __name__ == "__main__":
    main()
