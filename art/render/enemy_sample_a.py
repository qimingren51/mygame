#!/usr/bin/env python3
"""妖物重做 · A 法（精修三维）出帧：影妖 shade（models/shade_v2.py）、赤面狐 fox（models/fox_v2.py）。

Cycles CPU，渲染分辨率 = 帧 × RENDER_SCALE（4），一次渲染读出填色、墨线、发光部件（物体编号）、缝光（AOV）；
后期不吸附调色板（多档渐变），见 models/v2kit.post。最终渲染包在 bstyle.render_lock() 里（别的代理也在用 Blender）。

    art/.venv/bin/python art/render/enemy_sample_a.py                 # 两只都出
    art/.venv/bin/python art/render/enemy_sample_a.py shade           # 只出影妖
    art/.venv/bin/python art/render/enemy_sample_a.py --preview shade:float:0 out.png   # 单帧预览（3 倍放大，纸色底）
输出：art/out/enemy_sample@2x/<shade|fox>_A/（同正式素材格式）。
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

os.environ.setdefault("LANTERN_ART_DENSITY", "2")

ART = Path(__file__).resolve().parents[1]
for p in (ART, ART / "models", ART / "post", ART / "render"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from style import bstyle as B  # noqa: E402
from style import style as S  # noqa: E402
import v2kit as V2  # noqa: E402
import enemy_sample as ES  # noqa: E402

TMP = ART / "out" / "_tmp_enemy_a"


def _setup(kind):
    sp = ES.SPEC[kind]
    F = sp["size"]
    B.reset_scene()
    B.setup_render(F)
    B.setup_camera(F, anchor=sp["anchor"])
    B.verify_camera(F, verbose=False)
    return F


def _model(kind):
    if kind == "shade":
        import shade_v2 as M
        V2.setup_lines(outer_px=1.6, form_px=1.0, inner_px=0.8)
        root, parts, socks = M.build_shade()
        return M, root, parts, socks, M.pose_shade, M.CRACK
    import fox_v2 as M
    V2.setup_lines(outer_px=2.0, form_px=1.15, inner_px=0.8)
    root, parts, socks = M.build_fox()
    return M, root, parts, socks, M.pose_fox, M.MASK_GLOW


def render_kind(kind, only=None):
    t0 = time.perf_counter()
    F = _setup(kind)
    M, root, parts, socks, pose, glow_hex = _model(kind)
    sp = ES.SPEC[kind]
    frames, eyes = [], {}
    times = []
    with B.render_lock():
        for anim, (n, fps, _) in sp["anims"].items():
            for i in range(n):
                if only and (anim, i) not in only:
                    continue
                B.set_direction(root, "E")
                pose(parts, anim, i, n)
                tr = time.perf_counter()
                L = V2.render(TMP / f"{kind}_A_{anim}_{i:02d}")
                times.append(time.perf_counter() - tr)
                rgba, emit, flash = V2.post(L, f"{kind}_A", glow_hex, seed=i + 7)
                frames.append((anim, i, rgba, emit, flash))
                x, y = B.project_point(socks["eyes"].matrix_world.translation, F)
                eyes.setdefault(anim, []).append((x, y))
    info = f"{len(frames)} 帧，渲染 {sum(times) / max(len(times), 1):.1f}s/帧，{B.face_count(root)} 面，共 {time.perf_counter() - t0:.0f}s"
    return frames, {"eyes": eyes}, info


def main(argv):
    if argv and argv[0] == "--preview":
        kind, anim, idx = argv[1].split(":")
        frames, socks, info = render_kind(kind, only={(anim, int(idx))})
        import numpy as np
        from PIL import Image
        im = Image.fromarray(frames[0][2], "RGBA")
        big = im.resize((im.width * 3, im.height * 3), Image.NEAREST)
        bg = Image.new("RGBA", big.size, S.hex_to_rgb(S.PAPER) + (255,))
        bg.alpha_composite(big)
        bg.convert("RGB").save(argv[2])
        e = Image.fromarray(frames[0][3], "RGBA")
        eb = Image.new("RGBA", e.size, (30, 34, 50, 255))
        eb.alpha_composite(e)
        eb.convert("RGB").resize((e.width * 2, e.height * 2), Image.NEAREST).save(argv[2].replace(".png", "_emit.png"))
        print(info)
        return 0
    kinds = argv or ["shade", "fox"]
    for kind in kinds:
        frames, socks, info = render_kind(kind)
        extra = {"shadow_radius_px": 32 if kind == "shade" else 77, "method": "A"}
        out = ES.write_asset(f"{kind}_A", frames, socks, extra)
        print(f"[{kind}_A] {info} → {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
