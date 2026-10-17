# ============================================================== 青藤：藤、回血的绿光、万木春缠绕

VINE_W, VINE_H = 512, 32  # 横向拉到连线长度（游戏按 长度 ÷ 画布宽 拉伸），竖向整张 = 10 世界单位
VINE_FPS = 8
VINE_LEAVES = 12


def vine_stem_y(x, ph: float, amp: float = 3.2, lam: float = 118.0):
    """藤的中线：两头贴着中线（接主角和妖物），中间几道弯，弯随相位往妖物那头（+x）走。"""
    env = np.clip(np.sin(np.pi * np.clip(x / VINE_W, 0, 1)), 0, 1) ** 0.6
    return VINE_H / 2 + amp * env * np.sin(2 * math.pi * x / lam - ph)


def make_vine() -> list[Image.Image]:
    """青藤：主角（左端）连到妖物（右端，锚点）的一根藤。一根亮的主藤带几道弯，一根细的卷须绕着它拧；
    两侧交替长十二片小叶，叶尖朝妖物那头（+x），叶边亮、叶心淡、一道叶脉；两端在中线上收细。
    3 帧循环（8 帧/秒）：藤上的弯往妖物那头走，叶子翻一翻。叠加，白色可染（游戏染青绿）。"""
    w, h = VINE_W, VINE_H
    rng = np.random.default_rng(9761)
    tex = W.ptex(rng, ns=16, nt=1024, along=30.0, across=0.6)
    leaves = []
    for k in range(VINE_LEAVES):
        x0 = 30 + (w - 60) * (k + 0.5 + rng.uniform(-0.2, 0.2)) / VINE_LEAVES
        side = -1.0 if k % 2 == 0 else 1.0
        leaves.append((x0, side, rng.uniform(8.0, 11.0), rng.uniform(3.6, 4.6), math.radians(rng.uniform(32, 48)), rng.uniform(0, 2 * math.pi)))
    out = []
    for i in range(3):
        ph = 2 * math.pi * i / 3
        X, Y = grid(w, h)
        acc = F.Acc(X, Y)
        full = (slice(None), slice(None))
        ends = smoothstep(4.0, 22.0, X) * smoothstep(w - 4.0, w - 16.0, X)  # 两端收细、淡掉
        ys = vine_stem_y(X, ph)
        d = Y - ys
        hw = 2.0 * ends + 0.3
        core = smoothstep(hw + 0.5, hw - 0.5, np.abs(d))
        halo = np.exp(-((d / 4.5) ** 2)) * ends
        grain_ = dry(tex, np.clip(d / 2.5, -1, 1), X / w * 0.7 + 0.1 * i, 0.15)
        acc.add(full, 0.9 * core * ends * (0.75 + 0.25 * grain_))
        acc.add(full, 0.2 * halo)
        # 卷须：细的一根绕着主藤拧（在前面那半圈亮、后面那半圈暗）
        tw = 2 * math.pi * X / 38.0 - ph * 0.5
        yt = ys + 4.2 * np.sin(tw) * ends
        front = 0.45 + 0.55 * (np.cos(tw) > 0)
        acc.add(full, 0.65 * front * ends * smoothstep(1.4, 0.4, np.abs(Y - yt)))
        for x0, side, L, wd, ang0, lph in leaves:  # 叶子：叶尖朝 +x，上下交替，翻一翻
            y0 = float(vine_stem_y(np.array(x0), ph))
            ang = side * (ang0 + math.radians(10.0) * math.sin(ph + lph))
            u = np.array([math.cos(ang), math.sin(ang)])  # 图里 y 向下：side=-1 朝右上
            base = np.array([x0, y0])
            tip = base + u * L
            lo, hi = np.minimum(base, tip) - wd - 2, np.maximum(base, tip) + wd + 2
            sl = acc.window(lo[0], lo[1], hi[0], hi[1])
            cov, dd, along = F.almond_field(X[sl], Y[sl], base, tip, wd * (0.85 + 0.15 * math.cos(ph + lph)), bulge=0.4)
            rim = smoothstep(1.3, 0.0, np.abs(dd)) * (dd < 0.6)
            vperp = -(X[sl] - base[0]) * u[1] + (Y[sl] - base[1]) * u[0]
            rib = smoothstep(0.7, 0.2, np.abs(vperp)) * (along < 0.85)
            acc.add(sl, np.clip(0.32 * cov + 0.85 * rim + 0.4 * rib * cov, 0, 1))
        out.append(F.frame_white(acc.a, 9765 + i))
    return out


PULSE_W, PULSE_H = 96, 32
PULSE_HEAD = (78.0, 16.0)


def make_vine_pulse() -> list[Image.Image]:
    """每跳回血：一颗绿光从妖物沿藤流回主角。头朝 +x（锚点在头上），身后拖一道细尾，尾上几点碎光；
    3 帧循环（24 帧/秒）：头一明一暗、碎光往后掉。叠加，白色可染（染青绿）。"""
    w, h = PULSE_W, PULSE_H
    hx, hy = PULSE_HEAD
    rng = np.random.default_rng(9771)
    motes = [(rng.uniform(10, 56), rng.uniform(-3, 3), rng.uniform(0.7, 1.1), rng.uniform(0, 1)) for _ in range(7)]
    out = []
    for i in range(3):
        X, Y = grid(w, h)
        a = []
        r = np.hypot(X - hx, Y - hy)
        pulse = [1.0, 0.86, 0.93][i]
        a.append(pulse * smoothstep(3.6, 2.4, r))
        a.append(0.45 * pulse * np.exp(-((r / 7.5) ** 2)))
        tail, _ = needle(X, Y, hx, hy, math.pi, 62.0, 2.6, w1=0.2, taper=0.8)
        u = np.clip((hx - X) / 62.0, 0, 1)
        a.append(0.7 * tail * (1 - u) ** 0.8)
        for dx, dy, sz, p0 in motes:
            t = (i / 3 + p0) % 1.0
            x = hx - dx - 10 * t
            a.append(0.75 * (1 - t) * (1 - dx / 70) * F.dot(X, Y, x, hy + dy * (0.5 + t), sz))
        out.append(F.frame_white(soft_union(*a), 9775 + i))
    return out


BIND_SIZE = 192
BIND_R = 56.0  # 缠绕圈的横向半径（像素）≈ 妖物半径；游戏按妖物半径缩放


def make_vine_bind() -> list[Image.Image]:
    """万木春缠绕：藤蔓从妖物脚下长出来，绕着身子往上盘三圈把它裹住（盘的圈按地面透视压扁，前半圈亮、后半圈暗），
    盘的时候冒出几片叶子。0–2 帧长上去、盘紧，第 3 帧裹住（留着到缠绕结束，游戏淡出）。叠加，白色可染（染青绿）。
    锚点在画布中心偏下（妖物脚底）；radius_px 是缠绕圈的横向半径，按妖物半径缩放。"""
    size = BIND_SIZE
    cx, cy = size / 2, size * 0.72
    rng = np.random.default_rng(9781)
    tex = W.ptex(rng, ns=16, nt=1024, along=30.0, across=0.6)
    grow = [0.35, 0.7, 1.0, 1.0]
    out = []
    for i in range(4):
        X, Y = grid(size, size)
        acc = F.Acc(X, Y)
        for strand in range(2):
            n = 260
            t = np.linspace(0, grow[i], n)
            turns = 2.6
            th = 2 * math.pi * turns * t + strand * math.pi
            rr = BIND_R * (1.0 - 0.18 * t) * (0.92 + 0.08 * strand)
            pts = np.stack([cx + rr * np.cos(th), cy - 92 * t + rr * np.sin(th) * F.FLAT * 0.55], -1)
            front = np.sin(th) > 0  # 前半圈（靠镜头）亮
            hw = (2.6 - 1.2 * t) * (0.6 + 0.4 * np.clip(t * 6, 0, 1))
            cov, f = V.brush_stroke(X, Y, pts, hw, np.random.default_rng(9785 + strand), dry=0.25, dry_start=0.7, ss=SS)
            idx = np.clip((f["t"] * (n - 1)).round().astype(int), 0, n - 1)
            acc.add((slice(None), slice(None)), np.where(front[idx], 0.95, 0.4) * cov)
            for j in range(4):  # 叶子
                tj = (j + 0.6 + 0.4 * strand) / 4.6
                if tj > grow[i]:
                    continue
                p = int(tj / grow[i] * (n - 1))
                base = pts[p]
                ang = th[p] + math.pi / 2 + (0.6 if strand else -0.6)
                u = np.array([math.cos(ang), math.sin(ang) * 0.7])
                u /= np.linalg.norm(u)
                L = 12.0 * min(1.0, (grow[i] - tj) * 4 + 0.4)
                tip = base + u * L
                sl = acc.window(min(base[0], tip[0]) - 8, min(base[1], tip[1]) - 8, max(base[0], tip[0]) + 8, max(base[1], tip[1]) + 8)
                cv, dd, _ = F.almond_field(X[sl], Y[sl], base, tip, 5.0, bulge=0.4)
                rim = smoothstep(1.3, 0.0, np.abs(dd)) * (dd < 0.6)
                acc.add(sl, (0.9 if front[p] else 0.45) * np.clip(0.3 * cv + 0.85 * rim, 0, 1))
        out.append(F.frame_white(acc.a * (0.85 + 0.15 * dry(tex, 0.0, X / size, 0.2)), 9790 + i))
    return out


