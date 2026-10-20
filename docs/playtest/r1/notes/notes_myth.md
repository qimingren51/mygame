# 神话特效分镜进度（myth-art 分支，worktree：scratchpad/wt-myth）

worktree 的 art/out 是指向 /home/user/mygame/art/out 的软链接（产物都在主仓库的 art/out 里）；git add 时只加 art/post/myth_*.py，别加 art/out。

脚本：
- art/post/myth_scene.py：1080p 游戏画面合成（镜头缩放/震屏、旋转贴图、拖尾笔画、光照图钩子、辉光、暗角、分镜条拼版）
- art/post/myth_parts.py：元件 → art/out/assets@2x/myth/（+ meta.json）。`myth_parts.py sword` 只画一组
- art/post/myth_board.py：四格分镜 → art/out/review@2x/myth_<演出>_board.png / _hero.png；`myth_board.py sword:2` 只出一格到 art/out/myth_try/

经验：
- 合成在线性光里混合：墨的 alpha 0.67 看着只有四成黑，要 0.9 以上才压得住；叠加层很淡的尾巴在暗底上也很显眼，发光要收得紧。
- 云在天上，画在暗层之上（不被地上的灯照亮），否则发灰。

## 1. 万剑归宗（sword）— 完成
- 分镜：art/out/review@2x/myth_sword_board.png；原大：myth_sword_hero.png（2.0 秒剑柱劈云）
- 元件：sword_blade_0..2（终稿）、sword_cloud_0..5 + sword_cloud_emit_0..5（终稿）
- 演出期间建议暗层压到七成、灯光池六成（板上用了），否则剑河在暖光里发白

## 下一步
- 2. 北冥潮（kun）：kun_sea_0..5 + emit、kun_shadow、kun_leap_0..5
- 3. 燃灯（ult）：ult_lotus_0..7、ult_rays、ult_halo
- 4. 九尾登场（fox）：fox_moon、fox_body + emit、fox_tail + emit

## 2. 北冥潮（kun）— 完成
- 分镜：art/out/review@2x/myth_kun_board.png；原大：myth_kun_hero.png（1.75 秒鲲跃出水）
- 元件（终稿）：kun_sea_0..5 + kun_sea_emit_0..5、kun_shadow、kun_leap_0..5
- 要点：冰海的水要亮（光照图里加一盏冷光），鲲影才压得出来；鲲影放 2 倍（2.5 倍以上整片海都在影子里，看不出鱼形）
- 背鳍、八字浪痕、冻住的妖物是代码示意

## 3. 燃灯（ult）— 完成
- 分镜：art/out/review@2x/myth_ult_board.png；原大：myth_ult_hero.png（0.95 秒千条佛光）
- 元件（终稿）：ult_lotus_0..7、ult_rays、ult_halo
- 要点：暗层提亮以后叠加光很容易冲白：佛光两张的增益约 0.34 / 0.14，莲灯 0.5，头光 0.4；佛光贴图中心只留一小点白
- 化灰（按噪声烧掉、烧边余烬、灰片上飘）是代码示意

## 4. 九尾登场（fox）— 完成
- 分镜：art/out/review@2x/myth_fox_board.png；原大：myth_fox_hero.png（1.75 秒九尾全开成扇，月前剪影）
- 元件（终稿）：fox_moon（白色可染，建议 #DCE6FF）、fox_body + fox_body_emit（坐姿，挂点 tail_root）、fox_tail + fox_tail_emit
- 身子、尾巴都是距离场捏的（圆滑形体 smin 合起来，再加尖毛），比折线轮廓好看得多
- 要点：月亮叠加 × 1.5 很容易冲白、辉光把剪影晕灰：月亮增益约 0.7、辉光 0.26；剪影要画在月亮之上
- 扇的排法（从右往左一条条旋开，中间长两边短，前后两层明暗错开）、狐火环、墨尘是代码示意

## 全部完成
- 四张分镜条 + 四张原大图在 art/out/review@2x/myth_*；元件 art/out/assets@2x/myth/（49 张 + meta.json，约 12 MB，ult_rays 一张 3 MB）
- 没有打包图集；myth 图集等定了画风再打

## 第二轮修改（用户：“方向可以，修完再看一轮”）——【暂停，WIP】
按用户“先暂停”停在这里。脚本已提交到 myth-art（提交信息标了 WIP）。
art/out/review@2x/ 里的四张分镜条和原大图还是**第一轮**的，第二轮的试渲只在 art/out/myth_try/。

### 已经改好的（元件已重新生成）
- 命名：发光层改成帧号在前、_emit 在后（sword_cloud_0_emit、fox_body_emit），meta 保留 layer_of；myth_parts.build 会删掉这一组旧写法的文件。
  已按新命名重出：sword_blade、sword_giant、sword_cloud、kun_shadow、kun_fin、kun_leap、ult_lotus、fox_body、fox_tail。
- 万剑归宗：新元件 sword_giant（1024×160 大剑影：剑格、如意卷、缠绳柄、剑首、剑穗、剑身符文、剑尖）；
  第四格改成 2.4 秒“归宗”：剑影收回主角手里的符剑、剑身一亮、扣“归宗”二字（马善政体，示意），只剩少量拖尾火星（没有“下雨”了）。已试渲，可以。
- 北冥潮：kun_shadow 加深（身子约 0.97），鳍改成有骨条、膜半透明，新加 kun_shadow_emit（影子边一圈冰光）；
  新元件 kun_fin + kun_fin_emit（露出水面的背鳍：鳍条、半透明膜、前缘湿亮、根上白浪、鳍前浪花）；kun_leap 的鳍改成有骨条、扇贝缺口、半透明。
- 燃灯：ult_lotus 改成本体普通混合（纸色瓣、焦褐细轮廓、中脉）+ ult_lotus_N_emit（描金在墨线里侧、瓣根透光、灯焰）。
- 九尾：fox_body 重捏（大耳、口吻短、颈粗、胸前大毛领、身子圆、前腿收在胸下），尖毛的长短、间距都随机；fox_tail 尾毛不规整了。

### 没做完的（下一步）
1. **先重出 kun_sea**（`myth_parts.py kun_sea`）：它的发光层还是旧名 kun_sea_emit_N，分镜脚本已经按新名读，不重出北冥潮会报错；meta.json 里那几条旧条目也会跟着换掉。
2. 万剑归宗 2.0 秒剑柱：大剑影改成三层、缩到 0.5 倍、剑尖落在云缝里，小剑影挪到剑身外面——最后一次试渲还没看（myth_try/sword_2.png），要确认剑格、剑尖看得出。
3. 北冥潮 1.0 秒：分镜里还没接 kun_shadow_emit、kun_fin；要加大冰海的冷光（sea_light）、画背鳍和更粗的八字浪。
4. 燃灯 0.95 秒：分镜里 lotus_at 还按叠加画——要改成本体在 over 钩子（角色之上、暗层之下）+ 发光层叠加，灯焰处在光照图里加一盏灯，莲灯后面垫一圈暗晕，佛光在莲灯附近压低（先画进临时层再乘径向遮罩）。
5. 九尾 2.3 秒：去掉月亮残影和环上的青光（真身照常色），狐火环半径和尺寸放大 1.5 倍，加一圈落地墨尘冲击波（kill_ink / ink 排一圈 + 一道淡墨环）；新身子在月前的构图要再看一遍。
6. 四个演出都重出分镜条和原大图（`myth_board.py sword kun ult fox`），笔记补“第二轮改了什么”的最终版。
