"""图集重新打包前后的逐帧对比（草稿脚本，不进仓库）。
用法：python -I compare_pack2.py <旧图集目录> <新图集目录> --changed <前缀,…> --added <素材目录,…>
- 旧帧：除了 --changed 前缀开头的，逐像素、逐字段不变；
- 新增的帧正好是 --added 各素材目录（meta.json）里、旧图集没有的帧，并且和素材逐像素一致；--changed 的帧也和素材一致；
- 其余图集文件逐字节相同。"""
import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ap = argparse.ArgumentParser()
ap.add_argument("old")
ap.add_argument("new")
ap.add_argument("--changed", default="")
ap.add_argument("--added", default="")
ap.add_argument("--atlas", default="vfx")
args = ap.parse_args()
old_dir, new_dir = Path(args.old), Path(args.new)
changed_pref = [p for p in args.changed.split(",") if p]
src_dirs = [Path(p) for p in args.added.split(",") if p]


def load(d: Path, name: str):
    index = json.loads((d / "index.json").read_text(encoding="utf-8"))
    out, info, files = {}, {}, index["pages"][name]
    for fn in files:
        j = json.loads((d / fn).read_text(encoding="utf-8"))
        page = np.asarray(Image.open(d / j["meta"]["image"]).convert("RGBA"))
        for k, f in j["frames"].items():
            r, s, src = f["frame"], f["spriteSourceSize"], f["sourceSize"]
            can = np.zeros((src["h"], src["w"], 4), np.uint8)
            can[s["y"]:s["y"] + s["h"], s["x"]:s["x"] + s["w"]] = page[r["y"]:r["y"] + r["h"], r["x"]:r["x"] + r["w"]]
            out[k] = (can, {kk: v for kk, v in f.items() if kk != "frame"})
        info.update(j["meta"]["lantern"]["frames"])
    return out, info, files, index


fo, io, files_o, idx_o = load(old_dir, args.atlas)
fn, inew, files_n, idx_n = load(new_dir, args.atlas)
src = {}
for d in src_dirs:
    m = json.loads((d / "meta.json").read_text(encoding="utf-8"))
    for k in m["files"]:
        src[f"{m['name']}/{Path(k).stem}"] = d / k
is_changed = lambda k: any(k.startswith(p) for p in changed_pref)  # noqa: E731
added, removed = set(fn) - set(fo), set(fo) - set(fn)
same_keys = sorted(set(fo) & set(fn))
pix_changed = [k for k in same_keys if fo[k][0].shape != fn[k][0].shape or not (fo[k][0] == fn[k][0]).all()]
meta_changed = [k for k in same_keys if (fo[k][1] != fn[k][1] or io.get(k) != inew.get(k))]
bad_changed = [k for k in pix_changed + meta_changed if not is_changed(k)]
expect_added = {k for k in src if k not in fo}
print(f"{args.atlas} 页：{files_o} → {files_n}")
print(f"旧帧 {len(fo)}：像素变了 {len(pix_changed)}（允许的前缀 {changed_pref}），字段变了 {len(meta_changed)}，不该变的 {bad_changed[:8]}，少了 {sorted(removed)[:8]}")
print(f"新增 {len(added)} 帧；和素材里的新帧一致：{added == expect_added}（多 {sorted(added - expect_added)[:5]}，少 {sorted(expect_added - added)[:5]}）")
bad = []
for k in sorted((added | {k for k in pix_changed if is_changed(k)}) & set(src)):
    s_ = np.asarray(Image.open(src[k]).convert("RGBA"))
    a = fn[k][0]
    vis = (a[..., 3] > 0) | (s_[..., 3] > 0)
    if a.shape != s_.shape or not (a[..., 3] == s_[..., 3]).all() or not (a[vis] == s_[vis]).all():
        bad.append(k)
print(f"新增 / 改动的帧和素材逐像素一致：{not bad} {bad[:5]}")
missing_changed = [k for k in fo if is_changed(k) and k not in fn]


def md5s(d: Path):
    return {str(p.relative_to(d)): hashlib.md5(p.read_bytes()).hexdigest() for p in sorted(d.rglob("*")) if p.is_file()}


mo, mn = md5s(old_dir), md5s(new_dir)
mine = set(files_o) | set(files_n)
mine |= {f.replace(".json", ".png") for f in mine}
other_diff = sorted(k for k in set(mo) | set(mn) if mo.get(k) != mn.get(k) and k not in mine)
print(f"其余文件 {len(set(mo) - mine)} 个，变了：{other_diff}")
idx_ok = {k: v for k, v in idx_o.items() if k != "pages"} == {k: v for k, v in idx_n.items() if k != "pages"} and \
    {k: v for k, v in idx_o["pages"].items() if k != args.atlas} == {k: v for k, v in idx_n["pages"].items() if k != args.atlas}
print(f"index.json 里别的图集不变：{idx_ok}")
ok = not bad_changed and not removed and added == expect_added and not bad and idx_ok and not [k for k in other_diff if k != "index.json"]
print("通过" if ok else "有差异")
sys.exit(0 if ok else 1)
