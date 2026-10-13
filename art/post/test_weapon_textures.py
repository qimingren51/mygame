#!/usr/bin/env python3
"""weapon_textures.py 的自检：纯 assert，不依赖 pytest。

每次运行都会先重新生成一遍，同时记录脚本写了哪些文件，再单独渲染一遍与磁盘上的结果逐像素比对（确定性）。
不设 LANTERN_ART_DENSITY 时自动在 1 倍、2 倍各跑一遍（子进程，约 1 分钟 + 3 分钟）；设了就只测那一种密度。
1 倍还要核对与密度改造前的基准逐字节相同（post/golden_1x.json）；2 倍要与 1 倍是“同一张画”。

用法（在仓库根目录下）：
  art/.venv/bin/python art/post/test_weapon_textures.py
  LANTERN_ART_DENSITY=1 art/.venv/bin/python art/post/test_weapon_textures.py   # 只测 1 倍
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

import weapon_textures as W  # noqa: E402

V = W.V
S = W.S
D = V.D


def sz(w: int, h: int) -> tuple[int, int]:
    return (int(round(w * D)), int(round(h * D)))

# 文件名 → (尺寸, 锚点)。与任务约定一致，独立写一份，不从生成脚本里取。
EXPECTED = {
    "sword.png": (sz(44, 12), (0.6, 0.5)),
    "sword_evo.png": (sz(52, 14), (0.6, 0.5)),
    "sword_trail.png": (sz(48, 10), (1.0, 0.5)),
    **{f"crane_{i}.png": (sz(30, 26), (0.5, 0.5)) for i in range(4)},
    **{f"crane_evo_{i}.png": (sz(30, 26), (0.5, 0.5)) for i in range(4)},
    "ring.png": (sz(128, 128), (0.5, 0.5)),
    "ring_ink.png": (sz(128, 128), (0.5, 0.5)),
    "seal.png": (sz(40, 44), (0.5, 0.85)),
    "seal_evo.png": (sz(56, 60), (0.5, 0.85)),
    "seal_mark.png": (sz(64, 64), (0.5, 0.5)),
    "crack.png": (sz(128, 96), (0.5, 0.5)),
    "warn.png": (sz(64, 64), (0.5, 0.5)),
    "taiji.png": (sz(128, 128), (0.5, 0.5)),
    "blast.png": (sz(64, 64), (0.5, 0.5)),
    "shield.png": (sz(64, 64), (0.5, 0.5)),
    "chest.png": (sz(40, 36), (0.5, 0.85)),
    "soulbell.png": (sz(20, 26), (0.5, 0.85)),
    "lotus.png": (sz(22, 20), (0.5, 0.8)),
    **{f"foxfire_{i}.png": (sz(24, 24), (0.6, 0.5)) for i in range(3)},
    # M2.5：扇形预警（锚点在扇顶）
    "sector.png": (sz(76, 124), (0.0625, 0.5)),
    "sector_fill.png": (sz(76, 124), (0.0625, 0.5)),
    # M2.5：冲锋预警（车道沿 X 拉伸，锚点在起点；箭头锚点在底边正中）
    "charge_line.png": (sz(128, 20), (0.0, 0.5)),
    "charge_line_head.png": (sz(32, 32), (0.125, 0.5)),
}
# 白色、可染色、叠加混合的贴图
WHITE_TINT = {"sword_trail.png", "ring.png", "warn.png", "blast.png", "shield.png", *(f"foxfire_{i}.png" for i in range(3)), "sector.png", "sector_fill.png", "charge_line.png", "charge_line_head.png"}
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


STRETCH_X = {"charge_line.png"}  # 沿 X 拉伸的车道：最右一列故意不清零（接箭头不留缝）


def test_borders_transparent():
    for name in EXPECTED:
        al = rgba(name)[..., 3]
        border = np.concatenate([al[0], al[-1], al[:, 0]] + ([] if name in STRETCH_X else [al[:, -1]]))
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
    for i in range(3):
        al = rgba(f"foxfire_{i}.png")[..., 3].astype(np.float64)
        w = al.shape[1]
        xs = np.arange(w)
        hot_cx = ((al**4).sum(0) * xs).sum() / (al**4).sum()
        assert hot_cx > 0.5 * w, f"foxfire_{i} 最亮的火球应在右半边（朝 +X 飞），重心 {hot_cx:.1f}"
        ax = EXPECTED[f"foxfire_{i}.png"][1][0] * w
        cols = np.nonzero((al > 20).any(0))[0]
        assert ax - cols.min() > 1.5 * (cols.max() - ax), f"foxfire_{i} 火舌应向左（飞行反方向）拖得比火球长"
        assert al[:, : w // 3].sum() > 0.05 * al.sum(), f"foxfire_{i} 左边应拖着火舌"
    ff = [rgba(f"foxfire_{i}.png")[..., 3].astype(np.float64) for i in range(3)]
    assert min(np.abs(ff[i] - ff[(i + 1) % 3]).mean() for i in range(3)) > 0.5, "狐火各帧应有闪动"
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
        assert rows.max() <= ay + 4.0 * D, f"{name} 锚点以下内容太多（底 {rows.max()}，锚点 {ay:.1f}）"


def test_sector_shape():
    """扇形预警：扇顶在锚点、开口朝 +X、张角约 120°、外沿最亮处的半径与 meta 的 radius_px 一致；外沿比扇面里面亮（读得出是预警）；
    蓄力层同尺寸，外沿一道亮带。"""
    meta = meta_files()
    for name in ("sector.png", "sector_fill.png"):
        a = rgba(name)[..., 3].astype(np.float64) / 255.0
        h, w = a.shape
        ax, ay = EXPECTED[name][1][0] * w, EXPECTED[name][1][1] * h
        yy, xx = np.mgrid[0:h, 0:w] + 0.5
        r = np.hypot(xx - ax, yy - ay)
        ang = np.degrees(np.arctan2(yy - ay, xx - ax))
        vis = a > 0.15
        assert (xx[vis] > ax - 2 * D).all(), f"{name} 应全在扇顶右边（开口朝 +X）"
        span = ang[vis & (r > 0.4 * r.max())]
        assert 112 <= span.max() - span.min() <= 128, f"{name} 张角 {span.max() - span.min():.0f}° 应约 120°"
        assert abs(span.max() + span.min()) < 6, f"{name} 应以 +X 为中线上下对称"
        rad = meta[name]["radius_px"]
        assert meta[name]["angle_deg"] == 120
        ks = range(int(4 * D), int(r.max()) - 1)  # 扇顶附近像素太少，跳过
        prof = np.zeros(int(r.max()))
        for k in ks:
            sel = (np.abs(ang) < 40) & (r >= k) & (r < k + 1)
            prof[k] = a[sel].mean() if sel.any() else 0.0
        peak = int(np.argmax(prof))
        assert abs(peak - rad) <= 5 * D, f"{name} 最亮处的半径 {peak} 与 radius_px {rad} 不符"
        assert prof[peak] > 1.5 * prof[int(rad * 0.4)], f"{name} 外沿应比扇面里面亮"
        assert a[(r > rad + 4 * D)].max() < 0.05, f"{name} 半径外应透明"


def test_charge_line():
    """冲锋预警：车道锚点在起点、沿 X 一致（只在起点淡入；中线一行完全一致、两侧的边起伏不大），最右一列不透明、
    宽度与 meta 的 width_px 相符；箭头的箭尖在右边，底边那一列与车道最右一列接得上。"""
    meta = meta_files()
    a = rgba("charge_line.png")[..., 3].astype(np.float64) / 255.0
    h, w = a.shape
    e = meta["charge_line.png"]
    assert e["stretch"] == "x" and e["points"] == "+x"
    x0 = int(round(8 * D))
    mid = a[h // 2 - 1 : h // 2 + 1, x0:]
    assert (mid.max(1) - mid.min(1)).max() <= 2.5 / 255, "车道中线沿 X 应完全一致（拉伸不走样）"
    body = a[:, x0:]
    assert (body.max(1) - body.min(1)).max() < 0.25, "车道沿 X 的起伏太大"
    assert a[:, 0].max() == 0 and a[h // 2, 1] < 0.5 * a[h // 2, x0] and (np.diff(a[h // 2, :x0]) >= -1.5 / 255).all(), "起点应淡入"
    assert np.abs(a[:, -1] - a[:, -int(4 * D)]).max() < 0.03 and a[:, -1].max() > 0.6, "最右一列应与车道一致、不透明（接箭头）"
    rows = np.nonzero(a[:, w // 2] > 0.2)[0]
    width = rows.max() - rows.min() + 1
    assert abs(width - e["width_px"]) <= 2 * D, f"车道宽 {width} 像素与 width_px {e['width_px']} 不符"
    assert a[h // 2, w // 2] < a[rows.min() + int(1 * D), w // 2], "两侧的边应比中间亮"
    hd = rgba("charge_line_head.png")[..., 3].astype(np.float64) / 255.0
    hh, hw_ = hd.shape
    ax = int(round(EXPECTED["charge_line_head.png"][1][0] * hw_))
    xs = np.arange(hw_)
    assert (hd.sum(0) * xs).sum() / hd.sum() > ax, "箭头应朝 +X"
    cols = np.nonzero((hd > 0.2).any(0))[0]
    assert abs((cols.max() - ax) - meta["charge_line_head.png"]["head_len_px"]) <= 2 * D, "head_len_px 与箭尖位置不符"
    off = (hh - h) // 2
    # 只比车道宽度以内：箭头底边本来就比车道宽（两侧的箭翼），翼不算接缝
    band = a[:, -1] > 0.05
    seam = np.abs(hd[off : off + h, ax][band] - a[:, -1][band]).mean()
    assert seam < 0.06, f"箭头底边与车道末端接不上（车道宽度内平均差 {seam:.3f}）"
    wing = hd[:, ax][(np.arange(hh) < off + np.argmax(band)) | (np.arange(hh) >= off + h - np.argmax(band[::-1]))]
    assert wing.max() > 0.15, "箭头底边应比车道宽（两侧有箭翼）"


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
    assert cy[0] < cy[2] - 1.0 * D, f"翅膀上扬帧的重心应比下扑帧高：{cy}"


def test_ring_profile():
    a = rgba("ring.png")[..., 3].astype(np.float64)
    n = a.shape[0]
    yy, xx = np.mgrid[0:n, 0:n] + 0.5
    r = np.hypot(xx - n / 2, yy - n / 2)
    prof = np.array([a[(r >= k) & (r < k + 1)].mean() for k in range(n // 2)])
    peak = int(prof.argmax())
    want = meta_files()["ring.png"]["radius_px"]
    k12, k14 = int(12 * D), int(14 * D)
    assert abs(peak - want) <= 4 * D, f"环的最亮半径 {peak} 与 meta radius_px {want} 不符（2 倍容差 {4 * D}）"
    assert prof[:k12].max() == 0, "环中心应完全透明"
    assert prof[peak - k14] < prof[peak] * 0.5, "环内侧应淡出"
    assert prof[peak - k14] > 0, "环内侧应有柔和的余波"


def test_seal_mark_glyph_is_hollow():
    """白文：字口透明。印面中心竖笔处 alpha 应很低，旁边的朱砂地 alpha 高。"""
    a = rgba("seal_mark.png")[..., 3]
    c = a.shape[0] // 2

    def k(v):
        return int(round(v * D))

    assert a[c - k(4) : c + k(4), c - k(1) : c + k(2)].mean() < 40, "印文中竖处应透出地面"
    assert a[c - k(12) : c - k(6), c - k(9) : c - k(5)].mean() > 150, "字旁的朱砂地应不透明"


# ---------------------------------------------------------------- 确定性、体积、写盘范围


def test_deterministic():
    again = W.build()
    for key, (img, _, _) in again.items():
        disk = np.asarray(Image.open(W.WEAPON_DIR / f"{key}.png").convert("RGBA"))
        assert (np.asarray(img) == disk).all(), f"{key} 两次生成结果不一致"


def test_total_size():
    total = sum(p.stat().st_size for p in W.WEAPON_DIR.glob("*.png"))
    assert total < 300 * 1024 * D * D, f"贴图总体积 {total / 1024:.1f} KB 超过 {300 * D * D:.0f} KB"


def test_writes_only_own_outputs():
    allowed = (W.WEAPON_DIR.resolve(), W.REVIEW_DIR.resolve())
    assert WRITTEN, "没有记录到写盘"
    for p in WRITTEN:
        assert any(p.is_relative_to(d) for d in allowed), f"写到了不该写的地方：{p}"
    for p in WRITTEN:
        if p.is_relative_to(W.REVIEW_DIR.resolve()):
            assert p.name.startswith("weapons_"), f"检查图名字应以 weapons_ 开头：{p.name}"
    assert snapshot_other_outputs() == SNAPSHOT, "vfx/ 或 ground/ 的产物被改动了"


def test_meta_px_per_unit():
    meta = json.loads((W.WEAPON_DIR / "meta.json").read_text(encoding="utf-8"))
    assert meta["px_per_unit"] == S.PX_PER_UNIT, f"px_per_unit {meta['px_per_unit']} != {S.PX_PER_UNIT}"
    for name, e in meta["files"].items():
        if "radius_px" in e:
            assert isinstance(e["radius_px"], int), f"{name} radius_px 应为整数像素"


def test_pre_m25_unchanged():
    """快照里的 weapons/ 产物（M2.5 之前 + M2.5 第一批）逐字节不变，meta 已有条目与顶层字段不变（post/golden_m25.json，两种密度）。"""
    testkit.check_snapshot(V.ASSETS, ("weapons",), D)
    files = list(meta_files())
    assert files[-4:] == ["sector.png", "sector_fill.png", "charge_line.png", "charge_line_head.png"], "M2.5 的条目应追加在最后"


def test_density_1x_unchanged():
    """1 倍：已有贴图与密度改造前逐字节相同；meta 已有条目不变（新条目只追加）。"""
    if D != 1:
        return
    testkit.check_golden(V.ASSETS, ("weapons",))


def test_density_2x_same_art():
    """2 倍：缩回 1 倍后与 1 倍贴图基本一致。需要 1 倍产物在盘上（两种密度一起测时先测 1 倍）。"""
    if D != 2:
        return
    res = testkit.density_consistency(W.WEAPON_DIR, V.OUT / "assets" / "weapons", list(EXPECTED))
    assert len(res) == len(EXPECTED), "1 倍产物不全，先跑一遍 1 倍"


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
