"""Static security contracts for the web authentication boundary."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AUTH = ROOT / "ALU_Gauntlet" / "web" / "auth.py"


def test_oauth_state_is_short_lived_and_single_use():
    src = AUTH.read_text(encoding="utf-8")
    assert "STATE_TTL = 10 * 60" in src
    assert "secrets.token_urlsafe(32)" in src
    assert "expiry = self.states.pop(state, None)" in src


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


def test_web_security_headers_and_private_cache_contracts():
    src = (ROOT / "ALU_Gauntlet" / "web" / "routes" / "core.py").read_text(encoding="utf-8")
    assert 'X-Content-Type-Options", "nosniff' in src
    assert 'X-Frame-Options", "DENY' in src
    assert 'Referrer-Policy", "strict-origin-when-cross-origin' in src
    assert 'Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=()' in src
    assert 'Content-Security-Policy", "default-src \'self\'' in src
    assert "frame-ancestors 'none'" in src
    assert 'Strict-Transport-Security", "max-age=31536000; includeSubDomains' in src
    assert 'Cache-Control", "no-store' in src


def test_web_upload_and_auth_boundaries_have_explicit_limits():
    src = (ROOT / "ALU_Gauntlet" / "web" / "server.py").read_text(encoding="utf-8")
    assert "client_max_size=15 * 1024 * 1024" in src
    assert "_rate_limit_auth_request" in src
    assert "_request_origin_allowed" in src
