"""Make the TCT_app package root importable (the app itself relies on being
run from the TCT_app directory, so tests do the same via sys.path)."""
import sys
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent.parent
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))
