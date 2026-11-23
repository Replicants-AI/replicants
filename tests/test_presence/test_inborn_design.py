from copy import deepcopy
import json
from pathlib import Path

import pytest

from replicants.desktop.archive import ReplicantArchive, verify
from replicants.desktop.design import validate_design
from replicants.desktop.genome import conceive
from replicants.desktop.design import MASK, BODY_PIXELS


def test_design_is_inborn_and_immutable_across_archive_reopen(tmp_path):
    design = json.loads(Path('assets/inborn/sea-glass.json').read_text())
    genome = conceive('curious', '#68B7AE', design=design)
    original = deepcopy(genome['body_design'])
    design['pal']['A'] = '#FFFFFF'
    assert genome['body_design'] == original
    being = ReplicantArchive.create(genome, tmp_path / 'one.replicant', tmp_path / 'data')
    initial_bytes = being.genome_bytes
    being.checkpoint(); being.close()
    reopened = ReplicantArchive.open(being.path, being.data_home)
    try:
        assert reopened.genome['body_design'] == original
        assert verify(reopened.path)[1]['genome.yaml'] == initial_bytes
        assert all(e['kind'] != 'appearance_earned' for e in reopened.lineage)
    finally: reopened.close()


def test_design_rejects_a_hole_and_untrusted_color():
    design = json.loads(Path('assets/inborn/sea-glass.json').read_text())
    design['rows'][0] = '........'
    with pytest.raises(ValueError): validate_design(design)
    design['rows'][0] = '.AABBAA.'
    design['pal']['A'] = 'url(https://example.com)'
    with pytest.raises(ValueError): validate_design(design)


def per_pixel_design():
    keys = iter('ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789')
    colors = {}
    rows = []
    for row in MASK:
        cells = []
        for cell in row:
            if cell == '.':
                cells.append('.')
            else:
                key = next(keys)
                colors[key] = f'#{len(colors) * 3217:06X}'
                cells.append(key)
        rows.append(''.join(cells))
    return {'name': 'Each pixel its own color', 'rows': rows, 'pal': colors}


def test_every_pixel_can_have_its_own_color_in_the_archive(tmp_path):
    design = per_pixel_design()
    assert len(design['pal']) == BODY_PIXELS
    genome = conceive(design=design)
    being = ReplicantArchive.create(genome, tmp_path / 'pixels.replicant', tmp_path / 'data')
    being.checkpoint(); being.close()
    reopened = ReplicantArchive.open(being.path, being.data_home)
    try:
        assert reopened.genome['body_design'] == design
    finally:
        reopened.close()


@pytest.mark.asyncio
async def test_birth_packet_design_reaches_the_saved_genome(tmp_path, monkeypatch):
    from replicants.desktop import life
    monkeypatch.setenv('REPLICANTS_DATA_HOME', str(tmp_path / 'data'))
    design = per_pixel_design()
    errors = []

    class Platform:
        async def connect(self): pass
        async def disconnect(self): pass
        async def publish(self, kind, value): errors.append((kind, value))
        async def on_message(self, callback):
            # A rejected drawing must leave the birth flow available to retry.
            await callback({'type': 'control', 'payload': {'name': 'conceive', 'design': {}}})
            await callback({'type': 'control', 'payload': {
                'name': 'conceive', 'temperament': 'calm', 'gestation_seconds': 12, 'design': design}})

    class Runtime:
        def __init__(self, being, platform):
            assert being.genome['body_design'] == design
            assert being.genome['temperament']['preset'] == 'calm'
        async def run(self, **kwargs): pass

    monkeypatch.setattr(life, 'DesktopPlatform', Platform)
    monkeypatch.setattr(life, 'LivingReplicant', Runtime)
    output = tmp_path / 'birth.replicant'
    await life.birth(output=output, headless=True)
    assert errors and errors[0][0] == 'error'
    _, members = verify(output)
    import yaml
    assert yaml.safe_load(members['genome.yaml'])['body_design'] == design
