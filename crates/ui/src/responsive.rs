//! 标题和选择面板共用的画布：小窗口等比缩小，不改变游戏中其余界面的坐标。

use bevy::prelude::*;
use bevy::ui::{UiSystems, Val2};
use bevy::window::PrimaryWindow;

/// 面板按 1080 逻辑高度设计；宽度容纳最宽的 1160 面板及两侧留白。
const DESIGN_SIZE: Vec2 = Vec2::new(1280.0, 1080.0);

pub(crate) const PANEL_WIDTH_PERCENT: f32 = 90.0;
pub(crate) const CARD_WIDTH: f32 = 240.0;
pub(crate) const CARD_GAP: f32 = 22.0;

#[derive(Component)]
pub(crate) enum FitViewport {
    Fixed(Vec2),
    Upgrades(usize),
}

impl FitViewport {
    /// 准备页的可选行随解锁增加，为每行和页头、页脚留足空间。
    pub(crate) fn for_prep(rows: usize) -> Self {
        Self::Fixed(Vec2::new(DESIGN_SIZE.x, DESIGN_SIZE.y.max(280.0 + rows as f32 * 80.0)))
    }

    pub(crate) fn for_meta(items: usize) -> Self {
        // 两列文字允许换行；按最窄面板为每行和页头、提示留空间。
        Self::Fixed(Vec2::new(960.0, DESIGN_SIZE.y.max(280.0 + items.div_ceil(2) as f32 * 136.0)))
    }

    fn min_size(&self, logical_size: Vec2) -> Vec2 {
        match *self {
            Self::Fixed(size) => size,
            Self::Upgrades(cards) => upgrade_canvas(logical_size, cards),
        }
    }
}

impl Default for FitViewport {
    fn default() -> Self {
        Self::Fixed(DESIGN_SIZE)
    }
}

pub(crate) fn register(app: &mut App) {
    app.add_systems(PostUpdate, fit_viewport.before(UiSystems::Prepare));
}

/// 只接收窗口逻辑尺寸，DPI 已由 Bevy 换算，不能再除一次缩放因子。
fn panel_scale(logical_size: Vec2, min_size: Vec2) -> f32 {
    if !logical_size.is_finite() || logical_size.min_element() <= 0.0 {
        // 最小化时可能暂时没有可用尺寸，避免生成无穷大或非数坐标。
        return 1.0;
    }
    (logical_size / min_size).min_element().min(1.0)
}

/// 在一行到多行之间选择字号最大的排法；同样大时优先少换行。
/// 输入只用逻辑视口，返回排版画布的最小尺寸，不依赖窗口或 ECS。
fn upgrade_canvas(logical_size: Vec2, cards: usize) -> Vec2 {
    let cards = cards.max(1);
    let mut best_size = Vec2::ZERO;
    let mut best_scale = 0.0;
    for columns in 1..=cards {
        let rows = cards.div_ceil(columns) as f32;
        let width = CARD_WIDTH * columns as f32 + CARD_GAP * (columns - 1) as f32;
        // 每张卡为名称、说明和共鸣/进化提示留足高度；另留页头、操作提示及焦点框空间。
        let size =
            Vec2::new(width / (PANEL_WIDTH_PERCENT / 100.0), 280.0 + rows * 600.0 + (rows - 1.0) * CARD_GAP);
        let scale = panel_scale(logical_size, size);
        if scale >= best_scale {
            best_size = size;
            best_scale = scale;
        }
    }
    best_size
}

fn fit_viewport(
    window: Single<&Window, With<PrimaryWindow>>,
    mut panels: Query<(&FitViewport, &mut Node, &mut UiTransform)>,
) {
    for (panel, mut node, mut transform) in &mut panels {
        let scale = panel_scale(window.size(), panel.min_size(window.size()));
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
            let scale = panel_scale(size, DESIGN_SIZE);
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
            let scale = panel_scale(logical, DESIGN_SIZE);
            assert!((scale - 1.0 / dpi).abs() < 0.001);
            assert!((DESIGN_SIZE * scale * dpi).cmple(physical + Vec2::splat(0.001)).all());
        }
    }

    #[test]
    fn large_or_unavailable_windows_keep_a_finite_scale() {
        assert_eq!(panel_scale(Vec2::new(2560.0, 1440.0), DESIGN_SIZE), 1.0);
        for size in [Vec2::ZERO, Vec2::new(640.0, 0.0), Vec2::splat(f32::NAN), Vec2::INFINITY] {
            assert_eq!(panel_scale(size, DESIGN_SIZE), 1.0);
        }
    }

    #[test]
    fn existing_panels_follow_resize_dpi_and_restore() {
        let mut app = App::new();
        register(&mut app);
        let window = app.world_mut().spawn((Window::default(), PrimaryWindow)).id();
        let panel = app.world_mut().spawn((FitViewport::default(), Node::default())).id();
        for (width, height, dpi) in [(1920, 1080, 1.5), (1280, 720, 2.0), (360, 640, 1.0), (1920, 1080, 1.0)]
        {
            {
                let mut window = app.world_mut().get_mut::<Window>(window).unwrap();
                window.resolution.set_physical_resolution(width, height);
                window.resolution.set_scale_factor_override(Some(dpi));
            }
            app.update();
            let scale = panel_scale(Vec2::new(width as f32, height as f32) / dpi, DESIGN_SIZE);
            let node = app.world().get::<Node>(panel).unwrap();
            let transform = app.world().get::<UiTransform>(panel).unwrap();
            assert_eq!(node.width, percent(100.0 / scale));
            assert_eq!(node.height, percent(100.0 / scale));
            assert_eq!((node.left, node.top), (percent(50), percent(50)));
            assert_eq!(transform.scale, Vec2::splat(scale));
            assert_eq!(transform.translation, Val2::percent(-50.0, -50.0));
        }
    }

    #[test]
    fn fully_unlocked_prep_reserves_space_for_every_row_and_hints() {
        // 玩法、更、灯、灯坠、悟、八项属性、出发，共十四行。
        let prep = FitViewport::for_prep(14);
        let min_size = prep.min_size(DESIGN_SIZE);
        assert_eq!(min_size.y, 1400.0);
        assert_eq!(FitViewport::for_prep(4).min_size(DESIGN_SIZE), DESIGN_SIZE);
        for size in [Vec2::new(1280.0, 720.0), Vec2::new(960.0, 540.0), Vec2::new(640.0, 360.0)] {
            assert!((min_size * panel_scale(size, min_size)).cmple(size + Vec2::splat(0.001)).all());
        }
    }

    #[test]
    fn upgrade_cards_reflow_with_the_viewport_aspect_ratio() {
        let wide = upgrade_canvas(Vec2::new(1280.0, 720.0), 4);
        let narrow = upgrade_canvas(Vec2::new(360.0, 640.0), 4);
        assert!((wide.x * 0.9 - (4.0 * CARD_WIDTH + 3.0 * CARD_GAP)).abs() < 0.001);
        assert!((narrow.x * 0.9 - (2.0 * CARD_WIDTH + CARD_GAP)).abs() < 0.001);
        assert!(narrow.y > wide.y);
        assert!(panel_scale(Vec2::new(360.0, 640.0), narrow) > panel_scale(Vec2::new(360.0, 640.0), wide));
    }

    #[test]
    fn title_and_upgrade_layouts_fit_small_windows_and_high_dpi() {
        for physical in [
            Vec2::new(1920.0, 1080.0),
            Vec2::new(1280.0, 720.0),
            Vec2::new(1024.0, 768.0),
            Vec2::new(800.0, 600.0),
            Vec2::new(640.0, 360.0),
            Vec2::new(360.0, 640.0),
            Vec2::new(1600.0, 300.0),
        ] {
            for dpi in [1.0, 1.5, 2.0] {
                let logical = physical / dpi;
                for panel in
                    std::iter::once(FitViewport::for_meta(12)).chain((1..=4).map(FitViewport::Upgrades))
                {
                    let min_size = panel.min_size(logical);
                    let scale = panel_scale(logical, min_size);
                    assert!(scale.is_finite() && scale > 0.0 && scale <= 1.0);
                    assert!((min_size * scale * dpi).cmple(physical + Vec2::splat(0.001)).all());
                }
            }
        }
    }

    #[test]
    fn upgrade_layout_handles_empty_offers_and_unavailable_viewports() {
        for size in [Vec2::ZERO, Vec2::splat(f32::NAN), Vec2::INFINITY, Vec2::ONE] {
            for cards in 0..=4 {
                let canvas = upgrade_canvas(size, cards);
                assert!(canvas.is_finite() && canvas.min_element() > 0.0);
            }
        }
    }
}
