# Windows 程序资源

`crates/game/build.rs` 用 winresource 为 Windows 目标嵌入图标、版本信息和应用清单。版本字符串来自 `CARGO_PKG_VERSION`，数值版本由对应的主、次、补丁版本生成，第四段为 0；产品名和文件说明均为「提灯夜行」。图标组与 EXE 清单的资源编号均为 1。

构建脚本按 `CARGO_CFG_TARGET_OS` 判断目标系统，兼容交叉编译。Linux 目标不会读取这些资源或调用资源编译器；Windows 原生构建需要 Windows SDK 的 `rc.exe`（MSVC）或 MinGW 的 `windres`（GNU）。Linux 交叉编译 GNU Windows 目标需要 MinGW 工具链（包括 `x86_64-w64-mingw32-windres`）。普通 Rust 构建不需要 Python。

## 图标来源与更新

`lantern.ico` 来自仓库现有美术 `web/lantern/icons/icon-512.png`，包含 16、24、32、48、64、128、256 像素的 RGBA 图像。生成脚本和 ICO 均保存在仓库中：

```bash
python3 -m pip install Pillow
python3 packaging/windows/generate_icon.py
python3 packaging/windows/test_resources.py
```

Windows 运行时在窗口创建后，通过 winit 从 EXE 中加载同一图标组，设置标题栏和任务栏图标；由主线程执行，不依赖当前目录或额外的 ICO 文件。

## 清单与 DPI

`lantern.manifest` 声明普通用户权限 `asInvoker`、`PerMonitorV2`（旧系统回退到 `PerMonitor` / `true/pm`）、UTF-8 活动代码页和长路径感知。长路径仍受系统长路径策略及调用 API 支持限制。

Bevy 0.20 使用的 winit 默认会尝试启用 PerMonitorV2，与清单一致。清单在启动时确定进程 DPI 感知后，不再另加 DPI API 调用，也不覆盖 Bevy 的窗口缩放倍率；窗口尺寸和跨屏缩放继续交给 Bevy/winit。声明含义见 [Microsoft 应用清单文档](https://learn.microsoft.com/zh-cn/windows/win32/sbscs/application-manifests)。

## 验证

资源测试需要 Python 3.11 以上。上面的测试验证清单的 XML 命名空间、字段以及每个 ICO 尺寸与原图缩放后的像素。构建 Windows EXE 后，进一步检查最终 PE 中的清单、全部图标帧、版本字符串和数值版本：

```bash
python3 -m pip install Pillow pefile
cargo build --release -p lantern
python3 packaging/windows/test_resources.py --exe target/release/lantern.exe
```

Linux CI 检查仓库资源，Windows CI 同时检查最终 EXE。人工验收：查看 EXE 属性中的图标和详细信息；启动窗口后检查标题栏、任务栏和 Alt+Tab 图标，在 100% / 150% / 200% 缩放的显示器之间拖动窗口并切换全屏，确认文字清晰、鼠标点击位置正确。自动窗口渲染冒烟测试不能代替这项人工检查。
