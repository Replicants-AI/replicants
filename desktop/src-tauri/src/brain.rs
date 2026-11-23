//! Only the native overlay reads the private loopback descriptor.
use serde_json::Value;
use std::{path::PathBuf, process::{Command, Stdio}, sync::Mutex};
use std::os::windows::process::CommandExt;
use tauri::Manager;

static CHILD: Mutex<Option<std::process::Child>> = Mutex::new(None);

pub fn data_home() -> Result<PathBuf, String> {
    if let Some(path) = std::env::var_os("REPLICANTS_DATA_HOME") { return Ok(PathBuf::from(path)); }
    std::env::var_os("USERPROFILE").map(|p| PathBuf::from(p).join(".replicants"))
        .ok_or_else(|| "Windows user profile is unavailable".into())
}

fn descriptor_path() -> Option<PathBuf> {
    Some(std::env::var_os("REPLICANTS_SESSION_PATH").map(PathBuf::from)
        .unwrap_or(data_home().ok()?.join("desktop-session.json")))
}

#[tauri::command]
pub fn brain_running(app: tauri::AppHandle) -> bool {
    use windows_sys::Win32::{Foundation::CloseHandle, System::Threading::{OpenProcess, GetExitCodeProcess, QueryFullProcessImageNameW, PROCESS_QUERY_LIMITED_INFORMATION}};
    let Some(value) = descriptor_path().and_then(|p| std::fs::read(p).ok()).and_then(|b| serde_json::from_slice::<Value>(&b).ok()) else { return false; };
    let Some(pid) = value["pid"].as_u64().and_then(|pid| u32::try_from(pid).ok()).filter(|pid| *pid > 0) else { return false; };
    let image = unsafe {
        let handle = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, 0, pid);
        if handle.is_null() { return false; }
        let mut code = 0;
        let ok = GetExitCodeProcess(handle, &mut code);
        let mut buffer = [0u16; 32768];
        let mut length = buffer.len() as u32;
        let queried = QueryFullProcessImageNameW(handle, 0, buffer.as_mut_ptr(), &mut length);
        CloseHandle(handle);
        if ok == 0 || code != 259 || queried == 0 { return false; }
        PathBuf::from(String::from_utf16_lossy(&buffer[..length as usize]))
    };
    // A stale descriptor can outlive its process, and Windows reuses PIDs.
    // Never let a different executable block reopening the last checkpoint.
    let same_image = |expected: PathBuf| match (image.canonicalize(), expected.canonicalize()) {
        (Ok(actual), Ok(expected)) => actual.to_string_lossy().eq_ignore_ascii_case(&expected.to_string_lossy()),
        _ => false,
    };
    if let Ok(directory) = app.path().resource_dir() {
        if same_image(directory.join("backend/replicants-brain.exe")) { return true; }
    }
    cfg!(debug_assertions) && same_image(PathBuf::from(env!("CARGO_MANIFEST_DIR")).parent().unwrap().parent().unwrap().join(".venv/Scripts/python.exe"))
}

#[tauri::command]
pub fn desktop_connection(window: tauri::WebviewWindow) -> Option<Value> {
    if window.label() != "overlay" { return None; }
    let path = descriptor_path()?;
    let bytes = std::fs::read(path).ok()?;
    if bytes.len() > 4096 { return None; }
    let value: Value = serde_json::from_slice(&bytes).ok()?;
    if value["protocol"] != 1 || !(1..65536).contains(&value["port"].as_u64()?) || value["token"].as_str()?.len() < 32 { return None; }
    Some(value)
}

pub fn backend(app: &tauri::AppHandle) -> Result<Command, String> {
    let resource = app.path().resource_dir().map_err(|e| e.to_string())?.join("backend/replicants-brain.exe");
    let mut command;
    if resource.is_file() {
        command = Command::new(resource);
    } else if cfg!(debug_assertions) {
        let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).parent().unwrap().parent().unwrap().to_path_buf();
        let python = root.join(".venv/Scripts/python.exe");
        if !python.is_file() { return Err("Development Python environment is missing. Install the packaged beta to use Replicants.".into()); }
        command = Command::new(python);
        command.args(["-m", "replicants.desktop.bootstrap"]).current_dir(root);
    } else {
        return Err("The packaged brain is missing. Reinstall Replicants; your .replicant files are safe.".into());
    }
    command.creation_flags(0x08000000).env("REPLICANTS_BETA", "1");
    Ok(command)
}

pub fn start(app: &tauri::AppHandle, kind: &str, file: Option<String>) -> Result<(), String> {
    if brain_running(app.clone()) { return Err("A local brain is still awake. Wait for its checkpoint before opening another.".into()); }
    let mut current = CHILD.lock().map_err(|_| "brain launcher unavailable")?;
    if let Some(child) = current.as_mut() {
        if child.try_wait().map_err(|e| e.to_string())?.is_none() { return Err("The previous brain is still stopping.".into()); }
    }
    let mut command = backend(app)?;
    let home = data_home()?;
    std::fs::create_dir_all(&home).map_err(|e| e.to_string())?;
    let log = home.join("desktop-brain.log");
    if log.metadata().map(|m| m.len() > 2 * 1024 * 1024).unwrap_or(false) {
        let _ = std::fs::rename(&log, home.join("desktop-brain.previous.log"));
    }
    let output = std::fs::OpenOptions::new().create(true).append(true).open(log).map_err(|e| e.to_string())?;
    let errors = output.try_clone().map_err(|e| e.to_string())?;
    match kind {
        "birth" => { command.arg("birth"); },
        "open" => {
            let path = file.ok_or("Choose a .replicant file first")?;
            if !PathBuf::from(&path).is_file() { return Err("The selected .replicant file does not exist".into()); }
            command.args(["wake", "--file", &path]);
        },
        "connect" if cfg!(debug_assertions) => { command.arg("desktop"); },
        _ => return Err("Unknown lifecycle action".into()),
    }
    let child = command
        .stdin(Stdio::null()).stdout(output).stderr(errors).spawn().map_err(|e| e.to_string())?;
    *current = Some(child);
    Ok(())
}

#[tauri::command]
pub fn launch_brain(app: tauri::AppHandle) -> Result<(), String> { start(&app, "connect", None) }

#[tauri::command]
pub fn launch_status() -> Option<i32> {
    CHILD.lock().ok()?.as_mut()?.try_wait().ok()??.code()
}

#[tauri::command]
pub async fn finish_lifecycle(kind: String, file: Option<String>, app: tauri::AppHandle, window: tauri::WebviewWindow) -> Result<(), String> {
    if window.label() != "overlay" { return Err("Only the body may change its lifecycle".into()); }
    tauri::async_runtime::spawn_blocking(move || {
        for _ in 0..100 {
            if !brain_running(app.clone()) {
                let finished = CHILD.lock().map_err(|_| "brain launcher unavailable")?.as_mut()
                    .map(|c| c.try_wait().map(|s| s.is_some())).transpose().map_err(|e| e.to_string())?.unwrap_or(true);
                if finished {
                    return if kind == "quit" { crate::shell::stop_download(&app); app.exit(0); Ok(()) }
                        else if kind == "close" {
                            if let Some(window) = app.get_webview_window("birth") { let _ = window.close(); }
                            crate::panel(&app, "home"); Ok(())
                        }
                        else { start(&app, &kind, file) };
                }
            }
            std::thread::sleep(std::time::Duration::from_millis(50));
        }
        Err("The brain has not finished closing. Your body remains open; try again shortly.".into())
    }).await.map_err(|e| e.to_string())?
}

#[tauri::command]
pub async fn choose_replicant() -> Result<Option<String>, String> {
    tauri::async_runtime::spawn_blocking(|| {
        use windows_sys::Win32::UI::Controls::Dialogs::{GetOpenFileNameW, CommDlgExtendedError, OPENFILENAMEW, OFN_FILEMUSTEXIST, OFN_PATHMUSTEXIST, OFN_NOCHANGEDIR};
        let filter: Vec<u16> = "Replicant lives (*.replicant)\0*.replicant\0\0".encode_utf16().collect();
        let title: Vec<u16> = "Wake a Replicant\0".encode_utf16().collect();
        let directory = data_home()?.join("beings");
        let initial: Vec<u16> = directory.to_string_lossy().encode_utf16().chain(Some(0)).collect();
        let mut path = vec![0u16; 32768];
        let mut dialog = OPENFILENAMEW { lStructSize: std::mem::size_of::<OPENFILENAMEW>() as u32,
            lpstrFilter: filter.as_ptr(), lpstrTitle: title.as_ptr(), lpstrInitialDir: initial.as_ptr(), lpstrFile: path.as_mut_ptr(), nMaxFile: path.len() as u32,
            Flags: OFN_FILEMUSTEXIST | OFN_PATHMUSTEXIST | OFN_NOCHANGEDIR, ..Default::default() };
        unsafe {
            if GetOpenFileNameW(&mut dialog) != 0 {
                let length = path.iter().position(|c| *c == 0).unwrap_or(path.len());
                Ok(Some(String::from_utf16_lossy(&path[..length])))
            } else {
                let code = CommDlgExtendedError();
                if code == 0 { Ok(None) } else { Err(format!("File chooser failed ({code})")) }
            }
        }
    }).await.map_err(|e| e.to_string())?
}
