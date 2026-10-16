//! 资源目录与数据目录。

use std::path::{Path, PathBuf};

/// 返回规范化的绝对资源根目录；失败时列出尝试过的路径，由启动入口调用 fatal。按顺序：
/// 1. 环境变量 `LANTERN_ASSETS`（明确指定，无效时直接报错，不悄悄换一套资源）；
/// 2. 可执行文件旁的 `assets/`（发布包）；
/// 3. `cargo run`（含 `--release`）时仓库根目录的 `assets/`；
/// 4. 只在调试构建或 dev 特性下：编译时的仓库目录、工作目录下的 `assets/`。
pub fn asset_dir() -> Result<PathBuf, String> {
    let exe = std::env::current_exe().map_err(|e| format!("无法确定可执行文件路径，无法查找资源：{e}"))?;
    let override_dir = std::env::var_os("LANTERN_ASSETS");
    let development = cfg!(any(debug_assertions, feature = "dev"));
    // cargo run 时运行时有这个变量；开发构建直接启动程序时用编译时的平台 crate 目录。
    let manifest = std::env::var_os("CARGO_MANIFEST_DIR")
        .or_else(|| development.then(|| env!("CARGO_MANIFEST_DIR").into()));
    resolve_asset_dir(
        &exe,
        development,
        override_dir.as_deref().map(Path::new),
        manifest.as_deref().map(Path::new),
        Path::new("."),
    )
}

/// 规范化路径。Windows 上不用 canonicalize：它返回 `\\?\` 开头的路径，里面的 `/` 不再算分隔符，
/// Bevy 拼上 `atlas/…` 就找不到文件；那边用系统的绝对路径规范化（会处理 `.`、`..` 和 `/`）。
pub(crate) fn normalize(path: &Path) -> std::io::Result<PathBuf> {
    if cfg!(windows) { std::path::absolute(path) } else { path.canonicalize() }
}

fn resolve_asset_dir(
    exe: &Path,
    development: bool,
    override_dir: Option<&Path>,
    manifest: Option<&Path>,
    working_dir: &Path,
) -> Result<PathBuf, String> {
    let mut candidates = Vec::new();
    if let Some(dir) = override_dir {
        // 显式覆盖无效时直接报错，避免悄悄加载另一套资源。
        candidates.push(working_dir.join(dir));
    } else {
        if let Some(parent) = exe.parent() {
            candidates.push(parent.join("assets"));
        }
        if let Some(manifest) = manifest {
            candidates.push(working_dir.join(manifest).join("../../assets"));
        }
        if development {
            candidates.push(working_dir.join("assets"));
        }
    }

    let mut failures = Vec::new();
    for candidate in candidates {
        let candidate =
            std::path::absolute(&candidate).map_err(|e| format!("无法解析资源路径 {candidate:?}：{e}"))?;
        match normalize(&candidate) {
            Ok(path) if path.join("data").is_dir() => return Ok(path),
            Ok(_) => failures.push(format!("  {candidate:?}：缺少 data 子目录")),
            Err(e) => failures.push(format!("  {candidate:?}：{e}")),
        }
    }
    Err(format!("找不到资源目录（需要包含 data 子目录），已尝试的路径：\n{}", failures.join("\n")))
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

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;
    use std::time::{SystemTime, UNIX_EPOCH};

    struct TestDir(PathBuf);

    impl TestDir {
        fn new() -> Self {
            let stamp = SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_nanos();
            let path = std::env::temp_dir().join(format!("提灯 资源测试-{}-{stamp}", std::process::id()));
            for dir in ["安装目录/bin", "仓库/crates/platform", "工作目录"] {
                fs::create_dir_all(path.join(dir)).unwrap();
            }
            Self(normalize(&path).unwrap())
        }

        fn assets(&self, dir: &str) -> PathBuf {
            let path = self.0.join(dir);
            fs::create_dir_all(path.join("data")).unwrap();
            normalize(&path).unwrap()
        }

        /// 开发构建总有仓库目录（运行时或编译时）；发布版只有 `cargo run --release` 时才有。
        fn resolve(&self, development: bool, override_dir: Option<&Path>) -> Result<PathBuf, String> {
            self.resolve_with(development, override_dir, development)
        }

        fn resolve_with(
            &self,
            development: bool,
            override_dir: Option<&Path>,
            cargo_run: bool,
        ) -> Result<PathBuf, String> {
            resolve_asset_dir(
                &self.0.join("安装目录/bin/lantern.exe"),
                development,
                override_dir,
                cargo_run.then(|| self.0.join("仓库/crates/platform")).as_deref(),
                &self.0.join("工作目录"),
            )
        }
    }

    impl Drop for TestDir {
        fn drop(&mut self) {
            let _ = fs::remove_dir_all(&self.0);
        }
    }

    // 报错里的路径经过 std::path::absolute（Windows 上 `/` 换成 `\\`），期望值也同样规范化。
    #[test]
    fn release_uses_assets_beside_executable_unless_told_otherwise() {
        let dir = TestDir::new();
        // 仓库、工作目录、EXE 的祖先目录都有资源，发布版直接启动时也不去读。
        for path in ["仓库/assets", "工作目录/assets", "安装目录/assets"] {
            dir.assets(path);
        }
        let error = dir.resolve(false, None).unwrap_err();
        assert!(error.contains("已尝试的路径"), "{error}");
        assert!(
            error.contains(&format!("{:?}", std::path::absolute(dir.0.join("安装目录/bin/assets")).unwrap())),
            "{error}"
        );
        assert_eq!(error.lines().count(), 2, "{error}");
        // 明确指定的目录和 cargo run --release 可以用。
        let override_dir = dir.assets("覆盖目录");
        assert_eq!(dir.resolve(false, Some(&override_dir)).unwrap(), override_dir);
        assert_eq!(
            dir.resolve_with(false, None, true).unwrap(),
            normalize(&dir.0.join("仓库/assets")).unwrap()
        );

        let expected = dir.assets("安装目录/bin/assets");
        assert_eq!(dir.resolve(false, None).unwrap(), expected);
    }

    #[test]
    fn development_prefers_executable_then_manifest_then_working_directory() {
        let dir = TestDir::new();
        let working = dir.assets("工作目录/assets");
        let manifest = dir.assets("仓库/assets");
        let exe = dir.assets("安装目录/bin/assets");
        assert_eq!(dir.resolve(true, None).unwrap(), exe);
        fs::remove_dir_all(&exe).unwrap();
        assert_eq!(dir.resolve(true, None).unwrap(), manifest);
        fs::remove_dir_all(&manifest).unwrap();
        assert_eq!(dir.resolve(true, None).unwrap(), working);
    }

    #[test]
    fn development_override_is_absolute_and_normalized() {
        let dir = TestDir::new();
        dir.assets("安装目录/bin/assets");
        let expected = dir.assets("工作目录/中文 资源/assets");
        let path = dir.resolve(true, Some(Path::new("中文 资源/./assets/../assets"))).unwrap();
        assert!(path.is_absolute());
        assert_eq!(path, expected);
        assert_eq!(dir.resolve(true, Some(&expected)).unwrap(), expected);
    }

    #[test]
    fn invalid_override_does_not_fall_back() {
        let dir = TestDir::new();
        dir.assets("安装目录/bin/assets");
        dir.assets("仓库/assets");
        let error = dir.resolve(true, Some(Path::new("不存在的资源"))).unwrap_err();
        assert!(
            error.contains(&format!(
                "{:?}",
                std::path::absolute(dir.0.join("工作目录/不存在的资源")).unwrap()
            )),
            "{error}"
        );
        assert_eq!(error.lines().count(), 2, "{error}");
    }

    #[test]
    fn failure_lists_every_candidate_and_rejects_incomplete_directories() {
        let dir = TestDir::new();
        fs::create_dir_all(dir.0.join("安装目录/bin/assets")).unwrap();
        fs::write(dir.0.join("安装目录/bin/assets/data"), "不是目录").unwrap();
        fs::write(dir.0.join("仓库/assets"), "不是目录").unwrap();
        let error = dir.resolve(true, None).unwrap_err();
        for path in ["安装目录/bin/assets", "仓库/crates/platform/../../assets", "工作目录/assets"]
        {
            let path = std::path::absolute(dir.0.join(path)).unwrap();
            assert!(error.contains(&format!("{path:?}")), "{error}");
        }
        assert!(error.contains("缺少 data 子目录"), "{error}");
        assert_eq!(error.lines().count(), 4, "{error}");
    }
}
