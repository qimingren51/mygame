"""把素材文件夹打包成 PixiJS 图集（PNG + JSON）。

用法（在 lantern-next/ 目录下）：
    art/.venv/bin/python art/post/pack_atlas.py --name vfx --out public/assets art/out/assets/vfx
    art/.venv/bin/python art/post/pack_atlas.py --name actors --out public/assets art/out/assets/hero art/out/assets/shade ...
    art/.venv/bin/python art/post/pack_atlas.py --paper art/out/assets/ground/paper.png --out public/assets

支持两种 meta.json：
  1. 特效/地面格式：{"files": {"light.png": {"size": [w, h], "anchor": [ax, ay], ...}}}
  2. 角色格式（style.py 末尾的输出约定）：{"name", "size", "anchor", "anims": {...}, "sockets": {...}}

输出：
  <name>.png   图集（2 的幂，最大 2048²）
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

MAX_SIZE = 2048
PAD = 2  # 帧与帧之间的间距
MARGIN = 1  # 裁边时保留的透明边，线性过滤时不会采到邻居


def load_asset(folder: Path) -> tuple[str, list[tuple[str, Image.Image, tuple[float, float]]], dict]:
    """读取一个素材文件夹，返回 (素材名, [(帧名, 图像, 锚点)], 附加信息)。"""
    meta = json.loads((folder / "meta.json").read_text(encoding="utf-8"))
    name = meta.get("name") or folder.name
    frames: list[tuple[str, Image.Image, tuple[float, float]]] = []
    extra: dict = {}
    if "files" in meta:
        for fname, info in meta["files"].items():
            if info.get("tile"):
                continue  # 平铺贴图单独输出，不进图集
            img = Image.open(folder / fname).convert("RGBA")
            ax, ay = info.get("anchor", [0.5, 0.5])
            frames.append((f"{name}/{Path(fname).stem}", img, (ax, ay)))
    else:
        ax, ay = meta.get("anchor", [0.5, 0.875])
        for png in sorted(folder.glob("*.png")):
            img = Image.open(png).convert("RGBA")
            frames.append((f"{name}/{png.stem}", img, (ax, ay)))
        extra = {k: meta[k] for k in ("size", "anchor", "anims", "sockets", "height_px") if k in meta}
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


def build_atlas(name: str, folders: list[Path], out: Path) -> None:
    entries: list[dict] = []
    assets: dict = {}
    animations: dict[str, list[str]] = {}
    for folder in folders:
        aname, frames, extra = load_asset(folder)
        if extra:
            assets[aname] = extra
        for key, img, (ax, ay) in frames:
            cropped, rect = trim(img)
            entries.append({"key": key, "img": cropped, "rect": rect, "src": img.size, "anchor": (ax, ay)})
        # 角色素材：按 “动画_朝向” 组成序列（闪白帧单独成组）
        if "anims" in extra:
            for anim, info in extra["anims"].items():
                for d in info.get("dirs", ["E"]):
                    for suffix in ("", "_flash"):
                        seq = [f"{aname}/{anim}_{d}_{f:02d}{suffix}" for f in range(info["frames"])]
                        if all(any(e["key"] == s for e in entries) for s in seq):
                            animations[f"{aname}/{anim}_{d}{suffix}"] = seq

    sizes = [e["img"].size for e in entries]
    total = sum(w * h for w, h in sizes)
    layout = None
    dims = (0, 0)
    for side in (64, 128, 256, 512, 1024, 2048):
        for w, h in ((side, side // 2), (side, side)):
            if w * h < total or w > MAX_SIZE:
                continue
            layout = pack(sizes, w, h)
            if layout:
                dims = (w, h)
                break
        if layout:
            break
    if not layout:
        raise SystemExit(f"{name}: 放不进 {MAX_SIZE}² 的图集（共 {len(entries)} 帧，{total} 像素）")

    sheet = Image.new("RGBA", dims, (0, 0, 0, 0))
    frames_json: dict = {}
    for e, (x, y) in zip(entries, layout):
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

    out.mkdir(parents=True, exist_ok=True)
    png = out / f"{name}.png"
    sheet.save(png, optimize=True)
    data = {
        "frames": frames_json,
        "animations": animations,
        "meta": {
            "app": "lantern-next art/post/pack_atlas.py",
            "version": "1",
            "image": f"{name}.png",
            "format": "RGBA8888",
            "size": {"w": dims[0], "h": dims[1]},
            "scale": 1,
            "lantern": {"assets": assets},
        },
    }
    (out / f"{name}.json").write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    used = sum(w * h for w, h in sizes) / (dims[0] * dims[1])
    print(f"{name}: {len(entries)} 帧 → {dims[0]}×{dims[1]}，利用率 {used:.0%}，{png.stat().st_size / 1024:.0f} KB")


def update_index(out: Path, atlas: str | None = None, paper: bool = False) -> None:
    """维护 index.json：游戏只加载清单里列出的图集。"""
    path = out / "index.json"
    idx = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"atlases": [], "paper": False}
    if atlas and atlas not in idx["atlases"]:
        idx["atlases"].append(atlas)
        idx["atlases"].sort()
    if paper:
        idx["paper"] = True
    path.write_text(json.dumps(idx, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def write_paper(src: Path, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    img = Image.open(src).convert("RGB")
    dst = out / "paper.webp"
    # 纸纹对比度很低，质量低于 95 时纤维会被抹平（实测 97 约 16 KB，保留约 85% 细节）
    img.save(dst, "WEBP", quality=97, method=6)
    print(f"paper: {img.width}×{img.height} → {dst.stat().st_size / 1024:.0f} KB")


def main(argv: list[str]) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--name", help="图集名（输出 <name>.png / <name>.json）")
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--paper", type=Path, help="把平铺的宣纸转成 paper.webp")
    ap.add_argument("folders", nargs="*", type=Path)
    args = ap.parse_args(argv)
    if args.paper:
        write_paper(args.paper, args.out)
        update_index(args.out, paper=True)
    if args.folders:
        if not args.name:
            raise SystemExit("打包图集需要 --name")
        build_atlas(args.name, args.folders, args.out)
        update_index(args.out, atlas=args.name)


if __name__ == "__main__":
    main(sys.argv[1:])
