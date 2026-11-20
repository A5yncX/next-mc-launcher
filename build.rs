use std::{env, path::PathBuf};

fn main() {
    if env::var_os("CARGO_FEATURE_GUI").is_none()
        || env::var("CARGO_CFG_TARGET_OS").as_deref() != Ok("windows")
        || env::var("CARGO_CFG_TARGET_ENV").as_deref() != Ok("msvc")
    {
        return;
    }
    println!("cargo:rerun-if-env-changed=NEXT_MC_LAUNCHER_ICON_RES");
    let path = env::var_os("NEXT_MC_LAUNCHER_ICON_RES")
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("assets/next-mc.res"));
    println!("cargo:rerun-if-changed={}", path.display());
    println!(
        "cargo:rustc-link-arg-bin=next-mc-launcher={}",
        path.display()
    );
}
