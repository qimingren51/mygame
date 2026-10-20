#!/usr/bin/env python3
"""提灯夜行 · 神话特效的元件（docs/FEEL.md 第 13 节，四个样张）。只出桌面版 2 倍，Pillow + numpy，不用 Blender。

约定同逐帧特效（FEEL 第 12 节、vfx_frames.py）：
  - 2 倍密度（4 像素 / 世界单位），一次性的按 24 帧/秒；叠加帧最亮处 alpha 约 0.8，边上要飞白、干笔断续；
  - 普通混合的墨用焦墨 #17140F；方向朝 +X；地面的已按透视压扁（高 ÷ 宽 ≈ 0.62）。
  - 帧名 myth/<演出>_<元件>_<帧号>，单张的不带帧号；发光层是同画布、同锚点、同帧号的 <演出>_<元件>_<帧号>_emit（单张的 <演出>_<元件>_emit，
    同 actors 图集），meta 写 layer_of：本体普通混合（暗层之下），发光层叠加（暗层之上）。
  - 放新图集 myth（演出少见，单独一页）。

元件（FEEL 13.2）：
  万剑归宗  sword_blade_0..2（3 种剑影，96×24，叠加，可染金，挑着用）、sword_giant（大剑影，1024×160，剑柱最外一层）
            sword_cloud_0..5（被劈开的云，1024×512，焦墨）+ sword_cloud_emit_0..5（裂口金光，叠加）
  北冥潮    kun_sea_0..5（脚下冰海，1024×640 已压扁，墨蓝）+ kun_sea_emit_0..5（冰光，叠加）
            kun_shadow（鲲影，1536×512，焦墨，头朝 +X）+ kun_shadow_emit、kun_fin（露出水面的背鳍）+ kun_fin_emit
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


# ============================================================== 万剑归宗：大剑影（剑柱最外一层）


GIANT_W, GIANT_H = 1024, 160


def make_sword_giant() -> list[Image.Image]:
    """大剑影（1024×160，剑尖朝 +X，锚点在剑格中心）：剑柱最外一层，代码拿 3–5 张叠成一柄顶天的大剑（大小、角度、明暗错开）。
    剑身直、两刃，中脊一线最亮，脊两边各一道细的血槽线；剑身上一串淡的符文（刻进去的，暗）；如意剑格两头卷起；缠绳剑柄、圆环剑首，
    剑首拖两缕剑穗（飞白）。剑尖一点烧白。白色可染（建议金 #FFE7A8），叠加。"""
    w, h, ss = GIANT_W, GIANT_H, 2
    X, Y = V.grid(h, w, ss)
    cy = h / 2
    rng = np.random.default_rng(13901)
    tex = W.ptex(rng, ns=24, nt=1024, along=40.0, across=0.6)
    gx = 250.0  # 剑格
    tip = 1010.0
    u = np.clip((X - gx) / (tip - gx), 0, 1)
    hw = 21.0 - 4.0 * u
    tq = np.clip((u - 0.84) / 0.16, 0, 1)
    hw = hw * (1 - tq**1.1)
    inside = (X >= gx) & (X <= tip)
    d = np.abs(Y - cy) - hw
    cov = smoothstep(0.6, -0.6, d) * inside
    edge = smoothstep(1.8, 0.0, np.abs(d)) * inside * (hw > 0.3)
    ridge = smoothstep(1.4, 0.0, np.abs(Y - cy)) * inside * (u < 0.985)
    groove = smoothstep(1.0, 0.0, np.abs(np.abs(Y - cy) - hw * 0.45)) * inside * smoothstep(0.02, 0.06, u) * smoothstep(0.8, 0.72, u)
    body = cov * (0.16 + 0.06 * W.sample_ptex(tex, np.clip((Y - cy) / 20, -1, 1), u * 0.8))
    # 符文：剑身上一串刻进去的短笔画（发暗）
    glyph = np.zeros_like(X)
    for k in range(9):
        x0 = 300 + k * 34 + rng.uniform(-4, 4)
        for _ in range(3):
            a = rng.uniform(-1.2, 1.2)
            L = rng.uniform(5, 10)
            xa, ya = x0 + rng.uniform(-6, 6), cy + rng.uniform(-7, 7)
            dd, _t = F.seg(X, Y, xa, ya, xa + L * math.cos(a), ya + L * math.sin(a))
            glyph = np.maximum(glyph, smoothstep(1.4, 0.4, dd))
    glyph *= inside
    glint = np.exp(-(((X - (tip - 10)) / 10) ** 2 + ((Y - cy) / 4) ** 2))
    halo = np.exp(-np.maximum(d, 0) ** 2 / 18.0) * inside * (1 - cov)
    # 如意剑格：中间一块，两头往剑尖那边卷
    gq = np.hypot((X - (gx - 8)) / 9.0, (Y - cy) / 50.0)
    guard = smoothstep(1.04, 0.92, gq)
    curls = np.zeros_like(X)
    for sgn in (-1, 1):
        cxk, cyk = gx + 2, cy + sgn * 50
        rr = np.hypot(X - cxk, Y - cyk)
        curls = np.maximum(curls, smoothstep(2.2, 0.4, np.abs(rr - 9.0)) * ((X - cxk) * 1.0 > -12))
        curls = np.maximum(curls, smoothstep(10.5, 8.0, rr) * 0.5)
    guard_rim = smoothstep(2.0, 0.0, np.abs(gq - 0.98)) * 0.6
    grip = smoothstep(0.6, -0.6, np.abs(Y - cy) - 8.5) * ((X > 120) & (X < gx - 16))
    wrap = 0.55 + 0.45 * (np.sin((X - 120) * 0.62 + (Y - cy) * 0.5) > 0)
    pommel_r = np.hypot(X - 104, Y - cy)
    pommel = smoothstep(2.4, 0.3, np.abs(pommel_r - 14.0)) + 0.4 * smoothstep(15, 12, pommel_r)
    tassel = np.zeros_like(X)
    for k, (dy0, bend) in enumerate(((-3.0, 14.0), (4.0, 22.0))):
        pts = V.bezier([(90, cy + dy0), (62, cy + dy0 + bend * 0.4), (34, cy + dy0 + bend), (8, cy + dy0 + bend * 0.7)], 60)
        tassel = np.maximum(tassel, V.brush_stroke(X, Y, pts, np.linspace(3.5, 0.8, 60), np.random.default_rng(13902 + k), dry=0.6, ss=ss)[0])
    lum = F.soft_union(body * (1 - 0.6 * glyph), 0.7 * edge, 0.95 * ridge * (1 - 0.7 * glyph), 0.45 * groove, 0.95 * glint, 0.12 * halo,
                       0.7 * guard, 0.85 * curls, guard_rim, 0.4 * grip * wrap, 0.75 * pommel, 0.4 * tassel)
    return [to_white(lum, 13910, ss=ss)]


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


def make_kun_shadow() -> tuple[list[Image.Image], list[Image.Image]]:
    """鲲影：俯视的一条大鱼，头朝 +X，在冰海底下游过去。钝圆的头、纺锤形的身子、一对翅膀一样往后掠的大胸鳍（鲲化为鹏），
    小腹鳍，叉开的大尾。焦墨、普通混合（身子最浓约 0.97——合成在线性光里，0.9 才看着压得住），边是水下的虚边；背脊一道深的，
    身上鳞纹淡淡几排，水面的光纹（焦散）从身上淡出一张网。鳍有骨条：鳍条浓、鳍条之间的膜薄（约 0.4，透得出底下的水）。
    发光层：影子边上一圈冰光（冰海的光从鲲身边漏上来），把影子从亮水里托出来。代码放大约 2 倍。"""
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
    fins, fin_rays = [], []
    for sgn in (-1, 1):
        # 胸鳍像一对往后掠的翅膀：根在身子里（960–1200），前缘鼓出去，梢在 (690, ±242)；七根鳍条从根散到边上，
        # 鳍条之间的膜薄（淡），边上一道道扇贝似的缺口落在两根鳍条之间
        lead = V.bezier([(1200, cy + sgn * 110), (1130, cy + sgn * 222), (930, cy + sgn * 238), (700, cy + sgn * 228)], 70)
        tr = V.bezier([(700, cy + sgn * 228), (790, cy + sgn * 192), (880, cy + sgn * 156), (960, cy + sgn * 112)], 70)
        tt = np.linspace(0, 1, len(tr))
        scal = np.abs(np.sin(tt * math.pi * 4)) * 16 * (1 - tt * 0.4)
        tr = tr + np.stack([-scal * 0.45, -sgn * scal], -1)
        fins.append(np.concatenate([lead, tr]))
        root = np.array([1165.0, cy + sgn * 112])
        margin = np.concatenate([lead[28:], tr[:-8]])
        for q in np.linspace(0.0, 1.0, 7):
            end = margin[int(q * (len(margin) - 1))]
            fin_rays.append(np.stack([root + (end - root) * f + np.array([0, sgn * 10 * math.sin(math.pi * f)]) for f in np.linspace(0, 1, 12)]))
        pel_l = V.bezier([(680, cy + sgn * 96), (630, cy + sgn * 158), (570, cy + sgn * 176), (520, cy + sgn * 172)], 30)
        pel_t = V.bezier([(520, cy + sgn * 172), (565, cy + sgn * 144), (605, cy + sgn * 116), (630, cy + sgn * 92)], 30)
        fins.append(np.concatenate([pel_l, pel_t]))
        proot = np.array([650.0, cy + sgn * 98])
        for end in (pel_l[18], pel_l[-1], pel_t[10]):
            fin_rays.append(np.stack([proot + (end - proot) * f for f in np.linspace(0, 1, 8)]))
    for end in ((150, cy - 196), (190, cy - 140), (226, cy - 70), (226, cy + 70), (190, cy + 140), (150, cy + 196)):  # 尾鳍的鳍条
        fin_rays.append(np.stack([np.array([336.0, cy]) + (np.array(end) - np.array([336.0, cy])) * f for f in np.linspace(0, 1, 10)]))
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
    body_a = mb * (0.93 + 0.05 * spine + 0.02 * smoothstep(1150, 1420, X) - 0.06 * across**4 + 0.02 * n1)
    # 鳞纹：几排往后开的弧（淡一点的线）
    scale_u = (X - 600) / 46.0
    scale_v = (Y - cy) / 40.0
    arcs = np.abs(np.sin(np.pi * (scale_u + 0.5 * np.abs(scale_v)))) < 0.12
    body_a -= 0.05 * arcs * mb * smoothstep(600, 760, X) * smoothstep(1250, 1100, X) * smoothstep(0.85, 0.3, across)
    # 鳍：鳍条浓、膜薄（半透明），根浓梢淡
    acc_r = Acc(X, Y)
    ray_m = np.zeros_like(X)
    for rp in fin_rays:
        sl = acc_r.window(*(rp.min(0) - 8), *(rp.max(0) + 8))
        dd, tq = F.polyline_dist(X[sl], Y[sl], rp)
        ray_m[sl] = np.maximum(ray_m[sl], smoothstep(3.4 - 1.6 * tq, 1.0 - 0.6 * tq, dd))
    fin_r = np.clip((1180 - X) / 480.0, 0, 1)
    ray_f = V.fft_blur(ray_m * m_fin, 0.8 * ss)
    ray_t = V.fft_blur(ray_m * m_tail, 0.8 * ss)
    fin_a = mf * (0.56 - 0.16 * fin_r) + ray_f * (0.92 - 0.25 * fin_r)
    tail_a = mt * (0.62 - 0.14 * np.clip((330 - X) / 200, 0, 1) + 0.03 * n1) + ray_t * 0.85
    a = 1 - (1 - np.clip(body_a, 0, 1)) * (1 - np.clip(fin_a, 0, 1)) * (1 - np.clip(tail_a, 0, 1))
    # 水面的焦散光纹（两层噪声的零线织成网）：从影子里减掉一点
    c1 = V.noise(np.random.default_rng(13403), X.shape, 16 * ss)
    c2 = V.noise(np.random.default_rng(13404), X.shape, 11 * ss)
    caustic = np.maximum(smoothstep(0.07, 0.0, np.abs(c1)), smoothstep(0.06, 0.0, np.abs(c2)))
    a *= 1 - 0.08 * caustic
    a *= 0.98 + 0.02 * n2
    a = np.clip(a, 0, 0.97)
    a *= smoothstep(0, 10, X) * smoothstep(w, w - 10, X) * smoothstep(0, 10, Y) * smoothstep(h, h - 10, Y)
    # 发光层：影子边上一圈冰光（冰海的光从鲲身边漏上来），鳍膜边上淡一点
    m_all = np.clip(m_body + m_tail + m_fin, 0, 1)
    soft = V.fft_blur(m_all, 9.0 * ss)
    rim = np.clip((soft - m_all) * 3.0, 0, 1) * (1 - m_all) + 0.25 * np.clip((m_all - V.fft_blur(m_all, 3.0 * ss)) * 2.0, 0, 1)
    rim *= 0.75 + 0.25 * smoothstep(-0.5, 0.8, n1)
    rim *= smoothstep(0, 24, X) * smoothstep(w, w - 24, X) * smoothstep(0, 24, Y) * smoothstep(h, h - 24, Y)
    emit = to_color(0.7 * rim, 0.55 + 0.4 * rim, 13411, ICE_LIGHT, ss=ss)
    return [to_paint(a[..., None] * JIAO, a, 13410, ss=ss)], [emit]


# ============================================================== 北冥潮：露出水面的背鳍


FIN_W, FIN_H = 256, 256
FIN_WATER = 200.0  # 水面线（画布 y），锚点在这条线的正中


def make_kun_fin() -> tuple[list[Image.Image], list[Image.Image]]:
    """鲲的背鳍露出水面（256²，往 +X 游，锚点在水面线正中）：高高的一片弯鳍，前缘厚、往后掠，后缘内凹；六根鳍条从根散到边上，
    鳍条之间的膜薄（半透明）。本体焦墨、普通混合，入水的地方淡进水里；发光层：前缘一道湿亮的冰光、整片一圈细冰边、
    根上一圈压扁的白浪和往前翻的浪花、几点水珠。八字浪痕由代码沿身后拖（现成 wave_trail / 笔画）。"""
    w, h, ss = FIN_W, FIN_H, 4
    X, Y = grid(w, h)
    rng = np.random.default_rng(13951)
    lead = V.bezier([(178, FIN_WATER + 4), (176, 124), (146, 62), (92, 36)], 60)
    trail_ = V.bezier([(92, 36), (120, 104), (100, 160), (80, FIN_WATER + 4)], 60)
    poly = np.concatenate([lead, trail_])
    m = mask_polys(w, h, [poly], ss)
    base_pts = np.linspace(86, 172, 6)
    margin = np.concatenate([lead[14:], trail_[:44]])
    acc_r = Acc(X, Y)
    rays = np.zeros_like(X)
    for k, bxp in enumerate(base_pts):
        end = margin[int((1 - k / 5) * (len(margin) - 1))]  # 后面的根连后缘、前面的根连前缘，不交叉
        st = np.array([bxp, FIN_WATER])
        pts = np.stack([st + (end - st) * f + np.array([-10 * math.sin(math.pi * f), 0]) for f in np.linspace(0, 1, 14)])
        sl = acc_r.window(*(pts.min(0) - 5), *(pts.max(0) + 5))
        dd, tq = F.polyline_dist(X[sl], Y[sl], pts)
        rays[sl] = np.maximum(rays[sl], smoothstep(2.2 - 1.0 * tq, 0.6 - 0.3 * tq, dd))
    rays *= m
    ld, lt = F.polyline_dist(X, Y, lead)
    lead_thick = smoothstep(4.5, 1.0, ld) * m  # 前缘厚
    water_fade = smoothstep(FIN_WATER + 2, FIN_WATER - 22, Y)
    a = np.clip((0.6 * m + 0.38 * rays + 0.3 * lead_thick) * water_fade, 0, 0.97)
    body = to_paint(a[..., None] * V.col("#121820"), a, 13952, ss=ss)
    # 发光层
    acc = Acc(X, Y)
    inner, outer = edge_band(m, 1.5 * ss)
    acc.add((slice(None), slice(None)), (0.5 * np.clip(inner * 1.6, 0, 1) + 0.3 * np.clip(outer * 1.4, 0, 1)) * water_fade, 0.8)
    acc.add((slice(None), slice(None)), 0.75 * smoothstep(2.6, 0.4, ld) * smoothstep(0.1, 0.4, lt) * water_fade, 1.0)  # 前缘湿亮
    acc.add((slice(None), slice(None)), 0.18 * rays * water_fade, 0.7)
    # 根上一圈压扁的白浪 + 往前翻的浪花
    q = np.hypot((X - 132) / 86.0, (Y - FIN_WATER) / 16.0)
    foam = smoothstep(0.16, 0.0, np.abs(q - 0.85)) * (0.55 + 0.45 * smoothstep(-0.2, 0.6, V.noise(np.random.default_rng(13953), X.shape, 3 * ss)))
    acc.add((slice(None), slice(None)), 0.7 * foam, 0.85)
    tex = W.ptex(rng, ns=16, nt=256, along=12.0, across=0.6)
    for k in range(14):  # 鳍前翻起的浪花：往前上方甩出去的水针
        ang = -math.pi * rng.uniform(0.08, 0.42)
        L = rng.uniform(22, 56)
        x0, y0 = 176 + rng.uniform(-6, 10), FIN_WATER - rng.uniform(0, 8)
        sl = acc.window(x0 - 4, y0 - L - 4, x0 + L + 4, y0 + 4)
        cv, uu = F.needle(X[sl], Y[sl], x0, y0, ang, L, rng.uniform(1.6, 3.2), taper=1.3)
        acc.add(sl, 0.7 * cv * dry(tex, 0.0, uu * 0.5 + k * 0.17, 0.12 + 0.4 * uu), 0.9)
    for k in range(26):
        x, y = 190 + rng.normal(0, 22), FIN_WATER - abs(rng.normal(0, 26))
        sl = acc.window(x - 5, y - 5, x + 5, y + 5)
        acc.add(sl, 0.85 * F.dot(X[sl], Y[sl], x, y, rng.uniform(1.0, 2.4)), 0.95)
    emit = F.frame_color(acc.a, acc.heat(), 13954, ICE_LIGHT)
    return [body], [emit]


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
    wing_near = wing((0.77, -0.05), [(0.7, -0.27), (0.55, -0.41)], (0.33, -0.45), [(0.42, -0.33), (0.52, -0.2)], (0.6, -0.06), 5, 0.04)
    wing_far = wing((0.75, 0.06), [(0.69, 0.2), (0.58, 0.28)], (0.45, 0.3), [(0.52, 0.22), (0.57, 0.14)], (0.61, 0.08), 4, 0.03)
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
        fill = 0.16 * m_body + 0.05 * m_fin + 0.06 * m_small  # 鳍膜薄，透
        inner_f, _ = edge_band(np.clip(m_fin + m_small, 0, 1), 1.2 * ss)
        rim = 0.95 * inner_b + 0.45 * inner * (1 - m_body) + 0.25 * inner_f
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
        for fi, (root, tips) in enumerate((((0.74, -0.06), [(0.33 + 0.058 * k, -0.445 + 0.078 * k) for k in range(7)]),
                                           ((0.72, 0.07), [(0.45 + 0.035 * k, 0.29 - 0.04 * k) for k in range(6)]),
                                           ((0.1, 0.0), [(-0.06, 0.17), (-0.03, 0.1), (-0.03, -0.1), (-0.06, -0.16)]))):
            for tip in tips:
                seg_pts = bend([(root[0] + (tip[0] - root[0]) * q, root[1] + (tip[1] - root[1]) * q) for q in np.linspace(0, 1, 16)], spine, LEAP_L)
                sl = acc.window(*(seg_pts.min(0) - 5), *(seg_pts.max(0) + 5))
                d, tq = F.polyline_dist(X[sl], Y[sl], seg_pts)
                ray_l[sl] = np.maximum(ray_l[sl], smoothstep(2.4 - 1.0 * tq, 0.6, d) * (1 - 0.35 * tq))
        ray_l *= np.clip(m_fin + m_small, 0, 1)
        lum = F.soft_union(fill, rim, glow_out, 0.42 * streak * m_body, eye, gill_l * m_body, 0.72 * ray_l)
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


# ============================================================== 燃灯：莲灯开合


LOTUS_W, LOTUS_H = 256, 320
LOTUS_BASE = (128.0, 272.0)  # 莲座中心（画布像素）；锚点是底边中点
LOTUS_EL = math.radians(24)  # 稍微从上往下看（同游戏的 3/4 视角）
# 每层：(瓣数, 根半径, 瓣长, 瓣宽, 起始方位角)；每帧三层的张开角（离竖直多少度）
LOTUS_LAYERS = [(8, 16.0, 102.0, 40.0, 0.0), (8, 12.0, 86.0, 34.0, math.pi / 8), (6, 8.0, 68.0, 28.0, 0.0)]
LOTUS_TILT = [(10, 7, 4), (12, 8, 5), (36, 10, 6), (60, 28, 7), (72, 52, 20), (78, 63, 36), (81, 67, 47), (83, 69, 52)]
LOTUS_SIZE = [0.72, 0.86, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0]  # 升起时先小一点
LOTUS_FLAME = [0.0, 0.0, 0.25, 0.45, 0.65, 0.85, 1.0, 1.05]
LOTUS_GLOW = [0.55, 0.65, 0.75, 0.85, 0.92, 1.0, 1.0, 1.0]
LAMP_GOLD = [(0.0, "#D9963F"), (0.4, "#F2C46A"), (0.75, "#FFE7A8"), (1.0, "#FFFBF0")]


def lotus_petal(phi, tilt, r0, L, Wd, el, cup=0.18, n=40):
    """一片花瓣的轮廓（画布坐标，相对莲座中心）：在方位角 phi、离竖直 tilt 的平面里，杏仁形，瓣尖往里收一点（cup）。
    返回 (多边形, 瓣面朝向观察者的程度 −1..1, 中脉折线, 深度)。"""
    u = np.linspace(0, 1, n)
    half = 0.5 * Wd * np.sin(np.pi * u**0.8) ** 0.9 * (1 - 0.15 * u)
    # 瓣在自己的平面里：沿 d（根 → 尖）走，瓣尖往里卷（tilt 越大卷得越明显）
    t_eff = tilt - cup * u**2 * (0.4 + tilt)
    dx = np.sin(t_eff) * math.cos(phi)
    dy = np.sin(t_eff) * math.sin(phi)
    dz = np.cos(t_eff)
    step = L / (n - 1)
    px = r0 * math.cos(phi) + np.cumsum(dx) * step
    py = r0 * math.sin(phi) + np.cumsum(dy) * step
    pz = np.cumsum(dz) * step
    tx, ty = -math.sin(phi), math.cos(phi)  # 瓣宽的方向（切向）
    left = np.stack([px + half * tx, py + half * ty, pz], -1)
    right = np.stack([px - half * tx, py - half * ty, pz], -1)
    pts3 = np.concatenate([left, right[::-1]])

    def proj(p):
        x, y, z = p[..., 0], p[..., 1], p[..., 2]
        return np.stack([LOTUS_BASE[0] + x, LOTUS_BASE[1] - (z * math.cos(el) + y * math.sin(el))], -1)

    face = -math.sin(phi)  # y 往后为正；朝前（y < 0）的瓣面朝观察者
    mid = proj(np.stack([px, py, pz], -1))
    return proj(pts3), face, mid, float(np.mean(py))


LOTUS_PAPER = [(0.0, "#FBF5E6"), (0.55, "#F4E4C8"), (1.0, "#EBB8A6")]  # 瓣根 → 瓣尖（纸色到一点藕粉）
LOTUS_LINE = V.col("#5A4632")
LOTUS_SEAT = V.col("#B8955C")


def make_ult_lotus() -> tuple[list[Image.Image], list[Image.Image]]:
    """燃灯的莲灯：三层莲瓣（外八、中八、内六）围着一盏灯焰，从合着的花苞一层层打开。
    本体普通混合：纸色的瓣（瓣根暖白、瓣尖一点藕粉），焦褐的细轮廓、一道淡中脉，后面的瓣被前面的压住，层次靠轮廓分；
    发光层叠加、自带灯金色：看得见的瓣边描金、瓣根被灯焰照透的一层暖光、灯焰（芯白）、全开时灯焰放的几道短光。
    0–1 花苞升起（里头透光）；2–3 外层开；4–5 中层开、灯焰露出来；6–7 全开，末帧可以留着。锚点在底边中点（莲座底下）。"""
    w, h, ss = LOTUS_W, LOTUS_H, 4
    X, Y = grid(w, h)
    rng = np.random.default_rng(13601)
    tex = W.ptex(rng, ns=16, nt=512, along=20.0, across=0.6)
    bodies, emits = [], []
    for i in range(8):
        k = LOTUS_SIZE[i]
        paint = Paint(X, Y)
        R = np.zeros_like(X)  # 看得见的瓣边（描金）：和本体一样被前面的瓣盖住
        acc = Acc(X, Y)
        petals = []
        for li, (n, r0, L, Wd, a0) in enumerate(LOTUS_LAYERS):
            tilt = math.radians(LOTUS_TILT[i][li])
            for j in range(n):
                phi = a0 + 2 * math.pi * j / n + 0.04 * li
                poly, face, mid, depth = lotus_petal(phi, tilt, r0 * k, L * k, Wd * k, LOTUS_EL)
                petals.append((depth, li, poly, face, mid))
        # 莲座先画（在最下面）：一圈往下翻的萼片
        bx, by = LOTUS_BASE
        fl_ = 0.42
        rr = np.hypot(X - bx, (Y - by) / fl_)
        th = np.arctan2((Y - by) / fl_, X - bx)
        scallop = 30 * k * (1 + 0.12 * np.abs(np.sin(th * 6)))
        seat = smoothstep(scallop + 1.0, scallop - 1.0, rr) * (Y > by - 6 * k)
        seat_line = smoothstep(1.6, 0.3, np.abs(rr - scallop)) * (Y > by - 6 * k)
        full = (slice(None), slice(None))
        paint.over(full, LOTUS_SEAT, seat * 0.95)
        paint.over(full, LOTUS_LINE, seat_line * 0.8)
        R = np.maximum(R, seat_line * 0.6)
        for depth, li, poly, face, mid in sorted(petals, key=lambda t: -t[0]):
            lo, hi = poly.min(0) - 3, poly.max(0) + 3
            sl = paint.window(lo[0], lo[1], hi[0], hi[1])
            cov, d = F.poly_cover(X[sl], Y[sl], poly, aa=0.5)
            md, mt = F.polyline_dist(X[sl], Y[sl], mid)
            col = F.lerp_col(np.clip(mt * 0.9 + 0.1 * (li == 2), 0, 1), LOTUS_PAPER)
            shade = 1.0 - 0.1 * (1 - (face + 1) / 2) - 0.08 * (1 - mt) * (li < 2)  # 朝里的瓣、瓣根略暗
            col = col * shade[..., None]
            vein = smoothstep(1.0, 0.2, md) * cov * (1 - 0.6 * mt)
            col = col * (1 - 0.18 * vein[..., None])
            line = smoothstep(1.4, 0.3, np.abs(d)) * (d < 0.7)
            paint.over(sl, col, cov * 0.97)
            paint.over(sl, LOTUS_LINE, line * 0.85)
            rimk = smoothstep(1.2, 0.2, np.abs(d + 2.3)) * (d < -0.9)  # 描金在墨线里侧，墨线还在
            R[sl] = rimk + R[sl] * (1 - cov)
            # 瓣根被灯焰照透（只在看得见的地方）
            glow_in = cov * (1 - mt) ** 1.5 * LOTUS_GLOW[i] * (0.25 + 0.2 * (li / 2))
            acc.a[sl] = acc.a[sl] * (1 - cov)  # 前面的瓣挡住后面的透光
            acc.add(sl, glow_in, 0.6)
        bodies.append(paint.image(13630 + i))
        acc.add(full, 0.62 * R, 0.7)
        # 灯焰：莲心一朵泪滴形的火，芯白
        fl = LOTUS_FLAME[i]
        if fl > 0:
            fx, fy = bx, by - 34 * k - 22 * fl
            fh, fw = 46 * fl + 8, 13 * fl + 3
            q = np.hypot((X - fx) / fw, np.where(Y < fy, (Y - fy) / fh, (Y - fy) / (fw * 1.1)))
            acc.add(full, 0.7 * smoothstep(1.0, 0.55, q), 0.85)
            acc.add(full, smoothstep(0.55, 0.1, q), 1.0)
            acc.add(full, 0.18 * np.exp(-((np.hypot(X - fx, Y - fy) / (30 * fl + 8)) ** 2)) * fl, 0.9)
            if i >= 6:
                for kk in range(16):
                    ang = -math.pi / 2 + (kk - 7.5) / 7.5 * 1.3
                    L0 = (40 + 18 * ((kk * 5) % 3)) * (1 if i == 6 else 1.15)
                    x0, y0 = fx + 16 * math.cos(ang), fy + 16 * math.sin(ang)
                    sl = acc.window(min(x0, x0 + L0 * math.cos(ang)) - 4, min(y0, y0 + L0 * math.sin(ang)) - 4,
                                    max(x0, x0 + L0 * math.cos(ang)) + 4, max(y0, y0 + L0 * math.sin(ang)) + 4)
                    cv, uu = F.needle(X[sl], Y[sl], x0, y0, ang, L0, 1.6, taper=1.0)
                    acc.add(sl, 0.34 * cv * dry(tex, 0.0, uu * 0.4 + kk * 0.1, 0.1 + 0.5 * uu), 0.9)
        else:  # 合着的花苞里头透光
            gq = np.hypot((X - bx) / 20, (Y - (by - 40 * k)) / 34)
            acc.add(full, 0.4 * np.exp(-gq**2) * LOTUS_GLOW[i], 0.9)
        emits.append(F.frame_color(acc.a, acc.heat(), 13610 + i, LAMP_GOLD))
    return bodies, emits


# ============================================================== 燃灯：放射佛光


RAYS_SIZE = 2048


def angular_profile(rng, n_rays, width_deg, n=32768, jitter=1.0, amp=(0.5, 1.0)):
    """一圈放射光的角向分布：n_rays 道光，每道一个高斯，宽度在 width_deg 附近抖。返回长 n 的数组（周期）。"""
    th = np.linspace(0, 2 * math.pi, n, endpoint=False)
    prof = np.zeros(n)
    centers = (np.arange(n_rays) + rng.uniform(-0.45, 0.45, n_rays) * jitter) * 2 * math.pi / n_rays
    for c, wdeg, a in zip(centers, width_deg * rng.uniform(0.5, 1.6, n_rays), rng.uniform(*amp, n_rays)):
        d = np.angle(np.exp(1j * (th - c)))
        prof = np.maximum(prof, a * np.exp(-((d / math.radians(wdeg)) ** 2)))
    return prof


def make_ult_rays() -> list[Image.Image]:
    """放射佛光（2048²，锚点居中，代码转、缩放）：千道细光从中心射出去，长短、粗细、明暗都不一样，几道宽的柔光束打底，
    细光上带一点飞白，越往外越淡；中心只有一小点白热和一道细光轮（灯焰在莲灯里，不要在这里画一大团白）。透：光是一丝丝的，光和光之间是空的。叠加、自带灯金色。
    两张叠着反向慢转、一张放大一点，看着就是“千条”。"""
    size = RAYS_SIZE
    c = size / 2
    rng = np.random.default_rng(13701)
    yy, xx = np.mgrid[0:size, 0:size].astype(np.float32) + 0.5
    dx, dy = xx - c, yy - c
    r = np.hypot(dx, dy) / c  # 0..1（边上）
    th = np.mod(np.arctan2(dy, dx), 2 * math.pi)
    n = 32768
    idx = (th / (2 * math.pi) * n).astype(np.int32) % n

    def sample(prof):
        return prof[idx]

    lum = np.zeros((size, size), np.float32)
    heat = np.zeros((size, size), np.float32)

    def add(f, h):
        nonlocal lum, heat
        f = np.clip(f, 0, 1).astype(np.float32)
        lum = 1 - (1 - lum) * (1 - f)
        heat += f * h

    wsum = np.zeros((size, size), np.float32)
    # 宽的柔光束（24 道），长
    p = angular_profile(rng, 24, 3.2, n, amp=(0.4, 0.8))
    f = sample(p) * smoothstep(0.98, 0.25, r) * smoothstep(0.0, 0.06, r)
    add(0.45 * f, 0.6)
    wsum += 0.45 * f
    # 中等的光（120 道），分三档长短
    for k, (L, nr) in enumerate(((0.95, 40), (0.75, 40), (0.55, 40))):
        p = angular_profile(rng, nr, 0.55, n, amp=(0.5, 1.0))
        f = sample(p) * smoothstep(L, L * 0.45, r) * smoothstep(0.02, 0.07, r)
        add(0.6 * f, 0.75)
        wsum += 0.6 * f
    # 细光（约 900 道），分六档长短，带飞白
    tex = W.ptex(rng, ns=64, nt=2048, along=60.0, across=0.5)
    for k in range(6):
        L = 0.98 - 0.11 * k
        p = angular_profile(rng, 150, 0.12, n, amp=(0.35, 1.0))
        fly = W.sample_ptex(tex, np.clip((th / (2 * math.pi)) * 2 - 1, -1, 1), r * 1.6 + k * 0.17)
        f = sample(p) * smoothstep(L, L * 0.35, r) * smoothstep(0.03, 0.08, r) * smoothstep(0.25 + 0.3 * r, 0.6 + 0.3 * r, fly)
        add(0.75 * f, 0.85)
        wsum += 0.75 * f
    # 中心：白热的一团 + 一圈光轮
    core = np.exp(-((r / 0.018) ** 2))  # 中心只留一小点白热（灯焰本身在莲灯里）
    add(core, 1.0)
    wsum += core
    soft = np.exp(-((r / 0.035) ** 2)) * 0.25
    add(soft, 0.95)
    wsum += soft
    ring = np.exp(-(((r - 0.1) / 0.004) ** 2)) * 0.3
    add(ring, 1.0)
    wsum += ring
    h = heat / np.maximum(wsum, 1e-6)
    h = np.clip(h * (1 - 0.35 * r), 0, 1)
    a = PEAK * np.tanh(1.25 * np.clip(lum, 0, 1)) / math.tanh(1.25)
    a *= smoothstep(1.0, 0.9, r)
    a8 = V.dither_alpha(a, np.random.default_rng(13702))
    a8[a < 0.004] = 0
    rgb = F.lerp_col(h, LAMP_GOLD)
    return [V.to_rgba8(rgb, None, a8)]


# ============================================================== 燃灯：头光


HALO_SIZE = 512


def make_ult_halo() -> list[Image.Image]:
    """头光（512²，锚点居中，放在莲灯 / 主角头后）：佛像背后的圆光，全是细的光线，中间是空的、透的。
    里面一层淡淡的圆光；三道细圆线，两线之间一圈细的放射光、一圈小珠；最外一圈火焰纹（二十四朵 S 形往一边卷的火舌，只描边、
    里面极淡）。叠加、自带灯金色。"""
    size, ss = HALO_SIZE, 2
    X, Y = V.grid(size, size, ss)
    c = size / 2
    dx, dy = X - c, Y - c
    r = np.hypot(dx, dy)
    th = np.arctan2(dy, dx)
    rng = np.random.default_rng(13801)
    tex = W.ptex(rng, ns=24, nt=1024, along=24.0, across=0.6)
    parts = []
    parts.append((0.035 * np.exp(-((r / 100.0) ** 2)) + 0.05 * np.exp(-(((r - 102) / 18.0) ** 2)), 0.8))  # 淡淡的圆光，边上略亮
    for R0, a0 in ((108.0, 0.7), (150.0, 0.55), (178.0, 0.75)):
        parts.append((a0 * smoothstep(1.3, 0.0, np.abs(r - R0)), 1.0))
    rays = W.sample_ptex(tex, np.clip(np.sin(th * 3), -1, 1) * 0, th / (2 * math.pi) * 6 + r / 4000.0)
    fine = 0.5 + 0.5 * np.cos(th * 180 + 0.6 * np.sin(th * 7))
    band = smoothstep(110.0, 116.0, r) * smoothstep(148.0, 142.0, r)
    parts.append((0.22 * band * smoothstep(0.7, 0.98, fine) * (0.6 + 0.4 * rays), 0.9))  # 细放射光
    dots = 0.5 + 0.5 * np.cos(th * 48)
    parts.append((0.65 * smoothstep(0.93, 1.0, dots) * smoothstep(2.6, 0.6, np.abs(r - 164.0)), 1.0))  # 一圈小珠
    # 火焰纹：根在外圆线上，S 形往一边卷，只描边
    n = 24
    seg = (th / (2 * math.pi) * n) % 1.0
    local = (seg - 0.5) * 2
    odd = np.floor(th / (2 * math.pi) * n) % 2  # 一长一短
    rr = (r - 180.0) / (64.0 - 18.0 * odd)
    rc = np.clip(rr, 0, 1)
    sway = 0.2 * np.sin(rc * math.pi) + 0.38 * rc**2.2  # 轻轻的 S 形，尖往一边甩
    width = 0.92 * (1 - rc) ** 1.1 * (0.5 + 0.5 * np.sin(np.clip(rc * 2.6, 0, math.pi / 2)))
    q = local - sway
    inside = (rr > 0) & (rr < 1)
    tongue = smoothstep(width + 0.06, width - 0.06, np.abs(q)) * inside
    edge = smoothstep(0.1, 0.0, np.abs(np.abs(q) - width)) * inside * (width > 0.02)
    mid_line = smoothstep(0.06, 0.0, np.abs(q)) * inside * smoothstep(0.85, 0.2, rc)
    brk = dry(tex, np.clip(local, -1, 1), rc * 0.5 + np.floor(th / (2 * math.pi) * n) * 0.07, 0.1 * smoothstep(0.5, 1.0, rc))
    parts.append((0.025 * tongue, 0.6))
    parts.append((0.75 * edge * brk * (1 - 0.45 * rc), 0.75))
    parts.append((0.3 * mid_line, 0.7))
    a, heat = F.union_heat(parts)
    a *= smoothstep(c - 2, c - 10, r)
    return [to_color(a, heat, 13810, LAMP_GOLD, ss=ss)]


# ============================================================== 九尾登场：月亮


MOON_SIZE = 1024
MOON_R = 360.0  # 月面半径（像素）


def make_fox_moon() -> list[Image.Image]:
    """月亮（1024²，锚点居中，贴在镜头上方）：一轮满月，月面是淡墨晕出来的几块月海（边上略深、洇开），边缘一圈清亮，
    往里稍暗（临边昏暗），外面一圈柔光和一道淡淡的月晕。白色可染（建议冷白 #DCE6FF；血月染红），叠加。"""
    size, ss = MOON_SIZE, 2
    X, Y = V.grid(size, size, ss)
    c = size / 2
    r = np.hypot(X - c, Y - c)
    q = r / MOON_R
    disc = smoothstep(1.0 + 1.2 / MOON_R, 1.0 - 1.2 / MOON_R, q)
    n1 = V.noise(np.random.default_rng(14001), X.shape, 34 * ss)
    n2 = V.noise(np.random.default_rng(14002), X.shape, 10 * ss)
    n3 = V.noise(np.random.default_rng(14003), X.shape, 3 * ss)
    # 月海：几块淡墨（阈值以下），边上洇一道略深的水痕
    sea = smoothstep(0.25, 0.75, n1 + 0.25 * n2 - 0.15)
    seam = smoothstep(0.12, 0.0, np.abs(n1 + 0.25 * n2 - 0.4)) * 0.5
    limb = 1.0 - 0.22 * q**3  # 临边昏暗
    bright = limb * (1.0 - 0.36 * sea - 0.12 * seam) * (0.96 + 0.04 * n3)
    rim = smoothstep(0.02, 0.0, np.abs(q - 0.985)) * 0.25
    face = disc * np.clip(bright + rim, 0, 1)
    glow = np.exp(-np.maximum(q - 1.0, 0) / 0.06) * (1 - disc) * 0.45 + np.exp(-np.maximum(q - 1.0, 0) / 0.22) * (1 - disc) * 0.16
    halo = np.exp(-(((q - 1.28) / 0.07) ** 2)) * 0.06 * (0.7 + 0.3 * smoothstep(-1, 1, n2))
    a = np.clip(face + glow + halo, 0, 1)
    a *= smoothstep(c - 2, c - 24, r)
    return [to_white(a, 14010, ss=ss)]


# ============================================================== 九尾登场：身子剪影


FOX_W = 512
FOX_TAIL_ROOT = (204.0, 440.0)  # 尾根（脊梁末端，代码从这里旋开九条尾巴）
FOX_EYE = (394.0, 128.0)
FOX_MARK = (378.0, 112.0)
FOX_INK = V.col("#0E1318")
FOX_RIM = V.col(FOX_CYAN)


def sd_round_cone(X, Y, a, b, ra, rb):
    """两头半径不同的圆锥（胶囊）的有向距离（近似，够画剪影）。"""
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    t = np.clip(((X - ax) * dx + (Y - ay) * dy) / L2, 0, 1)
    r = ra + (rb - ra) * t
    return np.hypot(X - ax - t * dx, Y - ay - t * dy) - r


def sd_ellipse(X, Y, c, rx, ry, rot=0.0):
    ca, sa = math.cos(rot), math.sin(rot)
    u = ((X - c[0]) * ca + (Y - c[1]) * sa) / rx
    v = (-(X - c[0]) * sa + (Y - c[1]) * ca) / ry
    return (np.hypot(u, v) - 1.0) * min(rx, ry)


def smin(a, b, k):
    h = np.clip(0.5 + 0.5 * (b - a) / k, 0, 1)
    return b * (1 - h) + a * h - k * h * (1 - h)


def fur(d, X, Y, c, th0, th1, n, amp, lean=0.0, seed=0, jitter=0.35, sharp_range=(2.2, 3.6)):
    """在以 c 为中心、角度 th0..th1 的那一段边上加一簇簇尖毛：沿角度方向一串尖峰，把距离场往外推。
    每一簇的长短、粗细、间距都随机抖一点（jitter），不排得太齐。"""
    rng = np.random.default_rng(15000 + seed)
    th = np.arctan2(Y - c[1], X - c[0])
    span = th1 - th0
    q = np.mod(th - th0, 2 * math.pi) / span
    inside = (q >= 0) & (q <= 1)
    # 不均匀的间距：把 q 按一条随机抖过的单调曲线重新映射
    knots = np.cumsum(rng.uniform(1 - jitter, 1 + jitter, n + 1))
    knots = np.concatenate([[0], knots]) / knots[-1]
    qq = np.interp(np.clip(q, 0, 1), knots, np.linspace(0, 1, n + 2)) * (n + 1)
    idx = np.clip(np.floor(qq).astype(int), 0, n + 1)
    amps = rng.uniform(0.55, 1.3, n + 2)[idx]
    sharp = rng.uniform(*sharp_range, n + 2)[idx]
    ph = np.mod(qq + lean * np.clip(-d / 20.0, -1, 1), 1.0)
    spike = np.clip(1 - np.abs(ph - 0.5) * 2, 0, 1) ** sharp
    env = np.sin(np.pi * np.clip(q, 0, 1)) ** 0.6
    return d - amp * amps * spike * env * inside * smoothstep(34, 0, np.abs(d))


def fox_sdf(X, Y):
    """九尾的身子（没有尾巴），朝 +X 坐着、头抬起来望月：比例照 boss 图集的九尾——大耳、口吻短一点、颈粗、胸前一大圈蓬的毛领，
    身子圆，前腿收在胸下，后胯圆圆地着地。用几块圆滑的形体捏出来，再加毛领、颈毛、腮毛、后胯的毛（长短不齐）。"""
    haunch = sd_ellipse(X, Y, (238, 392), 84, 80, 0.15)
    back = sd_round_cone(X, Y, (240, 378), (330, 268), 74, 62)
    chest = sd_ellipse(X, Y, (346, 292), 64, 88, 0.1)
    neck = sd_round_cone(X, Y, (336, 252), (364, 170), 54, 40)
    head = sd_ellipse(X, Y, (376, 138), 42, 35, -0.18)
    snout = sd_round_cone(X, Y, (404, 138), (444, 150), 21, 5.5)
    jaw = sd_round_cone(X, Y, (398, 154), (434, 158), 14, 4.5)
    ear1 = sd_round_cone(X, Y, (378, 120), (378, 30), 25, 2.0)
    ear2 = sd_round_cone(X, Y, (348, 122), (332, 38), 23, 2.0)
    leg1 = sd_round_cone(X, Y, (346, 372), (350, 458), 19, 12)
    leg2 = sd_round_cone(X, Y, (368, 372), (376, 458), 17, 12)
    paw1 = sd_ellipse(X, Y, (360, 464), 21, 8)
    paw2 = sd_ellipse(X, Y, (386, 464), 20, 8)
    hpaw = sd_ellipse(X, Y, (306, 462), 48, 12)
    tuck = sd_ellipse(X, Y, (316, 452), 30, 14)  # 后爪收在身下，和前爪挨着
    root = sd_round_cone(X, Y, (226, 430), (196, 448), 36, 22)
    d = smin(haunch, back, 22)
    d = smin(d, chest, 20)
    d = smin(d, neck, 18)
    d = smin(d, head, 12)
    d = smin(d, snout, 8)
    d = smin(d, jaw, 6)
    d = smin(d, ear1, 6)
    d = smin(d, ear2, 6)
    d = smin(d, root, 12)
    d = smin(d, hpaw, 10)
    d = smin(d, tuck, 14)
    legs = np.minimum(smin(leg1, paw1, 6), smin(leg2, paw2, 6))
    d = smin(d, legs, 8)
    # 毛：胸前一大圈毛领（尖往下）、颈后的鬃、腮后、后胯后面
    d = fur(d, X, Y, (340, 270), -0.9, 1.15, 6, 36, lean=0.7, seed=1, sharp_range=(1.3, 2.0))  # 毛领：几大簇，宽、尖往下卷
    d = fur(d, X, Y, (350, 214), 3.2, 4.5, 4, 20, lean=0.5, seed=2, sharp_range=(1.4, 2.2))
    d = fur(d, X, Y, (376, 142), 1.45, 2.75, 3, 20, seed=3, sharp_range=(1.4, 2.2))
    d = fur(d, X, Y, (238, 392), 2.3, 3.5, 5, 10, seed=4)
    return d


def silhouette_layers(m, rim_px, ss, seed, glow_px=6.0, extra_emit=None, tint_zone=None):
    """剪影 → (本体 RGBA, 发光层 RGBA)：本体焦墨（略带青黑）、边上一道青线；发光层是青边往外的一圈光。
    tint_zone = (遮罩, 颜色)：这一块的墨往这个颜色过渡（尾尖透青）。"""
    inner, outer = edge_band(m, rim_px * ss)
    edge = np.clip(inner * 1.6, 0, 1)
    ink = FOX_INK
    if tint_zone is not None:
        ink = FOX_INK * (1 - tint_zone[0][..., None]) + tint_zone[1] * tint_zone[0][..., None]
    rgb = ink * (1 - edge[..., None]) + FOX_RIM * edge[..., None]
    a = np.clip(m * 0.98, 0, 1)
    body = to_paint(rgb * a[..., None], a, seed, ss=ss)
    g_in, g_out = edge_band(m, glow_px * ss)
    lum = 0.85 * edge + 0.5 * np.clip(g_out * 1.4, 0, 1) + 0.2 * np.clip(g_in, 0, 1)
    heat = 0.5 + 0.5 * edge
    if extra_emit is not None:
        lum = F.soft_union(lum, extra_emit[0])
        heat = np.maximum(heat, extra_emit[1])
    emit = to_color(lum, heat, seed + 1, FOXFIRE, ss=ss)
    return body, emit


FOXFIRE = [(0.0, "#3FB59A"), (0.5, FOX_CYAN), (0.85, "#D8FFF4"), (1.0, "#FFFFFF")]


def make_fox_body() -> tuple[list[Image.Image], list[Image.Image]]:
    """九尾的身子剪影（512²，锚点在地面线正中）：朝 +X 坐着、头抬起来望月；比例照 boss 图集的九尾：大耳、口吻不长、颈粗，
    胸前一大圈蓬的毛领、颈后一道鬃，身子圆，前腿收在胸下。本体焦墨（带一点青黑）、一道青边，普通混合；发光层：青边往外一圈光、丹凤眼一道青、额心一点青火。
    月亮前面的剪影要画在月亮之上（天上的层，同月亮一样在暗层之上）。尾根在 (204, 440)，九条尾巴（fox_tail）从这里旋开成扇，扇在身后。"""
    size, ss = FOX_W, 4
    X, Y = grid(size, size)
    d = fox_sdf(X, Y)
    m = smoothstep(0.5, -0.5, d)
    ex, ey = FOX_EYE
    eye = F.almond_field(X, Y, (ex - 8, ey + 2), (ex + 9, ey - 4), 3.6)[0]  # 丹凤眼往上挑
    mk = F.dot(X, Y, FOX_MARK[0], FOX_MARK[1], 2.6) + 0.6 * F.almond_field(X, Y, (FOX_MARK[0], FOX_MARK[1] + 3), (FOX_MARK[0] - 2, FOX_MARK[1] - 9), 3.0)[0]
    extra = (np.clip(eye + mk, 0, 1), np.clip(eye + mk, 0, 1))
    body, emit = silhouette_layers(m, 1.4, ss, 14110, glow_px=7.0, extra_emit=extra)
    return [body], [emit]


# ============================================================== 九尾登场：一条尾巴


TAIL_W, TAIL_H = 128, 512
TAIL_ROOT = (64.0, 500.0)


def make_fox_tail() -> tuple[list[Image.Image], list[Image.Image]]:
    """九尾的一条尾巴（128×512，锚点在尾根，尾巴朝上）：根细、中段蓬、尖收，S 形，两边一簇簇往尖上歪的尖毛；
    尖上一截青火（发光层，往上窜的火舌）。本体焦墨 + 青边，普通混合；代码从尾根旋开九条（中间长、两边短一点，前后两层错开）。"""
    w, h, ss = TAIL_W, TAIL_H, 4
    X, Y = grid(w, h)
    rng = np.random.default_rng(14201)
    sp = V.bezier([TAIL_ROOT, (28, 396), (104, 240), (62, 92)], 90)  # 尖留出 90 像素给青火
    t = np.linspace(0, 1, len(sp))
    rad = 5 + 50 * np.sin(np.pi * np.clip(t, 0, 1) ** 1.36) ** 0.8  # 根细、六成处最蓬、尖收成笔尖
    rad[-12:] = np.maximum(rad[-12:], 0) * np.linspace(1, 0.4, 12)
    d = np.full(X.shape, 1e9)
    tt = np.zeros(X.shape)
    for k in range(len(sp) - 1):
        dk = sd_round_cone(X, Y, sp[k], sp[k + 1], rad[k], rad[k + 1])
        closer = dk < d
        tt = np.where(closer, t[k], tt)
        d = np.minimum(d, dk)
    # 两边一簇簇尖毛：沿尾巴的位置排一串尖峰，越往尖越长，尖往尾尖歪
    # 尖毛的间距、长短、尖不尖都随机抖（左右两边各一套），不排得太齐
    side = np.sign((X - np.interp(Y, sp[::-1, 1], sp[::-1, 0])))
    rr2 = np.random.default_rng(14203)
    knots = np.concatenate([[0], np.cumsum(rr2.uniform(0.55, 1.5, 13))])
    knots /= knots[-1]
    qq = np.interp(tt, knots, np.linspace(0, 1, 14)) * 13 + 0.5 * (side > 0)
    idx = np.clip(np.floor(qq).astype(int), 0, 13)
    amps = rr2.uniform(0.5, 1.35, 14)[idx]
    sharp = rr2.uniform(1.8, 3.4, 14)[idx]
    ph = np.mod(qq + np.clip(-d / 18.0, -1, 1) * 0.7, 1.0)
    spike = np.clip(1 - np.abs(ph - 0.5) * 2, 0, 1) ** sharp
    d = d - (3 + 14 * tt**1.2) * amps * spike * smoothstep(0.05, 0.25, tt) * smoothstep(30, 0, np.abs(d))
    m = smoothstep(0.5, -0.5, d)
    # 尖上的青火：尾尖一截发亮，往上窜三条泪滴形的火舌（中间高、两边矮，往外歪），芯白
    acc = Acc(X, Y)
    tip = sp[-1]
    tdir = (sp[-1] - sp[-8]) / (np.linalg.norm(sp[-1] - sp[-8]) + 1e-9)
    tip_zone = smoothstep(90.0, 10.0, np.hypot(X - tip[0], Y - tip[1])) * m
    acc.add((slice(None), slice(None)), 0.32 * tip_zone, 0.8)
    base = sp[-11]
    for off, L, wd, lean in ((0.0, 128.0, 21.0, 0.05), (-11.0, 86.0, 14.0, -0.38), (11.0, 92.0, 14.0, 0.34)):
        nrm = np.array([-tdir[1], tdir[0]])
        b0 = base + nrm * off
        ang = math.atan2(tdir[1], tdir[0]) + lean
        t0 = b0 + L * np.array([math.cos(ang), math.sin(ang)])
        sl = acc.window(min(b0[0], t0[0]) - wd, min(b0[1], t0[1]) - wd, max(b0[0], t0[0]) + wd, max(b0[1], t0[1]) + wd)
        cov, dd, along = F.almond_field(X[sl], Y[sl], b0, t0, wd, bulge=0.3)
        rim = smoothstep(2.0, 0.0, np.abs(dd)) * (dd < 0.8)
        brk = dry(tex := W.ptex(np.random.default_rng(14202), ns=16, nt=256, along=12.0, across=0.6), np.clip(dd / wd, -1, 1), along * 0.6 + off * 0.01, 0.1 + 0.5 * along**2)
        acc.add(sl, (0.35 * cov + 0.7 * rim) * brk, 0.7 + 0.3 * (1 - along))
        core = smoothstep(0.55, 0.0, along) * cov * smoothstep(-wd * 0.18, -wd * 0.4, dd)
        acc.add(sl, 0.9 * core, 1.0)
    extra = (np.clip(acc.a, 0, 1), np.clip(acc.heat(), 0, 1))
    teal = smoothstep(0.72, 0.98, tt) * m  # 尾尖那一截墨里透出青
    body, emit = silhouette_layers(m, 1.3, ss, 14210, glow_px=6.0, extra_emit=extra, tint_zone=(teal, V.col('#1E5A50')))
    return [body], [emit]


# ============================================================== 规格与写出

# 名字 → (生成函数, 尺寸, 锚点, 混合, 可染, 颜色, 附加 meta)。生成函数返回帧列表；返回 (本体, 发光层) 的写两组。
SPECS: dict = {
    "sword_blade": (make_sword_blade, (BLADE_W, BLADE_H), (0.5, 0.5), "add", True, "white",
                    {"_variants": True, "points": "+x", "tint_hint": "#FFE7A8",
                     "note": "万剑归宗的剑影，3 种挑着用（不是动画）：0 长剑、1 符剑（系符纸）、2 剑气；剑尖朝 +X，锚点居中；"
                             "白色可染（建议金 #FFE7A8，金系 #E9D9A6 也行）。代码排成剑河，每柄后面拖一道 fx/streak"}),
    "sword_giant": (make_sword_giant, (GIANT_W, GIANT_H), (250.0 / GIANT_W, 0.5), "add", True, "white",
                    {"points": "+x", "tint_hint": "#FFE7A8",
                     "note": "大剑影：剑柱最外一层，剑尖朝 +X，锚点在剑格中心；代码拿 3–5 张叠成一柄顶天的大剑（大小差一两成、角度差两三度、明暗错开），"
                             "剑格在主角胸口、剑尖顶进云缝；里面再跑小剑影。白色可染（建议金 #FFE7A8），叠加"}),
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
                   {"points": "+x", "emit": "kun_shadow_emit", "note": "鲲影：俯视的大鱼，头朝 +X，锚点居中；焦墨（身子最浓约 0.95，鳍梢约 0.5），水下的虚边、背脊、鳞纹、水面焦散的光纹；"
                                             "画在冰海之上、妖物之下。代码放大约 2 倍（比画面宽）从画面一侧平移到另一侧；放到 2.5 倍以上整片海都在影子里，反而看不出鱼形，可以轻轻左右摆尾（整张绕头转几度）"}),
    "kun_fin": (make_kun_fin, (FIN_W, FIN_H), (0.5, FIN_WATER / FIN_H), "normal", False, "full",
                {"emit": "kun_fin_emit", "points": "+x",
                 "note": "鲲的背鳍露出水面：往 +X 游，锚点在水面线正中；焦墨、鳍条浓、膜半透明，入水处淡进水里，普通混合（画在冰海和鲲影之上、妖物之下）；"
                         "发光层见 kun_fin_emit（前缘湿亮、冰边、根上白浪、鳍前浪花）。代码跟着鲲影的背脊走，身后拖八字浪痕"}),
    "kun_leap": (make_kun_leap, (LEAP_SIZE, LEAP_SIZE), (0.5, LEAP_WATER / LEAP_SIZE), "add", False, "full",
                 {"points": "+x", "fps": 12,
                  "note": "鲲跃出水：侧面的冷光剪影，头朝 +X；锚点在水面线正中。0 破水、1 半身、2 跃到最高（鳍张开像翅膀）、3 翻过去、4 扎回、5 水花落下；"
                          "叠加、自带冷光色（#5E9AD8 → #CDEBFF → 白）。12 帧/秒，第 2 帧上顿帧 0.08 秒；代码放大约 1.9 倍"}),
    "ult_lotus": (make_ult_lotus, (LOTUS_W, LOTUS_H), (0.5, 1.0), "normal", False, "full",
                  {"hold_last": True, "emit": "ult_lotus_emit",
                   "note": "燃灯的莲灯：三层莲瓣围着灯焰，从花苞一层层打开（0–1 花苞升起、2–3 外层开、4–5 中层开灯焰露出、6–7 全开）；"
                           "锚点在底边中点（莲座底下），代码让它从主角的灯升到头顶上方；叠加、自带灯金色（#D9963F → #FFE7A8 → 白），末帧可以留到演出完"}),
    "ult_rays": (make_ult_rays, (RAYS_SIZE, RAYS_SIZE), (0.5, 0.5), "add", False, "full",
                 {"note": "放射佛光：千道细光、几十道柔光束，中心白热；锚点居中（放在莲灯的灯焰上）。代码两张叠着反向慢转（一张放大 1.15 倍），"
                          "从 0.4 倍长到盖满全屏（约 2 倍）；叠加、自带灯金色；佛光期间暗层提亮到八成"}),
    "ult_halo": (make_ult_halo, (HALO_SIZE, HALO_SIZE), (0.5, 0.5), "add", False, "full",
                 {"note": "头光：圆光 + 放射纹 + 一圈小珠 + 火焰纹，锚点居中，放在莲灯后面（也可以放主角头后），跟着慢转；叠加、自带灯金色"}),
    "fox_moon": (make_fox_moon, (MOON_SIZE, MOON_SIZE), (0.5, 0.5), "add", True, "white",
                 {"tint_hint": "#DCE6FF", "radius_px": int(MOON_R), "screen_space": "top",
                  "note": "九尾登场的月亮：满月，淡墨晕的月海、临边昏暗、一圈柔光和淡月晕；锚点居中，贴在镜头上方，代码从 0.6 倍放大到约 1.6 倍压到画面上方。"
                          "白色可染（建议冷白 #DCE6FF，血月染红），叠加"}),
    "fox_body": (make_fox_body, (FOX_W, FOX_W), (0.5, 471 / FOX_W), "normal", False, "full",
                 {"emit": "fox_body_emit", "sockets": {"tail_root": [FOX_TAIL_ROOT[0], FOX_TAIL_ROOT[1]], "eye": list(FOX_EYE)},
                  "note": "九尾的身子剪影（没有尾巴）：朝 +X 坐着、头抬起来望月；锚点在地面线正中；尾根挂点 tail_root，九条 fox_tail 从这里旋开成扇（扇在身后）。"
                          "焦墨（带一点青黑）+ 一道青边，普通混合；在月亮前面时要画在月亮之上（同月亮一样在暗层之上）；发光层见 fox_body_emit"}),
    "fox_tail": (make_fox_tail, (TAIL_W, TAIL_H), (TAIL_ROOT[0] / TAIL_W, TAIL_ROOT[1] / TAIL_H), "normal", False, "full",
                 {"emit": "fox_tail_emit", "points": "-y",
                  "note": "九尾的一条尾巴：锚点在尾根，尾巴朝上（−Y），S 形、两边一簇簇尖毛；代码从身子的 tail_root 旋开九条成扇（−78°…+78°，"
                          "中间长、两边短，前后两层错开），一条条展开。焦墨 + 青边，普通混合；发光层见 fox_tail_emit（青边、尾尖的青火）"}),
}
EMIT_SPECS = {
    "sword_cloud": {"name": "sword_cloud_emit", "blend": "add", "tint": False, "color": "full",
                    "note": "被劈开的云的发光层：缝口金线、缝里漏下的光、靠缝的云边描金；叠加、自带金色（#E3B05A → #FFE7A8 → #FFF8E8），画在暗层之上"},
}
EMIT_SPECS["kun_sea"] = {"name": "kun_sea_emit", "blend": "add", "tint": False, "color": "full",
                         "note": "冰海的发光层：冰缝、水边冰下透的光、冰板缝、浪尖亮线和碎光；叠加、自带冰色（#7FB6E8 → #CDEBFF → 白），画在暗层之上"}
EMIT_SPECS["kun_shadow"] = {"name": "kun_shadow_emit", "blend": "add", "tint": False, "color": "full",
                            "note": "鲲影的发光层：影子边上一圈冰光，叠加、自带冰色；和鲲影同画布、同锚点、同缩放，画在冰海发光层之上"}
EMIT_SPECS["kun_fin"] = {"name": "kun_fin_emit", "blend": "add", "tint": False, "color": "full",
                         "note": "背鳍的发光层：前缘湿亮的冰光、冰边、根上一圈白浪、鳍前浪花和水珠；叠加、自带冰色"}
EMIT_SPECS["ult_lotus"] = {"name": "ult_lotus_emit", "blend": "add", "tint": False, "color": "full",
                           "note": "莲灯的发光层：看得见的瓣边描金、瓣根被灯焰照透的暖光、灯焰（芯白）、全开时的几道短光；叠加、自带灯金色"}
EMIT_SPECS["fox_body"] = {"name": "fox_body_emit", "blend": "add", "tint": False, "color": "full",
                          "note": "九尾身子的发光层：青边往外一圈光、丹凤眼、额心青火印；叠加、自带狐火青（#3FB59A → #8FE3C8 → 白）"}
EMIT_SPECS["fox_tail"] = {"name": "fox_tail_emit", "blend": "add", "tint": False, "color": "full",
                          "note": "九尾尾巴的发光层：青边、尾尖一截青火往上窜；叠加、自带狐火青"}
GROUPS = {"sword": ["sword_blade", "sword_giant", "sword_cloud"], "kun": ["kun_sea", "kun_shadow", "kun_fin", "kun_leap"], "ult": ["ult_lotus", "ult_rays", "ult_halo"],
          "fox": ["fox_moon", "fox_body", "fox_tail"]}


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


def fname(name: str, n: int, i: int, emit: bool = False) -> str:
    """文件名：多帧的帧号在前、_emit 在后（同 actors 图集：sword_cloud_0_emit）；单张的 fox_body_emit。"""
    tail = "_emit" if emit else ""
    return f"{name}{tail}.png" if n == 1 else f"{name}_{i}{tail}.png"


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
        # 先删掉这一组旧的条目和文件（包括上一轮 <名>_emit_<帧号> 写法的）
        for k in [k for k in files if k.startswith(name + "_") or k == name + ".png"]:
            files.pop(k, None)
        for old in list(OUT.glob(f"{name}_*.png")) + list(OUT.glob(f"{name}.png")):
            if old.stem == name or old.stem[len(name) + 1:].split("_")[0] in {str(j) for j in range(64)} | {"emit"}:
                old.unlink()
        for i, img in enumerate(body):
            assert img.size == tuple(spec[1]), (name, img.size, spec[1])
            V.save_png(img, OUT / fname(name, n, i))
            files[fname(name, n, i)] = meta_for(name, spec, n, i)
        if emit is not None:
            en = EMIT_SPECS[name]
            for i, img in enumerate(emit):
                assert img.size == tuple(spec[1])
                V.save_png(img, OUT / fname(name, n, i, emit=True))
                files[fname(name, n, i, emit=True)] = meta_for(name, spec, n, i, emit=en)
        print(f"{name}: {n} 帧{' + 发光层' if emit else ''}  {time.perf_counter() - t0:.1f}s", flush=True)
    meta = {"name": "myth", "generator": GENERATOR, "format": "PNG RGBA，直通（非预乘）alpha", "px_per_unit": PPU, "files": dict(sorted(files.items()))}
    meta_path.write_text(V.dump_json(meta), encoding="utf-8")


def load(name: str, emit: bool = False) -> list[Image.Image]:
    """读回一组（审图、分镜用）。单张的返回一个元素的列表；emit=True 读发光层。"""
    if (OUT / fname(name, 1, 0, emit)).exists():
        return [Image.open(OUT / fname(name, 1, 0, emit)).convert("RGBA")]
    out = []
    i = 0
    while (OUT / fname(name, 2, i, emit)).exists():
        out.append(Image.open(OUT / fname(name, 2, i, emit)).convert("RGBA"))
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
