use std::path::PathBuf;
use std::process::Command;
use std::sync::{
    atomic::{AtomicBool, Ordering},
    Arc,
};

use serde::{Deserialize, Serialize};
use tao::{
    event::{Event, WindowEvent},
    event_loop::{ControlFlow, EventLoopBuilder},
    platform::windows::{IconExtWindows, WindowBuilderExtWindows},
    window::{Icon, WindowBuilder},
};
use wry::{
    http::{Method, Request, Response},
    NewWindowResponse, WebContext, WebView, WebViewBuilder, WebViewBuilderExtWindows,
};

use super::{
    avatar, create_mod, credentials, install, instances, report, window_size, Report, CANCELLED,
};
use crate::{auth, layout::Layout};

const ORIGIN: &str = "https://nextmc.local/";
const CSP: &str = "default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'none'";

fn serve(request: &Request<Vec<u8>>) -> Response<&'static [u8]> {
    let (status, mime, body): (u16, &str, &[u8]) = match (
        request.method(),
        request.uri().scheme_str(),
        request.uri().host(),
        request.uri().path(),
    ) {
        (&Method::GET, Some("nextmc"), Some("local"), "/") => (
            200,
            "text/html; charset=utf-8",
            include_bytes!("../../ui/dist/index.html"),
        ),
        (&Method::GET, Some("nextmc"), Some("local"), "/app.js") => (
            200,
            "text/javascript; charset=utf-8",
            include_bytes!("../../ui/dist/app.js"),
        ),
        (&Method::GET, Some("nextmc"), Some("local"), "/app.css") => (
            200,
            "text/css; charset=utf-8",
            include_bytes!("../../ui/dist/app.css"),
        ),
        _ => (404, "text/plain", b"not found"),
    };
    Response::builder()
        .status(status)
        .header("Content-Type", mime)
        .header("Content-Security-Policy", CSP)
        .header("X-Content-Type-Options", "nosniff")
        .body(body)
        .unwrap()
}

#[derive(Deserialize)]
#[serde(tag = "action", rename_all = "snake_case", deny_unknown_fields)]
enum Action {
    Status,
    Prepare { source: String },
    Download { source: String },
    Play,
    OnlinePlay,
    SignIn,
    OpenVerification,
    SignOut,
    Cancel,
    Reveal,
    RevealInstance,
    CreateInstance { name: String },
    SelectInstance { id: u32 },
    InstallCreate,
    SetCreate { id: u32, enabled: bool },
    SetAtlas { id: u32, enabled: bool },
    WindowDrag,
    WindowMinimize,
    WindowMaximize,
    WindowClose,
}

#[derive(Serialize)]
struct State {
    ready: bool,
    busy: bool,
    cancellable: bool,
    maximized: bool,
    instances: Vec<instances::Instance>,
    selected: u32,
    instance_error: Option<String>,
    create_enabled: bool,
    create_issue: Option<&'static str>,
    create_installable: bool,
    create_ready: bool,
    atlas_enabled: bool,
    challenge: Option<auth::Challenge>,
    player_name: Option<String>,
    player_avatar: Option<String>,
    restoring: bool,
    remembered: bool,
    account_notice: Option<String>,
    progress: Report,
}

impl State {
    fn instance_path(&self, layout: &Layout) -> Option<PathBuf> {
        self.instances
            .iter()
            .find(|item| item.id == self.selected)
            .map(|item| item.path(layout))
    }

    fn update_create(&mut self, layout: &Layout) {
        self.create_enabled = create_mod::enabled(&layout.data, self.selected);
        self.create_issue = create_mod::available(&layout.data).err();
        self.create_installable = create_mod::can_install();
        self.create_ready =
            self.create_issue.is_none() && create_mod::resources_ready(&layout.data);
        self.atlas_enabled =
            self.create_enabled && create_mod::atlas_enabled(&layout.data, self.selected);
    }

    fn send(&self, view: &WebView) {
        if let Ok(json) = serde_json::to_string(self) {
            let _ = view.evaluate_script(&format!("window.nextMCUpdate?.({json});"));
        }
    }
}

struct SignedIn {
    session: auth::Session,
    refresh: Option<String>,
    avatar: Option<String>,
}

impl SignedIn {
    fn from_auth((session, refresh): (auth::Session, Option<String>)) -> Self {
        let avatar = avatar::fetch(session.account.skin_url.as_deref());
        Self {
            session,
            refresh,
            avatar,
        }
    }

    fn display(self, state: &mut State) -> Arc<auth::Session> {
        state.player_name = Some(self.session.account.name.clone());
        state.player_avatar = self.avatar;
        Arc::new(self.session)
    }
}

const NOT_SAVED: &str = "本次已登录，但无法保存登录。再次打开启动器时可能需要重新登录。";

enum Message {
    Action(Action),
    Progress(Report),
    Challenge(auth::Challenge),
    SignInFinished(Result<SignedIn, String>),
    Restored(credentials::Saved, Result<SignedIn, String>),
    Finished { ready: bool, progress: Report },
}

fn open_verification(challenge: &auth::Challenge) -> bool {
    use windows_sys::Win32::UI::{Shell::ShellExecuteW, WindowsAndMessaging::SW_SHOWNORMAL};
    let url: Vec<_> = challenge
        .verification_uri
        .encode_utf16()
        .chain([0])
        .collect();
    let null = std::ptr::null();
    // The URI was checked against fixed Microsoft device-sign-in addresses in auth.
    unsafe {
        ShellExecuteW(
            std::ptr::null_mut(),
            null,
            url.as_ptr(),
            null,
            null,
            SW_SHOWNORMAL,
        ) as isize
            > 32
    }
}

pub(super) fn run() -> Result<(), Box<dyn std::error::Error>> {
    let events = EventLoopBuilder::<Message>::with_user_event().build();
    let layout = Layout::find(None, None).map(Arc::new);
    let mut state = State {
        ready: false,
        busy: false,
        cancellable: false,
        maximized: false,
        instances: Vec::new(),
        selected: 0,
        instance_error: None,
        create_enabled: false,
        create_issue: None,
        create_installable: false,
        create_ready: false,
        atlas_enabled: false,
        challenge: None,
        player_name: None,
        player_avatar: None,
        restoring: false,
        remembered: false,
        account_notice: None,
        progress: report("check", "等待检查本机资源…"),
    };
    match &layout {
        Ok(layout) => {
            state.update_create(layout);
            match instances::list(&layout.data) {
                Ok(found) => state.instances = found,
                Err(e) => state.instance_error = Some(format!("无法读取实例目录：{e}")),
            }
        }
        Err(e) => state.progress = report("error", e),
    }
    let saved_size = layout
        .as_ref()
        .ok()
        .and_then(|l| window_size::load(&l.data));
    let (mut normal_size, min_size, position) =
        window_size::initial(saved_size, events.primary_monitor());
    let icon = Icon::from_resource(1, None).ok();
    let mut builder = WindowBuilder::new()
        .with_title("Next MC Launcher")
        .with_window_icon(icon.clone())
        .with_taskbar_icon(icon)
        .with_decorations(false)
        .with_undecorated_shadow(true)
        .with_inner_size(normal_size)
        .with_min_inner_size(min_size);
    if let Some(position) = position {
        builder = builder.with_position(position);
    }
    let window = builder.build(&events)?;
    let proxy = events.create_proxy();
    let ipc = proxy.clone();
    let profile = layout
        .as_ref()
        .ok()
        .map(|layout| layout.data.join("webview"));
    let mut context = WebContext::new(profile);
    let web = WebViewBuilder::new_with_web_context(&mut context)
        .with_https_scheme(true)
        .with_custom_protocol("nextmc".into(), |_id, request| {
            serve(&request).map(std::borrow::Cow::Borrowed)
        })
        .with_navigation_handler(|url| url == ORIGIN)
        .with_new_window_req_handler(|_, _| NewWindowResponse::Deny)
        .with_download_started_handler(|_, _| false)
        .with_ipc_handler(move |request| {
            if request.uri().to_string() == ORIGIN && request.body().len() <= 8192 {
                if let Ok(action) = serde_json::from_str(request.body()) {
                    let _ = ipc.send_event(Message::Action(action));
                }
            }
        })
        .with_url("nextmc://local/")
        .build(&window)?;
    let cancel = Arc::new(AtomicBool::new(false));
    let mut close_after_task = false;
    let mut session: Option<Arc<auth::Session>> = None;
    let store = layout
        .as_ref()
        .ok()
        .map(|l| credentials::Store::new(&l.data));
    if let Some(store) = &store {
        state.remembered = store.exists();
        match store.load() {
            Ok(Some(saved)) => {
                state.restoring = true;
                let proxy = proxy.clone();
                std::thread::spawn(move || {
                    let result = auth::renew(auth::CLIENT_ID, &saved.refresh, &|_| {})
                        .map(SignedIn::from_auth);
                    let _ = proxy.send_event(Message::Restored(saved, result));
                });
            }
            Ok(None) => {}
            Err(_) => {
                state.account_notice =
                    Some("无法读取保存的登录。可重新登录，或清除本机登录。".into())
            }
        }
    }
    events.run(move |event, _, flow| {
        let _context = &context;
        *flow = ControlFlow::Wait;
        match event {
            Event::WindowEvent {
                event: WindowEvent::Resized(size),
                ..
            } => {
                let maximized = window.is_maximized();
                if !maximized && !window.is_minimized() && size.width > 0 && size.height > 0 {
                    normal_size = size.to_logical(window.scale_factor());
                }
                if state.maximized != maximized {
                    state.maximized = maximized;
                    state.send(&web);
                }
            }
            Event::LoopDestroyed => {
                if let Ok(layout) = &layout {
                    window_size::save(&layout.data, normal_size);
                }
            }
            Event::WindowEvent {
                event: WindowEvent::CloseRequested,
                ..
            }
            | Event::UserEvent(Message::Action(Action::WindowClose)) => {
                if !state.busy {
                    *flow = ControlFlow::Exit;
                } else if state.progress.phase == "play" {
                    state.progress.message = "请先退出游戏，再关闭启动器。".into();
                    state.send(&web);
                } else {
                    close_after_task = true;
                    if state.cancellable {
                        cancel.store(true, Ordering::Relaxed);
                        state.cancellable = false;
                        state.challenge = None;
                    }
                    state.progress.message = "当前操作结束后，启动器会退出。".into();
                    state.send(&web);
                }
            }
            Event::UserEvent(Message::Action(Action::WindowDrag)) => {
                let _ = window.drag_window();
            }
            Event::UserEvent(Message::Action(Action::WindowMinimize)) => window.set_minimized(true),
            Event::UserEvent(Message::Action(Action::WindowMaximize)) => {
                window.set_maximized(!window.is_maximized())
            }
            Event::UserEvent(Message::Progress(progress)) => {
                if !cancel.load(Ordering::Relaxed) {
                    if progress.phase == "login" {
                        state.challenge = None;
                    }
                    state.progress = progress;
                    state.send(&web);
                }
            }
            Event::UserEvent(Message::Challenge(challenge)) if !cancel.load(Ordering::Relaxed) => {
                state.challenge = Some(challenge);
                state.progress = report(
                    "login",
                    "请在 Microsoft 页面输入设备码。不要将设备码发给别人。",
                );
                state.send(&web);
            }
            Event::UserEvent(Message::Restored(saved, result)) => {
                state.restoring = false;
                let store = store.as_ref().unwrap();
                match result {
                    Ok(value) => match store.save(
                        value.refresh.as_deref().unwrap_or(&saved.refresh),
                        Some(&saved),
                    ) {
                        Ok(false) => {
                            state.account_notice =
                                Some("本机登录已在另一个窗口更新，请重新打开启动器。".into())
                        }
                        saved => {
                            state.account_notice = saved.is_err().then(|| NOT_SAVED.into());
                            session = Some(value.display(&mut state));
                        }
                    },
                    Err(_) => {
                        state.account_notice =
                            Some("暂时无法恢复 Microsoft 登录。可继续离线，或重新登录。".into())
                    }
                }
                state.remembered = store.exists();
                state.send(&web);
            }
            Event::UserEvent(Message::SignInFinished(result)) => {
                if close_after_task {
                    *flow = ControlFlow::Exit;
                    return;
                }
                state.challenge = None;
                state.busy = false;
                state.cancellable = false;
                state.progress = if cancel.load(Ordering::Relaxed) {
                    report("cancelled", auth::CANCELLED)
                } else {
                    match result {
                        Ok(value) => {
                            let store = store.as_ref().unwrap();
                            let saved = match &value.refresh {
                                Some(refresh) => store.save(refresh, None).unwrap_or(false),
                                None => {
                                    let _ = store.forget();
                                    false
                                }
                            };
                            state.remembered = store.exists();
                            session = Some(value.display(&mut state));
                            state.account_notice = (!saved).then(|| NOT_SAVED.into());
                            report("done", "Microsoft 登录成功，已验证 Java 版所有权。")
                        }
                        Err(error) => report("error", error),
                    }
                };
                state.send(&web);
            }
            Event::UserEvent(Message::Finished { ready, progress }) => {
                if close_after_task {
                    *flow = ControlFlow::Exit;
                    return;
                }
                state.ready = ready;
                state.progress = progress;
                state.busy = false;
                state.cancellable = false;
                if let Ok(layout) = &layout {
                    state.update_create(layout);
                }
                state.send(&web);
            }
            Event::UserEvent(Message::Action(action)) => {
                let Ok(layout) = &layout else {
                    state.send(&web);
                    return;
                };
                if matches!(action, Action::Cancel) {
                    if state.cancellable {
                        cancel.store(true, Ordering::Relaxed);
                        state.cancellable = false;
                        state.challenge = None;
                        state.progress.message = if state.progress.phase == "login" {
                            "正在取消登录…"
                        } else {
                            "正在取消，已校验文件会保留…"
                        }
                        .into();
                    }
                    state.send(&web);
                    return;
                }
                if matches!(action, Action::Reveal | Action::RevealInstance) {
                    let path = if matches!(action, Action::Reveal) {
                        Some(layout.data.clone())
                    } else {
                        state.instance_path(layout).map(|path| {
                            if state.create_enabled {
                                create_mod::directory(&layout.data, state.selected)
                            } else {
                                path
                            }
                        })
                    };
                    if let Some(path) = path {
                        let result = std::fs::create_dir_all(&path).and_then(|()| {
                            let system = std::env::var_os("SystemRoot")
                                .unwrap_or_else(|| "C:\\Windows".into());
                            Command::new(PathBuf::from(system).join("explorer.exe"))
                                .arg(path)
                                .spawn()
                        });
                        if let Err(e) = result {
                            state.instance_error = Some(format!("无法打开目录：{e}"));
                            state.send(&web);
                        }
                    }
                    return;
                }
                if matches!(action, Action::OpenVerification) {
                    if let Some(challenge) = &state.challenge {
                        if !open_verification(challenge) {
                            state.progress.message =
                                "无法打开默认浏览器。请在浏览器手动输入上面的网址。".into();
                            state.send(&web);
                        }
                    }
                    return;
                }
                if state.busy {
                    state.send(&web);
                    return;
                }
                match &action {
                    Action::SignIn => {
                        if state.restoring || state.player_name.is_some() {
                            return;
                        }
                        state.account_notice = None;
                        cancel.store(false, Ordering::Relaxed);
                        state.busy = true;
                        state.cancellable = true;
                        state.progress = report("login", "正在向 Microsoft 请求设备码…");
                        state.send(&web);
                        let (cancel, proxy) = (Arc::clone(&cancel), proxy.clone());
                        std::thread::spawn(move || {
                            let result = auth::sign_in(
                                auth::CLIENT_ID,
                                true,
                                &cancel,
                                &|code| {
                                    let _ = proxy.send_event(Message::Challenge(code));
                                },
                                &|phase| {
                                    let _ =
                                        proxy.send_event(Message::Progress(report("login", phase)));
                                },
                            )
                            .map(SignedIn::from_auth);
                            let _ = proxy.send_event(Message::SignInFinished(result));
                        });
                        return;
                    }
                    Action::SignOut => {
                        if state.restoring {
                            return;
                        }
                        if store.as_ref().unwrap().forget().is_err() {
                            state.account_notice = Some("无法清除本机登录，请稍后再试。".into());
                            state.send(&web);
                            return;
                        }
                        session = None;
                        state.player_name = None;
                        state.player_avatar = None;
                        state.remembered = false;
                        state.account_notice = None;
                        state.progress =
                            report("done", "已退出 Microsoft 登录，离线单机仍可使用。");
                        state.send(&web);
                        return;
                    }
                    Action::CreateInstance { name } => {
                        let result = (|| {
                            let _lock = layout.acquire()?;
                            let id = instances::create(&layout.data, name)?;
                            state.instances =
                                instances::list(&layout.data).map_err(|e| e.to_string())?;
                            state.selected = id;
                            state.update_create(layout);
                            Ok::<_, String>(())
                        })();
                        state.instance_error = result.err();
                        state.send(&web);
                        return;
                    }
                    Action::SelectInstance { id } => {
                        if state.instances.iter().any(|item| item.id == *id) {
                            state.selected = *id;
                            state.instance_error = None;
                            state.update_create(layout);
                        }
                        state.send(&web);
                        return;
                    }
                    Action::SetCreate { id, enabled } => {
                        if *id == state.selected && state.instance_path(layout).is_some() {
                            let result = (|| {
                                let _lock = layout.acquire()?;
                                if *enabled {
                                    create_mod::available(&layout.data)?;
                                }
                                create_mod::set_enabled(&layout.data, *id, *enabled)
                                    .map_err(|e| format!("无法保存机械动力开关：{e}"))
                            })();
                            state.instance_error = result.err();
                            state.update_create(layout);
                        }
                        state.send(&web);
                        return;
                    }
                    Action::SetAtlas { id, enabled } => {
                        if *id == state.selected && state.instance_path(layout).is_some() {
                            let result = (|| {
                                let _lock = layout.acquire()?;
                                if !create_mod::enabled(&layout.data, *id) {
                                    return Err("请先启用机械动力。".into());
                                }
                                if *enabled {
                                    create_mod::available(&layout.data)?;
                                }
                                create_mod::set_atlas(&layout.data, *id, *enabled)
                                    .map_err(|e| format!("无法保存 Atlas 开关：{e}"))
                            })();
                            state.instance_error = result.err();
                            state.update_create(layout);
                        }
                        state.send(&web);
                        return;
                    }
                    _ => {}
                }
                let selected = state.selected;
                let create = create_mod::enabled(&layout.data, selected);
                if create && matches!(action, Action::OnlinePlay) {
                    state.progress = report("error", create_mod::OFFLINE_ONLY);
                    state.send(&web);
                    return;
                }
                let online_session = if matches!(action, Action::OnlinePlay) {
                    if let Some(value) = session.as_ref().filter(|value| value.usable()) {
                        Some(Arc::clone(value))
                    } else {
                        session = None;
                        state.player_name = None;
                        state.player_avatar = None;
                        state.progress =
                            report("error", "没有有效正版会话，请重新登录 Microsoft。");
                        state.send(&web);
                        return;
                    }
                } else {
                    None
                };
                let instance = state.instance_path(layout);
                let (phase, message, cancellable) = match &action {
                    Action::InstallCreate => ("download", "正在安装 Create + Atlas 组件…", false),
                    Action::Prepare { .. } | Action::Download { .. } => {
                        ("verify", "正在检查文件…", true)
                    }
                    Action::Play if create => ("play", "正在验证并启动机械动力…", false),
                    Action::Play => ("play", "正在启动离线单机…", false),
                    Action::OnlinePlay => ("play", "正在用正版账号启动…", false),
                    _ => ("check", "正在检查资源状态…", false),
                };
                cancel.store(false, Ordering::Relaxed);
                state.busy = true;
                state.cancellable = cancellable;
                state.progress = report(phase, message);
                state.send(&web);
                let layout = Arc::clone(layout);
                let cancel = Arc::clone(&cancel);
                let proxy = proxy.clone();
                std::thread::spawn(move || {
                    let emit = |progress| {
                        let _ = proxy.send_event(Message::Progress(progress));
                    };
                    let result = (|| match action {
                        Action::Status => Ok(if install::ready(&layout) {
                            "本机已有兼容资源，可以直接开始单机。".into()
                        } else {
                            "未找到可用资源。请选择检查本机文件，或手动下载缺失文件。".into()
                        }),
                        Action::InstallCreate => {
                            let _lock = layout.acquire()?;
                            create_mod::install_component(&layout.data, &emit)
                        }
                        Action::Prepare { ref source } | Action::Download { ref source } => {
                            let _lock = layout.acquire()?;
                            let source = (!source.trim().is_empty())
                                .then(|| std::path::Path::new(source.trim()));
                            let target =
                                create.then(|| create_mod::variant(&layout)).transpose()?;
                            install::prepare(
                                target.as_ref().unwrap_or(&layout),
                                source,
                                matches!(action, Action::Download { .. }),
                                &cancel,
                                &emit,
                            )
                        }
                        Action::Play | Action::OnlinePlay => {
                            let _lock = layout.acquire()?;
                            let instance = instance.as_deref().ok_or("请选择可用实例。")?;
                            if create_mod::enabled(&layout.data, selected) {
                                if matches!(action, Action::OnlinePlay) {
                                    return Err(create_mod::OFFLINE_ONLY.into());
                                }
                                let dir = create_mod::directory(&layout.data, selected);
                                let target = create_mod::variant(&layout)?;
                                if !install::ready(&target) {
                                    return Err("请先在「下载」页准备机械动力资源。".into());
                                }
                                create_mod::prepare_instance(&dir).map_err(|e| {
                                    format!("无法验证 Create 原版贴图或写入设置：{e}")
                                })?;
                                let mut cmd = target.game(&dir)?;
                                cmd.env_remove("HORIZON_ACCOUNT_SESSIONS");
                                install::run_game(cmd, &dir, None, &emit)
                            } else {
                                install::play(&layout, instance, online_session.as_deref(), &emit)
                            }
                        }
                        _ => unreachable!(),
                    })();
                    let progress = match result {
                        Ok(message) => report("done", message),
                        Err(message) if message == CANCELLED => report("cancelled", message),
                        Err(message) => report("error", message),
                    };
                    let _ = proxy.send_event(Message::Finished {
                        ready: install::ready(&layout),
                        progress,
                    });
                });
            }
            _ => {}
        }
    });
}
