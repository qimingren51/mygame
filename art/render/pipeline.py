"""出图流水线的公共部分：渲一个素材的全部帧 → 后期 → 按输出约定写文件夹（PNG + meta.json + 挂点）。

style_frame.py（风格样张）和 produce.py（正式出图）都用这里的 render_asset()。

分层出图（variants）：同一个姿态在一次 Blender 会话里连渲几遍，每遍用一个 scope（bstyle.render_scope：
隐藏 / Holdout 遮挡 / 只画某些物体的墨线），写进各自的文件夹。主角就是这样拆成“底图 hero/”和
“每盏灯一份叠层 lantern_<灯>/”：叠层和底图同画布、同锚点、同帧名，纸纹也用底图的（grain），叠上去严丝合缝。
"""

from __future__ import annotations

import contextlib
import copy
import json
import sys
import time
from pathlib import Path

ART = Path(__file__).resolve().parents[1]
for p in (ART, ART / "models", ART / "post"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import numpy as np  # noqa: E402

from style import bstyle as B  # noqa: E402
from style import style as S  # noqa: E402
import postprocess as P  # noqa: E402


class _Folder:
    """一个输出文件夹：开工前清掉要重渲的旧图，渲完按（可合并的）meta 写出。"""

    def __init__(self, out_root: Path, name: str, merge: bool, redo: set):
        self.name = name
        self.out = Path(out_root) / name
        self.out.mkdir(parents=True, exist_ok=True)
        self.old_meta = None
        self.redo = redo
        if merge and (self.out / "meta.json").exists():
            # 只重渲 jobs 里的动画：删掉这些动画的旧图，meta 里其它动画和挂点保留
            self.old_meta = json.loads((self.out / "meta.json").read_text(encoding="utf-8"))
            for old in self.out.glob("*.png"):
                if old.name.split("_")[0] in redo:
                    old.unlink()
        else:
            for old in list(self.out.glob("*.png")) + list(self.out.glob("meta.json")):
                old.unlink()

    def write_meta(self, meta: dict) -> None:
        if self.old_meta is not None:
            old = self.old_meta
            merged = dict(old)
            merged.update({k: v for k, v in meta.items() if k not in ("anims", "sockets")})
            merged["anims"] = {**{k: v for k, v in old.get("anims", {}).items() if k not in self.redo}, **meta["anims"]}
            socks = {s_: dict(v) for s_, v in old.get("sockets", {}).items()}
            for s_, by_anim in meta.get("sockets", {}).items():
                socks.setdefault(s_, {}).update(by_anim)
            merged["sockets"] = socks
            meta = merged
        (self.out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")


def render_asset(name: str, frame_px: int, build, jobs, out_root: Path, meta_extra: dict | None = None,
                 pose=None, sockets_wanted=(), flash: bool = False, anchor=None, tmp_dir: Path | None = None,
                 timings: dict | None = None, merge: bool = False, scope=None, variants=(), grain: str | None = None,
                 palette_extra=()) -> Path:
    """jobs: [(动画, 朝向, 姿态帧号, 该动画总帧数)]，按顺序渲染。
    文件帧号 = 该动画该朝向里第几张（通常与姿态帧号相同）。
    写出 <out_root>/<name>/：<动画>_<朝向>_<NN>.png、_emit.png（有发光部件或 layers 里声明时）、
    _flash.png（flash=True）、meta.json（含逐帧挂点）。返回文件夹路径。
    scope(parts) → 上下文管理器：渲这个素材时的临时场景状态（例如主角底图隐藏灯笼头）。
    variants：同一姿态再渲的几层，每项 {"name", "scope": f(parts)→上下文管理器, "meta_extra", "palette_extra"}；
      写到 <out_root>/<variant name>/，帧名、anims 与本素材相同，挂点不写（sockets 为空），总写 _emit。
    grain：纸纹偏移用哪个名字（默认 name；变体总用本素材的，叠在一起纸纹对得上）。
    palette_extra：调色板外的颜色（后期吸附用；也会写进 meta）。"""
    meta_extra = dict(meta_extra or {})
    anchor = tuple(anchor or S.ANCHOR)
    redo = {j[0] for j in jobs}
    grain = grain or name
    passes = [{"name": name, "scope": scope, "palette_extra": list(palette_extra),
               "emit_always": "emit" in meta_extra.get("layers", []), "flash": flash, "base": True}]
    for v in variants:
        passes.append({"name": v["name"], "scope": v.get("scope"), "palette_extra": list(v.get("palette_extra", ())),
                       "emit_always": True, "flash": False, "base": False, "meta_extra": dict(v.get("meta_extra", {}))})
    for ps in passes:
        ps["folder"] = _Folder(out_root, ps["name"], merge, redo)
        ps["pal"] = tuple(P.LIGHT_COLORS) + tuple(c for c in ps["palette_extra"] if c not in P.LIGHT_COLORS)
    tmp_dir = Path(tmp_dir or (Path(out_root) / "_tmp"))
    t0 = time.perf_counter()
    B.reset_scene()
    B.setup_render(frame_px)
    B.setup_camera(frame_px, anchor=anchor)
    B.verify_camera(frame_px, verbose=False)
    B.setup_freestyle()
    root, parts, sockets = build()
    t_build = time.perf_counter() - t0
    sock_out: dict = {s: {} for s in sockets_wanted}
    anims: dict = {}
    seen: dict = {}
    times = []
    with B.render_lock():
        for anim, d, i, n in jobs:
            k = seen[(anim, d)] = seen.get((anim, d), -1) + 1
            if isinstance(parts, dict):
                parts["dir"] = d  # 有的姿态函数按朝向微调（主角背面的灯杖）
            B.set_direction(root, d)
            if pose:
                pose(parts, anim, i, n)
            base = f"{anim}_{d}_{k:02d}"
            for ps in passes:
                ctx = ps["scope"](parts) if ps["scope"] else contextlib.nullcontext()
                with ctx:
                    L = B.render_layers(tmp_dir / f"{ps['name']}_{base}")
                tp = time.perf_counter()
                R = P.process_layers(L, ps["name"], extra_palette=ps["pal"], grain_name=grain)
                out = ps["folder"].out
                P.save_png(R["rgba"], out / f"{base}.png")
                if R["stats"]["emit_px"] > 0 or ps["emit_always"]:
                    P.save_png(R["emit"], out / f"{base}_emit.png")
                if ps["flash"]:
                    P.save_png(R["flash"], out / f"{base}_flash.png")
                times.append((L["time_s"], time.perf_counter() - tp))
            for s in sockets_wanted:
                x, y = B.project_point(sockets[s].matrix_world.translation, frame_px)
                sock_out[s].setdefault(anim, {}).setdefault(d, []).append([round(x, 2), round(y, 2)])
            a = anims.setdefault(anim, {"frames": 0, "fps": 8, "dirs": []})
            if d not in a["dirs"]:
                a["dirs"].append(d)
    for (anim, d), k in seen.items():
        anims[anim]["frames"] = k + 1
    for an, extra in meta_extra.pop("anim_extra", {}).items():
        if an in anims:  # 只重渲部分动画时，其它动画的设置沿用旧 meta
            anims[an].update(extra)
    head = {"size": [frame_px, frame_px], "anchor": list(anchor), "px_per_unit": S.PX_PER_UNIT}
    for ps in passes:
        if ps["base"]:
            meta = {"name": name, **head, "anims": anims, "sockets": sock_out}
            meta.update(meta_extra)
            if ps["palette_extra"]:
                meta["palette_extra"] = ps["palette_extra"]
        else:
            meta = {"name": ps["name"], **head, "anims": copy.deepcopy(anims), "sockets": {}}
            meta.update(ps["meta_extra"])
        ps["folder"].write_meta(meta)
    r = np.array(times)
    info = {"frames": len(jobs), "passes": len(passes), "render_px": frame_px * S.RENDER_SCALE,
            "faces": B.face_count(root), "build_s": round(t_build, 3),
            "render_s_mean": round(float(r[:, 0].mean()), 3), "render_s_max": round(float(r[:, 0].max()), 3),
            "post_s_mean": round(float(r[:, 1].mean()), 3), "total_s": round(time.perf_counter() - t0, 2)}
    if timings is not None:
        timings[name] = info
    print(f"[{name}] {len(jobs)} 个姿态 × {len(passes)} 层，渲染 {info['render_s_mean']:.2f}s/张（{info['render_px']}²，"
          f"{info['faces']} 面），后期 {info['post_s_mean']:.2f}s/张，共 {info['total_s']:.1f}s")
    for p in tmp_dir.glob("*.exr"):
        p.unlink()
    return passes[0]["folder"].out
