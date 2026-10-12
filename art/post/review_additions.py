#!/usr/bin/env python3
"""提灯夜行 · 第二批 2D 素材的检查图（读盘，不重新生成）。

  art/out/review[@2x]/additions_sheet.png  界面图标（原大与 32 像素显示大小，纸色底 / 夜色底）、狐火、第二批地面贴图
  art/out/review[@2x]/ground_mock.png         游戏比例的地面场景：新旧地面装饰混排（宣纸上不打光 / 夜里灯照）

先跑 vfx_textures.py、weapon_textures.py、ui_icons.py（同一密度），再跑本脚本：
  art/.venv/bin/python art/post/review_additions.py
  LANTERN_ART_DENSITY=2 art/.venv/bin/python art/post/review_additions.py
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import vfx_textures as V  # noqa: E402
import weapon_textures as W  # noqa: E402

S = V.S
D = V.D
col = V.col
NIGHT = col(S.NIGHT_AMBIENT)
GROUND_NEW = ["spring", "rift", "rift_glow", "reed_0", "reed_1", "reed_2", "leaves_0", "leaves_1", "pebbles_0", "pebbles_1", "puddle_0", "bamboo_0", "bamboo_1"]
RIFT_TINT = "#D2386A"


def label_font(size: int):
    """检查图标签用的字体：有文泉驿就用（能显示中文名），没有就退回默认字体。只影响检查图，不影响素材。"""
    from PIL import ImageFont  # noqa: PLC0415

    for p in ("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc", "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"):
        try:
            return ImageFont.truetype(p, size)
        except OSError:
            continue
    return V.font(size)


def load(folder: str, name: str) -> Image.Image:
    return Image.open(V.ASSETS / folder / f"{name}.png").convert("RGBA")


def meta(folder: str) -> dict:
    """meta.json 的 files，键去掉 .png 后缀。"""
    files = json.loads((V.ASSETS / folder / "meta.json").read_text(encoding="utf-8"))["files"]
    return {k[:-4] if k.endswith(".png") else k: v for k, v in files.items()}


def paste(canvas: np.ndarray, img: Image.Image, x: int, y: int, mode="over", tint=None, scale: float = 1.0):
    """整数倍用最近邻放大（看真实像素），其他倍数用 LANCZOS（看显示效果）。"""
    if scale != 1.0:
        if float(scale).is_integer():
            img = img.resize((int(img.width * scale), int(img.height * scale)), Image.NEAREST)
        else:
            img = img.resize((max(1, round(img.width * scale)), max(1, round(img.height * scale))), Image.LANCZOS)
    V.composite(canvas, img, int(x), int(y), mode, tint, scale=1)


# ============================================================== 拼图


def additions_sheet(path: Path) -> None:
    ui_meta = meta("ui")
    icons = list(ui_meta)
    k = 2 / D  # 图标放大到 128 像素看细节（1 倍 2×，2 倍 1×）
    cell = int(64 * D * k) + 70
    cols = 5
    rows = math.ceil(len(icons) / cols)
    pad, label_h, title_h = 16, 16, 30
    width = pad + cols * 2 * (cell + 8) + pad
    icons_h = rows * (cell + label_h + 10)
    gm = meta("ground")
    wm = meta("weapons")
    ground_imgs = [(n, load("ground", n)) for n in GROUND_NEW]
    gk = max(1, int(round(2 / D)))
    # 地面一行行排
    gx, gy, grow = pad, 0, 0
    gpos = []
    for n, im in ground_imgs:
        w_, h_ = max(im.width * gk, 96), im.height * gk + label_h
        if gx + w_ + pad > width // 2 - pad:
            gx, gy = pad, gy + grow + 12
            grow = 0
        gpos.append((gx, gy))
        gx += w_ + 14
        grow = max(grow, h_)
    ground_h = gy + grow + 12
    fox_k = max(1, int(round(4 / D)))
    fox_h = int(24 * D) * fox_k + label_h + 12
    H = title_h + icons_h + title_h + fox_h + title_h + ground_h + pad
    canvas = np.zeros((H, width, 3))
    half = width // 2
    canvas[:, :half] = W.PAPER
    canvas[:, half:] = NIGHT
    labels = []
    y0 = title_h
    labels.append((pad, 8, "UI icons: native (x%g) + 32 px display size; left on paper, right on night" % k, 0))
    for i, n in enumerate(icons):
        r, c = divmod(i, cols)
        im = load("ui", n)
        for side in (0, 1):
            x = side * half + pad + c * (cell + 8)
            y = y0 + r * (cell + label_h + 10)
            paste(canvas, im, x, y + label_h, scale=k)
            paste(canvas, im, x + int(64 * D * k) + 6, y + label_h + int(64 * D * k) - 32, scale=32 / im.width)
            labels.append((x, y, f"{n.replace('icon_', '')} {ui_meta[n]['name']}", side))
    y0 += icons_h
    labels.append((pad, y0 + 8, "foxfire_0..2 (boss bullet): untinted on paper, tinted %s additive on night" % S.EYE["fox"], 0))
    y0 += title_h
    for i in range(3):
        im = load("weapons", f"foxfire_{i}")
        x = pad + i * (im.width * fox_k + 20)
        paste(canvas, im, x, y0 + label_h, scale=fox_k)
        paste(canvas, im, half + x, y0 + label_h, mode="add", tint=col(S.EYE["fox"]), scale=fox_k)
        labels.append((x, y0, f"foxfire_{i} {wm[f'foxfire_{i}']['size'][0]}x{wm[f'foxfire_{i}']['size'][1]}", 0))
    y0 += fox_h
    labels.append((pad, y0 + 8, "ground additions (normal blend; rift_glow additive tinted %s on night)" % RIFT_TINT, 0))
    y0 += title_h
    for (n, im), (x, y) in zip(ground_imgs, gpos):
        add = gm[n]["blend"] == "add"
        paste(canvas, im, x, y0 + y + label_h, scale=gk)
        paste(canvas, im, half + x, y0 + y + label_h, mode="add" if add else "over", tint=col(RIFT_TINT) if add else None, scale=gk)
        labels.append((x, y0 + y, f"{n} {im.width}x{im.height}", 0))
        labels.append((half + x, y0 + y, f"{n}" + (" add" if add else ""), 1))
    out = Image.fromarray(np.round(np.clip(canvas, 0, 1) * 255).astype(np.uint8), "RGB")
    dr = ImageDraw.Draw(out)
    f = label_font(12)
    for x, y, text, side in labels:
        dr.text((x, y), text, fill=S.INK["nong"] if side == 0 else "#C8C8C8", font=f)
    V.save_png(out, path)


# ============================================================== 地面场景


def optional_prop(name: str):
    """Blender 管线出的道具（山石、石灯笼），当前密度没有就借 1 倍的放大，再没有就跳过。"""
    for base, k in ((V.ASSETS, 1.0), (V.OUT / "assets", D)):
        p = base / name / "idle_S_00.png"
        if p.exists():
            return Image.open(p).convert("RGBA"), k
    return None, 1.0


def ground_mock(path: Path) -> None:
    Wm, Hm = V.dpx(1000), V.dpx(640)
    paper = Image.open(V.ASSETS / "ground" / "paper.png").convert("RGB")
    pt = np.asarray(paper, dtype=np.float64) / 255.0
    reps = (Hm // pt.shape[0] + 1, Wm // pt.shape[1] + 1, 1)
    base = np.tile(pt, reps)[:Hm, :Wm].copy()
    G = {n: load("ground", n) for n in ["wash_0", "wash_1", "wash_2", *[f"grass_{i}" for i in range(4)], *GROUND_NEW]}
    gm = meta("ground")
    shadow = load("vfx", "shadow")
    light = load("vfx", "light")
    hero, hero_k = optional_prop("hero")
    lantern, lantern_k = optional_prop("stone_lantern")
    rocks = [optional_prop(r) for r in ("rock_a", "rock_b", "rock_c")]

    def put(canvas, img, x, y, **kw):
        W.place(canvas, img, x * D, y * D, **kw)

    def A(n):
        return tuple(gm[n]["anchor"])

    layout = [
        ("wash_0", 210, 470, 1.3), ("wash_2", 760, 170, 1.2), ("wash_1", 640, 560, 1.0),
        ("spring", 250, 200, 1.0), ("rift", 760, 420, 1.0), ("puddle_0", 520, 520, 1.0),
        ("pebbles_0", 380, 300, 1.0), ("pebbles_1", 120, 560, 1.0), ("leaves_0", 560, 250, 1.0), ("leaves_1", 900, 560, 1.0),
    ]
    upright = [  # (名, x, y) 锚点在底边的，按 y 排序画
        ("reed_0", 140, 250), ("reed_1", 175, 262), ("reed_2", 360, 160), ("bamboo_0", 900, 270), ("bamboo_1", 940, 300),
        ("grass_0", 330, 420), ("grass_1", 600, 380), ("grass_2", 860, 470), ("grass_3", 450, 600), ("reed_2", 700, 610), ("grass_1", 60, 400),
    ]

    def draw_world(world):
        for n, x, y, s in layout:
            put(world, G[n], x, y, anchor=A(n), scale=s)
        items = [(y, "g", n, x) for n, x, y in upright]
        for i, (img, k) in enumerate(rocks):
            if img is not None:
                items.append(((330, 600, 480)[i], "r", i, (420, 120, 980 - 40)[i]))
        if lantern is not None:
            items.append((300, "l", 0, 640))
        if hero is not None:
            items.append((380, "h", 0, 470))
        for y, kind, n, x in sorted(items, key=lambda t: t[0]):
            if kind == "g":
                put(world, G[n], x, y, anchor=A(n))
            elif kind == "r":
                img, k = rocks[n]
                put(world, shadow, x, y, scale=0.7, alpha=0.8)
                put(world, img, x, y, anchor=(0.5, 0.8), scale=k)
            elif kind == "l":
                put(world, shadow, x, y, scale=0.8, alpha=0.8)
                put(world, lantern, x, y, anchor=(0.5, 0.8), scale=lantern_k)
            elif kind == "h":
                put(world, shadow, x, y, scale=1.0)
                put(world, hero, x, y, anchor=(0.5, 0.875), scale=hero_k)

    day = base.copy()
    draw_world(day)
    night_world = base.copy()
    draw_world(night_world)
    lm = np.broadcast_to(NIGHT, night_world.shape).copy()
    put(lm, light, 470, 330, scale=760 * D / light.width, mode="add", tint=col(S.LANTERN_LIGHT))
    put(lm, light, 640, 270, scale=300 * D / light.width, mode="add", tint=col(S.LANTERN_LIGHT) * 0.7)
    put(lm, light, 250, 200, scale=260 * D / light.width, mode="add", tint=col(S.SOUL_LIGHT) * 0.35)
    put(lm, light, 760, 420, scale=260 * D / light.width, mode="add", tint=col(RIFT_TINT) * 0.35)
    night = night_world * np.clip(lm, 0, 1)
    put(night, G["rift_glow"], 760, 420, anchor=A("rift_glow"), mode="add", tint=col(RIFT_TINT))
    put(day, G["rift_glow"], 760, 420, anchor=A("rift_glow"), mode="add", tint=col(RIFT_TINT), alpha=0.35)
    if lantern is not None:
        emit = V.ASSETS / "stone_lantern" / "idle_S_00_emit.png"
        if emit.exists():
            put(night, Image.open(emit).convert("RGBA"), 640, 300, anchor=(0.5, 0.8), mode="add")
    gap, top = 12, V.dpx(30)
    out = np.ones((Hm + top, Wm * 2 + gap, 3)) * 0.1
    out[top:, :Wm] = np.clip(day, 0, 1)
    out[top:, Wm + gap :] = np.clip(night, 0, 1)
    im = Image.fromarray(np.round(out * 255).astype(np.uint8), "RGB")
    dr = ImageDraw.Draw(im)
    f = V.font(V.dpx(14))
    dr.text((8, 7), f"day: paper, normal over (density {D:g}x, 1 texel = {1 / S.PX_PER_UNIT:g} world unit)", fill="#DDDDDD", font=f)
    dr.text((Wm + gap + 8, 7), "night: world x lightmap (lantern, spring, rift) + rift_glow additive", fill="#DDDDDD", font=f)
    V.save_png(im, path)


def main() -> None:
    V.REVIEW_DIR.mkdir(parents=True, exist_ok=True)
    additions_sheet(V.REVIEW_DIR / "additions_sheet.png")
    ground_mock(V.REVIEW_DIR / "ground_mock.png")
    print("写出", V.REVIEW_DIR / "additions_sheet.png", "与", V.REVIEW_DIR / "ground_mock.png")


if __name__ == "__main__":
    main()
