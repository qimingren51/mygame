"""第二阶段：新旧帧差异（按 动画 × 朝向 的平均绝对差）+ 没重渲的素材逐字节核对。

    art/.venv/bin/python kfix_diff.py snapshot <json>          # 记下 assets@2x 里每个文件的哈希
    art/.venv/bin/python kfix_diff.py diff <快照 json> <输出 json>  # 重渲后：差异表 + 没重渲的文件是否逐字节相同
差异：铺在宣纸色上的 RGB 和 alpha 的逐像素最大差（0–255），整帧平均；另给 >16/255 的像素占比。
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

A = Path("/home/user/mygame/art/out/assets@2x")
OLD = Path("/home/user/mygame/art/out/_kfix_old")
REDO = ("hero", "lantern_red", "lantern_mirror", "lantern_frost", "boss", "stonelord", "fox")
PAPER = np.array([237, 228, 207], np.float32)


def snapshot(path):
    h = {}
    for p in sorted(A.rglob("*")):
        if p.is_file() and not p.relative_to(A).parts[0].startswith("_"):
            h[str(p.relative_to(A))] = hashlib.sha1(p.read_bytes()).hexdigest()
    Path(path).write_text(json.dumps(h, indent=0))
    print(len(h), "个文件")


def frame_diff(a: Path, b: Path):
    x, y = np.asarray(Image.open(a).convert("RGBA"), np.float32), np.asarray(Image.open(b).convert("RGBA"), np.float32)
    on = lambda z: z[..., :3] * (z[..., 3:4] / 255) + PAPER * (1 - z[..., 3:4] / 255)  # noqa: E731
    d = np.maximum(np.abs(on(x) - on(y)).max(-1), np.abs(x[..., 3] - y[..., 3]))
    return float(d.mean()), float((d > 16).mean())


def diff(snap_path, out_path):
    res = {"by_asset": {}, "unchanged_check": {}}
    for asset in REDO:
        meta = json.loads((A / asset / "meta.json").read_text(encoding="utf-8"))
        rows = {}
        for an, a in meta["anims"].items():
            for d in a["dirs"]:
                ms, fs = [], []
                for i in range(a["frames"]):
                    k = f"{an}_{d}_{i:02d}.png"
                    if not (OLD / asset / k).exists():
                        continue
                    m, f = frame_diff(OLD / asset / k, A / asset / k)
                    ms.append(m)
                    fs.append(f)
                if ms:
                    rows[f"{an}_{d}"] = {"mean_abs": round(float(np.mean(ms)), 3), "max_frame_mean_abs": round(max(ms), 3),
                                         "px_gt16_pct": round(100 * float(np.mean(fs)), 3)}
        res["by_asset"][asset] = rows
    snap = json.loads(Path(snap_path).read_text())
    changed, missing = [], []
    for rel, h in snap.items():
        if rel.split("/")[0] in REDO:
            continue
        p = A / rel
        if not p.exists():
            missing.append(rel)
        elif hashlib.sha1(p.read_bytes()).hexdigest() != h:
            changed.append(rel)
    added = [str(p.relative_to(A)) for p in A.rglob("*") if p.is_file() and str(p.relative_to(A)) not in snap
             and p.relative_to(A).parts[0] not in REDO and not p.relative_to(A).parts[0].startswith("_")]
    res["unchanged_check"] = {"files_checked": sum(1 for r in snap if r.split("/")[0] not in REDO),
                              "changed": changed, "missing": missing, "added": added}
    Path(out_path).write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    for asset, rows in res["by_asset"].items():
        print(f"== {asset}")
        for k, v in rows.items():
            print(f"  {k:10s} 平均 {v['mean_abs']:6.3f}  最差帧 {v['max_frame_mean_abs']:6.3f}  >16/255 {v['px_gt16_pct']:6.3f}%")
    print("没重渲的文件：", res["unchanged_check"]["files_checked"], "个；变了", len(changed), "；缺", len(missing), "；新增", len(added))
    for c in (changed + missing)[:20]:
        print("  ", c)


if __name__ == "__main__":
    if sys.argv[1] == "snapshot":
        snapshot(sys.argv[2])
    else:
        diff(sys.argv[2], sys.argv[3])
