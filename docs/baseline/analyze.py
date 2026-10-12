"""汇总 probe.test.ts 的输出：每 30 秒的成长与压力、伤害来源占比、胜负与倒下时间。

用法：python3 analyze.py <数据目录>
数据目录里应有 probe_god.json、probe_godkite.json、probe_mortal.json、probe_kite.json（缺的跳过）。
"""

import json
import os
import statistics as st
import sys
from collections import defaultdict


def windows(run):
    s = run["samples"]
    out = []
    for a, b in zip(s, s[1:]):
        dt = b["t"] - a["t"]
        if dt <= 0:
            continue
        pa, pb = a["probe"], b["probe"]
        eff = {k: pb["eff"].get(k, 0) - pa["eff"].get(k, 0) for k in pb["eff"]}
        out.append(dict(
            t1=b["t"], dt=dt, level=b["level"],
            kills=(b["kills"] - a["kills"]) / dt, alive=b["alive"],
            spawn_hp=(pb["spawnHp"] - pa["spawnHp"]) / dt,
            eff={k: v / dt for k, v in eff.items()}, eff_tot=sum(eff.values()) / dt,
            incoming=(pb["incoming"] - pa["incoming"]) / dt,
        ))
    return out


def summarize(path, label):
    runs = json.load(open(path))
    won = sum(1 for r in runs if r["won"])
    dead = sorted(r["end"] for r in runs if not r["won"] and r["end"] < 719.5)
    print(f"\n===== {label}：{len(runs)} 局，胜 {won}，倒下 {len(dead)}，其余到测试上限 =====")
    if dead:
        print("倒下时间中位 %.0f 秒" % st.median(dead))
    W = defaultdict(list)
    for r in runs:
        for w in windows(r):
            if w["dt"] >= 29:
                W[w["t1"]].append(w)
    print("时间  局数  等级  击杀/秒  场上  刷出血量/秒  有效伤害/秒  压力比  受到伤害/秒")
    for t in sorted(W):
        ws = W[t]
        f = lambda k: st.mean(w[k] for w in ws)
        print("%4d %4d %6.1f %8.1f %5.0f %11.0f %11.0f %7.2f %10.1f" % (
            t, len(ws), f("level"), f("kills"), f("alive"), f("spawn_hp"), f("eff_tot"),
            f("eff_tot") / max(1, f("spawn_hp")), f("incoming")))
    srcs = sorted({k for ws in W.values() for w in ws for k in w["eff"]})
    print("伤害来源占比（%）：")
    print("时间 " + " ".join("%9s" % s[:9] for s in srcs))
    for t in sorted(W):
        ws = W[t]
        tot = sum(w["eff_tot"] for w in ws) or 1
        print("%4d " % t + " ".join("%9.1f" % (100 * sum(w["eff"].get(s, 0) for w in ws) / tot) for s in srcs))


def main():
    d = sys.argv[1] if len(sys.argv) > 1 else "."
    for name, label in [("probe_god.json", "无敌·绕圈"), ("probe_godkite.json", "无敌·风筝"),
                        ("probe_mortal.json", "非无敌·绕圈"), ("probe_kite.json", "非无敌·风筝")]:
        p = os.path.join(d, name)
        if os.path.exists(p):
            summarize(p, label)


if __name__ == "__main__":
    main()
