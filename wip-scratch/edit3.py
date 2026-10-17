p='/home/user/mygame/lantern-next/art/render/smoke_test.py'; s=open(p).read()
def rep(a, b):
    global s
    assert s.count(a) == 1, a
    s = s.replace(a, b)
rep('''from pathlib import Path

import bpy
import bmesh
import numpy as np
from mathutils import Vector
''', '''from pathlib import Path

_t_import = time.perf_counter()
import bpy  # noqa: E402  （在 blender -P 下 bpy 已加载，耗时≈0）
import bmesh  # noqa: E402
import numpy as np  # noqa: E402
from mathutils import Vector  # noqa: E402
IMPORT_BPY_S = time.perf_counter() - _t_import
''')
rep('''    with Timer("import_and_engines"):
''', '''    report["timings_s"]["import_bpy"] = round(IMPORT_BPY_S, 3)
    with Timer("engine_list"):
''')
rep('''        cam = setup_camera(sc)
    from bpy_extras''', '''        cam = setup_camera(sc)
        bpy.context.view_layer.update()  # 刷新 matrix_world，否则投影坐标全是原点
    from bpy_extras''')
rep('''    """背面=黑色自发光，正面=透明。配合 Solidify(翻转法线) 外壳得到轮廓线。"""''',
    '''    """配合 Solidify(翻转法线) 外壳得到轮廓线。
    外壳法线朝内：靠近相机的那半边是“背面”→ 透明（露出本体）；
    远端那半边是“正面”，只在本体轮廓外露出一圈 → 墨色自发光。
    （按原始法线方向理解，就是“外壳的背面涂黑、正面透明”。）"""''')
rep('''    L.new(tr.outputs["BSDF"], mix.inputs[1])   # 正面 → 透明
    L.new(emi.outputs["Emission"], mix.inputs[2])  # 背面 → 墨色''',
    '''    L.new(emi.outputs["Emission"], mix.inputs[1])  # Backfacing=0（翻转后的正面）→ 墨色
    L.new(tr.outputs["BSDF"], mix.inputs[2])       # Backfacing=1 → 透明''')
rep('def sobel_lines(normal_png, out_png, thr=0.35):', 'def sobel_lines(normal_png, out_png, thr=0.9):')
open(p,'w').write(s)
