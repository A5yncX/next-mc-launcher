use crate::{auth::Session, layout::Layout};
use serde_json::Value;
use std::fs::{self, File};
use std::io::{BufRead, BufReader, Write};
use std::os::windows::process::CommandExt;
use std::path::Path;
use std::process::{Child, Command, Stdio};
use std::sync::atomic::{AtomicBool, Ordering};
use std::time::Duration;

use super::{report, resources, Report, CANCELLED};

const NO_CONSOLE: u32 = 0x0800_0000; // CREATE_NO_WINDOW

pub(super) fn quiet(mut cmd: Command) -> Command {
    cmd.creation_flags(NO_CONSOLE).stdin(Stdio::null());
    cmd
}

pub(super) fn ready(layout: &Layout) -> bool {
    quiet(layout.check())
        .output()
        .is_ok_and(|out| out.status.success())
}

fn kill_tree(child: &mut Child) {
    if let Some(system) = std::env::var_os("SystemRoot") {
        let _ = quiet(Command::new(
            Path::new(&system).join("System32/taskkill.exe"),
        ))
        .args(["/F", "/T", "/PID", &child.id().to_string()])
        .output();
    }
    let _ = child.kill();
    let _ = child.wait();
}

pub(super) fn prepare(
    layout: &Layout,
    source: Option<&Path>,
    download: bool,
    cancel: &AtomicBool,
    emit: &dyn Fn(Report),
) -> Result<String, String> {
    if ready(layout) {
        return Ok("已有兼容的资源，无需重新准备。".into());
    }
    let (cache, java) = resources::collect(layout, source, download, cancel, emit)?;
    let (stage, previous) = (
        layout.resources.with_extension("preparing"),
        layout.resources.with_extension("previous"),
    );
    let log_path = layout.data.join("prepare-gui.log");
    if previous.exists() && !layout.resources.exists() {
        fs::rename(&previous, &layout.resources).map_err(|e| format!("无法恢复原资源：{e}"))?;
    }
    if stage.exists() {
        fs::remove_dir_all(&stage).map_err(|e| format!("无法清理上次未完成的资源：{e}"))?;
    }
    let log = File::create(&log_path).map_err(|e| e.to_string())?;
    let stderr = log.try_clone().map_err(|e| e.to_string())?;
    let reader = File::open(&log_path).map_err(|e| e.to_string())?;
    let mut cmd = quiet(layout.preparer());
    cmd.current_dir(&layout.data)
        .args([
            "--prepare",
            "--complete",
            "--progress",
            "json",
            "--minecraft-dir",
        ])
        .arg(&cache)
        .arg("--server-jar")
        .arg(resources::server_jar(&cache))
        .arg("--output")
        .arg(&stage)
        .stdout(log)
        .stderr(stderr);
    if std::env::var_os("JAVA_HOME").is_none() {
        if let Some(java) = java {
            cmd.arg("--java-home").arg(java);
        }
    }
    emit(report("prepare", "准备 Rust 客户端资源（需要 JDK 25）…"));
    let mut child = cmd
        .spawn()
        .map_err(|e| format!("无法运行资源准备器：{e}"))?;
    let mut reader = BufReader::new(reader);
    let mut line = Vec::new();
    let mut progress = report("prepare", "正在准备游戏资源…");
    let mut failure = None;
    let result = (|| {
        let status = loop {
            if cancel.load(Ordering::Relaxed) {
                return Err(CANCELLED.into());
            }
            let status = child.try_wait().map_err(|e| e.to_string())?;
            while reader
                .read_until(b'\n', &mut line)
                .map_err(|e| e.to_string())?
                > 0
            {
                if line.last() != Some(&b'\n') {
                    break;
                }
                if let Ok(value) = serde_json::from_slice::<Value>(&line) {
                    if let Some(message) = value["message"].as_str() {
                        progress.message = message.into();
                    }
                    if let Some(fraction) = value["fraction"].as_f64() {
                        progress.fraction = Some(fraction);
                    }
                    if let Some(error) = value["error"].as_str() {
                        failure = Some(error.to_owned());
                    }
                    emit(progress.clone());
                }
                line.clear();
            }
            if let Some(status) = status {
                break status;
            }
            std::thread::sleep(Duration::from_millis(100));
        };
        if status.success() {
            Ok(())
        } else {
            Err(format!(
                "资源准备失败：{}。日志：{}",
                failure.unwrap_or_else(|| status.to_string()),
                log_path.display()
            ))
        }
    })();
    if let Err(e) = result {
        if child.try_wait().ok().flatten().is_none() {
            kill_tree(&mut child);
        }
        let _ = fs::remove_dir_all(&stage);
        return Err(e);
    }
    if cancel.load(Ordering::Relaxed) {
        let _ = fs::remove_dir_all(&stage);
        return Err(CANCELLED.into());
    }
    if layout.resources.exists() {
        if previous.exists() {
            fs::remove_dir_all(&previous).map_err(|e| e.to_string())?;
        }
        fs::rename(&layout.resources, &previous).map_err(|e| format!("无法备份旧资源：{e}"))?;
    }
    if let Err(e) = fs::rename(&stage, &layout.resources) {
        if previous.exists() {
            let _ = fs::rename(&previous, &layout.resources);
        }
        return Err(format!("无法启用已准备的资源：{e}"));
    }
    if !ready(layout) {
        let _ = fs::rename(&layout.resources, &stage);
        if previous.exists() {
            let _ = fs::rename(&previous, &layout.resources);
        }
        return Err(format!(
            "资源准备后未通过检查。日志：{}",
            log_path.display()
        ));
    }
    let _ = fs::remove_dir_all(&previous);
    Ok("Minecraft 26.3 资源已就绪，可以开始离线单机。".into())
}

pub(super) fn play(
    layout: &Layout,
    instance: &Path,
    session: Option<&Session>,
    emit: &dyn Fn(Report),
) -> Result<String, String> {
    if !ready(layout) {
        return Err("资源尚未就绪，请先检查并准备资源。".into());
    }
    let cmd = match session {
        Some(s) if s.usable() => layout.game(instance)?,
        Some(_) => return Err("正版会话已过期。请重新登录 Microsoft。".into()),
        None => layout.offline_game(instance)?,
    };
    run_game(cmd, instance, session, emit)
}

pub(super) fn run_game(
    cmd: Command,
    instance: &Path,
    session: Option<&Session>,
    emit: &dyn Fn(Report),
) -> Result<String, String> {
    let mut cmd = quiet(cmd);
    if session.is_some() {
        cmd.arg("--session-stdin").stdin(Stdio::piped());
    }
    let log_path = instance.join("play-gui.log");
    let log = File::create(&log_path).map_err(|e| e.to_string())?;
    cmd.stderr(log.try_clone().map_err(|e| e.to_string())?)
        .stdout(log);
    let mut game = cmd.spawn().map_err(|e| format!("游戏未能启动：{e}"))?;
    if let Some(session) = session {
        let write = game
            .stdin
            .take()
            .expect("piped stdin")
            .write_all(session.body().as_bytes());
        if let Err(e) = write {
            let _ = game.kill();
            let _ = game.wait();
            return Err(format!("无法将正版会话交给游戏：{e}"));
        }
    }
    emit(report("play", "游戏运行中。退出游戏后可再次启动。"));
    let status = game.wait().map_err(|e| e.to_string())?;
    if !status.success() {
        return Err(format!(
            "游戏异常退出（{status}）。请查看 {}。",
            log_path.display()
        ));
    }
    Ok("游戏已退出。".into())
}
