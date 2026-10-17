"""抢先体验新法器里要立体渲的两样：孔明灯（天上飘的纸灯）、镇妖塔（七层小塔）。出图见 render/weapons_ea_render.py，
渲出来的帧再由 post/weapon_textures_ea.py 改名、加上 2D 的火和光，进 vfx 图集的 weapons/sky_lantern*、weapons/tower*。

孔明灯（docs/BALANCE.md 6.3：宽 20、高 26 世界单位）：
  上宽下窄的纸袋，顶上圆鼓，六片纸拼成（接缝一道深一点的纸色），下口一圈竹篾。灯在里面烧，看不见火，
  整张纸透着光：近火的下半截浅黄，往上橙，顶上深橙（kit.flame_material 沿 fade 分段，整张纸进发光层）。
  float 4 帧循环：在画面里左右轻轻摆（±1.5°）。
  fall 3 帧：往一边歪倒（18° → 42° → 70°），纸从下口一侧烧起来——烧穿的地方透空，边上一圈焦黑，
  烧着的边上窜起几条火舌，越烧越大；纸袋烧瘪了往下塌。
  锚点在灯身中心（游戏在这里放辉光和光源），帧 96²×密度。

    root, parts, sockets = build_sky_lantern()
    pose_sky_lantern(parts, "fall", 1, 3)
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

I, A, W = S.INK, S.ACCENT, S.WASH

# ================================================================ 孔明灯
LANTERN_FRAME_1X = 96  # 2 倍 192²（歪倒、火舌窜出来也不出框）
LANTERN_ANCHOR = (0.5, 0.5)  # 锚点 = 灯身中心
SL_R_TOP, SL_R_BOT, SL_H = 0.36, 0.29, 0.86  # 米：屏幕上约宽 18、高 27 世界单位
SL_PANELS = 6
# 纸：沿 fade（离灯里那团火的远近，0 = 贴着火 → 1 = 最远的顶角）分段，每段三档（亮, 中, 暗）；都是发光色，不吸附调色板
PAPER_BANDS = [(0.0, ("#FFF6DC", "#FFE6A6", "#FFD083")),
               (0.36, ("#FFD08A", "#FBB064", "#EE924B")),
               (0.72, ("#F39A4E", "#E07B3C", "#C45C30"))]
SL_FIRE_AT = (0.0, -0.06, -0.31)  # 灯里那团火（米，灯身坐标）：下口上方、略朝镜头
SL_GLOW_R = 0.78  # fade = 离火的距离 ÷ 这个
FIRE_BANDS = [(0.0, ("#FFF4D2", "#FFE09A", "#FFC46A")),
              (0.45, ("#FFB056", "#FF8A3D", "#F06A2C")),
              (0.8, ("#E2552A", "#C23A2B", "#9C2E22"))]
CHAR_HEX = I["nong"]  # 烧焦的纸边
SEAM_HEX = S.shade_ramp(A["zheshi"])[0]  # 纸的接缝：浅赭（不发光，夜里是一道暗线）
PALETTE_EXTRA = sorted({c for _, r in PAPER_BANDS + FIRE_BANDS for c in r})

# 每帧的姿态：(在画面里歪多少度, 烧到哪（越小烧得越多，99 = 没烧）, 火舌长度倍数, 纸袋塌下去多少)
SL_POSES = {
    "float": [(0.0, 99.0, 0.0, 1.0), (1.5, 99.0, 0.0, 1.0), (0.0, 99.0, 0.0, 1.0), (-1.5, 99.0, 0.0, 1.0)],
    "fall": [(18.0, 0.86, 0.55, 0.97), (42.0, 0.66, 1.0, 0.9), (70.0, 0.46, 1.3, 0.8)],
}


def _profile():
    """纸袋的剖面（r, z），下口 → 顶，z 以灯身中心为 0。"""
    zb, zt = -SL_H / 2, SL_H / 2
    # 下口收、中上鼓（像一口倒扣的钟），顶上圆拱：免得看成一只倒扣的杯子
    pts = [(SL_R_BOT * 0.92, zb), (SL_R_BOT, zb + 0.06), (0.322, zb + 0.24), (0.352, zb + 0.44), (SL_R_TOP + 0.01, zb + 0.6),
           (SL_R_TOP, zt - 0.17), (0.335, zt - 0.1), (0.29, zt - 0.05), (0.21, zt - 0.018), (0.1, zt - 0.003), (0.0, zt)]
    return pts


def _burn_material(m, seed: float):
    """在纸的材质后面接“烧”：b = 下口高、偏 +x 一侧高、加噪声；b > BurnT 烧穿（透空），差 0.07 以内是焦黑的边。
    BurnT 是材质里一个数值节点，pose 时按帧改；99 = 没烧。"""
    nt = m.node_tree
    N, L = nt.nodes, nt.links
    out = next(n for n in N if n.type == "OUTPUT_MATERIAL")
    link = out.inputs["Surface"].links[0]
    src = link.from_socket
    nt.links.remove(link)
    tc = N.new("ShaderNodeTexCoord")
    sep = N.new("ShaderNodeSeparateXYZ")
    L.new(tc.outputs["Object"], sep.inputs["Vector"])
    nz = N.new("ShaderNodeTexNoise")
    nz.inputs["Scale"].default_value = 5.5
    nz.inputs["Detail"].default_value = 4.0
    nz.noise_dimensions = "4D"
    nz.inputs["W"].default_value = seed
    L.new(tc.outputs["Object"], nz.inputs["Vector"])
    # b = 0.5 - z / H + 0.35 * x / R + 0.5 * (noise - 0.5)
    zt = N.new("ShaderNodeMath"); zt.operation = "MULTIPLY_ADD"
    zt.inputs[1].default_value = -1.0 / SL_H; zt.inputs[2].default_value = 0.5
    L.new(sep.outputs["Z"], zt.inputs[0])
    xt = N.new("ShaderNodeMath"); xt.operation = "MULTIPLY_ADD"
    xt.inputs[1].default_value = 0.35 / SL_R_TOP
    L.new(sep.outputs["X"], xt.inputs[0]); L.new(zt.outputs["Value"], xt.inputs[2])
    nt_ = N.new("ShaderNodeMath"); nt_.operation = "MULTIPLY_ADD"
    nt_.inputs[1].default_value = 0.5
    L.new(nz.outputs["Fac"], nt_.inputs[0]); L.new(xt.outputs["Value"], nt_.inputs[2])
    bval = N.new("ShaderNodeMath"); bval.operation = "ADD"; bval.inputs[1].default_value = -0.25
    L.new(nt_.outputs["Value"], bval.inputs[0])
    thr = N.new("ShaderNodeValue"); thr.name = "BurnT"
    thr.outputs[0].default_value = 99.0
    hole = N.new("ShaderNodeMath"); hole.operation = "GREATER_THAN"
    L.new(bval.outputs["Value"], hole.inputs[0]); L.new(thr.outputs[0], hole.inputs[1])
    thr2 = N.new("ShaderNodeMath"); thr2.operation = "ADD"; thr2.inputs[1].default_value = -0.07
    L.new(thr.outputs[0], thr2.inputs[0])
    char = N.new("ShaderNodeMath"); char.operation = "GREATER_THAN"
    L.new(bval.outputs["Value"], char.inputs[0]); L.new(thr2.outputs["Value"], char.inputs[1])
    char_emi = N.new("ShaderNodeEmission")
    char_emi.inputs["Color"].default_value = B.hex_lin(CHAR_HEX)
    mix1 = N.new("ShaderNodeMixShader")
    L.new(char.outputs["Value"], mix1.inputs["Fac"])
    L.new(src, mix1.inputs[1]); L.new(char_emi.outputs["Emission"], mix1.inputs[2])
    tr = N.new("ShaderNodeBsdfTransparent")
    mix2 = N.new("ShaderNodeMixShader")
    L.new(hole.outputs["Value"], mix2.inputs["Fac"])
    L.new(mix1.outputs["Shader"], mix2.inputs[1]); L.new(tr.outputs["BSDF"], mix2.inputs[2])
    L.new(mix2.outputs["Shader"], out.inputs["Surface"])
    m["burn_node"] = thr.name
    return m


def _set_burn(m, t: float) -> None:
    m.node_tree.nodes["BurnT"].outputs[0].default_value = float(t)


def _flame_tongues(ph: float, length: float, burn: float) -> list:
    """烧着的边上的几条火舌：(根, 长, 粗, 相位)。根贴在纸面上、跟着烧的前沿往上走（偏 +x 一侧先烧），
    火舌朝世界的上方（姿态里再转回来）。"""
    out = []
    front = max(0.04, 0.95 - burn)  # 烧的前沿离下口多高（占灯高的比例）
    for k, (th_deg, zf, lf) in enumerate(((-30, 0.6, 1.0), (0, 1.0, 0.85), (28, 0.8, 1.0), (55, 1.2, 0.75), (-58, 0.3, 0.6),
                                         (80, 1.0, 0.7), (-8, 0.2, 0.55), (42, 0.35, 0.65))):
        th = math.radians(th_deg)
        z = -SL_H / 2 + min(0.9, front * zf) * SL_H
        r = (SL_R_BOT + (SL_R_TOP - SL_R_BOT) * min(1.0, front * zf * 1.4)) * 1.04
        out.append((Vector((r * math.cos(th), r * math.sin(th), z)), lf * length, 0.05 + 0.015 * (k % 2), 0.4 * k + ph))
    return out


def build_sky_lantern():
    paper = K.flame_material("SkyLanternPaper", PAPER_BANDS, emissive_hex=PAPER_BANDS[0][1][0], seed=81.0, noise_amt=0.10,
                             edge=0.3, rim=0.45, rim_power=1.6)
    paper = _burn_material(paper, 81.5)
    fire = K.flame_material("SkyLanternFire", FIRE_BANDS, seed=83.0, noise_amt=0.08, rim=0.8, rim_power=1.3)
    seam = B.flat_material("SkyLanternSeam", SEAM_HEX)
    hoop = K.toon("SkyLanternHoop", ramp=[A["zheshi"], S.shade_ramp(A["zheshi"])[2], I["nong"]], edge=0.3, seed=84.0)
    root = B.empty("SkyLanternRoot")
    tilt = B.empty("SkyLanternTilt", root)  # 在画面里歪（绕视线转）
    body = B.empty("SkyLanternBody", tilt)  # 纸袋塌下去（缩 z）
    prof = _profile()
    shell = B.mesh_object("SkyLanternShell", B.lathe(prof, 48, radial=lambda th, z: 1 + 0.022 * abs(math.sin(SL_PANELS / 2 * th)),
                                                      cap_top=True, cap_bottom=False), paper, "outer", body, sharp_deg=0)
    fire_at = Vector(SL_FIRE_AT)
    B.set_point_attr(shell, "fade", [min(1.0, (v.co - fire_at).length / SL_GLOW_R) for v in shell.data.vertices])
    # 接缝：六道细纸条，贴着纸面从下口到顶
    def seams(bm):
        for k in range(SL_PANELS):
            th = 2 * math.pi * k / SL_PANELS
            pts = [Vector(((r * 1.012) * math.cos(th), (r * 1.012) * math.sin(th), z)) for r, z in prof[:-2]]
            K.tube_build(pts, lambda t: 0.0055, 4)(bm)
    B.mesh_object("SkyLanternSeams", seams, seam, "none", body, sharp_deg=0)
    # 下口一圈竹篾
    zb = -SL_H / 2
    ring = [Vector((SL_R_BOT * 1.01 * math.cos(a), SL_R_BOT * 1.01 * math.sin(a), zb + 0.008)) for a in [2 * math.pi * k / 40 for k in range(41)]]
    B.mesh_object("SkyLanternHoop", K.tube_build(ring, lambda t: 0.008, 6), hoop, "thin", body, sharp_deg=0)
    tongues = []
    for k in range(8):
        ob = B.mesh_object(f"SkyLanternFlame{k}", K.tube_build([Vector((0, 0, 0)), Vector((0, 0, 0.01))], lambda t: 0.001, 6), fire,
                           "thin", tilt, sharp_deg=0)
        tongues.append(ob)
    parts = {"root": root, "tilt": tilt, "body": body, "paper": paper, "tongues": tongues}
    sockets = {"glow": B.empty("SkyLanternGlow", tilt, loc=(0, 0, -SL_H * 0.25)), "feet": B.empty("SkyLanternFeet", root)}
    pose_sky_lantern(parts, "float", 0, 4)
    return root, parts, sockets


def pose_sky_lantern(parts, anim, frame, n):
    deg, burn, flame_k, squash = SL_POSES[anim][frame]
    _, _, fwd = B.camera_basis()
    parts["tilt"].rotation_mode = "QUATERNION"
    parts["tilt"].rotation_quaternion = Matrix.Rotation(math.radians(deg), 3, fwd).to_quaternion()
    parts["body"].scale = (1.0 + 0.4 * (1 - squash), 1.0 + 0.4 * (1 - squash), squash)
    parts["body"].location = (0, 0, -SL_H / 2 * (1 - squash))
    _set_burn(parts["paper"], burn)
    # 火舌：根在纸面上（随灯歪），方向朝世界的上方（在 tilt 的局部坐标里把世界 +Z 转回来）
    rot_inv = Matrix.Rotation(math.radians(-deg), 3, fwd)
    up_local = rot_inv @ Vector((0, 0, 1))
    ph = 1.3 * frame
    for ob, (base, L, r0, sph) in zip(parts["tongues"], _flame_tongues(ph, 0.26, burn)):
        if flame_k <= 0:
            K.replace_mesh(ob, K.tube_build([Vector((0, 0, 0)), Vector((0, 0, 0.001))], lambda t: 0.0, 3))
            continue
        b = Vector((base.x, base.y, base.z * squash - SL_H / 2 * (1 - squash)))
        b = Vector((b.x * (1.0 + 0.4 * (1 - squash)), b.y * (1.0 + 0.4 * (1 - squash)), b.z))
        side = up_local.cross(Vector((0, -1, 0))).normalized()
        pts = []
        for i in range(9):
            t = i / 8
            p = b + up_local * (L * flame_k * t) + side * (0.045 * math.sin(2 * math.pi * t * 1.3 - sph) * t
                                                            + 0.05 * t ** 3 * math.cos(sph))  # S 形摆、尖上回勾
            pts.append(p)
        fades: list = []
        K.replace_mesh(ob, K.tube_build(pts, lambda t, r0=r0: r0 * flame_k ** 0.5 * (1 - t) ** 0.9 * (1 + 0.3 * math.sin(math.pi * t)), 8,
                                        fades=fades))
        B.set_point_attr(ob, "fade", fades)
    bpy.context.view_layer.update()


# 名字: (建模, 摆姿态, 帧尺寸（1 倍）, 锚点, 调色板外的颜色, {动画: 帧数})
BUILDERS = {"sky_lantern": (build_sky_lantern, pose_sky_lantern, LANTERN_FRAME_1X, LANTERN_ANCHOR, PALETTE_EXTRA,
                            {a: len(v) for a, v in SL_POSES.items()})}


# ================================================================ 镇妖塔 / 玲珑塔
# 七层密檐小塔（方塔，转 45° 让一个角朝镜头）：石基座，第一层墙身高、开拱门，上面六层矮墙身、檐一层层收，
# 每层四个翼角挂铜铃；顶上攒尖顶和塔刹（仰莲、五重相轮、宝珠）。
# 镇妖塔（土）：墙身淡赭、瓦顶重墨、斗拱朱砂、铃和塔刹藤黄。BALANCE 6.3：半径 45 时宽约 40、高约 70 世界单位。
# 玲珑塔（进化）：整座放大 1.38 倍（宽约 56、高约 96），墙身玉白、瓦顶石绿、描金，每层拱门里透出金光（进发光层）。
# 只渲 idle 两帧（铃铛往两边摆）；落下、收走的帧由 post/weapon_textures_ea.py 用这两帧做 2D 的拉伸、位移、消散。
TOWER_FRAME_1X = {"tower": 224, "tower_gold": 288}  # 2 倍 448²、576²：上面留出落下时拉长的地方
TOWER_ANCHOR = (0.5, 0.88)  # 锚点 = 塔基座中心（落地点）
TOWER_K = {"tower": 1.0, "tower_gold": 1.38}
TW_TIERS = 7
TW_H0, TW_OV0 = 0.42, 0.14  # 第一层墙身半宽、檐挑出（米）：檐挑得少，俯视 30° 时下面的墙身才露得出来
TW_FIT = 0.93  # 整座再缩一点，镇妖塔在屏幕上约宽 40、高 70 世界单位
TW_GOLD = "#FFE7A8"  # 玲珑塔拱门里的金光（发光）
TW_LAMP = "#FFB45A"  # 镇妖塔拱门里的灯光（发光，夜里看得见塔）
TW_POSES = {"idle": [14.0, -14.0]}  # 每帧铃铛的摆角（度）


def _tower_mats(gold: bool) -> dict:
    Q = S.shade_ramp
    if gold:
        wall = K.toon("TowerGoldWall", ramp=[S.PAPER, S.mix(S.PAPER, A["shilv"], 0.22), W["shilv"]], edge=0.35, seed=91.0)
        tile = K.toon("TowerGoldTile", ramp=Q(A["shilv"]), wash=0.3, edge=0.25, seed=92.0)
        fascia = B.flat_material("TowerGoldFascia", A["tenghuang"])
        bracket = K.toon("TowerGoldBracket", A["tenghuang"], edge=0.25, seed=93.0)
        door = B.emissive_material("TowerGoldDoor", TW_GOLD, 1.0)
    else:
        wall = K.toon("TowerWall", W["zheshi"], edge=0.35, seed=91.0)
        tile = K.toon("TowerTile", ramp=[I["zhong"], I["nong"], I["jiao"]], wash=0.3, edge=0.25, seed=92.0)
        fascia = B.flat_material("TowerFascia", I["jiao"])
        bracket = K.toon("TowerBracket", A["zhusha"], edge=0.25, seed=93.0)
        door = B.emissive_material("TowerDoor", TW_LAMP, 1.0)
    return {"wall": wall, "tile": tile, "fascia": fascia, "bracket": bracket, "door": door,
            "stone": K.toon("TowerStone", ramp=[I["qing"], I["dan"], I["zhong"]], wash=0.4, wash_scale=3.0, edge=0.5, seed=94.0),
            "gold": K.toon("TowerFinial", ramp=[W["tenghuang"], A["tenghuang"], A["zheshi"]], edge=0.25, seed=95.0),
            "ridge": K.toon("TowerRidge", ramp=[I["dan"], I["zhong"], I["nong"]], wash=0.2, edge=0.2, seed=96.0)}


def _box(hx, hy, h, z0=0.0):
    def build(bm):
        import bmesh as _bm
        r = _bm.ops.create_cube(bm, size=1.0)
        _bm.ops.scale(bm, vec=(2 * hx, 2 * hy, h), verts=r["verts"])
        _bm.ops.translate(bm, vec=(0, 0, z0 + h / 2), verts=r["verts"])
    return build


def _arch_build(w, h, depth=0.006):
    """拱门（xz 平面里的圆拱，沿 -y 薄薄一片），底边中点为原点。"""
    def build(bm):
        n = 10
        pts = [(-w / 2, 0.0), (w / 2, 0.0)]
        for i in range(n + 1):
            a = math.pi * i / n
            pts.append((w / 2 * math.cos(a), h - w / 2 + w / 2 * math.sin(a)))
        f = [bm.verts.new((x, -depth, z)) for x, z in pts]
        bm.faces.new(f)
    return build


def build_tower(gold: bool = False):
    import qingqiu_props as Q  # noqa: PLC0415  借四坡翘角的檐（_hip_roof_build）

    m = _tower_mats(gold)
    k = TOWER_K["tower_gold" if gold else "tower"]
    pre = "TowerGold" if gold else "Tower"
    root = B.empty(f"{pre}Root")
    turn = B.empty(f"{pre}Turn", root, rot=(0, 0, math.radians(45)))  # 一个角朝镜头
    body = B.empty(f"{pre}Body", turn)
    body.scale = (k * TW_FIT,) * 3
    obj = B.mesh_object
    # 基座：两级石台
    obj(f"{pre}Plinth0", _box(0.66, 0.66, 0.08), m["stone"], "outer", body, smooth=False)
    obj(f"{pre}Plinth1", _box(0.58, 0.58, 0.07, 0.08), m["stone"], "inner", body, smooth=False)
    z = 0.15
    bells = []
    for t in range(TW_TIERS):
        h = TW_H0 * (1 - 0.08 * t)
        bh = 0.5 if t == 0 else 0.26 * (1 - 0.04 * t)
        ov = TW_OV0 * (1 - 0.04 * t)
        obj(f"{pre}Wall{t}", _box(h, h, bh, z), m["wall"], "outer", body, smooth=False)
        # 每面一道拱门（第一层大）
        aw, ah = (0.24, 0.34) if t == 0 else (0.1, 0.14 * (1 - 0.04 * t))
        for face in range(4):
            rot = math.radians(90 * face)
            n = Vector((math.sin(rot), -math.cos(rot), 0))
            loc = n * (h + 0.002) + Vector((0, 0, z + (0.02 if t == 0 else 0.03)))
            obj(f"{pre}Door{t}_{face}", _arch_build(aw, ah), m["door"], "none", body, loc=loc, rot=(0, 0, rot), smooth=False)
        # 斗拱：檐下一圈朱砂（玲珑塔描金）
        obj(f"{pre}Bracket{t}", _box(h + 0.035, h + 0.035, 0.035, z + bh - 0.01), m["bracket"], "inner", body, smooth=False)
        z_eave = z + bh + 0.02
        rise = 0.06 * (1 - 0.04 * t)
        top = t == TW_TIERS - 1
        s_top = 0.93 if top else 0.62
        build = Q._hip_roof_build(h + ov, h + ov, z_eave, rise if not top else 0.26, 0.06 * (1 - 0.03 * t), nf=12, ns=12,
                                  nlev=5, fascia=0.025, flare=0.1, s_top=s_top)
        roof = obj(f"{pre}Eave{t}", build, [m["tile"], m["fascia"]], "outer" if t == 0 else "inner", body, smooth=False)
        Q._mark_tiles(roof, *build.grid, build.cols)
        # 翼角的铜铃：挂点在角尖下面，铃身是个小钟
        cz = z_eave + 0.06 * (1 - 0.03 * t) - 0.012
        for cx, cy in ((1, 1), (1, -1), (-1, -1), (-1, 1)):
            r = (h + ov) * (1 + 0.08) * 0.98
            piv = B.empty(f"{pre}BellPivot{t}_{cx}{cy}", body, loc=(cx * r, cy * r, cz))
            obj(f"{pre}Bell{t}_{cx}{cy}", B.lathe([(0.0, -0.075), (0.026, -0.07), (0.022, -0.045), (0.012, -0.02), (0.0, -0.012)],
                                                   10), m["gold"], "thin", piv, sharp_deg=0)
            obj(f"{pre}BellCord{t}_{cx}{cy}", B.cylinder(0.003, 0.003, 0.02, 4), m["fascia"], "none", piv, loc=(0, 0, -0.01))
            bells.append((piv, cx * cy))
        z = z_eave + (rise if not top else 0.26) * s_top ** 1.6 - 0.01
    # 塔刹：仰莲、五重相轮、宝珠、刹尖
    zf = z - 0.02
    obj(f"{pre}Lotus", B.lathe([(0.0, 0.0), (0.09, 0.0), (0.12, 0.05), (0.07, 0.07), (0.0, 0.07)], 16), m["gold"], "inner", body,
        loc=(0, 0, zf), sharp_deg=0)
    zf += 0.07
    obj(f"{pre}Mast", B.cylinder(0.018, 0.012, 0.42, 8), m["gold"], "thin", body, loc=(0, 0, zf + 0.21))
    for j in range(5):
        rr = 0.075 * (1 - 0.1 * j)
        obj(f"{pre}Ring{j}", B.cylinder(rr, rr, 0.016, 16), m["gold"], "thin", body, loc=(0, 0, zf + 0.04 + 0.05 * j))
    obj(f"{pre}Pearl", B.uv_sphere(0.05, 14, 8), m["gold"], "inner", body, loc=(0, 0, zf + 0.34))
    parts = {"root": root, "body": body, "bells": bells}
    sockets = {"top": B.empty(f"{pre}Top", body, loc=(0, 0, zf + 0.42)), "feet": B.empty(f"{pre}Feet", root)}
    pose_tower(parts, "idle", 0, 2)
    return root, parts, sockets


def pose_tower(parts, anim, frame, n):
    deg = TW_POSES[anim][frame]
    for piv, sgn in parts["bells"]:
        piv.rotation_euler = (math.radians(deg * 0.35 * sgn), math.radians(deg), 0)
    bpy.context.view_layer.update()


def build_tower_gold():
    return build_tower(gold=True)


BUILDERS["tower"] = (build_tower, pose_tower, TOWER_FRAME_1X["tower"], TOWER_ANCHOR, [TW_LAMP], {"idle": 2})
BUILDERS["tower_gold"] = (build_tower_gold, pose_tower, TOWER_FRAME_1X["tower_gold"], TOWER_ANCHOR, [TW_GOLD], {"idle": 2})
