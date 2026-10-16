//! 运行时色板：与 art/style/style.py 的 RUNTIME_COLORS / RUNTIME_LEVELS 同值。
//! 修改后运行 python3 art/style/make_style_frames.py；脚本先校对，再生成三时刻样板。
//! 色值为 sRGB；光照强度和晨光插值在线性空间处理，不把亮度提升写进色相。
#![expect(dead_code, reason = "质感会话接入前，色板先只用来和美术的 style.py 对照")]

use bevy::prelude::*;

pub(crate) const INK: Color = Color::srgb_u8(23, 20, 15);
pub(crate) const GOLD: Color = Color::srgb_u8(226, 178, 58);
pub(crate) const DUST: Color = Color::srgb_u8(106, 100, 90);
/// 月夜（试玩第 1 轮：暗处也看得清地面和妖物）：光照图的底色，没被灯照到的地方乘它。
pub const NIGHT_AMBIENT: Color = Color::srgb_u8(70, 85, 127);
/// 夜签“无月”：原来的黑夜。
pub const NO_MOON_AMBIENT: Color = Color::srgb_u8(22, 27, 44);
pub(crate) const LANTERN_LIGHT: Color = Color::srgb_u8(255, 194, 122);
pub(crate) const FLAME_LIGHT: Color = Color::srgb_u8(255, 154, 77);
pub(crate) const SOUL_LIGHT: Color = Color::srgb_u8(191, 239, 255);
pub(crate) const WOOD_GLOW: Color = Color::srgb_u8(130, 164, 137);
pub(crate) const WATER_GLOW: Color = Color::srgb_u8(107, 142, 171);
pub(crate) const EARTH_GLOW: Color = Color::srgb_u8(190, 136, 78);
pub(crate) const WARNING: Color = Color::srgb_u8(234, 120, 65);
pub(crate) const DAWN_PEACH: Color = Color::srgb_u8(255, 209, 168);
pub(crate) const DAWN_WHITE: Color = Color::srgb_u8(255, 250, 240);

pub(crate) const IGNITE_LEN: f32 = 1.4;
pub const DAWN_LEN: f32 = 3.0;
pub(crate) const DAWN_DELAY: f32 = 0.8;
/// 妖潮只略压环境底光，灯光半径不变；克制装饰光，让危险色留在第一层。
pub(crate) const TIDE_AMBIENT_GAIN: f32 = 0.9;
pub(crate) const TIDE_PARTICLE_GAIN: f32 = 0.35;
pub(crate) const TIDE_DECOR_GAIN: f32 = 0.45;
pub(crate) const WARNING_ALPHA_MIN: f32 = 0.85;
pub(crate) const DAWN_LANTERN_GAIN: f32 = 0.35;
pub(crate) const DAWN_PARTICLE_GAIN: f32 = 0.2;

/// 天明经过暖桃再到鱼肚白；不直接在 sRGB 分量上插值，以免中段灰暗。
pub(crate) fn dawn_ambient(progress: f32) -> LinearRgba {
    let day = progress.clamp(0.0, 1.0);
    let (from, to, t) = if day < 0.5 {
        (NIGHT_AMBIENT, DAWN_PEACH, day * 2.0)
    } else {
        (DAWN_PEACH, DAWN_WHITE, (day - 0.5) * 2.0)
    };
    from.to_linear().mix(&to.to_linear(), t)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn luminance(c: LinearRgba) -> f32 {
        c.red * 0.2126 + c.green * 0.7152 + c.blue * 0.0722
    }

    #[test]
    fn ink_and_night_match_art_srgb() {
        assert_eq!(INK.to_srgba().to_u8_array(), [0x17, 0x14, 0x0f, 255]);
        assert_eq!(NIGHT_AMBIENT.to_srgba().to_u8_array(), [0x46, 0x55, 0x7f, 255]);
        assert_eq!(NO_MOON_AMBIENT.to_srgba().to_u8_array(), [0x16, 0x1b, 0x2c, 255]);
    }

    #[test]
    fn dawn_is_continuous_and_brightens_through_warm_peach() {
        assert_eq!(dawn_ambient(-1.0), NIGHT_AMBIENT.to_linear());
        assert_eq!(dawn_ambient(0.5), DAWN_PEACH.to_linear());
        assert_eq!(dawn_ambient(2.0), DAWN_WHITE.to_linear());
        let mut last = luminance(dawn_ambient(0.0));
        for i in 1..=100 {
            let c = dawn_ambient(i as f32 / 100.0);
            assert!(luminance(c) > last);
            assert_eq!(c.alpha, 1.0);
            last = luminance(c);
        }
        assert!((luminance(dawn_ambient(0.4999)) - luminance(dawn_ambient(0.5001))).abs() < 0.001);
    }

    #[test]
    fn tide_warning_has_more_light_than_a_single_decorative_particle() {
        // 比较同纹理、同覆盖面积的线性贡献；不能代替拥挤画面的实机遮挡检查。
        let warning = luminance(WARNING.to_linear()) * WARNING_ALPHA_MIN;
        for color in [GOLD, WOOD_GLOW, WATER_GLOW, FLAME_LIGHT, EARTH_GLOW, LANTERN_LIGHT] {
            assert!(warning > luminance(color.to_linear()) * TIDE_PARTICLE_GAIN);
        }
        let c = WARNING.to_srgba();
        assert!((c.red - c.blue) / c.red > 0.65);
        assert!(luminance(NIGHT_AMBIENT.to_linear()) * TIDE_AMBIENT_GAIN < luminance(dawn_ambient(0.5)));
    }
}
