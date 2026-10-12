"""出图流水线的公共部分：渲一个素材的全部帧 → 后期 → 按输出约定写文件夹（PNG + meta.json + 挂点）。

style_frame.py（风格样张）和 produce.py（正式出图）都用这里的 render_asset()。
"""

from __future__ import annotations

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


def render_asset(name: str, frame_px: int, build, jobs, out_root: Path, meta_extra: dict | None = None,
                 pose=None, sockets_wanted=(), flash: bool = False, anchor=None, tmp_dir: Path | None = None,
                 timings: dict | None = None, merge: bool = False) -> Path:
    """jobs: [(动画, 朝向, 姿态帧号, 该动画总帧数)]，按顺序渲染。
    文件帧号 = 该动画该朝向里第几张（通常与姿态帧号相同）。
    写出 <out_root>/<name>/：<动画>_<朝向>_<NN>.png、_emit.png（有发光部件或 layers 里声明时）、
    _flash.png（flash=True）、meta.json（含逐帧挂点）。返回文件夹路径。"""
    meta_extra = dict(meta_extra or {})
    anchor = tuple(anchor or S.ANCHOR)
    out = Path(out_root) / name
    out.mkdir(parents=True, exist_ok=True)
    old_meta = None
    redo = {j[0] for j in jobs}
    if merge and (out / "meta.json").exists():
        # 只重渲 jobs 里的动画：删掉这些动画的旧图，meta 里其它动画和挂点保留
        old_meta = json.loads((out / "meta.json").read_text(encoding="utf-8"))
        for old in out.glob("*.png"):
            if old.name.split("_")[0] in redo:
                old.unlink()
    else:
        for old in list(out.glob("*.png")) + list(out.glob("meta.json")):
            old.unlink()
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
            L = B.render_layers(tmp_dir / f"{name}_{anim}_{d}_{k:02d}")
            tp = time.perf_counter()
            R = P.process_layers(L, name)
            base = f"{anim}_{d}_{k:02d}"
            P.save_png(R["rgba"], out / f"{base}.png")
            if R["stats"]["emit_px"] > 0 or "emit" in meta_extra.get("layers", []):
                P.save_png(R["emit"], out / f"{base}_emit.png")
            if flash:
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
    meta = {"name": name, "size": [frame_px, frame_px], "anchor": list(anchor), "px_per_unit": S.PX_PER_UNIT,
            "anims": anims, "sockets": sock_out}
    meta.update(meta_extra)
    if old_meta is not None:
        merged = dict(old_meta)
        merged.update({k: v for k, v in meta.items() if k not in ("anims", "sockets")})
        merged["anims"] = {**{k: v for k, v in old_meta.get("anims", {}).items() if k not in redo}, **anims}
        socks = {s_: dict(v) for s_, v in old_meta.get("sockets", {}).items()}
        for s_, by_anim in sock_out.items():
            socks.setdefault(s_, {}).update(by_anim)
        merged["sockets"] = socks
        meta = merged
    (out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    r = np.array(times)
    info = {"frames": len(times), "render_px": frame_px * S.RENDER_SCALE, "faces": B.face_count(root),
            "build_s": round(t_build, 3),
            "render_s_mean": round(float(r[:, 0].mean()), 3), "render_s_max": round(float(r[:, 0].max()), 3),
            "post_s_mean": round(float(r[:, 1].mean()), 3), "total_s": round(time.perf_counter() - t0, 2)}
    if timings is not None:
        timings[name] = info
    print(f"[{name}] {len(times)} 帧，渲染 {info['render_s_mean']:.2f}s/帧（{info['render_px']}²，{info['faces']} 面），"
          f"后期 {info['post_s_mean']:.2f}s/帧，共 {info['total_s']:.1f}s")
    for p in tmp_dir.glob("*.exr"):
        p.unlink()
    return out
