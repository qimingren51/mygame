//! 音频层（docs/DESIGN.md 第 10 节）。只读模拟状态和事件、界面的 [`UiCue`] 与 [`MenuSoundscape`]，
//! 不影响模拟。
//!
//! - 用代码合成全部乐器和音效（[`synth`]、[`sfx`]），音乐采样库后台生成，不用音频文件。
//! - 四类总线（[`mixer`]）：音乐、音效、界面、环境各有音量；音效下再分战斗、前景、预警三路，
//!   预警和高光有自己的声部，不被成片的命中挤掉。
//! - 背景音乐（[`music`]）：青丘角调主题与三分钟长曲式，战斗压力驱动分轨，按乐句换配器，天明完整再现。
//!   六条分轨挂在音乐总线下，音量、闪避、变闷和场景混响都作用于它们。
//! - 场所（[`space`]）：标题、灯驿、夜战、夜主各有一种混响，插在各总线上；环境底层（[`ambience`]）
//!   跟着场所交叉淡化。有位置的音效按相对主角的左右做声像、按远近衰减。
//! - 高光闪避（[`duck`]）：燃灯、进化、夜主登场时压低战斗声、音乐和环境；夜主倒下全场静半拍，
//!   接着是一声低锣，天明时编钟和晨鸟。
//! - 命中声（[`impact`]）：按法器分组洗牌轮换纹理，用音频自己的随机流。
//! - 同类声音有最短间隔，几百次命中也不会炸耳朵；战斗和前景再过一个压缩器兜底。濒死时有心跳。

use std::time::Duration;

use bevy::prelude::*;
use kira::clock::ClockSpeed;
use kira::sound::static_sound::StaticSoundData;
use kira::{AudioManager, AudioManagerSettings, Decibels, DefaultBackend, Panning, StartTime};

use lantern_content::WeaponIdentity;
use lantern_core::{Pcg32, step::TICK_HZ};
use lantern_platform::{MenuSoundscape, Settings, UiCue};
use lantern_sim::combat::StrikeFx;
use lantern_sim::enemies::Enemies;
use lantern_sim::pickups::PickupKind;
use lantern_sim::{
    AppState, Director, GameContent, Health, Player, Pos, RunSetup, RunState, SimEvent, SimOutbox, SimPhase,
    Tick,
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
use music::{Music, MusicMode, PressureInput};
use sfx::Sfx;
use space::Scene;
use synth::jiao;

/// 音频的系统都在这里，排在 `PostUpdate`：界面在 `Update` 里写好场所和界面音，模拟事件在
/// `Last` 清空之前读到。
#[derive(SystemSet, Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub struct AudioSystems;

/// 音频私有随机流的序号（命中轮换另用一条）。
const AUDIO_STREAM: u64 = 0x0053_4658;

pub struct AudioPlugin;

impl Plugin for AudioPlugin {
    fn build(&self, app: &mut App) {
        app.add_systems(Startup, init_audio)
            .add_systems(OnEnter(AppState::Title), |time: Res<Time<Real>>, mut a: NonSendMut<Audio>| {
                a.reset();
                a.music.title(time.elapsed_secs_f64());
            })
            .add_systems(OnEnter(AppState::Run), start_run)
            .add_systems(
                PostUpdate,
                (
                    update_audio_time,
                    apply_settings,
                    sync_scene,
                    ambience::update_ambience,
                    play_ui_cues,
                    play_sim_events.run_if(in_state(AppState::Run)),
                    heartbeat.run_if(in_state(AppState::Run)),
                    run_music_mode.run_if(in_state(AppState::Run)),
                    tick_music,
                    update_mix,
                )
                    .chain()
                    .in_set(AudioSystems),
            );
    }
}

/// kira 的后端在部分平台上不能跨线程传递，所以作为 NonSend 资源放在主线程。
pub struct Audio {
    /// 管理器被丢掉时声音就停了，一直留着
    _manager: Option<AudioManager>,
    mixer: Option<Mixer>,
    ducking: Ducking,
    /// 夜主倒下的静半拍：到这个时刻（秒）前景声才回来
    death_silence_until: f64,
    impacts: ImpactPicker,
    /// 音高抖动等用的私有随机流，不碰模拟的随机数
    rng: Pcg32,
    ambience: Ambience,
    scene: Scene,
    /// 下一次心跳的时刻
    next_heart: f64,
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

    fn play_on(&mut self, lane: Lane, sound: StaticSoundData) {
        if let Some(mixer) = &mut self.mixer {
            mixer.play(lane, sound);
        }
    }

    /// 普通战斗声：高光时会被压低。
    fn play(&mut self, sound: &StaticSoundData) {
        self.play_on(Lane::Combat, sound.clone());
    }

    /// 高光与重要提示：不被闪避压低，只让位给夜主倒下的静半拍。
    fn foreground(&mut self, sound: &StaticSoundData) {
        self.foreground_with(sound.clone());
    }

    fn foreground_with(&mut self, sound: StaticSoundData) {
        if self.now >= self.death_silence_until {
            self.play_on(Lane::Foreground, sound);
        }
    }

    /// 危险预警：干声，不过压缩器。
    fn warning(&mut self, sound: StaticSoundData) {
        self.play_on(Lane::Warning, sound);
    }

    /// 界面反馈：近、干、居中，走界面音量。
    fn interface(&mut self, sound: StaticSoundData) {
        self.play_on(Lane::Ui, sound);
    }

    fn play_with(&mut self, sound: &StaticSoundData, rate: f64, volume: f32) {
        self.play_on(Lane::Combat, sound.playback_rate(rate).volume(Decibels(volume)));
    }

    /// 有位置的音效：按左右做声像，远处轻一点。
    fn play_at(&mut self, sound: &StaticSoundData, rate: f64, volume: f32, (pan, far): (f32, f32)) {
        let s = sound.playback_rate(rate).volume(Decibels(volume - far)).panning(Panning(pan));
        self.play_on(Lane::Combat, s);
    }

    /// 过 delay 秒再响。延迟的仪式声走前景，不会被自己触发的闪避压掉起音。
    fn play_later(&mut self, sound: &StaticSoundData, delay: f64) {
        let s = sound.start_time(StartTime::Delayed(Duration::from_secs_f64(delay)));
        self.play_on(Lane::Foreground, s);
    }

    /// lo 到 hi 倍之间随机的音高。
    fn rate(&mut self, lo: f32, hi: f32) -> f64 {
        f64::from(self.rng.range_f32(lo, hi))
    }

    /// 夜主倒下：战斗声、音乐、环境静半拍，已经响着的高光立刻收掉；预警和界面不受影响。
    fn boss_silence(&mut self) {
        self.ducking.trigger(Focus::BossDeath, self.now);
        self.death_silence_until = self.now + 0.55;
        if let Some(mixer) = &mut self.mixer {
            mixer.clear_foreground();
        }
    }

    /// 返回标题或开局：清掉上一处的声音（包括还没响的低锣和晨鸟）、闪避和节流。
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
    let mut mixer = manager.as_mut().and_then(|m| match Mixer::new(m, &settings) {
        Ok(mixer) => Some(mixer),
        Err(e) => {
            warn!("无法建立音频总线，静音运行：{e}");
            None
        }
    });
    let clock = manager.as_mut().and_then(|m| m.add_clock(ClockSpeed::TicksPerSecond(1.0)).ok());
    // 音乐在后台合成，分轨挂在音乐总线下；时钟先走，采样就绪时再确定第一拍的起点。
    let mut music = Music::new(clock, mixer.as_mut().map(|m| &mut m.music));
    music.start_clock();
    world.insert_non_send(Audio {
        _manager: manager,
        mixer,
        ducking: Ducking::default(),
        death_silence_until: 0.0,
        impacts: ImpactPicker::new(1),
        rng: Pcg32::new(1, AUDIO_STREAM),
        ambience: Ambience::new(),
        scene: Scene::Title,
        next_heart: 0.0,
        sfx: Sfx::new(),
        music,
        last: Vec::new(),
        now: 0.0,
        gem_chain: 0,
        gem_last: 0.0,
        muffled: false,
        last_phase: None,
    });
}

fn update_audio_time(time: Res<Time<Real>>, mut audio: NonSendMut<Audio>) {
    audio.now = time.elapsed_secs_f64();
}

/// 设置里的音量变了就跟着改（在 [`update_mix`] 里和闪避一起生效）。
fn apply_settings(settings: Option<Res<Settings>>, mut audio: NonSendMut<Audio>) {
    if let Some(s) = settings
        && s.is_changed()
        && let Some(mixer) = &mut audio.mixer
    {
        mixer.settings(&s);
    }
}

fn start_run(time: Res<Time<Real>>, setup: Option<Res<RunSetup>>, mut audio: NonSendMut<Audio>) {
    let seed = setup.map_or(1, |s| s.seed);
    audio.reset();
    audio.impacts = ImpactPicker::new(seed);
    audio.rng = Pcg32::new(seed, AUDIO_STREAM);
    audio.music.start_run(time.elapsed_secs_f64());
}

/// 场所由状态决定；标题界面里是标题还是灯驿，由界面写在 [`MenuSoundscape`] 里。
fn sync_scene(
    state: Res<State<AppState>>,
    menu: Option<Res<MenuSoundscape>>,
    director: Option<Res<Director>>,
    mut audio: NonSendMut<Audio>,
) {
    let scene = match state.get() {
        AppState::Boot => return,
        AppState::Title if menu.as_deref() == Some(&MenuSoundscape::Hub) => Scene::Hub,
        AppState::Title | AppState::Results => Scene::Title,
        AppState::Run if director.is_some_and(|d| d.boss.is_some()) => Scene::Boss,
        AppState::Run => Scene::Night,
    };
    // 混响和环境声都只在场所变了时才动
    audio.set_scene(scene);
}

/// 界面上的事出声：菜单操作、开场卷轴、灯驿。都走界面总线。
fn play_ui_cues(mut cues: MessageReader<UiCue>, mut audio: NonSendMut<Audio>) {
    let a = &mut *audio;
    let mut menu = None;
    for &cue in cues.read() {
        let sound = match cue {
            // 菜单音一帧只响最后一个，见下
            UiCue::Move | UiCue::Confirm | UiCue::Back => {
                menu = Some(cue);
                continue;
            }
            UiCue::ScrollUnroll => a.sfx.scroll_unroll.clone(),
            // 旁白一行一个音，按配乐的 E 角调往上走（E、G、A、C、D、E）
            UiCue::ScrollLine(k) => {
                const STEPS: [f64; 6] = [0.0, 3.0, 5.0, 8.0, 10.0, 12.0];
                let step = STEPS[usize::from(k).min(STEPS.len() - 1)];
                a.sfx.scroll_line.playback_rate(2f64.powf(step / 12.0)).volume(Decibels(-2.0))
            }
            UiCue::LampLit => a.sfx.lamp_lit.clone(),
            UiCue::DawnSpread => a.sfx.dawn_spread.clone(),
        };
        // 演出声同一帧来几个就响几个（心灯点亮和晨光铺开可能同时）
        a.interface(sound);
    }
    if let Some(cue) = menu
        && a.can("ui", 0.045)
    {
        let s = match cue {
            UiCue::Move => &a.sfx.ui_move,
            UiCue::Confirm => &a.sfx.ui_confirm,
            _ => &a.sfx.ui_back,
        }
        .clone();
        a.interface(s);
    }
}

/// 每 0.2 秒只读一次妖物池，不分配临时列表；压力记忆属于音频，不写回模拟。
fn run_music_mode(
    tick: Option<Res<Tick>>,
    content: Option<Res<GameContent>>,
    enemies: Option<Res<Enemies>>,
    hero: Option<Single<(&Pos, &Health), With<Player>>>,
    director: Option<Res<Director>>,
    phase: Option<Res<SimPhase>>,
    run: Option<Res<State<RunState>>>,
    mut last_sample: Local<f64>,
    mut audio: NonSendMut<Audio>,
) {
    let boss = director.as_ref().is_some_and(|d| d.boss.is_some());
    let over = phase.as_deref() == Some(&SimPhase::Over);
    let menu = phase.as_deref().is_some_and(|p| *p != SimPhase::Play)
        || run.is_some_and(|r| *r.get() != RunState::Playing);
    let dt = audio.now - *last_sample;
    if menu {
        *last_sample = audio.now;
    } else if !over && dt >= 0.2 {
        *last_sample = audio.now;
        if let (Some(en), Some(hero)) = (enemies, hero) {
            let (pos, health) = *hero;
            let nearby = en
                .iter_alive()
                .filter(|&i| {
                    let dx = en.x[i] - pos.0.x;
                    let dy = en.y[i] - pos.0.y;
                    en.hp[i] > 0.0 && en.damage[i] > 0.0 && dx * dx + dy * dy <= 180.0 * 180.0
                })
                .count();
            let seconds = tick.map_or(0.0, |t| t.0 as f32 / TICK_HZ as f32);
            let duration = content.map_or(600.0, |c| c.0.run.duration);
            let input = PressureInput {
                enemies: en.count,
                nearby,
                hp_ratio: health.hp / health.max.max(1.0),
                progress: seconds / duration.max(1.0),
            };
            let mode = audio.music.pressure.update(input, dt.min(0.5) as f32);
            // 妖潮在涌时直接上围攻的配器（行进织体和战鼓），不等压力慢慢升上去
            let surge = director.as_ref().is_some_and(|d| d.surge_t > 0.0);
            audio.music.request(if boss {
                MusicMode::Boss
            } else if surge {
                MusicMode::Siege
            } else {
                mode
            });
        }
    }
    // 天明即使已进入结算，也保留完整频带。
    let muffle = menu && !audio.music.is_dawn();
    audio.muffle(muffle);
    let now = phase.as_deref().copied();
    if audio.last_phase == Some(SimPhase::LevelUp) && now != Some(SimPhase::LevelUp) {
        let s = audio.sfx.select.clone();
        audio.interface(s);
    }
    audio.last_phase = now;
}

fn tick_music(mut audio: NonSendMut<Audio>) {
    let now = audio.now;
    audio.music.tick(now);
}

/// 闪避包络和静半拍换成各总线的音量。
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
    content: Res<GameContent>,
    outbox: Res<SimOutbox>,
    hero: Option<Single<&Pos, With<Player>>>,
    mut audio: NonSendMut<Audio>,
) {
    let hero = hero.map_or(bevy::math::Vec2::ZERO, |p| p.0);
    let space = audio.scene.space();
    // 相对主角的左右声像和远近衰减（分贝），按场所的空间大小
    let place = |p: bevy::math::Vec2| space.place(p - hero);
    let a = &mut *audio;
    if a.now - a.gem_last > 0.6 {
        a.gem_chain = 0;
    }
    // 先汇总整帧的高光再排声音，事件先后不改变闪避结果。天明的仪式只有一次。
    let (mut boss_down, mut dawn) = (false, false);
    for ev in &outbox.0 {
        if let Some(focus) = Focus::for_event(ev) {
            a.ducking.trigger(focus, a.now);
        }
        match *ev {
            SimEvent::BossDefeated { dawn: false, .. } => boss_down = true,
            SimEvent::BossDefeated { dawn: true, .. } | SimEvent::RunOver { won: true } => {
                dawn |= a.music.dawn(a.now);
            }
            _ => {}
        }
    }
    // 夜主倒下：全场静半拍，一声低锣；天明时编钟和晨鸟（无尽夜不天明）
    if boss_down || dawn {
        a.boss_silence();
        let s = a.sfx.boss_down.clone();
        a.play_later(&s, 0.6);
    }
    if dawn {
        let s = a.sfx.dawn.clone();
        a.play_later(&s, 1.6);
    } else if boss_down {
        a.music.request(MusicMode::Explore);
    }
    let mut impact_voices = 0;
    let critical = |e: &&SimEvent| matches!(e, SimEvent::Hit { crit: true, .. });
    for ev in outbox.0.iter().filter(critical).chain(outbox.0.iter().filter(|e| !critical(e))) {
        match *ev {
            SimEvent::Hit { crit, kind, pos, impact_pos, weapon, .. } => {
                if matches!(kind, lantern_sim::HitKind::Dot | lantern_sim::HitKind::Reaction) {
                    continue;
                }
                // 法器命中用各自的三种纹理洗牌轮换；没有法器的（燃灯、爆炸等）用通用命中声
                if let Some(identity) = WeaponIdentity::resolve(&content.0, weapon) {
                    if impact_voices >= 8 {
                        continue;
                    }
                    let (i, key, gap) = sfx::impact_group(identity, crit);
                    if a.can(key, gap) {
                        impact_voices += 1;
                        let pick = a.impacts.weapon(i, crit);
                        let sound = a.sfx.impacts[i][usize::from(crit)][pick.variant].clone();
                        a.play_at(&sound, pick.rate, pick.volume, place(impact_pos));
                    }
                    continue;
                }
                let (name, gap) = if crit { ("crit", 0.06) } else { ("hit", 0.045) };
                if a.can(name, gap) {
                    let pick = a.impacts.generic(crit);
                    let s = if crit { a.sfx.crit.clone() } else { a.sfx.hit.clone() };
                    a.play_at(&s, pick.rate, pick.volume, place(pos));
                }
            }
            SimEvent::Kill { rank: lantern_content::Rank::Elite, pos, .. } => {
                let s = a.sfx.elite_down.clone();
                a.play_at(&s, 1.0, 0.0, place(pos));
            }
            SimEvent::Kill { pos, .. } if a.can("kill", 0.04) => {
                let rate = a.rate(0.85, 1.15);
                let s = a.sfx.kill.clone();
                a.play_at(&s, rate, 0.0, place(pos));
            }
            SimEvent::GemPicked { .. } if a.can("gem", 0.05) => {
                a.gem_last = a.now;
                // 连续拾取时音高一路爬升
                let rate = f64::from(jiao(10 + a.gem_chain % 12) / jiao(10));
                a.gem_chain += 1;
                let s = a.sfx.gem.clone();
                a.play_with(&s, rate, 0.0);
            }
            SimEvent::Dash { .. } => {
                let s = a.sfx.dash.clone();
                a.play(&s);
            }
            SimEvent::PlayerHurt { .. } | SimEvent::Sacrifice { .. } => {
                a.music.pressure.hurt();
                if a.can("hurt", 0.2) {
                    let s = a.sfx.hurt.clone();
                    a.foreground(&s);
                }
            }
            SimEvent::LevelUp { .. } if a.can("level", 0.3) => {
                let s = a.sfx.level_up.clone();
                a.interface(s);
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
                a.interface(s);
            }
            SimEvent::Evolve { form, .. } => {
                // 锣声随异化压低、合璧抬高
                let s = a.sfx.evolution.clone();
                match form {
                    lantern_sim::weapons::Form::Mutated => a.foreground_with(s.playback_rate(0.88)),
                    lantern_sim::weapons::Form::Fused(_) => a.foreground_with(s.playback_rate(1.12)),
                    _ => a.foreground(&s),
                }
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
            SimEvent::UltNotReady if a.can("ult_not_ready", 0.6) => {
                // 复用轻一些、短一些的提示鼓点，连续按键时限制间隔。
                let s = a.sfx.warn.playback_rate(1.4).volume(Decibels(-10.0));
                a.foreground_with(s);
            }
            SimEvent::CoinPicked { .. } if a.can("coin", 0.08) => {
                let s = a.sfx.coins.clone();
                a.play_with(&s, 1.0, -8.0);
            }
            SimEvent::StoryBeat { .. } => {
                // 檐下一声轻响，不盖住正在靠近的妖物。
                let s = a.sfx.event.clone();
                a.play_with(&s, 0.85, -10.0);
            }
            SimEvent::LanternLit { .. } => {
                let s = a.sfx.event.clone();
                a.foreground(&s);
            }
            SimEvent::EncircleWarn { .. } => {
                let s = a.sfx.warn_big.clone();
                a.warning(s);
            }
            SimEvent::VolleyWarn { illusion, .. } if a.can(if illusion { "iwarn" } else { "vwarn" }, 0.1) => {
                let s = a.sfx.volley_warn.volume(Decibels(if illusion { -5.0 } else { 0.0 }));
                a.warning(s);
            }
            SimEvent::SweepWarn { .. } if a.can("swarn", 0.1) => {
                let s = a.sfx.sweep_warn.clone();
                a.warning(s);
            }
            SimEvent::RainWarn { .. } if a.can("rwarn", 0.1) => {
                let s = a.sfx.rain_warn.clone();
                a.warning(s);
            }
            SimEvent::LastStand { .. } | SimEvent::Revived { .. } => {
                let s = a.sfx.big_bell.clone();
                a.foreground(&s);
            }
            SimEvent::CharmTaken { .. } => {
                let s = a.sfx.resonance.clone();
                a.foreground(&s);
            }
            // 夜主换阶段：太鼓、低锣、一声狐啸；配乐在下一个小节线上加一层
            SimEvent::BossPhase { phase } => {
                let s = a.sfx.boss_phase.clone();
                a.foreground(&s);
                let now = a.now;
                a.music.boss_phase(phase, now);
            }
            SimEvent::BossEnraged => {
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
                    let rate = f64::from(jiao(8 + i32::from(kind) % 7) / jiao(8));
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
            SimEvent::Strike { fx, pos, .. } => {
                let (name, gap, sound) = match fx {
                    StrikeFx::Pulse => ("pulse", 0.4, &a.sfx.bell_pulse),
                    StrikeFx::Toll => ("toll", 0.5, &a.sfx.big_bell),
                    StrikeFx::Seal { .. } | StrikeFx::Bamboo => ("seal", 0.12, &a.sfx.seal),
                    StrikeFx::SwordGrove => ("sword_grove", 0.12, &a.sfx.sword),
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
                a.warning(s);
            }
            SimEvent::BossArrived { .. } | SimEvent::Surge => {
                if matches!(ev, SimEvent::BossArrived { .. }) {
                    a.music.request(MusicMode::Boss);
                }
                let s = a.sfx.warn_big.clone();
                a.warning(s);
            }
            // 竹丛打碎：一刀砍倒一片时不要连成一串
            SimEvent::BambooBroken { pos } if a.can("bamboo", 0.07) => {
                let rate = a.rate(0.9, 1.15);
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
            // 赢了的天明在上面统一安排
            SimEvent::RunOver { won: false } => {
                a.music.stop();
                let s = a.sfx.defeat.clone();
                a.foreground(&s);
            }
            _ => {}
        }
    }
}
