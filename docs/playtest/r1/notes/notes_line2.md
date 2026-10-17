# 第二阶段笔记（黑漆描金量产）

## 已有（样张阶段，主仓库 /home/user/mygame 未提交的文件）
- art/render/card_art.py：Blender 插画（lamp、bell_evo、jixing 三个场景 + 后期），缓存 art/out/_card_tmp/*.npz
- art/post/card_frames.py：卡框（漆、绢）+ 样张拼图；件在 art/out/skin_card/
- art/post/hud_frames.py：状态栏样张；件在 art/out/skin_hud/
- 样张：art/out/review@2x/card_sample_*.png、hud_sample_*.png、card_art_*.png

## 用户选定：黑漆描金。绢本不再做。
## 顺序：1 卡框 → 2 数值图标 → 3 状态栏皮肤 →（推一次）→ 4 插画三批（每批推一次）
## 推送：scratchpad 里的 git worktree，基于 origin/master，分支 playtest-r1-ui-lacquer，不推 master

## 第 1–3 步：已推（2026-10-16）
- 分支 playtest-r1-ui-lacquer，提交 0ad8f75（基于 origin/master 840514f），worktree：scratchpad/wt
- 皮肤：改 card_fan/ling/xuan/tian/focus、slot_l*、slot_s*（88²）、bar_track、bar_fill_hp/xp/shield、chip_dark；
  新 card_yi、card_he、hud_portrait、hud_ult_tick/_on/_full、hud_level_seal、hud_hp_track、hud_xp_track、bar_fill_trail
- 其余件保留 master 原图（panel_dark 等 8 件重生成有漂移，master 脚本同样漂移，已核实）
- cards 页：19 个数值图标 ui/stat_*（meta name "ui"），index.json 已加 cards
- 检查：check_atlas 通过；test_ui_skin 13/13（art/out）；组合后 12/13（只差确定性，原因同上）；cards 帧逐像素一致
- 审图：art/out/review@2x/lacquer_1080p.png（脚本 scratchpad/review_1080.py，依赖 card_frames.py 的文字工具）
- 要告诉协调：卡面字色改纸色/淡金（choice.rs 的 INK）、card_skin 让 Yi→card_yi、He→card_he、按钮字用 INK 在浓墨按钮上看不清（原有）、
  DESIGN.md 第 15 节要补新皮肤名（架构的文件）、Rust 测试本机没跑（缺 alsa/udev、没缓存；分支推送不触发 CI）

## 第 4 步：插画（进行中）

（2026-10-17 容器重启后由新的子代理接手；以下是接手后的记录）
- 工作区：scratchpad/wt（分支 playtest-r1-ui-lacquer）。先快进到 origin 的 12cfadb（临时审图提交），再 merge origin/master → be4947d。
- 审图工具（scratchpad/l2/）：cardrev.py（拼图 cards_<批>_sheet.png：1 倍整卡 + 2 倍插画；1080p 升级界面 cards_<批>_1080p.png，四张卡）、
  look.py（试渲快看：1 倍 + 2 倍，带五行印、品阶签；--draft 读 _card_tmp/draft_*）、cmp_cards.py（cards 页打包前后逐像素核对）。
  在仓库根目录运行：art/.venv/bin/python scratchpad/l2/cardrev.py b1 lamp ... --screen a,b,c,d
- 打包：pack_atlas.py --name cards --no-trim --out <wt>/assets/atlas art/out/assets@2x/ui_stats art/out/assets@2x/ui_cards
  ui_cards 里只放已定稿的卡（jixing 先挪到 scratchpad/l2/hold/，第 2 批再放回）；card_art.write_meta() 按目录重写 meta。
- 莲子：界面代码 describe.rs 用的是 ui/card_heal（supply id "heal"），任务和 DESIGN.md 写 ui/card_lotus —— 按任务出 card_lotus，回报时提醒架构。

### 第 1 批（5 件法器本体 + 进化）：已推 1d4ba49（2026-10-17）
- 重画：sword_evo（剑影改成一股斜着涌向右上的宽带，剑都顺着带子指向同一处；领头剑贴黄符）、bell（铃身提亮、更多铜青，
  去掉褐色风摆，改铃舌下垂一束红穗）、crane（侧面看、双翅高举成 V）、seal（青石更粗粝、朱砂压暗、地面压暗 spec=0.08、镜头近一点）。
  其余 6 张沿用前任 19:3x 的定稿。
- card_props：mat_stone 加 bump_dist；mat_ground_crack 加 spec；新增 metaball 手（hand / hand_points / HAND_OPEN / HAND_FIST）和 mat_skin。
- card_art：寒山钟的钟身抽成 temple_bell(frost)（静心要用不结霜的钟）；mat_bronze_bell 加 frost。
- cards 页 2048×2048（29 帧）；check_atlas 通过；19 个数值图标逐像素不变；其余 188 个文件逐字节不变。
- 审图：art/out/review@2x/cards_b1_sheet.png、cards_b1_1080p.png
- Rust 测试没跑：没有测试读 cards 页（只有 Windows/Xvfb 的冒烟测试），改动只有资源。

### 协调新规矩（2026-10-17 10:40 UTC 起，账号 7 天额度预警，用完五个会话都停到 22 号）
- 每批做完就推，不攒；省额度：审图先看 1 倍缩略图或裁局部，大图别反复打开；同一张别反复重渲，参数一次改到位；
  每做完一个阶段写进本文件；正式渲染照旧拿渲染锁。
- master 现在 cc2112f（含第 1 批 1d4ba49）；莲子定为 lotus（代码找 ui/icon_lotus、ui/card_lotus）。

### 第 2 批（17 门心法）：已推 847db87（2026-10-17，先 merge origin/master cc2112f → 0ccbab2）
- 17 张正式渲染完（疾行用前任缓存 --post 重出）；cards 页 46 帧 4096×2048；原 29 帧逐像素不变，其余 186 个文件逐字节不变；
  check_atlas 通过；lantern_ui lib 测试 63 个通过（CARGO_TARGET_DIR 借主仓库的 target）；test_ui_skin 13/13。
- 同一提交带上 hud_ult_tick 暗格提亮。审图：art/out/review@2x/cards_b2_sheet.png、cards_b2_1080p.png。
- 省额度的审图工具：scratchpad/l2/thumbs.py（只拼 1 倍缩略图，--draft 读试渲）。

### 第 3 批（5 异化 + 3 合璧 + 莲子、灯油）：场景代码改了一轮（还没推）
- 第一轮试渲都不行，已重写：冰火两重天（冷暖两份火材质、霜纸带墨字、灯里冷暖两盏光分开、灯顶白汽团）——第二轮试渲已过；
  赤霄（烧红的剑横过画面 + 白烟蛇被斩成两截）——第二轮试渲已过，蛇再淡一点、头大一点（已改）；
  冻土（霜铃悬在冻裂的地面上方，裂缝冰蓝光、冰晶簇）——第二轮还要改：裂缝光太白、冰晶太碎太蓝、碎冰发黑（已改，待试渲）；
  铁鹤（纸鹤的形折成铁，两翼换成一扇扇铁羽，右翼三片射出去）、竹印（碗口粗的巨竹 + 笋箨 + 掀起的地皮，印面朝下露“山”）、
  百鸟朝凤（火羽一片片的凤 + 朝凤的纸鹤 + 背景墨点小鸟）、万剑冢（土冢上的剑林逆着满月）、
  霜天剑雨（近处整把冰剑 + 远处四角攒尖钟亭）、莲子（莲蓬顶面朝镜头）、灯油（深褐釉壶、镜头退后）——都待试渲。
- card_weapons.py 新增：wind_bell（霜铃的铃，build_bell 改用它，结果不变）、mat_puff、mat_snake_smoke、mat_hot_steel(L)、
  mat_flame_feather、feather_width、pavilion_roof_build、low_spec、mat_sheath；crane_build 加 wings 参数（默认不变）。

### 第 3 批进展（2026-10-17 下午）
- 协调：第 2 批用户满意；锐目必须重画（不要写实皮肤、睫毛；暗处只一道月光照亮眼睛这一条，铜金放射纹虹膜，瞳孔里方孔七钱排北斗）
  → 已重写（card_passives：mat_iris + 真的小方孔钱 coin_build，眼睑只是暗影），跟第 3 批一起推，审图里标“重画”。折纸不改（已还原）。
- 三轮试渲后定稿的场景改动：铁鹤改回纸鹤的形（crane_build 带翅）+ 翼后缘一排三角铁羽 + 三支射出的铁羽；竹印印飞得更高、碎石；
  万剑冢镜头放进剑林里（剑都比人高）；莲子荷叶 UV 一圈 12 道叶脉（原来一道中脉像一束光）；灯油釉面高光收。
- 正式渲染队列：lamp_mut sword_mut bell_mut sword_grove phoenix frost_rain seal_mut lotus oil ruimu（l2/b3_final.log），之后 crane_mut。

### 第 4 批（新法器）准备
- 图标：art/post/ui_icons_new.py（新文件）→ art/out/assets@2x/ui_new（meta name "ui"，帧名 ui/icon_<id>、ui/icon_<id>_evo），
  10 个已出，审过（l2/new_icons*.png）；小孔明灯的火心太小会把整张填满 → 小灯不画火心，并加了“圆底外必须透明”的检查。
- 卡面：card_weapons 新增 青藤、万木春、镇妖塔、玲珑塔（mat_vine、mat_life_stream、helix_path、eave_build、pagoda、mat_vortex、spiral_in）；
  铜钱剑镜头近、剑更斜；天罡旋风亮；孔明灯挪开右上角；沧浪、北冥潮水面毛一点、白沫多、北冥潮更俯。WOOD_GRADE 挪到 card_weapons。
  10 张试渲排在铁鹤正式渲染之后（l2/b4_draft.log）。

### 进阶属性图标（20 个，ui_lacquer.py 的 ADV_KEYS，原 19 个逐字节不变）
| 属性（stat_labels.ron） | icon |
| --- | --- |
| Knockback | knockback |
| BurnDamage、BurnStacks、TrailDamage | burn |
| FrozenVuln、FreezeTime、ThornFreeze | freeze |
| SlowPower、SlowTime | slow |
| ProjSpeed | proj_speed |
| ProjLife | duration |
| ReactionDamage、ShengReaction、KeReaction | reaction |
| StunCrit | stun |
| DashCooldown、DashCharges、DashDistance、DashStrike | dash |
| ShieldCooldown、ShieldMult、OverhealShield | shield |
| Healing、LotusHeal | heal |
| Reveal | reveal |
| RevealVuln | reveal_vuln |
| Light | light |
| FlameBand | flame_band |
| UltCharge | ult |
| XpGain、FrozenXp | soul |
| OilGain | oil |
| GoldGain | coin |
| ChestMin、ChestLuck | chest |
可沿用原有的：Regen → regen，ArmorToDamage → armor，SummonMult → count，MovingDamage → speed。其余不写 icon。
