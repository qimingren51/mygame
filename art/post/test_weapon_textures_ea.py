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
    "coin_spark": (5, (128, 128), "add", False),
    "coin_whirl": (6, (448, 448), "add", True),
    "coin_cross": (4, (160, 160), "add", True),
}
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
    """meta.json：name = weapons（帧名 weapons/<名字>_<帧号>）、4 像素 / 世界单位；每帧 anim/frame/frames、fps 24、不循环；同组锚点一样。"""
    m = meta()
    assert m["name"] == "weapons" and m["px_per_unit"] == 4 and m["generator"] == E.GENERATOR
    for name, (n, size, blend, tint) in SPEC.items():
        anchors = set()
        for i in range(n):
            info = m["files"][f"{name}_{i}.png"]
            assert info["size"] == list(size) and info["blend"] == blend and info["tint"] is tint, f"{name}_{i}: {info}"
            assert info["anim"] == name and info["frame"] == i and info["frames"] == n, f"{name}_{i} 的 anim/frame/frames 不对"
            assert info["fps"] == 24 and info["loop"] is False and info["note"], f"{name}_{i}: fps {info['fps']} loop {info['loop']}"
            anchors.add(tuple(info["anchor"]))
        assert len(anchors) == 1, f"{name} 各帧锚点不一样：{anchors}"
    pngs = {p.name for p in E.OUT.glob("*.png")}
    assert pngs == set(m["files"]), f"目录里的 PNG 和 meta 对不上：{sorted(pngs ^ set(m['files']))[:6]}"
    # 和别的 weapons/* 帧不重名
    old = json.loads((V.OUT / "assets@2x" / "weapons" / "meta.json").read_text(encoding="utf-8"))["files"]
    assert not set(old) & set(m["files"]), f"和 weapon_textures 的帧重名：{sorted(set(old) & set(m['files']))}"


def test_png_format():
    for name, (n, size, *_r) in SPEC.items():
        for i in range(n):
            im = Image.open(E.OUT / f"{name}_{i}.png")
            assert im.mode == "RGBA" and im.size == size, f"{name}_{i}: {im.mode} {im.size}"
            assert alpha(name, i).sum() / 255 > 20, f"{name}_{i} 几乎是空的"


def test_colors():
    """可染的 RGB 恒为白；铜钱火星是暖的铜金色（R ≥ G ≥ B），第 0 帧的亮星接近烧白。"""
    for name, (n, _s, _b, tint) in SPEC.items():
        for i in range(n):
            px = rgba(name, i)
            vis = px[..., 3] > 0
            rgb = px[..., :3][vis].astype(int)
            if tint:
                assert (rgb == 255).all(), f"{name}_{i} 不是白色"
            else:
                assert (rgb[:, 0] >= rgb[:, 1]).all() and (rgb[:, 1] >= rgb[:, 2]).all(), f"{name}_{i} 不是暖色"
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
    for name in SPEC:
        peaks = [alpha(name, i).max() for i in frames_of(name)]
        assert max(peaks) <= PEAK8 + 2, f"{name} 最亮 {max(peaks):.0f} 超过 {PEAK8}"
        assert max(peaks) >= PEAK8 - 12, f"{name} 最亮只有 {max(peaks):.0f}"


def test_frames_change_and_fade():
    """相邻两帧不一样；一次性的：最亮的帧在前一半，末帧淡到三成五以下。"""
    for name in SPEC:
        sums = [alpha(name, i).sum() for i in frames_of(name)]
        for i in frames_of(name)[1:]:
            d = np.abs(alpha(name, i) - alpha(name, i - 1)).mean()
            assert d > 0.02, f"{name}_{i - 1} 和 {name}_{i} 几乎一样"
        assert int(np.argmax(sums)) < len(sums) / 2 + 0.5, f"{name} 最亮的帧太靠后：{[round(s / 255) for s in sums]}"
        assert 0 < sums[-1] <= 0.35 * max(sums), f"{name} 末帧 {sums[-1] / max(sums):.2f}"


# ---------------------------------------------------------------- 铜钱剑


def test_coin_spark_direction():
    """火星顺着入射方向（+X）溅：从第 1 帧起质心一帧比一帧往 +X 走，都在接触点的 +X 那边。"""
    ax = meta()["files"]["coin_spark_0.png"]["anchor"][0] * SPEC["coin_spark"][1][0]
    xs = [centroid(alpha("coin_spark", i))[0] for i in frames_of("coin_spark")]
    assert all(a < b for a, b in zip(xs[1:], xs[2:])), f"火星质心 x：{[round(x) for x in xs]}"
    assert min(xs[1:]) > ax + 4, f"火星没往 +X 溅：{[round(x) for x in xs]}，接触点 {ax}"
    assert meta()["files"]["coin_spark_0.png"]["points"] == "+x"


def test_coin_whirl_ring():
    """天罡旋风：以锚点为圆心的一圈，外沿 = radius_px；转满一整圈（每 30° 都有刀光）；顺时针转。"""
    info = meta()["files"]["coin_whirl_0.png"]
    R = float(info["radius_px"])
    assert info["anchor"] == [0.5, 0.5] and R == E.WHIRL_R
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
        assert math.hypot(cx - 224, cy - 224) <= 12, f"coin_whirl_{i} 偏心：({cx:.0f}, {cy:.0f})"
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


# ---------------------------------------------------------------- 其他


def test_review_images():
    for key in E.BATCHES:
        sheet = Image.open(E.REVIEW / f"weapons_ea_{key}.png")
        assert sheet.width >= 1500, f"weapons_ea_{key} 帧条尺寸 {sheet.size}"
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
