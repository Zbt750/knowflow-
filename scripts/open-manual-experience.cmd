@echo off
cd /d "%~dp0.."
start "" "%ProgramFiles%\Google\Chrome\Application\chrome.exe" --no-first-run --no-default-browser-check --user-data-dir="%cd%\storage\manual-experience\naiwa-offline\chrome-profile" --new-window "http://127.0.0.1:5188/chat"
