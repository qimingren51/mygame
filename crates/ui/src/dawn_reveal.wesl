// 灯驿长卷的地区晨光（docs/FEEL.md 第 9 节）：按“先亮哪里”的灰度图铺开，像颜色洇进纸里。
// mask 黑的先出现、白的最后；进度 0 → 1。铺开的那一道边颜色深一点，像水墨洇开时边上积的水痕。
import bevy_ui_render::ui_vertex_output::UiVertexOutput;

struct Reveal {
    // x：进度 0..1；y：边的宽度（灰度单位）；z：水痕的深浅；w：整体不透明度
    params: vec4<f32>,
}

@group(1) @binding(0)
var<uniform> reveal: Reveal;
@group(1) @binding(1)
var image: texture_2d<f32>;
@group(1) @binding(2)
var image_sampler: sampler;
@group(1) @binding(3)
var mask: texture_2d<f32>;
@group(1) @binding(4)
var mask_sampler: sampler;

@fragment
fn fragment(in: UiVertexOutput) -> @location(0) vec4<f32> {
    let c = textureSample(image, image_sampler, in.uv);
    let m = textureSample(mask, mask_sampler, in.uv).r;
    let edge = max(reveal.params.y, 0.001);
    // 进度拉到 [-edge, 1 + edge]，0 时全空、1 时全满
    let front = reveal.params.x * (1.0 + 2.0 * edge) - edge;
    let shown = smoothstep(m - edge, m + edge, front);
    // 水痕：正在铺开的那一道边（shown 在 0.5 附近）颜色压深一点
    let rim = 1.0 - abs(shown * 2.0 - 1.0);
    let rgb = c.rgb * (1.0 - reveal.params.z * rim * rim);
    return vec4<f32>(rgb, c.a * shown * reveal.params.w);
}
