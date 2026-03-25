@echo off
REM UFT Fog Engine Auto-Start on Boot
REM Finds the latest snapshot and resumes the engine

cd /d C:\Users\kevin\OneDrive\Documents\GitHub\UtilityFog-Fractal-TreeOpen

REM Find latest .npz snapshot
for /f "delims=" %%a in ('dir /b /o-d data\v070_gen*.npz 2^>nul') do (
    set LATEST=data\%%a
    goto :found
)
echo No snapshot found, starting fresh
python scripts/run_v070_engine.py
goto :end

:found
echo Resuming from %LATEST%
python scripts/run_v070_engine.py --resume %LATEST%

:end
