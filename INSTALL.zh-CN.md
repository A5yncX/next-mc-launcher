# Next MC Launcher · Windows x64 Beta

在 [GitHub Releases](https://github.com/A5yncX/next-mc-launcher/releases) 二选一：

- **`NextMC-Setup-Windows-x64.exe`**：当前用户安装，不需要管理员权限，可勾选创建桌面快捷方式。卸载不会删除存档。
- **`NextMC-Windows-x64.zip`**：完整解压到自己可写的目录，再运行 `next-mc-launcher.exe`。请保留旁边的 `horizon` 文件夹。

发行文件未签名，Windows SmartScreen 可能提示。只从上述 GitHub 仓库下载；可用 `Get-FileHash <文件名> -Algorithm SHA256` 核对旁边的 `.sha256` 文件。不要下载 GitHub 自动生成的 **Source code** 来游玩。

## 第一次玩

1. 启动器需要 [Microsoft Edge WebView2 Runtime](https://developer.microsoft.com/microsoft-edge/webview2/)。准备资源需要 [JDK 25](https://adoptium.net/temurin/releases/?version=25)；必要时将 `JAVA_HOME` 指向 JDK 安装目录。机械动力需要 [Microsoft Visual C++ x64 运行库](https://aka.ms/vs/17/release/vc_redist.x64.exe)，缺少 `VCRUNTIME140.dll` 或 `VCRUNTIME140_1.dll` 时从微软安装。准备完成后运行 Rust 游戏不需要 Java、Node.js 或 Rust 工具链。
2. 在「下载」页点 **检查并准备本机文件**，必要时填写已有的 Minecraft Java 26.3 安装目录。也可点 **下载缺失文件** 允许从 Mojang 补齐并校验。请使用你有权使用的游戏资源；发行包不包含 Minecraft 原版文件。
3. 资源就绪后点 **离线启动游戏**，在游戏中创建单人世界。此测试版只验证了单机，没有验证 Microsoft 登录、局域网或联机。

## 可选：机械动力 + Atlas

1. 打开 **实例 → 可选模组**，点 **安装 Create + Atlas**。也可以手动下载 `NextMC-Create-Atlas-Windows-x64.zip`，不解压，放到 `next-mc-launcher.exe` 同级，再点击同一按钮校验安装。
2. 启用 **机械动力（Create）**，前往「下载」准备对应资源，回到启动按钮 **离线启动机械动力** 创建单人世界。它会复用原始下载缓存，但有自己的资源目录和存档。
3. **Atlas 小地图和世界地图** 默认关闭，按实例开启。游戏内按 **M** 打开世界地图。
4. Create 默认使用移植版自带素材。如果想用原版贴图，可在开启机械动力后点 **打开实例目录**，把 [Create 6.0.10 NeoForge 原版 JAR](https://modrinth.com/mod/create/version/UjX6dr61) 放到 `horizon-mods/create-resources/`。它只用作本地素材，不执行 Java 模组。

升级或切换模组前先退出游戏。存档、配置和可选组件在 `%LOCALAPPDATA%\NextMC`，与安装目录分离。普通模式和机械动力模式的存档互不覆盖；关闭开关不会删档。建议备份整个数据目录。

排查问题可查看该目录下的 `prepare-gui.log`，或当前实例目录内的 `play-gui.log` 和 `logs`。

本项目基于 Horizon，与 Mojang、Microsoft 无隶属关系。对应源码和许可位于发行包内的 `source`、`horizon`、`licenses`，可选组件的对应源码单独随 Release 提供。
