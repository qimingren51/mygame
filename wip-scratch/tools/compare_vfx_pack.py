"""vfx 图集重新打包前后的逐像素对比（草稿脚本，不进仓库）。
用法：python -I compare_vfx_pack.py <旧图集目录> <新图集目录> <vfx_frames 产物目录>
旧帧逐像素、逐字段不变；新增的正好是 vfx_frames 的帧；其余图集文件逐字节相同。"""
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

old_dir, new_dir, frames_dir = map(Path, sys.argv[1:4])


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
    return out, info, files


fo, io, files_o = load(old_dir, "vfx")
fn, inew, files_n = load(new_dir, "vfx")
added, removed = set(fn) - set(fo), set(fo) - set(fn)
_fm = json.loads((frames_dir / "meta.json").read_text(encoding="utf-8"))
expect = {f"{_fm['name']}/{Path(k).stem}" for k in _fm["files"]}
changed = [k for k in sorted(set(fo) & set(fn)) if fo[k][0].shape != fn[k][0].shape or not (fo[k][0] == fn[k][0]).all()]
meta_changed = [k for k in sorted(set(fo) & set(fn)) if fo[k][1] != fn[k][1] or io.get(k) != inew.get(k)]
print(f"vfx 页：{files_o} → {files_n}")
print(f"旧帧 {len(fo)}：像素相同 {len(set(fo) & set(fn)) - len(changed)}，像素变了 {changed}，字段变了 {meta_changed}，少了 {sorted(removed)}")
print(f"新增 {len(added)} 帧；和 vfx_frames 产物一致：{added == expect}（多 {sorted(added - expect)[:5]}，少 {sorted(expect - added)[:5]}）")
# 新增帧和产物逐像素一致
bad = []
for k in sorted(added & expect):
    src = np.asarray(Image.open(frames_dir / f"{k.split('/', 1)[1]}.png").convert("RGBA"))
    a = fn[k][0]
    vis = (a[..., 3] > 0) | (src[..., 3] > 0)
    if a.shape != src.shape or not (a[..., 3] == src[..., 3]).all() or not (a[vis] == src[vis]).all():
        bad.append(k)
print(f"新增帧和产物逐像素一致：{not bad} {bad[:5]}")


def md5s(d: Path):
    return {str(p.relative_to(d)): hashlib.md5(p.read_bytes()).hexdigest() for p in sorted(d.rglob("*")) if p.is_file()}


mo, mn = md5s(old_dir), md5s(new_dir)
vfx_files = set(files_o) | set(files_n) | {f.replace(".json", ".png") for f in set(files_o) | set(files_n)}
other_diff = sorted(k for k in set(mo) | set(mn) if mo.get(k) != mn.get(k) and k not in vfx_files)
print(f"其余文件 {len(set(mo) - vfx_files)} 个，变了：{other_diff}")
ok = not changed and not meta_changed and not removed and added == expect and not bad and not [k for k in other_diff if k != "index.json"]
print("通过" if ok else "有差异")
sys.exit(0 if ok else 1)
