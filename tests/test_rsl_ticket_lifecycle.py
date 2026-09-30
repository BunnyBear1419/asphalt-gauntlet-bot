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


def test_ticket_staff_transfer_workflow_exists():
    text=(Path(__file__).parents[1] / "ALU_Gauntlet" / "cogs" / "tickets.py").read_text(encoding="utf-8")
    assert 'label="Transfer"' in text
    assert 'action=="transfer"' in text
    assert 'is_staff(target,settings["staff_role_ids"])' in text
    assert '"transferred"' in text


def test_ticket_owner_can_rate_closed_ticket_once():
    text=(Path(__file__).parents[1] / "ALU_Gauntlet" / "cogs" / "tickets.py").read_text(encoding="utf-8")
    assert 'if action!="rating"' in text
    assert 'custom_id=f"rsl:ticket:rating:{self.ticket_id}"' in text
    assert 'You have already rated this ticket.' in text


def test_ticket_admin_queue_actions_and_transcript_are_wired():
    root=Path(__file__).parents[1]
    server=(root/"ALU_Gauntlet"/"web"/"server.py").read_text(encoding="utf-8")
    page=(root/"ALU_Gauntlet"/"web"/"static"/"admin.html").read_text(encoding="utf-8")
    assert 'async def admin_ticket_transcript' in server
    assert '/api/admin/tickets/transcript' in server
    assert 'ticketAction' in page
    assert 'downloadTicketTranscript' in page
    assert 'data-ticket-action' in page
    assert 'data-ticket-transcript' in page
    assert 'ticket-post-panel' in page


def test_ticket_webhook_validation_is_https_only():
    server=(Path(__file__).parents[1] / "ALU_Gauntlet" / "web" / "server.py").read_text(encoding="utf-8")
    assert 'parsed.scheme != "https"' in server
    assert 'Integration webhook must be a public HTTPS endpoint.' in server


def test_ticket_support_hours_are_wired():
    root=Path(__file__).parents[1]
    cog=(root/"ALU_Gauntlet"/"cogs"/"tickets.py").read_text(encoding="utf-8")
    server=(root/"ALU_Gauntlet"/"web"/"server.py").read_text(encoding="utf-8")
    page=(root/"ALU_Gauntlet"/"web"/"static"/"admin.html").read_text(encoding="utf-8")
    assert 'def support_elapsed_seconds' in cog
    assert 'support_hours_enabled' in cog
    assert 'support_hours_timezone' in cog
    assert 'support_hours_days' in cog
    assert 'response_age=support_elapsed_seconds' in cog
    assert 'inactivity_age=support_elapsed_seconds' in cog
    assert 'support_hours_enabled' in server
    assert 'ticket-support-hours-enabled' in page
    assert 'ticket-support-timezone' in page
    assert 'ticket-support-days' in page


def test_ticket_orphan_recovery_is_wired():
    root=Path(__file__).parents[1]
    cog=(root/"ALU_Gauntlet"/"cogs"/"tickets.py").read_text(encoding="utf-8")
    server=(root/"ALU_Gauntlet"/"web"/"server.py").read_text(encoding="utf-8")
    page=(root/"ALU_Gauntlet"/"web"/"static"/"admin.html").read_text(encoding="utf-8")
    assert 'status":"orphaned"' in cog
    assert 'recovery_status":"channel_missing"' in cog
    assert 'async def recover' in cog
    assert 'action == "recover"' in server
    assert 'value="orphaned"' in page
    assert 'action=status==="orphaned"?"recover"' in page


def test_ticket_auto_assignment_is_wired():
    root=Path(__file__).parents[1]
    cog=(root/"ALU_Gauntlet"/"cogs"/"tickets.py").read_text(encoding="utf-8")
    server=(root/"ALU_Gauntlet"/"web"/"server.py").read_text(encoding="utf-8")
    page=(root/"ALU_Gauntlet"/"web"/"static"/"admin.html").read_text(encoding="utf-8")
    assert 'async def choose_auto_assignee' in cog
    assert 'auto_assigned' in cog
    assert 'auto_assign_enabled' in cog
    assert 'ticket-auto-assign' in page
    assert 'auto_assign_enabled' in server


def test_ticket_alerts_use_atomic_deduplication_and_claimed_staff_mention():
    root=Path(__file__).parents[1]
    cog=(root/"ALU_Gauntlet"/"cogs"/"tickets.py").read_text(encoding="utf-8")
    assert '"reminder_sent_at":None' in cog
    assert '"sla_alerted_at":None' in cog
    assert 'f"🚨 Staff alert:' in cog
    assert '"sla_alerted_at":None},{"$set"' in cog
    assert '"reminder_sent_at":None},{"$set"' in cog


def test_ticket_notification_pipeline_is_idempotent_and_player_preference_wired():
    root=Path(__file__).parents[1]
    cog=(root/"ALU_Gauntlet"/"cogs"/"tickets.py").read_text(encoding="utf-8")
    main=(root/"ALU_Gauntlet"/"main.py").read_text(encoding="utf-8")
    server=(root/"ALU_Gauntlet"/"web"/"server.py").read_text(encoding="utf-8")
    page=(root/"ALU_Gauntlet"/"web"/"static"/"admin.html").read_text(encoding="utf-8")
    assert 'async def notify_ticket' in cog
    assert 'rsl_ticket_notifications' in cog
    assert 'uniq_rsl_ticket_notification_event' in main
    assert 'notify_player_dm' in cog and 'notify_player_dm' in server and 'notify_player_dm' in page
    assert 'ticket.sla_escalated' in cog and 'ticket.closed' in cog and 'ticket.reopened' in cog
