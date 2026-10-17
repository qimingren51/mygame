def make_seal() -> Image.Image:
    """山印：方柱石印，3/4 俯视；龟钮（印钮是一只伏龟）。赭石淡墨的石色，焦墨轮廓，
    钮上穿一根朱砂绶带垂在侧面，底边沾一线朱砂印泥。"""
    W, H = 40, 44
    P = Painter(W, H, 3000)
    x0, w, h, dx, dy = 8.5, 16.0, 16.0, 7.0, 5.0
    y0 = 37.4 + dy / 2 - h  # 足印中心落在锚点 (0.5, 0.85)
    stone_box(P, x0, y0, w, h, dx, dy, STONE, ol=1.1, inner=0.7, cun=2)
    tx, ty = x0 + w / 2 + dx / 2, y0 - dy / 2 + 0.4  # 顶面中心
    ks = 1.22  # 龟钮的大小

    def q(x, y):
        return (tx + ks * x, ty + ks * y)

    def qa(pts):
        return np.array([q(*p) for p in pts])

    knob_lit, knob_dark = mixc(STONE, PAPER, 0.5), mixc(STONE, ZHONG, 0.35)
    ink = mixc(JIAO, NONG, 0.3)
    # 龟脚、龟头（先画，被龟壳压住）
    for fx, fy in ((-4.6, 1.0), (4.4, 1.2), (-2.4, 1.9), (2.6, 2.0)):
        d, t = P.sdf(ellipse_pts(*q(fx, fy - 0.6), 1.25 * ks, 0.85 * ks, 24))
        P.fill(d, knob_dark)
        P.outline(d, t, 0.5, ink)
    neck = catmull_closed(qa([(-4.8, -1.2), (-6.6, -2.6), (-8.6, -2.9), (-9.3, -1.6), (-8.4, -0.3), (-6.2, 0.3)]), 8)
    d, t = P.sdf(neck)
    P.fill(d, knob_lit, pool=0.3, pool_rgb=ZHONG, pool_w=0.6)
    P.outline(d, t, 0.6, ink)
    P.dot(*q(-8.0, -2.0), 0.45, JIAO)
    # 龟壳：拱起的半椭圆，壳上刻龟甲纹
    shell = catmull_closed(qa([(-6.0, 0.6), (-5.4, -3.0), (-2.0, -5.4), (2.2, -5.4), (5.6, -3.0), (6.4, 0.4), (0.2, 1.6)]), 10)
    d, t = P.sdf(wobble(shell, P.rng, 0.05, spacing=0.3))
    shade = smoothstep(ty - 6.0, ty + 1.5, P.Y) * 0.6 + 0.5 * smoothstep(tx - 3, tx + 7, P.X)
    P.fill(d, mixc(knob_lit, knob_dark, np.clip(shade, 0, 1)), mottle=0.08, mottle_rgb=ZHONG, pool=0.3, pool_rgb=ZHONG, pool_w=0.7)
    m = P.cover(d)
    hc = np.array(q(0.2, -2.6))
    hexa = ellipse_pts(hc[0], hc[1], 2.2 * ks, 1.35 * ks, 6, a0=0.0)
    P.line(V.arc_resample(np.vstack([hexa, hexa[:1]]), 60), 0.2, NONG, alpha=0.8, clip=m)
    for ax, ay in hexa:
        vx, vy = ax - hc[0], ay - hc[1]
        P.line(seg_pts((ax, ay), (ax + vx * 1.2, ay + vy * 1.6), n=12), 0.18, NONG, alpha=0.7, clip=m)
    P.line(seg_pts(q(-5.4, -0.4), q(0.2, 0.6), q(5.8, -0.4), n=40), 0.2, NONG, alpha=0.7, clip=m)
    P.outline(d, t, 0.75, ink)
    # 朱砂绶带：从龟钮穿出，垂过侧面
    P.line(V.bezier([q(4.2, -1.4), q(6.4, 0.0), (tx + 7.6, ty + 4.2), (tx + 8.2, ty + 8.0)], 50), 0.42, ZHUSHA)
    P.dot(tx + 7.6, ty + 4.0, 0.75, ZHUSHA_DK)
    P.line(V.bezier([(tx + 7.6, ty + 4.2), (tx + 6.8, ty + 6.4), (tx + 7.0, ty + 9.0)], 30), 0.5 * brush_profile(30, 1.0, 0.35, 0.0), ZHUSHA, dry=0.3, dry_start=0.6)
    return P.image()
