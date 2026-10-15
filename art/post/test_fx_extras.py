#!/usr/bin/env python3
"""fx_extras.py 的自检：纯 assert，不依赖 pytest。只有桌面版（2 倍），与 LANTERN_ART_DENSITY 无关。

每次先重新生成一遍（约 20 秒），记下写了哪些文件，核对别的产物没被动过；再在内存里画一遍，与盘上逐字节比对（确定性）。
最后用 pack_atlas 把新目录和现有的 ui / vfx 目录打进临时目录，确认帧名、不裁边、染色标记都对。

用法（在仓库根目录下）：
  art/.venv/bin/python art/post/test_fx_extras.py
"""

from __future__ import annotations

import hashlib
import io
import json
import sys
import tempfile
import traceback
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import fx_extras as F  # noqa: E402
import pack_atlas  # noqa: E402

V = F.V
A2 = F.OUT / "assets@2x"
ROLLER = F.SCREENS / "scroll_roller.png"
ROLLER_JSON = F.SCREENS / "scroll_roller.json"

# 与任务约定一致，独立写一份
WASH_SIZES = {"ink_wash.png": (1024, 320), "ink_wash_1.png": (768, 256)}
LEAF_FILES = [f"bamboo_leaf_{i}.png" for i in range(4)]
LEAF_SIZE = (32, 12)
ROLL_SIZE = (60, 832)

WRITTEN: list[Path] = []
SNAPSHOT: dict[str, str] = {}


def other_outputs() -> dict[str, str]:
    """别的脚本的产物（ui、vfx、weapons、portrait、lamp_icons、skin、卷轴画）：md5。"""
    out = {}
    for d in [A2 / n for n in ("ui", "vfx", "weapons", "portrait", "lamp_icons")] + [F.OUT / "skin"]:
        for p in sorted(d.glob("*")):
            if p.is_file():
                out[str(p)] = hashlib.md5(p.read_bytes()).hexdigest()
    for p in sorted(F.SCREENS.glob("*.png")):
        if p.name != ROLLER.name:
            out[str(p)] = hashlib.md5(p.read_bytes()).hexdigest()
    return out


def regenerate() -> None:
    SNAPSHOT.update(other_outputs())
    orig_save, orig_json = V.save_png, F.write_json

    def save(img, path):
        WRITTEN.append(Path(path).resolve())
        orig_save(img, path)

    def wjson(path, obj):
        WRITTEN.append(Path(path).resolve())
        orig_json(path, obj)

    V.save_png, F.write_json = save, wjson
    try:
        F.main()
    finally:
        V.save_png, F.write_json = orig_save, orig_json


def rgba(path: Path) -> np.ndarray:
    return np.asarray(Image.open(path).convert("RGBA"))


def meta(folder: Path) -> dict:
    return json.loads((folder / "meta.json").read_text(encoding="utf-8"))


# ============================================================== 清单与尺寸


def test_wash_meta_and_sizes():
    m = meta(F.WASH_DIR)
    assert m["name"] == "ui", "ui_wash 的 meta name 应为 ui（打包后帧名 ui/ink_wash）"
    assert m["px_per_unit"] == 4, "密度要与 ui 图集一致（4）"
    assert list(m["files"]) == list(WASH_SIZES), f"清单 {list(m['files'])}"
    for name, size in WASH_SIZES.items():
        e = m["files"][name]
        img = Image.open(F.WASH_DIR / name)
        assert img.mode == "RGBA" and img.size == size, f"{name}: {img.mode} {img.size} != {size}"
        assert e["size"] == list(size) and e["anchor"] == [0.5, 0.5], f"{name}: meta 尺寸 / 锚点不对"
        assert e["tint"] is True and e["blend"] == "normal", f"{name}: 应为 tint=true、blend=normal"


def test_leaf_meta_and_sizes():
    m = meta(F.LEAF_DIR)
    assert m["name"] == "vfx", "vfx_leaves 的 meta name 应为 vfx（帧名 vfx/bamboo_leaf_N）"
    assert m["px_per_unit"] == 4, "密度要与 vfx 图集一致（4）"
    assert list(m["files"]) == LEAF_FILES, f"清单 {list(m['files'])}"
    for name in LEAF_FILES:
        e = m["files"][name]
        img = Image.open(F.LEAF_DIR / name)
        assert img.mode == "RGBA" and img.size == LEAF_SIZE, f"{name}: {img.mode} {img.size}"
        assert e["size"] == list(LEAF_SIZE) and e["anchor"] == [0.5, 0.5], f"{name}: meta 尺寸 / 锚点不对"
        assert e["tint"] is True and e["blend"] == "normal" and e["points"] == "+x", f"{name}: 标记不对"
    # vfx 图集里不能重名
    assert not set(m["files"]) & set(meta(A2 / "vfx")["files"]) and not set(m["files"]) & set(meta(A2 / "weapons")["files"])


def test_white_rgb_tintable():
    """可染色的贴图：RGB 恒为白，形状只在 alpha 里（直通 alpha，透明处也是白，过滤不出黑边）。"""
    for p in [F.WASH_DIR / n for n in WASH_SIZES] + [F.LEAF_DIR / n for n in LEAF_FILES]:
        a = rgba(p)
        assert (a[..., :3] == 255).all(), f"{p.name}: 有不是白色的像素"
        assert a[..., 3].max() >= 230, f"{p.name}: alpha 最大只有 {a[..., 3].max()}（浓淡留给游戏调，贴图本身应能到满）"


# ============================================================== 淡墨


def test_wash_edges_transparent():
    for name in WASH_SIZES:
        al = rgba(F.WASH_DIR / name)[..., 3].astype(int)
        h, w = al.shape
        for m, lim in ((4, 0), (16, 12)):
            band = np.ones_like(al, bool)
            band[m : h - m, m : w - m] = False
            assert al[band].max() <= lim, f"{name}: 离边 {m} 像素内 alpha 最大 {al[band].max()} > {lim}"
        ys, xs = np.nonzero(al > 8)
        assert xs.min() >= 20 and xs.max() < w - 20 and ys.min() >= 16 and ys.max() < h - 16, f"{name}: 笔触离边太近"


def test_wash_is_a_stroke():
    """是一笔字，不是糊开的方块：四角空、上下沿起伏、中段实（衬字）、收笔飞白成丝、起笔比收笔浓。"""
    for name in WASH_SIZES:
        al = rgba(F.WASH_DIR / name)[..., 3].astype(np.float64) / 255.0
        h = al.shape[0]
        ys, xs = np.nonzero(al > 0.5)
        x0, x1, y0, y1 = xs.min(), xs.max(), ys.min(), ys.max()
        bw, bh = x1 - x0, y1 - y0
        k = int(0.18 * bh)
        corners = [al[y0 : y0 + k, x0 : x0 + k], al[y0 : y0 + k, x1 - k : x1], al[y1 - k : y1, x0 : x0 + k], al[y1 - k : y1, x1 - k : x1]]
        cm = [round(float(c.mean()), 2) for c in corners]
        assert np.mean(cm) < 0.25 and max(cm) < 0.6, f"{name}: 外框四角有墨（像方块）{cm}"
        cols = range(x0 + bw // 10, x1 - bw // 4)
        top = np.array([np.nonzero(al[:, x] > 0.5)[0].min() for x in cols])
        bot = np.array([np.nonzero(al[:, x] > 0.5)[0].max() for x in cols])
        assert np.ptp(top) >= 12 and np.ptp(bot) >= 12, f"{name}: 上下沿太直（起伏 {np.ptp(top)}、{np.ptp(bot)} 像素）"
        # 中段（字所在）：实
        cy = int(np.median((top + bot) / 2))
        mid = al[cy - h // 9 : cy + h // 9, x0 + int(0.3 * bw) : x0 + int(0.62 * bw)]
        assert mid.mean() > 0.7 and (mid < 0.35).mean() < 0.05, f"{name}: 中段不够实（平均 {mid.mean():.2f}，空洞 {(mid < 0.35).mean():.1%}）"
        # 收笔：沿竖线穿过很多条丝（飞白）
        tail = al[:, x0 + int(0.84 * bw) : x0 + int(0.95 * bw)]
        crossings = np.abs(np.diff((tail > 0.4).astype(int), axis=0)).sum(0).mean()
        assert crossings >= 8, f"{name}: 收笔的飞白丝太少（每列平均 {crossings:.1f} 次明暗交替）"
        head = al[:, x0 : x0 + int(0.25 * bw)].sum()
        tailm = al[:, x0 + int(0.75 * bw) : x1].sum()
        assert head > 1.3 * tailm, f"{name}: 起笔应比收笔浓（{head:.0f} vs {tailm:.0f}）"


# ============================================================== 竹叶


def test_leaf_edges_and_centre():
    for name in LEAF_FILES:
        al = rgba(F.LEAF_DIR / name)[..., 3]
        assert al[0].max() == al[-1].max() == al[:, 0].max() == al[:, -1].max() == 0, f"{name}: 边上一圈要全透明"
        ys, xs = np.nonzero(al > 20)
        cx, cy = (xs.min() + xs.max() + 1) / 2, (ys.min() + ys.max() + 1) / 2
        assert abs(cx - 16) <= 2.5 and abs(cy - 6) <= 1.5, f"{name}: 叶片没居中（外框中心 {cx}, {cy}）"


def test_leaf_shapes():
    """披针形、叶尖朝 +X（最宽处在左半）、中脉在 alpha 里浅一线；第 3 片是撕断的（短）；四片各不相同。"""
    als = [rgba(F.LEAF_DIR / n)[..., 3].astype(int) for n in LEAF_FILES]
    for i, al in enumerate(als):
        hgt = (al > 128).sum(0)
        xs = np.nonzero(hgt)[0]
        ext = xs.max() - xs.min() + 1
        if i < 3:
            assert ext >= 22, f"bamboo_leaf_{i}: 叶长只有 {ext} 像素"
            assert ext / hgt.max() >= 3.5, f"bamboo_leaf_{i}: 不够细长（{ext}/{hgt.max()}）"
            widest = xs.min() + int(np.argmax(hgt[xs.min() :]))
            assert widest < 16, f"bamboo_leaf_{i}: 最宽处在 x={widest}，叶尖应朝 +X（最宽处靠左）"
            right = hgt[xs.max() - ext // 5 : xs.max() + 1].mean()
            assert right < 0.5 * hgt.max(), f"bamboo_leaf_{i}: 叶尖不尖"
        # 中脉：叶片中段的竖剖面里，中间有一道比两边浅的凹
        dips = []
        for x in range(xs.min() + ext // 4, xs.min() + ext // 2):
            col = al[:, x]
            if (col > 128).sum() < 4:
                continue
            ys = np.nonzero(col > 100)[0]
            inner = col[ys.min() + 1 : ys.max()]
            j = int(np.argmin(inner))
            dips.append(min(inner[: j + 1].max(), inner[j:].max()) - inner[j])
        assert dips and np.median(dips) >= 20, f"bamboo_leaf_{i}: 看不出中脉（凹深 {dips}）"
    torn = (als[3] > 128).sum(0)
    whole = np.mean([np.ptp(np.nonzero((a > 128).sum(0))[0]) for a in als[:3]])
    assert np.ptp(np.nonzero(torn)[0]) < 0.75 * whole, "bamboo_leaf_3 应是撕断的半片（比整叶短）"
    for i in range(4):
        for j in range(i + 1, 4):
            assert np.abs(als[i] - als[j]).mean() > 10, f"bamboo_leaf_{i} 和 _{j} 太像"


# ============================================================== 轴


def test_roller():
    info = json.loads(ROLLER_JSON.read_text(encoding="utf-8"))
    img = Image.open(ROLLER)
    assert img.mode == "RGBA" and img.size == ROLL_SIZE, f"scroll_roller: {img.mode} {img.size}"
    assert info["size"] == list(ROLL_SIZE) and info["paper_height"] == 800 and info["scroll_size"] == [2400, 800]
    a = np.asarray(img).astype(int)
    al = a[..., 3]
    ext, pe, cx, r, kr = info["paper_top_y"], info["paper_edge_x"], info["rod_center_x"], info["rod_radius"], info["knob_radius"]
    assert ext + 800 + ext == ROLL_SIZE[1], "轴头上下伸出的像素应相同，且整张高 = 800 + 2 × paper_top_y"
    # alpha 外框：上下到头（轴头），左边从 0 起（阴影），右边是轴头的外缘
    ys, xs = np.nonzero(al > 8)
    assert ys.min() <= 1 and ys.max() >= ROLL_SIZE[1] - 2, f"轴头没伸到上下边（{ys.min()}..{ys.max()}）"
    assert abs((xs.max() + 1) - (cx + kr)) <= 1.5, f"alpha 外框右边 {xs.max()} 不是轴头外缘"
    xs0 = np.nonzero(al > 0)[1]
    assert xs0.min() <= 2 and xs0.max() < ROLL_SIZE[0] - 1, f"alpha 外框 x {xs0.min()}..{xs0.max()}：左边从阴影起，右边留透明"
    # 纸的那一段：paper_edge_x 往右到轴杆都不透明，左边是半透明的阴影
    for y in (ext, ext + 5, ext + 400, ext + 799):
        assert (al[y, pe : int(cx + r) - 1] == 255).all(), f"y={y}: 纸边到轴杆之间应不透明"
        assert al[y, : pe - 2].max() < 80, f"y={y}: paper_edge_x 左边应是淡影（{al[y, :pe - 2].max()}）"
    # 纸不伸出卷轴上下沿：轴头那几行里，纸边那一列是透明的
    assert al[: ext - 1, pe + 2].max() == 0 and al[ROLL_SIZE[1] - ext + 1 :, pe + 2].max() == 0, "纸伸出了卷轴上下沿"
    # 轴头比杆宽
    w_rod = (al[ext + 400] > 200).sum() - (al[ext + 400, : int(cx - r) - 1] > 200).sum()
    for y in (ext // 2, ROLL_SIZE[1] - 1 - ext // 2):
        w_knob = (al[y] > 200).sum()
        assert w_knob >= w_rod + 8, f"y={y}: 轴头宽 {w_knob} 不比杆 {w_rod} 宽"
    # 颜色：杆是深色漆，纸比杆亮
    lum = a[..., :3] @ np.array([0.299, 0.587, 0.114]) / 255.0
    rod = lum[ext + 50 : ext + 750, int(cx - r / 2) : int(cx + r / 2)]
    paper = lum[ext + 50 : ext + 750, pe + 1 : pe + 5]
    assert rod.mean() < 0.3, f"轴杆不够深（亮度 {rod.mean():.2f}）"
    assert paper.mean() > rod.mean() + 0.3, "卷起的纸应比轴杆亮得多"


# ============================================================== 确定性、写盘范围、打包


def test_deterministic():
    r = F.build()
    files = {**{F.WASH_DIR / f"{k}.png": v for k, v in r["washes"].items()},
             **{F.LEAF_DIR / f"bamboo_leaf_{i}.png": v for i, v in enumerate(r["leaves"])}, ROLLER: r["roller"]}
    for path, img in files.items():
        buf = io.BytesIO()
        img.save(buf, "PNG", optimize=True)
        assert buf.getvalue() == path.read_bytes(), f"{path.name}: 再画一遍不逐字节相同"


def test_writes_only_own_outputs():
    own = {(F.WASH_DIR / n).resolve() for n in [*WASH_SIZES, "meta.json"]}
    own |= {(F.LEAF_DIR / n).resolve() for n in [*LEAF_FILES, "meta.json"]}
    own |= {ROLLER.resolve(), ROLLER_JSON.resolve(), (F.REVIEW / "fx_extras_review.png").resolve()}
    assert set(WRITTEN) == own, f"写盘的文件不对：多了 {set(WRITTEN) - own}，少了 {own - set(WRITTEN)}"
    now = other_outputs()
    changed = [k for k in SNAPSHOT if now.get(k) != SNAPSHOT[k]]
    assert not changed, f"别的产物被改动了：{changed}"


def test_sizes_budget():
    total = sum(p.stat().st_size for p in [*F.WASH_DIR.glob("*.png"), *F.LEAF_DIR.glob("*.png"), ROLLER])
    assert total < 600 * 1024, f"总体积 {total / 1024:.0f} KB"


def test_packs_into_atlases():
    """按 README 的打包命令把新目录加进 ui（--no-trim）和 vfx 图集（打到临时目录，不动 assets/）。"""
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        pack_atlas.build_atlas("ui", [A2 / "ui", A2 / "portrait", A2 / "lamp_icons", F.WASH_DIR], out, trim_frames=False)
        pack_atlas.build_atlas("vfx", [A2 / "vfx", A2 / "weapons", F.LEAF_DIR], out)
        frames, info = {}, {}
        for js in sorted(out.glob("*.json")):
            d = json.loads(js.read_text(encoding="utf-8"))
            frames.update(d["frames"])
            info.update(d["meta"]["lantern"]["frames"])
        for name, (w, h) in [("ui/ink_wash", (1024, 320)), ("ui/ink_wash_1", (768, 256))]:
            f = frames[name]
            assert (f["frame"]["w"], f["frame"]["h"]) == (w, h) and not f["trimmed"], f"{name}: 应不裁边"
            assert info[name]["tint"] is True and info[name]["blend"] == "normal", f"{name}: 染色标记丢了"
        for i in range(4):
            name = f"vfx/bamboo_leaf_{i}"
            f = frames[name]
            assert f["sourceSize"] == {"w": 32, "h": 12} and f["anchor"] == {"x": 0.5, "y": 0.5}, f"{name}: 尺寸 / 锚点"
            assert info[name]["tint"] is True and info[name]["blend"] == "normal", f"{name}: 染色标记丢了"
        assert "ui/icon_lamp" in frames and "vfx/light" in frames and "weapons/sword" in frames, "原有的帧丢了"


def test_review_image():
    p = F.REVIEW / "fx_extras_review.png"
    assert p.exists() and p.stat().st_size > 200_000, "审图缺失或为空"


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
