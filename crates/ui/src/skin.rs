//! 界面九宫格皮肤（美术管线 art/post/ui_skin.py 生成，规格在 assets/atlas/skin/skin.json）。
//!
//! 每张皮肤图是 2 倍尺寸；切片宽度按原图像素写，显示时角和边缩到一半（`max_corner_scale = 1 / scale`）。

use bevy::prelude::*;
use bevy::sprite::{BorderRect, SliceScaleMode, TextureSlicer};
use bevy::ui::VisualBox;
use bevy::ui::widget::NodeImageMode;

use lantern_view::AssetRoot;

struct Item {
    name: String,
    image: Handle<Image>,
    /// 左、上、右、下（原图像素）
    slice: [f32; 4],
    tile: bool,
}

#[derive(Resource)]
pub(crate) struct Skin {
    scale: f32,
    items: Vec<Item>,
    /// 标题画面与 logo
    pub title: Handle<Image>,
    pub logo: Handle<Image>,
}

pub(crate) fn load_skin(mut commands: Commands, assets: Res<AssetServer>, root: Res<AssetRoot>) {
    let path = root.0.join("atlas/skin/skin.json");
    let json: serde_json::Value = match std::fs::read_to_string(&path).map(|t| serde_json::from_str(&t)) {
        Ok(Ok(v)) => v,
        other => {
            warn!("界面皮肤读取失败（{}）：{other:?}，界面改用纯色", path.display());
            serde_json::Value::Null
        }
    };
    let scale = json["scale"].as_f64().unwrap_or(2.0) as f32;
    let mut items = Vec::new();
    if let Some(map) = json["items"].as_object() {
        for (name, v) in map {
            let file = v["file"].as_str().unwrap_or_default();
            let s: Vec<f32> = v["slice"]
                .as_array()
                .map(|a| a.iter().map(|x| x.as_f64().unwrap_or(0.0) as f32).collect())
                .unwrap_or_default();
            let slice = [0, 1, 2, 3].map(|i| s.get(i).copied().unwrap_or(0.0));
            items.push(Item {
                name: name.clone(),
                image: assets.load(format!("atlas/skin/{file}")),
                slice,
                tile: v["center"].as_str() == Some("tile"),
            });
        }
    }
    commands.insert_resource(Skin {
        scale,
        items,
        title: assets.load("atlas/screens/title.png"),
        logo: assets.load("atlas/screens/logo.png"),
    });
}

impl Skin {
    fn item(&self, name: &str) -> Option<&Item> {
        self.items.iter().find(|i| i.name == name)
    }

    /// 皮肤图片节点：有切片的按九宫格，没有的整张拉伸。皮肤缺失时返回透明图。
    pub fn image(&self, name: &str) -> ImageNode {
        let Some(it) = self.item(name) else { return ImageNode::default().with_color(Color::NONE) };
        let [l, t, r, b] = it.slice;
        let mode = if l + t + r + b > 0.0 {
            let tile =
                if it.tile { SliceScaleMode::Tile { stretch_value: 1.0 } } else { SliceScaleMode::Stretch };
            NodeImageMode::Sliced(TextureSlicer {
                border: BorderRect { min_inset: Vec2::new(l, t), max_inset: Vec2::new(r, b) },
                center_scale_mode: tile,
                sides_scale_mode: tile,
                max_corner_scale: 1.0 / self.scale,
            })
        } else {
            NodeImageMode::Stretch
        };
        // 皮肤画满整个节点（含内边距），内边距只影响里面的文字
        ImageNode { visual_box: VisualBox::BorderBox, ..ImageNode::new(it.image.clone()).with_mode(mode) }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use bevy::asset::io::AssetSourceId;
    use std::fs;
    use std::path::Path;
    use std::time::{SystemTime, UNIX_EPOCH};

    #[test]
    fn skin_and_asset_server_read_the_supplied_root() {
        let stamp = SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_nanos();
        let dir = std::env::temp_dir().join(format!("提灯 皮肤-{}-{stamp}", std::process::id()));
        fs::create_dir_all(dir.join("atlas/skin")).unwrap();
        let root = dir.canonicalize().unwrap();
        let json = r#"{"scale":7,"items":{}}"#;
        fs::write(root.join("atlas/skin/skin.json"), json).unwrap();

        let mut app = App::new();
        app.add_plugins((
            MinimalPlugins,
            AssetPlugin { file_path: root.to_str().unwrap().to_owned(), ..default() },
        ))
        .init_asset::<Image>()
        .insert_resource(AssetRoot(root))
        .add_systems(Startup, load_skin);
        app.update();
        // 皮肤 JSON 必须使用传入的根目录，不能重新查找仓库里的那一份。
        assert_eq!(app.world().resource::<Skin>().scale, 7.0);
        let server = app.world().resource::<AssetServer>();
        let source = server.get_source(AssetSourceId::Default).unwrap();
        let bytes = bevy::tasks::block_on(async {
            let mut reader = source.reader().read(Path::new("atlas/skin/skin.json")).await.unwrap();
            let mut bytes = Vec::new();
            reader.read_to_end(&mut bytes).await.unwrap();
            bytes
        });
        assert_eq!(bytes, json.as_bytes());
        drop(app);
        fs::remove_dir_all(dir).unwrap();
    }
}
