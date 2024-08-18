#!/bin/bash

CONFIG_DIR=""
USER=""

while [[ "$#" -gt 0 ]]; do
    case $1 in
        --ConfigDirectory) CONFIG_DIR="$2"; shift ;;
        --User) USER="$2"; shift ;;
        *) echo "Unknown parameter passed: $1"; exit 1 ;;
    esac
    shift
done

echo "Creating virtual environment..."
python3 -m venv venv
if [ $? -ne 0 ]; then
    echo "Failed to create virtual environment."
    exit 1
fi
echo "Virtual environment created successfully."

echo "Activating virtual environment..."
source venv/bin/activate
if [ $? -ne 0 ]; then
    echo "Failed to activate virtual environment."
    exit 1
fi
echo "Virtual environment activated."

echo "Installing dependencies from requirements.txt..."
pip install -r requirements.txt
if [ $? -ne 0 ]; then
    echo "Failed to install dependencies."
    exit 1
fi
echo "Dependencies installed successfully."

echo "Starting the application with ConfigDirectory=$CONFIG_DIR and User=$USER..."
python3 server.py "$CONFIG_DIR" "$USER"
if [ $? -ne 0 ]; then
    echo "Failed to start the application."
    exit 1
fi
echo "Application started successfully."
