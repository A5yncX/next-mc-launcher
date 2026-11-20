use crate::layout::Layout;
use std::path::PathBuf;

pub(super) const USAGE: &str = "mc-login play [--horizon-dir DIR] [--resources DIR]";

pub(super) fn run(mut args: impl Iterator<Item = String>) -> Result<i32, String> {
    let (mut root, mut resources) = (None, None);
    while let Some(flag) = args.next() {
        let dest = match flag.as_str() {
            "--horizon-dir" => &mut root,
            "--resources" => &mut resources,
            "--help" | "-h" => {
                println!("{USAGE}\nStart the locally built Horizon client in offline single-player mode. No account required.");
                return Ok(0);
            }
            _ => return Err(format!("unknown play option {flag}\nUsage: {USAGE}")),
        };
        let path = args
            .next()
            .filter(|p| !p.is_empty() && !p.starts_with("--"))
            .ok_or_else(|| format!("{flag} requires a directory"))?;
        *dest = Some(PathBuf::from(path));
    }

    let layout = Layout::find(root, resources)?;
    let _lock = layout.acquire()?;
    if !layout
        .check()
        .status()
        .map_err(|e| format!("cannot run horizon-prepare: {e}"))?
        .success()
    {
        return Err(format!(
            "Horizon resources are not ready: {}. Prepare them with horizon-prepare before playing.",
            layout.resources.display()
        ));
    }
    println!("Starting offline single-player.");
    layout
        .offline_game(&layout.default_instance())?
        .status()
        .map(|status| status.code().unwrap_or(1))
        .map_err(|e| format!("cannot start horizon-client: {e}"))
}
