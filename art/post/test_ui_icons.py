#!/usr/bin/env python3
"""ui_icons.py 的自检：纯 assert，不依赖 pytest。

每次运行先重新生成，再单独渲染一遍逐像素比对（确定性）。
不设 LANTERN_ART_DENSITY 时自动在 1 倍、2 倍各跑一遍（子进程）；设了就只测那一种密度。

用法（在仓库根目录下）：
  art/.venv/bin/python art/post/test_ui_icons.py
"""

from __future__ import annotations

import json
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

V = U.V
S = U.S
D = V.D
N = int(round(64 * D))

WEAPON_IDS = ["lamp", "sword", "bell", "crane", "seal"]
PASSIVE_IDS = ["changming", "luxin", "jianyi", "ruimu", "jingxin", "yinhun", "zhezhi", "jixing", "houde", "panshi"]
ELEMENT_IDS = ["metal", "wood", "water", "fire", "earth"]
EXPECTED = (
    [f"icon_{w}.png" for w in WEAPON_IDS]
    + [f"icon_{w}_evo.png" for w in WEAPON_IDS]
    + [f"icon_{p}.png" for p in PASSIVE_IDS]
    + [f"icon_el_{e}.png" for e in ELEMENT_IDS]
)


def rgba(name: str) -> np.ndarray:
    return np.asarray(Image.open(U.UI_DIR / name).convert("RGBA"), dtype=np.float64)


def meta() -> dict:
    return json.loads((U.UI_DIR / "meta.json").read_text(encoding="utf-8"))


def at32(name: str) -> np.ndarray:
    """缩到 32 像素（界面上最小的显示尺寸），铺在纸色上。"""
    im = Image.open(U.UI_DIR / name).convert("RGBA").resize((32, 32), Image.LANCZOS)
    a = np.asarray(im, dtype=np.float64) / 255.0
    bg = np.array(S.hex_to_rgb(S.PAPER)) / 255.0
    return a[..., :3] * a[..., 3:] + bg * (1 - a[..., 3:])


def lum(rgb: np.ndarray) -> np.ndarray:
    return rgb @ np.array([0.299, 0.587, 0.114])


def radial(n: int) -> np.ndarray:
    yy, xx = np.mgrid[0:n, 0:n] + 0.5
    return np.hypot(xx - n / 2, yy - n / 2) / D  # 以 1 倍像素计的半径


def test_meta_and_sizes():
    m = meta()
    assert m["px_per_unit"] == S.PX_PER_UNIT
    files = m["files"]
    assert list(files) == EXPECTED, f"图标列表不符：{sorted(set(files) ^ set(EXPECTED))}"
    assert {p.name for p in U.UI_DIR.glob("*.png")} == set(EXPECTED), "ui/ 里多出或缺少文件"
    passives = json.loads(json.dumps(U.PASSIVES))
    for name, e in files.items():
        assert tuple(e["size"]) == (N, N), f"{name} meta size {e['size']} != {(N, N)}"
        assert tuple(e["anchor"]) == (0.5, 0.5), f"{name} 锚点应居中"
        assert e["blend"] == "normal" and e["tint"] is False and e["color"] == "full", f"{name} 应为全彩、正常混合"
        for k in ("kind", "id", "el", "name", "note"):
            assert k in e, f"{name} meta 缺少 {k}"
        im = Image.open(U.UI_DIR / name)
        assert im.size == (N, N) and im.mode == "RGBA", f"{name} 实际 {im.size} {im.mode}"
        if e["kind"] == "passive":
            assert passives[e["id"]][1] == e["el"], f"{name} 五行与 src/data/passives.ts 不符"


def test_borders_and_disc():
    r = radial(N)
    for name in EXPECTED:
        a = rgba(name)
        al = a[..., 3]
        border = np.concatenate([al[0], al[-1], al[:, 0], al[:, -1]])
        assert border.max() == 0, f"{name} 最外一圈应全透明"
        assert al[r < 20].min() > 250, f"{name} 圆底内部应不透明"
        assert al[r > 31.5].max() <= 10, f"{name} 圆外应透明"
        ring = (r > 26.5) & (r < 29.5)
        dark = lum(a[..., :3][ring] / 255.0) < 0.25
        assert dark.mean() > 0.5, f"{name} 墨圈不完整（暗像素只占 {dark.mean():.2f}）"


def test_readable_at_32px():
    """缩到 32 像素：物件区域要有足够的明暗对比，且各图标彼此不同。"""
    smalls = {}
    yy, xx = np.mgrid[0:32, 0:32] + 0.5
    inner = np.hypot(xx - 16, yy - 16) < 10.5
    for name in EXPECTED:
        s = at32(name)
        smalls[name] = s
        L = lum(s)[inner]
        assert L.std() > 0.1, f"{name} 在 32 像素下物件对比太低（std {L.std():.3f}）"
        assert np.percentile(L, 95) - np.percentile(L, 5) > 0.3, f"{name} 在 32 像素下缺少深浅层次"
    names = list(smalls)
    worst = (1.0, "")
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            dv = np.abs(smalls[names[i]] - smalls[names[j]])[inner].mean()
            worst = min(worst, (dv, f"{names[i]} / {names[j]}"))
    assert worst[0] > 0.05, f"32 像素下两个图标太像：{worst[1]}（差 {worst[0]:.3f}）"


def test_family_colors():
    """五行色弧在墨圈内侧；进化图标外有金圈；五行图标的圆底染了本行的淡彩。"""
    m = meta()["files"]
    r = radial(N)
    th = np.degrees(np.arctan2(*(np.mgrid[0:N, 0:N] + 0.5 - N / 2)))  # atan2(y, x)
    for name, e in m.items():
        a = rgba(name) / 255.0
        want = U.EL_INK[e["el"]]
        band = (np.abs(r - 24.3) < 0.5) & (np.mod(th, 360) > 70) & (np.mod(th, 360) < 220)
        got = a[..., :3][band].mean(0)
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


def test_deterministic():
    again = U.build()
    for key, (img, _, _) in again.items():
        disk = np.asarray(Image.open(U.UI_DIR / f"{key}.png").convert("RGBA"))
        assert (np.asarray(img) == disk).all(), f"{key} 两次生成结果不一致"


def test_total_size():
    total = sum(p.stat().st_size for p in U.UI_DIR.glob("*.png"))
    assert total < 320 * 1024 * D * D, f"图标总体积 {total / 1024:.1f} KB 超过 {320 * D * D:.0f} KB"


def test_density_2x_same_art():
    if D != 2:
        return
    res = testkit.density_consistency(U.UI_DIR, V.OUT / "assets" / "ui", EXPECTED, max_alpha_diff=4.0, max_rgb_diff=4.0)
    assert len(res) == len(EXPECTED), "1 倍图标不全，先跑一遍 1 倍"


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
