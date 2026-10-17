#!/usr/bin/env python3
"""提灯夜行 · 主角状态栏样张：黑漆描金 / 绢本织锦两套材质（复用 card_frames.py 的漆面、描金、绢面、织锦、铜件）。

按 1280×720 设计画布的逻辑像素排（1080p 下 ×1.5），贴图画 2 倍。状态栏整块放左上，不碰顶部正中的计时、
右上的五行计数、左下的按键提示：
  头像圆章（主角胸像）+ 一圈十二格的燃灯刻度（满了整圈亮）+ 右下一枚等级印；
  大血条 460×30：材质边框，数字写在条里，护盾是叠在血条上半的另一种颜色，掉血残影留一段浅色；
  经验条 10 高，带连珠纹，在血条下；
  法器格 64×64（底边一排等级点），心法格 44×44，空格只有淡淡的格框。
九宫格件按 out/skin 的做法出（记切边）：art/out/skin_hud/<lacquer|silk>/*.png + skin.json。

输出：art/out/review@2x/hud_sample_lacquer.png、hud_sample_silk.png（1920×1080，压在暗下来的游戏画面上），
      hud_sample_zoom.png（左上这一块按贴图原尺寸，两种画法上下对比，另加燃灯满格的样子）。

用法（仓库根目录）：art/.venv/bin/python art/post/hud_frames.py
"""

from __future__ import annotations

import json
import math
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import card_frames as CF  # noqa: E402
from card_frames import (GOLD, GOLD_OLD, GILT, COPPER, Cv, hexc, metal, mixc, paste, plain_text, rrect_sd, smoothstep,  # noqa: E402
                         fft_blur)

ART = CF.ART
REVIEW = CF.REVIEW
SKIN_OUT = ART / "out" / "skin_hud"
UI_ICONS = CF.UI_ICONS

# 逻辑尺寸（1280×720 画布）
BAR_W, BAR_H = 460, 30
XP_W, XP_H = 460, 10
SLOT_L, SLOT_S = 64, 44
PORTRAIT = 104  # 头像章外径
WINDOW = 78  # 头像窗口直径
SEAL = 30


# ============================================================== 件

def bar_frame(style: str, w: int, h: int, seed: int, ornate: bool = True) -> Image.Image:
    """横条的框（2 倍）：漆是黑漆槽 + 金边，两头一对金卷；绢是素锦包边 + 铜头。中间是深色的槽。"""
    W, H = w * 2, h * 2
    c = Cv(W, H, seed=seed, ss=2)
    r = H * 0.32
    d = rrect_sd(c.X, c.Y, 2, 2, W - 2, H - 2, r)
    body = smoothstep(c.aa, -c.aa, d)
    inset = 7.0 if h >= 20 else 4.0
    trough = rrect_sd(c.X, c.Y, inset + 2, inset + 2, W - inset - 2, H - inset - 2, max(r - inset, 2))
    if style == "lacquer":
        rgb, _, _ = CF.lacquer_surface(c, 2, 2, W - 2, H - 2, r, "fan")
        c.over(rgb, body)
        rim = smoothstep(1.4 + c.aa, 1.4 - c.aa, np.abs(d + 3.0))
        c.over(metal(c, rim, GOLD, sigma=0.5), rim * body)
    else:
        silk = CF.silk_field(c, 2, 2, W - 2, H - 2)
        c.over(silk, body)
        brc, band = CF.brocade_band(c, "fan", d, trough + 2.5, period=16.0)
        c.over(brc, band)
    # 槽：深色、上沿一道内阴影
    tb = smoothstep(c.aa, -c.aa, trough)
    shade = np.exp(-np.maximum(c.Y - (inset + 2), 0) / 4.0)
    c.over(hexc("#07090C") * (1 + 0.15 * (1 - shade))[..., None], tb * 0.96)
    if style == "lacquer":
        lip = smoothstep(1.0 + c.aa, 1.0 - c.aa, np.abs(trough + 0.6))
        c.over(metal(c, lip, GOLD_OLD, sigma=0.4), lip * 0.9)
    if ornate:  # 两头的饰件：漆是一对小金卷，绢是铜包头（都在左右切片以内）
        for sx in (1, -1):
            x0 = 14.0 if sx > 0 else W - 14.0
            if style == "lacquer":  # 一粒金珠夹在两道短金线里
                m = smoothstep(3.6 + c.aa, 3.6 - c.aa, np.hypot(c.X - x0, c.Y - H / 2))
                for dy in (-1, 1):
                    m = np.maximum(m, CF.stroke_mask(c, [(x0 + 7 * sx, H / 2 + dy * 6), (x0 + 16 * sx, H / 2 + dy * 6)], 1.0))
                c.over(metal(c, m, GOLD, sigma=0.5, depth=1.3), m)
            else:
                cap = rrect_sd(c.X, c.Y, (0 if sx > 0 else W - 26), 0, (26 if sx > 0 else W), H, r)
                capm = smoothstep(c.aa, -c.aa, np.maximum(cap, d))
                nail = smoothstep(3.4 + c.aa, 3.4 - c.aa, np.hypot(c.X - (x0 - 2 * sx), c.Y - H / 2))
                c.over(metal(c, capm * 0.6 + nail * 0.6, COPPER, sigma=0.8, depth=1.5), capm)
    return c.image()


def bar_fill(kind: str, w: int, h: int, seed: int) -> Image.Image:
    """填充条（2 倍）：hp 朱漆红，trail 掉血残影（浅），shield 护盾（淡青白，只画上半），xp 泥金。两头圆。"""
    W, H = w * 2, h * 2
    c = Cv(W, H, seed=seed, ss=2)
    r = H * 0.45
    d = rrect_sd(c.X, c.Y, 0.5, 0.5, W - 0.5, H - 0.5, r)
    m = smoothstep(c.aa, -c.aa, d)
    t = (c.Y / H)[..., None]
    if kind == "hp":
        rgb = mixc(hexc("#E8553C"), hexc("#7E1A14"), t[..., 0] ** 0.9)
        gloss = np.exp(-((c.Y / H - 0.26) / 0.10) ** 2)
        rgb = rgb + hexc("#FFD6B8") * (0.28 * gloss)[..., None]
        streak = CF.noise(c.rng, c.X.shape, (40.0 * c.ss, 1.2 * c.ss))
        rgb = rgb * (1 + 0.06 * streak)[..., None]
        a = m
    elif kind == "trail":
        rgb = mixc(hexc("#FFF0DA"), hexc("#E8C9A6"), t[..., 0])
        a = m * 0.85
    elif kind == "shield":
        rgb = mixc(hexc("#EAF6FF"), hexc("#8FC4EE"), t[..., 0])
        gloss = np.exp(-((c.Y / H - 0.3) / 0.15) ** 2)
        rgb = rgb + 0.15 * gloss[..., None]
        a = m * 0.88
    else:  # xp
        rgb = CF.ramp(0.74 + 0.24 * (1 - t[..., 0]) + 0.05 * CF.noise(c.rng, c.X.shape, 1.5 * c.ss), GILT)
        beads = np.zeros(c.X.shape)
        for x in np.arange(8.0, W, 14.0):
            beads = np.maximum(beads, smoothstep(2.0 + c.aa, 2.0 - c.aa, np.hypot(c.X - x, c.Y - H / 2)))
        rgb = rgb * (1 - 0.18 * beads)[..., None] + hexc("#FFF4CC") * (0.10 * beads)[..., None]
        a = m
    c.over(np.clip(rgb, 0, 1), a)
    return c.image()


def slot(style: str, size: int, empty: bool, seed: int) -> Image.Image:
    """法器格 / 心法格（2 倍）：漆是黑漆方砚 + 金边（空格只有一道淡金虚边）；绢是绢面方格 + 素锦边、铜角（空格只有淡墨框）。"""
    S_ = size * 2
    c = Cv(S_, S_, seed=seed, ss=2)
    r = 10.0 if size >= 60 else 8.0
    d = rrect_sd(c.X, c.Y, 2, 2, S_ - 2, S_ - 2, r)
    body = smoothstep(c.aa, -c.aa, d)
    if empty:
        # 空格：淡淡的格框（虚线），中间几乎透明
        per = CF.rrect_points(5, 5, S_ - 5, S_ - 5, r - 2, 1.0)
        dash = (np.arange(len(per)) // 6) % 2 == 0
        m = np.zeros(c.X.shape)
        pts = per[dash]
        for p in pts[::2]:
            m = np.maximum(m, CF.stroke_mask(c, [p, p + 0.01], 1.2))
        c.over(hexc("#000000"), body * 0.28)
        if style == "lacquer":
            c.over(metal(c, m, GOLD_OLD, sigma=0.3), m * 0.55)
        else:
            c.over(hexc("#D8CCB0"), m * 0.55)
        return c.image()
    if style == "lacquer":
        rgb, _, _ = CF.lacquer_surface(c, 2, 2, S_ - 2, S_ - 2, r, "fan")
        c.over(rgb, body)
        rim = smoothstep(1.5 + c.aa, 1.5 - c.aa, np.abs(d + 4.0))
        c.over(metal(c, rim, GOLD, sigma=0.5), rim)
        inner = np.exp(-np.maximum(-d - 6, 0) / 6.0) * (d < -6)
        c.over(hexc("#000000"), inner * 0.35)
    else:
        c.over(CF.silk_field(c, 2, 2, S_ - 2, S_ - 2), body)
        inner = rrect_sd(c.X, c.Y, 9, 9, S_ - 9, S_ - 9, r - 6)
        brc, band = CF.brocade_band(c, "fan", d, inner, period=14.0)
        c.over(brc, band)
        for (cx, cy) in ((8, 8), (S_ - 8, 8), (8, S_ - 8), (S_ - 8, S_ - 8)):
            nail = smoothstep(4.0 + c.aa, 4.0 - c.aa, np.hypot(c.X - cx, c.Y - cy))
            c.over(metal(c, nail, COPPER, sigma=0.7, depth=1.6), nail)
    return c.image()


def portrait_frame(style: str, seed: int = 31) -> Image.Image:
    """头像圆章（2 倍）：中间留出头像窗口；漆是黑漆圆盘 + 内外两道金圈；绢是一圈素锦 + 铜圈。燃灯刻度另画。"""
    S_ = PORTRAIT * 2
    c = Cv(S_, S_, seed=seed, ss=2)
    cc = S_ / 2
    rr = np.hypot(c.X - cc, c.Y - cc)
    outer = rr - (cc - 2)
    win = rr - WINDOW
    ring = smoothstep(c.aa, -c.aa, outer) * smoothstep(-c.aa, c.aa, win)
    if style == "lacquer":
        rgb, _, _ = CF.lacquer_surface(c, 0, 0, S_, S_, cc, "fan")
        c.over(rgb, ring)
        for rad, hw in ((cc - 5.0, 1.4), (WINDOW + 2.5, 2.2)):
            m = smoothstep(hw + c.aa, hw - c.aa, np.abs(rr - rad))
            c.over(metal(c, m, GOLD, sigma=0.5, depth=1.2), m)
    else:
        silk = CF.silk_field(c, 0, 0, S_, S_)
        c.over(silk, ring)
        band_o = rr - (cc - 4)
        band_i = rr - (WINDOW + 8)
        brc, band = CF.brocade_band(c, "fan", band_o, -band_i * -1 + 0 * band_i, period=16.0) if False else (None, None)
        m = smoothstep(c.aa, -c.aa, band_o) * smoothstep(-c.aa, c.aa, band_i)
        c.over(hexc(CF.RARITY["fan"]["brocade"]) * (1 + 0.08 * np.sin((c.X + c.Y) * 2.4))[..., None], m)
        m2 = smoothstep(2.2 + c.aa, 2.2 - c.aa, np.abs(rr - (WINDOW + 2.5)))
        c.over(metal(c, m2, COPPER, sigma=0.6, depth=1.3), m2)
        _ = brc, band
    return c.image()


def ult_tick(style: str, on: bool, full: bool = False) -> Image.Image:
    """燃灯刻度的一格（2 倍，24×14，朝上）：亮的是灯焰色并带一点光，满格时更亮；灭的只是一道暗槽。"""
    W_, H_ = 28, 16
    c = Cv(W_, H_, seed=55, ss=4)
    d = rrect_sd(c.X, c.Y, 5, 4, W_ - 5, H_ - 4, 3.5)
    m = smoothstep(c.aa, -c.aa, d)
    if on:
        glow = np.exp(-np.maximum(d, 0) ** 2 / (2 * (2.6 if full else 1.8) ** 2))
        c.over(hexc("#FFB04A"), glow * (0.85 if full else 0.6))
        col = mixc(hexc("#FFF2C4"), hexc("#FF8A2E"), np.clip(c.Y / H_ * 1.3, 0, 1))
        c.over(col, m)
    else:
        c.over(hexc("#0A0806") if style == "lacquer" else hexc("#3A3530"), m * 0.85)
        rim = smoothstep(0.8 + c.aa, 0.8 - c.aa, np.abs(d + 0.6))
        c.over(hexc("#6E5A36") if style == "lacquer" else hexc("#8A7E6A"), rim * 0.8)
    return c.image()


def level_seal(style: str) -> Image.Image:
    """等级印的底（2 倍 60×60）：朱砂方印，印框留白，字由界面写。"""
    ss = 4
    n = SEAL * 2 * ss
    rng = np.random.default_rng(77)
    Y, X = np.mgrid[0:n, 0:n].astype(np.float64) + 0.5
    cc = n / 2
    wob = 0.012 * n * CF.noise(rng, (n, n), n * 0.07)
    d = np.maximum(np.abs(X - cc), np.abs(Y - cc)) + wob - n * 0.45
    plate = smoothstep(1.5 * ss, -1.5 * ss, d)
    frame = smoothstep(0.9 * ss, 0.0, np.abs(d + n * 0.06))
    ink = 0.88 + 0.08 * CF.noise(rng, (n, n), 6.0 * ss)
    specks = smoothstep(2.2, 2.6, CF.noise(rng, (n, n), 1.3 * ss))
    a = plate * (1 - frame) * np.clip(ink, 0, 1) * (1 - specks)
    lay = CF.V.Layer(n, n)
    lay.over(hexc("#B8321F"), a)
    lay = lay.down(ss)
    rgb, al = lay.straight()
    return CF.V.to_rgba8(rgb, al)


def portrait_disc() -> Image.Image:
    """主角胸像（ui/portrait_hero，256²）只取里面的画（外圈原来的墨框不要），裁成头像窗口大小的圆。"""
    src = Image.open(ART / "out" / "assets@2x" / "portrait" / "portrait_hero.png").convert("RGBA")
    s = src.width
    k = 0.335  # 原图里画面的半径占比（原来的墨圈和橙色弧线都在外面）
    crop = src.crop((int(s * (0.5 - k)), int(s * (0.5 - k)), int(s * (0.5 + k)), int(s * (0.5 + k))))
    D = WINDOW * 2 * 2
    crop = crop.resize((D, D), Image.LANCZOS)
    m = Image.new("L", (D * 4, D * 4), 0)
    ImageDraw.Draw(m).ellipse((0, 0, D * 4 - 1, D * 4 - 1), fill=255)
    m = m.resize((D, D), Image.LANCZOS)
    bg = Image.new("RGBA", (D, D), (24, 26, 34, 255))
    bg.alpha_composite(crop)
    bg.putalpha(m)
    return bg


# ============================================================== 拼一块状态栏

def build_pieces() -> dict:
    t0 = time.perf_counter()
    P = {}
    for st in ("lacquer", "silk"):
        P[(st, "hud_bar_frame")] = bar_frame(st, BAR_W, BAR_H, 101)
        P[(st, "hud_xp_frame")] = bar_frame(st, XP_W, XP_H, 102, ornate=False)
        P[(st, "hud_slot_l")] = slot(st, SLOT_L, False, 103)
        P[(st, "hud_slot_l_empty")] = slot(st, SLOT_L, True, 104)
        P[(st, "hud_slot_s")] = slot(st, SLOT_S, False, 105)
        P[(st, "hud_slot_s_empty")] = slot(st, SLOT_S, True, 106)
        P[(st, "hud_portrait")] = portrait_frame(st)
        P[(st, "hud_ult_tick")] = ult_tick(st, False)
        P[(st, "hud_ult_tick_on")] = ult_tick(st, True)
        P[(st, "hud_ult_tick_full")] = ult_tick(st, True, full=True)
    P[("common", "hud_hp_fill")] = bar_fill("hp", BAR_W - 14, BAR_H - 14, 111)
    P[("common", "hud_hp_trail")] = bar_fill("trail", BAR_W - 14, BAR_H - 14, 112)
    P[("common", "hud_shield_fill")] = bar_fill("shield", BAR_W - 14, (BAR_H - 14) // 2, 113)
    P[("common", "hud_xp_fill")] = bar_fill("xp", XP_W - 8, XP_H - 8, 114)
    P[("common", "hud_level_seal")] = level_seal("lacquer")
    print(f"[hud pieces] {time.perf_counter() - t0:.1f}s")
    return P


SLICES = {"hud_bar_frame": ([48, 0, 48, 0], "大血条框：横向九宫格，两头饰件在切片以内；填充放在里面，四周各留 7（逻辑）"),
          "hud_xp_frame": ([16, 0, 16, 0], "经验条框：横向九宫格；填充四周各留 4"),
          "hud_hp_fill": ([20, 0, 20, 0], "血条填充：宽度按百分比"),
          "hud_hp_trail": ([20, 0, 20, 0], "掉血残影：画在血条填充后面，比血条慢半拍缩回"),
          "hud_shield_fill": ([12, 0, 12, 0], "护盾：叠在血条上半，宽度按护盾值"),
          "hud_xp_fill": ([10, 0, 10, 0], "经验填充：泥金连珠"),
          "hud_slot_l": ([24, 24, 24, 24], "法器格 64²"), "hud_slot_l_empty": ([24, 24, 24, 24], "法器空格：淡框"),
          "hud_slot_s": ([18, 18, 18, 18], "心法格 44²"), "hud_slot_s_empty": ([18, 18, 18, 18], "心法空格：淡框"),
          "hud_portrait": ([0, 0, 0, 0], "头像章：外径 104，窗口 78（逻辑）"),
          "hud_ult_tick": ([0, 0, 0, 0], "燃灯刻度（灭），12 格绕头像，界面旋转摆放"),
          "hud_ult_tick_on": ([0, 0, 0, 0], "燃灯刻度（亮）"), "hud_ult_tick_full": ([0, 0, 0, 0], "燃灯刻度（满格，更亮）"),
          "hud_level_seal": ([0, 0, 0, 0], "等级印底：字由界面写")}


def save_pieces(P: dict):
    for style in ("lacquer", "silk", "common"):
        d = SKIN_OUT / style
        d.mkdir(parents=True, exist_ok=True)
        items = {}
        for (st, name), img in P.items():
            if st != style:
                continue
            img.save(d / f"{name}.png", optimize=True)
            slc, note = SLICES[name]
            items[name] = {"file": f"{name}.png", "size": [img.width, img.height], "slice": slc, "center": "stretch",
                           "sides": "stretch", "note": note}
        lines = ["{", '  "scale": 2,', '  "items": {']
        names = list(items)
        for i, n in enumerate(names):
            lines.append(f"    {json.dumps(n, ensure_ascii=False)}: {json.dumps(items[n], ensure_ascii=False)}" +
                         ("," if i < len(names) - 1 else ""))
        lines += ["  }", "}"]
        (d / "skin.json").write_text("\n".join(lines) + "\n", encoding="utf-8")


def nine(img: Image.Image, name: str, w: float, h: float, k: float) -> Image.Image:
    """按 Bevy TextureSlicer 的规则把件画到 w×h（逻辑）× k（每逻辑像素的屏幕像素）。贴图是 2 倍，所以角按 k/2 缩。"""
    slc = SLICES[name][0]
    W, H = int(round(w * k)), int(round(h * k))
    if slc == [0, 0, 0, 0]:
        return img.resize((W, H), Image.LANCZOS)
    return CF.U.nine_slice(img, slc, W, H, "stretch", "stretch", max_corner_scale=k / 2)


WEAPONS = [("icon_lamp", 3), ("icon_bell", 8), ("icon_sword", 5), None, None, None]
PASSIVES = ["icon_jingxin", "icon_jixing", "icon_hanyi", None, None, None]


def hud_block(style: str, P: dict, k: float, *, hp=(86, 120), trail=0.08, shield=0.22, xp=0.63, ult=8, level=12) -> Image.Image:
    """左上整块状态栏，画到一张透明图上（单位：逻辑像素 × k）。"""
    pc = {name: img for (st, name), img in P.items() if st in (style, "common")}
    W, H = int(640 * k), int(230 * k)
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    lac = style == "lacquer"
    # 头像 + 燃灯刻度 + 等级印
    px0, py0 = 16, 14
    cx, cy = px0 + PORTRAIT / 2, py0 + PORTRAIT / 2
    disc = portrait_disc().resize((int(WINDOW * k), int(WINDOW * k)), Image.LANCZOS)
    paste(im, disc, cx * k, cy * k, center=True)
    paste(im, nine(pc["hud_portrait"], "hud_portrait", PORTRAIT, PORTRAIT, k), cx * k, cy * k, center=True)
    full = ult >= 12
    for i in range(12):
        name = "hud_ult_tick_full" if full else ("hud_ult_tick_on" if i < ult else "hud_ult_tick")
        tk = pc[name].resize((int(17 * k), int(10 * k)), Image.LANCZOS)
        ang = -90 + 30 * i + 15  # 从正上方顺时针
        rad = PORTRAIT / 2 - 8.5
        tk = tk.rotate(-(ang + 90), resample=Image.BICUBIC, expand=True)
        tx = cx + rad * math.cos(math.radians(ang))
        ty = cy + rad * math.sin(math.radians(ang))
        paste(im, tk, tx * k, ty * k, center=True)
    if full:  # 满格：头像窗口里一圈暖光
        g = Image.new("RGBA", (int(PORTRAIT * k), int(PORTRAIT * k)), (0, 0, 0, 0))
        ys, xs = np.mgrid[0:g.height, 0:g.width]
        rr = np.hypot(xs - g.width / 2, ys - g.height / 2) / (k)
        a = np.exp(-((rr - WINDOW / 2) / 5.0) ** 2) * 0.55
        arr = np.zeros((g.height, g.width, 4))
        arr[..., :3] = hexc("#FFB04A") * 255
        arr[..., 3] = a * 255
        paste(im, Image.fromarray(arr.astype(np.uint8), "RGBA"), cx * k, cy * k, center=True)
    seal = pc["hud_level_seal"].resize((int(SEAL * k), int(SEAL * k)), Image.LANCZOS)
    sx, sy = px0 + PORTRAIT - 20, py0 + PORTRAIT - 22
    paste(im, seal, sx * k, sy * k)
    num = plain_text(str(level), 17 * k, "#F6EEDC", kind="brush")
    paste(im, num, (sx + SEAL / 2) * k, (sy + SEAL / 2) * k + 1, center=True)
    # 名字
    bx = px0 + PORTRAIT + 14
    nm = plain_text("提灯人", 16 * k, "#E8DCC0" if lac else "#F2EBDC", shadow="#000000")
    paste(im, nm, bx * k, 10 * k)
    # 血条
    by = 32
    paste(im, nine(pc["hud_bar_frame"], "hud_bar_frame", BAR_W, BAR_H, k), bx * k, by * k)
    inner_w, inner_h = BAR_W - 14, BAR_H - 14
    fx, fy = bx + 7, by + 7
    frac = hp[0] / hp[1]
    tr = nine(pc["hud_hp_trail"], "hud_hp_trail", inner_w * min(1.0, frac + trail), inner_h, k)
    paste(im, tr, fx * k, fy * k)
    hpf = nine(pc["hud_hp_fill"], "hud_hp_fill", inner_w * frac, inner_h, k)
    paste(im, hpf, fx * k, fy * k)
    if shield > 0:
        sh = nine(pc["hud_shield_fill"], "hud_shield_fill", inner_w * shield, inner_h / 2, k)
        paste(im, sh, fx * k, fy * k)
    txt = plain_text(f"{hp[0]} / {hp[1]}", 17 * k, "#FFF6E8", shadow="#000000")
    paste(im, txt, (fx + inner_w - 10) * k - txt.width, (by + BAR_H / 2) * k - txt.height / 2)
    # 经验条
    xy = by + BAR_H + 6
    paste(im, nine(pc["hud_xp_frame"], "hud_xp_frame", XP_W, XP_H, k), bx * k, xy * k)
    xpf = nine(pc["hud_xp_fill"], "hud_xp_fill", (XP_W - 8) * xp, XP_H - 8, k)
    paste(im, xpf, (bx + 4) * k, (xy + 4) * k)
    # 法器格（底边一排等级点）
    wy = xy + XP_H + 10
    for i, w_ in enumerate(WEAPONS):
        x = bx + i * (SLOT_L + 8)
        if w_ is None:
            paste(im, nine(pc["hud_slot_l_empty"], "hud_slot_l_empty", SLOT_L, SLOT_L, k), x * k, wy * k)
            continue
        paste(im, nine(pc["hud_slot_l"], "hud_slot_l", SLOT_L, SLOT_L, k), x * k, wy * k)
        icon, lv = w_
        ic = Image.open(UI_ICONS / f"{icon}.png").convert("RGBA").resize((int(46 * k), int(46 * k)), Image.LANCZOS)
        paste(im, ic, (x + SLOT_L / 2) * k, (wy + SLOT_L / 2 - 4) * k, center=True)
        dots = CF.level_dots(style, lv, 8).resize((int(44 * k), int(5.5 * k)), Image.LANCZOS)
        paste(im, dots, (x + SLOT_L / 2) * k, (wy + SLOT_L - 7) * k, center=True)
    # 心法格
    sy2 = wy + SLOT_L + 8
    for i, ps in enumerate(PASSIVES):
        x = bx + i * (SLOT_S + 6)
        name = "hud_slot_s" if ps else "hud_slot_s_empty"
        paste(im, nine(pc[name], name, SLOT_S, SLOT_S, k), x * k, sy2 * k)
        if ps:
            ic = Image.open(UI_ICONS / f"{ps}.png").convert("RGBA").resize((int(34 * k), int(34 * k)), Image.LANCZOS)
            paste(im, ic, (x + SLOT_S / 2) * k, (sy2 + SLOT_S / 2) * k, center=True)
    return im


def hud_screen(style: str, P: dict) -> Image.Image:
    k = 1.5
    scr = CF.game_backdrop()
    paste(scr, hud_block(style, P, k), 0, 0)
    # 顶部正中的计时、右上的五行计数、左下的按键提示：只为示意不冲突，简画
    clock = plain_text("12:34", 28 * k, "#F2EBDC", shadow="#000000")
    paste(scr, clock, 960, 14 * k + clock.height / 2, center=True)
    els = [("金", 1, "#E2B23A"), ("木", 3, "#82A489"), ("水", 2, "#6B8EAB"), ("火", 3, "#EA7841"), ("土", 0, "#BE884E")]
    x = 1920 - 16 * k
    for ch, n, colr in reversed(els):
        t = plain_text(f"{ch} {n}", 15 * k, colr if n else "#6A6458", shadow="#000000")
        x -= t.width + 10 * k
        paste(scr, t, x, 18 * k)
    hint = plain_text("WASD 移动　空格 闪避　Q 燃灯　Esc 暂停", 16 * k, "#9C9384", shadow="#000000")
    paste(scr, hint, 16 * k, 1080 - 16 * k - hint.height)
    return scr.convert("RGB")


def zoom_sheet(P: dict) -> Image.Image:
    """左上这一块按贴图原尺寸（每逻辑像素 2 像素）：上漆下绢，右边加一张燃灯满格的头像。"""
    k = 2.0
    blocks = [hud_block(st, P, k) for st in ("lacquer", "silk")]
    fulls = [hud_block(st, P, k, ult=12).crop((0, 0, int(140 * k), int(140 * k))) for st in ("lacquer", "silk")]
    W_ = blocks[0].width + fulls[0].width + 60
    H_ = blocks[0].height * 2 + 120
    bg = CF.game_backdrop((W_, H_))
    for i, (b, f) in enumerate(zip(blocks, fulls)):
        y = 50 + i * (b.height + 40)
        paste(bg, plain_text(("黑漆描金", "绢本织锦")[i], 30, "#E6DCC6", shadow="#000000"), 30, y - 40)
        paste(bg, b, 10, y)
        paste(bg, f, b.width + 40, y)
        paste(bg, plain_text("燃灯满格", 24, "#E6DCC6", shadow="#000000"), b.width + 40 + f.width / 2, y + f.height + 18, center=True)
    return bg.convert("RGB")


def main() -> int:
    P = build_pieces()
    save_pieces(P)
    for st in ("lacquer", "silk"):
        hud_screen(st, P).save(REVIEW / f"hud_sample_{st}.png", optimize=True)
    zoom_sheet(P).save(REVIEW / "hud_sample_zoom.png", optimize=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
