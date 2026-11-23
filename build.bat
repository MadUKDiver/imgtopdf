
@echo off
title imgtopdf - Build

echo.
echo =====================================
echo       imgtopdf v2.1 Windows Builder
echo =====================================
echo.

if not exist .venv (
    echo Creating Python virtual environment...
    python -m venv .venv
)

echo.
echo Installing dependencies...

.venv\Scripts\python.exe -m pip install --upgrade pip
if errorlevel 1 goto error

.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 goto error

echo.
echo Creating application icon...

.venv\Scripts\python.exe make_icon.py
if errorlevel 1 goto error

echo.
echo Building imgtopdf.exe...

.venv\Scripts\pyinstaller.exe ^
    --onefile ^
    --windowed ^
    --clean ^
    --collect-all img2pdf ^
    --icon=imgtopdf.ico ^
    --add-data "imgtopdf.ico;." ^
    --name imgtopdf ^
    imgtopdf.py

if errorlevel 1 goto error

echo.
echo =====================================
echo BUILD COMPLETED SUCCESSFULLY
echo =====================================
echo.
echo Executable:
echo dist\imgtopdf.exe
echo.
pause
exit /b 0

:error
echo.
echo BUILD FAILED!
echo Please check the error messages above.
pause
exit /b 1

