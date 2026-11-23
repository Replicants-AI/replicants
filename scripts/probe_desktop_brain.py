"""Real local Gemma + native WebView bridge probe, isolated from the user's body.

Runs a hidden overlay with no global shortcut or cursor interception. Stimuli
are scripted adapter inputs; actions finish in the actual TypeScript renderer.
No screen capture, window titles, external network, or user identity files.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import subprocess
import time
import uuid

from replicants.desktop.entity import DesktopEntity
from replicants.desktop.runtime import DesktopRuntime, PERSON, desktop_config
from replicants.presence.platforms.desktop import DesktopPlatform


async def until(predicate, timeout=120):
    end = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() >= end: raise TimeoutError('probe condition not reached')
        await asyncio.sleep(.25)


async def probe(binary: Path, report: Path):
    area = Path.home() / '.replicants' / 'verification' / uuid.uuid4().hex
    area.mkdir(parents=True)
    os.environ['REPLICANTS_EXECUTION_WORKSPACE_DIR'] = str(area)
    cfg = desktop_config()
    cfg.harness.memory.database_path = str(area / 'memory.db')
    cfg.projects_path = lambda: str(area / 'projects.json')
    cfg.self_model_path = lambda: str(area / 'self_model.json')
    # Keep ordinary models and cognition settings. Delay unrelated portrait /
    # distillation calls in this narrow bridge experiment.
    cfg.harness.memory.relational.enabled = False
    cfg.harness.memory.distillation.enabled = False
    cfg.drives.initiative_cooldown = 60
    platform = DesktopPlatform(area / 'desktop-session.json')
    entity = DesktopEntity(cfg)
    runtime = DesktopRuntime(entity, platform)
    child = None
    runner = asyncio.create_task(runtime.run(launch=False))
    evidence = {'model': cfg.cognition.deliberate_model, 'area': str(area), 'checks': []}
    try:
        await until(lambda: platform.port != 0)
        env = dict(os.environ, REPLICANTS_SESSION_PATH=str(platform.session_path),
                   REPLICANTS_VERIFY_HIDDEN='1', REPLICANTS_TELEMETRY_PATH=str(area / 'view.json'))
        child = subprocess.Popen([str(binary.resolve())], env=env, creationflags=subprocess.CREATE_NO_WINDOW)
        await until(lambda: platform.connected, 30)
        print('Native overlay authenticated', flush=True)
        await asyncio.sleep(3)
        result = await platform.action('wave')
        evidence['checks'].append({'native_wave': result})
        print('Native wave result:', result, flush=True)
        assert result['status'] == 'completed', result
        for name in ['look_at', 'sit', 'inspect_window']:
            result = await platform.action(name)
            evidence['checks'].append({name: result})
            assert result['status'] == 'completed', result
        await runtime.receive({'type': 'event', 'payload': {'kind': 'poke'}})
        await runtime.receive({'type': 'event', 'payload': {'kind': 'drag_start'}})
        await runtime.receive({'type': 'event', 'payload': {'kind': 'drag_end'}})
        await until(lambda: PERSON in entity.tonic.bars._somatic_markers, 180)
        print('Touch marker formed:', entity.tonic.bars._somatic_markers[PERSON], flush=True)
        await runtime.receive({'type': 'event', 'payload': {'kind': 'chat', 'text': 'Hello little one. It is nice having you here. You can just be yourself.'}})
        await until(lambda: runtime._jobs.empty() and not runtime._cognition.locked(), 240)
        await until(lambda: entity.tonic.noise.current_fragments(), 180)
        print('Chat and GEN completed', flush=True)
        # A reproducible body pressure, then the ordinary real-time wake guards.
        # No direct call to wake() and no externally assigned body action.
        entity.tonic.bars._values['curiosity'] = 97
        await entity.tonic.tick_bars(0)
        await until(lambda: any(a['source'] == 'autonomous' and a['status'] == 'completed' for a in runtime.action_history), 240)
        await until(lambda: not runtime._cognition.locked(), 240)
        evidence['checks'].append({'autonomous_actions': list(runtime.action_history)})
        evidence['markers'] = entity.tonic.bars._somatic_markers
        evidence['fragments'] = entity.tonic.noise.current_fragments()
        evidence['state'] = runtime.state()
        evidence['model_calls'] = len(entity.client.calls)
        print('Autonomous body action completed', flush=True)
        child.terminate(); await asyncio.to_thread(child.wait, 10)
        await until(lambda: not platform.connected)
        child = subprocess.Popen([str(binary.resolve())], env=env, creationflags=subprocess.CREATE_NO_WINDOW)
        await until(lambda: platform.connected, 30)
        await asyncio.sleep(2)
        assert (await platform.action('wave'))['status'] == 'completed'
        evidence['checks'].append({'overlay_restart': 'reconnected_and_completed_wave'})
        runtime._stop.set(); await runner
        previous_token = platform.token
        platform = DesktopPlatform(area / 'desktop-session.json')
        entity = DesktopEntity(cfg)
        runtime = DesktopRuntime(entity, platform)
        runner = asyncio.create_task(runtime.run(launch=False))
        await until(lambda: platform.connected, 30)
        assert platform.token != previous_token
        assert PERSON in entity.tonic.bars._somatic_markers
        assert (await platform.action('wave'))['status'] == 'completed'
        evidence['checks'].append({'brain_restart': 'new_token_reconnected_marker_restored_and_wave_completed'})
        print('Overlay and brain restart checks completed', flush=True)
    finally:
        runtime._stop.set()
        await runner
        if child is not None:
            child.terminate(); await asyncio.to_thread(child.wait, 10)
        report.write_text(json.dumps(evidence, indent=2), encoding='utf-8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--binary', type=Path, default=Path('.git/desktop-bridge-build/debug/replicants-desktop.exe'))
    parser.add_argument('--report', type=Path, default=Path('.git/desktop-brain-probe.json'))
    args = parser.parse_args()
    asyncio.run(probe(args.binary, args.report))
