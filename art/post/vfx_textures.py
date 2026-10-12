#!/usr/bin/env python3
"""提灯夜行 · 特效贴图与地面贴图（只用 Pillow + numpy）。

替换 src/render/placeholders.ts 里代码画的占位图，名字、尺寸、锚点保持一致。
颜色全部取自 art/style/style.py（只引用，不修改）。
所有随机数都用固定种子，重复运行结果逐字节相同，全程约 10 秒。

输出（直通 alpha 的 RGBA PNG；宣纸是不透明平铺图，存为 RGB）：
  art/out/assets/vfx/      light glow eyes shadow spark gem_0..2 flame_0..3 ink_0..2 lantern + meta.json
  art/out/assets/ground/   paper wash_0..2 grass_0..3 + meta.json
  art/out/review/          vfx_sheet.png  paper_tile_2x2.png  light_test.png

用法（在 lantern-next/ 目录下）：
  art/.venv/bin/python art/post/vfx_textures.py
  art/.venv/bin/python art/post/test_vfx_textures.py
"""

from __future__ import annotations

import json
import math
import re
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

ART = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ART / "style"))
import style as S  # noqa: E402

OUT = ART / "out"
VFX_DIR = OUT / "assets" / "vfx"
GROUND_DIR = OUT / "assets" / "ground"
REVIEW_DIR = OUT / "review"


# ============================================================== 基础工具


def col(h: str) -> np.ndarray:
    """hex 颜色 → 0..1 的 float 数组"""
    return np.array(S.hex_to_rgb(h), dtype=np.float64) / 255.0


WHITE = np.ones(3)


def smoothstep(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def fft_blur(a: np.ndarray, sigma, wrap: bool = False, angle: float = 0.0) -> np.ndarray:
    """高斯模糊（FFT 实现）。sigma 可以是 (沿 angle 方向, 垂直方向) 的各向异性二元组。
    wrap=True 时按周期边界处理（可平铺），否则四周补零后再裁回。"""
    if np.isscalar(sigma):
        s_long = s_short = float(sigma)
    else:
        s_long, s_short = map(float, sigma)
    if s_long <= 0 and s_short <= 0:
        return a.copy()
    pad = 0 if wrap else int(math.ceil(3 * max(s_long, s_short))) + 1
    b = np.pad(a, pad) if pad else a
    h, w = b.shape
    fy = np.fft.fftfreq(h)[:, None]
    fx = np.fft.rfftfreq(w)[None, :]
    ca, sa = math.cos(angle), math.sin(angle)
    f_long = fx * ca + fy * sa
    f_short = -fx * sa + fy * ca
    g = np.exp(-2.0 * math.pi**2 * ((s_long * f_long) ** 2 + (s_short * f_short) ** 2))
    out = np.fft.irfft2(np.fft.rfft2(b) * g, s=(h, w))
    return out[pad : pad + a.shape[0], pad : pad + a.shape[1]] if pad else out


def noise(rng: np.random.Generator, shape, sigma, angle: float = 0.0) -> np.ndarray:
    """周期（可平铺）的平滑噪声，标准差归一为 1。"""
    n = fft_blur(rng.standard_normal(shape), sigma, wrap=True, angle=angle)
    return (n - n.mean()) / (n.std() + 1e-12)


def fbm(rng, shape, sigmas, weights) -> np.ndarray:
    out = sum(w * noise(rng, shape, s) for s, w in zip(sigmas, weights))
    return out / (np.std(out) + 1e-12)


def rank01(a: np.ndarray) -> np.ndarray:
    """按名次映射到均匀分布 [0, 1)，保留空间结构（蓝噪声、笔毛纹理用）。"""
    flat = a.ravel()
    r = np.empty(flat.size)
    r[np.argsort(flat, kind="stable")] = np.arange(flat.size)
    return (r / flat.size).reshape(a.shape)


def downsample(a: np.ndarray, k: int) -> np.ndarray:
    if k == 1:
        return a
    h, w = a.shape[0] // k, a.shape[1] // k
    return a.reshape(h, k, w, k, *a.shape[2:]).mean(axis=(1, 3))


def grid(h: int, w: int, ss: int):
    """超采样网格，返回以“最终像素”为单位的像素中心坐标 (X, Y)。"""
    ys = (np.arange(h * ss) + 0.5) / ss
    xs = (np.arange(w * ss) + 0.5) / ss
    return np.meshgrid(xs, ys)


def bump_window(d):
    """(1-d²)²，d≥1 处为 0，边缘一阶导数也为 0（不会出现硬圈）。"""
    return np.clip(1.0 - d * d, 0.0, 1.0) ** 2


class Layer:
    """预乘 alpha 的绘图层：over 叠加，最后转直通 alpha。"""

    def __init__(self, h: int, w: int):
        self.p = np.zeros((h, w, 3))
        self.a = np.zeros((h, w))

    def over(self, color, alpha):
        alpha = np.clip(alpha, 0.0, 1.0)
        c = np.broadcast_to(np.asarray(color, dtype=np.float64), self.p.shape)
        self.p = c * alpha[..., None] + self.p * (1.0 - alpha[..., None])
        self.a = alpha + self.a * (1.0 - alpha)

    def down(self, k: int) -> "Layer":
        out = Layer(1, 1)
        out.p = downsample(self.p, k)
        out.a = downsample(self.a, k)
        return out

    def straight(self):
        a = self.a
        rgb = self.p / np.maximum(a, 1e-6)[..., None]
        return np.clip(rgb, 0.0, 1.0), np.clip(a, 0.0, 1.0)


def bleed_rgb(rgb: np.ndarray, a8: np.ndarray) -> np.ndarray:
    """把颜色向全透明区域扩展（style.ALPHA_BLEED_PX），避免双线性过滤时出现黑边/白边。"""
    w = a8.astype(np.float64) / 255.0
    out = rgb.copy()
    hole = a8 == 0
    if not hole.any() or not (~hole).any():
        return out
    filled = np.zeros_like(hole)
    for sigma in (1.0, 2.5, float(S.ALPHA_BLEED_PX) * 1.5, 24.0):
        den = fft_blur(w, sigma)
        num = np.stack([fft_blur(rgb[..., c] * w, sigma) for c in range(3)], -1)
        ok = hole & ~filled & (den > 1e-4)
        out[ok] = num[ok] / den[ok][:, None]
        filled |= ok
    rest = hole & ~filled
    if rest.any():
        out[rest] = (rgb * w[..., None]).sum((0, 1)) / max(w.sum(), 1e-9)
    return np.clip(out, 0.0, 1.0)


def to_rgba8(rgb, a, a8=None) -> Image.Image:
    """直通 alpha 的 RGBA8。rgb 可以是单个颜色。a8 给出时直接用（已抖动的 alpha）。"""
    if a8 is None:
        a8 = np.clip(np.round(a * 255.0), 0, 255).astype(np.uint8)
    rgb = np.broadcast_to(np.asarray(rgb, dtype=np.float64), a8.shape + (3,)).copy()
    rgb = bleed_rgb(rgb, a8)
    rgb8 = np.clip(np.round(rgb * 255.0), 0, 255).astype(np.uint8)
    return Image.fromarray(np.dstack([rgb8, a8]), "RGBA")


def save_png(img: Image.Image, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, optimize=True)


def blue_noise01(rng, shape) -> np.ndarray:
    """近似蓝噪声的均匀分布 [0,1)：白噪声去掉低频后按名次重排。用于抖动。"""
    n = rng.standard_normal(shape)
    hp = n - fft_blur(n, 1.2, wrap=True)
    hp = hp - 0.5 * (hp - fft_blur(hp, 0.6, wrap=True))  # 稍压最高频，减少棋盘感
    return rank01(hp)


def dither_alpha(f: np.ndarray, rng) -> np.ndarray:
    """±0.5 LSB 蓝噪声抖动量化：floor(f·255 + u)，u∈[0,1)。均值无偏，拉伸后不出色带。"""
    u = blue_noise01(rng, f.shape)
    return np.clip(np.floor(f * 255.0 + u), 0, 255).astype(np.uint8)


# ============================================================== 笔画


def arc_resample(pts: np.ndarray, n: int) -> np.ndarray:
    seg = np.hypot(*np.diff(pts, axis=0).T)
    s = np.concatenate([[0.0], np.cumsum(seg)])
    u = np.linspace(0.0, s[-1], n)
    return np.stack([np.interp(u, s, pts[:, 0]), np.interp(u, s, pts[:, 1])], -1)


def bezier(ctrl, n: int = 160) -> np.ndarray:
    """三次（或二次）贝塞尔曲线，按弧长重采样。"""
    c = np.asarray(ctrl, dtype=np.float64)
    t = np.linspace(0.0, 1.0, n * 4)[:, None]
    if len(c) == 3:
        p = (1 - t) ** 2 * c[0] + 2 * (1 - t) * t * c[1] + t**2 * c[2]
    else:
        p = (1 - t) ** 3 * c[0] + 3 * (1 - t) ** 2 * t * c[1] + 3 * (1 - t) * t**2 * c[2] + t**3 * c[3]
    return arc_resample(p, n)


def stroke_fields(X, Y, pts: np.ndarray, halfw: np.ndarray):
    """对一条中线计算每个像素到中线的关系，只在包围盒内计算。
    返回 dict：perp（带符号的横向距离）、over（超出端点的距离）、hw（该处半宽）、t（沿笔 0..1）、m（盒内掩码）。
    距离单位都是最终像素。"""
    n = len(pts)
    pad = float(halfw.max()) * 1.8 + 1.0
    xs, ys = X[0], Y[:, 0]
    cx = np.nonzero((xs >= pts[:, 0].min() - pad) & (xs <= pts[:, 0].max() + pad))[0]
    cy = np.nonzero((ys >= pts[:, 1].min() - pad) & (ys <= pts[:, 1].max() + pad))[0]
    shape = X.shape
    res = {
        "perp": np.zeros(shape),
        "over": np.full(shape, 1e9),
        "hw": np.full(shape, 1e-6),
        "t": np.zeros(shape),
    }
    if len(cx) == 0 or len(cy) == 0:
        return res
    sl = (slice(cy[0], cy[-1] + 1), slice(cx[0], cx[-1] + 1))
    P = np.stack([X[sl].ravel(), Y[sl].ravel()], -1)
    tan = np.gradient(pts, axis=0)
    tan /= np.linalg.norm(tan, axis=1, keepdims=True) + 1e-12
    nrm = np.stack([-tan[:, 1], tan[:, 0]], -1)
    idx = np.empty(len(P), dtype=np.int64)
    step = 6000
    for i in range(0, len(P), step):
        d2 = ((P[i : i + step, None, :] - pts[None, :, :]) ** 2).sum(-1)
        idx[i : i + step] = d2.argmin(1)
    dp = P - pts[idx]
    along = (dp * tan[idx]).sum(1)
    perp = (dp * nrm[idx]).sum(1)
    segl = float(np.hypot(*np.diff(pts, axis=0).T).mean())
    over = np.maximum(np.abs(along) - 0.5 * segl, 0.0)
    # 只有首尾采样点之外的部分才算“超出端点”
    over = np.where((idx == 0) | (idx == n - 1), over, 0.0)
    t = np.clip((idx + np.clip(along / max(segl, 1e-9), -0.5, 0.5)) / (n - 1), 0.0, 1.0)
    hshape = X[sl].shape
    res["perp"][sl] = perp.reshape(hshape)
    res["over"][sl] = over.reshape(hshape)
    res["hw"][sl] = np.maximum(halfw[idx], 1e-6).reshape(hshape)
    res["t"][sl] = t.reshape(hshape)
    return res


def bristle_texture(rng, ns: int = 40, nt: int = 256) -> np.ndarray:
    """笔毛纹理：横向变化快、沿笔方向拉长的噪声，按名次归一到 0..1。"""
    n = rng.standard_normal((ns, nt))
    n = fft_blur(n, (14.0, 0.7), angle=0.0)  # 第一维沿 x（t 方向）长、第二维短
    return rank01(n)


def sample_tex(tex: np.ndarray, s: np.ndarray, t: np.ndarray) -> np.ndarray:
    ns, nt = tex.shape
    si = np.clip(((s + 1.0) * 0.5 * (ns - 1)).round().astype(int), 0, ns - 1)
    ti = np.clip((t * (nt - 1)).round().astype(int), 0, nt - 1)
    return tex[si, ti]


def brush_stroke(X, Y, pts, halfw, rng, *, dry=0.55, dry_start=0.45, edge_jitter=0.16, aa=0.6, ss=1):
    """一笔写意笔触的覆盖度 0..1：两侧边缘各自抖动，越往笔尾越干（飞白）。"""
    f = stroke_fields(X, Y, pts, halfw)
    t = f["t"]
    nt = 256
    e_l = np.interp(t, np.linspace(0, 1, nt), fft_blur(rng.standard_normal(nt)[None, :], (5, 0))[0] * 3.0)
    e_r = np.interp(t, np.linspace(0, 1, nt), fft_blur(rng.standard_normal(nt)[None, :], (5, 0))[0] * 3.0)
    e = np.where(f["perp"] > 0, e_l, e_r)
    hw = f["hw"] * np.clip(1.0 + edge_jitter * e, 0.4, 1.6)
    dist = np.hypot(f["perp"], f["over"])
    soft = aa / ss
    cover = smoothstep(hw + soft, hw - soft, dist)
    s = np.clip(f["perp"] / hw, -1.0, 1.0)
    tex = bristle_texture(rng)
    b = sample_tex(tex, s, t)
    d = dry * smoothstep(dry_start, 1.0, t)
    ink = smoothstep(d - 0.06, d + 0.06, b)
    return cover * ink, f


# ============================================================== 光与辉光


def radial_d(size: int):
    c = size / 2.0
    yy, xx = np.mgrid[0:size, 0:size] + 0.5
    return np.hypot(xx - c, yy - c) / c


def make_light(rng) -> tuple[Image.Image, np.ndarray]:
    """灯光池：(1-d²)² 窗口 × 中心亮斑，边缘一阶导为 0，半径处恰好为 0。"""
    size = 128
    d = radial_d(size)
    core = np.exp(-((d / 0.30) ** 2))
    f = bump_window(d) * (0.62 + 0.38 * core)
    a8 = dither_alpha(f, rng)
    a8[d >= 1.0 - 0.5 / 64] = 0  # 圆周（含最外一圈像素）严格为 0
    return to_rgba8(WHITE, None, a8), f


def make_glow(rng) -> Image.Image:
    """更紧的辉光：亮核 + 短裙边，用来给自发光物体烘一点泛光。"""
    d = radial_d(64)
    f = np.clip(1.0 - d * d, 0, 1) ** 3 * (0.22 + 0.78 * np.exp(-((d / 0.2) ** 2)))
    a8 = dither_alpha(f, rng)
    a8[d >= 1.0 - 0.5 / 32] = 0
    return to_rgba8(WHITE, None, a8)


def make_spark() -> Image.Image:
    ss = 8
    X, Y = grid(12, 12, ss)
    r = np.hypot(X - 6.0, Y - 6.0)
    f = bump_window(r / 6.0) * (0.72 * np.exp(-((r / 1.25) ** 2)) + 0.28 * np.exp(-((r / 3.0) ** 2)))
    # 很淡的十字星芒，让火星在暗处有一点“闪”的感觉
    star = (np.exp(-((X - 6.0) ** 2) / 0.18) + np.exp(-((Y - 6.0) ** 2) / 0.18)) * np.exp(-((r / 3.2) ** 2)) * 0.22
    f = np.clip(f + star * bump_window(r / 6.0), 0, 1)
    a = downsample(f, ss)
    a = a / a.max()
    return to_rgba8(WHITE, a)


def make_eyes() -> Image.Image:
    """两点妖眼：杏仁形亮核 + 柔和光晕，内眼角略低，显得凶。"""
    ss = 8
    X, Y = grid(10, 24, ss)
    total = np.zeros_like(X)
    for cx, sgn in ((6.0, 1.0), (18.0, -1.0)):
        ang = math.radians(12.0) * sgn  # 左眼顺时针、右眼逆时针，内眼角朝下
        dx, dy = X - cx, Y - 5.0
        u = dx * math.cos(ang) + dy * math.sin(ang)
        v = -dx * math.sin(ang) + dy * math.cos(ang)
        # 杏仁形：越靠两端越细
        half_h = 1.35 * np.sqrt(np.clip(1.0 - (u / 2.7) ** 2, 0, 1)) ** 1.3
        core = smoothstep(0.25, -0.25, np.abs(v) - half_h) * (np.abs(u) < 2.9)
        r = np.hypot(u / 1.25, v)
        halo = 0.62 * np.exp(-((r / 2.3) ** 2)) * bump_window(np.hypot(dx, dy) / 5.0)
        total = np.maximum(total, np.clip(core + halo, 0, 1))
    return to_rgba8(WHITE, downsample(total, ss))


# ============================================================== 影子、墨点


def angular_noise(rng, theta, harmonics=(2, 3, 4, 5, 7), amp=0.08):
    out = np.zeros_like(theta)
    for k in harmonics:
        out += rng.normal(0, amp / math.sqrt(k)) * np.cos(k * theta + rng.uniform(0, 2 * math.pi))
    return out


def make_shadow(rng) -> Image.Image:
    """接触阴影：焦墨，最大 alpha≈0.45，湿墨边，略不规则。"""
    ss, w, h = 4, 64, 24
    X, Y = grid(h, w, ss)
    dx, dy = (X - 32.0) / 27.0, (Y - 12.3) / 9.6
    # 超椭圆（指数 2.4）：两端比普通椭圆圆润，不会显得尖
    rho = (np.abs(dx) ** 2.4 + np.abs(dy) ** 2.4) ** (1 / 2.4)
    th = np.arctan2(dy, dx)
    # 不用 2 次谐波（会把椭圆拉尖成叶子形），只让轮廓轻微起伏
    rho = rho / (1.0 + angular_noise(rng, th, harmonics=(3, 4, 5, 6, 8), amp=0.07))
    n_lo = noise(rng, X.shape, 3.0 * ss)
    n_hi = noise(rng, X.shape, 0.6 * ss)
    edge = smoothstep(1.0, 0.80, rho + 0.03 * n_lo)
    rim = 0.06 * np.exp(-(((rho - 0.86) / 0.07) ** 2))  # 墨水干在边缘，略深一圈
    body = 0.30 + 0.11 * np.exp(-((rho / 0.5) ** 2)) + 0.025 * n_lo + 0.012 * n_hi
    # 外侧极淡的洇痕
    fringe = 0.05 * smoothstep(1.18, 0.95, rho) * smoothstep(0.2, 0.8, rank01(noise(rng, X.shape, (2.2 * ss, 0.5 * ss), angle=0.3)))
    a = np.maximum(edge * (body + rim), fringe)
    a = downsample(a, ss)
    a = np.clip(a, 0, 0.45)
    a[0, :] = a[-1, :] = 0
    a[:, 0] = a[:, -1] = 0
    return to_rgba8(col(S.INK["jiao"]), a)


def make_ink(rng) -> Image.Image:
    """飞溅墨点：主墨团带尖刺 + 卫星墨滴 + 细雾点。"""
    ss, size = 8, 20
    X, Y = grid(size, size, ss)
    cx, cy = 10.0 + rng.uniform(-0.6, 0.6), 10.0 + rng.uniform(-0.6, 0.6)
    dx, dy = X - cx, Y - cy
    rho = np.hypot(dx, dy)
    th = np.arctan2(dy, dx)
    r0 = rng.uniform(3.3, 4.2)
    R = r0 * (1.0 + angular_noise(rng, th, harmonics=(2, 3, 4, 5, 6, 8, 11), amp=0.18))
    n_spk = rng.integers(3, 6)
    spikes = []
    for _ in range(n_spk):
        a0 = rng.uniform(-math.pi, math.pi)
        wd = rng.uniform(0.10, 0.22)
        ln = rng.uniform(1.35, 1.95)
        spikes.append((a0, ln))
        dth = np.angle(np.exp(1j * (th - a0)))
        R = np.maximum(R, r0 * (1.0 + (ln - 1.0) * np.exp(-((dth / wd) ** 2))))
    m = smoothstep(1.0 + 0.04, 1.0 - 0.04, rho / R)
    lay = np.zeros_like(X)
    # 湿墨：中间略透，边缘积墨
    pool = 0.86 + 0.14 * smoothstep(0.55, 0.95, rho / R) + 0.05 * noise(rng, X.shape, 1.2 * ss)
    lay = np.maximum(lay, m * np.clip(pool, 0, 1))
    # 卫星墨滴：一部分顺着尖刺方向飞出去，拖一点尾巴
    n_sat = rng.integers(4, 8)
    for i in range(n_sat):
        if i < len(spikes) and rng.random() < 0.8:
            a0 = spikes[i][0] + rng.normal(0, 0.12)
            dist = r0 * spikes[i][1] + rng.uniform(1.2, 2.8)
        else:
            a0 = rng.uniform(-math.pi, math.pi)
            dist = rng.uniform(5.5, 8.2)
        dist = min(dist, 8.3)
        rr = rng.uniform(0.45, 1.35)
        px, py = cx + dist * math.cos(a0), cy + dist * math.sin(a0)
        px, py = np.clip(px, 1.6, size - 1.6), np.clip(py, 1.6, size - 1.6)
        u = (X - px) * math.cos(a0) + (Y - py) * math.sin(a0)
        v = -(X - px) * math.sin(a0) + (Y - py) * math.cos(a0)
        elong = rng.uniform(1.0, 1.9)
        uu = np.where(u < 0, u / (rr * elong), u / rr)  # 朝中心一侧拉长成泪滴
        lay = np.maximum(lay, smoothstep(1.06, 0.92, np.hypot(uu, v / rr)))
    # 细雾点
    for _ in range(rng.integers(5, 10)):
        a0 = rng.uniform(-math.pi, math.pi)
        dist = rng.uniform(4.0, 8.8)
        px = np.clip(cx + dist * math.cos(a0), 1.2, size - 1.2)
        py = np.clip(cy + dist * math.sin(a0), 1.2, size - 1.2)
        rr = rng.uniform(0.22, 0.45)
        lay = np.maximum(lay, smoothstep(rr + 0.1, rr - 0.1, np.hypot(X - px, Y - py)))
    a = downsample(lay, ss)
    a[0, :] = a[-1, :] = a[:, 0] = a[:, -1] = 0
    return to_rgba8(col(S.INK["jiao"]), a)


# ============================================================== 魂火、灯火、灯笼芯


def make_gem(rng, size: int, variant: int) -> Image.Image:
    """魂火：小泪滴形鬼火，下部圆肚是亮核，火舌 S 形甩向一侧。白色，游戏里染 SOUL_LIGHT。"""
    ss = 8
    X, Y = grid(size, size, ss)
    c = size / 2.0
    s = size / 26.0
    rb = 4.8 * s  # 下部圆头半径
    by = c + 3.6 * s  # 圆头中心
    lean = (1, -1, 1)[variant]
    curl = (1.0, 1.2, 1.5)[variant]  # 越大的魂火，火舌甩得越开
    # 主火舌：先略向反方向弯，再把尖甩出去（S 形）
    tip = (c + lean * 2.4 * curl * s, c - 10.0 * s)
    pts = bezier([(c, by), (c - lean * 1.8 * curl * s, by - 5.5 * s), (c + lean * 2.8 * curl * s, by - 9.5 * s), tip], 120)
    tt = np.linspace(0, 1, len(pts))
    f = stroke_fields(X, Y, pts, rb * (1.0 - tt) ** 1.1)
    m = np.clip(1.0 - np.hypot(f["perp"], f["over"]) / f["hw"], 0, 1)
    m = np.maximum(m, np.clip(1.0 - np.hypot(X - c, Y - by) / rb, 0, 1))
    m = np.clip(m + 0.06 * noise(rng, X.shape, 1.3 * ss) * (m > 0), 0, 1)
    body = smoothstep(0.0, 0.2, m) * 0.6
    core = smoothstep(0.25, 0.8, m) * np.exp(-(np.hypot((X - c) / (0.9 * rb), (Y - by + 1.0 * s) / (1.25 * rb)) ** 2))
    inner = smoothstep(0.55, 0.85, m) * 0.3  # 火舌里一道更亮的细芯
    hard = smoothstep(0.0, 0.1, m)
    halo = 0.32 * fft_blur(hard, 1.5 * s * ss) * (1.0 - hard)  # 外圈微光
    a = np.clip(body + 0.55 * core + inner + halo, 0, 1)
    a *= bump_window(np.hypot(X - c, Y - c) / (c * 1.02))
    a = downsample(a, ss)
    a = a / a.max()
    return to_rgba8(WHITE, a)


FLAME_STOPS = [
    (0.00, S.mix(S.ACCENT["zhusha"], S.INK["nong"], 0.40)),
    (0.10, S.ACCENT["zhusha"]),
    (0.30, S.mix(S.ACCENT["zhusha"], S.FLAME_LIGHT, 0.6)),
    (0.48, S.FLAME_LIGHT),
    (0.66, S.ACCENT["tenghuang"]),
    (0.86, S.mix(S.ACCENT["tenghuang"], "#FFFFFF", 0.45)),
    (1.00, S.mix(S.ACCENT["tenghuang"], "#FFFFFF", 0.70)),
]
FLAME_INK = S.mix(S.ACCENT["zhusha"], S.INK["jiao"], 0.7)


def ramp(h: np.ndarray, stops) -> np.ndarray:
    xs = [s[0] for s in stops]
    cs = np.stack([col(s[1]) for s in stops])
    return np.stack([np.interp(h, xs, cs[:, i]) for i in range(3)], -1)


def make_flames() -> list[Image.Image]:
    """环绕主角的灯火：4 帧循环。几笔向上挑的火舌叠成：藤黄芯、朱砂边，火舌尖收笔带一点焦墨和飞白。"""
    ss, w, h = 8, 32, 48
    X, Y = grid(h, w, ss)
    rng = np.random.default_rng(4100)
    # 两张噪声按相位旋转混合（cos·A + sin·B），4 帧首尾相接
    n1a, n1b = noise(rng, X.shape, 1.6 * ss), noise(rng, X.shape, 1.6 * ss)
    sa, sb = (noise(rng, X.shape, (5.0 * ss, 0.45 * ss), angle=math.pi / 2) for _ in range(2))
    bris = [bristle_texture(np.random.default_rng(4200 + i)) for i in range(4)]
    frames = []
    for fi in range(4):
        ph = 2 * math.pi * fi / 4
        cph, sph = math.cos(ph), math.sin(ph)
        edge_n = n1a * cph + n1b * sph
        streak = sa * cph + sb * sph
        sw = lambda a, k: a * math.sin(ph + k)  # noqa: E731  每条火舌各自的摆动
        tongues = [
            # (根部, 控制点1, 控制点2, 尖端, 根部半宽, 权重)
            ((16.0, 34.0), (14.6 + sw(1.2, 0), 25.0), (18.4 + sw(2.4, 1.0), 14.0), (14.6 + sw(3.0, 0.4), 3.4 + 1.4 * math.cos(2 * ph)), 7.6, 1.0),
            ((12.4, 33.0), (9.0, 27.0), (7.2 + sw(1.6, 2.2), 21.0), (9.2 + sw(2.4, 2.6), 12.6 + 2.0 * math.cos(ph + 1.0)), 4.0, 0.92),
            ((19.8, 33.0), (23.0, 28.5), (24.6 + sw(1.4, 4.0), 22.5), (22.4 + sw(2.2, 4.4), 15.0 + 2.0 * math.cos(ph + 3.0)), 3.6, 0.92),
            ((17.6, 27.0), (21.0, 21.0), (19.0, 15.0), (22.4 + sw(1.4, 5.0), 9.0 + 1.5 * math.sin(ph + 0.8)), 2.3, 0.85),
        ]
        m = np.zeros_like(X)
        heat = np.zeros_like(X)
        tip_t = np.zeros_like(X)
        dry = np.ones_like(X)
        for k, (p0, p1, p2, p3, hw0, wt) in enumerate(tongues):
            pts = bezier([p0, p1, p2, p3], 140)
            tt = np.linspace(0, 1, len(pts))
            halfw = hw0 * (1.0 - tt) ** 0.95 * (0.85 + 0.15 * np.sin(np.pi * np.minimum(tt * 2.5, 1.0)))
            f = stroke_fields(X, Y, pts, halfw)
            mk = np.clip(1.0 - np.hypot(f["perp"], f["over"]) / f["hw"], 0, 1) * wt
            sel = mk > m
            m = np.where(sel, mk, m)
            heat = np.maximum(heat, mk * (1.0 - 0.75 * f["t"] ** 0.8))  # 越往火舌尖越凉
            tip_t = np.where(sel, f["t"], tip_t)
            b = sample_tex(bris[k], np.clip(f["perp"] / f["hw"], -1, 1), f["t"])
            dk = 0.6 * smoothstep(0.5, 1.0, f["t"])
            dry = np.where(sel, smoothstep(dk - 0.08, dk + 0.08, b), dry)
        # 下部圆肚
        base = np.clip(1.0 - np.hypot((X - 16.0) / 8.4, (Y - 31.6 - 0.4 * math.sin(2 * ph)) / 8.2), 0, 1)
        sel = base > m
        m = np.where(sel, base, m)
        heat = np.maximum(heat, base)
        tip_t = np.where(sel, 0.0, tip_t)
        dry = np.where(sel, 1.0, dry)
        inside = smoothstep(0.0, 0.04, m)  # 噪声只在形状内部和边上起作用，不在外面生出墨点
        mn = m + (0.07 * edge_n + 0.05 * streak) * inside - 0.015
        cover = smoothstep(0.0, 0.10, mn) * dry
        # 边上顺着笔毛方向断开几丝
        cover *= 1.0 - 0.45 * smoothstep(0.9, 1.8, streak) * smoothstep(0.35, 0.05, m)
        core_glow = np.exp(-(((X - 16.0) / 4.0) ** 2 + ((Y - 30.0) / 6.0) ** 2))
        heat = heat * 0.9 + 0.3 * core_glow * inside + 0.10 * streak * inside + 0.05 * edge_n * inside
        rgb = ramp(np.clip(heat, 0, 1), FLAME_STOPS)
        inkiness = smoothstep(0.70, 0.97, tip_t) * 0.8  # 火舌尖收笔带一点焦墨
        rgb = rgb * (1 - inkiness[..., None]) + col(FLAME_INK) * inkiness[..., None]
        alpha = np.clip(cover * (0.82 + 0.18 * smoothstep(0.1, 0.45, heat)), 0, 1)
        lay = Layer(*X.shape)
        lay.over(rgb, alpha)
        lay = lay.down(ss)
        rgb_s, a = lay.straight()
        a[0, :] = a[-1, :] = a[:, 0] = a[:, -1] = 0
        frames.append(to_rgba8(rgb_s, a))
    return frames


def make_lantern() -> Image.Image:
    """灯笼芯：暖光椭圆，中心偏白，隐约几条竹骨，叠加混合。"""
    ss, w, h = 8, 20, 24
    X, Y = grid(h, w, ss)
    dx, dy = (X - 10.0) / 7.0, (Y - 12.0) / 8.8
    rho = np.hypot(dx, dy)
    body = smoothstep(1.0, 0.72, rho)
    # 竹骨：球面上的经线
    u = np.clip(dx / np.sqrt(np.clip(1 - dy * dy, 0.05, 1)), -1, 1)
    lon = np.arcsin(u)
    ribs = 1.0 - 0.22 * sum(np.exp(-(((lon - k) / 0.09) ** 2)) for k in (-0.95, 0.0, 0.95))
    rims = 1.0 - 0.25 * (np.exp(-(((dy + 0.86) / 0.07) ** 2)) + np.exp(-(((dy - 0.86) / 0.07) ** 2)))
    inten = body * (0.78 + 0.22 * np.exp(-((rho / 0.55) ** 2))) * ribs * rims
    halo = 0.30 * np.exp(-np.maximum(rho - 0.85, 0) / 0.18) * bump_window(np.hypot((X - 10) / 10.0, (Y - 12) / 12.0))
    a = np.clip(np.maximum(inten, halo), 0, 1)
    warm = col(S.LANTERN_LIGHT)
    hot = col(S.mix(S.LANTERN_LIGHT, "#FFFFFF", 0.6))
    edge = col(S.mix(S.LANTERN_LIGHT, S.FLAME_LIGHT, 0.5))
    t_hot = np.exp(-((rho / 0.5) ** 2))[..., None]
    t_edge = smoothstep(0.6, 1.1, rho)[..., None]
    rgb = warm * (1 - t_hot) + hot * t_hot
    rgb = rgb * (1 - t_edge) + edge * t_edge
    lay = Layer(*X.shape)
    lay.over(rgb, a)
    lay = lay.down(ss)
    rgb_s, a = lay.straight()
    a[0, :] = a[-1, :] = a[:, 0] = a[:, -1] = 0
    return to_rgba8(rgb_s, a)


# ============================================================== 地面：宣纸


def splat_lines(acc: np.ndarray, xs: np.ndarray, ys: np.ndarray, wts: np.ndarray) -> None:
    """双线性把采样点累加到周期画布上（越界自动环绕，保证可平铺）。"""
    h, w = acc.shape
    x0 = np.floor(xs).astype(np.int64)
    y0 = np.floor(ys).astype(np.int64)
    fx, fy = xs - x0, ys - y0
    flat = np.zeros(h * w)
    for oy, ox, ww in ((0, 0, (1 - fx) * (1 - fy)), (0, 1, fx * (1 - fy)), (1, 0, (1 - fx) * fy), (1, 1, fx * fy)):
        idx = ((y0 + oy) % h) * w + ((x0 + ox) % w)
        flat += np.bincount(idx, weights=wts * ww, minlength=h * w)
    acc += flat.reshape(h, w)


def fibre_layer(rng, size: int, ss: int, count: int, length, amp, sigma: float, wobble: float) -> np.ndarray:
    """一组纤维：随机方向、缓慢弯曲的细线，两端渐隐。返回最终尺寸的强度场（周期）。"""
    H = size * ss
    step = 0.5  # 采样步长（超采样像素）
    sig_hi = sigma * ss
    acc = np.zeros((H, H))
    xs_all, ys_all, w_all = [], [], []
    for _ in range(count):
        L = rng.uniform(*length) * ss
        n = max(int(L / step), 4)
        x0, y0 = rng.uniform(0, H), rng.uniform(0, H)
        th0 = rng.uniform(0, 2 * math.pi)
        dth = np.cumsum(rng.normal(0, wobble, n))
        dth = fft_blur(dth[None, :], (6, 0))[0]
        th = th0 + dth
        xs = x0 + np.cumsum(np.cos(th)) * step
        ys = y0 + np.cumsum(np.sin(th)) * step
        tt = np.linspace(0, 1, n)
        a = rng.uniform(*amp)
        prof = np.sin(np.pi * tt) ** 0.6 * (0.7 + 0.3 * np.cos(tt * rng.uniform(4, 12) + rng.uniform(0, 6)))
        lam = a * math.sqrt(2 * math.pi) * sig_hi  # 使模糊后线芯强度≈a
        xs_all.append(xs)
        ys_all.append(ys)
        w_all.append(prof * lam * step)
    splat_lines(acc, np.concatenate(xs_all), np.concatenate(ys_all), np.concatenate(w_all))
    acc = fft_blur(acc, sig_hi, wrap=True)
    return downsample(acc, ss)


def make_paper() -> Image.Image:
    """512² 可无缝平铺的宣纸：云絮状的浓淡、长短纤维、极细的纸粒、零星杂质。
    全部在周期域里生成（FFT 噪声 + 环绕绘制的纤维），所以四边自然接缝。"""
    size = 512
    rng = np.random.default_rng(1200)
    sh = (size, size)
    # 正值 = 朝 PAPER_SHADOW 方向变暗（单位：PAPER→PAPER_SHADOW 的整段色差）
    dark = np.zeros(sh)
    # 负值 = 朝更白更透的纸色变亮
    light_dir = col("#F8F2E4") - col(S.PAPER)
    # 1. 大块云状浓淡（纸浆厚薄不匀）
    cloud = fbm(rng, sh, (70.0, 30.0, 12.0), (0.3, 0.7, 0.5))  # 最低频压低，平铺时不易看出重复
    dark += 0.13 * cloud
    # 2. 中尺度的絮状纹（宣纸迎光看到的“云纹”）
    floc = noise(rng, sh, 3.2) + 0.6 * noise(rng, sh, 6.0)
    floc = floc / floc.std()
    dark += 0.07 * np.tanh(floc)
    # 3. 长纤维（深）与亮纤维（半透明的白丝）
    dark += fibre_layer(rng, size, 2, 150, (40, 150), (0.14, 0.40), 0.45, 0.035)
    dark -= fibre_layer(rng, size, 2, 110, (25, 100), (0.12, 0.30), 0.6, 0.05)
    # 4. 大量短细纤维，构成纸面的“毛”
    dark += fibre_layer(rng, size, 2, 900, (4, 18), (0.03, 0.10), 0.4, 0.08)
    dark -= fibre_layer(rng, size, 2, 700, (4, 16), (0.03, 0.09), 0.45, 0.08)
    # 5. 纸粒
    grain = noise(rng, sh, 0.55)
    dark += 0.035 * grain
    # 6. 零星杂质（草屑、深色小点）
    specks = np.zeros((size * 2, size * 2))
    xs = rng.uniform(0, size * 2, 22)
    ys = rng.uniform(0, size * 2, 22)
    splat_lines(specks, xs, ys, rng.uniform(4.0, 9.0, 22))
    specks = downsample(fft_blur(specks, 1.1, wrap=True), 2)
    dark += specks
    dark += fibre_layer(rng, size, 2, 6, (6, 14), (0.25, 0.4), 0.45, 0.12)

    base = col(S.PAPER)
    dvec = col(S.PAPER_SHADOW) - base
    pos = np.clip(dark, 0, None)[..., None]
    neg = np.clip(-dark, 0, None)[..., None]
    rgb = base + pos * dvec + neg * light_dir * 1.6
    rgb8 = np.clip(np.round(rgb * 255.0), 0, 255).astype(np.uint8)
    return Image.fromarray(rgb8, "RGB")


# ============================================================== 地面：淡墨晕染


def make_wash(seed: int, lobes, base_alpha: float, *, tilt=(0.0, 0.0), sweep: float | None = None) -> Image.Image:
    """水墨晕染：淡墨大块。边缘有的地方墨干后积成一道深痕、带毛茸茸的洇边（硬边），
    有的地方是湿接湿的柔边；内部一侧浓一侧淡，带淡淡的水渍纹。sweep 给出时，沿该方向的尾端做干笔飞白。"""
    ss, w, h = 2, 240, 160
    rng = np.random.default_rng(seed)
    X, Y = grid(h, w, ss)
    sh = X.shape
    nx, ny = (X - w / 2) / (w / 2), (Y - h / 2) / (h / 2)
    wx = nx + 0.08 * noise(rng, sh, 30 * ss) + 0.05 * noise(rng, sh, 12 * ss) + 0.02 * noise(rng, sh, 5 * ss)
    wy = ny + 0.08 * noise(rng, sh, 30 * ss) + 0.05 * noise(rng, sh, 12 * ss) + 0.02 * noise(rng, sh, 5 * ss)
    F = np.zeros(sh)
    for cx, cy, rx, ry, wt in lobes:
        F += wt * np.exp(-(((wx - cx) / rx) ** 2 + ((wy - cy) / ry) ** 2))
    # 边缘的分形起伏：大弯里套小弯，纸纤维让边线再碎一点
    F += 0.06 * noise(rng, sh, 9 * ss) + 0.035 * noise(rng, sh, 3 * ss) + 0.012 * noise(rng, sh, 1.2 * ss)
    # 细噪声会在边上掐出几个像素的小洞，看着像瑕疵：取 max(F, 模糊F-余量)，相当于软的闭运算，
    # 只填窄缝和小洞，凸出去的毛边不受影响
    F = np.maximum(F, fft_blur(F, 2.5 * ss) - 0.004)
    gy, gx = np.gradient(F, 1.0 / ss)
    # 近似的到边缘距离（最终像素），内正外负。梯度模先平滑再设下限，避免鞍点处距离发散出小洞
    gm = np.maximum(fft_blur(np.hypot(gx, gy), 2.0 * ss), 0.006)
    sd = np.clip((F - 0.5) / gm, -40, 40)
    # 软硬边：soft=1 是湿接湿的柔边，0 是干后积墨的硬边
    soft = smoothstep(-0.1, 0.9, noise(rng, sh, 20 * ss))
    wtr = 0.6 + 10.0 * soft
    inside = smoothstep(-0.5 * wtr, 0.5 * wtr, sd)
    # 内部：一侧浓一侧淡 + 湿画法的起伏 + 细颗粒
    interior = base_alpha * (1.0 + 0.35 * (tilt[0] * nx + tilt[1] * ny))
    interior = interior + 0.03 * noise(rng, sh, 10 * ss) + 0.012 * noise(rng, sh, 4 * ss) + 0.008 * noise(rng, sh, 0.5 * ss)
    interior -= 0.025 * smoothstep(12.0, 2.0, sd) * (1.0 - soft)  # 硬边内侧被带走的一条淡带
    # 墨聚的地方（叶瓣中心）再深一层，柔边过渡，出浓淡层次
    interior += 0.07 * smoothstep(0.62, 0.95, F + 0.08 * noise(rng, sh, 6 * ss))
    # 积墨的边：宽度和浓度沿边变化
    pool_w = 1.4 + 1.0 * smoothstep(-1, 1, noise(rng, sh, 10 * ss))
    pool_k = smoothstep(-1.0, 1.2, noise(rng, sh, 7 * ss))
    pool = 0.22 * pool_k * (1.0 - soft) ** 1.5 * np.exp(-np.maximum(sd, 0) / pool_w)
    # 水渍纹（backrun）：内部另一个场的等值线，很淡
    G = noise(rng, sh, 8.0 * ss) + 0.4 * noise(rng, sh, 2.5 * ss)
    tide = 0.025 * np.exp(-(((G - 0.7) / 0.12) ** 2)) * (G < 0.75) * smoothstep(4, 12, sd)
    # 洇边：顺着纸纤维往外渗，长短不一；只在硬边处明显
    fib = rank01(np.maximum.reduce([noise(rng, sh, (3.0 * ss, 0.35 * ss), angle=a) for a in (0.2, 1.25, 2.3)]))
    reach = 0.6 + 3.4 * fib**2
    bleed = 0.10 * (0.4 + 0.6 * pool_k) * (1.0 - 0.8 * soft) * np.exp(np.minimum(sd, 0) / reach) * smoothstep(0.15, 0.75, fib)
    a = inside * (interior + pool + tide) + (1.0 - inside) * bleed
    if sweep is not None:
        # 侧锋扫过去，尾端墨尽，留下顺笔方向的飞白
        along = ((X - w / 2) * math.cos(sweep) + (Y - h / 2) * math.sin(sweep)) / 80.0
        st = rank01(noise(rng, sh, (16 * ss, 0.7 * ss), angle=sweep))
        a *= 1.0 - 0.75 * smoothstep(0.15, 0.85, along) * smoothstep(0.3, 0.7, st)
    a *= smoothstep(1.0, 0.86, np.maximum(np.abs(nx), np.abs(ny)))  # 保证贴图四边为 0
    a = downsample(np.clip(a, 0, 0.35), ss)
    a[0, :] = a[-1, :] = a[:, 0] = a[:, -1] = 0
    return to_rgba8(col(S.INK["zhong"]), a)


WASHES = [
    # (种子, 叶瓣 [(cx, cy, rx, ry, 权重)...], 内部浓度, 关键字参数)
    # 0：淡墨，一大片横卧的水洼
    (3101, [(-0.30, 0.05, 0.42, 0.50, 1.0), (0.28, -0.06, 0.40, 0.46, 0.95), (0.0, 0.25, 0.36, 0.30, 0.6), (-0.05, -0.30, 0.30, 0.25, 0.5)], 0.14, {"tilt": (-0.5, 0.3)}),
    # 1：清墨，两汪相连，右上角另有一小滴
    (3202, [(-0.42, -0.05, 0.30, 0.48, 1.0), (0.38, 0.08, 0.32, 0.44, 0.95), (0.0, 0.05, 0.25, 0.22, 0.55), (0.62, -0.50, 0.10, 0.13, 0.95)], 0.10, {"tilt": (0.4, 0.0)}),
    # 2：淡墨，侧锋从左下扫向右上，尾端飞白
    (3303, [(-0.60, 0.34, 0.18, 0.30, 0.95), (-0.32, 0.18, 0.26, 0.40, 1.0), (0.0, 0.0, 0.28, 0.40, 1.0), (0.32, -0.16, 0.24, 0.32, 0.9), (0.60, -0.32, 0.16, 0.22, 0.75)], 0.15, {"tilt": (-0.6, 0.2), "sweep": math.atan2(-56.0, 154.0)}),
]


# ============================================================== 地面：草


GRASS_SPECS = [
    # (种子, 叶数, 石绿叶数, 叶长范围, 是否加苔点)
    (5101, 6, 0, (24, 38), True),
    (5202, 5, 1, (20, 34), False),
    (5303, 7, 2, (14, 28), True),
    (5404, 4, 3, (22, 38), True),
]


def make_grass(seed: int, n: int, n_green: int, hrange, dots: bool) -> Image.Image:
    """写意草丛：几笔撇出的叶子，钉头鼠尾，外侧的叶子弯下来，里面的互相交叉；
    笔尾飞白；后面的叶子墨淡，前面的浓，个别叶子调了石绿。"""
    ss, w, h = 6, 48, 40
    rng = np.random.default_rng(seed)
    X, Y = grid(h, w, ss)
    lay = Layer(*X.shape)
    # 根部一抹淡墨，把草“种”在地上
    smudge = 0.16 * bump_window(np.hypot((X - 24.0) / 12.0, (Y - 38.6) / 2.3)) * smoothstep(-1.5, 1.5, noise(rng, X.shape, 1.5 * ss) + 0.8)
    lay.over(col(S.INK["dan"]), smudge)
    green = set(rng.choice(n, size=n_green, replace=False).tolist()) if n_green else set()
    slots = np.sort(rng.uniform(-1.0, 1.0, n))
    slots = 0.5 * slots + 0.5 * np.linspace(-1, 1, n)  # 大致均匀排开，避免挤成一束
    order = rng.permutation(n)  # 先画的在后面，墨淡一些
    for rank_i, i in enumerate(order):
        u = slots[i]
        ang = 0.85 * u + rng.normal(0, 0.12)
        if abs(u) > 0.45:
            bend = rng.uniform(0.45, 0.9) * np.sign(ang)  # 外侧的叶子向外弯垂
        else:
            bend = rng.uniform(0.1, 0.45) * rng.choice([-1.0, 1.0])  # 里面的叶子随意弯，会交叉
        L = rng.uniform(*hrange) * (1.0 - 0.2 * abs(u))
        root = np.array([24.0 + 6.0 * u + rng.normal(0, 1.2), 39.0 - rng.uniform(0.0, 1.0)])
        d = np.array([math.sin(ang), -math.cos(ang)])
        side = np.array([-d[1], d[0]])
        for _ in range(20):  # 叶子出框就缩短
            ctrl = [root, root + d * L * 0.45, root + d * L * 0.85 + side * bend * L * 0.25, root + d * L * 0.95 + side * bend * L * 0.6]
            pts = bezier(ctrl, 160)
            if pts[:, 0].min() >= 2.0 and pts[:, 0].max() <= w - 2.0 and pts[:, 1].min() >= 2.0:
                break
            L *= 0.92
        tt = np.linspace(0, 1, len(pts))
        wmax = rng.uniform(0.9, 1.5)
        # 钉头鼠尾：起笔一顿，中段饱满，尾部尖收；个别叶子中间一折变细
        prof = (0.75 + 0.25 * np.sin(np.pi * np.clip(tt / 0.4, 0, 1) * 0.5)) * (1.0 - tt) ** 0.8
        prof += 0.35 * np.exp(-((tt / 0.05) ** 2))
        if rng.random() < 0.5:
            tk = rng.uniform(0.35, 0.6)
            prof *= 1.0 - 0.45 * np.exp(-(((tt - tk) / 0.05) ** 2))
        cover, _ = brush_stroke(X, Y, pts, wmax * prof, rng, dry=rng.uniform(0.45, 0.7), dry_start=rng.uniform(0.35, 0.55), ss=ss)
        depth = rank_i / max(n - 1, 1)  # 0=最后面
        if i in green:
            c = col(S.mix(S.ACCENT["shilv"], S.INK["nong"], 0.25 + 0.2 * depth))
        else:
            c = col(S.mix(S.INK["zhong"], S.INK["jiao"], 0.35 + 0.65 * depth))
        lay.over(c, cover * (0.80 + 0.15 * depth))
    if dots:
        # 苔点：根部几粒浓墨点
        for _ in range(rng.integers(2, 5)):
            px = 24.0 + rng.uniform(-13, 13)
            py = 38.6 - rng.uniform(0.0, 3.0)
            rr = rng.uniform(0.7, 1.3)
            dd = np.hypot((X - px) / (rr * rng.uniform(1.0, 1.5)), (Y - py) / rr)
            dd += 0.12 * noise(rng, X.shape, 0.6 * ss)
            lay.over(col(S.INK["jiao"]), smoothstep(1.0, 0.75, dd) * 0.92)
    lay = lay.down(ss)
    rgb, a = lay.straight()
    a[0, :] = a[:, 0] = a[:, -1] = 0
    return to_rgba8(rgb, a)


# ============================================================== 检查图


def font(size: int):
    try:
        return ImageFont.load_default(size=size)
    except Exception:  # noqa: BLE001
        return ImageFont.load_default()


def composite(bg: np.ndarray, img: Image.Image, x: int, y: int, mode: str, tint=None, scale: int = 2) -> None:
    """把 img 放大 scale 倍（最近邻，看真实像素）后叠到 float 画布 bg 上。"""
    im = img.convert("RGBA").resize((img.width * scale, img.height * scale), Image.NEAREST)
    arr = np.asarray(im, dtype=np.float64) / 255.0
    rgb, a = arr[..., :3], arr[..., 3:4]
    if tint is not None:
        rgb = rgb * np.asarray(tint)
    reg = bg[y : y + im.height, x : x + im.width]
    if mode == "add":
        reg += rgb * a
    else:
        reg[:] = rgb * a + reg * (1 - a)
    np.clip(reg, 0, 1, out=reg)


def review_sheet(entries, path: Path) -> None:
    """每张贴图 2× 摆两遍：上半张铺纸色、原样 over；下半张铺夜色 #161B2C、按游戏里的混合方式（发光的染色叠加）。"""
    width, pad, label_h = 1500, 18, 18
    # 先排版
    placements = []
    x = y = pad
    row_h = 0
    for name, img, *_ in entries:
        cw = max(img.width * 2, 118)
        ch = img.height * 2 + label_h
        if x + cw + pad > width:
            x = pad
            y += row_h + pad
            row_h = 0
        placements.append((x, y))
        x += cw + pad
        row_h = max(row_h, ch)
    panel_h = y + row_h + pad + 26
    canvas = np.zeros((panel_h * 2, width, 3))
    canvas[:panel_h] = col(S.PAPER)
    canvas[panel_h:] = col(S.NIGHT_AMBIENT)
    for (name, img, mode, tint), (px, py) in zip(entries, placements):
        composite(canvas, img, px, py + 26 + label_h, "over")
        composite(canvas, img, px, panel_h + py + 26 + label_h, mode, tint)
    out = Image.fromarray(np.round(canvas * 255).astype(np.uint8), "RGB")
    dr = ImageDraw.Draw(out)
    f_title, f_lab = font(16), font(12)
    dr.text((pad, 6), "(a) on PAPER, normal over, untinted", fill=S.INK["jiao"], font=f_title)
    dr.text((pad, panel_h + 6), "(b) on NIGHT_AMBIENT #161B2C, in-game blend (emissive: additive + tint)", fill="#E0E0E0", font=f_title)
    for (name, img, mode, tint), (px, py) in zip(entries, placements):
        lab = f"{name} {img.width}x{img.height}"
        dr.text((px, py + 26), lab, fill=S.INK["nong"], font=f_lab)
        dr.text((px, panel_h + py + 26), lab + (" add" if mode == "add" else ""), fill="#C8C8C8", font=f_lab)
    save_png(out, path)


def light_test(light: Image.Image, paper: Image.Image, path: Path) -> None:
    """灯光贴图拉伸到 400px（双线性，与 GPU 采样一致），加进夜色光照图（8 位，模拟渲染纹理），
    再正片叠底到平铺的宣纸上。右侧两格把亮度高通后放大 16 倍，用来看有没有同心色带：
    左为抖动后的贴图，右为不抖动直接取整的对照。"""
    N = 440
    cells = []
    a_f = np.asarray(light, dtype=np.float64)[..., 3]
    d = radial_d(128)
    core = np.exp(-((d / 0.30) ** 2))
    ref = np.round(bump_window(d) * (0.62 + 0.38 * core) * 255.0)  # 不抖动的对照
    pt = np.asarray(paper, dtype=np.float64) / 255.0
    tiled = np.tile(pt, (2, 2, 1))[:N, :N]
    amb = col(S.NIGHT_AMBIENT)
    tint = col(S.LANTERN_LIGHT)

    def lit(alpha8):
        big = np.asarray(Image.fromarray(alpha8.astype(np.float32), "F").resize((400, 400), Image.BILINEAR), dtype=np.float64) / 255.0
        lm = np.tile(amb, (N, N, 1))
        o = (N - 400) // 2
        lm[o : o + 400, o : o + 400] += big[..., None] * tint
        lm = np.round(np.clip(lm, 0, 1) * 255) / 255  # 光照渲染纹理是 8 位
        return lm

    lm_d, lm_r = lit(a_f), lit(ref)
    world_d = np.round(np.clip(tiled * lm_d, 0, 1) * 255) / 255
    cells.append(world_d)
    cells.append(lm_d)

    def hipass(img):
        lum = img @ np.array([0.299, 0.587, 0.114])
        pad = 24
        lp = np.pad(lum, pad, mode="edge")
        hp = (lp - fft_blur(lp, 6.0))[pad:-pad, pad:-pad]
        v = np.clip(0.5 + hp * 16.0, 0, 1)
        return np.repeat(v[..., None], 3, -1)

    cells.append(hipass(lm_d))
    cells.append(hipass(lm_r))
    gap = 10
    out = np.ones((N + 30, N * 4 + gap * 3, 3)) * 0.12
    for i, c in enumerate(cells):
        out[30:, i * (N + gap) : i * (N + gap) + N] = c
    im = Image.fromarray(np.round(out * 255).astype(np.uint8), "RGB")
    dr = ImageDraw.Draw(im)
    f = font(14)
    labels = ["paper x lightmap (light@400px)", "lightmap only", "lightmap hi-pass x16 (dithered)", "hi-pass x16 (no dither, ref)"]
    for i, t in enumerate(labels):
        dr.text((i * (N + gap) + 6, 8), t, fill="#DDDDDD", font=f)
    save_png(im, path)


# ============================================================== 主流程


def dump_json(obj) -> str:
    """缩进的 JSON，但数字短列表（size、anchor）写在一行里，方便人看。"""
    text = json.dumps(obj, ensure_ascii=False, indent=2)
    return re.sub(r"\[\s*([-0-9.eE]+),\s*([-0-9.eE]+)\s*\]", r"[\1, \2]", text) + "\n"


def anchor_entry(img: Image.Image, anchor, **extra):
    return {"size": [img.width, img.height], "anchor": [float(anchor[0]), float(anchor[1])], **extra}


def main() -> dict:
    t0 = time.perf_counter()
    VFX_DIR.mkdir(parents=True, exist_ok=True)
    GROUND_DIR.mkdir(parents=True, exist_ok=True)
    REVIEW_DIR.mkdir(parents=True, exist_ok=True)

    vfx: dict[str, tuple[Image.Image, tuple[float, float], dict]] = {}
    white_add = {"color": "white", "blend": "add", "tint": True}
    light, _ = make_light(np.random.default_rng(1001))
    vfx["light"] = (light, (0.5, 0.5), {**white_add, "note": "光照图里的灯光池，半径处 alpha 恰为 0，已做蓝噪声抖动"})
    vfx["glow"] = (make_glow(np.random.default_rng(1002)), (0.5, 0.5), {**white_add, "note": "自发光物体的烘焙泛光"})
    vfx["eyes"] = (make_eyes(), (0.5, 0.5), {**white_add, "note": "妖眼，按 style.EYE 染色"})
    vfx["shadow"] = (make_shadow(np.random.default_rng(1004)), (0.5, 0.5), {"color": "jiao", "blend": "normal", "note": "接触阴影，最大 alpha 约 0.45"})
    vfx["spark"] = (make_spark(), (0.5, 0.5), {**white_add})
    for i, size in enumerate((20, 26, 32)):
        vfx[f"gem_{i}"] = (make_gem(np.random.default_rng(1100 + i), size, i), (0.5, 0.5), {**white_add, "note": "魂火，默认染 SOUL_LIGHT"})
    for i, im in enumerate(make_flames()):
        vfx[f"flame_{i}"] = (im, (0.5, 0.6), {"color": "full", "blend": "add", "tint": False, "anim": "flame", "frame": i, "frames": 4})
    for i in range(3):
        vfx[f"ink_{i}"] = (make_ink(np.random.default_rng(1300 + i * 17)), (0.5, 0.5), {"color": "jiao", "blend": "normal"})
    vfx["lantern"] = (make_lantern(), (0.5, 0.5), {"color": "full", "blend": "add", "tint": False, "note": "灯笼芯，暖光 LANTERN_LIGHT"})

    ground: dict[str, tuple[Image.Image, tuple[float, float], dict]] = {}
    paper = make_paper()
    ground["paper"] = (paper, (0.0, 0.0), {"tile": True, "texel_world_units": 1.0 / S.PX_PER_UNIT, "mode": "RGB"})
    for i, (seed, lobes, ba, kw) in enumerate(WASHES):
        ground[f"wash_{i}"] = (make_wash(seed, lobes, ba, **kw), (0.5, 0.5), {"color": "zhong", "blend": "normal", "max_alpha": 0.35})
    for i, spec in enumerate(GRASS_SPECS):
        ground[f"grass_{i}"] = (make_grass(*spec), (0.5, 1.0), {"blend": "normal"})

    sizes = {}
    for folder, group, name in ((VFX_DIR, vfx, "vfx"), (GROUND_DIR, ground, "ground")):
        files = {}
        for key, (img, anc, extra) in group.items():
            fn = f"{key}.png"
            save_png(img, folder / fn)
            sizes[f"{name}/{fn}"] = (folder / fn).stat().st_size
            files[fn] = anchor_entry(img, anc, **extra)
        meta = {
            "name": name,
            "generator": "art/post/vfx_textures.py",
            "format": "PNG RGBA，直通（非预乘）alpha" + ("；paper.png 为不透明 RGB 平铺图" if name == "ground" else ""),
            "px_per_unit": S.PX_PER_UNIT,
            "files": files,
        }
        (folder / "meta.json").write_text(dump_json(meta), encoding="utf-8")

    # 检查图
    tints = {
        "light": col(S.LANTERN_LIGHT),
        "glow": col(S.LANTERN_LIGHT),
        "eyes": col(S.EYE["shade"]),
        "spark": col(S.mix(S.ACCENT["tenghuang"], "#FFFFFF", 0.5)),
        "gem_0": col(S.SOUL_LIGHT),
        "gem_1": col(S.SOUL_LIGHT),
        "gem_2": col(S.SOUL_LIGHT),
    }
    entries = []
    order = [k for k in vfx if k != "light"] + [k for k in ground if k.startswith("grass")] + ["light"]
    order += [k for k in ground if k.startswith("wash")]
    for key in order:
        img, _, extra = vfx.get(key) or ground[key]
        mode = "add" if extra.get("blend") == "add" else "over"
        entries.append((key, img, mode, tints.get(key)))
    entries.append(("paper(crop)", paper.crop((0, 0, 160, 160)).convert("RGBA"), "over", None))
    review_sheet(entries, REVIEW_DIR / "vfx_sheet.png")
    tile = Image.new("RGB", (1024, 1024))
    for ox in (0, 512):
        for oy in (0, 512):
            tile.paste(paper, (ox, oy))
    save_png(tile, REVIEW_DIR / "paper_tile_2x2.png")
    light_test(light, paper, REVIEW_DIR / "light_test.png")

    total = sum(sizes.values())
    dt = time.perf_counter() - t0
    print(f"写出 {len(sizes)} 张贴图，共 {total / 1024:.1f} KB，用时 {dt:.1f} s")
    for k, v in sizes.items():
        print(f"  {k:24s} {v / 1024:7.1f} KB")
    return sizes


if __name__ == "__main__":
    main()
