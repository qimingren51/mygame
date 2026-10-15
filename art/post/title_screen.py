#!/usr/bin/env python3
"""提灯夜行 · 标题画、标题字和审图（Pillow + numpy，不用 Blender）。

标题画（art/out/screens/title.png，1920×1080 不透明 RGB，只出桌面版）：
  一幅夜里的水墨长卷。先在宣纸上把整幅画画出来——远山三层，一层比一层近、一层比一层重，层间隔着雾，山有阴阳
  （朝月的一面淡），近山有披麻皴和苔点；月亮是留白（烘云托月）；中景一道山脊，枯笔勾边、苔点、疏草，右边一株老松，
  山脊上两座石灯笼；主角走在山路上、背对观众，右手持杖把灯笼挑到身侧。主角和石灯笼是写意画法，和灯驿长卷的人物
  同一套笔法（ink_figure.py：留白、洇墨、提按的墨线、侧锋铺衣、飞白）。
  再像游戏里一样打光：画 × 光照图 + 发光层。光照图 = 夜色底 + 月光 + 灯笼的暖光圈（边缘按水渍打散）+ 石灯笼的火光。
  黑暗里有几团魂火、远处两三对妖眼（影妖精灵的 _emit 眼睛）。最后整幅叠纸纹、压暗四角。纸用短而软的纤维
  （soft_paper_tile），暗处放大以后读作纸的纤维，不像裂纹。
  左边约 40% 保持安静、够暗，放竖排菜单；左上留给标题字，远山在这两处压淡。

标题字（art/out/screens/logo.png，透明 RGBA）：
  “提灯夜行”用马善政毛笔楷书写成真墨：笔画里有顺着笔势的飞白、收笔处积墨、墨边洇进纸纤维；
  旁边一方朱砂印“夜行”。外面一圈很淡的纸色晕（暗底上托住墨色，纸底上看不出来）。直通 alpha，颜色扩进透明区。

审图（art/out/review@2x/）：title_review.png（标题画 + 标题字 + 模拟竖排菜单，1920×1080）、
  title_review_half.png（半尺寸）、logo_review.png（标题字在纸底 / 夜底）、portrait_review.png（头像 256/128/64，纸底 / 夜底）。
  --sample 只出候选 art/out/screens/title_candidate.png 和新旧对比 title_fix_sample.png（整幅 + 主角、石灯笼、远山、
  夜空纸纹的 2 倍裁切），不动 title.png、logo.png 和其他审图。

运行（在仓库根目录下）：
    art/.venv/bin/python art/post/title_screen.py            # 全部
    art/.venv/bin/python art/post/title_screen.py --sample   # 只出候选和新旧对比
    art/.venv/bin/python art/post/title_screen.py --logo     # 只出标题字
固定随机种子，重复运行结果相同。出图参数固定为 2 倍密度（桌面版），与环境变量无关。
"""

from __future__ import annotations

import os

os.environ["LANTERN_ART_DENSITY"] = "2"  # 标题画只有桌面版：先定密度，再导入 style / vfx_textures

import json  # noqa: E402
import math  # noqa: E402
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
REVIEW = ART / "out" / "review@2x"
W, H = 1920, 1080

col, smoothstep = V.col, V.smoothstep
PAPER = col(S.PAPER)
PAPER_SH = col(S.PAPER_SHADOW)
JIAO, NONG, ZHONG, DAN, QING = (col(S.INK[k]) for k in ("jiao", "nong", "zhong", "dan", "qing"))
ZHUSHA, TENG, ZHESHI = col(S.ACCENT["zhusha"]), col(S.ACCENT["tenghuang"]), col(S.ACCENT["zheshi"])


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


def soft_paper_tile() -> np.ndarray:
    """标题画的纸（2 倍密度 1024²，可平铺）：vfx_textures.make_paper 的配方，但纤维短、弯、软，没有几百像素长的直纤维——
    那种纤维在夜空里被收尾的纸纹增益放大以后，像一道道细裂纹。"""
    size = V.dpx(512)
    rng = np.random.default_rng(1207)
    sh = (size, size)
    dark = np.zeros(sh)  # 正值 = 朝 PAPER_SHADOW 变暗，负值 = 朝更白更透的纸色变亮
    light_dir = col("#F8F2E4") - PAPER
    dark += 0.13 * V.fbm1(rng, sh, (70.0, 30.0, 12.0), (0.3, 0.7, 0.5))  # 纸浆厚薄
    floc = V.noise1(rng, sh, 3.2) + 0.6 * V.noise1(rng, sh, 6.0)
    dark += 0.08 * np.tanh(floc / floc.std())  # 絮
    dark += V.fibre_layer(rng, size, 2, 560, (4, 15), (0.12, 0.24), 0.7, 0.22)  # 短纤维：深、亮各一组，弯、软
    dark -= V.fibre_layer(rng, size, 2, 560, (4, 13), (0.12, 0.26), 0.75, 0.22)
    dark += V.fibre_layer(rng, size, 2, 900, (2, 8), (0.04, 0.10), 0.55, 0.12)  # 纸面的毛
    dark -= V.fibre_layer(rng, size, 2, 800, (2, 7), (0.04, 0.10), 0.55, 0.12)
    dark += 0.03 * V.noise1(rng, sh, 0.55)  # 纸粒
    rgb = PAPER + np.clip(dark, 0, None)[..., None] * (PAPER_SH - PAPER) + np.clip(-dark, 0, None)[..., None] * light_dir * 1.6
    return np.clip(np.round(rgb * 255.0), 0, 255) / 255.0


def soft_paper_canvas(rng) -> np.ndarray:
    """整幅宣纸，拼法和画布尺度的浓淡同 paper_canvas，纸用 soft_paper_tile。"""
    tile = soft_paper_tile()
    big = np.concatenate([tile, tile[:, ::-1]], 1)
    big = np.concatenate([big, big[::-1]], 0)
    out = big[37:37 + H, 61:61 + W].copy()
    cloud = fbm(rng, (H, W), (260.0, 90.0, 30.0), (0.5, 0.35, 0.15))
    return mixc(out, out * (PAPER_SH / PAPER), np.clip(0.18 + 0.16 * cloud, 0, 1) * 0.6)


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


def range_layer(P: Painting, ridge, color, alpha, fade, rng, *, mist_from, mist_len=70.0, edge=0.45, soft=1.4, streak=0.3,
                shade=0.0, quiet=None):
    """一层远山（mountain_layer 的写法）+ 阴阳：朝月亮的一面淡（留白多）、背月的一面重，往下渐平，山脚隐进雾里。
    soft 是山脊边缘的虚实（越远越虚）；quiet（(H, W)，0..1）处压淡：标题字和菜单后面。"""
    jit = 1.2 * noise(rng, (H, W), 1.2)
    depth = P.Y - ridge[None, :] + jit
    inside = smoothstep(-soft, soft * 1.2, depth)
    top = np.exp(-np.maximum(depth, 0) / 7.0)
    body = 0.35 + 0.65 * np.exp(-np.maximum(depth, 0) / fade)
    tex = noise(rng, (H, W), (40.0, 2.5), angle=math.pi / 2 + 0.25) * 0.6 + noise(rng, (H, W), (14.0, 1.4), angle=math.pi / 2 - 0.3) * 0.4
    a = alpha * inside * (body * (1 + streak * tex) + edge * top)
    if shade:
        # 山坡朝向：山脊线的斜率，贴着山脊用细的、往下用粗的（小起伏只管山脊附近，往下看大山势）
        s1 = np.gradient(blur(ridge[None, :], (5.0, 0))[0])
        s2 = np.gradient(blur(ridge[None, :], (34.0, 0))[0])
        w = smoothstep(0, 140, depth)
        s = s1[None, :] * (1 - w) + s2[None, :] * w
        facing = np.tanh(2.2 * s * np.sign(MOON[0] - P.X))  # > 0：朝着月亮
        k = np.exp(-np.maximum(depth, 0) / (fade * 1.6))
        a = a * (1 + shade * k * (np.clip(-facing, 0, 1) - 0.75 * np.clip(facing, 0, 1)))
    a = a * smoothstep(mist_from + mist_len, mist_from, P.Y + 25 * noise(rng, (H, W), (90.0, 14.0)))
    if quiet is not None:
        a = a * (1 - quiet)
    P.glaze(np.clip(a, 0, 0.95), color)


def hemp_cun(P: Painting, ridge, color, rng, mist_from, groups, *, strength=0.35, ln=(50, 110)):
    """披麻皴：groups = [(x, 笔数)]，每组三五笔从山脊往下、顺着山势的长弧（大致平行、略有聚散），淡墨，略干；雾里不画。"""
    slope = np.gradient(blur(ridge[None, :], (10.0, 0))[0])
    for gx, n in groups:
        sgn = 1.0 if slope[int(np.clip(gx, 0, W - 1))] > 0 else -1.0  # 朝下坡的方向
        base_ang = math.atan2(abs(slope[int(np.clip(gx, 0, W - 1))]) + 0.55, sgn)
        for k in range(n):
            x = gx - (k - (n - 1) / 2) * rng.uniform(7, 12) * sgn
            y = ridge[int(np.clip(x, 0, W - 1))] + rng.uniform(3, 12)
            if y > mist_from - 30:
                continue
            ang = base_ang + rng.normal(0, 0.06)
            length = rng.uniform(*ln) * (1 - 0.15 * abs(k - (n - 1) / 2))
            ts = np.linspace(0, 1, 18)
            th = ang + rng.uniform(0.15, 0.4) * -sgn * ts  # 越往下越平，弧向山外
            pts = np.stack([x + np.cumsum(np.cos(th)) * length / 18, y + np.cumsum(np.sin(th)) * length / 18], -1)
            hw = np.interp(ts, [0, 0.15, 0.7, 1], [0.7, rng.uniform(1.3, 2.0), 1.2, 0.4])
            P.stroke(pts, hw, color, strength * rng.uniform(0.7, 1.15), dry=0.42, dry_start=0.3, jitter=0.2, mode="glaze")


def ridge_dots(P: Painting, ridge, rng, xs, color, *, n=6, alpha=0.7):
    """苔点：山脊上几簇淡墨点。"""
    for gx in xs:
        for _ in range(n):
            x = gx + rng.normal(0, 14)
            y = ridge[int(np.clip(x, 0, W - 1))] + rng.uniform(0.5, 4)
            r = rng.uniform(1.2, 2.6)
            P.dot(x, y, r * rng.uniform(1.1, 1.6), r, color, alpha * rng.uniform(0.7, 1.0), ang=rng.uniform(-0.4, 0.4))


def mist_band(P: Painting, rng, lo, hi, strength, amp=28.0, glow=0.5):
    """山与山之间的一道雾：纸色略亮，高低随 x 起伏，浓淡成片；夜里被月光照着微微发亮（P.mist）。"""
    wav = blur(rng.standard_normal((1, W)), (90.0, 0))[0]
    yb = P.Y + (amp * wav / (wav.std() + 1e-9))[None, :]
    fog = smoothstep(lo, lo + (hi - lo) * 0.55, yb) * smoothstep(hi, hi - (hi - lo) * 0.3, yb)
    fog = fog * np.clip(0.35 + 0.65 * smoothstep(-1.2, 1.2, noise(rng, (H, W), (130.0, 22.0))), 0, 1)
    P.over(np.clip(fog * strength, 0, 1), mixc(PAPER, np.ones(3), 0.2))
    P.mist = np.maximum(P.mist, np.clip(fog * glow, 0, 1))


def title_quiet(P: Painting) -> np.ndarray:
    """标题字（左上，连光晕）和菜单（左下）后面要安静：远山在这里压淡。返回 (H, W)，0..1。"""
    def box(x0, y0, x1, y1, soft):
        d = np.maximum(np.maximum(x0 - P.X, P.X - x1), np.maximum(y0 - P.Y, P.Y - y1))
        return smoothstep(soft, 0, d)

    return np.maximum(0.55 * box(60, 40, 960, 360, 90), 0.35 * box(90, 520, 420, 840, 120))


def paint_ranges(P: Painting, rng):
    """远山三层，层层隐进雾里：
      远  最高最淡、边缘虚，主峰群在中右（主角望着的方向）和月下，左边只有低低的一抹（标题字下面）；
      中  峰位和远层错开，一高一低，几笔淡皴；
      近  低而重，两座有形的山头，披麻皴、苔点。
    各层都有阴阳（朝月的一面淡），层与层之间一道雾，最后山谷里一道雾（同旧版）。标题字和菜单后面压淡。"""
    xs = np.arange(W) + 0.5
    q = title_quiet(P)
    far = ridge_line(xs, [(1150, 300, 230, 200, 1.45), (1330, 230, 150, 190, 1.3), (1780, 250, 210, 240, 1.35),
                          (1560, 150, 140, 150, 1.2), (620, 120, 300, 260, 1.0), (180, 90, 260, 280, 1.0)], 560, rng,
                     rough=4.0, rough_sigma=16.0)
    range_layer(P, far, mixc(QING, SKY_INK, 0.35), 0.32, 150.0, rng, mist_from=560, mist_len=90.0, edge=0.22, soft=3.0,
                streak=0.2, shade=0.4, quiet=q)
    mist_band(P, rng, 430, 600, 0.36, amp=34.0)
    mid = ridge_line(xs, [(905, 215, 170, 150, 1.5), (760, 150, 130, 120, 1.3), (1470, 170, 150, 170, 1.4),
                          (1640, 120, 120, 140, 1.2), (390, 110, 200, 180, 1.1), (1240, 95, 120, 120, 1.1)], 650, rng,
                     rough=5.0, rough_sigma=18.0)
    range_layer(P, mid, mixc(QING, DAN, 0.55), 0.40, 105.0, rng, mist_from=650, mist_len=75.0, edge=0.4, soft=1.8, streak=0.3,
                shade=0.55, quiet=q)
    hemp_cun(P, mid, mixc(QING, ZHONG, 0.5), rng, 650, [(880, 3), (950, 3), (1440, 3), (1500, 3), (735, 2)], strength=0.22,
             ln=(35, 70))
    mist_band(P, rng, 540, 690, 0.34, amp=30.0)
    near = ridge_line(xs, [(1330, 132, 190, 160, 1.25), (560, 112, 210, 180, 1.15), (1010, 70, 140, 150, 1.0),
                           (1760, 100, 160, 200, 1.1)], 735, rng, rough=6.0, rough_sigma=18.0)
    range_layer(P, near, mixc(DAN, ZHONG, 0.15), 0.48, 80.0, rng, mist_from=735, mist_len=70.0, edge=0.5, soft=1.2, streak=0.35,
                shade=0.7, quiet=q)
    hemp_cun(P, near, mixc(DAN, NONG, 0.45), rng, 735, [(1262, 4), (1300, 3), (1395, 4), (1440, 3), (505, 4), (600, 3), (1710, 3),
                                                       (1060, 3), (960, 3)], strength=0.4)
    ridge_dots(P, near, rng, [1300, 1350, 560, 600, 1720], mixc(ZHONG, NONG, 0.4), n=5, alpha=0.6)
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


# ============================================================== 标题画：主角和石灯笼（写意）

WASH_L, WASH_M, WASH_D = mixc(QING, DAN, 0.5), mixc(DAN, ZHONG, 0.35), mixc(ZHONG, NONG, 0.3)  # 淡、中、重三档墨（同灯驿长卷）
SKIN = mixc(PAPER, ZHESHI, 0.10)  # 耳朵和手：纸色里一丝赭
HAIR = mixc(JIAO, NONG, 0.15)
LAMP_LIGHT, FLAME_LIGHT = col(S.LANTERN_LIGHT), col(S.FLAME_LIGHT)
LANTERN_AT = (168.2, -240.2)  # 灯笼光心（主角局部坐标，原点在脚底）：画面 (1353.2, 665.8)，和旧版渲染件一样


def _ink():
    """人物的笔法（ink_figure 反过来 import 本模块，所以用到时再导入）。"""
    import ink_figure

    return ink_figure


def hero_pose(x, y):
    """主角上身的姿态（局部坐标 → 局部坐标）：往左上的山路走，上身微微前倾、朝路的方向偏，头略低看着脚下，
    持灯的右肩抬起。脚和下摆不动。"""
    h = -y
    lean = 0.055 * max(h - 70.0, 0.0)
    tilt = 0.09 * float(smoothstep(150.0, 215.0, h))
    drop = 4.0 * float(smoothstep(228.0, 250.0, h))
    return x - lean, y - tilt * x + drop


def paint_hero(P: Painting, rng, lights) -> tuple[float, float]:
    """守灯人背影（docs/LORE.md：白衣墨氅，背一柄长剑，右手提灯），往左上的山路走：左脚迈出去（袍子底下只露一点脚跟），
    右脚在后、脚跟抬起露出鞋底，上身前倾，持灯的右肩抬起；墨氅和发带被同一阵风吹向左，下摆往左扬起。
    写意画法同灯驿长卷的人物（ink_figure）：擦出留白，淡墨淡彩洇两层，墨氅用长短粗细不一的侧锋铺出来（背灯的左边重），
    几道被步子扯斜的衣褶，再用提按有变化的焦墨勾轮廓，下摆飞白、断续。灯笼是朱砂纸，纸里透出暖光（发光层），
    焦墨的顶、底和描边，底下一绺穗子；杖头一点铜色的钩。
    大小、脚底、灯笼光心和光池都和旧版的渲染件一样。返回灯笼光心（画面坐标）。"""
    F = _ink()
    f = F.Fig(P, *HERO_FEET, pose=hero_pose)  # 身体：跟着姿态走
    f0 = F.Fig(P, *HERO_FEET)  # 杖和灯笼：灯笼的光心固定

    def rigid(ctrl):
        """飘带、穗子这类挂在身上的东西：整条跟着根部平移，不随姿态变形。"""
        x0, y0 = ctrl[0]
        px, py = hero_pose(x0, y0)
        return f0.pts([(x + px - x0, y + py - y0) for x, y in ctrl])

    wash_blob(P, HERO_FEET[0] + 2, HERO_FEET[1] + 2, 56, 12, ZHONG, 0.55, rng)
    # ---- 脚：左脚在前（远、高），袍子底下只露脚跟；右脚在后，脚跟抬起，露出靴筒的背面和鞋底
    f.fill([(-23, -13), (-9, -13), (-8, -5), (-12, -2), (-21, -3)], JIAO, 0.95, mode="over", rim=0.0)
    wash_blob(P, *f.pt(18, -1), 8, 2.2, JIAO, 0.6, rng)  # 脚尖点地处（被脚跟挡着）的一点影
    boot = [(7, -42), (24, -42), (25, -26), (22, -17), (11, -16), (7, -28)]
    f.fill(boot, mixc(JIAO, NONG, 0.25), 0.97, mode="over", rim=0.0)
    f.brush([(9, -40), (8, -26), (11, -17)], 1.0, color=JIAO, nail=0.3, tail=0.2)
    f.fill([(10, -17), (23, -18), (21, -10), (12, -9)], mixc(DAN, ZHONG, 0.3), 0.95, mode="over", rim=0.0, smooth=False)  # 鞋底
    f.brush([(11, -9.5), (21, -10.5)], 0.9, color=JIAO, smooth=False, nail=0.2, tail=0.2, press=0.0)
    # ---- 白衣下摆：墨氅下面露出一截，被风吹向左；后腿处被小腿挑起，开衩里露出靴筒
    robe = [(-50, -64), (-58, -44), (-68, -26), (-50, -17), (-32, -20), (-16, -13), (-2, -20), (5, -36), (16, -43), (26, -40),
            (34, -23), (46, -25), (46, -64)]
    f.knock(robe)
    f.wash(robe, WASH_L, 0.25, off=(-1.0, 0.8), soft=1.8)
    f.wash([(-58, -44), (-68, -26), (-50, -17), (-36, -20), (-40, -46)], WASH_M, 0.24, soft=1.6)
    f.brush([(-69, -26), (-50, -16), (-32, -20), (-16, -12), (-2, -20), (5, -36), (16, -44)], 1.2, color=JIAO, press=1.5,
            dry=0.35, dry_start=0.7)
    f.brush([(26, -41), (34, -23), (46, -25)], 1.1, color=JIAO, press=1.4, nail=0.4)
    f.brush([(-52, -56), (-58, -42), (-69, -26)], 0.9, color=NONG, nail=0.4)
    f.brush([(45, -54), (46, -26)], 0.8, color=NONG, nail=0.4)
    for a, b, c in (((-28, -50), (-36, -34), (-46, -20)), ((-8, -50), (-10, -32), (-15, -15)), ((30, -50), (33, -36), (35, -25))):
        f.brush([a, b, c], 0.6, color=NONG, alpha=0.7, nail=0.3, tail=0.5)
    # ---- 左袖：白色广袖垂在墨氅边上，往后摆、袖口被风带向左
    lsl = [(-34, -216), (-46, -204), (-55, -180), (-63, -152), (-72, -128), (-77, -118), (-64, -112), (-50, -114), (-42, -136),
           (-38, -180)]
    f.knock(lsl)
    f.wash(lsl, WASH_L, 0.28, off=(-1.2, 1.0), soft=1.6)
    f.wash([(-46, -200), (-55, -178), (-63, -150), (-72, -128), (-60, -130), (-52, -160)], WASH_M, 0.3, soft=1.5)
    f.brush([(-36, -217), (-46, -204), (-55, -180), (-63, -152), (-72, -128), (-78, -118)], 1.4, color=JIAO, press=1.5, dry=0.25)
    f.brush([(-78, -118), (-64, -111), (-50, -114)], 1.0, color=JIAO, nail=0.3)
    f.brush([(-50, -170), (-56, -136)], 0.6, color=NONG, alpha=0.7)
    F.hand(f, -52, -107, 3.3, skin=SKIN)
    # ---- 墨氅：擦出留白，淡淡铺一层底，背灯的左边罩重；再用长短粗细不一的侧锋铺开
    left = [(-14, -238), (-28, -232), (-36, -220), (-41, -204), (-43, -180), (-45, -150), (-49, -118), (-56, -94), (-67, -76),
            (-81, -66), (-96, -62)]
    right = [(14, -238), (26, -232), (36, -222), (46, -210), (53, -196), (51, -176), (50, -150), (50, -116), (49, -82), (46, -52)]
    hem = [(-96, -62), (-80, -56), (-62, -51), (-42, -44), (-20, -48), (2, -41), (24, -46), (46, -52)]
    cloak = left + hem[1:-1] + right[::-1]
    f.knock(cloak)
    f.wash(cloak, mixc(ZHONG, NONG, 0.4), 0.76, soft=1.8, tex=0.1)
    f.shade(cloak, NONG, 0.5, side=-1.0)
    ink = mixc(NONG, JIAO, 0.2)
    sweeps = [  # 控制点, 半宽, 浓度, 收笔干到哪
        ([(-30, -222), (-36, -170), (-42, -122), (-56, -88), (-82, -66)], 9.0, 0.6, 0.72),
        ([(-16, -230), (-20, -172), (-26, -112), (-38, -72), (-60, -53)], 11.0, 0.55, 0.78),
        ([(2, -232), (0, -182), (-4, -134)], 8.0, 0.5, 0.6),
        ([(16, -228), (21, -170), (17, -114), (6, -72), (-14, -49)], 6.5, 0.42, 0.75),
        ([(33, -218), (38, -168), (40, -122), (36, -84), (26, -50)], 5.5, 0.32, 0.7),
        ([(45, -200), (47, -152), (46, -108)], 3.2, 0.28, 0.55),
        ([(-6, -106), (-18, -78), (-36, -54)], 6.0, 0.5, 0.6),  # 被步子扯斜的
        ([(30, -100), (16, -72), (-2, -47)], 4.5, 0.4, 0.6),
        ([(-46, -98), (-64, -76), (-90, -63)], 5.0, 0.55, 0.55),  # 往左扬起的下摆
        ([(-24, -160), (-30, -128)], 4.0, 0.35, 0.5),
    ]
    for pts, w, a, ds in sweeps:
        f.brush(pts, w * rng.uniform(0.9, 1.1), color=ink, alpha=min(0.88, 1.3 * a * rng.uniform(0.9, 1.08)), mode="glaze", nail=0.25, tail=0.35,
                press=0.4, dry=0.5, dry_start=ds)
    folds = [([(-4, -226), (-8, -168), (-14, -112), (-26, -72), (-46, -52)], 1.1),  # 衣纹：顺着垂下，到下面被风和步子带向左
             ([(-30, -206), (-34, -150), (-44, -102), (-66, -70)], 1.0), ([(22, -214), (27, -150), (26, -106)], 0.9),
             ([(30, -112), (16, -84), (0, -58)], 0.9), ([(10, -98), (-6, -72), (-24, -51)], 0.8), ([(44, -196), (32, -164), (24, -126)], 0.9)]
    for pts, w in folds:
        f.brush(pts, w, color=JIAO, alpha=0.75, press=1.4, nail=0.6, tail=0.45, dry=0.3, dry_start=0.7)
    for pts in ([(36, -200), (38, -150), (40, -104)], [(16, -182), (19, -136)]):  # 受灯光的右边留两道淡处
        f.brush(pts, 1.5, color=mixc(DAN, PAPER, 0.35), alpha=0.2, nail=0.2, tail=0.5, press=0.2, dry=0.5, dry_start=0.4)
    f.brush(left[1:], 2.2, color=JIAO, press=1.6, dry=0.38, dry_start=0.66)  # 外轮廓：左边一笔长线，按重、后段飞白
    f.brush(hem[:4], 1.5, color=JIAO, press=1.6, dry=0.55, dry_start=0.15)  # 下摆：断续、飞白
    f.brush(hem[3:6], 1.3, color=JIAO, press=1.4, dry=0.5, dry_start=0.4)
    f.brush(hem[5:], 1.4, color=JIAO, press=1.4, dry=0.4, dry_start=0.5)
    f.brush(right[1:][::-1], 1.7, color=JIAO, press=1.5, dry=0.3, dry_start=0.65)
    for x0, y0, x1, y1 in ((-74, -58, -92, -64), (-56, -52, -70, -58), (-36, -45, -46, -49)):  # 下摆边上被风扯出的几丝干笔
        f.brush([(x0, y0), (x1, y1)], 1.6, color=ink, alpha=0.5, mode="glaze", nail=0.1, tail=0.6, press=0.0, dry=0.7,
                dry_start=0.1)
    f.knock([(-13, -244), (13, -244), (14, -236), (0, -231), (-14, -236)])  # 领口：白衣的交领露出一圈
    f.brush([(-14, -237), (0, -232), (14, -237)], 1.1, color=JIAO, nail=0.4)
    # ---- 右臂：抬起持杖，白色广袖从小臂上垂下来；墨氅搭在上臂上
    rsl = [(40, -216), (56, -210), (70, -207), (81, -208), (81, -199), (76, -186), (64, -176), (53, -179), (49, -192)]
    f.knock(rsl)
    f.wash(rsl, WASH_L, 0.28, off=(-1.0, 1.0), soft=1.6)
    f.wash([(50, -192), (54, -180), (64, -177), (74, -186), (62, -188)], WASH_M, 0.32, soft=1.4)
    f.brush([(42, -215), (56, -210), (70, -207), (82, -208)], 1.1, color=JIAO, press=1.2, nail=0.4)
    f.brush([(82, -199), (76, -185), (64, -175), (53, -178), (49, -190)], 1.3, color=JIAO, press=1.5, dry=0.25)
    f.brush([(68, -200), (63, -184)], 0.6, color=NONG, alpha=0.7)
    f.wash([(24, -234), (38, -224), (52, -212), (58, -201), (46, -203), (32, -214)], mixc(ZHONG, NONG, 0.45), 0.75, soft=1.5)
    f.brush([(24, -234), (38, -224), (52, -212), (59, -200)], 1.7, color=JIAO, press=1.4, nail=0.5)
    # ---- 背上的剑：剑柄从左肩上探出，剑鞘斜过后背，剑首垂一条朱砂剑穗
    g0, g1 = np.array([-21.0, -241.0]), np.array([42.0, -122.0])
    u = (g1 - g0) / np.linalg.norm(g1 - g0)
    nrm = np.array([-u[1], u[0]])
    f.brush([tuple(g0), tuple(g1)], 3.2, color=JIAO, smooth=False, nail=0.2, tail=0.0, press=0.0, dry=0.2, dry_start=0.8)
    for tt in (0.08, 0.6):  # 鞘上的箍
        p = g0 + (g1 - g0) * tt
        f.brush([tuple(p - nrm * 3.6), tuple(p + nrm * 3.6)], 0.8, color=mixc(ZHONG, TENG, 0.18), alpha=0.7, smooth=False, nail=0.0,
                tail=0.0, press=0.0)
    f.brush([tuple(g0 - nrm * 7.5 - u), tuple(g0 + nrm * 7.5 - u)], 1.7, color=JIAO, smooth=False, nail=0.3, tail=0.2)  # 剑格
    pm = g0 - u * 26
    f.brush([tuple(g0 - u * 2), tuple(pm)], 2.2, color=mixc(NONG, ZHESHI, 0.2), smooth=False, nail=0.1, tail=0.0, press=0.0)  # 剑柄
    for k in range(4):  # 缠绳
        p = g0 - u * (6 + 5 * k)
        f.brush([tuple(p - nrm * 2.3 - u * 1.2), tuple(p + nrm * 2.3 + u * 1.2)], 0.55, color=JIAO, smooth=False, nail=0.0, tail=0.0,
                press=0.0)
    f.dot(pm[0] - u[0] * 1.5, pm[1] - u[1] * 1.5, 2.6, JIAO, 0.95)  # 剑首
    F.ribbon(P, rigid([tuple(pm), (pm[0] - 8, pm[1] + 5), (pm[0] - 15, pm[1] + 13), (pm[0] - 19, pm[1] + 24)]), 1.5, ZHUSHA, 0.9,
             twists=1.0)
    # ---- 头：后脑全是头发（焦墨，受灯光的右边略淡），右边露一点耳朵；发髻、发冠、簪子
    hx, hy = 2.0, -258.0
    head = [(hx - 15, hy + 4), (hx - 14, hy - 10), (hx - 8, hy - 19), (hx + 4, hy - 21), (hx + 13, hy - 13), (hx + 16, hy + 2),
            (hx + 12, hy + 14), (hx + 4, hy + 19), (hx - 8, hy + 17), (hx - 13, hy + 11)]
    ear = [(hx + 13, hy - 1), (hx + 17, hy), (hx + 17, hy + 8), (hx + 13, hy + 10)]
    f.knock(ear)
    f.wash(ear, SKIN, 0.45, soft=1.0)
    f.brush([(hx + 14, hy), (hx + 17.5, hy + 2), (hx + 16.5, hy + 8), (hx + 14, hy + 10)], 0.6, color=NONG, nail=0.3, tail=0.3)
    f.fill(head, HAIR, 0.9, mode="over", rim=0.0, soft=0.5)
    f.wash([(hx + 4, hy - 19), (hx + 12, hy - 12), (hx + 15, hy + 2), (hx + 11, hy + 13), (hx + 6, hy + 4), (hx + 5, hy - 10)],
           mixc(ZHONG, DAN, 0.3), 0.5, mode="over", soft=1.4, ring=0.0)
    for k in range(6):  # 发丝：从发际往发髻梳上去
        x = hx - 11 + k * 4.4
        f.brush([(x + (k - 2.5) * 0.8, hy + 15 - abs(k - 2.5) * 1.6), (x + (k - 2.5) * 0.3, hy), (hx - 1 + (k - 2.5) * 1.2, hy - 19)],
                0.45, color=mixc(ZHONG, NONG, 0.3) if k >= 3 else JIAO, alpha=0.6, nail=0.0, tail=0.5, press=0.2)
    f.brush([(hx - 13, hy + 12), (hx - 15, hy), (hx - 13, hy - 11), (hx - 6, hy - 19), (hx + 4, hy - 21), (hx + 12, hy - 14)], 1.3,
            color=JIAO, press=1.4, nail=0.5, tail=0.35)
    f.brush([(hx + 13, hy - 12), (hx + 16, hy), (hx + 12, hy + 13)], 0.8, color=JIAO, nail=0.3, tail=0.4, gap=(0.35, 0.55))
    # 长发：从发髻垂到背中，被风带向左；发梢散开、飞白
    tail_c = curve_pts(f.pts([(hx - 1, hy - 18), (hx - 2, hy + 6), (hx - 5, hy + 34), (hx - 10, hy + 62), (hx - 18, hy + 86),
                              (hx - 28, hy + 102)]), 90)
    tt = np.linspace(0, 1, len(tail_c))
    P.stroke(tail_c, np.interp(tt, [0, 0.2, 0.55, 0.85, 1], [8.0, 9.0, 6.5, 3.6, 0.9]), HAIR, 0.96, dry=0.45, dry_start=0.7,
             jitter=0.12, near=True)
    for k in range(4):  # 发梢几缕
        d = (k - 1.5) * 2.4
        f.brush([(hx - 8 + d, hy + 58), (hx - 17 + d * 1.6, hy + 88), (hx - 30 + d * 2.4, hy + 106 + k * 3)], 0.75, color=JIAO,
                alpha=0.85, nail=0.0, tail=0.7, press=0.3, dry=0.4, dry_start=0.5)
    for k in range(3):  # 发上几道受光的淡丝
        f.brush([(hx + 1 + k * 1.5, hy + 4), (hx - 1 + k, hy + 34), (hx - 6 + k, hy + 62)], 0.45, color=mixc(DAN, ZHONG, 0.5),
                alpha=0.45, nail=0.0, tail=0.6, press=0.0)
    f.dot(hx - 1, hy - 24, 8.0, HAIR, 0.97)  # 发髻
    crown = [(hx - 7, hy - 29), (hx - 6, hy - 37), (hx - 1, hy - 40), (hx + 5, hy - 37), (hx + 6, hy - 29)]
    f.knock(crown)
    f.wash(crown, mixc(QING, PAPER, 0.4), 0.4, soft=0.8)
    f.brush(crown + [crown[0]], 0.7, color=JIAO, nail=0.2, tail=0.1, press=0.6)
    f.brush([(hx - 15, hy - 31), (hx + 16, hy - 34)], 0.85, color=mixc(NONG, ZHESHI, 0.2), smooth=False, nail=0.4, tail=0.3)  # 簪
    # 发带：两条朱砂，从发髻向左后方飘（和墨氅下摆、草同一个风向）
    F.ribbon(P, rigid([(hx - 6, hy - 27), (hx - 26, hy - 18), (hx - 48, hy + 4), (hx - 70, hy + 26), (hx - 94, hy + 42),
                       (hx - 116, hy + 58)]), 3.3, ZHUSHA, 0.92, twists=2.2, phase=0.3)
    F.ribbon(P, rigid([(hx - 6, hy - 24), (hx - 20, hy - 6), (hx - 36, hy + 16), (hx - 54, hy + 36), (hx - 74, hy + 50)]),
             2.7, mixc(ZHUSHA, JIAO, 0.12), 0.9, twists=1.6, phase=1.4)
    # ---- 杖：从手里斜挑出去，杖头一道铜箍、一个铜钩，灯笼挂在钩上
    hx_, hy_ = hero_pose(84.0, -204.0)
    hnd, tip = np.array([hx_, hy_]), np.array([174.0, -279.0])
    ud = (tip - hnd) / np.linalg.norm(tip - hnd)
    butt = hnd - ud * 22
    staff = mixc(mixc(NONG, ZHESHI, 0.45), DAN, 0.1)
    f0.brush([tuple(butt), tuple((butt + tip) / 2 + np.array([0, -1.2])), tuple(tip)], 3.1, color=staff, nail=0.4, tail=0.0,
             press=0.0, dry=0.15, dry_start=0.8)
    f0.brush([tuple(butt + np.array([0.8, 1.6])), tuple(tip + np.array([0.8, 1.6]))], 0.6, color=mixc(ZHESHI, PAPER, 0.35),
             alpha=0.55, smooth=False, nail=0.0, tail=0.3, press=0.0)  # 朝灯的一边受光
    brass = mixc(TENG, ZHESHI, 0.35)
    band = tip - ud * 7
    f0.brush([tuple(band - ud * 3), tuple(band + ud * 3)], 3.4, color=brass, smooth=False, nail=0.0, tail=0.0, press=0.0)
    f0.brush([tuple(band - ud * 3 + np.array([0, -2.6])), tuple(band + ud * 3 + np.array([0, -2.6]))], 0.6, color=JIAO, alpha=0.7,
             smooth=False, nail=0.0, tail=0.0, press=0.0)
    f0.dot(tip[0] + 0.8, tip[1] - 0.6, 3.0, brass, 0.97)
    hook = [(tip[0] + 1.5, tip[1] + 1.5), (tip[0] + 3.5, tip[1] + 6.5), (tip[0] + 0.5, tip[1] + 10.0), (tip[0] - 3.0, tip[1] + 8.0)]
    f0.brush(hook, 1.2, color=brass, nail=0.1, tail=0.2, press=0.3)
    f0.brush(hook, 0.45, color=JIAO, alpha=0.6, nail=0.0, tail=0.3, press=0.0)
    F.hand(f, 84.0, -204.0, 3.5, skin=SKIN)
    # ---- 灯笼：朱砂纸（左右两边略深），纸里透出暖光；焦墨描边、顶和底各一道短的焦墨；竹骨；底下一绺穗子
    lx, ly = LANTERN_AT
    rx, ry = 17.0, 21.0
    f0.brush([(tip[0] - 3.0, tip[1] + 8.0), (lx + 0.3, ly - ry - 5)], 0.55, color=NONG, smooth=False, nail=0.0, tail=0.0, press=0.0)
    gx, gy = f0.pt(lx, ly)
    sl = (slice(int(gy - 34), int(gy + 34)), slice(int(gx - 30), int(gx + 30)))
    X, Y = P.X[sl], P.Y[sl]
    rho = np.hypot((X - gx) / rx, (Y - gy) / ry)
    body = smoothstep(1.05, 0.9, rho)
    side = np.abs(X - gx) / rx
    P.over(body * 0.97, mixc(ZHUSHA, PAPER, 0.12), sl)
    P.over(body * 0.55 * smoothstep(0.55, 1.0, side), mixc(ZHUSHA, JIAO, 0.3), sl)  # 灯笼是圆的：两边略深
    P.mark_near(body, sl)
    core = np.exp(-((X - gx) ** 2 / (rx * 0.4) ** 2 + (Y - gy - 1.5) ** 2 / (ry * 0.42) ** 2))
    P.emit[sl] += (body * (0.08 + 0.55 * np.exp(-(rho / 0.5) ** 2)))[..., None] * mixc(ZHUSHA, FLAME_LIGHT, 0.5)
    P.emit[sl] += (core * 0.95)[..., None] * mixc(FLAME_LIGHT, np.ones(3), 0.5)
    for k in (-0.72, -0.26, 0.26, 0.72):  # 竹骨
        th = np.linspace(-1.3, 1.3, 18)
        f0.brush([(lx + k * rx * np.cos(a), ly + ry * np.sin(a) * 0.97) for a in th], 0.5, color=mixc(ZHUSHA, JIAO, 0.5), alpha=0.6,
                 nail=0.0, tail=0.1, press=0.0)
    th = np.linspace(-math.pi / 2, math.pi / 2, 24)  # 描边：左边一笔重、右边一笔轻，略断
    f0.brush([(lx - rx * np.cos(a), ly + ry * np.sin(a)) for a in th], 1.2, color=JIAO, nail=0.3, tail=0.3, press=1.0, dry=0.2,
             dry_start=0.75)
    f0.brush([(lx + rx * np.cos(a), ly + ry * np.sin(a)) for a in th], 0.9, color=JIAO, nail=0.3, tail=0.3, press=1.0,
             gap=(0.4, 0.55))
    f0.fill([(lx - 8, ly - ry - 5), (lx + 8, ly - ry - 5), (lx + 11, ly - ry + 1.5), (lx - 11, ly - ry + 1.5)], JIAO, 0.97, mode="over",
            rim=0.0, smooth=False)  # 顶
    f0.fill([(lx - 11, ly + ry - 1.5), (lx + 11, ly + ry - 1.5), (lx + 8, ly + ry + 4), (lx - 8, ly + ry + 4)], JIAO, 0.97, mode="over",
            rim=0.0, smooth=False)  # 底
    f0.brush([(lx - 7, ly - ry - 3.5), (lx + 7, ly - ry - 3.5)], 0.5, color=brass, alpha=0.7, smooth=False, nail=0.0, tail=0.0,
             press=0.0)
    # 穗子：一个结、一颗珠子，一绺丝被风带向左
    f0.brush([(lx, ly + ry + 4), (lx, ly + ry + 8)], 0.6, color=JIAO, smooth=False, nail=0.0, tail=0.0, press=0.0)
    f0.dot(lx, ly + ry + 9.5, 2.0, JIAO, 0.95)
    f0.dot(lx - 0.2, ly + ry + 13.0, 2.2, mixc(ZHUSHA, TENG, 0.25), 0.97)
    for k in range(5):
        d = (k - 2) * 1.1
        F.ribbon(P, f0.pts([(lx + d * 0.4, ly + ry + 15), (lx + d - 1.5, ly + ry + 26), (lx + d * 1.6 - 5.5, ly + ry + 38 + abs(d))]),
                 0.75, ZHUSHA, 0.92, twists=0.3, edge=0.0)
    f0.brush([(lx - 2.6, ly + ry + 16), (lx + 2.6, ly + ry + 16)], 0.9, color=mixc(ZHUSHA, JIAO, 0.5), smooth=False, nail=0.0, tail=0.0,
             press=0.0)
    lights.append((gx, gy, 480.0, mixc(LAMP_LIGHT, np.ones(3), 0.22), 1.12, HERO_FEET[1] + 8))
    lights.append((gx, gy, 170.0, LAMP_LIGHT, 0.35, None))
    return gx, gy


def paint_stone_lantern(P: Painting, rng, x, y, s, lights) -> None:
    """石灯笼（写意）：基座、竿、中台、火袋（窗里透出火光）、翘角的笠、宝珠。先擦出留白、淡墨铺底，再用侧锋的宽笔
    一块块压出石头（左边背光更重），重墨几笔铺出屋面，枯笔勾边、断续，苔点。局部坐标按旧版渲染件的尺寸，缩放 s。"""
    F = _ink()
    f = F.Fig(P, x, y, s)
    wash_blob(P, x + 4, y + 2, 46 * s * 1.4, 10 * s * 1.4, ZHONG, 0.5, rng)
    stone = mixc(DAN, ZHONG, 0.3)

    def jit(pts, a=1.2):  # 石头的边不那么齐
        return [(px + rng.normal(0, a), py + rng.normal(0, a * 0.6)) for px, py in pts]

    parts = [jit([(-45, 7), (-47, -7), (-39, -14), (39, -14), (47, -7), (45, 7)]),  # 基座
             jit([(-31, -14), (-27, -26), (27, -26), (31, -14)]),
             jit([(-14, -26), (-13, -96), (13, -96), (14, -26)], 0.8),  # 竿
             jit([(-24, -96), (-35, -103), (-35, -114), (35, -114), (35, -103), (24, -96)]),  # 中台
             jit([(-21, -114), (-22, -146), (22, -146), (21, -114)], 0.8)]  # 火袋
    for poly in parts:
        f.knock(poly, smooth=False)
        f.wash(poly, stone, 0.45, off=(-1.2, 0.8), smooth=False, soft=1.6, tex=0.25)

    def slab(y0, y1, x0, x1, a, n=3, horiz=False):
        """侧锋压一块石面：竖着几笔（左重右淡）或横着几笔，干笔带飞白。"""
        for k in range(n):
            if horiz:
                yy = y0 + (y1 - y0) * (k + 0.5) / n
                pts = [(x0 + rng.uniform(-1, 2), yy + rng.normal(0, 0.6)), (x1 + rng.uniform(-2, 1), yy + rng.normal(0, 0.6))]
                hw = (y1 - y0) / n * 0.75
            else:
                xx = x0 + (x1 - x0) * (k + 0.5) / n
                pts = [(xx + rng.normal(0, 0.6), y0 + rng.uniform(-1, 1)), (xx + rng.normal(0, 0.8), y1 + rng.uniform(-1, 1))]
                hw = (x1 - x0) / n * 0.7
            aa = a if horiz else a * (1.25 - 0.6 * k / max(n - 1, 1))
            f.brush(pts, hw, color=mixc(ZHONG, NONG, 0.3), alpha=float(np.clip(aa * rng.uniform(0.85, 1.1), 0, 1)), smooth=False,
                    dry=0.6, dry_start=0.25, nail=0.2, tail=0.15, press=0.0, mode="glaze")

    slab(-28, -94, -13, 2, 0.5, n=2)  # 竿：左半
    slab(-116, -144, -20, -4, 0.45, n=2)  # 火袋：左边
    slab(-114, -103, -34, 20, 0.4, n=1, horiz=True)  # 中台
    slab(-14, -2, -44, 18, 0.38, n=2, horiz=True)  # 基座
    # 笠：先洇一层，再几笔重墨的宽笔铺出屋面，两头翘起；檐下一道焦墨
    roof = jit([(-9, -177), (-28, -162), (-46, -154), (-53, -160), (-47, -148), (47, -148), (53, -160), (46, -154), (28, -162),
                (9, -177)], 0.8)
    f.knock(roof)
    f.wash(roof, mixc(DAN, ZHONG, 0.5), 0.6, off=(-1, 0.8), soft=1.4, tex=0.3)
    for k, (yy, a) in enumerate(((-158, 0.62), (-165, 0.5), (-171, 0.42))):
        wdt = 42 - 13 * k
        f.brush([(-wdt, yy + 4 + k), (0, yy - 2), (wdt, yy + 4 + k)], 3.4 - 0.6 * k, color=NONG, alpha=a, dry=0.55, dry_start=0.4,
                nail=0.3, tail=0.3, press=0.3, mode="glaze")
    f.brush([(-52, -159), (-45, -149), (0, -148), (45, -149), (52, -159)], 1.9, color=JIAO, press=1.6, dry=0.3, dry_start=0.6,
            nail=0.5, tail=0.25)
    f.brush([(-9, -177), (-28, -162), (-46, -154), (-54, -161)], 1.4, color=JIAO, press=1.4, dry=0.4, dry_start=0.5, nail=0.6,
            tail=0.3)
    f.brush([(9, -177), (28, -162), (46, -154), (54, -161)], 1.2, color=JIAO, press=1.4, dry=0.45, dry_start=0.4, nail=0.6,
            tail=0.3, gap=(0.35, 0.5))
    jew = [(-6, -176), (-6, -185), (0, -194), (6, -185), (6, -176)]  # 宝珠
    f.knock(jew)
    f.wash(jew, stone, 0.45, soft=1.1)
    f.brush([(-6, -176), (-6, -185), (0, -195), (6, -185)], 0.9, color=JIAO, nail=0.3, tail=0.4, press=1.2)
    # 火袋的窗：纸色里透出火光（发光层），两根窗框一根窗棂
    wx0, wx1, wy0, wy1 = -9.0, 9.0, -140.0, -121.0
    (gx0, gy0), (gx1, gy1) = f.pt(wx0, wy0), f.pt(wx1, wy1)
    sl = (slice(int(gy0) - 6, int(gy1) + 6), slice(int(gx0) - 6, int(gx1) + 6))
    Xw, Yw = P.X[sl], P.Y[sl]
    dd = np.minimum(np.minimum(Xw - gx0, gx1 - Xw), np.minimum(Yw - gy0, gy1 - Yw)) + 0.8 * noise(rng, Xw.shape, 1.2)
    win = smoothstep(-0.6, 0.8, dd)
    P.over(win * 0.97, mixc(PAPER, FLAME_LIGHT, 0.45), sl)
    P.mark_near(win, sl)
    cx_, cy_ = (gx0 + gx1) / 2, gy0 + (gy1 - gy0) * 0.62
    P.emit[sl] += (win * (0.42 + 0.5 * np.exp(-(((Xw - cx_) / (6 * s)) ** 2 + ((Yw - cy_) / (8 * s)) ** 2))))[..., None] * FLAME_LIGHT * 0.95
    k = dict(color=JIAO, press=1.5, dry=0.35, dry_start=0.55)
    f.brush([(wx0, wy0), (wx0 + 0.5, wy1)], 1.1, smooth=False, nail=0.3, tail=0.1, **k)
    f.brush([(wx1, wy0), (wx1 - 0.5, wy1)], 1.0, smooth=False, nail=0.3, tail=0.1, **k)
    f.brush([(0, wy0), (0, wy1)], 0.7, color=NONG, smooth=False, nail=0.0, tail=0.0, press=0.0)
    # 轮廓：枯笔勾，断续，左边重
    f.brush([(-21, -146), (-22, -130), (-21, -114)], 1.4, smooth=False, nail=0.5, tail=0.2, **k)
    f.brush([(21, -146), (22, -130), (21, -114)], 1.0, smooth=False, nail=0.5, tail=0.2, gap=(0.4, 0.62), **k)
    f.brush([(-36, -114), (0, -115), (36, -114)], 1.3, nail=0.5, tail=0.2, **k)
    f.brush([(-36, -113), (-35, -104), (-24, -96), (24, -96), (35, -104)], 1.1, smooth=False, nail=0.4, tail=0.3, gap=(0.55, 0.7), **k)
    f.brush([(-14, -96), (-13, -60), (-14, -26)], 1.5, nail=0.6, tail=0.2, **k)
    f.brush([(14, -95), (13, -62), (14, -27)], 1.0, nail=0.5, tail=0.3, gap=(0.3, 0.45), **k)
    f.brush([(-31, -14), (-27, -26), (27, -26), (31, -14)], 1.1, smooth=False, nail=0.4, tail=0.3, **k)
    f.brush([(-47, -7), (-39, -14), (39, -14), (47, -7)], 1.2, smooth=False, nail=0.5, tail=0.2, gap=(0.6, 0.72), **k)
    f.brush([(-47, -7), (-45, 7), (45, 7)], 1.6, smooth=False, nail=0.5, tail=0.3, **k)
    for dx, dy, r in ((-38, -156, 2.6), (-22, -164, 2.0), (31, -157, 2.3), (-41, -9, 2.4), (-30, 3, 2.0), (38, 2, 2.2),
                      (-11, -28, 1.8), (-15, -99, 1.8), (6, -178, 1.6)):  # 苔点
        f.dot(dx + rng.normal(0, 2), dy + rng.normal(0, 1), r, JIAO, 0.9)
    fx, fy = f.pt(-6.5, -122.5)  # 火光的位置同旧版渲染件
    lights.append((fx, fy, 190 * s, FLAME_LIGHT, 0.55, y))


# ============================================================== 标题画：光与收尾


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


def paint_title(rng_seed: int = 2026) -> tuple[Image.Image, dict]:
    t0 = time.perf_counter()
    rng = np.random.default_rng(rng_seed)
    P = Painting(rng)
    P.rgb = soft_paper_canvas(np.random.default_rng(rng_seed + 1))  # 换成纤维短而软的纸（天上的云、地面的笔触照旧用 rng）
    paper0 = P.rgb.copy()
    P.paper0 = paper0  # 人物的留白（ink_figure.knock）擦回这张干净的纸
    paint_sky(P, rng)
    paint_ranges(P, np.random.default_rng(rng_seed + 2))
    paint_ground(P, rng)
    paint_ground_detail(P, rng)
    paint_rock(P, rng, [(1588, 846), (1622, 806), (1668, 778), (1730, 758), (1800, 742), (1880, 728), (1960, 724)],
               [(1588, 846), (1572, 920), (1582, 1000), (1566, 1095)],
               [(1600, 850), (1660, 826), (1740, 808), (1830, 790), (1960, 770)])
    paint_pine(P, rng)
    paint_grass(P, rng)
    lights = []
    srng = np.random.default_rng(rng_seed + 3)
    for x, y, s in sorted(STONE_LANTERNS, key=lambda t: t[1]):  # 远的先画
        paint_stone_lantern(P, srng, x, y, s, lights)
    lx, ly = paint_hero(P, np.random.default_rng(rng_seed + 4), lights)
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
    info = {"lantern_px": [round(lx, 1), round(ly, 1)], "time_s": round(time.perf_counter() - t0, 1)}
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


SAMPLE_CROPS = [  # 对比图里的 2 倍裁切：名字、框（画面像素）
    ("主角", (1066, 596, 1406, 916)),
    ("石灯笼", (670, 724, 1030, 934)),
    ("远山", (700, 280, 1180, 740)),
    ("夜空纸纹", (980, 40, 1280, 300)),
]


def fix_sample(old: Image.Image | None, new: Image.Image, logo: Image.Image, path: Path) -> None:
    """新旧对比（左旧右新）：第一行是整幅（叠上标题字和菜单，半尺寸），下面每行一处 2 倍裁切；
    夜空纸纹另附一行拉开对比度的（新旧同一个拉伸），看清纤维的样子。没有旧图时左边空着。"""
    pad, col_w, lab_h = 16, 960, 34
    f = font("serif", 24, weight=500)
    rows = [("整幅（叠标题字和菜单，半尺寸）", [compose_review(im, logo).resize((W // 2, H // 2), Image.LANCZOS) if im else None
                                     for im in (old, new)])]
    for name, box in SAMPLE_CROPS:
        k = 2
        size = ((box[2] - box[0]) * k, (box[3] - box[1]) * k)
        rows.append((f"{name}（2 倍）", [im.crop(box).resize(size, Image.LANCZOS) if im else None for im in (old, new)]))
    name, box = SAMPLE_CROPS[-1]
    crops = [np.asarray(im.crop(box), np.float64) if im else None for im in (old, new)]
    lo, hi = np.percentile(np.concatenate([c.ravel() for c in crops if c is not None]), [1, 99])
    rows.append((f"{name}（2 倍，拉开对比度）", [Image.fromarray((np.clip((c - lo) / (hi - lo), 0, 1) * 255).astype(np.uint8)).resize(
        ((box[2] - box[0]) * 2, (box[3] - box[1]) * 2), Image.LANCZOS) if c is not None else None for c in crops]))
    height = pad + sum(lab_h + max(im.height for im in ims if im) + pad for _, ims in rows)
    out = Image.new("RGB", (col_w * 2 + pad * 3, height), S.hex_to_rgb(S.PAPER))
    dr = ImageDraw.Draw(out)
    ink = S.hex_to_rgb(S.INK["nong"])
    y = pad
    for title, ims in rows:
        for i, (im, side) in enumerate(zip(ims, ("旧", "新"))):
            x = pad + i * (col_w + pad)
            dr.text((x, y + 2), f"{side} · {title}", font=f, fill=ink)
            if im is not None:
                out.paste(im, (x + (col_w - im.width) // 2, y + lab_h))
        y += lab_h + max(im.height for im in ims if im) + pad
    out.save(path, optimize=True)


# ============================================================== 主程序


def main(argv: list[str]) -> int:
    t0 = time.perf_counter()
    OUT.mkdir(parents=True, exist_ok=True)
    REVIEW.mkdir(parents=True, exist_ok=True)
    sample = "--sample" in argv
    logo, info = make_logo()
    if not sample:
        save_rgba(logo, OUT / "logo.png")
        logo_review(logo, REVIEW / "logo_review.png")
        print(f"[logo] {logo.width}×{logo.height} {time.perf_counter() - t0:.1f}s → {OUT / 'logo.png'}")
    if "--logo" in argv:
        return 0
    title, tinfo = paint_title()
    if sample:  # 只出候选和新旧对比，不动 title.png
        title.save(OUT / "title_candidate.png", optimize=True)
        old = Image.open(OUT / "title.png").convert("RGB") if (OUT / "title.png").exists() else None
        fix_sample(old, title, logo, REVIEW / "title_fix_sample.png")
        print(f"[sample] {tinfo['time_s']}s → {OUT / 'title_candidate.png'}，对比 {REVIEW / 'title_fix_sample.png'}")
        return 0
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
