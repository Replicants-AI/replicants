"""Small packaged entry point for the desktop; independent of harness CLI setup."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import sys


def emit(value: dict):
    print(json.dumps(value, ensure_ascii=False), flush=True)


def main():
    # The native shell sends and decodes UTF-8 JSON. Windows redirected streams
    # otherwise inherit a legacy console code page, corrupting library names.
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(prog='replicants-brain')
    parser.add_argument('command', choices=['check', 'library', 'preferences', 'settings', 'pull', 'prepare', 'runtime-stop',
                                            'birth', 'wake', 'desktop', 'room-reader'])
    parser.add_argument('--file')
    parser.add_argument('--model')
    args = parser.parse_args()
    if args.command == 'room-reader':
        from replicants.desktop.room_sandbox import run
        run()
        return
    os.environ['REPLICANTS_BETA'] = '1'
    # Desktop configuration is local and separate from inherited deployment variables.
    for key in ('DATABASE_URL', 'REPLICANTS_DEPLOYMENT_MODE', 'REPLICANTS_INFERENCE_PROVIDER',
                'REPLICANTS_INFERENCE_BASE_URL', 'REPLICANTS_TIME_SCALE', 'REPLICANTS_START_HOUR'):
        os.environ.pop(key, None)
    try:
        from replicants.desktop import settings, setup
        if args.command == 'library':
            from replicants.desktop.library import lives
            emit(lives())
        elif args.command == 'preferences':
            try:
                emit({'settings': settings.load()})
            except ValueError as exc:
                emit({'settings': settings.DEFAULTS, 'error': str(exc)})
        elif args.command == 'settings':
            raw = sys.stdin.read(32769)
            if len(raw) > 32768:
                raise ValueError('Settings are too large.')
            emit({'settings': settings.save(json.loads(raw))})
        elif args.command == 'check':
            emit(asyncio.run(setup.check()))
        elif args.command == 'prepare':
            emit({'stage': 'result', 'report': asyncio.run(setup.prepare(emit))})
        elif args.command == 'runtime-stop':
            from replicants.desktop import local_runtime
            emit({'stopped': local_runtime.stop()})
        elif args.command == 'pull':
            if not args.model:
                raise ValueError('Choose a model to download.')
            asyncio.run(setup.pull(args.model, emit))
        else:
            asyncio.run(_run(args))
    except (Exception, KeyboardInterrupt) as exc:
        emit({'error': str(exc)[:1000] or type(exc).__name__})
        raise SystemExit(1) from exc


async def _run(args):
    from replicants.desktop.setup import require_ready
    await require_ready()
    if args.command == 'birth':
        from replicants.desktop.life import birth
        await birth(headless=True)
    elif args.command == 'wake':
        if not args.file:
            raise ValueError('Choose a .replicant file.')
        from replicants.desktop.life import wake_file
        await wake_file(Path(args.file), headless=True)
    else:
        from replicants.desktop.runtime import run_desktop
        await run_desktop(headless=True)


if __name__ == '__main__':
    main()
