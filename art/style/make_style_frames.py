#!/usr/bin/env python3
"""生成青丘三时刻色板与构图对照；不是实机截图，不改图集。仅依赖 Pillow。

python3 art/style/make_style_frames.py          # 校对 Rust 后重生 PNG 与参数表
python3 art/style/make_style_frames.py --check  # 校对色板、参数及已保存图像，不写文件
"""

from __future__ import annotations

import argparse
import io
import json
import math
from pathlib import Path
import random
import re

from PIL import Image, ImageDraw, ImageFont

import style as S

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs/style_frames"
C = S.RUNTIME_COLORS
P = S.RUNTIME_LEVELS
FONT = ROOT / "assets/fonts/NotoSerifSC-subset.ttf"
FRAMES = (("01_night", "入夜", 0.0, 0.0), ("02_tide", "妖潮", 1.0, 0.0), ("03_dawn", "天明", 0.0, 0.5))


def check_rust() -> None:
    """以美术色板为来源逐项检查 Rust 常量，避免文档好看但运行时已经漂色。"""
    source = (ROOT / "crates/view/src/palette.rs").read_text(encoding="utf-8")
    colors = dict(re.findall(r"const (\w+): Color = Color::srgb_u8\((\d+, \d+, \d+)\);", source))
    levels = dict(re.findall(r"const (\w+): f32 = ([\d.]+);", source))
    for key, value in C.items():
        expected = S.hex_to_rgb(value)
        actual = tuple(map(int, colors.get(key, "").split(", "))) if key in colors else None
        if actual != expected:
            raise ValueError(f"Rust 色值未同步：{key} 应为 {value} / {expected}，实际 {actual}")
    for key, value in P.items():
        if key not in levels or abs(float(levels[key]) - value) > 1e-6:
            raise ValueError(f"Rust 参数未同步：{key} 应为 {value}")


def linear_mix(a, b, t):
    return tuple(x + (y - x) * t for x, y in zip(a, b))


def ambient(tide, day):
    night, peach, white = (S.hex_to_linear(C[k]) for k in ("NIGHT_AMBIENT", "DAWN_PEACH", "DAWN_WHITE"))
    # 与运行时相同：妖潮剩余压暗随夜色一起退去，天明起点不跳回未压暗的月夜。
    night = tuple(v * (1 - (1 - P["TIDE_AMBIENT_GAIN"]) * tide) for v in night)
    if day > 0:
        return linear_mix(night, peach, day * 2) if day < 0.5 else linear_mix(peach, white, (day - 0.5) * 2)
    return night


def srgb(values):
    def channel(v):
        v = max(0.0, min(1.0, v))
        return round(255 * (v * 12.92 if v <= 0.0031308 else 1.055 * v ** (1 / 2.4) - 0.055))
    return tuple(channel(v) for v in values)


def luminance(values):
    return sum(v * k for v, k in zip(values, (0.2126, 0.7152, 0.0722)))


def scene(tide, day):
    """同机位同轮廓：纸面乘线性光照，小面积自发光相加；不模拟 HDR 辉光和遮挡。"""
    w, h = 752, 278
    surface = Image.new("RGB", (w, h), S.PAPER_SHADOW)
    d = ImageDraw.Draw(surface)
    # 三层远山、弯路与前景枝叶，固定构图留出右侧预警空间。
    d.polygon([(0, 110), (98, 52), (191, 104), (299, 39), (439, 104), (560, 59), (752, 124), (752, 278), (0, 278)], fill=S.INK["qing"])
    d.polygon([(0, 159), (115, 98), (213, 156), (361, 115), (501, 164), (632, 113), (752, 165), (752, 278), (0, 278)], fill=S.INK["dan"])
    d.polygon([(0, 224), (137, 159), (266, 188), (413, 151), (568, 186), (752, 162), (752, 278), (0, 278)], fill=S.INK["zhong"])
    d.polygon([(192, 278), (363, 278), (399, 227), (337, 185), (404, 151), (321, 182), (355, 224)], fill=S.PAPER_SHADOW)
    d.line([(286, 275), (374, 228), (324, 182), (397, 153)], fill=S.INK["qing"], width=2)
    rng = random.Random(71)
    for _ in range(75):
        x, y = rng.randrange(w), rng.randrange(168, h)
        d.line((x, y, x + rng.randrange(3, 14), y - 1), fill=S.INK["dan"])
    # 主角衣身、斗笠与提灯：只表达面积和轮廓，不能代替现有角色素材验收。
    d.ellipse((251, 224, 311, 235), fill=C["INK"])
    d.polygon([(272, 169), (257, 223), (281, 218), (297, 225), (285, 170)], fill=S.PAPER, outline=C["INK"])
    d.polygon([(264, 171), (279, 158), (292, 175)], fill=S.ACCENT["zheshi"], outline=C["INK"])
    d.line([(284, 183), (304, 190), (313, 184), (313, 199)], fill=C["INK"], width=3)
    d.rectangle((307, 199, 319, 216), fill=S.ACCENT["zhusha"], outline=C["INK"])
    d.line((272, 221, 270, 231), fill=C["INK"], width=3)
    d.line((286, 221, 291, 231), fill=C["INK"], width=3)
    for x, y in ((45, 273), (84, 243), (700, 272), (721, 221)):
        d.line((x, y, x - 17, y - 131), fill=C["INK"], width=4)
        for offset in (32, 57, 94):
            d.polygon([(x - 8, y - offset), (x - 42, y - offset - 21), (x - 21, y - offset + 2)], fill=C["INK"])
    # 妖影用同一位置与面积；天明按运行时化去进度淡出。
    dissolve = max(0.0, min(1.0, (day - 0.15) / 0.6))
    dissolve = dissolve * dissolve * (3 - 2 * dissolve)
    enemy = surface.copy()
    ed = ImageDraw.Draw(enemy)
    for x, y in ((502, 201), (550, 183), (584, 223)):
        ed.polygon([(x - 9, y), (x - 5, y - 19), (x + 1, y - 25), (x + 7, y - 15), (x + 12, y)], fill=C["INK"])
    surface = Image.blend(surface, enemy, 1 - dissolve)
    ink = surface.copy()
    ink_draw = ImageDraw.Draw(ink)
    for _ in range(14 if tide else 3):
        x, y = rng.randrange(332, 401), rng.randrange(204, 241)
        radius = rng.randrange(1, 4)
        ink_draw.ellipse((x, y, x + radius * 2, y + radius), fill=C["INK"])
    surface = Image.blend(surface, ink, 1 - day)
    # 白色遮罩分别标注灯窗、妖眼、装饰粒子与危险线，避免借色相伪造亮度。
    masks = {k: Image.new("L", (w, h)) for k in ("lamp", "eyes", "particles", "warning")}
    ImageDraw.Draw(masks["lamp"]).rectangle((310, 202, 316, 213), fill=255)
    for x, y in ((502, 201), (550, 183), (584, 223)):
        ImageDraw.Draw(masks["eyes"]).line((x - 2, y - 16, x + 3, y - 16), fill=160, width=1)
    pd = ImageDraw.Draw(masks["particles"])
    for _ in range(12 if tide else 5):
        x, y = rng.randrange(325, 465), rng.randrange(156, 238)
        pd.line((x, y, x + 3, y - 4), fill=180, width=1)
    if tide:
        wd = ImageDraw.Draw(masks["warning"])
        wd.line([(475, 213), (491, 208), (505, 217), (520, 207), (538, 213), (560, 204)], fill=255, width=3)
        wd.arc((463, 191, 591, 238), 8, 350, fill=220, width=2)
    base = ambient(tide, day)
    lamp = S.hex_to_linear(C["LANTERN_LIGHT"])
    day_gain = 1 - (1 - P["DAWN_LANTERN_GAIN"]) * day
    particle_gain = (1 - (1 - P["TIDE_PARTICLE_GAIN"]) * tide) * (1 - (1 - P["DAWN_PARTICLE_GAIN"]) * day)
    emits = [(masks["lamp"], lamp, day_gain), (masks["eyes"], S.hex_to_linear(S.EYE["shade"]), 1 - dissolve),
             (masks["particles"], S.hex_to_linear(C["GOLD"]), particle_gain),
             (masks["warning"], S.hex_to_linear(C["WARNING"]), P["WARNING_ALPHA_MIN"])]
    mask_pixels = [(list(m.get_flattened_data()), color, gain) for m, color, gain in emits]
    lut = [S.srgb_to_linear(i / 255) for i in range(256)]
    output = []
    for i, pixel in enumerate(surface.get_flattened_data()):
        x, y = i % w, i // w
        distance = ((x - 313) / 104) ** 2 + ((y - 208) / 69) ** 2
        light = math.exp(-distance * 2) * day_gain
        grain = 0.97 + rng.random() * 0.03
        rgb = [lut[pixel[k]] * min(1, base[k] + lamp[k] * light) * grain for k in range(3)]
        for mask, color, gain in mask_pixels:
            for k in range(3):
                rgb[k] += color[k] * mask[i] / 255 * gain * 1.5
        output.append(srgb(rgb))
    result = Image.new("RGB", (w, h))
    result.putdata(output)
    return result


def frame(index, title, tide, day):
    im = Image.new("RGB", (800, 600), S.PAPER)
    d = ImageDraw.Draw(im)
    def text(x, y, value, size=16, color=S.INK["nong"]):
        d.text((x, y), value, font=ImageFont.truetype(str(FONT), size), fill=color)
    text(24, 14, "青丘一夜", 20)
    text(24, 43, title, 32)
    text(502, 28, "画面与色值 / 对照图 " + index[:2], 16)
    text(502, 54, f"tide = {tide:.2f}    dawn = {day:.2f}", 14)
    im.paste(scene(tide, day), (24, 94))
    text(24, 384, "色值对照", 18)
    tokens = [("夜色" if not day else "天明", S.rgb_to_hex(srgb(ambient(tide, day)))),
              ("灯火", C["LANTERN_LIGHT"]), ("预警", C["WARNING"]), ("暗色", C["INK"]),
              ("金光", C["GOLD"]), ("水光", C["WATER_GLOW"])]
    for j, (label, color) in enumerate(tokens):
        x = 24 + j * 128
        d.rectangle((x, 419, x + 111, 444), fill=color)
        text(x, 449, label, 15)
        text(x, 472, color, 14)
    d.line((24, 510, 776, 510), fill=S.INK["qing"])
    order = "灯火 > 妖眼 > 夜色" if not tide and not day else "预警 > 灯火 > 粒子" if tide else "天明 > 灯火 > 妖眼"
    text(24, 523, order, 20)
    text(24, 562, "实机对照见 STYLE_GUIDE.md", 13)
    text(458, 527, f"Y = {luminance(ambient(tide, day)):.4f}", 15)
    text(458, 557, f"{P['IGNITE_LEN']:g} s / {P['DAWN_DELAY']:g} s + {P['DAWN_LEN']:g} s", 15)
    return im


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="校对已保存产物，不写文件")
    args = parser.parse_args()
    check_rust()
    outputs = {}
    for name, title, tide, day in FRAMES:
        data = io.BytesIO()
        frame(name, title, tide, day).save(data, format="PNG", optimize=True)
        outputs[name + ".png"] = data.getvalue()
    table = {"说明": "程序生成色板与构图示意，不是实机截图；Y 为环境底光线性亮度，非最终屏幕亮度。",
             "colors": C, "levels": P,
             "frames": {name: {"tide": tide, "dawn": day, "ambient_srgb": S.rgb_to_hex(srgb(ambient(tide, day))),
                               "ambient_linear_y": round(luminance(ambient(tide, day)), 6)}
                        for name, _, tide, day in FRAMES}}
    outputs["parameters.json"] = (json.dumps(table, ensure_ascii=False, indent=2) + "\n").encode()
    if not args.check:
        OUT.mkdir(parents=True, exist_ok=True)
    for name, content in outputs.items():
        path = OUT / name
        if args.check:
            if not path.exists() or path.read_bytes() != content:
                raise SystemExit(f"样板过期或缺失：{path}；请运行生成命令")
        else:
            path.write_bytes(content)
        print(f"{'校对' if args.check else '生成'}：{path.relative_to(ROOT)}（{len(content)} 字节）")


if __name__ == "__main__":
    main()
