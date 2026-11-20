# Next MC Launcher

[简体中文](#简体中文) · [English](#english) · [GitHub Releases](https://github.com/A5yncX/next-mc-launcher/releases)

## 简体中文

Next MC 是 [Horizon](https://github.com/horizon-rust/horizon) 的非官方 Windows x64 启动器。使用 Rust 版 Minecraft Java 26.3 客户端，支持离线单机和可选的机械动力（Create）+ Atlas。

1. 在 [Releases](https://github.com/A5yncX/next-mc-launcher/releases) 下载 `NextMC-Setup-Windows-x64.exe` 安装，或解压 `NextMC-Windows-x64.zip`。运行 `next-mc-launcher.exe`，保留同级的 `NextMC/` 文件夹。
2. 在 **下载 → 检查并准备本机文件** 复用已安装的游戏文件，或点 **下载缺失文件** 从 Mojang 获取。所需环境：[WebView2](https://developer.microsoft.com/microsoft-edge/webview2/)；首次准备资源用 [JDK 25](https://adoptium.net/temurin/releases/?version=25)。发行包不包含原版游戏文件。
3. 资源就绪后点 **离线启动游戏**。在 **设置 → 界面语言** 切换简体中文和 English。只想玩单机不需要登录。

机械动力：在 **实例 → 可选模组** 安装并启用 Create，再去 **下载** 准备资源。Atlas 可按实例开启，游戏内按 **M** 打开地图。普通模式与机械动力各自存档。

### 可选：使用 Create 原版贴图

发行版默认使用 Horizon 移植版自带贴图，**不附带 Create 原版贴图或 JAR**。想换成原版贴图：

1. 退出游戏，从 [Modrinth](https://modrinth.com/mod/create/version/UjX6dr61) 下载 **Create 6.0.10 for Minecraft 1.21.1（NeoForge）**，文件名为 `create-1.21.1-6.0.10.jar`。
2. 在启动器里选中已启用 Create 的实例，点击 **打开实例目录**。把 JAR 原样放进 `horizon-mods/create-resources/`；没有这个目录就新建，不用解压或改名。
3. 点击 **离线启动机械动力**。游戏只从 JAR 读取素材，不运行 Java 模组。移走 JAR 后重新启动，即可恢复移植版贴图。

从 beta.1 升级：便携版请解压到新目录，安装版建议先卸载旧版。存档和设置留在 `%LOCALAPPDATA%\NextMC`。本测试版仅验证单机；未验证 Microsoft 登录或联机。

[详细安装与排错](INSTALL.zh-CN.md) · [构建与打包](BUILD.md) · [许可](LICENSE)

## English

Next MC is an unofficial Windows x64 launcher for [Horizon](https://github.com/horizon-rust/horizon), a Rust client for Minecraft Java 26.3. It supports offline singleplayer and optional Create + Atlas.

1. Get `NextMC-Setup-Windows-x64.exe` or extract `NextMC-Windows-x64.zip` from [Releases](https://github.com/A5yncX/next-mc-launcher/releases). Run `next-mc-launcher.exe` and keep the `NextMC/` folder beside it.
2. In **Downloads → Check and prepare local files**, reuse your installed game files, or choose **Download missing files** to fetch them from Mojang. The launcher needs [WebView2](https://developer.microsoft.com/microsoft-edge/webview2/); initial resource preparation needs [JDK 25](https://adoptium.net/temurin/releases/?version=25). Original game files are not bundled.
3. Once resources are ready, choose **Play offline**. Change the UI language under **Settings → Language**. Offline singleplayer needs no sign-in.

For Create, install and enable it under **Instances → Optional mods**, then prepare its resources in **Downloads**. Enable Atlas per instance and press **M** in-game to open the map. Create and unmodded worlds are saved separately. If Create reports a missing `VCRUNTIME140` DLL, install the [Visual C++ x64 runtime](https://aka.ms/vs/17/release/vc_redist.x64.exe).

### Optional: Use the original Create textures

The release uses the Horizon port’s bundled textures by default. **The original Create textures and JAR are not included.** To use the originals:

1. Close the game. Download **Create 6.0.10 for Minecraft 1.21.1 (NeoForge)** from [Modrinth](https://modrinth.com/mod/create/version/UjX6dr61). The file is `create-1.21.1-6.0.10.jar`.
2. Select the Create-enabled instance in the launcher and click **Open instance folder**. Put the JAR in `horizon-mods/create-resources/`, creating the folder if needed. Do not extract or rename the file.
3. Click **Play Create offline**. The game reads assets from the JAR without running the Java mod. Remove the JAR and restart to switch back to the bundled textures.

Upgrading from beta.1: extract the ZIP to a new folder, or uninstall the old setup first. Saves and settings stay in `%LOCALAPPDATA%\NextMC`. This beta tests singleplayer only; Microsoft sign-in and multiplayer were not verified.

[Build and packaging](BUILD.md) · [License](LICENSE)
