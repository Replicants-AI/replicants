"""Temperament and body inheritance for a new being; never a persona."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
import random
import re

from replicants.config import EntityConfig
from replicants.desktop.archive import ReplicantArchive
from replicants.desktop.runtime import desktop_config
from replicants.desktop.design import validate_design

PRESETS = {
    'curious': {'social': 48, 'curiosity': 68, 'creative': 48, 'tension': 14, 'comfort': 50},
    'shy': {'social': 38, 'curiosity': 49, 'creative': 40, 'tension': 28, 'comfort': 66},
    'social': {'social': 72, 'curiosity': 54, 'creative': 46, 'tension': 12, 'comfort': 61},
    'calm': {'social': 40, 'curiosity': 46, 'creative': 34, 'tension': 7, 'comfort': 76},
}
PALETTES = {'pearl': '#E6E8EE', 'mint': '#C8E5D1', 'sand': '#E5D9B5', 'lavender': '#D5CDEA'}


def conceive(temperament='curious', palette='pearl', gestation_seconds=90, *, rng=None, design=None) -> dict:
    rng = rng or random.SystemRandom()
    if temperament == 'roll': temperament = rng.choice(list(PRESETS))
    if temperament not in PRESETS: raise ValueError('Unknown temperament.')
    color = PALETTES.get(palette, palette)
    if not re.fullmatch('#[0-9a-fA-F]{6}', color): raise ValueError('Use a named palette or a six-digit hex color.')
    seconds = float(gestation_seconds)
    if not 5 <= seconds <= 86400: raise ValueError('Gestation must be between 5 seconds and one day.')
    soma = deepcopy(desktop_config().harness.soma)
    for variable in soma['bars']['variables']:
        if variable['name'] in PRESETS[temperament]: variable['initial'] = PRESETS[temperament][variable['name']]
    genome = {'species_version': 1, 'temperament': {'preset': temperament,
            **{key: soma[key] for key in ('bars', 'coupling', 'impulses', 'conflicts')}},
        'gen': {'temperature': .88, 'fragment_density': 'sparse' if temperament in {'calm', 'shy'} else 'uneven'},
        'voice': {'verbosity': 'brief', 'register': 'plain', 'reserve': temperament in {'calm', 'shy'}},
        'base_palette': color.upper(), 'gestation_seconds': seconds, 'parents': [],
        # Inborn circadian phase in hours (reports/life-loop.md). Living with a person
        # entrains it; this is only where each being starts.
        'rhythm': {'chronotype_hours': round(rng.uniform(-2.0, 2.0), 2)}}
    if design is not None: genome['body_design'] = validate_design(design)
    return genome


@dataclass
class ArchiveConfig(EntityConfig):
    life_dir: str = ''

    def execution_workspace_dir(self): return self.life_dir
    def projects_path(self): return str(Path(self.life_dir) / 'projects.json')
    def self_model_path(self): return str(Path(self.life_dir) / 'self_model.json')
    def skills_dir(self): return str(Path(self.life_dir) / 'skills')
    def log_path(self): return str(Path(self.life_dir) / 'replicants.log')


def archive_config(being: ReplicantArchive) -> ArchiveConfig:
    config = desktop_config()
    genome = being.genome
    temperament = genome['temperament']
    config.name = 'replicant-' + being.id
    config.raw = {'name': config.name, 'desktop': {'temperament': temperament['preset'], 'display_name': being.manifest['name'] or ''}}
    from replicants.desktop.settings import apply
    apply(config)
    config.harness.memory.database_path = str(being.life / 'memory.db')
    config.harness.attachments.local_dir = str(being.life / 'attachments')
    config.harness.soma.update({key: deepcopy(temperament[key]) for key in ('bars', 'coupling', 'impulses', 'conflicts')})
    config.harness.soma['noise']['temperature'] = float(genome['gen']['temperature'])
    if genome['gen']['fragment_density'] == 'sparse':
        config.harness.soma['noise']['cycle_seconds'] = max(120, config.harness.soma['noise'].get('cycle_seconds', 60))
    config.harness.soma.setdefault('dreams', {})['enabled'] = True
    # Immutable tendencies, not facts about a past life.
    config.personality.backstory = ''
    config.personality.voice = dict(genome['voice'])
    return ArchiveConfig(**vars(config), life_dir=str(being.life))
