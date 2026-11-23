# Build only on an isolated Windows runner. Never requires a developer checkout at runtime.
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata

root = Path(SPECPATH).parent
datas = collect_data_files('replicants')
datas += copy_metadata('replicants')
datas += [(str(root / 'configs' / 'default.yaml'), 'configs'),
          (str(root / 'configs' / 'noise_seeds'), 'configs/noise_seeds')]
a = Analysis([str(root / 'scripts' / 'desktop_backend.py')], pathex=[str(root)],
             binaries=[], datas=datas, hiddenimports=collect_submodules('replicants'),
             hookspath=[], hooksconfig={}, runtime_hooks=[], excludes=['tkinter', 'pytest', 'sitecustomize'])
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='replicants-brain',
          debug=False, bootloader_ignore_signals=False, strip=False, upx=False, console=True)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='replicants-brain')
