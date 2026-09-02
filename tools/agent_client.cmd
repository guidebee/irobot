@echo off
setlocal
set "SCRIPT_DIR=%~dp0"
where py >nul 2>nul
if %ERRORLEVEL%==0 (
    rem -3 makes py.exe use its own resolved interpreter directly instead
    rem of honoring the script's "#!/usr/bin/env python3" shebang, which
    rem on this machine resolves to a broken Microsoft Store stub
    py -3 "%SCRIPT_DIR%agent_client.py" %*
) else (
    python "%SCRIPT_DIR%agent_client.py" %*
)
