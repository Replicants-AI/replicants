#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]
mod native;
mod brain;
mod shell;
use native::Rect;
use serde::Deserialize;
use serde_json::{json, Value};
use std::{sync::{atomic::{AtomicBool, Ordering}, Mutex}, thread, time::{Duration, Instant}};
use tauri::{Emitter, Manager, PhysicalPosition, PhysicalSize, State, WebviewUrl, WebviewWindowBuilder};
use tauri_plugin_global_shortcut::{GlobalShortcutExt, ShortcutState};

#[derive(Default)]
struct OverlayState {
    regions: Mutex<Vec<Rect>>, capture: AtomicBool,
    view: Mutex<Value>, mock: Mutex<Value>,
    inspector: Mutex<Value>,
    inspector_text: Mutex<String>,
}
#[derive(Deserialize)]
struct ViewReport { regions: Vec<Rect>, capture: bool, body: Value }

#[tauri::command]
fn report_view(report: ViewReport, state: State<'_, OverlayState>) {
    *state.regions.lock().unwrap() = report.regions;
    state.capture.store(report.capture, Ordering::Relaxed);
    *state.view.lock().unwrap() = report.body;
}
fn excluded(app: &tauri::AppHandle) -> Vec<isize> {
    let room_open = shell::room_is_open(app);
    app.webview_windows().values().filter(|w| w.label() != "room" || !room_open).filter_map(|w| w.hwnd().ok().map(|h| h.0 as isize)).collect()
}
fn world_snapshot(app: &tauri::AppHandle) -> native::Desktop {
    let mut desktop = native::snapshot(excluded(app));
    if let Some(room) = app.get_webview_window("room") {
        if let Ok(hwnd) = room.hwnd() {
            let id = format!("{:x}", hwnd.0 as usize);
            for window in &mut desktop.windows { if window.id == id { window.id = "replicants-room".into(); } }
        }
    }
    desktop
}
#[tauri::command]
fn desktop_snapshot(app: tauri::AppHandle) -> native::Desktop { world_snapshot(&app) }
#[tauri::command]
fn active_app_name() -> Option<String> { native::active_app() }
#[tauri::command]
fn runtime_options() -> Value { json!({"native_room":true,"verify_hidden": std::env::var("REPLICANTS_VERIFY_HIDDEN").as_deref() == Ok("1"), "development":cfg!(debug_assertions)}) }
#[tauri::command]
fn mock_state(state: State<'_, OverlayState>) -> Value { state.mock.lock().unwrap().clone() }
#[tauri::command]
fn set_mock_state(value: Value, app: tauri::AppHandle, state: State<'_, OverlayState>) {
    *state.mock.lock().unwrap() = value.clone();
    let _ = app.emit_to("overlay", "mock-state", value);
}
#[tauri::command]
fn view_state(state: State<'_, OverlayState>) -> Value { state.view.lock().unwrap().clone() }
#[tauri::command]
fn cache_inspector(value: Value, window: tauri::WebviewWindow, state: State<'_, OverlayState>) {
    if window.label() == "overlay" { *state.inspector.lock().unwrap() = value; }
}
#[tauri::command]
fn inspector_state(app: tauri::AppHandle, state: State<'_, OverlayState>) -> Value {
    let _ = app.emit_to("overlay", "brain-control", json!({"name":"inspect"}));
    state.inspector.lock().unwrap().clone()
}
#[tauri::command]
fn request_control(value: Value, app: tauri::AppHandle) { let _ = app.emit_to("overlay", "brain-control", value); }
#[tauri::command]
fn report_inspector_render(text: String, window: tauri::WebviewWindow, state: State<'_, OverlayState>) {
    if window.label() == "inspector" { *state.inspector_text.lock().unwrap() = text.chars().take(40000).collect(); }
}
#[tauri::command]
fn open_chat(app: tauri::AppHandle) {
    panel(&app, "conversation");
}
#[tauri::command]
fn conception_choice(value: Value, app: tauri::AppHandle) { let _ = app.emit_to("overlay", "conception-choice", value); }
#[tauri::command]
fn show_conception(app: tauri::AppHandle) { panel(&app, "birth"); }
#[tauri::command]
fn show_body(app: tauri::AppHandle) {
    if let Some(w) = app.get_webview_window("birth") { let _ = w.close(); }
    if std::env::var("REPLICANTS_VERIFY_HIDDEN").as_deref() != Ok("1") {
        if let Some(w) = app.get_webview_window("overlay") { let _ = w.show(); }
    }
}
#[tauri::command]
fn set_body_visible(visible: bool, app: tauri::AppHandle) {
    if std::env::var("REPLICANTS_VERIFY_HIDDEN").as_deref() == Ok("1") { return; }
    if let Some(window) = app.get_webview_window("overlay") {
        if visible { let _ = window.show(); } else { let _ = window.hide(); }
    }
}
static PANEL_BUILD: Mutex<()> = Mutex::new(());

fn panel(app: &tauri::AppHandle, label: &str) {
    // WebView2 creation from a synchronous IPC/menu callback can deadlock the
    // Windows event loop. Every entry point uses the same off-thread builder.
    let app = app.clone();
    let label = label.to_string();
    tauri::async_runtime::spawn_blocking(move || {
        let Ok(_guard) = PANEL_BUILD.lock() else { return; };
        if let Err(error) = build_panel(&app, &label) {
            let reason = format!("Could not open {label}: {error}");
            eprintln!("Replicants: {reason}");
            let _ = app.emit("product-update", json!({"kind":"error", "value":{"reason":reason}}));
        }
    });
}

fn build_panel(app: &tauri::AppHandle, label: &str) -> tauri::Result<()> {
    if let Some(w) = app.get_webview_window(label) { w.show()?; w.set_focus()?; return Ok(()); }
    let mut builder = WebviewWindowBuilder::new(app, label, WebviewUrl::App(format!("index.html?view={label}").into()))
        .title(match label { "home" => "Replicants", "conversation" => "Replicants · conversation", "settings" => "Replicants · settings", "room" => "Replicants · Room", "birth" => "Replicants · a new life", "inspector" => "Replicants · inspector", _ => "Replicants · body studio" })
        .inner_size(if label == "birth" { 780.0 } else { 600.0 }, 760.0).min_inner_size(360.0, 480.0).resizable(true)
        .visible(std::env::var("REPLICANTS_VERIFY_HIDDEN").as_deref() != Ok("1"));
    if let Some(path) = verification_webview_directory() {
        builder = builder.data_directory(path).additional_browser_args(verification_browser_arguments());
    }
    builder.build()?;
    Ok(())
}

fn verification_webview_directory() -> Option<std::path::PathBuf> {
    if std::env::var("REPLICANTS_VERIFY_HIDDEN").as_deref() != Ok("1") { return None; }
    std::env::var_os("REPLICANTS_SESSION_PATH").map(std::path::PathBuf::from)
        .and_then(|p| p.parent().map(|parent| parent.join("webview")))
}

fn verification_browser_arguments() -> &'static str {
    // Wry supplies its own arguments, which override the WebView2 environment
    // variable. Preserve its defaults and expose CDP only in explicit isolated
    // verification with a separate data directory. Normal launches have no port.
    "--disable-features=msWebOOUI,msPdfOOUI,msSmartScreenProtection --autoplay-policy=no-user-gesture-required --remote-debugging-port=9223"
}

fn main() {
    let mut context = tauri::generate_context!();
    // Independent verification must not borrow the user's WebView processes:
    // that also lets resource measurements include the complete renderer tree.
    if verification_webview_directory().is_some() {
        for window in &mut context.config_mut().app.windows { window.create = false; }
    }
    let result = tauri::Builder::default()
        .manage(OverlayState::default())
        .manage(shell::ProductState::default())
        .plugin(tauri_plugin_single_instance::init(|app, _, _| { panel(app, "home"); }))
        .plugin(tauri_plugin_global_shortcut::Builder::new().with_handler(|app, _, event| {
            if event.state() == ShortcutState::Pressed { open_chat(app.clone()); }
        }).build())
        .invoke_handler(tauri::generate_handler![report_view, desktop_snapshot, active_app_name, runtime_options, mock_state, set_mock_state, view_state, cache_inspector, inspector_state, request_control, report_inspector_render, open_chat, conception_choice, show_conception, show_body, set_body_visible, brain::desktop_connection, brain::launch_brain, brain::launch_status, brain::brain_running, brain::finish_lifecycle, brain::choose_replicant, shell::setup_check, shell::preferences, shell::life_library, shell::open_life, shell::show_life_folder, shell::save_preferences, shell::download_model, shell::prepare_local, shell::cancel_download, shell::cache_product, shell::product_snapshot, shell::show_panel, shell::request_lifecycle, shell::send_message, shell::open_help, shell::export_diagnostics])
        .on_window_event(|window, event| {
            if window.label() == "room" {
                if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                    api.prevent_close();
                    let _ = window.hide();
                    let _ = window.app_handle().emit_to("overlay", "brain-control", json!({"name":"room_close"}));
                }
            }
            if window.label() == "overlay" {
                if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                    api.prevent_close();
                    let _ = window.emit("lifecycle", json!({"kind":"quit"}));
                }
            }
            if ["home", "conversation", "settings"].contains(&window.label()) {
                if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                    api.prevent_close();
                    let _ = window.hide();
                }
            }
        })
        .setup(|app| {
            let verify_hidden = std::env::var("REPLICANTS_VERIFY_HIDDEN").as_deref() == Ok("1");
            let w = if let Some(window) = app.get_webview_window("overlay") { window } else {
                let cfg = app.config().app.windows.iter().find(|w| w.label == "overlay").unwrap();
                let mut builder = WebviewWindowBuilder::from_config(app.handle(), cfg)?;
                if let Some(path) = verification_webview_directory() {
                    builder = builder.data_directory(path).additional_browser_args(verification_browser_arguments());
                }
                builder.build()?
            };
            let (m, _) = native::primary();
            w.set_position(PhysicalPosition::new(m.x as i32, m.y as i32))?;
            w.set_size(PhysicalSize::new(m.width as u32, m.height as u32))?;
            w.set_ignore_cursor_events(true)?;
            if !verify_hidden {
                let _ = app.global_shortcut().register("Ctrl+Alt+R");
                panel(app.handle(), "home");
            }
            use tauri::menu::{Menu, MenuItem};
            let studio = MenuItem::with_id(app, "studio", "Mock body studio", true, None::<&str>)?;
            let chat = MenuItem::with_id(app, "chat", "Talk · Ctrl+Alt+R", true, None::<&str>)?;
            let connect = MenuItem::with_id(app, "connect", "Connect local brain", true, None::<&str>)?;
            let birth = MenuItem::with_id(app, "birth", "Birth new Replicant", true, None::<&str>)?;
            let open = MenuItem::with_id(app, "open", "Open .replicant…", true, None::<&str>)?;
            let inspector = MenuItem::with_id(app, "inspector", "Inspector", true, None::<&str>)?;
            let sleep = MenuItem::with_id(app, "sleep", "Sleep", true, None::<&str>)?;
            let wake = MenuItem::with_id(app, "wake", "Wake", true, None::<&str>)?;
            let ambient = MenuItem::with_id(app, "ambient", "Toggle ambient senses", true, None::<&str>)?;
            let active_app = MenuItem::with_id(app, "active_app", "Toggle active-app sense (off by default)", true, None::<&str>)?;
            let real = MenuItem::with_id(app, "time_1", "Dev clock: real time", true, None::<&str>)?;
            let fast = MenuItem::with_id(app, "time_60", "Dev clock: 60×", true, None::<&str>)?;
            let day = MenuItem::with_id(app, "time_360", "Dev clock: 360× (four-minute day)", true, None::<&str>)?;
            let quit = MenuItem::with_id(app, "quit", "Save and quit", true, None::<&str>)?;
            let home = MenuItem::with_id(app, "home", "Open Replicants", true, None::<&str>)?;
            let settings = MenuItem::with_id(app, "settings", "Settings and local models", true, None::<&str>)?;
            let menu = if cfg!(debug_assertions) {
                Menu::with_items(app, &[&home, &connect, &birth, &open, &inspector, &sleep, &wake, &ambient, &active_app, &real, &fast, &day, &studio, &chat, &settings, &quit])?
            } else {
                Menu::with_items(app, &[&home, &chat, &sleep, &wake, &settings, &inspector, &quit])?
            };
            tauri::tray::TrayIconBuilder::new()
                .icon(tauri::image::Image::new_owned(include_bytes!("../icons/dormant.rgba").to_vec(), 32, 32))
                .tooltip("Replicants").menu(&menu).on_menu_event(|app, event| match event.id.as_ref() {
                    "studio" => panel(app, "mock"), "chat" => open_chat(app.clone()),
                    "inspector" => panel(app, "inspector"),
                    "home" | "settings" => panel(app, event.id.as_ref()),
                    "connect" | "birth" | "open" | "quit" => { let _ = app.emit_to("overlay", "lifecycle", json!({"kind":event.id.as_ref()})); },
                    "sleep" | "wake" | "ambient" | "active_app" => { let _ = app.emit_to("overlay", "brain-control", json!({"name": event.id.as_ref()})); },
                    "time_1" | "time_60" | "time_360" => { let scale = event.id.as_ref()[5..].parse::<u32>().unwrap_or(1); let _ = app.emit_to("overlay", "brain-control", json!({"name":"time_scale","scale":scale})); },
                    _ => {}
                }).build(app)?;
            let handle = app.handle().clone();
            thread::spawn(move || {
                let mut monitor = m.clone();
                let mut ignore = true;
                let mut poll_at = Instant::now() - Duration::from_secs(1);
                let mut diag_at = Instant::now();
                let mut mock_source = String::new();
                let mut verify_control = String::new();
                let diagnostics_ms = std::env::var("REPLICANTS_TELEMETRY_INTERVAL_MS").ok()
                    .and_then(|s| s.parse::<u64>().ok()).unwrap_or(1000).max(50);
                loop {
                    let Some(w) = handle.get_webview_window("overlay") else { break; };
                    let state = handle.state::<OverlayState>();
                    let (sx, sy) = native::cursor();
                    let (x, y) = (sx - monitor.x, sy - monitor.y);
                    let hit = state.regions.lock().unwrap().iter().any(|r| r.contains(x,y));
                    let next_ignore = verify_hidden || !(hit || state.capture.load(Ordering::Relaxed));
                    if next_ignore != ignore { let _ = w.set_ignore_cursor_events(next_ignore); ignore = next_ignore; }
                    let _ = w.emit("cursor", json!({"x":x,"y":y,"hit":hit}));
                    if poll_at.elapsed() >= Duration::from_millis(250) {
                        let (current, _) = native::primary();
                        if current != monitor {
                            let _ = w.set_position(PhysicalPosition::new(current.x as i32, current.y as i32));
                            let _ = w.set_size(PhysicalSize::new(current.width as u32, current.height as u32));
                            monitor = current;
                        }
                        let _ = w.emit("desktop", world_snapshot(&handle)); poll_at = Instant::now();
                    }
                    if diag_at.elapsed() >= Duration::from_millis(diagnostics_ms) {
                        // Explicit development fixture; never enabled in normal operation.
                        if let Ok(path) = std::env::var("REPLICANTS_MOCK_STATE_PATH") {
                            if let Ok(source) = std::fs::read_to_string(path) {
                                if source != mock_source {
                                    if let Ok(value) = serde_json::from_str::<Value>(&source) {
                                        *state.mock.lock().unwrap() = value.clone();
                                        let _ = w.emit("mock-state", value); mock_source = source;
                                    }
                                }
                            }
                        }
                        if let Ok(path) = std::env::var("REPLICANTS_TELEMETRY_PATH") {
                            let _ = std::fs::write(path, json!({"body":*state.view.lock().unwrap(),"click_through":ignore,"pid":std::process::id(),"inspector":*state.inspector.lock().unwrap(),"inspector_text":*state.inspector_text.lock().unwrap()}).to_string());
                        }
                        if verify_hidden {
                            if let Ok(path) = std::env::var("REPLICANTS_VERIFY_CONTROL_PATH") {
                                if let Ok(source) = std::fs::read_to_string(path) {
                                    if source != verify_control {
                                        if let Ok(value) = serde_json::from_str::<Value>(&source) {
                                            if ["inspector", "home", "settings", "conversation"].contains(&value["kind"].as_str().unwrap_or("")) { panel(&handle, value["kind"].as_str().unwrap()); }
                                            else { let _ = handle.emit_to("overlay", "lifecycle", value); }
                                            verify_control = source;
                                        }
                                    }
                                }
                            }
                        }
                        diag_at = Instant::now();
                    }
                    thread::sleep(Duration::from_millis(50));
                }
            });
            Ok(())
        }).run(context);
    if let Err(error) = result { eprintln!("Replicants: {error}"); std::process::exit(1); }
}
