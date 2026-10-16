"""赤面狐四个关键姿态的独立审图；旧帧读取正式图集，不重渲旧版。

    LANTERN_ART_DENSITY=2 /path/to/art/.venv/bin/python art/render/fox_sample.py
    LANTERN_ART_DENSITY=2 /path/to/art/.venv/bin/python art/render/fox_sample.py --review

只渲 move 第3帧、pounce 第1/3/5帧到 art/out/fox-r3-sample@2x，绝不打包运行图集。
样张内帧号按采样顺序写入；source_frames.json 记录其与正式动作帧的对应，不能当完整动画导入。
原生320px审图、等效1倍160px审图和相同月夜光场合成均与正式帧逐项对应。
月夜图仅为素材合成审查，不是实机截图。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
import numpy as np

ART = Path(__file__).resolve().parents[1]
for directory in (ART, ART / "models", ART / "post", ART / "render"):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))
from style import style as S
import contact_sheet as CS

OUT = ART / "out" / f"fox-r3-sample@{S.DENSITY:g}x"
REVIEW = OUT / "review"
POSES = [("move", 3, 8, "MOVE"), ("pounce", 1, 6, "WINDUP"),
         ("pounce", 3, 6, "AIRBORNE"), ("pounce", 5, 6, "LAND")]


def render():
    from pipeline import render_asset
    import fox
    from fox_style import build_styled_fox

    render_asset("fox", S.FRAME["elite"], build_styled_fox,
                 [(anim, "E", frame, count) for anim, frame, count, _ in POSES], OUT,
                 pose=fox.pose_fox, sockets_wanted=("eyes",), anchor=S.BIG_ENEMY_ANCHOR,
                 grain="fox", meta_extra={"category": "elite", "layers": ["emit"],
                    "shadow_radius_px": round(24 * S.PX_PER_UNIT * 0.8),
                    "anim_extra": {"move": {"fps": 12}, "pounce": {"fps": 12, "loop": False, "windup_frames": 2}}})


def atlas_frames():
    atlas = ART.parent / "assets" / "atlas"
    data = json.loads((atlas / "actors.json").read_text(encoding="utf-8"))
    sheet = Image.open(atlas / data["meta"]["image"]).convert("RGBA")
    meta = data["meta"]["lantern"]["assets"]["fox"]

    def extract(name):
        entry = data["frames"].get(name)
        if entry is None:
            return None
        rect, size, src = entry["frame"], entry["sourceSize"], entry["spriteSourceSize"]
        full = Image.new("RGBA", (size["w"], size["h"]))
        full.alpha_composite(sheet.crop((rect["x"], rect["y"], rect["x"] + rect["w"], rect["y"] + rect["h"])),
                             (src["x"], src["y"]))
        return full

    frames = []
    for anim, index, _, _ in POSES:
        key = f"{anim}_E_{index:02d}"
        frames.append({"key": key, "rgba": extract(f"fox/{key}"), "emit": extract(f"fox/{key}_emit")})
    return meta, frames


def tile(frame, meta, night=False):
    width, height = meta["size"]
    at = CS.anchor_px(meta)
    base = CS.paper(width, height, seed=7)
    CS.place(base, frame, meta, at)
    if not night:
        return base.convert("RGB")
    emit = np.zeros((height, width, 3), np.float32)
    CS.place_emit(emit, frame, meta, at)
    # 同一暖灯位于左下方，妖物处在月夜/灯光边缘，不能给新版单独提亮。
    radius = width * 1.3
    return CS.night_composite(base, emit, [(at[0] - width * 0.66, at[1] + height * 0.20,
                                          radius, S.LANTERN_LIGHT)])


def review():
    REVIEW.mkdir(parents=True, exist_ok=True)
    old_meta, old = atlas_frames()
    new_asset = CS.load_asset(OUT / "fox")
    new_meta, new = new_asset["meta"], new_asset["frames"]
    assert len(new) == 4
    assert old_meta["size"] == new_meta["size"] == [320, 320]
    assert old_meta["anchor"] == new_meta["anchor"] == [0.5, 0.8]
    manifest = []
    for source, frame, pose in zip(old, new, POSES):
        box = frame["rgba"].getchannel("A").getbbox()
        assert box and min(box[0], box[1], 320 - box[2], 320 - box[3]) > 2, (source["key"], box)
        manifest.append({"source": source["key"], "sample": frame["key"], "pose": pose[-1], "bounds": box})
    (OUT / "source_frames.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    font_path = ART.parent / "assets/fonts/NotoSerifSC-subset.ttf"
    for night, small, name in [(False, False, "fox-r3-native"), (True, False, "fox-r3-moonlight"),
                               (False, True, "fox-r3-game-size"), (True, True, "fox-r3-game-size-moonlight")]:
        cell = 160 if small else 320
        font = ImageFont.truetype(str(font_path), 13 if small else 20)
        board = Image.new("RGB", (cell * 4, (cell + 54) * 2 + 34), CS.rgb(S.PAPER))
        draw = ImageDraw.Draw(board)
        draw.text((12, 6), "ASSET REVIEW / identical camera, anchor and lighting / NOT IN-GAME", font=font, fill=CS.rgb(S.INK["jiao"]))
        for row, (label, frames, meta) in enumerate((("ATLAS", old, old_meta), ("CANDIDATE", new, new_meta))):
            for col, (frame, pose) in enumerate(zip(frames, POSES)):
                x, y = col * cell, 34 + row * (cell + 54)
                shown = "NEW" if small and label == "CANDIDATE" else label
                draw.text((x + 8, y + 4), f"{shown} / {pose[-1]}", font=font, fill=CS.rgb(S.INK["jiao"]))
                image = tile(frame, meta, night)
                if small:
                    image = image.resize((cell, cell), Image.Resampling.LANCZOS)
                board.paste(image, (x, y + 28))
        board.save(REVIEW / f"{name}.png")
    print(f"四姿态审图：{REVIEW}")


if __name__ == "__main__":
    if S.DENSITY != 2:
        raise SystemExit("请设置 LANTERN_ART_DENSITY=2，与正式桌面图集一致")
    if "--review" not in sys.argv:
        render()
    review()
