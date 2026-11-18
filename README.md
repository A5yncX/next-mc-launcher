# Next MC Launcher

An experimental Rust project for launching [Horizon](https://github.com/horizon-rust/horizon).
The current prototype, `mc-login`, handles Microsoft sign-in and exports a
[Horizon session](https://github.com/horizon-rust/horizon/blob/main/docs/api/launch.md).
It does not download or start the game, and it has no GUI.

The sign-in flow uses Microsoft device code, Xbox Live, XSTS, and Minecraft
services to check ownership and read the Minecraft profile.

```
mc-login [--client-id ID] [--session-file PATH] [--print-session]
```

- The client ID is configuration, not code. Register your own Azure app
  (personal accounts, public client flows) and have Mojang approve it for
  the Minecraft API: https://aka.ms/mce-reviewappid. Horizon's own
  registration belongs to Horizon (docs/forking.md).
- The prototype stores tokens in plaintext in `mc-login.json` in the current
  working directory. Delete the file to clear the local sign-in cache.
- `--session-file ./session.json` exports a token for `horizon-client --session-file`.
  `--print-session` prints the token to stdout. Do not commit or share either output.

Build with `cargo build --release`. On Windows, use the Rust MSVC toolchain
and the Visual Studio C++ Build Tools with a Windows SDK.
