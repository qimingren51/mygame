#!/bin/bash
SP=/tmp/claude-0/-home-user-mygame/359de942-bb75-5fba-a0c0-c1c2c6f07e19/scratchpad
T=$SP/bin/tools-pool
for d in "$@"; do
  for pk in greedy random; do
    X=""; [ $pk = random ] && X="--picker random"
    LANTERN_DATA=$SP/pool/$d/data $T kite --runs 100 --seed 101 --meta none --skill novice --tier 1 $X --csv $SP/pool/$d-$pk-nov1 > $SP/pool/$d-$pk-nov1.txt 2>&1
    LANTERN_DATA=$SP/pool/$d/data $T kite --runs 100 --seed 101 --meta half --skill regular --tier 3 $X --csv $SP/pool/$d-$pk-gen3 > $SP/pool/$d-$pk-gen3.txt 2>&1
  done
done
echo POOL-DONE
