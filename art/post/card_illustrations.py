#!/usr/bin/env python3
"""把正式 4:3 卡面导入独立 cards 图集，保留现有 ui 图集。

在仓库根目录运行：
    art/.venv/bin/python art/post/card_illustrations.py --source art/out/cards/source --out assets/atlas

每次提供全部 39 张原图；文件名见 CARD_NAMES。只做 Lanczos 缩小，不裁切、
补画或调色。中间文件留在临时目录，最终仅写 cards 图集和 index.json。
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
SIZE = (768, 576)
PX_PER_UNIT = 4.0  # 桌面版 actors / boss / ground / lanterns / ui / vfx 均为此密度。

# 与 describe.rs 的 OfferInfo.art 一致：合璧直接用 card_<id>，没有 fusion_ 前缀。
CARD_NAMES = {
    "card_lamp": "灯火",
    "card_lamp_evo": "不夜城",
    "card_lamp_mut": "冰火两重天",
    "card_sword": "符剑",
    "card_sword_evo": "万剑归宗",
    "card_sword_mut": "赤霄",
    "card_bell": "霜铃",
    "card_bell_evo": "寒山钟",
    "card_bell_mut": "冻土",
    "card_crane": "纸鹤",
    "card_crane_evo": "千鹤引",
    "card_crane_mut": "铁鹤",
    "card_seal": "山印",
    "card_seal_evo": "镇岳",
    "card_seal_mut": "竹印",
    "card_coin_sword": "铜钱剑",
    "card_coin_sword_evo": "天罡",
    "card_phoenix": "百鸟朝凤",
    "card_sword_grove": "万剑冢",
    "card_frost_rain": "霜天剑雨",
    "card_jianyi": "剑意",
    "card_ruimu": "锐目",
    "card_xunfeng": "迅锋",
    "card_zhezhi": "折纸",
    "card_huichun": "回春",
    "card_jixing": "疾行",
    "card_jingxin": "静心",
    "card_hanyi": "寒意",
    "card_yinhun": "引魂",
    "card_changming": "长明",
    "card_luxin": "炉心",
    "card_dengxin": "灯芯",
    "card_houde": "厚德",
    "card_panshi": "磐石",
    "card_zaiwu": "载物",
    "card_qinggong": "轻功",
    "card_juhun": "聚魂",
    "card_lotus": "莲子",
    "card_oil": "灯油",
}


def check_destination(out: Path) -> None:
    """避免新增页导致游戏因密度不同或同名帧而加载错误；不修改其他组。"""
    index = out / "index.json"
    if not index.exists():
        return
    data = json.loads(index.read_text(encoding="utf-8"))
    keys = {f"ui/{frame}" for frame in CARD_NAMES}
    for group, pages in data["pages"].items():
        if group == "cards":
            continue
        for filename in pages:
            page = json.loads((out / filename).read_text(encoding="utf-8"))
            density = float(page["meta"]["lantern"]["pxPerUnit"])
            if not math.isclose(density, PX_PER_UNIT, rel_tol=0.0, abs_tol=1e-3):
                raise SystemExit(f"{filename}: pxPerUnit 为 {density}，卡面需要与桌面图集一致的 {PX_PER_UNIT}")
            duplicates = keys.intersection(page["frames"])
            if duplicates:
                raise SystemExit(f"{filename} 已有卡面帧，不能重复导入：{', '.join(sorted(duplicates))}")


def import_cards(source: Path, out: Path) -> None:
    missing = [f"{frame}.png" for frame in CARD_NAMES if not (source / f"{frame}.png").is_file()]
    if missing:
        raise SystemExit(f"卡面需全部 {len(CARD_NAMES)} 张齐备；{source} 缺少：\n" + "\n".join(missing))
    check_destination(out)
    # 整批校验、缩小和打包成功后才替换目标页；原图和临时独立 PNG 均不进入 assets。
    with tempfile.TemporaryDirectory(prefix="lantern-cards-") as tmp:
        staging = Path(tmp)
        normalized = staging / "ui"
        packed = staging / "atlas"
        normalized.mkdir()
        files = {}
        for frame, name in CARD_NAMES.items():
            filename = f"{frame}.png"
            with Image.open(source / filename) as original:
                width, height = original.size
                if width * 3 != height * 4:
                    raise SystemExit(f"{filename}: {width}×{height} 不是 4:3；导入不会裁切画面")
                if width < SIZE[0] or height < SIZE[1]:
                    raise SystemExit(f"{filename}: {width}×{height} 小于 768×576；需要更高分辨率原图")
                image = original.convert("RGBA")
                if image.size != SIZE:
                    image = image.resize(SIZE, Image.Resampling.LANCZOS)
                image.save(normalized / filename)
            files[filename] = {"size": list(SIZE), "anchor": [0.5, 0.5], "name": name, "tint": False}
        meta = {"name": "ui", "px_per_unit": PX_PER_UNIT, "files": files}
        (normalized / "meta.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
        pages = build_atlas("cards", [normalized], packed, trim_frames=False)
        out.mkdir(parents=True, exist_ok=True)
        for filename in pages:
            for suffix in (".png", ".json"):
                item = Path(filename).with_suffix(suffix)
                shutil.copyfile(packed / item, out / item)
        update_index(out, atlas="cards", pages=pages)
    print(f"已导入 {len(CARD_NAMES)} 张 768×576 卡面；帧名 ui/card_*，pxPerUnit {PX_PER_UNIT:g}；保留其他图集组")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", type=Path, default=ROOT / "art/out/cards/source", help="全部卡面原图目录")
    parser.add_argument("--out", type=Path, default=ROOT / "assets/atlas", help="目标图集目录")
    args = parser.parse_args()
    import_cards(args.source, args.out)


if __name__ == "__main__":
    main()
