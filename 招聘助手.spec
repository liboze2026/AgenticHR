# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['C:\\bzli\\boss_feishu\\launcher.py'],
    pathex=[],
    binaries=[],
    datas=[('C:\\bzli\\boss_feishu\\frontend\\dist', 'frontend/dist'), ('C:\\bzli\\boss_feishu\\app', 'app')],
    hiddenimports=['app.config', 'app.database', 'app.main', 'app.adapters.ai_provider', 'app.adapters.email_receiver', 'app.adapters.email_sender', 'app.adapters.feishu', 'app.adapters.feishu_ws', 'app.adapters.tencent_meeting_web', 'app.adapters.boss.base', 'app.adapters.boss.playwright_adapter', 'app.modules.ai_evaluation.router', 'app.modules.ai_evaluation.schemas', 'app.modules.ai_evaluation.service', 'app.modules.auth.deps', 'app.modules.auth.models', 'app.modules.auth.router', 'app.modules.auth.service', 'app.modules.boss_automation.router', 'app.modules.boss_automation.schemas', 'app.modules.boss_automation.service', 'app.modules.feishu_bot.command_handler', 'app.modules.feishu_bot.router', 'app.modules.feishu_bot.schemas', 'app.modules.meeting.account_pool', 'app.modules.meeting.router', 'app.modules.notification.models', 'app.modules.notification.router', 'app.modules.notification.schemas', 'app.modules.notification.service', 'app.modules.notification.templates', 'app.modules.resume.models', 'app.modules.resume.pdf_parser', 'app.modules.resume.router', 'app.modules.resume.schemas', 'app.modules.resume.service', 'app.modules.resume._ai_parse_worker', 'app.modules.scheduling.models', 'app.modules.scheduling.router', 'app.modules.scheduling.schemas', 'app.modules.scheduling.service', 'app.modules.screening.models', 'app.modules.screening.router', 'app.modules.screening.schemas', 'app.modules.screening.service', 'uvicorn.logging', 'uvicorn.loops', 'uvicorn.loops.auto', 'uvicorn.protocols', 'uvicorn.protocols.http', 'uvicorn.protocols.http.auto', 'uvicorn.protocols.websockets', 'uvicorn.protocols.websockets.auto', 'uvicorn.lifespan', 'uvicorn.lifespan.on', 'sqlalchemy.dialects.sqlite', 'pydantic', 'pydantic_settings', 'multipart', 'multipart.multipart', 'bcrypt', 'jwt', 'PIL', 'PIL.Image', 'lark_oapi', 'PyPDF2', 'playwright', 'playwright.sync_api', 'playwright.async_api', 'httpx', 'httpcore', 'anyio', 'sniffio', 'certifi', 'starlette.responses', 'starlette.routing', 'starlette.middleware', 'starlette.middleware.cors'],
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
    name='招聘助手',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='NONE',
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='招聘助手',
)
