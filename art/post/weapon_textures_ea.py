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

沧浪（水）：weapons/wave_front_0..3（浪头，循环）+ wave_front_fade_0..2（散掉）、wave_trail_0（身后的泡沫痕，竖向拉伸）。
青藤（木）：weapons/vine_0..2（藤，锚点右端、沿 X 拉伸）、vine_pulse_0..2（每跳流回主角的绿光）、vine_bind_0..3（万木春缠绕）。
都是白色可染的叠加帧；循环的组 meta 写 fps、loop: true，接在别的组后面播的写 follows。

孔明灯（火）、镇妖塔（土）：先跑 art/render/weapons_ea_render.py 用 Blender 渲源图（out/assets@2x/ea_<名字>/），这里读进来改名：
  weapons/sky_lantern_0..3（飘，循环）、sky_lantern_fall_0..2（烧着坠下），各带 _emit 发光层；lantern_mark_0（落点圈）、fire_sea_0..3（火海）。
  weapons/tower_0..1（立着，铃铛摆）、tower_fall_0..2（砸下来）、tower_lift_0..2（收走），各带 _emit；玲珑塔同一套叫 tower_gold*；
  tower_dust_0..5（落地的尘土冲击波）、tower_vortex_0..3（吸妖的旋涡）。

产物：art/out/assets@2x/weapons_ea/*.png + meta.json（name: weapons）
审图：art/out/review@2x/weapons_ea_<件>.png（纸色底 / 夜色底的帧条）、weapons_ea_<件>_ingame.png（1080p 合成）

用法（仓库根目录）：
  art/.venv/bin/python art/post/weapon_textures_ea.py            # 全部；后面跟件名（coin wave vine …）只画那几件
  art/.venv/bin/python art/post/test_weapon_textures_ea.py
"""

from __future__ import annotations

import json
import math
import sys
import time
from functools import lru_cache
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


# ============================================================== 沧浪：浪头、泡沫痕

WAVE_W, WAVE_H = 448, 128
WAVE_SPAN = 432.0  # 浪头横向的宽（像素）≈ 画布宽；游戏按 2 × 半宽 等比缩放（1080p 下 168 单位一比一）
WAVE_Y0 = 88.0  # 浪头正中的前沿（锚点）；往图里 +y（下）推进，两头往后（上）弯
WAVE_SAG = 44.0  # 两头比正中落后多少像素（月牙）
WAVE_FPS = 12
TRAIL_W, TRAIL_H = 448, 256


def bilerp(tex: np.ndarray, x, y) -> np.ndarray:
    """周期纹理的双线性采样（x、y 是纹理像素坐标，超出就绕回）。"""
    h, w = tex.shape
    x0, y0 = np.floor(x), np.floor(y)
    fx, fy = x - x0, y - y0
    x0, y0 = x0.astype(int) % w, y0.astype(int) % h
    x1, y1 = (x0 + 1) % w, (y0 + 1) % h
    return (tex[y0, x0] * (1 - fx) + tex[y0, x1] * fx) * (1 - fy) + (tex[y1, x0] * (1 - fx) + tex[y1, x1] * fx) * fy


def wave_crest_y(u, phase: float, wob: float = 2.5):
    """浪头中线（前沿）的 y：正中最靠前（WAVE_Y0），两头往后弯成月牙，沿浪头有几道小起伏（随相位走）。"""
    return WAVE_Y0 - WAVE_SAG * u**2 + wob * np.sin(5.0 * math.pi * u + phase) * (1 - u**2)


def make_wave_front_loop() -> list[Image.Image]:
    return list(_wave_front()[:4])


def make_wave_front_fade() -> list[Image.Image]:
    return list(_wave_front()[4:])


@lru_cache(maxsize=1)
def _wave_front() -> tuple[Image.Image, ...]:
    """沧浪推出的浪头：横着的一道月牙形浪，往图里 +y（下）推进，正中最靠前、两头往后弯、越往两头越细。
    浪头是一笔饱满的月牙笔锋：前沿利、亮（卷起的浪唇），往后起飞白；身后两三道细的回纹（浪背的涟漪），
    浪头后沿和两头卷起的地方缀着细碎的浪花点，浪唇前面溅几粒水珠。
    0–3 帧循环（12 帧/秒）：浪唇的小起伏顺着浪头走，浪花点翻滚，水珠往前溅；4–6 帧散掉：浪身碎成一串串浪花、变淡。
    白色，可染（游戏里染水色）。锚点是正中前沿。"""
    w, h = WAVE_W, WAVE_H
    cx = w / 2
    rng = np.random.default_rng(9701 + 11)
    tex = W.ptex(rng, ns=28, nt=1024, along=22.0, across=0.6)
    dots_a = V.noise(rng, (h, w), 1.1)
    dots_b = V.noise(rng, (h, w), 1.1)
    drops = [(rng.uniform(-0.75, 0.75), rng.uniform(0, 1), rng.uniform(8, 16), rng.uniform(1.0, 1.6)) for _ in range(14)]
    echoes = [(17.0, 0.55, 0.0), (31.0, 0.38, 1.7), (45.0, 0.22, 3.1)]  # 回纹：离浪唇多远、亮度、相位
    out = []
    for i in range(7):
        loop = i < 4
        ph = 2 * math.pi * (i % 4) / 4
        k = 0.0 if loop else (i - 3) / 3  # 散掉的进度 1/3、2/3、1
        X, Y = grid(w, h)
        acc = F.Acc(X, Y)
        full = (slice(None), slice(None))
        u = (X - cx) / (WAVE_SPAN / 2)
        uc = np.clip(u, -1, 1)
        ends = smoothstep(1.02, 0.86, np.abs(u))  # 两头收掉
        yc = wave_crest_y(uc, ph, wob=2.0) - 5.0 * k
        T = (25.0 - 6.0 * k) * (1 - 0.8 * uc**2) ** 0.8 + 1.0  # 浪身厚（往后）
        s = (yc - Y) / T  # 0 = 前沿，1 = 浪身后沿
        lip = np.exp(-(((Y - (yc - 2.2)) / 2.2) ** 2)) * smoothstep(1.0, 0.75, np.abs(u))
        body = smoothstep(-0.12, 0.02, s) * smoothstep(1.0, 0.45, s) * np.exp(-0.9 * np.clip(s, 0, None))
        dryk = 0.08 + 0.35 * np.clip(s, 0, 1) ** 1.4 + 0.4 * k + 0.3 * np.abs(uc) ** 3
        m = dry(tex, np.clip(2 * s - 1, -1, 1), X / w * 0.8 + 0.05 * (i % 4), dryk)
        acc.add(full, (1 - 0.7 * k) * ends * np.maximum(0.95 * lip * (1 - 0.5 * k), 0.9 * body * m))
        for dist, br, eph in echoes:  # 浪背的回纹：细线，跟着浪唇弯，越远越淡、越短
            ye = wave_crest_y(uc, ph + eph, wob=3.0) - dist - 4.0 * k
            span_e = 0.92 - dist / 80.0
            line = np.exp(-(((Y - ye) / 1.5) ** 2)) * smoothstep(span_e, span_e - 0.2, np.abs(u))
            acc.add(full, br * (1 - 0.6 * k) * line * dry(tex, 0.3, X / w * 0.6 + dist / 50 + 0.07 * (i % 4), 0.35 + 0.3 * k))
        # 浪花：细碎的点，挨着浪头后沿、两头更多；两张噪声转着混，4 帧一循环
        nz = math.cos(ph) * bilerp(dots_a, X, Y) + math.sin(ph) * bilerp(dots_b, X, Y)
        band = np.exp(-(((s - 1.15 - 0.5 * k) / (0.45 + 0.4 * k)) ** 2)) * ends
        band = band + 0.8 * np.exp(-(((s - 0.6) / 0.9) ** 2)) * smoothstep(0.55, 0.9, np.abs(u)) * ends  # 两头卷起处
        thr = 1.55 - 0.35 * band - 0.15 * k
        acc.add(full, (0.85 - 0.4 * k) * smoothstep(thr, thr + 0.25, nz) * np.clip(band, 0, 1))
        # 水珠：从浪唇往前（+y）溅出去
        for ux, p0, d1, sz in drops:
            t = ((i % 4) / 4 + p0) % 1.0 if loop else min(1.0, 0.7 + 0.3 * k)
            px = cx + ux * WAVE_SPAN / 2 + 3.0 * t * np.sign(ux)
            py0 = float(wave_crest_y(np.array(ux), ph, wob=2.0)) - 2
            py = py0 + d1 * t
            amp = (math.sin(math.pi * t) ** 0.7) * (1 - 0.7 * k) * (1 - abs(ux) ** 2)
            if amp <= 0.02:
                continue
            sl = acc.window(px - 6, py - 10, px + 6, py + 6)
            acc.add(sl, 0.8 * amp * streak(X[sl], Y[sl], px, py - 5 * (1 - t) - 1, px, py, sz))
        out.append(F.frame_white(acc.a, 9720 + i))
    return tuple(out)


def make_wave_trail() -> list[Image.Image]:
    """浪身后的泡沫痕：一条竖着的带子，宽 = 浪宽，游戏沿推进方向拉到走过的长度（锚点在下边正中 = 浪头那一头，往 −y 拉）。
    两道亮一些的泡沫线是浪头两端走过的路，中间几道顺着走向的细水纹，散着细碎的浪花点；离浪头越远越淡。白色，可染。"""
    w, h = TRAIL_W, TRAIL_H
    cx = w / 2
    rng = np.random.default_rng(9741)
    tex = W.ptex(rng, ns=112, nt=1024, along=40.0, across=0.6)
    dots = V.noise(rng, (h, w), 1.0)
    X, Y = grid(w, h)
    u = (X - cx) / (WAVE_SPAN / 2)
    v = Y / h  # 0 = 远端（上），1 = 浪头这头（下）
    fade = smoothstep(0.0, 0.9, v) ** 1.6 * smoothstep(0.985, 0.92, v)  # 最下面几行淡掉（四边透明，接浪头的地方被浪头盖住）
    a = []
    for su in (-0.86, 0.86):  # 浪头两端走过的两道泡沫线（微微摆）
        uu = u - su - 0.02 * np.sin(v * 9.0 + su)
        lane = np.exp(-((uu * WAVE_SPAN / 2 / 3.0) ** 2))
        a.append(0.45 * lane * fade * dry(tex, np.clip(uu * 25, -1, 1), v * 0.5 + su, 0.25))
    streaks = 0.1 * smoothstep(0.84, 0.6, np.abs(u)) * fade**1.5 * dry(tex, np.clip(u, -1, 1), v * 0.6 + 0.3, 0.8)
    a.append(streaks)
    band = smoothstep(0.95, 0.75, np.abs(u)) * fade
    a.append(0.6 * smoothstep(1.95, 2.2, bilerp(dots, X, Y)) * band)
    return [F.frame_white(soft_union(*a), 9745)]


# ============================================================== 青藤：藤、回血的绿光、万木春缠绕

VINE_W, VINE_H = 512, 40  # 横向拉到连线长度（游戏按 长度 ÷ 画布宽 拉伸），竖向整张 = 10 世界单位（4 像素 / 单位）
VINE_FPS = 8
VINE_LEAVES = 12


def vine_stem_y(x, ph: float, amp: float = 2.6, lam: float = 118.0):
    """藤的中线：两头贴着中线（接主角和妖物），中间几道弯，弯随相位往妖物那头（+x）走。"""
    env = np.clip(np.sin(np.pi * np.clip(x / VINE_W, 0, 1)), 0, 1) ** 0.6
    return VINE_H / 2 + amp * env * np.sin(2 * math.pi * x / lam - ph)


def make_vine() -> list[Image.Image]:
    """青藤：主角（左端）连到妖物（右端，锚点）的一根藤。一根亮的主藤带几道弯，一根细的卷须绕着它拧；
    两侧交替长十二片小叶，叶尖朝妖物那头（+x），叶边亮、叶心淡、一道叶脉；两端在中线上收细。
    3 帧循环（8 帧/秒）：藤上的弯往妖物那头走，叶子翻一翻。叠加，白色可染（游戏染青绿）。"""
    w, h = VINE_W, VINE_H
    rng = np.random.default_rng(9761)
    tex = W.ptex(rng, ns=16, nt=1024, along=30.0, across=0.6)
    leaves = []
    for k in range(VINE_LEAVES):
        x0 = 30 + (w - 60) * (k + 0.5 + rng.uniform(-0.2, 0.2)) / VINE_LEAVES
        side = -1.0 if k % 2 == 0 else 1.0
        leaves.append((x0, side, rng.uniform(11.0, 13.5), rng.uniform(5.2, 6.6), math.radians(rng.uniform(30, 40)), rng.uniform(0, 2 * math.pi)))
    out = []
    for i in range(3):
        ph = 2 * math.pi * i / 3
        X, Y = grid(w, h)
        acc = F.Acc(X, Y)
        full = (slice(None), slice(None))
        ends = smoothstep(4.0, 22.0, X) * smoothstep(w - 4.0, w - 16.0, X)  # 两端收细、淡掉
        ys = vine_stem_y(X, ph)
        d = Y - ys
        hw = 3.8 * ends + 0.4  # 主藤约 2 世界单位粗（整张高 10 单位 = 40 像素）
        core = smoothstep(hw + 0.5, hw - 0.5, np.abs(d))
        halo = np.exp(-((d / 6.5) ** 2)) * ends
        grain_ = dry(tex, np.clip(d / hw, -1, 1), X / w * 0.7 + 0.1 * i, 0.22)  # 藤皮上顺着走的笔毛纹
        edge = smoothstep(1.4, 0.3, np.abs(np.abs(d) - (hw - 0.9)))  # 两边亮、中间淡一点，像一根圆的藤
        acc.add(full, core * ends * (0.55 + 0.25 * grain_ + 0.2 * edge))
        acc.add(full, 0.18 * halo)
        # 卷须：细的一根绕着主藤拧（在前面那半圈亮、后面那半圈暗）
        tw = 2 * math.pi * X / 38.0 - ph * 0.5
        yt = ys + 6.2 * np.sin(tw) * ends
        front = 0.4 + 0.6 * (np.cos(tw) > 0)
        acc.add(full, 0.7 * front * ends * smoothstep(1.5, 0.5, np.abs(Y - yt)))
        for x0, side, L, wd, ang0, lph in leaves:  # 叶子：叶尖朝 +x，上下交替，翻一翻
            y0 = float(vine_stem_y(np.array(x0), ph))
            ang = side * (ang0 + math.radians(10.0) * math.sin(ph + lph))
            u = np.array([math.cos(ang), math.sin(ang)])  # 图里 y 向下：side=-1 朝右上
            base = np.array([x0, y0])
            tip = base + u * L
            lo, hi = np.minimum(base, tip) - wd - 2, np.maximum(base, tip) + wd + 2
            sl = acc.window(lo[0], lo[1], hi[0], hi[1])
            cov, dd, along = F.almond_field(X[sl], Y[sl], base, tip, wd * (0.85 + 0.15 * math.cos(ph + lph)), bulge=0.4)
            rim = smoothstep(1.3, 0.0, np.abs(dd)) * (dd < 0.6)
            vperp = -(X[sl] - base[0]) * u[1] + (Y[sl] - base[1]) * u[0]
            rib = smoothstep(0.7, 0.2, np.abs(vperp)) * (along < 0.85)
            acc.add(sl, np.clip(0.32 * cov + 0.85 * rim + 0.4 * rib * cov, 0, 1))
        out.append(F.frame_white(acc.a, 9765 + i))
    return out


PULSE_W, PULSE_H = 128, 48
PULSE_HEAD = (104.0, 24.0)


def make_vine_pulse() -> list[Image.Image]:
    """每跳回血：一颗绿光从妖物沿藤流回主角。头朝 +x（锚点在头上），身后拖一道细尾，尾上几点碎光；
    3 帧循环（24 帧/秒）：头一明一暗、碎光往后掉。叠加，白色可染（染青绿）。"""
    w, h = PULSE_W, PULSE_H
    hx, hy = PULSE_HEAD
    rng = np.random.default_rng(9771)
    motes = [(rng.uniform(12, 72), rng.uniform(-4, 4), rng.uniform(0.9, 1.4), rng.uniform(0, 1)) for _ in range(8)]
    out = []
    for i in range(3):
        X, Y = grid(w, h)
        a = []
        r = np.hypot(X - hx, Y - hy)
        pulse = [1.0, 0.86, 0.93][i]
        a.append(pulse * smoothstep(5.6, 4.0, r))
        a.append(0.5 * pulse * np.exp(-((r / 11.0) ** 2)))
        tail, _ = needle(X, Y, hx, hy, math.pi, 84.0, 3.6, w1=0.25, taper=0.8)
        u = np.clip((hx - X) / 84.0, 0, 1)
        a.append(0.7 * tail * (1 - u) ** 0.8)
        for dx, dy, sz, p0 in motes:
            t = (i / 3 + p0) % 1.0
            x = hx - dx - 12 * t
            a.append(0.75 * (1 - t) * (1 - dx / 90) * F.dot(X, Y, x, hy + dy * (0.5 + t), sz))
        out.append(F.frame_white(soft_union(*a), 9775 + i))
    return out


BIND_SIZE = 192
BIND_R = 56.0  # 缠绕圈的横向半径（像素）≈ 妖物半径；游戏按妖物半径缩放


def make_vine_bind() -> list[Image.Image]:
    """万木春缠绕：两根藤从妖物脚下两边长出来，各自绕着身子往上盘一圈多（盘的圈按地面透视压扁，前半圈亮、后半圈暗，
    半径中间鼓、带一点抖），交叉着把它裹住，梢上卷一个小卷，沿途冒出几片叶子。0–2 帧长上去、盘紧，
    第 3 帧裹住（留着到缠绕结束，游戏淡出）。叠加，白色可染（染青绿）。锚点是妖物脚底；radius_px 是缠绕圈的横向半径。"""
    size = BIND_SIZE
    cx, cy = size / 2, size * 0.72
    rng = np.random.default_rng(9781)
    grow = [0.38, 0.72, 1.0, 1.0]
    tight = [1.12, 1.05, 1.0, 0.96]  # 盘紧
    strands = []
    for sd in range(2):
        jit = rng.uniform(-1, 1, 6)
        strands.append(dict(th0=math.pi * (0.15 + sd) + rng.uniform(-0.3, 0.3), turns=1.35 + 0.15 * sd, height=84.0 - 10 * sd,
                            jit=jit, seed=9785 + sd, sign=1.0 if sd == 0 else -1.0))
    out = []
    for i in range(4):
        X, Y = grid(size, size)
        acc = F.Acc(X, Y)
        full = (slice(None), slice(None))
        for st in strands:
            n = 240
            t = np.linspace(0, grow[i], n)
            th = st["th0"] + st["sign"] * 2 * math.pi * st["turns"] * t
            wob = sum(st["jit"][k] * np.sin((k + 2) * math.pi * t + k) for k in range(6)) * 0.05
            rr = BIND_R * tight[i] * (0.82 + 0.22 * np.sin(math.pi * np.clip(t * 1.1, 0, 1))) * (1 + wob)
            pts = np.stack([cx + rr * np.cos(th), cy - st["height"] * t ** 0.9 + rr * np.sin(th) * F.FLAT * 0.6], -1)
            if grow[i] >= 0.99:  # 梢上卷一个小卷：顺着梢的方向绕半径 7 的圆弧，越绕越紧
                end, d_end = pts[-1], pts[-1] - pts[-2]
                ang0 = math.atan2(d_end[1], d_end[0])
                sg = st["sign"]
                c0 = end + 7.0 * np.array([math.cos(ang0 + sg * math.pi / 2), math.sin(ang0 + sg * math.pi / 2)])
                a_ = np.linspace(0.0, 4.0, 30)[1:]
                start = ang0 - sg * math.pi / 2
                cur = c0 + 7.0 * (1 - 0.18 * a_ / 4)[:, None] * np.stack([np.cos(start + sg * a_), np.sin(start + sg * a_)], -1)
                pts = np.vstack([pts, cur])
                th = np.concatenate([th, np.full(len(cur), th[-1])])
            m = len(pts)
            tt = np.linspace(0, 1, m)
            hw = (3.2 - 1.8 * tt) * (0.55 + 0.45 * np.clip(tt * 8, 0, 1))
            cov, f = V.brush_stroke(X, Y, pts, hw, np.random.default_rng(st["seed"]), dry=0.2, dry_start=0.75, ss=SS)
            idx = np.clip((f["t"] * (m - 1)).round().astype(int), 0, m - 1)
            front = np.sin(th) > -0.15  # 前半圈（靠镜头）亮
            acc.add(full, np.where(front[idx], 0.95, 0.38) * cov)
            for j in range(3):  # 叶子
                tj = (j + 0.55) / 3.3
                if tj > grow[i] - 0.05:
                    continue
                p = int(tj / grow[i] * (n - 1))
                base = pts[p]
                ang = th[p] + st["sign"] * math.pi / 2 + (0.5 if j % 2 else -0.5)
                u = np.array([math.cos(ang), math.sin(ang) * 0.75])
                u /= np.linalg.norm(u)
                L = 13.0 * min(1.0, (grow[i] - tj) * 3 + 0.45)
                tip = base + u * L
                sl = acc.window(min(base[0], tip[0]) - 8, min(base[1], tip[1]) - 8, max(base[0], tip[0]) + 8, max(base[1], tip[1]) + 8)
                cv, dd, _ = F.almond_field(X[sl], Y[sl], base, tip, 6.0, bulge=0.4)
                rim = smoothstep(1.3, 0.0, np.abs(dd)) * (dd < 0.6)
                acc.add(sl, (0.9 if front[p] else 0.45) * np.clip(0.3 * cv + 0.85 * rim, 0, 1))
        out.append(F.frame_white(acc.a, 9790 + i))
    return out


# ============================================================== 孔明灯、镇妖塔：Blender 渲的源图 + 2D 后期

SRC = V.OUT / "assets@2x"  # render/weapons_ea_render.py 渲的源图：ea_<名字>/<动画>_S_<NN>.png + _emit.png
EMIT_ALPHA = (0.3, 0.75)  # 发光层的强度：按亮度从最暗的发光色到最亮的压（整张纸都发光，不压的话夜里是一团白）


def src_rgba(asset: str, stem: str) -> tuple[np.ndarray, np.ndarray]:
    """读一帧源图（普通层、发光层），没有就提示先跑 Blender 那一步。"""
    d = SRC / f"ea_{asset}"
    p = d / f"{stem}.png"
    if not p.exists():
        raise FileNotFoundError(f"缺 {p}：先跑 art/.venv/bin/python art/render/weapons_ea_render.py --only {asset}")
    im = np.asarray(Image.open(p).convert("RGBA")).astype(np.float64) / 255.0
    e = d / f"{stem}_emit.png"
    em = np.asarray(Image.open(e).convert("RGBA")).astype(np.float64) / 255.0 if e.exists() else np.zeros_like(im)
    return im, em


def soften_emit(em: np.ndarray, gain: float = 1.0, k=EMIT_ALPHA) -> np.ndarray:
    """发光层的 alpha 按颜色亮度压到 k[0]..k[1]（再乘 gain），颜色不动。"""
    lum = em[..., :3].mean(-1)
    on = em[..., 3] > 0
    if not on.any():
        return em
    lo, hi = np.percentile(lum[on], 5), np.percentile(lum[on], 95)
    t = np.clip((lum - lo) / max(hi - lo, 1e-6), 0, 1)
    out = em.copy()
    out[..., 3] = np.clip(em[..., 3] * (k[0] + (k[1] - k[0]) * t) * gain, 0, 1)
    return out


def to_image(arr: np.ndarray) -> Image.Image:
    """0..1 的直通 RGBA → 8 位（透明处的颜色往外扩，免得线性过滤出黑边），四边一圈清掉。"""
    a = np.clip(arr[..., 3], 0, 1)
    a8 = np.clip(np.round(a * 255), 0, 255).astype(np.uint8)
    a8[0, :] = a8[-1, :] = a8[:, 0] = a8[:, -1] = 0
    return V.to_rgba8(np.clip(arr[..., :3], 0, 1), None, a8)


def shift_scale(arr: np.ndarray, anchor_px, dy: float = 0.0, sx: float = 1.0, sy: float = 1.0, out_hw=None) -> np.ndarray:
    """以锚点为中心缩放（sx、sy），再往上挪 dy 像素；双线性、预乘 alpha 采样。out_hw 给出时换画布大小（锚点像素不变）。"""
    h, w = arr.shape[:2]
    oh, ow = out_hw or (h, w)
    ax, ay = anchor_px
    yy, xx = np.mgrid[0:oh, 0:ow] + 0.5
    src_x = (xx - ax) / sx + ax
    src_y = (yy - ay + dy) / sy + ay
    prem = np.dstack([arr[..., :3] * arr[..., 3:4], arr[..., 3:4]])
    x0, y0 = np.floor(src_x - 0.5).astype(int), np.floor(src_y - 0.5).astype(int)
    fx, fy = src_x - 0.5 - x0, src_y - 0.5 - y0
    out = np.zeros((oh, ow, 4))
    for dy_, dx_, wgt in ((0, 0, (1 - fx) * (1 - fy)), (0, 1, fx * (1 - fy)), (1, 0, (1 - fx) * fy), (1, 1, fx * fy)):
        yi, xi = y0 + dy_, x0 + dx_
        ok = (yi >= 0) & (yi < h) & (xi >= 0) & (xi < w)
        v = np.zeros((oh, ow, 4))
        v[ok] = prem[yi[ok], xi[ok]]
        out += v * wgt[..., None]
    a = out[..., 3:4]
    return np.dstack([np.where(a > 1e-6, out[..., :3] / np.maximum(a, 1e-6), 0.0), a])


# ---------------------------------------------------------------- 孔明灯

LT_FLICKER = [1.0, 0.86, 0.96, 0.9]  # 飘着时灯火一明一暗


def _lantern_frames(kind: str) -> tuple[list, list]:
    if kind == "float":
        stems = [f"float_S_{i:02d}" for i in range(4)]
        gains = LT_FLICKER
    else:
        stems = [f"fall_S_{i:02d}" for i in range(3)]
        gains = [1.1, 1.2, 1.3]  # 烧起来更亮
    base, glow = [], []
    for st, g in zip(stems, gains):
        im, em = src_rgba("sky_lantern", st)
        base.append(to_image(im))
        glow.append(to_image(soften_emit(em, g)))
    return base, glow


@lru_cache(maxsize=None)
def _lantern(kind: str):
    return _lantern_frames(kind)


def make_sky_lantern() -> list[Image.Image]:
    return list(_lantern("float")[0])


def make_sky_lantern_emit() -> list[Image.Image]:
    return list(_lantern("float")[1])


def make_sky_lantern_fall() -> list[Image.Image]:
    return list(_lantern("fall")[0])


def make_sky_lantern_fall_emit() -> list[Image.Image]:
    return list(_lantern("fall")[1])


MARK_W, MARK_H = 352, 224
MARK_R = 144.0  # 圈的横向半径（像素）= 爆燃半径；1080p 下 56 单位一比一


def make_lantern_mark() -> list[Image.Image]:
    """孔明灯的落点圈：地上一圈干笔画的圆（按地面透视压扁），断成三四截，四个方向各一道往里指的短笔，
    正中一个小十字。白色可染（游戏染暗红、越接近落地越亮、慢慢收紧），叠加；radius_px 是圈的横向半径。"""
    w, h = MARK_W, MARK_H
    cx, cy = w / 2, h / 2
    rng = np.random.default_rng(9801)
    tex = W.ptex(rng, ns=24, nt=2048, along=40.0, across=0.6)
    X, Y = grid(w, h)
    gx, gy = X - cx, (Y - cy) / F.FLAT
    r = np.hypot(gx, gy)
    th = np.arctan2(gy, gx)
    a = []
    t = (th / (2 * math.pi)) % 1.0
    gaps = smoothstep(0.0, 0.02, np.abs(((t * 3.5 + 0.15) % 1.0) - 0.5) - 0.42)  # 断成几截
    ring = np.exp(-(((r - MARK_R) / 3.2) ** 2))
    a.append(0.9 * ring * dry(tex, np.clip((r - MARK_R) / 6, -1, 1), t, 0.28) * (1 - 0.85 * (1 - gaps)))
    a.append(0.3 * np.exp(-(((r - MARK_R + 10) / 2.0) ** 2)) * dry(tex, 0.4, t + 0.3, 0.55))  # 里面一道淡的
    for k in range(4):  # 往里指的短笔
        ang = math.pi / 4 + k * math.pi / 2
        x0, y0 = cx + (MARK_R + 6) * math.cos(ang), cy + (MARK_R + 6) * math.sin(ang) * F.FLAT
        x1, y1 = cx + (MARK_R - 22) * math.cos(ang), cy + (MARK_R - 22) * math.sin(ang) * F.FLAT
        a.append(0.85 * streak(X, Y, x0, y0, x1, y1, 3.0))
    for ang, L in ((0.0, 12.0), (math.pi / 2, 12.0 * F.FLAT)):  # 正中的小十字（竖的一笔按透视短一点）
        c1, _ = needle(X, Y, cx, cy, ang, L, 1.6, taper=1.0)
        c2, _ = needle(X, Y, cx, cy, ang + math.pi, L, 1.6, taper=1.0)
        a.append(0.6 * np.maximum(c1, c2))
    return [F.frame_white(soft_union(*a), 9805)]


SEA_W, SEA_H = 352, 224
SEA_R = 120.0  # 火海的横向半径（像素）= 0.8 × 爆燃半径；1080p 下 47 单位一比一


def make_fire_sea() -> list[Image.Image]:
    """孔明灯落地后的火海：地上一片低矮的火苗（按地面透视压扁的椭圆里散着四十来簇小火舌，尖往上翘），
    中间一层暗红的余烬光，火星往上飘。4 帧循环（12 帧/秒）：火舌一伸一缩、左右摆。叠加，自带火色，不染；
    radius_px 是火海的横向半径。"""
    w, h = SEA_W, SEA_H
    cx, cy = w / 2, h / 2
    rng = np.random.default_rng(9811)
    flames = []
    for _ in range(34):
        rr = SEA_R * math.sqrt(rng.uniform(0.0, 1.0)) * 0.9
        ang = rng.uniform(0, 2 * math.pi)
        flames.append((cx + rr * math.cos(ang), cy + rr * math.sin(ang) * F.FLAT, rng.uniform(16, 30) * (1.1 - 0.4 * rr / SEA_R),
                       rng.uniform(3.6, 5.6), rng.uniform(0, 2 * math.pi), int(rng.integers(1 << 30))))
    flames.sort(key=lambda f: f[1])
    embers = [(rng.uniform(-1, 1) * SEA_R * 0.8, rng.uniform(-1, 1) * SEA_R * 0.45, rng.uniform(0, 1), rng.uniform(0.8, 1.3)) for _ in range(14)]
    nz = V.noise(rng, (h, w), 6.0)
    out = []
    for i in range(4):
        ph = 2 * math.pi * i / 4
        X, Y = grid(w, h)
        acc = F.Acc(X, Y)
        full = (slice(None), slice(None))
        gx, gy = X - cx, (Y - cy) / F.FLAT
        rr = np.hypot(gx, gy) / SEA_R
        bed = smoothstep(1.0, 0.55, rr) * (0.45 + 0.25 * np.clip(bilerp(nz, X + 3 * math.sin(ph), Y), -1, 1))
        acc.add(full, 0.5 * bed, 0.2)  # 余烬：暗红的底
        for fx, fy, L0, wd, fph, sd in flames:
            L = L0 * (0.8 + 0.25 * math.sin(ph + fph))
            sway = 2.5 * math.sin(ph * 1.0 + fph * 1.7)
            pts = V.bezier([(fx, fy), (fx + sway * 0.4, fy - L * 0.5), (fx + sway, fy - L)], 30)
            tt = np.linspace(0, 1, len(pts))
            hw = wd * (1 - tt) ** 0.8 * (0.7 + 0.3 * np.sin(np.pi * np.clip(tt * 2, 0, 1))) + 0.1
            sl = acc.window(fx - wd * 3 - 4, fy - L - 4, fx + wd * 3 + 4, fy + wd * 2)
            cov, f_ = V.brush_stroke(X[sl], Y[sl], pts, hw, np.random.default_rng(sd), dry=0.25, dry_start=0.55, ss=SS)
            acc.add(sl, 0.95 * cov, np.clip(0.95 - 0.8 * f_["t"], 0, 1))
        for ex, ey, p0, sz in embers:
            t = (i / 4 + p0) % 1.0
            px, py = cx + ex, cy + ey * F.FLAT - 10 - 40 * t
            sl = acc.window(px - 4, py - 4, px + 4, py + 10)
            acc.add(sl, 0.8 * math.sin(math.pi * t) * streak(X[sl], Y[sl], px, py + 6, px, py, sz), 0.75)
        out.append(F.frame_color(acc.a, acc.heat(), 9815 + i, F.FIRE))
    return out


# ---------------------------------------------------------------- 镇妖塔 / 玲珑塔

TOWER_PAD = 24  # 源图下面再垫几行（基座前角离画布底太近）
# 落下 3 帧：(往上挪多少世界单位, 竖向拉长, 横向, 透明度)；收走 3 帧：(往上挪, 消散到哪 0..1, 金光)
TW_FALL = [(26.0, 1.16, 0.95, 0.8), (7.0, 1.05, 0.98, 0.95), (0.0, 0.93, 1.05, 1.0)]
TW_LIFT = [(1.5, 0.0, 1.0), (10.0, 0.42, 0.75), (24.0, 0.8, 0.45)]


def _tower_src(asset: str):
    m = json.loads((SRC / f"ea_{asset}" / "meta.json").read_text(encoding="utf-8"))
    size = m["size"][0]
    anc = (m["anchor"][0] * size, m["anchor"][1] * size)
    frames = [src_rgba(asset, f"idle_S_{i:02d}") for i in range(2)]
    pad = lambda a: np.concatenate([a, np.zeros((TOWER_PAD, a.shape[1], 4))], 0)  # noqa: E731
    return [(pad(im), pad(em)) for im, em in frames], anc, size


@lru_cache(maxsize=None)
def _tower(asset: str):
    """一座塔的全部帧：idle 2 帧（铃铛摆）、落下 3 帧、收走 3 帧，每帧（普通层, 发光层）。"""
    frames, anc, size = _tower_src(asset)
    rng = np.random.default_rng(9831 if asset == "tower" else 9832)
    h, w = frames[0][0].shape[:2]
    idle = [(to_image(im), to_image(soften_emit(em, 1.0, (0.55, 0.9)))) for im, em in frames]
    im0, em0 = frames[0]
    fall = []
    for dy_u, sy, sx, op in TW_FALL:  # 从天上砸下来：拉长、往下挪，后面拖几道墨的速度线
        im = shift_scale(im0, anc, dy=dy_u * F.PPU, sx=sx, sy=sy)
        em = shift_scale(soften_emit(em0, 1.0, (0.55, 0.9)), anc, dy=dy_u * F.PPU, sx=sx, sy=sy)
        im[..., 3] *= op
        if dy_u > 0:  # 塔身上方几道竖的速度线（焦墨、干笔）
            X, Y = np.mgrid[0:h, 0:w][::-1]
            top = np.nonzero(im[..., 3].max(1) > 0.3)[0].min()
            lines = np.zeros((h, w))
            for k in range(7):
                x = anc[0] + (k - 3) * size * 0.05 + rng.uniform(-4, 4)
                L = min(dy_u * F.PPU * rng.uniform(0.6, 1.1), top + 20 - 8)  # 不出画布
                d = np.abs(X + 0.5 - x)
                yy = Y + 0.5
                on = (yy < top + 20) & (yy > top + 20 - L)
                lines = np.maximum(lines, on * smoothstep(1.4, 0.4, d) * (1 - (top + 20 - yy) / max(L, 1)) * 0.6)
            ink = np.dstack([np.broadcast_to(F.JIAO, (h, w, 3)), lines])
            a_new = im[..., 3] + ink[..., 3] * (1 - im[..., 3])
            rgb = (im[..., :3] * im[..., 3:4] + ink[..., :3] * ink[..., 3:4] * (1 - im[..., 3:4])) / np.maximum(a_new[..., None], 1e-6)
            im = np.dstack([rgb, a_new])
        fall.append((to_image(im), to_image(em)))
    lift = []
    noise = V.noise(rng, (h, w), 5.0)
    rows = np.nonzero(im0[..., 3].max(1) > 0.3)[0]
    y_top, y_bot = rows.min(), rows.max()
    for dy_u, dis, glow in TW_LIFT:  # 收走：往上升、从下往上散成金色的光点
        im = shift_scale(im0, anc, dy=dy_u * F.PPU)
        em = shift_scale(soften_emit(em0, 1.0, (0.55, 0.9)), anc, dy=dy_u * F.PPU)
        yy = np.mgrid[0:h, 0:w][0] + 0.5
        cut = y_bot - dy_u * F.PPU - dis * (y_bot - y_top) * 1.05  # 这一行以下散掉（随 dis 从塔底往上走）
        level = (yy - cut) / 18.0 + 0.5 * noise  # >0 的散掉
        keep = smoothstep(0.15, -0.15, level)
        edge = np.exp(-((level / 0.35) ** 2)) * (im[..., 3] > 0.05) * (dis > 0)
        im[..., 3] *= keep
        em[..., 3] = np.clip(em[..., 3] * keep + 0.75 * edge * (dis > 0), 0, 1)
        em[..., :3] = np.where(edge[..., None] > 0.05, V.col("#FFE7A8"), em[..., :3])
        if glow > 0:  # 整座塔描一圈金边（收走前一亮）
            a = im[..., 3]
            rim = np.clip(V.fft_blur(a, 2.0) - a * 0.6, 0, 1) * glow * 0.6
            em[..., :3] = np.where(rim[..., None] > 0.02, V.col("#FFE7A8"), em[..., :3])
            em[..., 3] = np.clip(em[..., 3] + rim, 0, 1)
        lift.append((to_image(im), to_image(em)))
    anc_out = (anc[0] / w, anc[1] / h)
    return {"idle": idle, "fall": fall, "lift": lift, "anchor": anc_out, "size": (w, h)}


def _tower_maker(asset: str, kind: str, layer: int):
    def make() -> list[Image.Image]:
        return [fr[layer] for fr in _tower(asset)[kind]]
    return make


DUST_W, DUST_H = 448, 304
DUST_R = 160.0  # 末帧尘环的横向半径（像素）≈ 落地半径；1080p 下 62 单位一比一
DUST_INK = "#6E6253"  # 尘土：淡墨里带一点赭


def make_tower_dust() -> list[Image.Image]:
    """镇妖塔落地的尘土冲击波：一圈尘团从塔底往外滚开（按地面透视压扁），越滚越大、越淡、越散，
    外沿几粒碎石往外蹦。普通混合，土墨色 #6E6253，不染；radius_px 是末帧尘环的横向半径，按落地半径缩放。"""
    w, h = DUST_W, DUST_H
    cx, cy = w / 2, h / 2
    rng = np.random.default_rng(9841)
    puffs = [(2 * math.pi * (k + rng.uniform(-0.3, 0.3)) / 26, rng.uniform(0.8, 1.15), rng.uniform(0, 1)) for k in range(26)]
    stones = [(rng.uniform(0, 2 * math.pi), rng.uniform(0.9, 1.25), rng.uniform(1.0, 1.8)) for _ in range(16)]
    nz = V.noise(rng, (h, w), 3.0)
    Rk = [0.32, 0.55, 0.74, 0.88, 0.96, 1.0]
    env = [0.9, 0.85, 0.72, 0.55, 0.36, 0.18]
    out = []
    for i in range(6):
        X, Y = grid(w, h)
        acc = F.Acc(X, Y)
        R = DUST_R * Rk[i]
        for ang, rf, sz in puffs:
            r0 = R * rf
            px, py = cx + r0 * math.cos(ang), cy + r0 * math.sin(ang) * F.FLAT
            pr = (10 + 14 * sz) * (0.7 + 0.5 * Rk[i])
            sl = acc.window(px - pr * 1.6, py - pr * 1.2, px + pr * 1.6, py + pr * 1.2)
            d = np.hypot((X[sl] - px) / (pr * 1.25), (Y[sl] - py) / (pr * 0.85))
            n = bilerp(nz, X[sl] + 13 * i, Y[sl])
            acc.add(sl, env[i] * smoothstep(1.0, 0.45, d + 0.25 * n) * (0.55 + 0.25 * n))
        for ang, rf, sz in stones:
            if i == 0:
                continue
            r0 = R * rf + 6 * i
            px, py = cx + r0 * math.cos(ang), cy + r0 * math.sin(ang) * F.FLAT - 8 * math.sin(math.pi * i / 6)
            sl = acc.window(px - 4, py - 4, px + 4, py + 4)
            acc.add(sl, (1 - i / 7) * F.dot(X[sl], Y[sl], px, py, sz))
        out.append(F.frame_ink(acc.a, 9845 + i))
    # 换成土墨色（frame_ink 是焦墨）
    col = V.col(DUST_INK)
    return [V.to_rgba8(col, None, np.asarray(im)[..., 3]) for im in out]


VORTEX_W, VORTEX_H = 768, 480
VORTEX_R = 360.0  # 旋涡的横向半径（像素）= 吸的范围；1080p 下 140 单位一比一（玲珑塔的 500 要放大三倍多，它本来就淡）


def make_tower_vortex() -> list[Image.Image]:
    """镇妖塔吸妖的范围：地上一圈淡淡的旋涡（按地面透视压扁），六道螺旋的笔触往里卷，外沿一圈断续的细线，
    越往中心越淡（塔在中间）。4 帧循环（12 帧/秒），螺旋往里转。叠加，白色可染（游戏染土色 #C9925A）；
    radius_px 是旋涡的横向半径（= 吸的范围），按范围缩放。"""
    w, h = VORTEX_W, VORTEX_H
    cx, cy = w / 2, h / 2
    rng = np.random.default_rng(9851)
    tex = W.ptex(rng, ns=32, nt=2048, along=50.0, across=0.6)
    out = []
    for i in range(4):
        X, Y = grid(w, h)
        acc = F.Acc(X, Y)
        full = (slice(None), slice(None))
        gx, gy = X - cx, (Y - cy) / F.FLAT
        r = np.hypot(gx, gy) / VORTEX_R
        th = np.arctan2(gy, gx)
        rot = 2 * math.pi * (i / 4) / 6  # 4 帧转过一条螺旋的间隔：首尾接得上
        m = (r > 0.12) & (r < 1.04)
        rm, thm = r[m], th[m]
        # 六道往里卷的螺旋：相位 = 角度 + 卷度 × ln(r)
        phase = 6 * (thm + rot) + 6.0 * np.log(np.maximum(rm, 1e-3))
        arm = (0.5 + 0.5 * np.cos(phase)) ** 14  # 细的笔触
        fade = smoothstep(0.12, 0.5, rm) * smoothstep(1.04, 0.84, rm)
        streaks = dry(tex, np.clip(np.cos(phase) * 1.5, -1, 1), (thm / (2 * math.pi)) % 1.0 + rm * 0.3, 0.45)
        acc.add(m, 0.3 * arm * fade * streaks)
        rim = np.exp(-(((rm - 0.98) / 0.01) ** 2))
        gaps = smoothstep(0.0, 0.05, np.abs(((thm / (2 * math.pi)) * 9 + i / 4) % 1.0 - 0.5) - 0.12)  # 4 帧挪一格，接得上
        acc.add(m, 0.4 * rim * gaps)
        out.append(F.frame_white(acc.a, 9855 + i, peak=0.5))  # 淡淡的一层，不抢塔和妖物
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
WAVE = {
    "wave_front": (make_wave_front_loop, (WAVE_W, WAVE_H), (0.5, (WAVE_Y0 + 1.0) / WAVE_H), "add", True, "white",
                   {"points": "+y", "half_width_px": int(WAVE_SPAN / 2), "tint_hint": "#7CC8FF", "fps": WAVE_FPS, "loop": True,
                    "note": "沧浪的浪头：横着的月牙浪，往图里 +y（下）推进，锚点是正中前沿；half_width_px 是浪头半宽，"
                            "按浪的半宽等比缩放（缩放 = 半宽 ÷（half_width_px ÷ pxPerUnit））；4 帧循环，走到头接 wave_front_fade"}),
    "wave_front_fade": (make_wave_front_fade, (WAVE_W, WAVE_H), (0.5, (WAVE_Y0 + 1.0) / WAVE_H), "add", True, "white",
                        {"points": "+y", "half_width_px": int(WAVE_SPAN / 2), "tint_hint": "#7CC8FF", "fps": WAVE_FPS, "follows": "wave_front",
                         "note": "浪头散掉：接在 wave_front 循环后面播一遍（同画布、同锚点、同缩放），浪身碎成泡沫团、变淡"}),
    "wave_trail": (make_wave_trail, (TRAIL_W, TRAIL_H), (0.5, 1.0), "add", True, "white",
                   {"points": "+y", "half_width_px": int(WAVE_SPAN / 2), "tint_hint": "#7CC8FF", "stretch": "y",
                    "note": "浪身后的泡沫痕：锚点在下边正中（接在浪头后面），横向按浪宽缩放（同 wave_front），"
                            "竖向拉到走过的长度（往 −y），和浪头一起转、一起淡出"}),
}
VINE = {
    "vine": (make_vine, (VINE_W, VINE_H), (1.0, 0.5), "add", True, "white",
             {"points": "+x", "stretch": "x", "height_units": 10, "tint_hint": "#8FE07A", "fps": VINE_FPS, "loop": True,
              "note": "青藤：锚点在右端（放在妖物身上），沿 X 拉到主角（缩放 = 连线长度 ÷ 画布宽），整张高 = 10 世界单位；"
                      "两端在中线上收细；3 帧循环（叶子翻、藤上的弯往妖物那头走）；建议染 #8FE07A"}),
    "vine_pulse": (make_vine_pulse, (PULSE_W, PULSE_H), (PULSE_HEAD[0] / PULSE_W, PULSE_HEAD[1] / PULSE_H), "add", True, "white",
                   {"points": "+x", "tint_hint": "#8FE07A", "loop": True,
                    "note": "每跳回血的绿光：锚点在光头上，头朝 +X（转向主角），游戏沿藤从妖物移到主角；原大；3 帧循环；建议染 #8FE07A"}),
    "vine_bind": (make_vine_bind, (BIND_SIZE, BIND_SIZE), (0.5, 0.72), "add", True, "white",
                  {"radius_px": int(BIND_R), "tint_hint": "#8FE07A", "fps": 8, "hold_last": True,
                   "note": "万木春缠绕：藤从妖物脚下长出来盘三圈裹住；锚点是妖物脚底；radius_px 是缠绕圈的横向半径，按妖物半径缩放；"
                           "0–2 帧长上去，第 3 帧留到缠绕结束再淡出；建议染 #8FE07A"}),
}
LANTERN = {
    "sky_lantern": (make_sky_lantern, (192, 192), (0.5, 0.5), "normal", False, "full",
                    {"fps": 12, "loop": True, "width_units": 20, "height_units": 26,
                     "note": "孔明灯（飘着）：Blender 渲的纸灯，锚点在灯身中心（游戏在这里放辉光和光源）；原大约宽 20、高 26 世界单位，"
                             "按原大画（万灯升可放大一点）；4 帧循环（轻轻摆、灯火一明一暗），发光层见 sky_lantern_emit"}),
    "sky_lantern_emit": (make_sky_lantern_emit, (192, 192), (0.5, 0.5), "add", False, "full",
                         {"fps": 12, "loop": True, "layer_of": "sky_lantern",
                          "note": "孔明灯的发光层：透着灯火的纸，和 sky_lantern 同画布、同锚点、同帧，叠加画在暗层之上"}),
    "sky_lantern_fall": (make_sky_lantern_fall, (192, 192), (0.5, 0.5), "normal", False, "full",
                         {"fps": 12, "follows": "sky_lantern",
                          "note": "孔明灯落地前烧着坠下来：往一边歪倒，纸从下口烧穿，火舌窜起来；落地那一刻接 vfx/fire_burst"}),
    "sky_lantern_fall_emit": (make_sky_lantern_fall_emit, (192, 192), (0.5, 0.5), "add", False, "full",
                              {"fps": 12, "layer_of": "sky_lantern_fall", "note": "坠落帧的发光层（纸和火舌）"}),
    "lantern_mark": (make_lantern_mark, (MARK_W, MARK_H), (0.5, 0.5), "add", True, "white",
                     {"radius_px": int(MARK_R), "flat": F.FLAT, "tint_hint": "#C23A2B",
                      "note": "孔明灯的落点圈：地上一圈断续的干笔圆，四道往里指的短笔、正中小十字，已压扁；radius_px 是圈的横向半径，"
                              "按爆燃半径缩放（落地前 1 秒出现，可以从 1.2 倍收紧到 1 倍）；建议染暗红 #C23A2B，越接近落地越亮"}),
    "fire_sea": (make_fire_sea, (SEA_W, SEA_H), (0.5, 0.5), "add", False, "full",
                 {"radius_px": int(SEA_R), "flat": F.FLAT, "fps": 12, "loop": True,
                  "note": "孔明灯的火海：地上一片低矮的火苗（已压扁），自带火色、不染；radius_px 是火海的横向半径，按 0.8 × 爆燃半径缩放；"
                          "4 帧循环，3 秒后淡出"}),
}
TOWER_SRC = {"tower": 448, "tower_gold": 576}  # Blender 源图的画布（2 倍），下面再垫 TOWER_PAD 行


def _tower_specs(asset: str, title: str, units: str) -> dict:
    size = TOWER_SRC[asset]
    wh = (size, size + TOWER_PAD)
    anc = (0.5, 0.88 * size / (size + TOWER_PAD))
    base = f"{title}：Blender 渲的七层塔，锚点在塔基座中心（落地点）；原大{units}，"
    return {
        asset: (_tower_maker(asset, "idle", 0), wh, anc, "normal", False, "full",
                {"fps": 4, "loop": True, "note": base + "立着时 2 帧循环（檐角铜铃往两边摆）；发光层见 " + asset + "_emit"}),
        f"{asset}_emit": (_tower_maker(asset, "idle", 1), wh, anc, "add", False, "full",
                          {"fps": 4, "loop": True, "layer_of": asset, "note": f"{title}的发光层：拱门里的光"}),
        f"{asset}_fall": (_tower_maker(asset, "fall", 0), wh, anc, "normal", False, "full",
                          {"note": f"{title}从天上砸下来：0 帧在上方 26 单位、拉长，1 帧快落地，2 帧落地压扁一下；上方拖几道墨的速度线"}),
        f"{asset}_fall_emit": (_tower_maker(asset, "fall", 1), wh, anc, "add", False, "full",
                               {"layer_of": f"{asset}_fall", "note": "落下帧的发光层"}),
        f"{asset}_lift": (_tower_maker(asset, "lift", 0), wh, anc, "normal", False, "full",
                          {"fps": 12, "note": f"{title}收走：往上升，从下往上散成金色的光点"}),
        f"{asset}_lift_emit": (_tower_maker(asset, "lift", 1), wh, anc, "add", False, "full",
                               {"fps": 12, "layer_of": f"{asset}_lift", "note": "收走帧的发光层：金边、散开处的金光"}),
    }


TOWER = {
    **_tower_specs("tower", "镇妖塔", "约宽 40、高 70 世界单位（半径 45 时的大小）"),
    **_tower_specs("tower_gold", "玲珑塔", "约宽 56、高 96 世界单位（半径 60 时的大小）"),
    "tower_dust": (make_tower_dust, (DUST_W, DUST_H), (0.5, 0.5), "normal", False, DUST_INK,
                   {"radius_px": int(DUST_R), "flat": F.FLAT,
                    "note": "镇妖塔落地的尘土冲击波：一圈尘团往外滚开（已压扁），土墨色、普通混合、不染；radius_px 是末帧尘环的横向半径，按落地半径缩放"}),
    "tower_vortex": (make_tower_vortex, (VORTEX_W, VORTEX_H), (0.5, 0.5), "add", True, "white",
                     {"radius_px": int(VORTEX_R), "flat": F.FLAT, "fps": 12, "loop": True, "tint_hint": "#C9925A",
                      "note": "镇妖塔吸妖的范围：地上淡淡的旋涡（已压扁），螺旋往里转；radius_px 是旋涡的横向半径，按吸的范围（2.2R）缩放；"
                              "4 帧循环；建议染土色 #C9925A"}),
}
BATCHES = {"coin": COIN, "wave": WAVE, "vine": VINE, "lantern": LANTERN, "tower": TOWER}
TITLES = {"coin": "铜钱剑", "wave": "沧浪", "vine": "青藤", "lantern": "孔明灯", "tower": "镇妖塔"}
NOTES = {"coin": f"叠加帧审图染色：可染的按建议色（{COIN_TINT} 铜金），铜钱火星自带颜色",
         "wave": "叠加帧审图染色：浪头、泡沫痕按游戏的水色 #7CC8FF",
         "vine": "叠加帧审图染色：藤、绿光、缠绕按游戏的青绿 #8FE07A",
         "lantern": "孔明灯是 Blender 渲的普通混合 + 发光层（叠加）；落点圈按建议的暗红 #C23A2B，火海自带火色",
         "tower": "镇妖塔、玲珑塔是 Blender 渲的普通混合 + 发光层（叠加）；尘土是土墨色、普通混合；旋涡按建议的土色 #C9925A"}
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
    "vine": {
        "": [  # Lv8：连 5 只（连线距离 170 以内）；第二只身上缠着（万木春的缠绕），一颗绿光正往回流
            ("vine", 0, (62.0, -82.0), "body", None, {"to": (0.0, 12.0), "h_units": 10.0}),
            ("vine", 1, (125.0, 72.0), "body", None, {"to": (0.0, 12.0), "h_units": 10.0}),
            ("vine", 2, (-168.0, -100.0), "body", None, {"to": (0.0, 12.0), "h_units": 10.0}),
            ("vine_pulse", 1, (31.0, -35.0), "body", None, {"face": (0.0, 12.0)}),
            ("vine_bind", 3, (-168.0, -100.0), "feet", 18.0),
        ],
    },
    "lantern": {
        "": [  # Lv8：两盏灯飘着，一盏快落地（落点圈），另一处烧着的火海
            ("lantern_mark", 0, (125.0, 72.0), "ground", 56.0),
            ("sky_lantern", 0, (125.0, 72.0), "air", None),
            ("sky_lantern_emit", 0, (125.0, 72.0), "air", None),
            ("sky_lantern", 2, (-150.0, -60.0), "air", None),
            ("sky_lantern_emit", 2, (-150.0, -60.0), "air", None),
            ("fire_sea", 1, (-238.0, 58.0), "ground", 45.0),
            ("sky_lantern_fall", 1, (250.0, 128.0), "low", None),
            ("sky_lantern_fall_emit", 1, (250.0, 128.0), "low", None),
        ],
    },
    "tower": {
        "": [  # 镇妖塔立着（吸的范围 2.2R），另一座刚砸下来扬起尘土；玲珑塔在左边
            ("tower_vortex", 1, (125.0, 30.0), "ground", 132.0),
            ("tower", 0, (125.0, 30.0), "feet", None),
            ("tower_emit", 0, (125.0, 30.0), "feet", None),
            ("tower_dust", 2, (260.0, -110.0), "ground", 60.0),
            ("tower_fall", 2, (260.0, -110.0), "feet", None),
            ("tower_fall_emit", 2, (260.0, -110.0), "feet", None),
            ("tower_gold", 1, (-200.0, 40.0), "feet", None),
            ("tower_gold_emit", 1, (-200.0, 40.0), "feet", None),
        ],
    },
    "wave": {
        "": [  # 主角往下（+y）推出一道 Lv8 的浪（半宽 80），走了 150；身后的泡沫痕拉到 150 长
            ("wave_trail", 0, (0.0, 168.0), "ground", None, {"size_units": (160.0 * TRAIL_W / WAVE_SPAN, 150.0)}),
            ("wave_front", 1, (0.0, 168.0), "ground", 80.0),
            ("wave_front_fade", 1, (-260.0, 120.0), "ground", 50.0),  # Lv1 的浪（半宽 50）走到头散掉
        ],
    },
}


def main(only: list[str] | None = None) -> None:
    """only 给出时只画这几件（命令行：weapon_textures_ea.py wave vine）。"""
    import vfx_frames_review as R  # noqa: PLC0415  审图共用 vfx_frames 的

    t0 = time.perf_counter()
    for key, batch in BATCHES.items():
        if only and key not in only:
            continue
        frames = F.build(batch)
        F.write(frames, batch, out=OUT, name="weapons", generator=GENERATOR)
        R.strip_sheet(key, batch, frames, REVIEW / f"weapons_ea_{key}.png", title=f"新法器 · {TITLES[key]}", note=NOTES[key])
        for suffix, placements in INGAME[key].items():
            R.ingame(key, batch, frames, REVIEW / f"weapons_ea_{key}{suffix}_ingame.png", placements=placements, title=f"新法器 · {TITLES[key]}")
        print(f"{key}: {sum(len(v) for v in frames.values())} 帧  {time.perf_counter() - t0:.1f}s")


if __name__ == "__main__":
    main(sys.argv[1:])
