#!/usr/bin/env python3
"""提灯夜行 · 主角头像第二版样张（工笔淡彩加水墨的胸像）。

旧头像（render/portrait.py）用的是精灵的低模，近看像玩偶：脸是平块、头发是硬边几何块、眼睛像贴上去的。
这一版三维出底、二维后期：
  - 三维（Cycles CPU）：头颈用隐式曲面（v2kit.smin 等）——按高度放样的头型（额、颧、下颌、下巴各自的宽和前后），
    再并上鼻梁、鼻头、鼻翼、眉弓、颧骨、嘴唇、耳朵、颈；眼窝挖进去，眼球单独一个物体，眼睑是包着眼球的一层壳、
    按杏仁形的开口从眼球中心往外切开，所以眼睛嵌在眼眶里、上眼睑有厚度和投影。
    皮肤 Principled 带次表面，底色是按部位烘的顶点色（两颊、鼻头、耳朵泛红，眼周一层淡赭）。
    头发是贴着头骨的一层壳（发际线处收薄），发髻、马尾、鬓发是管子；斗笠版加一顶斗笠。
    灯笼的暖光从画面左下打上来，月光冷光从右后上方来，天光是很暗的靛蓝。
  - 二维（numpy / Pillow）：墨线（物体编号和深度的边，按受光提按）、五官用笔（眼线、睫毛、眉、鼻翼、唇线，
    位置是三维投影来的）、头发一缕缕带飞白的笔触（沿头发表面走的三维曲线投影下来，按深度遮挡）、
    夜色水墨底、宣纸纹、调色。

三个方向（VARIANTS）：cold 冷峻、gentle 温和、hat 带斗笠。
这一版只出样张，不打包图集：

    art/.venv/bin/python art/render/portrait_v2.py cold --draft     # 低采样试渲（256²）→ out/_tmp_portrait_v2/
    art/.venv/bin/python art/render/portrait_v2.py                  # 三个方向正式渲染 + 后期 + 审图
    art/.venv/bin/python art/render/portrait_v2.py --post           # 只重做后期和审图（读渲染缓存）

审图：out/review@2x/portrait_samples.png（三张 512² 大图 + 旧头像）、portrait_samples_hud.png（1080p 状态栏，实际大小）。
渲染包在 bstyle.render_lock() 里（几个代理同时出图时排队）。
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path

import numpy as np

ART = Path(__file__).resolve().parents[1]
for p in (ART, ART / "post", ART / "models", ART / "render"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

TMP = ART / "out" / "_tmp_portrait_v2"
REVIEW = ART / "out" / "review@2x"
SIZE = 512  # 母版边长；游戏里是 256²（2 倍密度），界面显示 92
WINDOW = 78 / 92  # 头像章漆环窗口（直径 78）占胸像图（92）的比例：圆外的部分看不见

# ====================================================================== 方向
# yaw：头转向（度，正 = 转向画面右边）；pitch：低头（度，正 = 低头）；roll：歪头；body：身子跟着转多少
# gaze：眼珠相对头的转动（度：左右、上下，正 = 向画面右、向下）；lid_up / lid_lo：上、下眼睑开合（1 = 常态）
# brow：眉（抬眉头、压眉尾）；mouth：嘴角（正 = 上扬）
VARIANTS = {
    "cold": dict(name="冷峻", yaw=28.0, pitch=2.0, roll=-2.0, body=12.0, gaze=(10.0, 1.0), lid_up=0.86, lid_lo=1.08,
                 brow=dict(inner=-0.0012, outer=0.0008, arch=0.0006), mouth=-0.0006, hat=False,
                 cam_elev=2.5, lantern_px=(0.16, 0.86), lantern_dy=-0.16, moon=(0.85, 0.20, 0.50)),
    "gentle": dict(name="温和", yaw=-26.0, pitch=7.0, roll=3.0, body=-10.0, gaze=(-6.0, 17.0), lid_up=0.92, lid_lo=1.0,
                   lid_drop=0.0024, frame=(-0.022, 0.0, -0.018),
                   brow=dict(inner=0.0010, outer=-0.0004, arch=0.0012), mouth=0.0007, hat=False,
                   cam_elev=0.0, lantern_px=(0.17, 0.84), lantern_dy=-0.20, moon=(0.80, 0.35, 0.55)),
    "hat": dict(name="带斗笠", yaw=20.0, pitch=2.0, roll=-1.0, body=8.0, gaze=(6.0, 4.0), lid_up=0.84, lid_lo=1.0,
                brow=dict(inner=-0.0008, outer=0.0006, arch=0.0006), mouth=-0.0003, hat=True,
                cam_elev=7.0, frame=(0.0, 0.0, 0.010), lantern_px=(0.18, 0.88), lantern_dy=-0.16, moon=(0.70, 0.30, 0.75)),
}
ORDER = ("cold", "gentle", "hat")


# ====================================================================== 隐式曲面（头部局部坐标，米）
# 原点在两耳孔连线中点；脸朝 -Y，上 +Z，主角自己的左边是 +X（和 models/hero.py 一致）。
def smin(a, b, k):
    h = np.clip(0.5 + 0.5 * (b - a) / k, 0.0, 1.0)
    return b + (a - b) * h - k * h * (1.0 - h)


def smax(a, b, k):
    return -smin(-a, -b, k)


def sd_ell(p, c, r):
    """椭球（Inigo Quilez 的近似距离）。"""
    q = (p - np.asarray(c, np.float64)) / np.asarray(r, np.float64)
    k0 = np.linalg.norm(q, axis=-1)
    k1 = np.linalg.norm(q / np.asarray(r, np.float64), axis=-1)
    return k0 * (k0 - 1.0) / np.maximum(k1, 1e-9)


def sd_cone(p, a, b, r0, r1):
    """圆锥台（两头是球）。"""
    a, b = np.asarray(a, np.float64), np.asarray(b, np.float64)
    ba = b - a
    t = np.clip(((p - a) @ ba) / float(ba @ ba), 0.0, 1.0)
    d = np.linalg.norm(p - (a + t[..., None] * ba), axis=-1)
    return d - (r0 + (r1 - r0) * t)


def sd_sphere(p, c, r):
    return np.linalg.norm(p - np.asarray(c, np.float64), axis=-1) - r


def catmull_table(zs, vals, z):
    """按 z 在表上做 Catmull-Rom 插值（表外取端点值）。vals (n, k)。"""
    zs = np.asarray(zs, np.float64)
    V = np.asarray(vals, np.float64)
    order = np.argsort(zs)
    zs, V = zs[order], V[order]
    n = len(zs)
    i = np.clip(np.searchsorted(zs, z) - 1, 0, n - 2)
    z0, z1 = zs[i], zs[i + 1]
    t = np.clip((z - z0) / np.maximum(z1 - z0, 1e-12), 0.0, 1.0)[..., None]
    p1, p2 = V[i], V[i + 1]
    p0 = V[np.maximum(i - 1, 0)]
    p3 = V[np.minimum(i + 2, n - 1)]
    t2, t3 = t * t, t * t * t
    return 0.5 * (2 * p1 + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t2 + (-p0 + 3 * p1 - 3 * p2 + p3) * t3)


# 头型放样表：高度 z → 前缘 y、后缘 y、最宽处 y、半宽、前半的超椭圆指数、后半指数
#            z       yF      yB      y0      w      nf    nb
LOFT = [(0.1077, -0.004, 0.022, 0.008, 0.000, 2.2, 2.2),
        (0.1045, -0.026, 0.044, 0.008, 0.026, 2.2, 2.2),
        (0.0962, -0.052, 0.070, 0.010, 0.046, 2.3, 2.2),
        (0.0824, -0.071, 0.088, 0.010, 0.059, 2.4, 2.2),
        (0.0659, -0.084, 0.098, 0.010, 0.067, 2.5, 2.2),
        (0.0466, -0.091, 0.102, 0.008, 0.071, 2.6, 2.2),
        (0.0300, -0.0935, 0.103, 0.005, 0.0725, 2.6, 2.2),
        (0.0150, -0.0915, 0.101, 0.000, 0.0715, 2.6, 2.2),
        (0.0000, -0.0890, 0.097, -0.004, 0.0695, 2.5, 2.2),
        (-0.0150, -0.0900, 0.090, -0.009, 0.0670, 2.4, 2.2),
        (-0.0280, -0.0920, 0.078, -0.014, 0.0635, 2.2, 2.2),
        (-0.0400, -0.0930, 0.060, -0.019, 0.0580, 2.0, 2.2),
        (-0.0520, -0.0930, 0.036, -0.024, 0.0530, 1.85, 2.2),
        (-0.0650, -0.0895, 0.010, -0.030, 0.0455, 1.7, 2.2),
        (-0.0780, -0.0880, -0.014, -0.040, 0.0355, 1.6, 2.2),
        (-0.0890, -0.0840, -0.030, -0.048, 0.0255, 1.7, 2.2),
        (-0.0970, -0.0760, -0.042, -0.054, 0.0175, 1.8, 2.2),
        (-0.1020, -0.0660, -0.050, -0.057, 0.0090, 2.0, 2.2),
        (-0.1045, -0.0600, -0.055, -0.057, 0.000, 2.0, 2.2)]


def sd_loft(p):
    """按高度放样的头型：每个水平截面是前后两半不同的超椭圆。返回沿径向的近似距离。"""
    x, y, z = p[..., 0], p[..., 1], p[..., 2]
    T = np.asarray(LOFT)
    v = catmull_table(T[:, 0], T[:, 1:], np.clip(z, T[-1, 0], T[0, 0]))
    yF, yB, y0, w, nf, nb = (v[..., k] for k in range(6))
    w = np.maximum(w, 1e-4)
    front = y < y0
    d = np.where(front, np.maximum(y0 - yF, 1e-4), np.maximum(yB - y0, 1e-4))
    n = np.where(front, nf, nb)
    ax = np.abs(x) / w
    ay = np.abs(y - y0) / d
    q = (ax ** n + ay ** n) ** (1.0 / n)
    r = np.hypot(x, y - y0)
    rad = r * (1.0 - 1.0 / np.maximum(q, 1e-6))
    # 截面以外（头顶之上、下巴之下）：再和上下两个盖子比
    top = z - T[0, 0]
    bot = T[-1, 0] - z
    return np.maximum(rad, np.maximum(top, bot))


# 眼：眼球中心、半径；杏仁形开口（沿眼球表面的弧长，米）：内眼角、外眼角（u 向外为正，v 向上）
EYE_C = (0.0320, -0.0748, 0.0040)
EYE_R = 0.0134
LID_T = 0.0026  # 眼睑厚
EYE_IN = (-0.0128, -0.0012)
EYE_OUT = (0.0140, 0.0028)
LID_UP_H, LID_LO_H = 0.0068, 0.0040  # 上、下眼睑离两角连线的最大距离


def _bump(t, peak, power):
    a = math.log(0.5) / math.log(peak)
    return np.sin(np.pi * np.clip(t, 0, 1) ** a) ** power


def lid_curves(t, var):
    """杏仁形开口的上下缘：沿两眼角连线的参数 t（0 内 → 1 外）→ (u, v_up, v_lo)，单位是眼球表面的弧长。"""
    u = EYE_IN[0] + (EYE_OUT[0] - EYE_IN[0]) * t
    base = EYE_IN[1] + (EYE_OUT[1] - EYE_IN[1]) * t
    drop = var.get("lid_drop", 0.0) * _bump(t, 0.5, 0.6)  # 往下看时上眼睑跟着落下来
    up = base + LID_UP_H * var.get("lid_up", 1.0) * _bump(t, 0.42, 0.85) - drop
    lo = base - LID_LO_H * var.get("lid_lo", 1.0) * _bump(t, 0.56, 1.1) - 0.25 * drop
    return u, up, lo


def eye_angles(p, c, sx):
    """点 → 相对眼球中心的 (u, v)（眼球表面弧长，u 朝外眼角）和到中心的距离。"""
    q = p - np.asarray(c, np.float64)
    r = np.linalg.norm(q, axis=-1)
    u = np.arctan2(q[..., 0] * sx, -q[..., 1]) * EYE_R
    v = np.arcsin(np.clip(q[..., 2] / np.maximum(r, 1e-9), -1, 1)) * EYE_R
    return u, v, r


def sd_eye_open(p, c, sx, var):
    """眼睑开口：从眼球中心往外的锥体（截面是杏仁形），只切眼睑那一层。里面为负。"""
    u, v, r = eye_angles(p, c, sx)
    span = EYE_OUT[0] - EYE_IN[0]
    t = (u - EYE_IN[0]) / span
    _, up, lo = lid_curves(t, var)
    d2 = np.maximum.reduce([v - up, lo - v, EYE_IN[0] - u, u - EYE_OUT[0]])
    q = p - np.asarray(c, np.float64)
    front = q[..., 1] - 0.004  # 只在眼球前半
    return np.maximum.reduce([d2, r - (EYE_R + LID_T + 0.006), front])


def eye_center(sx):
    return np.array([EYE_C[0] * sx, EYE_C[1], EYE_C[2]])


# 下半张脸按设计稿压短一点（年轻、秀气）：鼻底以下的高度乘 LOWER_K。隐式曲面在“设计坐标”里写，查询时换过去。
LOWER_K = 0.88
ZW0, ZW1 = -0.040, -0.125


def unwarp_z(z):
    """最终坐标的 z → 设计坐标的 z。"""
    zb = ZW0 + (ZW1 - ZW0) * LOWER_K
    return np.where(z >= ZW0, z, np.where(z >= zb, ZW0 + (z - ZW0) / LOWER_K, z - zb + ZW1))


def warp_z(z):
    """设计坐标的 z → 最终坐标的 z。"""
    z = np.asarray(z, np.float64)
    return np.where(z >= ZW0, z, np.where(z >= ZW1, ZW0 + (z - ZW0) * LOWER_K, ZW0 + (ZW1 - ZW0) * LOWER_K + (z - ZW1)))


def design(p):
    q = np.array(p, np.float64, copy=True)
    q[..., 2] = unwarp_z(q[..., 2])
    return q


def warp_pts(P):
    P = np.array(P, np.float64, copy=True)
    P[..., 2] = warp_z(P[..., 2])
    return P


def sd_head_base(p):
    return sd_loft(design(p))


def sd_skin(p, var):
    """头颈的皮肤。"""
    q = design(p)
    d = sd_loft(q)
    # 眉弓（很淡）、颧、下巴、下巴底下连到颈
    for sx in (-1, 1):
        d = smin(d, sd_ell(q, (0.030 * sx, -0.083, 0.0225), (0.020, 0.010, 0.0075)), 0.010)
        d = smin(d, sd_ell(q, (0.048 * sx, -0.063, -0.008), (0.016, 0.012, 0.011)), 0.020)
    d = smin(d, sd_ell(q, (0.0, -0.080, -0.096), (0.013, 0.008, 0.009)), 0.010)
    d = smin(d, sd_cone(q, (0.0, -0.058, -0.103), (0.0, -0.024, -0.116), 0.009, 0.016), 0.020)
    # 眼窝：先挖，再把眼睑壳并回来，最后按杏仁形切开
    for sx in (-1, 1):
        c = eye_center(sx)
        d = smax(d, -sd_ell(q, c + np.array([0.001 * sx, -0.0075, 0.0005]), (0.0182, 0.0080, 0.0120)), 0.008)
        d = smin(d, sd_sphere(q, c, EYE_R + LID_T), 0.0045)
    # 鼻：鼻梁、鼻头、鼻翼，鼻孔浅浅挖一下
    nose = sd_cone(q, (0.0, -0.0905, 0.012), (0.0, -0.1065, -0.025), 0.0044, 0.0060)
    nose = smin(nose, sd_ell(q, (0.0, -0.1025, -0.0305), (0.0086, 0.0078, 0.0076)), 0.006)
    for sx in (-1, 1):
        nose = smin(nose, sd_ell(q, (0.0102 * sx, -0.0960, -0.0350), (0.0055, 0.0066, 0.0056)), 0.004)
    d = smin(d, nose, 0.0075)
    for sx in (-1, 1):
        d = smax(d, -sd_ell(q, (0.0054 * sx, -0.0985, -0.0398), (0.0028, 0.0038, 0.0016)), 0.0018)
    # 上下唇、嘴角、嘴缝
    mc = var.get("mouth", 0.0)
    d = smin(d, sd_ell(q, (0.0, -0.0840, -0.0560), (0.0240, 0.0120, 0.0160)), 0.020)  # 口周
    d = smin(d, sd_ell(q, (0.0, -0.0935, -0.0545), (0.0175, 0.0050, 0.0044)), 0.005)
    d = smin(d, sd_ell(q, (0.0, -0.0912, -0.0622), (0.0150, 0.0056, 0.0048)), 0.005)
    for sx in (-1, 1):  # 嘴角的小窝（往上 / 往下挪就是表情）
        d = smax(d, -sd_sphere(q, (0.0195 * sx, -0.0868, -0.0586 + mc), 0.0024), 0.003)
    d = smax(d, -sd_ell(q, (0.0, -0.0965, -0.0583 + 0.4 * mc), (0.0185, 0.0080, 0.0007)), 0.0015)
    # 耳朵
    for sx in (-1, 1):
        ear = sd_ell(q, (0.0715 * sx, 0.008, -0.006), (0.0065, 0.0145, 0.026))
        ear = smax(ear, -sd_ell(q, (0.0765 * sx, 0.004, -0.004), (0.0032, 0.009, 0.017)), 0.003)
        d = smin(d, ear, 0.004)
    # 颈：颈柱 + 两条胸锁乳突肌
    d = smin(d, sd_cone(q, (0.0, 0.010, -0.050), (0.0, 0.022, -0.210), 0.046, 0.052), 0.022)
    for sx in (-1, 1):
        d = smin(d, sd_cone(q, (0.040 * sx, 0.020, -0.088), (0.012 * sx, -0.034, -0.185), 0.009, 0.009), 0.018)
    # 切开眼睑
    for sx in (-1, 1):
        d = smax(d, -sd_eye_open(p, eye_center(sx), sx, var), 0.0007)
    return d


# ====================================================================== 头发（头部局部坐标）
HAIR_TIE = np.array([0.0, 0.034, 0.116])  # 发髻扎起的地方（头顶偏后）


def hairline_z(phi):
    """发际线高度：phi 是绕竖轴的方位角（0 = 正前，±π = 正后，正 = 主角左边 +X）。"""
    a = np.abs(phi)
    xs = np.array([0.0, 0.35, 0.70, 0.95, 1.15, 1.30, 1.45, 1.75, 2.05, 2.40, 2.80, 3.1416])
    zs = np.array([0.064, 0.060, 0.047, 0.030, 0.016, 0.004, 0.024, 0.032, 0.000, -0.040, -0.066, -0.072])
    return np.interp(a, xs, zs)


def sd_hair_cap(p, skin_d):
    """贴着头骨的一层头发：发际线处收薄到 0，往上加厚；扎向头顶，所以表面有一道道朝发髻收拢的细沟。"""
    x, y, z = p[..., 0], p[..., 1], p[..., 2]
    phi = np.arctan2(x, -y)
    zh = hairline_z(phi)
    above = z - zh
    th = 0.0004 + 0.0100 * np.clip(above / 0.042, 0, 1) ** 0.75
    # 朝发髻收拢的细沟：绕“头心 → 发髻”轴的方位角上的正弦
    axis = HAIR_TIE - np.array([0.0, 0.0, 0.0])
    axis = axis / np.linalg.norm(axis)
    e1 = np.cross(axis, [1.0, 0.0, 0.0]); e1 /= np.linalg.norm(e1)
    e2 = np.cross(axis, e1)
    psi = np.arctan2(p @ e2, p @ e1)
    groove = 0.0006 * np.sin(psi * 46.0 + 0.8 * np.sin(psi * 7.0)) * np.clip(above / 0.02, 0, 1)
    d = skin_d - th + groove
    return smax(d, -above + 0.0004, 0.002)


def sd_topknot(p, hat=False):
    """发髻（马尾的长发是管子，见 ponytail_spines）。戴斗笠时发髻小一点、低一点，收在帽子里。"""
    if hat:
        return sd_ell(p, HAIR_TIE + np.array([0.0, 0.010, -0.012]), (0.018, 0.020, 0.012))
    return sd_ell(p, HAIR_TIE + np.array([0.0, 0.004, 0.006]), (0.024, 0.026, 0.018))


# ====================================================================== 网格
def sdf_grid(fn, lo, hi, step, coarse=3, margin=2.6):
    """在 v2kit.sdf_mesh 的同一套网格上求隐式曲面的值，只在曲面附近精算：先按 coarse 倍的粗格算一遍，
    离曲面远的格点直接用粗格的值（只要符号对），近的再精算。比全精算快好几倍。"""
    lo, hi = np.asarray(lo, np.float64), np.asarray(hi, np.float64)
    n = np.maximum(np.ceil((hi - lo) / step).astype(int) + 1, 2)
    xs = [lo[k] + np.arange(n[k]) * step for k in range(3)]
    nc = (n - 1) // coarse + 2
    xc = [lo[k] + np.arange(nc[k]) * step * coarse for k in range(3)]
    Gc = np.stack(np.meshgrid(*xc, indexing="ij"), -1)
    Fc = fn(Gc.reshape(-1, 3)).reshape(Gc.shape[:3])
    ii = [np.minimum(np.rint(np.arange(n[k]) / coarse).astype(int), nc[k] - 1) for k in range(3)]
    F = Fc[np.ix_(ii[0], ii[1], ii[2])]
    band = np.abs(F) < margin * step * coarse
    pts = np.argwhere(band)
    P = lo + pts * step
    vals = np.empty(len(P))
    for i in range(0, len(P), 400_000):
        vals[i:i + 400_000] = fn(P[i:i + 400_000])
    F[tuple(pts.T)] = vals
    return F


def sdf_mesh(fn, lo, hi, step):
    import v2kit as VK  # noqa: PLC0415

    F = sdf_grid(fn, lo, hi, step)
    total = F.size
    V, F = VK.sdf_mesh(lambda P: F.ravel() if len(P) == total else fn(P), lo, hi, step=step, project=0)
    # 沿梯度投到曲面上；每步最多挪半格（隐式曲面在平滑并集的折角处梯度不准，挪远了网格会破洞）
    h = step * 0.35
    for _ in range(3):
        f0 = fn(V)
        g = np.stack([(fn(V + np.eye(3)[k] * h) - fn(V - np.eye(3)[k] * h)) / (2 * h) for k in range(3)], -1)
        dv = (f0 / np.maximum((g * g).sum(-1), 1e-9))[:, None] * g
        n = np.linalg.norm(dv, axis=-1, keepdims=True)
        V = V - dv * np.minimum(1.0, 0.5 * step / np.maximum(n, 1e-12))
    # 法线用隐式曲面的梯度（比网格面法线平滑）
    g = np.stack([(fn(V + np.eye(3)[k] * h) - fn(V - np.eye(3)[k] * h)) for k in range(3)], -1)
    N = g / np.maximum(np.linalg.norm(g, axis=-1, keepdims=True), 1e-12)
    return V, np.asarray(F, np.int64), N


# ====================================================================== 姿态与相机（numpy，后期投影和 Blender 共用）
PIVOT_H = np.array([0.0, 0.008, -0.070])  # 头部局部坐标里的颈枢轴；世界原点就放在这里
LENS_MM, SENSOR_MM = 85.0, 36.0
CAM_DIST = 1.06
FRAME_CENTER_Z = -0.026  # 相机对准头心下方一点，头在圆里略偏上


def rot(axis, deg):
    a = math.radians(deg)
    c, s = math.cos(a), math.sin(a)
    if axis == "x":
        return np.array([[1, 0, 0], [0, c, -s], [0, s, c]])
    if axis == "y":
        return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])


def mat4(R=np.eye(3), t=(0, 0, 0)):
    M = np.eye(4)
    M[:3, :3] = R
    M[:3, 3] = t
    return M


def head_rot(var):
    """头的转动：先歪（y），再低头（x），最后转向（z）。"""
    return rot("z", var["yaw"]) @ rot("x", var["pitch"]) @ rot("y", var["roll"])


def head_matrix(var):
    """头部局部坐标 → 世界。"""
    R = head_rot(var)
    return mat4(R, -R @ PIVOT_H)


def body_matrix(var):
    """身子局部坐标（原点在颈枢轴）→ 世界。"""
    return mat4(rot("z", var["body"]))


def xform(M, P):
    P = np.asarray(P, np.float64)
    return P @ M[:3, :3].T + M[:3, 3]


def camera_pose(var):
    """相机位置、朝向（3×3，列是相机的右、上、后）。"""
    target = xform(head_matrix(var), [0.0, -0.01, FRAME_CENTER_Z]) + np.asarray(var.get("frame", (0, 0, 0)), np.float64)
    e = math.radians(var["cam_elev"])
    fwd = np.array([0.0, math.cos(e), math.sin(e)])  # 相机朝 +Y 看，抬头为正
    pos = target - fwd * CAM_DIST
    right = np.cross(fwd, [0, 0, 1.0]); right /= np.linalg.norm(right)
    up = np.cross(right, fwd)
    return pos, np.stack([right, up, -fwd], 1)


def project(var, P, size=SIZE):
    """世界坐标 → 像素（左上为原点）和相机深度（米，沿视线）。"""
    pos, Rc = camera_pose(var)
    q = (np.asarray(P, np.float64) - pos) @ Rc
    depth = -q[..., 2]
    f = LENS_MM / SENSOR_MM
    x = (0.5 + f * q[..., 0] / depth) * size
    y = (0.5 - f * q[..., 1] / depth) * size
    return np.stack([x, y], -1), depth


# ====================================================================== 身子、斗笠的隐式曲面（身子局部坐标）
TORSO_LIFT = 0.048  # 身子整体往上提（脖子别太长）
def sd_torso(p):
    """穿着袍子的上身：肩、胸、上臂，领口一圈贴着颈。"""
    p = p - np.array([0.0, 0.0, TORSO_LIFT])
    d = sd_ell(p, (0.0, 0.012, -0.300), (0.168, 0.104, 0.175))
    for sx in (-1, 1):
        d = smin(d, sd_cone(p, (0.02 * sx, 0.028, -0.135), (0.172 * sx, 0.034, -0.200), 0.050, 0.060), 0.05)
        d = smin(d, sd_cone(p, (0.180 * sx, 0.034, -0.215), (0.210 * sx, 0.046, -0.480), 0.062, 0.058), 0.03)
    # 领子：贴颈一圈（颈轴附近的圆筒壳）
    a, b = np.array([0.0, 0.016, -0.08]), np.array([0.0, 0.026, -0.22])
    ba = b - a
    t = np.clip(((p - a) @ ba) / float(ba @ ba), 0.0, 1.0)
    r = np.linalg.norm(p - (a + t[..., None] * ba), axis=-1)
    collar = np.maximum(np.abs(r - 0.061) - 0.009, np.maximum(p[..., 2] + 0.215, -0.118 - p[..., 2]))
    d = smin(d, collar, 0.02)
    # 前襟的 V 口：颈前挖开到胸口
    v = np.maximum(-0.218 + 1.55 * np.abs(p[..., 0]) - p[..., 2], -(p[..., 1] + 0.005))
    d = smax(d, -v, 0.006)
    return d


COLLAR_L = [(-0.002, 0.071, -0.112), (0.040, 0.054, -0.114), (0.060, 0.012, -0.124), (0.050, -0.038, -0.150),
            (0.022, -0.074, -0.192), (-0.006, -0.090, -0.226), (-0.050, -0.103, -0.272), (-0.090, -0.110, -0.320)]
COLLAR_R = [(0.002, 0.071, -0.112), (-0.040, 0.054, -0.114), (-0.060, 0.012, -0.124), (-0.050, -0.038, -0.150),
            (-0.024, -0.074, -0.190), (0.002, -0.088, -0.218)]


def cloak_edge(z):
    """墨氅前襟的边：离中线的距离随高度变（肩上贴着领子，往下敞开）。"""
    return 0.082 + 0.22 * np.clip(-0.16 - z, 0, None)


def sd_cloak(p, torso_d):
    p = p - np.array([0.0, 0.0, TORSO_LIFT])
    d = torso_d - 0.010
    edge = cloak_edge(p[..., 2]) - np.abs(p[..., 0])
    d = smax(d, edge, 0.004)
    return smax(d, p[..., 2] + 0.122, 0.006)


def sd_band(p, pts, r):
    d = np.full(p.shape[:-1], 1e9)
    for a, b in zip(pts[:-1], pts[1:]):
        d = np.minimum(d, sd_cone(p, a, b, r, r))
    return d


# 斗笠（头部局部坐标）：尖顶在头顶上方，帽檐往前压
HAT_APEX = np.array([0.0, 0.012, 0.152])
HAT_R = 0.235
HAT_TILT = 12.0  # 往前压的角度（度）


def sd_hat(p):
    """斗笠：微微外凸的锥面，厚 6 毫米，帽顶一个小钮；整体前倾 HAT_TILT。"""
    R = rot("x", HAT_TILT)  # 绕 x 正转 = 前低后高
    q = (p - HAT_APEX) @ R  # 世界 → 帽子局部（局部 z 向上，原点在尖顶）
    r = np.hypot(q[..., 0], q[..., 1])
    zc = -0.105 * (r / HAT_R) ** 0.80  # 锥面（微凸）
    d = np.abs(q[..., 2] - zc) * 0.75 - 0.003
    d = np.maximum(d, r - HAT_R)
    d = smin(d, sd_sphere(q, (0, 0, 0.002), 0.009), 0.004)
    return d


def hat_above(p):
    """点在斗笠锥面之上多少（米；负 = 在帽子里面）。"""
    q = (p - HAT_APEX) @ rot("x", HAT_TILT)
    r = np.hypot(q[..., 0], q[..., 1])
    return q[..., 2] + 0.105 * (r / HAT_R) ** 0.80


def hat_strap_pts():
    out = []
    for sx in (-1, 1):
        out.append([(0.066 * sx, -0.004, 0.072), (0.070 * sx, -0.022, 0.020), (0.060 * sx, -0.038, -0.040),
                    (0.034 * sx, -0.056, -0.094), (0.0, -0.062, -0.112)])
    return out


# ====================================================================== 头发的管子（头部局部坐标的点列）
def ponytail_spines(var):
    """马尾：几股从发髻后面出来，先往后上翘，再垂到肩后；末梢分开。斗笠版从脑后帽檐下出来。"""
    rng = np.random.default_rng(3)
    if var.get("hat"):
        base = [(0.0, 0.090, 0.050), (0.0, 0.112, 0.010), (0.004, 0.122, -0.050), (0.010, 0.120, -0.120),
                (0.018, 0.110, -0.200), (0.026, 0.100, -0.270)]
    else:
        base = [(0.0, 0.050, 0.120), (0.0, 0.088, 0.142), (0.0, 0.122, 0.122), (0.004, 0.142, 0.062),
                (0.010, 0.146, -0.018), (0.018, 0.138, -0.100), (0.028, 0.124, -0.190), (0.040, 0.110, -0.270)]
    base = np.asarray(base)
    spines = []
    for k in range(7):
        off = rng.normal(0, 1, 3) * np.array([0.010, 0.006, 0.004])
        tt = np.linspace(0, 1, len(base))[:, None]
        sp = base + off * tt ** 1.3 + np.array([0.0, 0.0, 0.0])
        sp[-1] += np.array([rng.normal(0, 0.02), rng.normal(0, 0.01), rng.uniform(-0.03, 0.02)])
        spines.append((sp, 0.0105 - 0.0008 * k))
    return spines


def sidelock_spines(var):
    """两缕鬓发：从鬓角发际线出来，在耳前垂到下颌，S 形；再两缕短额发斜扫到眉梢。"""
    out = []
    for sx in (-1, 1):
        out.append((np.array([(0.057 * sx, -0.054, 0.046), (0.066 * sx, -0.060, 0.016), (0.070 * sx, -0.058, -0.022),
                              (0.067 * sx, -0.060, -0.060), (0.063 * sx, -0.066, -0.096), (0.059 * sx, -0.068, -0.122)]),
                    0.0056, "side"))
    return out


def ribbon_spines(var):
    """朱砂发带两条长尾：从发髻后面垂下，和马尾错开。"""
    if var.get("hat"):
        root = np.array([0.0, 0.098, 0.040])
    else:
        root = np.array([0.0, 0.060, 0.124])
    a = root + np.array([(0.0, 0.0, 0.0), (0.020, 0.030, 0.000), (0.034, 0.050, -0.060), (0.040, 0.060, -0.140),
                         (0.052, 0.058, -0.220), (0.060, 0.064, -0.300)])
    b = root + np.array([(0.0, 0.0, 0.0), (-0.016, 0.034, -0.010), (-0.026, 0.060, -0.070), (-0.030, 0.072, -0.150),
                         (-0.036, 0.076, -0.230)])
    return [a, b]


def smooth_curve(pts, n=48):
    """过控制点的 Catmull-Rom 曲线，按弧长重采样。"""
    c = np.asarray(pts, np.float64)
    c = np.vstack([2 * c[0] - c[1], c, 2 * c[-1] - c[-2]])
    out = []
    for i in range(1, len(c) - 2):
        p0, p1, p2, p3 = c[i - 1], c[i], c[i + 1], c[i + 2]
        t = np.linspace(0, 1, 16, endpoint=False)[:, None]
        out.append(0.5 * (2 * p1 + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t ** 2
                          + (-p0 + 3 * p1 - 3 * p2 + p3) * t ** 3))
    out.append(c[-2][None])
    P = np.vstack(out)
    s = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(P, axis=0), axis=1))])
    u = np.linspace(0, s[-1], n)
    return np.stack([np.interp(u, s, P[:, k]) for k in range(P.shape[1])], -1)


def tube_mesh(spine, r0, r1, flat=1.0, nu=12, n=48, side=(1.0, 0.0, 0.0)):
    """沿点列的变粗细管（截面扁 flat 倍），两头封口。返回 (顶点, 面)。"""
    C = smooth_curve(spine, n)
    T = np.gradient(C, axis=0)
    T /= np.linalg.norm(T, axis=1, keepdims=True) + 1e-12
    V, F = [], []
    sd = np.asarray(side, np.float64)
    for j in range(n):
        t = j / (n - 1)
        a = sd - T[j] * (sd @ T[j])
        a /= np.linalg.norm(a) + 1e-12
        b = np.cross(T[j], a)
        r = r0 + (r1 - r0) * t
        for i in range(nu):
            th = 2 * math.pi * i / nu
            V.append(C[j] + a * r * math.cos(th) + b * r * flat * math.sin(th))
    for j in range(n - 1):
        for i in range(nu):
            F.append((j * nu + i, j * nu + (i + 1) % nu, (j + 1) * nu + (i + 1) % nu, (j + 1) * nu + i))
    V.append(C[0] - T[0] * r0 * 0.5)
    c0 = len(V) - 1
    F += [(c0, (i + 1) % nu, i) for i in range(nu)]
    V.append(C[-1] + T[-1] * 1e-4)
    c1 = len(V) - 1
    F += [(c1, (n - 1) * nu + i, (n - 1) * nu + (i + 1) % nu) for i in range(nu)]
    return np.asarray(V), F


def strip_mesh(spine, width, n=48, twist=0.0, up=(0.0, 0.0, 1.0), thick=0.0012):
    """扁带（发带）：沿点列扫一条有厚度的窄带，宽度方向大致垂直于 up 和走向，可以扭。"""
    C = smooth_curve(spine, n)
    T = np.gradient(C, axis=0)
    T /= np.linalg.norm(T, axis=1, keepdims=True) + 1e-12
    V, F = [], []
    for j in range(n):
        t = j / (n - 1)
        a = np.cross(T[j], up)
        a /= np.linalg.norm(a) + 1e-12
        b = np.cross(T[j], a)
        ang = twist * t
        a, b = a * math.cos(ang) + b * math.sin(ang), -a * math.sin(ang) + b * math.cos(ang)
        w = width * (0.75 + 0.25 * t)
        for sa, sb in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
            V.append(C[j] + a * w * 0.5 * sa + b * thick * 0.5 * sb)
    for j in range(n - 1):
        for i in range(4):
            F.append((j * 4 + i, j * 4 + (i + 1) % 4, (j + 1) * 4 + (i + 1) % 4, (j + 1) * 4 + i))
    F.append((3, 2, 1, 0))
    k = (n - 1) * 4
    F.append((k, k + 1, k + 2, k + 3))
    return np.asarray(V), F


# ====================================================================== 顶点色：皮肤按部位烘一层淡彩
def hexlin(h):
    h = h.lstrip("#")
    c = np.array([int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4)])
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


SKIN_BASE = "#EACAA6"  # 比精灵的肤色略白一点（工笔人物“三白”的底）
SKIN_BLUSH = "#D9907A"
SKIN_EYE = "#B9806A"
SKIN_LIP = "#B4584C"
SKIN_SHADOW = "#C7A58A"


def skin_paint(V, var):
    """皮肤底色：两颊、鼻头、耳朵泛红，眼周一层淡赭，唇是淡朱；颈往下略深。V 是头部局部坐标的顶点。"""
    V = design(V)
    base = hexlin(SKIN_BASE)[None, :].repeat(len(V), 0)

    def g(c, s):
        return np.exp(-np.sum(((V - np.asarray(c)) / np.asarray(s)) ** 2, axis=-1))

    def mixin(col, w):
        nonlocal base
        w = np.clip(w, 0, 1)[:, None]
        base = base * (1 - w) + hexlin(col)[None, :] * w

    mixin(SKIN_SHADOW, 0.55 * np.clip((-0.095 - V[:, 2]) / 0.06, 0, 1))  # 下巴底下、颈
    for sx in (-1, 1):
        mixin(SKIN_BLUSH, 0.42 * g((0.042 * sx, -0.080, -0.022), (0.020, 0.030, 0.020)))
        mixin(SKIN_EYE, 0.42 * g((0.031 * sx, -0.084, 0.010), (0.017, 0.020, 0.008)))  # 上眼睑一层胭脂赭
        mixin(SKIN_BLUSH, 0.45 * g((0.072 * sx, 0.006, -0.006), (0.012, 0.020, 0.030)))  # 耳
    mixin(SKIN_BLUSH, 0.22 * g((0.0, -0.104, -0.031), (0.010, 0.012, 0.010)))  # 鼻头
    mixin(SKIN_BLUSH, 0.12 * g((0.0, -0.086, -0.094), (0.014, 0.016, 0.010)))  # 下巴
    lips = np.minimum(sd_ell(V, (0.0, -0.0935, -0.0545), (0.0175, 0.0050, 0.0044)),
                      sd_ell(V, (0.0, -0.0912, -0.0622), (0.0150, 0.0056, 0.0048)))
    mixin(SKIN_LIP, 0.70 * np.clip(1.0 - lips / 0.0022, 0, 1) * np.clip(1 - np.abs(V[:, 0]) / 0.020, 0, 1) ** 0.5)
    return base


# ====================================================================== Blender 场景
INDEX = {"skin": 1, "eye": 2, "hair": 3, "ponytail": 4, "lock": 5, "ribbon": 6, "crown": 7, "robe": 8, "cloak": 9,
         "collar": 10, "hat": 11, "strap": 12, "lantern": 13, "sword": 14}


def _bpy():
    import bpy  # noqa: PLC0415

    return bpy


def CA():
    import card_art  # noqa: PLC0415

    return card_art


def new_mesh(name, V, F, mat, index, M=None, normals=None, colors=None, smooth=True):
    """numpy 顶点 / 面 → 物体（M 是 4×4 的局部 → 世界，直接写进顶点）。normals：逐顶点法线（自定义法线）。"""
    bpy = _bpy()
    V = np.asarray(V, np.float64)
    if M is not None:
        V = xform(M, V)
        if normals is not None:
            normals = normals @ M[:3, :3].T
    me = bpy.data.meshes.new(name)
    me.from_pydata(V.tolist(), [], [tuple(int(i) for i in f) for f in F])
    me.validate()
    if smooth:
        me.shade_smooth()
    if normals is not None:
        me.normals_split_custom_set_from_vertices(normals.tolist())
    if colors is not None:
        at = me.color_attributes.new("paint", "FLOAT_COLOR", "POINT")
        rgba = np.concatenate([colors, np.ones((len(colors), 1))], 1).astype(np.float32)
        at.data.foreach_set("color", rgba.ravel())
    me.materials.append(mat)
    ob = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(ob)
    ob.pass_index = index
    return ob


def build_materials():
    C = CA()
    M = {}
    lin = C.lin
    # 皮肤：顶点色底 + 次表面；粗糙度高一点，不要塑料高光
    m = C.Mat("Skin")
    col = m.n("ShaderNodeVertexColor", _layer_name="paint").outputs["Color"]
    nz = m.noise(m.coord("Object"), scale=90.0, detail=3.0, rough=0.5)
    col = m.mix(m.maprange(nz.outputs["Fac"], 0.3, 0.7, 0.0, 0.06), col, (0.62, 0.36, 0.26), "MULTIPLY")
    bsdf = m.principled(Base_Color=col, Roughness=0.52, Subsurface_Weight=0.30, Subsurface_Radius=(1.0, 0.42, 0.22),
                        Subsurface_Scale=0.0045, Specular_IOR_Level=0.32, Sheen_Weight=0.15, Sheen_Roughness=0.4)
    M["skin"] = m.surface(bsdf.outputs[0])
    # 眼球：按物体坐标里离“正前方”的角度画虹膜（瞳孔、虹膜一深一浅两圈、角膜缘一道深环），外面一层清漆出高光
    m = C.Mat("Eye")
    sep = m.n("ShaderNodeSeparateXYZ")
    m.l(m.coord("Object"), sep.inputs[0])
    vlen = m.n("ShaderNodeVectorMath", _operation="LENGTH")
    m.l(m.coord("Object"), vlen.inputs[0])
    cosf = m.math("DIVIDE", m.math("MULTIPLY", sep.outputs["Y"], -1.0), vlen.outputs["Value"])
    fib = m.noise(m.coord("Object"), scale=900.0, detail=2.0, rough=0.6)
    cosj = m.math("ADD", cosf, m.maprange(fib.outputs["Fac"], 0.3, 0.7, -0.004, 0.004))
    ramp, _ = m.ramp(cosj, [(0.70, (*lin("#C9C2B4"), 1)), (0.810, (*lin("#B8B0A2"), 1)), (0.826, (0.010, 0.008, 0.007, 1)),
                            (0.842, (*lin("#2A170D"), 1)), (0.905, (*lin("#4A2A15"), 1)), (0.950, (*lin("#2B190E"), 1)),
                            (0.964, (0.006, 0.005, 0.005, 1)), (1.0, (0.004, 0.004, 0.004, 1))])
    # 虹膜下半透一点光（灯从下面来，角膜把光聚到对面）：下半略亮
    low = m.maprange(sep.outputs["Z"], 0.004, -0.008, 0.0, 1.0)
    iris_mask = m.maprange(cosf, 0.835, 0.845, 0.0, 1.0)
    pupil = m.maprange(cosf, 0.958, 0.966, 1.0, 0.0)
    lit = m.math("MULTIPLY", m.math("MULTIPLY", low, iris_mask), pupil)
    ramp = m.mix(m.math("MULTIPLY", lit, 0.55), ramp, (*lin("#8A5A30"), 1.0), "MIX")
    bsdf = m.principled(Base_Color=ramp, Roughness=0.35, Coat_Weight=1.0, Coat_Roughness=0.03, Specular_IOR_Level=0.4)
    M["eye"] = m.surface(bsdf.outputs[0])
    # 头发：近黑，柔光，细沟出一道道高光
    m = C.Mat("Hair")
    bsdf = m.principled(Base_Color=(0.011, 0.010, 0.011), Roughness=0.36, Specular_IOR_Level=0.55, Sheen_Weight=0.35,
                        Sheen_Roughness=0.35, Sheen_Tint=(0.55, 0.62, 0.85))
    M["hair"] = m.surface(bsdf.outputs[0])
    m = C.Mat("Lock")
    bsdf = m.principled(Base_Color=(0.012, 0.011, 0.012), Roughness=0.40, Specular_IOR_Level=0.5, Sheen_Weight=0.4,
                        Sheen_Roughness=0.35)
    M["lock"] = m.surface(bsdf.outputs[0])
    # 衣：白袍、墨氅、白领
    m = C.Mat("Robe")
    bsdf = m.principled(Base_Color=lin("#D8D0C0"), Roughness=0.86, Sheen_Weight=0.4, Sheen_Roughness=0.5)
    M["robe"] = m.surface(bsdf.outputs[0])
    m = C.Mat("Collar")
    bsdf = m.principled(Base_Color=lin("#E6DFD0"), Roughness=0.82, Sheen_Weight=0.4)
    M["collar"] = m.surface(bsdf.outputs[0])
    m = C.Mat("Cloak")
    nz = m.noise(m.coord("Object"), scale=40.0, detail=4.0, rough=0.6)
    col = m.mix(m.maprange(nz.outputs["Fac"], 0.35, 0.65, 0.0, 1.0), (0.020, 0.018, 0.018), (0.034, 0.030, 0.030))
    bsdf = m.principled(Base_Color=col, Roughness=0.72, Sheen_Weight=0.7, Sheen_Roughness=0.45,
                        Sheen_Tint=(0.6, 0.65, 0.8))
    M["cloak"] = m.surface(bsdf.outputs[0])
    m = C.Mat("Ribbon")
    bsdf = m.principled(Base_Color=lin("#B8352A"), Roughness=0.55, Sheen_Weight=0.5, Sheen_Roughness=0.4)
    M["ribbon"] = m.surface(bsdf.outputs[0])
    m = C.Mat("Silver")
    bsdf = m.principled(Base_Color=(0.20, 0.21, 0.23), Metallic=0.5, Roughness=0.55)
    M["crown"] = m.surface(bsdf.outputs[0])
    m = C.Mat("Jade")
    bsdf = m.principled(Base_Color=lin("#5E8E72"), Roughness=0.12, Subsurface_Weight=0.5, Subsurface_Radius=(0.3, 0.8, 0.5),
                        Subsurface_Scale=0.004, Coat_Weight=0.6)
    M["jade"] = m.surface(bsdf.outputs[0])
    # 斗笠：竹篾编的，放射的篾条 + 一圈圈的编纹（凹凸），颜色深赭
    m = C.Mat("Hat")
    co = m.coord("Object")
    sp = m.n("ShaderNodeSeparateXYZ")
    m.l(co, sp.inputs[0])
    ang = m.math("ARCTAN2", sp.outputs["Y"], sp.outputs["X"])
    rad = m.math("SQRT", m.math("ADD", m.math("MULTIPLY", sp.outputs["X"], sp.outputs["X"]),
                                m.math("MULTIPLY", sp.outputs["Y"], sp.outputs["Y"])))
    spokes = m.math("SINE", m.math("MULTIPLY", ang, 110.0))
    rings = m.math("SINE", m.math("MULTIPLY", rad, 420.0))
    weave = m.math("MULTIPLY", m.math("ADD", spokes, 1.0), m.math("ADD", rings, 1.0))
    nz = m.noise(co, scale=60.0, detail=3.0)
    h = m.math("ADD", m.math("MULTIPLY", weave, 0.25), m.math("MULTIPLY", nz.outputs["Fac"], 0.3))
    colh = m.mix(m.maprange(h, 0.2, 1.0, 0.0, 1.0), lin("#5A3C20"), lin("#7E5A34"))
    bsdf = m.principled(Base_Color=colh, Roughness=0.85, Normal=m.bump(h, strength=0.18, distance=0.002))
    M["hat"] = m.surface(bsdf.outputs[0])
    m = C.Mat("Strap")
    bsdf = m.principled(Base_Color=lin("#3A2A1C"), Roughness=0.8)
    M["strap"] = m.surface(bsdf.outputs[0])
    # 灯笼：红纸透光（自发光），上下木口
    m = C.Mat("LanternPaper")
    co = m.coord("Object")
    sp = m.n("ShaderNodeSeparateXYZ")
    m.l(co, sp.inputs[0])
    ang = m.math("ARCTAN2", sp.outputs["Y"], sp.outputs["X"])
    ribs = m.maprange(m.math("ABSOLUTE", m.math("SINE", m.math("MULTIPLY", ang, 9.0))), 0.0, 0.25, 0.55, 1.0)
    vert = m.maprange(m.math("ABSOLUTE", sp.outputs["Z"]), 0.02, 0.065, 1.0, 0.45)
    k = m.math("MULTIPLY", ribs, vert)
    emc = m.mix(k, lin("#7A1608"), lin("#FFB25A"))
    em = m.n("ShaderNodeEmission", Strength=7.0)
    m.l(emc, em.inputs["Color"])
    m.l(m.math("MULTIPLY", k, 7.0), em.inputs["Strength"])
    M["lantern"] = m.surface(em.outputs[0])
    m = C.Mat("Wood")
    bsdf = m.principled(Base_Color=lin("#3B2414"), Roughness=0.6)
    M["wood"] = m.surface(bsdf.outputs[0])
    m = C.Mat("Gold")
    bsdf = m.principled(Base_Color=lin("#E2B23A"), Metallic=1.0, Roughness=0.35)
    M["gold"] = m.surface(bsdf.outputs[0])
    return M


def build_scene(var, draft: bool) -> dict:
    """建一个方向的整个场景（模型、灯、相机），返回后期要用的东西（投影用的姿态、灯笼位置）。"""
    bpy = _bpy()
    C = CA()
    t0 = time.perf_counter()
    res = 384 if draft == "draft" else SIZE * 2
    spp = {"draft": 16, "dev": 40}.get(draft, 160) if draft else 160
    sc = C.reset_scene(spp, bool(draft))
    sc.render.resolution_x = sc.render.resolution_y = res
    sc.render.resolution_percentage = 100
    sc.cycles.adaptive_threshold = 0.03 if draft == "draft" else (0.015 if draft else 0.008)
    sc.cycles.adaptive_min_samples = 8 if draft else 32
    sc.cycles.diffuse_bounces = 2
    sc.cycles.glossy_bounces = 2
    sc.cycles.transmission_bounces = 4
    sc.cycles.max_bounces = 6
    vl = sc.view_layers[0]
    vl.use_pass_normal = True
    vl.use_pass_diffuse_color = True
    for nm in ("lantern", "moon", "fill"):
        vl.lightgroups.add(name=nm)
    M = build_materials()
    HM, BM = head_matrix(var), body_matrix(var)
    step = 0.0024 if draft == "draft" else 0.0013
    # ---- 皮肤
    fn = lambda p: sd_skin(p, var)  # noqa: E731
    V, F, N = sdf_mesh(fn, (-0.088, -0.125, -0.235), (0.088, 0.112, 0.124), step)
    new_mesh("Skin", V, F, M["skin"], INDEX["skin"], HM, N, skin_paint(V, var))
    # ---- 眼球（随视线转）
    for sx in (-1, 1):
        c = eye_center(sx)
        bpy.ops.mesh.primitive_uv_sphere_add(segments=64, ring_count=32, radius=EYE_R, location=(0, 0, 0))
        ob = bpy.context.active_object
        ob.name = f"Eye{sx:+d}"
        ob.data.materials.append(M["eye"])
        ob.data.shade_smooth()
        ob.pass_index = INDEX["eye"]
        gx, gy = var["gaze"]
        Rg = rot("z", gx) @ rot("x", gy)
        ob.matrix_world = _mw(HM @ mat4(Rg, c))
    # ---- 头发：发壳 + 发髻
    hat = var.get("hat", False)
    fnh = lambda p: np.minimum(sd_hair_cap(p, sd_head_base(p)), sd_topknot(p, hat))  # noqa: E731
    if hat:  # 斗笠底下：头发不能穿出帽子
        fnh0 = fnh
        fnh = lambda p: smax(fnh0(p), hat_above(p) + 0.004, 0.002)  # noqa: E731
    V, F, N = sdf_mesh(fnh, (-0.090, -0.110, -0.090), (0.090, 0.120, 0.150), step * 1.15)
    new_mesh("Hair", V, F, M["hair"], INDEX["hair"], HM, N)
    if not hat:
        _crown(M, HM)
    for i, (sp, r0) in enumerate(ponytail_spines(var)):
        V, F = tube_mesh(sp, r0, r0 * 0.18, flat=0.7, n=64)
        new_mesh(f"Pony{i}", V, F, M["hair"], INDEX["ponytail"], HM)
    for i, (sp, r0, kind) in enumerate(sidelock_spines(var)):
        V, F = tube_mesh(sp, r0, r0 * 0.15, flat=0.45, n=40, side=(0, 1.0, 0) if kind == "side" else (0, 0, 1.0))
        ob = new_mesh(f"Lock{i}", V, F, M["lock"], INDEX["lock"], HM)
        ob.visible_shadow = False
    for i, sp in enumerate(ribbon_spines(var)):
        V, F = strip_mesh(sp, 0.013, n=56, twist=2.2 if i == 0 else -1.8, up=(1.0, 0.0, 0.0))
        new_mesh(f"Ribbon{i}", V, F, M["ribbon"], INDEX["ribbon"], HM)
    tie = (np.array([0.0, 0.098, 0.040]) if hat else HAIR_TIE + np.array([0, 0.016, 0.004]))
    bpy.ops.mesh.primitive_torus_add(major_radius=0.012, minor_radius=0.0035, location=(0, 0, 0))
    ob = bpy.context.active_object
    ob.data.materials.append(M["ribbon"])
    ob.data.shade_smooth()
    ob.pass_index = INDEX["ribbon"]
    ob.matrix_world = _mw(HM @ mat4(rot("x", 70.0), tie))
    # ---- 身子：白袍、墨氅、白领
    fnt = sd_torso
    V, F, N = sdf_mesh(fnt, (-0.30, -0.13, -0.56), (0.30, 0.15, -0.02), step * 2.4)
    new_mesh("Robe", V, F, M["robe"], INDEX["robe"], BM, N)
    fnc = lambda p: sd_cloak(p, sd_torso(p))  # noqa: E731
    V, F, N = sdf_mesh(fnc, (-0.31, -0.14, -0.56), (0.31, 0.16, -0.05), step * 2.4)
    new_mesh("Cloak", V, F, M["cloak"], INDEX["cloak"], BM, N)
    if hat:
        V, F, N = sdf_mesh(sd_hat, (-0.25, -0.26, -0.03), (0.25, 0.26, 0.19), step * 1.6)
        new_mesh("Hat", V, F, M["hat"], INDEX["hat"], HM, N)
        for i, pts in enumerate(hat_strap_pts()):
            V, F = tube_mesh(pts, 0.0016, 0.0016, n=32)
            new_mesh(f"Strap{i}", V, F, M["strap"], INDEX["strap"], HM)
    # ---- 灯笼（画面左下角只露一角）+ 灯光
    head_c = xform(HM, [0.0, -0.02, 0.0])
    lan = _lantern_pos(var)
    _lantern(M, lan)
    L = C.point_light("LanternLight", tuple(lan), 4.0, radius=0.035, color=tuple(hexlin("#FFB46A")))
    L.lightgroup = "lantern"
    moon = np.asarray(var["moon"], np.float64)
    S_ = C.sun_light("Moon", tuple(moon / np.linalg.norm(moon)), 4.0, angle_deg=2.0, color=tuple(hexlin("#A9BCEB")))
    S_.lightgroup = "moon"
    pos, Rc = camera_pose(var)
    A = C.area_light("Fill", tuple(pos + Rc[:, 0] * 0.6 + Rc[:, 1] * 0.5), tuple(head_c), 6.0, 0.8,
                     color=tuple(hexlin("#7F93C8")))
    A.lightgroup = "fill"
    C.set_world(tuple(hexlin("#1C2440")), 1.0)
    sc.world.lightgroup = "fill"
    # ---- 相机
    cd = bpy.data.cameras.new("Cam")
    cam = bpy.data.objects.new("Cam", cd)
    sc.collection.objects.link(cam)
    cd.lens, cd.sensor_width, cd.sensor_fit = LENS_MM, SENSOR_MM, "HORIZONTAL"
    cd.clip_start, cd.clip_end = 0.05, 10.0
    cam.matrix_world = _mw(mat4(Rc, pos))
    sc.camera = cam
    return {"build_s": round(time.perf_counter() - t0, 1), "lantern": lan.tolist(), "res": res}


def _mw(M):
    from mathutils import Matrix  # noqa: PLC0415

    return Matrix([list(r) for r in M])


def _crown(M, HM):
    """银冠：发髻上一只小冠（杯形），前面一颗石绿玉珠，一根横簪穿过去。"""
    bpy = _bpy()
    top = HAIR_TIE + np.array([0.0, 0.004, 0.014])
    prof = [(0.0, 0.0), (0.010, 0.0), (0.0118, 0.006), (0.0122, 0.012), (0.0078, 0.017), (0.0, 0.018)]
    V, F = [], []
    nseg = 32
    for r, z in prof:
        for i in range(nseg):
            a = 2 * math.pi * i / nseg
            V.append((r * math.cos(a), r * math.sin(a) * 0.82, z))
    for j in range(len(prof) - 1):
        for i in range(nseg):
            F.append((j * nseg + i, j * nseg + (i + 1) % nseg, (j + 1) * nseg + (i + 1) % nseg, (j + 1) * nseg + i))
    new_mesh("Crown", np.asarray(V), F, M["crown"], INDEX["crown"], HM @ mat4(rot("x", -16.0), top))
    bpy.ops.mesh.primitive_uv_sphere_add(segments=24, ring_count=12, radius=0.0034)
    ob = bpy.context.active_object
    ob.data.materials.append(M["jade"])
    ob.data.shade_smooth()
    ob.pass_index = INDEX["crown"]
    ob.matrix_world = _mw(HM @ mat4(np.eye(3), top + np.array([0.0, -0.0112, 0.0085])))
    V, F = tube_mesh([(-0.024, 0.0, 0.0), (0.0, 0.0, 0.0), (0.026, 0.0, 0.0)], 0.0013, 0.0009, n=16, side=(0, 0, 1.0))
    new_mesh("Pin", V, F, M["crown"], INDEX["crown"], HM @ mat4(rot("z", 8.0), top + np.array([0.0, 0.002, 0.010])))


def _sword(M, BM):
    """背上的剑：剑柄从左肩后面斜出来，藤黄剑格，缠绳的柄。"""
    a, b = np.array([0.095, 0.090, -0.130]), np.array([0.135, 0.105, -0.010])
    V, F = tube_mesh([a, (a + b) / 2, b], 0.0105, 0.0095, n=24, side=(0, 1.0, 0))
    new_mesh("SwordGrip", V, F, M["strap"], INDEX["sword"], BM)
    g0 = a + (b - a) * -0.02
    V, F = tube_mesh([g0 - (b - a) * 0.03, g0 + (b - a) * 0.03], 0.024, 0.024, flat=0.35, n=6, side=(1.0, 0, 0.3))
    new_mesh("SwordGuard", V, F, M["gold"], INDEX["sword"], BM)
    V, F = tube_mesh([b, b + (b - a) * 0.06], 0.013, 0.010, n=8)
    new_mesh("SwordPommel", V, F, M["gold"], INDEX["sword"], BM)


def _lantern(M, c):
    """红纸灯笼：扁圆的灯身（自发光）、上下木口、底下一缕朱砂穗。"""
    bpy = _bpy()
    bpy.ops.mesh.primitive_uv_sphere_add(segments=48, ring_count=24, radius=1.0)
    ob = bpy.context.active_object
    ob.data.materials.append(M["lantern"])
    ob.data.shade_smooth()
    ob.scale = (0.050, 0.050, 0.058)
    ob.location = tuple(c)
    ob.pass_index = INDEX["lantern"]
    ob.visible_shadow = False  # 灯芯的点光在灯身里面：灯身不挡光
    ob.lightgroup = "lantern"
    for dz in (0.055, -0.055):
        bpy.ops.mesh.primitive_cylinder_add(vertices=32, radius=0.025, depth=0.010, location=tuple(c + np.array([0, 0, dz])))
        o2 = bpy.context.active_object
        o2.data.materials.append(M["wood"])
        o2.pass_index = INDEX["lantern"]
        o2.visible_shadow = False
    V, F = tube_mesh([c + np.array([0, 0, 0.06]), c + np.array([0.004, 0.0, 0.10])], 0.0015, 0.0015, n=8)
    new_mesh("LanternCord", V, F, M["strap"], INDEX["lantern"])


# ====================================================================== 渲染
def render_cache(vid: str, draft: bool) -> dict:
    """渲染当前场景，读回 EXR，存成 npz（线性 RGBA、各光组、深度、法线、反照率、物体编号）。"""
    bpy = _bpy()
    from style import bstyle as B  # noqa: PLC0415

    sc = bpy.context.scene
    TMP.mkdir(parents=True, exist_ok=True)
    im = sc.render.image_settings
    im.media_type = "MULTI_LAYER_IMAGE"
    if im.file_format != "OPEN_EXR_MULTILAYER":
        im.file_format = "OPEN_EXR_MULTILAYER"
    im.exr_codec = "NONE"
    im.color_depth = "32"
    im.color_mode = "RGBA"
    tag = vid + (f"_{draft}" if draft else "")
    exr = TMP / f"{tag}.exr"
    sc.render.filepath = str(exr)
    t0 = time.perf_counter()
    with B.render_lock():
        t1 = time.perf_counter()
        bpy.ops.render.render(write_still=True)
    t2 = time.perf_counter()
    ch = B.read_exr_none(exr)
    vn = sc.view_layers[0].name
    keys = sorted(ch)

    def grab(prefix, comps):
        if f"{vn}.{prefix}.{comps[0]}" not in ch:
            return None
        return np.stack([ch[f"{vn}.{prefix}.{c}"] for c in comps], -1)

    out = {"rgba": grab("Combined", "RGBA"), "depth": ch.get(f"{vn}.Depth.Z"), "normal": grab("Normal", "XYZ"),
           "albedo": grab("Diffuse Color", "RGB")}
    for nm in ("lantern", "moon", "fill"):
        g = grab(f"Combined_{nm}", "RGB")
        if g is not None:
            out[f"lg_{nm}"] = g
    em = grab("Emission", "RGB")
    if em is not None:
        out["emit"] = em
    idx_key = next((k for k in ch if k.startswith(f"{vn}.IndexOB") or k.startswith(f"{vn}.Object Index")), None)
    out["index"] = ch[idx_key] if idx_key else np.zeros(out["rgba"].shape[:2], np.float32)
    out = {k: v for k, v in out.items() if v is not None}
    np.savez_compressed(TMP / f"{tag}.npz", **{k: (v.astype(np.float32) if k == "depth" else v.astype(np.float16))
                                              for k, v in out.items()})
    exr.unlink(missing_ok=True)
    info = {"wait_s": round(t1 - t0, 1), "render_s": round(t2 - t1, 1), "channels": keys[:60]}
    print(f"[portrait_v2] {tag}：渲染 {info['render_s']}s（等锁 {info['wait_s']}s）")
    return info


# ====================================================================== 后期：小工具（只用 numpy / Pillow）
def V2D():
    """post/vfx_textures（模糊、噪声、笔毛纹理）。"""
    return CA().vfx()


def blur(a, s):
    if s <= 0:
        return a
    if a.ndim == 3:
        return np.stack([V2D().fft_blur(a[..., k], s) for k in range(a.shape[-1])], -1)
    return V2D().fft_blur(a, s)


def ss(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3 - 2 * t)


def hexc(h):
    h = h.lstrip("#")
    return np.array([int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4)])


def srgb(x):
    x = np.clip(x, 0, None)
    return np.where(x <= 0.0031308, 12.92 * x, 1.055 * np.power(x, 1 / 2.4) - 0.055)


def tone(x, exposure=1.0):
    """线性光 → 显示值：柔和的肩（高光不硬切），再转 sRGB。"""
    x = np.clip(x * exposure, 0, None)
    y = x / (1.0 + 0.55 * x)  # Reinhard 的软肩
    return srgb(y * 1.55)


def masked_blur(c, m, s):
    """只在掩码内模糊（不和别的部件混色）。c (h,w,k)，m (h,w)。"""
    den = blur(m, s)
    num = blur(c * m[..., None], s)
    return num / np.maximum(den, 1e-6)[..., None]


def lum(c):
    return c[..., 0] * 0.2126 + c[..., 1] * 0.7152 + c[..., 2] * 0.0722


def resample_line(P, step=0.6):
    P = np.asarray(P, np.float64)
    if len(P) < 2:
        return P
    s = np.concatenate([[0.0], np.cumsum(np.hypot(*np.diff(P, axis=0).T))])
    n = max(2, int(s[-1] / step) + 1)
    u = np.linspace(0, s[-1], n)
    return np.stack([np.interp(u, s, P[:, 0]), np.interp(u, s, P[:, 1])], -1)


class Brush:
    """在 (h, w) 的画面上算一笔的覆盖度（只算笔画包围盒里的像素）：两边各自抖一点，越往笔尾越干（飞白）。"""

    def __init__(self, h, w, seed=0):
        self.h, self.w = h, w
        self.rng = np.random.default_rng(seed)

    def stroke(self, pts, hw, *, dry=0.0, dry_start=0.5, jitter=0.10, soft=0.75, tex_scale=1.0):
        P = resample_line(pts, 0.6)
        n = len(P)
        if n < 2:
            return None, None
        hw = np.interp(np.linspace(0, 1, n), np.linspace(0, 1, len(np.atleast_1d(hw))), np.atleast_1d(hw)) \
            if np.ndim(hw) else np.full(n, float(hw))
        pad = float(hw.max()) * 1.6 + 2.0
        x0 = int(max(0, math.floor(P[:, 0].min() - pad)))
        x1 = int(min(self.w, math.ceil(P[:, 0].max() + pad)))
        y0 = int(max(0, math.floor(P[:, 1].min() - pad)))
        y1 = int(min(self.h, math.ceil(P[:, 1].max() + pad)))
        if x1 <= x0 or y1 <= y0:
            return None, None
        ys, xs = np.mgrid[y0:y1, x0:x1].astype(np.float64) + 0.5
        Q = np.stack([xs.ravel(), ys.ravel()], -1)
        tan = np.gradient(P, axis=0)
        tan /= np.linalg.norm(tan, axis=1, keepdims=True) + 1e-12
        nrm = np.stack([-tan[:, 1], tan[:, 0]], -1)
        idx = np.empty(len(Q), np.int64)
        stepq = max(1, 4_000_000 // n)
        for i in range(0, len(Q), stepq):
            d2 = ((Q[i:i + stepq, None, :] - P[None, :, :]) ** 2).sum(-1)
            idx[i:i + stepq] = d2.argmin(1)
        dp = Q - P[idx]
        along = (dp * tan[idx]).sum(1)
        perp = (dp * nrm[idx]).sum(1)
        over = np.where((idx == 0) | (idx == n - 1), np.maximum(np.abs(along) - 0.3, 0.0), 0.0)
        t = idx / (n - 1)
        nt = 256
        el = np.interp(t, np.linspace(0, 1, nt), blur(self.rng.standard_normal((1, nt)), 5)[0] * 3.0)
        er = np.interp(t, np.linspace(0, 1, nt), blur(self.rng.standard_normal((1, nt)), 5)[0] * 3.0)
        w = hw[idx] * np.clip(1.0 + jitter * np.where(perp > 0, el, er), 0.4, 1.6)
        dist = np.hypot(perp, over)
        cov = ss(w + soft, np.maximum(w - soft, -soft), dist)
        if dry > 0:
            tex = V2D().bristle_texture(self.rng, 40, 256)
            sx = np.clip(perp / np.maximum(w, 1e-6), -1, 1)
            b = V2D().sample_tex(tex, sx, np.clip(t * tex_scale, 0, 1))
            d = dry * ss(dry_start, 1.0, t)
            cov = cov * ss(d - 0.08, d + 0.08, b)
        return cov.reshape(ys.shape), (slice(y0, y1), slice(x0, x1))


class Paint:
    """显示值 RGB 画布：over 覆盖、mul 罩染（乘色）、add 加光。"""

    def __init__(self, rgb):
        self.c = np.array(rgb, np.float64)
        self.h, self.w = self.c.shape[:2]

    def over(self, color, a, sl=None):
        a = np.clip(a, 0, 1)[..., None]
        if sl is None:
            self.c = self.c * (1 - a) + np.asarray(color, np.float64) * a
        else:
            col = color if np.ndim(color) == 1 else color[sl]
            self.c[sl] = self.c[sl] * (1 - a) + np.asarray(col, np.float64) * a

    def mul(self, color, a):
        a = np.clip(a, 0, 1)[..., None]
        self.c = self.c * (1 - a + a * np.asarray(color, np.float64))

    def add(self, color, a):
        self.c = self.c + np.asarray(color, np.float64) * np.clip(a, 0, None)[..., None]


# ====================================================================== 后期：投影和三维特征点
def snap(fn, P, iters=6, h=2e-4):
    """把点沿隐式曲面的梯度投到曲面上（牛顿法）。"""
    P = np.array(P, np.float64)
    for _ in range(iters):
        f0 = fn(P)
        g = np.stack([(fn(P + np.eye(3)[k] * h) - fn(P - np.eye(3)[k] * h)) / (2 * h) for k in range(3)], -1)
        P = P - (f0 / np.maximum((g * g).sum(-1), 1e-12))[:, None] * g
    return P


def surface_front(fn, xz, y0=-0.13, y1=-0.02, step=0.0004):
    """从脸前方沿 +Y 打一条线，求第一次碰到曲面的点（头部局部坐标）。xz (n,2)。"""
    xz = np.asarray(xz, np.float64)
    ys = np.arange(y0, y1, step)
    P = np.stack([np.repeat(xz[:, 0:1], len(ys), 1), np.repeat(ys[None, :], len(xz), 0),
                  np.repeat(xz[:, 1:2], len(ys), 1)], -1)
    d = fn(P.reshape(-1, 3)).reshape(len(xz), len(ys))
    k = np.argmax(d < 0, axis=1)
    k = np.maximum(k, 1)
    da, db = d[np.arange(len(xz)), k - 1], d[np.arange(len(xz)), k]
    t = da / np.maximum(da - db, 1e-12)
    y = ys[k - 1] + t * step
    return np.stack([xz[:, 0], y, xz[:, 1]], -1)


class Proj:
    """一个方向的投影：头部 / 身子局部坐标 → 渲染像素，带深度遮挡。"""

    def __init__(self, vid, R, zbuf):
        self.var = VARIANTS[vid]
        self.R = R
        self.z = zbuf
        self.HM = head_matrix(self.var)
        self.BM = body_matrix(self.var)

    def px(self, P, space="head"):
        M = self.HM if space == "head" else (self.BM if space == "body" else np.eye(4))
        W = xform(M, np.asarray(P, np.float64))
        xy, dep = project(self.var, W, self.R)
        return xy, dep

    def visible(self, xy, dep, tol=0.004):
        xi = np.clip(xy[:, 0].astype(int), 0, self.R - 1)
        yi = np.clip(xy[:, 1].astype(int), 0, self.R - 1)
        zb = self.z[yi, xi]
        inside = (xy[:, 0] >= 0) & (xy[:, 0] < self.R) & (xy[:, 1] >= 0) & (xy[:, 1] < self.R)
        return inside & (dep <= zb + tol)

    def facing(self, P, N, space="head"):
        """法线朝镜头的程度（-1..1）。"""
        M = self.HM if space == "head" else self.BM
        W = xform(M, P)
        Nw = np.asarray(N) @ M[:3, :3].T
        pos, _ = camera_pose(self.var)
        v = pos - W
        v /= np.linalg.norm(v, axis=-1, keepdims=True)
        return (Nw * v).sum(-1)


def lid_points(var, sx, which, n=40, r_k=0.6, t0=0.0, t1=1.0, lift=0.0):
    """眼睑边缘的三维点（头部局部坐标）：which = up / lo；lift 往外（离开开口）挪的弧长。"""
    t = np.linspace(t0, t1, n)
    u, up, lo = lid_curves(t, var)
    v = (up + lift) if which == "up" else (lo - lift)
    a, b = u / EYE_R, v / EYE_R
    d = np.stack([sx * np.sin(a) * np.cos(b), -np.cos(a) * np.cos(b), np.sin(b)], -1)
    return eye_center(sx) + d * (EYE_R + LID_T * r_k)


def iris_ring(var, sx, ang, n=48):
    """虹膜 / 瞳孔的边：离视线方向 ang 弧度的一圈点（在眼球表面）。返回 (圈, 中心)。"""
    gx, gy = var["gaze"]
    Rg = rot("z", gx) @ rot("x", gy)
    g = Rg @ np.array([0.0, -1.0, 0.0])
    e1 = Rg @ np.array([1.0, 0.0, 0.0])
    e2 = Rg @ np.array([0.0, 0.0, 1.0])
    th = np.linspace(0, 2 * math.pi, n, endpoint=False)
    d = (g[None, :] * math.cos(ang) + (e1[None, :] * np.cos(th)[:, None] + e2[None, :] * np.sin(th)[:, None]) * math.sin(ang))
    c = eye_center(sx)
    return c + d * EYE_R * 1.004, c + g * EYE_R


def brow_points(var, sx, n=24):
    """眉的三维点：眉头 → 眉尾，贴在眉弓上。冷峻的眉头压低、眉尾上挑（剑眉），温和的眉头略抬、弧度柔。"""
    b = var["brow"]
    t = np.linspace(0, 1, n)
    x = (0.0105 + 0.050 * t) * sx
    z = 0.0150 + b["inner"] * (1 - t) + 0.0050 * t + b["outer"] * t + b["arch"] * np.sin(np.pi * t ** 0.8) \
        + 0.0030 * np.sin(np.pi * t)
    P = surface_front(lambda p: sd_skin(p, var), np.stack([x, z], -1))
    return P + np.array([0.0, -0.0006, 0.0])


# ====================================================================== 后期：一个方向
GRADE = {
    "cold": dict(gain=(1.3, 1.9, 1.4), exposure=1.0),
    "gentle": dict(gain=(1.4, 1.8, 1.4), exposure=1.0),
    "hat": dict(gain=(1.6, 2.0, 0.8), exposure=1.0),
}
INK_JIAO = hexc("#17140F")
INK_NONG = hexc("#2E2924")
INK_SKIN = hexc("#5A3426")  # 脸上的线用赭墨，比衣纹的线暖、淡
PAPER = hexc("#EDE4CF")
NIGHT_TOP = hexc("#10162A")
NIGHT_LOW = hexc("#1E2742")
MOON_HAZE = hexc("#5E6F9C")
LAMP_GLOW = hexc("#FFB060")


def load_cache(vid, mode):
    tag = vid + (f"_{mode}" if mode else "")
    d = np.load(TMP / f"{tag}.npz")
    return {k: d[k].astype(np.float32) for k in d.files}


def edge_map(idx, z, alpha, ignore=()):
    """墨线的位置：部件分界、剪影、同一部件里深度跳变的地方。返回 (h, w) 0..1，以及“这条边属于前面哪个部件”。"""
    h, w = idx.shape
    E = np.zeros((h, w))
    own = np.zeros((h, w), np.int32)
    zz = np.where(alpha > 0.5, z, 1e3)
    for dy, dx in ((0, 1), (1, 0), (1, 1), (1, -1)):
        a_i = idx
        b_i = np.roll(np.roll(idx, -dy, 0), -dx, 1)
        a_z = zz
        b_z = np.roll(np.roll(zz, -dy, 0), -dx, 1)
        diff = a_i != b_i
        for p, q in ignore:
            diff &= ~(((a_i == p) & (b_i == q)) | ((a_i == q) & (b_i == p)))
        rel = np.abs(a_z - b_z) / np.minimum(a_z, b_z)
        thr = np.where(a_i == INDEX["skin"], 0.022, 0.010)  # 脸上只留真正的剪影（鼻、下颌、耳），别的交给五官的笔
        dep = (rel > thr) & (a_i == b_i) & (a_i > 0)
        e = (diff | dep).astype(np.float64)
        E = np.maximum(E, e)
        front = np.where(a_z <= b_z, a_i, b_i)  # 线归前面的部件（剪影线画在物体那一侧）
        own = np.where(e > 0, front, own)
    return E, own


def poly_mask(h, w, poly, ssn=4):
    """多边形 → 抗锯齿掩码。"""
    from PIL import Image, ImageDraw  # noqa: PLC0415

    im = Image.new("L", (w * ssn, h * ssn), 0)
    ImageDraw.Draw(im).polygon([(float(x) * ssn, float(y) * ssn) for x, y in poly], fill=255)
    return np.asarray(im.resize((w, h), Image.BOX), np.float64) / 255.0


def visible_runs(xy, vis, min_len=3):
    """可见的连续段。"""
    runs, cur = [], []
    for p, v in zip(xy, vis):
        if v:
            cur.append(p)
        elif cur:
            if len(cur) >= min_len:
                runs.append(np.asarray(cur))
            cur = []
    if len(cur) >= min_len:
        runs.append(np.asarray(cur))
    return runs


def hair_strands(var, n=150, seed=5):
    """头发表面的发丝：从发际线出发，贴着发壳走向发髻（头部局部坐标的点列）。"""
    rng = np.random.default_rng(seed)
    hat = var.get("hat", False)
    fn = lambda p: sd_hair_cap(p, sd_head_base(p))  # noqa: E731
    tie = HAIR_TIE + np.array([0.0, 0.012, -0.006])
    out = []
    phis = np.sort(rng.uniform(-math.pi, math.pi, n))
    for phi in phis:
        zh = float(hairline_z(np.array([phi]))[0]) + 0.003 + rng.uniform(0, 0.004)
        r0 = 0.11
        p0 = np.array([math.sin(phi) * r0, -math.cos(phi) * r0, zh])
        t = np.linspace(0, 1, 22)[:, None]
        wob = rng.normal(0, 0.006)
        P = p0 * (1 - t) + tie * t
        P = P + np.array([wob, 0.0, 0.0]) * np.sin(np.pi * t) + np.array([0, 0, 0.03]) * np.sin(np.pi * t)
        P = snap(fn, P, iters=5)
        if zh > -0.03:  # 前面和两鬓：发根从发际线下面一点的皮肤上起笔
            sk = snap(lambda q: sd_skin(q, var), np.array([p0 * np.array([1, 1, 0]) * 0.8 + np.array([0, 0, zh - 0.0075]),
                                                         p0 * np.array([1, 1, 0]) * 0.8 + np.array([0, 0, zh - 0.0035])]), iters=6)
            P = np.vstack([sk + (sk / np.linalg.norm(sk, axis=1, keepdims=True)) * 0.0004, P])
        if hat:
            P = P[P[:, 2] < 0.075]  # 斗笠底下只露出发际线附近
            if len(P) < 3:
                continue
        out.append(P)
    return out


def tube_strands(spine, r0, r1, k, seed=0, spread=1.0):
    """沿一束头发（管子）的发丝：在截面里错开 k 条，末梢散开一点。"""
    rng = np.random.default_rng(seed)
    C = smooth_curve(spine, 40)
    T = np.gradient(C, axis=0)
    T /= np.linalg.norm(T, axis=1, keepdims=True) + 1e-12
    out = []
    for _ in range(k):
        a, b = rng.normal(0, 0.5, 2) * spread
        side = np.cross(T, [0.0, 0.0, 1.0])
        side /= np.linalg.norm(side, axis=1, keepdims=True) + 1e-12
        up = np.cross(side, T)
        t = np.linspace(0, 1, len(C))[:, None]
        r = r0 + (r1 - r0) * t
        fan = 1.0 + 1.6 * t ** 2  # 末梢散开
        P = C + side * (a * r * fan) + up * (b * r * fan * 0.6)
        cut = int(len(C) * rng.uniform(0.75, 1.0))
        out.append(P[:cut])
    return out


def post_variant(vid, mode=""):
    """一个方向的后期：三维渲染 → 512² 的画（直通 alpha 的圆）。返回 PIL 图。"""
    from PIL import Image  # noqa: PLC0415

    var = VARIANTS[vid]
    G = GRADE[vid]
    Dc = load_cache(vid, mode)
    R = Dc["rgba"].shape[0]
    k = R / 1024.0
    alpha = np.clip(Dc["rgba"][..., 3], 0, 1)
    idx = np.rint(Dc["index"]).astype(np.int32)
    zbuf = np.where(alpha > 0.02, Dc["depth"], 1e9)
    gl, gm, gf = G["gain"]
    lin = Dc["lg_lantern"] * gl + Dc["lg_moon"] * gm + Dc["lg_fill"] * gf
    a3 = np.maximum(alpha, 1e-4)[..., None]
    lin_s = np.where(alpha[..., None] > 0.01, lin / a3, 0.0)
    disp = tone(lin_s, G["exposure"])
    lit_lan = np.clip(lum(Dc["lg_lantern"] / a3) * 2.2, 0, 1)  # 灯光照到的程度（线条在受光处变淡）
    rng = np.random.default_rng(11)
    lab = {n: idx == i for n, i in INDEX.items()}
    hair_m = lab["hair"] | lab["ponytail"] | lab["lock"]
    # ---- 1. 重新上色：三维只给明暗和光色，颜色按工笔淡彩重新染（暗面不发黑，亮面不过曝）
    disp = paint_surfaces(Dc, lab, G, k, alpha, disp, lin_s)
    if var.get("hat"):
        disp = brim_shadow(disp, lab, k)
    # ---- 3. 底：夜色水墨，月光一侧有一层淡雾托住头发的剪影，灯笼那边一团暖光
    P = Paint(np.zeros((R, R, 3)))
    yy, xx = np.mgrid[0:R, 0:R].astype(np.float64) + 0.5
    t = (yy / R)[..., None]
    P.c = NIGHT_TOP * (1 - t) + NIGHT_LOW * t
    fb = V2D().fbm(rng, (R, R), (90.0 * k, 36.0 * k, 12.0 * k), (0.55, 0.3, 0.15))
    P.c = P.c * (1 + 0.10 * fb[..., None])
    lan_xy, _ = project(var, _lantern_pos(var), R)
    mx, my = moon_screen(var, R)
    haze = np.exp(-(((xx - mx) / (0.36 * R)) ** 2 + ((yy - my) / (0.30 * R)) ** 2))
    haze = haze * (0.8 + 0.2 * fb)
    P.over(MOON_HAZE, 0.55 * haze)
    dl = np.hypot(xx - lan_xy[0], yy - lan_xy[1]) / R
    glow = np.exp(-(dl / 0.20) ** 2)
    P.add(LAMP_GLOW * 0.55, glow * (0.85 + 0.15 * fb))
    P.add(LAMP_GLOW * 0.25, np.exp(-(dl / 0.45) ** 2))
    # 远处一道淡淡的山影和雾（很淡，只为“夜行”的意境）
    ridge_y = R * (0.70 + 0.04 * np.sin(xx[0] / R * 5.0 + 1.0) + 0.02 * np.sin(xx[0] / R * 13.0))
    mtn = ss(-2.0 * k, 2.0 * k, yy - ridge_y[None, :]) * (1 - ss(0.0, 0.25 * R, yy - ridge_y[None, :]))
    P.over(hexc("#0C1122"), 0.35 * mtn)
    bg = P.c.copy()
    # ---- 4. 合成主体
    col = bg * (1 - alpha[..., None]) + disp * alpha[..., None]
    P = Paint(col)
    # ---- 5. 头发：墨色打底，月光、灯光的高光只从一缕缕发丝里透出来；发际线羽化，再用细笔丝出发根
    hm = hair_m.astype(np.float64)
    hairL = lum(disp)
    hue = disp / np.maximum(hairL, 1e-4)[..., None]
    Bz = Brush(R, R, seed=21)
    pj = Proj(vid, R, zbuf)
    lines_hair, roots = [], []
    for S3 in hair_strands(var, n=340):
        xy, dep = pj.px(S3)
        vis = pj.visible(xy, dep, 0.006)
        lines_hair += visible_runs(xy, vis)
        nr = max(4, int(len(xy) * 0.32))
        roots += visible_runs(xy[:nr], vis[:nr])
    for i, (sp, r0) in enumerate(ponytail_spines(var)):
        for S3 in tube_strands(sp, r0, r0 * 0.2, 6, seed=40 + i):
            xy, dep = pj.px(S3)
            lines_hair += visible_runs(xy, pj.visible(xy, dep, 0.012))
    for i, (sp, r0, kind) in enumerate(sidelock_spines(var)):
        for S3 in tube_strands(sp, r0, r0 * 0.2, 5, seed=60 + i, spread=0.8):
            xy, dep = pj.px(S3)
            lines_hair += visible_runs(xy, pj.visible(xy, dep, 0.008))
    strands = np.zeros((R, R))
    for run in lines_hair:
        cov, sl = Bz.stroke(run, np.array([0.35, 0.7, 0.55, 0.2]) * k * 1.3, dry=0.5, dry_start=0.4, jitter=0.2, soft=0.6)
        if cov is not None:
            strands[sl] = np.maximum(strands[sl], cov * rng.uniform(0.35, 1.0))
    spec = np.clip(hairL - 0.04, 0, None)
    spec_s = blur(spec * hm, 4.0 * k) / np.maximum(blur(hm, 4.0 * k), 1e-3)
    hair_ink = hexc("#111016")
    hair_col = hair_ink * (1 + 1.8 * spec_s)[..., None] + hue * (spec * strands)[..., None] * 0.95
    near_skin = blur(lab["skin"].astype(np.float64), 4.5 * k)
    cap = lab["hair"].astype(np.float64)
    P.over(hair_col, hm * alpha * (1 - cap * 0.95 * ss(0.03, 0.45, near_skin)))
    for run in roots:
        cov, sl = Bz.stroke(run, np.array([0.15, 0.55, 0.85, 0.9]) * k, jitter=0.15, soft=0.55)
        if cov is not None:
            P.over(hair_ink, cov * 0.9, sl)
    # ---- 6. 墨线：部件分界、剪影、深度跳变
    E, own = edge_map(idx, zbuf, alpha, ignore=((INDEX["skin"], INDEX["eye"]), (INDEX["hair"], INDEX["ponytail"]),
                                               (INDEX["lantern"], 0), (INDEX["crown"], INDEX["crown"])))
    thick = np.ones((R, R))
    for name, wv in (("skin", 0.55), ("eye", 0.4), ("hair", 0.9), ("ponytail", 0.8), ("lock", 0.7), ("cloak", 1.5),
                     ("robe", 1.15), ("collar", 1.0), ("hat", 1.2), ("lantern", 0.6), ("sword", 0.9), ("ribbon", 0.8)):
        thick = np.where(own == INDEX[name], wv, thick)
    thin_l = np.clip(blur(E * (thick < 0.8), 0.55 * k) * 2.6, 0, 1)
    mid_l = np.clip(blur(E * ((thick >= 0.8) & (thick < 1.2)), 0.85 * k) * 2.4, 0, 1)
    thk_l = np.clip(blur(E * (thick >= 1.2), 1.25 * k) * 2.3, 0, 1)
    nz = V2D().noise(rng, (R, R), 3.0 * k)
    dryk = ss(-1.2, 0.6, nz)
    face_line = thin_l * (1 - 0.6 * blur(lit_lan, 2.0 * k)) * (0.75 + 0.25 * dryk)
    is_skin_line = blur((own == INDEX["skin"]).astype(np.float64), 0.8 * k) > 0.2
    P.over(INK_SKIN, np.where(is_skin_line, face_line * 0.85, thin_l * 0.8))
    P.over(INK_JIAO, mid_l * (0.6 + 0.4 * dryk) * 0.9)
    P.over(INK_JIAO, thk_l * (0.55 + 0.45 * dryk) * 0.95)
    # ---- 7. 五官
    paint_eyes(P, pj, var, idx, k, lit_lan)
    paint_brows(P, pj, var, idx, k, rng)
    paint_nose_mouth(P, pj, var, idx, k)
    # ---- 8. 鬓发、额发、马尾：墨笔一缕缕压在上面，尾端飞白
    paint_locks(P, pj, var, k)
    paint_collar(P, pj, var, idx, k)
    if var.get("hat"):
        paint_hat(P, pj, var, idx, k)
    # ---- 9. 灯笼的光晕、纸纹、调色
    em = np.clip(lum(Dc["lg_lantern"]) - 1.2, 0, None) * (idx == INDEX["lantern"])
    P.add(LAMP_GLOW, blur(em, 14.0 * k) * 0.9 + blur(em, 40.0 * k) * 0.6)
    paper = paper_tex(R)
    P.c = P.c * (0.90 + 0.10 * paper[..., None]) + 0.025 * (paper[..., None] - 0.5)
    L = lum(P.c)
    P.c = P.c + (hexc("#141C34") - P.c) * (0.25 * (1 - ss(0.0, 0.25, L)))[..., None]  # 暗部偏靛
    img = np.clip(P.c, 0, 1)
    im = Image.fromarray((img * 255 + 0.5).astype(np.uint8)).resize((SIZE, SIZE), Image.LANCZOS)
    # 圆：比窗口大一圈（藏在漆环下面），外面透明
    yy, xx = np.mgrid[0:SIZE, 0:SIZE].astype(np.float64) + 0.5
    r = np.hypot(xx - SIZE / 2, yy - SIZE / 2) / (SIZE / 2)
    a = ss(0.985, 0.955, r)
    rgba = np.dstack([np.asarray(im), (a * 255 + 0.5).astype(np.uint8)])
    return Image.fromarray(rgba, "RGBA")


def brim_shadow(disp, lab, k):
    """斗笠帽檐下的影：帽檐下沿往下一段（约半张脸）压暗偏冷，越往下越淡，下巴和嘴留在灯光里。"""
    R = disp.shape[0]
    hat = lab["hat"]
    has = hat.any(0)
    ys = np.arange(R)[:, None]
    low = np.where(has, R - 1 - np.argmax(hat[::-1], axis=0), -1)  # 每列帽子最低的像素
    sg = 6.0 * k
    ker = np.exp(-0.5 * (np.arange(-int(3 * sg), int(3 * sg) + 1) / sg) ** 2)
    ker /= ker.sum()
    low = np.convolve(np.pad(np.where(has, low, low.max()).astype(np.float64), len(ker) // 2, mode="edge"), ker, "valid")
    d = (ys - low[None, :]) / R
    sh = ss(0.17, 0.02, d) * (d > -0.01) * has[None, :]
    m = (lab["skin"] | lab["eye"] | lab["lock"]).astype(np.float64) * sh
    m = blur(m, 2.0 * k)
    shade = disp * hexc("#3C4262")
    return disp * (1 - 0.88 * m[..., None]) + shade * (0.88 * m[..., None])


def ramp(t, stops):
    """t (h,w) 0..1 → 颜色，stops = [(位置, hex), ...]。"""
    xs = [p for p, _ in stops]
    cs = np.stack([hexc(c) for _, c in stops])
    return np.stack([np.interp(t, xs, cs[:, j]) for j in range(3)], -1)


def paint_surfaces(Dc, lab, G, k, alpha, disp, lin_s):
    """按部件重新染色。皮肤、白袍：反照率 × 柔化后的受光（灯光偏暖、月光偏冷），暗面留三四成亮；
    皮肤轮廓内侧再染一圈淡赭（工笔的“渲染”）。墨氅压暗、只留月光的边；灯笼按亮度从朱红染到暖金。"""
    a3 = np.maximum(alpha, 1e-4)
    gl, gm, gf = G["gain"]
    A = Dc["albedo"] / a3[..., None]
    LA = np.maximum(lum(A), 1e-3)
    e = {n: lum(Dc[f"lg_{n}"] / a3[..., None]) / LA for n in ("lantern", "moon", "fill")}
    out = disp.copy()
    warm, cool = hexc("#FFD9AE") / 0.95, hexc("#C3CEF0") / 0.94

    def put(m, col, soft=1.2):
        w = ss(0.5, 0.98, blur(m, soft * k)) * m
        return out * (1 - w[..., None]) + col * w[..., None]

    def lit(m, sig):
        """逐通道的受光（带着灯光、月光自己的颜色）：各光组 / 反照率，磨平以后压进 0..1。"""
        E = sum(g * masked_blur(np.clip(Dc[f"lg_{n}"] / a3[..., None], 0, None) / np.maximum(A, 1e-3), m, sig * k)
                for g, n in ((gl, "lantern"), (gm, "moon"), (gf, "fill")))
        return 1 - np.exp(-1.35 * np.clip(E, 0, None))
    # 皮肤
    m = lab["skin"].astype(np.float64)
    if m.sum() > 0:
        val = lit(m, 2.4)
        base = srgb(masked_blur(A, m, 1.4 * k))
        v = lum(val)
        col = base * (0.24 + 0.76 * val)
        col = col + (hexc("#6A4A5E") * base - col) * (0.28 * (1 - ss(0.0, 0.45, v)))[..., None]  # 暗面带一点绛紫
        edge = 1 - ss(0.45, 0.97, blur(m, 5.0 * k))
        col = col * (1 - (0.28 * edge)[..., None] * (1 - hexc("#B07A62")))
        out = put(m, np.clip(col, 0, 1))
    # 白袍、白领
    for nm in ("robe", "collar"):
        m = lab[nm].astype(np.float64)
        if m.sum() == 0:
            continue
        val = lit(m, 3.0)
        base = hexc("#ECE4D2")
        v = lum(val)
        col = base * (0.20 + 0.80 * val)
        col = col + (hexc("#56607E") * base - col) * (0.35 * (1 - ss(0.0, 0.5, v)))[..., None]
        out = put(m, np.clip(col, 0, 1))
    # 墨氅：压成墨色，只留月光、灯光照出的边
    m = lab["cloak"].astype(np.float64)
    if m.sum() > 0:
        sm = masked_blur(disp, m, 2.0 * k)
        L = lum(sm)
        col = hexc("#1B1A20") + (sm / np.maximum(L, 1e-4)[..., None]) * (0.30 * (1 - np.exp(-2.2 * np.clip(L - 0.05, 0, None))))[..., None]
        out = put(m, np.clip(col, 0, 1))
    # 斗笠：竹篾的赭色，按明暗从焦赭到暖黄
    m = lab["hat"].astype(np.float64)
    if m.sum() > 0:
        sm = masked_blur(disp, m, 1.6 * k)
        L = lum(sm)
        col = ramp(np.clip(1 - np.exp(-1.8 * L), 0, 1), [(0.0, "#110C09"), (0.3, "#2E1F13"), (0.6, "#5E4226"),
                                                          (0.85, "#93703F"), (1.0, "#CDAA70")])
        hue = sm / np.maximum(L, 1e-4)[..., None]
        col = col * (0.75 + 0.25 * hue / np.maximum(hue.mean(-1, keepdims=True), 1e-3))
        out = put(m, np.clip(col, 0, 1))
    # 发带：朱砂
    m = lab["ribbon"].astype(np.float64)
    if m.sum() > 0:
        L = lum(masked_blur(disp, m, 1.2 * k))
        col = ramp(np.clip(L * 1.6, 0, 1), [(0.0, "#3A0D0A"), (0.35, "#8E2418"), (0.7, "#C23A2B"), (1.0, "#F08A5A")])
        out = put(m, col)
    # 灯笼
    m = lab["lantern"].astype(np.float64)
    if m.sum() > 0:
        L = lum(lin_s)
        t = 1 - np.exp(-L / 2.5)
        col = ramp(t, [(0.0, "#2A0E08"), (0.25, "#7A1A0E"), (0.5, "#C2381E"), (0.75, "#F0782E"), (0.9, "#FFB55A"),
                       (1.0, "#FFE2A8")])
        out = put(m, col, 0.6)
    return np.clip(out, 0, 1)


def _lantern_pos(var):
    """灯笼芯的世界坐标：按画面位置（占画面的比例，左上为 0）和比头近多少米来摆。"""
    fx, fy = var["lantern_px"]
    pos, Rc = camera_pose(var)
    f = LENS_MM / SENSOR_MM
    ray = Rc @ np.array([(fx - 0.5) / f, -(fy - 0.5) / f, -1.0])
    return pos + ray * (CAM_DIST + var["lantern_dy"])


def moon_screen(var, R):
    """月光雾在画面上的中心：头后面、背灯的一侧偏上。"""
    hc, _ = project(var, xform(head_matrix(var), [0.0, 0.02, 0.05]), R)
    m = np.asarray(var["moon"], np.float64)
    return hc[0] + np.sign(m[0]) * 0.20 * R, hc[1] - 0.12 * R


def paper_tex(R):
    """宣纸纹（2 倍密度的月夜宣纸，归一到 0..1 附近，均值 0.5）。"""
    from PIL import Image  # noqa: PLC0415

    p = ART / "out" / "assets@2x" / "ground" / "paper.png"
    if not p.exists():
        return np.full((R, R), 0.5)
    a = np.asarray(Image.open(p).convert("L").resize((R, R), Image.BICUBIC), np.float64) / 255.0
    a = (a - a.mean()) / (a.std() + 1e-6)
    return np.clip(0.5 + 0.18 * a, 0, 1)


def paint_eyes(P, pj, var, idx, k, lit):
    """眼：上眼线（内细外粗、眼尾上挑）、双眼皮一道淡线、下眼睑半截淡线；虹膜分层（外圈深、下半透灯光、瞳孔），
    两点高光（灯笼的暖光在下、月光的冷光在上）。只画在皮肤和眼球上（被鬓发挡住的地方不画）。"""
    R = P.h
    Bz = Brush(R, R, seed=31)
    eye_m = (idx == INDEX["eye"]).astype(np.float64)
    face_ok = ((idx == INDEX["skin"]) | (idx == INDEX["eye"])).astype(np.float64)
    face_ok = np.clip(blur(face_ok, 1.0 * k) * 1.4, 0, 1)
    for sx in (-1, 1):
        mid = lid_points(var, sx, "up", 3)[1:2]
        nrm = (mid - eye_center(sx)) / np.linalg.norm(mid - eye_center(sx))
        f = float(pj.facing(mid, nrm)[0])
        if f < 0.15:
            continue
        fk = 0.55 + 0.45 * min(1.0, f / 0.8)
        # 虹膜
        ring, cen = iris_ring(var, sx, 0.54)
        xy, dep = pj.px(ring)
        cxy, _ = pj.px(cen[None, :])
        im = poly_mask(R, R, xy) * eye_m
        im = np.clip(blur(im, 0.4 * k), 0, 1) * eye_m
        cx, cy = cxy[0]
        rr = np.sqrt(max(1.0, (poly_mask(R, R, xy) > 0.5).sum() / math.pi))
        yy, xx = np.mgrid[0:R, 0:R].astype(np.float64) + 0.5
        dd = np.hypot(xx - cx, yy - cy) / rr
        iris = np.clip(hexc("#24150D") * (1 - ss(0.0, 1.0, (yy - cy) / rr)[..., None] * 0.0), 0, 1)
        low = ss(-0.1, 0.8, (yy - cy) / rr) * ss(1.0, 0.55, dd)
        iris_c = hexc("#2A170D")[None, None, :] * (1 - low[..., None]) + hexc("#8C5A2C")[None, None, :] * low[..., None]
        iris_c = iris_c * (1 - 0.6 * ss(0.78, 1.0, dd))[..., None]  # 外圈一道深环
        P.over(iris_c, im * 0.95)
        P.over(hexc("#070506"), im * ss(0.42, 0.34, dd))  # 瞳孔
        # 上眼睑在眼球上投下的影
        up3 = lid_points(var, sx, "up", 40)
        uxy, udep = pj.px(up3)
        shade = poly_mask(R, R, np.vstack([uxy, uxy[::-1] + np.array([0.0, 3.2 * k])]))
        P.over(hexc("#2A2224"), shade * eye_m * 0.55)
        # 高光：灯在左下，暖的一点在虹膜左下；月光一点冷的在右上
        for (ox, oy), r_, c_, a_ in (((-0.35, 0.30), 0.20, "#FFE2B0", 0.95), ((0.32, -0.38), 0.12, "#DCE6FF", 0.75)):
            hl = ss(1.0, 0.55, np.hypot(xx - (cx + ox * rr), yy - (cy + oy * rr)) / (r_ * rr + 0.6 * k))
            P.over(hexc(c_), hl * eye_m * a_)
        vis = pj.visible(uxy, udep, 0.006)
        hw = np.interp(np.linspace(0, 1, len(uxy)), [0, 0.25, 0.7, 0.92, 1.0], [0.7, 1.8, 3.0, 2.8, 0.9]) * k * fk
        for run_i, run in enumerate(visible_runs(np.column_stack([uxy, hw]), vis)):
            pts, w_ = run[:, :2], run[:, 2]
            # 眼尾往外挑出去一点（睫毛）
            if sx * (pts[-1, 0] - pts[0, 0]) * np.sign(var["yaw"] + 1e-6) != 0:
                pass
            cov, sl = Bz.stroke(pts, w_, jitter=0.05, soft=0.6)
            if cov is not None:
                P.over(INK_JIAO, cov * face_ok[sl] * 0.97, sl)
        # 眼尾一挑
        tail = lid_points(var, sx, "up", 6, t0=0.86, t1=1.0)
        tail = np.vstack([tail, tail[-1] + (tail[-1] - tail[-2]) * 3.0 + np.array([0.0, 0.0, 0.0012])])
        txy, tdep = pj.px(tail)
        if pj.visible(txy[:1], tdep[:1], 0.006)[0]:
            cov, sl = Bz.stroke(txy, np.array([1.8, 1.4, 0.4]) * k * fk, jitter=0.05)
            if cov is not None:
                P.over(INK_JIAO, cov * 0.9, sl)
        # 双眼皮
        cr = lid_points(var, sx, "up", 30, r_k=1.2, t0=0.22, t1=0.96, lift=0.0026)
        cxy2, cdep = pj.px(cr)
        for run in visible_runs(cxy2, pj.visible(cxy2, cdep, 0.006)):
            cov, sl = Bz.stroke(run, np.array([0.2, 0.7, 0.6, 0.2]) * k * fk, jitter=0.1)
            if cov is not None:
                P.over(INK_SKIN, cov * face_ok[sl] * 0.55, sl)
        # 下眼睑
        lo = lid_points(var, sx, "lo", 30, t0=0.30, t1=1.0, lift=0.0003)
        lxy, ldep = pj.px(lo)
        for run in visible_runs(lxy, pj.visible(lxy, ldep, 0.006)):
            cov, sl = Bz.stroke(run, np.array([0.2, 0.55, 0.75, 0.5]) * k * fk, jitter=0.1)
            if cov is not None:
                P.over(INK_SKIN, cov * face_ok[sl] * 0.55, sl)


def paint_brows(P, pj, var, idx, k, rng):
    """眉：先一笔淡墨铺底（眉头宽、眉尾收尖），再用细笔顺着眉的走向一根根丝出来。"""
    R = P.h
    Bz = Brush(R, R, seed=41)
    face_ok = np.clip(blur((idx == INDEX["skin"]).astype(np.float64), 1.0 * k) * 1.4, 0, 1)
    for sx in (-1, 1):
        B3 = brow_points(var, sx)
        xy, dep = pj.px(B3)
        vis = pj.visible(xy, dep, 0.006)
        nrm = np.array([0.0, -1.0, 0.25])
        f = float(pj.facing(B3[12:13], nrm[None, :] / np.linalg.norm(nrm))[0])
        fk = 0.5 + 0.5 * min(1.0, max(0.0, f) / 0.8)
        hw = np.interp(np.linspace(0, 1, len(xy)), [0, 0.15, 0.55, 1.0], [2.4, 3.4, 2.2, 0.4]) * k * fk
        for run in visible_runs(np.column_stack([xy, hw]), vis):
            cov, sl = Bz.stroke(run[:, :2], run[:, 2], jitter=0.15, dry=0.55, dry_start=0.35)
            if cov is not None:
                P.over(hexc("#2A2321"), cov * face_ok[sl] * 0.72, sl)
            # 丝：沿眉走、略斜的短笔
            pts = resample_line(run[:, :2], 1.0)
            if len(pts) < 4:
                continue
            tan = np.gradient(pts, axis=0)
            tan /= np.linalg.norm(tan, axis=1, keepdims=True) + 1e-9
            nrm2 = np.stack([-tan[:, 1], tan[:, 0]], -1)
            for j in range(0, len(pts) - 2, 2):
                u = j / max(1, len(pts) - 1)
                wv = np.interp(u, [0, 0.15, 0.55, 1.0], [2.4, 3.4, 2.2, 0.4]) * k * fk
                o = pts[j] + nrm2[j] * rng.uniform(-0.8, 0.8) * wv
                L_ = (3.0 + 4.0 * (1 - u)) * k
                d = tan[j] * L_ - nrm2[j] * L_ * 0.35 * (1 if u < 0.2 else 0.15)
                cov, sl = Bz.stroke(np.stack([o, o + d * 0.5, o + d]), np.array([0.45, 0.4, 0.1]) * k, soft=0.5)
                if cov is not None:
                    P.over(hexc("#0E0C0C"), cov * face_ok[sl] * 0.8, sl)


def paint_nose_mouth(P, pj, var, idx, k):
    """鼻翼一小笔、鼻孔一点；嘴缝一笔（中段重、嘴角收），下唇底下一道淡影。"""
    R = P.h
    Bz = Brush(R, R, seed=51)
    fn = lambda p: sd_skin(p, var)  # noqa: E731
    face_ok = np.clip(blur((idx == INDEX["skin"]).astype(np.float64), 1.0 * k) * 1.4, 0, 1)
    lip_ink = hexc("#5B2420")
    for sx in (-1, 1):
        ala = snap(fn, warp_pts(np.array([(0.0150 * sx, -0.0930, -0.0328), (0.0160 * sx, -0.0933, -0.0362),
                                          (0.0148 * sx, -0.0948, -0.0395), (0.0120 * sx, -0.0968, -0.0412)])))
        xy, dep = pj.px(ala)
        nrm = np.array([0.7 * sx, -0.7, 0.0])
        f = float(pj.facing(ala[1:2], nrm[None, :])[0])
        if f > 0.35:
            for run in visible_runs(xy, pj.visible(xy, dep, 0.005), 2):
                cov, sl = Bz.stroke(run, np.array([0.4, 1.1, 1.0, 0.3]) * k, jitter=0.05)
                if cov is not None:
                    P.over(INK_SKIN, cov * face_ok[sl] * 0.55, sl)
        nos = warp_pts(np.array([(0.0054 * sx, -0.0985, -0.0400)]))
        xy, dep = pj.px(nos)
        if pj.visible(xy, dep, 0.006)[0]:
            yy, xx = np.mgrid[0:R, 0:R].astype(np.float64) + 0.5
            d = np.hypot((xx - xy[0, 0]) / 1.0, (yy - xy[0, 1]) / 0.6) / (2.2 * k)
            P.over(hexc("#4A2622"), ss(1.0, 0.4, d) * face_ok * 0.65)
    mc = var.get("mouth", 0.0)
    xs = np.linspace(-0.0205, 0.0205, 25)
    zs = warp_z(-0.0584 + 0.4 * mc + (mc * 0.6) * (xs / 0.0205) ** 2)
    M3 = surface_front(fn, np.stack([xs, zs], -1)) + np.array([0.0, 0.0008, 0.0])
    xy, dep = pj.px(M3)
    hw = np.interp(np.linspace(0, 1, len(xy)), [0, 0.15, 0.5, 0.85, 1], [0.4, 1.2, 1.9, 1.2, 0.4]) * k
    for run in visible_runs(np.column_stack([xy, hw]), pj.visible(xy, dep, 0.006)):
        cov, sl = Bz.stroke(run[:, :2], run[:, 2], jitter=0.06)
        if cov is not None:
            P.over(lip_ink, cov * face_ok[sl] * 0.85, sl)
    xs = np.linspace(-0.010, 0.010, 12)
    L3 = surface_front(fn, np.stack([xs, warp_z(np.full_like(xs, -0.0700))], -1)) + np.array([0.0, 0.0008, 0.0])
    xy, dep = pj.px(L3)
    for run in visible_runs(xy, pj.visible(xy, dep, 0.006)):
        cov, sl = Bz.stroke(run, np.array([0.3, 0.9, 0.3]) * k, jitter=0.1)
        if cov is not None:
            P.over(INK_SKIN, cov * face_ok[sl] * 0.35, sl)


def paint_collar(P, pj, var, idx, k):
    """交领：左襟压右襟。白袍 V 口的两道边各画一道领缘（外线重、里面一道细线），左襟越过中线往右下去。"""
    R = P.h
    Bz = Brush(R, R, seed=71)
    ok = np.clip(blur(((idx == INDEX["robe"]) | (idx == INDEX["skin"])).astype(np.float64), 1.2 * k) * 1.5, 0, 1)
    lift = np.array([0.0, 0.0, TORSO_LIFT])
    for pts, w0 in ((COLLAR_L, 1.9), (COLLAR_R, 1.6)):
        C = smooth_curve(np.asarray(pts) + lift, 40)
        C = snap(sd_torso, C, iters=4) + np.array([0.0, -0.002, 0.0])
        for off, wk, a_ in ((0.0, 1.0, 0.92), (0.020, 0.55, 0.6)):
            Q = C.copy()
            if off:
                # 领缘的另一道线：沿身子表面往外（离开 V 口）挪
                Q = Q + np.stack([np.sign(Q[:, 0] + 1e-6) * 0.0, np.zeros(len(Q)), -np.full(len(Q), off)], -1)
                Q = snap(sd_torso, Q, iters=4) + np.array([0.0, -0.002, 0.0])
            xy, dep = pj.px(Q, "body")
            for run in visible_runs(xy, pj.visible(xy, dep, 0.012)):
                hw = np.array([0.6, 1.0, 1.0, 0.8, 0.4]) * w0 * wk * k
                cov, sl = Bz.stroke(run, hw, jitter=0.18, dry=0.25, dry_start=0.7)
                if cov is not None:
                    P.over(INK_NONG, cov * ok[sl] * a_, sl)


def paint_hat(P, pj, var, idx, k):
    """斗笠：从帽顶放射出去的竹篾，用细笔一根根勾（背光的一侧重），帽檐几道编纹。"""
    R = P.h
    Bz = Brush(R, R, seed=81)
    ok = np.clip(blur((idx == INDEX["hat"]).astype(np.float64), 0.8 * k) * 1.6, 0, 1)
    Rh = rot("x", HAT_TILT)
    rs = np.linspace(0.012, HAT_R * 0.995, 40)

    def on_cone(r, th, up=0.0035):
        q = np.stack([r * np.cos(th), r * np.sin(th), -0.105 * (r / HAT_R) ** 0.80 + up], -1)
        return HAT_APEX + q @ Rh.T

    for i, th in enumerate(np.linspace(0, 2 * math.pi, 56, endpoint=False)):
        P3 = on_cone(rs, np.full_like(rs, th))
        xy, dep = pj.px(P3)
        for run in visible_runs(xy, pj.visible(xy, dep, 0.006)):
            cov, sl = Bz.stroke(run, np.array([0.2, 0.5, 0.7, 0.6]) * k, jitter=0.2, dry=0.3, dry_start=0.6)
            if cov is not None:
                P.over(hexc("#20150D"), cov * ok[sl] * 0.55, sl)
    for r in (0.090, 0.150, 0.205, 0.228):
        th = np.linspace(0, 2 * math.pi, 240)
        P3 = on_cone(np.full_like(th, r), th)
        xy, dep = pj.px(P3)
        for run in visible_runs(xy, pj.visible(xy, dep, 0.006)):
            cov, sl = Bz.stroke(run, 0.55 * k, jitter=0.25, dry=0.2, dry_start=0.8)
            if cov is not None:
                P.over(hexc("#20150D"), cov * ok[sl] * 0.45, sl)


def paint_locks(P, pj, var, k):
    """鬓发、额发、马尾：沿三维的管子画墨笔，几笔错开，末梢飞白散开。"""
    R = P.h
    Bz = Brush(R, R, seed=61)
    ink = hexc("#100F14")
    for i, (sp, r0, kind) in enumerate(sidelock_spines(var)):
        for j, S3 in enumerate(tube_strands(sp, r0, r0 * 0.25, 4, seed=80 + i, spread=0.6)):
            xy, dep = pj.px(S3)
            for run in visible_runs(xy, pj.visible(xy, dep, 0.008)):
                w0 = (1.6 if kind == "side" else 1.0) * k
                cov, sl = Bz.stroke(run, np.array([w0 * 0.8, w0, w0 * 0.7, 0.2 * k]), dry=0.6, dry_start=0.45,
                                    jitter=0.2)
                if cov is not None:
                    P.over(ink, cov * 0.9, sl)
    for i, (sp, r0) in enumerate(ponytail_spines(var)):
        for j, S3 in enumerate(tube_strands(sp, r0, r0 * 0.3, 3, seed=90 + i, spread=0.9)):
            xy, dep = pj.px(S3)
            for run in visible_runs(xy, pj.visible(xy, dep, 0.012)):
                cov, sl = Bz.stroke(run, np.array([2.0, 2.6, 1.8, 0.3]) * k, dry=0.7, dry_start=0.35, jitter=0.25)
                if cov is not None:
                    P.over(ink, cov * 0.85, sl)



# ====================================================================== 审图
FONT_SERIF_FULL = ART / "out" / "fonts" / "NotoSerifSC-VF.ttf"
FONT_BRUSH_FULL = ART / "out" / "fonts" / "MaShanZheng-Regular.ttf"
SKIN_DIR = ART.parent / "assets" / "atlas" / "skin"
OLD_PORTRAIT = ART / "out" / "assets@2x" / "portrait" / "portrait_hero.png"


def _font(path, size):
    from PIL import ImageFont  # noqa: PLC0415

    for p in (path, ART.parent / "assets" / "fonts" / "NotoSerifSC-subset.ttf"):
        if Path(p).exists():
            return ImageFont.truetype(str(p), int(size))
    return ImageFont.load_default()


def window_preview(img, size):
    """把胸像缩到 size，按游戏里的样子装进头像章窗口（只露直径 78/92 的圆，外面是黑漆）。"""
    from PIL import Image  # noqa: PLC0415

    im = img.convert("RGBA").resize((size, size), Image.LANCZOS)
    yy, xx = np.mgrid[0:size, 0:size].astype(np.float64) + 0.5
    r = np.hypot(xx - size / 2, yy - size / 2) / (size / 2)
    a = np.asarray(im, np.float64)[..., 3] / 255.0 * ss(WINDOW + 0.01, WINDOW - 0.01, r)
    rgb = np.asarray(im, np.float64)[..., :3]
    lac = np.array([18, 14, 12], np.float64)
    out = rgb * a[..., None] + lac * (1 - a[..., None])
    ring = np.exp(-((r - WINDOW - 0.012) / 0.012) ** 2)
    out = out * (1 - ring[..., None]) + np.array([214, 176, 98]) * ring[..., None]
    out = np.where((r > 1.0)[..., None], 0, out)
    alpha = (r <= 1.0) * 255
    return Image.fromarray(np.dstack([np.clip(out, 0, 255), alpha]).astype(np.uint8), "RGBA")


def hud_seal(portrait, level="12", ticks_on=8):
    """1080p 状态栏的头像章（逻辑像素 = 物理像素）：胸像 92、漆环 104、十二格燃灯刻度、等级印 30。"""
    from PIL import Image, ImageDraw  # noqa: PLC0415

    S_ = 104
    canvas = Image.new("RGBA", (S_ + 8, S_ + 8), (0, 0, 0, 0))
    hero = portrait.convert("RGBA").resize((92, 92), Image.LANCZOS)
    canvas.alpha_composite(hero, (6, 6))
    ring = Image.open(SKIN_DIR / "hud_portrait.png").convert("RGBA").resize((S_, S_), Image.LANCZOS)
    canvas.alpha_composite(ring, (0, 0))
    tick_off = Image.open(SKIN_DIR / "hud_ult_tick.png").convert("RGBA").resize((17, 10), Image.LANCZOS)
    tick_on = Image.open(SKIN_DIR / "hud_ult_tick_on.png").convert("RGBA").resize((17, 10), Image.LANCZOS)
    r = S_ / 2 - 5 - 3.5
    for i in range(12):
        a = i / 12 * 2 * math.pi
        tk = (tick_on if i < ticks_on else tick_off).rotate(-math.degrees(a), resample=Image.BICUBIC, expand=True)
        cx, cy = S_ / 2 + r * math.sin(a), S_ / 2 - r * math.cos(a)
        canvas.alpha_composite(tk, (int(round(cx - tk.width / 2)), int(round(cy - tk.height / 2))))
    seal = Image.open(SKIN_DIR / "hud_level_seal.png").convert("RGBA").resize((30, 30), Image.LANCZOS)
    canvas.alpha_composite(seal, (S_ - 30 + 2, S_ - 30))
    ImageDraw.Draw(canvas).text((S_ - 15 + 2, S_ - 15), level, font=_font(FONT_BRUSH_FULL, 17), fill="#F6EEDC",
                                anchor="mm")
    return canvas


def review_sheets(images: dict, out_dir=REVIEW):
    """两张审图：portrait_samples.png（三张 512² 大图 + 旧头像）、portrait_samples_hud.png（1080p 状态栏，实际大小）。"""
    from PIL import Image, ImageDraw  # noqa: PLC0415

    out_dir.mkdir(parents=True, exist_ok=True)
    old = Image.open(OLD_PORTRAIT).convert("RGBA") if OLD_PORTRAIT.exists() else Image.new("RGBA", (256, 256))
    names = [VARIANTS[v]["name"] for v in images] + ["旧头像（现在的）"]
    ims = list(images.values()) + [old.resize((SIZE, SIZE), Image.LANCZOS)]
    # ---- 大图
    pad, top = 36, 96
    W = pad + len(ims) * (SIZE + pad)
    H = top + SIZE + 40 + 260 + 60
    sheet = Image.new("RGB", (W, H), (22, 24, 34))
    dr = ImageDraw.Draw(sheet)
    dr.text((pad, 28), "主角头像样张（ui/portrait_hero）· 512² 母版，游戏里 256²、显示 92；虚线圈 = 头像章窗口（直径 78）",
            font=_font(FONT_SERIF_FULL, 26), fill="#E8DFCB")
    for i, (nm, im) in enumerate(zip(names, ims)):
        x = pad + i * (SIZE + pad)
        bg = Image.new("RGBA", (SIZE, SIZE), (34, 36, 48, 255))
        bg.alpha_composite(im.convert("RGBA").resize((SIZE, SIZE), Image.LANCZOS))
        sheet.paste(bg.convert("RGB"), (x, top))
        rr = SIZE / 2 * WINDOW
        for a0 in range(0, 360, 6):
            dr.arc((x + SIZE / 2 - rr, top + SIZE / 2 - rr, x + SIZE / 2 + rr, top + SIZE / 2 + rr), a0, a0 + 3,
                   fill=(230, 200, 120), width=2)
        dr.text((x + SIZE / 2, top + SIZE + 22), f"{chr(65 + i) if i < len(images) else ''}{'  ' if i < len(images) else ''}{nm}",
                font=_font(FONT_SERIF_FULL, 26), fill="#F2E8D2", anchor="mm")
        # 下面：窗口里的 1:1（92 / 2 倍 184）
        y2 = top + SIZE + 60
        w184 = window_preview(im, 184)
        sheet.paste(w184, (x + 40, y2), w184)
        w92 = window_preview(im, 92)
        sheet.paste(w92, (x + 260, y2 + 46), w92)
        w46 = window_preview(im, 46)
        sheet.paste(w46, (x + 390, y2 + 69), w46)
        dr.text((x + 40, y2 + 200), "窗口里 2 倍 · 1 倍（1080p）· 半尺寸", font=_font(FONT_SERIF_FULL, 18), fill="#9C968A")
    sheet.save(out_dir / "portrait_samples.png", optimize=True)
    # ---- 1080p 状态栏
    bgp = REVIEW / "night_scene.png"
    if bgp.exists():
        bg = Image.open(bgp).convert("RGB").resize((1920, 1080), Image.LANCZOS)
        a = np.asarray(bg, np.float64) / 255.0
        a = np.clip(a * np.array([1.25, 1.35, 1.6]) + np.array([0.03, 0.04, 0.07]), 0, 1) * 0.55
        B = Image.fromarray((a * 255).astype(np.uint8)).convert("RGBA")
    else:
        B = Image.new("RGBA", (1920, 1080), (24, 30, 48, 255))
    dr = ImageDraw.Draw(B)
    fs = _font(FONT_SERIF_FULL, 18)

    def bar(x, y, frac):
        hp = Image.open(SKIN_DIR / "hud_hp_track.png").convert("RGBA").resize((460, 30), Image.LANCZOS)
        B.alpha_composite(hp, (x, y))
        fill = Image.open(SKIN_DIR / "bar_fill_hp.png").convert("RGBA").resize((int(446 * frac), 16), Image.LANCZOS)
        B.alpha_composite(fill, (x + 7, y + 7))
        xp = Image.open(SKIN_DIR / "hud_xp_track.png").convert("RGBA").resize((460, 10), Image.LANCZOS)
        B.alpha_composite(xp, (x, y + 36))
        xf = Image.open(SKIN_DIR / "bar_fill_xp.png").convert("RGBA").resize((int(452 * 0.6), 6), Image.LANCZOS)
        B.alpha_composite(xf, (x + 4, y + 38))
        dr.text((x + 446, y + 15), "86 / 120", font=fs, fill="#FFF6E8", anchor="rm")

    row = list(images.items()) + [("old", old)]
    for i, (vid, im) in enumerate(row):
        x, y = 40, 24 + i * 150
        B.alpha_composite(hud_seal(im), (x - 4, y - 4))
        dr.text((x + 118, y - 2), "提灯人", font=_font(FONT_SERIF_FULL, 24), fill="#EDE4CF")
        bar(x + 118, y + 30, 0.72)
        lab = VARIANTS[vid]["name"] if vid in VARIANTS else "旧头像（现在的）"
        dr.text((x + 600, y + 52), f"{chr(65 + i) if vid in VARIANTS else ''}  {lab}", font=_font(FONT_SERIF_FULL, 26),
                fill="#F2E8D2", anchor="lm")
    # 右边：同一排四个章并排（实际大小）和 2 倍
    x0, y0 = 1000, 60
    dr.text((x0, y0 - 40), "实际大小（1080p，100% 缩放）", font=fs, fill="#BFB5A2")
    for i, (vid, im) in enumerate(row):
        B.alpha_composite(hud_seal(im), (x0 + i * 130, y0))
        dr.text((x0 + i * 130 + 56, y0 + 124), VARIANTS[vid]["name"] if vid in VARIANTS else "旧", font=fs,
                fill="#E8DFCB", anchor="mm")
    y1 = 260
    dr.text((x0, y1 - 30), "2 倍（看细节）", font=fs, fill="#BFB5A2")
    for i, (vid, im) in enumerate(row):
        s2 = hud_seal(im)
        s2 = s2.resize((s2.width * 2, s2.height * 2), Image.LANCZOS)
        B.alpha_composite(s2, (x0 + (i % 2) * 250 + (i // 2) * 0, y1 + (i // 2) * 250) if False else (x0 + i * 225, y1))
    B.convert("RGB").save(out_dir / "portrait_samples_hud.png", optimize=True)


def main_render(vid: str, draft: bool) -> dict:
    var = VARIANTS[vid]
    info = build_scene(var, draft)
    print(f"[portrait_v2] {vid}：建模 {info['build_s']}s")
    info.update(render_cache(vid, draft))
    (TMP / f"{vid}{'_' + draft if draft else ''}.json").write_text(json.dumps(info, ensure_ascii=False, indent=1))
    return info


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("ids", nargs="*", help="方向：cold gentle hat（默认三个都出）")
    ap.add_argument("--draft", action="store_true", help="低分辨率、少采样试渲")
    ap.add_argument("--dev", action="store_true", help="正式分辨率、少采样（调后期用）")
    ap.add_argument("--post", action="store_true", help="只做后期（读缓存）")
    ap.add_argument("--render-only", action="store_true")
    a = ap.parse_args(argv)
    ids = a.ids or list(ORDER)
    mode = "draft" if a.draft else ("dev" if a.dev else "")
    images = {}
    for vid in ids:
        if not a.post:
            main_render(vid, mode)
        if not a.render_only:
            im = post_variant(vid, mode)
            d = TMP / "samples"
            d.mkdir(parents=True, exist_ok=True)
            im.save(d / f"portrait_hero_{vid}{'_' + mode if mode else ''}.png", optimize=True)
            im.resize((256, 256), Image_LANCZOS()).save(d / f"portrait_hero_{vid}_256.png", optimize=True)
            images[vid] = im
    if images and not a.render_only:
        review_sheets(images, REVIEW if not mode else TMP / "review")
    return 0


def Image_LANCZOS():
    from PIL import Image  # noqa: PLC0415

    return Image.LANCZOS


if __name__ == "__main__":
    sys.exit(main())
