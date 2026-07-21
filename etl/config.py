"""Environment/config loading for the ETL pipeline."""
import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(REPO_ROOT / ".env")


_load_dotenv()

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://analytics:changeme@postgres:5432/claude_code_analytics",
)

DATA_DIR = Path(os.environ.get("ETL_DATA_DIR", REPO_ROOT / "data"))
EMPLOYEES_CSV = Path(os.environ.get("ETL_EMPLOYEES_CSV", DATA_DIR / "employees.csv"))
TELEMETRY_JSONL = Path(
    os.environ.get("ETL_TELEMETRY_JSONL", DATA_DIR / "telemetry_logs.jsonl")
)

# Rows accumulated per table before an executemany/execute_values flush.
BATCH_SIZE = int(os.environ.get("ETL_BATCH_SIZE", "2000"))

# How often (in processed source lines) to emit a progress log line.
LOG_EVERY_N_LINES = int(os.environ.get("ETL_LOG_EVERY_N_LINES", "1000"))
