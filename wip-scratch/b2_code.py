# ============================================================== 第二批：火爆（自带颜色）和它的墨烟

FIRE = [(0.0, "#C2361E"), (0.45, "#FF8A3D"), (0.78, "#FFC27A"), (1.0, "#FFF1C2")]  # 热度 0 → 1：边 → 芯
FIRE_R = 96  # 火球加火舌横向的有效半径（像素），按爆燃半径缩放用
FIRE_LEN = [0.3, 0.75, 1.0, 1.04, 1.0, 0.9, 0.76]  # 火舌长度（× L）
FIRE_WID = [1.0, 1.0, 0.95, 0.8, 0.6, 0.42, 0.28]  # 火舌粗细
FIRE_RISE = [0.0, 2.0, 6.0, 11.0, 17.0, 23.0, 29.0]  # 火舌整体往上飘（像素）


def fire_tongues() -> list[dict]:
    """火爆的火舌（火爆和墨烟共用）：八条朝上半圈散开、两条短的往下两边。"""
    rng = np.random.default_rng(9921)
    out = []
    for k in range(8):
        phi = math.radians(-90 + (k - 3.5) * 34 + rng.uniform(-8, 8))
        out.append(dict(phi=phi, L=rng.uniform(62, 80), Wd=rng.uniform(9.0, 12.5), curl=float(rng.choice([-1.0, 1.0]) * rng.uniform(0.5, 1.0)),
                        seed=int(rng.integers(1 << 30))))
    for k in range(2):
        phi = math.radians(90 + (1 if k else -1) * rng.uniform(35, 55))
        out.append(dict(phi=phi, L=rng.uniform(34, 42), Wd=rng.uniform(7.0, 9.0), curl=0.6 * (1 if k else -1), seed=int(rng.integers(1 << 30))))
    return out


def tongue_points(tg: dict, i: int, cx: float, cy: float) -> np.ndarray:
    """第 i 帧这条火舌的中线：从爆点往外冲，再往上卷。"""
    L = tg["L"] * FIRE_LEN[i]
    ux, uy = math.cos(tg["phi"]), math.sin(tg["phi"])
    b = np.array([cx + 8 * ux, cy + 8 * uy - FIRE_RISE[i]])
    up = np.array([0.0, -1.0])
    side = np.array([-uy, ux]) * tg["curl"]
    ctrl = [b, b + np.array([ux, uy]) * L * 0.45, b + np.array([ux, uy]) * L * 0.6 + up * L * 0.42, b + up * L * 0.8 + side * L * 0.32]
    return V.bezier(ctrl, 90)


def make_fire_burst() -> list[Image.Image]:
    """火爆：第 0 帧芯里一团烧白的闪；1–3 帧一团边缘起毛的火球炸开，八条火舌往外冲、再往上卷（钉头鼠尾、尖上飞白），
    火星往上飘；4–6 帧火球散开、中间先空，火舌越卷越细往上飘。颜色按热度：芯 #FFF1C2 → #FF8A3D → 边和火舌尖 #C2361E。
    叠加，自带颜色，不染。尾巴两帧火舌尖上的墨烟是普通混合，单独在 fire_burst_smoke_0..1。"""
    w = h = 256
    cx, cy = 128.0, 128.0
    X, Y = grid(w, h)
    rng = np.random.default_rng(9920)
    tex = W.ptex(rng, ns=16, nt=1024, along=10.0, across=0.8)
    dx, dy = X - cx, Y - cy
    r = np.hypot(dx, dy)
    th = np.arctan2(dy, dx)
    tongues = fire_tongues()
    embers = [(rng.uniform(-1, 1), rng.uniform(50, 100), rng.uniform(0.9, 1.5), rng.uniform(0, 6)) for _ in range(12)]
    Rb = [24.0, 50.0, 64.0, 70.0, 72.0, 70.0, 64.0]
    body_env = [1.0, 1.0, 0.95, 0.8, 0.58, 0.38, 0.2]
    hole = [0.0, 0.0, 0.0, 0.2, 0.45, 0.62, 0.74]
    cool = [0.0, 0.05, 0.12, 0.22, 0.34, 0.46, 0.58]  # 越往后越冷（颜色往边上的红退）
    out = []
    for i in range(7):
        parts = []
        edge = rough_radius(np.random.default_rng(9922 + i // 3), th, Rb[i], 0.2, harmonics=(4, 5, 6, 7, 9, 11))
        rho = r / edge
        body = smoothstep(1.08, 0.82, rho)
        if hole[i] > 0:
            body = body * smoothstep(hole[i] * 0.7, hole[i] * 1.15, rho)
        licks = dry(tex, np.clip(rho * 2 - 1, -1, 1), (th / (2 * math.pi)) % 1.0 + 0.07 * i, np.clip(0.05 + 0.5 * smoothstep(0.55, 1.05, rho) + 0.3 * cool[i], 0, 0.95))
        parts.append((body_env[i] * body * licks, np.clip(1.0 - 0.7 * rho**1.6 - cool[i], 0, 1)))
        if i <= 1:
            parts.append(([1.0, 0.7][i] * np.exp(-((r / [14.0, 20.0][i]) ** 2)), 1.0))
        for tg in tongues:
            if i == 0:
                continue
            pts = tongue_points(tg, i, cx, cy)
            tt = np.linspace(0, 1, len(pts))
            hw = tg["Wd"] * FIRE_WID[i] * (0.6 + 0.4 * np.sin(np.pi * np.clip(tt / 0.3, 0, 1) * 0.5)) * (1 - tt) ** 0.8
            cov, f = V.brush_stroke(X, Y, pts, np.maximum(hw, 0.05), np.random.default_rng(tg["seed"]), dry=0.3 + 0.08 * i, dry_start=0.45, ss=SS), None
            cov = cov[0]
            # 火舌的热度：根上热、尖上冷
            dist = np.hypot(X - pts[0][0], Y - pts[0][1]) / max(tg["L"] * FIRE_LEN[i], 1.0)
            parts.append((min(1.0, 1.15 - 0.1 * i) * cov, np.clip(0.85 - 0.75 * dist - cool[i] * 0.6, 0, 1)))
        for x0, d1, sz, ph in embers:
            if i < 2:
                continue
            t = (i - 1) / 5
            px = cx + x0 * 70 + 6 * math.sin(4 * t + ph)
            py = cy - 20 - d1 * ease_out(t, 1.3)
            parts.append((0.85 * (1 - 0.8 * t) * streak(X, Y, px, py + 6, px, py, sz), 0.75 - 0.4 * t))
        a, heat = union_heat(parts)
        out.append(frame_color(a, heat, 9925 + i, FIRE))
    return out


def make_fire_smoke() -> list[Image.Image]:
    """火爆最后两帧（fire_burst 的第 5、6 帧）火舌尖上冒的墨烟：几缕焦墨从火舌尖往上卷，干笔、断续，第二帧更高、更散、更淡。
    普通混合，焦墨，不染；和 fire_burst 同画布、同锚点，从它的第 5 帧开始一起播。"""
    w = h = 256
    cx, cy = 128.0, 128.0
    X, Y = grid(w, h)
    rng = np.random.default_rng(9940)
    tongues = fire_tongues()[:8]
    wisps = [(rng.uniform(16, 28), rng.choice([-1.0, 1.0]), rng.uniform(2.2, 3.6), int(rng.integers(1 << 30))) for _ in tongues]
    out = []
    for j, i in enumerate((5, 6)):
        a = np.zeros_like(X)
        for tg, (L, turn, wd, sd) in zip(tongues, wisps):
            tip = tongue_points(tg, i, cx, cy)[-1]
            rise = 6.0 + 12.0 * j
            # 一缕往上卷的烟：起点在火舌尖，往上、往一边弯，尾巴卷回来一点
            ctrl = [tip + np.array([0.0, -2.0 - rise * 0.3]), tip + np.array([turn * L * 0.35, -L * 0.45 - rise]),
                    tip + np.array([-turn * L * 0.15, -L * 0.9 - rise]), tip + np.array([turn * L * 0.3, -L * 1.15 - rise])]
            pts = V.bezier(ctrl, 80)
            tt = np.linspace(0, 1, len(pts))
            hw = wd * (1.0 + 0.6 * j) * np.sin(np.pi * np.clip(tt * 1.1, 0, 1)) ** 0.7 + 0.15
            cov = V.brush_stroke(X, Y, pts, hw, np.random.default_rng(sd + j), dry=0.45 + 0.2 * j, dry_start=0.25, ss=SS)[0]
            a = np.maximum(a, [0.62, 0.42][j] * cov)
        out.append(frame_ink(a, 9945 + j))
    return out


# ============================================================== 第二批：冰碎


def make_ice_shatter() -> list[Image.Image]:
    """冰碎：第 0 帧一块六角冰晶，边亮、里面几道裂纹闪亮；第 1 帧裂开（碎片刚分开一条缝，裂缝最亮）；
    2–5 帧七片尖碎片往外飞散、打转、变小变淡，碎片边亮、里面淡，后面拖一点冰尘。白色可染（建议 #CDEBFF）。"""
    w = h = 192
    cx = cy = 96.0
    X, Y = grid(w, h)
    rng = np.random.default_rng(9931)
    Rb = 30.0
    hexv = np.array([(cx + Rb * 0.86 * math.cos(math.radians(60 * k + 30)), cy + Rb * math.sin(math.radians(60 * k + 30))) for k in range(6)])
    p0 = np.array([cx + rng.uniform(-4, 4), cy + rng.uniform(-4, 4)])
    # 沿六角形的周长挑 7 个点，和里面的 p0 连起来，切成 7 片扇形的尖碎片
    seglen = np.hypot(*(np.roll(hexv, -1, 0) - hexv).T)
    cum = np.concatenate([[0.0], np.cumsum(seglen)])
    per = cum[-1]
    cuts = np.sort((np.arange(7) + rng.uniform(-0.3, 0.3, 7)) / 7 * per + rng.uniform(0, per))
    cuts = np.mod(cuts, per)
    cuts.sort()

    def at(sv):
        k = int(np.searchsorted(cum, sv, side="right") - 1) % 6
        f = (sv - cum[k]) / seglen[k]
        return hexv[k] + f * (hexv[(k + 1) % 6] - hexv[k]), k

    shards = []
    for k in range(7):
        s0, s1 = cuts[k], cuts[(k + 1) % 7] + (per if k == 6 else 0.0)
        pa, ka = at(s0)
        pb, kb = at(s1 % per)
        poly = [p0, pa]
        j = ka
        steps = int(round((s1 - s0) / per * 6)) + 2
        for _ in range(steps):  # 中间经过的六角形顶点
            j = (j + 1) % 6
            vs = cum[j] if cum[j] >= s0 else cum[j] + per
            if s0 < vs < s1:
                poly.append(hexv[j])
        poly.append(pb)
        poly = np.array(poly)
        c = poly.mean(0)
        d = c - p0
        d = d / (np.linalg.norm(d) + 1e-9)
        shards.append(dict(poly=poly, c=c, d=d, speed=rng.uniform(48, 66), spin=rng.uniform(-1.4, 1.4)))
    dust = [(rng.uniform(0, 2 * math.pi), rng.uniform(20, 70), rng.uniform(0.6, 1.1)) for _ in range(16)]
    tex = W.ptex(rng, ns=12, nt=512, along=9.0, across=0.8)
    off = [0.0, 3.5, 18.0, 34.0, 46.0, 54.0]
    env = [0.95, 1.0, 0.92, 0.72, 0.48, 0.24]
    out = []
    for i in range(6):
        t = i / 5
        a = []
        for sh in shards:
            ang = sh["spin"] * ease_out(t, 1.6) if i >= 2 else 0.0
            k = off[i] * sh["speed"] / 57.0
            ca, sa = math.cos(ang), math.sin(ang)
            sc_ = 1.0 - 0.18 * t
            rel = (sh["poly"] - sh["c"]) * sc_
            rot = np.stack([rel[:, 0] * ca - rel[:, 1] * sa, rel[:, 0] * sa + rel[:, 1] * ca], -1)
            poly = rot + sh["c"] + sh["d"] * k + np.array([0.0, 6.0 * t * t])
            cov, dd = poly_cover(X, Y, poly)
            rim = smoothstep(1.5, 0.0, np.abs(dd)) * (dd < 0.8)
            a.append(env[i] * np.clip(0.3 * cov + 0.9 * rim, 0, 1))
        if i <= 1:  # 裂纹闪亮、冰芯一亮
            a.append([0.55, 0.85][i] * np.exp(-((np.hypot(X - p0[0], Y - p0[1]) / [7.0, 10.0][i]) ** 2)))
        if 1 <= i <= 3:  # 一圈碎霜往外扩
            R = [0, 36, 58, 76][i]
            q = (np.hypot(X - cx, Y - cy) - R) / 3.0
            a.append([0, 0.5, 0.36, 0.18][i] * np.exp(-(q**2)) * dry(tex, np.clip(q / 2, -1, 1), (np.arctan2(Y - cy, X - cx) / (2 * math.pi)) % 1, 0.45))
        for ang, d1, sz in dust:
            if i == 0:
                continue
            d = 8 + d1 * ease_out(t, 1.5)
            x1, y1 = cx + d * math.cos(ang), cy + d * math.sin(ang) + 5 * t * t
            x0, y0 = cx + (d - 6) * math.cos(ang), cy + (d - 6) * math.sin(ang)
            a.append(0.7 * (1 - 0.8 * t) * streak(X, Y, x0, y0, x1, y1, sz))
        out.append(frame_white(soft_union(*a), 9935 + i))
    return out


# ============================================================== 第二批：羽毛、纸屑粒子（4 种，不是动画）

FEATHER_W, FEATHER_H = 32, 16


def make_feather() -> list[Image.Image]:
    """散开用的小粒子（4 种，不是动画）：0、1 是羽毛（羽轴一线浅，羽片两边不对称、有一两道开叉，根上一小截光羽管），
    2 是对折过的纸片（折痕一线浅，折过去的一半淡一点），3 是撕下的纸屑（一边毛边）。尖 / 长边朝 +X，锚点居中；
    白色可染（建议纸白 #EDE6D6），浓淡在 alpha 里；小图不抖动，边缘干净（同 vfx/bamboo_leaf）。"""
    ss = 8
    X, Y = V.grid(FEATHER_H, FEATHER_W, ss)
    out = []
    rng = np.random.default_rng(9951)

    def finish(a):
        a = V.downsample(np.clip(a, 0, 1), ss)
        a[0, :] = a[-1, :] = a[:, 0] = a[:, -1] = 0.0
        a8 = np.clip(np.round(a * 255.0), 0, 255).astype(np.uint8)
        return Image.fromarray(np.dstack([np.full(a8.shape + (3,), 255, np.uint8), a8]), "RGBA")

    for k, (L, wu, wl, bend, splits) in enumerate(((27.0, 5.4, 3.6, 0.8, (0.62,)), (25.0, 4.6, 3.2, -1.2, (0.45, 0.78)))):
        x0 = (FEATHER_W - L) / 2
        s = (X - x0) / L  # 沿羽轴 0（根）..1（尖）
        sc = np.clip(s, 0, 1)
        yc = FEATHER_H / 2 + bend * (4 * (sc - 0.5) ** 2 - 0.5) + 0.6 * k
        perp = Y - yc
        vane_s = np.clip((s - 0.16) / 0.84, 0, 1)
        prof_u = wu * np.sin(np.pi * vane_s**0.75) ** 0.75 * (1 - 0.1 * vane_s)
        prof_l = wl * np.sin(np.pi * vane_s**0.65) ** 0.8
        prof = np.where(perp < 0, prof_u, prof_l)
        vane = smoothstep(prof + 0.15, prof - 0.15, np.abs(perp)) * (s > 0.16) * (s < 1.0)
        # 羽枝：斜着往根上倒的细纹；开叉：沿羽枝方向的一道空
        barb = (s * L) + np.abs(perp) * 0.9
        stripes = 0.5 + 0.5 * np.cos(2 * np.pi * barb / 1.6)
        for sp_ in splits:
            gap = np.abs(barb - (sp_ * L + 2.0)) < 0.35
            vane = vane * (1 - gap * (np.abs(perp) > 0.6))
        shaft = smoothstep(0.55, 0.25, np.abs(perp)) * (s > 0.0) * (s < 1.0)
        quill = shaft * (s < 0.18)
        a = np.maximum(vane * (0.78 + 0.14 * stripes - 0.18 * sc), 0.95 * quill)
        a = a - 0.3 * smoothstep(0.35, 0.1, np.abs(perp)) * (s > 0.16) * (s < 0.95)  # 羽轴浅一线
        out.append(finish(a))
    # 2：对折过的纸片（四边形，斜的折痕）
    poly = np.array([(4.0, 5.0), (27.5, 3.2), (29.0, 11.0), (5.5, 12.8)])
    cov, dd = poly_cover(X, Y, poly, aa=0.15)
    crease = np.abs((X - 15.0) * 0.55 - (Y - 8.0) * 1.0)
    folded = (X - 15.0) * 0.55 - (Y - 8.0) > 0
    a = cov * np.where(folded, 0.72, 0.92) - 0.35 * cov * smoothstep(0.5, 0.15, crease)
    out.append(finish(a))
    # 3：撕下的纸屑（右边是毛边）
    xs = np.linspace(0, FEATHER_H, 24)
    jag = 25.0 + rng.uniform(-1.6, 1.6, len(xs)) + 1.2 * np.sin(xs * 1.3)
    right = np.interp(Y, xs, jag)
    body = smoothstep(4.6, 5.0, X) * smoothstep(right + 0.3, right - 0.3, X) * smoothstep(3.6, 4.0, Y) * smoothstep(12.6, 12.2, Y)
    # 尖朝 +X：上下两条边往右收一点
    taper = smoothstep(0.0, 1.0, (12.4 - Y) - (X - 5) * 0.08) * smoothstep(0.0, 1.0, (Y - 3.8) - (X - 5) * 0.06)
    fibre = smoothstep(right - 2.2, right, X) * (0.4 + 0.6 * (V.fft_blur(rng.standard_normal(X.shape), (0.3 * ss, 2.0 * ss)) > 0))
    a = body * taper * (0.9 - 0.45 * fibre)
    out.append(finish(a))
    return out


# ============================================================== 第二批：进化爆发（日轮 / 莲花）与光柱

GOLD = [(0.0, "#E3B05A"), (0.55, "#FFE7A8"), (1.0, "#FFF8E8")]  # 进化：外边偏暖、主色 #FFE7A8、芯偏白
EVOLVE_SIZE = 512


def make_evolve() -> list[Image.Image]:
    """进化爆发：中心一朵放射状的光，像莲花也像日轮——八片尖瓣从里往外开（瓣边亮、瓣心淡），里圈八片小瓣错开；
    九道笔锋光芒从中心射出去（起笔饱满、收笔尖、带飞白），一圈短的日芒；中心一点烧白。
    0–3 帧开花、光芒伸长，4–5 帧开到最大、往外散、变干，末两帧光芒断成一截截、散成光点往外飘。叠加，自带金色 #FFE7A8，不染。"""
    size = EVOLVE_SIZE
    c = size / 2
    X, Y = grid(size, size)
    rng = np.random.default_rng(9961)
    tex = W.ptex(rng, ns=24, nt=1024, along=24.0, across=0.6)
    dx, dy = X - c, Y - c
    r = np.hypot(dx, dy)
    th = np.arctan2(dy, dx)
    petal_len = [40.0, 92.0, 122.0, 136.0, 142.0, 144.0, 140.0, 132.0]
    petal_env = [0.9, 1.0, 1.0, 0.95, 0.78, 0.55, 0.3, 0.12]
    ray_len = [80.0, 160.0, 205.0, 225.0, 232.0, 232.0, 226.0, 220.0]
    ray_w = [9.0, 10.0, 9.5, 8.0, 6.5, 5.0, 3.6, 2.6]
    ray_env = [0.9, 1.0, 1.0, 0.92, 0.75, 0.55, 0.35, 0.18]
    rays = [(math.radians(20 + 40 * k + rng.uniform(-6, 6)), rng.uniform(0.85, 1.0), rng.uniform(-0.06, 0.06), int(rng.integers(1 << 30))) for k in range(9)]
    motes = [(rng.uniform(0, 2 * math.pi), rng.uniform(60, 200), rng.uniform(1.0, 2.2), rng.uniform(16, 48)) for _ in range(90)]
    out = []
    for i in range(8):
        t = i / 7
        parts = []
        spin = math.radians(3.0 * i)
        for layer, (n, a0, scale, env_k, heat_k) in enumerate(((8, 0.0, 1.0, 1.0, 0.62), (8, math.pi / 8, 0.62, 0.8, 0.75))):
            for k in range(n):
                ang = a0 + 2 * math.pi * k / n + spin * (1 if layer == 0 else -1)
                L = petal_len[i] * scale
                base = np.array([c + 10 * math.cos(ang), c + 10 * math.sin(ang)])
                tip = base + L * np.array([math.cos(ang), math.sin(ang)])
                poly = W.almond(base, tip, 0.42 * L, n=40, bulge=0.42, asym=0.0)
                cov, dd = poly_cover(X, Y, poly)
                rim = smoothstep(2.2, 0.0, np.abs(dd)) * (dd < 1.0)
                along = np.clip(((X - base[0]) * math.cos(ang) + (Y - base[1]) * math.sin(ang)) / max(L, 1.0), 0, 1)
                fill = 0.28 * cov * (1 - 0.5 * along)
                m = dry(tex, np.clip(dd / 6.0, -1, 1), along * 0.5 + 0.13 * k + 0.5 * layer, 0.1 + 0.55 * t * t)
                parts.append((petal_env[i] * env_k * np.clip(fill + 0.85 * rim, 0, 1) * m, heat_k))
        for ang, lf, bend, sd in rays:
            L = ray_len[i] * lf
            n = 100
            tt = np.linspace(0, 1, n)
            r0 = 22.0 + 10 * t
            rr = r0 + tt * L
            aa = ang + bend * tt**2
            pts = np.stack([c + rr * np.cos(aa), c + rr * np.sin(aa)], -1)
            hw = ray_w[i] * np.sin(np.pi * np.clip(tt * 0.95 + 0.05, 0, 1)) ** 0.5 * (1 - tt) ** 0.6 + 0.2
            cov = V.brush_stroke(X, Y, pts, hw, np.random.default_rng(sd + i // 3), dry=0.3 + 0.55 * t, dry_start=0.35 - 0.25 * t, ss=SS)[0]
            if i >= 6:  # 光芒断成一截截
                cut = 0.5 + 0.5 * np.sin(r / (9.0 - i) + sd % 7)
                cov = cov * smoothstep(0.35, 0.6, cut)
            parts.append((ray_env[i] * cov, np.clip(0.95 - 0.55 * r / 240.0, 0, 1)))
        if 1 <= i <= 4:  # 日芒：一圈短的放射细光
            R0 = [0, 58, 72, 82, 88][i]
            for k in range(36):
                ang = 2 * math.pi * (k + 0.5) / 36 + 0.02 * i
                L = (10 + 8 * ((k * 7) % 5) / 4) * (1 - 0.15 * i)
                cv, _ = needle(X, Y, c + R0 * math.cos(ang), c + R0 * math.sin(ang), ang, L, 1.2, taper=1.0)
                parts.append(([0, 0.55, 0.5, 0.36, 0.2][i] * cv, 0.8))
        core = [1.0, 0.95, 0.85, 0.7, 0.5, 0.3, 0.12, 0.0][i]
        if core > 0:
            spokes = np.clip(0.55 + V.angular_noise(np.random.default_rng(9962), th, harmonics=(9, 13, 17, 23), amp=1.2), 0, 1)
            parts.append((core * np.exp(-((r / (20.0 + 6 * i)) ** 2)) * (0.6 + 0.4 * spokes), 1.0))
        if i >= 5:  # 散成光点往外飘
            k_ = (i - 4) / 3
            for ang, d1, sz, drift in motes:
                d = d1 + drift * k_
                if d > 238:
                    continue
                parts.append(((1.0 - 0.55 * k_) * 0.9 * dot(X, Y, c + d * math.cos(ang), c + d * math.sin(ang), sz * (1 - 0.3 * k_)), 0.7))
        a, heat = union_heat(parts)
        out.append(frame_color(a, heat, 9965 + i, GOLD))
    return out


PILLAR_W, PILLAR_H = 128, 512


def make_evolve_pillar() -> list[Image.Image]:
    """进化光柱：从地面升起的一道光。第 0 帧地上一团压扁的亮（光从地里冒出来），光柱只到三分之一；1–2 帧冲到顶，
    竖着的笔毛飞白，中心一线最亮，两边几缕细光丝往上飘；3–5 帧从下往上收细、变淡，光点往上飘。
    锚点在底边中点（光柱的根贴着地面）。叠加，自带金色 #FFE7A8，不染。"""
    w, h = PILLAR_W, PILLAR_H
    X, Y = grid(w, h)
    rng = np.random.default_rng(9971)
    tex = W.ptex(rng, ns=20, nt=1024, along=40.0, across=0.6)
    cx, gy = w / 2, float(h)
    dx = X - cx
    up = gy - Y  # 离地多高
    top = [170.0, 420.0, 500.0, 500.0, 500.0, 500.0]
    half = [17.0, 18.0, 17.0, 13.5, 9.5, 6.0]
    env = [1.0, 1.0, 0.95, 0.75, 0.5, 0.26]
    cut = [0.0, 0.0, 0.0, 50.0, 150.0, 270.0]  # 从下往上淡掉
    wisps = [(rng.choice([-1.0, 1.0]) * rng.uniform(12, 30), rng.uniform(60, 140), rng.uniform(0.7, 1.2), rng.uniform(0, 200)) for _ in range(8)]
    motes = [(rng.uniform(-36, 36), rng.uniform(0, 260), rng.uniform(1.0, 1.8)) for _ in range(22)]
    out = []
    for i in range(6):
        t = i / 5
        parts = []
        hw = half[i] * (1.0 - 0.3 * np.clip(up / 500.0, 0, 1))
        vert = smoothstep(top[i] + 6, top[i] - 50, up) * smoothstep(cut[i] - 30, cut[i] + 30, up) * (up >= 0)
        q = dx / np.maximum(hw, 1.0)
        body = np.exp(-(q**2) * 1.2) * vert
        m = dry(tex, np.clip(q / 1.6, -1, 1), up / 1024.0 + 0.05 * i, 0.08 + 0.25 * np.abs(np.clip(q, -1, 1)) + 0.35 * t)
        parts.append((env[i] * 0.85 * body * m, 0.6))
        core = smoothstep(2.6, 0.8, np.abs(dx)) * vert
        parts.append((env[i] * core * dry(tex, 0.0, up / 1024.0 + 0.3, 0.1 + 0.4 * t), 1.0))
        for xo, L, wd, y0 in wisps:
            yb = y0 + 160 * t
            c1 = smoothstep(yb - 4, yb + 10, up) * smoothstep(yb + L, yb + L - 30, up)
            parts.append((env[i] * 0.45 * np.exp(-(((dx - xo * (0.9 + 0.2 * t)) / wd) ** 2)) * c1 * (up < top[i]), 0.55))
        flare = [1.0, 0.8, 0.55, 0.35, 0.2, 0.1][i]  # 地上那一团：压扁的上半边，放射的细纹
        gq = np.hypot(dx / (34 + 10 * t), up / ((34 + 10 * t) * FLAT))
        spokes = np.clip(0.5 + V.angular_noise(np.random.default_rng(9972), np.arctan2(-up, dx), harmonics=(7, 11, 13, 17), amp=1.4), 0, 1)
        parts.append((flare * smoothstep(1.0, 0.25, gq) * (0.45 + 0.55 * spokes) * (up >= 0), 0.8))
        if i >= 1:
            for xo, y0, sz in motes:
                y = y0 + 260 * t * (0.6 + 0.4 * (sz - 1.0) / 0.8)
                if y > 490:
                    continue
                parts.append((0.85 * (1 - 0.6 * t) * dot(X, Y, cx + xo, gy - y, sz), 0.75))
        a, heat = union_heat(parts)
        out.append(frame_color(a, heat, 9975 + i, GOLD))
    return out


