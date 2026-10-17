def make_taiji() -> Image.Image:
    """水墨太极：焦墨半边带顺着圆周的飞白丝，白半边是宣纸色，外圈一笔圆相，边缘毛糙。正常混合。"""
    size, ss = 128, 4
    X, Y, r, tt = polar(size, ss)
    rng = np.random.default_rng(2700)
    c, R = size / 2.0, 52.0
    # 坐标轻微扭曲：手绘的 S 线
    wu = 0.010 * noise(rng, X.shape, 6 * ss) + 0.003 * noise(rng, X.shape, 1.5 * ss)
    wv = 0.010 * noise(rng, X.shape, 6 * ss) + 0.003 * noise(rng, X.shape, 1.5 * ss)
    u = (X - c) / R + wu
    v = (Y - c) / R + wv
    rho = np.hypot(u, v)
    Redge = 1.0 + 0.010 * sample1(pnoise1(rng, 512, 8.0), tt)
    disk = smoothstep(Redge + 0.012, Redge - 0.012, rho)
    soft = 1.2 / R

    def circ(cx, cy, rr):
        return smoothstep(rr + soft, rr - soft, np.hypot(u - cx, v - cy))

    c_top, c_bot = circ(0, -0.5, 0.5), circ(0, 0.5, 0.5)
    right = smoothstep(-soft, soft, u)
    black = np.clip(right * (1 - c_top) + c_bot * (1 - right), 0, 1)
    black = np.clip(black + circ(0, -0.5, 0.14) - circ(0, 0.5, 0.14), 0, 1)
    # 黑半边：顺着圆周扫的长笔毛丝，只在外缘偏干
    tex = ptex(rng, ns=48, nt=1024, along=36.0, across=0.5)
    b = sample_ptex(tex, np.clip(rho * 2 - 1, -1, 1), tt)
    dry = 0.30 * smoothstep(0.62, 0.99, rho)
    ink = smoothstep(dry - 0.06, dry + 0.06, b)
    blk_a = black * (0.62 + 0.38 * ink)
    blk_rgb = mixc(JIAO, NONG, 0.25 + 0.5 * (1 - ink))
    paper_rgb = mixc(PAPER, PAPER_SH, 0.3 * smoothstep(-1, 2, noise(rng, X.shape, 3 * ss)))
    # 外圈一笔：比太极略大，起笔在左上，收笔飞白
    t_rim = np.mod(tt - 0.62, 1.0)
    Rr = R * (1.035 + 0.008 * np.sin(2 * math.pi * t_rim))
    hw = np.interp(t_rim, [0, 0.04, 0.5, 0.88, 1.0], [1.6, 2.6, 2.2, 1.4, 0.3])
    rim_c = smoothstep(hw + 0.5, hw - 0.5, np.abs(r - Rr))
    rb = sample_ptex(tex, np.clip((r - Rr) / np.maximum(hw, 0.3), -1, 1), t_rim)
    rim_dry = 0.65 * smoothstep(0.7, 1.0, t_rim)
    rim = rim_c * smoothstep(rim_dry - 0.06, rim_dry + 0.06, rb)
    lay = V.Layer(*X.shape)
    lay.over(paper_rgb, disk)
    lay.over(blk_rgb, disk * blk_a)
    lay.over(mixc(JIAO, NONG, 0.2), rim)
    lay = lay.down(ss)
    rgb_s, a_s = lay.straight()
    a_s[0, :] = a_s[-1, :] = a_s[:, 0] = a_s[:, -1] = 0
    return V.to_rgba8(rgb_s, a_s)


def make_seal_mark() -> Image.Image:
    """朱砂印迹：方印、白文（字口不着印泥，透出地面），印泥不匀、四边有崩口。正常混合。"""
    size, ss = 64, 4
    X, Y = V.grid(size, size, ss)
    rng = np.random.default_rng(3200)
    c = size / 2.0
    ang = math.radians(-4.0)
    u = (X - c) * math.cos(ang) + (Y - c) * math.sin(ang)
    v = -(X - c) * math.sin(ang) + (Y - c) * math.cos(ang)
    half = 25.0
    sq = (np.abs(u) ** 10 + np.abs(v) ** 10) ** 0.1 - half  # 带一点圆角的方
    sq = sq + 0.5 * noise(rng, X.shape, 2.5 * ss) + 0.22 * noise(rng, X.shape, 0.7 * ss)
    # 崩口：边上几处缺一小块
    for _ in range(5):
        side = rng.integers(4)
        pos = rng.uniform(-0.8, 0.8) * half
        px, py = [(pos, -half), (half, pos), (pos, half), (-half, pos)][side]
        rr = rng.uniform(1.2, 2.6)
        sq = np.maximum(sq, rr - np.hypot(u - px, v - py) + 0.3 * noise(rng, X.shape, 0.8 * ss))
    cover = smoothstep(0.45, -0.45, sq)
    # 白文：字口不着色。字也带一点刀味（边上轻微起伏）
    gd = np.full(X.shape, 1e3)
    for stroke in SHAN_GLYPH:
        pts = V.arc_resample(np.array([(half * 1.02 * x, half * 1.02 * y) for x, y in stroke]), 120)
        gd = np.minimum(gd, polyline_dist(u, v, pts))
    gw = 2.9 + 0.3 * noise(rng, X.shape, 1.5 * ss)
    glyph = smoothstep(gw - 0.45, gw + 0.45, gd)  # 1 = 着色
    # 印泥不匀：大块浓淡 + 成簇的麻点 + 一角压得轻
    blot = 0.5 + 0.5 * noise(rng, X.shape, 4.0 * ss)
    speck = rank01(noise(rng, X.shape, 0.6 * ss) + 0.8 * (blot - 0.5))
    light_corner = smoothstep(0.0, 1.0, ((u + v) / (2 * half) + 0.2 * noise(rng, X.shape, 3 * ss)) * 1.6 - 0.5)
    dens = 0.95 - 0.12 * blot - 0.5 * smoothstep(0.9, 0.975, speck) - 0.3 * light_corner * smoothstep(0.6, 0.9, speck)
    a = np.clip(cover * glyph * dens, 0, 1)
    # 颜色：印泥积在边上偏深，薄处偏淡
    edge = np.exp(np.minimum(sq, 0) / 1.6) + np.exp(-np.abs(gd - gw) / 1.2) * 0.6
    rgb = mixc(ZHUSHA, mixc(ZHUSHA, JIAO, 0.3), np.clip(0.55 * edge + 0.25 * (1 - blot), 0, 1))
    rgb = mixc(rgb, mixc(ZHUSHA, PAPER, 0.25), 0.4 * light_corner * (1 - edge * 0.5))
    lay = V.Layer(*X.shape)
    lay.over(rgb, a)
    lay = lay.down(ss)
    rgb_s, a_s = lay.straight()
    a_s[0, :] = a_s[-1, :] = a_s[:, 0] = a_s[:, -1] = 0
    return V.to_rgba8(rgb_s, a_s)


def make_crack() -> Image.Image:
    """地裂：中心砸出的焦墨坑，向外放射七道折线裂缝（之字形、根部粗、尖上带飞白），少量分叉和环向短裂，
    坑外一圈干笔擦出的震痕，底下一片很淡的晕染压暗地面。按 30° 俯角压扁。正常混合（游戏里淡出）。"""
    W, H, ss = 128, 96, 4
    X, Y = V.grid(H, W, ss)
    rng = np.random.default_rng(3300)
    cx, cy, sy = 64.0, 48.5, 0.68
    U, Vv = X - cx, (Y - cy) / sy  # 圆形空间
    lines: list[tuple[np.ndarray, float]] = []

    def grow(p0, heading, length, w0, depth):
        pts = [np.asarray(p0, dtype=np.float64)]
        L = 0.0
        while L < length:
            step = rng.uniform(3.5, 7.0)
            heading += rng.normal(0, 0.10)  # 主方向慢慢偏
            a = heading + rng.normal(0, 0.42)  # 每一段围着主方向左右折
            pts.append(pts[-1] + step * np.array([math.cos(a), math.sin(a)]))
            L += step
        pts_a = np.array(pts)
        lines.append((pts_a, w0))
        n_br = {0: rng.integers(1, 3), 1: rng.integers(0, 2)}.get(depth, 0)
        for _ in range(n_br):
            if len(pts_a) < 4:
                break
            i = int(rng.uniform(0.3, 0.7) * (len(pts_a) - 1))
            frac = i / (len(pts_a) - 1)
            grow(pts_a[i], heading + rng.choice([-1, 1]) * rng.uniform(0.5, 0.95), length * (1 - frac) * rng.uniform(0.35, 0.6), w0 * (1 - frac) * 0.6 + 0.3, depth + 1)

    n_main = 7
    for i in range(n_main):
        hd = 2 * math.pi * (i + rng.uniform(-0.3, 0.3)) / n_main + 0.3
        grow(np.array([math.cos(hd), math.sin(hd)]) * 4.0, hd, rng.uniform(36, 54), rng.uniform(2.6, 3.4), 0)
    # 环向短裂（像碎成几块的地皮）
    for _ in range(3):
        rr = rng.uniform(14, 24)
        a0 = rng.uniform(0, 2 * math.pi)
        aa = np.linspace(a0, a0 + rng.uniform(0.5, 0.85), 6)
        rad = rr + rng.normal(0, 1.0, 6)
        lines.append((np.stack([rad * np.cos(aa), rad * np.sin(aa)], -1), 1.2))
    core = np.zeros(X.shape)
    lip = np.zeros(X.shape)
    for pts, w0 in lines:
        img_pts = np.stack([cx + pts[:, 0], cy + pts[:, 1] * sy], -1)
        n = max(int(np.hypot(*np.diff(img_pts, axis=0).T).sum() / 0.4), 8)
        dense = V.arc_resample(img_pts, n)
        tt = np.linspace(0, 1, n)
        hw = 0.5 * (w0 * (1 - tt) ** 0.85 + 0.25)
        cov, f = V.brush_stroke(X, Y, dense, hw, rng, dry=0.5, dry_start=0.55, edge_jitter=0.2, ss=ss)
        dist = np.hypot(f["perp"], f["over"])
        core = np.maximum(core, cov)
        lip = np.maximum(lip, smoothstep(f["hw"] + 0.9, f["hw"] + 0.3, dist))
    core = np.clip(core, 0, 1)
    rho = np.hypot(U, Vv)
    th = np.arctan2(Vv, U)
    # 中心坑：星形的黑洞
    pit_r = 5.0 * (1 + V.angular_noise(rng, th, harmonics=(3, 4, 5, 7), amp=0.22))
    pit = smoothstep(pit_r + 0.5, pit_r - 0.5, rho)
    # 震痕：坑外一圈干笔擦痕
    ring_tex = ptex(rng, ns=10, nt=512, along=8.0, across=0.6)
    rb = sample_ptex(ring_tex, np.clip((rho - 10.5) / 3.0, -1, 1), np.mod(th / (2 * math.pi), 1.0))
    scuff = 0.28 * smoothstep(3.2, 1.2, np.abs(rho - 10.5)) * smoothstep(0.45, 0.75, rb)
    # 碎石屑
    debris = np.zeros(X.shape)
    for _ in range(8):
        a0 = rng.uniform(0, 2 * math.pi)
        d0 = rng.uniform(7, 20)
        px, py = d0 * math.cos(a0), d0 * math.sin(a0)
        rr = rng.uniform(0.6, 1.2)
        pr = rr * (1 + V.angular_noise(rng, np.arctan2(Vv - py, U - px), harmonics=(2, 3), amp=0.3))
        debris = np.maximum(debris, smoothstep(pr + 0.3, pr - 0.3, np.hypot(U - px, Vv - py)))
    # 压暗的晕
    wash_r = 42.0 * (1 + V.angular_noise(rng, th, harmonics=(2, 3, 4, 5), amp=0.12))
    wash = 0.14 * smoothstep(wash_r, wash_r * 0.4, rho) * (0.75 + 0.25 * noise(rng, X.shape, 4 * ss))
    lay = V.Layer(*X.shape)
    lay.over(ZHONG, wash)
    lay.over(DAN, scuff)
    lay.over(DAN, 0.45 * lip)
    lay.over(JIAO, 0.96 * np.maximum(core, pit))
    lay.over(NONG, 0.9 * debris)
    lay = lay.down(ss)
    rgb_s, a_s = lay.straight()
    a_s[0, :] = a_s[-1, :] = a_s[:, 0] = a_s[:, -1] = 0
    return V.to_rgba8(rgb_s, a_s)
