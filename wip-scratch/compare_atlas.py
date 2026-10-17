"""打包前后逐像素对比（草稿脚本，不进仓库）。用法：python compare_atlas.py <旧图集目录> <新图集目录>"""
import hashlib, json, sys
from pathlib import Path
import numpy as np
from PIL import Image

old_dir, new_dir = Path(sys.argv[1]), Path(sys.argv[2])
EXPECT_PIXELS = {"ground/" + n for n in (*(f"grass_{i}" for i in range(4)), "leaves_0", "leaves_1", "pebbles_0", "pebbles_1",
                 *(f"qq_bamboo_leaves_{i}" for i in range(3)), "qq_moss_0", "qq_moss_1", "qq_fox_tracks")}
EXPECT_NEW = {"vfx/light_pool"}

def frames(d, name):
    j = json.loads((d / f"{name}.json").read_text(encoding="utf-8"))
    page = np.asarray(Image.open(d / j["meta"]["image"]).convert("RGBA"))
    out = {}
    for k, f in j["frames"].items():
        r, s, src = f["frame"], f["spriteSourceSize"], f["sourceSize"]
        can = np.zeros((src["h"], src["w"], 4), np.uint8)
        can[s["y"]:s["y"] + s["h"], s["x"]:s["x"] + s["w"]] = page[r["y"]:r["y"] + r["h"], r["x"]:r["x"] + r["w"]]
        meta = {kk: v for kk, v in f.items() if kk != "frame"}
        out[k] = (can, meta)
    return j, out

ok = True
for name in ("vfx", "ground"):
    jo, fo = frames(old_dir, name)
    jn, fn = frames(new_dir, name)
    added, removed = set(fn) - set(fo), set(fo) - set(fn)
    same, changed, meta_changed = 0, [], []
    for k in sorted(set(fo) & set(fn)):
        (a, ma), (b, mb) = fo[k], fn[k]
        if a.shape != b.shape or not (a == b).all():
            changed.append(k)
        else:
            same += 1
        if ma != mb:
            meta_changed.append(k)
    lo, ln = jo["meta"]["lantern"], jn["meta"]["lantern"]
    lant_diff = {kk for kk in set(lo) | set(ln) if lo.get(kk) != ln.get(kk)}
    fr_diff = {kk for kk in set(lo.get("frames", {})) | set(ln.get("frames", {})) if lo["frames"].get(kk) != ln["frames"].get(kk)}
    anim_diff = jo.get("animations") != jn.get("animations")
    print(f"{name}: 帧 旧 {len(fo)} 新 {len(fn)}；完全相同 {same}；像素不同 {len(changed)}：{changed}")
    print(f"  新增 {sorted(added)}  删掉 {sorted(removed)}  帧 meta 不同 {meta_changed}  lantern 顶层不同 {sorted(lant_diff)}  lantern.frames 不同 {sorted(fr_diff)}  animations 不同 {anim_diff}")
    if set(changed) - EXPECT_PIXELS or removed or meta_changed or anim_diff:
        ok = False
    if added - EXPECT_NEW or (fr_diff - added):
        ok = False
    if name == "ground" and set(changed) != EXPECT_PIXELS:
        ok = False
    if name == "vfx" and (changed or added != EXPECT_NEW):
        ok = False
    if name == "vfx":
        print("  light_pool 帧信息：", {k: v for k, v in fn["vfx/light_pool"][1].items()}, ln["frames"].get("vfx/light_pool"))

# 其余文件逐字节
md5 = lambda p: hashlib.md5(p.read_bytes()).hexdigest()
others_same, others_diff = 0, []
for p in sorted(old_dir.rglob("*")):
    if p.is_dir():
        continue
    rel = p.relative_to(old_dir)
    if str(rel) in ("vfx.png", "vfx.json", "ground.png", "ground.json", "paper.png"):
        continue
    q = new_dir / rel
    if not q.exists() or md5(p) != md5(q):
        others_diff.append(str(rel))
    else:
        others_same += 1
extra = sorted(str(p.relative_to(new_dir)) for p in new_dir.rglob("*") if p.is_file() and not (old_dir / p.relative_to(new_dir)).exists())
print(f"其余文件：逐字节相同 {others_same}，不同 {others_diff}，新多出 {extra}")
print("ground.json 逐字节相同" if md5(old_dir / "ground.json") == md5(new_dir / "ground.json") else "ground.json 有变化")
po = np.asarray(Image.open(old_dir / "paper.png").convert("RGB")); pn = np.asarray(Image.open(new_dir / "paper.png").convert("RGB"))
print(f"paper.png：{po.shape} → {pn.shape}，不同像素 {(po != pn).any(-1).mean():.1%}，均值 {po.reshape(-1, 3).mean(0).round(3)} → {pn.reshape(-1, 3).mean(0).round(3)}")
if others_diff or extra:
    ok = False
print("结论：" + ("只有预期的变化" if ok else "有预期之外的变化！"))
sys.exit(0 if ok else 1)
