"""Helpers for tests that inspect the refactored web route modules directly."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "ALU_Gauntlet" / "web"
ROUTE_DIR = WEB / "routes"

ROUTE_FILES = (
    "core.py",
    "admin.py",
    "gauntlet.py",
    "tournament.py",
    "clubs.py",
    "calendar.py",
    "trust.py",
    "auth.py",
    "player.py",
    "public.py",
)

def web_source(*route_names: str) -> str:
    """Read the real route-family source files; never synthesize server.py."""
    names = route_names or ROUTE_FILES
    return "\n".join(
        (ROUTE_DIR / (name if name.endswith(".py") else f"{name}.py")).read_text(encoding="utf-8")
        for name in names
    )
