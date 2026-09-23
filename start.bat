@echo off
setlocal
title Stock Bot
pushd "%~dp0"
if errorlevel 1 exit /b 1
where uv >nul 2>&1
if errorlevel 1 (
  echo Please install Python and uv as described in Chapter 5.
  pause
  exit /b 1
)
echo Starting Stock Bot. Keep this window open. Press Ctrl+C to stop.
uv run --locked stock-bot %*
if errorlevel 1 pause
popd
