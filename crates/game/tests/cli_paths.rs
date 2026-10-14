//! 启动失败发生在创建窗口之前；用 Linux 数据目录隔离原生路径及 fatal 日志测试。
#![cfg(target_os = "linux")]

use std::ffi::OsStr;
use std::fs;
use std::os::unix::ffi::OsStrExt;
use std::path::PathBuf;
use std::process::Command;
use std::time::{SystemTime, UNIX_EPOCH};

struct TestDir(PathBuf);

impl TestDir {
    fn new() -> Self {
        let stamp = SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_nanos();
        let path = std::env::temp_dir().join(format!("提灯 启动路径测试-{}-{stamp}", std::process::id()));
        fs::create_dir_all(&path).unwrap();
        Self(path)
    }

    fn game(&self) -> Command {
        let mut command = Command::new(env!("CARGO_BIN_EXE_lantern"));
        command
            .env("XDG_DATA_HOME", &self.0)
            .env("LANTERN_ASSETS", PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../assets"));
        command
    }

    fn assert_fatal(&self, command: &mut Command, expected: &str) {
        let output = command.output().unwrap();
        assert_eq!(output.status.code(), Some(1), "{output:?}");
        assert!(String::from_utf8(output.stderr).unwrap().contains(expected));
        let log = fs::read_dir(self.0.join("lantern/logs")).unwrap().next().unwrap().unwrap().path();
        assert!(fs::read_to_string(log).unwrap().contains(expected));
    }
}

impl Drop for TestDir {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

#[test]
fn reads_non_utf8_replay_path_before_reporting_format_error() {
    let dir = TestDir::new();
    let path = dir.0.join(OsStr::from_bytes(b"night \xff.ron"));
    // 文件能读到，才会进入旧版回放的格式检查；整个过程不需要启动窗口。
    fs::write(&path, "(format: 1)").unwrap();
    dir.assert_fatal(dir.game().arg("--replay").arg(path), "回放格式版本 1");
}

#[test]
fn reports_missing_non_utf8_replay_path_without_replacement() {
    let dir = TestDir::new();
    let path = dir.0.join(OsStr::from_bytes(b"missing \xff.ron"));
    // 日志与标准错误都保留字节转义，不能把不同文件名显示成同一个替换字符。
    let expected = format!("读取回放 {path:?} 失败");
    dir.assert_fatal(dir.game().arg("--replay").arg(path), &expected);
}

#[test]
fn reports_non_utf8_asset_path_through_fatal() {
    let dir = TestDir::new();
    let path = dir.0.join(OsStr::from_bytes(b"assets \xff"));
    fs::create_dir_all(path.join("data")).unwrap();
    let expected = format!("资源目录不是有效的 UTF-8 路径：{path:?}");
    dir.assert_fatal(dir.game().env("LANTERN_ASSETS", path), &expected);
}

#[test]
fn reports_missing_asset_directory_and_attempted_path_through_fatal() {
    let dir = TestDir::new();
    let path = dir.0.join("不存在的资源");
    dir.assert_fatal(dir.game().env("LANTERN_ASSETS", &path), "找不到资源目录");
    let log = fs::read_dir(dir.0.join("lantern/logs")).unwrap().next().unwrap().unwrap().path();
    let text = fs::read_to_string(log).unwrap();
    assert!(text.contains("已尝试的路径"), "{text}");
    assert!(text.contains(&format!("{path:?}")), "{text}");
}

#[test]
fn relative_assets_use_working_directory_and_are_logged_as_absolute() {
    let dir = TestDir::new();
    let assets = dir.0.join("中文 资源/assets");
    fs::create_dir_all(assets.join("data")).unwrap();
    let source = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../assets/data");
    for entry in fs::read_dir(source).unwrap() {
        let entry = entry.unwrap();
        if entry.file_type().unwrap().is_file() {
            fs::copy(entry.path(), assets.join("data").join(entry.file_name())).unwrap();
        }
    }
    // 内容成功加载后才读取回放；用坏回放在创建窗口前结束测试。
    fs::write(dir.0.join("回放.ron"), "(format: 1)").unwrap();
    dir.assert_fatal(
        dir.game()
            .current_dir(&dir.0)
            .env("LANTERN_ASSETS", "中文 资源/./assets/../assets")
            .env("RUST_LOG", "info")
            .args(["--replay", "回放.ron"]),
        "回放格式版本 1",
    );
    let log = fs::read_dir(dir.0.join("lantern/logs")).unwrap().next().unwrap().unwrap().path();
    assert!(
        fs::read_to_string(log)
            .unwrap()
            .contains(&format!("资源目录：{}", assets.canonicalize().unwrap().display()))
    );
}
