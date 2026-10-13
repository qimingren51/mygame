"""灯笼拆层的样张与审图（主角底图 + 灯笼叠层）。

    art/.venv/bin/python art/render/lantern_review.py sample   # 渲样张（几帧主角 + 三盏灯叠层 + 货郎、暗石灯笼）并出审图
    art/.venv/bin/python art/render/lantern_review.py review   # 不渲染，只重出样张的审图
    art/.venv/bin/python art/render/lantern_review.py full     # 正式素材（assets@2x，produce.py 渲完之后）的审图

样张帧：idle S/E/N/NW 第 0 帧、walk E 第 0–3 帧，渲到 art/out/lantern_sample@2x/（不动正式的 assets@2x/hero）。
两件道具直接渲到正式目录（新素材）。审图写到 art/out/review@2x/：
  lantern_sample.png   每盏灯：主角 + 叠层合成（宣纸底、夜景用该灯光色），1 倍和灯笼附近 3 倍；叠层单独放在棋盘格上
  lantern_diff.png     旧的单遍主角帧（_hero_before_split/）对比 底图 + 红纸灯叠层，差异热图；数字在 lantern_diff.json
  props_sample.png     货郎担、暗石灯笼、亮石灯笼，白天和夜里，1 倍和 3 倍
full（正式素材）写到同一个审图目录：
  lantern_<灯>_<动画>_8dir.gif / _night.gif   每盏灯 walk、idle、dash、death 的 8 向动图（主角 + 叠层；夜里用该灯光色）
  lantern_lineup_night.png / _day.png         三盏灯并排（2 倍素材原大），上排 idle S、下排 walk N
  lantern_diff_full.png / .json               全部 208 帧：旧单遍帧 vs 底图 + 红纸灯，按动画 × 朝向汇总、最差的帧
  lantern_check_report.json                   主角、三份叠层、货郎担、暗石灯笼的自检
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ART = Path(__file__).resolve().parents[1]
for p in (ART, ART / "models", ART / "post", ART / "render"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import numpy as np  # noqa: E402
from PIL import Image, ImageDraw, ImageFilter  # noqa: E402

from style import style as S  # noqa: E402
import check_asset as C  # noqa: E402
import contact_sheet as CS  # noqa: E402

D = S.DENSITY
OUT = ART / "out"
ASSETS = OUT / S.ASSETS_DIR_NAME
SAMPLE = OUT / ("lantern_sample" if D == 1 else f"lantern_sample@{D:g}x")
OLD_HERO = ASSETS / "_hero_before_split"
REVIEW = OUT / ("review" if D == 1 else f"review@{D:g}x")
LAMPS = ("red", "mirror", "frost")
SAMPLE_JOBS = [("idle", d, 0, 6) for d in ("S", "E", "N", "NW")] + [("walk", "E", i, 8) for i in range(4)]
CROP = int(42 * D)  # 3 倍放大时灯笼附近取的半边长（像素）


def sample_keys() -> list[str]:
    seen: dict = {}
    keys = []
    for an, d, _i, _n in SAMPLE_JOBS:
        k = seen[(an, d)] = seen.get((an, d), -1) + 1
        keys.append(f"{an}_{d}_{k:02d}")
    return keys


# ================================================================ 渲染
def render_sample(timings: dict) -> None:
    import produce as PR

    PR.render_hero(SAMPLE_JOBS, SAMPLE, timings=timings, lamps=LAMPS)
    for n in ("merchant", "stone_lantern_dark"):
        PR.produce(n, timings)


# ================================================================ 小工具
def _font(size: int):
    try:
        from ui_fonts import font
        return font("serif", size, weight=500)
    except Exception:  # noqa: BLE001
        from PIL import ImageFont
        return ImageFont.load_default()


def label(im: Image.Image, xy, text: str, size: int = int(11 * D), color=S.INK["nong"]):
    ImageDraw.Draw(im).text(xy, text, fill=CS.rgb(color) + (255,), font=_font(size))


def checker(w: int, h: int, cell: int = int(8 * D)) -> Image.Image:
    yy, xx = np.mgrid[0:h, 0:w]
    a = ((xx // cell + yy // cell) % 2).astype(np.uint8)
    rgb = np.where(a[..., None] == 1, np.array([200, 200, 200], np.uint8), np.array([235, 235, 235], np.uint8))
    return Image.fromarray(rgb.astype(np.uint8), "RGB").convert("RGBA")


def crop_box(cx: float, cy: float, W: int, H: int, r: int = CROP) -> tuple[int, int, int, int]:
    """以 (cx, cy) 为中心、半边长 r 的方框，挪进帧内（不取到帧外的黑边）。"""
    x0 = int(min(max(cx - r, 0), W - 2 * r))
    y0 = int(min(max(cy - r, 0), H - 2 * r))
    return x0, y0, x0 + 2 * r, y0 + 2 * r


def frame(asset_dir: Path, key: str) -> tuple[Image.Image, Image.Image | None]:
    im = Image.open(asset_dir / f"{key}.png").convert("RGBA")
    ep = asset_dir / f"{key}_emit.png"
    return im, (Image.open(ep).convert("RGBA") if ep.exists() else None)


def socket(meta: dict, key: str, name: str = "lantern") -> tuple[float, float]:
    an, d, i = key.split("_")
    return tuple(meta["sockets"][name][an][d][int(i)])


def lit(day: Image.Image, emit_ims: list, lights) -> Image.Image:
    """宣纸底的白天图 + 发光层 → 夜景（contact_sheet.night_composite）。"""
    em = np.zeros((day.height, day.width, 3), np.float32)
    for e in emit_ims:
        if e is not None:
            a = np.asarray(e, np.float32) / 255.0
            em += a[..., :3] * a[..., 3:4]
    return CS.night_composite(day, em, lights)


def strip(tiles: list[Image.Image], gap: int = int(4 * D), bg=S.PAPER) -> Image.Image:
    w = sum(t.width for t in tiles) + gap * (len(tiles) - 1)
    h = max(t.height for t in tiles)
    out = Image.new("RGB", (w, h), CS.rgb(bg))
    x = 0
    for t in tiles:
        out.paste(t.convert("RGB"), (x, 0))
        x += t.width + gap
    return out


def stack(blocks: list[tuple[str | None, Image.Image]], pad: int = int(6 * D), title_h: int = int(16 * D)) -> Image.Image:
    w = max(b.width for _, b in blocks) + 2 * pad
    h = sum(b.height + (title_h if t else 0) + pad for t, b in blocks) + pad
    out = Image.new("RGB", (w, h), CS.rgb(S.PAPER))
    y = pad
    for t, b in blocks:
        if t:
            label(out, (pad, y), t)
            y += title_h
        out.paste(b, (pad, y))
        y += b.height + pad
    return out


# ================================================================ 审图 1：每盏灯的合成样张
def lamp_sheet() -> Image.Image:
    hero_dir = SAMPLE / "hero"
    hmeta = json.loads((hero_dir / "meta.json").read_text(encoding="utf-8"))
    W, H = hmeta["size"]
    ax, ay = hmeta["anchor"][0] * W, hmeta["anchor"][1] * H
    keys = sample_keys()
    blocks = []
    for lid in LAMPS:
        odir = SAMPLE / f"lantern_{lid}"
        ometa = json.loads((odir / "meta.json").read_text(encoding="utf-8"))
        col = ometa["light_color"]
        day1, night1, raw1, day3, night3, dark3 = [], [], [], [], [], []
        for k in keys:
            base, _ = frame(hero_dir, k)
            ov, em = frame(odir, k)
            comp = base.copy()
            comp.alpha_composite(ov)
            day = CS.paper(W, H, seed=2)
            day.alpha_composite(comp)
            sx, sy = socket(hmeta, k)
            lx, ly = ax + sx, ay + sy
            night = lit(day, [em], [(lx, ly, CS.LIGHT_RADIUS_PX, col)])
            raw = checker(W, H)
            raw.alpha_composite(ov)
            label(raw, (int(3 * D), int(2 * D)), k, color=S.INK["dan"])
            day1.append(day)
            night1.append(night)
            raw1.append(raw)
            box = crop_box(lx, ly, W, H)
            day3.append(CS.zoom(day.convert("RGB").crop(box), 3))
            night3.append(CS.zoom(night.crop(box), 3))
            dark3.append(CS.zoom(lit(day, [em], []).crop(box), 3))
        name = ometa.get("lamp_name", lid)
        blocks += [(f"{name}（{lid}）  光色 {col}  —  主角底图 + 叠层，宣纸底，1 倍", strip(day1)),
                   (f"{name}  夜里（光源在 lantern 挂点，光色 {col}，叠加 _emit）", strip(night1)),
                   (f"{name}  叠层单独（棋盘格）", strip(raw1)),
                   (f"{name}  灯笼附近 3 倍：白天", strip(day3)),
                   (f"{name}  灯笼附近 3 倍：夜里（同上一排的光）", strip(night3)),
                   (f"{name}  灯笼附近 3 倍：只有夜色环境光 + 发光层（看 _emit 本身）", strip(dark3))]
    return stack(blocks)


# ================================================================ 审图 2：旧单遍帧 vs 底图 + 红纸灯
DIFF_HEAD = ("列：旧单遍帧 | 底图+红纸灯叠层 | 差异热图（黑 0，红 32/255，黄 ≥64/255；淡蓝圈 = 灯笼 4px 范围）"
             " | 灯笼附近 2 倍：旧 | 新 | 热图")


def diff_frame(old: Image.Image, base: Image.Image, ov: Image.Image, paper: np.ndarray) -> tuple[dict, Image.Image]:
    """旧单遍帧 vs 底图 + 叠层：比较铺在宣纸上的颜色和 alpha（全透明像素里扩出来的颜色不算）。
    返回统计和热图（0 → 黑，32/255 → 红，≥64/255 → 黄；灯笼 4px 范围描一圈淡蓝）。"""
    new = base.copy()
    new.alpha_composite(ov)
    o, n = np.asarray(old, np.float32), np.asarray(new, np.float32)

    def on_paper(a):
        al = a[..., 3:4] / 255.0
        return a[..., :3] * al + paper * (1 - al)

    d = np.maximum(np.abs(on_paper(o) - on_paper(n)).max(-1), np.abs(o[..., 3] - n[..., 3]))
    near_r = int(4 * D)  # 灯笼附近：叠层（不透明部分）向外扩 4px（2 倍密度）
    ova = np.asarray(ov, np.float32)[..., 3] > 0
    near = np.asarray(Image.fromarray((ova * 255).astype(np.uint8)).filter(ImageFilter.MaxFilter(2 * near_r + 1)), bool)
    gt8 = d > 8
    nonempty = (o[..., 3] > 0) | (n[..., 3] > 0)
    f = {"max": int(d.max()), "mean_all": round(float(d.mean()), 4),
         "mean_nonempty": round(float(d[nonempty].mean()), 3) if nonempty.any() else 0.0,
         "px_gt8": int(gt8.sum()), "px_gt8_near_lantern": int((gt8 & near).sum()),
         "px_gt8_elsewhere": int((gt8 & ~near).sum()), "sum": float(d.sum()), "n": int(d.size)}
    t = np.clip(d / 64.0, 0, 1)
    heat = np.stack([np.clip(t * 2, 0, 1), np.clip(t * 2 - 1, 0, 1), np.zeros_like(t)], -1) * 255
    edge = near & ~np.asarray(Image.fromarray((near * 255).astype(np.uint8)).filter(ImageFilter.MinFilter(3)), bool)
    heat[edge] = [70, 110, 160]
    return f, Image.fromarray(heat.astype(np.uint8), "RGB")


def diff_row(key, old, base, ov, heat_im, f, hmeta) -> tuple[str, Image.Image]:
    W, H = hmeta["size"]
    ax, ay = hmeta["anchor"][0] * W, hmeta["anchor"][1] * H
    new = base.copy()
    new.alpha_composite(ov)
    tiles = []
    for im in (old, new):
        bg = CS.paper(W, H, seed=2)
        bg.alpha_composite(im)
        tiles.append(bg.convert("RGB"))
    tiles.append(heat_im)
    sx, sy = socket(hmeta, key)
    box = crop_box(ax + sx, ay + sy, W, H)
    tiles += [CS.zoom(tiles[0].crop(box), 2), CS.zoom(tiles[1].crop(box), 2), CS.zoom(heat_im.crop(box), 2)]
    cap = (f"{key}: 最大 {f['max']}/255，平均 {f['mean_all']:.3f}（非空 {f['mean_nonempty']:.2f}），"
           f">8/255 的像素 {f['px_gt8']}（灯笼 4px 内 {f['px_gt8_near_lantern']}，其它 {f['px_gt8_elsewhere']}）")
    return cap, strip(tiles, bg=S.INK["jiao"])


def total_of(fs: list[dict]) -> dict:
    return {"frames": len(fs), "max": max(f["max"] for f in fs),
            "mean_all": round(sum(f["sum"] for f in fs) / max(sum(f["n"] for f in fs), 1), 4),
            "px_gt8": sum(f["px_gt8"] for f in fs), "px_gt8_near_lantern": sum(f["px_gt8_near_lantern"] for f in fs),
            "px_gt8_elsewhere": sum(f["px_gt8_elsewhere"] for f in fs)}


def diff_sheet() -> tuple[Image.Image, dict]:
    hero_dir, red_dir = SAMPLE / "hero", SAMPLE / "lantern_red"
    hmeta = json.loads((hero_dir / "meta.json").read_text(encoding="utf-8"))
    W, H = hmeta["size"]
    paper = np.asarray(CS.paper(W, H, seed=2).convert("RGB"), np.float32)
    rows, stats = [], {"frames": {}}
    for k in sample_keys():
        old, base, ov = frame(OLD_HERO, k)[0], frame(hero_dir, k)[0], frame(red_dir, k)[0]
        f, heat_im = diff_frame(old, base, ov, paper)
        stats["frames"][k] = {a: b for a, b in f.items() if a not in ("sum", "n")}
        rows.append(diff_row(k, old, base, ov, heat_im, f, hmeta))
        stats.setdefault("_all", []).append(f)
    stats["total"] = total_of(stats.pop("_all"))
    return stack([(DIFF_HEAD, Image.new("RGB", (10, 1), CS.rgb(S.PAPER)))] + rows), stats


# ================================================================ 第二阶段：正式素材的审图
COMPASS = ["NW", "N", "NE", "W", None, "E", "SW", "S", "SE"]  # 按屏幕方位排的 3×3
GIF_ANIMS = ("walk", "idle", "dash", "death")


def all_keys(meta: dict) -> list[str]:
    return [f"{an}_{d}_{i:02d}" for an, a in meta["anims"].items() for d in a["dirs"] for i in range(a["frames"])]


def lamp_gifs() -> list[Path]:
    """每盏灯、每个动画一张 8 向动图（3×3 方位格，中间空），宣纸底一张、夜里（该灯光色）一张，2 倍原大。"""
    hero_dir = ASSETS / "hero"
    hmeta = json.loads((hero_dir / "meta.json").read_text(encoding="utf-8"))
    W, H = hmeta["size"]
    ax, ay = hmeta["anchor"][0] * W, hmeta["anchor"][1] * H
    pad, lab = int(4 * D), int(10 * D)
    cols = 3
    gw, gh = cols * (W + pad) + pad, 3 * (H + pad + lab) + pad
    paths = []
    for lid in LAMPS:
        odir = ASSETS / f"lantern_{lid}"
        col = json.loads((odir / "meta.json").read_text(encoding="utf-8"))["light_color"]
        for an in GIF_ANIMS:
            a = hmeta["anims"][an]
            days, nights = [], []
            for i in range(a["frames"]):
                day = CS.paper(gw, gh, seed=2)
                emit = np.zeros((gh, gw, 3), np.float32)
                lights = []
                for k, d in enumerate(COMPASS):
                    if d is None:
                        continue
                    key = f"{an}_{d}_{i:02d}"
                    x, y = pad + (k % cols) * (W + pad), pad + (k // cols) * (H + pad + lab) + lab
                    base, _ = frame(hero_dir, key)
                    ov, em = frame(odir, key)
                    day.alpha_composite(base, (x, y))
                    day.alpha_composite(ov, (x, y))
                    label(day, (x + int(2 * D), y - lab), d, size=int(8 * D), color=S.INK["dan"])
                    if em is not None:
                        e = np.asarray(em, np.float32) / 255.0
                        emit[y:y + H, x:x + W] += e[..., :3] * e[..., 3:4]
                    sx, sy = socket(hmeta, key)
                    lights.append((x + ax + sx, y + ay + sy, CS.LIGHT_RADIUS_PX, col))
                days.append(day.convert("RGB"))
                nights.append(CS.night_composite(day, emit, lights))
            fps = a["fps"]
            for tag, frames in (("", days), ("_night", nights)):
                path = REVIEW / f"lantern_{lid}_{an}_8dir{tag}.gif"
                CS.gif(frames, path, fps, zoom_k=1)
                paths.append(path)
    return paths


def lineup() -> Path:
    """三盏灯并排的夜景（游戏原大，2 倍素材 1:1）：上排 idle S、下排 walk N（背面，铜镜灯的灯芯在镜子后面）；
    宣纸地面上有几块水墨斑，几只影妖、山石在光圈之间；各灯用自己的光色。另存一张白天的。"""
    names = ["hero", "shade", "rock_a", "rock_b", "stone_lantern_dark"]
    A = {n: CS.load_asset(ASSETS / n) for n in names if (ASSETS / n / "meta.json").exists()}
    O = {lid: CS.load_asset(ASSETS / f"lantern_{lid}") for lid in LAMPS}
    hmeta = A["hero"]["meta"]
    R = CS.LIGHT_RADIUS_PX
    w, h = int(3 * 2.3 * R), int(2 * 1.25 * R + 40 * D)
    day = CS.paper(w, h, seed=13, blotches=9)
    emit = np.zeros((h, w, 3), np.float32)
    lights = []
    items = []
    for row, key in enumerate(("idle_S_00", "walk_N_02")):
        for j, lid in enumerate(LAMPS):
            at = (w * (j + 0.5) / 3, int(26 * D) + (row + 0.78) * 1.25 * R)
            hf = next(f for f in A["hero"]["frames"] if f["key"] == key)
            of = next(f for f in O[lid]["frames"] if f["key"] == key)
            comp = hf["rgba"].copy()
            comp.alpha_composite(of["rgba"])
            items.append((dict(hf, rgba=comp, emit=of["emit"]), hmeta, at))
            sx, sy = hf["sockets"]["lantern"]
            lights.append((at[0] + sx, at[1] + sy, R, O[lid]["meta"]["light_color"]))
            if row == 0:
                label(day, (int(at[0] - 40 * D), int(4 * D)), f"{O[lid]['meta']['lamp_name']} {O[lid]['meta']['light_color']}")
    if "shade" in A:  # 光圈边上几只影妖、几块石头
        sh = A["shade"]["frames"][0]
        for x, y in ((w / 3, h * 0.30), (2 * w / 3, h * 0.82), (w * 0.95, h * 0.35)):
            items.append((sh, A["shade"]["meta"], (x, y)))
    for n, (x, y) in (("rock_a", (w * 0.04, h * 0.88)), ("rock_b", (w / 3, h * 0.92)), ("stone_lantern_dark", (2 * w / 3, h * 0.36))):
        if n in A:
            items.append((A[n]["frames"][0], A[n]["meta"], (x, y)))
    for f, meta, at in sorted(items, key=lambda it: it[2][1]):
        CS.place(day, f, meta, at)
        CS.place_emit(emit, f, meta, at)
    night = CS.night_composite(day, emit, lights)
    night.save(REVIEW / "lantern_lineup_night.png")
    day.convert("RGB").save(REVIEW / "lantern_lineup_day.png")
    return REVIEW / "lantern_lineup_night.png"


def diff_full() -> dict:
    """全部 208 帧：旧单遍帧（_hero_before_split）vs 正式底图 + 红纸灯叠层。按动画、朝向汇总，列出最差的帧，
    最差的 8 帧画成对比图。"""
    hero_dir, red_dir = ASSETS / "hero", ASSETS / "lantern_red"
    hmeta = json.loads((hero_dir / "meta.json").read_text(encoding="utf-8"))
    W, H = hmeta["size"]
    paper = np.asarray(CS.paper(W, H, seed=2).convert("RGB"), np.float32)
    per: dict = {}
    for k in all_keys(hmeta):
        f, _ = diff_frame(frame(OLD_HERO, k)[0], frame(hero_dir, k)[0], frame(red_dir, k)[0], paper)
        per[k] = f
    by_anim_dir = {}
    for an, a in hmeta["anims"].items():
        by_anim_dir[an] = {"all": total_of([per[k] for k in per if k.startswith(an + "_")])}
        for d in a["dirs"]:
            by_anim_dir[an][d] = total_of([per[k] for k in per if k.startswith(f"{an}_{d}_")])
    worst = sorted(per, key=lambda k: (per[k]["px_gt8_elsewhere"], per[k]["px_gt8"]), reverse=True)[:12]
    clean = {k: {a: b for a, b in f.items() if a not in ("sum", "n")} for k, f in per.items()}
    out = {"total": total_of(list(per.values())), "by_anim_dir": by_anim_dir,
           "worst_frames": [{"key": k, **clean[k]} for k in worst], "frames": clean}
    (REVIEW / "lantern_diff_full.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    # 图：动画 × 朝向的 >8/255 像素数表格 + 最差 8 帧
    cell_w, cell_h = int(64 * D), int(16 * D)
    dirs = list(S.DIRS)
    table = Image.new("RGB", (cell_w * (len(dirs) + 2), cell_h * (len(hmeta["anims"]) + 1)), CS.rgb(S.PAPER))
    for j, d in enumerate(["动画"] + dirs + ["全部"]):
        label(table, (j * cell_w + int(3 * D), int(2 * D)), d)
    for i, an in enumerate(hmeta["anims"]):
        label(table, (int(3 * D), (i + 1) * cell_h + int(2 * D)), an)
        for j, d in enumerate(dirs + ["all"]):
            t = by_anim_dir[an][d]
            x0, y0 = (j + 1) * cell_w, (i + 1) * cell_h
            k = min(1.0, t["px_gt8_elsewhere"] / max(80 * t["frames"], 1))
            ImageDraw.Draw(table).rectangle([x0 + 1, y0 + 1, x0 + cell_w - 2, y0 + cell_h - 2],
                                            fill=CS.rgb(S.mix(S.PAPER, S.ACCENT["zhusha"], 0.6 * k)))
            label(table, (x0 + int(3 * D), y0 + int(2 * D)), f"{t['px_gt8_near_lantern']}+{t['px_gt8_elsewhere']}")
    rows = [("每格：>8/255 的像素数（灯笼 4px 内 + 其它），整个动画 × 朝向所有帧加起来；底色越红“其它”越多", table)]
    for k in worst[:8]:
        old, base, ov = frame(OLD_HERO, k)[0], frame(hero_dir, k)[0], frame(red_dir, k)[0]
        f, heat_im = diff_frame(old, base, ov, paper)
        rows.append(diff_row(k, old, base, ov, heat_im, f, hmeta))
    stack([(DIFF_HEAD, Image.new("RGB", (10, 1), CS.rgb(S.PAPER)))] + rows).save(REVIEW / "lantern_diff_full.png")
    return out


def full_checks() -> list[dict]:
    names = ["hero", *(f"lantern_{lid}" for lid in LAMPS), "merchant", "stone_lantern_dark"]
    res = [C.check_asset(ASSETS / n) for n in names]
    for r in res:
        print(C.report(r))
    (REVIEW / "lantern_check_report.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    return res


# ================================================================ 审图 3：道具
def props_sheet() -> Image.Image:
    names = ["merchant", "stone_lantern_dark", "stone_lantern"]
    A = {n: CS.load_asset(ASSETS / n) for n in names}
    W, H = A[names[0]]["meta"]["size"]
    gap = int(10 * D)
    w, h = len(names) * (W + gap) + gap, H + gap
    day = CS.paper(w, h, seed=11)
    emit = np.zeros((h, w, 3), np.float32)
    lights = []
    for j, n in enumerate(names):
        f = A[n]["frames"][0]
        ax, ay = CS.anchor_px(A[n]["meta"])
        at = (gap + j * (W + gap) + ax, gap // 2 + ay)
        CS.place(day, f, A[n]["meta"], at)
        CS.place_emit(emit, f, A[n]["meta"], at)
        if f.get("emit") is not None:
            for sn, (rad, col) in CS.SOCKET_LIGHTS.items():
                if sn in f["sockets"]:
                    sx, sy = f["sockets"][sn]
                    lights.append((at[0] + sx, at[1] + sy, rad, col))
    d1 = day.convert("RGB")
    n1 = CS.night_composite(day, emit, lights)
    blocks = [("货郎担 merchant | 石灯笼（未点亮）stone_lantern_dark | 石灯笼（点亮）stone_lantern —— 白天 1 倍", d1),
              ("夜里（有 _emit 的道具在 flame 挂点放火光）", n1),
              ("白天 3 倍", CS.zoom(d1, 3)), ("夜里 3 倍", CS.zoom(n1, 3))]
    return stack(blocks)


# ================================================================ 自检
def run_checks() -> list[dict]:
    res = [C.check_asset(SAMPLE / "hero")] + [C.check_asset(SAMPLE / f"lantern_{lid}") for lid in LAMPS]
    res += [C.check_asset(ASSETS / n) for n in ("merchant", "stone_lantern_dark")]
    for r in res:
        print(C.report(r))
    return res


def main(argv: list[str]) -> int:
    t0 = time.perf_counter()
    timings: dict = {}
    if argv and argv[0] == "full":  # 第二阶段：正式素材（assets@2x）的审图、全帧对比、自检
        REVIEW.mkdir(parents=True, exist_ok=True)
        res = full_checks()
        out = diff_full()
        print("全部帧对比：", json.dumps(out["total"], ensure_ascii=False))
        for w_ in out["worst_frames"][:6]:
            print("  ", w_["key"], {k: w_[k] for k in ("max", "px_gt8", "px_gt8_near_lantern", "px_gt8_elsewhere")})
        print("夜景并排：", lineup())
        print("动图：", len(lamp_gifs()))
        print(f"共 {time.perf_counter() - t0:.1f}s")
        return 0 if all(r["ok"] for r in res) else 1
    if argv and argv[0] == "sample":
        render_sample(timings)
    REVIEW.mkdir(parents=True, exist_ok=True)
    lamp_sheet().save(REVIEW / "lantern_sample.png")
    im, stats = diff_sheet()
    im.save(REVIEW / "lantern_diff.png")
    props_sheet().save(REVIEW / "props_sample.png")
    res = run_checks()
    stats["checks"] = [{"asset": Path(r["info"]["asset"]).name, "ok": r["ok"], "errors": r["errors"][:20],
                        "warnings": r["warnings"][:20], "info": r["info"]} for r in res]
    stats["timings"] = timings
    (REVIEW / "lantern_diff.json").write_text(json.dumps(stats, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(stats["total"], ensure_ascii=False))
    print(f"共 {time.perf_counter() - t0:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
