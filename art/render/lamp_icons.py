"""提灯夜行 · 灯的界面图标 ui/icon_lamp_{red,mirror,frost}（择灯界面、局外“灯”页用）。

每盏灯的灯笼头单独渲（models/lanterns.py，不带主角）：四分之三侧面、相机略向下看，灯芯点亮，挂件随微风略摆；
用同一套假卡通材质、Freestyle 墨线和后期（post/postprocess.py）。再像 render/portrait.py 装头像那样装进
界面图标的圆框（post/ui_icons.py 的 disc_back / ring_front，只读）：宣纸圆底 → 灯后一团该灯光色的晕 →
灯笼 → 灯芯（由白热到灯色）→ 色弧（灯的光色兑国画颜料，同 ui_icons 五行色弧的配法）+ 一笔墨圈。

运行（在仓库根目录下，只出 2 倍）：
    LANTERN_ART_DENSITY=2 art/.venv/bin/python art/render/lamp_icons.py
输出：art/out/assets@2x/lamp_icons/icon_lamp_<灯>.png（128²）+ meta.json（特效 meta 格式，"name": "ui"，
打包后帧名是 ui/icon_lamp_<灯>；每项 kind=lamp、id、name、light_color）。
审图：art/out/review@2x/lamp_icons_review.png（128 / 64 / 32 像素，宣纸底和夜色底，旁边放几枚现有图标对照）。
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
from PIL import Image  # noqa: E402

from style import style as S  # noqa: E402

D = S.DENSITY
OUT_DIR = ART / "out" / S.ASSETS_DIR_NAME / "lamp_icons"
REVIEW = ART / "out" / ("review" if D == 1 else f"review@{D:g}x")
TMP = ART / "out" / "_tmp_lamp_icons"
LOGICAL = 64  # 与 ui_icons 的图标同一套 64 逻辑像素坐标；2 倍时 128²
LAMPS = ("red", "mirror", "frost")

# 取景（米，灯笼头自己的坐标：枢轴在原点，灯芯在 C_Z）：三盏灯同一个比例
VIEW_WIDTH_M = 0.78  # 64 逻辑像素对应的宽度（灯身约占圆框内径的六成，和现有图标一样留白）
VIEW_DROP_M = 0.07  # 画面中心比灯芯低这么多（下面的挂件比上面的盖子长）
PITCH_DEG = 16.0  # 相机略向下看
YAW_DEG = {"red": -28.0, "mirror": -34.0, "frost": -24.0}  # 四分之三侧面；铜镜灯多转一点，镜子从一侧露出来
LINE_K = 1.25  # 图标缩到 32 像素时线还看得见，线宽加粗一点
RENDER_K = 2  # 灯笼先按图标 2 倍大渲染（后期再缩），墨线、颜色都更干净


def arc_colors() -> dict:
    """色弧：灯的光色兑国画颜料（与 ui_icons.EL_INK 同一种配法：火兑朱砂、金兑藤黄赭石、水兑花青）。"""
    import lanterns as LAN

    info = LAN.lamp_data()
    A = S.ACCENT
    return {"red": S.mix(info["red"]["color"], A["zhusha"], 0.45),
            "mirror": S.mix(S.mix(info["mirror"]["color"], A["tenghuang"], 0.5), A["zheshi"], 0.3),
            "frost": S.mix(info["frost"]["color"], A["huaqing"], 0.5)}


# ================================================================ 渲染灯笼头
def render_head(lamp: str) -> dict:
    """单独渲一盏灯的灯笼头（px² 最终像素，px = 64 × 密度 × RENDER_K）。返回 rgba / emit (uint8) 与灯芯像素位置。"""
    import bpy
    from mathutils import Vector
    from style import bstyle as B
    import hero as HERO
    import lanterns as LAN
    import portrait as PT
    import postprocess as P

    px = int(round(LOGICAL * D * RENDER_K))
    t0 = time.perf_counter()
    B.reset_scene()
    B.setup_render(px)
    target = Vector((0.0, 0.0, LAN.C_Z - VIEW_DROP_M))
    PT.ortho_camera(target, PITCH_DEG, VIEW_WIDTH_M, px * S.RENDER_SCALE, px * S.RENDER_SCALE)
    B.setup_freestyle()
    PT.scale_lines(LINE_K * RENDER_K)  # 线宽按最终像素给，灯笼放大了 RENDER_K 倍，线也跟着
    root = B.empty("LampIconRoot")
    M = HERO._materials()  # 灯笼头共用主角的 cap / gold / tassel 材质
    head = LAN.build_head(lamp, root, (0, 0, 0), M)
    root.rotation_mode = "XYZ"
    root.rotation_euler.z = math.radians(YAW_DEG[lamp])
    head.animate(0.9, 0.25)  # 挂件随微风略摆
    head.set_core(1.0)
    bpy.context.view_layer.update()
    core_px = PT.project_px(head.pivot.matrix_world @ Vector((0, 0, LAN.C_Z)), px, px)
    pal = tuple(P.LIGHT_COLORS) + tuple(c for c in LAN.palette_extra(lamp) if c not in P.LIGHT_COLORS)
    with B.render_lock():
        L = B.render_layers(TMP / f"lamp_icon_{lamp}")
    R = P.process_layers(L, f"lamp_icon_{lamp}", extra_palette=pal)
    for p in TMP.glob("*.exr"):
        p.unlink()
    return {"rgba": R["rgba"], "emit": R["emit"], "core_px": core_px, "px": px, "render_s": L["time_s"],
            "total_s": time.perf_counter() - t0}


# ================================================================ 装框（借用 ui_icons 的圆框，只读）
def compose(lamp: str, head: dict) -> Image.Image:
    import portrait as PT

    UI, V, W = PT.import_ui()
    info = __import__("lanterns").lamp_data()
    light = V.col(info[lamp]["color"])
    arc = V.col(arc_colors()[lamp])
    P = W.Painter(LOGICAL, LOGICAL, 7300 + LAMPS.index(lamp), ss=4)
    C = UI.C
    UI.disc_back(P, UI.mixc(UI.PAPER, light, 0.06))
    n = P.X.shape[0]
    rgba = np.asarray(Image.fromarray(head["rgba"]).resize((n, n), Image.LANCZOS), np.float64) / 255.0
    emit = np.asarray(Image.fromarray(head["emit"]).resize((n, n), Image.LANCZOS), np.float64) / 255.0
    cx, cy = (np.array(head["core_px"]) / head["px"]) * LOGICAL  # 灯芯（逻辑坐标）
    r = np.hypot(P.X - C, P.Y - C)
    clip = UI.smoothstep(25.9 + P.aa, 25.9 - P.aa, r)  # 收在色弧里面
    disc = P.lay.a.copy() * clip
    # 灯后一团光：该灯的光色兑一点宣纸
    dl = np.hypot(P.X - cx, P.Y - cy)
    glow = np.exp(-((dl / 15.0) ** 2))
    P.lay.over(UI.mixc(light, UI.PAPER, 0.35), 0.55 * glow * disc)
    # 灯笼：颜色原样，灯侧略提亮
    lit = np.clip(rgba[..., :3] * UI.mixc(np.ones(3), light, 0.18 * glow) + 0.04 * glow[..., None] * light, 0, 1)
    P.lay.over(lit, rgba[..., 3] * clip)
    # 灯芯：发光层上由白热到灯色的渐变，外面一圈晕
    ea = np.clip(emit[..., 3], 0, 1)
    if ea.max() > 0:
        ys, xs = np.nonzero(ea > 0.5)
        er = max(1.0, 0.5 * max(xs.max() - xs.min(), ys.max() - ys.min()) / (n / LOGICAL))
        rr = np.hypot(P.X - cx, P.Y - cy) / er
        core_rgb = emit[..., :3]
        hot = UI.mixc(core_rgb, np.ones(3), 0.65)
        P.lay.over(UI.mixc(hot, core_rgb, UI.smoothstep(0.05, 1.0, rr)), ea * clip)
        halo = np.exp(-((np.maximum(rr - 0.8, 0) / 1.0) ** 2)) * (1 - ea)
        P.lay.over(UI.mixc(light, np.ones(3), 0.3), 0.30 * halo * clip * (1 - rgba[..., 3] * 0.6))
    UI.ring_front(P, arc, arc_hw=0.95)
    return P.image()


def write_meta(imgs: dict) -> None:
    import lanterns as LAN

    info = LAN.lamp_data()
    arcs = arc_colors()
    files = {}
    for lamp, img in imgs.items():
        files[f"icon_lamp_{lamp}.png"] = {
            "size": [img.width, img.height], "anchor": [0.5, 0.5], "color": "full", "blend": "normal", "tint": False,
            "kind": "lamp", "id": lamp, "name": info[lamp]["name"], "light_color": info[lamp]["color"],
            "arc_color": arcs[lamp], "note": f"灯的图标：{info[lamp]['name']}（灯笼头单独渲染，装进图标圆框）"}
    meta = {
        "name": "ui",
        "generator": "art/render/lamp_icons.py",
        "format": "PNG RGBA，直通（非预乘）alpha；全彩、正常混合、不染色",
        "px_per_unit": S.PX_PER_UNIT,
        "display_px_1x": LOGICAL,
        "files": files,
    }
    (OUT_DIR / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")


# ================================================================ 审图
def review(imgs: dict) -> Path:
    """三枚灯图标：128 / 64 / 32 像素，宣纸底一排、夜色底一排；右边放几枚现有图标（灯火、符剑、霜铃）对照。"""
    import contact_sheet as CS

    ui_dir = ART / "out" / S.ASSETS_DIR_NAME / "ui"
    refs = [Image.open(ui_dir / f"icon_{k}.png").convert("RGBA") for k in ("lamp", "sword", "bell")
            if (ui_dir / f"icon_{k}.png").exists()]
    full = int(LOGICAL * D)
    sizes = (full, full // 2, full // 4)
    gap = int(8 * D)
    tiles = list(imgs.values())
    width = gap + sum((s + gap) * (len(tiles) + len(refs)) + 2 * gap for s in sizes)
    rows = []
    for night in (False, True):
        h = full + 2 * gap
        bg = CS.paper(width, h, seed=5) if not night else Image.new("RGBA", (width, h), CS.rgb(S.NIGHT_AMBIENT) + (255,))
        x = gap
        for s in sizes:
            for k, im in enumerate(tiles + refs):
                sm = im.resize((s, s), Image.LANCZOS)
                bg.alpha_composite(sm, (x, gap + (full - s) // 2))
                x += s + gap
                if k == len(tiles) - 1:
                    x += gap  # 现有图标和灯图标之间空一点
            x += gap
        rows.append(bg.convert("RGB"))
    out = Image.new("RGB", (width, sum(r.height for r in rows)), CS.rgb(S.PAPER))
    y = 0
    for r_ in rows:
        out.paste(r_, (0, y))
        y += r_.height
    REVIEW.mkdir(parents=True, exist_ok=True)
    path = REVIEW / "lamp_icons_review.png"
    out.save(path)
    CS.zoom(out, 2).save(REVIEW / "lamp_icons_review_zoom.png")
    return path


def main(argv: list[str]) -> int:
    if D != 2 and "--any-density" not in argv:
        print("灯图标只出 2 倍：请加 LANTERN_ART_DENSITY=2（1 倍网页版已冻结）")
        return 2
    t0 = time.perf_counter()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    imgs = {}
    for lamp in LAMPS:
        head = render_head(lamp)
        img = compose(lamp, head)
        img.save(OUT_DIR / f"icon_lamp_{lamp}.png", optimize=True)
        imgs[lamp] = img
        print(f"[lamp_icon] {lamp}：渲染 {head['render_s']:.2f}s（{head['px'] * S.RENDER_SCALE}²），共 {head['total_s']:.1f}s")
    write_meta(imgs)
    path = review(imgs)
    if TMP.exists() and not any(TMP.iterdir()):
        TMP.rmdir()
    print(f"[lamp_icon] {len(imgs)} 枚 → {OUT_DIR}；审图 {path}；共 {time.perf_counter() - t0:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
