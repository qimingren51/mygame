# 主角头像重画（portrait-art 分支）进度

**状态：用户叫暂停，已停。** WIP 提交 7d4e6f5 已推到 origin/portrait-art（没动 master，也没动图集）。

worktree：scratchpad/wt-portrait（art/out、art/.venv 软链到主仓库，不要 git add 这两个）
脚本：art/render/portrait_v2.py（新开的，没改 portrait.py）

## 停在哪
- 三个方向的 dev 版（1024²、40 采样）刚渲完并做了后期：
  - 样张：art/out/_tmp_portrait_v2/samples/portrait_hero_{cold,gentle,hat}_dev.png（512²）
  - dev 审图：art/out/_tmp_portrait_v2/review/portrait_samples.png、portrait_samples_hud.png
- **正式渲染（160 采样）和正式审图还没出**，art/out/review@2x/portrait_samples*.png 还不存在。
- 最后这一轮改动（帽檐下的影加重、温和版低头 7°、发际线改圆、相机 cam_elev 符号修正）跑过 dev，结果还没看。

## 下一步
1. 看这一版 dev 的三张图（_tmp_portrait_v2/samples/），重点看：
   - 帽檐下的影够不够（brim_shadow）；温和版的脸是不是还显长；
   - 发壳还像不像头盔（发际线羽化 + 发根细笔）；
   - 冷峻版的相机改成从下往上 2.5° 以后的构图。
2. 还没解决的问题：
   - 脸还偏“三维渲染”，皮肤平、缺点生气：可以加两颊胭脂、皮肤上一层绢纹 / 笔触；
   - 眉是一条墨块，缺丝毛的感觉；嘴偏淡；
   - 鬓发是两根直线，有点僵；马尾露得少；
   - 银冠还偏亮，太像金属件。
3. 满意以后跑正式版：`art/.venv/bin/python art/render/portrait_v2.py`（三个方向依次渲，每个约 3–4 分钟，拿渲染锁），
   出 art/out/review@2x/portrait_samples.png 和 portrait_samples_hud.png。
4. 回报：两张审图路径、三个方向的优缺点各一句、推荐、提交哈希。去掉提交信息里的 WIP（新提交）。

## 已知
- 游戏里：头像章 104（逻辑像素），胸像画 92×92，漆环窗口直径 78 → 胸像图里能看见的圆 = 78/92 = 84.8%（512 母版里直径约 434）。
- 主角：白内袍交领、墨氅、黑发高马尾（银冠 + 石绿玉珠）、朱砂发带两条长尾、两缕鬓发、右手提灯（红纸灯）。
- 渲染只用 Cycles CPU，拿 B.render_lock()。
- cam_elev：正 = 相机在下面往上看（之前写反过一次，已改）。
- 用法：`portrait_v2.py <方向> --draft`（384² 试渲）、`--dev`（1024² 40 采样）、`--post`（只重做后期，读缓存）。

## 方案（已实现）
三维出底 + 二维后期：
- Blender：放样头型 + 隐式曲面五官（下半脸按 LOWER_K 压短）、眼球 + 杏仁形眼睑开口；皮肤顶点色 + 次表面；
  发壳（发际线收薄）、发髻、马尾 / 鬓发管子、发带、银冠；身子（白袍 + 墨氅）；斗笠（头发按帽子内面裁掉）。
  灯笼按画面位置摆（lantern_px），灯光、月光、补光分三个光组，后期分别调（GRADE）。
- 后期：按部件重新染色（反照率 × 柔化后的逐通道受光）、夜色水墨底、发丝高光 + 发际线羽化 + 发根细笔、
  墨线（部件分界 / 剪影 / 深度跳变，脸上阈值放宽）、五官用笔（眼线、双眼皮、下眼睑、虹膜分层 + 两点高光、眉、鼻翼、嘴）、
  鬓发、马尾墨笔飞白，二维画的交领，斗笠竹篾，帽檐下的影，灯笼光晕，宣纸纹。
- 提速：sdf_grid 只在曲面附近精算（皮肤网格从 130 秒降到 20 秒）；网格投影每步最多挪半格，不再破洞。
