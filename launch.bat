@echo off
title BMKG Station ME 48 - Weather Observation System
color 0A
cd /d "D:\Old\bmkg\OBS"

echo ============================================================
echo   Starting Station ME 48 (WAGB) Data Entry Software...
echo ============================================================
echo.

python -m streamlit run app.py

pause