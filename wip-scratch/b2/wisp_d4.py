import math
import numpy as np
INK=(40,36,32); MID=(85,80,74); PALE=(130,128,124)
C = (4.3, 13.2)
def wisp_path(th0=math.pi*0.7, th1=math.pi*2.5, r0=0.35, r1=2.55):
    """卷云头 + 尾：返回密的点列和每点的宽度（按弧长定）。"""
    pts, ws = [], []
    n = 60
    for i in range(n):
        u = i/(n-1)
        th = th0 + (th1-th0)*u
        r = r0 + (r1-r0)*u**0.8
        pts.append((C[0]+r*math.cos(th), C[1]+r*math.sin(th)))
        ws.append(0.35 + 3.4 * min(1.0, u / 0.72) ** 1.1 - 0.4 * max(0.0, (u - 0.72) / 0.28))
    tail = [(C[0]-1.2, C[1]+2.55), (C[0]-5.0, C[1]+2.3), (C[0]-9.5, C[1]+2.9), (C[0]-14.0, C[1]+4.7), (C[0]-18.0, C[1]+7.0), (C[0]-21.0, C[1]+9.6)]
    import enemy_design as DZ
    tc = DZ.curve_pts([pts[-1]] + tail, 80)[1:]
    m = len(tc)
    for k, p in enumerate(tc):
        v = (k+1)/m
        pts.append(tuple(p)); ws.append(3.0 * (1 - v) ** 1.1 + 0.1)
    return pts, ws
path, widths = wisp_path()
STROKES = [
    ([(4.6, 10.4), (0.6, 9.8), (-3.8, 10.4), (-8.2, 12.0), (-12.2, 14.0), (-15.6, 15.6)], [2.0, 1.9, 1.5, 1.0, 0.5, 0.15], MID),
    ([(2.0, 12.6), (-2.4, 12.6), (-6.8, 13.4), (-11.0, 14.8), (-15.0, 16.2), (-18.8, 16.8)], [1.4, 1.3, 1.0, 0.7, 0.35, 0.1], PALE),
    (path, widths, INK),
]
EYES = [((7.15, 13.75), 0.95, 0.40, -16.0, (159, 227, 255)), ((8.2, 13.3), 0.45, 0.28, -20.0, (159, 227, 255))]
