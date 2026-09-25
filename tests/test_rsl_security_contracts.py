"""Static security contracts for the web authentication boundary."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AUTH = ROOT / "ALU_Gauntlet" / "web" / "auth.py"


def test_oauth_state_is_short_lived_and_single_use():
    src = AUTH.read_text(encoding="utf-8")
    assert "STATE_TTL = 10 * 60" in src
    assert "secrets.token_urlsafe(32)" in src
    assert "state = self.states.pop(state, None)" in src


def test_session_tokens_are_random_hashed_and_http_only():
    src = AUTH.read_text(encoding="utf-8")
    assert "secrets.token_urlsafe(32)" in src
    assert "hashlib.sha256(token.encode" in src
    assert "httponly=True" in src
    assert 'samesite="Lax"' in src
    assert "secure=self.public_url.startswith" in src


def test_oauth_secrets_are_environment_backed():
    src = AUTH.read_text(encoding="utf-8")
    assert 'os.getenv("DISCORD_CLIENT_ID"' in src
    assert 'os.getenv("DISCORD_CLIENT_SECRET"' in src
    assert 'os.getenv("DISCORD_BOT_TOKEN"' not in src


def test_oauth_error_responses_do_not_echo_authorization_code_or_secret():
    src = AUTH.read_text(encoding="utf-8")
    assert 'text=f"Discord OAuth token exchange failed' in src
    assert "client_secret" not in src[src.find("raise web.HTTPServiceUnavailable"):src.find("raise web.HTTPServiceUnavailable")+500]
