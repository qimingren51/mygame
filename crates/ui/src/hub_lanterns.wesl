// 长卷上的墨树、灯身与火。位置来自存档的稳定灯火槽，不消耗模拟随机流。
import bevy_ui_render::ui_vertex_output::UiVertexOutput;

struct Scroll {
    // x：演出时间；y：常亮摇曳时间；z：灯数；w：积累带来的火光强度
    params: vec4<f32>,
    // xy：卷内位置；z：已点亮；w：新灯的延迟，负数表示旧灯
    lights: array<vec4<f32>, 64>,
}
@group(1) @binding(0) var<uniform> scroll: Scroll;

fn stroke(p: vec2<f32>, a: vec2<f32>, b: vec2<f32>, width: f32) -> f32 {
    let d = b - a;
    let h = clamp(dot(p - a, d) / dot(d, d), 0.0, 1.0);
    // 笔势微弯、收锋，边缘带纸纤维的断续，避免枝干像几何连线。
    let bend = vec2<f32>(-d.y, d.x) * sin(h * 3.14159) * 0.07;
    let taper = width * (1.0 - h * 0.38);
    let grain = sin(p.x * 3900.0 + p.y * 1100.0) * sin(p.y * 2800.0) * 0.00045;
    return 1.0 - smoothstep(taper, taper + 0.0018, length(p - a - d * h - bend) + grain);
}

@fragment
fn fragment(in: UiVertexOutput) -> @location(0) vec4<f32> {
    let uv = in.uv;
    // 两棵墨树，主干有折势；枝梢渐细，给远山和归途留白。
    var ink = 0.0;
    for (var tree = 0u; tree < 2u; tree += 1u) {
        let x = 0.19 + f32(tree) * 0.30;
        ink = max(ink, stroke(uv, vec2<f32>(x - 0.035, 0.91), vec2<f32>(x - 0.016, 0.71), 0.006));
        ink = max(ink, stroke(uv, vec2<f32>(x - 0.016, 0.71), vec2<f32>(x + 0.008, 0.50), 0.004));
        ink = max(ink, stroke(uv, vec2<f32>(x + 0.008, 0.50), vec2<f32>(x - 0.010, 0.29), 0.003));
        ink = max(ink, stroke(uv, vec2<f32>(x - 0.010, 0.29), vec2<f32>(x + 0.017, 0.13), 0.0015));
        for (var branch = 0u; branch < 3u; branch += 1u) {
            let y = 0.22 + f32(branch) * 0.20;
            let bend = sin(f32(branch + tree) * 2.4) * 0.016;
            ink = max(ink, stroke(uv, vec2<f32>(x, y + 0.13), vec2<f32>(x - 0.06, y + 0.045), 0.0028));
            ink = max(ink, stroke(uv, vec2<f32>(x - 0.06, y + 0.045), vec2<f32>(x - 0.13, y + bend), 0.0014));
            ink = max(ink, stroke(uv, vec2<f32>(x - 0.06, y + 0.045), vec2<f32>(x - 0.085, y - 0.04), 0.0008));
            ink = max(ink, stroke(uv, vec2<f32>(x, y + 0.10), vec2<f32>(x + 0.052, y + 0.016), 0.0023));
            ink = max(ink, stroke(uv, vec2<f32>(x + 0.052, y + 0.016), vec2<f32>(x + 0.12, y - 0.025 + bend), 0.0012));
            ink = max(ink, stroke(uv, vec2<f32>(x + 0.052, y + 0.016), vec2<f32>(x + 0.075, y - 0.05), 0.0008));
        }
    }
    var rgb = vec3<f32>(0.038, 0.046, 0.044) * ink;
    var alpha = ink * 0.92;
    for (var i = 0u; i < 64u; i += 1u) {
        if (f32(i) >= scroll.params.z) { break; }
        let lamp = scroll.lights[i];
        // 横向画布为 3.4:1，距离换成等比例，光晕才是圆的。
        var p = (uv - lamp.xy) * vec2<f32>(3.4, 1.0);
        // 光晕之外直接略过昂贵的指数计算。
        if (abs(p.x) > 0.23 || abs(p.y) > 0.23) { continue; }
        let age = select(scroll.params.x - lamp.w, 10.0, lamp.w < 0.0);
        let ignite = smoothstep(0.0, 0.25, age) * lamp.z;
        let breath = 0.94 + 0.06 * sin(scroll.params.y * 2.1 + f32(i) * 2.39);
        let spread = smoothstep(0.15, 0.95, age);
        let swell = 1.0 + 0.15 * sin(clamp(age / 0.8, 0.0, 1.0) * 3.14159);
        let radius = (0.026 + 0.049 * spread) * swell;
        let halo = exp(-dot(p, p) / (radius * radius)) * 0.30 * ignite * breath * scroll.params.w;
        let body = 1.0 - smoothstep(0.91, 1.07, length(p / vec2<f32>(0.015, 0.023)));
        let cord = select(0.0, stroke(p, vec2<f32>(0.0, -0.075), vec2<f32>(0.0, -0.024), 0.001), lamp.y < 0.8 && lamp.x < 0.65);
        rgb = mix(rgb, vec3<f32>(0.05, 0.055, 0.04), cord * 0.6);
        alpha = max(alpha, cord * 0.6);
        let ribs = 0.78 + 0.22 * cos(p.x * 570.0);
        let lit_body = vec3<f32>(0.88, 0.35, 0.10) * ribs;
        let body_color = mix(vec3<f32>(0.09, 0.075, 0.055), lit_body, ignite);
        rgb = mix(rgb, body_color, body * 0.86);
        alpha = max(alpha, body * 0.86);
        // 火从灯芯向上长，再轻轻偏斜；新灯先出现火芯，随后才铺开光晕。
        p.x += sin(scroll.params.y * 4.0 + f32(i)) * p.y * 0.075;
        let wick = p - vec2<f32>(0.0, 0.011 - 0.015 * ignite);
        let flame_shape = wick / vec2<f32>(0.004, 0.013 * max(ignite, 0.01));
        let flame = exp(-dot(flame_shape, flame_shape));
        let fire = flame * ignite * breath;
        rgb += vec3<f32>(1.0, 0.69, 0.29) * halo + vec3<f32>(1.0, 0.90, 0.58) * fire;
        alpha = max(alpha, max(halo, fire));
    }
    // 上面按预乘累积，这里还原成 UI 所需的普通透明混合。
    return vec4<f32>(rgb / max(alpha, 0.001), clamp(alpha, 0.0, 1.0));
}
