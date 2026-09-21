@echo off
chcp 65001 > nul
echo ========================================================
echo   사내 그룹웨어 AI 기안/품의서 초안 생성 도우미 실행기
echo ========================================================
echo.

:: 파이썬 설치 확인
python --version > nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python이 설치되어 있지 않거나 PATH에 등록되지 않았습니다.
    echo Python 3.10 이상을 먼저 설치해주세요.
    pause
    exit /b
)

:: 라이브러리 자동 점검 및 설치 (선택적)
echo [1/2] 필수 라이브러리 확인 중...
pip install -r requirements.txt

echo.
echo [2/2] Streamlit 웹 애플리케이션 시작 중...
echo 브라우저가 자동으로 열립니다. (기본 포트: 8501)
echo 프로그램을 종료하려면 이 창에서 Ctrl + C를 누르세요.
echo ========================================================
echo.

streamlit run app.py

pause
