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


# ============================================================== 北冥潮：脚下冰海


SEA_W, SEA_H = 1024, 640
SEA_RX, SEA_RY = 500.0, 500.0 * F.FLAT
SEA_RW = [0.05, 0.25, 0.52, 0.8, 0.84, 0.86]  # 水面半径（× SEA_RX）
SEA_PHASE = [0.0, 0.25, 0.5, 0.75, 1.08, 1.41]  # 波纹往外推的相位（3–5 帧循环：每帧 1/3 个波长）
SEA_BAND = 0.17  # 碎冰带的宽度
SEA_FROST = 0.16  # 冰带外面一圈霜
WATER = [(0.0, "#2A4E70"), (0.5, "#3D6890"), (1.0, "#5885B0")]  # 深 → 浅（冰海自己往上透冷光，水是亮的灰蓝，鲲影压得出来）
ICE_TOP, ICE_EDGE, ICE_CRACK = V.col("#C8D9E8"), V.col("#8CA4BB"), V.col("#1E3044")
FROST = V.col("#D8E6F0")
ICE_LIGHT = [(0.0, "#7FB6E8"), (0.6, ICE), (1.0, "#F4FBFF")]


def voronoi(U, Vv, pts):
    """到最近、次近种子点的距离（F1、F2）和最近的编号。U、V 是去掉透视压扁后的地面坐标。"""
    f1 = np.full(U.shape, 1e9)
    f2 = np.full(U.shape, 1e9)
    idx = np.zeros(U.shape, dtype=np.int32)
    for k, (pu, pv) in enumerate(pts):
        d = np.hypot(U - pu, Vv - pv)
        closer = d < f1
        f2 = np.where(closer, f1, np.minimum(f2, d))
        idx = np.where(closer, k, idx)
        f1 = np.where(closer, d, f1)
    return f1, f2, idx


def make_kun_sea() -> tuple[list[Image.Image], list[Image.Image]]:
    """脚下冰海（已压扁，锚点在中心 = 主角脚下）：地面先结霜、裂开，正中翻开一片墨蓝的海，往外推出一圈圈波纹（带一点旋），
    水边一圈碎冰板往外挤，再外面一圈霜。0 霜和放射的冰裂（缝里透冷光）；1 正中翻开；2–3 海往外漫；3–5 满了，波纹往外推（可循环）。
    本体普通混合（墨蓝的水、灰蓝的冰板、霜白），发光层叠加、自带冰色（#CDEBFF）：冰缝、水边冰下透的光、浪尖的亮线和碎光。"""
    w, h = SEA_W, SEA_H
    X, Y = V.grid(h, w, 1)
    cx, cy = w / 2, h / 2
    U, Vv = (X - cx) / SEA_RX, (Y - cy) / SEA_RY
    r = np.hypot(U, Vv)
    th = np.arctan2(Vv, U)
    px = 1.0 / SEA_RX  # 一个像素在地面坐标里多长（横向）
    rng = np.random.default_rng(13301)
    rough = 1.0 + V.angular_noise(np.random.default_rng(13302), th, harmonics=(3, 5, 7, 9, 13), amp=0.09)
    # 冰板：种子按半径均匀撒（中间密一点）
    n_seed = 340
    rs = np.sqrt(rng.uniform(0.0, 1.25, n_seed)) * 1.08
    ts = rng.uniform(0, 2 * math.pi, n_seed)
    pts = np.stack([rs * np.cos(ts), rs * np.sin(ts)], -1)
    f1, f2, idx = voronoi(U, Vv, pts)
    cell_r = rs[idx]
    shade = rng.uniform(0, 1, n_seed)[idx]
    edge_d = (f2 - f1) / 2  # 到冰板边的距离（地面坐标）
    n1 = V.noise(np.random.default_rng(13303), (h, w), 30)
    n2 = V.noise(np.random.default_rng(13304), (h, w), 6)
    n3 = V.noise(np.random.default_rng(13305), (h, w), 2.5)
    n_seg = V.noise(np.random.default_rng(13306), (h, w), 16)  # 浪线断开的地方（长短不齐）
    # 放射的冰裂（第 0 帧最显眼，后面留在霜里）
    cracks = []
    for k in range(11):
        ang = 2 * math.pi * k / 11 + rng.uniform(-0.2, 0.2)
        cracks.append(F.jag_path(rng, (cx, cy), ang, rng.uniform(260, 470), n=16, jitter=0.32))
    crack_d = np.full((h, w), 1e9)
    crack_t = np.zeros((h, w))
    for c in cracks:
        c = c.copy()
        c[:, 1] = cy + (c[:, 1] - cy) * F.FLAT
        d, t = F.polyline_dist(X, Y, c)
        better = d < crack_d
        crack_d = np.where(better, d, crack_d)
        crack_t = np.where(better, t, crack_t)
    body, emit = [], []
    for i in range(6):
        Rw = SEA_RW[i] * rough
        rel = r / np.maximum(Rw, 1e-3)  # 1 是水边
        water = smoothstep(1.0 + 2.5 * px / Rw, 1.0 - 2.5 * px / Rw, rel)
        band_out = Rw + SEA_BAND
        # 冰板：种子在水边附近的那几块浮着，外面的还连着地
        plate_zone = (cell_r > Rw - 0.06) & (cell_r < band_out + 0.02)
        plate_in = smoothstep(0.0, 2.2 * px, edge_d - (0.6 + 2.2 * smoothstep(band_out, Rw, r)) * px)  # 越靠水边缝越宽
        plate = plate_in * plate_zone * smoothstep(band_out + 0.02, band_out - 0.03, r) * (1 - water)
        frost_zone = smoothstep(band_out + SEA_FROST, band_out, r) * smoothstep(Rw - 0.02, Rw + 0.03, r)
        if i == 0:
            frost_zone = smoothstep(0.85, 0.3, r)
            plate = plate * 0
        frost = frost_zone * np.clip(0.55 + 0.35 * n1 + 0.2 * n2, 0, 1) * (1 - plate)
        hair = smoothstep(1.2 * px, 0.0, edge_d) * frost_zone * (cell_r > band_out - 0.02)  # 霜里冰板的细缝
        crack_vis = smoothstep(2.2, 0.6, crack_d * (1.0 + 1.5 * crack_t)) * smoothstep(1.0, 0.75, crack_t) * (1 - water)
        crack_vis *= (frost_zone if i else smoothstep(0.95, 0.2, r))
        # 水：墨蓝，中间略深；海水纹——一圈圈细的浪线往外推（带一点旋），断断续续，有几段卷起白沫；水边一圈白沫
        depth = np.clip(1 - rel, 0, 1)
        phi = r * 8.0 - SEA_PHASE[i] * 1.0 + 0.5 * th / (2 * math.pi) + 0.12 * n1
        fr = np.abs(np.mod(phi, 1.0) - 0.5)  # 0 在浪线上
        brk = np.clip((n_seg + 0.25) * 1.6, 0, 1)  # 浪线一段段的，两头收尖
        lw = (0.035 + 0.035 * smoothstep(0.2, 0.9, rel)) * brk  # 外圈的浪线粗一点
        line = smoothstep(lw + 0.012, lw * 0.3, fr) * (brk > 0.02) * water * smoothstep(0.08, 0.3, rel)
        cap = smoothstep(0.6, 0.95, n1 * 0.5 + 0.5) * smoothstep(0.1, 0.6, brk)  # 卷起白沫的几段
        foam_seg = smoothstep(lw * 2.6 + 0.012, lw * 0.8, fr) * cap * water * smoothstep(0.3, 0.7, rel) * smoothstep(-0.4, 0.3, n2)
        foam = np.maximum(smoothstep(0.88, 0.995, rel) * water * (0.55 + 0.45 * smoothstep(-0.2, 0.6, n2)), foam_seg)
        crest = line
        wave = 1.0 - fr * 2  # 浪尖亮线用
        wcol = F.lerp_col(np.clip(0.55 - 0.35 * depth + 0.08 * n2 + 0.06 * n1, 0, 1), WATER)
        wcol = wcol * (1 - line[..., None] * 0.7) + V.col("#9CC0DE") * (line[..., None] * 0.7)
        wcol = wcol * (1 - foam[..., None] * 0.85) + V.col("#CFE0EC") * (foam[..., None] * 0.85)
        # 冰板颜色：板面淡、边上深一点，每块略有不同
        pcol = ICE_EDGE + (ICE_TOP - ICE_EDGE) * np.clip(smoothstep(0, 9 * px, edge_d) * (0.75 + 0.25 * shade) + 0.08 * n3, 0, 1)[..., None]
        # 合起来（普通混合）：水在下，冰板、霜、冰缝依次盖上
        a = np.clip(water * 0.9, 0, 1)
        rgb = wcol * a[..., None]
        for col_, al in ((pcol, plate * 0.95), (FROST, frost * 0.55), (ICE_CRACK, np.maximum(hair * 0.6, crack_vis * 0.85))):
            al = np.clip(al, 0, 1)
            rgb = col_ * al[..., None] + rgb * (1 - al[..., None])
            a = al + a * (1 - al)
        edge_fade = smoothstep(0, 6, X) * smoothstep(w, w - 6, X) * smoothstep(0, 6, Y) * smoothstep(h, h - 6, Y)
        a *= edge_fade
        body.append(to_paint(rgb * edge_fade[..., None], a, 13310 + i, ss=1))
        # 发光层
        parts = []
        cg = smoothstep(1.6, 0.0, crack_d * (1.0 + 1.2 * crack_t)) * smoothstep(1.0, 0.6, crack_t) * (1 - water)
        cg *= (frost_zone if i else 1.0) * ([1.0, 0.7, 0.45, 0.3, 0.25, 0.25][i])
        parts.append((0.95 * cg, 1.0))
        parts.append((0.35 * smoothstep(3.0, 0.0, crack_d) * (1 - water) * (frost_zone if i else smoothstep(0.9, 0.2, r)) * [1.0, 0.6, 0.4, 0.3, 0.3, 0.3][i], 0.6))
        if i >= 1:
            rim = np.exp(-(((rel - 1.0) * Rw / (0.014)) ** 2)) * (1 - plate * 0.6)  # 水边冰下透的光
            parts.append((0.6 * rim, 0.8))
            gaps = smoothstep(1.4 * px, 0.0, edge_d - 0.4 * px) * plate_zone * smoothstep(band_out, Rw, r) * (1 - water) * (r > Rw)
            parts.append((0.55 * gaps, 0.7))  # 冰板缝里透的光
            hi = crest * smoothstep(0.2, 0.8, n2 * 0.5 + 0.5)
            parts.append((0.26 * hi, 0.8))  # 浪线上一段段的亮
            parts.append((0.4 * foam_seg, 0.95))  # 白沫
            hair_g = hair * 0.3
            parts.append((hair_g, 0.6))
        if i == 0:
            parts.append((0.7 * np.exp(-(r / 0.06) ** 2), 1.0))  # 脚下一点亮
        aa, heat = F.union_heat(parts)
        emit.append(to_color(aa * edge_fade, heat, 13330 + i, ICE_LIGHT, ss=1))
    return body, emit


# ============================================================== 北冥潮：鲲影（俯视，在冰海底下游过去）


SHADOW_W, SHADOW_H = 1536, 512


def smooth_profile(xs, hs, n=400):
    """按控制点 (x, 半宽) 插值成平滑的轮廓（三次 Hermite，斜率按相邻点）。"""
    xs, hs = np.asarray(xs, float), np.asarray(hs, float)
    t = np.linspace(xs[0], xs[-1], n)
    m = np.gradient(hs, xs)
    out = np.zeros_like(t)
    for k in range(len(xs) - 1):
        sel = (t >= xs[k]) & (t <= xs[k + 1])
        dx = xs[k + 1] - xs[k]
        u = (t[sel] - xs[k]) / dx
        h00, h10, h01, h11 = 2 * u**3 - 3 * u**2 + 1, u**3 - 2 * u**2 + u, -2 * u**3 + 3 * u**2, u**3 - u**2
        out[sel] = h00 * hs[k] + h10 * dx * m[k] + h01 * hs[k + 1] + h11 * dx * m[k + 1]
    return t, out


def make_kun_shadow() -> list[Image.Image]:
    """鲲影：俯视的一条大鱼，头朝 +X，在冰海底下游过去。钝圆的头、纺锤形的身子、一对翅膀一样往后掠的大胸鳍（鲲化为鹏），
    小腹鳍，叉开的大尾。焦墨、普通混合（身子最浓约 0.95——合成在线性光里，0.9 才看着压得住；鳍往梢上变淡），边是水下的虚边；背脊一道深的，
    身上鳞纹淡淡几排，水面的光纹（焦散）从身上淡出一张网。代码把它放大到 2.5 倍以上，画面装不下。"""
    w, h, ss = SHADOW_W, SHADOW_H, 2
    cy = h / 2
    X, Y = V.grid(h, w, ss)
    # 身子：控制点 (x, 半宽)
    bx, bh = smooth_profile([330, 420, 560, 760, 950, 1120, 1270, 1380, 1450, 1490, 1506],
                            [26, 42, 76, 120, 152, 162, 154, 130, 96, 50, 0], 500)
    top = np.stack([bx, cy - bh], -1)
    bot = np.stack([bx[::-1], cy + bh[::-1]], -1)
    body_poly = np.concatenate([top, bot])
    tail = [(345, cy - 30), (300, cy - 62), (232, cy - 128), (150, cy - 196), (118, cy - 190), (170, cy - 120), (214, cy - 52), (236, cy),
            (214, cy + 52), (170, cy + 120), (118, cy + 190), (150, cy + 196), (232, cy + 128), (300, cy + 62), (345, cy + 30)]
    fins = []
    for sgn in (-1, 1):
        # 胸鳍像一对往后掠的翅膀：根在身子里（960–1200），前缘鼓出去，梢在 (690, ±242)，后缘一道道扇贝似的缺口（鳍条）
        lead = V.bezier([(1200, cy + sgn * 110), (1130, cy + sgn * 232), (930, cy + sgn * 252), (690, cy + sgn * 242)], 70)
        tr = V.bezier([(690, cy + sgn * 242), (790, cy + sgn * 200), (880, cy + sgn * 160), (960, cy + sgn * 112)], 70)
        tt = np.linspace(0, 1, len(tr))
        scal = np.abs(np.sin(tt * math.pi * 5)) * 12 * (1 - tt * 0.5)
        tr = tr + np.stack([np.zeros_like(tt) - scal * 0.4, -sgn * scal], -1)
        fins.append(np.concatenate([lead, tr]))
        pel_l = V.bezier([(680, cy + sgn * 96), (630, cy + sgn * 158), (570, cy + sgn * 176), (520, cy + sgn * 172)], 30)
        pel_t = V.bezier([(520, cy + sgn * 172), (565, cy + sgn * 144), (605, cy + sgn * 116), (630, cy + sgn * 92)], 30)
        fins.append(np.concatenate([pel_l, pel_t]))
    m_body = mask_polys(w, h, [body_poly], ss)
    m_tail = mask_polys(w, h, [tail], ss)
    m_fin = mask_polys(w, h, fins, ss)
    blur = 3.2 * ss
    mb, mt, mf = (V.fft_blur(m, blur) for m in (m_body, m_tail, m_fin))
    n1 = V.noise(np.random.default_rng(13401), X.shape, 40 * ss)
    n2 = V.noise(np.random.default_rng(13402), X.shape, 7 * ss)
    # 背脊和身上的浓淡：中线最浓，往两边淡；头更浓
    across = np.abs(Y - cy) / np.maximum(np.interp(X, bx, bh), 1.0)
    spine = smoothstep(0.35, 0.0, across) * smoothstep(380, 600, X) * smoothstep(1460, 1300, X)
    body_a = mb * (0.86 + 0.08 * spine + 0.04 * smoothstep(1150, 1420, X) - 0.1 * across**4 + 0.03 * n1)
    # 鳞纹：几排往后开的弧（淡一点的线）
    scale_u = (X - 600) / 46.0
    scale_v = (Y - cy) / 40.0
    arcs = np.abs(np.sin(np.pi * (scale_u - 0.35 * scale_v**2 * 0 + 0.5 * np.abs(scale_v)))) < 0.12
    body_a -= 0.05 * arcs * mb * smoothstep(600, 760, X) * smoothstep(1250, 1100, X) * smoothstep(0.85, 0.3, across)
    # 鳍：根浓梢淡，鳍条一道道
    fin_r = np.clip((1180 - X) / 480.0, 0, 1)
    rays = 0.5 + 0.5 * np.cos((np.arctan2(np.abs(Y - cy) - 110, X - 1150)) * 24)
    fin_a = mf * (0.8 - 0.3 * fin_r + 0.08 * rays * smoothstep(0.1, 0.5, fin_r))
    tail_a = mt * (0.78 - 0.22 * np.clip((330 - X) / 200, 0, 1) + 0.04 * n1)
    a = 1 - (1 - np.clip(body_a, 0, 1)) * (1 - np.clip(fin_a, 0, 1)) * (1 - np.clip(tail_a, 0, 1))
    # 水面的焦散光纹（两层噪声的零线织成网）：从影子里减掉一点
    c1 = V.noise(np.random.default_rng(13403), X.shape, 16 * ss)
    c2 = V.noise(np.random.default_rng(13404), X.shape, 11 * ss)
    caustic = np.maximum(smoothstep(0.07, 0.0, np.abs(c1)), smoothstep(0.06, 0.0, np.abs(c2)))
    a *= 1 - 0.1 * caustic
    a *= 0.97 + 0.03 * n2
    a = np.clip(a, 0, 0.95)
    a *= smoothstep(0, 10, X) * smoothstep(w, w - 10, X) * smoothstep(0, 10, Y) * smoothstep(h, h - 10, Y)
    return [to_paint(a[..., None] * JIAO, a, 13410, ss=ss)]


# ============================================================== 北冥潮：鲲跃出水（侧面，冷光剪影）


LEAP_SIZE = 768
LEAP_WATER = 700.0  # 水面（画布 y），锚点在这条线的正中
LEAP_L = 600.0  # 鲲身长（像素）
KUN_LIGHT = [(0.0, "#5E9AD8"), (0.45, "#9FD0F5"), (0.75, ICE), (1.0, "#F6FCFF")]
# 每帧的脊线（贝塞尔，尾 → 头），以及露出水的程度
LEAP_SPINES = [
    [(300, 1040), (312, 880), (325, 720), (340, 560)],
    [(270, 930), (300, 720), (340, 520), (400, 330)],
    [(120, 540), (210, 190), (470, 100), (640, 290)],
    [(200, 250), (380, 70), (560, 210), (575, 620)],
    [(450, 330), (535, 330), (575, 600), (570, 900)],
    [(520, 610), (548, 700), (566, 820), (570, 1000)],
]
LEAP_SPLASH = [(1.0, 335), (0.8, 330), (0.3, 230), (0.35, 572), (1.0, 568), (0.6, 560)]  # (水花大小, x)


def fish_outline():
    """侧面的鲲，局部坐标 (u 从尾 0 到吻 1, v 背上为正)，单位是身长。返回 (身子, [鳍…]) 的多边形。"""
    us = [0.1, 0.2, 0.35, 0.5, 0.65, 0.78, 0.88, 0.95, 0.985, 1.0]
    back = [0.032, 0.056, 0.092, 0.118, 0.128, 0.118, 0.094, 0.062, 0.03, 0.0]
    belly = [-0.03, -0.05, -0.078, -0.098, -0.11, -0.104, -0.086, -0.06, -0.03, -0.008]
    tb, vb = smooth_profile(us, back, 120)
    tl, vl = smooth_profile(us, belly, 120)
    body = [(u, v) for u, v in zip(tb, vb)] + [(u, v) for u, v in zip(tl[::-1], vl[::-1])]
    tail = [(0.12, 0.028), (0.06, 0.07), (-0.01, 0.14), (-0.07, 0.19), (-0.06, 0.15), (-0.02, 0.07), (0.035, 0.0),
            (-0.02, -0.07), (-0.06, -0.15), (-0.07, -0.18), (-0.01, -0.13), (0.06, -0.065), (0.12, -0.028)]
    body = [tail[-1]] + body + [tail[0]]  # 尾柄接上
    def wing(root_f, lead_c, tip, trail_c, root_b, n_scal, depth):
        """一只鳍（翅膀）：前缘、后缘各一条贝塞尔；后缘一道道扇贝似的缺口（鳍条之间）。"""
        lead = V.bezier([root_f, lead_c[0], lead_c[1], tip], 50)
        tr = V.bezier([tip, trail_c[0], trail_c[1], root_b], 50)
        tt = np.linspace(0, 1, len(tr))
        d = np.gradient(tr, axis=0)
        d /= np.linalg.norm(d, axis=1, keepdims=True) + 1e-9
        nrm = np.stack([-d[:, 1], d[:, 0]], -1)
        tr = tr + nrm * (np.abs(np.sin(tt * math.pi * n_scal)) * depth * (1 - 0.6 * tt))[:, None]
        return [tuple(p) for p in lead] + [tuple(p) for p in tr]
    # 近侧的胸鳍往下后方张开，宽大像翅膀；远侧的在身子后面，往上后方，小一点
    wing_near = wing((0.77, -0.05), [(0.7, -0.27), (0.55, -0.41)], (0.33, -0.45), [(0.42, -0.33), (0.52, -0.2)], (0.6, -0.06), 4, 0.02)
    wing_far = wing((0.75, 0.06), [(0.69, 0.2), (0.58, 0.28)], (0.45, 0.3), [(0.52, 0.22), (0.57, 0.14)], (0.61, 0.08), 3, 0.014)
    dorsal = [(0.42, 0.11), (0.47, 0.17), (0.55, 0.16), (0.6, 0.125)]
    anal = [(0.24, -0.065), (0.2, -0.11), (0.15, -0.1), (0.15, -0.045)]
    return body, [wing_near, wing_far, dorsal, anal, tail]


def bend(pts_uv, spine, L):
    """局部 (u, v) → 画布：吻在脊线的末端，往回沿脊线（按弧长）量 (1 − u)·L；脊线不够长时顺着起点的切线往外延。
    v 沿法线（背朝脊线的左手边，画面 y 向下）。"""
    sp = V.bezier(spine, 400)
    seg = np.hypot(*np.diff(sp, axis=0).T)
    s = np.concatenate([[0], np.cumsum(seg)])
    total = float(s[-1])
    tan = np.gradient(sp, axis=0)
    tan /= np.linalg.norm(tan, axis=1, keepdims=True)
    nrm = np.stack([tan[:, 1], -tan[:, 0]], -1)
    out = []
    for u, v in pts_uv:
        sa = total - (1.0 - u) * L
        if sa < 0:
            p, n_ = sp[0] + sa * tan[0], nrm[0]
        else:
            j = min(int(np.searchsorted(s, sa)), len(sp) - 1)
            p, n_ = sp[j], nrm[j]
        out.append(p + v * L * n_)
    return np.array(out)


def make_kun_leap() -> list[Image.Image]:
    """鲲跃出水：侧面的冷光剪影，头朝 +X，从水里冲出来、拱成一道弧、再扎回去。剪影的边最亮，身子里淡淡透光，
    一道道冷光顺着身子往后流；一对鳍张开像翅膀（鲲化为鹏），眼和鳃一道亮线；身上往下淌水，水面炸开水花。
    0 头破水、水花冲天；1 半身出水；2 整条跃到最高（鳍全张）；3 翻过去头朝下；4 扎回水里、水花；5 只剩水花落下。
    叠加，自带冷光色（#5E9AD8 → #CDEBFF → 白）。锚点在水面线正中（底边往上 68 像素）。"""
    size, ss = LEAP_SIZE, 2
    X, Y = V.grid(size, size, ss)
    rng = np.random.default_rng(13501)
    tex = W.ptex(rng, ns=24, nt=1024, along=40.0, across=0.6)
    body_uv, fins_uv = fish_outline()
    out = []
    for i, spine in enumerate(LEAP_SPINES):
        body = bend(body_uv, spine, LEAP_L)
        fins = [bend(f, spine, LEAP_L) for f in fins_uv]
        m_body = mask_polys(size, size, [body], ss)
        m_fin = mask_polys(size, size, fins[:2], ss)
        m_small = mask_polys(size, size, fins[2:], ss)  # 背鳍、臀鳍、尾鳍
        m_all = np.clip(m_body + m_fin + m_small, 0, 1)
        inner, outer = edge_band(m_all, 2.2 * ss)
        inner_b, _ = edge_band(m_body, 1.6 * ss)
        # 沿身子的坐标：脊线上的点
        sp = V.bezier(spine, 160)
        f = V.stroke_fields(X[::ss, ::ss], Y[::ss, ::ss], sp, np.full(len(sp), 90.0))  # 粗网格上算，再放大（流光本来就柔）
        t_along = np.repeat(np.repeat(f["t"], ss, 0), ss, 1)
        perp = np.repeat(np.repeat(f["perp"], ss, 0), ss, 1)
        flow = W.sample_ptex(tex, np.clip(perp / 80.0, -1, 1), t_along * 1.4 - 0.12 * i)
        streak = smoothstep(0.55, 0.85, flow) * m_body
        fill = 0.16 * m_body + 0.1 * m_fin + 0.08 * m_small
        rim = 0.95 * inner + 0.55 * inner_b
        glow_out = 0.22 * outer
        # 眼、鳃
        eye_p = bend([(0.9, 0.03)], spine, LEAP_L)[0]
        eye = F.dot(X, Y, eye_p[0], eye_p[1], 5.5) + 0.5 * np.exp(-np.hypot(X - eye_p[0], Y - eye_p[1]) ** 2 / 200.0)
        gill = bend([(0.82, v) for v in np.linspace(0.08, -0.08, 20)], spine, LEAP_L)
        acc = Acc(X, Y)
        gill_l = np.zeros_like(X)
        sl = acc.window(*(gill.min(0) - 6), *(gill.max(0) + 6))
        gd, _ = F.polyline_dist(X[sl], Y[sl], gill)
        gill_l[sl] = smoothstep(2.6, 0.6, gd) * 0.7
        # 鳍条：从鳍根往外的几道线
        ray_l = np.zeros_like(X)
        for fi, (root, tips) in enumerate((((0.72, -0.06), [(0.34 + 0.065 * k, -0.43 + 0.075 * k) for k in range(5)]),
                                           ((0.71, 0.07), [(0.46 + 0.04 * k, 0.28 - 0.04 * k) for k in range(4)]),
                                           ((0.1, 0.0), [(-0.06, 0.17), (-0.03, 0.1), (-0.03, -0.1), (-0.06, -0.16)]))):
            for tip in tips:
                seg_pts = bend([(root[0] + (tip[0] - root[0]) * q, root[1] + (tip[1] - root[1]) * q) for q in np.linspace(0, 1, 16)], spine, LEAP_L)
                sl = acc.window(*(seg_pts.min(0) - 5), *(seg_pts.max(0) + 5))
                d, tq = F.polyline_dist(X[sl], Y[sl], seg_pts)
                ray_l[sl] = np.maximum(ray_l[sl], smoothstep(2.2, 0.5, d) * (1 - 0.6 * tq))
        ray_l *= np.clip(m_fin + m_small, 0, 1)
        lum = F.soft_union(fill, rim, glow_out, 0.42 * streak, eye, gill_l * m_body, 0.45 * ray_l)
        heat = np.clip(0.35 + 0.65 * (rim + eye + 0.5 * streak), 0, 1)
        # 水下的部分：看不见（只剩一点透上来的光）
        under = smoothstep(LEAP_WATER - 6, LEAP_WATER + 10, Y)
        lum = lum * (1 - under) + 0.12 * lum * under * smoothstep(LEAP_WATER + 90, LEAP_WATER, Y)
        acc.add((slice(None), slice(None)), lum, heat)
        # 身上往下淌的水：从身子下沿拖下来的细线和水珠
        r2 = np.random.default_rng(13510 + i)
        if 1 <= i <= 3:
            for _ in range(26):
                u = r2.uniform(0.05, 0.95)
                p0 = bend([(u, r2.uniform(-0.1, 0.1))], spine, LEAP_L)[0]
                if p0[1] > LEAP_WATER - 10:
                    continue
                L = r2.uniform(16, 64)
                x1, y1 = p0[0] - r2.uniform(-10, 10), p0[1] + L
                y1 = min(y1, LEAP_WATER)
                sl = acc.window(min(x1, p0[0]) - 6, p0[1] - 6, max(x1, p0[0]) + 6, y1 + 6)
                acc.add(sl, 0.55 * F.streak(X[sl], Y[sl], x1, y1, p0[0], p0[1], r2.uniform(1.0, 2.2)), 0.8)
                sl = acc.window(x1 - 6, y1 - 8, x1 + 6, y1 + 6)
                acc.add(sl, 0.8 * F.dot(X[sl], Y[sl], x1, min(y1, LEAP_WATER - 2), r2.uniform(1.5, 3.2)), 0.9)
        # 水花：水面上一圈冲起来的水针 + 水珠
        amp, sx = LEAP_SPLASH[i]
        if amp > 0:
            for k in range(int(30 * amp) + 6):
                ang = -math.pi / 2 + r2.uniform(-1.05, 1.05) * (0.7 if i in (0, 4) else 1.0)
                L = r2.uniform(40, 200) * amp * (1.0 - 0.45 * abs(ang + math.pi / 2))
                x0 = sx + r2.uniform(-60, 60) * amp
                x1, y1 = x0 + L * math.cos(ang), LEAP_WATER + L * math.sin(ang)
                sl = acc.window(min(x0, x1) - 10, min(LEAP_WATER, y1) - 10, max(x0, x1) + 10, max(LEAP_WATER, y1) + 10)
                cov, u_ = F.needle(X[sl], Y[sl], x0, LEAP_WATER, ang, L, r2.uniform(2.5, 5.5) * amp + 1)
                m = dry(tex, 0.0, u_ * 0.5 + k * 0.13, 0.15 + 0.4 * u_)
                acc.add(sl, 0.75 * cov * m, 0.7 + 0.3 * (1 - u_))
            for k in range(int(40 * amp) + 8):
                x = sx + r2.normal(0, 70 * amp)
                y = LEAP_WATER - abs(r2.normal(0, 110 * amp)) - 10
                sl = acc.window(x - 6, y - 6, x + 6, y + 6)
                acc.add(sl, 0.85 * F.dot(X[sl], Y[sl], x, y, r2.uniform(1.4, 3.6)), 0.9)
            # 水面一道亮线（压扁的环）
            ring = np.exp(-(((Y - LEAP_WATER) / 5.0) ** 2)) * smoothstep(150 * amp + 40, 30, np.abs(X - sx))
            acc.add((slice(None), slice(None)), 0.7 * ring, 0.8)
        a, hh = acc.a, acc.heat()
        a *= smoothstep(LEAP_WATER + 40, LEAP_WATER + 8, Y)
        out.append(to_color(a, hh, 13520 + i, KUN_LIGHT, ss=ss))
    return out


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
    "kun_sea": (make_kun_sea, (SEA_W, SEA_H), (0.5, 0.5), "normal", False, "full",
                {"emit": "kun_sea_emit", "flat": F.FLAT, "radius_px": int(SEA_RX), "fps": 8, "hold_last": True,
                 "note": "北冥潮的脚下冰海：锚点在中心（主角脚下），已压扁，radius_px 是满了以后的横向半径（第 3–5 帧水面约 0.85 倍）；"
                         "0 结霜冰裂、1 正中翻开、2–3 海往外漫、3–5 满了波纹往外推（3–5 可以循环到鲲游完）。灰蓝的水、浅灰蓝冰板、霜白，"
                         "普通混合（暗层之下、妖物之下）；发光层见 kun_sea_emit。代码按要盖住的范围放大（分镜里约 2.4–2.7 倍），"
                         "并在光照图里给冰海加一盏大的冷光（#CDEBFF，盖住水面），水才亮得起来、鲲影压得出来"}),
    "kun_shadow": (make_kun_shadow, (SHADOW_W, SHADOW_H), (0.5, 0.5), "normal", False, "jiao",
                   {"points": "+x", "note": "鲲影：俯视的大鱼，头朝 +X，锚点居中；焦墨（身子最浓约 0.95，鳍梢约 0.5），水下的虚边、背脊、鳞纹、水面焦散的光纹；"
                                             "画在冰海之上、妖物之下。代码放大约 2 倍（比画面宽）从画面一侧平移到另一侧；放到 2.5 倍以上整片海都在影子里，反而看不出鱼形，可以轻轻左右摆尾（整张绕头转几度）"}),
    "kun_leap": (make_kun_leap, (LEAP_SIZE, LEAP_SIZE), (0.5, LEAP_WATER / LEAP_SIZE), "add", False, "full",
                 {"points": "+x", "fps": 12,
                  "note": "鲲跃出水：侧面的冷光剪影，头朝 +X；锚点在水面线正中。0 破水、1 半身、2 跃到最高（鳍张开像翅膀）、3 翻过去、4 扎回、5 水花落下；"
                          "叠加、自带冷光色（#5E9AD8 → #CDEBFF → 白）。12 帧/秒，第 2 帧上顿帧 0.08 秒；代码放大约 1.9 倍"}),
}
EMIT_SPECS = {
    "sword_cloud": {"name": "sword_cloud_emit", "blend": "add", "tint": False, "color": "full",
                    "note": "被劈开的云的发光层：缝口金线、缝里漏下的光、靠缝的云边描金；叠加、自带金色（#E3B05A → #FFE7A8 → #FFF8E8），画在暗层之上"},
}
EMIT_SPECS["kun_sea"] = {"name": "kun_sea_emit", "blend": "add", "tint": False, "color": "full",
                         "note": "冰海的发光层：冰缝、水边冰下透的光、冰板缝、浪尖亮线和碎光；叠加、自带冰色（#7FB6E8 → #CDEBFF → 白），画在暗层之上"}
GROUPS = {"sword": ["sword_blade", "sword_cloud"], "kun": ["kun_sea", "kun_shadow", "kun_leap"]}


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
