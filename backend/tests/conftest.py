import os
import sys
import tempfile
from pathlib import Path

# Isolate runtime data before the package reads CLIPAWESOME_DATA at import time.
os.environ.setdefault("CLIPAWESOME_DATA", tempfile.mkdtemp(prefix="clipawesome-test-"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
