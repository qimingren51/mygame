

def smooth_stroke(X, Y, pts, hw, aa=0.45):
    """实心笔触（填色用，不带飞白）：返回覆盖度和 stroke_fields 的场。"""
    f = V.stroke_fields(X, Y, pts, np.asarray(hw, dtype=np.float64))
    return smoothstep(f["hw"] + aa, f["hw"] - aa, np.hypot(f["perp"], f["over"])), f


def curl_blade(root, ang0, L, bend, curl, curl_len, n=90):
    """卷草的中线：从 root 朝 ang0 出发走 L，整体弯 bend（弧度）；最后 curl_len 像素越卷越紧，一共再转 curl（弧度，正 = 顺时针）。"""
    s = np.linspace(0.0, L, n)
    k = np.clip((s - (L - curl_len)) / max(curl_len, 1e-6), 0, 1)
    theta = ang0 + bend * s / max(L, 1e-6) + curl * k**1.7
    steps = np.stack([np.cos(theta), np.sin(theta)], -1) * (L / (n - 1))
    return np.asarray(root, dtype=np.float64) + np.concatenate([[[0.0, 0.0]], np.cumsum(steps[:-1], 0)])


ZS_W, ZS_H = 320, 256
ZS_ROOT = (160.0, 200.0)  # 锚点：草丛中心的地面点（下面留给前排的根和土渣）
GRASS = [(0.0, "#2F7D57"), (0.45, "#6FD6A0"), (1.0, "#C6F4DC")]  # 根 → 主色 → 尖
GRASS_LIGHT = "#E2FAEC"


def make_react_zisheng() -> list[Image.Image]:
    """滋生：地上卷着长出一丛灵草：七株卷草（像蕨菜的嫩芽，尖上打卷、往外卷）从锚点四周破土，土渣往外蹦；
    0–2 帧往上长、卷慢慢舒开，3–5 帧长成、轻轻一摆后停住；根上四片小叶张开，地上一片很淡的绿，几粒淡绿的灵光点往上飘。
    普通混合，主色 #6FD6A0，焦墨勾边，不染；锚点是地面中心，radius_px 是滋生范围的横向半径（50，1080p 下一比一）。末帧可以留着。"""
    w, h = ZS_W, ZS_H
    ax, ay = ZS_ROOT
    rng = np.random.default_rng(9941)
    blades = []
    for k in range(7):
        gx = (k - 3) / 3 * 88 + rng.uniform(-9, 9)
        side = 1.0 if gx > 6 else (-1.0 if gx < -6 else float(rng.choice([-1.0, 1.0])))
        L = rng.uniform(104, 132) * (1 - 0.32 * abs(gx) / 92)
        blades.append(dict(root=(ax + gx, ay + rng.uniform(-22, 18) * FLAT), ang=-math.pi / 2 + 0.36 * gx / 92 + rng.uniform(-0.08, 0.08),
                           L=L, side=side, bend=side * rng.uniform(0.12, 0.3), curl=side * rng.uniform(3.9, 4.6),
                           w0=2.6 + 2.2 * L / 132, speed=rng.uniform(0.88, 1.12), seed=int(rng.integers(1 << 30))))
    leaves = []
    for k in range(4):
        gx = rng.uniform(-64, 64)
        side = 1.0 if gx >= 0 else -1.0
        leaves.append(dict(base=np.array([ax + gx, ay + rng.uniform(-6, 16) * FLAT]), ang=-math.pi / 2 + side * rng.uniform(0.75, 1.15),
                           L=rng.uniform(24, 32), wd=rng.uniform(9.5, 12.5)))
    motes = [(rng.uniform(-92, 92), rng.uniform(-16, 16), rng.uniform(1.5, 2.3), rng.uniform(0.75, 1.25)) for _ in range(9)]
    crumbs = [(rng.uniform(-84, 84), rng.uniform(-18, 18), rng.uniform(0, 2 * math.pi), rng.uniform(1.0, 1.9)) for _ in range(14)]
    grow = [0.24, 0.56, 0.84, 1.0, 1.0, 1.0]
    sway = [0.0, 0.0, 0.0, 0.07, 0.025, 0.0]
    hole_c, mote_c, light = V.col("#3E3227"), V.col("#D6F8E6"), V.col(GRASS_LIGHT)
    out = []
    for i in range(6):
        X, Y = grid(w, h)
        pt = Paint(X, Y)
        full = (slice(None), slice(None))
        gx_, gy_ = X - ax, (Y - ay) / FLAT
        edge = 112.0 * min(1.0, 0.35 + grow[i]) * (1 + V.angular_noise(np.random.default_rng(9942), np.arctan2(gy_, gx_), harmonics=(3, 5, 7, 9), amp=0.1))
        pt.over(full, V.col("#6FD6A0"), [0.08, 0.13, 0.16, 0.17, 0.17, 0.17][i] * smoothstep(edge, 0.55 * edge, np.hypot(gx_, gy_)))
        if i <= 2:  # 破土：土渣往外蹦
            for gx, gy, a0, sz in crumbs:
                d = [5.0, 13.0, 19.0][i]
                x = ax + gx + d * math.cos(a0)
                y = ay + (gy + d * math.sin(a0)) * FLAT - [5.0, 8.0, 3.0][i]
                sl = pt.window(x - 4, y - 4, x + 4, y + 4)
                pt.over(sl, hole_c, [0.85, 0.7, 0.4][i] * dot(X[sl], Y[sl], x, y, sz))
        items = [(b["root"][1], "b", b) for b in blades] + [(lf["base"][1], "l", lf) for lf in leaves]
        for _, kind, it in sorted(items, key=lambda q: q[0]):  # 从后往前画
            if kind == "l":  # 小叶：焦墨勾边、一道浅的叶脉
                g = float(smoothstep(0.2, 0.75, grow[i]))
                if g <= 0:
                    continue
                base = it["base"]
                u = np.array([math.cos(it["ang"]), math.sin(it["ang"])])
                tip = base + u * it["L"] * (0.45 + 0.55 * g)
                lo, hi = np.minimum(base, tip) - 10, np.maximum(base, tip) + 10
                sl = pt.window(lo[0], lo[1], hi[0], hi[1])
                cov, dd, along = almond_field(X[sl], Y[sl], base, tip, it["wd"] * (0.55 + 0.45 * g), bulge=0.4)
                pt.over(sl, JIAO, 0.88 * smoothstep(0.45, -0.45, dd - 1.1))
                v = -(X[sl] - base[0]) * u[1] + (Y[sl] - base[1]) * u[0]
                colr = lerp_col(0.3 + 0.5 * along, GRASS)
                colr = colr + (light - colr) * (0.55 * smoothstep(0.9, 0.3, np.abs(v)) * (along < 0.85))[..., None]
                pt.over(sl, colr, cov)
                continue
            b = it  # 卷草：先画一笔焦墨（宽 1 像素多一点，尾巴干笔断开），再在上面填绿
            g = min(1.0, grow[i] * b["speed"])
            L = b["L"] * g
            pts = curl_blade(b["root"], b["ang"] + b["side"] * sway[i], L, b["bend"], b["curl"] * (1.2 - 0.4 * g), float(np.clip(0.5 * L, 16, 40)))
            tt = np.linspace(0, 1, len(pts))
            hw = b["w0"] * (0.65 + 0.35 * g) * (1 - 0.8 * tt**0.9) + 0.45
            lo, hi = pts.min(0) - 9, pts.max(0) + 9
            sl = pt.window(lo[0], lo[1], hi[0], hi[1])
            r0 = b["root"]
            hole = np.hypot((X[sl] - r0[0]) / (b["w0"] * 2.0), (Y[sl] - r0[1] - 1) / (b["w0"] * 0.7))
            pt.over(sl, hole_c, 0.6 * g * smoothstep(1.0, 0.7, hole))
            ink, _ = V.brush_stroke(X[sl], Y[sl], pts, hw + 1.1, np.random.default_rng(b["seed"]), dry=0.3, dry_start=0.55, ss=SS)
            pt.over(sl, JIAO, 0.9 * ink)
            cov, f_ = smooth_stroke(X[sl], Y[sl], pts, hw)
            colr = lerp_col(0.12 + 0.88 * f_["t"], GRASS)
            colr = colr + (light - colr) * (0.4 * smoothstep(0.1, 0.8, -f_["perp"] / f_["hw"]))[..., None]  # 左边（向光）亮一点
            pt.over(sl, colr, cov)
        if 1 <= i <= 4:  # 灵光点往上飘
            for k, (gx, gy, sz, sp) in enumerate(motes):
                x = ax + gx + 3.0 * math.sin(1.3 * i + k)
                y = ay + gy * FLAT - (10.0 + 15.0 * i * sp)
                sl = pt.window(x - 5, y - 5, x + 5, y + 5)
                pt.over(sl, mote_c, [0.0, 0.6, 0.85, 0.75, 0.45][i] * dot(X[sl], Y[sl], x, y, sz))
        out.append(pt.image(9945 + i))
    return out


ZT_SIZE = 448
ZT_C = (224.0, 280.0)  # 炸开的点（锚点）：偏下，汽往上翻
ZT_R = 180  # 汽团的横向半径（蒸腾范围 70，1080p 下一比一）
STEAM = [(0.0, "#8F9CA8"), (0.55, "#E8EEF2"), (1.0, "#FFFFFF")]  # 背光 → 主色 → 受光


def make_react_zhengteng() -> list[Image.Image]:
    """蒸腾：一团白汽炸开、翻滚着往上升。0 帧一团紧的汽，八道汽柱往外喷；1–3 帧十几团汽往外滚开（每团左上受光、右下背光，
    背光那边一道淡灰的边，往下的贴地压扁）；4–6 帧整团往上飘、变大变薄，从上往下被扯成一缕缕。普通混合，主色 #E8EEF2，不染；
    radius_px 是汽团的横向半径（蒸腾范围 70，1080p 下一比一）。"""
    w = h = ZT_SIZE
    cx, cy = ZT_C
    rng = np.random.default_rng(9951)
    puffs = []
    for k in range(16):
        phi = 2 * math.pi * (k + rng.uniform(-0.35, 0.35)) / 16
        dist = rng.uniform(0.0, 0.45) if k % 3 == 0 else rng.uniform(0.5, 1.0)
        puffs.append(dict(phi=phi, dist=dist, r=rng.uniform(32, 46) * (1.12 - 0.3 * dist), rise=rng.uniform(0.8, 1.25), seed=int(rng.integers(1 << 30))))
    jets = [(2 * math.pi * (k + rng.uniform(-0.3, 0.3)) / 8, rng.uniform(64, 92)) for k in range(8)]
    spread = 128.0
    D = [0.2, 0.56, 0.84, 1.0, 1.08, 1.14, 1.18]  # 往外滚（× spread）
    SZ = [0.4, 0.7, 0.92, 1.02, 1.1, 1.17, 1.24]  # 每团的大小
    RISE = [0.0, 3.0, 8.0, 14.0, 24.0, 36.0, 50.0]  # 整团往上飘（像素）
    OP = [0.95, 0.95, 0.93, 0.88, 0.75, 0.55, 0.32]
    TEAR = [0.0, 0.0, 0.04, 0.1, 0.24, 0.4, 0.56]  # 扯碎的程度
    nrng = np.random.default_rng(9952)
    streaks = 0.5 + 0.2 * V.noise(nrng, (h + 96, w), (16.0, 3.5), angle=math.pi / 2)  # 竖着拉长的噪声，跟着汽往上走
    blobs = V.noise(nrng, (h, w), 6.0)
    lx, ly = -0.45, -0.89  # 光从左上来
    rim_c = V.col("#76838F")
    out = []
    for i in range(7):
        X, Y = grid(w, h)
        pt = Paint(X, Y)
        sh = min(int(RISE[i] * 1.3), 96)
        ns = np.repeat(np.repeat(streaks[sh : sh + h], SS, 0), SS, 1)
        nb = np.repeat(np.repeat(blobs, SS, 0), SS, 1)
        tear = TEAR[i] * np.clip(1.0 + (cy - Y) / 220.0, 0.5, 1.7)  # 越高扯得越碎
        keep = smoothstep(tear - 0.1, tear + 0.1, ns)
        cur = []
        for p in puffs:
            ux, uy = math.cos(p["phi"]), math.sin(p["phi"])
            uy = uy * FLAT if uy > 0 else 0.8 * uy
            cur.append((cy + uy * spread * p["dist"] * D[i] - RISE[i] * p["rise"], cx + ux * spread * p["dist"] * D[i], p["r"] * SZ[i], p))
        for py, px, r, p in sorted(cur, key=lambda q: q[0]):  # 上面（远）的先画，下面的盖上去
            sl = pt.window(px - 1.4 * r, py - 1.4 * r, px + 1.4 * r, py + 1.4 * r)
            dx, dy = X[sl] - px, Y[sl] - py
            edge = r * (1 + V.angular_noise(np.random.default_rng(p["seed"]), np.arctan2(dy, dx) + 0.15 * i, harmonics=(3, 4, 5, 7), amp=0.12))
            d = np.hypot(dx, dy) - edge
            shade = np.clip((dx * lx + dy * ly) / r, -1, 1)
            colr = lerp_col(0.55 + 0.45 * shade, STEAM)
            rim = smoothstep(-6.0, -0.5, d) * smoothstep(0.1, -0.5, shade)
            colr = colr + (rim_c - colr) * (0.5 * rim)[..., None]
            pt.over(sl, colr, smoothstep(1.5, -1.5, d) * OP[i] * (0.86 + 0.07 * nb[sl]) * keep[sl])
        if i <= 1:  # 往外喷的汽柱
            for a0, L in jets:
                sy_ = FLAT if math.sin(a0) > 0 else 1.0
                L2 = L * [0.8, 1.2][i]
                x0, y0 = cx + 14 * math.cos(a0), cy + 14 * math.sin(a0) * sy_
                x1, y1 = cx + L2 * math.cos(a0), cy + L2 * math.sin(a0) * sy_
                sl = pt.window(min(x0, x1) - 12, min(y0, y1) - 12, max(x0, x1) + 12, max(y0, y1) + 12)
                pt.over(sl, lerp_col(0.8, STEAM), [0.9, 0.55][i] * streak(X[sl], Y[sl], x0, y0, x1, y1, [8.0, 10.0][i]))
        out.append(pt.image(9955 + i))
    return out


RJ_FPS = 10  # 熔金印记循环的帧率（6 帧一圈 0.6 秒）
RJ_R = 30  # 金环半径（像素）
RJ_C = (64.0, 58.0)


def make_react_rongjin() -> list[Image.Image]:
    """熔金：妖物身上的熔金印记，循环（6 帧、10 帧/秒，首尾接得上）：一圈熔化的金环（干笔飞白，一段亮光绕着转，一圈转一周），
    环里四道短刻痕、一点金芯一明一暗；环下沿挂三滴金水往下淌、拉长、淡掉，再从环上冒出来；环外几点金星轮流一闪。
    叠加，主色 #FFB347，不染；radius_px 是金环的半径，游戏按妖物的身体半径缩放（半径 12 左右时 1080p 下一比一）。"""
    size = 128
    cx, cy = RJ_C
    rng = np.random.default_rng(9961)
    tex = W.ptex(rng, ns=12, nt=256, along=6.0, across=0.8)
    drips = [(math.radians(a), rng.uniform(0, 1)) for a in (62.0, 96.0, 128.0)]
    glints = [(rng.uniform(0, 2 * math.pi), rng.uniform(1.05, 1.3), k / 4 + rng.uniform(-0.05, 0.05)) for k in range(4)]
    n = 6
    out = []
    for i in range(n):
        ph = i / n
        X, Y = grid(size, size)
        acc = Acc(X, Y)
        full = (slice(None), slice(None))
        dx, dy = X - cx, Y - cy
        r = np.hypot(dx, dy)
        th = np.arctan2(dy, dx)
        rr = RJ_R * (1 + 0.04 * np.cos(3 * th + 1.3) + 0.025 * np.cos(5 * th + 0.4))
        q = (r - rr) / 3.0
        travel = 0.5 + 0.5 * np.cos(th - 2 * math.pi * ph)  # 一段亮光绕环转，一个循环转一圈
        ring = smoothstep(1.0, 0.45, np.abs(q)) * (0.65 + 0.35 * dry(tex, np.clip(q, -1, 1), (th / (2 * math.pi)) % 1, 0.3))
        acc.add(full, ring * (0.5 + 0.5 * travel**3), 0.4 + 0.55 * travel**3)
        acc.add(full, 0.22 * np.exp(-(((r - rr) / 7.0) ** 2)), 0.25)
        pulse = 0.72 + 0.28 * math.cos(2 * math.pi * ph)
        for k in range(4):
            a = math.pi / 4 + k * math.pi / 2
            cv, _ = needle(X, Y, cx + 8 * math.cos(a), cy + 8 * math.sin(a), a, 12.0, 1.7, taper=0.8)
            acc.add(full, 0.75 * pulse * cv, 0.65)
        acc.add(full, pulse * np.exp(-((r / 5.0) ** 2)), 1.0)
        for a0, p0 in drips:  # 金水：sin(π f) 在 f = 0、1 都是 0，接得上
            f = (ph + p0) % 1.0
            e = math.sin(math.pi * f)
            sx, sy = cx + RJ_R * math.cos(a0), cy + RJ_R * math.sin(a0)
            hx, hy = sx, sy + 5 + 20 * f
            d, u = seg(X, Y, sx, sy, hx, hy)
            acc.add(full, e * 0.65 * smoothstep(1.3, 0.4, d) * (0.4 + 0.6 * u), 0.55)
            acc.add(full, e * dot(X, Y, hx, hy + 1.0, 2.4 - 0.5 * f), 0.85)
        for a0, rf, p0 in glints:
            life = max(0.0, math.sin(2 * math.pi * ((ph + p0) % 1.0))) ** 2
            if life <= 0.01:
                continue
            gx, gy = cx + RJ_R * rf * math.cos(a0), cy + RJ_R * rf * math.sin(a0)
            for ang in (0.0, math.pi / 2, math.pi, 1.5 * math.pi):
                cv, _ = needle(X, Y, gx, gy, ang, 6.0 * life + 2, 1.1, taper=1.4)
                acc.add(full, life * cv, 0.95)
        out.append(frame_color(acc.a, acc.heat(), 9965 + i, [(0.0, "#A0521C"), (0.5, "#FFB347"), (1.0, "#FFF2C8")]))
    return out


DM_PAL = [(0.0, "#4FBF86"), (0.25, "#6FD6A0"), (0.75, "#E9D9A6"), (1.0, "#FFF6DA")]  # 热度：木 0.25、金 0.75、闪 1.0


def make_react_duanmu() -> list[Image.Image]:
    """断木：交叉的两刀。0 帧金色的一刀从左上斩到右下（中段粗、两头尖，外弧一侧是亮的刃口），刀头最亮；1 帧这刀亮满，
    木色的一刀从右上斩到左下；2 帧两刀都在，交叉处一闪（白金），木屑和金星往外崩；3–4 帧两刀从交叉处断开、往两边错开淡掉，
    木屑飞远。叠加，金 #E9D9A6 + 木 #6FD6A0，不染（自带颜色按热度：木 0.25、金 0.75、闪 1.0）。"""
    size = 256
    rng = np.random.default_rng(9981)
    cuts = [(np.array([52.0, 46.0]), np.array([206.0, 212.0]), 13.0, 0.75), (np.array([210.0, 50.0]), np.array([48.0, 206.0]), -11.0, 0.25)]
    seeds = [int(rng.integers(1 << 30)) for _ in cuts]
    curves = []
    for p0, p1, bulge, _ in cuts:
        u = (p1 - p0) / np.linalg.norm(p1 - p0)
        nrm = np.array([-u[1], u[0]])
        curves.append((V.bezier([p0, (p0 + p1) / 2 + nrm * bulge, p1], 120), u, nrm))
    d2 = ((curves[0][0][:, None] - curves[1][0][None]) ** 2).sum(-1)
    k0, k1 = np.unravel_index(int(d2.argmin()), d2.shape)
    xc, yc = (curves[0][0][k0] + curves[1][0][k1]) / 2  # 交叉点
    chips = [(rng.uniform(0, 2 * math.pi), rng.uniform(0.6, 1.0), rng.uniform(1.4, 2.3), float(rng.choice([0.25, 0.75]))) for _ in range(14)]
    reveal = [(0.72, 0.0), (1.0, 0.7), (1.0, 1.0), (1.0, 1.0), (1.0, 1.0)]  # 每帧两刀各斩到哪
    env = [(1.0, 0.0), (0.92, 1.0), (0.95, 1.0), (0.6, 0.62), (0.28, 0.3)]
    split = [0.0, 0.0, 0.0, 4.5, 9.0]  # 断开后错开的距离
    flash = [0.0, 0.55, 1.0, 0.35, 0.0]
    tt = np.linspace(0, 1, 120)
    hw = 7.0 * np.sin(np.pi * tt) ** 0.6 + 0.35
    out = []
    for i in range(5):
        X, Y = grid(size, size)
        acc = Acc(X, Y)
        full = (slice(None), slice(None))
        for (pts, u, nrm), (_, _, bulge, heat), sd, rv, e in zip(curves, cuts, seeds, reveal[i], env[i]):
            if rv <= 0 or e <= 0:
                continue
            halves = [(slice(0, 61), -1.0), (slice(60, 120), 1.0)] if split[i] > 0 else [(slice(0, 120), 0.0)]
            for k, (part, sgn) in enumerate(halves):
                q = pts[part] + sgn * split[i] * (nrm + 0.6 * u)
                lo, hi = q.min(0) - 12, q.max(0) + 12
                sl = acc.window(lo[0], lo[1], hi[0], hi[1])
                cov, f_ = V.brush_stroke(X[sl], Y[sl], q, hw[part], np.random.default_rng(sd + k), dry=0.35 + 0.1 * i, dry_start=0.55, ss=SS)
                t_full = tt[part][0] + f_["t"] * (tt[part][-1] - tt[part][0])  # 回到整刀的 0..1
                head = smoothstep(rv + 0.02, rv - 0.08, t_full) * (0.45 + 0.55 * np.clip(t_full / rv, 0, 1)) if rv < 1 else 1.0
                edge = smoothstep(0.25, 0.85, math.copysign(1.0, bulge) * f_["perp"] / f_["hw"])
                acc.add(sl, e * cov * head * (0.65 + 0.35 * edge), heat + 0.12 * edge)
        if flash[i] > 0:  # 交叉处一闪
            for ang in (0.0, math.pi / 2, math.pi, 1.5 * math.pi):
                cv, _ = needle(X, Y, xc, yc, ang, [0, 26.0, 40.0, 30.0][i], 2.4, taper=1.4)
                acc.add(full, flash[i] * cv, 1.0)
            acc.add(full, flash[i] * np.exp(-((np.hypot(X - xc, Y - yc) / [1, 6.0, 9.0, 7.0][i]) ** 2)), 1.0)
        if i >= 2:  # 木屑、金星往外崩
            for a0, df, sz, heat in chips:
                d1 = [0, 0, 22.0, 52.0, 78.0][i] * df
                d0 = max(0.0, d1 - 12.0)
                x0, y0 = xc + d0 * math.cos(a0), yc + d0 * math.sin(a0)
                x1, y1 = xc + d1 * math.cos(a0), yc + d1 * math.sin(a0) + 0.02 * d1 * d1
                sl = acc.window(min(x0, x1) - 6, min(y0, y1) - 6, max(x0, x1) + 6, max(y0, y1) + 6)
                acc.add(sl, [0, 0, 0.9, 0.7, 0.4][i] * streak(X[sl], Y[sl], x0, y0, x1, y1, sz), heat)
        out.append(frame_color(acc.a, acc.heat(), 9985 + i, DM_PAL))
    return out


LT_W, LT_H = 352, 256
LT_ROOT = (176.0, 220.0)  # 锚点：地刺根部的地面中心（底边往上 36 像素，下面留给地缝和土渣）
LT_R = 150  # 地刺丛的横向半径（裂土范围 60，1080p 下一比一）
EARTH = {"lit": "#B08B60", "mid": "#8B6A47", "dark": "#5E4630", "hole": "#3E3227", "dust": "#A08462", "chip": "#4A3826"}


def spike_shape(rng, H, wb, lean):
    """一根地刺的多边形（局部坐标：根的中点在原点，往上是 −y）：左右两边各四个抖动的点，按 lean 斜切（尖往外歪）。"""
    us = np.array([0.22, 0.45, 0.66, 0.84])
    left = [(-wb * (1 - u) ** 0.8 + rng.uniform(-0.16, 0.1) * wb, -H * u + rng.uniform(-3, 3)) for u in us]
    right = [(wb * (1 - u) ** 0.8 + rng.uniform(-0.1, 0.16) * wb, -H * u + rng.uniform(-3, 3)) for u in us]
    poly = np.array([(-wb, 0.0)] + left + [(rng.uniform(-1.5, 1.5), -H)] + right[::-1] + [(wb, 0.0)])
    poly[:, 0] += -poly[:, 1] * lean
    return poly


def make_react_lietu() -> list[Image.Image]:
    """裂土：一簇地刺破土而出。地上先裂开七道墨缝、土坑；七根尖石刺从坑里冲出来（中间的最高，两边的矮、往外歪），
    0 帧冒头、1 帧冲到顶、2 帧略过头、3 帧站住；每根左边受光（#B08B60）、右边背光（#5E4630），焦墨勾边，背光面几笔皴；
    碎石往外蹦、根上扬土；4 帧刺上裂开几道缝、尖上掉渣，5 帧往下塌回土里、变淡。普通混合，主色 #8B6A47，不染；
    锚点在地刺根部的地面中心，radius_px 是地刺丛的横向半径（裂土范围 60，1080p 下一比一）。"""
    w, h = LT_W, LT_H
    ax, ay = LT_ROOT
    rng = np.random.default_rng(9991)
    layout = [(0.0, -8.0, 134.0, 22.0, 0.0), (-34.0, 4.0, 102.0, 18.0, -0.2), (36.0, -2.0, 110.0, 18.0, 0.22), (-68.0, -6.0, 78.0, 15.0, -0.38),
              (70.0, 8.0, 74.0, 15.0, 0.36), (-104.0, 2.0, 50.0, 12.0, -0.55), (102.0, -4.0, 56.0, 12.0, 0.52)]
    spikes = []
    for gx, gy, H, wb, lean in layout:
        H *= rng.uniform(0.92, 1.08)
        lean += rng.uniform(-0.05, 0.05)
        spikes.append(dict(root=np.array([ax + gx + rng.uniform(-4, 4), ay + gy * FLAT]), H=H, wb=wb, side=1.0 if gx >= 0 else -1.0,
                           poly=spike_shape(rng, H, wb, lean), delay=rng.uniform(0, 0.12) + abs(gx) / 104 * 0.15,
                           frac=rng.uniform(0.52, 0.68), seed=int(rng.integers(1 << 30))))
    cracks = [jag_path(rng, (0.0, 0.0), 2 * math.pi * (k + rng.uniform(-0.3, 0.3)) / 7 + 0.2, rng.uniform(110, 150), n=10, jitter=0.35) for k in range(7)]
    pebbles = [(rng.uniform(-0.95 * math.pi, -0.05 * math.pi), rng.uniform(70, 130), rng.uniform(2.2, 4.0), int(rng.integers(0, 7)), rng.uniform(0, 2 * math.pi))
               for _ in range(12)]
    dusts = [(int(k), rng.uniform(-10, 10), rng.uniform(14, 22), int(rng.integers(1 << 30))) for k in range(7) for _ in range(2)]
    rise = [0.42, 0.98, 1.06, 1.0, 0.97, 0.55]
    OP = [1.0, 1.0, 1.0, 1.0, 0.94, 0.62]
    crack_grow = [0.45, 0.85, 1.0, 1.0, 1.0, 1.0]
    lit_c, mid_c, dark_c, hole_c = (V.col(EARTH[k]) for k in ("lit", "mid", "dark", "hole"))
    mottle = V.noise(np.random.default_rng(9993), (h, w), 2.5)
    out = []
    for i in range(6):
        X, Y = grid(w, h)
        pt = Paint(X, Y)
        mt = np.repeat(np.repeat(mottle, SS, 0), SS, 1)
        for pts in cracks:  # 地缝（焦墨，压扁）
            m = max(2, int(round(len(pts) * crack_grow[i])))
            sp = pts[:m] * np.array([1.0, FLAT]) + np.array([ax, ay])
            lo, hi = sp.min(0) - 6, sp.max(0) + 6
            sl = pt.window(lo[0], lo[1], hi[0], hi[1])
            d, tpar = polyline_dist(X[sl], Y[sl], sp)
            wid = 1.5 * (1 - 0.7 * tpar) + 0.35
            pt.over(sl, JIAO, OP[i] * 0.85 * smoothstep(wid + 0.5, wid - 0.5, d))
        for s in spikes:  # 土坑
            r0 = s["root"]
            sl = pt.window(r0[0] - 2 * s["wb"], r0[1] - s["wb"], r0[0] + 2 * s["wb"], r0[1] + s["wb"])
            e = np.hypot((X[sl] - r0[0]) / (1.3 * s["wb"]), (Y[sl] - r0[1]) / (0.42 * s["wb"]))
            pt.over(sl, hole_c, OP[i] * 0.85 * smoothstep(1.0, 0.75, e))
        for s in sorted(spikes, key=lambda q: q["root"][1]):  # 地刺（从后往前）
            hgt = max(0.08, rise[i] - s["delay"] * [1.0, 0.4, 0, 0, 0, 0][i])
            pl = s["poly"].copy()
            if hgt >= 1:
                pl[:, 1] *= hgt
            else:
                pl[:, 1] += (1 - hgt) * s["H"]
            poly = pl + s["root"]
            lo, hi = poly.min(0) - 4, poly.max(0) + 4
            sl = pt.window(lo[0], lo[1], hi[0], min(hi[1], s["root"][1] + 3))
            Xs, Ys = X[sl], Y[sl]
            cov, dd = poly_cover(Xs, Ys, poly)
            cov = cov * smoothstep(s["root"][1] + 1.0, s["root"][1] - 1.0, Ys)  # 地面以下的看不见
            b0 = s["root"] + np.array([0.0, max(0.0, (1 - hgt) * s["H"])])
            tip = poly[int(np.argmin(poly[:, 1]))]
            axv = (tip - b0) / max(np.linalg.norm(tip - b0), 1e-6)
            nv = np.array([-axv[1], axv[0]])
            v = (Xs - b0[0]) * nv[0] + (Ys - b0[1]) * nv[1]  # 中脊右边为正（背光）
            k = smoothstep(-2.5, 2.5, v)
            colr = lit_c * (1 - k[..., None]) + dark_c * k[..., None]
            colr = colr + (mid_c - colr) * np.clip(0.25 + 0.2 * mt[sl], 0, 0.6)[..., None]
            low = smoothstep(s["root"][1] - 0.3 * s["H"], s["root"][1], Ys)  # 根上暗一点
            colr = colr + (dark_c - colr) * (0.35 * low)[..., None]
            pt.over(sl, colr, OP[i] * cov)
            rr = np.random.default_rng(s["seed"])
            for uq in (0.25, 0.45, 0.65):  # 背光面几笔皴
                p0 = b0 + (tip - b0) * uq + nv * 2.0
                p1 = p0 + (nv * 0.55 - axv * 0.35) * s["wb"] * (1 - uq) * rr.uniform(0.8, 1.1)
                d, uu = seg(Xs, Ys, *p0, *p1)
                pt.over(sl, JIAO, OP[i] * 0.6 * cov * smoothstep(1.1, 0.3, d) * (1 - 0.6 * uu))
            band = smoothstep(1.7, 0.6, np.abs(dd)) * (dd > -2.0) * smoothstep(s["root"][1] + 1.0, s["root"][1] - 1.0, Ys)
            tex = W.ptex(rr, ns=8, nt=128, along=5.0, across=0.8)
            per = (np.arctan2(Ys - (b0[1] + tip[1]) / 2, Xs - (b0[0] + tip[0]) / 2) / (2 * math.pi)) % 1
            pt.over(sl, JIAO, OP[i] * 0.92 * band * (0.55 + 0.45 * dry(tex, 0.0 * per, per, 0.35)))
            if i >= 4:  # 裂开：一道横着的折线缝
                yk = b0 + (tip - b0) * s["frac"]
                pts = jag_path(rr, yk - nv * s["wb"] * 1.2, math.atan2(nv[1], nv[0]) + rr.uniform(-0.25, 0.25), 2.4 * s["wb"], n=6, jitter=0.5)
                d, _ = polyline_dist(Xs, Ys, pts)
                pt.over(sl, JIAO, OP[i] * 0.9 * cov * smoothstep(1.3, 0.4, d))
        if i <= 3:  # 碎石往外蹦（抛物线）
            for a0, v0, sz, ks, rot in pebbles:
                t = [0.25, 0.55, 0.85, 1.1][i]
                r0 = spikes[ks]["root"]
                x = r0[0] + math.cos(a0) * v0 * t
                y = r0[1] - 6 + math.sin(a0) * v0 * t + 70 * t * t
                if y > r0[1] + 12:
                    continue
                quad = np.array([(x + sz * math.cos(rot + i + q * 1.7), y + sz * 0.8 * math.sin(rot + i + q * 1.7)) for q in range(4)])
                sl = pt.window(x - 6, y - 6, x + 6, y + 6)
                c, _ = poly_cover(X[sl], Y[sl], quad)
                pt.over(sl, V.col(EARTH["chip"]), 0.95 * c)
        if i >= 4:  # 尖上掉渣
            for s in spikes[:5]:
                tip = s["poly"][int(np.argmin(s["poly"][:, 1]))] + s["root"]
                for q in range(2):
                    x = tip[0] + s["side"] * (3 + 5 * q) * (i - 3)
                    y = tip[1] + (8 + 14 * q) * (i - 3) ** 1.4 + (1 - rise[i]) * s["H"] * 0.3
                    sl = pt.window(x - 5, y - 5, x + 5, y + 5)
                    pt.over(sl, V.col(EARTH["chip"]), OP[i] * 0.9 * dot(X[sl], Y[sl], x, y, 2.2 - 0.5 * q))
        if i <= 3:  # 根上扬土
            for ks, ox, rad, sd in dusts:
                r0 = spikes[ks]["root"]
                x, y = r0[0] + ox * (1 + 0.3 * i), r0[1] - 4 - 6 * i
                R_ = rad * (0.7 + 0.25 * i)
                sl = pt.window(x - 1.6 * R_, y - 1.6 * R_, x + 1.6 * R_, y + 1.6 * R_)
                dx, dy = X[sl] - x, Y[sl] - y
                edge = R_ * (1 + V.angular_noise(np.random.default_rng(sd), np.arctan2(dy, dx), harmonics=(3, 4, 5, 7), amp=0.15))
                pt.over(sl, V.col(EARTH["dust"]), [0.5, 0.45, 0.32, 0.16][i] * smoothstep(0.0, -0.45 * R_, np.hypot(dx, dy * 1.3) - edge))
        out.append(pt.image(9995 + i))
    return out


YN_W, YN_H = 416, 272
YN_R = 172  # 泥滩的横向半径（淤泥范围 70，1080p 下一比一 ≈ 180）
MUD = {"body": "#5B4A3A", "deep": "#46382B", "rim": "#3E3227", "hi": "#8A745C", "hi2": "#A28C70"}


def make_react_yuni() -> list[Image.Image]:
    """淤泥：一团泥浆砸在地上溅开、摊成一滩。0 帧中间一团泥、九道泥舌往外甩，泥点飞在半空（沿飞的方向拉长）；
    1–2 帧摊开、泥舌收成一圈不规则的边，泥点落地成一圈小泥斑；3–5 帧落定：边上一圈深色的积泥（像颜料干在边上），
    面上三道亮的反光、几个气泡，3–4 帧一圈涟漪往外。已压扁，普通混合，主色 #5B4A3A，不染；
    radius_px 是泥滩的横向半径（淤泥范围 70，1080p 下一比一）；末帧留着（持续 4 秒，游戏淡出）。"""
    w, h = YN_W, YN_H
    cx, cy = w / 2, h / 2
    rng = np.random.default_rng(9971)
    fingers = [(2 * math.pi * (k + rng.uniform(-0.3, 0.3)) / 9, rng.uniform(0.8, 1.2), rng.uniform(0.08, 0.12)) for k in range(9)]
    drops = [(rng.uniform(0, 2 * math.pi), rng.uniform(1.02, 1.12), rng.uniform(3.0, 6.0)) for _ in range(16)]
    bubbles = [(rng.uniform(0, 2 * math.pi), rng.uniform(0.15, 0.65), rng.uniform(2.5, 4.2)) for _ in range(5)]
    sheens = [(-0.32, -0.3, 0.42, 195.0, 275.0), (0.18, 0.2, 0.3, 200.0, 250.0), (-0.05, 0.42, 0.22, 190.0, 240.0)]  # (中心 x, y（× R）, 半径, 起止角)
    Rs = [0.3, 0.64, 0.86, 0.96, 0.995, 1.0]
    FL = [0.5, 0.36, 0.16, 0.06, 0.01, 0.0]  # 泥舌长（× YN_R）
    DR = [0.45, 0.8, 1.0, 1.0, 1.0, 1.0]  # 泥点飞到哪（× 落点）
    body_c, rim_c, hi_c, hi2_c = (V.col(MUD[k]) for k in ("body", "rim", "hi", "hi2"))
    mottle = V.noise(np.random.default_rng(9973), (h, w), 5.0)
    out = []
    for i in range(6):
        X, Y = grid(w, h)
        pt = Paint(X, Y)
        full = (slice(None), slice(None))
        gx, gy = X - cx, (Y - cy) / FLAT
        r = np.hypot(gx, gy)
        th = np.arctan2(gy, gx)
        R = YN_R * Rs[i]
        edge = R * (1 + V.angular_noise(np.random.default_rng(9972), th, harmonics=(3, 4, 5, 7, 9, 11), amp=0.1))
        for a0, lf, wf in fingers:
            edge = edge + FL[i] * YN_R * lf * np.exp(-((np.angle(np.exp(1j * (th - a0))) / wf) ** 2))
        d = r - edge
        mt = np.repeat(np.repeat(mottle, SS, 0), SS, 1)
        colr = lerp_col(0.5 + 0.12 * mt, [(0.0, MUD["deep"]), (0.5, MUD["body"]), (1.0, MUD["hi"])])
        rim = smoothstep(-6.0, -1.0, d)
        colr = colr + (rim_c - colr) * (0.85 * rim)[..., None]
        pt.over(full, colr, smoothstep(1.0, -1.0, d) * (0.9 + 0.08 * rim))
        for a0, df, sz in drops:
            dist = YN_R * df * DR[i]
            x, y = cx + dist * math.cos(a0), cy + dist * math.sin(a0) * FLAT
            sl = pt.window(x - 14, y - 10, x + 14, y + 10)
            if i <= 1:  # 半空里：沿飞的方向拉长
                back = [10.0, 7.0][i]
                pt.over(sl, body_c, 0.92 * streak(X[sl], Y[sl], x - back * math.cos(a0), y - back * math.sin(a0) * FLAT, x, y, sz * 0.8))
            else:  # 落地的泥斑
                e = np.hypot((X[sl] - x) / sz, (Y[sl] - y) / (sz * FLAT))
                pt.over(sl, rim_c, smoothstep(1.1, 0.9, e))
                pt.over(sl, body_c, 0.9 * smoothstep(0.75, 0.5, e))
        if i >= 2:  # 面上的反光
            for sx, sy, sr, a0, a1 in sheens:
                angs = np.radians(np.linspace(a0, a1, 24))
                arc = np.stack([cx + R * (sx + sr * np.cos(angs)), cy + R * (sy + sr * np.sin(angs)) * FLAT], -1)
                lo, hi = arc.min(0) - 5, arc.max(0) + 5
                sl = pt.window(lo[0], lo[1], hi[0], hi[1])
                dd, tpar = polyline_dist(X[sl], Y[sl], arc)
                wid = 1.6 * np.sin(np.pi * tpar) + 0.3
                pt.over(sl, hi_c, [0, 0, 0.5, 0.75, 0.75, 0.75][i] * smoothstep(wid + 0.5, wid - 0.5, dd))
        if 3 <= i <= 4:  # 涟漪
            rr = R * [0, 0, 0, 0.42, 0.68][i]
            pt.over(full, hi2_c, [0, 0, 0, 0.5, 0.28][i] * smoothstep(1.6, 0.3, np.abs(r - rr) * np.hypot(1.0, 0.0)) * (d < -4))
        if i >= 3:  # 气泡
            for a0, bf, sz in bubbles:
                x, y = cx + R * bf * math.cos(a0), cy + R * bf * math.sin(a0) * FLAT
                sl = pt.window(x - 7, y - 7, x + 7, y + 7)
                e = np.hypot(X[sl] - x, (Y[sl] - y) / FLAT * 0.8)
                pt.over(sl, hi_c, 0.8 * smoothstep(0.9, 0.3, np.abs(e - sz)))
                pt.over(sl, hi2_c, 0.9 * dot(X[sl], Y[sl], x - 0.35 * sz, y - 0.3 * sz, 0.8))
        out.append(pt.image(9975 + i))
    return out
