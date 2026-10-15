//! 结算：天明 / 夜未尽、本局数据、构筑、灯油（移植自网页版 lantern/game.js 的 endRun）。
//! 灯油和最好成绩记进存档；跑分和观看回放不记。

use bevy::picking::events::{PointerClick, PointerOver};
use bevy::prelude::*;

use lantern_platform::profile::{NewRecord, Recorded, RunRecord};
use lantern_platform::{Actions, HubNews, Profile};
use lantern_sim::omens::{omen_good, omen_name};
use lantern_sim::{Arsenal, Build, Flow, GameContent, ReplayPlayback, RunSetup, RunState};
use lantern_view::Dawn;
use lantern_view::atlas::AtlasDb;

use crate::choice::spawn_icon;
use crate::describe::{element_color, hex, passive_color};
use crate::skin::Skin;
use crate::transition::InkTransition;
use crate::{CINNABAR, DIM, Fonts, INK, INK_DIM, PAPER, on_paper, overlay_vignette, text};

pub(crate) fn register(app: &mut App) {
    app.init_resource::<ResultsUi>()
        .add_systems(OnEnter(RunState::Over), record)
        .add_systems(Update, (spawn, slide_in, input, highlight).chain().run_if(in_state(RunState::Over)));
}

#[derive(Resource, Default)]
pub(crate) struct ResultsUi {
    selected: usize,
    clicked: Option<usize>,
    hovered: Option<usize>,
    stick: i32,
}

#[derive(Component)]
struct ResultsFocus(usize);

#[derive(Component)]
struct ResultsHint;

/// 进入结算时先记进存档；界面稍后才浮现：倒下时停一会儿，天明时等夜色褪完。
#[derive(Resource)]
pub(crate) struct Pending {
    recorded: Recorded,
    counts: bool,
    /// 还要等多久（现实秒）
    wait: f32,
}

/// 结算界面浮现的动画：底色淡入，纸卷从下面滑上来。
#[derive(Component)]
pub(crate) struct SlideIn {
    t: f32,
    /// 底色最后的不透明度：天明时浅一些，晨光还看得见
    alpha: f32,
}

#[derive(Component)]
struct SlidePanel;

fn record(
    mut commands: Commands,
    content: Res<GameContent>,
    flow: Res<Flow>,
    setup: Res<RunSetup>,
    playback: Option<Res<ReplayPlayback>>,
    mut profile: ResMut<Profile>,
    mut news: ResMut<HubNews>,
    mut ui: ResMut<ResultsUi>,
) {
    *ui = ResultsUi::default();
    let c = &content.0;
    let Some(r) = flow.result.clone() else { return };
    let counts =
        playback.is_none() && !matches!(setup.mode, lantern_sim::RunMode::Bench { .. }) && !setup.god;
    let recorded = if counts {
        let rec = RunRecord { result: &r, tier: setup.tier, attributes: !setup.attributes.is_empty() };
        let before = profile.clone();
        let got = profile.record(c, rec);
        // 回到灯驿时人物会说起这一局带来的变化
        *news = HubNews::after_run(c, &before, &profile, &r, &got);
        if let Err(e) = profile.save() {
            warn!("保存存档失败：{e}");
        }
        got
    } else {
        Recorded::default()
    };
    let bench = matches!(setup.mode, lantern_sim::RunMode::Bench { .. });
    let wait = if bench {
        0.0
    } else if r.won {
        0.7
    } else {
        1.6
    };
    commands.insert_resource(Pending { recorded, counts, wait });
}

fn slide_in(
    time: Res<Time<Real>>,
    mut roots: Query<(&mut SlideIn, &mut BackgroundColor)>,
    mut panels: Query<&mut UiTransform, With<SlidePanel>>,
) {
    for (mut s, mut bg) in &mut roots {
        s.t += time.delta_secs().min(0.1);
        let k = (s.t / 0.6).min(1.0);
        let ease = 1.0 - (1.0 - k).powi(3);
        bg.0.set_alpha(s.alpha * ease);
        for mut tf in &mut panels {
            tf.translation = bevy::ui::Val2::px(0.0, 36.0 * (1.0 - ease));
        }
    }
}

fn mmss(secs: f32) -> String {
    let s = secs.max(0.0) as u32;
    format!("{:02}:{:02}", s / 60, s % 60)
}

fn spawn(
    mut commands: Commands,
    time: Res<Time<Real>>,
    content: Res<GameContent>,
    fonts: Res<Fonts>,
    db: Res<AtlasDb>,
    skin: Res<Skin>,
    flow: Res<Flow>,
    setup: Res<RunSetup>,
    arsenal: Res<Arsenal>,
    build: Res<Build>,
    dawn: Res<Dawn>,
    pending: Option<ResMut<Pending>>,
    profile: Res<Profile>,
    playback: Option<Res<ReplayPlayback>>,
) {
    let Some(mut pending) = pending else { return };
    // 天明：等夜色褪完再开始计时
    if dawn.t.is_some() && dawn.progress() < 1.0 {
        return;
    }
    pending.wait -= time.delta_secs();
    if pending.wait > 0.0 {
        return;
    }
    commands.remove_resource::<Pending>();
    let (recorded, counts) = (std::mem::take(&mut pending.recorded), pending.counts);
    let c = &content.0;
    let Some(r) = flow.result.clone() else { return };
    let boss_name = c.enemies.iter().find(|e| e.boss.is_some()).map_or("夜主", |e| e.name.as_str());
    let sub = if r.endless {
        format!("无尽夜　·　撑了 {}　·　打退「{boss_name}」{} 次", mmss(r.seconds), r.bosses)
    } else if r.won {
        format!("存活 {}　·　击败「{boss_name}」", mmss(r.seconds))
    } else {
        format!("倒在第 {}　·　离天明还有 {}", mmss(r.seconds), mmss(c.run.duration - r.seconds))
    };
    let omen = setup.omen.as_ref().filter(|o| c.omen_index(&o.id).is_some());
    commands
        .spawn((
            DespawnOnExit(RunState::Over),
            GlobalZIndex(20),
            Node {
                position_type: PositionType::Absolute,
                width: percent(100),
                height: percent(100),
                flex_direction: FlexDirection::Column,
                align_items: AlignItems::Center,
                justify_content: JustifyContent::Center,
                row_gap: px(14),
                ..default()
            },
            BackgroundColor(Color::srgba(0.03, 0.04, 0.07, 0.0)),
            SlideIn { t: 0.0, alpha: if r.won { 0.45 } else { 0.8 } },
        ))
        .with_children(|root| {
            root.spawn(overlay_vignette(&skin));
            root.spawn((
                Node {
                    width: px(760),
                    flex_direction: FlexDirection::Column,
                    align_items: AlignItems::Center,
                    padding: UiRect::axes(px(56), px(40)),
                    row_gap: px(12),
                    ..default()
                },
                skin.image("panel"),
                SlidePanel,
                UiTransform::from_translation(bevy::ui::Val2::px(0.0, 36.0)),
            ))
            .with_children(|p| {
                results_body(
                    p, c, &fonts, &db, &skin, &r, &sub, omen, &recorded, counts, &arsenal, &build, &profile,
                );
                if playback.is_none() {
                    result_options(p, &fonts, &skin);
                }
            });
            if playback.is_none() {
                root.spawn((
                    ResultsHint,
                    crate::prompts::hint(
                        &fonts.body,
                        18.0,
                        PAPER,
                        "{nav} 选择　{confirm} 确定　{back} 回灯驿",
                    ),
                ));
                // 手记：本局拾到的旧纸，回去前也能先翻一翻
                root.spawn((
                    Node { padding: UiRect::all(px(8)), ..default() },
                    crate::prompts::hint(&fonts.body, 18.0, PAPER, "{hub} 翻看手记"),
                ))
                .observe(
                    |_: On<PointerClick>, mut reader: ResMut<crate::journals::Reader>| {
                        reader.open = true;
                    },
                );
            } else {
                root.spawn(crate::prompts::hint(&fonts.body, 18.0, PAPER, "{confirm} 回到标题"));
            }
        });
}

fn result_options(p: &mut ChildSpawnerCommands, fonts: &Fonts, skin: &Skin) {
    p.spawn((Node { width: percent(100), height: px(14), ..default() }, skin.image("divider")));
    p.spawn(Node { column_gap: px(24), ..default() }).with_children(|row| {
        for (i, label) in ["回灯驿", "再来一夜"].into_iter().enumerate() {
            let mut button = row.spawn((
                Node {
                    width: px(248),
                    height: px(64),
                    align_items: AlignItems::Center,
                    justify_content: JustifyContent::Center,
                    ..default()
                },
                skin.image("btn"),
            ));
            button.with_children(|b| {
                b.spawn((
                    ResultsFocus(i),
                    Visibility::Hidden,
                    Pickable::IGNORE,
                    Node {
                        position_type: PositionType::Absolute,
                        width: percent(100),
                        height: percent(100),
                        ..default()
                    },
                    skin.image("btn_focus"),
                ));
                b.spawn((Pickable::IGNORE, text(&fonts.title, 32.0, PAPER, label)));
            });
            button.observe(move |click: On<PointerClick>, mut ui: ResMut<ResultsUi>| {
                if click.button == bevy::picking::pointer::PointerButton::Primary {
                    ui.clicked = Some(i);
                }
            });
            button.observe(move |_: On<PointerOver>, mut ui: ResMut<ResultsUi>| ui.hovered = Some(i));
        }
    });
}

#[allow(clippy::too_many_arguments)]
fn results_body(
    p: &mut ChildSpawnerCommands,
    c: &lantern_content::Content,
    fonts: &Fonts,
    db: &AtlasDb,
    skin: &Skin,
    r: &lantern_sim::RunResult,
    sub: &str,
    omen: Option<&lantern_sim::OmenPick>,
    recorded: &Recorded,
    counts: bool,
    arsenal: &Arsenal,
    build: &Build,
    profile: &Profile,
) {
    {
        {
            p.spawn(text(
                &fonts.title,
                96.0,
                if r.won { on_paper(hex("#FFD98A")) } else { CINNABAR },
                if r.won { "天明" } else { "夜未尽" },
            ));
            p.spawn(text(&fonts.body, 20.0, INK, sub));
            let memory = if r.events.contains("qingqiu_left_lantern") {
                "檐下多了一盏灯。青火仍在。"
            } else if r.events.contains("qingqiu_guarded_fire") {
                "那一阵风过去时，小狐没有再往后缩。"
            } else if !r.journals.is_empty() {
                "旧纸收进灯座。回去，慢慢读。"
            } else {
                ""
            };
            if !memory.is_empty() {
                p.spawn(text(&fonts.body, 18.0, INK_DIM, memory));
            }
            if !r.journals.is_empty() {
                let pages = r.journals.iter().map(u8::to_string).collect::<Vec<_>>().join("、");
                p.spawn(text(&fonts.body, 16.0, INK_DIM, &format!("拾回手记 · {pages} 页")));
            }
            if let Some(pick) = omen {
                p.spawn(text(
                    &fonts.body,
                    16.0,
                    INK_DIM,
                    &format!("夜签「{}」　{}", omen_name(c, pick), omen_good(c, pick)),
                ));
            }
            if let Some(rec) = recorded.record {
                let s = match rec {
                    NewRecord::FirstDawn => "首次天明",
                    NewRecord::Kills => "新纪录 · 单局击杀",
                    NewRecord::Survival => "新纪录 · 存活时间",
                    NewRecord::Endless => "新纪录 · 无尽夜最长",
                };
                p.spawn(Node { align_items: AlignItems::Center, column_gap: px(8), ..default() })
                    .with_children(|row| {
                        if let Some(seal) = db.find("ui/seal_record") {
                            row.spawn((
                                Node { width: px(40), height: px(40), ..default() },
                                db.ui_image(seal),
                            ));
                        }
                        row.spawn(text(&fonts.body, 20.0, CINNABAR, s));
                    });
            }
            p.spawn((Node { width: percent(100), height: px(14), ..default() }, skin.image("divider")));
            p.spawn(Node { column_gap: px(16), ..default() }).with_children(|row| {
                for (k, v) in [
                    ("击杀", r.kills.to_string()),
                    ("等级", r.level.to_string()),
                    ("最高连斩", r.best_combo.to_string()),
                    ("进化", r.evolutions.to_string()),
                ] {
                    row.spawn((
                        Node {
                            width: px(128),
                            flex_direction: FlexDirection::Column,
                            align_items: AlignItems::Center,
                            padding: UiRect::all(px(10)),
                            ..default()
                        },
                        skin.image("panel_dark"),
                    ))
                    .with_children(|b| {
                        b.spawn(text(&fonts.body, 14.0, DIM, k));
                        b.spawn(text(&fonts.title, 32.0, PAPER, &v));
                    });
                }
            });
            // 构筑：法器（进化的标星）、心法
            p.spawn(Node { column_gap: px(10), align_items: AlignItems::Center, ..default() }).with_children(
                |row| {
                    for w in &arsenal.0 {
                        let def = &c.weapons[w.def];
                        let name = if w.evolved {
                            format!("ui/icon_{}_evo", def.id)
                        } else {
                            format!("ui/icon_{}", def.id)
                        };
                        spawn_icon(
                            row,
                            db,
                            fonts,
                            Some(&name),
                            &def.icon,
                            element_color(c, def.element),
                            52.0,
                        );
                    }
                    row.spawn(Node { width: px(16), ..default() });
                    for p in &build.passives {
                        let def = &c.passives[p.def];
                        let name = format!("ui/icon_{}", def.id);
                        spawn_icon(
                            row,
                            db,
                            fonts,
                            Some(&name),
                            &def.name,
                            passive_color(c, def.element),
                            36.0,
                        );
                    }
                },
            );
            if counts {
                let [time, kills, win, lamps, bonus] = r.oil_parts;
                let mut detail = format!("存活 +{time} · 击杀 {} → +{kills}", r.kills);
                if win > 0 {
                    detail.push_str(&format!(" · {} +{win}", if r.endless { "夜主" } else { "天明" }));
                }
                if lamps > 0 {
                    detail.push_str(&format!(" · 石灯笼 +{lamps}"));
                }
                if bonus > 0 {
                    detail.push_str(&format!(" · 额外 +{bonus}"));
                }
                p.spawn((Node { width: percent(100), height: px(14), ..default() }, skin.image("divider")));
                p.spawn(Node { align_items: AlignItems::Center, column_gap: px(8), ..default() })
                    .with_children(|row| {
                        if let Some(oil) = db.find("ui/icon_oil") {
                            row.spawn((
                                Node { width: px(44), height: px(44), ..default() },
                                db.ui_image(oil),
                            ));
                        }
                        row.spawn(text(
                            &fonts.title,
                            40.0,
                            on_paper(hex("#FFD98A")),
                            &format!("+{} 灯油", r.oil),
                        ));
                    });
                p.spawn(text(&fonts.body, 15.0, INK_DIM, &detail));
                p.spawn(text(
                    &fonts.body,
                    18.0,
                    on_paper(hex("#E8C27A")),
                    &format!(
                        "带出铜钱 {}　·　点亮石灯笼 {} / 5{}",
                        r.gold,
                        r.lanterns,
                        if r.lamps_complete { "　灯阵完整" } else { "" }
                    ),
                ));
                if !recorded.achievements.is_empty() {
                    let names: Vec<_> =
                        recorded.achievements.iter().map(|&k| c.achievements[k].name.as_str()).collect();
                    p.spawn(text(
                        &fonts.body,
                        18.0,
                        on_paper(hex("#FFD98A")),
                        &format!("达成：{}", names.join("、")),
                    ));
                }
                // 离下一盏心灯还差多少
                let next = c
                    .meta
                    .nodes
                    .iter()
                    .filter_map(|l| profile.meta_cost(c, &l.id).map(|cost| (l, cost)))
                    .min_by_key(|&(_, cost)| cost);
                if let Some((line, cost)) = next {
                    let lv = profile.meta_level(&line.id) + 1;
                    let s = if profile.oil >= cost {
                        format!("灯油 {}　·　可点亮「{}」Lv{lv}（回灯驿找老灯匠）", profile.oil, line.name)
                    } else {
                        format!(
                            "灯油 {}　·　点亮「{}」Lv{lv} 还差 {}",
                            profile.oil,
                            line.name,
                            cost - profile.oil
                        )
                    };
                    p.spawn(text(&fonts.body, 16.0, INK, &s));
                }
            }
        }
    }
}

pub(crate) fn input(
    actions: Res<Actions>,
    playback: Option<Res<ReplayPlayback>>,
    pending: Option<Res<Pending>>,
    slides: Query<&SlideIn>,
    mut ui: ResMut<ResultsUi>,
    mut transition: ResMut<InkTransition>,
    mut reader: ResMut<crate::journals::Reader>,
) {
    let axis = if actions.move_dir.x.abs() >= actions.move_dir.y.abs() {
        actions.move_dir.x
    } else {
        actions.move_dir.y
    };
    let stick = if axis.abs() >= 0.55 { axis.signum() as i32 } else { 0 };
    let stick_pressed = stick != 0 && stick != ui.stick;
    ui.stick = stick;
    // 观看回放由回放界面处理；等纸卷落定才接输入，墨幕期间丢弃鼠标事件。
    if playback.is_some()
        || pending.is_some()
        || reader.open
        || transition.active()
        || !slides.iter().any(|s| s.t >= 0.6)
    {
        ui.clicked = None;
        ui.hovered = None;
        return;
    }
    if actions.meta {
        reader.open = true;
        return;
    }
    if let Some(h) = ui.hovered.take()
        && actions.pointer_moved
    {
        ui.selected = h;
    }
    let nav = if actions.nav.x != 0 { actions.nav.x } else { actions.nav.y };
    let nav = if nav != 0 {
        nav
    } else if stick_pressed {
        stick
    } else {
        0
    };
    if nav != 0 {
        ui.selected = (ui.selected as i32 + nav).rem_euclid(2) as usize;
    }
    let clicked = ui.clicked.take();
    if let Some(i) = clicked {
        ui.selected = i;
    }
    if actions.back {
        transition.return_to_hub();
    } else if actions.confirm || clicked.is_some() {
        if ui.selected == 0 {
            transition.return_to_hub();
        } else {
            transition.retry();
        }
    }
}

fn highlight(ui: Res<ResultsUi>, mut focus: Query<(&ResultsFocus, &mut Visibility)>) {
    for (f, mut v) in &mut focus {
        v.set_if_neq(if f.0 == ui.selected { Visibility::Inherited } else { Visibility::Hidden });
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn input_app() -> App {
        let mut app = App::new();
        app.init_resource::<ResultsUi>()
            .init_resource::<Actions>()
            .init_resource::<InkTransition>()
            .init_resource::<crate::journals::Reader>()
            .add_systems(Update, (input, highlight).chain());
        app.world_mut().spawn(SlideIn { t: 0.6, alpha: 0.8 });
        app
    }

    #[test]
    fn keyboard_stick_and_pointer_share_focus_without_held_input_repeating() {
        let mut app = input_app();
        let focus = app.world_mut().spawn((ResultsFocus(1), Visibility::Hidden)).id();
        app.insert_resource(Actions { nav: IVec2::X, move_dir: Vec2::X, ..default() });
        app.update();
        assert_eq!(app.world().resource::<ResultsUi>().selected, 1);
        assert_eq!(*app.world().get::<Visibility>(focus).unwrap(), Visibility::Inherited);
        app.insert_resource(Actions { move_dir: Vec2::X, ..default() });
        app.update();
        assert_eq!(app.world().resource::<ResultsUi>().selected, 1);
        app.insert_resource(Actions::default());
        app.update();
        app.insert_resource(Actions { move_dir: -Vec2::X, ..default() });
        app.update();
        assert_eq!(app.world().resource::<ResultsUi>().selected, 0);
        app.world_mut().resource_mut::<ResultsUi>().hovered = Some(1);
        app.insert_resource(Actions { pointer_moved: true, ..default() });
        app.update();
        assert_eq!(app.world().resource::<ResultsUi>().selected, 1);
        app.world_mut().resource_mut::<ResultsUi>().clicked = Some(0);
        app.update();
        assert_eq!(app.world().resource::<ResultsUi>().selected, 0);
        assert!(app.world().resource::<InkTransition>().active());
    }

    #[test]
    fn pending_reveal_replay_and_curtain_discard_confirm_and_pointer_events() {
        let mut app = input_app();
        for blocked in 0..4 {
            app.insert_resource(InkTransition::default());
            app.insert_resource(ResultsUi { clicked: Some(1), hovered: Some(1), ..default() });
            app.insert_resource(Actions { confirm: true, pointer_moved: true, ..default() });
            match blocked {
                0 => {
                    app.insert_resource(Pending { recorded: Recorded::default(), counts: true, wait: 1.0 });
                }
                1 => {
                    app.world_mut().query::<&mut SlideIn>().single_mut(app.world_mut()).unwrap().t = 0.1;
                }
                2 => {
                    app.insert_resource(ReplayPlayback::new(lantern_sim::Replay::new(
                        "test",
                        0,
                        RunSetup::new(1, lantern_sim::RunMode::Normal),
                    )));
                }
                _ => app.world_mut().resource_mut::<InkTransition>().return_to_hub(),
            }
            app.update();
            let ui = app.world().resource::<ResultsUi>();
            assert_eq!(ui.selected, 0);
            assert!(ui.clicked.is_none() && ui.hovered.is_none());
            assert_eq!(app.world().resource::<InkTransition>().active(), blocked == 3);
            app.world_mut().remove_resource::<Pending>();
            app.world_mut().remove_resource::<ReplayPlayback>();
            app.world_mut().query::<&mut SlideIn>().single_mut(app.world_mut()).unwrap().t = 0.6;
        }
    }
}
