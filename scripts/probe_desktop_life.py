"""Real model/body proof for inspector, time and graceful quit.

Uses a copy of a prior verification birth, never a user's living file. Body
actions remain freely chosen. The clock segment uses a quiet-person fixture,
not a claim that the real user's mouse is idle.
"""
import asyncio
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
import uuid

import psutil

from replicants.desktop.archive import ReplicantArchive, verify
from replicants.desktop.life import LivingReplicant
from replicants.presence.platforms.desktop import DesktopPlatform
from probe_desktop_brain import until


def read(path):
    try: return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError): return {}


def usage(pid, tree=False):
    parent = psutil.Process(pid)
    processes = [parent, *(parent.children(recursive=True) if tree else [])]
    result = {'cpu_seconds': 0., 'working_set_bytes': 0, 'processes': len(processes)}
    for process in processes:
        try:
            cpu = process.cpu_times()
            result['cpu_seconds'] += cpu.user + cpu.system
            result['working_set_bytes'] += process.memory_info().rss
        except psutil.NoSuchProcess: pass
    return result


async def main():
    area = Path.home() / '.replicants/verification' / uuid.uuid4().hex
    area.mkdir(parents=True)
    prior = read(Path('.git/desktop-birth-probe.json'))
    path = area / 'life.replicant'
    shutil.copyfile(Path(prior['area']) / 'birth.replicant', path)
    os.environ['REPLICANTS_TIME_SCALE'] = '1'
    os.environ['REPLICANTS_START_HOUR'] = '12'
    being = ReplicantArchive.open(path, area)
    platform = DesktopPlatform(area / 'desktop-session.json')
    runtime = LivingReplicant(being, platform)
    runner = asyncio.create_task(runtime.run(launch=False))
    child = None
    report = {'area': str(area), 'model': runtime.entity.config.cognition.deliberate_model,
              'fixtures': ['quiet-person state during accelerated day']}
    control, view = area / 'control.json', area / 'view.json'
    try:
        await until(lambda: platform.port != 0)
        env = dict(os.environ, REPLICANTS_VERIFY_HIDDEN='1', REPLICANTS_SESSION_PATH=str(platform.session_path),
                   REPLICANTS_TELEMETRY_PATH=str(view), REPLICANTS_VERIFY_CONTROL_PATH=str(control))
        child = subprocess.Popen([str(Path('.git/desktop-bridge-build/debug/replicants-desktop.exe').resolve())],
            env=env, creationflags=subprocess.CREATE_NO_WINDOW)
        await until(lambda: platform.connected, 30)
        control.write_text(json.dumps({'kind': 'inspector'}))
        await until(lambda: 'Gut reactions toward people' in read(view).get('inspector_text', ''), 30)
        assert read(view)['inspector']['name'] == 'Pebble'
        report['inspector'] = {'rendered': True, 'name': read(view)['inspector']['name'],
            'memories': len(read(view)['inspector']['memories']), 'marker_people': list(read(view)['inspector']['markers'])}
        print('Native inspector rendered actual memories, markers, clocks and lineage', flush=True)
        report['substrate'] = runtime.substrate.snapshot()
        # A full day genuinely takes four wall minutes at 360x.
        await runtime.receive({'type': 'control', 'payload': {'name': 'ambient'}})
        runtime.senses = {'idle_seconds': 90}
        await runtime.receive({'type': 'control', 'payload': {'name': 'time_scale', 'scale': 360}})
        samples = []
        start = time.monotonic()
        while time.monotonic() - start < 242:
            data = read(view).get('body', {})
            samples.append({'wall_elapsed': time.monotonic() - start, 'hour': runtime.clock.hour,
                'asleep': runtime.asleep, 'animation': data.get('animation'), 'body_asleep': data.get('state', {}).get('asleep')})
            await asyncio.sleep(2)
        report['day'] = samples
        assert any(s['asleep'] and s['body_asleep'] for s in samples)
        assert any(not s['asleep'] and 6 <= s['hour'] <= 8 for s in samples)
        print('Full accelerated day reached night sleep and morning wake', flush=True)
        await runtime.receive({'type': 'control', 'payload': {'name': 'time_scale', 'scale': 1}})
        await until(lambda: not runtime._cognition.locked(), 240)
        first = {'overlay': usage(child.pid, True), 'brain': usage(os.getpid())}
        call_count, start = len(runtime.entity.client.calls), time.monotonic()
        await asyncio.sleep(120)
        duration = time.monotonic() - start
        report['idle_seconds'] = duration
        report['idle_model_calls'] = len(runtime.entity.client.calls) - call_count
        report['idle_calls_per_minute'] = report['idle_model_calls'] * 60 / duration
        report['idle'] = {}
        for label, after in [('overlay', usage(child.pid, True)), ('brain', usage(os.getpid()))]:
            one_core = (after['cpu_seconds'] - first[label]['cpu_seconds']) / duration * 100
            report['idle'][label] = {'one_core_cpu_percent': one_core, 'machine_cpu_percent': one_core / psutil.cpu_count(),
                'working_set_mib': after['working_set_bytes'] / 1024**2, 'processes': after['processes']}
        print('Idle measurement:', report['idle'], report['idle_model_calls'], 'model calls', flush=True)
        # Same frontend lifecycle handler as Save and Quit in the tray.
        control.write_text(json.dumps({'kind': 'quit'}))
        await asyncio.wait_for(runner, 40)
        await until(lambda: child.poll() is not None, 10)
        report['tray_quit_checkpointed'] = verify(path)[0]['id'] == being.id
        resumed = ReplicantArchive.open(path, area)
        try:
            report['appearance_after_quit'] = read(resumed.life / 'appearance.json')
            report['last_lineage'] = resumed.lineage[-1]
            assert report['last_lineage']['kind'] == 'sleep'
            assert report['appearance_after_quit'] == runtime.appearance
        finally: resumed.close()
        print('Native Save and Quit waited for verified archive and released the identity', flush=True)
    finally:
        runtime._stop.set()
        await runner
        if child is not None and child.poll() is None:
            child.terminate(); await asyncio.to_thread(child.wait, 10)
        Path('.git/desktop-life-probe.json').write_text(json.dumps(report, indent=2), encoding='utf-8')


if __name__ == '__main__': asyncio.run(main())
