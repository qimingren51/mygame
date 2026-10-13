"""灯笼头：主角灯杖杖头挂的三盏灯（红纸灯、铜镜灯、霜瓷灯），可以互换（docs/GAMEPLAY.md 11.4 节）。

每盏灯都挂在自己的枢轴（empty）下，枢轴是右臂 ArmR 的子物体、放在杖头；主角的姿态只转枢轴，
所以几盏灯的摆动、死亡时落地、灯芯熄灭都一样。约定（三盏灯共用）：
  - 枢轴原点 = 杖头挂绳的上端；灯芯中心在枢轴下方 C_Z 处（和原来的红纸灯一样），主角的 lantern 挂点就是它；
  - 灯芯是发光材质（pass_index=1），出图时从同一次渲染得到 _emit 发光层；
  - 灯身大小相近（宽约 0.24 米、高约 0.3 米），下面挂一件随风摆的小饰物（符纸 / 小铜剑 / 穗子）。

  red    红纸灯：原来的灯笼原样搬过来（朱砂纸壳、墨色上下盖、藤黄符纸、朱砂穗），一个顶点都没改。
  mirror 铜镜灯：六角铜框、淡纸灯屏，屏上开圆窗露出白金色灯芯；灯后（朝主角一侧）立一面圆铜镜，
         正面磨亮（淡藤黄），从正面看像灯芯背后的一轮光；从背后看是带镜钮的铜镜背。“铜镜聚光”。
         顶上铜钮，下面挂一柄小铜剑（剑修）。
  frost  霜瓷灯：青白瓷的灯罩，正面一圈冰裂纹镂空（冰裂格子里透出冰蓝灯芯），盖沿一圈霜花冰凌，淡蓝穗子。

颜色：铜 = 赭石（亮面、受光的边）+ 石绿铜锈（暗面）；瓷 = 偏冷的纸白，暗面花青。
调色板外的颜色（霜瓷、霜蓝穗子、两种灯芯）由 palette_extra() 给出，写进叠层素材的 meta。
"""

from __future__ import annotations

import math
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

import bmesh
import bpy
from mathutils import Matrix, Vector

ART = Path(__file__).resolve().parents[1]
for p in (ART, ART / "models"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
from style import bstyle as B  # noqa: E402
from style import style as S  # noqa: E402
import kit as K  # noqa: E402

LAMP_IDS = ("red", "mirror", "frost")
LAMPS_RON = ART.parent / "assets" / "data" / "lamps.ron"

# ---------------------------------------------------------------- 共用尺寸（米，相对枢轴）
CORD = 0.10  # 红纸灯挂绳长
SH_H, SH_R = 0.150, 0.118  # 红纸灯纸壳半高、半径
C_Z = -CORD - 0.026 - SH_H  # 灯芯中心（三盏灯相同）
CORE_SCALE = (0.086, 0.086, 0.114)  # 灯芯椭球半径
DROP_CENTER_Z = 0.118  # 死亡时灯笼落地：灯芯中心离地高度（三盏灯相同，lantern 挂点才对得上）

# ---------------------------------------------------------------- 颜色
I, A, W = S.INK, S.ACCENT, S.WASH
CORE_HEX = {"red": S.LANTERN_LIGHT, "mirror": "#FFE9B0", "frost": "#9FD4FF"}  # 灯芯（白天图里的颜色）
QB_LIT = S.mix(S.PAPER, S.SOUL_LIGHT, 0.30)  # 青白瓷亮面：偏冷的纸白
QB_MID = S.mix(QB_LIT, A["huaqing"], 0.30)  # 青白瓷中间调
FROST_BLUE = S.mix(A["huaqing"], S.SOUL_LIGHT, 0.5)  # 霜蓝（穗子）
BRONZE_RAMP = [A["zheshi"], S.shade_ramp(A["zheshi"])[2], S.shade_ramp(A["shilv"])[2]]  # 亮赭石 / 暗赭 / 铜锈绿
POLISH_RAMP = [W["tenghuang"], A["tenghuang"], A["zheshi"]]  # 磨亮的镜面
PORCELAIN_RAMP = [QB_LIT, QB_MID, W["huaqing"]]
ICE_RAMP = [S.SOUL_LIGHT, QB_LIT, QB_MID]


def palette_extra(lamp: str) -> list[str]:
    """该灯叠层用到的、不在 style.full_palette() 里的颜色（灯芯 + 新的填色）。青白瓷、磨亮的镜面、淡纸灯屏这几种
    很亮的颜色附近没有别的调色板色，明暗交界的抗锯齿和纸纹压暗（亮色压暗 10% 就超出容差）吸附不上，
    所以两档之间的过渡色也列进来。"""
    extra = {"red": [], "mirror": [CORE_HEX["mirror"], S.mix(W["tenghuang"], S.shade_ramp(W["tenghuang"])[1], 0.5),
                                   S.mix(S.PAPER, S.PAPER_SHADOW, 0.5)],
             "frost": [CORE_HEX["frost"], QB_LIT, QB_MID, S.mix(QB_LIT, QB_MID, 0.5), S.mix(QB_MID, W["huaqing"], 0.5),
                       *S.shade_ramp(FROST_BLUE)]}[lamp]
    pal = set(S.full_palette()) | {S.LANTERN_LIGHT, S.FLAME_LIGHT, S.SOUL_LIGHT}
    return [c for c in extra if c not in pal]


def lamp_data() -> dict:
    """从 assets/data/lamps.ron 读每盏灯的名字和光色：{id: {"name", "color"}}。"""
    out = {}
    text = LAMPS_RON.read_text(encoding="utf-8") if LAMPS_RON.exists() else ""
    for m in re.finditer(r'\(\s*id:\s*"(\w+)",\s*name:\s*"([^"]+)".*?color:\s*"(#[0-9A-Fa-f]{6})"', text, re.S):
        out[m.group(1)] = {"name": m.group(2), "color": m.group(3).upper()}
    for lid, (name, col) in {"red": ("红纸灯", "#FF9A4A"), "mirror": ("铜镜灯", "#F0E6C8"),
                             "frost": ("霜瓷灯", "#9FD4FF")}.items():
        out.setdefault(lid, {"name": name, "color": col})
    return out


# ================================================================ 材质
def screen_window_material(name: str, shell, radius: float, lattice: tuple[float, float, float] | None = None,
                           jitter: float = 0.010, bar_hex: str | None = None):
    """灯屏：以灯芯为圆心、在屏幕上半径 radius（米）以内的部分透明，露出灯芯；其余是灯屏本身的填色。
    和 bstyle.window_material（按朝向开窗）不同，这里按“离灯芯视线的距离”开窗，所以平面的六角灯屏也只开一个
    圆窗，窗口永远在灯芯正前方、比灯芯小，透过去只看得到灯芯。要求物体原点就是灯芯中心、不缩放。
    lattice=(格子密度, 格条宽, 格条不透明度)：窗里再留一层冰裂纹格条（Voronoi 到边距离小于格条宽的地方）。
    格条不透明度 < 0.5 时，物体编号通道（pass_alpha_threshold=0.5）透过格条看到灯芯，发光遮罩仍是整个圆窗
    （重心不受随机格子影响），格条只在颜色上显出来（白天、夜里的发光层里都有）。bar_hex：窗里格条的颜色
    （默认同灯屏；灯屏太亮时和灯芯分不开，给深一点的颜色）。"""
    m = shell.copy()
    m.name = name
    nt = m.node_tree
    N, L = nt.nodes, nt.links
    out = next(n for n in N if n.type == "OUTPUT_MATERIAL")
    link = out.inputs["Surface"].links[0]
    src = link.from_socket
    nt.links.remove(link)
    tc = N.new("ShaderNodeTexCoord")
    geo = N.new("ShaderNodeNewGeometry")
    vt = N.new("ShaderNodeVectorTransform")
    vt.vector_type, vt.convert_from, vt.convert_to = "VECTOR", "WORLD", "OBJECT"
    L.new(geo.outputs["Incoming"], vt.inputs["Vector"])
    proj = N.new("ShaderNodeVectorMath"); proj.operation = "PROJECT"
    L.new(tc.outputs["Object"], proj.inputs[0]); L.new(vt.outputs["Vector"], proj.inputs[1])
    rej = N.new("ShaderNodeVectorMath"); rej.operation = "SUBTRACT"
    L.new(tc.outputs["Object"], rej.inputs[0]); L.new(proj.outputs["Vector"], rej.inputs[1])
    ln = N.new("ShaderNodeVectorMath"); ln.operation = "LENGTH"
    L.new(rej.outputs["Vector"], ln.inputs[0])
    nz = N.new("ShaderNodeTexNoise"); nz.inputs["Scale"].default_value = 9.0
    L.new(tc.outputs["Object"], nz.inputs["Vector"])
    jit = N.new("ShaderNodeMath"); jit.operation = "MULTIPLY_ADD"
    jit.inputs[1].default_value = 2 * jitter; jit.inputs[2].default_value = -jitter
    L.new(nz.outputs["Fac"], jit.inputs[0])
    r = N.new("ShaderNodeMath"); r.operation = "ADD"
    L.new(ln.outputs["Value"], r.inputs[0]); L.new(jit.outputs["Value"], r.inputs[1])
    inside = N.new("ShaderNodeMath"); inside.operation = "LESS_THAN"; inside.inputs[1].default_value = radius
    L.new(r.outputs["Value"], inside.inputs[0])
    fac = inside.outputs["Value"]
    color = src
    if lattice:
        density, bar, bar_alpha = lattice
        vo = N.new("ShaderNodeTexVoronoi")
        vo.voronoi_dimensions = "3D"
        vo.feature = "DISTANCE_TO_EDGE"
        vo.inputs["Scale"].default_value = density
        vo.inputs["Randomness"].default_value = 0.9
        L.new(tc.outputs["Object"], vo.inputs["Vector"])
        cell = N.new("ShaderNodeMath"); cell.operation = "GREATER_THAN"; cell.inputs[1].default_value = bar
        L.new(vo.outputs["Distance"], cell.inputs[0])
        open_ = N.new("ShaderNodeMath"); open_.operation = "MULTIPLY_ADD"  # 格子 1，格条 1-不透明度
        open_.inputs[1].default_value = bar_alpha; open_.inputs[2].default_value = 1.0 - bar_alpha
        L.new(cell.outputs["Value"], open_.inputs[0])
        both = N.new("ShaderNodeMath"); both.operation = "MULTIPLY"
        L.new(fac, both.inputs[0]); L.new(open_.outputs["Value"], both.inputs[1])
        if bar_hex:  # 窗内的格条换色：窗内且不是格子的地方
            bar_here = N.new("ShaderNodeMath"); bar_here.operation = "SUBTRACT"
            L.new(fac, bar_here.inputs[0]); L.new(cell.outputs["Value"], bar_here.inputs[1])
            clamp = N.new("ShaderNodeMath"); clamp.operation = "MAXIMUM"; clamp.inputs[1].default_value = 0.0
            L.new(bar_here.outputs["Value"], clamp.inputs[0])
            bar_emi = N.new("ShaderNodeEmission")
            bar_emi.inputs["Color"].default_value = B.hex_lin(bar_hex)
            cmix = N.new("ShaderNodeMixShader")
            L.new(clamp.outputs["Value"], cmix.inputs["Fac"])
            L.new(src, cmix.inputs[1]); L.new(bar_emi.outputs["Emission"], cmix.inputs[2])
            color = cmix.outputs["Shader"]
        fac = both.outputs["Value"]
    tr = N.new("ShaderNodeBsdfTransparent")
    mix = N.new("ShaderNodeMixShader")
    L.new(fac, mix.inputs["Fac"])
    L.new(color, mix.inputs[1])
    L.new(tr.outputs["BSDF"], mix.inputs[2])
    L.new(mix.outputs["Shader"], out.inputs["Surface"])
    return m


def radial_rim(mat, r0: float, r1: float, amount: float):
    """假卡通材质的明暗点积再加一项：离物体原点 r0→r1 米之间线性加到 amount（镜面边缘受光提亮）。"""
    nt = mat.node_tree
    N, L = nt.nodes, nt.links
    wash = N["ToonBias"]  # bstyle.toon_material 里“晕染 + 偏置”那个节点
    tc = N.new("ShaderNodeTexCoord")
    ln = N.new("ShaderNodeVectorMath"); ln.operation = "LENGTH"
    L.new(tc.outputs["Object"], ln.inputs[0])
    mr = N.new("ShaderNodeMapRange")
    mr.inputs["From Min"].default_value, mr.inputs["From Max"].default_value = r0, r1
    mr.inputs["To Min"].default_value, mr.inputs["To Max"].default_value = 0.0, amount
    L.new(ln.outputs["Value"], mr.inputs["Value"])
    add = N.new("ShaderNodeMath"); add.operation = "ADD"
    add.inputs[1].default_value = wash.inputs[2].default_value
    L.new(mr.outputs["Result"], add.inputs[0])
    L.new(add.outputs["Value"], wash.inputs[2])
    return mat


# ================================================================ 灯笼头
@dataclass
class Head:
    """一盏灯的灯笼头。pivot 下的全部网格物体就是这盏灯（出图时整体显示/隐藏）。"""
    lamp: str
    pivot: object
    core_mat: object
    animate: object = None  # animate(phase, wind)：每帧重建/摆动飘动的小饰物
    drop: dict = field(default_factory=dict)  # 死亡落地：{"axis": "X"/"Y", "roll": f(frame)→度}

    def objects(self) -> list:
        return [o for o in self.pivot.children_recursive if o.type == "MESH"]

    def set_core(self, k: float) -> None:
        emi = next(n for n in self.core_mat.node_tree.nodes if n.type == "EMISSION")
        emi.inputs["Strength"].default_value = k


def build_head(lamp: str, parent, loc, M: dict, pivot_name: str | None = None) -> Head:
    """在 parent 下 loc 处建一盏灯。M 是主角的材质表（共用 cap/gold/tassel，与主角身上的同名部件一致）。"""
    lp = B.empty(pivot_name or f"LanternPivot_{lamp}", parent, loc=loc)
    return {"red": _build_red, "mirror": _build_mirror, "frost": _build_frost}[lamp](lp, M)


# ---------------------------------------------------------------- 红纸灯（原样搬自 hero.py）
TALISMAN_W, TALISMAN_LEN = 0.072, 0.26
TALISMAN_SIDE = Vector((math.cos(math.radians(-35)), math.sin(math.radians(-35)), 0))


def _talisman_points(top, phase, wind, n=7):
    pts = []
    for i in range(n):
        t = i / (n - 1)
        sway = (0.02 + 0.035 * wind) * t * t * math.sin(phase - 2.2 * t)
        back = (0.01 + 0.06 * wind) * t * t
        pts.append(Vector(top) + Vector((sway, back - 0.004 * i, -TALISMAN_LEN * t)))
    return pts


def _talisman_build(top, phase, wind):
    return K.strip_build(_talisman_points(top, phase, wind), TALISMAN_W, 0.006,
                         twist=math.radians(60) + 0.25 * math.sin(phase), side_hint=TALISMAN_SIDE, taper=(1.0, 0.92))


def _talisman_mark_build(top, phase, wind):
    pts = _talisman_points(top, phase, wind)
    seg = pts[2:5]
    n = (seg[-1] - seg[0]).normalized().cross(TALISMAN_SIDE).normalized()
    if n.y > 0:
        n = -n
    seg = [p + n * 0.006 for p in seg]
    return K.strip_build(seg, TALISMAN_W * 0.35, 0.004, twist=math.radians(30), side_hint=TALISMAN_SIDE,
                         taper=(1.0, 1.0))


def _build_red(lp, M) -> Head:
    T = B.toon_material
    shell = T("LanternShell", A["zhusha"], edge=0.25, seed=14.0)
    seal = B.flat_material("TalismanMark", A["zhusha"])
    core = B.emissive_material("LanternCore", CORE_HEX["red"], 1.0)
    window = B.window_material("LanternWindow", shell, open_facing=0.25)
    obj = B.mesh_object
    cord, sh_h, sh_r, c_z = CORD, SH_H, SH_R, C_Z
    obj("LanternCord", B.cylinder(0.005, 0.005, cord, 6), M["cap"], "none", lp, loc=(0, 0, -cord / 2))
    obj("LanternCapTop", B.cylinder(0.070, 0.060, 0.036, 16), M["cap"], "inner", lp, loc=(0, 0, -cord - 0.014))
    obj("LanternShell", B.lathe([(0.0, -sh_h), (0.066, -0.138), (0.102, -0.096), (sh_r, -0.036), (sh_r, 0.036),
                                 (0.102, 0.096), (0.066, 0.138), (0.0, sh_h)], 24,
                                radial=lambda th, z: 1 + 0.035 * abs(math.sin(4 * th))),
        window, "outer", lp, loc=(0, 0, c_z), sharp_deg=0)
    obj("LanternCore", B.uv_sphere(1.0, 16, 10, scale=CORE_SCALE), core, "none", lp, loc=(0, 0, c_z))
    obj("LanternCapBot", B.cylinder(0.060, 0.067, 0.030, 16), M["cap"], "inner", lp, loc=(0, 0, c_z - sh_h - 0.005))
    ttop = Vector((0.0, -0.06, c_z - sh_h - 0.014))
    tal = obj("Talisman", _talisman_build(ttop, 0.0, 0.0), M["gold"], "thin", lp)
    mark = obj("TalismanMark", _talisman_mark_build(ttop, 0.0, 0.0), seal, "none", lp)
    obj("LanternTassel", B.cylinder(0.009, 0.028, 0.11, 8), M["tassel"], "none", lp,
        loc=(0.024, 0.03, c_z - sh_h - 0.07))

    def animate(phase, wind):
        K.replace_mesh(tal, _talisman_build(ttop, phase, wind))
        K.replace_mesh(mark, _talisman_mark_build(ttop, phase, wind))

    return Head("red", lp, core, animate, {"axis": "Y", "roll": lambda f: 80 + 6 * (f - 3)})


# ---------------------------------------------------------------- 铜镜灯
MB_R = 0.100  # 六角灯身外接圆半径
MB_H = 0.125  # 灯身半高
MB_Z = 0.020  # 灯身中心比灯芯高这么多：俯视 30° 时正面的上铜箍正好让开圆窗（不然挡住窗的上缘，发光重心偏下）
MIRROR_R, MIRROR_Y, MIRROR_DZ = 0.180, 0.118, -0.025  # 铜镜半径、离灯芯的距离（朝主角一侧，+Y）、略低于灯芯


def _sword_pendant(prefix, parent, mat_blade, mat_cord):
    """小铜剑坠：剑尖朝下，总长约 0.17 米。parent 原点 = 挂点。"""
    obj = B.mesh_object
    obj(f"{prefix}Cord", B.cylinder(0.0045, 0.0045, 0.040, 6), mat_cord, "none", parent, loc=(0, 0, -0.020))
    obj(f"{prefix}Ring", B.uv_sphere(1.0, 10, 6, scale=(0.012, 0.006, 0.012)), mat_blade, "thin", parent,
        loc=(0, 0, -0.046))
    obj(f"{prefix}Grip", B.cylinder(0.0075, 0.0075, 0.034, 8), mat_blade, "thin", parent, loc=(0, 0, -0.072))
    obj(f"{prefix}Guard", B.uv_sphere(1.0, 10, 6, scale=(0.030, 0.010, 0.008)), mat_blade, "thin", parent,
        loc=(0, 0, -0.092))

    def blade(bm):  # 菱形截面的剑身：上宽下尖
        rows = []
        for z, w in ((-0.095, 0.016), (-0.120, 0.018), (-0.200, 0.014), (-0.228, 0.0)):
            if w <= 0:
                rows.append([bm.verts.new((0, 0, z))])
                continue
            rows.append([bm.verts.new((x, y, z)) for x, y in ((w, 0), (0, -0.006), (-w, 0), (0, 0.006))])
        for a, b in zip(rows, rows[1:]):
            if len(b) == 1:
                for i in range(4):
                    bm.faces.new((a[i], a[(i + 1) % 4], b[0]))
            else:
                for i in range(4):
                    bm.faces.new((a[i], a[(i + 1) % 4], b[(i + 1) % 4], b[i]))
        bm.faces.new(list(reversed(rows[0])))
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)

    obj(f"{prefix}Blade", blade, mat_blade, "thin", parent, smooth=False)


def _build_mirror(lp, M) -> Head:
    T = B.toon_material
    bronze = T("MirrorBronze", ramp=BRONZE_RAMP, edge=-0.45, seed=31.0)  # 积墨反过来：轮廓处提亮，金属的亮边
    polish = radial_rim(T("MirrorPolish", ramp=POLISH_RAMP, wash=0.10, edge=0.0, bias=-0.15, seed=32.0),
                        MIRROR_R * 0.45, MIRROR_R * 0.85, 0.75)  # 镜心铜黄、镜缘受光发亮
    paper = T("MirrorPaper", ramp=[S.PAPER, S.PAPER_SHADOW, I["qing"]], edge=0.2, seed=33.0)
    blade = T("MirrorSword", ramp=[A["tenghuang"], A["zheshi"], S.shade_ramp(A["zheshi"])[1]], edge=-0.3, seed=34.0)
    core = B.emissive_material("MirrorCore", CORE_HEX["mirror"], 1.0)
    window = screen_window_material("MirrorWindow", paper, radius=0.070)
    obj = B.mesh_object
    c = Vector((0, 0, C_Z + MB_Z))  # 灯身中心
    roof_top = MB_H + 0.057
    obj("MirrorCord", B.cylinder(0.005, 0.005, -(C_Z + MB_Z + roof_top + 0.03), 6), M["cap"], "none", lp,
        loc=(0, 0, (C_Z + MB_Z + roof_top + 0.03) / 2))
    # 灯身：六角灯屏（lathe 6 段：顶点在 0°、60°……，面心在 90°、270°，一面正对 -Y；平面着色，六条棱是折痕线）
    # + 上下铜箍 + 六根铜柱
    # 灯屏的原点必须在灯芯中心（圆窗按离灯芯视线的距离开），所以几何整体上移 MB_Z、原点不动
    obj("MirrorPanels", B.lathe([(r, z + MB_Z) for r, z in ((0.0, -MB_H), (MB_R - 0.008, -MB_H), (MB_R, -MB_H + 0.012),
                                                            (MB_R, MB_H - 0.012), (MB_R - 0.008, MB_H), (0.0, MB_H))], 6),
        window, "outer", lp, loc=(0, 0, C_Z), smooth=False)
    obj("MirrorCore", B.uv_sphere(1.0, 16, 10, scale=CORE_SCALE), core, "none", lp, loc=(0, 0, C_Z))
    for nm, z in (("MirrorRimTop", MB_H - 0.004), ("MirrorRimBot", -MB_H + 0.004)):
        obj(nm, B.lathe([(MB_R - 0.004, z - 0.014), (MB_R + 0.010, z - 0.011), (MB_R + 0.010, z + 0.011),
                         (MB_R - 0.004, z + 0.014)], 6, cap_top=False, cap_bottom=False),
            bronze, "inner", lp, loc=c, smooth=False)
    for i in range(6):
        a = math.radians(60 * i)
        K.limb(f"MirrorPost{i}", c + Vector((math.cos(a), math.sin(a), 0)) * (MB_R + 0.004) + Vector((0, 0, -MB_H + 0.01)),
               c + Vector((math.cos(a), math.sin(a), 0)) * (MB_R + 0.004) + Vector((0, 0, MB_H - 0.01)),
               0.009, 0.009, bronze, "thin", lp, segs=6)
    # 六角铜顶（檐口略外挑）+ 铜钮
    obj("MirrorRoof", B.lathe([(MB_R + 0.024, MB_H + 0.004), (MB_R + 0.028, MB_H + 0.014), (0.086, MB_H + 0.032),
                               (0.040, roof_top - 0.006), (0.0, roof_top)], 6),
        bronze, "inner", lp, loc=c, smooth=False)
    obj("MirrorKnobNeck", B.cylinder(0.012, 0.016, 0.016, 10), bronze, "inner", lp, loc=c + Vector((0, 0, roof_top + 0.006)))
    obj("MirrorKnob", B.uv_sphere(1.0, 12, 8, scale=(0.024, 0.024, 0.021)), bronze, "inner", lp,
        loc=c + Vector((0, 0, roof_top + 0.030)))
    obj("MirrorBase", B.lathe([(0.0, -MB_H - 0.026), (0.050, -MB_H - 0.026), (MB_R + 0.012, -MB_H - 0.008),
                               (MB_R + 0.012, -MB_H)], 6),
        bronze, "inner", lp, loc=c, smooth=False)
    # 圆铜镜：立在灯后（+Y，朝主角），正面磨亮朝前；背面铜锈，中间镜钮
    rot = (math.radians(90), 0, 0)  # 圆柱轴 Z → -Y
    mc = c + Vector((0, MIRROR_Y, MIRROR_DZ))
    obj("MirrorDisc", B.cylinder(MIRROR_R, MIRROR_R, 0.014, 40), bronze, "outer", lp, loc=mc, rot=rot, sharp_deg=30)
    obj("MirrorFace", B.cylinder(MIRROR_R - 0.014, MIRROR_R - 0.014, 0.004, 40), polish, "none", lp,
        loc=mc + Vector((0, -0.008, 0)), rot=rot)
    obj("MirrorBackKnob", B.uv_sphere(1.0, 12, 8, scale=(0.036, 0.020, 0.036)), blade, "inner", lp,
        loc=mc + Vector((0, 0.011, 0)))  # 镜钮：手摸得发亮
    # 小铜剑坠
    pend = B.empty("MirrorPendant", lp, loc=c + Vector((0, 0, -MB_H - 0.026)))
    _sword_pendant("MirrorSword", pend, blade, M["cap"])

    def animate(phase, wind):
        pend.rotation_euler = (math.atan(0.05 + 0.30 * wind) + 0.06 * math.sin(phase - 1.0),
                               (0.08 + 0.12 * wind) * math.sin(phase), 0)

    return Head("mirror", lp, core, animate, {"axis": "X", "roll": lambda f: -84 - 3 * (f - 3)})


# ---------------------------------------------------------------- 霜瓷灯
# 罐形：肩宽、下收（和红纸灯上下对称的椭圆拉开）
FROST_PROFILE = [(0.0, -0.150), (0.050, -0.148), (0.075, -0.130), (0.095, -0.090), (0.112, -0.030), (0.121, 0.030),
                 (0.117, 0.075), (0.099, 0.108), (0.070, 0.126), (0.0, 0.130)]


def _crystal_build(length, width):
    """一根冰凌：细长的四棱双锥，沿 +Z，根部在原点。"""
    def build(bm):
        tip = bm.verts.new((0, 0, length))
        root = bm.verts.new((0, 0, -0.006))
        mid = [bm.verts.new((width * math.cos(a), width * math.sin(a), length * 0.30))
               for a in (0.0, math.pi / 2, math.pi, 1.5 * math.pi)]
        for i in range(4):
            bm.faces.new((mid[i], mid[(i + 1) % 4], tip))
            bm.faces.new((mid[(i + 1) % 4], mid[i], root))
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    return build


def _build_frost(lp, M) -> Head:
    T = B.toon_material
    porcelain = T("FrostPorcelain", ramp=PORCELAIN_RAMP, edge=0.3, seed=41.0)
    ice = T("FrostIce", ramp=ICE_RAMP, wash=0.1, edge=-0.3, seed=42.0)
    blue = T("FrostTassel", FROST_BLUE, edge=0.3, seed=43.0)
    core = B.emissive_material("FrostCore", CORE_HEX["frost"], 1.0)
    window = screen_window_material("FrostWindow", porcelain, radius=0.080, lattice=(17.0, 0.11, 0.45),
                                    bar_hex=W["huaqing"])
    obj = B.mesh_object
    c = Vector((0, 0, C_Z))
    lid_top = 0.184
    obj("FrostCord", B.cylinder(0.005, 0.005, -(C_Z + lid_top + 0.03), 6), M["cap"], "none", lp,
        loc=(0, 0, (C_Z + lid_top + 0.03) / 2))
    obj("FrostShell", B.lathe(FROST_PROFILE, 24), window, "outer", lp, loc=c, sharp_deg=0)
    obj("FrostCore", B.uv_sphere(1.0, 16, 10, scale=CORE_SCALE), core, "none", lp, loc=c)
    obj("FrostLid", B.lathe([(0.0, 0.126), (0.066, 0.126), (0.088, 0.138), (0.084, 0.150), (0.056, 0.166),
                             (0.022, 0.180), (0.0, lid_top)], 24), porcelain, "inner", lp, loc=c, sharp_deg=50)
    obj("FrostPearl", B.uv_sphere(1.0, 12, 8, scale=(0.020, 0.020, 0.022)), ice, "inner", lp,
        loc=c + Vector((0, 0, lid_top + 0.016)))
    # 盖沿一圈冰凌：长短相间，向外上方斜出
    n = 7
    for i in range(n):
        a = 2 * math.pi * (i + 0.25) / n
        out = Vector((math.cos(a), math.sin(a), 0))
        length = 0.085 if i % 2 == 0 else 0.060
        elev = math.radians(40 if i % 2 == 0 else 24)
        d = (out * math.cos(elev) + Vector((0, 0, math.sin(elev)))).normalized()
        cr = obj(f"FrostCrystal{i}", _crystal_build(length, 0.020 if i % 2 == 0 else 0.016), ice, "thin", lp,
                 loc=c + out * 0.078 + Vector((0, 0, 0.140)), smooth=False)
        cr.rotation_mode = "QUATERNION"
        cr.rotation_quaternion = Vector((0, 0, 1)).rotation_difference(d)
    obj("FrostFoot", B.lathe([(0.0, -0.170), (0.040, -0.170), (0.058, -0.160), (0.050, -0.146), (0.0, -0.146)], 24),
        porcelain, "inner", lp, loc=c, sharp_deg=50)
    tas = B.empty("FrostTasselPivot", lp, loc=c + Vector((0, 0, -0.170)))
    obj("FrostBead", B.uv_sphere(1.0, 10, 6, scale=(0.016, 0.016, 0.016)), ice, "inner", tas, loc=(0, 0, -0.022))
    obj("FrostTassel", B.cylinder(0.008, 0.026, 0.11, 8), blue, "none", tas, loc=(0, 0, -0.092))

    def animate(phase, wind):
        tas.rotation_euler = (math.atan(0.03 + 0.25 * wind) + 0.05 * math.sin(phase - 1.0),
                              (0.06 + 0.10 * wind) * math.sin(phase), 0)

    return Head("frost", lp, core, animate, {"axis": "Y", "roll": lambda f: 80 + 6 * (f - 3)})


# ================================================================ 落地
def drop_head(head: Head, root, frame: int, center: Vector) -> None:
    """死亡时灯笼脱手：灯芯中心放到 center（root 坐标），按灯的落地方式侧躺（直接设世界矩阵）。"""
    roll = math.radians(head.drop["roll"](frame))
    rot = Matrix.Rotation(roll, 4, head.drop["axis"])
    pivot = center - (rot.to_3x3() @ Vector((0, 0, C_Z)))
    head.pivot.matrix_world = root.matrix_world @ (Matrix.Translation(pivot) @ rot)
