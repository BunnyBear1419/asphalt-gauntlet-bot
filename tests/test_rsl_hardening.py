from ALU_Gauntlet.core.rsl_hardening import *

def test_match_state_machine():
    assert can_transition(MatchState.CREATED,MatchState.ACCEPTED)
    assert can_transition(MatchState.ACCEPTED,MatchState.ACTIVE)
    assert can_transition(MatchState.ACTIVE,MatchState.SUBMITTED)
    assert can_transition(MatchState.SUBMITTED,MatchState.VERIFIED)
    assert can_transition(MatchState.VERIFIED,MatchState.SETTLED)
    assert not can_transition(MatchState.SETTLED,MatchState.ACTIVE)
    assert transition(MatchState.ACTIVE,MatchState.ABANDONED)==MatchState.ABANDONED

def test_reconciliation_requires_approval():
    assert reconcile_balance(ledger_balance=100,stored_balance=100)["action"]=="NONE"
    d=reconcile_balance(ledger_balance=105,stored_balance=100)
    assert d["requires_approval"] and d["action"]=="STAFF_APPROVAL_REQUIRED"

def test_permissions_are_fine_grained():
    ctx=PermissionContext("1","2",frozenset({"tickets"}))
    require_capability(ctx,"tickets")
    try: require_capability(ctx,"economy")
    except PermissionError: pass
    else: assert False

def test_profile_allowlist():
    raw={"user_id":"1","username":"Driver","timezone":"America/New_York","secret":"x"}
    assert public_profile(raw)=={"user_id":"1","username":"Driver"}
    assert public_profile(raw,owner=True)["timezone"]=="America/New_York"
    assert "secret" not in public_profile(raw,owner=True)

def test_proof_and_idempotency_are_deterministic():
    assert proof_fingerprint(content=b"abc",metadata=["race","1"])==proof_fingerprint(content=b"abc",metadata=["race","1"])
    assert idempotency_key("g","u","m")==idempotency_key("g","u","m")
    assert idempotency_key("g","u","m")!=idempotency_key("g","u","x")

def test_quiet_hours_and_limiter():
    assert within_quiet_hours(23,22,7) and within_quiet_hours(3,22,7)
    limiter=FixedWindowLimiter(2,60)
    assert limiter.allow("u",now=120) and limiter.allow("u",now=120)
    assert not limiter.allow("u",now=120)
    assert limiter.allow("u",now=180)

def test_retention():
    assert retention_due(0,now=31*86400,days=30)
    assert not retention_due(2*86400,now=31*86400,days=30)
