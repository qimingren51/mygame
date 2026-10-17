"""妖物重做样张的公共部分：按输出约定写帧（本体、_flash、_emit、meta.json、逐帧挂点），以及审图。

A 法（render/enemy_sample_a.py，Blender）和 B 法（post/enemy_2d.py，2D）都用这里的 finish() / write_asset()，
所以两种画法的帧尺寸、锚点、后期（纸纹、透明区扩色）完全一样，只差画法本身。
帧写到 art/out/enemy_sample@2x/<妖物>_<A|B>/，格式同 art/out/assets@2x/<妖物>/（以后可以直接打图集）。

    art/.venv/bin/python art/post/enemy_sample.py review    # 只拼审图（读已经出好的帧）
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

os.environ.setdefault("LANTERN_ART_DENSITY", "2")

HERE = Path(__file__).resolve().parent
ART = HERE.parent
for p in (ART, HERE):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

from style import style as S  # noqa: E402
import postprocess as PP  # noqa: E402

OUT = ART / "out" / "enemy_sample@2x"
REVIEW = ART / "out" / "review@2x"
D = S.DENSITY
PPU = S.PX_PER_UNIT  # 4 像素 / 单位

# 两只妖物的帧格式（世界观会话 2026-10-16 的外形描述）
SPEC = {
    # 影妖：人那么高（主角 0.85 倍），帧从 160² 放大到 224²；锚点是下摆墨烟的落地点；碰撞半径 13 不变
    "shade": {"size": 224, "anchor": (0.5, 0.875), "eye": "#FFC46B", "radius": 13,
              "anims": {"float": (8, 8, {})},
              "meta": {"category": "enemy", "floating": True, "default_anim": "float"}},
    # 赤面狐：帧 320²、锚点 (0.5, 0.8)；走路前沿约 22 单位、扑击 24–28
    "fox": {"size": 320, "anchor": (0.5, 0.8), "eye": "#FF6B5A", "radius": 24,
            "anims": {"move": (8, 12, {}), "pounce": (6, 12, {"loop": False, "windup_frames": 2, "vertical_motion": True})},
            "meta": {"category": "elite", "anchor_kind": "big_enemy", "default_anim": "move"}},
}


def finish(rgb, a, erg, ea, grain_name):
    """缩小后的直通 rgb/alpha（0..1）→ 最终 RGBA8：纸纹（同正式管线）、清掉极小 alpha、往透明区扩色；
    发光层同样处理；闪白是纯白 + 本体 alpha。返回 (rgba, emit, flash) 三个 uint8 数组。"""
    h, w = a.shape
    rgb255 = np.clip(rgb * 255.0 * PP.paper_grain(h, w, grain_name)[..., None], 0, 255)
    a = np.where(a < PP.ALPHA_FLOOR, 0.0, a)
    rgba = PP.to_rgba8(PP.alpha_bleed(rgb255, a), a)
    ea = np.where(ea < PP.ALPHA_FLOOR, 0.0, ea)
    emit = PP.to_rgba8(PP.alpha_bleed(np.where(ea[..., None] > 0, erg * 255.0, 0.0), ea), ea)
    return rgba, emit, PP.make_flash(rgba)


def write_asset(name, frames, sockets, extra_meta=None):
    """frames: [(动画, 帧号, rgba, emit, flash)]；sockets: {挂点: {动画: [[x, y], ...]}}（相对锚点的最终像素）。"""
    kind = name.split("_")[0]
    sp = SPEC[kind]
    out = OUT / name
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("*.png"):
        old.unlink()
    for anim, i, rgba, emit, flash in frames:
        base = f"{anim}_E_{i:02d}"
        PP.save_png(rgba, out / f"{base}.png")
        PP.save_png(emit, out / f"{base}_emit.png")
        PP.save_png(flash, out / f"{base}_flash.png")
    anims = {}
    for an, (n, fps, extra) in sp["anims"].items():
        anims[an] = {"frames": n, "fps": fps, "dirs": ["E"], **extra}
    meta = {"name": kind, "size": [sp["size"]] * 2, "anchor": list(sp["anchor"]), "px_per_unit": PPU,
            "anims": anims, **sp["meta"], "layers": ["emit", "flash"], "required_sockets": ["eyes"],
            "eye_color": sp["eye"], "game_radius": sp["radius"],
            "sockets": {s: {an: {"E": [[round(float(x), 2), round(float(y), 2)] for x, y in pts]}
                            for an, pts in by.items()} for s, by in sockets.items()}}
    meta.update(extra_meta or {})
    (out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    return out


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "review":
        import enemy_review as R  # noqa: E402

        R.main()
