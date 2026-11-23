//! Geometry and ambient activity only. No title, text, clipboard, or capture APIs.
use serde::{Deserialize, Serialize};
use std::mem::size_of;
use windows_sys::core::BOOL;
use windows_sys::Win32::{
    Foundation::{CloseHandle, HWND, LPARAM, POINT, RECT},
    Graphics::{Dwm::{DwmGetWindowAttribute, DWMWA_CLOAKED, DWMWA_EXTENDED_FRAME_BOUNDS},
               Gdi::{GetMonitorInfoW, MonitorFromPoint, MONITORINFO, MONITOR_DEFAULTTOPRIMARY}},
    System::{SystemInformation::GetTickCount, Threading::{OpenProcess, QueryFullProcessImageNameW, PROCESS_QUERY_LIMITED_INFORMATION}},
    UI::{Input::KeyboardAndMouse::{GetLastInputInfo, LASTINPUTINFO},
         WindowsAndMessaging::{EnumWindows, GetCursorPos, GetForegroundWindow, GetWindowThreadProcessId, GetWindow, GetWindowLongW, GetClassNameW, IsIconic,
                               IsWindowVisible, GW_OWNER, GWL_EXSTYLE, WS_EX_TOOLWINDOW}},
};

/// Executable basename only; the caller must have an explicit active-app opt-in.
pub fn active_app() -> Option<String> {
    unsafe {
        let foreground = GetForegroundWindow();
        if foreground.is_null() { return None; }
        let mut pid = 0;
        GetWindowThreadProcessId(foreground, &mut pid);
        let process = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, 0, pid);
        if process.is_null() { return None; }
        let mut buffer = [0u16; 32768];
        let mut length = buffer.len() as u32;
        let ok = QueryFullProcessImageNameW(process, 0, buffer.as_mut_ptr(), &mut length);
        CloseHandle(process);
        if ok == 0 { return None; }
        let path = String::from_utf16_lossy(&buffer[..length as usize]);
        std::path::Path::new(&path).file_name().map(|n| n.to_string_lossy().into_owned())
    }
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct Rect { pub x: f64, pub y: f64, pub width: f64, pub height: f64 }
impl Rect {
    pub fn contains(&self, x: f64, y: f64) -> bool {
        x >= self.x && x <= self.x + self.width && y >= self.y && y <= self.y + self.height
    }
}
#[derive(Clone, Debug, Serialize, PartialEq)]
pub struct FloorWindow { pub id: String, #[serde(flatten)] pub rect: Rect }
#[derive(Clone, Debug, Serialize)]
pub struct Desktop { pub monitor: Rect, pub work: Rect, pub windows: Vec<FloorWindow>, pub idle_seconds: f64, pub fullscreen: bool }
struct Enumeration { excluded: Vec<isize>, windows: Vec<FloorWindow>, origin: POINT, monitor: Rect }

unsafe extern "system" fn enumerate(hwnd: HWND, param: LPARAM) -> BOOL {
    let data = &mut *(param as *mut Enumeration);
    if data.excluded.contains(&(hwnd as isize)) || IsWindowVisible(hwnd) == 0 || IsIconic(hwnd) != 0
        || !GetWindow(hwnd, GW_OWNER).is_null() || (GetWindowLongW(hwnd, GWL_EXSTYLE) as u32 & WS_EX_TOOLWINDOW) != 0 { return 1; }
    let mut cloaked: u32 = 0;
    if DwmGetWindowAttribute(hwnd, DWMWA_CLOAKED as u32, &mut cloaked as *mut _ as _, size_of::<u32>() as u32) != 0 || cloaked != 0 { return 1; }
    let mut frame = RECT::default();
    if DwmGetWindowAttribute(hwnd, DWMWA_EXTENDED_FRAME_BOUNDS as u32, &mut frame as *mut _ as _, size_of::<RECT>() as u32) != 0 { return 1; }
    let rect = Rect { x: (frame.left - data.origin.x) as f64, y: (frame.top - data.origin.y) as f64,
                      width: (frame.right - frame.left) as f64, height: (frame.bottom - frame.top) as f64 };
    if rect.width >= 80.0 && rect.height >= 40.0 && rect.x < data.monitor.width && rect.x + rect.width > 0.0
        && rect.y >= 0.0 && rect.y < data.monitor.height - 8.0 {
        data.windows.push(FloorWindow { id: format!("{:x}", hwnd as usize), rect });
    }
    1
}

pub fn primary() -> (Rect, Rect) {
    unsafe {
        let h = MonitorFromPoint(POINT { x: 0, y: 0 }, MONITOR_DEFAULTTOPRIMARY);
        let mut info = MONITORINFO { cbSize: size_of::<MONITORINFO>() as u32, ..Default::default() };
        if GetMonitorInfoW(h, &mut info) == 0 { return (Rect { x: 0.0, y: 0.0, width: 1920.0, height: 1080.0 }, Rect { x: 0.0, y: 0.0, width: 1920.0, height: 1040.0 }); }
        let m = info.rcMonitor;
        let w = info.rcWork;
        (Rect { x: m.left as f64, y: m.top as f64, width: (m.right-m.left) as f64, height: (m.bottom-m.top) as f64 },
         Rect { x: (w.left-m.left) as f64, y: (w.top-m.top) as f64, width: (w.right-w.left) as f64, height: (w.bottom-w.top) as f64 })
    }
}
pub fn cursor() -> (f64, f64) {
    unsafe { let mut p = POINT::default(); GetCursorPos(&mut p); (p.x as f64, p.y as f64) }
}
pub fn snapshot(excluded: Vec<isize>) -> Desktop {
    let (monitor, work) = primary();
    let fullscreen = unsafe {
        let foreground = GetForegroundWindow();
        let mut class = [0u16; 64];
        let length = GetClassNameW(foreground, class.as_mut_ptr(), class.len() as i32);
        let class = String::from_utf16_lossy(&class[..length.max(0) as usize]);
        let mut frame = RECT::default();
        !foreground.is_null() && !excluded.contains(&(foreground as isize)) && class != "Progman" && class != "WorkerW"
            && DwmGetWindowAttribute(foreground, DWMWA_EXTENDED_FRAME_BOUNDS as u32, &mut frame as *mut _ as _, size_of::<RECT>() as u32) == 0
            && frame.left as f64 <= monitor.x && frame.top as f64 <= monitor.y
            && frame.right as f64 >= monitor.x + monitor.width && frame.bottom as f64 >= monitor.y + monitor.height
    };
    let mut enumeration = Enumeration { excluded, windows: vec![], origin: POINT { x: monitor.x as i32, y: monitor.y as i32 }, monitor: monitor.clone() };
    let mut input = LASTINPUTINFO { cbSize: size_of::<LASTINPUTINFO>() as u32, dwTime: 0 };
    unsafe {
        EnumWindows(Some(enumerate), &mut enumeration as *mut _ as LPARAM);
        GetLastInputInfo(&mut input);
        Desktop { monitor, work, windows: enumeration.windows, idle_seconds: GetTickCount().wrapping_sub(input.dwTime) as f64 / 1000.0, fullscreen }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test] fn native_geometry_is_title_free_and_primary_monitor_is_real() {
        let data = snapshot(vec![]);
        assert!(data.monitor.width > 100.0 && data.work.height <= data.monitor.height);
        let json = serde_json::to_string(&data).unwrap();
        assert!(!json.contains("title") && !json.contains("content"));
        assert!(data.windows.iter().all(|w| w.rect.width >= 80.0));
    }
    #[test] fn hit_regions_have_precise_edges() {
        let rect = Rect { x: 10.0, y: 10.0, width: 48.0, height: 42.0 };
        assert!(rect.contains(20.0, 20.0)); assert!(!rect.contains(9.0, 20.0));
    }
}
