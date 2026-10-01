from ALU_Gauntlet.core.rsl_ai_assistant import *
def test_assistant_is_read_only():
    req=AssistantRequest("1","How do tickets work?","tickets")
    validate_request(req)
    assert action_allowed("explain_rules")
    assert not action_allowed("settle_match")
def test_context_is_allowlisted():
    assert safe_context({"credits":5,"secret":"x"})=={"credits":5}
def test_unknown_topics_are_rejected():
    try: validate_request(AssistantRequest("1","change my result","settle_match"))
    except ValueError: pass
    else: assert False
