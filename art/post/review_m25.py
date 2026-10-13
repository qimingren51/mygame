#!/usr/bin/env python3
"""提灯夜行 · M2.5 新素材的检查图（读盘，不重新生成）。

  art/out/review[@2x]/m25_additions.png
    上半：全部 M2.5 界面图标与五行反应印——原大（1 倍放大 2×，2 倍 1×）+ 32 + 24 像素（印章 48 / 28 像素宽），
          左半纸色底、右半夜色底 #161B2C，每组前面放几个原有的图标作对照；
    下半：游戏比例（1 贴图像素 = 1 画面像素）的地面场景，左白天（宣纸、不打光）、右夜里（世界 × 光照图 + 自发光叠加）：
          金币挨着一颗魂火、放大 4 倍的金币，染红的扇形预警（蓄力到六成）与冲锋预警（长 200 世界单位），
          熔岩、淤泥、灵草按反应的半径摆在纸上。

先跑 vfx_textures.py、weapon_textures.py、ui_icons.py（同一密度），再跑本脚本：
  LANTERN_ART_DENSITY=2 art/.venv/bin/python art/post/review_m25.py
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import review_additions as R  # noqa: E402
import vfx_textures as V  # noqa: E402
import weapon_textures as W  # noqa: E402

S, D, col = V.S, V.D, V.col
NIGHT = col(S.NIGHT_AMBIENT)
SECTOR_RED = "#FF4A3A"
LAVA_TINT, HERB_TINT = "#FF7A2A", "#9CF0B8"
# 反应的半径（世界单位，assets/data/elements.ron）：熔岩 50、淤泥 70、灵草（滋生）50
ZONE_RADIUS = {"zone_lava": 50.0, "zone_mud": 70.0, "zone_herb": 50.0}


def icon_groups(um: dict) -> list[tuple[str, list[str], list[str], int]]:
    """[(标题, 新图标, 对照的原有图标, 每行几个)]"""
    def kind(*ks, new=True):
        return [n for n in um if um[n]["kind"] in ks and (n in M25) == new]

    return [
        ("心法（M2.5 新增 7 门；五行色弧，无属性的是中性弧）", kind("passive"), kind("passive", new=False), 4),
        ("夜签（朱砂双圈）、货币、奇遇", kind("omen") + kind("currency") + kind("encounter"), ["icon_omen_bloodmoon", "icon_omen_quiet", "icon_omen_element", "icon_oil", "icon_lotus", "icon_enc_toad"], 4),
        ("灯驿人物 icon_hub_0..3（暖的中性弧）", kind("hub"), ["icon_enc_merchant"], 4),
        ("灯坠（红绳圈 + 顶上中国结，挂在灯上的坠子）", kind("charm"), ["icon_sword", "icon_bell"], 4),
        ("精英词缀（小图标，原大 1 倍 32 / 2 倍 64 像素，朱砂弧；要在 24 像素认得出）", kind("affix"), ["icon_kills"], 6),
        ("五行反应印（朱白相间的圆角方印、双边栏，上下两字；前五相生、后五相克）", [n for n in um if n.startswith("seal_react_")], ["seal_fen", "seal_rui", "seal_tian"], 5),
    ]


M25: set[str] = set()


def sheet_icons(um: dict, f_lab, f_title):
    """上半张：图标与印章。返回 (画布, 文字列表)。"""
    k = 2 / D
    pad, lab_h, title_h, gap = 16, 20, 30, 12
    groups = icon_groups(um)
    ims = {n: R.load("ui", n) for g in groups for n in g[1] + g[2]}

    def cell_size(n):
        im = ims[n]
        seal = um[n]["kind"] == "seal"
        smalls = (48, 28) if seal else (32, 24)
        kk = k
        w = int(im.width * kk) + sum(s + 8 for s in smalls) + 10
        return max(w, 240), int(im.height * kk) + lab_h + gap, smalls, kk

    col_w = 16 + max(sum(cell_size(n)[0] for n in g[1][i : i + c]) for g in groups for c in [g[3]] for i in range(0, len(g[1]), c))
    half = pad + col_w + pad
    layout, y = [], 0
    for title, ns, refs, c in groups:
        layout.append(("title", title, y))
        y += title_h
        if refs:
            layout.append(("refs", refs, y))
            y += 32 + 22
        for i in range(0, len(ns), c):
            x, rh = pad, 0
            for n in ns[i : i + c]:
                w, h, smalls, kk = cell_size(n)
                layout.append(("cell", n, x, y, smalls, kk))
                x += w
                rh = max(rh, h)
            y += rh
    H = y + pad
    canvas = np.zeros((H, 2 * half, 3))
    canvas[:, :half] = W.PAPER
    canvas[:, half:] = NIGHT
    texts = []
    for item in layout:
        if item[0] == "title":
            for side in (0, 1):
                texts.append((side * half + pad, item[2] + 8, item[1], side, f_title))
            continue
        if item[0] == "refs":
            for side in (0, 1):
                x = side * half + pad
                texts.append((x, item[2] + 8, "原有的（32 像素）：", side, f_lab))
                x += 130
                for n in item[1]:
                    im = ims[n]
                    s = 32 if um[n]["kind"] != "seal" else 40
                    R.paste(canvas, im, x, item[2] + 2, scale=s / im.width)
                    x += s + 10
            continue
        _, n, x, y0, smalls, kk = item
        im, e = ims[n], um[n]
        lab = e["name"] + "  " + n.replace("icon_", "").replace("seal_", "")
        for side in (0, 1):
            xx = side * half + x
            R.paste(canvas, im, xx, y0 + lab_h, scale=kk)
            sx = xx + int(im.width * kk) + 8
            for s in smalls:
                R.paste(canvas, im, sx, y0 + lab_h, scale=s / im.width)
                sx += s + 8
            texts.append((xx, y0 + 2, lab, side, f_lab))
    return canvas, texts


def scene(f_lab):
    """下半张：游戏比例的地面场景（左白天、右夜里）。返回 (画布, 文字列表)。坐标按 1 倍像素写，乘 D 落到画布上。"""
    Wm, Hm = V.dpx(1000), V.dpx(560)
    paper = np.asarray(Image.open(V.ASSETS / "ground" / "paper.png").convert("RGB"), dtype=np.float64) / 255.0
    base = np.tile(paper, (Hm // paper.shape[0] + 1, Wm // paper.shape[1] + 1, 1))[:Hm, :Wm].copy()
    gm, wm, vm = R.meta("ground"), R.meta("weapons"), R.meta("vfx")
    G = {n: R.load("ground", n) for n in ("zone_lava", "zone_lava_glow", "zone_mud", "zone_herb", "zone_herb_glow")}
    sec, sec_fill = R.load("weapons", "sector"), R.load("weapons", "sector_fill")
    cl, cl_head = R.load("weapons", "charge_line"), R.load("weapons", "charge_line_head")
    coin, coin_emit, gem, shadow, light = (R.load("vfx", n) for n in ("coin", "coin_emit", "gem_1", "shadow", "light"))
    hero, hero_k = R.optional_prop("hero")

    def put(canvas, img, x, y, **kw):
        W.place(canvas, img, x * D, y * D, **kw)

    def zk(n):  # 区域按反应半径缩放：横向半径 radius_px 对到 半径 × px_per_unit
        return ZONE_RADIUS[n] * S.PX_PER_UNIT / gm[n]["radius_px"]

    zones = [("zone_lava", 170, 150), ("zone_mud", 470, 160), ("zone_herb", 800, 150)]
    sx, sy, s_rad = 560, 360, 80.0  # 扇形：顶点、半径（世界单位）
    s_scale = s_rad * S.PX_PER_UNIT / wm["sector"]["radius_px"]
    s_ang = math.radians(-12.0)
    coins = [(150, 420), (175, 432), (200, 418)]
    cx0, cy0, c_len, c_ang = 300, 505, 200.0, math.radians(-4.0)  # 冲锋预警：起点、长度（世界单位）、方向

    def world(canvas):
        for n, x, y in zones:
            put(canvas, G[n], x, y, anchor=tuple(gm[n]["anchor"]), scale=zk(n))
        for x, y in coins:
            put(canvas, coin, x, y, anchor=tuple(vm["coin"]["anchor"]))
        if hero is not None:
            put(canvas, shadow, sx - 30, sy, scale=1.0)
            put(canvas, hero, sx - 30, sy, anchor=(0.5, 0.875), scale=hero_k)

    def fx(canvas, mode):
        red = col(SECTOR_RED)
        al = 1.0 if mode == "add" else 0.55
        put(canvas, sec, sx, sy, anchor=tuple(wm["sector"]["anchor"]), angle=s_ang, scale=s_scale, mode=mode, tint=red, alpha=al)
        put(canvas, sec_fill, sx, sy, anchor=tuple(wm["sector_fill"]["anchor"]), angle=s_ang, scale=s_scale * 0.6, mode=mode, tint=red * 0.85, alpha=al)
        # 冲锋预警：车道拉到“长度 − 箭头长”，箭头接在末端（坐标按 1 倍像素，长度换成当前密度的像素再除回去）
        body_px = c_len * S.PX_PER_UNIT - wm["charge_line_head"]["head_len_px"]
        put(canvas, cl, cx0, cy0, anchor=tuple(wm["charge_line"]["anchor"]), angle=c_ang, scale=(body_px / cl.width, 1.0), mode=mode, tint=red, alpha=al)
        ex, ey = cx0 + body_px / D * math.cos(c_ang), cy0 + body_px / D * math.sin(c_ang)
        put(canvas, cl_head, ex, ey, anchor=tuple(wm["charge_line_head"]["anchor"]), angle=c_ang, mode=mode, tint=red, alpha=al)
        if mode == "add":
            put(canvas, G["zone_lava_glow"], 170, 150, anchor=tuple(gm["zone_lava_glow"]["anchor"]), scale=zk("zone_lava"), mode="add", tint=col(LAVA_TINT))
            put(canvas, G["zone_herb_glow"], 800, 150, anchor=tuple(gm["zone_herb_glow"]["anchor"]), scale=zk("zone_herb"), mode="add", tint=col(HERB_TINT))
            for x, y in coins:
                put(canvas, coin_emit, x, y, anchor=tuple(vm["coin_emit"]["anchor"]), mode="add")
        put(canvas, gem, 245, 425, mode=mode, tint=col(S.SOUL_LIGHT))

    day = base.copy()
    world(day)
    fx(day, "over")
    night_w = base.copy()
    world(night_w)
    lm = np.broadcast_to(NIGHT, night_w.shape).copy()
    put(lm, light, sx - 30, sy - 40, scale=520 * D / light.width, mode="add", tint=col(S.LANTERN_LIGHT))
    put(lm, light, 170, 150, scale=300 * D / light.width, mode="add", tint=col(LAVA_TINT) * 0.6)
    night = night_w * np.clip(lm, 0, 1)
    fx(night, "add")
    # 放大 4 倍的金币（最近邻，看真实像素），白天的贴在左下角
    for cv, dark in ((day, False), (night, True)):
        zoom = np.broadcast_to(W.PAPER, (coin.height * 4 + 8, coin.width * 4 + 8, 3)).copy()
        V.composite(zoom, coin, 4, 4, "over", scale=4)
        if dark:  # 夜里：纸和金币一起乘环境光，再叠自发光
            zoom = zoom * NIGHT
            V.composite(zoom, coin_emit, 4, 4, "add", scale=4)
        y0, x0 = Hm - zoom.shape[0] - V.dpx(8), V.dpx(20)
        cv[y0 : y0 + zoom.shape[0], x0 : x0 + zoom.shape[1]] = zoom
    gap, top = 12, V.dpx(26)
    out = np.ones((Hm + top, Wm * 2 + gap, 3)) * 0.1
    out[top:, :Wm] = np.clip(day, 0, 1)
    out[top:, Wm + gap :] = np.clip(night, 0, 1)
    texts = [
        (8, 6, f"白天：宣纸、不打光（密度 {D:g} 倍，1 贴图像素 = {1 / S.PX_PER_UNIT:g} 世界单位）；扇形染 {SECTOR_RED} 按正常混合只看形状", 2, f_lab),
        (Wm + gap + 8, 6, f"夜里：世界 × 光照图，扇形 / 熔岩光 {LAVA_TINT} / 灵草光 {HERB_TINT} / 金币自发光 / 魂火叠加", 2, f_lab),
    ]
    for ox, side in ((0, 2), (Wm + gap, 3)):
        for (n, x, y) in zones:
            texts.append((ox + int((x - 60) * D), top + int((y + 95) * D), f"{n}（半径 {ZONE_RADIUS[n]:g}）", side, f_lab))
        texts.append((ox + int(130 * D), top + int(380 * D), "金币 ×3、魂火 gem_1", side, f_lab))
        texts.append((ox + int(20 * D), top + Hm - (coin.height * 4 + 8) - V.dpx(8) - V.dpx(16), "金币 ×4（最近邻放大）", side, f_lab))
        texts.append((ox + int((sx + 20) * D), top + int((sy + 70) * D), f"扇形预警（半径 {s_rad:g}，蓄力六成）", side, f_lab))
        texts.append((ox + int(cx0 * D), top + int((cy0 + 14) * D), f"冲锋预警 charge_line + charge_line_head（长 {c_len:g}）", side, f_lab))
    return out, texts


def main() -> None:
    from ui_fonts import font  # noqa: PLC0415
    import ui_icons_m25  # noqa: PLC0415

    M25.update(f for f, *_ in ui_icons_m25.specs())
    um = R.meta("ui")
    f_lab, f_title = font("serif", 13), font("serif", 16, weight=600)
    top, t_top = sheet_icons(um, f_lab, f_title)
    bot, t_bot = scene(font("serif", max(12, int(7 * D))))
    Wt = max(top.shape[1], bot.shape[1])
    canvas = np.ones((top.shape[0] + bot.shape[0] + 40, Wt, 3)) * 0.1
    canvas[: top.shape[0], : top.shape[1]] = top
    y_bot = top.shape[0] + 40
    canvas[y_bot:, : bot.shape[1]] = bot
    img = Image.fromarray(np.round(np.clip(canvas, 0, 1) * 255).astype(np.uint8), "RGB")
    dr = ImageDraw.Draw(img)
    for x, y, text, side, f in t_top:
        dr.text((x, y), text, fill=S.INK["nong"] if side == 0 else "#D8D2C4", font=f)
    dr.text((16, top.shape[0] + 10), "游戏比例的地面场景", fill="#DDDDDD", font=f_title)
    for x, y, text, side, f in t_bot:
        dr.text((x, y_bot + y), text, fill="#DDDDDD" if (y < 30 or side == 3) else S.INK["jiao"], font=f)
    out = V.REVIEW_DIR / "m25_additions.png"
    V.save_png(img, out)
    print("写出", out)


if __name__ == "__main__":
    main()
