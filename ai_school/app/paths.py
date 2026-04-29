"""アプリパッケージ基準のパス（カレントディレクトリに依存しない）。"""
from __future__ import annotations

from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = str(APP_DIR / "templates")
