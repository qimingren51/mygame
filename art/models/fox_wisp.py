"""狐火（青丘小妖，妖类）：狐狸形状的青色鬼火。

造型：一团青火烧成一只奔跑的狐狸——尖耳、尖吻、细腰、四条化成火舌的腿，背上一排往上窜、一帧一帧长短跳动的火舌
（火焰纹：S 形、收尖、尖端回勾），火尾往后甩，尾尖散成几缕越飘越透明的余火（不描线）。
火身是近白的火芯，越靠轮廓、越往火舌尖越青、越暗（kit.flame_material：沿 fade 分段 + 轮廓 rim）。
整团火都在发光遮罩里：夜里芯亮边暗地淡淡发光（produce.py 出图后调 finish_flame()：按亮度把发光层里火身的 alpha 压到 FLAME_EMIT_ALPHA），
两只细长的眼嵌在焦墨眼眶里，最亮。墨线只用细线（thin），和墨烟幽灵（影妖、疾影）的粗外轮廓区分开。

动画：
  float  8 帧循环：悬在半空做“空中奔跑”——四腿交替伸缩，身体起伏，火舌和火尾的波沿长度向后窜。
  pounce 4 帧不循环：0–1 蓄力（身体压短、拱背、头压低，火往后收；第 1 帧最紧，游戏在预警期间停在这一帧），
         2–3 扑出（身体拉长前探，前腿前伸、后腿后蹬，火尾和火舌拉直向后）。
帧 FRAME["small"]（2 倍 160²），锚点 ANCHOR，悬浮。挂点 eyes（两眼之间）、feet（原点）。
颜色：BANDS（火身三段 × 三档）、EYE_HEX（眼）都不在 style.py 的调色板里，出图时写进 meta.palette_extra。

    root, parts, sockets = build_fox_wisp()
    pose_fox_wisp(parts, "float", i, 8)
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import bpy
from mathutils import Matrix, Vector

ART = Path(__file__).resolve().parents[1]
for p in (ART, ART / "models"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
from style import bstyle as B  # noqa: E402
from style import style as S  # noqa: E402
import kit as K  # noqa: E402

# 沿 fade 属性分段：火根（身体）→ 火舌中段 → 火舌尖。每段三档（亮, 中, 暗）
# 火芯近白，往外（轮廓、火舌）是青，火舌尖是发暗的深青——亮度拉开，游戏大小下也读得出“一团火”
BANDS = [(0.0, ("#E6FCF5", "#BDEEE2", "#8FD6C6")),
         (0.56, ("#7CCBBE", "#58AFA6", "#3F8C88")),
         (0.84, ("#3E8A87", "#2F6E72", "#25555E"))]
EYE_HEX = "#F2FFFC"  # 眼：近白的青光
PALETTE_EXTRA = [c for _, r in BANDS for c in r] + [EYE_HEX]
FLAME_EMIT_ALPHA = (0.16, 0.42)  # 发光层里火身的强度：最暗的深青 → 最亮的火芯（眼睛保持 1）；见 finish_flame()
FORWARD = -0.11  # 身体整体前移（米）：火尾往后甩也不出框


def _rot(v, axis, deg):
    return Matrix.Rotation(math.radians(deg), 3, axis) @ Vector(v)


# ================================================================ 姿态参数
def _state(anim: str, frame: int, n: int) -> dict:
    """一帧的姿态参数。ph 是循环相位（火舌、尾巴的波沿长度往后传）。"""
    ph = 2 * math.pi * (frame % max(n, 1)) / max(n, 1)
    st = dict(ph=ph, bob=0.0, stretch=1.0, arch=0.0, crouch=0.0, head_dy=0.0, head_dz=0.0, head_pitch=0.0,
              ear_back=0.0, tail_lift=0.0, tail_len=1.0, sweep=0.0, tongue_len=1.0, body_dy=0.0,
              legs={"FL": 0.0, "FR": 0.0, "HL": 0.0, "HR": 0.0}, leg_ext=1.0)
    if anim == "float":
        st["bob"] = 0.03 * math.sin(ph)
        st["arch"] = 0.015 * math.sin(ph + 0.8)
        g = math.sin(ph)  # 空中奔跑：前后腿反相（左右略错开）
        st["legs"] = {"FL": 0.8 * g, "FR": 0.8 * math.sin(ph + 0.6), "HL": -0.8 * g, "HR": -0.8 * math.sin(ph + 0.6)}
        st["tail_lift"] = 0.05 * math.sin(ph - 1.0)
        st["head_dz"] = 0.010 * math.sin(ph + 1.2)
        st["head_pitch"] = 2.0 * math.sin(ph + 1.2)
    elif anim == "pounce":
        # (伸长, 拱背, 压低, 头前后, 头高低, 头俯仰, 耳后贴, 尾抬, 尾长, 火往后扫, 火舌长, 身体前后, 腿, 腿长)
        # 腿：-1 收在身下 / +1 前腿前伸、后腿后蹬
        P = [
            (0.88, 0.05, 0.12, 0.03, -0.04, 12, 0.5, 0.10, 0.92, 0.45, 0.85, 0.07, -0.6, 0.85),
            (0.78, 0.09, 0.20, 0.05, -0.08, 20, 1.0, 0.18, 0.86, 0.75, 0.78, 0.11, -1.0, 0.75),  # 蓄力到底（预警时停在这）
            (1.16, -0.02, -0.03, -0.05, 0.01, -6, 0.9, -0.10, 0.92, 1.00, 1.05, 0.01, 1.0, 1.05),  # 扑出
            (1.12, 0.00, -0.02, -0.04, -0.01, 2, 0.7, -0.05, 0.92, 0.85, 1.00, 0.01, 0.7, 1.02),
        ][frame % 4]
        (st["stretch"], st["arch"], st["crouch"], st["head_dy"], st["head_dz"], st["head_pitch"], st["ear_back"],
         st["tail_lift"], st["tail_len"], st["sweep"], st["tongue_len"], st["body_dy"], legs, st["leg_ext"]) = P
        st["legs"] = {"FL": legs, "FR": legs * 0.85, "HL": -legs, "HR": -legs * 0.85}
        st["ph"] = 2 * math.pi * frame / 4 + 0.6
    return st


# ================================================================ 几何（每帧重建）
def _smooth(pts, n=12):
    """折线 → Catmull-Rom 平滑点列。"""
    pts = [Vector(p) for p in pts]
    P = [pts[0] * 2 - pts[1], *pts, pts[-1] * 2 - pts[-2]]
    out = []
    segs = len(pts) - 1
    for k in range(n):
        u = k / (n - 1) * segs
        i = min(int(u), segs - 1)
        t = u - i
        p0, p1, p2, p3 = P[i], P[i + 1], P[i + 2], P[i + 3]
        out.append(0.5 * ((2 * p1) + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t * t
                          + (-p0 + 3 * p1 - 3 * p2 + p3) * t ** 3))
    return out


def _spine(st):
    """身体脊线（身体坐标，前 = -Y）：颈根 → 胸 → 腰 → 臀 → 尾根。奔跑的狐狸胸高臀低一点，头抬着。"""
    L = 0.50 * st["stretch"]
    zc = 0.62 - st["crouch"] * 0.50
    a, c = st["arch"], st["crouch"]
    return [Vector((0, -0.52 * L + st["head_dy"] * 0.5, zc + 0.10 - c * 0.20)), Vector((0, -0.30 * L, zc + 0.04 - c * 0.06)),
            Vector((0, 0.0, zc + a + 0.01)), Vector((0, 0.28 * L, zc + a * 0.5)), Vector((0, 0.50 * L, zc + 0.02 + c * 0.10))]


def _body_radius(t):
    return float(0.080 + 0.072 * math.sin(math.pi * min(1.0, t * 1.12)) ** 0.6 - 0.022 * max(0.0, t - 0.55))


def _tongue_pts(base, d, length, ph, curl=0.6, wave=0.035, n=9, up=Vector((0, 0, 1))):
    """一条火舌（火焰纹）：从 base 沿 d 窜出，S 形摆动，尖端回勾（curl>0 往“上”勾）。"""
    d = Vector(d).normalized()
    side = d.cross(up)
    side = side.normalized() if side.length > 1e-4 else Vector((1, 0, 0))
    nrm = side.cross(d).normalized()
    pts = []
    for i in range(n):
        t = i / (n - 1)
        p = Vector(base) + d * (length * t)
        p += nrm * (wave * math.sin(2.0 * math.pi * t - ph) * t)
        p += nrm * (curl * length * 0.32 * t ** 3)
        pts.append(p)
    return pts


def _tongue_r(r0):
    return lambda t: r0 * (1 - t) ** 0.9 * (1 + 0.30 * math.sin(math.pi * t))


def _at(pts, t):
    i = t * (len(pts) - 1)
    k = min(int(i), len(pts) - 2)
    return pts[k].lerp(pts[k + 1], i - k)


def _shapes(st):
    """全部火形：{名字: (点列, 半径函数, 截面扁度, fade 起点, fade 终点)}，点在身体坐标里；另有 _head（头心位置）。"""
    ph, sw = st["ph"], st["sweep"]
    sp = _spine(st)
    body = _smooth(sp, 14)
    out = {"Body": (body, _body_radius, 0.92, 0.0, 0.30)}
    neck, chest, hip, rump = sp[0], sp[1], sp[3], sp[4]
    out["_head"] = neck + Vector((0, -0.10 + st["head_dy"] * 0.5, 0.07 + st["head_dz"]))
    # 尾巴：从臀后出发，向后、略向上弧起，尖端回卷成火苗；扫（sweep）越大越平直向后
    tl = 0.40 * st["tail_len"]
    lift = 0.26 + st["tail_lift"] - 0.22 * sw
    tdir = Vector((0, math.cos(lift), math.sin(lift))).normalized()
    tail = []
    for i in range(13):
        t = i / 12
        p = rump + tdir * (tl * t) + Vector((0, 0, 0.12 * tl * math.sin(math.pi * t) * (1 - sw * 0.6)))
        p += Vector((0.05 * t * t * math.sin(ph - 2.4 * t), 0, 0.045 * t * t * math.sin(ph - 2.0 * t + 0.7)))
        p += Vector((0, -0.06 * t ** 3 * (1 - sw), 0.12 * t ** 3 * (1 - sw)))  # 尖端回卷向上
        tail.append(p)
    out["Tail"] = (tail, K.bushy(0.118, peak=0.40), 0.85, 0.30, 0.95)
    # 腿：火舌状，根部粗；s>0 腿尖朝前（-Y），s<0 朝后；腿尖拖一点往后飘的火
    for nm, base, front in (("FL", chest + Vector((0.05, -0.02, -0.06)), True),
                            ("FR", chest + Vector((-0.05, 0.02, -0.06)), True),
                            ("HL", hip + Vector((0.05, 0.0, -0.05)), False),
                            ("HR", hip + Vector((-0.05, 0.03, -0.05)), False)):
        s = st["legs"][nm]
        d = _rot(Vector((0, 0, -1)), (1, 0, 0), -48 * s)
        ln = 0.25 * st["leg_ext"] * (0.85 + 0.15 * abs(s))
        mid = base + d * ln * 0.55
        tip = base + d * ln
        trail = tip + Vector((0, 0.09, 0.02)) * (0.6 + 0.4 * abs(s)) * (1 + 0.6 * sw)
        out[f"Leg{nm}"] = (_smooth([base, mid, tip, trail], 9), lambda t: 0.050 * (1 - t) ** 0.85 + 0.002, 0.8, 0.30, 1.0)
    # 背上一排往上窜的火舌：从肩、背、腰、臀窜出，向后上方，S 形、尖端回勾，长短一帧一帧地跳（火苗在烧）
    for k, (t, r0, ln, a) in enumerate([(0.06, 0.050, 0.22, 58), (0.26, 0.058, 0.31, 50), (0.46, 0.056, 0.28, 44),
                                        (0.66, 0.052, 0.30, 40), (0.86, 0.046, 0.24, 36)]):
        p = _at(body, t)
        base = p + Vector((0.012 * (k % 2 * 2 - 1), 0, _body_radius(t) * 0.62))
        aa = math.radians(a - 26 * sw)
        d = Vector((0.05 * math.sin(k * 2.3), math.cos(aa), math.sin(aa)))
        flick = 1 + 0.28 * math.sin(ph * 2 + k * 2.1) * (1 - 0.6 * sw)
        out[f"Tongue{k}"] = (_tongue_pts(base, d, ln * st["tongue_len"] * flick, ph * 2 + k * 1.3, curl=0.75 - 0.4 * sw,
                                         wave=0.045), _tongue_r(r0), 0.7, 0.30, 1.0)
    # 尾上的火舌和分叉的尾尖（往上窜）
    for k, (t, r0, ln, a) in enumerate([(0.36, 0.052, 0.26, 58), (0.64, 0.048, 0.26, 50), (0.92, 0.044, 0.24, 66),
                                        (0.92, 0.036, 0.20, 18)]):
        p = _at(tail, t)
        base = p + Vector((0, 0, 0.05 if k < 2 else 0.0))
        aa = math.radians(a - 34 * sw)
        d = Vector((0.07 * math.sin(k * 1.7 + 1), math.cos(aa), math.sin(aa)))
        flick = 1 + 0.25 * math.sin(ph * 2 + 1.3 + k * 1.9) * (1 - 0.6 * sw)
        out[f"TailTongue{k}"] = (_tongue_pts(base, d, ln * st["tongue_len"] * flick, ph * 2 + 0.8 + k * 1.1,
                                             curl=0.7 - 0.4 * sw, wave=0.045), _tongue_r(r0), 0.7, 0.40, 1.0)
    # 尾尖散开的几缕余火（不描线、越往尖越透明）：从尾尖往后上方飘，一帧一帧往后传
    tip, pre = tail[-1], tail[-3]
    for k, (a, ln, side) in enumerate(((52, 0.26, -0.05), (30, 0.30, 0.04), (74, 0.22, 0.02))):
        aa = math.radians(a - 30 * sw)
        d = Vector((side, math.cos(aa), math.sin(aa)))
        base = tip.lerp(pre, 0.3 * k)
        ln *= (1 - 0.45 * sw) * (1 + 0.3 * math.sin(ph + k * 2.2))
        out[f"Wisp{k}"] = (_tongue_pts(base, d, ln, ph * 1.5 + k * 2.0, curl=0.3,
                                       wave=0.05), lambda t: 0.032 * (1 - t) ** 0.7 + 0.002, 0.8, 0.0, 1.0)
    # 腹下的小火舌（向后下飘），让下沿也是火
    for k, (t, a, ln) in enumerate(((0.32, -168, 0.14), (0.62, -172, 0.15))):
        base = _at(body, t) + Vector((0, 0, -_body_radius(t) * 0.7))
        aa = math.radians(a + 8 * sw)
        d = Vector((0, -math.cos(aa), math.sin(aa)))
        out[f"Belly{k}"] = (_tongue_pts(base, d, ln * st["tongue_len"], ph + 2.0 + k, curl=-0.4, wave=0.025),
                            _tongue_r(0.032), 0.7, 0.40, 1.0)
    return out


def _head_parts(st):
    """头部各件（头坐标：原点在头心，面朝 -Y）：吻、两耳（耳尖往后勾，像火苗）、额顶一条往后窜的火舌。"""
    eb = st["ear_back"]
    out = {}
    out["Snout"] = (_smooth([Vector((0, -0.03, -0.012)), Vector((0, -0.13, -0.036)), Vector((0, -0.215, -0.052))], 7),
                    lambda t: 0.070 * (1 - t) ** 0.8 + 0.004, 0.85, 0.0, 0.25)
    for sx in (-1, 1):
        base = Vector((0.058 * sx, 0.025, 0.055))
        tip = base + _rot(Vector((0.035 * sx, 0.035, 0.175)), (1, 0, 0), -35 * eb)
        mid = base.lerp(tip, 0.55) + Vector((0.012 * sx, 0, 0.01))
        tipc = tip + _rot(Vector((0, 0.045, 0.015)), (1, 0, 0), -20 * eb)
        out[f"Ear{sx:+d}"] = (_smooth([base, mid, tip, tipc], 9), lambda t: 0.056 * (1 - t) ** 0.75 + 0.002, 0.55,
                              0.10, 0.95)
    crest = _tongue_pts(Vector((0, 0.04, 0.07)), Vector((0, 0.85, 0.45)), 0.20, st["ph"] + 2.6, curl=0.5)
    out["Crest"] = (crest, _tongue_r(0.034), 0.7, 0.35, 1.0)
    return out


def _set(ob, pts, rfn, flat, t0, t1):
    """重建一条火形的网格，fade 属性 = 沿长度从 t0 到 t1（火身分段上色用）。"""
    fades: list = []
    K.replace_mesh(ob, K.tube_build(pts, rfn, 12, flat=flat, fades=fades))
    B.set_point_attr(ob, "fade", [t0 + (t1 - t0) * f for f in fades])


def finish_flame(frame_png, k=FLAME_EMIT_ALPHA) -> None:
    """出图后处理一帧（<帧>.png 和 <帧>_emit.png 一起改；每帧只能调一次）：
    1. 火身像素硬吸附到最近的火色（BANDS）：管线不吸附发光像素，火芯和深青反差大，分段边界缩小后会留下一圈
       调色板外的过渡色；火身内部的分界本来就是水墨的硬边，吸附后自检的调色板比例才够；
    2. 发光层里火身的 alpha 按亮度从 k[0]（最暗的深青）到 k[1]（最亮的火芯）压暗，眼睛保持原样
       （按颜色分：离眼睛色近的算眼，离火身色近的算火身，过渡像素按比例插值）。"""
    import numpy as np
    from PIL import Image

    frame_png = Path(frame_png)
    emit_png = frame_png.with_name(frame_png.stem + "_emit.png")
    im = np.asarray(Image.open(frame_png).convert("RGBA")).astype(np.float32)
    em = np.asarray(Image.open(emit_png).convert("RGBA")).astype(np.float32)
    flames = np.array([S.hex_to_rgb(c) for _, r in BANDS for c in r], np.float32)
    eye = np.array(S.hex_to_rgb(EYE_HEX), np.float32)

    def nearest(rgb):
        d = np.sqrt(((rgb[..., None, :] - flames) ** 2).sum(-1))
        return flames[d.argmin(-1)], d.min(-1)

    d_eye = np.sqrt(((em[..., :3] - eye) ** 2).sum(-1))
    near, d_body = nearest(em[..., :3])
    w = np.clip(d_body / np.maximum(d_eye + d_body, 1e-6), 0, 1)  # 1 = 眼，0 = 火身
    w = w * w * (3 - 2 * w)
    body = (em[..., 3] > 0.6 * 255) & (w < 0.5)  # 发光层里实在的火身像素（墨线处发光 alpha 已经扣掉）
    em[..., :3] = np.where(body[..., None], near, em[..., :3])
    snap, _ = nearest(im[..., :3])
    im[..., :3] = np.where(body[..., None], snap, im[..., :3])
    lums = flames.mean(-1)
    lt = np.clip((em[..., :3].mean(-1) - lums.min()) / (lums.max() - lums.min()), 0, 1)
    kb = k[0] + (k[1] - k[0]) * lt
    em[..., 3] *= kb + (1 - kb) * w
    Image.fromarray(np.clip(im + 0.5, 0, 255).astype(np.uint8), "RGBA").save(frame_png, optimize=True)
    Image.fromarray(np.clip(em + 0.5, 0, 255).astype(np.uint8), "RGBA").save(emit_png, optimize=True)


# ================================================================ 组装
def build_fox_wisp():
    I = S.INK
    flame = K.flame_material("FoxWispFlame", BANDS, seed=71.0, noise_amt=0.08, rim=1.0, rim_power=1.3)
    wisp = B.smoke_material("FoxWispTrail", list(BANDS[1][1]), fade_start=0.05, fade_power=1.0, noise_amt=0.5,
                            seed=72.0, edge=0.0, wash=0.25)
    wisp["emissive"] = BANDS[1][1][0]
    wisp["emit_strength"] = 1.0
    eye = B.emissive_material("FoxWispEye", EYE_HEX, 1.0)
    socket_m = B.flat_material("FoxWispSocket", I["jiao"])
    root = B.empty("FoxWispRoot")
    yaw = K.yaw_pivot("FoxWispYaw", root, -22)
    lift = B.empty("FoxWispLift", yaw, loc=(0, FORWARD, 0))  # 上下浮动、前后挪
    body = B.empty("FoxWispBody", lift)
    head = B.empty("FoxWispHead", body)
    parts = {"root": root, "lift": lift, "body": body, "head": head, "obs": {}, "head_obs": {}}
    st = _state("float", 0, 8)
    for nm, v in _shapes(st).items():
        if nm.startswith("_"):
            continue
        trail = nm.startswith("Wisp")
        parts["obs"][nm] = B.mesh_object(f"FoxWisp{nm}", K.tube_build(v[0], v[1], 12, flat=v[2]),
                                         wisp if trail else flame, "none" if trail else "thin", body, sharp_deg=0)
    # 头：一个椭球（头心）+ 吻 + 两耳 + 额顶火舌；整体朝镜头偏一点，E 向两只眼都看得见
    skull = B.mesh_object("FoxWispSkull", K.ellipsoid((0.112, 0.130, 0.100), 20, 12), flame, "thin", head, sharp_deg=0)
    B.set_point_attr(skull, "fade", [0.0] * len(skull.data.vertices))
    for nm, v in _head_parts(st).items():
        parts["head_obs"][nm] = B.mesh_object(f"FoxWisp{nm}", K.tube_build(v[0], v[1], 12, flat=v[2]), flame, "thin",
                                              head, sharp_deg=0)
    # 眼：焦墨眼眶（细长、眼角上挑）+ 里面一道发光的细缝
    for sx in (-1, 1):
        # 绕 Z 转 +30°·sx：眼盘朝前外侧；绕 Y 转 -20°·sx：外眼角上挑
        loc = Vector((0.060 * sx, -0.090, 0.030))
        rot = (math.radians(-8), math.radians(-20 * sx), math.radians(32 * sx))
        B.mesh_object(f"FoxWispSocket{sx:+d}", K.ellipsoid((0.070, 0.030, 0.034), 14, 8), socket_m, "none", head,
                      loc=loc, rot=rot)
        B.mesh_object(f"FoxWispEye{sx:+d}", K.ellipsoid((0.058, 0.022, 0.017), 14, 8), eye, "none", head,
                      loc=loc + Vector((0.012 * sx, -0.012, 0.0)), rot=rot)
    sock = B.empty("FoxWispSocketEyes", head, loc=(0, -0.118, 0.024))
    sockets = {"eyes": sock, "feet": B.empty("FoxWispFeet", root)}
    parts["sockets"] = sockets
    pose_fox_wisp(parts, "float", 0, 8)
    return root, parts, sockets


def pose_fox_wisp(parts, anim, frame, n):
    st = _state(anim, frame, n)
    parts["lift"].location = (0, FORWARD + st["body_dy"], st["bob"])
    for nm, v in _shapes(st).items():
        if nm == "_head":
            parts["head"].location = v
            parts["head"].rotation_euler = (math.radians(st["head_pitch"]), 0, math.radians(-38))
            continue
        _set(parts["obs"][nm], *v)
    for nm, v in _head_parts(st).items():
        _set(parts["head_obs"][nm], *v)
    bpy.context.view_layer.update()
