"""石妖三个姿态小样，复用现有出图、图集还原、contact_sheet 与月夜合成。

    LANTERN_ART_DENSITY=2 /path/to/art/.venv/bin/python art/render/golem_sample.py
    LANTERN_ART_DENSITY=2 /path/to/art/.venv/bin/python art/render/golem_sample.py --review
    LANTERN_ART_DENSITY=2 /path/to/art/.venv/bin/python art/render/golem_sample.py --full

只渲 move_E_00/03/06；样张目录不是完整8帧动画，不可直接打包。
输出 out/golem-r4-sample@2x/review；--full 只读正式8帧，写 out/review@2x/golem-r4 和对照动图。
月夜图是素材合成，不是实机截图。
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw

ART = Path(__file__).resolve().parents[1]
for directory in (ART, ART / "models", ART / "post", ART / "render"):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))
from style import style as S
import contact_sheet as CS
from fox_sample import tile
from replace_atlas_assets import read_group, restore_assets

OUT = ART / "out" / f"golem-r4-sample@{S.DENSITY:g}x"
POSES = [0, 3, 6]


def main():
    full = "--full" in sys.argv
    poses = list(range(8)) if full else POSES
    if not full and "--review" not in sys.argv:
        import produce
        produce.produce("golem", {}, out_root=OUT / "candidate", only_frames={"move": POSES})
    atlas = ART.parent / "assets/atlas"
    with tempfile.TemporaryDirectory(prefix="golem-atlas-") as restored:
        old_dir = restore_assets(atlas, read_group(atlas, "actors"), Path(restored), {"golem"})["golem"]
        old = CS.load_asset(old_dir)
    new = CS.load_asset(ART / "out" / S.ASSETS_DIR_NAME / "golem" if full else OUT / "candidate/golem")
    assert old["meta"]["size"] == new["meta"]["size"] == [224, 224]
    assert old["meta"]["anchor"] == new["meta"]["anchor"] == [0.5, 0.8]
    old["frames"] = [f for f in old["frames"] if f["idx"] in poses]
    assert len(new["frames"]) == len(poses)
    if full:
        for key in ("anims", "game_radius", "px_per_unit", "layers", "required_sockets", "shadow_radius_px"):
            assert old["meta"].get(key) == new["meta"].get(key), key
    mapping = []
    for index, (before, after) in enumerate(zip(old["frames"], new["frames"])):
        box = after["rgba"].getchannel("A").getbbox()
        assert box and min(box[0], box[1], 224 - box[2], 224 - box[3]) > 2
        mapping.append({"source": before["key"], "sample": after["key"], "bounds": box})
        before["key"] = f"ATLAS move_E_{poses[index]:02d}"
        after["key"] = f"NEW move_E_{poses[index]:02d}"
    if not full:
        (OUT / "source_frames.json").write_text(json.dumps(mapping, indent=2), encoding="utf-8")
    review = ART / "out" / f"review@{S.DENSITY:g}x" / "golem-r4" if full else OUT / "review"
    review.mkdir(parents=True, exist_ok=True)
    for night, name in [(False, "native"), (True, "moonlight")]:
        assets = []
        for asset in (old, new):
            frames = [dict(frame, rgba=tile(frame, asset["meta"], night=night).convert("RGBA")) for frame in asset["frames"]]
            assets.append(dict(asset, frames=frames))
        board = CS.sheet(assets)
        board.save(review / f"golem-r4-{name}.png")
        board.resize((board.width // 2, board.height // 2), Image.Resampling.LANCZOS).save(review / f"golem-r4-{name}-game-size.png")
    if full:
        frames = []
        for before, after in zip(old["frames"], new["frames"]):
            pair = Image.new("RGB", (448, 492), CS.rgb(S.PAPER))
            for row, night in enumerate((False, True)):
                for col, (label, frame, meta) in enumerate((("ATLAS", before, old["meta"]), ("NEW", after, new["meta"]))):
                    x, y = col * 224, row * 246
                    ImageDraw.Draw(pair).text((x + 8, y + 4), f"{label} / {'MOON' if night else 'DAY'}", fill=CS.rgb(S.INK["jiao"]))
                    pair.paste(tile(frame, meta, night=night), (x, y + 22))
            frames.append(pair)
        CS.gif(frames, review / "golem-move-comparison.gif", new["meta"]["anims"]["move"]["fps"], zoom_k=1)
    print(f"石妖{len(poses)}姿态对比（上旧下新；素材合成）：{review}")


if __name__ == "__main__":
    if S.DENSITY != 2:
        raise SystemExit("请设置 LANTERN_ART_DENSITY=2")
    main()
