def make_sword(evo: bool) -> Image.Image:
    """符剑：细长的剑身指向 +X。淡钢色剑身 + 细墨线，藤黄剑格，浓墨剑柄，朱砂剑穗拖在左边，
    剑格前缠一道黄符纸、符尾从剑柄下飘出。evo（万剑归宗）：金边剑身、更亮，带一圈淡金色的光。
    小尺寸下墨线只给 0.6 像素左右，否则 4 像素高的剑身会被墨线吃掉一半。"""
    W, H = (52, 14) if evo else (44, 12)
    k = W / 44.0
    P = Painter(W, H, 2150 if evo else 2100)
    cy = H / 2.0

    def q(x, y):
        return (x * k, cy + y * k)

    def qa(pts):
        return np.array([q(*p) for p in pts])

    # 剑身外形：中段微收，最后约 5 单位收成剑尖
    xs = np.linspace(16.4, 42.9, 60)
    hw = np.where(xs < 37.6, 1.95 - 0.3 * (xs - 16.4) / 21.2, 1.65 * np.clip(1 - (xs - 37.6) / 5.3, 0, 1) ** 0.7)
    upper = [(x, -h) for x, h in zip(xs, hw)]
    lower = [(x, h) for x, h in zip(xs[::-1], hw[::-1])]
    blade = qa(upper + lower[1:-1])
    d_bl, t_bl = P.sdf(blade, pad=4.0)

    if evo:
        # 一圈很淡的金光（正常混合；纸上是金色的晕）
        halo = 0.38 * np.exp(-np.maximum(d_bl, 0.0) / 0.9) * smoothstep(3.0, 1.2, d_bl)
        halo *= smoothstep(16.0 * k, 19.0 * k, P.X)
        P.lay.over(mixc(TENG, WHITE, 0.6), halo)

    # ---- 剑穗（朱砂）：绳、结、散开的穗子
    cord = V.bezier([q(8.4, 0.5), q(7.2, 1.1), q(6.1, 1.8), q(5.2, 2.4)], 40)
    P.line(cord, 0.36 * k, ZHUSHA_DK)
    tuft_root = np.array(q(5.1, 2.45))
    tips = [(1.6, 3.5), (1.9, 4.6), (2.7, 2.7)] if not evo else [(1.4, 3.2), (1.6, 4.7), (2.4, 2.2), (2.7, 5.5)]
    for i, (tx, ty) in enumerate(tips):
        tip = np.array(q(tx, ty))
        mid = (tuft_root + tip) / 2 + np.array([0.0, 0.35 * k * (1 if i % 2 else -1)])
        pts = V.bezier([tuft_root, mid, tip], 40)
        P.line(pts, 0.66 * k * brush_profile(40, head=1.0, tail=0.25, belly=0.0), ZHUSHA, dry=0.3, dry_start=0.55)
    P.dot(*q(5.2, 2.4), 0.75 * k, mixc(ZHUSHA, JIAO, 0.2))
    P.dot(*q(5.0, 2.2), 0.3 * k, mixc(ZHUSHA, WHITE, 0.4), alpha=0.8)

    # ---- 剑柄（浓墨，缠绳的斜纹）
    grip = wobble(qa([(9.9, -1.15), (16.6, -1.15), (16.6, 1.15), (9.9, 1.15)]), P.rng, 0.05 * k)
    d, t = P.sdf(grip)
    stripes = 0.5 + 0.5 * np.sin(2 * math.pi * ((P.X / k) - (P.Y - cy) / k * 0.9) / 1.3)
    P.fill(d, mixc(NONG, mixc(ZHONG, DAN, 0.3), 0.7 * smoothstep(0.45, 0.85, stripes)))
    P.outline(d, t, 0.55 * k)

    # ---- 符尾：从符纸下沿飘向左下，压在剑柄上（先画，被剑格挡住根部）
    paper_rgb = mixc(W_TENG, TENG, 0.35) if not evo else mixc(TENG, WHITE, 0.2)
    tail_c = V.bezier([q(19.4, 1.6), q(17.0, 3.0), q(14.6, 2.6), q(12.0, 3.7)], 40)
    tail = ribbon(tail_c, np.linspace(0.75, 0.55, 40) * k)
    d, t = P.sdf(tail)
    P.fill(d, paper_rgb, mottle=0.1, mottle_rgb=ZHESHI)
    P.outline(d, t, 0.42 * k, mixc(ZHESHI, JIAO, 0.45))
    P.line(seg_pts(q(13.2, 3.2), q(14.6, 2.75), n=12), 0.18 * k, ZHUSHA, alpha=0.9)

    # ---- 剑首（金）
    d, t = P.sdf(ellipse_pts(*q(9.5, 0.0), 1.25 * k, 1.6 * k, 40))
    P.fill(d, mixc(TENG, GOLD_HI, smoothstep(0.5, -1.5, P.Y - cy)), pool=0.45, pool_rgb=GOLD_DK, pool_w=0.5)
    P.outline(d, t, 0.55 * k, mixc(GOLD_DK, JIAO, 0.4))

    # ---- 剑身：上半亮、下半略暗（刃面的两个斜面）
    yrel = (P.Y - cy) / k
    if evo:
        hi, lo = mixc(PAPER, WHITE, 0.85), mixc(W_TENG, WHITE, 0.6)
    else:
        hi, lo = mixc(PAPER, WHITE, 0.6), mixc(QING, PAPER, 0.4)
    P.fill(d_bl, mixc(hi, lo, smoothstep(-0.2, 0.4, yrel)))
    P.line(seg_pts(q(19.0, -1.05), q(35.5, -0.85)), 0.2 * k, WHITE, alpha=0.9)
    if evo:
        # 金边：轮廓内侧一道藤黄，外轮廓用暗金而不是焦墨，显得亮
        P.outline(d_bl, t_bl, 0.6 * k, TENG, center=-0.62 * k, jitter=0.12)
        P.outline(d_bl, t_bl, 0.6 * k, mixc(GOLD_DK, JIAO, 0.35), jitter=0.15)
    else:
        P.outline(d_bl, t_bl, 0.62 * k, mixc(JIAO, NONG, 0.3), jitter=0.18)

    # ---- 剑格（藤黄，月牙形，两端略翘），暗金描边
    gp = [(14.9, -4.0), (16.5, -3.6), (17.9, -0.45), (17.9, 0.45), (16.5, 3.6), (14.9, 4.0), (15.9, 0.0)]
    guard = catmull_closed(qa(gp), 8)
    d, t = P.sdf(guard)
    P.fill(d, mixc(TENG, GOLD_HI, smoothstep(0.5, -2.0, P.Y - cy)), pool=0.5, pool_rgb=GOLD_DK, pool_w=0.45)
    P.outline(d, t, 0.6 * k, mixc(GOLD_DK, JIAO, 0.45))

    # ---- 符纸：缠在剑格前的一道黄纸，上面一笔朱砂
    band = wobble(qa([(18.5, -2.55), (21.3, -2.45), (21.1, 2.6), (18.3, 2.5)]), P.rng, 0.05 * k)
    d, t = P.sdf(band)
    P.fill(d, paper_rgb, mottle=0.1, mottle_rgb=ZHESHI, pool=0.25, pool_rgb=ZHESHI, pool_w=0.4)
    P.line(seg_pts(q(19.9, -1.6), q(19.7, 1.6)), 0.24 * k, ZHUSHA)
    P.line(seg_pts(q(19.2, -0.5), q(20.5, -0.65)), 0.2 * k, ZHUSHA)
    P.outline(d, t, 0.45 * k, mixc(ZHESHI, JIAO, 0.5))
    return P.image()


CRANE_ELEV = (60.0, 6.0, -40.0, 18.0)  # 4 帧翼仰角（度）：上、下扑中、下、上提中
CRANE_BOB = (0.45, 0.0, -0.55, -0.15)  # 身体随扑翼的起伏（下扑时身体被抬起）
CRANE_BEND = (0.0, 1.0, 0.0, -1.0)  # 翼前缘的弯曲：下扑时翼尖滞后向上，上提时翼尖滞后向下
CRANE_PITCH = math.radians(35.0)  # 从斜上方看纸鹤：平展的翅膀也有面积，扑翼时翼面大小有变化


def crane_wing(hinge_f, hinge_b, elev_deg: float, side: int, bend: float, L: float = 11.0):
    """一侧翅膀：前后两个铰点 + 翼尖，按仰角和俯角投影到屏幕。side=+1 近侧（朝镜头），-1 远侧。"""
    ph = math.radians(elev_deg)
    sp, cp = math.sin(CRANE_PITCH), math.cos(CRANE_PITCH)
    Ls = L * (1.0 if side > 0 else 0.9)
    hf, hb = np.asarray(hinge_f, dtype=np.float64), np.asarray(hinge_b, dtype=np.float64)
    root = hb * 0.55 + hf * 0.45
    dy = Ls * (-math.sin(ph) * cp + side * math.cos(ph) * sp)
    dx = -(1.4 + 2.6 * abs(math.cos(ph)))  # 翼尖向后掠
    tip = root + np.array([dx, dy])
    lead = hf + (tip - hf) * 0.5
    ln = np.array([-(tip - hf)[1], (tip - hf)[0]])
    ln /= np.linalg.norm(ln) + 1e-9
    lead = lead + ln * bend * 0.8
    trail = hb + (tip - hb) * 0.72 + np.array([0.5, 0.0])
    return [tuple(hf), tuple(lead), tuple(tip), tuple(trail), tuple(hb)], tip, root


def make_crane(frame: int, evo: bool) -> Image.Image:
    """纸鹤：宣纸白的折纸鹤向右飞（从斜上方看），焦墨细轮廓、淡墨折痕，头上一点朱砂。4 帧扑翼循环。
    evo（千鹤引）：翼缘贴一道藤黄金箔，翼面撒两点金。"""
    W, H = 30, 26
    P = Painter(W, H, 2350 if evo else 2300)  # 各帧同一种子，轮廓抖动逐帧一致，不闪
    by = CRANE_BOB[frame] - 0.6
    elev, bend = CRANE_ELEV[frame], CRANE_BEND[frame]

    def o(x, y):
        return (x, y + by)

    body = [o(8.4, 15.0), o(15.0, 12.6), o(21.8, 14.4), o(15.6, 18.8)]
    neck = [o(18.4, 13.6), o(22.0, 15.0), o(25.4, 6.5)]
    head = [o(24.6, 6.2), o(26.4, 7.1), o(28.5, 10.3)]
    tail = [o(9.2, 14.1), o(12.6, 16.4), o(1.8, 8.4)]
    hf, hb = np.array(o(18.6, 13.4)), np.array(o(10.6, 13.9))
    far_poly, far_tip, far_root = crane_wing(hf + [0.7, -0.9], hb + [0.7, -0.9], elev, -1, bend)
    near_poly, near_tip, near_root = crane_wing(hf, hb, elev, +1, bend)

    paper_lit = mixc(PAPER, WHITE, 0.6)
    paper_mid = mixc(PAPER, WHITE, 0.2)
    paper_dark = mixc(PAPER_SH, QING, 0.3)
    ol, crease = 0.6, 0.16
    line_rgb = mixc(JIAO, NONG, 0.25)

    def facet(poly, rgb, *, w=ol, gold=False):
        poly = wobble(poly, P.rng, 0.04, spacing=0.3, sigma_px=2.0)
        d, t = P.sdf(poly)
        P.fill(d, rgb, mottle=0.04, mottle_rgb=PAPER_SH, pool=0.2, pool_rgb=QING, pool_w=0.7)
        if gold:
            P.outline(d, t, 0.6, TENG, center=-0.55, jitter=0.2)
        P.outline(d, t, w, line_rgb)
        return d

    # 远侧翅膀在身体后面，背光偏暗
    facet(far_poly, paper_dark, gold=evo)
    P.line(seg_pts(far_root, far_tip, n=30), crease, DAN, alpha=0.6)
    # 尾、颈、头、身
    facet(tail, paper_mid)
    P.line(seg_pts(o(10.8, 15.0), o(3.4, 9.0), n=30), crease, DAN, alpha=0.55)
    facet(neck, paper_mid)
    P.line(seg_pts(o(20.0, 14.3), o(24.9, 7.4), n=30), crease, DAN, alpha=0.55)
    facet(head, paper_lit, w=0.55)
    facet(body, paper_lit)
    P.line(seg_pts(o(9.4, 15.0), o(15.2, 15.6), o(21.0, 14.4), n=40), crease, DAN, alpha=0.6)
    # 近侧翅膀
    wing_rgb = paper_lit if elev < 30 else mixc(paper_lit, paper_mid, 0.5)
    facet(near_poly, wing_rgb, gold=evo)
    P.line(seg_pts(near_root, near_tip, n=30), crease, DAN, alpha=0.65)
    if evo:
        for f, off in ((0.42, (0.5, 0.2)), (0.66, (-0.6, 0.3))):
            px, py = near_root + (near_tip - near_root) * f + np.array(off)
            P.dot(px, py, 0.45, TENG)
    # 头上一点朱砂
    P.dot(*o(25.2, 7.3), 0.7, ZHUSHA)
    return P.image()


STONE = mixc(W_ZHESHI, DAN, 0.3)  # 赭石兑淡墨的石色


def stone_box(P: Painter, x0, y0, w, h, dx, dy, base_rgb, *, ol: float, inner: float, cun: int = 3, red_bottom: bool = True, edge_rgb=None):
    """3/4 视角的石块：顶面最亮、正面中间、右侧面最暗；几笔干墨皴；正面底边沾一线印泥。"""
    front, top, side, sil = box_faces(x0, y0, w, h, dx, dy)
    tones = (mixc(base_rgb, PAPER, 0.5), base_rgb, mixc(base_rgb, ZHONG, 0.5))
    masks = []
    for poly, rgb in zip((top, front, side), tones):
        poly = wobble(poly, P.rng, 0.07, spacing=0.3)
        d, _ = P.sdf(poly)
        masks.append(P.cover(d))
        P.fill(d, rgb, mottle=0.12, mottle_rgb=ZHONG, pool=0.25, pool_rgb=ZHONG, pool_w=0.8)
    # 皴笔：正面斜向的几笔干墨，长短不一
    for i in range(cun):
        xa = x0 + w * (0.12 + 0.7 * (i + P.rng.uniform(0.0, 0.4)) / cun)
        ya = y0 + h * P.rng.uniform(0.12, 0.35)
        L = h * P.rng.uniform(0.3, 0.55)
        pts = V.bezier([(xa, ya), (xa - 0.8 + P.rng.uniform(-0.4, 0.4), ya + L * 0.5), (xa - 0.4, ya + L)], 40)
        P.line(pts, 0.42 * brush_profile(40, 1.0, 0.2), mixc(DAN, ZHONG, 0.4), alpha=0.45, clip=masks[1], dry=0.55, dry_start=0.2)
    for i in range(max(cun - 1, 1)):
        fx = 0.3 + 0.4 * i / max(cun - 2, 1)
        xa, ya = x0 + w + dx * fx, y0 - dy * fx + h * P.rng.uniform(0.2, 0.35)
        pts = V.bezier([(xa, ya), (xa + 0.4, ya + h * 0.25), (xa - 0.1, ya + h * 0.5)], 40)
        P.line(pts, 0.4 * brush_profile(40, 1.0, 0.2), ZHONG, alpha=0.45, clip=masks[2], dry=0.5, dry_start=0.2)
    if red_bottom:
        P.line(seg_pts((x0 + 0.6, y0 + h - 0.6), (x0 + w - 0.3, y0 + h - 0.6), (x0 + w + dx - 0.5, y0 + h - dy - 0.6), n=60), 0.45, ZHUSHA, alpha=0.9)
    # 墨线：内部棱线用细线，整体外轮廓用粗线
    er = NONG if edge_rgb is None else edge_rgb
    P.line(seg_pts((x0, y0), (x0 + w, y0), (x0 + w + dx, y0 - dy), n=60), 0.5 * inner, er)
    P.line(seg_pts((x0 + w, y0), (x0 + w, y0 + h), n=30), 0.5 * inner, NONG)
    d, t = P.sdf(wobble(sil, P.rng, 0.06, spacing=0.3))
    P.outline(d, t, ol, jitter=0.25)
    return masks


def make_seal() -> Image.Image:
    """山印：方柱石印，3/4 俯视；龟钮（印钮是一只伏龟）。赭石淡墨的石色，焦墨轮廓，
    钮上穿一根朱砂绶带垂在侧面，底边沾一线朱砂印泥。"""
    W, H = 40, 44
    P = Painter(W, H, 3000)
    x0, w, h, dx, dy = 8.5, 16.0, 17.0, 7.0, 5.0
    y0 = 37.4 + dy / 2 - h  # 足印中心落在锚点 (0.5, 0.85)
    stone_box(P, x0, y0, w, h, dx, dy, STONE, ol=1.1, inner=0.7, cun=3)
    tx, ty = x0 + w / 2 + dx / 2, y0 - dy / 2  # 顶面中心
    knob_lit, knob_dark = mixc(STONE, PAPER, 0.45), mixc(STONE, ZHONG, 0.35)
    ink = mixc(JIAO, NONG, 0.3)
    # 龟脚、龟头（先画，被龟壳压住）
    for fx, fy in ((-4.6, 1.0), (4.4, 1.2), (-2.4, 1.9), (2.6, 2.0)):
        d, t = P.sdf(ellipse_pts(tx + fx, ty + fy - 0.6, 1.25, 0.85, 24))
        P.fill(d, knob_dark)
        P.outline(d, t, 0.5, ink)
    neck = catmull_closed([(tx - 4.8, ty - 1.2), (tx - 6.6, ty - 2.6), (tx - 8.6, ty - 2.9), (tx - 9.3, ty - 1.6), (tx - 8.4, ty - 0.3), (tx - 6.2, ty + 0.3)], 8)
    d, t = P.sdf(neck)
    P.fill(d, knob_lit, pool=0.3, pool_rgb=ZHONG, pool_w=0.6)
    P.outline(d, t, 0.6, ink)
    P.dot(tx - 8.0, ty - 2.0, 0.42, JIAO)
    # 龟壳：拱起的半椭圆，壳上刻龟甲纹
    shell = catmull_closed([(tx - 6.0, ty + 0.6), (tx - 5.4, ty - 3.0), (tx - 2.0, ty - 5.4), (tx + 2.2, ty - 5.4), (tx + 5.6, ty - 3.0),
                            (tx + 6.4, ty + 0.4), (tx + 0.2, ty + 1.6)], 10)
    d, t = P.sdf(wobble(shell, P.rng, 0.05, spacing=0.3))
    shade = smoothstep(ty - 5.0, ty + 1.5, P.Y) * 0.6 + 0.5 * smoothstep(tx - 3, tx + 6, P.X)
    P.fill(d, mixc(knob_lit, knob_dark, np.clip(shade, 0, 1)), mottle=0.08, mottle_rgb=ZHONG, pool=0.3, pool_rgb=ZHONG, pool_w=0.7)
    m = P.cover(d)
    hexa = ellipse_pts(tx + 0.2, ty - 2.5, 2.2, 1.35, 6, a0=0.0)
    hexa_c = np.vstack([hexa, hexa[:1]])
    P.line(V.arc_resample(hexa_c, 60), 0.2, NONG, alpha=0.8, clip=m)
    for (ax, ay) in hexa[[0, 1, 2, 3, 4, 5]]:
        vx, vy = ax - (tx + 0.2), ay - (ty - 2.5)
        P.line(seg_pts((ax, ay), (ax + vx * 1.2, ay + vy * 1.5), n=12), 0.18, NONG, alpha=0.7, clip=m)
    P.line(seg_pts((tx - 5.4, ty - 0.4), (tx + 0.2, ty + 0.6), (tx + 5.8, ty - 0.4), n=40), 0.2, NONG, alpha=0.7, clip=m)
    P.outline(d, t, 0.75, ink)
    # 朱砂绶带：从龟钮穿出，垂过侧面
    P.line(V.bezier([(tx + 4.2, ty - 1.4), (tx + 7.0, ty + 0.2), (tx + 6.9, ty + 4.5), (tx + 7.6, ty + 8.0)], 50), 0.42, ZHUSHA)
    P.dot(tx + 7.0, ty + 4.0, 0.75, ZHUSHA_DK)
    P.line(V.bezier([(tx + 7.0, ty + 4.2), (tx + 6.2, ty + 6.4), (tx + 6.4, ty + 8.8)], 30), 0.5 * brush_profile(30, 1.0, 0.35, 0.0), ZHUSHA, dry=0.3, dry_start=0.6)
    return P.image()


def make_seal_evo() -> Image.Image:
    """镇岳：更大的石印，印钮是三峰的山（金碧山水：石绿花青敷色、藤黄勾金），
    印台顶边一道金线，正面一个金色篆书“山”。"""
    W, H = 56, 60
    P = Painter(W, H, 3100)
    x0, w, h, dx, dy = 11.5, 24.0, 18.0, 9.0, 6.5
    y0 = 51.0 + dy / 2 - h
    stone = mixc(W_ZHESHI, ZHONG, 0.45)
    masks = stone_box(P, x0, y0, w, h, dx, dy, stone, ol=1.3, inner=1.0, cun=4, edge_rgb=TENG)
    # 正面金色篆书“山”：暗金托底、藤黄面
    gx, gy, gs = x0 + w / 2, y0 + h / 2 + 0.4, 6.0
    for stroke in SHAN_GLYPH:
        pts = V.arc_resample(np.array([(gx + gs * x, gy + gs * y) for x, y in stroke]), 60)
        P.line(pts + [0.3, 0.3], 0.62, GOLD_DK, alpha=0.9, clip=masks[1], jitter=0.05)
        P.line(pts, 0.5, TENG, clip=masks[1], jitter=0.05)
    # 山形印钮：三峰，主峰居中偏左，山脚坐满顶面
    bx, by = x0 + w / 2 + dx / 2, y0 - dy / 2 + 1.0
    peaks = [(-14.0, 1.2), (-12.8, -3.6), (-10.0, -10.2), (-8.0, -9.0), (-5.6, -15.8), (-2.8, -24.0), (0.2, -27.8), (2.6, -22.4),
             (4.6, -18.6), (6.6, -20.6), (8.6, -15.6), (10.6, -10.8), (12.8, -5.2), (14.0, 0.8), (0.0, 2.8)]
    mtn = catmull_closed([(bx + x, by + y) for x, y in peaks], 8)
    mtn = wobble(mtn, P.rng, 0.12, spacing=0.3)
    d, t = P.sdf(mtn)
    m_mask = P.cover(d)
    hgt = np.clip((by - P.Y) / 27.0, 0, 1)
    m_rgb = mixc(mixc(W_SHILV, W_HUAQING, 0.4), mixc(SHILV, HUAQING, 0.45), 0.25 + 0.5 * smoothstep(bx - 2, bx + 11, P.X))
    m_rgb = mixc(m_rgb, mixc(stone, PAPER, 0.3), smoothstep(0.45, 0.0, hgt) * 0.8)  # 山脚是石色，往上渐敷青绿
    P.fill(d, m_rgb, mottle=0.10, mottle_rgb=ZHONG, pool=0.3, pool_rgb=mixc(HUAQING, JIAO, 0.4), pool_w=0.8)
    # 披麻皴：顺山势的几笔
    for (sx, sy), (ex, ey) in (((-3.0, -21.0), (-7.4, -9.0)), ((-0.6, -18.0), (-3.2, -5.0)), ((3.0, -17.5), (5.0, -6.0)),
                               ((7.0, -14.0), (10.0, -4.0)), ((-8.0, -6.0), (-11.0, -0.5)), ((1.0, -10.0), (0.6, -1.0))):
        pts = V.bezier([(bx + sx, by + sy), (bx + (sx + ex) / 2 + 0.8, by + (sy + ey) / 2), (bx + ex, by + ey)], 40)
        P.line(pts, 0.42 * brush_profile(40, 1.0, 0.2), mixc(ZHONG, HUAQING, 0.3), alpha=0.55, clip=m_mask, dry=0.45, dry_start=0.3)
    # 勾金：峰脊一道藤黄
    for ridge in (((-2.8, -24.0), (0.2, -27.8), (2.6, -22.4)), ((-10.0, -10.2), (-8.0, -9.0), (-5.8, -15.0)), ((6.6, -20.6), (8.6, -15.6), (10.6, -10.8))):
        pts = V.bezier([(bx + x, by + y + 0.9) for x, y in ridge], 40)
        P.line(pts, 0.45 * brush_profile(40, 0.6, 0.3), TENG, clip=m_mask)
    # 山脚一抹留白的云气
    mist = V.bezier([(bx - 12.0, by - 2.4), (bx - 5.0, by - 4.6), (bx + 2.0, by - 1.6), (bx + 11.0, by - 3.6)], 60)
    P.line(mist, 1.1 * brush_profile(60, 0.5, 0.2), mixc(PAPER, WHITE, 0.4), alpha=0.75, clip=m_mask)
    P.outline(d, t, 1.05, mixc(JIAO, HUAQING, 0.15))
    return P.image()


def make_soulbell() -> Image.Image:
    """引魂铃：小铜铃（藤黄兑赭石，左亮右暗），圆肩、铃口向上弯成弧（于口），一道箍、三粒乳钉，
    铃口下露出铃舌；铃钮上系一个朱砂绳环。"""
    W, H = 20, 26
    P = Painter(W, H, 3500)
    cx = 10.0
    bronze = mixc(TENG, ZHESHI, 0.45)
    ink = mixc(JIAO, NONG, 0.2)
    # 朱砂绳环与结
    loop = ellipse_pts(cx, 3.4, 1.7, 1.75, 48)
    P.line(V.arc_resample(np.vstack([loop, loop[:1]]), 80), 0.42, ZHUSHA)
    # 铃口里的暗面和铃舌（先画，被铃身挡住）
    d, t = P.sdf(ellipse_pts(cx, 21.3, 5.9, 1.5, 40))
    P.fill(d, mixc(NONG, ZHESHI, 0.15))
    P.dot(cx + 0.2, 22.5, 1.15, mixc(GOLD_DK, JIAO, 0.4), ry=1.4)
    P.dot(cx - 0.2, 22.1, 0.35, GOLD_HI, alpha=0.8)
    # 铃钮（拱形）
    d, t = P.sdf(ellipse_pts(cx, 6.1, 1.6, 1.4, 32))
    P.fill(d, bronze, pool=0.4, pool_rgb=GOLD_DK, pool_w=0.5)
    P.dot(cx, 6.1, 0.6, NONG)
    P.outline(d, t, 0.5, ink)
    P.dot(cx, 5.0, 0.8, ZHUSHA_DK)
    # 铃身：圆肩，腰略收，下摆外撇；铃口是一道向上的弧，两角下垂
    y_top, y_mouth = 7.2, 21.6
    ys = np.linspace(y_top, y_mouth, 32)
    yn = (ys - y_top) / (y_mouth - y_top)
    hw = 2.9 + 1.7 * np.sqrt(yn) + 2.3 * yn**2.4
    left = [(cx - a, y) for a, y in zip(hw, ys)]
    xs = np.linspace(-hw[-1], hw[-1], 30)[1:-1]
    mouth = [(cx + x, y_mouth - 1.7 * (1 - (x / hw[-1]) ** 2)) for x in xs]
    right = [(cx + a, y) for a, y in zip(hw[::-1], ys[::-1])]
    crown = [(cx + 2.9 * math.cos(a), y_top - 1.5 * math.sin(a)) for a in np.linspace(0, math.pi, 14)[1:-1]]
    body = np.array(left + mouth + right + crown)
    d, t = P.sdf(body)
    shade = smoothstep(cx - 4.5, cx + 6.0, P.X)
    rgb = mixc(mixc(bronze, GOLD_HI, 0.4), mixc(bronze, ZHONG, 0.5), shade)
    P.fill(d, rgb, mottle=0.08, mottle_rgb=GOLD_DK, pool=0.35, pool_rgb=GOLD_DK, pool_w=0.6)
    mask = P.cover(d)
    # 高光、箍、乳钉、口沿
    P.line(V.bezier([(cx - 1.7, 8.6), (cx - 2.8, 13.0), (cx - 4.6, 19.0)], 30), 0.5 * brush_profile(30, 0.5, 0.3), GOLD_HI, alpha=0.8, clip=mask)
    arc = [(cx + 4.25 * math.cos(a), 11.8 + 0.9 * math.sin(a)) for a in np.linspace(math.pi, 0, 30)]
    P.line(np.array(arc), 0.3, GOLD_DK, clip=mask)
    lip = [(cx + x * 0.97, y_mouth - 1.2 - 1.7 * (1 - (x / hw[-1]) ** 2)) for x in np.linspace(-hw[-1], hw[-1], 40)]
    P.line(np.array(lip), 0.28, GOLD_DK, alpha=0.85, clip=mask)
    for xo in (-2.5, 0.0, 2.5):
        yy = 15.4 + 0.15 * abs(xo)
        P.dot(cx + xo, yy, 0.55, GOLD_DK, clip=mask)
        P.dot(cx + xo - 0.18, yy - 0.18, 0.24, GOLD_HI, clip=mask)
    P.outline(d, t, 0.85, ink)
    return P.image()
