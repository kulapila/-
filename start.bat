@echo off
cd /d d:\cc-test\survey_pipeline
taskkill //f //im python.exe 2>nul
echo Pulling latest data...
git pull
echo Starting viewer...
python -m src.viewer
pause
