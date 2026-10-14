//! 标题和选择面板共用的画布：小窗口等比缩小，不改变游戏中其余界面的坐标。

use bevy::prelude::*;
use bevy::ui::{UiSystems, Val2};
use bevy::window::PrimaryWindow;

/// 面板按 1080 逻辑高度设计；宽度容纳最宽的 1160 面板及两侧留白。
const DESIGN_SIZE: Vec2 = Vec2::new(1280.0, 1080.0);

#[derive(Component)]
pub(crate) struct FitViewport;

pub(crate) fn register(app: &mut App) {
    app.add_systems(PostUpdate, fit_viewport.before(UiSystems::Prepare));
}

/// 只接收窗口逻辑尺寸，DPI 已由 Bevy 换算，不能再除一次缩放因子。
fn panel_scale(logical_size: Vec2) -> f32 {
    if !logical_size.is_finite() || logical_size.min_element() <= 0.0 {
        // 最小化时可能暂时没有可用尺寸，避免生成无穷大或非数坐标。
        return 1.0;
    }
    (logical_size / DESIGN_SIZE).min_element().min(1.0)
}

fn fit_viewport(
    window: Single<&Window, With<PrimaryWindow>>,
    mut panels: Query<(&mut Node, &mut UiTransform), With<FitViewport>>,
) {
    let scale = panel_scale(window.size());
    for (mut node, mut transform) in &mut panels {
        // 扩大排版画布后绕窗口中心缩回，背景仍铺满窗口，文字和点击区域一起缩放。
        let extent = percent(100.0 / scale);
        if node.left != percent(50)
            || node.top != percent(50)
            || node.width != extent
            || node.height != extent
        {
            node.left = percent(50);
            node.top = percent(50);
            node.width = extent;
            node.height = extent;
        }
        transform.set_if_neq(UiTransform {
            translation: Val2::percent(-50.0, -50.0),
            scale: Vec2::splat(scale),
            ..default()
        });
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn small_and_narrow_windows_fit_the_design_canvas() {
        for size in [
            Vec2::new(1280.0, 720.0),
            Vec2::new(1024.0, 768.0),
            Vec2::new(960.0, 540.0),
            Vec2::new(800.0, 600.0),
            Vec2::new(640.0, 360.0),
            Vec2::new(360.0, 640.0),
            Vec2::new(1600.0, 300.0),
            Vec2::ONE,
        ] {
            let scale = panel_scale(size);
            assert!(scale > 0.0 && scale <= 1.0);
            assert!((DESIGN_SIZE * scale).cmple(size + Vec2::splat(0.001)).all());
            // 不设最小缩放下限，否则更小的窗口仍会溢出。
            assert!(((size / scale) - DESIGN_SIZE).min_element().abs() < 0.001);
        }
    }

    #[test]
    fn high_dpi_uses_logical_dimensions_once() {
        let physical = Vec2::new(1920.0, 1080.0);
        for dpi in [1.0, 1.25, 1.5, 2.0] {
            let logical = physical / dpi;
            let scale = panel_scale(logical);
            assert!((scale - 1.0 / dpi).abs() < 0.001);
            assert!((DESIGN_SIZE * scale * dpi).cmple(physical + Vec2::splat(0.001)).all());
        }
    }

    #[test]
    fn large_or_unavailable_windows_keep_a_finite_scale() {
        assert_eq!(panel_scale(Vec2::new(2560.0, 1440.0)), 1.0);
        for size in [Vec2::ZERO, Vec2::new(640.0, 0.0), Vec2::splat(f32::NAN), Vec2::INFINITY] {
            assert_eq!(panel_scale(size), 1.0);
        }
    }

    #[test]
    fn existing_panels_follow_resize_dpi_and_restore() {
        let mut app = App::new();
        register(&mut app);
        let window = app.world_mut().spawn((Window::default(), PrimaryWindow)).id();
        let panel = app.world_mut().spawn((FitViewport, Node::default())).id();
        for (width, height, dpi) in [(1920, 1080, 1.5), (1280, 720, 2.0), (360, 640, 1.0), (1920, 1080, 1.0)]
        {
            {
                let mut window = app.world_mut().get_mut::<Window>(window).unwrap();
                window.resolution.set_physical_resolution(width, height);
                window.resolution.set_scale_factor_override(Some(dpi));
            }
            app.update();
            let scale = panel_scale(Vec2::new(width as f32, height as f32) / dpi);
            let node = app.world().get::<Node>(panel).unwrap();
            let transform = app.world().get::<UiTransform>(panel).unwrap();
            assert_eq!(node.width, percent(100.0 / scale));
            assert_eq!(node.height, percent(100.0 / scale));
            assert_eq!((node.left, node.top), (percent(50), percent(50)));
            assert_eq!(transform.scale, Vec2::splat(scale));
            assert_eq!(transform.translation, Val2::percent(-50.0, -50.0));
        }
    }
}
