#!/bin/bash

# Step 1: Create a virtual environment
echo "Creating virtual environment..."
python3 -m venv venv
if [ $? -ne 0 ]; then
    echo "Failed to create virtual environment."
    exit 1
fi
echo "Virtual environment created successfully."

# Step 2: Activate the virtual environment
echo "Activating virtual environment..."
source venv/bin/activate
if [ $? -ne 0 ]; then
    echo "Failed to activate virtual environment."
    exit 1
fi
echo "Virtual environment activated."

# Step 3: Install the required packages
echo "Installing dependencies from requirements.txt..."
pip install -r requirements.txt
if [ $? -ne 0 ]; then
    echo "Failed to install dependencies."
    exit 1
fi
echo "Dependencies installed successfully."

# Step 4: Run the application
echo "Starting the application..."
python server.py
if [ $? -ne 0 ]; then
    echo "Failed to start the application."
    exit 1
fi
echo "Application started successfully."
