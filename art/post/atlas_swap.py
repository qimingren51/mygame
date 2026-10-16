#!/usr/bin/env python3
"""图集里只换几个素材：从现有图集把每个素材的整帧还原出来，换上新的素材文件夹，重新打包，再逐帧核对没换的部分。

为什么不直接按 README 的命令从 art/out/ 重新打包：art/out/ 不进 git，本机的产物不一定是当初打包用的那一批，
别的素材可能被悄悄换掉。这里没换的素材全部取自现有图集（裁过边的帧按 spriteSourceSize 放回原尺寸），
打包器只裁边、不重采样，所以没换的帧逐像素不变；打包后再逐帧核对一遍（像素、裁边信息、锚点、混合方式、素材 meta）。

    art/.venv/bin/python art/post/atlas_swap.py --atlas <仓库>/assets/atlas --name actors art/out/assets@2x/shade art/out/assets@2x/fox
    art/.venv/bin/python art/post/atlas_swap.py --atlas <仓库>/assets/atlas --name boss art/out/assets@2x/boss
新素材按文件夹 meta.json 的 name 对上现有素材（没有的就加在最后）。核对不过时退出码 1，图集照样写出（方便看）。
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import pack_atlas as PA  # noqa: E402


def load_pages(atlas: Path, name: str):
    """读一个图集的全部页：返回 (frames {帧名: (页图, 帧数据)}, 第 0 页的 meta.lantern, animations)。"""
    idx = json.loads((atlas / "index.json").read_text(encoding="utf-8"))
    files = idx.get("pages", {}).get(name, [f"{name}.json"])
    frames, lantern, anims = {}, None, {}
    for f in files:
        d = json.loads((atlas / f).read_text(encoding="utf-8"))
        img = Image.open(atlas / d["meta"]["image"]).convert("RGBA")
        lan = d["meta"]["lantern"]
        if lan.get("page", 0) == 0:
            lantern = lan
            anims = d.get("animations", {})
        for k, fr in d["frames"].items():
            frames[k] = (img, fr, lan["frames"].get(k, {}))
    return frames, lantern, anims


def crop(img, fr):
    r = fr["frame"]
    return np.asarray(img.crop((r["x"], r["y"], r["x"] + r["w"], r["y"] + r["h"])))


def rebuild_folder(asset: str, frames: dict, meta: dict, dst: Path) -> None:
    """把图集里一个素材的帧还原成素材文件夹（整帧 PNG + meta.json）。"""
    dst.mkdir(parents=True, exist_ok=True)
    for k, (img, fr, _) in frames.items():
        if k.split("/", 1)[0] != asset:
            continue
        sw, sh = fr["sourceSize"]["w"], fr["sourceSize"]["h"]
        full = Image.new("RGBA", (sw, sh), (0, 0, 0, 0))
        ss = fr["spriteSourceSize"]
        full.paste(Image.fromarray(crop(img, fr)), (ss["x"], ss["y"]))
        full.save(dst / (k.split("/", 1)[1] + ".png"))
    (dst / "meta.json").write_text(json.dumps({"name": asset, **meta}, ensure_ascii=False, indent=1), encoding="utf-8")


def main(argv) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--atlas", required=True, type=Path, help="图集目录（会被改写：<name>*.json/png、index.json）")
    ap.add_argument("--name", required=True)
    ap.add_argument("folders", nargs="+", type=Path, help="新的素材文件夹")
    a = ap.parse_args(argv)
    old_frames, old_lan, old_anims = load_pages(a.atlas, a.name)
    order = list(old_lan["assets"].keys())
    new = {}
    for f in a.folders:
        nm = json.loads((f / "meta.json").read_text(encoding="utf-8")).get("name") or f.name
        new[nm] = f
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        folders = []
        for asset in order + [n for n in new if n not in order]:
            if asset in new:
                folders.append(new[asset])
            else:
                dst = td / asset
                rebuild_folder(asset, old_frames, old_lan["assets"][asset], dst)
                folders.append(dst)
        idx_p = a.atlas / "index.json"
        idx = json.loads(idx_p.read_text(encoding="utf-8"))
        for f in idx.get("pages", {}).get(a.name, []):  # 旧的分页文件先删掉（页数可能变）
            for ext in (".json", ".png"):
                (a.atlas / f).with_suffix(ext).unlink(missing_ok=True)
        pages = PA.build_atlas(a.name, folders, a.atlas)
        PA.update_index(a.atlas, atlas=a.name, pages=pages)
    # 核对：没换的素材逐帧相同
    new_frames, new_lan, new_anims = load_pages(a.atlas, a.name)
    errors, checked = [], 0
    for k, (img, fr, info) in old_frames.items():
        asset = k.split("/", 1)[0]
        if asset in new:
            continue
        if k not in new_frames:
            errors.append(f"少了帧 {k}")
            continue
        nimg, nfr, ninfo = new_frames[k]
        for key in ("spriteSourceSize", "sourceSize", "anchor", "trimmed"):
            if fr[key] != nfr[key]:
                errors.append(f"{k}：{key} {fr[key]} → {nfr[key]}")
        if info != ninfo:
            errors.append(f"{k}：帧信息 {info} → {ninfo}")
        if not np.array_equal(crop(img, fr), crop(nimg, nfr)):
            errors.append(f"{k}：像素不同")
        checked += 1
    for asset, m in old_lan["assets"].items():
        if asset not in new and new_lan["assets"].get(asset) != m:
            errors.append(f"素材 {asset} 的 meta 变了")
    for seq, keys in old_anims.items():
        if seq.split("/", 1)[0] not in new and new_anims.get(seq) != keys:
            errors.append(f"动画序列 {seq} 变了")
    replaced = {n: sum(1 for k in new_frames if k.split('/', 1)[0] == n) for n in new}
    print(f"[{a.name}] 没换的帧 {checked} 个逐像素核对：{'全部相同' if not errors else f'{len(errors)} 处不同'}；换上的素材 {replaced}")
    for e in errors[:30]:
        print("  ✗", e)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
