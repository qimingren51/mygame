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
  - skin/skin.json（九宫格皮肤）与文件一致，slice 合法；screens/ 的图尺寸正确；
  - screens/hub/hub.json（灯驿长卷）文件齐全、尺寸与 rect 一致、在画面和安全区内，
    人物与 hub.ron、心灯与 meta.ron 对得上，心灯四层齐全，晨光配同尺寸的 mask。
有错误时退出码为 1。
"""

from __future__ import annotations

import json
import re
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
    hub = screens / "hub" / "hub.json"
    if hub.exists():
        total += check_hub(hub, errors, info)
    info.append(f"合计 {total / 1024 / 1024:.1f} MB（不含 paper.png）")
    return errors, info


def ron_ids(path: Path) -> list[str]:
    """按文件顺序取 RON 里各条目的 id（meta.ron 的心灯节点、hub.ron 的人物）。"""
    return re.findall(r'\(id: "([a-z0-9_]+)"', path.read_text(encoding="utf-8"))


def check_hub(path: Path, errors: list[str], info: list[str]) -> int:
    """灯驿长卷 screens/hub/hub.json：文件齐全、尺寸与 rect 一致、都在画面内，人物和心灯与内容数据对得上。
    每一层都写 rect: [x, y, w, h]（底图像素）；心灯四层 body、flame（带 base）、core、glow；晨光图配同尺寸的 mask。
    返回文件总字节数。"""
    d = path.parent
    hub = json.loads(path.read_text(encoding="utf-8"))
    W, H = hub["size"]
    total = path.stat().st_size

    def inside(what: str, x, y, w=0, h=0, area=(0, 0, W, H)):
        ax, ay, aw, ah = area
        if x < ax or y < ay or x + w > ax + aw or y + h > ay + ah:
            where = "安全区" if area != (0, 0, W, H) else f"{W}×{H} 的画面"
            errors.append(f"hub: {what}（{x}, {y}, {w}, {h}）超出{where}")

    def layer(what: str, spec: dict, mode: str | None = None, blend: str | None = None, file: str | None = None):
        """一层叠图：文件在、尺寸等于 rect 的宽高、rect 在画面内、颜色模式和混合方式对。"""
        nonlocal total
        file = file or spec["file"]
        png = d / file
        if not png.exists():
            errors.append(f"hub: {what} 的 {file} 不存在")
            return
        total += png.stat().st_size
        x, y, w, h = spec["rect"]
        with Image.open(png) as im:
            if mode and im.mode != mode:
                errors.append(f"hub: {file} 应为 {mode}，实际 {im.mode}")
            if im.size != (w, h):
                errors.append(f"hub: {file} 实际 {im.size[0]}×{im.size[1]}，rect 写的是 {w}×{h}")
        inside(f"{what}（{file}）", x, y, w, h)
        if blend and spec.get("blend") != blend:
            errors.append(f"hub: {what} 的 blend 应为 {blend}，实际 {spec.get('blend')}")

    layer("底图", {"file": "hub.png", "rect": [0, 0, W, H]}, "RGB")
    safe = tuple(hub.get("safe", (0, 0, W, H)))
    inside("safe", *safe)
    chars = [c["id"] for c in hub.get("characters", [])]
    want = ron_ids(ROOT / "assets" / "data" / "hub.ron")
    if chars != want:
        errors.append(f"hub: characters {chars} 应与 hub.ron 的顺序 {want} 一致")
    for c in hub.get("characters", []):
        inside(f"{c['id']} 的 rect", *c["rect"], area=safe)
        inside(f"{c['id']} 的 label", *c["label"], area=safe)
        inside(f"{c['id']} 的 light", *c["light"][:2], area=safe)
    lamps = hub.get("lamps", {})
    nodes = ron_ids(ROOT / "assets" / "data" / "meta.ron")
    if sorted(lamps) != sorted(nodes):
        errors.append(f"hub: lamps 的节点 {sorted(lamps)} 应与 meta.ron {sorted(nodes)} 一致")
    for lid, lp in lamps.items():
        missing = [k for k in ("body", "flame", "core", "glow") if k not in lp]
        if missing:
            errors.append(f"hub: 心灯 {lid} 缺少 {missing}")
            continue
        layer(f"心灯 {lid} 的灯身", lp["body"], "RGBA", "normal")
        layer(f"心灯 {lid} 的火苗", lp["flame"], "RGBA", "normal")
        layer(f"心灯 {lid} 的内圈光", lp["core"], "RGBA", "add")
        layer(f"心灯 {lid} 的光晕", lp["glow"], "RGBA", "add")
        inside(f"心灯 {lid} 的灯身", *lp["body"]["rect"], area=safe)
        bx, by = lp["flame"].get("base", (-1, -1))
        fx, fy, fw, fh = lp["flame"]["rect"]
        if not (fx <= bx <= fx + fw and fy <= by <= fy + fh):
            errors.append(f"hub: 心灯 {lid} 的火苗 base {bx, by} 不在火苗 rect 里")
    for rid, dp in hub.get("dawn", {}).items():
        layer(f"晨光 {rid}", dp, "RGBA", "normal")
        if "mask" not in dp:
            errors.append(f"hub: 晨光 {rid} 缺少 mask")
        else:
            layer(f"晨光 {rid} 的 mask", dp, "L", file=dp["mask"])
        if "glow" in dp:
            layer(f"晨光 {rid} 的辉光", dp["glow"], "RGBA", "add")
    for r in hub.get("text_safe", []):
        inside("text_safe", *r, area=safe)
    info.append(f"screens/hub: {len(chars)} 个人物、{len(lamps)} 盏心灯、{len(hub.get('dawn', {}))} 处晨光，"
                f"{total / 1024 / 1024:.1f} MB")
    return total


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
