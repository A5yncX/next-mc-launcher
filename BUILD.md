# Build / rebuild from the portable package

Start in the extracted `NextMC/` support folder. Its `source/mc-login` and `source/horizon` are the launcher and Horizon source trees used by this release, with Cargo and npm lockfiles. See `BUILD-INFO.txt` for the upstream Horizon revision and native toolchain. The included Horizon source is modified to use a local window title and look up an installed Minecraft icon at runtime. The official icon is not distributed.

On Windows x64 use the Rust MSVC toolchain, Visual Studio C++ Build Tools and Windows SDK, Node.js 22+, and JDK 25. Run the native build from an x64 Developer PowerShell:

```powershell
Set-Location source/horizon
$env:NEXT_MC_WINDOW_TITLE = 'next-mc-launcher'
Remove-Item Env:NEXT_MC_WINDOW_ICON_FILE -ErrorAction SilentlyContinue
$env:RUSTFLAGS = '-C target-feature=+crt-static'
cargo build --release --locked --target-dir target/plain -p horizon-game -p horizon-prepare --no-default-features --features horizon-game/audio,horizon-game/controllers
Remove-Item Env:RUSTFLAGS
Set-Location ../mc-login
npm --prefix ui ci
npm --prefix ui run build
$env:NEXT_MC_CREATE_COMPONENT = Get-Content ../../create-component.json -Raw
cargo build --release --locked --features gui --bin next-mc-launcher
Remove-Item Env:NEXT_MC_CREATE_COMPONENT
```

To run modified binaries, replace `next-mc-launcher.exe` beside the `NextMC/` folder and the Horizon binaries under `NextMC/horizon/target/plain/release/`. The precompiled `horizon/exporters` bundle is for the bundled exporter sources and lockfile. If you change those, rebuild the exporters using a permitted Minecraft installation and `horizon-prepare compile-exporters` (see `source/horizon/docs/api/launch-guide.md`). Dependency licence texts and Symphonia source are under `licenses` and `source/third-party` respectively.

### Optional Minecraft icon for local builds

From the `mc-login` checkout, generate icon resources from your installed Java 26.3 assets (change `$assets` if needed):

```powershell
$assets = "$env:APPDATA\horizon-launcher\minecraft\assets"
$icons = "$env:LOCALAPPDATA\NextMC\local-icons"
python tools/local_minecraft_icon.py $assets $icons
$env:NEXT_MC_LAUNCHER_ICON_RES = "$icons\minecraft-icon.res"
cargo build --release --locked --features gui --bin next-mc-launcher
Remove-Item Env:NEXT_MC_LAUNCHER_ICON_RES
```

For the regular game, set `NEXT_MC_WINDOW_ICON_FILE` to `$icons\minecraft-icon-32.png` and use the native build command above with `cargo rustc`, `-p horizon-game --bin horizon-client` in place of the two packages, and append `-- -C "link-arg=$icons\minecraft-icon.res"`. Do not redistribute these icon-embedded EXEs; rebuild without the icon resource before making the portable ZIP.

### Create + Atlas component

`NextMC-Create-Atlas-Source.zip` contains the staged Horizon source compiled with Create and Atlas. Sources: [Horizon `9f42064`](https://github.com/horizon-rust/horizon/commit/9f42064), [Create for Horizon `b99cab5`](https://github.com/Delete228/create-horizon/commit/b99cab5), [Atlas `66737a3`](https://github.com/MrCloudy2/horizon-atlas/commit/66737a3), staged using Horizon Mixins `e8cd0aa`. Build from `source/` in the extracted component source archive:

```powershell
cargo +stable build --locked --profile fast --target-dir game-target -p horizon-client --bin horizon-client --config profile.fast.opt-level=1 --config profile.fast.package.horizon-client.opt-level=0
cargo +stable build --locked --profile fast --target-dir prepare-target -p horizon-prepare
```

The component uses its own v4 exporter bundle and its own resource cache. Do not substitute the ordinary v5 preparer or exporter bundle. For release assembly, run `python tools/release_windows.py --help` in the launcher Git checkout (next to the Horizon checkout; apply `tools/horizon-local.patch` at the revision in `BUILD-INFO.txt`). Use the `component` step with the staged source, binaries, matching exporter bundle, mod licenses and pinned DXC files. Then run `release` with the same output directory, DXC directory and `--iscc` pointing to Inno Setup 6. Install UI packages with `npm --prefix ui ci` before packaging. These steps verify the pinned component and create checksums, a ZIP and an installer from the same payload. To reuse the beta.1 component for beta.2, copy its verified ZIP and `create-component.json` to the new output directory; no engine rebuild is needed.

### Developer CLI

The player package does not ship `mc-login.exe`. To build it from source, use `cargo build --release --locked --bin mc-login`. Run `mc-login play --horizon-dir DIR` for offline singleplayer; add `--resources DIR` to override prepared resources. Use `mc-login login --help` for Microsoft device-code sign-in and session export. Its local `mc-login.json` cache and any exported session files contain plaintext tokens; do not share them. Forks must register and obtain approval for their own [Minecraft API client ID](https://aka.ms/mce-reviewappid).
