def hstroke(c: Canvas, x0, x1, yc, hw, *, band, seed, head_len, tail_len, slant=0.25, blunt=3.0, taper=0.55, lift=0.12,
            dry=0.0, dry_tail=0.75, head_dry=0.0, edge_soft=0.7, rough=0.06, streak=True, tail_round=False):
    """一笔横画（按钮、提示条、进度条……）。拉伸带 band=(bx0, bx1) 内的一切只随 y 变：上下沿是直的，笔毛纹是
    横跨方向的一维纹，所以拉多长都不变形。起笔（左）和收笔（右）的变化都在带外：
      起笔：笔锋斜落（slant：下沿比上沿晚 slant·hw 起笔），方中带圆（blunt：超椭圆指数，越大越方）；
      收笔：笔肚收细（taper）、略向上提（lift），笔毛从两边先干、一根根断开（dry_tail）；head_dry>0 时起笔也毛。
    返回 dict：cov 覆盖度（含飞白）、shape 外形、s 横向坐标（-1 上沿 … 1 下沿）、T 笔毛纹、edge 到边缘的有向距离。"""
    rng = np.random.default_rng(seed)
    bx0, bx1 = band
    assert x0 + head_len <= bx0 + 1e-6 and x1 - tail_len >= bx1 - 1e-6, "笔头伸进了拉伸带"
    X, Y, x = c.X, c.Y, c.xs
    th = smoothstep(x0 + head_len, x0, x)
    tt = smoothstep(x1 - tail_len, x1, x)
    hwx = hw * (1 - (1 - taper) * tt**1.6)
    ycx = yc - lift * hw * tt**2
    v = Y - ycx[None, :]
    sv = np.clip(v / hwx[None, :], -1, 1)
    cap = np.maximum(th, tt)[None, :]
    n2 = noise(rng, X.shape, (5.0 * c.ss, 1.6 * c.ss))
    hwb = hwx[None, :] * (1 + rough * cap * n2)
    xl = x0 + slant * hw * (sv + 1) * 0.5
    over_l = np.maximum(xl - X, 0)
    over_r = np.maximum(X - x1, 0) * (1.0 if tail_round else 1.5)
    pw = np.where(over_l > 0, blunt, 2.0)
    ov = over_l + over_r
    dist = (np.abs(v) ** pw + ov**pw) ** (1.0 / pw)
    soft = edge_soft + c.aa
    shape = smoothstep(hwb + soft, hwb - soft, dist)
    s = np.clip(v / hwb, -1, 1)
    T1 = samp1(tex1(rng, 96, 1.3), s)
    z1 = (T1 - 0.5) / 0.29
    nl = noise(rng, X.shape, (11.0 * c.ss, 0.45 * c.ss))
    nsh = noise(rng, X.shape, (2.5 * c.ss, 0.6 * c.ss))
    T2 = rank01(0.8 * z1 + 0.55 * nl + 0.3 * nsh)
    wt = smoothstep(0.0, 0.35, np.maximum(tt, th * (head_dry > 0))[None, :])
    T = T1 * (1 - wt) + T2 * wt
    edgek = 0.5 + 0.5 * np.abs(s) ** 2  # 两边的笔毛先干
    d = dry + ((dry_tail - dry) * tt[None, :] ** 1.3 + head_dry * th[None, :] ** 1.6) * edgek
    ink = smoothstep(d - 0.08, d + 0.08, T) if streak else 1.0
    return {"cov": shape * ink, "shape": shape, "s": s, "T": T, "edge": dist - hwb}


def loop(c: Canvas, x0, y0, x1, y1, r, *, center, hw, seed, rgb, alpha=1.0, press=0.3, dry=0.0, seam=None, wobble=0.0,
         soft=0.5, tone=None, tone_k=0.0, slices=None):
    """沿圆角矩形一笔绕一圈的边框：顺时针，从左上角起笔，绕回左上角收笔，中间留个小缺口，收笔飞白（同图标的圆相）。
    hw = (上, 右, 下, 左) 半宽，转角处 press 加粗（折笔顿一下）。
    seam = (起笔位置, 缺口, 起笔长, 收笔长, 收笔粗细比, 收笔干度)，位置用绕行坐标 q（顶边直线段左端为 0，
    顺时针为正，左上圆弧和左边为负）。slices=(左, 上) 给出时检查起收笔都在左上角的切片以内。
    wobble>0 只给固定尺寸的贴图：整圈的粗细起伏和沿笔的飞白；拉伸用的贴图 wobble=0，直边上只随离边距离变化。"""
    rng = np.random.default_rng(seed)
    d, th = rrect(c, x0, y0, x1, y1, r)
    p, per = rrect_perim(c, x0, y0, x1, y1, r)
    q = np.where(p > per / 2, p - per, p)
    hwv = side_value(th, *hw, press=press)
    if wobble:
        hwv = hwv * (1 + wobble * W.sample1(pnoise(rng, 512, 10.0), p / per))
    v = d - center
    s = np.clip(v / hwv, -1, 1)
    T1 = samp1(tex1(rng, 64, 1.0), s)
    nt = int(per * c.ss) + 8
    tex = noise(rng, (48, nt), (10.0 * c.ss, 0.5))
    T2 = rank01(0.8 * (T1 - 0.5) / 0.29 + 0.6 * samp2(tex, s, (q + per / 2) * c.ss))
    edgek = 0.5 + 0.5 * s**2
    if seam is None:
        cov = smoothstep(hwv + soft + c.aa, hwv - soft - c.aa, np.abs(v))
        T = T2 if wobble else T1
        cov = cov * smoothstep(dry - 0.07, dry + 0.07, T)
    else:
        qs, gap, hl, tl, taper, dry_tail = seam
        qe = qs - gap
        if slices is not None:
            arc = r * math.pi / 2
            assert qs + hl <= slices[0] - x0 - r + 1e-6 and qe - tl >= -(arc + slices[1] - y0 - r) - 1e-6, "起收笔越过了切片"
        hA = hwv * (1 + 0.28 * bump(q, qs + 0.4 * hl, 0.6 * hl))
        oA = np.maximum(qs - q, 0) * 1.1
        covA = smoothstep(hA + soft + c.aa, hA - soft - c.aa, np.hypot(v, oA))
        ttl = smoothstep(qe - tl, qe, q)
        hB = hwv * (1 - (1 - taper) * ttl**1.5)
        oB = np.maximum(q - qe, 0) * 1.6
        covB = smoothstep(hB + soft + c.aa, hB - soft - c.aa, np.hypot(v, oB))
        TA = T2 if wobble else T1
        wt = smoothstep(0.0, 0.3, ttl)
        TB = TA * (1 - wt) + T2 * wt
        dB = dry + (dry_tail - dry) * ttl**1.3 * edgek
        covA = covA * smoothstep(dry - 0.07, dry + 0.07, TA) * (q > qe)  # 起笔那段只在缺口之后
        covB = covB * smoothstep(dB - 0.08, dB + 0.08, TB) * (q < qs)
        cov = np.maximum(covA, covB)
        T = np.where(q >= qs, TA, TB)
    color = rgb if tone is None else mixc(rgb, tone, np.clip(tone_k * (0.62 - T) * 1.6, 0, 1))
    c.over(color, cov * alpha)
    return d, th, cov, s
