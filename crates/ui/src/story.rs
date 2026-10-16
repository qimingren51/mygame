//! 檐下提示与一行余韵，不暂停战斗，不打开剧情弹窗。
use crate::{Fonts, PAPER, text};
use bevy::prelude::*;
use lantern_content::StoryBeat;
use lantern_platform::{Actions, ActiveInput, InputSet, Settings};
use lantern_sim::story::{Story, VillageStage};
use lantern_sim::{AppState, Player, Pos, RunState, SimEvent, SimOutbox, SimPhase};

#[derive(Component)]
struct Whisper;
#[derive(Resource, Default)]
struct Echo {
    words: String,
    left: f32,
}

pub(crate) fn register(app: &mut App) {
    app.init_resource::<Echo>()
        .add_systems(OnEnter(AppState::Run), spawn)
        .add_systems(
            PreUpdate,
            skip.after(InputSet::Gather).before(InputSet::Feed).run_if(in_state(AppState::Run)),
        )
        .add_systems(Update, update.run_if(in_state(AppState::Run)));
}

fn spawn(mut commands: Commands, fonts: Res<Fonts>, mut echo: ResMut<Echo>) {
    *echo = Echo::default();
    commands
        .spawn((
            Whisper,
            DespawnOnExit(AppState::Run),
            GlobalZIndex(4),
            Node {
                position_type: PositionType::Absolute,
                bottom: px(118),
                width: percent(100),
                justify_content: JustifyContent::Center,
                ..default()
            },
        ))
        .with_children(|p| {
            p.spawn(text(&fonts.body, 20.0, PAPER, ""));
        });
}

fn playing(run_state: &State<RunState>, phase: Option<&SimPhase>) -> bool {
    *run_state.get() == RunState::Playing && phase.is_some_and(|p| *p == SimPhase::Play)
}

/// 余韵还亮着时，交互键只用来略过这行字，不送进模拟，免得刚护完火就顺手开始留灯。
fn skip(
    mut actions: ResMut<Actions>,
    mut echo: ResMut<Echo>,
    run_state: Res<State<RunState>>,
    phase: Option<Res<SimPhase>>,
) {
    if actions.interact && echo.left > 0.0 && playing(&run_state, phase.as_deref()) {
        echo.left = 0.0;
        actions.interact = false;
    }
}

#[allow(clippy::too_many_arguments)]
fn update(
    time: Res<Time<Real>>,
    active: Res<ActiveInput>,
    settings: Res<Settings>,
    story: Option<Res<Story>>,
    phase: Option<Res<SimPhase>>,
    run_state: Res<State<RunState>>,
    outbox: Res<SimOutbox>,
    player: Query<&Pos, With<Player>>,
    mut echo: ResMut<Echo>,
    guide: Option<Res<crate::onboarding::Onboarding>>,
    mut roots: Query<(&Children, &mut Node), With<Whisper>>,
    mut texts: Query<(&mut Text, &mut TextColor)>,
) {
    let playing = playing(&run_state, phase.as_deref());
    if playing {
        echo.left = (echo.left - time.delta_secs()).max(0.0);
    }
    for ev in &outbox.0 {
        match ev {
            SimEvent::StoryBeat { beat } => {
                echo.words = match beat {
                    StoryBeat::GuardedFire => "风过去了。最小的那只，松开了攥着屋檐的爪。",
                    StoryBeat::LeftLantern => "你收回手。小狐的影子，留在灯边。",
                }
                .into();
                echo.left = 4.5;
            }
            SimEvent::JournalFound { page } if echo.left <= 0.0 => {
                echo.words = format!("拾回一页旧纸。　手记 · {page}");
                echo.left = 3.0;
            }
            _ => {}
        }
    }
    let prompt = story.as_ref().and_then(|s| s.village.as_ref()).map_or("", |v| {
        let pos = player.iter().next();
        if pos.is_none_or(|p| v.pos.distance_squared(p.0) > 180.0 * 180.0) {
            return "";
        }
        let near = pos.is_some_and(|p| v.near(p.0));
        match (v.stage, near, v.tending) {
            (VillageStage::Guard, true, true) => "护着青火，等这一阵风过去。　走开可中断",
            (VillageStage::Guard, true, false) => "小狐挤在青火下。　{interact}　护着这团火一会儿",
            (VillageStage::Guard, false, _) => "檐下有一点青火。小狐不肯离开。",
            (VillageStage::Leave, true, true) => "俯身，把灯芯拨亮。　走开可中断",
            (VillageStage::Leave, true, false) => "灯还空着。　{interact}　分一缕火，留给它们",
            (VillageStage::Leave, false, _) => "檐下还空着一盏灯。",
            _ => "",
        }
    });
    let template = if !playing {
        String::new()
    } else if echo.left > 0.0 {
        format!("{}　　{{interact}}　略过", echo.words)
    } else {
        prompt.to_string()
    };
    let words = crate::prompts::render(&template, &active, &settings);
    // 首夜引导条亮着时，这行字挪到引导条上方，不叠在一起。
    let bottom = px(if guide.is_some_and(|g| g.in_play()) { 172.0 } else { 118.0 });
    for (children, mut node) in &mut roots {
        if node.bottom != bottom {
            node.bottom = bottom;
        }
        for child in children.iter() {
            if let Ok((mut t, mut color)) = texts.get_mut(child) {
                if t.0 != words {
                    t.0.clone_from(&words);
                }
                color.0 = PAPER.with_alpha(if echo.left > 0.0 { echo.left.min(1.0) } else { 0.85 });
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// 余韵亮着时按交互键只略过字，不把交互送进模拟；字灭了以后照常交互。
    #[test]
    fn interact_skips_the_echo_without_reaching_the_sim() {
        let mut app = App::new();
        app.init_resource::<Actions>()
            .insert_resource(Echo { words: "风过去了。".into(), left: 2.0 })
            .insert_resource(State::new(RunState::Playing))
            .insert_resource(SimPhase::Play)
            .add_systems(Update, skip);
        app.insert_resource(Actions { interact: true, ..default() });
        app.update();
        assert_eq!(app.world().resource::<Echo>().left, 0.0);
        assert!(!app.world().resource::<Actions>().interact);
        app.insert_resource(Actions { interact: true, ..default() });
        app.update();
        assert!(app.world().resource::<Actions>().interact);
    }
}
