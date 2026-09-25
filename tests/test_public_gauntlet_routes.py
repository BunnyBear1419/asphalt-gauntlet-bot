"""Regression checks for the public Gauntlet route/SEO contract."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "ALU_Gauntlet" / "web" / "server.py"


def test_public_gauntlet_routes_are_registered():
    server = SERVER.read_text(encoding="utf-8")
    expected = (
        '/gauntlet/registration',
        '/gauntlet/defense',
        '/gauntlet/matches',
        '/gauntlet/leaderboard',
        '/gauntlet/references',
    )
    for route in expected:
        assert f'add_get("{route}"' in server


def test_public_gauntlet_pages_have_search_descriptions():
    server = SERVER.read_text(encoding="utf-8")
    expected = (
        '"gauntlet-registration.html":',
        '"gauntlet-defense.html":',
        '"gauntlet-matches.html":',
        '"gauntlet-leaderboard.html":',
        '"gauntlet-references.html":',
    )
    for page in expected:
        assert page in server
