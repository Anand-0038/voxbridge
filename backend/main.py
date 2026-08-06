"""
VoxBridge - Backend Package Entry Point

This file exists for package compatibility (e.g., `python -m backend`).
The actual FastAPI application is configured in app/main.py.

To run the server:
    cd backend
    uv run uvicorn app.main:app --reload
"""

import sys


def main():
    """Entry point that redirects to the correct uvicorn command."""
    print("VoxBridge Backend")
    print()
    print("Run the server with:")
    print("  cd backend")
    print("  uv run uvicorn app.main:app --reload")
    print()
    print("Or directly:")
    print("  uvicorn app.main:app --host 0.0.0.0 --port 8000")
    sys.exit(0)


if __name__ == "__main__":
    main()
