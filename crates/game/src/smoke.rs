//! 复用正式启动流程；资源和管线就绪后，提交 120 帧窗口画面再退出。

use std::path::Path;
use std::sync::{
    Arc,
    atomic::{AtomicU32, Ordering},
};
use std::time::{Duration, Instant};

use bevy::asset::{LoadState, UntypedHandle};
use bevy::camera::NormalizedRenderTarget;
use bevy::prelude::*;
use bevy::render::{
    Render, RenderApp, RenderSystems,
    camera::ExtractedCamera,
    extract_resource::{ExtractResource, ExtractResourcePlugin},
    render_asset::RenderAssets,
    render_resource::{CachedPipelineState, PipelineCache, PollType},
    renderer::RenderDevice,
    sync_world::MainEntity,
    texture::GpuImage,
    view::{ViewTarget, window::ExtractedWindow},
};
use bevy::shader::ShaderCacheError;
use bevy::text::FontCx;
use bevy::winit::WinitSettings;

use lantern_platform::diagnostics::fatal;
use lantern_view::{AssetRoot, atlas::AtlasDb};

const FRAMES: u32 = 120;
const TIMEOUT: Duration = Duration::from_secs(120);

#[derive(Resource, Clone)]
pub(super) struct SmokeTest {
    frames: Arc<AtomicU32>,
    start: Instant,
}

impl Default for SmokeTest {
    fn default() -> Self {
        Self { frames: default(), start: Instant::now() }
    }
}

impl SmokeTest {
    fn outcome(&self, exit: AppExit) -> Result<AppExit, String> {
        if exit.is_error() {
            return Ok(exit);
        }
        let frames = self.frames.load(Ordering::Acquire);
        if frames < FRAMES {
            return Err(format!("窗口提前退出，只渲染了 {frames}/{FRAMES} 帧"));
        }
        Ok(AppExit::Success)
    }

    pub(super) fn finish(&self, exit: AppExit) -> AppExit {
        match self.outcome(exit) {
            Ok(AppExit::Success) => {
                info!("冒烟测试通过：初始化完成，窗口渲染 {FRAMES} 帧");
                AppExit::Success
            }
            Ok(exit) => exit,
            Err(error) => fatal(&format!("冒烟测试失败：{error}")),
        }
    }
}

impl Plugin for SmokeTest {
    fn build(&self, app: &mut App) {
        info!("冒烟测试：初始化后渲染 {FRAMES} 帧，超时 {} 秒", TIMEOUT.as_secs());
        app.insert_resource(self.clone())
            // CI 窗口失焦时也持续渲染，不受桌面焦点影响。
            .insert_resource(WinitSettings::continuous())
            .add_plugins(ExtractResourcePlugin::<SmokeAssets>::default())
            .add_systems(PostStartup, load_assets)
            .add_systems(Update, check_progress);
        app.sub_app_mut(RenderApp)
            .insert_resource(self.clone())
            .add_systems(Render, count_presented_frame.in_set(RenderSystems::Cleanup));
    }
}

#[derive(Resource, Clone, ExtractResource, Default)]
#[extract_app(RenderApp)]
struct SmokeAssets {
    handles: Vec<UntypedHandle>,
    ready: bool,
}

fn load_assets(mut commands: Commands, root: Res<AssetRoot>, atlas: Res<AtlasDb>, server: Res<AssetServer>) {
    let mut handles: Vec<_> = atlas.images().cloned().map(Handle::untyped).collect();
    for font in ["fonts/MaShanZheng-subset.ttf", "fonts/NotoSerifSC-subset.ttf"] {
        handles.push(server.load::<Font>(font).untyped());
    }
    for image in ["atlas/screens/title.png", "atlas/screens/logo.png"] {
        handles.push(server.load::<Image>(image).untyped());
    }
    // 连同皮肤等其余图片一起解码；图集 JSON 已由正式图集加载器校验。
    load_images(&root.0, Path::new("atlas"), &server, &mut handles)
        .unwrap_or_else(|error| panic!("冒烟测试失败：{error}"));
    commands.insert_resource(SmokeAssets { handles, ready: false });
}

fn check_progress(
    test: Res<SmokeTest>,
    server: Res<AssetServer>,
    mut assets: ResMut<SmokeAssets>,
    fonts: Res<Assets<Font>>,
    mut font_cx: ResMut<FontCx>,
    mut exit: MessageWriter<AppExit>,
) {
    let mut ready = true;
    for handle in &assets.handles {
        // 粒子图集在 Startup 中生成，没有 AssetServer 加载状态；渲染线程仍需确认其上传完成。
        if handle.path().is_none() {
            continue;
        }
        match server.load_state(handle.id()) {
            LoadState::Failed(error) => {
                exit.write(fatal(&format!("冒烟测试失败：资源 {:?} 加载失败：{error}", handle.path())));
                assets.ready = false;
                return;
            }
            _ => ready &= server.is_loaded_with_dependencies(handle.id()),
        }
        // Bevy 0.20 的字体加载器只读字节，还要确认文字系统成功注册了字体。
        if let Ok(font) = handle.clone().try_typed::<Font>()
            && let Some(font) = fonts.get(font.id())
        {
            if font.alias.is_empty() {
                ready = false;
            } else if font_cx.collection.family_id(&font.alias).is_none() {
                exit.write(fatal(&format!("冒烟测试失败：字体 {:?} 无法解析", handle.path())));
                assets.ready = false;
                return;
            }
        }
    }
    assets.ready = ready;
    if test.start.elapsed() >= TIMEOUT {
        exit.write(fatal(&format!(
            "冒烟测试超时（{} 秒），已渲染 {}/{} 帧",
            TIMEOUT.as_secs(),
            test.frames.load(Ordering::Acquire),
            FRAMES,
        )));
    } else if test.frames.load(Ordering::Acquire) >= FRAMES {
        exit.write(AppExit::Success);
    }
}

fn count_presented_frame(
    test: Res<SmokeTest>,
    assets: Option<Res<SmokeAssets>>,
    pipelines: Res<PipelineCache>,
    images: Res<RenderAssets<GpuImage>>,
    windows: Query<(MainEntity, &ExtractedWindow)>,
    views: Query<(&ExtractedCamera, &ViewTarget)>,
    device: Res<RenderDevice>,
) {
    let Some(assets) = assets.filter(|assets| assets.ready) else { return };
    if test.frames.load(Ordering::Acquire) >= FRAMES {
        return;
    }
    let mut ready = pipelines.pipelines().next().is_some();
    for pipeline in pipelines.pipelines() {
        match &pipeline.state {
            CachedPipelineState::Ok(_) => {}
            CachedPipelineState::Err(
                error @ (ShaderCacheError::ProcessShaderError(_) | ShaderCacheError::CreateShaderModule(_)),
            ) => {
                panic!("冒烟测试失败：渲染管线编译失败：{error}");
            }
            _ => ready = false,
        }
    }
    // CPU 解码完成不等于贴图已上传到渲染设备。
    ready &= assets
        .handles
        .iter()
        .filter_map(|handle| handle.clone().try_typed::<Image>().ok())
        .all(|handle| images.get(handle.id()).is_some());
    // render_system 已提交画面并取走交换链纹理；空转、无相机或表面不可用不算一帧。
    let presented = windows.iter().any(|(entity, window)| {
        window.swap_chain_texture_view.is_some() && window.swap_chain_texture.is_none()
            && views.iter().any(|(camera, target)| {
                matches!(camera.target, Some(NormalizedRenderTarget::Window(window)) if window.entity() == entity)
                    && target.needs_present()
            })
    });
    if ready && presented {
        let frames = test.frames.load(Ordering::Acquire) + 1;
        if frames == 1 {
            info!("冒烟测试：资源和渲染管线就绪，开始统计窗口画面");
        }
        if frames == FRAMES {
            device
                .poll(PollType::Wait { submission_index: None, timeout: Some(Duration::from_secs(10)) })
                .unwrap_or_else(|error| panic!("冒烟测试失败：等待渲染完成失败：{error}"));
        }
        test.frames.store(frames, Ordering::Release);
    }
}

fn load_images(
    assets: &Path,
    relative: &Path,
    server: &AssetServer,
    handles: &mut Vec<UntypedHandle>,
) -> Result<(), String> {
    let dir = assets.join(relative);
    let entries = std::fs::read_dir(&dir).map_err(|e| format!("读取 {} 失败：{e}", dir.display()))?;
    for entry in entries {
        let entry = entry.map_err(|e| format!("读取 {} 失败：{e}", dir.display()))?;
        let path = relative.join(entry.file_name());
        let kind = entry.file_type().map_err(|e| format!("读取 {} 失败：{e}", path.display()))?;
        if kind.is_dir() {
            load_images(assets, &path, server, handles)?;
        } else if path.extension().is_some_and(|ext| ext == "png") {
            handles.push(server.load::<Image>(path).untyped());
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn main_updates_cannot_replace_rendered_frames() {
        let test = SmokeTest::default();
        let mut app = App::new();
        app.add_plugins((MinimalPlugins, AssetPlugin::default()))
            .insert_resource(test.clone())
            .init_resource::<SmokeAssets>()
            .init_asset::<Image>()
            .init_asset::<Font>()
            .init_resource::<FontCx>()
            .add_systems(Update, check_progress);
        let image = app.world_mut().resource_mut::<Assets<Image>>().add(Image::default());
        app.world_mut().resource_mut::<SmokeAssets>().handles.push(image.untyped());
        for _ in 0..FRAMES {
            app.update();
        }
        assert!(app.should_exit().is_none());
        assert!(app.world().resource::<SmokeAssets>().ready);
        test.frames.store(FRAMES - 1, Ordering::Release);
        app.update();
        assert!(app.should_exit().is_none());
        test.frames.store(FRAMES, Ordering::Release);
        app.update();
        assert_eq!(app.should_exit(), Some(AppExit::Success));
    }

    #[test]
    fn early_exit_and_failure_cannot_pass() {
        let test = SmokeTest::default();
        assert!(test.outcome(AppExit::Success).unwrap_err().contains("窗口提前退出"));
        test.frames.store(FRAMES, Ordering::Release);
        assert_eq!(test.outcome(AppExit::Success).unwrap(), AppExit::Success);
        assert!(test.outcome(AppExit::error()).unwrap().is_error());
    }
}
