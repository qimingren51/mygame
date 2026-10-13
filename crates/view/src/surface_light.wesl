// 原图乘以受光量后小幅叠加：墨线仍是墨线，不往透明区扩光，也不进入辉光层。
import bevy_sprite_render::mesh2d::vertex_output::VertexOutput;

struct Surface {
    uv_rect: vec4<f32>,
    tint: vec4<f32>,
    lights: array<vec4<f32>, 3>,
    colors: array<vec4<f32>, 3>,
    shape: vec4<f32>,
}
@group(constants::MATERIAL_BIND_GROUP) @binding(0) var<uniform> surface: Surface;
@group(constants::MATERIAL_BIND_GROUP) @binding(1) var image: texture_2d<f32>;
@group(constants::MATERIAL_BIND_GROUP) @binding(2) var image_sampler: sampler;

fn alpha_at(uv: vec2<f32>, texel: vec2<f32>) -> f32 {
    // 图集边界内采样，不能把邻帧的 alpha 当作轮廓。
    return textureSample(image, image_sampler, clamp(uv, surface.uv_rect.xy + texel * 0.5, surface.uv_rect.zw - texel * 0.5)).a;
}

@fragment
fn fragment(in: VertexOutput) -> @location(0) vec4<f32> {
    let texel = 1.0 / vec2<f32>(textureDimensions(image));
    let base = textureSample(image, image_sampler, in.uv);
    let q = (in.uv - surface.uv_rect.xy) / (surface.uv_rect.zw - surface.uv_rect.xy) * 2.0 - 1.0;
    let dx = alpha_at(in.uv + vec2(texel.x, 0.0), texel) - alpha_at(in.uv - vec2(texel.x, 0.0), texel);
    let dy = alpha_at(in.uv + vec2(0.0, texel.y), texel) - alpha_at(in.uv - vec2(0.0, texel.y), texel);
    let curve = vec2(q.x * surface.shape.x, -q.y) * 0.72;
    let edge = vec2(-dx * surface.shape.x, dy);
    let n = normalize(vec3(curve + edge * 1.3, sqrt(max(0.15, 1.0 - dot(curve, curve)))));
    var radiance = vec3(0.0);
    for (var i = 0u; i < 3u; i += 1u) {
        let light = surface.lights[i];
        let delta = light.xy - in.world_position.xy;
        let attenuation = max(0.0, 1.0 - dot(delta, delta) / max(1.0, light.z * light.z));
        let direction = normalize(vec3(delta, 18.0));
        let diffuse = max(0.0, dot(n, direction));
        let rim = pow(1.0 - n.z, 2.0) * diffuse;
        radiance += surface.colors[i].rgb * light.w * attenuation * attenuation * (0.32 * diffuse + 0.12 * rim);
    }
    return vec4(base.rgb * surface.tint.rgb * min(radiance, vec3(0.48)), base.a * surface.tint.a);
}
