"""守灯人的专属材质与墨线，正式主角、头像和样张共用。

在 setup_freestyle()、build_hero() 之后调用一次。只修改传入主角材质与当前主角场景；
其他素材仍由 pipeline 在 reset_scene() 后使用全局风格。灯侧受光不烘焙进图集。
"""

from __future__ import annotations

import contextlib

import bpy


def apply_hero_style(parts: dict) -> None:
    """保留色板端点，软化衣料与肤色的明暗，保留金属分档和墨氅分层。"""
    for key in ("white", "skin", "lining", "sleeve", "collar", "hair"):
        material = parts["mats"][key]
        for node in material.node_tree.nodes:
            if node.type == "VALTORGB":
                node.color_ramp.interpolation = "EASE"
            elif node.type == "MATH" and node.operation == "MULTIPLY" and node.inputs[1].default_value < 0:
                node.inputs[1].default_value *= 0.55
    # 墨氅保留分层晕染，明暗切档改成短过渡，避免褶面像几块硬板拼起来。
    tree = parts["mats"]["coat"].node_tree
    for node in list(tree.nodes):
        if node.type != "MATH" or node.operation != "GREATER_THAN":
            continue
        threshold = node.inputs[1].default_value
        ramp = tree.nodes.new("ShaderNodeMapRange")
        ramp.clamp = True
        ramp.interpolation_type = "SMOOTHSTEP"
        ramp.inputs["From Min"].default_value = threshold - 0.16
        ramp.inputs["From Max"].default_value = threshold + 0.16
        tree.links.new(node.inputs[0].links[0].from_socket, ramp.inputs["Value"])
        for link in list(node.outputs[0].links):
            tree.links.new(ramp.outputs["Result"], link.to_socket)
    # 外轮廓维持力度，减少内部边界吞掉衣褶与脸部的面积。
    # 记录原线宽，分层出图时灯笼继续沿用自己的风格，不跟着主角一起变细。
    parts["original_ink"] = []
    for name, factor in {"InkOuter": 0.85, "InkForm": 0.62, "InkInner": 0.68}.items():
        style = bpy.data.linestyles.get(name)
        if style is None:
            continue
        modifiers = [(m, m.thickness_min, m.thickness_max)
                     for m in style.thickness_modifiers if m.type == "CALLIGRAPHY"]
        parts["original_ink"].append((style, style.thickness, modifiers))
        style.thickness *= factor
        for modifier in style.thickness_modifiers:
            if modifier.type == "CALLIGRAPHY":
                modifier.thickness_min *= factor
                modifier.thickness_max *= factor


@contextlib.contextmanager
def lamp_ink(parts: dict):
    """灯笼叠层临时用原线宽，退出后恢复主角线宽；不改模型、挂点和任何色板。"""
    restore = []
    for style, width, modifiers in parts["original_ink"]:
        current = [(m, m.thickness_min, m.thickness_max) for m, _, _ in modifiers]
        restore.append((style, style.thickness, current))
        style.thickness = width
        for modifier, lo, hi in modifiers:
            modifier.thickness_min, modifier.thickness_max = lo, hi
    try:
        yield
    finally:
        for style, width, modifiers in restore:
            style.thickness = width
            for modifier, lo, hi in modifiers:
                modifier.thickness_min, modifier.thickness_max = lo, hi
