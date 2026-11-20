#![cfg_attr(windows, windows_subsystem = "windows")]

#[cfg(not(windows))]
fn main() {
    eprintln!("Next MC Launcher GUI requires Windows and WebView2.");
}

#[cfg(windows)]
#[path = "../auth.rs"]
mod auth;
#[cfg(windows)]
mod avatar;
#[cfg(windows)]
mod create_mod;
#[cfg(windows)]
mod credentials;
#[cfg(windows)]
mod desktop;
#[cfg(windows)]
mod install;
#[cfg(windows)]
mod instances;
#[cfg(windows)]
#[path = "../layout.rs"]
mod layout;
#[cfg(windows)]
mod resources;
#[cfg(windows)]
mod window_size;

#[cfg(windows)]
#[derive(Clone, serde::Serialize)]
struct Report {
    phase: &'static str,
    message: String,
    fraction: Option<f64>,
    files: Option<[usize; 2]>,
    bytes: Option<[u64; 2]>,
}

#[cfg(windows)]
const CANCELLED: &str = "已取消。下次会复用所有已校验文件。";

#[cfg(windows)]
fn report(phase: &'static str, message: impl Into<String>) -> Report {
    Report {
        phase,
        message: message.into(),
        fraction: None,
        files: None,
        bytes: None,
    }
}

#[cfg(windows)]
fn main() {
    if let Err(error) = desktop::run() {
        use windows_sys::Win32::UI::WindowsAndMessaging::{MessageBoxW, MB_ICONERROR};
        let title: Vec<_> = "Next MC Launcher\0".encode_utf16().collect();
        let text: Vec<_> =
            format!("无法打开启动器：{error}\n请确认已安装 Microsoft Edge WebView2 Runtime。\0")
                .encode_utf16()
                .collect();
        // The two NUL-terminated buffers stay alive for the synchronous dialog.
        unsafe {
            MessageBoxW(
                std::ptr::null_mut(),
                text.as_ptr(),
                title.as_ptr(),
                MB_ICONERROR,
            )
        };
    }
}
