import bevy_sprite_render::mesh2d::vertex_output::VertexOutput;

struct OutlineMaterial {
    color: vec4<f32>,
    uv_rect: vec4<f32>,
    step_fill: vec4<f32>,
};

@group(constants::MATERIAL_BIND_GROUP) @binding(0) var<uniform> material: OutlineMaterial;
@group(constants::MATERIAL_BIND_GROUP) @binding(1) var atlas: texture_2d<f32>;
@group(constants::MATERIAL_BIND_GROUP) @binding(2) var atlas_sampler: sampler;

fn alpha_at(uv: vec2<f32>) -> f32 {
    let inside = all(uv >= material.uv_rect.xy) && all(uv <= material.uv_rect.zw);
    let half_texel = 0.5 / vec2<f32>(textureDimensions(atlas));
    let safe_uv = clamp(uv, material.uv_rect.xy + half_texel, material.uv_rect.zw - half_texel);
    return select(0.0, textureSampleLevel(atlas, atlas_sampler, safe_uv, 0.0).a, inside);
}

@fragment
fn fragment(in: VertexOutput) -> @location(0) vec4<f32> {
    let step = material.step_fill.xy;
    let uv = mix(material.uv_rect.xy - step, material.uv_rect.zw + step, in.uv);
    let center = alpha_at(uv);
    var expanded = center;
    for (var y = -1; y <= 1; y += 1) {
        for (var x = -1; x <= 1; x += 1) {
            expanded = max(expanded, alpha_at(uv + vec2<f32>(f32(x), f32(y)) * step));
        }
    }
    let alpha = max(expanded - center, center * material.step_fill.z);
    return vec4<f32>(material.color.rgb, material.color.a * alpha);
}
