# ============================================================== 面板


def make_panel() -> Image.Image:
    """毛边宣纸大面板：512²，左上角 176、其余 80 的切片，中间 256² 一个周期（中间和四边都平铺）。
    纸纹、毛边、旧纸边都是对齐平铺区的周期场；淡墨晕染只在左上角里（176² 以内淡出）。"""
    Wd = H = 512
    L, T, R, B = 176, 176, 80, 80
    Cx, Cy = Wd - L - R, H - T - B
    ss = 2
    c = Canvas(Wd, H, 101, ss)
    rng = c.rng
    m = 13
    per = lambda f: c.periodic(f, L, T)  # noqa: E731
    pd = per(paper_field(rng, Cy, Cx, ss, grain=0.015))
    n_fine = per(noise(rng, (Cy * ss, Cx * ss), 1.6 * ss))
    n_mid = per(noise(rng, (Cy * ss, Cx * ss), 6.0 * ss))
    n_big = per(noise(rng, (Cy * ss, Cx * ss), 22.0 * ss))
    hair = per(fibres(rng, Cy, Cx, ss, 260, (3, 9), (0.4, 0.9), 0.35, 0.12))
    d, _ = rrect(c, m, m, Wd - m, H - m, 8)
    dd = d + 2.4 * n_big + 1.1 * n_mid + 0.5 * n_fine  # 撕开的纸边：大的起伏 + 细碎的毛
    body = smoothstep(0.7, -0.7, dd)
    # 纸边最外 3 px 薄而半透（撕口处纤维稀疏），外面再伸出几根纤维
    thin = smoothstep(-3.5, 0.0, dd)
    body = body * (1.0 - 0.45 * thin * np.clip(0.6 + 0.5 * n_fine, 0, 1))
    fringe = np.clip(hair * 1.2, 0, 0.85) * smoothstep(6.5, 1.0, dd) * (dd > -1.0)
    a = 1 - (1 - body) * (1 - fringe)
    rgb = paper_rgb(pd)
    # 旧纸边：靠边 20 px 内略黄略暗
    age = 0.5 * np.exp(np.minimum(dd, 0) / 8.0) * np.clip(0.75 + 0.35 * n_mid, 0, 1.2)
    rgb = mixc(rgb, mixc(PAPER_SH, ZHESHI, 0.12), np.clip(age, 0, 1))
    c.over(rgb, a)
    # 左上角的淡墨晕染：几团湿墨从角上洇进来，边上积一道干痕，墨落进纸纹里
    X, Y = c.X, c.Y
    wn = np.clip(noise(np.random.default_rng(102), X.shape, 14.0 * ss), -1.6, 1.6)
    wn2 = noise(np.random.default_rng(103), X.shape, 4.0 * ss)
    lobes = ((m - 4, m - 4, 150.0), (m + 92, m - 2, 52.0), (m - 2, m + 96, 58.0))
    f = np.full(X.shape, 9.0)
    for lx, ly, lr in lobes:
        f = np.minimum(f, np.hypot(X - lx, Y - ly) / lr)
    f = f * (1 + 0.10 * wn + 0.035 * wn2)
    inner = smoothstep(1.0, 0.15, f)
    rim = np.exp(-(((f - 0.965) / 0.03) ** 2)) * np.clip(0.35 + 0.65 * smoothstep(-0.8, 0.6, wn2), 0, 1)
    gran = np.clip(0.8 + 1.1 * pd, 0.3, 1.4)
    wash = (0.26 * inner**1.15 + 0.16 * rim * (f < 1.1)) * gran
    wash = wash * smoothstep(L - 2, L - 30, X) * smoothstep(T - 2, T - 30, Y) * body
    c.over(mixc(ZHONG, HUAQING, 0.18), wash)
    return finish(c)


INK_RIM = mixc(DAN, QING, 0.3)  # 夜色上的边框墨：淡墨，夜里看得见、纸上也不刺眼


def make_panel_dark() -> Image.Image:
    """夜墨面板（HUD 底板、提示框）：128×96，切片 32，中间与四边拉伸。约 86% 不透明，
    一笔淡墨干笔边：左上角起笔，绕一圈回到左上角收笔，留一个小缺口。"""
    Wd, H, m, r, L = 128, 96, 4, 12, 32
    c = Canvas(Wd, H, 201, 4)
    d, th = rrect(c, m, m, Wd - m, H - m, r)
    fill = smoothstep(0.6 + c.aa, -0.6 - c.aa, d)
    pool = smoothstep(-7.0, -1.5, d)  # 墨在边上积得浓一点
    c.over(mixc(NIGHT_INK, JIAO, 0.35 * pool), fill * (0.85 + 0.09 * pool))
    loop(c, m, m, Wd - m, H - m, r, center=-2.2, hw=(1.35, 1.05, 1.55, 1.15), seed=202, rgb=INK_RIM, alpha=0.7,
         press=0.55, dry=0.04, seam=(-5.0, 7.0, 13.0, 20.0, 0.3, 0.75), tone=ZHONG, tone_k=0.5, slices=(L, L))
    return finish(c, band_x=(L, L), band_y=(L, L))


def make_overlay() -> Image.Image:
    """全屏压暗：960×540（整张拉伸到全屏），中间较透，四周是墨云。"""
    Wd, H = 960, 540
    c = Canvas(Wd, H, 301, 1)
    rng = c.rng
    u = (c.X - Wd / 2) / (Wd / 2)
    v = (c.Y - H / 2) / (H / 2)
    p = 2.4
    rr = (np.abs(u) ** p + np.abs(v) ** p) ** (1 / p)
    cloud = V.fbm(rng, c.X.shape, (90.0, 40.0, 16.0), (0.5, 0.35, 0.2))
    fine = noise(rng, c.X.shape, 5.0)
    e = rr + 0.10 * cloud + 0.02 * fine
    a = 0.40 + 0.52 * smoothstep(0.45, 1.25, e)
    # 墨云：边上一团团更浓的墨，带一道湿边的水痕
    blob = smoothstep(0.15, 0.9, cloud) * smoothstep(0.55, 1.15, rr)
    a = a + 0.10 * blob
    tide = np.exp(-(((cloud - 0.55) / 0.05) ** 2)) * smoothstep(0.6, 1.1, rr)
    a = np.clip(a + 0.06 * tide, 0, 0.96)
    rgb = mixc(mixc(JIAO, NIGHT, 0.4), JIAO, 0.25 * blob)
    c.over(rgb * 0.75, a)
    return finish(c, clear=False, dither=302)


# ============================================================== 卡片

CARD_W, CARD_H, CARD_SL, CARD_M = 320, 400, 64, 16


def card_base(seed: int, *, wash_rgb=None, wash_a=0.0, shadow=0.3, glow_rgb=None, glow_a=0.0):
    """卡片底：宣纸笺，下面一层柔和的投影（或泥金光）。返回 (画布, 纸面距离场, 周期对齐函数)。"""
    Wd, H, L, m = CARD_W, CARD_H, CARD_SL, CARD_M
    Cx, Cy = Wd - 2 * L, H - 2 * L
    ss = 3
    c = Canvas(Wd, H, seed, ss)
    rng = c.rng
    per = lambda f: c.periodic(f, L, L)  # noqa: E731
    pd = per(paper_field(rng, Cy, Cx, ss, grain=0.012, fibre=0.8))
    n_edge = per(noise(rng, (Cy * ss, Cx * ss), 5.0 * ss))
    n_wash = per(noise(rng, (Cy * ss, Cx * ss), 12.0 * ss))
    x0, y0, x1, y1 = m, m, Wd - m, H - m
    if shadow:
        ds, _ = rrect(c, x0 + 2, y0 + 7, x1 - 2, y1 + 3, 8)
        c.over(JIAO, shadow * np.exp(-np.maximum(ds + 1.5, 0) ** 2 / (2 * 5.0**2)))
    if glow_rgb is not None:
        dg, _ = rrect(c, x0, y0, x1, y1, 6)
        c.over(glow_rgb, glow_a * np.exp(-np.maximum(dg, 0) ** 2 / (2 * 6.0**2)))
    d, _ = rrect(c, x0, y0, x1, y1, 5)
    d = d + 0.45 * n_edge
    body = smoothstep(0.6 + c.aa, -0.6 - c.aa, d)
    rgb = paper_rgb(pd)
    rgb = mixc(rgb, PAPER_SH, 0.3 * np.exp(np.minimum(d, 0) / 3.0))  # 纸边一线略深（纸的厚度）
    if wash_rgb is not None:
        k = wash_a * np.exp(np.minimum(d, 0) / 16.0) * np.clip(0.8 + 0.35 * n_wash, 0.3, 1.3) * smoothstep(-44, -30, d)
        rgb = mixc(rgb, wash_rgb, np.clip(k, 0, 1))
    c.over(rgb, body)
    return c, d, per


def card_frame(c: Canvas, inset: float, hw: float, rgb, *, seed: int, alpha=1.0, dark=None, dark_k=0.5, over=6.0, dry=0.03,
               dry_tail=0.6, head_len=12.0, tail_len=20.0):
    """四笔直线围成的框：横笔从左往右、竖笔从上往下写，左上两笔起笔、右下两笔收笔飞白，四角交叉出一点头。"""
    Wd, H, L, m = CARD_W, CARD_H, CARD_SL, CARD_M
    x0, y0, x1, y1 = m + inset, m + inset, Wd - m - inset, H - m - inset
    kw = dict(rgb=rgb, alpha=alpha, dark=dark, dark_k=dark_k, dry=dry, dry_tail=dry_tail, head_len=head_len, tail_len=tail_len)
    line_stroke(c, True, y0, x0 - over, x1 + over * 0.7, hw, period=Wd - 2 * L, origin=L, seed=seed, **kw)
    line_stroke(c, False, x0, y0 - over, y1 + over * 0.7, hw * 0.92, period=H - 2 * L, origin=L, seed=seed + 1, **kw)
    line_stroke(c, False, x1, y0 - over * 0.5, y1 + over, hw * 0.96, period=H - 2 * L, origin=L, seed=seed + 2, **kw)
    line_stroke(c, True, y1, x0 - over * 0.5, x1 + over, hw * 1.06, period=Wd - 2 * L, origin=L, seed=seed + 3, **kw)


def make_card(kind: str) -> Image.Image:
    """升级卡（凡 / 灵 / 玄 / 天）与夜签卡：320×400，切片 64，中间 192×272 一个周期（中间和四边都平铺）。
    品级越高框越重：凡一道淡墨；灵、玄一道品级色 + 一道细内框；玄的内框四角点墨；天是泥金框、外发金光、四角洒金。"""
    Wd, H, L, m = CARD_W, CARD_H, CARD_SL, CARD_M
    seed = {"fan": 410, "ling": 420, "xuan": 430, "tian": 440, "omen": 450}[kind]
    if kind == "omen":
        c, d, per = card_base(seed, wash_rgb=W_ZHUSHA, wash_a=0.12)
        card_frame(c, 9.0, 2.7, ZHUSHA, seed=seed + 10, dark=ZHUSHA_DK, dark_k=0.45, dry=0.03, dry_tail=0.55)
        loop(c, m, m, Wd - m, H - m, 6, center=-17.5, hw=(1.0,) * 4, seed=seed + 20, rgb=ZHUSHA, alpha=0.9, press=0.0)
        return finish(c)
    rc = RARITY[kind]
    tian = kind == "tian"
    wash = {"fan": 0.0, "ling": 0.11, "xuan": 0.12, "tian": 0.14}[kind]
    c, d, per = card_base(seed, wash_rgb=mixc(rc, PAPER, 0.3), wash_a=wash, shadow=0.18 if tian else 0.3,
                          glow_rgb=GOLD if tian else None, glow_a=0.6)
    hw = {"fan": 2.2, "ling": 2.5, "xuan": 2.7, "tian": 2.9}[kind]
    if kind == "fan":
        ink, dark = mixc(ZHONG, DAN, 0.35), NONG
    elif tian:
        ink, dark = mixc(rc, TENG, 0.35), GOLD_DK
    else:
        ink, dark = rc, mixc(rc, JIAO, 0.45)
    card_frame(c, 9.0, hw, ink, seed=seed + 10, dark=dark, dark_k=0.55, dry=0.05 if kind == "fan" else 0.03)
    if kind != "fan":
        loop(c, m, m, Wd - m, H - m, 6, center=-17.5, hw=(0.8,) * 4, seed=seed + 20, rgb=mixc(ink, dark, 0.3), alpha=0.8,
             press=0.0)
    if kind in ("xuan", "tian"):
        for (px, py) in ((m + 17.5, m + 17.5), (Wd - m - 17.5, m + 17.5), (m + 17.5, H - m - 17.5), (Wd - m - 17.5, H - m - 17.5)):
            dd = np.hypot(c.X - px, c.Y - py)
            c.over(mixc(ink, dark, 0.5), smoothstep(2.4 + c.aa, 2.4 - c.aa, dd))
    if tian:
        rng = np.random.default_rng(seed + 30)
        boxes = [(m + 3, m + 3, L - 5, L - 5), (Wd - L + 5, m + 3, Wd - m - 3, L - 5),
                 (m + 3, H - L + 5, L - 5, H - m - 3), (Wd - L + 5, H - L + 5, Wd - m - 3, H - m - 3)]
        flecks(c, rng, boxes[:1] * 3 + boxes[3:] * 3 + boxes[1:3], 60, (0.9, 2.8), GOLD, 0.85, hi=GOLD_HI)
        # 平铺区里稀疏几片（画在周期画布上再铺开，接缝处连续）
        fl = Canvas(Wd - 2 * L, H - 2 * L, seed + 31, c.ss)
        flecks(fl, rng, [(3, 3, Wd - 2 * L - 3, H - 2 * L - 3)], 9, (0.8, 1.9), GOLD, 0.8, hi=GOLD_HI)
        pa = per(fl.lay.a) * smoothstep(0.5, -1.5, d)
        pr = np.stack([per(fl.lay.p[..., k]) for k in range(3)], -1) / np.maximum(per(fl.lay.a), 1e-6)[..., None]
        c.over(np.clip(pr, 0, 1), pa)
    return finish(c)


def make_card_focus() -> Image.Image:
    """卡片焦点：叠在卡片上面的一笔泥金圈（左上起笔、留缺口、收笔飞白）与暖光，中间透明；尺寸、切片与卡片相同。"""
    Wd, H, L, m = CARD_W, CARD_H, CARD_SL, CARD_M
    c = Canvas(Wd, H, 460, 3)
    x0, y0, x1, y1 = m, m, Wd - m, H - m
    glow_rrect(c, x0, y0, x1, y1, 6, rgb=mixc(GOLD, LANTERN, 0.5), alpha=0.65, width=6.5)
    d, _ = rrect(c, x0, y0, x1, y1, 6)
    c.over(mixc(GOLD, LANTERN, 0.4), 0.2 * np.exp(np.minimum(d, 0) / 6.0) * smoothstep(1.0, -0.5, d))
    loop(c, x0, y0, x1, y1, 6, center=1.0, hw=(2.3, 2.0, 2.6, 2.1), seed=461, rgb=GOLD, alpha=0.97, press=0.6, dry=0.04,
         seam=(-2.0, 9.0, 16.0, 26.0, 0.25, 0.75), tone=GOLD_DK, tone_k=0.55, slices=(L, L))
    return finish(c, band_x=(L, L), band_y=(L, L))


def make_note(hi: bool) -> Image.Image:
    """卡片里的说明框：一块淡墨（hi：藤黄）晕染，边上积一道干痕。128×80，切片 24，中间与四边拉伸。"""
    Wd, H, m, r = 128, 80, 3, 9
    c = Canvas(Wd, H, 470 + hi, 4)
    d, th = rrect(c, m, m, Wd - m, H - m, r)
    # 四角各有一点洇开的不规则（只在圆角上）
    cw = sum(corner_weight(th, k) for k in ("tl", "tr", "br", "bl"))
    d = d + 0.8 * cw * np.sin(np.radians(th) * 7.0 + 1.3)
    fill_rgb = mixc(W_TENG, TENG, 0.25) if hi else mixc(DAN, ZHONG, 0.25)
    rim_rgb = mixc(TENG, ZHESHI, 0.55) if hi else mixc(ZHONG, NONG, 0.4)
    a_fill = 0.34 if hi else 0.10
    a_rim = 0.55 if hi else 0.28
    body = smoothstep(0.5 + c.aa, -0.5 - c.aa, d)
    c.over(fill_rgb, body * (a_fill + 0.05 * smoothstep(-8, -1, d)))
    c.over(rim_rgb, a_rim * np.exp(-(((d + 0.9) / 0.9) ** 2)))
    return finish(c, band_x=(24, 24), band_y=(24, 24))


# ============================================================== 按钮、胶囊


BTN_W, BTN_H, BTN_SL = 192, 112, 72


def make_button(primary: bool, state: str) -> Image.Image:
    """一笔横扫的按钮（primary：朱砂）。192×112，左右 72 的横向九宫格；状态 normal / focus / pressed / disabled。
    起笔方中带圆、收笔上提飞白，都在两端的切片里；中段只有横向的笔毛纹，拉多长都不变形。"""
    Wd, H, L = BTN_W, BTN_H, BTN_SL
    seed = 500 + 20 * primary
    c = Canvas(Wd, H, seed + {"normal": 0, "focus": 1, "pressed": 2, "disabled": 3}[state], 4)
    yc, hw = 56.0, 35.0
    dry, dry_tail, alpha = 0.012, 0.72, 0.97
    if primary:
        core, edge, light = ZHUSHA, ZHUSHA_DK, mixc(ZHUSHA, W_ZHUSHA, 0.5)
    else:
        core, edge, light = mixc(NONG, ZHONG, 0.45), mixc(JIAO, NONG, 0.3), mixc(ZHONG, DAN, 0.35)
    if state == "focus":
        core = mixc(core, mixc(TENG, ZHUSHA, 0.4), 0.2) if primary else mixc(core, ZHONG, 0.45)
        light = mixc(light, GOLD, 0.3)
    elif state == "pressed":
        yc, hw = 58.0, 32.5
        dry, dry_tail, alpha = 0.0, 0.5, 1.0
        core = mixc(core, edge, 0.4)
    elif state == "disabled":
        dry, dry_tail, alpha = 0.03, 0.82, 0.48
        core = mixc(mixc(core, DAN, 0.7), ZHONG, 0.15)
        edge, light = mixc(edge, DAN, 0.6), mixc(core, QING, 0.3)
    st = dict(band=(L, Wd - L), seed=seed + 7, head_len=44.0, tail_len=60.0, slant=0.32, blunt=3.0, taper=0.5, lift=0.1,
              dry=dry, dry_tail=dry_tail, edge_soft=0.8, rough=0.06)
    S_ = hstroke(c, 12.0, 184.0, yc, hw, **st)
    if state == "focus":
        e = np.maximum(S_["edge"], 0.0)
        c.over(mixc(GOLD, LANTERN, 0.5), 0.55 * np.exp(-(e**2) / (2 * 6.0**2)) * (1 - S_["shape"]))
    s, T = S_["s"], S_["T"]
    rgb = mixc(core, edge, np.clip(smoothstep(0.7, 1.0, np.abs(s)) * 0.8 + 0.35 * (0.45 - T), 0, 1))
    rgb = mixc(rgb, light, np.clip((T - 0.6) * 1.6, 0, 1) * smoothstep(0.3, -0.7, s))
    c.over(rgb, S_["cov"] * alpha)
    if state == "focus":
        g = hstroke(c, 26.0, 178.0, yc + hw + 1.0, 2.6, band=(L, Wd - L), seed=seed + 9, head_len=46.0, tail_len=58.0,
                    slant=0.0, blunt=2.0, taper=0.25, lift=0.0, dry=0.05, dry_tail=0.75, edge_soft=0.4, rough=0.1, head_taper=0.4)
        c.over(mixc(GOLD, GOLD_HI, 0.25), g["cov"])
    return finish(c, band_x=(L, L))


def make_capsule(kind: str) -> Image.Image:
    """小胶囊：pill / pill_on（开关、徽记）96×64，chip / chip_dark（五行、增益小签）80×48。
    左右为圆头，中段拉伸；边是一笔绕成的圈，起收笔在左边的圆头里。"""
    if kind.startswith("pill"):
        Wd, H, L, m, my = 96, 64, 32, 4, 6
    else:
        Wd, H, L, m, my = 80, 48, 24, 3, 5
    k = 1.0 if kind.startswith("pill") else 0.78
    c = Canvas(Wd, H, 600 + len(kind), 4)
    r = (H - 2 * my) / 2
    x0, y0, x1, y1 = m, my, Wd - m, H - my
    d, th = rrect(c, x0, y0, x1, y1, r)
    body = smoothstep(0.5 + c.aa, -0.5 - c.aa, d)
    pool = smoothstep(-6.0 * k, -1.0, d)
    if kind == "pill_on":
        c.over(mixc(ZHUSHA, ZHUSHA_DK, 0.35 * pool), body * 0.96)
        top = smoothstep(0.1, -0.7, (c.Y - y0) / (y1 - y0) * 2 - 1) * smoothstep(-2.5, -6.0, d)
        c.over(mixc(ZHUSHA, W_ZHUSHA, 0.55), body * 0.35 * top)
        rim, ra, tone = ZHUSHA_DK, 0.9, JIAO
    elif kind == "chip":
        c.over(mixc(mixc(PAPER, PAPER_LT, 0.3), PAPER_SH, 0.5 * pool), body * 0.96)
        rim, ra, tone = mixc(NONG, ZHONG, 0.3), 0.9, JIAO
    else:
        c.over(mixc(NIGHT_INK, JIAO, 0.3 * pool), body * (0.8 + 0.08 * pool))
        rim, ra, tone = INK_RIM, 0.75, ZHONG
    hwv = tuple(v * k for v in (1.3, 1.5, 1.4, 1.9))
    seam = (-16.0 * k, 6.5 * k, 12.0 * k, 26.0 * k, 0.3, 0.7)
    loop(c, x0, y0, x1, y1, r, center=-1.4 * k, hw=hwv, seed=610 + len(kind), rgb=rim, alpha=ra, press=0.0, dry=0.03,
         seam=seam, tone=tone, tone_k=0.4)
    return finish(c, band_x=(L, L))


# ============================================================== 法器 / 心法格子


def make_slot(big: bool, kind: str) -> Image.Image:
    """HUD 上的格子（不切片）：大 128²（法器）、小 80²（心法）。kind：full / empty / evo。
    夜墨的方砚，一笔淡墨圈边（左上起笔、留缺口、收笔飞白）；空格是断续的虚笔；进化格是泥金边、暖光和金屑。"""
    N = 128 if big else 80
    k = N / 128.0
    c = Canvas(N, N, 700 + 10 * big + {"full": 0, "empty": 1, "evo": 2}[kind], 4)
    rng = c.rng
    m, r = 8 * k, 22 * k
    x0, y0, x1, y1 = m, m, N - m, N - m
    d, th = rrect(c, x0, y0, x1, y1, r)
    body = smoothstep(0.5 + c.aa, -0.5 - c.aa, d)
    rr = np.hypot(c.X - N / 2, c.Y - N / 2) / (N / 2)
    if kind == "evo":
        glow_rrect(c, x0, y0, x1, y1, r, rgb=mixc(GOLD, LANTERN, 0.5), alpha=0.65, width=4.5 * k)
    if kind in ("full", "evo"):
        base = mixc(NIGHT_INK, mixc(ZHESHI, JIAO, 0.65), 0.45) if kind == "evo" else NIGHT_INK
        mott = noise(rng, c.X.shape, 9.0 * k * c.ss) + 0.5 * noise(rng, c.X.shape, 2.5 * k * c.ss)
        # 砚池：中间一团略浅的墨晕，四周积墨（往里凹）
        rgb = mixc(base, ZHONG, np.clip(0.16 * np.exp(-((rr / 0.62) ** 2)) + 0.035 * mott, 0, 1))
        rgb = mixc(rgb, JIAO, np.clip(0.6 * smoothstep(-16 * k, -1, d), 0, 1))
        c.over(rgb, body * 0.88)
        if kind == "evo":
            c.over(mixc(GOLD, LANTERN, 0.3), body * 0.16 * np.exp(-((rr / 0.55) ** 2)))
    else:
        c.over(NIGHT_INK, body * 0.32)
    if kind == "empty":
        p, per = rrect_perim(c, x0, y0, x1, y1, r)
        n = 12 if big else 8
        ph = np.mod(p / per * n + 0.3, 1.0)
        dash = np.sin(np.pi * np.clip(ph / 0.6, 0, 1)) ** 0.6 * (ph < 0.6)
        v = d + 1.8 * k
        hw = 2.0 * k * (0.3 + 0.7 * dash)
        T = rank01(0.8 * (samp1(tex1(np.random.default_rng(705 + big), 48, 1.0), np.clip(v / np.maximum(hw, 1e-3), -1, 1)) - 0.5)
                   + 0.25 * noise(rng, c.X.shape, (2.0 * c.ss, 2.0 * c.ss)))
        cov = smoothstep(hw + 0.45, hw - 0.45, np.abs(v)) * (dash > 0.05) * smoothstep(0.22, 0.36, T)
        c.over(INK_RIM, cov * 0.8)
        return finish(c)
    evo = kind == "evo"
    rim = mixc(GOLD, TENG, 0.25) if evo else INK_RIM
    hwv = tuple(v * k * (1.15 if evo else 1.0) for v in (2.6, 2.2, 3.0, 2.3))
    loop(c, x0, y0, x1, y1, r, center=-1.6 * k, hw=hwv, seed=720 + big, rgb=rim, alpha=0.97 if evo else 0.88, press=0.5,
         dry=0.07, wobble=0.12, seam=(-9.0 * k, 10.0 * k, 18.0 * k, 34.0 * k, 0.22, 0.8), tone=GOLD_DK if evo else ZHONG,
         tone_k=0.6)
    if evo:
        rng2 = np.random.default_rng(740 + big)
        e = 6 * k
        boxes = [(x0 - 2, y0 - 2, x0 + e * 3, y0 + e * 3), (x1 - e * 3, y1 - e * 3, x1 + 2, y1 + 2),
                 (x1 - e * 2, y0 - 2, x1 + 2, y0 + e * 2), (x0 - 2, y1 - e * 2, x0 + e * 2, y1 + 2)]
        flecks(c, rng2, boxes, 18 if big else 11, (0.6 * k + 0.3, 1.8 * k + 0.3), GOLD, 0.9, hi=GOLD_HI)
    return finish(c)


# ============================================================== 进度条


def make_track() -> Image.Image:
    """进度条的底槽：一笔压低的夜墨，上半更深（凹下去），边上一道淡墨。128×36，左右 24 的横向九宫格。"""
    Wd, H, L = 128, 36, 24
    c = Canvas(Wd, H, 800, 4)
    S_ = hstroke(c, 4.0, 124.0, 18.0, 13.5, band=(L, Wd - L), seed=801, head_len=18.0, tail_len=18.0, slant=0.2, blunt=2.4,
                 taper=0.86, lift=0.0, dry=0.0, dry_tail=0.3, edge_soft=0.7, rough=0.05)
    s = S_["s"]
    rgb = mixc(NIGHT_INK, JIAO, np.clip(0.65 * smoothstep(0.5, -0.9, s), 0, 1))
    c.over(rgb, S_["cov"] * 0.88)
    edge = S_["shape"] * smoothstep(0.6, 0.97, np.abs(s)) * (1 - 0.35 * (s < 0))
    c.over(INK_RIM, edge * 0.6 * smoothstep(0.15, 0.45, S_["T"]))
    return finish(c, band_x=(L, L))


def make_fill(kind: str) -> Image.Image:
    """进度条的填充：一笔颜料，上沿略亮、下沿积色，左端方中带圆、右端圆收略干。中段沿 x 完全一致，
    游戏按百分比改宽度，任何宽度两端都是笔头。hp 朱砂 / xp 藤黄 / boss 绛紫 / unlock 石绿 / shield 淡花青（细条）。"""
    shield = kind == "shield"
    Wd, H, L = (96, 12, 10) if shield else (96, 28, 20)
    c = Canvas(Wd, H, 820 + len(kind), 4)
    base = {"hp": ZHUSHA, "xp": mixc(TENG, GOLD, 0.5), "boss": BOSS, "unlock": SHILV, "shield": SHIELD}[kind]
    hi = mixc(base, WHITE if kind in ("xp", "shield") else PAPER_LT, 0.38)
    lo = mixc(base, JIAO, 0.38)
    if shield:
        S_ = hstroke(c, 2.0, 94.0, 6.0, 3.7, band=(L, Wd - L), seed=830, head_len=7.0, tail_len=7.0, slant=0.2, blunt=2.2,
                     taper=0.8, lift=0.0, dry=0.0, dry_tail=0.3, edge_soft=0.5, rough=0.04, tail_round=True)
    else:
        S_ = hstroke(c, 3.0, 93.0, 14.0, 10.5, band=(L, Wd - L), seed=831 + len(kind), head_len=16.0, tail_len=16.0,
                     slant=0.22, blunt=2.6, taper=0.8, lift=0.0, dry=0.0, dry_tail=0.4, edge_soft=0.6, rough=0.05,
                     tail_round=True)
    s, T = S_["s"], S_["T"]
    rgb = mixc(base, lo, np.clip(smoothstep(0.1, 1.0, s) * 0.85 + 0.25 * (0.5 - T), 0, 1))
    rgb = mixc(rgb, hi, np.clip(smoothstep(-0.2, -0.85, s) * 0.8 + 0.3 * (T - 0.6), 0, 1))
    c.over(rgb, S_["cov"])
    return finish(c, band_x=(L, L))


def make_pip(on: bool) -> Image.Image:
    """心灯进度点（40²，不切片）：灭 = 一个小墨圈；亮 = 圈里一点灯焰，带暖光。"""
    N = 40
    c = Canvas(N, N, 850 + on, 6)
    C = N / 2
    r = np.hypot(c.X - C, c.Y - C)
    th = np.mod(np.arctan2(c.Y - C, c.X - C), 2 * math.pi)
    if on:
        c.over(mixc(LANTERN, GOLD, 0.4), 0.55 * np.exp(-((r / 9.5) ** 2)) * smoothstep(19.5, 14, r))
    c.over(NIGHT_INK, (0.25 if on else 0.55) * smoothstep(9.6, 8.6, r))
    # 一笔圆圈（同 ui_icons 的圆相）：右上起笔，顺时针，收笔飞白，留个小缺口
    th0, span = math.radians(-40.0), math.radians(330.0)
    rel = np.mod(th - th0 + math.radians(10.0), 2 * math.pi) - math.radians(10.0)
    t = rel / span
    tc = np.clip(t, 0, 1)
    R = 10.4 + 0.5 * tc
    hw = np.interp(tc, [0.0, 0.06, 0.5, 0.9, 1.0], [1.7, 1.9, 1.6, 1.3, 0.45])
    over = np.where(t < 0, -t * span * R, 0.0)
    over = np.where(t > 1.0, 1e3, over)
    cov = smoothstep(hw + c.aa, hw - c.aa, np.hypot(r - R, over))
    tex = W.ptex(np.random.default_rng(852), ns=16, nt=256, along=8.0, across=0.6)
    b = W.sample_ptex(tex, np.clip((r - R) / np.maximum(hw, 0.3), -1, 1), tc * 0.999)
    dry = 0.5 * smoothstep(0.75, 1.0, tc) + 0.05
    cov = cov * smoothstep(dry - 0.08, dry + 0.08, b)
    c.over(GOLD if on else INK_RIM, cov * (0.95 if on else 0.85))
    if on:
        # 灯焰：上尖下圆的一滴，芯白、外金、根上一点朱砂
        fx, fy = C, C + 1.5
        dy = c.Y - fy
        wdt = np.where(dy < 0, 4.3 * np.clip(1 + dy / 9.5, 0, 1) ** 0.85, np.sqrt(np.clip(1 - (dy / 4.3) ** 2, 0, 1)) * 4.3)
        dd = np.abs(c.X - fx) - wdt
        fl = smoothstep(0.5, -0.5, dd) * (dy > -9.6) * (dy < 4.4)
        h = np.clip((-dy + 4.3) / 13.8, 0, 1)
        core = np.exp(-(((c.X - fx) / 1.6) ** 2 + ((c.Y - fy + 1.0) / 2.6) ** 2))
        frgb = mixc(mixc(ZHUSHA, TENG, smoothstep(0.0, 0.35, h)), GOLD_HI, smoothstep(0.45, 1.0, h) * 0.6)
        frgb = mixc(frgb, mixc(WHITE, GOLD_HI, 0.4), np.clip(core, 0, 1))
        c.over(frgb, fl)
    return finish(c)


# ============================================================== 提示条、小签


def make_toast(big: bool) -> Image.Image:
    """提示条：一笔横拖的夜墨，两端毛而软（big：下沿再拖一道朱砂）。toast 144×72 / toast_big 176×88。"""
    Wd, H, L = (176, 88, 64) if big else (144, 72, 56)
    c = Canvas(Wd, H, 900 + big, 4)
    yc, hw = (42.0, 29.0) if big else (36.0, 25.0)
    S_ = hstroke(c, 6.0, Wd - 6.0, yc, hw, band=(L, Wd - L), seed=901 + big, head_len=L - 8.0, tail_len=L - 8.0, slant=0.2,
                 blunt=2.2, taper=0.62, lift=0.06, dry=0.0, dry_tail=0.55, head_dry=0.42, edge_soft=1.5, rough=0.1)
    rgb = mixc(NIGHT_INK, JIAO, np.clip(np.abs(S_["s"]) ** 2 * 0.5, 0, 1))
    c.over(rgb, S_["cov"] * 0.86)
    if big:
        g = hstroke(c, 18.0, Wd - 12.0, yc + hw + 4.5, 2.5, band=(L, Wd - L), seed=905, head_len=40.0, tail_len=48.0,
                    slant=0.0, blunt=2.0, taper=0.25, lift=0.0, dry=0.03, dry_tail=0.72, edge_soft=0.4, rough=0.1, head_taper=0.45)
        c.over(ZHUSHA, g["cov"])
    return finish(c, band_x=(L, L))


# ============================================================== 其他


def make_divider() -> Image.Image:
    """分隔线：一笔淡墨横线，细入、中段匀、收笔飞白。256×24，左右 96 的横向九宫格。"""
    Wd, H, L = 256, 24, 96
    c = Canvas(Wd, H, 950, 4)
    S_ = hstroke(c, 10.0, 248.0, 12.0, 2.7, band=(L, Wd - L), seed=951, head_len=84.0, tail_len=90.0, slant=0.0, blunt=2.0,
                 taper=0.15, lift=0.0, dry=0.02, dry_tail=0.7, edge_soft=0.45, rough=0.08, head_taper=0.2)
    c.over(mixc(ZHONG, DAN, 0.35), S_["cov"] * 0.95)
    return finish(c, band_x=(L, L))


SCROLL_W, SCROLL_H, SCROLL_SL, SCROLL_BAND = 256, 480, 56, 40
SILK = mixc(mixc(HUAQING, PAPER_SH, 0.35), ZHONG, 0.12)  # 裱卷轴的绫子：淡花青


def scroll_mount(c: Canvas, per_x, y_top: float, y_bot: float, seed: int, *, flip: bool):
    """卷轴上下的绫边（淡花青的绫子，织纹极细 + 暗花云纹，靠纸一侧一道金线），沿 x 周期。"""
    rng = np.random.default_rng(seed)
    Hs = c.lay.a.shape[0]
    sh = (Hs, SCROLL_W * c.ss)
    weft = per_x(noise(rng, sh, (5.0 * c.ss, 0.3 * c.ss)))
    sheen = per_x(noise(rng, sh, 18.0 * c.ss))
    # 暗花：沿 x 周期的一排卷云（同色略亮），8 朵一个周期
    X = c.X
    ph = np.mod(X / SCROLL_W * 8.0, 1.0)
    cy = 0.5 * (y_top + y_bot)
    yy = (c.Y - cy) / (0.5 * (y_bot - y_top))
    cloud = np.exp(-(((ph - 0.5) / 0.16) ** 2 + (yy / 0.35) ** 2))
    curl = np.sin(2 * math.pi * (ph * 2.0) + yy * 3.0)
    flower = smoothstep(0.25, 0.4, cloud) * smoothstep(0.55, 0.75, cloud * (0.6 + 0.4 * curl)) * 0 + smoothstep(0.3, 0.5, cloud) * (1 - smoothstep(0.55, 0.62, cloud))
    inside = smoothstep(y_top - 0.5, y_top + 0.5, c.Y) * smoothstep(y_bot + 0.5, y_bot - 0.5, c.Y)
    rgb = SILK + 0.012 * weft[..., None] + 0.018 * sheen[..., None]
    rgb = mixc(rgb, mixc(SILK, PAPER_LT, 0.35), 0.5 * flower)
    yy01 = (c.Y - y_top) / (y_bot - y_top)
    rgb = mixc(rgb, ZHONG, 0.3 * (smoothstep(0.12, 0.0, yy01) + smoothstep(0.88, 1.0, yy01)))
    c.over(np.clip(rgb, 0, 1), inside)
    gy = y_bot - 3.0 if not flip else y_top + 3.0
    gl = smoothstep(1.4, 0.7, np.abs(c.Y - gy))
    c.over(mixc(TENG, GOLD_DK, 0.3), gl * 0.95)


def make_scroll_body() -> Image.Image:
    """宝箱卷轴的卷身：256×480，上下各 56 的切片；整张沿 x 周期（平铺），纸面沿 y 也周期。"""
    Wd, H, T, Bd = SCROLL_W, SCROLL_H, SCROLL_SL, SCROLL_BAND
    c = Canvas(Wd, H, 960, 2)
    rng = c.rng
    Cy = H - 2 * T
    pd = c.periodic(paper_field(rng, Cy, Wd, c.ss, grain=0.012, fibre=0.9), 0, T)
    c.over(paper_rgb(pd), np.ones_like(c.X))
    per_x = lambda f: c.periodic(f, 0, 0)  # noqa: E731
    # 绫边下的纸略有阴影（在切片以内结束）
    dist = np.minimum(c.Y - Bd, H - Bd - c.Y)
    c.over(mixc(PAPER_SH, ZHONG, 0.3), 0.32 * np.exp(-np.maximum(dist, 0) / 4.0) * smoothstep(T - Bd, T - Bd - 8, dist))
    scroll_mount(c, per_x, 0.0, float(Bd), 961, flip=False)
    scroll_mount(c, per_x, float(H - Bd), float(H), 962, flip=True)
    return finish(c, clear=False)


SCROLL_END_W, SCROLL_KNOB, SCROLL_TASSEL = 112, 34, 116


def make_scroll_end() -> Image.Image:
    """卷轴左端（不切片，游戏水平镜像得到右端）：卷起的纸筒 + 木轴头 + 朱砂穗子。
    图的右边缘贴着卷身的左边缘；卷身在本图里占 y ∈ [34, 514)（与 scroll_body 同高），上下伸出轴头，穗子垂在下面。"""
    Wd = SCROLL_END_W
    H = SCROLL_H + 2 * SCROLL_KNOB + SCROLL_TASSEL
    y0, y1 = SCROLL_KNOB, SCROLL_KNOB + SCROLL_H
    c = Canvas(Wd, H, 970, 3)
    rng = c.rng
    X, Y = c.X, c.Y
    ax, rad = 76.0, 34.0  # 纸筒中心线与半径（右缘到 110）
    u = np.clip((X - ax) / rad, -1, 1)
    inside = smoothstep(rad + 0.5, rad - 0.5, np.abs(X - ax)) * smoothstep(y0 - 0.5, y0 + 0.5, Y) * smoothstep(y1 + 0.5, y1 - 0.5, Y)
    pd = paper_field(rng, H, Wd, c.ss, grain=0.01, fibre=0.6)
    shade = 0.62 * (u + 0.2) ** 2 - 0.1  # 左上受光：偏左处最亮，两侧转暗
    rgb = mixc(paper_rgb(pd), mixc(PAPER_SH, ZHONG, 0.5), np.clip(shade, 0, 1))
    rgb = mixc(rgb, PAPER_LT, np.clip(-shade * 3.0, 0, 1))
    c.over(rgb, inside)
    # 纸筒上下的绫边，与卷身同色，随圆柱明暗
    for (a, b, flip) in ((y0, y0 + SCROLL_BAND, False), (y1 - SCROLL_BAND, y1, True)):
        cc = Canvas(Wd, H, 971, c.ss)
        scroll_mount(cc, lambda f: cc.periodic(f, 0, 0), float(a), float(b), 961 if not flip else 962, flip=flip)
        rgbm, am = cc.lay.p / np.maximum(cc.lay.a, 1e-6)[..., None], cc.lay.a
        rgbm = mixc(rgbm, JIAO, np.clip(shade, 0, 1) * 0.7)
        rgbm = mixc(rgbm, WHITE, np.clip(-shade * 1.5, 0, 1))
        c.over(np.clip(rgbm, 0, 1), am * inside)
    # 纸筒上几道卷层的细线（淡墨，竖向）
    for kk, xx in enumerate((ax - 25, ax - 12, ax + 8, ax + 22)):
        wv = 0.6 * np.sin(Y / 37.0 + kk)
        c.over(mixc(ZHONG, DAN, 0.4), 0.22 * smoothstep(0.9, 0.3, np.abs(X - xx - wv)) * inside)
    line_stroke(c, False, ax - rad + 1.0, y0 - 1, y1 + 1, 1.6, period=SCROLL_H, origin=y0, seed=972, rgb=JIAO, alpha=0.9,
                head_len=8, tail_len=12, dry=0.04, dry_tail=0.35)
    line_stroke(c, False, ax + rad - 1.0, y0 - 1, y1 + 1, 0.9, period=SCROLL_H, origin=y0, seed=973, rgb=ZHONG, alpha=0.55,
                head_len=8, tail_len=12, dry=0.04, dry_tail=0.35)
    # 纸筒上下口的椭圆（看得出是卷起来的）
    for yy in (y0, y1):
        de = np.hypot((X - ax) / rad, (Y - yy) / 4.0) - 1.0
        c.over(mixc(PAPER_SH, ZHONG, 0.3), smoothstep(0.0, -0.08, de) * 0.9)
        c.over(JIAO, smoothstep(0.12, 0.03, np.abs(de)) * 0.85)
    # 轴杆与轴头：赭石木杆，象牙色的轴头（扁鼓），墨线勾边
    wood = mixc(ZHESHI, JIAO, 0.3)
    for top in (True, False):
        ya, yb = (4.0, y0 + 2.0) if top else (y1 - 2.0, y1 + SCROLL_KNOB - 4.0)
        rod = smoothstep(8.5, 7.5, np.abs(X - ax)) * smoothstep(ya - 0.5, ya + 0.5, Y) * smoothstep(yb + 0.5, yb - 0.5, Y)
        rr_ = np.clip((X - ax) / 8.0, -1, 1)
        c.over(mixc(mixc(wood, PAPER_SH, 0.2), JIAO, np.clip(0.55 * (rr_ + 0.25) ** 2, 0, 1)), rod)
        cy = (ya + 11.0) if top else (yb - 11.0)
        dk = np.hypot((X - ax) / 15.0, (Y - cy) / 10.0) - 1.0
        cap = smoothstep(0.04, -0.04, dk)
        ivory = mixc(PAPER, PAPER_SH, 0.25)
        c.over(mixc(ivory, ZHONG, np.clip(0.55 * ((X - ax) / 15.0 + 0.3) ** 2, 0, 1)), cap)
        c.over(JIAO, smoothstep(0.11, 0.03, np.abs(dk)) * 0.9)
        c.over(mixc(ivory, WHITE, 0.5), 0.6 * np.exp(-(((X - ax + 6) / 2.6) ** 2 + ((Y - cy + 3) / 3.0) ** 2)))
    # 朱砂穗子：从下轴头垂下，打一个结，散开成穗
    ky = y1 + SCROLL_KNOB - 6.0
    cord = np.array([(ax, ky), (ax - 4, ky + 14), (ax - 2, ky + 30), (ax, ky + 38)])
    seg_stroke(c, V.bezier(cord, 40), 1.7, seed=974, rgb=ZHUSHA, taper=(1.0, 1.0))
    knot_y = ky + 42
    dk = np.hypot((X - ax) / 5.8, (Y - knot_y) / 4.8) - 1.0
    c.over(mixc(ZHUSHA, ZHUSHA_DK, np.clip(0.5 + 0.5 * (X - ax) / 5.8, 0, 1)), smoothstep(0.08, -0.08, dk))
    trng = np.random.default_rng(975)
    for i in range(18):
        x_top = ax + trng.uniform(-3.5, 3.5)
        x_bot = ax + (x_top - ax) * 2.4 + trng.uniform(-3, 3)
        y_end = knot_y + trng.uniform(54, 68)
        pts = V.bezier(np.array([(x_top, knot_y + 3), (x_top, knot_y + 20), (x_bot, y_end - 18), (x_bot, y_end)]), 48)
        seg_stroke(c, pts, trng.uniform(0.55, 0.9), seed=976 + i, rgb=mixc(ZHUSHA, ZHUSHA_DK, trng.uniform(0, 0.7)),
                   alpha=0.95, taper=(1.0, 0.4))
    c.over(ZHUSHA_DK, smoothstep(1.4, 0.6, np.abs(Y - knot_y - 7.5)) * smoothstep(5.4, 4.4, np.abs(X - ax)))
    return finish(c)


def make_arrow_marker() -> Image.Image:
    """屏幕外遭遇的指示（128²，白色可染色）：半透明圆底 + 一笔圆相 + 指向 +X 的笔锋。游戏绕中心旋转，图标画在圆底上。"""
    N = 128
    c = Canvas(N, N, 990, 4)
    C = N / 2
    r = np.hypot(c.X - C, c.Y - C)
    th = np.mod(np.arctan2(c.Y - C, c.X - C), 2 * math.pi)
    # 指针：从圆边向右撇出的一笔，根部宽、笔锋尖，两边略弧
    tip = 124.0
    base_x = C + 30.0
    xx = (c.X - base_x) / (tip - base_x)
    half = 15.0 * np.clip(1 - xx, 0, 1) ** 1.35
    ptr = smoothstep(0.6, -0.6, np.abs(c.Y - C) - half) * (xx >= 0) * (xx <= 1)
    a = ptr
    disc = smoothstep(38.5, 37.5, r)
    a = 1 - (1 - a) * (1 - 0.55 * disc)
    th0, span = math.radians(-30.0), math.radians(335.0)
    rel = np.mod(th - th0 + math.radians(8.0), 2 * math.pi) - math.radians(8.0)
    t = rel / span
    tc = np.clip(t, 0, 1)
    R = 40.0 + 0.8 * tc
    hw = np.interp(tc, [0.0, 0.05, 0.5, 0.9, 1.0], [3.4, 3.8, 3.2, 2.6, 0.8])
    over = np.where(t < 0, -t * span * R, 0.0)
    over = np.where(t > 1.0, 1e3, over)
    cov = smoothstep(hw + c.aa, hw - c.aa, np.hypot(r - R, over))
    tex = W.ptex(np.random.default_rng(991), ns=16, nt=512, along=8.0, across=0.6)
    b = W.sample_ptex(tex, np.clip((r - R) / np.maximum(hw, 0.3), -1, 1), tc * 0.999)
    dry = 0.5 * smoothstep(0.78, 1.0, tc) + 0.05
    cov = cov * smoothstep(dry - 0.08, dry + 0.08, b)
    a = 1 - (1 - a) * (1 - cov)
    c.over(WHITE, a)
    return finish(c)


def make_focus_ring() -> Image.Image:
    """键盘 / 手柄焦点：四角各一笔泥金折角（竖笔起、转折、横笔收，收笔飞白），带一点暖光，中间透明。
    128²，切片 48，中间与四边拉伸（四边是空的）。"""
    N, L = 128, 48
    c = Canvas(N, N, 1000, 4)
    m, arm, rc = 7.0, 30.0, 5.0
    gl = np.zeros_like(c.X)
    paths = []
    for i, (sx, sy) in enumerate(((1, 1), (-1, 1), (-1, -1), (1, -1))):
        cx = m if sx > 0 else N - m
        cy = m if sy > 0 else N - m
        # 竖臂末端 → 转角（圆一点） → 横臂末端
        a0 = (cx, cy + sy * arm)
        a1 = (cx, cy + sy * rc)
        a2 = (cx + sx * rc, cy)
        a3 = (cx + sx * arm, cy)
        pts = np.vstack([W.seg_pts(a0, a1, n=30), V.bezier([a1, (cx, cy), a2], 12)[1:], W.seg_pts(a2, a3, n=30)[1:]])
        pts = V.arc_resample(pts, 72)
        f = V.stroke_fields(c.X, c.Y, pts, np.full(len(pts), 3.0))
        gl = np.maximum(gl, np.exp(-np.hypot(np.maximum(np.abs(f["perp"]) - 2.0, 0), f["over"]) ** 2 / (2 * 3.4**2)))
        paths.append(pts)
    inside_corner = (np.minimum(c.X, N - c.X) < L - 1) & (np.minimum(c.Y, N - c.Y) < L - 1)
    c.over(mixc(GOLD, LANTERN, 0.5), 0.5 * gl * inside_corner)
    for i, pts in enumerate(paths):
        seg_stroke(c, pts, 2.8, seed=1010 + i, rgb=GOLD, dry=0.55, dry_start=0.6, jitter=0.14, taper=(0.9, 0.3))
    return finish(c, band_x=(L, L), band_y=(L, L))


def make_menu_hl() -> Image.Image:
    """标题菜单的选中底：一笔淡夜墨横扫，两端毛而软，下沿一道泥金干笔，四周一点暖光。320×80，左右 112 的横向九宫格。"""
    Wd, H, L = 320, 80, 112
    c = Canvas(Wd, H, 1100, 4)
    yc, hw = 38.0, 22.0
    S_ = hstroke(c, 14.0, 306.0, yc, hw, band=(L, Wd - L), seed=1101, head_len=96.0, tail_len=96.0, slant=0.2, blunt=2.2,
                 taper=0.5, lift=0.06, dry=0.0, dry_tail=0.6, head_dry=0.5, edge_soft=2.2, rough=0.12)
    e = np.maximum(S_["edge"], 0.0)
    c.over(mixc(GOLD, LANTERN, 0.6), 0.22 * np.exp(-(e**2) / (2 * 7.0**2)) * (1 - S_["shape"]) * smoothstep(306, 250, c.X) * smoothstep(14, 60, c.X))
    c.over(mixc(NIGHT_INK, JIAO, 0.3), S_["cov"] * 0.64)
    g = hstroke(c, 40.0, 292.0, yc + hw + 3.0, 1.9, band=(L, Wd - L), seed=1102, head_len=70.0, tail_len=84.0, slant=0.0,
                blunt=2.0, taper=0.2, lift=0.0, dry=0.04, dry_tail=0.75, edge_soft=0.4, rough=0.1, head_taper=0.35)
    c.over(GOLD, g["cov"] * 0.95)
    return finish(c, band_x=(L, L))


