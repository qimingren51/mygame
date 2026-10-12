#!/usr/bin/env python3
"""vfx_textures.py（含第二批地面贴图 ground_decor.py）的自检：纯 assert，不依赖 pytest。

不设 LANTERN_ART_DENSITY 时自动在 1 倍、2 倍各跑一遍（子进程）；设了就只测那一种密度。
1 倍还要核对与密度改造前的基准逐字节相同（post/golden_1x.json）；2 倍要与 1 倍是“同一张画”。

用法（在仓库根目录下）：
  art/.venv/bin/python art/post/test_vfx_textures.py           # 两种密度；产物缺失或比脚本旧时先重新生成
  art/.venv/bin/python art/post/test_vfx_textures.py --regen   # 强制重新生成后再测
  LANTERN_ART_DENSITY=2 art/.venv/bin/python art/post/test_vfx_textures.py   # 只测 2 倍
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

import vfx_textures as V  # noqa: E402

S = V.S
D = V.D


def sz(w: int, h: int) -> tuple[int, int]:
    """1 倍尺寸 → 当前密度。"""
    return (int(round(w * D)), int(round(h * D)))

# 文件名 → (尺寸, 锚点)，与 src/render/placeholders.ts 的占位图一致
EXPECTED_VFX = {
    "light.png": (sz(128, 128), (0.5, 0.5)),
    "glow.png": (sz(64, 64), (0.5, 0.5)),
    "eyes.png": (sz(24, 10), (0.5, 0.5)),
    "shadow.png": (sz(64, 24), (0.5, 0.5)),
    "spark.png": (sz(12, 12), (0.5, 0.5)),
    "gem_0.png": (sz(20, 20), (0.5, 0.5)),
    "gem_1.png": (sz(26, 26), (0.5, 0.5)),
    "gem_2.png": (sz(32, 32), (0.5, 0.5)),
    **{f"flame_{i}.png": (sz(32, 48), (0.5, 0.6)) for i in range(4)},
    **{f"ink_{i}.png": (sz(20, 20), (0.5, 0.5)) for i in range(3)},
    "lantern.png": (sz(20, 24), (0.5, 0.5)),
}
EXPECTED_GROUND = {
    "paper.png": (sz(512, 512), (0.0, 0.0)),
    **{f"wash_{i}.png": (sz(240, 160), (0.5, 0.5)) for i in range(3)},
    **{f"grass_{i}.png": (sz(48, 40), (0.5, 1.0)) for i in range(4)},
    # 第二批（ground_decor.py）
    "spring.png": (sz(160, 100), (0.5, 0.5)),
    "rift.png": (sz(140, 80), (0.5, 0.5)),
    "rift_glow.png": (sz(140, 80), (0.5, 0.5)),
    **{f"reed_{i}.png": (sz(40, 64), (0.5, 1.0)) for i in range(3)},
    **{f"leaves_{i}.png": (sz(64, 40), (0.5, 0.5)) for i in range(2)},
    **{f"pebbles_{i}.png": (sz(48, 28), (0.5, 0.5)) for i in range(2)},
    "puddle_0.png": (sz(72, 36), (0.5, 0.5)),
    **{f"bamboo_{i}.png": (sz(40, 56), (0.5, 1.0)) for i in range(2)},
}
BOTTOM_ANCHORED = ("grass", "reed", "bamboo")  # 锚点在底边，底边允许有根
WHITE_TEXTURES = ["light.png", "glow.png", "eyes.png", "spark.png", "gem_0.png", "gem_1.png", "gem_2.png"]
WHITE_GROUND = ["rift_glow.png"]
REVIEW = ["vfx_sheet.png", "paper_tile_2x2.png", "light_test.png"]


def all_outputs() -> list[Path]:
    return (
        [V.VFX_DIR / f for f in EXPECTED_VFX]
        + [V.GROUND_DIR / f for f in EXPECTED_GROUND]
        + [V.VFX_DIR / "meta.json", V.GROUND_DIR / "meta.json"]
        + [V.REVIEW_DIR / f for f in REVIEW]
    )


def ensure_outputs(force: bool) -> None:
    newest_src = max((HERE / n).stat().st_mtime for n in ("vfx_textures.py", "ground_decor.py", "weapon_textures.py"))
    newest_src = max(newest_src, (V.ART / "style" / "style.py").stat().st_mtime)
    stale = [p for p in all_outputs() if not p.exists() or p.stat().st_mtime < newest_src]
    if force or stale:
        print("重新生成贴图……")
        V.main()


def rgba(folder: Path, name: str) -> np.ndarray:
    return np.asarray(Image.open(folder / name).convert("RGBA"), dtype=np.int64)


def lum(a: np.ndarray) -> np.ndarray:
    return a[..., :3].astype(np.float64) @ np.array([0.299, 0.587, 0.114])


# ---------------------------------------------------------------- 尺寸与 meta


def test_meta_sizes_and_anchors():
    for folder, expected in ((V.VFX_DIR, EXPECTED_VFX), (V.GROUND_DIR, EXPECTED_GROUND)):
        meta = json.loads((folder / "meta.json").read_text(encoding="utf-8"))
        files = meta["files"]
        assert set(files) == set(expected), f"{folder.name}/meta.json 文件列表不符：{sorted(set(files) ^ set(expected))}"
        for name, (size, anchor) in expected.items():
            entry = files[name]
            assert tuple(entry["size"]) == size, f"{name} meta size {entry['size']} != {size}"
            assert len(entry["anchor"]) == 2 and all(0.0 <= v <= 1.0 for v in entry["anchor"]), f"{name} 锚点非法"
            assert tuple(entry["anchor"]) == anchor, f"{name} anchor {entry['anchor']} != {anchor}"
            im = Image.open(folder / name)
            assert im.size == size, f"{name} 实际尺寸 {im.size} != {size}"
            want_mode = "RGB" if name == "paper.png" else "RGBA"
            assert im.mode == want_mode, f"{name} mode {im.mode} != {want_mode}"


def test_no_empty_images():
    for folder, expected in ((V.VFX_DIR, EXPECTED_VFX), (V.GROUND_DIR, EXPECTED_GROUND)):
        for name in expected:
            a = rgba(folder, name)
            if name == "paper.png":
                assert lum(a).std() > 1.0, "宣纸没有纹理"
                continue
            alpha = a[..., 3]
            assert alpha.max() >= 60, f"{name} 几乎全透明（最大 alpha {alpha.max()}）"
            frac = (alpha > 8).mean()
            assert frac > 0.03, f"{name} 可见像素太少（{frac:.3f}）"


def test_sprite_borders_transparent():
    """非平铺贴图四周一圈必须全透明（草的锚点在底边，底边允许有根部）。"""
    for folder, expected in ((V.VFX_DIR, EXPECTED_VFX), (V.GROUND_DIR, EXPECTED_GROUND)):
        for name in expected:
            if name == "paper.png":
                continue
            al = rgba(folder, name)[..., 3]
            bottom = name.startswith(BOTTOM_ANCHORED)
            edges = [al[0, :], al[:, 0], al[:, -1]] + ([] if bottom else [al[-1, :]])
            m = max(int(e.max()) for e in edges)
            assert m == 0, f"{name} 边缘有不透明像素（最大 {m}）"
            if bottom:
                assert al[-1, :].max() > 0 or al[-2, :].max() > 0, f"{name} 根没有落在底边"


def test_white_textures_are_white():
    for folder, names in ((V.VFX_DIR, WHITE_TEXTURES), (V.GROUND_DIR, WHITE_GROUND)):
        for name in names:
            a = rgba(folder, name)
            assert (a[..., :3] == 255).all(), f"{name} 应为纯白 RGB（游戏里染色）"


def test_meta_density_and_blend():
    for folder in (V.VFX_DIR, V.GROUND_DIR):
        meta = json.loads((folder / "meta.json").read_text(encoding="utf-8"))
        assert meta["px_per_unit"] == S.PX_PER_UNIT, f"{folder.name}/meta.json px_per_unit {meta['px_per_unit']} != {S.PX_PER_UNIT}"
    vm = json.loads((V.VFX_DIR / "meta.json").read_text(encoding="utf-8"))["files"]
    for i in range(4):
        assert vm[f"flame_{i}.png"]["blend"] == "normal", "灯火应为正常混合（火舌尖的焦墨要黑）"
    gm = json.loads((V.GROUND_DIR / "meta.json").read_text(encoding="utf-8"))["files"]
    assert abs(gm["paper.png"]["texel_world_units"] - 1.0 / S.PX_PER_UNIT) < 1e-12
    for name, e in gm.items():
        if name in WHITE_GROUND:
            assert e["blend"] == "add" and e["tint"] is True, f"{name} 应为白色、染色、叠加"
        elif name.split("_")[0] in ("spring", "rift", "reed", "leaves", "pebbles", "puddle", "bamboo"):
            assert e["blend"] == "normal" and e["tint"] is False, f"{name} 应为正常混合、不染色"


def test_ground_decor_content():
    """第二批地面贴图的几处语义：灵泉中心是石绿的水、四周有墨线；裂隙中心偏红、边缘是焦墨；水洼偏暗。"""
    sp = rgba(V.GROUND_DIR, "spring.png").astype(np.float64)
    h, w = sp.shape[:2]
    c = sp[h // 2 - 3 : h // 2 + 3, w // 2 - 3 : w // 2 + 3]
    assert c[..., 3].min() > 200 and (c[..., 1] > c[..., 0]).all(), "灵泉中心应是不透明、偏绿的水面"
    rf = rgba(V.GROUND_DIR, "rift.png").astype(np.float64)
    al = rf[..., 3]
    core = rf[al > 200]
    assert (core[:, 0] > core[:, 1] + 40).mean() > 0.2, "裂隙里应有偏红的亮芯"
    assert (core[:, :3].sum(1) < 120).mean() > 0.15, "裂隙应有焦墨的边"
    gl = rgba(V.GROUND_DIR, "rift_glow.png")[..., 3].astype(np.float64)
    assert gl.max() >= 230, "裂隙光的芯要够亮"
    pd = rgba(V.GROUND_DIR, "puddle_0.png").astype(np.float64)
    vis = pd[pd[..., 3] > 150]
    assert vis[:, :3].mean() < 110, "水洼应偏暗"


def test_alpha_caps():
    sh = rgba(V.VFX_DIR, "shadow.png")[..., 3] / 255
    assert 0.38 <= sh.max() <= 0.47, f"影子最大 alpha {sh.max():.3f} 不在约 0.45"
    sc = rgba(V.VFX_DIR, "shadow.png")[..., :3]
    assert (np.abs(sc - np.array(S.hex_to_rgb(S.INK["jiao"]))) <= 1).all(), "影子颜色应为焦墨"
    for i in range(3):
        w = rgba(V.GROUND_DIR, f"wash_{i}.png")[..., 3] / 255
        assert 0.25 <= w.max() <= 0.36, f"wash_{i} 最大 alpha {w.max():.3f} 不在约 0.35"


# ---------------------------------------------------------------- 光


def test_light_boundary_and_profile():
    a = rgba(V.VFX_DIR, "light.png")[..., 3].astype(np.float64)
    n = a.shape[0]
    d = V.radial_d(n)
    assert a[n // 2 - 1 : n // 2 + 1, n // 2 - 1 : n // 2 + 1].min() >= 254, "光心不够亮"
    assert a[d >= 1.0].max() == 0, "半径之外 alpha 必须为 0"
    border = np.concatenate([a[0], a[-1], a[:, 0], a[:, -1]])
    assert border.max() == 0, "贴图边界 alpha 必须为 0"
    # 圆周附近（最外 1 像素环）也为 0
    ring = (d >= 1.0 - 1.0 / (n / 2)) & (d < 1.0)
    assert a[ring].max() <= 1, f"圆周处 alpha 应为 0，实际 {a[ring].max()}"
    # 按 1 像素宽的环取平均，应随半径单调不增（允许抖动带来的 0.6 LSB 起伏）
    r_px = np.floor(d * n / 2).astype(int)
    prof = np.array([a[r_px == r].mean() for r in range(n // 2)])
    rises = np.diff(prof)
    assert rises.max() <= 0.6, f"径向不单调：最大回升 {rises.max():.2f} LSB（半径 {rises.argmax()}）"


def test_light_dither():
    """抖动幅度 ±0.5 LSB：每个像素与理想值之差 < 1 LSB，且有相当一部分像素偏离四舍五入值（说明确实抖了）。"""
    a = rgba(V.VFX_DIR, "light.png")[..., 3].astype(np.float64)
    d = V.radial_d(a.shape[0])
    f = V.bump_window(d) * (0.62 + 0.38 * np.exp(-((d / 0.30) ** 2))) * 255.0
    sel = (d > 0.15) & (d < 0.9)
    err = a[sel] - f[sel]
    assert np.abs(err).max() < 1.0 + 1e-9, f"抖动超过 1 LSB：{np.abs(err).max():.3f}"
    assert abs(err.mean()) < 0.05, f"抖动有偏：{err.mean():.3f}"
    differs = (a[sel] != np.round(f[sel])).mean()
    assert differs > 0.2, f"看不出抖动（只有 {differs:.2%} 的像素偏离取整值）"


# ---------------------------------------------------------------- 宣纸


def seam_ratio(p: np.ndarray, axis: int) -> float:
    if axis == 1:
        wrap = np.abs(p[:, 0] - p[:, -1]).mean()
        inner = np.abs(np.diff(p, axis=1)).mean()
    else:
        wrap = np.abs(p[0, :] - p[-1, :]).mean()
        inner = np.abs(np.diff(p, axis=0)).mean()
    return wrap / inner


def test_paper_seamless():
    p = np.asarray(Image.open(V.GROUND_DIR / "paper.png"), dtype=np.float64)
    for c in range(3):
        for axis in (0, 1):
            r = seam_ratio(p[..., c], axis)
            assert 0.75 <= r <= 1.33, f"宣纸通道 {c} 轴 {axis} 接缝差异比 {r:.2f}（应≈1）"
    # 低频接缝：相邻行/列的均值之差，跨接缝处不应超出内部的 99 分位
    L = lum(p)
    for axis in (0, 1):
        m = L.mean(axis=axis)
        inner = np.abs(np.diff(m))
        wrap = abs(m[0] - m[-1])
        assert wrap <= np.percentile(inner, 99) + 1e-9, f"宣纸轴 {axis} 低频接缝 {wrap:.3f} > 内部 99 分位 {np.percentile(inner, 99):.3f}"


def test_paper_tone():
    p = np.asarray(Image.open(V.GROUND_DIR / "paper.png"), dtype=np.float64)
    mean = p.reshape(-1, 3).mean(0)
    want = np.array(S.hex_to_rgb(S.PAPER), dtype=np.float64)
    assert np.abs(mean - want).max() <= 3.0, f"宣纸平均色 {mean.round(1)} 偏离 PAPER {want}"
    sd = lum(p).std()
    assert 1.0 <= sd <= 8.0, f"宣纸对比度不合适（亮度标准差 {sd:.2f}）"


def test_paper_deterministic():
    again = np.asarray(V.make_paper())
    on_disk = np.asarray(Image.open(V.GROUND_DIR / "paper.png"))
    assert (again == on_disk).all(), "宣纸两次生成结果不一致（随机种子没固定？）"


# ---------------------------------------------------------------- 灯火


def test_ground_decor_deterministic():
    import ground_decor  # noqa: PLC0415

    for key, (img, _, _) in ground_decor.build().items():
        disk = np.asarray(Image.open(V.GROUND_DIR / f"{key}.png"))
        assert (np.asarray(img) == disk).all(), f"{key} 两次生成结果不一致"


def test_flame_frames():
    frames = [rgba(V.VFX_DIR, f"flame_{i}.png").astype(np.float64) for i in range(4)]
    cover = [f[..., 3].sum() for f in frames]
    assert max(cover) / min(cover) < 1.35, f"各帧火焰面积差太多：{cover}"
    for i in range(4):
        j = (i + 1) % 4
        diff = np.abs(frames[i][..., 3] - frames[j][..., 3]).mean()
        assert diff > 1.0, f"flame_{i} 与 flame_{j} 几乎一样，没有闪动"
    # 颜色：最亮处偏黄（R≥G>B），边缘偏红
    f0 = frames[0]
    a = f0[..., 3]
    core = f0[a > 240][:, :3]
    assert len(core) > 0
    hot = core[core.sum(1).argsort()[-20:]].mean(0)
    assert hot[0] >= hot[1] > hot[2], f"火芯颜色不是暖黄：{hot}"
    edge = f0[(a > 60) & (a < 200)][:, :3].mean(0)
    assert edge[0] > edge[1] + 40, f"火焰边缘不够红：{edge}"
    again = [np.asarray(im) for im in V.make_flames()]
    assert all((x == np.asarray(Image.open(V.VFX_DIR / f"flame_{i}.png"))).all() for i, x in enumerate(again)), "火焰两次生成不一致"


# ---------------------------------------------------------------- 体积与检查图


def test_total_size():
    total = sum(p.stat().st_size for p in V.VFX_DIR.glob("*.png")) + sum(p.stat().st_size for p in V.GROUND_DIR.glob("*.png"))
    limit = 800 * 1024 * D * D
    assert total < limit, f"贴图总体积 {total / 1024:.1f} KB 超过 {limit / 1024:.0f} KB"
    paper = (V.GROUND_DIR / "paper.png").stat().st_size
    assert paper < 250 * 1024 * D * D, f"宣纸 {paper / 1024:.1f} KB 超过 {250 * D * D:.0f} KB"


def test_review_images():
    for name in REVIEW:
        p = V.REVIEW_DIR / name
        assert p.exists() and p.stat().st_size > 10_000, f"检查图 {name} 缺失或为空"
    t = Image.open(V.REVIEW_DIR / "paper_tile_2x2.png")
    assert t.size == sz(1024, 1024)


def test_density_1x_unchanged():
    """1 倍：已有贴图与密度改造前逐字节相同；meta 已有条目不变（只追加新条目，外加登记过的有意改动）。"""
    if D != 1:
        return
    testkit.check_golden(V.ASSETS, ("vfx", "ground"))


def test_density_2x_same_art():
    """2 倍：缩回 1 倍后与 1 倍贴图基本一致（同一张画，不是另一组随机）。需要 1 倍产物在盘上。"""
    if D != 2:
        return
    one = V.OUT / "assets"
    for folder, expected in (("vfx", EXPECTED_VFX), ("ground", EXPECTED_GROUND)):
        names = [n for n in expected if n != "paper.png"]
        res = testkit.density_consistency(V.ASSETS / folder, one / folder, names)
        assert len(res) == len(names), f"{folder}: 1 倍产物不全，先跑一遍 1 倍"


def main() -> int:
    ensure_outputs("--regen" in sys.argv)
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
    print(f"\n{len(tests) - failed}/{len(tests)} 通过")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
