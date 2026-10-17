# ============================================================== 第二批：火爆（自带颜色）和它的墨烟

FIRE = [(0.0, "#C2361E"), (0.45, "#FF8A3D"), (0.78, "#FFC27A"), (1.0, "#FFF1C2")]  # 热度 0 → 1：边 → 芯
FIRE_SIZE = 384  # 清单写 256²；按 1080p 下约一比一放大到 384²（爆燃半径 44–69 在 1080p 下是 113–177 像素）
FS = FIRE_SIZE / 256  # 下面的像素量按 256² 的画布写，乘 FS
FIRE_C = (192.0, 240.0)  # 爆点（锚点）：偏下，火往上窜、墨烟往上飘，上面留的地方多
FIRE_R = 144  # 火团加火舌的有效半径（像素）= 爆燃半径；1080p 下 56 世界单位一比一
FIRE_LEN = [0.3, 0.75, 1.0, 1.04, 1.0, 0.9, 0.76]  # 火舌长度（× L）
FIRE_WID = [1.0, 1.0, 0.95, 0.8, 0.6, 0.42, 0.28]  # 火舌粗细
FIRE_RISE = [FS * v for v in (0.0, 2.0, 5.0, 9.0, 14.0, 19.0, 24.0)]  # 火舌整体往上飘（像素）


def fire_tongues() -> list[dict]:
    """火爆的大火舌（火爆和墨烟共用）：八条朝上半圈散开、两条短的往下两边。"""
    rng = np.random.default_rng(9921)
    out = []
    for k in range(8):
        phi = math.radians(-90 + (k - 3.5) * 34 + rng.uniform(-8, 8))
        out.append(dict(phi=phi, L=FS * rng.uniform(72, 90), Wd=FS * rng.uniform(9.0, 12.5), curl=float(rng.choice([-1.0, 1.0]) * rng.uniform(0.5, 1.0)),
                        seed=int(rng.integers(1 << 30))))
    for k in range(2):
        phi = math.radians(90 + (1 if k else -1) * rng.uniform(35, 55))
        out.append(dict(phi=phi, L=FS * rng.uniform(40, 48), Wd=FS * rng.uniform(7.0, 9.0), curl=0.6 * (1 if k else -1), seed=int(rng.integers(1 << 30))))
    return out


def tongue_points(tg: dict, i: int, cx: float, cy: float) -> np.ndarray:
    """第 i 帧这条火舌的中线：从爆点往外冲，再往上卷。"""
    L = tg["L"] * FIRE_LEN[i]
    ux, uy = math.cos(tg["phi"]), math.sin(tg["phi"])
    b = np.array([cx + 8 * FS * ux, cy + 8 * FS * uy - FIRE_RISE[i]])
    up = np.array([0.0, -1.0])
    side = np.array([-uy, ux]) * tg["curl"]
    ctrl = [b, b + np.array([ux, uy]) * L * 0.45, b + np.array([ux, uy]) * L * 0.6 + up * L * 0.42, b + up * L * 0.8 + side * L * 0.32]
    return V.bezier(ctrl, 90)


def make_fire_burst() -> list[Image.Image]:
    """火爆：第 0 帧爆点一团烧白的闪；1–3 帧炸开成一团火——十八条短火苗从芯里往四面舔出去（尖往上翘；朝下的短、钝，
    像火团底下鼓出来的一圈），八条大火舌冲得更远、再往上卷（钉头鼠尾、尖上飞白），火星往上飘；4–6 帧芯先空、
    火苗往外散成一圈，火舌越卷越细往上飘。颜色按热度：芯 #FFF1C2 → #FF8A3D → 边和火舌尖 #C2361E。叠加，自带颜色，不染。
    尾巴两帧火舌尖上的墨烟是普通混合，单独在 fire_burst_smoke_0..1。"""
    w = h = FIRE_SIZE
    cx, cy = FIRE_C
    rng = np.random.default_rng(9920)
    tongues = fire_tongues()
    licks = [(2 * math.pi * (k + rng.uniform(-0.3, 0.3)) / 18, rng.uniform(1.0, 1.35), FS * rng.uniform(6.0, 9.0), int(rng.integers(1 << 30))) for k in range(18)]
    embers = [(rng.uniform(-1, 1), FS * rng.uniform(50, 100), FS * rng.uniform(0.9, 1.5), rng.uniform(0, 6)) for _ in range(12)]
    Rb = [FS * v for v in (20.0, 38.0, 50.0, 56.0, 58.0, 56.0, 50.0)]  # 火团（短火苗）的半径
    R0 = [FS * v for v in (3.0, 6.0, 9.0, 13.0, 19.0, 24.0, 28.0)]  # 短火苗的根（芯空出来）
    RC = [FS * v for v in (14.0, 22.0, 26.0, 26.0, 24.0, 1.0, 1.0)]  # 芯的半径
    lick_env = [0.9, 1.0, 1.0, 0.9, 0.7, 0.48, 0.26]
    core = [1.0, 0.95, 0.8, 0.5, 0.2, 0.0, 0.0]
    cool = [0.0, 0.04, 0.1, 0.2, 0.32, 0.45, 0.58]  # 越往后越冷（颜色往边上的红退）
    out = []
    for i in range(7):
        X, Y = grid(w, h)
        acc = Acc(X, Y)
        full = (slice(None), slice(None))
        r = np.hypot(X - cx, Y - cy)
        if core[i] > 0:  # 芯：一团烧白，碎成放射的细纹
            spokes = np.clip(0.55 + V.angular_noise(np.random.default_rng(9923), np.arctan2(Y - cy, X - cx), harmonics=(7, 11, 13, 17, 23), amp=1.4), 0, 1)
            acc.add(full, core[i] * np.exp(-((r / RC[i]) ** 2)) * (0.6 + 0.4 * spokes), 1.0 - cool[i])
        for ang, lf, wd, sd in licks:  # 短火苗：从芯里往外舔，尖往上翘；朝下的短、钝
            down = max(0.0, math.sin(ang))
            L = Rb[i] * lf * (1.0 - 0.45 * down)
            r0 = R0[i]
            if L <= r0 + 4 * FS:
                continue
            u = np.array([math.cos(ang), math.sin(ang)])
            b = np.array([cx, cy]) + u * r0
            tip = np.array([cx, cy]) + u * L + np.array([0.0, -(0.28 + 0.3 * down) * L - FIRE_RISE[i] * 0.5])
            pts = V.bezier([b, b + (tip - b) * 0.5 + u * 4 * FS, tip], 60)
            tt = np.linspace(0, 1, len(pts))
            hw = wd * (1.0 - 0.25 * i / 6) * np.sin(np.pi * np.clip(0.15 + 0.85 * tt, 0, 1)) ** 0.5 * (1 - tt) ** (0.7 - 0.35 * down) + 0.15
            lo, hi = pts.min(0) - wd * 2.5, pts.max(0) + wd * 2.5
            sl = acc.window(lo[0], lo[1], hi[0], hi[1])
            cov, _ = V.brush_stroke(X[sl], Y[sl], pts, hw, np.random.default_rng(sd + i // 2), dry=0.2 + 0.08 * i, dry_start=0.5, ss=SS)
            heat = np.clip(0.95 - 0.7 * np.clip((r[sl] - r0) / max(L - r0, 1.0), 0, 1) - cool[i], 0, 1)
            acc.add(sl, lick_env[i] * cov, heat)
        for tg in tongues:  # 大火舌
            if i == 0:
                continue
            pts = tongue_points(tg, i, cx, cy)
            tt = np.linspace(0, 1, len(pts))
            hw = tg["Wd"] * FIRE_WID[i] * (0.6 + 0.4 * np.sin(np.pi * np.clip(tt / 0.3, 0, 1) * 0.5)) * (1 - tt) ** 0.8
            lo, hi = pts.min(0) - tg["Wd"] * 2.5, pts.max(0) + tg["Wd"] * 2.5
            sl = acc.window(lo[0], lo[1], hi[0], hi[1])
            cov, _ = V.brush_stroke(X[sl], Y[sl], pts, np.maximum(hw, 0.05), np.random.default_rng(tg["seed"]), dry=0.3 + 0.08 * i, dry_start=0.45, ss=SS)
            dist = np.hypot(X[sl] - pts[0][0], Y[sl] - pts[0][1]) / max(tg["L"] * FIRE_LEN[i], 1.0)
            acc.add(sl, min(1.0, 1.15 - 0.12 * i) * cov, np.clip(0.85 - 0.75 * dist - cool[i] * 0.6, 0, 1))
        for x0, d1, sz, ph in embers:
            if i < 2:
                continue
            t = (i - 1) / 5
            px = cx + x0 * 70 * FS + 6 * FS * math.sin(4 * t + ph)
            py = cy - 20 * FS - d1 * ease_out(t, 1.3)
            sl = acc.window(px - 4 * sz, py - 4 * sz, px + 4 * sz, py + 6 * FS + 4 * sz)
            acc.add(sl, 0.85 * (1 - 0.8 * t) * streak(X[sl], Y[sl], px, py + 6 * FS, px, py, sz), 0.75 - 0.4 * t)
        out.append(frame_color(acc.a, acc.heat(), 9925 + i, FIRE))
    return out


def make_fire_smoke() -> list[Image.Image]:
    """火爆最后两帧（fire_burst 的第 5、6 帧）火舌尖上冒的墨烟：六缕焦墨从火舌尖往上 S 形地卷，起笔浓、往上变细变干，
    第二帧更高、更散、更淡。普通混合，焦墨，不染；和 fire_burst 同画布、同锚点，从它的第 5 帧开始一起播。"""
    w = h = FIRE_SIZE
    cx, cy = FIRE_C
    X, Y = grid(w, h)
    rng = np.random.default_rng(9940)
    tongues = fire_tongues()[1:7]  # 两边最外的两条不冒烟，免得一圈太满
    wisps = [(FS * rng.uniform(26, 36), float(rng.choice([-1.0, 1.0])), FS * rng.uniform(1.8, 2.6), int(rng.integers(1 << 30))) for _ in tongues]
    out = []
    for j, i in enumerate((5, 6)):
        a = np.zeros_like(X)
        for tg, (L, turn, wd, sd) in zip(tongues, wisps):
            tip = tongue_points(tg, i, cx, cy)[-1]
            rise = FS * (3.0 + 9.0 * j)
            ctrl = [tip + np.array([0.0, -rise * 0.4]), tip + np.array([turn * L * 0.3, -L * 0.35 - rise]),
                    tip + np.array([-turn * L * 0.25, -L * 0.7 - rise]), tip + np.array([turn * L * 0.1, -L - rise])]
            pts = V.bezier(ctrl, 90)
            tt = np.linspace(0, 1, len(pts))
            hw = wd * (1.0 + 0.4 * j) * (1.0 - 0.6 * tt) * np.sin(np.clip(tt * 3.0, 0, 1) * np.pi / 2) ** 0.6 + 0.12
            cov = V.brush_stroke(X, Y, pts, hw, np.random.default_rng(sd + j), dry=0.4 + 0.2 * j, dry_start=0.3 - 0.1 * j, ss=SS)[0]
            a = np.maximum(a, [0.72, 0.5][j] * cov)
        out.append(frame_ink(a, 9945 + j))
    return out


