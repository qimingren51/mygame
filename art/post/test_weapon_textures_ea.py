#!/usr/bin/env python3
"""weapon_textures_ea.py（抢先体验五件新法器的贴图）的自检：纯 assert，不依赖 pytest。只有 2 倍（桌面版）。

产物缺失或比脚本旧时先重新生成。--regen 强制重新生成，并核对只写了 art/out/assets@2x/weapons_ea/ 和
review@2x/weapons_ea_*，别的产物（assets/atlas、art/out/assets@2x 的其他目录）一个字节都没动。
--quick 跳过确定性检查（另画一遍逐像素比对）。

用法（在仓库根目录下）：
  art/.venv/bin/python art/post/test_weapon_textures_ea.py
  art/.venv/bin/python art/post/test_weapon_textures_ea.py --regen
  art/.venv/bin/python art/post/test_weapon_textures_ea.py --quick
"""

from __future__ import annotations

import json
import math
import sys
import traceback
from functools import lru_cache
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import weapon_textures_ea as E  # noqa: E402  它经 vfx_frames 把密度定成 2 倍

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

F, V = E.F, E.V
ATLAS = V.ART.parent / "assets" / "atlas"

# 每组：帧数、画布、混合、可染（BALANCE.md 6.3 节的“画面”，帧数按 24 帧/秒折算）
SPEC = {
    "coin_slash": (6, (512, 896), "add", True),
    "coin_spark": (5, (128, 128), "add", False),
    "coin_whirl": (6, (1024, 1024), "add", True),
    "coin_cross": (4, (160, 160), "add", True),
    "wave_front": (4, (448, 128), "add", True),
    "wave_front_fade": (3, (448, 128), "add", True),
    "wave_trail": (1, (448, 256), "add", True),
    "vine": (3, (512, 40), "add", True),
    "vine_pulse": (3, (128, 48), "add", True),
    "vine_bind": (4, (192, 192), "add", True),
    "sky_lantern": (4, (192, 192), "normal", False),
    "sky_lantern_emit": (4, (192, 192), "add", False),
    "sky_lantern_fall": (3, (192, 192), "normal", False),
    "sky_lantern_fall_emit": (3, (192, 192), "add", False),
    "lantern_mark": (1, (352, 224), "add", True),
    "fire_sea": (4, (352, 224), "add", False),
    "tower": (2, (448, 472), "normal", False),
    "tower_emit": (2, (448, 472), "add", False),
    "tower_fall": (3, (448, 472), "normal", False),
    "tower_fall_emit": (3, (448, 472), "add", False),
    "tower_lift": (3, (448, 472), "normal", False),
    "tower_lift_emit": (3, (448, 472), "add", False),
    "tower_gold": (2, (576, 600), "normal", False),
    "tower_gold_emit": (2, (576, 600), "add", False),
    "tower_gold_fall": (3, (576, 600), "normal", False),
    "tower_gold_fall_emit": (3, (576, 600), "add", False),
    "tower_gold_lift": (3, (576, 600), "normal", False),
    "tower_gold_lift_emit": (3, (576, 600), "add", False),
    "tower_dust": (6, (448, 304), "normal", False),
    "tower_vortex": (4, (768, 480), "add", True),
}
LAYERS = {n for n in SPEC if n.endswith("_emit")}  # Blender 渲的发光层（不是特效帧，亮度另算）
HANDOFF = {"sky_lantern_fall", "tower_fall", "tower_gold_fall"}  # 播完接别的（爆燃、立着的塔），不淡出
# 不是 24 帧/秒一次播完的：(fps, loop)
PLAY = {"wave_front": (12, True), "wave_front_fade": (12, False), "vine": (8, True), "vine_pulse": (24, True), "vine_bind": (8, False),
        "sky_lantern": (12, True), "sky_lantern_emit": (12, True), "sky_lantern_fall": (12, False), "sky_lantern_fall_emit": (12, False),
        "fire_sea": (12, True), "tower_vortex": (12, True)}
for _t in ("tower", "tower_gold"):
    PLAY.update({_t: (4, True), f"{_t}_emit": (4, True), f"{_t}_lift": (12, False), f"{_t}_lift_emit": (12, False)})
LOOPS = {n for n, (_f, lp) in PLAY.items() if lp}
STILLS = {n for n, spec in SPEC.items() if spec[0] == 1}  # 只有一张的（拉伸用的带子）
# 跟半径走的帧：1080p 下按这些半径（世界单位）缩放时，缩放比例要在 0.8–1.25 之间（约一比一，不靠放大）
RADII = {"coin_slash": (140.0, 170.0), "coin_whirl": (200.0,)}
PEAK8 = round(F.PEAK * 255)

WRITTEN: list[Path] = []
SNAPSHOT: dict[str, tuple[int, int]] = {}


# ---------------------------------------------------------------- 准备


def outputs() -> list[Path]:
    out = [E.OUT / "meta.json"]
    for name, (n, *_rest) in SPEC.items():
        out += [E.OUT / f"{name}_{i}.png" for i in range(n)]
    for key in E.BATCHES:
        out += [E.REVIEW / f"weapons_ea_{key}.png", E.REVIEW / f"weapons_ea_{key}_ingame.png"]
    return out


def protected() -> dict[str, tuple[int, int]]:
    snap = {}
    folders = [ATLAS] + [p for p in (V.OUT / "assets@2x").iterdir() if p.is_dir() and p.name != E.OUT.name]
    for folder in folders:
        for p in sorted(folder.rglob("*")):
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
        E.main()
    finally:
        V.save_png = orig_save
        Path.write_text = orig_write  # type: ignore[method-assign]


def ensure_outputs(force: bool) -> None:
    names = ("weapon_textures_ea.py", "vfx_frames.py", "vfx_frames_review.py", "vfx_textures.py", "weapon_textures.py")
    newest = max((HERE / n).stat().st_mtime for n in names)
    stale = [p for p in outputs() if not p.exists() or p.stat().st_mtime < newest]
    if force or stale:
        print("重新生成新法器贴图……")
        regenerate()


@lru_cache(maxsize=1)
def meta() -> dict:
    return json.loads((E.OUT / "meta.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=None)
def rgba(name: str, i: int) -> np.ndarray:
    return np.asarray(Image.open(E.OUT / f"{name}_{i}.png").convert("RGBA"))


def alpha(name: str, i: int) -> np.ndarray:
    return rgba(name, i)[..., 3].astype(np.float64)


def frames_of(name: str) -> list[int]:
    return list(range(SPEC[name][0]))


def all_specs() -> dict:
    out = {}
    for batch in E.BATCHES.values():
        out.update(batch)
    return out


def centroid(a: np.ndarray) -> tuple[float, float]:
    h, w = a.shape
    tot = a.sum()
    return float((a.sum(0) * (np.arange(w) + 0.5)).sum() / tot), float((a.sum(1) * (np.arange(h) + 0.5)).sum() / tot)


def bbox(a: np.ndarray) -> tuple[int, int, int, int]:
    ys, xs = np.nonzero(a)
    return int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())


def polar(name: str):
    """以锚点为原点的半径和角度（度，顺时针为正：图里 y 向下）。"""
    w, h = SPEC[name][1]
    ax, ay = meta()["files"][f"{name}_0.png"]["anchor"]
    ys, xs = np.mgrid[0:h, 0:w] + 0.5
    return np.hypot(xs - ax * w, ys - ay * h), np.degrees(np.arctan2(ys - ay * h, xs - ax * w))


# ---------------------------------------------------------------- 清单与格式


def test_spec_matches_list():
    specs = all_specs()
    assert set(specs) == set(SPEC), f"组名不一致：{sorted(set(specs) ^ set(SPEC))}"
    for name, (n, size, blend, tint) in SPEC.items():
        _, size_, _, blend_, tint_, _, _ = specs[name]
        assert (tuple(size_), blend_, tint_) == (size, blend, tint), f"{name}: {size_} {blend_} {tint_}"
        assert len([k for k in meta()["files"] if k.rsplit("_", 1)[0] == name]) == n, f"{name} 帧数不是 {n}"


def test_meta_fields():
    """meta.json：name = weapons（帧名 weapons/<名字>_<帧号>）、4 像素 / 世界单位；每帧 anim/frame/frames、fps、loop（默认 24、不循环）；同组锚点一样。"""
    m = meta()
    assert m["name"] == "weapons" and m["px_per_unit"] == 4 and m["generator"] == E.GENERATOR
    for name, (n, size, blend, tint) in SPEC.items():
        anchors = set()
        fps, loop = PLAY.get(name, (24, False))
        for i in range(n):
            info = m["files"][f"{name}_{i}.png"]
            assert info["size"] == list(size) and info["blend"] == blend and info["tint"] is tint, f"{name}_{i}: {info}"
            assert info["anim"] == name and info["frame"] == i and info["frames"] == n, f"{name}_{i} 的 anim/frame/frames 不对"
            assert info["fps"] == fps and info["loop"] is loop and info["note"], f"{name}_{i}: fps {info['fps']} loop {info['loop']}"
            anchors.add(tuple(info["anchor"]))
        assert len(anchors) == 1, f"{name} 各帧锚点不一样：{anchors}"
    pngs = {p.name for p in E.OUT.glob("*.png")}
    assert pngs == set(m["files"]), f"目录里的 PNG 和 meta 对不上：{sorted(pngs ^ set(m['files']))[:6]}"
    # 和别的 weapons/* 帧不重名
    old = json.loads((V.OUT / "assets@2x" / "weapons" / "meta.json").read_text(encoding="utf-8"))["files"]
    assert not set(old) & set(m["files"]), f"和 weapon_textures 的帧重名：{sorted(set(old) & set(m['files']))}"


def test_png_format():
    for name, (n, size, *_r) in SPEC.items():
        assert max(size) <= 1024, f"{name} 单帧 {size} 超过 1024²"
        for i in range(n):
            im = Image.open(E.OUT / f"{name}_{i}.png")
            assert im.mode == "RGBA" and im.size == size, f"{name}_{i}: {im.mode} {im.size}"
            assert alpha(name, i).sum() / 255 > 20, f"{name}_{i} 几乎是空的"


def test_scale_at_1080p():
    """跟半径走的帧写了 radius_px；1080p 下按玩法半径缩放，比例在 0.8–1.25（贴图约一比一，不靠游戏里放大）。"""
    for name, radii in RADII.items():
        R = float(meta()["files"][f"{name}_0.png"]["radius_px"])
        for r in radii:
            k = r * E.K1080 / R
            assert 0.8 <= k <= 1.25, f"{name}: 半径 {r} 在 1080p 下要缩放 {k:.2f}（radius_px {R:.0f}）"


def test_colors():
    """可染的 RGB 恒为白；铜钱火星、火海是暖色（R ≥ G ≥ B），火星第 0 帧的亮星接近烧白；尘土是土墨色。
    Blender 渲的灯、塔另有管线的调色板（这里不查）。"""
    for name, (n, _s, _b, tint) in SPEC.items():
        for i in range(n):
            px = rgba(name, i)
            vis = px[..., 3] > 0
            rgb = px[..., :3][vis].astype(int)
            if tint:
                assert (rgb == 255).all(), f"{name}_{i} 不是白色"
            elif name in ("coin_spark", "fire_sea"):
                assert (rgb[:, 0] >= rgb[:, 1]).all() and (rgb[:, 1] >= rgb[:, 2]).all(), f"{name}_{i} 不是暖色"
            elif name == "tower_dust":
                assert (rgb == np.array(V.col(E.DUST_INK) * 255).round()).all(), f"{name}_{i} 不是土墨色"
    hot = rgba("coin_spark", 0)
    w = hot[..., 3].astype(float)
    mean = (hot[..., :3].astype(float) * w[..., None]).sum((0, 1)) / w.sum()
    assert mean[2] > 200, f"火星第 0 帧的亮星不够白：{mean.round()}"
    late = rgba("coin_spark", 3)
    w = late[..., 3].astype(float)
    mean = (late[..., :3].astype(float) * w[..., None]).sum((0, 1)) / w.sum()
    assert mean[0] - mean[2] > 60, f"火星后几帧应该是铜金色：{mean.round()}"


def test_borders_and_clipping():
    for name, (n, *_r) in SPEC.items():
        for i in range(n):
            a = alpha(name, i)
            assert a[0].max() == a[-1].max() == a[:, 0].max() == a[:, -1].max() == 0, f"{name}_{i} 四边不透明"
            band = np.concatenate([a[:4].ravel(), a[-4:].ravel(), a[:, :4].ravel(), a[:, -4:].ravel()])
            assert band.max() <= 16, f"{name}_{i} 靠边还有 alpha {band.max():.0f}，形状被画布切了"


def test_peak_alpha():
    """叠加的特效帧最亮处 alpha 约 0.8（发光层、普通混合的不算）。"""
    for name in SPEC:
        if name in LAYERS or SPEC[name][2] != "add":
            continue
        peaks = [alpha(name, i).max() for i in frames_of(name)]
        assert max(peaks) <= PEAK8 + 2, f"{name} 最亮 {max(peaks):.0f} 超过 {PEAK8}"
        floor = PEAK8 - 70 if name in STILLS else PEAK8 - 40 if name == "wave_front_fade" else PEAK8 - 12  # 淡带子、散掉的不用到顶
        if name == "tower_vortex":  # 淡淡的一层（峰值上限 0.5）
            assert 50 <= max(peaks) <= 0.5 * 255 + 2, f"旋涡最亮 {max(peaks):.0f}"
            continue
        assert max(peaks) >= floor, f"{name} 最亮只有 {max(peaks):.0f}"


def test_frames_change_and_fade():
    """相邻两帧不一样；一次性的：最亮的帧在前一半，末帧淡到三成五以下（散掉、缠住留着的除外）；
    循环的：首尾接得上（末帧到首帧的变化和相邻两帧差不多），亮度一帧帧差不多（±25%）。"""
    for name in SPEC:
        if name in STILLS or name in ("tower_emit", "tower_gold_emit"):  # 塔的拱门光两帧本来一样
            continue
        sums = [alpha(name, i).sum() for i in frames_of(name)]
        diffs = [np.abs(alpha(name, i) - alpha(name, i - 1)).mean() for i in frames_of(name)[1:]]
        least = 0.002 if name in ("tower", "tower_gold") else 0.02  # 塔立着只有檐角的铃铛在摆
        assert min(diffs) > least, f"{name} 有两帧几乎一样：{[round(d, 4) for d in diffs]}"
        if name in HANDOFF or name in LAYERS and name[: -len("_emit")] in HANDOFF:
            continue
        if name in LOOPS:
            wrap = np.abs(alpha(name, 0) - alpha(name, len(sums) - 1)).mean()
            assert wrap <= 1.6 * max(diffs), f"{name} 循环首尾接不上：首尾差 {wrap:.2f}，相邻 {[round(d, 2) for d in diffs]}"
            assert min(sums) >= 0.75 * max(sums), f"{name} 循环里亮度跳：{[round(x / max(sums), 2) for x in sums]}"
            continue
        if name == "wave_front_fade":  # 接在循环后面散掉：一帧比一帧淡
            assert all(a > b for a, b in zip(sums, sums[1:])) and sums[-1] <= 0.6 * sums[0], f"浪头散掉应该越来越淡：{sums}"
            continue
        if name.endswith("lift") or name.endswith("lift_emit"):  # 塔收走：一帧比一帧散得多
            assert all(a > b for a, b in zip(sums, sums[1:])) and sums[-1] <= 0.35 * sums[0], f"{name} 应该越散越少：{sums}"
            continue
        if meta()["files"][f"{name}_0.png"].get("hold_last"):  # 末帧留着的：长到最后
            assert int(np.argmax(sums)) >= len(sums) - 2, f"{name} 应该越长越满：{[round(x / 255) for x in sums]}"
            continue
        assert int(np.argmax(sums)) < len(sums) / 2 + 0.5, f"{name} 最亮的帧太靠后：{[round(x / 255) for x in sums]}"
        assert 0 < sums[-1] <= 0.35 * max(sums), f"{name} 末帧 {sums[-1] / max(sums):.2f}"


# ---------------------------------------------------------------- 铜钱剑


def test_coin_spark_direction():
    """火星顺着入射方向（+X）溅：从第 1 帧起质心一帧比一帧往 +X 走，都在接触点的 +X 那边。"""
    ax = meta()["files"]["coin_spark_0.png"]["anchor"][0] * SPEC["coin_spark"][1][0]
    xs = [centroid(alpha("coin_spark", i))[0] for i in frames_of("coin_spark")]
    assert all(a < b for a, b in zip(xs[1:], xs[2:])), f"火星质心 x：{[round(x) for x in xs]}"
    assert min(xs[1:]) > ax + 4, f"火星没往 +X 溅：{[round(x) for x in xs]}，接触点 {ax}"
    assert meta()["files"]["coin_spark_0.png"]["points"] == "+x"


def test_coin_slash_fan():
    """挥击：弧心是锚点，扇形朝 +X 张开 120°；外沿 = radius_px；笔锋从上往下扫（质心的角度一帧比一帧大），
    扫完时整个扇面都有刀光；扇形外面（±64° 以外）几乎没东西。"""
    info = meta()["files"]["coin_slash_0.png"]
    R = float(info["radius_px"])
    w, h = SPEC["coin_slash"][1]
    assert R == E.CSLASH_R and info["angle_deg"] == 120 and info["points"] == "+x"
    assert info["anchor"] == [E.CSLASH_C[0] / w, E.CSLASH_C[1] / h]
    r, th = polar("coin_slash")
    angs = []
    for i in frames_of("coin_slash"):
        a = alpha("coin_slash", i)
        angs.append(float((a * th).sum() / a.sum()))
        if i <= 2:
            out = a[np.abs(th) > 64].sum() / a.sum()
            assert out <= 0.03, f"coin_slash_{i} 扇形外面还有 {out:.1%}"
        if i in (1, 2):
            m = (a / a.sum()).ravel()
            order = np.argsort(r.ravel())
            r99 = r.ravel()[order][np.searchsorted(np.cumsum(m[order]), 0.99)]
            assert R - 12 <= r99 <= R + 24, f"coin_slash_{i} 外沿 {r99:.0f}，radius_px {R:.0f}"
    # 0–4 帧刀光一路往下（末帧只剩收笔的碎丝和飘远的铜钱影子，不算）
    assert all(a < b for a, b in zip(angs[:5], angs[1:5])), f"笔锋应该从上往下扫：质心角度 {[round(x) for x in angs]}"
    a = sum(alpha("coin_slash", i) for i in (0, 1, 2))  # 0–2 帧扫过的地方合起来
    sectors = [a[(th >= s) & (th < s + 10) & (r > 0.6 * R)].sum() for s in range(-60, 60, 10)]
    assert min(sectors) >= 0.03 * sum(sectors), f"扇面有一块没扫到：{[round(x / sum(sectors), 3) for x in sectors]}"


def test_coin_whirl_ring():
    """天罡旋风：以锚点为圆心的一圈，外沿 = radius_px；转满一整圈（每 30° 都有刀光）；顺时针转。"""
    info = meta()["files"]["coin_whirl_0.png"]
    R = float(info["radius_px"])
    assert info["anchor"] == [0.5, 0.5] and R == E.WHIRL_R
    half = SPEC["coin_whirl"][1][0] / 2
    r, th = polar("coin_whirl")
    for i in (1, 2, 3):
        a = alpha("coin_whirl", i)
        m = (a / a.sum()).ravel()
        order = np.argsort(r.ravel())
        cum = np.cumsum(m[order])
        r50 = r.ravel()[order][np.searchsorted(cum, 0.5)]
        r99 = r.ravel()[order][np.searchsorted(cum, 0.99)]
        assert R * 0.55 <= r50 <= R, f"coin_whirl_{i} 主体半径 {r50:.0f}"
        lo = R * 0.85 if i == 1 else R - 8  # 第 1 帧还在往外张
        assert lo <= r99 <= R + 24, f"coin_whirl_{i} 外沿 {r99:.0f}，radius_px {R:.0f}"
        cx, cy = centroid(a)
        assert math.hypot(cx - half, cy - half) <= 0.04 * R, f"coin_whirl_{i} 偏心：({cx:.0f}, {cy:.0f})"
    a = alpha("coin_whirl", 2)
    sectors = [a[(th >= s) & (th < s + 30) & (r > 0.7 * R)].sum() for s in range(-180, 180, 30)]
    assert min(sectors) >= 0.03 * sum(sectors), f"天罡第 2 帧有一块没刀光：{[round(s / sum(sectors), 3) for s in sectors]}"

    def profile(i):
        a = alpha("coin_whirl", i)
        band = (r > 0.8 * R) & (r < 1.05 * R)
        return np.bincount(((th[band] + 180) // 2).astype(int) % 180, weights=a[band], minlength=180)

    for i in (1, 2, 3):
        p, q = profile(i), profile(i + 1)
        shifts = range(-29, 30)  # 2° 一格：±58°（三道主刀光相隔 120°，只能在 ±60° 里分得清转向）
        best = max(shifts, key=lambda k: float((np.roll(p, k) * q).sum()))
        assert best * 2 >= 10, f"coin_whirl_{i}→{i + 1} 应该顺时针转，算出来转了 {best * 2}°"


def test_coin_cross_two_strokes():
    """再斩：第 0 帧只有“╲”一道，第 1 帧“╱”交叉上去、两道差不多亮。"""
    r, th = polar("coin_cross")

    def along(i, deg):
        a = alpha("coin_cross", i)
        ang = math.radians(deg)
        ys, xs = np.mgrid[0:160, 0:160] + 0.5
        dist = np.abs(-(xs - 80) * math.sin(ang) + (ys - 80) * math.cos(ang))
        return a[(dist < 10) & (r > 14)].sum()

    a0, b0 = along(0, 38), along(0, 142)
    a1, b1 = along(1, 38), along(1, 142)
    assert a0 > 4 * b0, f"第 0 帧应该只有一道：{a0 / 255:.0f} vs {b0 / 255:.0f}"
    assert 0.5 <= b1 / a1 <= 2.0, f"第 1 帧两道应该差不多：{a1 / 255:.0f} vs {b1 / 255:.0f}"


# ---------------------------------------------------------------- 沧浪


def test_wave_front_crescent():
    """浪头：横着的月牙，往 +y 推进——正中最靠前（锚点在正中前沿），两头往后（−y）弯；铺满差不多整张宽；
    散掉的三帧和循环同画布、同锚点。"""
    w, h = SPEC["wave_front"][1]
    info = meta()["files"]["wave_front_0.png"]
    assert info["points"] == "+y" and info["half_width_px"] == int(E.WAVE_SPAN / 2) and info["loop"] is True
    assert meta()["files"]["wave_front_fade_0.png"]["anchor"] == info["anchor"]
    ay = info["anchor"][1] * h

    def front_y(a, x0, x1):  # 这几列里浪唇（每列最亮处）的平均 y
        return float(np.mean(np.argmax(a[:, x0:x1], axis=0)))

    for i in frames_of("wave_front"):
        a = alpha("wave_front", i)
        mid, left, right = front_y(a, w // 2 - 20, w // 2 + 20), front_y(a, 40, 70), front_y(a, w - 70, w - 40)
        assert abs(mid - ay) <= 6, f"wave_front_{i} 正中前沿 {mid:.0f}，锚点 {ay:.0f}"
        assert left < mid - 20 and right < mid - 20, f"wave_front_{i} 两头应该往后弯：{left:.0f} / {mid:.0f} / {right:.0f}"
        x0, _, x1, _ = bbox(a > 0.25 * PEAK8)
        assert x1 - x0 >= 0.85 * w, f"wave_front_{i} 不够宽：{x1 - x0}"


def test_wave_trail_fades_backward():
    """泡沫痕：锚点在下边正中，靠浪头这头（下）最亮，往远处（上）淡下去。"""
    a = alpha("wave_trail", 0)
    info = meta()["files"]["wave_trail_0.png"]
    assert info["anchor"] == [0.5, 1.0] and info["stretch"] == "y"
    h = a.shape[0]
    near, far = a[int(h * 0.7) : int(h * 0.95)].sum(), a[int(h * 0.05) : int(h * 0.3)].sum()
    assert near > 3 * far, f"泡沫痕应该越远越淡：近 {near / 255:.0f}，远 {far / 255:.0f}"


# ---------------------------------------------------------------- 青藤


def test_vine_spans_and_anchors():
    """藤：锚点在右端正中；横向铺满（两端几像素淡掉），两端落在中线上（接主角和妖物）；整张高 = 10 世界单位。"""
    w, h = SPEC["vine"][1]
    info = meta()["files"]["vine_0.png"]
    assert info["anchor"] == [1.0, 0.5] and info["stretch"] == "x" and info["height_units"] == 10
    for i in frames_of("vine"):
        a = alpha("vine", i)
        cols = (a > 0.25 * PEAK8).any(0)
        assert cols[16 : w - 16].mean() >= 0.97, f"vine_{i} 中间断了"
        for x0, x1 in ((6, 22), (w - 22, w - 6)):
            c = a[:, x0:x1]
            cy = float((c.sum(1) * (np.arange(h) + 0.5)).sum() / max(c.sum(), 1))
            assert abs(cy - h / 2) <= 2.5, f"vine_{i} 端头不在中线上：{cy:.1f}"


def test_vine_pulse_head_forward():
    """回血的绿光：最亮处在锚点（光头），尾巴拖在 −x 那边。"""
    w, h = SPEC["vine_pulse"][1]
    ax, ay = (np.array(meta()["files"]["vine_pulse_0.png"]["anchor"]) * [w, h]).tolist()
    for i in frames_of("vine_pulse"):
        a = alpha("vine_pulse", i)
        yy, xx = np.unravel_index(np.argmax(a), a.shape)
        assert math.hypot(xx + 0.5 - ax, yy + 0.5 - ay) <= 4, f"vine_pulse_{i} 最亮处 ({xx}, {yy}) 不在光头"
        cx, _ = centroid(a)
        assert cx < ax - 8, f"vine_pulse_{i} 尾巴应该在 −x：质心 {cx:.0f}"


def test_vine_bind_grows_up():
    """万木春缠绕：藤从脚下往上长（质心一帧比一帧高、亮的范围变高），第 3 帧留着（hold_last）。"""
    info = meta()["files"]["vine_bind_0.png"]
    assert info["hold_last"] is True and info["radius_px"] == int(E.BIND_R)
    tops = [bbox(alpha("vine_bind", i) > 0.25 * PEAK8)[1] for i in frames_of("vine_bind")]
    assert tops[0] > tops[1] > tops[2], f"缠绕应该越长越高：顶 {tops}"


# ---------------------------------------------------------------- 孔明灯、镇妖塔


def opaque_box(name, i, thr=0.5):
    return bbox(alpha(name, i) > thr * 255)


def test_lantern_size_and_layers():
    """孔明灯：原大约宽 20、高 26 世界单位（4 像素 / 单位），锚点在灯身中心；发光层在灯的剪影里；
    坠落三帧越歪越厉害（剪影的长轴转过去）。"""
    for i in frames_of("sky_lantern"):
        x0, y0, x1, y1 = opaque_box("sky_lantern", i)
        wu, hu = (x1 - x0 + 1) / 4, (y1 - y0 + 1) / 4
        assert 17 <= wu <= 23 and 23 <= hu <= 29, f"sky_lantern_{i} 大小 {wu:.1f}×{hu:.1f} 单位"
        assert abs((x0 + x1) / 2 - 96) <= 6 and abs((y0 + y1) / 2 - 96) <= 10, f"sky_lantern_{i} 不在锚点上"
    for base, glow in (("sky_lantern", "sky_lantern_emit"), ("sky_lantern_fall", "sky_lantern_fall_emit")):
        for i in frames_of(base):
            inside = V.fft_blur((alpha(base, i) > 8).astype(float), 1.5) > 0.05
            outside = alpha(glow, i)[~inside].sum() / max(alpha(glow, i).sum(), 1)
            assert outside < 0.02, f"{glow}_{i} 有 {outside:.1%} 在灯的剪影外"

    widths = [np.ptp(np.nonzero(alpha("sky_lantern_fall", i).max(0) > 128)[0]) for i in frames_of("sky_lantern_fall")]
    w0 = np.ptp(np.nonzero(alpha("sky_lantern", 0).max(0) > 128)[0])
    assert w0 < widths[0] < widths[2], f"坠落应该越歪越横：飘着宽 {w0}，坠落 {widths}"


def test_lantern_mark_and_fire_sea():
    """落点圈、火海：贴地压扁（高 ÷ 宽 ≈ 0.62），横向半径和 radius_px 对得上。"""
    for name in ("lantern_mark", "fire_sea"):
        R = meta()["files"][f"{name}_0.png"]["radius_px"]
        for i in frames_of(name):
            x0, y0, x1, y1 = bbox(alpha(name, i) > 0.15 * PEAK8)
            assert abs((x1 - x0 + 1) / 2 - R) <= 0.15 * R + 8, f"{name}_{i} 横向半径 {(x1 - x0 + 1) / 2:.0f}，radius_px {R}"
            if name == "lantern_mark":
                ratio = (y1 - y0 + 1) / (x1 - x0 + 1)
                assert abs(ratio - F.FLAT) <= 0.06, f"{name}_{i} 高宽比 {ratio:.2f}"


def test_tower_sizes():
    """镇妖塔约宽 40、高 70 世界单位，玲珑塔约宽 56、高 96（4 像素 / 单位）；锚点在基座：塔的最下沿就在锚点下面不远；
    拱门的光在塔身里；落下第 0 帧比立着时高；收走一帧比一帧散。"""
    for name, (wu_, hu_) in (("tower", (40, 70)), ("tower_gold", (56, 96))):
        w, h = SPEC[name][1]
        ay = meta()["files"][f"{name}_0.png"]["anchor"][1] * h
        x0, y0, x1, y1 = opaque_box(name, 0)
        wu, hu = (x1 - x0 + 1) / 4, (y1 - y0 + 1) / 4
        assert abs(wu - wu_) <= 0.18 * wu_ and abs(hu - hu_) <= 0.12 * hu_, f"{name} 大小 {wu:.0f}×{hu:.0f} 单位"
        assert 0 <= y1 - ay <= 70, f"{name} 基座最下沿 {y1}，锚点 {ay:.0f}"
        inside = V.fft_blur((alpha(name, 0) > 8).astype(float), 1.5) > 0.05
        assert alpha(f"{name}_emit", 0)[~inside].sum() < 0.02 * max(alpha(f"{name}_emit", 0).sum(), 1), f"{name} 的拱门光跑出塔外"
        assert opaque_box(f"{name}_fall", 0)[1] < y0 - 40, f"{name}_fall_0 应该在上方"
        fall2 = opaque_box(f"{name}_fall", 2)
        assert (fall2[2] - fall2[0]) > (x1 - x0), f"{name}_fall_2 落地应该压扁变宽"


def test_tower_dust_and_vortex():
    """尘土一帧比一帧往外滚（越来越宽）、末帧淡；旋涡压扁、横向半径对得上 radius_px。"""
    widths = [np.ptp(np.nonzero(alpha("tower_dust", i).max(0) > 20)[0]) for i in frames_of("tower_dust")]
    assert all(a < b for a, b in zip(widths, widths[1:])), f"尘土应该越滚越宽：{widths}"
    R = meta()["files"]["tower_vortex_0.png"]["radius_px"]
    x0, y0, x1, y1 = bbox(alpha("tower_vortex", 0) > 20)
    assert abs((x1 - x0 + 1) / 2 - R) <= 0.06 * R, f"旋涡横向半径 {(x1 - x0 + 1) / 2:.0f}，radius_px {R}"
    assert abs((y1 - y0 + 1) / (x1 - x0 + 1) - F.FLAT) <= 0.05, "旋涡没按地面透视压扁"


# ---------------------------------------------------------------- 其他


def test_review_images():
    for key in E.BATCHES:
        sheet = Image.open(E.REVIEW / f"weapons_ea_{key}.png")
        assert sheet.width >= 900, f"weapons_ea_{key} 帧条尺寸 {sheet.size}"
        assert Image.open(E.REVIEW / f"weapons_ea_{key}_ingame.png").size == (1920, 1080)


def test_deterministic():
    if "--quick" in sys.argv:
        print("      （--quick：跳过）")
        return
    for batch in E.BATCHES.values():
        for name, imgs in F.build(batch).items():
            for i, img in enumerate(imgs):
                assert (np.asarray(img) == rgba(name, i)).all(), f"{name}_{i} 和磁盘上的不一样"


def test_writes_only_own_outputs():
    if not WRITTEN:
        print("      （这次没有重新生成，跳过写盘检查；加 --regen 可测）")
        return
    out, review = E.OUT.resolve(), E.REVIEW.resolve()
    for p in WRITTEN:
        assert p.is_relative_to(out) or (p.is_relative_to(review) and p.name.startswith("weapons_ea_")), f"写到了不该写的地方：{p}"
    assert protected() == SNAPSHOT, "别的产物（assets/atlas 或 art/out/assets@2x 的其他目录）被改动了"


def test_atlas_packed():
    """打包后的 vfx 图集里每帧都在（weapons/<名字>_<帧号>）：锚点、混合、可染、动画字段原样带进去，像素和产物一样。还没打包时跳过。"""
    index = json.loads((ATLAS / "index.json").read_text(encoding="utf-8"))
    frames, info, page_of = {}, {}, {}
    for fn in index["pages"].get("vfx", []):
        j = json.loads((ATLAS / fn).read_text(encoding="utf-8"))
        img = np.asarray(Image.open(ATLAS / j["meta"]["image"]).convert("RGBA"))
        for k, f in j["frames"].items():
            frames[k], page_of[k] = f, img
        info.update(j["meta"]["lantern"]["frames"])
    first = f"weapons/{next(iter(SPEC))}_0"
    if first not in frames:
        print("      （assets/atlas 里还没有新法器的帧，跳过）")
        return
    for name, (n, size, _b, _t) in SPEC.items():
        for i in range(n):
            key = f"weapons/{name}_{i}"
            assert key in frames, f"图集里缺 {key}"
            f, li, src = frames[key], info[key], meta()["files"][f"{name}_{i}.png"]
            assert (f["sourceSize"]["w"], f["sourceSize"]["h"]) == size and [f["anchor"]["x"], f["anchor"]["y"]] == src["anchor"], key
            for k in ("blend", "tint", "anim", "frame", "frames", "fps", "loop"):
                assert li[k] == src[k], f"{key} 的 {k}：图集 {li[k]}，产物 {src[k]}"
            r, s = f["frame"], f["spriteSourceSize"]
            can = np.zeros((size[1], size[0], 4), np.uint8)
            can[s["y"] : s["y"] + s["h"], s["x"] : s["x"] + s["w"]] = page_of[key][r["y"] : r["y"] + r["h"], r["x"] : r["x"] + r["w"]]
            b = rgba(name, i)
            vis = (can[..., 3] > 0) | (b[..., 3] > 0)
            assert (can[..., 3] == b[..., 3]).all() and (can[vis] == b[vis]).all(), f"图集里的 {key} 和产物不一样"


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
