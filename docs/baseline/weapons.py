"""原型五件法器的理论输出（BALANCE.md 第 6.1 节）：不含加成，参考密度每 900 平方单位一只。只作量级参考。

用法：python3 weapons.py
"""

import math
RHO=1/900  # 参考密度：每 900 平方单位一只（后期常见密度）
def lamp(lv,evo=False):
    c=[3,3,4,4,5,5,6,6][lv-1]; R=50+4*lv; d=12+3*lv; w=3.2+0.12*lv; size=10
    if evo: c,R,d,w,size=10,92,d*2.2,2.4,12
    rate=min(c*w/(2*math.pi),1/0.45)
    single=d*rate
    band=2*math.pi*R*2*size
    return single, single*band*RHO, f"{c}焰 半径{R} 伤{d:.0f}"
def sword(lv,evo=False):
    cd=1.15-0.06*lv; n=1+lv//3; d=12+4*lv; p=1+lv//3
    if evo: cd,n,d,p=0.42,3,d*1.6,6  # 无限穿透，按一条线上约 6 只估
    single=d/cd  # 只算一把剑打同一目标
    crowd=n*p*d/cd
    return single, crowd, f"{n}剑 冷却{cd:.2f} 伤{d:.0f} 穿{p if not evo else '∞'}"
def bell(lv,evo=False):
    cd=3-0.15*lv; r=70+9*lv; d=6+3*lv
    if evo: r*=1.3; d*=1.5
    single=d/cd
    extra=0
    if evo: extra=(6+3*lv)*3/6  # 每 6 秒全屏 3 倍
    area=math.pi*r*r
    crowd=single*area*RHO + extra*(420*746)*RHO
    return single+extra, crowd, f"冷却{cd:.2f} 半径{r:.0f} 伤{d:.0f}"
def crane(lv,evo=False):
    n=[1,1,2,2,3,3,4,4][lv-1]; d=9+3*lv; sp=250+6*lv; rest=0.35
    if evo: n,d,sp,rest=10,d*1.5,330,0.2
    cyc=rest+90/sp
    single=d/cyc  # 一只鹤
    crowd=n*d/cyc
    return single, crowd, f"{n}鹤 伤{d:.0f}"
def seal(lv,evo=False):
    cd=4.2-0.22*lv; n=1+lv//3; r=38+4*lv; d=22+8*lv
    zone=0
    if evo: cd,n,r,d=2.6,n+1,r*2,d*1.5; zone=d*0.25*2*5  # 地裂 2.5 秒，每 0.5 秒一次
    single=(d+zone)/cd
    crowd=n*(d+zone)/cd*math.pi*r*r*RHO
    return single, crowd, f"{n}印 冷却{cd:.2f} 半径{r:.0f} 伤{d:.0f}"
print(f"{'法器':4} {'等级':4} {'单体DPS':>8} {'群伤DPS':>8}  参数")
for name,f in [('灯火',lamp),('符剑',sword),('霜铃',bell),('纸鹤',crane),('山印',seal)]:
    for lv in (1,4,8):
        s,c,info=f(lv); print(f"{name:4} Lv{lv:<3} {s:8.0f} {c:8.0f}  {info}")
    s,c,info=f(8,True); print(f"{name:4} 进化  {s:8.0f} {c:8.0f}  {info}")
