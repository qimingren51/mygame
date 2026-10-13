"""提灯夜行 · 精灵后期处理（纯 Pillow / numpy，不依赖 bpy）。

输入是 bstyle.render_layers() 得到的三层（渲染分辨率，预乘 alpha 的线性 RGB）：
    fill (H,W,4)  填色
    lines (H,W,4) Freestyle 墨线
    emit (H,W)    发光遮罩（IndexOB == 1）

处理顺序（process_layers）：
  1. 缩小 RENDER_SCALE 倍：预乘 alpha 的盒式平均（纯色区域不会产生新颜色，边缘自然抗锯齿）
  2. 填色软吸附到 full_palette()：离最近调色板色在 PALETTE_TOLERANCE 以内的像素，
     偏差压到 SNAP_KEEP 以内（保留一点点晕染起伏，但不会跑出调色板）；发光部件不吸附
  3. 墨线叠在填色上，带墨晕（INK_BLEED_PX 高斯半径的淡淡外晕）
  4. 纸纹：均值为 1 的正片叠底（PAPER_OVERLAY），每个素材一个固定偏移，同一素材的各帧不闪
  5. 清掉极小的 alpha，往透明区域扩展颜色 ALPHA_BLEED_PX 像素（避免游戏里缩放出黑边/白边）
另外生成：发光层（只含发光部件，夜里叠加用）和受击闪白剪影。

也可以单独调用每个函数，例如 make_flash(rgba)。
"""

from __future__ import annotations

import hashlib
import sys
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

ART = Path(__file__).resolve().parents[1]
if str(ART) not in sys.path:
    sys.path.insert(0, str(ART))
from style import style as S  # noqa: E402

SNAP_KEEP = 3.0  # 吸附后与调色板色的最大残余偏差（8 位 RGB 欧氏距离）
INK_BLEED_GAIN = 0.35  # 墨晕外缘的浓度（相对线条本身）
ALPHA_FLOOR = 3 / 255  # 小于这个 alpha 的像素视为全透明
LIGHT_COLORS = [S.LANTERN_LIGHT, S.FLAME_LIGHT, S.SOUL_LIGHT, *S.EYE.values()]  # 发光色，不吸附也不算“出格”


# ================================================================ 颜色
def hex_rgb(h: str) -> np.ndarray:
    return np.array(S.hex_to_rgb(h), np.float32)


def linear_to_srgb(x: np.ndarray) -> np.ndarray:
    """线性 0..1 → sRGB 0..1。"""
    x = np.clip(x, 0.0, 1.0)
    return np.where(x <= 0.0031308, x * 12.92, 1.055 * np.power(x, 1 / 2.4) - 0.055)


def palette_array(extra: list[str] | tuple[str, ...] = ()) -> np.ndarray:
    cols = list(S.full_palette()) + [c for c in extra if c not in S.full_palette()]
    return np.stack([hex_rgb(c) for c in cols])


def nearest_palette(rgb: np.ndarray, pal: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """rgb (...,3) 0..255 → (最近调色板色 (...,3), 距离 (...))。"""
    flat = rgb.reshape(-1, 3)
    best_d = np.full(flat.shape[0], np.inf, np.float32)
    best_i = np.zeros(flat.shape[0], np.int32)
    for i, p in enumerate(pal):  # 调色板只有几十色，逐色比较比广播省内存
        d = np.sqrt(((flat - p) ** 2).sum(-1))
        m = d < best_d
        best_d[m], best_i[m] = d[m], i
    return pal[best_i].reshape(rgb.shape), best_d.reshape(rgb.shape[:-1])


# ================================================================ 基础滤波
def box_downscale(img: np.ndarray, k: int) -> np.ndarray:
    """(H,W,...) 每 k×k 块取平均。"""
    H, W = img.shape[:2]
    h, w = H // k, W // k
    x = img[: h * k, : w * k]
    return x.reshape(h, k, w, k, *img.shape[2:]).mean(axis=(1, 3))


def gaussian_blur(a: np.ndarray, sigma: float) -> np.ndarray:
    """二维单通道可分离高斯模糊（边缘按 0 填充）。"""
    if sigma <= 0:
        return a.copy()
    r = max(1, int(np.ceil(3 * sigma)))
    xs = np.arange(-r, r + 1, dtype=np.float32)
    k = np.exp(-0.5 * (xs / sigma) ** 2)
    k /= k.sum()
    p = np.pad(a, ((r, r), (0, 0)))
    out = sum(k[i] * p[i: i + a.shape[0]] for i in range(2 * r + 1))
    p = np.pad(out, ((0, 0), (r, r)))
    return sum(k[i] * p[:, i: i + a.shape[1]] for i in range(2 * r + 1))


def unpremultiply(prem: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    a = prem[..., 3]
    rgb = np.where(a[..., None] > 1e-5, prem[..., :3] / np.maximum(a[..., None], 1e-5), 0.0)
    return rgb, a


# ================================================================ 各步骤
def soft_snap(rgb: np.ndarray, mask: np.ndarray, pal: np.ndarray,
              tol: float = S.PALETTE_TOLERANCE, keep: float = SNAP_KEEP) -> np.ndarray:
    """mask 内、离调色板 tol 以内的像素拉向最近的调色板色，残余偏差不超过 keep。"""
    near, d = nearest_palette(rgb, pal)
    sel = mask & (d <= tol)
    k = np.where(d > keep, keep / np.maximum(d, 1e-6), 1.0)[..., None]
    out = rgb.copy()
    out[sel] = (near + (rgb - near) * k)[sel]
    return out


def ink_bleed(line_a: np.ndarray, sigma: float = S.INK_BLEED_PX, gain: float = INK_BLEED_GAIN) -> np.ndarray:
    """墨线外缘加一圈淡淡的晕：a' = 1 - (1-a)(1 - gain·blur(a))。"""
    return 1.0 - (1.0 - line_a) * (1.0 - gain * gaussian_blur(line_a, sigma))


@lru_cache(maxsize=4)
def paper_texture(size: int = 512, seed: int = 20240, density: float = S.DENSITY) -> np.ndarray:
    """按密度放大的纸纹（2 倍密度时纤维也粗一倍，和模型的比例不变）。"""
    base = _paper_texture_1x(size, seed)
    if density == 1:
        return base
    n = int(round(size * density))
    im = Image.fromarray((base * 255).astype(np.uint8)).resize((n, n), Image.BICUBIC)
    return np.asarray(im, np.float32) / 255.0


@lru_cache(maxsize=4)
def _paper_texture_1x(size: int = 512, seed: int = 20240) -> np.ndarray:
    """宣纸纹理（可平铺性不要求，取块时取模），值域约 0..1，均值约 0.8：亮底 + 暗纤维 + 云状起伏。"""
    rng = np.random.default_rng(seed)
    base = np.zeros((size, size), np.float32)
    for cells, amp in ((8, 0.5), (24, 0.3), (96, 0.2)):  # 多尺度值噪声
        n = rng.random((cells, cells)).astype(np.float32)
        im = Image.fromarray((n * 255).astype(np.uint8)).resize((size, size), Image.BICUBIC)
        base += amp * (np.asarray(im, np.float32) / 255.0)
    fib = Image.new("L", (size, size), 0)
    dr = ImageDraw.Draw(fib)
    for _ in range(size * 3):  # 纤维：短的弯线，大多接近水平
        x, y = rng.random(2) * size
        ang = rng.normal(0, 0.6)
        ln = rng.uniform(4, 22)
        pts = [(x, y)]
        for _s in range(3):
            ang += rng.normal(0, 0.25)
            x, y = x + np.cos(ang) * ln / 3, y + np.sin(ang) * ln / 3
            pts.append((x, y))
        dr.line(pts, fill=int(rng.uniform(60, 200)), width=1)
    fib = np.asarray(fib.filter(ImageFilter.GaussianBlur(0.6)), np.float32) / 255.0
    tex = 0.82 + 0.18 * (base - base.mean()) / (base.std() * 3 + 1e-6) - 0.35 * fib
    return np.clip(tex, 0.0, 1.0)


def asset_offset(name: str) -> tuple[int, int]:
    """每个素材固定的纸纹偏移（由名字哈希得到），保证同一素材所有帧纸纹一致、不闪。"""
    h = hashlib.md5(name.encode()).digest()
    n = paper_texture().shape[0]
    return int(h[0] * 2 * S.DENSITY) % n, int(h[1] * 2 * S.DENSITY) % n


def paper_grain(h: int, w: int, name: str, strength: float = S.PAPER_OVERLAY) -> np.ndarray:
    """返回 (h,w) 的乘数，均值为 1：纤维处略暗，其它地方略亮。"""
    tex = paper_texture()
    oy, ox = asset_offset(name)

    def mirror_idx(n, off, size):  # 镜像平铺：大画布也没有接缝
        i = (np.arange(n) + off) % (2 * size)
        return np.where(i >= size, 2 * size - 1 - i, i)

    g = tex[np.ix_(mirror_idx(h, oy, tex.shape[0]), mirror_idx(w, ox, tex.shape[1]))]
    f = 1.0 - strength * (1.0 - g)
    return f / f.mean()


def alpha_bleed(rgb: np.ndarray, a: np.ndarray, px: int = S.ALPHA_BLEED_PX) -> np.ndarray:
    """往全透明像素里扩展 RGB（每圈取已知邻居的平均），alpha 不变。"""
    rgb = rgb.copy()
    known = a > 0
    H, W = a.shape
    for _ in range(px):
        if known.all():
            break
        kp = np.pad(known.astype(np.float32), 1)
        cp = np.pad(rgb * known[..., None], ((1, 1), (1, 1), (0, 0)))
        s = np.zeros_like(rgb)
        n = np.zeros((H, W), np.float32)
        for dy in (0, 1, 2):
            for dx in (0, 1, 2):
                if dy == 1 and dx == 1:
                    continue
                s += cp[dy: dy + H, dx: dx + W]
                n += kp[dy: dy + H, dx: dx + W]
        grow = (~known) & (n > 0)
        rgb[grow] = s[grow] / n[grow][:, None]
        known = known | grow
    return rgb


def make_flash(rgba: np.ndarray) -> np.ndarray:
    """受击闪白：同样的 alpha，RGB 全白。"""
    out = np.empty_like(rgba)
    out[..., :3] = 255
    out[..., 3] = rgba[..., 3]
    return out


def to_rgba8(rgb: np.ndarray, a: np.ndarray) -> np.ndarray:
    return np.concatenate([np.clip(rgb + 0.5, 0, 255), np.clip(a * 255 + 0.5, 0, 255)[..., None]], -1).astype(np.uint8)


# ================================================================ 总流程
def process_layers(layers: dict, name: str, scale: int = S.RENDER_SCALE,
                   extra_palette: tuple[str, ...] = tuple(LIGHT_COLORS), grain_name: str | None = None) -> dict:
    """渲染三层 → 最终贴图。返回 uint8 数组：rgba / emit / flash（都是 (h,w,4)），以及 stats。
    grain_name：纸纹偏移按哪个名字取（默认 name）。叠层（灯笼叠在主角上）要用底图的名字，叠起来纸纹才对得上。"""
    fill = box_downscale(layers["fill"], scale)
    lines = box_downscale(layers["lines"], scale)
    emit_hi = layers["emit"] * np.clip(layers["fill"][..., 3], 0, 1)
    emit = box_downscale(emit_hi, scale)

    rgb_lin, fa = unpremultiply(fill)
    fill_rgb = linear_to_srgb(rgb_lin) * 255.0
    pal = palette_array(extra_palette)
    fill_rgb = soft_snap(fill_rgb, (fa > 0) & (emit < 0.3), pal)

    la = np.clip(lines[..., 3], 0, 1)
    la = np.clip(ink_bleed(la), 0, 1)
    ink = hex_rgb(S.LINE_COLOR)
    out_a = la + fa * (1 - la)
    num = ink * la[..., None] + fill_rgb * (fa * (1 - la))[..., None]
    out_rgb = np.where(out_a[..., None] > 1e-6, num / np.maximum(out_a[..., None], 1e-6), 0.0)

    h, w = out_a.shape
    out_rgb = np.clip(out_rgb * paper_grain(h, w, grain_name or name)[..., None], 0, 255)

    out_a = np.where(out_a < ALPHA_FLOOR, 0.0, out_a)
    out_rgb = alpha_bleed(out_rgb, out_a)
    rgba = to_rgba8(out_rgb, out_a)

    emit_a = np.clip(emit * (1 - la), 0, 1)
    emit_a = np.where(emit_a < ALPHA_FLOOR, 0.0, emit_a)
    emit_rgb = alpha_bleed(np.where(emit_a[..., None] > 0, fill_rgb, 0.0), emit_a)
    emit_rgba = to_rgba8(emit_rgb, emit_a)

    stats = {
        "opaque_px": int((out_a > 0.5).sum()),
        "line_px": int((la > 0.5).sum()),
        "emit_px": int((emit_a > 0.5).sum()),
    }
    return {"rgba": rgba, "emit": emit_rgba, "flash": make_flash(rgba), "stats": stats}


def save_png(arr: np.ndarray, path) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(arr, "RGBA" if arr.shape[-1] == 4 else "RGB").save(path, optimize=True)
