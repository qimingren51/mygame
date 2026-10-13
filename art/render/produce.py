"""提灯夜行 · 正式出图（T6）：主角、影妖、疾影、三块山石、石灯笼。

运行（在仓库根目录下）：
    art/.venv/bin/python art/render/produce.py                    # 全部（约 3 分钟）
    art/.venv/bin/python art/render/produce.py --only shade,wisp  # 只重渲部分素材（审图仍用全部）
    art/.venv/bin/python art/render/produce.py --only hero:dash+death  # 主角只重渲某几个动画（其它帧和 meta 保留）
                                                                    # 灯笼叠层 lantern_<灯> 总是跟着主角一起渲
    art/.venv/bin/python art/render/produce.py --review           # 不渲染，只自检 + 重拼审图
输出：
    art/out/assets/<素材>/    按 style.py 输出约定（PNG、_emit、_flash、meta.json、逐帧挂点）
                              主角拆成两层：hero/（不带灯笼头的底图，lantern 挂点照旧）和每盏灯一份叠层
                              lantern_<灯>/（同画布、同锚点、同帧名，主角身体当遮挡物，带 _emit；meta category=overlay）
    art/out/review/           审图：hero_sheet_day / hero_sheet_zoom（主角专页）、sheet_day / sheet_zoom / sheet_night / game_size / night_scene，
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

D = S.DENSITY  # 出图密度（LANTERN_ART_DENSITY）；下面写死的像素尺寸都是 1 倍的值，乘 D
ASSETS = ART / "out" / S.ASSETS_DIR_NAME
REVIEW = ART / "out" / ("review" if D == 1 else f"review@{D:g}x")
ALL = ["hero", "shade", "wisp", "rock_a", "rock_b", "rock_c", "stone_lantern"]
# 第二批妖物：(模块, 构造/姿态函数名后缀, 帧尺寸键, 帧数, fps, 游戏碰撞半径, 额外 meta)
BATCH2 = {
    "golem": ("golem", "golem", "golem", 8, 8, 19, {"category": "enemy", "anchor_kind": "big_enemy"}),
    "fox": ("fox", "fox", "elite", 8, 12, 24, {"category": "elite", "anchor_kind": "big_enemy"}),
    "ghoul": ("ghoul", "ghoul", "elite", 8, 8, 30, {"category": "elite", "anchor_kind": "big_enemy"}),
    "stonelord": ("stonelord", "stonelord", "elite", 8, 6, 28, {"category": "elite", "anchor_kind": "big_enemy"}),
    # 九尾着地，但锚点正上方最高处是摆动的尾扇，“头顶”y 配准没有意义，所以自检只查 x（身高仍逐帧查）。
    # 不能写 floating：游戏会给 floating 的妖物加悬浮起伏。
    "boss": ("fox", "boss", "boss", 8, 8, 44, {"category": "boss", "register_x_only": True, "anchor_kind": "big_enemy"}),
    "toad": ("toad", "toad", "small", 6, 10, 14, {"category": "enemy", "vertical_motion": True}),
}
ALL += list(BATCH2)
ALL += ["ancient_lamp", "blood_altar", "merchant", "stone_lantern_dark"]
HERO_LAMPS = ("red", "mirror", "frost")  # 主角的灯笼叠层（lanterns.LAMP_IDS）；跟着 hero 一起渲
OVERLAYS = [f"lantern_{lid}" for lid in HERO_LAMPS]
CHECK = ALL + OVERLAYS  # 自检的素材（叠层不单独渲，只自检）
HERO_ACTIONS = {"dash": (4, 16, {}), "hurt": (2, 10, {}),
                "death": (6, 8, {"loop": False, "vertical_motion": True})}  # 帧数, fps, 额外 meta
HERO_IDLE, HERO_WALK = 6, 8
SHADE_FRAMES, WISP_FRAMES = 8, 6


def hero_jobs(only_anims=None) -> list:
    jobs = [("idle", d, i, HERO_IDLE) for d in S.DIRS for i in range(HERO_IDLE)]
    jobs += [("walk", d, i, HERO_WALK) for d in S.DIRS for i in range(HERO_WALK)]
    for an, (n, fps, extra) in HERO_ACTIONS.items():
        jobs += [(an, d, i, n) for d in S.DIRS for i in range(n)]
    if only_anims:
        jobs = [j for j in jobs if j[0] in only_anims]
    return jobs


def render_hero(jobs, out_root: Path = ASSETS, merge: bool = False, timings: dict | None = None,
                lamps=HERO_LAMPS) -> None:
    """主角底图 hero/ + 每盏灯一份叠层 lantern_<灯>/：每个姿态在同一个 Blender 会话里连渲 1 + len(lamps) 遍。"""
    import functools
    import hero as HERO
    import lanterns as LAN

    info = LAN.lamp_data()
    hero_h = S.HERO_HEIGHT_M * S.PX_PER_M * math.cos(math.radians(S.CAMERA_PITCH_DEG))
    anim_extra = {"idle": {"fps": 6}, "walk": {"fps": 12, "stride_units": HERO.walk_stride_units()},
                  **{an: {"fps": fps, **extra} for an, (n, fps, extra) in HERO_ACTIONS.items()}}
    variants = []
    for lid in lamps:
        pe = LAN.palette_extra(lid)
        variants.append({"name": f"lantern_{lid}", "scope": functools.partial(HERO.lamp_scope, lamp=lid),
                         "palette_extra": pe,
                         "meta_extra": {"category": "overlay", "base": "hero", "lamp": lid, "lamp_name": info[lid]["name"],
                                        "light_color": info[lid]["color"], "layers": ["emit"],
                                        **({"palette_extra": pe} if pe else {})}})
    render_asset("hero", S.FRAME["hero"], functools.partial(HERO.build_hero, lamps=lamps), jobs, out_root,
                 pose=HERO.pose_hero, sockets_wanted=("lantern",), timings=timings, merge=merge,
                 scope=HERO.base_scope, variants=variants,
                 meta_extra={"category": "hero", "height_px": round(hero_h, 2), "layers": [],
                             "overlays": [f"lantern_{lid}" for lid in lamps],
                             "required_sockets": ["lantern"], "shadow_radius_px": round(13 * D), "anim_extra": anim_extra})


def produce(name: str, timings: dict, out_root: Path = ASSETS):
    import shade as GHOST
    import rock as ROCK
    import stone_lantern as SL

    ASSETS = out_root  # noqa: N806 - 下面沿用原来的名字
    if name.startswith("hero"):  # "hero" 全部；"hero:dash+death" 只重渲这些动画（其它帧和 meta 保留）
        only_anims = name.split(":", 1)[1].split("+") if ":" in name else None
        render_hero(hero_jobs(only_anims), ASSETS, merge=bool(only_anims), timings=timings)
    elif name in ("shade", "wisp"):
        n = SHADE_FRAMES if name == "shade" else WISP_FRAMES
        build = GHOST.build_shade if name == "shade" else GHOST.build_wisp
        render_asset(name, S.FRAME["small"], build, [("float", "E", i, n) for i in range(n)], ASSETS,
                     pose=GHOST.pose_ghost, sockets_wanted=("eyes",), flash=True, timings=timings,
                     meta_extra={"category": "enemy", "floating": True, "layers": ["emit", "flash"],
                                 "required_sockets": ["eyes"], "shadow_radius_px": round((15 if name == "shade" else 12) * D),
                                 "anim_extra": {"float": {"fps": 8 if name == "shade" else 10}}})
    elif name.startswith("rock_"):
        v = name[-1]
        render_asset(name, S.FRAME["prop"], lambda: ROCK.build_rock(v), [("idle", "S", 0, 1)], ASSETS,
                     anchor=S.PROP_ANCHOR, timings=timings,
                     meta_extra={"category": "prop", "shadow_radius_px": round(20 * D), "anim_extra": {"idle": {"fps": 1}}})
    elif name == "stone_lantern":
        render_asset(name, S.FRAME["prop"], SL.build_stone_lantern, [("idle", "S", 0, 1)], ASSETS,
                     anchor=S.PROP_ANCHOR, sockets_wanted=("flame",), timings=timings,
                     meta_extra={"category": "prop", "layers": ["emit"], "required_sockets": ["flame"],
                                 "shadow_radius_px": round(16 * D), "anim_extra": {"idle": {"fps": 1}}})
    elif name == "stone_lantern_dark":  # 没点亮的石灯笼：窗口焦墨、没有 _emit；纸纹用亮的那张的，点灯时直接换图
        render_asset(name, S.FRAME["prop"], lambda: SL.build_stone_lantern(lit=False), [("idle", "S", 0, 1)], ASSETS,
                     anchor=S.PROP_ANCHOR, sockets_wanted=("flame",), timings=timings, grain="stone_lantern",
                     meta_extra={"category": "prop", "lit_variant": "stone_lantern", "required_sockets": ["flame"],
                                 "shadow_radius_px": round(16 * D), "anim_extra": {"idle": {"fps": 1}}})
    elif name in ("ancient_lamp", "blood_altar", "merchant"):
        import event_props as EP
        sock = "glow" if name == "blood_altar" else "flame"
        radius = 30 if name == "merchant" else 20
        render_asset(name, S.FRAME["prop"], getattr(EP, f"build_{name}"), [("idle", "S", 0, 1)], ASSETS,
                     anchor=S.PROP_ANCHOR, sockets_wanted=(sock,), timings=timings,
                     meta_extra={"category": "prop", "layers": ["emit"], "required_sockets": [sock],
                                 "shadow_radius_px": round(radius * D), "anim_extra": {"idle": {"fps": 1}}})
    elif name in BATCH2:
        import importlib
        mod, fn, fk, n, fps, radius, extra = BATCH2[name]
        M = importlib.import_module(mod)
        anchor = S.BIG_ENEMY_ANCHOR if extra.get("anchor_kind") == "big_enemy" else S.ANCHOR
        render_asset(name, S.FRAME[fk], getattr(M, f"build_{fn}"), [("move", "E", i, n) for i in range(n)], ASSETS,
                     pose=getattr(M, f"pose_{fn}"), sockets_wanted=("eyes",), flash=True, timings=timings, anchor=anchor,
                     meta_extra={**extra, "layers": ["emit", "flash"], "required_sockets": ["eyes"],
                                 "game_radius": radius, "shadow_radius_px": round(radius * S.PX_PER_UNIT * 0.8),
                                 "anim_extra": {"move": {"fps": fps}}})
    else:
        raise SystemExit(f"未知素材 {name}")


# ================================================================ 审图
def with_overlay(A: dict, O: dict) -> dict:
    """主角底图 + 灯笼叠层合成的素材（审图用；游戏里也是这样叠画）：同名帧逐帧叠上，发光层也叠上。"""
    ov = {f["key"]: f for f in O["frames"]}
    frames = []
    for f in A["frames"]:
        o = ov.get(f["key"])
        if o is None:
            frames.append(f)
            continue
        rgba = f["rgba"].copy()
        rgba.alpha_composite(o["rgba"])
        emit = o["emit"]
        if f["emit"] is not None and emit is not None:
            emit = f["emit"].copy()
            emit.alpha_composite(o["emit"])
        frames.append(dict(f, rgba=rgba, emit=emit if emit is not None else f["emit"]))
    return dict(A, frames=frames)


def load_assets(names, lamp: str = "red") -> dict:
    """读素材；主角自动叠上某盏灯的叠层（有的话）。"""
    A = {n: CS.load_asset(ASSETS / n) for n in names}
    if "hero" in A and (ASSETS / f"lantern_{lamp}" / "meta.json").exists():
        A["hero"] = with_overlay(A["hero"], CS.load_asset(ASSETS / f"lantern_{lamp}"))
    return A


def view(A: dict, keys: list[str]) -> dict:
    return dict(A, frames=[f for k in keys for f in A["frames"] if f["key"] == k])


def mirrored(f: dict) -> dict:
    return dict(f, rgba=ImageOps.mirror(f["rgba"]), emit=ImageOps.mirror(f["emit"]) if f["emit"] else None,
                sockets={k: (-v[0], v[1]) for k, v in f["sockets"].items()})


def scene(A: dict, scale: float = 1.0, size=(600 * D, 360 * D)):
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
              (sl_at[0] + fx * scale, sl_at[1] + fy * scale, CS.SOCKET_LIGHTS["flame"][0] * scale, S.FLAME_LIGHT)]

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
    A = load_assets(ALL)
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
    g = int(10 * D)
    gs = Image.new("RGB", (d1.width + d2.width + g, d1.height * 2 + g), CS.rgb(S.PAPER))
    gs.paste(d1.convert("RGB"), (0, 0))
    gs.paste(night, (0, d1.height + g))
    gs.paste(d2.convert("RGB"), (d1.width + g, 0))
    gs.paste(CS.night_composite(d2, e2, l2), (d1.width + g, d1.height + g))
    gs.save(REVIEW / "game_size.png")
    hero_rows = [view(A["hero"], [f"idle_{d}_00" for d in S.DIRS]),
                 view(A["hero"], [f"walk_{d}_02" for d in S.DIRS]),
                 view(A["hero"], [f"walk_E_{i:02d}" for i in range(HERO_WALK)]),
                 view(A["hero"], [f"walk_S_{i:02d}" for i in range(HERO_WALK)])]
    hs = CS.sheet(hero_rows)
    hs.save(REVIEW / "hero_sheet_day.png")
    CS.zoom(hs).save(REVIEW / "hero_sheet_zoom.png")
    compass = ["NW", "N", "NE", "W", None, "E", "SW", "S", "SE"]  # 按屏幕方位排的 3×3
    CS.gif(CS.grid_frames(A["hero"], "walk", compass, cols=3), REVIEW / "hero_walk_8dir.gif", 12)
    CS.gif(CS.grid_frames(A["hero"], "idle", compass, cols=3), REVIEW / "hero_idle_8dir.gif", 6)
    for n, fps in (("shade", 8), ("wisp", 10)):
        CS.gif([f["rgba"] for f in A[n]["frames"]], REVIEW / f"{n}_float.gif", fps, zoom_k=3)
    timings["review_s"] = round(time.perf_counter() - t, 2)


def build_review_batch2(timings: dict):
    """第二批妖物的审图：排成一排比大小（含主角、影妖、疾影）、逐帧总表、夜景、各自的动图。"""
    REVIEW.mkdir(parents=True, exist_ok=True)
    t = time.perf_counter()
    names = ["hero", "shade", "wisp", "toad", "golem", "fox", "ghoul", "stonelord", "boss"]
    A = load_assets(names)
    # 1) 同一地面上排成一排（游戏 1 倍大小），再给 3 倍
    gap = int(10 * D)
    ws = [A[n]["meta"]["size"][0] for n in names]
    W = int(sum(w * 0.72 for w in ws) + gap * (len(names) + 1))
    Hh = int(300 * D)
    day = CS.paper(W, Hh, seed=11)
    emit = np.zeros((Hh, W, 3), np.float32)
    x = gap
    for n in names:
        f = A[n]["frames"][0]
        w = A[n]["meta"]["size"][0]
        at = (x + w * 0.36, Hh - 24 * D)
        CS.place(day, f, A[n]["meta"], at)
        CS.place_emit(emit, f, A[n]["meta"], at)
        x += w * 0.72 + gap
    day.convert("RGB").save(REVIEW / "batch2_lineup.png")
    CS.zoom(day.convert("RGB"), 3).save(REVIEW / "batch2_lineup_zoom.png")
    # 2) 逐帧总表（1 倍、3 倍）
    rows = [A[n] for n in ("toad", "golem", "fox", "ghoul", "stonelord", "boss")]
    sh = CS.sheet(rows)
    sh.save(REVIEW / "batch2_frames.png")
    CS.zoom(sh, 3).save(REVIEW / "batch2_frames_zoom.png")
    # 3) 夜景：主角提灯居中，赤面狐、青面鬼在光圈边缘，九尾在后方半明半暗，石将、石妖在暗处只见眼，金蟾在光里
    w, h = int(900 * D), int(520 * D)
    day = CS.paper(w, h, seed=13, blotches=10)
    emit = np.zeros((h, w, 3), np.float32)
    hf = next(f for f in A["hero"]["frames"] if f["key"] == "idle_S_00")
    hero_at = (w * 0.50, h * 0.74)
    lx, ly = hf["sockets"]["lantern"]
    light = (hero_at[0] + lx, hero_at[1] + ly)
    R = CS.LIGHT_RADIUS_PX
    def polar(ang, dist):
        a = math.radians(ang)
        return (light[0] + math.cos(a) * dist * R, light[1] + math.sin(a) * dist * R)
    items = [
        ("boss", mirrored(A["boss"]["frames"][0]), (w * 0.72, h * 0.42)),
        ("stonelord", A["stonelord"]["frames"][0], (w * 0.12, h * 0.40)),
        ("golem", mirrored(A["golem"]["frames"][2]), (w * 0.90, h * 0.86)),
        ("fox", A["fox"]["frames"][0], polar(175, 0.95)),
        ("ghoul", mirrored(A["ghoul"]["frames"][0]), polar(5, 1.05)),
        ("toad", A["toad"]["frames"][0], polar(110, 0.55)),
        ("hero", hf, hero_at),
    ]
    for n, f, pos in sorted(items, key=lambda it: it[2][1]):
        CS.place(day, f, A[n]["meta"], pos)
        CS.place_emit(emit, f, A[n]["meta"], pos)
    night = CS.night_composite(day, emit, [(light[0], light[1], R, S.LANTERN_LIGHT)])
    night.save(REVIEW / "batch2_night.png")
    day.convert("RGB").save(REVIEW / "batch2_day_scene.png")
    # 4) 动图
    for n in ("toad", "golem", "fox", "ghoul", "stonelord", "boss"):
        fps = A[n]["meta"]["anims"]["move"]["fps"]
        CS.gif([f["rgba"] for f in A[n]["frames"]], REVIEW / f"{n}_move.gif", fps,
               zoom_k=1 if n == "boss" else 2)
    timings["review2_s"] = round(time.perf_counter() - t, 2)


def build_review_desktop(timings: dict):
    """桌面版（任意密度）审图：游戏大小的总排列、几帧 3 倍放大、夜景、新动作和改过的妖物动图。"""
    REVIEW.mkdir(parents=True, exist_ok=True)
    t = time.perf_counter()
    A = load_assets(ALL)
    # 1) 游戏大小总排列：角色一排、道具一排
    def lineup(names, keys, path, hh):
        gap = int(10 * D)
        W = int(sum(A[n]["meta"]["size"][0] * 0.7 for n in names) + gap * (len(names) + 1))
        Hh = int(hh * D)
        day = CS.paper(W, Hh, seed=11)
        x = gap
        for n, k in zip(names, keys):
            f = next((fr for fr in A[n]["frames"] if fr["key"] == k), A[n]["frames"][0])
            w = A[n]["meta"]["size"][0]
            CS.place(day, f, A[n]["meta"], (x + w * 0.35, Hh - 22 * D))
            x += w * 0.7 + gap
        day.convert("RGB").save(path)
        return day
    actors = ["hero", "hero", "hero", "shade", "wisp", "toad", "golem", "fox", "ghoul", "stonelord", "boss"]
    keys = ["idle_S_00", "dash_E_01", "death_S_05", "float_E_00", "float_E_00", "move_E_00", "move_E_00", "move_E_00",
            "move_E_00", "move_E_00", "move_E_00"]
    lineup(actors, keys, REVIEW / "lineup_actors.png", 300)
    props = ["rock_a", "rock_b", "rock_c", "stone_lantern", "stone_lantern_dark", "ancient_lamp", "blood_altar", "merchant"]
    lineup(props, ["idle_S_00"] * len(props), REVIEW / "lineup_props.png", 110)
    # 2) 几帧 3 倍放大
    picks = [("hero", "idle_S_00"), ("hero", "dash_E_01"), ("hero", "hurt_S_00"), ("hero", "death_E_04"),
             ("fox", "move_E_00"), ("ghoul", "move_E_00"), ("stonelord", "move_E_00"),
             ("ancient_lamp", "idle_S_00"), ("blood_altar", "idle_S_00")]
    tiles = []
    for n, k in picks:
        f = next(fr for fr in A[n]["frames"] if fr["key"] == k)
        bg = CS.paper(f["rgba"].width, f["rgba"].height, seed=2)
        bg.alpha_composite(f["rgba"])
        tiles.append(bg.convert("RGB"))
    Hm = max(t_.height for t_ in tiles)
    zs = Image.new("RGB", (sum(t_.width for t_ in tiles), Hm), CS.rgb(S.PAPER))
    x = 0
    for t_ in tiles:
        zs.paste(t_, (x, Hm - t_.height)); x += t_.width
    CS.zoom(zs, 3).save(REVIEW / "zoom3_frames.png")
    bf = A["boss"]["frames"][0]["rgba"]
    bg = CS.paper(bf.width, bf.height, seed=2); bg.alpha_composite(bf)
    CS.zoom(bg.convert("RGB"), 2).save(REVIEW / "zoom2_boss.png")
    # 3) 夜景：主角居中；光圈边缘赤面狐、青面鬼；后方九尾半隐；石将、石妖在暗处；古灯、血祭坛、石灯笼各自发光
    w, h = int(1000 * D), int(560 * D)
    day = CS.paper(w, h, seed=13, blotches=10)
    emit = np.zeros((h, w, 3), np.float32)
    hf = next(f for f in A["hero"]["frames"] if f["key"] == "idle_S_00")
    hero_at = (w * 0.47, h * 0.74)
    lx, ly = hf["sockets"]["lantern"]
    light = (hero_at[0] + lx, hero_at[1] + ly)
    R = CS.LIGHT_RADIUS_PX
    lights = [(light[0], light[1], R, S.LANTERN_LIGHT)]
    def polar(ang, dist):
        a = math.radians(ang)
        return (light[0] + math.cos(a) * dist * R, light[1] + math.sin(a) * dist * R)
    items = [
        ("boss", mirrored(A["boss"]["frames"][0]), (w * 0.74, h * 0.40)),
        ("stonelord", A["stonelord"]["frames"][0], (w * 0.10, h * 0.42)),
        ("golem", mirrored(A["golem"]["frames"][2]), (w * 0.92, h * 0.90)),
        ("fox", A["fox"]["frames"][0], polar(172, 0.95)),
        ("ghoul", mirrored(A["ghoul"]["frames"][0]), polar(8, 1.05)),
        ("shade", A["shade"]["frames"][0], (w * 0.30, h * 0.92)),
        ("ancient_lamp", A["ancient_lamp"]["frames"][0], (w * 0.24, h * 0.62)),
        ("blood_altar", A["blood_altar"]["frames"][0], (w * 0.62, h * 0.93)),
        ("stone_lantern", A["stone_lantern"]["frames"][0], (w * 0.90, h * 0.55)),
        ("hero", hf, hero_at),
    ]
    for n, f, pos in sorted(items, key=lambda it: it[2][1]):
        CS.place(day, f, A[n]["meta"], pos)
        CS.place_emit(emit, f, A[n]["meta"], pos)
        for sn, (rad, col) in CS.SOCKET_LIGHTS.items():
            if sn in f["sockets"] and n != "hero":
                sx, sy = f["sockets"][sn]
                lights.append((pos[0] + sx, pos[1] + sy, rad, col))
    CS.night_composite(day, emit, lights).save(REVIEW / "night_scene.png")
    day.convert("RGB").save(REVIEW / "day_scene.png")
    # 4) 动图：主角新动作（8 向网格）、走路、改过的妖物
    compass = ["NW", "N", "NE", "W", None, "E", "SW", "S", "SE"]
    for an in ("dash", "hurt", "death", "walk", "idle"):
        fps = A["hero"]["meta"]["anims"][an]["fps"]
        frames = CS.grid_frames(A["hero"], an, compass, cols=3)
        frames = [f.resize((f.width // int(D), f.height // int(D)), Image.LANCZOS) for f in frames] if D > 1 else frames
        CS.gif(frames, REVIEW / f"hero_{an}_8dir.gif", fps, zoom_k=1)
    for n in ("fox", "ghoul", "stonelord", "boss", "golem", "toad", "shade", "wisp"):
        an = next(iter(A[n]["meta"]["anims"]))
        fps = A[n]["meta"]["anims"][an]["fps"]
        CS.gif([f["rgba"] for f in A[n]["frames"]], REVIEW / f"{n}_{an}.gif", fps, zoom_k=1 if n == "boss" or D > 1 else 2)
    timings["review_desktop_s"] = round(time.perf_counter() - t, 2)


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
    results = [C.check_asset(ASSETS / n) for n in CHECK if (ASSETS / n / "meta.json").exists()]
    print("\n==== check_asset ====")
    for r in results:
        print(C.report(r))
    timings["check_s"] = round(time.perf_counter() - t, 2)
    REVIEW.mkdir(parents=True, exist_ok=True)
    (REVIEW / "check_report.json").write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    if all((ASSETS / n / "meta.json").exists() for n in ALL):
        build_review_desktop(timings)
    elif D == 1 and all((ASSETS / n / "meta.json").exists() for n in ALL[:13]):
        build_review(timings)
        build_review_batch2(timings)
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
