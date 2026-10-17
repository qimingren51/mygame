"""抢先体验新法器里要立体渲的部件（模型在 models/ea_weapons.py）：孔明灯、镇妖塔。

渲法同道具（pipeline.render_asset：Cycles CPU、Freestyle 墨线、后期吸附调色板、纸纹、发光层），只渲 S 一个朝向，只出桌面版密度：
    art/.venv/bin/python art/render/weapons_ea_render.py                     # 全部 → out/assets@2x/ea_<名字>/
    art/.venv/bin/python art/render/weapons_ea_render.py --only sky_lantern  # 只渲一样
产物是角色格式（<动画>_S_<NN>.png + _emit.png + meta.json），不直接进图集：post/weapon_textures_ea.py 读这些图，
改成 weapons/<名字>_<帧号> 的帧名，加上 2D 的火和光，写进 out/assets@2x/weapons_ea/。
渲染时拿 bstyle 的渲染锁（render_asset 里），和别的出图脚本不会同时渲；EXR 中间文件放 out/_tmp_ea/。
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("LANTERN_ART_DENSITY", "2")  # 只有桌面版
ART = Path(__file__).resolve().parents[1]
for p in (ART, ART / "models", ART / "post", ART / "render"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import pipeline  # noqa: E402  先 import bpy，模型模块才 import 得到 bmesh
import ea_weapons as EW  # noqa: E402
from style import style as S  # noqa: E402

assert S.DENSITY == 2, "只出桌面版（LANTERN_ART_DENSITY=2）"
OUT = ART / "out" / S.ASSETS_DIR_NAME
TMP = ART / "out" / "_tmp_ea"


def render(name: str) -> Path:
    build, pose, frame_1x, anchor, pal, anims = EW.BUILDERS[name]
    jobs = [(anim, "S", i, n) for anim, n in anims.items() for i in range(n)]
    meta = {"category": "fx_source", "layers": ["emit"], "note": f"给 post/weapon_textures_ea.py 用的源图（{name}），不直接进图集",
            "anim_extra": {anim: {"fps": 12} for anim in anims}}
    return pipeline.render_asset(f"ea_{name}", int(round(frame_1x * S.DENSITY)), build, jobs, OUT, meta_extra=meta, pose=pose,
                                 anchor=anchor, tmp_dir=TMP, palette_extra=pal)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="", help="逗号分隔的名字（sky_lantern、tower、tower_gold）")
    args = ap.parse_args()
    names = [n for n in args.only.split(",") if n] or list(EW.BUILDERS)
    t0 = time.perf_counter()
    for n in names:
        out = render(n)
        print(f"{n} → {out}  {time.perf_counter() - t0:.1f}s")


if __name__ == "__main__":
    main()
