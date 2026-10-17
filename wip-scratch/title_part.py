# ============================================================== 标题画：画布与笔墨工具


class Painting:
    """一张宣纸上的画（白天看的样子，sRGB 0..1）+ 发光层（加法）。
    glaze：水墨罩染（相乘，层层叠深）；over：正常覆盖（留白、雾、不透明的笔触）。"""

    def __init__(self, rng):
        self.rng = rng
        self.X, self.Y = np.meshgrid(np.arange(W) + 0.5, np.arange(H) + 0.5)
        self.rgb = paper_canvas(rng)
        self.emit = np.zeros((H, W, 3))

    def glaze(self, a, color, sl=None):
        a = np.clip(a, 0, 1)[..., None]
        rel = np.asarray(color) / PAPER
        if sl is None:
            self.rgb *= 1 - a + a * rel
        else:
            self.rgb[sl] *= 1 - a + a * rel

    def over(self, a, color, sl=None):
        a = np.clip(a, 0, 1)[..., None]
        if sl is None:
            self.rgb[:] = self.rgb * (1 - a) + np.asarray(color) * a
        else:
            self.rgb[sl] = self.rgb[sl] * (1 - a) + np.asarray(color) * a

    def stroke(self, pts, halfw, color=None, alpha=1.0, *, dry=0.0, dry_start=0.5, jitter=0.16, mode="over", bleed=0.0):
        """一笔墨：color 默认焦墨。mode="glaze" 时按罩染叠（淡墨笔触叠在一起会更深）。bleed>0 时墨边略晕。"""
        sl, cov = stroke_cover(self.X, self.Y, pts, halfw, self.rng, dry=dry, dry_start=dry_start, jitter=jitter)
        if cov.size == 0:
            return
        if bleed > 0:
            cov = np.maximum(cov, 0.35 * blur(cov, bleed))
        c = JIAO if color is None else color
        (self.glaze if mode == "glaze" else self.over)(cov * alpha, c, sl)

    def dot(self, x, y, rx, ry, color=None, alpha=1.0, ang=0.0):
        """苔点：略不规则的椭圆墨点，边缘微晕。"""
        r = int(max(rx, ry) * 2 + 4)
        x0, y0 = max(0, int(x) - r), max(0, int(y) - r)
        x1, y1 = min(W, int(x) + r + 1), min(H, int(y) + r + 1)
        if x1 <= x0 or y1 <= y0:
            return
        sl = (slice(y0, y1), slice(x0, x1))
        dx, dy = self.X[sl] - x, self.Y[sl] - y
        ca, sa = math.cos(ang), math.sin(ang)
        u, v = (dx * ca + dy * sa) / rx, (-dx * sa + dy * ca) / ry
        th = np.arctan2(v, u)
        k = 1 + 0.18 * np.sin(3 * th + x) + 0.1 * np.sin(5 * th + y)
        d = np.hypot(u, v) / k
        a = smoothstep(1.0 + 0.6 / max(rx, 1), 1.0 - 0.6 / max(rx, 1), d) * alpha
        self.over(a, JIAO if color is None else color, sl)


def paper_canvas(rng) -> np.ndarray:
    """整幅宣纸：用 vfx_textures 的可平铺纸（2 倍密度，1024²）镜像拼满画布，再叠一层画布尺度的云状浓淡，
    看不出重复。"""
    tile = np.asarray(V.make_paper(), np.float64) / 255.0
    big = np.concatenate([tile, tile[:, ::-1]], 1)
    big = np.concatenate([big, big[::-1]], 0)
    out = big[37:37 + H, 61:61 + W].copy()
    cloud = fbm(rng, (H, W), (260.0, 90.0, 30.0), (0.5, 0.35, 0.15))
    out = mixc(out, out * (PAPER_SH / PAPER), np.clip(0.18 + 0.16 * cloud, 0, 1) * 0.6)
    return out


def ridge_line(xs, peaks, base, rng, rough=6.0, rough_sigma=18.0):
    """山脊线 y(x)：base 是平处的高度，peaks = [(中心 x, 高, 左半宽, 右半宽, 尖度)]，取最高的那座；再加崎岖。"""
    y = np.full(xs.shape, float(base))
    for cx, hgt, wl, wr, sharp in peaks:
        t = np.where(xs < cx, (cx - xs) / wl, (xs - cx) / wr)
        prof = np.clip(1 - t, 0, 1) ** sharp
        y = np.minimum(y, base - hgt * prof)
    n = blur(rng.standard_normal((1, xs.size)), (rough_sigma, 0))[0]
    n = n / (n.std() + 1e-9)
    n2 = blur(rng.standard_normal((1, xs.size)), (rough_sigma * 0.25, 0))[0]
    n2 = n2 / (n2.std() + 1e-9)
    return y + rough * n + rough * 0.35 * n2


def mountain_layer(P: Painting, ridge, color, alpha, fade, rng, *, edge=0.45, streak=0.35, mist_from=None, mist_len=80.0):
    """一层远山：山脊线下方罩一层墨，山脊处墨最浓（笔先落在山脊上，水往下走），往下渐淡；
    竖向的皴纹打散墨色；山脚隐进雾里（mist_from 以下按 mist_len 淡出）。山脊边缘略毛。"""
    jit = 1.2 * noise(rng, (H, W), 1.2)
    depth = P.Y - ridge[None, :] + jit
    inside = smoothstep(-1.0, 1.4, depth)
    top = np.exp(-np.maximum(depth, 0) / 7.0)
    body = 0.35 + 0.65 * np.exp(-np.maximum(depth, 0) / fade)
    tex = noise(rng, (H, W), (40.0, 2.5), angle=math.pi / 2 + 0.25) * 0.6 + noise(rng, (H, W), (14.0, 1.4), angle=math.pi / 2 - 0.3) * 0.4
    a = alpha * inside * (body * (1 + streak * tex) + edge * top)
    if mist_from is not None:
        m = smoothstep(mist_from + mist_len, mist_from, P.Y + 25 * noise(rng, (H, W), (90.0, 14.0)))
        a = a * m
    P.glaze(np.clip(a, 0, 0.95), color)


def wash_blob(P: Painting, cx, cy, rx, ry, color, alpha, rng, *, ang=0.0, rough=0.25, edge=0.25, mode="glaze"):
    """一团水墨晕染（不规则椭圆，边缘一圈水痕略深）。"""
    r = int(max(rx, ry) * 1.6) + 8
    x0, y0, x1, y1 = max(0, int(cx - r)), max(0, int(cy - r)), min(W, int(cx + r)), min(H, int(cy + r))
    if x1 <= x0 or y1 <= y0:
        return
    sl = (slice(y0, y1), slice(x0, x1))
    dx, dy = P.X[sl] - cx, P.Y[sl] - cy
    ca, sa = math.cos(ang), math.sin(ang)
    u, v = (dx * ca + dy * sa) / rx, (-dx * sa + dy * ca) / ry
    n = noise(rng, u.shape, max(rx, ry) * 0.18)
    d = np.hypot(u, v) * (1 + rough * 0.4 * n)
    m = smoothstep(1.0, 0.75, d)
    ring = np.exp(-((d - 0.88) / 0.06) ** 2) * edge
    a = alpha * (m * (0.85 + 0.15 * noise(rng, u.shape, 6.0)) + ring * m)
    (P.glaze if mode == "glaze" else P.over)(a, color, sl)


# ============================================================== 标题画：构图

HERO_FEET = (1185.0, 906.0)  # 主角脚底在画面上的位置
MOON = (1552.0, 198.0, 58.0)  # 月亮圆心、半径
SKY_INK = mixc(DAN, col(S.ACCENT["huaqing"]), 0.22)  # 夜空的淡墨里兑一点花青
# 中景山脊（主角站的那道）的远边：左下方从画外升上来，中间平缓，右端抬起接松下的大石
GROUND_EDGE = [(180, 1110), (420, 1015), (620, 935), (800, 884), (980, 862), (1180, 858), (1400, 862),
               (1560, 846), (1660, 812), (1760, 772), (1860, 748), (1960, 738)]
# 小路：从右下前景弯到主角脚下，再沿山脊往左延伸，越远越窄
PATH = [(1430, 1095), (1340, 1010), (1250, 945), (1185, 915), (1080, 893), (960, 882), (850, 885)]
STONE_LANTERNS = [(978.0, 878.0, 0.74), (712.0, 915.0, 0.50)]  # 脚底 x, y, 缩放（相对主角的比例尺）
WISPS = [(706.0, 735.0, 1.0), (888.0, 668.0, 0.75), (1712.0, 642.0, 0.85), (1622.0, 985.0, 0.7), (540.0, 870.0, 0.6)]
EYES = [(415.0, 1000.0, 0.85, False), (834.0, 975.0, 0.7, True), (1856.0, 1010.0, 0.9, True)]  # x, y, 缩放, 镜像


def ground_edge_y(xs: np.ndarray) -> np.ndarray:
    c = curve_pts(GROUND_EDGE, 400)
    order = np.argsort(c[:, 0])
    return np.interp(xs, c[order, 0], c[order, 1])


def paint_sky(P: Painting, rng):
    """夜空：上浓下淡的一层淡墨，横向的云气；月亮留白，月周围的墨一圈圈淡开（烘云托月），两缕薄云横过月下。"""
    mx, my, mr = MOON
    yn = P.Y / H
    base = 0.46 - 0.30 * smoothstep(0.0, 0.62, yn)
    cloud = noise(rng, (H, W), (230.0, 26.0), angle=-0.05)
    cloud2 = noise(rng, (H, W), (80.0, 10.0), angle=-0.03)
    a = base * (1 + 0.30 * cloud + 0.12 * cloud2)
    d = np.hypot(P.X - mx, P.Y - my)
    halo = smoothstep(mr * 0.95, mr * 5.0, d)
    a = a * (0.08 + 0.92 * halo ** 0.8)
    a = a * smoothstep(mr - 0.5, mr + 2.0, d + 1.5 * noise(rng, (H, W), 1.5))  # 月轮留白，边缘略毛
    P.glaze(a, SKY_INK)
    # 横过月亮下半的薄云（两缕淡墨），和月亮左上方一片更淡的云
    for cy, amp, sx in ((my + 0.38 * mr, 0.30, 1.0), (my + 0.85 * mr, 0.22, 1.3), (my - 1.6 * mr, 0.10, 2.0)):
        band = np.exp(-((P.Y - cy - 6 * noise(rng, (H, W), (120.0, 8.0))) / (9.0 * sx)) ** 2)
        span = smoothstep(mx - 330 * sx, mx - 120, P.X) * smoothstep(mx + 360 * sx, mx + 140, P.X)
        tex = 0.6 + 0.4 * noise(rng, (H, W), (60.0, 2.0), angle=-0.04)
        P.glaze(amp * band * span * tex, SKY_INK)


def paint_mountains(P: Painting, rng):
    """三层远山，一层比一层近、墨一层比一层重，山脚都隐进雾里；最后在山谷里铺一道雾。"""
    xs = np.arange(W) + 0.5
    layers = [
        # 基线, 山峰, 颜色, 浓度, 渐淡长度, 雾起处
        (540, [(1170, 330, 340, 250, 1.35), (1395, 240, 190, 230, 1.2), (690, 175, 320, 250, 1.1),
               (1830, 250, 230, 260, 1.3), (300, 120, 300, 320, 1.0)], QING, 0.34, 140.0, 560),
        (620, [(985, 240, 240, 190, 1.45), (1290, 170, 170, 220, 1.2), (520, 160, 260, 230, 1.2),
               (1690, 200, 210, 200, 1.3), (60, 120, 200, 200, 1.0)], mixc(QING, DAN, 0.5), 0.40, 110.0, 650),
        (712, [(830, 125, 300, 210, 1.0), (1480, 118, 260, 250, 1.0), (180, 95, 260, 300, 1.0)], DAN, 0.46, 80.0, 735),
    ]
    for base, peaks, c, a, fade, mist_from in layers:
        r = ridge_line(xs, peaks, base, rng, rough=5.0 if base < 600 else 7.0)
        mountain_layer(P, r, c, a, fade, rng, mist_from=mist_from, mist_len=70.0)
        # 山与山之间的雾：下一层之前铺一层纸色
        fog = smoothstep(base - 150, base - 30, P.Y) * smoothstep(base + 90, base, P.Y)
        fog = fog * (0.55 + 0.45 * noise(rng, (H, W), (150.0, 18.0)))
        P.over(np.clip(fog * 0.32, 0, 1), mixc(PAPER, np.ones(3), 0.2))
    # 山谷里的一道雾
    fog = smoothstep(660, 740, P.Y) * smoothstep(880, 770, P.Y) * (0.6 + 0.4 * noise(rng, (H, W), (200.0, 20.0)))
    P.over(np.clip(fog * 0.55, 0, 1), mixc(PAPER, np.ones(3), 0.25))


def paint_ground(P: Painting, rng):
    """中景山脊：淡墨铺地（越往前越重，带横向的干笔纹），小路留白；远边一道枯笔焦墨勾边，
    边下几笔皴、一溜苔点。"""
    g = ground_edge_y(P.X[0])
    depth = P.Y - g[None, :] + 1.5 * noise(rng, (H, W), 1.3)
    inside = smoothstep(-1.0, 1.5, depth)
    tex = V.rank01(noise(rng, (H, W), (70.0, 1.8), angle=-0.04))
    a = (0.20 + 0.42 * smoothstep(0, 260, depth)) * (0.70 + 0.55 * tex) + 0.12 * np.exp(-np.maximum(depth, 0) / 14.0)
    P.glaze(np.clip(a * inside, 0, 0.9), mixc(DAN, ZHONG, 0.35))
    # 小路：一道越远越窄的留白
    path = curve_pts(PATH, 200)
    hw = np.linspace(46, 7, len(path))
    sl, cov = stroke_cover(P.X, P.Y, path, hw, rng, jitter=0.25)
    cov = blur(cov, 3.0) * (0.75 + 0.25 * noise(rng, cov.shape, 4.0))
    P.over(np.clip(cov * 0.55, 0, 1), mixc(PAPER, PAPER_SH, 0.3), sl)
    # 远边：几段枯笔
    segs = [(260, 560), (540, 860), (840, 1250), (1230, 1590), (1570, 1700)]
    for k, (xa, xb) in enumerate(segs):
        xx = np.linspace(xa, xb, 40)
        yy = np.interp(xx, P.X[0], g) + 2.0 + 1.5 * np.sin(xx / 37.0 + k)
        hw = np.interp(np.linspace(0, 1, 40), [0, 0.1, 0.7, 1], [2.0, 4.6, 3.6, 1.2])
        P.stroke(np.stack([xx, yy], -1), hw, JIAO, 0.92, dry=0.45, dry_start=0.35, jitter=0.25, bleed=1.2)
    # 皴笔：沿坡势的短干笔，淡墨
    for _ in range(46):
        x = rng.uniform(380, 1600)
        y0 = float(np.interp(x, P.X[0], g)) + rng.uniform(10, 110)
        ln = rng.uniform(30, 95)
        sl_ = (np.interp(x + 10, P.X[0], g) - np.interp(x - 10, P.X[0], g)) / 20.0
        xx = np.linspace(x, x + ln, 14)
        yy = y0 + (xx - x) * sl_ + rng.uniform(-4, 4) * np.sin(np.linspace(0, math.pi, 14))
        hw = np.interp(np.linspace(0, 1, 14), [0, 0.2, 1], [0.8, rng.uniform(1.6, 2.8), 0.6])
        P.stroke(np.stack([xx, yy], -1), hw, ZHONG, rng.uniform(0.35, 0.7), dry=0.6, dry_start=0.2, mode="glaze")
    # 苔点：沿远边一溜，疏密不匀
    for _ in range(70):
        x = rng.uniform(330, 1700)
        if rng.random() < 0.35 and abs(x - HERO_FEET[0]) < 70:
            continue
        y = float(np.interp(x, P.X[0], g)) + rng.normal(0, 5) + 2
        r = rng.uniform(1.6, 4.2)
        P.dot(x, y, r * rng.uniform(1.0, 1.6), r, JIAO, rng.uniform(0.75, 1.0), ang=rng.uniform(-0.4, 0.4))
    # 前景：最下面一抹更重的墨，把画面兜住
    fg = smoothstep(960, 1080, P.Y) * (0.5 + 0.5 * noise(rng, (H, W), (120.0, 25.0)))
    P.glaze(np.clip(fg * 0.45, 0, 1), ZHONG)


def paint_rock(P: Painting, rng, outline, *, shade_dir=(-1.0, 0.6), alpha=0.55):
    """一块山石：淡墨罩染（背光一侧深），外沿枯笔勾，内部几道皴、顶上苔点。outline 是顶部轮廓（左 → 右）。"""
    o = curve_pts(outline, 160)
    xs = P.X[0]
    order = np.argsort(o[:, 0])
    top = np.interp(xs, o[order, 0], o[order, 1], left=1e9, right=1e9)
    depth = P.Y - top[None, :]
    inside = smoothstep(-1, 1.5, depth) * (top[None, :] < 1e8)
    cx = o[:, 0].mean()
    sh = smoothstep(-0.2, 1.0, (P.X - cx) / 260.0 * shade_dir[0] + depth / 200.0 * shade_dir[1])
    tex = 0.75 + 0.5 * V.rank01(noise(rng, (H, W), (30.0, 2.0), angle=1.1))
    P.glaze(np.clip(inside * alpha * (0.45 + 0.55 * sh) * tex, 0, 0.92), mixc(DAN, ZHONG, 0.5))
    hw = np.interp(np.linspace(0, 1, len(o)), [0, 0.08, 0.6, 1], [1.5, 5.0, 4.0, 2.0])
    P.stroke(o + [0, 1.5], hw, JIAO, 0.95, dry=0.4, dry_start=0.3, jitter=0.3, bleed=1.0)
    for _ in range(9):  # 皴：斜下的弧笔
        i = rng.integers(10, len(o) - 10)
        x, y = o[i]
        ln = rng.uniform(40, 110)
        ang = math.radians(rng.uniform(55, 110))
        pts = [(x, y + 6), (x + math.cos(ang) * ln * 0.5 + rng.uniform(-10, 10), y + 6 + math.sin(ang) * ln * 0.5),
               (x + math.cos(ang) * ln, y + 6 + math.sin(ang) * ln)]
        P.stroke(curve_pts(pts, 20), np.linspace(2.6, 0.8, 20), NONG, 0.8, dry=0.55, dry_start=0.15, mode="glaze")
    for _ in range(26):
        i = rng.integers(0, len(o))
        x, y = o[i]
        r = rng.uniform(1.8, 4.5)
        P.dot(x + rng.normal(0, 6), y + rng.uniform(-2, 6), r * 1.4, r, JIAO, 0.9)


def paint_pine(P: Painting, rng):
    """老松：树根扎在右边大石里，树干 S 形向左上，一枝长枝横伸到主角头顶上方，一枝斜上出画；
    树干两边枯笔勾皮、中间罩淡墨、点几片鳞皮；松针一簇簇扇形，浓淡两遍。"""
    trunk = curve_pts([(1812, 800), (1790, 700), (1738, 610), (1716, 520), (1670, 440), (1610, 392)], 120)
    t = np.linspace(0, 1, len(trunk))
    hw = 26 - 12 * t
    nrm = np.gradient(trunk, axis=0)
    nrm = np.stack([-nrm[:, 1], nrm[:, 0]], -1) / (np.linalg.norm(nrm, axis=1, keepdims=True) + 1e-9)
    sl, cov = stroke_cover(P.X, P.Y, trunk, hw, rng, jitter=0.12)
    P.glaze(cov * 0.62 * (0.8 + 0.2 * noise(rng, cov.shape, 6.0)), mixc(DAN, ZHONG, 0.4), sl)
    for side, w0 in ((1, 4.8), (-1, 3.6)):
        edge = trunk + nrm * (hw[:, None] - 2.0) * side
        P.stroke(edge, np.interp(t, [0, 0.1, 0.8, 1], [2.0, w0, w0 * 0.8, 1.5]), JIAO, 0.95, dry=0.45, dry_start=0.25, jitter=0.3)
    for k in range(22):  # 鳞皮：树干上的小弧
        i = int(rng.uniform(4, len(trunk) - 8))
        c = trunk[i] + nrm[i] * rng.uniform(-0.6, 0.6) * hw[i]
        r = rng.uniform(4.5, 8.0) * (1 - 0.4 * t[i])
        a0 = rng.uniform(-0.5, 0.5)
        arc = np.stack([c[0] + r * np.cos(np.linspace(a0 + 0.6, a0 + 2.7, 10)), c[1] + r * 0.7 * np.sin(np.linspace(a0 + 0.6, a0 + 2.7, 10))], -1)
        P.stroke(arc, np.linspace(1.4, 0.6, 10), NONG, 0.8, dry=0.3, jitter=0.0, mode="glaze")
    branches = [
        ([(1622, 400), (1540, 372), (1450, 360), (1370, 368), (1290, 352)], 11, 2.5),
        ([(1690, 470), (1742, 400), (1800, 352), (1880, 318), (1960, 300)], 9, 3.0),
        ([(1735, 600), (1676, 586), (1610, 594)], 6, 2.0),
        ([(1500, 366), (1470, 330), (1430, 312)], 4, 1.5),
        ([(1380, 366), (1336, 392), (1300, 404)], 3.5, 1.2),
    ]
    tips = []
    for pts, w0, w1 in branches:
        c = curve_pts(pts, 60)
        P.stroke(c, np.linspace(w0, w1, 60), JIAO, 0.95, dry=0.35, dry_start=0.5, jitter=0.25)
        tips.append(c)
    # 松针簇（中心, 半径, 朝向°）——沿枝条分布，枝梢更密
    clusters = []
    for c in tips:
        for f in (0.25, 0.5, 0.75, 1.0):
            p = c[min(int(f * (len(c) - 1)), len(c) - 1)]
            clusters.append((p[0] + rng.normal(0, 6), p[1] + rng.normal(-6, 5), rng.uniform(28, 46)))
    clusters += [(1592, 352, 40), (1652, 418, 36), (1712, 548, 30), (1772, 640, 26)]
    for pass_ in (0, 1):  # 先淡后浓，有前后
        for cx, cy, r in clusters:
            col_ = mixc(DAN, ZHONG, 0.6) if pass_ == 0 else JIAO
            ox, oy = (rng.normal(0, 7), rng.normal(-5, 3)) if pass_ == 0 else (0.0, 0.0)
            rr = r * (1.15 if pass_ == 0 else 0.9)
            n = int(rng.integers(13, 19))
            for k in range(n):
                ang = math.radians(rng.uniform(-170, -10) if rng.random() < 0.82 else rng.uniform(-10, 20) * (1 if rng.random() < 0.5 else -1) + 180 * (rng.random() < 0.5))
                ln = rr * rng.uniform(0.55, 1.0)
                bx, by = cx + ox + rng.normal(0, 2), cy + oy + rng.normal(0, 2)
                bend = rng.uniform(-0.15, 0.15)
                ts = np.linspace(0, 1, 8)
                xx = bx + np.cos(ang + bend * ts) * ln * ts
                yy = by + np.sin(ang + bend * ts) * ln * ts * 0.75
                P.stroke(np.stack([xx, yy], -1), np.linspace(1.5, 0.35, 8), col_, 0.82 if pass_ else 0.55, jitter=0.0,
                         mode="glaze" if pass_ == 0 else "over")


def paint_grass(P: Painting, rng):
    """疏草：几丛细长的墨草，被风吹向左边（与主角的发带同向）；前景几丛大的。"""
    g = ground_edge_y(P.X[0])
    spots = [(1110, 0, 1.0), (1262, 2, 0.9), (1035, 18, 0.8), (930, 4, 0.7), (850, 6, 0.6), (1460, 4, 0.9), (1560, -2, 0.8),
             (1340, 40, 1.0), (1150, 60, 1.1), (700, 20, 0.7), (560, 60, 0.8), (1600, 70, 1.2), (980, 120, 1.4),
             (1700, 180, 1.8), (1300, 170, 1.6), (820, 150, 1.4)]
    for x, dy, s in spots:
        y = float(np.interp(x, P.X[0], g)) + dy + 3
        n = int(rng.integers(4, 8))
        for k in range(n):
            ln = s * rng.uniform(18, 46)
            lean = math.radians(rng.uniform(-38, 8))  # 负 = 向左倒
            bx = x + rng.normal(0, 4 * s)
            ts = np.linspace(0, 1, 12)
            curl = rng.uniform(0.2, 0.9) * (1 if lean < 0 else 0.4)
            xx = bx + np.sin(lean) * ln * ts - curl * 12 * s * ts ** 2
            yy = y - np.cos(lean) * ln * ts + 3 * s * ts ** 2
            hw = np.interp(ts, [0, 0.25, 1], [1.4 * s, 1.6 * s, 0.25]) * rng.uniform(0.7, 1.0)
            P.stroke(np.stack([xx, yy], -1), hw, JIAO if rng.random() < 0.7 else NONG, rng.uniform(0.75, 0.95), jitter=0.1)


# ============================================================== 标题画：渲染件、光与收尾


def ensure_parts(force: bool = False) -> dict:
    """主角背影和石灯笼（Blender）。缺文件或 force 时调 render/title_hero.py（子进程，固定 2 倍参数）。"""
    if force or not (PARTS / "parts.json").exists():
        subprocess.run([sys.executable, str(ART / "render" / "title_hero.py")], check=True)
    meta = json.loads((PARTS / "parts.json").read_text(encoding="utf-8"))
    for k in ("hero_back", "stone_lantern"):
        meta[k]["rgba"] = Image.open(PARTS / f"{k}.png").convert("RGBA")
        meta[k]["emit"] = Image.open(PARTS / f"{k}_emit.png").convert("RGBA")
    return meta


def place(P: Painting, img: Image.Image, anchor, at, scale: float = 1.0, emit: Image.Image | None = None,
          emit_gain: float = 1.0, dim: float = 1.0):
    """按锚点把一张直通 alpha 的图贴进画里（emit 叠进发光层）。返回 图内像素 → 画面像素 的换算函数。"""
    if scale != 1.0:
        size = (max(1, round(img.width * scale)), max(1, round(img.height * scale)))
        img = img.resize(size, Image.LANCZOS)
        emit = emit.resize(size, Image.LANCZOS) if emit is not None else None
    x0, y0 = round(at[0] - anchor[0] * scale), round(at[1] - anchor[1] * scale)
    a = np.asarray(img, np.float64) / 255.0
    xs0, ys0, xs1, ys1 = max(0, x0), max(0, y0), min(W, x0 + img.width), min(H, y0 + img.height)
    sub = a[ys0 - y0: ys1 - y0, xs0 - x0: xs1 - x0]
    sl = (slice(ys0, ys1), slice(xs0, xs1))
    P.over(sub[..., 3] * dim, sub[..., :3], sl)
    if emit is not None:
        e = np.asarray(emit, np.float64)[ys0 - y0: ys1 - y0, xs0 - x0: xs1 - x0] / 255.0
        P.emit[sl] += e[..., :3] * e[..., 3:4] * emit_gain
    return lambda px, py: (x0 + px * scale, y0 + py * scale)


def paint_wisp(P: Painting, x, y, s, rng, lights):
    """魂火：一小团向上收尖的冷光（白芯、淡青外焰），外面一圈辉光，并给光照图添一点冷光。"""
    r = int(60 * s)
    sl = (slice(max(0, int(y) - r), min(H, int(y) + r)), slice(max(0, int(x) - r), min(W, int(x) + r)))
    dx, dy = P.X[sl] - x, P.Y[sl] - y
    sway = 2.0 * s * np.sin(dy / (6.0 * s) + x)
    u = (dx - sway * smoothstep(0, -20 * s, dy)) / (5.5 * s)
    v = dy / (9.0 * s)
    # 水滴形：下圆上尖
    width = np.where(v < 0, np.clip(1 + v * 0.55, 0, 1) ** 1.3, np.sqrt(np.clip(1 - v * v, 0, 1)))
    body = smoothstep(1.05, 0.55, np.abs(u) / np.maximum(width, 1e-3)) * smoothstep(1.0, 0.85, v) * smoothstep(-1.9, -1.2, v)
    core = np.exp(-(u ** 2 + ((v - 0.25) / 0.7) ** 2) * 2.2)
    soul = col(S.SOUL_LIGHT)
    e = soul[None, None] * (body * 0.75)[..., None] + mixc(soul, np.ones(3), 0.6)[None, None] * (core * 0.9)[..., None]
    glow = np.exp(-(dx ** 2 + (dy + 4 * s) ** 2) / (2 * (16 * s) ** 2))
    e += soul[None, None] * (glow * 0.22)[..., None]
    P.emit[sl] += e
    lights.append((x, y, 120 * s, mixc(soul, col(S.NIGHT_AMBIENT), 0.25), 0.30))


def eyes_layer() -> tuple[Image.Image, Image.Image, tuple[float, float]]:
    """影妖精灵（2 倍）第 0 帧：本体、发光层，以及眼睛在图里的位置。"""
    base = ART / "out" / "assets@2x" / "shade"
    meta = json.loads((base / "meta.json").read_text(encoding="utf-8"))
    w, h = meta["size"]
    ax, ay = meta["anchor"][0] * w, meta["anchor"][1] * h
    ex, ey = meta["sockets"]["eyes"]["float"]["E"][0]
    return (Image.open(base / "float_E_00.png").convert("RGBA"), Image.open(base / "float_E_00_emit.png").convert("RGBA"),
            (ax + ex, ay + ey))


def light_map(P: Painting, lights, rng) -> np.ndarray:
    """光照图：夜色底（略有起伏）+ 月光（月亮附近最亮，往左下迅速沉下去）+ 各个暖光 / 冷光。
    暖光圈的边缘按水渍打散（半径随角度起伏、过渡带里有颗粒），不是一个规整的圆。"""
    amb = col(S.NIGHT_AMBIENT)
    lm = amb[None, None] * (1 + 0.18 * noise(rng, (H, W), (300.0, 120.0)))[..., None]
    mx, my, mr = MOON
    d = np.hypot(P.X - mx, (P.Y - my) * 1.15)
    moon_col = mixc(col("#C8D3E6"), col(S.PAPER), 0.25)
    moon = 0.05 + 0.26 * np.exp(-(d / 620.0) ** 2) + 0.40 * np.exp(-(d / 210.0) ** 2) + 0.35 * np.exp(-(d / 80.0) ** 2)
    lm += moon[..., None] * moon_col
    gran = noise(rng, (H, W), 3.0) * 0.5 + noise(rng, (H, W), 12.0) * 0.5
    for x, y, R, c, inten in lights:
        r0 = int(R * 1.25) + 4
        sl = (slice(max(0, int(y) - r0), min(H, int(y) + r0)), slice(max(0, int(x) - r0), min(W, int(x) + r0)))
        dx, dy = P.X[sl] - x, P.Y[sl] - y
        th = np.arctan2(dy, dx)
        k = 1 + 0.07 * np.sin(3 * th + x * 0.01) + 0.05 * np.sin(5 * th + 1.3) + 0.03 * np.sin(9 * th + y)
        rr = np.hypot(dx, dy) / (R * k)
        f = np.clip(1 - rr ** 2, 0, 1) ** 2
        f = f * (1 + 0.35 * gran[sl] * np.clip(4 * f * (1 - f), 0, 1))
        lm[sl] += np.clip(f, 0, 1.2)[..., None] * (np.asarray(c) * inten)[None, None]
    return lm


def bloom(e: np.ndarray, sigma: float) -> np.ndarray:
    return np.stack([blur(e[..., c], sigma) for c in range(3)], -1)


def paint_title(rng_seed: int = 2026, force_render: bool = False) -> tuple[Image.Image, dict]:
    t0 = time.perf_counter()
    parts = ensure_parts(force_render)
    t_parts = time.perf_counter() - t0
    rng = np.random.default_rng(rng_seed)
    P = Painting(rng)
    paper0 = P.rgb.copy()
    paint_sky(P, rng)
    paint_mountains(P, rng)
    paint_ground(P, rng)
    paint_rock(P, rng, [(1592, 838), (1630, 790), (1690, 760), (1760, 742), (1840, 722), (1900, 716), (1960, 722)])
    paint_rock(P, rng, [(-20, 1000), (60, 975), (150, 985), (230, 1015), (300, 1060), (330, 1100)], alpha=0.45)
    paint_pine(P, rng)
    paint_grass(P, rng)
    lights = []
    # 石灯笼（远的先画）
    sl_meta = parts["stone_lantern"]
    for x, y, s in sorted(STONE_LANTERNS, key=lambda t: t[1]):
        wash_blob(P, x + 4, y + 2, 46 * s * 1.4, 10 * s * 1.4, ZHONG, 0.5, rng)
        to = place(P, sl_meta["rgba"], sl_meta["feet"], (x, y), s, sl_meta["emit"], emit_gain=0.85)
        fx, fy = to(*sl_meta["flame"])
        lights.append((fx, fy, 170 * s, col(S.FLAME_LIGHT), 0.55))
    # 主角：脚下一团淡墨影
    hb = parts["hero_back"]
    wash_blob(P, HERO_FEET[0] + 6, HERO_FEET[1] + 2, 58, 13, ZHONG, 0.55, rng)
    to = place(P, hb["rgba"], hb["feet"], HERO_FEET, 1.0, hb["emit"], emit_gain=1.25)
    lx, ly = to(*hb["lantern"])
    lights.append((lx, ly, 520.0, mixc(col(S.LANTERN_LIGHT), np.ones(3), 0.30), 1.0))
    lights.append((lx, ly, 150.0, col(S.LANTERN_LIGHT), 0.35))
    # 黑暗里的妖：影妖本体几乎看不见，只剩眼睛
    body, emit, (ex, ey) = eyes_layer()
    for x, y, s, flip in EYES:
        b, e_ = (body.transpose(Image.FLIP_LEFT_RIGHT), emit.transpose(Image.FLIP_LEFT_RIGHT)) if flip else (body, emit)
        ax = (body.width - ex) if flip else ex
        place(P, b, (ax, ey), (x, y), s, e_, emit_gain=1.5, dim=0.9)
    for x, y, s in WISPS:
        paint_wisp(P, x, y, s, rng, lights)
    # ---- 打光：画 × 光照图 + 发光层 + 辉光
    lm = light_map(P, lights, rng)
    out = P.rgb * np.clip(lm, 0, 1.08)
    e = P.emit
    out = out * (1 - np.clip(e.max(-1, keepdims=True), 0, 1) * 0.6) + e + 0.55 * bloom(e, 5.0) + 0.45 * bloom(e, 22.0)
    # 灯笼本身的光晕（大而淡）
    dl = np.hypot(P.X - lx, P.Y - ly)
    out += (np.exp(-(dl / 90.0) ** 2) * 0.10)[..., None] * col(S.LANTERN_LIGHT)
    # ---- 收尾：纸纹在暗处也看得见、四角压暗、左边更沉
    rel = paper0.mean(-1) / paper0.mean()
    out = out * (1 + 0.9 * (rel - 1))[..., None] + (0.012 * (rel - 1))[..., None]
    rx = (P.X - W * 0.62) / (W * 0.62)
    ry = (P.Y - H * 0.48) / (H * 0.62)
    vig = 1 - 0.42 * smoothstep(0.55, 1.35, np.hypot(rx, ry))
    vig *= 1 - 0.22 * smoothstep(0.45, 0.0, P.X / W)
    out = out * vig[..., None]
    img = Image.fromarray((np.clip(out, 0, 1) * 255 + 0.5).astype(np.uint8), "RGB")
    info = {"lantern_px": [round(lx, 1), round(ly, 1)], "time_s": round(time.perf_counter() - t0, 1),
            "parts_s": round(t_parts, 1), "render_timings": parts.get("timings", {})}
    return img, info


