"""提灯夜行 · 标题画里的主角背影和石灯笼（Blender 渲染，供 post/title_screen.py 合成）。

主角用正式模型（models/hero.py）、同一套墨色材质、墨线和后期，按标题画的比例单独渲一张大图（不是把 320² 的精灵放大）：
朝北（背对观众）、idle 第 0 帧，右手把灯笼向外侧举出；风比 idle 大一些，发带、马尾吹向画面左边。
石灯笼（models/stone_lantern.py）按同样的比例渲一张，合成时近大远小缩放。
相机俯角比游戏的 30° 低（这是平视远山的一幅画），每米像素数固定（PX_PER_M），所以人和灯笼的比例是真实的。

固定 2 倍出图参数（线宽、墨晕、纸纹按桌面版），与环境变量无关：
    art/.venv/bin/python art/render/title_hero.py
输出到 art/out/screens/parts/：hero_back.png、hero_back_emit.png、stone_lantern.png、stone_lantern_emit.png、parts.json
（脚底锚点、灯笼芯 / 灯窗位置、每米像素数、渲染耗时）。title_screen.py 缺这些文件时会自动调用本脚本。
"""

from __future__ import annotations

import os

os.environ["LANTERN_ART_DENSITY"] = "2"  # 标题画只有桌面版：先定密度，再导入 style

import json  # noqa: E402
import math  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402
from pathlib import Path  # noqa: E402

ART = Path(__file__).resolve().parents[1]
for p in (ART, ART / "models", ART / "post", ART / "render"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from PIL import Image  # noqa: E402

from style import style as S  # noqa: E402

OUT = ART / "out" / "screens" / "parts"
TMP = ART / "out" / "_tmp_title"
PX_PER_M = 140.0  # 标题画里主角约 2.2 米 ≈ 300 像素（1080 高的 28%）
PITCH_DEG = 12.0
HERO_FRAME_M = (3.6, 3.0)  # 取景宽、高（米）
HERO_YAW_DEG = 180.0 + 12.0  # 背对观众，略转向右边（看向月亮那边）
WIND = 0.55  # 发带、马尾、衣摆的风（idle 是 0.28）
WIND_TURN_DEG = -70.0  # 发带和马尾的飘向绕竖轴转多少（模型里风总是往身后吹；背影时“身后”正对观众）
LANTERN_FRAME_M = (1.2, 1.9)


def _render(name: str, w_m: float, h_m: float, target, build_fn):
    """通用：建场景 → 相机 → 墨线 → build_fn() 建模摆姿态 → 渲染 + 正式后期。返回 (rgba, emit, 投影函数结果)。"""
    import portrait as PT
    from style import bstyle as B

    w_px, h_px = int(round(w_m * PX_PER_M)), int(round(h_m * PX_PER_M))
    B.reset_scene()
    B.setup_render(max(w_px, h_px))
    PT.ortho_camera(target, PITCH_DEG, w_m, w_px * S.RENDER_SCALE, h_px * S.RENDER_SCALE)
    B.setup_freestyle()
    info = build_fn()
    pts = {k: PT.project_px(v, w_px, h_px) for k, v in info.items()}
    R = PT.render_processed(name, TMP, S.RENDER_SCALE)
    for p in TMP.glob("*.exr"):
        p.unlink()
    return R, pts, (w_px, h_px)


def build_hero_back() -> dict:
    """主角背影：idle 第 0 帧、朝北（灯杖按 hero.BACK_STAFF 外摆，灯笼落在右肩外侧），风加大并转向画面左边。"""
    import bpy
    from mathutils import Matrix, Vector
    import hero as HERO

    root, parts, sockets = HERO.build_hero()
    parts["dir"] = "N"
    root.rotation_mode = "XYZ"
    root.rotation_euler.z = math.radians(HERO_YAW_DEG)
    HERO.pose_hero(parts, "idle", 0, 6)
    # 举灯：右臂再往外抬一点，灯笼离身体远些
    arm = parts["arm_R"]
    arm.rotation_euler = (arm.rotation_euler.x + math.radians(-8), arm.rotation_euler.y + math.radians(-10),
                          arm.rotation_euler.z + math.radians(6))
    # 风：发带、马尾、鬓发按更大的风重建，再整体绕竖轴转向画面左边
    ph = 0.9
    HERO._replace_mesh(parts["ponytail"], HERO._strip_build(HERO._ponytail_points(ph, WIND), 0.10, 0.05, taper=(1.0, 0.3)))
    rib_a, rib_b = parts["ribbon"]
    HERO._replace_mesh(rib_a, HERO._strip_build(HERO._ribbon_points(1.05, ph, WIND * 1.3, 1.0), 0.066, 0.008, twist=2.4,
                                                taper=(0.8, 1.0)))
    HERO._replace_mesh(rib_b, HERO._strip_build(HERO._ribbon_points(0.90, ph + 1.3, WIND * 1.3, -0.6), 0.060, 0.008,
                                                twist=-2.0, taper=(0.8, 1.0)))
    turn = Matrix.Rotation(math.radians(WIND_TURN_DEG), 4, "Z")
    for ob in (parts["ponytail"], rib_a, rib_b):
        ob.matrix_basis = Matrix.Translation(ob.location) @ turn
    for ob, a0, a1, ln, front in parts["coat_panels"]:
        HERO._replace_mesh(ob, HERO._grid_build(HERO._coat_panel_rows(a0, a1, ln, front, ph, WIND * 0.6)))
    bpy.context.view_layer.update()
    return {"feet": Vector((0, 0, 0)), "lantern": sockets["lantern"].matrix_world.translation.copy(),
            "head": parts["head"].matrix_world.translation.copy()}


def build_lantern_prop() -> dict:
    import bpy
    from mathutils import Vector
    import stone_lantern as SL

    root, parts, sockets = SL.build_stone_lantern()
    root.rotation_euler.z = math.radians(-18)
    bpy.context.view_layer.update()
    return {"feet": Vector((0, 0, 0)), "flame": sockets["flame"].matrix_world.translation.copy()}


def main() -> int:
    t0 = time.perf_counter()
    OUT.mkdir(parents=True, exist_ok=True)
    meta = {"px_per_m": PX_PER_M, "pitch_deg": PITCH_DEG, "density": S.DENSITY, "timings": {}}
    for name, frame, target, fn in (
        ("hero_back", HERO_FRAME_M, (0.0, 0.0, 1.15), build_hero_back),
        ("stone_lantern", LANTERN_FRAME_M, (0.0, 0.0, 0.72), build_lantern_prop),
    ):
        t = time.perf_counter()
        R, pts, size = _render(name, *frame, target, fn)
        Image.fromarray(R["rgba"]).save(OUT / f"{name}.png", optimize=True)
        Image.fromarray(R["emit"]).save(OUT / f"{name}_emit.png", optimize=True)
        meta[name] = {"size": list(size), **{k: [round(v[0], 2), round(v[1], 2)] for k, v in pts.items()}}
        meta["timings"][name] = {"render_s": round(R["time_s"], 2), "total_s": round(time.perf_counter() - t, 2),
                                 "render_px": [size[0] * S.RENDER_SCALE, size[1] * S.RENDER_SCALE]}
        print(f"[title_hero] {name} {size[0]}×{size[1]}（渲染 {size[0] * S.RENDER_SCALE}×{size[1] * S.RENDER_SCALE}）"
              f" {R['time_s']:.1f}s")
    (OUT / "parts.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    if TMP.exists() and not any(TMP.iterdir()):
        TMP.rmdir()
    print(f"[title_hero] 共 {time.perf_counter() - t0:.1f}s → {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
