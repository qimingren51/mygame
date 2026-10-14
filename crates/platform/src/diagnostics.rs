//! 启动日志与致命错误提示；必须在解析参数、加载内容和创建 Bevy 插件前初始化。

use std::backtrace::Backtrace;
use std::fs::{self, File, OpenOptions};
use std::io::{self, Write};
use std::path::{Path, PathBuf};
use std::sync::OnceLock;
use std::time::{SystemTime, UNIX_EPOCH};

use bevy::log::tracing_subscriber::{self, EnvFilter, prelude::*};
use bevy::prelude::*;

use crate::paths;

static LOG: OnceLock<LogFile> = OnceLock::new();
const KEEP_LOGS: usize = 5;

struct LogFile {
    path: PathBuf,
    file: File,
}

impl LogFile {
    fn open(dir: &Path) -> io::Result<Self> {
        fs::create_dir_all(dir)?;
        let dir = fs::canonicalize(dir)?;
        let now = SystemTime::now().duration_since(UNIX_EPOCH).unwrap_or_default();
        let path = dir.join(format!("lantern-{:020}-{}.log", now.as_nanos(), std::process::id()));
        let file = OpenOptions::new().create_new(true).append(true).open(&path)?;
        Ok(Self { path, file })
    }

    /// 不经过日志过滤器或用户态缓冲，也不持有互斥锁，panic 时仍可写入。
    fn write_record(&self, level: &str, message: &str) -> io::Result<()> {
        let now = SystemTime::now().duration_since(UNIX_EPOCH).unwrap_or_default();
        let record = format!("[{}.{:03}] {level} lantern: {message}\n", now.as_secs(), now.subsec_millis());
        let mut file = &self.file;
        file.write_all(record.as_bytes())?;
        file.sync_all()
    }
}

/// 每次启动新建日志，保留最近五份。主程序随后禁用 Bevy 的 `LogPlugin`，避免重复初始化。
pub fn init() -> Result<(), String> {
    init_at(&paths::log_dir())
}

fn init_at(dir: &Path) -> Result<(), String> {
    let log = LogFile::open(dir).map_err(|e| format!("无法创建日志（{}）：{e}", dir.display()))?;
    LOG.set(log).map_err(|_| "日志已经初始化".to_string())?;
    let log = LOG.get().ok_or("日志未初始化")?;

    let previous_hook = std::panic::take_hook();
    std::panic::set_hook(Box::new(move |info| {
        let message = format!("程序发生错误：{info}");
        let details = format!(
            "{message}\n线程：{:?}\n调用栈：\n{}",
            std::thread::current().name(),
            Backtrace::force_capture()
        );
        report_fatal(&message, &details);
        previous_hook(info);
    }));

    log.write_record(
        "INFO",
        &format!(
            "提灯夜行启动；版本 {}；系统 {}；进程 {}；日志：{}",
            env!("CARGO_PKG_VERSION"),
            std::env::consts::OS,
            std::process::id(),
            log.path.display()
        ),
    )
    .map_err(|e| format!("写入启动日志失败：{e}"))?;

    let filter = EnvFilter::try_from_default_env()
        .unwrap_or_else(|_| EnvFilter::new(format!("info,{}", bevy::log::DEFAULT_FILTER)));
    let writer = log.file.try_clone().map_err(|e| format!("打开日志输出失败：{e}"))?;
    tracing_subscriber::registry()
        .with(filter)
        .with(tracing_subscriber::fmt::layer().with_writer(io::stderr))
        .with(tracing_subscriber::fmt::layer().with_ansi(false).with_writer(writer))
        .try_init()
        .map_err(|e| format!("初始化日志失败：{e}"))?;

    if let Err(e) = prune_logs(dir, &log.path) {
        warn!("清理旧日志失败：{e}");
    }
    Ok(())
}

fn prune_logs(dir: &Path, current: &Path) -> io::Result<()> {
    let mut logs = Vec::new();
    for entry in fs::read_dir(dir)? {
        let entry = entry?;
        let name = entry.file_name();
        let Some(name) = name.to_str() else { continue };
        let Some(stem) = name.strip_prefix("lantern-").and_then(|s| s.strip_suffix(".log")) else {
            continue;
        };
        let Some((time, pid)) = stem.split_once('-') else { continue };
        if time.len() == 20
            && time.parse::<u128>().is_ok()
            && pid.parse::<u32>().is_ok()
            && entry.file_type()?.is_file()
        {
            let path = fs::canonicalize(entry.path())?;
            if path != current {
                logs.push(path);
            }
        }
    }
    logs.sort();
    let remove = logs.len().saturating_sub(KEEP_LOGS - 1);
    for path in logs.into_iter().take(remove) {
        fs::remove_file(path)?;
    }
    Ok(())
}

/// 启动失败或图集无法加载时，先记录错误，再提示玩家，最后由调用方退出。
pub fn fatal(message: &str) -> AppExit {
    report_fatal(message, message);
    AppExit::error()
}

fn report_fatal(message: &str, details: &str) {
    let description = match LOG.get() {
        Some(log) => match log.write_record("ERROR", details) {
            Ok(()) => format!("{message}\n\n日志：{}", log.path.display()),
            Err(e) => format!("{message}\n\n日志写入失败：{e}\n日志路径：{}", log.path.display()),
        },
        None => format!("{message}\n\n日志尚未建立。日志目录：{}", paths::log_dir().display()),
    };
    // 无控制台或标准错误已关闭时，不让诊断代码再次 panic。
    let _ = writeln!(io::stderr().lock(), "{description}");
    #[cfg(windows)]
    {
        use std::sync::atomic::{AtomicBool, Ordering};
        // Bevy 的工作线程可能同时 panic，只弹一次，其他错误仍写入日志。
        static SHOWN: AtomicBool = AtomicBool::new(false);
        if !SHOWN.swap(true, Ordering::Relaxed) {
            rfd::MessageDialog::new()
                .set_title("提灯夜行 — 致命错误")
                .set_description(description)
                .set_level(rfd::MessageLevel::Error)
                .set_buttons(rfd::MessageButtons::Ok)
                .show();
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    struct TestDir(PathBuf);

    impl TestDir {
        fn new() -> Self {
            let now = SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_nanos();
            Self(std::env::temp_dir().join(format!("提灯 日志测试-{}-{now}", std::process::id())))
        }
    }

    impl Drop for TestDir {
        fn drop(&mut self) {
            let _ = fs::remove_dir_all(&self.0);
        }
    }

    #[test]
    fn reports_the_path_when_log_creation_fails() {
        let dir = TestDir::new();
        fs::create_dir_all(&dir.0).unwrap();
        // 用文件挡住日志目录，稳定复现无法建目录，不依赖测试用户的权限。
        let blocked = dir.0.join("logs");
        fs::write(&blocked, "保留原文件").unwrap();
        let error = init_at(&blocked).unwrap_err();
        assert!(error.contains("无法创建日志"));
        assert!(error.contains(blocked.to_str().unwrap()));
        assert_eq!(fs::read_to_string(blocked).unwrap(), "保留原文件");
    }

    #[test]
    fn keeps_five_logs_without_removing_other_files() {
        let dir = TestDir::new();
        fs::create_dir_all(&dir.0).unwrap();
        for i in 0..7 {
            fs::write(dir.0.join(format!("lantern-{i:020}-123.log")), "旧日志").unwrap();
        }
        fs::write(dir.0.join("lantern-notes.log"), "保留").unwrap();
        fs::write(dir.0.join("startup-error.txt"), "旧版错误").unwrap();
        let log = LogFile::open(&dir.0).unwrap();
        log.write_record("ERROR", "中文与空格路径").unwrap();
        prune_logs(&dir.0, &log.path).unwrap();
        assert_eq!(fs::read_dir(&dir.0).unwrap().count(), 7);
        assert!(!dir.0.join("lantern-00000000000000000002-123.log").exists());
        assert!(dir.0.join("lantern-00000000000000000003-123.log").exists());
        assert!(dir.0.join("lantern-notes.log").exists());
        assert!(dir.0.join("startup-error.txt").exists());
        assert!(fs::read_to_string(&log.path).unwrap().contains("中文与空格路径"));
    }

    // 独立进程测试全局 subscriber 和 panic hook，避免影响并行测试；Windows 弹窗留给真机验证。
    #[cfg(not(windows))]
    fn run_child(mode: &str, filter: &str) -> (std::process::Output, String) {
        let dir = TestDir::new();
        let output = std::process::Command::new(std::env::current_exe().unwrap())
            .args(["--exact", "diagnostics::tests::logging_child", "--nocapture"])
            .env("LANTERN_TEST_LOG_DIR", &dir.0)
            .env("LANTERN_TEST_LOG_MODE", mode)
            .env("RUST_LOG", filter)
            .output()
            .unwrap();
        let path = fs::read_dir(&dir.0).unwrap().next().unwrap().unwrap().path();
        (output, fs::read_to_string(path).unwrap())
    }

    #[test]
    #[cfg(not(windows))]
    fn logging_child() {
        let Some(dir) = std::env::var_os("LANTERN_TEST_LOG_DIR") else { return };
        init_at(Path::new(&dir)).unwrap();
        match std::env::var("LANTERN_TEST_LOG_MODE").unwrap().as_str() {
            "panic" => panic!("主线程错误"),
            "worker" => {
                let _ = std::thread::Builder::new()
                    .name("测试工作线程".into())
                    .spawn(|| panic!("工作线程错误"))
                    .unwrap()
                    .join();
            }
            _ => {
                info!("插件初始化前的日志");
                assert_eq!(fatal("启动失败测试"), AppExit::error());
            }
        }
    }

    #[test]
    #[cfg(not(windows))]
    fn captures_early_logs_and_fatal_errors() {
        let (output, log) = run_child("fatal", "info");
        assert!(output.status.success());
        assert!(log.contains("提灯夜行启动"));
        assert!(log.contains("插件初始化前的日志"));
        assert!(log.contains("启动失败测试"));
        assert!(!log.contains('\u{1b}'));
        assert!(String::from_utf8_lossy(&output.stderr).contains("日志："));
        let (output, log) = run_child("fatal", "off");
        assert!(output.status.success());
        assert!(log.contains("提灯夜行启动"));
        assert!(log.contains("启动失败测试"));
        assert!(!log.contains("插件初始化前的日志"));
    }

    #[test]
    #[cfg(not(windows))]
    fn captures_panics_even_when_logs_are_disabled() {
        for mode in ["panic", "worker"] {
            let (output, log) = run_child(mode, "off");
            assert_eq!(output.status.success(), mode == "worker");
            assert!(log.contains("线程错误"));
            assert!(log.contains("diagnostics.rs:"));
            assert!(log.contains("调用栈："));
            assert!(log.contains("logging_child"));
            if mode == "worker" {
                assert!(log.contains("测试工作线程"));
            }
        }
    }
}
