//! 首夜轻提示。只读模拟状态与事件，不暂停、不改难度、不向模拟发额外命令。

use bevy::prelude::*;
use lantern_platform::profile::OnboardingProgress;
use lantern_platform::{AutoPilot, Profile};
use lantern_sim::{
    AppState, Flow, InputFrame, Player, Pos, Progress, ReplayPlayback, RunMode, RunSetup, RunState,
    SimCommand, SimCommands, SimEvent, SimOutbox, SimPhase, SimSet, Tick,
};

use crate::prompts::Prompt;
use crate::skin::Skin;
use crate::{Fonts, PAPER, text};

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum Lesson {
    Move,
    Dash,
    Ult,
    Upgrade,
}

#[derive(Resource, Default)]
struct Onboarding {
    active: bool,
    last_pos: Option<Vec2>,
    distance: f32,
    expected_choice: Option<u32>,
    upgraded: bool,
    shown: Option<Lesson>,
    age: f32,
    alpha: f32,
}

#[derive(Component)]
struct Guide;
#[derive(Component)]
struct GuideText;

pub(crate) fn register(app: &mut App) {
    app.init_resource::<Onboarding>()
        .add_systems(OnEnter(AppState::Run), start)
        .add_systems(
            FixedUpdate,
            (before_choice.before(SimSet::Input), after_choice.after(SimSet::Input))
                .run_if(in_state(RunState::Playing))
                .run_if(resource_exists::<Flow>),
        )
        .add_systems(Update, update.run_if(in_state(AppState::Run)).run_if(resource_exists::<SimPhase>));
}

fn eligible(profile: &Profile, setup: &RunSetup, replay: bool, automatic: bool) -> bool {
    profile.runs == 0
        && !profile.onboarding.complete()
        && !replay
        && !automatic
        && !setup.god
        && !matches!(setup.mode, RunMode::Bench { .. })
}

fn start(
    mut commands: Commands,
    fonts: Res<Fonts>,
    skin: Res<Skin>,
    profile: Res<Profile>,
    setup: Res<RunSetup>,
    replay: Option<Res<ReplayPlayback>>,
    auto: Option<Res<AutoPilot>>,
    mut guide: ResMut<Onboarding>,
) {
    *guide = Onboarding { active: eligible(&profile, &setup, replay.is_some(), auto.is_some()), ..default() };
    commands
        .spawn((
            Guide,
            DespawnOnExit(AppState::Run),
            GlobalZIndex(12),
            Visibility::Hidden,
            Pickable::IGNORE,
            Node {
                position_type: PositionType::Absolute,
                left: percent(26),
                right: percent(26),
                bottom: px(86),
                min_height: px(72),
                padding: UiRect::axes(px(24), px(14)),
                align_items: AlignItems::Center,
                justify_content: JustifyContent::Center,
                ..default()
            },
            skin.image("toast"),
        ))
        .with_child((GuideText, Pickable::IGNORE, Prompt(String::new()), text(&fonts.body, 19.0, PAPER, "")));
}

// 升级确认只有经过模拟接受后才记为学会。重抽、封印和跳过都不计。
fn before_choice(
    mut guide: ResMut<Onboarding>,
    phase: Res<SimPhase>,
    flow: Res<Flow>,
    commands: Res<SimCommands>,
) {
    guide.expected_choice = if guide.active && *phase == SimPhase::LevelUp {
        flow.choice
            .as_ref()
            .filter(|choice| {
                commands
                    .0
                    .iter()
                    .any(|cmd| matches!(cmd, SimCommand::Choose(i) if (*i as usize) < choice.offers.len()))
            })
            .map(|choice| choice.level)
    } else {
        None
    };
}

fn after_choice(mut guide: ResMut<Onboarding>, phase: Res<SimPhase>, flow: Res<Flow>) {
    if let Some(level) = guide.expected_choice.take()
        && (*phase != SimPhase::LevelUp || flow.choice.as_ref().is_none_or(|c| c.level != level))
    {
        guide.upgraded = true;
    }
}

fn lesson(progress: OnboardingProgress, phase: SimPhase, seconds: f32, ult_ready: bool) -> Option<Lesson> {
    if phase == SimPhase::LevelUp && !progress.upgrade {
        return Some(Lesson::Upgrade);
    }
    if phase != SimPhase::Play {
        return None;
    }
    if !progress.movement {
        return Some(Lesson::Move);
    }
    if ult_ready && !progress.ult {
        return Some(Lesson::Ult);
    }
    if seconds >= 7.0 && !progress.dash {
        return Some(Lesson::Dash);
    }
    None
}

fn update(
    time: Res<Time<Real>>,
    run: Res<State<RunState>>,
    phase: Res<SimPhase>,
    tick: Res<Tick>,
    progress: Res<Progress>,
    input: Res<InputFrame>,
    player: Query<&Pos, With<Player>>,
    outbox: Res<SimOutbox>,
    mut profile: ResMut<Profile>,
    mut guide: ResMut<Onboarding>,
    mut panels: Query<(&mut Visibility, &mut ImageNode, &mut Node), With<Guide>>,
    mut labels: Query<(&mut Prompt, &mut TextColor), With<GuideText>>,
) {
    let playing = *run.get() == RunState::Playing;
    if guide.active && playing {
        let before = profile.onboarding;
        if let Ok(pos) = player.single() {
            if let Some(last) = guide.last_pos
                && *phase == SimPhase::Play
                && input.dir() != Vec2::ZERO
            {
                guide.distance += pos.0.distance(last).min(20.0);
            }
            guide.last_pos = Some(pos.0);
        }
        if guide.distance >= 55.0 {
            profile.onboarding.movement = true;
        }
        for event in &outbox.0 {
            match event {
                SimEvent::Dash { .. } => profile.onboarding.dash = true,
                SimEvent::Ult => profile.onboarding.ult = true,
                _ => {}
            }
        }
        profile.onboarding.upgrade |= guide.upgraded;
        if before != profile.onboarding
            && let Err(e) = profile.save()
        {
            warn!("保存首夜引导进度失败：{e}");
        }
        if profile.onboarding.complete() {
            guide.active = false;
        }
    }
    let want = (guide.active && playing)
        .then(|| lesson(profile.onboarding, *phase, tick.secs(), progress.ult >= 1.0))
        .flatten();
    if want != guide.shown {
        guide.shown = want;
        guide.age = 0.0;
        guide.alpha = 0.0;
    }
    guide.age += time.delta_secs().min(0.1);
    // 每个情境最多亮十秒；玩家可自然尝试，提示不会常驻压住战场。
    let visible = want.is_some() && guide.age < 10.0;
    let target = if visible { 1.0 } else { 0.0 };
    guide.alpha += (target - guide.alpha) * (time.delta_secs() * 8.0).min(1.0);
    for (mut visibility, mut image, mut node) in &mut panels {
        *visibility = if guide.alpha > 0.01 && playing { Visibility::Inherited } else { Visibility::Hidden };
        image.color.set_alpha(guide.alpha * 0.92);
        node.bottom = px(if want == Some(Lesson::Upgrade) { 32.0 } else { 86.0 });
    }
    for (mut prompt, mut color) in &mut labels {
        prompt.0 = match guide.shown {
            Some(Lesson::Move) => "初入长夜　·　{move} 移动，法器会自动迎敌",
            Some(Lesson::Dash) => "借一步风　·　{dash} 闪避，穿过包围",
            Some(Lesson::Ult) => "灯焰蓄满　·　{ult} 燃灯，驱散近身妖物",
            Some(Lesson::Upgrade) => "拾光成术　·　{nav} 看卡，{confirm} 选一门法器或心法",
            None => "",
        }
        .into();
        color.0 = PAPER.with_alpha(guide.alpha);
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn contextual_lessons_do_not_interrupt_other_panels() {
        let mut p = OnboardingProgress::default();
        assert_eq!(lesson(p, SimPhase::Play, 0.0, false), Some(Lesson::Move));
        p.movement = true;
        assert_eq!(lesson(p, SimPhase::Play, 3.0, false), None);
        assert_eq!(lesson(p, SimPhase::Play, 8.0, false), Some(Lesson::Dash));
        assert_eq!(lesson(p, SimPhase::Play, 8.0, true), Some(Lesson::Ult));
        assert_eq!(lesson(p, SimPhase::LevelUp, 8.0, true), Some(Lesson::Upgrade));
        assert_eq!(lesson(p, SimPhase::Shop, 8.0, true), None);
        assert_eq!(lesson(OnboardingProgress::completed(), SimPhase::Play, 60.0, true), None);
    }

    #[test]
    fn only_first_normal_night_is_eligible() {
        let mut profile = Profile::default();
        let setup = RunSetup::new(1, RunMode::Normal);
        assert!(eligible(&profile, &setup, false, false));
        assert!(!eligible(&profile, &setup, true, false));
        assert!(!eligible(&profile, &setup, false, true));
        profile.runs = 1;
        assert!(!eligible(&profile, &setup, false, false));
        profile.runs = 0;
        profile.onboarding = OnboardingProgress::completed();
        assert!(!eligible(&profile, &setup, false, false));
    }
    #[test]
    fn upgrade_lesson_waits_for_simulation_and_ignores_skip_or_invalid_choice() {
        use lantern_sim::{GameContent, Offer, SimPlugin};
        use std::{path::Path, sync::Arc};
        let content =
            lantern_content::Content::load(&Path::new(env!("CARGO_MANIFEST_DIR")).join("../../assets/data"))
                .unwrap();
        let mut app = App::new();
        app.add_plugins((bevy::state::app::StatesPlugin, SimPlugin))
            .insert_resource(GameContent(Arc::new(content)))
            .insert_resource(RunSetup::new(1, RunMode::Normal))
            .insert_resource(Onboarding { active: true, ..default() })
            .add_systems(
                FixedUpdate,
                (before_choice.before(SimSet::Input), after_choice.after(SimSet::Input)),
            );
        app.world_mut().resource_mut::<NextState<AppState>>().set(AppState::Run);
        app.world_mut().run_schedule(StateTransition);
        for (command, learned) in
            [(SimCommand::Skip, false), (SimCommand::Choose(9), false), (SimCommand::Choose(0), true)]
        {
            *app.world_mut().resource_mut::<SimPhase>() = SimPhase::LevelUp;
            app.world_mut().resource_mut::<Flow>().choice = Some(lantern_sim::flow::Choice {
                offers: vec![Offer::NewPassive(0)],
                inspired: false,
                level: 2,
                ember: false,
            });
            app.world_mut().resource_mut::<SimCommands>().0.push(command);
            assert!(!app.world().resource::<Onboarding>().upgraded);
            app.world_mut().run_schedule(FixedUpdate);
            assert_eq!(app.world().resource::<Onboarding>().upgraded, learned);
        }
    }
}
