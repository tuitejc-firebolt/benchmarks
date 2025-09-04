#!/bin/bash

# Firebolt Benchmarking Tool - Quick Setup Script
# This script automates the initial setup process

echo "🔥 Firebolt Benchmarking Tool - Quick Setup"
echo "=========================================="

# Check if Python is installed
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 is not installed. Please install Python 3.8+ first."
    exit 1
fi

PYTHON_VERSION=$(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')
echo "✅ Python $PYTHON_VERSION detected"

# Check if we're in the right directory
if [ ! -f "clients/python/requirements.txt" ]; then
    echo "❌ Please run this script from the benchmarks root directory"
    exit 1
fi

# Create virtual environment
echo "📦 Creating Python virtual environment..."
python3 -m venv venv

# Activate virtual environment
echo "🔌 Activating virtual environment..."
if [[ "$OSTYPE" == "msys" || "$OSTYPE" == "win32" ]]; then
    # Windows
    source venv/Scripts/activate
else
    # macOS/Linux
    source venv/bin/activate
fi

# Install dependencies
echo "⬇️  Installing Python dependencies..."
cd clients/python
pip install --upgrade pip
pip install -r requirements.txt

# Create credentials file from template
echo "📝 Setting up credentials file..."
cd ../../
mkdir -p config/credentials
if [ ! -f "config/credentials/credentials.json" ]; then
    if [ -f "config/credentials/sample_credentials.json" ]; then
        cp config/credentials/sample_credentials.json config/credentials/credentials.json
        echo "✅ Credentials template created at config/credentials/credentials.json"
        echo "⚠️  IMPORTANT: Edit this file with your actual database credentials!"
    else
        echo "⚠️  Sample credentials file not found. You'll need to create credentials.json manually."
    fi
else
    echo "✅ Credentials file already exists"
fi

echo ""
echo "🎉 Setup Complete!"
echo ""
echo "Next steps:"
echo "1. Edit config/credentials/credentials.json with your database credentials"
echo "2. Ensure your databases have the required test data loaded"
echo "3. Run the application:"
echo "   cd clients/python/src"
echo "   streamlit run main.py"
echo ""
echo "For detailed instructions, see INSTALLATION.md"
