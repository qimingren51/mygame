# 线 1 进度笔记（美术子代理）

scratchpad = /tmp/claude-0/-home-user-mygame/01f265ce-5196-560e-be75-2f924c080bfe/scratchpad
工作区：$SP/wt-moon（git worktree，主仓库 /home/user/mygame；Python 用主仓库的 /home/user/mygame/art/.venv/bin/python）
字体：$SP/wt-moon/art/out/fonts 是从主仓库拷的（避免下载）。vfx_leaves 也是从主仓库 art/out/assets@2x/vfx_leaves 拷的
（test_fx_extras 要 art/out/screens/scroll_qingqiu.png，工作区没有，跑不了；它重画的 vfx_leaves 和主仓库逐字节相同）。
草稿工具：$SP/tools/frame_stats.py（逐帧统计）、$SP/tools/compare_vfx_pack.py（vfx 图集打包前后逐像素对比）。

## 顺序（协调者第 3 次调整，2026-10-17，接手的子代理）
1. 铜钱剑按新半径重画（coin_slash 独立出图 140–170，coin_whirl 200）—— **完成**，已推 3ffa25f
2. 特效第二批（fire_burst、ice_shatter、feather、evolve、evolve_pillar）—— **完成**，已推 b6ab5c8
3. 四件新法器的持续画面（沧浪、青藤 **完成** 49e5d1a；孔明灯、镇妖塔 **完成** f0a1e7e）：weapons/sky_lantern（Blender 纸灯笼，飘 4 + 坠 3）、wave_front（月牙浪头 4 循环 + 散 3，叠加可染）、
   vine（锚点右端、沿 X 拉伸、粗约 10、叶子 3 帧）、tower（镇妖塔 R45 宽 40 高 70；玲珑塔 R60 宽 56 高 96；落 3、立 2 循环、收 3）
   + 各自事件的一次性特效（落点圈、火海贴花 4 循环、泡沫痕、绿光回流、尘土冲击波、金色冲击波，能复用就复用）
4. 特效第三批（十种反应 react_*）
规矩：只在 art/ 写脚本；每次打包后逐像素对比；1080p 下约一比一（1 单位 ≈ 2.57 像素）、单帧 ≤ 1024²、meta 写 radius_px；
Blender 最终渲染包在 B.render_lock() 里；每完成一项推一次、SendMessage(to: "main") 回报一次。
推送：$SP/tools/push_retry.sh $SP/wt-moon playtest-r1-vfx（2/4/8/16 秒重试；前台不能 sleep，用 python 的 time.sleep）。

## 1. 月夜收尾（完成）
- 分支 playtest-r1-moon-art：f737cc8（月夜改版）→ 2260536（合 master 840514f）→ baf570f（moon_textures 读分页的 actors 图集；
  赤面狐重画后月下 L* 差只有 11–12，test_previews 对它放宽到 10，其余 15；都比现状多拉开 ≥ 8）。已推送。
- 早先：逐像素对比 vfx 57 帧相同 + light_pool；ground 21 相同、14 调浓；1 倍 58 个文件逐字节不变。

## 2. 特效第一批（完成，playtest-r1-vfx 4d335d9）
- 分支 playtest-r1-vfx 从 baf570f 开（含月夜提交），用 merge 合 master（不 rebase，保住 f737cc8，两个分支先后合都不冲突）。
- art/post/vfx_frames.py（BATCH1，只出 2 倍）、vfx_frames_review.py（帧条 + 1080p 合成）、test_vfx_frames.py（17 项）。
- 47 帧：hit_{metal,wood,water,fire,earth}_0..4（128²）、crit_0..3（192²，#FFF3D6）、slash_0..5（256×448，锚点 (0.0625,0.5)，
  radius_px 200、angle_deg 120、points +x）、kill_ink_0..5（192²，焦墨，flat 0.62，hold_last）、shockwave_0..5（512×320，radius_px 220）。
- 叠加帧 alpha 映射：peak·tanh(1.25a)/tanh(1.25)，最亮 204。
- 打包：vfx 2048×1024 → 2048×2048；原 58 帧不变。

## 3. 铜钱剑（完成，playtest-r1-vfx 80579e7 + 合 master cb8eeec → 5cc4028）
- art/post/weapon_textures_ea.py（BATCHES["coin"]，输出 out/assets@2x/weapons_ea/，meta name "weapons"）、test_weapon_textures_ea.py（14 项）。
- weapons/coin_spark_0..4（128²，锚点 (0.375,0.46875)，自带铜金色，points +x）、coin_whirl_0..5（448²，radius_px 192，顺时针）、
  coin_cross_0..3（160²）；后两组可染，tint_hint #F2C46A。
- vfx_frames.write 加了 out/name/generator 参数；审图 ingame 的摆法是 (名, 帧, (x,y), 摆法, 想要的半径或 None)。
- 打包：仍 2048×2048（64%），原 105 帧不变，新增 15 帧。
- 检查：check_atlas 通过；test_vfx_frames 17/17；test_weapon_textures_ea 14/14。

## 4. 铜钱剑按新半径重画（完成，playtest-r1-vfx 3ffa25f；先合了 master 2a53dad → bbad158，DESIGN.md vfx 那行冲突手工合并）
- weapons/coin_slash_0..5：512×896，锚点弧心 (0.03125, 0.5)，radius_px 440、angle_deg 120、points +x，叠加、白可染（#F2C46A）。
  笔锋扫过 0–2 帧（起笔、收笔各探出扇形一点），刃口闪出铜钱影子（coin_glyph），扇面细风痕（tex_w），速度线越靠里越落后。
- weapons/coin_whirl_0..5：1024²，radius_px 464，薄两成，笔锋带铜钱影子，旋涡风痕。coin_spark / coin_cross 没动。
- weapon_textures_ea.py：tiled()（按行分条算，fn(acc) 往 F.Acc 里画）、finish_white()、coin_glyph()、crescent(edge_w)；
  掩码只算有东西的像素：挥击 15 秒、旋风 70 秒。审图 ingame 一个场面一张：weapons_ea_coin_ingame.png、weapons_ea_coin_whirl_ingame.png。
- vfx_frames.py 的 main(only) 修了：原来 sys.argv[1:] 把测试的 --regen 当批名，导致测试从不重画。
- 提交 1 的 vfx_frames.py 是去掉第二批的版本（helpers + main 进了提交 1）；完整版（含第二批）在 $SP/full_b2/vfx_frames.py，已拷回工作区。
- 打包：b1 只用 $SP/stage1/vfx_frames（从产物里挑出 b1 的 47 帧 + meta），vfx 2048² → 4096²（47%）。
  对比工具 $SP/tools/compare_pack2.py <旧> <新> --changed 前缀 --added 素材目录,…（旧帧逐像素逐字段、新帧和素材一致、别的文件逐字节）。
  打包前的图集备份：$SP/atlas_before_coin2。
- 检查：test_weapon_textures_ea 16/16、test_vfx_frames 17/17（--regen，b1 PNG 和打包用的逐字节相同）、check_atlas 通过。

## 5. 特效第二批（完成，playtest-r1-vfx b6ab5c8）
- 前任的初稿基础上：fire_burst 放大到 384²（FS = 1.5，radius_px 144），朝下短火苗改短改钝，笔触在窗口里算；
  smoke 同画布同锚点、meta 加 radius_px；evolve 花瓣笔毛纹改成沿花瓣（vperp），光芒末两帧按 ptex 断开；feather 0、1 重画成细长羽毛。
- 审图：普通混合可染的小粒子在帧条里纸色底染焦墨、夜色底画在暗层之上；ingame 加了 over 摆法（脚底、画在角色之上）；
  羽毛不进 ingame（纸白在纸上看不见）。
- test_vfx_frames 22 项（SPEC2、ALL、VARIANTS），全跑约 9 分钟（b1 70 秒 + b2 160–220 秒，确定性再来一遍）。
- 打包 159 帧，4096² 59%。打包前备份 $SP/atlas_before_b2。

## 6. 沧浪、青藤（完成，playtest-r1-vfx 49e5d1a）
- weapon_textures_ea.py：BATCHES coin / wave / vine，main(only)，NOTES；wave_front 的 7 帧一次算（lru_cache）拆成循环 4 + 散 3；
  循环组附加 meta 写 fps、loop: True，跟播的写 follows。
- vfx_frames_review.ingame 的摆法第 6 项：size_units（不等比拉伸）、to + h_units（从锚点拉到目标并转向）、face（+X 朝目标）。
- test_weapon_textures_ea：PLAY（fps、loop）、LOOPS、STILLS；循环首尾、浪头月牙、泡沫痕、藤、绿光、缠绕的专项。全跑约 4.5 分钟。
- 草稿：$SP/tools/try_ea.py <件> [组…] → $SP/ea_try/<件>/strip.png、ingame*.png。

## 7. 孔明灯、镇妖塔（完成，playtest-r1-vfx f0a1e7e）
- 协调者新规矩（额度预警，用完停到 22 号）：每做完一件就提交推送、回报哈希帧名尺寸；审图看缩略图或裁一小块，参数一次改到位；
  阶段写进本笔记；最终渲染拿渲染锁。合并候选 m2 由协调者做（质感在合 playtest-r1-vfx-m1 f19cfc0）。
- Blender：art/models/ea_weapons.py（BUILDERS：sky_lantern float 4 + fall 3；tower、tower_gold 只渲 idle 2 帧），
  art/render/weapons_ea_render.py --only … → out/assets@2x/ea_<名字>/（pipeline.render_asset，S 一个朝向，自带渲染锁）；
  灯 22 秒、塔 46 秒、金塔 75 秒。纸是 kit.flame_material（fade = 离灯里那团火的距离），烧穿用材质里的 BurnT 节点。
- weapon_textures_ea.py：lantern（sky_lantern*、lantern_mark、fire_sea）、tower（tower*、tower_gold*、tower_dust、tower_vortex）；
  塔的落下 / 收走是 2D（shift_scale、消散 + 金边）；发光层 soften_emit 压亮度；_emit 组 meta 写 layer_of。
- 审图摆法加了 air（54）、low（26）抬高；草稿工具 $SP/tools/preview_src.py（源图）、night_row.py（几组帧排一行）。
- 图集 4096² 83%（238 帧），第三批反应大概会分到第二页（pack_atlas 自动分页，游戏和脚本都支持）。
- 反应的范围（BALANCE 7.2）：燎原 60、赤地 50、凝霜 50、滋生 50、蒸腾 70、裂土 60、淤泥 70；熔金、断木单体；铸兵三片金刃。
