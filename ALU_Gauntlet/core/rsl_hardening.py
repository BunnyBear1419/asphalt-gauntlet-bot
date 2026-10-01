"""Shared RSL hardening primitives."""
from __future__ import annotations
import hashlib, hmac, time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Iterable

class MatchState(str, Enum):
    CREATED="CREATED"; ACCEPTED="ACCEPTED"; ACTIVE="ACTIVE"; SUBMITTED="SUBMITTED"; VERIFIED="VERIFIED"; SETTLED="SETTLED"; ABANDONED="ABANDONED"; EXPIRED="EXPIRED"; RECONCILIATION_REQUIRED="RECONCILIATION_REQUIRED"

_ALLOWED = {
 MatchState.CREATED:{MatchState.ACCEPTED,MatchState.EXPIRED,MatchState.ABANDONED},
 MatchState.ACCEPTED:{MatchState.ACTIVE,MatchState.EXPIRED,MatchState.ABANDONED},
 MatchState.ACTIVE:{MatchState.SUBMITTED,MatchState.EXPIRED,MatchState.ABANDONED},
 MatchState.SUBMITTED:{MatchState.VERIFIED,MatchState.EXPIRED,MatchState.RECONCILIATION_REQUIRED},
 MatchState.VERIFIED:{MatchState.SETTLED,MatchState.RECONCILIATION_REQUIRED},
 MatchState.SETTLED:set(),
 MatchState.ABANDONED:{MatchState.RECONCILIATION_REQUIRED},
 MatchState.EXPIRED:{MatchState.RECONCILIATION_REQUIRED},
 MatchState.RECONCILIATION_REQUIRED:{MatchState.VERIFIED,MatchState.SETTLED},
}
def can_transition(current, target): return MatchState(target) in _ALLOWED.get(MatchState(current),set())
def transition(current,target):
    c,t=MatchState(current),MatchState(target)
    if not can_transition(c,t): raise ValueError(f"Invalid RSL match transition: {c.value} -> {t.value}")
    return t

ADMIN_CAPABILITIES=frozenset({"system","players","moderation","tickets","gauntlet","tournaments","clubs","economy","media","audit"})
@dataclass(frozen=True)
class PermissionContext:
    user_id:str; guild_id:str; capabilities:frozenset[str]=frozenset(); administrator:bool=False
def has_capability(ctx,capability): return bool(ctx.administrator or capability in ctx.capabilities)
def require_capability(ctx,capability):
    if not has_capability(ctx,capability): raise PermissionError(f"RSL capability required: {capability}")

def proof_sha256(content:bytes)->str: return hashlib.sha256(content).hexdigest()
def proof_fingerprint(*,content:bytes,metadata:Iterable[str]=())->str:
    digest=hashlib.sha256(); digest.update(content)
    for value in metadata: digest.update(b"\0"); digest.update(str(value).encode("utf-8","replace"))
    return digest.hexdigest()
def same_proof(left,right): return hmac.compare_digest(str(left),str(right))

def public_profile(data:dict[str,Any],*,owner=False):
    allowed={"user_id","username","global_name","avatar","rsl_display_name","rsl_avatar_url","about","platform","driver_type","links","season_number","division","elo","career_wins","career_losses","xp","level","club_id","club_name"}
    if owner: allowed|={"timezone","notification_preferences","privacy_preferences"}
    return {k:data[k] for k in allowed if k in data}

def within_quiet_hours(hour,start,end):
    if start is None or end is None or start==end: return False
    hour,start,end=int(hour)%24,int(start)%24,int(end)%24
    return start<=hour<end if start<end else hour>=start or hour<end

@dataclass
class FixedWindowLimiter:
    limit:int; window_seconds:int; _buckets:dict[str,tuple[int,int]]|None=None
    def __post_init__(self):
        if self.limit<1 or self.window_seconds<1: raise ValueError("Rate-limit values must be positive")
        if self._buckets is None: self._buckets={}
    def allow(self,key,*,now=None):
        now=int(time.time() if now is None else now); bucket=now//self.window_seconds
        current,count=self._buckets.get(key,(bucket,0))
        if current!=bucket: current,count=bucket,0
        if count>=self.limit: self._buckets[key]=(current,count); return False
        self._buckets[key]=(current,count+1); return True

def reconcile_balance(*,ledger_balance:int,stored_balance:int):
    ledger_balance,stored_balance=int(ledger_balance),int(stored_balance); delta=ledger_balance-stored_balance
    return {"ok":delta==0,"ledger_balance":ledger_balance,"stored_balance":stored_balance,"delta":delta,"requires_approval":delta!=0,"action":"NONE" if delta==0 else "STAFF_APPROVAL_REQUIRED"}

def retention_due(timestamp,*,now=None,days=30):
    if days<0: raise ValueError("Retention days cannot be negative")
    return float(timestamp)<float(time.time() if now is None else now)-days*86400
def idempotency_key(*parts): return hashlib.sha256(":".join(map(str,parts)).encode()).hexdigest()
