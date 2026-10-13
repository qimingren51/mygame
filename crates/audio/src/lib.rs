//! 音频层（docs/DESIGN.md 第 10 节）。只读模拟事件，不影响玩法与随机流。
//! 四类总线分别调音量；场景混响、材质采样轮换和高光闪避均在 kira 内完成。

use std::time::Duration;

use bevy::prelude::*;
use kira::sound::static_sound::StaticSoundData;
use kira::{AudioManager, AudioManagerSettings, Decibels, DefaultBackend, Panning, StartTime};

use lantern_core::{Pcg32, step::TICK_HZ};
use lantern_platform::Settings;
use lantern_sim::combat::StrikeFx;
use lantern_sim::pickups::PickupKind;
use lantern_sim::{
    AppState, Director, Health, Player, Pos, RunSetup, RunState, SimEvent, SimOutbox, SimPhase, Tick,
};

mod ambience;
mod duck;
mod impact;
mod mixer;
mod music;
mod sfx;
mod space;
mod synth;

use ambience::Ambience;
use duck::{Ducking, Focus};
use impact::ImpactPicker;
use mixer::{Lane, Mixer, tween};
use music::{Music, MusicMode};
use sfx::{Instruments, Sfx};
use space::Scene;
use synth::pent;

/// 界面只报告场所，不直接操作音轨，也不写模拟状态。
#[derive(Resource, Clone, Copy, Debug, Default, PartialEq, Eq)]
pub enum MenuSoundscape {
    #[default]
    Title,
    Hub,
}

/// 界面确认反馈，走独立的界面音量。
#[derive(Message, Clone, Copy, Debug)]
pub enum UiCue {
    Move,
    Confirm,
    Back,
}

/// 界面在此系统集之前报告场所。PostUpdate 读取本帧事件，早于 Last 清空 outbox。
#[derive(SystemSet, Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub struct AudioSystems;

pub struct AudioPlugin;

impl Plugin for AudioPlugin {
    fn build(&self, app: &mut App) {
        app.init_resource::<MenuSoundscape>()
            .add_message::<UiCue>()
            .add_systems(Startup, init_audio)
            .add_systems(OnEnter(AppState::Title), |mut a: NonSendMut<Audio>| {
                a.reset();
                a.set_mode(MusicMode::Title, None);
            })
            .add_systems(OnEnter(AppState::Run), start_run)
            .add_systems(
                PostUpdate,
                (
                    advance_audio,
                    apply_settings,
                    sync_scene,
                    run_music_mode.run_if(in_state(AppState::Run)),
                    play_sim_events.run_if(in_state(AppState::Run)),
                    heartbeat.run_if(in_state(AppState::Run)),
                    play_ui_cues,
                    tick_music,
                    update_mix,
                )
                    .chain()
                    .in_set(AudioSystems),
            );
    }
}

/// kira 后端在部分平台不能跨线程传递，留在主线程。
pub struct Audio {
    _manager: Option<AudioManager>,
    mixer: Option<Mixer>,
    ducking: Ducking,
    death_silence_until: f64,
    impacts: ImpactPicker,
    rng: Pcg32,
    ambience: Ambience,
    scene: Scene,
    next_heart: f64,
    sfx: Sfx,
    music: Music,
    last: Vec<(&'static str, f64)>,
    now: f64,
    gem_chain: i32,
    gem_last: f64,
    muffled: bool,
    last_phase: Option<SimPhase>,
}

impl Audio {
    fn can(&mut self, name: &'static str, gap: f64) -> bool {
        let now = self.now;
        match self.last.iter_mut().find(|(n, _)| *n == name) {
            Some((_, t)) if now - *t < gap => false,
            Some((_, t)) => {
                *t = now;
                true
            }
            None => {
                self.last.push((name, now));
                true
            }
        }
    }

    fn play_on(&mut self, lane: Lane, sound: StaticSoundData) {
        if let Some(mixer) = &mut self.mixer {
            mixer.play(lane, sound);
        }
    }

    fn play(&mut self, sound: &StaticSoundData) {
        self.play_on(Lane::Combat, sound.clone());
    }

    fn foreground(&mut self, sound: &StaticSoundData) {
        if self.now >= self.death_silence_until {
            self.play_on(Lane::Foreground, sound.clone());
        }
    }

    fn warning(&mut self, sound: &StaticSoundData) {
        self.play_on(Lane::Warning, sound.clone());
    }

    fn interface(&mut self, sound: &StaticSoundData) {
        self.play_on(Lane::Ui, sound.clone());
    }

    fn play_with(&mut self, sound: &StaticSoundData, rate: f64, volume: f32) {
        self.play_on(Lane::Combat, sound.playback_rate(rate).volume(Decibels(volume)));
    }

    fn play_at(&mut self, sound: &StaticSoundData, rate: f64, volume: f32, (pan, far): (f32, f32)) {
        self.play_on(
            Lane::Combat,
            sound.playback_rate(rate).volume(Decibels(volume - far)).panning(Panning(pan)),
        );
    }

    /// 延迟的仪式声保留独立声部，不会被自己触发的闪避压掉起音。
    fn play_later(&mut self, sound: &StaticSoundData, delay: f64) {
        self.play_on(Lane::Foreground, sound.start_time(StartTime::Delayed(Duration::from_secs_f64(delay))));
    }

    fn reset(&mut self) {
        self.ducking = Ducking::default();
        self.death_silence_until = 0.0;
        self.last.clear();
        self.last_phase = None;
        self.gem_chain = 0;
        self.next_heart = self.now;
        self.muffle(false);
        if let Some(mixer) = &mut self.mixer {
            mixer.clear_sounds();
        }
    }

    fn set_mode(&mut self, mode: MusicMode, seed: Option<u64>) {
        self.music.set_mode(mode, seed, self.mixer.as_mut().map(|m| &mut m.music));
    }

    fn set_scene(&mut self, scene: Scene) {
        self.scene = scene;
        if let Some(mixer) = &mut self.mixer {
            mixer.set_scene(scene);
        }
        self.ambience.set_scene(scene, self.mixer.as_mut().map(|m| &mut m.ambience));
    }

    fn muffle(&mut self, on: bool) {
        if on == self.muffled {
            return;
        }
        self.muffled = on;
        if let Some(mixer) = &mut self.mixer {
            mixer.muffle(on);
        }
    }
}

fn init_audio(world: &mut World) {
    let settings = world.get_resource::<Settings>().cloned().unwrap_or_default();
    let mut manager = match AudioManager::<DefaultBackend>::new(AudioManagerSettings::default()) {
        Ok(m) => Some(m),
        Err(e) => {
            warn!("没有可用的音频输出，静音运行：{e}");
            None
        }
    };
    let mixer = manager.as_mut().and_then(|m| match Mixer::new(m, &settings) {
        Ok(mixer) => Some(mixer),
        Err(e) => {
            warn!("无法建立音频总线，静音运行：{e}");
            None
        }
    });
    world.insert_non_send(Audio {
        _manager: manager,
        mixer,
        ducking: Ducking::default(),
        death_silence_until: 0.0,
        impacts: ImpactPicker::new(1),
        rng: Pcg32::new(1, 0x0053_4658),
        ambience: Ambience::new(),
        scene: Scene::Title,
        next_heart: 0.0,
        sfx: Sfx::new(),
        music: Music::new(Instruments::new()),
        last: Vec::new(),
        now: 0.0,
        gem_chain: 0,
        gem_last: 0.0,
        muffled: false,
        last_phase: None,
    });
}

fn advance_audio(time: Res<Time<Real>>, mut audio: NonSendMut<Audio>) {
    audio.now = time.elapsed_secs_f64();
}

fn apply_settings(settings: Option<Res<Settings>>, mut audio: NonSendMut<Audio>) {
    if let Some(s) = settings
        && s.is_changed()
        && let Some(mixer) = &mut audio.mixer
    {
        mixer.settings(&s);
    }
}

fn start_run(setup: Res<RunSetup>, mut audio: NonSendMut<Audio>) {
    audio.reset();
    audio.impacts = ImpactPicker::new(setup.seed);
    audio.rng = Pcg32::new(setup.seed, 0x0053_4658);
    audio.set_mode(MusicMode::Play, Some(setup.seed));
}

fn sync_scene(
    state: Res<State<AppState>>,
    menu: Res<MenuSoundscape>,
    director: Option<Res<Director>>,
    mut audio: NonSendMut<Audio>,
) {
    let scene = match state.get() {
        AppState::Boot => return,
        AppState::Title if *menu == MenuSoundscape::Hub => Scene::Hub,
        AppState::Title | AppState::Results => Scene::Title,
        AppState::Run if director.is_some_and(|d| d.boss.is_some()) => Scene::Boss,
        AppState::Run => Scene::Night,
    };
    audio.set_scene(scene);
}

/// 音乐强度仍沿用既有节奏；暂停、选择和结束时低通。
fn run_music_mode(
    tick: Option<Res<Tick>>,
    director: Option<Res<Director>>,
    phase: Option<Res<SimPhase>>,
    run: Option<Res<State<RunState>>>,
    mut audio: NonSendMut<Audio>,
) {
    let secs = tick.map_or(0, |t| t.0 / u64::from(TICK_HZ));
    let boss = director.is_some_and(|d| d.boss.is_some());
    if phase.as_deref() != Some(&SimPhase::Over) {
        audio.music.intensity = if secs < 180 {
            0
        } else if secs < 390 {
            1
        } else {
            2
        };
        let mode = if boss { MusicMode::Boss } else { MusicMode::Play };
        if audio.music.mode != mode {
            audio.set_mode(mode, None);
        }
    }
    let menu = phase.as_deref().is_some_and(|p| *p != SimPhase::Play)
        || run.is_some_and(|r| *r.get() != RunState::Playing);
    audio.muffle(menu);
    let now = phase.as_deref().copied();
    if audio.last_phase == Some(SimPhase::LevelUp) && now != Some(SimPhase::LevelUp) {
        let s = audio.sfx.select.clone();
        audio.interface(&s);
    }
    audio.last_phase = now;
}

fn play_ui_cues(mut cues: MessageReader<UiCue>, mut audio: NonSendMut<Audio>) {
    if let Some(cue) = cues.read().last()
        && audio.can("ui", 0.045)
    {
        let s = match cue {
            UiCue::Move => &audio.sfx.ui_move,
            UiCue::Confirm => &audio.sfx.ui_confirm,
            UiCue::Back => &audio.sfx.ui_back,
        }
        .clone();
        audio.interface(&s);
    }
}

fn tick_music(mut audio: NonSendMut<Audio>) {
    let Audio { music, mixer, now, .. } = &mut *audio;
    music.tick(*now, mixer.as_mut().map(|m| &mut m.music));
}

fn update_mix(mut audio: NonSendMut<Audio>) {
    let now = audio.now;
    let duck = audio.ducking.gains(now);
    let silence = now < audio.death_silence_until;
    if let Some(mixer) = &mut audio.mixer {
        mixer.update(duck, tween(25));
        mixer.silence_foreground(silence);
    }
}

/// 濒死的心跳：生命低于三成时越来越急（和画面的暗角同一个节奏公式）。
fn heartbeat(
    phase: Option<Res<SimPhase>>,
    run: Option<Res<State<RunState>>>,
    hero: Option<Single<&Health, With<Player>>>,
    mut audio: NonSendMut<Audio>,
) {
    let playing =
        phase.as_deref() == Some(&SimPhase::Play) && run.is_some_and(|r| *r.get() == RunState::Playing);
    let Some(h) = hero else { return };
    let hp = h.hp / h.max.max(1.0);
    let low = ((0.3 - hp) / 0.2).clamp(0.0, 1.0);
    let a = &mut *audio;
    if !playing || low <= 0.0 || h.hp <= 0.0 {
        a.next_heart = a.now + 0.3;
        return;
    }
    if a.now >= a.next_heart {
        a.next_heart = a.now + 1.0 / f64::from(1.1 + low * 0.6);
        let s = a.sfx.heart.clone();
        a.play_with(&s, 1.0, -8.0 + low * 6.0);
    }
}

fn play_sim_events(
    outbox: Res<SimOutbox>,
    hero: Option<Single<&Pos, With<Player>>>,
    mut audio: NonSendMut<Audio>,
) {
    let hero = hero.map_or(bevy::math::Vec2::ZERO, |p| p.0);
    let space = audio.scene.space();
    let place = |p: bevy::math::Vec2| space.place(p - hero);
    let a = &mut *audio;
    if a.now - a.gem_last > 0.6 {
        a.gem_chain = 0;
    }
    // 先汇总整帧高光，再排声音，避免事件先后顺序改变闪避结果。
    for ev in &outbox.0 {
        if let Some(focus) = Focus::for_event(ev) {
            a.ducking.trigger(focus, a.now);
        }
        if matches!(ev, SimEvent::BossDefeated { .. }) {
            a.death_silence_until = a.now + 0.55;
            if let Some(mixer) = &mut a.mixer {
                mixer.clear_foreground();
            }
        }
    }
    for ev in &outbox.0 {
        match *ev {
            SimEvent::Hit { crit, kind, pos, element, .. } => {
                if kind == lantern_sim::HitKind::Dot {
                    continue;
                }
                let (name, gap) = if crit { ("crit", 0.06) } else { ("hit", 0.045) };
                if a.can(name, gap) {
                    let pick = a.impacts.next(element, crit);
                    let s = a.sfx.impacts.sound(pick);
                    a.play_at(&s, pick.rate, pick.volume, place(pos));
                }
            }
            SimEvent::Kill { rank: lantern_content::Rank::Elite, pos, .. } => {
                let s = a.sfx.elite_down.clone();
                a.play_at(&s, 1.0, 0.0, place(pos));
            }
            SimEvent::Kill { pos, .. } if a.can("kill", 0.04) => {
                let rate = f64::from(a.rng.range_f32(0.92, 1.08));
                let s = a.sfx.kill.clone();
                a.play_at(&s, rate, 0.0, place(pos));
            }
            // 夜主倒下：战斗与背景静半拍，一声低锣；天明时编钟和晨鸟（无尽夜不天明）
            SimEvent::BossDefeated { dawn, .. } => {
                let s = a.sfx.boss_down.clone();
                a.play_later(&s, 0.6);
                if dawn {
                    let s = a.sfx.dawn.clone();
                    a.play_later(&s, 1.6);
                }
            }
            SimEvent::GemPicked { .. } if a.can("gem", 0.05) => {
                a.gem_last = a.now;
                // 连续拾取时音高一路爬升
                let rate = f64::from(pent(10 + a.gem_chain % 12) / pent(10));
                a.gem_chain += 1;
                let s = a.sfx.gem.clone();
                a.play_with(&s, rate, 0.0);
            }
            SimEvent::Dash { .. } => {
                let s = a.sfx.dash.clone();
                a.play(&s);
            }
            SimEvent::PlayerHurt { .. } | SimEvent::Sacrifice { .. } if a.can("hurt", 0.2) => {
                let s = a.sfx.hurt.clone();
                a.foreground(&s);
            }
            SimEvent::LevelUp { .. } if a.can("level", 0.3) => {
                let s = a.sfx.level_up.clone();
                a.interface(&s);
            }
            SimEvent::ChestOpened { count, .. } => {
                let i = if count >= 5 {
                    2
                } else if count >= 3 {
                    1
                } else {
                    0
                };
                let s = a.sfx.chest[i].clone();
                a.interface(&s);
            }
            SimEvent::Evolve { .. } => {
                let s = a.sfx.evolution.clone();
                a.foreground(&s);
            }
            // 共鸣跨阶：盖章的闷响 + 钟
            SimEvent::Resonance { .. } if a.can("res", 0.3) => {
                let s = a.sfx.stamp.clone();
                a.foreground(&s);
                let s = a.sfx.resonance.clone();
                a.foreground(&s);
            }
            SimEvent::Sheng { .. } | SimEvent::Taiji | SimEvent::Buff { .. } if a.can("res", 0.3) => {
                let s = a.sfx.resonance.clone();
                a.foreground(&s);
            }
            SimEvent::Ult => {
                let s = a.sfx.ult.clone();
                a.foreground(&s);
            }
            SimEvent::CoinPicked { .. } if a.can("coin", 0.08) => {
                let s = a.sfx.coins.clone();
                a.play_with(&s, 1.0, -8.0);
            }
            SimEvent::LanternLit { .. } => {
                let s = a.sfx.event.clone();
                a.foreground(&s);
            }
            SimEvent::EncircleWarn { .. } => {
                let s = a.sfx.warn_big.clone();
                a.warning(&s);
            }
            SimEvent::SweepWarn { .. } | SimEvent::RainWarn { .. } if a.can("bwarn", 0.3) => {
                let s = a.sfx.warn.clone();
                a.warning(&s);
            }
            SimEvent::LastStand { .. } | SimEvent::Revived { .. } => {
                let s = a.sfx.big_bell.clone();
                a.foreground(&s);
            }
            SimEvent::CharmTaken { .. } => {
                let s = a.sfx.resonance.clone();
                a.foreground(&s);
            }
            SimEvent::BossPhase { .. } | SimEvent::BossEnraged => {
                let s = a.sfx.big_bell.clone();
                a.foreground(&s);
            }
            // 五行反应：第一次发生用盖章的声音，之后每种反应换一个音高
            SimEvent::Reaction { kind, first, pos, .. } => {
                if first {
                    let s = a.sfx.stamp.clone();
                    a.foreground(&s);
                    let s = a.sfx.resonance.clone();
                    a.foreground(&s);
                } else if a.can("react", 0.12) {
                    let rate = f64::from(pent(8 + i32::from(kind) % 7) / pent(8));
                    let s = a.sfx.bell_pulse.clone();
                    a.play_at(&s, rate, -6.0, place(pos));
                }
            }
            SimEvent::UltReady => {
                let s = a.sfx.ult_ready.clone();
                a.foreground(&s);
            }
            SimEvent::SwordFired { .. } if a.can("sword", 0.1) => {
                let s = a.sfx.sword.clone();
                a.play(&s);
            }
            SimEvent::CraneStrike { pos } if a.can("crane", 0.08) => {
                let s = a.sfx.crane.clone();
                a.play_at(&s, 1.0, 0.0, place(pos));
            }
            SimEvent::Strike { fx, pos, .. } => {
                let (name, gap, sound) = match fx {
                    StrikeFx::Pulse => ("pulse", 0.4, &a.sfx.bell_pulse),
                    StrikeFx::Toll => ("toll", 0.5, &a.sfx.big_bell),
                    StrikeFx::Seal { .. } => ("seal", 0.12, &a.sfx.seal),
                    StrikeFx::Blast(_) => ("blast", 0.09, &a.sfx.blast),
                    StrikeFx::Quake => ("quake", 0.3, &a.sfx.quake),
                    StrikeFx::Taiji => ("taiji", 1.0, &a.sfx.resonance),
                    StrikeFx::Ult | StrikeFx::None => continue,
                };
                let s = sound.clone();
                if a.can(name, gap) {
                    // 全屏的（钟鸣、太极）不分左右
                    let at =
                        if matches!(fx, StrikeFx::Toll | StrikeFx::Taiji) { (0.0, 0.0) } else { place(pos) };
                    a.play_at(&s, 1.0, 0.0, at);
                }
            }
            SimEvent::Elite { .. } => {
                let s = a.sfx.warn.clone();
                a.warning(&s);
            }
            SimEvent::BossArrived { .. } | SimEvent::Surge => {
                let s = a.sfx.warn_big.clone();
                a.warning(&s);
            }
            // 无尽夜夜深一层：和妖潮的警报同时来，晚半拍沉下去
            SimEvent::NightDeeper { .. } => {
                let s = a.sfx.deeper.clone();
                a.play_later(&s, 0.5);
            }
            SimEvent::Pickup { kind: PickupKind::Bell, .. } => {
                let s = a.sfx.soul_bell.clone();
                a.play(&s);
            }
            SimEvent::PlayerHealed { .. } if a.can("heal", 0.5) => {
                let s = a.sfx.heal.clone();
                a.play(&s);
            }
            SimEvent::ShieldUp if a.can("shield", 0.5) => {
                let s = a.sfx.shield.clone();
                a.play(&s);
            }
            SimEvent::Combo { .. } => {
                let s = a.sfx.combo.clone();
                a.foreground(&s);
            }
            SimEvent::Encounter { .. } => {
                let s = a.sfx.event.clone();
                a.foreground(&s);
            }
            SimEvent::CritterLooted { .. } => {
                let s = a.sfx.coins.clone();
                a.play(&s);
            }
            SimEvent::RunOver { won } => {
                a.set_mode(MusicMode::None, None);
                let s = if won { a.sfx.victory.clone() } else { a.sfx.defeat.clone() };
                a.foreground(&s);
            }
            _ => {}
        }
    }
}
