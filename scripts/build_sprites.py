"""Compile the authored SVG rectangles to palette-indexed 8x7 anatomy and icons.

No raster tracing: every SVG cell is read exactly. Transparent eye holes in the
two silhouettes become an explicit eye layer, separate from the filled body.
"""
from pathlib import Path
import hashlib
import json
import struct
import xml.etree.ElementTree as ET
import zlib

ROOT = Path(__file__).resolve().parents[1]

def compile_sprites():
    presets = {}
    for path in sorted((ROOT / 'assets/replicants').glob('*.svg')):
        palette = ['transparent']
        grid = [[0] * 8 for _ in range(7)]
        svg = ET.parse(path).getroot()
        assert svg.attrib['viewBox'] == '0 0 80 70'
        for rect in svg:
            assert rect.tag.endswith('rect') and rect.attrib['width'] == rect.attrib['height'] == '10'
            x, y = int(rect.attrib['x']) // 10, int(rect.attrib['y']) // 10
            color = rect.attrib['fill'].upper()
            if color not in palette:
                palette.append(color)
            grid[y][x] = palette.index(color)
        presets[path.stem] = {'palette': palette, 'pixels': grid, 'source_sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    assert len(presets) == 20
    base = json.loads(json.dumps(presets['00-replicant-silhouette-light']))
    for x in (3, 5):
        base['pixels'][2][x] = 1
    def layer(design, cells):
        src = presets[design]
        grid = [[0] * 8 for _ in range(7)]
        for x, y in cells:
            grid[y][x] = src['pixels'][y][x]
        return {'palette': src['palette'], 'pixels': grid}
    eyes = [[0] * 8 for _ in range(7)]
    eyes[2][3] = eyes[2][5] = 1
    data = {'version': 1, 'width': 8, 'height': 7, 'layer_order': ['base', 'eyes', 'hair', 'headwear', 'face', 'top', 'legs', 'accessory'],
            'base': base, 'eyes': {'palette': ['transparent', '#1B1B22'], 'pixels': eyes}, 'presets': presets,
            'layers': {'glasses': {'slot': 'face', **layer('04-glasses', [(x, 2) for x in range(2, 7)])},
                       'beanie': {'slot': 'headwear', **layer('02-beanie', [(x, 0) for x in range(1, 7)])}}}
    dest = ROOT / 'desktop/src/sprites.json'
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(data, indent=2) + '\n', encoding='utf-8')
    # Dormant silhouette, exactly sourced, centered in a 32x32 tray/app icon.
    rgba = bytearray(32 * 32 * 4)
    dormant = presets['00-replicant-silhouette-black']
    for y, row in enumerate(dormant['pixels']):
        for x, index in enumerate(row):
            if not index:
                continue
            color = bytes.fromhex(dormant['palette'][index][1:]) + b'\xff'
            for dy in range(3):
                for dx in range(3):
                    pos = ((y * 3 + dy + 5) * 32 + x * 3 + dx + 4) * 4
                    rgba[pos:pos + 4] = color
    icons = ROOT / 'desktop/src-tauri/icons'
    icons.mkdir(parents=True, exist_ok=True)
    (icons / 'dormant.rgba').write_bytes(rgba)
    def chunk(kind, payload):
        return struct.pack('>I', len(payload)) + kind + payload + struct.pack('>I', zlib.crc32(kind + payload))
    scan = b''.join(b'\0' + rgba[y * 128:(y + 1) * 128] for y in range(32))
    png = b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 32, 32, 8, 6, 0, 0, 0)) + chunk(b'IDAT', zlib.compress(scan)) + chunk(b'IEND', b'')
    (icons / 'icon.png').write_bytes(png)
    (icons / 'icon.ico').write_bytes(struct.pack('<HHH', 0, 1, 1) + struct.pack('<BBBBHHII', 32, 32, 0, 0, 1, 32, len(png), 22) + png)
    return data

if __name__ == '__main__':
    result = compile_sprites()
    print(f'Compiled {len(result["presets"])} exact SVG grids, two appearance layers, and dormant icons.')
