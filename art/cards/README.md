# 正式卡面插画

当前 41 张插画覆盖七件法器、七种进化、五种异化、三种合璧、十七门心法和两种补给。
使用内置 `image_gen` 逐张生成，总协调按题材、材质、构图与缩小后的辨识度审查。
完整提示词和帧映射在 [prompts.json](prompts.json)，不是运行时文案。

原始 1448×1086 图保留在工作区 `art/out/cards/source/`，该目录沿用美术中间产物约定不入 Git。
交付素材是 `assets/atlas/cards_0.png`、`cards_1.png` 及同名 JSON；每帧 768×576，4:3 全幅，无裁切、无染色。
游戏通过既有 `ui/card_*` 名称消费，不依赖用户目录中的生成缓存，也不覆盖旧 `ui` 图集。

重新导入完整源图：

```bash
python3 art/post/card_illustrations.py
python3 art/post/check_atlas.py
```

不要把正式插画改回放大的小图标。后续新增卡面须有明确题材、可读的主体和与既有世界一致的材质；替换候选先在原生尺寸与实际卡面尺寸审查。
