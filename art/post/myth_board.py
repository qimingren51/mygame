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
    """读元件；名字以 _emit 结尾的读发光层（文件名是帧号在前、_emit 在后）。"""
    if name not in _CACHE:
        _CACHE[name] = P.load(name[:-5], emit=True) if name.endswith("_emit") else P.load(name)
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


GIANTS = [(0.5, 2.0, 0.0, 0.0, 0.55), (0.55, 2.3, -0.022, -9.0, 0.16), (0.46, 1.7, 0.02, 8.0, 0.14)]  # (缩放, 粗细, 角度, 横移, 亮度)：剑尖落在云缝里


def giant_column(img, cam, gx, gy, gain=1.0):
    """剑柱最外一层：几张 sword_giant 叠成一柄顶天的大剑（剑格在 (gx, gy)，剑尖朝上），大小、粗细、角度错开一点。"""
    gs = parts("sword_giant")[0]
    for scl, sy, dang, dx, al in GIANTS:
        Z.blit(img, Z.pm_of(gs, tint=GOLD_T), gx + dx, gy, (250.0 / P.GIANT_W, 0.5), scl, angle=-math.pi / 2 + dang, sy=sy,
               mode="add", gain=Z.EMIT * al * gain)


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
        shot = Z.Shot(cam=cam, actors=Z.default_actors(), ambient=S_DIM(0.66), pool=0.36, bloom=0.36, vignette=0.36)
        rng = np.random.default_rng(41)
        col = []
        bx, by = cam.s(hx, hy, 26)
        for j in range(54):  # 小剑影：绕着大剑往上冲，在剑身两边拧成两股
            strand = j % 3
            hh = rng.uniform(30, 340)
            spread = 0.55 + 0.45 * min(hh / 140, 1)
            phase = hh / 34.0 + strand * 2 * math.pi / 3
            xo = (40 + 8 * spread) * math.sin(phase) + rng.normal(0, 3)
            x, y = cam.s(hx + xo, hy, 26 + hh)
            sc = rng.uniform(1.5, 1.9) * (1.1 - 0.2 * min(hh / 300, 1))
            ang = -math.pi / 2 + 0.22 * math.cos(phase) * spread
            L = rng.uniform(40, 90)
            tp = [(x - L * (1 - q) * math.cos(ang), y - L * (1 - q) * math.sin(ang)) for q in np.linspace(0, 1, 6)]
            col.append((x, y, ang, int(rng.integers(3)), sc * 0.85, rng.uniform(0.35, 0.55), tp))
        funnel = river_swords(cam, t_head=4.2, n=30, turns=1.0, R0=100, R1=28, h0=8, h1=56, seed=7, spread=0.6, size=(1.35, 1.6))

        def light(lm, cam):
            spot_light(lm, cam, hx, hy, 70, GOLD_T, 0.3, power=1.1)
            spot_light(lm, cam, hx, hy, 200, GOLD_DEEP, 0.14, power=1.6)

        def add(img, cam):
            top = -60
            god_rays(img, SW / 2 + cam.shake[0], 110, 11, 0.7, 1200, GOLD_T, 0.09, 61, width=(40, 120))
            draw_swords(img, cam, funnel, trail_w=1.8, trail_a=0.22, echoes=1)
            draw_swords(img, cam, col, trail_w=1.2, trail_a=0.2, echoes=1)
            giant_column(img, cam, bx, by - 58)
            gx, gy = cam.s(hx, hy)
            sw = M.atlas_frame("vfx", "vfx/shockwave_2")[0]
            Z.blit(img, Z.pm_of(sw, tint=GOLD_T), gx, gy, (0.5, 0.5), cam.sprite * 1.25, mode="add", gain=Z.EMIT * 0.3)
            Z.glow_ellipse(img, gx, gy, 80, 80 * FLAT, GOLD_T, 0.08, power=1.8)
            Z.glow(img, SW / 2 + cam.shake[0], 120, 110, GOLD_T, 0.08, power=2.2)  # 剑尖顶开云的地方亮一团

        shot.sky.append(cloud_layer(3, cy=140.0, scale=2.1))
        shot.light.append(light)
        shot.add.append(add)
        return shot, "2.0 秒 · 剑河冲天：三柄大剑影叠成一柄顶天的大剑（剑格在主角头顶、剑尖顶进云缝），小剑影绕着剑身往上冲，把上空的云劈开（上决浮云）；震屏 0.35、辉光猛涨"
    # k == 3：归宗——剑影收拢，飞回主角手里的符剑，剑身一亮，扣“归宗”二字
    cam = Z.Cam(z=1.06, cy=4.0)
    shot = Z.Shot(cam=cam, actors=Z.default_actors(), ambient=S_DIM(0.72), pool=0.62, bloom=0.42, vignette=0.36)
    sx_, sy_ = cam.s(hx + 12, hy, 30)  # 符剑：主角右手边，剑尖朝上
    sword = M.atlas_frame("vfx", "weapons/sword_evo")[0]

    def light(lm, cam):
        Z.glow(lm, sx_ / 2, sy_ / 2, 60 * cam.k / 2, GOLD_T, 0.5, power=1.4)

    def over(img, cam):
        Z.blit(img, Z.pm_of(sword), sx_, sy_, (0.6, 0.5), cam.sprite * 2.2, angle=-math.pi / 2)
        guizong(img, 690, 250, 150, layer="ink")

    def add(img, cam):
        r2 = np.random.default_rng(53)
        inc = []
        for j in range(72):  # 剑影从四面八方收回来，剑尖朝着符剑，越近越亮、越密
            ang = r2.uniform(0, 2 * math.pi)
            R = 30 + 420 * r2.uniform(0, 1) ** 1.6
            x, y = sx_ + R * math.cos(ang), sy_ - 40 + R * 0.75 * math.sin(ang)
            hd = math.atan2(sy_ - 40 - y, sx_ - x)
            L = 40 + 0.35 * R
            tp = [(x - L * (1 - q) * math.cos(hd), y - L * (1 - q) * math.sin(hd)) for q in np.linspace(0, 1, 6)]
            if R < 60:
                continue
            inc.append((x, y, hd, int(r2.integers(3)), r2.uniform(1.1, 1.45), (0.8 - 0.45 * R / 450), tp))
        draw_swords(img, cam, inc, trail_w=1.4, trail_a=0.3)
        # 剑身一亮：沿剑身一道白光、剑尖一颗星芒
        L = 104 * cam.sprite * 2.2
        top = (sx_, sy_ - 0.4 * L)
        Z.stroke(img, [(sx_, sy_ + 0.6 * L), top], [10, 4], WARM_WHITE, alpha=[0.3, 0.9], soft=4, gain=Z.EMIT)
        Z.glow(img, sx_, sy_ - 0.1 * L, 60, GOLD_T, 0.2, power=1.8)
        crit = M.atlas_frame("vfx", "vfx/crit_0")[0]
        Z.blit(img, Z.pm_of(crit), top[0], top[1] - 6, (0.5, 0.5), 0.42, mode="add", gain=Z.EMIT * 0.7)
        for _ in range(26):  # 少量拖尾火星
            a = r2.uniform(0, 2 * math.pi)
            R = r2.uniform(30, 160)
            x, y = sx_ + R * math.cos(a), sy_ - 40 + R * 0.8 * math.sin(a)
            Lk = r2.uniform(8, 22)
            Z.stroke(img, [(x + Lk * math.cos(a), y + Lk * math.sin(a)), (x, y)], [0.3, 2.0], GOLD_T, alpha=[0.0, 0.8], gain=Z.EMIT)
        guizong(img, 690, 250, 150, layer="gold")

    shot.sky.append(cloud_layer(5, alpha=0.7, emit_gain=0.6))
    shot.light.append(light)
    shot.over.append(over)
    shot.add.append(add)
    return shot, "2.4 秒 · 归宗：剑柱散开，所有剑影收拢、飞回主角手里的符剑，剑身一亮，扣下“归宗”二字（金字，题字层）；只剩几点拖尾火星，然后淡出"


_GZ: dict = {}


def guizong(img, x, y, size, layer):
    """“归宗”二字（示意：马善政体，竖排）。ink 是垫在字下面的一层淡墨（普通混合），gold 是金字（叠加）。"""
    key = (x, y, size)
    if key not in _GZ:
        from PIL import ImageDraw, ImageFilter, ImageFont
        font = ImageFont.truetype(str(V.OUT / "fonts" / "MaShanZheng-Regular.ttf"), size)
        m = Image.new("L", (int(size * 1.4), int(size * 2.5)), 0)
        d = ImageDraw.Draw(m)
        for i, ch in enumerate("归宗"):
            d.text((size * 0.2, size * 0.1 + i * size * 1.15), ch, fill=255, font=font)
        a = np.asarray(m, dtype=np.float32) / 255.0
        back = np.asarray(m.filter(ImageFilter.GaussianBlur(size * 0.12)), dtype=np.float32) / 255.0
        _GZ[key] = (a, back)
    a, back = _GZ[key]
    h, w = a.shape
    x0, y0 = int(x - w / 2), int(y)
    reg = img[y0 : y0 + h, x0 : x0 + w]
    if layer == "ink":
        k = np.clip(back * 1.6, 0, 0.75)[..., None]
        reg[:] = reg * (1 - k) + lin("#17140F").astype(np.float32) * k
    else:
        reg += (a[..., None] * GOLD_T * 0.9 + np.clip(back - a, 0, 1)[..., None] * GOLD_T * 0.35) * Z.EMIT


def S_DIM(k: float) -> str:
    """高光时把月夜底色压暗一点（演出期间压暗普通战斗）。"""
    c = np.clip(Z.to_srgb(lin(Z.NIGHT) * k), 0, 1)
    return "#" + "".join(f"{round(v * 255):02X}" for v in c)


# ============================================================== 北冥潮


ICE_T = lin("#CDEBFF").astype(np.float32)
WATER_T = lin("#6FB8FF").astype(np.float32)


def sea_layer(fi, scale, alpha=1.0, emit_gain=1.0, at=None):
    """脚下冰海：本体贴地（ground 钩子，妖物之下、暗层之下），发光层叠加。scale 是相对 1080p 一比一的倍数。"""
    body, em = parts("kun_sea")[fi], parts("kun_sea_emit")[fi]

    def ground(img, cam):
        x, y = cam.s(*(at or Z.HERO))
        Z.blit(img, Z.pm_of(body), x, y, (0.5, 0.5), cam.sprite * scale, alpha=alpha)

    def add(img, cam):
        x, y = cam.s(*(at or Z.HERO))
        Z.blit(img, Z.pm_of(em), x, y, (0.5, 0.5), cam.sprite * scale, mode="add", gain=Z.EMIT * alpha * emit_gain)

    return ground, add


def sea_light(cam, scale, gain, at=None):
    """冰海往上照的冷光（光照图）。"""
    def light(lm, cam_):
        x, y = cam_.s(*(at or Z.HERO))
        r = P.SEA_RX * cam_.sprite * scale * 0.85
        Z.glow_ellipse(lm, x / 2, y / 2, r / 2, r * FLAT / 2, ICE_T, gain, power=0.9)
    return light


def frozen(k=0.65):
    """冻住的妖物：颜色往冰蓝白拉，边上一圈冷光（改贴图的钩子）。"""
    ice = lin("#BFE0F5").astype(np.float32)

    def hook(pm, epm):
        a = pm[..., 3:4]
        rgb = pm[..., :3] * (1 - k) + ice * a * k * 0.55
        out = np.concatenate([rgb, a], -1)
        return out, (epm * 0.3 if epm is not None else None)
    return hook


def kun_panel(k: int) -> tuple[Z.Shot, str]:
    hx, hy = Z.HERO
    if k == 0:
        cam = Z.Cam(z=1.0, cy=4.0)
        shot = Z.Shot(cam=cam, actors=Z.default_actors(), ambient=S_DIM(0.82), pool=0.75, bloom=0.3, vignette=0.36)
        g, a = sea_layer(2, 2.4)
        shot.ground.append(g)
        shot.light.append(sea_light(cam, 2.4 * 0.55, 0.45))

        def add(img, cam):
            a(img, cam)
            # 浪往外推：水边一圈浪头（现成 weapons/wave_front，转成朝外）
            wf = M.atlas_frame("vfx", "weapons/wave_front_1")[0]
            wb = M.atlas_frame("vfx", "weapons/wave_front_body_1")[0]
            R = P.SEA_RX * 0.52 * 2.4 / Z.K * 1.0
            for j in range(14):
                th = 2 * math.pi * j / 14 + 0.2
                x, y = ring_pos(cam, hx, hy, R * 1.02, th, 0)
                ang = math.atan2(FLAT * math.sin(th), math.cos(th)) - math.pi / 2
                Z.blit(img, Z.pm_of(wf, tint=WATER_T), x, y, (0.5, 0.6953125), cam.sprite * 0.75, angle=ang, sy=0.8, mode="add", gain=Z.EMIT * 0.8)

        shot.add.append(add)
        return shot, "0.3 秒 · 脚下冰面结霜、放射着裂开，正中翻开一片冰海，一圈圈浪往外推，水边碎冰板往外挤，冰缝里透冷光"
    if k == 1:
        cam = Z.Cam(z=1.04, cy=4.0)
        actors = Z.default_actors()
        shot = Z.Shot(cam=cam, actors=actors, ambient=S_DIM(0.78), pool=0.7, bloom=0.3, vignette=0.4)
        g, a = sea_layer(4, 2.7)
        shadow = parts("kun_shadow")[0]
        sc = 2.05
        head_x = 1560.0  # 画面像素：头已经过了主角，身子和尾巴还拖在画面左边外头，一对大鳍正从主角脚下过
        cy_s = 585.0

        shadow_e = parts("kun_shadow_emit")[0]
        fin, fin_e = parts("kun_fin")[0], parts("kun_fin_emit")[0]
        fin_sc = 1.6

        def shadow_pos(cam):
            L = shadow.width * cam.sprite * sc
            return head_x - 0.48 * L, cy_s

        def fin_pos(cam):
            x, y = shadow_pos(cam)
            return x + (900 - 768) * cam.sprite * sc, y - 4

        def ground(img, cam):
            g(img, cam)
            Z.blit(img, Z.pm_of(shadow), *shadow_pos(cam), (0.5, 0.5), cam.sprite * sc, angle=-0.05)
            # 背鳍露出水面（kun_fin），跟着背脊
            Z.blit(img, Z.pm_of(fin), *fin_pos(cam), (0.5, P.FIN_WATER / P.FIN_H), cam.sprite * fin_sc)

        shot.ground.append(ground)
        shot.light.append(sea_light(cam, 2.7 * 0.95, 0.95))

        def add(img, cam):
            a(img, cam)
            Z.blit(img, Z.pm_of(shadow_e), *shadow_pos(cam), (0.5, 0.5), cam.sprite * sc, angle=-0.05, mode="add", gain=Z.EMIT * 0.65)
            fx, fy = fin_pos(cam)
            Z.glow_ellipse(img, fx - 20, fy - 50, 120, 90, ICE_T, 0.1, power=1.4)  # 鳍后面一团冷光，托出焦墨的鳍
            Z.blit(img, Z.pm_of(fin_e), fx, fy, (0.5, P.FIN_WATER / P.FIN_H), cam.sprite * fin_sc, mode="add", gain=Z.EMIT * 1.5)
            # 鳍前一道翻起的浪（现成 wave_front，转成朝 +X）
            wf = M.atlas_frame("vfx", "weapons/wave_front_2")[0]
            Z.blit(img, Z.pm_of(wf, tint=ICE_T), fx + 70, fy, (0.5, 0.6953125), cam.sprite * 0.6, angle=-math.pi / 2, sx=0.9, mode="add", gain=Z.EMIT)
            # 身后两道八字形的浪痕：浪头一节节往外翻（wave_front 转成朝外），后面拖一道粗的白沫带，越往后越宽、越散、越淡
            r2 = np.random.default_rng(71)
            for sgn in (-1, 1):
                pts = [(fx - 10 - 1000 * q, fy + sgn * (14 + 230 * q ** 0.85)) for q in np.linspace(0, 1, 40)]
                for j in range(1, len(pts)):
                    q = j / len(pts)
                    if r2.random() < 0.12 + 0.3 * q:
                        continue
                    (x0, y0), (x1, y1) = pts[j - 1], pts[j]
                    jit = r2.normal(0, 3 + 8 * q, 2)
                    Z.stroke(img, [(x0 + jit[0], y0 + jit[1]), (x1 + jit[0], y1 + jit[1])], [r2.uniform(14, 24) * (1 - 0.35 * q)] * 2, ICE_T,
                             alpha=0.4 * (1 - q) ** 1.1, gain=Z.EMIT, soft=6.0)
                    Z.stroke(img, [(x0 + jit[0], y0 + jit[1] - sgn * 4), (x1 + jit[0], y1 + jit[1] - sgn * 4)], [r2.uniform(3, 6) * (1 - 0.4 * q)] * 2, ICE_T,
                             alpha=0.75 * (1 - q) ** 1.2, gain=Z.EMIT, soft=1.5)  # 浪唇一道亮
                    if j % 5 == 2 and q < 0.75:  # 浪头往外翻
                        ang = math.atan2(y1 - y0, x1 - x0) + sgn * math.pi / 2
                        Z.blit(img, Z.pm_of(wf, tint=ICE_T), x1, y1, (0.5, 0.6953125), cam.sprite * (0.55 - 0.25 * q), angle=ang - math.pi / 2,
                               mode="add", gain=Z.EMIT * (0.8 - 0.6 * q))
            for _ in range(70):  # 浪花溅起的水珠
                x, y = fx + 50 + r2.normal(0, 40), fy + r2.normal(0, 26)
                Z.glow(img, x, y, r2.uniform(1.8, 3.8), ICE_T, r2.uniform(0.4, 1.0), power=2.0)

        shot.add.append(add)
        return shot, "1.0 秒 · 冰海铺满、冷光照亮水面，一片焦墨的鲲影从脚下掠过（边上一圈冰光），大得画面装不下；背鳍露出水面，划出两道八字浪"
    if k == 2:
        cam = Z.Cam(z=1.06, cy=4.0, shake=(-4.0, 3.0))
        actors = Z.default_actors()
        for a_ in actors:
            if not a_.key.startswith("hero/") and math.hypot(a_.x - hx, a_.y - hy) < 260:
                a_.hook = frozen(0.55)
        shot = Z.Shot(cam=cam, actors=actors, ambient=S_DIM(0.75), pool=0.65, bloom=0.5, vignette=0.34, desat=0.08)
        g, a = sea_layer(5, 2.7)
        leap = parts("kun_leap")[2]
        lx, ly, lsc = 905.0, 905.0, 2.4  # 比画面还高一截：顶上出画

        def light(lm, cam):
            Z.glow_ellipse(lm, (lx + 30) / 2, 380 / 2, 640 / 2, 460 / 2, ICE_T, 0.45, power=1.2)
            sea_light(cam, 2.7 * 0.95, 0.5)(lm, cam)

        def add(img, cam):
            a(img, cam)
            Z.blit(img, Z.pm_of(leap), lx, ly, (0.5, P.LEAP_WATER / P.LEAP_SIZE), cam.sprite * lsc, mode="add", gain=Z.EMIT)
            # 尾巴离水的地方：水面一圈冷光（水花在 kun_leap 帧里）
            Z.glow_ellipse(img, lx + (230 - 384) * cam.sprite * lsc, ly, 120, 40, ICE_T, 0.25, power=1.5)

        shot.ground.append(g)
        shot.light.append(light)
        shot.add.append(add)
        return shot, "1.75 秒 · 鲲跃出水，冷光剪影拱过主角头顶，鳍张开像翅膀（鲲化为鹏），身上往下淌水；顿帧 0.08 秒、震屏 0.3，近处的妖物冻住"
    cam = Z.Cam(z=1.03, cy=4.0)
    actors = Z.default_actors()
    for a_ in actors:
        if not a_.key.startswith("hero/") and math.hypot(a_.x - hx, a_.y - hy) < 300:
            a_.hook = frozen(0.6)
    shot = Z.Shot(cam=cam, actors=actors, ambient=S_DIM(0.85), pool=0.8, bloom=0.4, vignette=0.32)
    g, a = sea_layer(5, 2.7, alpha=0.5, emit_gain=0.7)
    body0, em0 = parts("kun_sea")[0], parts("kun_sea_emit")[0]

    def ground(img, cam):
        g(img, cam)
        x, y = cam.s(hx, hy)
        Z.blit(img, Z.pm_of(body0), x, y, (0.5, 0.5), cam.sprite * 2.7, alpha=0.8)  # 冰面碎开的裂纹（借第 0 帧）

    def add(img, cam):
        a(img, cam)
        x, y = cam.s(hx, hy)
        Z.blit(img, Z.pm_of(em0), x, y, (0.5, 0.5), cam.sprite * 2.7, mode="add", gain=Z.EMIT * 0.8)
        r2 = np.random.default_rng(91)
        sw = M.atlas_frame("vfx", "vfx/shockwave_3")[0]
        Z.blit(img, Z.pm_of(sw, tint=ICE_T), x, y, (0.5, 0.5), cam.sprite * 3.0, mode="add", gain=Z.EMIT * 0.7)  # 碎开的那一圈白霜往外荡
        for _ in range(70):  # 冰海碎成冰碴：崩起来的大块冰片（三角，亮边、淡面）
            R = math.sqrt(r2.uniform(0.02, 1.0)) * 360
            th = r2.uniform(0, 2 * math.pi)
            px, py = ring_pos(cam, hx, hy, R, th, r2.uniform(4, 40))
            sz = r2.uniform(7, 22)
            a0 = r2.uniform(0, 6.28)
            tri = [(px + sz * math.cos(a0 + q) * r2.uniform(0.5, 1.2), py + sz * math.sin(a0 + q) * r2.uniform(0.5, 1.2)) for q in (0.0, 2.3, 4.0)]
            Z.stroke(img, [tri[0], tri[1], tri[2], tri[0]], 1.6, ICE_T, alpha=0.75, gain=Z.EMIT)
            cxs, cys = sum(t[0] for t in tri) / 3, sum(t[1] for t in tri) / 3
            Z.glow(img, cxs, cys, sz * 0.8, ICE_T, 0.25, power=1.2)
        for _ in range(240):  # 飞起来的冰碴：尖的小碎片，往外、往上崩
            R = math.sqrt(r2.uniform(0, 1)) * 380
            th = r2.uniform(0, 2 * math.pi)
            px, py = ring_pos(cam, hx, hy, R, th, r2.uniform(6, 70))
            ang = math.atan2(FLAT * math.sin(th), math.cos(th)) - r2.uniform(0.2, 0.9)
            L = r2.uniform(5, 16)
            Z.stroke(img, [(px - L * math.cos(ang), py - L * math.sin(ang)), (px, py)], [0.4, r2.uniform(2.0, 4.2)], ICE_T, alpha=[0.15, r2.uniform(0.6, 1.0)], gain=Z.EMIT)
            Z.glow(img, px, py, 3.0, ICE_T, 0.5, power=2.0)

    shot.ground.append(ground)
    shot.light.append(sea_light(cam, 2.7 * 0.6, 0.18))
    shot.add.append(add)
    return shot, "2.2 秒 · 鲲扎回水里，冰海一下子碎成满地冰碴炸开（现成 vfx/ice_shatter），近处的妖物冻在原地；然后淡出"


# ============================================================== 燃灯


LAMP_T = lin("#FFE7A8").astype(np.float32)
EMBER_T = lin("#FFB347").astype(np.float32)
ASH = lin("#3A3631").astype(np.float32)


def ashen(p, seed=0):
    """被佛光照到的妖物化灰（改贴图的钩子）：按噪声从里往外烧掉，烧到的边一圈余烬（叠加层），剩下的发灰。p 0..1。"""
    def hook(pm, epm):
        h, w = pm.shape[:2]
        n = V.rank01(V.fft_blur(np.random.default_rng(900 + seed).standard_normal((h, w)), 3.0) + 0.6 * V.fft_blur(np.random.default_rng(901 + seed).standard_normal((h, w)), 14.0))
        a = pm[..., 3]
        keep = V.smoothstep(p, p + 0.08, n).astype(np.float32)
        q = np.float32(min(1.0, p * 1.6) * 0.85)
        rgb = pm[..., :3] * (1 - q) + ASH * a[..., None] * q
        out = np.concatenate([rgb * keep[..., None], (a * keep)[..., None]], -1).astype(np.float32)
        e = (a * np.exp(-(((n - p) / 0.035) ** 2)) * (p > 0.01)).astype(np.float32)
        em = np.concatenate([EMBER_T * e[..., None], e[..., None]], -1)
        if epm is not None:
            em = em + epm * keep[..., None]
        return out, em
    return hook


def ash_flakes(img, cam, actors, p, rise, n=26, seed=5, mode="over"):
    """化灰的妖物身上飘起来的灰片（普通混合）和余烬（叠加）：越往上越散、越淡。"""
    r2 = np.random.default_rng(seed)
    for a_ in actors:
        if a_.key.startswith("hero/"):
            continue
        for _ in range(n):
            q = r2.uniform(0, 1)
            x = a_.x + r2.normal(0, 9) + 18 * q * r2.normal(0, 1)
            hgt = r2.uniform(4, 40) + rise * q
            px, py = cam.s(x, a_.y, hgt)
            if mode == "over":
                sz = r2.uniform(1.5, 4.5) * (1 - 0.4 * q)
                col = ASH * 0.6
                al = 0.85 * (1 - q) ** 0.8 * p
                Z.stroke(img, [(px - sz, py - sz * 0.4), (px + sz, py + sz * 0.3)], sz * 0.9, col, mode="over", alpha=al)
            else:
                if r2.random() < 0.4:
                    Z.glow(img, px, py, r2.uniform(1.5, 3.2), EMBER_T, 0.9 * (1 - q) * p, power=1.8)


LAMP_LIT = lin("#FFF1D6").astype(np.float32) * 0.92


def lotus_at(img, cam, fi, h, scale, gain=1.0, dark=0.0):
    """莲灯：在主角头顶的天上，画在暗层之上（自己的灯焰照亮，本体按暖光 LAMP_LIT 着色）。
    dark > 0 时先在莲灯后面垫一圈暗晕（普通混合的淡墨），佛光再亮也压不白莲瓣；然后本体（普通混合）、发光层（叠加）。"""
    body, em = parts("ult_lotus")[fi], parts("ult_lotus_emit")[fi]
    x, y = cam.s(Z.HERO[0], Z.HERO[1], h)
    if dark > 0:
        fx, fy = flame_pos(cam, fi, h, scale)
        r = 240 * cam.sprite * scale  # 比头光大一圈、边很软，头光的圆线落在渐变里，不压在暗晕边上
        x0, x1 = int(max(fx - 2.2 * r, 0)), int(min(fx + 2.2 * r, SW))
        y0, y1 = int(max(fy - 2.2 * r, 0)), int(min(fy + 2.2 * r, SH))
        X, Y = np.meshgrid(np.arange(x0, x1) + 0.5, np.arange(y0, y1) + 0.5)
        k = (dark * np.exp(-((np.hypot(X - fx, (Y - fy) * 1.1) / r) ** 1.3)))[..., None].astype(np.float32)
        reg = img[y0:y1, x0:x1]
        reg[:] = reg * (1 - k) + lin("#2A2118").astype(np.float32) * k * 0.6
    pm = Z.pm_of(body).copy()
    pm[..., :3] *= LAMP_LIT
    Z.blit(img, pm, x, y, (0.5, 1.0), cam.sprite * scale)
    Z.blit(img, Z.pm_of(em), x, y, (0.5, 1.0), cam.sprite * scale, mode="add", gain=Z.EMIT * gain)
    return x, y


def rays_masked(img, cam, center, scale, angle, gain, r_hole, floor=0.15):
    """佛光：先画进一张临时层，在莲灯附近按半径压低（r_hole 以内只剩 floor），再叠到画面上。"""
    rays = parts("ult_rays")[0]
    tmp = np.zeros_like(img)
    Z.blit(tmp, Z.pm_of(rays), center[0], center[1], (0.5, 0.5), cam.sprite * scale, angle=angle, mode="add", gain=Z.EMIT * gain)
    Y, X = np.mgrid[0:SH, 0:SW].astype(np.float32)
    r = np.hypot(X + 0.5 - center[0], Y + 0.5 - center[1])
    m = floor + (1 - floor) * V.smoothstep(r_hole * 0.55, r_hole * 1.4, r)
    img += tmp * m[..., None]


def flame_pos(cam, fi, h, scale):
    """莲灯灯焰在画面上的位置（佛光、头光的中心）。"""
    x, y = cam.s(Z.HERO[0], Z.HERO[1], h)
    k = P.LOTUS_SIZE[fi]
    fl = P.LOTUS_FLAME[fi]
    fy = P.LOTUS_BASE[1] - 34 * k - 22 * fl
    return x, y - (P.LOTUS_H - fy) * cam.sprite * scale


def ult_panel(k: int) -> tuple[Z.Shot, str]:
    hx, hy = Z.HERO
    H_LAMP, SC = 62.0, 1.45
    near = lambda a_: (not a_.key.startswith("hero/"))  # noqa: E731
    if k == 0:
        cam = Z.Cam(z=1.08, cy=-6.0)
        shot = Z.Shot(cam=cam, actors=Z.default_actors(), ambient=S_DIM(0.6), pool=0.6, bloom=0.4, vignette=0.5, desat=0.18)

        def light(lm, cam):
            x, y = cam.s(hx, hy, H_LAMP - 20)
            Z.glow(lm, x / 2, y / 2, 70 * cam.k / 2, LAMP_T, 0.35, power=1.5)

        def add(img, cam):
            sx, sy = M.asset_meta("hero")["sockets"]["lantern"]["idle"]["S"][0]
            lx, ly = cam.s(hx + sx / Z.PPU, hy + sy / Z.PPU)
            x, y = lotus_at(img, cam, 1, H_LAMP - 14, SC)
            fx, fy = flame_pos(cam, 1, H_LAMP - 14, SC)
            # 从灯里升起来：一道细的光迹，弯一下
            pts = [(lx + (x - lx) * q + 18 * math.sin(q * math.pi) , ly + (fy + 30 - ly) * q) for q in np.linspace(0, 1, 20)]
            Z.stroke(img, pts, np.linspace(1.0, 5.0, 20), LAMP_T, alpha=np.linspace(0.05, 0.6, 20), gain=Z.EMIT)
            Z.glow(img, fx, fy + 20, 60, LAMP_T, 0.12, power=2.0)

        shot.light.append(light)
        shot.add.append(add)
        return shot, "0.3 秒 · 顿帧、推近，四下压暗：一盏合着的莲灯从主角的灯里升起，飘到头顶上方，灯苞里透着光"
    if k == 1:
        cam = Z.Cam(z=1.12, cy=-10.0)
        shot = Z.Shot(cam=cam, actors=Z.default_actors(), ambient=S_DIM(0.62), pool=0.65, bloom=0.3, vignette=0.46, desat=0.1)

        def light(lm, cam):
            fx, fy = flame_pos(cam, 5, H_LAMP, SC)
            Z.glow(lm, fx / 2, fy / 2, 160 * cam.k / 2, LAMP_T, 0.35, power=1.4)

        def add(img, cam):
            fx, fy = flame_pos(cam, 5, H_LAMP, SC)
            halo = parts("ult_halo")[0]
            Z.blit(img, Z.pm_of(halo), fx, fy, (0.5, 0.5), cam.sprite * 0.9, angle=0.2, mode="add", gain=Z.EMIT * 0.6)
            rays_masked(img, cam, (fx, fy), 0.6, 0.1, 0.32, 70, floor=0.3)
            lotus_at(img, cam, 5, H_LAMP, SC, gain=0.85, dark=0.25)

        shot.light.append(light)
        shot.add.append(add)
        return shot, "0.6 秒 · 灯罩一层层打开（外层、中层），灯焰露出来；身后亮起头光，第一圈佛光从灯焰里放出来"
    if k == 2:
        cam = Z.Cam(z=1.12, cy=-10.0, shake=(3.0, -2.0))
        actors = Z.default_actors()
        for j, a_ in enumerate(actors):
            if near(a_):
                a_.hook = ashen(0.45 + 0.1 * ((j * 7) % 3), j)
        shot = Z.Shot(cam=cam, actors=actors, ambient=S_DIM(0.7), pool=0.8, lift_dark=0.66, bloom=0.36, vignette=0.26)

        def light(lm, cam):
            fx, fy = flame_pos(cam, 7, H_LAMP, SC)
            Z.glow(lm, fx / 2, fy / 2, 420 * cam.k / 2, LAMP_T, 0.05, power=1.2)

        def over(img, cam):
            ash_flakes(img, cam, actors, 1.0, 70, mode="over")

        def add(img, cam):
            fx, fy = flame_pos(cam, 7, H_LAMP, SC)
            rays_masked(img, cam, (fx, fy), 2.0, 0.16, 0.36, 150, floor=0.12)
            rays_masked(img, cam, (fx, fy), 2.6, -0.21, 0.16, 150, floor=0.12)
            halo = parts("ult_halo")[0]
            Z.blit(img, Z.pm_of(halo), fx, fy, (0.5, 0.5), cam.sprite * 1.25, angle=0.32, mode="add", gain=Z.EMIT * 0.45)
            lotus_at(img, cam, 7, H_LAMP, SC, gain=0.7, dark=0.5)
            ash_flakes(img, cam, actors, 1.0, 70, mode="add")

        shot.light.append(light)
        shot.over.append(over)
        shot.add.append(add)
        return shot, "0.95 秒 · 莲灯全开，千条佛光照透全场（暗层往八成提，辉光拉满）；莲灯后面垫一圈暗晕、近处佛光压低，瓣的轮廓和描金看得清；妖物烧成灰往上飘"
    cam = Z.Cam(z=1.08, cy=-6.0)
    actors = [a_ for a_ in Z.default_actors() if not near(a_)]
    ghosts = [a_ for a_ in Z.default_actors() if near(a_)]
    for j, a_ in enumerate(ghosts):
        a_.hook = ashen(0.93, j)
        a_.shadow = False
    shot = Z.Shot(cam=cam, actors=actors + ghosts, ambient=S_DIM(0.8), pool=0.5, lift_dark=0.5, bloom=0.32, vignette=0.28)

    def light(lm, cam):
        fx, fy = flame_pos(cam, 7, H_LAMP, SC)
        Z.glow(lm, fx / 2, fy / 2, 300 * cam.k / 2, LAMP_T, 0.1, power=1.3)

    def over(img, cam):
        ash_flakes(img, cam, ghosts, 0.85, 150, n=34, seed=6, mode="over")

    def add(img, cam):
        fx, fy = flame_pos(cam, 7, H_LAMP, SC)
        rays_masked(img, cam, (fx, fy), 2.4, 0.3, 0.14, 140, floor=0.2)
        halo = parts("ult_halo")[0]
        Z.blit(img, Z.pm_of(halo), fx, fy, (0.5, 0.5), cam.sprite * 1.25, angle=0.45, mode="add", gain=Z.EMIT * 0.35)
        lotus_at(img, cam, 7, H_LAMP, SC, gain=0.8, dark=0.3)
        ash_flakes(img, cam, ghosts, 0.85, 150, n=34, seed=6, mode="add")

    shot.light.append(light)
    shot.over.append(over)
    shot.add.append(add)
    return shot, "1.3 秒 · 佛光收拢、淡下去，妖物只剩灰，灰和余烬飘得比平时高；接现在的三拍（墨浪、余烬）"


# ============================================================== 九尾登场


FOX_T = lin("#8FE3C8").astype(np.float32)
MOON_T = lin("#DCE6FF").astype(np.float32)
FAN = [32.0 - 15.5 * k for k in range(9)]  # 扇开以后每条尾巴的角度（离竖直，往右为正）；扇从右往左一条条打开


def fox_fan(img, cx, cy, sc, opened, alpha=1.0, emit_gain=1.0):
    """月前的九尾剪影：身子锚点放在画面 (cx, cy)，sc 是画面像素 / 贴图像素。opened[k] 是第 k 条尾巴打开了多少（0 合着、1 到位）。
    尾巴先画（在身子后面），从合着的位置（最右那条的角度）往左转到自己的角度；中间几条长，两边短一点，前后两层错开明暗。"""
    body, be = parts("fox_body")[0], parts("fox_body_emit")[0]
    tail, te = parts("fox_tail")[0], parts("fox_tail_emit")[0]
    bs = sc * 1.14  # 身子比尾巴大一点
    rx, ry = cx + (P.FOX_TAIL_ROOT[0] - 256) * bs, cy + (P.FOX_TAIL_ROOT[1] - 471) * bs
    anc = (P.TAIL_ROOT[0] / P.TAIL_W, P.TAIL_ROOT[1] / P.TAIL_H)
    order = sorted(range(9), key=lambda k: (k % 2, -abs(k - 4)))  # 后层（奇数）先画
    for k in order:
        o = opened[k]
        if o <= 0:
            continue
        ease = 1 - (1 - min(o, 1.0)) ** 2.2
        ang = FAN[0] + (FAN[k] - FAN[0]) * ease
        lk = 0.86 * (1.06 - 0.16 * abs(k - 4) / 4) * (0.94 if k % 2 else 1.0)
        back = 0.75 if k % 2 else 1.0
        a_ = math.radians(ang)
        flip = ang < FAN[4]
        Z.blit(img, Z.pm_of(tail), rx, ry, anc, sc * lk, angle=a_, flip=flip, alpha=alpha * min(1.0, o * 3))
        Z.blit(img, Z.pm_of(te), rx, ry, anc, sc * lk, angle=a_, flip=flip, mode="add", gain=Z.EMIT * emit_gain * back * alpha * min(1.0, o * 3))
    Z.blit(img, Z.pm_of(body), cx, cy, (0.5, 471 / 512), bs, alpha=alpha)
    Z.blit(img, Z.pm_of(be), cx, cy, (0.5, 471 / 512), bs, mode="add", gain=Z.EMIT * emit_gain * alpha)


def moon_at(img, x, y, radius_px, alpha=1.0):
    moon = parts("fox_moon")[0]
    Z.blit(img, Z.pm_of(moon, tint=MOON_T), x, y, (0.5, 0.5), radius_px / P.MOON_R, mode="add", gain=Z.EMIT * alpha)


def moon_light(gain):
    """月亮压下来时，月光把整片地照冷一点（光照图）。"""
    def light(lm, cam):
        Z.glow_ellipse(lm, SW / 4, 0, SW / 2 * 0.9, SH / 2 * 1.1, MOON_T, gain, power=1.0)
    return light


def fox_panel(k: int) -> tuple[Z.Shot, str]:
    if k == 0:
        cam = Z.Cam(z=0.97, cy=4.0)
        shot = Z.Shot(cam=cam, actors=Z.default_actors(), ambient=S_DIM(0.62), pool=0.75, bloom=0.3, vignette=0.42)
        shot.light.append(moon_light(0.12))

        def sky(img, cam):
            moon_at(img, 960, 262, 250, alpha=0.65)
            r2 = np.random.default_rng(101)
            for _ in range(40):  # 月边飘的几缕青光（狐火将起）
                a = r2.uniform(0, 2 * math.pi)
                rr = r2.uniform(255, 330)
                Z.glow(img, 960 + rr * math.cos(a), 262 + rr * math.sin(a), r2.uniform(1.5, 3), FOX_T, 0.6, power=2)

        shot.sky.append(sky)
        return shot, "0.5 秒 · 天暗下来，一轮满月放大、压到画面上方，月光把地照冷；月边飘起几点青光"
    if k == 1:
        cam = Z.Cam(z=0.93, cy=4.0)
        shot = Z.Shot(cam=cam, actors=Z.default_actors(), ambient=S_DIM(0.6), pool=0.72, bloom=0.2, vignette=0.4)
        shot.light.append(moon_light(0.15))
        t = 1.3
        opened = [np.clip((t - (0.6 + 0.12 * j)) / 0.25, 0, 1) for j in range(9)]

        def sky(img, cam):
            moon_at(img, 960, 262, 315, alpha=0.7)
            fox_fan(img, 1060, 536, 1.02, opened)

        shot.sky.append(sky)
        return shot, "1.3 秒 · 拉远看全景：月前浮出九尾的剪影，尾巴从右往左一条条旋开（已开五条），每条尾尖亮起一点青火"
    if k == 2:
        cam = Z.Cam(z=0.9, cy=4.0)
        shot = Z.Shot(cam=cam, actors=Z.default_actors(), ambient=S_DIM(0.58), pool=0.7, bloom=0.26, vignette=0.38)
        shot.light.append(moon_light(0.16))

        def sky(img, cam):
            moon_at(img, 960, 262, 320, alpha=0.7)
            fox_fan(img, 1060, 536, 1.02, [1.0] * 9)
            r2 = np.random.default_rng(102)
            for _ in range(70):  # 尾尖散出来的青火星
                a = math.radians(r2.uniform(-100, 40)) - math.pi / 2
                rr = r2.uniform(300, 520)
                x, y = 1060 + (204 - 256) * 1.16 + rr * math.cos(a), 536 + (440 - 471) * 1.16 + rr * math.sin(a)
                Z.glow(img, x, y, r2.uniform(1.5, 3.5), FOX_T, r2.uniform(0.4, 1.0), power=2)

        shot.sky.append(sky)
        return shot, "1.75 秒 · 九尾全开成扇，月前一道剪影：焦墨身子、青边，尾尖九点青火；《南山经》“有兽如狐而九尾”"
    # k == 3：剪影落下，化成真身，一圈狐火环亮起
    cam = Z.Cam(z=0.9, cy=-56.0, shake=(-6.0, 5.0))  # 镜头往上让一点：真身的尾巴不贴画面上沿
    bx, by = 60.0, -88.0
    actors = Z.default_actors()
    actors = [a_ for a_ in actors if math.hypot(a_.x - bx, a_.y - by) > 110]
    boss = Z.Actor("boss/summon_E_02", bx, by, atlas="boss", flip=False)  # 游戏里的真身，照常受光，不另加光
    actors.append(boss)
    shot = Z.Shot(cam=cam, actors=actors, ambient=S_DIM(0.8), pool=0.8, bloom=0.3, vignette=0.36)
    ring_n, ring_r = 16, 168.0  # 狐火环：比第一轮放大 1.5 倍

    def ground(img, cam):
        # 落地砸起的一圈墨尘冲击波：压扁的墨环（边上毛、断续），环上几团墨溅，往外拖几道尘
        x, y = cam.s(bx, by)
        R = 210 * cam.k
        x0, x1 = int(max(x - 1.5 * R, 0)), int(min(x + 1.5 * R, SW))
        y0, y1 = int(max(y - 1.5 * R * FLAT, 0)), int(min(y + 1.5 * R * FLAT, SH))
        X, Y = np.meshgrid(np.arange(x0, x1) + 0.5, np.arange(y0, y1) + 0.5)
        re = np.hypot((X - x) / R, (Y - y) / (R * FLAT))
        th = np.arctan2((Y - y) / FLAT, X - x)
        wob = V.angular_noise(np.random.default_rng(211), th, harmonics=(5, 7, 11, 17, 23), amp=0.5)
        band = np.exp(-(((re - 1.0 - 0.04 * wob) / (0.07 + 0.03 * wob)) ** 2)) * np.clip(0.55 + 0.6 * wob, 0, 1)
        inner = np.exp(-(((re - 0.82) / 0.16) ** 2)) * 0.25
        k = np.clip(0.75 * band + inner, 0, 0.85)[..., None].astype(np.float32)
        reg = img[y0:y1, x0:x1]
        reg[:] = reg * (1 - k) + lin("#17140F").astype(np.float32) * k
        r2 = np.random.default_rng(212)
        splat = [M.atlas_frame("vfx", f"vfx/kill_ink_{i}")[0] for i in (4, 5)] + [M.atlas_frame("vfx", f"vfx/ink_{i}")[0] for i in range(3)]
        for j in range(18):
            a = 2 * math.pi * j / 18 + r2.uniform(-0.12, 0.12)
            rr = R * r2.uniform(0.92, 1.12)
            px, py = x + rr * math.cos(a), y + rr * FLAT * math.sin(a)
            Z.blit(img, Z.pm_of(splat[j % len(splat)]), px, py, (0.5, 0.5), cam.sprite * r2.uniform(0.8, 1.4), angle=a, sy=0.7, alpha=0.7)
            L = r2.uniform(30, 70)
            Z.stroke(img, [(px, py), (px + L * math.cos(a), py + L * FLAT * math.sin(a))], [r2.uniform(4, 8), 0.5], lin("#17140F").astype(np.float32),
                     mode="over", alpha=[0.5, 0.0])

    def add(img, cam):
        x, y = cam.s(bx, by)
        sw = M.atlas_frame("vfx", "vfx/shockwave_2")[0]
        Z.blit(img, Z.pm_of(sw, tint=FOX_T), x, y, (0.5, 0.5), cam.sprite * 1.6, mode="add", gain=Z.EMIT * 0.45)
        ff = [M.atlas_frame("vfx", f"weapons/foxfire_{i}")[0] for i in range(3)]
        for j in range(ring_n):  # 狐火环：现成的狐火弹排一圈，朝外
            a = 2 * math.pi * j / ring_n
            px, py = cam.s(bx + ring_r * math.cos(a), by + ring_r * FLAT * math.sin(a), 16)
            ang = math.atan2(FLAT * math.sin(a), math.cos(a))
            Z.blit(img, Z.pm_of(ff[j % 3], tint=FOX_T), px, py, (0.6, 0.5), cam.sprite * 2.7, angle=ang, mode="add", gain=Z.EMIT)
            Z.glow(img, px, py, 45, FOX_T, 0.28, power=2)

    shot.ground.append(ground)
    shot.add.append(add)
    return shot, "2.3 秒 · 剪影落下化成真身（游戏里的九尾，照常受光），砸地顿帧 0.12 秒、震屏 0.5，砸起一圈墨尘冲击波，一圈狐火环亮起（现成狐火弹排一圈，放大 1.5 倍）；接登场题字"


# ============================================================== 汇总

SHOWS = {
    "sword": {
        "panels": sword_panel,
        "n": 4,
        "hero": 2,
        "title": "万剑归宗（符剑进化）· 2.6 秒 · 分镜",
        "sub": "《庄子·说剑》：天子之剑，上决浮云。元件：myth/sword_blade_0..2（剑影 3 种，叠加染金）、sword_giant（大剑影，剑柱最外一层叠三张）、"
               "sword_cloud_0..5 + _emit（被劈开的云，焦墨 + 裂口金光）；拖尾、聚光、云缝光、收拢的排法、“归宗”题字是代码 / 界面的示意",
    },
    "kun": {
        "panels": kun_panel,
        "n": 4,
        "hero": 2,
        "title": "北冥潮（沧浪进化）· 2.4 秒 · 分镜",
        "sub": "《逍遥游》：北冥有鱼，其名为鲲；鹏之徙于南冥，水击三千里。元件：myth/kun_sea_0..5 + _emit（脚下冰海）、kun_shadow + _emit（鲲影，边上一圈冰光）、"
               "kun_fin + _emit（露出水面的背鳍）、kun_leap_0..5（跃出水的冷光剪影，鳍有骨条）；浪头、冰碴用现成的 wave_front、ice_shatter，八字浪、水珠、冻住是代码的示意",
    },
    "ult": {
        "panels": ult_panel,
        "n": 4,
        "hero": 2,
        "title": "燃灯（大招）· 1.3 秒，接现在的三拍 · 分镜",
        "sub": "《大智度论》：燃灯佛生时，身边如灯。元件：myth/ult_lotus_0..7 + _emit（莲灯开合：纸色瓣、焦褐轮廓 + 描金和灯焰）、ult_rays（放射佛光，两张反向转）、"
               "ult_halo（头光）；光迹、暗层提亮、莲灯后的暗晕和近处压低佛光、化灰是代码的示意",
    },
    "fox": {
        "panels": fox_panel,
        "n": 4,
        "hero": 2,
        "title": "九尾登场（夜主）· 3.0 秒，接现在的登场题字 · 分镜",
        "sub": "《南山经》：青丘之山，有兽如狐而九尾。元件：myth/fox_moon（月亮，叠加可染冷白）、fox_body + _emit（坐姿剪影，比例照 boss 图集的九尾，焦墨描青边）、"
               "fox_tail + _emit（一条尾巴，代码旋开九条）；尾巴旋开的排法、青火星、墨尘冲击波、狐火环（现成 weapons/foxfire）是代码的示意",
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
