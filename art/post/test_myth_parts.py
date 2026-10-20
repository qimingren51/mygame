#!/usr/bin/env python3
"""myth_parts.py 产物的自检（读 art/out/assets@2x/myth/，不重画；--regen 先重画剑影再比逐字节）。

  1. 清单：meta.json 的条目和盘上的 PNG 一一对应，每组的帧数、尺寸、锚点和 SPECS 一致；
  2. 命名：发光层帧号在前、_emit 在后（sword_cloud_0_emit / fox_body_emit），没有旧写法 <名>_emit_<帧号>；
     每张发光层都有同名本体，画布、锚点一样，layer_of 指回本体；
  3. 四边：每帧最外一圈像素全透明（打包裁边、线性过滤不出毛边）；
  4. 叠加帧最亮处 alpha ≤ 0.8（抖动多 1 级）；可染的叠加帧 RGB 恒为白；
  5. 多帧的组写了 anim、frame、frames、fps；
  6. 图集（assets/atlas 里打过 myth 时）：每帧都在 myth 页里，原尺寸、锚点、blend、tint 和 meta 一致。

用法（仓库根目录）：art/.venv/bin/python art/post/test_myth_parts.py [--regen]
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
import myth_parts as P  # noqa: E402

ATLAS = P.V.ART.parent / "assets" / "atlas"
FAILS: list[str] = []


def check(cond: bool, msg: str) -> None:
    if not cond:
        FAILS.append(msg)


def main(args: list[str]) -> int:
    if "--regen" in args:
        before = (P.OUT / "sword_blade_0.png").read_bytes()
        P.build(["sword_blade"])
        check((P.OUT / "sword_blade_0.png").read_bytes() == before, "确定性：重画剑影和原来逐字节不同")
    meta = json.loads((P.OUT / "meta.json").read_text(encoding="utf-8"))
    files = meta["files"]
    check(meta["name"] == "myth" and meta["px_per_unit"] == 4, "meta：name 要是 myth、px_per_unit 4")
    on_disk = {p.name for p in P.OUT.glob("*.png")}
    check(on_disk == set(files), f"清单和盘上不一致：多 {sorted(on_disk - set(files))}，少 {sorted(set(files) - on_disk)}")
    # 每组：帧数、尺寸、锚点
    for name, spec in P.SPECS.items():
        _, size, anc, blend, tint, _, extra = spec
        body = sorted(k for k in files if re.fullmatch(rf"{name}(_\d+)?\.png", k))
        check(len(body) > 0, f"{name}：没有帧")
        for k in body:
            m = files[k]
            check(m["size"] == list(size), f"{k}：尺寸 {m['size']} ≠ {list(size)}")
            check(abs(m["anchor"][0] - anc[0]) < 1e-6 and abs(m["anchor"][1] - anc[1]) < 1e-6, f"{k}：锚点不对")
            check(m["blend"] == blend and m["tint"] == tint, f"{k}：blend / tint 不对")
            if len(body) > 1 and not extra.get("_variants"):
                check(all(f in m for f in ("anim", "frame", "frames", "fps")), f"{k}：多帧要写 anim、frame、frames、fps")
                check(m.get("frames") == len(body), f"{k}：frames 写的是 {m.get('frames')}，实际 {len(body)}")
        if "emit" in extra:
            for k in body:
                ek = k[:-4] + "_emit.png"
                check(ek in files, f"{k}：缺发光层 {ek}")
                if ek in files:
                    em = files[ek]
                    check(em["size"] == files[k]["size"] and em["anchor"] == files[k]["anchor"], f"{ek}：画布或锚点和本体不同")
                    check(em.get("layer_of") == name and em["blend"] == "add", f"{ek}：layer_of 要指回 {name}，blend 要是 add")
    for k in files:
        check(not re.search(r"_emit_\d+\.png$", k), f"{k}：旧命名（应为帧号在前、_emit 在后）")
        if "_emit" in k:
            check(k.endswith("_emit.png"), f"{k}：_emit 要在最后")
    # 像素
    for k, m in files.items():
        a = np.asarray(Image.open(P.OUT / k).convert("RGBA"))
        check(a.shape[1] == m["size"][0] and a.shape[0] == m["size"][1], f"{k}：PNG 尺寸和 meta 不同")
        al = a[..., 3]
        check(al[0].max() == 0 and al[-1].max() == 0 and al[:, 0].max() == 0 and al[:, -1].max() == 0, f"{k}：四边不透明")
        check(al.max() > 0, f"{k}：整张是空的")
        if m["blend"] == "add":
            check(al.max() <= round(P.PEAK * 255) + 1, f"{k}：叠加帧最亮 alpha {al.max()} 超过 0.8")
            if m["tint"]:
                check(bool((a[..., :3][al > 0] == 255).all()), f"{k}：可染的帧 RGB 要恒为白")
    # 图集
    idx_path = ATLAS / "index.json"
    idx = json.loads(idx_path.read_text(encoding="utf-8")) if idx_path.exists() else {}
    pages = idx.get("pages", {}).get("myth")
    if pages:
        frames, info = {}, {}
        for pg in pages:
            j = json.loads((ATLAS / pg).read_text(encoding="utf-8"))
            frames.update(j["frames"])
            info.update(j["meta"]["lantern"]["frames"])
            check(j["meta"]["lantern"]["pxPerUnit"] == 4, f"{pg}：pxPerUnit 要是 4")
        for k, m in files.items():
            key = f"myth/{k[:-4]}"
            check(key in frames, f"图集里没有 {key}")
            if key in frames:
                f = frames[key]
                check([f["sourceSize"]["w"], f["sourceSize"]["h"]] == m["size"], f"{key}：图集原尺寸不对")
                check(abs(f["anchor"]["x"] - m["anchor"][0]) < 1e-6 and abs(f["anchor"]["y"] - m["anchor"][1]) < 1e-6, f"{key}：图集锚点不对")
                check(info[key]["blend"] == m["blend"] and info[key]["tint"] == m["tint"], f"{key}：图集 blend / tint 不对")
        check(len(frames) == len(files), f"图集 myth 有 {len(frames)} 帧，meta 有 {len(files)} 张")
    else:
        print("（assets/atlas 里还没打 myth，跳过图集检查）")
    if FAILS:
        print(f"失败 {len(FAILS)} 项：")
        for f in FAILS:
            print("  - " + f)
        return 1
    print(f"通过：{len(files)} 张，{len(P.SPECS)} 组" + ("，图集一致" if pages else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
