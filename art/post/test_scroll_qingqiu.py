#!/usr/bin/env python3
"""scroll_qingqiu.py 的自检：纯 assert，不依赖 pytest。只有桌面版（2 倍），与 LANTERN_ART_DENSITY 无关。

产物缺失或比脚本旧时先重新生成（约 2 分钟）；--regen 强制重新生成；--determinism 再画一遍长夜版逐字节比对（多 1 分钟）。

用法（在仓库根目录下）：
  art/.venv/bin/python art/post/test_scroll_qingqiu.py
"""

from __future__ import annotations

import hashlib
import sys
import traceback
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import scroll_qingqiu as Q  # noqa: E402

NIGHT = Q.OUT / "scroll_qingqiu.png"
DAWN = Q.OUT / "scroll_qingqiu_dawn.png"
REVIEW = Q.REVIEW / "scroll_qingqiu_review.png"
SEAL_BOX = (Q.SEAL_AT[0] - 2, Q.SEAL_AT[1] - 2, Q.SEAL_AT[0] + Q.SEAL_PX + 2, Q.SEAL_AT[1] + Q.SEAL_PX + 2)
_cache: dict[str, np.ndarray] = {}


def ensure_outputs(force: bool) -> None:
    srcs = [HERE / n for n in ("scroll_qingqiu.py", "title_screen.py", "vfx_textures.py", "ui_fonts.py")] + [Q.ART / "style" / "style.py"]
    newest = max(p.stat().st_mtime for p in srcs)
    stale = [p for p in (NIGHT, DAWN, REVIEW) if not p.exists() or p.stat().st_mtime < newest]
    if force or stale:
        print("重新生成卷轴……")
        Q.main()


def img(path: Path) -> np.ndarray:
    if str(path) not in _cache:
        _cache[str(path)] = np.asarray(Image.open(path).convert("RGB"), np.float64) / 255.0
    return _cache[str(path)]


def lum(a: np.ndarray) -> np.ndarray:
    return a @ np.array([0.299, 0.587, 0.114])


def outside_seal() -> np.ndarray:
    m = np.ones((Q.H, Q.W), bool)
    x0, y0, x1, y1 = SEAL_BOX
    m[y0:y1, x0:x1] = False
    return m


def hipass(L: np.ndarray, sigma: float = 6.0) -> np.ndarray:
    return L - Q.blur(L, sigma)


def test_files_and_size():
    for p in (NIGHT, DAWN):
        im = Image.open(p)
        assert im.size == (2400, 800) and im.mode == "RGB", f"{p.name} 应为 2400×800 不透明 RGB（实际 {im.size} {im.mode}）"
    assert REVIEW.exists() and Image.open(REVIEW).width == 1280, "审图应是 1280 宽"


def test_night_is_ink_only():
    """长夜版只有墨：除朱砂印外，每个像素都是纸色和墨色之间的暖灰（彩度低、不偏青不偏绿）。"""
    a = img(NIGHT)[outside_seal()]
    chroma = a.max(1) - a.min(1)
    assert np.percentile(chroma, 99.9) <= 0.16, f"长夜版有颜色（彩度 99.9 分位 {np.percentile(chroma, 99.9):.3f}）"
    cool = (a[:, 2] > a[:, 0] + 0.025) | (a[:, 1] > a[:, 0] + 0.025)
    assert cool.mean() < 0.001, f"长夜版有偏青 / 偏绿的像素（{cool.mean():.4f}）"


def test_seal():
    """两张都有一方小朱砂印，只在左下角；印外没有朱红。"""
    for p in (NIGHT, DAWN):
        a = img(p)
        red = (a[..., 0] > a[..., 1] + 0.25) & (a[..., 0] > a[..., 2] + 0.25)
        x0, y0, x1, y1 = SEAL_BOX
        inside = red[y0:y1, x0:x1].sum()
        assert inside > 0.3 * Q.SEAL_PX ** 2, f"{p.name} 左下角应有朱砂印（红像素 {inside}）"
        assert red[outside_seal()].sum() < 50, f"{p.name} 印外不应有朱红（{red[outside_seal()].sum()}）"


def test_text_area_quiet():
    """旁白区安静：笔触的细节（高通能量）比画面主体少得多，也没有浓墨；长夜里够暗，纸色字看得清。"""
    x0, y0, x1, y1 = Q.TEXT_BOX
    for p, dark in ((NIGHT, True), (DAWN, False)):
        L = lum(img(p))
        hp = np.abs(hipass(L))
        box = hp[y0:y1, x0:x1].mean()
        body = hp[:, 1000:2300].mean()
        assert box < 0.35 * body, f"{p.name} 旁白区太花（高通 {box:.4f}，画面主体 {body:.4f}）"
        assert (L[y0:y1, x0:x1] < 0.12).mean() < 0.002, f"{p.name} 旁白区里有浓墨"
        m = L[y0:y1, x0:x1].mean()
        if dark:
            paper_l = lum(Q.PAPER)
            assert (paper_l + 0.05) / (m + 0.05) > 2.6, f"长夜旁白区不够暗（平均亮度 {m:.2f}），纸色字对比不足"
        else:
            assert m > 0.6, f"天明旁白区应是亮的晓色（平均亮度 {m:.2f}），写墨色字"


def test_same_painting():
    """天明和长夜是同一幅画：笔触的细节（高通亮度）高度相关；天明整体更亮。"""
    Ln, Ld = lum(img(NIGHT)), lum(img(DAWN))
    hn, hd = hipass(Ln)[:, 900:], hipass(Ld)[:, 900:]
    r = np.corrcoef(hn.ravel(), hd.ravel())[0, 1]
    assert r > 0.6, f"两张不像同一幅画（细节相关系数 {r:.2f}）"
    assert Ld.mean() > Ln.mean() + 0.1, f"天明应比长夜亮（{Ld.mean():.2f} vs {Ln.mean():.2f}）"


def test_dawn_colour():
    """天明的颜色回来了：竹子一带偏石绿；东边（右）低处偏暖；屋檐下的灯是青光（绿、蓝都比红高）。"""
    a = img(DAWN)
    mid = a[60:760, 1000:1700]
    green = (mid[..., 1] > mid[..., 0] + 0.03)
    assert green.mean() > 0.12, f"竹海不够绿（{green.mean():.3f}）"
    chroma_d = (a.max(-1) - a.min(-1))[:, 900:].mean()
    chroma_n = (img(NIGHT).max(-1) - img(NIGHT).min(-1))[:, 900:].mean()
    assert chroma_d > chroma_n + 0.03, f"天明的颜色太淡（彩度 {chroma_d:.3f} vs 长夜 {chroma_n:.3f}）"
    east = a[170:300, 2000:2400].reshape(-1, 3).mean(0)  # 狐村上方的天
    west = a[170:300, 100:500].reshape(-1, 3).mean(0)  # 旁白区的天
    assert east[0] - east[2] > west[0] - west[2] + 0.03, f"东边应比西边暖（{east.round(3)} vs {west.round(3)}）"
    for (cx, yb, w, wh, rh) in Q.HOUSES:
        for (x, y, s, _) in Q.lantern_spots(cx, yb, w, wh, rh):
            ring = a[int(y) - 18 : int(y) + 18, int(x) - 18 : int(x) + 18].reshape(-1, 3).mean(0)
            assert ring[1] > ring[0] + 0.02 and ring[2] >= ring[0], f"({x:.0f}, {y:.0f}) 的灯在天明时应是青光：{ring.round(3)}"


def test_night_glows():
    """长夜里灯和狐火是亮的（留白 + 烘出来的光）：灯心比周围的墙亮得多；狐火处比周围亮。"""
    L = lum(img(NIGHT))
    for (cx, yb, w, wh, rh) in Q.HOUSES:
        for (x, y, s, _) in Q.lantern_spots(cx, yb, w, wh, rh):
            core = L[int(y) - 3 : int(y) + 4, int(x) - 3 : int(x) + 4].mean()
            around = np.median(L[int(y) - 150 : int(y) + 150, int(x) - 150 : int(x) + 150])
            assert core > 0.85 and core > around + 0.12, f"({x:.0f}, {y:.0f}) 的灯不够亮（{core:.2f}，周围 {around:.2f}）"
    for (x, y, s) in Q.WISPS:
        core = L[int(y) - 3 : int(y) + 4, int(x) - 3 : int(x) + 4].mean()
        around = np.median(L[int(y) - 100 : int(y) + 100, int(x) - 100 : int(x) + 100])
        assert core > around + 0.15, f"({x:.0f}, {y:.0f}) 的狐火不够亮（{core:.2f}，周围 {around:.2f}）"


def test_size_on_disk():
    for p in (NIGHT, DAWN):
        kb = p.stat().st_size / 1024
        assert kb < 6000, f"{p.name} {kb:.0f} KB 太大"


def test_determinism():
    """固定种子：再画一遍长夜版，与盘上的逐字节相同（--determinism 时才跑）。"""
    if "--determinism" not in sys.argv:
        print("      （跳过：加 --determinism 再画一遍比对）")
        return
    paper = Q.paper_wide(np.random.default_rng(Q.SEED - 1))
    again = Q.paint(False, paper)
    assert hashlib.md5(np.asarray(again).tobytes()).hexdigest() == hashlib.md5(np.asarray(Image.open(NIGHT).convert("RGB")).tobytes()).hexdigest(), "两次生成不一致"


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
