use std::fs::{self, File};
use std::io::Read;
use std::path::Path;
use tao::{
    dpi::{LogicalSize, PhysicalPosition, PhysicalSize},
    monitor::MonitorHandle,
    platform::windows::MonitorHandleExtWindows,
};
use windows_sys::Win32::Graphics::Gdi::{GetMonitorInfoW, MONITORINFO};

pub(super) type Size = LogicalSize<u32>;
const DEFAULT: Size = Size::new(1060, 720);
const MIN: Size = Size::new(440, 460);

pub(super) fn load(data: &Path) -> Option<Size> {
    let mut text = String::new();
    File::open(data.join("launcher-window.txt"))
        .ok()?
        .take(64)
        .read_to_string(&mut text)
        .ok()?;
    parse(&text)
}

fn parse(text: &str) -> Option<Size> {
    let (width, height) = text.trim().split_once('x')?;
    let size = Size::new(width.parse().ok()?, height.parse().ok()?);
    (size.width > 0 && size.height > 0).then_some(size)
}

pub(super) fn save(data: &Path, size: Size) {
    let path = data.join("launcher-window.txt");
    let text = format!("{}x{}\n", size.width, size.height);
    if load(data) != Some(size) && fs::create_dir_all(data).is_ok() {
        let _ = fs::write(path, text);
    }
}

fn fit(saved: Option<Size>, work: Size) -> (Size, Size) {
    let limit = |n: u32| n.saturating_sub(32).max(1);
    let max = Size::new(limit(work.width), limit(work.height));
    let min = Size::new(MIN.width.min(max.width), MIN.height.min(max.height));
    let size = saved.unwrap_or(DEFAULT);
    (
        Size::new(
            size.width.clamp(min.width, max.width),
            size.height.clamp(min.height, max.height),
        ),
        min,
    )
}

pub(super) fn initial(
    saved: Option<Size>,
    monitor: Option<MonitorHandle>,
) -> (Size, Size, Option<PhysicalPosition<i32>>) {
    let Some(monitor) = monitor else {
        return (saved.unwrap_or(DEFAULT), MIN, None);
    };
    let mut info = MONITORINFO {
        cbSize: std::mem::size_of::<MONITORINFO>() as u32,
        ..Default::default()
    };
    // The taskbar can reduce the useful area even when the display resolution is unchanged.
    if unsafe { GetMonitorInfoW(monitor.hmonitor() as _, &mut info) } == 0 {
        let (size, min) = fit(saved, monitor.size().to_logical(monitor.scale_factor()));
        return (size, min, None);
    }
    let rect = info.rcWork;
    let scale = monitor.scale_factor();
    let work = PhysicalSize::new(
        (rect.right - rect.left) as u32,
        (rect.bottom - rect.top) as u32,
    )
    .to_logical(scale);
    let (size, min) = fit(saved, work);
    let physical = size.to_physical::<i32>(scale);
    let position = PhysicalPosition::new(
        (rect.left + rect.right - physical.width) / 2,
        (rect.top + rect.bottom - physical.height) / 2,
    );
    (size, min, Some(position))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn saved_size_is_validated_and_fits_the_current_work_area() {
        assert!(parse("broken").is_none());
        assert!(parse("0x540").is_none());
        assert_eq!(
            fit(parse("973x618\n"), Size::new(1600, 900)),
            (Size::new(973, 618), MIN)
        );
        assert_eq!(
            fit(parse("9999x8888"), Size::new(1024, 660)),
            (Size::new(992, 628), MIN)
        );
        assert_eq!(
            fit(None, Size::new(400, 450)),
            (Size::new(368, 418), Size::new(368, 418))
        );
    }
}
