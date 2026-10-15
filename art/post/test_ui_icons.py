#!/usr/bin/env python3
"""ui_icons.py（含 ui_seals.py 的朱砂印章）的自检：纯 assert，不依赖 pytest。

每次运行先重新生成，再单独渲染一遍逐像素比对（确定性）。
不设 LANTERN_ART_DENSITY 时自动在 1 倍、2 倍各跑一遍（子进程）；设了就只测那一种密度。

前 25 个图标（第一批）必须逐字节不变（OLD_MD5；kfix 有意重画的万剑归宗、疾行已换成新 md5），meta 里它们的条目也不变；第二批与印章追加在后面。
M2.5（第三批，ui_icons_m25.py 与五行反应印）追加在最后；M2.5 之前的全部图标、印章与 meta 条目按 post/golden_m25.json 核对。

用法（在仓库根目录下）：
  art/.venv/bin/python art/post/test_ui_icons.py
"""

from __future__ import annotations

import hashlib
import itertools
import json
import re
import sys
import traceback
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import testkit  # noqa: E402

if __name__ == "__main__":
    _rc = testkit.run_all_densities(__file__)
    if _rc is not None:
        sys.exit(_rc)

import ui_icons as U  # noqa: E402
import ui_icons_m25 as M  # noqa: E402
import ui_seals as Z  # noqa: E402

V = U.V
S = U.S
D = V.D
N = int(round(64 * D))
DKEY = f"{D:g}"

WEAPON_IDS = ["lamp", "sword", "bell", "crane", "seal"]
PASSIVE_IDS = ["changming", "luxin", "jianyi", "ruimu", "jingxin", "yinhun", "zhezhi", "jixing", "houde", "panshi"]
ELEMENT_IDS = ["metal", "wood", "water", "fire", "earth"]
EXPECTED = (
    [f"icon_{w}.png" for w in WEAPON_IDS]
    + [f"icon_{w}_evo.png" for w in WEAPON_IDS]
    + [f"icon_{p}.png" for p in PASSIVE_IDS]
    + [f"icon_el_{e}.png" for e in ELEMENT_IDS]
)
OLD_KINDS = ("weapon", "weapon_evo", "passive", "element")

# 第二批：id 与 web/lantern/game.js 一致
META_IDS = ["dmg", "hp", "agi", "luck"]
ENC_IDS = ["toad", "spring", "shrine", "altar", "rift"]
BUFF_IDS = ["fury", "swift", "soul", "iron"]
OMEN_IDS = ["bloodmoon", "fog", "glass", "foxes", "gale", "chestrain", "element", "greed", "quiet", "wonders"]
HUD_IDS = ["kills", "pause", "dash", "ult", "level"]
WEB_ACCENT = {  # game.js 的 EVENTS / BUFFS 颜色
    "toad": "#FFD98A", "spring": "#5FD4C4", "shrine": "#FF8A3D", "altar": "#FF6B5A", "rift": "#B07CF0",
    "fury": "#FF8A3D", "swift": "#6FD6A0", "soul": "#5FD4C4", "iron": "#E9D9A6",
}
NEW_ICONS = (
    ["icon_lotus.png", "icon_oil.png"]
    + [f"icon_meta_{m}{s}.png" for m in META_IDS for s in ("", "_off")]
    + [f"icon_enc_{e}.png" for e in ENC_IDS]
    + [f"icon_buff_{b}.png" for b in BUFF_IDS]
    + [f"icon_omen_{o}.png" for o in OMEN_IDS]
    + [f"icon_{h}.png" for h in HUD_IDS]
)
SEAL_SIZES_2X = {
    "seal_tian": (128, 128), "seal_xuan": (128, 128), "seal_ling": (128, 128), "seal_fan": (128, 128),
    "seal_rui": (128, 128), "seal_sheng": (128, 128), "seal_ning": (128, 128), "seal_fen": (128, 128), "seal_gu": (128, 128),
    "seal_evo": (96, 160), "seal_record": (96, 224), "seal_elite": (96, 160), "seal_boss": (96, 160),
}
SEALS = [f"{s}.png" for s in SEAL_SIZES_2X]
ICONS = EXPECTED + NEW_ICONS

# ---- M2.5（第三批）：id 与 assets/data/*.ron 一致（测试里直接读 RON 核对）
DATA = HERE.parents[1] / "assets" / "data"
M25_PASSIVES = ["xunfeng", "huichun", "hanyi", "dengxin", "zaiwu", "qinggong", "juhun"]
M25_OMENS = ["wuyue", "nike"]
AFFIX_IDS = ["ji", "jian", "fen", "zhao", "yin", "kuang"]
HUB_ROLES = ["lampsmith", "peddler", "lampboy", "storyteller"]
CHARM_IDS = ["wind_wheel", "pillar", "night_pearl", "elixir", "five_coins", "longevity", "ice_soul", "broken_sword"]
REACTION_IDS = ["liaoyuan", "rongyan", "zhubing", "ningshuang", "zisheng", "zhengteng", "rongjin", "duanmu", "lietu", "yuni"]
M25_ICONS = (
    [f"icon_{p}.png" for p in M25_PASSIVES] + [f"icon_omen_{o}.png" for o in M25_OMENS] + ["icon_gold.png", "icon_enc_merchant.png"]
    + [f"icon_affix_{a}.png" for a in AFFIX_IDS] + [f"icon_hub_{k}.png" for k in range(4)] + [f"icon_charm_{c}.png" for c in CHARM_IDS]
)
AFFIX = [f"icon_affix_{a}.png" for a in AFFIX_IDS]
FULL_M25 = [n for n in M25_ICONS if n not in AFFIX]  # 128² 的
REACT_SEALS = [f"seal_react_{r}.png" for r in REACTION_IDS]
ALL = ICONS + SEALS + M25_ICONS + REACT_SEALS
ALL_SEALS = SEALS + REACT_SEALS
SEAL_SIZES_2X.update({n[:-4]: (128, 128) for n in REACT_SEALS})
SMALL_24 = ["icon_lotus.png", "icon_oil.png"] + [f"icon_buff_{b}.png" for b in BUFF_IDS] + [f"icon_{h}.png" for h in HUD_IDS if h != "level"]
SMALL_24 += ["icon_gold.png"] + AFFIX
NA = N // 2  # 小图标（精英词缀）的边长


def ron_entries(name: str) -> list[dict]:
    """从 assets/data/<name>.ron 里粗读 (id: "...", name: "...", ...) 条目的 id、name、element。"""
    text = (DATA / name).read_text(encoding="utf-8")
    out = []
    for m in re.finditer(r'\(id: "([a-z_]+)", name: "([^"]+)"(.*?)(?=\n\s*\(id: |\n\])', text, re.S):
        el = re.search(r"element: (\w+)", m.group(3))
        out.append({"id": m.group(1), "name": m.group(2), "el": el.group(1).lower() if el else None})
    return out

# kfix（PORTING-NOTES 第 8 节的已知问题）有意重画了万剑归宗 icon_sword_evo、疾行 icon_jixing，这两项换成了新的 md5
OLD_MD5 = {  # 前 25 个图标在第二批加入之前的 md5（1 倍、2 倍），必须逐字节不变
    "1": {
        "icon_bell.png": "34886ab3d1c1f4c0b548b53255aacf6a", "icon_bell_evo.png": "369f88a9ad6aa71910d981e20ac76b4b", "icon_changming.png": "c9272b2ee0d6ded3f69c8314be914407",
        "icon_crane.png": "91f95f2c0d98c77ad4a6a4227355d43c", "icon_crane_evo.png": "6379ad6d19489958c934f147fa402a0e", "icon_el_earth.png": "4e22db580deb13e7dc5ec2853d383a44",
        "icon_el_fire.png": "5bcfa7e231007743120384ceb469fe92", "icon_el_metal.png": "c95b3f87207e21565af4314497191d0c", "icon_el_water.png": "32cafc3d8fa68e588b6ac152b91d6ef8",
        "icon_el_wood.png": "76af9e9bfbb64654ad1ec36aee7619c6", "icon_houde.png": "65535dbfc1ebfcf6cd78e44451d3fddb", "icon_jianyi.png": "5c7cdc90f626ab4e4385e19aad175938",
        "icon_jingxin.png": "acb82f974f3176973187def4d917c0aa", "icon_jixing.png": "bf85fd72627c979d071e1778f2a05f6f", "icon_lamp.png": "6c2d48a9512c705d99cbcd04d2f2e13c",
        "icon_lamp_evo.png": "112f67882b358c8911177a07af4b85be", "icon_luxin.png": "87a99a74350088ddb829176482edb2c9", "icon_panshi.png": "8dedb06d621e8ada350e63ba2f1db09b",
        "icon_ruimu.png": "bfc64a6e9ff4086b40a60c87f4d8484b", "icon_seal.png": "a514fd98bb8c7505a706a342f3f36cc9", "icon_seal_evo.png": "b8295c126c1d5ac7e6cf1d81bb5ee922",
        "icon_sword.png": "93e3fd8d53117e7a3f10fa236d6a95f4", "icon_sword_evo.png": "aac1a0141261cbfe146d5e60ffb61b3a", "icon_yinhun.png": "191facf0689b12ed12426e2c8485e0d0",
        "icon_zhezhi.png": "7e868917804e8e8498c635fc16580794",
    },
    "2": {
        "icon_bell.png": "74c0a8b615c4bad62478d108dd66ffdc", "icon_bell_evo.png": "fb9d1f721752dc1860097ccdbffd97b9", "icon_changming.png": "9f54c68a2a62cdda1430411479a0c49f",
        "icon_crane.png": "5e27f4a9534bfb6903b5376568ab5064", "icon_crane_evo.png": "6caa37a65add78084d74d1f7c263aa0f", "icon_el_earth.png": "c32a568055b1cfc654b6cea301be2930",
        "icon_el_fire.png": "7acaaa9fad7e2b94e6adc678f1593812", "icon_el_metal.png": "94291526968c85fad06df3fdc9caeab4", "icon_el_water.png": "405c9d795d03a39a87d01334e8d28410",
        "icon_el_wood.png": "b90e7643a4375e323218bcd0d5e4e66e", "icon_houde.png": "9556de568dafdc34c20765e3a72871dc", "icon_jianyi.png": "1eedbcc7ac6b41f32b3daab523ed286f",
        "icon_jingxin.png": "27405d77ef86f61a4477f87463eab126", "icon_jixing.png": "ee4c030296250f0057b634d78002a77c", "icon_lamp.png": "6e1f745dbb5f83cf68198cec575b526c",
        "icon_lamp_evo.png": "f936479b00bd4b6c1c25be7186244157", "icon_luxin.png": "c4ee4753720d6ca9cf8545cffe9ebff2", "icon_panshi.png": "c3f275c946c7c4c26270ad41fd9eba16",
        "icon_ruimu.png": "9bb23093ee6ce2320a98e9c90ffa90d4", "icon_seal.png": "3c4709433598ace102d5cf5cb90cfb23", "icon_seal_evo.png": "61bb26e43e95b258bab537ce7ac09242",
        "icon_sword.png": "ff1f5ca80e0f3a87debf8dec2afb8d0d", "icon_sword_evo.png": "b208f432f29eba06f9b78f015b1b7cf0", "icon_yinhun.png": "30082822154d8db6ae225979569dcf48",
        "icon_zhezhi.png": "72ad815804e033e9d9e641c5f119b653",
    },
}
OLD_META_MD5 = {  # 前 25 个条目（按键排序的 JSON）与旧的顶层字段的 md5
    "1": ("c8e791e6e467b6838088adf27690b15b", "fbc18a5c835f3ca1ab4ef9c3628a5741"),
    "2": ("9a30421a2e4ec693d8b131cba95aaf60", "227f28f56019d48b47fcb917ebc774c6"),
}
OLD_TOP_KEYS = ["name", "generator", "format", "px_per_unit", "display_px_1x", "el_colors"]


def rgba(name: str) -> np.ndarray:
    return np.asarray(Image.open(U.UI_DIR / name).convert("RGBA"), dtype=np.float64)


def meta() -> dict:
    return json.loads((U.UI_DIR / "meta.json").read_text(encoding="utf-8"))


def small(name: str, s: int = 32) -> np.ndarray:
    """缩到 s 像素（界面上的显示尺寸），铺在纸色上。"""
    im = Image.open(U.UI_DIR / name).convert("RGBA").resize((s, s), Image.LANCZOS)
    a = np.asarray(im, dtype=np.float64) / 255.0
    bg = np.array(S.hex_to_rgb(S.PAPER)) / 255.0
    return a[..., :3] * a[..., 3:] + bg * (1 - a[..., 3:])


def at32(name: str) -> np.ndarray:
    return small(name, 32)


def lum(rgb: np.ndarray) -> np.ndarray:
    return rgb @ np.array([0.299, 0.587, 0.114])


def radial(n: int) -> np.ndarray:
    yy, xx = np.mgrid[0:n, 0:n] + 0.5
    return np.hypot(xx - n / 2, yy - n / 2) / D  # 以 1 倍像素计的半径


def angle_deg(n: int) -> np.ndarray:
    return np.degrees(np.arctan2(*(np.mgrid[0:n, 0:n] + 0.5 - n / 2)))  # atan2(y, x)


def inner_disc(s: int, rad: float) -> np.ndarray:
    yy, xx = np.mgrid[0:s, 0:s] + 0.5
    return np.hypot(xx - s / 2, yy - s / 2) < rad


def arc_color(a: np.ndarray) -> np.ndarray:
    """墨圈内侧色弧（r≈24.3，左下半圈）的平均颜色。"""
    r, th = radial(N), np.mod(angle_deg(N), 360)
    band = (np.abs(r - 24.3) < 0.5) & (th > 70) & (th < 220)
    return a[..., :3][band].mean(0)


def is_vermilion(rgb: np.ndarray) -> np.ndarray:
    return (rgb[..., 0] > 0.5) & (rgb[..., 0] - rgb[..., 1] > 0.28) & (rgb[..., 0] - rgb[..., 2] > 0.28)


# ============================================================== meta 与尺寸


def test_meta_and_sizes():
    m = meta()
    assert m["px_per_unit"] == S.PX_PER_UNIT
    files = m["files"]
    assert list(files) == ALL, f"图标列表不符：{sorted(set(files) ^ set(ALL))}"
    assert {p.name for p in U.UI_DIR.glob("*.png")} == set(ALL), "ui/ 里多出或缺少文件"
    for name, e in files.items():
        assert tuple(e["anchor"]) == (0.5, 0.5), f"{name} 锚点应居中"
        assert e["blend"] == "normal" and e["tint"] is False and e["color"] == "full", f"{name} 应为全彩、正常混合"
        for k in ("kind", "id", "name", "note"):
            assert k in e, f"{name} meta 缺少 {k}"
        if e["kind"] in OLD_KINDS and name not in M25_ICONS:
            assert "el" in e, f"{name} meta 缺少 el"
        im = Image.open(U.UI_DIR / name)
        assert im.mode == "RGBA" and list(im.size) == e["size"], f"{name} 实际 {im.size} {im.mode}，meta {e['size']}"
        if name in ICONS or name in FULL_M25:
            assert im.size == (N, N), f"{name} 应为 {N}×{N}"
        if name in AFFIX:
            assert im.size == (NA, NA), f"{name} 应为 {NA}×{NA}（小图标）"
        if e["kind"] == "passive" and name not in M25_ICONS:
            assert U.PASSIVES[e["id"]][1] == e["el"], f"{name} 五行与 src/data/passives.ts 不符"
        if e["kind"] in ("encounter", "buff") and e["id"] in WEB_ACCENT:  # 货郎（M2.5）的颜色取自 events.ron，另测
            assert e["accent"] == WEB_ACCENT[e["id"]], f"{name} accent 与网页版颜色不符"
    for n in NEW_ICONS:
        e, stem = files[n], n[:-4]
        assert stem.endswith((e["id"], e["id"] + "_off")), f"{n} 的 id {e['id']} 与文件名不符"
        if e["kind"] == "meta":
            assert e["lit"] is (not stem.endswith("_off")), f"{n} 的 lit 字段不对"
    for n in ALL_SEALS:
        w2, h2 = SEAL_SIZES_2X[n[:-4]]
        assert w2 % 32 == 0 and h2 % 32 == 0
        want = [int(round(w2 * D / 2)), int(round(h2 * D / 2))]
        assert files[n]["size"] == want, f"{n} 尺寸 {files[n]['size']} != {want}"
        assert files[n]["kind"] == "seal" and files[n]["style"] in ("白文", "朱文", "朱白相间") and files[n]["group"] in ("rarity", "resonance", "mark", "reaction")


def test_m25_meta_matches_data():
    """M2.5 图标、反应印的 id / 名字 / 五行与 assets/data 的 RON 一致。"""
    files = meta()["files"]
    passives = {e["id"]: e for e in ron_entries("passives.ron")}
    for pid in M25_PASSIVES:
        e = files[f"icon_{pid}.png"]
        assert e["kind"] == "passive" and e["id"] == pid and e["name"] == passives[pid]["name"], f"icon_{pid} 与 passives.ron 不符"
        assert e.get("el") == passives[pid]["el"], f"icon_{pid} 五行 {e.get('el')} 与 passives.ron 的 {passives[pid]['el']} 不符"
    for fname, data, kind, ids in (("omens.ron", "icon_omen_{}", "omen", M25_OMENS), ("affixes.ron", "icon_affix_{}", "affix", AFFIX_IDS),
                                   ("charms.ron", "icon_charm_{}", "charm", CHARM_IDS)):
        names = {e["id"]: e["name"] for e in ron_entries(fname)}
        if kind != "omen":
            assert list(names) == ids, f"{fname} 的条目 {list(names)} 与测试的 {ids} 不一致"
        for i in ids:
            e = files[data.format(i) + ".png"]
            assert e["kind"] == kind and e["id"] == i and e["name"] == names[i], f"{data.format(i)} 与 {fname} 不符"
    ev = (DATA / "events.ron").read_text(encoding="utf-8")
    mm = re.search(r'\(id: "merchant", name: "([^"]+)".*?color: "(#[0-9A-Fa-f]{6})"', ev, re.S)
    e = files["icon_enc_merchant.png"]
    assert e["kind"] == "encounter" and e["name"] == mm.group(1) and e["accent"] == mm.group(2), "icon_enc_merchant 与 events.ron 不符"
    assert files["icon_gold.png"]["kind"] == "currency" and files["icon_gold.png"]["id"] == "gold"
    for k, role in enumerate(HUB_ROLES):
        e = files[f"icon_hub_{k}.png"]
        assert e["kind"] == "hub" and e["id"] == str(k) and e["role"] == role, f"icon_hub_{k} meta 不对"
    el = (DATA / "elements.ron").read_text(encoding="utf-8")
    reactions = re.findall(r'\(a: (\w+), b: (\w+), id: "(\w+)", name: "([^"]+)"', el)
    assert [r[2] for r in reactions] == REACTION_IDS, "elements.ron 的反应顺序变了"
    for a, b, rid, name in reactions:
        e = files[f"seal_react_{rid}.png"]
        assert e["group"] == "reaction" and e["id"] == rid and e["name"] == name and e["els"] == [a.lower(), b.lower()], f"seal_react_{rid} 与 elements.ron 不符"
        assert e["style"] == "朱白相间" and e["shape"] == "rsquare"


def test_pre_m25_unchanged():
    """快照里的图标、印章（M2.5 之前 + M2.5 第一批）逐字节不变，meta.json 已有条目与顶层字段不变、新条目只追加在后面（post/golden_m25.json）。"""
    n = testkit.check_snapshot(V.ASSETS, ("ui",), D)
    assert n == len(ALL), f"快照里应有 {len(ALL)} 个 PNG，实际核对了 {n} 个"
    assert list(meta()["files"])[: len(ICONS) + len(SEALS)] == ICONS + SEALS


def test_old_unchanged():
    """前 25 个图标与第二批加入之前逐字节相同，meta 条目与旧顶层字段也相同。"""
    want = OLD_MD5[DKEY]
    for n in EXPECTED:
        got = hashlib.md5((U.UI_DIR / n).read_bytes()).hexdigest()
        assert got == want[n], f"{n} 变了（md5 {got} != {want[n]}）"
    m = meta()
    old = {k: m["files"][k] for k in EXPECTED}
    top = {k: m[k] for k in OLD_TOP_KEYS}
    f_md5 = hashlib.md5(json.dumps(old, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    t_md5 = hashlib.md5(json.dumps(top, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    assert (f_md5, t_md5) == OLD_META_MD5[DKEY], "meta.json 里前 25 个条目或旧的顶层字段变了"
    assert list(m["files"])[:25] == EXPECTED, "前 25 个条目的顺序变了"


# ============================================================== 图标的框


def design_radius(n: int) -> np.ndarray:
    """以 64×64 设计坐标计的半径：普通图标就是 1 倍像素，小图标（32 像素画布）再乘 2。"""
    return radial(n) * (64 * D / n)


def test_borders_and_disc():
    m = meta()["files"]
    lit_ring = []
    for name in ICONS + M25_ICONS:
        a = rgba(name)
        al = a[..., 3]
        r = design_radius(al.shape[0])
        ring = (r > 26.5) & (r < 29.5)
        border = np.concatenate([al[0], al[-1], al[:, 0], al[:, -1]])
        assert border.max() == 0, f"{name} 最外一圈应全透明"
        assert al[r < 20].min() > 250, f"{name} 圆底内部应不透明"
        outside = r > 31.5
        if m[name]["kind"] == "charm":  # 灯坠顶上的中国结和提环伸出圆外，只许在正上方
            xx = (np.mgrid[0 : al.shape[0], 0 : al.shape[1]][1] + 0.5) / D
            outside &= np.abs(xx - 32.0) > 5.0
        assert al[outside].max() <= 10, f"{name} 圆外应透明"
        L = lum(a[..., :3][ring] / 255.0)
        e = m[name]
        if e["kind"] == "omen":
            continue  # 夜签是朱砂双圈，见 test_new_frames
        if e.get("lit") is False:
            dark = L < 0.6
            assert dark.mean() > 0.5, f"{name} 淡墨圈不完整（{dark.mean():.2f}）"
            assert L[dark].mean() > np.mean(lit_ring) + 0.1, f"{name} 未点亮的墨圈应比点亮的淡"
            continue
        dark = L < 0.25
        assert dark.mean() > 0.5, f"{name} 墨圈不完整（暗像素只占 {dark.mean():.2f}）"
        lit_ring.append(L[dark].mean())


def test_readable_at_32px():
    """缩到 32 像素：物件区域要有足够的明暗对比，且各图标彼此不同（前 25 个之间、第二批与前 25 个之间）。
    等级徽章底中间故意留空（数字由游戏画），不查物件对比。"""
    smalls = {}
    inner = inner_disc(32, 10.5)
    for name in ICONS:
        s = at32(name)
        smalls[name] = s
        if name == "icon_level.png":
            continue
        L = lum(s)[inner]
        assert L.std() > 0.1, f"{name} 在 32 像素下物件对比太低（std {L.std():.3f}）"
        assert np.percentile(L, 95) - np.percentile(L, 5) > 0.3, f"{name} 在 32 像素下缺少深浅层次"
    worst = (1.0, "")
    for a_, b_ in itertools.combinations(EXPECTED, 2):
        worst = min(worst, (np.abs(smalls[a_] - smalls[b_])[inner].mean(), f"{a_} / {b_}"))
    assert worst[0] > 0.05, f"32 像素下两个图标太像：{worst[1]}（差 {worst[0]:.3f}）"
    worst = (1.0, "")
    for a_ in NEW_ICONS:
        for b_ in EXPECTED:
            worst = min(worst, (np.abs(smalls[a_] - smalls[b_])[inner].mean(), f"{a_} / {b_}"))
    assert worst[0] > 0.05, f"32 像素下新图标与原有图标太像：{worst[1]}（差 {worst[0]:.3f}）"


def test_m25_readable_and_distinct():
    """M2.5 图标缩到 32 像素：物件区域有足够的明暗对比；与原有的全部图标、M2.5 的其他图标都不太像
    （小图标先放到同样的 32 像素再比）。"""
    inner = inner_disc(32, 10.5)
    sm = {n: at32(n) for n in ICONS + M25_ICONS if n != "icon_level.png"}
    for name in M25_ICONS:
        L = lum(sm[name])[inner]
        assert L.std() > 0.1, f"{name} 在 32 像素下物件对比太低（std {L.std():.3f}）"
        assert np.percentile(L, 95) - np.percentile(L, 5) > 0.3, f"{name} 在 32 像素下缺少深浅层次"
    worst = (1.0, "")
    for a_ in M25_ICONS:
        for b_ in sm:
            if b_ != a_ and not (b_ in M25_ICONS and M25_ICONS.index(b_) < M25_ICONS.index(a_)):
                worst = min(worst, (np.abs(sm[a_] - sm[b_])[inner].mean(), f"{a_} / {b_}"))
    assert worst[0] > 0.05, f"32 像素下两个图标太像：{worst[1]}（差 {worst[0]:.3f}）"


def m25_categories() -> dict[str, list[str]]:
    """M2.5 图标按类别归到原有的同类里（心法和原有 10 门心法比，夜签和原有 10 张比……），新的类别自成一组。"""
    m = meta()["files"]
    cats: dict[str, list[str]] = {}
    for n in EXPECTED + NEW_ICONS + M25_ICONS:
        k = {"currency": "supply"}.get(m[n]["kind"], m[n]["kind"])
        cats.setdefault(k, []).append(n)
    return {k: v for k, v in cats.items() if any(n in M25_ICONS for n in v)}


def test_m25_distinct_within_category():
    """同一类里（含原有的同类）任意两个图标在 32 像素下不能太像。"""
    inner = inner_disc(32, 10.5)
    cats = m25_categories()
    assert set(cats) == {"passive", "omen", "supply", "encounter", "affix", "hub", "charm"}, set(cats)
    for k, ns in cats.items():
        sm = {n: at32(n) for n in ns}
        for a_, b_ in itertools.combinations(ns, 2):
            if a_ not in M25_ICONS and b_ not in M25_ICONS:
                continue
            dv = np.abs(sm[a_] - sm[b_])[inner].mean()
            assert dv > 0.06, f"{k} 类里 {a_} 与 {b_} 在 32 像素下太像（差 {dv:.3f}）"


def test_readable_at_24px():
    """补给、增益、界面图标还要在 24 像素下认得出（信息栏、灯油数字旁）。"""
    inner = inner_disc(24, 7.9)
    for name in SMALL_24:
        L = lum(small(name, 24))[inner]
        assert L.std() > 0.1, f"{name} 在 24 像素下物件对比太低（std {L.std():.3f}）"
        assert np.percentile(L, 95) - np.percentile(L, 5) > 0.3, f"{name} 在 24 像素下缺少深浅层次"


def categories() -> dict[str, list[str]]:
    m = meta()["files"]
    cats: dict[str, list[str]] = {}
    for n in NEW_ICONS:
        e = m[n]
        k = {"currency": "supply"}.get(e["kind"], e["kind"])
        if k == "meta":
            k += "_lit" if e["lit"] else "_off"
        cats.setdefault(k, []).append(n)
    return cats


def test_distinct_within_category():
    """同一类里任意两个图标在 32 像素下不能太像（心灯的点亮 / 未点亮是同一幅画，分开比）。"""
    inner = inner_disc(32, 10.5)
    cats = categories()
    assert set(cats) == {"supply", "meta_lit", "meta_off", "encounter", "buff", "omen", "hud"}
    for k, ns in cats.items():
        sm = {n: at32(n) for n in ns}
        for a_, b_ in itertools.combinations(ns, 2):
            dv = np.abs(sm[a_] - sm[b_])[inner].mean()
            assert dv > 0.05, f"{k} 类里 {a_} 与 {b_} 在 32 像素下太像（差 {dv:.3f}）"


def test_family_colors():
    """五行色弧在墨圈内侧；进化图标外有金圈；五行图标的圆底染了本行的淡彩。（前 25 个）"""
    m = meta()["files"]
    r = radial(N)
    for name in EXPECTED:
        e = m[name]
        a = rgba(name) / 255.0
        want = U.EL_INK[e["el"]]
        got = arc_color(a)
        assert np.abs(got - want).max() < 0.2, f"{name} 五行色弧颜色 {np.round(got * 255)} 与 {e['el']} 不符"
        gold = (np.abs(r - 30.05) < 0.35) & (a[..., 3] > 0.5)
        g = a[..., :3][gold]
        is_gold = ((g[:, 0] > 0.6) & (g[:, 0] > g[:, 2] + 0.25)).mean() if len(g) else 0.0
        if e["kind"] == "weapon_evo":
            assert is_gold > 0.6, f"{name} 应有金圈（金色占 {is_gold:.2f}）"
        else:
            assert is_gold < 0.3, f"{name} 不应有金圈"
    for el in ELEMENT_IDS:
        a = rgba(f"icon_el_{el}.png") / 255.0
        plain = rgba("icon_houde.png") / 255.0
        zone = (r > 21) & (r < 23)
        d_el = np.abs(a[..., :3][zone].mean(0) - U.EL_WASH[el]).max()
        d_plain = np.abs(plain[..., :3][zone].mean(0) - U.EL_WASH[el]).max()
        assert d_el < d_plain + 0.01, f"icon_el_{el} 的圆底应染 {el} 的淡彩"


def test_new_frames():
    """第二批的框：各类色弧颜色；心灯点亮有暖灯晕、未点亮褪成淡墨；夜签是朱砂双圈、没有墨圈；等级徽章是金圈、中间空。"""
    m = meta()["files"]
    r = radial(N)
    want_arc = {"supply": U.NEUTRAL_ARC, "currency": U.NEUTRAL_ARC}
    for n in NEW_ICONS:
        e = m[n]
        a = rgba(n) / 255.0
        if e["kind"] in ("encounter", "buff"):
            want = U.ACC_INK[e["id"]]
        elif e["kind"] == "meta":
            want = U.LAMP_ARC if e["lit"] else U.QING
        elif e["kind"] == "hud" and e["id"] in ("kills", "pause", "dash"):
            want = U.NEUTRAL_ARC
        elif e["kind"] == "hud" and e["id"] == "ult":
            want = U.LAMP_ARC
        else:
            want = want_arc.get(e["kind"])
        if want is not None:
            got = arc_color(a)
            assert np.abs(got - want).max() < 0.2, f"{n} 色弧颜色 {np.round(got * 255)} 与 {np.round(np.asarray(want) * 255)} 不符"
    disc = r < 22
    for mid in META_IDS:
        lit = rgba(f"icon_meta_{mid}.png")[..., :3][disc] / 255.0
        off = rgba(f"icon_meta_{mid}_off.png")[..., :3][disc] / 255.0
        chroma_lit = np.percentile(lit.max(-1) - lit.min(-1), 99)
        chroma_off = np.percentile(off.max(-1) - off.min(-1), 99)  # 宣纸本身的彩度约 0.13
        assert chroma_off < 0.16 and chroma_lit > chroma_off + 0.08, f"icon_meta_{mid}_off 应褪成淡墨（彩度 {chroma_off:.3f} / 点亮 {chroma_lit:.3f}）"
        # 两版的纸底是同一个种子画的，逐像素相减后取中位数（多数像素是纸底）就是灯晕带来的暖色
        warm = np.median((lit[:, 0] - lit[:, 2]) - (off[:, 0] - off[:, 2]))
        assert warm > 0.02, f"icon_meta_{mid} 应有暖色灯晕（暖色差 {warm:.3f}）"
    for o in OMEN_IDS:
        a = rgba(f"icon_omen_{o}.png") / 255.0
        for rad, tol, need in ((27.2, 0.6, 0.6), (24.3, 0.22, 0.5)):
            band = (np.abs(r - rad) < tol) & (a[..., 3] > 0.5)
            frac = is_vermilion(a[..., :3][band]).mean()
            assert frac > need, f"icon_omen_{o} 在 r={rad} 处应是朱砂圈（朱色占 {frac:.2f}）"
        ink = lum(a[..., :3][(r > 26.5) & (r < 29.5) & (a[..., 3] > 0.5)]) < 0.25
        assert ink.mean() < 0.1, f"icon_omen_{o} 不应有墨圈"
    for name in M25_ICONS:
        e = m[name]
        a = rgba(name) / 255.0
        if e["kind"] == "omen":
            for rad, tol, need in ((27.2, 0.6, 0.6), (24.3, 0.22, 0.5)):
                band = (np.abs(r - rad) < tol) & (a[..., 3] > 0.5)
                frac = is_vermilion(a[..., :3][band]).mean()
                assert frac > need, f"{name} 在 r={rad} 处应是朱砂圈（朱色占 {frac:.2f}）"
            continue
        if e["kind"] == "affix":
            rs, th = design_radius(NA), np.mod(np.degrees(np.arctan2(*(np.mgrid[0:NA, 0:NA] + 0.5 - NA / 2))), 360)
            band = (np.abs(rs - 23.6) < 0.8) & (th > 70) & (th < 220)
            got = a[..., :3][band].mean(0)
            assert np.abs(got - M.AFFIX_ARC).max() < 0.2, f"{name} 色弧颜色 {np.round(got * 255)} 应是朱砂"
            continue
        if e["kind"] == "charm":
            band = (np.abs(r - 24.2) < 0.5) & (a[..., 3] > 0.5)
            frac = is_vermilion(a[..., :3][band]).mean()
            assert frac > 0.6, f"{name} 墨圈内侧应绕一圈红绳（朱色占 {frac:.2f}）"
            yy, xx = (np.mgrid[0:N, 0:N] + 0.5) / D
            knot = (np.abs(xx - 32.0) < 2.0) & (np.abs(yy - 5.2) < 2.0)
            assert is_vermilion(a[..., :3][knot]).mean() > 0.5, f"{name} 顶上应有一个红色的中国结"
            continue
        if e["kind"] == "passive":
            want = U.EL_INK[e["el"]] if e.get("el") else U.NEUTRAL_ARC
        else:
            want = {"currency": U.NEUTRAL_ARC, "encounter": M.MERCHANT_INK, "hub": M.HUB_ARC}[e["kind"]]
        got = arc_color(a)
        assert np.abs(got - want).max() < 0.2, f"{name} 色弧颜色 {np.round(got * 255)} 与 {np.round(np.asarray(want) * 255)} 不符"
    a = rgba("icon_level.png") / 255.0
    rim = (np.abs(r - U.F_LEVEL["gold_rim"][0]) < 1.0)
    g = a[..., :3][rim]
    gold = ((g[:, 0] > 0.55) & (g[:, 0] > g[:, 2] + 0.25)).mean()
    assert gold > 0.7, f"icon_level 应有金圈（金色占 {gold:.2f}）"
    centre = lum(a[..., :3][r < 17])
    assert centre.std() < 0.05 and centre.mean() > 0.8, "icon_level 中间应留空（给数字）"


# ============================================================== 朱砂印章


def seal_spec(n: str) -> dict:
    return next(s for s in Z.seal_specs() if s["fname"] == n[:-4])


def expected_glyph(spec):
    """按印章的章法在像素分辨率上重新排一遍字（不带刀口毛糙），得到期望的印泥（白文格子里是 1 - 字，朱文格子里是字）。"""
    w1, h1 = spec["size1"]
    P = U.W.Painter(int(w1), int(h1), 0, ss=1)
    want = np.zeros(P.X.shape)
    zone = np.zeros(P.X.shape, dtype=bool)
    for ch, cell, stretch, style in Z.glyph_layout(spec):
        g = Z.glyph_field(P, ch, cell, stretch=stretch)
        x0, y0, x1, y1 = cell
        z = (P.X >= x0) & (P.X <= x1) & (P.Y >= y0) & (P.Y <= y1)
        want = np.where(z, (1.0 - g) if style == "白文" else np.maximum(want, g), want)
        zone |= z
    return want, zone


def test_seals():
    """印章：外圈透明、圆印四角透明；印泥是朱砂（不透明像素里朱色占绝大多数）；覆盖面积合理；
    印文确实在（与重新排的字形高度相关）；稀有度印里有一道稀有度色的细边栏。"""
    m = meta()["files"]
    for n in ALL_SEALS:
        e, spec = m[n], seal_spec(n)
        a = rgba(n) / 255.0
        al = a[..., 3]
        h, w = al.shape
        border = np.concatenate([al[0], al[-1], al[:, 0], al[:, -1]])
        assert border.max() == 0, f"{n} 最外一圈应全透明"
        if spec["shape"] == "round":
            yy, xx = np.mgrid[0:h, 0:w] + 0.5
            out = np.hypot(xx - w / 2, yy - h / 2) / D > min(w, h) / (2 * D) - 0.2  # 印边毛糙最多外出约 1 像素
            assert al[out].max() < 0.05, f"{n} 圆印外应透明"
        opaque = al > 0.5
        verm = is_vermilion(a[..., :3][opaque]).mean()
        assert verm > 0.85, f"{n} 不透明处朱色只占 {verm:.2f}"
        cover = opaque.mean()
        lo, hi = {"白文": (0.45, 0.85), "朱文": (0.15, 0.6), "朱白相间": (0.3, 0.7)}[e["style"]]
        assert lo < cover < hi, f"{n}（{e['style']}）印泥覆盖 {cover:.2f} 不在 {lo}..{hi}"
        want, zone = expected_glyph(spec)
        corr = np.corrcoef(al[zone], want[zone])[0, 1]
        assert corr > 0.7, f"{n} 的印文与“{spec['text']}”对不上（相关 {corr:.2f}）"
        if e["group"] == "rarity":
            acc = np.array(S.hex_to_rgb(e["accent"])) / 255.0
            rgb = a[..., :3][opaque]
            d_acc = np.abs(rgb - U.mixc(U.mixc(acc, U.ZHUSHA, 0.25), U.PAPER, 0.15)).max(-1)
            frac = (d_acc < 0.12).mean()
            assert frac > 0.01, f"{n} 应有稀有度色 {e['accent']} 的细边栏（占 {frac:.3f}）"


def test_reaction_seals_family():
    """五行反应印与共鸣印一眼分得开：方的（四角有印泥，共鸣印是圆的、四角透明），上半是实的红（白文块），下半主要是纸（朱文）；
    外边与细边栏之间有一道空（双边栏）。"""
    for n in REACT_SEALS:
        al = rgba(n)[..., 3] / 255.0
        h, w = al.shape
        yy, xx = (np.mgrid[0:h, 0:w] + 0.5) / D
        corner = np.hypot(np.abs(xx - 32.0) - 28.2, np.abs(yy - 32.0) - 28.2) < 0.8  # 圆角外边上（圆印在这里早已出了印面）
        assert al[corner].mean() > 0.3, f"{n} 应是方印（四角有印泥，{al[corner].mean():.2f}）"
        block, cells, line_at = Z.zb_geometry(seal_spec(n))
        bx0, by0, bx1, by1 = block
        top = (xx > bx0 + 1) & (xx < bx1 - 1) & (yy > by0 + 1) & (yy < by1 - 1)
        bottom = (xx > bx0 + 1) & (xx < bx1 - 1) & (yy > by1 + 4) & (yy < 64 - by0 - 1)
        t_, b_ = al[top].mean(), al[bottom].mean()
        assert t_ > 0.45 and b_ < 0.42 and t_ - b_ > 0.15, f"{n} 上半应是白文块（{t_:.2f}）、下半是朱文（{b_:.2f}）"
        cols = np.abs(xx[0] - 32.0) < 10.0
        prof = np.array([al[i, cols].mean() for i in range(int(10 * D))])  # 正中上方一行一行往下
        assert prof.max() > 0.6 and prof[np.argmax(prof > 0.6) :].min() < 0.5, f"{n} 上边应是两道（外边 + 细边栏，中间有空）"
    for n in ("seal_rui.png", "seal_fen.png"):
        al = rgba(n)[..., 3] / 255.0
        yy, xx = (np.mgrid[0 : al.shape[0], 0 : al.shape[1]] + 0.5) / D
        corner = np.hypot(np.abs(xx - 32.0) - 28.2, np.abs(yy - 32.0) - 28.2) < 0.8
        assert al[corner].mean() < 0.05, "共鸣印应是圆的"


def test_seals_distinct():
    """同尺寸的印章缩到 32 像素宽后彼此不同（不是同一枚印换了个字看不出来）。"""
    groups: dict[tuple, list[str]] = {}
    for n in ALL_SEALS:
        groups.setdefault(SEAL_SIZES_2X[n[:-4]], []).append(n)
    for size, ns in groups.items():
        sm = {}
        for n in ns:
            im = Image.open(U.UI_DIR / n).convert("RGBA")
            sm[n] = np.asarray(im.resize((32, round(32 * im.height / im.width)), Image.LANCZOS), dtype=np.float64)[..., 3] / 255.0
        for a_, b_ in itertools.combinations(ns, 2):
            dv = np.abs(sm[a_] - sm[b_]).mean()
            assert dv > 0.06, f"{a_} 与 {b_} 缩小后太像（差 {dv:.3f}）"


# ============================================================== 确定性、体积、两种密度


def test_deterministic():
    again = U.build()
    assert [f"{k}.png" for k in again] == ALL
    for key, (img, _, _) in again.items():
        disk = np.asarray(Image.open(U.UI_DIR / f"{key}.png").convert("RGBA"))
        assert (np.asarray(img) == disk).all(), f"{key} 两次生成结果不一致"


def test_total_size():
    total = sum(p.stat().st_size for p in U.UI_DIR.glob("*.png"))
    budget = {1: 1150, 2: 3200}[int(D)]  # M2.5 加了 38 个图标与印章（原来 800 / 2200）
    assert total < budget * 1024, f"图标总体积 {total / 1024:.1f} KB 超过 {budget} KB"


def test_density_2x_same_art():
    if D != 2:
        return
    res = testkit.density_consistency(U.UI_DIR, V.OUT / "assets" / "ui", ALL, max_alpha_diff=4.0, max_rgb_diff=4.0)
    assert len(res) == len(ALL), "1 倍图标不全，先跑一遍 1 倍"


def main() -> int:
    U.main()
    tests = [(k, v) for k, v in globals().items() if k.startswith("test_") and callable(v)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"PASS  {name}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL  {name}: {e}")
        except Exception:  # noqa: BLE001
            failed += 1
            print(f"ERROR {name}")
            traceback.print_exc()
    print(f"\n{len(tests) - failed}/{len(tests)} 通过（密度 {D:g}x）")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
