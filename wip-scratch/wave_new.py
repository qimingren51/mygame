# ============================================================== 沧浪：浪头、泡沫痕

WAVE_W, WAVE_H = 448, 128
WAVE_SPAN = 432.0  # 浪头横向的宽（像素）≈ 画布宽；游戏按 2 × 半宽 等比缩放（1080p 下 168 单位一比一）
WAVE_Y0 = 88.0  # 浪头正中的前沿（锚点）；往图里 +y（下）推进，两头往后（上）弯
WAVE_SAG = 44.0  # 两头比正中落后多少像素（月牙）
WAVE_FPS = 12
TRAIL_W, TRAIL_H = 448, 256


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


def make_wave_front() -> list[Image.Image]:
    """沧浪推出的浪头：横着的一道月牙形浪，往图里 +y（下）推进，正中最靠前、两头往后弯、越往两头越细。
    前沿一道利的亮线（卷起的浪唇），往后是一条起飞白的浪身，身后碎成泡沫点；浪唇上溅起几粒水珠。
    0–3 帧循环（12 帧/秒）：浪唇上的小起伏顺着浪头走，泡沫翻滚，水珠往前溅；4–6 帧散掉：浪身碎成泡沫团、变淡。
    白色，可染（游戏里染水色）。锚点是正中前沿。"""
    w, h = WAVE_W, WAVE_H
    cx = w / 2
    rng = np.random.default_rng(9701 + 11)
    tex = W.ptex(rng, ns=24, nt=1024, along=18.0, across=0.7)
    foam_a = V.noise(rng, (64, 256), 2.2)
    foam_b = V.noise(rng, (64, 256), 2.2)
    drops = [(rng.uniform(-0.8, 0.8), rng.uniform(0, 2 * math.pi), rng.uniform(6, 16), rng.uniform(1.1, 1.9)) for _ in range(16)]
    out = []
    for i in range(7):
        loop = i < 4
        ph = 2 * math.pi * (i % 4) / 4  # 循环帧的相位
        k = 0.0 if loop else (i - 3) / 3  # 散掉的进度 1/3、2/3、1
        X, Y = grid(w, h)
        acc = F.Acc(X, Y)
        full = (slice(None), slice(None))
        u = (X - cx) / (WAVE_SPAN / 2)
        uc = np.clip(u, -1, 1)
        yc = wave_crest_y(uc, ph) - 6.0 * k  # 散的时候浪身往后退一点
        T = (30.0 - 8.0 * k) * (1 - 0.72 * uc**2) ** 0.7  # 浪身厚（往后）
        s = (yc - Y) / np.maximum(T, 1.0)  # 0 = 前沿，1 = 浪身后沿
        ends = smoothstep(1.02, 0.84, np.abs(u))  # 两头收掉
        # 浪唇：前沿一道亮线
        lip = np.exp(-(((Y - (yc - 2.2)) / 2.0) ** 2)) * smoothstep(1.0, 0.7, np.abs(u))
        # 浪身：前沿最亮往后淡，顺着浪头起飞白（笔毛纹沿 x）
        body = smoothstep(-0.06, 0.04, s) * smoothstep(1.0, 0.35, s) * np.exp(-1.2 * np.clip(s, 0, None))
        tt = X / w * 0.9 + 0.06 * (i % 4)
        dryk = 0.12 + 0.3 * np.clip(s, 0, 1) ** 1.5 + 0.35 * k + 0.25 * np.abs(uc) ** 3
        m = dry(tex, np.clip(2 * s - 1, -1, 1), tt, dryk)
        acc.add(full, (1 - 0.75 * k) * ends * np.maximum(0.95 * lip * (1 - 0.6 * k), 0.85 * body * m))
        # 泡沫：浪身后面一片碎点（两张噪声转着混，4 帧一循环）
        a_ = math.cos(ph) if loop else math.cos(ph) * (1 - 0.3 * k)
        b_ = math.sin(ph)
        nz = a_ * bilerp(foam_a, X / 448 * 256, Y / 128 * 64) + b_ * bilerp(foam_b, X / 448 * 256, Y / 128 * 64)
        behind = smoothstep(0.55, 1.0, s) * smoothstep(2.6 + 1.2 * k, 1.4, s)
        thr = 0.9 + 0.5 * np.clip(s - 1, 0, None) + 0.6 * k
        foam = smoothstep(thr, thr + 0.35, nz) * behind * ends
        acc.add(full, (0.7 - 0.45 * k) * foam)
        if not loop:  # 散掉：浪身碎成一团团泡沫
            nz2 = bilerp(foam_b, X / 448 * 256 + 37, Y / 128 * 64 + 11)
            clumps = smoothstep(1.2 - 0.5 * k, 1.6 - 0.5 * k, nz2) * smoothstep(-0.3, 0.2, s) * smoothstep(1.6, 0.8, s) * ends
            acc.add(full, (0.55 - 0.25 * k) * clumps)
        # 水珠：从浪唇往前上方溅出去
        for ux, p0, d1, sz in drops:
            t = ((i % 4) / 4 + p0 / (2 * math.pi)) % 1.0 if loop else min(1.0, 0.75 + 0.25 * k)
            px = cx + ux * WAVE_SPAN / 2 + 4.0 * t * np.sign(ux)
            py0 = float(wave_crest_y(np.array(ux), ph)) - 2
            py = py0 + d1 * t - 10.0 * t * (1 - t)
            amp = (math.sin(math.pi * t) ** 0.7) * (1 - 0.7 * k) * (1 - abs(ux) ** 2)
            if amp <= 0.02:
                continue
            sl = acc.window(px - 6, py - 10, px + 6, py + 6)
            acc.add(sl, 0.85 * amp * streak(X[sl], Y[sl], px, py - 5 * (1 - t), px, py, sz))
        out.append(F.frame_white(acc.a, 9720 + i))
    return out


def make_wave_trail() -> list[Image.Image]:
    """浪身后的泡沫痕：一条竖着的带子，宽 = 浪宽，游戏沿推进方向拉到走过的长度（锚点在下边正中 = 浪头那一头，往 −y 拉）。
    两条亮一些的泡沫线是浪头两端走过的路，中间散着泡沫点和顺着走向的细水纹；离浪头越远越淡（锚点那头最亮）。白色，可染。"""
    w, h = TRAIL_W, TRAIL_H
    cx = w / 2
    rng = np.random.default_rng(9741)
    tex = W.ptex(rng, ns=48, nt=1024, along=30.0, across=0.6)
    foam = V.noise(rng, (128, 224), 1.8)
    X, Y = grid(w, h)
    u = (X - cx) / (WAVE_SPAN / 2)
    v = Y / h  # 0 = 远端（上），1 = 浪头这头（下）
    fade = smoothstep(0.0, 0.85, v) ** 1.4 * smoothstep(1.0, 0.94, v)
    side = smoothstep(1.0, 0.82, np.abs(u))
    a = []
    for su in (-0.9, 0.9):  # 浪头两端走过的两道泡沫线
        lane = np.exp(-(((u - su) * WAVE_SPAN / 2 / 5.0) ** 2))
        a.append(0.55 * lane * fade * dry(tex, np.clip((u - su) * 20, -1, 1), Y / h * 0.6 + su, 0.3))
    streaks = 0.28 * side * fade * dry(tex, np.clip(u, -1, 1), Y / h * 0.5 + 0.3, 0.55)
    a.append(streaks)
    nz = bilerp(foam, X / w * 224, Y / h * 128)
    a.append(0.6 * smoothstep(1.1, 1.5, nz) * side * fade)
    return [F.frame_white(soft_union(*a), 9745)]


