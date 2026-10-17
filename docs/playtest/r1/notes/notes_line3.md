# 妖物重做 · 进度笔记（line3）

## 背景
- 用户选了 A 精修三维。B 手绘分件不再做。
- 协调者的新指示（2026-10-16）：1) 影妖、赤面狐定稿接进正式管线（produce.py，资源名 shade / fox，meta 加 contact_radius，check_asset 通过）；
  2) 其余 9 只按外形描述重画（顺序 wisp, golem, fox_wisp, bamboo_wraith, taofeng_fox, ghoul, stonelord, toad, boss）；
  3) 两三只一批：scratchpad 里开 worktree（基于 origin/master）→ 打包 actors / boss → 逐像素对比没改的帧 → check_atlas.py
  → 提交到分支 playtest-r1-enemies 并推送（不推 master）→ 回报（哪几只、contact_radius、审图路径）。

## 已完成
- 样张阶段（A/B 对比）全部完成：art/out/enemy_sample@2x/{shade,fox}_{A,B}/，审图 art/out/review@2x/enemy_sample_*。
- 阶段 1：正式管线接入完成。render/enemies_v2.py（V2 表）+ produce.py 分流；check_asset 加 style=paint、register_band。
- 第一批（shade、fox）18:27 推送：分支 playtest-r1-enemies，提交 e001d59（基于 origin/master 127e037）。
  contact_radius：shade 13.0（float 13.9）、fox 20.1（move 20.1 / pounce 25.2）。已回报 main。
  actors 分两页（actors_0 4096²、actors_1 1024×512）。⚠ crates/game/tests/smoke_test.rs:103 写死 actors.png，已告诉 main。
- 打包方法：art/post/atlas_swap.py（从现有图集还原其它素材 + 换新素材 + 逐像素核对）。
- worktree：/tmp/claude-0/-home-user-mygame/01f265ce-5196-560e-be75-2f924c080bfe/scratchpad/wt_enemies（分支 playtest-r1-enemies）
- 旧素材备份：art/out/assets@2x_old/<名>（审图“现版”列用）。

## 不提交的文件
- 样张用：art/post/ink2d.py、enemy_2d.py、enemy_sample.py、art/render/enemy_sample_a.py
- 别的代理的：art/post/card_frames.py、hud_frames.py、moon_textures.py、test_moon_textures.py、art/render/card_art.py

- 第二批（wisp、golem、fox_wisp + 赤面狐脸谱/腿/起伏、影妖墨烟、README 打包命令）推送：提交 11c419c，
  分支先快进到 origin/master 8c80477（第一批已被合进 master，冒烟测试已由架构改成按 index.json 找第一页）。
  contact_radius：wisp 10（11.1）、golem 14.4、fox_wisp 10（10.9/11.9）、fox 21.1（25.5）、shade 13.0。已回报 main。
  wisp、fox_wisp 帧 160→224。golem meta register_x_only；fox move vertical_motion。
- 新的公共件（v2kit）：design_patch（设计稿形状投到表面，CDT 三角剖分）、design_outline、tube_arrays、brush_material、
  membrane_alpha、flat_strip/strip_arrays、d2m/wave_line/design_strip、add_glow_const。
- 审图：enemy_review.py 支持 “素材:批” 对比 out/assets@2x_<批>/（b1 备份在 assets@2x_b1）。
- 测试用：scratchpad/b2/render_to.py（渲到临时文件夹）、quick_look.py、*_sketch.py（二维草图）。

## 下一步
- 第三批：bamboo_wraith（竹魅）、taofeng_fox（讨封狐）、ghoul（青面鬼）。之后 stonelord、toad、boss。
- 收尾时再修：狐火的火形、疾影的体积感、石妖缝光。

## 外形描述（世界观会话，原话；docs 里没有，从主会话记录里抄出来的）
- 疾影：不是缩小的影妖。一缕被风扯长的薄墨烟，细长、身子前倾，像一道斜着的笔锋，拖一条长尾，半透明，能看见里面一点魂光。只有一点眼光。大小约影妖一半。急、轻、飘。
- 石妖：青灰山石垒成的矮胖身子，没有脖子，两条胳膊是拖地的长条石，身上长青苔，裂缝里透暖黄的魂光。笨重、憨，但有压迫感。
- 金蟾：三条腿的圆胖蟾蜍，嘴里衔一枚方孔铜钱，背上的疙瘩是一枚枚铜钱，通体金黄。跑起来铜钱叮当往下掉。可爱、滑稽、带点贼。
- 青面鬼：魁梧佝偻的大鬼，青灰皮肤，獠牙外翻，乱发，赤红眼。肚子鼓胀，吞下的魂光从肚皮里透出来。冲锋时低头。主色青灰、赤。凶、压迫。
- 石将（精英）：陵墓神道两旁的石翁仲：方正高大，戴盔披甲，双手持一柄长刀，面目被风化得模糊，青苔从脚往上爬，走动时掉石屑。主色青灰石色。庄严、冷。
- 九尾（夜主）：巨大的白狐，身形修长，九条尾巴像扇面一样展开，尾尖染着青火。额心一点青，眼睛也是青的。脸上不画红（和赤面狐分开）。主色月白、青。美而凛，是护崽的母亲，凶起来不留情。
- 狐火：一团青绿的冷火，火苗往后拖成狐尾的样子，火心里隐约有两点狐眼。俏、诡异。
- 竹魅：一截截青竹节拼成的细长人形，手指是竹枝竹叶，头是一团竹叶，叶缝里两点眼。放竹刺时身上竹节裂开。主色青竹绿、墨。静、诡异。
- 讨封狐：两种样子。照见圈外是戴斗笠、披蓑衣的矮个路人，佝偻着，斗笠压得看不见脸，蓑衣下摆露出一截毛尾巴；进了照见圈就现形：一只直立的狐狸穿着不合身的人衣，袖子太长，眯眼笑。主色蓑草黄、狐赭。诡异里带滑稽。
- FEEL 里讨封狐现形的特效是“头上那片叶子飘下来（3 片竹叶）”→ 扮人时斗笠顶上放了三片竹叶。

## 第三批（2026-10-17，接手的子代理）
- 工作区 wt_enemies 已快进到 origin/playtest-r1-enemies-b2（75af3b2）并合了 origin/master。
- 现版备份：art/out/assets@2x_old/{bamboo_wraith,taofeng_fox,ghoul,stonelord,toad,boss}（从图集还原：scratchpad/b3/backup_old.py）。
- 竹魅 models/bamboo_v2.py：重写（前任的竹筒头不符合“头是一团竹叶”）。一节节竹段（段间墨色竹节）、头是一蓬披下来的竹叶（遮着焦墨的空和两点眼）、
  手是三根竹枝挂竹叶；shoot 像拉弓：远手前伸、近手把竹刺拉到腮边，竹节裂开透光（节缝里放发光的芯）。
- 讨封狐 models/taofeng_v2.py：重写。帧 224→256。斗笠顶三片竹叶、蓑衣三层、杖；现形后靛蓝旧袍、长袖（白里子）、斗笠挂背上、眯眼笑。
  reveal 加了 vertical_motion（一跳）。
- 青面鬼 models/ghoul_v2.py：新写。v2kit 加了隐式曲面工具（smin、sd_round_cone、sd_ellipsoid、sdf_mesh = surface nets），
  躯干、肚子、四肢、头各一块；肚子单独材质（发白、魂光走 AOV + 白天暖黄斑）；獠牙、黑爪、焦墨乱发、暗红破布。眼色改红 #FF4636
  （enemies.ron 里还是 #C8FF6B，回报时提醒）。
- 测试工具：scratchpad/b3/look.py（渲几帧对比主角）、full.py（整只渲到 b3/test + 帧条 + 动图）、strip.py、bw_sketch.py。
- 第三批已推送：提交 a01a03d，合 origin/master（2163392）为 0745b71，推到 playtest-r1-enemies（11c419c..0745b71 快进）。
  contact_radius：竹魅 12（走 16.2/射 31.2/idle 10.4）、讨封狐 13（扮人 16.1/现形 12.9/reveal 13.1）、青面鬼 23.6（冲锋 32.4）。
  actors 图集一页放下了：actors.json（index.json 跟着改）。没换的 419 帧逐像素相同；check_asset、check_atlas、
  cargo test -p lantern_ui layout（读真图集）通过。审图 art/out/review@2x/redo_b3_*、redo_{bamboo_wraith,taofeng_fox,ghoul}_*.gif。
- v2kit 新增（第四批起用）：sd_box、wave_noise、rot_y、d3m（设计稿三维 → 模型）、sdf_arrays、merge_arrays、prism_arrays。
- 第四批：石将 stonelord（SDF 方块 + 刻槽属性 + 青苔 + 掉石屑；3/4 侧面 YAW）、金蟾 toad（SDF 圆胖身子 + 铜钱）。
- 第四批已推送（2026-10-17 11:3x UTC）：提交 d916438（石将、金蟾），合 origin/master（6ba6142）为 c894ea0，推到 playtest-r1-enemies。
  contact_radius：石将 13.4、金蟾 14（前沿 17.1）。金蟾帧 160→192、整体往后挪 3.5；石将 move 加 vertical_motion。
  actors 仍一页，没换的 512 帧逐像素相同；check_asset、check_atlas 通过。审图 redo_b4_*、redo_{stonelord,toad}_move.gif。
- 省额度：出整套用 b2/render_to.py（EV.render 直接渲到 art/out/assets@2x），别用 produce.py（会把全部素材自检一遍，8 分钟）。
- 下一步：九尾 boss（boss 图集，帧 640²，move 8、sweep 6（2 帧蓄力）、summon 4），然后收尾三项。
- 九尾（2026-10-17 12:0x UTC）：models/boss_v2.py 写好（借用 fox_v2；SCALE (1.9, 2.05, 2.15)；月白、青眼、额心青印、
  九尾扇面、尾尖青火走 AOV——别用发光材质，发光层按物体分，整条尾巴会进去）。V2 表 boss：register_band [0.58, 0.74]
  （move 的“身高”在锚点那一列量到的是背，不是尾扇）。summon 最后几条尾巴限角 188°、短一点，不然出画。
  整套约 12 分钟（每帧 36 秒）。contact_radius 34.8（原表 40：新头在 52 单位以上，前沿只量到胸和前腿）。
- 收尾三项代码已改（未渲）：fox_wisp_v2 打开尾巴外沿火舌 TAIL_FLAMES、加两条 TONGUES 和头顶一簇 LICK；
  wisp_v2 加 _volume（笔画后面一根半透明的薄烟管：membrane_alpha + alpha_streak）；golem_v2 缝光 AOV 0.55→1.0、
  缝加厚加多（SEAMS2）、肚石背石上加发光裂缝（CRACKS，design_outline）。

## 第五批（九尾）已推送（13:43 UTC）
- 提交 2ce3db8（九尾 + boss 图集），合 origin/master fcbb79b → 535ff83，已推 playtest-r1-enemies。
- atlas_swap --name boss：boss 图集只有九尾（54 帧，没换的 0 个）；check_asset、check_atlas 通过（合并后再查一遍也过）。
- contact_radius 34.8（move；sweep 42.4、summon 31.9），原来 40；眼色 #5FE8D6（enemies.ron 现是 #FFD98A）；挂点 eyes 比原来高很多（-263 vs -164）。
- 审图：art/out/review@2x/redo_b5_{lineup,ingame,zoom3}.png、redo_boss_{move,sweep,summon}.gif
- 下一步：收尾三项（fox_wisp、wisp、golem）。先备份现版到 art/out/assets@2x_b2/，look.py 渲关键帧，再 render_to 整套。

## 九尾返工（协调员审过 2ce3db8：先不合，排在收尾前）
- 要改：身子用 SDF 重做（胸厚腰细、后腿大腿肌肉+反关节、前腿细长带腕和爪、颈长弯、头低前探、胸前颈下白毛领 brush/strip）；
  九尾摊成身后大扇面（左右张 140–160°），每条有弧度、根细中蓬尖青火、前后有层次，不挤一个平面；可加大画布但别出画；
  神态美而凛：眼细长上挑、青光更亮、脸窄吻长、耳大带内耳白毛。
- 流程：先 move 一两帧缩略图（和旧版、主角并排）给协调员看，方向对了再出整套；接触半径重量后回报。
- 收尾三项关键帧已渲在 b6/（fw1/wi1/go1.png），现版备份在 art/out/assets@2x_b2/{fox_wisp,wisp,golem}。
- 方向图（b5/cmp1_third.png）协调员认可：按这个出整套。整套前改三处：毛领改成一团蓬松毛量（外形柔、边缘用笔触尖毛收，
  颈侧层数减少、每层更宽更软）；扇面整体缩一成（1080p 下像狐狸背着扇面）；尾巴更蓬（中段粗、根尖细，长短弯度略有不同，前亮后暗）。
- 新 boss_v2.py：SDF 身子/腿/头（头静止网格按颈端摆）、G=1.12 整体放大（JWBody.scale）、HEAD_K=1.2；帧 768²（size_1x 384）。
  草图工具 b5/sketch.py（不进 Blender，按画面投影画多边形），对比 b5/cmp.py。单帧 look.py 约 1 分钟。
- 出整套后：check_asset、check_atlas、旧帧比对、redo_b5_* + 三动图、推送，回报哈希、contact_radius、眼睛挂点新位置。
- 九尾返工已推：提交 ab50da4，合 origin/master 97dec30 → c19f7fe（playtest-r1-enemies）。帧 896²，boss 图集分 boss_0/boss_1（4.4+1.4 MB）。
  register_band [0.30, 0.42]；contact_radius 44（move 前沿 74.8 含头；sweep 70.8、summon 47.1；锚点上 40 单位内 move 48.4）。
  眼睛挂点 move (251.8, -237.1) px = (+63, -59) 单位。审图 redo_b5_*、redo_boss_{move,sweep,summon}.gif；对比 b5/cmp2_third.png。
  上一版（2ce3db8）帧备份在 art/out/assets@2x_b5a/boss。lantern_view 73 测试过。
- 下一步：收尾三项（关键帧已在 b6/，现版备份 assets@2x_b2/）。

## 收尾三项已推（狐火、疾影、石妖）
- 提交 c94b6f2，合 origin/master b04c6f1 → 866ac2e（playtest-r1-enemies）。actors 图集分成 actors_0（4096²）+ actors_1（512²，4 帧）。
- check_asset、check_atlas 通过；没换的 476 帧逐像素相同；contact_radius 不变（10、10、14.4）；lantern_view 73 测试过。
- 审图 redo_b6_{lineup,ingame,zoom3}.png（和 b2 版并排）、redo_{fox_wisp_float,fox_wisp_pounce,wisp_float,golem_move}.gif。
- 第三条线（妖物重画）全部完成：第三、四批、九尾（返工）、收尾三项。
