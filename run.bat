@echo off
REM One-command start (Windows). The React app is pre-built in frontend\dist.
cd /d "%~dp0backend"
python -m pip install -q -r requirements.txt
python app.py
