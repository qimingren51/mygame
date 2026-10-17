BODY_BANDS = [(0.0, S.INK["nong"]), (0.36, S.INK["dan"]), (0.74, S.PAPER)]  # 背浓墨 → 侧淡墨 → 胸腹白
HEAD_BANDS = [(0.0, S.INK["nong"]), (0.40, S.INK["dan"]), (0.56, S.PAPER)]  # 额浓墨 → 淡墨 → 白色面纹
LEG_BANDS = [(0.0, S.INK["dan"]), (0.22, S.INK["nong"])]  # 大臂/大腿接侧腹的淡墨，往下是浓墨“袜子”
HEAD_S = 1.3  # 头整体放大（风格化：游戏尺寸下先读出狐狸头）


def _ring_body_build(spine, attrs_out, segs=20):
    """沿脊线的椭圆截面体（躯干、颈、头）：spine = [(中心点, 横半径, 竖半径[, 偏移]), ...]。
    attrs_out 按顶点顺序填“由背到腹”的 0..1（截面里越靠下越大）再加该截面的偏移，
    给 *_BANDS 分段上色：偏移越大白色越往上漫（胸前白围、喉部、吻部）。两端收成圆头。"""
    pts = [Vector(e[0]) for e in spine]
    n = len(pts)

    def build(bm):
        rings = []
        for i, e in enumerate(spine):
            p, rx, rz = Vector(e[0]), e[1], e[2]
            bias = e[3] if len(e) > 3 else 0.0
            tan = (pts[min(i + 1, n - 1)] - pts[max(i - 1, 0)]).normalized()
            side = tan.cross(Vector((0, 0, 1)))
            side = side.normalized() if side.length > 1e-4 else Vector((1, 0, 0))
            up = side.cross(tan).normalized()
            ring = []
            for j in range(segs):
                th = 2 * math.pi * j / segs
                ring.append(bm.verts.new(p + side * (math.cos(th) * rx) + up * (math.sin(th) * rz)))
                attrs_out.append(0.5 - 0.5 * math.sin(th) + bias)  # 顶 0，底 1
            rings.append(ring)
        for a_, b_ in zip(rings, rings[1:]):
            for j in range(segs):
                bm.faces.new((a_[j], a_[(j + 1) % segs], b_[(j + 1) % segs], b_[j]))
        for ring, e, ax, rev in ((rings[0], spine[0], pts[0] - pts[1], True),
                                 (rings[-1], spine[-1], pts[-1] - pts[-2], False)):
            c = sum((v.co for v in ring), Vector()) / segs
            cv = bm.verts.new(c + ax.normalized() * 0.55 * min(e[1], e[2]))
            attrs_out.append(0.5 + (e[3] if len(e) > 3 else 0.0))
            for j in range(segs):
                bm.faces.new((ring[(j + 1) % segs], ring[j], cv) if rev else (ring[j], ring[(j + 1) % segs], cv))
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)

    return build


def _cone_build(base, tip, r0, r1, flat=1.0, segs=12):
    """从 base 到 tip 的锥（下颌）；flat 压扁“竖向”截面。"""
    return K.tube_build(K.curve_points(base, tip, n=6), lambda t: r0 + (r1 - r0) * t, segs, flat=flat)


def _ear_build(base, tip, half_w, half_d, facing, segs=12):
    """宽底三角耳：底面是 半宽 half_w × 半厚 half_d 的扁椭圆，收到 tip 一点；facing 是耳孔朝向。"""
    base, tip = Vector(base), Vector(tip)
    ax = (tip - base).normalized()
    f = Vector(facing) - ax * Vector(facing).dot(ax)
    f.normalize()
    w = ax.cross(f).normalized()

    def build(bm):
        ring = [bm.verts.new(base + w * math.cos(2 * math.pi * j / segs) * half_w
                             + f * math.sin(2 * math.pi * j / segs) * half_d) for j in range(segs)]
        apex, bc = bm.verts.new(tip), bm.verts.new(base - ax * 0.01)
        for j in range(segs):
            bm.faces.new((ring[j], ring[(j + 1) % segs], apex))
            bm.faces.new((ring[(j + 1) % segs], ring[j], bc))
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)

    return build


def _bvh(ob):
    """网格物体（自身坐标）的 BVH，用来把眼睛、纹样贴到头的表面上。"""
    me = ob.data
    return BVHTree.FromPolygons([v.co.copy() for v in me.vertices], [tuple(p.vertices) for p in me.polygons])


def _on_surface(tree, p, out_dir, lift=0.0):
    """从 p 外侧沿 -out_dir 打射线，返回 (表面点 + 法线 * lift, 法线)。"""
    d = Vector(out_dir).normalized()
    hit, nrm, _, _ = tree.ray_cast(Vector(p) + d * 0.8, -d)
    if hit is None:
        return Vector(p), d
    if nrm.dot(d) < 0:
        nrm = -nrm
    return hit + nrm * lift, nrm


def _frame_rot(axis_x, nrm):
    """以 nrm 为局部 Z、axis_x 投到切平面为局部 X 的旋转（欧拉角）。"""
    x = Vector(axis_x) - nrm * Vector(axis_x).dot(nrm)
    x.normalize()
    y = nrm.cross(x).normalized()
    return Matrix((x, y, nrm)).transposed().to_euler(), x, y


def _boss_head(prefix, parent, M, eye_mat, head_mat, s=HEAD_S):
    """真正的狐狸头（头坐标系：原点在头心，面朝 -Y，单位米 × s）。
    一体的楔形头骨 → 中等长度的锥形吻部（起点与两眼间距同宽，长约头骨高的 1.15 倍）；HEAD_BANDS 上色：
    额头浓墨、鼻梁淡墨，吻部、下颌、两颊白色（同一个材质，不画分界线）；黑鼻头、嘴线；
    两颊白毛向后炸开成三簇尖；杏仁细缝眼（EYE['boss'] 发光、朱砂细边）贴在额止两侧，眼上各一笔朱砂火焰纹；
    宽底大三角耳（底宽约为高的 0.6），微外撇，内耳白、带一簇白毛。返回眼睛挂点。"""
    obj = B.mesh_object

    def V(x, y, z):
        return Vector((x * s, y * s, z * s))

    spine = [((0, 0.26, 0.04), 0.09, 0.09, -0.10), ((0, 0.18, 0.04), 0.19, 0.18, -0.10),
             ((0, 0.06, 0.02), 0.24, 0.20, -0.04), ((0, -0.06, 0.0), 0.22, 0.18, 0.02),  # 颧部最宽
             ((0, -0.16, -0.03), 0.16, 0.14, 0.10),  # 额止：吻部从这里起，宽度约等于两眼间距
             ((0, -0.28, -0.06), 0.11, 0.105, 0.26), ((0, -0.40, -0.08), 0.085, 0.085, 0.30),
             ((0, -0.50, -0.095), 0.06, 0.065, 0.30), ((0, -0.58, -0.10), 0.035, 0.04, 0.30)]
    spine = [(tuple(V(*p)), rx * s, rz * s, b) for p, rx, rz, b in spine]
    shade: list = []
    skull = obj(f"{prefix}Skull", _ring_body_build(spine, shade, segs=24), head_mat, "outer", parent, sharp_deg=0)
    B.set_point_attr(skull, "fade", shade)
    tree = _bvh(skull)
    obj(f"{prefix}Jaw", _cone_build(V(0, -0.12, -0.13), V(0, -0.48, -0.15), 0.08 * s, 0.024 * s, flat=0.55),
        M["mask"], "outer", parent)
    obj(f"{prefix}Nose", K.ellipsoid((0.042 * s, 0.034 * s, 0.032 * s), 10, 6), M["ink"], "none", parent,
        loc=V(0, -0.605, -0.095))
    eyes = []
    for sx in (-1, 1):
        # 嘴线：从鼻下沿吻侧往后，到嘴角微微上挑
        mouth = [_on_surface(tree, V(0.03 * sx, y, z), (sx * 0.6, 0, -0.8), 0.006 * s)[0]
                 for y, z in ((-0.56, -0.12), (-0.44, -0.135), (-0.32, -0.125), (-0.22, -0.10))]
        obj(f"{prefix}Mouth{sx:+d}", K.strip_build(mouth, 0.016 * s, 0.006 * s, side_hint=Vector((0, 0, 1)),
                                                   taper=(0.6, 1.0)), M["ink"], "none", parent)
        # 两颊白毛：向后、向外炸开的三簇尖
        for k_, (tip, r_) in enumerate((((0.38, 0.20, -0.04), 0.060), ((0.35, 0.28, -0.15), 0.065),
                                        ((0.27, 0.26, -0.25), 0.055))):
            base = V(0.17 * sx, 0.02, -0.08 - 0.03 * k_)
            tp = V(tip[0] * sx, tip[1], tip[2])
            obj(f"{prefix}Ruff{sx:+d}{k_}", K.tube_build(K.curve_points(base, tp, bend=V(0, -0.03, 0.03), n=6),
                                                           lambda t, r_=r_: r_ * s * (1 - t) ** 0.9 + 0.002, 8, flat=0.55),
                M["mask"], "outer", parent)
        # 杏仁眼：贴在额止两侧的表面上；眼角由前下斜向后上
        loc, nrm = _on_surface(tree, V(0.12 * sx, -0.15, 0.05), (sx * 0.72, -0.55, 0.42))
        rot, ex, ey = _frame_rot(Vector((0, 1, 0.55)), nrm)
        obj(f"{prefix}EyeRim{sx:+d}", K.ellipsoid((0.080 * s, 0.032 * s, 0.010 * s), 14, 6), M["red"], "none", parent,
            loc=loc + nrm * 0.004 * s, rot=rot)
        obj(f"{prefix}Eye{sx:+d}", K.ellipsoid((0.066 * s, 0.019 * s, 0.010 * s), 14, 6), eye_mat, "none", parent,
            loc=loc + nrm * 0.011 * s, rot=rot)
        eyes.append(loc)
        # 眼上一笔朱砂火焰纹：从眼头上方起笔，向上、向后挑出
        up = ey if ey.z > 0 else -ey
        flame = [_on_surface(tree, loc + up * (0.05 * s + 0.055 * s * k) + ex * (-0.02 + 0.035 * k - 0.012 * k * k) * s,
                             nrm, 0.007 * s)[0] for k in range(4)]
        obj(f"{prefix}Flame{sx:+d}", K.strip_build(flame, 0.036 * s, 0.006 * s, side_hint=ex, taper=(1.0, 0.1)),
            M["red"], "none", parent)
        # 宽底大三角耳：高约 0.38，底宽约 0.23（≈0.6 倍高），微外撇；耳孔朝前偏外
        base, tip = V(0.12 * sx, 0.08, 0.15), V(0.22 * sx, 0.13, 0.53)
        facing = Vector((0.34 * sx, -0.94, 0.0))
        obj(f"{prefix}Ear{sx:+d}", _ear_build(base, tip, 0.115 * s, 0.045 * s, facing), M["fur"], "outer", parent,
            sharp_deg=0)
        ax = (tip - base).normalized()
        f = (facing - ax * facing.dot(ax)).normalized()
        ib = base + ax * 0.04 * s + f * 0.03 * s
        obj(f"{prefix}EarIn{sx:+d}", _ear_build(ib, tip - ax * 0.09 * s + f * 0.012 * s, 0.075 * s, 0.022 * s, facing),
            M["mask"], "none", parent, sharp_deg=0)
        tuft = K.curve_points(ib + f * 0.01 * s, ib + f * 0.05 * s + ax * 0.16 * s + Vector((0.03 * sx * s, 0, 0)), n=5)
        obj(f"{prefix}EarTuft{sx:+d}", K.tube_build(tuft, lambda t: 0.028 * s * (1 - t) + 0.002, 6, flat=0.6),
            M["mask"], "none", parent)
    c = (eyes[0] + eyes[1]) / 2
    return B.empty(f"{prefix}SocketEyes", parent, loc=c)


def _leg_build(path, radii, fades=None):
    """有关节的锥形腿：沿关节点折线插值成管，半径逐段渐细（关节处可以略鼓）。fades 填沿腿的 0..1。"""
    pts, rr = [], []
    for (a_, ra), (b_, rb) in zip(zip(path, radii), zip(path[1:], radii[1:])):
        a_, b_ = Vector(a_), Vector(b_)
        for k in range(4):
            t = k / 4
            pts.append(a_.lerp(b_, t))
            rr.append(ra + (rb - ra) * t)
    pts.append(Vector(path[-1]))
    rr.append(radii[-1])
    n = len(pts)
    return K.tube_build(pts, lambda t: float(np.interp(t, np.linspace(0, 1, n), rr)), 12, fades=fades)


# 四肢（髋/肩坐标系，地面在 -髋高）：前腿 肩 → 肘（略后）→ 细前臂 → 腕 → 短掌 → 小爪；
# 后腿 粗大腿（髋部肌肉）→ 膝（向前）→ 细小腿 → 跗关节（向后）→ 长跖骨 → 小爪。
FRONT_HIP, HIND_HIP = (0.22, -0.58, 1.70), (0.20, 0.64, 1.86)
FRONT_LEG = ([(0, 0.0, 0.12), (0, 0.07, -0.50), (0, 0.03, -0.80), (0, -0.02, -1.36), (0, -0.06, -1.58)],
             [0.20, 0.12, 0.075, 0.064, 0.056])
HIND_LEG = ([(0, 0.02, 0.10), (0, -0.22, -0.58), (0, 0.0, -0.80), (0, 0.22, -1.02), (0, 0.12, -1.72)],
            [0.30, 0.13, 0.08, 0.07, 0.056])


def build_boss():
    I = S.INK
    M = _mats("Boss")
    eye = B.emissive_material("BossEye", S.EYE["boss"], 1.0)
    tail_mat = K.banded_toon_material("BossTailInk", TAIL_BANDS, edge=0.3, seed=58.0)
    ruff_mat = K.banded_toon_material("BossRuffInk", RUFF_BANDS, edge=0.3, seed=59.0)
    body_mat = K.banded_toon_material("BossBodyInk", BODY_BANDS, edge=0.3, noise_amt=0.12, seed=60.0)
    head_mat = K.banded_toon_material("BossHeadInk", HEAD_BANDS, edge=0.3, noise_amt=0.08, seed=61.0)
    leg_mat = K.banded_toon_material("BossLegInk", LEG_BANDS, edge=0.3, noise_amt=0.10, seed=62.0)
    paw_mat = K.toon("BossPaw", I["dan"], edge=0.35, seed=63.0)
    root = B.empty("BossRoot")
    yaw = K.yaw_pivot("BossYaw", root, -20)
    body = B.empty("BossBody", yaw)  # 四爪着地潜行（不悬浮）
    parts = {"root": root, "body": body, "M": M, "tails": [], "tail_mat": tail_mat}
    obj = B.mesh_object

    def ringed(name, spine, mat):
        shade: list = []
        ob = obj(name, _ring_body_build(spine, shade), mat, "outer", body, sharp_deg=0)
        B.set_point_attr(ob, "fade", shade)
        return ob

    # 躯干：深胸（胸前白围）、收腰（腹线向后腿抬起，白腹）、髋部再鼓起；第四项是白色往上漫的偏移
    ringed("BossTorso", [((0, -0.96, 1.86), 0.13, 0.15, 0.28), ((0, -0.84, 1.82), 0.30, 0.44, 0.28),
                         ((0, -0.58, 1.80), 0.36, 0.50, 0.16), ((0, -0.26, 1.85), 0.32, 0.41, 0.08),
                         ((0, 0.08, 1.93), 0.25, 0.27, 0.12), ((0, 0.38, 1.95), 0.27, 0.31, 0.06),
                         ((0, 0.66, 1.93), 0.32, 0.36, 0.0), ((0, 0.90, 1.92), 0.27, 0.30, 0.0),
                         ((0, 1.06, 1.92), 0.13, 0.15, 0.0)], body_mat)
    # 粗壮、微弓的颈，喉部白
    neck = [((0, -0.62, 2.00), 0.30, 0.36, 0.14), ((0, -0.88, 2.12), 0.27, 0.31, 0.26),
            ((0, -1.10, 2.16), 0.24, 0.27, 0.30), ((0, -1.28, 2.12), 0.20, 0.22, 0.30)]
    ringed("BossNeck", neck, body_mat)
    # 鬃毛：沿颈背向后飘，左右交错
    for i in range(10):
        f = i / 9
        y = -1.22 + 0.64 * f
        zc = float(np.interp(y, [-1.28, -1.10, -0.88, -0.62], [2.12, 2.16, 2.12, 2.00]))
        rz = float(np.interp(y, [-1.28, -1.10, -0.88, -0.62], [0.22, 0.27, 0.31, 0.36]))
        rx = float(np.interp(y, [-1.28, -1.10, -0.88, -0.62], [0.20, 0.24, 0.27, 0.30]))
        a = math.radians(-60 + 120 * ((i * 0.618) % 1.0))
        base = Vector((0.55 * rx * math.sin(a), y, zc + 0.80 * rz * math.cos(a)))
        tip = base + Vector((0.25 * math.sin(a), 0.46, 0.10 - 0.10 * f))
        fades: list = []
        ob = obj(f"BossMane{i}", K.tube_build(K.curve_points(base, tip, bend=Vector((0, 0.0, 0.06)), n=7),
                                             K.bushy(0.10, peak=0.3), 8, flat=0.6, fades=fades), ruff_mat, "outer", body)
        B.set_point_attr(ob, "fade", fades)
    head = B.empty("BossHead", body, loc=(0, -1.44, 2.12), rot=(math.radians(6), 0, math.radians(-8)))
    parts["head"] = head
    sock = _boss_head("BossH", head, M, eye, head_mat)
    # 四肢；肘后、跗后各一簇毛；小椭圆爪 + 墨色趾缝
    legs = {}
    for nm, sx, front in (("FL", 1, True), ("FR", -1, True), ("HL", 1, False), ("HR", -1, False)):
        hx, hy, hz = FRONT_HIP if front else HIND_HIP
        hip = B.empty(f"BossHip{nm}", body, loc=(hx * sx, hy, hz))
        path, radii = FRONT_LEG if front else HIND_LEG
        fades: list = []
        leg = obj(f"BossLeg{nm}", _leg_build(path, radii, fades), leg_mat, "outer", hip, sharp_deg=0)
        B.set_point_attr(leg, "fade", fades)
        j = Vector(path[3])  # 腕 / 跗关节略鼓
        obj(f"BossJoint{nm}", K.ellipsoid((radii[3] * 1.12, radii[3] * 1.3, radii[3] * 1.2), 10, 6), M["fur"], "outer",
            hip, loc=j)
        tuft_at = Vector(path[1]) + Vector((0, 0.06, -0.02)) if front else j + Vector((0, 0.04, 0.02))
        tuft_dir = Vector((0, 0.20, -0.10)) if front else Vector((0, 0.17, -0.07))
        fades = []
        tf = obj(f"BossTuft{nm}", K.tube_build(K.curve_points(tuft_at, tuft_at + tuft_dir, n=5),
                                               lambda t: 0.055 * (1 - t) + 0.002, 8, flat=0.6, fades=fades), ruff_mat,
                 "outer", hip)
        B.set_point_attr(tf, "fade", fades)
        ground = -hz
        paw_c = Vector((0, path[-1][1] - 0.05, ground + 0.05))
        obj(f"BossPaw{nm}", K.ellipsoid((0.075, 0.11, 0.05), 12, 6), paw_mat, "outer", hip, loc=paw_c)
        for t_ in (-1, 0, 1):  # 墨色趾缝
            pts = [paw_c + Vector((0.026 * t_, -0.05, 0.045)), paw_c + Vector((0.032 * t_, -0.105, 0.015))]
            obj(f"BossToe{nm}{t_}", K.strip_build(pts, 0.016, 0.006, side_hint=Vector((1, 0, 0)), taper=(1.0, 0.5)),
                M["ink"], "none", hip)
        legs[nm] = hip
    parts["legs"] = legs
    troot = Vector((0, 1.00, 1.94))  # 尾根粗，接在臀上
    for i in range(BOSS_TAILS):
        fades = []
        ob = obj(f"BossTail{i}", K.tube_build(_boss_tail(troot, i, 0.0), _brush, 12, flat=0.62, fades=fades),
                 tail_mat, "outer", body, sharp_deg=0)
        B.set_point_attr(ob, "fade", fades)
        parts["tails"].append((ob, troot, i))
    sockets = {"eyes": sock, "feet": B.empty("BossFeet", root)}
    parts["sockets"] = sockets
    bpy.context.view_layer.update()
    return root, parts, sockets


