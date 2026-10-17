#!/usr/bin/env python3
"""ui_icons_new.py（新法器图标）的自检：纯 assert，不依赖 pytest。

先重新生成，再查：id 和 assets/data/weapons.ron 对得上、meta 与尺寸、圆外透明圆内不透明、32 像素下有明暗层次且
彼此分得开、再渲一遍逐像素相同（确定性）。不设 LANTERN_ART_DENSITY 时在 1 倍、2 倍各跑一遍（子进程）。

用法（在仓库根目录下）：
  art/.venv/bin/python art/post/test_ui_icons_new.py
"""

from __future__ import annotations

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

import ui_icons_new as N  # noqa: E402

D = N.V.D
SIZE = int(round(64 * D))
ROOT = HERE.parents[1]
OLD_WEAPONS = {"lamp", "sword", "bell", "crane", "seal"}


def names() -> list[str]:
    return [f for f, *_ in N.specs()]


def rgba(name: str) -> np.ndarray:
    return np.asarray(Image.open(N.OUT_DIR / f"{name}.png").convert("RGBA"))


def lum(rgb: np.ndarray) -> np.ndarray:
    return rgb @ np.array([0.2126, 0.7152, 0.0722])


def test_ids_match_data():
    text = (ROOT / "assets" / "data" / "weapons.ron").read_text(encoding="utf-8")
    ids = set(re.findall(r'id: "([a-z_]+)", name:', text))
    assert ids - OLD_WEAPONS == set(N.WEAPONS_NEW), f"新法器的 id 和 weapons.ron 对不上：{sorted(ids - OLD_WEAPONS)}"


def test_meta_and_sizes():
    N.main()
    meta = json.loads((N.OUT_DIR / "meta.json").read_text(encoding="utf-8"))
    assert meta["name"] == "ui", "帧名要是 ui/icon_*"
    assert list(meta["files"]) == [f"{n}.png" for n in names()]
    for n in names():
        e = meta["files"][f"{n}.png"]
        assert e["kind"] in ("weapon", "weapon_evo") and e["id"] in N.WEAPONS_NEW and e["name"], n
        im = Image.open(N.OUT_DIR / f"{n}.png")
        assert im.mode == "RGBA" and im.size == (SIZE, SIZE), f"{n} 尺寸 {im.size}"


def test_disc():
    yy, xx = np.mgrid[0:SIZE, 0:SIZE]
    r = np.hypot((xx + 0.5) / D - 32.0, (yy + 0.5) / D - 32.0)
    for n in names():
        al = rgba(n)[..., 3]
        assert al[r > 31.5].max() <= 10, f"{n} 圆外应透明"
        assert al[r < 20].min() > 250, f"{n} 圆底内部应不透明"


def test_readable_and_distinct_at_32px():
    yy, xx = np.mgrid[0:32, 0:32]
    inner = np.hypot(xx + 0.5 - 16, yy + 0.5 - 16) < 10.5
    smalls = {}
    for n in names():
        s = np.asarray(Image.open(N.OUT_DIR / f"{n}.png").convert("RGBA").resize((32, 32), Image.LANCZOS), np.float64)[..., :3] / 255
        smalls[n] = s
        L = lum(s)[inner]
        assert L.std() > 0.08, f"{n} 在 32 像素下物件对比太低（std {L.std():.3f}）"
        assert np.percentile(L, 95) - np.percentile(L, 5) > 0.25, f"{n} 在 32 像素下缺少深浅层次"
    worst = min((np.abs(smalls[a] - smalls[b])[inner].mean(), f"{a} / {b}") for a, b in itertools.combinations(names(), 2))
    assert worst[0] > 0.04, f"32 像素下两个图标太像：{worst[1]}（差 {worst[0]:.3f}）"


def test_deterministic():
    for i, n in enumerate(names()):
        assert (np.asarray(N.make(i)) == rgba(n)).all(), f"{n} 两次渲染不一样"


def main() -> int:
    tests = [v for k, v in globals().items() if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  通过  {t.__name__}")
        except Exception:  # noqa: BLE001
            failed += 1
            print(f"  失败  {t.__name__}")
            traceback.print_exc()
    print(f"{len(tests) - failed}/{len(tests)} 通过")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
