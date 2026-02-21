@echo off
echo ========================================
echo Lumina Studio EXE Builder
echo ========================================
echo.

echo IMPORTANT: Please close any running LuminaStudio.exe processes before continuing!
echo.
pause

REM Check if PyInstaller is installed
python -c "import PyInstaller" 2>nul
if errorlevel 1 (
    echo PyInstaller not found. Installing...
    pip install pyinstaller
    if errorlevel 1 (
        echo Failed to install PyInstaller
        pause
        exit /b 1
    )
)

echo Cleaning previous build...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

echo.
echo Building executable...
echo This may take several minutes...
echo.

pyinstaller lumina_studio.spec --clean

if errorlevel 1 (
    echo.
    echo ========================================
    echo Build FAILED!
    echo ========================================
    echo.
    echo Common causes:
    echo - LuminaStudio.exe is still running (close it and try again)
    echo - Files in dist folder are open (close all files and try again)
    echo - Missing dependencies (run: pip install -r requirements.txt)
    echo.
    pause
    exit /b 1
)

echo.
echo ========================================
echo Build completed successfully!
echo ========================================
echo.
echo Executable location: dist\LuminaStudio\LuminaStudio.exe
echo.
echo Creating release package...

REM Create release folder
set RELEASE_NAME=LuminaStudio_v1.5.7_Windows
if exist %RELEASE_NAME% rmdir /s /q %RELEASE_NAME%
mkdir %RELEASE_NAME%

REM Copy executable and required files
xcopy /E /I /Y dist\LuminaStudio %RELEASE_NAME%

REM Copy test script to release folder
copy test_paths.py %RELEASE_NAME%\test_paths.py

REM Create a simple README for users
echo Lumina Studio v1.5.7 > %RELEASE_NAME%\README.txt
echo. >> %RELEASE_NAME%\README.txt
echo How to run: >> %RELEASE_NAME%\README.txt
echo 1. Double-click LuminaStudio.exe >> %RELEASE_NAME%\README.txt
echo 2. Wait for the web interface to open in your browser >> %RELEASE_NAME%\README.txt
echo 3. If browser doesn't open automatically, go to http://127.0.0.1:7860 >> %RELEASE_NAME%\README.txt
echo. >> %RELEASE_NAME%\README.txt
echo Troubleshooting: >> %RELEASE_NAME%\README.txt
echo - If you see errors, run test_paths.py to verify installation >> %RELEASE_NAME%\README.txt
echo - First launch may take 30-60 seconds to initialize >> %RELEASE_NAME%\README.txt
echo - Make sure icon.ico and lut-npy预设 folder are in the same directory >> %RELEASE_NAME%\README.txt
echo. >> %RELEASE_NAME%\README.txt
echo For more information, visit: >> %RELEASE_NAME%\README.txt
echo https://github.com/MOVIBALE/Lumina-Layers >> %RELEASE_NAME%\README.txt

echo.
echo ========================================
echo Release package created: %RELEASE_NAME%
echo ========================================
echo.
echo You can now distribute the %RELEASE_NAME% folder
echo.
pause
