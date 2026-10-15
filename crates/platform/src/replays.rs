//! 回放文件的录制与保存（docs/DESIGN.md 第 7、12 节）。
//!
//! 每局都录：开局时插入 [`ReplayLog`]，游戏中每 10 秒把当前回放写到 `replays/current.ron`
//! （万一崩溃，最近的一局也还在），一局结束时存成 `replays/<时间>-<种子>.ron`，只保留最近 20 局。
//! 重放（`--replay`）时不录。

use std::path::{Path, PathBuf};

use bevy::prelude::*;

use lantern_sim::{AppState, GameContent, Replay, ReplayLog, ReplayPlayback, RunSetup};

use crate::paths;
use crate::settings::write_atomic;

const KEEP: usize = 20;
const AUTOSAVE_SECS: f32 = 10.0;

pub fn replay_dir() -> PathBuf {
    paths::data_dir().join("replays")
}

pub(crate) fn register(app: &mut App) {
    app.add_systems(OnEnter(AppState::Run), start_recording)
        .add_systems(OnExit(AppState::Run), finish_recording)
        .add_systems(Update, autosave.run_if(in_state(AppState::Run)));
}

fn start_recording(
    mut commands: Commands,
    setup: Res<RunSetup>,
    content: Res<GameContent>,
    playback: Option<Res<ReplayPlayback>>,
) {
    if playback.is_some() {
        return;
    }
    let replay = Replay::new(env!("CARGO_PKG_VERSION"), content.0.hash, setup.clone());
    commands.insert_resource(ReplayLog(replay));
}

fn autosave(time: Res<Time>, log: Option<Res<ReplayLog>>, mut t: Local<f32>) {
    let Some(log) = log else { return };
    *t += time.delta_secs();
    if *t < AUTOSAVE_SECS {
        return;
    }
    *t = 0.0;
    if let Err(e) = write_atomic(&replay_dir().join("current.ron"), log.0.to_ron().as_bytes()) {
        warn!("自动保存回放失败：{e}");
    }
}

fn finish_recording(mut commands: Commands, log: Option<Res<ReplayLog>>) {
    let Some(log) = log else { return };
    if log.0.ticks == 0 {
        commands.remove_resource::<ReplayLog>();
        return;
    }
    let dir = replay_dir();
    let stamp =
        std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map(|d| d.as_secs()).unwrap_or(0);
    match save_finished_replay(&dir, &log.0, stamp) {
        Ok(path) => {
            commands.remove_resource::<ReplayLog>();
            info!("回放已保存：{}", path.display());
        }
        Err(e) => warn!("保存回放失败：{e}"),
    }
}

fn save_finished_replay(dir: &Path, replay: &Replay, stamp: u64) -> std::io::Result<PathBuf> {
    let path = dir.join(format!("{stamp}-{}.ron", replay.setup.seed));
    write_atomic(&path, replay.to_ron().as_bytes())?;
    let _ = std::fs::remove_file(dir.join("current.ron"));
    let _ = std::fs::remove_file(dir.join("current.bak"));
    prune(dir);
    Ok(path)
}

/// 只保留最近的 KEEP 局（文件名以时间开头，按名字排序即按时间排序）。
fn prune(dir: &std::path::Path) {
    let Ok(entries) = std::fs::read_dir(dir) else { return };
    let mut files: Vec<PathBuf> = entries
        .filter_map(|e| e.ok().map(|e| e.path()))
        .filter(|p| {
            p.extension().is_some_and(|x| x == "ron") && p.file_name().is_some_and(|n| n != "current.ron")
        })
        .collect();
    files.sort();
    let extra = files.len().saturating_sub(KEEP);
    for old in &files[..extra] {
        let _ = std::fs::remove_file(old);
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use lantern_sim::RunMode;

    #[test]
    fn failed_final_save_keeps_recovery_files_until_a_successful_retry() {
        let dir = std::env::temp_dir().join(format!("lantern-replays-test-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();
        let mut replay = Replay::new("test", 0, RunSetup::new(7, RunMode::Normal));
        replay.ticks = 1;
        let current = replay.to_ron();
        std::fs::write(dir.join("current.ron"), &current).unwrap();
        std::fs::write(dir.join("current.bak"), "上一次自动保存").unwrap();
        // 用同名目录让最终替换失败，不依赖权限或磁盘容量。
        let final_path = dir.join("100-7.ron");
        std::fs::create_dir(&final_path).unwrap();
        for i in 0..KEEP + 1 {
            std::fs::write(dir.join(format!("{i:03}-old.ron")), "旧回放").unwrap();
        }

        assert!(save_finished_replay(&dir, &replay, 100).is_err());
        assert_eq!(std::fs::read_to_string(dir.join("current.ron")).unwrap(), current);
        assert_eq!(std::fs::read_to_string(dir.join("current.bak")).unwrap(), "上一次自动保存");
        assert!(dir.join("000-old.ron").exists(), "保存失败也不能裁剪旧回放");

        std::fs::remove_dir(&final_path).unwrap();
        assert_eq!(save_finished_replay(&dir, &replay, 100).unwrap(), final_path);
        assert_eq!(Replay::parse(&std::fs::read_to_string(&final_path).unwrap()).unwrap(), replay);
        assert!(!dir.join("current.ron").exists());
        assert!(!dir.join("current.bak").exists());
        assert!(!dir.join("000-old.ron").exists());
        assert_eq!(std::fs::read_dir(&dir).unwrap().count(), KEEP);
        std::fs::remove_dir_all(dir).unwrap();
    }
}
