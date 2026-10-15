//! 结算：天明 / 夜未尽、本局数据、构筑、灯油（移植自网页版 lantern/game.js 的 endRun）。
//! 灯油和最好成绩记进存档；跑分和观看回放不记。

use bevy::prelude::*;

use lantern_platform::profile::{NewRecord, Recorded, RunRecord};
use lantern_platform::{Actions, HubNews, Profile};
use lantern_sim::omens::{omen_good, omen_name};
use lantern_sim::{AppState, Arsenal, Build, Flow, GameContent, ReplayPlayback, RunSetup, RunState};
use lantern_view::Dawn;
use lantern_view::atlas::AtlasDb;

use crate::choice::spawn_icon;
use crate::describe::{element_color, hex, passive_color};
use crate::skin::Skin;
use crate::{CINNABAR, DIM, Fonts, INK, INK_DIM, PAPER, on_paper, overlay_vignette, text};

pub(crate) fn register(app: &mut App) {
    app.add_systems(OnEnter(RunState::Over), record)
        .add_systems(Update, (spawn, slide_in, input).chain().run_if(in_state(RunState::Over)));
}

/// 进入结算时先记进存档；界面稍后才浮现：倒下时停一会儿，天明时等夜色褪完。
#[derive(Resource)]
struct Pending {
    recorded: Recorded,
    counts: bool,
    /// 还要等多久（现实秒）
    wait: f32,
}

/// 结算界面浮现的动画：底色淡入，纸卷从下面滑上来。
#[derive(Component)]
struct SlideIn {
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
) {
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
                )
            });
            root.spawn(text(&fonts.body, 20.0, PAPER, "Enter / 手柄 A　回到标题"));
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
                        format!("灯油 {}　·　可点亮「{}」Lv{lv}（标题界面按 M）", profile.oil, line.name)
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

fn input(
    actions: Res<Actions>,
    playback: Option<Res<ReplayPlayback>>,
    pending: Option<Res<Pending>>,
    mut next: ResMut<NextState<AppState>>,
) {
    // 观看回放时由回放界面处理；结算还没浮现时不响应，免得倒下时手上的按键直接跳过
    if playback.is_some() || pending.is_some() {
        return;
    }
    if actions.confirm || actions.back {
        next.set(AppState::Title);
    }
}
