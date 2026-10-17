"""1080p 审图（黑漆描金定稿件）：状态栏 + 升级三选一 + 属性格。

一律按游戏的逻辑尺寸 1:1 画（1080p、100% 缩放下逻辑像素 = 物理像素），九宫格按 Bevy 的规则（角 ×0.5）。
卡片先按 2 倍（600×920，和贴图同大）排好再缩一半，等于游戏里把 2 倍贴图画到 300×460。
文字用纯色（Bevy 的字没有渐变），颜色是建议值：卡上的字改成纸色 / 淡金。

在仓库根目录运行：art/.venv/bin/python <本文件> [输出路径]
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, "art/post")
import card_frames as CF  # noqa: E402
import ui_skin as U  # noqa: E402
import ui_lacquer as LQ  # noqa: E402

SKIN = Path("art/out/skin")
MAN = json.loads((SKIN / "skin.json").read_text(encoding="utf-8"))["items"]
ICONS = Path("art/out/assets@2x/ui")
STATS = Path("art/out/assets@2x/ui_stats")
REVIEW = Path("art/out/review@2x")
paste, plain, hexc = CF.paste, CF.plain_text, CF.hexc

PAPER = "#EDE4CF"
DIM = "#A79C86"
FOOT = "#8E8066"
_cache: dict = {}


def piece(name: str) -> Image.Image:
    if name not in _cache:
        _cache[name] = Image.open(SKIN / MAN[name]["file"]).convert("RGBA")
    return _cache[name]


def nine(name: str, w: float, h: float, k: float = 1.0) -> Image.Image:
    """把皮肤件画到 w×h（逻辑）× k；k=1 是 1080p，k=2 是贴图原尺寸。"""
    it = MAN[name]
    W, H = int(round(w * k)), int(round(h * k))
    if it["slice"] == [0, 0, 0, 0]:
        return piece(name).resize((W, H), Image.LANCZOS)
    return U.nine_slice(piece(name), it["slice"], W, H, it["center"], it["sides"], max_corner_scale=0.5 * k)


def icon(name: str, size: float, folder: Path = ICONS, alpha: float = 1.0) -> Image.Image:
    im = Image.open(folder / f"{name}.png").convert("RGBA").resize((int(round(size)), int(round(size))), Image.LANCZOS)
    return CF.fade(im, alpha) if alpha < 1 else im


# ============================================================== 卡片（2 倍排版，再缩一半）

RARITY_NAME = {"fan": "凡品", "ling": "灵品", "xuan": "玄品", "tian": "天品", "yi": "异化", "he": "合璧"}
RARITY_COL = {"fan": "#A9AEC2", "ling": "#6FB8FF", "xuan": "#B07CF0", "tian": "#FFD98A", "yi": "#CF8CDB", "he": "#F6BD62"}
EL_COL = {"wood": "#82A489", "fire": "#EA7841", "water": "#6B8EAB", "metal": "#E2B23A", "earth": "#BE884E"}

CARDS = [
    dict(art="jixing", name="疾行", gain="移动速度 +8%", stat="speed", el="wood", rarity="fan", lv=(3, 5), kind="心法",
         note=("木 2 → 3", None), pair=None, caption="移动速度 +8%。风属木：脚下生风，妖就追不上。"),
    dict(art="lamp", name="灯火", gain="火环绕身，烧近身妖", stat=None, el="fire", rarity="ling", lv=(1, 8), kind="新法器",
         note=("火 1 → 2", None), pair=("icon_changming", False), caption="火焰环绕周身，烧灼靠近的妖物。\n进化需心法「长明」"),
    dict(art="bell_evo", name="寒山钟", gain="每 6 秒全屏冻结", stat=None, el="water", rarity="tian", lv=None, kind="进化",
         note=("选择后立即进化", "#FFD98A"), pair=("icon_jingxin", True), caption="每 6 秒钟鸣全屏，冻结所有妖物。"),
]


def card_face(card: dict, index: int) -> Image.Image:
    """按 choice.rs 的排法：内边距 16（底 20）；插画 268×201 圆角 6；五行印 34、品阶签贴插画两角（各缩 8）；
    卡名 30 / 收益 22 / 等级点 10 / 提示 15 在插画和页脚之间居中；页脚高 30：类别（左）、配对图标 + 按键（右）。"""
    k = 2
    W, H = 300 * k, 460 * k
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    im.alpha_composite(nine(f"card_{card['rarity']}", 300, 460, k))
    ax0, ay0, aw, ah = 16 * k, 16 * k, 268 * k, 201 * k
    art = Image.open(REVIEW / f"card_art_{card['art']}.png").convert("RGBA").resize((aw, ah), Image.LANCZOS)
    im.alpha_composite(CF.rounded(art, 6 * k), (ax0, ay0))
    paste(im, icon(f"icon_el_{card['el']}", 34 * k), ax0 + 8 * k, ay0 + 8 * k)
    tag_t = plain(RARITY_NAME[card["rarity"]], 12 * k, RARITY_COL[card["rarity"]])
    tw, th = tag_t.width + 2 * 10 * k - 16, 12 * k * 1.25 + 2 * 3 * k
    tag = nine("chip_dark", tw / k, th / k, k)
    tx = ax0 + aw - 8 * k - tag.width
    paste(im, tag, tx, ay0 + 8 * k)
    paste(im, tag_t, tx + tag.width / 2, ay0 + 8 * k + tag.height / 2, center=True)
    # 正文
    rows = [(plain(card["name"], 30 * k, PAPER, kind="brush", shadow="#000000"), 0)]
    gcol = "#%02X%02X%02X" % tuple(int(v * 255) for v in CF.mixc(hexc(EL_COL[card["el"]]), hexc("#F2E8D2"), 0.45))
    g = plain(card["gain"], 22 * k, gcol, kind="serif" if "%" in card["gain"] else "brush", shadow="#000000")
    if card["stat"]:  # 数值类收益：前面放 32 的数值图标
        st = icon(f"stat_{card['stat']}", 32 * k, STATS)
        row = Image.new("RGBA", (st.width + 8 * k + g.width, max(st.height, g.height)), (0, 0, 0, 0))
        paste(row, st, 0, (row.height - st.height) / 2)
        paste(row, g, st.width + 8 * k, (row.height - g.height) / 2)
        g = row
    rows.append((g, 2 * k))
    if card["lv"]:
        cur, mx = card["lv"]
        dots = Image.new("RGBA", (mx * 10 * k + (mx - 1) * 6 * k, 10 * k), (0, 0, 0, 0))
        for i in range(mx):
            paste(dots, nine("pip_on" if i < cur else "pip", 10, 10, k), i * 16 * k, 0)
        rows.append((dots, 10 * k))
    if card["note"]:
        t, col = card["note"]
        rows.append((plain(t, 15 * k, col or DIM, shadow="#000000"), 6 * k))
    foot_top = H - 20 * k - 30 * k
    body_top = ay0 + ah
    total = sum(r.height + gap for r, gap in rows)
    y = body_top + (foot_top - body_top - total) / 2
    for r, gap in rows:
        y += gap
        paste(im, r, W / 2 - r.width / 2, y)
        y += r.height
    # 页脚
    fy = foot_top + 15 * k
    lab = plain(card["kind"], 12 * k, FOOT)
    paste(im, lab, 16 * k + 10 * k, fy - lab.height / 2)
    kc = CF.keycap("lacquer", str(index + 1), 22 * k)
    xr = W - 16 * k - 10 * k
    paste(im, kc, xr - kc.width, fy - kc.height / 2)
    if card["pair"]:
        name, owned = card["pair"]
        paste(im, icon(name, 30 * k, alpha=1.0 if owned else 0.5), xr - kc.width - 8 * k - 30 * k, fy - 15 * k)
    return im.resize((300, 460), Image.LANCZOS)


# ============================================================== 状态栏（逻辑 1:1）

PORTRAIT, WINDOW = 104, 78


def portrait_disc(d: int) -> Image.Image:
    src = Image.open("art/out/assets@2x/portrait/portrait_hero.png").convert("RGBA")
    s, kk = src.width, 0.335
    crop = src.crop((int(s * (0.5 - kk)), int(s * (0.5 - kk)), int(s * (0.5 + kk)), int(s * (0.5 + kk))))
    crop = crop.resize((d * 4, d * 4), Image.LANCZOS)
    bg = Image.new("RGBA", (d * 4, d * 4), (24, 26, 34, 255))
    bg.alpha_composite(crop)
    m = Image.new("L", (d * 4, d * 4), 0)
    from PIL import ImageDraw

    ImageDraw.Draw(m).ellipse((0, 0, d * 4 - 1, d * 4 - 1), fill=255)
    bg.putalpha(m)
    return bg.resize((d, d), Image.LANCZOS)


def hud(scr: Image.Image, *, hp=(86, 120), trail=0.08, shield=0.22, xp=0.63, ult=8, level=12, x0=16, y0=14):
    cx, cy = x0 + PORTRAIT / 2, y0 + PORTRAIT / 2
    paste(scr, portrait_disc(WINDOW + 2), cx, cy, center=True)
    paste(scr, nine("hud_portrait", PORTRAIT, PORTRAIT), cx, cy, center=True)
    for i in range(12):
        name = "hud_ult_tick_full" if ult >= 12 else ("hud_ult_tick_on" if i < ult else "hud_ult_tick")
        tk = nine(name, 17, 10, 4).rotate(-(30 * i + 15), resample=Image.BICUBIC, expand=True)
        tk = tk.resize((max(1, round(tk.width / 4)), max(1, round(tk.height / 4))), Image.LANCZOS)
        ang = math.radians(-90 + 30 * i + 15)
        r = PORTRAIT / 2 - 8.5
        paste(scr, tk, cx + r * math.cos(ang), cy + r * math.sin(ang), center=True)
    sx, sy = x0 + PORTRAIT - 22, y0 + PORTRAIT - 24
    paste(scr, nine("hud_level_seal", 30, 30), sx, sy)
    paste(scr, plain(str(level), 17, "#F6EEDC", kind="brush"), sx + 15, sy + 15, center=True)
    bx, by = x0 + PORTRAIT + 14, y0 + 6
    paste(scr, nine("hud_hp_track", 460, 30), bx, by)
    iw, ih = 460 - 14, 30 - 14
    frac = hp[0] / hp[1]
    paste(scr, nine("bar_fill_trail", iw * min(1, frac + trail), ih), bx + 7, by + 7)
    paste(scr, nine("bar_fill_hp", iw * frac, ih), bx + 7, by + 7)
    paste(scr, nine("bar_fill_shield", iw * shield, ih / 2), bx + 7, by + 7)
    t = plain(f"{hp[0]} / {hp[1]}", 15, "#FFF6E8", shadow="#000000")
    paste(scr, t, bx + 7 + iw - 8 - t.width, by + 15 - t.height / 2)
    xy = by + 30 + 6
    paste(scr, nine("hud_xp_track", 460, 10), bx, xy)
    paste(scr, nine("bar_fill_xp", (460 - 4) * xp, 6), bx + 2, xy + 2)
    wy = xy + 10 + 10
    weapons = [("icon_lamp", "3", "slot_l"), ("icon_bell_evo", "★", "slot_l_evo"), ("icon_sword", "5", "slot_l"), None, None, None]
    for i, w in enumerate(weapons):
        x = bx + i * (64 + 8)
        if w is None:
            paste(scr, nine("slot_l_empty", 64, 64), x, wy)
            continue
        ic, lv, sk = w
        paste(scr, nine(sk, 64, 64), x, wy)
        paste(scr, icon(ic, 50), x + 32, wy + 32, center=True)
        paste(scr, plain(lv, 12, "#FFD98A" if sk == "slot_l_evo" else PAPER, shadow="#000000"), x + 32, wy + 64 + 8, center=True)
    py = wy + 64 + 18
    passives = ["icon_jingxin", "icon_jixing", "icon_hanyi", "icon_changming", None, None]
    for i, p in enumerate(passives):
        x = bx + i * (44 + 6)
        paste(scr, nine("slot_s" if p else "slot_s_empty", 44, 44), x, py)
        if p:
            paste(scr, icon(p, 34), x + 22, py + 22, center=True)
            paste(scr, plain(str([2, 3, 1, 1][i]), 11, PAPER, shadow="#000000"), x + 22, py + 44 + 7, center=True)


def chips(scr: Image.Image):
    """右上五行计数：chip_dark + 五行色字。"""
    els = [("金", 1, "metal"), ("木", 3, "wood"), ("水", 2, "water"), ("火", 3, "fire"), ("土", 0, "earth")]
    x = 1920 - 16
    for ch, n, el in reversed(els):
        t = plain(f"{ch} {n}", 15, EL_COL[el] if n else "#6A6458", shadow="#000000")
        w = t.width + 12
        x -= w
        paste(scr, nine("chip_dark", w, 26), x, 16)
        paste(scr, t, x + w / 2, 16 + 13, center=True)
        x -= 6


# ============================================================== 属性格（20 像素图标）

STAT_ROWS = [("health", "生命", "120"), ("armor", "护甲", "2"), ("reduction", "减伤", "8%"), ("regen", "回复", "0.4/秒"),
             ("speed", "移速", "+16%"), ("damage", "伤害", "+20%"), ("cooldown", "冷却", "-10%"), ("area", "范围", "+15%"),
             ("count", "数量", "+1"), ("crit", "暴击", "8%"), ("crit_dmg", "暴伤", "150%"), ("magnet", "拾取", "+30%")]
GROUPS = [("base", "基础"), ("output", "输出"), ("survival", "生存"), ("lamp", "灯"), ("build", "构筑"), ("night", "夜"),
          ("weapons", "法器")]


def stat_panel(scr: Image.Image, x0: int, y0: int):
    w, h = 300, 330
    paste(scr, nine("panel_dark", w, h), x0, y0)
    paste(scr, plain("属性（图标 20）", 15, DIM), x0 + 18, y0 + 14)
    for i, (key, name, val) in enumerate(STAT_ROWS):
        col, row = i % 2, i // 2
        x, y = x0 + 18 + col * 140, y0 + 46 + row * 30
        paste(scr, icon(f"stat_{key}", 20, STATS), x, y)
        paste(scr, plain(name, 14, PAPER), x + 26, y + 10 - 9)
        v = plain(val, 14, "#E8C77A")
        paste(scr, v, x + 126 - v.width, y + 10 - 9)
    gy = y0 + 46 + 6 * 30 + 12
    paste(scr, plain("分组", 13, DIM), x0 + 18, gy)
    for i, (key, name) in enumerate(GROUPS):
        x = x0 + 18 + i * 38
        paste(scr, icon(f"stat_group_{key}", 20, STATS), x + 6, gy + 24)
        paste(scr, plain(name, 11, DIM), x + 16, gy + 54, center=True)


def main(out: str) -> None:
    scr = CF.game_backdrop()
    hud(scr)
    clock = plain("08:24", 28, "#F2EBDC", kind="serif", shadow="#000000")
    paste(scr, clock, 960, 14 + clock.height / 2, center=True)
    chips(scr)
    # 升级页
    y = 70
    paste(scr, plain("升级", 48, "#E9DFC7", kind="brush", shadow="#000000"), 960, y + 24, center=True)
    paste(scr, plain("Lv 12 → 13", 18, DIM, shadow="#000000"), 960, y + 66, center=True)
    x0 = 960 - (3 * 300 + 2 * 20) / 2
    cy = 190
    for i, c in enumerate(CARDS):
        paste(scr, card_face(c, i), x0 + i * 320, cy)
    paste(scr, nine("card_focus", 312, 472), x0 + 320 - 6, cy - 6)
    cap = CARDS[1]["caption"].split("\n")
    for j, line in enumerate(cap):
        paste(scr, plain(line, 16, "#E9E2D2" if j == 0 else "#C9B98F", shadow="#000000"), 960, cy + 460 + 28 + j * 24, center=True)
    paste(scr, plain("← → 选择　↑ ↓ 切换卡片与操作　空格 确定", 15, "#8E8576", shadow="#000000"), 960, cy + 460 + 92, center=True)
    labels = ["重抽（剩 2 次）", "封印第 1 项（剩 1 次）", "跳过（灯油 +10）"]
    bw, bh, gap = 240, 46, 16
    bx = 960 - (3 * bw + 2 * gap) / 2
    for j, lab in enumerate(labels):
        paste(scr, nine("btn", bw, bh), bx + j * (bw + gap), cy + 460 + 118)
        paste(scr, plain(lab, 16, PAPER), bx + j * (bw + gap) + bw / 2, cy + 460 + 118 + bh / 2, center=True)
    # 右边：属性格；左边：另外三种品阶的卡框（空卡，标名字）
    stat_panel(scr, 1920 - 16 - 300, 300)
    for j, r in enumerate(("xuan", "yi", "he")):
        x, yy = 16 + j * 152, 300
        mini = nine(f"card_{r}", 300, 460).resize((140, 215), Image.LANCZOS)
        paste(scr, mini, x, yy)
        paste(scr, plain(RARITY_NAME[r], 15, RARITY_COL[r], shadow="#000000"), x + 70, yy + 108, center=True)
    paste(scr, plain("另外三种卡框（缩小到 47%）", 13, DIM, shadow="#000000"), 16, 300 + 222)
    # 底下：19 个数值图标，32（卡片）和 20（属性格）
    keys = [k for k, *_ in STAT_ROWS] + [f"group_{g}" for g, _ in GROUPS]
    sx = 960 - (len(keys) * 44) / 2
    for i, key in enumerate(keys):
        paste(scr, icon(f"stat_{key}", 32, STATS), sx + i * 44 + 6, 960)
        paste(scr, icon(f"stat_{key}", 20, STATS), sx + i * 44 + 12, 1000)
    paste(scr, plain("数值图标：上 32（卡片），下 20（属性格）", 13, DIM, shadow="#000000"), 960, 1040, center=True)
    scr.convert("RGB").save(out, optimize=True)
    print("写出", out)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else str(REVIEW / "lacquer_1080p.png"))
