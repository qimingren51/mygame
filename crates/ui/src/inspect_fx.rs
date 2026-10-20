//! 物件检视的声音（docs/FEEL.md 第 14 节）：盯着画面层的 [`Inspect`]，打开、物件转进来、手转过一格、
//! 缩放一格、合上，各发一条 [`UiCue`]。面板和输入在 `inspect_ui.rs`，这里只听不改。

use bevy::prelude::*;
use lantern_platform::UiCue;
use lantern_view::inspect::Inspect;

/// 手转多少弧度响一下
const DETENT: f32 = std::f32::consts::PI / 6.0;
/// 最远那一格（0.75 倍，滚轮一格 1.12 倍）记作第 0 格
const FARTHEST: i32 = -3;

pub(crate) fn register(app: &mut App) {
    app.add_systems(Update, cues.after(crate::inspect_ui::input));
}

/// 这一帧检视的样子
#[derive(Clone, Copy)]
struct Seen<'a> {
    id: Option<&'a str>,
    entered: bool,
    turned: f32,
    zoom: i32,
}

impl<'a> Seen<'a> {
    fn of(v: &'a Inspect) -> Self {
        Seen { id: v.id(), entered: v.entered(), turned: v.turned(), zoom: v.zoom_step() }
    }
}

/// 上一帧听到哪了
#[derive(Default)]
struct Heard {
    id: Option<String>,
    entered: bool,
    turned: f32,
    zoom: i32,
}

impl Heard {
    fn hear(&mut self, now: Seen) -> Vec<UiCue> {
        let mut cues = Vec::new();
        if now.id != self.id.as_deref() {
            cues.push(if now.id.is_some() { UiCue::InspectOpen } else { UiCue::InspectClose });
            self.id = now.id.map(str::to_owned);
            self.entered = false;
            // 换了一件时，画面层下一帧才把上一件的状态清掉，这一帧不往下看
            return cues;
        }
        if now.id.is_none() {
            return cues;
        }
        // 入场以前（加载、等着色器、打开时归零）只记下起点，不出声；读不出模型就一直不出声
        if !self.entered {
            if now.entered {
                self.entered = true;
                cues.push(UiCue::InspectEnter);
            }
            self.turned = now.turned;
            self.zoom = now.zoom;
            return cues;
        }
        if (now.turned / DETENT).floor() > (self.turned / DETENT).floor() {
            cues.push(UiCue::InspectTurn);
        }
        self.turned = now.turned;
        if now.zoom != self.zoom {
            cues.push(UiCue::InspectZoom((now.zoom - FARTHEST).clamp(0, 255) as u8));
            self.zoom = now.zoom;
        }
        cues
    }
}

fn cues(inspect: Option<Res<Inspect>>, mut heard: Local<Heard>, mut out: MessageWriter<UiCue>) {
    let Some(inspect) = inspect else { return };
    for cue in heard.hear(Seen::of(&inspect)) {
        out.write(cue);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn seen(id: Option<&str>, entered: bool, turned: f32, zoom: i32) -> Seen<'_> {
        Seen { id, entered, turned, zoom }
    }

    #[test]
    fn open_enter_turn_zoom_close_in_order() {
        let mut h = Heard::default();
        assert!(h.hear(seen(None, false, 0.0, 0)).is_empty());
        assert_eq!(
            h.hear(seen(Some("sword"), true, 3.0, 2)),
            [UiCue::InspectOpen],
            "上一件的状态还没清，不算入场"
        );
        assert!(h.hear(seen(Some("sword"), false, 0.0, 0)).is_empty(), "加载中");
        assert_eq!(h.hear(seen(Some("sword"), true, 0.0, 0)), [UiCue::InspectEnter]);
        assert!(h.hear(seen(Some("sword"), true, DETENT * 0.9, 0)).is_empty(), "还没转满一格");
        assert_eq!(h.hear(seen(Some("sword"), true, DETENT * 1.1, 0)), [UiCue::InspectTurn]);
        assert_eq!(h.hear(seen(Some("sword"), true, DETENT * 1.1, 1)), [UiCue::InspectZoom(4)]);
        assert_eq!(h.hear(seen(Some("sword"), true, DETENT * 1.1, -3)), [UiCue::InspectZoom(0)]);
        assert_eq!(h.hear(seen(None, false, 0.0, 0)), [UiCue::InspectClose]);
        assert!(h.hear(seen(None, false, 0.0, 0)).is_empty());
    }

    #[test]
    fn switching_items_opens_again_and_waits_for_the_new_one() {
        let mut h = Heard::default();
        h.hear(seen(Some("sword"), false, 0.0, 0));
        h.hear(seen(Some("sword"), true, 0.0, 0));
        assert_eq!(h.hear(seen(Some("wind_wheel"), true, 5.0, 0)), [UiCue::InspectOpen]);
        assert!(h.hear(seen(Some("wind_wheel"), false, 0.0, 0)).is_empty(), "画面层清零后不会补响转动");
        assert_eq!(h.hear(seen(Some("wind_wheel"), true, 0.0, 0)), [UiCue::InspectEnter]);
    }

    #[test]
    fn a_model_that_fails_to_load_stays_quiet() {
        let mut h = Heard::default();
        h.hear(seen(Some("sword"), false, 0.0, 0));
        assert!(h.hear(seen(Some("sword"), false, 2.0, 3)).is_empty());
    }
}
