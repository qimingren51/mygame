# 检视模型样张（sword、wind_wheel）进度笔记

## 约定（协调者 + 架构定的规格）
- 输出 assets/models/inspect/<id>.glb；+Y 上、正面 +Z、原点几何中心、包围球半径 1。
- 主体 ≤ 5 万三角形（按实例展开算；描边另算）；贴图 ≤ 2048²；每件 ≤ 2 MB，39 件 ≤ 60 MB；PNG 内嵌，不用 Draco/meshopt。
- 发光：emissive 贴图 + 系数，>1 用 KHR_materials_emissive_strength（导出器自动写，已验证）。
- 描边：反向外壳，法线朝里，节点名、材质名以 `_outline` 结尾（引擎换成不受光纯黑，正常背面剔除）。
- 透明火焰：alphaMode BLEND（里层火不透明，外层 BLEND）。
- 动画：一条 `idle` 循环，首尾同帧（导出后把每个物体一条的动画合并成一条 idle）。
- 规格写进 DESIGN 第 15 节“检视模型”和 art/README.md。

## 环境
- worktree：/tmp/claude-0/-home-user-mygame/01f265ce-5196-560e-be75-2f924c080bfe/scratchpad/wt-inspect（分支 inspect-art，基于 origin/master d547294）
- 解释器：/home/user/mygame/art/.venv/bin/python，在 worktree 根目录运行。
- worktree 的 art/out/.render.lock、art/out/fonts 是软链到主仓库（锁共用；完整字体给贴图用）。

## 文件
- art/inspect/kit.py：PMat（单 Principled 材质）、周期坐标、零件登记、slab_strip（纸/绸）、join_objects、UV（Smart UV + 按面积统一密度 + 长岛切段 + 管子专用 UV）
- art/inspect/models.py：build_sword、build_wind_wheel（+ 贴图图案、材质、形变键）；REVIEW 特写镜头
- art/inspect/export.py：烘焙（各通道接自发光烘到浮点图，覆盖率自己光栅化）、numpy 后期、换材质、归一化、描边、动画、导出、改写 glb
- art/inspect/review.py：重新导入 glb 渲审图（--sample 小样；sheet / turn / idle）
- art/post/check_models.py + test_check_models.py（19 项，全过）

## 踩过的坑（别再踩）
- Smart UV 的 correct_aspect=True 会按材质里激活的图像节点的宽高比压扁 UV → 一律 False。
- join 目标的空网格会留一个空材质槽，Cycles 烘焙整物体失败 → join 后删空槽。
- 烘焙图的 alpha 不可靠（有时全 1）→ 覆盖率按 BakeUV 三角形自己光栅化。
- 岛缩放要先挪到各自的格子，否则 merge_overlap 会把意外重叠的岛并成一个。
- 体积主要卡在顶点数：六棱管用 Smart UV 会一面一个岛 → 管子用 tube_bake_uv；不带切线（Bevy 用 mikktspace 自己算）。

- UV 操作会按材质里图像贴图的宽高比压扁岛（不只是 correct_aspect）→ 展 UV 时 kit.plain_materials 临时换材质。
- 烘焙图边缘有黑缝 → Cycles margin=3 EXTEND + 覆盖率用 PIL 只填不描边。
- 分几次展的 UV 岛要放进全局 _SLOT，不然 merge_overlap 会把它们并在一起。

## 协调者第二轮要求（用户嫌占位剑粗糙）
- 刃口倒角、刃口亮线 vs 刃面锻纹；符纸纤维、朱砂浓淡、毛边略卷；木柄木纹 + 节疤、缠绳分明；剑格剑首雕纹；
  宝石 / 火焰有辉光、宝石内部折射感；风火轮铸纹、辐条、火（内核亮、外焰半透明）、飘带布纹；审图加特写（刃口、符纸、轮圈）。
- 已做：木柄露两头（mat_wood：顺纹 + 两个节疤），缠绳只缠中段；剑格两面嵌红玛瑙（mat_gem）；符纸积墨、浓淡、纤维、边卷；
  轮毂火珠 + 金托；红绸平纹；火舌芯线 + 流纹 + 外层半透明；REVIEW 四处特写 + detail 动图。
- 审图路径和哈希报给协调者，不直接发架构（架构检视器在 inspect-proto 97724c0）。

## 进度（用户说“先暂停”，2026-10-20 停在这里；WIP 提交 5ec588e 已推到 origin/inspect-art）
- [x] 管线：art/inspect/{kit,models,export,review}.py，art/post/check_models.py + test_check_models.py（19 项全过）
- [x] 文档：docs/DESIGN.md 第 15 节“检视模型”、art/README.md“检视模型（inspect/）”（风火轮标了 WIP）
- [x] 符剑正式版 assets/models/inspect/sword.glb：1.93 MB，主体 16918、描边 6569，2K 烘、底色/法线 1K、MR/自发光 512，自检通过（已提交）
- [!] 风火轮最新一版 2.55 MB，超 2 MB（UV 不再被压扁后贴图细节多了：底色 707 KB、法线 491 KB）。glb 没提交，
      挪到了 worktree 的 art/out/_inspect_tmp/final/wind_wheel_wip_2.55MB.glb（不进 git）。
- [ ] 正式审图一张都没出（暂停时不许开新渲染）。只有试渲小样：art/out/_inspect_tmp/sample_{sword,wind_wheel}.png（是草稿贴图，不能给用户看）。

## 下一步（恢复以后照这个顺序）
1. 风火轮压到 2 MB 以内（任选、先试最省的）：
   - 法线降到 512（底色留 1K），或者轮子贴图去噪 soften 0.35→0.6；
   - 少一点顶点：轮毂截面点（_hub_profile）再减、莲瓣 ns/nt 再小，或火的 main 层 sides 6→5；
   - 火的贴图 512 → 256（之前 256 时 72 KB，512 是 205 KB）。
   改完 `export.py wind_wheel --draft` 看草稿体积（草稿和正式差不多：几何一样，贴图正式大约多 0.4–0.8 MB），再出正式版。
2. 两件都过 `check_models.py --expect sword,wind_wheel` 以后，出正式审图（约半小时）：
   `art/.venv/bin/python art/inspect/review.py sword wind_wheel` → art/out/review@2x/inspect_<id>_{sheet.png,turn.gif,detail.gif,idle.gif}
   （拼图 4×3：正背侧俯仰、四分之三、四处特写：刃口与锻纹、符纸、剑格与宝石、木柄缠绳剑穗 / 轮圈铸纹、火舌、莲花轮毂与火珠、飘带布纹）。
   先 `--sample` 看一眼特写取景（REVIEW 里的点是估的，可能要挪）。
3. 待查：符纸特写里有一条灰色的细条穿过纸面（草稿里看到的，可能是剑身透过来或描边外壳），正式审图时确认。
4. 审图路径和分支哈希报给协调者（不要直接发架构；架构的检视器在 inspect-proto 97724c0）。
