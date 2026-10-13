//! 檐下提示与一行余韵，不暂停战斗，不打开剧情弹窗。
use crate::{Fonts, PAPER, text};
use bevy::prelude::*;
use lantern_content::StoryBeat;
use lantern_platform::Actions;
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
fn update(
    time: Res<Time<Real>>,
    actions: Res<Actions>,
    story: Option<Res<Story>>,
    phase: Option<Res<SimPhase>>,
    run_state: Res<State<RunState>>,
    outbox: Res<SimOutbox>,
    player: Query<&Pos, With<Player>>,
    mut echo: ResMut<Echo>,
    roots: Query<&Children, With<Whisper>>,
    mut texts: Query<(&mut Text, &mut TextColor)>,
) {
    let playing = *run_state.get() == RunState::Playing && phase.is_some_and(|p| *p == SimPhase::Play);
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
    if playing && actions.banish {
        echo.left = 0.0;
    }
    let prompt = story.as_ref().and_then(|s| s.village.as_ref()).map_or("", |v| {
        let pos = player.iter().next();
        if pos.is_none_or(|p| v.pos.distance_squared(p.0) > 180.0 * 180.0) {
            return "";
        }
        let near = pos.is_some_and(|p| v.near(p.0));
        match (v.stage, near, v.tending) {
            (VillageStage::Guard, true, true) => "护着青火，等这一阵风过去。　走开可中断",
            (VillageStage::Guard, true, false) => "小狐挤在青火下。　G / 手柄 X　护着这团火一会儿",
            (VillageStage::Guard, false, _) => "檐下有一点青火。小狐不肯离开。",
            (VillageStage::Leave, true, true) => "俯身，把灯芯拨亮。　走开可中断",
            (VillageStage::Leave, true, false) => "石灯还空着。　G / 手柄 X　分一缕火，留给它们",
            (VillageStage::Leave, false, _) => "檐下还空着一盏石灯。",
            _ => "",
        }
    });
    let echo_words = format!("{}　　C / 手柄 LB　略过", echo.words);
    let words = if !playing {
        ""
    } else if echo.left > 0.0 {
        &echo_words
    } else {
        prompt
    };
    for children in &roots {
        for child in children.iter() {
            if let Ok((mut t, mut color)) = texts.get_mut(child) {
                if t.0 != words {
                    t.0 = words.into();
                }
                color.0 = PAPER.with_alpha(if echo.left > 0.0 { echo.left.min(1.0) } else { 0.85 });
            }
        }
    }
}
