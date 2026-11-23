"""Fresh real-Gemma birth, measured compute/hardware, and checkpointed accounting."""
import asyncio
import json
import os
from pathlib import Path
import subprocess
import time
import uuid
import argparse
import shutil

from replicants.desktop.archive import ReplicantArchive, verify
from replicants.desktop.genome import conceive
from replicants.desktop.life import LivingReplicant
from replicants.desktop.runtime import PERSON
from replicants.presence.platforms.desktop import DesktopPlatform
from probe_desktop_brain import until
from probe_desktop_life import usage
import psutil


async def main(resume=None):
    area = Path.home() / '.replicants/verification' / uuid.uuid4().hex
    area.mkdir(parents=True)
    os.environ['REPLICANTS_TIME_SCALE'] = '1'
    os.environ['REPLICANTS_START_HOUR'] = '12'
    if resume:
        assert resume.resolve().is_relative_to(Path.home() / '.replicants/verification')
        shutil.copyfile(resume, area / 'Mica.replicant')
        being = ReplicantArchive.open(area / 'Mica.replicant', area)
    else:
        being = ReplicantArchive.create(conceive('curious', 'mint', 6), area / 'Mica.replicant', area)
    platform = DesktopPlatform(area / 'desktop-session.json')
    runtime = LivingReplicant(being, platform)
    runner = asyncio.create_task(runtime.run(launch=False))
    child = None
    report = {'area': str(area), 'id': being.id, 'model': runtime.entity.config.cognition.deliberate_model,
        'fixture': 'Six-second birth and scripted naming; subsequent behavior is unforced. Shared GPU load is not attributed to this being.'}
    control = area / 'control.json'
    try:
        await until(lambda: platform.port != 0)
        env = dict(os.environ, REPLICANTS_VERIFY_HIDDEN='1', REPLICANTS_SESSION_PATH=str(platform.session_path),
            REPLICANTS_TELEMETRY_PATH=str(area / 'view.json'), REPLICANTS_VERIFY_CONTROL_PATH=str(control))
        child = subprocess.Popen([str(Path('.git/desktop-bridge-build/debug/replicants-desktop.exe').resolve())],
            env=env, creationflags=subprocess.CREATE_NO_WINDOW)
        if not runtime.life_state['sealed']:
            await until(lambda: runtime.life_state['phase'] == 'awaiting_name', 180)
            await runtime.receive({'type': 'event', 'payload': {'kind': 'chat', 'text': 'Mica'}})
        await until(lambda: runtime.life_state['sealed'] and not runtime._cognition.locked(), 240)
        await until(lambda: platform.connected, 30)
        print('Fresh birth sealed:', being.id, runtime.entity.tonic.noise.current_fragments(), flush=True)
        await asyncio.sleep(10)
        first = {'overlay': usage(child.pid, True), 'brain': usage(os.getpid())}
        assert first['overlay']['processes'] >= 5, 'WebView renderer tree must be measured, not shared with the user body'
        call_count, idle_start = len(runtime.entity.client.calls), time.monotonic()
        await asyncio.sleep(120)
        duration = time.monotonic() - idle_start
        report['idle_seconds'] = duration
        report['idle_model_calls'] = len(runtime.entity.client.calls) - call_count
        report['idle'] = {}
        for label, after in [('overlay', usage(child.pid, True)), ('brain', usage(os.getpid()))]:
            one_core = (after['cpu_seconds'] - first[label]['cpu_seconds']) / duration * 100
            report['idle'][label] = {'one_core_cpu_percent': one_core, 'machine_cpu_percent': one_core / psutil.cpu_count(),
                'working_set_mib': after['working_set_bytes'] / 1024**2, 'processes': after['processes']}
        print('Complete process-tree idle measurement:', report['idle'], report['idle_model_calls'], 'model calls', flush=True)
        await until(lambda: not runtime._cognition.locked(), 240)
        report['substrate'] = runtime.substrate.snapshot()
        assert report['substrate']['inference']['totals']['chat']['completed'] > 0
        assert 'energy' not in runtime.state()
        print('Measured substrate:', report['substrate'], flush=True)
        control.write_text(json.dumps({'kind': 'quit'}))
        await asyncio.wait_for(runner, 40)
        await until(lambda: child.poll() is not None, 10)
        report['graceful_quit'] = verify(being.path)[0]['name'] == 'Mica'
        resumed = ReplicantArchive.open(being.path, area)
        awake = LivingReplicant(resumed, DesktopPlatform(area / 'desktop-session.json'))
        try:
            report['appearance_after_restart'] = awake.appearance
            report['marker_after_restart'] = awake.entity.tonic.bars._somatic_markers.get(PERSON)
            assert report['marker_after_restart']
            assert awake.appearance == runtime.appearance
            assert awake.life_state['sealed']
            assert awake.compute.totals == runtime.compute.totals
            assert awake.substrate.snapshot()['gpu']['status'] == 'not_sampled'
        finally: await awake.entity.shutdown(); resumed.close()
    finally:
        runtime._stop.set(); await runner
        if child is not None and child.poll() is None:
            child.terminate(); await asyncio.to_thread(child.wait, 10)
        Path('.git/desktop-substrate-probe.json').write_text(json.dumps(report, indent=2), encoding='utf-8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--resume', type=Path, help='Continue a previously born verification life only.')
    asyncio.run(main(parser.parse_args().resume))
