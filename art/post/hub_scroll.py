#!/usr/bin/env python3
"""提灯夜行 · 灯驿长卷（只出桌面版；Pillow + numpy，不用 Blender）。

docs/GAMEPLAY.md 11.6：一张水墨长卷，灯驿的夜景。画里四个人物（老灯匠、货郎、灯童、说书人），点亮的心灯在画里
变成一盏盏亮起的灯，通关的地区远山上露出一点晨光。长夜里的画只有墨色（docs/LORE.md 第 8 节），
暗处只有灯、火和一点月色的薄雾在亮（docs/FEEL.md 1.2）。

构图（1920×1080）：
  天上   墨色夜空，月亮留白（烘云托月），左上一条安静的天留给标题。
  远山   六个地区各一座：常羊（西，左）、章尾山（最远、最淡、最高，偏左，在后面）、北冥、幽都（山口里一座黑城）、
         丹穴、青丘（东，右）。山脚隐进雾里。
  中景   最后一座灯驿：一道白墙（墙上是灯童刻的一道道痕），门楼挂“灯驿”匾额，门开着，门外的路伸进雾里；
         右边一座厅，檐下说书人的桌子，旁边一架更鼓，门楼和厅之间一座漏刻。院子偏左一棵老树就是灯树，枝上挂 12 盏纸灯。
  人物   从左到右：老灯匠（树下的案子前糊灯，案头一盏油灯）、货郎（挑着担子，担头一盏小红灯，手摇拨浪鼓；
         灯把他的影子投在墙上，影子里有条狐狸尾巴）、灯童（坐在门槛上，牵着一盏兔子灯，望着门外的路）、
         说书人（檐下桌边，举着折扇，桌上醒木、残书、一支蜡烛）。四个人的灯在底图里一直亮着，照出各自的人。
  地面   院子、石板，最下面一条安静的地，留给提示文字；右下角一方朱砂印“灯驿”。

输出（art/out/screens/hub/，格式见 hub.json 的 note）：
  hub.png                      底图，不透明 RGB。心灯全部没点亮（纸灯留白、墨线勾边、不发光）。
  lamp_<id>.png                心灯点亮后的灯身（纸透出光），普通混合，不含火苗。
  lamp_<id>_flame.png          火苗（普通混合，火舌尖带一点焦墨），base = 火苗底部中点。
  lamp_<id>_core.png           内圈光，叠加（RGB × alpha 加到画面上）。
  lamp_<id>_glow.png           外圈光晕，叠加，照到旁边的枝和纸。
  dawn_<region>.png            那个地区的山脊和山后的天上一点晨光（暖桃色），普通混合。
  dawn_<region>_mask.png       同尺寸的灰度“先亮哪里”：黑 = 最先亮（山脊、天边），白 = 最后。边上带纸纤维的毛。
  dawn_<region>_glow.png       山脊上一线金光，叠加。
  hub.json                     各层的 rect、人物的点击区 / 名字位置 / 聚光、文字安全区。
  心灯的 id 按文件顺序从 assets/data/meta.ron 读。

合成顺序（游戏和审图一样）：底图 → 灯身 → 火苗（普通）→ 内圈 + 外圈（叠加）→ 晨光（普通）→ 晨光金线（叠加）。

画法尽量复用 title_screen.py 和 scroll_qingqiu.py（只 import）：Painting 的笔墨工具、ridge_line、mountain_layer、
mountain_texture、wash_blob、curve_pts、stroke_cover、light_map（光池）、bloom、make_seal、roof_poly。

运行（在仓库根目录下）：
    art/.venv/bin/python art/post/hub_scroll.py            # 画 + 全部输出 + 审图 review@2x/hub_review_{states,figures,ui_720}.png（约 1.5 分钟）
    art/.venv/bin/python art/post/hub_scroll.py --sample   # 只出样张（review@2x/hub_sample*.png），不写 screens/hub/
    art/.venv/bin/python art/post/test_hub_scroll.py       # 自检（含确定性：另画两遍逐字节比对，约 4 分钟）
固定随机种子，重复运行结果逐字节相同。
"""

from __future__ import annotations

import os

os.environ["LANTERN_ART_DENSITY"] = "2"  # 只有桌面版：先定密度，再导入 style / vfx_textures

import json  # noqa: E402
import math  # noqa: E402
import re  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402
from pathlib import Path  # noqa: E402

import numpy as np  # noqa: E402
from PIL import Image, ImageDraw, ImageFilter  # noqa: E402

HERE = Path(__file__).resolve().parent
ART = HERE.parent
ROOT = ART.parent
sys.path.insert(0, str(HERE))
import scroll_qingqiu as Q  # noqa: E402
import title_screen as T  # noqa: E402
import vfx_textures as V  # noqa: E402
from ui_fonts import font  # noqa: E402

S = V.S
W, H = T.W, T.H  # 1920×1080：title_screen 的画法函数默认就是这个尺寸
OUT = ART / "out" / "screens" / "hub"
REVIEW = ART / "out" / "review@2x"
META_RON = ROOT / "assets" / "data" / "meta.ron"
SEED = 3160

col, smoothstep, mixc, blur, noise = V.col, V.smoothstep, T.mixc, T.blur, T.noise
PAPER, PAPER_SH = T.PAPER, T.PAPER_SH
JIAO, NONG, ZHONG, DAN, QING = T.JIAO, T.NONG, T.ZHONG, T.DAN, T.QING
WHITE = np.ones(3)
PLASTER = mixc(PAPER, WHITE, 0.18)  # 白墙、灯纸：留白，比纸略亮
SKY = mixc(NONG, ZHONG, 0.45)  # 夜空：纯墨
ZHUSHA, TENG, ZHESHI = col(S.ACCENT["zhusha"]), col(S.ACCENT["tenghuang"]), col(S.ACCENT["zheshi"])
SHILV, HUAQING = col(S.ACCENT["shilv"]), col(S.ACCENT["huaqing"])
LAMP_LIGHT, FLAME_LIGHT = col(S.LANTERN_LIGHT), col(S.FLAME_LIGHT)
ADD_COLOR = col("#FFD98A")  # 叠加层的颜色：暖而不太饱和
DAWN_PEACH = col("#FFD1A8")  # 晨光：与 crates/view/src/atmos.rs 天明的暖桃色同值
DAWN_GOLD = col("#FFE3A6")  # 山脊金线
ADD_PEAK = 0.70  # 叠加层的 alpha 峰值（游戏亮起时会放大到 1.4 倍）
NIGHT_AMB = 0.40  # 长夜光照图的底（灰）：灯边以外的画都沉在这一档

# ---------------------------------------------------------------- 构图（画面像素）
# 游戏按“铺满窗口、居中裁掉多出来的”显示（16:10 剩 x 96–1824，21:9 剩 y 128–952，4:3 剩 x 240–1680）：
# 人物、心灯、匾额、文字安全区都在 SAFE 里，四个人在 x 240–1680 里；画面四边是可以裁掉的天、地、墙。
SAFE = (96, 128, 1728, 824)  # x, y, w, h
MOON = (1530.0, 176.0, 34.0)
TEXT_SAFE = [(110, 140, 470, 64), (200, 904, 1520, 46)]  # x, y, w, h：标题一行（天上）、底部提示（地上）
SEAL_AT, SEAL_PX = (1748, 880), 52
WALL_TOP, WALL_BASE = 560.0, 770.0  # 白墙：墙帽下沿、墙脚
GATE_CX, GATE_EAVE = 1150.0, 520.0  # 门楼中线、檐口
POSTS = (GATE_CX - 107.0, GATE_CX + 107.0)  # 门楼两根柱
WALL_X1 = POSTS[0]  # 左段墙一直到门楼的柱子
DOOR = (GATE_CX - 66.0, GATE_CX + 66.0, 586.0, 768.0)  # 门洞 x0, x1, y0, y1
SILL_Y = 768.0  # 门槛上沿
HALL = (1710.0, 512.0, 560.0, 120.0)  # 厅：屋顶中心 x、檐口 y、宽、屋顶高
HALL_X0 = 1372.0  # 厅的左边
PORCH_Y = 772.0  # 厅前台基上沿

# 远山：地区 id → (所在层, 主峰中心 x, 高, 左半宽, 右半宽, 尖度, 晨光窗口半宽)
REGIONS = {
    "changyang": ("far", 192.0, 185.0, 140.0, 140.0, 0.9, 94.0),
    "zhangwei": ("back", 720.0, 310.0, 200.0, 180.0, 1.45, 140.0),
    "beiming": ("far", 960.0, 160.0, 130.0, 120.0, 1.15, 110.0),
    "youdu": ("far", 1180.0, 0.0, 0.0, 0.0, 0.0, 118.0),  # 幽都：两道山肩夹一个山口，口里一座黑城
    "danxue": ("far", 1440.0, 210.0, 130.0, 130.0, 1.7, 124.0),
    "qingqiu": ("far", 1690.0, 175.0, 150.0, 170.0, 1.0, 130.0),
}
FAR_BASE, BACK_BASE = 455.0, 470.0
YOUDU_SHOULDERS = [(1092.0, 140.0, 110.0, 50.0, 1.4), (1272.0, 150.0, 50.0, 110.0, 1.35)]
YOUDU_FLOOR = 398.0

# 心灯：12 个挂灯的位置（灯身中心 x, y, 挂绳上端 y, 灯形）。按 meta.ron 的文件顺序一一对应：
# 前六个（祈福…灯坠栏）在中下两排，悟·金木水火土在上面一道弧上（按方位：金西、水北、土中、火南、木东，
# 和后面远山的地区一样从左到右），最后一个（香火）在左下。
LAMP_SLOTS = [
    (515.0, 425.0, 372.0, "round"), (687.0, 420.0, 368.0, "oval"), (345.0, 450.0, 398.0, "oval"), (855.0, 455.0, 402.0, "round"),
    (440.0, 522.0, 468.0, "drum"), (752.0, 530.0, 474.0, "drum"),
    (262.0, 382.0, 324.0, "round"), (938.0, 378.0, 320.0, "round"), (430.0, 334.0, 278.0, "oval"), (770.0, 330.0, 274.0, "oval"),
    (604.0, 312.0, 248.0, "round"),
    (272.0, 528.0, 474.0, "oval"),
]
LAMP_SHAPES = {"round": (17.0, 19.0), "oval": (15.0, 22.0), "drum": (16.0, 17.0)}
ELEMENT_TINT = {  # 悟·五行：点亮时纸上淡淡一层那一系的颜色
    "metal": mixc(TENG, PAPER, 0.35), "wood": mixc(SHILV, HUAQING, 0.3), "water": HUAQING, "fire": ZHUSHA, "earth": ZHESHI,
}

# 人物（hub.ron 的顺序）。坐标见各 paint_* 的原点。
SMITH_AT, PEDDLER_AT, CHILD_AT, TELLER_AT = (482.0, 806.0), (836.0, 818.0), (1112.0, 792.0), (1480.0, PORCH_Y)
CHARACTERS = [
    {"id": "smith", "name": "老灯匠", "role": "心灯", "rect": [262, 618, 262, 196], "label": [392, 822], "light": [400, 716, 175]},
    {"id": "peddler", "name": "货郎", "role": "属性 · 灯面", "rect": [668, 566, 352, 258], "label": [846, 830], "light": [850, 700, 190]},
    {"id": "child", "name": "灯童", "role": "成就 · 试炼", "rect": [1084, 668, 154, 132], "label": [1160, 806], "light": [1160, 742, 125]},
    {"id": "teller", "name": "说书人", "role": "图鉴 · 手记", "rect": [1436, 580, 230, 196], "label": [1548, 808], "light": [1546, 700, 165]},
]


def meta_ids() -> list[str]:
    """心灯节点的 id，按 meta.ron 的文件顺序。"""
    return re.findall(r'\(id: "([a-z0-9_]+)"', META_RON.read_text(encoding="utf-8"))


# ============================================================== 画布与笔墨工具


class Hub(T.Painting):
    """title_screen.Painting + 覆盖度记录：begin(name) 之后画的每一笔都记进 name 的覆盖度（遮挡、剪影用）。"""

    def __init__(self, rng):
        super().__init__(rng)
        self.track: dict[str, np.ndarray] = {}
        self.layers: dict[str, np.ndarray] = {}  # 远山各层的“山体”遮罩、山脊线
        self.ridges: dict[str, np.ndarray] = {}

    def begin(self, name: str) -> None:
        self.track[name] = np.zeros((H, W))

    def end(self, name: str) -> np.ndarray:
        return self.track.pop(name)

    def _note(self, a, sl):
        if not self.track:
            return
        a = np.clip(a, 0, 1)
        for m in self.track.values():
            if sl is None:
                np.maximum(m, a, out=m)
            else:
                m[sl] = np.maximum(m[sl], a)

    def glaze(self, a, color, sl=None):
        super().glaze(a, color, sl)
        self._note(a, sl)

    def over(self, a, color, sl=None):
        super().over(a, color, sl)
        self._note(a, sl)


def closed_curve(ctrl, per: int = 14) -> np.ndarray:
    """过控制点的闭合平滑曲线（Catmull-Rom）。"""
    c = np.asarray(ctrl, np.float64)
    m = len(c)
    t = np.linspace(0, 1, per, endpoint=False)[:, None]
    out = []
    for i in range(m):
        p0, p1, p2, p3 = c[(i - 1) % m], c[i], c[(i + 1) % m], c[(i + 2) % m]
        out.append(0.5 * ((2 * p1) + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t ** 2 + (-p0 + 3 * p1 - 3 * p2 + p3) * t ** 3))
    return np.vstack(out)


def shape_cover(poly, ss: int = 3, soft: float = 0.6, pad: int = 4):
    """多边形 → (切片, 覆盖度)，只在包围盒里算（超采样抗锯齿，边缘略晕）。"""
    pts = np.asarray(poly, np.float64)
    x0, y0 = max(0, int(pts[:, 0].min()) - pad), max(0, int(pts[:, 1].min()) - pad)
    x1, y1 = min(W, int(pts[:, 0].max()) + pad + 1), min(H, int(pts[:, 1].max()) + pad + 1)
    sl = (slice(y0, y1), slice(x0, x1))
    if x1 <= x0 or y1 <= y0:
        return sl, np.zeros((max(0, y1 - y0), max(0, x1 - x0)))
    im = Image.new("L", ((x1 - x0) * ss, (y1 - y0) * ss), 0)
    ImageDraw.Draw(im).polygon([((x - x0) * ss, (y - y0) * ss) for x, y in pts], fill=255)
    m = V.downsample(np.asarray(im, np.float64) / 255.0, ss)
    if soft:
        m = np.clip(blur(m, soft), 0, 1)
    return sl, m


def fill(P: Hub, poly, color, alpha=1.0, *, mode="glaze", rim=0.25, tex=None, smooth=True, near=True, soft=0.6):
    """一块水墨：闭合轮廓里罩一层墨（罩染时浓淡略不匀），边上一圈水痕略深。smooth=False 时轮廓是折线。
    mode="over" 是不透明的底（人物的衣服、器物），默认没有浓淡，免得透出后面的东西。"""
    if tex is None:
        tex = 0.15 if mode == "glaze" else 0.0
    pts = closed_curve(poly) if smooth else np.asarray(poly, np.float64)
    sl, m = shape_cover(pts, soft=soft)
    if m.size == 0:
        return sl, m
    a = m * (1.0 - tex + tex * (0.5 + 0.5 * noise(P.rng, m.shape, 5.0)))
    if rim:
        a = a + rim * m * (1 - smoothstep(0.45, 0.95, blur(m, 2.2)))
    (P.glaze if mode == "glaze" else P.over)(np.clip(a * alpha, 0, 1), color, sl)
    if near:
        P.mark_near(m, sl)
    return sl, m


def line(P: Hub, ctrl, w0, w1=None, color=None, alpha=0.95, *, dry=0.25, dry_start=0.5, jitter=0.18, mode="over", n=None,
         smooth=True, near=True, taper=True):
    """一笔线：过控制点（smooth）或折线，粗细从 w0 到 w1（半宽，像素），两头略收。"""
    p = np.asarray(ctrl, np.float64)
    length = float(np.hypot(*np.diff(p, axis=0).T).sum())
    n = n or max(8, int(length / 2.5))
    c = T.curve_pts(p, n) if (smooth and len(p) > 2) else V.arc_resample(p, n)
    t = np.linspace(0, 1, len(c))
    hw = w0 + ((w0 if w1 is None else w1) - w0) * t
    if taper:
        hw = hw * np.clip(0.45 + 0.55 * np.minimum(t / 0.12, 1) * np.minimum((1 - t) / 0.12, 1) + 0.0, 0.45, 1.0)
    P.stroke(c, hw, JIAO if color is None else color, alpha, dry=dry, dry_start=dry_start, jitter=jitter, mode=mode, near=near)


def ellipse(P: Hub, cx, cy, rx, ry, color, alpha=1.0, *, mode="over", ang=0.0, near=True, soft=0.5):
    th = np.linspace(0, 2 * math.pi, 48, endpoint=False)
    ca, sa = math.cos(ang), math.sin(ang)
    pts = np.stack([cx + rx * np.cos(th) * ca - ry * np.sin(th) * sa, cy + rx * np.cos(th) * sa + ry * np.sin(th) * ca], -1)
    sl, m = shape_cover(pts, soft=soft)
    if m.size:
        (P.glaze if mode == "glaze" else P.over)(m * alpha, color, sl)
        if near:
            P.mark_near(m, sl)
    return pts


def brush(P: Hub, ctrl, w, *, color=None, alpha=0.95, smooth=True, press=1.0, nail=0.7, tail=0.3, dry=0.0, dry_start=0.55,
          gap=None, mode="over", n=None, near=True):
    """白描的一笔：起笔一顿（钉头），行笔略细，转折处按重，收笔出锋；dry>0 时后段飞白；gap=(t0, t1) 在这一段断开。
    w 是行笔时的半宽（像素）。"""
    p = np.asarray(ctrl, np.float64)
    length = float(np.hypot(*np.diff(p, axis=0).T).sum())
    n = n or max(10, int(length / 1.4))
    c = T.curve_pts(p, n) if (smooth and len(p) > 2) else V.arc_resample(p, n)
    d = np.gradient(c, axis=0)
    ang = np.unwrap(np.arctan2(d[:, 1], d[:, 0]))
    seg = max(length / max(n - 1, 1), 1e-6)
    k = np.abs(np.gradient(ang)) / seg
    k = blur(k[None, :], (2.5, 0))[0]
    kn = np.clip(k * 16.0, 0, 1)  # 转弯半径 16 像素以内按到最重
    t = np.linspace(0, 1, n)
    prof = (0.62 + 0.55 * press * kn) * (1 + nail * np.exp(-(t / 0.06) ** 2))
    if tail:
        prof = prof * (0.18 + 0.82 * np.clip((1 - t) / tail, 0, 1) ** 0.7)
    wob = blur(P.rng.standard_normal((1, n)), (4.0, 0))[0]
    prof = prof * (1 + 0.12 * wob / (wob.std() + 1e-9))
    hw = w * prof
    c_ = JIAO if color is None else color
    pieces = [(c, hw)]
    if gap:
        i0, i1 = int(gap[0] * (n - 1)), int(gap[1] * (n - 1))
        pieces = [(c[:i0], hw[:i0]), (c[i1:], hw[i1:])]
    for cc, hh in pieces:
        if len(cc) >= 3:
            P.stroke(cc, hh, c_, alpha, dry=dry, dry_start=dry_start, jitter=0.1, mode=mode, near=near)


def wash(P: Hub, poly, color, alpha, *, soft=2.4, rough=0.6, ring=0.3, mode="glaze", tex=0.18, smooth=True):
    """一层淡墨或淡彩：边缘软、略不齐（洇开），干后边上一圈水痕略深。poly 是闭合轮廓（画面坐标）。"""
    pts = closed_curve(poly) if smooth else np.asarray(poly, np.float64)
    sl, m = shape_cover(pts, soft=0, pad=int(soft * 3) + 6)
    if m.size == 0:
        return
    ms = blur(m, soft)
    n1 = noise(P.rng, m.shape, 3.0)
    ms = ms + 0.10 * rough * n1
    body = smoothstep(0.28, 0.62, ms)
    rim = ring * np.exp(-((ms - 0.40) / 0.09) ** 2)
    a = alpha * np.clip(body * (1 - tex + tex * (0.5 + 0.5 * noise(P.rng, m.shape, 7.0))) + rim, 0, 1)
    (P.glaze if mode == "glaze" else P.over)(a, color, sl)
    P.mark_near(body, sl)


def knock(P: Hub, poly, smooth=True):
    """人物所在处的背景擦回纸色（画人物时那里本来是留白的），边缘略外扩一点。"""
    pts = closed_curve(poly) if smooth else np.asarray(poly, np.float64)
    sl, m = shape_cover(pts, soft=1.0, pad=6)
    if m.size == 0:
        return
    a = smoothstep(0.08, 0.5, m) * 0.98
    P.over(a, P.paper0[sl], sl)
    P.mark_near(a, sl)


class Fig:
    """点景人物的局部坐标：原点在脚底（坐着的人是座位前的地面），y 向上为负；s 缩放，flip=-1 左右翻转。"""

    def __init__(self, P: Hub, fx, fy, s=1.0, flip=1):
        self.P, self.fx, self.fy, self.s, self.flip = P, fx, fy, s, flip

    def pt(self, x, y):
        return (self.fx + self.flip * self.s * x, self.fy + self.s * y)

    def pts(self, ctrl):
        return np.array([self.pt(*p) for p in ctrl])

    def fill(self, ctrl, color, alpha=1.0, **kw):
        return fill(self.P, self.pts(ctrl), color, alpha, **kw)

    def line(self, ctrl, w0, w1=None, color=None, alpha=0.95, **kw):
        line(self.P, self.pts(ctrl), w0 * self.s, None if w1 is None else w1 * self.s, color, alpha, **kw)

    def ellipse(self, cx, cy, rx, ry, color, alpha=1.0, **kw):
        x, y = self.pt(cx, cy)
        return ellipse(self.P, x, y, rx * self.s, ry * self.s, color, alpha, **kw)

    def brush(self, ctrl, w, **kw):
        brush(self.P, self.pts(ctrl), w * self.s, **kw)

    def wash(self, ctrl, color, alpha, off=(0.0, 0.0), **kw):
        wash(self.P, self.pts([(x + off[0], y + off[1]) for x, y in ctrl]), color, alpha, **kw)

    def knock(self, ctrl, **kw):
        knock(self.P, self.pts(ctrl), **kw)

    def shade(self, ctrl, color, alpha, side=-1.0):
        """衣服的背光一面：在轮廓里朝 side（局部坐标，-1 = 身后）一侧罩一层墨，往另一侧淡掉。"""
        pts = self.pts(ctrl)
        sl, m = shape_cover(closed_curve(pts), soft=0.6)
        if m.size == 0:
            return
        x0, x1 = pts[:, 0].min(), pts[:, 0].max()
        u = (self.P.X[sl] - (x0 + x1) / 2) / max((x1 - x0) / 2, 1.0) * side * self.flip
        self.P.glaze(m * alpha * smoothstep(-0.3, 0.9, u) * (0.85 + 0.15 * noise(self.P.rng, m.shape, 4.0)), color, sl)

    def dot(self, x, y, r, color=None, alpha=0.95):
        gx, gy = self.pt(x, y)
        self.P.dot(gx, gy, r * self.s, r * self.s, JIAO if color is None else color, alpha)
        self.P.mark_near(np.ones(1), (slice(int(gy), int(gy) + 1), slice(int(gx), int(gx) + 1)))


# ============================================================== 天、远山、雾


def text_quiet(P: Hub) -> np.ndarray:
    """文字安全区的遮罩（边缘柔和）：那里的天压得很平、不画云。"""
    q = np.zeros((H, W))
    for (x, y, w, h) in TEXT_SAFE:
        q = np.maximum(q, smoothstep(x + w + 140, x + w - 20, P.X) * smoothstep(x - 140, x + 20, P.X)
                       * smoothstep(y + h + 70, y + h - 10, P.Y) * smoothstep(y - 70, y + 10, P.Y))
    return q


def paint_sky(P: Hub, rng):
    """夜空：上浓下淡的墨（纯墨，不兑颜色），横向的云气；月亮留白、四周一圈圈淡开，两缕薄云横过月下。
    左上标题区的天匀净。"""
    mx, my, mr = MOON
    yn = P.Y / H
    quiet = text_quiet(P) * (P.Y < 400)
    cloud = noise(rng, (H, W), (260.0, 30.0), angle=-0.04)
    cloud2 = noise(rng, (H, W), (90.0, 12.0), angle=-0.02)
    tex = 1.0 + (0.13 * cloud + 0.06 * cloud2) * (1.0 - 0.85 * quiet)
    base = 0.86 - 0.50 * smoothstep(0.06, 0.44, yn) + 0.05 * quiet
    a = base * tex
    d = np.hypot(P.X - mx, P.Y - my)
    halo = smoothstep(mr * 0.95, mr * 6.0, d)
    a = a * (0.10 + 0.90 * halo ** 0.75)
    a = a * smoothstep(mr - 0.5, mr + 2.0, d + 1.5 * noise(rng, (H, W), 1.5))  # 月轮留白
    P.glaze(np.clip(a, 0, 0.93), SKY)
    for cy, amp, wid, sx in ((my + 0.35 * mr, 0.5, 9.0, 1.0), (my + 0.85 * mr, 0.38, 7.0, 1.3), (my - 1.6 * mr, 0.14, 12.0, 2.0)):
        band = np.exp(-((P.Y - cy - 6 * noise(rng, (H, W), (140.0, 10.0))) / wid) ** 2)
        span = smoothstep(mx - 300 * sx, mx - 80, P.X) * smoothstep(mx + 340 * sx, mx + 110, P.X)
        t2 = 0.55 + 0.45 * V.rank01(noise(rng, (H, W), (70.0, 1.6), angle=-0.03))
        P.glaze(np.clip(amp * band * span * t2, 0, 1), SKY)
    for cx, cy, rx, ry, al in ((1120, 70, 300, 34, 0.10), (1860, 120, 200, 30, 0.08), (980, 228, 200, 20, 0.06)):
        T.wash_blob(P, cx, cy, rx, ry, SKY, al, rng, ang=-0.03, rough=0.5, edge=0.6)


def fog_band(P: Hub, rng, lo: float, hi: float, strength: float, amp: float = 30.0):
    """一道横雾（scroll_qingqiu.paint_fog_band 的长夜版）：纸色略亮，高低随 x 起伏，浓淡成片。"""
    wav = blur(rng.standard_normal((1, W)), (110.0, 0))[0]
    wav = amp * wav / (wav.std() + 1e-9)
    yb = P.Y + wav[None, :]
    fog = smoothstep(lo - 60, lo + 40, yb) * smoothstep(hi + 70, hi - 20, yb)
    fog = fog * np.clip(0.35 + 0.65 * smoothstep(-1.2, 1.2, noise(rng, (H, W), (150.0, 22.0))), 0, 1)
    P.over(np.clip(fog * strength, 0, 1), mixc(PAPER, WHITE, 0.22))
    P.mist = np.maximum(P.mist, np.clip(fog * strength * 1.6, 0, 1))


def inside_of(P: Hub, ridge: np.ndarray) -> np.ndarray:
    return smoothstep(-1.0, 1.4, P.Y - ridge[None, :])


def paint_far(P: Hub, rng):
    """远山两层：最后面只有章尾山一座，最淡最高；前面一列是另外五个地区。幽都是两道山肩夹着的山口，口里一座黑城。"""
    xs = np.arange(W) + 0.5
    # 章尾山
    _, cx, hgt, wl, wr, sharp, _ = REGIONS["zhangwei"]
    rb = T.ridge_line(xs, [(cx, hgt, wl, wr, sharp)], BACK_BASE, rng, rough=4.0)
    T.mountain_layer(P, rb, mixc(QING, DAN, 0.3), 0.34, 170.0, rng, mist_from=BACK_BASE - 20, mist_len=110.0, edge=0.45)
    T.mountain_texture(P, rb, mixc(QING, DAN, 0.5), rng, BACK_BASE - 40, n=30, strength=0.2, edge_k=1.2)
    P.layers["back"], P.ridges["back"] = inside_of(P, rb), rb
    fog_band(P, rng, 340, 450, 0.22)
    # 远山一列
    peaks = [(c, h_, l_, r_, s_) for k, (lay, c, h_, l_, r_, s_, _) in REGIONS.items() if lay == "far" and h_ > 0] + YOUDU_SHOULDERS
    rf = T.ridge_line(xs, peaks, FAR_BASE, rng, rough=5.0)
    # 幽都的山口：两道山肩之间压到山口底，两边是陡崖
    notch = smoothstep(1124.0, 1150.0, xs) * smoothstep(1240.0, 1214.0, xs)
    floor = YOUDU_FLOOR + 3.0 * np.sin(xs * 0.11)
    rf = rf * (1 - notch) + np.maximum(rf, floor) * notch
    color = mixc(QING, DAN, 0.7)
    T.mountain_layer(P, rf, color, 0.48, 130.0, rng, mist_from=FAR_BASE + 20, mist_len=80.0, edge=0.6)
    T.mountain_texture(P, rf, color, rng, FAR_BASE + 20, n=80, strength=0.26, edge_k=1.3)
    P.layers["far"], P.ridges["far"] = inside_of(P, rf), rf
    P.begin("city")
    paint_youdu_city(P, rng)
    P.layers["city"] = np.clip(P.end("city") * 1.2, 0, 1)
    fog_band(P, rng, 430, 520, 0.34)


def paint_youdu_city(P: Hub, rng):
    """幽都：山口里一座黑城——一道带垛口的城墙、正中两层的城楼；山口里的墨比别处重。"""
    cx = REGIONS["youdu"][1]
    x0, x1 = cx - 40.0, cx + 40.0
    yb = YOUDU_FLOOR + 6
    sl, m = shape_cover([(cx - 52, YOUDU_FLOOR - 10), (cx + 52, YOUDU_FLOOR - 10), (cx + 66, 480), (cx - 66, 480)], soft=6.0)
    P.glaze(0.35 * m * smoothstep(520, YOUDU_FLOOR, P.Y[sl]), ZHONG, sl)
    city = mixc(ZHONG, DAN, 0.35)
    wall = [(x0, yb), (x0, yb - 16)]
    x = x0
    while x < x1 - 4:  # 垛口
        wall += [(x + 3, yb - 16), (x + 3, yb - 19), (x + 6, yb - 19), (x + 6, yb - 16)]
        x += 7
    wall += [(x1, yb - 16), (x1, yb)]
    sl, m = shape_cover(wall, soft=0.4)
    P.over(0.85 * m, city, sl)
    for (w_, y_, h_) in ((30.0, yb - 16, 10.0), (22.0, yb - 26, 8.0)):  # 城楼：台座 + 两层屋檐
        sl, m = shape_cover([(cx - w_ / 2, y_), (cx + w_ / 2, y_), (cx + w_ / 2, y_ - h_), (cx - w_ / 2, y_ - h_)], soft=0.4)
        P.over(0.9 * m, city, sl)
    for (w_, y_) in ((44.0, yb - 26), (34.0, yb - 34)):
        poly, eave, ridge = Q.roof_poly(cx, y_, w_, 8.0)
        sl, m = shape_cover(poly, soft=0.4)
        P.over(0.95 * m, mixc(ZHONG, NONG, 0.4), sl)
    sl, m = shape_cover([(cx - 4, yb), (cx + 4, yb), (cx + 4, yb - 9), (cx, yb - 12), (cx - 4, yb - 9)], soft=0.3)  # 城门洞
    P.over(0.9 * m, NONG, sl)


def paint_beyond(P: Hub, rng):
    """墙外：一片雾里的平野（墙头上、枝缝里看得见）。"""
    fog_band(P, rng, 480, 560, 0.42)


# ============================================================== 灯驿：墙、门楼、厅、漏刻、更鼓


def paint_wall(P: Hub, rng, x0: float, x1: float):
    """一段白墙：墙身留白（略比纸亮），墙脚一道石基、水渍；墙帽是一溜小瓦顶。"""
    top, base = WALL_TOP, WALL_BASE
    sl, m = shape_cover([(x0, top), (x1, top), (x1, base), (x0, base)], soft=0.4)
    P.over(0.96 * m, PLASTER, sl)
    P.mark_near(m, sl)
    # 墙身略有浓淡、墙脚水渍往上洇
    stain = smoothstep(base - 90, base - 10, P.Y[sl]) * (0.5 + 0.5 * noise(rng, m.shape, (40.0, 8.0)))
    P.glaze(np.clip(m * (0.06 + 0.16 * stain + 0.04 * noise(rng, m.shape, 30.0)), 0, 1), DAN, sl)
    # 石基
    sl2, m2 = shape_cover([(x0, base - 24), (x1, base - 24), (x1, base + 2), (x0, base + 2)], soft=0.5)
    P.glaze(m2 * (0.42 + 0.1 * noise(rng, m2.shape, 6.0)), mixc(DAN, ZHONG, 0.3), sl2)
    xx = x0
    while xx < x1:  # 石缝
        line(P, [(xx, base - 23), (xx, base)], 0.9, color=ZHONG, alpha=0.6, smooth=False)
        xx += rng.uniform(46, 80)
    line(P, [(x0, base - 24), (x1, base - 24)], 1.0, color=ZHONG, alpha=0.6, smooth=False, dry=0.4)
    # 墙帽：一道小瓦顶
    cap = [(x0 - 4, top + 3), (x1 + 4, top + 3), (x1 + 4, top - 8), (x1 - 4, top - 15), (x0 + 4, top - 15), (x0 - 4, top - 8)]
    sl3, m3 = shape_cover(cap, soft=0.5)
    P.over(0.92 * m3, mixc(ZHONG, NONG, 0.4), sl3)
    P.mark_near(m3, sl3)
    line(P, [(x0, top - 14), (x1, top - 14)], 2.2, color=JIAO, alpha=0.95, smooth=False, dry=0.35)
    line(P, [(x0 - 4, top + 3), (x1 + 4, top + 3)], 1.6, color=JIAO, alpha=0.9, smooth=False, dry=0.3)
    xx = x0 + 3
    while xx < x1 - 2:  # 瓦当
        P.dot(xx, top + 3.5, 2.2, 2.0, NONG, 0.9)
        line(P, [(xx, top - 13), (xx + 1.5, top + 1)], 0.6, color=NONG, alpha=0.6, smooth=False)
        xx += 9.0
    # 墙下的影
    P.glaze(0.25 * smoothstep(top + 28, top + 4, P.Y[sl]) * m, ZHONG, sl)


TALLY = 23  # 墙上刻了几道（守灯人回来的次数）


def paint_tally(P: Hub, rng, x0: float, y0: float, n: int = TALLY):
    """灯童在门边墙上刻的痕：五道一个“正”字，一个个往下排（守灯人回来一次刻一道）。刻痕是一道焦墨、旁边一线留白。"""
    strokes = [((0, 0), (15, 0)), ((7.5, 0), (7.5, 16)), ((7.5, 8), (13.5, 8)), ((2.5, 8.5), (2.5, 16)), ((-1, 16), (16, 16))]
    k = 0
    row = 0
    while k < n:
        for i, (p, q) in enumerate(strokes):
            if k >= n:
                break
            j = rng.normal(0, 0.5, 4)
            a = (x0 + p[0] + j[0], y0 + row * 22 + p[1] + j[1])
            b_ = (x0 + q[0] + j[2], y0 + row * 22 + q[1] + j[3])
            line(P, [(a[0] + 0.8, a[1] + 0.9), (b_[0] + 0.8, b_[1] + 0.9)], 0.6, color=mixc(PAPER, WHITE, 0.4), alpha=0.7, smooth=False)
            line(P, [a, b_], 0.85, color=NONG, alpha=0.9, smooth=False, dry=0.2, jitter=0.25)
            k += 1
        row += 1


def paint_gatehouse(P: Hub, rng):
    """门楼：两根柱、门楣、“灯驿”匾额、小歇山顶；门开着，门洞里是门外的路，伸进雾里；门槛、石阶。"""
    cx = GATE_CX
    d0, d1, dy0, dy1 = DOOR
    p0, p1 = POSTS
    # 门洞里：门外的地和路，往远处隐进雾里
    sl, m = shape_cover([(d0, dy0), (d1, dy0), (d1, dy1 + 2), (d0, dy1 + 2)], soft=0.3)
    yy = P.Y[sl]
    P.over(m * 0.97, mixc(PAPER, WHITE, 0.12), sl)
    ground = smoothstep(dy0 + 40, dy1, yy)
    P.glaze(m * (0.18 + 0.42 * ground) * (0.85 + 0.15 * noise(rng, m.shape, (30.0, 4.0))), mixc(DAN, ZHONG, 0.35), sl)
    road = T.curve_pts([(cx + 4, dy1 + 4), (cx + 10, dy1 - 56), (cx - 2, dy1 - 110), (cx + 6, dy0 + 10)], 120)
    sl2, cov = T.stroke_cover(P.X, P.Y, road, np.linspace(38, 4, 120), rng, jitter=0.2)
    P.over(np.clip(blur(cov, 2.0) * 0.6, 0, 1), mixc(PAPER, WHITE, 0.2), sl2)
    mist = smoothstep(dy0 + 100, dy0 + 8, yy) * (0.6 + 0.4 * noise(rng, m.shape, (40.0, 8.0)))
    P.over(np.clip(m * mist * 0.6, 0, 1), mixc(PAPER, WHITE, 0.25), sl)
    P.mist[sl] = np.maximum(P.mist[sl], m * (0.4 + 0.5 * mist))
    # 门扇：向里开着，只看得见两条窄边
    for (xa, xb) in ((d0, d0 + 14), (d1 - 14, d1)):
        sl3, m3 = shape_cover([(xa, dy0 + 2), (xb, dy0 + 6), (xb, dy1 - 2), (xa, dy1)], soft=0.4)
        P.over(0.9 * m3, mixc(ZHONG, NONG, 0.3), sl3)
        P.mark_near(m3, sl3)
        for yk in np.linspace(dy0 + 22, dy1 - 22, 6):  # 门钉
            P.dot((xa + xb) / 2, yk, 1.6, 1.6, mixc(DAN, QING, 0.5), 0.8)
    # 门洞两侧的墙
    for (xa, xb) in ((p0, d0), (d1, p1)):
        sl4, m4 = shape_cover([(xa, GATE_EAVE + 8), (xb, GATE_EAVE + 8), (xb, WALL_BASE), (xa, WALL_BASE)], soft=0.4)
        P.over(0.96 * m4, PLASTER, sl4)
        P.glaze(m4 * (0.08 + 0.14 * smoothstep(WALL_BASE - 80, WALL_BASE, P.Y[sl4])), DAN, sl4)
        P.mark_near(m4, sl4)
    # 门框、门楣、柱
    for x in (d0, d1):
        line(P, [(x, dy0 - 2), (x, dy1)], 3.2, color=NONG, alpha=0.95, smooth=False, dry=0.2)
    line(P, [(p0 - 6, dy0 - 4), (p1 + 6, dy0 - 4)], 6.0, color=mixc(NONG, ZHONG, 0.3), alpha=0.95, smooth=False, dry=0.25)
    for x in (p0 + 6, p1 - 6):
        line(P, [(x, GATE_EAVE + 6), (x, WALL_BASE + 4)], 7.5, color=mixc(NONG, ZHONG, 0.25), alpha=0.96, smooth=False, dry=0.3, taper=False)
        line(P, [(x - 7, GATE_EAVE + 10), (x - 7, WALL_BASE)], 1.0, color=JIAO, alpha=0.7, smooth=False)
    # 檐下的暗
    sl5, m5 = shape_cover([(p0 - 16, GATE_EAVE + 2), (p1 + 16, GATE_EAVE + 2), (p1 + 16, GATE_EAVE + 46), (p0 - 16, GATE_EAVE + 46)], soft=6.0)
    P.glaze(0.45 * m5 * smoothstep(GATE_EAVE + 46, GATE_EAVE + 6, P.Y[sl5]), ZHONG, sl5)
    paint_roof(P, rng, cx, GATE_EAVE, 290.0, 80.0)
    paint_plaque(P, rng, cx, GATE_EAVE + 34.0)
    # 门槛、石阶
    sl6, m6 = shape_cover([(d0 - 6, SILL_Y), (d1 + 6, SILL_Y), (d1 + 6, SILL_Y + 10), (d0 - 6, SILL_Y + 10)], soft=0.4)
    P.over(0.92 * m6, mixc(DAN, ZHONG, 0.35), sl6)
    P.mark_near(m6, sl6)
    line(P, [(d0 - 6, SILL_Y), (d1 + 6, SILL_Y)], 1.4, color=JIAO, alpha=0.9, smooth=False)
    step = [(d0 - 24, SILL_Y + 10), (d1 + 24, SILL_Y + 10), (d1 + 30, SILL_Y + 28), (d0 - 30, SILL_Y + 28)]
    sl7, m7 = shape_cover(step, soft=0.5)
    P.over(0.9 * m7, mixc(PAPER, QING, 0.45), sl7)
    P.glaze(m7 * 0.25 * smoothstep(SILL_Y + 16, SILL_Y + 28, P.Y[sl7]), DAN, sl7)
    P.mark_near(m7, sl7)
    line(P, [step[3], step[2]], 1.6, color=NONG, alpha=0.85, smooth=False, dry=0.4)
    line(P, [step[0], step[3]], 1.0, color=NONG, alpha=0.7, smooth=False)
    line(P, [step[1], step[2]], 1.0, color=NONG, alpha=0.7, smooth=False)


def paint_roof(P: Hub, rng, cx, ye, w, rh, *, key=None):
    """一个屋顶（scroll_qingqiu.roof_poly）：重墨的屋面、瓦垄，焦墨的檐口和屋脊，翘角一点。"""
    poly, eave, ridge = Q.roof_poly(cx, ye, w, rh)
    sl, m = shape_cover(poly, soft=0.5)
    k = smoothstep(ye - rh, ye, P.Y[sl])
    roof_c = mixc(ZHONG, NONG, 0.35)
    P.over(0.95 * m * (1 - 0.0 * k), mixc(mixc(roof_c, DAN, 0.35), roof_c, k), sl)
    P.mark_near(m, sl)
    n_t = int(w / 8)
    for i in range(n_t):
        f = (i + 0.5) / n_t - 0.5
        top = (cx + f * 0.56 * w, ye - rh + 3)
        bot = (cx + f * 1.22 * w, ye - 0.1 * rh - 0.25 * rh * (2 * f) ** 2)
        line(P, [top, bot], 0.9, color=mixc(NONG, JIAO, 0.4), alpha=0.5, smooth=False, mode="glaze", jitter=0.1)
    hw_e = np.interp(np.linspace(0, 1, len(eave)), [0, 0.1, 0.9, 1], [1.4, 3.4, 3.4, 1.4])
    P.stroke(eave, hw_e, JIAO, 0.95, dry=0.3, jitter=0.2, near=True)
    hw_r = np.interp(np.linspace(0, 1, len(ridge)), [0, 0.15, 0.85, 1], [1.6, 3.6, 3.6, 1.6])
    P.stroke(ridge, hw_r, JIAO, 0.95, dry=0.25, jitter=0.2, near=True)
    for e in (eave[0], eave[-1], ridge[0], ridge[-1]):
        P.dot(e[0], e[1] - 1.0, 2.6, 1.9, JIAO, 0.9)
    return eave


def paint_plaque(P: Hub, rng, cx, cy):
    """匾额：横匾，焦墨框、淡赭墨的木底，“灯驿”两字，略带飞白（title_screen.ink_texture）。"""
    w, h = 112.0, 40.0
    x0, y0 = cx - w / 2, cy - h / 2
    sl, m = shape_cover([(x0, y0), (x0 + w, y0), (x0 + w, y0 + h), (x0, y0 + h)], soft=0.4)
    P.over(0.97 * m, mixc(PAPER, QING, 0.55), sl)
    P.glaze(m * (0.12 + 0.06 * noise(rng, m.shape, (30.0, 1.5))), DAN, sl)
    P.mark_near(m, sl)
    for (a, b) in (((x0, y0), (x0 + w, y0)), ((x0, y0 + h), (x0 + w, y0 + h)), ((x0, y0), (x0, y0 + h)), ((x0 + w, y0), (x0 + w, y0 + h))):
        line(P, [a, b], 2.4, color=JIAO, alpha=0.95, smooth=False, dry=0.15, taper=False)
    line(P, [(x0 + 4, y0 + 4), (x0 + w - 4, y0 + 4), (x0 + w - 4, y0 + h - 4), (x0 + 4, y0 + h - 4), (x0 + 4, y0 + 4)], 0.6, color=NONG,
         alpha=0.6, smooth=False, taper=False)
    # 两根挂绳
    for x in (x0 + 18, x0 + w - 18):
        line(P, [(x, y0 - 18), (x, y0)], 0.9, color=NONG, alpha=0.8, smooth=False)
    # 字：在 3 倍尺寸上排字、做墨，再缩小贴进去
    ss = 3
    fk = font("brush", int(29 * ss))
    txt = "灯驿"
    gw = int(w * ss)
    gh = int(h * ss)
    im = Image.new("L", (gw, gh), 0)
    dr = ImageDraw.Draw(im)
    for i, ch in enumerate(txt):
        bb = fk.getbbox(ch)
        cxx = gw * (0.29 + 0.42 * i)
        dr.text((cxx - (bb[2] - bb[0]) / 2 - bb[0], gh / 2 - (bb[3] - bb[1]) / 2 - bb[1] + ss), ch, font=fk, fill=255)
    mk = np.asarray(im, np.float64) / 255.0
    alpha, dens = T.ink_texture(mk, np.random.default_rng(SEED + 31), scale=29 * ss * 0.11, dry_amount=0.6)
    a = V.downsample(alpha, ss)
    sl2 = (slice(int(y0), int(y0) + a.shape[0]), slice(int(x0), int(x0) + a.shape[1]))
    P.over(a * 0.95, JIAO, sl2)


def paint_hall(P: Hub, rng) -> None:
    """右边的厅：屋顶、檐下的梁和两根柱、一排格扇门（纸白的格心、下半是木板），前面一道石台基。"""
    cx, ye, w, rh = HALL
    xl = HALL_X0
    sl, m = shape_cover([(xl, ye + 4), (W + 10, ye + 4), (W + 10, PORCH_Y), (xl, PORCH_Y)], soft=0.4)
    P.over(0.96 * m, mixc(PAPER, QING, 0.25), sl)
    P.mark_near(m, sl)
    cols = (xl + 18.0, 1830.0)
    panels = np.linspace(cols[0] + 14, cols[1] - 12, 7)
    yl0, yl1 = ye + 30, PORCH_Y - 66  # 格心
    for xa, xb in zip(panels[:-1], panels[1:]):
        xa, xb = xa + 2, xb - 2
        sl2, m2 = shape_cover([(xa, yl0), (xb, yl0), (xb, yl1), (xa, yl1)], soft=0.3)
        P.over(0.95 * m2, PLASTER, sl2)
        for gx in np.linspace(xa, xb, 6)[1:-1]:
            line(P, [(gx, yl0), (gx, yl1)], 0.7, color=DAN, alpha=0.7, smooth=False, taper=False)
        for gy in np.linspace(yl0, yl1, 10)[1:-1]:
            line(P, [(xa, gy), (xb, gy)], 0.7, color=DAN, alpha=0.7, smooth=False, taper=False)
        sl3, m3 = shape_cover([(xa, yl1 + 8), (xb, yl1 + 8), (xb, PORCH_Y - 4), (xa, PORCH_Y - 4)], soft=0.3)  # 裙板
        P.over(0.9 * m3, mixc(DAN, ZHONG, 0.45), sl3)
        for (p_, q_) in (((xa, yl0), (xb, yl0)), ((xa, yl1), (xb, yl1)), ((xa, yl1 + 8), (xb, yl1 + 8)), ((xa, yl0), (xa, PORCH_Y - 4)),
                         ((xb, yl0), (xb, PORCH_Y - 4))):
            line(P, [p_, q_], 1.2, color=NONG, alpha=0.85, smooth=False, taper=False, dry=0.15)
    line(P, [(xl - 10, ye + 14), (W + 10, ye + 14)], 7.0, color=mixc(ZHONG, NONG, 0.4), alpha=0.95, smooth=False, taper=False, dry=0.2)
    sl4, m4 = shape_cover([(xl - 10, ye), (W + 10, ye), (W + 10, ye + 70), (xl - 10, ye + 70)], soft=4.0)
    P.glaze(0.5 * m4 * smoothstep(ye + 70, ye + 8, P.Y[sl4]), ZHONG, sl4)
    for x in cols:
        line(P, [(x, ye + 6), (x, PORCH_Y)], 8.0, color=mixc(NONG, ZHONG, 0.3), alpha=0.96, smooth=False, dry=0.3, taper=False)
        line(P, [(x + 7.5, ye + 10), (x + 7.5, PORCH_Y)], 1.0, color=JIAO, alpha=0.7, smooth=False)
    paint_roof(P, rng, cx, ye, w, rh)
    face = [(xl - 14, PORCH_Y), (W + 10, PORCH_Y), (W + 10, PORCH_Y + 30), (xl - 14, PORCH_Y + 30)]  # 台基
    sl5, m5 = shape_cover(face, soft=0.4)
    P.over(0.92 * m5, mixc(PAPER, QING, 0.5), sl5)
    P.glaze(m5 * (0.30 + 0.12 * noise(rng, m5.shape, (20.0, 3.0))), DAN, sl5)
    P.mark_near(m5, sl5)
    line(P, [(xl - 14, PORCH_Y), (W + 10, PORCH_Y)], 1.8, color=JIAO, alpha=0.9, smooth=False, dry=0.3)
    line(P, [(xl - 14, PORCH_Y + 30), (W + 10, PORCH_Y + 30)], 1.4, color=NONG, alpha=0.8, smooth=False, dry=0.4)
    line(P, [(xl - 14, PORCH_Y), (xl - 14, PORCH_Y + 30)], 1.2, color=NONG, alpha=0.8, smooth=False)
    x = xl + 40
    while x < W:
        line(P, [(x, PORCH_Y + 2), (x, PORCH_Y + 29)], 0.8, color=ZHONG, alpha=0.6, smooth=False)
        x += rng.uniform(70, 110)


def paint_drum(P: Hub, rng):
    """更鼓：厅前说书人右边一架鼓：木架、鼓身（侧面），鼓面朝左，一对鼓槌搁在鼓上。"""
    cx, cy = 1768.0, PORCH_Y - 104.0
    for (a, b) in (((cx - 30, PORCH_Y), (cx + 4, cy + 4)), ((cx + 34, PORCH_Y), (cx - 2, cy + 4)), ((cx - 26, cy + 10), (cx + 30, cy + 10))):
        line(P, [a, b], 2.6, color=NONG, alpha=0.95, smooth=False, dry=0.2)
    body = [(cx - 26, cy - 30), (cx + 26, cy - 30), (cx + 32, cy - 12), (cx + 32, cy + 8), (cx + 26, cy + 24), (cx - 26, cy + 24),
            (cx - 32, cy + 8), (cx - 32, cy - 12)]
    fill(P, body, mixc(ZHONG, NONG, 0.2), 0.92, mode="over", rim=0.0, smooth=True)
    for k in (-0.6, 0.0, 0.6):  # 鼓身的箍
        x = cx + k * 26
        line(P, [(x, cy - 30), (x + 2 * k, cy + 24)], 0.8, color=JIAO, alpha=0.7, smooth=False)
    face = ellipse(P, cx - 30, cy - 3, 9, 27, mixc(PAPER, QING, 0.55), 0.95)
    P.stroke(np.vstack([face, face[:1]]), 1.3, JIAO, 0.9, near=True)
    for t in np.linspace(0, 2 * math.pi, 12, endpoint=False):  # 鼓钉
        P.dot(cx - 30 + 10.5 * math.cos(t), cy - 3 + 29 * math.sin(t), 1.2, 1.2, JIAO, 0.85)
    for dx in (-6.0, 6.0):  # 鼓槌
        line(P, [(cx + dx, cy - 34), (cx + dx + 18, cy - 62)], 1.6, color=NONG, alpha=0.95, smooth=False)
        P.dot(cx + dx + 18, cy - 62, 3.0, 3.0, NONG, 0.95)


def paint_clepsydra(P: Hub, rng):
    """漏刻：门楼和厅之间，三级台上三只壶，水一滴滴往下落，最下面的受水壶里立着刻箭。"""
    x0 = POSTS[1] + 12.0
    steps = [(x0 + 4, PORCH_Y - 74, 34.0), (x0 + 22, PORCH_Y - 38, 38.0), (x0 + 40, PORCH_Y - 4, 42.0)]  # 台：左, 顶 y, 宽
    for (sx, sy, sw) in steps:
        sl, m = shape_cover([(sx, sy), (sx + sw, sy), (sx + sw, PORCH_Y + 2), (sx, PORCH_Y + 2)], soft=0.4)
        P.over(0.92 * m, mixc(PAPER, QING, 0.5), sl)
        P.glaze(m * 0.22, DAN, sl)
        P.mark_near(m, sl)
        line(P, [(sx, sy), (sx + sw, sy)], 1.2, color=NONG, alpha=0.9, smooth=False)
        line(P, [(sx, sy), (sx, PORCH_Y)], 1.0, color=NONG, alpha=0.8, smooth=False)
    pots = [(x0 + 20, steps[0][1], 11.0, 18.0), (x0 + 40, steps[1][1], 12.0, 20.0), (x0 + 62, steps[2][1], 13.0, 34.0)]
    for i, (px, py, pr, ph) in enumerate(pots):
        body = [(px - pr, py), (px + pr, py), (px + pr * 1.05, py - ph * 0.7), (px + pr * 0.9, py - ph), (px - pr * 0.9, py - ph),
                (px - pr * 1.05, py - ph * 0.7)]
        fill(P, body, mixc(ZHONG, DAN, 0.3), 0.92, mode="over", rim=0.0)
        line(P, [(px - pr * 1.0, py - ph), (px + pr * 1.0, py - ph)], 1.6, color=JIAO, alpha=0.95, smooth=False)
        line(P, [(px + pr * 0.95, py - ph * 0.15), (px + pr * 0.95, py - ph * 0.95)], 0.8, color=mixc(PAPER, QING, 0.4), alpha=0.6, smooth=False)
        if i < 2:  # 出水口和水线
            nx, ny = px + pr + 6, py - ph * 0.25
            line(P, [(px + pr, py - ph * 0.2), (nx, ny)], 1.1, color=JIAO, alpha=0.9, smooth=False)
            line(P, [(nx + 1, ny + 1), (nx + 1, pots[i + 1][1] - pots[i + 1][3])], 0.45, color=mixc(PAPER, WHITE, 0.3), alpha=0.8,
                 smooth=False, taper=False)
    ax, ay = pots[2][0], pots[2][1] - pots[2][3]
    line(P, [(ax, ay + 2), (ax, ay - 44)], 1.2, color=NONG, alpha=0.95, smooth=False, taper=False)
    for k in range(6):
        line(P, [(ax - 3, ay - 8 - k * 6), (ax + 3, ay - 8 - k * 6)], 0.5, color=NONG, alpha=0.8, smooth=False, taper=False)


# ============================================================== 地面


def paint_ground(P: Hub, rng):
    """院子：墙脚以下淡墨铺地（越往前越重，带横向的干笔纹），门前一段石板路；最下面一条安静的地留给提示，再往下可以被裁掉。"""
    yy = P.Y
    depth = yy - WALL_BASE
    inside = smoothstep(-2.0, 2.0, depth)
    tex = V.rank01(noise(rng, (H, W), (70.0, 1.8), angle=-0.03))
    calm = smoothstep(100, 125, depth)  # 提示区和以下：纹理压平
    a = (0.12 + 0.20 * smoothstep(20, 150, depth)) * (0.75 + 0.45 * tex * (1 - 0.85 * calm)) + 0.06 * smoothstep(110, 200, depth)
    P.glaze(np.clip(a * inside, 0, 0.9), mixc(DAN, ZHONG, 0.3))
    P.mark_near(inside)
    P.glaze(np.clip(0.30 * np.exp(-np.maximum(depth, 0) / 10.0) * inside * (P.X < HALL_X0 - 14), 0, 1), ZHONG)  # 墙脚一道暗
    # 门前的石板路：从台阶往前展开，到提示区之前淡掉
    road = T.curve_pts([(GATE_CX, SILL_Y + 26), (GATE_CX - 8, 830), (GATE_CX + 14, 880), (GATE_CX + 26, 920)], 140)
    sl, cov = T.stroke_cover(P.X, P.Y, road, np.linspace(76, 120, 140), rng, jitter=0.2)
    cov = blur(cov, 4.0) * (0.75 + 0.25 * noise(rng, cov.shape, 6.0)) * smoothstep(905, 850, P.Y[sl])
    P.over(np.clip(cov * 0.42, 0, 1), mixc(PAPER, PAPER_SH, 0.3), sl)
    for k in range(3):  # 石板缝
        y = SILL_Y + 42 + k * 26 + k * k * 4
        half = 72 + k * 14
        line(P, [(GATE_CX - half + rng.normal(0, 6), y), (GATE_CX + half * 0.9 + rng.normal(0, 6), y + rng.normal(0, 2))], 1.0,
             color=mixc(ZHONG, DAN, 0.4), alpha=0.45, smooth=False, dry=0.5, jitter=0.3)
        for j in range(3):
            x = GATE_CX - half + (j + 0.5 + rng.uniform(-0.2, 0.2)) * half * 0.62
            line(P, [(x, y + 2), (x + rng.normal(0, 3), y + 20 + 2 * k)], 0.8, color=mixc(ZHONG, DAN, 0.4), alpha=0.35, smooth=False)
    # 擦笔：横向干笔，靠墙脚，避开提示区
    for _ in range(100):
        x = rng.uniform(-20, W)
        y = WALL_BASE + abs(rng.normal(0, 34)) + 6
        if y > 880:
            continue
        ln = rng.uniform(30, 110)
        xx = np.linspace(x, x + ln, 16)
        yy_ = y + rng.uniform(-3, 3) * np.sin(np.linspace(0, math.pi, 16)) + (xx - x) * rng.uniform(-0.04, 0.03)
        hw_ = np.interp(np.linspace(0, 1, 16), [0, 0.15, 1], [0.8, rng.uniform(1.4, 2.8), 0.6])
        P.stroke(np.stack([xx, yy_], -1), hw_, mixc(ZHONG, NONG, rng.uniform(0, 0.5)), rng.uniform(0.12, 0.3), dry=0.65, dry_start=0.05,
                 jitter=0.3, mode="glaze")


def paint_grass(P: Hub, rng, spots):
    """墙脚、树根、台阶边几丛草（scroll_qingqiu 的写法，纯墨）。"""
    for (x, y, s) in spots:
        for _ in range(int(rng.integers(4, 8))):
            ln = s * rng.uniform(14, 34)
            lean = math.radians(rng.uniform(-30, 25))
            bx = x + rng.normal(0, 4 * s)
            ts = np.linspace(0, 1, 12)
            xx = bx + np.sin(lean) * ln * ts - rng.uniform(0, 6) * s * ts ** 2
            yy = y - np.cos(lean) * ln * ts
            P.stroke(np.stack([xx, yy], -1), np.interp(ts, [0, 0.25, 1], [1.3 * s, 1.5 * s, 0.25]), JIAO if rng.random() < 0.7 else NONG,
                     rng.uniform(0.7, 0.95), jitter=0.1, near=True)


# ============================================================== 灯树与心灯


def lamp_slots(ids: list[str]) -> dict[str, tuple]:
    if len(ids) != len(LAMP_SLOTS):
        raise SystemExit(f"meta.ron 有 {len(ids)} 个心灯节点，画里只有 {len(LAMP_SLOTS)} 个挂灯的位置：先在 LAMP_SLOTS 里加位置")
    return dict(zip(ids, LAMP_SLOTS))


TRUNK = [(578, 814), (556, 752), (586, 690), (622, 632), (606, 576), (590, 526)]  # 灯树主干（从根到分杈）
BOUGHS = [  # 灯树的大枝：控制点、起止半宽。每盏灯挂在正上方经过的那道枝上
    ([(588, 524), (556, 450), (522, 380), (470, 330), (430, 282), (362, 276), (300, 302), (262, 330), (224, 352), (196, 362)], 16.0, 2.4),
    ([(594, 522), (640, 450), (687, 366), (728, 302), (770, 274), (850, 264), (905, 290), (938, 324), (975, 344), (1000, 350)], 16.0, 2.4),
    ([(590, 524), (612, 450), (626, 380), (614, 312), (604, 262), (592, 238)], 10.0, 1.8),
    ([(582, 550), (530, 506), (472, 478), (440, 474), (380, 478), (310, 476), (272, 474), (230, 482), (205, 492)], 10.0, 2.0),
    ([(596, 546), (660, 506), (752, 482), (820, 472), (870, 480), (910, 494)], 9.0, 2.0),
    ([(486, 476), (420, 432), (345, 400), (306, 390)], 5.0, 1.4),
    ([(700, 494), (790, 432), (855, 406), (902, 396)], 5.0, 1.4),
]
NO_TWIG = [(110 - 20, 140 - 20, 580 + 20, 204 + 30)]  # 小枝不进的框：标题区


def twig_ok(x, y, slots) -> bool:
    """小枝的点能不能画在这里：不进灯身、不进标题区、不挡远山的峰顶。"""
    for (lx, ly, hy, kind) in slots.values():
        rx, ry = LAMP_SHAPES[kind]
        if ((x - lx) / (rx + 12)) ** 2 + ((y - ly) / (ry + 18)) ** 2 < 1.0:
            return False
    for (x0, y0, x1, y1) in NO_TWIG:
        if x0 < x < x1 and y0 < y < y1:
            return False
    for rid, (lay, cx, hgt, wl, wr, sharp, half) in REGIONS.items():
        top = (BACK_BASE if lay == "back" else FAR_BASE) - hgt
        if hgt and abs(x - cx) < 0.55 * half and y < top + 60:
            return False
    return y > 236


def crab_twig(P: Hub, rng, start, ang, length, width, depth, slots):
    """蟹爪枝：一段略折的短枝，梢头往下勾一点；末端再分两三枝，越分越细。"""
    p = np.asarray(start, np.float64)
    pts = [p.copy()]
    a = ang
    for k in range(3):
        a += rng.normal(0, 0.28) + (0.22 if k == 2 else 0.0) * (1 if math.cos(a) > 0 else -1)  # 梢头往下勾
        q = p + length / 3 * rng.uniform(0.75, 1.2) * np.array([math.cos(a), math.sin(a)])
        if not twig_ok(q[0], q[1], slots):
            break
        pts.append(q)
        p = q
    if len(pts) < 2:
        return
    c = V.arc_resample(np.array(pts), max(6, int(length / 2)))
    P.stroke(c, np.linspace(width, max(0.5, width * 0.35), len(c)), JIAO, 0.92, dry=0.3, dry_start=0.5, jitter=0.2, near=True)
    if depth > 0:
        for k in range(int(rng.integers(2, 4))):
            q = c[int(rng.uniform(0.45, 1.0) * (len(c) - 1))]
            up = -math.pi / 2
            na = a + rng.choice([-1, 1]) * rng.uniform(0.45, 0.95)
            na = na + 0.25 * math.atan2(math.sin(up - na), math.cos(up - na))  # 略向上
            crab_twig(P, rng, q, na, length * rng.uniform(0.45, 0.7), width * 0.6, depth - 1, slots)


def paint_tree(P: Hub, rng, slots):
    """灯树：一棵老树，主干扭着往上、几处瘤节，分出几道大枝，蟹爪似的小枝；枝头疏疏几点叶。"""
    trunk = T.curve_pts(TRUNK, 120)
    t = np.linspace(0, 1, len(trunk))
    hw = 27 - 13 * t ** 0.7 + 9 * np.exp(-(t / 0.06) ** 2)  # 根部外撇
    nrm = np.gradient(trunk, axis=0)
    nrm = np.stack([-nrm[:, 1], nrm[:, 0]], -1) / (np.linalg.norm(nrm, axis=1, keepdims=True) + 1e-9)
    sl, cov = T.stroke_cover(P.X, P.Y, trunk, hw, rng, jitter=0.16)
    cov = cov * smoothstep(TRUNK[0][1] + 4, TRUNK[0][1] - 3, P.Y[sl])  # 根部平平地扎进地里
    P.over(cov * 0.95, mixc(DAN, ZHONG, 0.35), sl)
    side = np.clip((P.X[sl] - np.interp(P.Y[sl], trunk[::-1, 1], trunk[::-1, 0])) / 22.0, -1, 1)
    P.glaze(cov * np.clip(0.15 + 0.45 * smoothstep(-0.2, 1.0, side) + 0.15 * noise(rng, cov.shape, (14.0, 2.0), angle=1.5), 0, 1), NONG, sl)
    P.mark_near(cov, sl)
    for sgn, w0 in ((1, 6.5), (-1, 4.0)):  # 两边枯笔勾皮：背光一边重
        edge = trunk + nrm * (hw[:, None] - 2.5) * sgn
        P.stroke(edge, np.interp(t, [0, 0.1, 0.8, 1], [2.5, w0, w0 * 0.8, 2.0]), JIAO, 0.95, dry=0.5, dry_start=0.2, jitter=0.35, near=True)
    for _ in range(40):  # 树皮：顺着树干的皴
        i = int(rng.uniform(3, len(trunk) - 6))
        c = trunk[i] + nrm[i] * rng.uniform(-0.7, 0.7) * hw[i]
        ln = rng.uniform(12, 36)
        d = trunk[min(i + 6, len(trunk) - 1)] - trunk[i]
        d = d / (np.linalg.norm(d) + 1e-9)
        bend = nrm[i] * rng.normal(0, 3)
        pts = np.stack([c + d * s_ + bend * math.sin(math.pi * s_ / ln) for s_ in np.linspace(0, ln, 10)])
        P.stroke(pts, np.linspace(rng.uniform(1.0, 2.2), 0.4, 10), mixc(NONG, JIAO, rng.random()), rng.uniform(0.5, 0.85), dry=0.55,
                 dry_start=0.2, near=True)
    for (u, s_) in ((0.30, 1.0), (0.62, 0.75)):  # 瘤节：一团焦墨，上面半圈
        i = int(u * (len(trunk) - 1))
        c = trunk[i] + nrm[i] * hw[i] * 0.2
        P.dot(c[0], c[1], 5.0 * s_, 3.4 * s_, JIAO, 0.9, ang=0.4)
        th = np.linspace(math.pi * 1.05, math.pi * 1.95, 14)
        P.stroke(np.stack([c[0] + 9 * s_ * np.cos(th), c[1] + 7 * s_ * np.sin(th)], -1), np.linspace(1.8, 0.6, 14), JIAO, 0.85, near=True)
    # 根：几道露出地面的根
    for (dx, ln, dy, w) in ((-1, 62, 7, 7.0), (1, 54, 6, 6.0), (-1, 34, 12, 4.0), (1, 30, 11, 3.5), (0.3, 20, 14, 3.0)):
        x0, y0 = TRUNK[0][0] + dx * 22, TRUNK[0][1] - 10
        line(P, [(x0, y0), (x0 + dx * ln * 0.5, y0 + dy * 0.7), (x0 + dx * ln, y0 + dy)], w, 0.8, color=mixc(NONG, ZHONG, 0.3), alpha=0.95,
             dry=0.45)
    T.wash_blob(P, TRUNK[0][0] + 6, TRUNK[0][1] + 4, 70.0, 7.0, ZHONG, 0.35, rng)
    # 大枝：先一笔淡墨的身，再一笔焦墨压背光的一边
    paths = []
    for pts, w0, w1 in BOUGHS:
        pts = np.asarray(pts, np.float64)
        c = T.curve_pts(pts, 100)
        wob = blur(rng.standard_normal((1, len(c))), (4.0, 0))[0]
        nn = np.gradient(c, axis=0)
        nn = np.stack([-nn[:, 1], nn[:, 0]], -1) / (np.linalg.norm(nn, axis=1, keepdims=True) + 1e-9)
        c = c + nn * (wob / (wob.std() + 1e-9) * 1.6)[:, None]
        wv = np.linspace(w0, w1, len(c)) * (1 + 0.12 * np.sin(np.linspace(0, 9, len(c)) + w0))
        P.stroke(c, wv, mixc(ZHONG, NONG, 0.5), 0.95, dry=0.3, dry_start=0.6, jitter=0.3, near=True)
        P.stroke(c + nn * (wv[:, None] * 0.45), wv * 0.55, JIAO, 0.9, dry=0.45, dry_start=0.3, jitter=0.35, near=True)
        paths.append((c, wv))
    # 蟹爪小枝：沿大枝每隔一段抽一枝
    for c, wv in paths:
        n = len(c)
        for i in range(int(n * 0.3), n, 11):
            tan = c[min(i + 1, n - 1)] - c[max(i - 1, 0)]
            base_a = math.atan2(tan[1], tan[0])
            side = rng.choice([-1.0, 1.0])
            a = base_a + side * rng.uniform(0.6, 1.1)
            a = a + 0.35 * math.atan2(math.sin(-math.pi / 2 - a), math.cos(-math.pi / 2 - a))
            crab_twig(P, rng, c[i], a, rng.uniform(26, 50), max(0.9, wv[i] * 0.42), 2, slots)
    # 点叶：枝梢疏疏几点
    for c, wv in paths:
        x, y = c[-1]
        for k in range(int(rng.integers(4, 8))):
            ang = rng.uniform(0, 2 * math.pi)
            r = rng.uniform(2, 14)
            px, py = x + r * math.cos(ang), y + r * math.sin(ang) * 0.7
            if twig_ok(px, py, slots):
                P.dot(px, py, rng.uniform(1.8, 3.2), rng.uniform(1.3, 2.4), mixc(DAN, ZHONG, 0.4) if k % 2 else JIAO,
                      rng.uniform(0.6, 0.9), ang=rng.uniform(-1, 1))


def hang_point(x, y_top, default):
    """灯正上方最近的一道大枝（挂绳的上端）。"""
    best = None
    for pts, _, _ in BOUGHS:
        c = T.curve_pts(np.asarray(pts, np.float64), 200)
        near = np.abs(c[:, 0] - x) < 2.0
        ys = c[near, 1]
        ys = ys[ys < y_top - 8]
        if ys.size:
            yb = float(ys.max())
            best = yb if best is None else max(best, yb)
    return default if best is None else best + 2.0


def lantern_geom(x, y, kind):
    rx, ry = LAMP_SHAPES[kind]
    return rx, ry, y - ry - 6.0, y + ry + 6.0  # 半宽、半高、上箍顶、下箍底


def paint_lantern(P: Hub, x, y, hang_y, kind, rng):
    """一盏没点亮的纸灯：挂绳、上下两道黑箍、留白的灯身（两侧淡墨晕出圆）、竹骨两三道、焦墨勾边、灯穗。"""
    rx, ry, ytop, ybot = lantern_geom(x, y, kind)
    line(P, [(x, hang_y), (x + 0.5, ytop)], 0.8, color=NONG, alpha=0.9, smooth=False, taper=False, dry=0.0)
    r = int(max(rx, ry)) + 6
    sl = (slice(int(y - r), int(y + r) + 1), slice(int(x - r), int(x + r) + 1))
    dx, dy = (P.X[sl] - x) / rx, (P.Y[sl] - y) / ry
    if kind == "drum":  # 鼓形：上下平一些
        rho = np.maximum(np.hypot(dx, dy * 0.75), np.abs(dy))
    else:
        rho = np.hypot(dx, dy)
    body = smoothstep(1.0 + 0.6 / rx, 1.0 - 0.6 / rx, rho)
    P.over(0.97 * body, PLASTER, sl)
    P.glaze(body * (0.10 + 0.32 * np.clip(dx * dx, 0, 1) ** 1.5), DAN, sl)
    P.mark_near(body, sl)
    for k in (-0.55, 0.0, 0.55):  # 竹骨：经线
        ys = np.linspace(y - ry * 0.92, y + ry * 0.92, 18)
        xs = x + k * rx * np.sqrt(np.clip(1 - ((ys - y) / ry) ** 2, 0, 1)) * (1.0 if kind != "drum" else 1.15)
        P.stroke(np.stack([xs, ys], -1), 0.55, DAN, 0.55, near=True)
    th = np.linspace(0, 2 * math.pi, 64)
    if kind == "drum":
        ox = x + rx * np.clip(np.cos(th) * 1.08, -1, 1)
        oy = y + ry * np.clip(np.sin(th) * 1.05, -1, 1)
    else:
        ox, oy = x + rx * np.cos(th), y + ry * np.sin(th)
    P.stroke(np.stack([ox, oy], -1), 1.05, JIAO, 0.85, dry=0.25, dry_start=0.4, jitter=0.12, near=True)
    for (yc, wc) in ((y - ry - 2.5, rx * 0.62), (y + ry + 2.5, rx * 0.55)):
        line(P, [(x - wc, yc), (x + wc, yc)], 3.0, color=JIAO, alpha=0.95, smooth=False, taper=False, dry=0.1, jitter=0.05)
    for k in (-2.0, 0.0, 2.0):  # 灯穗
        line(P, [(x + k * 0.6, ybot - 1), (x + k, ybot + 13 + abs(k))], 0.8, color=NONG, alpha=0.85, smooth=False)


def paint_lanterns(P: Hub, rng, slots: dict):
    for lid, (x, y, hy, kind) in slots.items():
        rx, ry, ytop, ybot = lantern_geom(x, y, kind)
        paint_lantern(P, x, y, hang_point(x, ytop, hy), kind, rng)


# ============================================================== 人物


def paint_flame_emit(P: Hub, x, y, h, w, gain=1.0, color=None):
    """一小朵火（油灯、蜡烛）：画进发光层，底部在 (x, y)，高 h、宽 w。"""
    r = int(h * 1.6) + 4
    sl = (slice(max(0, int(y - h - r)), min(H, int(y + r))), slice(max(0, int(x - r)), min(W, int(x + r))))
    dx, dy = (P.X[sl] - x) / (w / 2), (P.Y[sl] - y) / h  # dy: 0 在底，-1 在尖
    v = -dy
    width = np.where(v > 0.25, np.clip((1 - v) / 0.75, 0, 1) ** 0.9, np.sqrt(np.clip(1 - ((0.25 - v) / 0.3) ** 2, 0, 1)))
    body = smoothstep(1.05, 0.55, np.abs(dx) / np.maximum(width, 1e-3)) * smoothstep(-0.08, 0.02, v) * smoothstep(1.02, 0.9, v)
    core = np.exp(-((dx / 0.55) ** 2 + ((v - 0.28) / 0.28) ** 2))
    c = FLAME_LIGHT if color is None else color
    e = c[None, None] * (body * 0.85)[..., None] + mixc(c, WHITE, 0.6)[None, None] * (core * 0.9)[..., None]
    P.emit[sl] += e * gain
    return sl


def paint_smith(P: Hub, rng, lights):
    """老灯匠：坐在矮凳上，驼着背、朝左（局部坐标朝右画、整个翻过来），白胡子，系着围裙、挽着袖子，
    一手扶着灯骨、一手拿糨糊刷子糊纸；面前一张案子：糊了一半的灯、一只灯骨、一捆竹篾、糨糊碗，案头一盏油灯。"""
    f = Fig(P, *SMITH_AT, flip=-1)
    bx0, bx1, btop = 62.0, 202.0, -92.0
    # 凳子
    f.brush([(-24, -42), (22, -42)], 2.2, color=NONG, smooth=False, nail=0.5, tail=0.2)
    f.brush([(-18, -40), (-22, 0)], 1.4, color=NONG, smooth=False, nail=0.4, tail=0.1)
    f.brush([(16, -40), (20, 0)], 1.4, color=NONG, smooth=False, nail=0.4, tail=0.1)
    # 腿：裤子，布鞋
    legs = [(-8, -56), (36, -62), (48, -54), (50, -8), (38, -8), (36, -44), (2, -40)]
    f.knock(legs)
    f.wash(legs, WASH_M, 0.5, off=(-1.5, 1.2))
    f.brush([(-6, -58), (34, -63), (48, -55), (51, -30), (50, -8)], 1.5, color=JIAO, press=1.6, dry=0.3)
    f.brush([(36, -44), (38, -8)], 0.9, color=NONG)
    f.brush([(34, -4), (62, -2)], 2.6, color=JIAO, smooth=False, nail=0.9, tail=0.3)
    # 袍子：驼背
    robe = [(-12, -44), (-20, -74), (-18, -104), (-6, -128), (10, -142), (26, -142), (34, -124), (36, -96), (44, -66), (46, -48), (20, -42)]
    f.knock(robe)
    f.wash(robe, WASH_M, 0.6, off=(-2.5, 1.5))
    f.wash([(-12, -46), (-20, -74), (-18, -104), (-6, -128), (8, -140), (4, -110), (-2, -70), (2, -46)], WASH_D, 0.38, soft=2.0)
    # 围裙：留白，边上淡淡一笔
    apron = [(22, -126), (34, -122), (40, -98), (52, -66), (54, -48), (34, -46), (28, -80), (20, -110)]
    f.knock(apron)
    f.wash(apron, WASH_L, 0.2, soft=1.6)
    f.brush([(-12, -44), (-20, -74), (-18, -104), (-6, -128), (12, -142)], 2.4, color=JIAO, press=1.6, dry=0.35, dry_start=0.6)  # 背
    f.brush([(46, -48), (20, -42), (-12, -44)], 1.2, color=NONG, gap=(0.35, 0.5))
    f.brush([(24, -126), (36, -120), (42, -96), (53, -66), (54, -48)], 1.1, color=NONG, press=1.4)  # 围裙边
    f.brush([(20, -110), (26, -80), (32, -48)], 0.8, color=NONG, alpha=0.8)
    f.brush([(2, -98), (36, -100)], 1.0, color=NONG, alpha=0.85)  # 围裙带
    f.brush([(0, -122), (6, -98)], 0.8, color=NONG, alpha=0.75)  # 衣褶
    f.brush([(-6, -80), (-2, -58)], 0.7, color=NONG, alpha=0.7)
    # 远手：挽袖的小臂扶着灯骨
    f.wash([(10, -130), (30, -112), (40, -112), (36, -122), (18, -134)], WASH_M, 0.5, soft=1.4)
    f.brush([(12, -128), (30, -110), (40, -112)], 1.0, color=NONG, press=1.4)
    farm = [(40, -110), (74, -118), (76, -112), (42, -104)]
    f.knock(farm)
    f.brush([(40, -111), (74, -119)], 0.7, color=NONG)
    f.brush([(42, -104), (75, -112)], 0.6, color=NONG)
    hand(f, 77, -116, 3.0)
    # 案板、案腿
    f.brush([(bx0 - 2, btop), (132, btop - 1), (bx1 + 2, btop)], 3.4, color=mixc(NONG, ZHONG, 0.3), nail=0.6, tail=0.15, press=0.2, dry=0.25)
    f.brush([(bx0 + 2, btop + 6), (bx1 - 2, btop + 6)], 0.9, color=NONG, smooth=False, nail=0.2, tail=0.2)
    for x in (bx0 + 8, bx1 - 8):
        f.brush([(x, btop + 7), (x + (2 if x > 100 else -2), 0)], 2.0, color=NONG, smooth=False, nail=0.6, tail=0.1, dry=0.3)
    f.brush([(bx0 + 8, -26), (bx1 - 8, -26)], 1.0, color=NONG, smooth=False, nail=0.3, tail=0.2)
    # 糊了一半的灯：靠人的半边糊了纸，另一半还是竹骨
    lx, ly, lrx, lry = 96.0, -120.0, 16.0, 22.0
    th = np.linspace(math.pi / 2, 3 * math.pi / 2, 24)
    half = [(lx + lrx * math.cos(a), ly + lry * math.sin(a)) for a in th] + [(lx, ly - lry)]
    f.knock(half)
    f.wash(half, WASH_L, 0.3, soft=1.4)
    th2 = np.linspace(-0.3, 2 * math.pi - 0.3, 40)
    f.brush([(lx + lrx * math.cos(a), ly + lry * math.sin(a)) for a in th2], 0.8, color=JIAO, nail=0.4, tail=0.15, press=0.6)
    for k in (0.0, 0.5, 0.85):
        f.brush([(lx + k * lrx * math.cos(a), ly + lry * math.sin(a)) for a in np.linspace(-math.pi / 2, math.pi / 2, 16)], 0.55,
                color=NONG, nail=0.1, tail=0.1, press=0.0)
    f.brush([(lx - lrx * 0.6, ly - lry - 2), (lx + lrx * 0.6, ly - lry - 2)], 1.8, color=JIAO, smooth=False, nail=0.3, tail=0.1)
    f.brush([(lx - lrx * 0.6, ly + lry + 2), (lx + lrx * 0.6, ly + lry + 2)], 1.8, color=JIAO, smooth=False, nail=0.3, tail=0.1)
    # 近手：挽起的袖子（一道卷边）、小臂、手里的糨糊刷
    sleeve = [(16, -136), (42, -108), (48, -112), (40, -124), (24, -140)]
    f.knock(sleeve)
    f.wash(sleeve, WASH_M, 0.55, off=(-1, 1), soft=1.6)
    f.brush([(16, -134), (30, -118), (42, -106)], 1.3, color=JIAO, press=1.5)
    f.brush([(38, -120), (46, -110)], 1.6, color=NONG, smooth=False, nail=0.4, tail=0.3)  # 卷起的袖口
    narm = [(44, -112), (68, -102), (70, -95), (44, -103)]
    f.knock(narm)
    f.brush([(45, -111), (68, -102)], 0.7, color=NONG)
    f.brush([(45, -103), (69, -96)], 0.6, color=NONG)
    f.brush([(64, -104), (100, -128)], 0.9, color=mixc(NONG, ZHESHI, 0.3), smooth=False, nail=0.3, tail=0.0, press=0.0)  # 刷柄
    f.brush([(98, -126), (108, -133)], 2.2, color=JIAO, smooth=False, nail=0.2, tail=0.6)  # 刷头
    hand(f, 70, -100, 3.2)
    # 头：秃顶、后脑一个小髻，朝前低着
    hx, hy, hr = 32.0, -154.0, 14.0
    head = [(hx - hr, hy - 2), (hx - 6, hy - hr), (hx + 6, hy - hr - 1), (hx + hr, hy - 6), (hx + hr + 2, hy + 4), (hx + 6, hy + hr), (hx - 8, hy + 10)]
    f.knock(head)
    f.wash(head, SKIN, 0.3, soft=1.8)
    f.brush([(hx - hr + 2, hy + 6), (hx - hr, hy - 4), (hx - 6, hy - hr + 1), (hx + 4, hy - hr - 1), (hx + hr - 2, hy - 8)], 1.1,
            color=NONG, press=1.2, nail=0.3)
    f.dot(hx - 12, hy - 12, 5.0, mixc(JIAO, NONG, 0.3), 0.95)  # 发髻
    f.wash([(hx - hr - 2, hy - 2), (hx - 8, hy - 8), (hx - 6, hy + 6), (hx - 12, hy + 10)], mixc(DAN, QING, 0.5), 0.45, soft=1.2)  # 鬓边白发
    profile_face(f, hx, hy, hr * 0.92, beard=None, old=True)
    # 长白胡子：留白，几道淡墨的须
    beard = [(hx + 4, hy + 8), (hx + 14, hy + 8), (hx + 16, hy + 24), (hx + 12, hy + 44), (hx + 8, hy + 50), (hx + 4, hy + 30)]
    f.knock(beard)
    for k, (dx, ln) in enumerate(((0.0, 42.0), (5.0, 36.0), (-3.0, 30.0), (9.0, 26.0))):
        f.brush([(hx + 6 + dx * 0.4, hy + 8), (hx + 10 + dx, hy + 8 + ln * 0.5), (hx + 7 + dx * 0.6, hy + 8 + ln)], 0.55, color=DAN,
                nail=0.1, tail=0.6, press=0.3)
    f.brush([(hx + 10, hy + 6), (hx + 18, hy + 9)], 0.9, color=mixc(DAN, QING, 0.4), nail=0.3, tail=0.6)  # 髭
    # 油灯：灯台、灯盏，火苗画进发光层
    lpx = 186.0
    f.brush([(lpx - 9, -93), (lpx + 9, -93)], 1.6, color=JIAO, smooth=False, nail=0.3, tail=0.2)
    f.brush([(lpx, -94), (lpx, -120)], 1.2, color=NONG, smooth=False, nail=0.3, tail=0.1)
    f.fill([(lpx - 9, -124), (lpx + 9, -124), (lpx + 6, -119), (lpx - 6, -119)], NONG, 0.95, mode="over", rim=0.0, smooth=False)
    fx_, fy_ = f.pt(lpx, -124)
    paint_flame_emit(P, fx_, fy_, 16.0, 7.0, gain=1.1)
    lights.append((fx_, fy_ - 10, 250.0, mixc(FLAME_LIGHT, LAMP_LIGHT, 0.5), 0.62, f.fy))
    # 案上：一只灯骨、一捆竹篾、糨糊碗
    for (gx, gy, grx, gry) in ((150.0, -110.0, 11.0, 15.0),):
        f.brush([(gx + grx * math.cos(a), gy + gry * math.sin(a)) for a in th2], 0.7, color=NONG, nail=0.3, tail=0.1, press=0.6)
        for k in (-0.5, 0.5):
            f.brush([(gx + k * grx * math.cos(a), gy + gry * math.sin(a)) for a in np.linspace(-math.pi / 2, math.pi / 2, 12)], 0.5,
                    color=NONG, nail=0.1, tail=0.1, press=0.0)
    for k in range(4):
        f.brush([(132 + k * 1.2, -94 - k * 1.1), (176, -95 - k * 1.5)], 0.5, color=NONG, alpha=0.85, smooth=False, nail=0.1, tail=0.2,
                press=0.0)
    bowl = [(114, -94), (132, -94), (130, -101), (116, -101)]
    f.wash(bowl, WASH_D, 0.7, soft=1.0, smooth=False)
    f.brush([(114, -101), (132, -101)], 1.0, color=JIAO, smooth=False, nail=0.3, tail=0.3)
    # 脚下的影
    gx, gy = f.pt(100, 2)
    T.wash_blob(P, gx, gy, 140.0, 9.0, ZHONG, 0.35, rng)


SKIN = mixc(PAPER, ZHESHI, 0.10)  # 脸和手：纸色里一丝赭
WASH_L, WASH_M, WASH_D = mixc(QING, DAN, 0.5), mixc(DAN, ZHONG, 0.35), mixc(ZHONG, NONG, 0.3)  # 淡、中、重三档墨


def profile_face(f: Fig, hx, hy, r, *, brow=True, beard=None, eye=1.0, nose=1.0, old=False):
    """朝右的侧脸：额、鼻、嘴、下巴一笔勾出，一点眼、一笔眉；beard: None / "stubble" / "long" / "goatee"。"""
    f.brush([(hx + 0.55 * r, hy - 0.95 * r), (hx + 0.85 * r, hy - 0.45 * r), (hx + 1.12 * r * nose, hy + 0.02 * r),
             (hx + 0.86 * r, hy + 0.2 * r), (hx + 0.92 * r, hy + 0.42 * r), (hx + 0.7 * r, hy + 0.78 * r), (hx + 0.2 * r, hy + 1.0 * r)],
            0.75, color=NONG, nail=0.4, tail=0.25, press=1.2)
    ex, ey = hx + 0.48 * r, hy - 0.22 * r
    f.brush([(ex - 0.16 * r, ey - 0.02 * r), (ex + 0.2 * r, ey + 0.03 * r)], 0.75 * eye, color=JIAO, nail=0.3, tail=0.5, smooth=False)
    f.dot(ex + 0.06 * r, ey + 0.06 * r, 0.75 * eye, JIAO, 0.95)
    if brow:
        f.brush([(ex - 0.3 * r, ey - 0.28 * r), (ex + 0.05 * r, ey - 0.36 * r), (ex + 0.3 * r, ey - 0.3 * r)],
                0.85 if not old else 1.2, color=mixc(DAN, QING, 0.5) if old else JIAO, nail=0.5, tail=0.4)
    f.brush([(hx - 0.42 * r, hy - 0.08 * r), (hx - 0.55 * r, hy + 0.12 * r), (hx - 0.4 * r, hy + 0.3 * r)], 0.6, color=NONG, nail=0.2, tail=0.3)  # 耳
    if beard == "stubble":
        for k in range(7):
            t = k / 6
            x = hx + (0.85 - 0.75 * t) * r
            y = hy + (0.45 + 0.5 * math.sin(math.pi * 0.5 * t)) * r
            f.brush([(x, y), (x - 0.12 * r, y + 0.16 * r)], 0.55, color=NONG, alpha=0.7, smooth=False, nail=0.0, tail=0.6)
    elif beard == "goatee":
        f.brush([(hx + 0.86 * r, hy + 0.36 * r), (hx + 1.05 * r, hy + 0.42 * r)], 0.6, color=NONG, smooth=False)  # 髭
        for k, dx in enumerate((0.0, 0.12, -0.1)):
            f.brush([(hx + (0.62 + dx) * r, hy + 0.85 * r), (hx + (0.72 + dx) * r, hy + 1.5 * r), (hx + (0.6 + dx) * r, hy + 2.2 * r - k * 0.2 * r)],
                    0.75, color=NONG, nail=0.3, tail=0.6, dry=0.3)


def hand(f: Fig, x, y, r=3.4, curl=1.0):
    """一只手：纸色一小团，两笔勾出握着的指节。"""
    f.knock([(x - r, y - r * 0.8), (x + r, y - r), (x + r * 1.1, y + r * 0.6), (x - r * 0.6, y + r)])
    f.brush([(x - r * 0.9, y - r * 0.6), (x + r * 0.2, y - r * 1.05), (x + r * 1.05, y - r * 0.2)], 0.55, color=NONG, nail=0.2, tail=0.3)
    f.brush([(x + r * 0.9 * curl, y + r * 0.1), (x + r * 0.3, y + r * 0.95), (x - r * 0.7, y + r * 0.7)], 0.55, color=NONG, nail=0.2, tail=0.3)


def paint_peddler(P: Hub, rng, lights) -> dict:
    """货郎：头往前探、斗笠前沿掀起，露出脸；短褂、裹腿、草鞋，右肩挑着扁担往右走，后头一只筐、前头一只带抽屉的货箱，
    担头挂一盏小红灯；一手扶担，一手摇着拨浪鼓。先擦出留白、淡墨洇两层，再白描勾线。返回影子要用的东西（剪影、灯的位置）。"""
    f = Fig(P, *PEDDLER_AT)
    P.begin("peddler")
    pole = [(-132, -160), (-60, -174), (14, -180), (80, -180), (150, -172)]  # 压在右肩上
    # ---- 后头的筐：绳、筐身淡墨，竹篾几笔
    for (q, r_) in (((-126, -162), (-152, -92)), ((-126, -162), (-98, -92)), ((-126, -162), (-126, -94))):
        f.brush([q, r_], 0.6, color=NONG, smooth=False, nail=0.2, tail=0.0, press=0.0)
    basket = [(-154, -92), (-96, -92), (-100, -40), (-112, -24), (-138, -24), (-150, -40)]
    f.knock(basket)
    f.wash(basket, mixc(DAN, ZHESHI, 0.15), 0.45, off=(-2, 1))
    for k in range(4):
        y = -80 + k * 14
        f.brush([(-151 + k * 1.2, y), (-125, y + 3), (-99 - k * 1.2, y)], 0.6, color=NONG, alpha=0.75, nail=0.2, tail=0.2, press=0.0)
    for k in range(5):
        x = -146 + k * 11
        f.brush([(x, -90), (x + (k - 2) * 1.5, -28)], 0.5, color=NONG, alpha=0.6, smooth=False, nail=0.1, tail=0.3, press=0.0)
    f.brush([(-156, -92), (-125, -95), (-94, -92)], 1.6, color=JIAO, nail=0.8, tail=0.2)
    f.brush([(-154, -90), (-152, -44), (-138, -24), (-112, -24), (-100, -42), (-96, -90)], 1.3, color=JIAO, dry=0.35, dry_start=0.5)
    for (dx, h_) in ((-140, 18), (-128, 24)):  # 筐里冒出来的货：几根杆、一卷布
        f.brush([(dx, -92), (dx + 4, -92 - h_)], 1.0, color=NONG, smooth=False, nail=0.5, tail=0.2)
    f.wash([(-120, -104), (-100, -104), (-98, -92), (-122, -92)], WASH_L, 0.5)
    f.brush([(-122, -94), (-118, -105), (-100, -104), (-98, -93)], 0.8, color=NONG)
    # ---- 腿：裹腿的裤子各一笔，草鞋
    legs = (((-6, -104), (-14, -58), (-30, -12)), ((12, -104), (28, -62), (24, -10)))
    for (hip, knee, ankle) in legs:
        thigh = [(hip[0] - 9, hip[1]), (hip[0] + 9, hip[1]), (knee[0] + 7, knee[1]), (ankle[0] + 4.5, ankle[1]), (ankle[0] - 4.5, ankle[1]),
                 (knee[0] - 7, knee[1])]
        f.knock(thigh, smooth=False)
        f.wash(thigh, WASH_M, 0.5, off=(-1.5, 1), smooth=False, soft=1.8)
        f.brush([(hip[0] - 9, hip[1] + 4), (knee[0] - 7, knee[1]), (ankle[0] - 4.5, ankle[1])], 1.5, color=JIAO, dry=0.3, press=1.4)
        f.brush([(hip[0] + 9, hip[1] + 8), (knee[0] + 7, knee[1] + 2), (ankle[0] + 4.5, ankle[1])], 1.1, color=NONG, press=1.2)
        for t in (0.42, 0.62, 0.82):  # 裹腿
            x = knee[0] + (ankle[0] - knee[0]) * t
            y = knee[1] + (ankle[1] - knee[1]) * t
            f.brush([(x - 5.5, y - 3), (x + 5.5, y + 2)], 0.7, color=NONG, smooth=False, nail=0.3, tail=0.4, press=0.0)
    for (x0, x1, lift) in ((-46, -22, -3), (14, 40, 0)):  # 草鞋：鞋底一笔、两道绳
        f.brush([(x0, lift - 1), (x1, 0)], 1.8, color=JIAO, smooth=False, nail=0.6, tail=0.3)
        f.brush([(x0 + 8, lift - 7), (x0 + 12, lift - 1)], 0.6, color=NONG, smooth=False)
        f.brush([(x1 - 10, -7), (x1 - 6, -1)], 0.6, color=NONG, smooth=False)
    # ---- 短褂
    coat = [(-10, -184), (-22, -170), (-28, -146), (-30, -116), (-26, -102), (24, -102), (34, -110), (32, -146), (24, -172), (16, -182)]
    f.knock(coat)
    f.wash(coat, WASH_M, 0.55, off=(-2.5, 1.5))
    f.wash([(-10, -182), (-22, -168), (-28, -144), (-30, -114), (-24, -104), (-4, -104), (-8, -140)], WASH_D, 0.35, off=(-1, 0))
    f.brush([(-8, -184), (-22, -168), (-28, -140), (-31, -114), (-26, -102)], 2.2, color=JIAO, dry=0.35, dry_start=0.6, press=1.5)
    f.brush([(18, -180), (30, -152), (34, -112)], 1.4, color=JIAO, press=1.2)
    f.brush([(-27, -103), (4, -100), (34, -108)], 1.3, color=NONG, gap=(0.42, 0.55))
    f.brush([(6, -186), (12, -166), (17, -182)], 0.9, color=NONG, smooth=False)  # 衣领
    f.brush([(12, -166), (14, -132), (12, -104)], 0.8, color=NONG)  # 衣襟
    f.brush([(-14, -152), (-8, -134)], 0.8, color=NONG, alpha=0.8)
    f.brush([(22, -142), (27, -124)], 0.7, color=NONG, alpha=0.8)
    f.brush([(-30, -118), (2, -121), (34, -120)], 2.0, color=mixc(NONG, ZHONG, 0.3), press=0.5)  # 腰带
    f.brush([(-4, -120), (-9, -100)], 1.2, color=NONG, nail=0.4, tail=0.6)
    f.brush([(2, -120), (4, -102)], 1.0, color=NONG, nail=0.4, tail=0.6)
    # ---- 扁担
    f.brush(pole, 3.2, color=mixc(NONG, ZHONG, 0.3), nail=0.3, tail=0.0, press=0.2, dry=0.15, dry_start=0.8)
    # ---- 后手：抬起扶着担
    sleeve_b = [(-6, -176), (-26, -162), (-38, -164), (-40, -172), (-28, -174), (-12, -182)]
    f.knock(sleeve_b)
    f.wash(sleeve_b, WASH_M, 0.5, off=(-1, 1))
    f.brush([(-6, -174), (-30, -155), (-38, -166)], 1.3, color=JIAO, press=1.6)
    f.brush([(-10, -182), (-28, -172), (-38, -174)], 0.9, color=NONG)
    hand(f, -42, -175, 3.6)
    # ---- 头、脸：头往前探
    hx, hy, hr = 20.0, -194.0, 10.5
    head = [(hx - hr, hy - 2), (hx - 4, hy - hr), (hx + hr, hy - 6), (hx + hr * 1.1, hy + 4), (hx + 4, hy + hr), (hx - hr, hy + 6)]
    f.knock(head)
    f.wash(head, SKIN, 0.35, soft=2.0)
    f.wash([(hx - hr - 1, hy - 4), (hx - 2, hy - hr), (hx + 2, hy - 2), (hx - 2, hy + 6), (hx - hr, hy + 8)], WASH_D, 0.8, soft=1.5)  # 头发
    profile_face(f, hx, hy, hr, beard="stubble")
    f.brush([(hx - 6, hy + hr - 1), (hx - 4, hy + hr + 8)], 0.9, color=NONG)  # 颈
    # ---- 斗笠：前沿掀起，底下露出脸
    hat = [(-46, -196), (-10, -207), (4, -246), (26, -224), (62, -218), (20, -206)]
    f.knock(hat, smooth=False)
    f.wash(hat, mixc(DAN, ZHESHI, 0.3), 0.5, off=(-1.5, 1), smooth=False, soft=1.6)
    f.wash([(-44, -197), (20, -205), (62, -217), (20, -210)], WASH_D, 0.55, smooth=False, soft=1.2)  # 笠沿底下的暗
    for k in range(-4, 6):
        t = (k + 4) / 9
        bx = -40 + 96 * t
        by = -199 - 18 * t
        f.brush([(4, -243), (bx, by)], 0.5, color=NONG, alpha=0.6, smooth=False, nail=0.0, tail=0.2, press=0.0)
    f.brush([(-48, -195), (-10, -206), (4, -247)], 1.5, color=JIAO, smooth=False, nail=0.6, tail=0.1)
    f.brush([(4, -247), (28, -224), (64, -218)], 1.5, color=JIAO, smooth=False, nail=0.4, tail=0.3)
    f.brush([(-48, -195), (8, -203), (64, -218)], 1.8, color=JIAO, nail=0.7, tail=0.25, dry=0.3, dry_start=0.5)
    # ---- 前头的货箱
    for (q, r_) in (((140, -174), (106, -118)), ((140, -174), (172, -118))):
        f.brush([q, r_], 0.6, color=NONG, smooth=False, nail=0.2, tail=0.0, press=0.0)
    box = [(104, -118), (174, -118), (174, -22), (104, -22)]
    f.knock(box, smooth=False)
    f.wash(box, WASH_M, 0.5, off=(-2, 1.5), smooth=False, soft=2.0)
    f.wash([(104, -118), (174, -118), (168, -128), (110, -128)], WASH_L, 0.5, smooth=False, soft=1.2)
    f.brush([(102, -118), (139, -119), (176, -118)], 1.6, color=JIAO, nail=0.7, tail=0.2)
    f.brush([(104, -116), (104, -22)], 1.5, color=JIAO, smooth=False, nail=0.8, tail=0.1, dry=0.3)
    f.brush([(174, -116), (175, -22)], 1.2, color=JIAO, smooth=False, nail=0.6, tail=0.1)
    f.brush([(102, -22), (176, -22)], 1.4, color=JIAO, smooth=False, nail=0.6, tail=0.2)
    for (q, r_) in (((106, -86), (172, -86)), ((106, -54), (172, -54)), ((139, -86), (139, -24))):
        f.brush([q, r_], 0.8, color=NONG, smooth=False, nail=0.3, tail=0.2, press=0.0)
    for (x, y) in ((139, -102), (121, -70), (157, -70), (121, -38), (157, -38)):
        f.dot(x, y, 1.8, NONG, 0.9)
    # ---- 担头的小红灯
    lx, ly = 156.0, -150.0
    f.brush([(150, -172), (lx, ly - 13)], 0.7, color=NONG, smooth=False, nail=0.2, tail=0.0, press=0.0)
    gx, gy = f.pt(lx, ly)
    sl = (slice(int(gy - 20), int(gy + 20)), slice(int(gx - 16), int(gx + 16)))
    rho = np.hypot((P.X[sl] - gx) / 9.5, (P.Y[sl] - gy) / 11.5)
    body = smoothstep(1.05, 0.85, rho)
    P.over(body * 0.95, mixc(ZHUSHA, PAPER, 0.15), sl)
    P.mark_near(body, sl)
    P.emit[sl] += (body * (0.30 + 0.45 * np.exp(-(rho / 0.6) ** 2)))[..., None] * mixc(ZHUSHA, FLAME_LIGHT, 0.55)
    f.brush([(lx - 6, ly - 12), (lx + 6, ly - 12)], 1.6, color=JIAO, smooth=False, nail=0.2, tail=0.0, press=0.0)
    f.brush([(lx - 6, ly + 12), (lx + 6, ly + 12)], 1.6, color=JIAO, smooth=False, nail=0.2, tail=0.0, press=0.0)
    f.brush([(lx, ly + 13), (lx, ly + 24)], 0.7, color=NONG, smooth=False, nail=0.0, tail=0.5)
    lights.append((gx, gy, 270.0, mixc(LAMP_LIGHT, mixc(ZHUSHA, FLAME_LIGHT, 0.6), 0.45), 0.6, f.fy + 2))
    # ---- 前手：袖子、手里的拨浪鼓
    sleeve_f = [(16, -178), (32, -158), (44, -150), (48, -158), (36, -170), (24, -182)]
    f.knock(sleeve_f)
    f.wash(sleeve_f, WASH_M, 0.5, off=(-1, 1))
    f.brush([(16, -176), (34, -150), (46, -152)], 1.3, color=JIAO, press=1.6)
    f.brush([(24, -182), (38, -168), (48, -160)], 0.9, color=NONG)
    f.brush([(54, -162), (58, -192)], 0.8, color=mixc(NONG, ZHESHI, 0.3), smooth=False, nail=0.2, tail=0.0, press=0.0)  # 鼓柄
    hand(f, 53, -160, 3.4)
    gx_, gy_ = f.pt(58.5, -199)
    f.knock([(51, -207), (66, -207), (66, -191), (51, -191)])
    f.wash([(51, -207), (66, -207), (66, -191), (51, -191)], mixc(DAN, ZHESHI, 0.25), 0.4, soft=1.2)
    th = np.linspace(0.2, 2 * math.pi + 0.1, 30)
    f.brush([(58.5 + 7 * math.cos(a), -199 + 8 * math.sin(a)) for a in th], 0.9, color=JIAO, nail=0.4, tail=0.2)
    for sx in (-1, 1):
        f.brush([(58.5 + sx * 7, -199), (58.5 + sx * 14, -195)], 0.45, color=NONG, smooth=False, nail=0.0, tail=0.0, press=0.0)
        f.dot(58.5 + sx * 15, -195, 2.0, NONG)
    sil = P.end("peddler")
    # 脚下的影：从脚往左后方拖到墙脚
    gx0, gy0 = f.pt(-48, -14)
    T.wash_blob(P, gx0, gy0, 92.0, 11.0, ZHONG, 0.45, rng, ang=0.18)
    # 尾巴：只在墙上的影子里——腿后面一道软软的、蓬松的弯
    tail = f.pts([(-18, -100), (-38, -92), (-60, -94), (-80, -104), (-94, -122), (-98, -138), (-90, -142), (-84, -128), (-70, -114),
                  (-52, -108), (-34, -108), (-20, -110)])
    tsl, tm = shape_cover(closed_curve(tail), soft=2.5, pad=10)
    sil[tsl] = np.maximum(sil[tsl], 0.9 * tm)
    return {"sil": sil, "light": (gx, gy)}


def paint_child(P: Hub, rng, lights):
    """灯童：坐在门槛上，侧身朝右，抱着膝，两个小发髻；一手牵着兔子灯的竹棍（白纸兔、红眼、两只轮子），望着门外的路。"""
    f = Fig(P, *CHILD_AT)
    seat = SILL_Y - f.fy  # 门槛上沿（局部坐标）
    # 裤腿、小鞋
    legs = [(-8, seat - 6), (20, seat - 26), (30, seat - 22), (34, -6), (24, -6), (20, seat - 12), (-2, seat + 2)]
    f.knock(legs)
    f.wash(legs, WASH_L, 0.45, off=(-1, 1), soft=1.6)
    f.brush([(-6, seat - 8), (20, seat - 27), (29, seat - 22), (33, -6)], 1.1, color=JIAO, press=1.6)
    f.brush([(4, seat - 2), (19, seat - 12), (24, -6)], 0.8, color=NONG)
    f.brush([(22, -4), (38, -3)], 2.4, color=JIAO, smooth=False, nail=0.8, tail=0.3)
    # 小褂：弓着背
    coat = [(2, seat - 54), (-10, seat - 42), (-15, seat - 22), (-13, seat - 2), (6, seat), (18, seat - 16), (22, seat - 30), (16, seat - 46),
            (10, seat - 54)]
    f.knock(coat)
    f.wash(coat, WASH_M, 0.6, off=(-1.5, 1.2), soft=1.8)
    f.wash([(2, seat - 52), (-10, seat - 40), (-14, seat - 20), (-12, seat - 4), (-2, seat - 6), (-4, seat - 36)], WASH_D, 0.4, soft=1.4)
    f.brush([(2, seat - 54), (-10, seat - 42), (-15, seat - 22), (-13, seat - 1)], 1.6, color=JIAO, press=1.6, dry=0.3)
    f.brush([(-13, seat - 1), (6, seat + 1)], 1.0, color=NONG, smooth=False)
    f.brush([(-6, seat - 30), (-2, seat - 16)], 0.7, color=NONG, alpha=0.8)  # 衣褶
    # 抱膝的手臂：袖子绕到膝前，手攥着竹棍
    arm = [(4, seat - 48), (14, seat - 30), (26, seat - 26), (30, seat - 32), (18, seat - 40), (10, seat - 52)]
    f.knock(arm)
    f.wash(arm, WASH_M, 0.55, off=(-1, 1), soft=1.6)
    f.brush([(4, seat - 46), (12, seat - 32), (26, seat - 27)], 1.1, color=JIAO, press=1.6)
    f.brush([(10, seat - 50), (20, seat - 40), (29, seat - 33)], 0.7, color=NONG)
    f.brush([(31, seat - 30), (62, -20)], 0.8, color=mixc(NONG, ZHESHI, 0.3), smooth=False, nail=0.3, tail=0.0, press=0.0)  # 竹棍
    hand(f, 31, seat - 30, 2.8)
    # 头：圆脸、后脑的头发、两个发髻
    hx, hy, hr = 8.0, seat - 66, 12.0
    head = [(hx - hr, hy), (hx - 6, hy - hr), (hx + 6, hy - hr), (hx + hr, hy - 2), (hx + hr * 0.9, hy + 7), (hx + 3, hy + hr), (hx - 8, hy + 8)]
    f.knock(head)
    f.wash(head, SKIN, 0.35, soft=1.8)
    f.wash([(hx - hr - 1, hy + 2), (hx - 8, hy - hr), (hx + 4, hy - hr - 1), (hx + 2, hy - 5), (hx - 3, hy + 3), (hx - 7, hy + 9)], WASH_D, 0.85,
           soft=1.4)
    for (bx, by, br) in ((hx - 5, hy - 15, 6.2), (hx + 7, hy - 17, 5.6)):  # 发髻：两团湿墨
        f.dot(bx, by, br, mixc(JIAO, NONG, 0.4), 0.95)
        f.brush([(bx - br * 0.7, by + br * 0.4), (bx + br * 0.6, by + br * 0.5)], 0.7, color=mixc(PAPER, QING, 0.3), alpha=0.6, smooth=False)
    # 侧脸：圆圆的额头、小鼻子、一点眼
    f.brush([(hx + 6, hy - hr + 1), (hx + hr, hy - 3), (hx + hr + 2, hy + 1), (hx + hr - 0.5, hy + 3), (hx + hr, hy + 6), (hx + 6, hy + hr)],
            0.7, color=NONG, nail=0.3, tail=0.3, press=1.2)
    f.dot(hx + 6.5, hy - 1, 1.1, JIAO, 0.95)
    f.brush([(hx + 4, hy - 4.5), (hx + 8.5, hy - 5)], 0.6, color=NONG, smooth=False)
    f.wash([(hx + 1, hy + 2), (hx + 6, hy + 2), (hx + 6, hy + 6), (hx + 1, hy + 6)], ZHUSHA, 0.12, soft=1.2)  # 脸蛋一点红（在灯光里）
    # 兔子灯：在台阶上
    rb = (82.0, -14.0)
    gx, gy = f.pt(*rb)
    for wx in (rb[0] - 12, rb[0] + 10):  # 轮子
        th = np.linspace(0, 2 * math.pi, 24)
        f.line([(wx + 5 * math.cos(a), -5 + 5 * math.sin(a)) for a in th], 1.0, color=JIAO, taper=False)
    sl = (slice(int(gy - 40), int(gy + 18)), slice(int(gx - 32), int(gx + 34)))
    X, Y = P.X[sl], P.Y[sl]
    bm = smoothstep(1.05, 0.88, np.hypot((X - gx) / 18.0, (Y - gy) / 10.5))
    hm = smoothstep(1.05, 0.85, np.hypot((X - gx - 17) / 8.0, (Y - gy + 9) / 7.0))
    ears = np.maximum(smoothstep(1.05, 0.8, np.hypot((X - gx - 13) / 2.8, (Y - gy + 25) / 9.0)),
                      smoothstep(1.05, 0.8, np.hypot((X - gx - 20) / 2.6, (Y - gy + 24) / 9.0)))
    tailm = smoothstep(1.05, 0.8, np.hypot((X - gx + 19) / 4.0, (Y - gy + 3) / 4.0))
    rabbit = np.clip(bm + hm + ears + tailm, 0, 1)
    P.over(rabbit * 0.97, mixc(PAPER, WHITE, 0.4), sl)
    P.mark_near(rabbit, sl)
    P.emit[sl] += (rabbit * (0.25 + 0.5 * np.exp(-(np.hypot((X - gx) / 14, (Y - gy) / 9)) ** 2)))[..., None] * mixc(LAMP_LIGHT, WHITE, 0.3)
    edge = rabbit * (1 - smoothstep(0.35, 0.9, blur(rabbit, 1.2)))
    P.over(np.clip(edge * 1.4, 0, 0.85), NONG, sl)
    P.dot(gx + 21, gy - 10, 1.5, 1.5, ZHUSHA, 0.95)  # 红眼（在灯光里）
    lights.append((gx + 2, gy - 4, 215.0, mixc(LAMP_LIGHT, WHITE, 0.15), 0.58, f.fy + 2))
    # 坐处的影
    sx_, sy_ = f.pt(22, seat + 10)
    T.wash_blob(P, sx_, sy_, 46.0, 5.0, ZHONG, 0.35, rng)


def paint_teller(P: Hub, rng, lights):
    """说书人：檐下桌边坐在凳上，戴一顶软巾（脑后垂两根巾带），长衫宽袖，一手举着折扇，一手按在桌上的醒木旁；
    桌上一本撕残的书、一支蜡烛。"""
    f = Fig(P, *TELLER_AT)
    gown = mixc(mixc(QING, DAN, 0.4), HUAQING, 0.12)  # 长衫：淡墨里一丝花青
    # 凳子：长衫后面露出两条腿
    f.brush([(-30, -50), (-34, 0)], 1.5, color=NONG, smooth=False, nail=0.5, tail=0.1)
    f.brush([(-8, -50), (-6, 0)], 1.5, color=NONG, smooth=False, nail=0.5, tail=0.1)
    # 小腿、鞋：从衣摆下面伸出来
    f.brush([(40, -26), (42, -6)], 3.6, color=mixc(ZHONG, NONG, 0.3), smooth=False, nail=0.3, tail=0.0, press=0.0)
    f.brush([(32, -3), (58, -2)], 2.6, color=JIAO, smooth=False, nail=0.9, tail=0.3)
    # 长衫：上身坐直，腿往前搭到膝，衣摆从膝盖垂下来
    gown_p = [(-20, -128), (-26, -104), (-28, -78), (-32, -56), (-30, -40), (-14, -40), (6, -36), (30, -26), (50, -24), (54, -44),
              (50, -62), (26, -66), (20, -92), (20, -126), (2, -134)]
    f.knock(gown_p)
    f.wash(gown_p, gown, 0.6, off=(-2.5, 1.5))
    f.wash([(-20, -126), (-26, -104), (-28, -78), (-32, -56), (-30, -42), (-14, -44), (-8, -80), (-4, -120)], WASH_M, 0.32, soft=2.0)
    f.wash([(20, -70), (36, -64), (50, -60), (52, -46), (36, -50), (22, -58)], WASH_M, 0.25, soft=1.6)  # 膝上的折
    f.brush([(-20, -128), (-26, -104), (-28, -78), (-32, -56), (-30, -40)], 2.2, color=JIAO, press=1.6, dry=0.3, dry_start=0.6)
    f.brush([(20, -76), (36, -66), (50, -62), (54, -44), (50, -24)], 1.4, color=JIAO, press=1.6)  # 膝
    f.brush([(-14, -40), (6, -36), (30, -26), (50, -24)], 1.1, color=NONG, gap=(0.45, 0.58))  # 衣摆
    f.brush([(2, -132), (8, -100), (10, -72)], 0.8, color=NONG, alpha=0.85)  # 衣襟
    f.brush([(-12, -100), (-14, -60)], 0.7, color=NONG, alpha=0.7)
    f.brush([(-24, -84), (-2, -86), (20, -84)], 1.4, color=mixc(ZHONG, DAN, 0.2), press=0.4)  # 腰带
    # 桌子：桌面、牙板、桌腿
    tx0, tx1, ttop = 62.0, 172.0, -84.0
    f.wash([(tx0, ttop), (tx1, ttop), (tx1, ttop + 18), (tx0, ttop + 18)], WASH_M, 0.55, smooth=False, soft=1.2)
    f.brush([(tx0 - 2, ttop), (117, ttop - 1), (tx1 + 2, ttop)], 2.6, color=mixc(NONG, ZHONG, 0.3), nail=0.6, tail=0.15, press=0.2, dry=0.2)
    f.brush([(tx0 + 6, ttop + 18), (tx1 - 6, ttop + 18)], 0.9, color=NONG, smooth=False, nail=0.2, tail=0.2)
    for x in (tx0 + 6, tx1 - 6):
        f.brush([(x, ttop + 6), (x, 0)], 2.0, color=NONG, smooth=False, nail=0.6, tail=0.1, dry=0.25)
    # 后手：伸到桌上，按在醒木旁
    arm_b = [(-6, -122), (12, -96), (56, -90), (56, -82), (10, -88), (-12, -112)]
    f.knock(arm_b)
    f.wash(arm_b, gown, 0.55, off=(-1, 1), soft=1.6)
    f.brush([(-6, -120), (12, -94), (54, -88)], 1.2, color=JIAO, press=1.5)
    f.brush([(-10, -112), (10, -88), (54, -82)], 0.8, color=NONG)
    hand(f, 60, -87, 3.2)
    # 头、软巾、山羊胡
    hx, hy, hr = 6.0, -148.0, 12.5
    head = [(hx - hr, hy), (hx - 6, hy - hr), (hx + 6, hy - hr), (hx + hr, hy - 3), (hx + hr + 1, hy + 5), (hx + 4, hy + hr), (hx - 8, hy + 9)]
    f.knock(head)
    f.wash(head, SKIN, 0.3, soft=1.8)
    cap = [(hx - hr - 2, hy - 2), (hx - hr + 1, hy - 12), (hx - 2, hy - hr - 6), (hx + 9, hy - hr - 3), (hx + hr + 1, hy - 6), (hx + 4, hy - 7),
           (hx - 6, hy - 4)]
    f.wash(cap, WASH_D, 0.85, soft=1.3)
    f.brush([(hx - hr - 2, hy - 2), (hx - hr + 1, hy - 12), (hx - 2, hy - hr - 6), (hx + 9, hy - hr - 3), (hx + hr + 1, hy - 6)], 1.2,
            color=JIAO, press=1.4, nail=0.4)
    f.brush([(hx - hr, hy - 4), (hx - hr - 7, hy + 10), (hx - hr - 9, hy + 24)], 1.2, color=NONG, nail=0.6, tail=0.5)  # 巾带
    f.brush([(hx - hr + 3, hy - 3), (hx - hr - 2, hy + 12), (hx - hr - 3, hy + 22)], 1.0, color=NONG, nail=0.5, tail=0.5)
    profile_face(f, hx, hy, hr, beard="goatee")
    # 书：摊开，右页撕掉一半，几行字
    book = [(76, ttop - 1), (100, ttop - 3), (102, ttop - 1), (128, ttop - 4), (124, ttop - 9), (120, ttop - 7), (116, ttop - 12),
            (108, ttop - 9), (102, ttop - 12), (78, ttop - 10)]
    f.knock(book, smooth=False)
    f.brush(book[:2] + [(102, ttop - 1), (128, ttop - 4)], 0.6, color=NONG, smooth=False, nail=0.2, tail=0.2, press=0.0)
    f.brush([(78, ttop - 10), (102, ttop - 12), (108, ttop - 9), (116, ttop - 12), (120, ttop - 7), (124, ttop - 9), (128, ttop - 4)], 0.6,
            color=NONG, smooth=False, nail=0.2, tail=0.2, press=0.0)
    f.brush([(76, ttop - 1), (78, ttop - 10)], 0.6, color=NONG, smooth=False, nail=0.2, tail=0.2, press=0.0)
    for k in range(4):
        f.brush([(82 + k * 5, ttop - 3), (84 + k * 5, ttop - 9)], 0.4, color=NONG, alpha=0.75, smooth=False, nail=0.0, tail=0.3, press=0.0)
    # 醒木
    f.fill([(64, ttop - 1), (76, ttop - 1), (75, ttop - 7), (65, ttop - 7)], JIAO, 0.97, mode="over", rim=0.0, smooth=False)
    # 蜡烛：烛台、白蜡，火苗画进发光层
    cx = 154.0
    f.brush([(cx - 8, ttop - 1), (cx + 8, ttop - 1)], 1.5, color=JIAO, smooth=False, nail=0.3, tail=0.2)
    f.brush([(cx, ttop - 2), (cx, ttop - 14)], 1.2, color=NONG, smooth=False, nail=0.2, tail=0.0)
    f.brush([(cx - 6, ttop - 14), (cx + 6, ttop - 14)], 1.1, color=JIAO, smooth=False, nail=0.2, tail=0.2)
    f.knock([(cx - 3.5, ttop - 15), (cx + 3.5, ttop - 15), (cx + 3.5, ttop - 38), (cx - 3.5, ttop - 38)], smooth=False)
    f.brush([(cx - 3.6, ttop - 15), (cx - 3.6, ttop - 38)], 0.5, color=DAN, smooth=False, nail=0.0, tail=0.0, press=0.0)
    fx_, fy_ = f.pt(cx, ttop - 39)
    paint_flame_emit(P, fx_, fy_, 15.0, 6.0, gain=1.05, color=mixc(FLAME_LIGHT, LAMP_LIGHT, 0.5))
    lights.append((fx_, fy_ - 8, 255.0, mixc(LAMP_LIGHT, FLAME_LIGHT, 0.25), 0.6, PORCH_Y + 2))
    # 前手：宽袖垂着，手举起折扇
    sleeve = [(12, -126), (34, -102), (52, -108), (52, -122), (30, -132)]
    f.knock(sleeve)
    f.wash(sleeve, gown, 0.6, off=(-1, 1.5), soft=1.8)
    f.brush([(12, -126), (24, -110), (34, -101), (52, -108)], 1.3, color=JIAO, press=1.6)
    f.brush([(30, -132), (48, -124)], 0.8, color=NONG)
    f.knock([(46, -122), (54, -122), (57, -142), (50, -142)], smooth=False)
    f.brush([(47, -120), (52, -142)], 0.6, color=NONG, smooth=False)
    pv = (58.0, -146.0)
    a0, a1, R, r0 = math.radians(-128), math.radians(-26), 34.0, 8.0
    th = np.linspace(a0, a1, 24)
    fan = [(pv[0] + R * math.cos(a), pv[1] + R * math.sin(a)) for a in th] + \
          [(pv[0] + r0 * math.cos(a), pv[1] + r0 * math.sin(a)) for a in th[::-1]]
    f.knock(fan, smooth=False)
    f.wash(fan, WASH_L, 0.18, smooth=False, soft=1.2)
    for a in np.linspace(a0, a1, 9):
        f.brush([(pv[0] + 3 * math.cos(a), pv[1] + 3 * math.sin(a)), (pv[0] + R * math.cos(a), pv[1] + R * math.sin(a))], 0.45, color=NONG,
                alpha=0.75, smooth=False, nail=0.0, tail=0.2, press=0.0)
    f.brush([(pv[0] + R * math.cos(a), pv[1] + R * math.sin(a)) for a in th], 1.0, color=JIAO, nail=0.5, tail=0.15, press=0.4)
    for a in (a0, a1):
        f.brush([pv, (pv[0] + R * math.cos(a), pv[1] + R * math.sin(a))], 0.8, color=JIAO, smooth=False, nail=0.3, tail=0.1, press=0.0)
    hand(f, 56, -144, 3.0)
    T.wash_blob(P, f.fx + 40, PORCH_Y + 2, 110.0, 6.0, ZHONG, 0.3, rng)


# ============================================================== 光与收尾


def light_terms(P: Hub, lights, seed: int) -> np.ndarray:
    """几盏灯在光照图里的贡献（暖光池）：用 title_screen.light_map 算（带灯 − 不带灯，噪声序列相同，所以夜色底相减抵掉）。"""
    with_l = T.light_map(P, lights, np.random.default_rng(seed))
    base = T.light_map(P, [], np.random.default_rng(seed))
    return with_l - base


def night_ambient(P: Hub, rng) -> np.ndarray:
    """长夜的底：灰（纸色兑一点灰，不偏蓝），月亮附近亮一点，雾在月光里微微发亮。"""
    amb = NIGHT_AMB * (1 + 0.10 * noise(rng, (H, W), (300.0, 120.0)))
    mx, my, mr = MOON
    d = np.hypot(P.X - mx, (P.Y - my) * 1.1)
    moon = 0.015 + 0.11 * np.exp(-(d / 650.0) ** 2) + 0.12 * np.exp(-(d / 200.0) ** 2)
    mist = P.mist * (1 - P.near) * (0.06 + 0.12 * np.exp(-(d / 900.0) ** 2))
    g = (amb + moon + mist)[..., None]
    return g * mixc(WHITE, PAPER / PAPER.max(), 0.22)[None, None]


def wall_shadow(P: Hub, sil: np.ndarray, light, wall_vis: np.ndarray, k: float = 1.4) -> np.ndarray:
    """货郎的影子投在白墙上：剪影从灯的位置按 k 倍往外放大（墙在人后面），只落在看得见的墙面上，边缘略虚。"""
    lx, ly = light
    ys, xs = np.nonzero(wall_vis > 0.01)
    out = np.zeros((H, W))
    if len(xs) == 0:
        return out
    x0, x1, y0, y1 = xs.min(), xs.max() + 1, ys.min(), ys.max() + 1
    X, Y = P.X[y0:y1, x0:x1], P.Y[y0:y1, x0:x1]
    sx = lx + (X - lx) / k - 0.5
    sy = ly + (Y - ly) / k - 0.5
    ix, iy = np.floor(sx).astype(int), np.floor(sy).astype(int)
    fx, fy = sx - ix, sy - iy
    ok = (ix >= 0) & (iy >= 0) & (ix < W - 1) & (iy < H - 1)
    ix, iy = np.clip(ix, 0, W - 2), np.clip(iy, 0, H - 2)
    v = (sil[iy, ix] * (1 - fx) * (1 - fy) + sil[iy, ix + 1] * fx * (1 - fy) + sil[iy + 1, ix] * (1 - fx) * fy
         + sil[iy + 1, ix + 1] * fx * fy) * ok
    out[y0:y1, x0:x1] = smoothstep(0.04, 0.28, v)
    out = blur(out, 1.4)
    return out * wall_vis


def finish(P: Hub, lm: np.ndarray, paper0: np.ndarray) -> tuple[np.ndarray, dict]:
    """画 × 光照图 + 发光层和辉光；纸纹在暗处也看得见，四边微微压暗。返回 (画面, 收尾参数)：叠层要用同样的纸纹和暗角。"""
    out = P.rgb * np.clip(lm, 0, 1.08)
    e = P.emit
    out = out * (1 - np.clip(e.max(-1, keepdims=True), 0, 1) * 0.6) + e + 0.55 * T.bloom(e, 5.0) + 0.45 * T.bloom(e, 22.0)
    rel = paper0.mean(-1) / paper0.mean()
    rel = rel - blur(rel, 40.0) / blur(np.ones_like(rel), 40.0) + 1.0
    lum = out.mean(-1, keepdims=True)
    gain = 1.3 + 1.6 * (1 - smoothstep(0.08, 0.6, lum))
    out = out * (1 + gain * (rel[..., None] - 1))
    rx = (P.X - W / 2) / (W / 2)
    ry = (P.Y - H / 2) / (H / 2)
    vig = 1 - 0.16 * smoothstep(0.7, 1.08, np.maximum(np.abs(rx) * 0.95, np.abs(ry)))
    out = np.clip(out * vig[..., None], 0, 1)
    return out, {"rel": rel, "vig": vig}


def put_seal(img: Image.Image) -> Image.Image:
    """右下角一方朱砂印“灯驿”（白文，title_screen.make_seal）。"""
    seal = T.make_seal("灯驿", SEAL_PX, np.random.default_rng(SEED + 99))
    im = img.convert("RGBA")
    im.alpha_composite(seal, SEAL_AT)
    return im.convert("RGB")


# ============================================================== 总装：画


def paint() -> dict:
    """画整幅画，返回底图和叠层要用的全部中间结果。"""
    t0 = time.perf_counter()
    rng = np.random.default_rng(SEED)
    ids = meta_ids()
    slots = lamp_slots(ids)
    P = Hub(rng)
    paper0 = P.rgb.copy()
    P.paper0 = paper0
    paint_sky(P, rng)
    paint_far(P, rng)
    P.begin("front")  # 远山以后画的都算挡在远山前面（晨光只落在露出来的山和天上）
    paint_beyond(P, rng)
    paint_ground(P, rng)
    paint_wall(P, rng, -20.0, WALL_X1)
    paint_wall(P, rng, POSTS[1], HALL_X0)
    P.begin("after_wall")  # 白墙以后画的：挡住墙上的影子
    paint_gatehouse(P, rng)
    paint_tally(P, rng, DOOR[1] + 5.0, 636.0)
    paint_clepsydra(P, rng)
    paint_hall(P, rng)
    paint_drum(P, rng)
    lights: list = []
    paint_tree(P, rng, slots)
    paint_lanterns(P, rng, slots)
    paint_smith(P, rng, lights)
    ped = paint_peddler(P, rng, lights)
    paint_child(P, rng, lights)
    paint_teller(P, rng, lights)
    paint_grass(P, rng, [(60, 772, 0.9), (200, 772, 0.7), (540, 816, 1.0), (628, 818, 0.8), (1010, 772, 0.8), (1060, 798, 0.7),
                         (1262, 800, 0.8), (1350, 804, 0.9), (720, 772, 0.6), (1700, 806, 0.7)])
    after_wall = P.end("after_wall")
    front = P.end("front")
    t_paint = time.perf_counter() - t0
    # ---- 光照
    wall_mask = np.zeros((H, W))
    wall_mask[int(WALL_TOP + 4):int(WALL_BASE), 0:int(WALL_X1)] = 1.0
    wall_vis = blur(wall_mask, 1.0) * (1 - np.clip(after_wall * 1.5, 0, 1))
    shadow = wall_shadow(P, ped["sil"], ped["light"], wall_vis)
    lm = night_ambient(P, np.random.default_rng(SEED + 5))
    lseed = SEED + 6
    lm0 = T.light_map(P, [], np.random.default_rng(lseed))
    lt = np.zeros((H, W, 3))
    for L in lights:  # 每盏灯单独算：脚下往前的地上压暗一些（名字写在那里），灯光集中在人身上
        term = T.light_map(P, [L], np.random.default_rng(lseed)) - lm0
        gy = L[5]
        lt += term * (1 - 0.7 * smoothstep(gy + 8, gy + 60, P.Y))[..., None]
    # 货郎的灯：墙上一大片斜照的光，影子落在这片光里
    gx, gy = ped["light"]
    wash = (gx - 210.0, gy - 20.0, 320.0, mixc(LAMP_LIGHT, mixc(ZHUSHA, FLAME_LIGHT, 0.6), 0.4), 0.5, None)
    lt += (T.light_map(P, [wash], np.random.default_rng(lseed)) - lm0) * wall_vis[..., None]
    lm = lm * (1 - 0.2 * shadow)[..., None] + lt * (1 - 0.85 * shadow)[..., None]
    out, fin = finish(P, lm, paper0)
    img = put_seal(Image.fromarray((out * 255 + 0.5).astype(np.uint8), "RGB"))
    return {"P": P, "img": img, "lm": lm, "fin": fin, "front": front, "slots": slots, "ids": ids, "lights": lights,
            "shadow": shadow, "paper0": paper0, "t_paint": t_paint, "t_total": time.perf_counter() - t0}


# ============================================================== 叠层：心灯


def crop_box(cx, cy, rx, ry):
    x0, y0 = max(0, int(math.floor(cx - rx))), max(0, int(math.floor(cy - ry)))
    x1, y1 = min(W, int(math.ceil(cx + rx))), min(H, int(math.ceil(cy + ry)))
    return x0, y0, x1 - x0, y1 - y0


def lamp_layers(R: dict, lid: str) -> dict:
    """一盏心灯点亮的四层：灯身（普通）、火苗（普通）、内圈（叠加）、外圈光晕（叠加）。返回 {层: (RGBA 数组 0..1, rect, 附加)}。"""
    x, y, hy, kind = R["slots"][lid]
    rx, ry, ytop, ybot = lantern_geom(x, y, kind)
    rel, vig = R["fin"]["rel"], R["fin"]["vig"]
    tint = ELEMENT_TINT.get(lid[3:]) if lid.startswith("wu_") else None
    out = {}
    # ---- 灯身：纸透出光，中心暖白，往边上转成橙；竹骨是暖褐的细线；只在墨线以里（墨线和上下箍保持原样）
    ss = 4
    bx, by, bw, bh = crop_box(x, y, rx + 3, ry + 3)
    X, Y = V.grid(bh, bw, ss)
    X, Y = X + bx, Y + by
    dx, dy = (X - x) / rx, (Y - y) / ry
    rho = np.maximum(np.hypot(dx, dy * 0.75), np.abs(dy)) if kind == "drum" else np.hypot(dx, dy)
    inside = smoothstep(0.93, 0.80, rho) * smoothstep(-1.0, -0.86, dy) * smoothstep(1.0, 0.86, dy)
    hot = np.exp(-((dx / 0.55) ** 2 + ((dy - 0.15) / 0.65) ** 2))
    edge = smoothstep(0.35, 0.95, rho)
    c_hot, c_mid, c_edge = col("#FFD48C"), col("#EE9E4E"), col("#B45E24")  # 叠加的内圈、外圈还会再加亮，灯身本身偏橙
    rgb = mixc(mixc(c_mid, c_hot, hot), c_edge, edge * (1 - hot))
    if tint is not None:
        rgb = mixc(rgb, rgb * (tint / tint.mean()), 0.22)
    lon = np.arcsin(np.clip(dx / np.sqrt(np.clip(1 - dy * dy, 0.05, 1)), -1, 1))
    ribs = sum(np.exp(-(((lon - k * 0.62) / 0.07) ** 2)) for k in (-1, 0, 1))
    rgb = mixc(rgb, rgb * col("#8A4A20") / col("#F7B868").max(), np.clip(0.55 * ribs, 0, 0.6))
    a = V.downsample(inside, ss)
    rgb = V.downsample(rgb * inside[..., None], ss) / np.maximum(a, 1e-6)[..., None]
    sl = (slice(by, by + bh), slice(bx, bx + bw))
    g = (1 + 0.8 * (rel[sl] - 1))[..., None] * vig[sl][..., None]
    rgb = np.clip(rgb * g, 0, 1)
    out["body"] = (np.dstack([rgb, a * 0.98]), (bx, by, bw, bh), {})
    # ---- 火苗：灯里的一舌火，底部在灯身中下部
    fh, fw = ry * 0.95, rx * 0.55
    base = (x, y + ry * 0.42)
    out["flame"] = flame_layer(base, fh, fw, R, seed=hash_id(lid))
    # ---- 内圈：火苗周围一小团亮，叠加
    cxc, cyc = x, base[1] - fh * 0.45
    rc = max(rx, ry) * 0.95
    cb = crop_box(cxc, cyc, rc * 1.6, rc * 1.6)
    Xc, Yc = np.meshgrid(np.arange(cb[0], cb[0] + cb[2]) + 0.5, np.arange(cb[1], cb[1] + cb[3]) + 0.5)
    dc = np.hypot((Xc - cxc) / rc, (Yc - cyc) / (rc * 1.25))
    ac = ADD_PEAK * np.exp(-(dc / 0.55) ** 2) * V.bump_window(dc / 1.6)
    out["core"] = (np.dstack([np.broadcast_to(ADD_COLOR, ac.shape + (3,)), ac]), cb, {"blend": "add"})
    # ---- 外圈：大而软的光晕，照到旁边的枝和纸；灯身里面压低一点（那里灯身自己已经亮了）
    Rg = 6.2 * max(rx, ry)
    gb = crop_box(x, y, Rg, Rg)
    Xg, Yg = np.meshgrid(np.arange(gb[0], gb[0] + gb[2]) + 0.5, np.arange(gb[1], gb[1] + gb[3]) + 0.5)
    d = np.hypot(Xg - x, (Yg - y) * 1.05)
    rb = max(rx, ry)
    ag = (0.62 * np.exp(-(d / (1.7 * rb)) ** 2) + 0.38 * np.exp(-(d / (3.6 * rb)) ** 2)) * V.bump_window(d / Rg)
    body_full = smoothstep(1.05, 0.8, np.hypot((Xg - x) / rx, (Yg - y) / ry))
    ag = ADD_PEAK * ag * (1 - 0.75 * body_full)
    gc = mixc(ADD_COLOR, mixc(ADD_COLOR, tint, 0.12), 1.0) if tint is not None else ADD_COLOR
    out["glow"] = (np.dstack([np.broadcast_to(gc, ag.shape + (3,)), ag]), gb, {"blend": "add"})
    return out


def hash_id(s: str) -> int:
    return sum((i + 1) * ord(c) for i, c in enumerate(s)) + SEED


def flame_layer(base, h, w, R, seed: int):
    """一舌火（vfx_textures.make_flames 的配色）：藤黄芯、朱砂边，火舌尖收一点焦墨。普通混合。
    返回 (RGBA, rect, {"base": [x, y]})，base = 火苗底部中点。"""
    bx_, by_ = base
    ss = 6
    pad = 3
    x0, y0 = int(math.floor(bx_ - w / 2 - pad - 2)), int(math.floor(by_ - h - pad - 2))
    x1, y1 = int(math.ceil(bx_ + w / 2 + pad + 2)), int(math.ceil(by_ + pad + 1))
    bw, bh = x1 - x0, y1 - y0
    X, Y = V.grid(bh, bw, ss)
    X, Y = X + x0, Y + y0
    rng = np.random.default_rng(seed)
    v = (by_ - Y) / h  # 0 底、1 尖
    lean = (0.10 * rng.standard_normal()) * h
    u = (X - bx_ - lean * np.clip(v, 0, 1) ** 2) / (w / 2)
    width = np.where(v > 0.3, np.clip((1 - v) / 0.7, 0, 1) ** 0.85, np.sqrt(np.clip(1 - ((0.3 - v) / 0.32) ** 2, 0, 1)))
    shape = np.clip(1 - np.abs(u) / np.maximum(width, 1e-3), 0, 1) * smoothstep(-0.03, 0.04, v) * smoothstep(1.0, 0.92, v)
    cover = smoothstep(0.0, 0.18, shape)
    heat = np.clip(shape * (1.05 - 0.7 * np.clip(v, 0, 1) ** 0.9) + 0.35 * np.exp(-((u / 0.5) ** 2 + ((v - 0.28) / 0.25) ** 2)), 0, 1)
    rgb = V.ramp(heat, V.FLAME_STOPS)
    ink = smoothstep(0.72, 0.98, v) * 0.75
    rgb = mixc(rgb, col(V.FLAME_INK), ink)
    a = cover * (0.80 + 0.2 * smoothstep(0.1, 0.5, heat))
    lay = V.Layer(*X.shape)
    lay.over(rgb, a)
    lay = lay.down(ss)
    rgb_s, a_s = lay.straight()
    a_s[0, :] = a_s[-1, :] = a_s[:, 0] = a_s[:, -1] = 0
    return np.dstack([rgb_s, a_s]), (x0, y0, bw, bh), {"base": [round(bx_, 1), round(by_, 1)]}


# ============================================================== 叠层：晨光


def dawn_layers(R: dict, rid: str) -> dict:
    """一个地区的晨光：山脊上一道暖桃色、往下坡淡开，山后的天上一片淡淡的亮（普通混合）；
    同尺寸的“先亮哪里”灰度图；山脊一线金光（叠加）。只落在露出来的山和天上（前面的屋、树、雾挡住的地方不画）。"""
    P = R["P"]
    lay, cx, hgt, wl, wr, sharp, half = REGIONS[rid]
    rng = np.random.default_rng(SEED + 400 + hash_id(rid) % 97)
    front = np.clip(R["front"] * 1.2, 0, 1)
    back, far, city = P.layers["back"], P.layers["far"], P.layers["city"]
    if lay == "back":
        body = back * (1 - far) * (1 - city) * (1 - front)
        ridge = P.ridges["back"]
    else:
        body = np.maximum(far, city) * (1 - front)
        ridge = P.ridges["far"]
    sky = (1 - back) * (1 - far) * (1 - city) * (1 - front)
    xs = np.arange(W) + 0.5
    inner = 0.7 if rid == "youdu" else 0.35  # 幽都是一个山口：窗口平一些，两道山肩都照到
    win = smoothstep(half, inner * half, np.abs(xs - cx))[None, :]
    rr = ridge[None, :]
    depth = P.Y - rr  # 山脊以下为正
    seg = ridge[int(max(0, cx - half)):int(min(W, cx + half))]
    top = float(seg.min())
    lift = np.clip((FAR_BASE + 20 - rr) / max(FAR_BASE + 20 - top, 1.0), 0, 1) ** 1.3  # 越高越早见光、越亮
    if rid == "youdu":
        lift = np.maximum(lift, 0.55)
    fib = V.rank01(blur(rng.standard_normal((H, W)), (9.0, 0.7), angle=0.35)) * 0.6 + V.rank01(noise(rng, (H, W), 2.5)) * 0.4
    rim = np.exp(-np.maximum(depth, 0) / 9.0) * smoothstep(-1.5, 1.0, depth)
    slope = np.exp(-np.maximum(depth, 0) / 60.0) * smoothstep(-1.0, 4.0, depth) * V.bump_window(np.clip(depth / 150.0, 0, 1))
    skyglow = np.exp(-np.maximum(-depth, 0) / 40.0) * smoothstep(1.0, -2.0, depth) * V.bump_window(np.clip(-depth / 100.0, 0, 1))
    city_rim = city * np.clip(1 - np.roll(city, 3, axis=0), 0, 1) * (1 - front)  # 黑城的屋脊、垛口上一线光
    a = (0.42 * rim + 0.16 * slope) * body * (0.35 + 0.65 * lift) + 0.24 * skyglow * sky * (0.4 + 0.6 * lift) + 0.35 * city_rim
    a = a * win * (0.82 + 0.18 * fib)
    a = np.clip(a, 0, 0.6)
    a[a < 0.004] = 0.0
    ys, xs_ = np.nonzero(a)
    x0, x1, y0, y1 = xs_.min(), xs_.max() + 1, ys.min(), ys.max() + 1
    sl = (slice(y0, y1), slice(x0, x1))
    rel, vig = R["fin"]["rel"][sl], R["fin"]["vig"][sl]
    color = DAWN_PEACH[None, None] * (1 + 0.8 * (rel[..., None] - 1)) * vig[..., None]
    color = mixc(color, color * mixc(WHITE, DAWN_GOLD / DAWN_GOLD.max(), 0.6), rim[sl])
    img = np.dstack([np.clip(color, 0, 1), a[sl]])
    # 先亮哪里：主峰的山脊最先，顺着山脊往两边、往下坡、往天上铺开；纸纤维的毛
    dist_ridge = np.abs(depth[sl])
    along = np.clip((ridge[None, x0:x1] - top) / 140.0, 0, 1)  # 山脊上离峰顶多远（越低越晚）
    t = 0.55 * along + 0.45 * np.clip(dist_ridge / 120.0, 0, 1) ** 0.8
    t = t + 0.16 * (fib[sl] - 0.5) + 0.06 * noise(rng, t.shape, 6.0)
    on = a[sl] > 0
    t = (t - t[on].min()) / max(np.ptp(t[on]), 1e-6)
    mask = np.where(on, np.clip(t, 0, 1), 1.0)
    out = {"main": (img, (x0, y0, x1 - x0, y1 - y0), {}), "mask": (mask, (x0, y0, x1 - x0, y1 - y0), {})}
    # 山脊金线（叠加）：贴着山脊一线，主峰处最亮
    gl = (np.exp(-((depth - 1.0) / 2.2) ** 2) * body + 0.6 * city_rim) * win * lift ** 1.5 * (0.7 + 0.3 * fib)
    gl = ADD_PEAK * 0.75 * gl / max(gl.max(), 1e-6)
    gl[gl < 0.004] = 0.0
    ys, xs_ = np.nonzero(gl)
    pad = 4  # 四边留几像素全透明：叠加层裁边处为 0
    gx0, gx1, gy0, gy1 = max(0, xs_.min() - pad), min(W, xs_.max() + 1 + pad), max(0, ys.min() - pad), min(H, ys.max() + 1 + pad)
    gsl = (slice(gy0, gy1), slice(gx0, gx1))
    out["glow"] = (np.dstack([np.broadcast_to(DAWN_GOLD, (gy1 - gy0, gx1 - gx0, 3)), gl[gsl]]), (gx0, gy0, gx1 - gx0, gy1 - gy0),
                   {"blend": "add"})
    return out


# ============================================================== 合成（与游戏相同的顺序）


def to_img(a: np.ndarray, mode="RGBA") -> Image.Image:
    a8 = np.clip(np.round(a * 255.0), 0, 255).astype(np.uint8)
    if a8.ndim == 2:
        return Image.fromarray(a8, "L")
    return Image.fromarray(a8, mode)


def blend_normal(base: np.ndarray, layer: np.ndarray, rect) -> None:
    x, y, w, h = rect
    a = layer[..., 3:4]
    base[y:y + h, x:x + w] = base[y:y + h, x:x + w] * (1 - a) + layer[..., :3] * a


def blend_add(base: np.ndarray, layer: np.ndarray, rect, k: float = 1.0) -> None:
    x, y, w, h = rect
    base[y:y + h, x:x + w] = base[y:y + h, x:x + w] + layer[..., :3] * layer[..., 3:4] * k


def quantize(layers):
    """叠层按写出的 8 位精度取整（审图和游戏看到的一样）。"""
    return {k: (np.round(v[0] * 255) / 255.0, v[1], v[2]) for k, v in layers.items()}


def composite(base_img: Image.Image, lamps: dict, dawns: dict, lit: list[str], dawn_ids: list[str]) -> Image.Image:
    """底图 → 灯身 → 火苗（普通）→ 内圈 + 外圈（叠加）→ 晨光（普通）→ 晨光金线（叠加）。"""
    out = np.asarray(base_img, np.float64) / 255.0
    out = out.copy()
    for lid in lit:
        blend_normal(out, *lamps[lid]["body"][:2])
    for lid in lit:
        blend_normal(out, *lamps[lid]["flame"][:2])
    for lid in lit:
        blend_add(out, *lamps[lid]["core"][:2])
        blend_add(out, *lamps[lid]["glow"][:2])
    out = np.clip(out, 0, 1)
    for rid in dawn_ids:
        blend_normal(out, *dawns[rid]["main"][:2])
    for rid in dawn_ids:
        blend_add(out, *dawns[rid]["glow"][:2])
    return Image.fromarray((np.clip(out, 0, 1) * 255 + 0.5).astype(np.uint8), "RGB")


# ============================================================== 审图


ROUND1 = ART / "out" / "_hub_round1" / "hub_sample.png"  # 上一轮的样张（审图对比用，没有就跳过）


def review_figures(R: dict, path: Path, compare: bool = False) -> None:
    """四个人物各裁一块放大 2 倍，一人一行：（compare 时先放上一轮的夜景）夜景（hub.png）| 宣纸上的原画（没打光）。"""
    P = R["P"]
    day = Image.fromarray((np.clip(P.rgb, 0, 1) * 255 + 0.5).astype(np.uint8), "RGB")
    old = Image.open(ROUND1).convert("RGB") if (compare and ROUND1.exists()) else None
    srcs = [(old, "上一轮"), (R["img"], "夜景（hub.png）"), (day, "宣纸原画（未打光）")]
    srcs = [(im, lab) for im, lab in srcs if im is not None]
    f = font("serif", 22)
    rows = []
    for c in CHARACTERS:
        x, y, w, h = c["rect"]
        pad = 18
        box = (max(0, x - pad), max(0, y - pad), min(W, x + w + pad), min(H, y + h + pad))
        rows.append((c, box))
    cw = max((b[2] - b[0]) * 2 for _, b in rows)
    out = Image.new("RGB", (len(srcs) * (cw + 16) + 16, sum((b[3] - b[1]) * 2 + 44 for _, b in rows) + 16), (26, 26, 28))
    d = ImageDraw.Draw(out)
    y = 8
    for c, b in rows:
        for i, (src, lab) in enumerate(srcs):
            im = src.crop(b).resize(((b[2] - b[0]) * 2, (b[3] - b[1]) * 2), Image.LANCZOS)
            x = 16 + i * (cw + 16)
            d.text((x, y), f"{c['name']} · {lab}", font=f, fill=(225, 225, 225))
            out.paste(im, (x, y + 34))
        y += (b[3] - b[1]) * 2 + 44
    out.save(path, optimize=True)


def reveal(dawn: dict, p: float) -> dict:
    """按灰度图铺开晨光（游戏的做法）：灰度 ≤ 进度的地方显出来，边上软 0.06。"""
    img, rect, extra = dawn["main"]
    m = dawn["mask"][0]
    k = smoothstep(m, m + 0.06, p * 1.06)
    out = dict(dawn)
    out["main"] = (np.dstack([img[..., :3], img[..., 3] * k]), rect, extra)
    g, grect, gextra = dawn["glow"]
    gx, gy = grect[0] - rect[0], grect[1] - rect[1]
    kg = np.ones(g.shape[:2])
    hh, ww = g.shape[:2]
    sub = k[max(0, gy):gy + hh, max(0, gx):gx + ww]
    kg[max(0, -gy):max(0, -gy) + sub.shape[0], max(0, -gx):max(0, -gx) + sub.shape[1]] = sub
    out["glow"] = (np.dstack([g[..., :3], g[..., 3] * kg]), grect, gextra)
    return out


def review_states(base: Image.Image, lamps, dawns, ids, path: Path) -> list[Image.Image]:
    """上一行三种状态并排：0 盏；前 6 盏；全部 + 青丘天明。下一行：青丘的晨光按灰度图铺开（25%、50%、75%、100%），
    再加六处晨光全亮。"""
    states = [([], [], "心灯 0 盏"), (ids[:6], [], "心灯前 6 盏"), (ids, ["qingqiu"], f"心灯 {len(ids)} 盏 + 青丘天明")]
    ims = [composite(base, lamps, dawns, lit, dw) for lit, dw, _ in states]
    sw, sh = 960, 540
    f = font("serif", 22)
    rid = "qingqiu"
    x, y, w, h = dawns[rid]["main"][1]
    box = (max(0, x - 40), max(0, y - 20), min(W, x + w + 40), min(H, y + h + 20))
    steps = [0.25, 0.5, 0.75, 1.0]
    tiles = [composite(base, lamps, {rid: reveal(dawns[rid], p_)}, [], [rid]).crop(box) for p_ in steps]
    all6 = composite(base, lamps, dawns, ids, list(REGIONS)).crop((0, 100, W, 520))
    th = 360
    tiles = [t.resize((round(t.width * th / t.height), th), Image.LANCZOS) for t in tiles]
    all6 = all6.resize((round(all6.width * th / all6.height), th), Image.LANCZOS)
    width = max(sw * 3 + 40, sum(t.width + 10 for t in tiles) + all6.width + 20)
    out = Image.new("RGB", (width, sh + 50 + th + 50), (26, 26, 28))
    d = ImageDraw.Draw(out)
    for i, (im, (_, _, lab)) in enumerate(zip(ims, states)):
        out.paste(im.resize((sw, sh), Image.LANCZOS), (10 + i * (sw + 10), 40))
        d.text((10 + i * (sw + 10), 8), lab, font=f, fill=(225, 225, 225))
    xx = 10
    for p_, t in zip(steps, tiles):
        out.paste(t, (xx, sh + 90))
        d.text((xx, sh + 58), f"青丘晨光 {int(p_ * 100)}%（按 mask 铺开）", font=f, fill=(225, 225, 225))
        xx += t.width + 10
    out.paste(all6, (xx, sh + 90))
    d.text((xx, sh + 58), "六处晨光全亮（远山）", font=f, fill=(225, 225, 225))
    out.save(path, optimize=True)
    return ims


def review_ui(full: Image.Image, path: Path) -> None:
    """缩到 1280×720 的样子：名字 + 行当写在 label 处，人物 0 加一团模拟聚光，红框是文字安全区；
    下面一张是居中纸色面板 + 60% 压暗。"""
    k = 1280 / W
    im = full.resize((1280, 720), Image.LANCZOS)
    arr = np.asarray(im, np.float64) / 255.0
    # 模拟聚光（叠加）
    c0 = CHARACTERS[0]
    lx, ly, lr = (v * k for v in c0["light"])
    yy, xx = np.mgrid[0:720, 0:1280] + 0.5
    dd = np.hypot(xx - lx, yy - ly) / lr
    arr = arr + (0.35 * V.bump_window(np.clip(dd, 0, 1)))[..., None] * ADD_COLOR[None, None]
    im = Image.fromarray((np.clip(arr, 0, 1) * 255 + 0.5).astype(np.uint8), "RGB").convert("RGBA")
    txt = Image.new("RGBA", im.size, (0, 0, 0, 0))
    dr = ImageDraw.Draw(txt)
    fn = font("serif", 26)
    fr = font("serif", 16)
    paper = S.hex_to_rgb(S.PAPER)
    for c in CHARACTERS:
        x, y = c["label"][0] * k, c["label"][1] * k
        bb = fn.getbbox(c["name"])
        dr.text((x - (bb[2] - bb[0]) / 2 - bb[0], y), c["name"], font=fn, fill=paper + (255,))
        bb2 = fr.getbbox(c["role"])
        dr.text((x - (bb2[2] - bb2[0]) / 2 - bb2[0], y + 32), c["role"], font=fr, fill=paper + (190,))
    # 标题行、提示行（模拟）
    tx, ty, _, _ = TEXT_SAFE[0]
    dr.text((tx * k + 8, ty * k + 8), "灯驿", font=font("serif", 30), fill=paper + (255,))
    dr.text((tx * k + 90, ty * k + 18), "灯油 1240　铜钱 386", font=fr, fill=paper + (220,))
    bx, by, _, _ = TEXT_SAFE[1]
    dr.text((bx * k + 8, by * k + 14), "←/→ 选人　Enter 进去　Esc 返回", font=fr, fill=paper + (200,))
    sh = txt.split()[3].filter(ImageFilter.GaussianBlur(3))
    shadow = Image.new("RGBA", im.size, (8, 9, 14, 0))
    shadow.putalpha(sh.point(lambda v: int(v * 0.7)))
    im.alpha_composite(shadow)
    im.alpha_composite(txt)
    bd = ImageDraw.Draw(im)
    for (x, y, w, h) in TEXT_SAFE:
        bd.rectangle([x * k, y * k, (x + w) * k, (y + h) * k], outline=(220, 50, 50, 255), width=1)
    sx, sy, sw, sh_ = SAFE
    bd.rectangle([sx * k, sy * k, (sx + sw) * k, (sy + sh_) * k], outline=(60, 120, 230, 255), width=1)
    bd.rectangle([240 * k, 0, 1680 * k, 719], outline=(60, 200, 120, 200), width=1)
    for c in CHARACTERS:
        x, y, w, h = c["rect"]
        bd.rectangle([x * k, y * k, (x + w) * k, (y + h) * k], outline=(80, 160, 220, 160), width=1)
    a = im.convert("RGB")
    # 第二张：60% 压暗 + 居中纸色面板
    dim = np.asarray(full.resize((1280, 720), Image.LANCZOS), np.float64) / 255.0 * 0.4
    b = Image.fromarray((dim * 255 + 0.5).astype(np.uint8), "RGB")
    bd2 = ImageDraw.Draw(b)
    px0, py0 = (1280 - 720) // 2, (720 - 400) // 2
    bd2.rectangle([px0, py0, px0 + 720, py0 + 400], fill=paper, outline=S.hex_to_rgb(S.INK["nong"]), width=2)
    bd2.text((px0 + 30, py0 + 24), "老灯匠 · 心灯", font=font("serif", 30), fill=S.hex_to_rgb(S.INK["jiao"]))
    bd2.text((px0 + 30, py0 + 74), "灯身破了我再糊，人回来就行。", font=font("serif", 20), fill=S.hex_to_rgb(S.INK["nong"]))
    # 第三张：4:3 窗口（铺满后居中裁成 1440×1080 那一块），缩到 960×720
    c43 = full.crop((240, 0, 1680, 1080)).resize((960, 720), Image.LANCZOS)
    f = font("serif", 16)
    out = Image.new("RGB", (1280 + 20 + 960, 720 * 2 + 12), (26, 26, 28))
    out.paste(a, (0, 0))
    out.paste(b, (0, 732))
    out.paste(c43, (1300, 0))
    d = ImageDraw.Draw(out)
    d.text((1300, 732), "右上：4:3 窗口居中裁切（x 240–1680）", font=f, fill=(225, 225, 225))
    d.text((1300, 760), "左上：1280×720；红框 = text_safe，蓝框 = safe（16:10 / 21:9 都留得住），", font=f, fill=(225, 225, 225))
    d.text((1300, 784), "绿线 = 4:3 的左右边，淡蓝框 = 人物点击区，人物 0 加了模拟聚光", font=f, fill=(225, 225, 225))
    d.text((1300, 808), "左下：60% 压暗 + 居中纸色面板（720×400）", font=f, fill=(225, 225, 225))
    out.save(path, optimize=True)


# ============================================================== 写文件


def write_outputs(R: dict, lamps: dict, dawns: dict, out: Path = OUT) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    R["img"].save(out / "hub.png", optimize=True)
    man = {"size": [W, H], "safe": list(SAFE), "characters": [], "lamps": {}, "dawn": {}, "text_safe": [list(r) for r in TEXT_SAFE]}
    for c in CHARACTERS:
        man["characters"].append({k: c[k] for k in ("id", "name", "rect", "label", "light")})
    for lid in R["ids"]:
        e = {}
        for part, suffix in (("body", ""), ("flame", "_flame"), ("core", "_core"), ("glow", "_glow")):
            arr, rect, extra = lamps[lid][part]
            fn = f"lamp_{lid}{suffix}.png"
            to_img(arr).save(out / fn, optimize=True)
            e[part] = {"file": fn, "rect": list(map(int, rect)), "blend": extra.get("blend", "normal")}
            if "base" in extra:
                e[part]["base"] = extra["base"]
        man["lamps"][lid] = e
    for rid in REGIONS:
        arr, rect, _ = dawns[rid]["main"]
        to_img(arr).save(out / f"dawn_{rid}.png", optimize=True)
        to_img(dawns[rid]["mask"][0]).save(out / f"dawn_{rid}_mask.png", optimize=True)
        garr, grect, _ = dawns[rid]["glow"]
        to_img(garr).save(out / f"dawn_{rid}_glow.png", optimize=True)
        man["dawn"][rid] = {"file": f"dawn_{rid}.png", "rect": list(map(int, rect)), "blend": "normal", "mask": f"dawn_{rid}_mask.png",
                            "glow": {"file": f"dawn_{rid}_glow.png", "rect": list(map(int, grect)), "blend": "add"}}
    man["note"] = ("坐标都是 1920×1080 底图上的像素，rect = [x, y, w, h]（左上角 + 宽高）。合成顺序：hub.png → 各灯 body → flame（普通混合）"
                   "→ core + glow（叠加：画面 += RGB × alpha）→ dawn（普通混合）→ dawn 的 glow（叠加）。PNG 都是直通（非预乘）alpha。"
                   "flame.base 是火苗底部中点（缩放、抖动绕这一点）。dawn mask 与 dawn 图同尺寸：黑 = 最先亮，白 = 最后，按阈值铺开。"
                   "characters：rect 是点击区；label 是名字和行当那块文字的上沿中点；light = [x, y, 半径]，选中时加的聚光。"
                   "text_safe：画面里安静、够暗的区域，放标题行（灯驿 + 灯油、铜钱）和底部提示。"
                   "safe：游戏按铺满窗口、居中裁切显示，16:10 与 21:9 都留得住的区域；人物、心灯、匾额、text_safe 都在里面。")
    (out / "hub.json").write_text(json.dumps(man, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return man


def load_layers(man: dict, out: Path = OUT) -> tuple[dict, dict]:
    """按 hub.json 从磁盘读回各层（和游戏读到的一样），给审图合成用。"""
    def rd(fn, mode="RGBA"):
        return np.asarray(Image.open(out / fn).convert(mode), np.float64) / 255.0

    lamps = {}
    for lid, e in man["lamps"].items():
        lamps[lid] = {part: (rd(v["file"]), tuple(v["rect"]), {k: v[k] for k in ("blend", "base") if k in v}) for part, v in e.items()}
    dawns = {}
    for rid, e in man["dawn"].items():
        dawns[rid] = {"main": (rd(e["file"]), tuple(e["rect"]), {}), "mask": (rd(e["mask"], "L"), tuple(e["rect"]), {}),
                      "glow": (rd(e["glow"]["file"]), tuple(e["glow"]["rect"]), {"blend": "add"})}
    return lamps, dawns


def arg(argv: list[str], name: str, default=None):
    return argv[argv.index(name) + 1] if name in argv else default


def main(argv: list[str]) -> int:
    """--sample：只出样张 review@2x/hub_sample*.png（和上一轮对比），不写 screens/hub/；
    --out DIR / --review DIR：换输出目录（自检的确定性测试用）；--no-review：不出审图。"""
    t0 = time.perf_counter()
    sample = "--sample" in argv
    out = Path(arg(argv, "--out", OUT))
    review = Path(arg(argv, "--review", REVIEW))
    R = paint()
    print(f"[hub] 画 {R['t_paint']:.1f}s，打光收尾共 {R['t_total']:.1f}s")
    lamps = {lid: quantize(lamp_layers(R, lid)) for lid in R["ids"]}
    dawns = {rid: quantize(dawn_layers(R, rid)) for rid in REGIONS}
    print(f"[hub] 叠层 {time.perf_counter() - t0:.1f}s")
    base = R["img"]
    if not sample:
        man = write_outputs(R, lamps, dawns, out)
        lamps, dawns = load_layers(man, out)  # 审图用写出去的文件合成
        base = Image.open(out / "hub.png").convert("RGB")
        n = sum(1 for _ in out.glob("*.png"))
        mb = sum(p_.stat().st_size for p_ in out.iterdir()) / 1024 / 1024
        print(f"[hub] → {out}（{n} 张 PNG + hub.json，共 {mb:.2f} MB）")
    if "--no-review" in argv:
        return 0
    review.mkdir(parents=True, exist_ok=True)
    pre = "hub_sample" if sample else "hub_review"
    if sample:
        base.save(review / "hub_sample.png", optimize=True)
    review_figures(R, review / f"{pre}_figures.png", compare=sample)
    ims = review_states(base, lamps, dawns, R["ids"], review / f"{pre}_states.png")
    review_ui(ims[2], review / f"{pre}_ui_720.png")
    print(f"[review] → {review}/{pre}_*.png，共 {time.perf_counter() - t0:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
