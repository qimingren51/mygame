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
| `m25_kite.patch` | 给桌面版加一个会躲的风筝机器人和 `lantern-tools kite` 子命令（三档局外成长、选更、按局统计），并按第 4.5 节修正燃灯充能 | 第 2.6 节 |
| `m25_p0_tuning.patch` | 第 2.6 节建议的 P0 数据改动：刷怪系数、接触伤害、夜主生命、更 | 第 2.6、4、9 节 |

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

## 复现 M2.5 的 P0 实测（第 2.6 节）

现状在 M2.5 局外层（提交 2eaa1f5）上测，调整后在提交 72c9dd2 上测。两个补丁都只是实验用，不提交到 `crates/` 和 `assets/data/`：

```bash
git worktree add --detach /tmp/kite HEAD
cd /tmp/kite
git apply "$OLDPWD/docs/baseline/m25_kite.patch"
cargo build --release -p lantern-tools

# 现状
./target/release/lantern-tools kite --runs 100 --seed 101 --meta none --tier 1
# 建议的数值：再打上数据补丁
git apply "$OLDPWD/docs/baseline/m25_p0_tuning.patch"
./target/release/lantern-tools kite --runs 100 --seed 101 --meta half --tier 2
```

- `--meta none|half|full`：局外成长三档。`half` 约等于第 35 局：属性买一半，心灯点一部分，挂长命锁。`full` 是全部买满、点满。具体等级见补丁里的 `meta_setup`。
- `--tier 1|2|3`：更。`--lamp <id>`：灯，不写时用红纸灯。
- 环境变量 `LANTERN_DATA=<目录>` 可以换一套数据目录，方便同时试几组数值。
- 100 局在云端 4 核上约 4–5 分钟；可以开几个进程并行跑。
- 机器人的走位：每步在 16 个方向里挑威胁最小的（附近的妖物、按速度外推的弹幕、夜主的扇形和落点预警、结界边缘），安全时去点石灯笼，快被碰到时闪避。它离夜主和大只精英比真人远，所以夜主击杀时间偏长。

## 模拟

```bash
python3 docs/baseline/pacing.py
python3 docs/baseline/resonance_mc.py               # 1.0 内容，新旧计点规则对比
python3 docs/baseline/resonance_mc.py --content p0  # P0 内容
python3 docs/baseline/weapons.py
```

这些脚本只是设计阶段的估算。桌面版做出来以后，以 `lantern-tools balance` 的实测为准（`BALANCE.md` 第 11 节），埋点的统计项可以照着 `probe.patch` 移植过去。
