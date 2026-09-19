@echo off
REM Quotex Signal Bot launcher — uses the rebuilt .venv interpreter
REM Security reminder: .env contains live credentials; never commit .env/session.json/.venv
REM Verified interpreter: .venv\Scripts\python.exe (pyquotex present)

set PYTHON=.venv\Scripts\python.exe
if not exist %PYTHON% (
    echo ERROR: .venv interpreter not found. Rebuild with: py -3 -m venv .venv
    echo Then install: .venv\Scripts\python.exe -m pip install --break-system-packages -r requirements.txt
    exit /b 1
)

REM Default: start bot (remove --mock for live mode after .env configured)
echo Starting Quotex Signal Bot...
echo Mode: %1 (pass --mock for simulated data, --login for auth, or leave blank for live with session)
echo.

%PYTHON% run.py %1 %2 %3 %4 %5

REM Note: .env and sessions/session.json contain real auth; .gitignore excludes them.
REM After successful login, session.json is cached; don't delete unless rotating credentials.
REM For full commands: see README.md (verified this session).
