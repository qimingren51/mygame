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
             skin: Res<skin::Skin>| {
                let c = &c.0;
                let mut arsenal = Arsenal::default();
                for id in ["lamp", "sword", "bell", "crane", "seal"] {
                    arsenal.0.push(lantern_sim::weapons::WeaponSlot::new(c.weapon_index(id).unwrap()));
                }
                let stats = lantern_sim::Stats::base(c);
                stats_panel::spawn_preview(&mut commands, c, &fonts, &skin, &stats, &arsenal, true);
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
