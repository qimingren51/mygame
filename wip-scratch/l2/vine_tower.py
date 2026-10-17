# ====================================================================== 青藤


def mat_vine(name, color=(0.10, 0.30, 0.07)):
    """青藤（tube_uv：UV.x 沿长＝米、UV.y 绕一圈）：青绿的藤皮，沿长细的纵纹，每隔一段一个深一点的节，半光。"""
    M = K.Mat(name)
    m = M.math
    uv = M.coord("UV")
    sep = M.n("ShaderNodeSeparateXYZ")
    M.l(uv, sep.inputs[0])
    mp = M.n("ShaderNodeMapping")
    M.l(uv, mp.inputs["Vector"])
    mp.inputs["Scale"].default_value = (6.0, 30.0, 1.0)
    fib = M.noise(mp.outputs["Vector"], scale=2.0, detail=6.0, rough=0.6)
    node = M.maprange(m("ABSOLUTE", m("SUBTRACT", m("FRACT", m("MULTIPLY", sep.outputs["X"], 6.0)), 0.5)), 0.5, 0.42)
    col = M.mix(M.maprange(fib.outputs["Fac"], 0.3, 0.7), (color[0] * 0.55, color[1] * 0.6, color[2] * 0.55, 1.0), (*color, 1.0))
    col = M.mix(m("MULTIPLY", node, 0.6), col, (0.04, 0.09, 0.03, 1.0))
    nrm = M.bump(m("ADD", fib.outputs["Fac"], m("MULTIPLY", node, 0.6)), strength=0.3, distance=0.002)
    bsdf = M.principled(Base_Color=col, Roughness=0.42, Coat_Weight=0.3, Coat_Roughness=0.2, Subsurface_Weight=0.1, Normal=nrm)
    return M.surface(bsdf.outputs[0])


def mat_life_stream(name, color=(0.45, 1.0, 0.55), strength=4.0, beads=40.0):
    """往回流的一缕绿光（ribbon：UV.x 沿长 0..1、UV.y 横跨）：一串光点沿长排开，中间一道细的亮线，两头淡出。只发光。"""
    M = K.Mat(name)
    m = M.math
    uv = M.coord("UV")
    sep = M.n("ShaderNodeSeparateXYZ")
    M.l(uv, sep.inputs[0])
    u, v = sep.outputs["X"], sep.outputs["Y"]
    across = m("POWER", m("SINE", m("MULTIPLY", v, math.pi)), 2.0)
    bead = M.maprange(m("SINE", m("MULTIPLY", u, beads * math.pi)), 0.55, 1.0)
    fade = m("MULTIPLY", M.maprange(u, 0.0, 0.08), M.maprange(u, 1.0, 0.75))
    a_ = m("MULTIPLY", m("MULTIPLY", across, m("ADD", 0.30, m("MULTIPLY", bead, 0.70))), fade)
    emi = M.n("ShaderNodeEmission", Color=(*color, 1.0))
    M.l(m("MULTIPLY", a_, strength), emi.inputs["Strength"])
    tr = M.n("ShaderNodeBsdfTransparent")
    add = M.n("ShaderNodeAddShader")
    M.l(tr.outputs[0], add.inputs[0])
    M.l(emi.outputs[0], add.inputs[1])
    return M.surface(add.outputs[0])


def helix_path(a, b, radius, turns, n=200, phase=0.0, taper=0.4, up=(0.0, 0.0, 1.0)):
    """从 a 到 b 的一段螺旋（绕 a→b 的轴转 turns 圈，半径往 b 收到 radius×(1-taper)）。返回点列（Vector）。"""
    from mathutils import Vector  # noqa: PLC0415

    a, b = Vector(a), Vector(b)
    ax = (b - a).normalized()
    e1 = Vector(up).cross(ax)
    e1 = e1.normalized() if e1.length > 1e-6 else Vector((1, 0, 0))
    e2 = ax.cross(e1)
    out = []
    for t in np.linspace(0, 1, n):
        r = radius * (1 - taper * t) * K.smoothstep(0.0, 0.12, t)
        ph = phase + 2 * math.pi * turns * t
        out.append(a.lerp(b, t) + e1 * (r * math.cos(ph)) + e2 * (r * math.sin(ph)))
    return out


@scene("vine", name="青藤", samples=128, grade=dict(WOOD_GRADE, exposure=1.02, bloom=0.38))
def build_vine(draft):
    """青藤：一根青藤从左下角甩出来，盘成两圈往右上伸，藤上挂着几片新叶；藤尖打着卷，一缕绿光（一串光点）
    从藤尖顺着藤绕回来。按画面位置摆（ScreenCam）。"""
    from mathutils import Vector  # noqa: PLC0415

    import card_passives as CP

    sky_gradient(lin("#05090A"), lin("#21402E"), 0.7, ground=lin("#030604"))
    rng = np.random.default_rng(97)
    S = ScreenCam(lens=40.0)
    vine_m = mat_vine("Vine")
    a, b = S(0.04, 0.96, 1.75), S(0.72, 0.34, 1.45)
    path = [Vector(p) for p in CP.bez([tuple(S(-0.06, 1.08, 1.85)), tuple(a)], n=10)[:-1]]
    path += helix_path(a, b, 0.11, 1.8, n=220, phase=0.4, taper=0.55, up=(0.0, -1.0, 0.0))
    # 藤尖：往上打一个小卷
    tip0, d0 = path[-1], (path[-1] - path[-4]).normalized()
    side = d0.cross(Vector((0, -1, 0))).normalized()
    for t in np.linspace(0.02, 1, 40):
        ang = t * 4.2
        r = 0.045 * (1 - 0.75 * t)
        path.append(tip0 + d0 * (0.05 * math.sin(ang) * (1 - 0.3 * t) + 0.01 * t) + side * (0.03 - r * math.cos(ang)))
    pts = [tuple(p) for p in path]
    make_obj("Vine", K.tube_uv(pts, 0.020, sides=20, radius_fn=lambda t: 1.0 - 0.80 * t ** 0.9), vine_m, index=1)
    # 新叶：沿藤每隔一段一片，叶面朝镜头一侧
    leaf_m = CP.mat_young_leaf("Leaf")
    cam = Vector((0, 0, 0))
    for k, i in enumerate((40, 75, 105, 140, 170, 200)):
        p = Vector(pts[i])
        tang = (Vector(pts[i + 2]) - Vector(pts[i - 2])).normalized()
        out = (p - Vector(a).lerp(Vector(b), i / len(pts))).normalized()
        d = (out * 0.8 + tang * 0.6 + Vector(rng.normal(0, 0.15, 3))).normalized()
        L = 0.085 - 0.006 * k
        ob = make_obj(f"Leaf{k}", K.leaf_build(L, L * 0.48, fold=0.18, curl=0.18, twist=rng.normal(0, 0.3)), leaf_m, index=2)
        zh = (cam - p).normalized() + Vector(rng.normal(0, 0.2, 3))
        CP.orient(ob, tuple(p + d * 0.006), d, zh)
    # 往回流的绿光：绕着藤再转一圈小螺旋，从藤尖流回藤根方向
    flow = []
    for j, p in enumerate(path[60:]):
        t = j / (len(path) - 61)
        q = Vector(p)
        tang = (Vector(path[min(60 + j + 2, len(path) - 1)]) - Vector(path[max(60 + j - 2, 0)])).normalized()
        e1 = tang.cross(Vector((0, -1, 0))).normalized()
        e2 = tang.cross(e1)
        ph = t * 2 * math.pi * 7
        flow.append(tuple(q + e1 * (0.030 * math.cos(ph)) + e2 * (0.030 * math.sin(ph))))
    make_obj("Flow", K.ribbon_uv(flow[::-1], 0.016, width_fn=lambda t: 0.6 + 0.4 * math.sin(math.pi * t)),
             mat_life_stream("FlowM", strength=5.0, beads=46.0), index=4)
    sparkle_m = P.mat_emit("Mote", (0.55, 1.0, 0.62), 10.0)
    for k in range(18):
        p = Vector(path[rng.integers(80, len(path))]) + Vector(rng.normal(0, 0.05, 3))
        make_obj(f"Mote{k}", K.ico_cloud([(0, 0, 0)], [rng.uniform(0.0015, 0.0035)], 1), sparkle_m, loc=tuple(p), index=4)
    K.point_light("TipGlow", tuple(tip0 + Vector((0, -0.06, 0.02))), 1.2, radius=0.05, color=(0.50, 1.0, 0.60))
    K.area_light("Back", tuple(S(0.6, -0.3, 2.6) + Vector((0, 0.8, 0.6))), tuple(S(0.45, 0.6, 1.6)), 90.0, 1.0, color=(0.85, 1.0, 0.85))
    K.area_light("Fill", (-0.4, -0.5, 0.4), tuple(S(0.45, 0.6, 1.6)), 6.0, 1.0, color=(0.75, 0.90, 0.80))
    S.place(lens=40.0, fstop=5.6, focus=1.6)
    return {"light": "wood"}


@background("vine")
def bg_vine(P_, h, w, rng, k):
    P_.fill_grad("#0A120F", "#0D1814", cloud=0.12)
    K.bg_glow(P_, 0.50, 0.55, 0.50, 0.45, "#2A5A3A", 0.30)
    bg_clouds(P_, rng, k, [(0.20, 0.03, 0.40, 0.95), (0.84, 0.02, 0.05, 0.55)], "#3E5A48", 0.16)
    K.bg_ink(P_, [(0.02, 0.06, 0.26, 0.18, 0.2), (0.98, 0.06, 0.22, 0.16, -0.4)], 0.45)


@scene("vine_evo", name="万木春", samples=128, grade=dict(WOOD_GRADE, exposure=1.02, bloom=0.34))
def build_vine_evo(draft):
    """万木春：一片龟裂的枯地，青藤从四面八方的地缝里长出来，在地上爬、往中间聚，藤上开着小白花、冒着新叶；
    中间三只小妖被藤一圈圈缠住，挣不动。斜俯看。"""
    from mathutils import Vector  # noqa: PLC0415

    import card_passives as CP

    sky_gradient(lin("#05080A"), lin("#22382C"), 0.6, ground=lin("#030504"))
    rng = np.random.default_rng(101)
    crack = K.np_image("crack_vine", P.crack_texture(2048, rng, n_main=16, reach=0.48, branch=0.07, width=2.4, ring=False))
    ground_plane("Ground", P.mat_ground_crack("Dry", crack, base=(0.055, 0.045, 0.034), uv_from_object=(6.0, 6.0), spec=0.08), size=14.0,
                 index=0)
    vine_m = mat_vine("Vine")
    leaf_m = CP.mat_young_leaf("Leaf")
    petal = CP.mat_petal("Petal")
    center = K.mat_gold("Pollen", color=(0.95, 0.72, 0.25), rough=0.5)
    stamen = CP.mat_petal("Stamen", color=(0.95, 0.90, 0.80), heart=(0.95, 0.85, 0.75))
    imps = [Vector((-0.30, 0.05, 0.0)), Vector((0.28, 0.12, 0.0)), Vector((0.0, 0.42, 0.0))]
    for i, c in enumerate(imps):
        P.imp(f"Imp{i}", size=0.13, loc=tuple(c + Vector((0, 0, 0.12))), rot=(0, 0, rng.uniform(-0.6, 0.6)), rng=rng)
    cam = Vector((0.0, -2.2, 2.0))
    n_v = 0
    for i, c in enumerate(imps):
        for j in range(3):  # 每只妖三根藤：从远处地缝里来，贴地爬到它脚下，再绕着身子往上缠
            a = rng.uniform(0, 2 * math.pi) if j else math.atan2(c.y - 0.15, c.x) + rng.normal(0, 0.4)
            start = c + Vector((math.cos(a), math.sin(a), 0)) * rng.uniform(1.3, 2.0)
            mid = c + Vector((math.cos(a + 0.4), math.sin(a + 0.4), 0)) * 0.45
            crawl = [Vector(p) + Vector((0, 0, 0.015)) for p in CP.bez([tuple(start), tuple(start.lerp(mid, 0.5) + Vector((0.1, -0.1, 0.0))),
                                                                       tuple(mid), tuple(c + Vector((0.16 * math.cos(a), 0.16 * math.sin(a), 0.0)))], n=80)]
            coil = helix_path(c + Vector((0, 0, 0.0)), c + Vector((0, 0, 0.30)), 0.15, 1.6 + 0.3 * j, n=90,
                              phase=a, taper=0.15)
            path = crawl + coil[3:]
            pts = [tuple(p) for p in path]
            make_obj(f"Vine{n_v}", K.tube_uv(pts, 0.014, sides=14, radius_fn=lambda t: 1.0 - 0.6 * t), vine_m, index=1)
            for k_ in range(4):
                idx = int(rng.uniform(0.1, 0.75) * len(pts))
                p = Vector(pts[idx])
                tang = (Vector(pts[min(idx + 2, len(pts) - 1)]) - Vector(pts[idx - 2])).normalized()
                if k_ % 2 == 0:
                    d = (tang + Vector((rng.normal(0, 0.5), rng.normal(0, 0.5), 0.6))).normalized()
                    L = rng.uniform(0.05, 0.07)
                    ob = make_obj(f"Leaf{n_v}_{k_}", K.leaf_build(L, L * 0.5, fold=0.18, curl=0.15, twist=rng.normal(0, 0.3)), leaf_m, index=2)
                    CP.orient(ob, tuple(p), d, (cam - p).normalized())
                else:
                    nrm = (cam - p).normalized() + Vector((0, 0, 0.5))
                    CP.blossom(f"Flower{n_v}_{k_}", tuple(p + Vector((0, 0, 0.012))), nrm, 0.024, petal, center, stamen, rng=rng,
                               spin=rng.uniform(0, 1))
            n_v += 1
    K.area_light("Moon", (-3.0, 3.0, 4.0), (0, 0.2, 0), 260.0, 2.5, color=(0.70, 0.85, 1.0))
    K.area_light("Front", (1.5, -3.0, 2.0), (0, 0.2, 0.1), 40.0, 2.5, color=(0.85, 0.95, 0.85))
    K.point_light("Life", (0.0, 0.2, 0.6), 6.0, radius=0.4, color=(0.55, 1.0, 0.60))
    K.camera(tuple(cam), (0.0, 0.25, 0.12), lens=34.0, fstop=8.0, focus=3.0)
    return {"light": "wood"}


@background("vine_evo")
def bg_vine_evo(P_, h, w, rng, k):
    P_.fill_grad("#0A120F", "#0D1612", cloud=0.12)
    K.bg_ink(P_, [(0.02, 0.06, 0.26, 0.18, 0.2), (0.98, 0.06, 0.22, 0.16, -0.4)], 0.45)


# ====================================================================== 镇妖塔


def eave_build(hs_out, hs_in, h, curl=0.25, n=16, nv=8):
    """一层塔檐：从檐口（外方、四角翘）往里往上收到上一层塔身（内方），坡面往下凹；下面一圈平的檐底。
    原点在檐口中心（檐口高度 z=0）。UV：u 沿一圈（每面 0..1，共 4）、v 檐 → 里（同 pavilion_roof_build）。"""
    def build(bm):
        uvl = bm.loops.layers.uv.new("UVMap")
        corners = [(1, -1), (1, 1), (-1, 1), (-1, -1)]

        def ring(half, z, lift_k):
            out = []
            for side in range(4):
                (ax, ay), (bx, by) = corners[side], corners[(side + 1) % 4]
                for i in range(n):
                    t = i / n
                    lift = lift_k * abs(2 * t - 1) ** 4
                    out.append(bm.verts.new((half * (ax + (bx - ax) * t), half * (ay + (by - ay) * t), z + lift)))
            return out

        rings = []
        for iv in range(nv + 1):
            v = iv / nv
            rings.append(ring(hs_in + (hs_out - hs_in) * (1 - v) ** 1.6, h * v ** 0.8, curl * (1 - v) ** 3))
        under = ring(hs_in * 1.01, -0.015, 0.0)
        N = len(rings[0])
        for iv in range(nv):
            for k in range(N):
                k1 = (k + 1) % N
                f = bm.faces.new((rings[iv][k], rings[iv][k1], rings[iv + 1][k1], rings[iv + 1][k]))
                u0, u1 = (k % n) / n, (k % n + 1) / n
                for lp, uv in zip(f.loops, ((u0 * 4, iv / nv), (u1 * 4, iv / nv), (u1 * 4, (iv + 1) / nv), (u0 * 4, (iv + 1) / nv))):
                    lp[uvl].uv = uv
        for k in range(N):  # 檐底
            k1 = (k + 1) % N
            f = bm.faces.new((rings[0][k1], rings[0][k], under[k], under[k1]))
            for lp in f.loops:
                lp[uvl].uv = (0.0, 0.0)

    return build


def pagoda(name, *, tiers=7, hs=0.30, body_h=0.20, shrink=0.085, wall_m=None, roof_m=None, trim_m=None, window_m=None,
           bell_m=None, loc=(0, 0, 0), rot=(0, 0, 0), index=1):
    """方塔（底在 z=0）：每层一段塔身（四面各一扇窗）+ 一层翘角的檐，檐角各挂一只小铜铃；顶上塔刹（相轮几圈 + 宝珠）。
    返回 (父物体, 塔高)。"""
    bpy = K._bpy()
    root = bpy.data.objects.new(name, None)
    K.link(root)
    root.location, root.rotation_euler = loc, rot
    z = 0.0
    make_obj(f"{name}_Base", K.box_build(hs * 2.4, hs * 2.4, 0.06), trim_m, parent=root, loc=(0, 0, 0.03), index=index, smooth=False,
             bevel=(0.006, 1))
    z = 0.06
    for k in range(tiers):
        f = (1 - shrink) ** k
        half = hs * f
        bh = body_h * (1 - 0.04 * k)
        make_obj(f"{name}_Body{k}", K.box_build(half * 2, half * 2, bh), wall_m, parent=root, loc=(0, 0, z + bh / 2), index=index,
                 smooth=False)
        for sx, sy, rz in ((0, -1, 0.0), (0, 1, 0.0), (-1, 0, math.pi / 2), (1, 0, math.pi / 2)):
            make_obj(f"{name}_Win{k}_{sx}{sy}", K.box_build(half * 0.55, 0.012, bh * 0.55), window_m, parent=root,
                     loc=(sx * (half + 0.002), sy * (half + 0.002), z + bh * 0.5), rot=(0, 0, rz), index=index, smooth=False)
        z += bh
        hs_out = half * 1.75
        hs_in = hs * (1 - shrink) ** (k + 1) * 0.98
        eh = body_h * 0.42
        make_obj(f"{name}_Eave{k}", eave_build(hs_out, hs_in, eh, curl=0.10 * f + 0.03), roof_m, parent=root, loc=(0, 0, z), index=index)
        lift = 0.10 * f + 0.03
        for sx in (-1, 1):
            for sy in (-1, 1):
                c = (sx * hs_out * 0.99, sy * hs_out * 0.99, z + lift - 0.012)
                make_obj(f"{name}_Bell{k}{sx}{sy}", K.lathe_uv([(0.0, 0.0), (0.012 * f + 0.006, -0.004), (0.016 * f + 0.008, -0.030 * f - 0.014),
                                                                 (0.0, -0.030 * f - 0.014)], segments=12), bell_m, parent=root,
                         loc=c, index=index)
        z += eh
    # 塔刹：一根杆、五圈相轮、顶上宝珠
    make_obj(f"{name}_Mast", K.tube_uv([(0, 0, z - 0.02), (0, 0, z + 0.36)], 0.010, sides=10), trim_m, parent=root, index=index)
    for j in range(5):
        make_obj(f"{name}_Ring{j}", K.torus_build(0.040 - 0.004 * j, 0.008, 32, 8), trim_m, parent=root,
                 loc=(0, 0, z + 0.06 + 0.05 * j), index=index)
    make_obj(f"{name}_Pearl", K.ico_cloud([(0, 0, 0)], [0.028], 3), trim_m, parent=root, loc=(0, 0, z + 0.40), index=index)
    return root, z + 0.43


def mat_vortex(name, color=(0.45, 0.20, 0.70), strength=1.2, dark=0.0):
    """旋涡里的气（ribbon：UV.x 沿长 0..1、UV.y 横跨）：暗紫的烟带，沿长一道道细丝，往里（u 大）越来越浓、越亮。
    dark>0 时更像墨烟（妖气）。"""
    M = K.Mat(name)
    m = M.math
    uv = M.coord("UV")
    sep = M.n("ShaderNodeSeparateXYZ")
    M.l(uv, sep.inputs[0])
    u, v = sep.outputs["X"], sep.outputs["Y"]
    mp = M.n("ShaderNodeMapping")
    M.l(uv, mp.inputs["Vector"])
    mp.inputs["Scale"].default_value = (3.0, 14.0, 1.0)
    nz = M.noise(mp.outputs["Vector"], scale=1.0, detail=5.0, rough=0.6)
    across = m("POWER", m("SINE", m("MULTIPLY", v, math.pi)), 1.2)
    fade = m("MULTIPLY", M.maprange(u, 0.0, 0.25), M.maprange(u, 1.0, 0.85))
    a_ = m("MULTIPLY", m("MULTIPLY", across, fade), M.maprange(nz.outputs["Fac"], 0.35, 0.65, 0.25, 1.0))
    bsdf = M.principled(Base_Color=(0.02, 0.015, 0.025, 1.0), Roughness=1.0, Specular_IOR_Level=0.0)
    bsdf.inputs["Emission Color"].default_value = (*color, 1.0)
    M.l(m("MULTIPLY", m("MULTIPLY", a_, u), strength * (1 - dark)), bsdf.inputs["Emission Strength"])
    tr = M.n("ShaderNodeBsdfTransparent")
    mx = M.n("ShaderNodeMixShader")
    M.l(m("MULTIPLY", a_, 0.85, clamp=True), mx.inputs[0])
    M.l(tr.outputs[0], mx.inputs[1])
    M.l(bsdf.outputs[0], mx.inputs[2])
    return M.surface(mx.outputs[0])


def spiral_in(c, r0, r1, turns, z0, z1, phase, n=120):
    """地上往里收的一道螺线（从半径 r0 转 turns 圈收到 r1，高度 z0 → z1）。"""
    from mathutils import Vector  # noqa: PLC0415

    out = []
    for t in np.linspace(0, 1, n):
        r = r0 + (r1 - r0) * t ** 0.8
        a = phase + 2 * math.pi * turns * t
        out.append(Vector(c) + Vector((r * math.cos(a), r * math.sin(a), z0 + (z1 - z0) * t ** 2)))
    return out


@scene("tower", name="镇妖塔", samples=128, grade=dict(EARTH_GRADE, exposure=1.02, bloom=0.36))
def build_tower(draft):
    """镇妖塔：一座七层小宝塔从天上压下来（略斜，塔底离地还有一截），每层翘角檐下挂着小铜铃；塔底下地上一圈旋涡，
    几缕墨色的妖气被卷着往塔底吸，旋涡心透出一点暗紫的光。镜头低一点往上看。"""
    from mathutils import Vector  # noqa: PLC0415

    sky_gradient(lin("#07080C"), lin("#3A3226"), 0.7, ground=lin("#060505"))
    rng = np.random.default_rng(103)
    wall = K.mat_lacquer("TowerWall", color=(0.10, 0.035, 0.025), rough=0.5, coat=0.3)
    roof = P.mat_roof_tiles("TowerTiles", color=(0.045, 0.045, 0.05))
    trim = P.mat_bronze("TowerBronze", base=(0.30, 0.20, 0.09), patina_amt=0.6)
    window = P.mat_emit("TowerWindow", (1.0, 0.55, 0.22), 2.5)
    root, H = pagoda("Tower", tiers=7, wall_m=wall, roof_m=roof, trim_m=trim, window_m=window, bell_m=trim, loc=(0.0, 0.0, 0.85),
                     rot=(math.radians(-6), math.radians(5), math.radians(28)))
    crack = K.np_image("crack_tower", P.crack_texture(2048, rng, n_main=10, reach=0.30, width=3.0))
    ground_plane("Ground", P.mat_ground_crack("GroundM", crack, base=(0.016, 0.014, 0.012), glow=((0.55, 0.25, 0.85), 0.8),
                                              uv_from_object=(8.0, 8.0), fade=2.0, spec=0.08), size=14.0, index=0)
    # 旋涡：地上几道往里收的紫烟；外面几缕墨色妖气被卷进来
    for j in range(6):
        pts = spiral_in((0, 0, 0), 1.25 + 0.15 * j, 0.06, 0.9 + 0.1 * j, 0.02, 0.10, phase=j * 1.05)
        make_obj(f"Swirl{j}", K.ribbon_uv([tuple(p) for p in pts], 0.10 + 0.02 * (j % 3), ups=[(0, 0, 1)] * len(pts)),
                 mat_vortex(f"SwirlM{j}", strength=1.6), index=4)
    for j in range(7):
        a0 = rng.uniform(0, 2 * math.pi)
        pts = spiral_in((0, 0, 0), rng.uniform(1.4, 2.0), 0.1, 0.45, rng.uniform(0.3, 0.8), 0.15, phase=a0)
        make_obj(f"Miasma{j}", K.ribbon_uv([tuple(p) for p in pts], 0.07, ups=[(0, 0, 1)] * len(pts)),
                 mat_vortex(f"MiasmaM{j}", color=(0.30, 0.12, 0.45), strength=0.6, dark=0.7), index=4)
    K.point_light("VortexGlow", (0.0, 0.0, 0.10), 18.0, radius=0.4, color=(0.55, 0.25, 0.85))
    K.area_light("Moon", (-4.0, 6.0, 7.0), (0, 0, 1.4), 900.0, 3.0, color=(0.66, 0.76, 1.0))
    K.area_light("Rim", (5.0, 5.0, 3.0), (0, 0, 1.6), 300.0, 2.0, color=(0.62, 0.72, 1.0))
    K.area_light("Front", (-2.0, -6.0, 1.5), (0, 0, 1.4), 90.0, 4.0, color=(0.75, 0.72, 0.85))
    K.camera((0.6, -5.2, 0.55), (0.0, 0.2, 1.62), lens=30.0, fstop=8.0, focus=5.3)
    _ = (root, H, Vector)
    return {"light": "earth"}


@background("tower")
def bg_tower(P_, h, w, rng, k):
    P_.fill_grad("#0D0F16", "#1A1714", cloud=0.12)
    K.bg_glow(P_, 0.50, 0.30, 0.45, 0.30, "#4A3A5A", 0.24)
    bg_clouds(P_, rng, k, [(0.16, 0.03, 0.25, 0.85), (0.24, 0.02, 0.55, 0.98)], "#5A5060", 0.18)
    K.bg_mist(P_, 0.80, 0.05, "#6A5A70", 0.16, rng, k)
    K.bg_ink(P_, [(0.02, 0.06, 0.26, 0.18, 0.2), (0.98, 0.08, 0.24, 0.18, -0.4)], 0.45)


@scene("tower_evo", name="玲珑塔", samples=128, grade=dict(WARM_GRADE, exposure=1.0, bloom=0.42, sat=1.04))
def build_tower_evo(draft):
    """玲珑塔：一座高大的九层玲珑宝塔悬在半空，檐是鎏金的，塔身每扇窗都透出金光；四面的小妖被吸向塔身，
    身后拖着一道道往塔去的气痕。镜头往上看，塔顶在画面上方中间。"""
    from mathutils import Vector  # noqa: PLC0415

    sky_gradient(lin("#0A0806"), lin("#3A2A16"), 0.6, ground=lin("#050403"))
    rng = np.random.default_rng(107)
    wall = K.mat_lacquer("GoldWall", color=(0.16, 0.06, 0.03), rough=0.4, coat=0.5)
    roof = K.mat_gold("GoldRoof", worn=0.35)
    trim = K.mat_gold("GoldTrim", worn=0.2)
    window = P.mat_emit("GoldWindow", (1.0, 0.70, 0.30), 7.0)
    root, H = pagoda("Tower", tiers=9, hs=0.34, body_h=0.21, wall_m=wall, roof_m=roof, trim_m=trim, window_m=window, bell_m=trim,
                     loc=(0.0, 0.0, -1.10), rot=(0, 0, math.radians(30)))
    K.point_light("TowerCore", (0.0, -0.3, 0.2), 120.0, radius=0.6, color=(1.0, 0.68, 0.28))
    # 四面的小妖被吸过来：每只身后一道往塔去的气痕
    for i in range(10):
        a = rng.uniform(0, 2 * math.pi)
        r = rng.uniform(1.3, 2.3)
        p = Vector((r * math.cos(a), r * math.sin(a) * 0.6 + 0.2, rng.uniform(-0.8, 1.1)))
        if p.y < -0.6 and abs(p.x) < 0.6:
            continue
        to = (Vector((0, 0, p.z * 0.6 + 0.1)) - p).normalized()
        P.imp(f"Imp{i}", size=rng.uniform(0.07, 0.10), loc=tuple(p), rot=tuple(rng.uniform(-1.0, 1.0, 3)), rng=rng)
        pts = [tuple(p - to * (0.55 * t) + Vector((0, 0, 0.05 * math.sin(4 * t + i)))) for t in np.linspace(0, 1, 30)]
        make_obj(f"Trail{i}", K.ribbon_uv(pts, 0.05, width_fn=lambda t: 1 - 0.8 * t),
                 K.mat_wind(f"TrailM{i}", strength=1.3, seed=i * 1.3, color=(1.0, 0.78, 0.45)), index=3)
    K.area_light("Rim", (-3.0, 4.0, 3.0), (0, 0, 0.4), 600.0, 2.5, color=(0.62, 0.72, 1.0))
    K.area_light("Front", (1.5, -5.0, 0.5), (0, 0, 0.4), 60.0, 3.0, color=(1.0, 0.82, 0.60))
    K.camera((0.2, -6.6, -0.65), (0.0, 0.0, 0.62), lens=30.0, fstop=8.0, focus=6.6)
    _ = (root, H)
    return {"light": "warm"}


@background("tower_evo")
def bg_tower_evo(P_, h, w, rng, k):
    P_.fill_grad("#120E0A", "#1A120C", cloud=0.12)
    K.bg_glow(P_, 0.50, 0.42, 0.50, 0.50, "#7A4A18", 0.40)
    K.bg_glow(P_, 0.50, 0.38, 0.20, 0.30, "#C08030", 0.22)
    bg_clouds(P_, rng, k, [(0.78, 0.03, 0.05, 0.95), (0.86, 0.02, 0.20, 0.80)], "#6A4A30", 0.20)
    K.bg_ink(P_, [(0.02, 0.06, 0.26, 0.18, 0.2), (0.98, 0.08, 0.24, 0.18, -0.4)], 0.45)


