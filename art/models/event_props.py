"""奇遇道具：古灯、血祭坛（道具帧 FRAME["prop"]，锚点 PROP_ANCHOR，只画 S 向一帧）。

古灯 ancient_lamp：风化的石座 + 青铜灯柱（赭石铜色，朝上的面泛淡彩石绿的铜锈）+ 铜灯笼（四根立柱围着发光的火窗）
  + 宝顶，约 1.6 米。火窗是发光材质（FLAME_LIGHT）。挂点 flame（火窗中心）、feet。
血祭坛 blood_altar：两层石台，侧面刻回纹（边标记），台面一只石盆，盆里是暗红的发光液面（朱砂色自发光）；
  台面和侧面泼着朱砂血迹、往下淌。挂点 glow（盆心）、feet。
货郎担 merchant：木货箱 + 竹筐 + 横搭的扁担，竹竿挑一盏小红纸灯笼（发光），“货”字布幌；不画人。挂点 flame（灯芯）、feet。
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import bmesh
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
from stone_lantern import _box, moss_material, _prism  # noqa: E402


def _mark_horizontal(ob, keep=0.9, seed=0):
    me = ob.data
    rng = np.random.default_rng(seed)
    attr = me.attributes.get("freestyle_edge") or me.attributes.new("freestyle_edge", "BOOLEAN", "EDGE")
    vals = []
    for e in me.edges:
        v0, v1 = (me.vertices[i].co for i in e.vertices)
        d = v1 - v0
        vals.append(abs(d.z) < 0.2 * d.length and rng.random() < keep)
    attr.data.foreach_set("value", vals)


def build_ancient_lamp():
    I, A = S.INK, S.ACCENT
    stone = K.toon("LampStone", ramp=[I["qing"], I["dan"], I["zhong"]], wash=0.4, edge=0.5, seed=81.0)
    bronze = K.toon("LampBronze", A["zheshi"], wash=0.3, edge=0.5, seed=82.0)
    patina = moss_material("LampPatina", coverage=0.55, up=0.2, seed=8.0)
    flame = B.emissive_material("LampFlame", S.FLAME_LIGHT, 1.0)
    inner = B.flat_material("LampInner", I["nong"])
    root = B.empty("AncientLamp")
    obj = B.mesh_object
    obj("LampBase", _prism(0.30, 0.28, 0.0, 0.10, seg=8, rot=math.radians(22.5)), stone, "outer", root, smooth=False)
    obj("LampBase2", _prism(0.20, 0.17, 0.10, 0.22, seg=8, rot=math.radians(22.5)), stone, "outer", root, smooth=False)
    for nm, build in (("LampPillar", B.lathe([(0.075, 0.22), (0.06, 0.40), (0.055, 0.95), (0.07, 1.00), (0.05, 1.04)], 12)),
                      ("LampCup", B.lathe([(0.05, 1.04), (0.16, 1.10), (0.18, 1.13), (0.17, 1.15)], 12))):
        obj(nm, build, bronze, "outer", root, sharp_deg=50)
        obj(nm + "Patina", build, patina, "none", root, scale=(1.03, 1.03, 1.0), sharp_deg=50, contour=True)
    # 灯笼：火窗（发光方块）+ 四根铜立柱 + 宝顶
    obj("LampFlameBox", K.ellipsoid((0.10, 0.10, 0.12), 12, 8), flame, "none", root, loc=(0, 0, 1.27))
    obj("LampFloor", B.cylinder(0.15, 0.15, 0.03, 8), inner, "inner", root, loc=(0, 0, 1.16))
    for i in range(4):
        a = math.radians(45 + 90 * i)
        K.limb(f"LampPost{i}", (0.14 * math.cos(a), 0.14 * math.sin(a), 1.15), (0.13 * math.cos(a), 0.13 * math.sin(a), 1.42),
               0.022, 0.02, bronze, "inner", root, segs=6)
    roof = B.lathe([(0.25, 1.41), (0.24, 1.44), (0.14, 1.50), (0.06, 1.55), (0.03, 1.57)], 8,
                   radial=lambda th, z: 1 + 0.10 * abs(math.cos(2 * th)) ** 4)
    obj("LampRoof", roof, bronze, "outer", root, smooth=False)
    obj("LampRoofPatina", roof, patina, "none", root, smooth=False, scale=(1.02, 1.02, 1.01), contour=True)
    obj("LampFinial", K.ellipsoid((0.04, 0.04, 0.05), 10, 6), bronze, "outer", root, loc=(0, 0, 1.61))
    sockets = {"flame": B.empty("LampSocketFlame", root, loc=(0, 0, 1.27)), "feet": B.empty("LampFeet", root)}
    bpy.context.view_layer.update()
    return root, {"root": root}, sockets


def _splat_build(r, seed, n=12):
    """一摊血迹：边缘参差的扁圆片（贴在面上）。"""
    rng = np.random.default_rng(seed)
    radii = r * rng.uniform(0.55, 1.15, n)

    def build(bm):
        c = bm.verts.new((0, 0, 0))
        ring = [bm.verts.new((radii[i] * math.cos(2 * math.pi * i / n), radii[i] * math.sin(2 * math.pi * i / n), 0))
                for i in range(n)]
        for i in range(n):
            bm.faces.new((c, ring[i], ring[(i + 1) % n]))
    return build


def build_blood_altar():
    I, A = S.INK, S.ACCENT
    stone = K.toon("AltarStone", ramp=[I["dan"], I["zhong"], I["nong"]], wash=0.4, edge=0.5, seed=91.0)
    blood = K.toon("AltarBlood", A["zhusha"], wash=0.2, edge=0.2, seed=92.0)
    pool = B.emissive_material("AltarGlow", A["zhusha"], 1.0)
    root = B.empty("BloodAltar")
    obj = B.mesh_object
    lower = obj("AltarLower", _prism(0.62, 0.58, 0.0, 0.16, seg=4, rot=math.radians(45)), stone, "outer", root,
                smooth=False, scale=(1.0, 0.72, 1.0))
    upper = obj("AltarUpper", _prism(0.50, 0.46, 0.16, 0.44, seg=4, rot=math.radians(45)), stone, "outer", root,
                smooth=False, scale=(1.0, 0.70, 1.0))
    # 回纹：上层侧面加几道水平细分再标边（像刻出来的纹带）
    for ob in (lower, upper):
        bm = bmesh.new()
        bm.from_mesh(ob.data)
        side = [e for e in bm.edges if abs(e.verts[0].co.z - e.verts[1].co.z) > 0.05]
        bmesh.ops.subdivide_edges(bm, edges=side, cuts=3, use_grid_fill=True)
        bm.to_mesh(ob.data)
        bm.free()
        _mark_horizontal(ob, keep=0.4, seed=3)
    obj("AltarRim", B.lathe([(0.0, 0.44), (0.30, 0.44), (0.32, 0.50), (0.28, 0.52), (0.24, 0.48)], 16, cap_top=False),
        stone, "outer", root, sharp_deg=50, scale=(1.0, 0.8, 1.0))
    obj("AltarPool", B.cylinder(0.25, 0.25, 0.01, 16), pool, "none", root, loc=(0, 0, 0.485), scale=(1.0, 0.8, 1.0))
    # 血迹：台面、侧面、地上几摊，正面有往下淌的痕
    for i, (pos, r, rot) in enumerate((((0.34, -0.10, 0.443), 0.10, (0, 0, 0)), ((-0.30, 0.12, 0.443), 0.08, (0, 0, 0)),
                                       ((0.20, -0.33, 0.30), 0.09, (math.radians(90), 0, 0)),
                                       ((-0.25, -0.44, 0.10), 0.07, (math.radians(90), 0, 0)),
                                       ((0.45, -0.55, 0.005), 0.12, (0, 0, 0)))):
        obj(f"AltarStain{i}", _splat_build(r, 10 + i), blood, "none", root, loc=pos, rot=rot, smooth=False)
    for i, x in enumerate((0.12, -0.05)):
        drip = K.curve_points((x, -0.33, 0.44), (x + 0.01, -0.335, 0.20 - 0.06 * i), n=5)
        obj(f"AltarDrip{i}", K.tube_build(drip, lambda t: 0.018 * (1 - 0.5 * t) + 0.004, 6, flat=0.4), blood, "none",
            root)
    sockets = {"glow": B.empty("AltarSocketGlow", root, loc=(0, 0, 0.49)), "feet": B.empty("AltarFeet", root)}
    bpy.context.view_layer.update()
    return root, {"root": root}, sockets


# ================================================================ 货郎担
def _glyph_mesh(name: str, text: str, size: float):
    """用完整版马善政字体把字转成扁平网格（XY 平面、居中、朝 +Z）。字体由 post/ui_fonts.py 下载缓存；
    拿不到字体时返回 None（调用方画几笔墨代替）。"""
    try:
        sys.path.insert(0, str(ART / "post"))
        from ui_fonts import font_file
        path = font_file("brush")
    except Exception as e:  # noqa: BLE001 - 没网、没缓存都只是少一个字
        print(f"[merchant] 没有拿到马善政字体（{e}），旗上画墨点代替")
        return None
    cu = bpy.data.curves.new(name + "Glyph", "FONT")
    cu.body = text
    cu.font = bpy.data.fonts.load(str(path), check_existing=True)
    cu.size = size
    cu.offset = size * 0.035  # 笔画加粗一点，小尺寸下不至于发虚
    cu.align_x, cu.align_y = "CENTER", "CENTER"
    tmp = bpy.data.objects.new(name + "Tmp", cu)
    bpy.context.scene.collection.objects.link(tmp)
    bpy.context.view_layer.update()
    me = bpy.data.meshes.new_from_object(tmp.evaluated_get(bpy.context.evaluated_depsgraph_get()))
    bpy.data.objects.remove(tmp)
    bpy.data.curves.remove(cu)
    return me


def _paper_lantern(prefix, parent, center, r, h, mats):
    """小红纸灯笼（货郎担上挂的那盏）：朱砂纸壳开窗、墨色上下盖、发光芯、小穗。返回灯芯挂点。"""
    obj = B.mesh_object
    c = Vector(center)
    obj(f"{prefix}Shell", B.lathe([(0.0, -h), (0.6 * r, -0.92 * h), (0.9 * r, -0.62 * h), (r, -0.2 * h), (r, 0.2 * h),
                                  (0.9 * r, 0.62 * h), (0.6 * r, 0.92 * h), (0.0, h)], 20,
                                 radial=lambda th, z: 1 + 0.04 * abs(math.sin(4 * th))),
        mats["window"], "outer", parent, loc=c, sharp_deg=0)
    obj(f"{prefix}Core", B.uv_sphere(1.0, 14, 8, scale=(0.74 * r, 0.74 * r, 0.76 * h)), mats["core"], "none", parent, loc=c)
    obj(f"{prefix}CapTop", B.cylinder(0.55 * r, 0.48 * r, 0.026, 12), mats["cap"], "inner", parent,
        loc=c + Vector((0, 0, h + 0.008)))
    obj(f"{prefix}CapBot", B.cylinder(0.48 * r, 0.55 * r, 0.022, 12), mats["cap"], "inner", parent,
        loc=c + Vector((0, 0, -h - 0.006)))
    obj(f"{prefix}Tassel", B.cylinder(0.006, 0.020, 0.08, 8), mats["tassel"], "none", parent,
        loc=c + Vector((0, 0, -h - 0.06)))
    return B.empty(f"{prefix}Socket", parent, loc=c)


def build_merchant():
    """货郎担（不画人）：左边一只带抽屉的木货箱，右边一只竹筐（装着布包袱、插着拨浪鼓），一根扁担横搭在两件上，
    绳子松垂；货箱后角插一根竹竿挑着小红纸灯笼（发光，挂点 flame），竹筐后插“货”字布幌。约 1.4 米宽、1.35 米高。"""
    I, A, W = S.INK, S.ACCENT, S.WASH
    wood = K.toon("MerchWood", A["zheshi"], wash=0.3, edge=0.45, seed=101.0)
    wood_dark = K.toon("MerchWoodDark", ramp=[S.shade_ramp(A["zheshi"])[1], S.shade_ramp(A["zheshi"])[2], I["nong"]],
                       wash=0.25, edge=0.4, seed=102.0)
    bamboo = K.toon("MerchBamboo", W["zheshi"], wash=0.25, edge=0.4, seed=103.0)
    pole = K.toon("MerchPole", A["zheshi"], edge=0.2, seed=104.0)
    blue = K.toon("MerchClothBlue", W["huaqing"], edge=0.3, seed=105.0)
    red = K.toon("MerchClothRed", W["zhusha"], edge=0.3, seed=106.0)
    flag = K.toon("MerchFlag", ramp=[S.PAPER, S.PAPER_SHADOW, I["qing"]], edge=0.2, seed=107.0)
    drum = K.toon("MerchDrum", A["zhusha"], edge=0.25, seed=108.0)
    rope = B.flat_material("MerchRope", I["nong"])
    char_ink = B.flat_material("MerchCharInk", I["jiao"])
    shell = K.toon("MerchLanternShell", A["zhusha"], edge=0.25, seed=109.0)
    lamp = {"window": B.window_material("MerchLanternWindow", shell, open_facing=0.25),
            "core": B.emissive_material("MerchLanternCore", S.FLAME_LIGHT, 1.0),
            "cap": K.toon("MerchCap", I["jiao"], seed=110.0), "tassel": K.toon("MerchTassel", A["zhusha"], seed=111.0)}
    root = B.empty("Merchant")
    obj = B.mesh_object

    # 货箱：箱体 + 顶板 + 三层抽屉（抽屉面略凸出、墨点拉手）
    cx, cy, cw, cd, ch = -0.40, 0.02, 0.36, 0.28, 0.48
    obj("MerchChest", _box(cw, ch, cd), wood, "outer", root, loc=(cx, cy, ch / 2), smooth=False)
    obj("MerchChestTop", _box(cw + 0.04, 0.03, cd + 0.03), wood_dark, "outer", root, loc=(cx, cy, ch + 0.015), smooth=False)
    obj("MerchChestFoot", _box(cw + 0.02, 0.035, cd + 0.02), wood_dark, "outer", root, loc=(cx, cy, 0.0175), smooth=False)
    for k, z in enumerate((0.115, 0.245, 0.375)):
        obj(f"MerchDrawer{k}", _box(cw - 0.06, 0.105, 0.012), wood_dark, "inner", root,
            loc=(cx, cy - cd / 2 - 0.004, z), smooth=False)
        obj(f"MerchKnob{k}", B.uv_sphere(0.013, 8, 6), rope, "none", root, loc=(cx, cy - cd / 2 - 0.013, z))
    # 箱顶上一个小包袱
    obj("MerchBundleTop", K.ellipsoid((0.10, 0.08, 0.055), 14, 8), red, "inner", root, loc=(cx + 0.03, cy - 0.01, ch + 0.08))
    obj("MerchBundleTopKnot", K.ellipsoid((0.030, 0.022, 0.028), 8, 6), red, "inner", root,
        loc=(cx + 0.03, cy - 0.04, ch + 0.135))

    # 竹筐：编织的横纹（边标记）+ 筐沿；里面两个包袱、插一只拨浪鼓
    bx, by = 0.42, 0.0
    prof = [(0.13, 0.0)] + [(0.13 + 0.06 * (z / 0.33) ** 0.8, z) for z in (0.03, 0.07, 0.11, 0.15, 0.19, 0.23, 0.27, 0.31)]
    basket = obj("MerchBasket", B.lathe(prof, 20, cap_top=False), bamboo, "outer", root, loc=(bx, by, 0.0), sharp_deg=50)
    _mark_horizontal(basket, keep=0.85, seed=5)
    obj("MerchBasketRim", B.lathe([(0.186, 0.300), (0.204, 0.312), (0.204, 0.332), (0.186, 0.340)], 20, cap_top=False,
                                  cap_bottom=False), bamboo, "inner", root, loc=(bx, by, 0.0), sharp_deg=50)
    obj("MerchBundleA", K.ellipsoid((0.12, 0.10, 0.085), 14, 8), blue, "inner", root, loc=(bx - 0.04, by + 0.03, 0.36))
    obj("MerchBundleAKnot", K.ellipsoid((0.035, 0.026, 0.03), 8, 6), blue, "inner", root, loc=(bx - 0.04, by - 0.01, 0.44))
    obj("MerchBundleB", K.ellipsoid((0.085, 0.075, 0.06), 12, 8), red, "inner", root, loc=(bx + 0.09, by - 0.06, 0.35))
    dx_, dy_, dz_ = bx - 0.19, by - 0.10, 0.80  # 拨浪鼓（货郎的招牌）：鼓面朝前
    K.limb("MerchDrumStick", (bx - 0.13, by - 0.06, 0.30), (dx_, dy_, dz_ - 0.06), 0.010, 0.008, pole, "thin", root, segs=6)
    obj("MerchDrum", B.cylinder(0.066, 0.066, 0.040, 18), drum, "inner", root, loc=(dx_, dy_, dz_),
        rot=(math.radians(90), 0, 0))
    obj("MerchDrumFace", B.cylinder(0.050, 0.050, 0.004, 18), flag, "none", root, loc=(dx_, dy_ - 0.021, dz_),
        rot=(math.radians(90), 0, 0))
    for sx in (-1, 1):  # 鼓两边的弹丸
        K.limb(f"MerchDrumString{sx:+d}", (dx_ + 0.064 * sx, dy_, dz_), (dx_ + 0.095 * sx, dy_, dz_ - 0.035), 0.004, 0.004,
               rope, "none", root, segs=4)
        obj(f"MerchDrumBead{sx:+d}", B.uv_sphere(0.015, 8, 6), rope, "none", root, loc=(dx_ + 0.098 * sx, dy_, dz_ - 0.045))

    # 扁担：横搭在箱顶和筐沿上，略弯；两头各两根松垂的担绳
    p0, p1 = Vector((-0.70, 0.06, 0.545)), Vector((0.72, 0.04, 0.365))
    obj("MerchPole", B.sweep(K.curve_points(p0, p1, bend=Vector((0, 0, 0.025)), n=10), 0.085, 0.040), pole, "thin", root)
    for k, (top, ends, bend) in enumerate(((Vector((-0.61, 0.06, 0.535)), ((-0.595, -0.13, 0.06), (-0.595, 0.17, 0.06)), -0.04),
                                           (Vector((0.65, 0.04, 0.37)), ((0.60, -0.13, 0.05), (0.61, 0.13, 0.05)), 0.04))):
        for j, e in enumerate(ends):
            pts = K.curve_points(top, e, bend=Vector((bend, 0, 0)), n=8)
            obj(f"MerchRope{k}{j}", K.tube_build(pts, lambda t: 0.0075, 6), rope, "none", root)

    # 灯竿：货箱后角插一根竹竿，竿头弯向前，挑着小红纸灯笼
    base, top, tip = Vector((-0.55, 0.13, 0.48)), Vector((-0.55, 0.13, 1.28)), Vector((-0.37, 0.06, 1.34))
    K.limb("MerchLampPole", base, top, 0.014, 0.011, bamboo, "thin", root, segs=8)
    arm = K.curve_points(top, tip, bend=Vector((0, 0, 0.05)), n=6)
    obj("MerchLampArm", K.tube_build(arm, lambda t: 0.010 - 0.003 * t, 6), bamboo, "thin", root)
    lr, lh = 0.074, 0.085
    lc = tip - Vector((0, 0, 0.075 + lh))
    K.limb("MerchLampCord", tip, lc + Vector((0, 0, lh)), 0.004, 0.004, rope, "none", root, segs=4)
    sock_flame = _paper_lantern("MerchLantern", root, lc, lr, lh, lamp)

    # 布幌：竹筐后插竿，横杆下挂一面白布，墨写“货”
    fx, fy = 0.57, 0.11
    K.limb("MerchFlagPole", (fx, fy, 0.22), (fx, fy, 1.20), 0.012, 0.010, bamboo, "thin", root, segs=8)
    K.limb("MerchFlagBar", (fx + 0.01, fy, 1.16), (fx - 0.27, fy, 1.16), 0.008, 0.008, bamboo, "thin", root, segs=6)
    x0, x1, z0, z1 = fx - 0.25, fx - 0.02, 0.78, 1.155
    rows = []
    for j in range(7):
        t = j / 6
        rows.append([Vector((x0 + (x1 - x0) * u / 4, fy - 0.004 + 0.012 * math.sin(2.4 * t + 1.3 * u / 4) * t,
                             z1 - (z1 - z0) * t - 0.012 * math.sin(math.pi * u / 4) * t)) for u in range(5)])
    obj("MerchFlagCloth", K.grid_build(rows, outward_from=Vector((fx - 0.1, fy + 1.0, 0))), flag, "inner", root)
    gm = _glyph_mesh("MerchChar", "货", 0.19)
    gc = Vector(((x0 + x1) / 2, fy - 0.014, (z0 + z1) / 2 - 0.005))
    if gm is not None:
        go = bpy.data.objects.new("MerchChar", gm)
        go.data.materials.append(char_ink)
        B.add_object(go, "none", root)
        go.location, go.rotation_euler = gc, (math.radians(90), 0, 0)
    else:
        for k, (dx, dz, w, h) in enumerate(((0, 0.04, 0.08, 0.016), (-0.01, 0.0, 0.06, 0.05), (0.0, -0.05, 0.07, 0.03))):
            obj(f"MerchCharMark{k}", _box(w, h, 0.004), char_ink, "none", root, loc=gc + Vector((dx, 0, dz)), smooth=False)

    sockets = {"flame": sock_flame, "feet": B.empty("MerchFeet", root)}
    bpy.context.view_layer.update()
    return root, {"root": root}, sockets
