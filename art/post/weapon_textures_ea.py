#!/usr/bin/env python3
"""提灯夜行 · 抢先体验五件新法器的贴图（docs/BALANCE.md 6.3 节各件的“画面”）。只出桌面版 2 倍，Pillow + numpy。

帧名照 weapons/* 的写法：weapons/<名字>_<帧号>（帧号从 0 起，一位数），和 vfx 图集一起打包（$A/weapons_ea）。
动画帧的约定同 vfx_frames.py：一次性的按 24 帧/秒，meta 写 anim、frame、frames、fps、loop；叠加帧最亮处 alpha 0.8、
边缘是飞白和干笔；可染的 RGB 恒为白；有方向的朝 +X。

大小按 1080p 下约一比一定（1080p 下 1 世界单位 ≈ 2.57 屏幕像素），不靠游戏里放大三四倍；单帧不超过 1024²。
跟半径走的帧在 meta 里写 radius_px（外沿半径），游戏按“想要的半径 × 2.57 ÷ radius_px”的屏幕比例缩放，
换成世界单位就是 想要的半径 ÷（radius_px ÷ pxPerUnit）。

铜钱剑（金，BALANCE 6.3：扫击半径 140–170，天罡 200）：
  weapons/coin_slash_0..5   挥击：120° 扇形的铜钱剑气，朝 +X 张开、弧心是锚点（同 vfx/slash 的约定，但独立出图）；
                            radius_px 440（1080p 下 171 单位一比一）；笔锋扫过处刃口闪出一枚枚铜钱的影子；白色可染
  weapons/coin_spark_0..4   命中的铜钱火星（约 16 世界单位）：接触点一闪，火星顺着入射方向（+X）溅出去，
                            两枚小铜钱翻着飞；自带铜金色、不染
  weapons/coin_whirl_0..5   天罡：周身一圈旋风刀光（半径 200），0.25 秒；radius_px 464（1080p 下放大约 1.1 倍）；白色可染
  weapons/coin_cross_0..3   天罡的再斩：目标身上的十字斩痕（约 30），0.15 秒；白色可染

产物：art/out/assets@2x/weapons_ea/*.png + meta.json（name: weapons）
审图：art/out/review@2x/weapons_ea_<件>.png（纸色底 / 夜色底的帧条）、weapons_ea_<件>_ingame.png（1080p 合成）

用法（仓库根目录）：
  art/.venv/bin/python art/post/weapon_textures_ea.py
  art/.venv/bin/python art/post/test_weapon_textures_ea.py
"""

from __future__ import annotations

import math
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import vfx_frames as F  # noqa: E402  它先把密度定成 2 倍，再导入 style / vfx_textures

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

V, W, S = F.V, F.W, F.S
OUT = V.OUT / "assets@2x" / "weapons_ea"
REVIEW = F.REVIEW
GENERATOR = "art/post/weapon_textures_ea.py"
SS = F.SS
grid, smoothstep, soft_union, needle, streak, dry, ease_out = F.grid, F.smoothstep, F.soft_union, F.needle, F.streak, F.dry, F.ease_out

COIN_TINT = "#F2C46A"  # 铜金：铜钱剑的刀光、旋风、再斩建议染这个
COPPER = [(0.0, "#B06A26"), (0.45, "#E5A042"), (0.75, "#F6CF74"), (1.0, "#FFF4D8")]  # 热度 0 → 1：暗铜 → 烧白


# ============================================================== 基础


union_heat = F.union_heat


def frame_color(a_ss: np.ndarray, heat_ss: np.ndarray, seed: int, palette=COPPER, peak: float = F.PEAK) -> Image.Image:
    return F.frame_color(a_ss, heat_ss, seed, palette, peak)


K1080 = 1080 / 420  # 1080p 下每世界单位的屏幕像素（视野高 420 单位）


def tiled(w: int, h: int, fn, rows: int = 64) -> np.ndarray:
    """大画布按行分条算超采样的亮度场，省内存：fn(acc) 往 F.Acc 里画（坐标是最终像素），每条缩小后拼起来。
    返回最终像素大小的亮度场（同 frame_white 里缩小后的那一步）。"""
    xs = (np.arange(w * SS) + 0.5) / SS
    out = np.zeros((h, w))
    for y0 in range(0, h, rows):
        y1 = min(h, y0 + rows)
        ys = y0 + (np.arange((y1 - y0) * SS) + 0.5) / SS
        acc = F.Acc(*np.meshgrid(xs, ys))
        fn(acc)
        out[y0:y1] = V.downsample(acc.a, SS)
    return out


def finish_white(a: np.ndarray, seed: int, peak: float = F.PEAK) -> Image.Image:
    """已缩小的亮度场 → 白色叠加帧（frame_white 的后半段：软饱和到 peak、蓝噪声抖动、四边为 0）。"""
    a = peak * np.tanh(1.25 * np.clip(a, 0.0, 1.0)) / math.tanh(1.25)
    a8 = V.dither_alpha(a, np.random.default_rng(seed))
    a8[a < 0.004] = 0
    a8[0, :] = a8[-1, :] = a8[:, 0] = a8[:, -1] = 0
    return V.to_rgba8(V.WHITE, None, a8)


def coin_glyph(X, Y, px, py, rc, squash, tilt, line=1.4):
    """一枚铜钱的亮线描（外圆内方）：外圈一道、方孔一圈，钱面淡淡一层。squash 是翻转后看到的宽度比例（翻到侧面看不见方孔）。"""
    ca, sa = math.cos(tilt), math.sin(tilt)
    u = (X - px) * ca + (Y - py) * sa
    v = -(X - px) * sa + (Y - py) * ca
    ax = max(rc * squash, 0.8)
    e = np.hypot(u / ax, v / rc)
    grad = np.hypot(u / ax**2, v / rc**2) / np.maximum(e, 1e-6)
    d_rim = (e - 1.0) / np.maximum(grad, 1e-6)  # 到椭圆边的近似距离（里负外正）
    ring = smoothstep(line + 0.5, line - 0.5, np.abs(d_rim + line))
    d_hole = np.maximum(np.abs(u) - 0.34 * ax, np.abs(v) - 0.34 * rc)
    hole = smoothstep(0.9 * line + 0.5, 0.9 * line - 0.5, np.abs(d_hole)) * (squash > 0.4)
    face = smoothstep(0.5, -0.5, d_rim) * smoothstep(-0.5, 0.5, d_hole)
    return np.clip(0.95 * ring + 0.8 * hole + 0.22 * face, 0, 1)


def crescent(r, g, *, head: float, tail: float, rim, thick: float, tex, t_off: float, dryk: float, edge_w: float = 1.7):
    """沿弧的月牙笔锋（刀光、旋风共用）。g 是像素沿弧的位置（度，已展开），head > tail；rim 是外沿半径（可随位置变）。
    返回 (亮度, 沿弧 0..1)。外沿一道利的亮线（半宽约 edge_w 像素），往里渐淡、起飞白；最厚处在笔锋后面一点，两头收尖。"""
    span = max(head - tail, 1e-3)
    v = (g - tail) / span
    inside = (v > 0) & (v < 1)
    vc = np.clip(v, 0, 1)
    shape = np.sin(np.pi * vc**1.6) ** 0.8
    rr = rim(vc) if callable(rim) else rim
    T = thick * shape
    s = (rr - r) / np.maximum(T, 0.5)
    body = smoothstep(rr + 0.6 * edge_w, rr - 0.6 * edge_w, r) * smoothstep(1.0, 0.5, s) * np.exp(-1.5 * np.clip(s, 0, None))
    edge = np.exp(-(((r - (rr - edge_w)) / edge_w) ** 2)) * shape**0.4
    k = dryk + 0.45 * (1 - vc) ** 2 + 0.3 * np.clip(s, 0, 1) ** 2
    m = dry(tex, np.clip(2 * s - 1, -1, 1), g / 360.0 + t_off, k)
    return inside * np.maximum(body, 0.95 * edge) * m, vc


# ============================================================== 铜钱剑：命中的铜钱火星


def coin_shape(X, Y, px, py, rc, squash, tilt):
    """一枚翻转中的铜钱（外圆内方）：返回 (覆盖度, 边圈)。squash 是看到的宽度比例（翻到侧面时变扁）。"""
    ca, sa = math.cos(tilt), math.sin(tilt)
    u = (X - px) * ca + (Y - py) * sa
    v = -(X - px) * sa + (Y - py) * ca
    ax = max(rc * squash, 0.6)
    e = np.hypot(u / ax, v / rc)
    aa = 0.6 / ax
    disk = smoothstep(1 + aa, 1 - aa, e)
    hole = smoothstep(1.0 + 0.6 / (0.36 * ax), 1.0 - 0.6 / (0.36 * ax), np.maximum(np.abs(u) / (0.36 * ax), np.abs(v) / (0.36 * rc)))
    cover = disk * (1 - hole * (squash > 0.55))  # 翻到侧面看不见方孔
    rim = disk * smoothstep(0.55, 0.85, e)
    return cover, rim


SPARK_W, SPARK_H = 128, 128
SPARK_C = (48.0, 60.0)  # 接触点（锚点）：偏左一点，火星主要往 +X 溅


def make_coin_spark() -> list[Image.Image]:
    """铜钱火星：接触点一下小亮星；九粒火星顺着入射方向（+X）扇形溅出去、往下坠，两粒往回崩，头亮（烧白）尾暗（铜红）；
    两枚小铜钱翻着飞出去（外圆内方，翻到侧面变扁，正面朝外时边上一闪）。自带铜金色，不染。"""
    X, Y = grid(SPARK_W, SPARK_H)
    cx, cy = SPARK_C
    rng = np.random.default_rng(9871)
    sparks = []
    for k in range(11):
        back = k >= 9
        ang = math.radians(180 + rng.uniform(-50, 50) if back else (k - 4) * 12.5 + rng.uniform(-5, 5))
        sparks.append((ang, rng.uniform(26, 40) * (0.5 if back else 1.0), rng.uniform(0.9, 1.3)))
    coins = [(math.radians(rng.uniform(-30, -12)), 24.0, rng.uniform(0, math.pi), rng.uniform(8, 11), rng.uniform(-0.6, 0.6)),
             (math.radians(rng.uniform(12, 30)), 20.0, rng.uniform(0, math.pi), -rng.uniform(8, 11), rng.uniform(-0.6, 0.6))]
    out = []
    for i in range(5):
        t = i / 4
        parts: list = []
        if i <= 1:  # 接触点的小亮星
            for k in range(4):
                L = [15.0, 10.0][i] * (1.0 if k % 2 == 0 else 0.6)
                c, _ = needle(X, Y, cx, cy, k * math.pi / 2 + 0.3, L, [2.2, 1.5][i], taper=1.6)
                parts.append(([1.0, 0.7][i] * c, 1.0))
            parts.append(([1.0, 0.6][i] * np.exp(-((np.hypot(X - cx, Y - cy) / [4.0, 3.0][i]) ** 2)), 1.0))
        for ang, d1, sz in sparks:
            if i == 0:
                continue
            d = 4 + d1 * ease_out(t, 1.6)
            x1, y1 = cx + d * math.cos(ang), cy + d * math.sin(ang) + 9.0 * t * t
            back = 10 * (1 - t) + 4
            x0, y0 = cx + (d - back) * math.cos(ang), cy + (d - back) * math.sin(ang) + 9.0 * max(t - 0.15, 0.0) ** 2
            fade = 1 - 0.85 * t
            parts.append((fade * streak(X, Y, x0, y0, x1, y1, sz), 0.95 - 0.5 * t))
            parts.append((fade * F.dot(X, Y, x1, y1, 1.1 * sz), 1.0))  # 火星头
        for ang, d1, ph, spin, tilt in coins:
            if i == 0:
                continue
            d = 6 + d1 * ease_out(t, 1.5)
            px, py = cx + d * math.cos(ang), cy + d * math.sin(ang) + 7.0 * t * t
            sq = max(0.18, abs(math.cos(ph + spin * t * 0.25)))
            cover, rim = coin_shape(X, Y, px, py, 5.5, sq, tilt + 0.8 * t)
            fade = 1 - 0.75 * t
            parts.append((fade * 0.42 * cover, 0.5))
            parts.append((fade * 0.85 * rim, 0.78))
            if sq > 0.8:  # 正面朝外时边上一闪
                gx, gy = px - 2.8 * math.cos(tilt), py - 2.8
                for k in range(2):
                    c, _ = needle(X, Y, gx, gy, k * math.pi / 2, 4.0, 0.9, taper=1.5)
                    c2, _ = needle(X, Y, gx, gy, k * math.pi / 2 + math.pi, 4.0, 0.9, taper=1.5)
                    parts.append((fade * (sq - 0.8) / 0.2 * np.maximum(c, c2), 1.0))
        a, heat = union_heat(parts)
        out.append(frame_color(a, heat, 9880 + i))
    return out


# ============================================================== 铜钱剑：挥击（扇形剑气）

CSLASH_W, CSLASH_H = 512, 896
CSLASH_C = (16.0, 448.0)  # 弧心（锚点）
CSLASH_R = 440.0  # 外沿半径（像素）= 扫击半径；1080p 下 171 世界单位一比一（140 时缩到 0.82）
CSLASH_ARC = 120.0
CSLASH_COINS = (0.14, 0.32, 0.5, 0.68, 0.86)  # 刃口上铜钱影子的位置（沿弧 0..1）


def make_coin_slash() -> list[Image.Image]:
    """铜钱剑的挥击：120° 扇形的铜钱剑气，朝 +X 张开、弧心是锚点，笔锋沿弧从上往下扫（图里 y 向下）。
    0–2 帧：月牙笔锋扫过整个扇面——外沿一道利的亮线，往里渐淡、起飞白，身后十几道速度线，扇面上一层淡淡的风痕；
    笔锋扫过的地方，刃口上一枚枚铜钱的影子闪出来（外圆内方）。3–5 帧：尾巴追上笔锋、越收越薄、碎成干笔丝，
    铜钱影子翻着往外飘、变淡，收笔处甩出几点火星。白色，可染（建议铜金 #F2C46A）。"""
    w, h = CSLASH_W, CSLASH_H
    cx, cy = CSLASH_C
    R, arc = CSLASH_R, CSLASH_ARC
    half = arc / 2
    rng = np.random.default_rng(9811)
    tex = W.ptex(rng, ns=40, nt=2048, along=36.0, across=0.6)
    tex_w = W.ptex(rng, ns=160, nt=1024, along=40.0, across=0.7)  # 风痕：更细的纹
    # 笔锋、尾巴沿弧的位置（0..1 是扇形的两条边）：起笔和收笔各探出扇形一点点，两头收尖的地方落在扇形外，扇面整个都扫得到
    head = [0.32, 0.8, 1.05, 1.05, 1.05, 1.05]
    tail = [-0.1, -0.08, 0.0, 0.3, 0.56, 0.8]
    thick = [52.0, 82.0, 92.0, 76.0, 54.0, 32.0]
    env = [0.95, 1.0, 1.0, 0.8, 0.52, 0.26]
    dryk = [0.06, 0.04, 0.08, 0.26, 0.42, 0.56]
    sheen = [0.07, 0.14, 0.16, 0.09, 0.04, 0.0]  # 扇面的风痕
    lines = [(rng.uniform(0.4, 0.93), rng.uniform(0.0, 0.5), rng.uniform(0.25, 0.7), rng.uniform(1.2, 2.6)) for _ in range(14)]
    coins = [(gk, rng.uniform(0, math.pi), rng.uniform(1.4, 2.2) * float(rng.choice([-1.0, 1.0])), rng.uniform(-1.5, 1.5)) for gk in CSLASH_COINS]
    sparks = [(rng.uniform(-0.5, 0.5), rng.uniform(22, 36), rng.uniform(1.4, 2.2), rng.uniform(0.15, 0.55)) for _ in range(10)]
    coin_age = [0.95, 0.85, 0.6, 0.36, 0.16]
    out = []
    for i in range(6):
        hd, tl = head[i], tail[i]
        span = max(hd - tl, 1e-3)

        def paint(acc, i=i, hd=hd, tl=tl, span=span):
            X, Y = acc.X, acc.Y
            dx, dy = X - cx, Y - cy
            r = np.hypot(dx, dy)
            g = (np.degrees(np.arctan2(dy, dx)) + half) / arc  # 沿弧 0（起笔，上）→ 1（收笔，下）
            on = (g > tl) & (g < hd) & (r < R + 4)
            m = on & (r > R - thick[i] * 1.6 - 4)  # 月牙只在外沿往里一条带子里
            if m.any():
                c, _ = crescent(r[m], g[m] * arc, head=hd * arc, tail=tl * arc, rim=R, thick=thick[i], tex=tex, t_off=0.11 * i, dryk=dryk[i], edge_w=2.6)
                acc.add(m, env[i] * c)
            for rf, a0, ln, wd in lines:  # 速度线：弧里细的、跟在笔锋后面
                g0 = max(tl + span * a0, 0.0)
                g1 = min(g0 + span * ln, hd - 0.04 - 0.15 * (1 - rf), 1.0)  # 越靠里的越落后：前沿是一道往后弯的弧
                if g1 - g0 < 0.03:
                    continue
                m = (g > g0) & (g < g1) & (np.abs(r - R * rf) < 4 * wd)
                if not m.any():
                    continue
                rm, gm = r[m], g[m]
                uu = (gm - g0) / (g1 - g0)
                prof = np.exp(-(((rm - R * rf) / wd) ** 2))
                acc.add(m, 0.38 * env[i] * prof * np.sin(np.pi * uu) ** 0.7
                        * dry(tex, np.clip((rm - R * rf) / (3 * wd), -1, 1), gm * 0.85 + rf, 0.25 + 0.3 * (1 - uu)))
            m = on & (r > 0.22 * R)
            if sheen[i] > 0 and m.any():  # 扇面上一层淡的风痕：笔锋身后最浓，往尾巴、往弧心淡；到扇形两边淡掉
                rm = r[m]
                vv = (g[m] + 0.15 * (1 - rm / R) - tl) / span  # 同速度线：越靠里越落后
                wv = smoothstep(0.0, 0.55, vv) * smoothstep(1.0, 0.88, vv) * smoothstep(-0.06, 0.08, g[m]) * smoothstep(1.06, 0.92, g[m])
                wr = smoothstep(0.22 * R, 0.9 * R, rm) * smoothstep(R + 1.0, R - 5.0, rm)
                st = dry(tex_w, np.clip(2 * rm / R - 1, -1, 1), g[m] * 0.6 + 0.5, 0.4 + 0.3 * (1 - vv))
                acc.add(m, sheen[i] * wv * wr * (0.3 + 0.7 * st))
            if i <= 2:  # 笔锋：一点亮，带一个顺着弧的四芒小星
                ha = math.radians(-half + arc * hd)
                hx, hy = cx + (R - 7) * math.cos(ha), cy + (R - 7) * math.sin(ha)
                sl = acc.window(hx - 40, hy - 40, hx + 40, hy + 40)
                Xs, Ys = X[sl], Y[sl]
                acc.add(sl, 0.9 * env[i] * np.exp(-((np.hypot(Xs - hx, Ys - hy) / 7.0) ** 2)))
                for k, L in enumerate((30.0, 14.0, 30.0, 14.0)):
                    cv, _ = needle(Xs, Ys, hx, hy, ha + math.pi / 2 * (k + 1), L, 2.4, taper=1.6)
                    acc.add(sl, 0.85 * env[i] * cv)
            for gk, ph, spin, jit in coins:  # 刃口上的铜钱影子：笔锋扫过时闪出来，之后翻着往外飘
                born = next((j for j in range(6) if head[j] >= gk + 0.02), 6)
                age = i - born
                if age < 0 or age >= len(coin_age):
                    continue
                ang = math.radians(-half + arc * gk + jit + 1.2 * age)
                rad = R + 4 + [0.0, 6.0, 13.0, 20.0, 26.0][age]  # 从刃口外面一点闪出来，往外飘
                px, py = cx + rad * math.cos(ang), cy + rad * math.sin(ang)
                rc = 12.0 * (1 + 0.03 * age)
                sl = acc.window(px - rc - 4, py - rc - 4, px + rc + 4, py + rc + 4)
                sq = max(0.15, abs(math.cos(ph + spin * age * 0.5)))
                acc.add(sl, coin_age[age] * coin_glyph(X[sl], Y[sl], px, py, rc, sq, ang + ph, line=1.6))
            if 2 <= i <= 4:  # 火星：收笔时从笔锋顺着挥的方向甩出去、往外飘
                ha = math.radians(half)
                tk = (i - 2) / 2
                tan = np.array([-math.sin(ha), math.cos(ha)])
                nrm = np.array([math.cos(ha), math.sin(ha)])
                for ds, d1, sz, out_k in sparks:
                    p0 = np.array([cx, cy]) + nrm * (R + 6 + 10 * ds) + tan * 12 * ds
                    dirv = tan + nrm * out_k
                    dirv /= np.linalg.norm(dirv)
                    p1 = p0 + dirv * d1 * (0.3 + 0.7 * tk)
                    p_tail = p1 - dirv * (16 * (1 - tk) + 6)
                    lo, hi = np.minimum(p1, p_tail) - 6, np.maximum(p1, p_tail) + 6
                    sl = acc.window(lo[0], lo[1], hi[0], hi[1])
                    acc.add(sl, 0.85 * (1 - 0.7 * tk) * streak(X[sl], Y[sl], p_tail[0], p_tail[1], p1[0], p1[1], sz))

        out.append(finish_white(tiled(w, h, paint), 9815 + i))
    return out


# ============================================================== 铜钱剑：天罡旋风

WHIRL_SIZE = 1024
WHIRL_R = 464.0  # 外沿半径（像素）= 旋风半径；1080p 下 200 世界单位 ≈ 514 像素，游戏里放大约 1.1 倍；火星再往外飘不到 40 像素


def make_coin_whirl() -> list[Image.Image]:
    """天罡：周身一圈旋风刀光。三道主刀光（月牙笔锋，头亮、尾巴拖细、往里旋）相隔 120°，顺时针转（图里 y 向下），
    里圈三道淡一些的错开 60°；弧里十几道速度线，圈里一层淡淡的旋涡风痕；三道主刀光的笔锋上各带一枚铜钱的影子。
    前两帧从里往外张开到外沿，末两帧越转越慢、碎成干笔丝，铜钱影子甩出去、笔锋甩出火星。白色，可染（建议铜金 #F2C46A）。"""
    size = WHIRL_SIZE
    cx = cy = size / 2
    R = WHIRL_R
    q = R / 192.0  # 相对旧版（半径 192）的放大
    rng = np.random.default_rng(9851)
    tex = W.ptex(rng, ns=40, nt=4096, along=60.0, across=0.6)
    tex_w = W.ptex(rng, ns=160, nt=2048, along=50.0, across=0.7)  # 旋涡风痕：更细的纹
    spin = [0.0, 62.0, 118.0, 166.0, 204.0, 232.0]  # 转过的角度（越转越慢）
    grow = [0.6, 0.9, 1.0, 1.0, 1.0, 1.0]
    length = [70.0, 150.0, 178.0, 178.0, 150.0, 108.0]
    thick = [20.0 * q, 31.0 * q, 34.0 * q, 29.0 * q, 21.0 * q, 12.0 * q]  # 比旧版薄两成：半径翻倍后整圈不至于太满
    env = [0.9, 1.0, 1.0, 0.8, 0.52, 0.26]
    dryk = [0.06, 0.04, 0.08, 0.24, 0.4, 0.55]
    vortex = [0.0, 0.1, 0.12, 0.07, 0.03, 0.0]  # 圈里的旋涡风痕
    blades = [(a0 + rng.uniform(-6, 6), rf, br, off) for a0, rf, br, off in
              ((0.0, 1.0, 1.0, 0.0), (120.0, 1.0, 1.0, 0.31), (240.0, 1.0, 1.0, 0.62), (60.0, 0.72, 0.45, 0.15), (180.0, 0.72, 0.45, 0.47), (300.0, 0.72, 0.45, 0.78))]
    lines = [(rng.uniform(0.42, 0.9), rng.uniform(0, 360), rng.uniform(40, 100), rng.uniform(1.4, 2.8)) for _ in range(15)]
    sparks = [(int(rng.integers(0, 3)), rng.uniform(-6, 6), rng.uniform(24, 40), rng.uniform(1.6, 2.4), rng.uniform(0.2, 0.45)) for _ in range(14)]
    coins = [(rng.uniform(0, math.pi), rng.uniform(1.4, 2.2)) for _ in range(3)]
    coin_env = [0.0, 0.9, 0.95, 0.75, 0.45, 0.2]
    out = []
    for i in range(6):

        def paint(acc, i=i):
            X, Y = acc.X, acc.Y
            dx, dy = X - cx, Y - cy
            r = np.hypot(dx, dy)
            th = np.degrees(np.arctan2(dy, dx))  # −180..180，顺时针为正
            for a0, rf, br, off in blades:
                hd = a0 + spin[i]
                L = length[i] * (1.0 if rf == 1.0 else 0.8)
                rim_r = R * grow[i] * rf
                m = (r < rim_r + 4) & (r > 0.86 * rim_r - thick[i] * rf * 1.6 - 4)
                if m.any():
                    g = hd - np.mod(hd - th[m], 360.0)  # 把像素的角度展开到 (hd − 360, hd]，笔锋在 hd，尾巴在 hd − L
                    c, _ = crescent(r[m], g, head=hd, tail=hd - L, rim=lambda v, rr=rim_r: rr * (0.86 + 0.14 * v), thick=thick[i] * rf,
                                    tex=tex, t_off=off, dryk=dryk[i], edge_w=2.8)
                    acc.add(m, env[i] * br * c)
                if i <= 2 and rf == 1.0:  # 笔锋的亮点
                    ha = math.radians(hd)
                    hx, hy = cx + (rim_r - 10) * math.cos(ha), cy + (rim_r - 10) * math.sin(ha)
                    sl = acc.window(hx - 30, hy - 30, hx + 30, hy + 30)
                    acc.add(sl, 0.85 * env[i] * np.exp(-((np.hypot(X[sl] - hx, Y[sl] - hy) / 9.0) ** 2)))
            for rf, a0, ln, wd in lines:  # 速度线：跟着转
                hd = a0 + spin[i] * 0.9
                rr = R * grow[i] * rf
                m = np.abs(r - rr) < 4 * wd
                if not m.any():
                    continue
                g = hd - np.mod(hd - th[m], 360.0)
                uu = np.clip((g - (hd - ln)) / ln, 0, 1)
                rm = r[m]
                prof = np.exp(-(((rm - rr) / wd) ** 2))
                acc.add(m, 0.32 * env[i] * prof * np.sin(np.pi * uu) ** 0.7 * dry(tex, np.clip((rm - rr) / (3 * wd), -1, 1), g / 360.0 + rf, 0.3 + 0.3 * (1 - uu)))
            m = (r > 0.3 * R) & (r < R * grow[i] + 2)
            if vortex[i] > 0 and m.any():  # 圈里淡淡的旋涡风痕（螺旋的笔毛纹），让人看得出整圈都在砍
                rm = r[m]
                t_sp = (th[m] - spin[i] * 0.8) / 360.0 + 0.18 * rm / R
                wr = smoothstep(0.3 * R, 0.85 * R, rm) * smoothstep(R * grow[i] + 2, R * grow[i] - 8, rm)
                acc.add(m, vortex[i] * wr * (0.3 + 0.7 * dry(tex_w, np.clip(2 * rm / R - 1, -1, 1), t_sp + 0.37, 0.45)))
            for k, (ph, sp) in enumerate(coins):  # 主刀光笔锋上的铜钱影子：跟着转，第 3 帧起甩出去、翻着变淡
                if coin_env[i] <= 0:
                    continue
                a0 = blades[k][0]
                if i <= 3:  # 贴着笔锋外沿
                    ang = math.radians(a0 + spin[i] - 9.0)
                    rad = R * grow[i] + 4
                else:
                    ang = math.radians(a0 + spin[3] - 9.0 + [0, 0, 0, 0, 16.0, 26.0][i])
                    rad = R + 4 + [0, 0, 0, 0, 12.0, 20.0][i]
                px, py = cx + rad * math.cos(ang), cy + rad * math.sin(ang)
                rc = 13.0
                sl = acc.window(px - rc - 4, py - rc - 4, px + rc + 4, py + rc + 4)
                sq = max(0.15, abs(math.cos(ph + sp * i * 0.5)))
                acc.add(sl, coin_env[i] * coin_glyph(X[sl], Y[sl], px, py, rc, sq, ang + ph, line=1.7))
            if i >= 2:  # 火星：第 2 帧从三道主刀光的笔锋甩出去，之后直线飞、变淡
                tk = (i - 2) / 3
                for j, ds, d1, sz, out_k in sparks:
                    hd = math.radians(blades[j][0] + spin[2] + ds)
                    tan = np.array([-math.sin(hd), math.cos(hd)])
                    nrm = np.array([math.cos(hd), math.sin(hd)])
                    p0 = np.array([cx, cy]) + nrm * (R + 8)
                    dirv = tan + nrm * out_k
                    dirv /= np.linalg.norm(dirv)
                    p1 = p0 + dirv * d1 * (0.3 + 0.7 * tk)
                    p_tail = p1 - dirv * (18 * (1 - tk) + 7)
                    lo, hi = np.minimum(p1, p_tail) - 6, np.maximum(p1, p_tail) + 6
                    sl = acc.window(lo[0], lo[1], hi[0], hi[1])
                    acc.add(sl, 0.8 * (1 - 0.75 * tk) * streak(X[sl], Y[sl], p_tail[0], p_tail[1], p1[0], p1[1], sz))

        out.append(finish_white(tiled(size, size, paint), 9860 + i))
    return out


# ============================================================== 铜钱剑：天罡的再斩（十字斩痕）


def make_coin_cross() -> list[Image.Image]:
    """再斩：目标身上一个十字斩痕。第 0 帧一道“╲”闪出（笔锋在前、尾巴飞白），第 1 帧“╱”交叉上去、两道都最亮，
    交叉处一点亮；之后两道变干、碎成丝，交叉处崩出几点火星。白色，可染（建议铜金 #F2C46A）。"""
    w = h = 160
    cx = cy = 80.0
    X, Y = grid(w, h)
    rng = np.random.default_rng(9891)
    strokes = []
    for k, ang in enumerate((math.radians(38), math.radians(-38 + 180))):
        L = 116 - 8 * k
        n = 120
        tt = np.linspace(-0.5, 0.5, n)
        bow = 4.0 * (1 - (2 * tt) ** 2) * (1 if k == 0 else -1)  # 微微的弧，像挥出来的
        pts = np.stack([tt * L, bow], -1)
        rot = np.array([[math.cos(ang), -math.sin(ang)], [math.sin(ang), math.cos(ang)]])
        strokes.append((pts @ rot.T + np.array([cx, cy]), int(rng.integers(1 << 30))))
    sparks = [(rng.uniform(0, 2 * math.pi), rng.uniform(14, 30), rng.uniform(0.8, 1.2)) for _ in range(8)]
    show = [(1.0, 0.0), (0.95, 1.0), (0.62, 0.7), (0.26, 0.3)]  # 每帧两道斩痕的亮度
    width = [(6.5, 0.0), (5.5, 6.5), (4.2, 5.0), (2.8, 3.2)]
    dryness = [(0.2, 0.0), (0.3, 0.2), (0.5, 0.45), (0.7, 0.65)]
    out = []
    for i in range(4):
        t = i / 3
        a = []
        for k, (pts, sd) in enumerate(strokes):
            if show[i][k] <= 0:
                continue
            tt = np.linspace(0, 1, len(pts))
            hw = width[i][k] * np.sin(np.pi * np.clip(tt, 0, 1)) ** 0.6 + 0.2
            cov, _ = V.brush_stroke(X, Y, pts, hw, np.random.default_rng(sd), dry=dryness[i][k], dry_start=0.3, ss=SS)
            a.append(show[i][k] * cov)
        if i in (1, 2):
            a.append([0, 0.9, 0.5][i] * np.exp(-((np.hypot(X - cx, Y - cy) / 6.0) ** 2)))
        if i >= 2:
            for ang, d1, sz in sparks:
                d = 6 + d1 * (0.5 + 0.5 * (i - 2))
                x1, y1 = cx + d * math.cos(ang), cy + d * math.sin(ang)
                x0, y0 = cx + (d - 6) * math.cos(ang), cy + (d - 6) * math.sin(ang)
                a.append((0.8 if i == 2 else 0.35) * streak(X, Y, x0, y0, x1, y1, sz))
        out.append(F.frame_white(soft_union(*a), 9895 + i))
    return out


# ============================================================== 清单与输出

# 名字: (生成函数, 画布 (w, h), 锚点, blend, tint, 颜色说明, 附加 meta)
COIN = {
    "coin_slash": (make_coin_slash, (CSLASH_W, CSLASH_H), (CSLASH_C[0] / CSLASH_W, CSLASH_C[1] / CSLASH_H), "add", True, "white",
                   {"points": "+x", "radius_px": int(CSLASH_R), "angle_deg": int(CSLASH_ARC), "tint_hint": COIN_TINT,
                    "note": "铜钱剑的挥击：120° 扇形剑气朝 +X 张开，锚点是弧心，笔锋从上往下扫（图里 y 向下，反手上下镜像）；"
                            "radius_px 是外沿半径，缩放 = 扫击半径 ÷（radius_px ÷ pxPerUnit），1080p 下 171 单位一比一；建议染铜金 #F2C46A"}),
    "coin_spark": (make_coin_spark, (SPARK_W, SPARK_H), (SPARK_C[0] / SPARK_W, SPARK_C[1] / SPARK_H), "add", False, "full",
                   {"points": "+x", "note": "铜钱剑命中的铜钱火星（约 16 世界单位）：锚点是接触点，火星朝 +X 溅，按入射方向转；自带铜金色，不染"}),
    "coin_whirl": (make_coin_whirl, (WHIRL_SIZE, WHIRL_SIZE), (0.5, 0.5), "add", True, "white",
                   {"radius_px": int(WHIRL_R), "tint_hint": COIN_TINT,
                    "note": "天罡：周身一圈旋风刀光，顺时针转（图里 y 向下）；radius_px 是外沿半径，缩放 = 旋风半径 ÷（radius_px ÷ pxPerUnit）；建议染铜金 #F2C46A"}),
    "coin_cross": (make_coin_cross, (160, 160), (0.5, 0.5), "add", True, "white",
                   {"tint_hint": COIN_TINT, "note": "天罡的再斩：目标身上的十字斩痕（约 30 世界单位，原大），0.15 秒；建议染铜金 #F2C46A"}),
}
BATCHES = {"coin": COIN}
TITLES = {"coin": "铜钱剑"}
# 1080p 合成，摆法同 vfx_frames_review：(名, 帧, (x, y), 摆法, 想要的半径或 None)。一张一个场面，后缀加在文件名上。
INGAME = {
    "coin": {
        "": [
            ("coin_slash", 2, (0.0, 12.0), "hero", 170.0),  # Lv6–8 的扫击半径，朝 +X：右边两只在扇形里
            ("coin_spark", 1, (62.0, -82.0), "body", None),
            ("coin_spark", 2, (125.0, 72.0), "body", None),
            ("coin_cross", 1, (-168.0, -100.0), "body", None),
            ("coin_spark", 3, (-238.0, 58.0), "body", None),
            ("coin_cross", 2, (250.0, 128.0), "body", None),
            ("coin_spark", 1, (288.0, -128.0), "body", None),
        ],
        "_whirl": [
            ("coin_whirl", 2, (0.0, 12.0), "hero", 200.0),  # 天罡的半径 200
            ("coin_cross", 1, (62.0, -82.0), "body", None),
            ("coin_spark", 2, (125.0, 72.0), "body", None),
            ("coin_cross", 2, (-168.0, -100.0), "body", None),
        ],
    },
}


def main() -> None:
    import vfx_frames_review as R  # noqa: PLC0415  审图共用 vfx_frames 的

    t0 = time.perf_counter()
    for key, batch in BATCHES.items():
        frames = F.build(batch)
        F.write(frames, batch, out=OUT, name="weapons", generator=GENERATOR)
        note = f"叠加帧审图染色：可染的按建议色（{COIN_TINT} 铜金），铜钱火星自带颜色"
        R.strip_sheet(key, batch, frames, REVIEW / f"weapons_ea_{key}.png", title=f"新法器 · {TITLES[key]}", note=note)
        for suffix, placements in INGAME[key].items():
            R.ingame(key, batch, frames, REVIEW / f"weapons_ea_{key}{suffix}_ingame.png", placements=placements, title=f"新法器 · {TITLES[key]}")
        print(f"{key}: {sum(len(v) for v in frames.values())} 帧  {time.perf_counter() - t0:.1f}s")


if __name__ == "__main__":
    main()
