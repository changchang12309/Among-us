# -*- mode: python ; coding: utf-8 -*-
# 太空狼人杀 v2.0.0 打包配置
# 入口改为 multiplayer.py（模式选择大厅），游戏进程由同一个 exe 通过 --game 参数复用。
# pictures/ 需要随包分发，供摩斯密码与身体扫描任务读取。


a = Analysis(
    ['multiplayer.py'],
    pathex=[],
    binaries=[],
    datas=[('pictures', 'pictures')],
    hiddenimports=['main_gui'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='太空狼人杀v2.0.0',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='太空狼人杀v2.0.0',
)
