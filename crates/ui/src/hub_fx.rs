//! 灯驿长卷的动画（docs/FEEL.md 第 9 节）：心灯亮起、地区晨光铺开、平时灯火摇曳。
//! 布局由灯驿界面按美术的 hub.json 生成，这里只播动画。目前先有晨光铺开用的材质
//! （在标题画面上临时试过：着色器能编译，按灰度图从先到后铺开）。

use bevy::asset::embedded_asset;
use bevy::prelude::*;
use bevy::render::render_resource::AsBindGroup;
use bevy::shader::ShaderRef;

/// 地区晨光：按“先亮哪里”的灰度图铺开（`dawn_reveal.wesl`）。
#[derive(AsBindGroup, Asset, TypePath, Debug, Clone)]
pub(crate) struct DawnReveal {
    /// x：进度 0..1；y：边的宽度（灰度单位）；z：水痕的深浅；w：整体不透明度
    #[uniform(0)]
    pub params: Vec4,
    #[texture(1)]
    #[sampler(2)]
    pub image: Handle<Image>,
    #[texture(3)]
    #[sampler(4)]
    pub mask: Handle<Image>,
}

impl DawnReveal {
    // 灯驿长卷接上以后，晨光那一层用它
    #[expect(dead_code)]
    pub(crate) fn new(image: Handle<Image>, mask: Handle<Image>) -> Self {
        DawnReveal { params: Vec4::new(0.0, 0.08, 0.25, 1.0), image, mask }
    }
}

impl UiMaterial for DawnReveal {
    fn fragment_shader() -> ShaderRef {
        "embedded://lantern_ui/dawn_reveal.wesl".into()
    }
}

pub(crate) fn register(app: &mut App) {
    embedded_asset!(app, "dawn_reveal.wesl");
    app.add_plugins(UiMaterialPlugin::<DawnReveal>::default());
}
