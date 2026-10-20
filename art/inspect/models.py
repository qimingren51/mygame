"""检视模型的建模：每件一个函数，注册在 MODELS 里（id 同 assets/data 里的 id）。

每个函数在当前（已清空的）场景里建零件（kit.part 登记节点、描边、贴图密度），返回一份说明 dict：
  atlases  贴图集：{名字: {size, channels, ao_dist, nodes}}，nodes 里的节点共用这套贴图（一套 UV）
  nodes    节点：{名字: {parent, pivot, shape_keys, uv: "smart" | "premade", bake_hide}}
  instances  实例：{新节点: (源节点, 位置, 欧拉角, 欧拉顺序)}，共用网格
  anim     idle 动画：frames、fps、spin / swing / keys
  review   审图：特写的镜头
造型以卡面插画为准（render/card_weapons.py、card_props.py），四面都做了细节：检视时可以转到任意角度、放大看。
"""

from __future__ import annotations

import math

import numpy as np

import kit
from kit import K, PMat

MODELS: dict[str, callable] = {}
# 审图的特写：(标题, 看向的点（米，建模坐标）, 镜头距离（米）, 方位角, 仰角)；方位角 0 = 正面（-Y），正 = 从右侧（+X）看
REVIEW: dict[str, dict] = {
    "sword": {"closeups": [("刃口与锻纹", (0.47, -0.004, 0.012), 0.085, -22.0, 28.0),
                           ("符纸", (0.215, -0.020, -0.004), 0.15, -12.0, 8.0),
                           ("剑格与宝石", (0.003, -0.011, 0.0), 0.10, -20.0, 12.0),
                           ("木柄、缠绳与剑穗", (-0.115, -0.004, -0.030), 0.20, 28.0, 10.0)],
              "detail_gif": 0},
    "wind_wheel": {"closeups": [("轮圈铸纹", (-0.140, -0.012, 0.078), 0.10, -14.0, 10.0),
                                ("火舌", (-0.262, -0.006, -0.030), 0.17, -10.0, 6.0),
                                ("莲花轮毂与火珠", (-0.072, -0.030, -0.040), 0.11, -14.0, 10.0),
                                ("飘带布纹", (-0.170, 0.030, -0.215), 0.13, -8.0, 4.0)],
                   "detail_gif": 0},
}


def model(mid):
    def deco(fn):
        MODELS[mid] = fn
        return fn

    return deco


def ss(e0, e1, x):
    t = np.clip((np.asarray(x, np.float64) - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3 - 2 * t)


def sstep(e0, e1, x):
    return float(ss(e0, e1, x))


def wavy(seed, n=6, lo=0.0015, hi=0.006, amp=1.0):
    """几道随机正弦叠起来的一维起伏（毛边、手缠的不匀）：f(x) → 约 ±amp。"""
    rng = np.random.default_rng(seed)
    ks = 2 * math.pi / rng.uniform(lo, hi, n)
    ph = rng.uniform(0, 2 * math.pi, n)
    w = rng.uniform(0.5, 1.0, n)
    w = w / w.sum()

    def f(x):
        return amp * float(np.sum(w * np.sin(ks * x + ph)))

    return f


# ====================================================================== 符剑：尺寸（米）
# 剑沿 +X（剑尖 +X，剑格在 x≈0），宽度沿 Z，厚度沿 Y；正面（贴符的一面）朝 -Y。
SW_L, SW_W, SW_T = 0.74, 0.040, 0.0085  # 剑身长、根部宽、脊厚（同卡面）
SW_TIP, SW_TAPER = 0.10, 0.15
GRIP_X0, GRIP_LEN = -0.0125, 0.150  # 剑柄从护手的柄侧开始往 -X
POMMEL_X = GRIP_X0 - GRIP_LEN  # 剑首的起点
NICKS_TOP = [(0.212, 0.00055, 0.0018), (0.505, 0.00070, 0.0022)]
NICKS_BOT = [(0.441, 0.00060, 0.0020)]
TALI_X0, TALI_GLUE, TALI_W = 0.312, 0.098, 0.030  # 符纸贴在剑脊上的起点、贴住的长度、宽


def blade_hw0(x):
    t = x / SW_L
    base = SW_W / 2 * (1 - SW_TAPER * t)
    if t > 1 - SW_TIP:
        s = min(max((t - (1 - SW_TIP)) / SW_TIP, 0.0), 1.0)
        base *= max(1 - s ** 1.7, 0.0) ** 0.75
    return max(base, 0.00025)


def blade_dims(x):
    """剑身截面：半宽、脊半厚、刃口宽、刃口内线半厚、刃尖半厚。"""
    hw0 = blade_hw0(x)
    k = hw0 / (SW_W / 2)
    th = SW_T / 2 * (1 - 0.35 * x / SW_L) * k ** 0.35
    be = min(0.0034 * k ** 0.6, 0.45 * hw0)
    te = th * 0.27
    ye = 0.00012 * min(1.0, k * 1.6)
    return hw0, th, be, te, ye


def _nick(x, lst):
    return sum(d * math.exp(-(((x - c) / w) ** 2)) for c, d, w in lst)


def blade_surface_y(x, z):
    """剑身正面（-Y）在 (x, z) 处的 y（刃口内线以内的斜面）。"""
    hw0, th, be, te, _ = blade_dims(x)
    inner = max(hw0 - be, 1e-6)
    a = min(abs(z) / inner, 1.0)
    return -(th - (th - te) * a)


def blade_build():
    """剑身：十个点的截面（中脊、两道斜面、两道开刃的刃口、刃尖一窄条），沿长取样，崩口处加密。
    面属性 facet：0 斜面、1 刃口、2 刃尖窄条；side：-1 正面、1 背面、0 刃尖。UV = (x, z)（米）。"""
    feats = [c for c, _, _ in NICKS_TOP + NICKS_BOT]
    xs = kit.adaptive_samples(0.0, SW_L * 0.997, 0.012, feats, fine=0.0010, reach=0.0026)
    tip_xs = np.arange(SW_L * (1 - SW_TIP), SW_L * 0.997, 0.0040)
    xs = np.unique(np.concatenate([xs, tip_xs]))
    facet_of = [1, 0, 0, 1, 2, 1, 0, 0, 1, 2]
    side_of = [-1, -1, -1, -1, 0, 1, 1, 1, 1, 0]

    def build(bm):
        import bmesh  # noqa: PLC0415

        uvl = bm.loops.layers.uv.new("UVMap")
        fa = kit.bm_face_attr(bm, "facet")
        sa = kit.bm_face_attr(bm, "side")
        rings = []
        for x in xs:
            hw0, th, be, te, ye = blade_dims(x)
            ht = max(hw0 - _nick(x, NICKS_TOP), hw0 * 0.6)
            hb = max(hw0 - _nick(x, NICKS_BOT), hw0 * 0.6)
            inner = hw0 - be
            sec = [(-ye, ht), (-te, inner), (-th, 0.0), (-te, -inner), (-ye, -hb), (ye, -hb), (te, -inner), (th, 0.0),
                   (te, inner), (ye, ht)]
            rings.append([bm.verts.new((float(x), y, z)) for y, z in sec])
        tipv = bm.verts.new((SW_L, 0.0, 0.0))
        k = 10
        for i in range(len(rings) - 1):
            for j in range(k):
                vs = (rings[i][j], rings[i + 1][j], rings[i + 1][(j + 1) % k], rings[i][(j + 1) % k])
                f = bm.faces.new(vs)
                for lp in f.loops:
                    lp[uvl].uv = (lp.vert.co.x, lp.vert.co.z)
                f[fa], f[sa] = facet_of[j], side_of[j]
        for j in range(k):
            f = bm.faces.new((rings[-1][j], tipv, rings[-1][(j + 1) % k]))
            for lp in f.loops:
                lp[uvl].uv = (lp.vert.co.x, lp.vert.co.z)
            f[fa], f[sa] = facet_of[j], side_of[j]
        f = bm.faces.new(list(reversed(rings[0])))
        f[fa], f[sa] = 0, 0
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
        for e in bm.edges:
            a, b = e.verts
            if a is tipv or b is tipv:
                e.smooth = False
                continue
            if abs(a.co.x - b.co.x) > 1e-7:  # 沿长的棱：截面的拐点，斜面之间不平滑
                e.smooth = False

    return build


# ---------------------------------------------------------------------- 剑格
GD_ZG, GD_ZC = 0.041, 0.031


def guard_xr(az):
    """剑格的轮廓（正面看，x 沿剑、z 横）：|z| 处的 (柄侧 xa, 剑侧 xb, 收圆系数 f)。
    中间朝剑身伸出一个尖（护住剑根），两翼往剑尖方向卷，翼端收圆。"""
    beak = 0.0058 * (1 - sstep(0.0, 0.019, az))
    curl = 0.0105 * sstep(0.017, GD_ZG, az) ** 2
    xb = 0.0072 + beak + curl
    xa = -0.0108 - 0.0022 * (1 - sstep(0.0, 0.013, az)) + 0.0050 * sstep(0.012, GD_ZG, az) ** 1.4
    f = 1.0
    if az > GD_ZC:
        f = math.sqrt(max(0.0, 1 - ((az - GD_ZC) / (GD_ZG - GD_ZC)) ** 2))
    return xa, xb, f


def guard_build(nz=58, ns=12):
    """剑格：轮廓里的一块“枕头”，正反两面 y = ±厚度·超椭圆，边缘圆润；翼端收成一点。"""

    def build(bm):
        import bmesh  # noqa: PLC0415

        zs = GD_ZG * np.sin(np.linspace(-math.pi / 2, math.pi / 2, nz))
        grids = []
        for sgn in (-1.0, 1.0):
            g = []
            for z in zs:
                xa, xb, f = guard_xr(abs(z))
                xm, half = (xa + xb) / 2, (xb - xa) / 2 * f
                ty = (0.0108 - 0.0036 * sstep(0.0, GD_ZG, abs(z))) * (f ** 0.5)
                row = []
                for s in np.linspace(0, 1, ns):
                    q = abs(2 * s - 1)
                    y = sgn * ty * max(0.0, 1 - q ** 4) ** 0.25
                    row.append(bm.verts.new((xm + (s - 0.5) * 2 * half, y, float(z))))
                g.append(row)
            grids.append(g)
        for g, flip in ((grids[0], False), (grids[1], True)):
            for i in range(nz - 1):
                for j in range(ns - 1):
                    vs = [g[i][j], g[i][j + 1], g[i + 1][j + 1], g[i + 1][j]]
                    if flip:
                        vs.reverse()
                    try:
                        bm.faces.new(vs)
                    except ValueError:
                        pass
        bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-7)
        bad = [f for f in bm.faces if f.calc_area() < 1e-12]
        bmesh.ops.delete(bm, geom=bad, context="FACES")
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)

    return build


GEM_C, GEM_R, GEM_H = (0.0006, 0.0), 0.0034, 0.0017  # 剑格宝石：中心 (x, z)、半径、凸起高度


# 剑格浮雕贴图覆盖的范围（物体坐标，米）
GR_X0, GR_X1, GR_Z0, GR_Z1 = -0.0165, 0.0215, -0.0425, 0.0425
GR_PX = 16.0  # 像素 / 毫米


def guard_relief():
    """剑格两面的浮雕高度图（行 = x 从 GR_X1 到 GR_X0，列 = z 从 GR_Z0 到 GR_Z1）：
    沿轮廓内收的一道边珠，中间一个双线菱形和乳钉，两翼各一组卷云（大小两个反向的螺旋，一道 S 弯连起来），翼根三颗连珠。"""
    W = int(round((GR_Z1 - GR_Z0) * 1000 * GR_PX))
    H = int(round((GR_X1 - GR_X0) * 1000 * GR_PX))

    def px(x, z):  # 物体坐标（米）→ 像素 (列, 行)
        return ((z - GR_Z0) * 1000 * GR_PX, (GR_X1 - x) * 1000 * GR_PX)

    lines = []
    # 边珠：轮廓内收 1.4 毫米
    outline = []
    for z in np.linspace(-GD_ZG, GD_ZG, 241):
        xa, xb, f = guard_xr(abs(z))
        xm, half = (xa + xb) / 2, (xb - xa) / 2 * f
        outline.append((xm + half, z))
    for z in np.linspace(GD_ZG, -GD_ZG, 241):
        xa, xb, f = guard_xr(abs(z))
        xm, half = (xa + xb) / 2, (xb - xa) / 2 * f
        outline.append((xm - half, z))
    P = np.array(outline)
    cen = P.mean(0)
    inset = []
    for i in range(len(P)):
        a, b = P[i - 1], P[(i + 1) % len(P)]
        t = b - a
        nrm = np.array([-t[1], t[0]])
        nrm /= np.linalg.norm(nrm) + 1e-12
        if np.dot(nrm, cen - P[i]) < 0:
            nrm = -nrm
        inset.append(P[i] + nrm * 0.0014)
    lines.append(([px(x, z) for x, z in inset] + [px(*inset[0])], 0.9))
    # 中间：双线菱形 + 乳钉
    for s, wd in ((1.0, 0.85),):
        dz, dx = 0.0078 * s, 0.0062 * s
        quad = [(0.0006 + dx, 0.0), (0.0006, dz), (0.0006 - dx, 0.0), (0.0006, -dz), (0.0006 + dx, 0.0)]
        lines.append(([px(x, z) for x, z in quad], wd))
    ring = [px(GEM_C[0] + GEM_R * 1.18 * math.cos(a), GEM_R * 1.18 * math.sin(a)) for a in np.linspace(0, 2 * math.pi, 90)]
    lines.append((ring, 0.75))  # 宝石的包边
    blobs = []
    # 两翼：卷云
    for sg in (-1.0, 1.0):
        c1 = (0.0028, sg * 0.0262)
        c2 = (-0.0045, sg * 0.0158)
        r1, r2 = 0.0054, 0.0031
        sp1 = kit.spiral(*px(*c1)[::1], r1 * 1000 * GR_PX, 0.6 * GR_PX, 1.55, a0=math.pi * (0.5 if sg > 0 else 0.5),
                         sign=sg, n=160)
        sp2 = kit.spiral(*px(*c2), r2 * 1000 * GR_PX, 0.5 * GR_PX, 1.35, a0=-math.pi * 0.5, sign=-sg, n=120)
        lines.append((sp1, 0.8))
        lines.append((sp2, 0.7))
        # S 弯：从大螺旋外端接到小螺旋外端
        a = np.array(sp1[0])
        b = np.array(sp2[0])
        mid = (a + b) / 2 + np.array([0.0, 3.0 * GR_PX]) * sg * 0.3
        ts = np.linspace(0, 1, 40)[:, None]
        curve = (1 - ts) ** 2 * a + 2 * (1 - ts) * ts * mid + ts ** 2 * b
        lines.append(([tuple(p) for p in curve], 0.7))
        # 翼根三颗连珠
        for k in range(3):
            blobs.append((px(-0.0072 + 0.0032 * k, sg * 0.0092), 0.55))
        # 翼尖一颗
        blobs.append((px(0.0088, sg * 0.0365), 0.9))
    mask = np.zeros((H, W))
    for pts, wd in lines:
        mask = np.maximum(mask, kit.draw_lines((H, W), [pts], wd * GR_PX))
    Y, X = np.mgrid[0:H, 0:W]
    for (cx, cy), r in blobs:
        d = np.hypot(X - cx, Y - cy) / (r * GR_PX)
        mask = np.maximum(mask, np.clip(1.4 - d * 1.4, 0, 1) ** 0.7)
    hgt = kit.height_from_mask(mask, 1.1 * GR_PX / 16 * 1.6)
    return hgt


# ---------------------------------------------------------------------- 剑身上的错金：北斗七星（背面）、铭文
IN_X0, IN_X1, IN_Z0, IN_Z1 = 0.022, 0.235, -0.013, 0.013
IN_PX = 9.0  # 像素 / 毫米


def blade_inlay():
    """剑身背面（+Y）的错金：近剑格两个字“镇邪”，往前一组北斗七星（金点、金丝连线）。
    图的列 = x（从 IN_X0 到 IN_X1），行 = z（从 IN_Z1 到 IN_Z0）。返回 0..1 遮罩。
    从背面看剑尖朝左，字按剑尖朝上的读法摆：字头朝 +X。"""
    from PIL import Image, ImageDraw, ImageFont  # noqa: PLC0415

    W = int(round((IN_X1 - IN_X0) * 1000 * IN_PX))
    H = int(round((IN_Z1 - IN_Z0) * 1000 * IN_PX))

    def px(x, z):
        return ((x - IN_X0) * 1000 * IN_PX, (IN_Z1 - z) * 1000 * IN_PX)

    mask = np.zeros((H, W))
    # 北斗：天枢、天璇、天玑、天权、玉衡、开阳、摇光（斗口朝剑格）
    stars = [(0.0, 0.0), (0.0, -1.05), (1.05, -1.25), (1.3, -0.25), (2.35, 0.05), (3.35, 0.42), (4.5, 0.12)]
    sc = 0.0205
    x0, z0 = 0.098, 0.0035
    pts = [px(x0 + sx * sc, z0 + sz * sc * 0.52) for sx, sz in stars]
    chain = [pts[0], pts[1], pts[2], pts[3], pts[0]], pts[3:]
    for pl in chain:
        mask = np.maximum(mask, kit.draw_lines((H, W), [pl], 0.32 * IN_PX) * 0.85)
    Y, X = np.mgrid[0:H, 0:W]
    for i, (cx, cy) in enumerate(pts):
        r = (1.25 if i in (0, 3, 6) else 1.05) * IN_PX
        d = np.hypot(X - cx, Y - cy) / r
        mask = np.maximum(mask, np.clip((1.0 - d) * 6.0, 0, 1))
    # 铭文：两个字，字头朝 +X（图里朝右）。先竖着写，再转 90°
    fsz = int(8.5 * IN_PX)
    f = ImageFont.truetype(str(kit.font_path()), fsz)
    im = Image.new("L", (int(fsz * 1.2), int(fsz * 2.4)), 0)
    dr = ImageDraw.Draw(im)
    y = 0
    for ch in "镇邪":
        bb = dr.textbbox((0, 0), ch, font=f)
        dr.text(((im.width - (bb[2] - bb[0])) / 2 - bb[0], y - bb[1]), ch, font=f, fill=255)
        y += int(fsz * 1.15)
    im = im.rotate(-90, expand=True)  # 字头朝右（+X）
    # 从背面看 +X 在左边：左右翻一下，背面看上去才是正字
    im = im.transpose(Image.FLIP_TOP_BOTTOM)
    cx, cy = px(0.048, 0.0)
    ox, oy = int(cx - im.width / 2), int(cy - im.height / 2)
    a = np.asarray(im, np.float64) / 255.0
    sub = mask[max(oy, 0):oy + a.shape[0], max(ox, 0):ox + a.shape[1]]
    mask[max(oy, 0):oy + a.shape[0], max(ox, 0):ox + a.shape[1]] = np.maximum(sub, a[:sub.shape[0], :sub.shape[1]])
    return np.clip(kit.blur(mask, 0.6), 0, 1)


# ---------------------------------------------------------------------- 符纸
def talisman_art(w=320, h=2700, seed=5):
    """黄符（竖长，第 0 行是贴住的一头）：土黄纸（纤维、斑渍、旧边、三折的折痕），朱砂：双线框、符头（三清三笔 + 圈点）、
    “敕令”、大“雷”字两边各一个雷纹、竖行“急急如律令”、符脚（闪电折线收一个钩）、底下一方白文小印“灵宝”。
    返回 (paper_rgb, ink)：0..1，sRGB。"""
    from PIL import Image, ImageDraw, ImageFilter, ImageFont  # noqa: PLC0415

    rng = np.random.default_rng(seed)
    V = K.vfx()
    paper = np.ones((h, w, 3)) * K.hexc("#C9A44C")
    fib = V.fft_blur(rng.standard_normal((h, w)), (12.0, 0.8), angle=math.pi / 2)
    fib /= fib.std() + 1e-9
    fib2 = V.fft_blur(rng.standard_normal((h, w)), (5.0, 0.7), angle=0.4)
    fib2 /= fib2.std() + 1e-9
    blot = V.fft_blur(rng.standard_normal((h, w)), 60.0)
    blot /= blot.std() + 1e-9
    paper *= (1 + 0.018 * fib + 0.012 * fib2 + 0.06 * blot)[..., None]
    # 水渍：两三圈淡褐的环
    Y, X = np.mgrid[0:h, 0:w]
    for cy, cx, r in ((0.62 * h, 0.35 * w, 0.42 * w), (0.83 * h, 0.7 * w, 0.30 * w)):
        d = np.hypot(X - cx, (Y - cy) * 0.9) / r
        ring = np.exp(-((d - 1) / 0.05) ** 2) * 0.10 + (d < 1) * 0.03
        paper *= (1 - ring)[..., None] * np.array([1.0, 0.97, 0.9]) + ring[..., None] * np.array([0.0, 0.0, 0.0])
    # 纸纤维：稀疏的一根根长纤维（有亮有暗，弯弯的），近看能分出来
    fibers = Image.new("L", (w * 2, h * 2), 128)
    fd = ImageDraw.Draw(fibers)
    for _ in range(int(h * w / 2600)):
        x0, y0 = rng.uniform(0, w * 2), rng.uniform(0, h * 2)
        a0 = rng.uniform(0, math.pi)
        L = rng.uniform(18, 70)
        pts_ = []
        for t in np.linspace(0, 1, 8):
            a = a0 + 0.6 * math.sin(3 * t + x0)
            pts_.append((x0 + L * t * math.cos(a), y0 + L * t * math.sin(a)))
        fd.line(pts_, fill=int(128 + rng.choice([-1, 1]) * rng.uniform(25, 60)), width=1)
    fb = (np.asarray(fibers.resize((w, h), Image.LANCZOS), np.float64) - 128) / 128.0
    paper *= (1 + 0.10 * fb)[..., None]
    edge = np.minimum(np.minimum(X, w - 1 - X), np.minimum(Y, h - 1 - Y)).astype(np.float64)
    paper *= (1 - 0.22 * np.exp(-edge / 14.0))[..., None]
    paper = paper * (1 - 0.10 * np.exp(-edge / 5.0))[..., None] + np.array([0.30, 0.20, 0.08]) * 0.10 * np.exp(-edge / 5.0)[..., None]
    # 三折的折痕（横）和对折的中线（竖）：纸纤维断了，积了一点灰
    for cy in (h / 3, 2 * h / 3):
        paper *= (1 - 0.10 * np.exp(-((Y - cy) / 3.0) ** 2))[..., None]
    paper *= (1 - 0.06 * np.exp(-((X - w / 2) / 2.5) ** 2))[..., None]

    ink = Image.new("L", (w, h), 0)
    dr = ImageDraw.Draw(ink)
    m1, m2 = int(w * 0.045), int(w * 0.085)
    dr.rectangle((m1, m1, w - 1 - m1, h - 1 - m1), outline=255, width=max(3, int(w * 0.018)))
    dr.rectangle((m2, m2, w - 1 - m2, h - 1 - m2), outline=255, width=max(2, int(w * 0.007)))
    cx = w // 2
    fnt = lambda s: ImageFont.truetype(str(kit.font_path()), int(s))  # noqa: E731
    # 符头：三笔 + 圈点
    y0 = int(h * 0.040)
    for dx in (-0.16, 0.0, 0.16):
        x = cx + dx * w
        dr.line((x, y0, x + dx * w * 0.25, y0 + h * 0.022), fill=255, width=int(w * 0.035))
    dr.line((cx - 0.24 * w, y0 + h * 0.026, cx + 0.24 * w, y0 + h * 0.026), fill=255, width=int(w * 0.03))
    ry = y0 + h * 0.050
    rr = w * 0.15
    dr.ellipse((cx - rr, ry - rr, cx + rr, ry + rr), outline=255, width=int(w * 0.03))
    dr.ellipse((cx - rr * 0.28, ry - rr * 0.28, cx + rr * 0.28, ry + rr * 0.28), fill=255)

    def column(text, y, size, gap=1.04):
        f = fnt(size)
        for ch in text:
            bb = dr.textbbox((0, 0), ch, font=f)
            dr.text((cx - (bb[2] - bb[0]) / 2 - bb[0], y - bb[1]), ch, font=f, fill=255)
            y += int(size * gap)
        return y

    y = column("敕令", int(h * 0.112), w * 0.66)
    y = column("雷", y + int(h * 0.006), w * 0.84)
    # 雷纹（回纹的小螺旋）两边各一个
    for sg in (-1, 1):
        sp = kit.spiral(cx + sg * w * 0.30, y - w * 0.45, w * 0.10, w * 0.015, 1.6, a0=0.0, sign=sg, n=80)
        dr.line(sp, fill=255, width=int(w * 0.022), joint="curve")
    y = column("急急如律令", y + int(h * 0.012), w * 0.56, gap=1.03)
    # 符脚：闪电折线 + 钩
    pts = []
    yy = y + h * 0.008
    for i in range(9):
        pts.append((cx + (0.24 if i % 2 else -0.24) * w * (1 - i / 12), yy + i * h * 0.0150))
    end = pts[-1]
    for a in np.linspace(0, 1.4 * math.pi, 14):
        pts.append((end[0] + w * 0.08 * math.sin(a), end[1] + w * 0.08 * (1 - math.cos(a))))
    dr.line(pts, fill=255, width=int(w * 0.030), joint="curve")
    ink_a = np.asarray(ink.filter(ImageFilter.GaussianBlur(w / 320)), np.float64) / 255.0
    # 小印（白文）：朱砂方块里刻掉两个字
    sy = int(min(h * 0.885, pts[-1][1] + w * 0.30))
    s = int(w * 0.42)
    stamp = Image.new("L", (s, s), 255)
    sd = ImageDraw.Draw(stamp)
    f2 = fnt(s * 0.42)
    for k, ch in enumerate("灵宝"):
        bb = sd.textbbox((0, 0), ch, font=f2)
        sd.text(((s - (bb[2] - bb[0])) / 2 - bb[0], s * (0.06 + 0.47 * k) - bb[1]), ch, font=f2, fill=0)
    sa = np.asarray(stamp, np.float64) / 255.0
    rough = V.fft_blur(rng.standard_normal(sa.shape), 1.2)
    sa = np.clip(sa * (0.88 + 0.12 * np.tanh(rough / (rough.std() + 1e-9))), 0, 1)
    ox = cx - s // 2
    ink_a[sy:sy + s, ox:ox + s] = np.maximum(ink_a[sy:sy + s, ox:ox + s], sa[:max(0, min(s, h - sy)), :] * 0.92)
    # 干笔：沿笔的方向断续
    dry = V.fft_blur(rng.standard_normal((h, w)), (7.0, 1.0), angle=math.pi / 2)
    ink_a = np.clip(ink_a * (0.80 + 0.22 * np.tanh(dry / (dry.std() + 1e-9))), 0, 1)
    # 墨的浓淡：一笔里有的地方浓有的地方淡（蘸墨处浓、拖到后面淡），笔画边上积墨（更深的一道边）
    dens = V.fft_blur(rng.standard_normal((h, w)), 22.0)
    dens = 0.5 + 0.5 * np.tanh(dens / (dens.std() + 1e-9) * 1.2)
    pool = np.clip((ink_a - V.fft_blur(ink_a, 1.6)) * 3.0, 0, 1)
    # 朱砂洇进纸里一点
    halo = np.clip(V.fft_blur(ink_a, 2.2) * 1.2 - ink_a, 0, 1) * 0.35
    thin, mid, dense = K.hexc("#C4452A"), K.hexc("#A8230F"), K.hexc("#741008")
    red = thin * (1 - dens[..., None]) + mid * dens[..., None]
    red = red * (1 - pool[..., None] * 0.7) + dense * pool[..., None] * 0.7
    a_eff = ink_a * (0.78 + 0.22 * dens)
    out = paper * (1 - halo[..., None] * 0.5) + K.hexc("#B2482A") * halo[..., None] * 0.5
    out = out * (1 - a_eff[..., None]) + red * a_eff[..., None]
    return np.clip(out, 0, 1), np.clip(a_eff + pool * 0.2, 0, 1)


# ---------------------------------------------------------------------- 剑首端面的浮雕
PM_PX = 20.0


def pommel_relief(size=640):
    """剑首圆顶的浮雕（以剑轴为中心的平面投影，覆盖 ±16 毫米）：八瓣宝相花 + 一圈连珠 + 中心乳钉。"""
    H = W = size
    c = size / 2
    k = size / 32.0  # 像素 / 毫米
    lines = []
    for i in range(8):
        a = i * math.pi / 4
        pts = []
        for t in np.linspace(0, 1, 40):
            ang = a + 0.36 * math.sin(math.pi * t)
            r = (2.6 + 8.2 * t) * k
            pts.append((c + r * math.cos(ang), c + r * math.sin(ang)))
        for t in np.linspace(1, 0, 40):
            ang = a - 0.36 * math.sin(math.pi * t)
            r = (2.6 + 8.2 * t) * k
            pts.append((c + r * math.cos(ang), c + r * math.sin(ang)))
        lines.append((pts, 0.8 * k))
    ring = [(c + 12.4 * k * math.cos(a), c + 12.4 * k * math.sin(a)) for a in np.linspace(0, 2 * math.pi, 200)]
    lines.append((ring, 0.7 * k))
    mask = np.zeros((H, W))
    for pts, wd in lines:
        mask = np.maximum(mask, kit.draw_lines((H, W), [pts], wd))
    Y, X = np.mgrid[0:H, 0:W]
    for i in range(24):
        a = i * 2 * math.pi / 24 + 0.13
        d = np.hypot(X - (c + 14.0 * k * math.cos(a)), Y - (c + 14.0 * k * math.sin(a))) / (0.65 * k)
        mask = np.maximum(mask, np.clip(1.3 - d * 1.3, 0, 1) ** 0.6)
    d = np.hypot(X - c, Y - c) / (1.6 * k)
    mask = np.maximum(mask, np.clip(1.3 - d * 1.3, 0, 1) ** 0.6)
    return kit.height_from_mask(mask, 1.2)


# ====================================================================== 符剑：材质


def mat_blade(name, inlay_img):
    """剑身的钢：用旧了的，不是新钢。
    - 斜面：偏暗的灰钢，沿长的折叠花纹、顺剑的细划痕，近剑格和几块斑上有氧化（褐锈、麻点，几乎不反光）；
    - 刃口：开过刃、常磨的那一窄条更亮更光，磨痕斜着走；崩口在几何上；
    - 背面近剑格：错金北斗七星和铭文。"""
    M = PMat(name)
    co = M.co
    u, v, _ = M.sep(M.uv())  # u = x，v = z（米）
    facet = M.attr("facet")
    side = M.attr("side")
    bev = M.math("COMPARE", facet, 1.0, 0.1)
    tipstrip = M.math("COMPARE", facet, 2.0, 0.1)
    back = M.math("GREATER_THAN", side, 0.5)
    # 折叠花纹
    mp = M.n("ShaderNodeMapping")
    M.l(co, mp.inputs["Vector"])
    mp.inputs["Scale"].default_value = (1.6, 36.0, 36.0)
    wave = M.n("ShaderNodeTexWave", _wave_type="BANDS", _bands_direction="Z", Scale=5.0, Distortion=8.0, Detail=5.0,
               Detail_Scale=1.6)
    M.l(mp.outputs["Vector"], wave.inputs["Vector"])
    pat = M.maprange(wave.outputs["Fac"], 0.25, 0.85)
    # 顺剑的划痕（稀疏的细线）
    scr = M.maprange(M.nz(1.0, detail=2.0, stretch=(4.0, 1400.0, 1400.0), seed=3.0), 0.64, 0.70)
    scr2 = M.maprange(M.nz(1.0, detail=2.0, stretch=(9.0, 700.0, 700.0), seed=8.0), 0.66, 0.71)
    scr = M.math("MAXIMUM", scr, M.math("MULTIPLY", scr2, 0.6))
    scr = M.math("MULTIPLY", scr, M.maprange(M.nz(30.0, seed=4.0), 0.4, 0.6))
    # 刃口的磨痕：斜 65° 的细线
    az = M.math("ABSOLUTE", v)
    ca, sa = math.cos(math.radians(65)), math.sin(math.radians(65))
    q = M.math("ADD", M.math("MULTIPLY", u, -sa), M.math("MULTIPLY", az, ca))
    p_ = M.math("ADD", M.math("MULTIPLY", u, ca), M.math("MULTIPLY", az, sa))
    gv = M.comb(M.math("MULTIPLY", q, 2600.0), M.math("MULTIPLY", p_, 60.0), 0.0)
    grind = M.maprange(M.nz(1.0, detail=3.0, rough=0.6, co=gv), 0.35, 0.75)
    # 氧化：近剑格多、往前少，一块块；斜面多、刃口（常磨）少
    xz = M.maprange(u, 0.02, 0.30, 1.0, 0.25)
    blot = M.maprange(M.nz(70.0, detail=6.0, rough=0.62, seed=1.0), 0.56, 0.72)
    spots = M.maprange(M.nz(240.0, detail=4.0, rough=0.6, seed=2.0), 0.66, 0.76)
    ox = M.math("ADD", M.math("MULTIPLY", blot, xz), M.math("MULTIPLY", spots, 0.55), clamp=True)
    ox = M.math("MULTIPLY", ox, M.math("SUBTRACT", 1.0, M.math("MULTIPLY", M.math("ADD", bev, tipstrip), 0.85)), clamp=True)
    pit = M.math("MULTIPLY", M.maprange(M.voronoi(1500.0), 0.0, 0.28, 1.0, 0.0), M.maprange(ox, 0.2, 0.7))
    # 错金（只在背面）
    ivec = M.comb(M.math("DIVIDE", M.math("SUBTRACT", u, IN_X0), IN_X1 - IN_X0),
                  M.math("DIVIDE", M.math("SUBTRACT", v, IN_Z0), IN_Z1 - IN_Z0), 0.0)
    ink = M.image(inlay_img, ivec, extension="CLIP", out="Color")
    inl = M.math("MULTIPLY", M.sep(ink)[0], back)
    inl = M.math("MULTIPLY", inl, M.math("SUBTRACT", 1.0, M.math("ADD", bev, tipstrip), clamp=True))
    gold_edge = M.math("SUBTRACT", M.maprange(inl, 0.05, 0.4), M.maprange(inl, 0.4, 0.9), clamp=True)  # 嵌槽的边
    # 颜色
    flat_c = M.mix(pat, (0.30, 0.312, 0.33, 1.0), (0.50, 0.512, 0.53, 1.0))
    edge_c = M.mix(grind, (0.62, 0.63, 0.645, 1.0), (0.76, 0.77, 0.78, 1.0))
    col = M.mix(M.math("ADD", bev, tipstrip), flat_c, edge_c)
    col = M.mix(M.math("MULTIPLY", scr, 0.30), col, (0.62, 0.63, 0.64, 1.0))
    rust = M.mix(M.nz(140.0, seed=6.0), (0.11, 0.065, 0.040, 1.0), (0.20, 0.11, 0.055, 1.0))
    col = M.mix(M.math("MULTIPLY", ox, 0.9), col, rust)
    col = M.mix(M.math("MULTIPLY", pit, 0.45), col, (0.05, 0.04, 0.035, 1.0))
    col = M.stroke(col, amount=0.05, scale=18.0, stretch=(0.25, 1.0, 1.0), warm=0.015)
    col = M.mix(inl, col, (0.86, 0.60, 0.24, 1.0))
    col = M.mix(M.math("MULTIPLY", gold_edge, 0.6), col, (0.10, 0.08, 0.05, 1.0))
    rough = M.math("ADD", 0.36, M.math("MULTIPLY", pat, 0.14))
    rough = M.mixf(M.math("ADD", bev, tipstrip), rough, M.math("ADD", 0.16, M.math("MULTIPLY", grind, 0.10)))
    rough = M.math("ADD", rough, M.math("MULTIPLY", scr, 0.16))
    rough = M.mixf(ox, rough, 0.78)
    rough = M.mixf(inl, rough, 0.30)
    metal = M.math("SUBTRACT", 1.0, M.math("MULTIPLY", ox, 0.75), clamp=True)
    metal = M.mixf(inl, metal, 1.0)
    M.normal_base(M.bevel_normal(0.00035))
    M.bump_add(M.math("MULTIPLY", grind, M.math("ADD", bev, tipstrip)), strength=0.06, distance=0.00008)
    M.bump_add(scr, strength=-0.05, distance=0.0001)
    M.bump_add(M.math("ADD", pit, M.math("MULTIPLY", blot, 0.15)), strength=-0.18, distance=0.00012)
    M.bump_add(gold_edge, strength=-0.25, distance=0.00012)
    return M.set(base=col, rough=rough, metal=metal)


def mat_gilt_bronze(name, relief=None, relief_mode=None, cav_dist=0.003, gilt=0.85):
    """铜鎏金：鎏金面、高处磨掉金露出的黄铜、凹处积的铜锈和污垢。
    relief = (图像, 方式)：方式 "guard"（剑格两面按 x、z 平面投影，只上在两个大面）、"pommel"（沿剑轴的平面投影，只上在端面）。"""
    M = PMat(name)
    co = M.co
    cav = M.cavity(cav_dist)
    edge = M.edge(0.0007, 0.0, 0.10)
    h = None
    if relief is not None:
        img, mode = relief
        x, y, z = M.sep(co)
        g = M.n("ShaderNodeNewGeometry")
        nx, ny, nzn = M.sep(g.outputs["Normal"])
        if mode == "guard":
            vec = M.comb(M.math("DIVIDE", M.math("SUBTRACT", z, GR_Z0), GR_Z1 - GR_Z0),
                         M.math("DIVIDE", M.math("SUBTRACT", x, GR_X0), GR_X1 - GR_X0), 0.0)
            face = M.maprange(M.math("ABSOLUTE", ny), 0.55, 0.85)
        else:  # pommel：端面朝 -X，(z, y) 平面
            px0 = relief_mode
            vec = M.comb(M.math("ADD", 0.5, M.math("DIVIDE", z, 0.032)), M.math("ADD", 0.5, M.math("DIVIDE", y, 0.032 * 0.84)), 0.0)
            face = M.math("MULTIPLY", M.maprange(M.math("MULTIPLY", nx, -1.0), 0.35, 0.7),
                          M.maprange(x, px0 + 0.0075, px0 + 0.0050))
        hh = M.sep(M.image(img, vec, extension="CLIP"))[0]
        h = M.math("MULTIPLY", hh, face)
    n1 = M.nz(55.0, detail=5.0, rough=0.62, seed=1.0)
    n2 = M.nz(240.0, detail=4.0, rough=0.6, seed=2.0)
    # 磨损：棱边、浮雕高处、手常摸的地方（噪声）
    wear = M.math("ADD", M.math("MULTIPLY", edge, 0.85), M.math("MULTIPLY", M.maprange(n1, 0.55, 0.72), 0.55), clamp=True)
    if h is not None:
        wear = M.math("ADD", wear, M.math("MULTIPLY", M.maprange(h, 0.55, 0.95), 0.9), clamp=True)
    wear = M.math("MULTIPLY", wear, M.math("SUBTRACT", 1.0, M.math("MULTIPLY", cav, 1.5), clamp=True))
    grime = M.math("ADD", M.math("MULTIPLY", cav, 1.6), M.math("MULTIPLY", M.maprange(n1, 0.30, 0.42, 0.6, 0.0), 0.5), clamp=True)
    if h is not None:  # 浮雕线脚下的凹处
        rim = M.math("SUBTRACT", M.maprange(h, 0.02, 0.25), M.maprange(h, 0.3, 0.6), clamp=True)
        grime = M.math("ADD", grime, M.math("MULTIPLY", rim, 0.7), clamp=True)
    gold = M.mix(M.maprange(n2, 0.2, 0.8), (0.74, 0.50, 0.19, 1.0), (0.84, 0.58, 0.24, 1.0))
    brass = (0.70, 0.52, 0.27, 1.0)
    bronze = (0.36, 0.22, 0.10, 1.0)
    base = M.mix(gilt, bronze, gold)
    col = M.mix(wear, base, brass)
    patina = M.mix(M.nz(90.0, seed=5.0), (0.07, 0.09, 0.06, 1.0), (0.13, 0.15, 0.09, 1.0))
    col = M.mix(M.math("MULTIPLY", grime, 0.85), col, patina)
    col = M.stroke(col, amount=0.06, scale=40.0)
    rough = M.mixf(wear, M.math("ADD", 0.30, M.math("MULTIPLY", n1, 0.10)), 0.20)
    rough = M.mixf(grime, rough, 0.70)
    metal = M.math("SUBTRACT", 1.0, M.math("MULTIPLY", grime, 0.85), clamp=True)
    M.normal_base(M.bevel_normal(0.0005))
    if h is not None:
        M.bump_add(h, strength=0.75, distance=0.00045)
    M.bump_add(M.math("ADD", M.math("MULTIPLY", n2, 0.6), M.math("MULTIPLY", grime, 0.4)), strength=0.05, distance=0.00015)
    return M.set(base=col, rough=rough, metal=metal)


def mat_cord(name, color=(0.030, 0.027, 0.036), hi=(0.085, 0.078, 0.10)):
    """缠柄的丝绳：两股拧成的绳（斜纹），朝外的一面磨得发亮（握手处），绳缝里暗。UV：u = 弧长米，v = 绕一圈。"""
    M = PMat(name)
    u, v, _ = M.sep(M.uv())
    tw = M.math("SINE", M.math("MULTIPLY", M.math("ADD", M.math("DIVIDE", u, 0.0021), M.math("MULTIPLY", v, 2.0)), 2 * math.pi))
    ply = M.math("POWER", M.maprange(tw, -1.0, 1.0), 0.6)
    fuzz = M.nz(900.0, detail=3.0, seed=2.0)
    g = M.n("ShaderNodeNewGeometry")
    _, gy, gz = M.sep(g.outputs["Normal"])
    _, py, pz = M.sep(M.co)
    rl = M.math("SQRT", M.math("ADD", M.math("MULTIPLY", py, py), M.math("MULTIPLY", pz, pz)))
    outward = M.math("DIVIDE", M.math("ADD", M.math("MULTIPLY", gy, py), M.math("MULTIPLY", gz, pz)), M.math("MAXIMUM", rl, 1e-4))
    worn = M.math("MULTIPLY", M.maprange(outward, 0.5, 0.95), M.maprange(M.nz(25.0, seed=4.0), 0.35, 0.65, 0.4, 1.0))
    cav = M.cavity(0.0025)
    col = M.mix(ply, color, hi)
    col = M.mix(M.math("MULTIPLY", worn, 0.55), col, (0.13, 0.12, 0.14, 1.0))
    col = M.mix(M.math("MULTIPLY", cav, 0.8), col, (0.008, 0.007, 0.009, 1.0))
    col = M.stroke(col, amount=0.08, scale=30.0)
    rough = M.mixf(worn, M.math("ADD", 0.58, M.math("MULTIPLY", fuzz, 0.1)), 0.40)
    M.bump_add(ply, strength=0.55, distance=0.0004)
    M.bump_add(fuzz, strength=0.08, distance=0.0001)
    return M.set(base=col, rough=rough, metal=0.0)


GRIP_KNOTS = [((-0.0335, -0.0060, 0.0082), 0.0034), ((-0.1395, 0.0085, -0.0058), 0.0026)]  # 节疤：(中心, 半径)


def mat_wood(name):
    """剑柄的木头（露在缠绳两头）：沿柄的顺纹（细密的年轮线，带一点起伏）、几个节疤（深色的芯、一圈圈绕开的纹）、
    握久了的油光（中段偏亮、粗糙度低），木纹在法线里凹下去。"""
    M = PMat(name)
    co = M.co
    x, y, z = M.sep(co)
    # 节疤：离节疤中心的距离；顺纹在节疤附近绕开（坐标往外推）
    warp = None
    knot_core = None
    rings = None
    for (cx, cy, cz), rk in GRIP_KNOTS:
        d = M.vmath("DISTANCE", co, (cx, cy, cz))
        fall = M.math("EXPONENT", M.math("MULTIPLY", M.math("POWER", M.math("DIVIDE", d, rk * 1.8), 2.0), -1.0))
        warp = fall if warp is None else M.math("ADD", warp, fall)
        core = M.maprange(d, rk * 0.45, rk * 0.25)
        knot_core = core if knot_core is None else M.math("MAXIMUM", knot_core, core)
        rr = M.math("MULTIPLY", M.math("SINE", M.math("MULTIPLY", d, 2 * math.pi / 0.0007)), M.maprange(d, rk * 1.6, rk * 0.4))
        rings = rr if rings is None else M.math("ADD", rings, rr)
    # 顺纹：沿 X 的线，截面方向（y、z）上取样；节疤处把坐标推开，线就绕着节疤走
    gy = M.math("ADD", M.math("MULTIPLY", y, 1.0), M.math("MULTIPLY", warp, 0.0022))
    gz = M.math("ADD", z, M.math("MULTIPLY", warp, 0.0016))
    gv = M.comb(M.math("MULTIPLY", x, 30.0), M.math("MULTIPLY", gy, 1500.0), M.math("MULTIPLY", gz, 1500.0))
    wob = M.nz(1.0, detail=2.0, co=M.comb(M.math("MULTIPLY", x, 18.0), M.math("MULTIPLY", y, 300.0), M.math("MULTIPLY", z, 300.0)))
    gv = M.vmath("ADD", gv, M.comb(0.0, M.math("MULTIPLY", wob, 2.5), M.math("MULTIPLY", wob, 2.5)))
    wave = M.n("ShaderNodeTexWave", _wave_type="RINGS", _rings_direction="X", Scale=1.0, Distortion=0.0, Detail=0.0)
    M.l(gv, wave.inputs["Vector"])
    grain = M.maprange(wave.outputs["Fac"], 0.25, 0.95)
    fine = M.nz(1.0, detail=3.0, co=M.comb(M.math("MULTIPLY", x, 60.0), M.math("MULTIPLY", y, 5000.0), M.math("MULTIPLY", z, 5000.0)))
    light = (0.30, 0.16, 0.075, 1.0)
    dark = (0.12, 0.058, 0.026, 1.0)
    col = M.mix(M.math("ADD", M.math("MULTIPLY", grain, 0.75), M.math("MULTIPLY", fine, 0.25)), light, dark)
    col = M.mix(M.math("MULTIPLY", M.maprange(rings, -1.0, 1.0), 0.5), col, (0.10, 0.045, 0.02, 1.0))
    col = M.mix(knot_core, col, (0.045, 0.020, 0.010, 1.0))
    cav = M.cavity(0.0025)
    col = M.mix(M.math("MULTIPLY", cav, 0.7), col, (0.03, 0.015, 0.008, 1.0))
    col = M.stroke(col, amount=0.06, scale=40.0, stretch=(0.3, 1.0, 1.0))
    oil = M.maprange(M.nz(20.0, seed=4.0), 0.3, 0.7)
    rough = M.mixf(oil, 0.42, 0.30)
    rough = M.math("ADD", rough, M.math("MULTIPLY", grain, 0.10))
    M.bump_add(M.math("ADD", M.math("MULTIPLY", grain, -1.0), M.math("MULTIPLY", knot_core, 0.6)), strength=0.18, distance=0.00012)
    M.bump_add(fine, strength=0.05, distance=0.00006)
    return M.set(base=col, rough=rough, metal=0.0)


def mat_paper(name, art_img, ink_img, length):
    """符纸：正面是符（朱砂微微凸起、半光，夜里透一点红金的光），背面淡淡透出反着的字，侧边是纸茬。
    折痕（三折）、对折的中线、旧边（毛边处发褐）、贴住的那段有一点浆糊的渍。UV：u = 弧长米（0 是贴住的一头），v = 0..1 横跨。"""
    M = PMat(name)
    u, v, _ = M.sep(M.uv())
    side = M.attr("side")
    edge_d = M.attr("edge_d")
    back = M.math("COMPARE", side, 1.0, 0.1)
    rim = M.math("COMPARE", side, 2.0, 0.1)
    vec = M.comb(v, M.math("SUBTRACT", 1.0, M.math("DIVIDE", u, length)), 0.0)
    art = M.image(art_img, vec, extension="EXTEND")
    ink = M.sep(M.image(ink_img, vec, extension="EXTEND"))[0]
    paper_back = M.mix(M.nz(80.0, seed=3.0), (0.62, 0.50, 0.26, 1.0), (0.70, 0.58, 0.32, 1.0))
    col = M.mix(back, art, M.mix(0.20, paper_back, art))
    col = M.mix(rim, col, (0.55, 0.42, 0.20, 1.0))
    aged = M.maprange(edge_d, 0.0, 0.0018, 1.0, 0.0)
    col = M.mix(M.math("MULTIPLY", aged, 0.45), col, (0.32, 0.20, 0.08, 1.0))
    glue = M.math("MULTIPLY", M.maprange(u, TALI_GLUE - 0.004, TALI_GLUE + 0.002, 1.0, 0.0), M.maprange(M.nz(70.0, seed=7.0), 0.35, 0.7))
    col = M.mix(M.math("MULTIPLY", glue, 0.18), col, (0.42, 0.30, 0.12, 1.0))
    col = M.stroke(col, amount=0.05, scale=50.0)
    fib = M.nz(1.0, detail=3.0, stretch=(900.0, 2600.0, 2600.0), seed=1.0)
    front = M.math("SUBTRACT", 1.0, M.math("ADD", back, rim), clamp=True)
    inkf = M.math("MULTIPLY", ink, front)
    rough = M.mixf(inkf, M.math("ADD", 0.80, M.math("MULTIPLY", fib, 0.1)), 0.50)
    glow = M.math("ADD", M.math("MULTIPLY", inkf, 1.0), M.math("MULTIPLY", M.math("MULTIPLY", ink, back), 0.10))
    M.bump_add(M.math("ADD", M.math("MULTIPLY", fib, 0.5), M.math("MULTIPLY", inkf, 0.9)), strength=0.18, distance=0.00012)
    return M.set(base=col, rough=rough, metal=0.0, emit=(1.0, 0.36, 0.10), emit_strength=M.math("MULTIPLY", glow, 1.6))


def mat_silk(name, color=(0.42, 0.030, 0.020), dark=(0.16, 0.010, 0.008), fiber=True):
    """红丝（剑穗、穗绳、结）：顺丝的纤维纹，凹处暗。UV：u = 弧长米。"""
    M = PMat(name)
    u, v, _ = M.sep(M.uv())
    n = M.nz(140.0, seed=2.0)
    col = M.mix(M.maprange(n, 0.3, 0.7), dark, color)
    cav = M.cavity(0.002)
    col = M.mix(M.math("MULTIPLY", cav, 0.8), col, (0.05, 0.004, 0.003, 1.0))
    col = M.stroke(col, amount=0.08, scale=60.0)
    if fiber:
        st = M.maprange(M.math("SINE", M.math("MULTIPLY", v, 2 * math.pi * 3.0)), -1, 1)
        M.bump_add(st, strength=0.25, distance=0.0002)
    M.bump_add(M.nz(1.0, stretch=(200.0, 3000.0, 3000.0), seed=5.0), strength=0.1, distance=0.0001)
    return M.set(base=col, rough=M.math("ADD", 0.42, M.math("MULTIPLY", n, 0.12)), metal=0.0)


def mat_gem(name, center_fn, axis_fn, radius, height, *, deep=(0.10, 0.004, 0.008), mid=(0.50, 0.025, 0.030),
            glow=(1.0, 0.32, 0.10), strength=1.4, swirl=0.0):
    """凸面宝石（剑格的红玛瑙、风火轮的火珠）：看起来像光在里面折了一下——
    边上深、中间透亮、偏下有一团聚起来的光（光从上面进去，在底下聚），里面几道细的“丝”（星光一样的六道）；
    这些都烘进底色，亮的那团和丝也进自发光（暗处看得出里面在发光）。swirl > 0 时里面是盘旋的火纹（火珠）。
    center_fn(M) / axis_fn(M) 给出这一点所在那颗宝石的中心和朝外的轴（节点插口）。"""
    M = PMat(name)
    co = M.co
    c = center_fn(M)
    n = axis_fn(M)
    q = M.vmath("SUBTRACT", co, c)
    dq = M.vmath("DOT_PRODUCT", q, n)
    h = M.math("DIVIDE", dq, height)
    lat = M.vmath("SUBTRACT", q, M.vscale(n, dq))
    rho = M.math("DIVIDE", M.vmath("LENGTH", lat), radius)
    lx, ly, lz = M.sep(lat)
    # 聚光：偏向世界 -Z（下方）0.35 个半径的一团
    spot = M.math("EXPONENT", M.math("MULTIPLY", M.math("ADD", M.math("POWER", M.math("DIVIDE", lx, radius * 0.55), 2.0),
                                                        M.math("POWER", M.math("DIVIDE", M.math("ADD", lz, radius * 0.35), radius * 0.45), 2.0)),
                                     -1.0))
    ang = M.math("ARCTAN2", lz, lx)
    star = M.math("POWER", M.math("ABSOLUTE", M.math("COSINE", M.math("MULTIPLY", ang, 3.0))), 40.0)
    star = M.math("MULTIPLY", star, M.math("SUBTRACT", 1.0, rho, clamp=True))
    inner = M.math("ADD", M.math("MULTIPLY", spot, 0.9), M.math("MULTIPLY", star, 0.25))
    if swirl:
        sw = M.math("SINE", M.math("ADD", M.math("MULTIPLY", ang, 3.0), M.math("MULTIPLY", rho, swirl)))
        inner = M.math("ADD", M.math("MULTIPLY", inner, 0.55), M.math("MULTIPLY", M.maprange(sw, 0.2, 1.0), M.math("SUBTRACT", 1.0, rho, clamp=True)))
    edge = M.maprange(rho, 0.55, 1.0)
    col = M.mix(edge, mid, deep)
    col = M.mix(M.math("MULTIPLY", inner, 0.85), col, (*glow, 1.0))
    top = M.maprange(h, 0.6, 1.0)
    col = M.mix(M.math("MULTIPLY", top, 0.15), col, (0.9, 0.7, 0.65, 1.0))
    em = M.math("MULTIPLY", M.math("MULTIPLY", inner, M.math("SUBTRACT", 1.0, M.math("MULTIPLY", edge, 0.8))), strength)
    return M.set(base=col, rough=0.05, metal=0.0, emit=glow, emit_strength=em, coat=0.0)


def mat_jade(name):
    """青白玉：云絮一样的白斑、几点褐沁。"""
    M = PMat(name)
    n1 = M.nz(260.0, detail=6.0, rough=0.62, seed=1.0)
    n2 = M.nz(600.0, detail=4.0, seed=2.0)
    col = M.mix(M.maprange(n1, 0.4, 0.7), (0.30, 0.46, 0.36, 1.0), (0.62, 0.72, 0.60, 1.0))
    col = M.mix(M.maprange(n2, 0.68, 0.76), col, (0.30, 0.18, 0.08, 1.0))
    return M.set(base=col, rough=M.math("ADD", 0.10, M.math("MULTIPLY", n1, 0.06)), metal=0.0)


# ====================================================================== 符剑：建模


def _lathe_x(name, profile, mat, node, x0, *, segments=40, oval=1.0, outline=1.0, density=1.0, direction=-1):
    """沿剑轴（X）的旋转体：profile = [(r, s)]，s 从 x0 往 direction 方向走。oval < 1 时截面在厚度（Y）方向压扁。"""
    def radial(th, z, i):
        _ = z, i
        return 1.0 / math.sqrt(math.cos(th) ** 2 + (math.sin(th) / oval) ** 2) if oval != 1.0 else 1.0

    ob = kit.obj(name, K.lathe_uv(profile, segments=segments, radial=radial), mat, node, outline=outline, density=density,
                 rot=(0, math.pi / 2 * (1 if direction > 0 else -1), 0), loc=(x0, 0, 0))
    # lathe 的 x → 世界 ±Z（宽），y → 世界 Y（厚）：上面的 oval 已经按 y 压扁
    return ob


@model("sword")
def build_sword(draft=False):
    """符剑本体：细长的剑，剑身贴一道黄符。四面都有做工：
    剑身中脊、两道开刃的刃口和磨痕、崩口、氧化和麻点、背面错金北斗与“镇邪”二字；剑格铜鎏金，两面浮雕卷云、菱形和连珠，
    磨掉金的高处露出黄铜、凹处积锈；柄上丝绳一圈圈缠紧（两股拧的绳纹、握处磨亮）；剑首宝相花端面、挂环；
    剑穗：穗绳穿环、中国结、青白玉珠、鎏金穗帽、几十根红丝；符纸：朱砂符文、纸纹、毛边撕口、三折的折痕、背面透字。"""
    _ = draft
    from mathutils import Vector  # noqa: PLC0415

    node_b, node_t, node_q = "sword_body", "sword_talisman", "sword_tassel"
    # ---- 剑身
    inlay = kit.np_image("sword_inlay", blade_inlay())
    kit.obj("Blade", blade_build(), mat_blade("sword_m_blade", inlay), node_b, outline=1.0, density=1.0)
    # ---- 剑格
    grel = kit.np_image("sword_guard_relief", guard_relief())
    gilt_guard = mat_gilt_bronze("sword_m_guard", relief=(grel, "guard"))
    kit.obj("Guard", guard_build(), gilt_guard, node_b, outline=1.0, density=1.8)
    gem_y = 0.0108 - 0.0004  # 剑格正中的厚度（略往里嵌）

    def gem_center(M):
        _, y, _ = M.sep(M.co)
        return M.comb(GEM_C[0], M.math("MULTIPLY", M.math("SIGN", y), gem_y), GEM_C[1])

    def gem_axis(M):
        _, y, _ = M.sep(M.co)
        return M.comb(0.0, M.math("SIGN", y), 0.0)

    m_gem = mat_gem("sword_m_gem", gem_center, gem_axis, GEM_R, GEM_H)
    gprof = [(0.0, GEM_H), (GEM_R * 0.35, GEM_H * 0.96), (GEM_R * 0.62, GEM_H * 0.84), (GEM_R * 0.82, GEM_H * 0.62),
             (GEM_R * 0.95, GEM_H * 0.33), (GEM_R, 0.0), (GEM_R * 0.9, -0.0006), (0.0, -0.0006)]
    for sg in (-1.0, 1.0):
        kit.obj(f"Gem{int(sg)}", K.lathe_uv(gprof, segments=28), m_gem, node_b, outline=0.5, density=3.0,
                loc=(GEM_C[0], sg * gem_y, GEM_C[1]), rot=(-sg * math.pi / 2, 0, 0))
    gilt = mat_gilt_bronze("sword_m_gilt")
    # ---- 柄：芯（黑漆木）、两头的铜箍、丝绳
    x_a, x_b = GRIP_X0 - 0.0008, POMMEL_X + 0.0020
    core_r = lambda t: 1.0 + 0.05 * math.sin(math.pi * t)  # noqa: E731
    pts = [(x_a + (x_b - x_a) * t, 0, 0) for t in np.linspace(0, 1, 30)]
    pts = [(x_a + (x_b - x_a) * t, 0, 0) for t in np.linspace(0, 1, 16)]
    kit.obj("GripCore", K.tube_uv(pts, 0.0112, sides=24, radius_fn=core_r, flat=0.84), mat_wood("sword_m_wood"), node_b,
            outline=1.0, density=1.5)
    fer = [(0.0136, 0.0), (0.0141, 0.0006), (0.0141, 0.0016), (0.0134, 0.0022), (0.0134, 0.0040), (0.0139, 0.0046),
           (0.0139, 0.0058), (0.0131, 0.0066), (0.0127, 0.0080), (0.0120, 0.0090)]
    _lathe_x("FerruleA", fer, gilt, node_b, GRIP_X0 + 0.0006, segments=40, oval=0.84, density=1.4)
    fer_b = [(0.0120, 0.0), (0.0128, 0.0010), (0.0134, 0.0024), (0.0134, 0.0040), (0.0128, 0.0048), (0.0128, 0.0066),
             (0.0118, 0.0074)]
    _lathe_x("FerruleB", fer_b, gilt, node_b, POMMEL_X - 0.0004, segments=40, oval=0.84, density=1.4, direction=1)
    # 丝绳：手缠的，圈距、松紧略不匀
    rc = 0.00245
    c0, c1 = GRIP_X0 - 0.0300, POMMEL_X + 0.0290  # 缠绳只缠中段，两头各露出两厘米木头
    pitch = 2 * rc * 1.10
    turns = int((c0 - c1) / pitch)
    jit_r = wavy(41, n=5, lo=0.02, hi=0.08, amp=0.00012)
    jit_p = wavy(42, n=4, lo=0.03, hi=0.09, amp=0.00025)
    cord = []
    nper = 10
    for i in range(turns * nper + 1):
        t = i / (turns * nper)
        a = 2 * math.pi * i / nper
        x = c0 - (c0 - c1) * t + jit_p(t * 0.14)
        rr = 0.0112 * core_r((x_a - x) / (x_a - x_b)) + rc * 0.62 + jit_r(t * 0.14)
        cord.append((x, rr * 0.84 * math.cos(a) + rc * 0.16 * math.cos(a), rr * math.sin(a)))
    kit.tube_bake_uv(kit.obj("Cord", K.tube_uv(cord, rc, sides=6), mat_cord("sword_m_cord"), node_b, outline=0.45, density=1.2),
                     rc, 0.22)
    # ---- 剑首：洋葱形的圆顶，端面宝相花；挂环
    prel = kit.np_image("sword_pommel_relief", pommel_relief())
    gilt_p = mat_gilt_bronze("sword_m_pommel", relief=(prel, "pommel"), relief_mode=POMMEL_X - 0.0274)
    prof = [(0.0118, 0.0), (0.0124, 0.0025), (0.0152, 0.0058), (0.0188, 0.0092), (0.0204, 0.0118), (0.0197, 0.0128),
            (0.0199, 0.0140), (0.0203, 0.0152), (0.0192, 0.0180), (0.0168, 0.0212), (0.0124, 0.0246), (0.0068, 0.0266),
            (0.0030, 0.0272), (0.0, 0.0274)]
    _lathe_x("Pommel", prof, gilt_p, node_b, POMMEL_X, segments=36, oval=0.84, density=1.6)
    ring_x = POMMEL_X - 0.0272 - 0.0034
    kit.obj("Ring", K.torus_build(0.0046, 0.00135, seg=28, ring=8), gilt, node_b, outline=0.6, density=1.2,
            loc=(ring_x, 0, 0), rot=(math.pi / 2, 0, 0))
    # ---- 剑穗（单独一个节点，绕挂点摆）
    silk = mat_silk("sword_m_silk")
    pivot = Vector((ring_x, 0.0, -0.0046))
    hang = pivot + Vector((0, 0, -0.0010))
    loop = []
    for a in np.linspace(-math.pi * 0.92, math.pi * 0.92, 26):  # 绕环的下沿套一圈（在 YZ 平面）
        loop.append((ring_x + 0.0004 * math.sin(a * 2), 0.0026 * math.sin(a), -0.0046 + 0.0026 * math.cos(a)))
    kit.tube_bake_uv(kit.obj("TasselLoop", K.tube_uv(loop, 0.00105, sides=6), silk, node_q, outline=0.5), 0.00105)
    knot_z = -0.0335
    za, zb = -0.0071, knot_z + 0.0040
    for sg in (-1, 1):
        pts = [(ring_x + 0.0002 * sg * math.sin(math.pi * t), sg * (0.00065 + 0.0007 * math.sin(math.pi * t)), za + (zb - za) * t)
               for t in np.linspace(0, 1, 9)]
        kit.tube_bake_uv(kit.obj(f"TasselCord{sg}", K.tube_uv(pts, 0.00105, sides=6), silk, node_q, outline=0.5), 0.00105)
    kit.tube_bake_uv(kit.obj("Knot", kit.torus_knot(2, 3, R=0.0036, r=0.0017, tube=0.00115, n=100, sides=6), silk, node_q,
                             outline=0.5, loc=(ring_x, 0, knot_z), rot=(math.pi / 2, 0, 0.3)), 0.00115)
    jade_z = knot_z - 0.0112
    kit.obj("Bead", K.lathe_uv([(0.0, -0.0056), (0.0030, -0.0049), (0.0052, -0.0028), (0.0058, 0.0), (0.0052, 0.0028),
                                (0.0030, 0.0049), (0.0, 0.0056)], segments=20), mat_jade("sword_m_jade"), node_q, outline=0.7,
            loc=(ring_x, 0, jade_z))
    cap_top = jade_z - 0.0052
    cap = [(0.0, 0.0), (0.0021, 0.0), (0.0026, -0.0010), (0.0030, -0.0022), (0.0034, -0.0024), (0.0036, -0.0034),
           (0.0046, -0.0062), (0.0057, -0.0098), (0.0062, -0.0112), (0.0060, -0.0122), (0.0050, -0.0126), (0.0, -0.0124)]
    kit.obj("Cap", K.lathe_uv(cap, segments=20), gilt, node_q, outline=0.7, loc=(ring_x, 0, cap_top), density=1.5)
    rng = np.random.default_rng(7)
    z0 = cap_top - 0.0112

    def strands(bm):
        import bmesh  # noqa: PLC0415

        bpy = K._bpy()
        for k in range(38):
            a = rng.uniform(0, 2 * math.pi)
            rr = 0.0047 * math.sqrt(rng.uniform(0.05, 1))
            Ls = rng.uniform(0.088, 0.112)
            sway = rng.uniform(-1, 1)
            ph = rng.uniform(0, 2 * math.pi)
            pts = []
            for t in np.linspace(0, 1, 6):
                spread = 1 + 0.9 * t
                dx = 0.010 * t * t * sway + 0.0012 * math.sin(3.0 * t + ph)
                pts.append((ring_x + rr * math.cos(a) * spread + dx, rr * math.sin(a) * spread + 0.0015 * math.sin(2.4 * t + ph) * t,
                            z0 + 0.003 - Ls * t))
            tmp = bmesh.new()
            K.tube_uv(pts, 0.00072, sides=4, caps=False, radius_fn=lambda t: 1.0 - 0.45 * t ** 3)(tmp)
            me = bpy.data.meshes.new("tmp")
            tmp.to_mesh(me)
            tmp.free()
            bm.from_mesh(me)
            bpy.data.meshes.remove(me)

    kit.tube_bake_uv(kit.obj("Strands", strands, mat_silk("sword_m_strands", fiber=False), node_q, outline=0.0, density=0.8),
                     0.00072)
    # ---- 符纸
    art, ink = talisman_art()
    art_img = kit.np_image("sword_talisman_art", art, colorspace="sRGB")
    ink_img = kit.np_image("sword_talisman_ink", ink)
    pts, ups = [], []
    glue_end = TALI_X0 - TALI_GLUE
    L_free = 0.150
    xs = list(np.linspace(TALI_X0, glue_end, 30)) + list(np.linspace(glue_end, glue_end - L_free, 84)[1:])
    for x in xs:
        s = max(0.0, (glue_end - x) / L_free)
        lift = sstep(0.0, 0.35, s)
        y = blade_surface_y(x, 0.0) - 0.00016 - 0.034 * lift * s ** 0.8 - 0.006 * math.sin(5.0 * s) * lift
        z = (0.011 * math.sin(7.0 * s - 0.4) - 0.022 * s) * lift
        pts.append((float(x), y, z))
        phi = 0.55 * lift * math.sin(5.5 * s + 0.2)
        ups.append((0.0, -math.sin(phi), -math.cos(phi)))
    total = sum(math.dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1))
    glue_t = TALI_GLUE / total
    el = wavy(11, n=7, lo=0.0012, hi=0.0050, amp=0.00032)
    er = wavy(12, n=7, lo=0.0012, hi=0.0050, amp=0.00032)
    jag = wavy(13, n=5, lo=0.05, hi=0.25, amp=0.0016)

    def lift_fn(t, s):
        off = (s - 0.5) * TALI_W
        x = TALI_X0 - min(t, glue_t) * total
        hw0, th, be, te, _ = blade_dims(x)
        v_glued = (th - te) * abs(off) / max(hw0 - be, 1e-6)  # 贴在剑脊两边的斜面上：横截面是个浅 V
        relax = sstep(glue_t, glue_t + 0.12, t)
        v = v_glued * (1 - relax) + 0.0014 * (1 - 2 * abs(s - 0.5)) * relax * -1
        e = abs(2 * s - 1)
        curl_e = (0.0003 + 0.0016 * relax) * e ** 2.4  # 两边微微卷起来（贴住的那段只翘一点点）
        crease = curl_e
        for k, tc in enumerate((1 / 3, 2 / 3)):
            crease += (0.0007 if k else -0.0006) * math.exp(-(((t - tc) * total) / 0.0016) ** 2) * relax
        return -v + crease

    kit.obj("Talisman", kit.slab_strip(pts, ups, lambda t: TALI_W, 0.00022, segs_w=5, edge_l=lambda t: el(t * total),
                                       edge_r=lambda t: er(t * total), end_jag=lambda s: 0.0008 + jag(s), lift=lift_fn),
            mat_paper("sword_m_paper", art_img, ink_img, total), node_t, outline=0.5, density=1.6)
    return {
        "id": "sword",
        # 2K 烘、1K 出（2 MB 的体积放不下 2K 的 PNG：底色光 2K 就 1.7 MB）；粗糙度金属度、自发光 512
        "atlases": {"body": {"size": 2048, "nodes": [node_b, node_t, node_q], "ao_dist": 0.012,
                             "channels": ["base", "normal", "mr", "emit"],
                             "out": {"base": 1024, "normal": 1024, "mr": 512, "emit": 512}}},
        "nodes": {node_b: {}, node_t: {"keys": "talisman"}, node_q: {"pivot": tuple(pivot)}},
        "keys": {"talisman": talisman_keys(glue_end, L_free)},
        "anim": {"frames": 96, "fps": 24,
                 "swing": {node_q: [(0, 4.0, 1, 0.0), (1, 1.6, 2, 0.0)]},
                 "weights": {node_t: [("flutter_a", 0.8, 2, 0.0), ("flutter_b", 0.8, 2, math.pi / 2)]}},
        "outline_width": 0.0030,
        "outline_ratio": 0.32,
    }


def talisman_keys(glue_end, L_free):
    """符纸的两个形变（抖动的两个相位）：只动离开剑身的那段，越往末端越大；横向的波沿纸往后走。"""

    def make(phase):
        def f(co, attr):
            _ = attr
            x = co[:, 0]
            s = np.clip((glue_end - x) / L_free, 0, 1)
            a = ss(0.05, 0.6, s) * s
            w = np.sin(9.0 * s + phase)
            out = np.zeros_like(co)
            out[:, 2] = 0.006 * a * w
            out[:, 1] = -0.004 * a * np.cos(9.0 * s + phase)
            return out

        return f

    return {"flutter_a": make(0.0), "flutter_b": make(math.pi / 2)}


# ====================================================================== 风火轮
# 一对轮子交叠摆放（前轮在左下、后轮在右上，同灯坠图标）。轮子在自己的坐标里：轮轴是 Y（正面朝 -Y），轮面在 XZ 平面。
# 建模先在“车床坐标”（轮轴 Z、正面 +Z）里做一个 45° 的重复单元（一根辐条、两片莲瓣、一颗莲子……），展好 UV，
# 再复制成 8 份（共用 UV：贴图上只画一个扇区，纹素密度是整圈摊开的 8 倍），最后转到轮轴 Y。程序纹理都用周期坐标，扇区之间没有接缝。
WW_N = 8
WW_R_OUT, WW_R_IN, WW_T = 0.150, 0.126, 0.0110  # 轮圈外、内半径，半厚
RIM_BAND = (0.1272, 0.1494)  # 正反两面浮雕贴图覆盖的半径（含两道边珠）
PC_CO, PC_W = kit.periodic_coords(WW_N)
WW_A = ((-0.072, 0.0, -0.040), (math.radians(-8.0), 0.0, math.radians(17.0)))  # 前轮：位置、欧拉角（YXZ：先绕轮轴转）
WW_B = ((0.080, 0.092, 0.050), (math.radians(5.0), math.radians(22.0), math.radians(-12.0)))  # 后轮


def _rim_profile():
    """轮圈截面 (r, z)：首尾相连的一圈（车床坐标，z 是轮轴，正 = 正面）。
    内面平；正反两面平（两道边珠和中间的卷云都在浮雕贴图里）；外缘中间一道凸棱，两侧各一道凹槽（填朱漆），圆角过渡。"""
    T = WW_T
    front = [(0.1268, T * 0.90), (0.1277, T), (0.1384, T * 1.01), (0.1490, T), (0.1499, T * 0.90)]
    outer = [(0.1502, 0.0080), (0.1493, 0.0068), (0.1490, 0.0051), (0.1493, 0.0035), (0.1506, 0.0030), (0.1515, 0.0016),
             (0.1517, 0.0)]
    top = front + outer
    bot = [(r, -z) for r, z in reversed(top) if z > 1e-9]
    inner = [(0.1261, -T * 0.5), (0.1258, 0.0), (0.1261, T * 0.5)]
    return top + bot + inner


def _hub_profile():
    """轮毂截面 (r, z)：从正面轴头顶（r = 0）一路到背面轴头顶，绕轴转一圈是实心的。
    轴头（平顶，上面嵌火珠，火珠另做）→ 轴 → 莲蓬（顶面平，莲子另做）→ 毂的正面（一道边珠）→ 圆角 → 毂侧（中间朱漆、两道边珠）→ 背面对称。"""
    half = [(0.0, 0.0284), (0.0038, 0.0283), (0.0057, 0.0279), (0.0057, 0.0234), (0.0070, 0.0229), (0.0104, 0.0226), (0.0115, 0.0220),
            (0.0119, 0.0208), (0.0119, 0.0160), (0.0160, 0.0155), (0.0244, 0.0154), (0.0262, 0.0159), (0.0271, 0.0168),
            (0.0281, 0.0159), (0.0302, 0.0154), (0.0338, 0.0151), (0.0354, 0.0143), (0.0361, 0.0127), (0.0362, 0.0092),
            (0.0369, 0.0086), (0.0369, 0.0058), (0.0362, 0.0052), (0.0360, 0.0)]
    return half + [(r, -z) for r, z in reversed(half[:-1])]


def sector_revolve(profile, segs, a0, a1, closed=False):
    """(r, z) 截面绕 Z 轴转过扇区 [a0, a1]（弧度），带 UV（u = 角度比例，v = 截面弧长米）。r = 0 的点合成一个。"""
    prof = [(float(r), float(z)) for r, z in profile]
    if closed:
        prof = prof + [prof[0]]
    arcs = [0.0]
    for (r0, z0), (r1, z1) in zip(prof, prof[1:]):
        arcs.append(arcs[-1] + math.hypot(r1 - r0, z1 - z0))

    def build(bm):
        import bmesh  # noqa: PLC0415

        uvl = bm.loops.layers.uv.new("UVMap")
        rings = []
        for i, (r, z) in enumerate(prof):
            if closed and i == len(prof) - 1:
                rings.append(rings[0])
                continue
            if r <= 1e-7:
                v = bm.verts.new((0.0, 0.0, z))
                rings.append([v] * (segs + 1))
                continue
            rings.append([bm.verts.new((r * math.cos(a), r * math.sin(a), z)) for a in np.linspace(a0, a1, segs + 1)])
        for i in range(len(prof) - 1):
            a, b = rings[i], rings[i + 1]
            for k in range(segs):
                vs = [a[k], a[k + 1], b[k + 1], b[k]]
                uvs = [(k / segs, arcs[i]), ((k + 1) / segs, arcs[i]), ((k + 1) / segs, arcs[i + 1]), (k / segs, arcs[i + 1])]
                if vs[0] is vs[1]:
                    vs, uvs = vs[1:], uvs[1:]
                elif vs[2] is vs[3]:
                    vs, uvs = vs[:3], uvs[:3]
                try:
                    f = bm.faces.new(vs)
                except ValueError:
                    continue
                for lp, uv in zip(f.loops, uvs):
                    lp[uvl].uv = uv
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)

    return build


def _revolve_bake_uv(ob, half):
    """扇区旋转体的烘焙 UV：沿圈 = 角度 × 该点半径（米），沿截面 = 截面弧长（米）。整个扇区一个岛，只在截面首尾断开。"""
    me = ob.data
    uv = np.zeros(len(me.loops) * 2, np.float32)
    me.uv_layers["UVMap"].data.foreach_get("uv", uv)
    uv = uv.reshape(-1, 2)
    vi = np.zeros(len(me.loops), np.int64)
    me.loops.foreach_get("vertex_index", vi)
    co = np.zeros(len(me.vertices) * 3)
    me.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3)
    r = np.hypot(co[vi, 0], co[vi, 1])
    b = np.stack([(uv[:, 0] - 0.5) * 2 * half * r, uv[:, 1]], -1)
    bu = me.uv_layers.get("BakeUV") or me.uv_layers.new(name="BakeUV")
    bu.data.foreach_set("uv", b.ravel())
    ob["inspect_uv"] = "premade"


def petal_build(r0, length, half_w, lift, cup=0.0012, thick=0.0013, ns=5, nt=4, back=False):
    """一片莲瓣（车床坐标，沿 +X）：瓣根在 r0，尖朝外、往正面翘起 lift，横向微微兜成勺形；正反两层合成的薄片。
    UV：u = 沿瓣 0..1，v = 横跨 0..1（材质里画脉）。back=True 时镜像到背面（z 取反）。"""

    def build(bm):
        import bmesh  # noqa: PLC0415

        uvl = bm.loops.layers.uv.new("UVMap")
        sg = -1.0 if back else 1.0
        grids = []
        for side in (0, 1):
            g = []
            for i in range(ns + 1):
                s = i / ns
                w = half_w * math.sin(math.pi * min(1.0, 0.18 + 0.82 * s)) ** 0.75 * (1.0 if s < 0.999 else 0.0)
                w = max(w, 1e-5) if s < 0.999 else 0.0
                row = []
                for j in range(nt + 1):
                    t = j / nt * 2 - 1
                    x = r0 + length * s
                    y = w * t
                    zc = WW_T * 0 + lift * s ** 1.5 + cup * (t * t) * math.sin(math.pi * s)
                    th = thick * (1 - t * t) ** 0.5 * (1 - s ** 3) + 0.00015
                    z = zc + (th if side == 0 else 0.0)
                    row.append(bm.verts.new((x, y, sg * z)))
                g.append(row)
            grids.append(g)
        for gi, g in enumerate(grids):
            for i in range(ns):
                for j in range(nt):
                    vs = [g[i][j], g[i + 1][j], g[i + 1][j + 1], g[i][j + 1]]
                    if gi == 1:
                        vs.reverse()
                    try:
                        f = bm.faces.new(vs)
                    except ValueError:
                        continue
                    for lp in f.loops:
                        x, y = lp.vert.co.x, lp.vert.co.y
                        lp[uvl].uv = ((x - r0) / length, 0.5 + y / (2 * half_w))
        # 两层的边缘缝起来
        for i in range(ns):
            for j in (0, nt):
                try:
                    bm.faces.new((grids[0][i][j], grids[0][i + 1][j], grids[1][i + 1][j], grids[1][i][j]))
                except ValueError:
                    pass
        for j in range(nt):
            try:
                bm.faces.new((grids[0][0][j], grids[0][0][j + 1], grids[1][0][j + 1], grids[1][0][j]))
            except ValueError:
                pass
        bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-7)
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)

    return build


def rim_relief_tile(W=1024, H=224, seed=3):
    """轮圈正反两面的浮雕：一个扇区（45°）一格，左右无缝。一道卷云的 S 形主线（每格两个波），波峰波谷各卷出一个螺旋，
    主线两侧点几颗连珠。行 = 半径从外（上）到内（下）。返回 0..1 高度。"""
    lines = []
    mid = H / 2
    amp = H * 0.17
    xs = np.linspace(-W * 0.1, W * 1.1, 400)
    wave = [(x, mid + amp * math.sin(2 * math.pi * 2 * x / W)) for x in xs]
    lines.append((wave, H * 0.058))
    blobs = []
    for k in range(-1, 5):
        xc = (k + 0.25) * W / 2
        up = 1.0
        for sgn, xx in ((1.0, xc), (-1.0, xc + W / 4)):
            cy = mid - sgn * amp * 0.25
            sp = kit.spiral(xx + W * 0.055 * sgn * up, cy + sgn * H * 0.06, H * 0.18, H * 0.025, 1.5, a0=math.pi * (0.5 if sgn > 0 else -0.5),
                            sign=sgn, n=120)
            lines.append((sp, H * 0.048))
            blobs.append((xx - W * 0.07 * sgn, mid + sgn * H * 0.24, H * 0.035))
    for yb in (H * 0.075, H * 0.925):  # 两道边珠
        lines.append(([(-W * 0.2, yb), (W * 1.2, yb)], H * 0.065))
    mask = np.zeros((H, W))
    for pts, wd in lines:
        # 左右各多画一份再取模，保证无缝
        for off in (-W, 0, W):
            shifted = [(x + off, y) for x, y in pts]
            mask = np.maximum(mask, kit.draw_lines((H, W), [shifted], wd))
    Y, X = np.mgrid[0:H, 0:W]
    for cx, cy, r in blobs:
        for off in (-W, 0, W):
            d = np.hypot(X - cx - off, Y - cy) / r
            mask = np.maximum(mask, np.clip(1.3 - d * 1.3, 0, 1) ** 0.6)
    return kit.height_from_mask(mask, 1.6)


def ribbon_pattern(W=512, H=192, seed=4):
    """红绸织锦：沿长（列）一个周期，横跨（行）是绸带的宽。两边各两道金线，中间一行如意云头，云头之间一颗金点。
    返回 (金线遮罩, 织纹高度)。"""
    lines = []
    for y in (0.08, 0.15, 0.85, 0.92):
        lines.append(([(-10, y * H), (W + 10, y * H)], H * 0.022))
    for k in range(2):
        cx = (k + 0.5) * W / 2
        cy = H / 2
        r = H * 0.16
        # 如意云头：三个相切的小圈 + 一条尾巴
        for dx, dy, rr in ((-0.9, 0.15, 0.55), (0.0, -0.35, 0.62), (0.9, 0.15, 0.55)):
            ring = [(cx + dx * r + rr * r * math.cos(a), cy + dy * r + rr * r * math.sin(a)) for a in np.linspace(0, 2 * math.pi, 50)]
            lines.append((ring, H * 0.022))
        tail = [(cx - 0.2 * r + t * r * 1.6, cy + 0.9 * r + 0.35 * r * math.sin(t * 5)) for t in np.linspace(0, 1, 30)]
        lines.append((tail, H * 0.022))
    mask = np.zeros((H, W))
    for pts, wd in lines:
        for off in (-W, 0, W):
            mask = np.maximum(mask, kit.draw_lines((H, W), [[(x + off, y) for x, y in pts]], wd))
    Y, X = np.mgrid[0:H, 0:W]
    for k in range(2):
        cx = k * W / 2
        for off in (-W, 0, W):
            d = np.hypot(X - cx - off, Y - H / 2) / (H * 0.05)
            mask = np.maximum(mask, np.clip(1.3 - d * 1.3, 0, 1))
    return np.clip(kit.blur(mask, 0.7), 0, 1), weave_tile()


def weave_tile(n=64, threads=8):
    """平纹织物的一格（左右上下无缝）：经线、纬线一上一下交错，每根线是圆鼓的截面。返回 0..1 高度。"""
    Y, X = np.mgrid[0:n, 0:n] / n * threads
    i, j = np.floor(X).astype(int), np.floor(Y).astype(int)
    fx, fy = X - i, Y - j
    warp = np.sin(np.pi * fx) ** 0.7 * (0.75 + 0.25 * np.sin(np.pi * fy))
    weft = np.sin(np.pi * fy) ** 0.7 * (0.75 + 0.25 * np.sin(np.pi * fx))
    up = (i + j) % 2 == 0
    return np.where(up, 0.5 + 0.5 * warp, 0.5 + 0.5 * weft) * 0.9


# ---------------------------------------------------------------------- 风火轮：材质


def mat_wheel(name, relief_img):
    """轮子的铜鎏金：周期坐标的噪声（8 个扇区无缝）。鎏金面、磨亮的棱和浮雕高处露出黄铜、凹处的铜绿和污垢；
    轮圈外缘两道凹槽和轮毂侧面填朱漆（漆面有细裂）；正反两面浮雕带是卷云纹。"""
    M = PMat(name, co=PC_CO, w=PC_W)
    x, y, z = M.sep(M.coord("Object"))
    r = M.math("SQRT", M.math("ADD", M.math("MULTIPLY", x, x), M.math("MULTIPLY", z, z)))
    ay = M.math("ABSOLUTE", y)
    u = M.math("FRACT", M.math("ADD", M.math("DIVIDE", M.math("MULTIPLY", M.math("ARCTAN2", z, x), float(WW_N)), 2 * math.pi), 0.5))
    g = M.n("ShaderNodeNewGeometry")
    # 法线在物体空间：烘的时候轮子已经摆好位置了，世界法线要转回物体空间
    vt = M.n("ShaderNodeVectorTransform", _vector_type="NORMAL", _convert_from="WORLD", _convert_to="OBJECT")
    M.l(g.outputs["Normal"], vt.inputs["Vector"])
    _, ny, _ = M.sep(vt.outputs["Vector"])
    face = M.maprange(M.math("ABSOLUTE", ny), 0.6, 0.85)
    band = M.math("MULTIPLY", M.maprange(r, RIM_BAND[0] - 0.0003, RIM_BAND[0] + 0.0001), M.maprange(r, RIM_BAND[1] + 0.0003, RIM_BAND[1] - 0.0001))
    band = M.math("MULTIPLY", band, M.math("MULTIPLY", face, M.maprange(ay, 0.0096, 0.0104)))
    v = M.math("DIVIDE", M.math("SUBTRACT", r, RIM_BAND[0]), RIM_BAND[1] - RIM_BAND[0])
    h = M.math("MULTIPLY", M.sep(M.image(relief_img, M.comb(u, v, 0.0), extension="REPEAT"))[0], band)
    # 朱漆：轮圈外缘两道槽、轮毂侧面中段
    groove = M.math("MULTIPLY", M.maprange(r, 0.1484, 0.1490), M.math("MULTIPLY", M.maprange(ay, 0.0030, 0.0035),
                                                                        M.maprange(ay, 0.0072, 0.0066)))
    drum = M.math("MULTIPLY", M.math("MULTIPLY", M.maprange(r, 0.0352, 0.0358), M.maprange(r, 0.0372, 0.0366)),
                  M.maprange(ay, 0.0050, 0.0046))
    lac = M.math("MAXIMUM", groove, drum)
    cav = M.cavity(0.003)
    edge = M.edge(0.0007, 0.0, 0.10)
    n1 = M.nz(45.0, detail=5.0, rough=0.62, seed=1.0)
    n2 = M.nz(220.0, detail=4.0, rough=0.6, seed=2.0)
    wear = M.math("ADD", M.math("MULTIPLY", edge, 0.8), M.math("MULTIPLY", M.maprange(h, 0.55, 0.95), 0.9), clamp=True)
    wear = M.math("ADD", wear, M.math("MULTIPLY", M.maprange(n1, 0.60, 0.74), 0.4), clamp=True)
    wear = M.math("MULTIPLY", wear, M.math("SUBTRACT", 1.0, M.math("MULTIPLY", cav, 1.5), clamp=True))
    rim_ = M.math("SUBTRACT", M.maprange(h, 0.02, 0.25), M.maprange(h, 0.3, 0.6), clamp=True)
    grime = M.math("ADD", M.math("MULTIPLY", cav, 1.7), M.math("MULTIPLY", rim_, 0.7), clamp=True)
    grime = M.math("ADD", grime, M.math("MULTIPLY", M.maprange(n1, 0.28, 0.40, 0.5, 0.0), 0.5), clamp=True)
    gold = M.mix(M.maprange(n2, 0.2, 0.8), (0.76, 0.51, 0.19, 1.0), (0.86, 0.60, 0.25, 1.0))
    col = M.mix(wear, gold, (0.74, 0.56, 0.30, 1.0))
    patina = M.mix(M.nz(80.0, seed=5.0), (0.06, 0.10, 0.07, 1.0), (0.12, 0.17, 0.11, 1.0))
    col = M.mix(M.math("MULTIPLY", grime, 0.85), col, patina)
    crack = M.maprange(M.voronoi(900.0, feature="DISTANCE_TO_EDGE"), 0.0, 0.06, 1.0, 0.0)
    lacq = M.mix(M.nz(160.0, seed=7.0), (0.30, 0.022, 0.014, 1.0), (0.42, 0.040, 0.020, 1.0))
    lacq = M.mix(M.math("MULTIPLY", crack, 0.5), lacq, (0.10, 0.010, 0.008, 1.0))
    col = M.mix(lac, col, lacq)
    col = M.stroke(col, amount=0.06, scale=35.0)
    rough = M.mixf(wear, M.math("ADD", 0.30, M.math("MULTIPLY", n1, 0.10)), 0.20)
    rough = M.mixf(grime, rough, 0.70)
    rough = M.mixf(lac, rough, M.math("ADD", 0.26, M.math("MULTIPLY", crack, 0.3)))
    metal = M.math("SUBTRACT", 1.0, M.math("MAXIMUM", M.math("MULTIPLY", grime, 0.85), lac), clamp=True)
    M.normal_base(M.bevel_normal(0.0005))
    M.bump_add(h, strength=0.8, distance=0.0005)
    M.bump_add(M.math("ADD", M.math("MULTIPLY", n2, 0.4), M.math("MULTIPLY", crack, M.math("MULTIPLY", lac, 0.6))), strength=0.05,
               distance=0.00015)
    return M.set(base=col, rough=rough, metal=metal)


def mat_petal(name):
    """莲瓣：鎏金，中脉一道凸棱、两侧各两道细脉，瓣尖磨亮，瓣根积锈。UV：u 沿瓣、v 横跨。"""
    M = PMat(name, co=PC_CO, w=PC_W)
    s, t, _ = M.sep(M.uv())
    tc = M.math("SUBTRACT", t, 0.5)
    rib = M.math("EXPONENT", M.math("MULTIPLY", M.math("POWER", M.math("DIVIDE", tc, 0.035), 2.0), -1.0))
    veins = None
    for k in (-1, 1):
        for a in (0.18, 0.33):
            d = M.math("SUBTRACT", tc, M.math("MULTIPLY", s, k * a))
            vv = M.math("EXPONENT", M.math("MULTIPLY", M.math("POWER", M.math("DIVIDE", d, 0.022), 2.0), -1.0))
            veins = vv if veins is None else M.math("MAXIMUM", veins, vv)
    hgt = M.math("ADD", rib, M.math("MULTIPLY", veins, M.maprange(s, 0.1, 0.5, 0.0, 0.6)))
    cav = M.cavity(0.0025)
    edge = M.edge(0.0006, 0.0, 0.12)
    tip = M.maprange(s, 0.6, 1.0)
    wear = M.math("ADD", M.math("MULTIPLY", edge, 0.8), M.math("MULTIPLY", tip, 0.35), clamp=True)
    col = M.mix(wear, (0.86, 0.60, 0.25, 1.0), (0.76, 0.58, 0.31, 1.0))
    col = M.mix(M.math("MULTIPLY", M.math("ADD", cav, M.maprange(s, 0.25, 0.0, 0.0, 0.5)), 0.9), col, (0.08, 0.11, 0.07, 1.0))
    col = M.stroke(col, amount=0.06, scale=60.0)
    rough = M.mixf(wear, 0.30, 0.20)
    M.normal_base(M.bevel_normal(0.0004))
    M.bump_add(hgt, strength=0.5, distance=0.0003)
    return M.set(base=col, rough=rough, metal=M.math("SUBTRACT", 1.0, M.math("MULTIPLY", cav, 0.7), clamp=True))


def mat_flame(name, layer, strength):
    """火舌：UV 是归一化的（u = 0 根 → 1 尖，v 绕一圈）。颜色从根到尖：里层白金 → 金 → 橙；外层金 → 橙 → 朱红 → 暗红。
    宽面中线一道最亮的芯，往两条窄边变红变暗（像画里火焰纹的描边）；顺着火舌往上走的几道细纹（火在流）。
    外层半透明：火身 alpha 约 0.75，窄边更透，尖上渐隐；里层不透明。底色是同一套颜色压暗，亮度靠自发光。"""
    M = PMat(name)
    u, v, _ = M.sep(M.uv())
    side = M.math("ABSOLUTE", M.math("COSINE", M.math("MULTIPLY", v, 2 * math.pi)))  # 1 = 窄边（截面长轴两端），0 = 宽面中线
    rimc = M.maprange(side, 0.55, 0.98)
    core = M.maprange(side, 0.35, 0.0)
    vec = M.comb(M.math("MULTIPLY", u, 3.0), M.math("MULTIPLY", v, 1.0), 0.0)
    nz = M.nz(2.2, detail=4.0, rough=0.6, co=vec, seed=float(layer))
    flow = M.math("SINE", M.math("MULTIPLY", M.math("ADD", M.math("MULTIPLY", v, 5.0),
                                                     M.math("ADD", M.math("MULTIPLY", u, 1.8), M.math("MULTIPLY", nz, 0.8))),
                               2 * math.pi))
    flow = M.maprange(flow, -1.0, 1.0)
    if layer == 0:
        stops = [(0.0, (1.0, 0.90, 0.58)), (0.45, (1.0, 0.70, 0.24)), (1.0, (1.0, 0.48, 0.09))]
    else:
        stops = [(0.0, (1.0, 0.80, 0.38)), (0.20, (1.0, 0.57, 0.13)), (0.48, (0.98, 0.31, 0.045)), (0.76, (0.80, 0.11, 0.02)),
                 (1.0, (0.36, 0.03, 0.015))]
    t = M.math("ADD", u, M.math("MULTIPLY", M.maprange(nz, 0.3, 0.7, -0.08, 0.08), 1.0))
    t = M.math("ADD", t, M.math("MULTIPLY", rimc, 0.24 if layer else 0.12))
    t = M.math("SUBTRACT", t, M.math("MULTIPLY", core, 0.10))
    t = M.math("ADD", t, M.math("MULTIPLY", flow, 0.05))
    col, _ = M.ramp(t, stops)
    emit_k = M.math("MULTIPLY", M.math("ADD", M.math("MULTIPLY", M.math("SUBTRACT", 1.0, u, clamp=True), 0.65), 0.35),
                    M.math("SUBTRACT", 1.0, M.math("MULTIPLY", rimc, 0.35)))
    emit_k = M.math("MULTIPLY", emit_k, M.math("ADD", 0.85, M.math("ADD", M.math("MULTIPLY", core, 0.45), M.math("MULTIPLY", flow, 0.15))))
    base = M.mix(0.55, col, (0.0, 0.0, 0.0, 1.0))
    if layer == 0:
        alpha = 1.0
    else:
        tipfade = M.maprange(u, 0.58, 1.0, 1.0, 0.0, interp="SMOOTHSTEP")
        body = M.math("SUBTRACT", 0.80, M.math("MULTIPLY", rimc, 0.35))
        alpha = M.math("MULTIPLY", tipfade, M.math("ADD", body, M.math("MULTIPLY", core, 0.15)))
        alpha = M.math("MULTIPLY", alpha, M.maprange(nz, 0.25, 0.55, 0.75, 1.0))
        alpha = M.math("MULTIPLY", alpha, M.math("ADD", 0.88, M.math("MULTIPLY", flow, 0.12)), clamp=True)
    return M.set(base=base, rough=0.6, metal=0.0, emit=col, emit_strength=M.math("MULTIPLY", emit_k, strength), alpha=alpha)


def mat_brocade(name, gold_img, weave_img, period=0.048):
    """红绸织锦（飘带）：朱红绸面、两边金线、一行如意云头（金线织的，微微凸起、半光）；细的经纬织纹，凹处暗。
    UV：u = 弧长米，v = 0..1 横跨。"""
    M = PMat(name)
    u, v, _ = M.sep(M.uv())
    vec = M.comb(M.math("DIVIDE", u, period), v, 0.0)
    gold = M.sep(M.image(gold_img, vec, extension="REPEAT"))[0]
    weave = M.sep(M.image(weave_img, M.comb(M.math("DIVIDE", u, 0.0032), M.math("MULTIPLY", v, 6.0), 0.0), extension="REPEAT"))[0]
    edge_d = M.attr("edge_d")
    n = M.nz(90.0, detail=4.0, seed=3.0)
    silk = M.mix(M.maprange(n, 0.3, 0.7), (0.44, 0.030, 0.016, 1.0), (0.66, 0.060, 0.026, 1.0))
    cav = M.cavity(0.002)
    col = M.mix(gold, silk, (0.80, 0.56, 0.22, 1.0))
    col = M.mix(M.math("MULTIPLY", cav, 0.8), col, (0.06, 0.006, 0.004, 1.0))
    fray = M.maprange(edge_d, 0.0, 0.0012, 1.0, 0.0)
    col = M.mix(M.math("MULTIPLY", fray, 0.35), col, (0.20, 0.015, 0.010, 1.0))
    col = M.stroke(col, amount=0.07, scale=50.0)
    rough = M.mixf(gold, M.math("ADD", 0.48, M.math("MULTIPLY", weave, 0.1)), 0.32)
    col = M.mix(M.math("MULTIPLY", M.maprange(weave, 0.45, 0.95, 1.0, 0.0), 0.25), col, (0.10, 0.008, 0.006, 1.0))  # 织纹的缝暗一点
    M.bump_add(M.math("ADD", M.math("MULTIPLY", weave, 0.7), M.math("MULTIPLY", gold, 0.8)), strength=0.35, distance=0.00018)
    return M.set(base=col, rough=rough, metal=M.math("MULTIPLY", gold, 0.9))


# ---------------------------------------------------------------------- 风火轮：建模


def _euler_matrix(eul, order="YXZ"):
    from mathutils import Euler  # noqa: PLC0415

    return Euler(eul, order).to_matrix()


def _flame_tongue(phi0, r0, z0, L, rho, *, sweep, wig=0.0, curl=0.0, zlean=0.0, flat=0.45, out=1.0, n=12, sides=6):
    """一条火舌的中心线（车床坐标）：从 (r0, phi0, z0) 往外窜、往后（-φ，轮子正面看逆时针转，火往顺时针拖）拖，S 形摆一下，尖上往回钩。
    返回 (tube build, 根点, 中心线)。"""
    pts = []
    for s in np.linspace(0.0, 1.0, n):
        rr = r0 + L * out * (0.82 * s + 0.18 * s * s)
        if curl:
            rr -= L * curl * 0.45 * max(0.0, (s - 0.68) / 0.32) ** 2
        ph = phi0 - (L / r0) * (sweep * s ** 1.25 - wig * math.sin(math.pi * s) * (1 - s))
        if curl:
            ph -= (L / r0) * curl * 0.6 * max(0.0, (s - 0.6) / 0.4) ** 2
        zz = z0 + zlean * L * s
        pts.append((rr * math.cos(ph), rr * math.sin(ph), zz))

    def radius(t):
        return (0.72 + 0.28 * math.sin(math.pi / 2 * min(1.0, t / 0.28))) * max(0.0, 1 - t) ** 0.85 + 0.02 * (1 - t)

    return K.tube_uv(pts, rho, sides=sides, radius_fn=radius, flat=flat, caps=True), pts[0], pts


@model("wind_wheel")
def build_wind_wheel(draft=False):
    """风火轮：哪吒脚下那对的小样，一对交叠摆放。四面都有做工：
    轮圈铜鎏金，正反两面边珠夹着卷云浮雕，外缘一道凸棱两道朱漆槽；八根宝瓶形辐条（两道箍）；轮毂正反两面八瓣莲花托着莲蓬（八颗莲子），
    毂侧朱漆、两道边珠，轴头圆钮；轮边一圈火：里层短火舌（不透明的白金）、外层长火舌（金到朱红，尖上渐隐，S 形、尖上回钩）、
    正反两面各几条舔过轮面的火、外面几点飞出去的火星；一条红绸织锦把两只轮子的轴头系在一起，打个结，两条燕尾飘带往左下飘。"""
    _ = draft
    import bmesh  # noqa: PLC0415
    from mathutils import Matrix, Vector  # noqa: PLC0415

    bpy = K._bpy()
    nA, nAf, nR = "wind_wheel_a", "wind_wheel_a_flame", "wind_wheel_ribbon"
    half = math.pi / WW_N
    relief = kit.np_image("wind_wheel_rim_relief", rim_relief_tile())
    m_wheel = mat_wheel("wind_wheel_m_bronze", relief)
    m_petal = mat_petal("wind_wheel_m_petal")
    # ---- 一个重复单元（车床坐标）
    parts = []
    rim = kit.obj("RimSec", sector_revolve(_rim_profile(), 10, -half, half, closed=True), m_wheel, "_sector", outline=1.0)
    _revolve_bake_uv(rim, half)
    parts.append(rim)
    parts.append(kit.obj("HubSec", sector_revolve(_hub_profile(), 5, -half, half), m_wheel, "_sector", outline=1.0, density=1.6))
    sp_prof = [(0.0060, 0.0), (0.0069, 0.0040), (0.0066, 0.0062), (0.0050, 0.0085), (0.0044, 0.0160), (0.0047, 0.0250),
               (0.0062, 0.0290), (0.0068, 0.0320), (0.0060, 0.0352), (0.0046, 0.0400), (0.0042, 0.0560), (0.0046, 0.0700),
               (0.0062, 0.0760), (0.0067, 0.0790), (0.0054, 0.0830), (0.0062, 0.0900), (0.0082, 0.0960)]
    sq = 0.72

    def radial(th, z, i):
        _ = z, i
        return 1.0 / math.sqrt((math.cos(th) / sq) ** 2 + math.sin(th) ** 2)

    parts.append(kit.obj("Spoke", K.lathe_uv(sp_prof, segments=8, radial=radial), m_wheel, "_sector", outline=0.8, density=1.3,
                         rot=(0, math.pi / 2, 0), loc=(0.0335, 0, 0)))
    for back in (False, True):
        zs = -1.0 if back else 1.0
        parts.append(kit.obj(f"PetalO{int(back)}", petal_build(0.0112, 0.0215, 0.0072, 0.0060, back=back), m_petal, "_sector",
                             outline=0.6, density=1.6, loc=(0, 0, zs * 0.0152)))
        pi_ = kit.obj(f"PetalI{int(back)}", petal_build(0.0108, 0.0150, 0.0058, 0.0072, back=back), m_petal, "_sector",
                      outline=0.6, density=1.8, loc=(0, 0, zs * 0.0160))
        pi_.rotation_euler = (0, 0, half)
        parts.append(pi_)
        seed = kit.obj(f"Seed{int(back)}", K.lathe_uv([(0.0, -0.0017), (0.0012, -0.0012), (0.0017, 0.0), (0.0012, 0.0012), (0.0, 0.0017)], segments=7),
                       m_wheel, "_sector", outline=0.0, density=1.5,
                       loc=(0.0087, 0, zs * 0.0222))
        parts.append(seed)
    sector = kit.join_objects(parts, "_sector_joined")
    kit.smart_unwrap_meters(sector, angle=72.0)
    # ---- 复制成 8 份、焊上扇区的边、转到轮轴 Y
    me = sector.data
    bm = bmesh.new()
    for k in range(WW_N):
        tmp = me.copy()
        tmp.transform(Matrix.Rotation(2 * math.pi * k / WW_N, 4, "Z"))
        bm.from_mesh(tmp)
        bpy.data.meshes.remove(tmp)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=2e-6)
    bmesh.ops.rotate(bm, verts=bm.verts, cent=(0, 0, 0), matrix=Matrix.Rotation(math.pi / 2, 3, "X"))
    wme = bpy.data.meshes.new("_wheel")
    bm.to_mesh(wme)
    bm.free()
    for m in me.materials:
        wme.materials.append(m)
    wme.shade_smooth()
    old = sector.data
    bpy.data.objects.remove(sector)
    bpy.data.meshes.remove(old)
    bpy.context.view_layer.update()
    wheel = bpy.data.objects.new("_wheel", wme)
    bpy.context.scene.collection.objects.link(wheel)
    kit.part(wheel, nA)
    wheel["inspect_uv"] = "premade"
    kit.set_attr(wme, "premade", np.ones(len(wme.polygons)), "FACE")
    # ---- 火珠：正反两个轴头上各嵌一颗（不在重复单元里，单独展 UV），里面盘着火纹，自己发光
    PEARL_Y, PEARL_R = 0.0326, 0.0066

    def pearl_center(M):
        _, y, _ = M.sep(M.co)
        return M.comb(0.0, M.math("MULTIPLY", M.math("SIGN", y), PEARL_Y), 0.0)

    def pearl_axis(M):
        _, y, _ = M.sep(M.co)
        return M.comb(0.0, M.math("SIGN", y), 0.0)

    m_pearl = mat_gem("wind_wheel_m_pearl", pearl_center, pearl_axis, PEARL_R, PEARL_R, deep=(0.22, 0.015, 0.004),
                      mid=(0.80, 0.16, 0.02), glow=(1.0, 0.52, 0.12), strength=2.2, swirl=9.0)
    pprof = [(0.0, -PEARL_R)] + [(PEARL_R * math.sin(a), -PEARL_R * math.cos(a)) for a in np.linspace(0.2, math.pi - 0.2, 10)] + \
        [(0.0, PEARL_R)]
    for sg in (-1.0, 1.0):
        pe = kit.obj(f"Pearl{int(sg)}", K.lathe_uv(pprof, segments=20), m_pearl, nA, outline=0.6, density=2.5,
                     loc=(0.0, sg * PEARL_Y, 0.0), rot=(-sg * math.pi / 2, 0, 0))
        kit.apply_transform(pe)
        kit.set_attr(pe.data, "dens", np.full(len(pe.data.polygons), 2.5), "FACE")
        pe.data.uv_layers.new(name="BakeUV")
        kit.smart_unwrap_meters(pe)
        pe["inspect_uv"] = "premade"
    # 金托：火珠和轴头之间一圈小托（不在重复单元里，同样单独展）
    for sg in (-1.0, 1.0):
        seat = kit.obj(f"Seat{int(sg)}", K.torus_build(0.0054, 0.0010, seg=24, ring=6), m_wheel, nA, outline=0.0, density=2.0,
                       loc=(0.0, sg * 0.0286, 0.0), rot=(math.pi / 2, 0, 0))
        kit.apply_transform(seat)
        kit.set_attr(seat.data, "dens", np.full(len(seat.data.polygons), 2.0), "FACE")
        seat.data.uv_layers.new(name="UVMap")
        seat.data.uv_layers.new(name="BakeUV")
        kit.smart_unwrap_meters(seat)
        seat["inspect_uv"] = "premade"
    # ---- 火（车床坐标里建，再转到轮轴 Y）
    rng = np.random.default_rng(23)
    m_core = mat_flame("wind_wheel_m_flame_core", 0, 2.6)
    m_fl = mat_flame("wind_wheel_m_flame", 1, 2.2)
    layers = []  # (build, 根点, 中心线, 材质, 层)
    for i in range(16):  # 里层：贴着轮缘的短火（不透明）
        phi = 2 * math.pi * i / 16 + rng.uniform(-0.06, 0.06)
        layers.append(_flame_tongue(phi, 0.1478, (0.0040 if i % 2 else -0.0040) + rng.uniform(-0.001, 0.001),
                                    rng.uniform(0.020, 0.030), 0.0078, sweep=0.55, wig=0.25, curl=0.3, flat=0.55, n=9)
                      + (m_core, 0))
    for i in range(11):  # 外层主火舌：宽根、S 形、尖上回钩
        phi = 2 * math.pi * (i + 0.37) / 11 + rng.uniform(-0.08, 0.08)
        layers.append(_flame_tongue(phi, 0.1474, rng.uniform(-0.0025, 0.0025), rng.uniform(0.066, 0.094), 0.0150,
                                    sweep=rng.uniform(0.55, 0.80), wig=rng.uniform(0.30, 0.50), curl=rng.uniform(0.45, 0.65),
                                    zlean=rng.uniform(-0.06, 0.06), flat=0.50) + (m_fl, 1))
    for i in range(8):  # 外层第二排：前后错开，给火一点厚度
        sg = 1.0 if i % 2 == 0 else -1.0
        phi = 2 * math.pi * (i + 0.85) / 8 + rng.uniform(-0.1, 0.1)
        layers.append(_flame_tongue(phi, 0.1468, sg * 0.0060, rng.uniform(0.045, 0.062), 0.0115, sweep=rng.uniform(0.5, 0.7),
                                    wig=0.35, curl=0.5, zlean=sg * 0.16, flat=0.50, n=11) + (m_fl, 1))
    for i in range(10):  # 舔过正反两面的火
        sg = 1.0 if i % 2 == 0 else -1.0
        phi = 2 * math.pi * (i // 2 + 0.15 + 0.5 * (i % 2)) / 5 + rng.uniform(-0.1, 0.1)
        layers.append(_flame_tongue(phi, 0.1385, sg * (WW_T + 0.0004), rng.uniform(0.032, 0.042), 0.0068, sweep=0.6, wig=0.3,
                                    curl=0.35, zlean=sg * 0.40, out=0.85, flat=0.5, n=9) + (m_fl, 2))
    for i in range(8):  # 飞出去的火星
        phi = rng.uniform(0, 2 * math.pi)
        layers.append(_flame_tongue(phi, rng.uniform(0.212, 0.236), rng.uniform(-0.012, 0.012), rng.uniform(0.012, 0.018),
                                    0.0034, sweep=0.5, wig=0.1, flat=0.6, n=6, sides=5) + (m_fl, 3))
    fparts = []
    rects = {0: (0.0, 0.0), 1: (0.0, 0.25), 2: (0.0, 0.5), 3: (0.0, 0.75)}
    for k, (build, base, pts, mat, layer) in enumerate(layers):
        ob = kit.obj(f"Flame{k}", build, mat, nAf, outline=0.0)
        me_ = ob.data
        L = sum(math.dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1))
        uv = np.zeros(len(me_.loops) * 2, np.float32)
        me_.uv_layers["UVMap"].data.foreach_get("uv", uv)
        uv = uv.reshape(-1, 2)
        uv[:, 0] = np.clip(uv[:, 0] / L, 0, 1)
        me_.uv_layers["UVMap"].data.foreach_set("uv", uv.ravel())
        bu = me_.uv_layers.new(name="BakeUV")
        rx, ry = rects[layer]
        b = uv.copy()
        b[:, 0] = rx + 0.004 + b[:, 0] * 0.992
        b[:, 1] = ry + 0.008 + b[:, 1] * 0.234
        bu.data.foreach_set("uv", b.ravel())
        ob["inspect_uv"] = "premade"
        nv = len(me_.vertices)
        bw = np.tile(np.asarray(base, np.float32), (nv, 1))
        at = me_.attributes.new("k_base", "FLOAT_VECTOR", "POINT")
        at.data.foreach_set("vector", bw.ravel())
        kit.set_attr(me_, "k_ca", np.full(nv, rng.uniform(-1, 1)), "POINT")
        fparts.append(ob)
    for ob in fparts:
        ob.data.transform(Matrix.Rotation(math.pi / 2, 4, "X") @ ob.matrix_basis)
        ob.matrix_basis.identity()
        bvec = np.zeros(len(ob.data.vertices) * 3, np.float32)
        ob.data.attributes["k_base"].data.foreach_get("vector", bvec)
        bvec = bvec.reshape(-1, 3)
        bvec = np.stack([bvec[:, 0], -bvec[:, 2], bvec[:, 1]], -1)
        ob.data.attributes["k_base"].data.foreach_set("vector", bvec.ravel())
    # ---- 红绸：系住两只轮子的轴头（前轮的后轴头、后轮的前轴头），结打在前轮上，两条燕尾飘带往左下飘
    gold_img, weave_img = (kit.np_image("wind_wheel_ribbon_gold", a) for a in ribbon_pattern())
    m_rib = mat_brocade("wind_wheel_m_ribbon", gold_img, weave_img)
    MA = Matrix.Translation(WW_A[0]) @ _euler_matrix(WW_A[1]).to_4x4()
    MB = Matrix.Translation(WW_B[0]) @ _euler_matrix(WW_B[1]).to_4x4()
    pa = MA @ Vector((0, 0.0256, 0))
    pb = MB @ Vector((0, -0.0256, 0))
    aA = (MA.to_3x3() @ Vector((0, 1, 0))).normalized()
    aB = (MB.to_3x3() @ Vector((0, 1, 0))).normalized()
    ax = (aA + aB).normalized()
    d = pb - pa
    e1 = (d - ax * d.dot(ax)).normalized()
    e2 = ax.cross(e1)
    D = d.dot(e1)
    hz = d.dot(ax)
    ra = 0.0057 + 0.0005
    loop = []
    for x in np.linspace(0, D, 22):  # 上面那条
        loop.append((x, ra))
    for a in np.linspace(math.pi / 2, -math.pi / 2, 10)[1:]:
        loop.append((D + ra * math.cos(a), ra * math.sin(a)))
    for x in np.linspace(D, 0, 22)[1:]:
        loop.append((x, -ra))
    for a in np.linspace(-math.pi / 2, -3 * math.pi / 2, 10)[1:]:
        loop.append((ra * math.cos(a), ra * math.sin(a)))
    belt = [tuple(pa + e1 * x + e2 * y + ax * (hz * min(max(x / D, 0.0), 1.0))) for x, y in loop]
    kit.obj("Belt", kit.slab_strip(belt, [tuple(ax)] * len(belt), lambda t: 0.0070, 0.0007, segs_w=3), m_rib, nR,
            outline=0.4, density=0.8)
    knot = pa + e2 * (ra + 0.0030)
    kn = kit.obj("RibbonKnot", kit.torus_knot(2, 3, R=0.0034, r=0.0016, tube=0.0014, n=84, sides=6), m_rib, nR,
                 outline=0.6, loc=tuple(knot))
    kn.rotation_euler = ax.to_track_quat("Z", "Y").to_euler()
    kit.tube_bake_uv(kn, 0.0014)
    tails = [[(0, 0, 0), (-0.004, 0.006, -0.012), (-0.020, 0.018, -0.050), (-0.050, 0.030, -0.100), (-0.086, 0.034, -0.150),
              (-0.112, 0.012, -0.196), (-0.128, -0.022, -0.236)],
             [(0, 0, 0), (0.004, 0.009, -0.010), (0.006, 0.024, -0.046), (-0.014, 0.038, -0.094), (-0.040, 0.044, -0.140),
              (-0.060, 0.026, -0.176), (-0.070, -0.004, -0.204)]]
    for ti, (ctrl, wdt, tw) in enumerate(zip(tails, (0.0215, 0.0185), (1.2, -0.9))):
        pts = K.catmull([tuple(knot + Vector(c)) for c in ctrl], n=52)
        P, T, N, Bn = K.frames_along([tuple(p) for p in pts])
        ups = []
        for i in range(len(P)):
            s = i / (len(P) - 1)
            xw = Vector((1.0, 0.0, 0.0))
            base_up = (xw - T[i] * xw.dot(T[i])).normalized()  # 宽面朝镜头（-Y）
            ups.append(tuple(Matrix.Rotation(tw * s ** 1.2 + 0.3 * math.sin(4 * s), 3, T[i]) @ base_up))
        tail = kit.obj(f"Tail{ti}", kit.slab_strip([tuple(p) for p in pts], ups, lambda t, w=wdt: w * (0.75 + 0.25 * min(1, t * 6)),
                                                    0.0006, segs_w=3, end_jag=lambda s, w=wdt: 0.9 * w * (1 - abs(2 * s - 1))),
                       m_rib, nR, outline=0.4, density=1.2)
        tme = tail.data
        co = np.zeros(len(tme.vertices) * 3)
        tme.vertices.foreach_get("co", co)
        co = co.reshape(-1, 3)
        dist = np.linalg.norm(co - np.asarray(knot), axis=1)
        kit.set_attr(tme, "k_s", np.clip(dist / 0.24, 0, 1), "POINT")
    return {
        "id": "wind_wheel",
        "atlases": {
            "body": {"size": 1024, "nodes": [nA, nR], "ao_dist": 0.02, "channels": ["base", "normal", "mr"], "split_len": 0.16,
                     "out": {"mr": 512},
                     "bake_hide": {nA: ["wind_wheel_b", nR, nAf, "wind_wheel_b_flame"], nR: [nAf, "wind_wheel_b_flame"]}},
            "flame": {"size": 512, "nodes": [nAf], "ao": False, "pack": False, "channels": ["base", "alpha", "emit"],
                      "bake_hide": {nAf: [nA, "wind_wheel_b", nR, "wind_wheel_b_flame"]},
                      "materials": {"wind_wheel_flame_core": {"from": ["wind_wheel_m_flame_core"]},
                                    "wind_wheel_flame": {"blend": True, "from": ["wind_wheel_m_flame"]}}},
        },
        "nodes": {nA: {"uv": "premade", "place": (WW_A[0], WW_A[1], "YXZ")},
                  nAf: {"uv": "premade", "parent": nA, "keys": "flame"},
                  nR: {"keys": "ribbon"}},
        "instances": {"wind_wheel_b": (nA, WW_B[0], WW_B[1], "YXZ"),
                      "wind_wheel_b_flame": (nAf, (0.0, 0.0, 0.0), (0.0, 0.0, 0.0), "XYZ")},
        "instance_parent": {"wind_wheel_b_flame": "wind_wheel_b"},
        "keys": {"flame": flame_keys(), "ribbon": ribbon_keys()},
        "anim": {"frames": 192, "fps": 24,
                 "spin": {nA: (1, -1), "wind_wheel_b": (1, -1)},
                 "weights": {nAf: [("flicker", 1.0, 11, 0.0)],
                             nR: [("sway_a", 1.0, 2, 0.0), ("sway_b", 1.0, 2, math.pi / 2)]}},
        "outline_width": 0.0030,
        "outline_ratio": 0.3,
    }


def flame_keys():
    """火舌一伸一缩：每条火舌按自己的系数 k_ca（-1..1，有的伸有的缩），沿自己从根到这一点的方向拉长或缩短。"""

    def make(attr_name):
        def f(co, attr):
            base = attr("k_base")
            c = attr(attr_name)
            if base is None or c is None:
                return np.zeros_like(co)
            return (co - base) * (0.16 * c)[:, None]

        return f

    return {"flicker": make("k_ca")}


def ribbon_keys():
    """飘带两条尾巴的波（两个相位的 sin、cos，动画里组合成往后走的波）；越往尾巴尖摆得越大，结和系带不动。"""

    def make(phase):
        def f(co, attr):
            s = attr("k_s")
            if s is None:
                return np.zeros_like(co)
            a = 0.016 * s ** 1.6
            w = np.sin(7.0 * s + phase)
            out = np.zeros_like(co)
            out[:, 0] = a * w
            out[:, 1] = 0.6 * a * np.cos(7.0 * s + phase)
            out[:, 2] = 0.25 * a * w
            return out

        return f

    return {"sway_a": make(0.0), "sway_b": make(math.pi / 2)}
