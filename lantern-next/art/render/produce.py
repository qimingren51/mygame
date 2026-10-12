"""提灯夜行 · 正式出图（T6）：主角、影妖、疾影、三块山石、石灯笼。

运行（在仓库的 lantern-next/ 目录下）：
    art/.venv/bin/python art/render/produce.py                    # 全部（约 3 分钟）
    art/.venv/bin/python art/render/produce.py --only shade,wisp  # 只重渲部分素材（审图仍用全部）
    art/.venv/bin/python art/render/produce.py --review           # 不渲染，只自检 + 重拼审图
输出：
    art/out/assets/<素材>/    按 style.py 输出约定（PNG、_emit、_flash、meta.json、逐帧挂点）
    art/out/review/           审图：sheet_day / sheet_zoom / sheet_night / game_size / night_scene，
                              动图 hero_walk_8dir.gif、hero_idle_8dir.gif、shade_float.gif、wisp_float.gif，
                              check_report.json、timings.json
不打图集（图集由主代理打）。
"""

from __future__ import annotations

import json
import math
import sys
import time
from pathlib import Path

ART = Path(__file__).resolve().parents[1]
for p in (ART, ART / "models", ART / "post", ART / "render"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import numpy as np  # noqa: E402
from PIL import Image, ImageOps  # noqa: E402

from style import style as S  # noqa: E402
import check_asset as C  # noqa: E402
import contact_sheet as CS  # noqa: E402
from pipeline import render_asset  # noqa: E402

ASSETS = ART / "out" / "assets"
REVIEW = ART / "out" / "review"
ALL = ["hero", "shade", "wisp", "rock_a", "rock_b", "rock_c", "stone_lantern"]
HERO_IDLE, HERO_WALK = 6, 8
SHADE_FRAMES, WISP_FRAMES = 8, 6


def produce(name: str, timings: dict):
    import hero as HERO
    import shade as GHOST
    import rock as ROCK
    import stone_lantern as SL

    if name == "hero":
        jobs = [("idle", d, i, HERO_IDLE) for d in S.DIRS for i in range(HERO_IDLE)]
        jobs += [("walk", d, i, HERO_WALK) for d in S.DIRS for i in range(HERO_WALK)]
        hero_h = S.HERO_HEIGHT_M * S.PX_PER_M * math.cos(math.radians(S.CAMERA_PITCH_DEG))
        render_asset("hero", S.FRAME["hero"], HERO.build_hero, jobs, ASSETS, pose=HERO.pose_hero,
                     sockets_wanted=("lantern",), timings=timings,
                     meta_extra={"category": "hero", "height_px": round(hero_h, 2), "layers": ["emit"],
                                 "required_sockets": ["lantern"], "shadow_radius_px": 13,
                                 "anim_extra": {"idle": {"fps": 6},
                                                "walk": {"fps": 12, "stride_units": HERO.walk_stride_units()}}})
    elif name in ("shade", "wisp"):
        n = SHADE_FRAMES if name == "shade" else WISP_FRAMES
        build = GHOST.build_shade if name == "shade" else GHOST.build_wisp
        render_asset(name, S.FRAME["small"], build, [("float", "E", i, n) for i in range(n)], ASSETS,
                     pose=GHOST.pose_ghost, sockets_wanted=("eyes",), flash=True, timings=timings,
                     meta_extra={"category": "enemy", "floating": True, "layers": ["emit", "flash"],
                                 "required_sockets": ["eyes"], "shadow_radius_px": 15 if name == "shade" else 12,
                                 "anim_extra": {"float": {"fps": 8 if name == "shade" else 10}}})
    elif name.startswith("rock_"):
        v = name[-1]
        render_asset(name, S.FRAME["prop"], lambda: ROCK.build_rock(v), [("idle", "S", 0, 1)], ASSETS,
                     anchor=S.PROP_ANCHOR, timings=timings,
                     meta_extra={"category": "prop", "shadow_radius_px": 20, "anim_extra": {"idle": {"fps": 1}}})
    elif name == "stone_lantern":
        render_asset(name, S.FRAME["prop"], SL.build_stone_lantern, [("idle", "S", 0, 1)], ASSETS,
                     anchor=S.PROP_ANCHOR, sockets_wanted=("flame",), timings=timings,
                     meta_extra={"category": "prop", "layers": ["emit"], "required_sockets": ["flame"],
                                 "shadow_radius_px": 16, "anim_extra": {"idle": {"fps": 1}}})
    else:
        raise SystemExit(f"未知素材 {name}")


# ================================================================ 审图
def view(A: dict, keys: list[str]) -> dict:
    return dict(A, frames=[f for k in keys for f in A["frames"] if f["key"] == k])


def mirrored(f: dict) -> dict:
    return dict(f, rgba=ImageOps.mirror(f["rgba"]), emit=ImageOps.mirror(f["emit"]) if f["emit"] else None,
                sockets={k: (-v[0], v[1]) for k, v in f["sockets"].items()})


def scene(A: dict, scale: float = 1.0, size=(600, 360)):
    """宣纸地面 + 水墨斑；主角居中提灯；右上有石灯笼自带一圈火光；光圈边缘一只影妖和一块石头；
    黑暗里还有一只影妖、一只疾影（只剩眼睛）和几块石头。返回 (白天图, 发光层, 光源列表)。"""
    w, h = round(size[0] * scale), round(size[1] * scale)
    day = CS.paper(w, h, seed=7, blotches=8)
    emit = np.zeros((h, w, 3), np.float32)
    hf = next(f for f in A["hero"]["frames"] if f["key"] == "idle_S_00")
    hero_at = (w * 0.47, h * 0.66)
    lx, ly = hf["sockets"]["lantern"]
    light = (hero_at[0] + lx * scale, hero_at[1] + ly * scale)
    R = CS.LIGHT_RADIUS_PX * scale
    slf = A["stone_lantern"]["frames"][0]
    sl_at = (w * 0.80, h * 0.40)
    fx, fy = slf["sockets"]["flame"]
    lights = [(light[0], light[1], R, S.LANTERN_LIGHT),
              (sl_at[0] + fx * scale, sl_at[1] + fy * scale, 70 * scale, S.FLAME_LIGHT)]

    def polar(ang, dist):
        a = math.radians(ang)
        return (light[0] + math.cos(a) * dist * R, light[1] + math.sin(a) * dist * R)

    sh = A["shade"]["frames"][0]
    wi = A["wisp"]["frames"][0]
    items = [
        (A["rock_c"], A["rock_c"]["frames"][0], (w * 0.10, h * 0.30)),
        (A["wisp"], wi, (w * 0.16, h * 0.55)),  # 黑暗里的疾影（朝东冲向主角）
        (A["shade"], mirrored(sh), (w * 0.86, h * 0.90)),  # 黑暗里的影妖（朝西）
        (A["rock_b"], A["rock_b"]["frames"][0], (w * 0.90, h * 0.47)),
        (A["stone_lantern"], slf, sl_at),
        (A["rock_a"], A["rock_a"]["frames"][0], polar(168, 0.95)),
        (A["shade"], mirrored(sh), polar(16, 0.90)),  # 光圈边缘的影妖，朝西面向主角
        (A["hero"], hf, hero_at),
    ]
    for AA, f, pos in sorted(items, key=lambda it: it[2][1]):
        CS.place(day, f, AA["meta"], pos, scale=scale)
        CS.place_emit(emit, f, AA["meta"], pos, scale=scale)
    return day, emit, lights


def build_review(timings: dict):
    REVIEW.mkdir(parents=True, exist_ok=True)
    A = {n: CS.load_asset(ASSETS / n) for n in ALL}
    t = time.perf_counter()
    rows = [view(A["hero"], [f"idle_{d}_00" for d in S.DIRS]),
            view(A["hero"], [f"walk_{d}_02" for d in S.DIRS]),
            A["shade"], A["wisp"],
            {"meta": A["rock_a"]["meta"], "frames": [A[n]["frames"][0] for n in ("rock_a", "rock_b", "rock_c", "stone_lantern")]}]
    day = CS.sheet(rows)
    day.save(REVIEW / "sheet_day.png")
    CS.zoom(day).save(REVIEW / "sheet_zoom.png")
    CS.sheet(rows, night=True).save(REVIEW / "sheet_night.png")
    d1, e1, l1 = scene(A, 1.0)
    night = CS.night_composite(d1, e1, l1)
    night.save(REVIEW / "night_scene.png")
    d2, e2, l2 = scene(A, 0.75)
    gs = Image.new("RGB", (d1.width + d2.width + 10, d1.height * 2 + 10), CS.rgb(S.PAPER))
    gs.paste(d1.convert("RGB"), (0, 0))
    gs.paste(night, (0, d1.height + 10))
    gs.paste(d2.convert("RGB"), (d1.width + 10, 0))
    gs.paste(CS.night_composite(d2, e2, l2), (d1.width + 10, d1.height + 10))
    gs.save(REVIEW / "game_size.png")
    compass = ["NW", "N", "NE", "W", None, "E", "SW", "S", "SE"]  # 按屏幕方位排的 3×3
    CS.gif(CS.grid_frames(A["hero"], "walk", compass, cols=3), REVIEW / "hero_walk_8dir.gif", 12)
    CS.gif(CS.grid_frames(A["hero"], "idle", compass, cols=3), REVIEW / "hero_idle_8dir.gif", 6)
    for n, fps in (("shade", 8), ("wisp", 10)):
        CS.gif([f["rgba"] for f in A[n]["frames"]], REVIEW / f"{n}_float.gif", fps, zoom_k=3)
    timings["review_s"] = round(time.perf_counter() - t, 2)


def main(argv):
    T0 = time.perf_counter()
    timings: dict = {}
    only = None
    for a in argv:
        if a.startswith("--only"):
            only = (a.split("=", 1)[1] if "=" in a else argv[argv.index(a) + 1]).split(",")
    if "--review" not in argv:
        for n in (only or ALL):
            produce(n, timings)
    timings["render_total_s"] = round(time.perf_counter() - T0, 2)
    t = time.perf_counter()
    results = [C.check_asset(ASSETS / n) for n in ALL if (ASSETS / n / "meta.json").exists()]
    print("\n==== check_asset ====")
    for r in results:
        print(C.report(r))
    timings["check_s"] = round(time.perf_counter() - t, 2)
    REVIEW.mkdir(parents=True, exist_ok=True)
    (REVIEW / "check_report.json").write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    if all((ASSETS / n / "meta.json").exists() for n in ALL):
        build_review(timings)
    timings["total_s"] = round(time.perf_counter() - T0, 2)
    old = {}
    tp = REVIEW / "timings.json"
    if tp.exists():
        old = json.loads(tp.read_text(encoding="utf-8"))
    old.update(timings)
    tp.write_text(json.dumps(old, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(timings, ensure_ascii=False, indent=1))
    return 0 if all(r["ok"] for r in results) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
