"""讨封狐（青丘小妖，妖类）：修行到一半的狐狸，夜里装成路人讨一句人话——“你看我像不像人？”

两种样子，同一个模型（按动画显示 / 隐藏两套部件）：
  扮人（disguise）：照见圈外像个赶夜路的人——赭石色的斗笠压得很低，脸藏在帽檐的阴影里（焦墨，只露一点下巴），
      身披三层棕蓑衣（蓑草用边标记画成竖向的细线），露出缠着绑腿的两条腿、草鞋，近手拄一根竹杖。没有发光的眼（扮人时不发光）。
  现形（move）：狐狸用后腿站着，还戴着那顶斗笠，穿一件旧袍子（褪色的麻布、浓墨腰带、赭石补丁），广袖里伸出墨爪拄着竹杖；
      赭石狐脸、白颊白吻、墨鼻头，两只尖耳从斗笠里顶出来，袍子后面拖一条白尖的大尾巴；趾行的狐腿；眼睛 EYE_HEX 发光。
  reveal（现形的过程）：蓑衣从肩上滑落、掉下去，耳朵顶破斗笠、吻部伸长、尾巴从衣摆下甩出来，眼睛一点点亮起来。

动画（只画 E）：disguise 6 帧循环（人的步子）、move 6 帧循环（现形后跑得快，小跑）、reveal 4 帧不循环。
帧 FRAME["golem"]（2 倍 224²），锚点 ANCHOR。挂点 eyes（扮人时在帽檐阴影里脸的位置）、feet。
眼睛颜色 EYE_HEX 不在调色板里，出图时写进 meta.palette_extra。
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import bpy
import numpy as np
from mathutils import Vector

ART = Path(__file__).resolve().parents[1]
for p in (ART, ART / "models"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
from style import bstyle as B  # noqa: E402
from style import style as S  # noqa: E402
import kit as K  # noqa: E402

EYE_HEX = "#FFD23F"  # 现形后的狐眼：亮金
PALETTE_EXTRA = [EYE_HEX]
HEAD_Z = 1.66  # 头心高度（扮人）


def _mark_vertical(ob, keep=0.45, seed=0):
    """蓑衣：竖向（沿下垂方向）的边随机标成 freestyle_edge，画成蓑草的细线。"""
    me = ob.data
    rng = np.random.default_rng(seed)
    attr = me.attributes.get("freestyle_edge") or me.attributes.new("freestyle_edge", "BOOLEAN", "EDGE")
    vals = []
    for e in me.edges:
        v0, v1 = (me.vertices[i].co for i in e.vertices)
        d = v1 - v0
        vals.append(abs(d.z) > 0.7 * d.length and rng.random() < keep)
    attr.data.foreach_set("value", vals)


# ================================================================ 姿态参数
def _state(anim: str, frame: int, n: int) -> dict:
    ph = 2 * math.pi * (frame % max(n, 1)) / max(n, 1)
    st = dict(ph=ph, form="human", cape=1.0, cape_drop=0.0, ears=0.0, snout=0.0, tail=0.0, eyes=0.0,
              lean=4.0, bob=0.0, head_pitch=0.0, stride=1.0, wind=0.15, staff=0.0, hat=0.0)
    if anim == "disguise":  # 人的步子：腿前后交替，身子微起伏，竹杖随步子前后点
        st.update(bob=0.012 * math.cos(2 * ph), staff=5.0 * math.sin(ph), wind=0.18, stride=1.0)
    elif anim == "move":  # 现形：前倾小跑，尾巴甩
        st.update(form="fox", cape=0.0, ears=1.0, snout=1.0, tail=1.0, eyes=1.0, lean=14.0, hat=1.0,
                  bob=0.018 * math.cos(2 * ph), staff=8.0 * math.sin(ph), wind=0.35, stride=1.25,
                  head_pitch=-3.0 + 3.0 * math.sin(2 * ph))
    elif anim == "reveal":
        # (蓑衣下滑, 耳, 吻, 尾, 眼, 前倾, 抬头) —— 第 0 帧还是人（抖一下肩，抬头“问话”），第 3 帧完全现形
        P = [(0.06, 0.00, 0.00, 0.00, 0.00, 2.0, -8.0),
             (0.32, 0.55, 0.55, 0.40, 0.40, 6.0, -5.0),
             (0.80, 1.00, 1.00, 0.85, 1.00, 11.0, -2.0),
             (1.00, 1.00, 1.00, 1.00, 1.00, 14.0, 0.0)][frame % 4]
        st.update(cape_drop=P[0], cape=0.0 if frame % 4 == 3 else 1.0, ears=P[1], snout=P[2], tail=P[3], eyes=P[4],
                  hat=P[1],
                  lean=P[5], head_pitch=P[6], form="human" if frame % 4 == 0 else "fox", stride=0.0, wind=0.5,
                  ph=0.6 + frame)
    return st


# ================================================================ 组装
def build_taofeng_fox():
    I, A = S.INK, S.ACCENT
    from hero import _sleeve_build  # 主角的广袖构造器（下垂的袖兜 + 浓墨袖口）
    from fox import _ear_build

    M = {
        "hat": K.toon("TFHat", S.WASH["zheshi"], edge=0.45, seed=101.0),
        "hat_band": K.toon("TFHatBand", A["zheshi"], seed=102.0),
        "cape": K.toon("TFCape", A["zheshi"], edge=0.35, seed=103.0, bias=-0.18),
        "cape2": K.toon("TFCape2", A["zheshi"], edge=0.35, seed=104.0, bias=-0.40),
        "shadow": B.flat_material("TFShadow", I["jiao"]),
        "skin": K.toon("TFSkin", S.SKIN, edge=0.3, seed=105.0, bias=-0.35),
        "legging": K.toon("TFLegging", I["nong"], edge=0.3, seed=106.0),
        "sandal": K.toon("TFSandal", A["zheshi"], seed=107.0),
        "staff": K.toon("TFStaff", S.WASH["tenghuang"], edge=0.4, seed=108.0),
        "fur": K.toon("TFFur", A["zheshi"], edge=0.45, seed=109.0),
        "legfur": K.toon("TFLegFur", A["zheshi"], edge=0.3, seed=114.0, bias=0.25),  # 细腿上提亮，免得像靴子
        "white": K.toon("TFWhite", ramp=[S.PAPER, I["qing"], I["dan"]], edge=0.35, seed=110.0),
        "robe": K.toon("TFRobe", S.WASH["huaqing"], edge=0.4, seed=111.0),  # 褪了色的花青旧袍
        "robe_dark": K.toon("TFRobeDark", I["nong"], seed=112.0),
        "patch": K.toon("TFPatch", S.WASH["zheshi"], seed=113.0),
        "ink": B.flat_material("TFInk", I["jiao"]),
    }
    eye = B.emissive_material("TFEye", EYE_HEX, 1.0)
    root = B.empty("TFRoot")
    yaw = K.yaw_pivot("TFYaw", root, -22)
    body = B.empty("TFBody", yaw)
    parts = {"root": root, "body": body, "M": M, "groups": {"human": [], "fox": []}, "dyn": {}}
    obj = B.mesh_object
    G = parts["groups"]

    # ---- 上身：一个前倾的枢轴（腰），头、帽、袖、蓑衣都挂在上面
    waist = B.empty("TFWaist", body, loc=(0, 0.04, 0.95))
    parts["waist"] = waist
    # 旧袍（现形）：上身 + 腰带 + 补丁；下摆每帧重建
    G["fox"].append(obj("TFChest", B.lathe([(0.15, 0.0), (0.17, 0.18), (0.20, 0.42), (0.22, 0.55), (0.17, 0.64),
                                             (0.08, 0.70), (0.0, 0.71)], 20, scale_y=0.78), M["robe"], "outer", waist,
                        sharp_deg=0))
    G["fox"].append(obj("TFSash", B.lathe([(0.168, 0.0), (0.178, 0.05), (0.168, 0.10)], 20, scale_y=0.82),
                        M["robe_dark"], "inner", waist, loc=(0, 0, 0.04)))
    G["fox"].append(obj("TFPatch", K.ellipsoid((0.07, 0.03, 0.06), 10, 6), M["patch"], "inner", waist,
                        loc=(-0.12, -0.13, 0.36), rot=(0, 0, math.radians(30))))
    for sx in (-1, 1):  # 交领
        pts = [Vector((0.07 * sx, -0.11, 0.66)), Vector((0.02 * sx, -0.165, 0.52)), Vector((-0.06 * sx, -0.165, 0.36))]
        G["fox"].append(obj(f"TFCollar{sx:+d}", K.strip_build(pts, 0.045, 0.012, side_hint=Vector((1, 0, 0)),
                                                              taper=(1.0, 0.8)), M["robe_dark"], "inner", waist))
    skirt = []
    for i, (c, w, ln) in enumerate(((-90, 100, 0.50), (90, 110, 0.52), (0, 70, 0.48), (180, 70, 0.48))):
        ob = obj(f"TFSkirt{i}", K.grid_build(K.rag_panel_rows(c, w, 0.18, 1.0, ln, seed=i + 3, tatter=0.25)),
                 M["robe"], "outer", body, loc=(0, 0.04, 0), sharp_deg=0)
        skirt.append((ob, c, w, i, ln))
        G["fox"].append(ob)
    parts["skirt"] = skirt
    # 蓑衣（扮人）：三层棕草，每帧重建
    cape = []
    for i, (zt, r, ln, fl, mat) in enumerate(((0.60, 0.15, 0.46, 0.13, "cape"), (0.34, 0.23, 0.50, 0.10, "cape2"),
                                               (0.02, 0.28, 0.56, 0.08, "cape"))):
        ob = obj(f"TFCape{i}", lambda bm: None, M[mat], "outer", waist, sharp_deg=0)
        cape.append((ob, zt, r, ln, fl, i))
        G["human"].append(ob)
    parts["cape"] = cape
    # ---- 头（挂在腰上，随前倾）
    head = B.empty("TFHead", waist, loc=(0, -0.06, HEAD_Z - 0.95))
    parts["head"] = head
    # 斗笠：宽檐尖顶，篾条用边标记画出放射线
    hatp = B.empty("TFHatPivot", head, loc=(0, 0.0, 0.08))  # 现形时斗笠被耳朵顶得往后仰
    parts["hat"] = hatp
    hat = obj("TFHat", B.lathe([(0.37, 0.0), (0.34, 0.025), (0.22, 0.085), (0.10, 0.15), (0.03, 0.19), (0.0, 0.205)],
                               32, radial=lambda th, z: 1 + 0.012 * math.cos(16 * th)), M["hat"], "outer", hatp,
              sharp_deg=0)
    me = hat.data
    attr = me.attributes.new("freestyle_edge", "BOOLEAN", "EDGE")
    attr.data.foreach_set("value", [(i % 4 == 0) for i in range(len(me.edges))])
    obj("TFHatBand", B.lathe([(0.115, 0.0), (0.125, 0.02), (0.115, 0.04)], 24), M["hat_band"], "inner", hatp,
        loc=(0, 0.0, -0.04))
    # 扮人的脸：帽檐下的一团阴影 + 一点下巴
    G["human"].append(obj("TFFaceShadow", K.ellipsoid((0.105, 0.075, 0.115), 16, 10), M["shadow"], "inner", head,
                          loc=(0, -0.03, -0.02)))
    G["human"].append(obj("TFChin", K.ellipsoid((0.065, 0.05, 0.04), 12, 8), M["skin"], "inner", head,
                          loc=(0, -0.07, -0.10)))
    # 现形的狐头：赭石头骨、白颊白吻、墨鼻头；吻和耳朵挂在各自的枢轴上（现形时伸长 / 顶出来）
    fox_head = []
    fox_head.append(obj("TFSkull", K.ellipsoid((0.14, 0.145, 0.13), 18, 12), M["fur"], "outer", head,
                        loc=(0, 0.0, 0.0)))
    fox_head.append(obj("TFCheeks", K.ellipsoid((0.135, 0.10, 0.085), 16, 10), M["white"], "outer", head,
                        loc=(0, -0.07, -0.07)))
    snout = B.empty("TFSnoutPivot", head, loc=(0, -0.10, -0.045))
    parts["snout"] = snout
    fox_head.append(obj("TFSnout", K.tube_build(K.curve_points((0, 0.0, 0.0), (0, -0.24, -0.03), n=6),
                                                lambda t: 0.078 * (1 - t) ** 0.75 + 0.014, 12, flat=0.8),
                        M["fur"], "outer", snout))
    fox_head.append(obj("TFJaw", K.tube_build(K.curve_points((0, 0.0, -0.035), (0, -0.20, -0.06), n=6),
                                              lambda t: 0.058 * (1 - t) ** 0.8 + 0.008, 10, flat=0.6),
                        M["white"], "outer", snout))
    fox_head.append(obj("TFNose", K.ellipsoid((0.026, 0.021, 0.021), 10, 6), M["ink"], "none", snout,
                        loc=(0, -0.245, -0.025)))
    ears = []
    for sx in (-1, 1):  # 耳朵从斗笠里顶出来（耳尖墨色）
        piv = B.empty(f"TFEarPivot{sx:+d}", head, loc=(0.085 * sx, -0.01, 0.07))
        base, tip = Vector((0, 0, 0)), Vector((0.10 * sx, -0.02, 0.44))
        e1 = obj(f"TFEar{sx:+d}", _ear_build(base, tip, 0.085, 0.040, Vector((0.4 * sx, -0.9, 0))), M["fur"], "outer",
                 piv, sharp_deg=0)
        e2 = obj(f"TFEarTip{sx:+d}", _ear_build(base.lerp(tip, 0.70), tip + Vector((0.004 * sx, -0.004, 0.01)), 0.03,
                                                0.022, Vector((0.4 * sx, -0.9, 0))), M["ink"], "none", piv, sharp_deg=0)
        fox_head += [e1, e2]
        ears.append(piv)
    parts["ears"] = ears
    G["fox"] += fox_head
    eyes = B.empty("TFEyes", head, loc=(0, 0, 0))
    parts["eyes"] = eyes
    K.slit_eyes("TF", eyes, Vector((0, -0.132, 0.015)), 0.12, (0.040, 0.014, 0.015), eye, tilt_deg=20)
    sock = B.empty("TFSocketEyes", head, loc=(0, -0.135, 0.0))
    # ---- 手臂：现形是两只广袖 + 墨爪；扮人只从蓑衣前面伸出一只拄杖的手
    for sx, nm in ((-1, "Near"), (1, "Far")):
        sh = B.empty(f"TFShoulder{nm}", waist, loc=(0.19 * sx, -0.02, 0.52))
        cuff = Vector((0.04 * sx, -0.24, -0.30)) if nm == "Near" else Vector((0.06 * sx, -0.06, -0.40))
        G["fox"].append(obj(f"TFSleeve{nm}", _sleeve_build(Vector((0, 0, 0)), cuff,
                                                           [(0.0, 0.065), (0.4, 0.085), (1.0, 0.13)], 0.20),
                            [M["robe"], M["robe_dark"], M["robe_dark"]], "outer", sh, sharp_deg=0))
        G["fox"].append(obj(f"TFPaw{nm}", K.ellipsoid((0.045, 0.05, 0.05), 10, 8), M["robe_dark"], "inner", sh,
                            loc=cuff + Vector((0, -0.03, -0.04))))
        parts[f"sh_{nm}"] = sh
    G["human"].append(obj("TFHandSleeve", K.tube_build([Vector((-0.20, -0.12, 0.30)), Vector((-0.22, -0.22, 0.24))],
                                                       lambda t: 0.055, 10), M["legging"], "inner", waist))
    G["human"].append(obj("TFHand", K.ellipsoid((0.045, 0.05, 0.05), 10, 8), M["skin"], "inner", waist,
                          loc=(-0.22, -0.27, 0.23)))
    # 竹杖：拄在身前，跟着近手
    staff = B.empty("TFStaffPivot", body, loc=(-0.22, -0.28, 0.0))
    parts["staff"] = staff
    obj("TFStaff", K.tube_build([Vector((0, 0, 0.02)), Vector((0, 0, 1.42))], lambda t: 0.024, 8), M["staff"], "thin",
        staff)
    for z in (0.40, 0.80, 1.20):
        obj(f"TFStaffNode{int(z * 100)}", B.cylinder(0.03, 0.03, 0.02, 8), M["robe_dark"], "none", staff, loc=(0, 0, z))
    # ---- 腿：扮人是缠绑腿的人腿 + 草鞋；现形是趾行的狐腿 + 墨爪
    for sx, nm in ((1, "L"), (-1, "R")):
        hip = B.empty(f"TFHip{nm}", body, loc=(0.10 * sx, 0.04, 0.93))
        knee = B.empty(f"TFKnee{nm}", hip, loc=(0, -0.02, -0.44))
        G["human"].append(K.limb(f"TFThigh{nm}", (0, 0, 0), (0, -0.02, -0.44), 0.075, 0.06, M["legging"], "outer", hip))
        G["human"].append(K.limb(f"TFShin{nm}", (0, 0, 0), (0, 0.02, -0.44), 0.058, 0.045, M["legging"], "outer", knee))
        G["human"].append(obj(f"TFSandal{nm}", K.ellipsoid((0.055, 0.11, 0.03), 10, 6), M["sandal"], "outer", knee,
                              loc=(0, -0.04, -0.47)))
        fhip = B.empty(f"TFFoxHip{nm}", body, loc=(0.10 * sx, 0.10, 0.92))
        fknee = B.empty(f"TFFoxKnee{nm}", fhip, loc=(0.0, -0.18, -0.30))
        G["fox"].append(K.limb(f"TFFoxThigh{nm}", (0, 0, 0), (0.0, -0.18, -0.30), 0.085, 0.055, M["fur"], "outer", fhip))
        G["fox"].append(K.limb(f"TFFoxShin{nm}", (0, 0, 0), (0, 0.25, -0.30), 0.045, 0.030, M["legfur"], "outer",
                               fknee))
        G["fox"].append(K.limb(f"TFFoxFoot{nm}", (0, 0.25, -0.30), (0, 0.06, -0.60), 0.028, 0.022, M["legfur"],
                               "outer", fknee))
        G["fox"].append(obj(f"TFFoxPaw{nm}", K.ellipsoid((0.035, 0.07, 0.028), 10, 6), M["robe_dark"], "outer", fknee,
                            loc=(0, 0.02, -0.612)))
        parts[f"hip_{nm}"], parts[f"knee_{nm}"] = hip, knee
        parts[f"fhip_{nm}"], parts[f"fknee_{nm}"] = fhip, fknee
    # ---- 尾巴（现形）：赭石大尾，白尖；每帧重建
    tail = obj("TFTail", lambda bm: None, [M["fur"], M["white"]], "outer", body, sharp_deg=0)
    parts["tail"] = tail
    G["fox"].append(tail)
    sockets = {"eyes": sock, "feet": B.empty("TFFeet", root)}
    parts["sockets"] = sockets
    pose_taofeng_fox(parts, "disguise", 0, 6)
    return root, parts, sockets


def _tail_pts(st):
    ph = st["ph"]
    ln = 0.95 * max(st["tail"], 0.05)
    root = Vector((0, 0.24, 0.80))
    pts = []
    for i in range(12):
        t = i / 11
        p = root + Vector((0, 0.55 * ln * t, -0.42 * ln * t + 0.75 * ln * t * t))
        p += Vector((0.06 * t * t * math.sin(ph - 2.0 * t), 0.05 * t * t * math.sin(ph - 1.5 * t + 1.0), 0))
        pts.append(p)
    return pts


def pose_taofeng_fox(parts, anim, frame, n):
    st = _state(anim, frame, n)
    ph = st["ph"]
    human = st["form"] == "human"
    for ob in parts["groups"]["human"]:
        ob.hide_render = not human
    for ob in parts["groups"]["fox"]:
        ob.hide_render = human
    # 蓑衣：扮人时整件穿着；现形的过程中往下滑（掉到地上），第 3 帧没了
    for ob, zt, r, ln, fl, i in parts["cape"]:
        vis = st["cape"] > 0
        ob.hide_render = not vis
        if not vis:
            continue
        drop = st["cape_drop"]
        rows = K.rag_panel_rows(0, 360, r, zt, ln, phase=ph + i, wind=st["wind"], flare=fl, tatter=0.35,
                                seed=20 + i, nu=24, nv=7, sy=0.82, center=Vector((0, 0.02, 0)))
        if drop > 0:  # 整件往下滑、往后坠，碰到地面就堆起来（往外摊一点）
            floor = -0.93
            for row in rows:
                for p in row:
                    z0 = p.z - drop * 0.95
                    if z0 < floor:
                        out = Vector((p.x, p.y, 0))
                        out = out.normalized() if out.length > 1e-4 else Vector((0, 1, 0))
                        p.xy += (out * (floor - z0) * 0.35).xy
                        z0 = floor + (z0 - floor) * -0.12
                    p.z = z0
                    p.y += drop * 0.14
        K.replace_mesh(ob, K.grid_build(rows))
        _mark_vertical(ob, keep=0.5, seed=30 + i)
        ob.hide_render = False
    # 袍子下摆
    if not human:
        for ob, c, w, i, ln in parts["skirt"]:
            K.replace_mesh(ob, K.grid_build(K.rag_panel_rows(c, w, 0.18, 1.0, ln, phase=ph, wind=st["wind"], seed=i + 3,
                                                             tatter=0.25)))
    # 上身前倾、起伏；头俯仰
    parts["body"].location.z = st["bob"]
    parts["waist"].rotation_euler = (math.radians(st["lean"]), 0, 0)
    parts["head"].rotation_euler = (math.radians(st["head_pitch"] - st["lean"] * 0.4), 0, math.radians(-14))
    parts["hat"].location = (0, 0.03 * st["hat"], 0.08 + 0.05 * st["hat"])
    parts["hat"].rotation_euler = (math.radians(-6 - 24 * st["hat"]), 0, 0)
    # 狐头的渐变：吻伸长、耳朵顶出来、眼睛睁开
    parts["snout"].scale = (1.0, max(0.05, st["snout"]), 1.0)
    for piv in parts["ears"]:
        piv.scale = (1.0, 1.0, max(0.05, st["ears"]))
    parts["eyes"].scale = (1.0, 1.0, max(0.02, st["eyes"]))
    for ob in parts["eyes"].children:
        ob.hide_render = st["eyes"] <= 0.01
    # 腿：扮人是人的步子；现形是趾行的小跑；reveal 原地站定
    s_amp = 20.0 * st["stride"]
    for nm, sgn in (("L", 1), ("R", -1)):
        s = sgn * math.sin(ph)
        parts[f"hip_{nm}"].rotation_euler = (math.radians(-s_amp * s), 0, 0)
        parts[f"knee_{nm}"].rotation_euler = (math.radians(s_amp * 1.1 * max(0.0, s)), 0, 0)
        parts[f"fhip_{nm}"].rotation_euler = (math.radians(-s_amp * 1.1 * s + (8 if anim == "reveal" else 0)), 0, 0)
        parts[f"fknee_{nm}"].rotation_euler = (math.radians(s_amp * 0.8 * max(0.0, -s) + 4), 0, 0)
    for nm, sgn in (("Near", 1), ("Far", -1)):
        if f"sh_{nm}" in parts:
            parts[f"sh_{nm}"].rotation_euler = (math.radians(6 * sgn * math.sin(ph) * st["stride"]), 0, 0)
    parts["staff"].rotation_euler = (math.radians(-6 + st["staff"]), 0, 0)
    # 尾巴
    if not human:
        tail = parts["tail"]
        K.replace_mesh(tail, K.tube_build(_tail_pts(st), K.bushy(0.13 * (0.6 + 0.4 * st["tail"]), peak=0.5), 12,
                                          zones=lambda t: 1 if t > 0.80 else 0))
    bpy.context.view_layer.update()
