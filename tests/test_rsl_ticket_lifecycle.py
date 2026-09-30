from pathlib import Path


TICKETS = Path(__file__).parents[1] / "ALU_Gauntlet" / "cogs" / "tickets.py"
MAIN = Path(__file__).parents[1] / "ALU_Gauntlet" / "main.py"


def test_ticket_lifecycle_has_restart_safe_controls():
    text = TICKETS.read_text(encoding="utf-8")
    assert 'TicketActions(self,str(row["_id"]),closed=str(row.get("status"))=="closed")' in text
    assert 'label="Unclaim"' in text
    assert 'action=="unclaim"' in text
    assert 'label="Lock"' in text
    assert 'action=="lock"' in text
    assert 'event":"staff_note"' in text


def test_ticket_lifecycle_tracks_activity_and_first_response():
    text = TICKETS.read_text(encoding="utf-8")
    assert "async def on_message" in text
    assert '"last_activity_at":now' in text
    assert 'update["first_response_at"]=now' in text


def test_ticket_lifecycle_has_reopen_permissions_and_sla_controls():
    text = TICKETS.read_text(encoding="utf-8")
    assert 'RSL ticket reopened' in text
    assert 'reminder_sent_at' in text
    assert 'sla_alerted_at' in text
    assert 'sla_escalated' in text


def test_ticket_unique_active_index_exists():
    text = MAIN.read_text(encoding="utf-8")
    assert 'uniq_rsl_active_ticket_type' in text
