"""Runtime release identity for deployment and recovery verification."""
from pathlib import Path

_MARKER = Path(__file__).resolve().parents[1] / ".rsl-release-sha"


def current_release_revision() -> str:
    try:
        value = _MARKER.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        return "unknown"
    if not value or not __import__("re").fullmatch(r"[0-9a-fA-F]{40}", value):
        return "unknown"
    return value.lower()
