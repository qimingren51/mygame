from pathlib import Path
p = Path("art/render/card_passives.py")
s = p.read_text(encoding="utf-8")
# ---- 锐目：去掉旧的倒影贴图和写实眼球材质，换成铜金虹膜 + 真的小铜钱
a = s.index("def dipper_reflection(size=512, span=0.70, center=(0.47, 0.45)):")
b = s.index("def lid_curves(a=0.0132, up=0.0036, lo=0.0032):")
s = s[:a] + '''def mat_iris(name, R=EYE_R, ri=0.0059, rp=0.0032):
    """眼球（物体坐标：光轴 +Z）：虹膜是铜金色的放射纹（深铜 → 亮金，近瞳孔一圈略亮的卷缩轮，外缘一道深色的缘），
    瞳孔放大、纯黑；眼白埋在暗处（灰蓝）；角膜一层清漆，接住月光的高光。不画血丝。"""
    M = K.Mat(name)
    m = M.math
    oc = M.coord("Object")
    sep = M.n("ShaderNodeSeparateXYZ")
    M.l(oc, sep.inputs[0])
    x, y, z = sep.outputs["X"], sep.outputs["Y"], sep.outputs["Z"]
    rxy = m("SQRT", m("ADD", m("MULTIPLY", x, x), m("MULTIPLY", y, y)))
    phi = m("ARCTAN2", y, x)
    front = m("GREATER_THAN", z, 0.0)
    t_ir = m("DIVIDE", m("SUBTRACT", rxy, rp), ri - rp)  # 0 瞳孔边 → 1 虹膜外缘
    # 放射纹：沿角度很密、沿半径拉长；再叠一层更细的
    cp = M.n("ShaderNodeCombineXYZ")
    M.l(m("MULTIPLY", phi, 14.0), cp.inputs["X"])
    M.l(m("MULTIPLY", t_ir, 1.2), cp.inputs["Y"])
    fib = M.noise(cp.outputs[0], scale=3.0, detail=7.0, rough=0.62)
    cp2 = M.n("ShaderNodeCombineXYZ")
    M.l(m("MULTIPLY", phi, 40.0), cp2.inputs["X"])
    M.l(m("MULTIPLY", t_ir, 0.8), cp2.inputs["Y"])
    fib2 = M.noise(cp2.outputs[0], scale=3.0, detail=4.0, rough=0.6)
    f = m("ADD", m("MULTIPLY", fib.outputs["Fac"], 0.6), m("MULTIPLY", fib2.outputs["Fac"], 0.4))
    icol, _ = M.ramp(M.maprange(f, 0.32, 0.68), [(0.0, (0.05, 0.020, 0.007)), (0.45, (0.30, 0.13, 0.035)), (0.8, (0.72, 0.42, 0.11)),
                                                 (1.0, (0.95, 0.70, 0.30))])
    collar = m("MULTIPLY", M.maprange(t_ir, 0.10, 0.28), M.maprange(t_ir, 0.45, 0.28))
    icol = M.mix(m("MULTIPLY", collar, 0.55), icol, (0.85, 0.58, 0.20, 1.0))
    icol = M.mix(M.maprange(t_ir, 0.80, 1.0), icol, (0.012, 0.006, 0.003, 1.0))
    icol = M.mix(M.maprange(t_ir, 0.06, 0.0), icol, (0.02, 0.01, 0.004, 1.0))  # 瞳孔边一圈暗
    in_iris = m("MULTIPLY", front, M.maprange(rxy, ri + 0.0002, ri - 0.0002))
    col = M.mix(in_iris, (0.07, 0.075, 0.085, 1.0), icol)
    in_pupil = m("MULTIPLY", front, M.maprange(rxy, rp + 0.0001, rp - 0.0001))
    col = M.mix(in_pupil, col, (0.0015, 0.0015, 0.0018, 1.0))
    nrm = M.bump(m("MULTIPLY", f, in_iris), strength=0.25, distance=0.0002)
    bsdf = M.principled(Base_Color=col, Roughness=0.42, Coat_Weight=1.0, Coat_Roughness=0.012, Coat_IOR=1.376, Normal=nrm)
    return M.surface(bsdf.outputs[0])


''' + s[b:]
a = s.index('@scene("ruimu", name="锐目"')
b = s.index('@background("ruimu")')
s = s[:a] + '''@scene("ruimu", name="锐目", samples=160, grade=dict(COLD_GRADE, exposure=1.05, bloom=0.40, sat=1.02))
def build_ruimu(draft):
    """锐目：一只眼睛的特写，脸和眼周都埋在暗处（眼睑只是两片暗影，不画皮肤和睫毛），只有一道横的月光照亮眼睛这一条；
    虹膜铜金色的放射纹，瞳孔放大，瞳孔里七枚方孔小铜钱排成北斗，钱面带一点高光。"""
    K.set_world(lin("#04060B"), 1.0)
    eye = make_obj("Eyeball", K.lathe_uv([(EYE_R * math.sin(a), -EYE_R * math.cos(a)) for a in np.linspace(0, math.pi, 96)], segments=128),
                   mat_iris("IrisM"), index=1)
    lid_m = P.mat_stone("LidDark", color=(0.012, 0.010, 0.010), rough=0.9, scale=40.0, bump=0.0)
    lid = make_obj("Lids", eyelid_build(), lid_m, index=1)
    # 瞳孔里的北斗七钱：真的小方孔钱，贴着瞳孔、钱面朝镜头；斗口朝上、斗柄往右
    rp, rc = 0.0032, 0.00047
    pts = np.array(P.DIPPER, float)
    pts = pts - (pts.min(0) + pts.max(0)) / 2
    k = (rp - rc * 1.15) / np.hypot(pts[:, 0], pts[:, 1]).max()
    ang = math.radians(-8)
    rot = np.array([[math.cos(ang), -math.sin(ang)], [math.sin(ang), math.cos(ang)]])
    pts = (pts * k) @ rot.T
    coin_m = P.mat_coin("PupilCoin", gilt=0.7, rough=0.22, emit=((1.0, 0.72, 0.36), 0.9))
    sc = rc / 0.022
    for j, (x, y) in enumerate(pts):
        zc = math.sqrt(max(EYE_R ** 2 - x * x - y * y, 0.0)) + 0.00004
        make_obj(f"Coin{j}", P.coin_build(), coin_m, parent=eye, loc=(x, y, zc), scale=(sc, sc, sc * 0.6), index=2)
    for ob in (eye, lid):  # 光轴 +Z → 世界 -Y（朝镜头），物体 +Y → 世界 +Z（朝上）
        ob.rotation_euler = (math.radians(90), 0, 0)
    # 月光：一道横的长条光，只照亮眼睛这一条；另一盏小的给铜钱点高光
    K.area_light("Key", (-0.05, -0.24, 0.035), (0, 0, 0.001), 0.35, 0.22, size_y=0.010, color=(0.78, 0.88, 1.0))
    K.area_light("Glint", (0.03, -0.20, 0.03), (0, 0, 0.0), 0.05, 0.02, color=(1.0, 0.92, 0.80))
    K.area_light("Rim", (0.10, 0.15, 0.06), (0, 0, 0), 0.03, 0.10, color=(0.55, 0.68, 1.0))
    K.camera((0.002, -0.080, 0.003), (0.0004, 0.0, 0.0006), lens=85.0)
    return {"light": "cold"}


''' + s[b:]
rep = [
('''    make_obj("Table", K.box_build(2.4, 1.6, 0.04), P.mat_wood_plain("Wood", color=(0.12, 0.075, 0.045), rough=0.55,
                                                                    grain_scale=(0.4, 14.0, 14.0)), loc=(0, 0.3, -0.02), index=0,
             smooth=False)''',
 '''    make_obj("Table", K.box_build(2.4, 1.6, 0.04), K.mat_lacquer("TableLac", color=(0.018, 0.011, 0.009), rough=0.22),
             loc=(0, 0.3, -0.02), index=0, smooth=False)'''),
('''    skin = P.mat_skin("Skin", color=(0.56, 0.40, 0.31))
    pinch = {''', '''    skin = P.mat_skin("Skin", color=(0.54, 0.38, 0.28), rough=0.56, sss=0.45)
    robe = K.mat_cloth("Robe", (0.030, 0.034, 0.052), weave=700.0)
    pinch = {'''),
('''        sleeve(f"Sleeve{side}", tuple(wrist + back * 0.01), tuple(back), r=0.042, L=0.34, flare=1.6)''',
 '''        sleeve(f"Sleeve{side}", tuple(wrist + back * 0.012), tuple(back), r=0.050, L=0.36, flare=2.6, mat=robe)'''),
('''    K.point_light("Warm", (lp.x + 0.15, lp.y - 0.10, 0.45), 22.0, radius=0.25, color=(1.0, 0.64, 0.32))
    K.area_light("Rim", (0.6, 0.9, 0.5), tuple(mid), 10.0, 0.6, color=(0.55, 0.65, 1.0))
    K.area_light("Fill", (0.2, -1.0, 0.8), tuple(mid), 12.0, 1.2, color=(0.80, 0.78, 0.90))
    K.area_light("Top", (mid.x - 0.1, mid.y + 0.1, 0.9), tuple(mid), 6.0, 0.5, color=(1.0, 0.92, 0.80))''',
 '''    K.point_light("Warm", (lp.x + 0.12, lp.y - 0.06, 0.32), 26.0, radius=0.12, color=(1.0, 0.60, 0.28))
    K.area_light("Rim", (0.6, 0.9, 0.5), tuple(mid), 5.0, 0.6, color=(0.55, 0.65, 1.0))
    K.area_light("Fill", (0.2, -1.0, 0.8), tuple(mid), 3.0, 1.2, color=(0.80, 0.74, 0.70))'''),
('''    """折纸：一张旧木桌，一双手从画面两个下角伸进来，正捏着一只快折好的纸鹤的两边翅尖（拇指、食指捏住，往两边轻轻拉开），
    桌上散着几张方纸，一张红的、一张蓝的；后面一盏小油灯给出暖光。按画面位置摆。"""''',
 '''    """折纸：一张黑漆矮几，一双手（宽袖）从画面两个下角伸进来，正捏着一只快折好的纸鹤的两边翅尖（拇指、食指捏住，往两边轻轻拉开），
    几上散着几张方纸，一张红的、一张蓝的；左后一盏小油灯，灯下暖光。按画面位置摆。"""'''),
]
for old, new in rep:
    assert s.count(old) == 1, old[:60]
    s = s.replace(old, new)
p.write_text(s, encoding="utf-8")
print("written")
