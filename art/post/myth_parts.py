#!/usr/bin/env python3
"""提灯夜行 · 神话特效的元件（docs/FEEL.md 第 13 节，四个样张）。只出桌面版 2 倍，Pillow + numpy，不用 Blender。

约定同逐帧特效（FEEL 第 12 节、vfx_frames.py）：
  - 2 倍密度（4 像素 / 世界单位），一次性的按 24 帧/秒；叠加帧最亮处 alpha 约 0.8，边上要飞白、干笔断续；
  - 普通混合的墨用焦墨 #17140F；方向朝 +X；地面的已按透视压扁（高 ÷ 宽 ≈ 0.62）。
  - 帧名 myth/<演出>_<元件>_<帧号>，单张的不带帧号；发光层是同画布、同锚点、同帧号的 <演出>_<元件>_emit_<帧号>，
    meta 写 layer_of（同 weapons/sky_lantern_emit 的写法）：本体普通混合（暗层之下），发光层叠加（暗层之上）。
  - 放新图集 myth（演出少见，单独一页）。

元件（FEEL 13.2）：
  万剑归宗  sword_blade_0..2（3 种剑影，96×24，叠加，可染金，挑着用）
            sword_cloud_0..5（被劈开的云，1024×512，焦墨）+ sword_cloud_emit_0..5（裂口金光，叠加）
  北冥潮    kun_sea_0..5（脚下冰海，1024×640 已压扁，墨蓝）+ kun_sea_emit_0..5（冰光，叠加）
            kun_shadow（鲲影，1536×512，焦墨半透明，头朝 +X）
            kun_leap_0..5（鲲跃出水的冷光剪影，768×768，叠加，#CDEBFF）
  燃灯      ult_lotus_0..7（莲灯开合，256×320，叠加，锚点底边中点）、ult_rays（放射佛光，2048²，叠加）、ult_halo（头光，512²，叠加）
  九尾登场  fox_moon（月亮，1024²，叠加冷白，可染）、fox_body（身子剪影，512²，焦墨描青边）+ fox_body_emit、
            fox_tail（一条尾巴，128×512，同上，锚点在尾根）+ fox_tail_emit

产物：art/out/assets@2x/myth/*.png + meta.json（name: myth）
用法（仓库根目录）：
  art/.venv/bin/python art/post/myth_parts.py              # 全部
  art/.venv/bin/python art/post/myth_parts.py sword kun     # 只画这几个演出的元件
  art/.venv/bin/python art/post/myth_parts.py sword_cloud   # 只画这一组
"""

from __future__ import annotations

import json
import math
import os
import sys
import time
from pathlib import Path

os.environ["LANTERN_ART_DENSITY"] = "2"

import numpy as np  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import vfx_frames as F  # noqa: E402
import vfx_textures as V  # noqa: E402
import weapon_textures as W  # noqa: E402

S = V.S
OUT = V.OUT / "assets@2x" / "myth"
GENERATOR = "art/post/myth_parts.py"
PPU, FPS, PEAK = 4, 24, F.PEAK
smoothstep = V.smoothstep
grid, dry, Acc, Paint = F.grid, F.dry, F.Acc, F.Paint
JIAO = V.col(S.INK["jiao"])
GOLD = F.GOLD  # 外边偏暖 #E3B05A、主色 #FFE7A8、芯偏白
ICE = "#CDEBFF"
FOX_CYAN = "#8FE3C8"  # 青丘狐火（fox_shrine 的 light_color）


# ============================================================== 小工具


def mask_polys(w: int, h: int, polys, ss: int = 4, holes=()) -> np.ndarray:
    """多边形填充的覆盖度（超采样网格，形状 (h·ss, w·ss)），坐标是最终像素。比 poly_sdf 快得多，大剪影用。"""
    im = Image.new("L", (w * ss, h * ss), 0)
    d = ImageDraw.Draw(im)
    for p in polys:
        d.polygon([(float(x) * ss, float(y) * ss) for x, y in p], fill=255)
    for p in holes:
        d.polygon([(float(x) * ss, float(y) * ss) for x, y in p], fill=0)
    return np.asarray(im, dtype=np.float64) / 255.0


def edge_band(m: np.ndarray, sigma: float) -> tuple[np.ndarray, np.ndarray]:
    """剪影的边：返回 (内侧的边带 0..1, 外侧的晕 0..1)。sigma 是超采样像素。"""
    b = V.fft_blur(m, sigma)
    inner = np.clip((m - b) * 2.0, 0, 1) * m
    outer = np.clip((b - m) * 2.0, 0, 1) * (1 - m)
    return inner, outer


def ribbon_poly(pts: np.ndarray, hw: np.ndarray) -> np.ndarray:
    """中线 + 半宽 → 闭合多边形（左边去、右边回）。"""
    return W.ribbon(np.asarray(pts, dtype=np.float64), np.asarray(hw, dtype=np.float64))


def to_white(a_ss, seed, peak=PEAK, ss=4):
    """叠加帧：亮度场 → 白色、软饱和到 peak、蓝噪声抖动（同 vfx_frames.frame_white，超采样倍数可改）。"""
    a = V.downsample(np.clip(a_ss, 0, None), ss)
    a = peak * np.tanh(1.25 * np.clip(a, 0.0, 1.0)) / math.tanh(1.25)
    a8 = V.dither_alpha(a, np.random.default_rng(seed))
    a8[a < 0.004] = 0
    a8[0, :] = a8[-1, :] = a8[:, 0] = a8[:, -1] = 0
    return V.to_rgba8(V.WHITE, None, a8)


def to_color(a_ss, heat_ss, seed, palette, peak=PEAK, ss=4):
    """自带颜色的叠加帧（同 vfx_frames.frame_color，超采样倍数可改）。"""
    a_ss = np.clip(a_ss, 0, None)
    a = V.downsample(a_ss, ss)
    heat = V.downsample(a_ss * np.clip(heat_ss, 0, 1), ss) / np.maximum(a, 1e-6)
    a = peak * np.tanh(1.25 * np.clip(a, 0.0, 1.0)) / math.tanh(1.25)
    a8 = V.dither_alpha(a, np.random.default_rng(seed))
    a8[a < 0.004] = 0
    a8[0, :] = a8[-1, :] = a8[:, 0] = a8[:, -1] = 0
    rgb = F.lerp_col(heat, palette)
    return V.to_rgba8(rgb, None, a8)


def to_paint(p_ss, a_ss, seed, ss=4):
    """普通混合的上色层（预乘颜色 + 覆盖度，超采样）→ RGBA 帧。"""
    a = V.downsample(np.clip(a_ss, 0, 1), ss)
    p = V.downsample(p_ss, ss)
    rgb = p / np.maximum(a, 1e-6)[..., None]
    a8 = V.dither_alpha(a, np.random.default_rng(seed))
    a8[a < 0.004] = 0
    a8[0, :] = a8[-1, :] = a8[:, 0] = a8[:, -1] = 0
    return V.to_rgba8(np.clip(rgb, 0, 1), None, a8)


# ============================================================== 万剑归宗：剑影


BLADE_W, BLADE_H = 96, 24


def make_sword_blade() -> list[Image.Image]:
    """三种剑影（挑着用，不是动画）：剑尖朝 +X，锚点居中。白色可染（建议金 #FFE7A8），叠加。
    0 长剑：直身双刃、中脊一线最亮，如意剑格、缠绳剑柄、圆剑首，柄后一缕剑穗；
    1 符剑：剑身短宽、柳叶形，剑格上系一张符纸往后飘（纸上朱书的几笔是暗的）；
    2 剑气：没有剑柄的一道光，中段最宽、两头尖，尾巴散成飞白（像一笔写出来的剑）。
    剑身的边和中脊亮、身上淡，剑尖一点烧白；剑后一圈 1–2 像素的薄光，辉光再往外补。"""
    w, h = BLADE_W, BLADE_H
    X, Y = grid(w, h)
    cy = h / 2
    rng = np.random.default_rng(13101)
    tex = W.ptex(rng, ns=16, nt=512, along=30.0, across=0.7)
    out = []

    def blade_field(x0, x1, hw0, taper_from, ridge=True, leaf=0.0):
        """剑身：x0（剑格）到 x1（剑尖）。半宽从 hw0 起，taper_from 之后收到尖；leaf > 0 时中段鼓一点（柳叶）。"""
        u = np.clip((X - x0) / (x1 - x0), 0, 1)
        hw = hw0 * (1 + leaf * np.sin(np.pi * np.clip(u / 0.8, 0, 1)) ** 1.5)
        tip = np.clip((u - taper_from) / (1 - taper_from), 0, 1)
        hw = hw * (1 - tip**1.15)
        inside = (X >= x0) & (X <= x1)
        d = np.abs(Y - cy) - hw
        cov = smoothstep(0.45, -0.45, d) * inside
        edge = smoothstep(1.1, 0.0, np.abs(d)) * inside * (hw > 0.15)
        rid = smoothstep(0.75, 0.0, np.abs(Y - cy)) * inside * (u < 0.98) if ridge else 0.0
        glint = np.exp(-(((X - (x1 - 3.0)) / 3.5) ** 2 + ((Y - cy) / 1.6) ** 2))
        halo = np.exp(-np.maximum(d, 0) ** 2 / 2.2) * inside * (1 - cov)
        return cov, edge, rid, glint, halo, u

    # 0 长剑
    cov, edge, rid, glint, halo, u = blade_field(34.0, 93.0, 2.6, 0.78)
    body = 0.2 * cov * (0.85 + 0.15 * W.sample_ptex(tex, np.clip((Y - cy) / 3, -1, 1), u * 0.4))
    guard_c = (31.5, cy)
    gq = np.hypot((X - guard_c[0]) / 2.1, (Y - cy) / 7.0)
    guard = smoothstep(1.05, 0.9, gq)
    wing = np.exp(-(((X - 30.0) / 2.4) ** 2)) * smoothstep(7.8, 6.0, np.abs(Y - cy)) * smoothstep(3.0, 5.5, np.abs(Y - cy))  # 剑格两头翘起的如意
    grip_d = np.abs(Y - cy) - 1.7
    grip = smoothstep(0.45, -0.45, grip_d) * ((X > 15) & (X < 30))
    wrap = 0.55 + 0.45 * (np.sin((X - 15) * 2.2) > 0)
    pommel = F.dot(X, Y, 13.0, cy, 2.4)
    tassel_pts = V.bezier([(12.0, cy), (8.0, cy + 1.5), (4.5, cy + 4.0), (1.5, cy + 3.0)], 40)
    tassel = V.brush_stroke(X, Y, tassel_pts, np.linspace(1.3, 0.4, 40), np.random.default_rng(13102), dry=0.5, ss=4)[0]
    parts = [body, 0.62 * edge, 1.0 * rid, 0.9 * glint, 0.14 * halo, 0.75 * guard, 0.7 * wing, 0.42 * grip * wrap, 0.7 * pommel, 0.35 * tassel]
    out.append(to_white(F.soft_union(*parts), 13110))

    # 1 符剑：柳叶剑身 + 飘的符纸
    cov, edge, rid, glint, halo, u = blade_field(40.0, 92.0, 2.8, 0.7, leaf=0.25)
    body = 0.22 * cov
    guard = smoothstep(1.05, 0.9, np.hypot((X - 37.5) / 2.0, (Y - cy) / 5.6))
    grip = smoothstep(0.45, -0.45, np.abs(Y - cy) - 1.5) * ((X > 26) & (X < 36))
    pommel = F.dot(X, Y, 25.0, cy, 2.0)
    # 符纸：从剑格往后飘的一条（两次弯），纸面淡、纸边亮，上面三笔暗的朱书
    t = np.linspace(0, 1, 60)
    paper_pts = np.stack([37.0 - 33.0 * t, cy + 2.2 + 3.2 * np.sin(t * 5.0 + 0.4) * t + 1.5 * t], -1)
    paper_hw = 2.6 * (1 - 0.25 * t)
    pf = V.stroke_fields(X, Y, paper_pts, paper_hw)
    pd = np.hypot(np.abs(pf["perp"]) - pf["hw"], 0) * (np.abs(pf["perp"]) > pf["hw"]) + pf["over"]
    pcov = smoothstep(0.5, -0.4, np.abs(pf["perp"]) - pf["hw"]) * smoothstep(0.5, -0.4, pf["over"] - 0.0)
    prim = smoothstep(0.9, 0.0, np.abs(np.abs(pf["perp"]) - pf["hw"])) * pcov
    glyph = np.zeros_like(X)
    for tg in (0.25, 0.45, 0.68):
        glyph = np.maximum(glyph, smoothstep(0.06, 0.0, np.abs(pf["t"] - tg)) * smoothstep(1.6, 0.6, np.abs(pf["perp"])))
    paper = pcov * (0.3 + 0.35 * prim) * (1 - 0.75 * glyph) * (1 - 0.6 * pf["t"])
    del pd
    parts = [body, 0.62 * edge, rid, 0.9 * glint, 0.14 * halo, 0.75 * guard, 0.42 * grip, 0.6 * pommel, paper]
    out.append(to_white(F.soft_union(*parts), 13111))

    # 2 剑气：中段最宽、两头尖的一笔光，尾巴飞白
    x0, x1 = 6.0, 94.0
    u = np.clip((X - x0) / (x1 - x0), 0, 1)
    prof = np.sin(np.pi * u**1.35) ** 0.7  # 最宽处偏后（约 0.6）
    hw = 3.4 * prof
    d = np.abs(Y - cy) - hw
    inside = (X >= x0) & (X <= x1)
    cov = smoothstep(0.45, -0.45, d) * inside
    m = dry(tex, np.clip((Y - cy) / np.maximum(hw, 0.6), -1, 1), u * 0.6 + 0.3, 0.55 * smoothstep(0.55, 0.0, u))
    core = smoothstep(0.9, 0.0, np.abs(Y - cy)) * smoothstep(0.08, 0.35, u) * inside
    edge = smoothstep(1.0, 0.0, np.abs(d)) * inside * (u > 0.3)
    halo = np.exp(-np.maximum(d, 0) ** 2 / 3.0) * inside * (1 - cov) * u
    flare = np.exp(-(((X - 58.0) / 1.6) ** 2)) * smoothstep(7.5, 3.0, np.abs(Y - cy))  # 剑格处一道横的短光（护手的影子）
    glint = np.exp(-(((X - 90.0) / 4.0) ** 2 + ((Y - cy) / 1.5) ** 2))
    parts = [0.28 * cov * m, core * m, 0.55 * edge * m, 0.16 * halo, 0.55 * flare, 0.9 * glint]
    out.append(to_white(F.soft_union(*parts), 13112))
    return out


# ============================================================== 万剑归宗：被劈开的云


CLOUD_W, CLOUD_H = 1024, 512
CLOUD_SS = 2
CLOUD_CX = CLOUD_W / 2
CLOUD_OPEN = [0.0, 4.0, 40.0, 118.0, 220.0, 330.0]  # 缝的半宽（底边处，像素）
CLOUD_FADE = [0.0, 0.0, 0.0, 0.12, 0.4, 0.75]  # 靠缝那边散掉的程度
CLOUD_ENV = [0.85, 1.0, 1.0, 0.85, 0.6, 0.32]  # 发光层的总亮度


def cloud_bottom(x):
    """云的下沿（没有劈开时）：中间垂得低，两头收上去。"""
    mid = np.clip(1.0 - np.abs(x - CLOUD_CX) / (CLOUD_W / 2), 0, 1)
    return 236.0 + 104.0 * mid**1.2


def cloud_billows(rng):
    """一层层的云头（鱼鳞一样）：(x, y, r, 卷云的方向 −1/0/1)。最下面一排先画，往上一排排盖上去，每团的下沿描浓边，
    所以画面上是一道道往下弯的弧。"""
    out = []
    for row in range(6):
        span = [370, 440, 500, 520, 530, 540][row]
        x = CLOUD_CX - span + rng.uniform(0, 30)
        while x < CLOUD_CX + span:
            mid = max(0.0, 1.0 - abs(x - CLOUD_CX) / (CLOUD_W / 2))
            r = rng.uniform(30, 68) * (0.75 + 0.45 * mid) * (1.0 + 0.12 * row)
            yb = float(cloud_bottom(x)) - row * 44.0 + rng.uniform(-16, 16)
            curl = (1 if rng.random() < 0.5 else -1) if (row <= 1 and rng.random() < 0.55) else 0
            out.append((x, yb - r * 0.88, r, curl))
            x += r * rng.uniform(1.05, 1.45)
    return out


def spiral_pts(cx, cy, r0, turns, direction, a0):
    th = np.linspace(0, turns * 2 * np.pi, 120)
    rr = r0 * (1 - th / (turns * 2 * np.pi) * 0.85)
    ang = a0 + direction * th
    return np.stack([cx + rr * np.cos(ang), cy + rr * np.sin(ang)], -1)


def make_sword_cloud() -> tuple[list[Image.Image], list[Image.Image]]:
    """被劈开的云：贴在镜头上方，锚点在画布中心（中心放在画面上沿附近，下沿的云头垂进画面），按画面宽度放大约 1.9 倍。
    一道浓墨的云横在上空，云头一排排像鱼鳞往下弯，每团下沿描一道积墨的浓边、里面淡、边内一圈水痕；下面两排有几团卷成云纹。
    0：云还整着，下沿正中被剑河顶亮；1：一道金线从下往上劈开（锯齿的裂口）；2–3：两半往两边推开、靠缝的云往上翻，
    缝里漏下光柱，靠缝的云头描金；4–5：继续退开，靠缝那边散成碎云，金光淡下去。
    本体焦墨、普通混合；发光层叠加、自带金色（#E3B05A → #FFE7A8 → #FFF8E8）：缝口金线、靠缝的云边、缝里的光柱。"""
    w, h, ss = CLOUD_W, CLOUD_H, CLOUD_SS
    X, Y = V.grid(h, w, ss)
    shape = X.shape
    rng = np.random.default_rng(13201)
    billows = cloud_billows(rng)
    n_low = V.noise(np.random.default_rng(13202), shape, 40 * ss)
    n_mid = V.noise(np.random.default_rng(13203), shape, 9 * ss)
    wx = V.noise(np.random.default_rng(13204), shape, 14 * ss) * 3.2
    wy = V.noise(np.random.default_rng(13205), shape, 14 * ss) * 2.6
    tex = W.ptex(np.random.default_rng(13206), ns=24, nt=1024, along=26.0, across=0.6)
    jag_n = V.noise(np.random.default_rng(13207), (1, shape[0]), (10 * ss, 0))[0]
    jag_n2 = V.noise(np.random.default_rng(13208), (1, shape[0]), (3 * ss, 0))[0]
    cloud, emit = [], []
    for i, half0 in enumerate(CLOUD_OPEN):
        frac = np.clip((Y - 40) / 300.0, 0, 1)
        hw = half0 * (0.22 + 0.78 * frac**0.8)
        jag = ((jag_n * 7.0 + jag_n2 * 2.2) * (1.0 + 0.012 * half0))[:, None] if half0 > 0 else np.zeros((shape[0], 1))
        cxy = CLOUD_CX + jag
        side = np.where(X >= cxy, 1.0, -1.0)
        gap = np.abs(X - cxy) < hw
        near = np.clip(np.abs(X - cxy) - hw, 0, None)  # 到缝口的距离
        xs = X - side * hw
        lift = half0 * 0.16 * np.exp(-np.abs(xs - CLOUD_CX) / 110.0)
        sx, sy = xs + wx, Y + lift + wy
        A = np.zeros(shape)
        R = np.zeros(shape)  # 看得见的下沿浓边（描金用）
        sl_all = []
        for bx, by, r, curl in billows:
            # 只算这团的包围盒（推开后在画布上的位置：两半各自平移）
            shift = (half0 * 1.0 + 12) if bx >= CLOUD_CX else -(half0 * 1.0 + 12)
            x0, x1 = bx - r * 1.1 + min(0, shift) - 10, bx + r * 1.1 + max(0, shift) + 10
            r0_, r1_ = int(max((by - r * 1.1 - 12 - half0 * 0.2) * ss, 0)), int(min((by + r * 1.1 + 12) * ss, shape[0]))
            c0_, c1_ = int(max(x0 * ss, 0)), int(min(x1 * ss, shape[1]))
            if r0_ >= r1_ or c0_ >= c1_:
                continue
            sl = (slice(r0_, r1_), slice(c0_, c1_))
            dx, dy = sx[sl] - bx, (sy[sl] - by) * 1.12
            q = np.hypot(dx, dy) / r
            m = smoothstep(1.0, 0.955, q)
            ang = np.arctan2(dy, dx)
            lower = smoothstep(-0.25, 0.75, np.sin(ang))
            rim = smoothstep(0.78, 0.9, q) * lower
            bloomband = smoothstep(0.05, 0.0, np.abs(q - 0.72)) * lower
            tone = 0.9 + 0.04 * n_low[sl] + 0.04 * np.clip(dy / r, -1, 1) + 0.1 * rim - 0.16 * bloomband
            if curl:
                ccx, ccy = bx + curl * r * 0.3, by + r * 0.42
                pts = spiral_pts(ccx, ccy, r * 0.36, 1.25, curl, math.pi * (0.5 + 0.5 * curl))
                dd, tt = F.polyline_dist(sx[sl], sy[sl], pts)
                line = smoothstep(2.3 - 1.2 * tt, 0.6 - 0.5 * tt, dd)
                tone = np.maximum(tone, 0.88 * line)
                rim = np.maximum(rim, 0.6 * line)
            tone = np.clip(tone, 0, 1)
            A[sl] = tone * m + A[sl] * (1 - m)
            R[sl] = rim * m + R[sl] * (1 - m)
        # 宣纸上的墨：一点浓淡和干笔
        A *= 0.97 + 0.03 * n_mid
        edge = np.clip(A, 0, 1)
        A *= 0.95 + 0.05 * dry(tex, np.clip(n_mid * 0.5, -1, 1), sx / 1600.0 + sy / 1100.0, 0.15)
        if CLOUD_FADE[i] > 0:
            reach = 50 + 280 * CLOUD_FADE[i]
            eat = smoothstep(reach, 0.0, near) * CLOUD_FADE[i]
            A *= np.clip(1 - eat * (1.15 + 0.9 * n_mid), 0, 1)
            R *= np.clip(1 - eat * (1.15 + 0.9 * n_mid), 0, 1)
        A *= ~gap
        R *= ~gap
        frame_fade = smoothstep(4, 46, Y) * smoothstep(2, 70, X) * smoothstep(w - 2, w - 70, X)
        A *= frame_fade
        R *= frame_fade
        cloud.append(to_paint(np.clip(A, 0, 1)[..., None] * JIAO, np.clip(A, 0, 1), 13210 + i, ss=ss))
        del edge

        # 发光层
        env = CLOUD_ENV[i]
        present = np.clip(V.fft_blur(A, 6 * ss) * 2.5, 0, 1)  # 附近有云
        bot = cloud_bottom(CLOUD_CX) + 10
        parts = []
        if i == 0:
            spot = np.exp(-(((X - CLOUD_CX) / 46) ** 2 + ((Y - (bot - 26)) / 22) ** 2))
            parts.append((0.95 * spot * (0.4 + 0.6 * A), 1.0))
            seam = smoothstep(1.8, 0.0, np.abs(X - CLOUD_CX - jag_n[:, None] * 3)) * smoothstep(bot - 120, bot - 20, Y) * (Y < bot)
            parts.append((0.9 * seam * present, 1.0))
            parts.append((0.6 * R * np.exp(-np.abs(X - CLOUD_CX) / 28.0), 0.55))
        else:
            vert = smoothstep(18, 60, Y) * smoothstep(bot + 30, bot - 20, Y)
            line_w = 1.6 + 0.025 * half0
            line = np.exp(-((near / line_w) ** 2)) * vert * present * (~gap)
            parts.append((0.95 * line, 1.0))
            inner = np.exp(-near / (5 + 0.05 * half0)) * np.clip(A * 1.6, 0, 1)
            parts.append((0.3 * inner, 0.8))
            rimgold = R * np.exp(-near / (14 + 0.08 * half0))
            parts.append((0.7 * rimgold, 0.6))
            if half0 > 20:
                u = np.clip((X - CLOUD_CX) / np.maximum(hw, 1), -1, 1)
                streak = W.sample_ptex(tex, u, 0.31 + Y / 4000.0)
                shaft = gap * smoothstep(20, 90, Y) * smoothstep(h - 6, bot - 40, Y) * (0.25 + 0.75 * np.abs(u) ** 1.5)
                parts.append((0.42 * shaft * smoothstep(0.3, 0.7, streak), 0.75))
            if i <= 2:
                spot = np.exp(-(((X - CLOUD_CX) / (40 + half0)) ** 2 + ((Y - (bot - 20)) / 26) ** 2))
                parts.append((0.7 * spot, 1.0))
        a, heat = F.union_heat(parts)
        a *= env * smoothstep(2, 30, Y) * smoothstep(h - 2, h - 30, Y)
        emit.append(to_color(a, heat, 13230 + i, GOLD, ss=ss))
    return cloud, emit


# ============================================================== 规格与写出

# 名字 → (生成函数, 尺寸, 锚点, 混合, 可染, 颜色, 附加 meta)。生成函数返回帧列表；返回 (本体, 发光层) 的写两组。
SPECS: dict = {
    "sword_blade": (make_sword_blade, (BLADE_W, BLADE_H), (0.5, 0.5), "add", True, "white",
                    {"_variants": True, "points": "+x", "tint_hint": "#FFE7A8",
                     "note": "万剑归宗的剑影，3 种挑着用（不是动画）：0 长剑、1 符剑（系符纸）、2 剑气；剑尖朝 +X，锚点居中；"
                             "白色可染（建议金 #FFE7A8，金系 #E9D9A6 也行）。代码排成剑河，每柄后面拖一道 fx/streak"}),
    "sword_cloud": (make_sword_cloud, (CLOUD_W, CLOUD_H), (0.5, 0.5), "normal", False, "jiao",
                    {"emit": "sword_cloud_emit", "screen_space": "top",
                     "note": "被劈开的云：贴在镜头上方（画布中心放在画面上沿往下约 120 像素，下沿的云头垂进画面），按画面宽度放大约 2 倍；"
                             "0 整着、1 金线劈开、2–3 推开漏金光、4–5 退开散掉（12 帧/秒，0.5 秒）。焦墨、普通混合；它在天上，建议画在暗层之上（不受地上灯光照亮），"
                             "剑河之上；发光层见 sword_cloud_emit"}),
}
EMIT_SPECS = {
    "sword_cloud": {"name": "sword_cloud_emit", "blend": "add", "tint": False, "color": "full",
                    "note": "被劈开的云的发光层：缝口金线、缝里漏下的光、靠缝的云边描金；叠加、自带金色（#E3B05A → #FFE7A8 → #FFF8E8），画在暗层之上"},
}
GROUPS = {"sword": ["sword_blade", "sword_cloud"]}


def meta_for(name, spec, n, i, size_override=None, emit=None):
    _, size, anc, blend, tint, color, extra = spec
    extra = dict(extra)
    variants = extra.pop("_variants", False)
    if n == 1:
        seq = {}
    elif variants:
        seq = {"variant": i, "variants": n}
    else:
        seq = {"anim": name, "frame": i, "frames": n, "fps": extra.pop("fps", FPS), "loop": extra.pop("loop", False)}
    m = {"size": list(size_override or size), "anchor": [float(anc[0]), float(anc[1])], "color": color, "blend": blend, "tint": tint,
         **seq, "kind": "fx", **extra}
    if emit:
        m.update({"blend": emit["blend"], "tint": emit["tint"], "color": emit["color"], "layer_of": name, "note": emit["note"]})
        m.pop("emit", None)
        if n > 1:
            m["anim"] = emit["name"]
    return m


def fname(name: str, n: int, i: int) -> str:
    return f"{name}.png" if n == 1 else f"{name}_{i}.png"


def build(names: list[str]) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    meta_path = OUT / "meta.json"
    files = json.loads(meta_path.read_text(encoding="utf-8"))["files"] if meta_path.exists() else {}
    for name in names:
        t0 = time.perf_counter()
        spec = SPECS[name]
        res = spec[0]()
        body, emit = (res if isinstance(res, tuple) else (res, None))
        n = len(body)
        # 先删掉这一组旧的条目
        for k in [k for k in files if k.startswith(name + "_") or k == name + ".png"]:
            if k.startswith(name + "_emit") and emit is None:
                continue
            files.pop(k, None)
        for i, img in enumerate(body):
            assert img.size == tuple(spec[1]), (name, img.size, spec[1])
            V.save_png(img, OUT / fname(name, n, i))
            files[fname(name, n, i)] = meta_for(name, spec, n, i)
        if emit is not None:
            en = EMIT_SPECS[name]
            for i, img in enumerate(emit):
                assert img.size == tuple(spec[1])
                V.save_png(img, OUT / fname(en["name"], n, i))
                files[fname(en["name"], n, i)] = meta_for(name, spec, n, i, emit=en)
        print(f"{name}: {n} 帧{' + 发光层' if emit else ''}  {time.perf_counter() - t0:.1f}s", flush=True)
    meta = {"name": "myth", "generator": GENERATOR, "format": "PNG RGBA，直通（非预乘）alpha", "px_per_unit": PPU, "files": dict(sorted(files.items()))}
    meta_path.write_text(V.dump_json(meta), encoding="utf-8")


def load(name: str) -> list[Image.Image]:
    """读回一组（审图、分镜用）。单张的返回一个元素的列表。"""
    if (OUT / f"{name}.png").exists():
        return [Image.open(OUT / f"{name}.png").convert("RGBA")]
    out = []
    i = 0
    while (OUT / f"{name}_{i}.png").exists():
        out.append(Image.open(OUT / f"{name}_{i}.png").convert("RGBA"))
        i += 1
    if not out:
        raise FileNotFoundError(name)
    return out


def main(args: list[str]) -> None:
    names = []
    for a in args or list(GROUPS):
        names += GROUPS.get(a, [a])
    build(names)


if __name__ == "__main__":
    main(sys.argv[1:])
