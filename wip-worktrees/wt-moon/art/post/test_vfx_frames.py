#!/usr/bin/env python3
"""vfx_frames.py（逐帧特效图，第一到第三批）的自检：纯 assert，不依赖 pytest。只有 2 倍（桌面版）。

产物缺失或比脚本旧时先重新生成（约 7 分钟）。--regen 强制重新生成，并核对只写了 art/out/assets@2x/vfx_frames/
和 review@2x/vfx_frames_*，别的产物（assets/atlas、art/out/assets@2x 的其他目录）一个字节都没动。
--quick 跳过确定性检查（另画一遍逐像素比对，约 7 分钟）。

用法（在仓库根目录下）：
  art/.venv/bin/python art/post/test_vfx_frames.py
  art/.venv/bin/python art/post/test_vfx_frames.py --regen
  art/.venv/bin/python art/post/test_vfx_frames.py --quick
"""

from __future__ import annotations

import json
import math
import os
import sys
import traceback
from functools import lru_cache
from pathlib import Path

os.environ["LANTERN_ART_DENSITY"] = "2"

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import vfx_frames as F  # noqa: E402

V = F.V
ATLAS = V.ART.parent / "assets" / "atlas"

# 质感会话的清单：帧数、画布、混合、可染。slash 的画布按刀光半径改大了（清单写 256×128，见 vfx_frames.py 开头）。
SPEC = {
    "hit_metal": (5, (128, 128), "add", True),
    "hit_wood": (5, (128, 128), "add", True),
    "hit_water": (5, (128, 128), "add", True),
    "hit_fire": (5, (128, 128), "add", True),
    "hit_earth": (5, (128, 128), "add", True),
    "crit": (4, (192, 192), "add", False),
    "slash": (6, (256, 448), "add", True),
    "kill_ink": (6, (192, 192), "normal", False),
    "shockwave": (6, (512, 320), "add", True),
}
# 第二批（FEEL.md 第 12 节）。火爆按 1080p 下约一比一放大到 384²（清单写 256²，见 vfx_frames.py）。
SPEC2 = {
    "fire_burst": (7, (384, 384), "add", False),
    "fire_burst_smoke": (2, (384, 384), "normal", False),
    "ice_shatter": (6, (192, 192), "add", True),
    "feather": (4, (32, 16), "normal", True),
    "evolve": (8, (512, 512), "add", False),
    "evolve_pillar": (6, (128, 512), "add", False),
}
# 第三批：十种反应（FEEL.md 第 12 节），都自带颜色、不染。有范围的按 1080p 下约一比一改了画布（清单写 256² / 256×192 / 384×240）。
SPEC3 = {
    "react_liaoyuan": (6, (384, 384), "add", False),
    "react_rongyan": (6, (384, 240), "add", False),
    "react_zhubing": (5, (256, 256), "add", False),
    "react_ningshuang": (6, (384, 240), "add", False),
    "react_zisheng": (6, (320, 288), "normal", False),
    "react_zhengteng": (7, (448, 448), "normal", False),
    "react_rongjin": (6, (128, 128), "add", False),
    "react_duanmu": (5, (256, 256), "add", False),
    "react_lietu": (6, (352, 320), "normal", False),
    "react_yuni": (6, (416, 272), "normal", False),
}
# 反应范围（BALANCE 7.2，世界单位）：radius_px 要约等于 范围 × 2.57（1080p 下一比一）
REACT_RANGE = {"react_liaoyuan": 60, "react_rongyan": 50, "react_ningshuang": 50, "react_zisheng": 50, "react_zhengteng": 70,
               "react_lietu": 60, "react_yuni": 70}
REACT_COLOR = {  # 主色（清单）；断木是金 + 木，另查
    "react_liaoyuan": "#FF7A2A", "react_rongyan": "#FF5A2A", "react_zhubing": "#F2D98A", "react_ningshuang": "#CDEBFF",
    "react_zisheng": "#6FD6A0", "react_zhengteng": "#E8EEF2", "react_rongjin": "#FFB347", "react_lietu": "#8B6A47", "react_yuni": "#5B4A3A",
}
GROUND3 = {"react_rongyan", "react_ningshuang", "react_yuni"}  # 已压扁的
LOOPS = {"react_rongjin"}  # 循环的
HOLD3 = {"react_rongyan", "react_ningshuang", "react_zisheng", "react_yuni"}  # 末帧可以留着
ALL = {**SPEC, **SPEC2, **SPEC3}
VARIANTS = {"feather"}  # 几种挑着用的粒子，不是动画
PEAK8 = round(F.PEAK * 255)

WRITTEN: list[Path] = []
SNAPSHOT: dict[str, tuple[int, int]] = {}


# ---------------------------------------------------------------- 准备


def outputs() -> list[Path]:
    out = [F.OUT / "meta.json"]
    for name, (n, *_rest) in ALL.items():
        out += [F.OUT / f"{name}_{i}.png" for i in range(n)]
    for key in F.BATCHES:
        out += [F.REVIEW / f"vfx_frames_{key}.png", F.REVIEW / f"vfx_frames_{key}_ingame.png"]
    return out + [F.REVIEW / "vfx_frames_b3_ingame2.png"]


def protected() -> dict[str, tuple[int, int]]:
    """别的产物（只读）：修改时间和大小。"""
    snap = {}
    folders = [ATLAS] + [p for p in (V.OUT / "assets@2x").iterdir() if p.is_dir() and p.name != F.OUT.name]
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
        F.main()
    finally:
        V.save_png = orig_save
        Path.write_text = orig_write  # type: ignore[method-assign]


def ensure_outputs(force: bool) -> None:
    newest = max((HERE / n).stat().st_mtime for n in ("vfx_frames.py", "vfx_frames_review.py", "vfx_textures.py", "weapon_textures.py"))
    stale = [p for p in outputs() if not p.exists() or p.stat().st_mtime < newest]
    if force or stale:
        print("重新生成逐帧特效……")
        regenerate()


@lru_cache(maxsize=1)
def meta() -> dict:
    return json.loads((F.OUT / "meta.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=None)
def rgba(name: str, i: int) -> np.ndarray:
    return np.asarray(Image.open(F.OUT / f"{name}_{i}.png").convert("RGBA"))


def alpha(name: str, i: int) -> np.ndarray:
    return rgba(name, i)[..., 3].astype(np.float64)


def frames_of(name: str) -> list[int]:
    return list(range(ALL[name][0]))


def additive() -> list[str]:
    return [n for n, s in ALL.items() if s[2] == "add"]


def animations() -> list[str]:
    return [n for n in ALL if n not in VARIANTS]


def centroid(a: np.ndarray) -> tuple[float, float]:
    h, w = a.shape
    tot = a.sum()
    return float((a.sum(0) * (np.arange(w) + 0.5)).sum() / tot), float((a.sum(1) * (np.arange(h) + 0.5)).sum() / tot)


def bbox(a: np.ndarray) -> tuple[int, int, int, int]:
    ys, xs = np.nonzero(a)
    return int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())


# ---------------------------------------------------------------- 清单与格式


def test_spec_matches_list():
    """生成清单和质感会话的清单一致：组名、帧数、画布、混合、可染（三批分开对）。"""
    for batch, spec in ((F.BATCH1, SPEC), (F.BATCH2, SPEC2), (F.BATCH3, SPEC3)):
        assert set(batch) == set(spec), f"组名不一致：{sorted(set(batch) ^ set(spec))}"
        for name, (n, size, blend, tint) in spec.items():
            _, size_, _, blend_, tint_, _, _ = batch[name]
            assert (tuple(size_), blend_, tint_) == (size, blend, tint), f"{name}: {size_} {blend_} {tint_}"
            assert len([k for k in meta()["files"] if k.rsplit("_", 1)[0] == name]) == n, f"{name} 帧数不是 {n}"
    assert set(F.BATCHES) == {"b1", "b2", "b3"}


def test_meta_fields():
    """meta.json：name = vfx、4 像素 / 世界单位；每帧有尺寸、锚点、混合、可染、anim/frame/frames、fps 24、不循环（熔金印记循环、10 帧/秒）；
    帧号一位数、从 0 连续。几种挑着用的粒子（羽毛）没有 anim，写 variant / variants。火爆的墨烟写明跟着火爆的第几帧播、同缩放。
    反应：有范围的写 radius_px（≈ 范围 × 2.57，1080p 下一比一），地面的写 flat，能留着的写 hold_last。"""
    m = meta()
    assert m["name"] == "vfx" and m["px_per_unit"] == 4 and m["generator"] == F.GENERATOR
    for name, (n, size, blend, tint) in ALL.items():
        anchors = set()
        for i in range(n):
            info = m["files"][f"{name}_{i}.png"]
            assert info["size"] == list(size) and info["blend"] == blend and info["tint"] is tint, f"{name}_{i}: {info}"
            if name in VARIANTS:
                assert info["variant"] == i and info["variants"] == n and "anim" not in info, f"{name}_{i} 的 variant 不对"
            else:
                assert info["anim"] == name and info["frame"] == i and info["frames"] == n, f"{name}_{i} 的 anim/frame/frames 不对"
                fps, loop = (F.RJ_FPS, True) if name in LOOPS else (24, False)
                assert info["fps"] == fps and info["loop"] is loop, f"{name}_{i}: fps {info['fps']} loop {info['loop']}"
            assert info["kind"] == "fx", f"{name}_{i} 的 kind"
            assert 0 <= info["anchor"][0] <= 1 and 0 <= info["anchor"][1] <= 1 and info["note"], f"{name}_{i} 锚点或说明不对"
            anchors.add(tuple(info["anchor"]))
        assert len(anchors) == 1, f"{name} 各帧锚点不一样：{anchors}"
        assert n <= 10, f"{name} 帧号要一位数"
    fire, smoke = m["files"]["fire_burst_0.png"], m["files"]["fire_burst_smoke_0.png"]
    assert fire["radius_px"] == F.FIRE_R and smoke["radius_px"] == F.FIRE_R and smoke["anchor"] == fire["anchor"], (fire, smoke)
    assert smoke["follows"] == "fire_burst" and smoke["start_frame"] == 5 and smoke["hold_last"] is True, smoke
    assert m["files"]["ice_shatter_0.png"]["tint_hint"] == "#CDEBFF" and m["files"]["feather_0.png"]["points"] == "+x"
    for name, (n, *_r) in SPEC3.items():
        for i in range(n):
            info = m["files"][f"{name}_{i}.png"]
            if name in REACT_RANGE:
                k = info["radius_px"] / (REACT_RANGE[name] * 2.571)
                assert 0.85 <= k <= 1.2, f"{name}_{i}: radius_px {info['radius_px']} 和范围 {REACT_RANGE[name]} 在 1080p 下不是约一比一（{k:.2f}）"
            assert (info.get("flat") == F.FLAT) is (name in GROUND3), f"{name}_{i} 的 flat"
            assert (info.get("hold_last") is True) is (name in HOLD3), f"{name}_{i} 的 hold_last"
    assert m["files"]["react_rongjin_0.png"]["radius_px"] == F.RJ_R
    pngs = {p.name for p in F.OUT.glob("*.png")}
    assert pngs == set(m["files"]), f"目录里的 PNG 和 meta 对不上：{sorted(pngs ^ set(m['files']))[:6]}"


def test_png_format():
    """PNG 是 RGBA，尺寸和 meta 一致；每帧都有内容。"""
    for name, (n, size, *_r) in ALL.items():
        for i in range(n):
            im = Image.open(F.OUT / f"{name}_{i}.png")
            assert im.mode == "RGBA" and im.size == size, f"{name}_{i}: {im.mode} {im.size}"
            assert alpha(name, i).sum() / 255 > 20, f"{name}_{i} 几乎是空的"


def test_colors():
    """可染的帧 RGB 恒为白；暴击是白金 #FFF3D6；墨花、火爆的墨烟是焦墨 #17140F（看得见的像素都是这个颜色）。
    火爆、进化自带暖色（R ≥ G ≥ B）：火爆第 0 帧的芯近白、末帧往红退；进化偏金。"""
    jiao = tuple(round(c * 255) for c in F.JIAO)
    want = {"crit": tuple(round(c * 255) for c in F.CRIT_RGB), "kill_ink": jiao, "fire_burst_smoke": jiao}
    assert want["crit"] == (255, 243, 214) and want["kill_ink"] == (23, 20, 15), want
    warm = {"fire_burst", "evolve", "evolve_pillar"}
    for name, (n, _s, _b, tint) in {**SPEC, **SPEC2}.items():
        for i in range(n):
            px = rgba(name, i)
            vis = px[..., 3] > 0
            rgb = px[..., :3][vis].astype(int)
            if name in warm:
                assert (rgb[:, 0] >= rgb[:, 1]).all() and (rgb[:, 1] >= rgb[:, 2]).all(), f"{name}_{i} 不是暖色"
                continue
            c = (255, 255, 255) if tint else want[name]
            assert (rgb == np.array(c)).all(), f"{name}_{i} 的颜色不是 {c}"

    def mean_rgb(name, i):
        px = rgba(name, i)
        w = px[..., 3].astype(float)
        return (px[..., :3].astype(float) * w[..., None]).sum((0, 1)) / w.sum()

    w, h = SPEC2["fire_burst"][1]
    ax, ay = (np.array(meta()["files"]["fire_burst_0.png"]["anchor"]) * [w, h]).astype(int)
    core = rgba("fire_burst", 0)[ay - 5 : ay + 5, ax - 5 : ax + 5, :3].reshape(-1, 3).mean(0)
    assert core[1] > 210 and core[2] > 160, f"火爆第 0 帧的芯不够白（应接近 #FFF1C2）：{core.round()}"
    late = mean_rgb("fire_burst", 6)
    assert late[0] - late[2] > 120, f"火爆末帧应该退到红：{late.round()}"
    gold = mean_rgb("evolve", 3)
    assert gold[0] - gold[2] > 30 and gold[2] > 120, f"进化应该是淡金：{gold.round()}"


def test_borders_and_clipping():
    """四边一圈全透明；靠边 4 像素里只有很淡的东西（没有被画布边切掉的形状）。羽毛这种小粒子只要求四边一圈全透明。"""
    for name, (n, *_r) in ALL.items():
        for i in range(n):
            a = alpha(name, i)
            assert a[0].max() == a[-1].max() == a[:, 0].max() == a[:, -1].max() == 0, f"{name}_{i} 四边不透明"
            if name in VARIANTS:
                continue
            band = np.concatenate([a[:4].ravel(), a[-4:].ravel(), a[:, :4].ravel(), a[:, -4:].ravel()])
            if name == "evolve_pillar":  # 光柱的根贴着底边，底边那几行不算
                band = np.concatenate([a[:4].ravel(), a[:-8, :4].ravel(), a[:-8, -4:].ravel()])
            assert band.max() <= 16, f"{name}_{i} 靠边还有 alpha {band.max():.0f}，形状被画布切了"


# ---------------------------------------------------------------- 亮度与节奏


def test_peak_alpha():
    """叠加帧最亮处 alpha 约 0.8（不超过、也不差太多）；墨花最浓处接近不透明。"""
    for name in additive():
        peaks = [alpha(name, i).max() for i in frames_of(name)]
        assert max(peaks) <= PEAK8 + 2, f"{name} 最亮 {max(peaks):.0f} 超过 {PEAK8}"
        assert max(peaks) >= PEAK8 - 12, f"{name} 最亮只有 {max(peaks):.0f}，不到 0.8 附近"
    peaks = [alpha("kill_ink", i).max() for i in frames_of("kill_ink")]
    assert min(peaks[1:]) >= 225, f"墨花不够浓：{peaks}"
    smoke = [alpha("fire_burst_smoke", i).max() for i in frames_of("fire_burst_smoke")]
    assert smoke[0] >= 150 and smoke[1] < smoke[0], f"墨烟：第 0 帧要浓、第 1 帧淡一些：{smoke}"


def test_frames_change():
    """相邻两帧不一样（是动画，不是重复帧）；几种挑着用的粒子互相也不一样。"""
    for name in ALL:
        for i in frames_of(name)[1:]:
            d = np.abs(alpha(name, i) - alpha(name, i - 1)).mean()
            assert d > 0.05, f"{name}_{i - 1} 和 {name}_{i} 几乎一样（平均差 {d:.3f}）"


def test_one_shot_fades_out():
    """一次性的叠加特效：最亮的帧在前一半，末帧淡到最多三成五（播完就没，不会“啪”地消失）；墨花末帧留着、和前一帧接近。
    （循环的熔金、末帧留着的反应另查，见 test_reactions_hold_and_fade。）"""
    for name in additive():
        if name in LOOPS or name in HOLD3:
            continue
        sums = [alpha(name, i).sum() for i in frames_of(name)]
        top = int(np.argmax(sums))
        assert top < len(sums) / 2 + 0.5, f"{name} 最亮的是第 {top} 帧，太靠后"
        assert sums[-1] <= 0.35 * max(sums), f"{name} 末帧还有 {sums[-1] / max(sums):.2f}"
        assert sums[-1] > 0, f"{name} 末帧是空的"
    s = [alpha("kill_ink", i).sum() for i in frames_of("kill_ink")]
    assert s[-1] >= 0.75 * max(s), f"墨花末帧太淡：{s[-1] / max(s):.2f}"
    assert np.abs(alpha("kill_ink", 5) - alpha("kill_ink", 4)).mean() < 2.0, "墨花最后两帧应该已经落定"
    assert meta()["files"]["kill_ink_5.png"]["hold_last"] is True


def test_crit_first_frame_biggest():
    """暴击第 0 帧最大最亮，之后一帧比一帧小、淡。"""
    sums = [alpha("crit", i).sum() for i in frames_of("crit")]
    assert all(a > b for a, b in zip(sums, sums[1:])), f"暴击的亮度总量应该逐帧变小：{[round(s / 255) for s in sums]}"
    # 光芒的长度：沿第 0 根光芒（每帧转 4°）从中心往外，alpha 过一半的最远处
    reach = []
    d = np.arange(0, 95, 0.5)
    for i in frames_of("crit"):
        a = alpha("crit", i)
        ang = math.radians(4 * i)
        xs = np.clip((96 + d * math.cos(ang)).astype(int), 0, 191)
        ys = np.clip((96 + d * math.sin(ang)).astype(int), 0, 191)
        on = np.nonzero(a[ys, xs] > 0.5 * PEAK8)[0]
        reach.append(float(d[on.max()]) if len(on) else 0.0)
    assert all(a > b for a, b in zip(reach, reach[1:])), f"四角星的光芒应该逐帧收短：{reach}"
    assert reach[0] >= 60, f"第 0 帧光芒太短：{reach[0]}"


# ---------------------------------------------------------------- 形状与朝向


def test_hits_start_at_center():
    """五种命中第 0 帧是在画布中心炸开的（质心离中心不超过 6 像素），之后不出画布。"""
    for name in ("hit_metal", "hit_wood", "hit_water", "hit_fire", "hit_earth"):
        cx, cy = centroid(alpha(name, 0))
        assert math.hypot(cx - 64, cy - 64) <= 6, f"{name} 第 0 帧的质心在 ({cx:.1f}, {cy:.1f})"


def test_slash_geometry():
    """刀光：锚点在弧心 (16, 224)，扇形朝 +X 张开 120°；外沿半径 = radius_px；笔锋从上扫到下，散的时候尾巴追上笔锋。"""
    info = meta()["files"]["slash_0.png"]
    assert info["points"] == "+x" and info["radius_px"] == F.SLASH_R and info["angle_deg"] == 120, info
    assert info["anchor"] == [16 / 256, 224 / 448], info["anchor"]
    ax, ay = 16.0, 224.0
    R = float(info["radius_px"])
    h, w = SPEC["slash"][1][1], SPEC["slash"][1][0]
    ys, xs = np.mgrid[0:h, 0:w] + 0.5
    r = np.hypot(xs - ax, ys - ay)
    ang = np.degrees(np.arctan2(ys - ay, xs - ax))
    cys = []
    for i in frames_of("slash"):
        a = alpha("slash", i)
        m = a / a.sum()
        # 收笔甩出去的火星可以略过 60°（顺着挥的方向飞），但不能绕到身后
        assert (m * (np.abs(ang) <= 64)).sum() >= 0.98 and np.abs(ang[a > 0]).max() <= 72, f"slash_{i} 有东西跑到 120° 扇形外面"
        cx, cy = centroid(a)
        cys.append(cy)
        assert cx > ax + 0.4 * R, f"slash_{i} 的质心不在 +X 那边"
        if i in (1, 2):
            order = np.argsort(r.ravel())
            cum = np.cumsum(m.ravel()[order])
            r50, r99 = r.ravel()[order][np.searchsorted(cum, 0.5)], r.ravel()[order][np.searchsorted(cum, 0.99)]
            assert R - 40 <= r50 <= R, f"slash_{i} 主体半径 {r50:.0f}，不在外沿 {R:.0f} 里侧"
            assert R - 4 <= r99 <= R + 16, f"slash_{i} 外沿 {r99:.0f}，和 radius_px {R:.0f} 对不上"
    assert all(a < b for a, b in zip(cys, cys[1:])), f"刀光应该从上扫到下：质心 y {[round(c) for c in cys]}"


def test_ground_flattened():
    """贴地的冲击波、墨花按地面透视压扁（高 ÷ 宽 ≈ 0.62），在画布中间。"""
    for i in frames_of("shockwave")[1:5]:
        a = alpha("shockwave", i)
        x0, y0, x1, y1 = bbox(a)
        ratio = (y1 - y0 + 1) / (x1 - x0 + 1)
        assert abs(ratio - F.FLAT) <= 0.03, f"shockwave_{i} 包围盒高宽比 {ratio:.2f}"
        cx, cy = centroid(a)
        assert abs(cx - 256) <= 20 and abs(cy - 160) <= 16, f"shockwave_{i} 偏了：({cx:.0f}, {cy:.0f})"
    widths = [np.ptp(np.nonzero(alpha("shockwave", i).max(0))[0]) for i in frames_of("shockwave")]
    assert all(a < b for a, b in zip(widths, widths[1:])), f"冲击波应该一帧比一帧大：{widths}"
    assert widths[-1] / 2 <= F.SHOCK_R + 20, "冲击波末帧比 radius_px 大太多"
    for i in frames_of("kill_ink")[2:]:
        a = alpha("kill_ink", i)
        cx, cy = centroid(a)
        vx = (a.sum(0) * (np.arange(a.shape[1]) + 0.5 - cx) ** 2).sum()
        vy = (a.sum(1) * (np.arange(a.shape[0]) + 0.5 - cy) ** 2).sum()
        assert 0.45 <= math.sqrt(vy / vx) <= 0.72, f"kill_ink_{i} 没压扁：{math.sqrt(vy / vx):.2f}"
        assert abs(cx - 96) <= 6 and abs(cy - 96) <= 6, f"kill_ink_{i} 偏了"


def test_groups_distinct():
    """五种命中互相不一样（不是同一套图换名字）。"""
    names = ["hit_metal", "hit_wood", "hit_water", "hit_fire", "hit_earth"]
    for k, a in enumerate(names):
        for b in names[k + 1 :]:
            d = np.abs(alpha(a, 1) - alpha(b, 1)).mean()
            assert d > 2.0, f"{a} 和 {b} 太像了（平均差 {d:.2f}）"


# ---------------------------------------------------------------- 第二批


def test_fire_burst_rises():
    """火爆：第 0 帧在爆点（锚点）一闪；之后火往上窜（质心一路往上）；末两帧芯空了（锚点附近比第 2 帧淡得多）；
    墨烟在火舌尖上方（比爆点高 radius_px 的六成以上）。"""
    w, h = SPEC2["fire_burst"][1]
    ax, ay = (np.array(meta()["files"]["fire_burst_0.png"]["anchor"]) * [w, h]).tolist()
    cx0, cy0 = centroid(alpha("fire_burst", 0))
    assert math.hypot(cx0 - ax, cy0 - ay) <= 12, f"火爆第 0 帧不在爆点：({cx0:.0f}, {cy0:.0f}) vs ({ax:.0f}, {ay:.0f})"
    ys = [centroid(alpha("fire_burst", i))[1] for i in frames_of("fire_burst")]
    assert ys[1] < ys[0] and ys[3] < ys[1] - 8 and ys[6] < ys[1] - 10, f"火应该往上窜：质心 y {[round(y) for y in ys]}"
    hole = [alpha("fire_burst", i)[int(ay) - 6 : int(ay) + 6, int(ax) - 6 : int(ax) + 6].mean() for i in (2, 5, 6)]
    assert hole[1] < 0.3 * hole[0] and hole[2] < 0.3 * hole[0], f"末两帧芯应该空了：{[round(v) for v in hole]}"
    for i in frames_of("fire_burst_smoke"):
        _, sy = centroid(alpha("fire_burst_smoke", i))
        assert sy < ay - 0.6 * F.FIRE_R, f"墨烟 {i} 不在火舌尖上方：质心 y {sy:.0f}，爆点 {ay:.0f}"


def test_ice_shards_fly_out():
    """冰碎：在中心裂开，碎片一帧比一帧往外飞（亮度按半径加权的平均半径变大），不出画布。"""
    w, h = SPEC2["ice_shatter"][1]
    ys, xs = np.mgrid[0:h, 0:w] + 0.5
    r = np.hypot(xs - w / 2, ys - h / 2)
    mean_r = [float((alpha("ice_shatter", i) * r).sum() / alpha("ice_shatter", i).sum()) for i in frames_of("ice_shatter")]
    assert mean_r[0] < 30 and all(a < b for a, b in zip(mean_r[1:5], mean_r[2:5])), f"碎片应该往外飞：平均半径 {[round(v) for v in mean_r]}"
    for i in frames_of("ice_shatter"):
        cx, cy = centroid(alpha("ice_shatter", i))
        assert math.hypot(cx - w / 2, cy - h / 2) <= 8, f"ice_shatter_{i} 偏心"


def test_feathers_are_particles():
    """羽毛纸屑：4 种互不相同，都是横着的长条（尖 / 长边朝 +X），在画布中间；小图不抖动（看得见的 alpha 没有孤立的噪点）。"""
    for i in frames_of("feather"):
        a = alpha("feather", i)
        x0, y0, x1, y1 = bbox(a > 40)
        assert (x1 - x0 + 1) >= 2.2 * (y1 - y0 + 1), f"feather_{i} 不够长：{x1 - x0 + 1}×{y1 - y0 + 1}"
        cx, cy = centroid(a)
        assert abs(cx - 16) <= 3 and abs(cy - 8) <= 2, f"feather_{i} 不在中间：({cx:.1f}, {cy:.1f})"
        lone = (a > 0) & (np.roll(a, 1, 0) == 0) & (np.roll(a, -1, 0) == 0) & (np.roll(a, 1, 1) == 0) & (np.roll(a, -1, 1) == 0)
        assert not lone.any(), f"feather_{i} 有孤立的噪点"
    for i in (0, 1):  # 羽毛比纸片细：最宽处不到 8 像素
        a = alpha("feather", i)
        assert (a > 60).sum(0).max() <= 8, f"feather_{i} 太宽，像叶子"


def test_evolve_radial():
    """进化爆发：在画布中心炸开（每帧质心离中心不超过 10 像素），0–3 帧越开越大、之后不收回，末两帧散成光点、淡到一成五以下。"""
    w, h = SPEC2["evolve"][1]
    ys, xs = np.mgrid[0:h, 0:w] + 0.5
    r = np.hypot(xs - w / 2, ys - h / 2)
    rms = []
    for i in frames_of("evolve"):
        a = alpha("evolve", i)
        cx, cy = centroid(a)
        assert math.hypot(cx - w / 2, cy - h / 2) <= 10, f"evolve_{i} 偏心：({cx:.0f}, {cy:.0f})"
        rms.append(float(np.sqrt((a * r * r).sum() / a.sum())))
    assert all(a < b for a, b in zip(rms[:4], rms[1:4])) and min(rms[4:]) >= 0.9 * rms[3], f"进化应该开到第 3 帧、之后不收回：{[round(v) for v in rms]}"
    sums = [alpha("evolve", i).sum() for i in frames_of("evolve")]
    assert sums[-1] <= 0.15 * max(sums), f"进化末帧还有 {sums[-1] / max(sums):.2f}"


def test_pillar_from_ground():
    """进化光柱：锚点在底边中点；第 0 帧只到三分之一高，1–2 帧冲到顶；整根光柱在中线附近；之后从下往上淡（质心一路往上）。"""
    w, h = SPEC2["evolve_pillar"][1]
    assert meta()["files"]["evolve_pillar_0.png"]["anchor"] == [0.5, 1.0]

    def top(i):
        rows = np.nonzero(alpha("evolve_pillar", i).max(1) > 0.25 * PEAK8)[0]
        return int(rows.min())

    assert top(0) > h * 0.55 and top(2) < h * 0.1, f"光柱高度：第 0 帧顶到 {top(0)}，第 2 帧顶到 {top(2)}"
    for i in frames_of("evolve_pillar"):
        a = alpha("evolve_pillar", i)
        assert a[:, w // 2 - 36 : w // 2 + 36].sum() >= 0.85 * a.sum(), f"evolve_pillar_{i} 太散"
    ys = [centroid(alpha("evolve_pillar", i))[1] for i in frames_of("evolve_pillar")]
    assert all(a > b for a, b in zip(ys, ys[1:])), f"光柱应该从下往上：质心 y {[round(y) for y in ys]}"


# ---------------------------------------------------------------- 第三批：反应


def anchor_px(name: str) -> tuple[float, float]:
    w, h = ALL[name][1]
    ax, ay = meta()["files"][f"{name}_0.png"]["anchor"]
    return ax * w, ay * h


def fullest(name: str) -> int:
    return int(np.argmax([alpha(name, i).sum() for i in frames_of(name)]))


def test_reaction_colors():
    """反应都自带颜色、不染：最满那帧按 alpha 加权的平均色接近清单的主色（滋生、裂土去掉焦墨勾边再算）；
    火、赤地、铸兵、熔金、土刺、泥是暖的（R ≥ G ≥ B），凝霜偏冷（B ≥ G ≥ R），滋生偏绿，蒸腾是带一点蓝灰的白；断木金、木两种颜色都有。"""
    for name, hexc in REACT_COLOR.items():
        px = rgba(name, fullest(name)).astype(float)
        w = px[..., 3].copy()
        if name in ("react_zisheng", "react_lietu"):
            w *= px[..., :3] @ np.array([0.299, 0.587, 0.114]) > 70
        got = (px[..., :3] * w[..., None]).sum((0, 1)) / w.sum()
        assert np.abs(got - F.V.col(hexc) * 255).max() <= 45, f"{name} 的平均色 {got.round()} 离主色 {hexc} 太远"
    for name in SPEC3:
        for i in frames_of(name):
            px = rgba(name, i)
            rgb = px[..., :3][px[..., 3] > 0].astype(int)
            r, g, b = rgb[:, 0], rgb[:, 1], rgb[:, 2]
            if name in ("react_liaoyuan", "react_rongyan", "react_zhubing", "react_rongjin", "react_lietu", "react_yuni"):
                assert ((r >= g) & (g >= b)).all(), f"{name}_{i} 不全是暖色"
            elif name == "react_ningshuang":
                assert ((b >= g) & (g >= r)).all(), f"{name}_{i} 不全是冷色"
            elif name == "react_zhengteng":
                vis = px[..., 3][px[..., 3] > 0] > 64
                assert ((b >= g) & (g >= r)).all() and (rgb[vis] @ np.array([0.299, 0.587, 0.114]) > 90).all(), f"{name}_{i} 不是白汽"
            elif name == "react_zisheng":
                lit = rgb @ np.array([0.299, 0.587, 0.114]) > 70
                assert ((g >= r) & (g >= b))[lit].mean() >= 0.98, f"{name}_{i} 不够绿"

    def count(i, green):
        px = rgba("react_duanmu", i).astype(int)
        r, g, b, a = (px[..., k] for k in range(4))
        m = (g - r > 30) if green else ((r >= g) & (r - b > 40))
        return int((m & (a > 60)).sum())

    assert count(0, True) <= 50 and count(0, False) >= 500, "断木第 0 帧应该只有金色的一刀"
    assert count(2, True) >= 500 and count(2, False) >= 500, "断木第 2 帧两刀（金、木）都要在"


def test_reactions_in_place():
    """在锚点上炸开：居中的反应每帧质心离锚点不超过 8 像素（断木从第 2 帧起，两刀都出来以后）；
    地面的已压扁（最满那帧 alpha > 10 的包围盒高宽比约 0.62）。"""
    for name in ("react_liaoyuan", "react_zhubing", "react_rongyan", "react_ningshuang", "react_yuni", "react_rongjin", "react_duanmu"):
        ax, ay = anchor_px(name)
        for i in frames_of(name)[2 if name == "react_duanmu" else 0 :]:
            cx, cy = centroid(alpha(name, i))
            assert math.hypot(cx - ax, cy - ay) <= 8, f"{name}_{i} 偏了：({cx:.0f}, {cy:.0f})，锚点 ({ax:.0f}, {ay:.0f})"
    for name in GROUND3:
        x0, y0, x1, y1 = bbox(alpha(name, fullest(name)) > 10)
        ratio = (y1 - y0 + 1) / (x1 - x0 + 1)
        assert abs(ratio - F.FLAT) <= 0.07, f"{name} 没压扁：高宽比 {ratio:.2f}"


def test_reaction_sizes():
    """radius_px 是看得见的横向半径：有范围的反应，最满那帧 alpha > 10 的左右半宽（取平均）在 radius_px 的 0.85–1.2 倍之间。"""
    for name in REACT_RANGE:
        a = alpha(name, fullest(name))
        ax, _ = anchor_px(name)
        xs = np.nonzero(a.max(0) > 10)[0]
        half = (ax - xs.min() + xs.max() + 1 - ax) / 2
        r = meta()["files"][f"{name}_0.png"]["radius_px"]
        assert 0.85 * r <= half <= 1.2 * r, f"{name} 看得见的半宽 {half:.0f}，radius_px {r}"


def test_reactions_hold_and_fade():
    """末帧能留着的（赤地、凝霜、滋生、淤泥）：末两帧形状一样、只是浓淡不同（alpha 的相关系数 ≥ 0.95）、末帧还有最满那帧的四成以上；
    一次性的普通混合（蒸腾、裂土）末帧淡到一半以下。"""
    for name in HOLD3:
        n = SPEC3[name][0]
        corr = float(np.corrcoef(alpha(name, n - 2).ravel(), alpha(name, n - 1).ravel())[0, 1])
        assert corr >= 0.95, f"{name} 末两帧形状不一样（相关系数 {corr:.3f}），留不住"
        sums = [alpha(name, i).sum() for i in frames_of(name)]
        assert sums[-1] >= 0.4 * max(sums), f"{name} 末帧太淡（{sums[-1] / max(sums):.2f}），留着看不见"
        assert meta()["files"][f"{name}_{n - 1}.png"]["hold_last"] is True
    for name in ("react_zhengteng", "react_lietu"):
        sums = [alpha(name, i).sum() for i in frames_of(name)]
        assert sums[-1] <= 0.5 * max(sums), f"{name} 末帧还有 {sums[-1] / max(sums):.2f}"


def test_liaoyuan_three_tongues():
    """燎原：火舌够到的那几帧，锚点外 0.45–0.9 倍半径的一圈里，亮的地方分成三段（三条火舌）；末帧比最满那帧淡得多。"""
    ax, ay = anchor_px("react_liaoyuan")
    R = meta()["files"]["react_liaoyuan_0.png"]["radius_px"]
    h, w = SPEC3["react_liaoyuan"][1][1], SPEC3["react_liaoyuan"][1][0]
    ys, xs = np.mgrid[0:h, 0:w] + 0.5
    r = np.hypot(xs - ax, ys - ay)
    th = np.arctan2(ys - ay, xs - ax)
    ring = (r > 0.45 * R) & (r < 0.9 * R)
    for i in (2, 3):
        a = alpha("react_liaoyuan", i)
        prof = np.bincount(((th[ring] + math.pi) / (2 * math.pi) * 72).astype(int) % 72, weights=a[ring], minlength=72)
        on = prof > 0.3 * prof.max()
        runs = int((on & ~np.roll(on, 1)).sum())
        assert runs == 3, f"react_liaoyuan_{i}: 一圈里亮的分成 {runs} 段，应该是三条火舌"


def test_zhubing_blades_fly_out():
    """铸兵：第 0 帧在中心一闪，之后三片金刃一帧比一帧往外飞（亮度加权的平均半径变大），不出画布。"""
    w, h = SPEC3["react_zhubing"][1]
    ys, xs = np.mgrid[0:h, 0:w] + 0.5
    r = np.hypot(xs - w / 2, ys - h / 2)
    mean_r = [float((alpha("react_zhubing", i) * r).sum() / alpha("react_zhubing", i).sum()) for i in frames_of("react_zhubing")]
    assert mean_r[0] < 25 and all(a < b for a, b in zip(mean_r, mean_r[1:])), f"金刃应该往外飞：平均半径 {[round(v) for v in mean_r]}"


def test_ningshuang_grows_then_holds():
    """凝霜：0–3 帧霜花一帧比一帧大，3–5 帧大小不变（留着）、只是变淡。"""
    widths = [np.ptp(np.nonzero(alpha("react_ningshuang", i).max(0) > 10)[0]) for i in frames_of("react_ningshuang")]
    assert all(a < b for a, b in zip(widths[:4], widths[1:4])) and max(widths[3:]) - min(widths[3:]) <= 4, f"霜花宽度 {widths}"
    sums = [alpha("react_ningshuang", i).sum() for i in frames_of("react_ningshuang")]
    assert sums[3] > sums[4] > sums[5], f"霜花 3–5 帧应该慢慢变淡：{[round(s / 255) for s in sums]}"


def test_rongjin_loops():
    """熔金印记循环：首尾那一步（5 → 0）和其他相邻两帧差不多（接得上，不跳）；每帧亮度总量差不多（不闪）。"""
    fr = [alpha("react_rongjin", i) for i in frames_of("react_rongjin")]
    d = [float(np.abs(fr[(i + 1) % 6] - fr[i]).mean()) for i in range(6)]
    assert d[-1] <= 1.3 * max(d[:-1]) and min(d) > 0.5, f"熔金首尾接不上：相邻帧差 {[round(v, 2) for v in d]}"
    sums = [a.sum() for a in fr]
    assert min(sums) >= 0.85 * max(sums), f"熔金各帧亮度差太多：{[round(s / 255) for s in sums]}"


def test_duanmu_cross_flash():
    """断木：第 2 帧两刀交叉处一闪（交叉点附近 alpha 接近最亮）；3–4 帧淡下去。"""
    a = alpha("react_duanmu", 2)
    ys, xs = np.nonzero(a >= 0.9 * a.max())
    assert np.hypot(xs.mean() - 128, ys.mean() - 128) <= 16, f"断木最亮的地方不在交叉处：({xs.mean():.0f}, {ys.mean():.0f})"
    sums = [alpha("react_duanmu", i).sum() for i in frames_of("react_duanmu")]
    assert sums[2] > sums[3] > sums[4], f"断木 3–4 帧应该淡下去：{[round(s / 255) for s in sums]}"


def test_zisheng_grows_from_root():
    """滋生：草从锚点（地面）往上长：0–3 帧草尖一帧比一帧高，3–5 帧差不多；浓的部分都在锚点以上（不长到地下）。"""
    _, ay = anchor_px("react_zisheng")
    tops = [int(np.nonzero(alpha("react_zisheng", i).max(1) > 100)[0].min()) for i in frames_of("react_zisheng")]
    assert all(a > b for a, b in zip(tops[:4], tops[1:4])) and max(tops[3:]) - min(tops[3:]) <= 6, f"草尖的高度（行）{tops}"
    assert ay - tops[3] >= 70, f"草长得太矮：{ay - tops[3]:.0f} 像素"
    for i in frames_of("react_zisheng"):
        rows = np.nonzero(alpha("react_zisheng", i).max(1) > 200)[0]
        assert rows.max() <= ay + 24, f"react_zisheng_{i} 的草长到锚点下面 {rows.max() - ay:.0f} 像素"


def test_zhengteng_rises():
    """蒸腾：0–3 帧一帧比一帧宽（第 0 帧一小团，宽不到第 3 帧的六成）；2 帧以后整团往上飘（质心一帧比一帧高）。"""
    widths = [np.ptp(np.nonzero(alpha("react_zhengteng", i).max(0) > 10)[0]) for i in frames_of("react_zhengteng")]
    assert all(a < b for a, b in zip(widths[:4], widths[1:4])) and widths[0] < 0.6 * widths[3], f"蒸腾的宽度：{widths}"
    ys = [centroid(alpha("react_zhengteng", i))[1] for i in frames_of("react_zhengteng")]
    assert all(a > b - 1 for a, b in zip(ys[2:], ys[3:])) and ys[6] < ys[2] - 8, f"汽应该往上飘：质心 y {[round(y) for y in ys]}"


def test_lietu_spikes_rise_and_sink():
    """裂土：地刺从地里冲出来（第 0 帧的刺尖比第 2 帧低 50 像素以上），末帧塌回去（比第 3 帧低 20 以上）；刺都在锚点（地面）以上。"""
    _, ay = anchor_px("react_lietu")

    def top(i):
        px = rgba("react_lietu", i).astype(float)
        body = (px[..., 3] > 128) & (px[..., :3] @ np.array([0.299, 0.587, 0.114]) > 70)  # 不算焦墨的地缝
        return int(np.nonzero(body.any(1))[0].min()), body

    t0, _ = top(0)
    t2, body = top(2)
    t3, _ = top(3)
    t5, _ = top(5)
    assert t0 > t2 + 50 and t5 > t3 + 20, f"刺尖的高度（行）：第 0 帧 {t0}、第 2 帧 {t2}、第 3 帧 {t3}、第 5 帧 {t5}"
    ys = np.nonzero(body)[0]
    assert ys.mean() < ay - 20 and ay - t2 >= 120, f"地刺不在地面上：平均行 {ys.mean():.0f}，锚点 {ay:.0f}，刺尖 {t2}"


def test_yuni_spreads_then_settles():
    """淤泥：0–2 帧一帧比一帧摊开，末两帧几乎一样（落定，可以留着）。"""
    widths = [np.ptp(np.nonzero(alpha("react_yuni", i).max(0) > 40)[0]) for i in frames_of("react_yuni")]
    assert widths[0] < widths[1] < widths[2], f"泥滩宽度 {widths}"
    d = float(np.abs(alpha("react_yuni", 5) - alpha("react_yuni", 4)).mean())
    assert d < 2.0, f"淤泥末两帧还在变（平均差 {d:.2f}）"


# ---------------------------------------------------------------- 其他


def test_review_images():
    sheet = Image.open(F.REVIEW / "vfx_frames_b1.png")
    assert sheet.width >= 2000 and sheet.height >= 3000, f"帧条审图尺寸 {sheet.size}"
    assert Image.open(F.REVIEW / "vfx_frames_b1_ingame.png").size == (1920, 1080)
    sheet = Image.open(F.REVIEW / "vfx_frames_b2.png")
    assert sheet.width >= 2000 and sheet.height >= 2000, f"第二批帧条审图尺寸 {sheet.size}"
    assert Image.open(F.REVIEW / "vfx_frames_b2_ingame.png").size == (1920, 1080)
    sheet = Image.open(F.REVIEW / "vfx_frames_b3.png")
    assert sheet.width >= 2000 and sheet.height >= 4000, f"第三批帧条审图尺寸 {sheet.size}"
    for suffix in ("", "2"):
        assert Image.open(F.REVIEW / f"vfx_frames_b3_ingame{suffix}.png").size == (1920, 1080)


def test_deterministic():
    """再画一遍，逐像素和磁盘上的一样（固定种子；也说明磁盘上的产物是最新的）。--quick 跳过。"""
    if "--quick" in sys.argv:
        print("      （--quick：跳过）")
        return
    for batch in F.BATCHES.values():
        for name, imgs in F.build(batch).items():
            for i, img in enumerate(imgs):
                assert (np.asarray(img) == rgba(name, i)).all(), f"{name}_{i} 和磁盘上的不一样"


def test_writes_only_own_outputs():
    """只在 --regen（或产物过期重新生成）时有记录：所有写盘都在 vfx_frames/ 或 review@2x/vfx_frames_*；别的产物没动。"""
    if not WRITTEN:
        print("      （这次没有重新生成，跳过写盘检查；加 --regen 可测）")
        return
    out, review = F.OUT.resolve(), F.REVIEW.resolve()
    for p in WRITTEN:
        assert p.is_relative_to(out) or (p.is_relative_to(review) and p.name.startswith("vfx_frames_")), f"写到了不该写的地方：{p}"
    assert protected() == SNAPSHOT, "别的产物（assets/atlas 或 art/out/assets@2x 的其他目录）被改动了"


def atlas_frames() -> tuple[dict, dict, dict]:
    """vfx 图集的帧表、meta.lantern.frames、每帧所在的页图（多页也能读）。"""
    index = json.loads((ATLAS / "index.json").read_text(encoding="utf-8"))
    frames, info, page_of = {}, {}, {}
    for fn in index["pages"].get("vfx", []):
        j = json.loads((ATLAS / fn).read_text(encoding="utf-8"))
        img = np.asarray(Image.open(ATLAS / j["meta"]["image"]).convert("RGBA"))
        for k, f in j["frames"].items():
            frames[k], page_of[k] = f, img
        info.update(j["meta"]["lantern"]["frames"])
    return frames, info, page_of


def test_atlas_packed():
    """打包后的 vfx 图集里每帧都在：锚点、混合、可染、动画字段原样带进 meta.lantern.frames，像素和产物一样。
    还没打包进图集时只提示、不算失败。"""
    frames, info, page_of = atlas_frames()
    if "vfx/hit_metal_0" not in frames:
        print("      （assets/atlas 里还没有逐帧特效，跳过）")
        return
    packed = dict(SPEC)
    for key, spec, label in (("vfx/fire_burst_0", SPEC2, "第二批"), ("vfx/react_liaoyuan_0", SPEC3, "第三批")):
        if key in frames:
            packed.update(spec)
        else:
            print(f"      （图集里还没有{label}，不查）")
    for name, (n, size, blend, tint) in packed.items():
        seq = ("variant", "variants") if name in VARIANTS else ("anim", "frame", "frames", "fps", "loop")
        for i in range(n):
            key = f"vfx/{name}_{i}"
            assert key in frames, f"图集里缺 {key}"
            f, li = frames[key], info[key]
            src = meta()["files"][f"{name}_{i}.png"]
            assert (f["sourceSize"]["w"], f["sourceSize"]["h"]) == size, f"{key} 原画布 {f['sourceSize']}"
            assert [f["anchor"]["x"], f["anchor"]["y"]] == src["anchor"], f"{key} 锚点 {f['anchor']}"
            for k in ("blend", "tint") + seq + tuple(k for k in ("radius_px", "flat", "hold_last") if k in src):
                assert li[k] == src[k], f"{key} 的 {k}：图集 {li[k]}，产物 {src[k]}"
            r, s = f["frame"], f["spriteSourceSize"]
            can = np.zeros((size[1], size[0], 4), np.uint8)
            can[s["y"] : s["y"] + s["h"], s["x"] : s["x"] + s["w"]] = page_of[key][r["y"] : r["y"] + r["h"], r["x"] : r["x"] + r["w"]]
            a, b = can, rgba(name, i)
            vis = (a[..., 3] > 0) | (b[..., 3] > 0)
            assert (a[..., 3] == b[..., 3]).all() and (a[vis] == b[vis]).all(), f"图集里的 {key} 和产物不一样"
    slash = info["vfx/slash_0"]
    assert slash["radius_px"] == F.SLASH_R and slash["angle_deg"] == 120 and slash["points"] == "+x", slash


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
