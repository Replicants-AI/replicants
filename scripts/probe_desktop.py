"""Windows acceptance probe using an owned test window and body telemetry.

No screenshots, window titles, or user content are read. This moves the cursor
and the test window, interacts with the creature, then restores the cursor.
Run with the overlay closed: .venv/Scripts/python.exe scripts/probe_desktop.py
"""
import ctypes as c
from ctypes import wintypes as w
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import psutil

ROOT = Path(__file__).resolve().parents[1]
u = c.windll.user32
u.SetProcessDPIAware()
u.CreateWindowExW.restype = w.HWND
u.CreateWindowExW.argtypes = [w.DWORD,w.LPCWSTR,w.LPCWSTR,w.DWORD,c.c_int,c.c_int,c.c_int,c.c_int,w.HWND,w.HMENU,w.HINSTANCE,c.c_void_p]
u.SetWindowPos.argtypes = [w.HWND,w.HWND,c.c_int,c.c_int,c.c_int,c.c_int,w.UINT]
u.DestroyWindow.argtypes = [w.HWND]
u.ShowWindow.argtypes = [w.HWND,c.c_int]
u.GetWindowLongW.argtypes = [w.HWND,c.c_int]
telemetry = ROOT / '.git/desktop-telemetry.json'
fixture = ROOT / '.git/desktop-mock.json'
report = {'checks': {}}
throw_only = '--throw-only' in sys.argv
original_cursor = w.POINT(); u.GetCursorPos(c.byref(original_cursor))


def pump(seconds=.1):
    until = time.monotonic() + seconds
    msg = w.MSG()
    while time.monotonic() < until:
        while u.PeekMessageW(c.byref(msg), None, 0, 0, 1):
            u.TranslateMessage(c.byref(msg)); u.DispatchMessageW(c.byref(msg))
        time.sleep(.01)


def data():
    try:
        return json.loads(telemetry.read_text())
    except (OSError, ValueError):
        return {}


def wait(predicate, timeout=10):
    start=time.monotonic()
    while time.monotonic()-start<timeout:
        value=data()
        if predicate(value): return value
        pump(.1)
    raise AssertionError(f'Native body condition timed out: {data()}')


def set_state(asleep=False):
    fixture.write_text(json.dumps({'state': {'bars': {'social':0,'curiosity':0,'creative':0,'tension':0,'comfort':1},'asleep':asleep,'salience':0,'affects':[],'mood_tags':[],'sim_hour':1 if asleep else 15,'temperament':'calm'}}))


def mouse(x,y,flag=0):
    u.SetCursorPos(int(x),int(y)); pump(.15)
    if flag: u.mouse_event(flag,0,0,0,0); pump(.15)


def drag_to(x,y):
    b=wait(lambda d:bool(d.get('body',{}).get('floor')))['body']
    mouse(b['x']+24,b['y']+21); wait(lambda d:d.get('click_through') is False)
    u.mouse_event(2,0,0,0,0); pump(.2)
    mouse(b['x']+36,b['y']+12); mouse(x,y); pump(.4)
    u.mouse_event(4,0,0,0,0); pump(1.2)


def throw_creature():
    b=wait(lambda d:bool(d.get('body',{}).get('floor')))['body']
    mouse(b['x']+24,b['y']+21);wait(lambda d:d.get('click_through') is False)
    u.mouse_event(2,0,0,0,0);pump(.12)
    mouse(450,480);pump(.2)
    for i in range(1,9):
        u.SetCursorPos(450+i*35,480-i*20);pump(.015)
    u.mouse_event(4,0,0,0,0)
    samples=[]
    for _ in range(24):
        pump(.05);samples.append(data().get('body',{}))
    assert any(p.get('last_throw',{}).get('vx',0)>1000 and p.get('last_throw',{}).get('vy',0)<-200 for p in samples),samples
    airborne=[p for p in samples if p.get('floor') is None and abs(p.get('vx',0))>100]
    assert len(airborne)>=2,samples
    assert min(p['y'] for p in airborne)<480-8*20-21,airborne
    assert max(p['x'] for p in airborne)>450+8*35,airborne
    report['checks']['native_mouse_throw_retains_momentum']=True
    report['checks']['native_mouse_throw_arcs_upward']=True
    report['throw_sample']={k:airborne[0][k] for k in ('x','y','vx','vy','animation','last_throw','appearance')}


handle = u.CreateWindowExW(8, 'STATIC', 'Replicants geometry probe', 0x10CF0000, 250, 360, 720, 260, None, None, None, None)
assert handle
test_id = format(handle,'x')
set_state()
env=dict(os.environ, REPLICANTS_TELEMETRY_PATH=str(telemetry), REPLICANTS_MOCK_STATE_PATH=str(fixture))
env['REPLICANTS_TELEMETRY_INTERVAL_MS']='100'
process=subprocess.Popen([str(ROOT/'desktop/src-tauri/target/debug/replicants-desktop.exe')],env=env,creationflags=subprocess.CREATE_NO_WINDOW)
try:
    live=wait(lambda d: d.get('pid')==process.pid and 'floor' in d.get('body',{}),30)
    assert live['body']['floor']==test_id, live
    report['checks']['lands_on_native_dwm_edge']=True
    if throw_only:
        throw_creature()
        assert data()['body']['appearance']['preset']=='01-classic'
        report['checks']['classic_skin_active']=True
        sys.exit(0)
    # Owned test window is the only window moved by this probe.
    before=live['body']['x']
    for i in range(1,7):
        u.SetWindowPos(handle,None,250+i*8,360,720,260,0x0004|0x0010); pump(.3)
    live=wait(lambda d:d.get('body',{}).get('x',0)>before+30)
    assert live['body']['floor']==test_id
    report['checks']['rides_slow_window']=True
    u.SetWindowPos(handle,None,800,480,720,260,0x0004|0x0010)
    wait(lambda d:d.get('body',{}).get('floor')!=test_id)
    report['checks']['fast_window_causes_fall']=True
    u.SetWindowPos(handle,None,250,360,720,260,0x0004|0x0010); pump(.5)
    drag_to(480,180)
    live=wait(lambda d:d.get('body',{}).get('floor')==test_id)
    assert live['body']['drags']>=1
    report['checks']['native_drag_and_drop_lands']=True
    b=live['body']; mouse(b['x']+24,b['y']+21); wait(lambda d:d.get('click_through') is False)
    before=b['pokes']; u.mouse_event(2,0,0,0,0); pump(.1); u.mouse_event(4,0,0,0,0)
    wait(lambda d:d.get('body',{}).get('pokes',0)>before)
    report['checks']['native_poke']=True
    mouse(50,50); wait(lambda d:d.get('click_through') is True)
    report['checks']['outside_click_through']=True
    u.ShowWindow(handle,6)
    wait(lambda d:d.get('body',{}).get('floor')!=test_id)
    report['checks']['minimize_removes_floor']=True
    # Poke's real-time wake guard expires after 45s. Place at a sleep corner.
    set_state(True); drag_to(45,u.GetSystemMetrics(1)-90); mouse(100,100)
    wait(lambda d:d.get('body',{}).get('behavior')=='sleep',60)
    report['checks']['night_sleeps_at_corner']=True
    root=psutil.Process(process.pid); procs=[root]+root.children(recursive=True)
    totals={p.pid:sum(p.cpu_times()[:2]) for p in procs}; started=time.monotonic(); pump(20)
    elapsed=time.monotonic()-started
    cpu=sum(max(0,sum(p.cpu_times()[:2])-totals.get(p.pid,0)) for p in procs if p.is_running())
    report['idle']={'seconds':round(elapsed,2),'cpu_one_core_percent':round(cpu/elapsed*100,2),'cpu_machine_percent':round(cpu/elapsed*100/psutil.cpu_count(),3),'processes':len(procs),'working_set_mib':round(sum(p.memory_info().rss for p in procs if p.is_running())/2**20,1),'includes_webview_children':True,'build':'debug'}
    report['final_body']=data()['body']
finally:
    process.terminate()
    try: process.wait(5)
    except subprocess.TimeoutExpired: process.kill()
    u.DestroyWindow(handle); u.SetCursorPos(original_cursor.x,original_cursor.y)
    (ROOT/('.git/desktop-native-throw.json' if throw_only else '.git/desktop-native-probe.json')).write_text(json.dumps(report,indent=2))
    print(json.dumps(report,indent=2))
