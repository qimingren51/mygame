#!/usr/bin/env python3
"""用新渲染替换 actors / lanterns 中的指定素材，其余帧从现有图集无损还原。

    python3 art/post/replace_atlas_assets.py --group actors art/out/assets@2x/hero
    python3 art/post/replace_atlas_assets.py --group lanterns art/out/assets@2x/lantern_{red,mirror,frost}

--atlas 默认为 assets/atlas。只替换素材目录 meta.json 声明的名字，不重渲其他
素材，不新增覆盖同名帧的图集。还原 PNG 只写临时目录，装箱沿用 pack_atlas.py。
"""

from __future__ import annotations

import argparse
import json
import math
import shutil
import tempfile
from pathlib import Path

from PIL import Image

from pack_atlas import build_atlas, update_index

ROOT = Path(__file__).resolve().parents[2]
PX_PER_UNIT = 4.0


def read_group(atlas: Path, group: str) -> dict[str, dict]:
    index = json.loads((atlas / "index.json").read_text(encoding="utf-8"))
    filenames = index["pages"].get(group)
    if not filenames:
        raise SystemExit(f"{atlas}: 没有 {group} 图集组")
    pages = {name: json.loads((atlas / name).read_text(encoding="utf-8")) for name in filenames}
    for name, page in pages.items():
        density = float(page["meta"]["lantern"]["pxPerUnit"])
        if not math.isclose(density, PX_PER_UNIT, rel_tol=0.0, abs_tol=1e-3):
            raise SystemExit(f"{name}: 密度为 {density}，此工具用于桌面版密度 {PX_PER_UNIT:g} 的图集")
    return pages


def asset_metadata(pages: dict[str, dict]) -> dict[str, dict]:
    return {name: meta for page in pages.values() for name, meta in page["meta"]["lantern"].get("assets", {}).items()}


def restore_assets(atlas: Path, pages: dict[str, dict], out: Path, names: set[str]) -> dict[str, Path]:
    """按原画布和裁切偏移还原；paste 不带 mask，避免把 alpha 再乘一次。"""
    assets = asset_metadata(pages)
    folders = {name: out / name for name in assets if name in names}
    for name, folder in folders.items():
        folder.mkdir(parents=True)
        meta = {"name": name, **assets[name]}
        (folder / "meta.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    if not folders:
        return folders
    for page in pages.values():
        with Image.open(atlas / page["meta"]["image"]) as source:
            sheet = source.convert("RGBA")
            for key, frame in page["frames"].items():
                name, filename = key.split("/", 1)
                if name not in names:
                    continue
                if frame["rotated"]:
                    raise SystemExit(f"{key}: 不支持旋转帧；现有桌面打包器不产生此格式")
                rect, offset, size = frame["frame"], frame["spriteSourceSize"], frame["sourceSize"]
                pixels = sheet.crop((rect["x"], rect["y"], rect["x"] + rect["w"], rect["y"] + rect["h"]))
                restored = Image.new("RGBA", (size["w"], size["h"]))
                restored.paste(pixels, (offset["x"], offset["y"]))
                restored.save(folders[name] / f"{filename}.png")
    return folders


def replacement_name(folder: Path) -> str:
    meta = json.loads((folder / "meta.json").read_text(encoding="utf-8"))
    name = meta.get("name") or folder.name
    density = float(meta.get("px_per_unit", 0))
    if not math.isclose(density, PX_PER_UNIT, rel_tol=0.0, abs_tol=1e-3):
        raise SystemExit(f"{folder}: meta.json 必须声明 px_per_unit: {PX_PER_UNIT:g}")
    if "anims" not in meta or "files" in meta:
        raise SystemExit(f"{folder}: 需要角色/灯笼渲染目录的 anims 元数据")
    # 渲染未完成时不能先删掉旧动画；按新 meta 检查动画本体及声明的附属层。
    suffixes = [""] + [f"_{layer}" for layer in meta.get("layers", [])]
    expected = [
        f"{anim}_{direction}_{frame:02d}{suffix}.png"
        for anim, spec in meta["anims"].items()
        for direction in spec.get("dirs", ["E"])
        for frame in range(spec["frames"])
        for suffix in suffixes
    ]
    missing = [file for file in expected if not (folder / file).is_file()]
    if missing:
        raise SystemExit(f"{folder}: 渲染不完整，缺少 {len(missing)} 帧，例如 {', '.join(missing[:3])}")
    return name


def retain_metadata(old: dict[str, dict], packed: Path, filenames: list[str], replaced: set[str]) -> None:
    """装箱只改变页坐标；未替换素材的帧属性、动画顺序、挂点等沿用原数据。"""
    old_frames = {key: value for page in old.values() for key, value in page["frames"].items()}
    old_info = {key: value for page in old.values() for key, value in page["meta"]["lantern"]["frames"].items()}
    animations = {
        key: value for page in old.values() for key, value in page["animations"].items()
        if key.split("/")[0] not in replaced
    }
    assets = {name: meta for name, meta in asset_metadata(old).items() if name not in replaced}
    fresh = [json.loads((packed / file).read_text(encoding="utf-8")) for file in filenames]
    for page in fresh:
        animations.update({key: value for key, value in page["animations"].items() if key.split("/")[0] in replaced})
        assets.update({name: meta for name, meta in page["meta"]["lantern"].get("assets", {}).items() if name in replaced})
    for i, (filename, page) in enumerate(zip(filenames, fresh)):
        lantern = page["meta"]["lantern"]
        for key, frame in page["frames"].items():
            if key.split("/")[0] in replaced:
                continue
            original = old_frames[key]
            if frame["sourceSize"] != original["sourceSize"] or frame["spriteSourceSize"] != original["spriteSourceSize"]:
                raise SystemExit(f"{key}: 重新裁边改变了原矩形，目标图集尚未改写")
            page["frames"][key] = {**original, "frame": frame["frame"]}
            lantern["frames"][key] = old_info[key]
        if i == 0:
            page["animations"] = animations
            lantern["assets"] = assets
        (packed / filename).write_text(json.dumps(page, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def replace_assets(atlas: Path, group: str, sources: list[Path]) -> None:
    old = read_group(atlas, group)
    assets = asset_metadata(old)
    owners = {key.split("/")[0] for page in old.values() for key in page["frames"]}
    if owners != set(assets):
        raise SystemExit(f"{group}: 帧所属素材与 assets 元数据不一致，不能完整还原")
    replacements = {}
    for folder in sources:
        name = replacement_name(folder)
        if name not in assets:
            raise SystemExit(f"{name}: 不属于 {group} 组，不能通过替换工具新增素材")
        if name in replacements:
            raise SystemExit(f"{name}: 重复指定替换目录")
        replacements[name] = folder
    with tempfile.TemporaryDirectory(prefix=f"lantern-replace-{group}-") as tmp:
        staging = Path(tmp)
        restored = restore_assets(atlas, old, staging / "sources", set(assets) - replacements.keys())
        folders = [replacements[name] if name in replacements else restored[name] for name in assets]
        packed = staging / "atlas"
        filenames = build_atlas(group, folders, packed)
        retain_metadata(old, packed, filenames, set(replacements))
        new_files = {file for name in filenames for file in (name, str(Path(name).with_suffix(".png")))}
        for file in sorted(new_files):
            shutil.copyfile(packed / file, atlas / file)
        update_index(atlas, atlas=group, pages=filenames)
        # 分页数变动时只移除本组不再引用的旧页；其他组和源渲染目录不动。
        old_files = set(old) | {page["meta"]["image"] for page in old.values()}
        for file in old_files - new_files:
            (atlas / file).unlink()
    print(f"{group}: 已替换 {', '.join(replacements)}；其余 {len(restored)} 个素材保留")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--atlas", type=Path, default=ROOT / "assets/atlas", help="读取并更新的现有图集目录")
    parser.add_argument("--group", choices=("actors", "lanterns"), required=True)
    parser.add_argument("sources", nargs="+", type=Path, help="待替换素材的完整渲染目录（含 meta.json）")
    args = parser.parse_args()
    replace_assets(args.atlas, args.group, args.sources)


if __name__ == "__main__":
    main()
