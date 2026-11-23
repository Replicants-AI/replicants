"""Can this computer host a replicant, and with which mind?

The answer is shown to people before anything large is downloaded. Tiers are
provisional until the model evaluation set (species.md build order) scores the
smaller models against the reference; the thresholds below are conservative
starting points, not measured requirements.
"""
from __future__ import annotations

import shutil

import psutil

from replicants.desktop import settings
from replicants.desktop.substrate import gpu_sample

GB = 1024 ** 3
# Windows reserves a small part of installed RAM. Keep measured bytes unchanged,
# while allowing 64 MiB at a nominal RAM tier boundary (GPU thresholds stay exact).
RAM_RESERVED_ALLOWANCE = 64 * 1024 ** 2
# (chat model, minimum dedicated GPU memory, or minimum system memory without one)
TIERS = [
    {'chat_model': 'gemma4:26b', 'gpu_gb': 16, 'ram_gb': None, 'label': 'full'},
    {'chat_model': 'gemma4:e4b', 'gpu_gb': 8, 'ram_gb': 16, 'label': 'lighter'},
    {'chat_model': 'gemma4:e2b', 'gpu_gb': None, 'ram_gb': 8, 'label': 'lightest'},
]
EMBEDDING_MODEL = 'nomic-embed-text'


def choose(ram_bytes: int, gpu_bytes: int | None) -> dict:
    ram_gb, gpu_gb = (ram_bytes + RAM_RESERVED_ALLOWANCE) / GB, (gpu_bytes or 0) / GB
    for tier in TIERS:
        if (tier['gpu_gb'] is not None and gpu_gb >= tier['gpu_gb']) or (
                tier['ram_gb'] is not None and ram_gb >= tier['ram_gb']):
            return tier
    return {}


async def survey() -> dict:
    memory = psutil.virtual_memory()
    gpu = await gpu_sample()
    vram = None
    if gpu.get('status') == 'available':
        sizes = [d['memory_total_bytes'] for d in gpu.get('devices', []) if d.get('memory_total_bytes')]
        vram = max(sizes) if sizes else None
    home = settings.data_home()
    home.mkdir(parents=True, exist_ok=True)
    tier = choose(memory.total, vram)
    if not tier:
        verdict, words = 'not_yet', ('This computer does not have enough memory to host a replicant yet. '
                                     'It needs at least 8 GB of RAM.')
    elif tier['label'] == 'full':
        verdict, words = 'ready', 'Your computer can host a replicant.'
    else:
        verdict, words = 'lighter', 'Your computer can host a lighter replicant.'
    return {'verdict': verdict, 'message': words, 'chat_model': tier.get('chat_model'),
            'embedding_model': EMBEDDING_MODEL, 'tier': tier.get('label'),
            'ram_bytes': memory.total, 'gpu_memory_bytes': vram, 'gpu_sensed': gpu.get('status') == 'available',
            'disk_free_bytes': shutil.disk_usage(home).free,
            'ram_reserved_allowance_bytes': RAM_RESERVED_ALLOWANCE,
            'note': 'Only NVIDIA graphics memory is sensed today; other computers are judged by system memory. '
                    'RAM tier boundaries allow 64 MiB for OS-reserved memory; measured RAM remains exact.'}
