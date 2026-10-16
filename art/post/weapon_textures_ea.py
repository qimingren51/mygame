#!/usr/bin/env python3
"""提灯夜行 · 抢先体验五件新法器的贴图（docs/BALANCE.md 6.3 节各件的“画面”）。只出桌面版 2 倍，Pillow + numpy。

帧名照 weapons/* 的写法：weapons/<名字>_<帧号>（帧号从 0 起，一位数），和 vfx 图集一起打包（$A/weapons_ea）。
动画帧的约定同 vfx_frames.py：一次性的按 24 帧/秒，meta 写 anim、frame、frames、fps、loop；叠加帧最亮处 alpha 0.8、
边缘是飞白和干笔；可染的 RGB 恒为白；有方向的朝 +X。

铜钱剑（金）：挥击的扇形刀光直接用 vfx/slash_0..5（vfx_frames.py），建议染铜金 #F2C46A。这里补它特有的：
  weapons/coin_spark_0..4   命中的铜钱火星（约 16 世界单位）：接触点一闪，火星顺着入射方向（+X）溅出去，
                            两枚小铜钱翻着飞；自带铜金色、不染
  weapons/coin_whirl_0..5   天罡：周身一圈旋风刀光（半径 100），0.25 秒；白色可染；radius_px 是外沿半径
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


def union_heat(parts: list[tuple[np.ndarray, float | np.ndarray]]) -> tuple[np.ndarray, np.ndarray]:
    """几层 (亮度, 热度) 合起来：亮度按 1 − ∏(1 − a)，热度按亮度加权平均。"""
    a = soft_union(*[p for p, _ in parts])
    wsum = sum(np.clip(p, 0, 1) for p, _ in parts)
    hsum = sum(np.clip(p, 0, 1) * h for p, h in parts)
    return a, hsum / np.maximum(wsum, 1e-6)


def frame_color(a_ss: np.ndarray, heat_ss: np.ndarray, seed: int, palette=COPPER, peak: float = F.PEAK) -> Image.Image:
    """自带颜色的叠加帧：alpha 同 vfx_frames.frame_white（软饱和到 peak、蓝噪声抖动、四边为 0），
    颜色按热度在调色板里插值（热度按亮度加权缩小）。"""
    a_ss = np.clip(a_ss, 0, None)
    a = V.downsample(a_ss, SS)
    heat = V.downsample(a_ss * np.clip(heat_ss, 0, 1), SS) / np.maximum(a, 1e-6)
    a = peak * np.tanh(1.25 * np.clip(a, 0.0, 1.0)) / math.tanh(1.25)
    a8 = V.dither_alpha(a, np.random.default_rng(seed))
    a8[a < 0.004] = 0
    a8[0, :] = a8[-1, :] = a8[:, 0] = a8[:, -1] = 0
    xs = [p for p, _ in palette]
    cols = np.array([V.col(c) for _, c in palette])
    rgb = np.stack([np.interp(np.clip(heat, 0, 1), xs, cols[:, k]) for k in range(3)], -1)
    return V.to_rgba8(rgb, None, a8)


def crescent(r, g, *, head: float, tail: float, rim, thick: float, tex, t_off: float, dryk: float):
    """沿弧的月牙笔锋（刀光、旋风共用）。g 是像素沿弧的位置（度，已展开），head > tail；rim 是外沿半径（可随位置变）。
    返回 (亮度, 沿弧 0..1)。外沿一道利的亮线，往里渐淡、起飞白；最厚处在笔锋后面一点，两头收尖。"""
    span = max(head - tail, 1e-3)
    v = (g - tail) / span
    inside = (v > 0) & (v < 1)
    vc = np.clip(v, 0, 1)
    shape = np.sin(np.pi * vc**1.6) ** 0.8
    rr = rim(vc) if callable(rim) else rim
    T = thick * shape
    s = (rr - r) / np.maximum(T, 0.5)
    body = smoothstep(rr + 1.0, rr - 1.0, r) * smoothstep(1.0, 0.5, s) * np.exp(-1.5 * np.clip(s, 0, None))
    edge = np.exp(-(((r - (rr - 1.6)) / 1.7) ** 2)) * shape**0.4
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


# ============================================================== 铜钱剑：天罡旋风

WHIRL_SIZE = 448
WHIRL_R = 192.0  # 外沿半径（像素）；火星再往外飘十几像素，不出画布


def make_coin_whirl() -> list[Image.Image]:
    """天罡：周身一圈旋风刀光。三道主刀光（月牙笔锋，头亮、尾巴拖细、往里旋）相隔 120°，顺时针转（图里 y 向下），
    里圈三道淡一些的错开 60°；弧里几道速度线；前两帧从里往外张开到外沿，末两帧越转越慢、碎成干笔丝，笔锋甩出火星。
    白色，可染（建议铜金 #F2C46A）。"""
    size = WHIRL_SIZE
    X, Y = grid(size, size)
    cx = cy = size / 2
    R = WHIRL_R
    rng = np.random.default_rng(9851)
    tex = W.ptex(rng, ns=28, nt=2048, along=40.0, across=0.6)
    dx, dy = X - cx, Y - cy
    r = np.hypot(dx, dy)
    th = np.degrees(np.arctan2(dy, dx))  # −180..180，顺时针为正
    spin = [0.0, 62.0, 118.0, 166.0, 204.0, 232.0]  # 转过的角度（越转越慢）
    grow = [0.6, 0.9, 1.0, 1.0, 1.0, 1.0]
    length = [70.0, 150.0, 178.0, 178.0, 150.0, 108.0]
    thick = [24.0, 38.0, 42.0, 36.0, 26.0, 15.0]
    env = [0.9, 1.0, 1.0, 0.8, 0.52, 0.26]
    dryk = [0.06, 0.04, 0.08, 0.24, 0.4, 0.55]
    blades = [(a0 + rng.uniform(-6, 6), rf, br, off) for a0, rf, br, off in
              ((0.0, 1.0, 1.0, 0.0), (120.0, 1.0, 1.0, 0.31), (240.0, 1.0, 1.0, 0.62), (60.0, 0.72, 0.55, 0.15), (180.0, 0.72, 0.55, 0.47), (300.0, 0.72, 0.55, 0.78))]
    lines = [(rng.uniform(0.42, 0.88), rng.uniform(0, 360), rng.uniform(40, 100), rng.uniform(0.7, 1.4)) for _ in range(9)]
    sparks = [(rng.integers(0, 3), rng.uniform(-6, 6), rng.uniform(12, 24), rng.uniform(0.8, 1.2), rng.uniform(0.25, 0.6)) for _ in range(12)]
    out = []
    for i in range(6):
        a = []
        for a0, rf, br, off in blades:
            hd = a0 + spin[i]
            L = length[i] * (1.0 if rf == 1.0 else 0.8)
            # 把像素的角度展开到 (hd − 360, hd]，笔锋在 hd，尾巴在 hd − L
            g = hd - np.mod(hd - th, 360.0)
            rim_r = R * grow[i] * rf
            c, _ = crescent(r, g, head=hd, tail=hd - L, rim=lambda v, rr=rim_r: rr * (0.86 + 0.14 * v), thick=thick[i] * rf,
                            tex=tex, t_off=off, dryk=dryk[i])
            a.append(env[i] * br * c)
            if i <= 2 and rf == 1.0:  # 笔锋的亮点
                ha = math.radians(hd)
                a.append(0.85 * env[i] * np.exp(-((np.hypot(X - cx - (rim_r - 4) * math.cos(ha), Y - cy - (rim_r - 4) * math.sin(ha)) / 4.5) ** 2)))
        for rf, a0, ln, wd in lines:  # 速度线：跟着转
            hd = a0 + spin[i] * 0.9
            g = hd - np.mod(hd - th, 360.0)
            uu = np.clip((g - (hd - ln)) / ln, 0, 1)
            rr = R * grow[i] * rf
            prof = np.exp(-(((r - rr) / wd) ** 2))
            a.append(0.32 * env[i] * prof * np.sin(np.pi * uu) ** 0.7 * dry(tex, np.clip((r - rr) / (3 * wd), -1, 1), g / 360.0 + rf, 0.3 + 0.3 * (1 - uu)))
        if i >= 2:  # 火星：第 2 帧从三道主刀光的笔锋甩出去，之后直线飞、变淡
            tk = (i - 2) / 3
            for j, ds, d1, sz, out_k in sparks:
                hd = math.radians(blades[int(j)][0] + spin[2] + ds)
                tan = np.array([-math.sin(hd), math.cos(hd)])
                nrm = np.array([math.cos(hd), math.sin(hd)])
                p0 = np.array([cx, cy]) + nrm * (R + 4)
                dirv = tan + nrm * out_k
                dirv /= np.linalg.norm(dirv)
                p1 = p0 + dirv * d1 * (0.3 + 0.7 * tk)
                p_tail = p1 - dirv * (8 * (1 - tk) + 3)
                a.append(0.8 * (1 - 0.75 * tk) * streak(X, Y, p_tail[0], p_tail[1], p1[0], p1[1], sz))
        out.append(F.frame_white(soft_union(*a), 9860 + i))
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
    "coin_spark": (make_coin_spark, (SPARK_W, SPARK_H), (SPARK_C[0] / SPARK_W, SPARK_C[1] / SPARK_H), "add", False, "full",
                   {"points": "+x", "note": "铜钱剑命中的铜钱火星（约 16 世界单位）：锚点是接触点，火星朝 +X 溅，按入射方向转；自带铜金色，不染"}),
    "coin_whirl": (make_coin_whirl, (WHIRL_SIZE, WHIRL_SIZE), (0.5, 0.5), "add", True, "white",
                   {"radius_px": int(WHIRL_R), "tint_hint": COIN_TINT,
                    "note": "天罡：周身一圈旋风刀光，顺时针转（图里 y 向下）；radius_px 是外沿半径，按旋风半径缩放；建议染铜金 #F2C46A"}),
    "coin_cross": (make_coin_cross, (160, 160), (0.5, 0.5), "add", True, "white",
                   {"tint_hint": COIN_TINT, "note": "天罡的再斩：目标身上的十字斩痕（约 30 世界单位，原大），0.15 秒；建议染铜金 #F2C46A"}),
}
BATCHES = {"coin": COIN}
TITLES = {"coin": "铜钱剑"}
INGAME = {
    "coin": [
        ("coin_whirl", 2, (0.0, 12.0), "hero", 100.0),  # 天罡的半径 100
        ("coin_spark", 1, (62.0, -82.0), "body", None),
        ("coin_spark", 2, (125.0, 72.0), "body", None),
        ("coin_cross", 1, (-168.0, -100.0), "body", None),
        ("coin_spark", 3, (-238.0, 58.0), "body", None),
        ("coin_cross", 2, (250.0, 128.0), "body", None),
        ("coin_spark", 1, (288.0, -128.0), "body", None),
    ],
}


def main() -> None:
    import vfx_frames_review as R  # noqa: PLC0415  审图共用 vfx_frames 的

    t0 = time.perf_counter()
    for key, batch in BATCHES.items():
        frames = F.build(batch)
        F.write(frames, batch, out=OUT, name="weapons", generator=GENERATOR)
        note = f"叠加帧审图染色：可染的按建议色（{COIN_TINT} 铜金），铜钱火星自带颜色"
        R.strip_sheet(key, batch, frames, REVIEW / f"weapons_ea_{key}.png", title=f"新法器 · {TITLES[key]}", note=note)
        R.ingame(key, batch, frames, REVIEW / f"weapons_ea_{key}_ingame.png", placements=INGAME[key], title=f"新法器 · {TITLES[key]}")
        print(f"{key}: {sum(len(v) for v in frames.values())} 帧  {time.perf_counter() - t0:.1f}s")


if __name__ == "__main__":
    main()
