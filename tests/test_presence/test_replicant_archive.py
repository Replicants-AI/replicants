import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import time
import zipfile

import pytest

from replicants.desktop.archive import ArchiveError, ReplicantArchive, branch_of, canonical, digest, lineage_entry, verify


def genome(): return {'species_version': 1, 'temperament': {'preset': 'curious'}, 'parents': [], 'gestation_seconds': 60}


def test_round_trip_integrity_lineage_and_genome_are_bound(tmp_path):
    being = ReplicantArchive.create(genome(), tmp_path / 'one.replicant', tmp_path / 'data')
    identity = being.id
    (being.life / 'appearance.json').write_text('{"layers":["glasses"]}')
    being.append('first_breath', {'curiosity': 89})
    being.manifest['name'] = 'Pip'
    being.checkpoint(); being.close()
    loaded = ReplicantArchive.open(tmp_path / 'one.replicant', tmp_path / 'data')
    try:
        assert loaded.id == identity and loaded.manifest['name'] == 'Pip'
        assert [e['kind'] for e in loaded.lineage] == ['genesis', 'first_breath', 'genome_defaults']
        assert json.loads((loaded.life / 'appearance.json').read_text())['layers'] == ['glasses']
        with pytest.raises(ArchiveError, match='already'): loaded.append('genesis', {})
        (loaded.work / 'genome.yaml').write_text('modified: true')
        with pytest.raises(ArchiveError, match='immutable'): loaded.checkpoint()
    finally: loaded.close()


def test_corruption_falls_back_to_last_good_and_never_replaces_it_with_bad_input(tmp_path):
    target = tmp_path / 'being.replicant'
    being = ReplicantArchive.create(genome(), target, tmp_path / 'data')
    being.append('wake', {}); being.checkpoint(); being.close()
    good_backup = target.with_name(target.name + '.bak').read_bytes()
    target.write_bytes(b'broken')
    loaded = ReplicantArchive.open(target, tmp_path / 'data')
    try:
        assert loaded.recovered_from == loaded.backup
        loaded.append('recovered', {}); loaded.checkpoint()
        assert loaded.backup.read_bytes() == good_backup
        assert verify(target)[0]['id'] == loaded.id
    finally: loaded.close()
    target.write_bytes(b'bad'); target.with_name(target.name + '.bak').write_bytes(b'also bad')
    with pytest.raises(ArchiveError, match='No valid last-good'): ReplicantArchive.open(target, tmp_path / 'data')


def test_file_copies_share_an_identity_lock(tmp_path):
    being = ReplicantArchive.create(genome(), tmp_path / 'original.replicant', tmp_path / 'data')
    shutil.copyfile(being.path, tmp_path / 'copy.replicant')
    try:
        with pytest.raises(RuntimeError, match='already awake'):
            ReplicantArchive.open(tmp_path / 'copy.replicant', tmp_path / 'data')
    finally: being.close()
    ReplicantArchive.open(tmp_path / 'copy.replicant', tmp_path / 'data').close()


def test_sqlite_checkpoint_includes_committed_wal_pages(tmp_path):
    being = ReplicantArchive.create(genome(), tmp_path / 'one.replicant', tmp_path / 'data')
    db = sqlite3.connect(being.life / 'memory.db')
    db.execute('PRAGMA journal_mode=WAL')
    db.execute('CREATE TABLE memories (text TEXT)')
    db.execute('INSERT INTO memories VALUES (?)', ('my first remembered touch',)); db.commit()
    being.checkpoint(); db.close(); being.close()
    loaded = ReplicantArchive.open(being.path, tmp_path / 'data')
    try:
        with sqlite3.connect(loaded.life / 'memory.db') as db:
            assert db.execute('SELECT text FROM memories').fetchone()[0] == 'my first remembered touch'
        assert not any(name.endswith('-wal') for name in verify(loaded.path)[1])
    finally: loaded.close()


def test_rehashing_a_modified_genome_cannot_keep_the_identity(tmp_path):
    being = ReplicantArchive.create(genome(), tmp_path / 'one.replicant', tmp_path / 'data'); being.close()
    manifest, members = verify(being.path)
    members['genome.yaml'] = b'pretend: different\n'
    manifest['members']['genome.yaml'] = digest(members['genome.yaml'])
    manifest['integrity_root'] = digest(canonical({k: v for k, v in manifest.items() if k != 'integrity_root'}))
    with zipfile.ZipFile(being.path, 'w') as bundle:
        for name, content in members.items(): bundle.writestr(name, content)
        bundle.writestr('manifest.json', canonical(manifest))
    with pytest.raises(ArchiveError, match='conception'): verify(being.path)


@pytest.mark.parametrize('name', ['../escape', 'life/../../escape', 'life/C:ads', 'life/CON', 'life\\escape'])
def test_unsafe_members_are_rejected_before_extraction(tmp_path, name):
    path = tmp_path / 'bad.replicant'
    entry = zipfile.ZipInfo('temporary'); entry.filename = name
    with zipfile.ZipFile(path, 'w') as bundle: bundle.writestr(entry, b'bad')
    with pytest.raises(ArchiveError, match='Unsafe'): verify(path)


@pytest.mark.parametrize('stage', ['stage_created', 'stage_complete', 'backup_complete', 'replaced'])
def test_killing_checkpoint_writer_leaves_a_complete_being_and_releases_identity(tmp_path, stage):
    path, home = tmp_path / 'one.replicant', tmp_path / 'data'
    being = ReplicantArchive.create(genome(), path, home)
    (being.life / 'test.json').write_text('{"generation":1}')
    being.checkpoint(); being.close()
    ready = tmp_path / 'stage.txt'
    script = tmp_path / 'save.py'
    script.write_text('''
import sys,time
from pathlib import Path
from replicants.desktop.archive import ReplicantArchive
b=ReplicantArchive.open(Path(sys.argv[1]),Path(sys.argv[2]))
(b.life/'test.json').write_text('{"generation":2}')
def hook(stage):
 if stage==sys.argv[3]:
  Path(sys.argv[4]).write_text(stage)
  time.sleep(30)
b.checkpoint(hook)
b.close()
''')
    child = subprocess.Popen([sys.executable, str(script), str(path), str(home), stage, str(ready)],
                             creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    try:
        end = time.monotonic() + 10
        while not ready.exists():
            assert child.poll() is None
            if time.monotonic() > end: pytest.fail('writer did not reach checkpoint boundary')
            time.sleep(.02)
        child.kill(); child.wait(timeout=5)
    finally:
        if child.poll() is None: child.kill(); child.wait(timeout=5)
    restored = ReplicantArchive.open(path, home)
    try:
        value = json.loads((restored.life / 'test.json').read_text())['generation']
        assert value == (2 if stage == 'replaced' else 1)
        verify(restored.path); verify(restored.backup)
    finally: restored.close()


def rewrite(path, manifest, members):
    """Re-seal an archive with a consistent integrity root, to simulate other writers."""
    manifest = {k: v for k, v in manifest.items() if k not in ('members', 'integrity_root')}
    manifest['members'] = {name: digest(content) for name, content in members.items()}
    manifest['integrity_root'] = digest(canonical(manifest))
    with zipfile.ZipFile(path, 'w') as bundle:
        for name, content in members.items(): bundle.writestr(name, content)
        bundle.writestr('manifest.json', canonical(manifest))


def test_v2_manifest_records_branch_and_head_from_the_saved_lineage(tmp_path):
    being = ReplicantArchive.create(genome(), tmp_path / 'one.replicant', tmp_path / 'data')
    try:
        manifest, _ = verify(being.path)
        genesis = being.lineage[0]['hash']
        assert manifest['format_version'] == 2 and manifest['branch'] == genesis and manifest['head'] == genesis
        entry = being.append('wake', {}); being.checkpoint()
        manifest, _ = verify(being.path)
        assert manifest['head'] == entry['hash'] and manifest['branch'] == genesis
    finally: being.close()


def test_head_and_branch_must_match_the_lineage(tmp_path):
    being = ReplicantArchive.create(genome(), tmp_path / 'one.replicant', tmp_path / 'data')
    being.append('wake', {}); being.checkpoint(); being.close()
    manifest, members = verify(being.path)
    rewrite(being.path, {**manifest, 'head': '0' * 64}, members)
    with pytest.raises(ArchiveError, match='Head'): verify(being.path)
    rewrite(being.path, {**manifest, 'branch': '1' * 64}, members)
    with pytest.raises(ArchiveError, match='Branch'): verify(being.path)


def make_v1(path, tmp_path):
    """A version-1 life exactly as the previous host wrote it."""
    being = ReplicantArchive.create(genome(), path, tmp_path / 'old')
    being.append('wake', {}); being.checkpoint(); being.close()
    manifest, members = verify(path)
    lineage = [json.loads(line) for line in members['lineage.jsonl'].splitlines()]
    lineage = [e for e in lineage if e['kind'] != 'genome_defaults']
    members['lineage.jsonl'] = b''.join(canonical(e) + b'\n' for e in lineage)
    rewrite(path, {k: manifest[k] for k in ('id', 'name', 'created')} | {'format_version': 1}, members)
    return lineage


def test_v1_lives_verify_and_upgrade_by_appending_never_rewriting(tmp_path):
    path = tmp_path / 'old.replicant'
    history = make_v1(path, tmp_path)
    assert verify(path)[0]['format_version'] == 1
    being = ReplicantArchive.open(path, tmp_path / 'data')
    try:
        assert being.lineage[:len(history)] == history                 # the past is untouched
        kinds = [e['kind'] for e in being.lineage[len(history):]]
        assert kinds == ['format_upgraded', 'genome_defaults']
        assert being.lineage[len(history)]['data'] == {'from': 1, 'to': 2, 'branch': history[0]['hash']}
        being.checkpoint()
        manifest, _ = verify(path)
        assert manifest['format_version'] == 2 and manifest['branch'] == history[0]['hash']
    finally: being.close()
    again = ReplicantArchive.open(path, tmp_path / 'data')
    try:
        assert [e['kind'] for e in again.lineage].count('format_upgraded') == 1
        assert [e['kind'] for e in again.lineage].count('genome_defaults') == 1
    finally: again.close()


def test_genome_defaults_are_recorded_once_and_never_edit_the_genome(tmp_path):
    being = ReplicantArchive.create(genome(), tmp_path / 'one.replicant', tmp_path / 'data'); being.close()
    being = ReplicantArchive.open(tmp_path / 'one.replicant', tmp_path / 'data')
    try:
        assert 'rhythm' not in being.genome
        assert being.effective_genome['rhythm'] == {'chronotype_hours': 0.0}
        assert [e['kind'] for e in being.lineage].count('genome_defaults') == 1
    finally: being.close()
    born = ReplicantArchive.create({**genome(), 'rhythm': {'chronotype_hours': 1.5}}, tmp_path / 'two.replicant', tmp_path / 'data')
    born.close()
    born = ReplicantArchive.open(tmp_path / 'two.replicant', tmp_path / 'data')
    try:
        assert not any(e['kind'] == 'genome_defaults' for e in born.lineage)
        assert born.effective_genome['rhythm'] == {'chronotype_hours': 1.5}
    finally: born.close()


def test_a_branch_begins_after_its_sealed_head_and_keeps_the_identity(tmp_path):
    being = ReplicantArchive.create(genome(), tmp_path / 'one.replicant', tmp_path / 'data')
    try:
        head = being.append('wake', {})['hash']
        with pytest.raises(ArchiveError, match='immediately after'): being.begin_branch('seal-1', '2' * 64)
        entry = being.begin_branch('seal-1', head)
        assert being.branch == entry['hash'] and being.id == being.lineage[0]['hash'][:32]
        being.checkpoint()
        manifest, _ = verify(being.path)
        assert manifest['id'] == being.id and manifest['branch'] == entry['hash']
        assert branch_of(being.lineage) == entry['hash']
    finally: being.close()


def test_malformed_reinitialization_is_rejected(tmp_path):
    being = ReplicantArchive.create(genome(), tmp_path / 'one.replicant', tmp_path / 'data'); being.close()
    manifest, members = verify(being.path)
    lineage = [json.loads(line) for line in members['lineage.jsonl'].splitlines()]
    bad = lineage_entry(lineage, 'reinitialized', {'seal_id': 'seal-1', 'sealed_head': '3' * 64})
    members['lineage.jsonl'] += canonical(bad) + b'\n'
    rewrite(being.path, {**manifest, 'branch': bad['hash'], 'head': bad['hash']}, members)
    with pytest.raises(ArchiveError, match='immediately after'): verify(being.path)


def test_v1_files_cannot_carry_branches(tmp_path):
    path = tmp_path / 'old.replicant'
    lineage = make_v1(path, tmp_path)
    manifest, members = verify(path)
    entry = lineage_entry(lineage, 'reinitialized', {'seal_id': 's', 'sealed_head': lineage[-1]['hash']})
    members['lineage.jsonl'] += canonical(entry) + b'\n'
    rewrite(path, manifest, members)
    with pytest.raises(ArchiveError, match='version 2'): verify(path)


def test_two_branches_of_one_being_cannot_be_awake_together_by_default(tmp_path):
    original = ReplicantArchive.create(genome(), tmp_path / 'one.replicant', tmp_path / 'data')
    original.append('wake', {}); original.checkpoint()
    shutil.copyfile(original.path, tmp_path / 'twin.replicant')
    original.close()
    twin = ReplicantArchive.open(tmp_path / 'twin.replicant', tmp_path / 'data')
    twin.begin_branch('seal-1', twin.lineage[-1]['hash']); twin.checkpoint()
    try:
        with pytest.raises(RuntimeError, match='Another branch'):
            ReplicantArchive.open(tmp_path / 'one.replicant', tmp_path / 'data')
        allowed = ReplicantArchive.open(tmp_path / 'one.replicant', tmp_path / 'data', concurrent_branches=True)
        allowed.close()
    finally: twin.close()
