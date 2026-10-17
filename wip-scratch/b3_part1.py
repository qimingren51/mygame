# ============================================================== 第三批：十种五行反应（都不染，按主色画）
# 尺寸按 BALANCE 7.2 的反应范围在 1080p 下约一比一定（1 世界单位 ≈ 2.57 像素），radius_px 是效果的横向半径，
# 游戏按反应范围缩放；地面的已按透视压扁（flat 0.62）。


class Paint:
    """普通混合的上色层（超采样网格上预乘 alpha 叠画），最后缩小、抖动成 RGBA 帧。"""

    def __init__(self, X, Y):
        self.X, self.Y = X, Y
        self.xs, self.ys = X[0], Y[:, 0]
        self.p = np.zeros(X.shape + (3,))
        self.a = np.zeros(X.shape)

    def window(self, x0, y0, x1, y1):
        r0, r1 = np.searchsorted(self.ys, y0), np.searchsorted(self.ys, y1)
        c0, c1 = np.searchsorted(self.xs, x0), np.searchsorted(self.xs, x1)
        return slice(int(r0), int(r1)), slice(int(c0), int(c1))

    def over(self, sl, rgb, alpha) -> None:
        """在上面盖一层：rgb 是颜色（0..1，单色或逐像素），alpha 是覆盖度。"""
        al = np.clip(alpha, 0, 1)
        col = np.broadcast_to(np.asarray(rgb, dtype=np.float64), al.shape + (3,))
        self.p[sl] = col * al[..., None] + self.p[sl] * (1 - al[..., None])
        self.a[sl] = al + self.a[sl] * (1 - al)

    def image(self, seed: int) -> Image.Image:
        a = V.downsample(self.a, SS)
        p = V.downsample(self.p, SS)
        rgb = p / np.maximum(a, 1e-6)[..., None]
        a8 = V.dither_alpha(np.clip(a, 0, 1), np.random.default_rng(seed))
        a8[a < 0.004] = 0
        a8[0, :] = a8[-1, :] = a8[:, 0] = a8[:, -1] = 0
        return V.to_rgba8(np.clip(rgb, 0, 1), None, a8)


def lerp_col(t, palette):
    """按 t（0..1，可以是场）在调色板 [(t, "#hex"), …] 里插值出颜色。"""
    xs = [q for q, _ in palette]
    cols = np.array([V.col(c) for _, c in palette])
    t = np.clip(np.asarray(t, dtype=np.float64), 0, 1)
    return np.stack([np.interp(t, xs, cols[:, k]) for k in range(3)], -1)


def jag_path(rng, p0, ang, length, n=14, jitter=0.35, bend=0.0):
    """裂缝 / 闪电似的折线：从 p0 朝 ang 走 length，每一段方向抖一下。"""
    pts = [np.array(p0, dtype=np.float64)]
    a = ang
    for _ in range(n):
        a += rng.uniform(-jitter, jitter) + bend
        pts.append(pts[-1] + length / n * np.array([math.cos(a), math.sin(a)]))
    return np.array(pts)


def polyline_dist(X, Y, pts):
    """到折线的距离和沿线参数（0..1）。"""
    best = np.full(X.shape, 1e9)
    tpar = np.zeros(X.shape)
    seglen = np.hypot(*np.diff(pts, axis=0).T)
    cum = np.concatenate([[0.0], np.cumsum(seglen)])
    total = max(cum[-1], 1e-6)
    for k in range(len(pts) - 1):
        d, u = seg(X, Y, *pts[k], *pts[k + 1])
        better = d < best
        best = np.where(better, d, best)
        tpar = np.where(better, (cum[k] + u * seglen[k]) / total, tpar)
    return best, tpar


REACT_FIRE = [(0.0, "#B8321C"), (0.45, "#FF7A2A"), (0.8, "#FFC27A"), (1.0, "#FFF1C2")]


def make_react_liaoyuan() -> list[Image.Image]:
    """燎原：一团火炸开，三条火舌朝三个方向窜出去（120° 散开、带一点弯，像去点着旁边的妖物），舌尖各爆一小团火；
    火星顺着火舌飞，末两帧火舌变细、断成一截截往上飘。叠加，主色 #FF7A2A，不染；radius_px 是火舌够到的半径。"""
    size = 352
    c = size / 2
    R = 150.0
    rng = np.random.default_rng(9901)
    tongues = []
    for k in range(3):
        ang = math.radians(-90 + 120 * k + rng.uniform(-14, 14))
        tongues.append(dict(ang=ang, curl=float(rng.choice([-1.0, 1.0])) * rng.uniform(0.25, 0.45), seed=int(rng.integers(1 << 30))))
    licks = [(2 * math.pi * (k + rng.uniform(-0.3, 0.3)) / 12, rng.uniform(0.8, 1.2), int(rng.integers(1 << 30))) for k in range(12)]
    embers = [(int(rng.integers(0, 3)), rng.uniform(0.2, 1.0), rng.uniform(-8, 8), rng.uniform(1.0, 1.6)) for _ in range(15)]
    reach = [0.22, 0.6, 0.9, 1.0, 1.0, 0.96]
    width = [11.0, 15.0, 14.0, 11.0, 7.0, 4.0]
    core_r = [20.0, 30.0, 34.0, 30.0, 22.0, 12.0]
    env = [1.0, 1.0, 1.0, 0.85, 0.6, 0.32]
    out = []
    for i in range(6):
        X, Y = grid(size, size)
        acc = Acc(X, Y)
        full = (slice(None), slice(None))
        r = np.hypot(X - c, Y - c)
        th = np.arctan2(Y - c, X - c)
        spokes = np.clip(0.55 + V.angular_noise(np.random.default_rng(9902), th, harmonics=(7, 11, 13, 17), amp=1.3), 0, 1)
        acc.add(full, env[i] * np.exp(-((r / core_r[i]) ** 2)) * (0.6 + 0.4 * spokes), 1.0 - 0.12 * i)
        for ang, lf, sd in licks:  # 火团边上一圈短火苗，尖往上翘
            L = core_r[i] * 1.5 * lf
            u = np.array([math.cos(ang), math.sin(ang)])
            b = np.array([c, c]) + u * core_r[i] * 0.4
            tip = np.array([c, c]) + u * L + np.array([0.0, -0.3 * L])
            pts = V.bezier([b, (b + tip) / 2 + u * 3, tip], 30)
            tt = np.linspace(0, 1, len(pts))
            hw = 5.0 * (1 - tt) ** 0.7 + 0.2
            sl = acc.window(min(b[0], tip[0]) - 12, min(b[1], tip[1]) - 12, max(b[0], tip[0]) + 12, max(b[1], tip[1]) + 12)
            cov, f_ = V.brush_stroke(X[sl], Y[sl], pts, hw, np.random.default_rng(sd + i // 2), dry=0.3, dry_start=0.5, ss=SS)
            acc.add(sl, env[i] * 0.9 * cov, np.clip(0.9 - 0.7 * f_["t"] - 0.1 * i, 0, 1))
        for tg in tongues:  # 三条大火舌
            L = R * reach[i]
            u = np.array([math.cos(tg["ang"]), math.sin(tg["ang"])])
            nrm = np.array([-u[1], u[0]]) * tg["curl"]
            b = np.array([c, c]) + u * 10
            pts = V.bezier([b, b + u * L * 0.4 + nrm * L * 0.25, b + u * L * 0.8 + nrm * L * 0.2, b + u * L], 80)
            tt = np.linspace(0, 1, len(pts))
            hw = width[i] * (0.55 + 0.45 * np.sin(np.pi * np.clip(tt * 1.6, 0, 1))) * (1 - 0.75 * tt) + 0.3
            lo, hi = pts.min(0) - 24, pts.max(0) + 24
            sl = acc.window(lo[0], lo[1], hi[0], hi[1])
            cov, f_ = V.brush_stroke(X[sl], Y[sl], pts, hw, np.random.default_rng(tg["seed"] + i // 2), dry=0.3 + 0.1 * i,
                                     dry_start=0.4, ss=SS)
            if i >= 4:  # 断成一截截
                cut = 0.5 + 0.5 * np.sin(f_["t"] * 22 + tg["seed"] % 7)
                cov = cov * smoothstep(0.25, 0.55, cut)
            acc.add(sl, env[i] * cov, np.clip(0.95 - 0.75 * f_["t"] - 0.08 * i, 0, 1))
            if i >= 2:  # 舌尖爆一小团火
                tip = pts[-1]
                k_ = [0, 0, 0.7, 1.0, 0.7, 0.35][i]
                sl = acc.window(tip[0] - 26, tip[1] - 30, tip[0] + 26, tip[1] + 20)
                rr = np.hypot(X[sl] - tip[0], (Y[sl] - tip[1]) * 1.2)
                acc.add(sl, k_ * np.exp(-((rr / 11.0) ** 2)) * (0.6 + 0.4 * dry(W.ptex(np.random.default_rng(9903), 12, 256, 8.0, 0.8),
                                                                                  0.0, np.arctan2(Y[sl] - tip[1], X[sl] - tip[0]) / 6.3, 0.2)), 0.8)
        for k, tpos, off, sz in embers:  # 火星顺着火舌飞
            if i == 0:
                continue
            tg = tongues[k]
            u = np.array([math.cos(tg["ang"]), math.sin(tg["ang"])])
            p = np.array([c, c]) + u * R * min(1.0, tpos * reach[i] + 0.1 * i) + np.array([-u[1], u[0]]) * off - np.array([0, 4.0 * i])
            sl = acc.window(p[0] - 6, p[1] - 6, p[0] + 6, p[1] + 10)
            acc.add(sl, 0.85 * (1 - i / 7) * streak(X[sl], Y[sl], p[0] - u[0] * 6, p[1] - u[1] * 6, p[0], p[1], sz), 0.7)
        out.append(frame_color(acc.a, acc.heat(), 9905 + i, REACT_FIRE))
    return out


GROUND_W, GROUND_H = 384, 240  # 地面反应的画布（清单的尺寸）；中心是锚点


def make_react_rongyan() -> list[Image.Image]:
    """赤地：地面从中心爆开，一圈发红的裂缝往外裂（九道主缝、每道分一两个叉，折线、越往外越细），裂缝里透出熔岩的光，
    缝边一圈暗红的余热；正中先一闪，冲出一圈热浪；末两帧光往回收、缝里只剩暗红。已压扁，叠加，主色 #FF5A2A，不染。"""
    w, h = GROUND_W, GROUND_H
    cx, cy = w / 2, h / 2
    R = 150.0
    rng = np.random.default_rng(9911)
    cracks = []
    for k in range(9):
        ang = 2 * math.pi * (k + rng.uniform(-0.25, 0.25)) / 9
        main = jag_path(rng, (0.0, 0.0), ang, R * rng.uniform(0.8, 1.0), n=12, jitter=0.32)
        cracks.append((main, 1.0))
        for _ in range(int(rng.integers(1, 3))):
            j = int(rng.integers(3, 9))
            sub = jag_path(rng, main[j], ang + rng.choice([-1, 1]) * rng.uniform(0.5, 0.9), R * rng.uniform(0.25, 0.4), n=6, jitter=0.4)
            cracks.append((sub, j / 12))
    grow = [0.18, 0.55, 0.9, 1.0, 1.0, 1.0]
    glow = [1.0, 1.0, 1.0, 0.9, 0.6, 0.3]
    heat_k = [1.0, 0.95, 0.85, 0.7, 0.45, 0.25]
    out = []
    for i in range(6):
        X, Y = grid(w, h)
        acc = Acc(X, Y)
        full = (slice(None), slice(None))
        gx, gy = X - cx, (Y - cy) / FLAT
        r = np.hypot(gx, gy)
        if i <= 2:  # 正中一闪 + 热浪
            acc.add(full, [1.0, 0.7, 0.35][i] * np.exp(-((r / [16.0, 24.0, 30.0][i]) ** 2)), 1.0)
            ring = np.exp(-(((r - R * [0.15, 0.55, 0.95][i]) / 6.0) ** 2))
            acc.add(full, [0.5, 0.45, 0.25][i] * ring, 0.7)
        for pts, start in cracks:
            vis = np.clip((grow[i] - start) / max(1 - start, 1e-3), 0, 1) if start > 0 else grow[i]
            if vis <= 0:
                continue
            m = max(2, int(round(len(pts) * vis)))
            sp = pts[:m] * np.array([1.0, FLAT]) + np.array([cx, cy])
            lo, hi = sp.min(0) - 14, sp.max(0) + 14
            sl = acc.window(lo[0], lo[1], hi[0], hi[1])
            d, tpar = polyline_dist(X[sl], Y[sl], sp)
            wid = 2.4 * (1 - 0.6 * tpar) * (1.0 if start == 0 else 0.7) + 0.4
            line = smoothstep(wid + 0.5, wid - 0.5, d)
            halo = np.exp(-((d / (6.0 + 3 * (i >= 3))) ** 2))
            acc.add(sl, glow[i] * np.clip(line + 0.35 * halo, 0, 1), np.clip(heat_k[i] * (0.95 - 0.4 * tpar) * (0.7 + 0.3 * line), 0, 1))
        out.append(frame_color(acc.a, acc.heat(), 9915 + i, [(0.0, "#8E2414"), (0.4, "#FF5A2A"), (0.75, "#FFB070"), (1.0, "#FFF0D0")]))
    return out


def make_react_zhubing() -> list[Image.Image]:
    """铸兵：中心一闪，三片金刃（剑形：刃口一道亮线、中脊一道、尖朝外）从中心闪出去、往外飞，带一点转；
    末两帧飞远、变淡，身后拖细光。叠加，主色 #F2D98A，不染（金刃本身另有投射物，这是出手那一下）。"""
    size = 256
    c = size / 2
    rng = np.random.default_rng(9921)
    blades = [math.radians(-90 + 120 * k + rng.uniform(-6, 6)) for k in range(3)]
    L = [26.0, 64.0, 86.0, 90.0, 88.0]
    off = [6.0, 12.0, 20.0, 34.0, 52.0]
    env = [0.9, 1.0, 1.0, 0.75, 0.4]
    spin = [0.0, 0.05, 0.1, 0.16, 0.22]
    out = []
    for i in range(5):
        X, Y = grid(size, size)
        acc = Acc(X, Y)
        full = (slice(None), slice(None))
        r = np.hypot(X - c, Y - c)
        if i <= 1:
            for k in range(4):
                cv, _ = needle(X, Y, c, c, k * math.pi / 2 + math.pi / 4, [34.0, 22.0][i], [3.0, 2.2][i], taper=1.5)
                acc.add(full, [1.0, 0.7][i] * cv, 1.0)
            acc.add(full, [1.0, 0.6][i] * np.exp(-((r / [8.0, 6.0][i]) ** 2)), 1.0)
        for ang0 in blades:
            ang = ang0 + spin[i]
            u = np.array([math.cos(ang), math.sin(ang)])
            base = np.array([c, c]) + u * off[i]
            tip = base + u * L[i]
            lo, hi = np.minimum(base, tip) - 12, np.maximum(base, tip) + 12
            sl = acc.window(lo[0], lo[1], hi[0], hi[1])
            cov, dd, along = almond_field(X[sl], Y[sl], base, tip, 11.0, bulge=0.3)
            vperp = -(X[sl] - base[0]) * u[1] + (Y[sl] - base[1]) * u[0]
            edge = smoothstep(1.4, 0.2, np.abs(dd)) * (vperp > 0)  # 一侧刃口亮
            ridge = smoothstep(0.9, 0.2, np.abs(vperp)) * (along < 0.95)
            acc.add(sl, env[i] * np.clip(0.4 * cov + 0.9 * edge + 0.6 * ridge * cov, 0, 1), np.clip(0.55 + 0.45 * along, 0, 1))
            if i >= 2:  # 身后拖的细光
                t0 = base - u * (12 + 10 * i)
                sl2 = acc.window(min(t0[0], base[0]) - 6, min(t0[1], base[1]) - 6, max(t0[0], base[0]) + 6, max(t0[1], base[1]) + 6)
                acc.add(sl2, 0.5 * env[i] * streak(X[sl2], Y[sl2], t0[0], t0[1], base[0], base[1], 2.2), 0.6)
        out.append(frame_color(acc.a, acc.heat(), 9925 + i, [(0.0, "#B88A3A"), (0.5, "#F2D98A"), (1.0, "#FFF8E0")]))
    return out


def make_react_ningshuang() -> list[Image.Image]:
    """凝霜：地上一朵霜花：六道主枝从中心往外长（每道两侧一排斜的冰晶小枝，越往外越短），主枝之间六片淡的瓣，
    边上一圈细霜针；正中先一闪。0–3 帧往外长，4–5 帧留着、变淡。已压扁，叠加，主色 #CDEBFF，不染。"""
    w, h = GROUND_W, GROUND_H
    cx, cy = w / 2, h / 2
    R = 150.0
    rng = np.random.default_rng(9931)
    grow = [0.2, 0.5, 0.8, 1.0, 1.0, 1.0]
    env = [1.0, 1.0, 0.95, 0.9, 0.6, 0.3]
    out = []
    for i in range(6):
        X, Y = grid(w, h)
        acc = Acc(X, Y)
        full = (slice(None), slice(None))
        gx, gy = (X - cx), (Y - cy) / FLAT
        r = np.hypot(gx, gy)
        th = np.arctan2(gy, gx)
        if i <= 1:
            acc.add(full, [1.0, 0.6][i] * np.exp(-((r / [14.0, 20.0][i]) ** 2)), 1.0)
        L = R * grow[i]
        for k in range(6):
            ang = math.radians(30 + 60 * k)
            u = np.array([math.cos(ang), math.sin(ang)])
            # 主枝（地面坐标里画，再压扁）：用 gx, gy 直接算
            d, uu = seg(gx, gy, 0.0, 0.0, u[0] * L, u[1] * L)
            hw = 2.2 * (1 - 0.6 * uu) + 0.4
            acc.add(full, env[i] * smoothstep(hw + 0.6, hw - 0.6, d), 0.9 - 0.3 * uu)
            for j in range(1, 7):  # 两侧斜的小枝
                t = j / 7
                if t * R > L:
                    continue
                p = u * t * L
                bl = (1 - t) * 0.35 * R * min(1.0, (L - t * R) / (0.2 * R) + 0.3)
                for sgn in (-1, 1):
                    a2 = ang + sgn * math.radians(60)
                    q = p + bl * np.array([math.cos(a2), math.sin(a2)])
                    d2, u2 = seg(gx, gy, p[0], p[1], q[0], q[1])
                    acc.add(full, 0.8 * env[i] * smoothstep(1.6, 0.4, d2) * (1 - 0.5 * u2), 0.7)
            # 瓣：主枝之间一片淡的杏仁形
            a3 = ang + math.radians(30)
            v = np.array([math.cos(a3), math.sin(a3)])
            cov, dd, _ = almond_field(gx, gy, v * 8, v * L * 0.62, 0.3 * L * 0.62 + 1, bulge=0.45)
            acc.add(full, env[i] * (0.18 * cov + 0.45 * smoothstep(1.2, 0.0, np.abs(dd)) * (dd < 0.5)), 0.5)
        if i >= 2:  # 外沿一圈细霜针
            needles = np.clip(np.cos(th * 36) ** 16, 0, 1) * np.exp(-(((r - L * 0.95) / 6.0) ** 2))
            acc.add(full, 0.5 * env[i] * needles, 0.6)
        out.append(frame_color(acc.a, acc.heat(), 9935 + i, [(0.0, "#7FB8E8"), (0.6, "#CDEBFF"), (1.0, "#FFFFFF")]))
    return out


