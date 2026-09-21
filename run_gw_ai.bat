@echo off
echo ========================================================
echo   Run gw_ai.py (AI Document Batch Processor)
echo ========================================================
echo.

python --version > nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python is not installed or not in PATH.
    pause
    exit /b
)

echo Which model would you like to use for data loading?
echo [1] GPT (OpenAI)
echo [2] Gemini (Google)
choice /c 12 /m "Select model: "
if errorlevel 2 goto use_gemini
if errorlevel 1 goto use_gpt

:use_gpt
set SELECTED_PROVIDER=openai
goto start_job

:use_gemini
set SELECTED_PROVIDER=gemini
goto start_job

:start_job
echo.
echo Starting background batch job with %SELECTED_PROVIDER%...
echo.

python gw_ai.py --provider %SELECTED_PROVIDER%

echo.
echo ========================================================
echo Process completed. Press any key to exit.
echo ========================================================
pause
