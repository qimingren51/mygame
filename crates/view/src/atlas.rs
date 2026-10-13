//! 图集读取（格式见 docs/DESIGN.md 第 15 节）。
//!
//! 启动时同步读 `assets/atlas/index.json` 和各页 JSON，建好帧表、动画序列和素材元数据；
//! PNG 交给 AssetServer 异步加载。帧经过裁边，JSON 里的锚点相对原始帧尺寸，
//! 这里换算成 Bevy 精灵的锚点（相对裁边后的矩形，原点在中心，y 向上）。

use std::collections::HashMap;
use std::path::Path;

use bevy::math::URect;
use bevy::prelude::*;
use bevy::sprite::Anchor;
use serde::Deserialize;

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub struct FrameId(pub u32);

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Blend {
    Normal,
    Add,
}

#[derive(Clone, Debug)]
pub struct Frame {
    page: usize,
    index: usize,
    /// 在整页贴图里的纹理坐标（0–1，左上角为原点）
    pub uv: Rect,
    /// 裁边后的尺寸（世界单位）
    pub size: Vec2,
    pub anchor: Anchor,
    pub blend: Blend,
    /// 纯白贴图，用时乘以颜色
    pub tint: bool,
    /// 缩放为 1 时的有效半径（世界单位）：反应区域、扇形等按它缩放到想要的半径（图集 meta 的 radius_px）
    pub radius: Option<f32>,
    /// 缩放为 1 时的可见宽度、箭头长度（世界单位）：冲锋预警的车道和箭头（meta 的 width_px、head_len_px）
    pub width: Option<f32>,
    pub head_len: Option<f32>,
}

/// 一个素材的一个动作。
#[derive(Clone, Debug, Deserialize)]
pub struct AnimMeta {
    pub frames: u32,
    pub fps: f32,
    pub dirs: Vec<String>,
    /// 走完一整轮动画对应的移动距离（世界单位）
    #[serde(default)]
    pub stride_units: Option<f32>,
    /// 出手动作的前几帧是蓄力（DESIGN 第 15 节“妖物动作”）
    #[serde(default)]
    pub windup_frames: usize,
    /// false：播一遍停在最后一帧；没写时循环
    #[serde(default = "yes", rename = "loop")]
    pub looping: bool,
    /// 播完后从这一帧起循环，直到这一招结束
    #[serde(default)]
    pub loop_from: Option<usize>,
}

fn yes() -> bool {
    true
}

/// 一个素材（角色、道具）的元数据。
#[derive(Clone, Debug, Deserialize)]
pub struct AssetMeta {
    pub anims: HashMap<String, AnimMeta>,
    /// 挂点：名字 → 动作 → 方向 → 逐帧坐标（图集像素，相对锚点，y 向下）
    #[serde(default)]
    pub sockets: HashMap<String, HashMap<String, HashMap<String, Vec<[f32; 2]>>>>,
    #[serde(default)]
    pub floating: bool,
    #[serde(default)]
    pub shadow_radius_px: f32,
    /// 平时循环的动作（有好几个动作的素材才写，DESIGN 第 15 节）
    #[serde(default)]
    pub default_anim: Option<String>,
}

impl AssetMeta {
    /// 平时循环的动作：meta 写了 default_anim 就用它，否则用 move，再没有就取名字排在最前的那个。
    pub fn default_anim(&self) -> Option<(&str, &AnimMeta)> {
        let named = |name: &str| self.anims.get_key_value(name).map(|(k, v)| (k.as_str(), v));
        self.default_anim
            .as_deref()
            .and_then(named)
            .or_else(|| named("move"))
            .or_else(|| self.anims.iter().min_by_key(|(k, _)| k.as_str()).map(|(k, v)| (k.as_str(), v)))
    }
}

struct Page {
    image: Handle<Image>,
    layout: Handle<TextureAtlasLayout>,
}

/// 全部图集。
#[derive(Resource)]
pub struct AtlasDb {
    pages: Vec<Page>,
    frames: Vec<Frame>,
    by_name: HashMap<String, FrameId>,
    anims: HashMap<String, Vec<FrameId>>,
    pub assets: HashMap<String, AssetMeta>,
    /// 图集像素 / 世界单位
    pub px_per_unit: f32,
}

#[derive(Deserialize)]
struct IndexJson {
    pages: HashMap<String, Vec<String>>,
}

#[derive(Deserialize)]
struct Rect4 {
    x: u32,
    y: u32,
    w: u32,
    h: u32,
}

#[derive(Deserialize)]
struct Size2 {
    w: f32,
    h: f32,
}

#[derive(Deserialize)]
struct Xy {
    x: f32,
    y: f32,
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase")]
struct FrameJson {
    frame: Rect4,
    sprite_source_size: Rect4,
    source_size: Size2,
    anchor: Xy,
}

#[derive(Deserialize)]
struct FrameMetaJson {
    blend: String,
    tint: bool,
    #[serde(default)]
    radius_px: Option<f32>,
    #[serde(default)]
    width_px: Option<f32>,
    #[serde(default)]
    head_len_px: Option<f32>,
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase")]
struct LanternMeta {
    px_per_unit: f32,
    #[serde(default)]
    frames: HashMap<String, FrameMetaJson>,
    #[serde(default)]
    assets: HashMap<String, AssetMeta>,
}

#[derive(Deserialize)]
struct MetaJson {
    image: String,
    size: Size2,
    lantern: LanternMeta,
}

#[derive(Deserialize)]
struct PageJson {
    frames: HashMap<String, FrameJson>,
    #[serde(default)]
    animations: HashMap<String, Vec<String>>,
    meta: MetaJson,
}

impl AtlasDb {
    /// 从 `<assets>/atlas/` 读取全部图集。失败时返回人能看懂的错误。
    pub fn load(
        asset_root: &Path,
        assets: &AssetServer,
        layouts: &mut Assets<TextureAtlasLayout>,
    ) -> Result<AtlasDb, String> {
        let dir = asset_root.join("atlas");
        let read = |name: &str| -> Result<String, String> {
            std::fs::read_to_string(dir.join(name)).map_err(|e| format!("读取 atlas/{name} 失败：{e}"))
        };
        let index: IndexJson = serde_json::from_str(&read("index.json")?)
            .map_err(|e| format!("atlas/index.json 格式错误：{e}"))?;
        let mut db = AtlasDb {
            pages: Vec::new(),
            frames: Vec::new(),
            by_name: HashMap::new(),
            anims: HashMap::new(),
            assets: HashMap::new(),
            px_per_unit: 0.0,
        };
        let mut animations: Vec<(String, Vec<String>)> = Vec::new();
        // 按名字排序，帧编号与加载顺序无关
        let mut files: Vec<&String> = index.pages.values().flatten().collect();
        files.sort();
        for file in files {
            let page: PageJson =
                serde_json::from_str(&read(file)?).map_err(|e| format!("atlas/{file} 格式错误：{e}"))?;
            let ppu = page.meta.lantern.px_per_unit;
            if db.px_per_unit == 0.0 {
                db.px_per_unit = ppu;
            } else if (db.px_per_unit - ppu).abs() > 1e-3 {
                return Err(format!("atlas/{file} 的出图密度 {ppu} 与其他图集 {} 不一致", db.px_per_unit));
            }
            let mut layout =
                TextureAtlasLayout::new_empty(UVec2::new(page.meta.size.w as u32, page.meta.size.h as u32));
            let page_idx = db.pages.len();
            let mut names: Vec<&String> = page.frames.keys().collect();
            names.sort();
            for name in names {
                let f = &page.frames[name];
                let r = &f.frame;
                let index = layout.add_texture(URect::new(r.x, r.y, r.x + r.w, r.y + r.h));
                // 锚点：先算出在原始帧里的像素位置，再换算到裁边后的矩形
                let s = &f.sprite_source_size;
                let ax = f.anchor.x * f.source_size.w - s.x as f32;
                let ay = f.anchor.y * f.source_size.h - s.y as f32;
                let anchor = Anchor(Vec2::new(ax / r.w as f32 - 0.5, 0.5 - ay / r.h as f32));
                let meta = page.meta.lantern.frames.get(name);
                let (pw, ph) = (page.meta.size.w, page.meta.size.h);
                let frame = Frame {
                    page: page_idx,
                    index,
                    uv: Rect::new(
                        r.x as f32 / pw,
                        r.y as f32 / ph,
                        (r.x + r.w) as f32 / pw,
                        (r.y + r.h) as f32 / ph,
                    ),
                    size: Vec2::new(r.w as f32, r.h as f32) / ppu,
                    anchor,
                    blend: if meta.is_some_and(|m| m.blend == "add") { Blend::Add } else { Blend::Normal },
                    tint: meta.is_some_and(|m| m.tint),
                    radius: meta.and_then(|m| m.radius_px).map(|r| r / ppu),
                    width: meta.and_then(|m| m.width_px).map(|w| w / ppu),
                    head_len: meta.and_then(|m| m.head_len_px).map(|h| h / ppu),
                };
                db.by_name.insert(name.clone(), FrameId(db.frames.len() as u32));
                db.frames.push(frame);
            }
            animations.extend(page.animations);
            db.assets.extend(page.meta.lantern.assets);
            db.pages.push(Page {
                image: assets.load(format!("atlas/{}", page.meta.image)),
                layout: layouts.add(layout),
            });
        }
        // 动画可能引用其他页的帧，所有页都读完再解析
        for (name, frames) in animations {
            let ids = frames
                .iter()
                .map(|f| {
                    db.by_name.get(f).copied().ok_or_else(|| format!("动画 {name} 引用了不存在的帧 {f}"))
                })
                .collect::<Result<Vec<_>, _>>()?;
            db.anims.insert(name, ids);
        }
        if db.frames.is_empty() {
            return Err("atlas/index.json 里没有任何图集".into());
        }
        Ok(db)
    }

    /// 加一页程序生成的贴图（粒子用的软点、烟、灰……）。帧的锚点在中心，白色可染色，
    /// 世界尺寸照样是像素 ÷ `px_per_unit`。
    pub fn add_page(
        &mut self,
        image: Handle<Image>,
        size: UVec2,
        frames: &[(&str, URect)],
        layouts: &mut Assets<TextureAtlasLayout>,
    ) {
        let mut layout = TextureAtlasLayout::new_empty(size);
        let page = self.pages.len();
        let s = size.as_vec2();
        for &(name, r) in frames {
            let index = layout.add_texture(r);
            self.by_name.insert(name.to_string(), FrameId(self.frames.len() as u32));
            self.frames.push(Frame {
                page,
                index,
                uv: Rect::new(
                    r.min.x as f32 / s.x,
                    r.min.y as f32 / s.y,
                    r.max.x as f32 / s.x,
                    r.max.y as f32 / s.y,
                ),
                size: r.size().as_vec2() / self.px_per_unit,
                anchor: Anchor::CENTER,
                blend: Blend::Normal,
                tint: true,
                radius: None,
                width: None,
                head_len: None,
            });
        }
        self.pages.push(Page { image, layout: layouts.add(layout) });
    }

    pub fn frame(&self, id: FrameId) -> &Frame {
        &self.frames[id.0 as usize]
    }

    /// 这一帧所在的整页贴图。
    pub fn image(&self, id: FrameId) -> Handle<Image> {
        self.pages[self.frame(id).page].image.clone()
    }

    /// 这一帧所在的页（同一页的帧可以共用材质）。
    pub fn page_of(&self, id: FrameId) -> usize {
        self.frame(id).page
    }

    pub fn find(&self, name: &str) -> Option<FrameId> {
        self.by_name.get(name).copied()
    }

    /// 动画序列，例如 `hero/walk_SE`。
    pub fn anim(&self, name: &str) -> Option<&[FrameId]> {
        self.anims.get(name).map(Vec::as_slice)
    }

    /// 做一个显示这一帧的精灵。
    pub fn sprite(&self, id: FrameId) -> (Sprite, Anchor) {
        let f = self.frame(id);
        let page = &self.pages[f.page];
        let sprite = Sprite {
            image: page.image.clone(),
            texture_atlas: Some(TextureAtlas { layout: page.layout.clone(), index: f.index }),
            custom_size: Some(f.size),
            ..default()
        };
        (sprite, f.anchor)
    }

    /// 把已有精灵换成这一帧（同一页时只改下标，不克隆句柄）。
    /// 界面用的图片节点（图标）。
    pub fn ui_image(&self, id: FrameId) -> ImageNode {
        let f = self.frame(id);
        let page = &self.pages[f.page];
        ImageNode::from_atlas_image(
            page.image.clone(),
            TextureAtlas { layout: page.layout.clone(), index: f.index },
        )
    }

    pub fn set(&self, id: FrameId, sprite: &mut Sprite, anchor: &mut Anchor) {
        let f = self.frame(id);
        let page = &self.pages[f.page];
        match &mut sprite.texture_atlas {
            Some(ta) if ta.layout == page.layout => ta.index = f.index,
            _ => {
                sprite.image = page.image.clone();
                sprite.texture_atlas = Some(TextureAtlas { layout: page.layout.clone(), index: f.index });
            }
        }
        sprite.custom_size = Some(f.size);
        *anchor = f.anchor;
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn meta(json: &str) -> AssetMeta {
        serde_json::from_str(json).unwrap()
    }

    /// 平时的动作：写了 default_anim 用它，没写用 move，再没有取名字最前的。
    #[test]
    fn default_anim_prefers_meta_then_move() {
        let anim = r#"{"frames": 4, "fps": 8, "dirs": ["E"]}"#;
        let ghoul = meta(&format!(r#"{{"anims": {{"charge": {anim}, "move": {anim}}}}}"#));
        assert_eq!(ghoul.default_anim().unwrap().0, "move", "不能拿冲锋当走路");
        let wraith = meta(&format!(
            r#"{{"anims": {{"idle": {anim}, "move": {anim}, "shoot": {anim}}}, "default_anim": "move"}}"#
        ));
        assert_eq!(wraith.default_anim().unwrap().0, "move");
        let wisp =
            meta(&format!(r#"{{"anims": {{"float": {anim}, "pounce": {anim}}}, "default_anim": "float"}}"#));
        assert_eq!(wisp.default_anim().unwrap().0, "float");
        let single = meta(&format!(r#"{{"anims": {{"walk": {anim}}}}}"#));
        assert_eq!(single.default_anim().unwrap().0, "walk");
    }
}
