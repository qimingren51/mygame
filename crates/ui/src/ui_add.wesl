// 界面上的叠加层（灯驿长卷的灯芯、光晕、晨光的光、人物聚光）：画面 += 贴图 RGB × alpha × 颜色。
// 混合方式在 hub_scene.rs 的 UiAdd::specialize 里改成叠加。
import bevy_ui_render::ui_vertex_output::UiVertexOutput;

struct Tint {
    color: vec4<f32>,
}

@group(1) @binding(0)
var<uniform> tint: Tint;
@group(1) @binding(1)
var image: texture_2d<f32>;
@group(1) @binding(2)
var image_sampler: sampler;

@fragment
fn fragment(in: UiVertexOutput) -> @location(0) vec4<f32> {
    let c = textureSample(image, image_sampler, in.uv);
    return vec4<f32>(c.rgb * tint.color.rgb, c.a * tint.color.a);
}
