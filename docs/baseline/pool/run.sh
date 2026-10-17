#!/bin/bash
# 第 9 项卡池的对照（BALANCE.md 6.4 节）。先在 47f08a6 上打 pool_proto.patch 编出 lantern-tools，
# 再把每个方案的数据目录放在 <目录>/<方案>/data（b8：用 run-b8.ron、passives-b8.ron 换掉 run.ron、passives.ron）。
#   bash run.sh <lantern-tools 路径> <目录> b8 …
T=$1; DIR=$2; shift 2
for d in "$@"; do
  for pk in greedy random; do
    X=""; [ $pk = random ] && X="--picker random"
    LANTERN_DATA=$DIR/$d/data $T kite --runs 100 --seed 101 --meta none --skill novice --tier 1 $X --csv $DIR/$d-$pk-nov1 > $DIR/$d-$pk-nov1.txt 2>&1
    LANTERN_DATA=$DIR/$d/data $T kite --runs 100 --seed 101 --meta half --skill regular --tier 3 $X --csv $DIR/$d-$pk-gen3 > $DIR/$d-$pk-gen3.txt 2>&1
  done
done
# 汇总：python3 sum.py <目录> b8 …
