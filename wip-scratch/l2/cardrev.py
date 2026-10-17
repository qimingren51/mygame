"""卡面插画审图（线 2）：拼图（每张：1 倍整卡 + 2 倍插画）和 1080p 升级界面（四张卡）。

在仓库根目录运行：
  art/.venv/bin/python <本文件> <批名> <id> [<id> ...] [--screen id1,id2,id3,id4] [--art-dir 目录]
插画默认读 art/out/review@2x/card_art_<id>.png；输出 art/out/review@2x/cards_<批名>_sheet.png、cards_<批名>_1080p.png。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PIL import Image, ImageDraw

SP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SP))
sys.path.insert(0, "art/post")
import card_frames as CF  # noqa: E402
import review_1080 as R  # noqa: E402

REVIEW = Path("art/out/review@2x")
ICONS = Path("art/out/assets@2x/ui")
EXTRA_ICONS = [Path("art/out/assets@2x/ui_new")]  # 新法器图标（第 4 批）
plain, paste = CF.plain_text, CF.paste

# id → (名字, 五行, 品阶, 类别, 收益, 等级, 提示, 配对图标)
W = "新法器"
INFO: dict[str, tuple] = {
    "lamp": ("灯火", "fire", "xuan", W, "火环绕身，烧近身妖", (1, 8), "火 1 → 2", "icon_changming"),
    "lamp_evo": ("不夜城", "fire", "tian", "进化", "十盏灯环身，内圈火海", None, "选择后立即进化", None),
    "lamp_mut": ("冰火两重天", "fire", "yi", "异化 · 不可合璧", "半冰半火，引爆蒸腾", None, "异化：舍弃合璧", None),
    "sword": ("符剑", "metal", "ling", "法器", "伤害 +4，穿透 +1", (3, 8), "金 2 → 3", "icon_jianyi"),
    "sword_evo": ("万剑归宗", "metal", "tian", "进化", "三剑连发，无限穿透", None, "选择后立即进化", None),
    "sword_mut": ("赤霄", "metal", "yi", "异化 · 不可合璧", "熔金易伤，击杀分剑", None, "异化：舍弃合璧", None),
    "bell": ("霜铃", "water", "xuan", W, "寒波伤敌并减速", (1, 8), "水 1 → 2", "icon_jingxin"),
    "bell_evo": ("寒山钟", "water", "tian", "进化", "每 6 秒全屏冻结", None, "选择后立即进化", None),
    "bell_mut": ("冻土", "water", "yi", "异化 · 不可合璧", "脚下冻土，冻死即碎", None, "异化：舍弃合璧", None),
    "crane": ("纸鹤", "wood", "ling", "法器", "数量 +1", (4, 8), "木 3 → 4", "icon_zhezhi"),
    "crane_evo": ("千鹤引", "wood", "tian", "进化", "十只纸鹤，更快更狠", None, "选择后立即进化", None),
    "crane_mut": ("铁鹤", "wood", "yi", "异化 · 不可合璧", "五只铁鹤，伤害 ×3", None, "异化：舍弃合璧", None),
    "seal": ("山印", "earth", "xuan", W, "石印落地，击晕一片", (1, 8), "土 0 → 1", "icon_houde"),
    "seal_evo": ("镇岳", "earth", "tian", "进化", "巨岩砸地，裂缝伤敌", None, "选择后立即进化", None),
    "seal_mut": ("竹印", "earth", "yi", "异化 · 不可合璧", "巨竹挑飞，竹墙挡路", None, "异化：舍弃合璧", None),
    "coin_sword": ("铜钱剑", "metal", "xuan", W, "扇形剑气，自带暴击", (1, 8), "金 1 → 2", "icon_ruimu"),
    "coin_sword_evo": ("天罡", "metal", "tian", "进化", "剑气绕身，暴击再斩", None, "选择后立即进化", None),
    "sky_lantern": ("孔明灯", "fire", "xuan", W, "灯飘向妖群，落地爆燃", (1, 8), "火 2 → 3", "icon_luxin"),
    "sky_lantern_evo": ("万灯升", "fire", "tian", "进化", "八盏齐落，满地火海", None, "选择后立即进化", None),
    "wave": ("沧浪", "water", "xuan", W, "推浪开路，减速妖物", (1, 8), "水 2 → 3", "icon_hanyi"),
    "wave_evo": ("北冥潮", "water", "tian", "进化", "巨浪四散，推开冻结", None, "选择后立即进化", None),
    "vine": ("青藤", "wood", "xuan", W, "藤连妖物，吸血续命", (1, 8), "木 1 → 2", "icon_huichun"),
    "vine_evo": ("万木春", "wood", "tian", "进化", "八藤齐连，定时缠住", None, "选择后立即进化", None),
    "tower": ("镇妖塔", "earth", "xuan", W, "落塔吸妖，聚成一团", (1, 8), "土 1 → 2", "icon_panshi"),
    "tower_evo": ("玲珑塔", "earth", "tian", "进化", "全屏吸妖，到时炸开", None, "选择后立即进化", None),
    "phoenix": ("百鸟朝凤", "wood", "he", "合璧 · 腾出一格", "群鹤化凤，扑击留火海", None, "合璧：纸鹤 + 灯火", None),
    "sword_grove": ("万剑冢", "earth", "he", "合璧 · 腾出一格", "万剑成林，穿行即斩", None, "合璧：山印 + 符剑", None),
    "frost_rain": ("霜天剑雨", "water", "he", "合璧 · 腾出一格", "钟鸣剑雨，冻结贯穿", None, "合璧：霜铃 + 符剑", None),
    "lotus": ("莲子", None, "fan", "补给", "回复 30% 生命", None, None, None),
    "oil": ("灯油", None, "fan", "补给", "灯油 +20", None, None, None),
}
P = "新心法"
for pid, name, el, gain in (
    ("jianyi", "剑意", "metal", "暴击伤害 +20%"), ("ruimu", "锐目", "metal", "暴击率 +5%"),
    ("xunfeng", "迅锋", "metal", "飞行物快、远 +10%"), ("zhezhi", "折纸", "wood", "1、3、5 级数量 +1"),
    ("huichun", "回春", "wood", "每秒回血 +0.2"), ("jixing", "疾行", "wood", "移速 +8%"),
    ("jingxin", "静心", "water", "冷却 -6%"), ("hanyi", "寒意", "water", "减速 +6%，冰冻 +10%"),
    ("yinhun", "引魂", "water", "拾取范围 +25%"), ("changming", "长明", "fire", "范围 +10%"),
    ("luxin", "炉心", "fire", "伤害 +8%"), ("dengxin", "灯芯", "fire", "照见圈、燃灯更强"),
    ("houde", "厚德", "earth", "生命 +20，护甲 +1"), ("panshi", "磐石", "earth", "受伤 -5%"),
    ("zaiwu", "载物", "earth", "护盾 +15%，以甲增伤"), ("qinggong", "轻功", None, "闪避冷却 -10%"),
    ("juhun", "聚魂", None, "魂火 +6%，偶多一选项"),
):
    INFO[pid] = (name, el, "ling", P, gain, (1, 5), None, None)


def icon_path(name: str) -> Path:
    for d in [ICONS, *EXTRA_ICONS]:
        if (d / f"{name}.png").exists():
            return d / f"{name}.png"
    return ICONS / f"{name}.png"


def icon(name: str, size: float, alpha: float = 1.0) -> Image.Image:
    im = Image.open(icon_path(name)).convert("RGBA").resize((int(round(size)), int(round(size))), Image.LANCZOS)
    return CF.fade(im, alpha) if alpha < 1 else im


def art_img(cid: str, art_dir: Path) -> Image.Image:
    p = art_dir / f"card_art_{cid}.png"
    if not p.exists():
        p = art_dir / f"card_{cid}.png"
    return Image.open(p).convert("RGBA")


def art_block(cid: str, k: float, art_dir: Path) -> Image.Image:
    """插画区 268×201×k：圆角 6，左上五行印 34，右上品阶签（同 choice.rs）。"""
    name, el, rar = INFO[cid][:3]
    aw, ah = round(268 * k), round(201 * k)
    im = CF.rounded(art_img(cid, art_dir).resize((aw, ah), Image.LANCZOS), round(6 * k))
    if el:
        paste(im, icon(f"icon_el_{el}", 34 * k), 8 * k, 8 * k)
    tag_t = plain(R.RARITY_NAME[rar], 12 * k, R.RARITY_COL[rar])
    tw, th = tag_t.width + 2 * 10 * k - 16, 12 * k * 1.25 + 2 * 3 * k
    tag = R.nine("chip_dark", tw / k, th / k, k)
    tx = aw - 8 * k - tag.width
    paste(im, tag, tx, 8 * k)
    paste(im, tag_t, tx + tag.width / 2, 8 * k + tag.height / 2, center=True)
    return im


def card_face(cid: str, index: int, art_dir: Path) -> Image.Image:
    """整张卡（逻辑 300×460，1080p 下 1:1）：照 review_1080.card_face 的排法。"""
    name, el, rar, kind, gain, lv, note, pair = INFO[cid]
    k = 2
    Wc, Hc = 300 * k, 460 * k
    im = Image.new("RGBA", (Wc, Hc), (0, 0, 0, 0))
    im.alpha_composite(R.nine(f"card_{rar}", 300, 460, k))
    ax0, ay0 = 16 * k, 16 * k
    im.alpha_composite(art_block(cid, k, art_dir), (ax0, ay0))
    rows = [(plain(name, 30 * k, R.PAPER, kind="brush", shadow="#000000"), 0)]
    ecol = R.EL_COL.get(el, "#C9B98F") if el else "#C9B98F"
    gcol = "#%02X%02X%02X" % tuple(int(v * 255) for v in CF.mixc(CF.hexc(ecol), CF.hexc("#F2E8D2"), 0.45))
    rows.append((plain(gain, 22 * k, gcol, kind="serif" if any(c.isdigit() for c in gain) else "brush", shadow="#000000"), 2 * k))
    if lv:
        cur, mx = lv
        dots = Image.new("RGBA", (mx * 10 * k + (mx - 1) * 6 * k, 10 * k), (0, 0, 0, 0))
        for i in range(mx):
            paste(dots, R.nine("pip_on" if i < cur else "pip", 10, 10, k), i * 16 * k, 0)
        rows.append((dots, 10 * k))
    if note:
        hi = rar in ("tian", "yi", "he")
        rows.append((plain(note, 15 * k, R.RARITY_COL[rar] if hi else R.DIM, shadow="#000000"), 6 * k))
    foot_top = Hc - 20 * k - 30 * k
    body_top = ay0 + 201 * k
    total = sum(r.height + gap for r, gap in rows)
    y = body_top + (foot_top - body_top - total) / 2
    for r, gap in rows:
        y += gap
        paste(im, r, Wc / 2 - r.width / 2, y)
        y += r.height
    fy = foot_top + 15 * k
    lab = plain(kind, 12 * k, R.FOOT)
    paste(im, lab, 26 * k, fy - lab.height / 2)
    kc = CF.keycap("lacquer", str(index + 1), 22 * k)
    xr = Wc - 26 * k
    paste(im, kc, xr - kc.width, fy - kc.height / 2)
    if pair and icon_path(pair).exists():
        paste(im, icon(pair, 30 * k, alpha=0.5), xr - kc.width - 8 * k - 30 * k, fy - 15 * k)
    return im.resize((300, 460), Image.LANCZOS)


def sheet(batch: str, ids: list[str], art_dir: Path) -> Path:
    """拼图：每格左边 1 倍整卡（游戏里的实际大小），右边 2 倍插画（536×402）；两列。"""
    cw, ch = 300 + 16 + 536, 460
    cols = 2
    rows = (len(ids) + cols - 1) // cols
    gap = 28
    Wt, Ht = cols * cw + (cols + 1) * gap, rows * (ch + 40) + gap + 60
    scr = CF.game_backdrop((Wt, Ht))
    paste(scr, plain(f"卡面插画 · {batch}（左：1 倍整卡；右：插画 2 倍）", 22, "#E9DFC7", shadow="#000000"), gap, 18)
    for i, cid in enumerate(ids):
        c, r = i % cols, i // cols
        x, y = gap + c * (cw + gap), 60 + r * (ch + 40)
        paste(scr, card_face(cid, i % 4, art_dir), x, y)
        paste(scr, art_block(cid, 2, art_dir), x + 316, y)
        paste(scr, plain(f"ui/card_{cid}", 15, R.DIM, shadow="#000000"), x + 316, y + 402 + 10)
    out = REVIEW / f"cards_{batch}_sheet.png"
    scr.convert("RGB").save(out, optimize=True)
    return out


def screen(batch: str, ids: list[str], art_dir: Path, focus: int = 1) -> Path:
    """1080p 升级界面：状态栏 + 四张卡（逻辑 1:1）。"""
    scr = CF.game_backdrop()
    R.hud(scr)
    clock = plain("12:40", 28, "#F2EBDC", kind="serif", shadow="#000000")
    paste(scr, clock, 960, 14 + clock.height / 2, center=True)
    R.chips(scr)
    y = 70
    paste(scr, plain("升级", 48, "#E9DFC7", kind="brush", shadow="#000000"), 960, y + 24, center=True)
    paste(scr, plain("Lv 17 → 18", 18, R.DIM, shadow="#000000"), 960, y + 66, center=True)
    n = len(ids)
    x0 = 960 - (n * 300 + (n - 1) * 20) / 2
    cy = 190
    for i, cid in enumerate(ids):
        paste(scr, card_face(cid, i, art_dir), x0 + i * 320, cy)
    paste(scr, R.nine("card_focus", 312, 472), x0 + focus * 320 - 6, cy - 6)
    paste(scr, plain("← → 选择　↑ ↓ 切换卡片与操作　空格 确定", 15, "#8E8576", shadow="#000000"), 960, cy + 460 + 60, center=True)
    out = REVIEW / f"cards_{batch}_1080p.png"
    scr.convert("RGB").save(out, optimize=True)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("batch")
    ap.add_argument("ids", nargs="+")
    ap.add_argument("--screen", default=None, help="1080p 里放哪几张（逗号分隔，默认前四张）")
    ap.add_argument("--art-dir", type=Path, default=REVIEW)
    a = ap.parse_args()
    print("写出", sheet(a.batch, a.ids, a.art_dir))
    ids = a.screen.split(",") if a.screen else a.ids[:4]
    print("写出", screen(a.batch, ids, a.art_dir))


if __name__ == "__main__":
    main()
