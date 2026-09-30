"""Cross-cutting RSL assurance helpers.

These helpers consolidate security/privacy/evidence/anti-farming/readiness logic
without creating duplicate competition or support systems. They are advisory:
they never decide competition outcomes or automatically punish players.
"""
from __future__ import annotations

import hashlib
import re
import time
from collections import Counter
from typing import Any

SUSPICIOUS_EVENT_TYPES = {
    "AUTH_FAILURE", "RATE_LIMIT", "UPLOAD_REJECTED", "PERMISSION_DENIED",
    "ECONOMY_ANOMALY", "XP_ANOMALY", "MATCH_ANOMALY",
}

def redact_document(value: Any, *, secret_keys: set[str] | None = None) -> Any:
    secret_keys = secret_keys or {
        "token", "access_token", "refresh_token", "client_secret", "password",
        "session", "session_token", "oauth_state", "authorization", "cookie",
    }
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            if str(key).lower() in secret_keys or any(part in str(key).lower() for part in ("secret", "password")):
                out[str(key)] = "[REDACTED]"
            elif str(key).lower() in {"_id"}:
                out[str(key)] = str(item)
            else:
                out[str(key)] = redact_document(item, secret_keys=secret_keys)
        return out
    if isinstance(value, list):
        return [redact_document(item, secret_keys=secret_keys) for item in value[:200]]
    return value

def privacy_export_metadata(user_id: str, guild_id: str) -> dict[str, str]:
    return {
        "export_version": "1",
        "user_id": str(user_id),
        "guild_id": str(guild_id),
        "generated_at": str(int(time.time())),
        "note": "Secrets, authentication tokens, credentials, and private operational data are excluded.",
    }

def evidence_fingerprint(value: str) -> str:
    return hashlib.sha256(str(value).encode("utf-8", "ignore")).hexdigest()

def anti_farm_flags(events: list[dict[str, Any]], *, daily_cap: int = 25) -> list[str]:
    """Return advisory flags only; callers must send them to human review."""
    flags: list[str] = []
    if len(events) > daily_cap:
        flags.append("daily_activity_cap_exceeded")
    signatures = [str(e.get("signature") or e.get("message_hash") or "") for e in events]
    signatures = [x for x in signatures if x]
    repeated = max(Counter(signatures).values(), default=0)
    if repeated >= 5:
        flags.append("repeated_activity_pattern")
    if any(bool(e.get("self_awarded")) for e in events):
        flags.append("self_award_pattern")
    return flags

def anomaly_flags(*, win_rate: float | None = None, evidence_reuse: int = 0,
                  coin_gain: int = 0, abandoned_matches: int = 0) -> list[str]:
    flags = []
    if win_rate is not None and win_rate >= 0.98:
        flags.append("unusual_win_rate")
    if evidence_reuse >= 3:
        flags.append("reused_evidence")
    if coin_gain >= 10000:
        flags.append("unusual_coin_gain")
    if abandoned_matches >= 5:
        flags.append("repeated_abandonments")
    return flags

def readiness_check(checks: dict[str, bool | None]) -> dict[str, Any]:
    blocked = sorted(k for k, v in checks.items() if v is False)
    warnings = sorted(k for k, v in checks.items() if v is None)
    status = "BLOCKED" if blocked else ("WARNINGS" if warnings else "READY")
    return {"status": status, "blocked": blocked, "warnings": warnings, "ready": status == "READY"}

def public_status_snapshot(*, web_ok: bool, discord_ok: bool, database_ok: bool,
                           competition_ok: bool, auth_ok: bool, notifications_ok: bool,
                           release: str) -> dict[str, Any]:
    services = {
        "website": bool(web_ok), "discord": bool(discord_ok), "database": bool(database_ok),
        "competition": bool(competition_ok), "authentication": bool(auth_ok),
        "notifications": bool(notifications_ok),
    }
    return {
        "release": str(release),
        "services": services,
        "healthy": all(services.values()),
        "generated_at": int(time.time()),
    }

def performance_bucket(milliseconds: float) -> str:
    ms = float(milliseconds)
    if ms < 250: return "fast"
    if ms < 1000: return "normal"
    if ms < 2500: return "slow"
    return "critical"
