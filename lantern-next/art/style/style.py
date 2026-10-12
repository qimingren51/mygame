"""提灯夜行 · 水墨风格的唯一来源。

所有美术脚本（Blender 渲染、后期处理、特效贴图、自检）都从这里取颜色、尺寸、相机和线条参数。
子代理只能引用，不能修改；要改风格请改这一个文件，然后全部素材重渲。

本文件不依赖 bpy，普通 Python（Pillow/numpy 脚本）也能直接 import。
Blender 相关的辅助函数放在 bstyle.py。
"""

from __future__ import annotations

# ---------------------------------------------------------------- 调色板

PAPER = "#EDE4CF"  # 宣纸
PAPER_SHADOW = "#D9CDB1"  # 宣纸上的淡影、纸纹暗部

# 墨分五色：焦、浓、重、淡、清（由深到浅）
INK = {
    "jiao": "#17140F",  # 焦墨：外轮廓、眼眶、最深处
    "nong": "#2E2924",  # 浓墨：内线、深色衣物暗部
    "zhong": "#4F4942",  # 重墨：暗面
    "dan": "#857E73",  # 淡墨：晕染、远景
    "qing": "#BAB2A3",  # 清墨：最淡的渲染
}

# 点缀色（国画颜料）
ACCENT = {
    "zhusha": "#C23A2B",  # 朱砂：灯笼、围巾、印章
    "zheshi": "#A8743F",  # 赭石：斗笠、木杆
    "huaqing": "#3E5A7E",  # 花青：长袍
    "shilv": "#5E8E72",  # 石绿：草叶、青面鬼
    "tenghuang": "#E2B23A",  # 藤黄：灯穗、魂火、金蟾
}

SKIN = "#E9D0AB"  # 皮肤：淡赭

# 夜色与光
NIGHT_AMBIENT = "#161B2C"  # 光照图的底色（游戏里同值）
LANTERN_LIGHT = "#FFC27A"  # 灯笼暖光
FLAME_LIGHT = "#FF9A4D"  # 火焰
SOUL_LIGHT = "#BFEFFF"  # 魂火冷光

# 妖眼颜色（与 src/data/enemies.ts 的 eye 字段一致）
EYE = {
    "shade": "#FF8A5B",
    "wisp": "#9FE3FF",
    "golem": "#FFB46B",
    "fox": "#FF6B5A",
    "ghoul": "#C8FF6B",
    "boss": "#FFD98A",
    "stonelord": "#FFB46B",
    "toad": "#FFF1C2",
}

# 填色分档：亮面 / 中间 / 暗面，与重墨按比例混合。
# 每个基础色只允许出现这三档（加上墨线色），自检按此展开调色板。
SHADE_STEPS = (0.0, 0.28, 0.55)  # 与 INK["zhong"] 的混合比例
SHADE_THRESHOLDS = (0.55, 0.05)  # 光照点积大于第一个值为亮面，大于第二个为中间，否则暗面


def hex_to_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def rgb_to_hex(c: tuple[int, int, int]) -> str:
    return "#%02X%02X%02X" % c


def mix(a: str, b: str, t: float) -> str:
    """按比例 t 把颜色 a 混向 b（sRGB 空间直接插值，和国画调色的直觉一致）。"""
    ca, cb = hex_to_rgb(a), hex_to_rgb(b)
    return rgb_to_hex(tuple(round(x + (y - x) * t) for x, y in zip(ca, cb)))  # type: ignore[arg-type]


def shade_ramp(base: str) -> list[str]:
    """一个基础色的三档填色：亮、中、暗。"""
    return [mix(base, INK["zhong"], t) for t in SHADE_STEPS]


def srgb_to_linear(c: float) -> float:
    """0..1 的 sRGB 分量转线性（Blender 节点里的颜色是线性的）。"""
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def hex_to_linear(h: str) -> tuple[float, float, float]:
    r, g, b = hex_to_rgb(h)
    return srgb_to_linear(r / 255), srgb_to_linear(g / 255), srgb_to_linear(b / 255)


BASE_COLORS = [PAPER, PAPER_SHADOW, SKIN, *INK.values(), *ACCENT.values()]


def full_palette() -> list[str]:
    """自检用的完整调色板：每个基础色的三档 + 墨色 + 宣纸。"""
    out: list[str] = []
    for c in BASE_COLORS:
        for s in shade_ramp(c):
            if s not in out:
                out.append(s)
    for c in INK.values():
        if c not in out:
            out.append(c)
    return out


PALETTE_TOLERANCE = 18  # 自检时允许的 RGB 欧氏距离（叠纸纹和墨线晕染之后）

# ---------------------------------------------------------------- 尺寸

PX_PER_UNIT = 2  # 最终贴图像素 / 游戏世界单位（游戏里同值）
RENDER_SCALE = 4  # 先放大 4 倍渲染，后期再缩小
ANCHOR = (0.5, 0.875)  # 脚底锚点（相对帧宽高）；游戏里 Sprite 的 anchor 与此一致

# 每类素材的最终帧尺寸（像素，正方形）
FRAME = {
    "hero": 128,
    "small": 80,  # 影妖、疾影、金蟾
    "golem": 112,
    "elite": 160,  # 赤面狐、青面鬼、石将
    "boss": 320,
    "prop": 96,  # 宝箱、祭坛等
}

# Blender 建模尺度：1 米 = 25 个世界单位 = 50 个最终像素
WORLD_UNITS_PER_M = 25.0
PX_PER_M = WORLD_UNITS_PER_M * PX_PER_UNIT  # 50

# 主角身高（脚底到斗笠尖）约 1.75 米，屏幕上约 76 像素（含俯角缩短）
HERO_HEIGHT_M = 1.75
# 自检：同一素材各帧身高与目标的允许偏差
HEIGHT_TOLERANCE = 0.04
# 自检：同一动画里脚底位置的允许偏差（最终像素）
FOOT_TOLERANCE_PX = 1.0

# ---------------------------------------------------------------- 相机与灯光

# 正交相机，俯角 30°（视线与地面夹 30°）。相机固定，转模型得到各个朝向。
CAMERA_PITCH_DEG = 30.0
# 正交相机的取景宽度（米）= 帧像素 / PX_PER_M
def ortho_scale(frame_px: int) -> float:
    return frame_px / PX_PER_M


# 主光方向（世界坐标，从物体指向光源），固定不随模型转：左上偏前。
# 相机在 -Y 侧、朝 +Y 看，所以“前”是 -Y，“左”是 -X。
KEY_LIGHT_DIR = (-0.55, -0.45, 0.70)

# 朝向约定（游戏里同值）：屏幕坐标 y 向下，0=东 1=东南 2=南 3=西南 4=西 5=西北 6=北 7=东北。
# 南 = 朝向镜头（世界 -Y），东 = 屏幕右（世界 +X），北 = 背对镜头（世界 +Y）。
# 模型建模时面朝 -Y（正视图里正对观众），角色的右手在世界 -X 一侧。
DIRS = ("E", "SE", "S", "SW", "W", "NW", "N", "NE")


def dir_rotation_deg(d: int) -> float:
    """朝向 d 时模型绕 Z 轴的旋转角（度）。模型默认面朝 -Y，即 d=2（南）时为 0。"""
    return 90.0 - d * 45.0


# ---------------------------------------------------------------- 线条

LINE_COLOR = INK["jiao"]
# 最终像素下的线宽；渲染时乘以 RENDER_SCALE
LINE_OUTER_PX = 2.6  # 外轮廓
LINE_INNER_PX = 1.1  # 内线（折痕、材质分界）
LINE_NOISE_SEED = 7  # 噪点修饰器固定种子，避免逐帧抖动
LINE_NOISE_AMPLITUDE_PX = 0.6
LINE_NOISE_PERIOD_PX = 18.0
LINE_TAPER = 0.35  # 首尾收笔：两端线宽缩到这个比例

# ---------------------------------------------------------------- 渲染

SAMPLES = 16  # 自发光材质没有噪点问题，16 个采样就够
SAMPLES_PREVIEW = 4

# ---------------------------------------------------------------- 后期

INK_BLEED_PX = 0.6  # 墨线晕染（最终像素下的高斯半径）
PAPER_OVERLAY = 0.10  # 纸纹叠加强度（正片叠底）
ALPHA_BLEED_PX = 4  # 往透明区域扩展颜色的距离，避免缩放出现黑边/白边

# ---------------------------------------------------------------- 输出约定
#
# 每个素材输出到 art/out/assets/<素材名>/：
#   <动画>_<朝向>_<帧号两位>.png      最终 RGBA，尺寸为 FRAME[类别]，锚点为 ANCHOR
#   <动画>_<朝向>_<帧号两位>_flash.png 白色剪影帧（只有妖物需要）
#   meta.json:
#     {
#       "name": "hero", "size": [128, 128], "anchor": [0.5, 0.875],
#       "anims": {"idle": {"frames": 6, "fps": 8, "dirs": ["E", ...]},
#                 "walk": {"frames": 8, "fps": 12, "dirs": [...], "stride_units": 26}},
#       "sockets": {"lantern": {"idle": {"E": [[x, y], ...每帧], ...}}}
#     }
#   挂点坐标单位是最终像素，相对锚点（脚底），x 向右、y 向下。
#   只画一个方向的素材（妖物）朝向写 "E"，游戏里镜像得到西。
