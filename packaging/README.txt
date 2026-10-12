提灯夜行（桌面版 · 开发预览）
==============================

运行
  Windows：双击 lantern.exe
  Linux：  在终端运行 ./lantern
           需要 Vulkan 显卡驱动（Mesa 或厂商驱动）、ALSA 音频库和 libxkbcommon-x11，
           大多数桌面发行版都自带。缺少时，Ubuntu / Debian 上可以运行：
           sudo apt install mesa-vulkan-drivers libasound2 libxkbcommon-x11-0

操作
  移动    WASD / 方向键 / 手柄左摇杆
  闪避    空格 / Shift / 手柄 A
  暂停    Esc / 手柄 Start
  全屏    F11 或 Alt+Enter

命令行参数
  --seed <数字>   指定种子，同一种子加同一操作，结果完全一样
  --windowed      以窗口模式启动

数据位置（设置、存档、日志）
  Windows：%APPDATA%\lantern\data\
  Linux：  ~/.local/share/lantern/

assets 文件夹必须和程序放在同一个目录里。
字体：马善政楷书、思源宋体（Noto Serif SC），SIL Open Font License，许可证见 assets/fonts/。
