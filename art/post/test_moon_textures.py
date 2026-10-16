#!/usr/bin/env python3
"""moon_textures.py（“月夜”改版的候选与对比）和管线里月夜那几样的自检：纯 assert，不依赖 pytest。只测 2 倍（桌面版）。

管线（vfx_textures.py 2 倍）的产物缺失或过期时先跑一遍管线；moon_textures 的产物缺失或过期时再重新生成（约 3 分钟）。
--regen 强制重新生成 moon_textures 的产物，并核对它只写了 art/out/moon/ 和 review@2x/moon_*，
正式产物（assets/atlas/、art/out/assets@2x/vfx、ground）一个字节都没动。
另外核对：管线里的 vfx/light_pool = light_a，2 倍的 ground/paper = paper_a，调浓的 14 帧 = 原图调浓一次（不重复压），
别的地面帧没被调；打包过的图集（assets/atlas）里也是这些。

用法（在仓库根目录下）：
  art/.venv/bin/python art/post/test_moon_textures.py
  art/.venv/bin/python art/post/test_moon_textures.py --regen
"""

from __future__ import annotations

import json
import os
import sys
import traceback
from pathlib import Path

os.environ["LANTERN_ART_DENSITY"] = "2"

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import moon_textures as M  # noqa: E402

V = M.V
LIGHTS = tuple(M.LIGHTS)
PAPERS = tuple(M.PAPERS)
PANELS = [p[0] for p in M.PANELS]

WRITTEN: list[Path] = []
SNAPSHOT: dict[str, tuple[int, int]] = {}


def outputs() -> list[Path]:
    out = [M.OUT / f"light_{k}.png" for k in LIGHTS] + [M.OUT / f"light_{k}_curve.png" for k in LIGHTS]
    out += [M.OUT / f"paper_{k}.png" for k in PAPERS] + [M.OUT / f"paper_{k}_tile2x2.png" for k in PAPERS]
    out += [M.OUT / "ground_compare.png", M.OUT / "moon_report.json"]
    out += [M.OUT / f"preview_{k}.png" for k in PANELS]
    out += [M.REVIEW / "moon_compare.png", M.REVIEW / "moon_light_curves.png"]
    return out


def protected() -> dict[str, tuple[int, int]]:
    """正式产物（只读）：修改时间和大小。"""
    snap = {}
    for folder in (M.ATLAS, V.VFX_DIR, V.GROUND_DIR):
        if folder.exists():
            for p in sorted(folder.iterdir()):
                if p.is_file():
                    st = p.stat()
                    snap[str(p)] = (st.st_mtime_ns, st.st_size)
    return snap


def regenerate() -> None:
    """重新生成，并记录所有写盘的路径（包住 V.save_png 和 Path.write_text）。"""
    SNAPSHOT.update(protected())
    orig_save, orig_write = V.save_png, Path.write_text

    def save_png(img, path):
        WRITTEN.append(Path(path).resolve())
        return orig_save(img, path)

    def write_text(self, *a, **kw):
        WRITTEN.append(Path(self).resolve())
        return orig_write(self, *a, **kw)

    V.save_png = save_png
    Path.write_text = write_text  # type: ignore[method-assign]
    try:
        M.main()
    finally:
        V.save_png = orig_save
        Path.write_text = orig_write  # type: ignore[method-assign]


def ensure_pipeline() -> None:
    """管线 2 倍的 vfx/、ground/ 缺失或比脚本旧时，先跑一遍 vfx_textures（这是管线自己的产物，不算 moon_textures 写的）。"""
    newest = max((HERE / n).stat().st_mtime for n in ("vfx_textures.py", "ground_decor.py", "weapon_textures.py"))
    newest = max(newest, (V.ART / "style" / "style.py").stat().st_mtime)
    need = [V.VFX_DIR / "light_pool.png", V.VFX_DIR / "meta.json", V.GROUND_DIR / "paper.png", V.GROUND_DIR / "meta.json"]
    need += [V.GROUND_DIR / f"{n}.png" for n in M.DECOR_NAMES]
    if any(not p.exists() or p.stat().st_mtime < newest for p in need):
        print("先跑管线（vfx_textures.py，2 倍）……")
        V.main()


def ensure_outputs(force: bool) -> None:
    ensure_pipeline()
    newest = max((HERE / n).stat().st_mtime for n in ("moon_textures.py", "vfx_textures.py", "ground_decor.py"))
    newest = max(newest, (V.ART / "style" / "style.py").stat().st_mtime)
    stale = [p for p in outputs() if not p.exists() or p.stat().st_mtime < newest]
    if force or stale:
        print("重新生成候选……")
        regenerate()


def alpha(key: str) -> np.ndarray:
    return np.asarray(Image.open(M.OUT / f"light_{key}.png").convert("RGBA"), dtype=np.float64)[..., 3]


def paper(key: str) -> np.ndarray:
    return np.asarray(Image.open(M.OUT / f"paper_{key}.png"), dtype=np.float64)


def report() -> dict:
    return json.loads((M.OUT / "moon_report.json").read_text(encoding="utf-8"))


# ---------------------------------------------------------------- 灯光


def test_light_format():
    """和现在的 vfx/light 同尺寸（2 倍 256²，图集里的原画布）、RGBA、RGB 全白（游戏里染色）。"""
    j, _ = M.atlas("vfx")
    src = j["frames"]["vfx/light"]["sourceSize"]
    for k in LIGHTS:
        im = Image.open(M.OUT / f"light_{k}.png")
        assert im.mode == "RGBA", f"light_{k} mode {im.mode}"
        assert im.size == (src["w"], src["h"]) == (M.LIGHT_SIZE, M.LIGHT_SIZE), f"light_{k} 尺寸 {im.size} 和现在的 {src} 不同"
        a = np.asarray(im)
        assert (a[..., :3] == 255).all(), f"light_{k} 应为纯白 RGB"


def test_light_boundary():
    """光心满亮；半径之外、贴图四边、圆周最外一圈都为 0（和现在的 make_light 一样）。"""
    for k in LIGHTS:
        a = alpha(k)
        n = a.shape[0]
        d = V.radial_d(n)
        assert a[n // 2 - 1 : n // 2 + 1, n // 2 - 1 : n // 2 + 1].min() >= 254, f"light_{k} 光心不够亮"
        assert a[d >= 1.0].max() == 0, f"light_{k} 半径之外 alpha 必须为 0"
        assert max(a[0].max(), a[-1].max(), a[:, 0].max(), a[:, -1].max()) == 0, f"light_{k} 贴图边界 alpha 必须为 0"
        ring = (d >= 1.0 - 1.0 / (n / 2)) & (d < 1.0)
        assert a[ring].max() <= 1, f"light_{k} 圆周处 alpha 应为 0"


def test_light_monotonic():
    """按 1 像素宽的环取平均，随半径单调不增（允许抖动带来的 0.6 LSB 起伏）；曲线本身也单调。"""
    r = np.linspace(0, 1, 5001)
    for k in LIGHTS:
        prof = M.ring_profile(alpha(k))
        assert np.diff(prof).max() <= 0.6, f"light_{k} 径向不单调：回升 {np.diff(prof).max():.2f} LSB"
        assert np.diff(M.CURVES[k](r)).max() <= 1e-12, f"light_{k} 的曲线不单调"


def test_light_plateau():
    """中间一大片平的亮区：0.48R 以内的环平均都 ≥ 0.9；降到 0.9 在 0.48–0.65R，降到 0.5 在 0.6–0.78R，0.95R 外 ≤ 0.03。
    现在的 vfx/light 0.13R 就掉到 0.9 以下（对照）。"""
    for k in LIGHTS:
        prof = M.ring_profile(alpha(k)) / 255.0
        n2 = len(prof)
        assert prof[: int(0.48 * n2)].min() >= 0.9, f"light_{k} 0.48R 以内有低于 0.9 的地方"
        r9, r5 = M.level_radius(M.CURVES[k], 0.9), M.level_radius(M.CURVES[k], 0.5)
        assert 0.48 <= r9 <= 0.65, f"light_{k} 亮区到 {r9:.2f}R，不在 0.48–0.65"
        assert 0.60 <= r5 <= 0.78, f"light_{k} 半亮在 {r5:.2f}R，不在 0.60–0.78"
        assert prof[int(0.95 * n2) :].max() <= 0.03, f"light_{k} 最外 5% 还太亮"
    assert M.level_radius(M.curve_old, 0.9) < 0.2, "对照：现在的灯光应该很快就掉下去"


def test_light_soft_edge():
    """没有硬边：0.9 → 0.1 至少跨 0.2R（40 世界单位、1080p 约 100 像素）；256 贴图上相邻像素最多差 9 LSB；
    0.97R 以外不超过 3 LSB（羽化到 0）。"""
    n = M.LIGHT_SIZE
    rp = (np.arange(n // 2) + 0.5) / (n / 2)
    for k in LIGHTS:
        c = M.CURVES[k]
        width = M.level_radius(c, 0.1) - M.level_radius(c, 0.9)
        assert width >= 0.2, f"light_{k} 边太硬：0.9→0.1 只跨 {width:.3f}R"
        step = np.abs(np.diff(c(rp))).max() * 255
        assert step <= 9.0, f"light_{k} 相邻像素最多差 {step:.1f} LSB"
        assert c(np.array([0.97, 0.98, 0.99])).max() * 255 <= 3.0, f"light_{k} 最外 3% 没收干净"


def test_light_a_matches_spec():
    """light_a = 质感会话给的参数：r ≤ 0.4 为 1；0.5 + 0.5·cos(π(r−0.4)/0.6)，约 0.5R 0.93、0.7R 0.5、0.85R 0.15、1.0R 0；
    最外 3% 再羽化（只会更暗，不改里面）。"""
    c = M.curve_a
    assert float(c(np.array(0.4))) == 1.0 and float(c(np.array(0.2))) == 1.0
    for r, want in ((0.5, 0.933), (0.7, 0.5), (0.85, 0.146)):
        got = float(c(np.array(r)))
        assert abs(got - want) < 0.005, f"light_a 在 {r}R 是 {got:.3f}，应约 {want}"
    assert float(c(np.array(1.0))) == 0.0
    r = np.linspace(0, 1, 2001)
    base = V.raised_cos(r, 0.4, 1.0)
    assert np.allclose(c(r)[r <= 0.97], base[r <= 0.97]) and (c(r) <= base + 1e-12).all(), "羽化只能在最外 3%、只能更暗"


def test_light_dither():
    """±0.5 LSB 蓝噪声抖动：每个像素离理想值 < 1 LSB、无偏；衰减带里有相当一部分像素不等于四舍五入的值。"""
    for k in LIGHTS:
        a = alpha(k)
        d = V.radial_d(a.shape[0])
        f = M.CURVES[k](d) * 255.0
        sel = (d > 0.3) & (d < 0.95) & (f > 2) & (f < 253)
        err = a[sel] - f[sel]
        assert np.abs(err).max() < 1.0 + 1e-9, f"light_{k} 抖动超过 1 LSB"
        assert abs(err.mean()) < 0.06, f"light_{k} 抖动有偏：{err.mean():.3f}"
        assert (a[sel] != np.round(f[sel])).mean() > 0.2, f"light_{k} 看不出抖动"


def test_light_deterministic():
    for k in LIGHTS:
        img, _ = M.make_light(k)
        assert (np.asarray(img) == np.asarray(Image.open(M.OUT / f"light_{k}.png"))).all(), f"light_{k} 两次生成不一致"


# ---------------------------------------------------------------- 宣纸


def seam_ratio(p: np.ndarray, axis: int) -> float:
    if axis == 1:
        return np.abs(p[:, 0] - p[:, -1]).mean() / np.abs(np.diff(p, axis=1)).mean()
    return np.abs(p[0, :] - p[-1, :]).mean() / np.abs(np.diff(p, axis=0)).mean()


def test_paper_format():
    for k in PAPERS:
        im = Image.open(M.OUT / f"paper_{k}.png")
        assert im.mode == "RGB" and im.size == (M.PAPER_SIZE, M.PAPER_SIZE) == (1024, 1024), f"paper_{k} {im.mode} {im.size}"


def test_paper_seamless():
    """四边无缝：跨接缝的相邻差和内部一样（每个通道、两个方向）；接缝两侧的斜率接得上；低频（行列均值）不跳。"""
    for k in PAPERS:
        p = paper(k)
        for c in range(3):
            for axis in (0, 1):
                r = seam_ratio(p[..., c], axis)
                assert 0.85 <= r <= 1.18, f"paper_{k} 通道 {c} 轴 {axis} 接缝差异比 {r:.2f}（应≈1）"
        L = p @ M.LUMA
        for axis in (0, 1):
            t = np.tile(L, (2, 2))
            n = L.shape[axis]
            g = np.diff(np.take(t, np.arange(n - 3, n + 3), axis=axis), n=2, axis=axis)
            inner = np.abs(np.diff(L, n=2, axis=axis)).mean()
            assert np.abs(g).mean() <= 1.25 * inner, f"paper_{k} 轴 {axis} 接缝处斜率接不上"
            m = L.mean(axis=axis)
            assert abs(m[0] - m[-1]) <= np.percentile(np.abs(np.diff(m)), 99) + 1e-9, f"paper_{k} 轴 {axis} 低频接缝"


def test_paper_tone():
    """整体均值和第一版 2 倍宣纸（V.PAPER_MEAN_2X）逐通道相同（差 < 0.25/255，地面亮度不漂）；亮度标准差 0.035–0.045
    （sRGB 亮度，0..1），按 L*/100 算也在 0.033–0.045；第一版约 0.013（对照）。"""
    want = np.array(V.PAPER_MEAN_2X)
    old = M.paper_stats(M.legacy_paper().astype(np.uint8))
    assert old["luma_std"] < 0.02
    for k in PAPERS:
        p = paper(k)
        mean = p.reshape(-1, 3).mean(0)
        assert np.abs(mean - want).max() < 0.25, f"paper_{k} 均值 {mean.round(2)} 和现在的 {want.round(2)} 不同"
        st = M.paper_stats(p.astype(np.uint8))
        assert 0.035 <= st["luma_std"] <= 0.045, f"paper_{k} 亮度标准差 {st['luma_std']}"
        assert 0.033 <= st["lstar_std_over_100"] <= 0.045, f"paper_{k} L* 标准差 {st['lstar_std_over_100']}"
        assert abs(st["luma_std"] - M.PAPERS[k]["std"]) < 0.0015, f"paper_{k} 标准差没打到目标 {M.PAPERS[k]['std']}"


def test_paper_tiers():
    """三档层次都在：细纤维（σ 1.5 以下的高频）够多；中等尺度（墨晕斑、云絮那一档）有起伏；墨晕斑、水渍折痕两档非零；
    纤维档不弱于云絮档的一半（不是一张只有斑的“迷彩”）。"""
    rep = report()["papers"]
    for k in PAPERS:
        L = paper(k) @ M.LUMA / 255.0
        L = L - L.mean()
        hi = L - V.fft_blur(L, 1.5, wrap=True)
        mid = V.fft_blur(L, 6.0, wrap=True) - V.fft_blur(L, 40.0, wrap=True)
        assert hi.std() >= 0.008, f"paper_{k} 细纤维太少（高频 {hi.std():.4f}）"
        assert mid.std() >= 0.01, f"paper_{k} 中等尺度没有起伏（{mid.std():.4f}）"
        t = rep[k]["tier_luma_std"]
        fib, cld, blot, marks = (t[M.TIERS[n]] for n in ("fibre", "cloud", "blotch", "marks"))
        assert blot > 0.001 and marks > 0.0005, f"paper_{k} 墨晕斑或水渍折痕太淡：{blot}, {marks}"
        assert fib >= 0.5 * cld and fib >= 0.02, f"paper_{k} 纤维档 {fib} 太弱（云絮 {cld}）"


def test_paper_no_repeat():
    """平铺不显重复、不抢角色：比 256 像素（64 世界单位）更大的起伏占方差 ≤ 10%（现在的纸是 55%）；四个象限亮度差 ≤ 0.006；
    低通（σ 24）后最显眼的一块 ≤ 4σ；亮部是软肩、不削顶（每个通道 255 那一级不比 254 多）；99% 的像素在均值 ±0.13 以内。"""
    for k in PAPERS:
        st = M.paper_stats(paper(k).astype(np.uint8))
        assert st["lowfreq_share_lambda_ge_256px"] <= 0.10, f"paper_{k} 大块起伏太多：{st['lowfreq_share_lambda_ge_256px']}"
        assert st["quadrant_luma_spread"] <= 0.006, f"paper_{k} 四个象限浓淡不匀：{st['quadrant_luma_spread']}"
        assert st["max_blob_over_std_sigma24"] <= 4.0, f"paper_{k} 有一块特别显眼：{st['max_blob_over_std_sigma24']}σ"
        p = paper(k)
        for c in range(3):
            h = np.bincount(p[..., c].astype(np.int64).ravel(), minlength=256)
            assert h[255] <= h[254], f"paper_{k} 通道 {c} 在 255 堆积（削顶）：{h[253:].tolist()}"
        L = p @ M.LUMA / 255.0
        lo, hi = np.percentile(L, (0.5, 99.5))
        assert hi - L.mean() <= 0.13 and L.mean() - lo <= 0.13, f"paper_{k} 太花：{lo:.3f}..{hi:.3f}"


def test_paper_deterministic():
    for k in PAPERS:
        img, _ = M.make_paper(k)
        assert (np.asarray(img) == np.asarray(Image.open(M.OUT / f"paper_{k}.png"))).all(), f"paper_{k} 两次生成不一致"


# ---------------------------------------------------------------- 地面装饰


def test_decor_boost():
    """调浓（管线 2 倍的产物 vs 生成函数现画的原图）：同尺寸、RGBA；alpha 只增不减；全透明处（含外扩的颜色）一点不动；
    对纸面的 L* 反差（游戏里平均 alpha）提高 5%–13%；压暗颜色的像素最多压到线性亮度的 70%（不往黑里压），色相不变（三通道等比）。"""
    before = M.decor_before()
    assert set(before) == set(M.DECOR_NAMES), f"decor_before 的帧和 DECOR_NAMES 不一致：{sorted(set(before) ^ set(M.DECOR_NAMES))}"
    for n in M.BOOST_FRAMES:
        src, im = before[n], Image.open(V.GROUND_DIR / f"{n}.png")
        assert im.mode == "RGBA" and im.size == src.size, f"{n} 尺寸 {im.size} != {src.size}"
        a0, a1 = np.asarray(src).astype(np.int64), np.asarray(im).astype(np.int64)
        assert (a1[..., 3] >= a0[..., 3]).all(), f"{n} 有 alpha 变小的像素"
        z = a0[..., 3] == 0
        assert (a1[z] == a0[z]).all(), f"{n} 全透明的像素被改了"
        ratio = M.decor_contrast(im)["mean"] / M.decor_contrast(src)["mean"]
        assert 1.05 <= ratio <= 1.13, f"{n} 反差只变了 {ratio:.3f} 倍"
        ch = (a1[..., :3] != a0[..., :3]).any(-1)
        if ch.any():
            y0 = M.to_lin(a0[..., :3][ch] / 255.0) @ M.Y709
            y1 = M.to_lin(a1[..., :3][ch] / 255.0) @ M.Y709
            assert (y1 >= M.DECOR_DARK_MIN * y0 - 0.004).all(), f"{n} 颜色压得太暗（最低 {np.min(y1 / np.maximum(y0, 1e-6)):.2f}）"
            big = a0[..., :3][ch].min(-1) >= 40  # 太暗的像素量化误差大，不比色相
            q = M.to_lin(a1[..., :3][ch][big] / 255.0) / M.to_lin(a0[..., :3][ch][big] / 255.0)
            if len(q):
                assert (q.max(1) / q.min(1)).max() <= 1.2, f"{n} 压暗时色相变了"


def test_decor_boost_once():
    """管线只调一次：2 倍产物 = boost_decor(原图)，逐字节相同（再调一次就会更浓，对不上）；没列在 MOON_BOOST_FRAMES 里的
    （墨晕、竹笋）和原图逐字节相同（没被误调）。"""
    before, after = M.decor_before(), M.decor_after()
    for n in M.DECOR_NAMES:
        disk = np.asarray(Image.open(V.GROUND_DIR / f"{n}.png").convert("RGBA"))
        want = np.asarray(after[n])
        assert (disk == want).all(), f"{n}：管线产物和“原图调浓一次”不同"
        if n not in V.MOON_BOOST_FRAMES:
            assert (disk == np.asarray(before[n])).all(), f"{n} 不该调浓"
    twice = np.asarray(V.boost_decor(after["grass_0"]))
    assert (twice != np.asarray(after["grass_0"])).any(), "对照：调两次应该和调一次不同"


# ---------------------------------------------------------------- 管线与图集


def test_pipeline_light_pool():
    """管线里的 vfx/light_pool（2 倍）= 候选 light_a；meta：白色、染色、叠加、锚点居中、带说明；vfx/light 没变（其余光源还用它）。"""
    pool = np.asarray(Image.open(V.VFX_DIR / "light_pool.png").convert("RGBA"))
    assert (pool == np.asarray(Image.open(M.OUT / "light_a.png").convert("RGBA"))).all(), "vfx/light_pool 和 light_a 不同"
    e = json.loads((V.VFX_DIR / "meta.json").read_text(encoding="utf-8"))["files"]["light_pool.png"]
    assert (e["color"], e["blend"], e["tint"], tuple(e["anchor"]), tuple(e["size"])) == ("white", "add", True, (0.5, 0.5), (256, 256)) and e.get("note")
    old = np.asarray(Image.open(V.VFX_DIR / "light.png").convert("RGBA"))
    assert (old == np.asarray(V.make_light(np.random.default_rng(1001))[0])).all(), "vfx/light 不该变"


def test_pipeline_paper():
    """管线 2 倍的 ground/paper = 候选 paper_a；第一版 2 倍宣纸的均值 = V.PAPER_MEAN_2X（这个常数没抄错）。"""
    disk = np.asarray(Image.open(V.GROUND_DIR / "paper.png").convert("RGB"))
    assert (disk == np.asarray(Image.open(M.OUT / "paper_a.png").convert("RGB"))).all(), "2 倍的 ground/paper 和 paper_a 不同"
    legacy = M.legacy_paper().reshape(-1, 3).mean(0)
    assert np.abs(legacy - np.array(V.PAPER_MEAN_2X)).max() < 0.001, f"第一版宣纸均值 {legacy} 和 PAPER_MEAN_2X 不符"


def test_atlas_packed():
    """打包后的图集（assets/atlas）：paper.png 是月夜版；vfx 图集里有 vfx/light_pool（= light_a）；ground 图集里调浓的帧和管线产物一样。
    还没重新打包时（图集里是第一版的纸）只提示、不算失败。"""
    paper = np.asarray(Image.open(M.ATLAS / "paper.png").convert("RGB"))
    if (paper == M.legacy_paper().astype(np.uint8)).all():
        print("      （assets/atlas 还没按月夜重新打包，跳过）")
        return
    assert (paper == np.asarray(Image.open(V.GROUND_DIR / "paper.png").convert("RGB"))).all(), "图集里的 paper.png 不是管线的月夜版"
    def same(a: np.ndarray, b: np.ndarray) -> bool:
        """alpha 处处相同、看得见的像素颜色相同（裁掉的透明边在图集里是 0，源图里是外扩的颜色，不比）。"""
        vis = (a[..., 3] > 0) | (b[..., 3] > 0)
        return a.shape == b.shape and (a[..., 3] == b[..., 3]).all() and (a[vis] == b[vis]).all()

    pool, anc = M.atlas_frame("vfx", "vfx/light_pool")
    assert anc == (0.5, 0.5) and same(np.asarray(pool), np.asarray(Image.open(M.OUT / "light_a.png").convert("RGBA"))), "图集里的 light_pool 不对"
    for n in M.BOOST_FRAMES:
        f, _ = M.atlas_frame("ground", f"ground/{n}")
        assert same(np.asarray(f), np.asarray(Image.open(V.GROUND_DIR / f"{n}.png").convert("RGBA"))), f"图集里的 {n} 不是调浓后的"


# ---------------------------------------------------------------- 模拟画面


def test_previews():
    """1920×1080 的模拟画面都在；新组合的月下地面明显比现状亮、月下妖物和地面拉得开（L* 差），灯下亮而不过曝。"""
    for k in PANELS:
        im = Image.open(M.OUT / f"preview_{k}.png")
        assert im.size == (1920, 1080) and im.mode == "RGB", f"preview_{k} {im.size}"
    cmp_ = Image.open(M.REVIEW / "moon_compare.png")
    assert cmp_.width == 1920 and cmp_.height > 1620, f"moon_compare 尺寸 {cmp_.size}"
    assert Image.open(M.REVIEW / "moon_light_curves.png").width >= 2000
    pv = report()["previews"]
    now = pv["now"]
    assert now["ground_luma_median"]["月下 r>260"] < 65, "现状的月下应该是一片灰（模拟薄雾）"
    assert max(v for k, v in now["enemy_vs_ground_dL"].items() if "月下" in k) < 5, "现状：月下的妖物几乎看不出（对照）"
    for k in PANELS[1:]:
        m = pv[k]
        assert m["ground_luma_median"]["月下 r>260"] >= 70, f"{k} 月下地面太暗"
        assert 195 <= m["ground_luma_median"]["灯下 r<60"] <= 235, f"{k} 灯下地面 {m['ground_luma_median']['灯下 r<60']}"
        foes = [v for kk, v in m["enemy_vs_ground_dL"].items() if "月下" in kk]
        assert min(foes) >= 15, f"{k} 月下的妖物和地面 L* 只差 {min(foes)}"


def test_report():
    rep = report()
    assert set(rep["lights"]) == {"old", *LIGHTS} and set(rep["papers"]) == {"old", *PAPERS}
    assert set(rep["decor"]["frames"]) == set(M.BOOST_FRAMES + M.WASH_FRAMES)
    assert set(rep["previews"]) == set(PANELS)
    assert rep["density"] == 2 and rep["px_per_unit"] == 4.0


def test_writes_only_own_outputs():
    """只在 --regen（或产物过期重新生成）时有记录：所有写盘都在 art/out/moon/ 或 review@2x/moon_*；正式产物没动。"""
    if not WRITTEN:
        print("      （这次没有重新生成，跳过写盘检查；加 --regen 可测）")
        return
    out, review = M.OUT.resolve(), M.REVIEW.resolve()
    for p in WRITTEN:
        assert p.is_relative_to(out) or (p.is_relative_to(review) and p.name.startswith("moon_")), f"写到了不该写的地方：{p}"
    assert protected() == SNAPSHOT, "正式产物（assets/atlas 或 art/out/assets@2x）被改动了"


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
