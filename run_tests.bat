@echo off
REM Lumina Studio - Quick Test Runner
REM Run this script to execute the full test suite

echo ╔═══════════════════════════════════════════════════════════════════════════════╗
echo ║                    LUMINA STUDIO - QUICK TEST RUNNER                          ║
echo ╚═══════════════════════════════════════════════════════════════════════════════╝
echo.

REM Check if test images exist
if not exist "test_images\sample_logo.png" (
    echo [SETUP] Test images not found. Generating...
    python create_test_images.py
    if errorlevel 1 (
        echo [ERROR] Failed to generate test images
        pause
        exit /b 1
    )
    echo.
)

REM Run test suite
echo [RUN] Starting test suite...
echo.
python test_pipeline.py

REM Check result
if errorlevel 1 (
    echo.
    echo [FAILED] Some tests failed. Please review the output above.
    pause
    exit /b 1
) else (
    echo.
    echo [SUCCESS] All tests passed!
    pause
    exit /b 0
)
