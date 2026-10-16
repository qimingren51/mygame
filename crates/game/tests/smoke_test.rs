//! 启动真实窗口，检查渲染成功及资源损坏时的退出码与日志；失败不能等待 Windows 弹窗。

use std::fs;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

struct TestDir(PathBuf);

impl TestDir {
    fn new() -> Self {
        let stamp = SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_nanos();
        let path = std::env::temp_dir().join(format!("提灯 冒烟测试-{}-{stamp}", std::process::id()));
        fs::create_dir_all(path.join("安装 目录")).unwrap();
        fs::create_dir_all(path.join("工作 目录")).unwrap();
        let dir = Self(path);
        fs::copy(env!("CARGO_BIN_EXE_lantern"), dir.exe()).unwrap();
        copy_dir(
            &PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../assets"),
            &dir.0.join("安装 目录/assets"),
        );
        dir
    }

    fn exe(&self) -> PathBuf {
        self.0.join("安装 目录").join(format!("lantern{}", std::env::consts::EXE_SUFFIX))
    }

    fn run(&self, args: &[&str], success: bool, expected: &str) {
        let mut child = Command::new(self.exe())
            .current_dir(self.0.join("工作 目录"))
            .env_remove("LANTERN_ASSETS")
            .env("XDG_DATA_HOME", &self.0)
            .env("RUST_LOG", if success { "info" } else { "off" })
            .args(args)
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .spawn()
            .unwrap();
        let start = Instant::now();
        let status = loop {
            if let Some(status) = child.try_wait().unwrap() {
                break status;
            }
            if start.elapsed() > Duration::from_secs(180) {
                child.kill().unwrap();
                child.wait().unwrap();
                panic!("冒烟测试超时：{args:?}");
            }
            std::thread::sleep(Duration::from_millis(20));
        };
        #[cfg(target_os = "linux")]
        let logs = self.0.join("lantern/logs");
        #[cfg(not(target_os = "linux"))]
        let logs = lantern_platform::paths::log_dir();
        let suffix = format!("-{}.log", child.id());
        let log = fs::read_dir(logs)
            .unwrap()
            .map(|entry| entry.unwrap().path())
            .find(|path| path.file_name().unwrap().to_string_lossy().ends_with(&suffix))
            .unwrap();
        let text = fs::read_to_string(log).unwrap();
        assert_eq!(status.code(), Some(if success { 0 } else { 1 }), "预期：{expected}\n{text}");
        assert!(text.contains(expected), "{text}");
    }
}

impl Drop for TestDir {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

fn copy_dir(from: &Path, to: &Path) {
    fs::create_dir_all(to).unwrap();
    for entry in fs::read_dir(from).unwrap() {
        let entry = entry.unwrap();
        let dest = to.join(entry.file_name());
        if entry.file_type().unwrap().is_dir() {
            copy_dir(&entry.path(), &dest);
        } else {
            fs::copy(entry.path(), dest).unwrap();
        }
    }
}

#[test]
fn reports_startup_errors_without_a_window() {
    let dir = TestDir::new();
    dir.run(&["--seed", "bad", "--smoke-test"], false, "种子不是数字");
    fs::write(dir.0.join("安装 目录/assets/data/player.ron"), "invalid").unwrap();
    dir.run(&["--smoke-test", "--windowed"], false, "内容数据有误");
}

#[test]
#[cfg_attr(not(windows), ignore = "需要窗口和渲染设备；Linux 可在 Xvfb + lavapipe 下运行")]
fn rendered_package_completes_and_reports_failures() {
    let dir = TestDir::new();
    let smoke = ["--smoke-test", "--windowed"];
    dir.run(&smoke, true, "冒烟测试通过：初始化完成，窗口渲染 120 帧");
    let assets = dir.0.join("安装 目录/assets");
    // 图集 JSON 正常但贴图损坏时，必须等待异步解码并报告失败。
    let image = assets.join("atlas/actors.png");
    let original = fs::read(&image).unwrap();
    fs::write(&image, b"broken png").unwrap();
    dir.run(&smoke, false, "actors.png");
    fs::write(&image, &original).unwrap();
    fs::remove_file(&image).unwrap();
    dir.run(&smoke, false, "actors.png");
    fs::write(image, original).unwrap();
    fs::write(assets.join("fonts/NotoSerifSC-subset.ttf"), "invalid").unwrap();
    dir.run(&smoke, false, "NotoSerifSC-subset.ttf");
}
