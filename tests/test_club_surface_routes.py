from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "ALU_Gauntlet" / "web"


def test_clubs_client_api_paths_have_registered_routes():
    script = (WEB / "static" / "clubs.js").read_text(encoding="utf-8")
    core = (WEB / "routes" / "core.py").read_text(encoding="utf-8")
    paths = sorted(set(re.findall(r'api\("([^"]+)"', script)))
    expected = {
        "/api/me",
        "/api/guilds",
        "/api/clubs",
        "/api/clubs/update",
        "/api/clubs/join",
        "/api/clubs/leave",
        "/api/clubs/member",
    }
    assert expected.issubset(set(paths))
    for path in expected:
        assert path in core, f"Club client route is not registered: {path}"


def test_club_create_controls_are_bound():
    page = (WEB / "static" / "clubs.html").read_text(encoding="utf-8")
    script = (WEB / "static" / "clubs.js").read_text(encoding="utf-8")
    for marker in (
        'id="open-create"',
        'id="close-create"',
        'id="club-form"',
        'id="add-create-club-link"',
        'id="club-image"',
    ):
        assert marker in page
    for marker in (
        '$("#open-create").onclick',
        '$("#close-create").onclick',
        '$("#club-form").onsubmit',
        'api("/api/clubs"',
    ):
        assert marker in script
