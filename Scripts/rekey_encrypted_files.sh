#!/bin/bash
#
# !!! EXPERIMENTAL !!!
#
# Re-keys or decrypts WilmerAI encrypted discussion files.
#
# Usage:
#   Re-key:   ./rekey_encrypted_files.sh --user myuser --api-key OLD_KEY --new-api-key NEW_KEY
#   Decrypt:  ./rekey_encrypted_files.sh --user myuser --api-key OLD_KEY
#
# This script activates the project's virtual environment so that the
# cryptography library (and all other dependencies) are available without
# a separate install.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Locate the virtual environment
if [ -d "$PROJECT_ROOT/venv" ]; then
    VENV_DIR="$PROJECT_ROOT/venv"
elif [ -d "$PROJECT_ROOT/.venv" ]; then
    VENV_DIR="$PROJECT_ROOT/.venv"
elif [ -d "$PROJECT_ROOT/.venv1" ]; then
    VENV_DIR="$PROJECT_ROOT/.venv1"
else
    echo "Error: No virtual environment found (checked venv, .venv, .venv1)."
    echo "Run the main WilmerAI setup script first to create the virtual environment."
    exit 1
fi

echo "Using virtual environment: $VENV_DIR"
source "$VENV_DIR/bin/activate"

python3 "$SCRIPT_DIR/rekey_encrypted_files.py" "$@"
