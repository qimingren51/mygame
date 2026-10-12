#!/usr/bin/env python3
"""ui_skin.py 的自检：纯 assert，不依赖 pytest。

先运行 ui_skin.py 出图，再运行本测试：本测试在进程里重新生成一遍，逐像素与磁盘上的文件比对（确定性），
另起一个 LANTERN_ART_DENSITY=2 的子进程生成几件，核对与密度无关。约 1 分钟。

检查项：
  - skin.json 与文件一一对应，字段、尺寸、切片合法（切片在图内、中间留有正的区域）；
  - 平铺区（tile）首尾相接没有接缝（环绕处的差别不比相邻两列 / 两行之间大）；
  - 拉伸带（stretch）沿拉伸方向完全一致（进度条、按钮拉多长都不出色阶）；
  - 切片线两侧连续（角上的笔画、光晕没有越过切片线、被拉伸带截断）；平铺带两头和中间一样（角上的东西没有漏进来）；
  - 进度条填充的两端笔头都在切片以内，中段是满的；
  - 直通 alpha：边缘的半透明像素颜色不变暗（不是预乘），全透明像素的颜色由邻近的可见像素扩展而来；
  - 可染色贴图 RGB 恒为白；nine_slice 与 Bevy 规则一致（原尺寸不变、平铺按原尺寸重复）；
  - 整个 skin 目录不超过 3 MB。

用法（在仓库根目录下）：
  art/.venv/bin/python art/post/ui_skin.py
  art/.venv/bin/python art/post/test_ui_skin.py
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import traceback
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import ui_skin as U  # noqa: E402

SKIN = U.SKIN_DIR
EXPECTED = [
    "panel", "panel_dark", "overlay_vignette",
    "card_fan", "card_ling", "card_xuan", "card_tian", "card_omen", "card_focus", "note_box", "note_box_hi",
    "btn", "btn_focus", "btn_pressed", "btn_disabled",
    "btn_primary", "btn_primary_focus", "btn_primary_pressed", "btn_primary_disabled", "pill", "pill_on",
    "slot_l", "slot_l_empty", "slot_l_evo", "slot_s", "slot_s_empty", "slot_s_evo",
    "bar_track", "bar_fill_hp", "bar_fill_xp", "bar_fill_boss", "bar_fill_shield", "bar_fill_unlock", "pip", "pip_on",
    "toast", "toast_big", "chip", "chip_dark",
    "divider", "scroll_body", "scroll_end", "arrow_marker", "focus_ring", "menu_hl",
]  # fmt: skip
FILLS = ["bar_fill_hp", "bar_fill_xp", "bar_fill_boss", "bar_fill_shield", "bar_fill_unlock"]
BUDGET = 3 * 1024 * 1024
GLOWS = ["card_focus", "focus_ring", "pip_on"]
INDEPENDENT = ["card_tian", "btn_focus", "slot_l_evo", "panel_dark", "scroll_body", "bar_fill_hp"]


def manifest() -> dict:
    return json.loads((SKIN / "skin.json").read_text(encoding="utf-8"))


def rgba(name: str) -> np.ndarray:
    return np.asarray(Image.open(SKIN / f"{name}.png").convert("RGBA"), dtype=np.float64)


def premul(a: np.ndarray) -> np.ndarray:
    """0..255 的预乘 RGBA（比较内容时用，全透明像素的颜色不算）。"""
    al = a[..., 3:] / 255.0
    return np.concatenate([a[..., :3] * al, a[..., 3:]], -1)


def lum(rgb: np.ndarray) -> np.ndarray:
    return rgb @ np.array([0.299, 0.587, 0.114])


def regions(e: dict) -> dict:
    """九宫格各区域的 (行切片, 列切片)。"""
    w, h = e["size"]
    l, t, r, b = e["slice"]
    return {
        "c": (slice(t, h - b), slice(l, w - r)),
        "t": (slice(0, t), slice(l, w - r)),
        "b": (slice(h - b, h), slice(l, w - r)),
        "l": (slice(t, h - b), slice(0, l)),
        "r": (slice(t, h - b), slice(w - r, w)),
    }


def sliced(e: dict) -> bool:
    return any(e["slice"])


# ============================================================== 清单


def test_manifest():
    m = manifest()
    assert set(m) == {"scale", "items"}, f"skin.json 顶层字段不对：{sorted(m)}"
    assert m["scale"] == 2
    items = m["items"]
    assert sorted(items) == sorted(EXPECTED), f"条目不符：{sorted(set(items) ^ set(EXPECTED))}"
    on_disk = {p.name for p in SKIN.iterdir()}
    assert on_disk == {f"{n}.png" for n in EXPECTED} | {"skin.json"}, f"skin/ 里多出或缺少文件：{sorted(on_disk ^ ({f'{n}.png' for n in EXPECTED} | {'skin.json'}))}"
    keys = {"file", "size", "slice", "center", "sides", "text", "note"}
    for name, e in items.items():
        want = keys | ({"tint"} if name == "arrow_marker" else set())
        assert set(e) == want, f"{name}: 字段 {sorted(e)}"
        assert e["file"] == f"{name}.png"
        im = Image.open(SKIN / e["file"])
        assert im.mode == "RGBA", f"{name}: {im.mode}"
        assert list(im.size) == e["size"], f"{name}: 实际 {im.size}，清单 {e['size']}"
        assert e["center"] in ("stretch", "tile") and e["sides"] in ("stretch", "tile")
        assert re.fullmatch(r"#[0-9a-f]{6}", e["text"]), f"{name}: text {e['text']}"
        assert isinstance(e["note"], str) and re.search(r"[一-鿿]", e["note"]), f"{name}: note 要一句中文"
        sl = e["slice"]
        assert len(sl) == 4 and all(isinstance(v, int) and v >= 0 for v in sl), f"{name}: slice {sl}"
        w, h = e["size"]
        l, t, r, b = sl
        if sliced(e):
            assert w - l - r > 0 and h - t - b > 0, f"{name}: 切片 {sl} 没给中间留位置（{w}×{h}）"
            if t == b == 0:
                assert e["sides"] == "stretch", f"{name}: 横向九宫格的两端只能拉伸（平铺会把笔头竖着重复）"
            if l == r == 0:
                assert e["center"] == "tile" or e["sides"] == "stretch"
    assert items["arrow_marker"]["tint"] is True
    assert m == U.manifest({n: Image.open(SKIN / f"{n}.png") for n in EXPECTED}), "skin.json 与 ui_skin.specs() 不一致"


def test_tint_white():
    a = rgba("arrow_marker")
    vis = a[..., 3] > 0
    assert vis.any()
    assert (a[..., :3][vis] == 255).all(), "arrow_marker 可见像素的 RGB 应恒为 255（染色用）"


# ============================================================== 平铺接缝


def seam_ratio(p: np.ndarray, axis: int) -> tuple[float, float]:
    """沿 axis（1=列、0=行）方向：首尾环绕处的平均差，与相邻两列（行）平均差的均值。"""
    if axis == 0:
        p = p.transpose(1, 0, 2)
    adj = np.abs(np.diff(p, axis=1)).mean(axis=(0, 2))
    wrap = float(np.abs(p[:, 0] - p[:, -1]).mean())
    return wrap, float(adj.mean())


def test_tile_seams():
    n = 0
    for name, e in manifest()["items"].items():
        if not sliced(e):
            continue
        p = premul(rgba(name))
        reg = regions(e)
        checks = []
        if e["center"] == "tile":
            checks += [("c", 1), ("c", 0)]
        if e["sides"] == "tile":
            checks += [("t", 1), ("b", 1), ("l", 0), ("r", 0)]
        for key, axis in checks:
            ys, xs = reg[key]
            sub = p[ys, xs]
            if sub.size == 0 or min(sub.shape[:2]) < 2:
                continue
            wrap, adj = seam_ratio(sub, axis)
            assert wrap <= 1.6 * adj + 0.4, f"{name}: 平铺区 {key} 沿{'x' if axis else 'y'}的接缝差 {wrap:.2f}，相邻差均值 {adj:.2f}"
            n += 1
    assert n >= 20, f"只检查了 {n} 个平铺方向"
    print(f"  平铺接缝：{n} 个方向")


# ============================================================== 拉伸带


def test_stretch_bands_uniform():
    n = 0
    for name, e in manifest()["items"].items():
        if not sliced(e):
            continue
        p = premul(rgba(name))
        w, h = e["size"]
        l, t, r, b = e["slice"]
        bands = []  # (区域, 沿哪个方向必须一致：1=沿 x 每列相同，0=沿 y 每行相同)
        if e["center"] == "stretch":
            if l or r:
                bands.append(((slice(t, h - b), slice(l, w - r)), 1))
            if t or b:
                bands.append(((slice(t, h - b), slice(l, w - r)), 0))
        if e["sides"] == "stretch":
            if t:
                bands.append(((slice(0, t), slice(l, w - r)), 1))
            if b:
                bands.append(((slice(h - b, h), slice(l, w - r)), 1))
            if (t or b) and l:
                bands.append(((slice(t, h - b), slice(0, l)), 0))
            if (t or b) and r:
                bands.append(((slice(t, h - b), slice(w - r, w)), 0))
        for (ys, xs), axis in bands:
            sub = p[ys, xs]
            ref = sub[:, :1] if axis == 1 else sub[:1, :]
            dev = float(np.abs(sub - ref).max())
            assert dev <= 1.0, f"{name}: 拉伸带 {ys},{xs} 沿{'x' if axis else 'y'}不一致（最大差 {dev:.1f}/255），拉伸后会出色阶"
            n += 1
    assert n >= 40, f"只检查了 {n} 条拉伸带"
    print(f"  拉伸带：{n} 条")


def test_fill_ends():
    for name in FILLS:
        e = manifest()["items"][name]
        a = rgba(name)[..., 3] / 255.0
        w, _ = e["size"]
        l, _, r, _ = e["slice"]
        assert a[:, :2].max() < 0.1 and a[:, -2:].max() < 0.1, f"{name}: 笔头碰到了贴图左右边"
        band = a[:, l]
        assert band.max() > 0.95, f"{name}: 中段不满（{band.max():.2f}）"
        # 两端的笔头确实在切片里收住：切片内最外 20% 的平均 alpha 明显低于中段
        cap_l = a[:, : max(2, l // 5)].mean()
        cap_r = a[:, w - max(2, r // 5) :].mean()
        assert cap_l < 0.6 * band.mean() and cap_r < 0.6 * band.mean(), f"{name}: 两端没有收成笔头"


# ============================================================== 切片线与角


def test_slice_lines_continuous():
    """切片线两侧的两列（行）之差不比附近相邻列（行）之差大很多：角上的笔画、光晕没有被切片线截断。"""
    n = 0
    for name, e in manifest()["items"].items():
        if not sliced(e):
            continue
        p = premul(rgba(name))
        w, h = e["size"]
        l, t, r, b = e["slice"]
        lines = [(1, l), (1, w - r)] if (l or r) else []
        lines += [(0, t), (0, h - b)] if (t or b) else []
        for axis, pos in lines:
            q = p if axis == 1 else p.transpose(1, 0, 2)
            size = q.shape[1]
            if pos <= 1 or pos >= size - 1:
                continue
            diffs = np.abs(np.diff(q, axis=1)).mean(axis=(0, 2))  # diffs[i] = |列 i+1 - 列 i|
            jump = diffs[pos - 1]
            near = np.concatenate([diffs[max(0, pos - 13) : pos - 2], diffs[pos + 1 : pos + 12]])
            ref = float(np.median(near)) if near.size else 0.0
            assert jump <= 2.5 * ref + 1.2, f"{name}: 切片线 {'x' if axis else 'y'}={pos} 两侧跳变 {jump:.2f}（附近 {ref:.2f}）"
            n += 1
    print(f"  切片线：{n} 条")


def test_no_corner_spill_into_tiles():
    """平铺带两头的几列（行）与整条带的“平均列”的差，不比带中间的列大：角上的东西没有漏进平铺区。"""
    for name, e in manifest()["items"].items():
        if not sliced(e):
            continue
        p = premul(rgba(name))
        reg = regions(e)
        keys = (["c"] if e["center"] == "tile" else []) + (["t", "b", "l", "r"] if e["sides"] == "tile" else [])
        for key in keys:
            ys, xs = reg[key]
            sub = p[ys, xs]
            if sub.size == 0:
                continue
            for axis in ((1, 0) if key == "c" else ((1,) if key in "tb" else (0,))):
                q = sub if axis == 1 else sub.transpose(1, 0, 2)
                if q.shape[1] < 24:
                    continue
                dev = np.abs(q - q.mean(axis=1, keepdims=True)).mean(axis=(0, 2))
                ends = max(dev[:6].max(), dev[-6:].max())
                inner = dev[8:-8]
                lim = max(1.8 * float(np.median(inner)) + 1.0, 1.4 * float(np.percentile(inner, 90)))
                assert ends <= lim, f"{name}: 平铺区 {key} 两头与中间不一样（{ends:.2f}，中间最多 {lim:.2f}），可能有角上的笔画漏进来"


# ============================================================== 直通 alpha 与扩色


def box_mean(x: np.ndarray, r: int) -> np.ndarray:
    """(2r+1)² 方框求和（边界补零）。"""
    k = 2 * r + 1
    pad = np.pad(x, [(r, r), (r, r)] + [(0, 0)] * (x.ndim - 2))
    c = pad.cumsum(0).cumsum(1)
    c = np.pad(c, [(1, 0), (1, 0)] + [(0, 0)] * (x.ndim - 2))
    return c[k:, k:] - c[:-k, k:] - c[k:, :-k] + c[:-k, :-k]


def test_straight_alpha_and_bleed():
    for name in EXPECTED:
        a = rgba(name)
        al = a[..., 3] / 255.0
        rgb = a[..., :3]
        vis = al > 0
        if vis.all():
            continue
        # 全透明但挨着可见像素（2 px 内）的颜色 ≈ 邻近可见像素的 alpha 加权平均
        wsum = box_mean(al, 3)
        csum = box_mean(rgb * al[..., None], 3)
        near = (~vis) & (box_mean(vis.astype(float), 2) > 0)
        if near.sum() > 20:
            ref = csum[near] / np.maximum(wsum[near], 1e-6)[:, None]
            err = float(np.median(np.abs(rgb[near] - ref).mean(-1)))
            assert err < 14.0, f"{name}: 全透明像素的颜色没有从邻近扩展过来（中位差 {err:.1f}）"
        # 直通：实心形状抗锯齿边上的半透明像素，颜色与旁边实心像素相近（预乘的话会按 alpha 变暗）
        solid = al > 0.94
        edge = (al > 0.03) & (al < 0.3) & (box_mean(solid.astype(float), 1) > 0)
        if edge.sum() > 30:
            ref = box_mean(rgb * solid[..., None], 1)[edge] / np.maximum(box_mean(solid.astype(float), 1)[edge], 1e-6)[:, None]
            ok = lum(ref) > 60
            if ok.sum() > 30:
                ratio = float(np.median(lum(rgb[edge][ok]) / lum(ref[ok])))
                assert ratio > 0.55, f"{name}: 边缘半透明像素比实心处暗很多（亮度比 {ratio:.2f}），像是预乘了 alpha"
    # 只有光晕的贴图没有实心像素：淡的光晕和浓的光晕应一样亮（预乘的话淡处发黑）
    for name in GLOWS:
        a = rgba(name)
        al = a[..., 3] / 255.0
        lo = lum(a[..., :3][(al > 0.03) & (al < 0.2)])
        hi = lum(a[..., :3][al > 0.5])
        assert lo.size > 50 and hi.size > 20
        assert np.median(lo) > 0.6 * np.median(hi), f"{name}: 淡光晕比浓处暗很多（{np.median(lo):.0f} vs {np.median(hi):.0f}）"


def test_finish_is_straight():
    """出图流程本身：同一种颜色、alpha 从 0 渐变到 1，输出的 RGB 处处等于这个颜色（直通，不预乘）。"""
    c = U.Canvas(64, 16, 0, 2)
    color = U.col("#c23a2b")
    c.over(color, np.clip(c.X / 64.0, 0, 1))
    a = np.asarray(U.finish(c, clear=False), dtype=np.float64)
    want = np.round(color * 255)
    assert np.abs(a[..., :3] - want).max() <= 1.0, "finish() 输出的颜色随 alpha 变了"
    assert a[..., 3].min() < 10 and a[..., 3].max() > 245


# ============================================================== nine_slice


def test_nine_slice_rules():
    e = manifest()["items"]["card_ling"]
    img = Image.open(SKIN / "card_ling.png")
    same = U.nine_slice(img, e["slice"], img.width, img.height, e["center"], e["sides"])
    d = np.abs(premul(np.asarray(same, dtype=np.float64)) - premul(np.asarray(img.convert("RGBA"), dtype=np.float64))).max()
    assert d <= 1.0, f"原尺寸 nine_slice 应原样返回（差 {d}）"
    l, t, r, b = e["slice"]
    cw, ch = img.width - l - r, img.height - t - b
    big = U.nine_slice(img, e["slice"], l + r + 2 * cw + 10, t + b + 2 * ch + 7, "tile", "tile")
    P = premul(np.asarray(big, dtype=np.float64))
    src = premul(np.asarray(img.convert("RGBA"), dtype=np.float64))[t : t + ch, l : l + cw]
    for oy, ox in ((0, 0), (0, cw), (ch, 0), (ch, cw)):
        got = P[t + oy : t + oy + ch, l + ox : l + ox + cw]
        assert np.abs(got - src).max() <= 1.0, "中间平铺块应按原尺寸从左上开始重复"
    # 横向九宫格：高度减半时两端按同一比例缩小，不变形
    bt = Image.open(SKIN / "btn.png")
    half = U.nine_slice(bt, [72, 0, 72, 0], 400, bt.height // 2)
    assert half.size == (400, bt.height // 2)
    cap = np.asarray(half, dtype=np.float64)[:, :36]
    ref = np.asarray(bt.resize((96, bt.height // 2), Image.BILINEAR), dtype=np.float64)[:, :36]
    assert np.abs(premul(cap) - premul(ref)).mean() < 6.0, "两端应按 min(宽比, 高比) 等比缩放"


# ============================================================== 确定性、与密度无关、体积


def md5s(names) -> dict:
    imgs = U.build(names)
    return {n: hashlib.md5(imgs[n].tobytes()).hexdigest() for n in names}


def test_determinism():
    imgs = U.build()
    for n in EXPECTED:
        disk = np.asarray(Image.open(SKIN / f"{n}.png").convert("RGBA"))
        assert np.array_equal(np.asarray(imgs[n]), disk), f"{n}: 重新生成与磁盘上的文件不同（先运行 ui_skin.py？）"
    text = (SKIN / "skin.json").read_text(encoding="utf-8")
    assert text == U.dump_manifest(U.manifest(imgs)), "skin.json 与重新生成的清单不同"


def test_density_independent():
    """换一个 LANTERN_ART_DENSITY，生成结果逐字节相同（桌面专用，只按 2 倍画）。"""
    here = md5s(INDEPENDENT)
    other = "1" if os.environ.get("LANTERN_ART_DENSITY", "1") == "2" else "2"
    code = (
        "import sys, json; sys.path.insert(0, %r); import test_ui_skin as T; print('MD5', json.dumps(T.md5s(%r)))"
        % (str(HERE), INDEPENDENT)
    )
    r = subprocess.run([sys.executable, "-c", code], env={**os.environ, "LANTERN_ART_DENSITY": other},
                       capture_output=True, text=True, cwd=str(HERE.parents[1]))
    assert r.returncode == 0, r.stderr[-2000:]
    line = [ln for ln in r.stdout.splitlines() if ln.startswith("MD5 ")][-1]
    there = json.loads(line[4:])
    assert here == there, f"LANTERN_ART_DENSITY={other} 时结果不同：{[k for k in here if here[k] != there[k]]}"


def test_size_budget():
    total = sum(p.stat().st_size for p in SKIN.iterdir())
    print(f"  体积：{total / 1024:.0f} KB")
    assert total <= BUDGET, f"skin/ 共 {total / 1024:.0f} KB，超过 {BUDGET // 1024} KB"


TESTS = [
    test_manifest,
    test_tint_white,
    test_tile_seams,
    test_stretch_bands_uniform,
    test_fill_ends,
    test_slice_lines_continuous,
    test_no_corner_spill_into_tiles,
    test_straight_alpha_and_bleed,
    test_finish_is_straight,
    test_nine_slice_rules,
    test_size_budget,
    test_determinism,
    test_density_independent,
]


def main() -> int:
    if not (SKIN / "skin.json").exists():
        print("没有 art/out/skin/skin.json，先运行 art/post/ui_skin.py")
        return 1
    failed = 0
    for t in TESTS:
        try:
            t()
            print(f"ok    {t.__name__}")
        except Exception:  # noqa: BLE001
            failed += 1
            print(f"FAIL  {t.__name__}")
            traceback.print_exc()
    print(f"\n{len(TESTS) - failed}/{len(TESTS)} 通过")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
