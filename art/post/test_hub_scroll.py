#!/usr/bin/env python3
"""hub_scroll.py（灯驿长卷）的自检：纯 assert，不依赖 pytest。只有桌面版（2 倍）。

产物缺失或比脚本旧时先重新生成（约 1.5 分钟）；--regen 强制重新生成；
确定性测试另画两遍到临时目录（并行，约 2 分钟），逐字节比对；--quick 跳过这一项。

用法（在仓库根目录下）：
  art/.venv/bin/python art/post/test_hub_scroll.py
"""

from __future__ import annotations

import json
import math
import re
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import hub_scroll as H  # noqa: E402

OUT = H.OUT
MAN = OUT / "hub.json"
REVIEWS = [H.REVIEW / f"hub_review_{k}.png" for k in ("states", "figures", "ui_720", "road", "road_ui_720")]
ASSETS = H.ROOT / "assets" / "atlas" / "screens" / "hub"  # 游戏里正在用的那一份
SAFE = (96, 128, 1728, 824)  # 16:10 与 21:9 铺满后都留得住的区域（x, y, w, h）
FOUR_THREE = (240, 1680)  # 4:3 铺满后剩下的 x 范围：四个人物要在里面
_cache: dict[str, object] = {}


def ensure_outputs(force: bool) -> None:
    srcs = [HERE / n for n in ("hub_scroll.py", "ink_figure.py", "title_screen.py", "scroll_qingqiu.py", "vfx_textures.py",
                                 "ui_fonts.py")]
    srcs += [H.ART / "style" / "style.py", H.META_RON]
    newest = max(p.stat().st_mtime for p in srcs)
    outs = [MAN, OUT / "hub.png"] + REVIEWS
    stale = [p for p in outs if not p.exists() or p.stat().st_mtime < newest]
    if force or stale:
        print("重新生成灯驿长卷……")
        H.main([])


def man() -> dict:
    if "man" not in _cache:
        _cache["man"] = json.loads(MAN.read_text(encoding="utf-8"))
    return _cache["man"]


def img(name: str, mode: str | None = None) -> np.ndarray:
    key = f"{name}:{mode}"
    if key not in _cache:
        im = Image.open(OUT / name)
        _cache[key] = np.asarray(im.convert(mode) if mode else im, np.float64) / 255.0
    return _cache[key]


def base() -> np.ndarray:
    return img("hub.png", "RGB")


def lum(a: np.ndarray) -> np.ndarray:
    return a @ np.array([0.299, 0.587, 0.114])


def layers():
    """所有叠层：(名字, 层信息)，层信息里有 file、rect、blend。"""
    m = man()
    for lid, e in m["lamps"].items():
        for part, v in e.items():
            yield f"心灯 {lid}.{part}", v
    for rid, e in m["dawn"].items():
        yield f"晨光 {rid}", {"file": e["file"], "rect": e["rect"], "blend": e.get("blend", "normal")}
        yield f"晨光 {rid}.mask", {"file": e["mask"], "rect": e["rect"], "blend": "mask"}
        yield f"晨光 {rid}.glow", e["glow"]
    for n, e in enumerate(m.get("road_lamps", [])):
        for part, v in e.items():
            yield f"路灯 {n}.{part}", v


def inside(r, box) -> bool:
    x, y, w, h = r
    bx, by, bw, bh = box
    return x >= bx and y >= by and x + w <= bx + bw and y + h <= by + bh


def blend(canvas: np.ndarray, layer: dict) -> None:
    """按游戏的规则叠一层：normal = 直通 alpha 覆盖；add = 画面 += RGB × alpha。"""
    x, y, w, h = layer["rect"]
    a = img(layer["file"], "RGBA")
    sub = canvas[y:y + h, x:x + w]
    if layer.get("blend", "normal") == "add":
        sub += a[..., :3] * a[..., 3:4]
    else:
        sub[:] = sub * (1 - a[..., 3:4]) + a[..., :3] * a[..., 3:4]


def composite(lamps: list[str], dawns: list[str], road: int = 0) -> np.ndarray:
    """游戏的合成顺序：灯身（心灯 + 前 road 盏路灯）→ 火苗 → 内圈 + 外圈（叠加）→ 晨光 → 晨光金线。"""
    m = man()
    out = base().copy()
    groups = [m["lamps"][lid] for lid in lamps] + m.get("road_lamps", [])[:road]
    for e in groups:
        blend(out, e["body"])
    for e in groups:
        blend(out, e["flame"])
    for e in groups:
        blend(out, e["core"])
        blend(out, e["glow"])
    out = np.clip(out, 0, 1)
    for rid in dawns:
        blend(out, {"file": m["dawn"][rid]["file"], "rect": m["dawn"][rid]["rect"]})
    for rid in dawns:
        blend(out, m["dawn"][rid]["glow"])
    return np.clip(out, 0, 1)


def rect_mask(rects) -> np.ndarray:
    m = np.zeros((H.H, H.W), bool)
    for (x, y, w, h) in rects:
        m[y:y + h, x:x + w] = True
    return m


# ============================================================== 清单与文件


def test_manifest_files_and_sizes():
    """hub.json 里的每个文件都在、尺寸等于 rect 的宽高、模式对；目录里没有清单之外的 PNG。"""
    m = man()
    assert m["size"] == [1920, 1080], f"size 应为 [1920, 1080]：{m['size']}"
    assert m["safe"] == list(SAFE), f"safe 应为 {list(SAFE)}：{m['safe']}"
    b = Image.open(OUT / "hub.png")
    assert b.size == (1920, 1080) and b.mode == "RGB", f"hub.png 应为 1920×1080 不透明 RGB（{b.size} {b.mode}）"
    used = {"hub.png"}
    for name, v in layers():
        p = OUT / v["file"]
        assert p.exists(), f"{name} 的 {v['file']} 不存在"
        used.add(v["file"])
        with Image.open(p) as im:
            want = "L" if v["blend"] == "mask" else "RGBA"
            assert im.mode == want, f"{v['file']} 应为 {want}，实际 {im.mode}"
            assert list(im.size) == v["rect"][2:], f"{v['file']} 尺寸 {im.size} 与 rect {v['rect']} 不一致"
        assert v["blend"] in ("normal", "add", "mask"), f"{name} 的 blend 不对：{v['blend']}"
    extra = {p.name for p in OUT.glob("*.png")} - used
    assert not extra, f"目录里有清单之外的文件：{sorted(extra)}"
    for lid, e in m["lamps"].items():
        assert e["body"]["blend"] == "normal" and e["flame"]["blend"] == "normal", f"{lid}：灯身、火苗应为普通混合"
        assert e["core"]["blend"] == "add" and e["glow"]["blend"] == "add", f"{lid}：内圈、外圈应为叠加"
    for rid, e in m["dawn"].items():
        assert e["glow"]["blend"] == "add", f"{rid}：晨光金线应为叠加"


def test_ids_match_content():
    """心灯与 meta.ron 的节点一一对应（按文件顺序，每盏四层），人物与 hub.ron 的顺序一致；画里的挂灯位置数等于节点数。"""
    m = man()
    nodes = re.findall(r'\(id: "([a-z0-9_]+)"', H.META_RON.read_text(encoding="utf-8"))
    assert list(m["lamps"]) == nodes, f"lamps {list(m['lamps'])} 应与 meta.ron {nodes} 一致"
    assert len(H.LAMP_SLOTS) == len(nodes), f"meta.ron 有 {len(nodes)} 个节点，画里有 {len(H.LAMP_SLOTS)} 个挂灯位置"
    for lid, e in m["lamps"].items():
        assert set(e) == {"body", "flame", "core", "glow"}, f"{lid} 应有 body、flame、core、glow 四层：{sorted(e)}"
    hub = re.findall(r'\(id: "([a-z0-9_]+)", name: "([^"]+)"', (H.ROOT / "assets" / "data" / "hub.ron").read_text(encoding="utf-8"))
    chars = [(c["id"], c["name"]) for c in m["characters"]]
    assert chars == hub, f"characters {chars} 应与 hub.ron {hub} 一致"
    assert list(m["dawn"]) == list(H.REGIONS), f"dawn 的地区 {list(m['dawn'])} 不对"


def test_rects_inside_image():
    """每一层、每个人物的点击区 / 名字 / 聚光中心、每个文字安全区都在 1920×1080 里。"""
    full = (0, 0, 1920, 1080)
    for name, v in layers():
        assert inside(v["rect"], full), f"{name} 的 rect {v['rect']} 超出画面"
    for c in man()["characters"]:
        assert inside(c["rect"], full), f"{c['id']} 的 rect 超出画面"
        for (x, y) in (c["label"], c["light"][:2]):
            assert 0 <= x < 1920 and 0 <= y < 1080, f"{c['id']} 的 label / light 超出画面"
    for r in man()["text_safe"]:
        assert inside(r, full), f"text_safe {r} 超出画面"


def test_safe_area():
    """心灯（四层）、人物（点击区、名字、聚光中心）、文字安全区都在 safe 里；四个人物在 4:3 的 x 240–1680 里。"""
    m = man()
    for lid, e in m["lamps"].items():
        for part, v in e.items():
            assert inside(v["rect"], SAFE), f"心灯 {lid}.{part} 的 rect {v['rect']} 不在 safe 里"
    x0, x1 = FOUR_THREE
    for c in m["characters"]:
        x, y, w, h = c["rect"]
        assert inside(c["rect"], SAFE), f"{c['id']} 的点击区不在 safe 里"
        for (px, py) in (c["label"], c["light"][:2]):
            assert inside((px, py, 0, 0), SAFE), f"{c['id']} 的 label / light 不在 safe 里"
        assert x >= x0 and x + w <= x1, f"{c['id']} 的点击区 x {x}–{x + w} 超出 4:3 的 {x0}–{x1}"
    for r in m["text_safe"]:
        assert inside(r, SAFE), f"text_safe {r} 不在 safe 里"
    for rid, e in m["dawn"].items():
        x, y, w, h = e["rect"]
        assert x >= SAFE[0] and x + w <= SAFE[0] + SAFE[2], f"晨光 {rid} 的 x 超出 safe"


# ============================================================== 心灯


def test_lamp_layers_stay_local():
    """每盏灯的四层叠上去，只改变它自己几个 rect 里的像素；每一层都确实改变了一些像素。"""
    m = man()
    b = base()
    for lid, e in m["lamps"].items():
        out = composite([lid], [])
        changed = np.abs(out - b).max(-1) > 1.5 / 255
        own = rect_mask([v["rect"] for v in e.values()])
        assert not (changed & ~own).any(), f"心灯 {lid} 改到了自己的 rect 以外（{(changed & ~own).sum()} 个像素）"
        for part, v in e.items():
            a = img(v["file"], "RGBA")[..., 3]
            assert (a > 0.1).sum() >= 20, f"心灯 {lid}.{part} 几乎是空的"
        # 灯身亮起来：灯身中心比底图亮得多、偏暖
        x, y, hy, kind = H.LAMP_SLOTS[list(m["lamps"]).index(lid)]
        c0 = b[int(y) - 3:int(y) + 4, int(x) - 3:int(x) + 4].reshape(-1, 3).mean(0)
        c1 = out[int(y) - 3:int(y) + 4, int(x) - 3:int(x) + 4].reshape(-1, 3).mean(0)
        assert lum(c1) > lum(c0) + 0.25 and c1[0] > c1[2] + 0.15, f"心灯 {lid} 点亮后不够亮 / 不够暖：{c0.round(2)} → {c1.round(2)}"
        # 亮起时游戏把叠加层放大到 1.4 倍：灯身不能整个冲成白的
        flash = base().copy()
        for k in ("body", "flame"):
            blend(flash, e[k])
        for k in ("core", "glow"):
            v = e[k]
            x0, y0, w0, h0 = v["rect"]
            a = img(v["file"], "RGBA")
            flash[y0:y0 + h0, x0:x0 + w0] += a[..., :3] * a[..., 3:4] * 1.4
        bx, by, bw, bh = e["body"]["rect"]
        inner = img(e["body"]["file"], "RGBA")[..., 3] > 0.5
        hot = np.clip(flash[by:by + bh, bx:bx + bw], 0, 1).min(-1) > 0.97
        assert (hot & inner).sum() < 0.5 * inner.sum(), f"心灯 {lid} 放大 1.4 倍时灯身大半冲白了（{(hot & inner).sum() / inner.sum():.0%}）"


def test_additive_layers():
    """叠加层（灯的内圈、外圈，晨光金线）：alpha 峰值 ≤ 0.75，四边裁到 0；颜色暖而不太饱和（R ≥ G ≥ B，不是纯白）。"""
    for name, v in layers():
        if v["blend"] != "add":
            continue
        a = img(v["file"], "RGBA")
        al = a[..., 3]
        assert al.max() <= 0.75 + 1e-9, f"{name} 的 alpha 峰值 {al.max():.3f} > 0.75"
        assert al.max() >= 0.3, f"{name} 太淡（峰值 {al.max():.3f}）"
        edge = np.concatenate([al[0], al[-1], al[:, 0], al[:, -1]])
        assert edge.max() <= 1.5 / 255, f"{name} 的裁边处 alpha 没有落到 0（{edge.max() * 255:.0f}/255）"
        rgb = (a[..., :3] * al[..., None]).sum((0, 1)) / max(al.sum(), 1e-9)
        assert rgb[0] >= rgb[1] >= rgb[2] and rgb[2] < 0.8 and rgb[2] > 0.3, f"{name} 的颜色不对：{rgb.round(3)}"


def test_flame_base():
    """火苗的 base（底部中点）在火苗的 rect 里、靠近底边，base 上方就是火苗。"""
    for lid, e in man()["lamps"].items():
        v = e["flame"]
        x, y, w, h = v["rect"]
        bx, by = v["base"]
        assert x <= bx <= x + w and y <= by <= y + h, f"心灯 {lid} 的火苗 base {v['base']} 不在 rect {v['rect']} 里"
        assert y + h - by <= 6, f"心灯 {lid} 的火苗 base 离 rect 底边太远（{y + h - by:.1f}）"
        a = img(v["file"], "RGBA")[..., 3]
        col = a[:, int(round(bx - x)) - 1:int(round(bx - x)) + 2]
        ys = np.nonzero(col.max(1) > 0.5)[0]
        assert ys.size and abs((ys.max() + y) - by) <= 5, f"心灯 {lid} 的火苗底部和 base 对不上"
        tip = ys.min() + y
        assert by - tip >= 12, f"心灯 {lid} 的火苗太矮（{by - tip:.0f}）"


# ============================================================== 晨光


def test_dawn_masks():
    """晨光的“先亮哪里”：单通道、与晨光图同尺寸，在有晨光的地方用满 0–255 的大部分；没有晨光的地方是白（最后）。"""
    m = man()
    for rid, e in m["dawn"].items():
        mk = Image.open(OUT / e["mask"])
        dw = Image.open(OUT / e["file"])
        assert mk.mode == "L", f"{e['mask']} 应为单通道 L：{mk.mode}"
        assert mk.size == dw.size, f"{e['mask']} {mk.size} 与 {e['file']} {dw.size} 尺寸不同"
        v = np.asarray(mk)
        a = np.asarray(dw)[..., 3]
        on = a > 0
        lo, hi = np.percentile(v[on], [2, 98])
        assert v[on].min() <= 5 and v[on].max() >= 250, f"{rid} 的 mask 没有用到两头（{v[on].min()}–{v[on].max()}）"
        assert hi - lo >= 160, f"{rid} 的 mask 范围太窄（2–98% 分位 {lo:.0f}–{hi:.0f}）"
        assert len(np.unique(v[on])) >= 200, f"{rid} 的 mask 灰阶太少（{len(np.unique(v[on]))}）"
        assert (v[~on] == 255).all(), f"{rid} 的 mask 在没有晨光的地方应为 255"
        # 山脊（金线最亮处）比远处的天、山脚先亮
        g = e["glow"]
        ga = img(g["file"], "RGBA")[..., 3]
        gx, gy = g["rect"][0] - e["rect"][0], g["rect"][1] - e["rect"][1]
        full = np.zeros(v.shape)
        ys, xs = np.nonzero(ga > 0.7 * ga.max())  # 金线最亮的三成：峰顶的山脊
        ys, xs = ys + gy, xs + gx
        ok = (ys >= 0) & (xs >= 0) & (ys < v.shape[0]) & (xs < v.shape[1])
        full[ys[ok], xs[ok]] = 1
        ridge_t = v[(full > 0) & on].mean()
        assert ridge_t < np.median(v[on]), f"{rid}：山脊应比别处先亮（山脊 {ridge_t:.0f}，中位 {np.median(v[on]):.0f}）"


def test_dawn_stays_on_its_mountain():
    """晨光（普通 + 金线）看得见的部分（alpha > 0.02）只在它那座山的窗口里、墙头以上，各地区之间不重叠，
    也不落在心灯、人物和文字安全区上。"""
    m = man()
    keep_off = rect_mask([c["rect"] for c in m["characters"]] + m["text_safe"])
    for e in m["lamps"].values():  # 灯身、火苗本身（不透明的部分）
        for k in ("body", "flame"):
            x, y, w, h = e[k]["rect"]
            keep_off[y:y + h, x:x + w] |= img(e[k]["file"], "RGBA")[..., 3] > 0.1
    seen = np.zeros((H.H, H.W), int)
    for rid, e in m["dawn"].items():
        lay, cx, hgt, wl, wr, sharp, half = H.REGIONS[rid]
        vis = np.zeros((H.H, H.W), bool)
        for v in (e, e["glow"]):
            x, y, w, h = v["rect"]
            vis[y:y + h, x:x + w] |= img(v["file"], "RGBA")[..., 3] > 0.02
        ys, xs = np.nonzero(vis)
        assert xs.min() >= cx - half - 8 and xs.max() <= cx + half + 8, f"{rid} 的晨光超出了那座山（x {xs.min()}–{xs.max()}）"
        assert ys.max() < H.WALL_TOP - 10, f"{rid} 的晨光落到了墙头以下（y {ys.max()}）"
        assert not (vis & keep_off).any(), f"{rid} 的晨光落在心灯 / 人物 / 文字区上"
        seen += vis
    assert (seen > 1).sum() == 0, f"几处晨光互相重叠（{(seen > 1).sum()} 个像素）"


def test_focus_lights():
    """人物的聚光 light = [x, y, 半径, 强度]：半径为正、强度在 (0, 1]；灯童在门洞的暗处，给得比别人大。"""
    lights = {c["id"]: c["light"] for c in man()["characters"]}
    for cid, L in lights.items():
        assert len(L) == 4 and all(isinstance(v, (int, float)) for v in L), f"{cid} 的 light 应是 [x, y, 半径, 强度]：{L}"
        assert L[2] > 0 and 0 < L[3] <= 1, f"{cid} 的聚光半径 / 强度不对：{L}"
    assert lights["child"][3] > max(L[3] for k, L in lights.items() if k != "child"), "灯童的聚光应比别人强"
    assert "强度" in man()["note"], "note 里要说明 light 的第 4 个值"


def test_dawn_only_on_the_top():
    """晨光只照峰顶和上面几成的山脊：金线的 alpha 峰值 ≤ 0.35、只在峰高的上面一半，东坡（右）比西坡亮；
    晨光的暖色九成以上在峰的上半截和山后的天上。幽都放宽到上面 65%（山口里黑城的屋脊、山口的天比两道山肩低）。"""
    m = man()
    for rid, e in m["dawn"].items():
        lay, cx, hgt, wl, wr, sharp, half = H.REGIONS[rid]
        base_y = H.BACK_BASE if lay == "back" else H.FAR_BASE
        g = img(e["glow"]["file"], "RGBA")[..., 3]
        gx, gy = e["glow"]["rect"][:2]
        assert g.max() <= 0.35 + 1e-9, f"{rid} 的山脊金线太亮（峰值 {g.max():.3f}）"
        ys, xs = np.nonzero(g > 0.02)
        ytop = ys.min() + gy
        h = base_y - ytop
        reach = (ys.max() + gy - ytop) / h
        limit = 0.65 if rid == "youdu" else 0.5  # 幽都：山口里黑城的屋脊、山口的天比两道山肩低
        assert reach <= limit, f"{rid} 的金线往下铺得太远（到峰高的 {reach:.0%}）"
        a = img(e["file"], "RGBA")[..., 3]
        ax, ay = e["rect"][:2]
        yy = np.mgrid[0:a.shape[0], 0:a.shape[1]][0] + ay
        upper = a[yy <= ytop + limit * h].sum() / a.sum()
        assert upper >= 0.9, f"{rid} 的晨光没有集中在上半截（{upper:.0%}）"
        if rid == "youdu":
            continue
        x_s = xs[ys == ys.min()].mean() + gx
        xx = np.mgrid[0:g.shape[0], 0:g.shape[1]][1] + gx
        right, left = g[xx > x_s].sum(), g[xx < x_s].sum()
        assert right > 1.3 * left, f"{rid}：东坡（右）应比西坡亮（右 {right:.0f}，左 {left:.0f}）"


# ============================================================== 路灯


def label_text() -> list:
    """名字和行当在游戏里实际写字的地方：名字一行（39 像素字，每字约 39 宽）、行当一行（21 像素字，约 7 个字宽），
    都以 label 点为中，从 label 点往下共约 64 像素。（游戏里名字块有 420 宽，但字只占中间这些。）"""
    out = []
    for c in man()["characters"]:
        x, y = c["label"]
        nw, rw = 39 * len(c["name"]), 21 * 7
        out += [(x - nw / 2, y, nw, 40), (x - rw / 2, y + 40, rw, 24)]
    return out


def overlap(a, b) -> bool:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    return ax < bx + bw and bx < ax + aw and ay < by + bh and by < ay + ah


def test_road_lamps_layout():
    """路灯 1–10 盏，每盏四层（灯身、火苗普通，内圈、外圈叠加），文件名 road_<n>…；四层都在 safe 里；
    看得见的灯（灯身、火苗、内圈）不碰人物点击区、名字和行当的字、text_safe 和心灯；
    底部提示条上面空出一截（游戏在那里写台词，路灯亮起时会放大）：灯身底边 ≤ 提示条上沿 − 24，光晕底边 ≤ 提示条上沿 − 14；
    外圈光晕是光不是灯：落在名字和行当的字上、text_safe 里几乎为 0，挨着点击区边上的也不亮；
    路灯之间不重叠；近的大、远的小。"""
    m = man()
    rl = m.get("road_lamps")
    assert rl and 1 <= len(rl) <= 10, f"road_lamps 应有 1–10 盏：{None if rl is None else len(rl)}"
    assert len(rl) == len(H.ROAD_LAMPS), f"road_lamps {len(rl)} 盏，脚本里排了 {len(H.ROAD_LAMPS)} 个位置"
    texts = [(int(math.floor(x)), y, int(math.ceil(w)) + 1, h) for (x, y, w, h) in label_text()]
    keep_off = [c["rect"] for c in m["characters"]] + texts + [list(r) for r in m["text_safe"]]
    lamp_rects = [v["rect"] for e in m["lamps"].values() for k, v in e.items() if k in ("body", "flame", "core")]
    text = rect_mask(texts + [list(r) for r in m["text_safe"]])
    edge = rect_mask([c["rect"] for c in m["characters"]])
    band = m["text_safe"][1][1]  # 底部提示条的上沿
    bodies = []
    for n, e in enumerate(rl):
        assert set(e) == {"body", "flame", "core", "glow"}, f"路灯 {n} 应有四层：{sorted(e)}"
        for part, suffix, blend_ in (("body", "", "normal"), ("flame", "_flame", "normal"), ("core", "_core", "add"), ("glow", "_glow", "add")):
            v = e[part]
            assert v["file"] == f"road_{n}{suffix}.png", f"路灯 {n}.{part} 的文件名不对：{v['file']}"
            assert v["blend"] == blend_, f"路灯 {n}.{part} 应为 {blend_}"
            assert inside(v["rect"], SAFE), f"路灯 {n}.{part} 的 rect {v['rect']} 不在 safe 里"
        for part in ("body", "flame", "core"):
            for r in keep_off + lamp_rects:
                assert not overlap(e[part]["rect"], r), f"路灯 {n}.{part} {e[part]['rect']} 碰到了 {r}"
        bx, by, bw, bh = e["body"]["rect"]
        assert by + bh <= band - 24, f"路灯 {n} 的灯身底边 y {by + bh} 离提示条（上沿 {band}）太近，应 ≤ {band - 24}"
        gx, gy, gw, gh = e["glow"]["rect"]
        assert gy + gh <= band - 14, f"路灯 {n} 的光晕底边 y {gy + gh} 离提示条（上沿 {band}）太近，应 ≤ {band - 14}"
        x, y, w, h = e["glow"]["rect"]
        g = img(e["glow"]["file"], "RGBA")[..., 3]
        on_text = (g * text[y:y + h, x:x + w]).max()
        assert on_text <= 0.03, f"路灯 {n} 的光晕落在名字 / 行当的字上或文字区里（{on_text:.3f}）"
        on_edge = (g * edge[y:y + h, x:x + w]).max()
        assert on_edge <= 0.25, f"路灯 {n} 的光晕漏到点击区边上太亮（{on_edge:.3f}）"
        bodies.append(e["body"]["rect"])
    for i in range(len(bodies)):
        for j in range(i + 1, len(bodies)):
            assert not overlap(bodies[i], bodies[j]), f"路灯 {i} 和 {j} 的灯身重叠"
    by_depth = sorted(range(len(bodies)), key=lambda i: bodies[i][1] + bodies[i][3])  # 按脚下的 y 排：越往下越近
    near, far = by_depth[-1], by_depth[0]
    assert bodies[near][3] > bodies[far][3], f"近的路灯应比远的大（{bodies[near][3]} vs {bodies[far][3]}）"
    heart = max(v["body"]["rect"][2] * v["body"]["rect"][3] for v in m["lamps"].values())
    lantern = max(img(e["body"]["file"], "RGBA")[..., 3].sum() for e in rl)
    assert lantern < 1.6 * heart, "路灯整盏的墨不应比一盏心灯的灯身大太多（树才是主角）"


def test_road_lamps_render():
    """每盏路灯叠上去只改自己的几个 rect；灯身是整盏灯：杆从灯笼一直到地上（底边有影子），灯笼亮、暖；
    火苗的 base 在火苗 rect 里、靠底边；叠加层的规则见 test_additive_layers（同样查了路灯）。"""
    m = man()
    b = base()
    for n, e in enumerate(m["road_lamps"]):
        out = composite([], [], 0)
        for part in ("body", "flame", "core", "glow"):
            blend(out, e[part])
        out = np.clip(out, 0, 1)
        changed = np.abs(out - b).max(-1) > 1.5 / 255
        own = rect_mask([v["rect"] for v in e.values()])
        assert not (changed & ~own).any(), f"路灯 {n} 改到了自己的 rect 以外"
        a = img(e["body"]["file"], "RGBA")
        x, y, w, h = e["body"]["rect"]
        rows = np.nonzero(a[..., 3].max(1) > 0.5)[0]
        assert rows.size and rows.max() - rows.min() >= 40, f"路灯 {n} 的灯身太矮（{rows.max() - rows.min() if rows.size else 0}）：应是整盏灯"
        assert a[-6:, :, 3].max() > 0.25, f"路灯 {n} 的灯身底边没有落地的影子"
        lit = (lum(a[..., :3]) > 0.75) & (a[..., 3] > 0.9)
        warm = (a[..., 0] - a[..., 2])[lit]
        assert lit.sum() >= 20 and warm.mean() > 0.15, f"路灯 {n} 的灯笼不够亮 / 不够暖"
        v = e["flame"]
        fx, fy, fw, fh = v["rect"]
        bx, by = v["base"]
        assert fx <= bx <= fx + fw and fy <= by <= fy + fh and fy + fh - by <= 6, f"路灯 {n} 的火苗 base {v['base']} 不对"
        fa = img(v["file"], "RGBA")[..., 3]
        ys = np.nonzero(fa.max(1) > 0.5)[0]
        assert ys.size and by - (ys.min() + fy) >= 5, f"路灯 {n} 的火苗太矮"


def test_existing_outputs_unchanged():
    """和游戏里正在用的（assets/atlas/screens/hub/）比：底图和路灯以外的各层逐字节相同；hub.json 里路灯以外的键和值都没变，
    road_lamps 的盏数、每盏的层、文件名、混合方式都和游戏里的一样，只有 rect、base 的数可以变。"""
    if not ASSETS.exists():
        print("      （跳过：没有 assets/atlas/screens/hub/）")
        return
    old = json.loads((ASSETS / "hub.json").read_text(encoding="utf-8"))
    new = man()
    for k, v in old.items():
        if k != "road_lamps":
            assert new.get(k) == v, f"hub.json 的 {k} 变了"
    assert set(new) - set(old) <= {"road_lamps"}, f"hub.json 多了别的键：{sorted(set(new) - set(old))}"
    if "road_lamps" in old:
        ro, rn = old["road_lamps"], new["road_lamps"]
        assert len(ro) == len(rn), f"路灯的盏数变了：{len(ro)} → {len(rn)}"
        for n, (eo, en) in enumerate(zip(ro, rn)):
            assert set(eo) == set(en), f"路灯 {n} 的层变了"
            for part in eo:
                assert set(eo[part]) == set(en[part]), f"路灯 {n}.{part} 的键变了"
                for key in eo[part]:
                    if key not in ("rect", "base"):
                        assert eo[part][key] == en[part][key], f"路灯 {n}.{part} 的 {key} 变了"
    diff = [p.name for p in sorted(ASSETS.iterdir())
            if p.name != "hub.json" and not p.name.startswith("road_") and p.read_bytes() != (OUT / p.name).read_bytes()]
    assert not diff, f"这些文件和游戏里的不一样了：{diff[:6]}"

# ============================================================== 底图


def test_text_safe_quiet():
    """文字安全区安静、够暗：笔触细节（高通能量）远少于画面主体，没有明显的线，纸色字对比够；点满灯、晨光全亮也一样。"""
    full = composite(list(man()["lamps"]), list(man()["dawn"]), len(man().get("road_lamps", [])))
    for label, a in (("底图", base()), ("全亮（心灯、路灯、晨光）", full)):
        L = lum(a)
        hp = np.abs(L - H.blur(L, 6.0))
        fine = np.abs(L - H.blur(L, 1.2))
        body = hp[300:880, 150:1800].mean()
        for (x, y, w, h) in man()["text_safe"]:
            b = hp[y:y + h, x:x + w]
            assert b.mean() < 0.2 * body, f"{label}：text_safe {[x, y, w, h]} 太花（高通 {b.mean():.4f}，主体 {body:.4f}）"
            assert fine[y:y + h, x:x + w].max() < 0.05, f"{label}：text_safe {[x, y, w, h]} 里有明显的线（{fine[y:y + h, x:x + w].max():.3f}）"
            m = L[y:y + h, x:x + w].mean()
            assert (lum(H.PAPER) + 0.05) / (m + 0.05) > 3.0, f"{label}：text_safe {[x, y, w, h]} 不够暗（平均亮度 {m:.2f}）"
            assert L[y:y + h, x:x + w].std() < 0.04, f"{label}：text_safe {[x, y, w, h]} 浓淡不匀（标准差 {L[y:y + h, x:x + w].std():.3f}）"


def test_ink_only_except_lights():
    """长夜的底图只有墨：离四个人的灯远的地方都是纸墨的暖灰（彩度低），全图没有偏青 / 偏绿的像素；
    灯边是暖的。朱砂印除外。"""
    b = base()
    yy, xx = np.mgrid[0:H.H, 0:H.W]
    far = np.ones((H.H, H.W), bool)
    for c in man()["characters"]:
        x, y, r = c["light"][:3]
        far &= np.hypot(xx - x, yy - y) > 2.0 * r + 60
    sx, sy = H.SEAL_AT
    seal = (xx >= sx - 4) & (xx < sx + H.SEAL_PX + 4) & (yy >= sy - 4) & (yy < sy + H.SEAL_PX + 4)
    far &= ~seal
    assert far.mean() > 0.25, "离灯远的区域太少，测不出来"
    chroma = b.max(-1) - b.min(-1)
    p = np.percentile(chroma[far], 99.9)
    assert p <= 0.14, f"离灯远的地方有颜色（彩度 99.9 分位 {p:.3f}）"
    cool = ((b[..., 2] > b[..., 0] + 0.02) | (b[..., 1] > b[..., 0] + 0.02)) & ~seal
    assert cool.mean() < 0.0005, f"有偏青 / 偏绿的像素（{cool.mean():.4f}）"
    for c in man()["characters"]:
        x, y, r = c["light"][:3]
        near = (np.hypot(xx - x, yy - y) < r) & ~seal
        warm = (b[..., 0] - b[..., 2])[near].mean()
        assert warm > 0.08, f"{c['id']} 的灯边不够暖（R−B {warm:.3f}）"


def test_size_on_disk():
    """hub.png < 3 MB，整个目录 < 5 MB。"""
    kb = (OUT / "hub.png").stat().st_size / 1024
    assert kb < 3 * 1024, f"hub.png {kb:.0f} KB 太大"
    total = sum(p.stat().st_size for p in OUT.iterdir()) / 1024 / 1024
    assert total < 5.0, f"screens/hub/ 共 {total:.2f} MB 太大"


def test_review_images():
    """审图都在：三种状态、人物特写、720p 界面样张。"""
    for p in REVIEWS:
        assert p.exists(), f"缺审图 {p.name}"
        with Image.open(p) as im:
            assert im.width >= 1280, f"{p.name} 太小（{im.size}）"


def test_determinism():
    """固定种子：另画两遍到临时目录（并行），所有文件逐字节相同，也和 screens/hub/ 里的相同（--quick 跳过）。"""
    if "--quick" in sys.argv:
        print("      （跳过：--quick）")
        return
    with tempfile.TemporaryDirectory() as ta, tempfile.TemporaryDirectory() as tb:
        cmd = [sys.executable, str(HERE / "hub_scroll.py"), "--no-review", "--out"]
        procs = [subprocess.Popen(cmd + [t], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE) for t in (ta, tb)]
        for pr in procs:
            _, err = pr.communicate()
            assert pr.returncode == 0, f"生成失败：{err.decode(errors='replace')[-500:]}"
        fa = sorted(p.name for p in Path(ta).iterdir())
        fb = sorted(p.name for p in Path(tb).iterdir())
        assert fa == fb, "两次生成的文件列表不同"
        ours = sorted(p.name for p in OUT.iterdir())
        assert fa == ours, f"文件列表和 screens/hub/ 不同：{set(fa) ^ set(ours)}"
        diff = [n for n in fa if (Path(ta) / n).read_bytes() != (Path(tb) / n).read_bytes()]
        assert not diff, f"两次生成不一致：{diff[:5]}"
        diff = [n for n in fa if (Path(ta) / n).read_bytes() != (OUT / n).read_bytes()]
        assert not diff, f"和 screens/hub/ 里的不一致：{diff[:5]}"


def main() -> int:
    ensure_outputs("--regen" in sys.argv)
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
