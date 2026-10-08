@echo off
setlocal
cd /d "%~dp0"
echo.
echo === TruthLens setup ===
echo.

rem ---- find Python 3.10-3.12 -------------------------------------------------
set "PY="
for %%V in (3.12 3.11 3.10) do (
  if not defined PY (
    py -%%V -c "import sys" >nul 2>&1 && set "PY=py -%%V"
  )
)
if not defined PY (
  python -c "import sys; sys.exit(0 if (3,10)<=sys.version_info[:2]<=(3,12) else 1)" >nul 2>&1 && set "PY=python"
)
if not defined PY (
  echo [x] Python 3.10, 3.11 or 3.12 is required. Get it from https://www.python.org/downloads/
  echo     Tick "Add python.exe to PATH" during install, then run setup.bat again.
  exit /b 1
)
echo [ok] Using %PY%

where node >nul 2>&1
if errorlevel 1 (
  echo [x] Node.js 20 or newer is required. Get it from https://nodejs.org/
  exit /b 1
)
echo [ok] Node.js found

rem ---- backend ---------------------------------------------------------------
echo.
echo --- Installing the backend (this can take a few minutes) ---
if not exist "backend\.venv\Scripts\python.exe" (
  %PY% -m venv backend\.venv || exit /b 1
)
backend\.venv\Scripts\python -m pip install --upgrade pip --quiet
backend\.venv\Scripts\python -m pip install -r backend\requirements.txt || (
  echo [x] Installing Python packages failed. See the messages above.
  exit /b 1
)

if not exist "backend\.env" (
  copy "backend\.env.example" "backend\.env" >nul
  echo [!] Created backend\.env - open it and paste your GEMINI_API_KEY.
)

rem ---- frontend --------------------------------------------------------------
echo.
echo --- Building the web app ---
pushd frontend
call npm ci || call npm install || (popd & exit /b 1)
call npm run build || (popd & exit /b 1)
popd

echo.
echo === Setup complete ===
echo  1. Put your Gemini API key in backend\.env  (GEMINI_API_KEY=...)
echo  2. Start the app with:  run.bat
echo.
endlocal
