# Build on the isolated Windows validation machine. The reader has its own bundle.
from pathlib import Path

root = Path(SPECPATH).parent
a = Analysis([str(root / 'replicants/desktop/room_reader.py')], pathex=[str(root)],
             binaries=[], datas=[], hiddenimports=[], hookspath=[], hooksconfig={},
             runtime_hooks=[], excludes=['tkinter', 'pytest', 'replicants', 'sitecustomize'])
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='replicants-room-reader',
          debug=False, bootloader_ignore_signals=False, strip=False, upx=False, console=True)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='reader')
