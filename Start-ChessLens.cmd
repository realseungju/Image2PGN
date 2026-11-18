@echo off
setlocal
pushd "%~dp0" || exit /b 1
set "UV_PROJECT_ENVIRONMENT=%CD%\.chesslens-venv"
where uv.exe >nul 2>&1
if errorlevel 1 (
    echo Install uv, then open this launcher again:
    echo https://docs.astral.sh/uv/getting-started/installation/
    pause
    popd
    exit /b 1
)
uv.exe run --frozen --no-dev chesslens --port 8787 %*
set "chesslens_exit=%errorlevel%"
if not "%chesslens_exit%"=="0" pause
popd
exit /b %chesslens_exit%
