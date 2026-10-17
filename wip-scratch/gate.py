def build_fox_gate():
    """石牌坊（狐祠庭院的入口，一间两柱一楼，中式，不是鸟居）：两根方石柱各夹一对方墩（夹杆石），
    小额枋、花板、大额枋三层（花板两边各刻一块浅浮雕方框），正中一块空白石匾（浓墨边框，只盖一方朱砂小印，没有字），
    柱和小额枋之间一对雀替；顶上一段四坡翘角瓦顶（浓墨瓦、瓦垄、正脊两端鸱尾）。石头风化，墩、额枋、瓦上有苔，
    左柱上系一条褪色的红布。约 3.4 米宽、3.25 米高，门洞净宽约 1.8 米、净高 2.4 米。"""
    m = _mats()
    st = m["stone"]
    moss = m["moss_thin"]
    carve = K.toon("QqGateCarve", ramp=[I["dan"], I["zhong"], I["nong"]], wash=0.3, edge=0.3, seed=362.0)
    roof_moss = moss_material("QqGateRoofMoss", coverage=0.74, up=0.55, seed=361.0)
    root = B.empty("FoxGate")
    obj = B.mesh_object
    px = 1.15
    z_lo, z_pa, z_hi, z_top = 2.40, 2.51, 2.65, 2.78  # 小额枋底、花板底、大额枋底、大额枋顶

    def mossy(name, build, loc=(0, 0, 0), k=1.02, mat=moss):
        obj(name + "Moss", build, mat, "none", root, loc=loc, smooth=False, scale=(k, k, 1.0 + (k - 1) / 2), contour=True)

    for sx in (-1, 1):
        x = px * sx
        pl = _prism(0.36, 0.33, 0.0, 0.52, seg=4, rot=math.radians(45))
        obj(f"GatePlinth{sx:+d}", pl, st, "outer", root, loc=(x, 0, 0), smooth=False)
        mossy(f"GatePlinth{sx:+d}", pl, loc=(x, 0, 0))
        cap = _prism(0.33, 0.25, 0.52, 0.60, seg=4, rot=math.radians(45))
        obj(f"GatePlinthCap{sx:+d}", cap, st, "outer", root, loc=(x, 0, 0), smooth=False)
        mossy(f"GatePlinthCap{sx:+d}", cap, loc=(x, 0, 0))
        obj(f"GatePillar{sx:+d}", _prism(0.172, 0.16, 0.0, z_top, seg=4, rot=math.radians(45)), st, "outer", root,
            loc=(x, 0, 0), smooth=False)
        # 雀替：柱子内侧、小额枋下面的一块弯石板
        xi = x - 0.115 * sx
        poly = [(xi, z_lo), (xi, z_lo - 0.27), (xi - 0.05 * sx, z_lo - 0.17), (xi - 0.15 * sx, z_lo - 0.08),
                (xi - 0.26 * sx, z_lo - 0.03), (xi - 0.36 * sx, z_lo)]
        if sx < 0:
            poly = poly[::-1]
        obj(f"GateBracket{sx:+d}", _plate_build(poly, 0.12), st, "inner", root, smooth=False)
    # 三层额枋：小额枋、花板（缩进一点，两边各一块浅浮雕方框）、大额枋
    lo = _box(2.62, z_pa - z_lo, 0.20)
    obj("GateBeamLow", lo, st, "outer", root, loc=(0, 0, (z_lo + z_pa) / 2), smooth=False)
    mossy("GateBeamLow", lo, loc=(0, 0, (z_lo + z_pa) / 2), k=1.01)
    obj("GatePanel", _box(2.30, z_hi - z_pa, 0.10), st, "inner", root, loc=(0, 0.02, (z_pa + z_hi) / 2), smooth=False)
    for sx in (-1, 1):
        obj(f"GatePanelCarve{sx:+d}", _box(0.50, 0.075, 0.01), carve, "inner", root, loc=(0.70 * sx, -0.034, (z_pa + z_hi) / 2),
            smooth=False)
    hi = _box(2.86, z_top - z_hi, 0.24)
    obj("GateBeamHigh", hi, st, "outer", root, loc=(0, 0, (z_hi + z_top) / 2), smooth=False)
    mossy("GateBeamHigh", hi, loc=(0, 0, (z_hi + z_top) / 2), k=1.01)
    # 石匾：浓墨边框、石面空白，正中一方朱砂小印（压在三层额枋前面）
    zc = (z_pa + z_hi) / 2
    obj("GatePlaqueFrame", _box(0.74, 0.28, 0.05), m["dark"], "inner", root, loc=(0, -0.125, zc), smooth=False)
    obj("GatePlaque", _box(0.62, 0.18, 0.02), m["white"], "none", root, loc=(0, -0.155, zc), smooth=False)
    obj("GatePlaqueSeal", _box(0.065, 0.065, 0.006), m["red"], "none", root, loc=(0, -0.167, zc), smooth=False)
    # 四坡翘角瓦顶：浓墨瓦、瓦垄、正脊两端鸱尾；出檐浅，露得出大额枋；瓦上零星的苔
    roof = _roof_k("Gate", root, m, 1.3, hx=1.55, hy=0.28, y_c=0.04, z_eave=2.90, rise=0.30, curl=0.13, nf=18,
                   ridge_r=0.035, fascia=0.04, flare=0.07)
    obj("GateRoofMoss", lambda bm: bm.from_mesh(roof.data), roof_moss, "none", roof.parent, loc=roof.location,
        scale=(1.004, 1.02, 1.01), smooth=False, contour=True)
    # 左柱上系的红布：一圈布带 + 垂下的两条布尾
    cz = 1.32
    obj("GateCloth", _prism(0.19, 0.188, cz - 0.04, cz + 0.04, seg=4, rot=math.radians(45)), m["bib_faded"], "inner", root,
        loc=(-px, 0, 0), smooth=False)
    for k, (dx, L, ph) in enumerate(((-0.025, 0.40, 0.0), (0.03, 0.32, 1.3))):
        pts = [Vector((-px + dx + 0.03 * math.sin(2.2 * t + ph) * t, -0.14 - 0.03 * t, cz - 0.02 - L * t))
               for t in np.linspace(0, 1, 7)]
        obj(f"GateClothTail{k}", K.strip_build(pts, 0.05, 0.006, taper=(1.0, 0.7)), m["bib_faded"], "inner", root,
            smooth=False)
    sockets = {"feet": B.empty("FoxGateFeet", root)}
    bpy.context.view_layer.update()
    return root, {"root": root}, sockets


