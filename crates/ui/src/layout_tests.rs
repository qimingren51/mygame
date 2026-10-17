//! 用真实字体和内容做无窗口排版回归，不依赖显卡。

use bevy::camera::{ComputedCameraValues, RenderTargetInfo};
use bevy::ecs::system::RunSystemOnce;
use bevy::prelude::*;
use bevy::window::PrimaryWindow;
use lantern_content::Content;
use lantern_platform::Profile;
use lantern_sim::{Arsenal, Build, Offer};
use lantern_view::{AssetRoot, atlas::AtlasDb};

use crate::{Fonts, choice, responsive, skin, stats_panel, title};

fn setup() -> App {
    let root = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../../assets");
    let mut app = App::new();
    app.add_plugins((
        MinimalPlugins,
        AssetPlugin { file_path: root.to_str().unwrap().to_owned(), ..default() },
        bevy::input::InputPlugin,
        bevy::picking::DefaultPickingPlugins,
        bevy::input_focus::InputFocusPlugin,
        bevy::window::WindowPlugin { primary_window: None, ..default() },
        bevy::image::ImagePlugin::default(),
        bevy::text::TextPlugin,
        bevy::ui::UiPlugin,
    ))
    .init_asset::<TextureAtlasLayout>()
    .insert_resource(AssetRoot(root.clone()))
    .insert_resource(lantern_sim::GameContent(Content::load(&root.join("data")).unwrap().into()));
    responsive::register(&mut app);
    let mut fonts = app.world_mut().resource_mut::<Assets<Font>>();
    let title =
        fonts.add(Font::from_bytes(std::fs::read(root.join("fonts/MaShanZheng-subset.ttf")).unwrap()));
    let body = fonts.add(Font::from_bytes(std::fs::read(root.join("fonts/NotoSerifSC-subset.ttf")).unwrap()));
    app.insert_resource(Fonts { title, body });
    app.world_mut().run_system_once(skin::load_skin).unwrap();
    app.world_mut()
        .run_system_once(
            |mut commands: Commands,
             root: Res<AssetRoot>,
             assets: Res<AssetServer>,
             mut layouts: ResMut<Assets<TextureAtlasLayout>>| {
                commands.insert_resource(AtlasDb::load(&root.0, &assets, &mut layouts).unwrap());
            },
        )
        .unwrap();
    app.world_mut().spawn((Window::default(), PrimaryWindow));
    app.world_mut().spawn(Camera2d);
    app
}

fn assert_fits_after_resize(app: &mut App) {
    for (width, height, dpi) in [
        (1920, 1080, 1.0),
        (1920, 1080, 1.5),
        (1280, 720, 2.0),
        (800, 600, 1.5),
        (640, 360, 2.0),
        (360, 640, 1.0),
        (1920, 1080, 1.0),
    ] {
        let world = app.world_mut();
        let mut window = world.query::<&mut Window>().single_mut(world).unwrap();
        window.resolution.set_physical_resolution(width, height);
        window.resolution.set_scale_factor_override(Some(dpi));
        let mut camera = world.query::<&mut Camera>().single_mut(world).unwrap();
        camera.computed = ComputedCameraValues {
            target_info: Some(RenderTargetInfo {
                physical_size: UVec2::new(width, height),
                scale_factor: dpi,
            }),
            ..default()
        };
        // 字体资源事件先进入排版系统，再检查稳定布局。
        for _ in 0..3 {
            app.update();
        }
        let world = app.world_mut();
        let mut texts = world.query::<(Entity, &Text, &ComputedNode, &UiGlobalTransform)>();
        let mut count = 0;
        for (entity, text, node, transform) in texts.iter(world) {
            if text.0.is_empty() {
                continue;
            }
            count += 1;
            assert!(node.size().min_element() > 0.0, "字的大小无效：{}", text.0);
            let min = transform.transform_point2(-node.size() / 2.0);
            let max = transform.transform_point2(node.size() / 2.0);
            assert!(
                min.cmpge(Vec2::splat(-1.0)).all()
                    && max.cmple(Vec2::new(width as f32, height as f32) + Vec2::ONE).all(),
                "超出窗口：{}，{width}x{height} / {dpi}，{min:?}..{max:?}",
                text.0
            );
            // 文字在窗口内还不够，卡内文字也不能穿出纸面。
            let mut ancestor = entity;
            while let Some(parent) = world.get::<ChildOf>(ancestor) {
                ancestor = parent.parent();
                if world.get::<choice::Card>(ancestor).is_some() {
                    let card = world.get::<ComputedNode>(ancestor).unwrap();
                    let transform = world.get::<UiGlobalTransform>(ancestor).unwrap();
                    let card_min = transform.transform_point2(-card.size() / 2.0);
                    let card_max = transform.transform_point2(card.size() / 2.0);
                    assert!(
                        min.cmpge(card_min - Vec2::ONE).all() && max.cmple(card_max + Vec2::ONE).all(),
                        "超出卡片：{}，{width}x{height} / {dpi}，{min:?}..{max:?}，卡片 {card_min:?}..{card_max:?}",
                        text.0
                    );
                    break;
                }
            }
        }
        assert!(count > 10);
    }
}

#[test]
fn meta_text_fits_after_resize_and_dpi_changes() {
    let mut app = setup();
    app.world_mut()
        .run_system_once(
            |mut commands: Commands,
             c: Res<lantern_sim::GameContent>,
             fonts: Res<Fonts>,
             skin: Res<skin::Skin>,
             db: Res<AtlasDb>| {
                title::meta_panel(&mut commands, &c.0, &fonts, &skin, &db, &Profile::default());
            },
        )
        .unwrap();
    assert_fits_after_resize(&mut app);
}

#[test]
fn four_upgrade_cards_with_notes_and_banish_hint_fit_after_resize() {
    let mut app = setup();
    app.world_mut()
        .run_system_once(
            |mut commands: Commands,
             c: Res<lantern_sim::GameContent>,
             fonts: Res<Fonts>,
             skin: Res<skin::Skin>,
             db: Res<AtlasDb>| {
                let build = Build { points: [c.0.elements.thresholds[0] - 1; 5], tiers: [1; 5], ..default() };
                choice::spawn_level_up(
                    &mut commands,
                    &c.0,
                    &fonts,
                    &db,
                    &skin,
                    &Arsenal::default(),
                    &build,
                    &[Offer::NewWeapon(0), Offer::NewWeapon(1), Offer::NewPassive(0), Offer::NewPassive(1)],
                    true,
                    2,
                    0,
                    3,
                    3,
                );
            },
        )
        .unwrap();
    // 检查入场动画结束后的卡片尺寸。
    let world = app.world_mut();
    for mut transform in world.query_filtered::<&mut UiTransform, With<choice::Card>>().iter_mut(world) {
        *transform = UiTransform::default();
    }
    assert_fits_after_resize(&mut app);
}

#[test]
fn stats_panel_with_every_stat_fits_after_resize() {
    let mut app = setup();
    app.world_mut()
        .run_system_once(
            |mut commands: Commands,
             c: Res<lantern_sim::GameContent>,
             fonts: Res<Fonts>,
             skin: Res<skin::Skin>,
             db: Res<AtlasDb>| {
                let c = &c.0;
                let mut arsenal = Arsenal::default();
                for id in ["lamp", "sword", "bell", "crane", "seal"] {
                    arsenal.0.push(lantern_sim::weapons::WeaponSlot::new(c.weapon_index(id).unwrap()));
                }
                let stats = lantern_sim::Stats::base(c);
                stats_panel::spawn_preview(
                    &mut commands,
                    c,
                    &fonts,
                    &skin,
                    Some(&db),
                    &stats,
                    &arsenal,
                    true,
                );
            },
        )
        .unwrap();
    assert_fits_after_resize(&mut app);
}

#[test]
fn hud_shows_the_omen_and_element_icons_from_the_atlas() {
    let mut app = setup();
    let mut run = lantern_sim::RunSetup::new(1, lantern_sim::RunMode::Normal);
    run.omen = Some(lantern_sim::OmenPick { id: "bloodmoon".into(), element: None });
    app.insert_resource(run);
    app.world_mut().run_system_once(crate::hud::spawn_hud).unwrap();
    app.update();
    let world = app.world_mut();
    let atlas_images = world.query::<&ImageNode>().iter(world).filter(|i| i.texture_atlas.is_some()).count();
    // 夜签一个、五行五个
    assert!(atlas_images >= 6, "{atlas_images}");
    let name = lantern_sim::omens::omen_name(
        &world.resource::<lantern_sim::GameContent>().0,
        &lantern_sim::OmenPick { id: "bloodmoon".into(), element: None },
    );
    assert!(world.query::<&Text>().iter(world).any(|t| t.0 == name));
}

#[test]
fn codex_pages_with_everything_unlocked_fit_after_resize() {
    for page in 0..crate::hub::CODEX_PAGES.len() {
        let mut app = setup();
        app.world_mut()
            .run_system_once(
                move |mut commands: Commands,
                      c: Res<lantern_sim::GameContent>,
                      fonts: Res<Fonts>,
                      skin: Res<skin::Skin>,
                      db: Res<AtlasDb>| {
                    let c = &c.0;
                    let mut profile = Profile::default();
                    profile.reactions = u32::MAX;
                    profile.codex.extend(c.weapons.iter().flat_map(|w| {
                        [format!("w:{}", w.id), format!("w:{}_evo", w.id), format!("w:{}_mut", w.id)]
                    }));
                    profile.codex.extend(c.fusions.iter().map(|f| format!("f:{}", f.id)));
                    profile.codex.extend(c.passives.iter().map(|p| format!("p:{}", p.id)));
                    crate::hub::codex_panel(&mut commands, c, &fonts, &skin, &db, &profile, page);
                },
            )
            .unwrap();
        assert_fits_after_resize(&mut app);
    }
}

/// 锁着的法器照样列在图鉴里，空位上写怎么解锁；它的进化心法写“<新法器>解锁后可得”；拿到过才写名字。
#[test]
fn codex_shows_how_to_unlock_locked_weapons() {
    let root = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../../assets/data");
    let c = Content::load(&root).unwrap();
    let texts = |profile: &Profile, page: usize| {
        let mut app = setup();
        let p = profile.clone();
        app.world_mut()
            .run_system_once(
                move |mut commands: Commands,
                      c: Res<lantern_sim::GameContent>,
                      fonts: Res<Fonts>,
                      skin: Res<skin::Skin>,
                      db: Res<AtlasDb>| {
                    crate::hub::codex_panel(&mut commands, &c.0, &fonts, &skin, &db, &p, page);
                },
            )
            .unwrap();
        let world = app.world_mut();
        world.query::<&Text>().iter(world).map(|t| t.0.clone()).collect::<Vec<_>>()
    };
    let mut profile = Profile::default();
    let weapons = texts(&profile, 1);
    assert!(!weapons.iter().any(|t| t == "铜钱剑"), "没拿到过不写名字");
    assert!(weapons.iter().any(|t| t == "符剑进化或异化后可得"), "{weapons:?}");
    assert!(texts(&profile, 2).iter().any(|t| t == "铜钱剑解锁后可得"));
    // 解锁以后不再写怎么解锁；拿到过写名字
    profile.unlocked.insert("coin_sword".into());
    profile.codex.insert("w:coin_sword".into());
    let weapons = texts(&profile, 1);
    assert!(weapons.iter().any(|t| t == "铜钱剑"));
    assert!(!weapons.iter().any(|t| t == "符剑进化或异化后可得"));
    assert!(!texts(&profile, 2).iter().any(|t| t == "铜钱剑解锁后可得"));
    assert_eq!(c.run.choices.locked.len(), 5);
}

/// 结算报新法器：标题“新法器 · X”，下面一行 weapons.ron 的 unlock；五件同时报也放得下。
#[test]
fn results_list_new_weapons_and_fit() {
    let mut app = setup();
    app.world_mut()
        .run_system_once(
            |mut commands: Commands,
             c: Res<lantern_sim::GameContent>,
             fonts: Res<Fonts>,
             skin: Res<skin::Skin>,
             db: Res<AtlasDb>| {
                let c = &c.0;
                let r = lantern_sim::RunResult {
                    events: Default::default(),
                    journals: Default::default(),
                    won: false,
                    seconds: 300.0,
                    kills: 800,
                    level: 10,
                    best_combo: 0,
                    evolutions: 1,
                    oil: 100,
                    oil_parts: [0; 5],
                    gold: 50,
                    lanterns: 0,
                    lamps_complete: false,
                    feats: Default::default(),
                    endless: false,
                    bosses: 0,
                };
                let recorded = lantern_platform::profile::Recorded {
                    unlocked: c.run.choices.locked.clone(),
                    ..Default::default()
                };
                // 和 results.rs 的结算面板一样：画布按新法器加高，面板 760 宽
                let height = crate::results::RESULTS_HEIGHT
                    + crate::results::UNLOCK_ROW * recorded.unlocked.len() as f32;
                commands
                    .spawn((
                        responsive::FitViewport::Fixed(Vec2::new(1280.0, height)),
                        Node {
                            position_type: PositionType::Absolute,
                            flex_direction: FlexDirection::Column,
                            align_items: AlignItems::Center,
                            justify_content: JustifyContent::Center,
                            ..default()
                        },
                    ))
                    .with_children(|root| {
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
                        ))
                        .with_children(|p| {
                            crate::results::results_body(
                                p,
                                c,
                                &fonts,
                                &db,
                                &skin,
                                &r,
                                "",
                                None,
                                &recorded,
                                true,
                                &Arsenal::default(),
                                &Build::default(),
                                &Profile::default(),
                            );
                            crate::results::result_options(p, &fonts, &skin);
                        });
                    });
            },
        )
        .unwrap();
    let world = app.world_mut();
    let texts: Vec<String> = world.query::<&Text>().iter(world).map(|t| t.0.clone()).collect();
    assert!(texts.iter().any(|t| t == "新法器 · 铜钱剑"), "{texts:?}");
    assert!(texts.iter().any(|t| t == "七枚铜钱成了剑"));
    assert_fits_after_resize(&mut app);
}

/// 信息栏顶部三块（左上头像和血条、中间用时、右上五行和击杀）在各种窗口里都不互相压住，也不出窗口。
#[test]
fn hud_top_clusters_stay_apart_in_every_window() {
    let mut app = setup();
    let mut run = lantern_sim::RunSetup::new(1, lantern_sim::RunMode::Normal);
    run.omen = Some(lantern_sim::OmenPick { id: "bloodmoon".into(), element: None });
    app.insert_resource(run);
    app.world_mut().run_system_once(crate::hud::spawn_hud).unwrap();
    {
        let world = app.world_mut();
        // 按最长的写：一小时、五位数击杀
        for mut t in world.query_filtered::<&mut Text, With<crate::hud::Clock>>().iter_mut(world) {
            t.0 = "59:59".into();
        }
        for mut t in world.query_filtered::<&mut Text, With<crate::hud::Kills>>().iter_mut(world) {
            t.0 = "击杀 99999　铜钱 9999　石灯笼 5/5".into();
        }
    }
    let rect = |world: &mut World, e: Entity| {
        let node = world.get::<ComputedNode>(e).unwrap();
        let tf = world.get::<UiGlobalTransform>(e).unwrap();
        (tf.transform_point2(-node.size() / 2.0), tf.transform_point2(node.size() / 2.0))
    };
    let apart = |a: (Vec2, Vec2), b: (Vec2, Vec2)| {
        a.1.x <= b.0.x || b.1.x <= a.0.x || a.1.y <= b.0.y || b.1.y <= a.0.y
    };
    for (width, height, dpi) in
        [(1280, 720, 1.0), (1920, 1080, 1.0), (1920, 1080, 1.5), (960, 540, 1.0), (640, 360, 1.0)]
    {
        let world = app.world_mut();
        let mut window = world.query::<&mut Window>().single_mut(world).unwrap();
        window.resolution.set_physical_resolution(width, height);
        window.resolution.set_scale_factor_override(Some(dpi));
        let mut camera = world.query::<&mut Camera>().single_mut(world).unwrap();
        camera.computed = ComputedCameraValues {
            target_info: Some(RenderTargetInfo {
                physical_size: UVec2::new(width, height),
                scale_factor: dpi,
            }),
            ..default()
        };
        for _ in 0..3 {
            app.update();
        }
        let world = app.world_mut();
        let clock = single::<crate::hud::Clock>(world);
        let kills = single::<crate::hud::Kills>(world);
        let hp = single::<crate::hud_fx::HpBar>(world);
        let portrait = single::<crate::hud_fx::UltBar>(world);
        let (clock, kills, hp, portrait) =
            (rect(world, clock), rect(world, kills), rect(world, hp), rect(world, portrait));
        let size = format!("{width}x{height} / {dpi}");
        assert!(apart(clock, hp), "用时压住血条：{size}");
        assert!(apart(clock, kills), "用时压住击杀：{size}");
        assert!(apart(kills, hp), "击杀压住血条：{size}");
        let screen = Vec2::new(width as f32, height as f32) + Vec2::ONE;
        for (name, r) in [("用时", clock), ("击杀", kills), ("血条", hp), ("头像", portrait)] {
            assert!(r.0.cmpge(Vec2::splat(-1.0)).all() && r.1.cmple(screen).all(), "{name}出了窗口：{size}");
        }
    }
}

fn single<C: Component>(world: &mut World) -> Entity {
    world.query_filtered::<Entity, With<C>>().single(world).unwrap()
}

/// stat_labels.ron 写的图标在图集里都有（组 `ui/stat_group_*`、属性 `ui/stat_*`），法器组也是。
#[test]
fn stat_icons_named_in_the_data_are_in_the_atlas() {
    let mut app = setup();
    let world = app.world_mut();
    let c = world.resource::<lantern_sim::GameContent>().0.clone();
    let db = world.resource::<AtlasDb>();
    let mut names = vec!["ui/stat_group_weapons".to_string()];
    for g in &c.stat_labels {
        if !g.icon.is_empty() {
            names.push(format!("ui/stat_group_{}", g.icon));
        }
        names.extend(g.stats.iter().filter(|l| !l.icon.is_empty()).map(|l| format!("ui/stat_{}", l.icon)));
    }
    assert!(names.len() >= 19);
    for n in names {
        assert!(db.find(&n).is_some(), "图集里没有 {n}");
    }
}

/// 卡面找图的名字和图集对得上：补给用 lotus、oil 的图标；十件法器本体和进化都有插画，有异化的还有异化插画。
#[test]
fn offer_cards_find_their_icons_and_art_in_the_atlas() {
    let mut app = setup();
    let world = app.world_mut();
    let c = world.resource::<lantern_sim::GameContent>().0.clone();
    let db = world.resource::<AtlasDb>();
    let (arsenal, build) = (Arsenal::default(), Build::default());
    for offer in [Offer::Heal, Offer::Oil] {
        let info = crate::describe::offer_info(&c, &arsenal, &build, offer);
        let icon = info.icon.unwrap();
        assert!(db.find(&icon).is_some(), "图集里没有 {icon}");
    }
    assert_eq!(crate::describe::offer_info(&c, &arsenal, &build, Offer::Heal).art, "ui/card_lotus");
    assert_eq!(c.weapons.len(), 10);
    for (d, w) in c.weapons.iter().enumerate() {
        let info = crate::describe::offer_info(&c, &arsenal, &build, Offer::NewWeapon(d));
        let suffixes: &[&str] = if w.mutation.is_some() { &["", "_evo", "_mut"] } else { &["", "_evo"] };
        for suffix in suffixes {
            assert!(db.find(&format!("{}{suffix}", info.art)).is_some(), "图集里没有 {}{suffix}", info.art);
        }
    }
    // 十件法器都有图标和进化图标；合璧、灯油都有卡面
    let mut names: Vec<String> = c
        .weapons
        .iter()
        .flat_map(|w| [format!("ui/icon_{}", w.id), format!("ui/icon_{}_evo", w.id)])
        .collect();
    names.extend(c.fusions.iter().map(|f| format!("ui/card_{}", f.id)));
    names.push(crate::describe::offer_info(&c, &arsenal, &build, Offer::Oil).art);
    for name in names {
        assert!(db.find(&name).is_some(), "图集里没有 {name}");
    }
}
