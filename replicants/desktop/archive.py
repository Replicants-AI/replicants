"""Verified portable beings, hash-linked lineage and atomic checkpoints.

Format version 2 (reports/replicant-format.md, species.md §4.5) adds branches:
identity is the genesis hash forever; a branch is one continuous line of life
from genesis, named by the hash of its latest `reinitialized` entry (or by
genesis for the original line). The manifest records the branch and the head.
"""
from __future__ import annotations

from contextlib import closing
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import sqlite3
import stat
import tempfile
import time
import uuid
import zipfile

import yaml

from replicants.desktop.protocol import InstanceLock

VERSION = 2
SUPPORTED_VERSIONS = {1, 2}
# Framework defaults for genome blocks that older genomes do not carry. Genomes are
# never edited; the first wake records exactly which defaults this life runs on.
GENOME_DEFAULTS_VERSION = 1
GENOME_DEFAULTS = {'rhythm': {'chronotype_hours': 0.0}}
HASH = re.compile('[0-9a-f]{64}')
MAX_BYTES = 512 * 1024 * 1024
MAX_MEMBERS = 10000
ZERO_HASH = '0' * 64


class ArchiveError(ValueError):
    pass


def canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode('utf-8')


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def lineage_entry(prior: list[dict], kind: str, data: dict, at: float | None = None) -> dict:
    entry = {'index': len(prior), 'previous': prior[-1]['hash'] if prior else ZERO_HASH,
             'time': time.time() if at is None else at, 'kind': kind, 'data': data}
    return {**entry, 'hash': digest(canonical(entry))}


def branch_of(lineage: list[dict]) -> str:
    """The latest reinitialization starts the current branch; otherwise genesis does."""
    for entry in reversed(lineage):
        if entry['kind'] == 'reinitialized':
            return entry['hash']
    return lineage[0]['hash']


def _check_reinitialized(entry: dict) -> None:
    data = entry.get('data')
    if not isinstance(data, dict): raise ArchiveError('Invalid reinitialization.')
    seal = data.get('seal_id')
    if not isinstance(seal, str) or not 0 < len(seal) <= 200: raise ArchiveError('Reinitialization must name its seal.')
    if not isinstance(data.get('sealed_head'), str) or not HASH.fullmatch(data['sealed_head']):
        raise ArchiveError('Reinitialization must name its sealed head.')
    if entry['previous'] != data['sealed_head']:
        raise ArchiveError('A branch must begin immediately after its sealed head.')


def safe_member(name: str) -> bool:
    parts = name.split('/')
    reserved = {'CON', 'PRN', 'AUX', 'NUL'} | {f'{p}{i}' for p in ('COM', 'LPT') for i in range(1, 10)}
    if any(p in {'', '.', '..'} or p.endswith((' ', '.')) or any(c in p for c in '<>:"\\|?*')
           or p.split('.')[0].upper() in reserved for p in parts): return False
    return name in {'manifest.json', 'genome.yaml', 'lineage.jsonl'} or (parts[0] == 'life' and len(parts) > 1)


def verify(path: Path) -> tuple[dict, dict[str, bytes]]:
    """Check every byte and lineage link before extracting any member."""
    try:
        with zipfile.ZipFile(path) as archive:
            entries = archive.infolist()
            if len(entries) > MAX_MEMBERS or sum(i.file_size for i in entries) > MAX_BYTES:
                raise ArchiveError('Archive exceeds the local demo size limit.')
            names = [i.filename for i in entries]
            if len(set(n.casefold() for n in names)) != len(names): raise ArchiveError('Duplicate archive member.')
            if any(not safe_member(i.filename) or not safe_member(i.orig_filename) or stat.S_ISLNK(i.external_attr >> 16) or i.flag_bits & 1 for i in entries):
                raise ArchiveError('Unsafe archive member.')
            members = {i.filename: archive.read(i) for i in entries}
        manifest = json.loads(members.pop('manifest.json'))
        if not isinstance(manifest, dict): raise ArchiveError('Manifest must be a mapping.')
        version = manifest.get('format_version')
        if version not in SUPPORTED_VERSIONS: raise ArchiveError('Unsupported .replicant version.')
        root = manifest.get('integrity_root')
        unsigned = {key: value for key, value in manifest.items() if key != 'integrity_root'}
        if root != digest(canonical(unsigned)): raise ArchiveError('Manifest integrity check failed.')
        if manifest.get('members') != {name: digest(data) for name, data in members.items()}:
            raise ArchiveError('Life or genome integrity check failed.')
        genome = yaml.safe_load(members['genome.yaml'])
        if not isinstance(genome, dict): raise ArchiveError('Genome must be a mapping.')
        lineage = [json.loads(line) for line in members['lineage.jsonl'].splitlines() if line.strip()]
        if any(not isinstance(entry, dict) for entry in lineage): raise ArchiveError('Invalid lineage entry.')
        if not lineage or lineage[0]['kind'] != 'genesis': raise ArchiveError('Missing genesis.')
        previous = ZERO_HASH
        for index, entry in enumerate(lineage):
            if entry['index'] != index or entry['previous'] != previous: raise ArchiveError('Broken lineage link.')
            if entry['hash'] != digest(canonical({k: v for k, v in entry.items() if k != 'hash'})):
                raise ArchiveError('Lineage integrity check failed.')
            if index and entry['kind'] == 'genesis': raise ArchiveError('An identity cannot be conceived twice.')
            if entry['kind'] == 'reinitialized':
                if version < 2: raise ArchiveError('Branches require format version 2.')
                _check_reinitialized(entry)
            previous = entry['hash']
        if lineage[0]['data']['genome_sha256'] != digest(members['genome.yaml']):
            raise ArchiveError('Genome differs from conception.')
        if manifest['id'] != lineage[0]['hash'][:32] or not re.fullmatch('[0-9a-f]{32}', manifest['id']):
            raise ArchiveError('Identity does not match genesis.')
        if version >= 2:
            if manifest.get('branch') != branch_of(lineage): raise ArchiveError('Branch does not match lineage.')
            if manifest.get('head') != lineage[-1]['hash']: raise ArchiveError('Head does not match lineage.')
        return manifest, members
    except ArchiveError:
        raise
    except (OSError, ValueError, TypeError, KeyError, NotImplementedError, zipfile.BadZipFile, yaml.YAMLError) as exc:
        raise ArchiveError(f'Invalid .replicant file: {exc}') from exc


class ReplicantArchive:
    def __init__(self, path: Path, manifest: dict, members: dict[str, bytes], data_home: Path,
                 *, concurrent_branches: bool = False):
        self.path = path.resolve()
        self.manifest = manifest
        self.id = manifest['id']
        self.data_home = data_home
        self.genome_bytes = members['genome.yaml']
        self.genome = yaml.safe_load(self.genome_bytes)
        self.lineage = [json.loads(line) for line in members['lineage.jsonl'].splitlines() if line.strip()]
        self.branch = branch_of(self.lineage)
        self.locks = self._acquire_locks(concurrent_branches)
        self.lock = self.locks[0]
        self.work = data_home / 'working' / self.id / uuid.uuid4().hex
        self.recovered_from: Path | None = None
        self.closed = False
        try:
            self.work.mkdir(parents=True, exist_ok=False)
            for name, data in members.items():
                target = self.work.joinpath(*PurePosixPath(name).parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
            self.life.mkdir(exist_ok=True)
        except BaseException:
            self._release_locks()
            raise

    def _acquire_locks(self, concurrent_branches: bool) -> list:
        """One lock per branch always. By default, also one awake branch per identity.

        Copies of one branch can never wake together. Whether two branches of one
        being may live on one computer at once is host policy; the default is no.
        """
        locks = [InstanceLock(self.data_home / 'locks' / f'{self.id}.{self.branch[:16]}.lock')]
        if not concurrent_branches:
            try:
                locks.append(InstanceLock(self.data_home / 'locks' / (self.id + '.lock')))
            except RuntimeError as exc:
                locks[0].close()
                raise RuntimeError('Another branch of this Replicant is already awake on this computer.') from exc
        return locks

    def _release_locks(self):
        for lock in reversed(getattr(self, 'locks', [])):
            lock.close()

    def _settle_format(self) -> None:
        """Upgrade an older life in place by appending to it; never rewrite its history."""
        if self.manifest.get('format_version', 1) < VERSION:
            self.append('format_upgraded', {'from': self.manifest.get('format_version', 1), 'to': VERSION,
                                            'branch': self.branch})
            self.manifest['format_version'] = VERSION
        missing = {block: value for block, value in GENOME_DEFAULTS.items() if block not in self.genome}
        recorded = any(e['kind'] == 'genome_defaults' and e['data'].get('version') == GENOME_DEFAULTS_VERSION
                       for e in self.lineage)
        if missing and not recorded:
            self.append('genome_defaults', {'version': GENOME_DEFAULTS_VERSION, 'applied': missing})

    @property
    def effective_genome(self) -> dict:
        """The genome as written, plus the recorded framework defaults it was born without."""
        applied = {}
        for entry in self.lineage:
            if entry['kind'] == 'genome_defaults':
                applied.update(entry['data'].get('applied', {}))
        return {**applied, **self.genome}

    def begin_branch(self, seal_id: str, sealed_head: str) -> dict:
        """Start a new branch from a seal taken at this life's current head (species.md §4.2)."""
        if sealed_head != self.lineage[-1]['hash']:
            raise ArchiveError('A branch must begin immediately after its sealed head.')
        entry = self.append('reinitialized', {'seal_id': seal_id, 'sealed_head': sealed_head})
        old = self.branch
        self.branch = entry['hash']
        try:
            fresh = InstanceLock(self.data_home / 'locks' / f'{self.id}.{self.branch[:16]}.lock')
        except RuntimeError:
            self.branch = old
            raise
        self.locks[0].close()
        self.locks[0] = self.lock = fresh
        return entry

    @property
    def life(self) -> Path:
        return self.work / 'life'

    @property
    def backup(self) -> Path:
        return self.path.with_name(self.path.name + '.bak')

    @classmethod
    def open(cls, path: Path, data_home: Path | None = None, *, concurrent_branches: bool = False):
        from replicants.desktop.settings import data_home as host_data_home
        data_home = data_home or host_data_home()
        path = path.expanduser().resolve()
        recovered = None
        try:
            manifest, members = verify(path)
        except ArchiveError as original:
            recovered = path.with_name(path.name + '.bak')
            try: manifest, members = verify(recovered)
            except ArchiveError as backup:
                raise ArchiveError(f'{original} No valid last-good backup: {backup}') from original
        being = cls(path, manifest, members, data_home, concurrent_branches=concurrent_branches)
        being.recovered_from = recovered
        being._settle_format()
        return being

    @classmethod
    def create(cls, genome: dict, path: Path | None = None, data_home: Path | None = None):
        from replicants.desktop.settings import data_home as host_data_home
        data_home = data_home or host_data_home()
        genome_bytes = yaml.safe_dump(genome, sort_keys=True, allow_unicode=True).encode('utf-8')
        created = time.time()
        genesis = lineage_entry([], 'genesis', {'genome_sha256': digest(genome_bytes),
            'parents': [], 'host': 'local', 'nonce': uuid.uuid4().hex}, created)
        identity = genesis['hash'][:32]
        target = path or data_home / 'beings' / (identity + '.replicant')
        target = target.expanduser().resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        # Reserve without overwriting any existing being.
        with target.open('xb'): pass
        manifest = {'format_version': VERSION, 'id': identity, 'name': None, 'created': created,
                    'branch': genesis['hash'], 'head': genesis['hash']}
        being = None
        try:
            being = cls(target, manifest, {'genome.yaml': genome_bytes, 'lineage.jsonl': canonical(genesis) + b'\n'}, data_home)
            being.checkpoint()
            return being
        except BaseException:
            if being is not None: being.close()
            if target.exists() and target.stat().st_size == 0: target.unlink()
            raise

    def append(self, kind: str, data: dict, at: float | None = None):
        if self.closed: raise RuntimeError('Replicant archive is closed.')
        if kind == 'genesis': raise ArchiveError('Genesis already happened.')
        entry = lineage_entry(self.lineage, kind, data, at)
        with (self.work / 'lineage.jsonl').open('ab') as stream:
            stream.write(canonical(entry) + b'\n'); stream.flush(); os.fsync(stream.fileno())
        self.lineage.append(entry)
        return entry

    def snapshot(self):
        """Capture coherent bytes on the owning thread before an asynchronous write."""
        if self.closed: raise RuntimeError('Replicant archive is closed.')
        if (self.work / 'genome.yaml').read_bytes() != self.genome_bytes:
            raise ArchiveError('The conceived genome is immutable.')
        if [json.loads(line) for line in (self.work / 'lineage.jsonl').read_bytes().splitlines()] != self.lineage:
            raise ArchiveError('The append-only lineage was changed outside the host.')
        with tempfile.TemporaryDirectory(prefix='checkpoint-', dir=self.work) as snapshot_dir:
            paths = [(p.relative_to(self.work).as_posix(), p) for p in self.life.rglob('*')
                     if p.is_file() and not p.name.endswith(('-wal', '-shm', '-journal'))]
            paths += [('genome.yaml', self.work / 'genome.yaml'), ('lineage.jsonl', self.work / 'lineage.jsonl')]
            if any(not safe_member(name) or p.is_symlink() for name, p in paths): raise ArchiveError('Unsafe life member.')
            if len(paths) > MAX_MEMBERS or sum(p.stat().st_size for _, p in paths) > MAX_BYTES:
                raise ArchiveError('Life exceeds the local beta size limit.')
            members = {}
            for index, (name, path) in enumerate(sorted(paths)):
                if path.suffix == '.db':
                    snapshot_path = Path(snapshot_dir) / f'{index}.db'
                    with closing(sqlite3.connect(path)) as source, closing(sqlite3.connect(snapshot_path)) as dest:
                        source.backup(dest)
                    members[name] = snapshot_path.read_bytes()
                else:
                    members[name] = path.read_bytes()
            if sum(map(len, members.values())) > MAX_BYTES:
                raise ArchiveError('Life exceeds the local beta size limit.')
            manifest = {k: self.manifest[k] for k in ('id', 'name', 'created')}
            # The branch and head are read from the lineage bytes being saved, never from memory.
            saved = [json.loads(line) for line in members['lineage.jsonl'].splitlines() if line.strip()]
            manifest.update(format_version=VERSION, branch=branch_of(saved), head=saved[-1]['hash'])
            return manifest, members

    def checkpoint(self, hook=None, *, snapshot=None):
        """A killed writer leaves the previous full file or the new full file.

        The runtime captures snapshot() first, then performs compression and verification
        in one supervised worker. This writer never reads mutable working-life files.
        """
        if self.closed: raise RuntimeError('Replicant archive is closed.')
        manifest, members = snapshot if snapshot is not None else self.snapshot()
        manifest = {**manifest, 'members': {name: digest(content) for name, content in members.items()}}
        manifest['integrity_root'] = digest(canonical(manifest))
        stage = self.path.with_name(self.path.name + '.' + uuid.uuid4().hex + '.tmp')
        backup_stage = self.backup.with_name(self.backup.name + '.' + uuid.uuid4().hex + '.tmp')
        try:
            with stage.open('xb') as stream:
                if hook: hook('stage_created')
                with zipfile.ZipFile(stream, 'w', compression=zipfile.ZIP_DEFLATED) as bundle:
                    for name, content in sorted(members.items()): bundle.writestr(name, content)
                    bundle.writestr('manifest.json', canonical(manifest))
                stream.flush(); os.fsync(stream.fileno())
            if hook: hook('stage_complete')
            verify(stage)
            try:
                verify(self.path)
            except ArchiveError:
                pass  # Never replace a good backup with corrupt input.
            else:
                shutil.copyfile(self.path, backup_stage)
                with backup_stage.open('r+b') as stream: os.fsync(stream.fileno())
                os.replace(backup_stage, self.backup)
            if hook: hook('backup_complete')
            os.replace(stage, self.path)
            if hook: hook('replaced')
            # Naming can advance on the owning thread during compression.
            self.manifest.update(members=manifest['members'], integrity_root=manifest['integrity_root'])
        finally:
            stage.unlink(missing_ok=True)
            backup_stage.unlink(missing_ok=True)

    def close(self):
        if not self.closed:
            self.closed = True
            self._release_locks()
