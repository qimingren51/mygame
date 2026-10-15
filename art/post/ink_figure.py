#!/usr/bin/env python3
"""水墨写意人物的笔法（灯驿长卷 hub_scroll.py 和标题画 title_screen.py 共用；Pillow + numpy）。

画一个人：先在宣纸上擦出留白（knock），洇两层淡墨淡彩（wash，略错开），再用提按有变化的墨线勾轮廓和衣纹（brush：
起笔一顿、转折按重、收笔出锋，后段可飞白）。Fig 给一个以脚底为原点的局部坐标（y 向上为负），可缩放、左右翻转。
ribbon 是飘带，hand 是手。

所有函数都直接画进 title_screen.Painting（或它的子类）：用 P.glaze / P.over / P.stroke / P.dot / P.mark_near，
knock 还要 P.paper0（干净的纸）。画布固定 1920×1080（标题画和灯驿长卷都是这个尺寸）。
"""

from __future__ import annotations

import math

import numpy as np
from PIL import Image, ImageDraw

import title_screen as T
import vfx_textures as V

W, H = 1920, 1080
smoothstep, blur, noise = V.smoothstep, T.blur, T.noise
JIAO, NONG = T.JIAO, T.NONG


def closed_curve(ctrl, per: int = 14) -> np.ndarray:
    """过控制点的闭合平滑曲线（Catmull-Rom）。"""
    c = np.asarray(ctrl, np.float64)
    m = len(c)
    t = np.linspace(0, 1, per, endpoint=False)[:, None]
    out = []
    for i in range(m):
        p0, p1, p2, p3 = c[(i - 1) % m], c[i], c[(i + 1) % m], c[(i + 2) % m]
        out.append(0.5 * ((2 * p1) + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t ** 2 + (-p0 + 3 * p1 - 3 * p2 + p3) * t ** 3))
    return np.vstack(out)


def shape_cover(poly, ss: int = 3, soft: float = 0.6, pad: int = 4):
    """多边形 → (切片, 覆盖度)，只在包围盒里算（超采样抗锯齿，边缘略晕）。"""
    pts = np.asarray(poly, np.float64)
    x0, y0 = max(0, int(pts[:, 0].min()) - pad), max(0, int(pts[:, 1].min()) - pad)
    x1, y1 = min(W, int(pts[:, 0].max()) + pad + 1), min(H, int(pts[:, 1].max()) + pad + 1)
    sl = (slice(y0, y1), slice(x0, x1))
    if x1 <= x0 or y1 <= y0:
        return sl, np.zeros((max(0, y1 - y0), max(0, x1 - x0)))
    im = Image.new("L", ((x1 - x0) * ss, (y1 - y0) * ss), 0)
    ImageDraw.Draw(im).polygon([((x - x0) * ss, (y - y0) * ss) for x, y in pts], fill=255)
    m = V.downsample(np.asarray(im, np.float64) / 255.0, ss)
    if soft:
        m = np.clip(blur(m, soft), 0, 1)
    return sl, m


def fill(P, poly, color, alpha=1.0, *, mode="glaze", rim=0.25, tex=None, smooth=True, near=True, soft=0.6):
    """一块水墨：闭合轮廓里罩一层墨（罩染时浓淡略不匀），边上一圈水痕略深。smooth=False 时轮廓是折线。
    mode="over" 是不透明的底（人物的衣服、器物），默认没有浓淡，免得透出后面的东西。"""
    if tex is None:
        tex = 0.15 if mode == "glaze" else 0.0
    pts = closed_curve(poly) if smooth else np.asarray(poly, np.float64)
    sl, m = shape_cover(pts, soft=soft)
    if m.size == 0:
        return sl, m
    a = m * (1.0 - tex + tex * (0.5 + 0.5 * noise(P.rng, m.shape, 5.0)))
    if rim:
        a = a + rim * m * (1 - smoothstep(0.45, 0.95, blur(m, 2.2)))
    (P.glaze if mode == "glaze" else P.over)(np.clip(a * alpha, 0, 1), color, sl)
    if near:
        P.mark_near(m, sl)
    return sl, m


def line(P, ctrl, w0, w1=None, color=None, alpha=0.95, *, dry=0.25, dry_start=0.5, jitter=0.18, mode="over", n=None,
         smooth=True, near=True, taper=True):
    """一笔线：过控制点（smooth）或折线，粗细从 w0 到 w1（半宽，像素），两头略收。"""
    p = np.asarray(ctrl, np.float64)
    length = float(np.hypot(*np.diff(p, axis=0).T).sum())
    n = n or max(8, int(length / 2.5))
    c = T.curve_pts(p, n) if (smooth and len(p) > 2) else V.arc_resample(p, n)
    t = np.linspace(0, 1, len(c))
    hw = w0 + ((w0 if w1 is None else w1) - w0) * t
    if taper:
        hw = hw * np.clip(0.45 + 0.55 * np.minimum(t / 0.12, 1) * np.minimum((1 - t) / 0.12, 1) + 0.0, 0.45, 1.0)
    P.stroke(c, hw, JIAO if color is None else color, alpha, dry=dry, dry_start=dry_start, jitter=jitter, mode=mode, near=near)


def ellipse(P, cx, cy, rx, ry, color, alpha=1.0, *, mode="over", ang=0.0, near=True, soft=0.5):
    th = np.linspace(0, 2 * math.pi, 48, endpoint=False)
    ca, sa = math.cos(ang), math.sin(ang)
    pts = np.stack([cx + rx * np.cos(th) * ca - ry * np.sin(th) * sa, cy + rx * np.cos(th) * sa + ry * np.sin(th) * ca], -1)
    sl, m = shape_cover(pts, soft=soft)
    if m.size:
        (P.glaze if mode == "glaze" else P.over)(m * alpha, color, sl)
        if near:
            P.mark_near(m, sl)
    return pts


def brush(P, ctrl, w, *, color=None, alpha=0.95, smooth=True, press=1.0, nail=0.7, tail=0.3, dry=0.0, dry_start=0.55,
          gap=None, mode="over", n=None, near=True):
    """白描的一笔：起笔一顿（钉头），行笔略细，转折处按重，收笔出锋；dry>0 时后段飞白；gap=(t0, t1) 在这一段断开。
    w 是行笔时的半宽（像素）。"""
    p = np.asarray(ctrl, np.float64)
    length = float(np.hypot(*np.diff(p, axis=0).T).sum())
    n = n or max(10, int(length / 1.4))
    c = T.curve_pts(p, n) if (smooth and len(p) > 2) else V.arc_resample(p, n)
    d = np.gradient(c, axis=0)
    ang = np.unwrap(np.arctan2(d[:, 1], d[:, 0]))
    seg = max(length / max(n - 1, 1), 1e-6)
    k = np.abs(np.gradient(ang)) / seg
    k = blur(k[None, :], (2.5, 0))[0]
    kn = np.clip(k * 16.0, 0, 1)  # 转弯半径 16 像素以内按到最重
    t = np.linspace(0, 1, n)
    prof = (0.62 + 0.55 * press * kn) * (1 + nail * np.exp(-(t / 0.06) ** 2))
    if tail:
        prof = prof * (0.18 + 0.82 * np.clip((1 - t) / tail, 0, 1) ** 0.7)
    wob = blur(P.rng.standard_normal((1, n)), (4.0, 0))[0]
    prof = prof * (1 + 0.12 * wob / (wob.std() + 1e-9))
    hw = w * prof
    c_ = JIAO if color is None else color
    pieces = [(c, hw)]
    if gap:
        i0, i1 = int(gap[0] * (n - 1)), int(gap[1] * (n - 1))
        pieces = [(c[:i0], hw[:i0]), (c[i1:], hw[i1:])]
    for cc, hh in pieces:
        if len(cc) >= 3:
            P.stroke(cc, hh, c_, alpha, dry=dry, dry_start=dry_start, jitter=0.1, mode=mode, near=near)


def wash(P, poly, color, alpha, *, soft=2.4, rough=0.6, ring=0.3, mode="glaze", tex=0.18, smooth=True):
    """一层淡墨或淡彩：边缘软、略不齐（洇开），干后边上一圈水痕略深。poly 是闭合轮廓（画面坐标）。"""
    pts = closed_curve(poly) if smooth else np.asarray(poly, np.float64)
    sl, m = shape_cover(pts, soft=0, pad=int(soft * 3) + 6)
    if m.size == 0:
        return
    ms = blur(m, soft)
    n1 = noise(P.rng, m.shape, 3.0)
    ms = ms + 0.10 * rough * n1
    body = smoothstep(0.28, 0.62, ms)
    rim = ring * np.exp(-((ms - 0.40) / 0.09) ** 2)
    a = alpha * np.clip(body * (1 - tex + tex * (0.5 + 0.5 * noise(P.rng, m.shape, 7.0))) + rim, 0, 1)
    (P.glaze if mode == "glaze" else P.over)(a, color, sl)
    P.mark_near(body, sl)


def knock(P, poly, smooth=True):
    """人物所在处的背景擦回纸色（画人物时那里本来是留白的），边缘略外扩一点。"""
    pts = closed_curve(poly) if smooth else np.asarray(poly, np.float64)
    sl, m = shape_cover(pts, soft=1.0, pad=6)
    if m.size == 0:
        return
    a = smoothstep(0.08, 0.5, m) * 0.98
    P.over(a, P.paper0[sl], sl)
    P.mark_near(a, sl)


class Fig:
    """点景人物的局部坐标：原点在脚底（坐着的人是座位前的地面），y 向上为负；s 缩放，flip=-1 左右翻转。
    pose(x, y) → (x, y)：给了就先把局部坐标变一下（前倾、肩斜这类整体的姿态），所有笔都跟着走。"""

    def __init__(self, P, fx, fy, s=1.0, flip=1, pose=None):
        self.P, self.fx, self.fy, self.s, self.flip, self.pose = P, fx, fy, s, flip, pose

    def pt(self, x, y):
        if self.pose is not None:
            x, y = self.pose(x, y)
        return (self.fx + self.flip * self.s * x, self.fy + self.s * y)

    def pts(self, ctrl):
        return np.array([self.pt(*p) for p in ctrl])

    def fill(self, ctrl, color, alpha=1.0, **kw):
        return fill(self.P, self.pts(ctrl), color, alpha, **kw)

    def line(self, ctrl, w0, w1=None, color=None, alpha=0.95, **kw):
        line(self.P, self.pts(ctrl), w0 * self.s, None if w1 is None else w1 * self.s, color, alpha, **kw)

    def ellipse(self, cx, cy, rx, ry, color, alpha=1.0, **kw):
        x, y = self.pt(cx, cy)
        return ellipse(self.P, x, y, rx * self.s, ry * self.s, color, alpha, **kw)

    def brush(self, ctrl, w, **kw):
        brush(self.P, self.pts(ctrl), w * self.s, **kw)

    def wash(self, ctrl, color, alpha, off=(0.0, 0.0), **kw):
        wash(self.P, self.pts([(x + off[0], y + off[1]) for x, y in ctrl]), color, alpha, **kw)

    def knock(self, ctrl, **kw):
        knock(self.P, self.pts(ctrl), **kw)

    def shade(self, ctrl, color, alpha, side=-1.0):
        """衣服的背光一面：在轮廓里朝 side（局部坐标，-1 = 身后）一侧罩一层墨，往另一侧淡掉。"""
        pts = self.pts(ctrl)
        sl, m = shape_cover(closed_curve(pts), soft=0.6)
        if m.size == 0:
            return
        x0, x1 = pts[:, 0].min(), pts[:, 0].max()
        u = (self.P.X[sl] - (x0 + x1) / 2) / max((x1 - x0) / 2, 1.0) * side * self.flip
        self.P.glaze(m * alpha * smoothstep(-0.3, 0.9, u) * (0.85 + 0.15 * noise(self.P.rng, m.shape, 4.0)), color, sl)

    def dot(self, x, y, r, color=None, alpha=0.95):
        gx, gy = self.pt(x, y)
        self.P.dot(gx, gy, r * self.s, r * self.s, JIAO if color is None else color, alpha)
        self.P.mark_near(np.ones(1), (slice(int(gy), int(gy) + 1), slice(int(gx), int(gx) + 1)))


def hand(f: Fig, x, y, r=3.4, curl=1.0, skin=None):
    """一只手：纸色一小团，两笔勾出握着的指节；skin 给了就再洇一层肤色。"""
    pts = [(x - r, y - r * 0.8), (x + r, y - r), (x + r * 1.1, y + r * 0.6), (x - r * 0.6, y + r)]
    f.knock(pts)
    if skin is not None:
        f.wash(pts, skin, 0.4, soft=1.0)
    f.brush([(x - r * 0.9, y - r * 0.6), (x + r * 0.2, y - r * 1.05), (x + r * 1.05, y - r * 0.2)], 0.55, color=NONG, nail=0.2, tail=0.3)
    f.brush([(x + r * 0.9 * curl, y + r * 0.1), (x + r * 0.3, y + r * 0.95), (x - r * 0.7, y + r * 0.7)], 0.55, color=NONG, nail=0.2, tail=0.3)


def ribbon(P, pts, hw0, color, alpha, *, twists=2.0, phase=0.0, edge=0.55):
    """一条飘带（画面坐标）：一笔，宽窄随扭转起伏（扭到侧面时变窄），尾端出锋；扭到侧面处一道细墨边。"""
    c = T.curve_pts(pts, 90)
    t = np.linspace(0, 1, len(c))
    tw = 0.35 + 0.65 * np.abs(np.cos(math.pi * twists * t + phase))
    hw = hw0 * tw * (0.25 + 0.75 * np.clip((1 - t) / 0.35, 0, 1) ** 0.6) * np.clip(t / 0.05, 0.4, 1)
    P.stroke(c, hw, color, alpha, jitter=0.08, near=True)
    if edge:
        P.stroke(c + np.array([0.0, 0.6]), np.maximum(hw * 0.25, 0.35) * (1 - tw) + 0.2, NONG, edge * alpha, jitter=0.0, near=True)

