from pathlib import Path


TICKETS = Path(__file__).parents[1] / "ALU_Gauntlet" / "cogs" / "tickets.py"
MAIN = Path(__file__).parents[1] / "ALU_Gauntlet" / "main.py"


def test_ticket_lifecycle_has_restart_safe_controls():
    text = TICKETS.read_text(encoding="utf-8")
    assert 'locked=bool(row.get("locked",False))' in text
    assert 'label="Unclaim"' in text
    assert 'action=="unclaim"' in text
    assert 'label="Unlock" if self.locked else "Lock"' in text
    assert 'locked=not bool((row or {}).get("locked",False))' in text
    assert 'action=="reopen"' in text
    assert 'Unknown ticket action' in text
    assert 'label="Assign"' in text
    assert 'label="Members"' in text
    assert 'event":"member_added"' in text
    assert 'event":"member_removed"' in text
    assert 'event":"staff_note"' in text
    assert 'label="Tag"' in text
    assert 'label="Reply"' in text
    assert 'tag_updated' in text
    assert 'canned_response' in text
    assert 'canned_responses' in text
    assert 'label="Rating"' in text
    assert 'rating_submitted' in text
    assert 'fingerprint=hashlib.sha256' in text
    assert '$evidence_append' in text
    assert '"evidence":{"$each":evidence' in text
    assert 'recent_cutoff' in text
    assert 'recent_same' in text
    assert 'intake_snapshot' in text
    assert 'RSL Support Rating' in text


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


def test_ticket_analytics_and_dashboard_metrics():
    server=(Path(__file__).parents[1] / "ALU_Gauntlet" / "web" / "server.py").read_text(encoding="utf-8")
    page=(Path(__file__).parents[1] / "ALU_Gauntlet" / "web" / "static" / "admin.html").read_text(encoding="utf-8")
    assert '"avg_first_response_minutes"' in server
    assert '"avg_resolution_hours"' in server
    assert '"avg_rating"' in server
    assert '"staff_workload"' in server
    assert 'ticket-stat-response' in page
    assert 'ticket-stat-resolution' in page
    assert 'ticket-stat-rating' in page
    assert 'ticket-staff-workload' in page


def test_ticket_localization_and_integrations_are_wired():
    root=Path(__file__).parents[1]
    cog=(root/"ALU_Gauntlet"/"cogs"/"tickets.py").read_text(encoding="utf-8")
    server=(root/"ALU_Gauntlet"/"web"/"server.py").read_text(encoding="utf-8")
    page=(root/"ALU_Gauntlet"/"web"/"static"/"admin.html").read_text(encoding="utf-8")
    assert "_localized_type" in cog
    assert "interaction.locale" in cog or 'getattr(interaction,"locale"' in cog
    assert "ticket.opened" in cog
    assert '"webhook_url"' in server
    assert '"translations"' in server
    assert 'ticket-types-json' in page
    assert 'ticket-webhook' in page
    assert 'saveTicketSettings' in page
