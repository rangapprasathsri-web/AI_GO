"""
Root entrypoint for FastAPI application.
Enables local execution with 'uvicorn main:app --reload'
and automatic detection by Vercel deployment tools.
"""
import sys
from pathlib import Path

root_dir = Path(__file__).resolve().parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from backend.api.main import app

__all__ = ["app"]
