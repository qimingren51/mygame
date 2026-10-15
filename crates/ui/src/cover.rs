//! 整幅画“铺满再居中裁边”（cover）：按 s = max(窗口宽 ÷ 画宽, 窗口高 ÷ 画高) 缩放后居中，
//! 超出窗口的部分裁掉，不拉伸、不留黑边（标题画、灯驿长卷，docs/DESIGN.md 第 15 节）。

use bevy::prelude::*;
use bevy::window::PrimaryWindow;

/// 挂在绝对定位的整幅画节点上：画的原始尺寸（像素）。
#[derive(Component, Clone, Copy)]
pub(crate) struct Cover(pub Vec2);

impl Cover {
    /// 窗口里的缩放和左上角位置。
    pub(crate) fn fit(self, window: Vec2) -> (f32, Vec2) {
        let s = (window.x / self.0.x).max(window.y / self.0.y);
        (s, (window - self.0 * s) * 0.5)
    }
}

pub(crate) fn fit_covers(window: Single<&Window, With<PrimaryWindow>>, mut q: Query<(&Cover, &mut Node)>) {
    let size = Vec2::new(window.width(), window.height());
    for (&c, mut node) in &mut q {
        let (s, at) = c.fit(size);
        let (w, h, l, t) = (px(c.0.x * s), px(c.0.y * s), px(at.x), px(at.y));
        if node.width != w || node.height != h || node.left != l || node.top != t {
            node.width = w;
            node.height = h;
            node.left = l;
            node.top = t;
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn cover_fills_and_centers() {
        let c = Cover(Vec2::new(1920.0, 1080.0));
        // 16:10：按高铺满，两边各裁 96（以 1920 宽计）
        let (s, at) = c.fit(Vec2::new(1920.0, 1200.0));
        assert!((s - 1200.0 / 1080.0).abs() < 1e-6);
        assert!((at.x - (1920.0 - 1920.0 * s) / 2.0).abs() < 1e-3 && at.y.abs() < 1e-3);
        // 21:9：按宽铺满，上下裁
        let (s, at) = c.fit(Vec2::new(2560.0, 1080.0));
        assert!((s - 2560.0 / 1920.0).abs() < 1e-6 && at.x.abs() < 1e-3 && at.y < 0.0);
    }
}
