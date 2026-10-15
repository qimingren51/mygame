//! 音频层（docs/DESIGN.md 第 10 节）。只消费模拟事件，不影响模拟。
//!
//! - 启动时用代码合成全部乐器和音效（[`synth`]、[`sfx`]），不用音频文件。
//! - 音效和音乐各走一条轨道，音量来自设置；音乐轨道带低通滤波，升级选择、暂停时变闷。
//! - 背景音乐（[`music`]）：低音持续音 + 按种子生成的五声旋律 + 随局势加强的鼓点；夜主出场后换成更紧的节奏。
//! - 同类声音有最短间隔，几百次命中也不会炸耳朵；音效轨再挂一个压缩器兜底。
//! - 空间感（docs/FEEL.md 第 6 节）：音效和音乐都送一点到混响轨；有位置的音效按相对主角的
//!   左右做声像、按远近衰减。濒死时有心跳；夜主倒下时全场静半拍，接着是天明的编钟和晨鸟。

use std::time::Duration;

use bevy::prelude::*;
use kira::effect::compressor::CompressorBuilder;
use kira::effect::filter::{FilterBuilder, FilterHandle};
use kira::effect::reverb::ReverbBuilder;
use kira::sound::static_sound::StaticSoundData;
use kira::track::{SendTrackBuilder, SendTrackHandle, TrackBuilder, TrackHandle};
use kira::{AudioManager, AudioManagerSettings, Decibels, DefaultBackend, Mix, Panning, StartTime, Tween};

use lantern_content::WeaponIdentity;
use lantern_core::step::TICK_HZ;
use lantern_platform::{Settings, UiCue};
use lantern_sim::combat::StrikeFx;
use lantern_sim::pickups::PickupKind;
use lantern_sim::{
    AppState, Director, Health, Player, Pos, RunSetup, RunState, SimEvent, SimOutbox, SimPhase, Tick,
};

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
                a.muffle(false);
                a.last_phase = None;
                a.set_mode(MusicMode::Title, None);
            })
            .add_systems(OnEnter(AppState::Run), start_run)
            .add_systems(
                Update,
                (
                    apply_settings,
                    play_ui_cues,
                    update_clock,
                    play_sim_events.run_if(in_state(AppState::Run)),
                    heartbeat.run_if(in_state(AppState::Run)),
                    run_music_mode.run_if(in_state(AppState::Run)),
                    tick_music,
                )
                    .chain(),
            );
    }
}

/// 界面上的演出（开场卷轴、灯驿）出声。
fn play_ui_cues(mut cues: MessageReader<UiCue>, mut audio: NonSendMut<Audio>) {
    let a = &mut *audio;
    for cue in cues.read() {
        match *cue {
            UiCue::ScrollUnroll => {
                let s = a.sfx.scroll_unroll.clone();
                a.play(&s);
            }
            // 旁白一行一个音，按五声音阶往上走（D、E、F#、A、B）
            UiCue::ScrollLine(k) => {
                const STEPS: [f64; 6] = [0.0, 2.0, 4.0, 7.0, 9.0, 12.0];
                let step = STEPS[usize::from(k).min(STEPS.len() - 1)];
                let s = a.sfx.scroll_line.clone();
                a.play_with(&s, 2f64.powf(step / 12.0), -2.0);
            }
            UiCue::LampLit => {
                let s = a.sfx.lamp_lit.clone();
                a.play(&s);
            }
            UiCue::DawnSpread => {
                let s = a.sfx.dawn_spread.clone();
                a.play(&s);
            }
        }
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
    /// 混响发送轨（一直留着，否则发送就断了）
    _reverb: Option<SendTrackHandle>,
    /// 设置里的音量（静半拍之后恢复用）
    sfx_vol: f32,
    music_vol: f32,
    /// 静半拍：到这个时刻（秒）恢复音量
    duck_until: Option<f64>,
    /// 下一次心跳的时刻
    next_heart: f64,
    music_filter: Option<FilterHandle>,
    sfx: Sfx,
    music: Music,
    /// 各种音效上次播放的时刻（秒），用于限制间隔
    last: Vec<(&'static str, f64)>,
    now: f64,
    impact_variant: [[usize; 2]; 5],
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

    /// 有位置的音效：按左右做声像，远处轻一点。
    fn play_at(&mut self, sound: &StaticSoundData, rate: f64, volume: f32, (pan, far): (f32, f32)) {
        let s = sound.playback_rate(rate).volume(Decibels(volume - far)).panning(Panning(pan));
        Self::play_on(self.sfx_track.as_mut(), s);
    }

    /// 过 delay 秒再响。
    fn play_later(&mut self, sound: &StaticSoundData, delay: f64) {
        let s = sound.start_time(StartTime::Delayed(Duration::from_secs_f64(delay)));
        Self::play_on(self.sfx_track.as_mut(), s);
    }

    /// 全场静 secs 秒（音效和音乐一起；混响的余音还在大殿里回荡）。
    fn duck(&mut self, secs: f64) {
        let tween = Tween { duration: Duration::from_millis(60), ..default() };
        if let Some(t) = &mut self.sfx_track {
            t.set_volume(Decibels::SILENCE, tween);
        }
        if let Some(t) = &mut self.music_track {
            t.set_volume(Decibels::SILENCE, tween);
        }
        self.duck_until = Some(self.now + secs);
    }

    /// 静完半拍后很快回来，紧接着那一声低锣要有完整的起音。
    fn restore_volume(&mut self) {
        let tween = Tween { duration: Duration::from_millis(80), ..default() };
        let (sfx, music) = (sfx_db(self.sfx_vol), db(self.music_vol));
        if let Some(t) = &mut self.sfx_track {
            t.set_volume(sfx, tween);
        }
        if let Some(t) = &mut self.music_track {
            t.set_volume(music, tween);
        }
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
    let (mut sfx_track, mut music_track, mut music_filter, mut reverb) = (None, None, None, None);
    if let Some(m) = &mut manager {
        // 一个大殿般的混响：余音长、高频收一点
        reverb = m
            .add_send_track(SendTrackBuilder::new().with_effect(
                ReverbBuilder::new().feedback(0.84).damping(0.55).stereo_width(1.0).mix(Mix::WET),
            ))
            .ok();
        let send = reverb.as_ref().map(SendTrackHandle::id);
        let mut sfx = TrackBuilder::new().volume(sfx_db(settings.sfx_volume)).with_effect(
            CompressorBuilder::new()
                .threshold(-10.0)
                .ratio(3.0)
                .attack_duration(Duration::from_millis(4))
                .release_duration(Duration::from_millis(120)),
        );
        let mut music = TrackBuilder::new().volume(db(settings.music_volume));
        music_filter = Some(music.add_effect(FilterBuilder::new().cutoff(18_000.0)));
        if let Some(id) = send {
            sfx = sfx.with_send(id, Decibels(-11.0));
            music = music.with_send(id, Decibels(-9.0));
        }
        sfx_track = m.add_sub_track(sfx).ok();
        music_track = m.add_sub_track(music).ok();
    }
    world.insert_non_send(Audio {
        _manager: manager,
        sfx_track,
        music_track,
        _reverb: reverb,
        sfx_vol: settings.sfx_volume,
        music_vol: settings.music_volume,
        duck_until: None,
        next_heart: 0.0,
        music_filter,
        sfx: Sfx::new(),
        music: Music::new(Instruments::new()),
        last: Vec::new(),
        now: 0.0,
        impact_variant: [[0; 2]; 5],
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
    audio.sfx_vol = s.sfx_volume;
    audio.music_vol = s.music_volume;
    if audio.duck_until.is_some() {
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

fn update_clock(time: Res<Time<Real>>, mut audio: NonSendMut<Audio>) {
    audio.now = time.elapsed_secs_f64();
}

fn tick_music(mut audio: NonSendMut<Audio>) {
    let now = audio.now;
    if audio.duck_until.is_some_and(|t| now >= t) {
        audio.duck_until = None;
        audio.restore_volume();
    }
    let Audio { music, music_track, .. } = &mut *audio;
    music.tick(now, music_track.as_mut());
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
    content: Res<lantern_sim::GameContent>,
    outbox: Res<SimOutbox>,
    hero: Option<Single<&Pos, With<Player>>>,
    mut audio: NonSendMut<Audio>,
) {
    let hero = hero.map_or(bevy::math::Vec2::ZERO, |p| p.0);
    // 相对主角的左右声像和远近衰减（分贝）
    let place = |p: bevy::math::Vec2| {
        let d = p - hero;
        ((d.x / 340.0).clamp(-0.75, 0.75), (d.length() / 420.0 * 6.0).min(9.0))
    };
    let a = &mut *audio;
    if a.now - a.gem_last > 0.6 {
        a.gem_chain = 0;
    }
    let mut impact_voices = 0;
    let critical = |e: &&SimEvent| matches!(e, SimEvent::Hit { crit: true, .. });
    for ev in outbox.0.iter().filter(critical).chain(outbox.0.iter().filter(|e| !critical(e))) {
        match *ev {
            SimEvent::Hit { crit, kind, pos, impact_pos, weapon, .. } => {
                if matches!(kind, lantern_sim::HitKind::Dot | lantern_sim::HitKind::Reaction) {
                    continue;
                }
                if let Some(identity) = WeaponIdentity::resolve(&content.0, weapon) {
                    if impact_voices >= 8 {
                        continue;
                    }
                    let (i, key, gap) = sfx::impact_group(identity, crit);
                    if a.can(key, gap) {
                        impact_voices += 1;
                        let c = usize::from(crit);
                        let v = a.impact_variant[i][c];
                        a.impact_variant[i][c] = (v + 1) % 3;
                        let sound = a.sfx.impacts[i][c][v].clone();
                        let rate = 0.96 + (a.now * 3571.0 + i as f64 * 0.17).fract() * 0.08;
                        a.play_at(&sound, rate, 0.0, place(impact_pos));
                    }
                    continue;
                }
                if crit {
                    if a.can("crit", 0.06) {
                        let rate = 0.94 + (a.now * 3571.0).fract() * 0.12;
                        let s = a.sfx.crit.clone();
                        a.play_at(&s, rate, 0.0, place(pos));
                    }
                } else if a.can("hit", 0.045) {
                    let rate = 0.8 + (a.now * 7919.0).fract() * 0.5;
                    let s = a.sfx.hit.clone();
                    a.play_at(&s, rate, 0.0, place(pos));
                }
            }
            SimEvent::Kill { rank: lantern_content::Rank::Elite, pos, .. } => {
                let s = a.sfx.elite_down.clone();
                a.play_at(&s, 1.0, 0.0, place(pos));
            }
            SimEvent::Kill { pos, .. } if a.can("kill", 0.04) => {
                let rate = 0.85 + (a.now * 104_729.0).fract() * 0.3;
                let s = a.sfx.kill.clone();
                a.play_at(&s, rate, 0.0, place(pos));
            }
            // 夜主倒下：全场静半拍，一声低锣；天明时编钟和晨鸟（无尽夜不天明）
            SimEvent::BossDefeated { dawn, .. } => {
                a.duck(0.55);
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
            // 共鸣跨阶：盖章的闷响 + 钟
            SimEvent::Resonance { .. } if a.can("res", 0.3) => {
                let s = a.sfx.stamp.clone();
                a.play(&s);
                let s = a.sfx.resonance.clone();
                a.play(&s);
            }
            SimEvent::Sheng { .. } | SimEvent::Taiji | SimEvent::Buff { .. } if a.can("res", 0.3) => {
                let s = a.sfx.resonance.clone();
                a.play(&s);
            }
            SimEvent::Ult => {
                let s = a.sfx.ult.clone();
                a.play(&s);
            }
            SimEvent::UltNotReady if a.can("ult_not_ready", 0.6) => {
                // 复用轻一些、短一些的提示鼓点，连续按键时限制间隔。
                let s = a.sfx.warn.clone();
                a.play_with(&s, 1.4, -10.0);
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
            SimEvent::LastStand { .. } | SimEvent::Revived { .. } => {
                let s = a.sfx.big_bell.clone();
                a.play(&s);
            }
            SimEvent::CharmTaken { .. } => {
                let s = a.sfx.resonance.clone();
                a.play(&s);
            }
            SimEvent::BossPhase { .. } => {
                let s = a.sfx.boss_phase.clone();
                a.play(&s);
            }
            SimEvent::BossEnraged => {
                let s = a.sfx.big_bell.clone();
                a.play(&s);
            }
            // 五行反应：第一次发生用盖章的声音，之后每种反应换一个音高
            SimEvent::Reaction { kind, first, pos, .. } => {
                if first {
                    let s = a.sfx.stamp.clone();
                    a.play(&s);
                    let s = a.sfx.resonance.clone();
                    a.play(&s);
                } else if a.can("react", 0.12) {
                    let rate = f64::from(pent(8 + i32::from(kind) % 7) / pent(8));
                    let s = a.sfx.bell_pulse.clone();
                    a.play_at(&s, rate, -6.0, place(pos));
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
                a.play(&s);
            }
            SimEvent::BossArrived { .. } | SimEvent::Surge => {
                let s = a.sfx.warn_big.clone();
                a.play(&s);
            }
            // 竹丛打碎：一刀砍倒一片时不要连成一串
            SimEvent::BambooBroken { pos } if a.can("bamboo", 0.07) => {
                let rate = 0.9 + (a.now * 6007.0).fract() * 0.25;
                let s = a.sfx.bamboo.clone();
                a.play_at(&s, rate, -3.0, place(pos));
            }
            // 狐火烧平结界里的竹丛：跟着夜主登场的警报晚一点着起来
            SimEvent::BambooBurned { .. } => {
                let s = a.sfx.burn.clone();
                a.play_later(&s, 0.3);
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
