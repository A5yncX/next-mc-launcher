# Corresponding source / 对应源码

Download `NextMC-Rust-Create-Preview-Source.zip` from the [same release](https://github.com/A5yncX/next-mc-launcher/releases/tag/create-preview.1). The archive contains the modified Pumpkin and Horizon trees, the 61 Pumpkin and 2 Horizon patches, generator and test scripts, lockfiles, build instructions and dependency notices/source where applicable. The GitHub `lab/` folder is the readable patch series; GitHub's automatic “Source code” ZIP contains the launcher repo, **not** the full combined source trees. Keep the source ZIP's directory layout when compiling: Pumpkin's `create-engine` path is relative to the staged Horizon tree.

- Pumpkin: [`eda69440e6369c5f8a05c3f69fc809c40dab93a6`](https://github.com/Pumpkin-MC/Pumpkin/commit/eda69440e6369c5f8a05c3f69fc809c40dab93a6), GPL-3.0 (see the original license and asset notice under `research_pumpkin_horizon/.cache/Pumpkin-eda…/`).
- Horizon: [`9f42064c11efe7ef3e5ed2baad7ddc2a3b36eea0`](https://github.com/horizon-rust/horizon/commit/9f42064c11efe7ef3e5ed2baad7ddc2a3b36eea0), MIT, with third-party notices in its source tree.
- Create for Horizon [`b99cab5`](https://github.com/Delete228/create-horizon/commit/b99cab5) (0.9.0) and [Atlas `66737a3`](https://github.com/MrCloudy2/horizon-atlas/commit/66737a3) (off in the preview), MIT, staged with Horizon Mixins `e8cd0aa`. The included Create art is from the native port. Original Create textures and JARs are not redistributed.

The two trees are separate: use the GPL-3.0 terms for this Pumpkin derivative and the original licenses for Horizon, Create for Horizon and third-party components. The new Pumpkin patches are GPL-3.0; the new Horizon patches are MIT. See `licenses/` in both archives and `source/third-party/` in the source archive. Mojang-derived interoperability data in upstream source is subject to the upstream asset notices; no prepared cache or Minecraft JAR is included.

## Rebuild on Windows x64 / Windows 源码构建

Prerequisites: Git Bash, Python 3.11+, Rust 1.100.0 MSVC (with C++ Build Tools / Windows SDK), your own 26.3 server JAR and prepared Create resources (see [Play](README.md#play)). The tested binaries are the native `fast` client and a server with stripped dev debug info. Extract to a **short path**, such as `D:\CreateSrc`, to avoid Windows path-length errors. Start in the extracted **source archive root**, with the sources already patched:

```bash
ROOT="$PWD"
LAB="$ROOT/research_pumpkin_horizon/create-core"
S="$ROOT/research_create_rust/.create-lab-build/stage"
P="$ROOT/research_pumpkin_horizon/.cache/Pumpkin-eda69440e6369c5f8a05c3f69fc809c40dab93a6"

export RUSTUP_TOOLCHAIN=stable CARGO_PROFILE_DEV_DEBUG=0 CARGO_BUILD_JOBS=8
(cd "$S" && cargo build --locked --profile fast -p horizon-client --target-dir ../game-target)
```

1. Open the rebuilt `research_create_rust/.create-lab-build/game-target/fast/horizon-client.exe` with `--resources <resources-create-v4> --game-dir <new-folder> --home <new-folder> --developer-single-player`. In that folder set `horizon-mods.txt` to `mod.create:true` and `mod.atlas:false` (one per line) before starting. Enter the game once, close it, and find `.horizon-cache/mod-content/<hash>/` with `facts.json`, `items.json` and `registries.json`. Or reuse this cache produced by the same preview client. Do not share it.
2. Point to that cache and your local Mojang server JAR (Next MC beta.2 stores it under `%LOCALAPPDATA%/NextMC/minecraft/server-jars/26.3.jar` after downloading). The generator checks the pinned registry, then codegen rebuilds the generated Rust server code from your local inputs. Do **not** run the entire codegen suite on this Windows revision.

```bash
export PUMPKIN_MINECRAFT_SERVER_JAR='D:/path/to/26.3-server.jar'
CLIENT_CACHE='D:/path/to/player/.horizon-cache/mod-content/<hash>'
python prepare_pumpkin_data.py "$P" "$PUMPKIN_MINECRAFT_SERVER_JAR"
python "$LAB/generate_full_registry.py" --pumpkin "$P" --client-cache "$CLIENT_CACHE"
(cd "$P" && cargo run --locked -p pumpkin-codegen -- block item tag placed_feature placed_features_generated configured_feature configured_features_generated recipes && cargo build --locked -p pumpkin)
```

Copy `$P/target/debug/pumpkin.exe` to `CreatePreview/server/pumpkin-create.exe` and the rebuilt client to `CreatePreview/bin/horizon-client.exe` in the Windows package. For fresh worlds the pack is already included; to regenerate it, `python "$LAB/generate_passive_data.py" path/to/create-lab/datapacks/create-passive` with a new/empty output folder. For validation, `python "$LAB/check_behavior_parity.py" --client "$CLIENT_CACHE"` and the dual-client `smoke_*.py` scripts accept `--pumpkin`, `--client`, `--resources` where applicable; run them on isolated worlds only. The ledger's `--require-complete` gate is deliberately **not** satisfied by this preview.

源码包无需再打补丁；按上述目录构建。先在本机生成 Create 注册表缓存，再运行服务端数据生成。Windows ZIP 可直接玩，无需执行源码构建步骤。
