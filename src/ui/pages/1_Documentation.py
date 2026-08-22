"""Streamlit multipage entry point for Technical Specification previews."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from src.ui.documentation import render_documentation_page

render_documentation_page()
