# 数值基线与模拟脚本

`docs/BALANCE.md` 里的实测数据和模拟结果都可以用这里的脚本复现。冻结的 `web/lantern-next/` 本身不改动，埋点只打在临时副本上。

| 文件 | 作用 | 对应 |
| --- | --- | --- |
| `probe.patch` | 给 lantern-next 的模拟加伤害来源埋点（按来源统计有效伤害、刷出的血量、受到的伤害） | `BALANCE.md` 第 2 节 |
| `probe.test.ts` | 用测试里的自动选卡机器人跑整局，输出每 30 秒的快照（JSON）。走位有“绕圈”（原测试）和“风筝”两种 | 第 2 节 |
| `analyze.py` | 汇总上面的 JSON：成长与压力、伤害来源占比、胜负与倒下时间 | 第 2 节 |
| `pacing.py` | 单局节奏模型：击杀≈刷怪时每分钟的等级、累计击杀、场上妖物数 | 第 4.2、4.3 节 |
| `resonance_mc.py` | 共鸣计点规则的蒙特卡洛模拟：专精和兼修机器人各阶的达成时间 | 第 7.1 节 |
| `weapons.py` | 原型五件法器按公式算的理论输出 | 第 6.1 节 |

## 复现原型实测

需要 Node 22 和 Python 3。

```bash
# 在仓库根目录
cp -r web/lantern-next /tmp/ln
cd /tmp/ln
npm ci
patch -p1 < "$OLDPWD/docs/baseline/probe.patch"
cp "$OLDPWD/docs/baseline/probe.test.ts" tests/sim/

S10=$(seq -s, 1 10); S40=$(seq -s, 1 40)
PROBE_MODE=god     PROBE_SEEDS=424242,$S10 PROBE_OUT=/tmp/probe_god.json     npx vitest run tests/sim/probe.test.ts
PROBE_MODE=godkite PROBE_SEEDS=424242,$S10 PROBE_OUT=/tmp/probe_godkite.json npx vitest run tests/sim/probe.test.ts
PROBE_MODE=mortal  PROBE_SEEDS=$S40        PROBE_OUT=/tmp/probe_mortal.json  npx vitest run tests/sim/probe.test.ts
PROBE_MODE=kite    PROBE_SEEDS=$S40        PROBE_OUT=/tmp/probe_kite.json    npx vitest run tests/sim/probe.test.ts

cd "$OLDPWD"
python3 docs/baseline/analyze.py /tmp
```

四批一共约 5 分钟（云端 4 核）。`PROBE_MODE`：`god` 无敌·绕圈，`godkite` 无敌·风筝，`mortal` 非无敌·绕圈，`kite` 非无敌·风筝。

## 模拟

```bash
python3 docs/baseline/pacing.py
python3 docs/baseline/resonance_mc.py               # 1.0 内容，新旧计点规则对比
python3 docs/baseline/resonance_mc.py --content p0  # P0 内容
python3 docs/baseline/weapons.py
```

这些脚本只是设计阶段的估算。桌面版做出来以后，以 `lantern-tools balance` 的实测为准（`BALANCE.md` 第 11 节），埋点的统计项可以照着 `probe.patch` 移植过去。
