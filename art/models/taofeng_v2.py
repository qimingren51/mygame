"""讨封狐（精修三维）：斗笠蓑衣的矮个路人；进了照见圈现形，是一只穿着不合身人衣、用后腿站着的狐狸。

设定（LORE-TEXT 4.1）：狐狸修行到一半，要讨一句人话。夜里它装成路人，问你：“你看我像不像人？”凑近了，尾巴就露出来了。
外形（世界观会话）：照见圈外是戴斗笠、披蓑衣的矮个路人，佝偻着，斗笠压得看不见脸，蓑衣下摆露出一截毛尾巴；
进了照见圈就现形：一只直立的狐狸穿着不合身的人衣，袖子太长，眯眼笑。主色蓑草黄、狐赭；诡异里带滑稽。
造型：
  扮人（disguise）：佝偻的矮个子，一顶压得很低的大斗笠（竹篾编的，一圈圈、一道道），斗笠顶上顶着三片竹叶
      （狐狸顶叶子变人；现形时这几片叶子飘下来，见 FEEL）；脸在帽檐底下，只有尖尖的黑鼻头探出来；
      身上三层蓑衣（棕黄的蓑草，下摆参差），蓑衣下露出打着绑腿的两条腿、草鞋；近手拄一根竹杖；
      蓑衣后摆底下露出一截毛尾巴（白尖），一步一甩。不发光的眼。
  现形（move）：狐狸用后腿站着、一蹦一蹦地走；斗笠推到脑后、挂在背上（像背着一面圆盘）；
      穿一件太大的旧袍子（褪色的靛蓝麻布，交领，袖子长出爪子一大截、甩来甩去，下摆到小腿），腰上胡乱系一道草绳；
      狐赭的脸、白颊，眯着眼笑（两道往上弯的金色眼缝），嘴角往上翘；腿下半截是黑的（狐狸的“袜子”）；大尾巴白尖。
  reveal（4 帧，不循环）：0 一愣，尾巴从蓑衣底下炸出来、斗笠被耳朵顶起；1 “噗”——蓑衣往上掀开、斗笠弹起、杖脱手，
      顶上的竹叶没了，眼睛亮了；2 蓑衣往后落下去，狐狸伏低；3 站直（接 move 的第 0 帧）。
头、耳借用赤面狐（models/fox_v2.py：同一族），缩小，没有朱砂脸谱；尾巴借用赤面狐的做法，尾尖换成白的。
帧 256²（2 倍；原 224²，现形一跳时蓑衣、尾巴要地方），锚点 (0.5, 0.875)。挂点 eyes（扮人时在帽檐底下脸的位置）。

    root, parts, sockets = build_taofeng_fox()
    pose_taofeng_fox(parts, "disguise", i, 6)
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import bpy
import numpy as np
from mathutils import Vector

ART = Path(__file__).resolve().parents[1]
for p in (ART, ART / "models", ART / "post"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
from style import bstyle as B  # noqa: E402
from style import style as S  # noqa: E402
import kit as K  # noqa: E402
import v2kit as V2  # noqa: E402
import enemy_design as DZ  # noqa: E402
import fox_v2 as FX  # noqa: E402
import bamboo_v2 as BW  # noqa: E402

I, A_ = S.INK, S.ACCENT
EYE = "#FFD23F"
EYE_HOT = "#FFF4C8"
VZ = V2.VZ
d2m = V2.d2m
LAT_RISE = BW.LAT_RISE
STRAW_STOPS = [(0.00, "#1C140C"), (0.18, "#30241A"), (0.36, "#4C3A24"), (0.52, "#685032"), (0.68, "#866A42"),
               (0.84, "#A88A58"), (1.00, "#C8AE7C")]  # 蓑草：暗部焦褐、亮部枯黄（旧了，比斗笠深）
HAT_STOPS = [(0.00, "#2E2416"), (0.2, "#4E3E26"), (0.42, "#7A6440"), (0.62, "#A08654"), (0.82, "#C4AB76"),
             (1.00, "#E0CDA0")]
ROBE_STOPS = [(0.00, "#171C26"), (0.18, "#232C3A"), (0.36, "#33415A"), (0.52, "#465872"), (0.68, "#5E7088"),
              (0.84, "#7E8EA2"), (1.00, "#A3AEBC")]  # 褪色的靛蓝麻布
COLLAR_STOPS = [(0.0, "#4A5466"), (0.5, "#9AA2AE"), (1.0, "#D0D2D0")]  # 交领的里子：发白的旧布
CLOTH_STOPS = [(0.00, I["jiao"]), (0.3, "#2A2622"), (0.6, "#463F36"), (0.85, "#6A6050"), (1.0, "#857A66")]  # 绑腿
# 狐赭：比赤面狐的淡赭深、暖（两只一眼分得开）；明暗和毛色分区走同一条色带（zone 往米白推）
FUR_STOPS = [(0.00, "#2C1A10"), (0.16, "#4A2C17"), (0.30, "#6E4020"), (0.44, "#93582A"), (0.56, "#B06E36"),
             (0.68, "#C98C4E"), (0.80, "#E2B47E"), (0.90, "#F2DCB8"), (1.00, "#FBF1DE")]
SOCK_STOPS = [(0.0, I["jiao"]), (0.45, "#221A15"), (0.8, "#3E3028"), (1.0, "#5A4636")]  # 狐狸腿下半截的黑
CREAM_STOPS = [(0.0, "#B89A78"), (0.4, "#E8D6BA"), (0.7, "#F6EAD6"), (1.0, "#FFFAF0")]
RIM = S.mix("#E8D8B8", I["qing"], 0.25)
HEAD_SCALE = 0.62  # 借用赤面狐的头，缩小

# ---------------------------------------------------------------- 骨架（设计稿单位，x 前、y 上）
HIP_Y = {"human": 16.5, "fox": 16.8}
SPINE = {"human": 11.5, "fox": 12.0}
NECK = 2.4
LEG = {"human": [8.8, 8.4], "fox": [7.2, 6.4, 4.6]}  # 人：大腿、小腿（脚另加）；狐：大腿、小腿、跖（趾行）
ARM = [7.0, 6.6, 3.0]  # 上臂、前臂、手（袖口）
LAT_LEG, LAT_ARM = 0.06, 0.11
GROUND = {"human": 1.1, "fox": 0.9}


def pose_params(anim, i, n):
    """每帧：form（human / fox）、dy、lean（前倾，度）、head（低头为正）、legs/arms 角度（从正下方量，正 = 往前）、
    hat（斗笠：0 压低遮脸、0.5 被顶起、1 弹开、2 挂到背上）、cape（蓑衣：0 披着、1 掀起、2 落到身后、3 没了）、
    tail（0 只露一截 → 1 整条）、puff（尾毛炸开）、eyes（发不发光）、staff（杖：None 没有，否则倾角）、leaf（斗笠顶的竹叶）、ph。"""
    ph = 2 * math.pi * i / n
    if anim == "disguise":  # 人的步子：慢、略蹒跚，拄杖
        legs = {}
        for far, off in ((False, 0.0), (True, math.pi)):
            s = math.sin(ph + off)
            lift = max(0.0, math.cos(ph + off)) ** 1.4
            legs[far] = [2.0 + 14 * s + 7 * lift, -3.0 + 7 * s - 28 * lift, 90.0 - 18 * lift]
        return {"form": "human", "dy": -0.35 + 0.35 * math.cos(2 * ph), "lean": 15.0, "head": 16.0, "legs": legs,
                "arms": {False: [22.0 + 5 * math.sin(ph), 104.0 + 6 * math.sin(ph), 110.0], True: [10.0, 30.0, 30.0]},
                "hat": 0.0, "cape": 0.0, "tail": 0.0, "puff": False, "eyes": False, "staff": 6.0 + 7 * math.sin(ph),
                "leaf": True, "ph": ph, "sleeve": 0.0}
    if anim == "move":  # 现形后：直立着一蹦一蹦地走，袖子甩
        legs = {}
        for far, off in ((False, 0.0), (True, math.pi)):
            s = math.sin(ph + off)
            lift = max(0.0, math.cos(ph + off)) ** 1.2
            legs[far] = [14.0 + 22 * s + 12 * lift, -40.0 + 8 * s - 28 * lift, 30.0 - 8 * s + 26 * lift]
        sw = math.sin(ph)
        return {"form": "fox", "dy": -0.6 + 0.9 * abs(math.cos(ph)), "lean": 4.0 + 2.0 * math.cos(2 * ph),
                "head": -6.0 + 3.0 * math.sin(2 * ph + 0.6), "legs": legs,
                "arms": {False: [10.0 - 34 * sw, 34.0 - 22 * sw, 20.0], True: [10.0 + 34 * sw, 34.0 + 22 * sw, 20.0]},
                "hat": 2.0, "cape": 3.0, "tail": 1.0, "puff": False, "eyes": True, "staff": None, "leaf": False,
                "ph": ph, "sleeve": sw}
    R = [  # reveal：form, dy, lean, head, hat, cape, tail, puff, eyes, 近臂, 远臂, staff, leaf
        ("human", 0.4, 14.0, 6.0, 0.5, 0.0, 0.6, True, False, [30.0, 20.0, 20.0], [10.0, 30.0, 30.0], 14.0, True),
        ("fox", 1.6, -10.0, -16.0, 1.0, 1.0, 1.0, True, True, [150.0, 120.0, 110.0], [-150.0, -120.0, -110.0], None,
         False),
        ("fox", -2.6, 24.0, -4.0, 2.0, 2.0, 1.0, False, True, [40.0, 70.0, 60.0], [20.0, 60.0, 50.0], None, False),
        ("fox", -0.6, 6.0, -8.0, 2.0, 3.0, 1.0, False, True, [14.0, 36.0, 20.0], [6.0, 32.0, 20.0], None, False),
    ]
    form, dy, lean, head, hat, cape, tail, puff, eyes, na, fa, staff, leaf = R[i]
    if form == "human":
        legs = {False: [6.0, -6.0, 90.0], True: [-6.0, -6.0, 90.0]}
    else:
        bend = 1.5 if i == 2 else 1.0
        legs = {False: [16.0 * bend, -42.0 * bend, 32.0 * bend], True: [6.0 * bend, -44.0 * bend, 36.0 * bend]}
        if i == 1:  # 一跳：脚离地
            legs = {False: [24.0, -30.0, 40.0], True: [-4.0, -20.0, 44.0]}
    return {"form": form, "dy": dy, "lean": lean, "head": head, "legs": legs, "arms": {False: na, True: fa},
            "hat": hat, "cape": cape, "tail": tail, "puff": puff, "eyes": eyes, "staff": staff, "leaf": leaf,
            "ph": 2 * math.pi * i / 4, "sleeve": 0.0}


def _chain(root, segs, angs):
    pts = [np.asarray(root, np.float64)]
    for ln, a in zip(segs, angs):
        r = math.radians(a)
        pts.append(pts[-1] + ln * np.array([math.sin(r), -math.cos(r)]))
    return pts


def _ground(chain_fn, g, airborne=False):
    """站地的腿收短：最低的关节低于地面时加大弯曲，二分到正好着地（airborne：一跳时不管）。"""
    if airborne or chain_fn(0.0)[-1][1] >= g:
        return chain_fn(0.0)
    lo, hi = 0.0, 70.0
    for _ in range(36):
        mid = (lo + hi) / 2
        if chain_fn(mid)[-1][1] < g:
            lo = mid
        else:
            hi = mid
    return chain_fn(hi)


def skeleton(p, airborne=False):
    form = p["form"]
    hx, hy = 0.0, HIP_Y[form] + p["dy"]
    a = math.radians(p["lean"])
    sh = (hx + SPINE[form] * math.sin(a), hy + SPINE[form] * math.cos(a))
    ah = math.radians(p["lean"] * 0.6 + p["head"])
    neck = (sh[0] + NECK * math.sin(ah), sh[1] + NECK * math.cos(ah))
    out = {"hip": (hx, hy), "shoulder": sh, "neck": neck, "legs": {}, "arms": {}}
    segs = LEG[form]
    for far, angs in p["legs"].items():
        if form == "fox":
            th, sn, mt = angs

            def fn(d, th=th, sn=sn, mt=mt):
                return _chain((hx, hy), segs, [th + 0.8 * d, sn - 1.1 * d, mt + 0.9 * d])
            pts = _ground(fn, GROUND["fox"], airborne)
            toe = pts[-1] + np.array([2.2, -0.3])
            pts = pts + [toe]
        else:
            th, sn, ft = angs

            def fn(d, th=th, sn=sn):
                return _chain((hx, hy), segs, [th + 0.9 * d, sn - 1.3 * d])
            pts = _ground(fn, GROUND["human"])
            ank = pts[-1]
            r = math.radians(ft)
            pts = pts + [ank + 3.0 * np.array([math.sin(r), -math.cos(r)])]
        out["legs"][far] = [tuple(q) for q in pts]
    for far, (u, f, h) in p["arms"].items():
        root = (sh[0] - 0.4, sh[1] - 1.2)
        out["arms"][far] = [tuple(q) for q in _chain(root, ARM, [u, f, h])]
    return out


# ---------------------------------------------------------------- 几何小件
def tube(c_list, lat, radii, nu=12, nv=None, caps=True):
    """设计稿上的折线 → 管（模型坐标），半径（单位）沿长插值。"""
    pts = [d2m(x, y, lat) for x, y in c_list]
    rr = np.asarray(radii, np.float64) / 25.0

    def prof(t):
        r = float(np.interp(t, np.linspace(0, 1, len(rr)), rr))
        return r, r * 25.0 / VZ, r * 25.0 / VZ
    return V2.tube_arrays(pts, prof, nu=nu, nv=nv or max(8, 4 * len(pts)), cap0=caps, cap1=caps)


def skirt(top, bot, r_top, r_bot, lat0=0.0, nu=36, nv=9, fringe=0.0, seed=0, sway=0.0, flare=0.0, open_top=True,
          bulge=0.0):
    """一圈衣摆 / 蓑衣（设计稿的上口中心 top、下口中心 bot）：半径 (左右, 前, 后)（单位）；
    fringe > 0：下摆参差（蓑草）；sway：下摆往后甩多少单位；flare：下摆往外张；bulge：中段往外鼓（驼背）。
    属性 su（上 0 → 下 1）、sv（绕一圈）、zone（上口一圈压暗：被上一层盖住的地方）。"""
    rng = np.random.default_rng(seed)
    jag = rng.uniform(0.0, 1.0, nu)
    V, su, sv, zn = [], [], [], []
    for j in range(nv):
        t = j / (nv - 1)
        cx = top[0] + (bot[0] - top[0]) * t - sway * t ** 1.5
        cy = top[1] + (bot[1] - top[1]) * t
        k = 1.0 + flare * t ** 2 + bulge * math.sin(math.pi * t)
        rl = (r_top[0] + (r_bot[0] - r_top[0]) * t ** 0.85) * k
        rf = (r_top[1] + (r_bot[1] - r_top[1]) * t ** 0.85) * k
        rb = (r_top[2] + (r_bot[2] - r_top[2]) * t ** 0.85) * k
        for i in range(nu):
            th = 2 * math.pi * i / nu
            c, s_ = math.cos(th), math.sin(th)
            dx = (rf if s_ > 0 else rb) * s_  # 设计稿 x：s_ > 0 往前
            dy = 0.0
            if fringe and j == nv - 1:
                dy = -fringe * (0.35 + 0.65 * jag[i]) * (1.0 if i % 2 else 0.6)
            p = d2m(cx + dx, cy + dy, lat0 + rl / 25.0 * c)
            V.append(tuple(p))
            su.append(t)
            sv.append(i / nu)
            zn.append(-0.45 * max(0.0, 1 - t / 0.3) ** 1.5)
    F = [(j * nu + i, (j + 1) * nu + i, (j + 1) * nu + (i + 1) % nu, j * nu + (i + 1) % nu)
         for j in range(nv - 1) for i in range(nu)]
    if not open_top:
        V.append(tuple(d2m(top[0], top[1] + 0.3, lat0)))
        su.append(0.0); sv.append(0.0); zn.append(-0.4)
        c0 = len(V) - 1
        F += [(c0, (i + 1) % nu, i) for i in range(nu)]
    return V, F, {"su": su, "sv": sv, "zone": zn}


def hat_arrays(r_u=10.5, h_u=4.6, nu=48, nv=10):
    """斗笠（局部坐标：原点在帽里头顶，帽檐往下张）：矮圆锥，顶上一个小尖、帽檐略往下弯；属性 su（顶 → 檐）、sv（一圈）。"""
    r, h = r_u / 25.0, h_u / VZ
    V, su, sv = [(0.0, 0.0, h * 0.78 + 0.03)], [0.0], [0.0]
    for j in range(1, nv):
        t = j / (nv - 1)
        rr = r * t
        z = h * 0.78 - h * t ** 0.9 - 0.016 * t ** 4
        for i in range(nu):
            th = 2 * math.pi * i / nu
            V.append((rr * math.cos(th), rr * math.sin(th), z))
            su.append(t)
            sv.append(i / nu)
    F = [(0, 1 + (i + 1) % nu, 1 + i) for i in range(nu)]
    for j in range(nv - 2):
        a0, a1 = 1 + j * nu, 1 + (j + 1) * nu
        F += [(a0 + i, a0 + (i + 1) % nu, a1 + (i + 1) % nu, a1 + i) for i in range(nu)]
    b0 = len(V)  # 帽檐的厚度、帽里
    last = 1 + (nv - 2) * nu
    for i in range(nu):
        x, y, z = V[last + i]
        V.append((x * 0.97, y * 0.97, z - 0.01)); su.append(1.0); sv.append(i / nu)
    F += [(last + i, b0 + i, b0 + (i + 1) % nu, last + (i + 1) % nu) for i in range(nu)]
    V.append((0.0, 0.0, h * 0.5)); su.append(1.0); sv.append(0.0)
    c1 = len(V) - 1
    F += [(c1, b0 + (i + 1) % nu, b0 + i) for i in range(nu)]
    return V, F, {"su": su, "sv": sv}


def _merge(arrs):
    V, F, A = [], [], {}
    keys = set()
    for _, _, a in arrs:
        keys |= set(a)
    for v, f, a in arrs:
        o = len(V)
        n = len(v)
        V.extend(list(v))
        F.extend([tuple(i + o for i in ff) for ff in f])
        for k in keys:
            A.setdefault(k, []).extend(list(a.get(k, [0.0] * n)))
    return V, F, A


def _set(ob, V, F, A, smooth=True):
    K.replace_mesh(ob, V2.arrays_build(V, F), smooth=smooth, attrs=A)


def fur_material(name, seed, stops=FUR_STOPS, streak=0.18, bias=-0.36, rim=0.55):
    return V2.paint_material(name, stops, wash=0.26, wash_scale=2.6, seed=seed, shade_attr="zone", shade_gain=1.0,
                             streak=streak, streak_scale=(4.0, 60.0), rim_hex=RIM, rim=rim, rim_power=2.4,
                             value_var=0.05, edge=0.22, bias=bias)


# ---------------------------------------------------------------- 组装
def build_taofeng_fox():
    root = B.empty("TFRoot")
    body = B.empty("TFBody", root)
    m_straw = V2.paint_material("TFStraw", STRAW_STOPS, wash=0.3, wash_scale=3.0, seed=41.0, shade_attr="zone",
                                streak=0.42, streak_scale=(70.0, 3.0), rim_hex=S.mix("#E6D3A8", I["qing"], 0.3), rim=0.45,
                                value_var=0.08, edge=0.3, bias=0.02)
    m_hat = V2.paint_material("TFHat", HAT_STOPS, wash=0.25, wash_scale=3.0, seed=42.0, streak=0.3,
                              streak_scale=(90.0, 10.0), rim_hex=S.mix("#E6D3A8", I["qing"], 0.3), rim=0.35,
                              value_var=0.06, edge=0.25, bias=0.08)
    m_robe = V2.paint_material("TFRobe", ROBE_STOPS, wash=0.32, wash_scale=2.4, seed=43.0, shade_attr="zone",
                               streak=0.1, streak_scale=(20.0, 3.0), rim_hex=S.mix("#C9D6DC", I["qing"], 0.3), rim=0.45,
                               value_var=0.08, edge=0.3, bias=-0.02)
    m_collar = V2.paint_material("TFCollar", COLLAR_STOPS, wash=0.2, seed=44.0, edge=0.0)
    m_cloth = V2.paint_material("TFCloth", CLOTH_STOPS, wash=0.25, seed=45.0, edge=0.2, bias=0.05, streak=0.3,
                                streak_scale=(4.0, 40.0))
    m_stick = V2.paint_material("TFStick", [(0.0, "#2A2418"), (0.35, "#5C5234"), (0.7, "#8E8050"), (1.0, "#C2B07A")],
                                wash=0.2, seed=46.0, edge=0.15, shade_attr="nodeshade")
    m_node = V2.paint_material("TFStickNode", [(0.0, I["jiao"]), (0.6, "#2E2A1E"), (1.0, "#4E4630")], wash=0.2, seed=47.0,
                               edge=0.0)
    m_rope = V2.paint_material("TFRope", [(0.0, "#2A2017"), (0.5, "#6E5A3A"), (1.0, "#B09468")], wash=0.3, seed=48.0)
    m_fur = fur_material("TFFur", 49.0)
    m_fur_far = fur_material("TFFurFar", 50.0, bias=-0.6, rim=0.3)
    m_sock = V2.paint_material("TFSock", SOCK_STOPS, wash=0.2, seed=51.0, edge=0.1, rim_hex=I["zhong"], rim=0.5)
    m_tail = fur_material("TFTail", 52.0, streak=0.25)
    m_tip = V2.paint_material("TFTailTip", CREAM_STOPS, wash=0.2, seed=53.0, edge=0.1, rim_hex=RIM, rim=0.3)
    m_head = fur_material("TFFurHead", 54.0)
    m_head_dark = fur_material("TFFurHeadDark", 54.0, bias=-1.05, rim=0.15)
    m_cream = V2.paint_material("TFCream", CREAM_STOPS, wash=0.2, seed=55.0, edge=0.1)
    m_ink = V2.paint_material("TFInk", FX.INK_STOPS, wash=0.2, seed=56.0, rim_hex=I["zhong"], rim=0.5, edge=0.1)
    m_leaf = V2.brush_material("TFLeaf", BW.LEAF_LIGHT, edge_soft=0.22, edge_dark=0.25, streak=0.3, streak_from=0.5,
                               scale=(5.0, 10.0), fade_from=0.92, seed=57.0)
    m_jiao = B.flat_material("TFJiao", I["jiao"])
    parts = {"root": root, "body": body, "dyn": {}}

    def dyn(name, mat, line="outer"):
        ob = V2.mesh_from_arrays(name, [(0, 0, 0), (0.001, 0, 0), (0, 0.001, 0)], [(0, 1, 2)], mat, line, body)
        parts["dyn"][name] = ob
        return ob

    for nm, mat, line in (("Cape", m_straw, "outer"), ("CapeTop", m_straw, "outer"), ("Robe", m_robe, "outer"),
                          ("RobeFar", m_robe, "outer"), ("Sleeves", m_robe, "outer"), ("SleevesFar", m_robe, "outer"),
                          ("Collar", m_collar, "inner"), ("Belt", m_rope, "inner"), ("LegsHuman", m_cloth, "outer"),
                          ("Sandals", m_straw, "inner"), ("LegsFox", m_fur, "outer"), ("LegsFoxFar", m_fur_far, "outer"),
                          ("Socks", m_sock, "outer"), ("Hands", m_cloth, "inner"), ("Stick", m_stick, "inner"),
                          ("StickNodes", m_node, "inner"), ("Leaf", m_leaf, "none")):
        dyn(nm, mat, line)
    # 头：借用赤面狐的头和耳（缩小）
    head_piv = B.empty("TFHeadPivot", body)
    head_s = B.empty("TFHeadScale", head_piv)
    head_s.scale = (HEAD_SCALE, HEAD_SCALE, HEAD_SCALE)
    head_yaw = B.empty("TFHeadYaw", head_s, rot=(0, 0, math.radians(-16)))
    neck0 = d2m(*DZ.FOX_NECK)
    head = FX.build_head(head_yaw, m_head)
    ear_n = FX.build_ear("TFEarNear", DZ.FOX_EAR_NEAR, head_yaw, m_head, m_cream, m_ink, neck0)
    ear_f = FX.build_ear("TFEarFar", DZ.FOX_EAR_FAR, head_yaw, m_head, m_cream, m_ink, neck0)
    ear_n.location.x -= 0.07
    ear_f.location.x += 0.09
    B.mesh_object("TFNose", K.ellipsoid((0.032, 0.026, 0.024)), m_jiao, "none", head_yaw,
                  loc=d2m(*DZ.FOX_NOSE) - neck0 + Vector((0, -0.006, 0.006)))
    # 斗笠（挂在 hat 空物体上，每帧摆）
    hat_piv = B.empty("TFHatPivot", body)
    hv, hf, ha = hat_arrays()
    hat = V2.mesh_from_arrays("TFHat", hv, hf, m_hat, "outer", hat_piv, attrs=ha)
    parts.update(head_piv=head_piv, head_yaw=head_yaw, head=head, ears=(ear_n, ear_f), hat_piv=hat_piv, hat=hat,
                 m_head=m_head, m_head_dark=m_head_dark)
    # 尾巴（每帧重建，借用赤面狐的尾巴做法；尾尖白）
    tail_s = B.empty("TFTailScale", body)
    tail_s.scale = (0.62, 0.62, 0.62)
    tail = B.mesh_object("TFTail", lambda bm: None, [m_tail, m_tip], "outer", tail_s)
    tail_f = B.mesh_object("TFTailFur", lambda bm: None, [m_tail, m_tip], "none", tail_s)
    bpy.data.collections[B.CONTOUR_COLLECTION].objects.link(tail_f)
    parts.update(tail=tail, tail_f=tail_f, tail_s=tail_s, eyes=[])
    # 脸：现形的姿态下按设计稿投到头上——眯着笑的眼（两道往上弯的金色眼缝）、往上翘的嘴角
    B.set_direction(root, "E")
    pose_taofeng_fox(parts, "move", 0, 6)
    bpy.context.view_layer.update()
    tree = V2.bvh_world(head)
    m_eye = B.emissive_material("TFEye", EYE, 1.0)
    m_hot = B.emissive_material("TFEyeHot", EYE_HOT, 1.0)
    eyes = []
    (ex, ey), hl, hh, tilt = DZ.FOX_EYE2
    cx, cy = _world_to_design(head_yaw.matrix_world @ (d2m(ex, ey) - neck0))
    k = HEAD_SCALE * 1.05
    for nm, mat, th, lift in (("Ink", m_jiao, 1.0, 0.004), ("Eye", m_eye, 0.62, 0.006), ("Hot", m_hot, 0.3, 0.008)):
        poly = _crescent(cx, cy, hl * k, hh * k * 1.25, th, tilt=-14.0)
        ob = V2.design_patch(f"TF{nm}", tree, V2.closed_smooth(poly, 40), mat, head_yaw, lift=lift, spacing=0.12)
        if nm != "Ink":
            eyes.append(ob)
    # 远眼：一小道
    (fx, fy), fl, fh, _ = DZ.FOX_EYE_FAR
    fxs, fys = _world_to_design(head_yaw.matrix_world @ (d2m(fx, fy) - neck0))
    for nm, mat, th, lift in (("FarInk", m_jiao, 1.0, 0.004), ("FarEye", m_eye, 0.6, 0.006)):
        poly = _crescent(fxs - 0.2, fys + 0.1, fl * k * 1.5, fh * k * 1.4, th, tilt=8.0)
        ob = V2.design_patch(f"TF{nm}", tree, V2.closed_smooth(poly, 30), mat, head_yaw, lift=lift, spacing=0.1)
        if ob is not None and nm != "FarInk":
            eyes.append(ob)
    # 嘴：从鼻下往后、嘴角往上翘（笑）
    mouth = [_world_to_design(head_yaw.matrix_world @ (d2m(x, y) - neck0)) for x, y in
             DZ.FOX_HEAD_PTS["mouth"]]
    mouth = mouth + [(mouth[-1][0] - 0.6, mouth[-1][1] + 0.7)]
    V2.design_outline("TFMouth", tree, mouth, [0.28, 0.34, 0.34, 0.3, 0.2], m_jiao, head_yaw, lift=0.005, closed=False)
    parts["eyes"] = eyes
    sock = B.empty("TFSocketEyes", head_yaw)
    sock.location = d2m(ex * 0.75 + fx * 0.25, ey * 0.75 + fy * 0.25) - neck0
    B.set_direction(root, "S")
    parts["sockets"] = {"eyes": sock}
    pose_taofeng_fox(parts, "disguise", 0, 6)
    return root, parts, parts["sockets"]


def _crescent(cx, cy, hl, hh, thick, tilt=0.0, n=14):
    """眯着笑的眼：一道往上拱的弯（∩），中间粗两头尖；thick 是相对粗细。"""
    pts_top, pts_bot = [], []
    for t in np.linspace(-1, 1, n):
        y_top = hh * (1 - t * t) ** 0.8
        w = hh * 0.62 * thick * (1 - t * t) ** 0.6
        pts_top.append((t * hl, y_top))
        pts_bot.append((t * hl * 0.92, y_top - w))
    pts = pts_top + pts_bot[::-1]
    a = math.radians(tilt)
    return [(cx + x * math.cos(a) - y * math.sin(a), cy - hh * 0.4 + x * math.sin(a) + y * math.cos(a)) for x, y in pts]


def _world_to_design(w):
    right, up, _ = B.camera_basis()
    return 25.0 * w.dot(right), 25.0 * w.dot(up)


def _place_head(parts, sk, p):
    hp = parts["head_piv"]
    neck = sk["neck"]
    hp.location = d2m(*neck)
    hp.rotation_euler = (math.radians(-(p["head"] * 0.8 + p["lean"] * 0.3)), 0, 0)
    for e in parts["eyes"]:
        e.hide_render = not p["eyes"]
    for e in parts["ears"]:
        e.hide_render = p["form"] == "human" and p["hat"] < 0.5
    # 扮人时脸在帽檐的阴影里：头换成暗一档的毛色
    parts["head"].data.materials[0] = parts["m_head_dark"] if p["form"] == "human" else parts["m_head"]
    # 斗笠：扮人时压低遮住脸；被耳朵顶起；弹开；挂到背上（像背着一面圆盘）
    hat = parts["hat_piv"]
    t = p["hat"]
    nx, ny = neck
    if t <= 0.0:
        c, rot = (nx + 3.4, ny + 4.9), (17.0, 0.0)
    elif t <= 0.5:
        c, rot = (nx + 3.0, ny + 8.0), (6.0, -8.0)
    elif t <= 1.0:
        c, rot = (nx - 3.6, ny + 11.0), (-58.0, 0.0)
    else:  # 挂到背上（绳子勒在脖子上）：帽口贴着后背，帽顶朝后、略朝镜头转，看得出是一面圆的斗笠
        c, rot = (nx - 6.4, ny - 2.6), None
    lat = {True: 0.0, False: 0.14}[t < 1.0]
    hat.location = d2m(c[0], c[1] - LAT_RISE * lat, lat)
    if rot is None:
        axis = Vector((-0.62, 0.72, 0.32)).normalized()  # 帽顶的朝向（模型坐标：-X 朝镜头、+Y 往后）
        hat.rotation_euler = axis.to_track_quat("Z", "Y").to_euler()
    else:
        hat.rotation_euler = (math.radians(rot[0]), math.radians(rot[1]), 0)


def pose_taofeng_fox(parts, anim, frame, n):
    p = pose_params(anim, frame, n)
    sk = skeleton(p, airborne=(anim == "reveal" and frame == 1))
    D = parts["dyn"]
    form = p["form"]
    hip, sh = np.asarray(sk["hip"]), np.asarray(sk["shoulder"])
    groups = {k: [] for k in D}
    walk = math.sin(2 * p["ph"])
    # 腿
    for far in (False, True):
        lat = LAT_LEG if far else -LAT_LEG
        pts = [np.asarray(q) for q in sk["legs"][far]]
        if form == "human":
            groups["LegsHuman"].append(tube(pts[:3], lat, [2.0, 1.6, 1.35]))
            groups["Sandals"].append(tube([pts[2] + np.array([-1.0, -0.3]), pts[3] + np.array([0.4, 0.0])], lat,
                                          [1.0, 0.85], nu=8))
        else:
            groups["LegsFoxFar" if far else "LegsFox"].append(tube(pts[:3], lat, [2.1, 1.5, 1.0]))
            groups["Socks"].append(tube([pts[1] + (pts[2] - pts[1]) * 0.55, pts[2], pts[3], pts[4]], lat,
                                        [0.95, 0.8, 0.85, 0.55], nu=10))
    # 尾巴：扮人时只露一截（蓑衣后摆底下），现形后整条甩出来、白尖
    tl = p["tail"]
    root_t = (hip[0] - 2.4, hip[1] - 3.2 - 5.0 * (1 - tl))
    ang = 205 - 40 * tl
    c2 = DZ.fox_tail_curve(root_t, angle=ang, curl=-6.0 * tl - 2.0, wave=7.0, ph=p["ph"], n=18,
                           length=DZ.FOX_TAIL_LEN * (0.55 + 0.45 * tl) * 0.95)
    cm = [d2m(x, y, 0.07) / 0.62 for x, y in c2]
    tube_b, fur_b = FX._tail_geom(cm, 1.3 if p["puff"] else 1.0)
    K.replace_mesh(parts["tail"], tube_b)
    K.replace_mesh(parts["tail_f"], fur_b)
    # 袍子（现形；扮人时也在蓑衣底下，看不见就不建）
    lean = math.radians(p["lean"])
    if form == "fox" or p["cape"] >= 1:
        hem_y = 9.4 + 0.8 * walk * (form == "fox")
        waist = hip + (sh - hip) * 0.24
        # 上身：肩 → 腰（松垮，略鼓）；下摆：腰 → 小腿（往外张、往后甩）
        groups["Robe"].append(skirt((sh[0] - 0.5, sh[1] - 0.2), (waist[0] - 0.2, waist[1]), (2.3, 2.3, 2.7),
                                    (3.3, 3.5, 3.7), lat0=-0.005, nu=36, nv=7, bulge=0.14, open_top=False))
        groups["Robe"].append(skirt((waist[0] - 0.2, waist[1] + 0.3), (hip[0] - 1.0, hem_y), (3.2, 3.4, 3.6),
                                    (5.6, 6.0, 6.6), lat0=-0.005, nu=40, nv=9, sway=1.2 + 0.8 * walk, flare=0.12))
        # 交领：从颈前斜着压到腰前（右压左，一道发白的布边，在近镜头的这一面）
        nk = np.asarray(sk["neck"])
        col = [nk + np.array([0.6, -1.4]), sh + np.array([1.4, -2.6]), waist + np.array([2.4, 1.6]),
               waist + np.array([2.6, 0.2])]
        groups["Collar"].append(tube(col, -0.125, [0.6, 0.65, 0.55, 0.4], nu=8))
        # 草绳：腰上一圈 + 前面垂下的两截
        ring = [d2m(waist[0] - 0.2 + 3.75 * math.sin(th), waist[1] + 0.5 * math.cos(th), -0.005 - 0.142 * math.cos(th))
                for th in np.linspace(0, 2 * math.pi, 25)]
        groups["Belt"].append(V2.tube_arrays(ring, lambda t: (0.016, 0.016, 0.016), nu=6, nv=25, cap0=False, cap1=False))
        knot = (waist[0] + 3.4, waist[1] - 0.3)
        groups["Belt"].append(tube([knot, (knot[0] + 0.6, knot[1] - 2.6), (knot[0] + 0.2 + 0.6 * walk, knot[1] - 4.6)],
                                   -0.12, [0.45, 0.4, 0.3], nu=6))
        # 袖子：宽、长出爪子一大截，袖口往下耷拉、跟着甩
        for far in (False, True):
            lat = LAT_ARM if far else -LAT_ARM
            pts = [np.asarray(q) for q in sk["arms"][far]]
            sl = pts[2] + (pts[3] - pts[2]) * 0.8
            droop = np.array([-1.2 * p["sleeve"] * (1 if far else -1), -3.4])
            path = [pts[0], pts[1], pts[2], sl + droop * 0.4, sl + droop]
            groups["SleevesFar" if far else "Sleeves"].append(tube(path, lat, [1.7, 1.7, 2.1, 2.4, 2.2], nu=14))
            # 袖口：一圈发白的里子（袖子长出爪子一大截，耷拉着）
            e0, e1 = sl + droop * 0.78, sl + droop * 1.02
            groups["Collar"].append(tube([e0, e1], lat - 0.004, [2.38, 2.3], nu=14))
    # 蓑衣：三层（披肩、中、下），佝偻的背往外鼓；现形时掀起、落到身后
    cape = p["cape"]
    if cape < 3:
        nk = np.asarray(sk["neck"])
        if cape == 0:
            tiers = [((nk[0] - 1.4, nk[1] - 0.6), (sh[0] - 2.6, sh[1] - 8.6), (2.4, 2.2, 3.0), (7.4, 6.0, 7.6), 1.6),
                     ((sh[0] - 1.0, sh[1] - 4.2), (hip[0] - 1.8, hip[1] - 2.4), (5.0, 4.6, 5.6), (8.2, 7.0, 8.2), 1.8),
                     ((hip[0] - 0.8, hip[1] + 1.4), (hip[0] - 1.2, 10.8), (6.6, 6.0, 7.0), (8.8, 7.8, 8.6), 2.0)]
            sway = 0.6 * walk
        elif cape == 1:  # 掀起：整片往上、往外翻开
            tiers = [((nk[0] - 1.2, nk[1] + 1.0), (nk[0] - 6.0, nk[1] + 8.5), (2.6, 2.4, 3.2), (9.0, 7.0, 10.0), 2.0),
                     ((sh[0] - 2.0, sh[1] - 1.0), (sh[0] - 9.0, sh[1] + 5.0), (5.0, 4.4, 6.0), (10.0, 8.0, 10.0), 2.2)]
            sway = -2.0
        else:  # 落到身后：一团塌下去的蓑草
            tiers = [((hip[0] - 6.0, 9.0), (hip[0] - 9.0, 1.2), (4.0, 3.0, 4.0), (9.0, 6.0, 9.0), 2.4),
                     ((hip[0] - 8.0, 5.0), (hip[0] - 10.0, 0.6), (6.0, 5.0, 6.0), (10.0, 7.0, 9.0), 2.0)]
            sway = 1.0
        for k, (top, bot, rt, rb, fr) in enumerate(tiers):
            key = "CapeTop" if k == 0 else "Cape"
            groups[key].append(skirt(top, bot, rt, rb, lat0=0.0, nu=44, nv=8, fringe=fr, seed=60 + k, sway=sway,
                                     flare=0.12, bulge=0.12 if cape == 0 else 0.0))
    # 手：扮人时近手从蓑衣里伸出来握杖（裹着布）
    if form == "human":
        pts = [np.asarray(q) for q in sk["arms"][False]]
        groups["Hands"].append(tube([pts[1] - (pts[2] - pts[1]) * 0.15, pts[2]], -LAT_ARM - 0.02, [1.05, 0.9], nu=12))
        groups["Hands"].append(tube([pts[2] - (pts[3] - pts[2]) * 0.15, pts[2] + (pts[3] - pts[2]) * 0.3],
                                    -LAT_ARM - 0.035, [1.0, 0.85], nu=10))
    # 杖：近手握着，杖头往前下方拄地（一根细竹，带竹节）
    if p["staff"] is not None:
        hand = np.asarray(sk["arms"][False][2])
        a = math.radians(p["staff"])
        down = np.array([math.sin(a), -math.cos(a)])
        top = hand - down * 4.5
        bot = hand + down * ((hand[1] - 0.3) / max(math.cos(a), 0.3))
        b_, r_, _ = BW.culm([bot, top], -LAT_ARM - 0.04, 0.62, [0.3, 0.62], 0.0, taper=0.1, end_nodes=(False, True))
        groups["Stick"] += b_
        groups["StickNodes"] += r_
    # 头、斗笠、眼、耳
    _place_head(parts, sk, p)
    # 斗笠顶上三片竹叶（狐狸顶叶子变人）
    if p["leaf"]:
        hp = parts["hat_piv"]
        bpy.context.view_layer.update()
        top_w = hp.matrix_world @ Vector((0.0, 0.0, 4.6 / VZ * 0.78 + 0.03))
        tx, ty = _world_to_design(top_w)
        base = (tx - 0.2, ty + 0.2)
        for k, (a0, a1, ln, w) in enumerate(((150, 205, 7.0, 1.7), (95, 30, 6.0, 1.5), (60, -10, 5.5, 1.4))):
            groups["Leaf"].append(BW.leaf(base, a0, a1, ln, w, -0.3 - 0.01 * k, turn=0.9, ph=p["ph"] + k, sway=6.0,
                                          ref_lat=0.0))
    for k, arrs in groups.items():
        ob = D[k]
        if arrs:
            _set(ob, *_merge(arrs), smooth=(k != "Leaf"))
            ob.hide_render = False
        else:
            ob.hide_render = True
    bpy.context.view_layer.update()
