#!/bin/bash
# 推送，网络失败按 2/4/8/16 秒重试。用法：push_retry.sh <工作区> <分支>
cd "$1" || exit 2
for d in 0 2 4 8 16; do
  [ "$d" -gt 0 ] && python3 -c "import time; time.sleep($d)"
  if git push origin "$2"; then exit 0; fi
  echo "推送失败，${d} 秒后重试……"
done
exit 1
