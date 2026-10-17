"""cards 页打包前后逐像素核对（线 2 草稿，不进仓库）。

用法：python cmp_cards.py <旧 assets/atlas> <新 assets/atlas> <素材目录> ...
  - 旧页里的帧在新页里都在，像素和帧信息完全相同（--changed 列出的除外）；
  - 新页里每一帧和素材目录里的原图逐像素相同；
  - assets/atlas 下 cards* 以外的文件逐字节相同。
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image


def frames(d: Path, atlas: str = "cards") -> tuple[dict, dict]:
    idx = json.loads((d / "index.json").read_text(encoding="utf-8"))
    out, info = {}, {}
    for f in idx["pages"].get(atlas, []):
        j = json.loads((d / f).read_text(encoding="utf-8"))
        page = np.asarray(Image.open(d / j["meta"]["image"]).convert("RGBA"))
        for k, fr in j["frames"].items():
            r, s, src = fr["frame"], fr["spriteSourceSize"], fr["sourceSize"]
            can = np.zeros((src["h"], src["w"], 4), np.uint8)
            can[s["y"]:s["y"] + s["h"], s["x"]:s["x"] + s["w"]] = page[r["y"]:r["y"] + r["h"], r["x"]:r["x"] + r["w"]]
            out[k] = can
            info[k] = (j["meta"]["lantern"]["frames"].get(k), fr["anchor"], fr["trimmed"])
    return out, info


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("old", type=Path)
    ap.add_argument("new", type=Path)
    ap.add_argument("src", nargs="+", type=Path)
    ap.add_argument("--changed", default="", help="允许像素变化的帧（逗号分隔）")
    a = ap.parse_args()
    allow = {s for s in a.changed.split(",") if s}
    fo, io = frames(a.old)
    fn, inn = frames(a.new)
    ok = True
    same, changed = 0, []
    for k in sorted(fo):
        if k not in fn:
            print("× 新页少了", k)
            ok = False
            continue
        if fo[k].shape == fn[k].shape and (fo[k] == fn[k]).all() and io[k] == inn[k]:
            same += 1
        else:
            changed.append(k)
    bad = [k for k in changed if k not in allow]
    print(f"旧帧 {len(fo)}：完全相同 {same}，有变化 {len(changed)} {changed}")
    if bad:
        print("× 不该变的帧变了：", bad)
        ok = False
    added = sorted(set(fn) - set(fo))
    print(f"新增 {len(added)}：{added}")
    # 每一帧对原图
    srcs = {}
    for d in a.src:
        meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
        for fname in meta["files"]:
            srcs[f"{meta['name']}/{Path(fname).stem}"] = d / fname
    for k, img in fn.items():
        p = srcs.get(k)
        if p is None:
            print("× 找不到原图", k)
            ok = False
            continue
        ref = np.asarray(Image.open(p).convert("RGBA"))
        if ref.shape != img.shape or not (ref == img).all():
            print("× 和原图不同", k)
            ok = False
    print(f"新页 {len(fn)} 帧逐像素对原图：{'全部相同' if ok else '有问题'}")

    # 其余文件逐字节
    def md5(p: Path) -> str:
        return hashlib.md5(p.read_bytes()).hexdigest()

    diff = []
    names = {p.relative_to(a.old) for p in a.old.rglob("*") if p.is_file()} | {p.relative_to(a.new) for p in a.new.rglob("*") if p.is_file()}
    for rel in sorted(names):
        if rel.name.startswith("cards") or rel.name == "index.json":
            continue
        po, pn = a.old / rel, a.new / rel
        if not po.exists() or not pn.exists() or md5(po) != md5(pn):
            diff.append(str(rel))
    print(f"cards 以外的文件：{len(names)} 个里不同 {len(diff)} {diff}")
    io_ = json.loads((a.old / "index.json").read_text(encoding="utf-8"))
    in_ = json.loads((a.new / "index.json").read_text(encoding="utf-8"))
    io_["pages"].pop("cards", None)
    in_["pages"].pop("cards", None)
    if io_ != in_:
        print("× index.json 除 cards 外有变化")
        ok = False
    if diff:
        ok = False
    print("通过" if ok else "未通过")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
