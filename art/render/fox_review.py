"""赤面狐完整正式动作的独立审图，不要求其他素材中间产物存在。

    LANTERN_ART_DENSITY=2 /path/to/art/.venv/bin/python art/render/fox_review.py

读取 out/assets@2x/fox，输出 out/review@2x/fox-r3/ 的逐帧日夜图、两种动作动图。
同帧同光场合成；动图保持素材12fps，扑击末帧仅为审图多停3帧。不修改正式图集。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ART = Path(__file__).resolve().parents[1]
for directory in (ART, ART / "post", ART / "render"):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))
from style import style as S
import contact_sheet as CS
from fox_sample import tile


def main():
    source = ART / "out" / S.ASSETS_DIR_NAME / "fox"
    out = ART / "out" / f"review@{S.DENSITY:g}x" / "fox-r3"
    out.mkdir(parents=True, exist_ok=True)
    asset = CS.load_asset(source)
    meta = asset["meta"]
    current = json.loads((ART.parent / "assets/atlas/actors.json").read_text(encoding="utf-8"))
    old = current["meta"]["lantern"]["assets"]["fox"]
    for key in ("size", "anchor", "px_per_unit", "anims", "layers", "required_sockets",
                "game_radius", "shadow_radius_px", "anchor_kind", "default_anim", "sockets"):
        assert meta.get(key) == old.get(key), f"正式接口发生变化：{key}"
    print("正式接口对照通过：画布、锚点、动作/帧率/蓄力、碰撞参考、emit/flash、逐帧眼睛挂点均保持。")
    font = ImageFont.truetype(str(ART.parent / "assets/fonts/NotoSerifSC-subset.ttf"), 14)
    rows = []
    for anim in meta["anims"]:
        frames = [f for f in asset["frames"] if f["anim"] == anim]
        day = [tile(frame, meta) for frame in frames]
        night = [tile(frame, meta, night=True) for frame in frames]
        for label, images in (("DAY", day), ("MOON", night)):
            row = Image.new("RGB", (8 * 160, 188), CS.rgb(S.PAPER))
            draw = ImageDraw.Draw(row)
            for index, image in enumerate(images):
                draw.text((index * 160 + 6, 4), f"{anim} / {index:02d} / {label}", font=font, fill=CS.rgb(S.INK["jiao"]))
                row.paste(image.resize((160, 160), Image.Resampling.LANCZOS), (index * 160, 28))
            rows.append(row)
        # 完整画布与脚底都保留在动图中，不能逐帧重裁造成假位移。
        pairs = []
        for index, (left, right) in enumerate(zip(day, night)):
            pair = Image.new("RGB", (640, 348), CS.rgb(S.PAPER))
            draw = ImageDraw.Draw(pair)
            draw.text((8, 4), f"{anim} / {index:02d} / 12 FPS / ASSET REVIEW", font=font, fill=CS.rgb(S.INK["jiao"]))
            pair.paste(left, (0, 28))
            pair.paste(right, (320, 28))
            pairs.append(pair)
        if meta["anims"][anim].get("loop") is False:
            pairs.extend([pairs[-1]] * 3)
        CS.gif(pairs, out / f"fox-{anim}.gif", meta["anims"][anim]["fps"], zoom_k=1)
        CS.sheet([dict(asset, frames=frames)]).save(out / f"fox-{anim}-native.png")
    board = Image.new("RGB", (1280, sum(row.height for row in rows)), CS.rgb(S.PAPER))
    y = 0
    for row in rows:
        board.paste(row, (0, y))
        y += row.height
    board.save(out / "fox-actions-day-moon.png")
    print(f"完整动作审图：{out}")


if __name__ == "__main__":
    if S.DENSITY != 2:
        raise SystemExit("请设置 LANTERN_ART_DENSITY=2，与正式桌面图集一致")
    main()
