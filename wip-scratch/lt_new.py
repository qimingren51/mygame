# ============================================================== 孔明灯、镇妖塔：Blender 渲的源图 + 2D 后期

SRC = V.OUT / "assets@2x"  # render/weapons_ea_render.py 渲的源图：ea_<名字>/<动画>_S_<NN>.png + _emit.png
EMIT_ALPHA = (0.3, 0.75)  # 发光层的强度：按亮度从最暗的发光色到最亮的压（整张纸都发光，不压的话夜里是一团白）


def src_rgba(asset: str, stem: str) -> tuple[np.ndarray, np.ndarray]:
    """读一帧源图（普通层、发光层），没有就提示先跑 Blender 那一步。"""
    d = SRC / f"ea_{asset}"
    p = d / f"{stem}.png"
    if not p.exists():
        raise FileNotFoundError(f"缺 {p}：先跑 art/.venv/bin/python art/render/weapons_ea_render.py --only {asset}")
    im = np.asarray(Image.open(p).convert("RGBA")).astype(np.float64) / 255.0
    e = d / f"{stem}_emit.png"
    em = np.asarray(Image.open(e).convert("RGBA")).astype(np.float64) / 255.0 if e.exists() else np.zeros_like(im)
    return im, em


def soften_emit(em: np.ndarray, gain: float = 1.0, k=EMIT_ALPHA) -> np.ndarray:
    """发光层的 alpha 按颜色亮度压到 k[0]..k[1]（再乘 gain），颜色不动。"""
    lum = em[..., :3].mean(-1)
    on = em[..., 3] > 0
    if not on.any():
        return em
    lo, hi = np.percentile(lum[on], 5), np.percentile(lum[on], 95)
    t = np.clip((lum - lo) / max(hi - lo, 1e-6), 0, 1)
    out = em.copy()
    out[..., 3] = np.clip(em[..., 3] * (k[0] + (k[1] - k[0]) * t) * gain, 0, 1)
    return out


def to_image(arr: np.ndarray) -> Image.Image:
    """0..1 的直通 RGBA → 8 位（透明处的颜色往外扩，免得线性过滤出黑边），四边一圈清掉。"""
    a = np.clip(arr[..., 3], 0, 1)
    a8 = np.clip(np.round(a * 255), 0, 255).astype(np.uint8)
    a8[0, :] = a8[-1, :] = a8[:, 0] = a8[:, -1] = 0
    return V.to_rgba8(np.clip(arr[..., :3], 0, 1), None, a8)


def shift_scale(arr: np.ndarray, anchor_px, dy: float = 0.0, sx: float = 1.0, sy: float = 1.0, out_hw=None) -> np.ndarray:
    """以锚点为中心缩放（sx、sy），再往上挪 dy 像素；双线性、预乘 alpha 采样。out_hw 给出时换画布大小（锚点像素不变）。"""
    h, w = arr.shape[:2]
    oh, ow = out_hw or (h, w)
    ax, ay = anchor_px
    yy, xx = np.mgrid[0:oh, 0:ow] + 0.5
    src_x = (xx - ax) / sx + ax
    src_y = (yy - ay + dy) / sy + ay
    prem = np.dstack([arr[..., :3] * arr[..., 3:4], arr[..., 3:4]])
    x0, y0 = np.floor(src_x - 0.5).astype(int), np.floor(src_y - 0.5).astype(int)
    fx, fy = src_x - 0.5 - x0, src_y - 0.5 - y0
    out = np.zeros((oh, ow, 4))
    for dy_, dx_, wgt in ((0, 0, (1 - fx) * (1 - fy)), (0, 1, fx * (1 - fy)), (1, 0, (1 - fx) * fy), (1, 1, fx * fy)):
        yi, xi = y0 + dy_, x0 + dx_
        ok = (yi >= 0) & (yi < h) & (xi >= 0) & (xi < w)
        v = np.zeros((oh, ow, 4))
        v[ok] = prem[yi[ok], xi[ok]]
        out += v * wgt[..., None]
    a = out[..., 3:4]
    return np.dstack([np.where(a > 1e-6, out[..., :3] / np.maximum(a, 1e-6), 0.0), a])


# ---------------------------------------------------------------- 孔明灯

LT_FLICKER = [1.0, 0.86, 0.96, 0.9]  # 飘着时灯火一明一暗


def _lantern_frames(kind: str) -> tuple[list, list]:
    if kind == "float":
        stems = [f"float_S_{i:02d}" for i in range(4)]
        gains = LT_FLICKER
    else:
        stems = [f"fall_S_{i:02d}" for i in range(3)]
        gains = [1.1, 1.2, 1.3]  # 烧起来更亮
    base, glow = [], []
    for st, g in zip(stems, gains):
        im, em = src_rgba("sky_lantern", st)
        base.append(to_image(im))
        glow.append(to_image(soften_emit(em, g)))
    return base, glow


@lru_cache(maxsize=None)
def _lantern(kind: str):
    return _lantern_frames(kind)


def make_sky_lantern() -> list[Image.Image]:
    return list(_lantern("float")[0])


def make_sky_lantern_emit() -> list[Image.Image]:
    return list(_lantern("float")[1])


def make_sky_lantern_fall() -> list[Image.Image]:
    return list(_lantern("fall")[0])


def make_sky_lantern_fall_emit() -> list[Image.Image]:
    return list(_lantern("fall")[1])


MARK_W, MARK_H = 352, 224
MARK_R = 144.0  # 圈的横向半径（像素）= 爆燃半径；1080p 下 56 单位一比一


def make_lantern_mark() -> list[Image.Image]:
    """孔明灯的落点圈：地上一圈干笔画的圆（按地面透视压扁），断成三四截，四个方向各一道往里指的短笔，
    正中一个小十字。白色可染（游戏染暗红、越接近落地越亮、慢慢收紧），叠加；radius_px 是圈的横向半径。"""
    w, h = MARK_W, MARK_H
    cx, cy = w / 2, h / 2
    rng = np.random.default_rng(9801)
    tex = W.ptex(rng, ns=24, nt=2048, along=40.0, across=0.6)
    X, Y = grid(w, h)
    gx, gy = X - cx, (Y - cy) / F.FLAT
    r = np.hypot(gx, gy)
    th = np.arctan2(gy, gx)
    a = []
    t = (th / (2 * math.pi)) % 1.0
    gaps = smoothstep(0.0, 0.02, np.abs(((t * 3.5 + 0.15) % 1.0) - 0.5) - 0.42)  # 断成几截
    ring = np.exp(-(((r - MARK_R) / 3.2) ** 2))
    a.append(0.9 * ring * dry(tex, np.clip((r - MARK_R) / 6, -1, 1), t, 0.28) * (1 - 0.85 * (1 - gaps)))
    a.append(0.3 * np.exp(-(((r - MARK_R + 10) / 2.0) ** 2)) * dry(tex, 0.4, t + 0.3, 0.55))  # 里面一道淡的
    for k in range(4):  # 往里指的短笔
        ang = math.pi / 4 + k * math.pi / 2
        x0, y0 = cx + (MARK_R + 6) * math.cos(ang), cy + (MARK_R + 6) * math.sin(ang) * F.FLAT
        x1, y1 = cx + (MARK_R - 22) * math.cos(ang), cy + (MARK_R - 22) * math.sin(ang) * F.FLAT
        a.append(0.85 * streak(X, Y, x0, y0, x1, y1, 3.0))
    for ang, L in ((0.0, 12.0), (math.pi / 2, 12.0 * F.FLAT)):  # 正中的小十字（竖的一笔按透视短一点）
        c1, _ = needle(X, Y, cx, cy, ang, L, 1.6, taper=1.0)
        c2, _ = needle(X, Y, cx, cy, ang + math.pi, L, 1.6, taper=1.0)
        a.append(0.6 * np.maximum(c1, c2))
    return [F.frame_white(soft_union(*a), 9805)]


SEA_W, SEA_H = 352, 224
SEA_R = 120.0  # 火海的横向半径（像素）= 0.8 × 爆燃半径；1080p 下 47 单位一比一


def make_fire_sea() -> list[Image.Image]:
    """孔明灯落地后的火海：地上一片低矮的火苗（按地面透视压扁的椭圆里散着四十来簇小火舌，尖往上翘），
    中间一层暗红的余烬光，火星往上飘。4 帧循环（12 帧/秒）：火舌一伸一缩、左右摆。叠加，自带火色，不染；
    radius_px 是火海的横向半径。"""
    w, h = SEA_W, SEA_H
    cx, cy = w / 2, h / 2
    rng = np.random.default_rng(9811)
    flames = []
    for _ in range(46):
        rr = SEA_R * math.sqrt(rng.uniform(0.0, 1.0)) * 0.92
        ang = rng.uniform(0, 2 * math.pi)
        flames.append((cx + rr * math.cos(ang), cy + rr * math.sin(ang) * F.FLAT, rng.uniform(10, 22) * (1.1 - 0.4 * rr / SEA_R),
                       rng.uniform(2.6, 4.2), rng.uniform(0, 2 * math.pi), int(rng.integers(1 << 30))))
    flames.sort(key=lambda f: f[1])
    embers = [(rng.uniform(-1, 1) * SEA_R * 0.8, rng.uniform(-1, 1) * SEA_R * 0.45, rng.uniform(0, 1), rng.uniform(0.8, 1.3)) for _ in range(14)]
    nz = V.noise(rng, (h, w), 6.0)
    out = []
    for i in range(4):
        ph = 2 * math.pi * i / 4
        X, Y = grid(w, h)
        acc = F.Acc(X, Y)
        full = (slice(None), slice(None))
        gx, gy = X - cx, (Y - cy) / F.FLAT
        rr = np.hypot(gx, gy) / SEA_R
        bed = smoothstep(1.0, 0.55, rr) * (0.45 + 0.25 * np.clip(bilerp(nz, X + 3 * math.sin(ph), Y), -1, 1))
        acc.add(full, 0.5 * bed, 0.2)  # 余烬：暗红的底
        for fx, fy, L0, wd, fph, sd in flames:
            L = L0 * (0.8 + 0.25 * math.sin(ph + fph))
            sway = 2.5 * math.sin(ph * 1.0 + fph * 1.7)
            pts = V.bezier([(fx, fy), (fx + sway * 0.4, fy - L * 0.5), (fx + sway, fy - L)], 30)
            tt = np.linspace(0, 1, len(pts))
            hw = wd * (1 - tt) ** 0.8 * (0.7 + 0.3 * np.sin(np.pi * np.clip(tt * 2, 0, 1))) + 0.1
            sl = acc.window(fx - wd * 3 - 4, fy - L - 4, fx + wd * 3 + 4, fy + wd * 2)
            cov, f_ = V.brush_stroke(X[sl], Y[sl], pts, hw, np.random.default_rng(sd), dry=0.25, dry_start=0.55, ss=SS)
            acc.add(sl, 0.95 * cov, np.clip(0.95 - 0.8 * f_["t"], 0, 1))
        for ex, ey, p0, sz in embers:
            t = (i / 4 + p0) % 1.0
            px, py = cx + ex, cy + ey * F.FLAT - 10 - 40 * t
            sl = acc.window(px - 4, py - 4, px + 4, py + 10)
            acc.add(sl, 0.8 * math.sin(math.pi * t) * streak(X[sl], Y[sl], px, py + 6, px, py, sz), 0.75)
        out.append(F.frame_color(acc.a, acc.heat(), 9815 + i, F.FIRE))
    return out


# ---------------------------------------------------------------- 镇妖塔 / 玲珑塔

TOWER_PAD = 24  # 源图下面再垫几行（基座前角离画布底太近）
# 落下 3 帧：(往上挪多少世界单位, 竖向拉长, 横向, 透明度)；收走 3 帧：(往上挪, 消散到哪 0..1, 金光)
TW_FALL = [(26.0, 1.16, 0.95, 0.8), (7.0, 1.05, 0.98, 0.95), (0.0, 0.93, 1.05, 1.0)]
TW_LIFT = [(1.5, 0.0, 1.0), (10.0, 0.42, 0.75), (24.0, 0.8, 0.45)]


def _tower_src(asset: str):
    m = json.loads((SRC / f"ea_{asset}" / "meta.json").read_text(encoding="utf-8"))
    size = m["size"][0]
    anc = (m["anchor"][0] * size, m["anchor"][1] * size)
    frames = [src_rgba(asset, f"idle_S_{i:02d}") for i in range(2)]
    pad = lambda a: np.concatenate([a, np.zeros((TOWER_PAD, a.shape[1], 4))], 0)  # noqa: E731
    return [(pad(im), pad(em)) for im, em in frames], anc, size


@lru_cache(maxsize=None)
def _tower(asset: str):
    """一座塔的全部帧：idle 2 帧（铃铛摆）、落下 3 帧、收走 3 帧，每帧（普通层, 发光层）。"""
    frames, anc, size = _tower_src(asset)
    rng = np.random.default_rng(9831 if asset == "tower" else 9832)
    h, w = frames[0][0].shape[:2]
    idle = [(to_image(im), to_image(soften_emit(em, 1.0, (0.55, 0.9)))) for im, em in frames]
    im0, em0 = frames[0]
    fall = []
    for dy_u, sy, sx, op in TW_FALL:  # 从天上砸下来：拉长、往下挪，后面拖几道墨的速度线
        im = shift_scale(im0, anc, dy=dy_u * F.PPU, sx=sx, sy=sy)
        em = shift_scale(soften_emit(em0, 1.0, (0.55, 0.9)), anc, dy=dy_u * F.PPU, sx=sx, sy=sy)
        im[..., 3] *= op
        if dy_u > 0:  # 塔身上方几道竖的速度线（焦墨、干笔）
            X, Y = np.mgrid[0:h, 0:w][::-1]
            top = np.nonzero(im[..., 3].max(1) > 0.3)[0].min()
            lines = np.zeros((h, w))
            for k in range(7):
                x = anc[0] + (k - 3) * size * 0.05 + rng.uniform(-4, 4)
                L = dy_u * F.PPU * rng.uniform(0.6, 1.1)
                d = np.abs(X + 0.5 - x)
                yy = Y + 0.5
                on = (yy < top + 20) & (yy > top + 20 - L)
                lines = np.maximum(lines, on * smoothstep(1.4, 0.4, d) * (1 - (top + 20 - yy) / max(L, 1)) * 0.6)
            ink = np.dstack([np.broadcast_to(F.JIAO, (h, w, 3)), lines])
            a_new = im[..., 3] + ink[..., 3] * (1 - im[..., 3])
            rgb = (im[..., :3] * im[..., 3:4] + ink[..., :3] * ink[..., 3:4] * (1 - im[..., 3:4])) / np.maximum(a_new[..., None], 1e-6)
            im = np.dstack([rgb, a_new])
        fall.append((to_image(im), to_image(em)))
    lift = []
    noise = V.noise(rng, (h, w), 5.0)
    rows = np.nonzero(im0[..., 3].max(1) > 0.3)[0]
    y_top, y_bot = rows.min(), rows.max()
    for dy_u, dis, glow in TW_LIFT:  # 收走：往上升、从下往上散成金色的光点
        im = shift_scale(im0, anc, dy=dy_u * F.PPU)
        em = shift_scale(soften_emit(em0, 1.0, (0.55, 0.9)), anc, dy=dy_u * F.PPU)
        yy = np.mgrid[0:h, 0:w][0] + 0.5
        cut = y_bot - dy_u * F.PPU - dis * (y_bot - y_top) * 1.05  # 这一行以下散掉
        level = (cut - yy) / 18.0 + 0.5 * noise  # >0 的散掉
        keep = smoothstep(0.15, -0.15, level)
        edge = np.exp(-((level / 0.35) ** 2)) * (im[..., 3] > 0.05) * (dis > 0)
        im[..., 3] *= keep
        em[..., 3] = np.clip(em[..., 3] * keep + 0.75 * edge * (dis > 0), 0, 1)
        em[..., :3] = np.where(edge[..., None] > 0.05, V.col("#FFE7A8"), em[..., :3])
        if glow > 0:  # 整座塔描一圈金边（收走前一亮）
            a = im[..., 3]
            rim = np.clip(V.fft_blur(a, 2.0) - a * 0.6, 0, 1) * glow * 0.6
            em[..., :3] = np.where(rim[..., None] > 0.02, V.col("#FFE7A8"), em[..., :3])
            em[..., 3] = np.clip(em[..., 3] + rim, 0, 1)
        lift.append((to_image(im), to_image(em)))
    anc_out = (anc[0] / w, anc[1] / h)
    return {"idle": idle, "fall": fall, "lift": lift, "anchor": anc_out, "size": (w, h)}


def _tower_maker(asset: str, kind: str, layer: int):
    def make() -> list[Image.Image]:
        return [fr[layer] for fr in _tower(asset)[kind]]
    return make


DUST_W, DUST_H = 416, 272
DUST_R = 160.0  # 末帧尘环的横向半径（像素）≈ 落地半径；1080p 下 62 单位一比一
DUST_INK = "#6E6253"  # 尘土：淡墨里带一点赭


def make_tower_dust() -> list[Image.Image]:
    """镇妖塔落地的尘土冲击波：一圈尘团从塔底往外滚开（按地面透视压扁），越滚越大、越淡、越散，
    外沿几粒碎石往外蹦。普通混合，土墨色 #6E6253，不染；radius_px 是末帧尘环的横向半径，按落地半径缩放。"""
    w, h = DUST_W, DUST_H
    cx, cy = w / 2, h / 2
    rng = np.random.default_rng(9841)
    puffs = [(2 * math.pi * (k + rng.uniform(-0.3, 0.3)) / 26, rng.uniform(0.8, 1.15), rng.uniform(0, 1)) for k in range(26)]
    stones = [(rng.uniform(0, 2 * math.pi), rng.uniform(0.9, 1.25), rng.uniform(1.0, 1.8)) for _ in range(16)]
    nz = V.noise(rng, (h, w), 3.0)
    Rk = [0.32, 0.55, 0.74, 0.88, 0.96, 1.0]
    env = [0.9, 0.85, 0.72, 0.55, 0.36, 0.18]
    out = []
    for i in range(6):
        X, Y = grid(w, h)
        acc = F.Acc(X, Y)
        R = DUST_R * Rk[i]
        for ang, rf, sz in puffs:
            r0 = R * rf
            px, py = cx + r0 * math.cos(ang), cy + r0 * math.sin(ang) * F.FLAT
            pr = (10 + 14 * sz) * (0.7 + 0.5 * Rk[i])
            sl = acc.window(px - pr * 1.6, py - pr * 1.2, px + pr * 1.6, py + pr * 1.2)
            d = np.hypot((X[sl] - px) / (pr * 1.25), (Y[sl] - py) / (pr * 0.85))
            n = bilerp(nz, X[sl] + 13 * i, Y[sl])
            acc.add(sl, env[i] * smoothstep(1.0, 0.45, d + 0.25 * n) * (0.55 + 0.25 * n))
        for ang, rf, sz in stones:
            if i == 0:
                continue
            r0 = R * rf + 6 * i
            px, py = cx + r0 * math.cos(ang), cy + r0 * math.sin(ang) * F.FLAT - 8 * math.sin(math.pi * i / 6)
            sl = acc.window(px - 4, py - 4, px + 4, py + 4)
            acc.add(sl, (1 - i / 7) * F.dot(X[sl], Y[sl], px, py, sz))
        out.append(F.frame_ink(acc.a, 9845 + i))
    # 换成土墨色（frame_ink 是焦墨）
    col = V.col(DUST_INK)
    return [V.to_rgba8(col, None, np.asarray(im)[..., 3]) for im in out]


VORTEX_W, VORTEX_H = 768, 480
VORTEX_R = 360.0  # 旋涡的横向半径（像素）= 吸的范围；1080p 下 140 单位一比一（玲珑塔的 500 要放大三倍多，它本来就淡）


def make_tower_vortex() -> list[Image.Image]:
    """镇妖塔吸妖的范围：地上一圈淡淡的旋涡（按地面透视压扁），六道螺旋的笔触往里卷，外沿一圈断续的细线，
    越往中心越淡（塔在中间）。4 帧循环（12 帧/秒），螺旋往里转。叠加，白色可染（游戏染土色 #C9925A）；
    radius_px 是旋涡的横向半径（= 吸的范围），按范围缩放。"""
    w, h = VORTEX_W, VORTEX_H
    cx, cy = w / 2, h / 2
    rng = np.random.default_rng(9851)
    tex = W.ptex(rng, ns=32, nt=2048, along=50.0, across=0.6)
    out = []
    for i in range(4):
        X, Y = grid(w, h)
        acc = F.Acc(X, Y)
        full = (slice(None), slice(None))
        gx, gy = X - cx, (Y - cy) / F.FLAT
        r = np.hypot(gx, gy) / VORTEX_R
        th = np.arctan2(gy, gx)
        rot = 2 * math.pi * (i / 4) / 6  # 4 帧转过一条螺旋的间隔：首尾接得上
        m = (r > 0.12) & (r < 1.04)
        rm, thm = r[m], th[m]
        # 六道往里卷的螺旋：相位 = 角度 + 卷度 × ln(r)
        phase = 6 * (thm + rot) + 6.0 * np.log(np.maximum(rm, 1e-3))
        arm = (0.5 + 0.5 * np.cos(phase)) ** 6
        fade = smoothstep(0.12, 0.45, rm) * smoothstep(1.04, 0.86, rm)
        streaks = dry(tex, np.clip(np.cos(phase) * 1.5, -1, 1), (thm / (2 * math.pi)) % 1.0 + rm * 0.3, 0.35)
        acc.add(m, 0.55 * arm * fade * streaks)
        rim = np.exp(-(((rm - 0.98) / 0.012) ** 2))
        gaps = smoothstep(0.0, 0.05, np.abs(((thm / (2 * math.pi)) * 9 + i / 4) % 1.0 - 0.5) - 0.12)  # 4 帧挪一格，接得上
        acc.add(m, 0.5 * rim * gaps)
        out.append(F.frame_white(acc.a, 9855 + i))
    return out


