//! 通过真实命令行读写非 UTF-8 路径，防止参数在进入解析器前就被转成字符串。
#![cfg(unix)]

use std::ffi::OsStr;
use std::fs;
use std::os::unix::ffi::OsStrExt;
use std::path::PathBuf;
use std::process::Command;
use std::time::{SystemTime, UNIX_EPOCH};

use lantern_sim::Replay;

struct TestDir(PathBuf);

impl TestDir {
    fn new() -> Self {
        let stamp = SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_nanos();
        let path = std::env::temp_dir().join(format!("提灯 命令行测试-{}-{stamp}", std::process::id()));
        fs::create_dir_all(&path).unwrap();
        Self(path)
    }
}

impl Drop for TestDir {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

fn tools() -> Command {
    let mut command = Command::new(env!("CARGO_BIN_EXE_lantern-tools"));
    command.env("LANTERN_DATA", PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../assets/data"));
    command
}

#[test]
fn records_exports_and_replays_non_utf8_paths() {
    let dir = TestDir::new();
    let record = dir.0.join(OsStr::from_bytes(b"night \xff.ron"));
    let csv = dir.0.join(OsStr::from_bytes(b"csv \xfe"));
    let output = tools()
        .args(["kite", "--runs", "1", "--jobs", "1", "--seed", "1", "--skill", "circle", "--record"])
        .arg(&record)
        .arg("--csv")
        .arg(&csv)
        .output()
        .unwrap();
    assert!(output.status.success(), "{output:?}");
    let replay = Replay::parse(&fs::read_to_string(&record).unwrap()).unwrap();
    assert!(replay.steps > 0);
    assert!(!replay.hashes.is_empty());
    for name in ["timeline.csv", "runs.csv"] {
        assert!(fs::read_to_string(csv.join(name)).unwrap().lines().count() > 1);
    }

    let output = tools().arg("replay").arg(&record).output().unwrap();
    assert!(output.status.success(), "{output:?}");
    assert!(String::from_utf8(output.stdout).unwrap().contains("个检查点与录制时一致"));
}

#[test]
fn rejects_non_utf8_numbers_and_text_without_panicking() {
    let invalid = OsStr::from_bytes(b"\xff");
    for (command, flag, expected) in [
        ("bench", "--seed", "后面要跟一个数字"),
        ("balance", "--runs", "后面要跟一个数字"),
        ("kite", "--tier", "后面要跟一个数字"),
        ("kite", "--meta", "必须是有效的 UTF-8 文字"),
        ("kite", "--lamp", "必须是有效的 UTF-8 文字"),
        ("kite", "--skill", "必须是有效的 UTF-8 文字"),
        ("kite", "--school", "必须是有效的 UTF-8 文字"),
        ("kite", "--combo", "必须是有效的 UTF-8 文字"),
    ] {
        let output = tools().args([command, flag]).arg(invalid).output().unwrap();
        assert_eq!(output.status.code(), Some(1), "{output:?}");
        assert!(String::from_utf8(output.stderr).unwrap().contains(expected));
    }
    let output = tools().arg(invalid).output().unwrap();
    assert_eq!(output.status.code(), Some(1), "{output:?}");
    assert!(String::from_utf8(output.stderr).unwrap().contains("用法："));
}
