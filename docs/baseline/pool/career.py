"""按局抽样估算新法器的解锁进度（BALANCE.md 6.4 节）。
每局从对应状态的实测局里随机抽一局：已解锁 0–2 件用“第一局”状态（S0），3 件以上用“全部解锁”状态（S5）。
这一局进化或异化过的老法器，解锁同五行的新法器；完成第 5、8、11、14、17 局时按顺序保底送一件。
用法：python3 career.py <目录> <选卡 greedy|random> <格 nov1|gen3>"""
import csv, random, statistics, sys

PAIR = {"sword": "coin_sword", "lamp": "sky_lantern", "bell": "wave", "crane": "vine", "seal": "tower"}
ORDER = ["coin_sword", "sky_lantern", "wave", "vine", "tower"]
PITY = {5, 8, 11, 14, 17}

d, pk, cell = sys.argv[1:4]
E, L = (sys.argv[4], sys.argv[5]) if len(sys.argv) > 5 else ("S0", "S5")
def load(v):
    out = []
    for r in csv.DictReader(open(f"{d}/{v}-{pk}-{cell}/runs.csv")):
        ev = {e.split("@")[0] for e in r["evolutions"].split()} if r["evolutions"] else set()
        out.append({PAIR[w] for w in ev if w in PAIR})
    return out
early, late = load(E), load(L)
rng = random.Random(7)
first, every, by_pity = [], [], []
for _ in range(20000):
    got, f, pity = set(), None, 0
    for n in range(1, 41):
        got |= rng.choice(early if len(got) <= 2 else late)
        if n in PITY and len(got) < 5:
            got.add(next(w for w in ORDER if w not in got))
            pity += 1
        if f is None and got:
            f = n
        if len(got) == 5:
            break
    first.append(f); every.append(n); by_pity.append(pity)
q = lambda v, p: sorted(v)[int(p * (len(v) - 1))]
share = sum(1 for r in early if r) / len(early)
print(f"{E}/{L} {pk} {cell}: 一局解锁至少一件的概率 {100*share:.0f}%；第一件：中位第 {q(first,.5)} 局（P90 第 {q(first,.9)} 局）；"
      f"全部：中位第 {q(every,.5)} 局（P10 {q(every,.1)}，P90 {q(every,.9)}）；平均有 {statistics.mean(by_pity):.1f} 件靠保底")
