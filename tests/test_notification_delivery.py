from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
NOTIFICATIONS = ROOT / "ALU_Gauntlet" / "cogs" / "notifications.py"
MAIN = ROOT / "ALU_Gauntlet" / "main.py"


def test_notification_delivery_uses_the_database_unique_identity():
    source = NOTIFICATIONS.read_text(encoding="utf-8")
    main = MAIN.read_text(encoding="utf-8")

    assert '"event_id": str(event["id"])' in source
    assert '"user_id": user_id' in source
    assert '"lead_days": float(lead_days)' in source
    assert '"_id": delivery_id' not in source
    assert '"event_id", 1), ("user_id", 1), ("lead_days", 1)' in main
    assert 'name="uniq_notification_delivery"' in main


def test_failed_notification_delivery_is_retryable():
    source = NOTIFICATIONS.read_text(encoding="utf-8")

    assert 'await self.bot.db.notification_deliveries.delete_one(delivery_filter)' in source
    assert '{"$set": {"sent_at": now, "status": "sent"}}' in source
