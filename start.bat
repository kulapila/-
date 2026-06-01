@echo off
cd /d d:\cc-test\survey_pipeline
taskkill //f //im python.exe 2>nul
echo Pulling latest data...
git pull
echo Starting viewer...
start http://127.0.0.1:8080
python -m src.viewer
pause
