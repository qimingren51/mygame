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
    # M2.5
    "coin.png": (sz(32, 26), (0.5, 0.5)),
    "coin_emit.png": (sz(32, 26), (0.5, 0.5)),
    # 青丘：可平铺的迷雾
    **{f"mist_{i}.png": (sz(256, 256), (0.5, 0.5)) for i in range(2)},
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
    # M2.5：五行反应留下的区域
    "zone_lava.png": (sz(224, 144), (0.5, 0.5)),
    "zone_lava_glow.png": (sz(224, 144), (0.5, 0.5)),
    "zone_mud.png": (sz(240, 152), (0.5, 0.5)),
    "zone_herb.png": (sz(208, 132), (0.5, 0.5)),
    "zone_herb_glow.png": (sz(208, 132), (0.5, 0.5)),
    # 青丘（帧名前缀 qq_）
    "qq_bamboo_leaves_0.png": (sz(72, 44), (0.5, 0.5)),
    "qq_bamboo_leaves_1.png": (sz(56, 36), (0.5, 0.5)),
    "qq_bamboo_leaves_2.png": (sz(96, 40), (0.5, 0.5)),
    "qq_shoots_0.png": (sz(44, 44), (0.5, 1.0)),
    "qq_shoots_1.png": (sz(32, 40), (0.5, 1.0)),
    "qq_moss_0.png": (sz(56, 36), (0.5, 0.5)),
    "qq_moss_1.png": (sz(44, 30), (0.5, 0.5)),
    "qq_wash_0.png": (sz(320, 200), (0.5, 0.5)),
    "qq_wash_1.png": (sz(288, 192), (0.5, 0.5)),
    "qq_fox_tracks.png": (sz(128, 40), (0.5, 0.5)),
}
BOTTOM_ANCHORED = ("grass", "reed", "bamboo", "qq_shoots")  # 锚点在底边，底边允许有根
WHITE_TEXTURES = ["light.png", "glow.png", "eyes.png", "spark.png", "gem_0.png", "gem_1.png", "gem_2.png", "mist_0.png", "mist_1.png"]
WHITE_GROUND = ["rift_glow.png", "zone_lava_glow.png", "zone_herb_glow.png"]
M25_VFX = ["coin.png", "coin_emit.png"]
M25_GROUND = ["zone_lava.png", "zone_lava_glow.png", "zone_mud.png", "zone_herb.png", "zone_herb_glow.png"]
QQ_VFX = ["mist_0.png", "mist_1.png"]
QQ_GROUND = [n for n in EXPECTED_GROUND if n.startswith("qq_")]
TILEABLE = ("mist_0.png", "mist_1.png")  # 四边无缝的平铺贴图：边上不透明，另测接缝
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
            if name == "paper.png" or name in TILEABLE:
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


def meta_px_per_unit(folder: Path) -> float:
    return json.loads((folder / "meta.json").read_text(encoding="utf-8"))["px_per_unit"]


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
        elif name.split("_")[0] in ("spring", "rift", "reed", "leaves", "pebbles", "puddle", "bamboo", "zone", "qq"):
            assert e["blend"] == "normal" and e["tint"] is False, f"{name} 应为正常混合、不染色"
    assert vm["coin.png"]["blend"] == "normal" and vm["coin.png"]["tint"] is False and vm["coin.png"]["color"] == "full", "金币应全彩、正常混合"
    assert vm["coin_emit.png"]["blend"] == "add" and vm["coin_emit.png"]["tint"] is False, "金币的自发光应叠加、不染色（自带暖金色）"
    for name in ("zone_lava.png", "zone_mud.png", "zone_herb.png"):
        assert isinstance(gm[name]["radius_px"], int) and gm[name]["radius_px"] > 0, f"{name} meta 应有 radius_px"
    for name in TILEABLE:
        e = vm[name]
        assert e["blend"] == "normal" and e["tint"] is True and e["color"] == "white", f"{name} 应为白色、可染色、正常混合"
        assert "tile" not in e and e["tileable"] is True, f"{name} 不写 tile 键（进图集），要标 tileable: true"
        assert e["tile_units"] == e["size"][0] / meta_px_per_unit(V.VFX_DIR) == 128, f"{name} 的 tile_units 应是图宽 / px_per_unit = 128"
        assert e["size"][0] == e["size"][1], f"{name} 应是正方形"
        assert 0.1 <= e["alpha_hint"] <= 0.5, f"{name} 的 alpha_hint 不对"
    for name in QQ_GROUND:
        assert gm[name].get("region") == "qingqiu" and gm[name]["kind"] == "decor", f"{name} 应标 region: qingqiu、kind: decor"


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


def test_m25_coin():
    """金币：钱面是金色（R>G>B）、宽约 11 世界单位；方孔透明；自发光与金币同尺寸、亮处在钱面上，暖金色；四周透明。"""
    c = rgba(V.VFX_DIR, "coin.png").astype(np.float64)
    al = c[..., 3]
    h, w = al.shape
    cols = np.nonzero((al > 128).any(0))[0]
    width_units = (cols.max() - cols.min() + 1) / S.PX_PER_UNIT
    assert 10.0 <= width_units <= 12.5, f"金币宽 {width_units:.1f} 世界单位，应约 11"
    face = c[al > 230][:, :3]
    assert (face[:, 0] > face[:, 1]).mean() > 0.9 and (face[:, 1] > face[:, 2] + 20).mean() > 0.8, "钱面应是金色"
    cx, cy = int(round(V.COIN_C[0] * D)), int(round(V.COIN_C[1] * D))
    assert al[cy : cy + 1, cx - 1 : cx + 1].max() < 30, "方孔应透明"  # 孔的上沿露出一线孔壁，取中间偏下
    assert al[cy, cx + int(6 * D)] > 200, "方孔旁边是钱面"
    rows = np.nonzero((al > 128).any(1))[0]
    assert (rows.max() - rows.min() + 1) < 0.85 * (cols.max() - cols.min() + 1), "金币应是稍俯看的扁圆"
    e = rgba(V.VFX_DIR, "coin_emit.png").astype(np.float64)
    ea = e[..., 3] / 255.0
    hot = e[..., :3] * ea[..., None]
    assert hot.sum() > 0 and (hot[..., 0].sum() > hot[..., 1].sum() > hot[..., 2].sum()), "自发光应是暖金色"
    assert ea[al > 230].mean() > ea[al < 10].mean(), "自发光主要在钱面上"
    assert ea[al < 10].max() > 0.1, "钱外应有一圈金晕"


def test_m25_zones():
    """反应区域：熔岩有暗的壳和橙红的裂缝、光贴图亮在裂缝上；淤泥偏暗偏褐；灵草偏绿、光贴图亮在草尖。四周柔和地淡出。"""
    lv = rgba(V.GROUND_DIR, "zone_lava.png").astype(np.float64)
    vis = lv[lv[..., 3] > 200][:, :3]
    assert (vis.sum(1) < 200).mean() > 0.3, "熔岩应有焦墨的壳"
    hot = (vis[:, 0] > 180) & (vis[:, 0] > vis[:, 2] + 100)
    assert hot.mean() > 0.04, f"熔岩应有橙红的裂缝（占 {hot.mean():.3f}）"
    gl = rgba(V.GROUND_DIR, "zone_lava_glow.png").astype(np.float64)[..., 3]
    lv_hot = (lv[..., 0] > 180) & (lv[..., 0] > lv[..., 2] + 100) & (lv[..., 3] > 200)
    assert gl[lv_hot].mean() > 1.5 * gl[lv[..., 3] > 200].mean() and gl.max() >= 230, "熔岩的光应亮在裂缝上"
    md = rgba(V.GROUND_DIR, "zone_mud.png").astype(np.float64)
    vis = md[md[..., 3] > 200][:, :3]
    assert vis.mean() < 100 and (vis[:, 0] >= vis[:, 2] - 5).mean() > 0.5, "淤泥应偏暗、偏褐"
    hb = rgba(V.GROUND_DIR, "zone_herb.png").astype(np.float64)
    vis = hb[hb[..., 3] > 150][:, :3]
    assert (vis[:, 1] > vis[:, 0]).mean() > 0.7, "灵草应偏绿"
    hg = rgba(V.GROUND_DIR, "zone_herb_glow.png").astype(np.float64)[..., 3]
    assert hg.max() >= 230 and (hg > 200).mean() < 0.05, "灵草的光应是零星的亮点"
    for n in ("zone_lava.png", "zone_mud.png", "zone_herb.png"):
        al = rgba(V.GROUND_DIR, n)[..., 3].astype(np.float64)
        h, w = al.shape
        yy, xx = np.mgrid[0:h, 0:w]
        q = np.hypot((xx - w / 2) / (w / 2), (yy - h / 2) / (h / 2))
        assert al[q > 0.97].max() < 40, f"{n} 边缘应淡到纸里（外圈最大 alpha {al[q > 0.97].max():.0f}）"
        assert al[q < 0.3].mean() > 60, f"{n} 中间应有内容"


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


# ---------------------------------------------------------------- 青丘：迷雾、地面装饰


def seam_local(a: np.ndarray, axis: int, k: int = 4) -> float:
    """平铺 2×2 后跨接缝那一行（列）的平均差，与接缝两侧各 k 行（列）的平均差之比。无缝时≈1，有缝时远大于 1。
    雾是低频的，整行的平均差本身起伏大，所以只和接缝附近比。"""
    t = np.tile(a, (2, 2))
    d = np.abs(np.diff(t, axis=axis)).mean(axis=1 - axis)
    n = a.shape[axis]
    seam = d[n - 1]
    near = np.concatenate([d[n - 1 - k : n - 1], d[n : n + k]]).mean()
    return seam / max(near, 1e-6)


def test_mist_tileable():
    """迷雾四边无缝：接缝处的跳变与附近一致（含一阶导数：接缝两侧的斜率接得上）；边上不透明（不是透明边的精灵）。"""
    for name in TILEABLE:
        al = rgba(V.VFX_DIR, name)[..., 3].astype(np.float64)
        for axis in (0, 1):
            r = seam_local(al, axis)
            assert 0.5 <= r <= 1.6, f"{name} 轴 {axis} 接缝处跳变是附近的 {r:.2f} 倍（应≈1）"
            t = np.tile(al, (2, 2))
            n = al.shape[axis]
            g = np.diff(np.take(t, np.arange(n - 3, n + 3), axis=axis), n=2, axis=axis)  # 接缝两侧的二阶差分
            inner = np.abs(np.diff(al, n=2, axis=axis)).mean()
            assert np.abs(g).mean() <= 2.5 * inner + 0.5, f"{name} 轴 {axis} 接缝处斜率接不上"
        border = np.concatenate([al[0], al[-1], al[:, 0], al[:, -1]])
        assert border.mean() > 5, f"{name} 是平铺贴图，边上不应全透明"


def test_mist_density():
    """迷雾的浓淡：有透亮的空隙、有浓的雾心，平均不太浓；不出现一团独大（四个象限的平均 alpha 差不多），两张不一样。"""
    alphas = []
    for name in TILEABLE:
        al = rgba(V.VFX_DIR, name)[..., 3].astype(np.float64) / 255.0
        alphas.append(al)
        assert 0.2 <= al.mean() <= 0.5, f"{name} 平均 alpha {al.mean():.2f} 不在 0.2–0.5"
        assert (al < 0.05).mean() > 0.08, f"{name} 没有透亮的空隙"
        assert al.max() >= 0.95 and (al > 0.8).mean() < 0.25, f"{name} 雾心太少或太满"
        h, w = al.shape
        quads = [al[: h // 2, : w // 2].mean(), al[: h // 2, w // 2 :].mean(), al[h // 2 :, : w // 2].mean(), al[h // 2 :, w // 2 :].mean()]
        assert max(quads) - min(quads) < 0.25, f"{name} 四个象限浓淡差太大（平铺时看得出重复）：{np.round(quads, 2)}"
    assert np.abs(alphas[0] - alphas[1]).mean() > 0.1, "两张迷雾太像"


def test_qq_ground_content():
    """青丘地面：落竹叶以枯黄、赭、灰为主（不是鲜绿）；竹笋偏赭、尖上一点墨绿；苔点有焦墨的点和兑石绿的底；
    晕是淡的、柔边、偏青；狐狸脚印是一串分开的小印，从左下往右上，越往右越浓。"""
    for i in range(3):
        a = rgba(V.GROUND_DIR, f"qq_bamboo_leaves_{i}.png").astype(np.float64)
        vis = a[a[..., 3] > 200][:, :3]
        assert len(vis) > 50, f"qq_bamboo_leaves_{i} 叶子太少"
        sat = vis.max(1) - vis.min(1)
        assert np.median(sat) < 90, f"qq_bamboo_leaves_{i} 颜色太艳（长夜里以墨为主）"
        lum_ = vis.sum(1)
        assert (lum_ < np.median(lum_) - 90).mean() > 0.05, f"qq_bamboo_leaves_{i} 应有墨线（比叶色深得多的勾边）"
    for i in range(2):
        a = rgba(V.GROUND_DIR, f"qq_shoots_{i}.png").astype(np.float64)
        vis = a[a[..., 3] > 200][:, :3]
        assert (vis[:, 0] > vis[:, 2] + 15).mean() > 0.4, f"qq_shoots_{i} 笋壳应偏赭"
        green = (a[..., 3] > 150) & (a[..., 1] > a[..., 0] + 5)
        top = np.nonzero((a[..., 3] > 150).any(1))[0].min()
        assert green[top : top + int(0.15 * a.shape[0])].any(), f"qq_shoots_{i} 最高那根笋的尖上应有墨绿的箨叶"
    for i in range(2):
        a = rgba(V.GROUND_DIR, f"qq_moss_{i}.png").astype(np.float64)
        dots = (a[..., 3] > 200) & (a[..., :3].sum(-1) < 160)
        assert dots.sum() > 20 * D * D, f"qq_moss_{i} 苔点太少"
        wash = (a[..., 3] > 30) & (a[..., 3] < 140)
        assert wash.mean() > 0.1 and (a[wash][:, 1] >= a[wash][:, 0]).mean() > 0.5, f"qq_moss_{i} 底下应有兑石绿的淡墨"
    for i in range(2):
        a = rgba(V.GROUND_DIR, f"qq_wash_{i}.png").astype(np.float64)
        al = a[..., 3] / 255.0
        assert 0.12 <= al.max() <= 0.31, f"qq_wash_{i} 最大 alpha {al.max():.2f} 应≈0.3 以内（淡）"
        vis = a[al > 0.08][:, :3]
        assert vis[:, 2].mean() > vis[:, 0].mean() - 4 and vis[:, 1].mean() > vis[:, 0].mean(), f"qq_wash_{i} 应偏青（花青、石绿），不是暖灰"
        g = np.hypot(*np.gradient(al))
        assert np.percentile(g[al > 0.02], 99.5) < 0.05 / D, f"qq_wash_{i} 边太硬（应是湿接湿的柔边）"
    a = rgba(V.GROUND_DIR, "qq_fox_tracks.png").astype(np.float64)
    ink = a[..., 3] > 120
    cols = ink.any(0)
    runs = np.count_nonzero(np.diff(cols.astype(int)) == 1) + int(cols[0])
    assert runs >= 6, f"狐狸脚印应是一串分开的印（只数出 {runs} 个）"
    xs = np.nonzero(ink)[1]
    ys = np.nonzero(ink)[0]
    assert np.corrcoef(xs, ys)[0, 1] < -0.5, "脚印应从左下往右上走"
    w = a.shape[1]
    left = a[..., 3][:, : w // 3].max()
    right = a[..., 3][:, 2 * w // 3 :].max()
    assert right > left + 20, "越往右（越新）的脚印应越浓"


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


def test_pre_m25_unchanged():
    """快照里的 vfx/、ground/ 产物（M2.5 之前 + M2.5 第一批）逐字节不变，meta 已有条目与顶层字段不变（post/golden_m25.json，两种密度）。"""
    testkit.check_snapshot(V.ASSETS, ("vfx", "ground"), D)
    for folder, m25, qq in (("vfx", M25_VFX, QQ_VFX), ("ground", M25_GROUND, QQ_GROUND)):
        files = list(json.loads((V.ASSETS / folder / "meta.json").read_text(encoding="utf-8"))["files"])
        assert files[-len(qq) :] == qq, f"{folder}/meta.json 的青丘条目应追加在最后：{files[-len(qq):]}"
        assert files[-len(qq) - len(m25) : -len(qq)] == m25, f"{folder}/meta.json 的 M2.5 条目应紧挨在青丘条目之前"


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
