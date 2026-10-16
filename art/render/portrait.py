"""提灯夜行 · 主角头像（界面 HUD 用的圆形头像 ui/portrait_hero）。

用正式主角模型（models/hero.py）、同一套假卡通墨色材质、Freestyle 墨线和后期（post/postprocess.py），
只是相机拉近：胸像、四分之三侧脸、微微看向画面左边；灯杖从画框左下方斜伸进来，灯笼挂在脸的左下方，
暖光照亮脸的左侧（后期按灯笼位置染暖光、背灯一侧压一层淡夜色）。近景专用的改动：精灵尺度的墨点眼和眉
换成后期按投影位置画的五官，发束与脸面沿用正式主角模型，脸的暗面改染淡赭，灯笼缩小、灯杖变细。
再装进界面图标同一套圆框（post/ui_icons.py 的 frame_back / frame_front：宣纸圆底 + 一笔墨圈），
墨圈内侧是一道藤黄偏火色的暖弧。

运行（在仓库根目录下）：
    art/.venv/bin/python art/render/portrait.py                          # 1 倍：128²
    LANTERN_ART_DENSITY=2 art/.venv/bin/python art/render/portrait.py    # 2 倍：256²
    art/.venv/bin/python art/render/portrait.py --all                    # 两种密度各出一遍（子进程，约 17 秒）
输出：art/out/<ASSETS_DIR_NAME>/portrait/portrait_hero.png + meta.json（特效 meta 格式，"name": "ui"，
打包后帧名是 ui/portrait_hero）。直通 alpha，颜色扩进透明区。

这里的相机 / 线宽 / 投影小工具也给 render/title_hero.py（标题画的主角背影）用。
"""

from __future__ import annotations

import json
import math
import os
import subprocess
import sys
import time
from pathlib import Path

ART = Path(__file__).resolve().parents[1]
for p in (ART, ART / "models", ART / "post", ART / "render"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import numpy as np  # noqa: E402

from style import style as S  # noqa: E402

D = S.DENSITY
OUT_DIR = ART / "out" / S.ASSETS_DIR_NAME / "portrait"
TMP = ART / "out" / "_tmp_portrait"
LOGICAL = 64  # 圆框按 64 逻辑像素画（与图标同一套坐标），头像是图标的 2 倍大
K = 2  # 头像边长 = LOGICAL * K * DENSITY
SIZE = LOGICAL * K  # 1 倍下 128

# 胸像取景（米，世界坐标）：相机对准的点、取景宽度、俯角；主角绕 Z 转多少（0 = 正对镜头，负 = 看向画面左边）
BUST_TARGET = (-0.06, 0.0, 1.93)
BUST_WIDTH_M = 0.76
BUST_PITCH_DEG = 9.0
BUST_YAW_DEG = -24.0
# 灯笼摆位（主角模型坐标，未转向前）：灯笼芯中心；灯杖从 STAFF_FROM 连到灯笼正上方的杖头
LANTERN_AT = (-0.10, -0.37, 1.75)
STAFF_FROM = (-0.51, -0.55, 1.42)  # 灯杖从画框外左下方斜伸进来，灯笼挂在杖头内侧、脸的左下方
HEAD_ROT_DEG = (-4.0, 0.0, -10.0)  # 头枢轴（抬下巴、侧倾、转向）
ARM_ROT_DEG = (0.0, 0.0, 0.0)  # 右臂（肩为轴）
LANTERN_SCALE = 0.8
STAFF_K = 0.6  # 近景里原粗细的灯杖像根木桩
LINE_K = 1.0  # 头像线宽倍数（相对 style 的线宽）


# ================================================================ Blender 小工具（title_hero.py 也用）
def ortho_camera(target, pitch_deg: float, width_m: float, res_x: int, res_y: int, distance: float = 25.0):
    """正交相机：从 -Y 侧朝 +Y 看，俯角 pitch_deg，取景宽 width_m 米，画面中心对准 target。"""
    import bpy
    from mathutils import Vector

    sc = bpy.context.scene
    r = sc.render
    r.resolution_x, r.resolution_y = int(res_x), int(res_y)
    cam = sc.camera
    if cam is None:
        cam = bpy.data.objects.new("Cam", bpy.data.cameras.new("Cam"))
        sc.collection.objects.link(cam)
        sc.camera = cam
    cd = cam.data
    cd.type = "ORTHO"
    cd.ortho_scale = width_m * max(1.0, res_y / res_x)  # Blender 的 ortho_scale 量的是长边
    cd.sensor_fit = "AUTO"
    cd.shift_x = cd.shift_y = 0.0
    cd.clip_start, cd.clip_end = 0.1, distance * 3
    p = math.radians(pitch_deg)
    cam.rotation_mode = "XYZ"
    cam.rotation_euler = (math.radians(90.0) - p, 0.0, 0.0)
    fwd = Vector((0.0, math.cos(p), -math.sin(p)))
    cam.location = Vector(target) - fwd * distance
    bpy.context.view_layer.update()
    return cam


def scale_lines(k: float) -> None:
    """把 setup_freestyle 建好的几种笔触整体加粗 / 变细 k 倍（书法修饰器的上下限一起缩放）。"""
    import bpy

    if abs(k - 1.0) < 1e-6:
        return
    for st in bpy.data.linestyles:
        st.thickness *= k
        for mo in st.thickness_modifiers:
            if mo.type == "CALLIGRAPHY":
                mo.thickness_min *= k
                mo.thickness_max *= k


def project_px(world_xyz, out_w: int, out_h: int) -> tuple[float, float]:
    """世界坐标 → 最终像素（左上角为原点，x 向右，y 向下）。"""
    import bpy
    from bpy_extras.object_utils import world_to_camera_view
    from mathutils import Vector

    sc = bpy.context.scene
    co = world_to_camera_view(sc, sc.camera, Vector(world_xyz))
    return co.x * out_w, (1.0 - co.y) * out_h


def render_processed(name: str, tmp_dir: Path, scale: int) -> dict:
    """在渲染锁里渲一次，读出填色 / 墨线 / 发光三层，走正式后期。返回 process_layers 的结果 + 渲染耗时。"""
    from style import bstyle as B
    import postprocess as P

    with B.render_lock():
        L = B.render_layers(tmp_dir / f"{name}")
    R = P.process_layers(L, name, scale=scale)
    R["time_s"] = L["time_s"]
    return R


def place_lantern(parts: dict, lantern_at, scale: float = 1.0, staff_from=None, staff_k: float = 1.0) -> None:
    """把灯笼挂到 lantern_at（主角模型坐标里的灯笼芯中心，随主角转向），灯杖从右手重新连到灯笼正上方的杖头。
    灯杖、杖头、灯笼都挂在右臂下，所以换算到右臂的局部坐标（右臂、上身此刻的旋转都已计入）。
    scale：灯笼（连同挂绳、符纸）整体缩放；胸像里原大的灯笼比脸还大，喧宾夺主。
    staff_from：灯杖下端经过的点（主角模型坐标）；不给就从右手握处起。staff_k：灯杖和杖头的粗细倍数。"""
    import bpy
    from mathutils import Matrix, Vector
    from style import bstyle as B
    import hero as HERO

    root, armR, lp = parts["root"], parts["arm_R"], parts["lantern"]
    bpy.context.view_layer.update()
    tip_root = Vector(lantern_at) - Vector((0, 0, parts["lantern_cz"] * scale))  # lantern_cz < 0：灯笼芯在杖头下方
    to_arm = armR.matrix_world.inverted() @ root.matrix_world
    lp.matrix_basis = to_arm @ Matrix.Translation(tip_root) @ Matrix.Scale(scale, 4)  # 灯笼保持竖直（与主角同向）
    if staff_from is None:
        hand = armR.matrix_world.inverted() @ bpy.data.objects["HandR"].matrix_world.translation
    else:
        hand = to_arm @ Vector(staff_from)
    b = to_arm @ tip_root
    d = b - hand
    a = hand - d.normalized() * HERO.STAFF_GRIP  # 握处以下再留一截
    staff = bpy.data.objects["Staff"]
    staff.scale = (staff_k, staff_k, (b - a).length / HERO.STAFF_LEN)
    B.aim(staff, a, b)
    knob = bpy.data.objects["StaffKnob"]
    knob.location = b
    knob.scale = (staff_k,) * 3
    bpy.context.view_layer.update()


# ================================================================ 头像
def soften_skin(parts: dict) -> None:
    """近景的脸：精灵用的三档肤色（暗面混重墨）在胸像上是一道生硬的灰色分界，
    改成工笔人物的染法——暗面只染一层淡赭，中间档更接近亮面。直接改肤色材质里的色阶节点。"""
    m = parts["mats"]["skin"]
    cr = next(n for n in m.node_tree.nodes if n.type == "VALTORGB").color_ramp
    from style import bstyle as B

    mid = S.mix(S.SKIN, S.ACCENT["zheshi"], 0.16)
    dark = S.mix(S.mix(S.SKIN, S.ACCENT["zheshi"], 0.30), S.INK["zhong"], 0.10)
    for e in cr.elements:  # 元素按位置排序：0 暗、SHADE_THRESHOLDS[1] 中、[0] 亮
        if e.position < 0.01:
            e.color = B.hex_lin(dark)
        elif abs(e.position - S.SHADE_THRESHOLDS[1]) < 1e-4:
            e.color = B.hex_lin(mid)


# 五官的特征点（头心坐标，米）：眼内外角、眉头眉尾、鼻梁与鼻尖、嘴角。后期投影到画面上用墨笔画。
FACE_FEATURES = {
    "eye_in": (0.019, -0.006), "eye_out": (0.064, 0.000), "eye_mid": (0.041, 0.004),
    "brow_in": (0.016, 0.030), "brow_mid": (0.042, 0.040), "brow_out": (0.070, 0.038),
    "nose_top": (0.006, 0.010), "nose_tip": (0.007, -0.048), "nose_base": (0.0, -0.056),
    "mouth_l": (0.016, -0.090), "mouth_c": (0.0, -0.088), "mouth_r": (-0.016, -0.090),
}


def face_points(parts: dict, px: int) -> dict:
    """五官特征点 → 最终像素坐标，并给出该点脸面朝向镜头的程度（0 = 侧到看不见，1 = 正对）。
    键名带 _L / _R（主角自己的左 / 右，左在模型 +X）。"""
    import bpy
    from mathutils import Vector
    import hero as HERO

    head = parts["head"]
    hc = HERO.HEAD_C - Vector((0, 0, 1.84))
    cam = bpy.context.scene.camera
    view = (cam.matrix_world.to_3x3() @ Vector((0, 0, -1))).normalized()
    out = {}
    for key, (x0, z) in FACE_FEATURES.items():
        for side, sx in (("L", 1), ("R", -1)):
            x = x0 * sx
            surface = HERO.face_surface(x, z)
            local = hc + surface
            # 鼻梁与下颌已由正式模型塑形；法线也从同一表面求，避免远侧五官穿到脸外。
            eps = 0.0005
            dx = HERO.face_surface(x + eps, z) - HERO.face_surface(x - eps, z)
            dz = HERO.face_surface(x, z + eps) - HERO.face_surface(x, z - eps)
            nrm = dx.cross(dz).normalized()
            w = head.matrix_world
            pw = w @ local
            nw = (w.to_3x3() @ nrm).normalized()
            out[f"{key}_{side}"] = (*project_px(pw, px, px), max(0.0, -nw.dot(view)))
    return out


def build_bust():
    """建模 + 摆姿态：idle 第 0 帧；身体转向画面左边，头再多转一点；灯笼挂在脸的左前下方。
    返回 (root, parts, sockets)。"""
    import bpy
    import hero as HERO

    from hero_style import apply_hero_style

    root, parts, sockets = HERO.build_hero()
    apply_hero_style(parts)
    parts["dir"] = "S"
    root.rotation_mode = "XYZ"
    root.rotation_euler.z = math.radians(BUST_YAW_DEG)
    HERO.pose_hero(parts, "idle", 0, 6)
    parts["head"].rotation_euler = tuple(math.radians(v) for v in HEAD_ROT_DEG)
    parts["arm_R"].rotation_euler = tuple(math.radians(v) for v in ARM_ROT_DEG)
    for sx in (-1, 1):  # 精灵尺度的墨点眼和眉在近景里像两颗黑豆，改由后期按投影位置画（见 face_points）
        for nm in (f"Eye{sx:+d}", f"Brow{sx:+d}"):
            bpy.data.objects[nm].hide_render = True
    soften_skin(parts)
    bpy.context.view_layer.update()
    place_lantern(parts, LANTERN_AT, LANTERN_SCALE, STAFF_FROM, STAFF_K)
    return root, parts, sockets


def render_bust(px: int, tmp_dir: Path = TMP) -> dict:
    """渲染 px² 的胸像（最终像素）。返回 rgba / emit (uint8 h,w,4)、灯笼芯和五官的像素位置、耗时。"""
    from style import bstyle as B

    t0 = time.perf_counter()
    B.reset_scene()
    B.setup_render(px)
    ortho_camera(BUST_TARGET, BUST_PITCH_DEG, BUST_WIDTH_M, px * S.RENDER_SCALE, px * S.RENDER_SCALE)
    B.setup_freestyle()
    scale_lines(LINE_K)
    root, parts, sockets = build_bust()
    lantern_px = project_px(sockets["lantern"].matrix_world.translation, px, px)
    face = face_points(parts, px)
    t_build = time.perf_counter() - t0
    R = render_processed("hero_portrait", tmp_dir, S.RENDER_SCALE)
    for p in tmp_dir.glob("*.exr"):
        p.unlink()
    if tmp_dir.exists() and not any(tmp_dir.iterdir()):
        tmp_dir.rmdir()
    return {"rgba": R["rgba"], "emit": R["emit"], "lantern_px": lantern_px, "face": face,
            "render_s": R["time_s"], "build_s": t_build, "faces": B.face_count(root),
            "render_px": px * S.RENDER_SCALE}


# ================================================================ 装框（纯 numpy，借用 ui_icons 的圆框）
def import_ui():
    """导入 ui_icons / vfx_textures / weapon_textures。它们用 `import style`（把 style/ 目录放进 sys.path）
    取到 style.py 本身，而这里的 `style` 已经是 art/style 包，所以导入时临时把模块名指向 style.py。"""
    pkg = sys.modules.get("style")
    sys.modules["style"] = S
    try:
        import ui_icons as UI
        import vfx_textures as V
        import weapon_textures as W
    finally:
        if pkg is not None:
            sys.modules["style"] = pkg
    return UI, V, W


def compose_portrait(bust: dict) -> "Image.Image":
    """宣纸圆底 → 灯下的胸像（光照图 + 发光层）→ 暖弧与一笔墨圈。返回 RGBA（直通 alpha，颜色已扩边）。"""
    from PIL import Image

    UI, V, W = import_ui()

    class BigPainter(W.Painter):
        """ui_icons 的圆框按 64 逻辑像素画；头像要 K 倍大，所以把网格加密 K 倍、坐标仍按逻辑像素。"""

        def __init__(self, logical: int, k: int, seed: int, ss: int):
            self.w = self.h = logical
            self.ss = ss
            n = int(round(logical * k * D))
            X, Y = V.grid(n, n, ss)
            self.X, self.Y = X / (k * D), Y / (k * D)
            self.lay = V.Layer(*self.X.shape)
            self.rng = np.random.default_rng(seed)
            self.aa = 0.6 / (ss * D * k)

    ss = 4
    P = BigPainter(LOGICAL, K, 7101, ss)
    UI.frame_back(P, "fire")
    C = UI.C
    n = P.X.shape[0]
    out_px = n // ss
    # 胸像放大到超采样网格
    rgba = np.asarray(Image.fromarray(bust["rgba"]).resize((n, n), Image.BICUBIC), np.float64) / 255.0
    emit = np.asarray(Image.fromarray(bust["emit"]).resize((n, n), Image.BICUBIC), np.float64) / 255.0
    lx, ly = (np.array(bust["lantern_px"]) / out_px) * LOGICAL  # 逻辑坐标
    r = np.hypot(P.X - C, P.Y - C)
    clip = UI.smoothstep(26.6 + P.aa, 26.6 - P.aa, r)  # 收在墨圈里
    # ---- 灯下：圆底仍是亮的宣纸（与图标一家），灯笼一侧晕开一团藤黄暖光，背灯的一侧（右上）罩一层很淡的夜色
    disc = P.lay.a.copy() * clip
    dl = np.hypot(P.X - lx, P.Y - ly)
    away = UI.smoothstep(-8.0, 34.0, (P.X - lx) * 0.75 - (P.Y - ly) * 0.66)  # 0 灯侧 → 1 背灯侧
    glow_bg = np.exp(-((dl / 20.0) ** 2))
    night = V.col(S.mix(S.INK["dan"], S.NIGHT_AMBIENT, 0.45))
    P.lay.over(night, 0.20 * away * (1 - glow_bg) * disc)
    P.lay.over(UI.mixc(UI.TENG, UI.PAPER, 0.30), 0.55 * glow_bg * disc)
    # 胸像：底色 × 光（灯侧染暖、提亮一点，背灯侧略压暗偏冷）
    warm = np.exp(-((dl / 30.0) ** 2))
    tint = UI.mixc(np.ones(3), V.col(S.LANTERN_LIGHT), 0.42 * warm)
    cool = UI.mixc(np.ones(3), V.col(S.mix(S.NIGHT_AMBIENT, "#FFFFFF", 0.62)), 0.40 * away * (1 - warm))
    lit = rgba[..., :3] * tint * cool
    lit = np.clip(lit + 0.06 * warm[..., None] * V.col(S.LANTERN_LIGHT), 0, 1)
    # 胸口往下渐渐沉进墨色，视线留在脸上
    fy = bust["face"]["nose_tip_L"][1] * LOGICAL / out_px
    low = UI.smoothstep(fy + 12.0, fy + 30.0, P.Y) * (1 - 0.6 * glow_bg)
    lit = UI.mixc(lit, lit * V.col(S.mix(S.INK["dan"], S.NIGHT_AMBIENT, 0.3)), 0.55 * low)
    P.lay.over(lit, rgba[..., 3] * clip)
    # 发光层：灯笼芯是一团由白热到暖橙的光（渲染出来是平涂的一块），外面再晕一圈
    ea = np.clip(emit[..., 3], 0, 1)
    if ea.max() > 0:
        ys, xs = np.nonzero(ea > 0.5)
        ex, ey = xs.mean() / (n / LOGICAL), ys.mean() / (n / LOGICAL)
        er = max(1.0, 0.5 * (xs.max() - xs.min()) / (n / LOGICAL))
        rr = np.hypot((P.X - ex) / er, (P.Y - ey) / (er * 1.25))
        core = UI.mixc(UI.mixc(V.col(S.LANTERN_LIGHT), np.ones(3), 0.75), V.col(S.mix(S.LANTERN_LIGHT, S.FLAME_LIGHT, 0.55)),
                       UI.smoothstep(0.1, 1.05, rr))
        P.lay.over(core, ea * clip)
        halo = np.exp(-((np.maximum(rr - 0.9, 0) / 0.9) ** 2)) * (1 - ea)
        P.lay.over(UI.mixc(V.col(S.LANTERN_LIGHT), np.ones(3), 0.2), 0.35 * halo * clip)
    paint_face(P, UI, V, {k: (x * LOGICAL / out_px, y * LOGICAL / out_px, v) for k, (x, y, v) in bust["face"].items()},
               (lx, ly))
    UI.frame_front(P, "fire")
    return P.image()


def paint_face(P, UI, V, f: dict, lantern) -> None:
    """按投影好的特征点用墨笔画五官（逻辑坐标）：剑眉、凤眼（上眼线 + 瞳仁 + 一点高光）、鼻尖一笔、淡朱的嘴。
    两只眼看向灯（画面左边），远侧的眼随脸转过去自然变窄。"""
    JIAO, NONG, ZHONG = UI.JIAO, UI.NONG, UI.ZHONG
    lip = V.col(S.mix(S.ACCENT["zhusha"], S.INK["zhong"], 0.35))
    nose_ink = V.col(S.mix(S.INK["zhong"], S.ACCENT["zheshi"], 0.35))

    def pt(k):
        return np.array(f[k][:2])

    def curve(a, m, b, n=24, lift=0.0):
        """过 a、m、b 的二次曲线（m 是中点处的控制，lift 再把中段往上推）。"""
        t = np.linspace(0, 1, n)[:, None]
        c = 2 * m - 0.5 * (a + b) + np.array([0.0, -lift])
        return (1 - t) ** 2 * a + 2 * (1 - t) * t * c + t ** 2 * b

    gaze = np.array([-0.30, 0.04])  # 瞳仁看向左下方的灯
    for side in ("L", "R"):
        v = f[f"eye_mid_{side}"][2]
        if v < 0.12:
            continue
        a, m, b = pt(f"eye_in_{side}"), pt(f"eye_mid_{side}"), pt(f"eye_out_{side}")
        w = np.hypot(*(b - a))
        # 眉：眉头粗、眉尾上挑收尖
        ba, bm, bb = pt(f"brow_in_{side}"), pt(f"brow_mid_{side}"), pt(f"brow_out_{side}")
        brow = curve(ba, bm, bb, lift=0.04 * w)
        hw = np.interp(np.linspace(0, 1, len(brow)), [0, 0.15, 0.7, 1], [0.16, 0.24, 0.17, 0.05]) * (0.6 + 0.4 * v)
        P.line(brow, hw, JIAO, 0.95, jitter=0.1)
        # 瞳仁：上眼线下面的一颗墨点（先画，眼线压在上面）
        c = m + gaze * w * 0.35 + np.array([0.0, 0.10 * w])
        P.dot(c[0], c[1], 0.15 * w + 0.10 * v, NONG, 0.95, ry=0.19 * w + 0.10 * v)
        P.dot(c[0] - 0.05 * w, c[1] - 0.07 * w, 0.05 * w + 0.03, UI.PAPER, 0.8)
        # 上眼线：内眼角细，外眼角粗、末端微微上挑
        lid = curve(a, m, b, lift=0.10 * w)
        hw = np.interp(np.linspace(0, 1, len(lid)), [0, 0.3, 0.85, 1], [0.06, 0.15, 0.22, 0.08]) * (0.55 + 0.45 * v)
        P.line(lid, hw, JIAO, 1.0, jitter=0.08)
        # 下眼睑：外侧一半的一道淡线
        low = curve(m + np.array([0.0, 0.22 * w]), 0.5 * (m + b) + np.array([0.0, 0.2 * w]), b + np.array([0.0, 0.06 * w]), n=12)
        P.line(low, 0.05 + 0.03 * v, ZHONG, 0.45)
    # 鼻：近侧鼻翼下一小笔
    nt, nb = pt("nose_tip_L"), pt("nose_base_R")
    nose = np.stack([nt + np.array([0.15, -0.35]), nt, 0.5 * (nt + nb)])
    P.line(nose, np.array([0.04, 0.13, 0.07]), nose_ink, 0.9, jitter=0.0)
    # 嘴：一笔，中段略重
    ml, mc, mr = pt("mouth_l_L"), pt("mouth_c_L"), pt("mouth_r_R")
    mouth = curve(mr, mc + np.array([0.0, 0.05]), ml, n=16)
    hw = np.interp(np.linspace(0, 1, len(mouth)), [0, 0.5, 1], [0.04, 0.11, 0.05])
    P.line(mouth, hw, lip, 0.85, jitter=0.0)


def write_meta(img) -> None:
    meta = {
        "name": "ui",
        "generator": "art/render/portrait.py",
        "format": "PNG RGBA，直通（非预乘）alpha；全彩、正常混合、不染色",
        "px_per_unit": S.PX_PER_UNIT,
        "display_px_1x": SIZE,
        "files": {"portrait_hero.png": {"size": [img.width, img.height], "anchor": [0.5, 0.5], "blend": "normal",
                                        "tint": False, "kind": "portrait", "id": "hero", "name": "主角"}},
    }
    (OUT_DIR / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")


def main(argv: list[str]) -> int:
    if "--all" in argv:
        for dens in ("1", "2"):
            env = dict(os.environ, LANTERN_ART_DENSITY=dens)
            subprocess.run([sys.executable, __file__], env=env, check=True)
        return 0
    t0 = time.perf_counter()
    px = int(round(SIZE * D))
    bust = render_bust(px)
    t1 = time.perf_counter()
    img = compose_portrait(bust)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    img.save(OUT_DIR / "portrait_hero.png", optimize=True)
    write_meta(img)
    print(f"[portrait] {px}²：建模 {bust['build_s']:.2f}s，渲染 {bust['render_s']:.2f}s（{bust['render_px']}²，"
          f"{bust['faces']} 面），装框 {time.perf_counter() - t1:.2f}s，共 {time.perf_counter() - t0:.1f}s → "
          f"{OUT_DIR / 'portrait_hero.png'}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
