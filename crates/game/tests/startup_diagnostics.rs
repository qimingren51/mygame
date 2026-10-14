//! 直接运行主程序，验证创建窗口前的错误也能留下日志；Windows 原生弹窗留给真机验证。
#![cfg(target_os = "linux")]

use std::fs;
use std::path::PathBuf;
use std::process::Command;
use std::time::{SystemTime, UNIX_EPOCH};

struct TestDir(PathBuf);

impl TestDir {
    fn new() -> Self {
        let stamp = SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_nanos();
        let path = std::env::temp_dir().join(format!("提灯 启动日志测试-{}-{stamp}", std::process::id()));
        fs::create_dir_all(&path).unwrap();
        Self(path)
    }

    fn game(&self) -> Command {
        let mut command = Command::new(env!("CARGO_BIN_EXE_lantern"));
        command
            .env("XDG_DATA_HOME", &self.0)
            .env("LANTERN_ASSETS", PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../assets"))
            // 即使关闭普通日志，启动标记和致命错误也必须写入。
            .env("RUST_LOG", "off");
        command
    }
}

impl Drop for TestDir {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

#[test]
fn logs_argument_content_and_replay_failures_before_window_creation() {
    for (args, expected) in [
        (vec!["--seed", "不是数字"], "种子不是数字"),
        (vec![], "内容数据有误"),
        (vec!["--replay", "不存在的回放.ron"], "读取回放"),
    ] {
        let dir = TestDir::new();
        let mut command = dir.game();
        if args.is_empty() {
            let assets = dir.0.join("缺少内容的资源");
            fs::create_dir_all(assets.join("data")).unwrap();
            command.env("LANTERN_ASSETS", assets);
        }
        let output = command.current_dir(&dir.0).args(args).output().unwrap();
        assert_eq!(output.status.code(), Some(1), "{output:?}");
        let logs: Vec<_> =
            fs::read_dir(dir.0.join("lantern/logs")).unwrap().map(|entry| entry.unwrap().path()).collect();
        assert_eq!(logs.len(), 1);
        let log = fs::read_to_string(&logs[0]).unwrap();
        assert!(log.contains("提灯夜行启动"), "{log}");
        assert!(log.contains(expected), "{log}");
        assert!(log.find("提灯夜行启动").unwrap() < log.find(expected).unwrap());
        assert!(!log.contains('\u{1b}'));
        let stderr = String::from_utf8(output.stderr).unwrap();
        assert!(stderr.contains(expected), "{stderr}");
        assert!(stderr.contains(logs[0].to_str().unwrap()), "{stderr}");
    }
}

#[test]
fn reports_unwritable_log_directory_without_a_second_panic() {
    let dir = TestDir::new();
    fs::create_dir_all(dir.0.join("lantern")).unwrap();
    let blocked = dir.0.join("lantern/logs");
    fs::write(&blocked, "保留原文件").unwrap();
    let output = dir.game().output().unwrap();
    assert_eq!(output.status.code(), Some(1), "{output:?}");
    let stderr = String::from_utf8(output.stderr).unwrap();
    assert!(stderr.contains("无法创建日志"), "{stderr}");
    assert!(stderr.contains("日志尚未建立"), "{stderr}");
    assert!(stderr.contains(blocked.to_str().unwrap()), "{stderr}");
    assert_eq!(fs::read_to_string(blocked).unwrap(), "保留原文件");
}
