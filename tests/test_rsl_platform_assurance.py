from ALU_Gauntlet.core.platform_assurance import (
    anti_farm_flags, anomaly_flags, evidence_fingerprint, performance_bucket,
    public_status_snapshot, readiness_check, redact_document,
)

def test_redaction_never_exports_secrets():
    data = redact_document({"user_id":"1","access_token":"abc","nested":{"client_secret":"x","name":"Driver"}})
    assert data["access_token"] == "[REDACTED]"
    assert data["nested"]["client_secret"] == "[REDACTED]"
    assert data["nested"]["name"] == "Driver"

def test_evidence_fingerprint_is_deterministic():
    assert evidence_fingerprint("same") == evidence_fingerprint("same")
    assert evidence_fingerprint("same") != evidence_fingerprint("different")

def test_antifarm_and_anomaly_flags_are_advisory():
    events = [{"signature":"same"} for _ in range(5)]
    assert "repeated_activity_pattern" in anti_farm_flags(events)
    assert "unusual_win_rate" in anomaly_flags(win_rate=0.99)
    assert "reused_evidence" in anomaly_flags(evidence_reuse=3)

def test_readiness_has_three_clear_states():
    assert readiness_check({"a":True,"b":True})["status"] == "READY"
    assert readiness_check({"a":True,"b":None})["status"] == "WARNINGS"
    assert readiness_check({"a":False,"b":True})["status"] == "BLOCKED"

def test_public_status_and_performance_buckets():
    snapshot = public_status_snapshot(web_ok=True, discord_ok=True, database_ok=True,
        competition_ok=True, auth_ok=True, notifications_ok=True, release="r1")
    assert snapshot["healthy"] is True
    assert performance_bucket(100) == "fast"
    assert performance_bucket(1500) == "slow"
