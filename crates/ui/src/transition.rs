//! 跨面板、跨场景的墨幕。先盖住旧画面，再切换；目标贴图与渲染管线就绪后揭开。
//! 只用真实时间做演出；遮挡期间停定步循环，不读写模拟数据、随机流或回放命令。

use std::sync::{
    Arc,
    atomic::{AtomicU64, Ordering},
};

use bevy::asset::{LoadState, UntypedAssetId};
use bevy::prelude::*;
use bevy::render::extract_resource::{ExtractResource, ExtractResourcePlugin};
use bevy::render::render_asset::RenderAssets;
use bevy::render::render_resource::{AsBindGroup, PipelineCache};
use bevy::render::texture::GpuImage;
use bevy::render::{Render, RenderApp, RenderSystems};
use bevy::shader::ShaderRef;

use lantern_platform::{Actions, InputSet};
use lantern_sim::{AppState, RunState};
use lantern_view::{SceneAssets, atlas::AtlasDb};

use crate::{
    Fonts,
    scroll::ScrollArt,
    skin::Skin,
    title::{ReturnToHub, TitleMode, TitleUi},
};

const HALF: f32 = 0.24;

enum Destination {
    Page(TitleMode, usize),
    App(AppState),
    Hub,
    Retry,
}

#[derive(Default, Debug, PartialEq)]
enum Phase {
    #[default]
    Idle,
    Closing(f32),
    Covered,
    Switched,
    Waiting,
    Opening(f32),
}

#[derive(Resource, Default)]
pub(crate) struct InkTransition {
    phase: Phase,
    target: Option<Destination>,
}

impl InkTransition {
    pub(crate) fn active(&self) -> bool {
        self.phase != Phase::Idle
    }

    fn request(&mut self, target: Destination) {
        if !self.active() {
            self.target = Some(target);
            self.phase = Phase::Closing(0.0);
        }
    }

    pub(crate) fn page(&mut self, mode: TitleMode, selected: usize) {
        self.request(Destination::Page(mode, selected));
    }

    pub(crate) fn return_to_hub(&mut self) {
        self.request(Destination::Hub);
    }

    pub(crate) fn retry(&mut self) {
        self.request(Destination::Retry);
    }

    fn coverage(&self) -> f32 {
        match self.phase {
            Phase::Idle => 0.0,
            Phase::Closing(t) => t / HALF,
            Phase::Opening(t) => 1.0 - t / HALF,
            _ => 1.0,
        }
    }

    /// 返回 true 时才允许提交状态；卡顿不跳过全遮挡帧或目标首帧。
    fn advance(&mut self, dt: f32, loaded: bool, rendered: bool) -> bool {
        let dt = dt.clamp(0.0, 0.05);
        self.phase = match self.phase {
            Phase::Closing(t) if t + dt >= HALF => Phase::Covered,
            Phase::Closing(t) => Phase::Closing(t + dt),
            Phase::Covered if loaded && rendered => {
                self.phase = Phase::Switched;
                return true;
            }
            Phase::Switched => Phase::Waiting,
            Phase::Waiting if rendered => Phase::Opening(0.0),
            Phase::Opening(t) if t + dt >= HALF => Phase::Idle,
            Phase::Opening(t) => Phase::Opening(t + dt),
            _ => return false,
        };
        false
    }
}

#[derive(Asset, TypePath, AsBindGroup, Clone, Debug)]
struct InkMaterial {
    #[uniform(0)]
    ink: Vec4,
}

impl UiMaterial for InkMaterial {
    fn fragment_shader() -> ShaderRef {
        "shaders/ink_transition.wesl".into()
    }
}

#[derive(Component)]
struct Curtain;

#[derive(Resource)]
struct Preloads {
    files: Vec<UntypedAssetId>,
    images: Vec<AssetId<Image>>,
}

impl Preloads {
    fn new(images: Vec<AssetId<Image>>, fonts: &[AssetId<Font>], server: &AssetServer) -> Self {
        // 粒子会往图集追加程序生成的页；它们没有文件加载状态，只等 GPU 回执。
        let files = images
            .iter()
            .map(|id| id.untyped())
            .filter(|id| server.get_path(*id).is_some())
            .chain(fonts.iter().map(|id| id.untyped()))
            .collect();
        Self { files, images }
    }
}

/// 主线程发出帧序号，渲染线程在该帧真正绘制、纹理上传且管线编译完后回执。
/// 回执带序号，旧场景已就绪的结果不能误放行新场景。
#[derive(Resource, Clone, Default, ExtractResource)]
#[extract_app(RenderApp)]
struct RenderFence {
    serial: u64,
    done: Arc<AtomicU64>,
    images: Vec<AssetId<Image>>,
}

impl RenderFence {
    fn request(&mut self, images: Vec<AssetId<Image>>) {
        self.serial += 1;
        self.images = images;
    }

    fn ready(&self) -> bool {
        self.done.load(Ordering::Acquire) >= self.serial
    }
}

pub(crate) fn register(app: &mut App) {
    app.init_resource::<InkTransition>()
        .init_resource::<RenderFence>()
        .add_plugins((
            UiMaterialPlugin::<InkMaterial>::default(),
            ExtractResourcePlugin::<RenderFence>::default(),
        ))
        .add_systems(PostStartup, setup)
        .add_systems(PreUpdate, block_input.after(InputSet::Gather).before(InputSet::Feed))
        .add_systems(PostUpdate, drive.before(bevy::ui::UiSystems::Prepare))
        .configure_sets(RunFixedMainLoop, RunFixedMainLoopSystems::FixedMainLoop.run_if(idle));
    if let Some(render) = app.get_sub_app_mut(RenderApp) {
        render.add_systems(Render, acknowledge.in_set(RenderSystems::Cleanup));
    }
}

fn idle(transition: Res<InkTransition>) -> bool {
    !transition.active()
}

fn block_input(transition: Res<InkTransition>, mut actions: ResMut<Actions>) {
    if transition.active() {
        *actions = Actions::default();
    }
}

fn setup(
    mut commands: Commands,
    mut materials: ResMut<Assets<InkMaterial>>,
    skin: Res<Skin>,
    art: Res<ScrollArt>,
    db: Res<AtlasDb>,
    scene: Res<SceneAssets>,
    fonts: Res<Fonts>,
    server: Res<AssetServer>,
) {
    let images: Vec<_> = skin
        .images()
        .chain(db.images())
        .chain([&art.night, &art.dawn, &scene.paper])
        .map(Handle::id)
        .collect();
    commands.insert_resource(Preloads::new(images, &[fonts.body.id(), fonts.title.id()], &server));
    // 透明时也参与渲染，标题期间就编译墨幕材质；常驻根节点不随状态销毁。
    commands.spawn((
        Curtain,
        Node {
            position_type: PositionType::Absolute,
            width: percent(100),
            height: percent(100),
            ..default()
        },
        GlobalZIndex(1000),
        Pickable::IGNORE,
        MaterialNode(materials.add(InkMaterial { ink: Vec4::ZERO })),
    ));
}

fn acknowledge(fence: Res<RenderFence>, images: Res<RenderAssets<GpuImage>>, cache: Res<PipelineCache>) {
    if cache.waiting_pipelines().next().is_none() && fence.images.iter().all(|id| images.get(*id).is_some()) {
        fence.done.store(fence.serial, Ordering::Release);
    }
}

fn drive(
    mut commands: Commands,
    time: Res<Time<Real>>,
    state: Res<State<AppState>>,
    mut next: ResMut<NextState<AppState>>,
    next_run: Option<ResMut<NextState<RunState>>>,
    mut transition: ResMut<InkTransition>,
    mut fence: ResMut<RenderFence>,
    preloads: Res<Preloads>,
    assets: Res<AssetServer>,
    mut mode: ResMut<TitleMode>,
    mut ui: ResMut<TitleUi>,
    curtain: Single<(&MaterialNode<InkMaterial>, &mut Pickable), With<Curtain>>,
    mut materials: ResMut<Assets<InkMaterial>>,
) {
    // 所有 Title / Run 出入口统一接住，包括结算、暂停返回、跑分和回放。
    // Boot 的启动跳转照常；真正的场景切换只在下方全遮挡分支提交。
    if *state.get() != AppState::Boot
        && let NextState::Pending(target) = *next
    {
        next.reset();
        if target != *state.get() {
            transition.request(Destination::App(target));
        }
    }
    let loaded = preloads.files.iter().all(|id| assets.is_loaded_with_dependencies(*id));
    if matches!(transition.phase, Phase::Covered)
        && let Some(id) =
            preloads.files.iter().find(|id| matches!(assets.get_load_state(**id), Some(LoadState::Failed(_))))
    {
        // 保留旧界面并收墨，缺图不会让玩家永远困在遮罩中。
        error!("切换画面失败：{id:?}");
        transition.target = None;
        transition.phase = Phase::Opening(0.0);
    }
    let was_closing = matches!(transition.phase, Phase::Closing(_));
    let was_switched = transition.phase == Phase::Switched;
    if transition.advance(time.delta_secs(), loaded, fence.ready())
        && let Some(target) = transition.target.take()
    {
        match target {
            Destination::Page(target, selected) => {
                *mode = target;
                ui.selected = selected;
                ui.clicked = None;
                ui.hovered = None;
                ui.dirty = true;
            }
            Destination::App(target) => next.set(target),
            Destination::Hub => {
                commands.insert_resource(ReturnToHub);
                next.set(AppState::Title);
            }
            Destination::Retry => {
                // Bevy 0.20 的 set 会重入同一状态，完整执行清理、开局与回放归档。
                // 原样保留 RunSetup（含种子），子状态必须显式离开 Over。
                next.set(AppState::Run);
                if let Some(mut next_run) = next_run {
                    next_run.set(RunState::Playing);
                }
            }
        }
    }
    if was_closing && transition.phase == Phase::Covered {
        fence.request(Vec::new());
    } else if was_switched {
        // 到这里 OnEnter 和 Update 的新场景实体才已生成，要求这一帧的新回执。
        fence.request(preloads.images.clone());
    }
    let (material, mut picking) = curtain.into_inner();
    *picking = if transition.active() { Pickable::default() } else { Pickable::IGNORE };
    if let Some(mut material) = materials.get_mut(&material.0) {
        material.ink = Vec4::new(transition.coverage(), time.elapsed_secs(), 0.0, 0.0);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn results_app() -> App {
        use lantern_sim::{GameContent, OmenPick, RunMode, RunSetup, SimPhase, SimPlugin};

        let content = lantern_content::Content::load(
            &std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../../assets/data"),
        )
        .unwrap();
        let mut setup = RunSetup::new(739, RunMode::Endless);
        setup.tier = 2;
        setup.lamp = Some(content.lamps[1].id.clone());
        setup.omen = Some(OmenPick { id: content.omens[0].id.clone(), element: None });
        setup.meta.insert(content.meta.nodes[0].id.clone(), 1);
        setup.attributes.insert(content.attributes.list[0].id.clone(), 1);
        setup.charms.push(content.charms[0].id.clone());
        setup.charm_pool = setup.charms.clone();
        setup.insight = Some(lantern_content::Element::Fire);

        let mut app = App::new();
        app.add_plugins((MinimalPlugins, bevy::state::app::StatesPlugin, AssetPlugin::default(), SimPlugin))
            .insert_resource(bevy::time::TimeUpdateStrategy::ManualDuration(
                std::time::Duration::from_millis(50),
            ))
            .insert_resource(GameContent(Arc::new(content)))
            .insert_resource(setup)
            .init_resource::<InkTransition>()
            .init_resource::<RenderFence>()
            .init_resource::<Assets<InkMaterial>>()
            .init_resource::<TitleMode>()
            .init_resource::<TitleUi>()
            .init_resource::<lantern_platform::Profile>()
            .insert_resource(Preloads { files: Vec::new(), images: Vec::new() })
            .configure_sets(RunFixedMainLoop, RunFixedMainLoopSystems::FixedMainLoop.run_if(idle))
            .add_systems(OnEnter(AppState::Title), crate::title::enter)
            .add_systems(PostUpdate, drive);
        app.world_mut().spawn((Curtain, MaterialNode::<InkMaterial>::default(), Pickable::IGNORE));
        app.world_mut().resource_mut::<NextState<AppState>>().set(AppState::Run);
        app.update();
        app.insert_resource(SimPhase::Over);
        app.world_mut().resource_mut::<NextState<RunState>>().set(RunState::Over);
        app.update();
        app
    }

    fn finish_transition(app: &mut App) {
        for _ in 0..30 {
            app.update();
            // 无窗口测试只代替渲染回执，仍执行真正的墨幕驱动和状态生命周期。
            let fence = app.world().resource::<RenderFence>();
            fence.done.store(fence.serial, Ordering::Release);
            if !app.world().resource::<InkTransition>().active() {
                return;
            }
        }
        panic!("墨幕未结束");
    }

    #[test]
    fn retry_reenters_run_cleans_old_entities_and_preserves_full_setup() {
        use lantern_sim::{Health, Player, Progress, RunSetup, SimPhase, Tick};

        let mut app = results_app();
        let setup = app.world().resource::<RunSetup>().clone();
        let player = app.world_mut().query_filtered::<Entity, With<Player>>().single(app.world()).unwrap();
        app.world_mut().get_mut::<Health>(player).unwrap().hp = 1.0;
        app.world_mut().resource_mut::<Tick>().0 = 999;
        app.world_mut().resource_mut::<Progress>().kills = 123;
        let hud = app.world_mut().spawn(DespawnOnExit(AppState::Run)).id();
        let results = app.world_mut().spawn(DespawnOnExit(RunState::Over)).id();
        app.world_mut().resource_mut::<InkTransition>().retry();
        // 收墨时再次操作不能把重开改成回灯驿。
        app.world_mut().resource_mut::<InkTransition>().return_to_hub();
        finish_transition(&mut app);
        assert_eq!(*app.world().resource::<State<AppState>>().get(), AppState::Run);
        assert_eq!(*app.world().resource::<State<RunState>>().get(), RunState::Playing);
        assert_eq!(*app.world().resource::<SimPhase>(), SimPhase::Play);
        assert_eq!(app.world().resource::<RunSetup>(), &setup);
        assert_eq!(app.world().resource::<Tick>().0, 0);
        assert_eq!(app.world().resource::<Progress>().kills, 0);
        for old in [player, hud, results] {
            assert!(app.world().get_entity(old).is_err());
        }
        let hp = app.world_mut().query_filtered::<&Health, With<Player>>().single(app.world()).unwrap();
        assert_eq!(hp.hp, hp.max);
    }

    #[test]
    fn returning_from_results_enters_hub_and_consumes_the_landing_request() {
        let mut app = results_app();
        app.world_mut().resource_mut::<InkTransition>().return_to_hub();
        finish_transition(&mut app);
        assert_eq!(*app.world().resource::<State<AppState>>().get(), AppState::Title);
        assert_eq!(*app.world().resource::<TitleMode>(), TitleMode::Hub);
        assert!(app.world().resource::<TitleUi>().dirty);
        assert!(!app.world().contains_resource::<ReturnToHub>());
        assert!(!app.world().contains_resource::<State<RunState>>());
        app.world_mut().resource_mut::<NextState<AppState>>().set(AppState::Title);
        app.update();
        assert_eq!(*app.world().resource::<TitleMode>(), TitleMode::Main);
    }

    #[test]
    fn switch_requires_opaque_frame_and_loaded_assets_then_a_new_render() {
        let mut t = InkTransition::default();
        t.page(TitleMode::Prep, 3);
        for _ in 0..5 {
            assert!(!t.advance(0.05, true, true));
        }
        assert_eq!(t.phase, Phase::Covered);
        assert_eq!(t.coverage(), 1.0);
        assert!(!t.advance(0.01, false, true));
        assert!(!t.advance(0.01, true, false));
        assert!(t.advance(0.01, true, true));
        assert!(!t.advance(0.01, true, true));
        assert_eq!(t.phase, Phase::Waiting);
        assert!(!t.advance(2.0, true, false));
        assert_eq!(t.coverage(), 1.0);
        t.advance(0.01, true, true);
        for _ in 0..5 {
            t.advance(0.05, true, true);
        }
        assert!(!t.active());
        assert_eq!(t.coverage(), 0.0);
    }

    #[test]
    fn repeated_input_cannot_replace_destination_or_skip_cover_on_stall() {
        let mut t = InkTransition::default();
        t.page(TitleMode::Prep, 3);
        t.page(TitleMode::Hub, 0);
        assert!(matches!(t.target, Some(Destination::Page(TitleMode::Prep, 3))));
        assert!(!t.advance(2.0, true, true));
        assert!(t.coverage() < 1.0);
    }

    #[test]
    fn previous_render_acknowledgement_cannot_release_new_scene() {
        let mut fence = RenderFence::default();
        fence.request(Vec::new());
        fence.done.store(fence.serial, Ordering::Release);
        assert!(fence.ready());
        fence.request(Vec::new());
        assert!(!fence.ready());
    }

    #[test]
    fn generated_atlas_pages_wait_for_gpu_without_waiting_for_file_load() {
        let mut app = App::new();
        app.add_plugins((MinimalPlugins, bevy::asset::AssetPlugin::default())).init_asset::<Image>();
        let generated = app.world_mut().resource_mut::<Assets<Image>>().add(Image::default());
        let server = app.world().resource::<AssetServer>();
        let file: Handle<Image> = server.load("atlas/paper.png");
        let preloads = Preloads::new(vec![generated.id(), file.id()], &[], server);
        assert_eq!(preloads.files, vec![file.id().untyped()]);
        assert_eq!(preloads.images, vec![generated.id(), file.id()]);
    }

    #[test]
    fn covered_time_neither_advances_fixed_steps_nor_accumulates_catchup() {
        use bevy::time::TimeUpdateStrategy;
        use std::time::Duration;

        #[derive(Resource, Default)]
        struct Steps(u32);

        let mut app = App::new();
        app.add_plugins(MinimalPlugins)
            .init_resource::<InkTransition>()
            .init_resource::<Steps>()
            .insert_resource(TimeUpdateStrategy::ManualDuration(Duration::from_millis(20)))
            .insert_resource(Time::<Fixed>::from_duration(Duration::from_millis(20)))
            .configure_sets(RunFixedMainLoop, RunFixedMainLoopSystems::FixedMainLoop.run_if(idle))
            .add_systems(FixedUpdate, |mut steps: ResMut<Steps>| steps.0 += 1);
        app.update();
        app.update();
        let before = app.world().resource::<Steps>().0;
        assert!(before > 0);
        app.world_mut().resource_mut::<InkTransition>().phase = Phase::Covered;
        for _ in 0..100 {
            app.update();
        }
        assert_eq!(app.world().resource::<Steps>().0, before);
        app.world_mut().resource_mut::<InkTransition>().phase = Phase::Idle;
        app.update();
        assert_eq!(app.world().resource::<Steps>().0, before + 1);
    }
}
