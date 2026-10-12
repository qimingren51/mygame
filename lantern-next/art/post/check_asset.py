"""素材自检：按 style.py 末尾的输出约定检查一个素材文件夹。

用法：
    art/.venv/bin/python art/post/check_asset.py art/out/style/assets/hero [更多文件夹...]
全部通过返回 0；有不通过的项返回 1，并打印中文报告。--json 时额外输出机器可读结果。

检查项：
  1. meta.json 结构：name/size/anchor/anims/sockets；每个动画有 frames/fps/dirs，朝向都在 DIRS 里；
     anchor 必须是 ANCHOR（道具 category=prop 时是 PROP_ANCHOR）
  2. 每个 <动画>_<朝向>_<帧号>.png 都存在、是 RGBA、尺寸等于 meta.size；附带的 _emit/_flash 图尺寸一致
  3. 四周至少 1px 完全透明（不能贴边）
  4. 脚底漂移：同一动画同一朝向的各帧，“脚点”离中位数不超过 FOOT_TOLERANCE_PX
  5. 身高：各帧身高离全素材中位数不超过 HEIGHT_TOLERANCE；meta 给了 height_px 时也和目标比
  6. 调色板：不透明的非墨线像素里，≥90% 离调色板（full_palette + 发光色）在 PALETTE_TOLERANCE 以内
  7. 墨线占比：在合理范围 LINE_RATIO_RANGE 内
  8. 挂点：meta.sockets 里每个挂点都覆盖每个动画、每个朝向、每一帧

“脚点”的定义（对走路时一只脚前后移动不敏感）：
  - 只看锚点左右 BODY_WINDOW×宽 的中间列（排除灯笼、飘带等伸到两侧的部件）
  - 底线 y：自下而上第一行“宽度 ≥ 下半身最宽行的 35%”的行（取到的是下摆/双脚这一整排，
    不会被单个脚尖拉低）
  - 脚点 x：底线往上 BASE_BAND×身高 这一条带里，按 alpha 加权的水平重心
  悬浮的素材（meta.floating=true）只检查 x。
“身高”：中间列里最上面一个不透明像素到底线的距离；与目标比较时减去一个外线宽
  （外轮廓线在顶部和底部各有约半个线宽伸出模型之外）。
“墨线像素”：离墨线色 LINE_NEAR 以内的纯墨，或不在调色板容差内、但能解释为“某个调色板色与墨线色的混合、
  墨的比例 ≥ 20%”的过渡像素。焦墨填色（头发、靴子暗面）也算在墨里，所以墨线占比其实是“墨的覆盖率”。
  底线 y 和顶 y 都取亚像素（行宽/行 alpha 总量插值），否则整数行跳动本身就有 1px。
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ART = Path(__file__).resolve().parents[1]
if str(ART) not in sys.path:
    sys.path.insert(0, str(ART))
from style import style as S  # noqa: E402

LIGHT_COLORS = [S.LANTERN_LIGHT, S.FLAME_LIGHT, S.SOUL_LIGHT, *S.EYE.values()]
PALETTE_MIN_SHARE = 0.90
LINE_RATIO_RANGE = (0.05, 0.60)
BODY_WINDOW = 0.15  # 中间列半宽（相对帧宽）
BASE_BAND = 0.12
ALPHA_OPAQUE = 0.5
LINE_NEAR = 10.0  # 离墨线色这么近就算纯墨
FOOT_EXCLUDE_PX = 2  # 求脚点 x 时去掉最底下几行（单个脚尖），只看下摆/双脚这一排
FRAME_RE = re.compile(r"^(?P<anim>[a-z0-9]+)_(?P<dir>[A-Z]{1,2})_(?P<idx>\d{2})(?P<suffix>_[a-z]+)?\.png$")


def _pal(extra=()):
    cols = list(S.full_palette()) + [c for c in extra if c not in S.full_palette()]
    return np.array([S.hex_to_rgb(c) for c in cols], np.float32)


def line_mask(rgb: np.ndarray, pal: np.ndarray, tol: float = S.PALETTE_TOLERANCE, min_t: float = 0.2) -> np.ndarray:
    """墨线像素 = 离墨线色 LINE_NEAR 以内（纯墨），或者“不在调色板容差内、但能解释为某个调色板色 p 与
    墨线色的混合（墨比例 t≥min_t）”（线条边缘的过渡像素）。在调色板容差内的其它颜色都算填色。"""
    ink = np.array(S.hex_to_rgb(S.LINE_COLOR), np.float32)
    flat = rgb.reshape(-1, 3).astype(np.float32)
    near_ink = np.sqrt(((flat - ink) ** 2).sum(-1)) <= LINE_NEAR
    off_pal = palette_distance(rgb, pal).reshape(-1) > tol
    mixed = np.zeros(flat.shape[0], bool)
    for p in pal:
        d = ink - p
        dd = float((d * d).sum())
        if dd < 1e-6:
            continue
        t = np.clip(((flat - p) @ d) / dd, 0, 1)
        dist = np.sqrt(((flat - (p + t[:, None] * d)) ** 2).sum(-1))
        mixed |= (dist <= tol) & (t >= min_t)
    return (near_ink | (off_pal & mixed)).reshape(rgb.shape[:2])


def palette_distance(rgb: np.ndarray, pal: np.ndarray) -> np.ndarray:
    flat = rgb.reshape(-1, 3).astype(np.float32)
    best = np.full(flat.shape[0], np.inf, np.float32)
    for p in pal:
        best = np.minimum(best, np.sqrt(((flat - p) ** 2).sum(-1)))
    return best.reshape(rgb.shape[:2])


def measure(alpha: np.ndarray, anchor_x: float, band_rows: tuple[float, float] | None = None) -> dict | None:
    """脚点与身高（像素，可为小数），定义见文件头。band_rows 给定时用这几行求脚点 x
    （同一动画同一朝向的各帧用同一条带，避免条带本身跳动）。"""
    H, W = alpha.shape
    x0 = max(0, int(round(anchor_x - BODY_WINDOW * W)))
    x1 = min(W, int(round(anchor_x + BODY_WINDOW * W)) + 1)
    win = alpha[:, x0:x1].astype(np.float64)
    rows = np.where((win >= ALPHA_OPAQUE).any(1))[0]
    if rows.size == 0:
        return None
    top, bottom = int(rows[0]), int(rows[-1])
    widths = win.sum(1)
    thr = 0.35 * widths[(top + bottom) // 2: bottom + 1].max()
    y = bottom
    while y > top and widths[y] < thr:
        y -= 1
    nxt = widths[y + 1] if y + 1 < H else 0.0
    base = y + 0.5 + (widths[y] - thr) / max(widths[y] - nxt, 1e-6)  # 宽度降到阈值的位置（亚像素）
    # 顶：第一行 alpha 总量的亚像素位置
    tops = win[top].sum() / max(win[top + 1].sum(), 1e-6) if top + 1 < H else 1.0
    top_f = top + 1 - min(1.0, tops)
    if band_rows is None:
        band_rows = (base - BASE_BAND * (base - top_f), base - FOOT_EXCLUDE_PX)
    r0, r1 = int(np.floor(band_rows[0])), int(np.ceil(band_rows[1]))
    band = win[max(r0, 0): max(r1, r0 + 1)]
    xs = np.arange(x0, x1) + 0.5
    wsum = band.sum()
    foot_x = float((band.sum(0) * xs).sum() / wsum) if wsum > 0 else float("nan")
    return {"foot_x": foot_x, "foot_y": float(base), "top": float(top_f), "height": float(base - top_f)}


def check_asset(asset_dir: Path) -> dict:
    asset_dir = Path(asset_dir)
    errors: list[str] = []
    warns: list[str] = []
    info: dict = {"asset": str(asset_dir)}

    meta_p = asset_dir / "meta.json"
    if not meta_p.exists():
        return {"ok": False, "errors": [f"缺少 meta.json：{meta_p}"], "warnings": [], "info": info}
    try:
        meta = json.loads(meta_p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        return {"ok": False, "errors": [f"meta.json 不是合法 JSON：{e}"], "warnings": [], "info": info}

    # ---- 1. meta 结构
    for key, typ in (("name", str), ("size", list), ("anchor", list), ("anims", dict), ("sockets", dict)):
        if not isinstance(meta.get(key), typ):
            errors.append(f"meta.{key} 缺失或类型不对（应为 {typ.__name__}）")
    if errors:
        return {"ok": False, "errors": errors, "warnings": warns, "info": info}
    W, H = meta["size"]
    want_anchor = S.PROP_ANCHOR if meta.get("category") == "prop" else S.ANCHOR
    if list(meta["anchor"]) != list(want_anchor):
        errors.append(f"meta.anchor = {meta['anchor']}，应为 {list(want_anchor)}（category={meta.get('category')}）")
    if W != H or W not in S.FRAME.values():
        warns.append(f"meta.size = {meta['size']}，不在 FRAME 规定的尺寸里")
    expected: list[tuple[str, str, int]] = []
    for an, a in meta["anims"].items():
        if not re.fullmatch(r"[a-z0-9]+", an):
            errors.append(f"动画名 {an!r} 只能用小写字母和数字")
        if not (isinstance(a.get("frames"), int) and a["frames"] >= 1):
            errors.append(f"anims.{an}.frames 必须是正整数")
            continue
        if not (isinstance(a.get("fps"), (int, float)) and a["fps"] > 0):
            errors.append(f"anims.{an}.fps 必须是正数")
        dirs = a.get("dirs")
        if not (isinstance(dirs, list) and dirs and all(d in S.DIRS for d in dirs)):
            errors.append(f"anims.{an}.dirs 必须是非空列表，取值在 {S.DIRS} 里")
            continue
        for d in dirs:
            for i in range(a["frames"]):
                expected.append((an, d, i))
    ax, ay = meta["anchor"][0] * W, meta["anchor"][1] * H
    pal = _pal(LIGHT_COLORS + list(meta.get("palette_extra", [])))
    floating = bool(meta.get("floating", False))

    # ---- 2/3. 文件、尺寸、边距
    present = {p.name for p in asset_dir.glob("*.png")}
    for p in sorted(present):
        if not FRAME_RE.match(p):
            warns.append(f"文件名不合约定，忽略：{p}")
    frames: dict = {}
    for an, d, i in expected:
        name = f"{an}_{d}_{i:02d}.png"
        if name not in present:
            errors.append(f"缺少帧：{name}")
            continue
        im = Image.open(asset_dir / name)
        if im.mode != "RGBA":
            errors.append(f"{name} 不是 RGBA（是 {im.mode}）")
            im = im.convert("RGBA")
        if im.size != (W, H):
            errors.append(f"{name} 尺寸 {im.size}，应为 {(W, H)}")
            continue
        arr = np.asarray(im)
        a = arr[..., 3]
        if a[0].any() or a[-1].any() or a[:, 0].any() or a[:, -1].any():
            errors.append(f"{name} 贴边：四周 1px 内有不透明像素")
        frames[(an, d, i)] = arr
        for suf in ("_emit", "_flash"):
            sp = asset_dir / f"{an}_{d}_{i:02d}{suf}.png"
            if sp.exists() and Image.open(sp).size != (W, H):
                errors.append(f"{sp.name} 尺寸不对")
    if not frames:
        errors.append("没有可检查的帧")
        return {"ok": False, "errors": errors, "warnings": warns, "info": info}

    # ---- 4/5. 脚点、身高
    ms = {k: measure(v[..., 3] / 255.0, ax) for k, v in frames.items()}
    # 第二遍：同一动画同一朝向用同一条带求脚点 x
    bases: dict = {}
    for (an, d, i), m in ms.items():
        if m:
            bases.setdefault((an, d), []).append((m["foot_y"], m["height"]))
    for k in list(ms):
        if ms[k] is None:
            continue
        b = np.array(bases[(k[0], k[1])])
        mb, mh = float(np.median(b[:, 0])), float(np.median(b[:, 1]))
        ms[k]["foot_x"] = measure(frames[k][..., 3] / 255.0, ax, (mb - BASE_BAND * mh, mb - FOOT_EXCLUDE_PX))["foot_x"]
    for k, m in ms.items():
        if m is None:
            errors.append(f"{k[0]}_{k[1]}_{k[2]:02d}.png 是空图")
    groups: dict = {}
    for (an, d, i), m in ms.items():
        if m:
            groups.setdefault((an, d), []).append(m)
    drift_max = 0.0
    for (an, d), lst in groups.items():
        fx = np.array([m["foot_x"] for m in lst])
        fy = np.array([m["foot_y"] for m in lst])
        dx = float(np.abs(fx - np.median(fx)).max())
        dy = 0.0 if floating else float(np.abs(fy - np.median(fy)).max())
        drift_max = max(drift_max, dx, dy)
        if dx > S.FOOT_TOLERANCE_PX or dy > S.FOOT_TOLERANCE_PX:
            errors.append(f"{an}_{d}：脚点漂移 x {dx:.2f}px / y {dy:.2f}px，超过 {S.FOOT_TOLERANCE_PX}px")
        if abs(float(np.median(fx)) - ax) > 3.0:
            warns.append(f"{an}_{d}：脚点 x 中位数 {np.median(fx):.1f}，离锚点 {ax:.1f} 超过 3px")
        if not floating and meta.get("category") != "prop" and abs(float(np.median(fy)) - ay) > 6.0:
            warns.append(f"{an}_{d}：底线 y 中位数 {np.median(fy):.1f}，离锚点 {ay:.1f} 超过 6px")
    heights = np.array([m["height"] for m in ms.values() if m])
    hmed = float(np.median(heights))
    bad = [(k, m["height"]) for k, m in ms.items() if m and abs(m["height"] - hmed) > S.HEIGHT_TOLERANCE * hmed]
    for k, h in bad:
        errors.append(f"{k[0]}_{k[1]}_{k[2]:02d}.png 身高 {h:.0f}px，离中位数 {hmed:.0f}px 超过 {S.HEIGHT_TOLERANCE:.0%}")
    if "height_px" in meta:
        tgt = float(meta["height_px"])
        h_model = hmed - S.LINE_OUTER_PX
        if abs(h_model - tgt) > S.HEIGHT_TOLERANCE * tgt:
            errors.append(f"身高中位数 {hmed:.1f}px（减去外线 {h_model:.1f}px）与目标 {tgt:.1f}px 相差超过 {S.HEIGHT_TOLERANCE:.0%}")
    info.update(foot_drift_max_px=round(drift_max, 2), height_median_px=round(hmed, 1),
                height_range_px=[round(float(heights.min()), 1), round(float(heights.max()), 1)])

    # ---- 6/7. 调色板、墨线占比
    shares, ratios = [], []
    for k, arr in frames.items():
        rgb, a = arr[..., :3], arr[..., 3]
        opaque = a >= 250
        if not opaque.any():
            continue
        lm = line_mask(rgb, pal) & opaque
        rest = opaque & ~lm
        ratio = float(lm.sum() / opaque.sum())
        ratios.append(ratio)
        if rest.any():
            dist = palette_distance(rgb[rest][:, None, :], pal)[:, 0]
            share = float((dist <= S.PALETTE_TOLERANCE).mean())
        else:
            share = 1.0
        shares.append(share)
        nm = f"{k[0]}_{k[1]}_{k[2]:02d}.png"
        if share < PALETTE_MIN_SHARE:
            errors.append(f"{nm}：非墨线像素只有 {share:.1%} 在调色板容差内（要求 ≥{PALETTE_MIN_SHARE:.0%}）")
        if not (LINE_RATIO_RANGE[0] <= ratio <= LINE_RATIO_RANGE[1]):
            errors.append(f"{nm}：墨线占不透明像素 {ratio:.1%}，不在 {LINE_RATIO_RANGE[0]:.0%}~{LINE_RATIO_RANGE[1]:.0%}")
    info.update(palette_share_min=round(min(shares), 3) if shares else None,
                line_ratio_range=[round(float(min(ratios)), 3), round(float(max(ratios)), 3)] if ratios else None)

    # ---- 8. 挂点
    for sname, by_anim in meta["sockets"].items():
        for an, a in meta["anims"].items():
            for d in a.get("dirs", []):
                lst = (by_anim.get(an) or {}).get(d)
                if not isinstance(lst, list) or len(lst) != a.get("frames"):
                    errors.append(f"挂点 {sname} 缺少 {an}/{d} 的逐帧坐标（应有 {a.get('frames')} 个）")
                    continue
                for xy in lst:
                    if not (isinstance(xy, list) and len(xy) == 2 and all(isinstance(v, (int, float)) for v in xy)):
                        errors.append(f"挂点 {sname} {an}/{d} 坐标格式不对：{xy}")
                        break
                    if not (-ax <= xy[0] <= W - ax and -ay <= xy[1] <= H - ay):
                        warns.append(f"挂点 {sname} {an}/{d} 在帧外：{xy}")
    for req in meta.get("required_sockets", []):
        if req not in meta["sockets"]:
            errors.append(f"缺少必需的挂点 {req}")
    info["frames_checked"] = len(frames)
    return {"ok": not errors, "errors": errors, "warnings": warns, "info": info}


def report(res: dict) -> str:
    i = res["info"]
    head = ("通过" if res["ok"] else "不通过") + f"  {i.get('asset')}"
    lines = [head]
    if "frames_checked" in i:
        lines.append(f"  帧数 {i['frames_checked']}；脚点最大漂移 {i.get('foot_drift_max_px')}px；"
                     f"身高中位数 {i.get('height_median_px')}px（范围 {i.get('height_range_px')}）；"
                     f"调色板内比例最低 {i.get('palette_share_min')}；墨线占比 {i.get('line_ratio_range')}")
    for e in res["errors"]:
        lines.append("  ✗ " + e)
    for w in res["warnings"]:
        lines.append("  ! " + w)
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    as_json = "--json" in argv
    dirs = [a for a in argv if not a.startswith("--")]
    if not dirs:
        print(__doc__)
        return 2
    results = [check_asset(Path(d)) for d in dirs]
    for r in results:
        print(report(r))
    if as_json:
        print(json.dumps(results, ensure_ascii=False, indent=1))
    return 0 if all(r["ok"] for r in results) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
