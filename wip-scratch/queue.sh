cd /home/user/mygame
for id in "$@"; do
  art/.venv/bin/python art/render/card_art.py $id --no-post --samples 128 2>&1 | grep -v "CUEW\|^Fra:" | tail -1
done
