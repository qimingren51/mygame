"""把素材文件夹打包成 PixiJS 图集（PNG + JSON）。

用法（在仓库根目录下；桌面版用 2 倍密度的产物 art/out/assets@2x，输出到 assets/atlas）：
    art/.venv/bin/python art/post/pack_atlas.py --name vfx --out assets/atlas art/out/assets@2x/vfx art/out/assets@2x/weapons
    art/.venv/bin/python art/post/pack_atlas.py --name actors --out assets/atlas art/out/assets@2x/hero art/out/assets@2x/shade ...
    art/.venv/bin/python art/post/pack_atlas.py --paper art/out/assets@2x/ground/paper.png --out assets/atlas
    art/.venv/bin/python art/post/pack_atlas.py --name ui --no-trim --out assets/atlas art/out/assets@2x/ui art/out/assets@2x/portrait

支持两种 meta.json：
  1. 特效/地面格式：{"files": {"light.png": {"size": [w, h], "anchor": [ax, ay], ...}}}
  2. 角色格式（style.py 末尾的输出约定）：{"name", "size", "anchor", "anims": {...}, "sockets": {...}}

输出：
  <name>.png   图集（2 的幂，单页最大 4096²；放不下时分页为 <name>_0、<name>_1 …）
  <name>.json  Pixi 的 Spritesheet 格式。帧名为 "<素材名>/<文件名去扩展名>"，例如 "vfx/light"、"hero/walk_E_03"。
               trimmed + spriteSourceSize 记录裁掉的透明边，anchor 是相对原始尺寸的锚点。
               animations：角色素材的每个“动画_朝向”是一个序列，例如 "hero/walk_E"。
               meta.lantern.assets：每个角色素材的 anims、fps、挂点等原样保留，游戏里读取。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

MAX_SIZE = 4096  # 单页上限；超出时自动分页（网页版 lantern-next 当年用 2048）
DEFAULT_PX_PER_UNIT = 2.0  # 素材 meta.json 没写 px_per_unit 时的默认密度
PAD = 2  # 帧与帧之间的间距
MARGIN = 1  # 裁边时保留的透明边，线性过滤时不会采到邻居


# 帧 meta 里不导出的字段：尺寸、锚点已在帧数据里，blend / tint 单独写，其余是给人看的说明
FRAME_INFO_SKIP = {"size", "anchor", "blend", "tint", "tile", "note", "color"}


def frame_info_fields(info: dict) -> dict:
    """素材 meta 里每个文件的附加标量字段（数字、布尔、字符串），写进图集的 meta.lantern.frames。"""
    return {
        k: v for k, v in info.items() if k not in FRAME_INFO_SKIP and isinstance(v, (int, float, bool, str))
    }


def load_asset(folder: Path, emit: bool = True) -> tuple[str, list[dict], dict]:
    """读取一个素材文件夹，返回 (素材名, 帧列表, 附加信息)。

    每帧是 {"key", "img", "anchor", "blend", "tint", "info"}：
    - 特效 / 地面格式：blend、tint 取自 meta.json 的 files.<文件>.blend / tint；
      其余标量字段（radius_px、angle_deg、flat、stretch、kind、id、name 等）放进 info，原样写进图集；
    - 角色格式：普通帧 blend=normal；自发光层 *_emit 是 blend=add（emit=False 时跳过）。
    """
    meta = json.loads((folder / "meta.json").read_text(encoding="utf-8"))
    name = meta.get("name") or folder.name
    frames: list[dict] = []
    extra: dict = {}
    if "files" in meta:
        for fname, info in meta["files"].items():
            if info.get("tile"):
                continue  # 平铺贴图单独输出，不进图集
            img = Image.open(folder / fname).convert("RGBA")
            ax, ay = info.get("anchor", [0.5, 0.5])
            frames.append(
                {
                    "key": f"{name}/{Path(fname).stem}",
                    "img": img,
                    "anchor": (ax, ay),
                    "blend": info.get("blend", "normal"),
                    "tint": bool(info.get("tint", False)),
                    "info": frame_info_fields(info),
                }
            )
    else:
        ax, ay = meta.get("anchor", [0.5, 0.875])
        for png in sorted(folder.glob("*.png")):
            is_emit = png.stem.endswith("_emit")
            if is_emit and not emit:
                continue
            img = Image.open(png).convert("RGBA")
            frames.append(
                {"key": f"{name}/{png.stem}", "img": img, "anchor": (ax, ay), "blend": "add" if is_emit else "normal", "tint": False}
            )
        # 角色的元数据原样带进图集（动画、挂点、碰撞半径、影子大小等），文件名之类的除外
        extra = {k: v for k, v in meta.items() if k not in ("name",)}
    if not frames:
        raise SystemExit(f"{folder}: 没有找到任何帧")
    return name, frames, extra


def trim(img: Image.Image) -> tuple[Image.Image, tuple[int, int, int, int]]:
    """裁掉透明边（保留 MARGIN 像素）。返回裁后的图和 (x, y, w, h)，坐标相对原图。"""
    a = np.asarray(img)[:, :, 3]
    ys, xs = np.nonzero(a)
    if len(xs) == 0:
        return img.crop((0, 0, 1, 1)), (0, 0, 1, 1)
    x0 = max(0, int(xs.min()) - MARGIN)
    y0 = max(0, int(ys.min()) - MARGIN)
    x1 = min(img.width, int(xs.max()) + 1 + MARGIN)
    y1 = min(img.height, int(ys.max()) + 1 + MARGIN)
    return img.crop((x0, y0, x1, y1)), (x0, y0, x1 - x0, y1 - y0)


def pack(sizes: list[tuple[int, int]], width: int, height: int) -> list[tuple[int, int]] | None:
    """按高度降序的货架式装箱。放不下返回 None。"""
    order = sorted(range(len(sizes)), key=lambda i: (-sizes[i][1], -sizes[i][0]))
    pos: list[tuple[int, int]] = [(0, 0)] * len(sizes)
    x = y = PAD
    shelf = 0
    for i in order:
        w, h = sizes[i]
        if w + 2 * PAD > width:
            return None
        if x + w + PAD > width:
            x = PAD
            y += shelf + PAD
            shelf = 0
        if y + h + PAD > height:
            return None
        pos[i] = (x, y)
        x += w + PAD
        shelf = max(shelf, h)
    return pos


def asset_px_per_unit(folder: Path) -> float | None:
    """素材目录 meta.json 里记录的密度（贴图像素 / 世界单位）；没有记录返回 None。"""
    meta = json.loads((folder / "meta.json").read_text(encoding="utf-8"))
    v = meta.get("px_per_unit")
    return float(v) if v is not None else None


def fit_page(sizes: list[tuple[int, int]], max_size: int) -> tuple[tuple[int, int], list[tuple[int, int]]] | None:
    """找能装下全部帧的最小页面（2 的幂，宽 ≥ 高），装不下返回 None。"""
    total = sum(w * h for w, h in sizes)
    side = 64
    while side <= max_size:
        for w, h in ((side, side // 2), (side, side)):
            if w * h < total:
                continue
            layout = pack(sizes, w, h)
            if layout:
                return (w, h), layout
        side *= 2
    return None


def paginate(entries: list[dict], max_size: int) -> list[tuple[list[dict], tuple[int, int], list[tuple[int, int]]]]:
    """分页：按素材整组放，同一素材尽量在同一页；单个素材一页放不下时才拆开。"""
    groups: dict[str, list[dict]] = {}
    for e in entries:
        groups.setdefault(e["key"].split("/")[0], []).append(e)
    pages: list[list[dict]] = []
    cur: list[dict] = []
    for group in groups.values():
        trial = cur + group
        if fit_page([e["img"].size for e in trial], max_size):
            cur = trial
            continue
        if cur:
            pages.append(cur)
            cur = []
        if fit_page([e["img"].size for e in group], max_size):
            cur = list(group)
            continue
        # 这个素材自己就超过一页：逐帧往下排
        for e in group:
            trial = cur + [e]
            if fit_page([x["img"].size for x in trial], max_size):
                cur = trial
            else:
                if not cur:
                    raise SystemExit(f"{e['key']} 单帧就超过 {max_size}²")
                pages.append(cur)
                cur = [e]
    if cur:
        pages.append(cur)
    out = []
    for page in pages:
        fitted = fit_page([e["img"].size for e in page], max_size)
        assert fitted is not None
        out.append((page, fitted[0], fitted[1]))
    return out


def build_atlas(
    name: str, folders: list[Path], out: Path, max_size: int = MAX_SIZE, emit: bool = True, trim_frames: bool = True
) -> list[str]:
    """打包并写出图集，返回写出的 JSON 文件名列表（一页时是 <name>.json，多页时是 <name>_0.json …）。

    trim_frames=False 时不裁透明边：每帧的矩形就是原图大小（界面图标用，代码不用处理 spriteSourceSize）。
    """
    entries: list[dict] = []
    assets: dict = {}
    animations: dict[str, list[str]] = {}
    densities: set[float] = set()
    for folder in folders:
        aname, frames, extra = load_asset(folder, emit)
        d = asset_px_per_unit(folder)
        if d is not None:
            densities.add(d)
        if extra:
            assets[aname] = extra
        for f in frames:
            if trim_frames:
                cropped, rect = trim(f["img"])
            else:
                cropped, rect = f["img"], (0, 0, f["img"].width, f["img"].height)
            entries.append({**f, "img": cropped, "rect": rect, "src": f["img"].size})
        # 角色素材：按 “动画_朝向” 组成序列（闪白帧单独成组）
        keys = {e["key"] for e in entries}
        if "anims" in extra:
            for anim, info in extra["anims"].items():
                for d2 in info.get("dirs", ["E"]):
                    for suffix in ("", "_flash", "_emit"):
                        seq = [f"{aname}/{anim}_{d2}_{f:02d}{suffix}" for f in range(info["frames"])]
                        if all(s in keys for s in seq):
                            animations[f"{aname}/{anim}_{d2}{suffix}"] = seq
    if len(densities) > 1:
        raise SystemExit(f"{name}: 素材的密度不一致 {sorted(densities)}，不能打进同一张图集")
    px_per_unit = densities.pop() if densities else DEFAULT_PX_PER_UNIT

    pages = paginate(entries, max_size)
    multi = len(pages) > 1
    names = [f"{name}_{i}" if multi else name for i in range(len(pages))]
    out.mkdir(parents=True, exist_ok=True)
    for i, (page, dims, layout) in enumerate(pages):
        sheet = Image.new("RGBA", dims, (0, 0, 0, 0))
        frames_json: dict = {}
        for e, (x, y) in zip(page, layout):
            sheet.paste(e["img"], (x, y))
            rx, ry, rw, rh = e["rect"]
            sw, sh = e["src"]
            frames_json[e["key"]] = {
                "frame": {"x": x, "y": y, "w": rw, "h": rh},
                "rotated": False,
                "trimmed": (rw, rh) != (sw, sh),
                "spriteSourceSize": {"x": rx, "y": ry, "w": rw, "h": rh},
                "sourceSize": {"w": sw, "h": sh},
                "anchor": {"x": e["anchor"][0], "y": e["anchor"][1]},
            }
        png = out / f"{names[i]}.png"
        sheet.save(png, optimize=True)
        # 每帧的混合方式与是否染色（只列本页的帧）
        frame_info = {e["key"]: {**e.get("info", {}), "blend": e["blend"], "tint": e["tint"]} for e in page}
        lantern: dict = {"pxPerUnit": px_per_unit, "page": i, "pages": len(pages), "frames": frame_info}
        # 动画序列和角色元数据只写在第 0 页；多页时读取方要先合并所有页的 frames
        if i == 0:
            lantern["assets"] = assets
        data = {
            "frames": frames_json,
            "animations": animations if i == 0 else {},
            "meta": {
                "app": "art/post/pack_atlas.py",
                "version": "2",
                "image": f"{names[i]}.png",
                "format": "RGBA8888",
                "size": {"w": dims[0], "h": dims[1]},
                "scale": 1,
                "related_multi_packs": [f"{n}.json" for j, n in enumerate(names) if j != i],
                "lantern": lantern,
            },
        }
        (out / f"{names[i]}.json").write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        used = sum(e["img"].size[0] * e["img"].size[1] for e in page) / (dims[0] * dims[1])
        print(f"{names[i]}: {len(page)} 帧 → {dims[0]}×{dims[1]}，利用率 {used:.0%}，{png.stat().st_size / 1024:.0f} KB")
    return [f"{n}.json" for n in names]


def update_index(out: Path, atlas: str | None = None, paper: bool = False, pages: list[str] | None = None) -> None:
    """维护 index.json：列出已经打包的图集，以及每个图集的分页 JSON。"""
    path = out / "index.json"
    idx = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"atlases": [], "paper": False}
    idx.setdefault("pages", {})
    if atlas and atlas not in idx["atlases"]:
        idx["atlases"].append(atlas)
        idx["atlases"].sort()
    if atlas and pages:
        idx["pages"][atlas] = pages
    if paper:
        idx["paper"] = True
    path.write_text(json.dumps(idx, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def write_paper(src: Path, out: Path, fmt: str = "png") -> None:
    """宣纸平铺贴图。桌面版用无损 PNG；网页版当年用 WebP（质量 97，低于 95 纤维会被抹平）。"""
    out.mkdir(parents=True, exist_ok=True)
    img = Image.open(src).convert("RGB")
    if fmt == "webp":
        dst = out / "paper.webp"
        img.save(dst, "WEBP", quality=97, method=6)
    else:
        dst = out / "paper.png"
        img.save(dst, optimize=True)
    print(f"paper: {img.width}×{img.height} → {dst.stat().st_size / 1024:.0f} KB")


def main(argv: list[str]) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--name", help="图集名（输出 <name>.png / <name>.json）")
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--paper", type=Path, help="写出平铺宣纸 paper.png（或 --paper-format webp）")
    ap.add_argument("--paper-format", choices=["png", "webp"], default="png")
    ap.add_argument("--no-emit", action="store_true", help="角色的自发光层 *_emit 不打进图集")
    ap.add_argument("--max", type=int, default=MAX_SIZE, help="单页最大边长（默认 4096）")
    ap.add_argument("--no-trim", action="store_true", help="不裁透明边（界面图标：帧矩形 = 原图大小）")
    ap.add_argument("folders", nargs="*", type=Path)
    args = ap.parse_args(argv)
    if args.paper:
        write_paper(args.paper, args.out, args.paper_format)
        update_index(args.out, paper=True)
    if args.folders:
        if not args.name:
            raise SystemExit("打包图集需要 --name")
        pages = build_atlas(args.name, args.folders, args.out, args.max, emit=not args.no_emit, trim_frames=not args.no_trim)
        update_index(args.out, atlas=args.name, pages=pages)


if __name__ == "__main__":
    main(sys.argv[1:])
