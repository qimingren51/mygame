#!/usr/bin/env python3
"""weapon_textures.py 的自检：纯 assert，不依赖 pytest。

每次运行都会先重新生成一遍（约 20 秒），同时记录脚本写了哪些文件，
再单独渲染一遍与磁盘上的结果逐像素比对（确定性），全程约 35 秒。

用法（在 lantern-next/ 目录下）：
  art/.venv/bin/python art/post/test_weapon_textures.py
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
import weapon_textures as W  # noqa: E402

V = W.V
S = W.S

# 文件名 → (尺寸, 锚点)。与任务约定一致，独立写一份，不从生成脚本里取。
EXPECTED = {
    "sword.png": ((44, 12), (0.6, 0.5)),
    "sword_evo.png": ((52, 14), (0.6, 0.5)),
    "sword_trail.png": ((48, 10), (1.0, 0.5)),
    **{f"crane_{i}.png": ((30, 26), (0.5, 0.5)) for i in range(4)},
    **{f"crane_evo_{i}.png": ((30, 26), (0.5, 0.5)) for i in range(4)},
    "ring.png": ((128, 128), (0.5, 0.5)),
    "ring_ink.png": ((128, 128), (0.5, 0.5)),
    "seal.png": ((40, 44), (0.5, 0.85)),
    "seal_evo.png": ((56, 60), (0.5, 0.85)),
    "seal_mark.png": ((64, 64), (0.5, 0.5)),
    "crack.png": ((128, 96), (0.5, 0.5)),
    "warn.png": ((64, 64), (0.5, 0.5)),
    "taiji.png": ((128, 128), (0.5, 0.5)),
    "blast.png": ((64, 64), (0.5, 0.5)),
    "shield.png": ((64, 64), (0.5, 0.5)),
    "chest.png": ((40, 36), (0.5, 0.85)),
    "soulbell.png": ((20, 26), (0.5, 0.85)),
    "lotus.png": ((22, 20), (0.5, 0.8)),
}
# 白色、可染色、叠加混合的贴图
WHITE_TINT = {"sword_trail.png", "ring.png", "warn.png", "blast.png", "shield.png"}
REVIEW = ["weapons_sheet.png", "weapons_ingame.png"]

WRITTEN: list[Path] = []
SNAPSHOT: dict[str, tuple[int, int]] = {}


def snapshot_other_outputs() -> dict[str, tuple[int, int]]:
    """vfx_textures.py 的产物（vfx/、ground/）：修改时间和大小。"""
    out = {}
    for folder in (V.VFX_DIR, V.GROUND_DIR):
        if folder.exists():
            for p in sorted(folder.iterdir()):
                st = p.stat()
                out[str(p)] = (st.st_mtime_ns, st.st_size)
    return out


def regenerate() -> None:
    """重新生成，并记录所有写盘的路径（包住 save_png 和 Path.write_text）。"""
    SNAPSHOT.update(snapshot_other_outputs())
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
        W.main()
    finally:
        V.save_png = orig_save
        Path.write_text = orig_write  # type: ignore[method-assign]


def rgba(name: str) -> np.ndarray:
    return np.asarray(Image.open(W.WEAPON_DIR / name).convert("RGBA"), dtype=np.int64)


def meta_files() -> dict:
    return json.loads((W.WEAPON_DIR / "meta.json").read_text(encoding="utf-8"))["files"]


# ---------------------------------------------------------------- 尺寸、锚点、meta


def test_meta_sizes_and_anchors():
    files = meta_files()
    assert set(files) == set(EXPECTED), f"meta.json 文件列表不符：{sorted(set(files) ^ set(EXPECTED))}"
    for name, (size, anchor) in EXPECTED.items():
        e = files[name]
        assert tuple(e["size"]) == size, f"{name} meta size {e['size']} != {size}"
        assert tuple(e["anchor"]) == anchor, f"{name} meta anchor {e['anchor']} != {anchor}"
        im = Image.open(W.WEAPON_DIR / name)
        assert im.size == size, f"{name} 实际尺寸 {im.size} != {size}"
        assert im.mode == "RGBA", f"{name} mode {im.mode} != RGBA"


def test_meta_blend_and_tint():
    files = meta_files()
    for name, e in files.items():
        for key in ("blend", "tint", "note"):
            assert key in e, f"{name} meta 缺少 {key}"
        if name in WHITE_TINT:
            assert e["blend"] == "add" and e["tint"] is True and e["color"] == "white", f"{name} 应为白色、可染色、叠加"
        else:
            assert e["blend"] == "normal" and e["tint"] is False, f"{name} 应为正常混合、不染色"


def test_png_files_match_meta():
    pngs = {p.name for p in W.WEAPON_DIR.glob("*.png")}
    assert pngs == set(EXPECTED), f"weapons/ 里多出或缺少文件：{sorted(pngs ^ set(EXPECTED))}"


# ---------------------------------------------------------------- 像素


def test_white_textures_are_white():
    for name in WHITE_TINT:
        a = rgba(name)
        assert (a[..., :3] == 255).all(), f"{name} RGB 应恒为 255（游戏里染色）"


def test_colour_sprites_have_colour():
    """全彩贴图：要有墨（暗像素）且不是纯白；带点缀色的要真的出现该颜色。"""
    for name in EXPECTED:
        if name in WHITE_TINT:
            continue
        a = rgba(name)
        vis = a[..., 3] > 128
        rgb = a[..., :3][vis].astype(np.float64)
        assert len(rgb) > 0, f"{name} 没有不透明像素"
        assert (rgb.sum(1) < 200).any() or name == "seal_mark.png", f"{name} 没有墨线/暗部"
        assert not (rgb == 255).all(), f"{name} 不应是纯白"

    def red_frac(name):
        a = rgba(name)
        vis = a[..., 3] > 128
        r, g, b = (a[..., i][vis] for i in range(3))
        return ((r > g + 60) & (r > b + 60)).mean()

    assert red_frac("seal_mark.png") > 0.85, "印迹应以朱砂红为主"
    assert red_frac("chest.png") > 0.3, "宝箱应是朱漆"
    for name in ("sword.png", "sword_evo.png", "seal.png", "soulbell.png", *(f"crane_{i}.png" for i in range(4))):
        assert red_frac(name) > 0.0, f"{name} 应有一点朱砂"


def test_alpha_not_empty():
    for name in EXPECTED:
        al = rgba(name)[..., 3]
        assert al.max() >= 200, f"{name} 最大 alpha 太低（{al.max()}）"
        frac = (al > 8).mean()
        assert frac > 0.03, f"{name} 可见像素太少（{frac:.3f}）"


def test_borders_transparent():
    for name in EXPECTED:
        al = rgba(name)[..., 3]
        border = np.concatenate([al[0], al[-1], al[:, 0], al[:, -1]])
        assert border.max() == 0, f"{name} 最外一圈像素必须全透明（最大 {border.max()}）"


def test_point_right():
    """有方向的精灵在旋转 0 时指向 +X。"""
    for name in ("sword.png", "sword_evo.png"):
        a = rgba(name)
        al = a[..., 3]
        w = al.shape[1]
        cols = np.nonzero((al > 128).any(0))[0]
        assert cols.max() > 0.93 * w, f"{name} 剑尖没有到右端"
        r, g, b = a[..., 0], a[..., 1], a[..., 2]
        red = (al > 128) & (r > g + 70) & (r > b + 70)
        assert red.any() and np.nonzero(red)[1].mean() < 0.3 * w, f"{name} 朱砂剑穗应在左边"
        # 剑身右半比左半细（剑尖在右）
        h_right = (al[:, int(0.88 * w)] > 128).sum()
        h_mid = (al[:, int(0.6 * w)] > 128).sum()
        assert h_right <= h_mid, f"{name} 剑尖应比剑身细"
    al = rgba("sword_trail.png")[..., 3].astype(np.float64)
    xs = np.arange(al.shape[1])
    cx = (al.sum(0) * xs).sum() / al.sum()
    assert cx > 0.6 * al.shape[1], "剑尾光的粗亮端应在右边（锚点 1.0）"
    for i in range(4):
        for prefix in ("crane", "crane_evo"):
            a = rgba(f"{prefix}_{i}.png")
            r, g, b, al = a[..., 0], a[..., 1], a[..., 2], a[..., 3]
            red = (al > 100) & (r > g + 50) & (r > b + 50)
            assert red.any(), f"{prefix}_{i} 头上没有朱砂点"
            assert np.nonzero(red)[1].mean() > 0.7 * a.shape[1], f"{prefix}_{i} 头（朱砂点）应在右边"


def test_ground_anchor():
    """锚点 y 是落地点：锚点以下只剩很少的内容（阴影、铃舌），锚点所在行有内容。"""
    for name in ("seal.png", "seal_evo.png", "chest.png", "soulbell.png", "lotus.png"):
        al = rgba(name)[..., 3]
        h = al.shape[0]
        ay = EXPECTED[name][1][1] * h
        rows = np.nonzero((al > 128).any(1))[0]
        assert rows.max() >= ay - 1.0, f"{name} 底部在锚点上方太远（底 {rows.max()}，锚点 {ay:.1f}）"
        assert rows.max() <= ay + 4.0, f"{name} 锚点以下内容太多（底 {rows.max()}，锚点 {ay:.1f}）"


def test_crane_flap():
    frames = [rgba(f"crane_{i}.png")[..., 3].astype(np.float64) for i in range(4)]
    area = [f.sum() for f in frames]
    assert max(area) / min(area) < 1.6, f"各帧面积差太多：{area}"
    for i in range(4):
        j = (i + 1) % 4
        diff = np.abs(frames[i] - frames[j]).mean()
        assert diff > 2.0, f"crane_{i} 与 crane_{j} 几乎一样，没有扑翼"
    # 第 0 帧翅膀向上、第 2 帧翅膀向下：可见像素的竖直重心
    ys = np.arange(frames[0].shape[0])[:, None]
    cy = [(f * ys).sum() / f.sum() for f in frames]
    assert cy[0] < cy[2] - 1.0, f"翅膀上扬帧的重心应比下扑帧高：{cy}"


def test_ring_profile():
    a = rgba("ring.png")[..., 3].astype(np.float64)
    n = a.shape[0]
    yy, xx = np.mgrid[0:n, 0:n] + 0.5
    r = np.hypot(xx - n / 2, yy - n / 2)
    prof = np.array([a[(r >= k) & (r < k + 1)].mean() for k in range(n // 2)])
    peak = int(prof.argmax())
    want = meta_files()["ring.png"]["radius_px"]
    assert abs(peak - want) <= 4, f"环的最亮半径 {peak} 与 meta radius_px {want} 不符"
    assert prof[:12].max() == 0, "环中心应完全透明"
    assert prof[peak - 14] < prof[peak] * 0.5, "环内侧应淡出"
    assert prof[peak - 14] > 0, "环内侧应有柔和的余波"


def test_seal_mark_glyph_is_hollow():
    """白文：字口透明。印面中心竖笔处 alpha 应很低，旁边的朱砂地 alpha 高。"""
    a = rgba("seal_mark.png")[..., 3]
    c = a.shape[0] // 2
    assert a[c - 4 : c + 4, c - 1 : c + 2].mean() < 40, "印文中竖处应透出地面"
    assert a[c - 12 : c - 6, c - 9 : c - 5].mean() > 150, "字旁的朱砂地应不透明"


# ---------------------------------------------------------------- 确定性、体积、写盘范围


def test_deterministic():
    again = W.build()
    for key, (img, _, _) in again.items():
        disk = np.asarray(Image.open(W.WEAPON_DIR / f"{key}.png").convert("RGBA"))
        assert (np.asarray(img) == disk).all(), f"{key} 两次生成结果不一致"


def test_total_size():
    total = sum(p.stat().st_size for p in W.WEAPON_DIR.glob("*.png"))
    assert total < 300 * 1024, f"贴图总体积 {total / 1024:.1f} KB 超过 300 KB"


def test_writes_only_own_outputs():
    allowed = (W.WEAPON_DIR.resolve(), W.REVIEW_DIR.resolve())
    assert WRITTEN, "没有记录到写盘"
    for p in WRITTEN:
        assert any(p.is_relative_to(d) for d in allowed), f"写到了不该写的地方：{p}"
    for p in WRITTEN:
        if p.is_relative_to(W.REVIEW_DIR.resolve()):
            assert p.name.startswith("weapons_"), f"检查图名字应以 weapons_ 开头：{p.name}"
    assert snapshot_other_outputs() == SNAPSHOT, "vfx/ 或 ground/ 的产物被改动了"


def test_review_images():
    for name in REVIEW:
        p = W.REVIEW_DIR / name
        assert p.exists() and p.stat().st_size > 20_000, f"检查图 {name} 缺失或为空"


def main() -> int:
    regenerate()
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
