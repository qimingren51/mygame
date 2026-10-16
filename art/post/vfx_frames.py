#!/usr/bin/env python3
"""提灯夜行 · 逐帧特效图（质感会话的清单，试玩第 1 轮第 5 项）。只出桌面版 2 倍，Pillow + numpy，不用 Blender。

约定（质感会话定的）：
  - 进 vfx 图集，帧名 vfx/<名字>_<帧号>（帧号从 0 起，一位数）；同一组每帧画布一样大、锚点一样（默认画布中心）。
  - 2 倍密度（4 像素 / 世界单位）。一次性的按 24 帧/秒，播完就没；meta 写 anim、frame、frames、fps、loop。
  - 可染：白色，tint: true，游戏按五行色乘（金 #E9D9A6、木 #6FD6A0、水 #6FB8FF、火 #FF8A3D、土 #C9925A）。
  - 叠加帧：游戏在线性 HDR 里叠、还过辉光，最亮处 alpha 约 0.8；边缘是水墨的飞白、干笔断续，不画平滑的渐变圆。
  - 普通混合的墨色用焦墨 #17140F。有方向的帧开口或前进方向朝 +X；地面上的环按透视压扁，高 ÷ 宽 ≈ 0.62。

第一批：hit_metal / hit_wood / hit_water / hit_fire / hit_earth（各 5 帧 128²）、crit（4 帧 192²，白金 #FFF3D6，不染）、
slash（6 帧，月牙刀光，弧心是锚点，扇形朝 +X 张开 120°）、kill_ink（6 帧 192²，焦墨，普通混合，末帧留着）、
shockwave（6 帧 512×320，贴地亮环，已压扁）。

slash 的画布：清单写的 256×128 只放得下半径约 70 像素的 120° 扇形（铜钱剑半径 70–85 世界单位 = 280–340 像素，要放大 4–5 倍，
会糊）；这里改成 256×448、弧心在左边 (16, 224)，外沿半径 200 像素（50 世界单位，游戏里放大 1.4–1.7 倍），
meta 照扇形预警 weapons/sector 的写法：points: "+x"、radius_px（外沿半径）、angle_deg。弧心左边那一大块是空的，打包时会裁掉，不占图集。

产物：art/out/assets@2x/vfx_frames/*.png + meta.json（name: vfx）
审图：art/out/review@2x/vfx_frames_b1.png（纸色底 / 夜色底的帧条）、vfx_frames_b1_ingame.png（1080p 合成）
打包：pack_atlas.py --name vfx --out assets/atlas $A/vfx $A/weapons $A/vfx_leaves $A/vfx_frames

用法（仓库根目录）：
  art/.venv/bin/python art/post/vfx_frames.py
  art/.venv/bin/python art/post/test_vfx_frames.py
"""

from __future__ import annotations

import json
import math
import os
import sys
import time
from pathlib import Path

os.environ["LANTERN_ART_DENSITY"] = "2"  # 只有桌面版：先定密度，再导入 style / vfx_textures

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import vfx_textures as V  # noqa: E402
import weapon_textures as W  # noqa: E402

S = V.S
assert V.D == 2
OUT = V.OUT / "assets@2x" / "vfx_frames"
REVIEW = V.OUT / "review@2x"
GENERATOR = "art/post/vfx_frames.py"
PPU = 4
SS = 4  # 超采样
FPS = 24
PEAK = 0.8  # 叠加帧最亮处的 alpha
smoothstep = V.smoothstep
JIAO = V.col(S.INK["jiao"])
CRIT_RGB = V.col("#FFF3D6")
ELEMENT = {"metal": "#E9D9A6", "wood": "#6FD6A0", "water": "#6FB8FF", "fire": "#FF8A3D", "earth": "#C9925A"}
SHOCK_TINT = "#FFE2A8"
FLAT = 0.62  # 地面透视：高 ÷ 宽


# ============================================================== 基础


def grid(w: int, h: int):
    """超采样网格，坐标是最终像素（像素中心在 .5）。"""
    return V.grid(h, w, SS)


def frame_white(a_ss: np.ndarray, seed: int, peak: float = PEAK, rgb=None) -> Image.Image:
    """超采样的亮度场 → 白色（或给定颜色）叠加帧：缩小、软饱和到 peak、蓝噪声抖动；四边一圈为 0。"""
    a = V.downsample(np.clip(a_ss, 0, None), SS)
    a = peak * np.tanh(1.25 * np.clip(a, 0.0, 1.0)) / math.tanh(1.25)  # 1 → peak，淡处略提一点
    a8 = V.dither_alpha(a, np.random.default_rng(seed))
    a8[a < 0.004] = 0
    a8[0, :] = a8[-1, :] = a8[:, 0] = a8[:, -1] = 0
    return V.to_rgba8(V.WHITE if rgb is None else rgb, None, a8)


def frame_ink(a_ss: np.ndarray, seed: int) -> Image.Image:
    """超采样的墨的浓度 → 焦墨、普通混合的帧（同样抖动、四边为 0）。"""
    a = np.clip(V.downsample(np.clip(a_ss, 0, None), SS), 0, 1)
    a8 = V.dither_alpha(a, np.random.default_rng(seed))
    a8[a < 0.004] = 0
    a8[0, :] = a8[-1, :] = a8[:, 0] = a8[:, -1] = 0
    return V.to_rgba8(JIAO, None, a8)


def soft_union(*fields) -> np.ndarray:
    """几层亮度合起来：1 − ∏(1 − a)，重叠处变亮但不会无限叠。"""
    out = np.zeros_like(fields[0])
    for f in fields:
        out = 1.0 - (1.0 - out) * (1.0 - np.clip(f, 0, 1))
    return out


def seg(X, Y, x0, y0, x1, y1):
    """到线段的距离和沿线参数 u∈[0,1]。"""
    dx, dy = x1 - x0, y1 - y0
    L2 = max(dx * dx + dy * dy, 1e-9)
    u = np.clip(((X - x0) * dx + (Y - y0) * dy) / L2, 0.0, 1.0)
    return np.hypot(X - (x0 + u * dx), Y - (y0 + u * dy)), u


def needle(X, Y, x0, y0, ang, L, w0, *, w1=0.0, taper=1.2, aa=0.45):
    """从 (x0, y0) 朝 ang 的针状光：半宽从 w0 收到 w1（起笔饱满、收笔尖）。返回覆盖度、沿线参数 u。"""
    d, u = seg(X, Y, x0, y0, x0 + L * math.cos(ang), y0 + L * math.sin(ang))
    hw = w1 + (w0 - w1) * (1.0 - u) ** taper
    return smoothstep(hw + aa, hw - aa, d), u


def dot(X, Y, x, y, r, aa=0.45):
    return smoothstep(r + aa, r - aa, np.hypot(X - x, Y - y))


def streak(X, Y, x0, y0, x1, y1, w, aa=0.45):
    """一道拖尾：从 (x0, y0) 细到 (x1, y1) 粗（头在 1 端），火星、水珠的运动模糊。"""
    d, u = seg(X, Y, x0, y0, x1, y1)
    hw = w * (0.25 + 0.75 * u)
    return smoothstep(hw + aa, hw - aa, d) * (0.35 + 0.65 * u)


def dry(tex, s, t, k):
    """飞白：笔毛纹理 tex 在 (s 横跨笔触 −1..1, t 沿笔触) 处的值高于 k 才着墨。k 越大越干。"""
    k = np.asarray(k, dtype=np.float64)
    if np.all(k <= 0):
        return 1.0
    return smoothstep(k - 0.09, k + 0.09, W.sample_ptex(tex, s, t))


def poly_cover(X, Y, poly, aa=0.45):
    d, _ = W.poly_sdf(X, Y, np.asarray(poly, dtype=np.float64))
    return smoothstep(aa, -aa, d), d


def ease_out(t, p=2.0):
    return 1.0 - (1.0 - t) ** p


def rough_radius(rng, theta, base, amp, harmonics=(3, 4, 5, 7, 9)):
    """不规则的轮廓半径：base × (1 + 角向噪声)。"""
    return base * (1.0 + V.angular_noise(rng, theta, harmonics=harmonics, amp=amp))


# ============================================================== 命中：金（十字闪 + 斜的剑痕碎光）


def make_hit_metal() -> list[Image.Image]:
    """细长的十字闪（横长竖短、略斜），两三道斜的剑痕碎光往外错开、碎掉，几点火星甩出去。"""
    w = h = 128
    cx, cy = 64.0, 64.0
    X, Y = grid(w, h)
    rng = np.random.default_rng(9101)
    tex = W.ptex(rng, ns=16, nt=256, along=12.0, across=0.7)
    tilt = math.radians(-12.0)
    shards = []
    for k in range(3):
        side = (-1) ** k
        ang = tilt + math.radians(side * rng.uniform(38, 52) + (0 if k < 2 else 180))
        off = rng.uniform(10, 16)
        nrm = ang + math.pi / 2
        ox, oy = cx + off * math.cos(nrm) * side, cy + off * math.sin(nrm) * side
        shards.append((ang, ox, oy, rng.uniform(28, 38), rng.uniform(1.6, 2.3), nrm, side))
    sparks = [(rng.uniform(0, 2 * math.pi), rng.uniform(26, 44), rng.uniform(0.7, 1.2)) for _ in range(11)]
    env = [1.0, 0.86, 0.62, 0.38, 0.16]
    Lh = [50, 58, 56, 46, 32]
    wr = [2.7, 2.1, 1.6, 1.15, 0.8]
    out = []
    for i in range(5):
        t = i / 4
        a = []
        for L, ang in ((Lh[i], tilt), (Lh[i], tilt + math.pi), (0.5 * Lh[i], tilt + math.pi / 2), (0.5 * Lh[i], tilt - math.pi / 2)):
            c, u = needle(X, Y, cx, cy, ang, L, wr[i], taper=1.4)
            s = ((X - cx) * -math.sin(ang) + (Y - cy) * math.cos(ang)) / max(wr[i], 1e-3)
            a.append(env[i] * c * dry(tex, np.clip(s, -1, 1), u * 0.35 + ang / 7.0, np.maximum(0.0, 0.55 * t + 0.5 * u - 0.45)))
        r = np.hypot(X - cx, Y - cy)
        a.append(env[i] * np.exp(-((r / (5.0 - 2.6 * t)) ** 2)))
        a.append(0.35 * env[i] * np.exp(-((r / (11.0 - 4 * t)) ** 2)) * (i < 3))
        for ang, ox, oy, L, wd, nrm, side in shards:
            appear = [0.75, 1.0, 0.82, 0.52, 0.24][i]
            drift = 7.0 * ease_out(t)
            x0 = ox + drift * math.cos(nrm) * side - 0.5 * L * math.cos(ang)
            y0 = oy + drift * math.sin(nrm) * side - 0.5 * L * math.sin(ang)
            c, u = needle(X, Y, x0, y0, ang, L * (0.8 + 0.25 * min(t * 2, 1)), wd * (1 - 0.45 * t), w1=0.3, taper=0.8)
            s = ((X - x0) * -math.sin(ang) + (Y - y0) * math.cos(ang)) / max(wd, 1e-3)
            a.append(appear * c * dry(tex, np.clip(s, -1, 1), u * 0.5 + nrm, 0.15 + 0.6 * t))
        for ang, d1, sz in sparks:
            if i == 0:
                continue
            d = 8 + d1 * ease_out(t, 1.6)
            tail = 9 * (1 - t) + 2
            x1, y1 = cx + d * math.cos(ang), cy + d * math.sin(ang)
            x0, y0 = cx + (d - tail) * math.cos(ang), cy + (d - tail) * math.sin(ang)
            a.append(0.9 * (1 - t) ** 1.1 * streak(X, Y, x0, y0, x1, y1, sz))
        out.append(frame_white(soft_union(*a), 9110 + i))
    return out


# ============================================================== 命中：木（纸屑、叶片翻飞）


def make_hit_wood() -> list[Image.Image]:
    """中心一下六瓣的亮，八九片叶片、纸屑状的亮片从中心翻飞出去：边亮、中间一道叶脉，翻转时变窄，越飞越淡；
    前两帧亮片后面拖一道短影。"""
    w = h = 128
    cx, cy = 64.0, 64.0
    X, Y = grid(w, h)
    rng = np.random.default_rng(9201)
    n = 9
    flakes = []
    for k in range(n):
        phi = 2 * math.pi * (k + rng.uniform(-0.3, 0.3)) / n
        flakes.append(dict(phi=phi, dist=rng.uniform(24, 38), L=rng.uniform(12, 17), Wd=rng.uniform(5.0, 7.0),
                           rot0=rng.uniform(0, math.pi), spin=rng.uniform(-6, 6), tum=rng.uniform(2.5, 5.5),
                           ph=rng.uniform(0, math.pi), leaf=k % 3 != 0, wob=rng.uniform(-3, 3),
                           jit=rng.uniform(-0.25, 0.25, (4, 2))))
    specks = [(rng.uniform(0, 2 * math.pi), rng.uniform(14, 40), rng.uniform(0.6, 1.0)) for _ in range(12)]

    def pos(f, t):
        d = 5 + f["dist"] * ease_out(t, 1.7)
        return (cx + d * math.cos(f["phi"]) + f["wob"] * math.sin(3 * t + f["ph"]) * t,
                cy + d * math.sin(f["phi"]) - 6 * t * t)  # 纸屑飘起一点

    out = []
    for i in range(5):
        t = i / 4
        a = []
        r = np.hypot(X - cx, Y - cy)
        if i < 2:
            th = np.arctan2(Y - cy, X - cx)
            star = 0.5 + 0.5 * np.cos(6 * th + 0.4)
            a.append((0.95 - 0.45 * i) * np.exp(-((r / (8.0 + 5 * i + 5 * star)) ** 2)))
        for f in flakes:
            px, py = pos(f, t)
            rot = f["rot0"] + f["spin"] * t
            tumble = max(0.25, abs(math.cos(f["tum"] * t + f["ph"])))
            L, Wd = f["L"] * (1 - 0.15 * t), f["Wd"] * tumble * (1 - 0.15 * t)
            u = np.array([math.cos(rot), math.sin(rot)])
            base, tip = np.array([px, py]) - u * L / 2, np.array([px, py]) + u * L / 2
            if f["leaf"]:
                poly = W.almond(base, tip, Wd, n=28, bulge=0.5, asym=0.15)
            else:  # 纸屑：歪的四边形
                v = np.array([-u[1], u[0]]) * Wd / 2
                poly = np.array([base + v, tip + v * 0.7, tip - v, base - v * 0.8]) + f["jit"] * np.array([L, Wd]) * 0.3
            cov, dd = poly_cover(X, Y, poly)
            rim = smoothstep(1.6, 0.0, np.abs(dd)) * (dd < 0.6)
            vein, _ = needle(X, Y, base[0], base[1], rot, L, 0.5, w1=0.15, taper=0.6)
            fade = (1 - 0.8 * t) ** 1.1 if i else 0.9  # 末帧还剩一点淡的
            a.append(fade * np.clip(0.5 * cov + 0.72 * rim - 0.3 * vein * f["leaf"], 0, 1))
            if 1 <= i <= 2:  # 拖影：从上一帧的位置拉过来
                qx, qy = pos(f, max(t - 0.2, 0.0))
                a.append(0.32 * fade * streak(X, Y, qx, qy, px, py, 0.32 * f["Wd"]))
        for ang, d1, sz in specks:
            d = 6 + d1 * ease_out(t, 1.5)
            a.append(0.8 * (1 - 0.85 * t) * dot(X, Y, cx + d * math.cos(ang), cy + d * math.sin(ang) - 3 * t, sz))
        out.append(frame_white(soft_union(*a), 9210 + i))
    return out


# ============================================================== 命中：水（一圈水花，冰晶溅开）


def make_hit_water() -> list[Image.Image]:
    """一圈水花（略扁的环，断成一簇簇水珠，环上冒几根冠状的水刺），几粒尖的冰晶往外溅：冰晶边亮、里面淡。"""
    w = h = 128
    cx, cy = 64.0, 64.0
    X, Y = grid(w, h)
    rng = np.random.default_rng(9301)
    tex = W.ptex(rng, ns=12, nt=512, along=9.0, across=0.8)
    ring_flat = 0.82
    rr = np.hypot(X - cx, (Y - cy) / ring_flat)
    th = np.mod(np.arctan2((Y - cy) / ring_flat, X - cx) / (2 * math.pi), 1.0)
    spikes = [(rng.uniform(0, 2 * math.pi), rng.uniform(6, 11)) for _ in range(9)]
    drops = [(rng.uniform(0, 2 * math.pi), rng.uniform(30, 48), rng.uniform(1.1, 1.8)) for _ in range(10)]
    ice = [(2 * math.pi * (k + rng.uniform(-0.25, 0.25)) / 6, rng.uniform(34, 52), rng.uniform(4.0, 6.5), rng.uniform(0, math.pi), rng.uniform(-5, 5))
           for k in range(6)]
    R = [9, 20, 30, 38, 44]
    wr = [4.5, 3.8, 3.0, 2.4, 1.8]
    env = [1.0, 0.92, 0.72, 0.48, 0.22]
    out = []
    for i in range(5):
        t = i / 4
        a = []
        q = (rr - R[i]) / wr[i]
        ring = np.exp(-(q**2) * 1.6) * dry(tex, np.clip(q, -1, 1), th, 0.12 + 0.55 * t)
        a.append(env[i] * ring)
        if i == 0:
            a.append(0.9 * np.exp(-((np.hypot(X - cx, Y - cy) / 6.5) ** 2)))
        for ang, L in spikes:
            if i == 0 or i == 4:
                continue
            bx, by = cx + R[i] * math.cos(ang), cy + R[i] * math.sin(ang) * ring_flat
            c, _ = needle(X, Y, bx, by, ang, L * (1.0 - 0.3 * t), 1.5, taper=1.0)
            a.append(env[i] * 0.85 * c)
        for ang, d1, sz in drops:
            d = 10 + d1 * ease_out(t, 1.8)
            x1, y1 = cx + d * math.cos(ang), cy + d * math.sin(ang) + 10 * t * t
            back = 7 * (1 - t) + 2
            x0, y0 = cx + (d - back) * math.cos(ang), cy + (d - back) * math.sin(ang) + 10 * t * t
            a.append((0.9 if i else 0.0) * (1 - t) ** 0.9 * streak(X, Y, x0, y0, x1, y1, sz))
        for ang, d1, sz, rot0, spin in ice:
            if i == 0:
                continue
            d = 8 + d1 * ease_out(t, 2.0)
            px, py = cx + d * math.cos(ang), cy + d * math.sin(ang) + 6 * t * t
            rot = rot0 + spin * t
            u = np.array([math.cos(rot), math.sin(rot)])
            v = np.array([-u[1], u[0]])
            p = np.array([px, py])
            poly = [p + u * sz, p + v * sz * 0.38, p - u * sz * 0.55, p - v * sz * 0.38]
            cov, dd = poly_cover(X, Y, poly)
            edge = smoothstep(1.1, 0.0, np.abs(dd))
            a.append((1 - t) ** 0.7 * np.clip(0.3 * cov + 0.85 * edge, 0, 1))
        out.append(frame_white(soft_union(*a), 9310 + i))
    return out


# ============================================================== 命中：火（小燃爆，火舌往上卷）


def make_hit_fire() -> list[Image.Image]:
    """中心一团亮的燃爆，五六条火舌从中心往外冲、再往上卷（钉头鼠尾、尖上飞白），火星往上飘；燃爆退下去，火舌越卷越细。"""
    w = h = 128
    cx, cy = 64.0, 66.0
    X, Y = grid(w, h)
    rng = np.random.default_rng(9401)
    tongues = []
    for k in range(6):
        phi = math.radians(-90 + (k - 2.5) * 30 + rng.uniform(-8, 8))  # 朝上半边散开
        tongues.append(dict(phi=phi, L=rng.uniform(26, 38), Wd=rng.uniform(2.6, 3.8), curl=rng.choice([-1.0, 1.0]) * rng.uniform(0.5, 1.0),
                            seed=int(rng.integers(1 << 30))))
    embers = [(rng.uniform(-1, 1), rng.uniform(20, 40), rng.uniform(0.6, 1.1), rng.uniform(0, 6)) for _ in range(9)]
    Ls = [0.35, 0.78, 1.0, 0.95, 0.72]
    Ws = [1.0, 1.0, 0.85, 0.62, 0.38]
    env = [1.0, 0.95, 0.8, 0.56, 0.3]
    out = []
    for i in range(5):
        t = i / 4
        a = []
        th = np.arctan2(Y - cy, X - cx)
        rad = rough_radius(np.random.default_rng(9402), th, [10.0, 9.0, 6.5, 4.0, 2.0][i], 0.18)
        core = smoothstep(rad + 1.5, rad - 2.5, np.hypot(X - cx, Y - cy))
        a.append([0.95, 0.8, 0.55, 0.3, 0.12][i] * core)
        for tg in tongues:
            L = tg["L"] * Ls[i]
            rise = 9.0 * t
            ux, uy = math.cos(tg["phi"]), math.sin(tg["phi"])
            b = np.array([cx + 5 * ux, cy + 5 * uy - rise])
            up = np.array([0.0, -1.0])
            side = np.array([-uy, ux]) * tg["curl"]
            ctrl = [b, b + np.array([ux, uy]) * L * 0.45, b + np.array([ux, uy]) * L * 0.6 + up * L * 0.45, b + up * L * 0.85 + side * L * 0.35]
            pts = V.bezier(ctrl, 90)
            tt = np.linspace(0, 1, len(pts))
            hw = tg["Wd"] * Ws[i] * (0.65 + 0.35 * np.sin(np.pi * np.clip(tt / 0.3, 0, 1) * 0.5)) * (1 - tt) ** 0.85
            cov, _ = V.brush_stroke(X, Y, pts, np.maximum(hw, 0.05), np.random.default_rng(tg["seed"]), dry=0.35 + 0.35 * t, dry_start=0.5, ss=SS)
            a.append(env[i] * cov)
        for x0, d1, sz, ph in embers:
            if i == 0:
                continue
            px = cx + x0 * 22 + 3 * math.sin(5 * t + ph)
            py = cy - 6 - d1 * ease_out(t, 1.4)
            a.append(0.9 * (1 - t) * streak(X, Y, px, py + 5, px, py, sz))
        out.append(frame_white(soft_union(*a), 9410 + i))
    return out


# ============================================================== 命中：土（闷的爆点，碎石往下落）


def make_hit_earth() -> list[Image.Image]:
    """闷的爆点：一团扁的、边缘起毛的光（不尖、不白，往外散得慢），底下往两边压出一层尘；
    七八块棱角石块先往上、往外蹦，再往下掉、打着转，石块边亮、上沿更亮。"""
    w = h = 128
    cx, cy = 64.0, 62.0
    X, Y = grid(w, h)
    rng = np.random.default_rng(9501)
    tex = W.ptex(rng, ns=12, nt=512, along=8.0, across=0.9)
    rocks = []
    for k in range(8):
        ang = math.radians(-90 + (k - 3.5) * 22 + rng.uniform(-7, 7))
        sp = rng.uniform(150, 250)
        n_v = int(rng.integers(4, 7))
        verts = [(2 * math.pi * j / n_v + rng.uniform(-0.3, 0.3), rng.uniform(0.7, 1.0)) for j in range(n_v)]
        rocks.append(dict(vx=1.25 * sp * math.cos(ang), vy=-rng.uniform(300, 420) * abs(math.sin(ang)) ** 0.5, size=rng.uniform(3.8, 6.0) * (1.3 if k % 3 == 1 else 1.0),
                          verts=verts, rot0=rng.uniform(0, math.pi), spin=rng.uniform(-9, 9)))
    g = 4800.0  # 像素 / 秒²：蹦起来一下就往下掉
    out = []
    for i in range(5):
        t = i / 4
        T = i / FPS
        a = []
        dx, dy = X - cx, (Y - cy) / 0.7
        rr = np.hypot(dx, dy)
        th = np.arctan2(dy, dx)
        Rb = [15.0, 20.0, 23.0, 25.0, 26.0][i]
        edge = rough_radius(np.random.default_rng(9502), th, Rb, 0.18)
        body = smoothstep(edge + 2.0, edge - 5.0, rr) * (0.55 + 0.45 * smoothstep(edge, 0, rr))
        hole = smoothstep(edge * 0.3, edge * 0.9, rr) if i >= 2 else 1.0  # 爆点散开，中间先空
        a.append([0.74, 0.66, 0.48, 0.3, 0.13][i] * body * hole * dry(tex, np.clip(rr / edge * 2 - 1, -1, 1), np.mod(th / (2 * math.pi), 1), 0.08 + 0.42 * t))
        if i < 2:
            a.append([0.5, 0.3][i] * np.exp(-((rr / 7.0) ** 2)))
        dust = np.exp(-((np.hypot((X - cx) / (20 + 30 * t), (Y - cy - 9) / (5 + 4 * t))) ** 2)) * smoothstep(62.0, 44.0, np.abs(X - cx))
        a.append([0.0, 0.48, 0.42, 0.26, 0.1][i] * dust * dry(tex, np.clip((Y - cy - 9) / 7, -1, 1), (X - cx) / 160 + 0.5, 0.16 + 0.4 * t))
        for rk in rocks:
            if i == 0:
                continue
            px = cx + rk["vx"] * T
            py = cy - 4 + rk["vy"] * T + 0.5 * g * T * T
            rot = rk["rot0"] + rk["spin"] * T
            sz = rk["size"]
            poly = [(px + sz * f * math.cos(a0 + rot), py + sz * f * math.sin(a0 + rot)) for a0, f in rk["verts"]]
            cov, dd = poly_cover(X, Y, poly)
            rim = smoothstep(1.4, 0.0, np.abs(dd))
            top = smoothstep(py + sz, py - sz, Y)  # 上沿受光更亮
            a.append((1 - 0.72 * t) * np.clip(0.42 * cov + 0.72 * rim * (0.55 + 0.45 * top), 0, 1))
        out.append(frame_white(soft_union(*a), 9510 + i))
    return out


# ============================================================== 暴击（四角星大闪 + 两道交叉笔锋）


def make_crit() -> list[Image.Image]:
    """四角星形的大闪（凹边四芒星：四根针一样的光芒，芒尖细而利、飞白，中心一点最亮），两道交叉的笔锋斜着划过
    （起笔饱满、收笔飞白）；第 0 帧最大最亮，之后收小、变干、散成光点。颜色白金 #FFF3D6，不染色。"""
    w = h = 192
    cx, cy = 96.0, 96.0
    X, Y = grid(w, h)
    rng = np.random.default_rng(9601)
    tex = W.ptex(rng, ns=16, nt=256, along=10.0, across=0.7)
    dx, dy = X - cx, Y - cy
    r = np.hypot(dx, dy)
    motes = [(2 * math.pi * k / 8 + rng.uniform(-0.2, 0.2), rng.uniform(30, 58), rng.uniform(0.8, 1.4)) for k in range(8)]
    strokes = []
    for k, ang in enumerate((math.radians(-40), math.radians(52))):
        L = 168 - 18 * k
        pts = np.stack([np.linspace(-L / 2, L / 2, 120), 3.0 * np.sin(np.linspace(0, math.pi, 120)) * (1 - 2 * k)], -1)
        rot = np.array([[math.cos(ang), -math.sin(ang)], [math.sin(ang), math.cos(ang)]])
        strokes.append((pts @ rot.T + np.array([cx, cy]), int(rng.integers(1 << 30))))
    R = [88.0, 70.0, 50.0, 30.0]
    env = [1.0, 0.74, 0.48, 0.24]
    out = []
    for i in range(4):
        t = i / 3
        rot = math.radians(4 * i)
        a = []
        for k in range(4):  # 四根光芒：凹边收尖，芒尖飞白
            ang = rot + k * math.pi / 2
            L = R[i] * (1.0 if k % 2 == 0 else 0.82)
            c, u = needle(X, Y, cx, cy, ang, L, 0.1 * R[i] + 1.5, taper=1.9)
            s = (dx * -math.sin(ang) + dy * math.cos(ang)) / (0.1 * R[i] + 1.5)
            a.append(env[i] * c * (1.0 - 0.45 * u) * dry(tex, np.clip(s, -1, 1), u * 0.5 + 0.25 * k, 0.55 * u**1.5 + 0.2 * t))
            ridge, _ = needle(X, Y, cx, cy, ang, L * 1.02, 1.1, taper=1.0)
            a.append(env[i] * 0.9 * ridge)
        a.append(env[i] * np.exp(-((r / (7.0 - 3 * t)) ** 2)))
        for pts, sd in strokes:
            tt = np.linspace(0, 1, len(pts))
            hw = (6.0 - 2.6 * t) * np.sin(np.pi * np.clip(tt * 1.05, 0, 1)) ** 0.7 + 0.2
            cov, _ = V.brush_stroke(X, Y, pts, hw, np.random.default_rng(sd), dry=0.25 + 0.4 * t, dry_start=0.35, ss=SS)
            a.append(env[i] * (0.95 - 0.1 * t) * cov)
        for ang, d1, sz in motes:
            if i == 0:
                continue
            d = 28 + d1 * t
            a.append(0.8 * (1.1 - t) * dot(X, Y, cx + d * math.cos(ang), cy + d * math.sin(ang), sz * (1.2 - 0.3 * t)))
        out.append(frame_white(soft_union(*a), 9610 + i, rgb=CRIT_RGB))
    return out


# ============================================================== 刀光（月牙，扇形朝 +X 张开 120°，锚点在弧心）

SLASH_W, SLASH_H = 256, 448
SLASH_C = (16.0, 224.0)  # 弧心（锚点）
SLASH_R = 200.0  # 外沿半径（像素）= 扫击半径
SLASH_ARC = 120.0


def make_slash() -> list[Image.Image]:
    """月牙形的刀光：笔锋沿弧从上扫到下（0–2 帧），尖头在前、身子在后最厚、尾巴拖细；外沿一道利的亮边，往里渐淡、
    顺着挥的方向起飞白；弧里几道速度线；扫完后尾巴追上笔锋、越收越薄、碎成干笔丝（3–5 帧）；笔锋甩出几点火星。"""
    X, Y = grid(SLASH_W, SLASH_H)
    cx, cy = SLASH_C
    R = SLASH_R
    rng = np.random.default_rng(9701)
    tex = W.ptex(rng, ns=28, nt=1024, along=30.0, across=0.6)
    dx, dy = X - cx, Y - cy
    r = np.hypot(dx, dy)
    half = SLASH_ARC / 2
    g = (np.degrees(np.arctan2(dy, dx)) + half) / SLASH_ARC  # 沿弧 0（起笔，上）→ 1（收笔，下）
    head = [0.44, 0.86, 1.0, 1.0, 1.0, 1.0]
    tail = [0.0, 0.0, 0.0, 0.3, 0.56, 0.8]
    thick = [28.0, 44.0, 50.0, 40.0, 28.0, 16.0]
    env = [0.95, 1.0, 1.0, 0.8, 0.52, 0.26]
    dryk = [0.06, 0.04, 0.08, 0.26, 0.42, 0.56]
    lines = [(rng.uniform(0.6, 0.9), rng.uniform(0.0, 0.45), rng.uniform(0.3, 0.7), rng.uniform(0.7, 1.5)) for _ in range(7)]
    sparks = [(rng.uniform(-0.5, 0.5), rng.uniform(14, 32), rng.uniform(0.7, 1.1), rng.uniform(0.35, 0.95)) for _ in range(9)]
    out = []
    for i in range(6):
        hd, tl = head[i], tail[i]
        span = max(hd - tl, 1e-3)
        v = (g - tl) / span  # 0 = 尾，1 = 笔锋
        inside = (v > 0) & (v < 1)
        vc = np.clip(v, 0, 1)
        shape = np.sin(np.pi * vc**1.6) ** 0.8  # 最厚处在笔锋后面一点（v≈0.65），两头收尖
        T = thick[i] * shape
        s = (R - r) / np.maximum(T, 0.5)  # 0 = 外沿，1 = 里沿
        rim = smoothstep(R + 1.0, R - 1.0, r)  # 外沿利
        body = rim * smoothstep(1.0, 0.5, s) * np.exp(-1.5 * np.clip(s, 0, None))
        edge = np.exp(-(((r - (R - 1.6)) / 1.7) ** 2)) * shape**0.4  # 外沿一道亮线
        k = dryk[i] + 0.45 * (1 - vc) ** 2 + 0.3 * np.clip(s, 0, 1) ** 2
        m = dry(tex, np.clip(2 * s - 1, -1, 1), g * 0.85 + 0.11 * i, k)
        a = [env[i] * inside * np.maximum(body, 0.95 * edge) * m]
        for rf, a0, ln, wd in lines:  # 速度线：弧里几道细的、跟在笔锋后面
            g0 = tl + span * a0
            g1 = min(g0 + span * ln, hd - 0.04)
            if g1 - g0 < 0.03:
                continue
            uu = np.clip((g - g0) / (g1 - g0), 0, 1)
            on = (g > g0) & (g < g1)
            prof = np.exp(-(((r - R * rf) / wd) ** 2))
            a.append(0.38 * env[i] * on * prof * np.sin(np.pi * uu) ** 0.7 * dry(tex, np.clip((r - R * rf) / (3 * wd), -1, 1), g * 0.85 + rf, 0.25 + 0.3 * (1 - uu)))
        if i <= 2:  # 笔锋的亮点
            ha = math.radians(-half + SLASH_ARC * hd)
            hx, hy = cx + (R - 4) * math.cos(ha), cy + (R - 4) * math.sin(ha)
            a.append(0.9 * env[i] * np.exp(-((np.hypot(X - hx, Y - hy) / 4.5) ** 2)))
        if 2 <= i <= 4:  # 火星：收笔时从笔锋顺着挥的方向甩出去、往外飘
            ha = math.radians(half)
            tk = (i - 2) / 2
            tan = np.array([-math.sin(ha), math.cos(ha)])
            nrm = np.array([math.cos(ha), math.sin(ha)])
            for ds, d1, sz, out_k in sparks:
                p0 = np.array([cx, cy]) + nrm * (R + 5 + 6 * ds) + tan * 6 * ds
                dirv = tan + nrm * out_k
                dirv /= np.linalg.norm(dirv)
                p1 = p0 + dirv * d1 * (0.3 + 0.7 * tk)
                p_tail = p1 - dirv * (8 * (1 - tk) + 3)
                a.append(0.85 * (1 - 0.7 * tk) * streak(X, Y, p_tail[0], p_tail[1], p1[0], p1[1], sz))
        out.append(frame_white(soft_union(*a), 9710 + i))
    return out


# ============================================================== 击杀墨花（画在地上）


def make_kill_ink() -> list[Image.Image]:
    """墨滴砸在地上开成一朵墨花：先是一颗浓墨点，砸开出八九片花瓣、几片带尖，四周甩出带拖尾的墨点；
    末两帧落定：拖尾没了，花瓣边洇开一点，中间最浓。焦墨、普通混合，已按地面透视压扁，末帧留着。"""
    w = h = 192
    cx, cy = 96.0, 96.0
    X, Y = grid(w, h)
    rng = np.random.default_rng(9801)
    gx, gy = X - cx, (Y - cy) / FLAT  # 地面坐标
    r = np.hypot(gx, gy)
    th = np.arctan2(gy, gx)
    R0 = 30.0
    petals = [(2 * math.pi * (k + rng.uniform(-0.25, 0.25)) / 9, rng.uniform(0.18, 0.42), rng.uniform(0.22, 0.4)) for k in range(9)]
    spikes = [(rng.uniform(0, 2 * math.pi), rng.uniform(1.45, 1.9)) for _ in range(5)]
    drops = [(rng.uniform(0, 2 * math.pi), rng.uniform(1.7, 3.2), rng.uniform(1.6, 4.0)) for _ in range(11)]
    nz = V.noise(rng, X.shape, 6.0 * SS)
    lob = np.zeros_like(r)
    for ang, amp, wid in petals:
        dth = np.angle(np.exp(1j * (th - ang)))
        lob = np.maximum(lob, amp * np.exp(-((dth / wid) ** 2)))
    spk = np.zeros_like(r)
    for ang, reach in spikes:
        dth = np.angle(np.exp(1j * (th - ang)))
        spk = np.maximum(spk, (reach - 1.0) * np.exp(-((dth / 0.06) ** 2)))
    rough = 0.06 * V.angular_noise(np.random.default_rng(9802), th, harmonics=(5, 7, 11, 13), amp=1.0)
    grow = [0.42, 0.86, 1.0, 1.03, 1.04, 1.04]
    lobe_k = [0.15, 0.65, 1.0, 1.0, 1.0, 1.0]
    out = []
    for i in range(6):
        edge = R0 * grow[i] * (1.0 + lobe_k[i] * (lob + spk) + rough)
        body = smoothstep(edge + 1.2, edge - 1.2, r)
        dens = 0.8 + 0.08 * nz + 0.1 * smoothstep(edge - 6, edge - 1, r)  # 边上积墨深一点
        if i >= 4:
            dens = dens - 0.06 * (i - 3)
            body = np.maximum(body, 0.16 * smoothstep(edge + 4.0, edge, r))  # 洇开的一圈
        a = body * np.clip(dens, 0, 1)
        for ang, dist, sz in drops:
            if i == 0:
                continue
            k = [0, 0.42, 0.76, 0.95, 1.0, 1.0][i]
            d = R0 * dist * k
            px, py = cx + d * math.cos(ang), cy + d * math.sin(ang) * FLAT
            elong = [0, 2.2, 1.7, 1.25, 1.0, 1.0][i]
            ux, uy = math.cos(ang), math.sin(ang) * FLAT
            nrm = math.hypot(ux, uy)
            ux, uy = ux / nrm, uy / nrm
            along = (X - px) * ux + (Y - py) * uy
            perp = -(X - px) * uy + (Y - py) * ux
            drop = smoothstep(1.0 + 0.3, 1.0 - 0.3, np.hypot(along / (sz * elong), perp / sz))
            a = np.maximum(a, 0.9 * drop)
            if i <= 3:  # 拖尾：从花里拉出来的一道细墨
                tail_len = d - R0 * grow[i]
                if tail_len > 2:
                    c, u = needle(X, Y, px, py, math.atan2(-uy, -ux), tail_len, sz * 0.55, w1=0.2, taper=1.5)
                    a = np.maximum(a, [0, 0.75, 0.55, 0.3][i] * c)
        out.append(frame_ink(a, 9810 + i))
    return out


# ============================================================== 冲击波（贴地亮环，已压扁）

SHOCK_W, SHOCK_H = 512, 320
SHOCK_R = 220.0  # 末帧亮环的半径（地面坐标，像素）；碎屑再往外最多十几像素，不出画布


def make_shockwave() -> list[Image.Image]:
    """贴地的一圈亮边由小扩大：前沿亮而薄、后面拖一层淡光；越扩越碎（沿圈的飞白越来越多）、越淡；第 0 帧中间一下闪。
    地面坐标里画圆，按透视压扁成高 ÷ 宽 0.62。白色，建议染 #FFE2A8（可按五行色染）。"""
    X, Y = grid(SHOCK_W, SHOCK_H)
    cx, cy = SHOCK_W / 2, SHOCK_H / 2
    rng = np.random.default_rng(9901)
    tex = W.ptex(rng, ns=16, nt=1024, along=16.0, across=0.8)
    gx, gy = X - cx, (Y - cy) / FLAT
    rho = np.hypot(gx, gy)
    th = np.mod(np.arctan2(gy, gx) / (2 * math.pi), 1.0)
    grow = [0.16, 0.38, 0.58, 0.75, 0.89, 1.0]
    wr = [9.0, 9.5, 8.5, 7.5, 6.5, 5.5]
    env = [1.0, 0.92, 0.74, 0.54, 0.34, 0.16]
    dk = [0.06, 0.16, 0.28, 0.4, 0.52, 0.64]
    debris = [(rng.uniform(0, 1), rng.uniform(4, 16), rng.uniform(0.9, 1.6)) for _ in range(26)]
    out = []
    for i in range(6):
        R = SHOCK_R * grow[i]
        q = (rho - R) / wr[i]
        edge = np.exp(-(q**2) * 1.4)
        trail = 0.38 * smoothstep(-5.0, -0.2, q) * (q < 0.3) * np.exp(np.minimum(q, 0) / 2.4)
        m = dry(tex, np.clip(q / 2.5, -1, 1), th, dk[i])
        a = [env[i] * (edge + trail) * m]
        if i == 0:  # 中间一下闪：碎成一根根放射的亮丝，不是平滑的圆
            spokes = np.clip(0.5 + V.angular_noise(np.random.default_rng(9902), np.arctan2(gy, gx), harmonics=(9, 13, 17, 23, 29, 37), amp=1.8), 0, 1)
            a.append(0.72 * np.exp(-((rho / (R * 0.85)) ** 2)) * (0.35 + 0.65 * spokes))
        if i >= 1:
            for t0, ahead, sz in debris:
                ang = 2 * math.pi * t0
                d = R + ahead * (0.6 + 0.4 * i / 5)
                a.append(0.7 * env[i] * dot(X, Y, cx + d * math.cos(ang), cy + d * math.sin(ang) * FLAT, sz))
        out.append(frame_white(soft_union(*a), 9910 + i))
    return out


# ============================================================== 清单与输出

# 名字: (生成函数, 画布 (w, h), 锚点, blend, tint, 颜色说明, 附加 meta)
BATCH1 = {
    "hit_metal": (make_hit_metal, (128, 128), (0.5, 0.5), "add", True, "white", {"element": "metal", "note": "命中·金：细长十字闪 + 斜的剑痕碎光"}),
    "hit_wood": (make_hit_wood, (128, 128), (0.5, 0.5), "add", True, "white", {"element": "wood", "note": "命中·木：叶片、纸屑状的亮片翻飞出去"}),
    "hit_water": (make_hit_water, (128, 128), (0.5, 0.5), "add", True, "white", {"element": "water", "note": "命中·水：一圈水花，冰晶溅开"}),
    "hit_fire": (make_hit_fire, (128, 128), (0.5, 0.5), "add", True, "white", {"element": "fire", "note": "命中·火：小燃爆，火舌往上卷"}),
    "hit_earth": (make_hit_earth, (128, 128), (0.5, 0.5), "add", True, "white", {"element": "earth", "note": "命中·土：闷的爆点，碎石往下落"}),
    "crit": (make_crit, (192, 192), (0.5, 0.5), "add", False, "full", {"note": "暴击：四角星大闪 + 两道交叉笔锋，白金 #FFF3D6，第 0 帧最大最亮"}),
    "slash": (make_slash, (SLASH_W, SLASH_H), (SLASH_C[0] / SLASH_W, SLASH_C[1] / SLASH_H), "add", True, "white",
              {"points": "+x", "radius_px": int(SLASH_R), "angle_deg": int(SLASH_ARC),
               "note": "刀光：月牙笔锋沿弧从上扫到下，扇形朝 +X 张开 120°，锚点在弧心；radius_px 是外沿半径，按扫击半径缩放、转到出手方向"}),
    "kill_ink": (make_kill_ink, (192, 192), (0.5, 0.5), "normal", False, "jiao", {"flat": FLAT, "hold_last": True,
                                                                                   "note": "击杀墨花：焦墨、普通混合，画在地上（已压扁），末帧留着"}),
    "shockwave": (make_shockwave, (SHOCK_W, SHOCK_H), (0.5, 0.5), "add", True, "white", {"flat": FLAT, "radius_px": int(SHOCK_R), "tint_hint": SHOCK_TINT,
                                                                                        "note": "冲击波：贴地亮环由小扩大，越扩越碎越淡；已压扁，radius_px 是末帧的横向半径；建议染 #FFE2A8"}),
}
BATCHES = {"b1": BATCH1}


def build(batch: dict) -> dict[str, list[Image.Image]]:
    return {name: spec[0]() for name, spec in batch.items()}


def meta_entries(batch: dict, frames: dict[str, list[Image.Image]]) -> dict:
    files = {}
    for name, (_, size, anc, blend, tint, color, extra) in batch.items():
        n = len(frames[name])
        for i, img in enumerate(frames[name]):
            assert img.size == size, (name, img.size, size)
            files[f"{name}_{i}.png"] = {"size": list(size), "anchor": [float(anc[0]), float(anc[1])], "color": color, "blend": blend, "tint": tint,
                                        "anim": name, "frame": i, "frames": n, "fps": FPS, "loop": False, "kind": "fx", **extra}
    return files


def write(frames: dict[str, list[Image.Image]], batch: dict, out: Path = OUT, name: str = "vfx", generator: str = GENERATOR) -> dict:
    """写 PNG 和 meta.json（name 决定图集里的帧名前缀）。meta 里别的批次的条目保留。"""
    out.mkdir(parents=True, exist_ok=True)
    meta_path = out / "meta.json"
    files = json.loads(meta_path.read_text(encoding="utf-8"))["files"] if meta_path.exists() else {}
    files.update(meta_entries(batch, frames))
    for key, imgs in frames.items():
        for i, img in enumerate(imgs):
            V.save_png(img, out / f"{key}_{i}.png")
    meta = {"name": name, "generator": generator, "format": "PNG RGBA，直通（非预乘）alpha", "px_per_unit": PPU, "files": files}
    meta_path.write_text(V.dump_json(meta), encoding="utf-8")
    return meta


def main() -> None:
    t0 = time.perf_counter()
    for key, batch in BATCHES.items():
        frames = build(batch)
        write(frames, batch)
        import vfx_frames_review as R  # noqa: PLC0415  审图单独一个文件

        R.strip_sheet(key, batch, frames, REVIEW / f"vfx_frames_{key}.png")
        R.ingame(key, batch, frames, REVIEW / f"vfx_frames_{key}_ingame.png")
        print(f"{key}: {sum(len(v) for v in frames.values())} 帧  {time.perf_counter() - t0:.1f}s")


if __name__ == "__main__":
    main()
