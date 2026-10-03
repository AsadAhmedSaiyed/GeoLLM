"""GeoLLM harness. Makes lib/ importable so harness modules can use geollm_lib on the host."""
import sys
from pathlib import Path

_LIB = str(Path(__file__).resolve().parent.parent / "lib")
if _LIB not in sys.path:
    sys.path.insert(0, _LIB)