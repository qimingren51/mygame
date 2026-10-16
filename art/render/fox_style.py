"""赤面狐正式出图与样张共用材质和线条，不影响同模块的九尾。

保留全局色板端点。与精修后的守灯人一样，让布料和毛色保有柔和的体积过渡，
同时削弱内部墨线；妖眼颜色、发光分层与素材锚点不变。
"""
from __future__ import annotations

import bpy


def apply_fox_style(parts: dict) -> None:
    for key in ("fur", "mask", "robe", "under", "robe_dark"):
        for node in parts["M"][key].node_tree.nodes:
            if node.type == "VALTORGB":
                node.color_ramp.interpolation = "EASE"
            elif node.type == "MATH" and node.operation == "MULTIPLY" and node.inputs[1].default_value < 0:
                node.inputs[1].default_value *= 0.58
    for name, factor in {"InkOuter": 0.80, "InkForm": 0.57, "InkInner": 0.62}.items():
        style = bpy.data.linestyles.get(name)
        if style is None:
            continue
        style.thickness *= factor
        for modifier in style.thickness_modifiers:
            if modifier.type == "CALLIGRAPHY":
                modifier.thickness_min *= factor
                modifier.thickness_max *= factor


def build_styled_fox():
    """每次由流水线重建独立场景；线宽只作用于本次赤面狐出图。"""
    import fox

    root, parts, sockets = fox.build_fox()
    apply_fox_style(parts)
    return root, parts, sockets
