#!/usr/bin/env python3
"""提灯夜行 · 标题画、标题字和审图（Pillow + numpy；主角背影和石灯笼由 render/title_hero.py 用 Blender 渲）。

标题画（art/out/screens/title.png，1920×1080 不透明 RGB，只出桌面版）：
  一幅夜里的水墨长卷。先在宣纸上把整幅画画出来——淡墨远山层层隐入雾里、月亮是留白（烘云托月）、
  中景一道山脊，枯笔勾边、苔点、疏草，右边一株老松，山脊上两座石灯笼；主角立在山脊上背对观众，把灯笼向外举出。
  再像游戏里一样打光：画 × 光照图 + 发光层。光照图 = 夜色底 + 月光 + 灯笼的暖光圈（边缘按水渍打散）+ 石灯笼的火光。
  黑暗里有几团魂火、远处两三对妖眼（影妖精灵的 _emit 眼睛）。最后整幅叠纸纹、压暗四角。
  左边约 40% 保持安静、够暗，放竖排菜单；左上留给标题字。

标题字（art/out/screens/logo.png，透明 RGBA）：
  “提灯夜行”用马善政毛笔楷书写成真墨：笔画里有顺着笔势的飞白、收笔处积墨、墨边洇进纸纤维；
  旁边一方朱砂印“夜行”。外面一圈很淡的纸色晕（暗底上托住墨色，纸底上看不出来）。直通 alpha，颜色扩进透明区。

审图（art/out/review@2x/）：title_review.png（标题画 + 标题字 + 模拟竖排菜单，1920×1080）、
  title_review_half.png（半尺寸）、logo_review.png（标题字在纸底 / 夜底）、portrait_review.png（头像 256/128/64，纸底 / 夜底）。

运行（在仓库根目录下）：
    art/.venv/bin/python art/post/title_screen.py            # 全部（缺主角背影时先调 title_hero.py 渲染）
    art/.venv/bin/python art/post/title_screen.py --render   # 强制重渲主角背影和石灯笼
    art/.venv/bin/python art/post/title_screen.py --logo     # 只出标题字
固定随机种子，重复运行结果相同。出图参数固定为 2 倍密度（桌面版），与环境变量无关。
"""

from __future__ import annotations

import os

os.environ["LANTERN_ART_DENSITY"] = "2"  # 标题画只有桌面版：先定密度，再导入 style / vfx_textures

import json  # noqa: E402
import math  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402
from pathlib import Path  # noqa: E402

import numpy as np  # noqa: E402
from PIL import Image, ImageDraw, ImageFilter  # noqa: E402

HERE = Path(__file__).resolve().parent
ART = HERE.parent
sys.path.insert(0, str(HERE))
import vfx_textures as V  # noqa: E402
from ui_fonts import font  # noqa: E402

S = V.S
OUT = ART / "out" / "screens"
PARTS = OUT / "parts"
REVIEW = ART / "out" / "review@2x"
W, H = 1920, 1080

col, smoothstep = V.col, V.smoothstep
PAPER = col(S.PAPER)
PAPER_SH = col(S.PAPER_SHADOW)
JIAO, NONG, ZHONG, DAN, QING = (col(S.INK[k]) for k in ("jiao", "nong", "zhong", "dan", "qing"))
ZHUSHA, TENG = col(S.ACCENT["zhusha"]), col(S.ACCENT["tenghuang"])


def mixc(a, b, t):
    t = np.asarray(t, dtype=np.float64)
    if t.ndim:
        t = t[..., None]
    return np.asarray(a) * (1 - t) + np.asarray(b) * t


def blur(a: np.ndarray, sigma, angle: float = 0.0) -> np.ndarray:
    return V.fft_blur(a, sigma, angle=angle)


def noise(rng, shape, sigma, angle: float = 0.0) -> np.ndarray:
    """平滑噪声，标准差 1（周期边界，FFT 生成）。"""
    return V.noise(rng, shape, sigma, angle)


def fbm(rng, shape, sigmas, weights) -> np.ndarray:
    return V.fbm(rng, shape, sigmas, weights)


def stroke_cover(X, Y, pts, halfw, rng, *, dry: float = 0.0, dry_start: float = 0.5, jitter: float = 0.16):
    """一笔的覆盖度：只在笔画包围盒里算（大画布上画很多小笔触时省时间）。返回 (切片, 覆盖度)。"""
    pts = np.asarray(pts, dtype=np.float64)
    halfw = np.broadcast_to(np.asarray(halfw, dtype=np.float64), (len(pts),)).copy()
    pad = float(halfw.max()) * 2.0 + 3.0
    h, w = X.shape
    x0 = max(0, int(pts[:, 0].min() - pad))
    x1 = min(w, int(pts[:, 0].max() + pad) + 1)
    y0 = max(0, int(pts[:, 1].min() - pad))
    y1 = min(h, int(pts[:, 1].max() + pad) + 1)
    sl = (slice(y0, y1), slice(x0, x1))
    if x1 <= x0 or y1 <= y0:
        return sl, np.zeros((max(0, y1 - y0), max(0, x1 - x0)))
    Xs, Ys = X[sl], Y[sl]
    if dry > 0:
        cov, _ = V.brush_stroke(Xs, Ys, pts, halfw, rng, dry=dry, dry_start=dry_start, edge_jitter=jitter)
        return sl, cov
    f = V.stroke_fields(Xs, Ys, pts, halfw)
    hw = f["hw"]
    if jitter:
        e = np.interp(f["t"], np.linspace(0, 1, 64), blur(rng.standard_normal((1, 64)), (3, 0))[0] * 2.5)
        hw = hw * np.clip(1.0 + jitter * e, 0.5, 1.5)
    return sl, smoothstep(hw + 0.6, hw - 0.6, np.hypot(f["perp"], f["over"]))


def curve_pts(ctrl, n: int = 80) -> np.ndarray:
    """过控制点的平滑曲线（Catmull-Rom），按弧长重采样。"""
    c = np.asarray(ctrl, dtype=np.float64)
    c = np.vstack([2 * c[0] - c[1], c, 2 * c[-1] - c[-2]])
    out = []
    for i in range(1, len(c) - 2):
        p0, p1, p2, p3 = c[i - 1], c[i], c[i + 1], c[i + 2]
        t = np.linspace(0, 1, 24, endpoint=False)[:, None]
        out.append(0.5 * ((2 * p1) + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t ** 2
                          + (-p0 + 3 * p1 - 3 * p2 + p3) * t ** 3))
    out.append(c[-2][None])
    return V.arc_resample(np.vstack(out), n)


def save_rgba(img: Image.Image, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, optimize=True)


# ============================================================== 标题字


def streak_field(rng, shape, n_angles: int = 12, long: float = 22.0, short: float = 0.7) -> np.ndarray:
    """n_angles 个方向的笔毛纹理（沿该方向拉长的噪声，按名次归一到 0..1），形状 (n, h, w)。"""
    out = []
    for k in range(n_angles):
        a = math.pi * k / n_angles
        out.append(V.rank01(blur(rng.standard_normal(shape), (long, short), angle=a)))
    return np.stack(out)


def ink_texture(mask: np.ndarray, rng, scale: float, dry_amount: float = 0.95, zones: np.ndarray | None = None) -> tuple[np.ndarray, np.ndarray]:
    """把字形遮罩变成“真墨”：返回 (alpha, 墨色浓度 0..1，1 = 焦墨)。scale 是笔画粗细的量级（像素）。
      - 飞白：结构张量估出每点的笔势方向，取同方向的笔毛纹理；zones（0..1，手工指定的“笔干了”的地方，
        多在长笔画的后段）加上一点低频噪声决定哪里干，越靠笔画边缘越干；笔势不明确的交叉处和端头不起飞白。
      - 积墨：笔画端头（周围墨少的凸处）墨饱、略微鼓出、颜色最深；行笔中段略淡一点。
      - 洇边：墨边顺着纸纤维往外渗一点点。"""
    h, w = mask.shape
    m = np.clip(mask, 0, 1)
    g = blur(m, scale * 0.15)
    gy, gx = np.gradient(g)
    jxx, jxy, jyy = (blur(a, scale * 0.30) for a in (gx * gx, gx * gy, gy * gy))
    theta_s = np.mod(0.5 * np.arctan2(2 * jxy, jxx - jyy) + math.pi / 2, math.pi)  # 笔势方向（边缘法线转 90°）
    coh = np.sqrt((jxx - jyy) ** 2 + 4 * jxy ** 2) / (jxx + jyy + 1e-9)  # 方向一致性：交叉处低
    tex = streak_field(rng, (h, w), long=scale * 1.8, short=max(0.6, scale * 0.03))
    n = tex.shape[0]
    f = theta_s / math.pi * n
    i0 = np.floor(f).astype(int) % n
    i1 = (i0 + 1) % n
    fr = f - np.floor(f)
    yy, xx = np.mgrid[0:h, 0:w]
    b = tex[i0, yy, xx] * (1 - fr) + tex[i1, yy, xx] * fr
    inner = smoothstep(0.5, 0.95, blur(m, scale * 0.20))  # 笔画内部 1，边上 0
    ends = m * smoothstep(0.60, 0.30, blur(m, scale * 0.9))  # 端头
    zone = 0.22 * smoothstep(0.6, 1.4, fbm(rng, (h, w), (scale * 1.6, scale * 0.7), (0.75, 0.25)))
    if zones is not None:
        zone = np.maximum(zone, zones)
    tips = m * smoothstep(0.42, 0.18, blur(m, scale * 0.6))  # 只有笔尖最尖的一点不干
    dry = dry_amount * zone * smoothstep(0.15, 0.5, coh) * (0.38 + 0.62 * (1 - inner)) - 1.0 * blur(tips, scale * 0.1)
    dry = np.clip(dry, 0, 0.78)
    white = smoothstep(dry - 0.035, dry + 0.035, b)  # 1 = 有墨
    pool = smoothstep(0.30, 0.55, blur(m, scale * 0.10)) * smoothstep(0.05, 0.35, blur(ends, scale * 0.22))
    body = np.maximum(m, pool)
    fib = V.rank01(blur(rng.standard_normal((h, w)), (scale * 0.45, 0.6), angle=0.3))
    fib2 = V.rank01(blur(rng.standard_normal((h, w)), (scale * 0.45, 0.6), angle=2.1))
    seep = smoothstep(0.06, 0.45, blur(body, scale * 0.05)) * smoothstep(0.6, 0.97, np.maximum(fib, fib2)) * (1 - body)
    alpha = np.clip(np.maximum(body * white, 0.45 * seep), 0, 1)
    wet = fbm(rng, (h, w), (scale * 1.2, scale * 0.5), (0.7, 0.3))
    dens = np.clip(0.80 + 0.06 * wet + 0.25 * pool + 0.12 * (1 - inner) - 0.10 * dry, 0, 1)
    dens = np.where(seep * 0.45 > body * white, 0.45, dens)
    return alpha, dens


def make_seal(text: str, size: int, rng) -> Image.Image:
    """朱砂印：方印、白文（字留白），印边略不齐，印泥有轻重、零星没印上的白点。返回 RGBA。"""
    ss = 3
    n = size * ss
    X, Y = np.meshgrid(np.arange(n) + 0.5, np.arange(n) + 0.5)
    c = n / 2
    half = n * 0.46
    wob = 0.012 * n * noise(rng, (n, n), n * 0.06)
    d = np.maximum(np.abs(X - c), np.abs(Y - c)) + wob - half
    plate = smoothstep(1.5 * ss, -1.5 * ss, d)
    # 字：两字竖排，右列一字一格（印文从右往左、从上往下读；两字时上下排）
    glyph = Image.new("L", (n, n), 0)
    dr = ImageDraw.Draw(glyph)
    f = font("serif", int(n * 0.43), weight=900)
    for i, ch in enumerate(text):
        bb = f.getbbox(ch)
        gw, gh = bb[2] - bb[0], bb[3] - bb[1]
        cx, cy = c, n * (0.285 + 0.43 * i)
        dr.text((cx - gw / 2 - bb[0], cy - gh / 2 - bb[1]), ch, font=f, fill=255)
    gl = np.asarray(glyph.filter(ImageFilter.GaussianBlur(0.45 * ss)), np.float64) / 255.0
    gl = gl + 0.25 * noise(rng, (n, n), 2.0 * ss) * smoothstep(0.1, 0.5, gl) * (1 - gl)
    carve = smoothstep(0.35, 0.55, gl)
    # 印泥：轻重不匀 + 没印上的白点 + 边缘一圈略深
    ink = 0.86 + 0.10 * noise(rng, (n, n), 9.0 * ss) + 0.05 * noise(rng, (n, n), 1.5 * ss)
    specks = smoothstep(2.1, 2.6, noise(rng, (n, n), 1.2 * ss)) + smoothstep(1.9, 2.4, noise(rng, (n, n), 4.0 * ss)) * 0.8
    red_a = plate * (1 - carve) * np.clip(ink, 0, 1) * (1 - np.clip(specks, 0, 1))
    rim = smoothstep(-6 * ss, -1 * ss, d) * plate
    red = mixc(ZHUSHA, mixc(ZHUSHA, JIAO, 0.25), 0.5 * rim + 0.25 * (1 - np.clip(ink, 0, 1)))
    # 印面以内没沾上印泥的地方（白文的字、白点）露出的是纸：填纸色，暗底上字也清楚
    lay = V.Layer(n, n)
    lay.over(PAPER, plate)
    lay.over(red, red_a)
    lay = lay.down(ss)
    rgb, a = lay.straight()
    return V.to_rgba8(rgb, a)


HALO = (34.0, 0.50, 1.4, 0.30)  # 薄雾的模糊半径、浓度；亮边的模糊半径、浓度


def make_logo(halo: bool = True) -> tuple[Image.Image, dict]:
    """标题字“提灯夜行”+ 朱砂印。返回 (RGBA, 信息)。"""
    rng = np.random.default_rng(4100)
    ss = 2  # 在 2 倍尺寸上做墨的纹理，再缩小
    char_px = 214
    gap = 10
    seal_px = 96
    margin = 64
    # 每个字略有大小、高低、倾斜的变化，像一口气写下来
    jit = [(1.00, 4, -1.5), (1.03, -6, 1.0), (0.97, 3, -0.5), (1.06, -10, 1.5)]
    # 飞白的位置（每个字的墨框里归一化坐标：中心 u, v，半径 ru, rv，方向°）：长笔画收尾处笔干
    dry_zones = [
        [(0.82, 0.91, 0.17, 0.08, 10), (0.20, 0.80, 0.06, 0.17, 90)],  # 提：是的长捺、提手旁的竖
        [(0.84, 0.19, 0.17, 0.06, 2), (0.71, 0.74, 0.05, 0.17, 90)],  # 灯：丁的横、竖
        [(0.68, 0.86, 0.19, 0.07, 25), (0.55, 0.165, 0.16, 0.05, 0)],  # 夜：捺、首横
        [(0.65, 0.76, 0.05, 0.17, 90), (0.84, 0.29, 0.13, 0.05, 0)],  # 行：亍的竖、横
    ]
    text = "提灯夜行"
    glyphs = []
    for ch, (k, dy, rot) in zip(text, jit):
        fk = font("brush", int(char_px * ss * 1.08 * k))
        bb = fk.getbbox(ch)
        gw, gh = bb[2] - bb[0], bb[3] - bb[1]
        im = Image.new("L", (gw + 40 * ss, gh + 40 * ss), 0)
        ImageDraw.Draw(im).text((20 * ss - bb[0], 20 * ss - bb[1]), ch, font=fk, fill=255)
        im = im.rotate(rot, resample=Image.BICUBIC, expand=True)
        im = im.crop(im.getbbox())
        glyphs.append((im, dy * ss))
    total_w = sum(g.width for g, _ in glyphs) + gap * ss * (len(text) - 1)
    Wl = int(total_w / ss + 14 + seal_px + margin * 2)
    Hl = int(max(g.height for g, _ in glyphs) / ss + margin * 2 + 20)
    mask = Image.new("L", (Wl * ss, Hl * ss), 0)
    zones = np.zeros((Hl * ss, Wl * ss))
    yy, xx = np.mgrid[0:Hl * ss, 0:Wl * ss]
    x = margin * ss
    for (im, dy), zl in zip(glyphs, dry_zones):
        gy0 = int((Hl * ss - im.height) / 2 + dy)
        mask.paste(im, (int(x), gy0), im)
        for u, v, ru, rv, ang in zl:
            cx, cy = x + u * im.width, gy0 + v * im.height
            a = math.radians(ang)
            # 半径按字框的宽高给，方向上取长轴
            rl, rs = (ru * im.width, rv * im.height) if abs(math.cos(a)) > 0.5 else (rv * im.height, ru * im.width)
            dxr = (xx - cx) * math.cos(a) + (yy - cy) * math.sin(a)
            dyr = -(xx - cx) * math.sin(a) + (yy - cy) * math.cos(a)
            zones = np.maximum(zones, np.exp(-((dxr / rl) ** 2 + (dyr / rs) ** 2) * 1.4))
        x += im.width + gap * ss
    m = np.asarray(mask, np.float64) / 255.0
    alpha, dens = ink_texture(m, rng, scale=char_px * ss * 0.11, zones=zones)
    rgb = mixc(mixc(ZHONG, NONG, 0.55), JIAO, dens)
    prem = V.downsample(rgb * alpha[..., None], ss)
    alpha = V.downsample(alpha, ss)
    rgb = prem / np.maximum(alpha, 1e-6)[..., None]
    h, w = alpha.shape
    lay = V.Layer(h, w)
    body = V.downsample(m, ss)
    if halo:
        # 纸色晕：暗底上托住墨色。一团边缘打散的薄雾（像月光照着的雾），再贴着笔画一道很窄的亮边；
        # 颜色就是纸色，放在纸上看不出来
        hrng = np.random.default_rng(4111)
        mist_s, mist_a, rim_s, rim_a = HALO
        rim = smoothstep(0.02, 0.35, blur(body, rim_s))
        cloud = smoothstep(-1.6, 1.6, fbm(hrng, (h, w), (40.0, 14.0), (0.7, 0.3)))
        mist = smoothstep(0.0, 0.40, blur(body, mist_s)) * (0.65 + 0.35 * cloud)
        hz = np.maximum(rim_a * rim, mist_a * mist)
        yy, xx = np.mgrid[0:h, 0:w]
        border = np.minimum(np.minimum(xx, w - 1 - xx), np.minimum(yy, h - 1 - yy))
        hz = hz * smoothstep(0, margin * 0.9, border)  # 雾贴着图边淡到 0，不会被图框切出直边
        lay.over(mixc(PAPER, np.ones(3), 0.12), np.clip(hz, 0, 1))
    lay.over(rgb, alpha)
    # 朱砂印：在“行”字右下
    seal = make_seal("夜行", seal_px, np.random.default_rng(4120))
    sx = int(x / ss) + 4
    sy = int(Hl * 0.53)
    sa = np.asarray(seal, np.float64) / 255.0
    lay2 = V.Layer(seal.height, seal.width)
    lay2.p = sa[..., :3] * sa[..., 3:4]
    lay2.a = sa[..., 3]
    sl = (slice(sy, sy + seal.height), slice(sx, sx + seal.width))
    sub = V.Layer(seal.height, seal.width)
    sub.p, sub.a = lay.p[sl].copy(), lay.a[sl].copy()
    if halo:
        sub.over(mixc(PAPER, np.ones(3), 0.18), np.clip(blur(sa[..., 3], 6.0), 0, 1) * 0.5)
    sub.over(sa[..., :3], sa[..., 3])
    lay.p[sl], lay.a[sl] = sub.p, sub.a
    rgb_s, a_s = lay.straight()
    a_s[0, :] = a_s[-1, :] = a_s[:, 0] = a_s[:, -1] = 0
    img = V.to_rgba8(rgb_s, a_s)
    ink_box = Image.fromarray((V.downsample(m, ss) > 0.5).astype(np.uint8) * 255).getbbox()
    return img, {"size": [img.width, img.height], "ink_bbox": list(ink_box), "seal_xy": [sx, sy, seal.width]}


def logo_review(logo: Image.Image, path: Path) -> None:
    """标题字在纸底、夜底、标题画常见的暗蓝灰底上各放一遍。"""
    pad = 30
    bgs = [S.PAPER, S.NIGHT_AMBIENT, S.mix(S.NIGHT_AMBIENT, S.INK["dan"], 0.35)]
    out = Image.new("RGB", (logo.width + pad * 2, (logo.height + pad) * len(bgs) + pad), S.hex_to_rgb(S.PAPER))
    for i, c in enumerate(bgs):
        bg = Image.new("RGBA", (logo.width, logo.height), S.hex_to_rgb(c) + (255,))
        bg.alpha_composite(logo)
        out.paste(bg.convert("RGB"), (pad, pad + i * (logo.height + pad)))
    save_rgba(out, path)


# ============================================================== 标题画：画布与笔墨工具


class Painting:
    """一张宣纸上的画（白天看的样子，sRGB 0..1）+ 发光层（加法）。
    glaze：水墨罩染（相乘，层层叠深）；over：正常覆盖（留白、雾、不透明的笔触）。"""

    def __init__(self, rng):
        self.rng = rng
        self.X, self.Y = np.meshgrid(np.arange(W) + 0.5, np.arange(H) + 0.5)
        self.rgb = paper_canvas(rng)
        self.emit = np.zeros((H, W, 3))
        self.near = np.zeros((H, W))  # 近处（受灯笼光照的）区域：中景地面、石、松、人、石灯笼
        self.mist = np.zeros((H, W))  # 雾：夜里被月光照着，自己微微发亮

    def mark_near(self, a, sl=None):
        if sl is None:
            self.near = np.maximum(self.near, np.clip(a, 0, 1))
        else:
            self.near[sl] = np.maximum(self.near[sl], np.clip(a, 0, 1))

    def glaze(self, a, color, sl=None):
        a = np.clip(a, 0, 1)[..., None]
        rel = np.asarray(color) / PAPER
        if sl is None:
            self.rgb *= 1 - a + a * rel
        else:
            self.rgb[sl] *= 1 - a + a * rel

    def over(self, a, color, sl=None):
        a = np.clip(a, 0, 1)[..., None]
        if sl is None:
            self.rgb[:] = self.rgb * (1 - a) + np.asarray(color) * a
        else:
            self.rgb[sl] = self.rgb[sl] * (1 - a) + np.asarray(color) * a

    def stroke(self, pts, halfw, color=None, alpha=1.0, *, dry=0.0, dry_start=0.5, jitter=0.16, mode="over", bleed=0.0,
               near=False):
        """一笔墨：color 默认焦墨。mode="glaze" 时按罩染叠（淡墨笔触叠在一起会更深）。bleed>0 时墨边略晕。"""
        sl, cov = stroke_cover(self.X, self.Y, pts, halfw, self.rng, dry=dry, dry_start=dry_start, jitter=jitter)
        if cov.size == 0:
            return
        if bleed > 0:
            cov = np.maximum(cov, 0.35 * blur(cov, bleed))
        c = JIAO if color is None else color
        (self.glaze if mode == "glaze" else self.over)(cov * alpha, c, sl)
        if near:
            self.mark_near(cov, sl)

    def dot(self, x, y, rx, ry, color=None, alpha=1.0, ang=0.0):
        """苔点：略不规则的椭圆墨点，边缘微晕。"""
        r = int(max(rx, ry) * 2 + 4)
        x0, y0 = max(0, int(x) - r), max(0, int(y) - r)
        x1, y1 = min(W, int(x) + r + 1), min(H, int(y) + r + 1)
        if x1 <= x0 or y1 <= y0:
            return
        sl = (slice(y0, y1), slice(x0, x1))
        dx, dy = self.X[sl] - x, self.Y[sl] - y
        ca, sa = math.cos(ang), math.sin(ang)
        u, v = (dx * ca + dy * sa) / rx, (-dx * sa + dy * ca) / ry
        th = np.arctan2(v, u)
        k = 1 + 0.18 * np.sin(3 * th + x) + 0.1 * np.sin(5 * th + y)
        d = np.hypot(u, v) / k
        a = smoothstep(1.0 + 0.6 / max(rx, 1), 1.0 - 0.6 / max(rx, 1), d) * alpha
        self.over(a, JIAO if color is None else color, sl)


def paper_canvas(rng) -> np.ndarray:
    """整幅宣纸：用 vfx_textures 的可平铺纸（2 倍密度，1024²）镜像拼满画布，再叠一层画布尺度的云状浓淡，
    看不出重复。"""
    tile = np.asarray(V.make_paper(), np.float64) / 255.0
    big = np.concatenate([tile, tile[:, ::-1]], 1)
    big = np.concatenate([big, big[::-1]], 0)
    out = big[37:37 + H, 61:61 + W].copy()
    cloud = fbm(rng, (H, W), (260.0, 90.0, 30.0), (0.5, 0.35, 0.15))
    out = mixc(out, out * (PAPER_SH / PAPER), np.clip(0.18 + 0.16 * cloud, 0, 1) * 0.6)
    return out


def ridge_line(xs, peaks, base, rng, rough=6.0, rough_sigma=18.0):
    """山脊线 y(x)：base 是平处的高度，peaks = [(中心 x, 高, 左半宽, 右半宽, 尖度)]。
    每座主峰旁再随机长出两三个矮一些的肩峰；崎岖程度随山高增加（高处石骨嶙峋，山脚平缓）。"""
    y = np.full(xs.shape, float(base))
    subs = []
    for cx, hgt, wl, wr, sharp in peaks:
        subs.append((cx, hgt, wl, wr, sharp))
        for _ in range(int(rng.integers(2, 4))):
            side = -1 if rng.random() < 0.5 else 1
            off = side * rng.uniform(0.25, 0.75) * (wl if side < 0 else wr)
            w2 = rng.uniform(0.3, 0.55) * (wl + wr) / 2
            subs.append((cx + off, hgt * rng.uniform(0.4, 0.78), w2, w2 * rng.uniform(0.7, 1.3), sharp * rng.uniform(0.8, 1.4)))
    for cx, hgt, wl, wr, sharp in subs:
        t = np.where(xs < cx, (cx - xs) / wl, (xs - cx) / wr)
        prof = np.clip(1 - t, 0, 1) ** sharp * (1 - 0.05 * np.exp(-(t / 0.05) ** 2))  # 峰尖略圆
        y = np.minimum(y, base - hgt * prof)
    above = base - y

    def n1d(sigma):
        n = blur(rng.standard_normal((1, xs.size)), (sigma, 0))[0]
        return n / (n.std() + 1e-9)

    return y + n1d(30.0) * (rough + 0.05 * above) + n1d(rough_sigma * 0.4) * (0.4 * rough + 0.018 * above) + n1d(3.0) * 0.8

def mountain_layer(P: Painting, ridge, color, alpha, fade, rng, *, edge=0.45, streak=0.35, mist_from=None, mist_len=80.0):
    """一层远山：山脊线下方罩一层墨，山脊处墨最浓（笔先落在山脊上，水往下走），往下渐淡；
    竖向的皴纹打散墨色；山脚隐进雾里（mist_from 以下按 mist_len 淡出）。山脊边缘略毛。"""
    jit = 1.2 * noise(rng, (H, W), 1.2)
    depth = P.Y - ridge[None, :] + jit
    inside = smoothstep(-1.0, 1.4, depth)
    top = np.exp(-np.maximum(depth, 0) / 7.0)
    body = 0.35 + 0.65 * np.exp(-np.maximum(depth, 0) / fade)
    tex = noise(rng, (H, W), (40.0, 2.5), angle=math.pi / 2 + 0.25) * 0.6 + noise(rng, (H, W), (14.0, 1.4), angle=math.pi / 2 - 0.3) * 0.4
    a = alpha * inside * (body * (1 + streak * tex) + edge * top)
    if mist_from is not None:
        m = smoothstep(mist_from + mist_len, mist_from, P.Y + 25 * noise(rng, (H, W), (90.0, 14.0)))
        a = a * m
    P.glaze(np.clip(a, 0, 0.95), color)


def wash_blob(P: Painting, cx, cy, rx, ry, color, alpha, rng, *, ang=0.0, rough=0.25, edge=0.25, mode="glaze"):
    """一团水墨晕染（不规则椭圆，边缘一圈水痕略深）。"""
    r = int(max(rx, ry) * 1.6) + 8
    x0, y0, x1, y1 = max(0, int(cx - r)), max(0, int(cy - r)), min(W, int(cx + r)), min(H, int(cy + r))
    if x1 <= x0 or y1 <= y0:
        return
    sl = (slice(y0, y1), slice(x0, x1))
    dx, dy = P.X[sl] - cx, P.Y[sl] - cy
    ca, sa = math.cos(ang), math.sin(ang)
    u, v = (dx * ca + dy * sa) / rx, (-dx * sa + dy * ca) / ry
    n = noise(rng, u.shape, max(rx, ry) * 0.18)
    d = np.hypot(u, v) * (1 + rough * 0.4 * n)
    m = smoothstep(1.0, 0.75, d)
    ring = np.exp(-((d - 0.88) / 0.06) ** 2) * edge
    a = alpha * (m * (0.85 + 0.15 * noise(rng, u.shape, 6.0)) + ring * m)
    (P.glaze if mode == "glaze" else P.over)(a, color, sl)


# ============================================================== 标题画：构图

HERO_FEET = (1185.0, 906.0)  # 主角脚底在画面上的位置
MOON = (1552.0, 196.0, 50.0)  # 月亮圆心、半径
SKY_INK = mixc(DAN, col(S.ACCENT["huaqing"]), 0.22)  # 夜空的淡墨里兑一点花青
# 中景山脊（主角站的那道）的远边：左下方从画外升上来，中间平缓，右端抬起接松下的大石
GROUND_EDGE = [(180, 1110), (420, 1015), (620, 935), (800, 884), (980, 862), (1180, 858), (1400, 862),
               (1560, 846), (1660, 812), (1760, 772), (1860, 748), (1960, 738)]
# 小路：从右下前景弯到主角脚下，再沿山脊往左延伸，越远越窄
PATH = [(1430, 1095), (1340, 1010), (1250, 945), (1185, 915), (1080, 893), (960, 882), (850, 885)]
STONE_LANTERNS = [(978.0, 878.0, 0.74), (712.0, 915.0, 0.50)]  # 脚底 x, y, 缩放（相对主角的比例尺）
WISPS = [(706.0, 735.0, 1.0), (888.0, 668.0, 0.75), (1712.0, 642.0, 0.85), (1622.0, 985.0, 0.7), (540.0, 870.0, 0.6)]
EYES = [(452.0, 992.0, 0.72, False), (604.0, 818.0, 0.5, False), (1862.0, 1004.0, 0.8, True)]  # 眼睛位置, 缩放, 镜像


def ground_edge_y(xs: np.ndarray) -> np.ndarray:
    c = curve_pts(GROUND_EDGE, 400)
    order = np.argsort(c[:, 0])
    return np.interp(xs, c[order, 0], c[order, 1])


def paint_sky(P: Painting, rng):
    """夜空：上浓下淡的一层淡墨，横向的云气；月亮留白，月周围的墨一圈圈淡开（烘云托月），两缕薄云横过月下。"""
    mx, my, mr = MOON
    yn = P.Y / H
    base = 0.46 - 0.30 * smoothstep(0.0, 0.62, yn)
    cloud = noise(rng, (H, W), (230.0, 26.0), angle=-0.05)
    cloud2 = noise(rng, (H, W), (80.0, 10.0), angle=-0.03)
    a = base * (1 + 0.30 * cloud + 0.12 * cloud2)
    d = np.hypot(P.X - mx, P.Y - my)
    halo = smoothstep(mr * 0.95, mr * 5.0, d)
    a = a * (0.08 + 0.92 * halo ** 0.8)
    a = a * smoothstep(mr - 0.5, mr + 2.0, d + 1.5 * noise(rng, (H, W), 1.5))  # 月轮留白，边缘略毛
    P.glaze(a, SKY_INK)
    # 横过月亮下半的薄云（两缕淡墨），和月亮左上方一片更淡的云
    for cy, amp, wid, sx in ((my + 0.30 * mr, 0.55, 11.0, 1.0), (my + 0.78 * mr, 0.42, 8.0, 1.3), (my - 1.5 * mr, 0.16, 14.0, 2.0)):
        band = np.exp(-((P.Y - cy - 7 * noise(rng, (H, W), (140.0, 10.0))) / wid) ** 2)
        span = smoothstep(mx - 330 * sx, mx - 90, P.X) * smoothstep(mx + 380 * sx, mx + 120, P.X)
        tex = 0.55 + 0.45 * V.rank01(noise(rng, (H, W), (70.0, 1.6), angle=-0.03))
        P.glaze(np.clip(amp * band * span * tex, 0, 1), SKY_INK)
    # 天上几片云：淡墨染开，边缘一圈干了的水痕
    for cx, cy, rx, ry, a in ((420, 150, 380, 60, 0.20), (980, 95, 300, 42, 0.16), (1240, 300, 260, 30, 0.12),
                              (200, 420, 300, 40, 0.14), (1760, 110, 220, 36, 0.14)):
        wash_blob(P, cx, cy, rx, ry, SKY_INK, a, rng, ang=-0.04, rough=0.5, edge=0.6)


def mountain_texture(P: Painting, ridge, color, rng, mist_from, *, n=60, strength=0.3, edge_k=1.6):
    """披麻皴：从山脊往下顺着山势的长弧笔（淡墨干笔），山脊上几段略重的边线；雾里不画。"""
    slope = np.gradient(blur(ridge[None, :], (12.0, 0))[0])
    deep = mixc(color, NONG, 0.5)
    for _ in range(n):
        x = rng.uniform(0, W)
        i = int(np.clip(x, 0, W - 1))
        y = ridge[i] + rng.uniform(2, 30)
        if y > mist_from - 30:
            continue
        sgn = -1.0 if slope[i] < 0 else 1.0  # 朝下坡的方向
        d = np.array([sgn, abs(slope[i]) + 0.35])
        d = d / np.linalg.norm(d)
        ln = rng.uniform(30, 95)
        bend = rng.uniform(-0.25, 0.25)
        ts = np.linspace(0, 1, 14)
        rot = np.array([[math.cos(bend), -math.sin(bend)], [math.sin(bend), math.cos(bend)]])
        d2 = rot @ d
        pts = np.stack([x + (d[0] * (1 - ts) + d2[0] * ts) * ln * ts, y + (d[1] * (1 - ts) + d2[1] * ts) * ln * ts], -1)
        hw = np.interp(ts, [0, 0.2, 1], [0.8, rng.uniform(1.4, 2.6), 0.5])
        P.stroke(pts, hw, deep, strength * rng.uniform(0.6, 1.2), dry=0.55, dry_start=0.1, mode="glaze")
    for _ in range(n // 6):  # 山脊边线
        x0 = rng.uniform(0, W - 150)
        xx = np.linspace(x0, x0 + rng.uniform(60, 160), 24)
        yy = np.interp(xx, np.arange(W) + 0.5, ridge) + 1.5
        if yy.max() > mist_from - 20:
            continue
        P.stroke(np.stack([xx, yy], -1), np.interp(np.linspace(0, 1, 24), [0, 0.2, 0.8, 1], [0.6, 2.0, 1.6, 0.5]), deep,
                 strength * edge_k, dry=0.6, dry_start=0.2, mode="glaze")


def paint_mountains(P: Painting, rng):
    """三层远山，一层比一层近、墨一层比一层重，山脚都隐进雾里；最后在山谷里铺一道雾。"""
    xs = np.arange(W) + 0.5
    layers = [
        # 基线, 山峰, 颜色, 浓度, 渐淡长度, 雾起处
        (540, [(1170, 330, 340, 250, 1.35), (1395, 240, 190, 230, 1.2), (690, 175, 320, 250, 1.1),
               (1830, 250, 230, 260, 1.3), (300, 120, 300, 320, 1.0)], QING, 0.34, 140.0, 560),
        (620, [(985, 240, 240, 190, 1.45), (1290, 170, 170, 220, 1.2), (520, 160, 260, 230, 1.2),
               (1690, 200, 210, 200, 1.3), (60, 120, 200, 200, 1.0)], mixc(QING, DAN, 0.5), 0.40, 110.0, 650),
        (712, [(830, 125, 300, 210, 1.0), (1480, 118, 260, 250, 1.0), (180, 95, 260, 300, 1.0)], DAN, 0.46, 80.0, 735),
    ]
    for li, (base, peaks, c, a, fade, mist_from) in enumerate(layers):
        r = ridge_line(xs, peaks, base, rng, rough=5.0 if base < 600 else 7.0)
        mountain_layer(P, r, c, a, fade, rng, mist_from=mist_from, mist_len=70.0)
        if li >= 1:
            mountain_texture(P, r, c, rng, mist_from, n=70 if li == 1 else 60, strength=0.22 + 0.1 * li,
                             edge_k=0.8 if li == 1 else 1.6)
        # 山与山之间的雾：下一层之前铺一层纸色
        wav = blur(rng.standard_normal((1, W)), (90.0, 0))[0]
        wav = 28.0 * wav / (wav.std() + 1e-9)  # 雾带的高低随 x 起伏
        yb = P.Y + wav[None, :]
        fog = smoothstep(base - 150, base - 30, yb) * smoothstep(base + 90, base, yb)
        fog = fog * np.clip(0.35 + 0.65 * smoothstep(-1.2, 1.2, noise(rng, (H, W), (130.0, 22.0))), 0, 1)
        P.over(np.clip(fog * 0.32, 0, 1), mixc(PAPER, np.ones(3), 0.2))
        P.mist = np.maximum(P.mist, np.clip(fog * 0.5, 0, 1))
    # 山谷里的一道雾
    wav = blur(rng.standard_normal((1, W)), (120.0, 0))[0]
    yb = P.Y + (34.0 * wav / (wav.std() + 1e-9))[None, :]
    fog = smoothstep(650, 735, yb) * smoothstep(900, 770, yb) * np.clip(0.35 + 0.65 * smoothstep(-1.3, 1.3, noise(rng, (H, W), (180.0, 24.0))), 0, 1)
    P.over(np.clip(fog * 0.55, 0, 1), mixc(PAPER, np.ones(3), 0.25))
    P.mist = np.maximum(P.mist, np.clip(fog, 0, 1))


def paint_ground(P: Painting, rng):
    """中景山脊：淡墨铺地（越往前越重，带横向的干笔纹），小路留白；远边一道枯笔焦墨勾边，
    边下几笔皴、一溜苔点。"""
    g = ground_edge_y(P.X[0])
    depth = P.Y - g[None, :] + 1.5 * noise(rng, (H, W), 1.3)
    inside = smoothstep(-1.0, 1.5, depth)
    tex = V.rank01(noise(rng, (H, W), (70.0, 1.8), angle=-0.04))
    a = (0.10 + 0.50 * smoothstep(20, 300, depth)) * (0.70 + 0.55 * tex) + 0.12 * np.exp(-np.maximum(depth, 0) / 14.0)
    P.glaze(np.clip(a * inside, 0, 0.9), mixc(DAN, ZHONG, 0.35))
    P.mark_near(inside)
    # 小路：一道越远越窄的留白
    path = curve_pts(PATH, 200)
    hw = np.linspace(46, 7, len(path))
    sl, cov = stroke_cover(P.X, P.Y, path, hw, rng, jitter=0.25)
    cov = blur(cov, 3.0) * (0.75 + 0.25 * noise(rng, cov.shape, 4.0))
    P.over(np.clip(cov * 0.55, 0, 1), mixc(PAPER, PAPER_SH, 0.3), sl)
    # 远边：几段枯笔
    segs = [(260, 560), (540, 860), (840, 1250), (1230, 1590), (1570, 1700)]
    for k, (xa, xb) in enumerate(segs):
        xx = np.linspace(xa, xb, 40)
        yy = np.interp(xx, P.X[0], g) + 2.0 + 1.5 * np.sin(xx / 37.0 + k)
        hw = np.interp(np.linspace(0, 1, 40), [0, 0.1, 0.7, 1], [2.0, 4.6, 3.6, 1.2])
        P.stroke(np.stack([xx, yy], -1), hw, JIAO, 0.92, dry=0.45, dry_start=0.35, jitter=0.25, bleed=1.2)
    # 皴笔：沿坡势的短干笔，淡墨
    for _ in range(46):
        x = rng.uniform(380, 1600)
        y0 = float(np.interp(x, P.X[0], g)) + rng.uniform(10, 110)
        ln = rng.uniform(30, 95)
        sl_ = (np.interp(x + 10, P.X[0], g) - np.interp(x - 10, P.X[0], g)) / 20.0
        xx = np.linspace(x, x + ln, 14)
        yy = y0 + (xx - x) * sl_ + rng.uniform(-4, 4) * np.sin(np.linspace(0, math.pi, 14))
        hw = np.interp(np.linspace(0, 1, 14), [0, 0.2, 1], [0.8, rng.uniform(1.6, 2.8), 0.6])
        P.stroke(np.stack([xx, yy], -1), hw, ZHONG, rng.uniform(0.35, 0.7), dry=0.6, dry_start=0.2, mode="glaze")
    # 苔点：沿远边一溜，疏密不匀
    for _ in range(70):
        x = rng.uniform(330, 1700)
        if rng.random() < 0.35 and abs(x - HERO_FEET[0]) < 70:
            continue
        y = float(np.interp(x, P.X[0], g)) + rng.normal(0, 5) + 2
        r = rng.uniform(1.6, 4.2)
        P.dot(x, y, r * rng.uniform(1.0, 1.6), r, JIAO, rng.uniform(0.75, 1.0), ang=rng.uniform(-0.4, 0.4))
    # 前景：最下面一抹更重的墨，把画面兜住
    fg = smoothstep(960, 1080, P.Y) * (0.5 + 0.5 * noise(rng, (H, W), (120.0, 25.0)))
    P.glaze(np.clip(fg * 0.45, 0, 1), ZHONG)


def paint_ground_detail(P: Painting, rng):
    """地面的笔墨细节（灯光照到时看得见）：横向的擦笔、几块干了带水痕的淡墨、小路边的碎石点。"""
    g = ground_edge_y(P.X[0])
    for _ in range(150):  # 擦：横向干笔，靠远边和石边密一些
        x = rng.uniform(300, 1640)
        gy = float(np.interp(x, P.X[0], g))
        y = gy + abs(rng.normal(0, 70)) + 8
        if y > H - 4:
            continue
        ln = rng.uniform(30, 130) * (0.6 + 0.4 * min(1.0, (y - gy) / 120))
        xx = np.linspace(x, x + ln, 16)
        yy = y + rng.uniform(-3, 3) * np.sin(np.linspace(0, math.pi, 16)) + (xx - x) * rng.uniform(-0.05, 0.04)
        hw = np.interp(np.linspace(0, 1, 16), [0, 0.15, 1], [0.8, rng.uniform(1.5, 3.4), 0.6])
        P.stroke(np.stack([xx, yy], -1), hw, mixc(ZHONG, NONG, rng.uniform(0, 0.6)), rng.uniform(0.18, 0.42), dry=0.65,
                 dry_start=0.05, jitter=0.3, mode="glaze")
    for _ in range(9):  # 淡墨块
        x = rng.uniform(820, 1600)
        y = float(np.interp(x, P.X[0], g)) + rng.uniform(25, 170)
        wash_blob(P, x, y, rng.uniform(60, 150), rng.uniform(10, 24), mixc(DAN, ZHONG, 0.3), rng.uniform(0.12, 0.22), rng,
                  ang=rng.uniform(-0.08, 0.08), rough=0.6, edge=0.9)
    path = curve_pts(PATH, 200)
    nrm = np.gradient(path, axis=0)
    nrm = np.stack([-nrm[:, 1], nrm[:, 0]], -1) / (np.linalg.norm(nrm, axis=1, keepdims=True) + 1e-9)
    hw = np.linspace(46, 7, len(path))
    for _ in range(60):  # 路边碎石
        i = int(rng.integers(0, len(path)))
        side = -1 if rng.random() < 0.5 else 1
        c = path[i] + nrm[i] * side * hw[i] * rng.uniform(0.8, 1.3)
        r = rng.uniform(1.4, 3.6) * (0.5 + 0.5 * hw[i] / 46)
        P.dot(c[0], c[1], r * rng.uniform(1.2, 1.9), r, mixc(NONG, JIAO, rng.random()), rng.uniform(0.5, 0.9),
              ang=rng.uniform(-0.3, 0.3))


def poly_mask(poly, ss: int = 2, soft: float = 0.8) -> np.ndarray:
    """多边形 → (H, W) 覆盖度（超采样抗锯齿，边缘略晕）。"""
    im = Image.new("L", (W * ss, H * ss), 0)
    ImageDraw.Draw(im).polygon([(x * ss, y * ss) for x, y in poly], fill=255)
    m = V.downsample(np.asarray(im, np.float64) / 255.0, ss)
    return np.clip(blur(m, soft), 0, 1) if soft else m


def paint_rock(P: Painting, rng, top, side, plane, *, alpha=0.7):
    """一块大石（松根所在）：top 顶部轮廓（左 → 右），side 左侧轮廓（上 → 下，到画面底），
    plane 顶面与正面的分界（左 → 右）。顶面淡、正面重；正面用斧劈皴（斜下的宽扁干笔），
    轮廓枯笔勾，分界一笔淡墨，顶上苔点。"""
    t = curve_pts(top, 160)
    sd = curve_pts(side, 60)
    pl = curve_pts(plane, 120)
    poly = list(map(tuple, sd[::-1])) + list(map(tuple, t)) + [(W + 40, t[-1][1]), (W + 40, H + 40), (sd[-1][0], H + 40)]
    m = poly_mask(poly)
    order = np.argsort(pl[:, 0])
    py = np.interp(P.X[0], pl[order, 0], pl[order, 1])
    front = smoothstep(-6, 10, P.Y - py[None, :] + 6 * noise(rng, (H, W), (20.0, 3.0), angle=1.2))
    tex = V.rank01(noise(rng, (H, W), (30.0, 2.2), angle=1.95))
    a = m * (0.22 + 0.55 * front * (0.65 + 0.5 * tex)) * alpha / 0.7
    P.glaze(np.clip(a, 0, 0.95), mixc(DAN, ZHONG, 0.6))
    P.mark_near(m)
    hw = np.interp(np.linspace(0, 1, len(t)), [0, 0.06, 0.6, 1], [1.5, 5.4, 4.4, 2.5])
    P.stroke(t + [0, 1.5], hw, JIAO, 0.95, dry=0.4, dry_start=0.3, jitter=0.3, bleed=1.0)
    P.stroke(sd, np.interp(np.linspace(0, 1, len(sd)), [0, 0.2, 1], [4.8, 3.6, 1.0]), JIAO, 0.9, dry=0.5, dry_start=0.2,
             jitter=0.3)
    P.stroke(pl, np.interp(np.linspace(0, 1, len(pl)), [0, 0.2, 0.8, 1], [0.8, 2.6, 2.2, 0.6]), NONG, 0.8, dry=0.5,
             dry_start=0.4, mode="glaze")
    for _ in range(26):  # 斧劈皴：正面上斜下的宽扁笔
        x = rng.uniform(t[0, 0] + 10, W - 10)
        y0 = float(np.interp(x, pl[order, 0], pl[order, 1])) + rng.uniform(8, 200)
        ln = rng.uniform(26, 70)
        ang = math.radians(rng.uniform(100, 125))
        pts = np.array([(x, y0), (x + math.cos(ang) * ln, y0 + math.sin(ang) * ln)])
        pts = V.arc_resample(pts, 12)
        hw = np.interp(np.linspace(0, 1, 12), [0, 0.2, 1], [rng.uniform(3, 6), rng.uniform(4, 8), 1.0])
        P.stroke(pts, hw, mixc(ZHONG, NONG, 0.5), rng.uniform(0.35, 0.65), dry=0.55, dry_start=0.1, jitter=0.3,
                 mode="glaze")
    for _ in range(34):
        i = int(rng.integers(0, len(t)))
        x, y = t[i]
        r = rng.uniform(1.8, 4.8)
        P.dot(x + rng.normal(0, 6), y + rng.uniform(-3, 5), r * 1.4, r, JIAO, 0.92)


def needle_fan(P: Painting, cx, cy, r, rng, *, color, alpha, mode="over", tilt=0.0, wash=0.0):
    """一簇松针：从一条短短的“簇心”向上、向两侧扇开的细针，压扁成横向的一团；wash>0 时底下先罩一团淡墨。"""
    if wash:
        wash_blob(P, cx, cy - r * 0.25, r * 1.05, r * 0.48, ZHONG, wash, rng, ang=tilt, rough=0.4, edge=0.3)
    n = int(rng.integers(20, 30))
    for k in range(n):
        a = math.radians(-180 + 180 * (k + rng.uniform(0.1, 0.9)) / n) + tilt
        ln = r * rng.uniform(0.7, 1.05) * (0.75 + 0.25 * abs(math.cos(a)))
        bx = cx + rng.normal(0, r * 0.08) + math.cos(a) * r * 0.08
        by = cy + rng.normal(0, r * 0.04)
        ts = np.linspace(0, 1, 7)
        xx = bx + math.cos(a) * ln * ts
        yy = by + math.sin(a) * ln * ts * 0.62
        P.stroke(np.stack([xx, yy], -1), np.linspace(1.4, 0.35, 7), color, alpha * rng.uniform(0.8, 1.0), jitter=0.0,
                 mode=mode, near=True)


def paint_pine(P: Painting, rng):
    """老松：根扎在右边大石里，树干粗壮、S 形向左上，一枝长枝横伸到主角头顶上方，一枝斜上出画；
    树干：中间罩淡墨、两边枯笔勾皮、鳞皮一片片；枝干转折有节；松针一簇簇扇形，先淡后浓两遍。"""
    trunk = curve_pts([(1828, 752), (1800, 680), (1752, 600), (1736, 520), (1694, 446), (1630, 398)], 120)
    t = np.linspace(0, 1, len(trunk))
    hw = 34 - 17 * t ** 0.8
    nrm = np.gradient(trunk, axis=0)
    nrm = np.stack([-nrm[:, 1], nrm[:, 0]], -1) / (np.linalg.norm(nrm, axis=1, keepdims=True) + 1e-9)
    sl, cov = stroke_cover(P.X, P.Y, trunk, hw, rng, jitter=0.10)
    side = np.clip(((P.X[sl] - np.interp(P.Y[sl], trunk[::-1, 1], trunk[::-1, 0])) / 30.0), -1, 1)
    P.glaze(cov * (0.82 + 0.15 * side) * (0.8 + 0.2 * noise(rng, cov.shape, 5.0)), mixc(ZHONG, NONG, 0.5), sl)
    P.mark_near(cov, sl)
    for sgn, w0 in ((1, 6.0), (-1, 4.5)):
        edge = trunk + nrm * (hw[:, None] - 2.5) * sgn
        P.stroke(edge, np.interp(t, [0, 0.1, 0.8, 1], [2.5, w0, w0 * 0.8, 2.0]), JIAO, 0.95, dry=0.45, dry_start=0.25,
                 jitter=0.3)
    for k in range(34):  # 鳞皮
        i = int(rng.uniform(3, len(trunk) - 6))
        c = trunk[i] + nrm[i] * rng.uniform(-0.65, 0.65) * hw[i]
        r = rng.uniform(5.0, 9.5) * (1 - 0.35 * t[i])
        a0 = rng.uniform(-0.4, 0.4)
        th = np.linspace(a0 + 0.5, a0 + 2.8, 10)
        arc = np.stack([c[0] + r * np.cos(th), c[1] + r * 0.65 * np.sin(th)], -1)
        P.stroke(arc, np.linspace(1.8, 0.7, 10), JIAO, 0.75, dry=0.25, jitter=0.0)
    branches = [  # 控制点, 起止粗细
        ([(1650, 404), (1585, 380), (1520, 378), (1468, 360), (1400, 366), (1330, 350), (1268, 360)], 14, 3.0),
        ([(1712, 470), (1760, 412), (1806, 376), (1860, 334), (1950, 314)], 12, 4.0),
        ([(1750, 610), (1700, 596), (1646, 606), (1606, 596)], 8, 2.5),
        ([(1515, 376), (1490, 340), (1452, 318)], 5, 1.8),
        ([(1405, 365), (1368, 392), (1326, 404)], 4.5, 1.5),
        ([(1792, 380), (1790, 330), (1770, 296)], 5, 1.8),
    ]
    paths = []
    for pts, w0, w1 in branches:
        c = curve_pts(pts, 70)
        P.stroke(c, np.linspace(w0, w1, 70), JIAO, 0.95, dry=0.35, dry_start=0.55, jitter=0.25, near=True)
        paths.append(c)
    clusters = []
    for c in paths:
        for f in (0.3, 0.55, 0.8, 1.0):
            p = c[min(int(f * (len(c) - 1)), len(c) - 1)]
            clusters.append((p[0] + rng.normal(0, 5), p[1] + rng.normal(-8, 4), rng.uniform(30, 50)))
    clusters += [(1600, 360, 46), (1662, 420, 40), (1724, 556, 34), (1778, 650, 28), (1560, 344, 36), (1846, 300, 44)]
    for cx, cy, r in clusters:  # 第一遍：淡墨、略大、错开，作远一层
        needle_fan(P, cx + rng.normal(0, 8), cy + rng.normal(-6, 3), r * 1.15, rng, color=mixc(DAN, ZHONG, 0.5),
                   alpha=0.6, mode="glaze", tilt=rng.uniform(-0.15, 0.15), wash=0.28)
    for cx, cy, r in clusters:  # 第二遍：焦墨
        needle_fan(P, cx, cy, r, rng, color=JIAO, alpha=0.85, tilt=rng.uniform(-0.12, 0.12))

def paint_grass(P: Painting, rng):
    """疏草：几丛细长的墨草，被风吹向左边（与主角的发带同向）；前景几丛大的。"""
    g = ground_edge_y(P.X[0])
    spots = [(1110, 0, 1.0), (1262, 2, 0.9), (1035, 18, 0.8), (930, 4, 0.7), (850, 6, 0.6), (1460, 4, 0.9), (1560, -2, 0.8),
             (1340, 40, 1.0), (1150, 60, 1.1), (700, 20, 0.7), (560, 60, 0.8), (1600, 70, 1.2), (980, 120, 1.4),
             (1700, 180, 1.8), (1300, 170, 1.6), (820, 150, 1.4)]
    for x, dy, s in spots:
        y = float(np.interp(x, P.X[0], g)) + dy + 3
        n = int(rng.integers(4, 8))
        for k in range(n):
            ln = s * rng.uniform(18, 46)
            lean = math.radians(rng.uniform(-38, 8))  # 负 = 向左倒
            bx = x + rng.normal(0, 4 * s)
            ts = np.linspace(0, 1, 12)
            curl = rng.uniform(0.2, 0.9) * (1 if lean < 0 else 0.4)
            xx = bx + np.sin(lean) * ln * ts - curl * 12 * s * ts ** 2
            yy = y - np.cos(lean) * ln * ts + 3 * s * ts ** 2
            hw = np.interp(ts, [0, 0.25, 1], [1.4 * s, 1.6 * s, 0.25]) * rng.uniform(0.7, 1.0)
            P.stroke(np.stack([xx, yy], -1), hw, JIAO if rng.random() < 0.7 else NONG, rng.uniform(0.75, 0.95), jitter=0.1)


# ============================================================== 标题画：渲染件、光与收尾


def ensure_parts(force: bool = False) -> dict:
    """主角背影和石灯笼（Blender）。缺文件或 force 时调 render/title_hero.py（子进程，固定 2 倍参数）。"""
    if force or not (PARTS / "parts.json").exists():
        subprocess.run([sys.executable, str(ART / "render" / "title_hero.py")], check=True)
    meta = json.loads((PARTS / "parts.json").read_text(encoding="utf-8"))
    for k in ("hero_back", "stone_lantern"):
        meta[k]["rgba"] = Image.open(PARTS / f"{k}.png").convert("RGBA")
        meta[k]["emit"] = Image.open(PARTS / f"{k}_emit.png").convert("RGBA")
    return meta


def place(P: Painting, img: Image.Image, anchor, at, scale: float = 1.0, emit: Image.Image | None = None,
          emit_gain: float = 1.0, dim: float = 1.0):
    """按锚点把一张直通 alpha 的图贴进画里（emit 叠进发光层）。返回 图内像素 → 画面像素 的换算函数。"""
    if scale != 1.0:
        size = (max(1, round(img.width * scale)), max(1, round(img.height * scale)))
        img = img.resize(size, Image.LANCZOS)
        emit = emit.resize(size, Image.LANCZOS) if emit is not None else None
    x0, y0 = round(at[0] - anchor[0] * scale), round(at[1] - anchor[1] * scale)
    a = np.asarray(img, np.float64) / 255.0
    xs0, ys0, xs1, ys1 = max(0, x0), max(0, y0), min(W, x0 + img.width), min(H, y0 + img.height)
    sub = a[ys0 - y0: ys1 - y0, xs0 - x0: xs1 - x0]
    sl = (slice(ys0, ys1), slice(xs0, xs1))
    P.over(sub[..., 3] * dim, sub[..., :3], sl)
    P.mark_near(sub[..., 3], sl)
    if emit is not None:
        e = np.asarray(emit, np.float64)[ys0 - y0: ys1 - y0, xs0 - x0: xs1 - x0] / 255.0
        P.emit[sl] += e[..., :3] * e[..., 3:4] * emit_gain
    return lambda px, py: (x0 + px * scale, y0 + py * scale)


def paint_wisp(P: Painting, x, y, s, rng, lights):
    """魂火：一小团向上收尖的冷光（白芯、淡青外焰），外面一圈辉光，并给光照图添一点冷光。"""
    r = int(60 * s)
    sl = (slice(max(0, int(y) - r), min(H, int(y) + r)), slice(max(0, int(x) - r), min(W, int(x) + r)))
    dx, dy = P.X[sl] - x, P.Y[sl] - y
    sway = 2.0 * s * np.sin(dy / (6.0 * s) + x)
    u = (dx - sway * smoothstep(0, -20 * s, dy)) / (5.5 * s)
    v = dy / (9.0 * s)
    # 水滴形：下圆上尖
    width = np.where(v < 0, np.clip(1 + v * 0.55, 0, 1) ** 1.3, np.sqrt(np.clip(1 - v * v, 0, 1)))
    body = smoothstep(1.05, 0.55, np.abs(u) / np.maximum(width, 1e-3)) * smoothstep(1.0, 0.85, v) * smoothstep(-1.9, -1.2, v)
    core = np.exp(-(u ** 2 + ((v - 0.25) / 0.7) ** 2) * 2.2)
    soul = col(S.SOUL_LIGHT)
    e = soul[None, None] * (body * 0.75)[..., None] + mixc(soul, np.ones(3), 0.6)[None, None] * (core * 0.9)[..., None]
    tail = np.exp(-((dx - 1.5 * sway) / (2.2 * s)) ** 2) * smoothstep(-34 * s, -12 * s, dy) * smoothstep(-6 * s, -14 * s, dy)
    e += soul[None, None] * (tail * 0.22)[..., None]
    glow = np.exp(-(dx ** 2 + (dy + 4 * s) ** 2) / (2 * (16 * s) ** 2))
    e += soul[None, None] * (glow * 0.22)[..., None]
    P.emit[sl] += e
    lights.append((x, y, 75 * s, mixc(soul, col(S.NIGHT_AMBIENT), 0.25), 0.16, None))


def eyes_layer() -> tuple[Image.Image, Image.Image, tuple[float, float]]:
    """影妖精灵（2 倍）第 0 帧：本体、发光层，以及眼睛在图里的位置。"""
    base = ART / "out" / "assets@2x" / "shade"
    meta = json.loads((base / "meta.json").read_text(encoding="utf-8"))
    w, h = meta["size"]
    ax, ay = meta["anchor"][0] * w, meta["anchor"][1] * h
    ex, ey = meta["sockets"]["eyes"]["float"]["E"][0]
    return (Image.open(base / "float_E_00.png").convert("RGBA"), Image.open(base / "float_E_00_emit.png").convert("RGBA"),
            (ax + ex, ay + ey))


def light_map(P: Painting, lights, rng) -> np.ndarray:
    """光照图：夜色底（略有起伏）+ 月光（月亮附近亮，往左下沉下去）+ 各个暖光 / 冷光。
    灯光只照得到近处（P.near：中景地面、石、松、人）——那里按球形衰减，地上另有一片压扁的光池；
    远山和天空只染到一小团空气里的光晕。光圈边缘随角度起伏，过渡带里有一点水渍般的浓淡，不是规整的圆。"""
    amb = col(S.NIGHT_AMBIENT)
    lm = amb[None, None] * (1 + 0.15 * noise(rng, (H, W), (300.0, 120.0)))[..., None]
    mx, my, mr = MOON
    d = np.hypot(P.X - mx, (P.Y - my) * 1.1)
    moon_col = mixc(col("#C8D3E6"), col(S.PAPER), 0.25)
    moon = 0.035 + 0.20 * np.exp(-(d / 650.0) ** 2) + 0.16 * np.exp(-(d / 210.0) ** 2)
    lm += moon[..., None] * moon_col
    # 雾在月光里微微发亮（离月亮越远越暗），近处的东西挡在雾前面
    lm += (P.mist * (1 - P.near) * (0.10 + 0.30 * np.exp(-(d / 900.0) ** 2)))[..., None] * moon_col
    gran = noise(rng, (H, W), 26.0)
    near = P.near
    for x, y, R, c, inten, ground_y in lights:
        r0 = int(R * 1.3) + 4
        sl = (slice(max(0, int(y) - r0), min(H, int(max(y, ground_y or y)) + r0)), slice(max(0, int(x) - r0), min(W, int(x) + r0)))
        dx, dy = P.X[sl] - x, P.Y[sl] - y
        th = np.arctan2(dy, dx)
        k = 1 + 0.07 * np.sin(3 * th + x * 0.01) + 0.05 * np.sin(5 * th + 1.3) + 0.03 * np.sin(9 * th + y)
        rr = np.hypot(dx, dy) / (R * k)
        f = np.clip(1 - rr ** 2, 0, 1) ** 2
        if ground_y is not None:  # 地上的光池：灯下偏前、压扁的椭圆
            pr = np.hypot(dx / (R * 0.95 * k), (P.Y[sl] - ground_y) / (R * 0.32 * k))
            f = np.maximum(f, 0.62 * np.clip(1 - pr ** 2, 0, 1) ** 2.2)
        f = f * (1 + 0.12 * gran[sl] * np.clip(4 * f * (1 - f), 0, 1))
        f = f * (1 - 0.16 * np.exp(-((f - 0.07) / 0.035) ** 2))  # 光圈边上一道略暗的“水痕”，像一笔染开的边
        air = 0.22 * np.clip(1 - (rr / 0.42) ** 2, 0, 1) ** 2
        nm = near[sl]
        lm[sl] += (np.clip(f, 0, 1.1) * nm + air * (1 - nm))[..., None] * (np.asarray(c) * inten)[None, None]
    return lm

def bloom(e: np.ndarray, sigma: float) -> np.ndarray:
    return np.stack([blur(e[..., c], sigma) for c in range(3)], -1)


def paint_title(rng_seed: int = 2026, force_render: bool = False) -> tuple[Image.Image, dict]:
    t0 = time.perf_counter()
    parts = ensure_parts(force_render)
    t_parts = time.perf_counter() - t0
    rng = np.random.default_rng(rng_seed)
    P = Painting(rng)
    paper0 = P.rgb.copy()
    paint_sky(P, rng)
    paint_mountains(P, rng)
    paint_ground(P, rng)
    paint_ground_detail(P, rng)
    paint_rock(P, rng, [(1588, 846), (1622, 806), (1668, 778), (1730, 758), (1800, 742), (1880, 728), (1960, 724)],
               [(1588, 846), (1572, 920), (1582, 1000), (1566, 1095)],
               [(1600, 850), (1660, 826), (1740, 808), (1830, 790), (1960, 770)])
    paint_pine(P, rng)
    paint_grass(P, rng)
    lights = []
    # 石灯笼（远的先画）
    sl_meta = parts["stone_lantern"]
    for x, y, s in sorted(STONE_LANTERNS, key=lambda t: t[1]):
        wash_blob(P, x + 4, y + 2, 46 * s * 1.4, 10 * s * 1.4, ZHONG, 0.5, rng)
        to = place(P, sl_meta["rgba"], sl_meta["feet"], (x, y), s, sl_meta["emit"], emit_gain=0.85)
        fx, fy = to(*sl_meta["flame"])
        lights.append((fx, fy, 190 * s, col(S.FLAME_LIGHT), 0.55, y))
    # 主角：脚下一团淡墨影
    hb = parts["hero_back"]
    wash_blob(P, HERO_FEET[0] + 6, HERO_FEET[1] + 2, 58, 13, ZHONG, 0.55, rng)
    to = place(P, hb["rgba"], hb["feet"], HERO_FEET, 1.0, hb["emit"], emit_gain=1.25)
    lx, ly = to(*hb["lantern"])
    lights.append((lx, ly, 480.0, mixc(col(S.LANTERN_LIGHT), np.ones(3), 0.22), 1.12, HERO_FEET[1] + 8))
    lights.append((lx, ly, 170.0, col(S.LANTERN_LIGHT), 0.35, None))
    # 黑暗里的妖：影妖本体几乎看不见，只剩眼睛
    body, emit, (ex, ey) = eyes_layer()
    for x, y, s, flip in EYES:
        b, e_ = (body.transpose(Image.FLIP_LEFT_RIGHT), emit.transpose(Image.FLIP_LEFT_RIGHT)) if flip else (body, emit)
        ax = (body.width - ex) if flip else ex
        place(P, b, (ax, ey), (x, y), s, e_, emit_gain=2.2, dim=0.3)
    for x, y, s in WISPS:
        paint_wisp(P, x, y, s, rng, lights)
    # 月亮：月轮自己发一点光，被挡在前面的薄云按透过率减弱
    mx, my, mr = MOON
    dm = np.hypot(P.X - mx, P.Y - my)
    disc = smoothstep(mr + 1.3, mr - 1.3, dm)
    trans = np.clip(P.rgb.mean(-1) / paper0.mean(-1), 0, 1)
    moon_rgb = mixc(col(S.PAPER), np.ones(3), 0.35)
    P.emit += (disc * trans * 0.36)[..., None] * moon_rgb
    P.emit += (np.exp(-np.maximum(dm - mr, 0) / 26.0) * (1 - disc) * 0.10)[..., None] * col("#C8D3E6")
    # ---- 打光：画 × 光照图 + 发光层 + 辉光
    lm = light_map(P, lights, rng)
    out = P.rgb * np.clip(lm, 0, 1.08)
    e = P.emit
    out = out * (1 - np.clip(e.max(-1, keepdims=True), 0, 1) * 0.6) + e + 0.55 * bloom(e, 5.0) + 0.45 * bloom(e, 22.0)
    # 灯笼本身的光晕（大而淡）
    dl = np.hypot(P.X - lx, P.Y - ly)
    out += (np.exp(-(dl / 90.0) ** 2) * 0.12 + np.exp(-(dl / 260.0) ** 2) * 0.05)[..., None] * col(S.LANTERN_LIGHT)
    # ---- 收尾：纸纹在暗处也看得见、四角压暗、左边更沉
    rel = paper0.mean(-1) / paper0.mean()
    rel = rel - blur(rel, 40.0) / blur(np.ones_like(rel), 40.0) + 1.0  # 只要纸的纹理，不要大块浓淡（那已经画进去了）
    lum = out.mean(-1, keepdims=True)
    gain = 1.6 + 2.0 * (1 - smoothstep(0.05, 0.5, lum))  # 暗处把纸纹拉出来，亮处少拉
    out = out * (1 + gain * (rel[..., None] - 1)) + 0.02 * (rel[..., None] - 1)
    rx = (P.X - W * 0.62) / (W * 0.62)
    ry = (P.Y - H * 0.48) / (H * 0.62)
    vig = 1 - 0.42 * smoothstep(0.55, 1.35, np.hypot(rx, ry))
    vig *= 1 - 0.22 * smoothstep(0.45, 0.0, P.X / W)
    out = out * vig[..., None]
    img = Image.fromarray((np.clip(out, 0, 1) * 255 + 0.5).astype(np.uint8), "RGB")
    info = {"lantern_px": [round(lx, 1), round(ly, 1)], "time_s": round(time.perf_counter() - t0, 1),
            "parts_s": round(t_parts, 1), "render_timings": parts.get("timings", {})}
    return img, info


# ============================================================== 审图

LOGO_AT = (64, 58)  # 标题字在 1920×1080 上的左上角（审图用的建议位置）
LOGO_SCALE = 0.80
MENU = ["开始", "心灯", "设置", "退出"]
MENU_AT = (150, 560)  # 第一项文字的左上角
MENU_STEP = 66


def compose_review(title: Image.Image, logo: Image.Image) -> Image.Image:
    """标题画 + 标题字 + 模拟竖排菜单（思源宋体 500，32 像素；第一项是选中态）。"""
    im = title.convert("RGBA")
    lg = logo.resize((round(logo.width * LOGO_SCALE), round(logo.height * LOGO_SCALE)), Image.LANCZOS)
    im.alpha_composite(lg, LOGO_AT)
    txt = Image.new("RGBA", im.size, (0, 0, 0, 0))
    dr = ImageDraw.Draw(txt)
    f = font("serif", 32, weight=500)
    paper = S.hex_to_rgb(S.PAPER)
    for i, t in enumerate(MENU):
        x, y = MENU_AT[0], MENU_AT[1] + i * MENU_STEP
        sel = i == 0
        if sel:  # 选中：前面一点灯火，字更亮
            cx, cy = x - 26, y + 21
            glow = Image.new("RGBA", im.size, (0, 0, 0, 0))
            ImageDraw.Draw(glow).ellipse([cx - 9, cy - 9, cx + 9, cy + 9], fill=S.hex_to_rgb(S.LANTERN_LIGHT) + (150,))
            txt.alpha_composite(glow.filter(ImageFilter.GaussianBlur(6)))
            dr.ellipse([cx - 3.5, cy - 3.5, cx + 3.5, cy + 3.5], fill=S.hex_to_rgb(S.mix(S.LANTERN_LIGHT, "#FFFFFF", 0.5)) + (255,))
        dr.text((x, y), t, font=f, fill=paper + ((255,) if sel else (165,)))
    sh = txt.split()[3].filter(ImageFilter.GaussianBlur(3))
    shadow = Image.new("RGBA", im.size, (8, 9, 14, 0))
    shadow.putalpha(sh.point(lambda v: int(v * 0.6)))
    im.alpha_composite(shadow)
    im.alpha_composite(txt)
    return im.convert("RGB")


def portrait_review(path: Path) -> None:
    """头像：256（2 倍文件原大）、128（1 倍文件原大）、64（游戏 HUD 显示大小，由 2 倍缩小），纸底和夜底各一行。"""
    p2 = ART / "out" / "assets@2x" / "portrait" / "portrait_hero.png"
    p1 = ART / "out" / "assets" / "portrait" / "portrait_hero.png"
    if not p2.exists():
        print("[review] 缺头像，先运行 art/render/portrait.py --all")
        return
    a2 = Image.open(p2).convert("RGBA")
    a1 = Image.open(p1).convert("RGBA") if p1.exists() else a2.resize((128, 128), Image.LANCZOS)
    a64 = a2.resize((64, 64), Image.LANCZOS)
    pad = 24
    row_h = 256 + pad * 2
    out = Image.new("RGB", (pad * 5 + 256 + 128 + 64 + 120, row_h * 2), S.hex_to_rgb(S.PAPER))
    f = font("serif", 16)
    for r, bgc in enumerate((S.PAPER, S.NIGHT_AMBIENT)):
        bg = Image.new("RGBA", (out.width, row_h), S.hex_to_rgb(bgc) + (255,))
        x = pad
        for im, lab in ((a2, "256（2 倍）"), (a1, "128（1 倍）"), (a64, "64（HUD）")):
            bg.alpha_composite(im, (x, pad + (256 - im.height) // 2))
            ImageDraw.Draw(bg).text((x, row_h - pad + 2), lab, font=f,
                                    fill=S.hex_to_rgb(S.INK["dan"] if r == 0 else S.INK["qing"]) + (255,))
            x += im.width + pad
        # HUD 里的样子：头像旁边一个等级徽记的占位
        hud = a64.copy()
        bg.alpha_composite(hud, (x + 20, pad + 96))
        d = ImageDraw.Draw(bg)
        d.ellipse([x + 70, pad + 136, x + 92, pad + 158], fill=S.hex_to_rgb(S.INK["jiao"]) + (255,),
                  outline=S.hex_to_rgb(S.ACCENT["tenghuang"]) + (255,), width=2)
        out.paste(bg.convert("RGB"), (0, r * row_h))
    out.save(path, optimize=True)


# ============================================================== 主程序


def main(argv: list[str]) -> int:
    t0 = time.perf_counter()
    OUT.mkdir(parents=True, exist_ok=True)
    REVIEW.mkdir(parents=True, exist_ok=True)
    logo, info = make_logo()
    save_rgba(logo, OUT / "logo.png")
    logo_review(logo, REVIEW / "logo_review.png")
    print(f"[logo] {logo.width}×{logo.height} {time.perf_counter() - t0:.1f}s → {OUT / 'logo.png'}")
    if "--logo" in argv:
        return 0
    title, tinfo = paint_title(force_render="--render" in argv)
    title.save(OUT / "title.png", optimize=True)
    print(f"[title] {title.width}×{title.height} {tinfo['time_s']}s → {OUT / 'title.png'}")
    rev = compose_review(title, logo)
    rev.save(REVIEW / "title_review.png", optimize=True)
    rev.resize((W // 2, H // 2), Image.LANCZOS).save(REVIEW / "title_review_half.png", optimize=True)
    portrait_review(REVIEW / "portrait_review.png")
    (OUT / "title_info.json").write_text(json.dumps({"logo": info, "title": tinfo, "logo_at": LOGO_AT, "logo_scale": LOGO_SCALE,
                                                     "menu_at": MENU_AT}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[review] → {REVIEW}（title_review.png、title_review_half.png、logo_review.png、portrait_review.png）"
          f"，共 {time.perf_counter() - t0:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
