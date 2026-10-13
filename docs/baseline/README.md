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
| `m25_kite.patch` | 第一版风筝机器人和燃灯充能修正（已收进 de0af3b；它只扫了妖物池的前 count 个槽位，有 bug，留作记录） | 第 2.6 节 |
| `m25_p0_tuning.patch` | 第一版的 P0 数据校准（已收进 de0af3b） | 第 2.6、4、9 节 |
| `m25_kite_skill.patch` | 给 `lantern-tools kite` 加 `--skill novice\|regular\|expert` 三档手法 | 第 2.6 节 |
| `m25_p0_pressure.patch` | 疾影加快、合围收紧（数据，已收进 d454bb2） | 第 2.6 节 |
| `m25_p0_tiers.patch` | 第三轮的更倍率（已被第四轮取代，没收） | 第 2.6、9 节 |
| `m25_p0_round4.patch` | 第四轮的数据：更的倍率、霜铃、符剑、灯火、铜镜灯、霜瓷灯、赤地 | 第 2.6 节 |
| `m25_p0_round5.patch` | 第五轮的数据：灯火再削、照见易伤上限 30%、照夜珠 +8% | 第 2.6、7.3 节 |
| `m25_p0_round6.patch` | 第六轮的数据：霜铃伤害再 × 1.15、寒山钟钟鸣 105 | 第 2.6 节 |
| `m25_endless_proto.patch` | 无尽夜“夜深”的原型代码：生命复利、移速、魂火打折、抗控制，用环境变量调 | 第 4.7 节 |
| `m25_mark_spread.patch` | 余印的原型代码（印记在妖物死时传给附近 3 只）；正式实现时参数请放进 `elements.ron` | 第 2.6、7.2 节 |

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

风筝机器人已经在 `lantern-tools` 里（提交 de0af3b）。按手法分档的补丁还没收：

```bash
git worktree add --detach /tmp/kite HEAD
cd /tmp/kite
git apply "$OLDPWD/docs/baseline/m25_kite_skill.patch"
cargo build --release -p lantern-tools
./target/release/lantern-tools kite --runs 60 --seed 101 --skill novice --meta none --tier 1
# 再试疾影加快、合围收紧：
git apply "$OLDPWD/docs/baseline/m25_p0_pressure.patch"
./target/release/lantern-tools kite --runs 60 --seed 101 --skill novice --meta none --tier 1
```

- `--skill novice|regular|expert`：手法（2.6 节的表），不写时是 expert。`--meta none|half|full`：局外成长。`--tier`：更。
- 环境变量 `LANTERN_DATA=<目录>` 可以换一套数据目录，几组数值并行比。
- 60 局在云端 4 核上约 5–7 分钟。

## 模拟

```bash
python3 docs/baseline/pacing.py
python3 docs/baseline/resonance_mc.py               # 1.0 内容，新旧计点规则对比
python3 docs/baseline/resonance_mc.py --content p0  # P0 内容
python3 docs/baseline/weapons.py
```

这些脚本只是设计阶段的估算。桌面版做出来以后，以 `lantern-tools balance` 的实测为准（`BALANCE.md` 第 11 节），埋点的统计项可以照着 `probe.patch` 移植过去。
