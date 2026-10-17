

# ====================================================================== 剑意


def sleeve(name, wrist, d, *, r=0.040, L=0.20, mat=None, index=1, flare=1.5):
    """袖口：沿 d（从腕往肘）的一段布筒，腕口略收、往后放宽，口沿一道深色镶边。"""
    from mathutils import Vector  # noqa: PLC0415

    mat = mat or K.mat_cloth(f"{name}_Cloth", (0.045, 0.055, 0.085), weave=900.0)
    d = Vector(d).normalized()
    pts = [tuple(Vector(wrist) + d * (L * t)) for t in np.linspace(0, 1, 20)]
    make_obj(name, K.tube_uv(pts, r, sides=40, radius_fn=lambda t: 1.0 + (flare - 1.0) * t ** 1.5, caps=False), mat, index=index)
    make_obj(f"{name}_Hem", K.tube_uv([tuple(Vector(wrist) + d * (L * t)) for t in np.linspace(0, 0.08, 4)], r * 1.03, sides=40,
                                      caps=False), K.mat_cloth(f"{name}_HemM", (0.012, 0.012, 0.016), weave=900.0), index=index)


def scabbard(name, L=0.70, W=0.050, T=0.026, *, lac=None, gold=None, parent=None, index=1):
    """剑鞘（沿 +X，鞘口在 x=0）：扁椭圆截面的黑漆木鞘，鞘口、鞘中、鞘尾三道鎏金铜箍，尾端收圆。"""
    lac = lac or K.mat_lacquer(f"{name}_Lac", color=(0.020, 0.012, 0.010))
    gold = gold or K.mat_gold(f"{name}_Gold", worn=0.5)
    pts = [(L * t, 0.0, 0.0) for t in np.linspace(0, 1, 60)]
    make_obj(name, K.tube_uv(pts, W / 2, sides=32, flat=T / W, radius_fn=lambda t: (1 - 0.12 * t) * (1 - 0.6 * max(0.0, (t - 0.96) / 0.04) ** 2)),
             lac, parent=parent, index=index, rot=(math.pi / 2, 0, 0))
    for x0, x1 in ((0.0, 0.045), (0.30, 0.32), (L - 0.07, L)):
        k0 = 1 - 0.12 * x0 / L
        make_obj(f"{name}_Band{x0:.2f}", K.tube_uv([(x0, 0, 0), (x1, 0, 0)], W / 2 * k0 * 1.08, sides=32, flat=T / W), gold,
                 parent=parent, index=index, rot=(math.pi / 2, 0, 0))


@scene("jianyi", name="剑意", samples=128, grade=dict(COLD_GRADE, bloom=0.40))
def build_jianyi(draft):
    """剑意：一只手握着剑柄（手背朝镜头、袖口压在腕上），剑还在黑漆鞘里，只拔出一指宽；鞘口那道缝里已经凝出一道白光，
    几缕光丝从缝里迸出来。剑斜着从左下指向右上，冷月光打轮廓。"""
    from mathutils import Matrix, Vector  # noqa: PLC0415

    sky_gradient(lin("#05080F"), lin("#33496C"), 0.9, ground=lin("#04060A"))
    rng = np.random.default_rng(13)
    S = ScreenCam(lens=45.0)
    g0, g1 = S(0.36, 0.62, 0.95), S(0.98, 0.20, 1.10)  # 剑格在左中，鞘尾出画右上
    d = (g1 - g0).normalized()
    zh = Vector((0.0, -0.4, 1.0))
    q = frame_quat(d, zh)
    steel = P.mat_steel("Steel", tint=(0.86, 0.89, 0.94), rough=0.10, edge_glow=((0.85, 0.95, 1.0), 4.0))
    root = P.sword("Sword", steel=steel, loc=tuple(g0), rot=q.to_euler(), index=1, tassel=True)
    gap = 0.030  # 拔出的一指宽
    sc_root = K._bpy().data.objects.new("ScabbardRoot", None)
    K.link(sc_root, root)
    sc_root.location = (gap, 0, 0)
    scabbard("Scabbard", L=0.72, parent=sc_root)
    # 鞘口的光：一圈很亮的光环 + 几缕往外迸的光丝 + 点光
    R_ = Matrix(((1, 0, 0), (0, 1, 0), (0, 0, 1)))
    glow = P.mat_emit("GapGlow", (0.85, 0.94, 1.0), 30.0)
    make_obj("GapRing", K.tube_uv([(gap - 0.002, 0, 0), (gap + 0.001, 0, 0)], 0.027, sides=32, flat=0.52, caps=False), glow, parent=root,
             index=3, rot=(math.pi / 2, 0, 0))
    for j in range(9):
        a = 2 * math.pi * j / 9 + rng.normal(0, 0.2)
        dirv = Vector((rng.uniform(-0.2, 0.25), math.cos(a), math.sin(a) * 0.6)).normalized()
        L = rng.uniform(0.06, 0.16)
        pts = [tuple(Vector((gap, 0, 0)) + dirv * (0.02 + L * t) + Vector((0.01 * t, 0, 0))) for t in np.linspace(0, 1, 20)]
        make_obj(f"Ray{j}", K.ribbon_uv(pts, rng.uniform(0.004, 0.010), ups=[(1, 0, 0)] * len(pts)),
                 K.mat_wind(f"RayM{j}", strength=rng.uniform(2.0, 3.5), seed=j * 1.3, color=(0.80, 0.92, 1.0)), parent=root, index=3)
    K.point_light("GapLight", tuple(root.matrix_world @ Vector((gap, -0.03, 0.0))) if False else tuple(g0 + d * gap + Vector((0, -0.04, 0))),
                  3.0, radius=0.01, color=(0.80, 0.92, 1.0))
    # 握剑的手：拳握在柄中段，拇指朝剑格；手背朝镜头
    skin = P.mat_skin("Skin", color=(0.56, 0.40, 0.31))
    grip_c = g0 - d * 0.085
    hx = d  # 手的 +X（拇指一侧）顺着剑
    hz = (Vector((0, 0, 1)) - d * d.z).normalized()  # 手指朝上绕过剑柄
    hz = (hz + Vector((0, -0.6, 0))).normalized()
    hq = frame_quat(hx, hz)
    Rm = hq.to_matrix()
    wrist = grip_c - Rm @ Vector((0.0, -0.024, 0.080))
    P.hand("Hand", skin, P.HAND_FIST, loc=tuple(wrist), rot=hq.to_euler())
    sleeve("Sleeve", tuple(wrist + Rm @ Vector((0, 0.0, 0.01))), tuple(-(Rm @ Vector((0, 0, 1)))), r=0.042, L=0.25)
    K.area_light("Moon", (-1.2, 1.6, 1.6), tuple(g0), 90.0, 1.2, color=(0.66, 0.78, 1.0))
    K.area_light("Key", (-0.8, -1.2, 0.9), tuple(g0), 25.0, 1.0, color=(0.78, 0.84, 1.0))
    K.area_light("Warm", (1.0, -0.8, -0.4), tuple(g0), 4.0, 0.8, color=(1.0, 0.74, 0.50))
    S.place(lens=45.0, fstop=4.0, focus=0.95)
    _ = R_
    return {"light": "cold"}


@background("jianyi")
def bg_jianyi(P_, h, w, rng, k):
    P_.fill_grad("#0C1322", "#111B2E", cloud=0.12)
    K.bg_glow(P_, 0.48, 0.45, 0.45, 0.40, "#405A80", 0.30)
    K.bg_glow(P_, 0.46, 0.48, 0.12, 0.14, "#B8CCE6", 0.18)
    bg_clouds(P_, rng, k, [(0.25, 0.03, 0.40, 0.98), (0.80, 0.03, 0.02, 0.60)], "#5B7194", 0.18)
    K.bg_ink(P_, [(0.02, 0.06, 0.26, 0.18, 0.2), (0.98, 0.96, 0.30, 0.20, -0.2)], 0.45)


# ====================================================================== 聚魂


@scene("juhun", name="聚魂", samples=128, grade=dict(WARM_GRADE, exposure=1.0, bloom=0.44))
def build_juhun(draft):
    """聚魂：一只摊开的手（掌心朝上，袖口在右下），掌心上方一团暖光；点点魂火从四面八方沿着弧线汇过来，
    越近越暖、越亮，拖着细尾。手被那团光从上面照亮。"""
    from mathutils import Vector  # noqa: PLC0415

    K.set_world(lin("#07080E"), 1.0)
    rng = np.random.default_rng(41)
    skin = P.mat_skin("Skin", color=(0.56, 0.40, 0.31))
    pose = {"index": (-8, 14, 12, 6), "middle": (-1, 14, 12, 6), "ring": (6, 16, 13, 7), "pinky": (14, 18, 14, 8), "thumb": (50, 25, 12, 10)}
    # 手：掌心朝上（手的 -Y → 世界 +Z），手指朝左后
    hx = Vector((0.25, 0.97, 0.0)).normalized()  # 拇指一侧朝里（远离镜头）
    hz = Vector((-0.92, 0.20, 0.18)).normalized()  # 手指朝左
    q = frame_quat(hx, hz)
    wrist = Vector((0.10, -0.02, -0.02))
    P.hand("Hand", skin, pose, loc=tuple(wrist), rot=q.to_euler())
    Rm = q.to_matrix()
    sleeve("Sleeve", tuple(wrist + Rm @ Vector((0, 0, 0.012))), tuple(-(Rm @ Vector((0, 0, 1)))), r=0.044, L=0.30, flare=1.7)
    palm = wrist + Rm @ Vector((0.0, -0.05, 0.06))
    orb_c = palm + Vector((0, 0, 0.075))
    core = P.mat_emit("Orb", (1.0, 0.78, 0.45), 24.0)
    make_obj("Orb", K.ico_cloud([(0, 0, 0)], [0.020], 3), core, loc=tuple(orb_c), index=4)
    halo = mat_soul_fire_warm("Halo")
    make_obj("Halo", K.ico_cloud([(0, 0, 0)], [0.040], 3), halo, loc=tuple(orb_c), index=4)
    K.point_light("OrbLight", tuple(orb_c), 6.0, radius=0.02, color=(1.0, 0.72, 0.40))
    # 魂火：从四周沿弧线飞向掌心（远处青白、近处暖金）
    for k in range(16):
        a = 2 * math.pi * k / 16 + rng.normal(0, 0.15)
        el = rng.uniform(-0.3, 0.9)
        r0 = rng.uniform(0.25, 0.45)
        start = orb_c + Vector((r0 * math.cos(a) * math.cos(el), r0 * math.sin(a) * math.cos(el) * 0.7, r0 * math.sin(el) * 0.6 + 0.05))
        side = Vector((-math.sin(a), math.cos(a), 0.0)) * rng.uniform(0.06, 0.14) * (1 if k % 2 else -1)
        pts = []
        for t in np.linspace(0, 1, 50):
            pts.append(tuple(start.lerp(orb_c, t) + side * math.sin(math.pi * t) * (1 - t)))
        head_t = rng.uniform(0.35, 0.8)
        n_ = int(len(pts) * head_t)
        trail = pts[max(0, n_ - 18):n_]
        if len(trail) < 3:
            continue
        warm = head_t
        col = (0.45 + 0.55 * warm, 0.90 - 0.15 * warm, 0.85 - 0.45 * warm)
        make_obj(f"Wisp{k}", K.ribbon_uv(list(reversed(trail)), rng.uniform(0.006, 0.010), width_fn=lambda t: 1 - 0.9 * t),
                 K.mat_wind(f"WispM{k}", strength=2.2, seed=k * 1.1, color=col), index=4)
        make_obj(f"Spirit{k}", K.ico_cloud([(0, 0, 0)], [rng.uniform(0.004, 0.007)], 2), P.mat_emit(f"SpiritM{k}", col, 18.0),
                 loc=trail[-1], index=4)
    K.area_light("Rim", (-0.6, 0.8, 0.5), tuple(palm), 8.0, 0.6, color=(0.55, 0.68, 1.0))
    K.area_light("Fill", (0.4, -0.8, 0.3), tuple(palm), 1.5, 0.8, color=(0.62, 0.70, 0.95))
    K.camera(tuple(palm + Vector((0.05, -0.55, 0.30))), tuple(palm + Vector((0.0, 0.0, 0.06))), lens=50.0, fstop=3.2, focus=0.62)
    return {"light": "warm"}


def mat_soul_fire_warm(name):
    return mat_soul_fire(name, color=(1.0, 0.70, 0.36), strength=3.0)


@background("juhun")
def bg_juhun(P_, h, w, rng, k):
    P_.fill_grad("#0A0B12", "#0C0C12", cloud=0.12)
    K.bg_glow(P_, 0.50, 0.40, 0.45, 0.40, "#5A3A1C", 0.26)
    K.bg_glow(P_, 0.50, 0.40, 0.45, 0.40, "#2E5A60", 0.10)
    K.bg_ink(P_, [(0.02, 0.06, 0.26, 0.18, 0.2), (0.98, 0.08, 0.24, 0.18, -0.4), (0.02, 0.96, 0.26, 0.18, -0.2)], 0.45)


# ====================================================================== 折纸


@scene("zhezhi", name="折纸", samples=128, grade=dict(WARM_GRADE, exposure=1.02, bloom=0.30))
def build_zhezhi(draft):
    """折纸：一张旧木桌，一双手正捏着一只快折好的纸鹤（左手捏住鹤身、右手拉起一边翅尖），桌上散着几张方纸、
    一张折了一半；左后方一盏小油灯给出暖光。"""
    from mathutils import Euler, Vector  # noqa: PLC0415

    K.set_world(lin("#0A0806"), 1.0)
    rng = np.random.default_rng(57)
    make_obj("Table", K.box_build(2.4, 1.6, 0.04), P.mat_wood_plain("Wood", color=(0.12, 0.075, 0.045), rough=0.55,
                                                                    grain_scale=(0.4, 14.0, 14.0)), loc=(0, 0.3, -0.02), index=0,
             smooth=False)
    paper = P.mat_paper_plain("Paper", color=(0.86, 0.83, 0.74))
    tinted = [P.mat_paper_plain("PaperR", color=(0.70, 0.20, 0.14)), P.mat_paper_plain("PaperB", color=(0.32, 0.42, 0.58)), paper]
    for k, (x, y, rz, m_) in enumerate(((-0.30, 0.20, 0.3, 0), (0.30, 0.28, -0.4, 2), (-0.12, 0.40, 0.9, 1), (0.42, -0.02, 0.15, 2),
                                         (-0.42, -0.05, -0.6, 2))):
        make_obj(f"Sheet{k}", K.box_build(0.15, 0.15, 0.0008), tinted[m_], loc=(x, y, 0.0005 + 0.0009 * k), rot=(0, 0, rz), index=1,
                 smooth=False)
    # 纸鹤（捏在两手之间，离桌面一点）
    crane = make_obj("Crane", P.crane_build(wing_up=0.06, wing_sweep=0.0, neck_up=0.16, tail_up=0.16, scale=0.42), P.mat_crane_paper("CraneP"),
                     smooth=False, loc=(0.0, 0.05, 0.065), index=2)
    crane.rotation_euler = Euler((0.0, 0.0, math.radians(-10)), "XYZ")
    skin = P.mat_skin("Skin", color=(0.56, 0.40, 0.31))
    pinch = {"index": (-4, 40, 35, 20), "middle": (0, 55, 60, 35), "ring": (6, 70, 70, 40), "pinky": (12, 80, 75, 40),
             "thumb": (22, 45, 18, 12)}
    # 右手：从右下伸进来，拇指和食指捏住右翅尖
    hq_r = frame_quat(Vector((0.1, 0.25, -1.0)), Vector((-0.9, 0.35, 0.25)))
    P.hand("HandR", skin, pinch, loc=(0.24, -0.10, 0.10), rot=hq_r.to_euler())
    sleeve("SleeveR", (0.25, -0.11, 0.105), tuple(Vector((0.9, -0.35, -0.10))), r=0.042, L=0.30, flare=1.6)
    # 左手：从左下伸进来，捏住鹤身
    hq_l = frame_quat(Vector((0.1, 0.25, 1.0)), Vector((0.9, 0.35, 0.25)))
    P.hand("HandL", skin, pinch, mirror=True, loc=(-0.22, -0.12, 0.09), rot=hq_l.to_euler())
    sleeve("SleeveL", (-0.23, -0.13, 0.095), tuple(Vector((-0.9, -0.35, -0.10))), r=0.042, L=0.30, flare=1.6)
    lamp, fz = bronze_oil_lamp("Lamp", loc=(-0.55, 0.65, 0.0), scale=0.8, flame=1.4)
    K.point_light("Warm", (-0.4, 0.4, 0.45), 18.0, radius=0.05, color=(1.0, 0.64, 0.32))
    K.area_light("Rim", (0.6, 0.9, 0.5), (0, 0.05, 0.06), 10.0, 0.6, color=(0.55, 0.65, 1.0))
    K.area_light("Fill", (0.2, -1.0, 0.6), (0, 0.05, 0.06), 3.0, 1.0, color=(0.70, 0.75, 0.95))
    K.camera((0.05, -0.62, 0.42), (0.0, 0.08, 0.05), lens=45.0, fstop=3.2, focus=0.72)
    _ = rng
    return {"light": "warm"}


@background("zhezhi")
def bg_zhezhi(P_, h, w, rng, k):
    P_.fill_grad("#0E0B0A", "#0A0808", cloud=0.12)
    K.bg_glow(P_, 0.30, 0.30, 0.40, 0.35, "#6A3A16", 0.28)
    K.bg_ink(P_, [(0.98, 0.06, 0.26, 0.18, -0.4), (0.02, 0.96, 0.30, 0.20, 0.2)], 0.45)
