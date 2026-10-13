@echo off
rem Windows: first run creates the environment. Requires Python 3.10+ and ffmpeg on PATH.
cd /d "%~dp0"
if not exist .venv\Scripts\mw.exe (
  py -3 -m venv .venv || python -m venv .venv
  .venv\Scripts\python -m pip install --quiet -e .
  if not exist .env copy .env.example .env
)
.venv\Scripts\mw serve --port 8770
