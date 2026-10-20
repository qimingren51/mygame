"""神话特效分镜的 1080p 游戏画面合成（只读图集，不写 assets）。

和 vfx_frames_review.ingame / moon_textures.render 同一套摆法，多了分镜要的几样：
  - 镜头：中心、缩放（推近 / 拉远）、震屏偏移；
  - 光照图里可以加别的光（聚光、剑河、佛光），也可以整体提亮（燃灯“暗层提亮到八成”）；
  - 任意旋转、缩放的贴图（剑影、尾巴）和拖尾笔画；
  - 辉光（照 view/lib.rs 的 Bloom：阈值 1.0、软膝 0.25、叠加）和暗角（atmos.rs base_vignette）。

合成顺序（线性光）：
  地面（宣纸 + 装饰 + 影子）→ ground 钩子（贴地的普通混合：冰海、鲲影、墨）→ 角色（按脚底 y 排序）
  → over 钩子（空中的普通混合）→ × 光照图（月夜底色 + 灯笼光照池 + light 钩子）
  → 自发光（妖眼、灯笼窗，× 1.5）→ add 钩子（叠加特效，× 1.5）→ sky 钩子（镜头上的月亮、剪影）→ 辉光 → 暗角。
"""

from __future__ import annotations

import math
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

os.environ.setdefault("LANTERN_ART_DENSITY", "2")
sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402

import moon_textures as M  # noqa: E402

V, S = M.V, M.S
SW, SH = M.SW, M.SH
K = M.K  # 2.571 像素 / 世界单位（1080p）
PPU = M.PPU  # 图集 4 像素 / 世界单位
EMIT = 1.5  # 叠加层 × 1.5（lighting.rs EMIT_HDR）
NIGHT = S.NIGHT_AMBIENT  # #46557F
lin, to_lin, to_srgb = M.lin, M.to_lin, M.to_srgb


# ============================================================== 镜头


@dataclass
class Cam:
    cx: float = 0.0  # 镜头中心（世界坐标）
    cy: float = 0.0
    z: float = 1.0  # 缩放：1.06 推近 6%，0.9 拉远
    shake: tuple[float, float] = (0.0, 0.0)  # 震屏（画面像素）

    @property
    def k(self) -> float:
        return K * self.z

    def s(self, x: float, y: float, h: float = 0.0) -> tuple[float, float]:
        """世界坐标 → 画面像素；h 是离地高度（世界单位，往上抬）。"""
        return (SW / 2 + (x - self.cx) * self.k + self.shake[0], SH / 2 + (y - self.cy - h) * self.k + self.shake[1])

    @property
    def sprite(self) -> float:
        """图集像素 → 画面像素。"""
        return self.k / PPU


# ============================================================== 贴图与混合


def frame(atlas: str, key: str):
    return M.atlas_frame(atlas, key)


_PM: dict = {}


def pm_of(img: Image.Image, tint=None) -> np.ndarray:
    """直通 alpha 的 sRGB 贴图 → 线性、预乘的 float32（同一张图只算一次）。"""
    k = (id(img), None if tint is None else tuple(np.round(np.asarray(tint, dtype=np.float64), 5)))
    if k not in _PM:
        _PM[k] = (M.premul(img, tint=tint), img)  # 留着 img 的引用，id 不会被复用
    return _PM[k][0]


def blit(canvas, img_or_pm, x, y, anchor, scale, *, angle=0.0, sx=1.0, sy=1.0, mode="over", gain=1.0, tint=None, alpha=1.0, flip=False):
    """把贴图画到画布上：锚点放在 (x, y)（画面像素），scale = 画面像素 / 贴图像素，angle 顺时针（弧度，画面 y 向下）。
    sx、sy 是贴图自身两个轴的额外拉伸（转之前）。双线性采样。over：预乘 alpha 正常混合；add：叠加（× gain）。"""
    pm = img_or_pm if isinstance(img_or_pm, np.ndarray) else pm_of(img_or_pm, tint)
    if alpha != 1.0:
        pm = pm * alpha
    h, w = pm.shape[:2]
    ax, ay = anchor[0] * w, anchor[1] * h
    kx, ky = scale * sx, scale * sy
    ca, sa = math.cos(angle), math.sin(angle)
    # 贴图四角在画面上的位置 → 包围盒
    corners = []
    for u, v in ((0, 0), (w, 0), (0, h), (w, h)):
        dx, dy = (u - ax) * kx, (v - ay) * ky
        corners.append((x + dx * ca - dy * sa, y + dx * sa + dy * ca))
    xs, ys = [c[0] for c in corners], [c[1] for c in corners]
    ix0, ix1 = max(int(math.floor(min(xs))), 0), min(int(math.ceil(max(xs))) + 1, canvas.shape[1])
    iy0, iy1 = max(int(math.floor(min(ys))), 0), min(int(math.ceil(max(ys))) + 1, canvas.shape[0])
    if ix0 >= ix1 or iy0 >= iy1:
        return
    px = np.arange(ix0, ix1) + 0.5 - x
    py = np.arange(iy0, iy1) + 0.5 - y
    PX, PY = np.meshgrid(px, py)
    # 逆变换：画面 → 贴图
    u = (PX * ca + PY * sa) / kx + ax - 0.5
    v = (-PX * sa + PY * ca) / ky + ay - 0.5
    if flip:
        u = (w - 1) - u
    inside = (u > -1) & (u < w) & (v > -1) & (v < h)
    if not inside.any():
        return
    pmp = np.pad(pm, ((1, 1), (1, 1), (0, 0)))
    uu, vv = np.clip(u + 1, 0, w + 0.999), np.clip(v + 1, 0, h + 0.999)
    j0, i0 = np.floor(uu).astype(np.int32), np.floor(vv).astype(np.int32)
    j1, i1 = np.minimum(j0 + 1, w + 1), np.minimum(i0 + 1, h + 1)
    fu, fv = (uu - j0)[..., None], (vv - i0)[..., None]
    s = (pmp[i0, j0] * (1 - fu) + pmp[i0, j1] * fu) * (1 - fv) + (pmp[i1, j0] * (1 - fu) + pmp[i1, j1] * fu) * fv
    s *= inside[..., None]
    reg = canvas[iy0:iy1, ix0:ix1]
    if mode == "add":
        reg += s[..., :3] * gain
    elif mode == "mul":  # 光照图里压暗用
        reg *= 1.0 - s[..., 3:4] + s[..., :3]
    else:
        reg[:] = s[..., :3] * gain + reg * (1.0 - s[..., 3:4])


def stroke(canvas, pts, width, color, *, mode="add", gain=1.0, alpha=None, soft=1.0):
    """沿画面坐标的折线画一笔（拖尾、光丝）：width、alpha 可以是每个点一个值。add 叠加颜色 × alpha × gain；over 是正常混合。"""
    pts = np.asarray(pts, dtype=np.float64)
    n = len(pts)
    if n < 2:
        return
    wid = np.broadcast_to(np.asarray(width, dtype=np.float64), (n,))
    al = np.ones(n) if alpha is None else np.broadcast_to(np.asarray(alpha, dtype=np.float64), (n,))
    pad = wid.max() + 2 * soft + 1
    x0, x1 = max(int(pts[:, 0].min() - pad), 0), min(int(pts[:, 0].max() + pad) + 1, canvas.shape[1])
    y0, y1 = max(int(pts[:, 1].min() - pad), 0), min(int(pts[:, 1].max() + pad) + 1, canvas.shape[0])
    if x0 >= x1 or y0 >= y1:
        return
    X, Y = np.meshgrid(np.arange(x0, x1) + 0.5, np.arange(y0, y1) + 0.5)
    best = np.full(X.shape, 1e9)
    bw = np.zeros(X.shape)
    ba = np.zeros(X.shape)
    for i in range(n - 1):
        ax_, ay_ = pts[i]
        dx, dy = pts[i + 1] - pts[i]
        L2 = max(dx * dx + dy * dy, 1e-9)
        t = np.clip(((X - ax_) * dx + (Y - ay_) * dy) / L2, 0, 1)
        d = np.hypot(X - ax_ - t * dx, Y - ay_ - t * dy)
        w_ = wid[i] + (wid[i + 1] - wid[i]) * t
        a_ = al[i] + (al[i + 1] - al[i]) * t
        # 取“覆盖度最大”的一段，接缝处不重复叠
        cov = np.clip((w_ * 0.5 + soft - d) / (2 * soft), 0, 1)
        better = cov * a_ > ba * np.clip((bw * 0.5 + soft - best) / (2 * soft), 0, 1)
        best = np.where(better, d, best)
        bw = np.where(better, w_, bw)
        ba = np.where(better, a_, ba)
    cov = np.clip((bw * 0.5 + soft - best) / (2 * soft), 0, 1)
    cov = cov * cov * (3 - 2 * cov) * ba
    reg = canvas[y0:y1, x0:x1]
    col = np.asarray(color, dtype=np.float32)
    if mode == "add":
        reg += (cov[..., None] * col * gain).astype(np.float32)
    else:
        reg[:] = reg * (1 - cov[..., None]) + col * cov[..., None]


def glow(canvas, x, y, r, color, gain=1.0, power=2.0):
    """一团柔光（画面像素半径 r）：(1 − d/r)^power，叠加。光照图里加光、画面里补光芯都用它。"""
    x0, x1 = max(int(x - r), 0), min(int(x + r) + 1, canvas.shape[1])
    y0, y1 = max(int(y - r), 0), min(int(y + r) + 1, canvas.shape[0])
    if x0 >= x1 or y0 >= y1:
        return
    X, Y = np.meshgrid(np.arange(x0, x1) + 0.5, np.arange(y0, y1) + 0.5)
    d = np.clip(1 - np.hypot(X - x, Y - y) / r, 0, 1) ** power
    canvas[y0:y1, x0:x1] += (d[..., None] * np.asarray(color, dtype=np.float32) * gain).astype(np.float32)


def glow_ellipse(canvas, x, y, rx, ry, color, gain=1.0, power=2.0):
    x0, x1 = max(int(x - rx), 0), min(int(x + rx) + 1, canvas.shape[1])
    y0, y1 = max(int(y - ry), 0), min(int(y + ry) + 1, canvas.shape[0])
    if x0 >= x1 or y0 >= y1:
        return
    X, Y = np.meshgrid(np.arange(x0, x1) + 0.5, np.arange(y0, y1) + 0.5)
    d = np.clip(1 - np.hypot((X - x) / rx, (Y - y) / ry), 0, 1) ** power
    canvas[y0:y1, x0:x1] += (d[..., None] * np.asarray(color, dtype=np.float32) * gain).astype(np.float32)


# ============================================================== 场景


HERO = (0.0, 12.0)
# 一屏的妖物：(帧, x, y)。灯边、灯下几只，月下一圈；主角周围留出地方给特效
HORDE = [
    ("shade/float_E_00", 68.0, -84.0),
    ("shade/float_E_03", 132.0, 74.0),
    ("shade/float_E_05", -162.0, -98.0),
    ("golem/move_E_00", -236.0, 62.0),
    ("fox/move_E_02", 248.0, 128.0),
    ("shade/float_E_06", 292.0, -128.0),
    ("wisp/float_E_02", -324.0, -44.0),
    ("ghoul/move_E_03", -118.0, 156.0),
    ("fox_wisp/float_E_01", 198.0, -36.0),
    ("shade/float_E_01", -54.0, -160.0),
    ("fox/move_E_05", 338.0, 22.0),
    ("bamboo_wraith/move_E_01", -330.0, 150.0),
    ("shade/float_E_04", 40.0, 168.0),
    ("wisp/float_E_04", 150.0, -170.0),
    ("taofeng_fox/move_E_02", -250.0, -170.0),
]


def ambient_lin(hexcol: str = NIGHT) -> np.ndarray:
    return lin(hexcol).astype(np.float32)


@dataclass
class Actor:
    key: str  # 图集帧名，如 shade/float_E_00
    x: float
    y: float
    atlas: str = "actors"
    flip: bool | None = None  # None：在主角右边的朝左
    alpha: float = 1.0
    emit: bool = True
    scale: float = 1.0
    lift: float = 0.0  # 离地（世界单位）
    shadow: bool = True
    hook: object = None  # hook(pm, emit_pm) → (pm, emit_pm)：化灰、冻住之类改贴图


@dataclass
class Shot:
    cam: Cam = field(default_factory=Cam)
    actors: list = field(default_factory=list)
    ambient: str = NIGHT
    pool: float = 1.0  # 灯笼光照池的强度
    lift_dark: float = 0.0  # 暗层整体提亮到这个亮度（0 不提；燃灯 0.8）
    lift_tint: str = "#FFF1D6"
    bloom: float = 0.16  # 辉光强度（atmos.rs BLOOM_BASE；高光时最多约 0.61）
    vignette: float = 0.28
    decor: bool = True
    ground: list = field(default_factory=list)  # 钩子 f(canvas, cam)
    over: list = field(default_factory=list)
    light: list = field(default_factory=list)  # f(lightmap_half, cam)：光照图是半分辨率，画面坐标要 / 2
    add: list = field(default_factory=list)
    sky: list = field(default_factory=list)
    post: list = field(default_factory=list)  # 辉光之前、整张画面上
    desat: float = 0.0  # 顿帧时整体去色（0..1）


def default_actors(hero: bool = True, horde=HORDE) -> list[Actor]:
    out = [Actor(k, x, y) for k, x, y in horde]
    if hero:
        out.append(Actor("hero/idle_S_00", *HERO, flip=False))
    return out


def _actor_sprites(a: Actor):
    im, anc = frame(a.atlas, a.key)
    emit = None
    if a.emit:
        try:
            emit = frame(a.atlas, a.key + "_emit")[0]
        except KeyError:
            emit = None
    return im, anc, emit


def render(shot: Shot) -> np.ndarray:
    """合成一帧，返回线性光的 float32 画面（辉光、暗角都已加上）。"""
    cam = shot.cam
    sc = cam.sprite
    paper = np.asarray(Image.open(M.ATLAS / "paper.png").convert("RGB"))
    img = paper_layer(paper, cam)
    shadow, s_anc = frame("vfx", "vfx/shadow")
    spm = pm_of(shadow)
    # 地面装饰（平铺，同 moon_textures 的摆法）
    if shot.decor:
        for name, x, y, al, flip in M.flat_layout():
            im, anc = frame("ground", f"ground/{name}")
            blit(img, pm_of(im) * al, *cam.s(x, y), anc, sc, flip=flip)
        for at, f, x, y in M.UPRIGHT:
            im, _ = frame(at, f)
            foot = min(max(im.width / PPU * 0.3, 5.0), 24.0)
            blit(img, spm * 0.55, *cam.s(x, y), s_anc, 2 * foot * cam.k / shadow.width)
    # 影子
    for a in shot.actors:
        if not a.shadow:
            continue
        asset = a.key.split("/")[0]
        try:
            m = M.asset_meta(asset)
        except KeyError:
            m = {}
        r_px = m.get("shadow_radius_px", 24) * a.scale
        al = (0.42 if m.get("floating") else 0.62) if asset != "hero" else 0.8
        blit(img, spm * al * a.alpha, *cam.s(a.x, a.y), s_anc, sc * (2 * r_px) / shadow.width)
    for f in shot.ground:
        f(img, cam)
    # 立着的东西和角色，按脚底 y 排序
    items = []
    if shot.decor:
        items += [(y, "up", (at, f, x, y)) for at, f, x, y in M.UPRIGHT]
    items += [(a.y, "actor", a) for a in shot.actors]
    emits = []
    for _, kind, it in sorted(items, key=lambda t: t[0]):
        if kind == "up":
            at, f, x, y = it
            im, anc = frame(at, f)
            blit(img, im, *cam.s(x, y), anc, sc)
            continue
        a = it
        im, anc, em = _actor_sprites(a)
        flip = (a.x > HERO[0]) if a.flip is None else a.flip
        pm, epm = pm_of(im), (pm_of(em) if em is not None else None)
        if a.hook is not None:
            pm, epm = a.hook(pm, epm)
        pos = cam.s(a.x, a.y, a.lift)
        blit(img, pm * a.alpha, *pos, anc, sc * a.scale, flip=flip)
        if a.key.startswith("hero/"):
            lim, lanc = frame("lanterns", "lantern_red/" + a.key.split("/")[1])
            blit(img, lim, *pos, lanc, sc * a.scale)
            lem = frame("lanterns", "lantern_red/" + a.key.split("/")[1] + "_emit")[0]
            emits.append((pm_of(lem), pos, lanc, sc * a.scale, False, a.alpha))
        if epm is not None:
            emits.append((epm, pos, anc, sc * a.scale, flip, a.alpha))
    for f in shot.over:
        f(img, cam)
    # 光照图：半分辨率，月夜底色 + 灯笼光照池 + 钩子里的光
    lm = np.broadcast_to(ambient_lin(shot.ambient), (SH // 2, SW // 2, 3)).copy()
    hero = next((a for a in shot.actors if a.key.startswith("hero/")), None)
    if hero is not None and shot.pool > 0:
        sx, sy = M.asset_meta("hero")["sockets"]["lantern"]["idle"]["S"][0]
        lx, ly = cam.s(hero.x + sx / PPU, hero.y + sy / PPU)
        pool, _ = frame("vfx", "vfx/light_pool")
        blit(lm, pm_of(pool, tint=lin(M.TINT_NOW)) * shot.pool, lx / 2, ly / 2, (0.5, 0.5), (2 * M.LIGHT_R * cam.k / 2) / pool.width, mode="add")
    for f in shot.light:
        f(lm, cam)
    if shot.lift_dark > 0:
        tgt = lin(shot.lift_tint).astype(np.float32) * shot.lift_dark
        lm = np.maximum(lm, tgt)
    lm_full = upsample2(lm)
    img *= lm_full
    # 自发光（妖眼、灯笼窗）
    for epm, pos, anc, scl, flip, al in emits:
        blit(img, epm * al, *pos, anc, scl, flip=flip, mode="add", gain=EMIT)
    lx, ly = (0, 0)
    if hero is not None:
        sx, sy = M.asset_meta("hero")["sockets"]["lantern"]["idle"]["S"][0]
        lx, ly = cam.s(hero.x + sx / PPU, hero.y + sy / PPU)
        old_light, _ = frame("vfx", "vfx/light")
        blit(img, pm_of(old_light, tint=lin("#FFC773")) * 0.22, lx, ly, (0.5, 0.5), (2 * 14.0 * cam.k) / old_light.width, mode="add", gain=EMIT)
    for f in shot.add:
        f(img, cam)
    for f in shot.sky:
        f(img, cam)
    for f in shot.post:
        f(img, cam)
    if shot.desat > 0:
        lum = (img * np.array([0.2126, 0.7152, 0.0722], np.float32)).sum(-1, keepdims=True)
        img = img * (1 - shot.desat) + lum * shot.desat
    if shot.bloom > 0:
        img = img + bloom(img, shot.bloom)
    if shot.vignette > 0:
        img = vignette(img, shot.vignette)
    return img


def paper_layer(paper: np.ndarray, cam: Cam) -> np.ndarray:
    """平铺的宣纸（双线性、环绕），1 纹素 = 0.25 世界单位，跟着镜头走、缩放。"""
    tex = to_lin(paper.astype(np.float64) / 255.0).astype(np.float32)
    n = tex.shape[0]
    tx = ((np.arange(SW) + 0.5 - SW / 2 - cam.shake[0]) / cam.k + cam.cx) * PPU + M.PAPER_ORIGIN[0] - 0.5
    ty = ((np.arange(SH) + 0.5 - SH / 2 - cam.shake[1]) / cam.k + cam.cy) * PPU + M.PAPER_ORIGIN[1] - 0.5
    j0, i0 = np.floor(tx).astype(int), np.floor(ty).astype(int)
    fu, fv = (tx - j0)[None, :, None], (ty - i0)[:, None, None]
    j0, j1, i0, i1 = j0 % n, (j0 + 1) % n, i0 % n, (i0 + 1) % n
    A, B = tex[i0], tex[i1]
    return ((A[:, j0] * (1 - fu) + A[:, j1] * fu) * (1 - fv) + (B[:, j0] * (1 - fu) + B[:, j1] * fu) * fv).astype(np.float32)


def upsample2(lm: np.ndarray) -> np.ndarray:
    """半分辨率的光照图 → 全分辨率（双线性，同 moon_textures）。"""
    h, w = lm.shape[:2]
    gx = np.clip((np.arange(SW) + 0.5) / 2 - 0.5, 0, w - 1)
    gy = np.clip((np.arange(SH) + 0.5) / 2 - 0.5, 0, h - 1)
    j0, i0 = np.floor(gx).astype(int), np.floor(gy).astype(int)
    j1, i1 = np.minimum(j0 + 1, w - 1), np.minimum(i0 + 1, h - 1)
    fu, fv = (gx - j0)[None, :, None], (gy - i0)[:, None, None]
    return ((lm[i0][:, j0] * (1 - fu) + lm[i0][:, j1] * fu) * (1 - fv) + (lm[i1][:, j0] * (1 - fu) + lm[i1][:, j1] * fu) * fv).astype(np.float32)


# ============================================================== 后期：辉光、暗角


def _down2(a):
    h, w = a.shape[0] // 2 * 2, a.shape[1] // 2 * 2
    a = a[:h, :w]
    return 0.25 * (a[0::2, 0::2] + a[1::2, 0::2] + a[0::2, 1::2] + a[1::2, 1::2])


def _blur(a, r: int = 2):
    """小核的可分离高斯（σ ≈ r / 2），边缘夹住。"""
    xs = np.arange(-r, r + 1)
    k = np.exp(-0.5 * (xs / max(r / 2.0, 0.5)) ** 2)
    k /= k.sum()
    p = np.pad(a, ((r, r), (0, 0), (0, 0)), mode="edge")
    a = sum(k[i] * p[i : i + a.shape[0]] for i in range(2 * r + 1))
    p = np.pad(a, ((0, 0), (r, r), (0, 0)), mode="edge")
    return sum(k[i] * p[:, i : i + a.shape[1]] for i in range(2 * r + 1))


def _up_to(a, shape):
    im = [np.asarray(Image.fromarray(a[..., c].astype(np.float32), "F").resize((shape[1], shape[0]), Image.BILINEAR)) for c in range(a.shape[2])]
    return np.stack(im, -1)


def bloom(img: np.ndarray, intensity: float, threshold: float = 1.0, softness: float = 0.25) -> np.ndarray:
    """近似 Bevy 的辉光：软阈值（亮度 = 最大分量）取出亮部，降采样金字塔上逐级模糊，低频略加强，叠加回去。"""
    br = img.max(-1, keepdims=True)
    knee = threshold * softness
    soft = np.clip(br - threshold + knee, 0, 2 * knee) ** 2 / (4 * knee + 1e-5)
    contrib = np.maximum(br - threshold, soft) / np.maximum(br, 1e-5)
    bright = img * contrib
    levels = []
    cur = bright
    for _ in range(7):
        cur = _blur(_down2(cur), 2)
        levels.append(cur)
    acc = levels[-1]
    for i in range(len(levels) - 2, -1, -1):
        lf = 1.0 + 0.5 * (i / (len(levels) - 1)) ** 0.9  # 低频略加强（low_frequency_boost 0.5）
        acc = _up_to(acc, levels[i].shape) + levels[i] * lf
    acc = _up_to(acc, img.shape)
    return (acc * (intensity * 0.8)).astype(np.float32)


def vignette(img: np.ndarray, intensity: float, radius: float = 0.95, color=(0.02, 0.025, 0.05)) -> np.ndarray:
    y, x = np.mgrid[0:SH, 0:SW].astype(np.float32)
    u, v = (x + 0.5) / SW - 0.5, (y + 0.5) / SH - 0.5
    d = np.sqrt((u * (SW / SH)) ** 2 + v * v) / math.hypot(0.5 * SW / SH, 0.5)  # 角上 = 1
    f = intensity * np.clip((d - (radius - 0.6)) / 0.6, 0, 1) ** 1.6
    c = to_lin(np.asarray(color)).astype(np.float32)
    return img * (1 - f[..., None]) + c * f[..., None]


def to8(img: np.ndarray) -> Image.Image:
    return Image.fromarray(np.round(to_srgb(np.clip(img, 0, 1)) * 255).astype(np.uint8), "RGB")


# ============================================================== 分镜条


def board(panels: list[tuple[Image.Image, str]], title: str, sub: str, path: Path, cols: int = 2) -> None:
    """2×2（或横排）分镜条：每格 960×540（从 1080p 缩下来），格下一行小字。"""
    pw, ph, cap, pad, head = 960, 540, 40, 12, 86
    rows = math.ceil(len(panels) / cols)
    W = cols * pw + (cols + 1) * pad
    H = head + rows * (ph + cap + pad) + pad
    out = Image.new("RGB", (W, H), (22, 22, 26))
    d = ImageDraw.Draw(out)
    d.text((pad + 4, 14), title, fill=(244, 240, 228), font=M.font(28))
    d.text((pad + 4, 52), sub, fill=(190, 186, 172), font=M.font(17))
    for i, (im, text) in enumerate(panels):
        r, c = divmod(i, cols)
        x0 = pad + c * (pw + pad)
        y0 = head + r * (ph + cap + pad)
        out.paste(im.resize((pw, ph), Image.LANCZOS), (x0, y0))
        d.text((x0 + 6, y0 + ph + 8), text, fill=(232, 228, 216), font=M.font(19))
    V.save_png(out, path)
