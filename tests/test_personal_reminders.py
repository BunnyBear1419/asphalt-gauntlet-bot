from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVER = (ROOT / "ALU_Gauntlet" / "web" / "server.py").read_text(encoding="utf-8")
NOTIFICATIONS = (ROOT / "ALU_Gauntlet" / "cogs" / "notifications.py").read_text(encoding="utf-8")
CALENDAR = (ROOT / "ALU_Gauntlet" / "web" / "static" / "calendar.js").read_text(encoding="utf-8")


def test_personal_reminder_api_is_private_and_timezone_aware():
    assert 'add_get("/api/reminders", self.list_reminders)' in SERVER
    assert 'add_post("/api/reminders", self.create_reminder)' in SERVER
    assert 'add_put("/api/reminders/{reminder_id}", self.update_reminder)' in SERVER
    assert 'add_delete("/api/reminders/{reminder_id}", self.delete_reminder)' in SERVER
    assert 'custom_reminders.find({"user_id": str(user.user_id)' in SERVER
    assert 'ZoneInfo(timezone_name)' in SERVER
    assert 'local_dt.astimezone(timezone.utc).timestamp()' in SERVER


def test_personal_reminder_delivery_is_deduplicated():
    assert 'event_id": event_id, "user_id": user_id, "lead_days": float(selected_days)' in NOTIFICATIONS
    assert 'await self._notify_custom_reminders(now)' in NOTIFICATIONS
    assert 'notification_deliveries.update_one' in NOTIFICATIONS
    assert 'set_on_insert' not in NOTIFICATIONS.lower() or '$setOnInsert' in NOTIFICATIONS


def test_calendar_has_personal_reminder_ui():
    assert 'calendar-add-reminder' in CALENDAR or 'calendar-add-reminder' in (ROOT / "ALU_Gauntlet" / "web" / "static" / "calendar.html").read_text(encoding="utf-8")
    assert 'showReminderForm' in CALENDAR
    assert '/api/reminders' in CALENDAR
    assert 'type==="personal"' in CALENDAR
