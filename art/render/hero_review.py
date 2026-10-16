"""正式主角渲完后的独立审图，不要求敌人和场景素材存在，也不重新渲染。

    LANTERN_ART_DENSITY=2 art/.venv/bin/python art/render/hero_review.py

输出 art/out/review@2x/hero-r2/：八方向、关键动作、五种动作动图、正式头像旧新对照。
主角按游戏方式叠上红纸灯；头像旧图直接读取当前正式 ui 图集。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ART = Path(__file__).resolve().parents[1]
for directory in (ART, ART / "models", ART / "render", ART / "post"):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

import contact_sheet as CS
import produce as PR
from style import style as S

OUT = PR.REVIEW / "hero-r2"


def portrait_comparison():
    atlas_dir = ART.parent / "assets" / "atlas"
    atlas = json.loads((atlas_dir / "ui.json").read_text(encoding="utf-8"))
    frame = atlas["frames"]["ui/portrait_hero"]
    box = frame["frame"]
    sheet = Image.open(atlas_dir / atlas["meta"]["image"]).convert("RGBA")
    cropped = sheet.crop((box["x"], box["y"], box["x"] + box["w"], box["y"] + box["h"]))
    size, source = frame["sourceSize"], frame["spriteSourceSize"]
    old = Image.new("RGBA", (size["w"], size["h"]))
    old.alpha_composite(cropped, (source["x"], source["y"]))
    new = Image.open(PR.ASSETS / "portrait" / "portrait_hero.png").convert("RGBA")
    board = Image.new("RGB", (720, 460), S.PAPER)
    draw = ImageDraw.Draw(board)
    font = ImageFont.truetype(str(ART.parent / "assets/fonts/NotoSerifSC-subset.ttf"), 20)
    for index, (label, image) in enumerate((("CURRENT ATLAS", old), ("NEW PORTRAIT", new))):
        x = index * 360
        draw.text((x + 35, 20), label, font=font, fill=S.INK["jiao"])
        large = image.resize((256, 256), Image.Resampling.LANCZOS)
        board.paste(large, (x + 52, 65), large)
        icon = image.resize((64, 64), Image.Resampling.LANCZOS)
        board.paste(icon, (x + 148, 350), icon)
        draw.text((x + 118, 420), "64px preview", font=font, fill=S.INK["zhong"])
    board.save(OUT / "portrait-comparison.png")


def hero_contact_sheets():
    OUT.mkdir(parents=True, exist_ok=True)
    hero = PR.load_assets(["hero"])["hero"]
    moments = {"idle": 0, "walk": 2, "dash": 2, "hurt": 0, "death": 3}
    rows = [PR.view(hero, [f"{action}_{direction}_{frame:02d}" for direction in S.DIRS])
            for action, frame in moments.items()]
    CS.sheet(rows).save(OUT / "eight-directions.png")
    CS.sheet(rows, night=True).save(OUT / "eight-directions-night.png")
    actions = [("walk", "S"), ("walk", "E"), ("dash", "SE"), ("hurt", "SE"), ("death", "SE")]
    rows = [PR.view(hero, [f"{action}_{direction}_{frame:02d}"
                          for frame in range(hero["meta"]["anims"][action]["frames"])])
            for action, direction in actions]
    CS.sheet(rows).save(OUT / "key-actions.png")
    compass = ["NW", "N", "NE", "W", None, "E", "SW", "S", "SE"]
    for action in moments:
        frames = CS.grid_frames(hero, action, compass, cols=3)
        frames = [frame.resize((round(frame.width / S.DENSITY), round(frame.height / S.DENSITY)),
                               Image.Resampling.LANCZOS) for frame in frames]
        CS.gif(frames, OUT / f"{action}-eight-directions.gif", hero["meta"]["anims"][action]["fps"], zoom_k=1)
    print(f"主角动作审图完成：{OUT}")


def main():
    hero_contact_sheets()
    portrait_comparison()
    print(f"主角与头像审图完成：{OUT}")


if __name__ == "__main__":
    main()
