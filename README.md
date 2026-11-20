# Next MC Launcher

A Windows desktop launcher for a locally built [Horizon](https://github.com/horizon-rust/horizon)
client. The graphical interface uses [Astryx](https://github.com/meta/astryx).

## Desktop launcher (Windows x64)

Get the setup EXE or portable ZIP from [GitHub Releases](https://github.com/A5yncX/next-mc-launcher/releases) and follow [安装说明](INSTALL.zh-CN.md). No Rust or Node.js is needed to play. The UI is bundled and requires Microsoft Edge WebView2 Runtime.

- Select or create a profile under **实例**, then click **启动游戏** on the left.
  The default profile keeps the old saves; new profiles have independent saves,
  settings and logs. No sign-in is required.
- If resources aren't ready, open **下载** and click **检查并准备本机文件**. It checks the regular Minecraft and
  Horizon install directories; you can also enter a local Minecraft directory.
- Click **下载缺失文件** to allow downloads from Mojang for the pinned 26.3 version.
  The launcher shows file and byte progress, verifies the files, and keeps verified
  files if you cancel or retry. It never writes into an existing Minecraft install.
- Resource preparation requires JDK 25. Set `JAVA_HOME` if the launcher can't
  find it through your installed Minecraft runtime or system configuration.
- Click **Microsoft 正版登录** and use the device code in your browser. The approved
  public app ID is built in; players do not enter it or a client secret. Use
  **使用正版账号启动** after ownership is confirmed, or use **离线启动游戏** at any time.
- Drag a window edge to resize. The normal window size is remembered and fitted to
  the current display when you reopen it. In **设置**, pick **跟随系统**, **浅色**, or
  **深色**. Animations respect the Windows reduced-motion preference.
- The GUI displays your Minecraft skin head when available. It protects the refresh
  token with Windows DPAPI for the current Windows user and restores the session
  when reopened. **退出 Microsoft 登录** removes the saved login. The launcher does
  not copy this login into the portable ZIP or use the CLI's plaintext cache.

From this checkout, build the desktop launcher with PowerShell:

```powershell
Push-Location ui
npm ci
npm run build
Pop-Location
cargo build --release --locked --features gui --bin next-mc-launcher
```

### Optional Create + Atlas component

In **实例 → 可选模组**, click **安装 Create + Atlas** to fetch the pinned, prebuilt component. Then enable **机械动力（Create）** and prepare its Minecraft resources under **下载**. Both modes share the original download cache, but prepared resources and saves are separate. Create saves stay under `%LOCALAPPDATA%\NextMC\create-instances\<id>` even if you turn the switch off. This beta validates only singleplayer.

**Atlas 小地图和世界地图** is off by default and is remembered per instance; press **M** in game. Create uses its bundled artwork by default. To use the original look, place the official [Create 6.0.10 NeoForge JAR](https://modrinth.com/mod/create/version/UjX6dr61) inside the Create instance's `horizon-mods/create-resources/` (use **打开实例目录**). It is read as data, not executed. No Mojang or original Create assets are redistributed.

## Offline single-player (CLI)

Double-click `target\release\mc-login.exe` to skip the desktop interface, or run:

```powershell
.\target\release\mc-login.exe
```

The `play` subcommand also starts offline and accepts custom paths.

No account, token cache, or network sign-in is used. LAN and multiplayer are
unavailable in this mode. Saves and logs go under `%LOCALAPPDATA%\NextMC\offline-instance`.
Your existing Minecraft and Horizon saves are not used.

The default layout is sibling checkouts named `mc-login` and `horizon`, with the
locally built `horizon-client.exe` and `horizon-prepare.exe` in Horizon's
`target/plain/release`. Keep both checkouts in this layout when using the GUI.
In the CLI, use `play --horizon-dir DIR` if the checkout is elsewhere.
For this layout, build from the Horizon checkout with:

```powershell
cargo build --release --locked --target-dir target/plain -p horizon-game -p horizon-prepare --no-default-features --features horizon-game/audio,horizon-game/controllers
```

For a Horizon checkout with the local window branding patch, set
`NEXT_MC_WINDOW_TITLE=next-mc-launcher` before building. The branded client reads
an icon from local Minecraft assets at runtime; it does not bundle the official icon.

For the Windows portable ZIP, see [BUILD.md](BUILD.md) and
[INSTALL.zh-CN.md](INSTALL.zh-CN.md). Run `python tools/package_windows.py` after
building both checkouts and preparing the Horizon exporters.

`play` checks `%LOCALAPPDATA%\NextMC\resources` before starting. Use
`play --resources DIR` to use a different prepared directory. If the check fails,
follow the [Horizon preparation guide](https://github.com/horizon-rust/horizon/blob/main/docs/api/launch-guide.md)
with the same build of `horizon-prepare` and set its `--output` to the directory
above. Reuse the Minecraft files already installed for the version shown by
`horizon-prepare --launch-api`; if you need files, use the official Minecraft
launcher and the `downloads.server` URL in Mojang's version JSON, or use the
GUI's manual download. No Minecraft game files are bundled.

## Microsoft sign-in and session export

The sign-in flow uses Microsoft device code, Xbox Live, XSTS, and Minecraft
services to check ownership and read the Minecraft profile. It exports a
[Horizon session](https://github.com/horizon-rust/horizon/blob/main/docs/api/launch.md).

```
mc-login login [--client-id ID] [--session-file PATH] [--print-session]
```

- The CLI uses the same default app ID. Developers can override it using
  `--client-id ID` or `HORIZON_MSA_CLIENT_ID`. Existing commands with sign-in flags
  still work without the `login` subcommand.
- For a fork, register your own Azure app
  (personal accounts, public client flows) and have Mojang approve it for
  the Minecraft API: https://aka.ms/mce-reviewappid. Horizon's own
  registration belongs to Horizon (docs/forking.md).
- The CLI stores tokens in plaintext in `mc-login.json` in the current
  working directory. Delete the file to clear the local sign-in cache.
- `--session-file ./session.json` exports a token for `horizon-client --session-file`.
  `--print-session` prints the token to stdout. Do not commit or share either output.

Build with `cargo build --release`. On Windows, use the Rust MSVC toolchain
and the Visual Studio C++ Build Tools with a Windows SDK.
