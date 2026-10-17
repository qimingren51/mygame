"""2D 笔墨分件工具（妖物重做 B 法：手绘分件动画）。纯 Pillow + numpy。

做法像 Spine 的剪纸动画：
  1. 每个部件（头、身、腿、尾、衣摆……）在自己的透明画层上用笔墨画一遍（Layer）：
     洇开的墨块（wash）、带笔毛纹的宽笔（broad）、提按的墨线（brush）、毛笔丝（fur）、发光（emit_*）；
  2. 画完裁成部件（Part），每帧给它一个变形（Affine 仿射、Bend 弯腰与压扁、Curve 沿曲线弯），
     逆向采样贴进帧画布（Frame），按前后顺序叠；
  3. 超采样画、最后缩小，边缘和细笔都干净。

坐标：设计稿用世界单位（x 右、y 上，原点是锚点）；画层用像素（x 右、y 下）。Layer.P() 负责换算。
本体是预乘 alpha（p, a）；发光层单独一份（ep, ea），夜里叠在暗层之上。
"""

from __future__ import annotations

import math
import os
import sys
from pathlib import Path

os.environ.setdefault("LANTERN_ART_DENSITY", "2")  # 只出桌面版 2 倍密度

import numpy as np  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402

_ART = Path(__file__).resolve().parents[1]
for _p in (_ART, _ART / "post"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
from style import style as S  # noqa: E402

# vfx_textures 用 `import style` 取 style.py 本身（它把 style/ 目录放进 sys.path）；这里的 style 是 art/style 包，
# 所以导入时临时把模块名指向 style.py（同 render/portrait.py 的做法）
_pkg = sys.modules.get("style")
sys.modules["style"] = S
try:
    import vfx_textures as V  # noqa: E402
finally:
    if _pkg is not None:
        sys.modules["style"] = _pkg
smoothstep = V.smoothstep
col = V.col
PAPER = col(S.PAPER)
JIAO, NONG, ZHONG, DAN, QING = (col(S.INK[k]) for k in ("jiao", "nong", "zhong", "dan", "qing"))


def blur(a, sigma, angle=0.0):
    return V.fft_blur(a, sigma, angle=angle)


def mixc(a, b, t):
    t = np.asarray(t, np.float64)
    if t.ndim:
        t = t[..., None]
    return np.asarray(a) * (1 - t) + np.asarray(b) * t


def curve_pts(ctrl, n=80, closed=False):
    """过控制点的平滑曲线（Catmull-Rom），按弧长重采样成 n 个点。"""
    c = np.asarray(ctrl, np.float64)
    if closed:
        m = len(c)
        seg = [(c[(i - 1) % m], c[i], c[(i + 1) % m], c[(i + 2) % m]) for i in range(m)]
    else:
        c = np.vstack([2 * c[0] - c[1], c, 2 * c[-1] - c[-2]])
        seg = [(c[i - 1], c[i], c[i + 1], c[i + 2]) for i in range(1, len(c) - 2)]
    t = np.linspace(0, 1, 24, endpoint=False)[:, None]
    out = [0.5 * ((2 * p1) + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t ** 2
                  + (-p0 + 3 * p1 - 3 * p2 + p3) * t ** 3) for p0, p1, p2, p3 in seg]
    out = np.vstack(out + ([c[0][None]] if closed else [c[-2][None]]))
    return V.arc_resample(out, n)


def bilinear(img, x, y):
    """img (H,W[,C]) 在像素坐标 (x, y) 处双线性采样（像素中心在 +0.5），画外为 0。"""
    H, W = img.shape[:2]
    xf, yf = x - 0.5, y - 0.5
    x0, y0 = np.floor(xf), np.floor(yf)
    fx, fy = xf - x0, yf - y0
    x0, y0 = x0.astype(np.int64), y0.astype(np.int64)
    out = None
    for dx, dy, w in ((0, 0, (1 - fx) * (1 - fy)), (1, 0, fx * (1 - fy)), (0, 1, (1 - fx) * fy), (1, 1, fx * fy)):
        xi, yi = x0 + dx, y0 + dy
        ok = (xi >= 0) & (xi < W) & (yi >= 0) & (yi < H)
        v = img[np.clip(yi, 0, H - 1), np.clip(xi, 0, W - 1)]
        ww = w * ok
        v = v * (ww[..., None] if img.ndim == 3 else ww)
        out = v if out is None else out + v
    return out


def seg_fields(X, Y, pts, halfw):
    """每个像素到折线的最近点（逐段只在该段附近的小块里算，比逐点快得多）。
    返回 dict：perp（带符号的横向距离，沿走向的右手边为正——画面上往右走时是下边）、over（超出两端的距离）、
    hw（该处半宽）、t（沿笔 0..1）。X、Y 是这一块的像素中心坐标。"""
    pts = np.asarray(pts, np.float64)
    halfw = np.broadcast_to(np.asarray(halfw, np.float64), (len(pts),))
    shape = X.shape
    best = np.full(shape, np.inf)
    out = {"perp": np.zeros(shape), "over": np.full(shape, 1e9), "hw": np.full(shape, 1e-6), "t": np.zeros(shape)}
    if X.size == 0 or len(pts) < 2:
        return out
    seg = np.diff(pts, axis=0)
    sl_ = np.hypot(seg[:, 0], seg[:, 1])
    keep = sl_ > 1e-9
    if not keep.any():
        return out
    cum = np.concatenate([[0.0], np.cumsum(sl_)])
    total = max(cum[-1], 1e-9)
    gx0, gy0 = X[0, 0] - 0.5, Y[0, 0] - 0.5
    H, W = shape
    pad = float(halfw.max()) * 1.8 + 3.0
    nseg = len(seg)
    for i in range(nseg):
        if not keep[i]:
            continue
        a, b = pts[i], pts[i + 1]
        xa = int(max(0, math.floor(min(a[0], b[0]) - pad - gx0)))
        xb = int(min(W, math.ceil(max(a[0], b[0]) + pad - gx0) + 1))
        ya = int(max(0, math.floor(min(a[1], b[1]) - pad - gy0)))
        yb = int(min(H, math.ceil(max(a[1], b[1]) + pad - gy0) + 1))
        if xb <= xa or yb <= ya:
            continue
        loc = (slice(ya, yb), slice(xa, xb))
        px, py = X[loc] - a[0], Y[loc] - a[1]
        d = seg[i] / sl_[i]
        along = px * d[0] + py * d[1]
        perp = px * (-d[1]) + py * d[0]
        perp = -perp  # 右手边为正（与 vfx_textures.stroke_fields 的约定一致）
        lo = -np.inf if i == 0 else 0.0
        hi = np.inf if i == nseg - 1 else sl_[i]
        al = np.clip(along, max(lo, 0.0) if i > 0 else -np.inf, hi)
        al_in = np.clip(along, 0.0, sl_[i])
        dx = along - al_in
        dist2 = dx * dx + perp * perp
        m = dist2 < best[loc]
        if not m.any():
            continue
        bl = best[loc]
        bl[m] = dist2[m]
        u = al_in / sl_[i]
        for key, val in (("perp", perp), ("over", np.abs(dx)), ("hw", halfw[i] + (halfw[i + 1] - halfw[i]) * u),
                         ("t", (cum[i] + al_in) / total)):
            o = out[key][loc]
            o[m] = val[m]
    return out


# ================================================================ 画层
class Layer:
    """一个部件的画层。ppu：每世界单位多少像素（已含超采样）；origin：锚点所在像素。"""

    def __init__(self, w, h, ppu, origin, seed=0):
        self.w, self.h, self.k = int(w), int(h), float(ppu)
        self.ox, self.oy = origin
        self.p = np.zeros((self.h, self.w, 3), np.float32)
        self.a = np.zeros((self.h, self.w), np.float32)
        self.ep = np.zeros((self.h, self.w, 3), np.float32)
        self.ea = np.zeros((self.h, self.w), np.float32)
        xs, ys = np.arange(self.w) + 0.5, np.arange(self.h) + 0.5
        self.X, self.Y = np.meshgrid(xs, ys)
        self.rng = np.random.default_rng(seed)

    # ---------------- 坐标
    def P(self, pts):
        """设计稿坐标（单位，y 上）→ 像素。"""
        q = np.asarray(pts, np.float64)
        return np.stack([self.ox + q[..., 0] * self.k, self.oy - q[..., 1] * self.k], -1)

    def U(self, pts):
        """像素 → 设计稿坐标。"""
        q = np.asarray(pts, np.float64)
        return np.stack([(q[..., 0] - self.ox) / self.k, (self.oy - q[..., 1]) / self.k], -1)

    def box(self, pts_px, pad):
        p = np.asarray(pts_px)
        x0, y0 = max(0, int(p[:, 0].min() - pad)), max(0, int(p[:, 1].min() - pad))
        x1, y1 = min(self.w, int(p[:, 0].max() + pad) + 1), min(self.h, int(p[:, 1].max() + pad) + 1)
        return (slice(y0, max(y0, y1)), slice(x0, max(x0, x1)))

    # ---------------- 合成
    def over(self, cov, color, sl):
        """不透明地盖上去（color 可以是逐像素的 (h,w,3)）。"""
        c = np.clip(cov, 0, 1).astype(np.float32)
        colr = np.broadcast_to(np.asarray(color, np.float32), c.shape + (3,))
        self.p[sl] = colr * c[..., None] + self.p[sl] * (1 - c[..., None])
        self.a[sl] = c + self.a[sl] * (1 - c)

    def glaze(self, cov, color, sl):
        """罩染：已有颜料按 color/宣纸 相乘（墨只会越叠越深）；空白处照常上色。"""
        c = np.clip(cov, 0, 1).astype(np.float32)
        colr = np.broadcast_to(np.asarray(color, np.float32), c.shape + (3,))
        rel = np.clip(colr / PAPER.astype(np.float32), 0, 1.2)
        a0 = self.a[sl]
        self.p[sl] = self.p[sl] * (1 - c[..., None] + c[..., None] * rel) + colr * (c * (1 - a0))[..., None]
        self.a[sl] = a0 + c * (1 - a0)

    def tint(self, cov, color, sl):
        """只改已有颜料的颜色、不改 alpha（夹在形里的提亮、换色）。"""
        c = (np.clip(cov, 0, 1) * self.a[sl]).astype(np.float32)
        colr = np.broadcast_to(np.asarray(color, np.float32), c.shape + (3,))
        self.p[sl] = self.p[sl] * (1 - np.clip(cov, 0, 1)[..., None]) + colr * c[..., None]

    def erase(self, cov, sl):
        c = 1 - np.clip(cov, 0, 1).astype(np.float32)
        self.p[sl] *= c[..., None]
        self.a[sl] *= c
        self.ep[sl] *= c[..., None]
        self.ea[sl] *= c

    def emit(self, cov, color, sl, keep_base=True):
        """发光层（眼、裂缝里的魂光）。keep_base=False 时本体同一处也换成这个颜色（白天看得见）。"""
        c = np.clip(cov, 0, 1).astype(np.float32)
        colr = np.broadcast_to(np.asarray(color, np.float32), c.shape + (3,))
        self.ep[sl] = colr * c[..., None] + self.ep[sl] * (1 - c[..., None])
        self.ea[sl] = c + self.ea[sl] * (1 - c)
        if not keep_base:
            self.over(c, colr, sl)

    # ---------------- 形
    def cover(self, poly_px, ss=3, soft=0.0, pad=4, smooth=True, closed=True):
        """闭合轮廓（像素）→ (切片, 覆盖度)。smooth 时先过 Catmull-Rom。"""
        pts = curve_pts(poly_px, max(24, len(poly_px) * 16), closed=True) if (smooth and closed) else np.asarray(poly_px)
        sl = self.box(pts, pad + 3 * soft)
        y0, x0 = sl[0].start, sl[1].start
        hh, ww = sl[0].stop - y0, sl[1].stop - x0
        if hh <= 0 or ww <= 0:
            return sl, np.zeros((max(hh, 0), max(ww, 0)), np.float32)
        im = Image.new("L", (ww * ss, hh * ss), 0)
        ImageDraw.Draw(im).polygon([((x - x0) * ss, (y - y0) * ss) for x, y in pts], fill=255)
        m = V.downsample(np.asarray(im, np.float64) / 255.0, ss)
        if soft > 0:
            m = np.clip(blur(m, soft), 0, 1)
        return sl, m.astype(np.float32)

    def noise(self, shape, sigma, angle=0.0):
        return V.noise(self.rng, shape, sigma, angle)

    def fill(self, poly, color, alpha=1.0, *, mode="over", soft=0.6, wet=0.0, tex=0.0, tex_sigma=6.0, units=True):
        """一块颜色。wet>0：边缘洇开、略参差（墨晕）。tex>0：浓淡略不匀。返回 (切片, 覆盖度)。"""
        poly = self.P(poly) if units else np.asarray(poly)
        sl, m = self.cover(poly, soft=soft, pad=int(wet * 4) + 4)
        if m.size == 0:
            return sl, m
        if wet > 0:  # 噪声只加在边上（离形远的地方不会冒出墨点）
            mb = blur(m, wet)
            n = self.noise(m.shape, wet * 1.2)
            m = smoothstep(0.30, 0.70, mb + 0.5 * n * mb * (1 - mb))
        a = m * alpha
        if tex > 0:
            a = a * (1 - tex + tex * (0.5 + 0.5 * np.tanh(self.noise(m.shape, tex_sigma))))
        (self.over if mode == "over" else self.glaze)(a, color, sl)
        return sl, m

    def wash(self, poly, color, alpha, *, soft=6.0, rough=0.5, ring=0.25, mode="glaze", units=True, clip=None):
        """一层淡墨淡彩：边软、洇开，干后边上一圈水痕略深。clip：限制在某个 alpha 场里（例如只罩在本体上）。"""
        poly = self.P(poly) if units else np.asarray(poly)
        sl, m = self.cover(poly, soft=0, pad=int(soft * 3) + 6)
        if m.size == 0:
            return
        ms = blur(m, soft) + 0.10 * rough * self.noise(m.shape, soft * 0.8)
        body = smoothstep(0.25, 0.65, ms)
        rimv = ring * np.exp(-((ms - 0.42) / 0.08) ** 2)
        a = alpha * np.clip(body * (0.88 + 0.12 * self.noise(m.shape, soft * 1.5)) + rimv, 0, 1)
        if clip is not None:
            a = a * clip[sl]
        (self.over if mode == "over" else self.glaze)(a, color, sl)

    def shade(self, poly, color, alpha, direction, lo=-0.2, hi=1.0, *, mode="glaze", soft=3.0, units=True, clip=None):
        """背光一面：在轮廓里沿 direction（单位向量，设计稿坐标）由淡到浓罩一层。"""
        poly_px = self.P(poly) if units else np.asarray(poly)
        sl, m = self.cover(poly_px, soft=soft)
        if m.size == 0:
            return
        c = poly_px.mean(0)
        ext = max(np.ptp(poly_px[:, 0]), np.ptp(poly_px[:, 1])) / 2 + 1e-6
        dx, dy = direction[0], -direction[1]
        u = ((self.X[sl] - c[0]) * dx + (self.Y[sl] - c[1]) * dy) / ext
        g = smoothstep(lo, hi, u + 0.12 * self.noise(m.shape, 8.0))
        a = m * alpha * g
        if clip is not None:
            a = a * clip[sl]
        (self.over if mode == "over" else self.glaze)(a, color, sl)

    # ---------------- 笔
    def _fields(self, c, hw):
        pad = float(np.max(hw)) * 2.0 + 3.0
        sl = self.box(c, pad)
        f = seg_fields(self.X[sl], self.Y[sl], c, np.asarray(hw, np.float64))
        return sl, f

    def _dry(self, f, dry, dry_start, jitter=0.12):
        """干笔：两侧边缘各自抖动，越往笔尾越干（飞白）。同 vfx_textures.brush_stroke，只是用快的距离场。"""
        t = f["t"]
        nt = 256
        e_l = np.interp(t, np.linspace(0, 1, nt), blur(self.rng.standard_normal((1, nt)), (5, 0))[0] * 3.0)
        e_r = np.interp(t, np.linspace(0, 1, nt), blur(self.rng.standard_normal((1, nt)), (5, 0))[0] * 3.0)
        e = np.where(f["perp"] > 0, e_l, e_r)
        hw = f["hw"] * np.clip(1.0 + jitter * e, 0.4, 1.6)
        cover = smoothstep(hw + 0.6, hw - 0.6, np.hypot(f["perp"], f["over"]))
        s = np.clip(f["perp"] / np.maximum(f["hw"], 1e-6), -1.0, 1.0)
        b = V.sample_tex(V.bristle_texture(self.rng), s, t)
        d = dry * smoothstep(dry_start, 1.0, t)
        return cover * smoothstep(d - 0.06, d + 0.06, b)

    def broad(self, ctrl, hw, colors, alpha=1.0, *, units=True, n=None, dry=0.0, dry_start=0.5, jitter=0.18,
              taper=(0.15, 0.25), mode="over", streak=1.0, tex=None, clip=None, smooth=True, cross=0.0, wet=0.0):
        """宽笔：一笔铺过去，笔毛带出顺着笔势的浓淡丝（colors=(浅, 深)，按笔毛纹在两色间取）；
        cross>0 是侧锋：笔的一边浓一边淡（顺着笔走的方向，右手边——画面上往右画时是下边——浓）；
        dry>0 后段飞白；wet>0 笔边洇开；taper=(起笔, 收笔) 两头收的长度占比。hw 是半宽（单位或像素，随 units）。"""
        p = self.P(ctrl) if units else np.asarray(ctrl, np.float64)
        k = self.k if units else 1.0
        length = float(np.hypot(*np.diff(p, axis=0).T).sum())
        n = n or max(12, int(length / 2.0))
        c = curve_pts(p, n) if (smooth and len(p) > 2) else V.arc_resample(p, n)
        t = np.linspace(0, 1, n)
        hw = np.broadcast_to(np.asarray(hw, np.float64) * k, (n,)).copy() if np.ndim(hw) == 0 else np.interp(
            t, np.linspace(0, 1, len(hw)), np.asarray(hw, np.float64) * k)
        if taper:
            a0, a1 = taper
            hw = hw * np.clip(0.25 + 0.75 * np.minimum(t / max(a0, 1e-3), 1), 0, 1) ** 0.6 * \
                np.clip(0.2 + 0.8 * np.minimum((1 - t) / max(a1, 1e-3), 1), 0, 1) ** 0.6
        sl, f = self._fields(c, hw)
        if f["t"].size == 0:
            return sl, None
        nt = 256
        e_l = np.interp(f["t"], np.linspace(0, 1, nt), blur(self.rng.standard_normal((1, nt)), (6, 0))[0] * 3.0)
        e_r = np.interp(f["t"], np.linspace(0, 1, nt), blur(self.rng.standard_normal((1, nt)), (6, 0))[0] * 3.0)
        e = np.where(f["perp"] > 0, e_l, e_r)
        hwj = f["hw"] * np.clip(1.0 + jitter * e, 0.45, 1.6)
        dist = np.hypot(f["perp"], f["over"])
        soft = 0.8 + wet
        cov = smoothstep(hwj + soft, hwj - soft, dist)
        s = np.clip(f["perp"] / np.maximum(f["hw"], 1e-6), -1, 1)
        b = V.sample_tex(tex if tex is not None else V.bristle_texture(self.rng, 48, 256), s, f["t"])
        if dry > 0:
            d = dry * smoothstep(dry_start, 1.0, f["t"])
            cov = cov * smoothstep(d - 0.08, d + 0.08, b)
        bb = 0.5 + (b - 0.5) * streak + 0.5 * cross * s
        colr = mixc(colors[0], colors[1], np.clip(bb, 0, 1)) if isinstance(colors, tuple) else colors
        a = cov * alpha
        if clip is not None:
            a = a * clip[sl]
        (self.over if mode == "over" else self.glaze)(a, colr, sl)
        return sl, cov

    def brush(self, ctrl, w, color=None, alpha=0.95, *, units=True, press=1.0, nail=0.6, tail=0.35, dry=0.0,
              dry_start=0.6, gap=None, mode="over", n=None, wob=0.12, smooth=True, clip=None, emit=None):
        """白描的一笔：起笔一顿（钉头），行笔略细，转弯处按重，收笔出锋；dry>0 后段飞白；gap=(t0,t1) 断开。
        w 是行笔半宽（单位或像素）。emit=(颜色, 强度) 时同时画进发光层。"""
        p = self.P(ctrl) if units else np.asarray(ctrl, np.float64)
        w = w * (self.k if units else 1.0)
        length = float(np.hypot(*np.diff(p, axis=0).T).sum())
        n = n or max(10, int(length / 1.3))
        c = curve_pts(p, n) if (smooth and len(p) > 2) else V.arc_resample(p, n)
        d = np.gradient(c, axis=0)
        ang = np.unwrap(np.arctan2(d[:, 1], d[:, 0]))
        seg = max(length / max(n - 1, 1), 1e-6)
        kk = blur((np.abs(np.gradient(ang)) / seg)[None, :], (2.5, 0))[0]
        kn = np.clip(kk * 6.0 * self.k / 4.0, 0, 1)
        t = np.linspace(0, 1, n)
        prof = (0.62 + 0.5 * press * kn) * (1 + nail * np.exp(-(t / 0.07) ** 2))
        if tail:
            prof = prof * (0.15 + 0.85 * np.clip((1 - t) / tail, 0, 1) ** 0.7)
        prof = prof * np.clip(0.35 + 0.65 * t / 0.05, 0, 1)
        wb = blur(self.rng.standard_normal((1, n)), (4.0, 0))[0]
        prof = prof * (1 + wob * wb / (wb.std() + 1e-9))
        hw = np.maximum(w * prof, 0.5)
        pieces = [(c, hw)]
        if gap:
            i0, i1 = int(gap[0] * (n - 1)), int(gap[1] * (n - 1))
            pieces = [(c[:i0], hw[:i0]), (c[i1:], hw[i1:])]
        for cc, hh in pieces:
            if len(cc) < 3:
                continue
            sl, f = self._fields(cc, hh)
            if dry > 0:
                cov = self._dry(f, dry, dry_start)
            else:
                cov = smoothstep(f["hw"] + 0.7, f["hw"] - 0.7, np.hypot(f["perp"], f["over"]))
            a = cov * alpha
            if clip is not None:
                a = a * clip[sl]
            if emit is not None:
                self.emit(a * emit[1], emit[0], sl)
            if color is not False:
                (self.over if mode == "over" else self.glaze)(a, JIAO if color is None else color, sl)

    def fur(self, roots, dirs, length, w, colors, alpha=0.9, *, curl=0.0, mode="over", dry=0.35, units=True,
            clip=None, jitter=0.25):
        """一排毛笔丝：每个根点沿方向画一根出锋的短笔（毛簇、鬃毛、尾毛）。roots/dirs 是数组；length、w 可逐根给。"""
        roots = np.asarray(roots, np.float64)
        dirs = np.asarray(dirs, np.float64)
        nr = len(roots)
        length = np.broadcast_to(np.asarray(length, np.float64), (nr,))
        w = np.broadcast_to(np.asarray(w, np.float64), (nr,))
        for i in range(nr):
            d = dirs[i] / (np.linalg.norm(dirs[i]) + 1e-9)
            nrm = np.array([-d[1], d[0]])
            L = length[i] * (1 + jitter * self.rng.uniform(-1, 1))
            cu = curl * L * (1 + 0.3 * self.rng.uniform(-1, 1))
            pts = [roots[i], roots[i] + d * L * 0.5 + nrm * cu * 0.35, roots[i] + d * L + nrm * cu]
            colr = colors[i % len(colors)] if isinstance(colors, list) else colors
            self.brush(pts, w[i], colr, alpha, units=units, nail=0.1, tail=0.8, press=0.3, dry=dry, dry_start=0.4,
                       mode=mode, clip=clip, wob=0.05)

    def dot(self, c, rx, ry, color, alpha=1.0, *, ang=0.0, units=True, soft=0.8, mode="over", emit=None):
        cx, cy = self.P(c) if units else c
        rx, ry = (rx * self.k, ry * self.k) if units else (rx, ry)
        r = max(rx, ry) * 1.6 + 4
        sl = self.box(np.array([[cx - r, cy - r], [cx + r, cy + r]]), 2)
        dx, dy = self.X[sl] - cx, self.Y[sl] - cy
        ca, sa = math.cos(ang), math.sin(ang)
        u, v = (dx * ca + dy * sa) / rx, (-dx * sa + dy * ca) / ry
        th = np.arctan2(v, u)
        kk = 1 + 0.08 * np.sin(3 * th + cx) + 0.05 * np.sin(5 * th + cy)
        dd = np.hypot(u, v) / kk
        a = smoothstep(1.0 + soft / max(rx, 1), 1.0 - soft / max(rx, 1), dd) * alpha
        if emit is not None:
            self.emit(a * emit, color, sl)
        if mode is not None:
            (self.over if mode == "over" else self.glaze)(a, color, sl)
        return sl, a

    def glow(self, c, r, color, alpha, units=True):
        """发光层里的一团柔光（眼睛、魂光外的一圈）。"""
        cx, cy = self.P(c) if units else c
        r = r * self.k if units else r
        sl = self.box(np.array([[cx - 3 * r, cy - 3 * r], [cx + 3 * r, cy + 3 * r]]), 2)
        d2 = ((self.X[sl] - cx) ** 2 + (self.Y[sl] - cy) ** 2) / (r * r)
        self.emit(np.exp(-d2) * alpha, color, sl)

    def part(self, pivot=(0.0, 0.0), pad=6, name=""):
        """裁出有内容的包围盒，得到部件。pivot：设计稿坐标里的转轴。"""
        m = (self.a > 1e-3) | (self.ea > 1e-3)
        ys, xs = np.nonzero(m)
        if len(xs) == 0:
            y0 = x0 = 0
            y1 = x1 = 1
        else:
            y0, y1 = max(0, ys.min() - pad), min(self.h, ys.max() + pad + 1)
            x0, x1 = max(0, xs.min() - pad), min(self.w, xs.max() + pad + 1)
        return Part(self.p[y0:y1, x0:x1].copy(), self.a[y0:y1, x0:x1].copy(), self.ep[y0:y1, x0:x1].copy(),
                    self.ea[y0:y1, x0:x1].copy(), (x0, y0), self.P(pivot), self.k, (self.ox, self.oy), name)


class Part:
    """画好的部件：裁剪后的四张图 + 裁剪偏移（画层像素）+ 转轴（画层像素）。"""

    def __init__(self, p, a, ep, ea, off, pivot_px, k, origin, name=""):
        self.p, self.a, self.ep, self.ea = p, a, ep, ea
        self.off = np.asarray(off, np.float64)
        self.pivot = np.asarray(pivot_px, np.float64)
        self.k = k
        self.origin = origin
        self.name = name
        self.stack = np.dstack([p, a[..., None], ep, ea[..., None]]).astype(np.float32)

    def bounds(self):
        """画层像素下的四个角。"""
        h, w = self.a.shape
        x0, y0 = self.off
        return np.array([[x0, y0], [x0 + w, y0], [x0, y0 + h], [x0 + w, y0 + h]], np.float64)


# ================================================================ 变形（逆映射：帧像素 → 画层像素）
class Affine:
    """绕转轴 pivot（画层像素）：缩放 (sx, sy)（沿 axis 角度方向）→ 旋转 rot（度，逆时针为正，画面上）→ 平移 (tx, ty) 单位。"""

    def __init__(self, pivot, rot=0.0, sx=1.0, sy=1.0, tx=0.0, ty=0.0, k=1.0, axis=0.0, shear=0.0):
        self.pv = np.asarray(pivot, np.float64)
        th = math.radians(-rot)  # 画面 y 向下，逆时针为正 → 取负
        R = np.array([[math.cos(th), -math.sin(th)], [math.sin(th), math.cos(th)]])
        a = math.radians(-axis)
        Ra = np.array([[math.cos(a), -math.sin(a)], [math.sin(a), math.cos(a)]])
        Sm = Ra @ np.diag([sx, sy]) @ Ra.T
        Sh = np.array([[1.0, shear], [0.0, 1.0]])
        self.M = R @ Sm @ Sh
        self.Mi = np.linalg.inv(self.M)
        self.t = np.array([tx * k, -ty * k])

    def fwd(self, q):
        q = np.asarray(q, np.float64)
        return (q - self.pv) @ self.M.T + self.pv + self.t

    def inv(self, x, y):
        u = np.stack([x - self.pv[0] - self.t[0], y - self.pv[1] - self.t[1]], -1)
        v = u @ self.Mi.T
        return v[..., 0] + self.pv[0], v[..., 1] + self.pv[1]


class Chain:
    """几个变形串起来：先 inner 再 outer（例如先弯腰，再整体平移）。"""

    def __init__(self, *ws):
        self.ws = ws

    def fwd(self, q):
        for w in self.ws:
            q = w.fwd(q)
        return q

    def inv(self, x, y):
        for w in reversed(self.ws):
            x, y = w.inv(x, y)
        return x, y


class Bend:
    """弯腰 + 压扁拉长：以 pivot（画层像素）为底，高处转得多（rot 度 × 权重(高度)），整体按 (sx, sy) 缩放；
    height 是权重从 0 到 1 的高度（像素）。逆映射用不动点迭代（角度小，三次就收敛）。"""

    def __init__(self, pivot, rot=0.0, sx=1.0, sy=1.0, height=100.0, power=1.5):
        self.pv = np.asarray(pivot, np.float64)
        self.rot, self.sx, self.sy, self.hgt, self.pw = math.radians(-rot), sx, sy, float(height), power

    def _theta(self, h):
        return self.rot * np.clip(h / self.hgt, 0, 1.5) ** self.pw

    def fwd(self, q):
        q = np.asarray(q, np.float64)
        v = (q - self.pv) * np.array([self.sx, self.sy])
        th = self._theta(-(q[..., 1] - self.pv[1]))
        c, s = np.cos(th), np.sin(th)
        return np.stack([v[..., 0] * c - v[..., 1] * s, v[..., 0] * s + v[..., 1] * c], -1) + self.pv

    def inv(self, x, y):
        ux, uy = x - self.pv[0], y - self.pv[1]
        h = -uy / self.sy
        for _ in range(4):
            th = self._theta(h)
            c, s = np.cos(-th), np.sin(-th)
            vx, vy = ux * c - uy * s, ux * s + uy * c
            h = -vy / self.sy
        return vx / self.sx + self.pv[0], vy / self.sy + self.pv[1]


class Curve:
    """沿曲线弯：部件在画层里是沿 x 轴摆直画的（rest_a → rest_b 一条水平线），
    每帧给一条新中线 pts（帧像素，首尾对应 rest_a、rest_b），按弧长对应、垂距不变（stretch 可改粗细）。"""

    def __init__(self, rest_a, rest_b, pts, width_scale=1.0):
        self.ra = np.asarray(rest_a, np.float64)
        self.rb = np.asarray(rest_b, np.float64)
        self.L0 = float(self.rb[0] - self.ra[0])
        self.q = np.asarray(pts, np.float64)
        seg = np.diff(self.q, axis=0)
        self.sl = np.hypot(seg[:, 0], seg[:, 1])
        self.s0 = np.concatenate([[0.0], np.cumsum(self.sl)])
        self.L1 = float(self.s0[-1])
        self.tan = seg / np.maximum(self.sl[:, None], 1e-9)
        self.ws = width_scale

    def fwd(self, p):
        p = np.asarray(p, np.float64)
        s = (p[..., 0] - self.ra[0]) / self.L0 * self.L1
        d = (p[..., 1] - self.ra[1]) * self.ws
        i = np.clip(np.searchsorted(self.s0, s) - 1, 0, len(self.sl) - 1)
        base = self.q[i] + self.tan[i] * (s - self.s0[i])[..., None]
        nrm = np.stack([-self.tan[i][..., 1], self.tan[i][..., 0]], -1)
        return base + nrm * d[..., None]

    def inv(self, x, y):
        P = np.stack([x.ravel(), y.ravel()], -1)
        best_d = np.full(len(P), np.inf)
        best_s = np.zeros(len(P))
        best_n = np.zeros(len(P))
        nseg = len(self.sl)
        for i in range(nseg):
            a, t, L = self.q[i], self.tan[i], self.sl[i]
            v = P - a
            along = v @ t
            lo = -1e9 if i == 0 else 0.0
            hi = 1e9 if i == nseg - 1 else L
            al = np.clip(along, lo, hi)
            perp = v[:, 0] * (-t[1]) + v[:, 1] * t[0]
            dd = (along - al) ** 2 + perp ** 2
            m = dd < best_d
            best_d[m] = dd[m]
            best_s[m] = self.s0[i] + al[m]
            best_n[m] = perp[m]
        u = self.ra[0] + best_s / self.L1 * self.L0
        v = self.ra[1] + best_n / self.ws
        return u.reshape(x.shape), v.reshape(x.shape)


# ================================================================ 帧画布
class Frame:
    """一帧的超采样画布（和部件同一个像素坐标系）：按顺序把部件贴进来，最后缩小。"""

    def __init__(self, w, h):
        self.w, self.h = int(w), int(h)
        self.p = np.zeros((self.h, self.w, 3), np.float32)
        self.a = np.zeros((self.h, self.w), np.float32)
        self.ep = np.zeros((self.h, self.w, 3), np.float32)
        self.ea = np.zeros((self.h, self.w), np.float32)

    def put(self, part: Part, warp=None, alpha=1.0, emit_gain=1.0, tint=None):
        """把部件按 warp 贴进来（warp=None 原位）。tint=(颜色, 强度)：整件罩一层色（受击、远近）。"""
        corners = part.bounds()
        fc = warp.fwd(corners) if warp is not None else corners
        pad = 6
        if isinstance(warp, (Curve, Chain)) or isinstance(warp, Bend):
            # 非线性变形：包围盒用一圈采样点的正向映射估计
            h, w = part.a.shape
            xs = np.linspace(0, w, 24) + part.off[0]
            ys = np.linspace(0, h, 24) + part.off[1]
            ring = np.concatenate([np.stack([xs, np.full_like(xs, ys[0])], -1), np.stack([xs, np.full_like(xs, ys[-1])], -1),
                                   np.stack([np.full_like(ys, xs[0]), ys], -1), np.stack([np.full_like(ys, xs[-1]), ys], -1)])
            fc = np.vstack([fc, warp.fwd(ring)])
            pad = 24
        x0, y0 = max(0, int(fc[:, 0].min()) - pad), max(0, int(fc[:, 1].min()) - pad)
        x1, y1 = min(self.w, int(fc[:, 0].max()) + pad), min(self.h, int(fc[:, 1].max()) + pad)
        if x1 <= x0 or y1 <= y0:
            return
        X, Y = np.meshgrid(np.arange(x0, x1) + 0.5, np.arange(y0, y1) + 0.5)
        if warp is not None:
            u, v = warp.inv(X, Y)
        else:
            u, v = X, Y
        smp = bilinear(part.stack, u - part.off[0], v - part.off[1])
        p, a, ep, ea = smp[..., 0:3], smp[..., 3], smp[..., 4:7], smp[..., 7]
        a = np.clip(a * alpha, 0, 1)
        p = p * alpha
        if tint is not None:
            p = p * (1 - tint[1]) + np.asarray(tint[0], np.float32) * a[..., None] * tint[1]
        sl = (slice(y0, y1), slice(x0, x1))
        self.p[sl] = p + self.p[sl] * (1 - a[..., None])
        self.a[sl] = a + self.a[sl] * (1 - a)
        # 发光层：被前面的本体挡住的部分要挡掉，所以先按本体 alpha 压暗，再叠上自己的
        ea = np.clip(ea * alpha * emit_gain, 0, 1)
        ep = ep * alpha * emit_gain
        hide = 1 - np.maximum(a, ea)
        self.ep[sl] = ep + self.ep[sl] * hide[..., None]
        self.ea[sl] = ea + self.ea[sl] * hide

    def paint(self, layer: Layer):
        """直接把一个画层（同坐标系、整幅）叠上来（每帧现画的烟、飘带）。"""
        self.p = layer.p + self.p * (1 - layer.a[..., None])
        self.a = layer.a + self.a * (1 - layer.a)
        self.ep = layer.ep + self.ep * (1 - np.maximum(layer.a, layer.ea)[..., None])
        self.ea = layer.ea + self.ea * (1 - np.maximum(layer.a, layer.ea))

    def down(self, ss):
        """缩小 ss 倍（盒式平均，预乘），返回 (rgb 直通 0..1, alpha, emit rgb 直通, emit alpha)。"""
        def d(x):
            return V.downsample(x.astype(np.float64), ss)
        p, a, ep, ea = d(self.p), d(self.a), d(self.ep), d(self.ea)
        rgb = p / np.maximum(a, 1e-6)[..., None]
        erg = ep / np.maximum(ea, 1e-6)[..., None]
        return np.clip(rgb, 0, 1), np.clip(a, 0, 1), np.clip(erg, 0, 1), np.clip(ea, 0, 1)
