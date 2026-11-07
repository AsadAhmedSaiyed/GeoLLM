"""GeoLLM harness. Makes lib/ importable so harness modules can use geollm_lib on the host."""
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_ENV_FILE = _ROOT / ".env"
def reload_dotenv() -> None:
    """Load or reload .env into os.environ so .env values take precedence over stale shell vars."""
    if _ENV_FILE.is_file():
        for _line in _ENV_FILE.read_text(encoding="utf-8", errors="replace").splitlines():
            _s = _line.strip()
            if not _s or _s.startswith("#") or "=" not in _s:
                continue
            if _s.startswith("export "):
                _s = _s[7:].strip()
            _k, _v = _s.split("=", 1)
            _k, _v = _k.strip(), _v.strip()
            if not _k or " " in _k:
                continue
            if len(_v) >= 2 and _v[0] == _v[-1] and _v[0] in ("'", '"'):
                _v = _v[1:-1]
            os.environ[_k] = _v


reload_dotenv()

_LIB = str(_ROOT / "lib")
if _LIB not in sys.path:
    sys.path.insert(0, _LIB)
