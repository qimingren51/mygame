"""主角造型、布料与灯侧受光的两朝向对照，不写正式图集。

仓库根目录：
    LANTERN_ART_DENSITY=2 art/.venv/bin/python art/render/hero_material_sample.py
    ... --only candidate                 # 调整样张后只重渲候选

沿用 pipeline.render_asset 的相机、墨线和后期，旧模型默认取首轮基线 c473828。
主角专属明暗与墨线复用 hero_style，不改变其他素材的全局风格。
输出 art/out/r2-hero-material-v2/：旧/新 RGBA、720p/1080p 对照、挂点与单帧耗时。
受光页给两侧同样的月色与灯位置，只供模型审查，不把灯光烘焙进正式主角图集。
"""

from __future__ import annotations

import argparse
import contextlib
import json
import re
import subprocess
import sys
import types
from pathlib import Path

import bpy
from PIL import Image, ImageDraw, ImageFont

ART = Path(__file__).resolve().parents[1]
ROOT = ART.parent
for directory in (ART, ART / "models", ART / "render", ART / "post"):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

import hero as HERO
from pipeline import render_asset
from hero_style import apply_hero_style
from style import bstyle as B
from style import style as S

OUT = ART / "out" / "r2-hero-material-v2"
JOBS = [("idle", "SE", 0, 6), ("idle", "E", 0, 6)]


def reference_model(ref: str):
    source = subprocess.run(["git", "show", f"{ref}:art/models/hero.py"], cwd=ROOT,
                            check=True, text=True, capture_output=True).stdout
    module = types.ModuleType("hero_reference")
    # 旧模块仍从当前仓库导入公共管线，避免拿旧渲染设置制造不可比的结果。
    module.__file__ = str(ART / "models" / "hero.py")
    exec(compile(source, module.__file__, "exec"), module.__dict__)
    return module


@contextlib.contextmanager
def lamp_study(parts):
    """同一灯位、同一环境的局部受光比较；退出后恢复中性底图材质。"""
    lamp = parts["sockets"]["lantern"].matrix_world.translation
    restore = []
    for material in parts["mats"].values():
        tree = material.node_tree
        emission = next((node for node in tree.nodes if node.type == "EMISSION"), None)
        if emission is None or not emission.inputs["Color"].links:
            continue
        original = emission.inputs["Color"].links[0].from_socket
        added = []

        def node(kind):
            value = tree.nodes.new(kind)
            added.append(value)
            return value

        geometry = node("ShaderNodeNewGeometry")
        direction = node("ShaderNodeVectorMath"); direction.operation = "SUBTRACT"
        direction.inputs[0].default_value = lamp
        tree.links.new(geometry.outputs["Position"], direction.inputs[1])
        unit = node("ShaderNodeVectorMath"); unit.operation = "NORMALIZE"
        tree.links.new(direction.outputs["Vector"], unit.inputs[0])
        dot = node("ShaderNodeVectorMath"); dot.operation = "DOT_PRODUCT"
        tree.links.new(geometry.outputs["Normal"], dot.inputs[0])
        tree.links.new(unit.outputs["Vector"], dot.inputs[1])
        gain = node("ShaderNodeMath"); gain.operation = "MAXIMUM"
        gain.inputs[1].default_value = 0.0
        tree.links.new(dot.outputs["Value"], gain.inputs[0])
        color = node("ShaderNodeVectorMath"); color.operation = "SCALE"
        color.inputs[0].default_value = S.hex_to_linear(S.LANTERN_LIGHT)
        tree.links.new(gain.outputs[0], B.sock(color.inputs, "Scale"))
        ambient = node("ShaderNodeVectorMath"); ambient.operation = "ADD"
        ambient.inputs[1].default_value = (0.32, 0.38, 0.52)
        tree.links.new(color.outputs["Vector"], ambient.inputs[0])
        mix = node("ShaderNodeVectorMath"); mix.operation = "MULTIPLY"
        tree.links.new(original, mix.inputs[0])
        tree.links.new(ambient.outputs["Vector"], mix.inputs[1])
        tree.links.new(mix.outputs["Vector"], emission.inputs["Color"])
        restore.append((tree, emission, original, added))
    try:
        yield
    finally:
        for tree, emission, original, nodes in restore:
            tree.links.new(original, emission.inputs["Color"])
            for node in nodes:
                tree.nodes.remove(node)


def render(label, module, timings, lit=False):
    def build():
        root, parts, sockets = module.build_hero()
        if label.startswith("candidate"):
            apply_hero_style(parts)
        return root, parts, sockets

    render_asset(label, S.FRAME["hero"], build, JOBS, OUT, pose=module.pose_hero,
                 sockets_wanted=("lantern", "feet"), tmp_dir=OUT / f"tmp-{label}",
                 grain="hero", timings=timings, scope=lamp_study if lit else None)


def compose(lit=False):
    suffix = "_lit" if lit else ""
    keys = [(label, direction) for direction in ("SE", "E") for label in ("baseline", "candidate")]
    images = [Image.open(OUT / f"{label}{suffix}" / f"idle_{direction}_00.png").convert("RGBA")
              for label, direction in keys]
    bounds = [image.getchannel("A").getbbox() for image in images]
    box = (min(b[0] for b in bounds) - 8, min(b[1] for b in bounds) - 8,
           max(b[2] for b in bounds) + 8, max(b[3] for b in bounds) + 8)
    background = "#434A58" if lit else S.PAPER
    ink = S.PAPER if lit else S.INK["jiao"]
    secondary = S.INK["qing"] if lit else S.INK["zhong"]
    board = Image.new("RGB", (1180, 1060), background)
    draw = ImageDraw.Draw(board)
    font_path = ROOT / "assets" / "fonts" / "NotoSerifSC-subset.ttf"
    title = ImageFont.truetype(str(font_path), 26)
    small = ImageFont.truetype(str(font_path), 17)
    draw.text((30, 16), "HERO / FORM & MATERIAL STUDY II", font=title, fill=ink)
    note = "Same moon ambient and lamp position." if lit else "Neutral atlas colors."
    draw.text((30, 56), f"{note} Model sample, not a gameplay capture.", font=small, fill=secondary)
    # 720p 实机固定纵向视野，图集像素除以密度后再按世界单位投影；不把 2x 原图冒充游戏尺寸。
    content = (ROOT / "assets" / "data" / "run.ron").read_text(encoding="utf-8")
    view_height = float(re.search(r"view_height:\s*([\d.]+)", content).group(1))
    for index, ((label, direction), image) in enumerate(zip(keys, images)):
        left = index * 295
        draw.text((left + 16, 100), f"{label.upper()} / {direction}", font=small, fill=ink)
        crop = image.crop(box)
        factor = min(365 / crop.height, 260 / crop.width)
        closeup = crop.resize((round(crop.width * factor), round(crop.height * factor)), Image.Resampling.LANCZOS)
        board.paste(closeup, (left + (295 - closeup.width) // 2, 138), closeup)
        for height, top in ((720, 570), (1080, 790)):
            draw.text((left + 20, top - 38), f"{height}p / actual size", font=small, fill=secondary)
            game_scale = height / view_height / S.PX_PER_UNIT
            sprite = image.resize((round(image.width * game_scale), round(image.height * game_scale)),
                                  Image.Resampling.LANCZOS)
            board.paste(sprite, (left + (295 - sprite.width) // 2, top), sprite)
    for x in (295, 590, 885):
        draw.line((x, 95, x, 1030), fill=S.INK["dan"], width=1)
    path = OUT / ("lamp-comparison.png" if lit else "comparison.png")
    board.save(path)
    return str(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-ref", default="c473828")
    parser.add_argument("--only", choices=("baseline", "candidate"))
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    report_path = OUT / "timings.json"
    report = json.loads(report_path.read_text()) if report_path.exists() else {}
    report["baseline_ref"] = args.baseline_ref
    if args.only != "candidate":
        model = reference_model(args.baseline_ref)
        render("baseline", model, report)
        render("baseline_lit", model, report, lit=True)
    if args.only != "baseline":
        render("candidate", HERO, report)
        render("candidate_lit", HERO, report, lit=True)
    if all((OUT / label / "meta.json").exists() for label in ("baseline", "candidate")):
        metas = [json.loads((OUT / label / "meta.json").read_text()) for label in ("baseline", "candidate")]
        report["same_pose_sockets"] = metas[0]["sockets"] == metas[1]["sockets"]
        report["comparison"] = compose()
        report["lamp_comparison"] = compose(lit=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
