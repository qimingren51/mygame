"""原型：远山三层、纸纹（之后并进 title_screen.py）。"""
from __future__ import annotations

import math
import sys

sys.path.insert(0, "/home/user/mygame/art/post")
import numpy as np  # noqa: E402

import title_screen as T  # noqa: E402

V, S = T.V, T.S
col, smoothstep, mixc, blur, noise = V.col, V.smoothstep, T.mixc, T.blur, T.noise
PAPER, PAPER_SH, JIAO, NONG, ZHONG, DAN, QING = T.PAPER, T.PAPER_SH, T.JIAO, T.NONG, T.ZHONG, T.DAN, T.QING
W, H = T.W, T.H


# ---------------------------------------------------------------- 纸
def soft_paper_tile() -> np.ndarray:
    """vfx_textures.make_paper 的配方，但纤维短、弯、软：没有几百像素长的直纤维（暗处放大后像裂纹）。2 倍密度 1024²，可平铺。"""
    size = V.dpx(512)
    rng = np.random.default_rng(1207)
    sh = (size, size)
    dark = np.zeros(sh)
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
    """整幅宣纸（同 paper_canvas 的拼法和画布尺度的浓淡），纤维用 soft_paper_tile。"""
    tile = soft_paper_tile()
    big = np.concatenate([tile, tile[:, ::-1]], 1)
    big = np.concatenate([big, big[::-1]], 0)
    out = big[37:37 + H, 61:61 + W].copy()
    cloud = T.fbm(rng, (H, W), (260.0, 90.0, 30.0), (0.5, 0.35, 0.15))
    return mixc(out, out * (PAPER_SH / PAPER), np.clip(0.18 + 0.16 * cloud, 0, 1) * 0.6)


# ---------------------------------------------------------------- 远山
MOON_X = T.MOON[0]


def range_layer(P, ridge, color, alpha, fade, rng, *, mist_from, mist_len=70.0, edge=0.45, soft=1.4, streak=0.3, shade=0.0,
                quiet=None):
    """一层远山（mountain_layer 的写法）+ 阴阳：朝月亮的一面淡（留白多），背月的一面重；越往下越平，隐进雾里。
    soft 是山脊边缘的虚实（远的虚），quiet：(H, W) 0..1，标题字和菜单后面压淡。"""
    jit = 1.2 * noise(rng, (H, W), 1.2)
    depth = P.Y - ridge[None, :] + jit
    inside = smoothstep(-soft, soft * 1.2, depth)
    top = np.exp(-np.maximum(depth, 0) / 7.0)
    body = 0.35 + 0.65 * np.exp(-np.maximum(depth, 0) / fade)
    tex = noise(rng, (H, W), (40.0, 2.5), angle=math.pi / 2 + 0.25) * 0.6 + noise(rng, (H, W), (14.0, 1.4), angle=math.pi / 2 - 0.3) * 0.4
    a = alpha * inside * (body * (1 + streak * tex) + edge * top)
    if shade:
        r1 = blur(ridge[None, :], (5.0, 0))[0]
        r2 = blur(ridge[None, :], (34.0, 0))[0]
        s1, s2 = np.gradient(r1), np.gradient(r2)
        w = smoothstep(0, 140, depth)
        s = s1[None, :] * (1 - w) + s2[None, :] * w
        side = np.sign(MOON_X - P.X)
        facing = np.tanh(2.2 * s * side)  # >0 朝月
        k = np.exp(-np.maximum(depth, 0) / (fade * 1.6))
        a = a * (1 + shade * k * (np.clip(-facing, 0, 1) * 1.0 - np.clip(facing, 0, 1) * 0.75))
    m = smoothstep(mist_from + mist_len, mist_from, P.Y + 25 * noise(rng, (H, W), (90.0, 14.0)))
    a = a * m
    if quiet is not None:
        a = a * (1 - quiet)
    P.glaze(np.clip(a, 0, 0.95), color)
    return inside * m


def hemp_cun(P, ridge, color, rng, mist_from, xs_groups, *, strength=0.35, ln=(50, 110)):
    """披麻皴：几组从山脊往下、顺着山势的长弧笔（三五笔一组，大致平行、略有聚散），淡墨干笔；山脊上几点苔。"""
    rs = blur(ridge[None, :], (10.0, 0))[0]
    slope = np.gradient(rs)
    for gx, n in xs_groups:
        i = int(np.clip(gx, 0, W - 1))
        sgn = 1.0 if slope[i] > 0 else -1.0
        base_ang = math.atan2(abs(slope[i]) + 0.55, sgn)
        for k in range(n):
            x = gx + (k - (n - 1) / 2) * rng.uniform(7, 12) * sgn * -1
            ii = int(np.clip(x, 0, W - 1))
            y = ridge[ii] + rng.uniform(3, 12)
            if y > mist_from - 30:
                continue
            ang = base_ang + rng.normal(0, 0.06)
            length = rng.uniform(*ln) * (1 - 0.15 * abs(k - (n - 1) / 2))
            ts = np.linspace(0, 1, 18)
            bend = rng.uniform(0.15, 0.4) * -sgn
            th = ang + bend * ts
            pts = np.stack([x + np.cumsum(np.cos(th)) * length / 18, y + np.cumsum(np.sin(th)) * length / 18], -1)
            hw = np.interp(ts, [0, 0.15, 0.7, 1], [0.7, rng.uniform(1.3, 2.0), 1.2, 0.4])
            P.stroke(pts, hw, color, strength * rng.uniform(0.7, 1.15), dry=0.42, dry_start=0.3, jitter=0.2, mode="glaze")


def ridge_dots(P, ridge, rng, xs, color, *, n=6, alpha=0.7):
    """苔点：山脊上几簇淡墨点。"""
    for gx in xs:
        for _ in range(n):
            x = gx + rng.normal(0, 14)
            i = int(np.clip(x, 0, W - 1))
            y = ridge[i] + rng.uniform(0.5, 4)
            r = rng.uniform(1.2, 2.6)
            P.dot(x, y, r * rng.uniform(1.1, 1.6), r, color, alpha * rng.uniform(0.7, 1.0), ang=rng.uniform(-0.4, 0.4))


def fog_band(P, rng, lo, hi, strength, amp=28.0, glow=0.5):
    wav = blur(rng.standard_normal((1, W)), (90.0, 0))[0]
    wav = amp * wav / (wav.std() + 1e-9)
    yb = P.Y + wav[None, :]
    fog = smoothstep(lo, lo + (hi - lo) * 0.55, yb) * smoothstep(hi, hi - (hi - lo) * 0.3, yb)
    fog = fog * np.clip(0.35 + 0.65 * smoothstep(-1.2, 1.2, noise(rng, (H, W), (130.0, 22.0))), 0, 1)
    P.over(np.clip(fog * strength, 0, 1), mixc(PAPER, np.ones(3), 0.2))
    P.mist = np.maximum(P.mist, np.clip(fog * glow, 0, 1))


def quiet_mask(P) -> np.ndarray:
    """标题字（左上）和菜单（左下）后面：远山压淡。"""
    lx0, ly0, lx1, ly1 = 60, 40, 960, 360  # 标题字和它的光晕
    dl = np.maximum(np.maximum(lx0 - P.X, P.X - lx1), np.maximum(ly0 - P.Y, P.Y - ly1))
    q1 = smoothstep(90, 0, dl) * 0.55
    mx0, my0, mx1, my1 = 90, 520, 420, 840
    dm = np.maximum(np.maximum(mx0 - P.X, P.X - mx1), np.maximum(my0 - P.Y, P.Y - my1))
    q2 = smoothstep(120, 0, dm) * 0.35
    return np.maximum(q1, q2)


def paint_ranges(P, rng):
    """远山三层：远的高、淡、虚，主峰在右半；中层峰位和远层错开；近的一层低而重，有披麻皴和苔点。层与层之间一道雾，
    最后山谷里一道雾。标题字和菜单后面压淡。"""
    xs = np.arange(W) + 0.5
    q = quiet_mask(P)
    # 远：主峰群在中右（主角头顶以上、月下），左边只有低低的一抹（标题字下面）
    far = T.ridge_line(xs, [(1150, 300, 230, 200, 1.45), (1330, 230, 150, 190, 1.3), (1780, 250, 210, 240, 1.35),
                            (1560, 150, 140, 150, 1.2), (620, 120, 300, 260, 1.0), (180, 90, 260, 280, 1.0)], 560, rng,
                       rough=4.0, rough_sigma=16.0)
    range_layer(P, far, mixc(QING, T.SKY_INK, 0.35), 0.32, 150.0, rng, mist_from=560, mist_len=90.0, edge=0.22, soft=3.0,
                streak=0.2, shade=0.4, quiet=q)
    fog_band(P, rng, 430, 600, 0.36, amp=34.0)
    # 中：峰位和远层错开，节奏一高一低
    mid = T.ridge_line(xs, [(905, 215, 170, 150, 1.5), (760, 150, 130, 120, 1.3), (1470, 170, 150, 170, 1.4),
                            (1640, 120, 120, 140, 1.2), (390, 110, 200, 180, 1.1), (1240, 95, 120, 120, 1.1)], 650, rng,
                       rough=5.0, rough_sigma=18.0)
    range_layer(P, mid, mixc(QING, DAN, 0.55), 0.40, 105.0, rng, mist_from=650, mist_len=75.0, edge=0.4, soft=1.8, streak=0.3,
                shade=0.55, quiet=q)
    hemp_cun(P, mid, mixc(QING, ZHONG, 0.5), rng, 650, [(880, 3), (950, 3), (1440, 3), (1500, 3), (735, 2)], strength=0.22, ln=(35, 70))
    fog_band(P, rng, 540, 690, 0.34, amp=30.0)
    # 近：低而重，两座有形的山头，披麻皴、苔点
    near = T.ridge_line(xs, [(1330, 132, 190, 160, 1.25), (560, 112, 210, 180, 1.15), (1010, 70, 140, 150, 1.0),
                             (1760, 100, 160, 200, 1.1)], 735, rng, rough=6.0, rough_sigma=18.0)
    range_layer(P, near, mixc(DAN, ZHONG, 0.15), 0.48, 80.0, rng, mist_from=735, mist_len=70.0, edge=0.5, soft=1.2, streak=0.35,
                shade=0.7, quiet=q)
    hemp_cun(P, near, mixc(DAN, NONG, 0.45), rng, 735, [(1262, 4), (1300, 3), (1395, 4), (1440, 3), (505, 4), (600, 3), (1710, 3),
                                                        (1060, 3), (960, 3)], strength=0.4)
    ridge_dots(P, near, rng, [1300, 1350, 560, 600, 1720], mixc(ZHONG, NONG, 0.4), n=5, alpha=0.6)
    # 山谷里的一道雾（同旧版）
    wav = blur(rng.standard_normal((1, W)), (120.0, 0))[0]
    yb = P.Y + (34.0 * wav / (wav.std() + 1e-9))[None, :]
    fog = smoothstep(650, 735, yb) * smoothstep(900, 770, yb) * np.clip(0.35 + 0.65 * smoothstep(-1.3, 1.3, noise(rng, (H, W), (180.0, 24.0))), 0, 1)
    P.over(np.clip(fog * 0.55, 0, 1), mixc(PAPER, np.ones(3), 0.25))
    P.mist = np.maximum(P.mist, np.clip(fog, 0, 1))
