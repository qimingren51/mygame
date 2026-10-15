import bevy_ui_render::ui_vertex_output::UiVertexOutput;

@group(1) @binding(0) var<uniform> ink: vec4<f32>;

fn hash(p: vec2<f32>) -> f32 {
    return fract(sin(dot(p, vec2<f32>(127.1, 311.7))) * 43758.5453);
}

fn noise(p: vec2<f32>) -> f32 {
    let i = floor(p);
    let f = fract(p);
    let u = f * f * (3.0 - 2.0 * f);
    return mix(mix(hash(i), hash(i + vec2<f32>(1.0, 0.0)), u.x),
        mix(hash(i + vec2<f32>(0.0, 1.0)), hash(i + vec2<f32>(1.0)), u.x), u.y);
}

@fragment
fn fragment(in: UiVertexOutput) -> @location(0) vec4<f32> {
    // 标题期间预热管线，空闲帧不计算全屏噪声。
    if ink.x <= 0.0 { return vec4<f32>(0.0); }
    // 以长边为尺度，超宽屏也能完整遮住四角；晕染边缘随纸纤维起伏。
    let p = (in.uv - 0.5) * in.size / max(in.size.x, in.size.y);
    let wash = noise(p * 9.0) * 0.65 + noise(p * 27.0) * 0.25 + noise(p * 81.0) * 0.10;
    let field = length(p + vec2<f32>(0.09, -0.03)) * 1.45 + wash * 0.30;
    let t = clamp(ink.x, 0.0, 1.0);
    let front = mix(-0.15, 1.6, t * t * (3.0 - 2.0 * t));
    let wet = 1.0 - smoothstep(front - 0.015, front + 0.09, field);
    let dense = 1.0 - smoothstep(front - 0.10, front, field);
    var alpha = mix(wet * 0.48, 1.0, dense);
    if t <= 0.0 { alpha = 0.0; }
    if t >= 1.0 { alpha = 1.0; }
    // 夜色墨底与纸面颗粒；满屏等待时留一点如标题魂火般的呼吸暖光。
    let grain = hash(floor(in.uv * in.size));
    let pigment = vec3<f32>(0.008, 0.011, 0.016) + wash * 0.009 + grain * 0.002;
    let glow = exp(-dot(p * vec2<f32>(95.0, 48.0), p * vec2<f32>(95.0, 48.0)))
        * (0.045 + 0.015 * sin(ink.y * 2.4)) * smoothstep(0.88, 1.0, t);
    return vec4<f32>(pigment + glow * vec3<f32>(1.0, 0.64, 0.25), alpha);
}
