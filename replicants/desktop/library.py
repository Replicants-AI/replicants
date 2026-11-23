"""Host-local life discovery. Preview metadata is verified fully only when opened."""
import json
from pathlib import Path
import zipfile

from replicants.desktop.protocol import private_write
from replicants.desktop.settings import data_home


def _recent():
    try:
        value = json.loads((data_home() / 'desktop-library.json').read_text(encoding='utf-8'))
        return [p for p in value if isinstance(p, str)][:40] if isinstance(value, list) else []
    except (OSError, ValueError): return []


def remember(path: Path):
    value = str(path.resolve())
    private_write(data_home() / 'desktop-library.json', [value, *[p for p in _recent() if p != value]][:40])


def lives():
    paths = {Path(p) for p in _recent()}
    directory = data_home() / 'beings'
    if directory.is_dir():
        from itertools import islice
        paths.update(islice(directory.glob('*.replicant'), 200))
    result = []
    for path in paths:
        if not path.is_file() or path.suffix.lower() != '.replicant': continue
        try: stat = path.stat()
        except OSError: continue
        record = {'file': str(path.resolve()), 'name': path.stem, 'modified_at': stat.st_mtime,
                  'size_bytes': stat.st_size, 'preview': False}
        for candidate in [path, path.with_name(path.name + '.bak')]:
            try:
                with zipfile.ZipFile(candidate) as bundle:
                    info = bundle.getinfo('manifest.json')
                    if info.file_size > 1024 * 1024: continue
                    manifest = json.loads(bundle.read(info))
                if not isinstance(manifest, dict): continue
                record.update(name=str(manifest.get('name') or 'Unnamed Replicant')[:80],
                              id=str(manifest.get('id', ''))[:64], preview=True)
                break
            except (OSError, ValueError, KeyError, zipfile.BadZipFile, RuntimeError): continue
        result.append(record)
    return {'lives': sorted(result, key=lambda record: record['modified_at'], reverse=True)[:40]}
