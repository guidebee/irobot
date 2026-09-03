@echo off
setlocal
set "SCRIPT_DIR=%~dp0"
rem `python -m irobot_gym_ide.app` resolves the package relative to the
rem current working directory, not this script's location -- cd into the
rem repo root first (this script's own directory) so the launcher works
rem from anywhere, same pattern as tools\agent_client.cmd.
cd /d "%SCRIPT_DIR%"
where py >nul 2>nul
if %ERRORLEVEL%==0 (
    rem -3 makes py.exe use its own resolved interpreter directly instead
    rem of honoring any shebang, which on this machine resolves to a
    rem broken Microsoft Store stub -- see tools\agent_client.cmd
    py -3 -m irobot_gym_ide.app %*
) else (
    python -m irobot_gym_ide.app %*
)
