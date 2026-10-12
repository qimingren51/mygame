//! 音频层（docs/DESIGN.md 第 10 节）。只消费模拟事件，不影响模拟。
//!
//! - 启动时用代码合成全部乐器和音效（[`synth`]、[`sfx`]），不用音频文件。
//! - 音效和音乐各走一条轨道，音量来自设置；音乐轨道带低通滤波，升级选择、暂停时变闷。
//! - 背景音乐（[`music`]）：低音持续音 + 按种子生成的五声旋律 + 随局势加强的鼓点；夜主出场后换成更紧的节奏。
//! - 同类声音有最短间隔，几百次命中也不会炸耳朵。

use std::time::Duration;

use bevy::prelude::*;
use kira::effect::filter::{FilterBuilder, FilterHandle};
use kira::sound::static_sound::StaticSoundData;
use kira::track::{TrackBuilder, TrackHandle};
use kira::{AudioManager, AudioManagerSettings, Decibels, DefaultBackend, Tween};

use lantern_core::step::TICK_HZ;
use lantern_platform::Settings;
use lantern_sim::combat::StrikeFx;
use lantern_sim::pickups::PickupKind;
use lantern_sim::{AppState, Director, RunSetup, RunState, SimEvent, SimOutbox, SimPhase, Tick};

mod music;
mod sfx;
mod synth;

use music::{Music, MusicMode};
use sfx::{Instruments, Sfx};
use synth::pent;

pub struct AudioPlugin;

impl Plugin for AudioPlugin {
    fn build(&self, app: &mut App) {
        app.add_systems(Startup, init_audio)
            .add_systems(OnEnter(AppState::Title), |mut a: NonSendMut<Audio>| {
                a.set_mode(MusicMode::Title, None)
            })
            .add_systems(OnEnter(AppState::Run), start_run)
            .add_systems(
                Update,
                (
                    apply_settings,
                    play_sim_events.run_if(in_state(AppState::Run)),
                    run_music_mode.run_if(in_state(AppState::Run)),
                    tick_music,
                )
                    .chain(),
            );
    }
}

/// 线性音量（0–1）换成分贝。
fn db(v: f32) -> Decibels {
    if v <= 0.001 { Decibels::SILENCE } else { Decibels(20.0 * v.log10()) }
}

/// 音效按网页版的增益合成，整体偏轻；音效轨道再提 7 分贝。
fn sfx_db(v: f32) -> Decibels {
    let d = db(v);
    if d == Decibels::SILENCE { d } else { Decibels(d.0 + 7.0) }
}

/// kira 的后端在部分平台上不能跨线程传递，所以作为 NonSend 资源放在主线程。
pub struct Audio {
    /// 管理器被丢掉时声音就停了，一直留着
    _manager: Option<AudioManager>,
    sfx_track: Option<TrackHandle>,
    music_track: Option<TrackHandle>,
    music_filter: Option<FilterHandle>,
    sfx: Sfx,
    music: Music,
    /// 各种音效上次播放的时刻（秒），用于限制间隔
    last: Vec<(&'static str, f64)>,
    now: f64,
    /// 拾取魂火的连拾次数；停顿一会儿回到起点
    gem_chain: i32,
    gem_last: f64,
    muffled: bool,
    /// 上一帧的模拟阶段：离开升级选择时响一声确认
    last_phase: Option<SimPhase>,
}

impl Audio {
    /// 同名音效的最短间隔。
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

    fn play_on(track: Option<&mut TrackHandle>, sound: StaticSoundData) {
        if let Some(track) = track
            && let Err(e) = track.play(sound)
        {
            warn!("播放失败：{e}");
        }
    }

    fn play(&mut self, sound: &StaticSoundData) {
        Self::play_on(self.sfx_track.as_mut(), sound.clone());
    }

    fn play_with(&mut self, sound: &StaticSoundData, rate: f64, volume: f32) {
        Self::play_on(self.sfx_track.as_mut(), sound.playback_rate(rate).volume(Decibels(volume)));
    }

    fn set_mode(&mut self, mode: MusicMode, seed: Option<u64>) {
        let Self { music, music_track, .. } = self;
        music.set_mode(mode, seed, music_track.as_mut());
    }

    fn muffle(&mut self, on: bool) {
        if on == self.muffled {
            return;
        }
        self.muffled = on;
        if let Some(f) = &mut self.music_filter {
            let tween = Tween { duration: Duration::from_millis(150), ..default() };
            f.set_cutoff(if on { 650.0 } else { 18_000.0 }, tween);
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
    let (mut sfx_track, mut music_track, mut music_filter) = (None, None, None);
    if let Some(m) = &mut manager {
        sfx_track = m.add_sub_track(TrackBuilder::new().volume(sfx_db(settings.sfx_volume))).ok();
        let mut builder = TrackBuilder::new().volume(db(settings.music_volume));
        music_filter = Some(builder.add_effect(FilterBuilder::new().cutoff(18_000.0)));
        music_track = m.add_sub_track(builder).ok();
    }
    world.insert_non_send(Audio {
        _manager: manager,
        sfx_track,
        music_track,
        music_filter,
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

/// 设置里的音量变了就跟着改。
fn apply_settings(settings: Option<Res<Settings>>, mut audio: NonSendMut<Audio>) {
    let Some(s) = settings else { return };
    if !s.is_changed() {
        return;
    }
    let tween = Tween { duration: Duration::from_millis(100), ..default() };
    if let Some(t) = &mut audio.sfx_track {
        t.set_volume(sfx_db(s.sfx_volume), tween);
    }
    if let Some(t) = &mut audio.music_track {
        t.set_volume(db(s.music_volume), tween);
    }
}

fn start_run(setup: Res<RunSetup>, mut audio: NonSendMut<Audio>) {
    audio.gem_chain = 0;
    audio.set_mode(MusicMode::Play, Some(setup.seed));
}

/// 局势：开局、3 分钟、6.5 分钟三档；夜主在场时换成夜主的音乐。选择、暂停、结束时音乐变闷。
fn run_music_mode(
    tick: Option<Res<Tick>>,
    director: Option<Res<Director>>,
    phase: Option<Res<SimPhase>>,
    run: Option<Res<State<RunState>>>,
    mut audio: NonSendMut<Audio>,
) {
    let secs = tick.map_or(0, |t| t.0 / u64::from(TICK_HZ));
    let boss = director.is_some_and(|d| d.boss.is_some());
    let over = phase.as_deref() == Some(&SimPhase::Over);
    if !over {
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
        audio.play(&s);
    }
    audio.last_phase = now;
}

fn tick_music(time: Res<Time<Real>>, mut audio: NonSendMut<Audio>) {
    audio.now = time.elapsed_secs_f64();
    let now = audio.now;
    let Audio { music, music_track, .. } = &mut *audio;
    music.tick(now, music_track.as_mut());
}

fn play_sim_events(outbox: Res<SimOutbox>, mut audio: NonSendMut<Audio>) {
    let a = &mut *audio;
    if a.now - a.gem_last > 0.6 {
        a.gem_chain = 0;
    }
    for ev in &outbox.0 {
        match *ev {
            SimEvent::Hit { crit, kind, .. } => {
                if kind == lantern_sim::HitKind::Dot {
                    continue;
                }
                if crit {
                    if a.can("crit", 0.06) {
                        let s = a.sfx.crit.clone();
                        a.play(&s);
                    }
                } else if a.can("hit", 0.045) {
                    let rate = 0.8 + (a.now * 7919.0).fract() * 0.5;
                    let s = a.sfx.hit.clone();
                    a.play_with(&s, rate, 0.0);
                }
            }
            SimEvent::Kill { .. } if a.can("kill", 0.04) => {
                let rate = 0.85 + (a.now * 104_729.0).fract() * 0.3;
                let s = a.sfx.kill.clone();
                a.play_with(&s, rate, 0.0);
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
                a.play(&s);
            }
            SimEvent::LevelUp { .. } if a.can("level", 0.3) => {
                let s = a.sfx.level_up.clone();
                a.play(&s);
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
                a.play(&s);
            }
            SimEvent::Evolve { .. } => {
                let s = a.sfx.evolution.clone();
                a.play(&s);
            }
            SimEvent::Resonance { .. } | SimEvent::Sheng { .. } | SimEvent::Taiji | SimEvent::Buff { .. }
                if a.can("res", 0.3) =>
            {
                let s = a.sfx.resonance.clone();
                a.play(&s);
            }
            SimEvent::Ult => {
                let s = a.sfx.ult.clone();
                a.play(&s);
            }
            SimEvent::CoinPicked { .. } if a.can("coin", 0.08) => {
                let s = a.sfx.coins.clone();
                a.play_with(&s, 1.0, -8.0);
            }
            SimEvent::LanternLit { .. } => {
                let s = a.sfx.event.clone();
                a.play(&s);
            }
            SimEvent::EncircleWarn { .. } => {
                let s = a.sfx.warn_big.clone();
                a.play(&s);
            }
            SimEvent::SweepWarn { .. } | SimEvent::RainWarn { .. } if a.can("bwarn", 0.3) => {
                let s = a.sfx.warn.clone();
                a.play(&s);
            }
            SimEvent::BossPhase { .. } | SimEvent::BossEnraged => {
                let s = a.sfx.big_bell.clone();
                a.play(&s);
            }
            // 五行反应：第一次发生用盖章的声音，之后每种反应换一个音高
            SimEvent::Reaction { kind, first, .. } => {
                if first {
                    let s = a.sfx.resonance.clone();
                    a.play(&s);
                } else if a.can("react", 0.12) {
                    let rate = f64::from(pent(8 + i32::from(kind) % 7) / pent(8));
                    let s = a.sfx.bell_pulse.clone();
                    a.play_with(&s, rate, -6.0);
                }
            }
            SimEvent::UltReady => {
                let s = a.sfx.ult_ready.clone();
                a.play(&s);
            }
            SimEvent::SwordFired { .. } if a.can("sword", 0.1) => {
                let s = a.sfx.sword.clone();
                a.play(&s);
            }
            SimEvent::CraneStrike { .. } if a.can("crane", 0.08) => {
                let s = a.sfx.crane.clone();
                a.play(&s);
            }
            SimEvent::Strike { fx, .. } => {
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
                    a.play(&s);
                }
            }
            SimEvent::Elite { .. } => {
                let s = a.sfx.warn.clone();
                a.play(&s);
            }
            SimEvent::BossArrived { .. } | SimEvent::Surge => {
                let s = a.sfx.warn_big.clone();
                a.play(&s);
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
                a.play(&s);
            }
            SimEvent::Encounter { .. } => {
                let s = a.sfx.event.clone();
                a.play(&s);
            }
            SimEvent::CritterLooted { .. } => {
                let s = a.sfx.coins.clone();
                a.play(&s);
            }
            SimEvent::RunOver { won } => {
                a.set_mode(MusicMode::None, None);
                let s = if won { a.sfx.victory.clone() } else { a.sfx.defeat.clone() };
                a.play(&s);
            }
            _ => {}
        }
    }
}
