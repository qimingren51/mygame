#!/usr/bin/env python3
"""check_models.py 的自检：纯 assert，不依赖 pytest，也不需要 Blender（在内存里拼小 glb）。

先拼一件合格的样例（八面体主体 + 翻面的描边外壳 + 一张 PNG + 一条首尾相接的 idle），确认它通过；
再逐条弄坏一处（面数、半径、描边、法线朝向、贴图、命名、动画、体积、扩展、自发光、缺件），确认每条都报得出来。
assets/models/inspect/ 下有正式的 glb 时，也全部过一遍。

用法（在仓库根目录下）：
  art/.venv/bin/python art/post/test_check_models.py
"""

from __future__ import annotations

import io
import sys
import tempfile
import traceback
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import check_models as CM  # noqa: E402

TMP = Path(tempfile.mkdtemp(prefix="check_models_"))

OCTA_V = np.array([(1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1)], np.float32)
OCTA_F = np.array([(0, 2, 4), (2, 1, 4), (1, 3, 4), (3, 0, 4), (2, 0, 5), (1, 2, 5), (3, 1, 5), (0, 3, 5)], np.uint16)


def png_bytes(w, h):
    b = io.BytesIO()
    Image.new("RGB", (w, h), (120, 90, 60)).save(b, "PNG")
    return b.getvalue()


class Glb:
    """拼一个最小的 glb：往 views 里加数据，accessors 指过去。"""

    def __init__(self):
        self.js = {"asset": {"version": "2.0"}, "scene": 0, "scenes": [{"nodes": []}], "nodes": [], "meshes": [],
                   "materials": [], "accessors": [], "bufferViews": [], "buffers": []}
        self.datas = []

    def view(self, data: bytes):
        self.js["bufferViews"].append({"buffer": 0, "byteLength": len(data)})
        self.datas.append(data)
        return len(self.datas) - 1

    def acc(self, arr, ctype, typ):
        arr = np.ascontiguousarray(arr)
        v = self.view(arr.tobytes())
        a = {"bufferView": v, "componentType": ctype, "count": int(arr.shape[0]), "type": typ}
        if typ == "VEC3" and ctype == 5126:
            a["min"] = arr.min(0).tolist()
            a["max"] = arr.max(0).tolist()
        self.js["accessors"].append(a)
        return len(self.js["accessors"]) - 1

    def mesh(self, name, verts, faces, material):
        pos = self.acc(verts.astype(np.float32), 5126, "VEC3")
        idx = self.acc(faces.astype(np.uint16).reshape(-1, 1), 5123, "SCALAR")
        self.js["meshes"].append({"name": name, "primitives": [{"attributes": {"POSITION": pos}, "indices": idx,
                                                                 "material": material}]})
        return len(self.js["meshes"]) - 1

    def node(self, d):
        self.js["nodes"].append(d)
        return len(self.js["nodes"]) - 1

    def write(self, path):
        CM.write_glb(path, self.js, self.datas)
        return path


def good(mid="good", *, scale=1.0, outline_flip=True, tex=(64, 64), with_outline=True, anim_loop=True, extra_tris=0):
    """合格的样例；参数用来弄坏某一处。"""
    g = Glb()
    js = g.js
    js["materials"] = [{"name": f"{mid}_body", "pbrMetallicRoughness": {"baseColorTexture": {"index": 0}}},
                       {"name": f"{mid}_outline", "extensions": {"KHR_materials_unlit": {}}}]
    js["extensionsUsed"] = ["KHR_materials_unlit"]
    js["images"] = [{"name": f"{mid}_base", "mimeType": "image/png", "bufferView": g.view(png_bytes(*tex))}]
    js["textures"] = [{"source": 0}]
    faces = OCTA_F
    verts = OCTA_V * scale
    if extra_tris:
        faces = np.vstack([faces, np.tile(OCTA_F[:1], (extra_tris, 1))])
    m_body = g.mesh(f"{mid}_body", verts, faces, 0)
    children = [g.node({"name": f"{mid}_body", "mesh": m_body})]
    if with_outline:
        of = OCTA_F[:, ::-1] if outline_flip else OCTA_F
        m_out = g.mesh(f"{mid}_body_outline", OCTA_V * scale * 1.01, of, 1)
        children.append(g.node({"name": f"{mid}_body_outline", "mesh": m_out}))
    spin = children[0]
    root = g.node({"name": mid, "children": children, "extras": {"inspect": {"id": mid, "up": "+Y", "front": "+Z"}}})
    js["scenes"][0]["nodes"] = [root]
    t = np.linspace(0, 2, 9, dtype=np.float32).reshape(-1, 1)
    ang = np.linspace(0, 2 * np.pi if anim_loop else np.pi, 9)
    q = np.stack([np.zeros(9), np.sin(ang / 2), np.zeros(9), np.cos(ang / 2)], -1).astype(np.float32)
    ti = g.acc(t, 5126, "SCALAR")
    js["accessors"][ti]["min"], js["accessors"][ti]["max"] = [0.0], [2.0]
    qi = g.acc(q, 5126, "VEC4")
    js["animations"] = [{"name": "idle", "samplers": [{"input": ti, "output": qi, "interpolation": "LINEAR"}],
                         "channels": [{"sampler": 0, "target": {"node": spin, "path": "rotation"}}]}]
    return g


def at(case, mid="good"):
    """每个用例一个目录，文件名 = id（检查按文件名认 id）。"""
    d = TMP / case
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{mid}.glb"


def errs_of(g, case):
    return CM.check_file(g.write(at(case)))["errors"]


def has(errs, word):
    return any(word in e for e in errs)


# ====================================================================== 测试


def test_roundtrip():
    g = good()
    p = g.write(at("roundtrip"))
    js, bins = CM.read_glb(p)
    assert js["nodes"][-1]["name"] == "good" and len(bins) % 4 == 0
    assert CM.png_size(bins[js["bufferViews"][0]["byteOffset"]:][:64]) == (64, 64)


def test_good_passes():
    res = CM.check_file(good().write(at("good")))
    assert not res["errors"], res["errors"]
    s = res["stats"]
    assert s["tris"] == 8 and s["outline_tris"] == 8, s
    assert abs(s["radius"] - 1.0) < 1e-6 and s["animations"] == ["idle"], s


def test_too_many_tris():
    e = errs_of(good(extra_tris=CM.MAX_TRIS), "tris")
    assert has(e, "三角形"), e


def test_outline_not_counted_in_budget():
    g = good()
    js = g.js
    # 描边多出很多面也不算进主体的 5 万
    out_mesh = js["meshes"][1]
    big = np.tile(OCTA_F[:, ::-1], (CM.MAX_TRIS // 8 + 10, 1))
    out_mesh["primitives"][0]["indices"] = g.acc(big.reshape(-1, 1), 5123, "SCALAR")
    e = errs_of(g, "outline_big")
    assert not has(e, "主体"), e


def test_radius():
    e = errs_of(good(scale=1.5), "radius")
    assert has(e, "半径"), e


def test_center():
    g = good()
    g.js["nodes"][0]["translation"] = [0.3, 0.0, 0.0]
    e = errs_of(g, "center")
    assert has(e, "中心") or has(e, "半径"), e


def test_missing_outline():
    e = errs_of(good(with_outline=False), "no_outline")
    assert has(e, "描边"), e


def test_outline_normals_outward():
    e = errs_of(good(outline_flip=False), "outline_out")
    assert has(e, "法线"), e


def test_outline_material_name():
    g = good()
    g.js["materials"][1]["name"] = "good_black"
    e = errs_of(g, "outline_mat")
    assert has(e, "_outline"), e


def test_texture_rules():
    assert has(errs_of(good(tex=(100, 64)), "npot"), "2 的幂")
    assert has(errs_of(good(tex=(4096, 16)), "big_tex"), "超过")


def test_naming():
    g = good()
    g.js["materials"][0]["name"] = "Material.001"
    e = errs_of(g, "naming")
    assert has(e, "不以 good 开头"), e
    g = good()
    g.js["nodes"][-1]["name"] = "Scene"
    assert has(errs_of(g, "rootname"), "根节点名")


def test_orientation_extras():
    g = good()
    g.js["nodes"][-1]["extras"] = {}
    assert has(errs_of(g, "noextras"), "+Y")
    g = good()
    g.js["nodes"][-1]["rotation"] = [0.7071, 0, 0, 0.7071]
    assert has(errs_of(g, "rootrot"), "变换")


def test_animation_rules():
    assert has(errs_of(good(anim_loop=False), "noloop"), "首尾")
    g = good()
    g.js["animations"][0]["name"] = "Action"
    assert has(errs_of(g, "animname"), "idle")


def test_file_size():
    g = good()
    g.view(b"\0" * (CM.MAX_FILE + 1024))
    assert has(errs_of(g, "huge"), "2 MB")


def test_banned_extensions():
    g = good()
    g.js["extensionsUsed"] = ["KHR_draco_mesh_compression"]
    assert has(errs_of(g, "draco"), "Draco") or has(errs_of(g, "draco"), "draco")


def test_emissive_strength():
    g = good()
    g.js["materials"][0]["emissiveFactor"] = [3.0, 1.0, 1.0]
    assert has(errs_of(g, "emis"), "emissive")


def test_expect_reports_missing():
    p = good("sword").write(at("expect", "sword"))
    results, summary = CM.check_all([p], expect=["sword", "wind_wheel"])
    assert summary["missing"] == ["wind_wheel"], summary
    assert any("wind_wheel" in e for e in summary["errors"]), summary
    assert not results[0]["errors"], results[0]["errors"]


def test_cli_exit_codes():
    p = good().write(at("cli_ok"))
    assert CM.main([str(p)]) == 0
    bad = good(scale=2.0).write(at("cli_bad"))
    assert CM.main([str(bad)]) == 1
    assert CM.main([str(p.parent), "--expect", "good,nothing_here"]) == 1


def test_real_models():
    """仓库里已经有的正式检视模型都要过自检。"""
    files = sorted(CM.MODEL_DIR.glob("*.glb"))
    if not files:
        print("      （assets/models/inspect/ 还没有 glb，跳过）")
        return
    results, summary = CM.check_all(files)
    bad = {r["id"]: r["errors"] for r in results if r["errors"]}
    assert not bad, bad
    assert not summary["errors"], summary["errors"]


def main() -> int:
    tests = [(k, v) for k, v in globals().items() if k.startswith("test_") and callable(v)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"PASS  {name}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL  {name}: {e}")
        except Exception:  # noqa: BLE001
            failed += 1
            print(f"ERROR {name}")
            traceback.print_exc()
    print(f"\n{len(tests) - failed}/{len(tests)} 通过")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
