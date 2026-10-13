#!/usr/bin/env python3
"""提灯夜行 · 法器、法术特效与拾取物贴图（只用 Pillow + numpy）。

笔刷、噪声、直通 alpha 输出、透明区扩色等工具全部复用 vfx_textures.py（只 import，不改它，也不碰它的产物）。
颜色全部取自 art/style/style.py。所有随机数都用固定种子，重复运行结果逐字节相同，全程约 20 秒（生成约 12 秒，其余是两张检查图）。

约定：
  - PNG 为直通（非预乘）alpha，颜色已向透明区扩展，缩放时不出黑边。
  - “可染色”贴图 RGB 恒为 255，只有 alpha 有形状，游戏里 tint 后叠加混合（blend=add）。
  - 有方向的精灵（剑、剑尾光、纸鹤）旋转角为 0 时指向 +X（屏幕右）。
  - 1 倍密度下 1 个贴图像素 = 0.5 世界单位（style.PX_PER_UNIT = 2·DENSITY）。
  - 出图密度由环境变量 LANTERN_ART_DENSITY（1 或 2）决定：尺寸、线宽、噪声尺度都按密度缩放，
    2 倍是同一张画画得更细（随机序列与 1 倍相同，见 vfx_textures.noise1），不是放大 1 倍图。1 倍结果与改造前逐字节相同。

输出：
  art/out/<A>/weapons/      sword sword_evo sword_trail crane_0..3 crane_evo_0..3 ring ring_ink seal seal_evo
                            seal_mark crack warn taiji blast shield chest soulbell lotus foxfire_0..2
                            + M2.5：sector sector_fill（扇形预警）charge_line charge_line_head（冲锋预警）+ meta.json
                            （<A> = style.ASSETS_DIR_NAME：assets / assets@2x）
  art/out/review/（2 倍：review@2x/）  weapons_sheet.png（纸色底 / 夜色底）  weapons_ingame.png（游戏比例的模拟场景）

用法（在仓库根目录下）：
  art/.venv/bin/python art/post/weapon_textures.py
  art/.venv/bin/python art/post/test_weapon_textures.py
"""

from __future__ import annotations

import math
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import vfx_textures as V  # noqa: E402  只复用工具函数，不会触发它的 main()

S = V.S
ART = V.ART
OUT = V.OUT
D = V.D
WEAPON_DIR = V.ASSETS / "weapons"
REVIEW_DIR = V.REVIEW_DIR

col = V.col
smoothstep = V.smoothstep
noise = V.noise
rank01 = V.rank01
fft_blur = V.fft_blur

# ============================================================== 颜色

WHITE = V.WHITE
PAPER = col(S.PAPER)
PAPER_SH = col(S.PAPER_SHADOW)
JIAO, NONG, ZHONG, DAN, QING = (col(S.INK[k]) for k in ("jiao", "nong", "zhong", "dan", "qing"))
ZHUSHA, ZHESHI, HUAQING, SHILV, TENG = (col(S.ACCENT[k]) for k in ("zhusha", "zheshi", "huaqing", "shilv", "tenghuang"))
W_ZHUSHA, W_ZHESHI, W_HUAQING, W_SHILV, W_TENG = (col(S.WASH[k]) for k in ("zhusha", "zheshi", "huaqing", "shilv", "tenghuang"))


def mixc(a, b, t):
    """颜色数组插值（t 可以是标量或与画布同形的数组）。"""
    a, b = np.asarray(a, dtype=np.float64), np.asarray(b, dtype=np.float64)
    t = np.asarray(t, dtype=np.float64)
    if t.ndim:
        t = t[..., None]
    return a + (b - a) * t


GOLD_DK = mixc(TENG, JIAO, 0.42)  # 金饰的描边/暗部
GOLD_HI = mixc(TENG, WHITE, 0.45)  # 金饰的高光
ZHUSHA_DK = mixc(ZHUSHA, JIAO, 0.35)

# ============================================================== 几何工具


def pnoise1(rng, n: int = 256, sigma: float = 6.0) -> np.ndarray:
    """一维周期平滑噪声，标准差归一为 1（沿轮廓、沿圆周的线宽变化用）。"""
    a = fft_blur(rng.standard_normal((1, n)), (sigma, 0.0), wrap=True)[0]
    return (a - a.mean()) / (a.std() + 1e-12)


def sample1(arr: np.ndarray, t) -> np.ndarray:
    """按周期参数 t∈[0,1) 线性采样一维数组。"""
    n = len(arr)
    return np.interp(np.mod(t, 1.0) * n, np.arange(n + 1), np.append(arr, arr[0]))


def ptex(rng, ns: int = 24, nt: int = 512, along: float = 10.0, across: float = 0.8) -> np.ndarray:
    """周期的笔毛纹理（沿 t 方向拉长），按名次归一到 0..1。圆环类笔触用它，接缝处不断。"""
    return rank01(noise(rng, (ns, nt), (along, across)))


def sample_ptex(tex: np.ndarray, s, t) -> np.ndarray:
    """双线性采样笔毛纹理：s∈[-1,1] 横跨笔触（夹紧），t 沿笔触（周期）。"""
    ns, nt = tex.shape
    fs = np.clip((np.asarray(s) + 1.0) * 0.5 * (ns - 1), 0, ns - 1)
    ft = np.mod(t, 1.0) * nt
    i0 = np.floor(fs).astype(int)
    i1 = np.minimum(i0 + 1, ns - 1)
    ws = fs - i0
    j0f = np.floor(ft)
    j0 = j0f.astype(int) % nt
    j1 = (j0 + 1) % nt
    wt = ft - j0f
    return (tex[i0, j0] * (1 - ws) + tex[i1, j0] * ws) * (1 - wt) + (tex[i0, j1] * (1 - ws) + tex[i1, j1] * ws) * wt


def resample_closed(P, spacing: float) -> np.ndarray:
    P = np.asarray(P, dtype=np.float64)
    Q = np.vstack([P, P[:1]])
    seg = np.hypot(*np.diff(Q, axis=0).T)
    s = np.concatenate([[0.0], np.cumsum(seg)])
    n = max(int(s[-1] / spacing), 8)
    u = np.linspace(0.0, s[-1], n, endpoint=False)
    return np.stack([np.interp(u, s, Q[:, 0]), np.interp(u, s, Q[:, 1])], -1)


def wobble(P, rng, amp: float, spacing: float = 0.4, sigma_px: float = 2.5) -> np.ndarray:
    """沿法线方向给闭合多边形加平滑抖动：手绘的轮廓，不是矢量直线。"""
    Q = resample_closed(P, spacing)
    n = len(Q)
    w = fft_blur(rng.standard_normal((1, n)), (sigma_px / spacing, 0.0), wrap=True)[0]
    w = w / (w.std() + 1e-12)
    tan = np.roll(Q, -1, 0) - np.roll(Q, 1, 0)
    tan /= np.linalg.norm(tan, axis=1, keepdims=True) + 1e-12
    nrm = np.stack([tan[:, 1], -tan[:, 0]], -1)
    return Q + nrm * (amp * w)[:, None]


def catmull_closed(pts, n_per: int = 10) -> np.ndarray:
    """闭合 Catmull-Rom 样条，穿过所有控制点（圆润的有机外形）。"""
    P = np.asarray(pts, dtype=np.float64)
    m = len(P)
    s = np.linspace(0.0, 1.0, n_per, endpoint=False)[:, None]
    out = []
    for i in range(m):
        p0, p1, p2, p3 = P[(i - 1) % m], P[i], P[(i + 1) % m], P[(i + 2) % m]
        out.append(0.5 * (2 * p1 + (-p0 + p2) * s + (2 * p0 - 5 * p1 + 4 * p2 - p3) * s**2 + (-p0 + 3 * p1 - 3 * p2 + p3) * s**3))
    return np.vstack(out)


def ellipse_pts(cx, cy, rx, ry, n: int = 64, a0: float = 0.0) -> np.ndarray:
    th = np.linspace(0.0, 2 * math.pi, n, endpoint=False) + a0
    return np.stack([cx + rx * np.cos(th), cy + ry * np.sin(th)], -1)


def seg_pts(*pts, n: int = 48) -> np.ndarray:
    """折线（按弧长均匀重采样）。"""
    return V.arc_resample(np.asarray(pts, dtype=np.float64), n)


def almond(base, tip, width: float, n: int = 40, bulge: float = 0.45, asym: float = 0.0) -> np.ndarray:
    """花瓣/叶片：从 base 到 tip 的杏仁形，两端尖，最宽处在 bulge。"""
    b, t = np.asarray(base, dtype=np.float64), np.asarray(tip, dtype=np.float64)
    ax = t - b
    L = float(np.hypot(*ax))
    u = ax / L
    nv = np.array([-u[1], u[0]])
    s = np.linspace(0.0, 1.0, n)
    p = math.log(0.5) / math.log(bulge)
    prof = 0.5 * width * np.sin(np.pi * s**p) ** 0.85
    left = b + s[:, None] * ax + nv * (prof * (1 + asym))[:, None]
    right = b + s[:, None] * ax - nv * (prof * (1 - asym))[:, None]
    return np.vstack([left, right[::-1][1:-1]])


def ribbon(center: np.ndarray, hw: np.ndarray) -> np.ndarray:
    """沿中线的带子（符纸尾、绳子）：左边正走、右边倒回，得到闭合多边形。"""
    tan = np.gradient(center, axis=0)
    tan /= np.linalg.norm(tan, axis=1, keepdims=True) + 1e-12
    nrm = np.stack([-tan[:, 1], tan[:, 0]], -1)
    return np.vstack([center + nrm * hw[:, None], (center - nrm * hw[:, None])[::-1]])


def box_faces(x0, y0, w, h, dx, dy):
    """3/4 视角的方块：正面、顶面、右侧面，以及整体外轮廓。y0 是正面上沿。"""
    front = [(x0, y0), (x0 + w, y0), (x0 + w, y0 + h), (x0, y0 + h)]
    top = [(x0, y0), (x0 + dx, y0 - dy), (x0 + w + dx, y0 - dy), (x0 + w, y0)]
    side = [(x0 + w, y0), (x0 + w + dx, y0 - dy), (x0 + w + dx, y0 + h - dy), (x0 + w, y0 + h)]
    sil = [(x0, y0 + h), (x0, y0), (x0 + dx, y0 - dy), (x0 + w + dx, y0 - dy), (x0 + w + dx, y0 + h - dy), (x0 + w, y0 + h)]
    return front, top, side, sil


def poly_sdf(X, Y, poly, pad: float = 3.0):
    """闭合多边形的有向距离（内负外正，单位最终像素）与最近点的周长参数 t∈[0,1)。
    只在多边形包围盒外扩 pad 的范围内计算，盒外 d 记为很大的正数。"""
    P = np.asarray(poly, dtype=np.float64)
    d_out = np.full(X.shape, 1e3)
    t_out = np.zeros(X.shape)
    xs, ys = X[0], Y[:, 0]
    cx = np.nonzero((xs >= P[:, 0].min() - pad) & (xs <= P[:, 0].max() + pad))[0]
    cy = np.nonzero((ys >= P[:, 1].min() - pad) & (ys <= P[:, 1].max() + pad))[0]
    if len(cx) == 0 or len(cy) == 0:
        return d_out, t_out
    sl = (slice(cy[0], cy[-1] + 1), slice(cx[0], cx[-1] + 1))
    x, y = X[sl], Y[sl]
    A = P
    B = np.roll(P, -1, axis=0)
    seglen = np.hypot(*(B - A).T)
    cum = np.concatenate([[0.0], np.cumsum(seglen)])[:-1]
    perim = max(float(seglen.sum()), 1e-9)
    d2 = np.full(x.shape, np.inf)
    tp = np.zeros(x.shape)
    inside = np.zeros(x.shape, dtype=bool)
    for i in range(len(P)):
        ax, ay = A[i]
        bx, by = B[i]
        ex, ey = bx - ax, by - ay
        L2 = ex * ex + ey * ey
        if L2 < 1e-12:
            continue
        wx, wy = x - ax, y - ay
        h = np.clip((wx * ex + wy * ey) / L2, 0.0, 1.0)
        dx, dy = wx - ex * h, wy - ey * h
        dd = dx * dx + dy * dy
        sel = dd < d2
        d2 = np.where(sel, dd, d2)
        tp = np.where(sel, (cum[i] + h * seglen[i]) / perim, tp)
        if (ay > y.min() or by > y.min()) and (ay <= y.max() or by <= y.max()):
            cond = ((ay > y) != (by > y)) & (x < ex * (y - ay) / (ey if abs(ey) > 1e-12 else 1e-12) + ax)
            inside ^= cond
    d = np.sqrt(d2)
    d_out[sl] = np.where(inside, -d, d)
    t_out[sl] = tp
    return d_out, t_out


def polyline_dist(X, Y, pts) -> np.ndarray:
    """到折线（开放）的距离。"""
    P = np.asarray(pts, dtype=np.float64)
    d2 = np.full(X.shape, np.inf)
    for i in range(len(P) - 1):
        ax, ay = P[i]
        ex, ey = P[i + 1] - P[i]
        L2 = max(ex * ex + ey * ey, 1e-12)
        h = np.clip(((X - ax) * ex + (Y - ay) * ey) / L2, 0.0, 1.0)
        d2 = np.minimum(d2, (X - ax - ex * h) ** 2 + (Y - ay - ey * h) ** 2)
    return np.sqrt(d2)


def brush_profile(n: int, head: float = 0.8, tail: float = 0.3, belly: float = 0.15) -> np.ndarray:
    """一笔的粗细：起笔略收、中段饱满、收笔变细。"""
    tt = np.linspace(0.0, 1.0, n)
    prof = (1.0 - belly) + belly * np.sin(np.pi * tt)
    return prof * np.interp(tt, [0.0, 0.12, 0.8, 1.0], [head, 1.0, 1.0, tail])


# ============================================================== 画布


class Painter:
    """在 ss 倍超采样网格上按“最终像素”坐标作画：填色、描边、笔触，预乘 alpha 叠加，最后缩小输出。"""

    def __init__(self, w: int, h: int, seed: int, ss: int = 8):
        self.w, self.h, self.ss = w, h, ss
        self.X, self.Y = V.grid1(h, w, ss)
        self.lay = V.Layer(*self.X.shape)
        self.rng = np.random.default_rng(seed)
        self.aa = 0.6 / (ss * D)  # 抗锯齿宽度按“最终像素”算，坐标是 1 倍像素

    # ---- 形状
    def sdf(self, poly, pad: float = 3.0):
        return poly_sdf(self.X, self.Y, poly, pad)

    def cover(self, d) -> np.ndarray:
        return smoothstep(self.aa, -self.aa, d)

    # ---- 填色
    def fill(self, d, rgb, alpha=1.0, *, pool: float = 0.0, pool_rgb=None, pool_w: float = 0.8, mottle: float = 0.0, mottle_rgb=None, mottle_sigma: float = 1.6, clip=None):
        """淡彩填色：mottle 是颜料不匀的斑驳，pool 是颜料干在边缘积成的一圈深色。"""
        c = self.cover(d)
        rgb = np.broadcast_to(np.asarray(rgb, dtype=np.float64), self.X.shape + (3,)).copy()
        if mottle:
            m = V.noise1(self.rng, self.X.shape, mottle_sigma * self.ss)
            m2 = V.noise1(self.rng, self.X.shape, 0.5 * self.ss)
            k = np.clip(mottle * (0.5 + 0.35 * m + 0.15 * m2), 0, 1)
            rgb = mixc(rgb, JIAO if mottle_rgb is None else mottle_rgb, k)
        if pool:
            k = pool * np.exp(np.minimum(d, 0.0) / pool_w) * (d < 0.5)
            rgb = mixc(rgb, JIAO if pool_rgb is None else pool_rgb, np.clip(k, 0, 1))
        a = c * alpha
        if clip is not None:
            a = a * clip
        self.lay.over(rgb, a)
        return c

    # ---- 描边
    def outline(self, d, t, width: float, rgb=JIAO, *, center: float | None = None, jitter: float = 0.22, dry: float = 0.0, alpha=1.0, clip=None):
        """沿 sdf 等值线的墨线：线宽沿周长有提按，dry>0 时带飞白。center 是线中心所在的 d 值（默认略向内收）。"""
        if center is None:
            center = -0.15 * width
        n = sample1(pnoise1(self.rng, 256, 5.0), t)
        w = width * np.clip(1.0 + jitter * n, 0.45, 1.8)
        dd = d - center
        cov = smoothstep(0.5 * w + self.aa, 0.5 * w - self.aa, np.abs(dd))
        if dry > 0:
            tex = ptex(self.rng, ns=12, nt=256, along=6.0, across=0.7)
            b = sample_ptex(tex, np.clip(dd / (0.5 * w), -1, 1), t)
            dk = dry * smoothstep(-0.4, 1.2, sample1(pnoise1(self.rng, 256, 12.0), t))
            cov = cov * smoothstep(dk - 0.07, dk + 0.07, b)
        a = cov * alpha
        if clip is not None:
            a = a * clip
        self.lay.over(rgb, a)
        return cov

    # ---- 笔触
    def stroke_cover(self, pts, halfw, *, dry: float = 0.0, dry_start: float = 0.5, jitter: float = 0.12) -> np.ndarray:
        """一笔的覆盖度（与 vfx_textures.brush_stroke 同法；dry=0 时不做笔毛纹理，细线不会出现针眼）。"""
        pts = np.asarray(pts, dtype=np.float64)
        halfw = np.broadcast_to(np.asarray(halfw, dtype=np.float64), (len(pts),)).copy()
        if dry > 0:
            cov, _ = V.brush_stroke(self.X, self.Y, pts, halfw, self.rng, dry=dry, dry_start=dry_start, edge_jitter=jitter, ss=self.ss * D)
            return cov
        f = V.stroke_fields(self.X, self.Y, pts, halfw)
        hw = f["hw"]
        if jitter:
            e = sample1(pnoise1(self.rng, 256, 5.0), f["t"] * 0.999)
            hw = hw * np.clip(1.0 + jitter * e, 0.5, 1.5)
        return smoothstep(hw + self.aa, hw - self.aa, np.hypot(f["perp"], f["over"]))

    def line(self, pts, halfw, rgb=JIAO, alpha=1.0, *, clip=None, **kw) -> np.ndarray:
        cov = self.stroke_cover(pts, halfw, **kw)
        a = cov * alpha
        if clip is not None:
            a = a * clip
        self.lay.over(rgb, a)
        return cov

    def dot(self, cx, cy, r, rgb=JIAO, alpha=1.0, *, ry=None, clip=None):
        dd = np.hypot((self.X - cx) / r, (self.Y - cy) / (ry or r)) - 1.0
        a = smoothstep(self.aa / r, -self.aa / r, dd) * alpha
        if clip is not None:
            a = a * clip
        self.lay.over(rgb, a)

    # ---- 输出
    def image(self, keep_bottom: bool = False) -> Image.Image:
        """keep_bottom=True：底边一行不清零（锚点在底边的草、芦苇、竹子，根要落在底边上）。"""
        lay = self.lay.down(self.ss)
        rgb, a = lay.straight()
        a[0, :] = a[:, 0] = a[:, -1] = 0
        if not keep_bottom:
            a[-1, :] = 0
        return V.to_rgba8(rgb, a)


def white_image(a_ss: np.ndarray, ss: int, peak: float | None = None, dither_seed: int | None = None) -> Image.Image:
    """超采样的 alpha 场 → 最终尺寸的白色可染色贴图（RGB 恒为 255，边框一圈为 0）。
    peak 给出时，把缩小后可见像素的这个百分位拉到满 alpha（细环缩小后会变暗）；
    dither_seed 给出时，量化前做 ±0.5 LSB 蓝噪声抖动（大倍数放大的柔和渐变不出色带）。"""
    a = V.downsample(np.clip(a_ss, 0, None), ss)
    if peak is not None:
        a = a / np.percentile(a[a > 0.02], peak)
    a = np.clip(a, 0, 1)
    if dither_seed is not None:
        a8 = V.dither_alpha(a, np.random.default_rng(dither_seed))
        a8[a <= 0] = 0
        a8[0, :] = a8[-1, :] = a8[:, 0] = a8[:, -1] = 0
        return V.to_rgba8(WHITE, None, a8)
    a[0, :] = a[-1, :] = a[:, 0] = a[:, -1] = 0
    return V.to_rgba8(WHITE, a)


# ============================================================== 符剑


def make_sword(evo: bool) -> Image.Image:
    """符剑：细长的剑身指向 +X。淡钢色剑身 + 细墨线，藤黄剑格，浓墨剑柄，朱砂剑穗拖在左边，
    剑格前缠一道黄符纸、符尾从剑柄下飘出。evo（万剑归宗）：金边剑身、更亮，带一圈淡金色的光。
    小尺寸下墨线只给 0.6 像素左右，否则 4 像素高的剑身会被墨线吃掉一半。"""
    W, H = (52, 14) if evo else (44, 12)
    k = W / 44.0
    P = Painter(W, H, 2150 if evo else 2100)
    cy = H / 2.0

    def q(x, y):
        return (x * k, cy + y * k)

    def qa(pts):
        return np.array([q(*p) for p in pts])

    # 剑身外形：中段微收，最后约 5 单位收成剑尖
    xs = np.linspace(16.4, 42.9, 60)
    hw = np.where(xs < 37.6, 1.95 - 0.3 * (xs - 16.4) / 21.2, 1.65 * np.clip(1 - (xs - 37.6) / 5.3, 0, 1) ** 0.7)
    upper = [(x, -h) for x, h in zip(xs, hw)]
    lower = [(x, h) for x, h in zip(xs[::-1], hw[::-1])]
    blade = qa(upper + lower[1:-1])
    d_bl, t_bl = P.sdf(blade, pad=4.0)

    if evo:
        # 一圈很淡的金光（正常混合；纸上是金色的晕）
        halo = 0.38 * np.exp(-np.maximum(d_bl, 0.0) / 0.9) * smoothstep(3.0, 1.2, d_bl)
        halo *= smoothstep(16.0 * k, 19.0 * k, P.X)
        P.lay.over(mixc(TENG, WHITE, 0.6), halo)

    # ---- 剑穗（朱砂）：绳、结、散开的穗子
    cord = V.bezier([q(8.4, 0.5), q(7.2, 1.1), q(6.1, 1.8), q(5.2, 2.4)], 40)
    P.line(cord, 0.36 * k, ZHUSHA_DK)
    tuft_root = np.array(q(5.1, 2.45))
    tips = [(1.6, 3.5), (1.9, 4.6), (2.7, 2.7)] if not evo else [(1.4, 3.2), (1.6, 4.7), (2.4, 2.2), (2.7, 5.5)]
    for i, (tx, ty) in enumerate(tips):
        tip = np.array(q(tx, ty))
        mid = (tuft_root + tip) / 2 + np.array([0.0, 0.35 * k * (1 if i % 2 else -1)])
        pts = V.bezier([tuft_root, mid, tip], 40)
        P.line(pts, 0.66 * k * brush_profile(40, head=1.0, tail=0.25, belly=0.0), ZHUSHA, dry=0.3, dry_start=0.55)
    P.dot(*q(5.2, 2.4), 0.75 * k, mixc(ZHUSHA, JIAO, 0.2))
    P.dot(*q(5.0, 2.2), 0.3 * k, mixc(ZHUSHA, WHITE, 0.4), alpha=0.8)

    # ---- 剑柄（浓墨，缠绳的斜纹）
    grip = wobble(qa([(9.9, -1.15), (16.6, -1.15), (16.6, 1.15), (9.9, 1.15)]), P.rng, 0.05 * k)
    d, t = P.sdf(grip)
    stripes = 0.5 + 0.5 * np.sin(2 * math.pi * ((P.X / k) - (P.Y - cy) / k * 0.9) / 1.3)
    P.fill(d, mixc(NONG, mixc(ZHONG, DAN, 0.3), 0.7 * smoothstep(0.45, 0.85, stripes)))
    P.outline(d, t, 0.55 * k)

    # ---- 符尾：从符纸下沿飘向左下，压在剑柄上（先画，被剑格挡住根部）
    paper_rgb = mixc(W_TENG, TENG, 0.35) if not evo else mixc(TENG, WHITE, 0.2)
    tail_c = V.bezier([q(19.4, 1.6), q(17.0, 3.0), q(14.6, 2.6), q(12.0, 3.7)], 40)
    tail = ribbon(tail_c, np.linspace(0.75, 0.55, 40) * k)
    d, t = P.sdf(tail)
    P.fill(d, paper_rgb, mottle=0.1, mottle_rgb=ZHESHI)
    P.outline(d, t, 0.42 * k, mixc(ZHESHI, JIAO, 0.45))
    P.line(seg_pts(q(13.2, 3.2), q(14.6, 2.75), n=12), 0.18 * k, ZHUSHA, alpha=0.9)

    # ---- 剑首（金）
    d, t = P.sdf(ellipse_pts(*q(9.5, 0.0), 1.25 * k, 1.6 * k, 40))
    P.fill(d, mixc(TENG, GOLD_HI, smoothstep(0.5, -1.5, P.Y - cy)), pool=0.45, pool_rgb=GOLD_DK, pool_w=0.5)
    P.outline(d, t, 0.55 * k, mixc(GOLD_DK, JIAO, 0.4))

    # ---- 剑身：上半亮、下半略暗（刃面的两个斜面）
    yrel = (P.Y - cy) / k
    if evo:
        hi, lo = mixc(PAPER, WHITE, 0.85), mixc(W_TENG, WHITE, 0.6)
    else:
        hi, lo = mixc(PAPER, WHITE, 0.6), mixc(QING, PAPER, 0.4)
    P.fill(d_bl, mixc(hi, lo, smoothstep(-0.2, 0.4, yrel)))
    P.line(seg_pts(q(19.0, -1.05), q(35.5, -0.85)), 0.2 * k, WHITE, alpha=0.9)
    if evo:
        # 金边：轮廓内侧一道藤黄，外轮廓用暗金而不是焦墨，显得亮
        P.outline(d_bl, t_bl, 0.6 * k, TENG, center=-0.62 * k, jitter=0.12)
        P.outline(d_bl, t_bl, 0.6 * k, mixc(GOLD_DK, JIAO, 0.35), jitter=0.15)
    else:
        P.outline(d_bl, t_bl, 0.62 * k, mixc(JIAO, NONG, 0.3), jitter=0.18)

    # ---- 剑格（藤黄，月牙形，两端略翘），暗金描边
    gp = [(14.9, -4.0), (16.5, -3.6), (17.9, -0.45), (17.9, 0.45), (16.5, 3.6), (14.9, 4.0), (15.9, 0.0)]
    guard = catmull_closed(qa(gp), 8)
    d, t = P.sdf(guard)
    P.fill(d, mixc(TENG, GOLD_HI, smoothstep(0.5, -2.0, P.Y - cy)), pool=0.5, pool_rgb=GOLD_DK, pool_w=0.45)
    P.outline(d, t, 0.6 * k, mixc(GOLD_DK, JIAO, 0.45))

    # ---- 符纸：缠在剑格前的一道黄纸，上面一笔朱砂
    band = wobble(qa([(18.5, -2.55), (21.3, -2.45), (21.1, 2.6), (18.3, 2.5)]), P.rng, 0.05 * k)
    d, t = P.sdf(band)
    P.fill(d, paper_rgb, mottle=0.1, mottle_rgb=ZHESHI, pool=0.25, pool_rgb=ZHESHI, pool_w=0.4)
    P.line(seg_pts(q(19.9, -1.6), q(19.7, 1.6)), 0.24 * k, ZHUSHA)
    P.line(seg_pts(q(19.2, -0.5), q(20.5, -0.65)), 0.2 * k, ZHUSHA)
    P.outline(d, t, 0.45 * k, mixc(ZHESHI, JIAO, 0.5))
    return P.image()


def make_trail() -> Image.Image:
    """剑尾光：右端（锚点）粗而亮，向左收成一线，带顺笔方向的几丝飞白。白色，染色后叠加。"""
    W, H, ss = 48, 10, 8
    X, Y = V.grid1(H, W, ss)
    rng = np.random.default_rng(2200)
    x_head = 45.2
    u = np.clip(X / x_head, 0, 1)  # 0=左端尾巴，1=右端
    hw = 3.3 * u**1.35 + 0.15
    v = (Y - H / 2.0) / hw
    # 右端圆头
    head = np.hypot((X - x_head) / 2.2, (Y - H / 2.0) / 3.45)
    shape = np.where(X <= x_head, smoothstep(1.0, 0.55, np.abs(v)), smoothstep(1.0, 0.6, head))
    core = np.exp(-((v / 0.42) ** 2)) * (X <= x_head) + np.exp(-((head / 0.42) ** 2)) * (X > x_head)
    tex = V.bristle_texture(rng, ns=14, nt=256)
    b = V.sample_tex(tex, np.clip(v, -1, 1), u)
    dry = 0.75 * (1 - u) ** 1.6
    streak = smoothstep(dry - 0.12, dry + 0.12, b) * (0.7 + 0.3 * b)
    a = shape * (0.25 + 0.75 * u**1.1) * (0.55 * streak + 0.45 * core)
    a = np.clip(a + 0.35 * core * u**2, 0, 1)
    return white_image(a, ss)


# ============================================================== 纸鹤

CRANE_ELEV = (60.0, 6.0, -40.0, 18.0)  # 4 帧翼仰角（度）：上、下扑中、下、上提中
CRANE_BOB = (0.45, 0.0, -0.55, -0.15)  # 身体随扑翼的起伏（下扑时身体被抬起）
CRANE_BEND = (0.0, 1.0, 0.0, -1.0)  # 翼前缘的弯曲：下扑时翼尖滞后向上，上提时翼尖滞后向下
CRANE_PITCH = math.radians(35.0)  # 从斜上方看纸鹤：平展的翅膀也有面积，扑翼时翼面大小有变化


def crane_wing(hinge_f, hinge_b, elev_deg: float, side: int, bend: float, L: float = 11.5):
    """一侧翅膀：前后两个铰点 + 翼尖，按仰角和俯角投影到屏幕。side=+1 近侧（朝镜头），-1 远侧。"""
    ph = math.radians(elev_deg)
    sp, cp = math.sin(CRANE_PITCH), math.cos(CRANE_PITCH)
    Ls = L * (1.0 if side > 0 else 0.9)
    hf, hb = np.asarray(hinge_f, dtype=np.float64), np.asarray(hinge_b, dtype=np.float64)
    root = hb * 0.55 + hf * 0.45
    dy = Ls * (-math.sin(ph) * cp + side * math.cos(ph) * sp)
    dx = -(1.0 + 2.4 * abs(math.cos(ph)))  # 翼尖向后掠
    tip = root + np.array([dx, dy])
    lead = hf + (tip - hf) * 0.5
    ln = np.array([-(tip - hf)[1], (tip - hf)[0]])
    ln /= np.linalg.norm(ln) + 1e-9
    lead = lead + ln * bend * 0.8
    trail = hb + (tip - hb) * 0.75 - np.array([0.4, 0.0])
    return [tuple(hf), tuple(lead), tuple(tip), tuple(trail), tuple(hb)], tip, root


def make_crane(frame: int, evo: bool) -> Image.Image:
    """纸鹤：宣纸白的折纸鹤向右飞（从斜上方看），焦墨细轮廓、淡墨折痕，头上一点朱砂。4 帧扑翼循环。
    evo（千鹤引）：翼缘贴一道藤黄金箔，翼面撒两点金。"""
    W, H = 30, 26
    P = Painter(W, H, 2350 if evo else 2300)  # 各帧同一种子，轮廓抖动逐帧一致，不闪
    by = CRANE_BOB[frame] - 0.6
    elev, bend = CRANE_ELEV[frame], CRANE_BEND[frame]

    def o(x, y):
        return (x, y + by)

    body = [o(8.4, 15.0), o(15.0, 12.6), o(21.8, 14.4), o(15.6, 18.8)]
    neck = [o(18.0, 13.5), o(22.4, 15.2), o(26.1, 7.5), o(24.9, 6.5)]
    head = [o(24.5, 6.1), o(26.5, 7.0), o(28.5, 10.4)]
    tail = [o(8.4, 13.4), o(13.0, 16.6), o(4.2, 11.8), o(1.7, 8.0)]
    hf, hb = np.array(o(18.6, 13.4)), np.array(o(10.6, 13.9))
    far_poly, far_tip, far_root = crane_wing(hf + [1.0, -1.5], hb + [1.0, -1.5], elev, -1, bend)
    near_poly, near_tip, near_root = crane_wing(hf, hb, elev, +1, bend)

    paper_lit = mixc(PAPER, WHITE, 0.6)
    paper_mid = mixc(PAPER, WHITE, 0.2)
    paper_dark = mixc(PAPER_SH, QING, 0.3)
    paper_body = mixc(PAPER, PAPER_SH, 0.35)
    ol, crease = 0.6, 0.16
    line_rgb = mixc(JIAO, NONG, 0.25)

    def facet(poly, rgb, *, w=ol, gold=False):
        poly = wobble(poly, P.rng, 0.04, spacing=0.3, sigma_px=2.0)
        d, t = P.sdf(poly)
        P.fill(d, rgb, mottle=0.04, mottle_rgb=PAPER_SH, pool=0.2, pool_rgb=QING, pool_w=0.7)
        if gold:
            P.outline(d, t, 0.6, TENG, center=-0.55, jitter=0.2)
        P.outline(d, t, w, line_rgb)
        return d

    # 远侧翅膀在身体后面，背光偏暗
    facet(far_poly, paper_dark, gold=evo)
    P.line(seg_pts(far_root, far_tip, n=30), crease, DAN, alpha=0.6)
    # 尾、颈、头、身
    facet(tail, paper_mid, w=0.5)
    P.line(seg_pts(o(10.8, 15.2), o(3.0, 9.3), n=30), crease, DAN, alpha=0.5)
    facet(neck, paper_mid, w=0.5)
    P.line(seg_pts(o(20.2, 14.4), o(25.4, 7.4), n=30), crease, DAN, alpha=0.5)
    facet(head, paper_lit, w=0.5)
    facet(body, paper_body)
    P.line(seg_pts(o(9.4, 15.0), o(15.2, 15.6), o(21.0, 14.4), n=40), crease, DAN, alpha=0.6)
    # 近侧翅膀
    wing_rgb = paper_lit if elev < 30 else mixc(paper_lit, paper_mid, 0.5)
    facet(near_poly, wing_rgb, gold=evo)
    P.line(seg_pts(near_root, near_tip, n=30), crease, DAN, alpha=0.65)
    if evo:
        for f, off in ((0.42, (0.5, 0.2)), (0.66, (-0.6, 0.3))):
            px, py = near_root + (near_tip - near_root) * f + np.array(off)
            P.dot(px, py, 0.45, TENG)
    # 头上一点朱砂
    P.dot(*o(25.2, 7.3), 0.7, ZHUSHA)
    return P.image()


# ============================================================== 圆环、靶环、太极


def polar(size: int, ss: int):
    X, Y = V.grid1(size, size, ss)
    c = size / 2.0
    dx, dy = X - c, Y - c
    r = np.hypot(dx, dy)
    th = np.arctan2(dy, dx)
    return X, Y, r, np.mod(th / (2 * math.pi), 1.0)


def make_ring() -> Image.Image:
    """涟漪环：外沿清楚的一道细亮环，向内柔和淡出；沿圆周有笔毛的丝纹和几处若断若连。
    白色，染色叠加（霜铃寒波染冰蓝、冲击波、大招染金、地震染赭）。从 30 到 800 像素都能用。"""
    size, ss = 128, 4
    X, Y, r, tt = polar(size, ss)
    rng = np.random.default_rng(2400)
    R0 = 57.0
    R = R0 * (1.0 + 0.004 * sample1(pnoise1(rng, 512, 18.0), tt))
    w = 3.4 * np.clip(1.0 + 0.22 * sample1(pnoise1(rng, 512, 10.0), tt), 0.55, 1.5)
    p = r - R  # 正 = 外侧
    # 主环：外沿较硬（波前），内沿稍软
    band = smoothstep(0.9, -0.5, p) * smoothstep(-w - 1.4, -w + 0.6, p)
    # 丝纹：沿圆周拉长的笔毛纹理，横跨环带约 6 条
    tex = ptex(rng, ns=8, nt=1024, along=6.0, across=0.6)
    b = sample_ptex(tex, np.clip((p + 0.5 * w) / (0.5 * w + 0.6), -1, 1), tt)
    silk = 0.62 + 0.38 * b
    # 若断若连：几处变淡（不全断，染色后仍然是一整圈）
    gap = smoothstep(0.9, 1.9, sample1(pnoise1(rng, 512, 14.0), tt))
    band = band * silk * (1.0 - 0.55 * gap)
    # 波前上一线最亮
    crest = 0.35 * np.exp(-(((p + 0.9) / 0.9) ** 2)) * (1.0 - 0.4 * gap)
    # 向内的柔和余波 + 一道很淡的二次涟漪
    inner = 0.30 * np.exp(np.minimum(p + w, 0.0) / 9.0) * smoothstep(-w + 0.6, -w - 1.5, p)
    inner *= 0.85 + 0.15 * sample1(pnoise1(rng, 512, 30.0), tt)  # 只做大尺度起伏，不要放射状的细条
    echo = 0.14 * np.exp(-(((p + 3.4 + 6.5) / 1.6) ** 2)) * (0.75 + 0.25 * sample_ptex(tex, 0.3, tt))  # 只跟半径走，不随环宽起伏
    a = band + crest + inner + echo
    a *= smoothstep(12.0, 28.0, r)  # 中心完全透明
    a *= V.bump_window(r / 63.4) ** 0.15
    return white_image(a, ss, peak=99.0, dither_seed=2401)  # 波前最亮处满 alpha；内侧余波抖动防色带


def make_ring_ink() -> Image.Image:
    """圆相：一笔写成的墨圈（焦墨起笔、重墨行笔、收笔飞白），留一个小缺口。地面上的墨痕，正常混合。"""
    size, ss = 128, 4
    X, Y, r, _ = polar(size, ss)
    rng = np.random.default_rng(2500)
    c = size / 2.0
    th = np.mod(np.arctan2(Y - c, X - c), 2 * math.pi)
    th0 = math.radians(118.0)  # 起笔在左下
    span = math.radians(334.0)
    # 起笔前留一小段负参数，用来画圆头
    rel = np.mod(th - th0 + math.radians(10.0), 2 * math.pi) - math.radians(10.0)
    t = rel / span
    Rm = 49.0
    R = Rm - 1.6 + 3.2 * np.clip(t, 0, 1) + 0.9 * np.sin(2 * math.pi * np.clip(t, 0, 1) * 1.5 + 0.7)
    prof_t = np.linspace(0, 1, 256)
    prof = np.interp(prof_t, [0.0, 0.04, 0.12, 0.45, 0.8, 0.94, 1.0], [5.6, 6.6, 5.4, 4.6, 3.6, 1.9, 0.25])
    hw = np.interp(np.clip(t, 0, 1), prof_t, prof)
    hw = hw * (1.0 + 0.08 * np.interp(np.clip(t, 0, 1), np.linspace(0, 1, 256), pnoise1(rng, 256, 6.0)))
    perp = r - R
    over = np.maximum(-t, 0.0) * span * Rm  # 起笔圆头
    over = np.where(t > 1.0, 1e3, over)
    dist = np.hypot(perp, over)
    cover = smoothstep(hw + 0.5, hw - 0.5, dist)
    # 笔毛与飞白：越往后越干；起笔处墨饱满、边上积墨
    s = np.clip(perp / np.maximum(hw, 0.3), -1, 1)
    tex = ptex(rng, ns=30, nt=1024, along=7.0, across=0.6)
    b = sample_ptex(tex, s, np.clip(t, 0, 1) * 0.999)
    dry = 0.78 * smoothstep(0.42, 1.0, t) + 0.10 * smoothstep(0.1, 0.4, t) * (np.abs(s) > 0.55)
    ink = smoothstep(dry - 0.06, dry + 0.06, b)
    cover = cover * ink
    # 浓淡：起笔焦墨，行笔渐转重墨；笔毛之间略淡
    tone = smoothstep(0.05, 0.75, np.clip(t, 0, 1)) * 0.75 + 0.25 * (1 - b)
    rgb = mixc(JIAO, ZHONG, np.clip(tone, 0, 1) * 0.8)
    a = cover * (0.97 - 0.18 * smoothstep(0.3, 1.0, t) * (1 - b))
    # 起笔处的洇墨：外面一圈很淡的晕
    start_pt = np.array([c + (Rm - 1.6) * math.cos(th0), c + (Rm - 1.6) * math.sin(th0)])
    bleed = 0.16 * np.exp(-np.hypot(X - start_pt[0], Y - start_pt[1]) / 6.0) * smoothstep(0.2, 0.8, rank01(V.noise1(rng, X.shape, 1.2 * ss)))
    lay = V.Layer(*X.shape)
    lay.over(ZHONG, bleed * (1 - cover))
    lay.over(rgb, a)
    lay = lay.down(ss)
    rgb_s, a_s = lay.straight()
    a_s[0, :] = a_s[-1, :] = a_s[:, 0] = a_s[:, -1] = 0
    return V.to_rgba8(rgb_s, a_s)


def make_warn() -> Image.Image:
    """落印预警：一圈细的毛笔短划（12 段，每段两头尖），四个向内的短刻度和中心一点。白色，染色叠加。"""
    size, ss = 64, 8
    X, Y, r, tt = polar(size, ss)
    rng = np.random.default_rng(2600)
    R0, w = 27.0, 1.05
    n = 12
    ph = tt * n + 0.5
    frac = np.mod(ph, 1.0)
    duty = 0.68
    seg = np.floor(ph).astype(int) % n
    jit = rng.uniform(0.85, 1.15, n)
    taper = np.sin(np.pi * np.clip(frac / duty, 0, 1)) ** 0.7 * (frac < duty)
    hw = w * taper * jit[seg]
    ring = smoothstep(hw + 0.12, hw - 0.12, np.abs(r - R0)) * (hw > 0.05)
    # 四个向内的刻度
    ticks = np.zeros_like(r)
    for k in range(4):
        a0 = k * math.pi / 2
        ux, uy = math.cos(a0), math.sin(a0)
        along = (X - 32) * ux + (Y - 32) * uy
        perp = -(X - 32) * uy + (Y - 32) * ux
        t = np.clip((along - 18.5) / 5.5, 0, 1)
        thw = 0.85 * (0.35 + 0.65 * t)
        ticks = np.maximum(ticks, smoothstep(thw + 0.12, thw - 0.12, np.abs(perp)) * (along > 18.5) * (along < 24.0))
    dot = smoothstep(2.3, 1.9, r)
    fill = 0.10 * smoothstep(R0 - 0.5, R0 - 4.0, r)
    a = np.clip(np.maximum.reduce([ring, 0.85 * ticks, dot]) + fill, 0, 1)
    return white_image(a, ss)


def make_taiji() -> Image.Image:
    """水墨太极：焦墨半边带顺着圆周的飞白丝，白半边是宣纸色，外圈一笔圆相，边缘毛糙。正常混合。"""
    size, ss = 128, 4
    X, Y, r, tt = polar(size, ss)
    rng = np.random.default_rng(2700)
    c, R = size / 2.0, 52.0
    # 坐标轻微扭曲：手绘的 S 线
    wu = 0.010 * V.noise1(rng, X.shape, 6 * ss) + 0.003 * V.noise1(rng, X.shape, 1.5 * ss)
    wv = 0.010 * V.noise1(rng, X.shape, 6 * ss) + 0.003 * V.noise1(rng, X.shape, 1.5 * ss)
    u = (X - c) / R + wu
    v = (Y - c) / R + wv
    rho = np.hypot(u, v)
    Redge = 1.0 + 0.010 * sample1(pnoise1(rng, 512, 8.0), tt)
    disk = smoothstep(Redge + 0.012, Redge - 0.012, rho)
    soft = 1.2 / R

    def circ(cx, cy, rr):
        return smoothstep(rr + soft, rr - soft, np.hypot(u - cx, v - cy))

    c_top, c_bot = circ(0, -0.5, 0.5), circ(0, 0.5, 0.5)
    right = smoothstep(-soft, soft, u)
    black = np.clip(right * (1 - c_top) + c_bot * (1 - right), 0, 1)
    black = np.clip(black + circ(0, -0.5, 0.14) - circ(0, 0.5, 0.14), 0, 1)
    # 黑半边：顺着圆周扫的长笔毛丝，只在外缘偏干
    tex = ptex(rng, ns=48, nt=1024, along=36.0, across=0.5)
    b = sample_ptex(tex, np.clip(rho * 2 - 1, -1, 1), tt)
    dry = 0.30 * smoothstep(0.62, 0.99, rho)
    ink = smoothstep(dry - 0.06, dry + 0.06, b)
    blk_a = black * (0.62 + 0.38 * ink)
    blk_rgb = mixc(JIAO, NONG, 0.25 + 0.5 * (1 - ink))
    paper_rgb = mixc(PAPER, PAPER_SH, 0.3 * smoothstep(-1, 2, V.noise1(rng, X.shape, 3 * ss)))
    # 外圈一笔：比太极略大，起笔在左上，收笔飞白
    t_rim = np.mod(tt - 0.62, 1.0)
    Rr = R * (1.035 + 0.008 * np.sin(2 * math.pi * t_rim))
    hw = np.interp(t_rim, [0, 0.04, 0.5, 0.88, 1.0], [1.6, 2.6, 2.2, 1.4, 0.3])
    rim_c = smoothstep(hw + 0.5, hw - 0.5, np.abs(r - Rr))
    rb = sample_ptex(tex, np.clip((r - Rr) / np.maximum(hw, 0.3), -1, 1), t_rim)
    rim_dry = 0.65 * smoothstep(0.7, 1.0, t_rim)
    rim = rim_c * smoothstep(rim_dry - 0.06, rim_dry + 0.06, rb)
    lay = V.Layer(*X.shape)
    lay.over(paper_rgb, disk)
    lay.over(blk_rgb, disk * blk_a)
    lay.over(mixc(JIAO, NONG, 0.2), rim)
    lay = lay.down(ss)
    rgb_s, a_s = lay.straight()
    a_s[0, :] = a_s[-1, :] = a_s[:, 0] = a_s[:, -1] = 0
    return V.to_rgba8(rgb_s, a_s)


def make_blast() -> Image.Image:
    """爆炸：亮核 + 起伏的烟团边 + 几道放射的拖尾 + 零星火星。白色，染色叠加（火爆染橙、冰爆染蓝）。"""
    size, ss = 64, 4
    X, Y, r, tt = polar(size, ss)
    rng = np.random.default_rng(2800)
    rn = r / 30.0
    edge = 0.62 * (1.0 + 0.16 * sample1(pnoise1(rng, 512, 9.0), tt) + 0.06 * sample1(pnoise1(rng, 512, 3.0), tt))
    puff = smoothstep(edge + 0.08, edge - 0.18, rn)
    billow = 0.5 + 0.5 * V.noise1(rng, X.shape, 2.4 * ss)
    puff = puff * (0.45 + 0.25 * billow) * (1.0 - 0.35 * smoothstep(0.25, 0.0, rn - edge + 0.25) * (billow < 0.4))
    core = np.exp(-((rn / 0.32) ** 2))
    streaks = np.zeros_like(r)
    for i in range(9):
        a0 = 2 * math.pi * (i + rng.uniform(-0.3, 0.3)) / 9
        L0, L1 = rng.uniform(0.2, 0.35), rng.uniform(0.72, 0.95)
        ux, uy = math.cos(a0), math.sin(a0)
        along = ((X - 32) * ux + (Y - 32) * uy) / 30.0
        perp = np.abs(-(X - 32) * uy + (Y - 32) * ux)
        t = np.clip((along - L0) / (L1 - L0), 0, 1)
        hw = 1.15 * (1 - t) ** 0.9 + 0.05
        s = smoothstep(hw + 0.2, hw - 0.2, perp) * (along > L0 - 0.02) * (along < L1)
        streaks = np.maximum(streaks, s * (0.85 - 0.35 * t))
    sparks = np.zeros_like(r)
    for _ in range(7):
        a0 = rng.uniform(0, 2 * math.pi)
        d0 = rng.uniform(0.72, 0.93) * 30
        px, py = 32 + d0 * math.cos(a0), 32 + d0 * math.sin(a0)
        rr = rng.uniform(0.6, 1.1)
        sparks = np.maximum(sparks, smoothstep(rr + 0.3, rr - 0.3, np.hypot(X - px, Y - py)))
    a = np.clip(np.maximum.reduce([puff + 0.75 * core, streaks, 0.9 * sparks]), 0, 1)
    a *= V.bump_window(r / 31.5) ** 0.3
    return white_image(a, ss)


# 先天八卦（自上起顺时针），每卦三爻由内到外：1=阳爻（整），0=阴爻（断）
BAGUA = ((1, 1, 1), (1, 1, 0), (0, 1, 0), (0, 0, 1), (0, 0, 0), (1, 0, 0), (1, 0, 1), (0, 1, 1))


def make_shield() -> Image.Image:
    """护体罩：八角的细亮边 + 向边缘渐亮的淡淡罩面 + 内圈八卦爻（白色，染色叠加）。"""
    size, ss = 64, 8
    X, Y, r, tt = polar(size, ss)
    rng = np.random.default_rng(2900)
    th = tt * 2 * math.pi
    sector = math.pi / 4
    rel = np.mod(th + math.pi / 2 + sector / 2, sector) - sector / 2  # 以正上方为第 0 边的法线
    apo = r * np.cos(rel)  # 到中心的“边心距”坐标，八角形等值线
    A0 = 27.6
    rim_w = 0.8 * np.clip(1 + 0.18 * sample1(pnoise1(rng, 256, 6.0), tt), 0.6, 1.4)
    rim = smoothstep(rim_w + 0.15, rim_w - 0.15, np.abs(apo - A0))
    inner_rim = 0.35 * smoothstep(0.55, 0.25, np.abs(apo - (A0 - 2.4)))
    fill = (0.07 + 0.22 * smoothstep(A0 - 16.0, A0 - 0.5, apo) ** 2) * (apo < A0)
    bars = np.zeros_like(r)
    sidx = np.floor(np.mod(th + math.pi / 2 + sector / 2, 2 * math.pi) / sector).astype(int) % 8
    along = r * np.sin(rel)  # 沿边方向的坐标
    for line in range(3):
        a_line = 15.5 + line * 2.6  # 爻：由内到外
        half_len = a_line * math.tan(sector / 2) * 0.62
        yang = np.array([BAGUA[s][line] for s in range(8)])[sidx]
        on = smoothstep(0.62, 0.38, np.abs(apo - a_line)) * smoothstep(half_len + 0.2, half_len - 0.2, np.abs(along))
        gap = smoothstep(0.75, 1.05, np.abs(along) / (0.17 * half_len + 1e-9))
        bars = np.maximum(bars, on * np.where(yang == 1, 1.0, gap))
    a = np.clip(np.maximum.reduce([rim, inner_rim, 0.7 * bars]) + fill, 0, 1)
    a *= smoothstep(31.0, 29.5, r)
    return white_image(a, ss)


# ============================================================== 山印、镇岳


STONE = mixc(W_ZHESHI, DAN, 0.3)  # 赭石兑淡墨的石色


def stone_box(P: Painter, x0, y0, w, h, dx, dy, base_rgb, *, ol: float, inner: float, cun: int = 3, red_bottom: bool = True, edge_rgb=None):
    """3/4 视角的石块：顶面最亮、正面中间、右侧面最暗；几笔干墨皴；正面底边沾一线印泥。"""
    front, top, side, sil = box_faces(x0, y0, w, h, dx, dy)
    tones = (mixc(base_rgb, PAPER, 0.5), base_rgb, mixc(base_rgb, ZHONG, 0.5))
    masks = []
    for poly, rgb in zip((top, front, side), tones):
        poly = wobble(poly, P.rng, 0.07, spacing=0.3)
        d, _ = P.sdf(poly)
        masks.append(P.cover(d))
        P.fill(d, rgb, mottle=0.12, mottle_rgb=ZHONG, pool=0.25, pool_rgb=ZHONG, pool_w=0.8)
    # 皴笔：正面斜向的几笔干墨，长短不一
    for i in range(cun):
        xa = x0 + w * (0.12 + 0.7 * (i + P.rng.uniform(0.0, 0.4)) / cun)
        ya = y0 + h * P.rng.uniform(0.12, 0.35)
        L = h * P.rng.uniform(0.3, 0.55)
        pts = V.bezier([(xa, ya), (xa - 0.8 + P.rng.uniform(-0.4, 0.4), ya + L * 0.5), (xa - 0.4, ya + L)], 40)
        P.line(pts, 0.42 * brush_profile(40, 1.0, 0.2), mixc(DAN, ZHONG, 0.4), alpha=0.45, clip=masks[1], dry=0.55, dry_start=0.2)
    for i in range(max(cun - 1, 1)):
        fx = 0.3 + 0.4 * i / max(cun - 2, 1)
        xa, ya = x0 + w + dx * fx, y0 - dy * fx + h * P.rng.uniform(0.2, 0.35)
        pts = V.bezier([(xa, ya), (xa + 0.4, ya + h * 0.25), (xa - 0.1, ya + h * 0.5)], 40)
        P.line(pts, 0.4 * brush_profile(40, 1.0, 0.2), ZHONG, alpha=0.45, clip=masks[2], dry=0.5, dry_start=0.2)
    if red_bottom:
        P.line(seg_pts((x0 + 0.6, y0 + h - 0.6), (x0 + w - 0.3, y0 + h - 0.6), (x0 + w + dx - 0.5, y0 + h - dy - 0.6), n=60), 0.45, ZHUSHA, alpha=0.9)
    # 墨线：内部棱线用细线，整体外轮廓用粗线
    er = NONG if edge_rgb is None else edge_rgb
    P.line(seg_pts((x0, y0), (x0 + w, y0), (x0 + w + dx, y0 - dy), n=60), 0.5 * inner, er)
    P.line(seg_pts((x0 + w, y0), (x0 + w, y0 + h), n=30), 0.5 * inner, NONG)
    d, t = P.sdf(wobble(sil, P.rng, 0.06, spacing=0.3))
    P.outline(d, t, ol, jitter=0.25)
    return masks


def make_seal() -> Image.Image:
    """山印：方柱石印，3/4 俯视；龟钮（印钮是一只伏龟）。赭石淡墨的石色，焦墨轮廓，
    钮上穿一根朱砂绶带垂在侧面，底边沾一线朱砂印泥。"""
    W, H = 40, 44
    P = Painter(W, H, 3000)
    x0, w, h, dx, dy = 8.5, 16.0, 16.0, 7.0, 5.0
    y0 = 37.4 + dy / 2 - h  # 足印中心落在锚点 (0.5, 0.85)
    stone_box(P, x0, y0, w, h, dx, dy, STONE, ol=1.1, inner=0.7, cun=2)
    tx, ty = x0 + w / 2 + dx / 2, y0 - dy / 2 + 0.4  # 顶面中心
    ks = 1.22  # 龟钮的大小

    def q(x, y):
        return (tx + ks * x, ty + ks * y)

    def qa(pts):
        return np.array([q(*p) for p in pts])

    knob_lit, knob_dark = mixc(STONE, PAPER, 0.5), mixc(STONE, ZHONG, 0.35)
    ink = mixc(JIAO, NONG, 0.3)
    # 龟脚、龟头（先画，被龟壳压住）
    for fx, fy in ((-4.6, 1.0), (4.4, 1.2), (-2.4, 1.9), (2.6, 2.0)):
        d, t = P.sdf(ellipse_pts(*q(fx, fy - 0.6), 1.25 * ks, 0.85 * ks, 24))
        P.fill(d, knob_dark)
        P.outline(d, t, 0.5, ink)
    neck = catmull_closed(qa([(-4.8, -1.2), (-6.6, -2.6), (-8.6, -2.9), (-9.3, -1.6), (-8.4, -0.3), (-6.2, 0.3)]), 8)
    d, t = P.sdf(neck)
    P.fill(d, knob_lit, pool=0.3, pool_rgb=ZHONG, pool_w=0.6)
    P.outline(d, t, 0.6, ink)
    P.dot(*q(-8.0, -2.0), 0.45, JIAO)
    # 龟壳：拱起的半椭圆，壳上刻龟甲纹
    shell = catmull_closed(qa([(-6.0, 0.6), (-5.4, -3.0), (-2.0, -5.4), (2.2, -5.4), (5.6, -3.0), (6.4, 0.4), (0.2, 1.6)]), 10)
    d, t = P.sdf(wobble(shell, P.rng, 0.05, spacing=0.3))
    shade = smoothstep(ty - 6.0, ty + 1.5, P.Y) * 0.6 + 0.5 * smoothstep(tx - 3, tx + 7, P.X)
    P.fill(d, mixc(knob_lit, knob_dark, np.clip(shade, 0, 1)), mottle=0.08, mottle_rgb=ZHONG, pool=0.3, pool_rgb=ZHONG, pool_w=0.7)
    m = P.cover(d)
    hc = np.array(q(0.2, -2.6))
    hexa = ellipse_pts(hc[0], hc[1], 2.2 * ks, 1.35 * ks, 6, a0=0.0)
    P.line(V.arc_resample(np.vstack([hexa, hexa[:1]]), 60), 0.2, NONG, alpha=0.8, clip=m)
    for ax, ay in hexa:
        vx, vy = ax - hc[0], ay - hc[1]
        P.line(seg_pts((ax, ay), (ax + vx * 1.2, ay + vy * 1.6), n=12), 0.18, NONG, alpha=0.7, clip=m)
    P.line(seg_pts(q(-5.4, -0.4), q(0.2, 0.6), q(5.8, -0.4), n=40), 0.2, NONG, alpha=0.7, clip=m)
    P.outline(d, t, 0.75, ink)
    # 朱砂绶带：从龟钮穿出，垂过侧面
    P.line(V.bezier([q(4.2, -1.4), q(6.4, 0.0), (tx + 7.6, ty + 4.2), (tx + 8.2, ty + 8.0)], 50), 0.42, ZHUSHA)
    P.dot(tx + 7.6, ty + 4.0, 0.75, ZHUSHA_DK)
    P.line(V.bezier([(tx + 7.6, ty + 4.2), (tx + 6.8, ty + 6.4), (tx + 7.0, ty + 9.0)], 30), 0.5 * brush_profile(30, 1.0, 0.35, 0.0), ZHUSHA, dry=0.3, dry_start=0.6)
    return P.image()


def make_seal_evo() -> Image.Image:
    """镇岳：更大的石印，印钮是三峰的山（金碧山水：石绿花青敷色、藤黄勾金），
    印台顶边一道金线，正面一个金色篆书“山”。"""
    W, H = 56, 60
    P = Painter(W, H, 3100)
    x0, w, h, dx, dy = 11.5, 24.0, 18.0, 9.0, 6.5
    y0 = 51.0 + dy / 2 - h
    stone = mixc(W_ZHESHI, ZHONG, 0.45)
    masks = stone_box(P, x0, y0, w, h, dx, dy, stone, ol=1.3, inner=1.0, cun=4, edge_rgb=TENG)
    # 正面金色篆书“山”：暗金托底、藤黄面
    gx, gy, gs = x0 + w / 2, y0 + h / 2 + 0.4, 6.0
    for stroke in SHAN_GLYPH:
        pts = V.arc_resample(np.array([(gx + gs * x, gy + gs * y) for x, y in stroke]), 60)
        P.line(pts + [0.3, 0.3], 0.62, GOLD_DK, alpha=0.9, clip=masks[1], jitter=0.05)
        P.line(pts, 0.5, TENG, clip=masks[1], jitter=0.05)
    # 山形印钮：三峰，主峰居中偏左，山脚坐满顶面
    bx, by = x0 + w / 2 + dx / 2, y0 - dy / 2 + 1.0
    peaks = [(-14.0, 1.2), (-12.8, -3.6), (-10.0, -10.2), (-8.0, -9.0), (-5.6, -15.8), (-2.8, -24.0), (0.2, -27.8), (2.6, -22.4),
             (4.6, -18.6), (6.6, -20.6), (8.6, -15.6), (10.6, -10.8), (12.8, -5.2), (14.0, 0.8), (0.0, 2.8)]
    mtn = catmull_closed([(bx + x, by + y) for x, y in peaks], 8)
    mtn = wobble(mtn, P.rng, 0.12, spacing=0.3)
    d, t = P.sdf(mtn)
    m_mask = P.cover(d)
    hgt = np.clip((by - P.Y) / 27.0, 0, 1)
    m_rgb = mixc(mixc(W_SHILV, W_HUAQING, 0.4), mixc(SHILV, HUAQING, 0.45), 0.25 + 0.5 * smoothstep(bx - 2, bx + 11, P.X))
    m_rgb = mixc(m_rgb, mixc(stone, PAPER, 0.3), smoothstep(0.45, 0.0, hgt) * 0.8)  # 山脚是石色，往上渐敷青绿
    P.fill(d, m_rgb, mottle=0.10, mottle_rgb=ZHONG, pool=0.3, pool_rgb=mixc(HUAQING, JIAO, 0.4), pool_w=0.8)
    # 披麻皴：顺山势的几笔
    for (sx, sy), (ex, ey) in (((-3.0, -21.0), (-7.4, -9.0)), ((-0.6, -18.0), (-3.2, -5.0)), ((3.0, -17.5), (5.0, -6.0)),
                               ((7.0, -14.0), (10.0, -4.0)), ((-8.0, -6.0), (-11.0, -0.5)), ((1.0, -10.0), (0.6, -1.0))):
        pts = V.bezier([(bx + sx, by + sy), (bx + (sx + ex) / 2 + 0.8, by + (sy + ey) / 2), (bx + ex, by + ey)], 40)
        P.line(pts, 0.42 * brush_profile(40, 1.0, 0.2), mixc(ZHONG, HUAQING, 0.3), alpha=0.55, clip=m_mask, dry=0.45, dry_start=0.3)
    # 勾金：峰脊一道藤黄
    for ridge in (((-2.8, -24.0), (0.2, -27.8), (2.6, -22.4)), ((-10.0, -10.2), (-8.0, -9.0), (-5.8, -15.0)), ((6.6, -20.6), (8.6, -15.6), (10.6, -10.8))):
        pts = V.bezier([(bx + x, by + y + 0.9) for x, y in ridge], 40)
        P.line(pts, 0.45 * brush_profile(40, 0.6, 0.3), TENG, clip=m_mask)
    # 山脚一抹留白的云气
    mist = V.bezier([(bx - 12.0, by - 2.4), (bx - 5.0, by - 4.6), (bx + 2.0, by - 1.6), (bx + 11.0, by - 3.6)], 60)
    P.line(mist, 0.9 * brush_profile(60, 0.4, 0.15), mixc(PAPER, WHITE, 0.3), alpha=0.45, clip=m_mask, dry=0.35, dry_start=0.2)
    P.outline(d, t, 1.05, mixc(JIAO, HUAQING, 0.15))
    return P.image()


# 篆书“山”（单位：字高的一半；y 向下）：中竖最高，两侧竖较矮，底部一道兜底的弧
SHAN_GLYPH = (
    tuple(map(tuple, np.vstack([[(-0.62, -0.28), (-0.62, 0.30)], V.bezier([(-0.62, 0.30), (-0.62, 0.62), (-0.30, 0.62)], 12)[1:],
                                [(0.30, 0.62)], V.bezier([(0.30, 0.62), (0.62, 0.62), (0.62, 0.30)], 12)[1:], [(0.62, -0.28)]]))),
    ((0.0, -0.80), (0.0, 0.62)),
)


def make_seal_mark() -> Image.Image:
    """朱砂印迹：方印、白文（字口不着印泥，透出地面），印泥不匀、四边有崩口。正常混合。"""
    size, ss = 64, 4
    X, Y = V.grid1(size, size, ss)
    rng = np.random.default_rng(3200)
    c = size / 2.0
    ang = math.radians(-4.0)
    u = (X - c) * math.cos(ang) + (Y - c) * math.sin(ang)
    v = -(X - c) * math.sin(ang) + (Y - c) * math.cos(ang)
    half = 25.0
    sq = (np.abs(u) ** 10 + np.abs(v) ** 10) ** 0.1 - half  # 带一点圆角的方
    sq = sq + 0.5 * V.noise1(rng, X.shape, 2.5 * ss) + 0.22 * V.noise1(rng, X.shape, 0.7 * ss)
    # 崩口：边上几处缺一小块
    for _ in range(5):
        side = rng.integers(4)
        pos = rng.uniform(-0.8, 0.8) * half
        px, py = [(pos, -half), (half, pos), (pos, half), (-half, pos)][side]
        rr = rng.uniform(1.2, 2.6)
        sq = np.maximum(sq, rr - np.hypot(u - px, v - py) + 0.3 * V.noise1(rng, X.shape, 0.8 * ss))
    cover = smoothstep(0.45, -0.45, sq)
    # 白文：字口不着色。字也带一点刀味（边上轻微起伏）
    gd = np.full(X.shape, 1e3)
    for stroke in SHAN_GLYPH:
        pts = V.arc_resample(np.array([(half * 1.02 * x, half * 1.02 * y) for x, y in stroke]), 120)
        gd = np.minimum(gd, polyline_dist(u, v, pts))
    gw = 2.9 + 0.3 * V.noise1(rng, X.shape, 1.5 * ss)
    glyph = smoothstep(gw - 0.45, gw + 0.45, gd)  # 1 = 着色
    # 印泥不匀：大块浓淡 + 成簇的麻点 + 一角压得轻
    blot = 0.5 + 0.5 * V.noise1(rng, X.shape, 4.0 * ss)
    speck = rank01(V.noise1(rng, X.shape, 0.6 * ss) + 0.8 * (blot - 0.5))
    light_corner = smoothstep(0.0, 1.0, ((u + v) / (2 * half) + 0.2 * V.noise1(rng, X.shape, 3 * ss)) * 1.6 - 0.5)
    dens = 0.95 - 0.12 * blot - 0.5 * smoothstep(0.9, 0.975, speck) - 0.3 * light_corner * smoothstep(0.6, 0.9, speck)
    a = np.clip(cover * glyph * dens, 0, 1)
    # 颜色：印泥积在边上偏深，薄处偏淡
    edge = np.exp(np.minimum(sq, 0) / 1.6) + np.exp(-np.abs(gd - gw) / 1.2) * 0.6
    rgb = mixc(ZHUSHA, mixc(ZHUSHA, JIAO, 0.3), np.clip(0.55 * edge + 0.25 * (1 - blot), 0, 1))
    rgb = mixc(rgb, mixc(ZHUSHA, PAPER, 0.25), 0.4 * light_corner * (1 - edge * 0.5))
    lay = V.Layer(*X.shape)
    lay.over(rgb, a)
    lay = lay.down(ss)
    rgb_s, a_s = lay.straight()
    a_s[0, :] = a_s[-1, :] = a_s[:, 0] = a_s[:, -1] = 0
    return V.to_rgba8(rgb_s, a_s)


def make_crack() -> Image.Image:
    """地裂：中心砸出的焦墨坑，向外放射七道折线裂缝（之字形、根部粗、尖上带飞白），少量分叉和环向短裂，
    坑外一圈干笔擦出的震痕，底下一片很淡的晕染压暗地面。按 30° 俯角压扁。正常混合（游戏里淡出）。"""
    W, H, ss = 128, 96, 4
    X, Y = V.grid1(H, W, ss)
    rng = np.random.default_rng(3300)
    cx, cy, sy = 64.0, 48.5, 0.68
    U, Vv = X - cx, (Y - cy) / sy  # 圆形空间
    lines: list[tuple[np.ndarray, float]] = []

    def grow(p0, heading, length, w0, depth):
        pts = [np.asarray(p0, dtype=np.float64)]
        L = 0.0
        while L < length:
            step = rng.uniform(3.5, 7.0)
            heading += rng.normal(0, 0.10)  # 主方向慢慢偏
            a = heading + rng.normal(0, 0.42)  # 每一段围着主方向左右折
            pts.append(pts[-1] + step * np.array([math.cos(a), math.sin(a)]))
            L += step
        pts_a = np.array(pts)
        lines.append((pts_a, w0))
        n_br = {0: rng.integers(1, 3), 1: rng.integers(0, 2)}.get(depth, 0)
        for _ in range(n_br):
            if len(pts_a) < 4:
                break
            i = int(rng.uniform(0.3, 0.7) * (len(pts_a) - 1))
            frac = i / (len(pts_a) - 1)
            grow(pts_a[i], heading + rng.choice([-1, 1]) * rng.uniform(0.5, 0.95), length * (1 - frac) * rng.uniform(0.35, 0.6), w0 * (1 - frac) * 0.6 + 0.3, depth + 1)

    n_main = 7
    for i in range(n_main):
        hd = 2 * math.pi * (i + rng.uniform(-0.3, 0.3)) / n_main + 0.3
        grow(np.array([math.cos(hd), math.sin(hd)]) * 4.0, hd, rng.uniform(36, 54), rng.uniform(2.6, 3.4), 0)
    # 环向短裂（像碎成几块的地皮）
    for _ in range(3):
        rr = rng.uniform(14, 24)
        a0 = rng.uniform(0, 2 * math.pi)
        aa = np.linspace(a0, a0 + rng.uniform(0.5, 0.85), 6)
        rad = rr + rng.normal(0, 1.0, 6)
        lines.append((np.stack([rad * np.cos(aa), rad * np.sin(aa)], -1), 1.2))
    core = np.zeros(X.shape)
    lip = np.zeros(X.shape)
    for pts, w0 in lines:
        img_pts = np.stack([cx + pts[:, 0], cy + pts[:, 1] * sy], -1)
        n = max(int(np.hypot(*np.diff(img_pts, axis=0).T).sum() / 0.4), 8)
        dense = V.arc_resample(img_pts, n)
        tt = np.linspace(0, 1, n)
        hw = 0.5 * (w0 * (1 - tt) ** 0.85 + 0.25)
        cov, f = V.brush_stroke(X, Y, dense, hw, rng, dry=0.5, dry_start=0.55, edge_jitter=0.2, ss=ss * D)
        dist = np.hypot(f["perp"], f["over"])
        core = np.maximum(core, cov)
        lip = np.maximum(lip, smoothstep(f["hw"] + 0.9, f["hw"] + 0.3, dist))
    core = np.clip(core, 0, 1)
    rho = np.hypot(U, Vv)
    th = np.arctan2(Vv, U)
    # 中心坑：星形的黑洞
    pit_r = 6.2 * (1 + V.angular_noise(rng, th, harmonics=(3, 4, 5, 7), amp=0.22))
    pit = smoothstep(pit_r + 0.5, pit_r - 0.5, rho)
    # 震痕：坑外一圈干笔擦痕
    ring_tex = ptex(rng, ns=10, nt=512, along=8.0, across=0.6)
    rb = sample_ptex(ring_tex, np.clip((rho - 10.5) / 3.0, -1, 1), np.mod(th / (2 * math.pi), 1.0))
    scuff = 0.28 * smoothstep(3.2, 1.2, np.abs(rho - 10.5)) * smoothstep(0.45, 0.75, rb)
    # 碎石屑
    debris = np.zeros(X.shape)
    for _ in range(8):
        a0 = rng.uniform(0, 2 * math.pi)
        d0 = rng.uniform(7, 20)
        px, py = d0 * math.cos(a0), d0 * math.sin(a0)
        rr = rng.uniform(0.6, 1.2)
        pr = rr * (1 + V.angular_noise(rng, np.arctan2(Vv - py, U - px), harmonics=(2, 3), amp=0.3))
        debris = np.maximum(debris, smoothstep(pr + 0.3, pr - 0.3, np.hypot(U - px, Vv - py)))
    # 压暗的晕
    wash_r = 42.0 * (1 + V.angular_noise(rng, th, harmonics=(2, 3, 4, 5), amp=0.12))
    wash = 0.14 * smoothstep(wash_r, wash_r * 0.4, rho) * (0.75 + 0.25 * V.noise1(rng, X.shape, 4 * ss))
    lay = V.Layer(*X.shape)
    lay.over(ZHONG, wash)
    lay.over(DAN, scuff)
    lay.over(DAN, 0.45 * lip)
    lay.over(JIAO, 0.96 * np.maximum(core, pit))
    lay.over(NONG, 0.9 * debris)
    lay = lay.down(ss)
    rgb_s, a_s = lay.straight()
    a_s[0, :] = a_s[-1, :] = a_s[:, 0] = a_s[:, -1] = 0
    return V.to_rgba8(rgb_s, a_s)


# ============================================================== 拾取物


def make_chest() -> Image.Image:
    """宝箱：朱漆方箱 3/4 俯视，箱盖顶面有一道漆光，藤黄铜饰（包角、箱盖压条、圆锁片），焦墨轮廓。"""
    W, H = 40, 36
    P = Painter(W, H, 3400)
    x0, w, h, dx, dy = 5.5, 22.0, 15.5, 7.0, 5.0
    y0 = 30.6 + dy / 2 - h
    lid_h = 5.2
    front, top, side, sil = box_faces(x0, y0, w, h, dx, dy)
    lac = ZHUSHA
    tones = (mixc(lac, PAPER, 0.28), lac, mixc(lac, ZHONG, 0.45))
    masks = []
    for poly, rgb in zip((top, front, side), tones):
        d, _ = P.sdf(wobble(poly, P.rng, 0.06, spacing=0.3))
        masks.append(P.cover(d))
        P.fill(d, rgb, mottle=0.08, mottle_rgb=ZHUSHA_DK, pool=0.3, pool_rgb=ZHUSHA_DK, pool_w=0.7)
    # 漆光：顶面一道斜的亮带
    gl = V.bezier([(x0 + 4.0, y0 - 1.2), (x0 + 10.0, y0 - 3.6), (x0 + 17.0, y0 - 4.2)], 40)
    P.line(gl, 0.75 * brush_profile(40, 0.5, 0.2), mixc(lac, WHITE, 0.55), alpha=0.7, clip=masks[0])
    # 箱盖缝（正面、侧面）
    ys = y0 + lid_h
    P.line(seg_pts((x0, ys), (x0 + w, ys), (x0 + w + dx, ys - dy), n=60), 0.42, mixc(ZHUSHA_DK, JIAO, 0.5))
    # 铜饰：箱盖压条、包角、侧面压条
    def gold_poly(poly, ol=0.55):
        d, t = P.sdf(wobble(poly, P.rng, 0.04, spacing=0.25))
        P.fill(d, TENG, pool=0.45, pool_rgb=GOLD_DK, pool_w=0.4)
        P.outline(d, t, ol, GOLD_DK)

    gold_poly([(x0, ys - 0.8), (x0 + w, ys - 0.8), (x0 + w, ys + 0.8), (x0, ys + 0.8)])
    gold_poly([(x0 + w, ys - 0.8), (x0 + w + dx, ys - dy - 0.8), (x0 + w + dx, ys - dy + 0.8), (x0 + w, ys + 0.8)])
    for xa, xb in ((x0, x0 + 2.4), (x0 + w - 2.4, x0 + w)):
        gold_poly([(xa, y0), (xb, y0), (xb, y0 + h), (xa, y0 + h)])
    gold_poly([(x0 + w + dx - 2.0, y0 - dy + 1.5), (x0 + w + dx, y0 - dy), (x0 + w + dx, y0 + h - dy), (x0 + w + dx - 2.0, y0 + h - dy + 1.5)])
    # 圆锁片 + 锁鼻
    lx, ly = x0 + w / 2, ys + 1.6
    d, t = P.sdf(ellipse_pts(lx, ly, 3.0, 3.0, 48))
    P.fill(d, mixc(TENG, GOLD_HI, smoothstep(1.5, -2.5, P.Y - ly)), pool=0.5, pool_rgb=GOLD_DK, pool_w=0.5)
    P.outline(d, t, 0.6, GOLD_DK)
    P.dot(lx, ly + 0.5, 0.65, JIAO, ry=1.0)
    P.line(seg_pts((lx, ly - 3.8), (lx, ly - 1.6), n=20), 0.55, GOLD_DK)
    # 外轮廓
    d, t = P.sdf(wobble(sil, P.rng, 0.06, spacing=0.3))
    P.outline(d, t, 1.15, jitter=0.25)
    P.line(seg_pts((x0, y0), (x0 + w, y0), (x0 + w + dx, y0 - dy), n=60), 0.36, JIAO)
    P.line(seg_pts((x0 + w, y0), (x0 + w, y0 + h), n=30), 0.36, JIAO)
    return P.image()


def make_soulbell() -> Image.Image:
    """引魂铃：小铜铃（藤黄兑赭石，左亮右暗），圆肩、铃口向上弯成弧（于口），一道箍、三粒乳钉，
    铃口下露出铃舌；铃钮上系一个朱砂绳环。"""
    W, H = 20, 26
    P = Painter(W, H, 3500)
    cx = 10.0
    bronze = mixc(TENG, ZHESHI, 0.45)
    ink = mixc(JIAO, NONG, 0.2)
    # 朱砂绳环与结
    loop = ellipse_pts(cx, 3.4, 1.7, 1.75, 48)
    P.line(V.arc_resample(np.vstack([loop, loop[:1]]), 80), 0.42, ZHUSHA)
    # 铃口里的暗面和铃舌（先画，被铃身挡住）
    d, t = P.sdf(ellipse_pts(cx, 21.3, 5.9, 1.5, 40))
    P.fill(d, mixc(NONG, ZHESHI, 0.15))
    P.dot(cx + 0.2, 22.5, 1.15, mixc(GOLD_DK, JIAO, 0.4), ry=1.4)
    P.dot(cx - 0.2, 22.1, 0.35, GOLD_HI, alpha=0.8)
    # 铃钮（拱形）
    d, t = P.sdf(ellipse_pts(cx, 6.1, 1.6, 1.4, 32))
    P.fill(d, bronze, pool=0.4, pool_rgb=GOLD_DK, pool_w=0.5)
    P.dot(cx, 6.1, 0.6, NONG)
    P.outline(d, t, 0.5, ink)
    P.dot(cx, 5.0, 0.8, ZHUSHA_DK)
    # 铃身：圆肩，腰略收，下摆外撇；铃口是一道向上的弧，两角下垂
    y_top, y_mouth = 7.2, 21.6
    ys = np.linspace(y_top, y_mouth, 32)
    yn = (ys - y_top) / (y_mouth - y_top)
    hw = 2.9 + 1.7 * np.sqrt(yn) + 2.3 * yn**2.4
    left = [(cx - a, y) for a, y in zip(hw, ys)]
    xs = np.linspace(-hw[-1], hw[-1], 30)[1:-1]
    mouth = [(cx + x, y_mouth - 1.7 * (1 - (x / hw[-1]) ** 2)) for x in xs]
    right = [(cx + a, y) for a, y in zip(hw[::-1], ys[::-1])]
    crown = [(cx + 2.9 * math.cos(a), y_top - 1.5 * math.sin(a)) for a in np.linspace(0, math.pi, 14)[1:-1]]
    body = np.array(left + mouth + right + crown)
    d, t = P.sdf(body)
    shade = smoothstep(cx - 4.5, cx + 6.0, P.X)
    rgb = mixc(mixc(bronze, GOLD_HI, 0.4), mixc(bronze, ZHONG, 0.5), shade)
    P.fill(d, rgb, mottle=0.08, mottle_rgb=GOLD_DK, pool=0.35, pool_rgb=GOLD_DK, pool_w=0.6)
    mask = P.cover(d)
    # 高光、箍、乳钉、口沿
    P.line(V.bezier([(cx - 1.7, 8.6), (cx - 2.8, 13.0), (cx - 4.6, 19.0)], 30), 0.5 * brush_profile(30, 0.5, 0.3), GOLD_HI, alpha=0.8, clip=mask)
    arc = [(cx + 4.25 * math.cos(a), 11.8 + 0.9 * math.sin(a)) for a in np.linspace(math.pi, 0, 30)]
    P.line(np.array(arc), 0.3, GOLD_DK, clip=mask)
    lip = [(cx + x * 0.97, y_mouth - 1.2 - 1.7 * (1 - (x / hw[-1]) ** 2)) for x in np.linspace(-hw[-1], hw[-1], 40)]
    P.line(np.array(lip), 0.28, GOLD_DK, alpha=0.85, clip=mask)
    for xo in (-2.5, 0.0, 2.5):
        yy = 15.4 + 0.15 * abs(xo)
        P.dot(cx + xo, yy, 0.55, GOLD_DK, clip=mask)
        P.dot(cx + xo - 0.18, yy - 0.18, 0.24, GOLD_HI, clip=mask)
    P.outline(d, t, 0.85, ink)
    return P.image()


def make_lotus() -> Image.Image:
    """莲：一朵粉白小莲花坐在石绿荷叶上。花瓣根白梢粉（朱砂淡彩），淡墨勾瓣，荷叶有叶脉与一道缺口。"""
    W, H = 22, 20
    P = Painter(W, H, 3600)
    cx, cy = 11.0, 15.3
    # 荷叶：透视压扁的圆，右前方一道 V 形缺口
    th = np.linspace(0, 2 * math.pi, 96, endpoint=False)
    notch = 0.42 * np.exp(-((np.angle(np.exp(1j * (th - 1.05))) / 0.16) ** 2))
    rr = 1.0 - notch
    leaf = np.stack([cx + 9.4 * rr * np.cos(th), cy + 3.3 * rr * np.sin(th)], -1)
    leaf = wobble(leaf, P.rng, 0.06, spacing=0.3)
    d, t = P.sdf(leaf)
    leaf_rgb = mixc(W_SHILV, mixc(SHILV, ZHONG, 0.3), smoothstep(cy - 3.0, cy + 3.5, P.Y) * 0.8)
    P.fill(d, leaf_rgb, mottle=0.1, mottle_rgb=mixc(SHILV, JIAO, 0.5), pool=0.3, pool_rgb=mixc(SHILV, JIAO, 0.45), pool_w=0.6)
    lmask = P.cover(d)
    for a in np.linspace(0.3, 2 * math.pi - 0.3, 9) + 1.05:
        P.line(seg_pts((cx, cy), (cx + 8.5 * math.cos(a), cy + 3.0 * math.sin(a)), n=20), 0.18, mixc(SHILV, JIAO, 0.45), alpha=0.6, clip=lmask)
    P.outline(d, t, 0.6, mixc(SHILV, JIAO, 0.65))
    # 花瓣：根部白、尖上粉
    pink = mixc(W_ZHUSHA, PAPER, 0.15)
    pink_tip = mixc(W_ZHUSHA, ZHUSHA, 0.25)
    white = mixc(PAPER, WHITE, 0.6)
    base = np.array([cx, cy - 1.6])

    def petal(tip, width, shade=0.0, asym=0.0):
        poly = almond(base, tip, width, 40, bulge=0.55, asym=asym)
        d, t = P.sdf(poly)
        along = ((P.X - base[0]) * (tip[0] - base[0]) + (P.Y - base[1]) * (tip[1] - base[1])) / ((tip[0] - base[0]) ** 2 + (tip[1] - base[1]) ** 2)
        rgb = mixc(white, pink, smoothstep(0.25, 0.85, along))
        rgb = mixc(rgb, pink_tip, smoothstep(0.82, 1.0, along))
        rgb = mixc(rgb, QING, shade)
        P.fill(d, rgb, pool=0.18, pool_rgb=pink_tip, pool_w=0.5)
        P.outline(d, t, 0.5, mixc(ZHUSHA_DK, JIAO, 0.45), jitter=0.2)

    for tip, wdt in (((cx - 3.3, 4.4), 4.4), ((cx + 3.3, 4.4), 4.4)):
        petal(tip, wdt, shade=0.18)
    petal((cx, 2.6), 4.8, shade=0.08)
    # 莲蓬（藤黄）从中间露一点
    P.dot(cx, cy - 4.3, 1.9, mixc(TENG, W_SHILV, 0.3), ry=0.9)
    P.dot(cx - 0.6, cy - 4.4, 0.3, GOLD_DK)
    P.dot(cx + 0.7, cy - 4.3, 0.3, GOLD_DK)
    for tip, wdt, asym in (((cx - 6.6, 8.2), 4.0, 0.15), ((cx + 6.6, 8.2), 4.0, -0.15)):
        petal(tip, wdt, asym=asym)
    for tip, wdt in (((cx - 3.4, 8.6), 4.6), ((cx + 3.4, 8.6), 4.6)):
        petal(tip, wdt)
    return P.image()


# ============================================================== 狐火


def make_foxfire(frame: int) -> Image.Image:
    """狐火（夜主的弹幕）：亮的圆核 + 向左（飞行反方向）拖出的三缕火舌，火舌逐帧摆动，尾巴更淡。
    白色可染色、叠加混合；旋转角 0 时朝 +X 飞。3 帧循环。"""
    W, H, ss = 24, 24, 8
    X, Y = V.grid1(H, W, ss)
    ph = 2 * math.pi * frame / 3
    cx, cy = 14.4, 12.0
    r = np.hypot(X - cx, Y - cy)
    core_r = 3.6 + 0.3 * math.sin(ph)
    core = smoothstep(core_r + 0.9, core_r - 0.8, r)
    hot = np.exp(-((r / 2.0) ** 2))
    tongues = np.zeros_like(r)
    # (纵向偏移, 长度, 根部半宽, 摆幅, 相位)
    for dy0, L, w0, amp, k in ((0.0, 12.0, 3.0, 1.2, 0.0), (-2.4, 8.6, 1.7, 1.0, 2.2), (2.3, 8.2, 1.6, 1.0, 4.1)):
        wob = amp * math.sin(ph + k)
        p0 = (cx - 0.5, cy + dy0 * 0.5)
        p1 = (cx - L * 0.35, cy + dy0 + wob * 0.6)
        p2 = (cx - L * 0.7, cy + dy0 * 1.2 - wob)
        p3 = (cx - L, cy + dy0 * 1.35 + wob * 0.9)
        pts = V.bezier([p0, p1, p2, p3], 80)
        tt = np.linspace(0, 1, len(pts))
        f = V.stroke_fields(X, Y, pts, w0 * (1 - tt) ** 0.9 + 0.08)
        m = np.clip(1 - np.hypot(f["perp"], f["over"]) / f["hw"], 0, 1)
        tongues = np.maximum(tongues, smoothstep(0.0, 0.35, m) * (0.85 - 0.5 * f["t"]))
    shape = np.maximum(core, tongues)
    halo = 0.4 * fft_blur(shape, V.sig(1.6 * ss)) * (1 - core)
    a = np.clip(np.maximum(shape, halo) + 0.25 * hot, 0, 1)
    a *= V.bump_window(np.hypot((X - 12.0) / 11.6, (Y - 12.0) / 11.6)) ** 0.25
    return white_image(a, ss)


# ============================================================== 扇形预警（M2.5）

SECTOR_W, SECTOR_H = 76, 124  # 画布（1 倍像素）
SECTOR_APEX = (4.75, 62.0)  # 扇顶 = 锚点 (0.0625, 0.5)
SECTOR_R = 64.0  # 半径（1 倍像素；2 倍 128）
SECTOR_HALF = math.radians(60.0)  # 半角：整扇 120°


def sector_fields(ss: int):
    """以扇顶为原点的极坐标：X, Y, 半径 r（1 倍像素）、角 a（弧度，0 = +X）、到扇形边界的近似距离 d（内负外正）。"""
    X, Y = V.grid1(SECTOR_H, SECTOR_W, ss)
    dx, dy = X - SECTOR_APEX[0], Y - SECTOR_APEX[1]
    r = np.hypot(dx, dy)
    a = np.arctan2(dy, dx)
    d_arc = r - SECTOR_R
    d_side = (np.abs(a) - SECTOR_HALF) * np.maximum(r, 1e-6)  # 到两条边的弧长近似距离
    return X, Y, r, a, np.maximum(d_arc, d_side), d_arc, d_side


def make_sector() -> Image.Image:
    """扇形预警：120° 的扇面，扇顶在锚点、开口朝 +X。扇面一层由里往外渐浓的淡光（水墨的不匀）、两条边是干笔的细线
    （近扇顶收尖）、外沿一笔更重的弧（飞白），里面一道淡的同心弧，读得出“这一片要挨打”。白色，染色叠加（游戏里染红）。"""
    ss = 6
    X, Y, r, a, d, d_arc, d_side = sector_fields(ss)
    rng = np.random.default_rng(3100)
    u = np.clip(r / SECTOR_R, 0, 1.2)
    t = np.clip((a + SECTOR_HALF) / (2 * SECTOR_HALF), 0, 1)  # 沿弧 0..1
    # 扇面：由里往外渐浓，带一点晕染的不匀
    wash = 0.08 + 0.26 * u**1.6 + 0.04 * V.noise1(rng, X.shape, 5.0 * ss)
    fill = np.clip(wash, 0, 1) * smoothstep(0.6, -0.6, d)
    # 外沿的弧：一笔，两头收细，飞白
    tex = ptex(rng, ns=16, nt=512, along=8.0, across=0.6)
    hw = 2.3 * np.interp(t, [0.0, 0.08, 0.5, 0.92, 1.0], [0.35, 1.0, 1.1, 1.0, 0.35])
    pc = d_arc + 2.0
    b = sample_ptex(tex, np.clip(pc / np.maximum(hw, 0.3), -1, 1), t * 0.999)
    rim = smoothstep(hw + 0.4, hw - 0.4, np.abs(pc)) * (np.abs(a) <= SECTOR_HALF + 0.02)
    rim = rim * (0.55 + 0.45 * smoothstep(0.25, 0.45, b)) * (1.0 - 0.5 * smoothstep(0.85, 1.0, np.abs(2 * t - 1)) * (b < 0.5))
    # 两条边：干笔细线，近扇顶收尖
    sides = np.zeros_like(r)
    for sgn in (-1.0, 1.0):
        ang = sgn * SECTOR_HALF
        ux, uy = math.cos(ang), math.sin(ang)
        along = (X - SECTOR_APEX[0]) * ux + (Y - SECTOR_APEX[1]) * uy
        perp = -(X - SECTOR_APEX[0]) * uy + (Y - SECTOR_APEX[1]) * ux + sgn * 1.1
        ta = np.clip(along / SECTOR_R, 0, 1)
        shw = 1.25 * (0.2 + 0.8 * smoothstep(0.0, 0.35, ta))
        bs = sample_ptex(tex, np.clip(perp / np.maximum(shw, 0.3), -1, 1), np.mod(ta * 0.7 + 0.15 * (sgn + 1), 1.0))
        line = smoothstep(shw + 0.35, shw - 0.35, np.abs(perp)) * (along > 0) * (along < SECTOR_R - 1.0)
        sides = np.maximum(sides, line * (0.55 + 0.25 * smoothstep(0.3, 0.6, bs)))
    # 里面一道淡的同心弧（断续）
    echo = 0.28 * smoothstep(0.9, 0.2, np.abs(r - 0.62 * SECTOR_R)) * smoothstep(0.35, 0.6, sample_ptex(tex, 0.0, t * 0.6)) * smoothstep(0.5, -1.5, d_side)
    a_ss = np.clip(np.maximum.reduce([fill, rim, sides, fill + echo]), 0, 1)
    return white_image(a_ss, ss, dither_seed=3101)


def make_sector_fill() -> Image.Image:
    """扇形预警的“蓄力”层：同尺寸同锚点，匀净的扇面 + 外沿一道亮带。游戏里按蓄力进度从扇顶往外缩放（0→1），
    亮带就是往外推的那道“浪头”；叠在 sector 上一起染色叠加。"""
    ss = 6
    X, Y, r, a, d, d_arc, d_side = sector_fields(ss)
    u = np.clip(r / SECTOR_R, 0, 1)
    body = (0.22 + 0.18 * u) * smoothstep(0.8, -0.8, d)
    front = 0.75 * np.exp(-(((d_arc + 2.2) / 1.6) ** 2)) * smoothstep(0.8, -0.8, d_side)
    a_ss = np.clip(body + front, 0, 1)
    return white_image(a_ss, ss, dither_seed=3102)


# ============================================================== 冲锋预警（M2.5）
#
# 精英扑击 / 冲撞的地面预警：车道 charge_line 的锚点在起点（左端、竖向居中），沿 +X 伸出去，游戏按冲锋长度沿 X 拉伸、再旋转；
# 车道沿 X 的透明度一致（只在起点淡入），横向的笔丝只随 y 变，所以怎么拉都不走样；最右一列不清零，接上箭头不留缝。
# 箭头 charge_line_head 单独一帧，锚点在箭头底边的正中，接在车道的末端；箭头里先接着画一小段同样的车道，再收成箭尖。

CHARGE_W, CHARGE_H = 128, 20  # 车道画布（1 倍像素；2 倍 256×40）
CHARGE_HW = 7.0  # 车道半宽：宽 14 像素（1 倍）= 2 倍 28 像素
HEAD_W, HEAD_H = 32, 32  # 箭头画布（2 倍 64×64）
HEAD_BASE, HEAD_TIP, HEAD_HH = 4.0, 29.5, 12.5  # 箭头底边、箭尖的 x，底边的半高


def lane_alpha(v: np.ndarray, rim_mod) -> np.ndarray:
    """车道的横截面：v 是到中线的距离（1 倍像素）。中间一层淡的、顺着冲锋方向的笔丝（只随 v 变），两侧一道稍亮的边，
    边外一圈很淡的洇痕。rim_mod 调两侧边的浓淡（车道里沿 X 缓慢起伏，箭头里取 1）。"""
    rng = np.random.default_rng(3200)
    vs = np.linspace(-CHARGE_HW - 3, CHARGE_HW + 3, 96)
    silk = np.interp(v, vs, 0.62 + 0.7 * rank01(V.noise(rng, (1, 96), (1.6, 0.0)))[0])
    rim_w = np.interp(v, vs, 0.8 + 0.35 * rank01(V.noise(rng, (1, 96), (3.0, 0.0)))[0])
    va = np.abs(v)
    fill = 0.27 * smoothstep(CHARGE_HW + 0.4, CHARGE_HW - 1.4, va) * silk
    rim = 1.0 * np.exp(-(((va - (CHARGE_HW - 1.3)) / (0.9 * rim_w)) ** 2)) * rim_mod * (0.75 + 0.25 * silk)
    bleed = 0.1 * np.exp(-np.maximum(va - CHARGE_HW + 0.6, 0) / 0.9) * (va > CHARGE_HW - 0.6)
    return np.clip(np.maximum.reduce([fill, rim, bleed]), 0, 1)


def make_charge_line() -> Image.Image:
    """冲锋预警的车道：一条压在地上的淡光带，顺着冲锋方向的笔丝、两侧的边稍亮（浓淡沿 X 缓慢起伏），边外一圈淡淡的洇痕，
    起点一小段淡入；其余沿 X 一致，拉多长都不走样。白色，染色叠加（游戏里染红）。"""
    ss = 6
    X, Y = V.grid1(CHARGE_H, CHARGE_W, ss)
    v = Y - CHARGE_H / 2
    rng = np.random.default_rng(3201)
    wav = sample1(pnoise1(rng, 256, 14.0), X / CHARGE_W * 0.999)
    rim_mod = 1.0 - 0.18 * smoothstep(-0.2, 1.4, wav) * smoothstep(CHARGE_W - 4.0, CHARGE_W - 24.0, X)  # 末端回到 1，与箭头接上
    a = lane_alpha(v, rim_mod) * smoothstep(0.0, 7.0, X)
    a8 = np.clip(V.downsample(a, ss), 0, 1)
    a8[0, :] = a8[-1, :] = 0
    a8[:, 0] = 0  # 起点那一列清零；最右一列保留（拉伸后接箭头）
    return V.to_rgba8(WHITE, a8)


def make_charge_line_head() -> Image.Image:
    """冲锋预警的箭头：接着车道画一小段，收成一个干笔勾边的箭尖（两条斜边重、底下淡淡一层），里面再一道小的折笔。"""
    ss = 6
    X, Y = V.grid1(HEAD_H, HEAD_W, ss)
    v = Y - HEAD_H / 2
    rng = np.random.default_rng(3202)
    span = HEAD_TIP - HEAD_BASE
    u = (X - HEAD_BASE) / span  # 0 底边 .. 1 箭尖
    half = HEAD_HH * np.clip(1.0 - u, 0, 1)
    inside = smoothstep(0.4, -0.4, np.abs(v) - half) * (u >= 0) * (u <= 1)
    # 车道接进来：底边处与 charge_line 最右一列相同，往里几像素淡进箭头的填色
    lane = lane_alpha(v, 1.0) * (X >= HEAD_BASE) * smoothstep(HEAD_BASE + 7.0, HEAD_BASE + 1.0, X)
    fill = (0.24 + 0.14 * u) * inside
    tex = ptex(rng, ns=12, nt=256, along=6.0, across=0.6)
    edges = np.zeros_like(X)
    for sgn in (-1.0, 1.0):
        p0 = np.array([HEAD_BASE, HEAD_H / 2 + sgn * HEAD_HH])
        p1 = np.array([HEAD_TIP, HEAD_H / 2])
        d = p1 - p0
        L = float(np.hypot(*d))
        t = np.clip(((X - p0[0]) * d[0] + (Y - p0[1]) * d[1]) / L**2, 0, 1)
        perp = np.hypot(X - p0[0] - d[0] * t, Y - p0[1] - d[1] * t)
        hw = 1.35 * (0.45 + 0.55 * smoothstep(0.0, 0.25, t)) * (1.0 - 0.35 * t)
        b = sample_ptex(tex, np.clip(perp / np.maximum(hw, 0.3), -1, 1), t * 0.999)
        dry = 0.55 * smoothstep(0.55, 1.0, t)  # 往箭尖去笔越干，带飞白
        edges = np.maximum(edges, smoothstep(hw + 0.4, hw - 0.4, perp) * smoothstep(dry - 0.08, dry + 0.08, b) * (0.7 + 0.3 * b))
    # 里面一道小折笔
    chev = np.zeros_like(X)
    for sgn in (-1.0, 1.0):
        p0 = np.array([HEAD_BASE + 8.0, HEAD_H / 2 + sgn * 6.0])
        p1 = np.array([HEAD_BASE + 15.5, HEAD_H / 2])
        d = p1 - p0
        t = np.clip(((X - p0[0]) * d[0] + (Y - p0[1]) * d[1]) / float(d @ d), 0, 1)
        perp = np.hypot(X - p0[0] - d[0] * t, Y - p0[1] - d[1] * t)
        chev = np.maximum(chev, smoothstep(1.05, 0.45, perp))
    a = np.clip(np.maximum.reduce([np.maximum(lane, fill), edges, 0.7 * chev * inside]), 0, 1)
    return white_image(a, ss)


# ============================================================== 汇总

WHITE_ADD = {"color": "white", "blend": "add", "tint": True}


def build() -> dict[str, tuple[Image.Image, tuple[float, float], dict]]:
    """生成全部贴图：{名字: (图, 锚点, meta 附加字段)}。不写盘，测试用它做两次生成的比对。"""
    out: dict[str, tuple[Image.Image, tuple[float, float], dict]] = {}
    full = {"color": "full", "blend": "normal", "tint": False}
    out["sword"] = (make_sword(False), (0.6, 0.5), {**full, "kind": "weapon", "points": "+x", "note": "符剑：剑尖朝 +X，剑身约 22 世界单位"})
    out["sword_evo"] = (make_sword(True), (0.6, 0.5), {**full, "kind": "weapon", "points": "+x", "note": "万剑归宗：金边剑身，自带一圈淡金光"})
    out["sword_trail"] = (make_trail(), (1.0, 0.5), {**WHITE_ADD, "kind": "fx", "points": "+x", "note": "剑尾光：锚点在右端（剑的位置），向左拖尾，画在剑后面；建议染 #CFE3F5"})
    for i in range(4):
        out[f"crane_{i}"] = (make_crane(i, False), (0.5, 0.5), {**full, "kind": "weapon", "points": "+x", "anim": "crane", "frame": i, "frames": 4, "fps": 10, "note": "纸鹤扑翼循环"})
    for i in range(4):
        out[f"crane_evo_{i}"] = (make_crane(i, True), (0.5, 0.5), {**full, "kind": "weapon", "points": "+x", "anim": "crane_evo", "frame": i, "frames": 4, "fps": 12, "note": "千鹤引：翼缘金箔"})
    out["ring"] = (make_ring(), (0.5, 0.5), {**WHITE_ADD, "kind": "fx", "radius_px": V.dpx(57), "note": "涟漪环：环外沿半径约 57px（贴图半宽 64），按需要的半径缩放；霜铃染 #6FB8FF，大招染金，地震染赭"})
    out["ring_ink"] = (make_ring_ink(), (0.5, 0.5), {"color": "full", "blend": "normal", "tint": False, "kind": "fx", "radius_px": V.dpx(50), "note": "一笔圆相墨圈，地面墨痕"})
    out["seal"] = (make_seal(), (0.5, 0.85), {**full, "kind": "weapon", "note": "山印：锚点是石印底面中心（落地点）"})
    out["seal_evo"] = (make_seal_evo(), (0.5, 0.85), {**full, "kind": "weapon", "note": "镇岳：锚点是石印底面中心（落地点）"})
    out["seal_mark"] = (make_seal_mark(), (0.5, 0.5), {**full, "kind": "fx", "note": "朱砂印迹，白文字口透明（露出地面）；可随机旋转"})
    out["crack"] = (make_crack(), (0.5, 0.5), {**full, "kind": "fx", "note": "镇岳地裂，已按俯角压扁；淡出使用"})
    out["warn"] = (make_warn(), (0.5, 0.5), {**WHITE_ADD, "kind": "fx", "radius_px": V.dpx(27), "note": "落印预警靶环，建议染 #C9925A，可慢慢旋转"})
    out["taiji"] = (make_taiji(), (0.5, 0.5), {**full, "kind": "fx", "radius_px": V.dpx(54), "note": "水墨太极，焦墨与宣纸色，可旋转"})
    out["blast"] = (make_blast(), (0.5, 0.5), {**WHITE_ADD, "kind": "fx", "note": "爆炸烟团，火染 #FF8A3D，冰染 #6FB8FF"})
    out["shield"] = (make_shield(), (0.5, 0.5), {**WHITE_ADD, "kind": "fx", "radius_px": V.dpx(28), "note": "护体罩：八角 + 八卦爻，建议染 #C9925A"})
    out["chest"] = (make_chest(), (0.5, 0.85), {**full, "kind": "pickup", "note": "宝箱：锚点是箱底中心"})
    out["soulbell"] = (make_soulbell(), (0.5, 0.85), {**full, "kind": "pickup", "note": "引魂铃：锚点在铃口"})
    out["lotus"] = (make_lotus(), (0.5, 0.8), {**full, "kind": "pickup", "note": "莲：锚点在荷叶中心"})
    # ---- 第二批（桌面版）新增：只往后追加，前面的条目与 1 倍文件逐字节不变
    for i in range(3):
        out[f"foxfire_{i}"] = (make_foxfire(i), (0.6, 0.5), {**WHITE_ADD, "kind": "fx", "points": "+x", "anim": "foxfire", "frame": i, "frames": 3, "fps": 12,
                                                            "note": "夜主的狐火弹：锚点在火球中心，火舌向后拖；建议染 #FF6B5A（style.EYE.fox）"})
    # ---- M2.5 追加
    sector_anchor = (SECTOR_APEX[0] / SECTOR_W, SECTOR_APEX[1] / SECTOR_H)
    out["sector"] = (make_sector(), sector_anchor, {**WHITE_ADD, "kind": "fx", "points": "+x", "radius_px": V.dpx(SECTOR_R), "angle_deg": 120,
                                                    "note": "扇形预警：120°，锚点在扇顶、开口朝 +X；radius_px 是半径，按需要的半径缩放；建议染红 #FF4A3A"})
    out["sector_fill"] = (make_sector_fill(), sector_anchor, {**WHITE_ADD, "kind": "fx", "points": "+x", "radius_px": V.dpx(SECTOR_R), "angle_deg": 120,
                                                              "note": "扇形预警的蓄力层：与 sector 同尺寸同锚点，按蓄力进度从扇顶往外缩放（0→1），外沿一道亮带"})
    head_len = V.dpx(HEAD_TIP - HEAD_BASE)
    out["charge_line"] = (make_charge_line(), (0.0, 0.5), {**WHITE_ADD, "kind": "fx", "points": "+x", "stretch": "x", "width_px": V.dpx(2 * CHARGE_HW),
                                                         "note": f"冲锋预警的车道：锚点在起点（左端、竖向居中），沿 +X 拉伸到“冲锋长度 − 箭头长 {head_len} 像素”再旋转；"
                                                                 "沿 X 透明度一致（只有起点淡入），拉多长都不走样；末端接 charge_line_head；建议染红 #FF4A3A"})
    out["charge_line_head"] = (make_charge_line_head(), (HEAD_BASE / HEAD_W, 0.5), {**WHITE_ADD, "kind": "fx", "points": "+x", "width_px": V.dpx(2 * CHARGE_HW), "head_len_px": head_len,
                                                                                    "note": "冲锋预警的箭头：锚点在箭头底边正中，放在车道末端、同样旋转，不拉伸；箭尖比锚点远 head_len_px"})
    return out


# ============================================================== 检查图

TINTS = {
    "foxfire_0": S.EYE["fox"],
    "foxfire_1": S.EYE["fox"],
    "foxfire_2": S.EYE["fox"],
    "ring": "#6FB8FF",
    "sword_trail": "#CFE3F5",
    "warn": "#C9925A",
    "blast": "#FF8A3D",
    "shield": "#C9925A",
    "sector": "#FF4A3A",
    "sector_fill": "#FF4A3A",
    "charge_line": "#FF4A3A",
    "charge_line_head": "#FF4A3A",
}


def review_sheet(items, path: Path, scale: int = 3) -> None:
    """每张贴图 3× 摆两遍：上半张铺纸色、原样 over；下半张铺夜色、按游戏里的混合方式（白色贴图染色后叠加）。"""
    width, pad, label_h = 1720, 18, 18
    f_title, f_lab = V.font(16), V.font(12)
    order = list(items)

    def label(name, night):
        img, _, extra = items[name]
        lab = f"{name} {img.width}x{img.height}"
        return lab + (f" add {TINTS.get(name, '')}" if night and extra.get("blend") == "add" else "")

    placements = []
    x = y = pad
    row_h = 0
    for name in order:
        img = items[name][0]
        cw = max(img.width * scale, int(f_lab.getlength(label(name, True))) + 6)
        ch = img.height * scale + label_h
        if x + cw + pad > width:
            x = pad
            y += row_h + pad
            row_h = 0
        placements.append((x, y))
        x += cw + pad
        row_h = max(row_h, ch)
    panel_h = y + row_h + pad + 26
    canvas = np.zeros((panel_h * 2, width, 3))
    canvas[:panel_h] = PAPER
    canvas[panel_h:] = col(S.NIGHT_AMBIENT)
    for name, (px, py) in zip(order, placements):
        img, _, extra = items[name]
        add = extra.get("blend") == "add"
        tint = col(TINTS[name]) if name in TINTS else None
        V.composite(canvas, img, px, py + 26 + label_h, "over", None, scale=scale)
        V.composite(canvas, img, px, panel_h + py + 26 + label_h, "add" if add else "over", tint, scale=scale)
    im = Image.fromarray(np.round(canvas * 255).astype(np.uint8), "RGB")
    dr = ImageDraw.Draw(im)
    dr.text((pad, 6), f"(a) on PAPER, normal over, untinted, {scale}x nearest", fill=S.INK["jiao"], font=f_title)
    dr.text((pad, panel_h + 6), "(b) on NIGHT_AMBIENT #161B2C, in-game blend (white textures: tint + additive)", fill="#E0E0E0", font=f_title)
    for name, (px, py) in zip(order, placements):
        dr.text((px, py + 26), label(name, False), fill=S.INK["nong"], font=f_lab)
        dr.text((px, panel_h + py + 26), label(name, True), fill="#C8C8C8", font=f_lab)
    V.save_png(im, path)


def place(canvas: np.ndarray, img: Image.Image, x: float, y: float, *, angle: float = 0.0, scale=1.0, anchor=(0.5, 0.5), mode: str = "over", tint=None, alpha: float = 1.0) -> None:
    """像 GPU 那样把精灵（旋转、缩放、锚点）双线性采样到 float 画布上；预乘 alpha 插值，不出黑边。"""
    arr = np.asarray(img.convert("RGBA"), dtype=np.float64) / 255.0
    a = arr[..., 3] * alpha
    rgb = arr[..., :3] * (np.asarray(tint) if tint is not None else 1.0)
    pm = np.dstack([rgb * a[..., None], a])
    pm = np.pad(pm, ((1, 1), (1, 1), (0, 0)))
    h, w = img.height, img.width
    sx, sy = (scale, scale) if np.isscalar(scale) else scale
    ca, sa = math.cos(angle), math.sin(angle)
    ax, ay = anchor[0] * w, anchor[1] * h
    corners = np.array([[0, 0], [w, 0], [0, h], [w, h]], dtype=np.float64) - [ax, ay]
    cx = x + (corners[:, 0] * sx) * ca - (corners[:, 1] * sy) * sa
    cy = y + (corners[:, 0] * sx) * sa + (corners[:, 1] * sy) * ca
    x0, x1 = max(int(math.floor(cx.min())), 0), min(int(math.ceil(cx.max())) + 1, canvas.shape[1])
    y0, y1 = max(int(math.floor(cy.min())), 0), min(int(math.ceil(cy.max())) + 1, canvas.shape[0])
    if x0 >= x1 or y0 >= y1:
        return
    gx, gy = np.meshgrid(np.arange(x0, x1) + 0.5, np.arange(y0, y1) + 0.5)
    dx, dy = gx - x, gy - y
    u = (dx * ca + dy * sa) / sx + ax - 0.5 + 1.0  # 源像素坐标（含 1 像素填充）
    v = (-dx * sa + dy * ca) / sy + ay - 0.5 + 1.0
    ok = (u >= 0) & (v >= 0) & (u <= w + 1) & (v <= h + 1)
    u = np.clip(u, 0, w + 0.999)
    v = np.clip(v, 0, h + 0.999)
    i0, j0 = np.floor(v).astype(int), np.floor(u).astype(int)
    i1, j1 = np.minimum(i0 + 1, h + 1), np.minimum(j0 + 1, w + 1)
    fv, fu = (v - i0)[..., None], (u - j0)[..., None]
    s = (pm[i0, j0] * (1 - fu) + pm[i0, j1] * fu) * (1 - fv) + (pm[i1, j0] * (1 - fu) + pm[i1, j1] * fu) * fv
    s = s * ok[..., None]
    reg = canvas[y0:y1, x0:x1]
    if mode == "add":
        reg += s[..., :3]
    else:
        reg[:] = s[..., :3] + reg * (1 - s[..., 3:4])


def load_optional(path: Path) -> Image.Image | None:
    try:
        return Image.open(path).convert("RGBA")
    except (FileNotFoundError, OSError):
        return None


def hero_stand_in() -> Image.Image:
    """主角素材不在时的替身：160 像素高的灰色剪影。"""
    im = Image.new("RGBA", (160, 160), (0, 0, 0, 0))
    dr = ImageDraw.Draw(im)
    dr.ellipse((68, 10, 92, 34), fill=(60, 56, 50, 230))
    dr.polygon([(62, 36), (98, 36), (110, 140), (50, 140)], fill=(60, 56, 50, 230))
    return im


def ingame_mock(items, path: Path) -> None:
    """游戏比例的模拟场景：1 贴图像素 = 1 画面像素 = 0.5 世界单位，主角用真实素材（160 像素帧）做比例参考。
    上左：夜里灯照下的宣纸（世界层 × 光照图，发光物最后叠加，与游戏同法）；
    上右：同一场景不打光，发光物改成染色后正常叠放，只为看清形状；
    下：涟漪环染冰蓝后按 30/60/120/240/480 像素直径缩放（双线性），以及 800 像素时的局部。"""
    Wm, Hm = V.dpx(900), V.dpx(600)

    def put(canvas, img, x, y, **kw):
        # 布局坐标按 1 倍像素写，乘密度后落到当前密度的画布上（贴图本身已是当前密度的尺寸）
        place(canvas, img, x * D, y * D, **kw)
    paper_img = load_optional(V.GROUND_DIR / "paper.png")
    if paper_img is not None:
        pt = np.asarray(paper_img.convert("RGB"), dtype=np.float64) / 255.0
        base = np.tile(pt, (2, 2, 1))[:Hm, :Wm].copy()
    else:
        base = np.broadcast_to(PAPER, (Hm, Wm, 3)).copy()
    hero, hero_k = load_optional(V.ASSETS / "hero" / "idle_SE_00.png"), 1.0
    hero_emit = load_optional(V.ASSETS / "hero" / "idle_SE_00_emit.png")
    if hero is None:  # 当前密度的主角还没出图：借 1 倍的放大，只作比例参考
        hero, hero_k = load_optional(V.OUT / "assets" / "hero" / "idle_SE_00.png"), D
        hero_emit = load_optional(V.OUT / "assets" / "hero" / "idle_SE_00_emit.png")
    if hero is None:
        hero, hero_k = hero_stand_in(), D
    shadow = load_optional(V.VFX_DIR / "shadow.png")
    light = load_optional(V.VFX_DIR / "light.png")
    wash = load_optional(V.GROUND_DIR / "wash_0.png")
    T = {k: v[0] for k, v in items.items()}
    A = {k: v[1] for k, v in items.items()}
    hx, hy = 450.0, 330.0
    wx, wy = 640.0, 420.0  # 落印点
    ring_r = items["ring"][2]["radius_px"]
    swords = [(hx + 95, hy - 135, -0.55, "sword"), (hx + 175, hy - 70, -0.2, "sword"), (hx - 150, hy - 110, math.pi + 0.35, "sword"),
              (hx + 70, hy + 60, 0.5, "sword_evo"), (hx - 70, hy - 190, -2.1, "sword"), (hx - 120, hy + 40, math.pi - 0.3, "sword_evo")]

    def draw_world(world):
        if wash is not None:
            put(world, wash, 600, 480, scale=1.4, anchor=(0.5, 0.5))
        # 地面：镇岳留下的地裂和印迹、一个圆相墨痕
        put(world, T["crack"], 250, 450, scale=1.2, anchor=A["crack"], alpha=0.9)
        put(world, T["seal_mark"], 250, 450, angle=math.radians(8), scale=(0.9, 0.9 * 0.7), anchor=A["seal_mark"], alpha=0.85)
        put(world, T["ring_ink"], 360, 530, scale=(0.75, 0.75 * 0.6), anchor=A["ring_ink"], alpha=0.75)
        # 拾取物
        for name, px, py in (("chest", 560, 525), ("soulbell", 615, 545), ("lotus", 505, 550)):
            if shadow is not None:
                put(world, shadow, px, py, scale=(T[name].width / 64 * 0.95, 0.5), anchor=(0.5, 0.5), alpha=0.8)
            put(world, T[name], px, py, anchor=A[name])
        # 已经落地的镇岳
        if shadow is not None:
            put(world, shadow, 215, 300, scale=(0.75, 0.9), anchor=(0.5, 0.5))
        put(world, T["seal_evo"], 215, 300, anchor=A["seal_evo"])
        # 主角
        if shadow is not None:
            put(world, shadow, hx, hy, scale=1.0, anchor=(0.5, 0.5))
        put(world, hero, hx, hy, anchor=(0.5, 0.875), scale=hero_k)
        # 正在落下的山印：地上的影子，石印还在半空
        if shadow is not None:
            put(world, shadow, wx, wy, scale=(0.7, 0.85), anchor=(0.5, 0.5), alpha=0.6)
        put(world, T["seal"], wx, wy - 60, anchor=A["seal"])
        # 纸鹤三只
        for name, px, py, ang in (("crane_0", 300, 180, -0.15), ("crane_2", 640, 160, 0.1), ("crane_evo_1", 720, 270, 0.35)):
            put(world, T[name], px, py, angle=ang, anchor=A[name])

    def draw_swords(canvas, lightmap=None):
        # 飞剑画在尾光之上（游戏里尾光在剑后面）；夜里按所在位置的光照染色
        for sx_, sy_, ang, name in swords:
            tint = None if lightmap is None else lightmap[int(sy_ * D), int(sx_ * D)]
            put(canvas, T[name], sx_, sy_, angle=ang, anchor=A[name], tint=tint)

    def draw_fx(canvas, mode, k_alpha=1.0):
        def fx(name, x, y, alpha=1.0, **kw):
            put(canvas, T[name], x, y, anchor=A[name], mode=mode, tint=col(TINTS[name]), alpha=alpha * k_alpha, **kw)

        fx("warn", wx, wy, 0.95, scale=(1.4, 1.4 * 0.62))
        fx("ring", hx, hy - 30, 0.5, scale=(140 * D / ring_r, 140 * D / ring_r * 0.62))
        fx("blast", 780, 500, 1.0, scale=1.3)
        for sx_, sy_, ang, _ in swords:
            fx("sword_trail", sx_, sy_, 0.8, angle=ang, scale=(1.6, 1.0))

    # 夜：世界层 × 光照图 + 发光物
    world = base.copy()
    draw_world(world)
    lm = np.broadcast_to(col(S.NIGHT_AMBIENT), world.shape).copy()
    if light is not None:
        put(lm, light, hx - 10, hy - 60, scale=900 * D / light.width, anchor=(0.5, 0.5), mode="add", tint=col(S.LANTERN_LIGHT))
    else:
        lm[:] = 1.0
    lm = np.clip(lm, 0, 1)
    lit = world * lm
    draw_fx(lit, "add")
    draw_swords(lit, lm)
    if hero_emit is not None:
        put(lit, hero_emit, hx, hy, anchor=(0.5, 0.875), mode="add", scale=hero_k)
    lit = np.clip(lit, 0, 1)
    # 白天：不打光，发光物染色后正常叠放
    day = base.copy()
    draw_world(day)
    draw_fx(day, "over", 0.85)
    draw_swords(day)
    day = np.clip(day, 0, 1)

    # 涟漪环缩放条
    # 涟漪环缩放条：直径按 1 倍屏幕像素写（世界单位 ×2），乘密度后是当前密度下的屏幕像素
    strip_h = V.dpx(520)
    strip = np.broadcast_to(col(S.NIGHT_AMBIENT), (strip_h, Wm * 2 + 12, 3)).copy()
    x = 20
    for dia in (30, 60, 120, 240, 480):
        put(strip, T["ring"], x + dia / 2, 30 + 240, scale=dia * D / (2 * ring_r), anchor=(0.5, 0.5), mode="add", tint=col(TINTS["ring"]))
        x += dia + 30
    big = np.broadcast_to(col(S.NIGHT_AMBIENT), (V.dpx(900), V.dpx(900), 3)).copy()
    put(big, T["ring"], 450, 450, scale=800 * D / (2 * ring_r), anchor=(0.5, 0.5), mode="add", tint=col(TINTS["ring"]))
    c0, c1, x0 = V.dpx(50), V.dpx(500), V.dpx(x + 10)
    crop = big[c0:c1, c0:c1]
    strip[V.dpx(40) : V.dpx(40) + crop.shape[0], x0 : x0 + crop.shape[1]] = crop[:, : max(0, strip.shape[1] - x0)]
    gap, top = 12, V.dpx(34)
    out = np.ones((Hm + top + strip_h + top, Wm * 2 + gap, 3)) * 0.1
    out[top : top + Hm, :Wm] = lit
    out[top : top + Hm, Wm + gap :] = day
    out[top + Hm + top :, :] = np.clip(strip, 0, 1)
    im = Image.fromarray(np.round(out * 255).astype(np.uint8), "RGB")
    dr = ImageDraw.Draw(im)
    f = V.font(V.dpx(15))
    ppu = V.PPU
    dr.text((8, 9), f"night: world x lightmap + additive FX (density {D:g}x: 1 texel = 1 px = {1 / S.PX_PER_UNIT:g} world unit)", fill="#DDDDDD", font=f)
    dr.text((Wm + gap + 8, 9), "same scene unlit; FX drawn tinted with normal blend (shape check only)", fill="#DDDDDD", font=f)
    dr.text((8, top + Hm + 8), f"ring.png tinted #6FB8FF, additive, bilinear: diameter 15 / 30 / 60 / 120 / 240 world units ({ppu} px/unit), and a crop at 400 units", fill="#DDDDDD", font=f)
    V.save_png(im, path)


# ============================================================== 主流程


def main() -> dict:
    t0 = time.perf_counter()
    WEAPON_DIR.mkdir(parents=True, exist_ok=True)
    REVIEW_DIR.mkdir(parents=True, exist_ok=True)
    items = build()
    t1 = time.perf_counter()
    files = {}
    sizes = {}
    for key, (img, anc, extra) in items.items():
        fn = f"{key}.png"
        V.save_png(img, WEAPON_DIR / fn)
        sizes[fn] = (WEAPON_DIR / fn).stat().st_size
        files[fn] = V.anchor_entry(img, anc, **extra)
    meta = {
        "name": "weapons",
        "generator": "art/post/weapon_textures.py",
        "format": "PNG RGBA，直通（非预乘）alpha；tint=true 的贴图 RGB 恒为白色，游戏里染色后叠加",
        "px_per_unit": V.PPU,
        "direction": "有方向的精灵（points=+x）旋转角 0 时指向屏幕右",
        "files": files,
    }
    (WEAPON_DIR / "meta.json").write_text(V.dump_json(meta), encoding="utf-8")
    review_sheet(items, REVIEW_DIR / "weapons_sheet.png", scale=max(1, int(round(3 / D))))
    ingame_mock(items, REVIEW_DIR / "weapons_ingame.png")
    total = sum(sizes.values())
    print(f"写出 {len(sizes)} 张贴图，共 {total / 1024:.1f} KB；生成 {t1 - t0:.1f} s，合计 {time.perf_counter() - t0:.1f} s")
    for k, v in sizes.items():
        print(f"  {k:22s} {v / 1024:6.1f} KB")
    return sizes


if __name__ == "__main__":
    main()
