# 青丘地区包：未完成的进度（wip/qingqiu-art 分支）

这个分支保存的是暂停时的半成品，**还没审、没打包**，不要直接合进 master。

## 已经完成并在 master 上的
- 青丘道具：`models/qingqiu_props.py`、`render/props_qingqiu.py`（竹丛和砍倒的竹丛、狐仙祠、石狐、狐村灯串），已审过（65d34f7）。图集还没打包。
- 冲锋预警 `weapons/charge_line` + `charge_line_head`（345669b）。

## 这个分支里的半成品
- 妖物（Blender，样张阶段）：
  - `models/fox_wisp.py`（狐火）、`models/bamboo_wraith.py`（竹魅）、`models/taofeng_fox.py`（讨封狐）；
  - `models/fox.py`（赤面狐 pounce、九尾 sweep / summon）、`models/ghoul.py`（青面鬼 charge）的新动作、`models/kit.py`；
  - `render/produce.py` 的批次表；审图脚本是 `render/qingqiu_review.py`。
  - 样张还没给美术会话审过。
- 地面、迷雾、竹刺、开场卷轴（Pillow，样张阶段）：
  - `post/ground_decor.py`（`qq_*`）、`post/vfx_textures.py`（`mist_0..1`）、`post/weapon_textures.py`（`bamboo_spike`、`bamboo_spike_trail`）；
  - `post/scroll_qingqiu.py` 和 `post/test_scroll_qingqiu.py`；两个自检脚本也有改动。

## 和架构会话约好的规则
- 蓄力动作在 meta 里写 `windup_frames: n`。
- 九尾的 `sweep`、`summon` 设为 `loop: false`。
- `bamboo_spike` 锚点居中、朝 +X。
- 迷雾放进 vfx 图集，meta 写 `tileable: true` 和 `tile_units`（不要写 `tile`）。
- 卷轴放在 `screens/`，不进图集。

## 恢复时
1. 在 master 上 `git checkout wip/qingqiu-art -- art/`（或合并这个分支），装好 `art/.venv`（见 art/README.md）。
2. 中间产物 `art/out/` 不提交，需要重新渲染：
   - 道具：`LANTERN_ART_DENSITY=2 art/.venv/bin/python art/render/props_qingqiu.py`。
   - 妖物、地面、卷轴先出样张，审过后再正式出图。
3. 打包新的 actors、boss、vfx、ground 和 screens，运行 `check_atlas.py`，更新 DESIGN 第 15 节，推送前先通知架构会话。
