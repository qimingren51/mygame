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
    let expected = format!("资源目录不是有效的 UTF-8 路径：{path:?}");
    dir.assert_fatal(dir.game().env("LANTERN_ASSETS", path), &expected);
}
