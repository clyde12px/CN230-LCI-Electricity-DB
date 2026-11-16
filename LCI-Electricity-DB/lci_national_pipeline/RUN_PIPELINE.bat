@echo off
cd /d "%~dp0"
py scripts\run_pipeline.py
if errorlevel 1 (
  echo.
  echo PIPELINE FAILED - inspect outputs\reports\quality_report.json
) else (
  echo.
  echo PIPELINE QUALITY GATE PASSED - inspect outputs\reports\quality_report.json
)
pause
