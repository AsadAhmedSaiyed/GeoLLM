"""Single source of settings. Every value can be overridden by an environment variable."""
import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _f(name, default):
    return type(default)(os.environ.get(name, default))


@dataclass(frozen=True)
class Config:
    pi_command: str
    provider: str | None
    model: str | None
    idle_timeout_s: float
    total_timeout_s: float
    max_tool_calls: int
    sandbox_timeout_s: int
    sandbox_memory: str
    sandbox_cpus: float
    runs_dir: Path
    required_result_keys: tuple
    result_contract: str
    max_message_chars: int
    verbose: bool

    @property
    def tool_timeout_s(self) -> int:
        return int(os.environ.get("GEOLLM_TOOL_TIMEOUT_S", self.sandbox_timeout_s + 60))


def load_config() -> Config:
    keys = [k.strip() for k in os.environ.get("GEOLLM_REQUIRED_RESULT_KEYS", "").split(",") if k.strip()]
    return Config(
        pi_command=os.environ.get("PI_COMMAND", "pi"),
        provider=os.environ.get("GEOLLM_PROVIDER"),
        model=os.environ.get("GEOLLM_MODEL"),
        idle_timeout_s=_f("GEOLLM_PI_IDLE_TIMEOUT_S", 300.0),
        total_timeout_s=_f("GEOLLM_PI_TOTAL_TIMEOUT_S", 1800.0),
        max_tool_calls=_f("GEOLLM_MAX_TOOL_CALLS", 8),
        sandbox_timeout_s=_f("GEOLLM_SANDBOX_TIMEOUT_S", 180),
        sandbox_memory=os.environ.get("GEOLLM_SANDBOX_MEMORY", "2g"),
        sandbox_cpus=_f("GEOLLM_SANDBOX_CPUS", 2.0),
        runs_dir=Path(os.environ.get("GEOLLM_RUNS_DIR", ROOT / "runs")),
        required_result_keys=tuple(keys),
        result_contract=os.environ.get(
            "GEOLLM_RESULT_CONTRACT",
            "The script must save a summary of its computed results with geollm_lib's result-saving "
            "helper exactly once, and write all output files into the sandbox output directory.",
        ),
        max_message_chars=_f("GEOLLM_MAX_MESSAGE_CHARS", 6000),
        verbose=os.environ.get("GEOLLM_PI_VERBOSE", "1") != "0",
    )