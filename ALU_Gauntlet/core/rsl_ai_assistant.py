"""Safe, read-only RSL assistant policy.

This is intentionally provider-neutral: it supplies the safety contract and
context filtering for a future AI provider without granting the model any
mutation authority.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any

READ_ONLY_TOPICS=frozenset({"rules","navigation","tickets","credits","xp","public_stats","diagnostics"})
FORBIDDEN_ACTIONS=frozenset({"settle_match","verify_result","approve_proof","award_credits","change_ranking","change_bracket","punish_player","edit_competition"})

@dataclass(frozen=True)
class AssistantRequest:
    user_id:str
    question:str
    topic:str

def validate_request(request:AssistantRequest)->None:
    if request.topic not in READ_ONLY_TOPICS:
        raise ValueError("RSL assistant only supports read-only topics.")
    if not request.question.strip():
        raise ValueError("A question is required.")

def safe_context(data:dict[str,Any])->dict[str,Any]:
    allowed={"rules","navigation","ticket_status","credits","xp","public_stats","diagnostics"}
    return {k:data[k] for k in allowed if k in data}

def action_allowed(action:str)->bool:
    return action not in FORBIDDEN_ACTIONS
