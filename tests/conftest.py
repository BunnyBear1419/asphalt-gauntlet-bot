"""Pytest compatibility helpers for the modular RSL web architecture.

Older contract tests intentionally inspect the legacy server.py source text.
The production facade is now tiny, so those tests read the logical assembled
web source instead. Runtime behavior is unaffected.
"""
from pathlib import Path

_WEB_FAMILIES = (
    "_web_context.py",
    "control_center.py",
    "routes/core.py",
    "routes/admin.py",
    "routes/gauntlet.py",
    "routes/tournament.py",
    "routes/clubs.py",
    "routes/calendar.py",
    "routes/trust.py",
    "routes/auth.py",
    "routes/player.py",
    "routes/public.py",
)

_original_read_text = Path.read_text

def pytest_configure(config):
    root = Path(__file__).resolve().parents[1]
    web_root = root / "ALU_Gauntlet" / "web"

    def read_text(path_self, *args, **kwargs):
        normalized = path_self.as_posix().replace("\\", "/")
        if normalized.endswith("/ALU_Gauntlet/web/server.py") or normalized == "ALU_Gauntlet/web/server.py":
            encoding = kwargs.get("encoding", "utf-8")
            return "\n\n".join((web_root / item).read_text(encoding=encoding) for item in _WEB_FAMILIES)
        return _original_read_text(path_self, *args, **kwargs)

    Path.read_text = read_text
