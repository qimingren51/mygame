"""检查 assets/atlas/ 能不能被桌面版正常加载（规则照 crates/view/src/atlas.rs 写）。

用法（在仓库根目录下）：
    art/.venv/bin/python art/post/check_atlas.py            # 默认检查 assets/atlas
    art/.venv/bin/python art/post/check_atlas.py <目录>

检查项：
  - index.json 列出的每页 JSON 和 PNG 都在，PNG 尺寸与 meta.size 一致；
  - 所有页的 pxPerUnit 相同（不同时游戏启动即退出）；
  - 帧名跨页不重复（重复时后读的会悄悄覆盖前面的）；
  - 帧矩形在页内，裁边信息自洽；
  - animations 引用的帧都存在；角色元数据里每个动画、每个方向都有序列；
  - ui/ 开头的帧不裁边（矩形 = 原图大小，界面代码不处理裁边）；
  - skin/skin.json（九宫格皮肤）与文件一致，slice 合法；screens/ 的图尺寸正确。
有错误时退出码为 1。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]


def check(atlas: Path) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    info: list[str] = []
    index = json.loads((atlas / "index.json").read_text(encoding="utf-8"))
    files = sorted(f for pages in index.get("pages", {}).values() for f in pages)
    if set(index.get("atlases", [])) != set(index.get("pages", {})):
        errors.append(f"index.json 的 atlases {index.get('atlases')} 与 pages 的键 {sorted(index.get('pages', {}))} 不一致")
    ppu: float | None = None
    owner: dict[str, str] = {}
    animations: dict[str, list[str]] = {}
    assets: dict[str, dict] = {}
    total = 0
    for file in files:
        path = atlas / file
        if not path.exists():
            errors.append(f"缺少 {file}")
            continue
        page = json.loads(path.read_text(encoding="utf-8"))
        meta = page["meta"]
        lan = meta["lantern"]
        p = float(lan["pxPerUnit"])
        if ppu is None:
            ppu = p
        elif abs(ppu - p) > 1e-3:
            errors.append(f"{file} 的 pxPerUnit {p} 与其他页 {ppu} 不一致（游戏会启动失败）")
        png = atlas / meta["image"]
        if not png.exists():
            errors.append(f"{file} 引用的 {meta['image']} 不存在")
            continue
        total += png.stat().st_size + path.stat().st_size
        with Image.open(png) as im:
            pw, ph = im.size
        if (pw, ph) != (meta["size"]["w"], meta["size"]["h"]):
            errors.append(f"{meta['image']} 实际尺寸 {pw}×{ph}，meta.size 写的是 {meta['size']}")
        for name, f in page["frames"].items():
            if name in owner:
                errors.append(f"帧 {name} 在 {owner[name]} 和 {file} 里重复")
            owner[name] = file
            r, s, src = f["frame"], f["spriteSourceSize"], f["sourceSize"]
            if r["x"] + r["w"] > pw or r["y"] + r["h"] > ph:
                errors.append(f"{name} 的矩形超出 {meta['image']}")
            if (r["w"], r["h"]) != (s["w"], s["h"]) or s["x"] + s["w"] > src["w"] or s["y"] + s["h"] > src["h"]:
                errors.append(f"{name} 的裁边信息不自洽")
            if name.startswith("ui/") and (s["x"], s["y"], s["w"], s["h"]) != (0, 0, src["w"], src["h"]):
                errors.append(f"{name} 被裁了边（ui 图集要用 --no-trim 打包）")
            if name not in lan.get("frames", {}):
                errors.append(f"{name} 在 meta.lantern.frames 里没有 blend / tint")
        animations.update(page.get("animations", {}))
        assets.update(lan.get("assets", {}))
        info.append(f"{file}: {len(page['frames'])} 帧，{pw}×{ph}，pxPerUnit {p:g}")
    for anim, seq in animations.items():
        missing = [f for f in seq if f not in owner]
        if missing:
            errors.append(f"动画 {anim} 引用了不存在的帧 {missing[:3]}")
    for name, a in assets.items():
        for an, spec in a.get("anims", {}).items():
            for d in spec.get("dirs", []):
                if f"{name}/{an}_{d}" not in animations:
                    errors.append(f"{name} 的动画 {an} 缺少方向 {d} 的序列")
    if index.get("paper") and not (atlas / "paper.png").exists():
        errors.append("index.json 写了 paper: true，但没有 paper.png")

    skin = atlas / "skin" / "skin.json"
    if skin.exists():
        sk = json.loads(skin.read_text(encoding="utf-8"))
        for name, it in sk.get("items", {}).items():
            png = skin.parent / it["file"]
            if not png.exists():
                errors.append(f"skin: {name} 的 {it['file']} 不存在")
                continue
            total += png.stat().st_size
            with Image.open(png) as im:
                w, h = im.size
            if [w, h] != list(it["size"]):
                errors.append(f"skin: {name} 实际 {w}×{h}，清单写 {it['size']}")
            l, t, rr, b = it["slice"]
            if min(l, t, rr, b) < 0 or (any(it["slice"]) and (l + rr >= w or t + b >= h)):
                errors.append(f"skin: {name} 的 slice {it['slice']} 不合法（尺寸 {w}×{h}）")
            for k in ("center", "sides"):
                if it.get(k) not in ("stretch", "tile"):
                    errors.append(f"skin: {name} 的 {k} 应为 stretch 或 tile")
        info.append(f"skin: {len(sk.get('items', {}))} 项，scale {sk.get('scale')}")

    screens = atlas / "screens"
    if screens.exists():
        for png in sorted(screens.glob("*.png")):
            total += png.stat().st_size
            with Image.open(png) as im:
                info.append(f"screens/{png.name}: {im.size[0]}×{im.size[1]} {im.mode}")
                if png.name == "title.png" and im.size != (1920, 1080):
                    errors.append(f"screens/title.png 应为 1920×1080，实际 {im.size}")
    info.append(f"合计 {total / 1024 / 1024:.1f} MB（不含 paper.png）")
    return errors, info


def main(argv: list[str]) -> int:
    atlas = Path(argv[0]) if argv else ROOT / "assets" / "atlas"
    errors, info = check(atlas)
    for line in info:
        print("  " + line)
    for e in errors:
        print("✗ " + e)
    print("通过" if not errors else f"{len(errors)} 个错误")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
