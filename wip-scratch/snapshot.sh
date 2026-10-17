#!/bin/bash
# 把美术还没提交的改动快照到 wip/playtest1-art（只做备份，不合 master）。
# 内容：主仓库改动和新文件（原路径）、各工作区的改动（wip-worktrees/<名>/）、
# 进度笔记（docs/playtest/r1/notes/）、scratchpad 里的小脚本（wip-scratch/）。
# 大于 2MB 的文件（图集）不拷，能用脚本重新生成。
set -euo pipefail
SP=/tmp/claude-0/-home-user-mygame/01f265ce-5196-560e-be75-2f924c080bfe/scratchpad
REPO=/home/user/mygame
W=$SP/wt-wip
BR=wip/playtest1-art
MAX=2000000

cd "$REPO"
git fetch origin "$BR" --quiet
[ -d "$W" ] && git worktree remove --force "$W"
git worktree add --detach "$W" "origin/$BR" >/dev/null 2>&1

copy() {  # copy <src> <dst>
  local s=$1 d=$2
  [ -f "$s" ] || return 0
  if [ "$(stat -c %s "$s")" -gt "$MAX" ]; then echo "skip big: $s"; return 0; fi
  mkdir -p "$(dirname "$d")"
  cp -p "$s" "$d"
}

# 主仓库：原路径
git ls-files -m -o --exclude-standard -z | while IFS= read -r -d '' f; do
  copy "$REPO/$f" "$W/$f"
done

# 各工作区：wip-worktrees/<名>/
for wt in wt wt-moon wt_enemies; do
  P=$SP/$wt
  [ -d "$P" ] || continue
  dst=$W/wip-worktrees/$wt
  rm -rf "$dst"
  (cd "$P" && git ls-files -m -o --exclude-standard -z) | while IFS= read -r -d '' f; do
    copy "$P/$f" "$dst/$f"
  done
  if [ -d "$dst" ]; then
    { echo "branch: $(git -C "$P" rev-parse --abbrev-ref HEAD)"
      echo "base: $(git -C "$P" rev-parse HEAD)"
      git -C "$P" status --short; } > "$dst/STATUS.txt"
  fi
done

# 进度笔记与 scratchpad 小脚本
mkdir -p "$W/docs/playtest/r1/notes"
cp -p "$SP"/notes_line*.md "$W/docs/playtest/r1/notes/" 2>/dev/null || true
for d in . l2 b2 b3 tools; do
  for f in "$SP/$d"/*.py "$SP/$d"/*.sh; do
    [ -f "$f" ] || continue
    copy "$f" "$W/wip-scratch/$d/$(basename "$f")"
  done
done

cd "$W"
git add -A
if git diff --cached --quiet; then
  echo "nothing new"
else
  git commit -q -F - <<'EOF'
WIP：试玩第 1 轮美术快照（子代理进行中，未审）

只做备份：主仓库改动、各工作区改动（wip-worktrees/）、进度笔记、scratchpad 小脚本。不合 master。

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_016wrsqW1m7DE4TZou4HCj3C
EOF
  git show --stat --format='%h %s' HEAD | tail -n 3 || true
  for i in 0 2 4 8 16; do
    sleep $i
    if git push -q origin "HEAD:$BR"; then echo "pushed $(git rev-parse --short HEAD)"; break; fi
  done
fi
cd "$REPO"
git worktree remove --force "$W"
