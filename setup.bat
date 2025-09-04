@echo off
REM Firebolt Benchmarking Tool - Quick Setup Script for Windows
REM This script automates the initial setup process on Windows

echo 🔥 Firebolt Benchmarking Tool - Quick Setup
echo ==========================================

REM Check if Python is installed
python --version >nul 2>&1
if errorlevel 1 (
    echo ❌ Python is not installed. Please install Python 3.8+ first.
    pause
    exit /b 1
)

echo ✅ Python detected

REM Check if we're in the right directory
if not exist "clients\python\requirements.txt" (
    echo ❌ Please run this script from the benchmarks root directory
    pause
    exit /b 1
)

REM Create virtual environment
echo 📦 Creating Python virtual environment...
python -m venv venv

REM Activate virtual environment
echo 🔌 Activating virtual environment...
call venv\Scripts\activate.bat

REM Install dependencies
echo ⬇️ Installing Python dependencies...
cd clients\python
python -m pip install --upgrade pip
pip install -r requirements.txt

REM Create credentials file from template
echo 📝 Setting up credentials file...
cd ..\..\
if not exist "config\credentials" mkdir config\credentials
if not exist "config\credentials\credentials.json" (
    if exist "config\credentials\sample_credentials.json" (
        copy config\credentials\sample_credentials.json config\credentials\credentials.json
        echo ✅ Credentials template created at config\credentials\credentials.json
        echo ⚠️ IMPORTANT: Edit this file with your actual database credentials!
    ) else (
        echo ⚠️ Sample credentials file not found. You'll need to create credentials.json manually.
    )
) else (
    echo ✅ Credentials file already exists
)

echo.
echo 🎉 Setup Complete!
echo.
echo Next steps:
echo 1. Edit config\credentials\credentials.json with your database credentials
echo 2. Ensure your databases have the required test data loaded
echo 3. Run the application:
echo    cd clients\python\src
echo    streamlit run main.py
echo.
echo For detailed instructions, see INSTALLATION.md
pause
