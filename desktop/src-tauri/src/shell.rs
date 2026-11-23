//! Product windows receive a curated state cache, never the private websocket token.
use serde_json::{json, Value};
use std::{io::{BufRead, BufReader, Write}, process::{Child, Stdio}, sync::Mutex};
use tauri::{Emitter, Manager, State};

#[derive(Default)]
pub struct ProductState {
    snapshot: Mutex<Value>,
    download: Mutex<Option<Child>>,
}

pub fn room_is_open(app: &tauri::AppHandle) -> bool {
    app.state::<ProductState>().snapshot.lock().unwrap()["room_window_open"].as_bool().unwrap_or(false)
}

fn call(app: &tauri::AppHandle, action: &str, input: Option<Value>) -> Result<Value, String> {
    let mut command = crate::brain::backend(app)?;
    command.arg(action).stdin(if input.is_some() { Stdio::piped() } else { Stdio::null() })
        .stdout(Stdio::piped()).stderr(Stdio::null());
    let mut child = command.spawn().map_err(|e| e.to_string())?;
    if let Some(value) = input {
        child.stdin.take().ok_or("Settings input unavailable")?.write_all(value.to_string().as_bytes()).map_err(|e| e.to_string())?;
    }
    let output = child.wait_with_output().map_err(|e| e.to_string())?;
    let source = String::from_utf8_lossy(&output.stdout);
    let value: Value = source.lines().rev().find_map(|line| serde_json::from_str(line).ok())
        .ok_or("The local backend did not return a result. Reinstall the beta if this persists.")?;
    if !output.status.success() { return Err(value["error"].as_str().unwrap_or("The local backend could not finish").into()); }
    Ok(value)
}

#[tauri::command]
pub async fn setup_check(app: tauri::AppHandle) -> Result<Value, String> {
    tauri::async_runtime::spawn_blocking(move || call(&app, "check", None)).await.map_err(|e| e.to_string())?
}

#[tauri::command]
pub async fn preferences(app: tauri::AppHandle) -> Result<Value, String> {
    tauri::async_runtime::spawn_blocking(move || call(&app, "preferences", None)).await.map_err(|e| e.to_string())?
}

#[tauri::command]
pub async fn life_library(app: tauri::AppHandle) -> Result<Value, String> {
    tauri::async_runtime::spawn_blocking(move || call(&app, "library", None)).await.map_err(|e| e.to_string())?
}

#[tauri::command]
pub fn open_life(file: String, app: tauri::AppHandle) -> Result<(), String> {
    let path = std::path::Path::new(&file);
    if !path.is_file() || path.extension().and_then(|v| v.to_str()).map(|s| s.to_lowercase()).as_deref() != Some("replicant") {
        return Err("Choose an existing .replicant life file".into());
    }
    app.emit_to("overlay", "lifecycle", json!({"kind":"open", "file":file})).map_err(|e| e.to_string())
}

#[tauri::command]
pub fn show_life_folder() -> Result<(), String> {
    let directory = crate::brain::data_home()?.join("beings");
    std::fs::create_dir_all(&directory).map_err(|e| e.to_string())?;
    std::process::Command::new("explorer.exe").arg(directory).spawn().map_err(|e| e.to_string())?;
    Ok(())
}

#[tauri::command]
pub async fn save_preferences(value: Value, app: tauri::AppHandle) -> Result<Value, String> {
    tauri::async_runtime::spawn_blocking(move || {
        let saved = call(&app, "settings", Some(value))?;
        let _ = app.emit("preferences-changed", &saved["settings"]);
        Ok(saved)
    }).await.map_err(|e| e.to_string())?
}

#[tauri::command]
pub async fn download_model(model: String, app: tauri::AppHandle) -> Result<(), String> {
    tauri::async_runtime::spawn_blocking(move || stream(&app, &["pull", "--model", &model], "model-download")).await.map_err(|e| e.to_string())?
}

/// One-button setup: check the computer, get thought running, download a fitting mind.
#[tauri::command]
pub async fn prepare_local(app: tauri::AppHandle) -> Result<(), String> {
    tauri::async_runtime::spawn_blocking(move || stream(&app, &["prepare"], "setup-progress")).await.map_err(|e| e.to_string())?
}

/// Runs one long backend task, forwarding each JSON line as an event. Shares the
/// download slot, so Cancel and Quit stop either kind of task.
fn stream(app: &tauri::AppHandle, args: &[&str], event: &str) -> Result<(), String> {
        let state = app.state::<ProductState>();
        {
            let mut current = state.download.lock().map_err(|_| "Download state unavailable")?;
            if current.is_some() { return Err("Setup or a model download is already running".into()); }
            let mut command = crate::brain::backend(app)?;
            let mut child = command.args(args).stdin(Stdio::null()).stdout(Stdio::piped()).stderr(Stdio::null())
                .spawn().map_err(|e| e.to_string())?;
            let stdout = child.stdout.take().ok_or("Download output unavailable")?;
            *current = Some(child);
            drop(current);
            let mut failure = None;
            for line in BufReader::new(stdout).lines() {
                match line {
                    Ok(line) => if let Ok(value) = serde_json::from_str::<Value>(&line) {
                        if let Some(error) = value["error"].as_str() { failure = Some(error.to_string()); }
                        let _ = app.emit(event, value);
                    },
                    Err(error) => { failure = Some(error.to_string()); break; }
                }
            }
            let mut current = state.download.lock().map_err(|_| "Download state unavailable")?;
            let success = current.as_mut().map(|child| child.wait().map(|s| s.success())).transpose()
                .map_err(|e| e.to_string())?.unwrap_or(false);
            *current = None;
            if let Some(error) = failure { return Err(error); }
            if !success { return Err("Download stopped. You can resume it later.".into()); }
        }
        Ok(())
}

#[tauri::command]
pub fn cancel_download(state: State<'_, ProductState>) -> Result<(), String> {
    if let Some(child) = state.download.lock().map_err(|_| "Download state unavailable")?.as_mut() {
        child.kill().map_err(|e| e.to_string())?;
    }
    Ok(())
}

pub fn stop_download(app: &tauri::AppHandle) {
    let state = app.state::<ProductState>();
    if let Ok(mut download) = state.download.lock() {
        if let Some(child) = download.as_mut() { let _ = child.kill(); let _ = child.wait(); }
    };
    // The private local runtime belongs to the app; it never outlives it.
    // The backend stops only a process it started from its own runtime folder.
    let _ = call(app, "runtime-stop", None);
}

#[tauri::command]
pub fn cache_product(kind: String, value: Value, window: tauri::WebviewWindow, app: tauri::AppHandle, state: State<'_, ProductState>) {
    if window.label() != "overlay" || !["state", "health", "conversation", "connected", "error", "appearance", "lifecycle", "room"].contains(&kind.as_str()) { return; }
    let mut snapshot = state.snapshot.lock().unwrap();
    if !snapshot.is_object() { *snapshot = json!({}); }
    snapshot[&kind] = value.clone();
    if kind == "room" {
        let was_open = snapshot["room_window_open"].as_bool().unwrap_or(false);
        let open = value["open"].as_bool().unwrap_or(false);
        snapshot["room_window_open"] = json!(open);
        if open && !was_open { crate::panel(&app, "room"); }
        if was_open && !open { if let Some(room) = app.get_webview_window("room") { let _ = room.hide(); } }
    }
    if kind == "connected" && value["value"] == false {
        snapshot["room"] = json!({"open":false,"available":false,"status":"closed"});
        snapshot["room_window_open"] = json!(false);
        if let Some(room) = app.get_webview_window("room") { let _ = room.hide(); }
    }
    let _ = app.emit("product-update", json!({"kind": kind, "value": value}));
}

#[tauri::command]
pub fn product_snapshot(state: State<'_, ProductState>) -> Value { state.snapshot.lock().unwrap().clone() }

#[tauri::command]
pub fn show_panel(label: String, app: tauri::AppHandle) -> Result<(), String> {
    if !["home", "conversation", "settings", "inspector", "room"].contains(&label.as_str()) { return Err("Unknown window".into()); }
    crate::panel(&app, &label);
    Ok(())
}

#[tauri::command]
pub fn request_lifecycle(kind: String, app: tauri::AppHandle) -> Result<(), String> {
    if !["birth", "open", "quit", "close"].contains(&kind.as_str()) { return Err("Unknown lifecycle action".into()); }
    app.emit_to("overlay", "lifecycle", json!({"kind":kind})).map_err(|e| e.to_string())
}

#[tauri::command]
pub fn send_message(id: String, text: String, app: tauri::AppHandle) -> Result<(), String> {
    if id.len() > 128 || text.trim().is_empty() || text.chars().count() > 4000 { return Err("Messages must contain 1 to 4,000 characters".into()); }
    app.emit_to("overlay", "send-message", json!({"id":id,"text":text})).map_err(|e| e.to_string())
}

#[tauri::command]
pub fn open_help(target: String) -> Result<(), String> {
    let url = match target.as_str() { "ollama" => "https://ollama.com/download/windows", "releases" => "https://github.com/Replicants-AI/replicants/releases", _ => return Err("Unknown help link".into()) };
    std::process::Command::new("rundll32.exe").args(["url.dll,FileProtocolHandler", url]).spawn().map_err(|e| e.to_string())?;
    Ok(())
}

#[tauri::command]
pub fn export_diagnostics(app: tauri::AppHandle, state: State<'_, ProductState>) -> Result<String, String> {
    let snapshot = state.snapshot.lock().map_err(|_| "Product state unavailable")?;
    let home = crate::brain::data_home()?;
    std::fs::create_dir_all(&home).map_err(|e| e.to_string())?;
    let path = home.join("replicants-support.json");
    // No prompts, transcript, inner thoughts, descriptor, logs, paths, or authentication.
    let report = json!({"version":app.package_info().version.to_string(), "platform":"windows",
        "connected":snapshot["connected"], "health": {"status":snapshot["health"]["status"],
        "last_checkpoint_at":snapshot["health"]["last_checkpoint_at"], "paused":snapshot["health"]["paused"]},
        "vigilance":snapshot["state"]["vigilance"], "gestating":snapshot["state"]["gestating"]});
    std::fs::write(&path, serde_json::to_vec_pretty(&report).map_err(|e| e.to_string())?).map_err(|e| e.to_string())?;
    Ok(path.to_string_lossy().into_owned())
}
