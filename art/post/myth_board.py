#!/usr/bin/env python3
"""神话特效的样张分镜（docs/FEEL.md 13.2 的四个演出，典故见 docs/LORE.md 9.14）。只读图集和 myth_parts 的元件，不写 assets。

每个演出 4 格关键帧，按 FEEL 13.2 的“分段”挑时刻；格子是 1080p 游戏画面（myth_scene 合成：月夜底色 + 宣纸 + 灯笼光照池，
叠加特效在暗层之上 × 1.5，普通混合的墨在暗层之下，再过辉光、暗角），缩到 960×540 拼成 2×2，格下一行字写第几秒、在发生什么。
“代码”那一栏的东西（剑影排阵、拖尾、光点、浪花、冰碴、狐火环、化灰）这里用现成贴图和简单的笔画摆出来，示意排法。

产物：art/out/review@2x/myth_<演出>_board.png（分镜条）、myth_<演出>_hero.png（最出彩的一格，1920×1080 原大）
用法（仓库根目录）：
  art/.venv/bin/python art/post/myth_board.py sword            # 一个演出：分镜条 + 原大图
  art/.venv/bin/python art/post/myth_board.py sword:2 kun:3     # 只出某一格（试构图），写到 out/myth_try/<演出>_<格>.png
"""

from __future__ import annotations

import math
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

import myth_parts as P  # noqa: E402
import myth_scene as Z  # noqa: E402

V, M = Z.V, Z.M
lin = Z.lin
REVIEW = V.OUT / "review@2x"
TRY = V.OUT / "myth_try"
SW, SH = Z.SW, Z.SH
FLAT = 0.62
GOLD_T = lin("#FFE7A8").astype(np.float32)
GOLD_DEEP = lin("#F2C46A").astype(np.float32)
WARM_WHITE = lin("#FFF4DC").astype(np.float32)


def parts(name):
    if name not in _CACHE:
        _CACHE[name] = P.load(name)
    return _CACHE[name]


_CACHE: dict = {}


# ============================================================== 万剑归宗


def ring_pos(cam, cx, cy, R, th, h):
    """地面上（压扁 0.62）半径 R、高 h 的一圈上，角 th 处的画面坐标。"""
    return cam.s(cx + R * math.cos(th), cy + FLAT * R * math.sin(th), h)


def sword_at(img, cam, x, y, ang, variant, scale=1.0, alpha=1.0, tint=GOLD_T):
    blade = parts("sword_blade")[variant]
    Z.blit(img, Z.pm_of(blade, tint=tint), x, y, (0.5, 0.5), cam.sprite * scale, angle=ang, mode="add", gain=Z.EMIT * alpha)


def trail(img, pts, w0, a0, color=GOLD_T, gain=Z.EMIT):
    """拖尾（fx/streak 的示意）：pts 从尾到头，头粗、亮，尾细、淡。"""
    n = len(pts)
    t = np.linspace(0, 1, n)
    Z.stroke(img, pts, w0 * (0.15 + 0.85 * t), color, alpha=a0 * t**1.4, gain=gain)


def river_swords(cam, t_head, n=120, turns=2.0, R0=118.0, R1=82.0, h0=8.0, h1=44.0, hero=Z.HERO, seed=1, spread=1.0, size=(1.3, 1.65), tail=(0.3, 0.55)):
    """剑河：n 柄剑沿两圈螺旋排开（外圈低、内圈高），逆时针绕身。返回 [(x, y, ang, variant, scale, alpha, trail_pts)]。"""
    rng = np.random.default_rng(seed)
    out = []
    hx, hy = hero
    for j in range(n):
        s = j / n  # 0 是剑头（最里、最高），1 是剑尾
        th = t_head - s * turns * 2 * math.pi + rng.uniform(-0.05, 0.05)
        R = R1 + (R0 - R1) * s + rng.normal(0, 9) * spread
        h = h1 + (h0 - h1) * s + rng.normal(0, 5) * spread + 22.0
        x, y = ring_pos(cam, hx, hy, R, th, h)
        x2, y2 = ring_pos(cam, hx, hy, R, th + 0.02, h)
        ang = math.atan2(y2 - y, x2 - x)
        back = math.sin(th) < 0  # 远侧
        sc = rng.uniform(*size) * (0.88 if back else 1.06)
        al = rng.uniform(0.75, 1.0) * (0.72 if back else 1.0)
        L = rng.uniform(*tail)
        tp = [ring_pos(cam, hx, hy, R, th - L * (1 - q), h) for q in np.linspace(0, 1, 9)]
        out.append((x, y, ang, int(rng.integers(3)), sc, al, tp))
    return out


def incoming_swords(cam, n, t, seed=2, hero=Z.HERO):
    """还在路上的剑：从四周（妖物堆里、画面边上）沿弧线飞进来，汇进剑河。t 是进度 0..1。"""
    rng = np.random.default_rng(seed)
    out = []
    hx, hy = hero
    for j in range(n):
        th0 = rng.uniform(0, 2 * math.pi)
        p = np.clip(t + rng.uniform(-0.25, 0.15), 0, 1)
        R = 360 - (360 - 125) * p
        th = th0 + 1.6 * p
        h = 4 + 26 * p + 22
        x, y = ring_pos(cam, hx, hy, R, th, h)
        tp = []
        for q in np.linspace(max(p - 0.35, 0), p, 10):
            tp.append(ring_pos(cam, hx, hy, 360 - 235 * q, th0 + 1.6 * q, 4 + 26 * q + 22))
        x2, y2 = tp[-2]
        ang = math.atan2(y - y2, x - x2)
        out.append((x, y, ang, int(rng.integers(3)), rng.uniform(1.2, 1.5), rng.uniform(0.6, 0.95), tp))
    return out


def draw_swords(img, cam, swords, trail_w=1.8, trail_a=0.3, echoes=0):
    """先画拖尾再画剑。echoes > 0 时每柄剑沿拖尾再留几道残影（越往后越淡）：代码多画几次同一张剑影，看着就是成百上千柄。"""
    for x, y, ang, v, sc, al, tp in swords:
        if tp:
            trail(img, tp, trail_w * sc, trail_a * al)
    for x, y, ang, v, sc, al, tp in swords:
        if echoes and tp:
            for e in range(1, echoes + 1):
                q = 1 - e / (echoes + 1)
                i = q * (len(tp) - 1)
                i0 = int(i)
                f = i - i0
                p0, p1 = tp[i0], tp[min(i0 + 1, len(tp) - 1)]
                ex, ey = p0[0] + (p1[0] - p0[0]) * f, p0[1] + (p1[1] - p0[1]) * f
                sword_at(img, cam, ex, ey, ang, v, sc * (1 - 0.06 * e), al * 0.42 * q)
        sword_at(img, cam, x, y, ang, v, sc, al)


def god_rays(img, x0, y0, n, spread, length, color, alpha, seed, width=(30, 90)):
    """从一点往下散开的几道光（云缝里漏下来的光）：每道是一条越往下越宽、越淡的光带。"""
    rng = np.random.default_rng(seed)
    for k in range(n):
        ang = math.pi / 2 + (k / max(n - 1, 1) - 0.5) * 2 * spread + rng.uniform(-0.05, 0.05)
        L = length * rng.uniform(0.7, 1.0)
        x1, y1 = x0 + L * math.cos(ang), y0 + L * math.sin(ang)
        w = rng.uniform(*width)
        Z.stroke(img, [(x0, y0), (x1, y1)], [w * 0.25, w], color, alpha=[alpha * rng.uniform(0.7, 1.2), 0.0], soft=w * 0.35, gain=Z.EMIT)


def cloud_layer(fi, alpha=1.0, emit=True, cy=124.0, scale=2.0, emit_gain=1.0):
    """镜头上方的云：画布中心放在画面 (960, cy)，按画面宽度放大。本体在暗层之下（over 钩子），发光层在暗层之上（add 钩子）。"""
    body = parts("sword_cloud")[fi]
    em = parts("sword_cloud_emit")[fi]

    def sky(img, cam):
        Z.blit(img, Z.pm_of(body), SW / 2 + cam.shake[0], cy + cam.shake[1], (0.5, 0.5), scale, alpha=alpha)
        if emit:
            Z.blit(img, Z.pm_of(em), SW / 2 + cam.shake[0], cy + cam.shake[1], (0.5, 0.5), scale, mode="add", gain=Z.EMIT * alpha * emit_gain)

    return sky


def light_ring(lm, cam, cx, cy, R, color, gain, n=28, r_units=34.0, h=0.0):
    """光照图里沿一圈放一串小光（剑河照亮地面）。光照图是半分辨率。"""
    for k in range(n):
        th = 2 * math.pi * k / n
        x, y = cam.s(cx + R * math.cos(th), cy + FLAT * R * math.sin(th), h)
        Z.glow(lm, x / 2, y / 2, r_units * cam.k / 2, color, gain, power=1.6)


def spot_light(lm, cam, x, y, r_units, color, gain, power=1.4):
    sx, sy = cam.s(x, y)
    Z.glow_ellipse(lm, sx / 2, sy / 2, r_units * cam.k / 2, r_units * FLAT * cam.k / 2, color, gain, power=power)


def sword_panel(k: int) -> tuple[Z.Shot, str]:
    hx, hy = Z.HERO
    if k == 0:
        cam = Z.Cam(z=1.06, cy=4.0)
        shot = Z.Shot(cam=cam, actors=Z.default_actors(), ambient=S_DIM(0.72), pool=0.55, bloom=0.3, vignette=0.42, desat=0.12)

        def light(lm, cam):
            spot_light(lm, cam, hx, hy, 46, GOLD_T, 1.6, power=1.2)
            spot_light(lm, cam, hx, hy, 95, GOLD_DEEP, 0.35, power=1.5)

        def add(img, cam):
            x, y = cam.s(hx, hy, 20)
            # 头顶聚光：一束从画面上方落到主角身上的光，地上一团压扁的亮
            pts = [(x, -20), (x, y - 30)]
            Z.stroke(img, pts, [70, 40], GOLD_T, alpha=[0.05, 0.22], soft=24)
            Z.stroke(img, pts, [16, 8], WARM_WHITE, alpha=[0.05, 0.35], soft=6)
            gx, gy = cam.s(hx, hy)
            Z.glow_ellipse(img, gx, gy, 70, 70 * FLAT, GOLD_T, 0.5, power=1.5)
            pil = parts  # noqa: F841
            pillar = M.atlas_frame("vfx", "vfx/evolve_pillar_1")[0]
            Z.blit(img, Z.pm_of(pillar), gx, gy, (0.5, 1.0), cam.sprite * 1.1, mode="add", gain=Z.EMIT * 0.55)
            # 四周的剑影刚从地上立起来：竖着，带一小截从地上拉起的光
            rng = np.random.default_rng(31)
            for j in range(64):
                th = 2 * math.pi * j / 64 + rng.uniform(-0.04, 0.04)
                R = rng.uniform(150, 330)
                lift = rng.uniform(4, 22)
                sx, sy = ring_pos(cam, hx, hy, R, th, lift)
                bx, by = ring_pos(cam, hx, hy, R, th, 0)
                Z.stroke(img, [(bx, by), (sx, sy + 10)], [1.0, 2.6], GOLD_T, alpha=[0.0, 0.45], gain=Z.EMIT)
                Z.glow_ellipse(img, bx, by, 9, 4, GOLD_T, 0.35)
                sword_at(img, cam, sx, sy, -math.pi / 2 + rng.uniform(-0.12, 0.12), int(rng.integers(3)), rng.uniform(0.85, 1.1), rng.uniform(0.45, 0.85))

        shot.sky.append(cloud_layer(0, alpha=0.55, emit=False))
        shot.light.append(light)
        shot.add.append(add)
        return shot, "0.25 秒 · 顿帧、推近 6%：头顶一束聚光落到主角身上，四周地上一柄柄剑影立起来；天上的云开始聚"
    if k == 1:
        cam = Z.Cam(z=1.06, cy=4.0)
        shot = Z.Shot(cam=cam, actors=Z.default_actors(), ambient=S_DIM(0.72), pool=0.55, bloom=0.28, vignette=0.38)
        river = river_swords(cam, t_head=2.4, n=96)
        inc = incoming_swords(cam, 24, 0.75)

        def light(lm, cam):
            light_ring(lm, cam, hx, hy, 104, GOLD_T, 0.2, n=30)
            spot_light(lm, cam, hx, hy, 50, GOLD_T, 0.3)

        def add(img, cam):
            draw_swords(img, cam, inc, trail_w=1.8, trail_a=0.32)
            draw_swords(img, cam, river)

        shot.sky.append(cloud_layer(0, alpha=0.95, emit=False))
        shot.light.append(light)
        shot.add.append(add)
        return shot, "1.2 秒 · 120 柄剑影从四周飞来，螺旋汇成剑河绕身两圈（外圈低、内圈高），每柄拖一道光；云压满上空"
    if k == 2:
        cam = Z.Cam(z=1.06, cy=4.0, shake=(5.0, -3.0))
        shot = Z.Shot(cam=cam, actors=Z.default_actors(), ambient=S_DIM(0.7), pool=0.5, bloom=0.61, vignette=0.34)
        rng = np.random.default_rng(41)
        col = []
        bx, by = cam.s(hx, hy, 26)
        for j in range(90):  # 剑柱：三股拧在一起往上冲，越往上越散开一点
            strand = j % 3
            hh = rng.uniform(30, 340)
            spread = 0.55 + 0.45 * min(hh / 140, 1)
            phase = hh / 34.0 + strand * 2 * math.pi / 3
            xo = 40 * spread * math.sin(phase) + rng.normal(0, 4)
            x, y = cam.s(hx + xo, hy, 26 + hh)
            sc = rng.uniform(1.5, 1.9) * (1.1 - 0.2 * min(hh / 300, 1))
            ang = -math.pi / 2 + 0.22 * math.cos(phase) * spread
            L = rng.uniform(40, 90)
            tp = [(x - L * (1 - q) * math.cos(ang), y - L * (1 - q) * math.sin(ang)) for q in np.linspace(0, 1, 6)]
            col.append((x, y, ang, int(rng.integers(3)), sc, rng.uniform(0.48, 0.72), tp))
        funnel = river_swords(cam, t_head=4.2, n=30, turns=1.0, R0=100, R1=28, h0=8, h1=56, seed=7, spread=0.6, size=(1.35, 1.6))

        def light(lm, cam):
            spot_light(lm, cam, hx, hy, 70, GOLD_T, 0.45, power=1.1)
            spot_light(lm, cam, hx, hy, 200, GOLD_DEEP, 0.18, power=1.6)

        def add(img, cam):
            top = -60
            god_rays(img, SW / 2 + cam.shake[0], 170, 11, 0.7, 1150, GOLD_T, 0.11, 61, width=(40, 120))
            Z.stroke(img, [(bx, top), (bx, by)], [170, 130], GOLD_DEEP, alpha=[0.04, 0.06], soft=70)
            Z.stroke(img, [(bx, top), (bx, by)], [44, 34], GOLD_T, alpha=[0.05, 0.1], soft=18)
            Z.stroke(img, [(bx, top), (bx, by)], [5, 4], WARM_WHITE, alpha=[0.15, 0.25], soft=3)
            draw_swords(img, cam, funnel, trail_w=1.8, trail_a=0.25, echoes=1)
            draw_swords(img, cam, col, trail_w=1.4, trail_a=0.24, echoes=2)
            gx, gy = cam.s(hx, hy)
            sw = M.atlas_frame("vfx", "vfx/shockwave_2")[0]
            Z.blit(img, Z.pm_of(sw, tint=GOLD_T), gx, gy, (0.5, 0.5), cam.sprite * 1.25, mode="add", gain=Z.EMIT * 0.3)
            Z.glow_ellipse(img, gx, gy, 80, 80 * FLAT, GOLD_T, 0.08, power=1.8)
            Z.glow(img, SW / 2 + cam.shake[0], 250, 120, GOLD_T, 0.12, power=2.2)  # 剑柱顶开云的地方亮一团

        shot.sky.append(cloud_layer(3, cy=140.0, scale=2.1))
        shot.light.append(light)
        shot.add.append(add)
        return shot, "2.0 秒 · 剑河冲天，三股拧成一道剑柱，把上空的云劈开（上决浮云），缝里漏下金光；震屏 0.35、辉光猛涨"
    # k == 3
    cam = Z.Cam(z=1.03, cy=4.0)
    shot = Z.Shot(cam=cam, actors=Z.default_actors(), ambient=S_DIM(0.85), pool=0.8, bloom=0.4, vignette=0.3)
    rng = np.random.default_rng(51)
    bx, by = cam.s(hx, hy, 26)

    def light(lm, cam):
        spot_light(lm, cam, hx, hy, 80, GOLD_T, 0.5)
        for _ in range(26):  # 落下的光点照亮地面一小片
            x, y = rng.uniform(-330, 330), rng.uniform(-190, 190)
            spot_light(lm, cam, x, y, rng.uniform(8, 16), GOLD_T, 0.16, power=2.0)

    def add(img, cam):
        Z.stroke(img, [(bx, -40), (bx, by)], [60, 40], GOLD_T, alpha=[0.05, 0.16], soft=24)
        r2 = np.random.default_rng(52)
        for j in range(380):  # 剑影化成的光点往下落：剑柱那一带密、上面密，竖着拖一小截
            near_col = r2.random() < 0.35
            x = r2.normal(SW / 2, 90 if near_col else 520) if r2.random() < 0.8 else r2.uniform(0, SW)
            y = r2.uniform(-10, SH) * (0.45 + 0.55 * r2.random())
            if not (0 < x < SW):
                continue
            r = r2.uniform(1.2, 3.2)
            L = r2.uniform(8, 26) * r / 2
            a = r2.uniform(0.35, 1.0)
            Z.stroke(img, [(x, y - L), (x, y)], [0.3, 1.6 * r], GOLD_T, alpha=[0.0, 0.6 * a], gain=Z.EMIT)
            Z.glow(img, x, y, r * 2.2, WARM_WHITE, 0.9 * a, power=2.0)
        for j in range(18):  # 还没散完的几柄，半透明、竖着往下掉
            x, y = r2.normal(SW / 2, 260), r2.uniform(60, 520)
            sword_at(img, cam, x, y, math.pi / 2 + r2.uniform(-0.3, 0.3), int(r2.integers(3)), 1.1, r2.uniform(0.25, 0.5))

    shot.sky.append(cloud_layer(5))
    shot.light.append(light)
    shot.add.append(add)
    return shot, "2.45 秒 · 剑柱散了，剑影化成光点纷纷落下，照亮一片片地面；云退到两边散开，演出最后 0.4 秒淡出"


def S_DIM(k: float) -> str:
    """高光时把月夜底色压暗一点（演出期间压暗普通战斗）。"""
    c = np.clip(Z.to_srgb(lin(Z.NIGHT) * k), 0, 1)
    return "#" + "".join(f"{round(v * 255):02X}" for v in c)


# ============================================================== 汇总

SHOWS = {
    "sword": {
        "panels": sword_panel,
        "n": 4,
        "hero": 2,
        "title": "万剑归宗（符剑进化）· 2.6 秒 · 分镜",
        "sub": "《庄子·说剑》：天子之剑，上决浮云。元件：myth/sword_blade_0..2（剑影 3 种，叠加染金）、sword_cloud_0..5 + _emit（被劈开的云，焦墨 + 裂口金光）；"
               "拖尾、光点、聚光、剑柱的光是代码画的示意",
    },
}


def render_panel(show: str, k: int) -> tuple[Image.Image, str]:
    shot, text = SHOWS[show]["panels"](k)
    return Z.to8(Z.render(shot)), text


def main(args: list[str]) -> None:
    for a in args:
        t0 = time.perf_counter()
        if ":" in a:
            show, k = a.split(":")
            im, text = render_panel(show, int(k))
            TRY.mkdir(parents=True, exist_ok=True)
            im.save(TRY / f"{show}_{k}.png")
            print(f"{show}:{k}  {text}  {time.perf_counter() - t0:.1f}s", flush=True)
            continue
        cfg = SHOWS[a]
        panels = [render_panel(a, k) for k in range(cfg["n"])]
        Z.board(panels, cfg["title"], cfg["sub"], REVIEW / f"myth_{a}_board.png")
        V.save_png(panels[cfg["hero"]][0], REVIEW / f"myth_{a}_hero.png")
        print(f"{a}: {time.perf_counter() - t0:.1f}s", flush=True)


if __name__ == "__main__":
    main(sys.argv[1:])
