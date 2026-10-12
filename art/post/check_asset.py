"""素材自检：按 style.py 末尾的输出约定检查一个素材文件夹。

用法：
    art/.venv/bin/python art/post/check_asset.py art/out/style/assets/hero [更多文件夹...]
全部通过返回 0；有不通过的项返回 1，并打印中文报告。--json 时额外输出机器可读结果。

检查项：
  1. meta.json 结构：name/size/anchor/anims/sockets；每个动画有 frames/fps/dirs，朝向都在 DIRS 里；
     anchor：道具（category=prop）用 PROP_ANCHOR，大体型妖物（anchor_kind=big_enemy）用 BIG_ENEMY_ANCHOR，其余 ANCHOR；
     px_per_unit：素材的出图密度（缺省按 2，即 1 倍）。像素阈值（配准容差、外线宽、帧尺寸）都按
     素材自己的密度换算，所以 1 倍和 2 倍的文件夹用同一个脚本、任何环境变量下都能检查
  2. 每个 <动画>_<朝向>_<帧号>.png 都存在、是 RGBA、尺寸等于 meta.size；附带的 _emit/_flash 图尺寸一致
  3. 四周至少 1px 完全透明（不能贴边）
  4. 脚底漂移：同一动画同一朝向的各帧，“脚点”离中位数不超过 FOOT_TOLERANCE_PX
  5. 身高：各帧身高离“同一动画同一朝向”的中位数不超过 HEIGHT_TOLERANCE；全素材中位数和 meta.height_px
     （有的话）比；某个朝向整体偏离全素材中位数只给警告（道具可能高过头顶）
  6. 调色板：不透明的非墨线像素里，≥90% 离调色板（full_palette + 发光色）在 PALETTE_TOLERANCE 以内
  7. 墨线占比：在合理范围 LINE_RATIO_RANGE 内
  8. 挂点：meta.sockets 里每个挂点都覆盖每个动画、每个朝向、每一帧

“配准漂移”（检查项 4，沿用 FOOT_TOLERANCE_PX）：
  原先按“脚底”测，但真正迈步的腿（主角跑动每轮前进 3.2 米，着地脚相对身体前后各约 0.3 米，S 向画面上
  就是上下约 ±7px）和飘动的衣摆会让任何“按脚”量出来的点本身就在动，量不出贴图有没有错位。
  现在量的是身体的配准点：
  - y：锚点正上方窄列（±TOP_WINDOW×宽）里最高的不透明像素（冠顶/帽尖），亚像素
  - x：同一窄列里，锚点以上身高 40%~62% 的躯干条带的 alpha 加权重心（同组各帧用同一条带）
  同一动画同一朝向各帧离中位数不超过 FOOT_TOLERANCE_PX；悬浮素材（floating）只查 x；
  只播一次的动画（meta anims.<名>.loop=false，主角死亡）不查配准；
  vertical_motion（跳跃等本来就大幅上下的动画）也只查 x，并且不查逐帧身高。
“着地”：非悬浮、非道具素材，锚点附近最低的不透明像素要在锚点上方 6% 身高到下方 10% 帧高之间
  （脚没飘起来、没沉下去；跑动时前脚在 S 向画面上会比锚点低几个像素，属正常）。
“身高”：锚点（地面）到冠顶的距离。逐帧和同组中位数比（HEIGHT_TOLERANCE）；全素材中位数减半个外线宽后
  和 meta.height_px 比；某个朝向整体偏离只给警告（道具可能高过头顶）。
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
LINE_RATIO_RANGE = (0.05, 0.65)  # 主角墨氅背面（W/NW）墨色本来就多，上限 65%
BODY_WINDOW = 0.15  # 中间列半宽（相对帧宽）：求底线、脚点
TOP_WINDOW = 0.06  # 求“头顶”时用更窄的列（头顶/冠就在锚点正上方，两侧摆动的灯笼不算）
BASE_BAND = 0.12
ALPHA_OPAQUE = 0.5
LINE_NEAR = 10.0  # 离墨线色这么近就算纯墨
BAND = (0.40, 0.62)  # 躯干条带：锚点以上身高的 40%~62%（腰到胸），求配准点 x
GROUND_BAND = (-0.06, 0.10)  # 着地检查：最低的不透明像素应在锚点上方 6% 身高到下方 10% 帧高之间
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


def measure(alpha: np.ndarray, anchor_x: float, anchor_y: float, band_rows: tuple[float, float] | None = None) -> dict | None:
    """一帧的“配准点”和身高（像素，可为小数），定义见文件头。
    band_rows 给定时用这几行求躯干重心 x（同一动画同一朝向的各帧用同一条带）。"""
    H, W = alpha.shape
    x0 = max(0, int(round(anchor_x - BODY_WINDOW * W)))
    x1 = min(W, int(round(anchor_x + BODY_WINDOW * W)) + 1)
    win = alpha[:, x0:x1].astype(np.float64)
    rows = np.where((win >= ALPHA_OPAQUE).any(1))[0]
    if rows.size == 0:
        return None
    bottom = int(rows[-1])
    # 顶：锚点正上方窄列里第一个不透明行，按该行 alpha 总量取亚像素位置
    t0 = max(0, int(round(anchor_x - TOP_WINDOW * W)))
    t1 = min(W, int(round(anchor_x + TOP_WINDOW * W)) + 1)
    tw = alpha[:, t0:t1].astype(np.float64)
    trows = np.where((tw >= ALPHA_OPAQUE).any(1))[0]
    top = int(trows[0]) if trows.size else int(rows[0])
    tops = tw[top].sum() / max(tw[top + 1].sum(), 1e-6) if top + 1 < H else 1.0
    top_f = top + 1 - min(1.0, tops)
    height = anchor_y - top_f
    if band_rows is None:
        band_rows = (anchor_y - BAND[1] * height, anchor_y - BAND[0] * height)
    r0, r1 = int(np.floor(band_rows[0])), int(np.ceil(band_rows[1]))
    band = tw[max(r0, 0): max(r1, r0 + 1)]
    xs = np.arange(t0, t1) + 0.5
    wsum = band.sum()
    reg_x = float((band.sum(0) * xs).sum() / wsum) if wsum > 0 else float("nan")
    return {"reg_x": reg_x, "reg_y": float(top_f), "height": float(height), "bottom": float(bottom + 1)}


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
    if meta.get("category") == "prop":
        want_anchor = S.PROP_ANCHOR
    elif meta.get("anchor_kind") == "big_enemy":
        want_anchor = S.BIG_ENEMY_ANCHOR
    else:
        want_anchor = S.ANCHOR
    if list(meta["anchor"]) != list(want_anchor):
        errors.append(f"meta.anchor = {meta['anchor']}，应为 {list(want_anchor)}（category={meta.get('category')}）")
    ppu = float(meta.get("px_per_unit", 2.0))
    if "px_per_unit" not in meta:
        warns.append("meta 缺少 px_per_unit，按 2（1 倍密度）处理")
    k = ppu / S.PX_PER_UNIT  # 素材密度 / 当前环境密度
    foot_tol = S.FOOT_TOLERANCE_PX * k
    line_outer = S.LINE_OUTER_PX * k
    info["px_per_unit"] = ppu
    if W != H or W not in [round(v * k) for v in S.FRAME.values()]:
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
    # vertical_motion：动画本身就上下大幅移动（金蟾跳跃），只查 x 配准，不查逐帧身高和着地
    vmotion = bool(meta.get("vertical_motion", False))
    floating = floating or vmotion

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

    # ---- 4/5. 配准漂移、身高、着地
    ms = {k: measure(v[..., 3] / 255.0, ax, ay) for k, v in frames.items()}
    for k, m in ms.items():
        if m is None:
            errors.append(f"{k[0]}_{k[1]}_{k[2]:02d}.png 是空图")
    groups: dict = {}
    for (an, d, i), m in ms.items():
        if m:
            groups.setdefault((an, d), []).append(((an, d, i), m))
    drift_max = 0.0
    for (an, d), lst in groups.items():
        gh = float(np.median([m["height"] for _, m in lst]))
        band = (ay - BAND[1] * gh, ay - BAND[0] * gh)  # 同组用同一条带
        for k, m in lst:
            m["reg_x"] = measure(frames[k][..., 3] / 255.0, ax, ay, band)["reg_x"]
        fx = np.array([m["reg_x"] for _, m in lst])
        fy = np.array([m["reg_y"] for _, m in lst])
        # 单个动画也可以声明 vertical_motion（主角死亡倒地），该动画同样只查 x
        g_vm = vmotion or bool(meta["anims"].get(an, {}).get("vertical_motion"))
        g_float = floating or g_vm
        one_shot = meta["anims"].get(an, {}).get("loop") is False  # 只播一次的动画（死亡）不要求逐帧配准
        dx = 0.0 if one_shot else float(np.abs(fx - np.median(fx)).max())
        dy = 0.0 if (g_float or one_shot) else float(np.abs(fy - np.median(fy)).max())
        drift_max = max(drift_max, dx, dy)
        if dx > foot_tol or dy > foot_tol:
            errors.append(f"{an}_{d}：配准漂移 x {dx:.2f}px / y {dy:.2f}px，超过 {foot_tol:g}px")
        for k, m in lst:
            if not g_vm and abs(m["height"] - gh) > S.HEIGHT_TOLERANCE * gh:
                errors.append(f"{an}_{d}_{k[2]:02d}.png 身高 {m['height']:.0f}px，离本组中位数 {gh:.0f}px 超过 {S.HEIGHT_TOLERANCE:.0%}")
            if not g_float and meta.get("category") != "prop":
                lo = ay - abs(GROUND_BAND[0]) * gh
                hi = ay + max(GROUND_BAND[1] * H, 0.9 * (H - ay))  # 锚点下方的空间可以用（朝镜头的拳脚），贴边另有检查
                if not (lo <= m["bottom"] <= hi):
                    errors.append(f"{an}_{d}_{k[2]:02d}.png 着地异常：最低点 y={m['bottom']:.0f}，应在 {lo:.0f}~{hi:.0f}")
        groups[(an, d)] = [m for _, m in lst]
    heights = np.array([m["height"] for m in ms.values() if m])
    hmed = float(np.median(heights))
    # 各朝向的中位数和全素材中位数比只给警告——有些朝向里灯杖、灯笼正好在头顶后方
    for (an, d), lst in groups.items():
        gmed = float(np.median([m["height"] for m in lst]))
        if abs(gmed - hmed) > S.HEIGHT_TOLERANCE * hmed:
            warns.append(f"{an}_{d}：剪影高 {gmed:.0f}px，与全素材中位数 {hmed:.0f}px 不同（多半是道具高过头顶，请目检）")
    if "height_px" in meta:
        tgt = float(meta["height_px"])
        h_model = hmed - line_outer / 2
        if abs(h_model - tgt) > S.HEIGHT_TOLERANCE * tgt:
            errors.append(f"身高中位数 {hmed:.1f}px（减去半个外线宽 {h_model:.1f}px）与目标 {tgt:.1f}px 相差超过 {S.HEIGHT_TOLERANCE:.0%}")
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
