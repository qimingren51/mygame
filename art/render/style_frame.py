"""提灯夜行 · 风格样张：用正式管线渲几样素材，检查并拼出审图用的大图。

运行（在仓库根目录下）：
    art/.venv/bin/python art/render/style_frame.py            # 完整：主角 idle 5 向 + walk 8 帧×5 向
    art/.venv/bin/python art/render/style_frame.py --quick    # 快速：walk 只渲第 2 帧
输出到 art/out/style/：
    assets/<素材>/...         每个素材一个文件夹，符合 style.py 末尾的输出约定（含 meta.json、挂点、_emit/_flash）
    sheet_day.png            1 倍：主角 idle 5 个朝向 + walk 第 2 帧 5 个朝向；影妖、两块石头
    sheet_zoom.png           上图 3 倍最近邻放大
    sheet_walk.png           walk 一整圈（S、E 两个朝向），3 倍
    night.png                夜景小场景：主角提灯居中，光圈边缘一只影妖和一块石头，远处黑暗里一只只剩眼睛的影妖
    game_size.png            游戏里的实际大小：同一场景 1 倍和 0.75 倍，白天/夜里
    timings.json             各阶段耗时
"""

from __future__ import annotations

import json
import math
import sys
import time
from pathlib import Path

ART = Path(__file__).resolve().parents[1]
for p in (ART, ART / "models", ART / "post"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import bpy  # noqa: E402,F401
import numpy as np  # noqa: E402
from PIL import Image, ImageOps  # noqa: E402

from style import bstyle as B  # noqa: E402
from style import style as S  # noqa: E402
import postprocess as P  # noqa: E402
import check_asset as C  # noqa: E402
import contact_sheet as CS  # noqa: E402
import hero as HERO  # noqa: E402
sys.path.insert(0, str(ART / "render"))
from pipeline import render_asset as _render_asset  # noqa: E402
import shade as SHADE  # noqa: E402
import rock as ROCK  # noqa: E402

OUT = ART / "out" / "style"
ASSETS = OUT / "assets"
QUICK = "--quick" in sys.argv
HERO_DIRS = ["S", "SE", "E", "NE", "N"]
WALK_FRAMES = 8
TIMES: dict = {"frames": {}}


def _rel(p: Path) -> str:
    return str(p.relative_to(ART.parent)) if p.is_relative_to(ART.parent) else str(p)


def render_asset(name, frame_px, build, jobs, meta_extra, pose=None, sockets_wanted=(), flash=False, anchor=None):
    """转给 pipeline.render_asset（与正式出图同一套），输出到 out/style/assets。"""
    return _render_asset(name, frame_px, build, jobs, ASSETS, meta_extra=meta_extra, pose=pose,
                         sockets_wanted=sockets_wanted, flash=flash, anchor=anchor, tmp_dir=OUT / "_tmp",
                         timings=TIMES["frames"])


def time_shade_512():
    """影妖按 512² 单独计一次时（正式帧是 80px → 320²）。"""
    B.reset_scene()
    B.setup_render(128)
    B.setup_camera(128)
    B.setup_freestyle()
    root, parts, _ = SHADE.build_shade()
    B.set_direction(root, "E")
    with B.render_lock():
        B.render_layers(OUT / "_tmp" / "shade_t512")  # 预热
        L = B.render_layers(OUT / "_tmp" / "shade_t512")
    TIMES["shade_512_render_s"] = round(L["time_s"], 3)


# ================================================================ 场景（夜景 / 游戏大小）
def build_scene(assets: dict, scale: float = 1.0, size=(480, 300)):
    """宣纸地面 + 水墨斑；主角居中提灯，光圈边缘一只影妖和一块石头，远处黑暗里另一只影妖（镜像=朝西）。"""
    w, h = round(size[0] * scale), round(size[1] * scale)
    day = CS.paper(w, h, seed=7, blotches=6)
    emit = np.zeros((h, w, 3), np.float32)
    H, SH, R1, R2 = assets["hero"], assets["shade"], assets["rock_a"], assets["rock_b"]
    hf = next(f for f in H["frames"] if f["key"] == "idle_S_00")
    hero_at = (w * 0.5, h * 0.66)
    lx, ly = hf["sockets"]["lantern"]
    light = (hero_at[0] + lx * scale, hero_at[1] + ly * scale)
    R = CS.LIGHT_RADIUS_PX * scale

    def at_polar(ang_deg, dist):
        a = math.radians(ang_deg)
        return (light[0] + math.cos(a) * dist * R, light[1] + math.sin(a) * dist * R)

    sh = SH["frames"][0]
    sh_w = dict(sh, rgba=ImageOps.mirror(sh["rgba"]), emit=ImageOps.mirror(sh["emit"]) if sh["emit"] else None)
    items = [
        (R2, R2["frames"][0], (w * 0.12, h * 0.22)),  # 远处黑暗里的石头
        (SH, sh_w, (w * 0.86, h * 0.36)),  # 黑暗里的影妖（镜像=朝西）：只剩眼睛
        (R1, R1["frames"][0], at_polar(165, 0.92)),  # 光圈左缘的石头
        (SH, sh_w, at_polar(18, 0.88)),  # 光圈右缘的影妖，朝西面向主角
        (H, hf, hero_at),
    ]
    for A, f, pos in sorted(items, key=lambda it: it[2][1]):  # 按脚底 y 排序
        CS.place(day, f, A["meta"], pos, scale=scale)
        CS.place_emit(emit, f, A["meta"], pos, scale=scale)
    return day, emit, [(light[0], light[1], R, S.LANTERN_LIGHT)]


def view(A: dict, keys: list[str]) -> dict:
    return dict(A, frames=[f for k in keys for f in A["frames"] if f["key"] == k])


def main():
    T0 = time.perf_counter()
    OUT.mkdir(parents=True, exist_ok=True)
    walk_idx = [2] if QUICK else list(range(WALK_FRAMES))
    hero_jobs = [("idle", d, 0, 6) for d in HERO_DIRS] + [("walk", d, i, WALK_FRAMES) for d in HERO_DIRS for i in walk_idx]
    hero_h = S.HERO_HEIGHT_M * S.PX_PER_M * math.cos(math.radians(S.CAMERA_PITCH_DEG))
    render_asset("hero", S.FRAME["hero"], HERO.build_hero, hero_jobs, pose=HERO.pose_hero,
                 sockets_wanted=("lantern",),
                 meta_extra={"category": "hero", "height_px": round(hero_h, 2), "layers": ["emit"],
                             "required_sockets": ["lantern"], "shadow_radius_px": 13,
                             "anim_extra": {"idle": {"fps": 8}, "walk": {"fps": 12, "stride_units": HERO.walk_stride_units()}},
                             "note": "风格样张：idle 只渲第 0 帧"})
    render_asset("shade", S.FRAME["small"], SHADE.build_shade, [("idle", "E", 0, 6)], pose=SHADE.pose_shade,
                 sockets_wanted=("eyes",), flash=True,
                 meta_extra={"category": "enemy", "floating": True, "layers": ["emit", "flash"],
                             "required_sockets": ["eyes"], "shadow_radius_px": 16,
                             "anim_extra": {"idle": {"fps": 8}}, "note": "风格样张：只渲第 0 帧"})
    for nm, v in (("rock_a", "a"), ("rock_b", "b")):
        render_asset(nm, S.FRAME["prop"], lambda v=v: ROCK.build_rock(v), [("idle", "S", 0, 1)], anchor=S.PROP_ANCHOR,
                     meta_extra={"category": "prop", "shadow_radius_px": 20, "anim_extra": {"idle": {"fps": 1}}})
    time_shade_512()
    TIMES["render_total_s"] = round(time.perf_counter() - T0, 2)
    for p in (OUT / "_tmp").glob("*"):
        p.unlink()

    # ---- 自检
    t = time.perf_counter()
    results = [C.check_asset(ASSETS / n) for n in ("hero", "shade", "rock_a", "rock_b")]
    print("\n==== check_asset ====")
    for r in results:
        print(C.report(r))
    TIMES["check_s"] = round(time.perf_counter() - t, 2)
    (OUT / "check_report.json").write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")

    # ---- 拼图
    t = time.perf_counter()
    A = {n: CS.load_asset(ASSETS / n) for n in ("hero", "shade", "rock_a", "rock_b")}
    hero_keys = [f"idle_{d}_00" for d in HERO_DIRS] + [f"walk_{d}_{0 if QUICK else 2:02d}" for d in HERO_DIRS]
    day = CS.sheet([view(A["hero"], hero_keys), A["shade"], A["rock_a"], A["rock_b"]])
    day.save(OUT / "sheet_day.png")
    CS.zoom(day).save(OUT / "sheet_zoom.png")
    if not QUICK:
        walk = CS.sheet([view(A["hero"], [f"walk_S_{i:02d}" for i in range(WALK_FRAMES)]),
                         view(A["hero"], [f"walk_E_{i:02d}" for i in range(WALK_FRAMES)])])
        CS.zoom(walk, 2).save(OUT / "sheet_walk.png")
    d1, e1, l1 = build_scene(A, 1.0)
    night = CS.night_composite(d1, e1, l1)
    night.save(OUT / "night.png")
    CS.zoom(night, 2).save(OUT / "night_zoom.png")
    d2, e2, l2 = build_scene(A, 0.75)
    gs = Image.new("RGB", (d1.width + d2.width + 10, d1.height * 2 + 10), CS.rgb(S.PAPER))
    gs.paste(d1.convert("RGB"), (0, 0))
    gs.paste(night, (0, d1.height + 10))
    gs.paste(d2.convert("RGB"), (d1.width + 10, 0))
    gs.paste(CS.night_composite(d2, e2, l2), (d1.width + 10, d1.height + 10))
    gs.save(OUT / "game_size.png")
    TIMES["sheets_s"] = round(time.perf_counter() - t, 2)
    TIMES["total_s"] = round(time.perf_counter() - T0, 2)
    (OUT / "timings.json").write_text(json.dumps(TIMES, ensure_ascii=False, indent=1), encoding="utf-8")
    print("\n==== 耗时 ====")
    print(json.dumps(TIMES, ensure_ascii=False, indent=1))
    print("审图：", ", ".join(_rel(OUT / n) for n in ("sheet_day.png", "sheet_zoom.png", "night.png", "game_size.png")))
    return 0 if all(r["ok"] for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
