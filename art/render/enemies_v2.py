#!/usr/bin/env python3
"""妖物重做（精修三维）的正式出图：models/<妖物>_v2.py 建模 + models/v2kit.py 的材质、墨线、后期。

和旧管线（render/pipeline.py）的区别：
  - 后期不吸附调色板（多档带色相偏移的渐变），墨线按填色渐隐、打散一点，缝里的魂光走 AOV 通道；
  - meta 里写 style: "paint"（check_asset.py 对这种素材不查调色板比例和墨线占比）、contact_radius（见下）。
输出格式同旧管线：<out>/<素材>/<动画>_E_<NN>.png、_emit.png、_flash.png、meta.json（逐帧挂点，相对锚点的最终像素）。
只画 E（游戏里镜像得到西）。最终渲染包在 bstyle.render_lock() 里（别的代理也在用 Blender）。

contact_radius（世界单位）：量法同 docs/PLAYTEST.md 的表——取朝东的帧，锚点往上 52 单位（主角身高）以内，
每一行身体最靠前的点（alpha > 0.5）；每帧取各行前沿的第 90 百分位，再在动画各帧之间取中位数；
默认动画（default_anim）的结果和 game_radius 取较小的那个。各动画分别量的值写在 contact_radius_by_anim。

    LANTERN_ART_DENSITY=2 art/.venv/bin/python art/render/produce.py --only shade,fox   # 正式出图（走这里）
    LANTERN_ART_DENSITY=2 art/.venv/bin/python art/render/enemies_v2.py --preview fox:pounce:3 out.png
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("LANTERN_ART_DENSITY", "2")

ART = Path(__file__).resolve().parents[1]
for p in (ART, ART / "models", ART / "post", ART / "render"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

from style import style as S  # noqa: E402

D = S.DENSITY
ASSETS = ART / "out" / S.ASSETS_DIR_NAME
TMP = ART / "out" / "_tmp_enemies_v2"
CONTACT_HEIGHT_UNITS = 52.0  # 主角身高：量前沿时只看锚点往上这么高

# 素材 → 设置。size_1x：1 倍密度的帧边长（2 倍时乘 2）；anims：(动画, 帧数, fps, 额外 meta)；
# lines：墨线三档宽（1 倍像素）；glow：AOV 缝光 / 夜光的颜色；sockets：逐帧挂点（模型里同名的空物体）。
V2 = {
    # 影妖：人那么高（主角 0.88 倍），帧 224²；锚点是下摆墨烟的落地点；眼色改成暖金
    "shade": {"module": "shade_v2", "build": "build_shade", "pose": "pose_shade", "size_1x": 112, "anchor": S.ANCHOR,
              "anims": [("float", 8, 8, {})], "radius": 13, "eye": "#FFC46B", "glow": "#F7D58A",
              "lines": (1.6, 1.0, 0.8), "sockets": ("eyes",), "shadow_units": 8,
              "meta": {"category": "enemy", "floating": True, "default_anim": "float"}},
    # 疾影：一缕被风扯长的薄墨烟（独立造型，不是小号影妖）；帧 224²（原 160²），锚点同影妖
    "wisp": {"module": "wisp_v2", "build": "build_wisp", "pose": "pose_wisp", "size_1x": 112, "anchor": S.ANCHOR,
             "anims": [("float", 6, 10, {})], "radius": 10, "eye": "#9FE3FF", "glow": "#8CC8E8",
             "lines": (1.2, 0.8, 0.6), "sockets": ("eyes",), "shadow_units": 6,
             "meta": {"category": "enemy", "floating": True, "default_anim": "float"}},
    # 石妖：青灰山石垒成的矮胖身子；帧 224²、锚点 (0.5, 0.8)
    "golem": {"module": "golem_v2", "build": "build_golem", "pose": "pose_golem", "size_1x": 112,
              "anchor": S.BIG_ENEMY_ANCHOR, "anims": [("move", 8, 8, {})], "radius": 19, "eye": "#FFB46B",
              "glow": "#FFB46B", "lines": (2.0, 1.15, 0.8), "sockets": ("eyes",), "shadow_units": 15,
              # 锚点正上方是驼背的斜坡（不是头顶），石头前后一点头那里就上下变：自检只查 x 配准
              "meta": {"category": "enemy", "anchor_kind": "big_enemy", "default_anim": "move", "register_x_only": True}},
    # 狐火：一团青绿冷火拖成狐尾；帧 224²（原 160²），悬浮；扑击 2 帧蓄力
    "fox_wisp": {"module": "fox_wisp_v2", "build": "build_fox_wisp", "pose": "pose_fox_wisp", "size_1x": 112,
                 "anchor": S.ANCHOR,
                 "anims": [("float", 8, 10, {}),
                           ("pounce", 4, 10, {"loop": False, "windup_frames": 2, "vertical_motion": True})],
                 "radius": 10, "eye": "#F2FFFC", "glow": "#8FE3C8", "lines": (1.0, 0.7, 0.6), "sockets": ("eyes",),
                 "shadow_units": 6, "meta": {"category": "enemy", "floating": True, "default_anim": "float"}},
    # 竹魅：竹节拼成的细长人形；帧 320²、锚点 (0.5, 0.875)；挂点 eyes、muzzle（竹刺出手的位置）
    "bamboo_wraith": {"module": "bamboo_v2", "build": "build_bamboo_wraith", "pose": "pose_bamboo_wraith", "size_1x": 160,
                      "anchor": S.ANCHOR,
                      "anims": [("idle", 4, 4, {}), ("move", 6, 8, {}),
                                ("shoot", 5, 10, {"loop": False, "windup_frames": 2})],
                      "radius": 12, "eye": "#9BF5C9", "glow": "#9BF5C9", "lines": (2.0, 1.15, 0.8),
                      "sockets": ("eyes", "muzzle"), "shadow_units": 9.5,
                      "meta": {"category": "enemy", "default_anim": "move"}},
    # 讨封狐：扮人（斗笠蓑衣）、现形（直立的狐狸穿不合身的人衣）；帧 256²（原 224²），锚点 (0.5, 0.875)
    "taofeng_fox": {"module": "taofeng_v2", "build": "build_taofeng_fox", "pose": "pose_taofeng_fox", "size_1x": 128,
                    "anchor": S.ANCHOR,
                    # reveal：一跳、蓑衣掀起，身高一帧一个样（自检不查逐帧身高；游戏不读）
                    "anims": [("disguise", 6, 8, {}), ("move", 6, 10, {}),
                              ("reveal", 4, 8, {"loop": False, "vertical_motion": True})],
                    "radius": 13, "eye": "#FFD23F", "glow": "#FFD23F", "lines": (1.8, 1.1, 0.8), "sockets": ("eyes",),
                    "shadow_units": 10.5, "meta": {"category": "enemy", "default_anim": "disguise"}},
    # 青面鬼：精英（小头目），帧 320²、锚点 (0.5, 0.8)；冲锋 2 帧蓄力、从第 2 帧起循环；肚子里的魂光走 AOV
    "ghoul": {"module": "ghoul_v2", "build": "build_ghoul", "pose": "pose_ghoul", "size_1x": 160,
              "anchor": S.BIG_ENEMY_ANCHOR,
              # move 一步一沉 1.1 单位（驼背跟着上下，自检只查 x 配准；游戏不读）
              "anims": [("move", 8, 8, {"vertical_motion": True}),
                        ("charge", 6, 10, {"loop": False, "windup_frames": 2, "loop_from": 2, "vertical_motion": True})],
              "radius": 30, "eye": "#FF4636", "glow": "#F7C978", "lines": (2.2, 1.25, 0.85), "sockets": ("eyes",),
              "shadow_units": 24, "meta": {"category": "elite", "anchor_kind": "big_enemy", "default_anim": "move"}},
    # 石将：精英，石翁仲（3/4 侧面）；帧 320²、锚点 (0.5, 0.8)
    "stonelord": {"module": "stonelord_v2", "build": "build_stonelord", "pose": "pose_stonelord", "size_1x": 160,
                  # move 一步一沉（石头人落脚重，盔顶跟着上下，自检只查 x 配准；游戏不读）
                  "anchor": S.BIG_ENEMY_ANCHOR, "anims": [("move", 8, 6, {"vertical_motion": True})], "radius": 28,
                  "eye": "#FFB46B",
                  "glow": "#FFB46B", "lines": (2.2, 1.25, 0.85), "sockets": ("eyes",), "shadow_units": 22.5,
                  "meta": {"category": "elite", "anchor_kind": "big_enemy", "default_anim": "move"}},
    # 金蟾：三足、衔钱、一蹦一蹦（vertical_motion）；帧 192²（原 160²）、锚点 (0.5, 0.875)
    "toad": {"module": "toad_v2", "build": "build_toad", "pose": "pose_toad", "size_1x": 96, "anchor": S.ANCHOR,
             "anims": [("move", 6, 10, {})], "radius": 14, "eye": "#FFF1C2", "glow": "#FFD36B", "lines": (1.6, 1.0, 0.75),
             "sockets": ("eyes",), "shadow_units": 11.25,
             "meta": {"category": "enemy", "vertical_motion": True, "default_anim": "move"}},
    # 赤面狐：精英，帧 320²、锚点 (0.5, 0.8)；扑击 2 帧蓄力
    "fox": {"module": "fox_v2", "build": "build_fox", "pose": "pose_fox", "size_1x": 160, "anchor": S.BIG_ENEMY_ANCHOR,
            "anims": [("move", 8, 12, {"vertical_motion": True}),  # 小跑一步一起伏 1.7 单位（自检不查逐帧身高）
                      ("pounce", 6, 12, {"loop": False, "windup_frames": 2, "vertical_motion": True})],
            "radius": 24, "eye": "#FF6B5A", "glow": "#E2553C", "lines": (2.0, 1.15, 0.8), "sockets": ("eyes",),
            "shadow_units": 19.2, "meta": {"category": "elite", "anchor_kind": "big_enemy", "default_anim": "move",
                                           "register_band": [0.70, 0.92]}},  # 四足：配准取躯干那一段（见 check_asset）
}


def frame_px(name):
    return int(round(V2[name]["size_1x"] * D))


def contact_front(folder: Path, anim: str, meta: dict) -> float:
    """一个动画的“画出来的前沿”（世界单位），量法见文件头。"""
    W, H = meta["size"]
    ax, ay = meta["anchor"][0] * W, meta["anchor"][1] * H
    ppu = float(meta["px_per_unit"])
    n = meta["anims"][anim]["frames"]
    fronts = []
    for i in range(n):
        a = np.asarray(Image.open(folder / f"{anim}_E_{i:02d}.png"))[..., 3] / 255.0
        per = []
        for y in range(max(0, int(ay - CONTACT_HEIGHT_UNITS * ppu)), min(H, int(ay) + 1)):
            xs = np.nonzero(a[y] > 0.5)[0]
            if len(xs):
                per.append((xs.max() + 0.5 - ax) / ppu)
        if per:
            fronts.append(float(np.percentile(per, 90)))
    return float(np.median(fronts)) if fronts else 0.0


def write_contact(folder: Path) -> dict:
    """量各动画的前沿，写进 meta：contact_radius（默认动画，和 game_radius 取小）、contact_radius_by_anim。"""
    mp = folder / "meta.json"
    meta = json.loads(mp.read_text(encoding="utf-8"))
    by = {an: round(contact_front(folder, an, meta), 1) for an in meta["anims"]}
    default = meta.get("default_anim") or next(iter(meta["anims"]))
    meta["contact_radius_by_anim"] = by
    meta["contact_radius"] = round(min(by[default], float(meta.get("game_radius", by[default]))), 1)
    mp.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"contact_radius": meta["contact_radius"], "by_anim": by}


def _setup(name):
    from style import bstyle as B
    import v2kit as V2K

    cfg = V2[name]
    F = frame_px(name)
    B.reset_scene()
    B.setup_render(F)
    B.setup_camera(F, anchor=cfg["anchor"])
    B.verify_camera(F, verbose=False)
    o, f, i = cfg["lines"]
    V2K.setup_lines(outer_px=o, form_px=f, inner_px=i)
    return F


def render(name: str, out_root: Path = ASSETS, only_anims=None, timings: dict | None = None, only_frames=None) -> Path:
    """出一只妖物的全部帧（only_anims：只重渲这几个动画，其它帧和 meta 保留）。返回素材文件夹。"""
    import importlib
    from style import bstyle as B
    import v2kit as V2K

    t0 = time.perf_counter()
    cfg = V2[name]
    F = _setup(name)
    M = importlib.import_module(cfg["module"])
    root, parts, socks = getattr(M, cfg["build"])()
    pose = getattr(M, cfg["pose"])
    out = Path(out_root) / name
    out.mkdir(parents=True, exist_ok=True)
    redo = {an for an, *_ in cfg["anims"] if not only_anims or an in only_anims}
    old_meta = None
    if only_anims and (out / "meta.json").exists():
        old_meta = json.loads((out / "meta.json").read_text(encoding="utf-8"))
        for fp in out.glob("*.png"):
            if fp.name.split("_")[0] in redo:
                fp.unlink()
    else:
        for fp in list(out.glob("*.png")) + list(out.glob("meta.json")):
            fp.unlink()
    sock_out = {s: {} for s in cfg["sockets"]}
    times = []
    with B.render_lock():
        for an, n, fps, _ in cfg["anims"]:
            if an not in redo:
                continue
            for i in range(n):
                if only_frames and i not in only_frames.get(an, range(n)):
                    continue
                B.set_direction(root, "E")
                pose(parts, an, i, n)
                tr = time.perf_counter()
                L = V2K.render(TMP / f"{name}_{an}_{i:02d}")
                times.append(time.perf_counter() - tr)
                rgba, emit, flash = V2K.post(L, name, cfg["glow"], seed=i + 7)
                base = f"{an}_E_{i:02d}"
                Image.fromarray(rgba, "RGBA").save(out / f"{base}.png", optimize=True)
                Image.fromarray(emit, "RGBA").save(out / f"{base}_emit.png", optimize=True)
                Image.fromarray(flash, "RGBA").save(out / f"{base}_flash.png", optimize=True)
                for s in cfg["sockets"]:
                    x, y = B.project_point(socks[s].matrix_world.translation, F)
                    sock_out[s].setdefault(an, {}).setdefault("E", []).append([round(x, 2), round(y, 2)])
    anims = {an: {"frames": n, "fps": fps, "dirs": ["E"], **ex} for an, n, fps, ex in cfg["anims"]}
    meta = {"name": name, "size": [F, F], "anchor": list(cfg["anchor"]), "px_per_unit": S.PX_PER_UNIT, "anims": anims,
            "sockets": sock_out, **cfg["meta"], "layers": ["emit", "flash"], "required_sockets": list(cfg["sockets"]),
            "eye_color": cfg["eye"], "game_radius": cfg["radius"],
            "shadow_radius_px": round(cfg["shadow_units"] * S.PX_PER_UNIT), "style": "paint"}
    if old_meta is not None:  # 只重渲部分动画：其它动画的挂点沿用旧 meta
        for s, by in old_meta.get("sockets", {}).items():
            for an, v in by.items():
                if an not in redo:
                    meta["sockets"].setdefault(s, {})[an] = v
    (out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    cr = write_contact(out)
    for p in TMP.glob("*.exr"):
        p.unlink()
    info = {"frames": len(times), "render_s_mean": round(float(np.mean(times)), 2) if times else 0.0,
            "faces": B.face_count(root), "total_s": round(time.perf_counter() - t0, 1), **cr}
    if timings is not None:
        timings[name] = info
    print(f"[{name}] {info}")
    return out


def preview(spec: str, path: str) -> None:
    """单帧预览：素材:动画:帧号 → 3 倍放大、纸色底（另存一张发光层）。不写素材文件夹。"""
    import importlib
    from style import bstyle as B
    import v2kit as V2K

    name, an, idx = spec.split(":")
    cfg = V2[name]
    F = _setup(name)
    M = importlib.import_module(cfg["module"])
    root, parts, socks = getattr(M, cfg["build"])()
    n = next(nn for a, nn, *_ in cfg["anims"] if a == an)
    with B.render_lock():
        B.set_direction(root, "E")
        getattr(M, cfg["pose"])(parts, an, int(idx), n)
        L = V2K.render(TMP / f"preview_{name}")
    rgba, emit, _ = V2K.post(L, name, cfg["glow"], seed=int(idx) + 7)
    im = Image.fromarray(rgba, "RGBA")
    big = im.resize((im.width * 3, im.height * 3), Image.NEAREST)
    bg = Image.new("RGBA", big.size, S.hex_to_rgb(S.PAPER) + (255,))
    bg.alpha_composite(big)
    bg.convert("RGB").save(path)
    e = Image.fromarray(emit, "RGBA")
    eb = Image.new("RGBA", e.size, (30, 34, 50, 255))
    eb.alpha_composite(e)
    eb.convert("RGB").resize((e.width * 2, e.height * 2), Image.NEAREST).save(str(path).replace(".png", "_emit.png"))
    for p in TMP.glob("*.exr"):
        p.unlink()


if __name__ == "__main__":
    if len(sys.argv) >= 4 and sys.argv[1] == "--preview":
        preview(sys.argv[2], sys.argv[3])
    else:
        for nm in sys.argv[1:] or list(V2):
            render(nm)
