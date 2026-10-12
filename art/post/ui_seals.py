#!/usr/bin/env python3
"""提灯夜行 · 朱砂印章（界面用，只用 Pillow + numpy）。

石章钤在纸上的样子：朱砂印泥有轻有重（大块的压力起伏）、砂眼里露出底下的纸（透明）、
印边不齐、有几处崩口（残边），印泥在笔画边上略积得深一点。印章外面全透明，没有纸底。

  稀有度（天 玄 灵 凡）：方印、白文（红底上刻出白字），印里一道细边栏染该稀有度的卡片色，作为次要的点缀；
  五行共鸣（锐 生 凝 焚 固）：圆印、朱文（红字红边），共鸣触发时盖在屏幕上；
  标记（进化、新纪录、精英、夜主）：竖长方印，进化 / 新纪录 / 精英是朱文，夜主是白文（整块红，压得住）。

印文用完整版思源宋体的最粗一档（900）：笔画粗细匀、横平竖直，缩小后比毛笔楷书更像刻出来的字，
小尺寸下也认得清；字按印面格子略拉伸填满（篆刻的章法），再做圆角、刀口的毛糙和崩口。字体来自 ui_fonts。

坐标按 1 倍像素写，出图密度由 style.DENSITY 决定；尺寸都是 32 的倍数（2 倍下）。
本模块由 ui_icons.py 调用（ui_icons.build() 里和图标一起出图），输出到同一个 ui/ 目录、同一个 meta.json。
"""

from __future__ import annotations

import math
import sys
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import ui_icons as U  # noqa: E402
from ui_fonts import font  # noqa: E402

V, W, S = U.V, U.W, U.S
mixc, smoothstep, col = U.mixc, U.smoothstep, U.col
ZHUSHA, ZHUSHA_DK, W_ZHUSHA, PAPER = U.ZHUSHA, U.ZHUSHA_DK, U.W_ZHUSHA, U.PAPER

GLYPH_FONT = ("serif", 900)  # 印文字体：(ui_fonts 名, 字重)
RARITY_HEX = {"tian": "#c9962e", "xuan": "#7a4fb0", "ling": "#3e6fa8", "fan": "#857e73"}  # 卡片色（与界面皮肤一致）

# (文件名, 印文, 白文/朱文, 形状, 2 倍尺寸 (宽, 高), meta)
SEALS = [
    ("seal_tian", "天", "白文", "square", (128, 128), {"group": "rarity", "id": "tian", "accent": RARITY_HEX["tian"]}),
    ("seal_xuan", "玄", "白文", "square", (128, 128), {"group": "rarity", "id": "xuan", "accent": RARITY_HEX["xuan"]}),
    ("seal_ling", "灵", "白文", "square", (128, 128), {"group": "rarity", "id": "ling", "accent": RARITY_HEX["ling"]}),
    ("seal_fan", "凡", "白文", "square", (128, 128), {"group": "rarity", "id": "fan", "accent": RARITY_HEX["fan"]}),
    ("seal_rui", "锐", "朱文", "round", (128, 128), {"group": "resonance", "id": "metal", "el": "metal"}),
    ("seal_sheng", "生", "朱文", "round", (128, 128), {"group": "resonance", "id": "wood", "el": "wood"}),
    ("seal_ning", "凝", "朱文", "round", (128, 128), {"group": "resonance", "id": "water", "el": "water"}),
    ("seal_fen", "焚", "朱文", "round", (128, 128), {"group": "resonance", "id": "fire", "el": "fire"}),
    ("seal_gu", "固", "朱文", "round", (128, 128), {"group": "resonance", "id": "earth", "el": "earth"}),
    ("seal_evo", "进化", "朱文", "rect", (96, 160), {"group": "mark", "id": "evo"}),
    ("seal_record", "新纪录", "朱文", "rect", (96, 224), {"group": "mark", "id": "record"}),
    ("seal_elite", "精英", "朱文", "rect", (96, 160), {"group": "mark", "id": "elite"}),
    ("seal_boss", "夜主", "白文", "rect", (96, 160), {"group": "mark", "id": "boss"}),
]

MARGIN = 1.6  # 印边离画布边（1 倍像素），留出透明边和残边的余地
BORDER = 2.7  # 朱文印的边宽
GLYPH_PX = 440  # 字形掩码的渲染字号（与密度无关，两种密度采样同一张掩码）


def seal_specs() -> list[dict]:
    out = []
    for i, (fname, text, style, shape_, size2, extra) in enumerate(SEALS):
        meta = {"kind": "seal", **extra, "name": text, "style": style, "shape": shape_, "font": f"{GLYPH_FONT[0]}:{GLYPH_FONT[1]}"}
        out.append({"fname": fname, "text": text, "style": style, "shape": shape_, "size1": (size2[0] / 2, size2[1] / 2), "seed": 8000 + 41 * i, "meta": meta})
    return out


# ============================================================== 字形


@lru_cache(maxsize=64)
def glyph_mask(ch: str) -> np.ndarray:
    """一个字的覆盖度掩码（0..1），裁到字面墨迹的包围盒，四周留 12 像素空白。"""
    name, weight = GLYPH_FONT
    f = font(name, GLYPH_PX, weight)
    n = int(GLYPH_PX * 1.4)
    im = Image.new("L", (n, n), 0)
    ImageDraw.Draw(im).text((n // 2, n // 2), ch, fill=255, font=f, anchor="mm")
    a = np.asarray(im, dtype=np.float64) / 255.0
    ys, xs = np.nonzero(a > 0.02)
    a = a[ys.min() : ys.max() + 1, xs.min() : xs.max() + 1]
    return np.pad(a, 12)


def sample_bilinear(M: np.ndarray, u: np.ndarray, v: np.ndarray) -> np.ndarray:
    """按掩码像素坐标 (u 横, v 竖) 双线性采样，出界为 0。"""
    h, w = M.shape
    inside = (u >= 0) & (u <= w - 1) & (v >= 0) & (v <= h - 1)
    u = np.clip(u, 0, w - 1.001)
    v = np.clip(v, 0, h - 1.001)
    j0, i0 = np.floor(u).astype(int), np.floor(v).astype(int)
    fu, fv = u - j0, v - i0
    out = (M[i0, j0] * (1 - fu) + M[i0, j0 + 1] * fu) * (1 - fv) + (M[i0 + 1, j0] * (1 - fu) + M[i0 + 1, j0 + 1] * fu) * fv
    return out * inside


def glyph_field(P: W.Painter, ch: str, cell, *, stretch: float = 1.2, round_px: float = 0.4) -> np.ndarray:
    """把一个字放进格子 cell=(x0, y0, x1, y1)（1 倍像素）：保持字形比例放到最大，再沿短的一边最多拉伸 stretch 倍填满格子
    （篆刻的章法：字随印面方圆）。round_px 是笔画转角的圆钝程度（1 倍像素）。返回 0..1 的软覆盖度。"""
    M = glyph_mask(ch)
    gh, gw = M.shape[0] - 24, M.shape[1] - 24
    x0, y0, x1, y1 = cell
    cw, chh = x1 - x0, y1 - y0
    s = min(cw / gw, chh / gh)
    sx, sy = min(cw / gw, s * stretch), min(chh / gh, s * stretch)
    bw, bh = gw * sx, gh * sy
    bx, by = (x0 + x1 - bw) / 2, (y0 + y1 - bh) / 2
    Mb = V.fft_blur(M, round_px / min(sx, sy))
    u = (P.X - bx) / sx + 12
    v = (P.Y - by) / sy + 12
    return sample_bilinear(Mb, u, v)


# ============================================================== 印面


def body_sdf(P: W.Painter, shape_: str, w1: float, h1: float) -> np.ndarray:
    """印面的有向距离（内负外正，1 倍像素），不含残边。"""
    cx, cy = w1 / 2, h1 / 2
    if shape_ == "round":
        return np.hypot(P.X - cx, P.Y - cy) - (min(w1, h1) / 2 - MARGIN)
    rc = 2.2
    qx = np.abs(P.X - cx) - (w1 / 2 - MARGIN - rc)
    qy = np.abs(P.Y - cy) - (h1 / 2 - MARGIN - rc)
    return np.hypot(np.maximum(qx, 0), np.maximum(qy, 0)) + np.minimum(np.maximum(qx, qy), 0) - rc


def cells_for(spec) -> list[tuple[float, float, float, float]]:
    w1, h1 = spec["size1"]
    n = len(spec["text"])
    if spec["shape"] == "round":
        r = min(w1, h1) / 2 - MARGIN - BORDER - 3.4
        k = r * 0.8
        return [(w1 / 2 - k, h1 / 2 - k * 1.02, w1 / 2 + k, h1 / 2 + k * 1.02)]
    inset = MARGIN + (BORDER + 2.6 if spec["style"] == "朱文" else 4.6)
    x0, x1 = inset, w1 - inset
    y0, y1 = inset, h1 - inset
    gap = 1.8
    ch = (y1 - y0 - gap * (n - 1)) / n
    return [(x0, y0 + k * (ch + gap), x1, y0 + k * (ch + gap) + ch) for k in range(n)]


def make_seal(index: int) -> Image.Image:
    spec = seal_specs()[index]
    w1, h1 = spec["size1"]
    P = W.Painter(int(w1), int(h1), spec["seed"], ss=U.SS)
    rng = P.rng
    cx, cy = w1 / 2, h1 / 2
    # ---- 印面外形：手刻的边不齐，再崩掉几处
    d = body_sdf(P, spec["shape"], w1, h1)
    d = d + 0.32 * V.noise1(rng, P.X.shape, 1.6 * P.ss) + 0.14 * V.noise1(rng, P.X.shape, 0.45 * P.ss)
    for _ in range(3):
        a = rng.uniform(0, 2 * math.pi)
        if spec["shape"] == "round":
            R = min(w1, h1) / 2 - MARGIN
            px, py = cx + R * math.cos(a), cy + R * math.sin(a)
        else:
            px = cx + (w1 / 2 - MARGIN) * float(np.clip(1.5 * math.cos(a), -1, 1))
            py = cy + (h1 / 2 - MARGIN) * float(np.clip(1.5 * math.sin(a), -1, 1))
        r = rng.uniform(1.0, 2.0)
        d = np.maximum(d, r - np.hypot(P.X - px, P.Y - py))
    body = smoothstep(P.aa, -P.aa, d)
    # ---- 印文
    glyph = np.zeros(P.X.shape)
    for ch, cell in zip(spec["text"], cells_for(spec)):
        glyph = np.maximum(glyph, glyph_field(P, ch, cell))
    gnoise = 0.12 * V.noise1(rng, P.X.shape, 0.5 * P.ss)
    th = 0.42 if spec["style"] == "白文" else 0.38  # 白文字口略放开，朱文字略加粗
    g = smoothstep(th - 0.06, th + 0.06, glyph + gnoise)
    # ---- 印泥：朱文是边框 + 字，白文是整块减去字
    if spec["style"] == "朱文":
        bw = BORDER * np.clip(1.0 + 0.18 * V.noise1(rng, P.X.shape, 3.0 * P.ss), 0.6, 1.4)
        frame = body * smoothstep(-bw - P.aa, -bw + P.aa, d)
        ink = np.maximum(frame, g * body)
    else:
        ink = body * (1.0 - g)
        if spec["meta"].get("group") == "rarity":
            # 细边栏：印面里一圈细线，染稀有度的卡片色（次要点缀）
            line = smoothstep(0.42 + P.aa, 0.42 - P.aa, np.abs(d + 3.0))
            acc = col(spec["meta"]["accent"])
            ink_line = line * body
    # ---- 压力起伏、砂眼、边上积色
    press = V.noise1(rng, P.X.shape, 6.0 * P.ss)
    press = press + 0.6 * V.noise1(rng, P.X.shape, 2.0 * P.ss)
    p01 = np.clip(0.5 + 0.3 * press, 0, 1)
    speck = V.rank01(V.noise1(rng, P.X.shape, 0.22 * P.ss))
    hole_th = 0.975 - 0.03 * (1 - p01)
    holes = smoothstep(hole_th, hole_th + 0.015, speck)  # 细砂眼：零星几点
    patch = smoothstep(0.88, 0.97, V.rank01(V.noise1(rng, P.X.shape, 1.4 * P.ss)))  # 几处压得轻的地方
    grain = smoothstep(0.45, 0.6, V.rank01(V.noise1(rng, P.X.shape, 0.25 * P.ss)))
    holes = np.maximum(holes, patch * grain)
    dens = (0.88 + 0.12 * p01) * (1.0 - 0.9 * holes)
    soft = V.fft_blur(ink, 0.9 * P.ss * V.D)
    edge = np.clip(ink - soft, 0, 1)
    rgb = mixc(mixc(ZHUSHA, W_ZHUSHA, 0.14), mixc(ZHUSHA, ZHUSHA_DK, 0.32), p01)
    rgb = mixc(rgb, ZHUSHA_DK, np.clip(edge * 1.4, 0, 0.55))
    P.lay.over(rgb, ink * dens)
    if spec["style"] == "白文" and spec["meta"].get("group") == "rarity":
        P.lay.over(mixc(mixc(acc, ZHUSHA, 0.25), PAPER, 0.15), ink_line * (1.0 - 0.6 * holes))
    return P.image()


def main() -> None:
    """单独预览：把全部印章画到 art/out/<ASSETS>/ui/ 之外的检查图里（正式出图请运行 ui_icons.py）。"""
    imgs = [make_seal(i) for i in range(len(SEALS))]
    wsum = sum(im.width for im in imgs) + 10 * (len(imgs) + 1)
    hmax = max(im.height for im in imgs) + 20
    sheet = Image.new("RGB", (wsum, hmax), S.PAPER)
    x = 10
    for im in imgs:
        sheet.paste(im, (x, 10), im)
        x += im.width + 10
    out = V.REVIEW_DIR / "seals_preview.png"
    V.save_png(sheet, out)
    print("写出", out)


if __name__ == "__main__":
    main()
