//! 资源目录与数据目录。

use std::path::PathBuf;

/// 资源根目录，按顺序查找：
/// 1. 环境变量 `LANTERN_ASSETS`；
/// 2. 通过 `cargo run` 运行时，仓库根目录的 `assets/`；
/// 3. 从可执行文件所在目录往上逐级找含有 `data/` 的 `assets/`：
///    发布版就在程序旁边，开发时直接运行 `target/debug/lantern` 会找到仓库根目录的。
pub fn asset_dir() -> PathBuf {
    if let Some(dir) = std::env::var_os("LANTERN_ASSETS") {
        return PathBuf::from(dir);
    }
    if let Some(manifest) = std::env::var_os("CARGO_MANIFEST_DIR") {
        // cargo run 时这是 crates/game
        return PathBuf::from(manifest).join("../../assets");
    }
    let exe = std::env::current_exe().ok();
    exe.as_deref()
        .and_then(|exe| {
            exe.ancestors().skip(1).map(|dir| dir.join("assets")).find(|a| a.join("data").is_dir())
        })
        .unwrap_or_else(|| PathBuf::from("assets"))
}

/// 存档、设置、回放所在目录。
/// Linux：`~/.local/share/lantern/`；Windows：`%APPDATA%\lantern\data\`。
/// 取不到系统目录时退回到当前目录下的 `lantern-data/`。
pub fn data_dir() -> PathBuf {
    directories::ProjectDirs::from("", "", "lantern")
        .map(|d| d.data_dir().to_path_buf())
        .unwrap_or_else(|| PathBuf::from("lantern-data"))
}

/// 日志目录：Windows 为 `%APPDATA%\lantern\logs`，其他平台为数据目录下的 `logs`。
pub fn log_dir() -> PathBuf {
    #[cfg(windows)]
    if let Some(dirs) = directories::BaseDirs::new() {
        return dirs.data_dir().join("lantern").join("logs");
    }
    data_dir().join("logs")
}
