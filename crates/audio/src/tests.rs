//! 用可控制初始化结果的后端测试完整插件，不依赖机器声卡或真实等待。

use std::cell::Cell;
use std::io;

use bevy::state::app::StatesPlugin;
use bevy::time::TimeUpdateStrategy;
use kira::backend::mock::{MockBackend, MockBackendSettings};
use kira::backend::{Backend, Renderer};

use super::*;

thread_local! {
    // 音频初始化是 NonSend 系统；每个测试线程各自控制设备状态。
    static DEVICE_AVAILABLE: Cell<bool> = const { Cell::new(false) };
    static ATTEMPTS: Cell<u32> = const { Cell::new(0) };
}

pub(super) struct TestBackend(MockBackend);

impl Backend for TestBackend {
    type Settings = ();
    type Error = io::Error;

    fn setup(_: (), internal_buffer_size: usize) -> Result<(Self, u32), Self::Error> {
        ATTEMPTS.set(ATTEMPTS.get() + 1);
        if !DEVICE_AVAILABLE.get() {
            return Err(io::Error::other("测试：没有音频设备"));
        }
        let (backend, rate) =
            MockBackend::setup(MockBackendSettings { sample_rate: 44_100 }, internal_buffer_size).unwrap();
        Ok((Self(backend), rate))
    }

    fn start(&mut self, renderer: Renderer) -> Result<(), Self::Error> {
        self.0.start(renderer).unwrap();
        Ok(())
    }
}

fn setup(available: bool) -> App {
    DEVICE_AVAILABLE.set(available);
    ATTEMPTS.set(0);
    let mut app = App::new();
    app.add_plugins((MinimalPlugins, StatesPlugin))
        .init_state::<AppState>()
        .add_sub_state::<RunState>()
        .init_resource::<Settings>()
        .init_resource::<SimOutbox>()
        .add_message::<UiCue>()
        .insert_resource(RunSetup::new(42, lantern_sim::RunMode::Normal))
        .insert_resource(SimPhase::Play)
        .add_plugins(AudioPlugin)
        .add_systems(Startup, |mut next: ResMut<NextState<AppState>>| {
            next.set(AppState::Title);
        });
    app
}

fn advance(app: &mut App, millis: u64) {
    app.insert_resource(TimeUpdateStrategy::ManualDuration(Duration::from_millis(millis)));
    app.update();
}

#[test]
fn missing_device_retries_in_real_time_and_recovers() {
    let mut app = setup(false);
    advance(&mut app, 0);
    assert!(app.world().contains_resource::<AudioUnavailable>());
    assert_eq!(ATTEMPTS.get(), 1);
    assert!(app.world().non_send::<Audio>()._manager.is_none());
    assert!(app.world().non_send::<Audio>().mixer.is_none());

    // 暂停（虚拟时间停住）也照样按真实时间重试。
    app.world_mut().resource_mut::<Time<Virtual>>().pause();
    advance(&mut app, 2999);
    assert_eq!(ATTEMPTS.get(), 1);
    advance(&mut app, 1);
    assert_eq!(ATTEMPTS.get(), 2);
    assert!(app.world().contains_resource::<AudioUnavailable>());

    // 第二次失败后间隔翻倍到 6 秒。
    DEVICE_AVAILABLE.set(true);
    advance(&mut app, 5999);
    assert_eq!(ATTEMPTS.get(), 2);
    assert!(app.world().contains_resource::<AudioUnavailable>());
    advance(&mut app, 1);
    assert_eq!(ATTEMPTS.get(), 3);
    assert!(!app.world().contains_resource::<AudioUnavailable>());
    let audio = app.world().non_send::<Audio>();
    assert!(audio._manager.is_some());
    assert!(audio.mixer.is_some());
    assert!(!audio.muffled);

    // 恢复后不再初始化管理器，即使经过很长的真实时间。
    advance(&mut app, 3_600_000);
    assert_eq!(ATTEMPTS.get(), 3);
    assert!(!app.world().contains_resource::<AudioUnavailable>());
}

#[test]
fn available_device_with_zero_volume_does_not_report_unavailable_or_retry() {
    let mut app = setup(true);
    {
        let mut settings = app.world_mut().resource_mut::<Settings>();
        settings.sfx_volume = 0.0;
        settings.music_volume = 0.0;
    }
    advance(&mut app, 0);
    assert!(!app.world().contains_resource::<AudioUnavailable>());
    assert_eq!(ATTEMPTS.get(), 1);
    assert!(app.world().non_send::<Audio>()._manager.is_some());

    advance(&mut app, 60_000);
    assert_eq!(ATTEMPTS.get(), 1);
    assert!(!app.world().contains_resource::<AudioUnavailable>());
}
