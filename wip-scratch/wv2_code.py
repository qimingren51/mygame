# ============================================================== 沧浪：浪头（水墙）、泡沫痕

# 试玩第 1 轮第二版（用户要“加粗加强”）：浪身厚到原来的 2.3 倍，浪唇一排卷起的浪花，前沿溅水花、起水雾，身后拖泡沫；
# 另出一层普通混合的墨蓝水体（*_body，同画布、同锚点、同帧号），在灯下的暖纸面上靠它的深色把白浪托出来。
WAVE_W, WAVE_H = 448, 128
WAVE_SPAN = 432.0  # 浪头横向的宽（像素）≈ 画布宽；游戏按 2 × 半宽 等比缩放（1080p 下 168 单位一比一）
WAVE_Y0 = 88.0  # 浪头正中的前沿（锚点）；往图里 +y（下）推进，两头往后（上）弯
WAVE_SAG = 44.0  # 两头比正中落后多少像素（月牙）
WAVE_T = 58.0  # 浪身正中的厚（往后，像素）；第一版 25
WAVE_FPS = 12
TRAIL_W, TRAIL_H = 448, 256
WATER = [(0.0, "#132A42"), (0.3, "#1F4669"), (1.0, "#3C729C")]  # 墨蓝水体：浪唇下最深 → 浪背浅、薄
WATER_INK = "#0E1C2C"


def bilerp(tex: np.ndarray, x, y) -> np.ndarray:
    """周期纹理的双线性采样（x、y 是纹理像素坐标，超出就绕回）。"""
    h, w = tex.shape
    x0, y0 = np.floor(x), np.floor(y)
    fx, fy = x - x0, y - y0
    x0, y0 = x0.astype(int) % w, y0.astype(int) % h
    x1, y1 = (x0 + 1) % w, (y0 + 1) % h
    return (tex[y0, x0] * (1 - fx) + tex[y0, x1] * fx) * (1 - fy) + (tex[y1, x0] * (1 - fx) + tex[y1, x1] * fx) * fy


def wave_crest_y(u, phase: float, wob: float = 2.5):
    """浪头中线（前沿）的 y：正中最靠前（WAVE_Y0），两头往后弯成月牙，沿浪头有几道小起伏（随相位走）。"""
    return WAVE_Y0 - WAVE_SAG * u**2 + wob * np.sin(5.0 * math.pi * u + phase) * (1 - u**2)


def wave_thick(u, k: float):
    """浪身的厚（像素）：正中最厚，两头收薄；散掉时（k → 1）变薄。"""
    return WAVE_T * (1 - 0.45 * k) * (1 - 0.72 * u**2) ** 0.8 + 2.0


def make_wave_front_loop() -> list[Image.Image]:
    return list(_wave()[0][:4])


def make_wave_front_fade() -> list[Image.Image]:
    return list(_wave()[0][4:])


def make_wave_front_body() -> list[Image.Image]:
    return list(_wave()[1][:4])


def make_wave_front_fade_body() -> list[Image.Image]:
    return list(_wave()[1][4:])


@lru_cache(maxsize=1)
def _wave() -> tuple[tuple[Image.Image, ...], tuple[Image.Image, ...]]:
    """沧浪推出的浪头：横着的一道月牙形水墙，往图里 +y（下）推进，正中最靠前、两头往后弯、越往两头越薄。
    叠加层（白，可染）：前沿一道利的亮浪唇，贴着它一排九个往前卷、再往回勾的浪花卷（浪尖卷起），浪唇后面一带白沫；
    浪身上四道顺着浪唇的水纹，越往后越淡；浪身后沿、两头卷起处缀着泡沫点；前沿溅出水珠，前面浮一层淡水雾。
    水体层（普通混合，墨蓝，不染）：浪唇下最深、往后变浅变薄，前沿一道深色的边，每个浪花卷里一团深的，水纹之间压一道暗。
    0–3 帧循环（12 帧/秒）：浪唇的小起伏顺着浪头走，浪花卷一涨一缩，泡沫翻滚，水珠往前溅；4–6 帧散掉：变薄、碎成一块块、变淡。
    锚点是正中前沿。返回 (叠加 7 帧, 水体 7 帧)。"""
    w, h = WAVE_W, WAVE_H
    cx = w / 2
    rng = np.random.default_rng(9701 + 11)
    tex = W.ptex(rng, ns=28, nt=1024, along=22.0, across=0.6)
    foam_a = V.noise(rng, (h, w), 1.3)
    foam_b = V.noise(rng, (h, w), 1.3)
    big = V.noise(rng, (h, w), 4.0)  # 水体的浓淡、散掉时一块块碎开
    mist_n = V.noise(rng, (h, w), 2.5)
    drops = [(rng.uniform(-0.8, 0.8), rng.uniform(0, 1), rng.uniform(10, 26), rng.uniform(1.2, 2.0)) for _ in range(22)]
    curls = [(xk + rng.uniform(-0.035, 0.035), rng.uniform(0.85, 1.15), rng.uniform(0, 2 * math.pi), int(rng.integers(1 << 30)))
             for xk in np.linspace(-0.8, 0.8, 9)]
    stria = [(0.34, 0.5, 0.0), (0.52, 0.42, 1.3), (0.7, 0.32, 2.6), (0.88, 0.22, 3.9)]  # 浪身上的水纹：位置（× 厚）、亮度、相位
    ink_c = V.col(WATER_INK)
    adds, bodies = [], []
    for i in range(7):
        loop = i < 4
        ph = 2 * math.pi * (i % 4) / 4
        k = 0.0 if loop else (i - 3) / 3  # 散掉的进度 1/3、2/3、1
        X, Y = grid(w, h)
        acc = F.Acc(X, Y)
        pt = F.Paint(X, Y)
        full = (slice(None), slice(None))
        u = (X - cx) / (WAVE_SPAN / 2)
        uc = np.clip(u, -1, 1)
        ends = smoothstep(1.02, 0.84, np.abs(u))  # 两头收掉
        yc = wave_crest_y(uc, ph, wob=2.0) - 6.0 * k
        T = wave_thick(uc, k)
        s = (yc - Y) / T  # 0 = 前沿，1 = 浪身后沿
        nb = bilerp(big, X, Y)
        brk = smoothstep(0.75 * k - 0.15, 0.75 * k + 0.15, 0.5 + 0.22 * nb) if k > 0 else np.ones_like(X)
        mass = smoothstep(-0.05, 0.03, s) * smoothstep(1.08, 0.6, s) * ends
        # ---- 水体（普通混合）
        pt.over(full, F.lerp_col(np.clip(s, 0, 1), WATER), 0.86 * mass * (0.9 + 0.1 * nb) * (1 - 0.55 * k) * brk)
        pt.over(full, ink_c, 0.75 * (1 - 0.6 * k) * ends * brk * np.exp(-(((Y - (yc + 0.3)) / 1.5) ** 2)))  # 前沿一道深色的边
        for sj, _br, eph in stria:  # 水纹之间压一道暗
            yj = wave_crest_y(uc, ph + eph, wob=3.0) - 6.0 * k - (sj + 0.09) * T
            pt.over(full, ink_c, 0.3 * mass * brk * np.exp(-(((Y - yj) / 2.0) ** 2)) * dry(tex, -0.3, X / w * 0.5 + sj, 0.3))
        # ---- 叠加：浪唇、白沫、水纹
        lip = np.exp(-(((Y - (yc - 2.5)) / 2.6) ** 2)) * smoothstep(1.0, 0.78, np.abs(u))
        crest = smoothstep(-0.02, 0.05, s) * smoothstep(0.3, 0.12, s)
        fz = math.cos(ph) * bilerp(foam_a, X, Y) + math.sin(ph) * bilerp(foam_b, X, Y)
        foam = smoothstep(0.1, 0.9, fz)
        acc.add(full, ends * brk * (1 - 0.5 * k) * np.maximum(0.95 * lip, crest * (0.45 + 0.5 * foam)))
        acc.add(full, 0.16 * mass * (1 - np.clip(s, 0, 1)) * brk)  # 浪身淡淡一层
        for sj, br, eph in stria:
            yj = wave_crest_y(uc, ph + eph, wob=3.0) - 6.0 * k - sj * T
            span = 0.94 - 0.25 * sj
            line = np.exp(-(((Y - yj) / 1.7) ** 2)) * smoothstep(span, span - 0.2, np.abs(u))
            acc.add(full, br * (1 - 0.5 * k) * brk * line * dry(tex, 0.3, X / w * 0.6 + sj + 0.07 * (i % 4), 0.3 + 0.3 * k))
        # ---- 浪花卷：从浪身斜着拖上来，到前沿往前卷、再往回勾（图里 y 向下，前 = +y）
        for xk, sc, cph, sd in curls:
            uk = float(np.clip(xk, -1, 1))
            px0 = cx + xk * WAVE_SPAN / 2
            yf = float(wave_crest_y(np.array(uk), ph, wob=2.0)) - 6.0 * k
            Tk = float(wave_thick(np.array(uk), k))
            r0 = 8.5 * sc * (1 + 0.1 * math.sin(ph + cph)) * (1 - 0.35 * k) * (1 - 0.4 * uk**2)
            c = np.array([px0, yf - 0.9 * r0])
            ang = np.linspace(math.pi, -math.pi / 3, 40)
            rad = r0 * (1 - 0.45 * np.linspace(0, 1, 40))
            spiral = c + np.stack([np.cos(ang) * rad, np.sin(ang) * rad], -1)
            tail = np.stack([np.linspace(c[0] - r0 - 0.35 * Tk, c[0] - r0, 16), np.linspace(c[1] - 0.45 * Tk, c[1], 16)], -1)
            pts = np.vstack([tail[:-1], spiral])
            tt = np.linspace(0, 1, len(pts))
            hw = 1.9 * sc * (1 - 0.35 * k) * np.sin(np.pi * np.clip(tt * 1.15, 0, 1)) ** 0.5 + 0.35
            lo, hi = pts.min(0) - 6, pts.max(0) + 6
            sl = acc.window(lo[0], lo[1], hi[0], hi[1])
            cov, _ = V.brush_stroke(X[sl], Y[sl], pts, hw, np.random.default_rng(sd + i // 4), dry=0.3 + 0.3 * k, dry_start=0.5, ss=SS)
            acc.add(sl, 0.9 * (1 - 0.6 * k) * cov * brk[sl])
            hole = np.hypot(X[sl] - c[0], Y[sl] - c[1]) / (0.62 * r0)  # 卷里一团深的
            pt.over(sl, ink_c, 0.5 * (1 - 0.6 * k) * smoothstep(1.0, 0.5, hole) * brk[sl])
        # ---- 泡沫点：挨着浪身后沿、两头卷起处更多；两张噪声转着混，4 帧一循环
        band = np.exp(-(((s - 1.05 - 0.4 * k) / (0.22 + 0.3 * k)) ** 2)) * ends
        band = band + 0.8 * np.exp(-(((s - 0.55) / 0.8) ** 2)) * smoothstep(0.6, 0.92, np.abs(u)) * ends
        thr = 1.5 - 0.4 * band - 0.15 * k
        acc.add(full, (0.8 - 0.35 * k) * smoothstep(thr, thr + 0.25, fz) * np.clip(band, 0, 1))
        # ---- 水雾：前沿前面浮一层淡的，一团团
        mist = np.exp(-(((Y - (yc + 6.0 + 6.0 * k)) / (8.0 + 4.0 * k)) ** 2)) * smoothstep(yc - 4.0, yc + 1.0, Y) * ends
        acc.add(full, 0.3 * (1 - 0.3 * k) * mist * smoothstep(-0.8, 1.2, bilerp(mist_n, X - 3.0 * (i % 4), Y)))
        # ---- 水珠：从浪唇往前（+y）溅出去
        for ux, p0, d1, sz in drops:
            t = ((i % 4) / 4 + p0) % 1.0 if loop else min(1.0, 0.7 + 0.3 * k)
            px = cx + ux * WAVE_SPAN / 2 + 3.0 * t * np.sign(ux)
            py0 = float(wave_crest_y(np.array(ux), ph, wob=2.0)) - 2
            py = py0 + d1 * t
            amp = (math.sin(math.pi * t) ** 0.7) * (1 - 0.7 * k) * (1 - abs(ux) ** 2)
            if amp <= 0.02:
                continue
            sl = acc.window(px - 7, py - 12, px + 7, py + 7)
            acc.add(sl, 0.85 * amp * streak(X[sl], Y[sl], px, py - 6 * (1 - t) - 1, px, py, sz))
        adds.append(F.frame_white(acc.a, 9720 + i))
        bodies.append(pt.image(9730 + i))
    return tuple(adds), tuple(bodies)


def make_wave_trail() -> list[Image.Image]:
    return [_wave_trail()[0]]


def make_wave_trail_body() -> list[Image.Image]:
    return [_wave_trail()[1]]


@lru_cache(maxsize=1)
def _wave_trail() -> tuple[Image.Image, Image.Image]:
    """浪身后的泡沫痕：一条竖着的带子，宽 = 浪宽，游戏沿推进方向拉到走过的长度（锚点在下边正中 = 浪头那一头，往 −y 拉）。
    叠加层（白，可染）：两道宽的泡沫线是浪头两端走过的路，中间翻着一团团泡沫（越靠近浪头越密），几道顺着走向的水纹；
    离浪头越远越淡。水体层（普通混合，墨蓝，不染）：一条淡淡的湿痕，同样越远越淡。返回 (叠加, 水体)。"""
    w, h = TRAIL_W, TRAIL_H
    cx = w / 2
    rng = np.random.default_rng(9741)
    tex = W.ptex(rng, ns=112, nt=1024, along=40.0, across=0.6)
    dots = V.noise(rng, (h, w), 1.4)
    big = V.noise(rng, (h, w), 5.0)
    X, Y = grid(w, h)
    u = (X - cx) / (WAVE_SPAN / 2)
    v = Y / h  # 0 = 远端（上），1 = 浪头这头（下）
    fade = smoothstep(0.0, 0.9, v) ** 1.3 * smoothstep(0.985, 0.92, v)  # 最下面几行淡掉（四边透明，接浪头的地方被浪头盖住）
    a = []
    for su in (-0.84, 0.84):  # 浪头两端走过的两道泡沫线（微微摆）
        uu = u - su - 0.02 * np.sin(v * 9.0 + su)
        lane = np.exp(-((uu * WAVE_SPAN / 2 / 6.0) ** 2))
        a.append(0.7 * lane * fade * dry(tex, np.clip(uu * 15, -1, 1), v * 0.5 + su, 0.25))
    a.append(0.22 * smoothstep(0.86, 0.6, np.abs(u)) * fade**1.2 * dry(tex, np.clip(u, -1, 1), v * 0.6 + 0.3, 0.7))
    dens = smoothstep(0.95, 0.7, np.abs(u)) * fade
    thr = 1.75 - 0.6 * v
    a.append(0.85 * smoothstep(thr, thr + 0.3, bilerp(dots, X, Y)) * dens)
    add = F.frame_white(soft_union(*a), 9745)
    pt = F.Paint(X, Y)
    wet = 0.32 * smoothstep(0.97, 0.72, np.abs(u)) * fade**1.2 * (0.8 + 0.2 * bilerp(big, X, Y))
    pt.over((slice(None), slice(None)), V.col("#24507A"), wet)
    return add, pt.image(9746)


# ============================================================== 青藤：藤、回血的绿光、万木春缠绕

# 试玩第 1 轮第二版（用户要“加粗加强”）：主藤从约 2 单位粗加到约 4 单位，叶子更大更多，加了结节和卷须；
# 画布加高到 512×64（整张高 16 世界单位，第一版 40 像素 = 10 单位），另出普通混合的藤身（*_body：焦墨勾边、绿的藤皮和叶子）。
VINE_W, VINE_H = 512, 64  # 横向拉到连线长度（游戏按 长度 ÷ 画布宽 拉伸），竖向整张 = 16 世界单位（4 像素 / 单位）
VINE_UNITS = 16
VINE_FPS = 8
VINE_HW = 7.6  # 主藤半宽（像素）：粗约 3.8 世界单位
VINE_LEAVES = 16
VINE_NODES = (64.0, 136.0, 204.0, 276.0, 344.0, 414.0, 470.0)  # 结节的 x
BARK = [(0.0, "#1C4527"), (0.5, "#3D8749"), (1.0, "#86CC7E")]  # 藤皮：背光 → 中 → 受光
LEAF = [(0.0, "#2C6A37"), (0.55, "#4FA45A"), (1.0, "#9ADB92")]


def vine_stem_y(x, ph: float, amp: float = 3.2, lam: float = 118.0):
    """藤的中线：两头贴着中线（接主角和妖物），中间几道弯，弯随相位往妖物那头（+x）走。"""
    env = np.clip(np.sin(np.pi * np.clip(x / VINE_W, 0, 1)), 0, 1) ** 0.6
    return VINE_H / 2 + amp * env * np.sin(2 * math.pi * x / lam - ph)


def vine_half_width(x) -> np.ndarray:
    """主藤的半宽：两头收细（接主角、妖物的地方），结节处鼓一点。"""
    hw = VINE_HW * (0.3 + 0.7 * smoothstep(4.0, 44.0, x) * smoothstep(VINE_W - 4.0, VINE_W - 34.0, x))
    for xn in VINE_NODES:
        hw = hw + 1.7 * np.exp(-(((x - xn) / 4.5) ** 2))
    return hw


def make_vine() -> list[Image.Image]:
    return list(_vine()[0])


def make_vine_body() -> list[Image.Image]:
    return list(_vine()[1])


@lru_cache(maxsize=1)
def _vine() -> tuple[tuple[Image.Image, ...], tuple[Image.Image, ...]]:
    """青藤：主角（左端）连到妖物（右端，锚点）的一根粗藤（约 4 世界单位），带几道弯，七个结节（鼓一点、一道横纹），
    结节上长卷须（往妖物那头斜出去、梢上打卷）；两侧交替十六片大叶，叶尖朝妖物那头（+x），一道叶脉；两端在中线上收细。
    叠加层（白，可染）：藤上受光的一边一道亮边、藤皮的笔毛纹、结节的亮环，叶边亮、叶脉亮，卷须一线亮，外面一圈淡光。
    藤身层（普通混合，不染）：焦墨勾边，绿的藤皮（上亮下暗）、深色的结节横纹，叶子绿、叶脉深，卷须焦墨。
    3 帧循环（8 帧/秒）：藤上的弯往妖物那头走，叶子翻一翻、卷须摆一摆。返回 (叠加 3 帧, 藤身 3 帧)。"""
    w, h = VINE_W, VINE_H
    rng = np.random.default_rng(9761)
    tex = W.ptex(rng, ns=16, nt=1024, along=30.0, across=0.6)
    leaves = []
    for k in range(VINE_LEAVES):
        x0 = 40 + (w - 84) * (k + 0.5 + rng.uniform(-0.2, 0.2)) / VINE_LEAVES
        side = -1.0 if k % 2 == 0 else 1.0
        leaves.append((x0, side, rng.uniform(18.0, 24.0), rng.uniform(8.5, 10.5), math.radians(rng.uniform(30, 40)), rng.uniform(0, 2 * math.pi),
                       int(rng.integers(1 << 30))))
    tendrils = []
    for j, xn in enumerate(VINE_NODES[1:-1]):
        side = 1.0 if j % 2 == 0 else -1.0
        tendrils.append((xn, side, rng.uniform(15.0, 19.0), rng.uniform(0, 2 * math.pi), int(rng.integers(1 << 30))))
    ink_c, vein_c = F.JIAO, V.col("#1E4A27")
    adds, bodies = [], []
    for i in range(3):
        ph = 2 * math.pi * i / 3
        X, Y = grid(w, h)
        acc = F.Acc(X, Y)
        pt = F.Paint(X, Y)
        full = (slice(None), slice(None))
        ends = smoothstep(2.0, 14.0, X) * smoothstep(w - 2.0, w - 12.0, X)
        ys = vine_stem_y(X, ph)
        hw = vine_half_width(X)
        d = Y - ys
        nd = np.clip(d / hw, -1.5, 1.5)
        # ---- 叶子（先画：叶根压在藤下面）
        for x0, side, L, wd, ang0, lph, sd in leaves:
            y0 = float(vine_stem_y(np.array(x0), ph))
            ang = side * (ang0 + math.radians(10.0) * math.sin(ph + lph))
            uv = np.array([math.cos(ang), math.sin(ang)])  # 图里 y 向下：side=-1 朝右上
            base = np.array([x0, y0])
            tip = base + uv * L
            lo, hi = np.minimum(base, tip) - wd - 3, np.maximum(base, tip) + wd + 3
            sl = acc.window(lo[0], lo[1], hi[0], hi[1])
            cov, dd, along = F.almond_field(X[sl], Y[sl], base, tip, wd * (0.85 + 0.15 * math.cos(ph + lph)), bulge=0.4)
            vperp = -(X[sl] - base[0]) * uv[1] + (Y[sl] - base[1]) * uv[0]
            rim = smoothstep(1.3, 0.0, np.abs(dd)) * (dd < 0.6)
            rib = smoothstep(0.8, 0.25, np.abs(vperp)) * (along < 0.88)
            pt.over(sl, ink_c, 0.9 * smoothstep(0.45, -0.45, dd - 1.2))
            lit = smoothstep(-0.6, 0.8, -vperp * side / max(wd * 0.5, 1e-6))  # 朝上的半片亮
            colr = F.lerp_col(0.3 + 0.35 * along + 0.3 * lit, LEAF)
            colr = colr + (vein_c - colr) * (0.75 * rib)[..., None]
            pt.over(sl, colr, cov)
            acc.add(sl, np.clip(0.28 * cov + 0.85 * rim + 0.45 * rib * cov, 0, 1))
        # ---- 卷须：从结节往妖物那头斜出去，梢上打卷
        for xn, side, L, tph, sd in tendrils:
            yn = float(vine_stem_y(np.array(xn), ph))
            root = (xn + 2.0, yn + side * (VINE_HW - 1.0))
            a0 = side * math.radians(48.0 + 8.0 * math.sin(ph + tph))
            pts = F.curl_blade(root, a0, L, side * 0.2, side * 7.0, 9.0, n=60)
            tt = np.linspace(0, 1, len(pts))
            hwt = 1.15 * (1 - 0.6 * tt) + 0.3
            lo, hi = pts.min(0) - 4, pts.max(0) + 4
            sl = acc.window(lo[0], lo[1], hi[0], hi[1])
            ink, _ = V.brush_stroke(X[sl], Y[sl], pts, hwt + 0.6, np.random.default_rng(sd), dry=0.2, dry_start=0.7, ss=SS)
            pt.over(sl, ink_c, 0.9 * ink)
            cv, _ = F.smooth_stroke(X[sl], Y[sl], pts, hwt * 0.55)
            acc.add(sl, 0.75 * cv)
        # ---- 主藤
        cov = smoothstep(hw + 0.5, hw - 0.5, np.abs(d)) * ends
        grain_ = dry(tex, np.clip(nd, -1, 1), X / w * 0.7 + 0.1 * i, 0.22)  # 藤皮上顺着走的笔毛纹
        pt.over(full, ink_c, 0.92 * smoothstep(hw + 1.6 + 0.5, hw + 1.6 - 0.5, np.abs(d)) * ends)
        bark = F.lerp_col(np.clip(0.55 - 0.42 * nd, 0, 1), BARK)
        bark = bark + (V.col(BARK[0][1]) - bark) * (0.35 * (1 - grain_))[..., None]
        pt.over(full, bark, cov)
        top = smoothstep(1.6, 0.4, np.abs(d + hw - 1.6))  # 受光的上沿
        acc.add(full, cov * (0.4 + 0.2 * grain_) + 0.75 * top * ends)
        acc.add(full, 0.12 * np.exp(-((d / 13.0) ** 2)) * ends)
        for xn in VINE_NODES:  # 结节：一道深的横纹 + 上半一个亮点
            ring = np.exp(-(((X - xn) / 1.3) ** 2)) * cov
            pt.over(full, ink_c, 0.75 * ring)
            acc.add(full, 0.55 * np.exp(-(((X - xn - 2.5) / 2.0) ** 2)) * smoothstep(0.1, -0.6, nd) * cov)
        adds.append(F.frame_white(acc.a, 9765 + i))
        bodies.append(pt.image(9768 + i))
    return tuple(adds), tuple(bodies)


PULSE_W, PULSE_H = 128, 48
PULSE_HEAD = (104.0, 24.0)


def make_vine_pulse() -> list[Image.Image]:
    """每跳回血：一颗绿光从妖物沿藤流回主角。头朝 +x（锚点在头上），身后拖一道尾，尾上几点碎光；
    3 帧循环（24 帧/秒）：头一明一暗、碎光往后掉。叠加，白色可染（染青绿）。第二版跟着藤加粗放大了一圈。"""
    w, h = PULSE_W, PULSE_H
    hx, hy = PULSE_HEAD
    rng = np.random.default_rng(9771)
    motes = [(rng.uniform(12, 76), rng.uniform(-5, 5), rng.uniform(1.2, 1.9), rng.uniform(0, 1)) for _ in range(9)]
    out = []
    for i in range(3):
        X, Y = grid(w, h)
        a = []
        r = np.hypot(X - hx, Y - hy)
        pulse = [1.0, 0.86, 0.93][i]
        a.append(pulse * smoothstep(7.4, 5.6, r))
        a.append(0.5 * pulse * np.exp(-((r / 13.0) ** 2)))
        tail, _ = needle(X, Y, hx, hy, math.pi, 88.0, 4.8, w1=0.3, taper=0.8)
        u = np.clip((hx - X) / 88.0, 0, 1)
        a.append(0.7 * tail * (1 - u) ** 0.8)
        for dx, dy, sz, p0 in motes:
            t = (i / 3 + p0) % 1.0
            x = hx - dx - 12 * t
            a.append(0.75 * (1 - t) * (1 - dx / 94) * F.dot(X, Y, x, hy + dy * (0.5 + t), sz))
        out.append(F.frame_white(soft_union(*a), 9775 + i))
    return out


BIND_SIZE = 192
BIND_R = 56.0  # 缠绕圈的横向半径（像素）≈ 妖物半径；游戏按妖物半径缩放


def make_vine_bind() -> list[Image.Image]:
    return list(_vine_bind()[0])


def make_vine_bind_body() -> list[Image.Image]:
    return list(_vine_bind()[1])


@lru_cache(maxsize=1)
def _vine_bind() -> tuple[tuple[Image.Image, ...], tuple[Image.Image, ...]]:
    """万木春缠绕：两根粗藤从妖物脚下两边长出来，各自绕着身子往上盘一圈多（盘的圈按地面透视压扁，前半圈亮、后半圈暗，
    半径中间鼓、带一点抖），交叉着把它裹住，梢上卷一个小卷，沿途冒出几片大叶。0–2 帧长上去、盘紧，第 3 帧裹住（留着到缠绕结束）。
    叠加层（白，可染）；藤身层（普通混合，不染）：焦墨勾边、绿的藤皮，后半圈暗、淡。锚点是妖物脚底；radius_px 是缠绕圈的横向半径。
    第二版藤粗加了一倍（同主藤），叶子放大。返回 (叠加 4 帧, 藤身 4 帧)。"""
    size = BIND_SIZE
    cx, cy = size / 2, size * 0.72
    rng = np.random.default_rng(9781)
    grow = [0.38, 0.72, 1.0, 1.0]
    tight = [1.12, 1.05, 1.0, 0.96]  # 盘紧
    strands = []
    for sd in range(2):
        jit = rng.uniform(-1, 1, 6)
        strands.append(dict(th0=math.pi * (0.15 + sd) + rng.uniform(-0.3, 0.3), turns=1.35 + 0.15 * sd, height=84.0 - 10 * sd,
                            jit=jit, seed=9785 + sd, sign=1.0 if sd == 0 else -1.0))
    ink_c, vein_c = F.JIAO, V.col("#1E4A27")
    adds, bodies = [], []
    for i in range(4):
        X, Y = grid(size, size)
        acc = F.Acc(X, Y)
        pt = F.Paint(X, Y)
        full = (slice(None), slice(None))
        parts = []  # (是不是前半圈, 画法)：先画所有后半圈，再画前半圈
        for st in strands:
            n = 240
            t = np.linspace(0, grow[i], n)
            th = st["th0"] + st["sign"] * 2 * math.pi * st["turns"] * t
            wob = sum(st["jit"][k] * np.sin((k + 2) * math.pi * t + k) for k in range(6)) * 0.05
            rr = BIND_R * tight[i] * (0.82 + 0.22 * np.sin(math.pi * np.clip(t * 1.1, 0, 1))) * (1 + wob)
            pts = np.stack([cx + rr * np.cos(th), cy - st["height"] * t ** 0.9 + rr * np.sin(th) * F.FLAT * 0.6], -1)
            if grow[i] >= 0.99:  # 梢上卷一个小卷：顺着梢的方向绕半径 8 的圆弧，越绕越紧
                end, d_end = pts[-1], pts[-1] - pts[-2]
                ang0 = math.atan2(d_end[1], d_end[0])
                sg = st["sign"]
                c0 = end + 8.0 * np.array([math.cos(ang0 + sg * math.pi / 2), math.sin(ang0 + sg * math.pi / 2)])
                a_ = np.linspace(0.0, 4.0, 30)[1:]
                start = ang0 - sg * math.pi / 2
                cur = c0 + 8.0 * (1 - 0.18 * a_ / 4)[:, None] * np.stack([np.cos(start + sg * a_), np.sin(start + sg * a_)], -1)
                pts = np.vstack([pts, cur])
                th = np.concatenate([th, np.full(len(cur), th[-1])])
            m = len(pts)
            tt = np.linspace(0, 1, m)
            hw = (5.6 - 3.0 * tt) * (0.55 + 0.45 * np.clip(tt * 8, 0, 1))
            front = np.sin(th) > -0.15  # 前半圈（靠镜头）亮
            cov, f = V.brush_stroke(X, Y, pts, hw, np.random.default_rng(st["seed"]), dry=0.2, dry_start=0.75, ss=SS)
            ink, _ = V.brush_stroke(X, Y, pts, hw + 1.3, np.random.default_rng(st["seed"] + 7), dry=0.12, dry_start=0.8, ss=SS)
            idx = np.clip((f["t"] * (m - 1)).round().astype(int), 0, m - 1)
            fr = front[idx]
            nd = np.clip(f["perp"] / f["hw"], -1, 1)
            acc.add(full, np.where(fr, 0.95, 0.38) * cov * (0.75 + 0.25 * smoothstep(0.2, -0.8, nd)))
            parts.append((False, ink, cov, nd, fr))
            leaves = []
            for j in range(3):  # 叶子
                tj = (j + 0.55) / 3.3
                if tj > grow[i] - 0.05:
                    continue
                p = int(tj / grow[i] * (n - 1))
                base = pts[p]
                ang = th[p] + st["sign"] * math.pi / 2 + (0.5 if j % 2 else -0.5)
                uv = np.array([math.cos(ang), math.sin(ang) * 0.75])
                uv /= np.linalg.norm(uv)
                L = 18.0 * min(1.0, (grow[i] - tj) * 3 + 0.45)
                tip = base + uv * L
                sl = acc.window(min(base[0], tip[0]) - 10, min(base[1], tip[1]) - 10, max(base[0], tip[0]) + 10, max(base[1], tip[1]) + 10)
                cv, dd, along = F.almond_field(X[sl], Y[sl], base, tip, 8.5, bulge=0.4)
                rim = smoothstep(1.3, 0.0, np.abs(dd)) * (dd < 0.6)
                vperp = -(X[sl] - base[0]) * uv[1] + (Y[sl] - base[1]) * uv[0]
                rib = smoothstep(0.8, 0.25, np.abs(vperp)) * (along < 0.88)
                acc.add(sl, (0.9 if front[p] else 0.45) * np.clip(0.3 * cv + 0.85 * rim + 0.35 * rib * cv, 0, 1))
                leaves.append((sl, cv, dd, along, rib, bool(front[p])))
            parts.append((True, leaves))
        # 藤身：后半圈（暗、淡）先画，前半圈后画；叶子跟着它长在哪半圈
        for want_front in (False, True):
            for part in parts:
                if part[0]:
                    for sl, cv, dd, along, rib, fr_ in part[1]:
                        if fr_ != want_front:
                            continue
                        k_ = 1.0 if fr_ else 0.55
                        pt.over(sl, ink_c, k_ * 0.9 * smoothstep(0.45, -0.45, dd - 1.2))
                        colr = F.lerp_col(0.35 + 0.4 * along, LEAF) * (1.0 if fr_ else 0.7)
                        colr = colr + (vein_c - colr) * (0.75 * rib)[..., None]
                        pt.over(sl, colr, k_ * cv)
                    continue
                _, ink, cov, nd, fr = part
                sel = fr if want_front else ~fr
                k_ = 1.0 if want_front else 0.55
                pt.over(full, ink_c, k_ * 0.92 * ink * sel)
                bark = F.lerp_col(np.clip(0.55 - 0.42 * nd, 0, 1), BARK) * (1.0 if want_front else 0.7)
                pt.over(full, bark, k_ * cov * sel)
        adds.append(F.frame_white(acc.a, 9790 + i))
        bodies.append(pt.image(9795 + i))
    return tuple(adds), tuple(bodies)


