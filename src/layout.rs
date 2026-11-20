use std::env;
use std::fs::{self, File};
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};

pub(crate) struct Layout {
    pub(crate) root: PathBuf,
    pub(crate) data: PathBuf,
    pub(crate) resources: PathBuf,
    game: PathBuf,
}

impl Layout {
    pub(crate) fn find(root: Option<PathBuf>, resources: Option<PathBuf>) -> Result<Self, String> {
        let absolute = |path| std::path::absolute(path).map_err(|e| e.to_string());
        let root = match root {
            Some(path) => absolute(path)?,
            None => {
                let exe = env::current_exe().map_err(|e| format!("cannot locate launcher: {e}"))?;
                let support = exe.with_file_name("NextMC").join("horizon");
                std::iter::once(support)
                    .chain(exe.ancestors().skip(1).map(|dir| dir.join("horizon")))
                    .find(|dir| dir.join("research-lock.json").is_file())
                    .ok_or("Horizon checkout not found; pass --horizon-dir DIR.")?
            }
        };
        let data = env::var_os("LOCALAPPDATA")
            .filter(|p| !p.is_empty())
            .map(PathBuf::from)
            .ok_or("LOCALAPPDATA is not set.")?
            .join("NextMC");
        let data = absolute(data)?;
        let resources = absolute(resources.unwrap_or_else(|| data.join("resources")))?;
        let game = root.join(format!(
            "target/plain/release/horizon-client{}",
            env::consts::EXE_SUFFIX
        ));
        if !game.is_file() {
            return Err(format!(
                "local Horizon client not found: {}",
                game.display()
            ));
        }
        Ok(Self {
            root,
            data,
            resources,
            game,
        })
    }

    #[cfg(all(windows, feature = "gui"))]
    pub(crate) fn create_variant(&self, root: PathBuf) -> Self {
        Self {
            game: root.join("target/plain/release/horizon-client.exe"),
            root,
            data: self.data.clone(),
            resources: self.data.join("resources-create-v4"),
        }
    }

    pub(crate) fn preparer(&self) -> Command {
        let mut cmd = Command::new(self.root.join(format!(
            "target/plain/release/horizon-prepare{}",
            env::consts::EXE_SUFFIX
        )));
        cmd.arg("--root").arg(&self.root);
        cmd
    }

    pub(crate) fn check(&self) -> Command {
        let mut cmd = self.preparer();
        cmd.args(["--check", "--output"]).arg(&self.resources);
        cmd
    }

    pub(crate) fn acquire(&self) -> Result<File, String> {
        fs::create_dir_all(&self.data).map_err(|e| e.to_string())?;
        let file = File::options()
            .read(true)
            .write(true)
            .create(true)
            .truncate(false)
            .open(self.data.join("operation.lock"))
            .map_err(|e| e.to_string())?;
        file.try_lock()
            .map_err(|e| format!("Next MC 正在执行其他任务，或无法锁定数据目录：{e}"))?;
        Ok(file)
    }

    pub(crate) fn default_instance(&self) -> PathBuf {
        self.data.join("offline-instance")
    }

    pub(crate) fn offline_game(&self, instance: &Path) -> Result<Command, String> {
        let mut cmd = self.game(instance)?;
        cmd.arg("--developer-single-player").stdin(Stdio::null());
        Ok(cmd)
    }

    pub(crate) fn game(&self, instance: &Path) -> Result<Command, String> {
        fs::create_dir_all(instance)
            .map_err(|e| format!("cannot create {}: {e}", instance.display()))?;
        let mut cmd = Command::new(&self.game);
        cmd.current_dir(instance)
            .arg("--resources")
            .arg(&self.resources)
            .arg("--game-dir")
            .arg(instance)
            .arg("--home")
            .arg(instance);
        Ok(cmd)
    }
}
