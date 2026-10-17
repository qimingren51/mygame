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
    head = [0.36, 0.84, 1.0, 1.0, 1.0, 1.0]
    tail = [0.0, 0.0, 0.0, 0.3, 0.56, 0.8]
    thick = [56.0, 88.0, 100.0, 82.0, 58.0, 34.0]
    env = [0.95, 1.0, 1.0, 0.8, 0.52, 0.26]
    dryk = [0.06, 0.04, 0.08, 0.26, 0.42, 0.56]
    sheen = [0.1, 0.2, 0.22, 0.12, 0.05, 0.0]  # 扇面的风痕
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
            full = (slice(None), slice(None))
            dx, dy = X - cx, Y - cy
            r = np.hypot(dx, dy)
            gd = np.degrees(np.arctan2(dy, dx)) + half  # 沿弧的角度：0（起笔，上）→ 120（收笔，下）
            g = gd / arc
            c, vc = crescent(r, gd, head=hd * arc, tail=tl * arc, rim=R, thick=thick[i], tex=tex, t_off=0.11 * i, dryk=dryk[i], edge_w=2.6)
            acc.add(full, env[i] * c)
            for rf, a0, ln, wd in lines:  # 速度线：弧里细的、跟在笔锋后面
                g0 = tl + span * a0
                g1 = min(g0 + span * ln, hd - 0.04)
                if g1 - g0 < 0.03:
                    continue
                uu = np.clip((g - g0) / (g1 - g0), 0, 1)
                on = (g > g0) & (g < g1)
                prof = np.exp(-(((r - R * rf) / wd) ** 2))
                acc.add(full, 0.38 * env[i] * on * prof * np.sin(np.pi * uu) ** 0.7
                        * dry(tex, np.clip((r - R * rf) / (3 * wd), -1, 1), g * 0.85 + rf, 0.25 + 0.3 * (1 - uu)))
            if sheen[i] > 0:  # 扇面上一层淡的风痕：笔锋身后最浓，往尾巴、往弧心淡
                v = (g - tl) / span
                vv = np.clip(v, 0, 1)
                wv = smoothstep(0.0, 0.55, vv) * smoothstep(1.0, 0.9, vv) * (v > 0) * (v < 1)
                wr = smoothstep(0.22 * R, 0.9 * R, r) * smoothstep(R + 1.0, R - 5.0, r)
                st = dry(tex, np.clip(2 * r / R - 1, -1, 1), g * 0.3 + 0.5, 0.35 + 0.3 * (1 - vv))
                acc.add(full, sheen[i] * wv * wr * (0.35 + 0.65 * st))
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
                rad = R - 22 + [0.0, 8.0, 18.0, 30.0, 44.0][age]
                px, py = cx + rad * math.cos(ang), cy + rad * math.sin(ang)
                rc = 10.5 * (1 + 0.04 * age)
                sl = acc.window(px - rc - 4, py - rc - 4, px + rc + 4, py + rc + 4)
                sq = max(0.15, abs(math.cos(ph + spin * age * 0.5)))
                acc.add(sl, coin_age[age] * coin_glyph(X[sl], Y[sl], px, py, rc, sq, ang + ph))
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
    spin = [0.0, 62.0, 118.0, 166.0, 204.0, 232.0]  # 转过的角度（越转越慢）
    grow = [0.6, 0.9, 1.0, 1.0, 1.0, 1.0]
    length = [70.0, 150.0, 178.0, 178.0, 150.0, 108.0]
    thick = [24.0 * q, 38.0 * q, 42.0 * q, 36.0 * q, 26.0 * q, 15.0 * q]
    env = [0.9, 1.0, 1.0, 0.8, 0.52, 0.26]
    dryk = [0.06, 0.04, 0.08, 0.24, 0.4, 0.55]
    vortex = [0.0, 0.1, 0.12, 0.07, 0.03, 0.0]  # 圈里的旋涡风痕
    blades = [(a0 + rng.uniform(-6, 6), rf, br, off) for a0, rf, br, off in
              ((0.0, 1.0, 1.0, 0.0), (120.0, 1.0, 1.0, 0.31), (240.0, 1.0, 1.0, 0.62), (60.0, 0.72, 0.55, 0.15), (180.0, 0.72, 0.55, 0.47), (300.0, 0.72, 0.55, 0.78))]
    lines = [(rng.uniform(0.42, 0.9), rng.uniform(0, 360), rng.uniform(40, 100), rng.uniform(1.4, 2.8)) for _ in range(15)]
    sparks = [(int(rng.integers(0, 3)), rng.uniform(-6, 6), rng.uniform(24, 40), rng.uniform(1.6, 2.4), rng.uniform(0.2, 0.45)) for _ in range(14)]
    coins = [(rng.uniform(0, math.pi), rng.uniform(1.4, 2.2)) for _ in range(3)]
    coin_env = [0.0, 0.9, 0.95, 0.75, 0.45, 0.2]
    out = []
    for i in range(6):

        def paint(acc, i=i):
            X, Y = acc.X, acc.Y
            full = (slice(None), slice(None))
            dx, dy = X - cx, Y - cy
            r = np.hypot(dx, dy)
            th = np.degrees(np.arctan2(dy, dx))  # −180..180，顺时针为正
            for a0, rf, br, off in blades:
                hd = a0 + spin[i]
                L = length[i] * (1.0 if rf == 1.0 else 0.8)
                g = hd - np.mod(hd - th, 360.0)  # 把像素的角度展开到 (hd − 360, hd]，笔锋在 hd，尾巴在 hd − L
                rim_r = R * grow[i] * rf
                c, _ = crescent(r, g, head=hd, tail=hd - L, rim=lambda v, rr=rim_r: rr * (0.86 + 0.14 * v), thick=thick[i] * rf,
                                tex=tex, t_off=off, dryk=dryk[i], edge_w=2.8)
                acc.add(full, env[i] * br * c)
                if i <= 2 and rf == 1.0:  # 笔锋的亮点
                    ha = math.radians(hd)
                    hx, hy = cx + (rim_r - 10) * math.cos(ha), cy + (rim_r - 10) * math.sin(ha)
                    sl = acc.window(hx - 30, hy - 30, hx + 30, hy + 30)
                    acc.add(sl, 0.85 * env[i] * np.exp(-((np.hypot(X[sl] - hx, Y[sl] - hy) / 9.0) ** 2)))
            for rf, a0, ln, wd in lines:  # 速度线：跟着转
                hd = a0 + spin[i] * 0.9
                g = hd - np.mod(hd - th, 360.0)
                uu = np.clip((g - (hd - ln)) / ln, 0, 1)
                rr = R * grow[i] * rf
                prof = np.exp(-(((r - rr) / wd) ** 2))
                acc.add(full, 0.32 * env[i] * prof * np.sin(np.pi * uu) ** 0.7 * dry(tex, np.clip((r - rr) / (3 * wd), -1, 1), g / 360.0 + rf, 0.3 + 0.3 * (1 - uu)))
            if vortex[i] > 0:  # 圈里淡淡的旋涡风痕（螺旋的笔毛纹），让人看得出整圈都在砍
                t_sp = (th - spin[i] * 0.8) / 360.0 + 0.18 * r / R
                wr = smoothstep(0.3 * R, 0.85 * R, r) * smoothstep(R * grow[i] + 2, R * grow[i] - 8, r)
                acc.add(full, vortex[i] * wr * (0.3 + 0.7 * dry(tex, np.clip(2 * r / R - 1, -1, 1), t_sp + 0.37, 0.45)))
            for k, (ph, sp) in enumerate(coins):  # 主刀光笔锋上的铜钱影子：跟着转，第 3 帧起甩出去、翻着变淡
                if coin_env[i] <= 0:
                    continue
                a0 = blades[k][0]
                if i <= 3:
                    ang = math.radians(a0 + spin[i] - 9.0)
                    rad = R * grow[i] - 26
                else:
                    ang = math.radians(a0 + spin[3] - 9.0 + [0, 0, 0, 0, 16.0, 26.0][i])
                    rad = R - 26 + [0, 0, 0, 0, 22.0, 40.0][i]
                px, py = cx + rad * math.cos(ang), cy + rad * math.sin(ang)
                rc = 12.0
                sl = acc.window(px - rc - 4, py - rc - 4, px + rc + 4, py + rc + 4)
                sq = max(0.15, abs(math.cos(ph + sp * i * 0.5)))
                acc.add(sl, coin_env[i] * coin_glyph(X[sl], Y[sl], px, py, rc, sq, ang + ph))
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


