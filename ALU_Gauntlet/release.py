"""Runtime release identity for deployment and recovery verification."""
from pathlib import Path

_MARKER = Path(__file__).resolve().parents[1] / ".rsl-release-sha"


def current_release_revision() -> str:
    try:
        value = _MARKER.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        return "unknown"
    return value if value else "unknown"
