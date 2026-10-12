"""美术自检的公共小工具：两种密度都跑、1 倍基准核对、2 倍与 1 倍的一致性。纯 numpy/Pillow，不依赖 pytest。"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
GOLDEN = HERE / "golden_1x.json"
DENSITIES = ("1", "2")


def run_all_densities(script: str) -> int | None:
    """没有设 LANTERN_ART_DENSITY 时，用子进程把本测试在 1 倍、2 倍各跑一遍，返回退出码；
    已经设了（子进程里）就返回 None，由调用者在本进程里跑这一种密度。"""
    if os.environ.get("LANTERN_ART_DENSITY"):
        return None
    worst = 0
    for d in DENSITIES:
        print(f"\n======== 密度 {d}x ========", flush=True)
        env = {**os.environ, "LANTERN_ART_DENSITY": d}
        r = subprocess.run([sys.executable, script, *sys.argv[1:]], env=env)
        worst = max(worst, r.returncode)
    print("\n两种密度：" + ("全部通过" if worst == 0 else "有失败"))
    return worst


def check_golden(assets_dir: Path, folders) -> None:
    """1 倍产物与密度改造前的基准比对：已有 PNG 逐字节（md5）相同；meta.json 的顶层字段与已有条目不变，
    新条目只能追加在后面。"""
    g = json.loads(GOLDEN.read_text(encoding="utf-8"))
    n = 0
    for key, want in g["png_md5"].items():
        folder, name = key.split("/")
        if folder not in folders:
            continue
        got = hashlib.md5((assets_dir / folder / name).read_bytes()).hexdigest()
        assert got == want, f"1 倍 {key} 与改造前不同（md5 {got} != {want}）"
        n += 1
    assert n > 0, "基准里没有这些文件夹"
    for folder in folders:
        old = g["meta"][folder]
        new = json.loads((assets_dir / folder / "meta.json").read_text(encoding="utf-8"))
        for k, v in old.items():
            if k != "files":
                assert new.get(k) == v, f"{folder}/meta.json 顶层字段 {k} 变了：{new.get(k)!r} != {v!r}"
        assert list(new["files"])[: len(old["files"])] == list(old["files"]), f"{folder}/meta.json 已有条目的顺序变了"
        changes = g.get("deliberate_meta_changes", {}).get(folder, {})
        for name, entry in old["files"].items():
            want = {**entry, **changes.get(name, {})}
            assert new["files"][name] == want, f"{folder}/meta.json 的 {name} 条目变了"


def density_consistency(dir_2x: Path, dir_1x: Path, names, *, max_alpha_diff: float = 6.0, max_rgb_diff: float = 6.0) -> dict:
    """2 倍贴图按 2×2 平均缩回 1 倍后应与 1 倍贴图基本一致（同一张画，只是更细）。
    比较 alpha 的平均差，以及两边都不透明处的颜色平均差（0..255）。返回 {名字: (alpha 差, 颜色差)}。"""
    out = {}
    for n in names:
        p1, p2 = dir_1x / n, dir_2x / n
        if not p1.exists():
            continue
        a1 = np.asarray(Image.open(p1).convert("RGBA"), dtype=np.float64)
        a2 = np.asarray(Image.open(p2).convert("RGBA"), dtype=np.float64)
        h, w = a1.shape[:2]
        assert a2.shape[:2] == (2 * h, 2 * w), f"{n}: 2 倍尺寸 {a2.shape[:2]} 不是 1 倍 {a1.shape[:2]} 的两倍"
        al2 = a2[..., 3] / 255.0
        pm = (a2[..., :3] * al2[..., None]).reshape(h, 2, w, 2, 3).mean((1, 3))
        al = al2.reshape(h, 2, w, 2).mean((1, 3))
        rgb2 = pm / np.maximum(al, 1e-6)[..., None]
        da = np.abs(al * 255.0 - a1[..., 3]).mean()
        both = (al > 0.6) & (a1[..., 3] > 150)
        dc = np.abs(rgb2 - a1[..., :3])[both].mean() if both.any() else 0.0
        out[n] = (da, dc)
        assert da <= max_alpha_diff, f"{n}: 2 倍与 1 倍的 alpha 平均差 {da:.1f} 太大（不像同一张画）"
        assert dc <= max_rgb_diff, f"{n}: 2 倍与 1 倍的颜色平均差 {dc:.1f} 太大"
    return out
