"""Regression coverage for Discord/web calendar notification parity."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLAYER = ROOT / "ALU_Gauntlet" / "cogs" / "player.py"
NOTIFICATIONS = ROOT / "ALU_Gauntlet" / "cogs" / "notifications.py"


def test_discord_notification_center_uses_shared_preferences():
    source = PLAYER.read_text(encoding="utf-8")
    assert "DiscordNotificationSettingsView" in source
    assert "DiscordNotificationSettingsButton" in source
    assert "notification_preferences" in source
    assert "gauntlet_notifications" in source
    assert "tournament_notifications" in source
    assert "gauntlet_lead_days" in source
    assert "tournament_lead_days" in source


def test_notification_scheduler_reads_the_same_preference_fields():
    source = NOTIFICATIONS.read_text(encoding="utf-8")
    assert "notification_preferences" in source
    assert "gauntlet_notifications" in source
    assert "tournament_notifications" in source
    assert "event_lead_days" in source
