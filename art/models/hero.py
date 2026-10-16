"""白衣墨氅剑仙：主角模型（程序化部件 + 两段式腿 IK）。

造型（约 6.5 头身，宽肩、窄腰、长腿，挺拔）：
  - 内袍宣纸白（亮面纸色，暗面清墨/淡墨），浅墨广袖，袖口浓墨镶边，袖尾随风飘；白交领在胸前交成尖 V
  - 外披焦墨/浓墨大氅：无袖（只有短肩），前襟敞开露出白袍和双腿；腰下分成四片长摆（前左、前右、后左、后右），
    跑动时向后飘
  - 浓墨长裤、焦墨长靴；浓墨宽腰带，左前挂石绿玉佩和朱砂穗
  - 黑发高马尾（清墨银冠 + 石绿玉珠），两缕鬓发垂在脸侧；朱砂发带两条长尾
  - 背上斜背长剑：剑柄在左肩上方，S/SE 向也能露出来；藤黄剑格，朱砂剑穗
  - 右手（世界 -X）持赭石灯杖，向前外侧伸出，杖头挂灯笼。灯笼头在 models/lanterns.py（红纸灯、铜镜灯、霜瓷灯可换），
    build_hero(lamps=...) 可以同时挂几盏（同一位置、同样摆动），出图时每次只显示一盏（见 base_scope / lamp_scope）
  - 脸：肤色，连贯的鼻梁与下颌侧形，细长眼睑与剑眉；两束额发分开露出眉眼

约定：脚底在原点，面朝 -Y，右手在 -X；总高 HERO_HEIGHT_M（脚底到冠顶）。
动画（pose_hero）：
  idle：重心在右腿，左腿放松；微风吹动马尾、发带、大氅长摆、袖尾；呼吸起伏
  walk：轻功式的轻快大步（约 8° 前倾）。游戏里 118 单位/秒、stride_units=80 → 每轮前进 3.2 米，
        这已是奔跑的速度：每只脚只着地约 1.5 帧（着地时脚相对地面不滑），其余是贴地的腾空，
        摆动脚抬得很低（腾空帧最低的脚离地约 2px），像“踏雪无痕”。长摆、发带、马尾强烈后飘，袖子摆动。
  纵深朝向（S/N 正对、背对镜头，斜向减半）：步子沿镜头纵深迈，画面上两腿前后重叠、看不出交替，所以按朝向
        （_depth_k，E/W 为 0、和原来完全一样）加大抬膝、后踢、两脚左右分开，左袖横摆，长摆尾端随步子左右甩、
        后片向两侧分开（N 向露出腿）。冲刺同理：更前倾，长摆、发带向两侧拖开，两腿左右分开、抬膝。
大氅背面（N/NE/NW 大半个人都是它）：长摆和上身背面按顶点属性 fade 分层晕染（COAT_BANDS：浓墨 → 重墨 → 淡墨），
  上背中间、长摆往下摆和中缝方向渐淡，边缘仍是浓墨，读得出是布而不是一团黑。
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import bmesh
import bpy
import numpy as np
from mathutils import Matrix, Vector

ART = Path(__file__).resolve().parents[1]
if str(ART) not in sys.path:
    sys.path.insert(0, str(ART))
from style import bstyle as B  # noqa: E402
from style import style as S  # noqa: E402
import lanterns as LAN  # noqa: E402
import kit as K  # noqa: E402  （lanterns 已把 models/ 加进 sys.path）

H = S.HERO_HEIGHT_M  # 2.2

# ---------------------------------------------------------------- 尺寸（米，静止时的绝对高度）
PELVIS_Z = 1.00  # 髋关节高
HIP_X = 0.088
L_THIGH, L_SHIN = 0.50, 0.465
ANKLE_Z = 0.065
WAIST_Z = 1.27
SHOULDER_Z = 1.68
NECK_Z = 1.76
HEAD_C = Vector((0.0, -0.012, 1.985))
HEAD_R = (0.106, 0.112, 0.150)
CROWN_TOP = H
TORSO_SY = 0.66
TORSO_PROFILE = [(0.150, 1.02), (0.145, 1.13), (0.130, 1.23), (0.126, WAIST_Z), (0.152, 1.39), (0.198, 1.50),
                 (0.236, 1.60), (0.252, 1.665), (0.222, 1.705), (0.135, 1.735), (0.060, NECK_Z)]
HAND_R = Vector((-0.335, -0.305, 1.30))  # 右手握杖处
STAFF_DIR = Vector((-0.40, -0.50, 0.77)).normalized()
STAFF_LEN, STAFF_GRIP = 1.32, 0.22
STAFF_R = (0.034, 0.030)
SWORD_POMMEL = Vector((0.255, 0.205, 2.00))
SWORD_TIP = Vector((-0.33, 0.175, 0.86))
COAT_TOP = 1.235  # 长摆从腰带下沿开始
COAT_OFF = 0.024  # 大氅比内袍大一圈

# 动画
WALK_STRIDE_UNITS = 80  # style.py 约定
CYCLE_M = WALK_STRIDE_UNITS / S.WORLD_UNITS_PER_M  # 一轮前进 3.2 米
DUTY = 0.19  # 每只脚着地占一轮的比例
CONTACT_M = CYCLE_M * DUTY  # 着地期间脚相对身体后移的距离（约 0.6 米）
SWING_LIFT = 0.24  # 摆动脚最高抬起
WALK_BOB = 0.022  # 起伏约 ±1px：配准检查（FOOT_TOLERANCE_PX=1.5）量的是冠顶
WALK_LEAN_DEG = 8.0
IDLE_WIND, WALK_WIND = 0.28, 1.0
# 纵深朝向的加量（乘 _depth_k；长摆只在背对镜头时分开、甩动，正对镜头时后片在身后，分开了像两片翅膀）
DEPTH_LIFT = 0.16  # 摆动脚多抬
DEPTH_KICK = 0.16  # 摆动前段脚跟后踢（S 向这条腿显得短）
DEPTH_BACK = 0.10  # 后踢再往后一点
DEPTH_SPREAD = 0.065  # 两脚各往外分开（米）
DEPTH_COAT_SPLIT = 0.22  # 背对镜头走路：后片尾端向两侧分开，中间露出腿
DEPTH_COAT_SWAY = 0.10  # 背对镜头走路：长摆尾端随步子左右甩
# 正对镜头（S，SE/SW 约 0.6，乘 _toward_k）再加：抬膝前顶（膝盖从袍子前面顶出来）、两脚再分开、起伏加大、左袖摆幅加大
TOWARD_KNEE_UP = 0.16  # 摆动中段脚再抬高（米）
TOWARD_KNEE_FWD = 0.10  # 同时脚往前收到膝下
TOWARD_SPREAD = 0.015  # 两脚再往外分开（米）
TOWARD_BOB = 0.008  # 起伏再加（米；着地中段最低、腾空最高，冠顶配准容差 3px 以内）
DASH_LEAN_EXTRA = 12.0  # 冲刺多前倾（度）
DASH_LEAN_TOWARD = 8.0  # 正对镜头再多前倾（度）：从正面看得出扑过来，躯干缩短
DASH_COAT_SPLIT = (0.20, 0.36)  # 冲刺时长摆尾端向两侧拖开（正对、背对镜头）
DASH_COAT_FLY = 0.35  # 正对镜头冲刺：长摆少往后上方飘（身后的东西画面上本来就往上，飘高了像一对翅膀）
DASH_COAT_UPRIGHT = 0.7  # 正对镜头冲刺：长摆绕腰线往回转前倾角的这么多，垂在腿后而不是跟着上身平伸出去
DASH_RIBBON_SPREAD = 1.1  # 冲刺时发带向两侧
# 大氅分层晕染：受光面、褶面与暗内层分开，往下摆依次淡一档（都是调色板里的颜色）。
_DAN = S.shade_ramp(S.INK["dan"])  # 淡墨三档：亮、中、暗
COAT_BANDS = [(0.0, [S.INK["dan"], S.INK["zhong"], S.INK["nong"]]),
              (0.40, [S.INK["dan"], _DAN[1], S.INK["zhong"]]),
              (0.72, [S.INK["qing"], S.INK["dan"], S.INK["zhong"]])]


def walk_stride_units() -> float:
    return WALK_STRIDE_UNITS


def _facing(parts) -> float:
    """朝向镜头的程度：S 为 1，N 为 -1，E/W 为 0（斜向 ±0.71）。"""
    d = parts.get("dir")
    if d not in S.DIRS:
        return 0.0
    c = math.cos(math.radians(S.dir_rotation_deg(S.DIRS.index(d))))
    return 0.0 if abs(c) < 1e-6 else c


def _depth_k(parts) -> float:
    """朝向的纵深系数：步子沿镜头纵深迈的程度。E/W 为 0，S/N 为 1，斜向约 0.6。"""
    return abs(_facing(parts)) ** 1.5


def _away_k(parts) -> float:
    """背对镜头的程度：N 为 1，NE/NW 约 0.6，其余 0。"""
    return max(0.0, -_facing(parts)) ** 1.5


def _toward_k(parts) -> float:
    """正对镜头的程度：S 为 1，SE/SW 约 0.6，其余 0。"""
    return max(0.0, _facing(parts)) ** 1.5


# ================================================================ 材质
def _materials():
    I, A = S.INK, S.ACCENT
    T = B.toon_material
    m = {
        "white": T("RobeWhite", ramp=[S.PAPER, I["qing"], I["dan"]], seed=1.0, edge=0.45),
        "sleeve": T("SleeveCloth", ramp=[I["qing"], I["dan"], I["zhong"]], wash=0.12, edge=0.2, seed=1.0),
        "collar": T("CollarLinen", ramp=[S.PAPER, S.PAPER_SHADOW, I["qing"]], wash=0.08, edge=0.12, seed=1.0),
        "lining": T("RobeLining", ramp=[I["qing"], I["dan"], I["zhong"]], seed=1.0, edge=0.3),
        # 大氅按顶点属性 fade 分层晕染；受光面仍能辨出褶皱，外线保留焦墨。
        "coat": K.banded_toon_material("CoatInk", COAT_BANDS, noise_amt=0.16, seed=2.0, edge=0.35),
        "trousers": T("Trousers", I["nong"], seed=3.0),
        "boot": T("Boot", I["jiao"], seed=4.0),
        "belt": T("Belt", I["nong"], seed=5.0),
        "skin": T("Skin", S.SKIN, wash=0.05, edge=0.12, seed=6.0),
        "hair": T("Hair", ramp=[I["zhong"], I["nong"], I["jiao"]], wash=0.08, edge=0.18, seed=7.0),
        "silver": T("Silver", I["qing"], seed=8.0),
        "jade": T("Jade", A["shilv"], seed=9.0),
        "ribbon": T("Ribbon", A["zhusha"], edge=0.35, seed=10.0),
        "tassel": T("Tassel", A["zhusha"], seed=11.0),
        "staff": T("Staff", A["zheshi"], edge=0.15, seed=12.0),
        "gold": T("Tenghuang", A["tenghuang"], seed=13.0),
        "cap": T("Cap", I["jiao"], seed=15.0),
        "scabbard": T("Scabbard", I["nong"], seed=16.0),
        "eye": B.flat_material("EyeInk", I["jiao"]),
    }
    # banded_toon_material 不把 seed 传给底下的假卡通材质：手动把晕染噪声的种子设回 2.0，fade=0 处和原来一样
    for n in m["coat"].node_tree.nodes:
        if n.type == "TEX_NOISE" and n.noise_dimensions == "4D":
            n.inputs["W"].default_value += 2.0
    return m


# ================================================================ 几何工具
def _torso_r(z):
    return float(np.interp(z, [p[1] for p in TORSO_PROFILE], [p[0] for p in TORSO_PROFILE]))


def _torso_point(theta_deg, z, off=0.0):
    """内袍躯干表面上的点（theta 从 +X 起逆时针；-90° 是正前方，+90° 是正后方）。"""
    th = math.radians(theta_deg)
    r = _torso_r(z)
    return Vector(((r + off) * math.cos(th), (r * TORSO_SY + off) * math.sin(th), z))


def _face_xyz(x, y, z):
    """从单位头形塑出颧骨、下颌与连贯鼻梁，侧面不再是一颗光滑的椭球。"""
    jaw = 1.0 - 0.24 * max(-z, 0.0) ** 1.3
    px = x * HEAD_R[0] * jaw
    py = y * HEAD_R[1]
    front = max(-y, 0.0) ** 3
    nose = 0.030 * math.exp(-(px / 0.024) ** 2 - ((z + 0.10) / 0.45) ** 2)
    brow = 0.006 * math.exp(-((z - 0.17) / 0.16) ** 2)
    chin = 0.008 * math.exp(-((z + 0.73) / 0.20) ** 2)
    py -= front * (nose + brow + chin)
    return Vector((px, py, z * HEAD_R[2]))


def face_surface(x, z):
    """头心坐标中的脸面点；五官贴在同一表面上，近景取点也可复用。"""
    zn = z / HEAD_R[2]
    xn = x / (HEAD_R[0] * (1.0 - 0.24 * max(-zn, 0.0) ** 1.3))
    yn = -math.sqrt(max(0.0, 1.0 - xn * xn - zn * zn))
    return _face_xyz(xn, yn, zn)


def _strip_build(pts, width, thick, twist=0.0, taper=(1.0, 0.6), side_hint=Vector((1, 0, 0))):
    """扁带（发带、马尾、鬓发、符纸）：沿点列扫一个扁矩形，宽度方向大致沿 side_hint，可沿长度扭转。"""
    pts = [Vector(p) for p in pts]
    n = len(pts)
    ups = []
    for i in range(n):
        tan = (pts[min(i + 1, n - 1)] - pts[max(i - 1, 0)]).normalized()
        side = side_hint - tan * side_hint.dot(tan)
        if side.length < 1e-4:
            side = Vector((0, 1, 0))
        side.normalize()
        side = (Matrix.Rotation(twist * i / max(n - 1, 1), 3, tan) @ side).normalized()
        ups.append(tan.cross(side))
    return B.sweep(pts, width, thick, ups=ups, width_fn=lambda t: taper[0] + (taper[1] - taper[0]) * t)


def _replace_mesh(ob, build):
    """换掉物体的网格（每帧重建飘动部件用），保留材质。"""
    old = ob.data
    me = bpy.data.meshes.new(old.name)
    bm = bmesh.new()
    build(bm)
    bm.to_mesh(me)
    bm.free()
    me.shade_smooth()
    for m in old.materials:
        me.materials.append(m)
    ob.data = me
    if old.users == 0:
        bpy.data.meshes.remove(old)


def _grid_build(rows, cap=False):
    """由点阵 rows[v][u] 建一张单层曲面（布片），法线统一朝外（远离身体中轴）。"""
    def build(bm):
        vs = [[bm.verts.new(p) for p in row] for row in rows]
        for j in range(len(vs) - 1):
            for i in range(len(vs[0]) - 1):
                f = bm.faces.new((vs[j][i], vs[j][i + 1], vs[j + 1][i + 1], vs[j + 1][i]))
        for f in bm.faces:
            c = f.calc_center_median()
            if f.normal.dot(Vector((c.x, c.y, 0))) < 0:
                f.normal_flip()
    return build


# ---------------------------------------------------------------- 大氅
UPPER_WASH = 0.88  # 上背中间晕开的最大 fade


def _upper_fade(theta_deg, z):
    """大氅上身的晕染：背中间（θ=90°）、腰上到肩胛之间最淡，往两侧、往肩线回到浓墨。"""
    back = max(0.0, math.sin(math.radians(theta_deg))) ** 2
    hump = float(np.interp(z, [COAT_TOP, 1.40, 1.55, 1.665, 1.70], [0.35, 1.0, 0.85, 0.2, 0.0]))
    return UPPER_WASH * back * hump


def _coat_upper_build(segs=36, fades=None):
    """大氅上身：比内袍大一圈的壳，前襟敞开（开口自领口向下张开成 V），肩部只有短肩（无袖）。
    fades 给一个列表时按顶点顺序填晕染属性（_upper_fade）。"""
    zs = [COAT_TOP, 1.30, 1.39, 1.50, 1.60, 1.665, 1.705, 1.735, NECK_Z + 0.02]

    def opening(z):  # 前襟开口半角（度），领口窄、腰间宽
        return float(np.interp(z, [COAT_TOP, 1.40, 1.62, NECK_Z + 0.02], [44, 36, 18, 30]))

    if fades is not None:
        fades.extend(_upper_fade(-90 + opening(z) + (360 - 2 * opening(z)) * i / segs, z)
                     for z in zs for i in range(segs + 1))

    def build(bm):
        rings = []
        for z in zs:
            r = _torso_r(min(z, NECK_Z)) + COAT_OFF + (0.012 if z > 1.70 else 0.0)
            if 1.58 < z < 1.70:
                # 布顺着肩斜落下，去掉原来突出的硬壳肩垫，躯干比例与肩枢轴不变。
                r += 0.012 * math.sin(math.pi * (z - 1.58) / 0.12)
            if z > NECK_Z:
                r = 0.085  # 立领
            ring = []
            for i in range(segs + 1):  # 开口两侧各留一列顶点（开放的边 → 描边）
                a0 = -90 + opening(z)
                th = math.radians(a0 + (360 - 2 * opening(z)) * i / segs)
                sy = TORSO_SY if z <= NECK_Z else 0.9
                ring.append(bm.verts.new(((r) * math.cos(th), (r * sy + 0.01) * math.sin(th) + 0.008, z)))
            rings.append(ring)
        for a, b in zip(rings, rings[1:]):
            for i in range(segs):
                bm.faces.new((a[i], a[i + 1], b[i + 1], b[i]))
        for f in bm.faces:
            c = f.calc_center_median()
            if f.normal.dot(Vector((c.x, c.y, 0))) < 0:
                f.normal_flip()

    return build


COAT_PANELS = {  # 名字: (θ0, θ1, 长度, 是否前片)
    "CoatBackL": (16, 87, 1.08, False),
    "CoatBackR": (93, 164, 1.08, False),
    "CoatFrontL": (-72, -14, 0.94, True),
    "CoatFrontR": (-166, -108, 0.94, True),
}


def _panel_fade(th_deg, t, front):
    """长摆的晕染：往下摆渐淡（墨色由浓到淡）；后片靠中缝更淡、靠两侧浓，前片只在下摆淡一点。"""
    if front:
        return 0.45 * t * t
    seam = math.sin(math.radians(th_deg)) ** 2
    return (0.20 + 0.75 * t ** 1.1) * (0.6 + 0.4 * seam)


def _coat_panel_rows(th0, th1, length, front, phase, wind, nu=12, nv=12, split=0.0, sway=0.0, fly=1.0, pitch=0.0,
                     fades=None):
    """一片长摆的点阵：从腰带下沿垂下、略外张、尾端收窄成燕尾；随风（wind）向后上方飘，并有行进的波。
    split：尾端向身体两侧分开（米，左片往 +X、右片往 -X）；sway：尾端整体横摆（米，+X 为正）；
    都按 t^1.4 从腰往下渐增，0 时与原来完全相同；fly：随风往后上方飘的倍数；pitch：垂下的部分先绕腰线往前转（弧度，
    抵消上身前倾，让长摆往下垂）。fades 给列表时按顶点顺序填晕染属性。"""
    cp, sp = math.cos(pitch), math.sin(pitch)
    yc = (_torso_r(COAT_TOP) * TORSO_SY + COAT_OFF + 0.01) * math.sin(math.radians((th0 + th1) / 2))
    rows = []
    thc, tw = (th0 + th1) / 2, (th1 - th0)
    rx, ry = _torso_r(COAT_TOP) + COAT_OFF, _torso_r(COAT_TOP) * TORSO_SY + COAT_OFF + 0.01
    side = 1.0 if math.cos(math.radians(thc)) >= 0 else -1.0
    for j in range(nv + 1):
        t = j / nv
        row = []
        for i in range(nu + 1):
            u = i / nu
            if fades is not None:
                fades.append(_panel_fade(thc + (u - 0.5) * tw * (1 - 0.28 * t), t, front))
            th = math.radians(thc + (u - 0.5) * tw * (1 - 0.28 * t))
            out = Vector((math.cos(th), math.sin(th) * 0.85, 0)).normalized()
            L = length * (1 - 0.10 * abs(u - 0.5) * 2 * t)  # 尾端中间长、两边短
            p = Vector((rx * math.cos(th), ry * math.sin(th), COAT_TOP)) + out * (0.17 * t ** 1.2) + Vector((0, 0, -L * t))
            # 腰线固定，宽褶向下展开；褶峰随布片走，不用逐帧随机噪声制造碎皱。
            pleat = math.sin(math.pi * u) ** 0.7 * (1.0 - math.exp(-5.0 * t))
            p += out * (0.024 * pleat * math.sin(math.tau * (1.6 * u - 0.12 * t) + (0.3 if front else 1.0)))
            if pitch:  # 绕这片顶边的腰线（y = yc，z = COAT_TOP）往前转：+Y 往 -Y
                dy_, dz_ = p.y - yc, p.z - COAT_TOP
                p = Vector((p.x, yc + dy_ * cp + dz_ * sp, COAT_TOP - dy_ * sp + dz_ * cp))
            s = wind * (0.65 + 0.35 * min(wind, 1.0)) * (t ** 1.35) * L
            p += Vector((0, 0.85 * s * fly, 0.36 * s * t * fly))  # 向后上方飘
            if front:
                p += out * (0.10 * s) + Vector((0, 0.15 * s, 0))  # 前片从腿两侧往后飘（不往外张成裙子）
            amp = (0.010 + 0.05 * wind) * t
            w = math.sin(2 * math.pi * 1.1 * t - phase + u * 1.2 + (0.0 if front else 1.3))
            p += out * (amp * w) + Vector((0, amp * 0.6 * math.cos(2 * math.pi * t - phase + u), 0))
            if split or sway:
                p += Vector(((side * split + sway) * t ** 1.4, 0, 0))
            row.append(p)
        rows.append(row)
    return rows


# ---------------------------------------------------------------- 广袖
def _sleeve_build(A, Bp, radii, droop, phase=0.0, wind=0.0, segs=28, border=0.12, swing_back=0.0):
    """广袖：从肩 A 到袖口 B 的喇叭管，下侧随长度下垂成袖兜；袖兜尾端随相位飘动并被风往后带。
    最后一段是浓墨镶边（材质 1），袖口封一个凹进去的暗内衬（材质 2）。顶点相对 A。"""
    A, Bp = Vector(A), Vector(Bp)
    d = (Bp - A).normalized()
    down = Vector((0, 0, -1))
    u = down - d * down.dot(d)
    if u.length < 1e-3:
        u = Vector((0, 1, 0))
    u.normalize()
    v = d.cross(u).normalized()
    ts = [0.0, 0.12, 0.25, 0.4, 0.55, 0.7, 0.86, 1.0 - border * 0.5, 1.0]
    flutter = 1 + (0.06 + 0.12 * wind) * math.sin(phase)

    def build(bm):
        rings = []
        for t in ts:
            r = float(np.interp(t, [p[0] for p in radii], [p[1] for p in radii]))
            c = A.lerp(Bp, t) - A
            ring = []
            for i in range(segs):
                th = 2 * math.pi * i / segs
                dirv = u * math.cos(th) + v * math.sin(th)
                bag = max(0.0, math.cos(th)) ** 1.3
                sag = droop * flutter * (t ** 1.6) * bag
                back = (swing_back + 0.10 * wind * math.sin(phase - 1.0 + t)) * (t ** 2) * bag
                # 肩与袖口两端收束，中段由肘腕牵出三道宽褶；下侧袖兜仍由原动画控制。
                tension = math.sin(math.pi * t) ** 0.7
                fold = 0.030 * tension * (0.72 * math.sin(3.0 * th + 0.9 * t)
                                          + 0.28 * math.sin(5.0 * th - 0.6 * t))
                ring.append(bm.verts.new(c + dirv * (r + fold) + u * sag + Vector((0, back, 0))))
            rings.append(ring)
        for j in range(len(rings) - 1):
            a, b = rings[j], rings[j + 1]
            for i in range(segs):
                f = bm.faces.new((a[i], a[(i + 1) % segs], b[(i + 1) % segs], b[i]))
                if ts[j] >= 0.86 - 1e-6:
                    f.material_index = 1
        bm.faces.new(list(reversed(rings[0])))
        cen = sum((p.co for p in rings[-1]), Vector()) / segs - d * 0.05
        cv = bm.verts.new(cen)
        for i in range(segs):
            f = bm.faces.new((rings[-1][i], rings[-1][(i + 1) % segs], cv))
            f.material_index = 2
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)

    return build


SH_L = Vector((0.225, 0.008, 1.655))
SH_R = Vector((-0.225, 0.008, 1.655))
CUFF_L = Vector((0.325, 0.03, 1.16))
CUFF_R = HAND_R + Vector((0.035, 0.055, 0.03))
SLEEVE_RADII = [(0.0, 0.055), (0.35, 0.074), (0.75, 0.112), (1.0, 0.132)]
SLEEVE_DROOP = (0.18, 0.22)  # 肩臂收紧，余量垂在袖口；不改变握杖手与袖枢轴


# ---------------------------------------------------------------- 头发与发带
def _ponytail_points(phase, wind, n=12):
    """高马尾（相对冠后的根点）：先向后上翘，再垂落；有风时向后飘。"""
    pts = []
    for i in range(n):
        t = i / (n - 1)
        s = 0.88 * t
        y = 0.10 * math.sin(min(t * 3.0, 1.0) * 1.4) + 0.22 * t * (0.4 + 0.6 * wind) + 0.08 * wind * t
        z = 0.05 * math.sin(min(t * 4.0, 1.0) * 1.6) - s * (0.95 - 0.40 * wind)
        z += 0.06 * wind * t * t
        x = 0.035 * t * math.sin(2 * math.pi * 0.9 * t - phase) * (0.6 + wind)
        y += 0.03 * t * math.cos(2 * math.pi * 1.1 * t - phase) * (0.5 + wind)
        pts.append(Vector((x, y, z)))
    return pts


def _ponytail_build(phase, wind):
    return K.tube_build(_ponytail_points(phase, wind),
                        lambda t: 0.044 * (1.0 - t) ** 0.7, segs=12, flat=0.65)


def _ribbon_points(length, phase, wind, side, n=16, spread=0.0):
    """发带（相对冠后的根点）：从冠后出发，向后、略偏一侧，重力下垂 + 行进的 S 形波。
    spread：再往 side 那一侧拉开（冲刺的纵深朝向用，0 时和原来一样）。"""
    d_idle = Vector((0.55 * side, 0.55, -1.0)).normalized()
    d_walk = Vector((0.30 * side, 0.80, -0.62)).normalized()
    dirv = d_idle.lerp(d_walk, wind).normalized()
    if spread:
        dirv = (dirv + Vector((math.copysign(spread, side), 0, 0))).normalized()
    sdv = Vector((0, 0, 1)).cross(dirv).normalized()
    up = dirv.cross(sdv).normalized()
    k = 2 * math.pi * 1.4 / length
    amp = 0.03 + 0.05 * wind
    pts = []
    for i in range(n):
        s = length * i / (n - 1)
        w = s / length
        p = dirv * s + sdv * (math.sin(k * s - phase) * amp * w) + up * (math.cos(0.8 * k * s - phase + 0.7) * amp * 0.7 * w)
        p.z -= (0.10 + 0.22 * wind) * s * s
        pts.append(p)
    return pts


def _sidelock_points(sx, phase, wind):
    """鬓发：从太阳穴垂到下颌下，略向外弯（相对头枢轴）。"""
    top = Vector((0.099 * sx, -0.043, 0.050))
    pts = []
    for i in range(7):
        t = i / 6
        pts.append(top + Vector((0.012 * sx * math.sin(t * 2.2) + 0.006 * sx * math.sin(phase + t * 3) * (0.5 + wind),
                                  0.012 * t + 0.03 * wind * t * t, -0.20 * t)))
    return pts


# ================================================================ 组装
def build_hero(lamps=("red",)):
    """返回 (root, parts, sockets)。sockets: lantern（灯芯中心）、feet（原点）。
    lamps：挂哪几盏灯（lanterns.LAMP_IDS 里的 id）。第一盏在原来的位置建（物体顺序与只挂红纸灯时相同），
    lantern 挂点挂在它的枢轴下；其余几盏最后建，枢轴每帧跟着第一盏走。parts["lamps"] = {id: lanterns.Head}。"""
    lamps = tuple(lamps or ("red",))
    M = _materials()
    obj = B.mesh_object
    root = B.empty("HeroRoot")
    parts: dict = {"root": root, "mats": M}

    # ---- 骨盆与腿（两段式，IK 在 pose_hero 里解）
    pelvis = B.empty("Pelvis", root, loc=(0, 0, PELVIS_Z))
    parts["pelvis"] = pelvis
    for side, sx in (("L", 1), ("R", -1)):
        hip = B.empty(f"Hip{side}", pelvis, loc=(HIP_X * sx, 0, 0))
        obj(f"Thigh{side}", B.lathe([(0.0, -L_THIGH - 0.02), (0.062, -L_THIGH), (0.068, -0.30), (0.080, -0.08),
                                     (0.085, 0.02), (0.0, 0.05)], 14, scale_y=0.95),
            M["trousers"], "outer", hip, sharp_deg=0)
        knee = B.empty(f"Knee{side}", hip, loc=(0, 0, -L_THIGH))
        obj(f"Shin{side}", B.lathe([(0.0, -L_SHIN), (0.050, -L_SHIN + 0.01), (0.054, -0.30), (0.062, -0.08),
                                    (0.068, -0.02), (0.0, 0.03)], 14, scale_y=1.05),
            M["boot"], "outer", knee, sharp_deg=0)
        ankle = B.empty(f"Ankle{side}", knee, loc=(0, 0, -L_SHIN))
        obj(f"Foot{side}", B.uv_sphere(1.0, 14, 8, scale=(0.050, 0.115, 0.050)), M["boot"], "outer", ankle,
            loc=(0, -0.05, -0.020))
        parts[f"hip_{side}"], parts[f"knee_{side}"], parts[f"ankle_{side}"] = hip, knee, ankle

    # ---- 上身枢轴（前倾、呼吸都转这里）
    chest = B.empty("Chest", pelvis)
    parts["chest"] = chest

    def rel(v):  # 绝对高度 → 相对骨盆
        return Vector(v) - Vector((0, 0, PELVIS_Z))

    # 内袍：躯干 + 前后两片白下摆（到大腿中部）
    obj("Torso", B.lathe(TORSO_PROFILE, 32, scale_y=TORSO_SY), M["white"], "outer", chest, loc=rel((0, 0, 0)),
        sharp_deg=0)
    flaps = []
    for nm, thc, w in (("TunicFront", -90, 64), ("TunicBack", 90, 70)):
        ob = obj(nm, _grid_build(_tunic_rows(thc, w, 0.0, 0.0)), M["white"], "outer", chest, loc=rel((0, 0, 0)),
                 sharp_deg=0)
        flaps.append((ob, thc, w))
    parts["tunic"] = flaps
    obj("Neck", B.cylinder(0.042, 0.047, 0.13, 12), M["skin"], "inner", chest, loc=rel((0, 0.004, 1.80)))

    # 交领：白领在胸前交成尖 V（左襟压右襟），领线描内线
    long_path = [(95, 1.77, 0.010), (40, 1.765, 0.012), (-30, 1.745, 0.010), (-62, 1.69, 0.006),
                 (-90, 1.58, 0.006), (-118, 1.49, 0.006), (-142, 1.43, 0.006)]
    short_path = [(150, 1.77, 0.010), (215, 1.745, 0.008), (243, 1.68, 0.004), (262, 1.62, 0.003)]
    obj("CollarL", B.sweep([rel(_torso_point(t, z, o)) for t, z, o in long_path], 0.062, 0.006), M["collar"],
        "inner", chest)
    obj("CollarR", B.sweep([rel(_torso_point(t, z, o)) for t, z, o in short_path], 0.048, 0.005), M["collar"],
        "inner", chest)

    # 大氅：上身壳 + 四片长摆
    fades: list = []
    up = obj("CoatUpper", _coat_upper_build(fades=fades), M["coat"], "outer", chest, loc=rel((0, 0, 0)), sharp_deg=0)
    B.set_point_attr(up, "fade", fades)
    panels = []
    for nm, (a0, a1, ln, front) in COAT_PANELS.items():
        fades = []
        ob = obj(nm, _grid_build(_coat_panel_rows(a0, a1, ln, front, 0.0, 0.0, fades=fades)), M["coat"], "outer",
                 chest, loc=rel((0, 0, 0)), sharp_deg=0)
        B.set_point_attr(ob, "fade", fades)
        panels.append((ob, a0, a1, ln, front))
    parts["coat_panels"] = panels

    # 腰带、玉佩、穗
    obj("Belt", B.lathe([(0.140, 1.22), (0.146, 1.27), (0.150, 1.32)], 32, scale_y=TORSO_SY + 0.06), M["belt"],
        "inner", chest, loc=rel((0, 0, 0)), sharp_deg=0)
    pend = B.empty("PendantPivot", chest, loc=rel((0.075, -0.098, 1.23)))
    obj("PendantCord", B.cylinder(0.004, 0.004, 0.08, 6), M["belt"], "none", pend, loc=(0, 0, -0.04))
    obj("Jade", B.cylinder(0.034, 0.034, 0.013, 16), M["jade"], "inner", pend, loc=(0, -0.004, -0.105),
        rot=(math.radians(90), 0, 0))
    obj("PendantTassel", B.cylinder(0.007, 0.024, 0.10, 8), M["tassel"], "none", pend, loc=(0, -0.004, -0.19))
    parts["pendant"] = pend

    # 广袖
    sleeve_mats = [M["sleeve"], M["belt"], M["lining"]]
    sL = B.empty("SleevePivotL", chest, loc=rel(SH_L))
    slv_l = obj("SleeveL", _sleeve_build(SH_L, CUFF_L, SLEEVE_RADII, SLEEVE_DROOP[0]), sleeve_mats, "outer", sL,
                sharp_deg=0)
    obj("HandL", B.uv_sphere(1.0, 12, 8, scale=(0.032, 0.036, 0.046)), M["skin"], "inner", sL,
        loc=CUFF_L - SH_L + Vector((0.0, -0.01, -0.05)))
    armR = B.empty("ArmR", chest, loc=rel(SH_R))
    sR = B.empty("SleevePivotR", armR)
    slv_r = obj("SleeveR", _sleeve_build(SH_R, CUFF_R, SLEEVE_RADII, SLEEVE_DROOP[1]), sleeve_mats, "outer", sR,
                sharp_deg=0)
    obj("HandR", B.uv_sphere(1.0, 12, 8, scale=(0.036, 0.036, 0.040)), M["skin"], "inner", armR, loc=HAND_R - SH_R)
    parts.update(sleeve_L=sL, sleeve_R=sR, arm_R=armR, sleeve_mesh=(slv_l, slv_r))

    # 灯杖与灯笼
    a = HAND_R - STAFF_DIR * STAFF_GRIP
    tip = HAND_R + STAFF_DIR * (STAFF_LEN - STAFF_GRIP)
    staff = obj("Staff", B.cylinder(STAFF_R[0], STAFF_R[1], STAFF_LEN, 10), M["staff"], "thin", armR)
    B.aim(staff, a - SH_R, tip - SH_R)
    obj("StaffKnob", B.uv_sphere(0.040, 10, 6), M["gold"], "thin", armR, loc=tip - SH_R)
    heads = {lamps[0]: LAN.build_head(lamps[0], armR, tip - SH_R, M, pivot_name="LanternPivot")}
    lp = heads[lamps[0]].pivot
    parts["lantern"] = lp
    sock_lantern = B.empty("SocketLantern", lp, loc=(0, 0, LAN.C_Z))
    parts["lantern_loc0"] = lp.location.copy()
    parts["lantern_cz"] = LAN.C_Z

    # ---- 头：脸（下巴收尖）、发、冠、马尾、鬓发、发带
    head = B.empty("HeadPivot", chest, loc=rel((0, 0, 1.84)))
    parts["head"] = head
    hc = HEAD_C - Vector((0, 0, 1.84))

    def face_build(bm):
        bmesh.ops.create_uvsphere(bm, u_segments=40, v_segments=28, radius=1.0)
        for v in bm.verts:
            v.co = _face_xyz(*v.co)

    obj("Head", face_build, M["skin"], "outer", head, loc=hc)

    def hair_cap(bm):
        bmesh.ops.create_uvsphere(bm, u_segments=40, v_segments=28, radius=1.0)
        kill = []
        for f in bm.faces:
            c = f.calc_center_median()
            front = c.y < -0.12
            if front and c.z < 0.58 - 0.38 * abs(c.x) and not (abs(c.x) > 0.88 and c.z > -0.08):
                kill.append(f)
            elif c.z < -0.28 and c.y < 0.45:
                kill.append(f)
        bmesh.ops.delete(bm, geom=kill, context="FACES")
        bmesh.ops.scale(bm, vec=(HEAD_R[0] * 1.08, HEAD_R[1] * 1.07, HEAD_R[2] * 1.05), verts=bm.verts)

    obj("HairCap", hair_cap, M["hair"], "outer", head, loc=hc + Vector((0, 0.006, 0.008)))
    # 两束大形沿额头分开，露出眉眼；不用逐根发丝把游戏尺寸变成碎线。
    for sx, width in ((-1, 0.038), (1, 0.028)):
        points = []
        for i in range(9):
            t = i / 8
            x = sx * (0.012 + 0.090 * math.sin(t * math.pi / 2))
            z = 0.130 - (0.115 if sx < 0 else 0.095) * t
            points.append(face_surface(x, z) + Vector((0, -0.008, 0.004)))
        obj(f"Forelock{sx:+d}", _strip_build(points, width, 0.012, taper=(0.8, 0.08),
                                             side_hint=Vector((0.8, 0, 0.5))),
            M["hair"], "none", head, loc=hc)
    crown_z = CROWN_TOP - 0.075 - 1.84
    obj("TopKnot", B.uv_sphere(1.0, 14, 8, scale=(0.040, 0.046, 0.040)), M["hair"], "outer", head,
        loc=(0, 0.035, crown_z + 0.025))
    obj("Crown", B.lathe([(0.0, 0.0), (0.040, 0.0), (0.046, 0.032), (0.050, 0.055), (0.030, 0.068), (0.0, 0.075)], 14),
        M["silver"], "inner", head, loc=(0, 0.03, crown_z), sharp_deg=50)
    obj("CrownJade", B.uv_sphere(0.017, 10, 6), M["jade"], "none", head, loc=(0, -0.012, crown_z + 0.04))
    pin = obj("Hairpin", B.cylinder(0.006, 0.006, 0.17, 6), M["silver"], "inner", head)
    B.aim(pin, Vector((-0.085, 0.035, crown_z + 0.045)), Vector((0.085, 0.028, crown_z + 0.045)))
    # 眼与眉贴着新的颧骨表面，眼用细长的上睑形，不再是凸起的黑色球珠。
    for sx in (-1, 1):
        x = 0.042 * sx
        eye_at = hc + face_surface(x, -0.004) + Vector((0, -0.002, 0))
        obj(f"Eye{sx:+d}", B.uv_sphere(1.0, 12, 6, scale=(0.017, 0.003, 0.0045)), M["eye"], "none", head,
            loc=eye_at, rot=(0, math.radians(-8 * sx), 0))
        brow = obj(f"Brow{sx:+d}", B.cylinder(0.0035, 0.0015, 0.045, 8), M["eye"], "none", head)
        B.aim(brow, hc + face_surface(x - 0.020 * sx, 0.025) + Vector((0, -0.002, 0)),
              hc + face_surface(x + 0.020 * sx, 0.031) + Vector((0, -0.002, 0)))
    locks = [obj(f"SideLock{sx:+d}", _strip_build(_sidelock_points(sx, 0, 0), 0.020, 0.009, taper=(1.0, 0.1)),
                 M["hair"], "none", head, loc=hc) for sx in (-1, 1)]
    parts["sidelocks"] = locks
    root_tail = Vector((0, 0.07, crown_z + 0.02))
    tail = obj("Ponytail", _ponytail_build(0, 0),
               M["hair"], "inner", head, loc=root_tail)
    rib_root = Vector((0, 0.05, crown_z + 0.035))
    rib_a = obj("RibbonA", _strip_build(_ribbon_points(0.95, 0, 0, 1.0), 0.066, 0.008, twist=2.4, taper=(0.8, 1.0)),
                M["ribbon"], "inner", head, loc=rib_root)
    rib_b = obj("RibbonB", _strip_build(_ribbon_points(0.80, 1.3, 0, -0.6), 0.060, 0.008, twist=-2.0, taper=(0.8, 1.0)),
                M["ribbon"], "inner", head, loc=rib_root)
    parts.update(ponytail=tail, ribbon=(rib_a, rib_b))

    # ---- 背剑：剑柄在左肩上方
    sw = B.empty("Sword", chest, loc=rel((0, 0, 0)))
    d = (SWORD_TIP - SWORD_POMMEL).normalized()
    P = SWORD_POMMEL
    Ls = (SWORD_TIP - P).length

    def seg(name, t0, t1, r0, r1, mat, line="inner", segs=10):
        o = obj(name, B.cylinder(r0, r1, (t1 - t0), segs), mat, line, sw)
        B.aim(o, P + d * t0, P + d * t1)
        return o

    obj("Pommel", B.uv_sphere(0.026, 10, 6), M["gold"], "inner", sw, loc=P)
    seg("Grip", 0.015, 0.215, 0.017, 0.017, M["cap"])
    guard = obj("Guard", B.uv_sphere(1.0, 12, 6, scale=(0.080, 0.026, 0.018)), M["gold"], "inner", sw)
    guard.location = P + d * 0.225
    guard.rotation_mode = "QUATERNION"
    guard.rotation_quaternion = Vector((0, 0, 1)).rotation_difference(d)
    seg("Scabbard", 0.24, Ls, 0.030, 0.024, M["scabbard"], "outer", 12)
    seg("Throat", 0.24, 0.29, 0.034, 0.034, M["gold"])
    seg("Chape", Ls - 0.06, Ls + 0.012, 0.028, 0.012, M["gold"])
    st = B.empty("SwordTasselPivot", sw, loc=P)
    obj("SwordTasselCord", B.cylinder(0.004, 0.004, 0.07, 6), M["tassel"], "none", st, loc=(0, 0, -0.035))
    obj("SwordTassel", B.cylinder(0.008, 0.026, 0.10, 8), M["tassel"], "none", st, loc=(0, 0, -0.12))
    parts["sword_tassel"] = st

    for lid in lamps[1:]:  # 其余几盏灯：最后建，前面所有物体的顺序与只挂一盏时相同
        heads[lid] = LAN.build_head(lid, armR, tip - SH_R, M)
    parts["lamps"] = heads
    sockets = {"lantern": sock_lantern, "feet": B.empty("SocketFeet", root)}
    parts["sockets"] = sockets
    bpy.context.view_layer.update()
    pose_hero(parts, "idle", 0, 6)
    return root, parts, sockets


def _tunic_rows(thc, width_deg, phase, wind, nu=12, nv=10, length=0.58):
    """内袍下摆的一片（前或后），从腰下垂到大腿中部，随风略飘。"""
    rows = []
    z0 = 1.22
    for j in range(nv + 1):
        t = j / nv
        row = []
        for i in range(nu + 1):
            u = i / nu
            th = math.radians(thc + (u - 0.5) * width_deg * (1 - 0.15 * t))
            r = _torso_r(z0 - 0.0) + 0.012 + 0.05 * t
            r += 0.018 * t * math.sin(math.pi * u) ** 0.7 * math.sin(math.tau * (1.5 * u + 0.1 * t))
            p = Vector((r * math.cos(th), (r * TORSO_SY + 0.012 + 0.03 * t) * math.sin(th), z0 - length * t))
            s = wind * t * t * length
            p += Vector((0, 0.35 * s, 0.10 * s)) + Vector((0, 0.01 * math.sin(phase + u * 2) * t * (0.5 + wind), 0))
            row.append(p)
        rows.append(row)
    return rows


# ================================================================ 姿态
def _leg_ik(parts, side, target_root: Vector, toe_tilt=0.0, dx=0.0):
    """两段式腿 IK（在矢状面 y-z 里解，膝盖朝前）。target_root：踝关节在 root 坐标里的位置（x 不用）。
    dx：踝关节相对髋关节往外/往内挪的距离（米，root 的 +X 为正）：整条腿绕前后轴外展，脚掌放平。
    dx=0 时和原来完全一样。"""
    hip = parts[f"hip_{side}"]
    pel = parts["pelvis"]
    hip_root = pel.location + Vector((hip.location.x, 0, 0))
    d = target_root - hip_root
    dy, dz = d.y, d.z
    abd = 0.0
    if dx:  # 外展：先在“髋到踝”那个斜面里解，再整体绕 Y 转过去
        r = math.hypot(dx, dz)
        abd = math.atan2(-dx, -dz)
        dz = -r
    D = min(max(math.hypot(dy, dz), 0.25), L_THIGH + L_SHIN - 1e-4)
    phi = math.atan2(dy, -dz)  # 从“正下”转向 +Y（向后）的角度
    cos_a = (L_THIGH ** 2 + D ** 2 - L_SHIN ** 2) / (2 * L_THIGH * D)
    alpha = math.acos(max(-1.0, min(1.0, cos_a)))
    cos_k = (L_THIGH ** 2 + L_SHIN ** 2 - D ** 2) / (2 * L_THIGH * L_SHIN)
    bend = math.pi - math.acos(max(-1.0, min(1.0, cos_k)))
    a1 = phi - alpha  # 大腿向前（膝盖在前）
    parts[f"knee_{side}"].rotation_euler = (bend, 0, 0)
    if not dx:
        hip.rotation_euler = (a1, 0, 0)
        parts[f"ankle_{side}"].rotation_euler = (-(a1 + bend) + toe_tilt, 0, 0)
        return
    hip.rotation_euler = (a1, abd, 0)  # XYZ 欧拉：先绕 X（前后），再绕 Y（外展）
    # 脚掌：整条链是 Ry(abd)·Rx(a1+bend)·R踝，要让脚只剩脚尖角 Rx(toe_tilt)，不跟着外展侧翻
    ank = (Matrix.Rotation(-(a1 + bend), 3, "X") @ Matrix.Rotation(-abd, 3, "Y")
           @ Matrix.Rotation(toe_tilt, 3, "X"))
    parts[f"ankle_{side}"].rotation_euler = ank.to_euler("XYZ")


def _foot_walk(p, kd=0.0, fk=0.0):
    """一只脚在一轮里的位置（相对骨盆正下方；y 向前为负）、抬高、脚尖角。p∈[0,1)，p=0 刚着地。
    kd：纵深系数（_depth_k）。加大抬脚、摆动前段的脚跟后踢；fk：正对镜头系数（_toward_k），摆动中段再抬脚、
    脚收到膝下（大腿抬平，膝盖往镜头顶）。都为 0 时与原来完全相同。"""
    if p < DUTY:  # 着地：相对身体匀速后移（与地面不打滑）
        q = p / DUTY
        return -CONTACT_M / 2 + CONTACT_M * q, 0.0, 0.0
    q = (p - DUTY) / (1 - DUTY)  # 摆动：先后踢再向前，抬膝
    s = q * q * (3 - 2 * q)
    y = CONTACT_M / 2 - CONTACT_M * s + (0.22 + DEPTH_BACK * kd) * math.sin(math.pi * q) * (1 - q) ** 1.5
    z = (SWING_LIFT + DEPTH_LIFT * kd) * math.sin(math.pi * q) ** 2.5
    if kd:  # 脚跟后踢：摆动前段小腿折上去（正面看这条腿短一截）
        z += DEPTH_KICK * kd * math.sin(math.pi * min(q / 0.6, 1.0)) ** 2 * (1 - q)
    if fk:  # 抬膝前顶：q 0.2–0.75 之间鼓起，约 0.47 最高；q≈0.7 那帧已回到原来的轨迹往下落（那帧两脚都离地，
        # S 向画面上后脚本来就高，前脚再抬着最低点就离地 12px，算“没着地”），着地不变
        bump = math.sin(math.pi * min(max((q - 0.2) / 0.55, 0.0), 1.0)) ** 1.5
        z += TOWARD_KNEE_UP * fk * bump
        y -= TOWARD_KNEE_FWD * fk * bump
    tilt = math.radians(35) * math.sin(math.pi * min(q * 1.6, 1.0)) * (1 - q)
    return y, z, tilt


def pose_hero(parts: dict, anim: str, frame: int, n_frames: int):
    """设置一帧姿态（绝对值，可重复调用）。"""
    ph = 2 * math.pi * (frame % n_frames) / n_frames
    pel, chest = parts["pelvis"], parts["chest"]
    sL, sR, armR, lp = parts["sleeve_L"], parts["sleeve_R"], parts["arm_R"], parts["lantern"]
    lp.location = parts["lantern_loc0"]
    _set_core_strength(parts, 1.0)
    kd, fk = _depth_k(parts), _toward_k(parts)
    coat_split = coat_sway = rib_spread = 0.0  # 长摆尾端向两侧分开 / 左右甩（米）、发带向两侧（见 _ribbon_points）
    coat_fly = 1.0  # 长摆随风往后上方飘的倍数
    coat_pitch = 0.0  # 长摆绕腰线往前转（弧度）
    if anim == "walk":
        p = (frame % n_frames) / n_frames
        wind, rib_phase = WALK_WIND, 2 * ph
        bob = -(WALK_BOB + TOWARD_BOB * fk) * math.cos(2 * math.pi * (2 * p - DUTY))  # 着地中段最低、腾空最高
        pel.location = (0, 0, PELVIS_Z + bob)  # 重心不压低：着地两端腿伸直（IK 会把脚抬起约 2cm），不显得蹲
        pel.rotation_euler = (0, 0, math.radians(4) * math.sin(ph))  # 骨盆随步子微转
        chest.rotation_euler = (math.radians(WALK_LEAN_DEG), 0, math.radians(-3) * math.sin(ph))  # +X 转 = 前倾
        chest.location = (0, 0, 0)
        for side, off, sx in (("L", 0.0, 1), ("R", 0.5, -1)):
            y, z, tilt = _foot_walk((p + off) % 1.0, kd, fk)
            _leg_ik(parts, side, Vector((HIP_X * sx * 0.9, y, ANKLE_Z + z)), tilt,
                    dx=sx * (DEPTH_SPREAD * kd + TOWARD_SPREAD * fk))
        swing = math.sin(ph - 0.5)
        # 纵深朝向：左袖往前摆时略往里收（正面看左右交替；正对镜头摆得更大）；长摆尾端随步子左右甩、后片向两侧分开
        sL.rotation_euler = (math.radians(-(12 + 8 * fk) * swing + 6), math.radians((9 * kd + 6 * fk) * swing),
                             math.radians(-4))
        ka = _away_k(parts)
        coat_split = DEPTH_COAT_SPLIT * ka
        coat_sway = DEPTH_COAT_SWAY * ka * math.sin(ph - 1.2)
        sR.rotation_euler = (math.radians(5 + 6 * swing), 0, 0)
        # 持杖手稳（NW 向杖头正在头顶上方，晃动会被当成配准漂移；上身扭转也只给 ±3°）
        armR.rotation_euler = (math.radians(3 + 0.6 * math.sin(2 * ph)), 0, 0)
        lp.rotation_euler = (math.radians(14 + 8 * math.sin(ph - 1.2)), math.radians(4 * math.sin(2 * ph - 1)), 0)
        parts["pendant"].rotation_euler = (math.radians(16 + 10 * math.sin(2 * ph - 1)), 0, 0)
        parts["sword_tassel"].rotation_euler = (math.radians(30 + 10 * math.sin(2 * ph - 1.4)), 0, 0)
        sleeve_back = 0.10
    elif anim in ("dash", "hurt", "death"):
        wind, rib_phase, sleeve_back = _pose_action(parts, anim, frame, n_frames)
        if anim == "dash":  # 纵深朝向：长摆、发带向两侧拖开（正面、背面都看得见在冲）
            front_k = kd - _away_k(parts)  # 正对镜头那部分
            coat_split = DASH_COAT_SPLIT[0] * front_k + DASH_COAT_SPLIT[1] * _away_k(parts)
            coat_sway = 0.06 * kd * math.sin(ph - 1.0)
            coat_fly = 1.0 - (1.0 - DASH_COAT_FLY) * front_k
            lean = 20 + DASH_LEAN_EXTRA * kd * kd + DASH_LEAN_TOWARD * fk * fk  # 同 _pose_action
            coat_pitch = math.radians(DASH_COAT_UPRIGHT * lean) * front_k
            rib_spread = DASH_RIBBON_SPREAD * (0.3 * front_k + _away_k(parts))  # 正对镜头时少分开（不然在头顶横成一道弧）
    else:  # idle：重心在右腿，左腿放松；微风；呼吸
        wind, rib_phase = IDLE_WIND, ph
        breath = math.sin(ph)
        pel.location = (-0.022, 0, PELVIS_Z - 0.012)
        pel.rotation_euler = (0, math.radians(-2.0), math.radians(-6))
        chest.location = (0, 0, 0.004 * breath)
        chest.rotation_euler = (math.radians(-1.5 + 0.6 * breath), math.radians(3.0), math.radians(8))  # 微后仰：挺胸抬头
        _leg_ik(parts, "R", Vector((-HIP_X - 0.03, 0.01, ANKLE_Z)))  # 承重腿：直立
        _leg_ik(parts, "L", Vector((HIP_X + 0.085, -0.15, ANKLE_Z)))  # 放松腿：前伸外撇，膝微屈
        parts["hip_L"].rotation_euler.z = math.radians(-12)  # 脚尖外撇
        sL.rotation_euler = (math.radians(2 + 1.5 * math.sin(ph - 0.8)), 0, 0)
        sR.rotation_euler = (math.radians(1.0 * math.sin(ph - 0.8)), 0, 0)
        armR.rotation_euler = (math.radians(0.8 * breath), 0, 0)
        lp.rotation_euler = (math.radians(3 * math.sin(ph - 1.0)), math.radians(1.5 * math.cos(ph)), 0)
        parts["pendant"].rotation_euler = (math.radians(3 * math.sin(ph - 1.0)), 0, 0)
        parts["sword_tassel"].rotation_euler = (math.radians(8 + 4 * math.sin(ph - 1.4)), 0, 0)
        sleeve_back = 0.02
    if anim in ("idle", "walk"):
        parts["head"].rotation_euler = (math.radians(-6 if anim != "walk" else -2), 0, 0)  # 抬下巴
    if anim != "idle":
        parts["hip_L"].rotation_euler.z = 0.0
    parts["hip_R"].rotation_euler.z = 0.0
    if anim != "death":
        _back_view_staff(parts)
    wind_hair = min(wind, 1.15)  # 发带/马尾的方向插值不外推太多
    if anim == "dash":
        wind_hair = 0.9  # 冲刺时 S 向发带/马尾正好在头顶后方，飘得太高会被当成冠顶漂移

    # 飘动部件：每帧重建
    slv_l, slv_r = parts["sleeve_mesh"]
    _replace_mesh(slv_l, _sleeve_build(SH_L, CUFF_L, SLEEVE_RADII, SLEEVE_DROOP[0], rib_phase, wind,
                                       swing_back=sleeve_back))
    _replace_mesh(slv_r, _sleeve_build(SH_R, CUFF_R, SLEEVE_RADII, SLEEVE_DROOP[1], rib_phase + 0.7, wind,
                                       swing_back=sleeve_back))
    # 跪下/倒地时长摆按骨盆高度收短，不穿到地面以下（N 向会伸出帧底）
    top_h = pel.location.z + (COAT_TOP - PELVIS_Z)
    for ob, a0, a1, ln, front in parts["coat_panels"]:
        ln_k = min(ln, max(0.25, top_h - 0.04))
        fades: list = []
        split = coat_split * (0.5 if front and anim == "walk" else 1.0)
        _replace_mesh(ob, _grid_build(_coat_panel_rows(a0, a1, ln_k, front, rib_phase, wind, split=split,
                                                       sway=coat_sway, fly=coat_fly, pitch=coat_pitch,
                                                       fades=fades)))
        B.set_point_attr(ob, "fade", fades)
    for ob, thc, w in parts["tunic"]:
        _replace_mesh(ob, _grid_build(_tunic_rows(thc, w, rib_phase, wind * 0.5)))
    _replace_mesh(parts["ponytail"], _ponytail_build(rib_phase, wind_hair))
    rib_a, rib_b = parts["ribbon"]
    _replace_mesh(rib_a, _strip_build(_ribbon_points(0.95, rib_phase, wind_hair, 1.0, spread=rib_spread), 0.066, 0.008,
                                      twist=2.4, taper=(0.8, 1.0)))
    _replace_mesh(rib_b, _strip_build(_ribbon_points(0.80, rib_phase + 1.3, wind_hair, -0.6, spread=rib_spread), 0.060,
                                      0.008, twist=-2.0, taper=(0.8, 1.0)))
    for sx, ob in zip((-1, 1), parts["sidelocks"]):
        _replace_mesh(ob, _strip_build(_sidelock_points(sx, rib_phase, wind_hair), 0.020, 0.009, taper=(1.0, 0.1)))
    for h in parts["lamps"].values():  # 其余几盏灯的枢轴跟着第一盏；挂件（符纸、剑坠、穗子）随风
        if h.pivot is not lp:
            h.pivot.location = lp.location
            h.pivot.rotation_mode = lp.rotation_mode
            h.pivot.rotation_euler = lp.rotation_euler
        h.animate(rib_phase + 0.6, wind)
    bpy.context.view_layer.update()
    if anim == "death":
        _drop_lantern(parts, frame)
        bpy.context.view_layer.update()


# ---------------------------------------------------------------- 背面朝向的灯杖、动作动画
# 背对镜头时（N/NE/NW）杖向前伸就是往画面上方伸，灯笼会悬在头顶；这几个朝向把持杖手臂往外侧摆、
# 压低仰角，让灯笼落在肩旁。朝向由出图流水线在 pose 前写进 parts["dir"]。
# NW 向时右手一侧本身就背离镜头，外摆还会抬高，所以要摆到外后方（-75°）才落在肩旁
BACK_STAFF = {"N": (-22, -48), "NE": (-16, -32), "NW": (-12, -75)}  # (绕前后轴压低, 绕竖轴外摆) 度


def _back_view_staff(parts):
    d = parts.get("dir")
    if d not in BACK_STAFF:
        return
    roll, yaw = BACK_STAFF[d]
    armR = parts["arm_R"]
    armR.rotation_euler = (armR.rotation_euler.x, math.radians(roll), math.radians(yaw))


def _set_core_strength(parts, k):
    """灯芯的自发光强度（死亡动画里灯灭），每盏灯都设。"""
    for h in parts["lamps"].values():
        h.set_core(k)


# 死亡：踉跄 → 单膝跪地 → 前俯 → 灯笼落地 → 伏倒 → 静止；灯芯在最后三帧熄灭
# 第 3 帧起灯笼脱手落在身侧；人跪着拄杖（右臂把杖扶直，杖不会戳出帧底）。
# 帧下方只有 12.5% 帧高（约 0.8 米地面进深），所以前俯幅度、灯笼落点都收在锚点 0.5 米以内。
DEATH = [  # (骨盆 y, 骨盆 z, 胸前俯°, 头°, 左脚(y,z), 右脚(y,z), 右臂俯°, 左袖°, 灯芯亮度)
    (0.03, PELVIS_Z - 0.02, -10, -16, (-0.12, 0.0), (0.02, 0.0), 6, -10, 1.0),
    (0.06, 0.66, 14, 8, (-0.30, 0.0), (0.32, 0.0), 20, 6, 1.0),
    (0.08, 0.58, 30, 22, (-0.30, 0.0), (0.33, 0.0), 0, 14, 0.9),
    (0.10, 0.50, 46, 30, (-0.22, 0.0), (0.34, 0.0), -60, 20, 0.6),
    (0.12, 0.44, 60, 34, (0.04, 0.0), (0.34, 0.0), -78, 26, 0.3),
    (0.12, 0.42, 64, 38, (0.06, 0.0), (0.34, 0.0), -84, 28, 0.08),
]


def _pose_action(parts, anim, frame, n):
    """dash / hurt / death 的姿态。返回 (wind, 飘动相位, 袖后摆)。"""
    pel, chest, head = parts["pelvis"], parts["chest"], parts["head"]
    sL, sR, armR, lp = parts["sleeve_L"], parts["sleeve_R"], parts["arm_R"], parts["lantern"]
    ph = 2 * math.pi * (frame % n) / n
    if anim == "dash":  # 轻功冲刺：前倾 20°，双腿前后大劈，衣摆发带全展
        # 纵深朝向（S/N）再多前倾 DASH_LEAN_EXTRA；两腿左右分开，后蹬的脚抬得更高，往前摆的腿抬膝
        kd = _depth_k(parts)
        p = (frame % n) / n
        pel.rotation_euler = (0, 0, math.radians(5) * math.sin(ph))
        chest.location = (0, 0, 0)
        # 多前倾按 kd² 给：斜向只多一点（NW/NE 灯杖正好在头顶旁边，前倾一变杖头就进“冠顶”量的那一列）；
        # 正对镜头再多前倾、重心再低一点：头肩往前往下，躯干缩短，从正面看得出是扑过来
        fk2 = _toward_k(parts) ** 2
        pel.location = (0, 0.02, PELVIS_Z - 0.06 - 0.04 * fk2 + 0.012 * math.cos(2 * ph))
        lean = 20 + DASH_LEAN_EXTRA * kd * kd + DASH_LEAN_TOWARD * fk2
        chest.rotation_euler = (math.radians(lean), 0, math.radians(-4) * math.sin(ph))
        head.rotation_euler = (math.radians(-14 - 8 * kd * kd - 8 * fk2), 0, 0)  # 抬头看前方
        for side, off, sx in (("L", 0.0, 1), ("R", math.pi, -1)):
            a = 2 * math.pi * p + off
            c = math.cos(a)
            y = -0.44 * c
            z = 0.03 + (0.16 if c < 0 else 0.0) * (-c)  # 后蹬的脚抬起，前脚贴地
            if kd:
                z += kd * (0.16 * max(0.0, -c) + 0.24 * max(0.0, -math.sin(a)))
            _leg_ik(parts, side, Vector((HIP_X * sx * 0.9, y, ANKLE_Z + z)), math.radians(30) * max(0.0, -c),
                    dx=sx * 0.07 * kd)
        sL.rotation_euler = (math.radians(38), 0, math.radians(-8))  # 左袖甩向后
        sR.rotation_euler = (math.radians(14), 0, 0)
        armR.rotation_euler = (math.radians(-6), 0, 0)
        lp.rotation_euler = (math.radians(38 + 4 * math.sin(ph)), 0, 0)  # 灯笼被甩向后
        parts["pendant"].rotation_euler = (math.radians(45), 0, 0)
        parts["sword_tassel"].rotation_euler = (math.radians(60), 0, 0)
        return 1.12, 2 * ph, 0.30  # 再大衣摆/发带就飘出 E/W 帧边
    if anim == "hurt":  # 受击：头和上身向后一挫，灯笼往前甩
        k = (1.0, 0.72)[frame % 2]  # 两帧幅度接近：冠顶前后差不超过配准容差
        pel.location = (-0.02, 0.03 * k, PELVIS_Z - 0.02)
        pel.rotation_euler = (0, 0, 0)
        chest.location = (0, 0, 0)
        chest.rotation_euler = (math.radians(-8 * k), 0, math.radians(4 * k))
        head.rotation_euler = (math.radians(-14 * k), 0, math.radians(5 * k))
        _leg_ik(parts, "R", Vector((-HIP_X - 0.03, 0.03, ANKLE_Z)))
        _leg_ik(parts, "L", Vector((HIP_X + 0.07, -0.13, ANKLE_Z)))
        sL.rotation_euler = (math.radians(-18 * k), 0, 0)
        sR.rotation_euler = (math.radians(-10 * k), 0, 0)
        armR.rotation_euler = (math.radians(-6 * k), 0, 0)
        lp.rotation_euler = (math.radians(-24 * k + 8 * (1 - k)), math.radians(6 * k), 0)
        parts["pendant"].rotation_euler = (math.radians(-12 * k), 0, 0)
        parts["sword_tassel"].rotation_euler = (math.radians(-10 * k), 0, 0)
        return 0.6, 1.5 + frame, 0.0
    # death
    py, pz, lean, hd, fl, fr, arm, sl, core = DEATH[min(frame, len(DEATH) - 1)]
    pel.location = (0, py, pz)
    pel.rotation_euler = (0, 0, 0)
    chest.location = (0, 0, 0)
    chest.rotation_euler = (math.radians(lean), 0, math.radians(4))
    head.rotation_euler = (math.radians(hd), 0, math.radians(-6))
    _leg_ik(parts, "L", Vector((HIP_X + 0.03, fl[0], ANKLE_Z + fl[1])))
    _leg_ik(parts, "R", Vector((-HIP_X - 0.02, fr[0], ANKLE_Z + fr[1])), math.radians(60) if fr[0] > 0.3 else 0.0)
    sL.rotation_euler = (math.radians(sl), 0, math.radians(-6))
    sR.rotation_euler = (math.radians(sl * 0.6), 0, 0)
    armR.rotation_euler = (math.radians(arm), 0, 0)
    lp.rotation_euler = (math.radians(-10 + 12 * math.sin(frame)), 0, 0)
    parts["pendant"].rotation_euler = (math.radians(lean * 0.8), 0, 0)
    parts["sword_tassel"].rotation_euler = (math.radians(lean), 0, 0)
    _set_core_strength(parts, core)
    return 0.15, 0.4 * frame, 0.0


def _drop_lantern(parts, frame):
    """死亡第 3 帧起，灯笼脱手，躺在右前方的地上（直接设世界矩阵）。每盏灯的灯芯落在同一点（lantern 挂点），
    红纸灯、霜瓷灯侧躺，铜镜灯镜面朝下平躺（见 lanterns.Head.drop）。"""
    if frame < 3:
        return
    center = Vector((-0.30, 0.16 + 0.02 * (frame - 3), LAN.DROP_CENTER_Z))  # root 坐标：右侧身旁，离锚点 0.35 米以内
    for h in parts["lamps"].values():
        LAN.drop_head(h, parts["root"], frame, center)


# ================================================================ 出图分层
def lamp_objects(parts, lamp=None) -> list:
    """某盏灯（None = 全部）的网格物体。"""
    heads = parts["lamps"].values() if lamp is None else [parts["lamps"][lamp]]
    return [o for h in heads for o in h.objects()]


def base_scope(parts):
    """主角底图：所有灯笼头都不渲染（灯杖、杖头留在主角身上）。"""
    return B.render_scope(hide=lamp_objects(parts))


def lamp_scope(parts, lamp):
    """某盏灯的叠层：只渲这盏灯；主角身体（含灯杖）换成 Holdout 材质当遮挡物（挡住的灯笼像素透明），
    墨线只画这盏灯自己的（身体仍在 Freestyle 视图图里，挡住灯笼的线）；其余几盏不渲染。"""
    mine = lamp_objects(parts, lamp)
    others = [o for o in lamp_objects(parts) if o not in mine]
    keep = set(mine) | set(others)
    body = [o for o in bpy.context.scene.objects if o.type == "MESH" and o not in keep]
    return B.render_scope(hide=others, holdout=body, lines_only=mine, lines_tag=f"lamp_{lamp}")
