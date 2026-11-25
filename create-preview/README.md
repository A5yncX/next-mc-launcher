# Rust Create Preview 1

[中文](#开始玩) · [English](#play) · [GitHub release](https://github.com/A5yncX/next-mc-launcher/releases/tag/create-preview.1) · [Build from source](BUILD.md) · [106-block checklist](lab/behavior-parity.md)

## 开始玩

1. 在 **Windows x64** 上打开 [Next MC beta.2](https://github.com/A5yncX/next-mc-launcher/releases/tag/v0.1.0-beta.2)。在「实例 → 可选模组」安装 **Create + Atlas**、开启 **Create**，然后在「下载」准备游戏资源。首次准备需要 [JDK 25](https://adoptium.net/temurin/releases/?version=25)；预览包不会附带 Minecraft 或 Create 原版 JAR、原版贴图和已准备的资源。如果提示缺少 `VCRUNTIME140`，安装 [VC++ x64 运行库](https://aka.ms/vs/17/release/vc_redist.x64.exe)。
2. 解压 `NextMC-Rust-Create-Preview-Windows-x64.zip` 到**新目录**。双击 `Start-Server.cmd`，窗口显示 `Server is now running` 后，首次在该窗口输入 `datapack enable "file/create-passive"` 启用掉落和配方，再双击 `Play-Create.cmd`。首次加载可能需要一两分钟。不需要在玩家电脑编译 Rust，也不用登录 Microsoft。游戏与服务端进程都是 Rust；不执行 Java Create。
3. 这是创造模式工坊。在创造物品栏搜索马达、传动轴和齿轮，摆成一条线；将相邻大小齿轮啮合可改变传动比。想切换生存，在服务端窗口输入 `gamemode survival CreatePlayer`。结束时退出游戏，在服务端窗口输入 `stop` 保存。

预览只连接 `127.0.0.1:25586`。存档保存在 `CreatePreview/server/create-lab/`，不读取或修改 beta.2 的存档。不要导入正式存档或对公网开放。不要用旧客户端连预览服，也不要替换现有启动器的 EXE。

**进度：106 个方块全部注册、全部已有部分行为，0 个完成全部对齐验收。** 已有双客户端和重启测试覆盖传动、红石离合/换向、水轮、部分流体及流水线、同区块旋转装配、移动收割与耕作。跨区块移动、移动库存，以及多种完整机器交互仍未完成。[逐方块进度表](lab/behavior-parity.md)列出了各自的证据和限制。

**排错：** 玩家日志在 `CreatePreview/player/client.log`。默认从 `%LOCALAPPDATA%\NextMC\resources-create-v4` 读资源；其他位置可在 CMD 运行 `Play-Create.cmd "D:\path\to\resources-create-v4"`。如果端口被占用，请关掉原来打开的预览服务端。允许从 [Modrinth](https://modrinth.com/mod/create/version/UjX6dr61) 自行取得 `create-1.21.1-6.0.10.jar`，放进 `CreatePreview/player/horizon-mods/create-resources/` 后重启；客户端只读取素材。

## Play

1. On **Windows x64**, open [Next MC beta.2](https://github.com/A5yncX/next-mc-launcher/releases/tag/v0.1.0-beta.2). In **Instances → Optional mod**, install **Create + Atlas** and enable **Create**. In **Downloads**, prepare the game resources. First-time preparation needs [JDK 25](https://adoptium.net/temurin/releases/?version=25). Original game and Create JARs, original textures, and prepared resources are not included. If `VCRUNTIME140` is missing, install the [VC++ x64 runtime](https://aka.ms/vs/17/release/vc_redist.x64.exe).
2. Extract `NextMC-Rust-Create-Preview-Windows-x64.zip` into a **new folder**. Run `Start-Server.cmd`. After `Server is now running` appears, on first launch enter `datapack enable "file/create-passive"` in the server console to activate drops and recipes; then run `Play-Create.cmd`. The first load may take a minute or two. No Rust compilation or Microsoft sign-in is needed to play. The client and server run natively; they do not execute the Java Create mod.
3. Start in Creative and find a creative motor, shaft and cogwheels in your inventory menu. To switch to Survival, enter `gamemode survival CreatePlayer` in the server console. When done, close the game and type `stop` in that console to save.

**Status:** all 106 blocks are registered and partially implemented; **zero have passed full parity**. Two-client and restart tests cover selected drivetrain, Redstone, water wheels, fluid and production systems, same-chunk rotation, and moving farm tools. Cross-chunk motion, moving inventories, and some machine interactions are unfinished. See the [per-block checklist](lab/behavior-parity.md).

**Local preview only:** `127.0.0.1:25586`. The new world lives at `CreatePreview/server/create-lab/`. Do not import your main save, host this build publicly, or replace your existing launcher or its binaries. Read `CreatePreview/player/client.log` for errors. If you prepared resources elsewhere, run `Play-Create.cmd "D:\path\to\resources-create-v4"` in CMD. For optional original textures, obtain `create-1.21.1-6.0.10.jar` yourself from [Modrinth](https://modrinth.com/mod/create/version/UjX6dr61) and put it in `CreatePreview/player/horizon-mods/create-resources/` before restarting; the JAR is only read for assets.

[Create for Horizon](https://github.com/Delete228/create-horizon) is the upstream native port; this preview adds a matched experimental [Pumpkin](https://github.com/Pumpkin-MC/Pumpkin) server and [Horizon](https://github.com/horizon-rust/horizon) client. It is not a Forge, NeoForge, Fabric or Pumpkin WASM add-on. See [BUILD.md](BUILD.md) for source revisions and licensing.
