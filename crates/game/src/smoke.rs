//! 无窗口、无 GPU、无声卡的发布包冒烟测试；复用正式的内容、图集和资源加载器。

use std::path::Path;
use std::time::{Duration, Instant};

use bevy::asset::{LoadState, UntypedHandle};
use bevy::image::{CompressedImageFormats, ImageLoader};
use bevy::prelude::*;
use bevy::text::FontLoader;

use lantern_content::Content;
use lantern_sim::{InputFrame, harness::SimHarness};
use lantern_view::atlas::AtlasDb;

const FRAMES: u64 = 120;
const LOAD_TIMEOUT: Duration = Duration::from_secs(30);

pub(super) fn run(assets: &Path, file_path: String, content: Content, seed: u64) -> Result<(), String> {
    info!("冒烟测试：无窗口模式，加载资源后运行 {FRAMES} 帧");
    let mut app = App::new();
    app.add_plugins((MinimalPlugins, AssetPlugin { file_path, ..default() }))
        .init_asset::<Image>()
        .register_asset_loader(ImageLoader::new(CompressedImageFormats::NONE))
        .init_asset::<Font>()
        .init_asset_loader::<FontLoader>();
    app.finish();
    app.cleanup();

    let server = app.world().resource::<AssetServer>().clone();
    let atlas = AtlasDb::load(assets, &server, &mut Assets::<TextureAtlasLayout>::default())?;
    let mut handles: Vec<UntypedHandle> = atlas.images().cloned().map(Handle::untyped).collect();
    for font in ["fonts/MaShanZheng-subset.ttf", "fonts/NotoSerifSC-subset.ttf"] {
        handles.push(server.load::<Font>(font).untyped());
    }
    for image in ["atlas/screens/title.png", "atlas/screens/logo.png"] {
        handles.push(server.load::<Image>(image).untyped());
    }
    // 连同皮肤等其余图片一起解码；图集 JSON 由正式图集加载器校验。
    load_images(assets, Path::new("atlas"), &server, &mut handles)?;
    let start = Instant::now();
    loop {
        app.update();
        let mut ready = true;
        for handle in &handles {
            match server.load_state(handle.id()) {
                LoadState::Failed(error) => {
                    return Err(format!("资源 {:?} 加载失败：{error}", handle.path()));
                }
                _ => ready &= server.is_loaded_with_dependencies(handle.id()),
            }
        }
        if ready {
            break;
        }
        if start.elapsed() >= LOAD_TIMEOUT {
            return Err("资源加载超时（30 秒）".into());
        }
        std::thread::sleep(Duration::from_millis(5));
    }

    let mut sim = SimHarness::new(content, seed);
    for _ in 0..FRAMES {
        sim.step(InputFrame::default(), &[]);
        app.update();
    }
    if sim.tick() != FRAMES {
        return Err(format!("模拟只推进了 {} 帧，预期 {FRAMES} 帧", sim.tick()));
    }
    info!("冒烟测试通过：资源加载完成，模拟运行 {FRAMES} 帧");
    Ok(())
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
