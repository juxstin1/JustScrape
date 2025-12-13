@echo off
REM Web Scraper CLI - Premium Interactive Experience

REM Get the directory where this batch file is located
set SCRAPER_DIR=%~dp0

REM Activate the virtual environment
call "%SCRAPER_DIR%venv\Scripts\activate.bat"

REM Run the premium interactive scraper
python "%SCRAPER_DIR%scrape_premium.py" %*
pause
