#!/usr/bin/env python3
"""青藤 / 万木春的独立 HUD 圆章，只生成两个 128px 图标，不重渲整套 UI。

    python3 art/post/ui_vine_icons.py

源目录 art/out/assets@2x/ui_vine/（name=ui，密度4），预览在
art/out/review@2x/ui_vine_icons.png。画布、纸底、墨圈、木色弧和进化金圈复用 ui_icons。
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

os.environ["LANTERN_ART_DENSITY"] = "2"

import numpy as np
from PIL import Image, ImageDraw, ImageFont

import ui_icons as U

ROOT = Path(__file__).resolve().parents[2]
V, W = U.V, U.W
GREEN = U.mixc(U.EL_INK["wood"], U.SHILV, 0.35)
DARK = U.mixc(GREEN, U.JIAO, 0.6)
LIGHT = U.mixc(GREEN, U.W_SHILV, 0.45)


def vine_stroke(painter, points, width, *, gold=False):
    """墨骨、青色藤皮与一道短亮面，粗细随笔势收拢。"""
    width = np.asarray(width)
    U.stroke(painter, points, width + 0.55, DARK, jitter=0.08)
    U.stroke(painter, points, width, GREEN, jitter=0.06)
    U.stroke(painter, points - np.array([0.35, 0.4]), width * 0.25,
             U.mixc(LIGHT, U.GOLD_HI, 0.45) if gold else LIGHT, 0.9, jitter=0.04)


def coiled_vine(painter):
    """一根有空心的盘藤，五片宽叶；缩小后仍保留清楚的盘绕轮廓。"""
    curves = [
        [(18, 48), (10, 37), (14, 19), (29, 17)],
        [(29, 17), (47, 14), (54, 36), (40, 43)],
        [(40, 43), (29, 50), (18, 37), (27, 29)],
        [(27, 29), (32, 24), (39, 29), (35, 35)],
    ]
    points = np.vstack([V.bezier(curve, 34)[:-1] for curve in curves])
    vine_stroke(painter, points, np.linspace(2.25, 1.1, len(points)))
    for x, y, angle, length, width in [
        (17, 24, -148, 10, 5.8),
        (28, 13, -80, 10, 5.8),
        (47, 26, -28, 10, 5.7),
        (42, 47, 41, 10, 5.8),
        (16, 43, 163, 9, 5.5),
    ]:
        U.leaf(painter, x, y, angle, length, width, GREEN)
    for points in [[(20, 40), (17, 36), (22, 37)], [(42, 23), (45, 19), (45, 26)]]:
        U.shape(painter, points, DARK, ol=0.45, mottle=0.0, wob=0.02)


def spring_boughs(painter):
    """粗藤从根部生出繁枝，八片叶形成向上的树冠，与盘藤有不同剪影。"""
    for curve in [
        [(31, 46), (26, 49), (21, 51), (18, 49)],
        [(32, 47), (36, 52), (42, 53), (46, 49)],
        [(32, 46), (32, 50), (30, 52), (30, 54)],
    ]:
        points = V.bezier(curve, 30)
        vine_stroke(painter, points, np.linspace(1.4, 0.4, len(points)), gold=True)
    branches = [
        ([(32, 48), (27, 37), (35, 28), (32, 12)], 2.5, 0.8),
        ([(31, 36), (22, 31), (16, 25), (14, 23)], 1.7, 0.55),
        ([(31, 31), (40, 31), (46, 27), (49, 24)], 1.65, 0.55),
        ([(31, 27), (26, 23), (23, 20), (22, 16)], 1.35, 0.5),
        ([(32, 23), (36, 20), (40, 18), (41, 15)], 1.3, 0.5),
        ([(31, 39), (26, 34), (22, 31), (19, 30)], 1.35, 0.55),
        ([(32, 36), (38, 35), (43, 33), (46, 32)], 1.4, 0.55),
    ]
    for curve, start, end in branches:
        points = V.bezier(curve, 38)
        vine_stroke(painter, points, np.linspace(start, end, len(points)), gold=True)
    for i, (x, y, angle, length, width) in enumerate([
        (13.5, 23, -145, 10, 6.3),
        (22, 16, -115, 11, 6.7),
        (31.5, 12.5, -88, 10, 6.2),
        (41, 16, -55, 11, 6.6),
        (48, 24, -20, 11, 6.6),
        (19, 30, -155, 11, 6.6),
        (45, 32, -5, 11, 6.3),
        (28, 26, -148, 9, 5.7),
    ]):
        U.leaf(painter, x, y, angle, length, width, U.mixc(GREEN, LIGHT, 0.2 if i % 2 else 0.0))
    painter.dot(31.5, 38.0, 1.15, U.TENG)
    painter.dot(31.2, 37.6, 0.45, U.GOLD_HI)


def make_icon(evolved: bool) -> Image.Image:
    painter = W.Painter(U.SIZE, U.SIZE, 17147 if evolved else 17110, ss=U.SS)
    U.frame_back(painter, "wood", evo=evolved)
    (spring_boughs if evolved else coiled_vine)(painter)
    U.frame_front(painter, "wood", evo=evolved)
    return painter.image()


def preview(images: list[Image.Image], path: Path) -> None:
    font_path = "/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc"
    try:
        font = ImageFont.truetype(font_path, 21)
        small = ImageFont.truetype(font_path, 16)
    except OSError:
        font = small = ImageFont.load_default()
    sheet = Image.new("RGBA", (944, 540), "#171A22")
    draw = ImageDraw.Draw(sheet)
    for i, (image, name) in enumerate(zip(images, ("青藤 · 盘藤", "万木春 · 繁枝"))):
        x = 24 + i * 464
        draw.text((x, 15), name, font=font, fill=U.S.PAPER)
        for j, background in enumerate((U.S.PAPER, "#242934")):
            left = x + j * 204
            draw.rounded_rectangle((left, 53, left + 184, 237), radius=9, fill=background)
            sheet.alpha_composite(image, (left + 28, 81))
        draw.text((x, 249), "128 px 原图；下方为 48 / 32 / 24 px", font=small, fill=U.S.PAPER)
        for j, size in enumerate((48, 32, 24)):
            sheet.alpha_composite(image.resize((size, size), Image.Resampling.LANCZOS), (x + 36 + j * 116, 289))
    draw.line((24, 358, 920, 358), fill="#4F4942", width=1)
    draw.text((24, 370), "现有圆章对照（只读图集，不重新生成）", font=small, fill=U.S.PAPER)
    atlas = json.loads((ROOT / "assets/atlas/ui.json").read_text(encoding="utf-8"))
    with Image.open(ROOT / "assets/atlas" / atlas["meta"]["image"]) as source:
        for i, (key, name) in enumerate((("crane", "纸鹤"), ("crane_evo", "千鹤引"), ("huichun", "回春"))):
            frame = atlas["frames"][f"ui/icon_{key}"]["frame"]
            rect = (frame["x"], frame["y"], frame["x"] + frame["w"], frame["y"] + frame["h"])
            image = source.crop(rect).convert("RGBA").resize((96, 96), Image.Resampling.LANCZOS)
            sheet.alpha_composite(image, (100 + i * 280, 411))
            draw.text((211 + i * 280, 445), name, font=small, fill=U.S.PAPER)
    V.save_png(sheet, path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, default=ROOT / "art/out/assets@2x/ui_vine")
    parser.add_argument("--review", type=Path, default=ROOT / "art/out/review@2x/ui_vine_icons.png")
    args = parser.parse_args()
    files, images = {}, []
    for evolved, name in ((False, "青藤"), (True, "万木春")):
        filename = f"icon_vine{'_evo' if evolved else ''}.png"
        image = make_icon(evolved)
        V.save_png(image, args.out / filename)
        images.append(image)
        files[filename] = V.anchor_entry(image, (0.5, 0.5), blend="normal", tint=False,
            kind="weapon_evo" if evolved else "weapon", id="vine", el="wood", name=name)
    meta = {"name": "ui", "generator": "art/post/ui_vine_icons.py", "px_per_unit": V.PPU,
        "display_px_1x": U.SIZE, "format": "PNG RGBA，直通 alpha，全彩不染色", "files": files}
    (args.out / "meta.json").write_text(V.dump_json(meta), encoding="utf-8")
    preview(images, args.review)
    print(f"两个 128px 圆章：{args.out}\n预览：{args.review}")


if __name__ == "__main__":
    main()
