#!/usr/bin/env python3
"""检视模型自检（规格见 docs/DESIGN.md 第 15 节“检视模型”）。只用标准库 + numpy，不需要 Blender。

用法（仓库根目录）：
  art/.venv/bin/python art/post/check_models.py                        # 检查 assets/models/inspect/ 下全部 glb
  art/.venv/bin/python art/post/check_models.py --expect sword,wind_wheel   # 另外报出缺了哪几件
  art/.venv/bin/python art/post/check_models.py path/to/a.glb --json   # 只查一个文件，输出 JSON

检查：
  - 文件：glb 2.0，≤ 2 MB；目录合计 ≤ 60 MB（按 39 件的总预算）；不用 Draco / meshopt / KTX2；
  - 命名：根节点名 = 文件名（id），每个节点、网格、材质名都以 id 开头；
  - 朝向：根节点 extras.inspect 写明 up = +Y、front = +Z，根节点没有变换；
  - 包围球：主体（不含描边）中心在原点（≤ 0.02），离中心最远的顶点 = 1（±0.02）；描边 ≤ 1.06；
  - 面数：主体（按实例展开，实际画多少算多少）≤ 5 万三角形，描边另算；
  - 描边：至少一个节点名以 _outline 结尾，它的网格、材质名也以 _outline 结尾，外壳的法线朝里（有符号体积为负）；
    不是描边的节点不能用描边材质；
  - 贴图：PNG，宽高 ≤ 2048 且是 2 的幂；
  - 材质：自发光亮度大于 1 时要用 KHR_materials_emissive_strength；透明的用 BLEND；
  - 动画：有的话只有一条，叫 idle，每个通道首尾的值相同（四元数允许整体取反）。
"""

from __future__ import annotations

import argparse
import json
import math
import struct
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]
MODEL_DIR = REPO / "assets" / "models" / "inspect"

MAX_FILE = 2 * 1024 * 1024
MAX_TOTAL = 60 * 1024 * 1024
MAX_TRIS = 50_000
MAX_TEX = 2048
RADIUS_TOL = 0.02
CENTER_TOL = 0.02
OUTLINE_MAX_R = 1.06
BANNED_EXT = ("KHR_draco_mesh_compression", "EXT_meshopt_compression", "KHR_meshopt_compression", "KHR_texture_basisu")

COMP = {5120: np.int8, 5121: np.uint8, 5122: np.int16, 5123: np.uint16, 5125: np.uint32, 5126: np.float32}
NCOMP = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}


# ====================================================================== glb 读写


def read_glb(path):
    """读 glb → (json dict, BIN bytes)。"""
    data = Path(path).read_bytes()
    magic, ver, length = struct.unpack("<4sII", data[:12])
    if magic != b"glTF" or ver != 2:
        raise ValueError(f"{path}: 不是 glb 2.0")
    off, js, bins = 12, None, b""
    while off < length:
        clen, ctype = struct.unpack("<II", data[off:off + 8])
        chunk = data[off + 8:off + 8 + clen]
        if ctype == 0x4E4F534A:
            js = json.loads(chunk.decode("utf-8"))
        elif ctype == 0x004E4942:
            bins = chunk
        off += 8 + clen
    if js is None:
        raise ValueError(f"{path}: 没有 JSON 块")
    return js, bins


def write_glb(path, js, view_datas):
    """按 bufferView 的顺序重新排 BIN（4 字节对齐），改好 byteOffset / byteLength，写 glb。"""
    out = bytearray()
    for v, d in zip(js["bufferViews"], view_datas):
        while len(out) % 4:
            out += b"\0"
        v["byteOffset"] = len(out)
        v["byteLength"] = len(d)
        v["buffer"] = 0
        out += d
    while len(out) % 4:
        out += b"\0"
    js["buffers"] = [{"byteLength": len(out)}]
    jb = json.dumps(js, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    while len(jb) % 4:
        jb += b" "
    total = 12 + 8 + len(jb) + 8 + len(out)
    with open(path, "wb") as f:
        f.write(struct.pack("<4sII", b"glTF", 2, total))
        f.write(struct.pack("<II", len(jb), 0x4E4F534A))
        f.write(jb)
        f.write(struct.pack("<II", len(out), 0x004E4942))
        f.write(out)


def accessor(js, bins, i):
    a = js["accessors"][i]
    v = js["bufferViews"][a["bufferView"]]
    dt = COMP[a["componentType"]]
    n = NCOMP[a["type"]]
    off = v.get("byteOffset", 0) + a.get("byteOffset", 0)
    stride = v.get("byteStride", 0)
    item = np.dtype(dt).itemsize * n
    if stride and stride != item:
        raw = np.frombuffer(bins, np.uint8, count=stride * a["count"], offset=off).reshape(a["count"], stride)[:, :item]
        arr = raw.copy().view(dt).reshape(a["count"], n)
    else:
        arr = np.frombuffer(bins, dt, count=a["count"] * n, offset=off).reshape(a["count"], n)
    return arr.astype(np.float64) if dt == np.float32 else arr


def png_size(b: bytes):
    if b[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    w, h = struct.unpack(">II", b[16:24])
    return int(w), int(h)


def node_matrix(n):
    if "matrix" in n:
        return np.array(n["matrix"], np.float64).reshape(4, 4).T
    t = np.array(n.get("translation", [0, 0, 0]), np.float64)
    q = np.array(n.get("rotation", [0, 0, 0, 1]), np.float64)
    s = np.array(n.get("scale", [1, 1, 1]), np.float64)
    x, y, z, w = q
    R = np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                  [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                  [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])
    M = np.eye(4)
    M[:3, :3] = R * s[None, :]
    M[:3, 3] = t
    return M


def is_identity(n):
    return np.allclose(node_matrix(n), np.eye(4), atol=1e-6)


# ====================================================================== 检查


def check_file(path: Path) -> dict:
    """查一个 glb，返回 {id, errors, warnings, stats}。"""
    mid = path.stem
    errs, warns = [], []
    stats = {"file_bytes": path.stat().st_size}
    try:
        js, bins = read_glb(path)
    except Exception as e:  # noqa: BLE001
        return {"id": mid, "errors": [f"读不了：{e}"], "warnings": [], "stats": stats}
    if stats["file_bytes"] > MAX_FILE:
        errs.append(f"体积 {stats['file_bytes'] / 1e6:.2f} MB，超过 2 MB")
    used = set(js.get("extensionsUsed", [])) | set(js.get("extensionsRequired", []))
    for e in BANNED_EXT:
        if e in used:
            errs.append(f"用了 {e}（Bevy 不支持）")
    nodes = js.get("nodes", [])
    meshes = js.get("meshes", [])
    mats = js.get("materials", [])
    scene = js.get("scenes", [{}])[js.get("scene", 0)]
    roots = scene.get("nodes", [])
    # ---- 根节点、命名、朝向
    if len(roots) != 1:
        errs.append(f"场景里应当只有一个根节点，现在 {len(roots)} 个")
    root = nodes[roots[0]] if roots else {}
    if root.get("name") != mid:
        errs.append(f"根节点名 {root.get('name')!r} 不等于 id {mid!r}")
    if root and not is_identity(root):
        errs.append("根节点带了变换（应当是单位变换）")
    ex = (root.get("extras") or {}).get("inspect", {})
    if ex.get("up") != "+Y" or ex.get("front") != "+Z":
        errs.append("根节点 extras.inspect 没写 up = +Y、front = +Z")
    for kind, lst in (("节点", nodes), ("网格", meshes), ("材质", mats)):
        for it in lst:
            nm = it.get("name", "")
            if not nm.startswith(mid):
                errs.append(f"{kind}名 {nm!r} 不以 {mid} 开头")
    # ---- 遍历节点（世界矩阵）
    world = {}

    def walk(i, M):
        Mw = M @ node_matrix(nodes[i])
        world[i] = Mw
        for c in nodes[i].get("children", []):
            walk(c, Mw)

    for r in roots:
        walk(r, np.eye(4))
    outline_mats = {i for i, m in enumerate(mats) if m.get("name", "").endswith("_outline")}
    body_pts, out_pts = [], []
    tris_body = tris_out = 0
    out_nodes = []
    vol_bad = []
    for i, M in world.items():
        n = nodes[i]
        if "mesh" not in n:
            continue
        me = meshes[n["mesh"]]
        is_out = n.get("name", "").endswith("_outline")
        if is_out:
            out_nodes.append(n["name"])
            if not me.get("name", "").endswith("_outline"):
                errs.append(f"描边节点 {n['name']} 的网格名 {me.get('name')!r} 不以 _outline 结尾")
        vol = 0.0
        for p in me["primitives"]:
            pos = accessor(js, bins, p["attributes"]["POSITION"])
            P = pos @ M[:3, :3].T + M[:3, 3]
            if "indices" in p:
                idx = accessor(js, bins, p["indices"]).reshape(-1, 3).astype(np.int64)
            else:
                idx = np.arange(len(pos)).reshape(-1, 3)
            nt = len(idx)
            mi = p.get("material")
            if is_out:
                tris_out += nt
                out_pts.append(P)
                if mi is None or mi not in outline_mats:
                    errs.append(f"描边节点 {n['name']} 的材质名不以 _outline 结尾")
            else:
                tris_body += nt
                body_pts.append(P)
                if mi is not None and mi in outline_mats:
                    errs.append(f"节点 {n['name']} 不是描边，却用了描边材质")
            a, b, c = P[idx[:, 0]], P[idx[:, 1]], P[idx[:, 2]]
            vol += float(np.einsum("ij,ij->i", a, np.cross(b, c)).sum() / 6.0)
        if is_out and vol >= 0:
            vol_bad.append(n["name"])
    stats.update(tris=tris_body, outline_tris=tris_out, outline_nodes=out_nodes)
    if not out_nodes:
        errs.append("没有描边外壳（名字以 _outline 结尾的节点）")
    for nm in vol_bad:
        errs.append(f"描边 {nm} 的法线没有朝里（有符号体积不为负）")
    if tris_body > MAX_TRIS:
        errs.append(f"主体 {tris_body} 三角形，超过 {MAX_TRIS}")
    if body_pts:
        P = np.vstack(body_pts)
        c = (P.min(0) + P.max(0)) / 2
        r = float(np.linalg.norm(P, axis=1).max())
        stats.update(center=[round(float(v), 4) for v in c], radius=round(r, 4))
        if np.linalg.norm(c) > CENTER_TOL:
            errs.append(f"几何中心 {np.round(c, 3).tolist()} 不在原点")
        if abs(r - 1.0) > RADIUS_TOL:
            errs.append(f"包围球半径 {r:.3f}，应当是 1")
    else:
        errs.append("没有主体网格")
    if out_pts:
        ro = float(np.linalg.norm(np.vstack(out_pts), axis=1).max())
        stats["outline_radius"] = round(ro, 4)
        if ro > OUTLINE_MAX_R:
            errs.append(f"描边外壳半径 {ro:.3f}，超过 {OUTLINE_MAX_R}")
    # ---- 贴图
    texs = []
    for im in js.get("images", []):
        if "bufferView" not in im:
            errs.append(f"贴图 {im.get('name')} 没有内嵌")
            continue
        v = js["bufferViews"][im["bufferView"]]
        b = bins[v.get("byteOffset", 0):v.get("byteOffset", 0) + v["byteLength"]]
        sz = png_size(b)
        if sz is None or im.get("mimeType") != "image/png":
            errs.append(f"贴图 {im.get('name')} 不是 PNG")
            continue
        texs.append({"name": im.get("name"), "size": list(sz), "bytes": len(b)})
        w, h = sz
        if max(w, h) > MAX_TEX:
            errs.append(f"贴图 {im.get('name')} {w}×{h}，超过 {MAX_TEX}")
        if w & (w - 1) or h & (h - 1):
            errs.append(f"贴图 {im.get('name')} {w}×{h} 不是 2 的幂")
    stats["textures"] = texs
    # ---- 材质
    for m in mats:
        ef = m.get("emissiveFactor", [0, 0, 0])
        es = m.get("extensions", {}).get("KHR_materials_emissive_strength", {}).get("emissiveStrength", 1.0)
        if max(ef) > 1.0 + 1e-6:
            errs.append(f"材质 {m.get('name')} 的 emissiveFactor 超过 1（应当用 KHR_materials_emissive_strength）")
        if m.get("name", "").endswith("_outline") and m.get("alphaMode", "OPAQUE") != "OPAQUE":
            warns.append(f"描边材质 {m.get('name')} 不是不透明")
        pbr = m.get("pbrMetallicRoughness", {})
        if pbr.get("baseColorFactor", [1, 1, 1, 1])[3] < 1.0 and m.get("alphaMode", "OPAQUE") == "OPAQUE":
            warns.append(f"材质 {m.get('name')} 带透明度但 alphaMode 是 OPAQUE")
        if max(ef) > 0 and es > 1.0 and "KHR_materials_emissive_strength" not in used:
            errs.append("用了自发光亮度但 extensionsUsed 里没有 KHR_materials_emissive_strength")
    stats["materials"] = [{"name": m.get("name"), "alpha": m.get("alphaMode", "OPAQUE"),
                           "emissive_strength": m.get("extensions", {}).get("KHR_materials_emissive_strength", {})
                           .get("emissiveStrength", 1.0 if max(m.get("emissiveFactor", [0, 0, 0])) > 0 else 0.0)}
                          for m in mats]
    # ---- 动画
    anims = js.get("animations", [])
    stats["animations"] = [a.get("name") for a in anims]
    if anims:
        if len(anims) != 1 or anims[0].get("name") != "idle":
            errs.append(f"动画应当只有一条 idle，现在是 {[a.get('name') for a in anims]}")
        for a in anims:
            for ch in a["channels"]:
                s = a["samplers"][ch["sampler"]]
                t = accessor(js, bins, s["input"]).ravel()
                v = accessor(js, bins, s["output"])
                path_ = ch["target"]["path"]
                if path_ == "weights":
                    v = v.reshape(len(t), -1)
                first, last = v[0], v[-1]
                ok = np.allclose(first, last, atol=1e-3)
                if path_ == "rotation" and not ok:
                    ok = np.allclose(first, -last, atol=1e-3)
                if not ok:
                    nm = nodes[ch["target"]["node"]].get("name")
                    errs.append(f"idle 的 {nm}.{path_} 首尾接不上")
                stats.setdefault("idle_seconds", round(float(t[-1] - t[0]), 3))
    return {"id": mid, "errors": errs, "warnings": warns, "stats": stats}


def check_all(paths, expect=None):
    results = [check_file(p) for p in paths]
    total = sum(p.stat().st_size for p in paths)
    summary = {"files": len(paths), "total_bytes": total, "errors": []}
    if total > MAX_TOTAL:
        summary["errors"].append(f"合计 {total / 1e6:.1f} MB，超过 60 MB")
    if expect:
        have = {p.stem for p in paths}
        missing = [e for e in expect if e not in have]
        summary["missing"] = missing
        for e in missing:
            summary["errors"].append(f"缺 {e}.glb")
    return results, summary


def fmt(res):
    s = res["stats"]
    lines = [f"{res['id']}: {'通过' if not res['errors'] else '不通过'}  "
             f"{s.get('file_bytes', 0) / 1e6:.2f} MB  主体 {s.get('tris', '?')} 三角形，描边 {s.get('outline_tris', '?')}  "
             f"半径 {s.get('radius', '?')}  动画 {s.get('animations')}"]
    for t in s.get("textures", []):
        lines.append(f"    贴图 {t['name']}: {t['size'][0]}×{t['size'][1]}，{t['bytes'] / 1e3:.0f} KB")
    for e in res["errors"]:
        lines.append(f"  ✗ {e}")
    for w in res["warnings"]:
        lines.append(f"  ! {w}")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="检视模型自检")
    ap.add_argument("paths", nargs="*", help="glb 文件或目录（默认 assets/models/inspect/）")
    ap.add_argument("--expect", default="", help="期望有的 id，逗号分隔；缺的会报出来")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    targets = [Path(p) for p in a.paths] or [MODEL_DIR]
    files = []
    for t in targets:
        files += sorted(t.glob("*.glb")) if t.is_dir() else [t]
    expect = [e.strip() for e in a.expect.split(",") if e.strip()]
    results, summary = check_all(files, expect)
    bad = any(r["errors"] for r in results) or bool(summary["errors"])
    if a.json:
        print(json.dumps({"results": results, "summary": summary}, ensure_ascii=False, indent=1))
    else:
        for r in results:
            print(fmt(r))
        print(f"合计 {summary['files']} 件，{summary['total_bytes'] / 1e6:.2f} MB（预算 60 MB）")
        for e in summary["errors"]:
            print(f"  ✗ {e}")
        print("全部通过" if not bad else "有问题")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
