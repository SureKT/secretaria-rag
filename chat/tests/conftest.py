import sys
from pathlib import Path

# make `api` importable from chat/ root when running pytest
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
